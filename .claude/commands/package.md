---
description: 打包给用户的 zip（电脑端 + 手机端源码）
---
1. 先执行 /test，全部通过才继续。
2. 运行 `bash scripts/package.sh`，它会在 `dist/` 下生成 `aimind.zip`（整个仓库）。
3. 检查 zip 里没有 `data/`、`.venv/`、`__pycache__/`、`build/`、`.dart_tool/`。
4. 用中文告诉用户：zip 里有什么、怎么用；如果是从旧版升级，提醒把旧的 `data` 文件夹复制到 `server/data`。
