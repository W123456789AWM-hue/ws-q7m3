import 'dart:convert';
import 'dart:io';
import 'dart:math';

/// 手机本机的设置（识别、复盘、NAS 的设置都在电脑上，手机通过网络去改）
class AppSettings {
  // ---- 连接电脑 ----
  String serverUrl = ''; // 例如 http://192.168.1.20:8765
  String serverUrl2 = ''; // 备用地址：外出时用（如 Tailscale 的 http://100.x.x.x:8765）
  String token = ''; // 电脑界面「设备连接」里显示的口令
  String deviceId = newDeviceId(); // 这台设备的编号（第一次启动自动生成，几台设备同时录音时用来区分）
  String deviceName = defaultDeviceName(); // 在电脑上显示的名字，例如“客厅手机”“办公室 iPad”
  bool wifiOnly = false; // 仅 WiFi 下上传；不在 WiFi 时录音先存手机
  bool compressOnCellular = true; // 用移动网络时把录音压缩到 1/4 再传

  // ---- 录音 ----
  bool autoStart = false; // 打开 App 就自动开始录音
  bool skipSilence = true; // 没人说话的片段不上传（省流量、省电、省 NAS 空间）
  bool micAutoGain = true;
  bool micNoiseSuppress = false;
  double vadMarginDb = 8; // 判断“有声音”的灵敏度：比环境噪音高多少 dB
  int chunkSec = 10; // 每多少秒上传一片
  int maxSpoolMb = 3000; // 手机上最多暂存多少 MB 没传完的录音

  File? file;

  Map<String, dynamic> toJson() => {
        'serverUrl': serverUrl,
        'serverUrl2': serverUrl2,
        'token': token,
        'deviceId': deviceId,
        'deviceName': deviceName,
        'wifiOnly': wifiOnly,
        'compressOnCellular': compressOnCellular,
        'autoStart': autoStart,
        'skipSilence': skipSilence,
        'micAutoGain': micAutoGain,
        'micNoiseSuppress': micNoiseSuppress,
        'vadMarginDb': vadMarginDb,
        'chunkSec': chunkSec,
        'maxSpoolMb': maxSpoolMb,
      };

  void apply(Map<String, dynamic> m) {
    int i(String k, int d) => (m[k] as num?)?.toInt() ?? d;
    double f(String k, double d) => (m[k] as num?)?.toDouble() ?? d;
    String s(String k, String d) => (m[k] as String?) ?? d;
    bool b(String k, bool d) => (m[k] as bool?) ?? d;

    String url(String v) {
      final u = v.trim().replaceAll(RegExp(r'/+$'), '');
      return u.isNotEmpty && !u.contains('://') ? 'http://$u' : u;
    }

    serverUrl = url(s('serverUrl', serverUrl));
    serverUrl2 = url(s('serverUrl2', serverUrl2));
    token = s('token', token).trim();
    deviceId = s('deviceId', deviceId).trim();
    if (deviceId.isEmpty) deviceId = newDeviceId();
    deviceName = s('deviceName', deviceName).trim();
    if (deviceName.isEmpty) deviceName = defaultDeviceName();
    wifiOnly = b('wifiOnly', wifiOnly);
    compressOnCellular = b('compressOnCellular', compressOnCellular);
    autoStart = b('autoStart', autoStart);
    skipSilence = b('skipSilence', skipSilence);
    micAutoGain = b('micAutoGain', micAutoGain);
    micNoiseSuppress = b('micNoiseSuppress', micNoiseSuppress);
    vadMarginDb = f('vadMarginDb', vadMarginDb).clamp(3, 30).toDouble();
    chunkSec = i('chunkSec', chunkSec).clamp(5, 60);
    maxSpoolMb = i('maxSpoolMb', maxSpoolMb).clamp(100, 50000);
  }

  static String newDeviceId() {
    final r = Random.secure();
    return 'm${List.generate(8, (_) => r.nextInt(36).toRadixString(36)).join()}';
  }

  static String defaultDeviceName() {
    if (Platform.isIOS) return 'iPhone';
    if (Platform.isAndroid) return '安卓手机';
    return '手机';
  }

  static AppSettings load(File f) {
    final s = AppSettings()..file = f;
    var m = <String, dynamic>{};
    if (f.existsSync()) {
      try {
        m = jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;
      } catch (_) {/* 配置损坏就用默认值 */}
    }
    s.apply(m);
    if (m['deviceId'] == null) s.save(); // 新生成的设备编号要记住
    return s;
  }

  void save() {
    apply(toJson()); // 统一做一次范围修正
    final f = file;
    if (f == null) return;
    f.parent.createSync(recursive: true);
    final tmp = File('${f.path}.tmp')..writeAsStringSync(jsonEncode(toJson()));
    tmp.renameSync(f.path);
  }
}
