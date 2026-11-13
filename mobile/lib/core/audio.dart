import 'dart:collection';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

const int kSampleRate = 16000;
const int kFrame = 480; // 30ms
const double kFrameSec = kFrame / kSampleRate;
const double kEndSilenceSec = 0.8; // 停顿多久算一句结束
const double kMaxUttSec = 25; // 一句最长多少秒

/// 一句话的音频
class Utterance {
  Utterance(this.start, this.end, this.pcm);
  final DateTime start;
  final DateTime end;
  final Int16List pcm;
}

/// 实时切句：16kHz 单声道 16bit PCM 字节流 → 一句一句的 [Utterance]。
/// 用自适应噪声底判断“有人在说话”，只有说话的片段才会送去识别，
/// 安静的时候识别模型完全不运行（省电、不发热）。
class Segmenter {
  Segmenter({
    required this.now,
    required this.onUtterance,
    this.marginDb = 10,
    this.minDb = -50,
  });

  final DateTime Function() now;
  final void Function(Utterance) onUtterance;
  double marginDb;
  double minDb;

  double levelDb = -100;
  double noiseDb = -60;
  DateTime? lastVoice;
  int speechFrames = 0; // 到目前为止判定为“有声音”的帧数（每帧 30 毫秒）

  final Int16List _f = Int16List(kFrame);
  int _fi = 0;
  double _sumSq = 0;
  int? _carry;
  final ListQueue<Int16List> _preroll = ListQueue<Int16List>();
  bool _inUtt = false;
  List<Int16List> _buf = [];
  DateTime _uttStart = DateTime.fromMillisecondsSinceEpoch(0);
  int _silence = 0;
  int _voiced = 0;
  int _run = 0;

  void addBytes(Uint8List b) {
    if (b.isEmpty) return;
    var i = 0;
    if (_carry != null) {
      final v = _carry! | (b[0] << 8);
      _sample(v >= 0x8000 ? v - 0x10000 : v);
      _carry = null;
      i = 1;
    }
    final bd = ByteData.sublistView(b);
    for (; i + 1 < b.length; i += 2) {
      _sample(bd.getInt16(i, Endian.little));
    }
    if (i < b.length) _carry = b[i];
  }

  void _sample(int s) {
    _f[_fi++] = s;
    _sumSq += s * s;
    if (_fi == kFrame) {
      _frame();
      _fi = 0;
      _sumSq = 0;
    }
  }

  void _frame() {
    final rms = math.sqrt(_sumSq / kFrame + 1e-9);
    final db = 20 * math.log(rms / 32768 + 1e-9) / math.ln10;
    levelDb = db;
    // 自适应噪声底：快降慢升
    if (db < noiseDb) {
      noiseDb = 0.8 * noiseDb + 0.2 * db;
    } else {
      noiseDb += 0.002 * (db - noiseDb);
    }
    final speech = db > math.max(minDb, noiseDb + marginDb);
    final t = now();
    if (speech) {
      lastVoice = t;
      speechFrames++;
    }
    final frame = Int16List.fromList(_f);

    if (!_inUtt) {
      _run = speech ? _run + 1 : 0;
      _preroll.addLast(frame);
      if (_preroll.length > 10) _preroll.removeFirst();
      if (_run >= 3) {
        // 连续 90ms 有声才算开口
        _inUtt = true;
        _buf = _preroll.toList();
        _uttStart = t.subtract(
            Duration(milliseconds: (_buf.length * kFrameSec * 1000).round()));
        _silence = 0;
        _voiced = _run;
        _preroll.clear();
      }
    } else {
      _buf.add(frame);
      if (speech) {
        _silence = 0;
        _voiced++;
      } else {
        _silence++;
      }
      if (_silence * kFrameSec >= kEndSilenceSec ||
          _buf.length * kFrameSec >= kMaxUttSec) {
        flush();
      }
    }
  }

  /// 结束当前这一句（停止录音时也要调用一次）
  void flush() {
    if (!_inUtt) return;
    _inUtt = false;
    _run = 0;
    final buf = _buf;
    _buf = [];
    if (_voiced * kFrameSec < 0.4 || buf.isEmpty) return;
    final pcm = Int16List(buf.length * kFrame);
    for (var i = 0; i < buf.length; i++) {
      pcm.setRange(i * kFrame, (i + 1) * kFrame, buf[i]);
    }
    onUtterance(Utterance(_uttStart, now(), pcm));
  }
}

Uint8List buildWavHeader(int dataLen, {int sampleRate = kSampleRate}) {
  final h = ByteData(44);
  void str(int off, String s) {
    for (var i = 0; i < s.length; i++) {
      h.setUint8(off + i, s.codeUnitAt(i));
    }
  }

  str(0, 'RIFF');
  h.setUint32(4, 36 + dataLen, Endian.little);
  str(8, 'WAVE');
  str(12, 'fmt ');
  h.setUint32(16, 16, Endian.little);
  h.setUint16(20, 1, Endian.little);
  h.setUint16(22, 1, Endian.little);
  h.setUint32(24, sampleRate, Endian.little);
  h.setUint32(28, sampleRate * 2, Endian.little);
  h.setUint16(32, 2, Endian.little);
  h.setUint16(34, 16, Endian.little);
  str(36, 'data');
  h.setUint32(40, dataLen, Endian.little);
  return h.buffer.asUint8List();
}

/// 把完整录音按固定时长切成多个 WAV 文件（audio_001.wav …）。
/// 每写满一个就回调 [onPartClosed]，可以立刻上传 NAS 并删除本地副本。
class WavPartWriter {
  WavPartWriter(this.dir, {this.partSec = 1800, this.onPartClosed, int startPart = 0})
      : _part = startPart;

  final Directory dir;
  final int partSec;
  final void Function(File)? onPartClosed;
  RandomAccessFile? _raf;
  File? _file;
  int _part;
  int _bytes = 0;

  /// 正在写入的文件（还不能上传）
  String? get currentPath => _file?.path;

  void add(Uint8List chunk) {
    if (chunk.isEmpty) return;
    if (_raf == null) _open();
    _raf!.writeFromSync(chunk);
    _bytes += chunk.length;
    if (_bytes >= partSec * kSampleRate * 2 && _bytes.isEven) close();
  }

  void _open() {
    _part++;
    _bytes = 0;
    dir.createSync(recursive: true);
    _file = File('${dir.path}/audio_${_part.toString().padLeft(3, '0')}.wav');
    _raf = _file!.openSync(mode: FileMode.write);
    _raf!.writeFromSync(buildWavHeader(0));
  }

  void close() {
    final raf = _raf;
    final f = _file;
    if (raf == null || f == null) return;
    _raf = null;
    _file = null;
    try {
      raf.setPositionSync(0);
      raf.writeFromSync(buildWavHeader(_bytes & ~1));
      raf.closeSync();
    } catch (_) {}
    onPartClosed?.call(f);
  }

  /// App 被杀后留下的半截文件：按实际大小修正头部
  static void repair(File f) {
    final len = f.lengthSync();
    if (len < 44) {
      f.deleteSync();
      return;
    }
    final raf = f.openSync(mode: FileMode.append);
    try {
      raf.setPositionSync(0);
      raf.writeFromSync(buildWavHeader((len - 44) & ~1));
    } finally {
      raf.closeSync();
    }
  }
}
