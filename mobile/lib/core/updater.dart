/// 手机直接在线更新（不经过电脑）：从发布仓库拿更新清单 → 验数字签名 → 下载安装包 → 核对大小和 sha256。
/// 和电脑端 server/aimind/updater.py 是同一套清单、同一把公钥、同样的线路（直连 GitHub + 几个下载镜像）。
/// 走哪条线路都不影响安全：清单被改过签名就对不上，安装包被改过 sha256 就对不上。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;

const updateRepo = 'W123456789AWM-hue/aimind-releases';
const manifestUrl = 'https://github.com/$updateRepo/releases/latest/download/latest.json';
const updatePublicKey = 'JEm27iMP2XRcLJ95mRWP1Q74taIq81YAplvj6Ejgpxo='; // 和 server/aimind/version.py 里的一致
const fallbackMirrors = ['https://gh-proxy.com/', 'https://ghfast.top/', 'https://ghproxy.net/'];

class UpdateException implements Exception {
  UpdateException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// 验签并解析清单；签名不对直接拒绝
Map<String, dynamic> verifyManifest(Uint8List raw, String sigB64, {String publicKey = updatePublicKey}) {
  var ok = false;
  try {
    ok = ed.verify(ed.PublicKey(base64Decode(publicKey)), raw, base64Decode(sigB64.trim()));
  } catch (_) {}
  if (!ok) throw UpdateException('更新清单的签名验证不通过，已拒绝（可能被篡改，或者下载不完整）');
  final m = jsonDecode(utf8.decode(raw));
  if (m is! Map || m['version'] is! String || m['assets'] is! Map) throw UpdateException('更新清单格式不对');
  return Map<String, dynamic>.from(m);
}

class MobileUpdater {
  MobileUpdater({this.mirror = '', this.manifest = manifestUrl, this.publicKey = updatePublicKey});

  final String mirror; // 用户自己填的镜像（可不填）
  final String manifest;
  final String publicKey;
  static String? _good; // 上次成功的线路，下次先试它

  List<String> get _routes {
    final list = <String>[if (mirror.isNotEmpty) mirror, '', ...fallbackMirrors.where((m) => m != mirror)];
    final g = _good;
    if (g != null && list.remove(g)) list.insert(0, g);
    return list;
  }

  static String _with(String url, String m) =>
      m.isEmpty || !url.startsWith('https://github.com/') ? url : '${m.replaceAll(RegExp(r'/+$'), '')}/$url';

  /// 按线路依次尝试；[use] 抛错也会换下一条
  Future<T> _try<T>(String url, Future<T> Function(HttpClientResponse) use) async {
    Object? last;
    for (final m in _routes) {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
      try {
        final req = await client.getUrl(Uri.parse(_with(url, m)));
        req.headers.set('User-Agent', 'AIMind-Mobile');
        final resp = await req.close().timeout(const Duration(seconds: 20));
        if (resp.statusCode != 200) throw UpdateException('HTTP ${resp.statusCode}');
        final out = await use(resp);
        _good = m;
        return out;
      } catch (e) {
        last = e;
      } finally {
        client.close(force: true);
      }
    }
    throw UpdateException('连不上发布服务器（试过 ${_routes.length} 条线路）。换个网络再试，或者连上电脑后通过电脑更新。\n最后的错误：$last');
  }

  Future<Uint8List> _bytes(String url) => _try(url, (r) async {
        final b = BytesBuilder(copy: false);
        await for (final c in r.timeout(const Duration(seconds: 20))) {
          b.add(c);
          if (b.length > (1 << 20)) throw UpdateException('清单太大，不对劲');
        }
        return b.takeBytes();
      });

  Future<Map<String, dynamic>> fetchManifest() async {
    final raw = await _bytes(manifest);
    final sig = await _bytes('$manifest.sig');
    return verifyManifest(raw, utf8.decode(sig), publicKey: publicKey);
  }

  /// 下载清单里的一个安装包到 [dst]，核对大小和 sha256
  Future<File> download(Map<String, dynamic> asset, File dst, void Function(int got) onProgress) async {
    final size = (asset['size'] as num).toInt();
    await dst.parent.create(recursive: true);
    return _try('${asset['url']}', (resp) async {
      final sink = dst.openWrite();
      var got = 0;
      try {
        await for (final c in resp.timeout(const Duration(seconds: 60))) {
          sink.add(c);
          got += c.length;
          onProgress(got);
        }
      } finally {
        await sink.close();
      }
      final digest = await sha256.bind(dst.openRead()).first;
      if (got != size || digest.toString() != '${asset['sha256']}') {
        await dst.delete().catchError((_) => dst);
        throw UpdateException('下载的安装包校验不通过，已删除');
      }
      return dst;
    });
  }
}
