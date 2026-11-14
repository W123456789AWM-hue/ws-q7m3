// 实时消息（WebSocket）：服务端推什么，这里分发给对应模块
import {$} from './dom.js';
import {addCaption, renderAll, renderHeader, renderNext, setLevel} from './live.js';
import {toast} from './layers.js';
import {upsertReview} from './reviews.js';
import {emit, state} from './state.js';

function handle(m) {
  switch (m.type) {
    case 'level': return setLevel(m.db);
    case 'error': return toast('⚠ ' + m.msg, 8000);
    case 'status': return toast(m.msg);
    case 'model': $('modelMsg').textContent = m.msg; $('modelMsg').title = m.msg; if (m.done) toast(m.msg); return;
    case 'nas': $('nasInfo').textContent = m.msg; return;
    case 'eval': return emit('eval', m);
    case 'report': return emit('report', m);
    case 'next_review': state.nextReview = m.data; return renderNext();
    case 'state':
      Object.assign(state, {recording: m.recording, nextReview: m.next_review, micOn: !!m.mic_on, devices: m.devices || []});
      if (!state.viewingHistory) { state.session = m.session; renderAll(); }
      renderHeader(); renderNext();
      return;
  }
  const s = state.session;
  if (state.viewingHistory || !s) return;
  if (m.type === 'caption') {
    let p = s.paragraphs.find(x => x.id === m.pid);
    if (!p) { p = {id: m.pid, start_clock: m.clock, text: '', segments: [], status: 'live', device_name: m.device_name}; s.paragraphs.push(p); }
    p.text += m.text;
    p.device_name ||= m.device_name;
    p.segments.push({clock: m.clock, text: m.text, pid: m.pid, sec: m.sec});
    addCaption(m);
  } else if (m.type === 'review') {
    s.reviews ||= [];
    const i = s.reviews.findIndex(x => x.id === m.data.id);
    if (i >= 0) s.reviews[i] = m.data; else s.reviews.push(m.data);
    upsertReview(m.data);
    if (m.data.status !== 'analyzing') emit('usage-changed');
  }
}

export function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onmessage = e => handle(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}
