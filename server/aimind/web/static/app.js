let S = null;            // 当前显示的会话
let recording = false;
let viewingHistory = false;
let nextReview = null;
let MIC_ON = false;
let DEVS = [];          // 正在录音的设备 [{id,name,stopped,idle_sec}]
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function toast(msg, ms = 3500) {
  const t = $('toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms);
}

async function api(url, opts = {}) {
  const r = await fetch(url, {method: 'POST', ...opts});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.detail || ('出错 ' + r.status)); throw new Error(j.detail); }
  return j;
}

let _lvRaf = 0, _lvVal = 0;
function setLevel(db) {
  _lvVal = Math.max(0, Math.min(1, (db + 60) / 60));
  if (!_lvRaf) _lvRaf = requestAnimationFrame(() => { _lvRaf = 0; $('lv').style.transform = `scaleX(${_lvVal})`; });
}

// ---------------- WebSocket ----------------
function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onmessage = e => handle(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}
function handle(m) {
  switch (m.type) {
    case 'level': setLevel(m.db); return;
    case 'error': return toast('⚠ ' + m.msg, 8000);
    case 'status': return toast(m.msg);
    case 'model': $('modelMsg').textContent = m.msg; $('modelMsg').title = m.msg; if (m.done) toast(m.msg); return;
    case 'nas': $('nasInfo').textContent = m.msg; return;
    case 'eval': if ($('evalMsg')) $('evalMsg').textContent = m.msg; if (m.done) { toast(m.msg); if ($('evalDrawer').classList.contains('open')) evalShowSet(); } return;
    case 'daily': return;
    case 'report':
      if ($('dailyDrawer').classList.contains('open') && m.period === RP.period && m.key === periodKey()) showDaily(m.md);
      toast(`${m.key} ${PNAME[m.period]}已生成`); loadUsage(); return;
    case 'next_review': nextReview = m.data; renderNext(); return;
    case 'state':
      recording = m.recording; nextReview = m.next_review; MIC_ON = !!m.mic_on; DEVS = m.devices || [];
      if (!viewingHistory) { S = m.session; renderAll(); }
      renderHeader(); renderNext(); return;
  }
  if (viewingHistory || !S) return;
  if (m.type === 'caption') {
    let p = S.paragraphs.find(x => x.id === m.pid);
    if (!p) { p = {id: m.pid, start_clock: m.clock, text: '', segments: [], status: 'live', device_name: m.device_name}; S.paragraphs.push(p); }
    p.text += m.text;
    p.device_name = p.device_name || m.device_name;
    p.segments.push({clock: m.clock, text: m.text, pid: m.pid, sec: m.sec});
    addCaption(m.clock, m.text || voiceLabel(m.sec), m.pid, m.device_name, !m.text);
  }
  if (m.type === 'review') {
    S.reviews = S.reviews || [];
    const i = S.reviews.findIndex(x => x.id === m.data.id);
    if (i >= 0) S.reviews[i] = m.data; else S.reviews.push(m.data);
    upsertReview(m.data);
    if (m.data.status !== 'analyzing') loadUsage();
  }
}

// ---------------- 渲染 ----------------
function renderHeader() {
  const st = S?.status;
  const pill = $('pill');
  const live = DEVS.filter(d => !d.stopped).map(d => d.name);
  let cls = 'pill', txt = '待机';
  if (recording) { cls = 'pill on'; txt = 'REC' + (live.length ? ' · ' + live.join('、') : ''); }
  else if (st === 'finishing') { cls = 'pill busy'; txt = '收尾复盘中'; }
  pill.className = cls; pill.lastElementChild.textContent = txt; pill.title = txt;
  const b = $('btnRec');
  b.className = MIC_ON ? 'rec' : 'primary';
  b.innerHTML = MIC_ON ? '<svg><use href="#i-stop"/></svg><span>停止电脑麦克风</span>'
                       : '<svg><use href="#i-mic"/></svg><span>电脑麦克风录音</span>';
  $('btnReview').disabled = !recording;
  $('btnFinish').disabled = !recording;
  if (!MIC_ON) setLevel(-60);
}

function renderNext() {
  const n = nextReview;
  if (!n || viewingHistory) { $('nextInfo').textContent = ''; return; }
  if (n.mode === 'realtime') {
    $('nextInfo').textContent = `实时复盘 · 已积累 ${n.new_chars}/${n.min_chars} ${n.unit || '字'}，停顿后触发`;
    return;
  }
  const m = Math.floor(n.seconds_left / 60), s = n.seconds_left % 60;
  const u = n.unit || '字';
  const need = n.new_chars < n.min_chars ? ` · 新内容 ${n.new_chars}/${n.min_chars} ${u}（不够会跳过）` : ` · 已积累 ${n.new_chars} ${u}`;
  $('nextInfo').textContent = `下次复盘 ${m}:${String(s).padStart(2, '0')}${need}`;
}

function voiceLabel(sec) { return sec ? `◉ ${Number(sec).toFixed(1)}s 语音` : ''; }
function fmtSec(sec) { sec = Math.round(sec || 0); return sec >= 60 ? `${Math.floor(sec / 60)} 分 ${sec % 60} 秒` : `${sec} 秒`; }

