import 'package:flutter/material.dart';

import '../app_state.dart';
import '../core/util.dart';
import 'widgets.dart';

/// 复盘报告：日复盘 / 月复盘 / 年复盘（电脑上按设置自动生成，这里查看或手动生成）
class DailyPage extends StatefulWidget {
  const DailyPage({super.key, required this.app});
  final AppState app;

  @override
  State<DailyPage> createState() => _DailyPageState();
}

const _names = {'day': '日复盘', 'month': '月复盘', 'year': '年复盘'};
const _spans = {'day': '这一天', 'month': '这个月', 'year': '这一年'};
const _emptyHints = {
  'day': '这一天还没有日复盘。\n电脑会在设置的时间自动生成，也可以现在手动生成。',
  'month': '这个月还没有月复盘。\n电脑会按设置在月底（或下月 1 号）自动生成，也可以现在手动生成。\n月复盘会用上这个月每天的日复盘。',
  'year': '这一年还没有年复盘。\n电脑会按设置在年底（或次年 1 月 1 日）自动生成，也可以现在手动生成。\n年复盘会用上每个月的月复盘。',
};

class _DailyPageState extends State<DailyPage> {
  String _period = 'day';
  DateTime _date = DateTime.now();
  String _md = '';
  bool _busy = false;
  bool _loading = true;
  String _error = '';

  String get _key => switch (_period) {
        'month' => '${_date.year}-${pad2(_date.month)}',
        'year' => '${_date.year}',
        _ => fmtDate(_date),
      };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    final key = _key, period = _period;
    try {
      final md = await widget.app.api.report(period, key);
      if (mounted && key == _key && period == _period) setState(() => _md = md);
    } catch (e) {
      if (mounted) {
        setState(() {
          _md = '';
          _error = '$e';
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _step(int n) {
    final d = _date;
    _date = switch (_period) {
      'year' => DateTime(d.year + n, 1, 1),
      'month' => DateTime(d.year, d.month + n, 1),
      _ => d.add(Duration(days: n)),
    };
    _load();
  }

  bool get _atNow {
    final now = DateTime.now();
    return switch (_period) {
      'year' => _date.year >= now.year,
      'month' => _date.year > now.year || (_date.year == now.year && _date.month >= now.month),
      _ => fmtDate(_date).compareTo(fmtDate(now)) >= 0,
    };
  }

  Future<void> _pick() async {
    if (_period != 'day') return;
    final d = await showDatePicker(
        context: context, initialDate: _date, firstDate: DateTime(2024), lastDate: DateTime.now());
    if (d != null) {
      _date = d;
      await _load();
    }
  }

  Future<void> _make() async {
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final md = await widget.app.api.report(_period, _key, make: true);
      if (mounted) setState(() => _md = md);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = _names[_period]!;
    return Scaffold(
      appBar: AppBar(title: const Text('复盘报告')),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          if (_loading) const LinearProgressIndicator() else const SizedBox(height: 4),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'day', label: Text('日')),
                ButtonSegment(value: 'month', label: Text('月')),
                ButtonSegment(value: 'year', label: Text('年')),
              ],
              selected: {_period},
              onSelectionChanged: (v) {
                _period = v.first;
                _load();
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(onPressed: _busy ? null : () => _step(-1), icon: const Icon(Icons.chevron_left)),
                TextButton.icon(
                  onPressed: _period == 'day' && !_busy ? _pick : null,
                  icon: const Icon(Icons.calendar_month),
                  label: Text(_key, style: const TextStyle(fontSize: 16)),
                ),
                IconButton(
                    onPressed: _busy || _atNow ? null : () => _step(1),
                    icon: const Icon(Icons.chevron_right)),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            child: FilledButton.tonalIcon(
              onPressed: _busy || _loading ? null : _make,
              icon: _busy
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.auto_awesome),
              label: Text(_busy
                  ? 'AI 正在汇总${_spans[_period]}的复盘…'
                  : _md.isEmpty
                      ? '生成$name'
                      : '重新生成$name'),
            ),
          ),
          if (_error.isNotEmpty)
            Padding(
                padding: const EdgeInsets.all(16),
                child: Text(_error, style: TextStyle(color: theme.colorScheme.error))),
          if (_md.isNotEmpty)
            SummaryCard(_md, title: '$_key $name')
          else if (_error.isEmpty && !_loading)
            Padding(
              padding: const EdgeInsets.all(32),
              child: Text(_emptyHints[_period]!,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: theme.colorScheme.outline, height: 1.7)),
            ),
        ],
      ),
    );
  }
}
