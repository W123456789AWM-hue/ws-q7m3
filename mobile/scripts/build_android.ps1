# 一键打包安卓安装包（Windows）—— 由工程根目录的 build_android.bat 调用
# 缺什么装什么：Git、Flutter、JDK、Android SDK 都装到 %LOCALAPPDATA%\ai_mind_build 里，
# 不改系统环境变量，不需要管理员权限。已经装过的会直接复用。
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$proj = Split-Path -Parent $PSScriptRoot
$tc   = Join-Path $env:LOCALAPPDATA 'ai_mind_build'
$dl   = Join-Path $tc 'downloads'
$src  = Join-Path $tc 'src'
$out  = Join-Path $proj 'output'
foreach ($d in @($tc, $dl, $out)) { New-Item -ItemType Directory -Force $d | Out-Null }

function Step($m) { Write-Host "`n==== $m ====" -ForegroundColor Cyan }
function Has($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what 失败（退出码 $LASTEXITCODE）" } }

# 下载：依次尝试多个地址，支持断点续传
function Download($urls, $dst) {
  if (Test-Path $dst) { return }
  $part = "$dst.part"
  foreach ($u in $urls) {
    Write-Host "下载 $u"
    if (Has 'curl.exe') {
      & curl.exe -L --fail --retry 3 --retry-delay 3 --connect-timeout 20 -C - -o $part $u
      if ($LASTEXITCODE -eq 0) { Move-Item -Force $part $dst; return }
      if ($LASTEXITCODE -eq 33 -or $LASTEXITCODE -eq 36) {
        # 断点文件和服务器对不上：从头再来一次
        Remove-Item -Force $part -ErrorAction SilentlyContinue
        & curl.exe -L --fail --retry 3 --connect-timeout 20 -o $part $u
        if ($LASTEXITCODE -eq 0) { Move-Item -Force $part $dst; return }
      }
    } else {
      try {
        Invoke-WebRequest $u -OutFile $part -UseBasicParsing
        Move-Item -Force $part $dst
        return
      } catch { }
    }
    Write-Host '这个地址下载失败，换下一个…' -ForegroundColor Yellow
  }
  $name = Split-Path -Leaf $dst
  throw "下载失败：$name（请检查网络，或开/关一下代理后重试）"
}

function Unzip($zip, $dir) {
  New-Item -ItemType Directory -Force $dir | Out-Null
  & tar.exe -xf $zip -C $dir
  if ($LASTEXITCODE -ne 0) { Expand-Archive -Path $zip -DestinationPath $dir -Force }
  $global:LASTEXITCODE = 0
}

$ok = $false
$useMirror = $false
$flog = Join-Path $out 'flutter_log.txt'

# 运行命令，并把它的全部输出同时显示在窗口里、写进 flutter_log.txt（出错时把这个文件发给 Claude）
function RunLogged($cmdline, $what) {
  Add-Content -Path $flog -Value "`r`n>>> $cmdline" -Encoding UTF8
  & cmd.exe /c "$cmdline 2>&1" | ForEach-Object {
    Write-Host $_
    Add-Content -Path $flog -Value $_ -Encoding UTF8
  }
  if ($LASTEXITCODE -ne 0) { throw "$what 失败（退出码 $LASTEXITCODE）" }
}
$logFile = Join-Path $out 'build_log.txt'
try { Start-Transcript -Path $logFile -Force | Out-Null } catch { }

try {
  Write-Host 'AI 录音思考 · 一键打包安卓安装包' -ForegroundColor Green
  Write-Host "工具会装到：$tc"
  Write-Host '第一次运行需要下载约 3–5GB（Flutter、Android SDK 等），可能要半小时以上；以后再打包只要几分钟。'
  Write-Host '过程中会自动接受 Android SDK 的许可协议。'
  $ans = Read-Host '继续吗？(y/n)'
  if ($ans -ne 'y') { throw '已取消' }

  # ---------- 1. Git ----------
  Step '1/6 Git'
  if (-not (Has 'git')) {
    $gitDir = Join-Path $tc 'mingit'
    if (-not (Test-Path (Join-Path $gitDir 'cmd\git.exe'))) {
      $zip = Join-Path $dl 'mingit.zip'
      $urls = @(
        'https://registry.npmmirror.com/-/binary/git-for-windows/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip',
        'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip'
      )
      Download $urls $zip
      Unzip $zip $gitDir
    }
    $env:Path = (Join-Path $gitDir 'cmd') + ';' + $env:Path
  }
  & git --version
  Check 'Git'

  # ---------- 2. Flutter ----------
  Step '2/6 Flutter'
  if (-not (Has 'flutter')) {
    $flutterBin = Join-Path $tc 'flutter\bin'
    if (-not (Test-Path (Join-Path $flutterBin 'flutter.bat'))) {
      $zip = Join-Path $dl 'flutter.zip'
      if (-not (Test-Path $zip)) {
        $archive = $null
        foreach ($h in @('https://storage.googleapis.com', 'https://storage.flutter-io.cn')) {
          if ($archive) { break }
          try {
            $json = Invoke-RestMethod "$h/flutter_infra_release/releases/releases_windows.json"
            $hash = $json.current_release.stable
            foreach ($r in $json.releases) {
              if (-not $archive -and $r.hash -eq $hash) { $archive = $r.archive }
            }
          } catch {
            Write-Host "$h 连不上，换下一个…" -ForegroundColor Yellow
          }
        }
        if (-not $archive) { throw '获取 Flutter 版本信息失败，请检查网络' }
        $urls = @(
          "https://storage.googleapis.com/flutter_infra_release/releases/$archive",
          "https://storage.flutter-io.cn/flutter_infra_release/releases/$archive"
        )
        Download $urls $zip
      }
      Write-Host '解压 Flutter（要几分钟）…'
      Unzip $zip $tc
    }
    $env:Path = $flutterBin + ';' + $env:Path
  }
  # 连不上 Google 时，后续的组件和依赖包走镜像
  try {
    Invoke-WebRequest 'https://storage.googleapis.com/flutter_infra_release/releases/releases_windows.json' -Method Head -TimeoutSec 10 -UseBasicParsing | Out-Null
  } catch {
    Write-Host 'Google 存储连不上，改用国内镜像（Flutter、Gradle、Maven 都走镜像）' -ForegroundColor Yellow
    $useMirror = $true
    $env:FLUTTER_STORAGE_BASE_URL = 'https://storage.flutter-io.cn'
    $env:PUB_HOSTED_URL = 'https://pub.flutter-io.cn'
  }
  & flutter --version
  Check 'Flutter'

  # ---------- 3. JDK ----------
  Step '3/6 Java (JDK 17)'
  # 读 JDK 目录下的 release 文件判断版本（17 及以上才用）
  function JdkOk($dir) {
    if (-not $dir) { return $false }
    if (-not (Test-Path (Join-Path $dir 'bin\java.exe'))) { return $false }
    $rel = Join-Path $dir 'release'
    if (-not (Test-Path $rel)) { return $false }
    $line = Get-Content $rel | Where-Object { $_ -match '^JAVA_VERSION="(\d+)' } | Select-Object -First 1
    if (-not $line) { return $false }
    $null = $line -match '^JAVA_VERSION="(\d+)'
    return ([int]$Matches[1] -ge 17)
  }
  $jdk = $null
  $candidates = @(
    (Join-Path $tc 'jdk'),
    (Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Android Studio\jbr'),
    $env:JAVA_HOME
  )
  try {
    $reg = Get-ItemProperty 'HKLM:\SOFTWARE\Android Studio' -ErrorAction Stop
    if ($reg.Path) { $candidates += (Join-Path $reg.Path 'jbr') }
  } catch { }
  $javaCmd = Get-Command java.exe -ErrorAction SilentlyContinue
  if ($javaCmd) { $candidates += (Split-Path -Parent (Split-Path -Parent $javaCmd.Source)) }
  foreach ($c in $candidates) {
    if (-not $jdk -and (JdkOk $c)) { $jdk = $c }
  }
  if (-not $jdk) {
    $zip = Join-Path $dl 'jdk17.zip'
    if (-not (Test-Path $zip)) {
      $urls = @()
      # 清华镜像的文件名带版本号，先读目录找出最新的
      try {
        $base = 'https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/x64/windows/'
        $page = Invoke-WebRequest $base -UseBasicParsing -TimeoutSec 20
        $m = [regex]::Matches($page.Content, 'OpenJDK17U-jdk_x64_windows_hotspot_[0-9._]+\.zip')
        if ($m.Count -gt 0) { $urls += ($base + $m[$m.Count - 1].Value) }
      } catch { }
      $urls += 'https://repo.huaweicloud.com/openjdk/17.0.2/openjdk-17.0.2_windows-x64_bin.zip'
      $urls += 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse'
      $urls += 'https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip'
      try {
        Download $urls $zip
      } catch {
        Write-Host ''
        Write-Host 'JDK 自动下载都失败了。可以手动解决（二选一）：' -ForegroundColor Yellow
        Write-Host "  A. 用浏览器下载任意 JDK 17 的 Windows x64 zip 包，改名为 jdk17.zip，放到 $dl 里，再运行本程序"
        Write-Host '  B. 安装 Android Studio（自带 Java），再运行本程序'
        throw
      }
    }
    $tmp = Join-Path $tc 'jdk_tmp'
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Unzip $zip $tmp
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $inner) { Remove-Item -Force $zip; throw 'JDK 压缩包损坏，已删除，请重新运行' }
    Remove-Item -Recurse -Force (Join-Path $tc 'jdk') -ErrorAction SilentlyContinue
    Move-Item $inner.FullName (Join-Path $tc 'jdk')
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    $jdk = Join-Path $tc 'jdk'
    if (-not (JdkOk $jdk)) { throw "下载的 JDK 不可用：$jdk" }
  }
  $env:JAVA_HOME = $jdk
  $env:Path = (Join-Path $jdk 'bin') + ';' + $env:Path
  Write-Host "使用 JDK：$jdk"

  # ---------- 4. Android SDK ----------
  Step '4/6 Android SDK'
  $sdk = $null
  $candidates = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, (Join-Path $env:LOCALAPPDATA 'Android\Sdk'))
  foreach ($c in $candidates) {
    if (-not $sdk -and $c -and (Test-Path (Join-Path $c 'platform-tools'))) { $sdk = $c }
  }
  if (-not $sdk) { $sdk = Join-Path $tc 'android-sdk' }
  New-Item -ItemType Directory -Force $sdk | Out-Null
  $sdkm = Join-Path $sdk 'cmdline-tools\latest\bin\sdkmanager.bat'
  if (-not (Test-Path $sdkm)) {
    $zip = Join-Path $dl 'cmdline-tools.zip'
    Download @('https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip') $zip
    $tmp = Join-Path $tc 'clt_tmp'
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Unzip $zip $tmp
    New-Item -ItemType Directory -Force (Join-Path $sdk 'cmdline-tools') | Out-Null
    Move-Item (Join-Path $tmp 'cmdline-tools') (Join-Path $sdk 'cmdline-tools\latest')
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
  }
  $env:ANDROID_HOME = $sdk
  $env:ANDROID_SDK_ROOT = $sdk
  Write-Host "使用 Android SDK：$sdk"
  Write-Host '接受许可协议…'
  $yes = 1..60 | ForEach-Object { 'y' }
  try { $yes | & $sdkm --licenses | Out-Null } catch { }
  $global:LASTEXITCODE = 0
  if (-not (Test-Path (Join-Path $sdk 'platform-tools\adb.exe'))) {
    & $sdkm 'platform-tools'
    Check '安装 platform-tools'
  }

  # ---------- 5. 编译 ----------
  Step '5/6 编译（第一次会下载 Gradle 和安卓编译组件，耐心等）'
  # 复制到纯英文路径再编译：安卓编译工具遇到中文或带空格的路径容易出错
  New-Item -ItemType Directory -Force $src | Out-Null
  & robocopy.exe $proj $src /E /XD build .dart_tool output .git .idea /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw '复制工程文件失败' }
  # 代码目录按原样镜像（工程里删掉的旧文件，编译目录里也删掉）
  foreach ($sub in @('lib', 'test', 'tool')) {
    $from = Join-Path $proj $sub
    if (Test-Path $from) {
      & robocopy.exe $from (Join-Path $src $sub) /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
      if ($LASTEXITCODE -ge 8) { throw '复制工程文件失败' }
    }
  }
  $global:LASTEXITCODE = 0
  $ks = Join-Path $env:USERPROFILE '.android\debug.keystore'
  if (-not (Test-Path $ks)) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $ks) | Out-Null
    Copy-Item (Join-Path $proj 'ci\debug.keystore') $ks
  }
  Push-Location $src
  try {
    Set-Content -Path $flog -Value "build started $(Get-Date)" -Encoding UTF8
    RunLogged 'flutter create --org com.example --project-name ai_mind --platforms=android,ios .' 'flutter create'
    if ($useMirror) {
      # Gradle 本体走腾讯镜像
      $wp = Join-Path $src 'android\gradle\wrapper\gradle-wrapper.properties'
      if (Test-Path $wp) {
        $t = [IO.File]::ReadAllText($wp)
        $t = $t.Replace('https\://services.gradle.org/distributions/', 'https\://mirrors.cloud.tencent.com/gradle/')
        [IO.File]::WriteAllText($wp, $t, (New-Object Text.UTF8Encoding($false)))
      }
      # 依赖库走阿里云镜像：放在独立的 Gradle 目录里，不影响你电脑上其他项目
      $gh = Join-Path $tc 'gradle-home'
      New-Item -ItemType Directory -Force (Join-Path $gh 'init.d') | Out-Null
      $init = @'
def mirrors = [
    'https://maven.aliyun.com/repository/google',
    'https://maven.aliyun.com/repository/public',
    'https://maven.aliyun.com/repository/gradle-plugin',
]
beforeSettings { settings ->
    settings.pluginManagement.repositories { rh ->
        mirrors.each { u -> rh.maven { r -> r.setUrl(u) } }
    }
}
allprojects { p ->
    p.buildscript.repositories { rh ->
        mirrors.each { u -> rh.maven { r -> r.setUrl(u) } }
    }
    p.repositories { rh ->
        mirrors.each { u -> rh.maven { r -> r.setUrl(u) } }
    }
}
'@
      [IO.File]::WriteAllText((Join-Path $gh 'init.d\mirrors.gradle'), $init, (New-Object Text.UTF8Encoding($false)))
      $env:GRADLE_USER_HOME = $gh
    }
    RunLogged 'flutter pub get' '下载依赖包'
    RunLogged 'flutter build apk --release --split-per-abi' '编译 APK'
  } finally {
    Pop-Location
  }

  # ---------- 6. 输出 ----------
  Step '6/6 完成'
  $apkDir = Join-Path $src 'build\app\outputs\flutter-apk'
  $apks = @(Get-ChildItem $apkDir -Filter '*-release.apk')
  if ($apks.Count -eq 0) { throw '没有找到生成的 APK' }
  foreach ($a in $apks) { Copy-Item $a.FullName $out -Force }
  $main = Join-Path $out 'app-arm64-v8a-release.apk'
  Write-Host "安装包已生成：$out" -ForegroundColor Green
  Write-Host '  app-arm64-v8a-release.apk    <- 绝大多数安卓手机用这个'
  Write-Host '  app-armeabi-v7a-release.apk  <- 很老的 32 位手机'
  $ok = $true

  # 手机用数据线连着电脑、并开了 USB 调试的话，可以直接装进去
  $adb = Join-Path $sdk 'platform-tools\adb.exe'
  if ((Test-Path $adb) -and (Test-Path $main)) {
    $devs = @(& $adb devices | Where-Object { $_ -match '\tdevice\s*$' })
    if ($devs.Count -gt 0) {
      $ans = Read-Host '检测到已连接的安卓手机，现在直接安装到手机上吗？(y/n)'
      if ($ans -eq 'y') {
        & $adb install -r $main
        if ($LASTEXITCODE -eq 0) {
          Write-Host '已安装到手机' -ForegroundColor Green
        } else {
          Write-Host '安装失败：如果手机上有旧版本，先卸载再试；或把 APK 文件传到手机手动安装' -ForegroundColor Yellow
        }
      }
    } else {
      Write-Host '没有检测到手机。把上面的 APK 传到手机（数据线、网盘都行），在手机上点开安装即可。'
    }
  }
  Start-Process explorer.exe $out
}
catch {
  $msg = $_.Exception.Message
  Write-Host "`n出错了：$msg" -ForegroundColor Red
  Write-Host "编译的详细输出在：$flog"
  Write-Host '请把 flutter_log.txt 这个文件发给 Claude（里面有具体的错误原因）。重新运行本程序会从断点继续，不会重复下载。'
}
finally {
  try { Stop-Transcript | Out-Null } catch { }
}
if (-not $ok) { exit 1 }
