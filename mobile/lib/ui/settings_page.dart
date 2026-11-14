import 'package:flutter/material.dart';

import '../app_state.dart';
import '../core/settings.dart';
import 'update_section.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.app});
  final AppState app;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

/// 电脑端的一个设置项（通过网络读写电脑上的 config）
class _R {
  const _R(this.key, this.label,
      {this.hint, this.type = 'text', this.options = const {}, this.lines = 1});
  final String key;
  final String label;
  final String? hint;
  final String type; // text / secret / int / choice
  final Map<String, String> options;
  final int lines;
}

const _remoteGroups = <String, List<_R>>{
  'AI 复盘': [
    _R('review_mode', '小复盘：多久做一次', type: 'choice', options: {
      'interval': '自定义周期：每隔 N 分钟复盘一次',
      'realtime': '实时：每说完一段就立刻复盘',
    }),
    _R('review_interval_min', '【自定义周期】每隔多少分钟复盘一次', type: 'int', hint: '1–240'),
    _R('review_min_sec', '【自定义周期】新语音少于多少秒就跳过这一轮', type: 'int'),
    _R('realtime_min_sec', '【实时复盘】一段语音少于多少秒先攒着', type: 'int'),
    _R('session_review', '大复盘：整场总复盘', type: 'choice', options: {
      'end': '一场录音结束时做',
      'off': '不做（只看日 / 月 / 年复盘）',
    }),
    _R('daily_review_time', '大复盘：日复盘每天几点做', hint: '24 小时制，如 23:00；留空 = 不自动做'),
    _R('monthly_review', '大复盘：月复盘', type: 'choice', options: {
      'month_end': '每月最后一天做',
      'next_month': '下个月 1 号做',
      'off': '不自动做（可以手动生成）',
    }),
    _R('yearly_review', '大复盘：年复盘', type: 'choice', options: {
      'year_end': '12 月 31 日做',
      'next_year': '次年 1 月 1 日做',
      'off': '不自动做（可以手动生成）',
    }),
    _R('period_review_time', '月复盘、年复盘在那天几点做', hint: '24 小时制，默认 23:30（排在日复盘之后）'),
    _R('about_me', '关于我（强烈建议填写）',
        hint: '你的身份、正在做的事、长期目标。AI 据此推断你的潜在需求', lines: 4),
    _R('extra_instructions', '额外要求', hint: '例如：多从商业角度想', lines: 3),
    _R('glossary', '我常说的词 / 专有名词 / 英文术语',
        hint: '人名、公司名、术语，用逗号隔开。识别错的词 AI 会按这些来理解', lines: 3),
  ],
  'AI 听录音（OpenAI）': [
    _R('review_input', 'AI 怎么拿到内容', type: 'choice', options: {
      'audio': '直接听录音（推荐）',
      'text': '电脑先识别成文字，再交给 AI（旧方式）',
    }),
    _R('audio_api_key', 'OpenAI API Key', type: 'secret',
        hint: '在 platform.openai.com 的 API keys 页面生成'),
    _R('audio_model', '听录音的模型', hint: '默认 gpt-audio-1.5'),
    _R('audio_max_min', '每次最多发送多少分钟录音', type: 'int', hint: '超过会分几次听，再合并复盘'),
  ],
  '文字 AI（总复盘、日复盘用；不填则用上面的 OpenAI）': [
    _R('llm_provider', '接口类型', type: 'choice', options: {
      'openai': 'OpenAI 兼容（OpenAI / DeepSeek / 硅基流动 / Ollama…）',
      'anthropic': 'Anthropic（Claude）',
    }),
    _R('llm_base_url', '接口地址', hint: 'OpenAI 兼容填到 /v1；Claude 填 https://api.anthropic.com'),
    _R('llm_api_key', 'API Key', type: 'secret'),
    _R('llm_model', '模型名'),
  ],
  '电脑本地识别（只在“先识别成文字”时用）': [
    _R('stt_provider', '识别模型', type: 'choice', options: {
      'sensevoice': 'SenseVoice（带标点；整句英文/粤语更好）',
      'paraformer': 'Paraformer（中文夹英文单词更稳；不带标点）',
      'whisper': 'Whisper large-v3（显卡加速，需在电脑上另外安装）',
    }),
    _R('stt_language', '语言（SenseVoice / Whisper）', hint: 'zh 普通话；留空 = 自动识别'),
    _R('pause_close_sec', '停顿多少秒算新的一段', type: 'int'),
  ],
  '存储': [
    _R('nas_dir', 'NAS 目录（电脑上能访问的路径）',
        hint: r'Windows 例：\\192.168.1.10\recordings；Mac 例：/Volumes/recordings；留空 = 只存电脑'),
  ],
};

class _SettingsPageState extends State<SettingsPage> {
  AppState get app => widget.app;
  AppSettings get s => app.settings;

