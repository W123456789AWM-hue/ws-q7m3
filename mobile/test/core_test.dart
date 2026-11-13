import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:ai_mind/core/audio.dart';
import 'package:ai_mind/core/settings.dart';
import 'package:ai_mind/core/uploader.dart';
import 'package:flutter_test/flutter_test.dart';

Uint8List _noise(double seconds, double amp) {
  final n = (kSampleRate * seconds).round();
  final bd = ByteData(n * 2);
  final rnd = math.Random(1);
  for (var i = 0; i < n; i++) {
    bd.setInt16(i * 2, (amp * 32767 * (rnd.nextDouble() * 2 - 1)).round(), Endian.little);
  }
  return bd.buffer.asUint8List();
}

void main() {
  test('切片：有声音的片保存音频，静音的片只留标记，最后有停止标记', () {
    final dir = Directory.systemTemp.createTempSync('spool_test');
    var t = DateTime(2026, 1, 1, 9);
    final st = AppSettings()..chunkSec = 5;
    final spool = ChunkSpool(dir, st, now: () => t);
    void feed(Uint8List b) {
      for (var i = 0; i < b.length; i += 3200) {
        t = t.add(const Duration(milliseconds: 100));
        spool.add(Uint8List.sublistView(b, i, math.min(i + 3200, b.length)));
      }
    }

    spool.start();
    feed(_noise(5, 0.0005)); // 安静
    feed(_noise(5, 0.3)); // 有声音
    feed(_noise(5, 0.0005)); // 安静
    spool.stop();

    final items = Uploader(dir, st).pending();
    expect(items.map((e) => e.kind).toList(), ['s', 'v', 's', 'x']);
    expect(items[1].file.lengthSync(), 5 * kSampleRate * 2);
    expect(items[0].file.lengthSync(), 0);
    expect(items[1].start.difference(items[0].start).inSeconds, 5);
    dir.deleteSync(recursive: true);
  });

  test('地址自动补全 http://', () {
    final s = AppSettings()..apply({'serverUrl': '192.168.1.20:8765/'});
    expect(s.serverUrl, 'http://192.168.1.20:8765');
  });
}
