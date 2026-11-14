# AI 录音思考助手

全天录音 → AI 听录音做发散复盘（盲点、潜在需求、发散联想、建议、追问）→ 结果存电脑、同步 NAS，手机和电脑都能看。
用户是中文使用者：**界面文字、注释、提交说明、回复都用简体中文**。

## 仓库结构

```
server/                 电脑端（Python 3.10+，FastAPI）。在这里运行命令
  aimind/
    config.py           设置项 DEFAULTS（加设置只加一行）；数据目录 = $AIMIND_DATA 或 server/data
    engine.py           核心：多设备录音 → 切句 → 段落 → 复盘调度 → 收尾。所有状态在这里
    devices.py          录音设备上传：落盘到 data/inbox → 按录音时间喂给 engine；设备注册表
    session.py          一场录音的数据结构、session.json、report.md
    nas.py              同步到 NAS
    evalset.py          识别测试集（本地识别模式用）
    audio/              vad.py 切句（每台设备一个 Segmenter，带录音时钟）、wavstore.py、mic.py、adpcm.py
    review/             prompts.py 提示词、llm.py 文字 AI、listen.py AI 听录音（gpt-audio）、daily.py 日复盘、usage.py 用量统计
    stt/                本地识别（SenseVoice / Paraformer / Whisper），只在 review_input=text 时用
    web/                app.py（口令、WebSocket）、hub.py（单例）、routes_*.py（API）、static/（界面）
  desktop_app.py        打包成桌面程序时的入口（自带窗口 pywebview；冻结后数据在 %APPDATA%/AIMind 或 ~/Library/Application Support/AIMind）
  splash_win.py         Windows 启动动画：系统分层窗口逐帧播放 static/splash.webp（真透明）；Mac 用 static/splash.html + pywebview 透明窗口
  packaging/            make_splash.py（白底视频 → 透明 60 帧 + 鸣谢文字）、aimind.spec（PyInstaller 主程序）、
                        setup_app.py + setup_ui.html + setup.spec（Windows 安装程序，pywebview 界面，装到 %LOCALAPPDATA%\Programs\AIMind，
                        注册到「设置 → 应用」，卸载脚本 uninstall.ps1）、build_windows.bat/.ps1、build_mac.sh
  tests/                pytest：test_units.py 单元，test_e2e.py 多设备全流程（AI 用假接口）
  tools/                mock_openai.py 假 OpenAI；device_sim.py 模拟录音设备
mobile/                 手机 App（Flutter）：只负责录音、上传、查看和改设置
  lib/core/             不依赖界面的逻辑：settings、api、uploader（切片暂存上传）、endpoints、adpcm
  lib/ui/               页面
  tool/core_check.dart  不用手机的联调：按手机方式上传真实录音给运行中的电脑端并检查结果
scripts/package.sh      打包给用户的 zip
.github/workflows/build-all.yml  云端打包四个平台（Windows exe、Mac dmg、安卓 APK、iPhone IPA）
docs/iphone-install.md  iPhone 安装：免费 Apple ID 自签 / 付费证书云端签名（mobile/scripts/sign_ios.sh，密钥 IOS_P12_BASE64 等）
```

## 版本与在线更新

- 版本号只写在 `server/aimind/version.py` 的 `VERSION`（打包配置、安装程序、手机 App 都从这里 / 标签来）。
- **发布新版本**：改 VERSION → 提交（提交说明就是给用户看的更新说明）→ `git tag v<版本> && git push origin v<版本>`。
  云端 `.github/workflows/build-all.yml` 打包四个平台，`release` 任务用 `packaging/make_release.py` 生成并签名 `latest.json`，
  上传到公开的发布仓库 `aimind-releases`（只放安装包）。标签和 VERSION 不一致会直接失败。
- 签名：Ed25519（`aimind/ed25519.py` 纯 Python）。公钥写在 version.py；私钥在 GitHub 仓库密钥 `UPDATE_SIGNING_KEY`，
  本机备份在 `%LOCALAPPDATA%\ai_mind_build\release-signing-key.txt`。**私钥丢了 = 已装的程序再也收不到更新**，不要提交进仓库。
