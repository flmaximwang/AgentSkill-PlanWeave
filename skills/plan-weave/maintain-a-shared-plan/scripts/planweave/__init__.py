"""PlanWeave 的核心：一份 plan 的模型 / 存储 / 视图 / 线程探活 + 一层 CLI 适配器。

- `model`   数据模型与派生规则（纯函数，出错抛 PlanError）
- `store`   磁盘读写与唯一写入漏斗 `commit()`
- `render`  三个视图（PLAN.md / plan.canvas / plan.html）的生成
- `workers` 子代理线程探活（七种结论）
- `cli`     命令行适配层（唯一 print、唯一退出码）

任何 harness 都能 `from planweave import store` 直接读写同一份 plan.json，不必经过命令行；
反过来，命令行不依赖任何 harness。
"""

__version__ = "2.0.0"
__all__ = ["model", "store", "render", "workers", "cli"]
