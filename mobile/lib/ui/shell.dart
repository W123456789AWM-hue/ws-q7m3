import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_state.dart';
import 'daily_page.dart';
import 'history_page.dart';
import 'home_page.dart';
import 'settings_page.dart';
import 'splash.dart';
import 'theme.dart';
import 'update_section.dart';

/// App 的外壳：底部四个标签（录音 / 报告 / 历史 / 设置）+ 启动动画。
/// 切换标签时内容淡入并轻微放大；每个标签第一次点到才创建，之后保留状态（设置填到一半切走不会丢）。
class Shell extends StatefulWidget {
  const Shell({super.key, required this.app});
  final AppState app;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _tab = 0;
  final _built = <int>{0};
  final _gen = [0, 0, 0, 0]; // 报告、历史每次点进去重新读一遍
  late bool _splash = widget.app.settings.splash;

  static const _tabs = [
    (Icons.mic_none_rounded, Icons.mic_rounded, '录音'),
    (Icons.auto_awesome_outlined, Icons.auto_awesome, '报告'),
    (Icons.history_rounded, Icons.history_rounded, '历史'),
    (Icons.settings_outlined, Icons.settings, '设置'),
  ];

  @override
  void initState() {
    super.initState();
    widget.app.addListener(_notifyUpdate);
    WidgetsBinding.instance.addPostFrameCallback((_) => _notifyUpdate());
  }

  @override
  void dispose() {
    widget.app.removeListener(_notifyUpdate);
    super.dispose();
  }

  /// 发现新版本：弹窗告诉用户（同一个版本只提醒一次；启动动画放完再弹）
  void _notifyUpdate() {
    final app = widget.app, v = app.newVersion;
    if (!mounted || _splash || v.isEmpty || v == app.settings.updateNotified) return;
    app.settings.updateNotified = v;
    app.settings.save();
    final notes = app.newVersionNotes.trim();
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('发现新版本 $v'),
        content: SingleChildScrollView(
          child: Text(
              '${notes.isEmpty ? '' : '$notes\n\n'}当前版本 $appVersion。更新只需一两分钟，录音和复盘记录都不受影响。'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('以后再说')),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => Scaffold(
                  appBar: AppBar(title: const Text('软件更新')),
                  body: ListView(padding: const EdgeInsets.fromLTRB(20, 0, 20, 32), children: [UpdateSection(app: app)]),
                ),
              ));
            },
            child: const Text('现在更新'),
          ),
        ],
      ),
    );
  }

  void _go(int i) {
    if (i == _tab) return;
    HapticFeedback.selectionClick();
    setState(() {
      _tab = i;
      _built.add(i);
      if (i == 1 || i == 2) _gen[i]++;
    });
  }

  Widget _page(int i) => switch (i) {
        0 => HomePage(app: widget.app, onOpenSettings: () => _go(3)),
        1 => DailyPage(key: ValueKey('daily${_gen[1]}'), app: widget.app),
        2 => HistoryPage(key: ValueKey('history${_gen[2]}'), app: widget.app),
        _ => SettingsPage(app: widget.app),
      };

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Stack(children: [
      Scaffold(
        extendBody: false,
        body: Stack(children: [
          for (var i = 0; i < _tabs.length; i++)
            if (_built.contains(i))
              IgnorePointer(
                ignoring: i != _tab,
                child: AnimatedOpacity(
                  opacity: i == _tab ? 1 : 0,
                  duration: Motion.normal,
                  curve: Motion.ease,
                  child: AnimatedScale(
                    scale: i == _tab ? 1 : .985,
                    duration: Motion.normal,
                    curve: Motion.easeOut,
                    child: TickerMode(enabled: i == _tab, child: _page(i)),
                  ),
                ),
              ),
        ]),
        bottomNavigationBar: ClipRect(
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 24, sigmaY: 24),
            child: Container(
              decoration: BoxDecoration(
                color: c.surface.withValues(alpha: .72),
                border: Border(top: BorderSide(color: c.sep, width: .5)),
              ),
              child: SafeArea(
                top: false,
                child: SizedBox(
                  height: 56,
                  child: ListenableBuilder(
                    listenable: widget.app,
                    builder: (context, _) => Row(children: [
                      for (var i = 0; i < _tabs.length; i++)
                        Expanded(
                          child: _NavItem(
                            icon: i == _tab ? _tabs[i].$2 : _tabs[i].$1,
                            label: _tabs[i].$3,
                            active: i == _tab,
                            dot: (i == 3 && widget.app.newVersion.isNotEmpty) || (i == 0 && widget.app.recording && _tab != 0),
                            dotColor: i == 0 ? c.red : c.accent,
                            onTap: () => _go(i),
                          ),
                        ),
                    ]),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
      if (_splash) Positioned.fill(child: SplashOverlay(onDone: () {
        setState(() => _splash = false);
        _notifyUpdate();
      })),
    ]);
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.icon, required this.label, required this.active, required this.onTap, this.dot = false, this.dotColor});
  final IconData icon;
  final String label;
  final bool active, dot;
  final Color? dotColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final col = active ? c.accent : c.label2;
    return Pressable(
      scale: .9,
      onTap: onTap,
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Stack(clipBehavior: Clip.none, children: [
          AnimatedSwitcher(
            duration: Motion.fast,
            transitionBuilder: (child, a) => ScaleTransition(scale: Tween(begin: .8, end: 1.0).animate(a), child: FadeTransition(opacity: a, child: child)),
            child: Icon(icon, key: ValueKey(icon), color: col, size: 25),
          ),
          if (dot)
            Positioned(
              right: -3,
              top: -1,
              child: Container(width: 8, height: 8, decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle)),
            ),
        ]),
        const SizedBox(height: 2),
        AnimatedDefaultTextStyle(
          duration: Motion.fast,
          style: Theme.of(context).textTheme.labelSmall!.copyWith(color: col, fontSize: 10.5, fontWeight: active ? FontWeight.w600 : FontWeight.w500),
          child: Text(label),
        ),
      ]),
    );
  }
}
