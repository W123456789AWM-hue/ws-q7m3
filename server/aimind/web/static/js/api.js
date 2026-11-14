// 和电脑端服务通信
import {toast} from './layers.js';

/** POST（默认）或其他方法；失败时弹提示并抛错 */
export async function api(url, opts = {}) {
  const r = await fetch(url, {method: 'POST', ...opts});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.detail || ('出错 ' + r.status)); throw new Error(j.detail || r.status); }
  return j;
}

export const postJSON = (url, body) => api(url, {headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});

export async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}
