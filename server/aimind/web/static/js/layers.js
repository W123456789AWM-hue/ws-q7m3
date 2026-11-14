// 浮层管理：抽屉、设置弹窗、更多菜单、提示条。同一时间只开一个大浮层，Esc 关闭。
import {$, actions} from './dom.js';
import {hide, isOpen, show} from './anim.js';

let current = null;   // 当前打开的抽屉 / 弹窗

export async function openLayer(id) {
  closeMenu();
  const el = $(id);
  if (current && current !== el) await closeLayer(false);
  current = el;
  show($('mask'));
  await show(el);
}

export async function closeLayer(withMask = true) {
  const el = current;
  current = null;
  if (withMask) hide($('mask'));
  if (el) await hide(el);
}

export const layerOpen = id => isOpen($(id));

export function toggleMenu() { isOpen($('moreMenu')) ? closeMenu() : show($('moreMenu')); }
export function closeMenu() { hide($('moreMenu')); }

let toastTimer = 0;
export function toast(msg, ms = 3200) {
  const t = $('toast');
  t.textContent = msg;
  show(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => hide(t), ms);
}

export function initLayers() {
  actions({
    closeAll: () => closeLayer(),
    toggleMenu: (_, e) => { e.stopPropagation(); toggleMenu(); },
  });
  document.addEventListener('click', e => { if (!e.target.closest('.more')) closeMenu(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeMenu(); closeLayer(); }
  });
}
