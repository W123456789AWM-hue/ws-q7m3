import 'dart:io';

import 'package:flutter/services.dart';

/// 与 android/.../MainActivity.kt 通信：前台服务 + 电池优化白名单。
/// iOS 不需要（靠 Info.plist 的 audio 后台模式保活）。
class AndroidBridge {
  static const _ch = MethodChannel('ai_mind/android');

  static Future<void> startForegroundService() async {
    if (!Platform.isAndroid) return;
    await _ch.invokeMethod('startService');
  }

  static Future<void> stopForegroundService() async {
    if (!Platform.isAndroid) return;
    try {
      await _ch.invokeMethod('stopService');
    } catch (_) {}
  }

  static Future<bool> isIgnoringBatteryOptimizations() async {
    if (!Platform.isAndroid) return true;
    try {
      return await _ch.invokeMethod<bool>('isIgnoringBatteryOptimizations') ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> requestIgnoreBatteryOptimizations() async {
    if (!Platform.isAndroid) return;
    try {
      await _ch.invokeMethod('requestIgnoreBatteryOptimizations');
    } catch (_) {}
  }
}
