import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:ai_mind/core/feedback.dart';
import 'package:flutter_test/flutter_test.dart';

/// 假飞书：机器人地址 /hook，开放平台 /open-apis/...；记下收到的东西
class FakeFeishu {
  late HttpServer server;
  final cards = <Map<String, dynamic>>[];
  int uploads = 0;
  bool down = false; // true：机器人地址返回 503（模拟没网 / 飞书出问题）

  String get base => 'http://127.0.0.1:${server.port}';

  Future<void> start() async {
    server = await HttpServer.bind('127.0.0.1', 0);
    server.listen((req) async {
      final body = await req.fold<List<int>>([], (a, b) => a..addAll(b));
      Object out = {'code': 0};
      if (req.uri.path == '/hook') {
        if (down) {
          req.response.statusCode = 503;
          await req.response.close();
          return;
        }
        cards.add(jsonDecode(utf8.decode(body)) as Map<String, dynamic>);
      } else if (req.uri.path.endsWith('/tenant_access_token/internal')) {
        out = {'code': 0, 'tenant_access_token': 't-1', 'expire': 7200};
      } else if (req.uri.path.endsWith('/im/v1/images')) {
        expect(req.headers.value('authorization'), 'Bearer t-1');
        uploads++;
        out = {'code': 0, 'data': {'image_key': 'img_$uploads'}};
      }
      req.response.headers.contentType = ContentType.json;
      req.response.write(jsonEncode(out));
      await req.response.close();
    });
  }
}

void main() {
  test('飞书签名和电脑端算法一致', () {
    // 电脑端：base64(hmac_sha256(key="1700000000\nabc", msg=b""))
    expect(feishuSign('abc', 1700000000), 'VIS10b0EBvzzSdFnuk4tznEmK5wHaruvf/WnViv2yR4=');
  });

  test('不连电脑也能发反馈：带签名、附图；发不出去先存着，之后自动补发', () async {
    final fs = FakeFeishu();
    await fs.start();
    final dir = Directory.systemTemp.createTempSync('fb');
    final box = FeedbackOutbox(Directory('${dir.path}/feedback'),
        webhook: '${fs.base}/hook', secret: 's3cret', appId: 'cli_x', appSecret: 'sec', feishuBase: '${fs.base}/open-apis');
    expect(box.configured, isTrue);

    final r = await box.submit(
        kind: 'bug', text: '录音按钮没反应', contact: 'wx: test', source: '我的手机', version: '0.11.1',
        diag: '发送设备：App 0.11.1', images: [Uint8List.fromList([0xff, 0xd8, 0xff, 1, 2, 3])]);
    expect(r['status'], 'sent');
    expect(r.containsKey('diag'), isFalse); // 给界面的记录不带诊断信息
    expect(fs.uploads, 1);
    final card = fs.cards.single;
    expect(card['sign'], feishuSign('s3cret', int.parse(card['timestamp'] as String)));
    final text = jsonEncode(card['card']);
    expect(text, contains('【问题】AI 录音思考助手 0.11.1 · 我的手机'));
    expect(text, contains('录音按钮没反应'));
    expect(text, contains('img_1'));
    expect(text, contains('发送设备：App 0.11.1'));

    // 飞书暂时不通：存成待发送，不丢；恢复后补发
    fs.down = true;
    final p = await box.submit(kind: 'idea', text: '想要导出 PDF');
    expect(p['status'], 'pending');
    expect(p['error'], contains('503'));
    expect(box.history().first['text'], '想要导出 PDF');
    fs.down = false;
    expect(await box.retryPending(), 1);
    expect(fs.cards.length, 2);
    expect(box.history().every((x) => x['status'] == 'sent'), isTrue);

    // 没有内置反馈通道（本机打包）：记为待发送并说明原因
    final none = FeedbackOutbox(Directory('${dir.path}/none'), webhook: '', secret: '');
    expect(none.configured, isFalse);
    expect((await none.submit(kind: 'bug', text: 'x'))['error'], contains('没有内置反馈通道'));

    await fs.server.close(force: true);
    dir.deleteSync(recursive: true);
  });
}
