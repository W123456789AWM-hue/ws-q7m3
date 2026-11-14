import 'package:flutter/material.dart';

import 'theme.dart';

/// 极简 Markdown 显示（标题、列表、加粗），用于总复盘和日复盘
class MarkdownLite extends StatelessWidget {
  const MarkdownLite(this.text, {super.key});
  final String text;

  static final _bold = RegExp(r'\*\*(.+?)\*\*');

  TextSpan _inline(String s, TextStyle? base) {
    final spans = <TextSpan>[];
    var last = 0;
    for (final m in _bold.allMatches(s)) {
      if (m.start > last) spans.add(TextSpan(text: s.substring(last, m.start)));
      spans.add(TextSpan(
          text: m.group(1), style: const TextStyle(fontWeight: FontWeight.w700)));
      last = m.end;
    }
    if (last < s.length) spans.add(TextSpan(text: s.substring(last)));
    return TextSpan(style: base, children: spans);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final body = theme.textTheme.bodyMedium?.copyWith(height: 1.55);
    final children = <Widget>[];
    for (final raw in text.split('\n')) {
      final l = raw.trimRight();
      if (l.trim().isEmpty) continue;
      final h = RegExp(r'^(#{1,4})\s+(.*)$').firstMatch(l);
      final li = RegExp(r'^\s*[-*]\s+(\[[ xX]\]\s+)?(.*)$').firstMatch(l);
      if (h != null) {
        children.add(Padding(
          padding: const EdgeInsets.only(top: 12, bottom: 4),
          child: Text(h.group(2)!,
              style: theme.textTheme.titleSmall?.copyWith(
                  color: theme.colorScheme.primary, fontWeight: FontWeight.w700)),
        ));
      } else if (li != null) {
        children.add(Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(li.group(1) != null ? '☐ ' : '• ', style: body),
            Expanded(child: Text.rich(_inline(li.group(2)!, body))),
          ]),
        ));
      } else {
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text.rich(_inline(l, body)),
        ));
      }
    }
    return SelectionArea(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children));
  }
}

const _kindNames = {
  'realtime': '实时复盘',
  'periodic': '定时复盘',
  'manual': '手动复盘',
  'final_part': '收尾复盘',
};

/// 复盘卡片里每个小节的颜色（和电脑端一样用系统色）
Color _tone(BuildContext context, String k) {
  final c = context.c;
  return switch (k) {
    'amber' => c.orange,
    'violet' => c.purple,
    'blue' => c.accent,
    'green' => c.green,
    'teal' => c.teal,
    'orange' => c.red,
    _ => c.label2,
  };
}

String _fmtSec(Object? v) {
  final s = (v is num ? v : num.tryParse('$v') ?? 0).round();
  return s >= 60 ? '${s ~/ 60} 分 ${s % 60} 秒' : '$s 秒';
}

/// 一次 AI 复盘的卡片
class ReviewCard extends StatelessWidget {
  const ReviewCard(this.r, {super.key, this.onRetry});
  final Map<String, dynamic> r;
  final VoidCallback? onRetry;

