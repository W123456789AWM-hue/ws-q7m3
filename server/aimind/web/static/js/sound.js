// 按钮音效：点按钮、开关、分段按钮、菜单项时轻轻“嗒”一声（设置 → 通用 → 声音 可关）。
// 用 Web Audio 播放：第一次点击时才创建（浏览器要求有用户操作后才能出声），之后每次几乎零延迟。
import {on} from './state.js';
import {getJSON} from './api.js';

let ctx = null, buf = null, loading = null, last = 0;
export let clicksOn = true;
let volume = 1;            // 设置 → 声音 → 按钮音效音量

function apply(cfg) {
  clicksOn = cfg?.sound_clicks !== false;
  volume = Math.min(1.5, Math.max(0.1, Number(cfg?.click_volume) || 1));
}

const TARGET = 'button, [data-action], [role=button], .switch, input[type=checkbox], select, summary';

async function load() {
  ctx ||= new (window.AudioContext || window.webkitAudioContext)();
  const data = await (await fetch(new URL('../sounds/click.wav', import.meta.url))).arrayBuffer();
  buf = await new Promise((ok, bad) => ctx.decodeAudioData(data, ok, bad));
}

export function playClick() {
  if (!clicksOn) return;
  const now = performance.now();
  if (now - last < 40) return;          // 连点 / 一次点击触发多个事件时只响一声
  last = now;
  if (!buf) { (loading ||= load().catch(() => { loading = null; })).then(() => buf && playClick()); return; }
  if (ctx.state === 'suspended') ctx.resume();
  const src = ctx.createBufferSource();
  const gain = ctx.createGain();
  gain.gain.value = 0.55 * volume;
  src.buffer = buf;
  src.playbackRate.value = 0.97 + Math.random() * 0.06;   // 每次音高略有不同，听起来不机械
  src.connect(gain).connect(ctx.destination);
  src.start();
}

export function initSound() {
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const el = e.target.closest(TARGET);
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    if (el.matches('input[type=text], textarea')) return;
    playClick();
  }, {capture: true, passive: true});
  // 用键盘按回车 / 空格触发按钮时也响
  document.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.closest?.('button, [role=button]')) playClick();
  }, {capture: true, passive: true});
  on('config', apply);
  getJSON('/api/config').then(apply).catch(() => {});
}
