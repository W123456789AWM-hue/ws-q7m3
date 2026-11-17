/// 手机直接把反馈发到开发者的飞书群（不经过电脑）。
///
/// - 和电脑端 server/aimind/feedback.py 同一个机器人、同一种卡片格式。
/// - 机器人地址和密钥不写在代码里：云端打包时从 GitHub 密钥用 --dart-define 传进来
///   （FEEDBACK_WEBHOOK / FEEDBACK_SECRET；附图另要 FEEDBACK_APP_ID / FEEDBACK_APP_SECRET）。
///   本机打包没传时 [configured] 为 false，界面会提示改为经电脑发送。
/// - 发不出去（没网）就存在手机的 feedback/ 里，下次打开 App、或下次发反馈时再发，不会丢。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

const _webhook = String.fromEnvironment('FEEDBACK_WEBHOOK');
const _secret = String.fromEnvironment('FEEDBACK_SECRET');
const _appId = String.fromEnvironment('FEEDBACK_APP_ID');
const _appSecret = String.fromEnvironment('FEEDBACK_APP_SECRET');
const _feishu = 'https://open.feishu.cn/open-apis';
const kinds = {'bug': '问题', 'idea': '建议', 'other': '其他'};

/// 飞书签名：HmacSHA256(key = "时间戳\n密钥", 消息为空) 再 base64（和电脑端一样）
String feishuSign(String secret, int ts) =>
    base64Encode(Hmac(sha256, utf8.encode('$ts\n$secret')).convert(const []).bytes);

/// 飞书消息卡片（和电脑端 feedback._card 一致）
Map<String, dynamic> feedbackCard(Map<String, dynamic> item, {List<String> imageKeys = const [], String imageNote = ''}) {
  final kind = kinds[item['kind']] ?? '其他';
  final t = DateTime.fromMillisecondsSinceEpoch(((item['time'] as num) * 1000).round());
  String two(int v) => v.toString().padLeft(2, '0');
  final body = [
    '**内容**\n${item['text']}',
    if ('${item['contact'] ?? ''}'.isNotEmpty) '**联系方式**：${item['contact']}',
    '**时间**：${t.year}-${two(t.month)}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}　**编号**：${item['id']}',
  ];
  final elements = <Map<String, dynamic>>[
    {'tag': 'div', 'text': {'tag': 'lark_md', 'content': body.join('\n')}},
    for (var i = 0; i < imageKeys.length; i++)
      {
        'tag': 'img',
        'img_key': imageKeys[i],
        'alt': {'tag': 'plain_text', 'content': '附图 ${i + 1}'},
        'mode': 'fit_horizontal',
        'preview': true,
      },
  ];
  final missing = ((item['images'] as List?)?.length ?? 0) - imageKeys.length;
  if (missing > 0) {
    final why = imageNote.isEmpty ? '' : '（$imageNote）';
    elements.add({
      'tag': 'note',
      'elements': [
        {'tag': 'plain_text', 'content': '还有 $missing 张附图没能显示$why，图片存在用户手机的 feedback/${item['id']} 里'}
      ]
    });
  }
  final diag = '${item['diag'] ?? ''}';
  if (diag.isNotEmpty) {
    elements.addAll([
      {'tag': 'hr'},
      {'tag': 'div', 'text': {'tag': 'plain_text', 'content': diag.length > 3500 ? diag.substring(diag.length - 3500) : diag}},
    ]);
  }
  return {
    'msg_type': 'interactive',
    'card': {
      'header': {
        'title': {'tag': 'plain_text', 'content': '【$kind】AI 录音思考助手 ${item['version'] ?? ''} · ${item['source'] ?? '手机'}'},
        'template': {'bug': 'red', 'idea': 'blue'}[item['kind']] ?? 'grey',
      },
      'elements': elements,
    },
  };
}

class FeedbackOutbox {
  FeedbackOutbox(this.dir, {String? webhook, String? secret, String? appId, String? appSecret, this.feishuBase = _feishu})
      : webhook = webhook ?? _webhook,
        secret = secret ?? _secret,
        appId = appId ?? _appId,
        appSecret = appSecret ?? _appSecret;

  final Directory dir; // <数据目录>/feedback
  final String webhook, secret, appId, appSecret, feishuBase;
  bool _busy = false;
  String _token = '';
  DateTime _tokenUntil = DateTime(0);

