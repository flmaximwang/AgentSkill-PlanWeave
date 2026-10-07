"""loomerto —— 一份 plan 的模型 / 存储 / 视图 / 改动 / 线程探活 / 画布服务 + 一层 CLI 适配器。

**跨 harness 的工作台**：`plan.json` 是唯一真相，任何 harness（Hermes / 别的 agent 框架 /
一个本地 web 服务 / 一个脚本）都能直接 import 这个包读写同一份 plan；命令行只是其中一层。

- `model`   数据模型与派生规则（纯函数，出错抛 `PlanError`）
- `store`   磁盘读写与唯一写入漏斗 `commit()`；plan 在哪由调用方说（`--plan` / `--plans-root`）
- `render`  三个视图（PLAN.md / plan.canvas / plan.html）的生成，只返回字符串
- `edits`   **改动的唯一实现**（改状态 / 改字段 / 加任务 / 加块 / 重排）—— CLI 与画布共用
- `serve`   `loomerto open` 的画布服务（纯 stdlib，只绑 127.0.0.1，写回同一个 commit）
- `workers` 子代理线程探活（七种结论）
- `cli`     命令行适配层（唯一 print、唯一退出码）

名字 = loom + concerto：协奏曲里独奏与乐队主次分明、却同演一曲 —— 正对「一个人 + 几个 agent 在同一份
plan 上各按自己的声部推进」；loom 那一半接着说多条工作线被织成一块布。
"""

__version__ = "0.1.0"
__all__ = ["model", "store", "render", "edits", "serve", "workers", "cli"]
