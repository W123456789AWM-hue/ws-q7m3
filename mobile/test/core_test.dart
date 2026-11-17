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

/// 像说话的声音：音高在 120~200Hz 之间起伏的元音（带谐波），音量像音节一样一起一伏
Uint8List _talk(double seconds, double amp) {
  final n = (kSampleRate * seconds).round();
  final bd = ByteData(n * 2);
  var ph = 0.0;
  for (var i = 0; i < n; i++) {
    final t = i / kSampleRate;
    ph += 2 * math.pi * (160 + 40 * math.sin(2 * math.pi * 0.7 * t)) / kSampleRate;
    var s = 0.0;
    for (var k = 1; k < 20; k++) {
      s += math.sin(k * ph) / k;
    }
    final env = 0.5 + 0.5 * math.pow(math.sin(2 * math.pi * 4 * t), 2);
    bd.setInt16(i * 2, (amp * 16000 * s * env).round().clamp(-32768, 32767), Endian.little);
  }
  return bd.buffer.asUint8List();
}

void main() {
  test('杂音不算人声：白噪、嗡嗡声、提示音过滤，说话（包括单字）保留', () {
    Int16List i16(Uint8List b) => b.buffer.asInt16List();
    Int16List tone(List<double> hz, double sec) {
      final n = (kSampleRate * sec).round();
      return Int16List.fromList([
        for (var i = 0; i < n; i++)
          hz.fold<double>(0, (a, f) => a + 4000 * math.sin(2 * math.pi * f * i / kSampleRate)).round()
      ]);
    }

    expect(looksLikeSpeech(i16(_noise(3, 0.1))), isFalse);
    expect(looksLikeSpeech(tone([100, 200], 3)), isFalse);
    expect(looksLikeSpeech(tone([440], 3)), isFalse);
    expect(looksLikeSpeech(i16(_talk(2, 0.3))), isTrue);
    expect(looksLikeSpeech(i16(_talk(0.3, 0.3))), isTrue);
  });

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
    feed(_talk(5, 0.3)); // 有人说话
    feed(_noise(5, 0.0005)); // 安静
    feed(_noise(5, 0.3)); // 很响但只是杂音（风扇、车流）：也算没人说话
    spool.stop();

    final items = Uploader(dir, st).pending();
    expect(items.map((e) => e.kind).toList(), ['s', 'v', 's', 's', 'x']);
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
