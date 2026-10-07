# 架构：一个仓储、两条腿（包 + skill）

> 需求见 [`../REQUIREMENTS.md`](../REQUIREMENTS.md)（R-08 / R-11 是这份文件对应的条目）；命令清单见
> [`cli-reference.md`](cli-reference.md)。这份文件随代码走 —— 改了模块边界或路径规则就改这里。

## 1. 一句话

`plan.json` 是唯一真相；**核心层不 print、不 `sys.exit`、不认命令行**，任何 harness
（Hermes / 别的 agent 框架 / 一个本地 web 服务 / 一个脚本）都能直接 import 它；
命令行只是**其中一个**适配器。它自己不是 harness 应用 —— 不驻留、不起服务、不持有状态。

**仓库根的 `loomerto/` 是包，`skills/` 是它随包的 skill。** skill 不夹带实现：它只带一个薄壳，
把「我这个 profile 的 plans 在哪」告诉包，然后调包。两者各自安装、各自更新，但 source of truth 同一处。

## 2. 仓库布局

```
Loomerto/                             ← 仓库根 = python 项目根（GitHub: flmaximwang/Loomerto）
├── pyproject.toml                    包元数据 + console scripts（loomerto / plan）+ 包数据
├── loomerto/                          ★ python 包（纯 stdlib、零依赖、>=3.9）
│   ├── __init__.py   __main__.py      `python -m loomerto` 的入口
│   ├── assets/plan.html              可视化模板（**包数据**，跟着包走）
│   ├── model.py     数据模型与派生规则：状态机、block_deps/edge_deps、ready/waiting 派生、
│   │                环检测、粒度规则（expand/collapse 的结构演算）、事件日志。**纯函数，不碰磁盘。**
│   ├── store.py     磁盘：**plans_root() 定位**、原子落盘、**唯一写入漏斗 commit(slug, plan)**
│   ├── render.py    plan.json → PLAN.md / plan.canvas / plan.html，**只返回字符串**（写盘归 store）
│   ├── workers.py   子代理线程探活：读转录 + manifest.json，给七种结论
│   └── cli.py       argparse + 15 个子命令 + 中文输出。**唯一允许 print、唯一决定退出码的地方。**
├── skills/                           随包发布的 skill（装进 Hermes profile 的是这一层）
│   └── plan-weave/maintain-a-shared-plan/
│       ├── SKILL.md                  给 AI 的操作手册（模型 / 状态表 / 谁在做 / 坑）
│       └── scripts/plan.py           **薄壳**：交代 plans 根 → 找包 → 调 cli.main()
├── docs/                             architecture.md（本文）/ cli-reference.md
├── REQUIREMENTS.md                   需求单一入口（含完整文档地图）
└── blind-tests/                      路由盲测的产物
```

依赖方向是单向的：`cli → store → render → model`、`cli → workers`、`store → model`。
`model` 不认识上面任何一层。

## 3. 四条跨 harness / 跨安装方式的约定

1. **错误只抛 `PlanError`**（`model.PlanError`，带 `code`＝建议的退出码）。没有 `sys.exit`。
   最外层（`cli.main()` / 未来的服务）把它变成 stderr + 退出码。
2. **所有写入都过 `store.commit()`**。要加约束（协作者校验 R-05、状态前置条件 R-04、画布写回 R-02），
   挂在这里一处就够 —— 不必去每个命令里补。
3. **视图永远派生**：`PLAN.md` / `plan.html` / `plan.canvas` 都由 `plan.json` 生成，且三个文件
   都走 `atomic_write`（同目录临时文件 + `os.replace`），读者不会看到写了一半的文件。
4. **plan 目录不靠猜**：`store.plans_root()` 只看显式配置 ——
   `--plans-root` → `--profile`（⇒ `~/.hermes/profiles/<名字>/workspace/plans`）→ `$LOOMERTO_PLANS_ROOT`
   → `$LOOMERTO_PROFILE` → `~/.hermes/workspace/plans`。
   **包不推断 profile**（它可能装在 site-packages 里，离任何 profile 都远）；profile 的位置由调用方
   交给它。模板同理：`$LOOMERTO_TEMPLATE` → 包自带的 `loomerto/assets/plan.html`。

## 4. 薄壳契约（`skills/.../scripts/plan.py`）

1. 若调用方没设 `LOOMERTO_PLANS_ROOT`，就把 `<本 skill 所在 home>/workspace/plans` 设上
   （装在 profile 里 = 该 profile 的 plans；在 checkout 里跑 = `<repo>/workspace/plans`，本机自测用）。
2. 找包：`<home>/loomerto`（checkout 优先：改的是哪份，跑的就是哪份）→ `$LOOMERTO_HOME` →
   已安装的 `import loomerto` → 已装好的 `loomerto` 命令（`os.execv` 交给它）。
3. 四条都不成立 ⇒ 打印该装哪一条（`uv tool install --editable <repo>` 等），退出码 2。
   **不抛 ImportError** —— 那种报错会把人引到「谁把这个包删了」，而不是「装它」。

## 5. 怎么接一个新前端（R-02 画布写回 / R-06 web 服务）

```python
from loomerto import store, model, render      # 装过包就能直接 import

plan = store.load("my-plan")             # 读
for t, b in model.all_blocks(plan): ...  # 算（派生状态一律用 model 的函数，别自己实现一份）
store.commit("my-plan", plan)            # 写 = 落 json + 同步三视图（一步）
print(render.render_html(plan, store.TEMPLATE))   # 想自定义输出就自己取字符串
```

- **人在画布上改**（R-02）：前端把改动写成「对 plan.json 的最小 patch」，走 `commit()`；不要另存一份状态。
- **多 plan 切换**（R-06）：`store.plans_root()` 下每个 `<slug>/plan.json` 就是一个 plan，
  `list` 那种一览在库里对应「遍历 plans_root + `model.progress()`」。
- **绑定与暴露**：服务只绑本机回环地址、纯 stdlib；跨机器不要开端口，让每台机器读同一份 json。

## 6. 开发与验收（本机实测有效的四道闸）

1. **名字自检**：机械搬迁/新增分支后，先静态查「用到的名字是否都能解析」（拆分那轮抓到 3 处漏 import：
   `re` / `json` / 一个漏改的 `die`），比一条条跑命令看 `NameError` 快，也不漏未覆盖的分支。
2. **对拉**：新代码与改动前的版本（`git show <旧 sha>:<路径>`）对同一串命令比 stdout / stderr / 退出码，
   再比产出的 `plan.json` / `PLAN.md` / `plan.canvas` / `plan.html`。
3. **真数据只读回归**：拿装好的那份对真实 plans 跑只读命令（`list` / `workers` / `check`）。
4. **install 回读**：`uv tool install --editable .` 后从**任意目录**跑 `loomerto --profile plan-weave list`，
   确认包数据（模板）与 plans 根都对；skill 侧再跑一次薄壳（模拟「装进 profile」的那条路）。

```bash
# 本机（macOS，系统 python3 是 3.9.6；旧 pip 装不了 editable，所以用 uv）
uv tool install --editable .        # → ~/.local/bin/{loomerto,plan}
python3 -m loomerto --plans-root <plans> list
```
