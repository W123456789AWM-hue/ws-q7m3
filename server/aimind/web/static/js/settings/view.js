// 设置界面：左边分类 + 搜索，右边分组列表。改了就自动保存（不用点保存）。
// 搜索：输入时左边列出匹配的设置项、分类旁显示命中数；点结果（或回车）→ 切到那个分类、滚过去、高亮闪烁。
import {$, $$, actions, esc, icon, onChange, onInput} from '../dom.js';
import {api, getJSON, postJSON} from '../api.js';
import {replay, segmented, settled, swap} from '../anim.js';
import {layerOpen, openLayer, toast} from '../layers.js';
import {state} from '../state.js';
import {loadUsage, usageHtml} from '../usage.js';
import {ALL, CATEGORIES} from './schema.js';

let cfg = {}, mics = [], model = {}, current = 'general';
const TEST_LABEL = {audio: '测试', llm: '测试', stt: '检查', nas: '测试'};

// ---------- 外观（只存在本机浏览器里） ----------
const getTheme = () => { try { return localStorage.getItem('aim-theme') || 'auto'; } catch { return 'auto'; } };
function setTheme(t) {
  try { localStorage.setItem('aim-theme', t); } catch { /* 隐私模式等 */ }
  if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
}

// ---------- 一行设置项 ----------
function control(f) {
  const v = f.k === 'theme' ? getTheme() : cfg[f.k];
  const opts = f.options || [];
  switch (f.type) {
    case 'select': return `<select data-k="${f.k}" data-change="setField">${opts.map(([val, t]) =>
      `<option value="${esc(val)}" ${String(val) === String(v ?? '') ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
    case 'seg': case 'theme': {
      const list = f.type === 'theme' ? [['auto', '自动'], ['light', '浅色'], ['dark', '深色']] : opts;
      return `<div class="segmented" data-k="${f.k}">${list.map(([val, t]) =>
        `<button type="button" data-action="setSeg" data-val="${esc(val)}" class="${String(val) === String(v) ? 'on' : ''}">${esc(t)}</button>`).join('')}</div>`;
    }
    case 'bool': return `<input type="checkbox" class="switch" data-k="${f.k}" data-change="setField" ${v ? 'checked' : ''}>`;
    case 'textarea': return `<textarea data-k="${f.k}" data-input="setFieldLater" rows="3">${esc(v)}</textarea>`;
    case 'mic': return `<select data-k="${f.k}" data-change="setField"><option value="">系统默认</option>${mics.map(m =>
      `<option value="${m.index ?? ''}" ${m.index === v ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select>`;
    case 'test': return `<button data-action="testConn" data-arg="${f.k}">${TEST_LABEL[f.k] || '测试'}</button>`;
    case 'preview': return `<button data-action="previewSplash">预览</button>`;
    case 'number': return `<input type="number" data-k="${f.k}" data-input="setFieldLater" value="${esc(v)}" style="width:110px">`;
    case 'time': return `<input type="time" data-k="${f.k}" data-change="setField" value="${esc(v)}">`;
    default: return `<input type="${f.type === 'password' ? 'password' : 'text'}" data-k="${f.k}" data-input="setFieldLater" value="${esc(v)}" spellcheck="false">`;
  }
}

function rowHtml(f) {
  if (f.type === 'usage') return `<div class="row stack" id="row_usage" data-row="usage" style="padding:0">${usageHtml()}</div>`;
  if (f.type === 'preview' && !state.app?.desktop) return '';
  let desc = f.desc || '';
  if (f.type === 'test') desc = f.k === 'stt' && model ? `SenseVoice 模型：${model.sensevoice_ready ? '已就绪' : '还没下载（点检查会自动下载）'}` : '';
  const stack = f.type === 'textarea' || f.stack;
  const gone = f.when && !f.when(cfg) ? ' gone' : '';
  return `<div class="row${stack ? ' stack' : ''}${gone}" id="row_${f.k}" data-row="${f.k}">
    <div class="txt"><b>${esc(f.label)}</b>${desc || f.type === 'test' ? `<small id="${f.type === 'test' ? 't_' + f.k : ''}" class="${f.type === 'test' ? 'test-msg' : ''}">${esc(desc)}</small>` : ''}</div>
    <div class="ctl">${control(f)}</div></div>`;
}

function groupHtml(g) {
  const main = g.items.filter(f => !f.adv), adv = g.items.filter(f => f.adv);
  const gone = g.when && !g.when(cfg) ? ' style="display:none"' : '';
  const rows = main.map(rowHtml).join('');
  return `<section data-group="${esc(g.title)}"${gone}>
    <div class="group-title">${esc(g.title)}${g.note ? ` <span class="hint">· ${esc(g.note)}</span>` : ''}</div>
    ${g.items[0]?.type === 'usage' ? rows : `<div class="group">${rows}</div>`}
    ${adv.length ? `<div class="adv"><button data-action="toggleAdv">高级</button>
      <div class="adv-body"><div><div class="group" style="margin-top:6px">${adv.map(rowHtml).join('')}</div></div></div></div>` : ''}
  </section>`;
}

function renderCats(counts = {}) {
  $('setCats').innerHTML = CATEGORIES.map(c => `<button class="cat ${c.id === current ? 'on' : ''}" data-action="setCat" data-arg="${c.id}">
    <span class="ico" style="--c:${c.color}">${icon(c.icon)}</span>${esc(c.name)}${counts[c.id] ? `<span class="n">${counts[c.id]}</span>` : ''}</button>`).join('');
}

function renderPane() {
  const c = CATEGORIES.find(x => x.id === current);
  $('setTitle').textContent = c.name;
  $('setBody').innerHTML = c.groups.map(groupHtml).join('');
  $$('#setBody .segmented').forEach(segmented);
}

async function showCategory(id) {
  if (id === current && $('setBody').childElementCount) return;
  current = id;
  $$('#setCats .cat').forEach(b => b.classList.toggle('on', b.dataset.arg === id));
  await swap($('setBody'), renderPane);
  $('setBody').scrollTop = 0;
}

/** 条件显示：改了某个设置后，重新判断哪些项该出现（新出现的淡入） */
function refreshVisibility() {
  const cat = CATEGORIES.find(x => x.id === current);
  for (const g of cat.groups) {
    const sec = $('setBody').querySelector(`[data-group="${CSS.escape(g.title)}"]`);
    if (sec && g.when) sec.style.display = g.when(cfg) ? '' : 'none';
    for (const f of g.items) {
      const row = $('row_' + f.k);
      if (!row || !f.when) continue;
      const show = f.when(cfg), was = !row.classList.contains('gone');
      row.classList.toggle('gone', !show);
      if (show && !was) replay(row, 'appear');
    }
  }
  $$('#setBody .segmented').forEach(segmented);
}

// ---------- 保存 ----------
let savedTimer = 0;
function flashSaved() {
  const tip = $('savedTip');
  tip.classList.add('show');
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => tip.classList.remove('show'), 1400);
}

async function save(k, v) {
  if (k === 'theme') { setTheme(v); flashSaved(); return; }
  if (k === 'review_interval_min') v = Math.max(1, Math.min(240, v || 30));
  cfg[k] = v;
  refreshVisibility();
  await postJSON('/api/config', {[k]: v});
  flashSaved();
}

function readValue(input) {
  const f = ALL.find(x => x.k === input.dataset.k);
  if (f.type === 'bool') return input.checked;
  if (f.type === 'number') return Number(input.value);
  if (f.type === 'mic') return input.value === '' ? null : Number(input.value);
  return input.value;
}

const later = {};
function saveLater(input) {          // 打字时停一下再保存
  const k = input.dataset.k;
  clearTimeout(later[k]);
  later[k] = setTimeout(() => save(k, readValue(input)), 600);
}

// ---------- 搜索 ----------
let hits = [], sel = 0;
const norm = s => String(s || '').toLowerCase();

function search(q) {
  q = norm(q).trim();
  const box = $('setResults');
  if (!q) { box.hidden = true; hits = []; renderCats(); return; }
  const words = q.split(/\s+/);
  hits = ALL.filter(f => f.type !== 'preview' || state.app?.desktop).filter(f => {
    const hay = norm([f.label, f.desc, f.kw, f.group.title, f.cat.name].join(' '));
    return words.every(w => hay.includes(w));
  });
  sel = 0;
  const counts = {};
  hits.forEach(f => { counts[f.cat.id] = (counts[f.cat.id] || 0) + 1; });
  renderCats(counts);
  const mark = s => esc(s).replace(new RegExp(words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'gi'), m => `<mark>${m}</mark>`);
  box.innerHTML = hits.length ? hits.slice(0, 8).map((f, i) =>
    `<button class="${i === sel ? 'sel' : ''}" data-action="gotoField" data-arg="${f.k}">${mark(f.label)}<small>${esc(f.cat.name)}</small></button>`).join('')
    : '<div class="none">没有找到相关设置</div>';
  box.hidden = false;
}

/** 跳到某个设置项：切分类 → 展开「高级」 → 滚过去 → 高亮闪烁 */
async function gotoField(k) {
  const f = ALL.find(x => x.k === k);
  if (!f) return;
  await showCategory(f.cat.id);
  if (f.when && !f.when(cfg)) toast('这一项要在满足条件时才会用到，已先显示出来');
  const row = $('row_' + k);
  if (!row) return;
  row.classList.remove('gone');
  row.closest('section').style.display = '';
  const adv = row.closest('.adv');
  if (adv && !adv.classList.contains('open')) { adv.classList.add('open'); await settled(adv.querySelector('.adv-body'), 320); }
  row.scrollIntoView({behavior: 'smooth', block: 'center'});
  setTimeout(() => replay(row, 'flash'), 260);
  row.querySelector('input,select,textarea')?.focus({preventScroll: true});
}

// ---------- 打开 ----------
export async function openSettings(focus) {
  // 只等设置本身（很快）；麦克风列表、模型状态、用量在后台取，取到了再刷新当前页（打开不卡顿）
  const [c, app] = await Promise.all([getJSON('/api/config'), state.app || getJSON('/api/app_info').catch(() => ({}))]);
  cfg = c; state.app = app;
  if (focus === 'usage') current = 'usage';
  $('setSearch').value = ''; $('setResults').hidden = true;
  renderCats(); renderPane();
  const refresh = ids => { if (ids.includes(current)) renderPane(); };
  getJSON('/api/devices').then(m => { mics = m; refresh(['record']); }).catch(() => {});
  getJSON('/api/model').then(mo => { model = mo; refresh(['ai']); }).catch(() => {});
  loadUsage().then(() => refresh(['usage']));
  await openLayer('settingsSheet');
  $$('#setBody .segmented').forEach(segmented);   // 弹窗出现后再算滑块位置
}

export function initSettings() {
  actions({
    openSettings: btn => openSettings(btn?.dataset?.arg),
    setCat: btn => showCategory(btn.dataset.arg),
    gotoField: btn => gotoField(btn.dataset.arg),
    toggleAdv: btn => btn.parentElement.classList.toggle('open'),
    setSeg: btn => {
      const box = btn.parentElement;
      box.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
      segmented(box);
      const f = ALL.find(x => x.k === box.dataset.k);
      const raw = btn.dataset.val;
      save(box.dataset.k, f.type === 'seg' && typeof f.options[0][0] === 'number' ? Number(raw) : raw);
    },
    testConn: async btn => {
      const kind = btn.dataset.arg, msg = $('t_' + kind);
      btn.disabled = true; msg.textContent = '测试中…';
      try { const r = await api('/api/test/' + kind); msg.textContent = (r.ok ? '✅ ' : '❌ ') + r.msg; }
      catch (e) { msg.textContent = '❌ ' + e.message; }
      finally { btn.disabled = false; }
    },
    previewSplash: async btn => { btn.disabled = true; setTimeout(() => { btn.disabled = false; }, 1500); await api('/api/splash_preview'); },
  });
  onChange({setField: input => save(input.dataset.k, readValue(input))});
  onInput({setFieldLater: saveLater, searchSettings: input => search(input.value)});
  $('setSearch').addEventListener('keydown', e => {
    if (!hits.length) return;
    const btns = $$('#setResults button');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + btns.length) % btns.length;
      btns.forEach((b, i) => b.classList.toggle('sel', i === sel));
    } else if (e.key === 'Enter') { e.preventDefault(); gotoField(btns[sel]?.dataset.arg); }
  });
  document.addEventListener('keydown', e => {   // Ctrl / ⌘ + ,  打开设置；Ctrl / ⌘ + F 在设置里搜索
    if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); openSettings(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f' && layerOpen('settingsSheet')) { e.preventDefault(); $('setSearch').focus(); }
  });
  window.addEventListener('resize', () => $$('.segmented').forEach(segmented));
}