  late final _url = TextEditingController(text: s.serverUrl);
  late final _url2 = TextEditingController(text: s.serverUrl2);
  late final _token = TextEditingController(text: s.token);
  late final _name = TextEditingController(text: s.deviceName);
  late final _margin = TextEditingController(text: '${s.vadMarginDb}');

  Map<String, dynamic>? _remote; // 电脑上的设置（加载成功后才有）
  final Map<String, TextEditingController> _rc = {};
  final Map<String, String> _choice = {};
  String _remoteError = '';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (app.configured) _loadRemote();
  }

  @override
  void dispose() {
    _url.dispose();
    _url2.dispose();
    _token.dispose();
    _name.dispose();
    _margin.dispose();
    for (final c in _rc.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _applyLocal() {
    s.serverUrl = _url.text;
    s.serverUrl2 = _url2.text;
    s.token = _token.text;
    s.deviceName = _name.text;
    s.vadMarginDb = double.tryParse(_margin.text.trim()) ?? s.vadMarginDb;
    app.saveSettings();
    _url.text = s.serverUrl; // 显示规范化后的地址
    _url2.text = s.serverUrl2;
    _name.text = s.deviceName;
  }

  Future<void> _loadRemote() async {
    setState(() {
      _busy = true;
      _remoteError = '';
    });
    try {
      final cfg = await app.api.getConfig();
      for (final g in _remoteGroups.values) {
        for (final f in g) {
          final v = cfg[f.key];
          if (f.type == 'choice') {
            _choice[f.key] = f.options.containsKey('$v') ? '$v' : f.options.keys.first;
          } else {
            final text = v == null ? '' : '$v';
            final c = _rc[f.key];
            if (c == null) {
              _rc[f.key] = TextEditingController(text: text);
            } else {
              c.text = text;
            }
          }
        }
      }
      if (mounted) setState(() => _remote = cfg);
    } catch (e) {
      if (mounted) setState(() => _remoteError = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 只把改过的项发给电脑
  Map<String, dynamic> _remotePatch() {
    final cfg = _remote;
    final patch = <String, dynamic>{};
    if (cfg == null) return patch;
    for (final g in _remoteGroups.values) {
      for (final f in g) {
        final Object? v;
        if (f.type == 'choice') {
          v = _choice[f.key];
        } else if (f.type == 'int') {
          v = int.tryParse(_rc[f.key]!.text.trim());
          if (v == null) continue;
        } else {
          v = f.type == 'secret' ? _rc[f.key]!.text.trim() : _rc[f.key]!.text;
        }
        if ('$v' != '${cfg[f.key] ?? ''}') patch[f.key] = v;
      }
    }
    return patch;
  }

  Future<bool> _saveAll({bool quiet = false}) async {
    _applyLocal();
    final patch = _remotePatch();
    try {
      if (patch.isNotEmpty) {
        await app.api.setConfig(patch);
        _remote = {...?_remote, ...patch};
      }
      if (!quiet && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(_remote == null ? '已保存手机上的设置' : '已保存（电脑上的设置已同步）')));
      }
      return true;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('手机上的设置已保存；电脑上的没保存成功：$e')));
      }
      return false;
    }
  }

  Future<void> _dialog(String msg) => showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          content: SelectableText(msg),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('好'))],
        ),
      );

  Future<void> _connect() async {
    _applyLocal();
    setState(() => _busy = true);
    String msg;
    try {
      await app.api.view();
      msg = '✅ 已连上电脑\n当前使用的地址：${app.endpoints.active}'
          '${app.endpoints.usingBackup ? '（备用地址）' : ''}';
    } catch (e) {
      msg = '❌ $e';
    }
    if (!mounted) return;
    setState(() => _busy = false);
    await _dialog(msg);
    if (msg.startsWith('✅')) await _loadRemote();
  }

  Future<void> _remoteTest(String kind) async {
    if (!await _saveAll(quiet: true)) return;
    setState(() => _busy = true);
    String msg;
    try {
      msg = await app.api.test(kind);
    } catch (e) {
      msg = '❌ $e';
    }
    if (!mounted) return;
    setState(() => _busy = false);
    await _dialog(msg);
  }

  Widget _title(String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(top: 22, bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: Theme.of(context).colorScheme.primary)),
          if (sub != null) Text(sub, style: Theme.of(context).textTheme.bodySmall),
        ]),
      );

  Widget _text(TextEditingController c, String label,
          {String? hint, bool secret = false, bool number = false, int lines = 1}) =>
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: TextField(
          controller: c,
          obscureText: secret,
          maxLines: secret ? 1 : lines,
          autocorrect: false,
          enableSuggestions: !secret,
          keyboardType: number
              ? const TextInputType.numberWithOptions(signed: true, decimal: true)
              : null,
          decoration: InputDecoration(
              labelText: label,
              helperText: hint,
              helperMaxLines: 3,
              border: const OutlineInputBorder(),
              isDense: true),
        ),
      );

  Widget _dropdown(_R f) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: InputDecorator(
          decoration: InputDecoration(
              labelText: f.label, border: const OutlineInputBorder(), isDense: true),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              value: _choice[f.key],
              isExpanded: true,
              isDense: true,
              items: [
                for (final e in f.options.entries)
                  DropdownMenuItem(
                      value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis)),
              ],
              onChanged: (v) {
                if (v != null) setState(() => _choice[f.key] = v);
              },
            ),
          ),
        ),
      );

  Widget _switch(String title, String? sub, bool value, void Function(bool) onChanged) =>
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(title),
        subtitle: sub == null ? null : Text(sub),
        value: value,
        onChanged: (v) => setState(() => onChanged(v)),
      );

  Widget _btn(String label, VoidCallback onPressed) => Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton(onPressed: onPressed, child: Text(label)),
      );

  List<Widget> _remoteWidgets() {
    if (_remote == null) {
      return [
        _title('电脑上的设置'),
        Text(_remoteError.isNotEmpty
            ? '读取失败：$_remoteError'
            : app.configured
                ? '正在读取…'
                : '连上电脑后，这里可以设置 AI 复盘、AI 接口、语音识别和 NAS。'),
        if (_remoteError.isNotEmpty) _btn('重试', _loadRemote),
      ];
    }
    final out = <Widget>[];
    _remoteGroups.forEach((title, fields) {
      out.add(_title(title, title == 'AI 复盘' ? '以下设置保存在电脑上，对电脑和手机都生效' : null));
      for (final f in fields) {
        out.add(f.type == 'choice'
            ? _dropdown(f)
            : _text(_rc[f.key]!, f.label,
                hint: f.hint,
                secret: f.type == 'secret',
                number: f.type == 'int',
                lines: f.lines));
      }
      if (title.startsWith('AI 听录音')) {
        out.add(_btn('测试 AI 能不能听到录音', () => _remoteTest('audio')));
      }
      if (title.startsWith('文字 AI')) out.add(_btn('测试文字 AI', () => _remoteTest('llm')));
      if (title.startsWith('电脑本地识别')) out.add(_btn('检查 / 下载识别模型', () => _remoteTest('stt')));
      if (title == '存储') out.add(_btn('测试 NAS 写入', () => _remoteTest('nas')));
    });
    return out;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('设置'),
        actions: [TextButton(onPressed: _busy ? null : _saveAll, child: const Text('保存'))],
      ),
      body: AbsorbPointer(
        absorbing: _busy,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 48),
          children: [
            if (_busy) const LinearProgressIndicator(),
            _title('连接电脑', '在电脑上打开「AI 录音思考助手」→「设备连接」，照着填'),
            _text(_url, '电脑地址（在家 / 同一个 WiFi 时用）', hint: '例如 http://192.168.1.20:8765'),
            _text(_url2, '备用地址（外出时用，可不填）',
                hint: '手机和电脑都装 Tailscale 后，填电脑的 http://100.x.x.x:8765。哪个地址能连上就自动用哪个'),
            _text(_token, '连接口令'),
            _text(_name, '这台设备的名字',
                hint: '几台手机/平板同时录音时，电脑上用它区分，例如“客厅手机”“办公室 iPad”'),
            _btn('测试连接', _connect),
            _title('录音与上传（手机上）'),
            _switch('仅 WiFi 下上传', '打开：用移动网络时不传，录音先存手机，连上 WiFi 再补传。\n关闭：在外面用移动网络也实时传（需要填备用地址）', s.wifiOnly,
                (v) => s.wifiOnly = v),
            _switch('用移动网络时压缩后再传', '流量约为原来的 1/4，对识别准确度影响很小', s.compressOnCellular,
                (v) => s.compressOnCellular = v),
            _switch('没人说话的片段不上传', '省流量、省电，也省 NAS 空间', s.skipSilence,
                (v) => s.skipSilence = v),
            _switch('打开 App 就自动开始录音', '适合全天候使用', s.autoStart, (v) => s.autoStart = v),
            _switch('麦克风自动增益', '手机离得远、声音小时有帮助（下次开始录音生效）', s.micAutoGain,
                (v) => s.micAutoGain = v),
            _switch('系统降噪', '环境嘈杂时可以试试（下次开始录音生效）', s.micNoiseSuppress,
                (v) => s.micNoiseSuppress = v),
            _text(_margin, '声音检测灵敏度（dB）',
                number: true, hint: '比环境噪音高多少算“有人说话”。漏掉小声说话就调小（5–6），环境吵就调大（10–15）'),
            ..._remoteWidgets(),
            UpdateSection(app: app),
          ],
        ),
      ),
    );
  }
}
