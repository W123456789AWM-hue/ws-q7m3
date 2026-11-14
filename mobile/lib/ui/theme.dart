/// 手机端的设计变量：和电脑端 server/aimind/web/static/css/tokens.css 用同一套颜色、圆角、动画曲线。
/// 改主题只改这一个文件。深浅色跟随系统。
library;

import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// 动画：Apple 风格的缓动（快出慢停），所有过渡都用这几个
class Motion {
  static const ease = Cubic(.32, .72, 0, 1);
  static const easeOut = Cubic(.16, 1, .3, 1);
  static const fast = Duration(milliseconds: 160);
  static const normal = Duration(milliseconds: 280);
  static const slow = Duration(milliseconds: 420);
}

/// Material 配色之外的颜色（系统色、分隔线、次级文字…）
class AppColors extends ThemeExtension<AppColors> {
  const AppColors({
    required this.bg,
    required this.surface,
    required this.fill,
    required this.sep,
    required this.label,
    required this.label2,
    required this.label3,
    required this.accent,
    required this.accentSoft,
    required this.tech,
    required this.red,
    required this.orange,
    required this.yellow,
    required this.green,
    required this.teal,
    required this.purple,
    required this.indigo,
  });

  final Color bg, surface, fill, sep, label, label2, label3;
  final Color accent, accentSoft, tech, red, orange, yellow, green, teal, purple, indigo;

  static const dark = AppColors(
    bg: Color(0xFF000000),
    surface: Color(0xFF1C1C1E),
    fill: Color(0x3D767680),
    sep: Color(0x6B545458),
    label: Color(0xFFF5F5F7),
    label2: Color(0x9EEBEBF5),
    label3: Color(0x5CEBEBF5),
    accent: Color(0xFF0A84FF),
    accentSoft: Color(0x290A84FF),
    tech: Color(0xFF64D2FF),
    red: Color(0xFFFF453A),
    orange: Color(0xFFFF9F0A),
    yellow: Color(0xFFFFD60A),
    green: Color(0xFF30D158),
    teal: Color(0xFF40C8E0),
    purple: Color(0xFFBF5AF2),
    indigo: Color(0xFF5E5CE6),
  );

  static const light = AppColors(
    bg: Color(0xFFF5F5F7),
    surface: Color(0xFFFFFFFF),
    fill: Color(0x29787880),
    sep: Color(0x383C3C43),
    label: Color(0xFF1D1D1F),
    label2: Color(0xA83C3C43),
    label3: Color(0x5C3C3C43),
    accent: Color(0xFF007AFF),
    accentSoft: Color(0x1F007AFF),
    tech: Color(0xFF0A84FF),
    red: Color(0xFFFF3B30),
    orange: Color(0xFFFF9500),
    yellow: Color(0xFFFFCC00),
    green: Color(0xFF34C759),
    teal: Color(0xFF30B0C7),
    purple: Color(0xFFAF52DE),
    indigo: Color(0xFF5856D6),
  );

  @override
  AppColors copyWith() => this;

  @override
  AppColors lerp(ThemeExtension<AppColors>? other, double t) => t < .5 || other is! AppColors ? this : other;
}

extension AppColorsX on BuildContext {
  AppColors get c => Theme.of(this).extension<AppColors>()!;
}