- 程序端 `aimind/updater.py`：检查（验签）→ 下载（核对大小 + sha256）→ Windows 调安装程序 `--silent --upgrade --wait-pid --relaunch`、
  Mac 用脚本替换 .app。录音中不更新。手机 App 通过电脑的 `/api/update/mobile`、`/api/update/file/…` 更新。
- 本机测试更新：设置项 `update_manifest_url` 指向自己搭的发布目录（见 tests/test_e2e.py 的 test_online_update_*）。

## 用户反馈

- 设置「反馈」（`js/feedback.js`）和手机 App 设置页（`feedback_section.dart`）→ `POST /api/feedback` → `aimind/feedback.py` 发到开发者的飞书群（自定义机器人，带签名）。
  手机不直接连飞书，由电脑转发（机器人地址只在电脑端程序里）。
- 机器人地址 / 签名密钥：GitHub 仓库密钥 `FEEDBACK_WEBHOOK` / `FEEDBACK_SECRET`，打包时 `aimind.spec` 写进程序；
  本机打包用 `%LOCALAPPDATA%\ai_mind_build\feedback_target.json`；测试用环境变量 `AIMIND_FEEDBACK_WEBHOOK` / `AIMIND_FEEDBACK_SECRET`。**不要提交进仓库。**
- 发不出去存 `data/feedback/`，每 5 分钟重发。诊断信息经 `redact()` 抹掉密钥，不带录音和复盘内容。
- 附图（选填，最多 3 张，界面先压到长边 1600）：自定义机器人不能传图，另用飞书「企业自建应用」（权限 `im:resource`，开启机器人能力）
  上传拿 image_key 放进卡片；密钥 `FEEDBACK_APP_ID` / `FEEDBACK_APP_SECRET`（测试用 `AIMIND_FEEDBACK_APP_ID` / `_SECRET`）。
  没配或卡片不收图时文字照发，卡片里注明，图片留在 `data/feedback/<编号>/`。

## 复盘层级

- 小复盘（阶段复盘）：录音中按 `review_mode`（realtime / interval）触发，engine.py。
- 大复盘：整场总复盘（`session_review`，engine._finish）→ 日复盘 → 月复盘 → 年复盘（review/daily.py）。
  逐级汇总：月复盘读日复盘（没有就用当天阶段复盘的 `brief_digest`），年复盘读月复盘（缺的先补）。
  自动时机在 `daily.due_reports()`（含错过后补做），接口 `/api/report?period=day|month|year&key=`；旧的 `/api/daily` 保留给旧版 App。

## 数据流（改 engine 前先读）

- 设备 → `POST /api/phone/chunk?device&name&stream&seq&start&dur&silent&enc` → `devices.py` 落盘 → `engine.feed(dev, pcm, start)` / `engine.skip` / `engine.device_stop`。
- 每台设备一个 `Track`（Segmenter + WavStore + 当前段落）；几台设备共用一个 `Session`。段落带 `device`/`device_name`。
- `review_input=audio`：每句存成 `clips/*.pcm`，复盘时按段落分组发给 gpt-audio，返回的听写文字填回段落，片段删除。
  `review_input=text`：每句先本地识别成文字。
- 复盘按“录音时间”调度（补传的录音也准）；segment 上的 `rv` 表示被第几次复盘用过。
- 所有设备停了 / 长时间没数据 / 点「结束本场」/ 过零点 → `_detach_and_finish` 后台收尾，新录音开新的一场。
- 锁顺序：`feed_lock` → `lock`，不要反过来。

## 兼容性约定

- 手机 API 只加不改：旧版 App 不带 `device` 参数也要能用（当作设备 `phone`，名字“手机”）。
- `session.json` 只加字段；旧数据（v0.8：`part` 而不是 `file`、没有 `device`）要能读。
- 设置项改名要在 `config.load()` 里迁移（看 `config_version`）。

## 常用命令（在 server/ 下）

