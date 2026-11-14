/// IMA ADPCM 编码：把 16bit 录音压缩到 1/4（每个采样 4 bit），用移动网络上传时省流量。
/// 实测对识别结果的影响很小。电脑端 app/adpcm.py 负责还原。
/// 格式：前 4 字节 = 首个采样(int16 小端) + 步长索引 + 0；之后每字节两个 4bit 码，低 4 位在前。
library;

import 'dart:typed_data';

const _step = <int>[
  7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, //
  66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371,
  408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707,
  1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132,
  7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
  27086, 29794, 32767,
];
const _idx = <int>[-1, -1, -1, -1, 2, 4, 6, 8];

/// 还原成 16bit 小端录音（手机独立复盘时，之前按压缩格式存下的片要先还原）
Uint8List adpcmDecode(Uint8List data) {
  if (data.length < 4) return Uint8List(0);
  final n = (data.length - 4) * 2;
  final out = ByteData(n * 2);
  var pred = ByteData.sublistView(data).getInt16(0, Endian.little);
  var idx = data[2].clamp(0, 88);
  for (var i = 0; i < n; i++) {
    final b = data[4 + (i >> 1)];
    final code = i.isEven ? b & 0x0F : b >> 4;
    final step = _step[idx];
    var d = step >> 3;
    if (code & 4 != 0) d += step;
    if (code & 2 != 0) d += step >> 1;
    if (code & 1 != 0) d += step >> 2;
    pred = (code & 8) != 0 ? pred - d : pred + d;
    if (pred > 32767) pred = 32767;
    if (pred < -32768) pred = -32768;
    idx = (idx + _idx[code & 7]).clamp(0, 88);
    out.setInt16(i * 2, pred, Endian.little);
  }
  return out.buffer.asUint8List();
}

/// [pcm]：16bit 小端单声道，长度为偶数
Uint8List adpcmEncode(Uint8List pcm) {
  final n = pcm.length ~/ 2;
  final bd = ByteData.sublistView(pcm);
  final out = Uint8List(4 + (n + 1) ~/ 2);
  var pred = n > 0 ? bd.getInt16(0, Endian.little) : 0;
  var idx = 0;
  out[0] = pred & 0xFF;
  out[1] = (pred >> 8) & 0xFF;
  out[2] = idx;
  var o = 4;
  var low = -1;
  for (var i = 0; i < n; i++) {
    final s = bd.getInt16(i * 2, Endian.little);
    final step = _step[idx];
    var diff = s - pred;
    var code = 0;
    if (diff < 0) {
      code = 8;
      diff = -diff;
    }
    var d = step >> 3;
    if (diff >= step) {
      code |= 4;
      diff -= step;
      d += step;
    }
    if (diff >= step >> 1) {
      code |= 2;
      diff -= step >> 1;
      d += step >> 1;
    }
    if (diff >= step >> 2) {
      code |= 1;
      d += step >> 2;
    }
    pred = (code & 8) != 0 ? pred - d : pred + d;
    if (pred > 32767) pred = 32767;
    if (pred < -32768) pred = -32768;
    idx += _idx[code & 7];
    if (idx < 0) idx = 0;
    if (idx > 88) idx = 88;
    if (low < 0) {
      low = code;
    } else {
      out[o++] = low | (code << 4);
      low = -1;
    }
  }
  if (low >= 0) out[o++] = low;
  return out;
}