  Widget _section(BuildContext context, String tone, String title, Object? items,
      Widget Function(Object? item) build) {
    if (items is! List || items.isEmpty) return const SizedBox.shrink();
    final col = _tone(context, tone);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
      decoration: BoxDecoration(
          color: col.withValues(alpha: .1), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title,
            style: TextStyle(
                color: col, fontWeight: FontWeight.w700, fontSize: 13)),
        const SizedBox(height: 4),
        for (final x in items)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('• '),
              Expanded(child: build(x)),
            ]),
          ),
      ]),
    );
  }

  Widget _plain(Object? x) => Text('$x', style: const TextStyle(height: 1.5));

  Widget _tagged(BuildContext context, String tag, String text, {bool hot = false}) {
    final scheme = Theme.of(context).colorScheme;
    return Text.rich(TextSpan(style: const TextStyle(height: 1.5), children: [
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Container(
          margin: const EdgeInsets.only(right: 6),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(
              color: hot ? scheme.errorContainer : scheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(4)),
          child: Text(tag,
              style: TextStyle(
                  fontSize: 11,
                  color: hot ? scheme.onErrorContainer : scheme.onSurfaceVariant)),
        ),
      ),
      TextSpan(text: text),
    ]));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final a = (r['analysis'] as Map?) ?? const {};
    final status = '${r['status']}';
    final kind = _kindNames['${r['kind']}'] ?? '复盘';
    final title = '${a['title'] ?? ''}'.isEmpty ? kind : '${a['title']}';
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.outline);

    final body = <Widget>[];
    if (status == 'analyzing') {
      body.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(children: [
          const SizedBox(
              width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
          const SizedBox(width: 10),
          Expanded(
              child: Text(r['sec'] != null
                  ? 'AI 正在听 ${_fmtSec(r['sec'])} 的录音并发散思考…'
                  : 'AI 正在发散思考 ${r['chars']} 字的内容…')),
        ]),
      ));
    } else if (status == 'error') {
      body.add(Text('${r['error']}', style: TextStyle(color: theme.colorScheme.error)));
      if (onRetry != null) {
        body.add(Align(
            alignment: Alignment.centerLeft,
            child: TextButton(onPressed: onRetry, child: const Text('重试'))));
      }
    } else if (a['trivial'] == true) {
      body.add(Text('这段时间以闲聊或噪音为主。${a['summary'] ?? ''}', style: muted));
    } else {
      body.add(Text('${a['summary'] ?? ''}', style: const TextStyle(height: 1.55)));
      body.add(_section(context, 'amber', '🔍 你可能没注意到', a['blind_spots'], _plain));
      body.add(_section(context, 'violet', '💡 潜在需求', a['latent_needs'], (x) {
        if (x is! Map) return _plain(x);
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${x['need']}', style: const TextStyle(height: 1.5)),
          Text('依据：${x['evidence']}', style: muted),
        ]);
      }));
      body.add(_section(
          context,
          'blue',
          '🌀 发散联想',
          a['divergent'],
          (x) => x is Map
              ? _tagged(context, '${x['angle']}', '${x['idea']}')
              : _plain(x)));
      body.add(_section(
          context,
          'green',
          '✅ 建议',
          a['suggestions'],
          (x) => x is Map
              ? _tagged(context, '${x['priority'] ?? ''}', '${x['text']}',
                  hot: x['priority'] == '高')
              : _plain(x)));
      body.add(_section(context, 'gray', '❓ 值得追问自己', a['questions'], _plain));
      body.add(_section(context, 'orange', '🔁 和上次复盘相比', a['changes'], _plain));
      body.add(_section(context, 'teal', '🎧 从语气里听出来的', a['voice_cues'], _plain));
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: theme.textTheme.titleMedium),
          Text('${r['from_clock']}–${r['to_clock']} · $kind', style: muted),
          const SizedBox(height: 6),
          ...body,
          if ('${r['text'] ?? ''}'.isNotEmpty)
            Theme(
              data: theme.copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: const EdgeInsets.only(bottom: 8),
                dense: true,
                title: Text('${r['sec'] != null ? 'AI 听写的原文' : '这次复盘用到的原文'}（${r['chars']} 字）',
                    style: muted),
                children: [
                  SelectableText('${r['text']}', style: theme.textTheme.bodySmall)
                ],
              ),
            ),
        ]),
      ),
    );
  }
}

/// 整场总复盘卡片
class SummaryCard extends StatelessWidget {
  const SummaryCard(this.markdown, {super.key, this.title = '📋 整场总复盘'});
  final String markdown;
  final String title;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: theme.colorScheme.primary.withValues(alpha: .55))),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: theme.textTheme.titleMedium),
          MarkdownLite(markdown),
        ]),
      ),
    );
  }
}

/// 转写列表（按段落）
class TranscriptList extends StatelessWidget {
  const TranscriptList(this.paragraphs, {super.key, this.controller, this.shrinkWrap = false});

  /// true：放在别的滚动列表里面，自己不滚动
  final List<Map<String, dynamic>> paragraphs;
  final ScrollController? controller;
  final bool shrinkWrap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (paragraphs.isEmpty) {
      return Padding(
          padding: const EdgeInsets.all(36),
          child: Center(child: Text('还没有听写内容', style: TextStyle(color: theme.colorScheme.outline))));
    }
    // 几台设备同时录音时，每段前面标上是哪台设备录的
    final multi = paragraphs.map((p) => p['device_name'] ?? '').toSet().length > 1;
    return ListView.separated(
      controller: controller,
      shrinkWrap: shrinkWrap,
      physics: shrinkWrap ? const NeverScrollableScrollPhysics() : null,
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
      itemCount: paragraphs.length,
      separatorBuilder: (_, __) => const Divider(height: 24),
      itemBuilder: (context, i) {
        final p = paragraphs[i];
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
              '${p['start_clock']}${multi && '${p['device_name'] ?? ''}'.isNotEmpty ? ' · ${p['device_name']}' : ''}'
              '${p['status'] == 'live' ? ' · 正在听' : ''}',
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.outline)),
          const SizedBox(height: 2),
          SelectableText('${p['text']}', style: const TextStyle(height: 1.6)),
        ]);
      },
    );
  }
}
