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

// ---------------- 是不是人在说话（过滤杂音） ----------------
// 只看音量的话，风扇、键盘、车流、翻东西也会被当成“有人说话”发给 AI（白花钱，还干扰复盘）。
// 人说话时元音有明显的音高（70~400Hz 的周期性），而且音高在变；杂音没有周期性，电器嗡嗡声音高一成不变。
// 和电脑端 server/aimind/audio/vad.py 的 looks_like_speech 是同一套算法、同一组参数。
const int _vWin = 320, _vHop = 160, _vLagLo = 18, _vLagHi = 115, _vRun = 4;
const double _vR = 0.35, _vMinSec = 0.08;

/// 每个“有音高”的帧：[第几帧, 周期采样数 @8kHz]
List<List<int>> voicedFrames(Int16List pcm) {
  final n = pcm.length ~/ 2;
  final x = Float64List(n);
  for (var i = 0; i < n; i++) {
    x[i] = (pcm[2 * i] + pcm[2 * i + 1]) / 2; // 16k → 8k
  }
  if (n < _vWin) return [];
  final count = (n - _vWin) ~/ _vHop + 1;
  final db = Float64List(count);
  var maxDb = -1e9;
  for (var f = 0; f < count; f++) {
    final o = f * _vHop;
    var m = 0.0;
    for (var i = 0; i < _vWin; i++) {
      m += x[o + i];
    }
    m /= _vWin;
    var e = 0.0;
    for (var i = 0; i < _vWin; i++) {
      final v = x[o + i] - m;
      e += v * v;
    }
    db[f] = 10 * math.log(e / _vWin + 1e-6) / math.ln10;
    if (db[f] > maxDb) maxDb = db[f];
  }
  final floor = 20 * math.log(32768 * math.pow(10, -55 / 20)) / math.ln10;
  final gate = math.max(maxDb - 30, floor);
  final out = <List<int>>[];
  final w = Float64List(_vWin);
  final sq = Float64List(_vWin);
  final r = Float64List(_vLagHi - _vLagLo + 1);
  for (var f = 0; f < count; f++) {
    if (db[f] <= gate) continue;
    final o = f * _vHop;
    var m = 0.0;
    for (var i = 0; i < _vWin; i++) {
      m += x[o + i];
    }
    m /= _vWin;
    var acc = 0.0;
    for (var i = 0; i < _vWin; i++) {
      w[i] = x[o + i] - m;
      acc += w[i] * w[i];
      sq[i] = acc;
    }
    for (var lag = _vLagLo; lag <= _vLagHi; lag++) {
      var num = 0.0;
      for (var i = 0; i + lag < _vWin; i++) {
        num += w[i] * w[i + lag];
      }
      final e1 = acc - sq[lag - 1]; // w[lag:] 的能量
      final e0 = sq[_vWin - 1 - lag]; // w[:N-lag] 的能量
      r[lag - _vLagLo] = num / math.sqrt(e0 * e1 + 1e-9);
    }
    var best = -1, bestR = -1.0;
    for (var k = 1; k < r.length - 1; k++) {
      if (r[k] > r[k - 1] && r[k] >= r[k + 1] && r[k] > _vR && r[k] > bestR) {
        best = k;
        bestR = r[k];
      }
    }
    if (best >= 0) out.add([f, best + _vLagLo]);
  }
  return out;
}

/// 只留连续 [_vRun] 帧以上、音高平滑变化的浊音（真说话的元音是连着的，杂音凑出的“周期”是零散的）
List<int> voicedRuns(List<List<int>> frames) {
  final out = <int>[];
  var run = <int>[];
  List<int>? prev;
  for (final fr in frames) {
    if (prev != null && fr[0] == prev[0] + 1 && (fr[1] - prev[1]).abs() <= 0.15 * prev[1]) {
      run.add(fr[1]);
    } else {
      if (run.length >= _vRun) out.addAll(run);
      run = [fr[1]];
    }
    prev = fr;
  }
  if (run.length >= _vRun) out.addAll(run);
  return out;
}

/// 这段录音里像不像有人在说话。宁可放过，不要误删
bool looksLikeSpeech(Int16List pcm) {
  final lags = voicedRuns(voicedFrames(pcm));
  if (lags.length * _vHop / 8000 < _vMinSec) return false;
  if (lags.length >= 25) {
    final c = <int, int>{};
    for (final l in lags) {
      c[l] = (c[l] ?? 0) + 1;
    }
    final top = c.values.toList()..sort((a, b) => b - a);
    if (top.take(3).fold<int>(0, (a, b) => a + b) / lags.length > 0.9) return false; // 音高一成不变：嗡嗡声、提示音
  }
  return true;
}
