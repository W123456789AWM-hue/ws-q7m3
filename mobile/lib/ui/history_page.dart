import 'package:flutter/material.dart';

import '../app_state.dart';
import 'home_page.dart' show asMaps;
import 'widgets.dart';

/// 加载中 / 出错 / 内容 三种状态的通用外壳
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder});
  final Future<T> Function() load;
  final Widget Function(BuildContext, T) builder;

  @override
  State<Loader<T>> createState() => _LoaderState<T>();
}

class _LoaderState<T> extends State<Loader<T>> {
  late Future<T> _f = widget.load();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: _f,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text('${snap.error}', textAlign: TextAlign.center),
                const SizedBox(height: 12),
                OutlinedButton(
                    onPressed: () => setState(() => _f = widget.load()),
                    child: const Text('重试')),
              ]),
            ),
          );
        }
        return widget.builder(context, snap.data as T);
      },
    );
  }
}

class HistoryPage extends StatelessWidget {
  const HistoryPage({super.key, required this.app});
  final AppState app;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('历史记录')),
      body: Loader<List<Map<String, dynamic>>>(
        load: app.api.sessions,
        builder: (context, items) {
          if (items.isEmpty) return const Center(child: Text('还没有记录'));
          return ListView.builder(
            itemCount: items.length,
            itemBuilder: (context, i) {
              final s = items[i];
              final title = '${s['title'] ?? ''}'.isEmpty ? '（未命名）' : '${s['title']}';
              return ListTile(
                title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(
                    '${'${s['started']}'.replaceFirst('T', ' ').split('.').first} · ${s['count']} 次复盘'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => SessionPage(app: app, id: '${s['id']}', title: title))),
              );
            },
          );
        },
      ),
    );
  }
}

/// 查看一次历史录音：总复盘 + 各次复盘 + 完整转写
class SessionPage extends StatelessWidget {
  const SessionPage({super.key, required this.app, required this.id, required this.title});
  final AppState app;
  final String id;
  final String title;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(title),
          bottom: const TabBar(tabs: [Tab(text: 'AI 复盘'), Tab(text: '完整转写')]),
        ),
        body: Loader<Map<String, dynamic>>(
          load: () => app.api.session(id),
          builder: (context, session) {
            final reviews = asMaps(session['reviews']).reversed.toList();
            final summary = '${session['summary'] ?? ''}';
            return TabBarView(children: [
              ListView(
                padding: const EdgeInsets.only(top: 6, bottom: 24),
                children: [
                  if (summary.isNotEmpty) SummaryCard(summary),
                  for (final r in reviews) ReviewCard(r),
                  if (summary.isEmpty && reviews.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(32),
                        child: Center(child: Text('这次录音没有复盘内容'))),
                ],
              ),
              TranscriptList(asMaps(session['paragraphs'])),
            ]);
          },
        ),
      ),
    );
  }
}
