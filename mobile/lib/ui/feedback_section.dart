import 'dart:io';

import 'package:flutter/material.dart';

import '../app_state.dart';
import 'update_section.dart' show appVersion;

/// 设置页里的「反馈」：写好后发给电脑，由电脑转发给开发者（手机里不存机器人地址）
class FeedbackSection extends StatefulWidget {
  const FeedbackSection({super.key, required this.app});
  final AppState app;

  @override
  State<FeedbackSection> createState() => _FeedbackSectionState();
}

class _FeedbackSectionState extends State<FeedbackSection> {
  static const _kinds = {'bug': '问题', 'idea': '建议', 'other': '其他'};
  final _text = TextEditingController();
  final _contact = TextEditingController();
  String _kind = 'bug';
  bool _diag = true, _sending = false;
  String _msg = '';
  List<Map<String, dynamic>> _items = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _text.dispose();
    _contact.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final items = await widget.app.api.feedbackHistory();
      if (mounted) setState(() => _items = items);
    } catch (_) {/* 没连上电脑 / 电脑端是旧版 */}
  }

  Future<void> _send() async {
    final text = _text.text.trim();
    if (text.isEmpty) {
      setState(() => _msg = '先写一下想说的');
      return;
    }
    setState(() {
      _sending = true;
      _msg = '';
    });
    final s = widget.app.settings;
    try {
      final r = await widget.app.api.sendFeedback({
        'kind': _kind,
        'text': text,
        'contact': _contact.text.trim(),
        'include_diag': _diag,
        'source': s.deviceName,
        'client': 'App $appVersion · ${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
      });
      _text.clear();
      setState(() {
        _msg = r['status'] == 'sent' ? '已送达，谢谢你的反馈！' : '电脑暂时没发出去，已存好，联网后会自动重发';
        _items = [r, ..._items.where((x) => x['id'] != r['id'])];
      });
    } catch (e) {
      setState(() => _msg = '发送失败：$e（要先连上电脑）');
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    String when(num ts) {
      final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
      return '${d.month}/${d.day} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
    }

    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('反馈', style: t.textTheme.titleMedium?.copyWith(color: t.colorScheme.primary)),
        const SizedBox(height: 4),
        Text('遇到问题或想要新功能，直接告诉开发者（经电脑转发）', style: TextStyle(color: t.colorScheme.outline)),
        const SizedBox(height: 8),
        SegmentedButton<String>(
          segments: [for (final e in _kinds.entries) ButtonSegment(value: e.key, label: Text(e.value))],
          selected: {_kind},
          showSelectedIcon: false,
          onSelectionChanged: (v) => setState(() => _kind = v.first),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _text,
          minLines: 3,
          maxLines: 8,
          maxLength: 4000,
          decoration: const InputDecoration(
              labelText: '想说的', hintText: '怎么操作的、看到了什么，或者希望加什么功能', border: OutlineInputBorder()),
        ),
        TextField(
          controller: _contact,
          maxLength: 100,
          decoration: const InputDecoration(labelText: '联系方式（选填：微信 / 邮箱）', border: OutlineInputBorder()),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('附带诊断信息'),
          subtitle: const Text('版本、系统、电脑端最近的日志（密钥会自动抹掉，不含录音和复盘内容）'),
          value: _diag,
          onChanged: (v) => setState(() => _diag = v),
        ),
        FilledButton(onPressed: _sending ? null : _send, child: Text(_sending ? '发送中…' : '发送')),
        if (_msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_msg)),
        if (_items.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('发过的反馈', style: t.textTheme.titleSmall),
          for (final x in _items.take(10))
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text('${x['text']}', maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Text('${_kinds[x['kind']] ?? '其他'} · ${when(x['time'] as num)}'
                  '${'${x['source'] ?? ''}'.isNotEmpty ? ' · ${x['source']}' : ''}'),
              trailing: Text(x['status'] == 'sent' ? '已送达' : '等待发送',
                  style: TextStyle(color: x['status'] == 'sent' ? Colors.green : Colors.orange)),
            ),
        ],
      ]),
    );
  }
}
