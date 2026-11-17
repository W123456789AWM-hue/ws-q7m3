/// 手机直接调用 AI（OpenAI 兼容的 Chat Completions 接口；Google Gemini 也走它的兼容接口）：听录音做复盘、文字做总复盘。
/// 只在「手机独立复盘」模式下使用；连电脑的模式里这些都由电脑做。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'audio.dart';
import 'settings.dart';

class AiException implements Exception {
  AiException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// 一段要发给 AI 听的录音：前面的标注 + 16k 单声道 PCM
class AudioPart {
  AudioPart(this.label, this.pcm);
  final String label;
  final Uint8List pcm;
}

/// PCM → WAV 文件内容
Uint8List wavBytes(Uint8List pcm) {
  final h = ByteData(44);
  void tag(int at, String s) {
    for (var i = 0; i < 4; i++) {
      h.setUint8(at + i, s.codeUnitAt(i));
    }
  }

  tag(0, 'RIFF');
  h.setUint32(4, 36 + pcm.length, Endian.little);
  tag(8, 'WAVE');
  tag(12, 'fmt ');
  h.setUint32(16, 16, Endian.little);
  h.setUint16(20, 1, Endian.little);
  h.setUint16(22, 1, Endian.little);
  h.setUint32(24, kSampleRate, Endian.little);
  h.setUint32(28, kSampleRate * 2, Endian.little);
  h.setUint16(32, 2, Endian.little);
  h.setUint16(34, 16, Endian.little);
  tag(36, 'data');
  h.setUint32(40, pcm.length, Endian.little);
  return (BytesBuilder(copy: false)
        ..add(h.buffer.asUint8List())
        ..add(pcm))
      .takeBytes();
}

class AiClient {
  AiClient(this.s);
  final AppSettings s;

  static const busyCodes = {500, 502, 503, 504};
  static const geminiFallback = 'gemini-flash-lite-latest';

  /// 服务器临时过载时的重试间隔（测试里改短）
  static List<Duration> busyWaits = const [Duration(seconds: 4), Duration(seconds: 12), Duration(seconds: 25)];

  Future<String> _post(Map<String, dynamic> body, Duration timeout, {bool audio = false}) async {
    if (s.aiApiKey.isEmpty) throw AiException('还没填写 ${s.vendorName} 的 API Key（设置 → 手机独立复盘）');
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 15);
    try {
      Future<(int, String)> send(Map<String, dynamic> b) async {
        final req = await client.postUrl(Uri.parse('${s.aiEndpoint}/chat/completions'));
        req.headers.set('Authorization', 'Bearer ${s.aiApiKey}');
        final bytes = utf8.encode(jsonEncode(b));
        req.headers.contentType = ContentType('application', 'json', charset: 'utf-8');
        req.contentLength = bytes.length;
        req.add(bytes);
        final resp = await req.close().timeout(timeout);
        return (resp.statusCode, await resp.transform(utf8.decoder).join().timeout(timeout));
      }

      /// 对方临时过载（5xx，比如 Gemini 的 “high demand”）：等一会儿重试；
      /// Gemini 几次都忙，最后换备用模型试一次（备用模型不能用就保留原来的错误）
      Future<(int, String)> sendRetry(Map<String, dynamic> b) async {
        var (code, text) = await send(b);
        for (var i = 0; i < busyWaits.length && busyCodes.contains(code); i++) {
          await Future<void>.delayed(busyWaits[i]);
          var bb = b;
          if (i == busyWaits.length - 1 && s.google && b['model'] != geminiFallback) {
            bb = Map.of(b)..['model'] = geminiFallback;
          }
          final (c2, t2) = await send(bb);
          if (!identical(bb, b) && (c2 == 400 || c2 == 403 || c2 == 404)) break;
          (code, text) = (c2, t2);
        }
        return (code, text);
      }

      var (code, text) = await sendRetry(body);
      if (code == 400 && !(audio && text.toLowerCase().contains('audio'))) {
        // 有的模型不收 temperature / max_tokens，去掉再试
        (code, text) = await sendRetry(Map.of(body)
          ..remove('temperature')
          ..remove('max_tokens'));
      }
      if (busyCodes.contains(code)) {
        throw AiException('${s.vendorName} 那边现在太忙（HTTP $code，服务器临时过载，不是你的设置问题），'
            '已自动重试几次仍不行。一般过几分钟就好，点「重试」即可');
      }
      if (code == 401) throw AiException('${s.vendorName} 的 API Key 不对或已失效');
      if (code == 413) throw AiException('一次发送的录音太大，请把复盘间隔调短一些');
      if (code == 429) throw AiException('额度不足或请求太频繁（HTTP 429）：${_cut(text)}');
      if (code >= 300) throw AiException('AI 接口返回 HTTP $code：${_cut(text)}');
      final j = jsonDecode(text) as Map;
      final content = ((j['choices'] as List).first as Map)['message']['content'];
      if (content is List) {
        return content.map((p) => p is Map ? '${p['text'] ?? ''}' : '').join().trim(); // 少数兼容接口返回分段内容
      }
      return '${content ?? ''}'.trim();
    } on AiException {
      rethrow;
    } on TimeoutException {
      throw AiException('AI 接口超时，稍后会再试');
    } on SocketException catch (e) {
      throw AiException('连不上 AI 接口（${e.message}），检查网络或接口地址');
    } on HandshakeException {
      throw AiException('连 AI 接口时安全连接失败，检查网络或接口地址');
    } on FormatException {
      throw AiException('AI 接口返回的内容看不懂，检查接口地址是否填到了 /v1');
    } finally {
      client.close(force: true);
    }
  }

