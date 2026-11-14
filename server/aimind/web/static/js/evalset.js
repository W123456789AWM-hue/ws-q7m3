// 识别测试（只在“先在本机识别成文字”时有意义）：标注句子 → 测试集 → 比较几个本地识别模型的错误率
import {$, $$, actions, esc, onChange, onInput} from './dom.js';
import {api, getJSON, postJSON} from './api.js';
import {segmented, swap} from './anim.js';
import {layerOpen, openLayer, toast} from './layers.js';
import {on} from './state.js';

const EV = {tab: 'label', sid: ''};
let audio = null;

const tabs = () => `<div class="segmented" id="evTabs" style="margin:4px 0 14px">
  <button data-action="evalTab" data-arg="label" class="${EV.tab === 'label' ? 'on' : ''}">① 标注句子</button>
  <button data-action="evalTab" data-arg="set" class="${EV.tab === 'set' ? 'on' : ''}">② 测试集与评测</button></div>`;

async function showLabel() {
  const sessions = await getJSON('/api/sessions');
  if (!EV.sid && sessions.length) EV.sid = sessions[0].id;
  let rows = '<p class="empty">还没有录音。先用手机或电脑录一段平时真实的说话（5–10 分钟就够）。</p>';
  if (EV.sid) {
    const utts = await getJSON('/api/eval/utts/' + encodeURIComponent(EV.sid));
    rows = utts.some(u => u.has_audio) ? utts.filter(u => u.has_audio).map(u => `<div class="ev-row ${u.in_set ? 'inset' : ''}">
        <input type="checkbox" id="evc_${u.i}" ${u.in_set ? 'checked' : ''}>
        <small>${esc(u.clock)}<br>${u.sec}秒</small>
        <button class="icon" title="播放这一句" data-action="evalPlay" data-arg="/api/eval/audio?sid=${encodeURIComponent(EV.sid)}&i=${u.i}">▶</button>
        <textarea id="evt_${u.i}" data-input="evalEdited" data-arg="${u.i}">${esc(u.in_set ? u.ref : u.text)}</textarea></div>`).join('')
      : '<p class="empty">这一场录音没有保存每句话的位置，不能用来标注。设置里要开着「保存完整录音」。</p>';
  }
  $('evalBody').innerHTML = tabs() + `
    <p class="hint">点 ▶ 听一句，把右边的文字改成<b>你实际说的话</b>。听不清的不要勾；改过的会自动打勾。绿色框 = 已在测试集里。</p>
    <div style="display:flex;gap:8px;align-items:center;margin:12px 0">
      <select style="flex:1" data-change="evalSession">${sessions.map(s =>
        `<option value="${esc(s.id)}" ${s.id === EV.sid ? 'selected' : ''}>${esc(s.started.replace('T', ' '))} ${esc(s.title || '')}</option>`).join('')}</select>
      <button class="primary" data-action="evalAdd">把打勾的句子存入测试集</button></div>
    <div>${rows}</div>`;
}

const opsHtml = ops => ops.map(([op, r, h]) => op === '=' ? esc(h)
  : op === 'S' ? `<span class="op-S" title="应为：${esc(r)}">${esc(h)}</span>`
  : op === 'D' ? `<span class="op-D" title="漏了">${esc(r)}</span>` : `<span class="op-I" title="多出来的">${esc(h)}</span>`).join(' ');

