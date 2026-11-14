/// 手机独立复盘：不连电脑，手机自己把录音交给 AI 听，结果存在手机上。
///
/// 数据流：录音切成的小片（暂存目录，和传给电脑时是同一批文件）→ 连续有声音的片拼成“段落”→
/// 每隔 N 分钟（按录音时间算）把还没复盘的段落发给 AI → 听写 + 复盘存进这一场的 json → 录音片段删除。
/// 停止录音后把剩下的复盘完，再做一次整场总复盘。
/// 数据格式和电脑端的 session.json 对齐（reviews / paragraphs / summary），界面两种模式共用。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'adpcm.dart';
import 'ai.dart';
import 'audio.dart';
import 'prompts.dart' as prompts;
import 'settings.dart';
import 'uploader.dart' show SpoolItem;
import 'util.dart';

const int _bytesPerSec = kSampleRate * 2;
const int maxParagraphSec = 120; // 一个段落最长多少秒（再长就另起一段）
const int maxReviewSec = 8 * 60; // 一次最多发给 AI 多少秒录音
const int minReviewSec = 15; // 新录音少于这么多秒，这一轮先不复盘

typedef Json = Map<String, dynamic>;

class LocalEngine {
  LocalEngine(this.root, this.spoolDir, this.settings, {AiClient? ai, this.onChanged})
      : ai = ai ?? AiClient(settings);

  final Directory root; // <数据目录>/local
  final Directory spoolDir;
  final AppSettings settings;
  final AiClient ai;
  final void Function()? onChanged;

  bool _busy = false;
  bool _again = false;
  String working = ''; // 正在做什么（给界面显示）
  final Map<String, Json> _cache = {};

  Directory get _sessions => Directory('${root.path}/sessions');
  Directory get _reports => Directory('${root.path}/reports');
  File _sessionFile(String id) => File('${_sessions.path}/$id.json');
  File _clip(String sid, int pid) => File('${root.path}/clips/$sid/$pid.pcm');

  // ======================= 读写一场录音 =======================
  Json? _load(String id) {
    final c = _cache[id];
    if (c != null) return c;
    final f = _sessionFile(id);
    if (!f.existsSync()) return null;
    try {
      return _cache[id] = Map<String, dynamic>.from(jsonDecode(f.readAsStringSync()) as Map);
    } catch (_) {
      return null;
    }
  }

  void _save(Json s) {
    _sessions.createSync(recursive: true);
    final f = _sessionFile('${s['id']}');
    File('${f.path}.tmp')
      ..writeAsStringSync(jsonEncode(s))
      ..renameSync(f.path);
    _cache['${s['id']}'] = s;
    onChanged?.call();
  }

  Json _open(String id, DateTime start) =>
      _load(id) ??
      <String, dynamic>{
        'id': id,
        'started': start.toIso8601String(),
        'date': fmtDate(start),
        'title': '',
        'status': 'recording',
        'summary': '',
        'reviews': <dynamic>[],
        'paragraphs': <dynamic>[],
        'last_review_ms': start.millisecondsSinceEpoch,
      };

  static List<Json> _maps(Object? v) => [for (final e in (v as List? ?? const [])) e as Json];

  List<Json> _pending(Json s) =>
      [for (final p in _maps(s['paragraphs'])) if (p['status'] == 'pending') p];

  static num _sec(Iterable<Json> ps) => ps.fold<num>(0, (a, p) => a + (p['sec'] as num? ?? 0));

  // ======================= 给界面的数据 =======================
  /// 所有场次（新的在前）
  List<Json> sessions() {
    if (!_sessions.existsSync()) return [];
    final out = <Json>[];
    for (final f in _sessions.listSync().whereType<File>()) {
      if (!f.path.endsWith('.json')) continue;
      final s = _load(f.uri.pathSegments.last.replaceAll('.json', ''));
      if (s == null) continue;
      out.add({
        'id': s['id'],
        'title': s['title'],
        'started': s['started'],
        'count': _maps(s['reviews']).where((r) => r['status'] == 'done').length,
      });
    }
    out.sort((a, b) => '${b['id']}'.compareTo('${a['id']}'));
    return out;
  }

