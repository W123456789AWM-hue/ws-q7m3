import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../android_bridge.dart';
import '../app_state.dart';
import '../core/util.dart';
import 'sfx.dart';
import 'theme.dart';
import 'widgets.dart';

List<Map<String, dynamic>> asMaps(Object? v) =>
    [for (final e in (v as List? ?? const [])) Map<String, dynamic>.from(e as Map)];

/// 首页：大录音按钮（外圈跟着音量动）+ 状态 + 本场的 AI 复盘 / 听写
class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.app, this.onOpenSettings});
  final AppState app;
  final VoidCallback? onOpenSettings;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  AppState get app => widget.app;
  StreamSubscription<String>? _msgSub;
  bool _batteryOk = true;
  int _tab = 0; // 0 = AI 复盘，1 = 听写
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 2400));

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _msgSub = app.messages.stream.listen(_toast);
    app.addListener(_syncPulse);
    _checkBattery();
    if (app.settings.autoStart) {
      // 等界面出来后再开始（安卓要求在前台时启动麦克风服务）
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!app.recording) app.startRecording();
      });
    }
  }

  void _syncPulse() {
    if (app.recording && !_pulse.isAnimating) _pulse.repeat();
    if (!app.recording && _pulse.isAnimating) _pulse.stop();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    app.removeListener(_syncPulse);
    _msgSub?.cancel();
    _pulse.dispose();
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
    final c = context.c;
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListenableBuilder(
          listenable: app,
          builder: (context, _) {
            final s = app.view?['session'] as Map?;
            final reviews = asMaps(s?['reviews']);
            final paragraphs = asMaps(s?['paragraphs']);
            final summary = '${s?['summary'] ?? ''}';
            return RefreshIndicator(
              onRefresh: () => app.refresh(force: true),
              child: CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
                slivers: [
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(20, 14, 16, 2),
                      child: Row(children: [
                        Expanded(child: Text('AI 录音思考', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, letterSpacing: -.6))),
                        Pressable(
                          onTap: widget.onOpenSettings,
                          child: Pill(app.standalone ? '手机独立复盘' : '连接电脑',
                              color: app.standalone ? c.purple : c.accent,
                              icon: app.standalone ? Icons.smartphone_rounded : Icons.computer_rounded),
                        ),
                      ]),
                    ),
                  ),
                  if (Platform.isAndroid && !_batteryOk) SliverToBoxAdapter(child: _batteryBanner()),
                  SliverToBoxAdapter(child: app.configured ? _hero(context) : _welcome(context)),
                  SliverPersistentHeader(
                    pinned: true, // 往下翻时这一条留在顶上，随时能切换
                    delegate: _PinnedHeader(
                      color: c.bg,
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                        child: Segmented(
                          labels: ['AI 复盘${reviews.isEmpty ? '' : ' ${reviews.length}'}', '听写'],
                          index: _tab,
                          onChanged: (i) => setState(() => _tab = i),
                        ),
                      ),
                    ),
                  ),
                  SliverToBoxAdapter(
                    child: AnimatedSwitcher(
                      duration: Motion.normal,
                      switchInCurve: Motion.easeOut,
                      switchOutCurve: Motion.ease,
                      transitionBuilder: (child, a) => FadeTransition(
                        opacity: a,
                        child: SlideTransition(position: Tween(begin: const Offset(0, .02), end: Offset.zero).animate(a), child: child),
                      ),
                      layoutBuilder: (cur, prev) => Stack(alignment: Alignment.topCenter, children: [...prev, if (cur != null) cur]),
                      child: _tab == 0
                          ? _reviews(context, reviews, summary, key: const ValueKey('r'))
                          : TranscriptList(paragraphs.reversed.toList(), key: const ValueKey('t'), shrinkWrap: true),
                    ),
                  ),
                  const SliverToBoxAdapter(child: SizedBox(height: 28)),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _batteryBanner() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
          decoration: BoxDecoration(color: context.c.orange.withValues(alpha: .14), borderRadius: BorderRadius.circular(14)),
          child: Row(children: [
            Icon(Icons.battery_alert_rounded, color: context.c.orange, size: 20),
            const SizedBox(width: 8),
            const Expanded(child: Text('建议关闭电池优化，否则息屏后系统可能停掉录音', style: TextStyle(fontSize: 13))),
            TextButton(
              onPressed: () async {
                await AndroidBridge.requestIgnoreBatteryOptimizations();
                await Future<void>.delayed(const Duration(seconds: 3));
                _checkBattery();
              },
              child: const Text('去设置'),
            ),
            IconButton(visualDensity: VisualDensity.compact, onPressed: () => setState(() => _batteryOk = true), icon: const Icon(Icons.close, size: 18)),
          ]),
        ),
      );

  /// 第一次打开：还没连电脑，也没开独立模式
  Widget _welcome(BuildContext context) {
    final c = context.c;
    return Appear(
      child: Card(
        margin: const EdgeInsets.fromLTRB(16, 14, 16, 6),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('先选一种用法', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            _choice(Icons.computer_rounded, c.accent, '连接电脑（推荐）', '手机只录音，AI 复盘在电脑上做，结果存电脑和 NAS。\n在电脑上打开「设备连接」，把地址和口令填到设置里。'),
            const SizedBox(height: 10),
            _choice(Icons.smartphone_rounded, c.purple, '手机独立复盘', '不用电脑：手机直接把录音交给 AI，结果存在手机上。\n需要在设置里填你自己的 AI 接口 Key。'),
            const SizedBox(height: 14),
            SizedBox(width: double.infinity, child: FilledButton(onPressed: widget.onOpenSettings, child: const Text('去设置'))),
          ]),
        ),
      ),
    );
  }

  Widget _choice(IconData icon, Color col, String title, String sub) => Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(color: col.withValues(alpha: .16), borderRadius: BorderRadius.circular(9)),
          child: Icon(icon, color: col, size: 19),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
            const SizedBox(height: 2),
            Text(sub, style: TextStyle(color: context.c.label2, fontSize: 13, height: 1.45)),
          ]),
        ),
      ]);

  // ---------------- 状态文字 ----------------
  /// (文字, 是不是出了问题)
  List<(String, bool)> _statusLines() {
    final out = <(String, bool)>[];
    if (app.standalone) {
      final s = app.view?['session'] as Map?;
      if (app.engine.working.isNotEmpty) out.add((app.engine.working, false));
      final n = app.view?['next_review'] as Map?;
      if (n != null && app.engine.working.isEmpty) {
        final left = (n['seconds_left'] as num?)?.toInt() ?? 0;
        out.add(('下次复盘 ${fmtDuration(Duration(seconds: left))} 后 · 新录音 ${n['new_chars']} 秒', false));
      }
      if (app.settings.aiKey.isEmpty) out.add(('还没填 AI 的 API Key（设置 → 手机独立复盘）', true));
      if ('${s?['summary_error'] ?? ''}'.isNotEmpty) out.add(('总复盘没做成：${s?['summary_error']}', true));
      return out;
    }
    final u = app.uploader;
    final mb = (u.pendingBytes / (1024 * 1024)).toStringAsFixed(1);
    final wait = u.pendingCount > 0 ? '待上传 ${u.pendingCount} 片（$mb MB）' : '';
    switch (u.state) {
      case 'uploading':
        out.add(('正在传给电脑… $wait', false));
      case 'waiting_wifi':
        out.add(('现在不是 WiFi，录音先存在手机里 · $wait', false));
      case 'no_server':
        out.add(('还没设置电脑地址 · $wait', true));
      case 'error':
        out.add(('${u.lastError} · $wait · 会自动重试', true));
      default:
        if (u.pendingCount > 0) {
          out.add((wait, false));
        } else if (u.lastOk != null) {
          out.add(('录音已全部传到电脑（${fmtClock(u.lastOk!)}）', false));
        }
    }
    if (app.viewError.isNotEmpty) {
      out.add(('电脑：${app.viewError}', true));
    } else if (app.view != null) {
      final v = app.view!;
      final backlog = (v['backlog'] as num?)?.toInt() ?? 0;
      final parts = <String>[];
      if (backlog > 0) parts.add('电脑还有 $backlog 片等待处理');
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
      if (parts.isNotEmpty) out.add((parts.join(' · '), false));
    }
    return out;
  }

  Widget _hero(BuildContext context) {
    final c = context.c;
    final recording = app.recording;
    final level = ((app.spool.levelDb + 60) / 60).clamp(0.0, 1.0);
    final start = app.recordStart;
    final total = recording && start != null ? DateTime.now().difference(start) : Duration.zero;
    final canReviewNow = app.standalone ? recording : app.view?['recording'] == true;
    final connected = app.standalone || (app.view != null && app.viewError.isEmpty);
    final lines = _statusLines();

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      child: Column(children: [
        const SizedBox(height: 14),
        // 录音按钮
        SizedBox(
          width: 220,
          height: 220,
          child: AnimatedBuilder(
            animation: _pulse,
            builder: (context, child) => CustomPaint(
              painter: _OrbPainter(
                  t: _pulse.value, level: recording ? level : 0, color: recording ? c.red : c.accent, active: recording),
              child: child,
            ),
            child: Center(
              child: Pressable(
                scale: .93,
                onTap: app.starting
                    ? null
                    : () {
                        HapticFeedback.mediumImpact();
                        recording ? app.stopRecording() : app.startRecording();
                      },
                child: AnimatedContainer(
                  duration: Motion.slow,
                  curve: Motion.ease,
                  width: 116,
                  height: 116,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: recording ? [c.red, Color.lerp(c.red, c.orange, .35)!] : [c.accent, Color.lerp(c.accent, c.tech, .55)!],
                    ),
                    boxShadow: [BoxShadow(color: (recording ? c.red : c.accent).withValues(alpha: .45), blurRadius: 34, spreadRadius: -6, offset: const Offset(0, 12))],
                  ),
                  child: AnimatedSwitcher(
                    duration: Motion.normal,
                    switchInCurve: Motion.easeOut,
                    transitionBuilder: (child, a) => ScaleTransition(scale: a, child: FadeTransition(opacity: a, child: child)),
                    child: app.starting
                        ? const SizedBox(key: ValueKey('w'), width: 30, height: 30, child: CircularProgressIndicator(strokeWidth: 3, color: Colors.white))
                        : Icon(recording ? Icons.stop_rounded : Icons.mic_rounded, key: ValueKey(recording), color: Colors.white, size: 52),
                  ),
                ),
              ),
            ),
          ),
        ),
        // 计时
        AnimatedSwitcher(
          duration: Motion.normal,
          child: recording
              ? Text(fmtDuration(total),
                  key: const ValueKey('time'),
                  style: TextStyle(fontSize: 40, fontWeight: FontWeight.w300, letterSpacing: 1, color: c.label, fontFeatures: const [FontFeature.tabularFigures()]))
              : Text('点一下开始录音', key: const ValueKey('idle'), style: TextStyle(fontSize: 17, color: c.label2, fontWeight: FontWeight.w500)),
        ),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.center, children: [
          if (recording) Pill('录音中', color: c.red, icon: Icons.fiber_manual_record),
          if (!app.standalone)
            Pill(connected ? (app.endpoints.usingBackup ? '电脑已连接 · 外出线路' : '电脑已连接') : '电脑没连上',
                color: connected ? c.green : c.orange, icon: connected ? Icons.check_circle_rounded : Icons.error_rounded),
          if (canReviewNow)
            Pressable(
              onTap: () => _do(app.reviewNow, app.standalone ? '已复盘' : '已让电脑立即复盘'),
              child: Pill('立即复盘', color: c.accent, icon: Icons.auto_awesome),
            ),
        ]),
        AnimatedSize(
          duration: Motion.normal,
          curve: Motion.ease,
          alignment: Alignment.topCenter,
          child: Padding(
            padding: EdgeInsets.only(top: lines.isEmpty ? 0 : 10),
            child: Column(children: [
              for (final (text, bad) in lines)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Text(text,
                      textAlign: TextAlign.center,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 12.5, height: 1.4, color: bad ? c.red : c.label2)),
                ),
            ]),
          ),
        ),
      ]),
    );
  }

  Widget _reviews(BuildContext context, List<Map<String, dynamic>> reviews, String summary, {Key? key}) {
    final c = context.c;
    if (reviews.isEmpty && summary.isEmpty) {
      final where = app.standalone ? '手机会按设置的间隔把录音交给 AI 听并复盘' : '电脑会按你设置的方式（实时 / 周期）把录音交给 AI 听并复盘';
      return Padding(
        key: key,
        padding: const EdgeInsets.fromLTRB(36, 36, 36, 12),
        child: Column(children: [
          Icon(Icons.auto_awesome, size: 34, color: c.label3),
          const SizedBox(height: 12),
          Text(app.recording ? '正在录音。\n$where，结果会出现在这里。' : '像平常一样说话就行。\n$where，\n帮你找盲点、潜在需求和新的思路。',
              textAlign: TextAlign.center, style: TextStyle(color: c.label2, height: 1.7, fontSize: 14)),
        ]),
      );
    }
    final sid = '${(app.view?['session'] as Map?)?['id'] ?? ''}';
    return Column(key: key, children: [
      if (summary.isNotEmpty) Appear(child: SummaryCard(summary)),
      for (final (i, r) in reviews.reversed.indexed)
        Appear(
          key: ValueKey('rv$sid-${r['id']}'),
          delay: Duration(milliseconds: math.min(i, 5) * 45),
          child: ReviewCard(r, onRetry: () => _do(() => app.retryReview(r['id'] as int), app.standalone ? '已重试' : '已让电脑重试')),
        ),
    ]);
  }
}

