#!/usr/bin/env bash
# 用付费开发者账号的证书给 iPhone 版签名（云端 macOS 上运行，见 .github/workflows/build-all.yml）
#   用法：bash scripts/sign_ios.sh <Runner.app> <输出.ipa>
#   环境变量（来自 GitHub 仓库密钥）：
#     IOS_P12_BASE64     证书（含私钥）导出的 .p12，base64
#     IOS_P12_PASSWORD   导出 .p12 时设的密码
#     IOS_PROFILE_BASE64 描述文件 .mobileprovision，base64（Ad Hoc 或 Development，里面要有你的 iPhone）
# 包名（Bundle ID）直接从描述文件里读，所以只要描述文件和证书配套就行，不用改工程。
set -euo pipefail
APP_SRC="$1"; OUT="$2"
W="${RUNNER_TEMP:-$(mktemp -d)}/iossign"
rm -rf "$W"; mkdir -p "$W/Payload"

# ---- 临时钥匙串，导入证书 ----
KC="$W/sign.keychain-db"; KCPW="$(uuidgen)"
security create-keychain -p "$KCPW" "$KC"
security set-keychain-settings -lut 3600 "$KC"
security unlock-keychain -p "$KCPW" "$KC"
echo "$IOS_P12_BASE64" | base64 --decode > "$W/cert.p12"
security import "$W/cert.p12" -P "$IOS_P12_PASSWORD" -A -t cert -f pkcs12 -k "$KC" >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KCPW" "$KC" >/dev/null
security list-keychains -d user -s "$KC" $(security list-keychains -d user | tr -d '"')
IDENT="$(security find-identity -v -p codesigning "$KC" | awk 'NR==1{print $2}')"
if [ -z "$IDENT" ] || [ "$IDENT" = "0" ]; then
  echo "::error::证书里没有可用于签名的身份（.p12 要连同私钥一起导出）"; exit 1
fi

# ---- 读描述文件：团队、包名、权限 ----
echo "$IOS_PROFILE_BASE64" | base64 --decode > "$W/profile.mobileprovision"
security cms -D -i "$W/profile.mobileprovision" > "$W/profile.plist"
PB=/usr/libexec/PlistBuddy
TEAM="$($PB -c 'Print :TeamIdentifier:0' "$W/profile.plist")"
APPID="$($PB -c 'Print :Entitlements:application-identifier' "$W/profile.plist")"
BUNDLE="${APPID#"$TEAM".}"
if [ "$BUNDLE" = "*" ]; then BUNDLE="com.aimind.recorder"; fi      # 通配描述文件：随便用一个固定包名
EXPIRE="$($PB -c 'Print :ExpirationDate' "$W/profile.plist")"
echo "签名：团队 $TEAM，包名 $BUNDLE，描述文件到期 $EXPIRE"
$PB -x -c 'Print :Entitlements' "$W/profile.plist" > "$W/ent.plist"
$PB -c "Set :application-identifier $TEAM.$BUNDLE" "$W/ent.plist"

# ---- 改包名、放描述文件、由内到外逐个签名 ----
APP="$W/Payload/Runner.app"
cp -R "$APP_SRC" "$APP"
$PB -c "Set :CFBundleIdentifier $BUNDLE" "$APP/Info.plist"
cp "$W/profile.mobileprovision" "$APP/embedded.mobileprovision"
rm -rf "$APP/_CodeSignature"
if [ -d "$APP/Frameworks" ]; then
  find "$APP/Frameworks" -maxdepth 1 \( -name '*.framework' -o -name '*.dylib' \) -print0 |
    while IFS= read -r -d '' f; do codesign -f -s "$IDENT" --keychain "$KC" "$f"; done
fi
codesign -f -s "$IDENT" --keychain "$KC" --entitlements "$W/ent.plist" "$APP"
codesign --verify --deep --strict "$APP"

(cd "$W" && zip -qry "out.ipa" Payload)
mv "$W/out.ipa" "$OUT"
security delete-keychain "$KC" || true
rm -f "$W/cert.p12"
echo "已签名：$OUT"
