// 入口：把各个模块装起来。每个模块只管自己那一块界面，通过 data-action 注册操作、通过 state 的事件通信。
//
//   js/dom.js        DOM 小工具 + 事件分发（data-action / data-change / data-input）
//   js/anim.js       过渡动画：浮层开关、内容切换、高亮
//   js/layers.js     浮层管理：抽屉、设置弹窗、菜单、提示条
//   js/api.js        和服务端通信
//   js/state.js      界面状态 + 事件
//   js/format.js     格式化、Markdown
//   js/live.js       顶栏、听写、录音操作、历史 ↔ 当前
//   js/reviews.js    复盘卡片
//   js/panels.js     设备连接、历史、复盘报告
//   js/evalset.js    识别测试
//   js/usage.js      AI 用量
//   js/update.js     在线更新（顶栏提示 + 设置里的「软件更新」）
//   js/settings/     设置：schema.js（设置项清单）+ view.js（界面、搜索、自动保存）
//   js/ws.js         实时消息分发
//   js/sound.js      按钮音效
import {initActions} from './js/dom.js';
import {initLayers} from './js/layers.js';
import {initLive, renderAll, renderHeader} from './js/live.js';
import {initReviews} from './js/reviews.js';
import {initPanels} from './js/panels.js';
import {initEval} from './js/evalset.js';
import {initUsage} from './js/usage.js';
import {initUpdate} from './js/update.js';
import {initFeedback} from './js/feedback.js';
import {initSettings} from './js/settings/view.js';
import {connect} from './js/ws.js';
import {initSound} from './js/sound.js';

initActions();
initSound();
initLayers();
initLive();
initReviews();
initPanels();
initEval();
initSettings();
initUsage();
initUpdate();
initFeedback();
renderAll();
renderHeader();
connect();
