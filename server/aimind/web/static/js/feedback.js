// 用户反馈：设置「反馈」里写 → 电脑发到开发者的飞书群；发不出去会先存着，过一会儿自动重发
import {$, actions, onChange, esc, icon} from './dom.js';
import {getJSON, postJSON, api} from './api.js';
import {segmented} from './anim.js';
import {toast} from './layers.js';

let kind = 'bug', items = [], configured = true, diagOpen = false, sending = false;
let images = [], maxImages = 3;   // 附图（选填）：压缩后的 data URL

/** 图片压缩成长边不超过 1600 的 JPEG（截图几 MB → 几百 KB），GIF 保持原样 */
async function shrink(file) {
  const raw = await new Promise((ok, bad) => {
    const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r.readAsDataURL(file);
  });
  if (file.type === 'image/gif') return raw;
  const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = raw; });
  const k = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
  const c = document.createElement('canvas');
  c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
  const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);   // 透明 PNG 转 JPEG 时别变黑
  g.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', 0.85);
}

async function addImages(files) {
  const list = [...files].filter(f => f.type.startsWith('image/'));
  if (!list.length) return;
  const room = maxImages - images.length;
  if (room <= 0) { toast(`附图最多 ${maxImages} 张`); return; }
  if (list.length > room) toast(`附图最多 ${maxImages} 张，多的没加上`);
  for (const f of list.slice(0, room)) {
    try { images.push(await shrink(f)); } catch { toast('这张图片读不出来，换一张试试'); }
  }
  renderImages();
}

function imagesHtml() {
  return images.map((src, i) => `<div class="fb-thumb"><img src="${src}" alt="附图 ${i + 1}">
      <button type="button" class="fb-del" data-action="fbDelImg" data-arg="${i}" title="去掉这张">${icon('x')}</button></div>`).join('')
    + (images.length < maxImages ? `<button type="button" class="fb-add" data-action="fbPick">＋ 添加图片</button>` : '');
}

function renderImages() {
  const box = $('fbImgs');
  if (box) box.innerHTML = imagesHtml();
}
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
        ${x.images?.length ? `<small>附图 ${x.images.length} 张</small>` : ''}
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
    <div class="row stack"><div class="txt"><b>附图 <span class="fb-opt">选填</span></b>
        <small>截图能让开发者更快看懂问题，最多 ${maxImages} 张；也可以在上面的输入框里直接粘贴截图</small></div>
      <div class="ctl fb-imgs" id="fbImgs">${imagesHtml()}</div>
      <input type="file" id="fbFile" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden data-change="fbFile"></div>
    <div class="row"><div class="txt"><b>联系方式 <span class="fb-opt">选填</span></b><small>微信 / 邮箱，方便回复你</small></div>
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
  try {
    const r = await getJSON('/api/feedback');
    items = r.items; configured = r.configured; maxImages = r.max_images || maxImages;
  } catch { return; }
  rerenderHistory();
}

export function initFeedback() {
  onChange({fbFile: inp => { addImages(inp.files); inp.value = ''; }});
  // 在反馈输入框里粘贴截图
  document.addEventListener('paste', e => {
    if (e.target?.id !== 'fbText') return;
    const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); addImages(files); }
  });
  actions({
    fbPick: () => $('fbFile').click(),
    fbDelImg: btn => { images.splice(+btn.dataset.arg, 1); renderImages(); },
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
        const r = await postJSON('/api/feedback', {kind, text, contact: $('fbContact').value,
          include_diag: $('fbDiagOn').checked, images});
        toast(r.status === 'sent' ? '已送达，谢谢你的反馈！' : '暂时没发出去，已存好，联网后会自动重发');
        $('fbText').value = '';
        images = []; renderImages();
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
