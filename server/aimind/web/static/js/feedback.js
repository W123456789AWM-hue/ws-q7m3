// 用户反馈：设置「反馈」里写 → 电脑发到开发者的飞书群；发不出去会先存着，过一会儿自动重发
import {$, actions, esc} from './dom.js';
import {getJSON, postJSON, api} from './api.js';
import {segmented} from './anim.js';
import {toast} from './layers.js';

let kind = 'bug', items = [], configured = true, diagOpen = false, sending = false;
const KINDS = [['bug', '问题'], ['idea', '建议'], ['other', '其他']];
const STATUS = {sent: '已送达', pending: '等待发送'};
const when = t => new Date(t * 1000).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'});

function historyHtml() {
  if (!items.length) return '<div class="row"><div class="txt"><small>还没有发过反馈</small></div></div>';
  const pending = items.some(x => x.status === 'pending');
  return items.map(x => `<div class="row stack fb-item">
      <div class="txt"><b>${esc(KINDS.find(k => k[0] === x.kind)?.[1] || '其他')} · ${when(x.time)}
        <span class="fb-st ${x.status}">${STATUS[x.status] || x.status}</span></b>
        <small class="fb-text">${esc(x.text)}</small>
        ${x.status === 'pending' && x.error ? `<small class="fb-err">${esc(x.error)}</small>` : ''}</div></div>`).join('')
    + (pending ? `<div class="row"><div class="txt"><small>没送达的会每 5 分钟自动重发</small></div>
        <div class="ctl"><button data-action="fbRetry">现在重发</button></div></div>` : '');
}

/** 设置「反馈」里的整块内容 */
export function feedbackHtml() {
  return `<div class="group">
    <div class="row" id="fbNoTarget" ${configured ? 'hidden' : ''}><div class="txt"><small style="color:var(--orange)">这个版本还没接通反馈通道，写好的反馈会先存在本机，升级后自动发出。</small></div></div>
    <div class="row"><div class="txt"><b>类型</b></div>
      <div class="ctl"><div class="segmented" id="fbKind">${KINDS.map(([v, t]) =>
        `<button type="button" data-action="fbKind" data-val="${v}" class="${v === kind ? 'on' : ''}">${t}</button>`).join('')}</div></div></div>
    <div class="row stack"><div class="txt"><b>想说的</b><small>遇到了什么问题（怎么操作的、看到了什么），或者希望加什么功能</small></div>
      <div class="ctl"><textarea id="fbText" rows="5" maxlength="4000" placeholder="比如：点「结束本场」后一直显示正在收尾…"></textarea></div></div>
    <div class="row"><div class="txt"><b>联系方式</b><small>选填：微信 / 邮箱，方便回复你</small></div>
      <div class="ctl"><input id="fbContact" type="text" maxlength="100" spellcheck="false"></div></div>
    <div class="row"><div class="txt"><b>附带诊断信息</b><small>版本、系统、最近的程序日志（密钥会自动抹掉；不含录音和复盘内容）。
      <a href="#" data-action="fbDiag">${diagOpen ? '收起' : '看看会发什么'}</a></small></div>
      <div class="ctl"><input id="fbDiagOn" type="checkbox" class="switch" checked></div></div>
    <div class="row stack fb-diag" id="fbDiagBox" ${diagOpen ? '' : 'hidden'}><pre id="fbDiagText">读取中…</pre></div>
    <div class="row"><div class="txt"><small>发出后开发者会第一时间看到</small></div>
      <div class="ctl"><button class="primary" data-action="fbSend" ${sending ? 'disabled' : ''}>${sending ? '发送中…' : '发送'}</button></div></div>
  </div>
  <div class="group-title" style="margin-top:18px">我发过的反馈</div>
  <div class="group" id="fbHistory">${historyHtml()}</div>`;
}

function rerenderHistory() {
  const h = $('fbHistory'), w = $('fbNoTarget');
  if (h) h.innerHTML = historyHtml();
  if (w) w.hidden = configured;
}

export async function loadFeedback() {
  try { const r = await getJSON('/api/feedback'); items = r.items; configured = r.configured; } catch { return; }
  rerenderHistory();
}

export function initFeedback() {
  actions({
    fbKind: btn => {
      kind = btn.dataset.val;
      btn.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
      segmented(btn.parentElement);
    },
    fbDiag: async (a, e) => {
      e?.preventDefault();
      diagOpen = !diagOpen;
      $('fbDiagBox').hidden = !diagOpen;
      a.textContent = diagOpen ? '收起' : '看看会发什么';
      if (diagOpen) $('fbDiagText').textContent = (await getJSON('/api/feedback/diag').catch(() => ({text: '读取失败'}))).text;
    },
    fbSend: async btn => {
      const text = $('fbText').value.trim();
      if (!text) { toast('先写一下想说的'); $('fbText').focus(); return; }
      sending = true; btn.disabled = true; btn.textContent = '发送中…';
      try {
        const r = await postJSON('/api/feedback', {kind, text, contact: $('fbContact').value, include_diag: $('fbDiagOn').checked});
        toast(r.status === 'sent' ? '已送达，谢谢你的反馈！' : '暂时没发出去，已存好，联网后会自动重发');
        $('fbText').value = '';
        items = [r, ...items.filter(x => x.id !== r.id)];
        rerenderHistory();
      } catch { /* api() 已经弹了提示 */ } finally {
        sending = false; btn.disabled = false; btn.textContent = '发送';
      }
    },
    fbRetry: async btn => {
      btn.disabled = true;
      try {
        const r = await api('/api/feedback/retry');
        items = r.items; rerenderHistory();
        toast(r.sent ? `重发成功 ${r.sent} 条` : '还是没发出去，稍后会再试');
      } catch { btn.disabled = false; }
    },
  });
}
