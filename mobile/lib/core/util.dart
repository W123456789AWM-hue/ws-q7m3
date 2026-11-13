String pad2(int v) => v.toString().padLeft(2, '0');

String fmtDate(DateTime t) => '${t.year}-${pad2(t.month)}-${pad2(t.day)}';

String fmtClock(DateTime t) => '${pad2(t.hour)}:${pad2(t.minute)}:${pad2(t.second)}';

String fmtCompact(DateTime t) =>
    '${t.year}${pad2(t.month)}${pad2(t.day)}_${pad2(t.hour)}${pad2(t.minute)}${pad2(t.second)}';

String fmtDuration(Duration d) {
  final h = d.inHours;
  final m = d.inMinutes % 60;
  final s = d.inSeconds % 60;
  return h > 0 ? '$h:${pad2(m)}:${pad2(s)}' : '${pad2(m)}:${pad2(s)}';
}

String truncate(String s, int n) => s.length <= n ? s : '${s.substring(0, n)}…';
