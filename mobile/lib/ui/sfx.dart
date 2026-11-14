/// 界面音效：按钮的轻点声、启动动画的音效（声音文件由 server/packaging/make_sounds.py 合成，和电脑端一样）。
///
/// - 和别的 App 的声音混在一起放，不打断你正在听的音乐；iPhone 静音开关打开时不响。
/// - 录音时一律不响：点击声会被麦克风录进去，而且 iPhone 上播放声音可能打断录音。
/// - 任何错误都吞掉：音效出问题不能影响 App 本身。
library;

import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class Sfx {
  static bool clicks = true; // 设置：按钮音效
  static bool splashSound = true; // 设置：启动音效
  static bool Function() busy = () => false; // 正在录音时返回 true

  static final bool _enabled = !kIsWeb && !Platform.environment.containsKey('FLUTTER_TEST');
  static AudioPlayer? _click, _splash;
  static bool _ready = false, _needContext = true;
  static DateTime _last = DateTime(2000);

  /// 只放提示音：Android 不抢音频焦点（音乐不暂停），iPhone 用 ambient（跟随静音开关、和别的声音混放）
  static final AudioContext _ctx = AudioContext(
    android: const AudioContextAndroid(
      contentType: AndroidContentType.sonification,
      usageType: AndroidUsageType.assistanceSonification,
      audioFocus: AndroidAudioFocus.none,
    ),
    iOS: AudioContextIOS(category: AVAudioSessionCategory.ambient),
  );

  static Future<void> init() async {
    if (!_enabled || _ready) return;
    try {
      await _applyContext();
      _click = AudioPlayer(playerId: 'ui-click')..setReleaseMode(ReleaseMode.stop);
      await _click!.setPlayerMode(PlayerMode.lowLatency);
      await _click!.setSource(AssetSource('sounds/click.wav'));
      await _click!.setVolume(.6);
      _ready = true;
    } catch (e) {
      debugPrint('按钮音效初始化失败：$e');
    }
  }

  static Future<void> _applyContext() async {
    if (!_needContext) return;
    await AudioPlayer.global.setAudioContext(_ctx);
    _needContext = false;
  }

  /// 录音停了之后调用：录音时系统的声音设置被录音改过，下次放声音前要改回来
  static void afterRecording() => _needContext = true;

  /// 按钮音效（40 毫秒内连着触发只响一次）
  static void tap() {
    if (!_enabled || !clicks || busy()) return;
    final now = DateTime.now();
    if (now.difference(_last).inMilliseconds < 40) return;
    _last = now;
    unawaited(() async {
      try {
        if (!_ready) await init();
        await _applyContext();
        final p = _click;
        if (p == null) return;
        await p.stop();
        await p.resume();
      } catch (_) {}
    }());
  }

  static Future<void> splash() async {
    if (!_enabled || !splashSound || busy()) return;
    try {
      await _applyContext();
      _splash = AudioPlayer(playerId: 'ui-splash');
      await _splash!.setReleaseMode(ReleaseMode.release);
      await _splash!.play(AssetSource('sounds/splash.wav'), volume: .9);
    } catch (e) {
      debugPrint('启动音效播放失败：$e');
    }
  }

  /// 动画被点掉了：声音在 0.25 秒内淡出
  static Future<void> stopSplash() async {
    final p = _splash;
    if (p == null) return;
    _splash = null;
    try {
      for (var v = .9; v > 0; v -= .15) {
        await p.setVolume(v);
        await Future<void>.delayed(const Duration(milliseconds: 40));
      }
      await p.stop();
      await p.dispose();
    } catch (_) {}
  }
}

/// 所有 Material 按钮、列表项、开关行在按下时都会创建“水波纹”：在这里顺手放按钮音效，
/// 不用每个按钮单独写。水波纹本身不画（和之前一样，按下只轻微变暗）。
class ClickSplashFactory extends InteractiveInkFeatureFactory {
  const ClickSplashFactory();

  @override
  InteractiveInkFeature create({
    required MaterialInkController controller,
    required RenderBox referenceBox,
    required Offset position,
    required Color color,
    required TextDirection textDirection,
    bool containedInkWell = false,
    RectCallback? rectCallback,
    BorderRadius? borderRadius,
    ShapeBorder? customBorder,
    double? radius,
    VoidCallback? onRemoved,
  }) {
    Sfx.tap();
    return NoSplash.splashFactory.create(
      controller: controller,
      referenceBox: referenceBox,
      position: position,
      color: color,
      textDirection: textDirection,
      containedInkWell: containedInkWell,
      rectCallback: rectCallback,
      borderRadius: borderRadius,
      customBorder: customBorder,
      radius: radius,
      onRemoved: onRemoved,
    );
  }
}
