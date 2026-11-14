// 设置项清单：加一个设置 = 在这里加一行（服务端 config.py 的 DEFAULTS 也要有同名的键）。
//
// 每一项：{k: 键, label: 名字, desc: 一句说明, type, options, when(cfg): 什么时候显示, adv: 收在「高级」里, kw: 额外的搜索词}
// type：select / seg（分段按钮）/ bool（开关）/ text / password / number / time / textarea / mic（麦克风列表）
//       test（测试按钮）/ preview（预览启动动画）/ usage（用量面板）/ update（软件更新）/ theme（外观，只存在本机浏览器里）

const audioMode = c => (c.review_input || 'audio') === 'audio';
const textMode = c => c.review_input === 'text';
const interval = c => (c.review_mode || 'interval') !== 'realtime';
const realtime = c => c.review_mode === 'realtime';

export const CATEGORIES = [
  {id: 'general', name: '通用', icon: 'user', color: '#8e8e93', groups: [
    {title: '软件更新', items: [
      {k: 'update', label: '软件更新', type: 'update', kw: '版本 升级 新版本 在线更新 下载'},
      {k: 'update_auto_check', label: '自动检查新版本', desc: '启动时和每 6 小时检查一次；有新版本时顶栏会提示，不会自动安装', type: 'bool', kw: '升级 版本'},
      {k: 'update_mirror', label: '下载镜像', desc: '连不上 GitHub 时填，比如 https://ghproxy.net/（会加在下载地址前面）', type: 'text', adv: true, kw: '代理 加速 github'},
    ]},
    {title: '外观', items: [
      {k: 'theme', label: '外观', desc: '跟随系统的深色 / 浅色，或者固定一种', type: 'theme', kw: '主题 深色 浅色 暗色 夜间 dark light'},
    ]},
    {title: '让 AI 更懂你', items: [
      {k: 'about_me', label: '关于我', desc: '你的身份、正在做的事、长期目标。AI 据此推断你的潜在需求（强烈建议填写）', type: 'textarea', kw: '个人 简介 身份 目标'},
      {k: 'glossary', label: '常说的词 / 专有名词', desc: '人名、公司名、产品名、英文术语，用逗号隔开。听写时会按这些词来写', type: 'textarea', kw: '术语 词库 人名 识别错'},
      {k: 'extra_instructions', label: '额外要求', desc: '例如：多从商业角度想；建议要考虑我只有周末有空', type: 'textarea', kw: '提示词 要求'},
    ]},
  ]},

  {id: 'ai', name: 'AI 服务', icon: 'brain', color: '#bf5af2', groups: [
    {title: 'AI 听录音（OpenAI）', items: [
      {k: 'review_input', label: 'AI 怎么拿到内容', type: 'select', kw: '模式 本地识别 文字模式',
        options: [['audio', '直接听录音（推荐，能听出语气）'], ['text', '先在本机识别成文字再交给 AI']]},
      {k: 'audio_api_key', label: 'OpenAI API Key', desc: '在 platform.openai.com 的 API keys 页面生成', type: 'password', kw: '密钥 key openai'},
      {k: 'audio_model', label: '听录音的模型', desc: '默认 gpt-audio-1.5', type: 'text', when: audioMode, kw: 'gpt audio 模型'},
      {k: 'audio_trim_silence', label: '发送前去掉多余的静音', desc: '只去掉每句话前后的空白，省 10% 左右的 token，不影响内容', type: 'bool', when: audioMode, kw: '省钱 token 静音'},
      {k: 'audio', label: '测试 AI 能不能听到录音', type: 'test'},
      {k: 'audio_base_url', label: '接口地址', desc: '默认 https://api.openai.com/v1，一般不用改', type: 'text', adv: true, kw: 'url 代理 base'},
      {k: 'audio_max_min', label: '每次最多发送多少分钟录音', desc: '超过会分几次听再合并。报“录音太大”时调小', type: 'number', adv: true, when: audioMode},
    ]},
    {title: '文字 AI（总复盘、日 / 月 / 年复盘）', note: '不填就用上面的 OpenAI', items: [
      {k: 'llm_provider', label: '接口类型', type: 'select', kw: 'deepseek 硅基流动 claude anthropic ollama',
        options: [['openai', 'OpenAI 兼容（DeepSeek / 硅基流动 / 通义 / Ollama…）'], ['anthropic', 'Anthropic（Claude）']]},
      {k: 'llm_base_url', label: '接口地址', desc: '硅基流动 https://api.siliconflow.cn/v1；本机 Ollama http://127.0.0.1:11434/v1', type: 'text', kw: 'url'},
      {k: 'llm_api_key', label: 'API Key', desc: '本机 Ollama 不用填', type: 'password', kw: '密钥'},
      {k: 'llm_model', label: '模型名', desc: '从服务商的模型列表里复制完整名字', type: 'text'},
      {k: 'llm', label: '测试文字 AI', type: 'test'},
    ]},
    {title: '本地识别', when: textMode, items: [
      {k: 'stt_provider', label: '识别引擎', type: 'select', kw: 'sensevoice paraformer whisper 语音识别', options: [
        ['sensevoice', 'SenseVoice（带标点，约 240MB）'], ['paraformer', 'Paraformer（中文夹英文更稳）'],
        ['whisper', 'Whisper large-v3（最准，需 NVIDIA 显卡）'], ['api', '在线接口（会上传音频）']]},
      {k: 'stt', label: '检查 / 下载识别模型', type: 'test'},
      {k: 'stt_language', label: '语言', desc: 'zh 普通话；yue 粤语；en 英语；留空自动识别', type: 'text', adv: true},
      {k: 'local_whisper_model', label: 'Whisper 模型', desc: 'large-v3（最准）/ large-v3-turbo（快几倍）', type: 'text', adv: true,
        when: c => c.stt_provider === 'whisper'},
    ]},
  ]},

  {id: 'review', name: '复盘', icon: 'loop', color: '#ff9f0a', groups: [
    {title: '小复盘（录音过程中）', items: [
      {k: 'review_mode', label: '多久做一次', type: 'seg', kw: '实时 周期 间隔 频率',
        options: [['interval', '每隔 N 分钟'], ['realtime', '每说完一段']]},
      {k: 'review_interval_min', label: '每隔多少分钟', desc: '1–240。间隔越长越省 token；随时可以点「立即复盘」', type: 'number', when: interval, kw: '间隔 周期'},
      {k: 'review_min_sec', label: '新语音少于多少秒就跳过这一轮', desc: '没怎么说话的时段不浪费 AI 调用', type: 'number', when: c => interval(c) && audioMode(c), kw: '跳过 省钱'},
      {k: 'realtime_min_sec', label: '一段少于多少秒先攒着', desc: '太短的一两句并入下一段一起复盘', type: 'number', when: c => realtime(c) && audioMode(c)},
      {k: 'review_min_chars', label: '新内容少于多少字就跳过这一轮', type: 'number', when: c => interval(c) && textMode(c)},
      {k: 'realtime_min_chars', label: '一段少于多少字先攒着', type: 'number', when: c => realtime(c) && textMode(c)},
    ]},
    {title: '大复盘（总结）', items: [
      {k: 'session_review', label: '整场总复盘', type: 'select', kw: '总结 收尾',
        options: [['end', '一场录音结束时做'], ['off', '不做']]},
      {k: 'daily_review_time', label: '日复盘时间', desc: '每天几点做；留空不自动做。电脑没开错过了，下次打开会补上', type: 'time', kw: '每天 日报'},
      {k: 'monthly_review', label: '月复盘', type: 'select', kw: '每月 月报',
        options: [['month_end', '每月最后一天'], ['next_month', '下个月 1 号'], ['off', '不自动做']]},
      {k: 'yearly_review', label: '年复盘', type: 'select', kw: '每年 年报 年终',
        options: [['year_end', '12 月 31 日'], ['next_year', '次年 1 月 1 日'], ['off', '不自动做']]},
      {k: 'period_review_time', label: '月 / 年复盘时间', desc: '那天几点做；排在日复盘之后能用上当天的日复盘', type: 'time',
        when: c => c.monthly_review !== 'off' || c.yearly_review !== 'off'},
    ]},
  ]},

  {id: 'record', name: '录音', icon: 'wave', color: '#ff453a', groups: [
    {title: '录音', items: [
      {k: 'mic_device', label: '麦克风', desc: '这台电脑录音时用哪个麦克风', type: 'mic', kw: '话筒 输入设备'},
      {k: 'save_audio', label: '保存完整录音', desc: '每台设备每 30 分钟一个 WAV 文件', type: 'bool', kw: 'wav 存档'},
      {k: 'pause_close_sec', label: '停顿多少秒算新的一段', desc: '实时复盘以“说完一段”触发', type: 'number', adv: true, kw: '分段'},
      {k: 'vad_margin_db', label: '说话检测灵敏度（dB）', desc: '比环境噪音高多少算说话。环境吵调大（12–15），声音小调小（6–8）', type: 'number', adv: true, kw: 'vad 噪音 灵敏度'},
    ]},
  ]},

  {id: 'storage', name: '存储', icon: 'disk', color: '#0a84ff', groups: [
    {title: 'NAS', items: [
      {k: 'nas_dir', label: 'NAS 共享目录', desc: 'Windows 例：\\\\192.168.1.10\\recordings；Mac 例：/Volumes/recordings。留空只存本机', type: 'text', stack: true, kw: '同步 网络 共享 备份'},
      {k: 'nas', label: '测试 NAS 写入', type: 'test'},
    ]},
  ]},

  {id: 'desktop', name: '启动动画', icon: 'play', color: '#5e5ce6', groups: [
    {title: '桌面程序', items: [
      {k: 'splash_enabled', label: '打开程序时播放启动动画', type: 'bool', kw: '开机 动画 logo'},
      {k: 'splash_speed', label: '动画速度', desc: '1× 约 8 秒；点动画也能直接跳过', type: 'seg', when: c => c.splash_enabled !== false, kw: '快 慢',
        options: [[0.5, '0.5×'], [0.75, '0.75×'], [1, '1×'], [1.5, '1.5×'], [2, '2×'], [3, '3×']]},
      {k: 'splash', label: '预览启动动画', desc: '按上面的速度播放一遍', type: 'preview', when: c => c.splash_enabled !== false},
    ]},
  ]},

  {id: 'usage', name: '用量', icon: 'chart', color: '#30d158', groups: [
    {title: '今天的 AI 用量', items: [{k: 'usage', label: 'AI 用量', type: 'usage', kw: 'token 费用 花费 钱 统计'}]},
  ]},
];

/** 所有可搜索的条目（带上所属分类、分组） */
export const ALL = CATEGORIES.flatMap(c => c.groups.flatMap(g => g.items.map(f => ({...f, cat: c, group: g}))));
