// 过渡动画：所有“窗口操作”（浮层开关、内容切换、高亮）都走这里，样式在 css/motion.css。
// 规则：打开 = 去掉 hidden → 下一帧加 data-open（触发 CSS 过渡）；关闭 = 去掉 data-open → 过渡结束再加 hidden。

const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const nextFrame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

/** 等元素的过渡 / 动画结束（最多 maxMs，防止事件丢了卡住） */
export function settled(el, maxMs = 520) {
  if (reduce()) return Promise.resolve();
  return new Promise(res => {
    let done = false;
    const end = e => { if (e && e.target !== el) return; if (done) return; done = true;
      el.removeEventListener('transitionend', end); el.removeEventListener('animationend', end); res(); };
    el.addEventListener('transitionend', end);
    el.addEventListener('animationend', end);
    setTimeout(end, maxMs);
  });
}

export const isOpen = el => !!el && el.hasAttribute('data-open');

export async function show(el) {
  if (!el || isOpen(el)) return;
  el.hidden = false;
  await nextFrame();
  el.setAttribute('data-open', '');
  return settled(el);
}

export async function hide(el) {
  if (!el || !isOpen(el)) return;
  el.removeAttribute('data-open');
  await settled(el);
  if (!el.hasAttribute('data-open')) el.hidden = true;   // 期间又被打开了就不隐藏
}

/** 内容切换：旧内容淡出 → render() 换内容 → 新内容淡入 */
export async function swap(el, render) {
  if (!el) return;
  if (reduce() || !el.childElementCount) { await render(); return; }
  el.classList.add('swap-out');
  await settled(el, 180);
  await render();
  el.classList.remove('swap-out');
  el.classList.remove('swap-in'); void el.offsetWidth; el.classList.add('swap-in');
}

/** 让元素重新播放一次某个动画 class（比如搜索命中的闪烁） */
export function replay(el, cls) {
  if (!el) return;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
  settled(el, 1700).then(() => el.classList.remove(cls));
}

/** 分段控件：滑块移到选中的按钮下面 */
export function segmented(box) {
  if (!box) return;
  let thumb = box.querySelector('.thumb');
  if (!thumb) { thumb = document.createElement('span'); thumb.className = 'thumb'; box.prepend(thumb); }
  const on = box.querySelector('button.on');
  if (!on) { thumb.style.width = '0'; return; }
  thumb.style.width = on.offsetWidth + 'px';
  thumb.style.transform = `translateX(${on.offsetLeft}px)`;
}
