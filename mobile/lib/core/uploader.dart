/// 手机端核心：把录音切成小片存到手机上，再按顺序传给电脑。
///
/// - 每 [AppSettings.chunkSec] 秒一片；没人说话的片只记一个“静音”标记，不存也不传音频
/// - 传成功才删；电脑没开、不在 WiFi、App 被杀，都只是晚点传，不会丢
library;

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'adpcm.dart';
import 'audio.dart';
import 'endpoints.dart';
import 'settings.dart';
import 'util.dart';

const int _bytesPerSec = kSampleRate * 2;

/// 一个待上传的片（信息都在文件名里：流_序号_开始毫秒_时长毫秒_类型）
class SpoolItem {
  SpoolItem(this.file, this.stream, this.seq, this.start, this.durMs, this.kind);
  final File file;
  final String stream;
  final int seq;
  final DateTime start;
  final int durMs;
  final String kind; // v = 有声音（PCM）；a = 有声音（ADPCM 压缩）；s = 静音；x = 停止标记

  bool get hasAudio => kind == 'v' || kind == 'a';

  static SpoolItem? parse(File f) {
    final name = f.uri.pathSegments.last;
    final m = RegExp(r'^(\d{8}_\d{6})_(\d{8})_(\d+)_(\d+)_([vasx])\.bin$').firstMatch(name);
    if (m == null) return null;
    return SpoolItem(f, m.group(1)!, int.parse(m.group(2)!),
        DateTime.fromMillisecondsSinceEpoch(int.parse(m.group(3)!)), int.parse(m.group(4)!), m.group(5)!);
  }
}

/// 录音 → 切片 → 写入暂存目录
class ChunkSpool {
  ChunkSpool(this.dir, this.settings, {DateTime Function()? now, this.onChunk})
      : now = now ?? DateTime.now;

  final Directory dir;
  final AppSettings settings;
  final DateTime Function() now;
  final void Function()? onChunk;

  String? stream;
  int _seq = 0;
  BytesBuilder _buf = BytesBuilder(copy: false);
  DateTime? _chunkStart;
  DateTime? _prevEnd;
  Segmenter? _det;
  int _framesAtStart = 0;
  int voicedChunks = 0;
  int silentChunks = 0;

  /// 为 true 时新切出来的片用 ADPCM 压缩（由外面根据“是不是在用移动网络”来设置）
  bool compress = false;

  bool get recording => stream != null;
  double get levelDb => recording ? (_det?.levelDb ?? -100) : -100;

  void start() {
    if (recording) return;
    dir.createSync(recursive: true);
    stream = fmtCompact(now());
    _seq = 0;
    _buf = BytesBuilder(copy: false);
    _chunkStart = null;
    _prevEnd = null;
    voicedChunks = 0;
    silentChunks = 0;
    _framesAtStart = 0;
    // 这里的检测器只用来判断“这一片里有没有声音”，真正的切句在电脑上做
    _det = Segmenter(now: now, onUtterance: (_) {}, marginDb: settings.vadMarginDb, minDb: -55);
  }

  void add(Uint8List pcm) {
    if (!recording || pcm.isEmpty) return;
    if (_chunkStart == null) {
      // 正常情况下紧接上一片；如果录音中断过（来电等），用真实时间
      final t = now().subtract(Duration(milliseconds: pcm.length * 1000 ~/ _bytesPerSec));
      final prev = _prevEnd;
      _chunkStart = prev != null && t.difference(prev).inMilliseconds.abs() < 2000 ? prev : t;
    }
    _det!
      ..marginDb = settings.vadMarginDb
      ..addBytes(pcm);
    _buf.add(pcm);
    if (_buf.length >= settings.chunkSec * _bytesPerSec) _cut();
  }

  void _cut() {
    final start = _chunkStart;
    if (start == null || _buf.isEmpty) return;
    var bytes = _buf.takeBytes();
    if (bytes.length.isOdd) bytes = Uint8List.sublistView(bytes, 0, bytes.length - 1);
    final durMs = bytes.length * 1000 ~/ _bytesPerSec;
    final frames = _det?.speechFrames ?? 0;
    final voiced = !settings.skipSilence ||
        // 这一片里至少有 2 帧（60 毫秒）声音；只有 1 帧多半是上一片末尾的余音
        frames - _framesAtStart >= 2;
    _framesAtStart = frames;
    final kind = !voiced ? 's' : (compress ? 'a' : 'v');
    final name = '${stream}_${_seq.toString().padLeft(8, '0')}_'
        '${start.millisecondsSinceEpoch}_${durMs}_$kind.bin';
    final tmp = File('${dir.path}/$name.tmp');
    tmp.writeAsBytesSync(
        kind == 's' ? const <int>[] : (kind == 'a' ? adpcmEncode(bytes) : bytes),
        flush: false);
    tmp.renameSync('${dir.path}/$name');
    voiced ? voicedChunks++ : silentChunks++;
    _seq++;
    _prevEnd = start.add(Duration(milliseconds: durMs));
    _chunkStart = null;
    _buf = BytesBuilder(copy: false);
    onChunk?.call();
  }

  /// 停止录音：把最后不满一片的也存下来，并写一个“停止”标记（电脑收到后做整场总复盘）
  void stop() {
    if (!recording) return;
    _cut();
    final name = '${stream}_${_seq.toString().padLeft(8, '0')}_'
        '${now().millisecondsSinceEpoch}_0_x.bin';
    File('${dir.path}/$name').writeAsBytesSync(const <int>[]);
    stream = null;
    _det = null;
    onChunk?.call();
  }
}

