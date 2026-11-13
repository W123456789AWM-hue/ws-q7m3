// 手机端核心逻辑联调（不需要手机）：把一段录音按手机的方式切片、暂存、上传给电脑端服务，
// 再通过接口读回转写和复盘。用法：
//   dart tool/core_check.dart <16k单声道wav> <电脑地址> <口令>
import 'dart:io';
import 'dart:typed_data';

import '../lib/core/api.dart';
import '../lib/core/endpoints.dart';
import '../lib/core/settings.dart';
import '../lib/core/uploader.dart';

var failures = 0;
void check(bool ok, String what) {
  stdout.writeln('${ok ? "  ok  " : " FAIL "} $what');
  if (!ok) failures++;
}

Future<void> drain(Uploader u) async {
  for (var i = 0; i < 200 && u.pending().isNotEmpty; i++) {
    await u.kick(force: true);
    if (u.state == 'error') break;
  }
}

Future<void> main(List<String> args) async {
  final wav = File(args[0]).readAsBytesSync();
  final pcm = Uint8List.sublistView(wav, 44);
  final server = args[1], token = args[2];
  final tmp = Directory.systemTemp.createTempSync('aimind_phone');
  final spoolDir = Directory('${tmp.path}/spool');

  final st = AppSettings()
    ..serverUrl = 'http://127.0.0.1:1' // 先故意填一个连不上的地址
    ..token = 'wrong'
    ..deviceName = '联调手机'
    ..skipSilence = true
    ..chunkSec = 10;
  var clock = DateTime(2026, 11, 12, 14, 0, 0);
  final spool = ChunkSpool(spoolDir, st, now: () => clock);

  stdout.writeln('== 录音切片（电脑连不上，先存手机）');
  spool.start();
  const step = 3201; // 奇数字节的块
  for (var i = 0; i < pcm.length; i += step) {
    final end = i + step > pcm.length ? pcm.length : i + step;
    clock = DateTime(2026, 11, 12, 14, 0, 0).add(Duration(milliseconds: (end / 32).round()));
    spool.add(Uint8List.sublistView(pcm, i, end));
  }
  spool.stop();
  var up = Uploader(spoolDir, st);
  final items = up.pending();
  stdout.writeln('     有声 ${spool.voicedChunks} 片，静音 ${spool.silentChunks} 片，共 ${items.length} 个文件（含停止标记）');
  check(spool.voicedChunks > 0 && spool.silentChunks > 0, '静音片被识别出来，不占空间');
  check(items.last.kind == 'x', '最后是停止标记');
  final bytes = items.where((i) => i.kind == 'v').fold<int>(0, (n, i) => n + i.file.lengthSync());
  check(bytes < pcm.length * 0.8, '暂存大小 ${bytes ~/ 1024}KB < 原始 ${pcm.length ~/ 1024}KB');

  await up.kick(force: true);
  check(up.state == 'error' && up.pending().length == items.length, '电脑连不上：保留在手机上（${up.lastError}）');

  stdout.writeln('== 口令不对');
  st.serverUrl = server;
  await up.kick(force: true);
  check(up.state == 'error' && up.lastError.contains('口令'), '提示口令不对，录音仍保留');
  final api = ServerApi(st, Endpoints(st));
  try {
    await api.view();
    check(false, '错口令应被拒绝');
  } on ApiException catch (e) {
    check(e.status == 401, '接口拒绝错误口令（${e.message}）');
  }

  stdout.writeln('== App 被杀后重新打开：接着传');
  st.token = token;
  up = Uploader(spoolDir, st); // 新的实例，相当于重启 App
  await drain(up);
  check(up.pending().isEmpty && up.state == 'idle', '全部传完，手机暂存已清空');

  stdout.writeln('== 电脑端处理结果（手机查看）');
  Map<String, dynamic> v = {};
  for (var i = 0; i < 120; i++) {
    v = await api.view();
    final s = v['session'] as Map?;
    if ((v['backlog'] as int) == 0 && s != null && s['status'] == 'done') break;
    await Future<void>.delayed(const Duration(seconds: 1));
  }
  final s = Map<String, dynamic>.from(v['session'] as Map);
  final reviews = (s['reviews'] as List);
  final paras = (s['paragraphs'] as List);
  stdout.writeln('     会话 ${s['id']}：${paras.length} 段，${reviews.length} 次复盘');
  for (final p in paras) {
    stdout.writeln('     ${(p as Map)['start_clock']} ${p['text']}');
  }
  check('${s['id']}'.startsWith('20261112_14'), '会话时间用的是手机录音的时间');
  check(paras.length == 6, '按停顿分成 6 段（实际 ${paras.length}）');
  check((paras.first as Map)['start_clock'].toString().startsWith('14:00:0'), '转写时间和录音时间对得上');
  check(reviews.isNotEmpty && reviews.every((r) => (r as Map)['status'] == 'done'), '复盘全部完成');
  check(reviews.every((r) => !(r as Map).containsKey('text')), '给手机的数据不带大段原文');
  check('${s['summary']}'.isNotEmpty, '有整场总复盘');
  check(v['source'] == 'phone', '来源标记为手机');

  stdout.writeln('== 历史 / 日复盘 / 设置');
  final list = await api.sessions();
  check(list.any((e) => e['id'] == s['id']), '历史列表里有这一场');
  final full = await api.session('${s['id']}');
  check((full['reviews'] as List).isNotEmpty && ((full['reviews'] as List).first as Map)['text'] != null, '历史详情带原文');
  final md = await api.makeDaily('2026-11-12');
  check(md.contains('日复盘') && (await api.daily('2026-11-12')) == md, '日复盘生成并可读回');
  final cfg = await api.getConfig();
  await api.setConfig({'review_interval_min': 45, 'glossary': 'Flutter, NAS'});
  final cfg2 = await api.getConfig();
  check(cfg2['review_interval_min'] == 45 && cfg2['glossary'] == 'Flutter, NAS', '手机可以改电脑上的设置');
  check(cfg2['server_token'] == cfg['server_token'] && cfg2['llm_model'] == cfg['llm_model'], '其他设置不受影响');
  check((await api.test('llm')).startsWith('✅'), '远程测试 AI 接口');
  try {
    await api.reviewNow();
    check(false, '没在录音时立即复盘应报错');
  } on ApiException catch (e) {
    check(e.message.contains('录音'), '错误信息能传回手机（${e.message}）');
  }

  stdout.writeln('== 外出场景：主地址连不上 → 自动换备用地址；移动网络 → 压缩上传');
  st.serverUrl = 'http://127.0.0.1:1'; // 家里的地址，在外面连不上
  st.serverUrl2 = server; // 备用地址（Tailscale）
  final ep = Endpoints(st);
  final t16 = DateTime(2026, 11, 12, 16, 0, 0);
  clock = t16;
  final spool2 = ChunkSpool(spoolDir, st, now: () => clock)..compress = true;
  spool2.start();
  for (var i = 0; i < pcm.length; i += step) {
    final end = i + step > pcm.length ? pcm.length : i + step;
    clock = t16.add(Duration(milliseconds: (end / 32).round()));
    spool2.add(Uint8List.sublistView(pcm, i, end));
  }
  spool2.stop();
  final up2 = Uploader(spoolDir, st, endpoints: ep);
  final items2 = up2.pending();
  final bytes2 = items2.where((i) => i.hasAudio).fold<int>(0, (n, i) => n + i.file.lengthSync());
  check(items2.any((i) => i.kind == 'a') && !items2.any((i) => i.kind == 'v'), '有声音的片都是压缩格式');
  check(bytes2 < bytes * 0.27, '压缩后 ${bytes2 ~/ 1024}KB，约为未压缩 ${bytes ~/ 1024}KB 的 ${(bytes2 * 100 / bytes).round()}%');
  await drain(up2);
  check(up2.pending().isEmpty, '通过备用地址全部传完');
  check(ep.usingBackup && ep.active == server, '自动切到了备用地址');
  final api2 = ServerApi(st, ep);
  Map<String, dynamic> v2 = {};
  for (var i = 0; i < 120; i++) {
    v2 = await api2.view();
    final s2 = v2['session'] as Map?;
    if ((v2['backlog'] as int) == 0 && s2 != null && s2['status'] == 'done' && '${s2['id']}'.startsWith('20261112_16')) break;
    await Future<void>.delayed(const Duration(seconds: 1));
  }
  final s2 = Map<String, dynamic>.from(v2['session'] as Map);
  final paras2 = s2['paragraphs'] as List;
  for (final p in paras2) {
    stdout.writeln('     ${(p as Map)['start_clock']} ${p['text']}');
  }
  check('${s2['id']}'.startsWith('20261112_16') && paras2.length == 6, '压缩上传的录音同样识别出 6 段');
  check(paras2.every((p) => '${(p as Map)['text']}'.contains('点至下午5点')), '压缩后 AI 听写内容正常');
  check(paras2.every((p) => '${(p as Map)['text']}'.trim().isNotEmpty && !'${p['text']}'.startsWith('🎙')),
      '压缩后上传的录音，每段都有 AI 听写文字');

  check(st.deviceId.isNotEmpty && paras2.every((p) => (p as Map)['device_name'] == '联调手机'),
      '电脑上显示这台设备的名字（多设备区分）');

  tmp.deleteSync(recursive: true);
  stdout.writeln(failures == 0 ? '\n全部通过' : '\n有 $failures 项失败');
  exit(failures == 0 ? 0 : 1);
}