```bash
python -m pytest -q                       # 全部测试，约 10 秒
ruff check aimind tools tests             # 风格检查
python run.py                             # 启动（AIMIND_NO_BROWSER=1 不开窗口，AIMIND_DATA=/tmp/x 用临时数据）
python -m tools.mock_openai               # 假 OpenAI：设置里接口地址填 http://127.0.0.1:9100/v1，Key 填 sk-test
python -m tools.device_sim --device a --name 客厅手机 [--adpcm]
```

手机端：`cd mobile && dart analyze lib tool`；联调：先启动电脑端，再 `dart tool/core_check.dart <16k单声道.wav> http://<电脑IP>:8765 <口令>`
（要用局域网 IP，不要用 127.0.0.1：本机访问不检查口令）。打包 APK 用 `mobile/build_android.bat`（Windows）。
`record` 插件及其各平台实现在 pubspec.yaml 里固定了版本（record_android 2.3.0 编译不过），升级前先实测能编译。
Windows 程序放在太深的路径（比如在 WinRAR 里直接双击）会报 DLL load failed“文件名或扩展名太长”：
desktop_app 会识别压缩软件临时目录并提示；给用户的推荐方式是安装程序。
Windows 上打包要放在短路径（`%LOCALAPPDATA%\ai_mind_build`），工程路径太深时 PortAudio 等 DLL 会加载失败（错误 0xce）。
电脑端独立程序：`server/packaging/build_windows.bat`（Windows）、`bash server/packaging/build_mac.sh`（Mac）。

## 省 token 的约定（改提示词前看）

- 提示词里固定不变的部分（系统提示、关于我、常用词、额外要求）放最前面，每次都变的（上次复盘、时间范围、内容）放后面——这样能命中提示缓存。
- 模型输出的 JSON 解析失败时用 `llm.repair_json`（只花文字 token），不要把录音重发一遍。
- 每次调用 AI 后 `usage.record()` 记一笔，界面状态栏和设置里能看到。

## 改代码的习惯

- 改完跑 `python -m pytest -q` 和 `ruff check`；改了上传协议或手机看到的数据，再跑 `core_check.dart`。
- 新功能先在 `tests/test_e2e.py` 里用 `DeviceSim` 写一个场景。
- 桌面程序的功能（如预览启动动画）由 desktop_app.py 注册到 `hub.desktop_hooks`，路由里调用；浏览器方式运行时为空。
  Mac 的启动动画是 splash.html（pywebview 本地 http 服务打开，ImageDecoder 逐帧调速）；Windows 是 splash_win.py。
- 界面是纯 HTML/JS（`web/static/`），不用构建（原生 ES 模块）；文字都是中文、面向非程序员。参考 Apple 设计，深浅色跟随系统。
  - `css/`：tokens.css（颜色、圆角、动画曲线，改主题只改这里）→ base → layout → components → settings → motion（所有过渡动画）。
  - `app.js` 只负责把 `js/` 下的模块装起来；每个模块管一块界面，`initXxx()` 里用 `actions({...})` 注册操作。
  - **不写内联 onclick**：元素标 `data-action="名字"`（参数放 `data-arg`）/ `data-change` / `data-input`，由 `js/dom.js` 统一分发。
  - 模块间通信用 `js/state.js` 的 `state` + `emit/on`，不要互相直接调渲染函数造成循环依赖。
  - 浮层（抽屉、设置弹窗、菜单、提示条）一律 `hidden` 起步，用 `js/anim.js` 的 `show/hide` 开关（带过渡）；换内容用 `swap()`。
  - 加设置项：`js/settings/schema.js` 加一行（分类、说明、`when` 条件、`adv` 高级、`kw` 搜索词）+ `config.py` 的 DEFAULTS。改了自动保存。
- 界面性能：列表整页渲染时拼好字符串一次放进去；实时消息只追加/替换变化的那一项（`addCaption`、`upsertReview`）。
- 不要替用户注册账号或填写 API Key；测试只用 `tools/mock_openai.py`。