  /// 这个安装包里有没有反馈通道（云端打包的才有）
  bool get configured => webhook.isNotEmpty;
  bool get imagesConfigured => appId.isNotEmpty && appSecret.isNotEmpty;

  File _file(String id) => File('${dir.path}/$id.json');
  Directory _imgDir(String id) => Directory('${dir.path}/$id');

  /// 新建一条反馈并马上试着发；返回给界面看的记录（status: sent / pending）
  Future<Map<String, dynamic>> submit({
    required String kind,
    required String text,
    String contact = '',
    String source = '',
    String version = '',
    String diag = '',
    List<Uint8List> images = const [],
  }) async {
    final now = DateTime.now();
    final rnd = Random();
    final id = '${now.month.toString().padLeft(2, '0')}${now.day.toString().padLeft(2, '0')}-'
        '${List.generate(6, (_) => '0123456789abcdef'[rnd.nextInt(16)]).join()}';
    final item = <String, dynamic>{
      'id': id,
      'time': now.millisecondsSinceEpoch / 1000,
      'kind': kinds.containsKey(kind) ? kind : 'other',
      'text': text.length > 4000 ? text.substring(0, 4000) : text,
      'contact': contact.length > 100 ? contact.substring(0, 100) : contact,
      'source': source,
      'version': version,
      'status': 'pending',
      'error': '',
      'via': 'phone',
      if (diag.isNotEmpty) 'diag': diag,
    };
    if (images.isNotEmpty) {
      final d = _imgDir(id)..createSync(recursive: true);
      item['images'] = <String>[];
      for (var i = 0; i < images.length && i < 3; i++) {
        File('${d.path}/${i + 1}.jpg').writeAsBytesSync(images[i]);
        (item['images'] as List).add('${i + 1}.jpg');
      }
    }
    _save(item);
    return _public(await _trySend(item));
  }

  /// 之前没发出去的再发一次，返回发成功的条数
  Future<int> retryPending() async {
    if (_busy || !configured) return 0;
    _busy = true;
    var ok = 0;
    try {
      for (final item in _all()) {
        if (item['status'] == 'pending' && (await _trySend(item))['status'] == 'sent') ok++;
      }
    } finally {
      _busy = false;
    }
    return ok;
  }

  /// 在这台手机上直接发的反馈（新的在前）
  List<Map<String, dynamic>> history() => [for (final x in _all().reversed) _public(x)];

  List<Map<String, dynamic>> _all() {
    if (!dir.existsSync()) return [];
    final out = <Map<String, dynamic>>[];
    for (final f in dir.listSync().whereType<File>().where((f) => f.path.endsWith('.json'))) {
      try {
        out.add(Map<String, dynamic>.from(jsonDecode(f.readAsStringSync()) as Map));
      } catch (_) {/* 坏文件跳过 */}
    }
    out.sort((a, b) => (a['time'] as num).compareTo(b['time'] as num));
    return out;
  }

  void _save(Map<String, dynamic> item) {
    dir.createSync(recursive: true);
    final tmp = File('${_file(item['id'] as String).path}.tmp')..writeAsStringSync(jsonEncode(item));
    tmp.renameSync(_file(item['id'] as String).path);
  }

  static Map<String, dynamic> _public(Map<String, dynamic> item) =>
      {for (final e in item.entries) if (e.key != 'diag' && e.key != 'image_keys') e.key: e.value};

  Future<Map<String, dynamic>> _trySend(Map<String, dynamic> item) async {
    try {
      if (!configured) throw Exception('这个版本没有内置反馈通道，请连上电脑后再发');
      await _send(item);
      item
        ..['status'] = 'sent'
        ..['error'] = ''
        ..['sent_at'] = DateTime.now().millisecondsSinceEpoch / 1000;
    } catch (e) {
      final msg = '$e'.replaceFirst('Exception: ', '');
      item
        ..['status'] = 'pending'
        ..['error'] = msg.length > 200 ? msg.substring(0, 200) : msg;
    }
    item['tries'] = ((item['tries'] as num?) ?? 0) + 1;
    _save(item);
    return item;
  }

