// 主界面：顶栏状态、听写列表、录音操作、历史 ↔ 当前切换
import {$, actions, esc, icon, onChange} from './dom.js';
import {api, getJSON, postJSON} from './api.js';
import {swap} from './anim.js';
import {voiceLabel} from './format.js';
import {closeLayer, openLayer, toast} from './layers.js';
import {renderReviews, renderSummary} from './reviews.js';
import {state} from './state.js';

// ---------- 顶栏 ----------
let lvRaf = 0, lvVal = 0;
export function setLevel(db) {      // 音量条：合并到下一帧画，用 transform 不触发排版
  lvVal = Math.max(0, Math.min(1, (db + 60) / 60));
  if (!lvRaf) lvRaf = requestAnimationFrame(() => { lvRaf = 0; $('lv').style.transform = `scaleX(${lvVal})`; });
}

export function renderHeader() {
  const st = state.session?.status;
  const live = state.devices.filter(d => !d.stopped).map(d => d.name);
  let cls = 'status', txt = '待机';
  if (state.recording) { cls = 'status on'; txt = '正在录音' + (live.length ? ' · ' + live.join('、') : ''); }
  else if (st === 'finishing') { cls = 'status busy'; txt = '收尾复盘中'; }
  const pill = $('status');
  pill.className = cls; pill.lastElementChild.textContent = txt; pill.title = txt;
  const b = $('btnRec');
  b.className = state.micOn ? 'rec' : 'primary';
  b.innerHTML = state.micOn ? `${icon('stop')}<span>停止电脑麦克风</span>` : `${icon('mic')}<span>电脑麦克风录音</span>`;
  $('btnReview').disabled = !state.recording;
  $('btnFinish').disabled = !state.recording;
  if (!state.micOn) setLevel(-60);
}

export function renderNext() {
  const n = state.nextReview, box = $('nextInfo');
  if (!n || state.viewingHistory) { box.textContent = ''; return; }
  const u = n.unit || '字';
  if (n.mode === 'realtime') { box.textContent = `实时复盘 · 已积累 ${n.new_chars}/${n.min_chars} ${u}`; return; }
  const m = Math.floor(n.seconds_left / 60), s = n.seconds_left % 60;
  const need = n.new_chars < n.min_chars ? ` · 新内容 ${n.new_chars}/${n.min_chars} ${u}` : ` · 已积累 ${n.new_chars} ${u}`;
  box.textContent = `下次复盘 ${m}:${String(s).padStart(2, '0')}${need}`;
}

// ---------- 听写 ----------
let lastPid = null;
const multiDevice = () => {
  const s = state.session;
  return (s?.devices || []).length > 1 || new Set((s?.paragraphs || []).map(p => p.device_name)).size > 1;
};
function capHtml(clock, text, pid, dev, voice, multi, cls = '') {
  const sep = lastPid !== null && pid !== lastPid ? '<div class="cap sep"></div>' : '';
  lastPid = pid;
  const tag = dev && multi ? `<span class="dev">${esc(dev)}</span>` : '';
  return `${sep}<div class="cap${voice ? ' voice' : ''}${cls}"><time>${esc(clock)}</time>${tag}${esc(text)}</div>`;
}

/** 录音中新来的一句：只追加这一句（滑入动画），用户在看底部时自动跟随 */
export function addCaption(m) {
  const col = $('captions');
  const stick = col.scrollHeight - col.scrollTop - col.clientHeight < 200;
  $('capList').insertAdjacentHTML('beforeend',
    capHtml(m.clock, m.text || voiceLabel(m.sec), m.pid, m.device_name, !m.text, multiDevice(), ' new'));
  if (stick) col.scrollTo({top: col.scrollHeight, behavior: 'smooth'});
}

function renderCaptions() {
  lastPid = null;
  const s = state.session;
  const paras = s ? [...s.paragraphs].sort((a, b) => (a.start_t ?? 0) - (b.start_t ?? 0) || a.id - b.id) : [];
  const multi = multiDevice(), out = [];
  for (const p of paras) {
    const segs = p.segments || [], d = p.device_name;
    if (segs.some(x => x.text)) for (const x of segs) out.push(capHtml(x.clock || p.start_clock, x.text, p.id, d, false, multi));
    else if (p.text) out.push(capHtml(p.start_clock, p.text, p.id, d, false, multi));
    else for (const x of segs) out.push(capHtml(x.clock || p.start_clock, voiceLabel(x.sec) + ' · 等 AI 复盘时听写', p.id, d, true, multi));
  }
  $('capList').innerHTML = out.join('');      // 一次放进页面（几千句也不卡）
  $('captions').scrollTop = $('captions').scrollHeight;
}

/** 整个会话重画（换会话、听写文字填回来时） */
export function renderAll() {
  const s = state.session;
  renderCaptions();
  renderReviews();
  renderSummary();
  $('sessInfo').textContent = s ? `会话 ${s.id}${s.title ? ' · ' + s.title : ''}${(s.devices || []).length ? ' · ' + s.devices.join(' / ') : ''}` : '';
  $('nasInfo').textContent = s?.nas_status || '';
  $('viewing').innerHTML = state.viewingHistory && s
    ? `<div class="viewing"><span style="flex:1">正在查看历史记录</span>
         <button data-action="backToLive">返回当前</button><button data-action="openFolder" data-arg="${esc(s.id)}">打开文件夹</button></div>` : '';
  renderNext();
}

// ---------- 历史 ↔ 当前（主区域淡出淡入） ----------
export async function viewSession(id) {
  const s = await getJSON('/api/sessions/' + encodeURIComponent(id));
  closeLayer();
  await swap($('main'), () => { state.session = s; state.viewingHistory = true; renderAll(); });
}

export async function backToLive() {
  const st = await getJSON('/api/state').catch(() => null);
  await swap($('main'), () => {
    state.viewingHistory = false;
    Object.assign(state, {session: st?.session || null, recording: !!st?.recording, nextReview: st?.next_review,
                          micOn: !!st?.mic_on, devices: st?.devices || []});
    renderAll(); renderHeader();
  });
}

export function initLive() {
  actions({
    toggleRec: async () => {
      if (state.viewingHistory) await backToLive();
      await api(state.micOn ? '/api/stop' : '/api/start');
    },
    finishNow: async () => {
      if (!confirm('结束这一场？所有设备的内容会马上做整场总复盘。设备之后再传来的录音会开新的一场。')) return;
      await api('/api/finish');
    },
    reviewNow: async () => { await api('/api/review_now'); toast('已交给 AI 复盘'); },
    backToLive: () => backToLive(),
    openFolder: btn => api('/api/open_folder/' + encodeURIComponent(btn.dataset.arg)),
    pickWav: () => $('file').click(),
    openTextTest: () => openLayer('textDrawer'),
    analyzeText: async () => {
      state.viewingHistory = false;
      await postJSON('/api/analyze_text', {text: $('testText').value});
      closeLayer();
    },
  });
  onChange({
    importWav: async input => {
      const f = input.files[0]; input.value = '';
      if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      state.viewingHistory = false;
      await api('/api/import', {body: fd});
      toast('已开始处理音频文件');
    },
  });
}
