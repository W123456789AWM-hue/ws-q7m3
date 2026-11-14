# iPhone 版怎么装

App 没有上架 App Store，苹果要求装到 iPhone 上的程序必须签名。有两种办法：

| | 免费 Apple ID 自签 | 付费开发者账号（每年 688 元） |
|---|---|---|
| 用哪个安装包 | `AIMind-<版本>-ios-unsigned.ipa` | `AIMind-<版本>-ios.ipa`（云端自动签好） |
| 有效期 | **7 天**，到期要重签（数据不丢） | 1 年（跟描述文件一起到期） |
| 需要做的 | 每次装 / 续签时用电脑签一下 | 一次性把证书放进 GitHub，以后每个版本自动签好 |
| 限制 | 一个免费 Apple ID 同时最多 3 个自签 App | 每年最多登记 100 台设备 |

安装包都在发布页：<https://github.com/W123456789AWM-hue/aimind-releases/releases/latest>

---

## 一、免费 Apple ID 自签（Sideloadly）

**准备**（Windows 才需要）：从苹果官网下载安装 **iTunes** 和 **iCloud**。不要用微软商店里的版本，Sideloadly 认不到。Mac 不用装。

1. 到 <https://sideloadly.io> 下载并安装 Sideloadly（Windows / Mac 都有）。
2. 用数据线把 iPhone 连到电脑，手机上点「信任此电脑」。
3. 打开 Sideloadly：
   - 把 `AIMind-<版本>-ios-unsigned.ipa` 拖进窗口；
   - 「Apple account」填你的 Apple ID（建议用一个不常用的小号）；
   - 点 **Start**，按提示输入 Apple ID 密码和手机上收到的验证码。密码只发给苹果，不经过本程序。
4. 手机上第一次打开前：
   - **设置 → 通用 → VPN 与设备管理**，点你的 Apple ID，再点「信任」；
   - iOS 16 及以上还要打开 **设置 → 隐私与安全性 → 开发者模式**，按提示重启。
5. **7 天后 App 会打不开**：重复第 3 步再装一次就好（同一个 Apple ID 重签，设置和数据都还在）。
   Sideloadly 有「Automatically refresh」选项，电脑开着并且和手机在同一个 Wi-Fi 时会自动续签。

更新版本：下载新的 `ios-unsigned.ipa`，按第 3 步装上即可，会覆盖旧版、保留数据。

---

## 二、付费开发者账号：云端自动签名

配好一次以后，每次发布都会多出一个签好名的 `AIMind-<版本>-ios.ipa`，直接装，一年内不用管。
下面的事都要你本人在苹果网站和 GitHub 上操作（涉及账号、证书和密码）。

### 1. 在苹果开发者网站准备三样东西

登录 <https://developer.apple.com/account> → 「证书、标识符和描述文件」：

1. **App ID**（标识符 → ＋ → App IDs → App）：
   描述随便填，Bundle ID 选 Explicit，填一个你自己的，比如 `com.你的名字拼音.aimind`。不用勾任何功能。
2. **登记你的 iPhone**（设备 → ＋）：
   需要手机的 UDID：把手机连到 Mac 的「访达」里点手机型号那一行，或者在 Windows 上用爱思助手查看。
3. **证书**（证书 → ＋ → Apple Distribution）：
   要上传一个证书请求文件（CSR）。在 Mac 上打开「钥匙串访问」→ 菜单「钥匙串访问 → 证书助理 → 从证书颁发机构请求证书」，
   填邮箱、选「存储到磁盘」，然后上传。下载得到的 `.cer` 双击装进钥匙串。
   再在钥匙串里找到这个证书（展开能看到私钥），右键 →「导出」→ 格式选 `.p12`，**设一个密码**，记下来。
4. **描述文件**（描述文件 → ＋ → Ad Hoc）：选第 1 步的 App ID、第 3 步的证书、第 2 步的设备 → 下载 `.mobileprovision`。

### 2. 转成文字，放进 GitHub 仓库密钥

先把两个文件转成 base64 文字。

在 Mac「终端」里运行：

```bash
base64 -i 证书.p12 | pbcopy
```

上面这条会把结果复制到剪贴板，去粘贴到 GitHub。然后对描述文件做同样的事：

```bash
base64 -i 描述文件.mobileprovision | pbcopy
```

如果用 Windows，在 PowerShell 里运行：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("证书.p12")) | Set-Clipboard
```

然后打开 <https://github.com/W123456789AWM-hue/aimind/settings/secrets/actions>，点「New repository secret」，加三个：

| 名字 | 内容 |
|---|---|
| `IOS_P12_BASE64` | 证书 `.p12` 的 base64 |
| `IOS_P12_PASSWORD` | 导出 `.p12` 时设的密码 |
| `IOS_PROFILE_BASE64` | 描述文件 `.mobileprovision` 的 base64 |

**这几样不要发给任何人，也不要提交进仓库。**

### 3. 之后

- 下一次发布时，云端会自动签名，发布页多出 `AIMind-<版本>-ios.ipa`。
  Bundle ID 直接从描述文件里读，不用改代码。
- 安装方法任选一个：
  - Windows：爱思助手 →「应用游戏 → 导入安装」；
  - Mac：在「访达」里把 ipa 拖到手机上；
  - 也可以用 Sideloadly 的普通安装模式，它不会重新签名。
- 要加一台新 iPhone：先在苹果网站登记设备，再重新生成描述文件，然后更新 `IOS_PROFILE_BASE64`。
- 证书或描述文件过期（一年）：重新生成，再更新对应的密钥。

签名用的脚本是 `mobile/scripts/sign_ios.sh`。从免费自签换到付费签名后，Bundle ID 不一样，手机上会变成两个 App。
设置要在新的那个里重新连一次电脑；复盘记录都在电脑上，不受影响。
