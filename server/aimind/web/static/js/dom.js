// DOM 小工具 + 统一的事件分发。
// 页面上不写内联 onclick：元素标 data-action="名字"（点击）/ data-change / data-input，
// 各模块用 actions({名字: fn}) 注册处理函数，fn(元素, 事件) 被调用；元素上的 data-arg 是参数。

export const $ = id => document.getElementById(id);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

const registry = {click: {}, change: {}, input: {}};

/** 注册点击处理：actions({openSettings: () => ...}) */
export const actions = map => Object.assign(registry.click, map);
/** 注册 change / input 处理（对应 data-change / data-input） */
export const onChange = map => Object.assign(registry.change, map);
export const onInput = map => Object.assign(registry.input, map);

function dispatch(kind, attr) {
  return e => {
    const el = e.target.closest(`[${attr}]`);
    if (!el || el.disabled) return;
    const fn = registry[kind][el.getAttribute(attr)];
    if (!fn) return console.warn('没有注册的操作：', el.getAttribute(attr));
    Promise.resolve(fn(el, e)).catch(err => console.error(err));
  };
}

export function initActions() {
  document.addEventListener('click', dispatch('click', 'data-action'));
  document.addEventListener('change', dispatch('change', 'data-change'));
  document.addEventListener('input', dispatch('input', 'data-input'));
}

/** 把一段 HTML 字符串变成元素 */
export function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export const icon = name => `<svg><use href="#i-${name}"/></svg>`;