  /// 一场录音，格式和电脑端一致；还没听写的段落显示成“等待 AI 听写”
  Json? session(String id) {
    final s = _load(id);
    if (s == null) return null;
    return {
      ...s,
      'paragraphs': [
        for (final p in _maps(s['paragraphs']))
          {
            ...p,
            if (p['status'] == 'pending') 'text': '（${(p['sec'] as num).round()} 秒录音，等待 AI 听写）',
            if (p['status'] == 'pending') 'status': 'live',
          }
      ],
    };
  }

  /// 首页用：最近一场 + 下次复盘还有多久
  Json view({required bool recording, String? stream}) {
    final list = sessions();
    final id = stream ?? (list.isEmpty ? null : '${list.first['id']}');
    final s = id == null ? null : _load(id);
    Json? next;
    if (recording && s != null) {
      final since = DateTime.now().millisecondsSinceEpoch - (s['last_review_ms'] as num).toInt();
      next = {
        'mode': 'interval',
        'seconds_left': (settings.reviewEveryMin * 60 - since ~/ 1000).clamp(0, 1 << 30),
        'new_chars': _sec(_pending(s)).round(),
        'unit': '秒录音',
      };
    }
    return {
      'recording': recording,
      'session': id == null ? null : session(id),
      'next_review': next,
      'backlog': 0,
    };
  }

  // ======================= 处理暂存的录音片 =======================
  List<SpoolItem> _items() {
    if (!spoolDir.existsSync()) return [];
    final items = <SpoolItem>[];
    for (final f in spoolDir.listSync().whereType<File>()) {
      final it = SpoolItem.parse(f);
      if (it != null) items.add(it);
    }
    items.sort((a, b) {
      final c = a.stream.compareTo(b.stream);
      return c != 0 ? c : a.seq.compareTo(b.seq);
    });
    return items;
  }

  /// 有新片或定时器触发时调用
  Future<void> kick() async {
    if (_busy) {
      _again = true;
      return;
    }
    _busy = true;
    try {
      do {
        _again = false;
        for (final it in _items()) {
          await _take(it);
        }
      } while (_again);
    } finally {
      _busy = false;
      working = '';
      onChanged?.call();
    }
  }

  DateTime _streamStart(String stream) => DateTime(
      int.parse(stream.substring(0, 4)), int.parse(stream.substring(4, 6)), int.parse(stream.substring(6, 8)),
      int.parse(stream.substring(9, 11)), int.parse(stream.substring(11, 13)), int.parse(stream.substring(13, 15)));

  Future<void> _take(SpoolItem it) async {
    final s = _open(it.stream, _streamStart(it.stream));
    final ps = s['paragraphs'] as List;
    final endMs = it.start.millisecondsSinceEpoch + it.durMs;
    if (it.hasAudio) {
      var pcm = it.file.readAsBytesSync();
      if (it.kind == 'a') pcm = adpcmDecode(pcm);
      final last = ps.isEmpty ? null : ps.last as Json;
      final Json p;
      if (last != null &&
          last['status'] == 'pending' &&
          last['open'] == true &&
          (it.start.millisecondsSinceEpoch - (last['end_ms'] as num)).abs() < 1500 &&
          (last['sec'] as num) < maxParagraphSec) {
        p = last;
      } else {
        last?.remove('open');
        p = <String, dynamic>{
          'id': (s['next_pid'] as num? ?? 1).toInt(),
          'start_ms': it.start.millisecondsSinceEpoch,
          'start_clock': fmtClock(it.start),
          'sec': 0,
          'text': '',
          'status': 'pending',
          'open': true,
        };
        s['next_pid'] = (p['id'] as int) + 1;
        ps.add(p);
      }
      final f = _clip('${s['id']}', p['id'] as int);
      f.parent.createSync(recursive: true);
      f.writeAsBytesSync(pcm, mode: FileMode.append);
      p['sec'] = (p['sec'] as num) + pcm.length / _bytesPerSec;
      p['end_ms'] = endMs;
    } else if (ps.isNotEmpty) {
      (ps.last as Json).remove('open'); // 静音或停止：这一段说完了
    }
    _save(s);
    it.file.deleteSync();

    if (it.kind == 'x') {
      await _finish(s);
    } else if (endMs - (s['last_review_ms'] as num) >= settings.reviewEveryMin * 60000) {
      s['last_review_ms'] = endMs; // 不管成不成，下一轮都等满一个间隔（接口坏了也不会连着重试）
      if (_sec(_pending(s)) >= minReviewSec) {
        await _review(s, 'periodic');
      } else {
        _save(s);
      }
    }
  }

