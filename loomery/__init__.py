"""loomery —— 一份 plan 的模型 / 存储 / 视图 / 线程探活 + 一层 CLI 适配器。

**跨 harness 的工作台**：`plan.json` 是唯一真相，任何 harness（Hermes / 别的 agent 框架 /
一个本地 web 服务 / 一个脚本）都能直接 import 这个包读写同一份 plan；命令行只是其中一层。

- `model`   数据模型与派生规则（纯函数，出错抛 `PlanError`）
- `store`   磁盘读写与唯一写入漏斗 `commit()`；plan 目录由 `store.plans_root()` 决定
- `render`  三个视图（PLAN.md / plan.canvas / plan.html）的生成，只返回字符串
- `workers` 子代理线程探活（七种结论）
- `cli`     命令行适配层（唯一 print、唯一退出码）

名字取「织造工场」（loomery = 织布的地方）：多条工作线在这里被织成一块布。
"""

__version__ = "0.1.0"
__all__ = ["model", "store", "render", "workers", "cli"]