class _PinnedHeader extends SliverPersistentHeaderDelegate {
  _PinnedHeader({required this.child, required this.color});
  final Widget child;
  final Color color;

  @override
  double get minExtent => 52;
  @override
  double get maxExtent => 52;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) => ColoredBox(color: color, child: child);

  @override
  bool shouldRebuild(_PinnedHeader old) => true;
}

/// 录音按钮外面的光圈：没录音时是一圈细线；录音时两圈波纹向外扩散，粗细和大小跟着音量变
class _OrbPainter extends CustomPainter {
  _OrbPainter({required this.t, required this.level, required this.color, required this.active});
  final double t, level;
  final Color color;
  final bool active;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    const r0 = 58.0;
    final ring = Paint()..style = PaintingStyle.stroke;
    if (!active) {
      canvas.drawCircle(center, r0 + 14, ring..color = color.withValues(alpha: .18)..strokeWidth = 1);
      canvas.drawCircle(center, r0 + 30, ring..color = color.withValues(alpha: .08)..strokeWidth = 1);
      return;
    }
    // 音量光晕
    canvas.drawCircle(center, r0 + 10 + level * 30, Paint()..color = color.withValues(alpha: .10 + level * .16));
    for (final phase in [0.0, .5]) {
      final p = (t + phase) % 1;
      canvas.drawCircle(center, r0 + 8 + p * 46, ring
        ..color = color.withValues(alpha: (1 - p) * .38)
        ..strokeWidth = 1.5 + level * 2.5);
    }
  }

  @override
  bool shouldRepaint(_OrbPainter o) => o.t != t || o.level != level || o.color != color || o.active != active;
}