let lastCapPid = null;
function multiDevice() { return (S?.devices || []).length > 1 || new Set((S?.paragraphs || []).map(p => p.device_name)).size > 1; }
function capHtml(clock, text, pid, dev, voice, multi) {
  let sep = '';
  if (lastCapPid !== null && pid !== lastCapPid) sep = '<div class="cap sep"></div>';
  lastCapPid = pid;
  const tag = dev && multi ? `<span class="dev">${esc(dev)}</span>` : '';
  return `${sep}<div class="cap${voice ? ' voice' : ''}"><time>${esc(clock)}</time>${tag}${esc(text)}</div>`;
}
function addCaption(clock, text, pid, dev, voice) {   // 录音中新来的一句：只追加这一句
  const col = $('captions');
  const stick = col.scrollHeight - col.scrollTop - col.clientHeight < 200;
  $('capList').insertAdjacentHTML('beforeend', capHtml(clock, text, pid, dev, voice, multiDevice()));
  if (stick) col.scrollTop = col.scrollHeight;
}

function renderAll() {
  lastCapPid = null;
  // 几台设备的段落按录音时间交错排；整个列表拼成一个字符串，一次放进页面
  const paras = S ? [...S.paragraphs].sort((a, b) => (a.start_t ?? 0) - (b.start_t ?? 0) || a.id - b.id) : [];
  const multi = multiDevice(), out = [];
  for (const p of paras) {
    const segs = p.segments || [];
    const d = p.device_name;
    if (segs.some(s => s.text)) { for (const s of segs) out.push(capHtml(s.clock || p.start_clock, s.text, p.id, d, false, multi)); }
    else if (p.text) out.push(capHtml(p.start_clock, p.text, p.id, d, false, multi));   // AI 听写的文字（按段落）
    else for (const s of segs) out.push(capHtml(s.clock || p.start_clock, voiceLabel(s.sec) + ' · 等 AI 复盘时听写', p.id, d, true, multi));
  }
  $('capList').innerHTML = out.join('');
  $('captions').scrollTop = $('captions').scrollHeight;
  renderReviews();
  renderSummary();
  $('sessInfo').textContent = S ? `SESSION ${S.id}${S.title ? ' · ' + S.title : ''}${(S.devices || []).length ? ' · ' + S.devices.join(' / ') : ''}` : '';
  $('nasInfo').textContent = S?.nas_status || '';
  $('viewing').innerHTML = viewingHistory
    ? `<div class="viewing"><span style="flex:1">正在查看历史记录</span><button onclick="backToLive()">返回当前</button>
       <button onclick="api('/api/open_folder/${esc(S.id)}')">打开文件夹</button></div>` : '';
  renderNext();
}

function list(items, fmt = x => esc(x)) {
  return (items || []).map(x => `<li>${fmt(x)}</li>`).join('');
}
function sec(cls, title, items, fmt) {
  if (!items || !items.length) return '';
  return `<div class="sec ${cls}"><h4>${title}</h4><ul>${list(items, fmt)}</ul></div>`;
}

const KIND = {realtime: '实时复盘', periodic: '定时复盘', manual: '手动复盘', final_part: '收尾复盘'};
function reviewCard(r) {
  const a = r.analysis || {};
  const badge = {analyzing: 'AI 思考中', error: '复盘失败'}[r.status] || '';
  let body = '';
  if (r.status === 'analyzing') body = r.sec != null ? `<p class="dots">AI 正在听 ${fmtSec(r.sec)} 的录音</p>` : `<p class="dots">AI 正在思考 ${r.chars} 字的内容</p>`;
  else if (r.status === 'error') body = `<p style="color:var(--rec)">${esc(r.error)}</p><button onclick="api('/api/retry_review/${r.id}')">重试</button>`;
  else if (a.trivial) body = `<p class="live-text">这段时间以闲聊或噪音为主。${esc(a.summary || '')}</p>`;
  else body = `
    <p class="sum">${esc(a.summary)}</p>
    <div class="secs">
    ${sec('blind', '你可能没注意到', a.blind_spots)}
    ${sec('need', '潜在需求', a.latent_needs, x => typeof x === 'object'
        ? `${esc(x.need)}<div class="ev">依据：${esc(x.evidence)}</div>` : esc(x))}
    ${sec('div', '发散联想', a.divergent, x => typeof x === 'object'
        ? `<span class="tag">${esc(x.angle)}</span>${esc(x.idea)}` : esc(x))}
    ${sec('sug', '建议', a.suggestions, x => typeof x === 'object'
        ? `<span class="tag pri-${esc(x.priority)}">${esc(x.priority)}</span>${esc(x.text)}` : esc(x))}
    ${sec('voice', '从语气里听出来的', a.voice_cues)}
    ${sec('q', '值得追问自己', a.questions)}
    ${sec('chg', '和上次复盘相比', a.changes)}
    </div>
    ${a.topics?.length ? `<details><summary>话题时间线</summary><ul>${list(a.topics, x => typeof x === 'object'
        ? `${esc(x.time)} ${esc(x.topic)}：${esc(x.gist)}` : esc(x))}</ul></details>` : ''}`;
  const raw = r.text ? `<details><summary>${r.sec != null ? 'AI 听写的原文' : '这次复盘用到的原文'}（${r.chars} 字）</summary><div style="white-space:pre-wrap">${esc(r.text)}</div></details>` : '';
  return `<div class="card" data-rid="${r.id}"><div class="hd"><b>${esc(a.title || KIND[r.kind] || '复盘')}</b>
    <small>${esc(r.from_clock)}–${esc(r.to_clock)} · ${KIND[r.kind] || ''}</small>${badge ? `<span class="badge ${r.status === 'error' ? 'error' : 'analyzing'}">${badge}</span>` : ''}</div>
    ${body}${raw}</div>`;
}