ThemeData buildTheme(Brightness b) {
  final c = b == Brightness.dark ? AppColors.dark : AppColors.light;
  final scheme = ColorScheme.fromSeed(seedColor: c.accent, brightness: b).copyWith(
    primary: c.accent,
    onPrimary: Colors.white,
    secondary: c.tech,
    surface: c.bg,
    onSurface: c.label,
    onSurfaceVariant: c.label2,
    outline: c.label2,
    outlineVariant: c.sep,
    error: c.red,
    onError: Colors.white,
    errorContainer: c.red.withValues(alpha: .15),
    onErrorContainer: c.red,
    surfaceContainerLowest: c.bg,
    surfaceContainerLow: c.surface,
    surfaceContainer: c.surface,
    surfaceContainerHigh: c.surface,
    surfaceContainerHighest: c.fill,
    primaryContainer: c.accentSoft,
    onPrimaryContainer: c.accent,
    secondaryContainer: c.accentSoft,
    onSecondaryContainer: c.accent,
    surfaceTint: Colors.transparent,
  );
  final r12 = BorderRadius.circular(12);
  final base = ThemeData(colorScheme: scheme, useMaterial3: true, brightness: b);
  final text = base.textTheme.apply(bodyColor: c.label, displayColor: c.label);
  return base.copyWith(
    extensions: [c],
    scaffoldBackgroundColor: c.bg,
    splashFactory: NoSplash.splashFactory, // 不要安卓的水波纹，按下只变暗一点
    highlightColor: c.fill.withValues(alpha: .12),
    dividerColor: c.sep,
    dividerTheme: DividerThemeData(color: c.sep, thickness: .5, space: .5),
    textTheme: text.copyWith(
      titleLarge: text.titleLarge?.copyWith(fontWeight: FontWeight.w700, letterSpacing: -.3),
      titleMedium: text.titleMedium?.copyWith(fontWeight: FontWeight.w600, letterSpacing: -.2),
      titleSmall: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
      bodySmall: text.bodySmall?.copyWith(color: c.label2),
    ),
    // 页面切换：两个系统都用 iOS 的横向推入（可以从左边缘滑回去）
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: CupertinoPageTransitionsBuilder(),
      TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
    }),
    appBarTheme: AppBarTheme(
      backgroundColor: c.bg,
      foregroundColor: c.label,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(color: c.label, fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: -.4),
      systemOverlayStyle: (b == Brightness.dark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark)
          .copyWith(statusBarColor: Colors.transparent, systemNavigationBarColor: c.bg),
    ),
    cardTheme: CardThemeData(
      color: c.surface,
      elevation: 0,
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, 44),
        shape: RoundedRectangleBorder(borderRadius: r12),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 40),
        foregroundColor: c.accent,
        backgroundColor: c.fill.withValues(alpha: .1),
        side: BorderSide.none,
        shape: RoundedRectangleBorder(borderRadius: r12),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500),
      ),
    ),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(foregroundColor: c.accent)),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.surface,
      isDense: true,
      labelStyle: TextStyle(color: c.label2),
      floatingLabelStyle: TextStyle(color: c.accent),
      helperStyle: TextStyle(color: c.label2, height: 1.4),
      hintStyle: TextStyle(color: c.label3),
      border: OutlineInputBorder(borderRadius: r12, borderSide: BorderSide(color: c.sep, width: .5)),
      enabledBorder: OutlineInputBorder(borderRadius: r12, borderSide: BorderSide(color: c.sep, width: .5)),
      focusedBorder: OutlineInputBorder(borderRadius: r12, borderSide: BorderSide(color: c.accent, width: 1.5)),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: const WidgetStatePropertyAll(Colors.white),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.green : c.fill),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    listTileTheme: ListTileThemeData(iconColor: c.label2, subtitleTextStyle: TextStyle(color: c.label2, fontSize: 13, height: 1.4)),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.surface : c.fill.withValues(alpha: .1)),
        foregroundColor: WidgetStatePropertyAll(c.label),
        side: WidgetStatePropertyAll(BorderSide(color: c.sep, width: .5)),
        shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
      ),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: c.accent, linearTrackColor: c.fill, circularTrackColor: Colors.transparent),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: b == Brightness.dark ? const Color(0xFF2C2C2E) : const Color(0xFF1D1D1F),
      contentTextStyle: const TextStyle(color: Colors.white, fontSize: 14),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    dialogTheme: DialogThemeData(backgroundColor: c.surface, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20))),
    bannerTheme: MaterialBannerThemeData(backgroundColor: c.orange.withValues(alpha: .14)),
    tabBarTheme: TabBarThemeData(
      labelColor: c.accent,
      unselectedLabelColor: c.label2,
      indicatorColor: c.accent,
      dividerColor: c.sep,
      labelStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
    ),
    expansionTileTheme: ExpansionTileThemeData(iconColor: c.label2, collapsedIconColor: c.label3),
  );
}

/// 内容出现时的小动画：淡入 + 从下面滑上来一点（列表里的卡片、切换的内容都用它）
class Appear extends StatelessWidget {
  const Appear({super.key, required this.child, this.delay = Duration.zero, this.offset = 14});
  final Widget child;
  final Duration delay;
  final double offset;

  @override
  Widget build(BuildContext context) {
    final total = Motion.slow + delay;
    final start = delay.inMilliseconds / total.inMilliseconds;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: total,
      curve: Interval(start, 1, curve: Motion.easeOut),
      builder: (_, t, child) => Opacity(
        opacity: t.clamp(0, 1),
        child: Transform.translate(offset: Offset(0, (1 - t) * offset), child: child),
      ),
      child: child,
    );
  }
}

/// 按下去缩一点、松开弹回来（按钮、卡片的按压反馈）
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.scale = .96});
  final Widget child;
  final VoidCallback? onTap;
  final double scale;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;

  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: widget.onTap == null ? null : (_) => setState(() => _down = true),
        onTapUp: (_) => setState(() => _down = false),
        onTapCancel: () => setState(() => _down = false),
        onTap: widget.onTap == null
            ? null
            : () {
                HapticFeedback.selectionClick();
                widget.onTap!();
              },
        child: AnimatedScale(
          scale: _down ? widget.scale : 1,
          duration: _down ? Motion.fast : Motion.normal,
          curve: Motion.easeOut,
          child: AnimatedOpacity(opacity: _down ? .8 : 1, duration: Motion.fast, child: widget.child),
        ),
      );
}

/// 一小块状态标签（圆角胶囊）
class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.color, this.icon});
  final String text;
  final Color? color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final col = color ?? context.c.label2;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(color: col.withValues(alpha: .14), borderRadius: BorderRadius.circular(99)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 13, color: col), const SizedBox(width: 4)],
        Flexible(child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: col, fontSize: 12, fontWeight: FontWeight.w500))),
      ]),
    );
  }
}
