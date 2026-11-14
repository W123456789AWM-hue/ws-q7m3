import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

import 'sfx.dart';
import 'theme.dart';

/// 启动动画：和电脑端同一段动画（assets/splash.webp，透明背景，按文件里每一帧的真实时长、乘上 [speed] 播放），
/// 配上启动音效（assets/sounds/splash.wav，按同样的速度生成，见 server/packaging/make_sounds.py，所以画面和声音对得上）。
/// 播完淡出并轻微放大，露出下面的界面；点一下可以跳过（声音也淡出）。
/// 解码失败、太慢都不会卡住：最多 [maxWait] 后一定让开。
class SplashOverlay extends StatefulWidget {
  const SplashOverlay({super.key, required this.onDone, this.speed = 1.5}); // 改速度要同步改 make_sounds.py
  final VoidCallback onDone;
  final double speed;

  static const maxWait = Duration(seconds: 8);
  static const lastHold = Duration(milliseconds: 900); // 最后一帧（完整的标志）停留多久

  @override
  State<SplashOverlay> createState() => _SplashOverlayState();
}

class _SplashOverlayState extends State<SplashOverlay> with SingleTickerProviderStateMixin {
  ui.Codec? _codec;
  ui.Image? _frame;
  Ticker? _ticker;
  Timer? _guard;
  int _shown = 0; // 已经显示到第几帧
  Duration _nextAt = Duration.zero; // 下一帧该在什么时候出现
  bool _decoding = false, _leaving = false, _gone = false, _skipped = false;

  @override
  void initState() {
    super.initState();
    _guard = Timer(SplashOverlay.maxWait, _leave);
    _start();
  }

  Future<void> _start() async {
    try {
      final data = await rootBundle.load('assets/splash.webp');
      // 按屏幕宽度解码就够了，省内存
      final w = (ui.PlatformDispatcher.instance.views.first.physicalSize.width).clamp(360, 1000).round();
      final codec = await ui.instantiateImageCodec(data.buffer.asUint8List(), targetWidth: w);
      if (!mounted) return codec.dispose();
      _codec = codec;
      _ticker = createTicker(_tick)..start();
    } catch (_) {
      _leave();
    }
  }

  Future<void> _tick(Duration elapsed) async {
    final codec = _codec;
    if (codec == null || _decoding || _leaving || elapsed < _nextAt) return;
    if (_shown >= codec.frameCount) return _leave();
    _decoding = true;
    try {
      // 手机解码跟不上时跳帧，保证总时长不变（声音和画面不会越走越错开）
      ui.Image? img;
      while (_shown < codec.frameCount && elapsed >= _nextAt) {
        img?.dispose();
        final f = await codec.getNextFrame();
        img = f.image;
        _shown++;
        var dur = f.duration.inMicroseconds > 0 ? f.duration : const Duration(microseconds: 16667);
        dur = Duration(microseconds: dur.inMicroseconds ~/ widget.speed);
        if (_shown == codec.frameCount && dur > SplashOverlay.lastHold) dur = SplashOverlay.lastHold;
        _nextAt += dur;
      }
      if (!mounted) return img?.dispose();
      if (_frame == null) unawaited(Sfx.splash()); // 第一帧出现：开始放声音
      final old = _frame;
      setState(() => _frame = img);
      old?.dispose();
    } catch (_) {
      _leave();
    } finally {
      _decoding = false;
    }
  }

  void _skip() {
    _skipped = true;
    _leave();
  }

  void _leave() {
    if (_leaving || !mounted) return;
    if (_skipped) unawaited(Sfx.stopSplash()); // 正常放完时不停，让余音自然收尾
    _guard?.cancel();
    _ticker?.stop();
    setState(() => _leaving = true);
  }

  @override
  void dispose() {
    _guard?.cancel();
    _ticker?.dispose();
    _frame?.dispose();
    _codec?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_gone) return const SizedBox.shrink();
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: _skip,
      child: AnimatedOpacity(
        opacity: _leaving ? 0 : 1,
        duration: Motion.slow,
        curve: Motion.ease,
        onEnd: () {
          if (_leaving && !_gone) {
            _gone = true;
            widget.onDone();
          }
        },
        child: ColoredBox(
          // 白底：这段动画是从白底视频抠出来的（标志里有黑色的字），放在深色上会看不见；
          // 系统自带的启动画面也是白的，衔接起来没有闪一下的感觉
          color: Colors.white,
          child: Center(
            child: AnimatedScale(
              scale: _leaving ? 1.12 : 1,
              duration: Motion.slow,
              curve: Motion.ease,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: AspectRatio(
                  aspectRatio: 1000 / 381,
                  child: _frame == null ? const SizedBox.shrink() : RawImage(image: _frame, fit: BoxFit.contain),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