/// 分段选择（两三个选项，选中的那块滑过去）
class Segmented extends StatelessWidget {
  const Segmented({super.key, required this.labels, required this.index, required this.onChanged});
  final List<String> labels;
  final int index;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      height: 36,
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(color: c.fill.withValues(alpha: .14), borderRadius: BorderRadius.circular(10)),
      child: Stack(children: [
        AnimatedAlign(
          alignment: Alignment(labels.length == 1 ? 0 : -1 + 2 * index / (labels.length - 1), 0),
          duration: Motion.normal,
          curve: Motion.ease,
          child: FractionallySizedBox(
            widthFactor: 1 / labels.length,
            heightFactor: 1,
            child: Container(
              decoration: BoxDecoration(
                color: c.surface,
                borderRadius: BorderRadius.circular(8),
                boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .12), blurRadius: 6, offset: const Offset(0, 2))],
              ),
            ),
          ),
        ),
        Row(children: [
          for (var i = 0; i < labels.length; i++)
            Expanded(
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () {
                  if (i != index) {
                    HapticFeedback.selectionClick();
                    Sfx.tap();
                  }
                  onChanged(i);
                },
                child: Center(
                  child: AnimatedDefaultTextStyle(
                    duration: Motion.fast,
                    style: Theme.of(context).textTheme.bodyMedium!.copyWith(fontSize: 14, color: c.label, fontWeight: i == index ? FontWeight.w600 : FontWeight.w400),
                    child: Text(labels[i]),
                  ),
                ),
              ),
            ),
        ]),
      ]),
    );
  }
}
