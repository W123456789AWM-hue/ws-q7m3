"""版本号：全工程只在这里写一次。

发布新版本：改这里 → 提交 → 打同名标签（git tag v0.9.2 && git push origin v0.9.2）→ 云端自动打包并发布。
（云端会检查标签和这里是否一致；手机 App 的版本号也从标签来。）
"""
VERSION = "0.9.8"

# 在线更新：发布仓库（公开，只放安装包）的最新版本清单 + 清单的签名公钥（私钥只在 GitHub 的加密设置里）
UPDATE_REPO = "W123456789AWM-hue/aimind-releases"
MANIFEST_URL = f"https://github.com/{UPDATE_REPO}/releases/latest/download/latest.json"
UPDATE_PUBLIC_KEY = "JEm27iMP2XRcLJ95mRWP1Q74taIq81YAplvj6Ejgpxo="


def parse(v: str) -> tuple:
    """'0.9.10' → (0, 9, 10)；'v1.2' 也认。比较版本用"""
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def newer(a: str, b: str) -> bool:
    """a 比 b 新吗"""
    return parse(a) > parse(b)
