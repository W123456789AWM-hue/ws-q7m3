import 'dart:async';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import 'android_bridge.dart';
import 'core/api.dart';
import 'core/endpoints.dart';
import 'core/local_engine.dart';
import 'core/settings.dart';
import 'core/updater.dart';
import 'core/uploader.dart';
import 'recorder.dart';
import 'ui/sfx.dart';
import 'ui/update_section.dart' show appVersion, newer;

/// 手机端：录音 → 切片暂存 → 传给电脑（或者「手机独立复盘」：手机自己交给 AI）；界面显示转写和复盘
class AppState extends ChangeNotifier {
  AppState(this.dataDir)
      : settings = AppSettings.load(File('${dataDir.path}/settings.json')) {
    final spoolDir = Directory('${dataDir.path}/spool');
    endpoints = Endpoints(settings);
    uploader = Uploader(spoolDir, settings,
        endpoints: endpoints, canUpload: _canUpload, onChanged: notifyListeners);
    engine = LocalEngine(Directory('${dataDir.path}/local'), spoolDir, settings, onChanged: _localChanged);
    spool = ChunkSpool(spoolDir, settings,
        onChunk: () => unawaited(settings.standalone ? engine.kick() : uploader.kick()));
    api = ServerApi(settings, endpoints);
    mic = MicRecorder(settings: settings, onData: spool.add, onProblem: say);
  }

  final Directory dataDir;
  final AppSettings settings;
  late final Endpoints endpoints;
  late final Uploader uploader;
  late final ChunkSpool spool;
  late final LocalEngine engine;
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
  bool get standalone => settings.standalone;
  bool get configured => standalone || endpoints.all.isNotEmpty;

  /// 发布仓库里的最新版本号（比当前新才有值）：设置页和底部导航上显示小红点
  String newVersion = '';

  void _localChanged() {
    if (standalone) view = engine.view(recording: recording, stream: spool.stream);
    notifyListeners();
  }

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
    spool.compress = !standalone && !onWifi && settings.compressOnCellular;
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
    Sfx.clicks = settings.soundClicks;
    Sfx.splashSound = settings.splashSound;
    Sfx.busy = () => recording || starting;
    unawaited(Sfx.init());
    uploader.startTimer();
    unawaited(uploader.kick()); // 上次没传完的接着传
    await _checkNetwork();
    _poll = Timer.periodic(const Duration(seconds: 4), (_) {
      _tick++;
      if (_tick % 4 == 0) unawaited(_checkNetwork());
      // 用移动网络时少刷新一点，省流量
      if (standalone) {
        unawaited(engine.kick()); // 上次没处理完的接着处理
        _localChanged();
      } else if (onWifi || _tick % 4 == 0) {
        refresh();
      }
    });
    unawaited(refresh());
    if (settings.autoCheckUpdate) unawaited(checkUpdate());
  }

  /// 从电脑拉取最新的转写和复盘（App 在后台时不拉，省电）
  Future<void> refresh({bool force = false}) async {
    if (standalone) {
      viewError = '';
      _localChanged();
      return;
    }
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
    Sfx.afterRecording();
    await AndroidBridge.stopForegroundService();
    notifyListeners();
    unawaited(standalone ? engine.kick() : uploader.kick(force: true));
  }

  // ---- 下面这些：连电脑时问电脑，独立模式用手机上的数据 ----
  Future<List<Map<String, dynamic>>> sessions() async => standalone ? engine.sessions() : api.sessions();

  Future<Map<String, dynamic>> session(String id) async =>
      standalone ? (engine.session(id) ?? <String, dynamic>{}) : api.session(id);

  Future<String> report(String period, String key, {bool make = false}) async => !standalone
      ? api.report(period, key, make: make)
      : (make ? engine.makeReport(period, key) : engine.report(period, key));

  Future<void> reviewNow() async {
    if (!standalone) return api.reviewNow();
    final id = (view?['session'] as Map?)?['id'];
    if (id != null) await engine.reviewNow('$id');
  }

  Future<void> retryReview(int rid, {String? sessionId}) async {
    if (!standalone) return api.retryReview(rid);
    final id = sessionId ?? (view?['session'] as Map?)?['id'];
    if (id != null) await engine.retry('$id', rid);
  }

  /// 直接从发布仓库看有没有新版本（不经过电脑）；失败不打扰用户
  Future<void> checkUpdate() async {
    try {
      final m = await MobileUpdater(mirror: settings.updateMirror).fetchManifest();
      final v = '${m['version']}';
      newVersion = newer(v, appVersion) ? v : '';
      notifyListeners();
    } catch (_) {}
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
    unawaited(standalone ? engine.kick() : uploader.kick(force: true));
    unawaited(refresh(force: true));
  }
}
