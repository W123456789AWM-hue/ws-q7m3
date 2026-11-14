// AI 用量：底栏的一行摘要 + 设置里的明细
import {$, esc} from './dom.js';
import {getJSON} from './api.js';
import {fmtSec, kfmt} from './format.js';
import {emit, on, state} from './state.js';

export async function loadUsage() {
  try { state.usage = await getJSON('/api/usage'); } catch { return; }
  const t = state.usage.total;
  const hit = t.input ? Math.round(t.cached / t.input * 100) : 0;
  $('usageInfo').textContent = !t.calls ? '今日 AI · 0 次'
    : `今日 AI · ${t.calls} 次 · 输入 ${kfmt(t.input)}${hit ? `（缓存 ${hit}%）` : ''} · 输出 ${kfmt(t.output)}`
      + (t.audio_sec ? ` · 听 ${fmtSec(t.audio_sec)}` : '') + (t.saved_sec ? ` · 省静音 ${fmtSec(t.saved_sec)}` : '');
  emit('usage', state.usage);
}

export function usageHtml() {
  const t = state.usage?.total || {};
  const hit = t.input ? Math.round((t.cached || 0) / t.input * 100) : 0;
  const rows = Object.entries(state.usage?.models || {}).map(([m, x]) =>
    `<tr><td>${esc(m)}</td><td class="num">${x.calls}</td><td class="num">${kfmt(x.input)}</td><td class="num">${kfmt(x.cached)}</td><td class="num">${kfmt(x.output)}</td></tr>`).join('');
  return `<div class="stats">
      <div class="stat"><b>${t.calls || 0}</b><small>调用次数</small></div>
      <div class="stat"><b>${kfmt(t.input)}</b><small>输入 token</small></div>
      <div class="stat"><b>${hit}%</b><small>缓存命中（更便宜）</small></div>
      <div class="stat"><b>${kfmt(t.output)}</b><small>输出 token</small></div>
      <div class="stat"><b>${fmtSec(t.audio_sec)}</b><small>AI 听的录音</small></div>
      <div class="stat"><b>${fmtSec(t.saved_sec)}</b><small>去掉的静音</small></div></div>
    ${rows ? `<table class="tbl"><tr><th>模型</th><th>次数</th><th>输入</th><th>其中缓存</th><th>输出</th></tr>${rows}</table>` : ''}
    <div class="group-title">省 token 的建议</div>
    <ul class="tips">
      <li>小复盘选「自定义周期」并把间隔调长（30–60 分钟）：每次复盘都要带上固定的说明，次数越少越省。</li>
      <li>「新语音少于多少秒就跳过」调大一点，没怎么说话的时段就不会调用 AI。</li>
      <li>同一个房间只放一台设备录音；几台一起录，同一段话会被重复听好几遍。</li>
      <li>「关于我」「常用词」写精炼些：每次都会发送（放在最前面，能命中缓存，按半价或更低计费）。</li>
    </ul>`;
}

export function initUsage() {
  loadUsage();
  setInterval(loadUsage, 60000);
  on('usage-changed', loadUsage);
  on('report', loadUsage);
}