async function showSet() {
  const j = await getJSON('/api/eval/set'), res = j.results;
  let table = '<p class="hint">还没有评测结果。</p>', detail = '';
  if (res) {
    const ok = res.engines.filter(e => !e.error);
    const best = Math.min(...ok.filter(e => e.key !== 'orig').map(e => e.rate));
    table = `<p class="hint">上次评测：${esc(res.time)}，${res.count} 句 / ${Math.round(res.seconds)} 秒。错误率越低越好。</p>
      <table class="tbl"><tr><th>识别模型</th><th>错误率</th><th>错误 / 总数</th><th>全对的句子</th><th>速度</th></tr>
      ${res.engines.map(e => e.error ? `<tr><td>${esc(e.label)}</td><td colspan="4" style="color:var(--red)">不可用：${esc(e.error)}</td></tr>`
        : `<tr><td>${esc(e.label)}</td><td class="num ${e.key !== 'orig' && e.rate === best ? 'best' : ''}">${e.rate}%</td>
           <td class="num">${e.errors} / ${e.words}</td><td class="num">${e.perfect} / ${res.count}</td>
           <td class="num">${e.speed ? '实时的 ' + e.speed + ' 倍' : '—'}</td></tr>`).join('')}</table>`;
    const byId = Object.fromEntries(j.items.map(x => [x.id, x]));
    detail = '<div class="group-title">逐句对比（红色 = 和你标注的不一样）</div>' + (ok[0]?.rows || []).map((_, n) => {
      const id = ok[0].rows[n].id, it = byId[id];
      return it ? `<div class="card mini"><button class="icon" data-action="evalPlay" data-arg="/api/eval/item_audio/${id}">▶</button> <b>${esc(it.ref)}</b>
        <button class="ghost" style="float:right" data-action="evalRemove" data-arg="${id}">删除</button>
        ${ok.map(e => { const r = e.rows[n]; return `<div style="margin-top:4px"><span class="tag">${esc(e.label)}</span>${opsHtml(r.ops)} ${r.errors ? `<small style="color:var(--red)">（${r.errors} 处）</small>` : '✓'}</div>`; }).join('')}</div>` : '';
    }).join('');
  } else if (j.count) {
    detail = j.items.map(it => `<div class="card mini"><button class="icon" data-action="evalPlay" data-arg="/api/eval/item_audio/${it.id}">▶</button> ${esc(it.ref)}
      <button class="ghost" style="float:right" data-action="evalRemove" data-arg="${it.id}">删除</button></div>`).join('');
  }
  const names = {sensevoice: 'SenseVoice', paraformer: 'Paraformer', whisper: 'Whisper（显卡）'};
  $('evalBody').innerHTML = tabs() + `
    <p>测试集：<b>${j.count}</b> 句，共 <b>${Math.round(j.seconds)}</b> 秒。${j.count < 30 ? '建议至少 50 句（约 5 分钟），结果才稳定。' : ''}
      可评测：${j.engines.map(e => names[e]).join('、')}</p>
    <div style="display:flex;gap:8px;align-items:center;margin:12px 0">
      <button class="primary" data-action="evalRun" ${j.count ? '' : 'disabled'}>开始评测</button>
      <button data-action="evalExport" ${j.count ? '' : 'disabled'}>导出测试集（zip）</button>
      <span class="hint" id="evalMsg"></span></div>${table}${detail}`;
}

const render = () => swap($('evalBody'), async () => { await (EV.tab === 'label' ? showLabel() : showSet()); segmented($('evTabs')); });

export function initEval() {
  actions({
    openEval: async () => { await openLayer('evalDrawer'); render(); },
    evalTab: btn => { EV.tab = btn.dataset.arg; render(); },
    evalPlay: btn => { audio?.pause(); audio = new Audio(btn.dataset.arg); audio.play(); },
    evalAdd: async () => {
      const picks = $$('[id^=evc_]').filter(c => c.checked).map(c => { const i = Number(c.id.slice(4)); return {i, ref: $('evt_' + i).value}; });
      if (!picks.length) return toast('还没有打勾的句子');
      const r = await postJSON('/api/eval/add', {sid: EV.sid, picks});
      toast(`已保存。测试集现在有 ${r.count} 句，共 ${Math.round(r.seconds)} 秒`);
      render();
    },
    evalRun: async () => { await api('/api/eval/run'); $('evalMsg').textContent = '开始评测…（没下载过的模型会先自动下载）'; },
    evalRemove: async btn => { await api('/api/eval/remove/' + btn.dataset.arg); render(); },
    evalExport: () => { location.href = '/api/eval/export'; },
  });
  onChange({evalSession: sel => { EV.sid = sel.value; render(); }});
  onInput({evalEdited: ta => { $('evc_' + ta.dataset.arg).checked = true; }});
  on('eval', m => {
    if ($('evalMsg')) $('evalMsg').textContent = m.msg;
    if (m.done) { toast(m.msg); if (layerOpen('evalDrawer')) { EV.tab = 'set'; render(); } }
  });
  if (location.hash === '#eval' || location.hash === '#label') {
    EV.tab = location.hash === '#eval' ? 'set' : 'label';
    openLayer('evalDrawer').then(render);
  }
}