  Future<void> _send(Map<String, dynamic> item) async {
    final note = await _uploadImages(item);
    final keys = [for (final v in ((item['image_keys'] as Map?) ?? {}).values) '$v'];
    try {
      await _postCard(feedbackCard(item, imageKeys: keys, imageNote: note));
    } catch (e) {
      if (keys.isEmpty) rethrow;
      // 卡片不收图片：文字先送到，注明原因（和电脑端一样）
      final why = '$e'.replaceFirst('Exception: ', '');
      await _postCard(feedbackCard(item, imageNote: '卡片放不进图片：${why.length > 120 ? why.substring(0, 120) : why}'));
    }
  }

  Future<void> _postCard(Map<String, dynamic> payload) async {
    if (secret.isNotEmpty) {
      final ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
      payload['timestamp'] = '$ts';
      payload['sign'] = feishuSign(secret, ts);
    }
    await _http(webhook, utf8.encode(jsonEncode(payload)), 'application/json');
  }

  /// 把还没上传的附图传到飞书（image_key 记在 item 里，重试时不重复传）。返回没传成功的原因
  Future<String> _uploadImages(Map<String, dynamic> item) async {
    final names = [for (final n in (item['images'] as List?) ?? const []) '$n'];
    if (names.isEmpty) return '';
    if (!imagesConfigured) return '这个版本还没接通图片通道';
    final keys = Map<String, dynamic>.from((item['image_keys'] as Map?) ?? {});
    var err = '';
    for (final n in names) {
      if ('${keys[n] ?? ''}'.isNotEmpty) continue;
      try {
        final f = File('${_imgDir(item['id'] as String).path}/$n');
        final boundary = '----aimind${DateTime.now().microsecondsSinceEpoch}';
        final body = BytesBuilder(copy: false)
          ..add(utf8.encode('--$boundary\r\nContent-Disposition: form-data; name="image_type"\r\n\r\nmessage\r\n'
              '--$boundary\r\nContent-Disposition: form-data; name="image"; filename="$n"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n'))
          ..add(f.readAsBytesSync())
          ..add(utf8.encode('\r\n--$boundary--\r\n'));
        final r = await _http('$feishuBase/im/v1/images', body.takeBytes(), 'multipart/form-data; boundary=$boundary',
            headers: {'Authorization': 'Bearer ${await _appToken()}'}, timeout: const Duration(seconds: 60));
        keys[n] = (r['data'] as Map)['image_key'];
      } catch (e) {
        final m = '$e'.replaceFirst('Exception: ', '');
        err = '图片上传失败：${m.length > 120 ? m.substring(0, 120) : m}';
      }
    }
    item['image_keys'] = keys;
    return err;
  }

  Future<String> _appToken() async {
    if (_token.isNotEmpty && DateTime.now().isBefore(_tokenUntil)) return _token;
    final r = await _http('$feishuBase/auth/v3/tenant_access_token/internal',
        utf8.encode(jsonEncode({'app_id': appId, 'app_secret': appSecret})), 'application/json');
    _token = '${r['tenant_access_token']}';
    _tokenUntil = DateTime.now().add(Duration(seconds: ((r['expire'] as num?) ?? 7200).toInt() - 300));
    return _token;
  }

  /// POST，返回飞书的 JSON；code 不为 0 时抛错（和电脑端 _http 一样）
  Future<Map<String, dynamic>> _http(String url, List<int> body, String ctype,
      {Map<String, String> headers = const {}, Duration timeout = const Duration(seconds: 20)}) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
    try {
      final req = await client.postUrl(Uri.parse(url));
      req.headers.set('Content-Type', ctype);
      headers.forEach(req.headers.set);
      req.contentLength = body.length;
      req.add(body);
      final resp = await req.close().timeout(timeout);
      final text = await resp.transform(utf8.decoder).join().timeout(timeout);
      Map<String, dynamic> j = {};
      try {
        j = Map<String, dynamic>.from(jsonDecode(text.isEmpty ? '{}' : text) as Map);
      } catch (_) {}
      final code = j['code'] ?? j['StatusCode'] ?? 0;
      if (code != 0) throw Exception('飞书返回错误 $code：${j['msg'] ?? j['StatusMessage'] ?? ''}');
      if (resp.statusCode >= 300) throw Exception('飞书返回 HTTP ${resp.statusCode}');
      return j;
    } on SocketException {
      throw Exception('没有网络，联网后会自动重发');
    } on TimeoutException {
      throw Exception('网络太慢，联网后会自动重发');
    } on HandshakeException {
      throw Exception('安全连接失败，联网后会自动重发');
    } finally {
      client.close(force: true);
    }
  }
}
