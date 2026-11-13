import 'dart:async';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import 'android_bridge.dart';
import 'core/api.dart';
import 'core/endpoints.dart';
import 'core/settings.dart';
import 'core/uploader.dart';
import 'recorder.dart';

/// 手机端：录音 → 切片暂存 → 传给电脑；并从电脑读取转写和复盘来显示
class AppState extends ChangeNotifier {
  AppState(this.dataDir)
      : settings = AppSettings.load(File('${dataDir.path}/settings.json')) {
    final spoolDir = Directory('${dataDir.path}/spool');
    endpoints = Endpoints(settings);
    uploader = Uploader(spoolDir, settings,
        endpoints: endpoints, canUpload: _canUpload, onChanged: notifyListeners);
    spool = ChunkSpool(spoolDir, settings, onChunk: () => unawaited(uploader.kick()));
    api = ServerApi(settings, endpoints);
    mic = MicRecorder(settings: settings, onData: spool.add, onProblem: say);
  }

  final Directory dataDir;
  final AppSettings settings;
  late final Endpoints endpoints;
  late final Uploader uploader;
  late final ChunkSpool spool;
  late final ServerApi api;
  late final MicRecorder mic;

  /// 电脑端的当前状态（/api/phone/view）
  Map<String, dynamic>? view;
  String viewError = '';
  bool foreground = true;
  bool starting = false;
  DateTime? recordStart;

  final StreamController<String> messages = StreamController<String>.broadcast();
  Timer? _poll;
  Timer? _meter;
  bool _refreshing = false;

  bool get recording => spool.recording;
  bool get configured => endpoints.all.isNotEmpty;

  /// 当前是不是连着 WiFi（每次轮询时更新）
  bool onWifi = true;
  int _tick = 0;

  Future<void> _checkNetwork() async {
    try {
      final r = await Connectivity().checkConnectivity();
      onWifi = r.contains(ConnectivityResult.wifi) || r.contains(ConnectivityResult.ethernet);
    } catch (_) {
      onWifi = true;
    }
    // 用移动网络时，新录的片压缩后再传
    spool.compress = !onWifi && settings.compressOnCellular;
  }

  void say(String m) {
    messages.add(m);
    notifyListeners();
  }

  Future<bool> _canUpload() async {
    await _checkNetwork();
    return !settings.wifiOnly || onWifi;
  }

  Future<void> init() async {
    uploader.startTimer();
    unawaited(uploader.kick()); // 上次没传完的接着传
    await _checkNetwork();
    _poll = Timer.periodic(const Duration(seconds: 4), (_) {
      _tick++;
      if (_tick % 4 == 0) unawaited(_checkNetwork());
      // 用移动网络时少刷新一点，省流量
      if (onWifi || _tick % 4 == 0) refresh();
    });
    unawaited(refresh());
  }

  /// 从电脑拉取最新的转写和复盘（App 在后台时不拉，省电）
  Future<void> refresh({bool force = false}) async {
    if (_refreshing || !configured || (!foreground && !force)) return;
    _refreshing = true;
    try {
      view = await api.view();
      viewError = '';
    } catch (e) {
      viewError = '$e';
    } finally {
      _refreshing = false;
      notifyListeners();
    }
  }

  Future<void> startRecording() async {
    if (starting || recording) return;
    starting = true;
    notifyListeners();
    try {
      if (!await mic.hasPermission()) {
        say('没有麦克风权限，请在系统设置里允许');
        return;
      }
      // 安卓：必须在 App 处于前台时启动麦克风前台服务
      await AndroidBridge.startForegroundService();
      spool.start();
      try {
        await mic.start();
      } catch (e) {
        say('启动录音失败：$e');
        spool.stop();
        await AndroidBridge.stopForegroundService();
        return;
      }
      recordStart = DateTime.now();
      _meter?.cancel();
      _meter = Timer.periodic(const Duration(milliseconds: 250), (_) => notifyListeners());
    } catch (e) {
      say('启动失败：$e');
    } finally {
      starting = false;
      notifyListeners();
    }
  }

  Future<void> stopRecording() async {
    _meter?.cancel();
    await mic.stop();
    spool.stop(); // 写入停止标记：电脑收到后做整场总复盘
    recordStart = null;
    await AndroidBridge.stopForegroundService();
    notifyListeners();
    unawaited(uploader.kick(force: true));
  }

  @override
  void dispose() {
    _poll?.cancel();
    _meter?.cancel();
    uploader.dispose();
    super.dispose();
  }

  void saveSettings() {
    settings.save();
    notifyListeners();
    unawaited(uploader.kick(force: true));
    unawaited(refresh(force: true));
  }
}
