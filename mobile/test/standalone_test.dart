import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:ai_mind/core/adpcm.dart';
import 'package:ai_mind/core/audio.dart';
import 'package:ai_mind/core/local_engine.dart';
import 'package:ai_mind/core/settings.dart';
import 'package:ai_mind/core/updater.dart';
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

/// 假的 AI 接口：收到录音就按标注里的段落编号返回听写和复盘；收到文字就返回一份总复盘
class FakeAi {
  late HttpServer server;
  int audioCalls = 0, textCalls = 0, failNext = 0;
  final List<int> audioParts = [];
  String get url => 'http://127.0.0.1:${server.port}/v1';

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((req) async {
      final body = jsonDecode(await utf8.decoder.bind(req).join()) as Map;
      void reply(int code, Object j) {
        req.response
          ..statusCode = code
          ..headers.contentType = ContentType.json
          ..write(jsonEncode(j));
        req.response.close();
      }

      if (req.headers.value('authorization') != 'Bearer sk-test') return reply(401, {'error': 'bad key'});
      if (failNext > 0) {
        failNext--;
        return reply(500, {'error': 'boom'});
      }
      final user = (body['messages'] as List).last['content'];
      if (user is List) {
        audioCalls++;
        final ids = [
          for (final p in user)
            if (p['type'] == 'text' && '${p['text']}'.startsWith('【段落 #'))
              int.parse(RegExp(r'#(\d+)').firstMatch('${p['text']}')!.group(1)!)
        ];
        final audios = user.where((p) => p['type'] == 'input_audio').toList();
        audioParts.add(audios.length);
        // 发来的必须是合法的 WAV
        final wav = base64Decode('${audios.first['input_audio']['data']}');
        if (String.fromCharCodes(wav.sublist(0, 4)) != 'RIFF') return reply(400, {'error': 'audio not wav'});
        return reply(200, {
          'choices': [
            {
              'message': {
                'content': '```json\n${jsonEncode({
                      'transcripts': [for (final i in ids) {'id': i, 'text': '第$i段的听写。'}],
                      'trivial': false,
                      'title': '第$audioCalls次',
                      'summary': '概括$audioCalls',
                      'blind_spots': ['盲点$audioCalls'],
                    })}\n```'
              }
            }
          ]
        });
      }
      textCalls++;
      reply(200, {
        'choices': [
          {
            'message': {'content': '## 整体在聊什么\n总复盘$textCalls'}
          }
        ]
      });
    });
  }
}

void main() {
  HttpOverrides.global = null; // 测试里默认不让发网络请求；这里要连本机的假 AI 接口

  test('手机独立复盘：到时间自动复盘，停止后收尾并做总复盘；失败能重试', () async {
    final ai = FakeAi();
    await ai.start();
    final tmp = Directory.systemTemp.createTempSync('standalone_test');
    final spoolDir = Directory('${tmp.path}/spool');
    var t = DateTime(2026, 1, 1, 9);
    final st = AppSettings()
      ..chunkSec = 5
      ..standalone = true
      ..aiBaseUrl = ai.url
      ..aiKey = 'sk-test'
      ..reviewEveryMin = 1;
    final spool = ChunkSpool(spoolDir, st, now: () => t);
    final engine = LocalEngine(Directory('${tmp.path}/local'), spoolDir, st);
    void feed(Uint8List b) {
      for (var i = 0; i < b.length; i += 3200) {
        t = t.add(const Duration(milliseconds: 100));
        spool.add(Uint8List.sublistView(b, i, math.min(i + 3200, b.length)));
      }
    }

    spool.start();
    final sid = spool.stream!;
    feed(_noise(20, 0.3)); // 第 1 段
    feed(_noise(10, 0.0005)); // 安静：另起一段
    feed(_noise(35, 0.3)); // 第 2 段（满 1 分钟：触发第一次复盘）
    await engine.kick();
    var s = engine.session(sid)!;
    expect(ai.audioCalls, 1);
    expect(ai.audioParts.single, 2); // 两个段落各一段录音
    expect((s['reviews'] as List).single['status'], 'done');
    expect((s['reviews'] as List).single['kind'], 'periodic');
    expect((s['paragraphs'] as List).map((p) => p['text']).toList(), ['第1段的听写。', '第2段的听写。']);
    expect(s['title'], '第1次');
    expect(engine.pendingBytes(), 0); // 复盘完录音片段就删掉

    // 接口坏了：这次复盘记为失败，录音留着
    feed(_noise(10, 0.0005));
    feed(_noise(20, 0.3)); // 第 3 段
    ai.failNext = 1;
    spool.stop();
    await engine.kick();
    s = engine.session(sid)!;
    final bad = (s['reviews'] as List).last as Map;
    expect(bad['status'], 'error');
    expect('${bad['error']}', contains('HTTP 500'));
    expect(engine.pendingBytes(), greaterThan(0));
    expect((s['paragraphs'] as List).last['status'], 'live'); // 界面上显示“等待 AI 听写”
    expect(Uploader(spoolDir, st).pending(), isEmpty); // 暂存的片都处理掉了

    // 点「重试」：补上这次复盘，并做整场总复盘
    await engine.retry(sid, bad['id'] as int);
    s = engine.session(sid)!;
    expect((s['reviews'] as List).map((r) => r['status']).toList(), ['done', 'done']);
    expect(s['summary'], contains('总复盘'));
    expect(s['status'], 'done');
    expect(engine.pendingBytes(), 0);
    expect(engine.sessions().single['count'], 2);

    // 日复盘
    expect(engine.report('day', '2026-01-01'), '');
    expect(await engine.makeReport('day', '2026-01-01'), contains('总复盘'));
    expect(engine.report('day', '2026-01-01'), isNotEmpty);
    expect(await engine.makeReport('month', '2026-01'), isNotEmpty);
    await expectLater(engine.makeReport('day', '2026-01-02'), throwsA(anything));

    await ai.server.close(force: true);
    tmp.deleteSync(recursive: true);
  });

  test('没填 API Key：复盘记为失败并说明原因，不会崩', () async {
    final tmp = Directory.systemTemp.createTempSync('standalone_nokey');
    final spoolDir = Directory('${tmp.path}/spool');
    var t = DateTime(2026, 1, 2, 9);
    final st = AppSettings()
      ..chunkSec = 5
      ..standalone = true;
    final spool = ChunkSpool(spoolDir, st, now: () => t);
    final engine = LocalEngine(Directory('${tmp.path}/local'), spoolDir, st);
    spool.start();
    final sid = spool.stream!;
    final b = _noise(10, 0.3);
    for (var i = 0; i < b.length; i += 3200) {
      t = t.add(const Duration(milliseconds: 100));
      spool.add(Uint8List.sublistView(b, i, math.min(i + 3200, b.length)));
    }
    spool.stop();
    await engine.kick();
    final r = (engine.session(sid)!['reviews'] as List).single as Map;
    expect(r['status'], 'error');
    expect('${r['error']}', contains('API Key'));
    tmp.deleteSync(recursive: true);
  });

  test('压缩过的录音片能还原', () {
    final pcm = _noise(1, 0.2);
    final back = adpcmDecode(adpcmEncode(pcm));
    expect(back.length, pcm.length);
  });

  test('在线更新：真实清单验签通过，改一个字就拒绝', () {
    final raw = File('test/fixtures/latest.json').readAsBytesSync();
    final sig = File('test/fixtures/latest.json.sig').readAsStringSync();
    final m = verifyManifest(raw, sig);
    expect(m['version'], '0.9.12');
    expect((m['assets'] as Map).keys, containsAll(['android-arm64', 'android-armv7']));
    final bad = Uint8List.fromList(raw)..[20] ^= 1;
    expect(() => verifyManifest(bad, sig), throwsA(isA<UpdateException>()));
  });
}
