// 界面状态（唯一一份）+ 简单的事件通知。模块之间不直接互相调用渲染，而是 emit / on。
export const state = {
  session: null,        // 当前显示的会话（实时的或历史的）
  recording: false,
  micOn: false,
  devices: [],          // 正在录音的设备 [{id,name,stopped,idle_sec}]
  nextReview: null,
  viewingHistory: false,
  usage: null,
  app: null,            // /api/app_info：是不是桌面程序、平台、端口
};

const subs = {};
export const on = (evt, fn) => (subs[evt] ||= []).push(fn);
export const emit = (evt, data) => (subs[evt] || []).forEach(fn => fn(data));
