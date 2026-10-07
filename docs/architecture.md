# 架构：跨 harness 的工作台

> 需求见 [`../REQUIREMENTS.md`](../REQUIREMENTS.md)（R-08 是这份文件对应的条目）；命令清单见
> [`cli-reference.md`](cli-reference.md)。这份文件随代码走 —— 改了模块边界就改这里。

## 1. 一句话

`plan.json` 是唯一真相；**核心层不 print、不 `sys.exit`、不认命令行**，任何 harness
（Hermes / 别的 agent 框架 / 一个本地 web 服务 / 一个脚本）都能直接 import 它；
命令行只是**其中一个**适配器。它自己不是 harness 应用 —— 不驻留、不起服务、不持有状态。

## 2. 模块边界（`scripts/`）

```
scripts/plan.py                 CLI 入口（薄壳：插 sys.path → planweave.cli.main()）
scripts/planweave/
├── model.py     数据模型与派生规则：状态机、block_deps/edge_deps、ready/waiting 派生、
│                环检测、粒度规则（expand/collapse 的结构演算）、事件日志。**纯函数，不碰磁盘。**
├── store.py     磁盘：目录定位（<profile>/workspace/plans/<slug>/）、原子落盘、
│                **唯一写入漏斗 commit(slug, plan)** —— 改完 json 顺手同步三个视图。
├── render.py    plan.json → PLAN.md / plan.canvas / plan.html，**只返回字符串**（写盘归 store）。
├── workers.py   子代理线程探活：读转录 + manifest.json，给七种结论。
└── cli.py       argparse + 15 个子命令 + 中文输出。**唯一允许 print、唯一决定退出码的地方。**
```

依赖方向是单向的：`cli → store → render → model`、`cli → workers`、`store → model`。
`model` 不认识上面任何一层。

## 3. 三条跨 harness 约定

1. **错误只抛 `PlanError`**（`model.PlanError`，带 `code`＝建议的退出码）。没有 `sys.exit`。
   最外层（`cli.main()` / 未来的服务）把它变成 stderr + 退出码。
2. **所有写入都过 `store.commit()`**。要在写入前后加约束（协作者校验、状态机前置条件、
   画布写回），挂在这里一处就够 —— 不必去每个命令里补。
3. **视图永远派生**：`PLAN.md` / `plan.html` / `plan.canvas` 都由 `plan.json` 生成，且三个文件
   都走 `atomic_write`（同目录临时文件 + `os.replace`），读者不会看到写了一半的文件。

## 4. 怎么接一个新前端（R-02 画布写回 / R-06 web 服务）

```python
import sys; sys.path.insert(0, "<skill>/scripts")
from planweave import store, model, render

plan = store.load("my-plan")             # 读
for t, b in model.all_blocks(plan): ...  # 算（派生状态一律用 model 的函数，别自己实现一份）
store.commit("my-plan", plan)            # 写 = 落 json + 同步三视图（一步）
print(render.render_html(plan, store.TEMPLATE))   # 想自定义输出就自己取字符串
```

- **人在画布上改**（R-02）：前端把改动写成「对 plan.json 的最小 patch」，走 `commit()`；不要另存一份状态。
- **多 plan 切换**（R-06）：`store.PLANS_ROOT` 下每个 `<slug>/plan.json` 就是一个 plan，
  `list` 那种一览在库里对应「遍历 `PLANS_ROOT` + `model.progress()`」。
- **绑定与暴露**：服务只绑本机回环地址、纯 stdlib；跨机器不要开端口，让每台机器读同一份 json。

## 5. 改代码前的三道闸（2026-10-07 实测有效）

1. **名字自检**：机械搬迁/新增分支后，先静态查「用到的名字是否都能解析」（本轮抓到 3 处漏 import：
   `re` / `json` / 一个漏改的 `die`），比一条条跑命令看 `NameError` 快，也不漏未覆盖的分支。
2. **对拉**：`python3 scripts/plan.py <命令>` 与改动前的版本（`git show <旧 sha>:…/plan.py`）对同一串
   命令比 stdout / stderr / 退出码，再比产出的 `plan.json` / `PLAN.md` / `plan.canvas` / `plan.html`。
   本轮 37 条命令 + 4 个产物**逐字节一致**才提交。
3. **真数据只读回归**：拿装好的那份对真实 plans 跑只读命令（`list` / `workers` / `check`），
   确认路径推导（`PROFILE_HOME = <包文件>.parents[5]`）没算错 —— 改目录层级时这行最容易错。
