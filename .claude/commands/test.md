---
description: 跑电脑端全部测试和风格检查（可选：手机端静态检查）
---
在 `server/` 下运行 `python -m pytest -q` 和 `ruff check aimind tools tests`。
如果改动涉及 `mobile/`，再在 `mobile/` 下运行 `dart analyze lib tool`（没有 Dart 环境就说明跳过了）。
有失败就定位原因并修好，再跑一遍，直到全部通过。最后用一两句中文总结结果。
