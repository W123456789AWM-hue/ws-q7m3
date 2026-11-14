// 侧边抽屉里的面板：设备连接、历史记录、复盘报告（日 / 月 / 年）
import {$, $$, actions, esc, onChange} from './dom.js';
import {api, getJSON, postJSON} from './api.js';
import {segmented, swap} from './anim.js';
import {ago, md, today} from './format.js';
import {layerOpen, openLayer, toast} from './layers.js';
import {viewSession} from './live.js';
import {on} from './state.js';

// ---------- 设备连接 ----------
const copyRows = (arr, empty) => arr?.length
  ? `<div class="group">${arr.map(u => `<div class="row"><input readonly value="${esc(u)}" style="flex:1" data-action="selectAll"></div>`).join('')}</div>`
  : `<p class="hint" style="margin:0 4px">${empty}</p>`;

async function renderDevices() {
  const j = await getJSON('/api/phone/info');
  const phones = (j.phones || []).map(d => `<div class="row">
      <span class="dot ${d.online ? 'on' : ''}"></span>
      <div class="txt"><b>${esc(d.name)}</b><small>${esc(d.id)} · 最后在线 ${ago(d.last_seen)}${d.backlog ? ` · 待处理 ${d.backlog} 片` : ''}</small></div>
      <div class="ctl"><button data-action="renameDevice" data-id="${esc(d.id)}" data-name="${esc(d.name)}">改名</button>
        <button class="ghost" data-action="forgetDevice" data-id="${esc(d.id)}" title="从列表移除（不影响已有记录）">移除</button></div></div>`).join('');
  $('devicesBody').innerHTML = `
    <p class="hint" style="margin:0 4px">手机、平板、别的电脑都可以当录音设备，几台同时录也行：内容合在同一场里，一起交给 AI 复盘。</p>
    <div class="group-title">已连接过的设备</div>
    ${phones ? `<div class="group">${phones}</div>` : '<p class="hint" style="margin:0 4px">还没有设备连上来。</p>'}
    <div class="group-title">在 App「设置」里填：电脑地址（任选一个能连通的）</div>
    ${copyRows(j.urls, '没找到局域网地址，请检查电脑是否已联网')}
    <div class="group-title">备用地址（外出时用）</div>
    ${copyRows(j.away_urls, '还没有。在这台电脑和手机上都装 Tailscale 并用同一账号登录，这里会出现 100. 开头的地址。')}
    <div class="group-title">连接口令</div>${copyRows([j.token], '')}
    <div class="group-title">在其他电脑的浏览器里查看结果</div>${copyRows(j.view_urls, '暂无')}
    <p class="hint" style="margin:14px 4px 0">地址里带了口令，不要发给别人。第一次启动时系统防火墙会询问，要点「允许」，否则设备连不上。
      电脑没开时，设备会先把录音存着，连上后自动补传。</p>`;
}

// ---------- 历史 ----------
async function renderHistory() {
  const items = await getJSON('/api/sessions');
  $('histList').innerHTML = items.length ? `<div class="group">${items.map(s => `
    <div class="row click" data-action="viewSession" data-arg="${esc(s.id)}">
      <div class="txt"><b>${esc(s.title || '（未命名）')}</b>
        <small class="mono">${esc(s.started.replace('T', ' '))} · ${s.count} 次复盘${(s.devices || []).length ? ' · ' + esc(s.devices.join('、')) : ''}</small></div>
      <span class="chev">›</span></div>`).join('')}</div>` : '<p class="empty">还没有记录</p>';
}

// ---------- 复盘报告 ----------
const PNAME = {day: '日复盘', month: '月复盘', year: '年复盘'};
const SPAN = {day: '这一天', month: '这个月', year: '这一年'};
const EMPTY = {
  day: '这一天还没有日复盘。<br>到了设置的时间会自动生成，也可以点「生成」。',
  month: '这个月还没有月复盘。<br>会按设置自动生成，也可以点「生成」。月复盘会用上这个月每天的日复盘。',
  year: '这一年还没有年复盘。<br>会按设置自动生成，也可以点「生成」。年复盘会用上每个月的月复盘。',
};
let period = 'day';
const keyInput = () => ({day: $('dayKey'), month: $('monthKey'), year: $('yearKey')}[period]);
const reportKey = () => String(keyInput().value);
const showReport = text => { $('reportBody').innerHTML = text ? md(text) : `<p class="empty">${EMPTY[period]}</p>`; };

async function loadReport() {
  const key = reportKey(); if (!key) return;
  $('btnMakeReport').textContent = '生成' + PNAME[period];
  const j = await getJSON(`/api/report?period=${period}&key=${encodeURIComponent(key)}`);
  if (key === reportKey()) await swap($('reportBody'), () => showReport(j.md));
}

function setPeriod(p) {
  period = p;
  $$('#periodTabs button').forEach(b => b.classList.toggle('on', b.dataset.arg === p));
  segmented($('periodTabs'));
  ['day', 'month', 'year'].forEach(x => { $(x + 'Key').hidden = x !== p; });
  loadReport();
}

function stepPeriod(n) {
  const k = keyInput();
  if (period === 'year') k.value = Number(k.value) + n;
  else if (period === 'month') {
    const [y, m] = k.value.split('-').map(Number);
    const d = new Date(y, m - 1 + n, 1);
    k.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  } else {
    const d = new Date(k.value + 'T12:00:00'); d.setDate(d.getDate() + n);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); k.value = d.toISOString().slice(0, 10);
  }
  loadReport();
}

export function initPanels() {
  actions({
    openDevices: async () => { await renderDevices(); openLayer('devicesDrawer'); },
    selectAll: input => input.select(),
    renameDevice: async btn => {
      const name = prompt('新名字（比如：客厅手机、办公室 iPad）', btn.dataset.name);
      if (!name) return;
      await postJSON(`/api/phones/${encodeURIComponent(btn.dataset.id)}/rename`, {name});
      renderDevices();
    },
    forgetDevice: async btn => { await api(`/api/phones/${encodeURIComponent(btn.dataset.id)}/forget`); renderDevices(); },
    openHistory: async () => { await renderHistory(); openLayer('historyDrawer'); },
    viewSession: row => viewSession(row.dataset.arg),
    openReports: async () => {
      const t = today();
      $('dayKey').value ||= t; $('monthKey').value ||= t.slice(0, 7); $('yearKey').value ||= t.slice(0, 4);
      await openLayer('reportsDrawer');
      segmented($('periodTabs'));
      loadReport();
    },
    setPeriod: btn => setPeriod(btn.dataset.arg),
    stepPeriod: btn => stepPeriod(Number(btn.dataset.arg)),
    makeReport: async () => {
      const key = reportKey(), p = period;
      $('reportBody').innerHTML = `<p class="thinking">AI 正在汇总${SPAN[p]}的复盘</p>`;
      try { const j = await api(`/api/report?period=${p}&key=${encodeURIComponent(key)}`); if (key === reportKey()) showReport(j.md); }
      catch { loadReport(); }
    },
  });
  onChange({loadReport: () => loadReport()});
  on('report', m => {
    if (layerOpen('reportsDrawer') && m.period === period && m.key === reportKey()) showReport(m.md);
    toast(`${m.key} ${PNAME[m.period]}已生成`);
  });
}
