// 格式化：时长、数量、日期、极简 Markdown
import {esc} from './dom.js';

export const fmtSec = sec => { sec = Math.round(sec || 0); return sec >= 60 ? `${Math.floor(sec / 60)} 分 ${sec % 60} 秒` : `${sec} 秒`; };
export const kfmt = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0);
export const voiceLabel = sec => sec ? `◉ ${Number(sec).toFixed(1)}s 语音` : '';

export function ago(t) {
  if (!t) return '从未';
  const s = Math.round(Date.now() / 1000 - t);
  return s < 60 ? '刚刚' : s < 3600 ? `${Math.floor(s / 60)} 分钟前` : s < 86400 ? `${Math.floor(s / 3600)} 小时前` : `${Math.floor(s / 86400)} 天前`;
}

export function today() {
  const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
export function md(src) {
  const out = []; let inList = false;
  for (const raw of String(src || '').split('\n')) {
    const l = raw.trimEnd();
    const li = l.match(/^\s*[-*]\s+(\[[ x]\]\s+)?(.*)$/);
    if (li) { if (!inList) { out.push('<ul>'); inList = true; } out.push(`<li>${li[1] ? '☐ ' : ''}${inline(li[2])}</li>`); continue; }
    if (inList) { out.push('</ul>'); inList = false; }
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    if (h) out.push(`<h3>${inline(h[2])}</h3>`);
    else if (l.trim()) out.push(`<p>${inline(l)}</p>`);
  }
  if (inList) out.push('</ul>');
  return out.join('');
}