function renderReviews() {
  const box = $('reviews');
  if (!S || !(S.reviews || []).length) {
    if (S && S.paragraphs.length) box.innerHTML = '<p class="empty">还没到复盘的时候。想马上看，点顶部「立即复盘」。</p>';
    return;
  }
  box.innerHTML = [...S.reviews].reverse().map(reviewCard).join('');
}
function upsertReview(r) {   // 只替换变了的那一张卡片（不重画全部，也不会让所有卡片重新播放动画）
  const box = $('reviews');
  const old = box.querySelector(`.card[data-rid="${r.id}"]`);
  if (!old) { if (!box.querySelector('.card')) box.innerHTML = ''; box.insertAdjacentHTML('afterbegin', reviewCard(r)); return; }
  const tmp = document.createElement('div'); tmp.innerHTML = reviewCard(r);
  const card = tmp.firstElementChild; card.style.animation = 'none';
  old.replaceWith(card);
}

function md(src) {   // 极简 Markdown
  const out = []; let inList = false;
  for (const raw of String(src || '').split('\n')) {
    const l = raw.trimEnd();
    const li = l.match(/^\s*[-*]\s+(\[[ x]\]\s+)?(.*)$/);
    if (li) { if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${li[1] ? '☐ ' : ''}${inline(li[2])}</li>`); continue; }
    if (inList) { out.push('</ul>'); inList = false; }
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    if (h) out.push(`<h3>${inline(h[2])}</h3>`);
    else if (l.trim()) out.push(`<p>${inline(l)}</p>`);
  }
  if (inList) out.push('</ul>');
  return out.join('');
}
function inline(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); }

function renderSummary() {
  $('summaryBox').innerHTML = S?.summary
    ? `<div class="card" id="summary"><div class="hd"><b>整场总复盘</b><small>SESSION REVIEW</small></div>${md(S.summary)}</div>` : '';
}

// ---------------- 操作 ----------------
async function toggleRec() {
  if (viewingHistory) await backToLive();
  if (MIC_ON) await api('/api/stop');
  else { if (!recording) $('reviews').innerHTML = ''; await api('/api/start'); }
}
async function finishNow() {
  if (!confirm('结束这一场？所有设备的内容会马上做整场总复盘。设备之后再传来的录音会开新的一场。')) return;
  await api('/api/finish');
}
async function reviewNow() { await api('/api/review_now'); toast('已交给 AI 复盘'); }

async function importWav(input) {
  const f = input.files[0]; input.value = '';
  if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  viewingHistory = false;
  await api('/api/import', {body: fd});
  toast('已开始处理音频文件');
}

async function analyzeText() {
  const text = $('testText').value;
  viewingHistory = false;
  await api('/api/analyze_text', {headers: {'content-type': 'application/json'}, body: JSON.stringify({text})});
  closeDrawers();
}

function openDrawer(id) { closeMore(); $('mask').style.display = 'block'; $(id).classList.add('open'); }
function toggleMore(e) { e.stopPropagation(); $('moreMenu').classList.toggle('open'); }
function closeMore() { $('moreMenu').classList.remove('open'); }
document.addEventListener('click', closeMore);
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeMore(); closeDrawers(); } });
function closeDrawers() { $('mask').style.display = 'none'; document.querySelectorAll('.drawer').forEach(d => d.classList.remove('open')); }

// ---------------- 识别测试 ----------------
let EV = {tab: 'label', sid: ''};
async function openEval() { openDrawer('evalDrawer'); EV.tab === 'label' ? evalShowLabel() : evalShowSet(); }
function evalTabs() {
  return `<div class="ev-tabs"><button class="${EV.tab === 'label' ? 'on' : ''}" onclick="evalShowLabel()">① 标注：挑句子，改成实际说的话</button>
    <button class="${EV.tab === 'set' ? 'on' : ''}" onclick="evalShowSet()">② 测试集与评测</button></div>`;
}
async function evalShowLabel(sid) {
  EV.tab = 'label';
  const sessions = await (await fetch('/api/sessions')).json();
  if (sid !== undefined) EV.sid = sid;
  if (!EV.sid && sessions.length) EV.sid = sessions[0].id;
  let rows = '<p class="empty">还没有录音。先用手机或电脑录一段平时真实的说话（5–10 分钟就够）。</p>';
  if (EV.sid) {
    const utts = await (await fetch('/api/eval/utts/' + EV.sid)).json();
    const usable = utts.filter(u => u.has_audio);
    rows = usable.length ? utts.map(u => !u.has_audio ? '' : `<div class="ev-row ${u.in_set ? 'inset' : ''}">
        <input type="checkbox" id="evc_${u.i}" ${u.in_set ? 'checked' : ''}>
        <small>${esc(u.clock)}<br>${u.sec}秒</small>
        <button title="播放这一句" onclick="evalPlay('/api/eval/audio?sid=${esc(EV.sid)}&i=${u.i}')">▶</button>
        <textarea id="evt_${u.i}" oninput="document.getElementById('evc_${u.i}').checked=true">${esc(u.in_set ? u.ref : u.text)}</textarea>
      </div>`).join('')
      : '<p class="empty">这一场录音是旧版本录的，没有保存每句话的位置，不能用来标注。<br>升级后新录的都可以（设置里要开着「保存完整录音」）。</p>';
  }
  $('evalBody').innerHTML = evalTabs() + `
    <p class="hint">做法：点 ▶ 听一句，把右边的文字改成<b>你实际说的话</b>（英文照写英文，标点无所谓）。听不清或不确定的句子不要勾。
    改过的会自动打勾；识别本来就全对的，手动打勾也加进去（否则测试集里全是难句，会低估准确率）。绿色底 = 已在测试集里。</p>
    <div class="row fg"><label style="margin:0">选一场录音：</label>
      <select style="width:auto;flex:1" onchange="evalShowLabel(this.value)">${sessions.map(s =>
        `<option value="${esc(s.id)}" ${s.id === EV.sid ? 'selected' : ''}>${esc(s.started.replace('T', ' '))} ${esc(s.title || '')}</option>`).join('')}</select>
      <button class="primary" onclick="evalAdd()">把打勾的句子存入测试集</button></div>
    <div>${rows}</div>`;
}
let evAudio = null;
function evalPlay(url) { if (evAudio) evAudio.pause(); evAudio = new Audio(url); evAudio.play(); }
async function evalAdd() {
  const picks = [];
  document.querySelectorAll('[id^=evc_]').forEach(c => {
    if (c.checked) { const i = Number(c.id.slice(4)); picks.push({i, ref: $('evt_' + i).value}); }
  });
  if (!picks.length) return toast('还没有打勾的句子');
  const r = await api('/api/eval/add', {headers: {'content-type': 'application/json'}, body: JSON.stringify({sid: EV.sid, picks})});
  toast(`已保存。测试集现在有 ${r.count} 句，共 ${Math.round(r.seconds)} 秒`);
  evalShowLabel();
}
function opsHtml(ops) {
  return ops.map(([op, r, h]) => op === '=' ? esc(h) : op === 'S' ? `<span class="op-S" title="应为：${esc(r)}">${esc(h)}</span>`
    : op === 'D' ? `<span class="op-D" title="漏了">${esc(r)}</span>` : `<span class="op-I" title="多出来的">${esc(h)}</span>`).join(' ');
}
async function evalShowSet() {
  EV.tab = 'set';
  const j = await (await fetch('/api/eval/set')).json();
  const res = j.results;
  let table = '<p class="hint">还没有评测结果。</p>';
  let detail = '';
  if (res) {
    const ok = res.engines.filter(e => !e.error);
    const best = Math.min(...ok.filter(e => e.key !== 'orig').map(e => e.rate));
    table = `<p class="hint">上次评测：${esc(res.time)}，${res.count} 句 / ${Math.round(res.seconds)} 秒。错误率 = 错、漏、多的字词数 ÷ 总字词数（一个汉字或一个英文单词算一个），越低越好。</p>
      <table class="ev"><tr><th>识别模型</th><th>错误率</th><th>错误 / 总数</th><th>全对的句子</th><th>速度</th></tr>
      ${res.engines.map(e => e.error ? `<tr><td>${esc(e.label)}</td><td colspan="4" style="color:var(--rec)">不可用：${esc(e.error)}</td></tr>`
        : `<tr><td>${esc(e.label)}</td><td class="num ${e.key !== 'orig' && e.rate === best ? 'best' : ''}">${e.rate}%</td>
           <td class="num">${e.errors} / ${e.words}</td><td class="num">${e.perfect} / ${res.count}</td>
           <td class="num">${e.speed ? '实时的 ' + e.speed + ' 倍' : '—'}</td></tr>`).join('')}</table>`;
    const byId = Object.fromEntries(j.items.map(x => [x.id, x]));
    detail = '<h3 style="font-size:14px;margin-top:18px">逐句对比（红色 = 和你标注的不一样；鼠标放上去看正确的字）</h3>' +
      (ok[0]?.rows || []).map((_, n) => {
        const id = ok[0].rows[n].id, it = byId[id];
        if (!it) return '';
        return `<div class="card" style="padding:10px 14px;margin-bottom:8px">
          <div><button onclick="evalPlay('/api/eval/item_audio/${id}')">▶</button> <b>${esc(it.ref)}</b>
            <button style="float:right;padding:2px 8px" title="从测试集删除" onclick="evalRemove(${id})">删除</button></div>
          ${ok.map(e => { const r = e.rows[n]; return `<div style="margin-top:4px"><span class="tag">${esc(e.label)}</span>${opsHtml(r.ops)} ${r.errors ? `<small style="color:var(--rec)">（${r.errors} 处）</small>` : '✓'}</div>`; }).join('')}
        </div>`;
      }).join('');
  } else if (j.count) {
    detail = j.items.map(it => `<div class="card" style="padding:10px 14px;margin-bottom:8px"><button onclick="evalPlay('/api/eval/item_audio/${it.id}')">▶</button> ${esc(it.ref)}
      <button style="float:right;padding:2px 8px" onclick="evalRemove(${it.id})">删除</button></div>`).join('');
  }
  $('evalBody').innerHTML = evalTabs() + `
    <p>测试集：<b>${j.count}</b> 句，共 <b>${Math.round(j.seconds)}</b> 秒。${j.count < 30 ? '建议至少 50 句（约 5 分钟），结果才稳定。' : ''}
      可评测的模型：${j.engines.map(e => ({sensevoice: 'SenseVoice', paraformer: 'Paraformer', whisper: 'Whisper（显卡）'}[e])).join('、')}${j.engines.includes('whisper') ? '' : '（Whisper 还没安装）'}</p>
    <div class="row"><button class="primary" onclick="evalRun()" ${j.count ? '' : 'disabled'}>开始评测</button>
      <button onclick="location.href='/api/eval/export'" ${j.count ? '' : 'disabled'}>导出测试集（zip，可发给 Claude）</button>
      <span class="hint" id="evalMsg"></span></div>
    ${table}${detail}`;
}
async function evalRun() { await api('/api/eval/run'); $('evalMsg').textContent = '开始评测…（没下载过的模型会先自动下载）'; }
async function evalRemove(id) { await api('/api/eval/remove/' + id); evalShowSet(); }

// ---------------- 设备连接 ----------------
function ago(t) {
  if (!t) return '从未';
  const s = Math.round(Date.now() / 1000 - t);
  return s < 60 ? '刚刚' : s < 3600 ? `${Math.floor(s / 60)} 分钟前` : s < 86400 ? `${Math.floor(s / 3600)} 小时前` : `${Math.floor(s / 86400)} 天前`;
}
const inputs = arr => arr.map(u => `<input readonly value="${esc(u)}" onclick="this.select()">`).join('');
async function openPhone() {
  const j = await (await fetch('/api/phone/info')).json();
  const phones = (j.phones || []).map(d => `<div class="hist dev-row">
      <span>${d.online ? '🟢' : '⚪'} <b>${esc(d.name)}</b><br><small>${esc(d.id)} · 最后在线 ${ago(d.last_seen)}${d.backlog ? ` · 待处理 ${d.backlog} 片` : ''}</small></span>
      <button onclick="renameDev('${esc(d.id)}','${esc(d.name)}')">改名</button>
      <button onclick="forgetDev('${esc(d.id)}')" title="从列表移除（不影响已有记录）">移除</button></div>`).join('');
  $('phoneBody').innerHTML = `
    <p>手机、平板、别的电脑都可以当录音设备，几台同时录也行：它们的内容会合在同一场里，一起交给 AI 复盘（同一房间里几台设备录到的同一段话，AI 会合并）。</p>
    <div class="fg"><h3>已连接过的设备</h3>
    ${phones || '<p class="hint">还没有设备连上来。</p>'}
    <p class="hint">每台设备在 App 设置里填一个不同的「设备名称」，这里就会分开显示。</p>
    <h3>在 App 的「设置」里填</h3>
    <label>电脑地址（任选一个能连通的）</label>
    ${j.urls.length ? inputs(j.urls) : '<p>没找到局域网地址，请检查电脑是否已联网</p>'}
    <label>备用地址（外出时用）</label>
    ${(j.away_urls || []).length ? inputs(j.away_urls)
      : '<p class="hint">还没有。想在外面也能把录音传回来：在这台电脑和手机上都安装 Tailscale（tailscale.com），用同一个账号登录，然后重新打开这个面板，这里会出现一个 100. 开头的地址。</p>'}
    <label>连接口令</label><input readonly value="${esc(j.token)}" onclick="this.select()">
    <label>在其他电脑（如 Mac）的浏览器里查看结果</label>
    ${inputs(j.view_urls || []) || '<p class="hint">暂无</p>'}
    <p class="hint">地址里带了口令，不要发给别人。<br>第一次启动时 Windows 防火墙会弹窗，要点「允许访问」，否则设备连不上。
    这台电脑要一直开着、本程序一直运行；电脑没开时，设备会先把录音存着，连上后自动补传。</p></div>`;
  openDrawer('phoneDrawer');
}
async function renameDev(id, old) {
  const name = prompt('新名字（比如：客厅手机、办公室 iPad）', old);
  if (!name) return;
  await api(`/api/phones/${encodeURIComponent(id)}/rename`, {headers: {'content-type': 'application/json'}, body: JSON.stringify({name})});
  openPhone();
}
async function forgetDev(id) { await api(`/api/phones/${encodeURIComponent(id)}/forget`); openPhone(); }

// ---------------- 复盘报告：日 / 月 / 年 ----------------
const PNAME = {day: '日复盘', month: '月复盘', year: '年复盘'};
const RP = {period: 'day'};
function today() { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); }
function periodKey() {
  return RP.period === 'day' ? $('dailyDate').value : RP.period === 'month' ? $('monthDate').value : String($('yearDate').value);
}
function setPeriod(p) {
  RP.period = p;
  document.querySelectorAll('#periodTabs button').forEach(b => b.classList.toggle('on', b.dataset.p === p));
  $('dailyDate').hidden = p !== 'day'; $('monthDate').hidden = p !== 'month'; $('yearDate').hidden = p !== 'year';
  loadDaily();
}
function stepPeriod(n) {
  if (RP.period === 'year') $('yearDate').value = Number($('yearDate').value) + n;
  else if (RP.period === 'month') {
    const [y, m] = $('monthDate').value.split('-').map(Number);
    const d = new Date(y, m - 1 + n, 1);
    $('monthDate').value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  } else {
    const d = new Date($('dailyDate').value + 'T12:00:00'); d.setDate(d.getDate() + n);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); $('dailyDate').value = d.toISOString().slice(0, 10);
  }
  loadDaily();
}
const EMPTY_HINT = {
  day: '这一天还没有日复盘。<br>到了设置的时间会自动生成，也可以点「生成」。',
  month: '这个月还没有月复盘。<br>会按设置在月底（或下月 1 号）自动生成，也可以点「生成」。<br>月复盘会用上这个月每天的日复盘。',
  year: '这一年还没有年复盘。<br>会按设置在年底（或次年 1 月 1 日）自动生成，也可以点「生成」。<br>年复盘会用上每个月的月复盘（缺的月份会先自动补）。',
};
function showDaily(text) {
  $('dailyBody').innerHTML = text ? md(text) : `<p class="empty">${EMPTY_HINT[RP.period]}</p>`;
}
async function openDaily() {
  const t = today();
  if (!$('dailyDate').value) $('dailyDate').value = t;
  if (!$('monthDate').value) $('monthDate').value = t.slice(0, 7);
  if (!$('yearDate').value) $('yearDate').value = t.slice(0, 4);
  openDrawer('dailyDrawer'); loadDaily();
}
async function loadDaily() {
  const key = periodKey(); if (!key) return;
  $('btnMakeReport').textContent = '生成' + PNAME[RP.period];
  const j = await (await fetch(`/api/report?period=${RP.period}&key=${encodeURIComponent(key)}`)).json();
  if (key === periodKey()) showDaily(j.md);
}
async function makeDaily() {
  const key = periodKey(), p = RP.period;
  $('dailyBody').innerHTML = `<p class="dots">AI 正在汇总${{day: '这一天', month: '这个月', year: '这一年'}[p]}的复盘</p>`;
  try { const j = await api(`/api/report?period=${p}&key=${encodeURIComponent(key)}`); if (key === periodKey()) showDaily(j.md); }
  catch (e) { loadDaily(); }
}

// ---------------- 历史 ----------------
async function openHistory() {
  const items = await (await fetch('/api/sessions')).json();
  $('histList').innerHTML = items.length ? items.map(s => `<div class="hist" onclick="viewSession('${esc(s.id)}')">
    <b>${esc(s.title || '（未命名）')}</b><br><small>${esc(s.started.replace('T', ' '))} · ${s.count} 次复盘${(s.devices || []).length ? ' · ' + esc(s.devices.join('、')) : ''}</small></div>`).join('')
    : '<p class="empty">还没有记录</p>';
  openDrawer('historyDrawer');
}
async function viewSession(id) {
  S = await (await fetch('/api/sessions/' + id)).json();
  viewingHistory = true; closeDrawers(); renderAll();
}
async function backToLive() {
  viewingHistory = false;
  const st = await (await fetch('/api/state')).json().catch(() => null);
  S = st?.session || null; recording = !!st?.recording; nextReview = st?.next_review;
  MIC_ON = !!st?.mic_on; DEVS = st?.devices || [];
  if (!S) $('reviews').innerHTML = '';
  renderAll(); renderHeader();
}

// ---------------- AI 用量 ----------------
let USAGE = null;
const kfmt = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0);
async function loadUsage() {
  try { USAGE = await (await fetch('/api/usage')).json(); } catch { return; }
  const t = USAGE.total;
  if (!t.calls) { $('usageInfo').textContent = '今日 AI · 0 次'; return; }
  const hit = t.input ? Math.round(t.cached / t.input * 100) : 0;
  $('usageInfo').textContent = `今日 AI · ${t.calls} 次 · 输入 ${kfmt(t.input)}${hit ? `（缓存 ${hit}%）` : ''} · 输出 ${kfmt(t.output)}`
    + (t.audio_sec ? ` · 听 ${fmtSec(t.audio_sec)}` : '') + (t.saved_sec ? ` · 省静音 ${fmtSec(t.saved_sec)}` : '');
}
function usageHtml() {
  const t = USAGE?.total || {};
  const hit = t.input ? Math.round((t.cached || 0) / t.input * 100) : 0;
  const rows = Object.entries(USAGE?.models || {}).map(([m, x]) =>
    `<tr><td>${esc(m)}</td><td class="num">${x.calls}</td><td class="num">${kfmt(x.input)}</td><td class="num">${kfmt(x.cached)}</td><td class="num">${kfmt(x.output)}</td></tr>`).join('');
  return `<div class="stats">
      <div class="stat"><b>${t.calls || 0}</b><small>调用次数</small></div>
      <div class="stat"><b>${kfmt(t.input)}</b><small>输入 token</small></div>
      <div class="stat"><b>${hit}%</b><small>缓存命中（更便宜）</small></div>
      <div class="stat"><b>${kfmt(t.output)}</b><small>输出 token</small></div>
      <div class="stat"><b>${fmtSec(t.audio_sec)}</b><small>AI 听的录音</small></div>
      <div class="stat"><b>${fmtSec(t.saved_sec)}</b><small>去掉的静音</small></div></div>
    ${rows ? `<table class="ev"><tr><th>模型</th><th>次数</th><th>输入</th><th>其中缓存</th><th>输出</th></tr>${rows}</table>` : ''}
    <ul class="tips">
      <li>最省钱的设置：复盘方式选「自定义周期」并把间隔调长（30–60 分钟）。每次复盘都要带上固定的说明文字，次数越少越省。</li>
      <li>「新语音少于多少秒就跳过」调大一点，没怎么说话的时段就不会调用 AI。</li>
      <li>同一个房间只放一台设备录音；几台一起录，同一段话会被重复听好几遍。</li>
      <li>「关于我」「常用词」写精炼些：它们每次都会发送（已经放在最前面，能命中缓存，按半价或更低计费）。</li>
      <li>想更省：「AI 怎么拿到内容」改成先在本机识别成文字，再交给便宜的文字模型（听不出语气，但费用低很多）。</li>
    </ul>`;
}

// ---------------- 设置 ----------------
const FIELDS = [
  ['h', 'AI 听录音（OpenAI）'],
  ['review_input', 'AI 怎么拿到内容', 'select', [['audio', '直接听录音（推荐：能听出语气情绪，不需要本地识别）'], ['text', '先在本机识别成文字，再把文字交给 AI（旧方式）']]],
  ['audio_api_key', 'OpenAI API Key', 'password', '在 platform.openai.com 的 API keys 页面生成。留空则借用下方「AI 接口」里的 OpenAI Key'],
  ['audio_model', '听录音的模型', 'text', '默认 gpt-audio-1.5'],
  ['audio_base_url', '接口地址', 'text', '默认 https://api.openai.com/v1，一般不用改'],
  ['audio_max_min', '每次最多发送多少分钟录音', 'number', '超过会分几次听，再合并复盘。报“录音太大”时调小'],
  ['audio_trim_silence', '发送前去掉每句话前后多余的静音（省 token，不影响内容）', 'bool'],
  ['test', 'audio', '测试 AI 能不能听到录音'],
  ['h', '本地识别（只在“先在本机识别成文字”时使用）'],
  ['stt_provider', '识别引擎', 'select', [['sensevoice', 'SenseVoice（带标点；整句英文/粤语/日韩语更好；首次自动下载约 240MB）'], ['paraformer', 'Paraformer（中文为主夹英文单词更稳，嘈杂时不易认错语言；不带标点；约 240MB）'], ['whisper', 'Whisper large-v3（最准，用 NVIDIA 显卡跑；需先运行 install_whisper_gpu.bat）'], ['api', '在线接口（不推荐，会上传音频）']]],
  ['stt_language', '语言', 'text', 'zh = 普通话；yue = 粤语；en = 英语；留空 = 自动识别（中英混说时可留空）'],
  ['local_whisper_model', 'Whisper 模型', 'text', '只在选 Whisper 时有效：large-v3（最准）/ large-v3-turbo（快几倍，略逊）'],
  ['test', 'stt', '检查 / 下载识别模型'],
  ['h', '小复盘（录音过程中）'],
  ['review_mode', '多久做一次小复盘', 'select', [['interval', '自定义周期：每隔 N 分钟复盘一次'], ['realtime', '实时：每说完一段（停顿后）就复盘']]],
  ['review_interval_min', '【自定义周期】每隔多少分钟复盘一次', 'number', '可设 1–240。间隔越长越省 token；录音时随时可以点「立即复盘」'],
  ['review_min_sec', '【自定义周期】新语音少于多少秒就跳过这一轮', 'number', '没怎么说话的时段不浪费 AI 调用（听录音模式）'],
  ['realtime_min_sec', '【实时】一段语音少于多少秒先攒着', 'number', '太短的一两句并入下一段一起。说完一段的判定见下方「停顿多少秒算新的一段」'],
  ['review_min_chars', '【文字模式】新内容少于多少字就跳过这一轮', 'number', '只在“先在本机识别成文字”时使用'],
  ['realtime_min_chars', '【文字模式·实时】一段少于多少字先攒着', 'number', '只在“先在本机识别成文字”时使用'],
  ['h', '大复盘（总结）'],
  ['session_review', '整场总复盘', 'select', [['end', '一场录音结束时做（所有设备停止 / 点「结束本场」/ 过零点）'], ['off', '不做（只看日 / 月 / 年复盘）']]],
  ['daily_review_time', '日复盘：每天几点做', 'text', '24 小时制，如 23:00；留空 = 不自动做。电脑没开错过了，下次打开会补上前一天的'],
  ['monthly_review', '月复盘', 'select', [['month_end', '每月最后一天做'], ['next_month', '下个月 1 号做'], ['off', '不自动做（可以在「复盘报告」里手动生成）']]],
  ['yearly_review', '年复盘', 'select', [['year_end', '12 月 31 日做'], ['next_year', '次年 1 月 1 日做'], ['off', '不自动做（可以在「复盘报告」里手动生成）']]],
  ['period_review_time', '月复盘、年复盘在那天几点做', 'text', '24 小时制，默认 23:30：排在日复盘之后，月复盘能用上当天的日复盘'],
  ['h', '复盘内容'],
  ['about_me', '关于我（强烈建议填写）', 'textarea', '你的身份、正在做的事、长期目标。AI 会据此推断你的潜在需求。'],
  ['extra_instructions', '额外要求', 'textarea', '例如：多从商业角度想；建议要考虑我只有周末有空'],
  ['glossary', '我常说的词 / 专有名词 / 英文术语', 'textarea', '人名、公司名、产品名、术语，用逗号隔开。识别错的词 AI 会按这些来理解'],
  ['h', '文字 AI（总复盘、日复盘用；不填则用上面的 OpenAI）'],
  ['llm_provider', '接口类型', 'select', [['openai', 'OpenAI 兼容（硅基流动 / DeepSeek / 通义 / Kimi / 本机 Ollama…）'], ['anthropic', 'Anthropic（Claude）']]],
  ['llm_base_url', '接口地址', 'text', '硅基流动国际版 https://api.siliconflow.com/v1；国内版 https://api.siliconflow.cn/v1；本机 Ollama http://127.0.0.1:11434/v1'],
  ['llm_api_key', 'API Key', 'password', '本机 Ollama 不用填'],
  ['llm_model', '模型名', 'text', '从服务商的模型列表里复制完整名字'],
  ['test', 'llm', '测试 AI 接口'],
  ['h', '分段与录音'],
  ['pause_close_sec', '停顿多少秒算新的一段', 'number', '实时复盘以“说完一段”触发'],
  ['mic_device', '麦克风', 'mic'],
  ['vad_margin_db', '说话检测灵敏度（dB）', 'number', '比环境噪音高多少算说话。环境吵调大（12-15），声音小调小（6-8）'],
  ['save_audio', '保存完整录音', 'bool'],
  ['h', '启动动画（桌面程序）'],
  ['splash_enabled', '打开程序时播放启动动画', 'bool'],
  ['splash_speed', '动画速度', 'seg', [[0.5, '0.5×'], [0.75, '0.75×'], [1, '1×'], [1.5, '1.5×'], [2, '2×'], [3, '3×']], '1× 约 8 秒；数字越大越快。点动画也能直接跳过'],
  ['preview', 'splash', '预览启动动画'],
  ['h', '存储'],
  ['nas_dir', 'NAS 共享目录', 'text', 'Windows 例：\\\\192.168.1.10\\recordings 或 Z:\\录音；Mac 例：/Volumes/recordings（先在访达里连接服务器）。留空则只存本机 data 文件夹'],
  ['test', 'nas', '测试 NAS 写入'],
  ['h', '今日 AI 用量'],
  ['usage'],
];
let CFG = {};
let APP = null;
async function openSettings(focus) {
  const [cfg, mics, model, app] = await Promise.all([
    fetch('/api/config').then(r => r.json()), fetch('/api/devices').then(r => r.json()),
    fetch('/api/model').then(r => r.json()), APP || fetch('/api/app_info').then(r => r.json()), loadUsage()]);
  CFG = cfg; APP = app;
  const html = FIELDS.map(f => {
    const [k, label, type, extra] = f;
    if (k === 'h') return `<h3${label.startsWith('今日') ? ' id="usageSec"' : ''}>${label}</h3>`;
    if (k === 'usage') return `<div id="usageBox">${usageHtml()}</div>`;
    if (k === 'preview') return APP?.desktop
      ? `<div class="row"><button onclick="previewSplash(this)">${type}</button><span class="hint">按上面选的速度播放一遍（会先保存设置）</span></div>` : '';
    if (k === 'test') {
      const note = label === 'stt' ? `<span class="hint">SenseVoice 模型：${model.sensevoice_ready ? '✅ 已就绪' : '未下载（开始录音或点此按钮时自动下载）'}</span>` : '';
      return `<div class="row"><button onclick="testConn('${label}', this)">${type}</button><span class="hint" id="t_${label}"></span>${note}</div>`;
    }
    const v = CFG[k] ?? '';
    let input;
    if (type === 'select') input = `<select id="f_${k}">${extra.map(([val, t]) => `<option value="${val}" ${val === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`;
    else if (type === 'textarea') input = `<textarea id="f_${k}">${esc(v)}</textarea>`;
    else if (type === 'bool') return `<label class="switch"><input type="checkbox" id="f_${k}" ${v ? 'checked' : ''}>${label}</label>`;
    else if (type === 'seg') input = `<div class="seg" id="f_${k}" data-v="${v}">${extra.map(([val, t]) =>
      `<button type="button" class="${Number(val) === Number(v) ? 'on' : ''}" onclick="segPick(this, ${val})">${t}</button>`).join('')}</div>`;
    else if (type === 'mic') input = `<select id="f_${k}"><option value="">系统默认</option>${mics.map(m => `<option value="${m.index ?? ''}" ${m.index === v ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select>`;
    else input = `<input id="f_${k}" type="${type}" value="${esc(v)}">`;
    const note = type === 'seg' ? f[4] : extra;
    const hint = (type !== 'select' && type !== 'mic' && note && typeof note === 'string') ? `<div class="hint">${esc(note)}</div>` : '';
    return `<label>${label}</label>${input}${hint}`;
  }).join('');
  $('settingsForm').innerHTML = html;
  openDrawer('settingsDrawer');
  if (focus === 'usage') $('usageSec')?.scrollIntoView({block: 'start'});
}
function segPick(btn, val) {
  const box = btn.parentElement; box.dataset.v = val;
  box.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
}
async function previewSplash(btn) {
  await saveSettings();
  btn.disabled = true; setTimeout(() => btn.disabled = false, 1500);
  await api('/api/splash_preview');
}
function collect() {
  const out = {};
  for (const [k, , type] of FIELDS) {
    if (k === 'h' || k === 'test' || k === 'usage' || k === 'preview') continue;
    const el = $('f_' + k); if (!el) continue;
    let v = el.value;
    if (type === 'number') v = Number(v);
    if (type === 'bool') v = el.checked;
    if (type === 'seg') v = Number(el.dataset.v);
    if (type === 'mic') v = v === '' ? null : Number(v);
    out[k] = v;
  }
  if (out.review_interval_min) out.review_interval_min = Math.max(1, Math.min(240, out.review_interval_min));
  return out;
}
async function saveSettings() {
  await api('/api/config', {headers: {'content-type': 'application/json'}, body: JSON.stringify(collect())});
  toast('已保存');
}
async function testConn(kind, btn) {
  await saveSettings();
  btn.disabled = true; $('t_' + kind).textContent = '测试中…';
  try { const r = await api('/api/test/' + kind); $('t_' + kind).textContent = (r.ok ? '✅ ' : '❌ ') + r.msg; }
  finally { btn.disabled = false; }
}

connect();
loadUsage();
setInterval(loadUsage, 60000);
if (location.hash === '#eval') { EV.tab = 'set'; openEval(); }
if (location.hash === '#label') openEval();
