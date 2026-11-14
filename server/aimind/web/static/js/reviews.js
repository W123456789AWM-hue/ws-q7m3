// 复盘卡片 + 整场总复盘
import {$, actions, el, esc} from './dom.js';
import {api} from './api.js';
import {fmtSec, md} from './format.js';
import {state} from './state.js';

const KIND = {realtime: '实时复盘', periodic: '定时复盘', manual: '手动复盘', final_part: '收尾复盘'};
const list = (items, fmt = x => esc(x)) => (items || []).map(x => `<li>${fmt(x)}</li>`).join('');
const sec = (cls, title, items, fmt) => items?.length ? `<div class="sec ${cls}"><h4>${title}</h4><ul>${list(items, fmt)}</ul></div>` : '';
const obj = (x, f) => typeof x === 'object' && x ? f(x) : esc(x);

function body(r) {
  const a = r.analysis || {};
  if (r.status === 'analyzing') {
    return r.sec != null ? `<p class="thinking">AI 正在听 ${fmtSec(r.sec)} 的录音</p>` : `<p class="thinking">AI 正在思考 ${r.chars} 字的内容</p>`;
  }
  if (r.status === 'error') return `<p style="color:var(--red)">${esc(r.error)}</p><button data-action="retryReview" data-arg="${r.id}">重试</button>`;
  if (a.trivial) return `<p class="hint">这段时间以闲聊或噪音为主。${esc(a.summary || '')}</p>`;
  return `<p class="sum">${esc(a.summary)}</p>
    <div class="secs">
      ${sec('blind', '你可能没注意到', a.blind_spots)}
      ${sec('need', '潜在需求', a.latent_needs, x => obj(x, v => `${esc(v.need)}<div class="ev">依据：${esc(v.evidence)}</div>`))}
      ${sec('div', '发散联想', a.divergent, x => obj(x, v => `<span class="tag">${esc(v.angle)}</span>${esc(v.idea)}`))}
      ${sec('sug', '建议', a.suggestions, x => obj(x, v => `<span class="tag pri-${esc(v.priority)}">${esc(v.priority)}</span>${esc(v.text)}`))}
      ${sec('voice', '从语气里听出来的', a.voice_cues)}
      ${sec('q', '值得追问自己', a.questions)}
      ${sec('chg', '和上次复盘相比', a.changes)}
    </div>
    ${a.topics?.length ? `<details><summary>话题时间线</summary><ul>${list(a.topics, x => obj(x, v => `${esc(v.time)} ${esc(v.topic)}：${esc(v.gist)}`))}</ul></details>` : ''}`;
}

export function reviewCard(r, cls = '') {
  const a = r.analysis || {};
  const badge = {analyzing: 'AI 思考中', error: '复盘失败'}[r.status];
  const raw = r.text ? `<details><summary>${r.sec != null ? 'AI 听写的原文' : '这次复盘用到的原文'}（${r.chars} 字）</summary>
    <div style="white-space:pre-wrap">${esc(r.text)}</div></details>` : '';
  return `<article class="card ${cls}" data-rid="${r.id}">
    <div class="hd"><b>${esc(a.title || KIND[r.kind] || '复盘')}</b><small>${esc(r.from_clock)}–${esc(r.to_clock)} · ${KIND[r.kind] || ''}</small>
      ${badge ? `<span class="badge ${r.status === 'error' ? 'error' : 'analyzing'}">${badge}</span>` : ''}</div>
    ${body(r)}${raw}</article>`;
}

const EMPTY = `<div class="empty"><div class="orb"></div>
  <p>点上方「电脑麦克风录音」，或者在手机 App 里开始录音（几台设备可以同时录）。</p>
  <p class="sub">AI 会直接<b>听录音</b>：写出听写文字，指出你没注意到的点、潜在需求，还有从语气里听出来的东西。</p></div>`;

export function renderReviews() {
  const box = $('reviews'), s = state.session;
  if (!s) { box.innerHTML = EMPTY; return; }
  if (!(s.reviews || []).length) {
    box.innerHTML = s.paragraphs?.length ? '<p class="empty">还没到复盘的时候。想马上看，点顶部「立即复盘」。</p>' : EMPTY;
    return;
  }
  box.innerHTML = [...s.reviews].reverse().map((r, i) => reviewCard(r, i < 6 ? 'enter' : '')).join('');
  box.querySelectorAll('.card.enter').forEach((c, i) => { c.style.animationDelay = `${i * 40}ms`; });
}

/** 只替换变了的那一张：新卡片从上面滑入，更新的卡片闪一下边框 */
export function upsertReview(r) {
  const box = $('reviews');
  const old = box.querySelector(`.card[data-rid="${r.id}"]`);
  if (!old) {
    if (!box.querySelector('.card')) box.innerHTML = '';
    box.prepend(el(reviewCard(r, 'enter')));
    return;
  }
  old.replaceWith(el(reviewCard(r, 'update')));
}

export function renderSummary() {
  const s = state.session;
  $('summaryBox').innerHTML = s?.summary
    ? `<article class="card md enter" id="summary"><div class="hd"><b>整场总复盘</b><small>SESSION REVIEW</small></div>${md(s.summary)}</article>` : '';
}

export function initReviews() {
  actions({retryReview: btn => api('/api/retry_review/' + btn.dataset.arg)});
}
