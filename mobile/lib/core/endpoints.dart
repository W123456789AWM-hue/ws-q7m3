import 'dart:async';
import 'dart:io';

import 'settings.dart';

/// 电脑明确返回了错误（口令不对、参数错等）——换地址也没用
class ApiException implements Exception {
  ApiException(this.message, {this.status = 0});
  final String message;
  final int status;
  @override
  String toString() => message;
}

/// 电脑有两个地址：家里 WiFi 用的局域网地址，和外出时用的备用地址（如 Tailscale）。
/// 哪个能连上用哪个，并记住上次成功的那个，下次先试它。
class Endpoints {
  Endpoints(this.s);
  final AppSettings s;
  String _preferred = '';

  List<String> get all => [s.serverUrl, s.serverUrl2].where((u) => u.isNotEmpty).toList();

  /// 当前在用的地址（给界面显示）
  String get active => all.contains(_preferred) ? _preferred : (all.isEmpty ? '' : all.first);

  bool get usingBackup => s.serverUrl2.isNotEmpty && active == s.serverUrl2;

  Future<T> run<T>(Future<T> Function(String base) fn) async {
    final list = all;
    if (list.isEmpty) throw ApiException('还没填写电脑地址（设置 → 连接电脑）');
    final order = [active, ...list.where((u) => u != active)];
    Object? last;
    for (final u in order) {
      try {
        final r = await fn(u);
        _preferred = u;
        return r;
      } on ApiException {
        rethrow;
      } catch (e) {
        last = e; // 连接层面的失败：试下一个地址
      }
    }
    if (last is TimeoutException) {
      throw ApiException('连接电脑超时：电脑开着吗？${list.length > 1 ? '两个地址都试过了' : '手机和电脑在同一个网络吗？'}');
    }
    if (last is SocketException || last is HandshakeException) {
      throw ApiException('连不上电脑：检查地址、网络，以及电脑防火墙是否允许');
    }
    throw ApiException('连接出错：$last');
  }
}
