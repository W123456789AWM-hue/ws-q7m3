import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../app_state.dart';
import '../core/endpoints.dart' show ApiException;
import 'update_section.dart' show appVersion;

/// 设置页里的「反馈」：连着电脑时发给电脑转发（带上电脑端的诊断信息）；
/// 不连电脑、或电脑连不上时，手机直接发给开发者（core/feedback.dart），发不出去先存手机、联网后自动重发
class FeedbackSection extends StatefulWidget {
  const FeedbackSection({super.key, required this.app});
  final AppState app;

  @override
  State<FeedbackSection> createState() => _FeedbackSectionState();
}

class _FeedbackSectionState extends State<FeedbackSection> {
  static const _kinds = {'bug': '问题', 'idea': '建议', 'other': '其他'};
  static const _maxImages = 3;
  final _text = TextEditingController();
  final _contact = TextEditingController();
  String _kind = 'bug';
  bool _diag = true, _sending = false;
  String _msg = '';
  List<Map<String, dynamic>> _items = [];
  final List<XFile> _images = []; // 附图（选填）

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
    final app = widget.app;
    var remote = <Map<String, dynamic>>[];
    if (!app.standalone && app.configured) {
      try {
        remote = await app.api.feedbackHistory();
      } catch (_) {/* 没连上电脑 / 电脑端是旧版 */}
    }
    if (mounted) setState(() => _items = _merge(app.feedback.history(), remote));
  }

  /// 手机直接发的 + 电脑上记的，按时间排（新的在前）
  static List<Map<String, dynamic>> _merge(List<Map<String, dynamic>> a, List<Map<String, dynamic>> b) {
    final seen = <String>{};
    final all = [
      for (final x in [...a, ...b])
        if (seen.add('${x['id']}')) x
    ]..sort((x, y) => ((y['time'] as num?) ?? 0).compareTo((x['time'] as num?) ?? 0));
    return all;
  }

  /// 手机直接发时附带的诊断信息（不含 Key、录音和复盘内容）
  String _phoneDiag() {
    final app = widget.app;
    final s = app.settings;
    return [
      '发送设备：App $appVersion · ${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
      '用法：${s.standalone ? '手机独立复盘（${s.google ? 'Google' : s.aiEndpoint.replaceFirst(RegExp(r'^https?://'), '')}）' : '连接电脑'}',
      if (!s.standalone) '电脑：${app.configured ? '已填地址，这次没连上' : '还没填电脑地址'}',
      if (app.viewError.isNotEmpty) '最近的错误：${app.viewError}',
    ].join('\n');
  }

  /// 从相册选截图：系统自带的图片选择器，不用申请相册权限；先缩到长边 1600 再发
  Future<void> _pick() async {
    final room = _maxImages - _images.length;
    if (room <= 0) return;
    try {
      final picked = await ImagePicker()
          .pickMultiImage(maxWidth: 1600, maxHeight: 1600, imageQuality: 85, limit: room > 1 ? room : null);
      if (picked.isEmpty || !mounted) return;
      setState(() {
        _images.addAll(picked.take(room));
        _msg = picked.length > room ? '附图最多 $_maxImages 张，多的没加上' : '';
      });
    } catch (e) {
      if (mounted) setState(() => _msg = '没能打开相册：$e');
    }
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
    final app = widget.app;
    final s = app.settings;
    try {
      final bytes = [for (final f in _images) await f.readAsBytes()];
      Map<String, dynamic>? r;
      var direct = true;
      if (!app.standalone && app.configured) {
        try {
          r = await app.api.sendFeedback({
            'kind': _kind,
            'text': text,
            'contact': _contact.text.trim(),
            'include_diag': _diag,
            'source': s.deviceName,
            'client': 'App $appVersion · ${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
            if (bytes.isNotEmpty) 'images': [for (final b in bytes) base64Encode(b)],
          });
          direct = false;
        } on ApiException catch (e) {
          // 电脑回了明确的错误（比如内容不合规）就照实说；电脑是旧版没有反馈功能（404）时改为手机直接发
          if (e.status != 404) rethrow;
        } catch (_) {/* 电脑连不上：手机直接发 */}
      }
      if (direct) {
        if (!app.feedback.configured) {
          throw Exception(app.standalone ? '这个版本没有内置反馈通道，请更新 App' : '连不上电脑，这个版本也没有内置反馈通道');
        }
        r = await app.feedback.submit(
          kind: _kind,
          text: text,
          contact: _contact.text.trim(),
          source: s.deviceName,
          version: appVersion,
          diag: _diag ? _phoneDiag() : '',
          images: bytes,
        );
      }
      final item = r!;
      _text.clear();
      setState(() {
        _images.clear();
        _msg = item['status'] == 'sent'
            ? '已送达，谢谢你的反馈！'
            : direct
                ? '暂时没发出去（${item['error']}），已存在手机上，联网后会自动重发'
                : '电脑暂时没发出去，已存好，联网后会自动重发';
        _items = _merge([item], _items);
      });
    } catch (e) {
      setState(() => _msg = '发送失败：${'$e'.replaceFirst('Exception: ', '')}');
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
        Text('反馈', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(
            widget.app.standalone || !widget.app.configured
                ? '遇到问题或想要新功能，直接告诉开发者（不用连电脑）'
                : '遇到问题或想要新功能，直接告诉开发者（连着电脑时经电脑转发，连不上就由手机直接发）',
            style: TextStyle(color: t.colorScheme.outline)),
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
        Text('附图（选填）', style: t.textTheme.bodyMedium),
        Text('截图能让开发者更快看懂问题，最多 $_maxImages 张', style: TextStyle(color: t.colorScheme.outline, fontSize: 12)),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (var i = 0; i < _images.length; i++)
            Stack(children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.file(File(_images[i].path), width: 76, height: 76, fit: BoxFit.cover),
              ),
              Positioned(
                top: 2,
                right: 2,
                child: InkWell(
                  onTap: () => setState(() => _images.removeAt(i)),
                  child: const CircleAvatar(
                      radius: 11, backgroundColor: Colors.black54, child: Icon(Icons.close, size: 14, color: Colors.white)),
                ),
              ),
            ]),
          if (_images.length < _maxImages)
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size(76, 76)),
              onPressed: _sending ? null : _pick,
              icon: const Icon(Icons.add_photo_alternate_outlined),
              label: const Text('添加图片'),
            ),
        ]),
        const SizedBox(height: 16),
        TextField(
          controller: _contact,
          maxLength: 100,
          decoration: const InputDecoration(labelText: '联系方式（选填：微信 / 邮箱）', border: OutlineInputBorder()),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('附带诊断信息'),
          subtitle: const Text('版本、系统、最近的错误（连着电脑时还有电脑端日志；密钥会自动抹掉，不含录音和复盘内容）'),
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
                  '${'${x['source'] ?? ''}'.isNotEmpty ? ' · ${x['source']}' : ''}'
                  '${(x['images'] as List?)?.isNotEmpty == true ? ' · 附图 ${(x['images'] as List).length} 张' : ''}'),
              trailing: Text(x['status'] == 'sent' ? '已送达' : '等待发送',
                  style: TextStyle(color: x['status'] == 'sent' ? Colors.green : Colors.orange)),
            ),
        ],
      ]),
    );
  }
}
