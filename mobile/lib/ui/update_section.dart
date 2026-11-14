import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import '../android_bridge.dart';
import '../app_state.dart';

/// 这个 App 的版本号：云端打包时用 --dart-define=APP_VERSION=… 传进来（和电脑端同一个版本号）
const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: '0.9.2');

List<int> _parse(String v) =>
    v.replaceFirst(RegExp(r'^[vV]'), '').split('.').map((p) => int.tryParse(p.replaceAll(RegExp(r'\D'), '')) ?? 0).toList();

bool newer(String a, String b) {
  final x = _parse(a), y = _parse(b);
  for (var i = 0; i < 3; i++) {
    final p = i < x.length ? x[i] : 0, q = i < y.length ? y[i] : 0;
    if (p != q) return p > q;
  }
  return false;
}

/// 设置页里的「软件更新」：通过电脑检查新版本；安卓下载后打开系统安装界面，iPhone 只提示
class UpdateSection extends StatefulWidget {
  const UpdateSection({super.key, required this.app});
  final AppState app;

  @override
  State<UpdateSection> createState() => _UpdateSectionState();
}

class _UpdateSectionState extends State<UpdateSection> {
  Map<String, dynamic>? _info;
  bool _checking = false;
  double? _progress;     // 下载中：0–1
  String _msg = '';

  bool get _available {
    final latest = '${_info?['latest'] ?? ''}';
    return latest.isNotEmpty && newer(latest, appVersion) && _info?['asset'] != null;
  }

  Future<void> _check() async {
    setState(() {
      _checking = true;
      _msg = '';
    });
    try {
      final abi = await AndroidBridge.abi();
      final info = await widget.app.api.updateInfo(Platform.isIOS ? 'ios' : 'android', abi);
      setState(() {
        _info = info;
        final err = '${info['error'] ?? ''}';
        _msg = err.isNotEmpty ? err : (_available ? '' : '已经是最新版本');
      });
    } catch (e) {
      setState(() => _msg = '检查失败：$e（要先连上电脑）');
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _install() async {
    final a = Map<String, dynamic>.from(_info!['asset'] as Map);
    final size = (a['size'] as num).toInt();
    setState(() {
      _progress = 0;
      _msg = '';
    });
    try {
      final dir = Directory('${(await getTemporaryDirectory()).path}/updates');
      if (await dir.exists()) await dir.delete(recursive: true);   // 只留这一个版本
      final file = await widget.app.api.downloadUpdate('${a['key']}', File('${dir.path}/${a['name']}'), size,
          '${a['sha256']}', (got) {
        if (mounted) setState(() => _progress = got / size);
      });
      final r = await AndroidBridge.installApk(file.path);
      setState(() => _msg = r == 'need_permission'
          ? '请在打开的设置页里允许“安装未知应用”，然后回来再点一次「下载并安装」'
          : '已打开安装界面，点「安装」即可（录音会先停止，装好后重新打开 App）');
    } catch (e) {
      setState(() => _msg = '更新失败：$e');
    } finally {
      if (mounted) setState(() => _progress = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final latest = '${_info?['latest'] ?? ''}';
    final notes = '${_info?['notes'] ?? ''}';
    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('软件更新', style: t.textTheme.titleMedium?.copyWith(color: t.colorScheme.primary)),
        const SizedBox(height: 4),
        Text('当前版本 $appVersion${_info != null ? ' · 电脑端 ${_info!['desktop_version']}' : ''}',
            style: TextStyle(color: t.colorScheme.outline)),
        const SizedBox(height: 8),
        if (_available) ...[
          Text('有新版本 $latest', style: TextStyle(color: t.colorScheme.primary, fontWeight: FontWeight.w600)),
          if (notes.isNotEmpty)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text(notes, style: t.textTheme.bodySmall)),
          const SizedBox(height: 8),
        ],
        if (_progress != null) ...[
          LinearProgressIndicator(value: _progress),
          const SizedBox(height: 4),
          Text('正在从电脑下载 ${((_progress ?? 0) * 100).round()}%', style: t.textTheme.bodySmall),
        ],
        Wrap(spacing: 8, runSpacing: 8, children: [
          OutlinedButton(onPressed: _checking || _progress != null ? null : _check,
              child: Text(_checking ? '正在检查…' : '检查更新')),
          if (_available && Platform.isAndroid)
            FilledButton(onPressed: _progress != null ? null : _install, child: const Text('下载并安装')),
        ]),
        if (_available && Platform.isIOS)
          Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text((_info?['asset'] as Map?)?['key'] == 'ios-signed'
                  ? '新版已经签好名：在电脑上用爱思助手或 Sideloadly 把 AIMind-…-ios.ipa 装到手机即可（苹果不允许未上架的 App 自己更新）。'
                  : 'iPhone 版需要在电脑上用 Sideloadly 签名安装新版本（苹果不允许未上架的 App 自己更新）。')),
        if (_msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_msg)),
      ]),
    );
  }
}
