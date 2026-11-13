import 'dart:async';
import 'dart:typed_data';

import 'package:record/record.dart';

import 'core/settings.dart';

/// 持续录音：一条麦克风 PCM 流（16kHz 单声道）不间断地交给 [onData]。
///
/// 用“流式录音”而不是反复 start/stop，是因为 iOS 在后台停掉录音后
/// 很可能无法再启动；一条流不停，切句和分段都在 Dart 里完成。
class MicRecorder {
  MicRecorder({required this.settings, required this.onData, required this.onProblem});

  final AppSettings settings;

  final void Function(Uint8List) onData;
  final void Function(String) onProblem;

  final AudioRecorder _rec = AudioRecorder();
  StreamSubscription<Uint8List>? _sub;
  Timer? _watchdog;
  DateTime _lastData = DateTime.now();
  bool _restarting = false;
  bool running = false;
  int restarts = 0;

  Future<bool> hasPermission() => _rec.hasPermission();

  Future<void> start() async {
    if (running) return;
    running = true;
    restarts = 0;
    try {
      await _open();
    } catch (e) {
      running = false;
      rethrow;
    }
    _watchdog?.cancel();
    _watchdog = Timer.periodic(const Duration(seconds: 10), (_) => _check());
  }

  Future<void> stop() async {
    running = false;
    _watchdog?.cancel();
    try {
      await _rec.stop();
    } catch (_) {}
    await _sub?.cancel();
    _sub = null;
  }

  Future<void> _open() async {
    final stream = await _rec.startStream(RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: 16000,
      numChannels: 1,
      autoGain: settings.micAutoGain,
      noiseSuppress: settings.micNoiseSuppress,
      // 来电等打断后自动恢复
      audioInterruption: AudioInterruptionMode.pauseResume,
      // 不抢蓝牙耳机通话通道（否则听音乐会变成低音质通话模式）
      // voiceRecognition：安卓专门为语音识别调校的收音方式
      androidConfig: const AndroidRecordConfig(
          manageBluetooth: false, audioSource: AndroidAudioSource.voiceRecognition),
      iosConfig: const IosRecordConfig(categoryOptions: [
        IosAudioCategoryOption.mixWithOthers,
        IosAudioCategoryOption.defaultToSpeaker,
        IosAudioCategoryOption.allowBluetoothA2DP,
      ]),
    ));
    _lastData = DateTime.now();
    _sub = stream.listen(
      (chunk) {
        _lastData = DateTime.now();
        if (running) onData(chunk);
      },
      onError: (Object e) => onProblem('录音流错误：$e'),
      cancelOnError: false,
    );
  }

  /// 看门狗：长时间收不到音频数据就重启录音流
  Future<void> _check() async {
    if (!running || _restarting) return;
    final gap = DateTime.now().difference(_lastData);
    if (gap < const Duration(seconds: 30)) return;
    try {
      // 被来电等打断时会自动暂停/恢复，先等一会
      if (await _rec.isPaused() && gap < const Duration(minutes: 3)) return;
    } catch (_) {}
    _restarting = true;
    try {
      await _sub?.cancel();
      _sub = null;
      try {
        await _rec.stop();
      } catch (_) {}
      await _open();
      restarts++;
      onProblem('录音中断过，已自动恢复（第 $restarts 次）');
    } catch (e) {
      onProblem('录音中断，重启失败（10 秒后再试）：$e');
    } finally {
      _restarting = false;
    }
  }

  void dispose() {
    _watchdog?.cancel();
    _rec.dispose();
  }
}