  // ======================= 复盘 =======================
  /// 把还没复盘的段落（最多 [maxReviewSec] 秒）发给 AI。返回是否成功
  Future<bool> _review(Json s, String kind) async {
    final batch = <Json>[];
    num total = 0;
    for (final p in _pending(s)) {
      if (batch.isNotEmpty && total + (p['sec'] as num) > maxReviewSec) break;
      batch.add(p);
      total += p['sec'] as num;
    }
    if (batch.isEmpty) return true;
    final reviews = s['reviews'] as List;
    final from = '${batch.first['start_clock']}';
    final to = fmtClock(DateTime.fromMillisecondsSinceEpoch((batch.last['end_ms'] as num).toInt()));
    final r = <String, dynamic>{
      'id': (s['next_rid'] as num? ?? 1).toInt(),
      'kind': kind,
      'status': 'analyzing',
      'date': s['date'],
      'from_clock': from.substring(0, 5),
      'to_clock': to.substring(0, 5),
      'sec': total.round(),
      'chars': 0,
      'text': '',
      'pids': [for (final p in batch) p['id']],
    };
    s['next_rid'] = (r['id'] as int) + 1;
    reviews.add(r);
    working = 'AI 正在听 ${total.round()} 秒录音';
    _save(s);
    try {
      final parts = <AudioPart>[];
      for (final p in batch) {
        final f = _clip('${s['id']}', p['id'] as int);
        if (!f.existsSync()) continue;
        final pcm = f.readAsBytesSync();
        if (pcm.length < _bytesPerSec ~/ 10) continue;
        parts.add(AudioPart('【段落 #${p['id']} · ${p['start_clock']} · ${(p['sec'] as num).round()}秒】', pcm));
      }
      if (parts.isEmpty) throw AiException('这段时间的录音片段找不到了');
      final done = [for (final x in _maps(reviews)) if (x['status'] == 'done') x];
      final prev = done.length > 2 ? done.sublist(done.length - 2) : done;
      final header = prompts.audioHeader('${s['date']} $from–$to', prev, settings.aboutMe,
          settings.extraInstructions, settings.glossary);
      final out = await ai.listen(prompts.audioReviewSystem, header, parts);
      final data = prompts.parseJson(out) ?? <String, dynamic>{'title': '复盘', 'summary': out};
      final texts = <int, String>{};
      for (final t in (data.remove('transcripts') as List? ?? const [])) {
        if (t is! Map) continue;
        final id = int.tryParse('${t['id']}');
        final txt = '${t['text'] ?? ''}'.trim();
        if (id != null && txt.isNotEmpty) texts[id] = (texts[id] ?? '') + txt;
      }
      for (final p in batch) {
        p['text'] = texts[p['id']] ?? '（这一段 AI 没有给出听写）';
        p['status'] = 'done';
        p.remove('open');
        final f = _clip('${s['id']}', p['id'] as int);
        if (f.existsSync()) f.deleteSync();
      }
      r['text'] = [for (final p in batch) if (texts[p['id']] != null) '[${p['start_clock']}] ${texts[p['id']]}'].join('\n\n');
      r['chars'] = texts.values.fold<int>(0, (a, t) => a + t.length);
      r['analysis'] = data;
      r['status'] = 'done';
      reviews.removeWhere((x) => (x as Json)['status'] == 'error'); // 之前失败的那些段落这次一起做掉了
      if ('${s['title']}'.isEmpty && data['trivial'] != true) s['title'] = '${data['title'] ?? ''}';
      _save(s);
      return true;
    } catch (e) {
      r['status'] = 'error';
      r['error'] = '$e';
      _save(s);
      return false;
    }
  }

