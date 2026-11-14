import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

import 'endpoints.dart';
import 'settings.dart';

export 'endpoints.dart' show ApiException;

/// 和电脑上的服务通信：看复盘、看转写、改设置
class ServerApi {
  ServerApi(this.s, this.endpoints);
  final AppSettings s;
  final Endpoints endpoints;

  /// [body] 不为 null 或 [post] 为 true 时发 POST，否则 GET
  Future<dynamic> call(String path,
      {Map<String, String>? query, Object? body, bool post = false, Duration? timeout}) {
    final t = timeout ?? const Duration(seconds: 20);
    return endpoints.run((base) async {
      final b = Uri.parse(base);
      final uri = b.replace(
          path: '${b.path.replaceAll(RegExp(r'/+$'), '')}$path',
          queryParameters: query == null || query.isEmpty ? null : query);
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      try {
        final req = await ((body != null || post) ? client.postUrl(uri) : client.getUrl(uri));
        req.headers.set('X-Token', s.token);
        if (body != null) {
          final bytes = utf8.encode(jsonEncode(body));
          req.headers.contentType = ContentType('application', 'json', charset: 'utf-8');
          req.contentLength = bytes.length;
          req.add(bytes);
        } else if (post) {
          req.contentLength = 0;
        }
        final resp = await req.close().timeout(t);
        final text = await resp.transform(utf8.decoder).join().timeout(t);
        dynamic j;
        try {
          j = text.isEmpty ? null : jsonDecode(text);
        } catch (_) {
          j = null;
        }
        if (resp.statusCode < 200 || resp.statusCode >= 300) {
          final detail =
              j is Map && j['detail'] != null ? '${j['detail']}' : 'HTTP ${resp.statusCode}';
          throw ApiException(detail, status: resp.statusCode);
        }
        return j;
      } finally {
        client.close(force: true);
      }
    });
  }

  Future<Map<String, dynamic>> view() async =>
      Map<String, dynamic>.from(await call('/api/phone/view') as Map);

  Future<List<Map<String, dynamic>>> sessions() async => [
        for (final e in (await call('/api/sessions') as List)) Map<String, dynamic>.from(e as Map)
      ];

  Future<Map<String, dynamic>> session(String id) async =>
      Map<String, dynamic>.from(await call('/api/sessions/$id') as Map);

  Future<String> daily(String date) async =>
      '${(await call('/api/daily', query: {'date': date}) as Map)['md'] ?? ''}';

  Future<String> makeDaily(String date) async => '${(await call('/api/daily',
          query: {'date': date}, post: true, timeout: const Duration(minutes: 4)) as Map)['md'] ?? ''}';

  /// 日 / 月 / 年复盘。period：day / month / year；key：2026-11-13 / 2026-11 / 2026。
  /// 电脑端是旧版本（没有 /api/report）时，日复盘退回旧接口，月 / 年复盘提示升级。
  Future<String> report(String period, String key, {bool make = false}) async {
    try {
      final j = await call('/api/report',
          query: {'period': period, 'key': key},
          post: make,
          timeout: make ? const Duration(minutes: 6) : null);
      return '${(j as Map)['md'] ?? ''}';
    } on ApiException catch (e) {
      if (e.status != 404) rethrow;
      if (period == 'day') return make ? makeDaily(key) : daily(key);
      throw ApiException('电脑上的程序版本太旧，不支持月复盘 / 年复盘，请更新电脑端', status: 404);
    }
  }

  /// 在线更新：问电脑有没有新版本（电脑替手机去发布服务器查、并验证签名）
  /// 发反馈：电脑转发到开发者的飞书群（发不出去电脑会先存着，之后自动重发）
  Future<Map<String, dynamic>> sendFeedback(Map<String, Object> body) async =>
      Map<String, dynamic>.from(await call('/api/feedback', body: body) as Map);

  /// 发过的反馈（存在电脑上，几台设备发的都在）
  Future<List<Map<String, dynamic>>> feedbackHistory() async {
    final j = await call('/api/feedback') as Map;
    return [for (final x in j['items'] as List) Map<String, dynamic>.from(x as Map)];
  }

  Future<Map<String, dynamic>> updateInfo(String platform, String abi) async => Map<String, dynamic>.from(
      await call('/api/update/mobile', query: {'platform': platform, 'abi': abi},
          timeout: const Duration(seconds: 45)) as Map);

  /// 从电脑下载新版安装包（电脑已经校验过；这里再核对一次大小和 sha256）
  Future<File> downloadUpdate(String key, File dst, int size, String sha256hex,
      void Function(int got) onProgress) {
    return endpoints.run((base) async {
      final b = Uri.parse(base);
      final uri = b.replace(path: '${b.path.replaceAll(RegExp(r'/+$'), '')}/api/update/file/$key');
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 6);
      try {
        final req = await client.getUrl(uri);
        req.headers.set('X-Token', s.token);
        final resp = await req.close().timeout(const Duration(minutes: 5));
        if (resp.statusCode != 200) {
          final text = await resp.transform(utf8.decoder).join();
          String detail = 'HTTP ${resp.statusCode}';
          try { detail = '${(jsonDecode(text) as Map)['detail'] ?? detail}'; } catch (_) {}
          throw ApiException(detail, status: resp.statusCode);
        }
        await dst.parent.create(recursive: true);
        final sink = dst.openWrite();
        var got = 0;
        await for (final chunk in resp.timeout(const Duration(seconds: 60))) {
          sink.add(chunk);
          got += chunk.length;
          onProgress(got);
        }
        await sink.close();
        final digest = await sha256.bind(dst.openRead()).first;
        if (got != size || digest.toString() != sha256hex) {
          await dst.delete().catchError((_) => dst);
          throw ApiException('下载的安装包校验不通过，已删除，请重试');
        }
        return dst;
      } finally {
        client.close(force: true);
      }
    });
  }

  Future<Map<String, dynamic>> getConfig() async =>
      Map<String, dynamic>.from(await call('/api/config') as Map);

  Future<void> setConfig(Map<String, dynamic> patch) async {
    await call('/api/config', body: patch);
  }

  Future<void> reviewNow() async {
    await call('/api/review_now', post: true);
  }

  Future<void> retryReview(int id) async {
    await call('/api/retry_review/$id', post: true);
  }

  /// kind: llm / nas / stt
  Future<String> test(String kind) async {
    final j = await call('/api/test/$kind', post: true, timeout: const Duration(minutes: 3)) as Map;
    return '${j['ok'] == true ? '✅' : '❌'} ${j['msg']}';
  }
}