  static String _cut(String t) => t.length > 200 ? t.substring(0, 200) : t;

  /// 让 AI 听几段录音
  Future<String> listen(String system, String header, List<AudioPart> parts) {
    final content = <Map<String, dynamic>>[
      {'type': 'text', 'text': header},
      for (final p in parts) ...[
        {'type': 'text', 'text': p.label},
        {
          'type': 'input_audio',
          'input_audio': {'data': base64Encode(wavBytes(p.pcm)), 'format': 'wav'}
        },
      ],
    ];
    return _post(_tune({
      'model': s.aiListenModel,
      'modalities': ['text'],
      'messages': [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': content},
      ],
      'temperature': 0.8,
      'max_tokens': 12000,
    }, 32000), const Duration(minutes: 5), audio: true);
  }

  /// 文字对话（总复盘、日 / 月 / 年复盘）
  Future<String> chat(String system, String user) => _post(_tune({
        'model': s.aiChatModel,
        'messages': [
          {'role': 'system', 'content': system},
          {'role': 'user', 'content': user},
        ],
        'temperature': 0.9,
        'max_tokens': 4000,
      }, 16000), const Duration(minutes: 3));

  /// Google Gemini：不认 modalities；关不掉“思考”且思考也占输出额度，调到最省、额度放宽（免得复盘被截断）
  Map<String, dynamic> _tune(Map<String, dynamic> body, int geminiMaxTokens) {
    if (!s.aiEndpoint.contains('generativelanguage.googleapis.com')) return body;
    return Map.of(body)
      ..remove('modalities')
      ..['reasoning_effort'] = 'low'
      ..['max_tokens'] = geminiMaxTokens;
  }

  /// 设置页的测试按钮：发 1.5 秒提示音，确认 Key、模型都能用
  Future<String> test() async {
    final n = (kSampleRate * 1.5).round();
    final bd = ByteData(n * 2);
    for (var i = 0; i < n; i++) {
      // 440Hz 方波（不需要 sin，够 AI 听出“有声音”）
      bd.setInt16(i * 2, ((i * 440 * 2 ~/ kSampleRate).isEven ? 6000 : -6000), Endian.little);
    }
    final out = await listen('', '这是一段测试音频。请用一句中文描述你听到了什么。', [AudioPart('【测试】', bd.buffer.asUint8List())]);
    return 'AI 能听到录音（${s.aiListenModel}）：${out.length > 80 ? out.substring(0, 80) : out}';
  }
}
