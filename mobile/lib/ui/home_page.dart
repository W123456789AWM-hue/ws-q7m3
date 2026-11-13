import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../android_bridge.dart';
import '../app_state.dart';
import '../core/util.dart';
import 'daily_page.dart';
import 'history_page.dart';
import 'settings_page.dart';
import 'widgets.dart';

List<Map<String, dynamic>> asMaps(Object? v) =>
    [for (final e in (v as List? ?? const [])) Map<String, dynamic>.from(e as Map)];

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.app});
  final AppState app;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  AppState get app => widget.app;
  StreamSubscription<String>? _msgSub;
  bool _batteryOk = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _msgSub = app.messages.stream.listen(_toast);
    _checkBattery();
    if (app.settings.autoStart) {
      // 等界面出来后再开始（安卓要求在前台时启动麦克风服务）
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!app.recording) app.startRecording();
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _msgSub?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    app.foreground = state == AppLifecycleState.resumed;
    if (app.foreground) app.refresh();
  }

  void _toast(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(m), duration: const Duration(seconds: 4)));
  }

  Future<void> _checkBattery() async {
    final ok = await AndroidBridge.isIgnoringBatteryOptimizations();
    if (mounted) setState(() => _batteryOk = ok);
  }

  void _push(Widget page) =>
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => page));

  Future<void> _do(Future<void> Function() fn, String okMsg) async {
    try {
      await fn();
      _toast(okMsg);
      await app.refresh(force: true);
    } catch (e) {
      _toast('$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('AI 录音思考'),
          actions: [
            IconButton(
                tooltip: '日 / 月 / 年复盘',
                icon: const Icon(Icons.today),
                onPressed: () => _push(DailyPage(app: app))),
            IconButton(
                tooltip: '历史',
                icon: const Icon(Icons.history),
                onPressed: () => _push(HistoryPage(app: app))),
            IconButton(
                tooltip: '设置',
                icon: const Icon(Icons.settings),
                onPressed: () => _push(SettingsPage(app: app))),
          ],
        ),
        body: ListenableBuilder(
          listenable: app,
          builder: (context, _) {
            final s = app.view?['session'] as Map?;
            final reviews = asMaps(s?['reviews']);
            final paragraphs = asMaps(s?['paragraphs']);
            return Column(children: [
              if (Platform.isAndroid && !_batteryOk) _batteryBanner(),
              _statusCard(context),
              const TabBar(tabs: [Tab(text: 'AI 复盘'), Tab(text: '转写')]),
              Expanded(
                child: TabBarView(children: [
                  _reviewTab(context, reviews, '${s?['summary'] ?? ''}'),
                  TranscriptList(paragraphs.reversed.toList()),
                ]),
              ),
            ]);
          },
        ),
      ),
    );
  }

  Widget _batteryBanner() => MaterialBanner(
        content: const Text('建议关闭电池优化，否则系统可能在息屏后停掉录音'),
        leading: const Icon(Icons.battery_alert),
        actions: [
          TextButton(
            onPressed: () async {
              await AndroidBridge.requestIgnoreBatteryOptimizations();
              await Future<void>.delayed(const Duration(seconds: 3));
              _checkBattery();
            },
            child: const Text('去设置'),
          ),
          TextButton(
              onPressed: () => setState(() => _batteryOk = true), child: const Text('忽略')),
        ],
      );

  /// 上传状态的一句话
  String _uploadLine() {
    final u = app.uploader;
    final mb = (u.pendingBytes / (1024 * 1024)).toStringAsFixed(1);
    final wait = u.pendingCount > 0 ? '待上传 ${u.pendingCount} 片（$mb MB）' : '';
    switch (u.state) {
      case 'uploading':
        return '正在传给电脑… $wait';
      case 'waiting_wifi':
        return '现在不是 WiFi，录音先存在手机里（设置里可改成用移动网络也传）· $wait';
      case 'no_server':
        return '还没设置电脑地址 · $wait';
      case 'error':
        return '${u.lastError} · $wait · 会自动重试';
      default:
        if (u.pendingCount > 0) return wait;
        return u.lastOk == null ? '' : '录音已全部传到电脑（${fmtClock(u.lastOk!)}）';
    }
  }

  /// 电脑端状态的一句话
  String _serverLine() {
    if (!app.configured) return '';
    if (app.viewError.isNotEmpty) return '电脑：${app.viewError}';
    final v = app.view;
    if (v == null) return '正在连接电脑…';
    final backlog = (v['backlog'] as num?)?.toInt() ?? 0;
    final parts = <String>[app.endpoints.usingBackup ? '电脑：已连接（外出线路）' : '电脑：已连接'];
    if (backlog > 0) parts.add('还有 $backlog 片等待处理');
    final n = v['next_review'] as Map?;
    if (n != null) {
      final unit = '${n['unit'] ?? '字'}';
      final amount = n['new_chars'] is num ? (n['new_chars'] as num).round() : n['new_chars'];
      if (n['mode'] == 'realtime') {
        parts.add('实时复盘（已积累 $amount $unit）');
      } else {
        final left = (n['seconds_left'] as num?)?.toInt() ?? 0;
        parts.add('下次复盘 ${fmtDuration(Duration(seconds: left))} 后（新内容 $amount $unit）');
      }
    } else if ((v['session'] as Map?)?['status'] == 'finishing') {
      parts.add('正在生成整场总复盘');
    }
    return parts.join(' · ');
  }

  Widget _statusCard(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline);
    final recording = app.recording;

    if (!app.configured) {
      return Card(
        margin: const EdgeInsets.all(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('先连接电脑', style: theme.textTheme.titleMedium),
            const SizedBox(height: 6),
            const Text('手机只负责录音，语音识别和 AI 复盘在电脑上完成。\n'
                '在电脑上打开「AI 录音思考助手」，点「设备连接」，把里面的地址和口令填到这里的设置里。'),
            const SizedBox(height: 10),
            FilledButton.icon(
              icon: const Icon(Icons.settings),
              label: const Text('去设置'),
              onPressed: () => _push(SettingsPage(app: app)),
            ),
          ]),
        ),
      );
    }

    final level = ((app.spool.levelDb + 60) / 60).clamp(0.0, 1.0);
    final start = app.recordStart;
    final total = recording && start != null ? DateTime.now().difference(start) : Duration.zero;
    final serverRecording = app.view?['recording'] == true;
    final up = _uploadLine();
    final sv = _serverLine();
    final problem = app.uploader.state == 'error' || app.viewError.isNotEmpty;

    return Card(
      margin: const EdgeInsets.all(12),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(recording ? '● 录音中  ${fmtDuration(total)}' : '未录音',
                  style: theme.textTheme.titleMedium
                      ?.copyWith(color: recording ? theme.colorScheme.error : null)),
            ),
            if (serverRecording)
              OutlinedButton(
                onPressed: () => _do(app.api.reviewNow, '已让电脑立即复盘'),
                child: const Text('立即复盘'),
              ),
          ]),
          const SizedBox(height: 8),
          LinearProgressIndicator(value: recording ? level : 0),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                  backgroundColor: recording ? theme.colorScheme.error : null),
              icon: app.starting
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : Icon(recording ? Icons.stop : Icons.mic),
              label: Text(recording ? '停止录音' : '开始录音'),
              onPressed: app.starting
                  ? null
                  : () => recording ? app.stopRecording() : app.startRecording(),
            ),
          ),
          if (up.isNotEmpty)
            Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(up, style: muted, maxLines: 2, overflow: TextOverflow.ellipsis)),
          if (sv.isNotEmpty)
            Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(sv,
                    style: problem && app.viewError.isNotEmpty
                        ? muted?.copyWith(color: theme.colorScheme.error)
                        : muted,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis)),
        ]),
      ),
    );
  }

  Widget _reviewTab(
      BuildContext context, List<Map<String, dynamic>> reviews, String summary) {
    final theme = Theme.of(context);
    if (reviews.isEmpty && summary.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            app.recording
                ? '录音正在传给电脑。\n电脑会按你设置的方式（实时 / 周期）把录音交给 AI 听并复盘，结果会出现在这里。'
                : '点「开始录音」，像平常一样说话。\n\n手机只录音；电脑把录音交给 AI 听，做发散复盘，\n结果会自动显示在这里，并同步到 NAS。',
            textAlign: TextAlign.center,
            style: TextStyle(color: theme.colorScheme.outline, height: 1.7),
          ),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: () => app.refresh(force: true),
      child: ListView(
        padding: const EdgeInsets.only(top: 6, bottom: 24),
        children: [
          if (summary.isNotEmpty) SummaryCard(summary),
          for (final r in reviews.reversed)
            ReviewCard(r,
                onRetry: () => _do(() => app.api.retryReview(r['id'] as int), '已让电脑重试')),
        ],
      ),
    );
  }
}
