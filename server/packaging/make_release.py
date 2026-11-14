"""生成发布清单：写 latest.json（版本、说明、各平台安装包的地址 / 大小 / sha256），并用私钥签名成 latest.json.sig。

云端发布（.github/workflows/build-all.yml 的 release 任务）和本机测试都用它：
  python packaging/make_release.py --version 0.9.2 --dir <放安装包的文件夹> --base-url <下载地址前缀> [--notes-file F]
私钥：环境变量 UPDATE_SIGNING_KEY（base64 的 32 字节），或 --key-file 指定的文件。

文件名约定（不符合的文件忽略）：
  AIMind-Setup-<版本>.exe                 windows
  AIMind-<版本>-mac-arm64.dmg / -mac-intel.dmg
  AIMind-<版本>-android-arm64.apk / -android-armv7.apk
  AIMind-<版本>-ios-unsigned.ipa         ios（未签名，用免费 Apple ID 自签）
  AIMind-<版本>-ios.ipa                  ios-signed（云端用付费开发者证书签好的，配了才有）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aimind import ed25519  # noqa: E402
from aimind.version import UPDATE_PUBLIC_KEY  # noqa: E402

PATTERNS = {
    "windows": "AIMind-Setup-{v}.exe",
    "mac-arm64": "AIMind-{v}-mac-arm64.dmg",
    "mac-intel": "AIMind-{v}-mac-intel.dmg",
    "android-arm64": "AIMind-{v}-android-arm64.apk",
    "android-armv7": "AIMind-{v}-android-armv7.apk",
    "ios": "AIMind-{v}-ios-unsigned.ipa",
    "ios-signed": "AIMind-{v}-ios.ipa",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--base-url", required=True, help="安装包的下载地址前缀，比如 https://github.com/x/y/releases/download/v0.9.2")
    ap.add_argument("--notes-file")
    ap.add_argument("--key-file")
    a = ap.parse_args()

    v = a.version.lstrip("v")
    d = Path(a.dir)
    assets = {}
    for key, pat in PATTERNS.items():
        f = d / pat.format(v=v)
        if f.exists():
            assets[key] = {"name": f.name, "url": f"{a.base_url.rstrip('/')}/{f.name}",
                           "size": f.stat().st_size, "sha256": sha256(f)}
    if not assets:
        sys.exit(f"{d} 里没有符合命名的安装包")
    notes = Path(a.notes_file).read_text(encoding="utf-8-sig").strip() if a.notes_file else ""
    manifest = {"version": v, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "notes": notes, "assets": assets}
    raw = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")

    key_b64 = os.environ.get("UPDATE_SIGNING_KEY") or (Path(a.key_file).read_text().strip() if a.key_file else "")
    if not key_b64:
        sys.exit("没有私钥：设置环境变量 UPDATE_SIGNING_KEY 或用 --key-file")
    seed = base64.b64decode(key_b64)
    if base64.b64encode(ed25519.public_key(seed)).decode() != UPDATE_PUBLIC_KEY:
        sys.exit("私钥和程序里内置的公钥对不上（aimind/version.py 的 UPDATE_PUBLIC_KEY），这样发出去的更新会被拒绝")
    (d / "latest.json").write_bytes(raw)
    (d / "latest.json.sig").write_text(base64.b64encode(ed25519.sign(seed, raw)).decode())
    print(f"v{v}：{', '.join(assets)}；已签名")


if __name__ == "__main__":
    main()
