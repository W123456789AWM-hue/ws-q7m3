import 'dart:async';
import 'dart:convert';
import 'dart:io';

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