/// 把暂存目录里的片按顺序传给电脑
class Uploader {
  Uploader(this.dir, this.settings, {Endpoints? endpoints, this.canUpload, this.onChanged})
      : endpoints = endpoints ?? Endpoints(settings);

  final Directory dir;
  final AppSettings settings;
  final Endpoints endpoints;
  final Future<bool> Function()? canUpload;
  final void Function()? onChanged;

  bool _busy = false;
  Timer? _timer;
  int _fails = 0;
  DateTime? _retryAt;

  int pendingCount = 0;
  int pendingBytes = 0;
  int uploadedChunks = 0;
  DateTime? lastOk;
  String state = 'idle'; // idle / uploading / waiting_wifi / error / no_server
  String lastError = '';

  void startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) => kick());
  }

  void dispose() => _timer?.cancel();

  List<SpoolItem> pending() {
    if (!dir.existsSync()) return [];
    final items = <SpoolItem>[];
    for (final f in dir.listSync().whereType<File>()) {
      final it = SpoolItem.parse(f);
      if (it != null) items.add(it);
    }
    items.sort((a, b) {
      final c = a.stream.compareTo(b.stream);
      return c != 0 ? c : a.seq.compareTo(b.seq);
    });
    return items;
  }

  void _refresh(List<SpoolItem> items) {
    pendingCount = items.length;
    var n = 0;
    for (final it in items) {
      if (it.hasAudio) n += it.file.lengthSync();
    }
    pendingBytes = n;
  }

  void _set(String st, [String err = '']) {
    state = st;
    lastError = err;
    onChanged?.call();
  }

  /// 有新片或定时器触发时调用；[force] 用于用户手动点“立即重试”
  Future<void> kick({bool force = false}) async {
    if (_busy) return;
    if (force) _retryAt = null;
    _busy = true;
    try {
      var items = pending();
      _refresh(items);
      // 暂存超过上限：丢掉最老的（保住最新的）
      while (pendingBytes > settings.maxSpoolMb * 1024 * 1024 && items.isNotEmpty) {
        items.first.file.deleteSync();
        items = items.sublist(1);
        _refresh(items);
        lastError = '手机暂存已满，最早的录音被丢弃';
      }
      if (items.isEmpty) {
        if (state != 'error') _set('idle');
        return;
      }
      if (endpoints.all.isEmpty) return _set('no_server', '还没填写电脑地址');
      final at = _retryAt;
      if (at != null && DateTime.now().isBefore(at)) return;
      final can = canUpload;
      if (can != null && !await can()) return _set('waiting_wifi');
      _set('uploading');
      for (final it in items) {
        try {
          final size = it.file.lengthSync();
          await endpoints.run((base) => _send(base, it));
          it.file.deleteSync();
          uploadedChunks++;
          lastOk = DateTime.now();
          _fails = 0;
          pendingCount--;
          if (it.hasAudio) pendingBytes -= size;
          if (pendingBytes < 0) pendingBytes = 0;
          onChanged?.call();
        } catch (e) {
          _fails++;
          // 失败后隔一会再试：5 秒、10 秒……最长 1 分钟
          _retryAt = DateTime.now().add(Duration(seconds: (5 * _fails).clamp(5, 60)));
          return _set('error', _explain(e));
        }
      }
      _refresh(pending());
      _set('idle');
    } finally {
      _busy = false;
      // 上传期间又录了新的片：接着传
      if (state == 'idle' && pending().isNotEmpty) unawaited(kick());
    }
  }

  String _explain(Object e) {
    return '$e';
  }

  /// 告诉电脑是哪台设备传的（几台设备同时录音时分开显示）
  Map<String, String> get _device => {
        if (settings.deviceId.isNotEmpty) 'device': settings.deviceId,
        if (settings.deviceName.isNotEmpty) 'name': settings.deviceName,
      };

  Future<void> _send(String baseUrl, SpoolItem it) async {
    final base = Uri.parse(baseUrl);
    final prefix = base.path.replaceAll(RegExp(r'/+$'), '');
    final Uri uri;
    if (it.kind == 'x') {
      uri = base.replace(
          path: '$prefix/api/phone/stop',
          queryParameters: {'stream': it.stream, 'seq': '${it.seq}', ..._device});
    } else {
      uri = base.replace(path: '$prefix/api/phone/chunk', queryParameters: {
        'stream': it.stream,
        'seq': '${it.seq}',
        'start': it.start.toIso8601String(),
        'dur': (it.durMs / 1000).toStringAsFixed(3),
        'silent': it.kind == 's' ? '1' : '0',
        if (it.kind == 'a') 'enc': 'adpcm',
        ..._device,
      });
    }
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final req = await client.postUrl(uri);
      req.headers.set('X-Token', settings.token);
      req.headers.set('Content-Type', 'application/octet-stream');
      if (it.hasAudio) {
        req.contentLength = it.file.lengthSync();
        await req.addStream(it.file.openRead());
      } else {
        req.contentLength = 0;
      }
      final resp = await req.close().timeout(const Duration(seconds: 40));
      await resp.drain<void>();
      if (resp.statusCode == 401) throw ApiException('连接口令不对', status: 401);
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw ApiException('电脑返回错误 HTTP ${resp.statusCode}', status: resp.statusCode);
      }
    } finally {
      client.close(force: true);
    }
  }
}
