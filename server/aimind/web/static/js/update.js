// 在线更新：顶栏的“有新版本”小提示 + 设置里「软件更新」那一块
import {$, actions, esc} from './dom.js';
import {api, getJSON} from './api.js';
import {md} from './format.js';
import {toast} from './layers.js';
import {emit, on, state} from './state.js';

const mb = n => n ? (n / 1048576).toFixed(1) + ' MB' : '';

function renderBadge() {
  const u = state.update, b = $('updBadge');
  const show = !!u?.available;
  b.hidden = !show;
  if (show) b.querySelector('span').textContent = `新版本 ${u.latest}`;
}

/** 设置「通用 → 软件更新」里的内容 */
export function updateHtml() {
  const u = state.update || {};
  let status;
  if (u.installing) status = '<span class="thinking">正在安装新版本，程序会自动重新打开…</span>';
  else if (u.downloading) status = `<div class="upd-bar"><i style="width:${u.progress}%"></i></div><small>正在下载 ${u.progress}%</small>`;
  else if (u.checking) status = '<span class="thinking">正在检查…</span>';
  else if (u.available) status = `<b class="upd-new">有新版本 ${esc(u.latest)}</b>${u.date ? ` <small>${esc(u.date)}</small>` : ''}`;
  else if (u.latest) status = '<span class="hint">已经是最新版本</span>';
  else status = '<span class="hint">还没检查过</span>';
  const canInstall = u.available && !u.install_problem && !u.downloading && !u.installing;
  return `<div class="row"><div class="txt"><b>当前版本 ${esc(u.current || '')}</b>
      <small>${status}</small></div>
    <div class="ctl"><button data-action="checkUpdate" ${u.checking || u.downloading || u.installing ? 'disabled' : ''}>检查更新</button>
      ${u.available ? `<button class="primary" data-action="installUpdate" ${canInstall ? '' : 'disabled'}>下载并安装${u.size ? `（${mb(u.size)}）` : ''}</button>` : ''}</div></div>
    ${u.available && u.notes ? `<div class="row stack"><div class="txt"><b>更新内容</b></div><div class="md upd-notes">${md(u.notes)}</div></div>` : ''}
    ${u.available && u.install_problem ? `<div class="row"><div class="txt"><small style="color:var(--orange)">${esc(u.install_problem)}</small></div></div>` : ''}
    ${u.error ? `<div class="row"><div class="txt"><small style="color:var(--red)">${esc(u.error)}</small></div></div>` : ''}`;
}

export async function loadUpdate() {
  try { state.update = await getJSON('/api/update'); } catch { return; }
  renderBadge();
  emit('update-changed');
}

export function initUpdate() {
  actions({
    checkUpdate: async () => {
      state.update = {...(state.update || {}), checking: true}; emit('update-changed');
      state.update = await api('/api/update/check');
      renderBadge(); emit('update-changed');
      if (!state.update.error) toast(state.update.available ? `有新版本 ${state.update.latest}` : '已经是最新版本');
    },
    installUpdate: async () => {
      const recording = state.recording;
      if (recording) return toast('正在录音，等这一场结束后再更新（录音不会丢）');
      if (!confirm(`下载并安装 ${state.update.latest}？\n\n安装时程序会关闭，装好后自动重新打开（大约 10 秒）。录音、复盘和设置都不受影响。`)) return;
      await api('/api/update/install');
    },
  });
  on('update', m => { state.update = m; renderBadge(); emit('update-changed'); });
  loadUpdate();
}