  /// 录音停了：把剩下的复盘完，再做整场总复盘
  Future<void> _finish(Json s) async {
    var ok = true;
    while (ok && _sec(_pending(s)) >= 3) {
      ok = await _review(s, 'final_part');
    }
    s['status'] = 'done';
    final real = prompts.reviewDigest(_maps(s['reviews']));
    if (ok && real.length >= 2 && '${s['summary']}'.isEmpty) {
      working = '正在生成整场总复盘';
      s['status'] = 'finishing';
      _save(s);
      try {
        s['summary'] = await ai.chat(prompts.finalSystem, prompts.digestUser(_maps(s['reviews']), settings.aboutMe));
      } catch (e) {
        s['summary_error'] = '$e';
      }
      s['status'] = 'done';
    }
    _save(s);
  }

  /// 「立即复盘」：不等间隔，现在就把还没复盘的发给 AI
  Future<void> reviewNow(String id) async {
    final s = _load(id);
    if (s == null) return;
    if (_sec(_pending(s)) < 3) throw AiException('还没有新的录音可以复盘');
    await _exclusive(() async {
      s['last_review_ms'] = DateTime.now().millisecondsSinceEpoch;
      await _review(s, 'manual');
    });
  }

  /// 失败的那次重试：去掉失败记录，把那些段落重新发一次
  Future<void> retry(String id, int rid) async {
    final s = _load(id);
    if (s == null) return;
    await _exclusive(() async {
      (s['reviews'] as List).removeWhere((r) => (r as Json)['id'] == rid && r['status'] == 'error');
      if (s['status'] == 'done') {
        await _finish(s);
      } else {
        await _review(s, 'manual');
      }
    });
  }

  Future<void> _exclusive(Future<void> Function() fn) async {
    if (_busy) throw AiException('AI 正在忙，等这一轮做完再点');
    _busy = true;
    try {
      await fn();
    } finally {
      _busy = false;
      working = '';
      onChanged?.call();
    }
    if (_again) unawaited(kick());
  }

  // ======================= 日 / 月 / 年复盘 =======================
  File _reportFile(String period, String key) => File('${_reports.path}/$period-$key.md');

  String report(String period, String key) {
    final f = _reportFile(period, key);
    return f.existsSync() ? f.readAsStringSync() : '';
  }

  List<Json> _reviewsOn(String date) => [
        for (final it in sessions())
          if ('${_load('${it['id']}')?['date']}' == date) ..._maps(_load('${it['id']}')!['reviews'])
      ];

  Future<String> makeReport(String period, String key) async {
    final String md;
    if (period == 'day') {
      final reviews = _reviewsOn(key);
      if (prompts.reviewDigest(reviews).isEmpty) throw AiException('这一天没有可以复盘的内容');
      md = await ai.chat(prompts.dailySystem, prompts.digestUser(reviews, settings.aboutMe));
    } else if (period == 'month') {
      final parts = <String>[];
      for (var d = 1; d <= 31; d++) {
        final date = '$key-${pad2(d)}';
        final day = report('day', date);
        final body = day.isNotEmpty ? day : prompts.briefDigest(_reviewsOn(date));
        if (body.isNotEmpty) parts.add('### $date\n$body');
      }
      if (parts.isEmpty) throw AiException('这个月没有可以复盘的内容');
      md = await ai.chat(prompts.monthlySystem, prompts.periodUser(settings.aboutMe, '$key 每天的复盘', parts));
    } else {
      final parts = <String>[
        for (var m = 1; m <= 12; m++)
          if (report('month', '$key-${pad2(m)}').isNotEmpty) '### $key-${pad2(m)}\n${report('month', '$key-${pad2(m)}')}'
      ];
      if (parts.isEmpty) throw AiException('这一年还没有月复盘，请先生成月复盘');
      md = await ai.chat(prompts.yearlySystem, prompts.periodUser(settings.aboutMe, '$key 年每个月的复盘', parts));
    }
    _reports.createSync(recursive: true);
    _reportFile(period, key).writeAsStringSync(md);
    return md;
  }

  /// 还没复盘的录音占了多少字节（给界面显示）
  int pendingBytes() {
    final d = Directory('${root.path}/clips');
    if (!d.existsSync()) return 0;
    return d.listSync(recursive: true).whereType<File>().fold<int>(0, (a, f) => a + f.lengthSync());
  }

  // 测试用
  Uint8List clipBytes(String sid, int pid) => _clip(sid, pid).readAsBytesSync();
}
