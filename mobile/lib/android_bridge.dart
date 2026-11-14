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

  /// 手机 CPU 架构（选安装包用）：arm64-v8a / armeabi-v7a
  static Future<String> abi() async {
    if (!Platform.isAndroid) return '';
    try {
      return await _ch.invokeMethod<String>('abi') ?? 'arm64-v8a';
    } catch (_) {
      return 'arm64-v8a';
    }
  }

  /// 打开系统的安装界面装 APK。返回 ok / need_permission（需要先允许“安装未知应用”，已经跳到设置页）
  static Future<String> installApk(String path) async {
    return await _ch.invokeMethod<String>('installApk', {'path': path}) ?? 'ok';
  }

  static Future<void> requestIgnoreBatteryOptimizations() async {
    if (!Platform.isAndroid) return;
    try {
      await _ch.invokeMethod('requestIgnoreBatteryOptimizations');
    } catch (_) {}
  }
}
