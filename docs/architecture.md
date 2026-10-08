# 架构：一个仓储、两条腿（包 + skill）

> 需求见 [`../REQUIREMENTS.md`](../REQUIREMENTS.md)（R-08 / R-11 是这份文件对应的条目）；命令清单见
> [`cli-reference.md`](cli-reference.md)。这份文件随代码走 —— 改了模块边界或路径规则就改这里。

## 1. 一句话

`plan.json` 是唯一真相；**核心层不 print、不 `sys.exit`、不认命令行**，任何 harness
（Hermes / 别的 agent 框架 / 一个本地 web 服务 / 一个脚本）都能直接 import 它；
命令行只是**其中一个**适配器。它自己不是 harness 应用 —— 不驻留、不起服务、不持有状态。

**仓库根的 `loomerto/` 是包，`skills/` 是它随包的 skill。** skill 不夹带实现：它只带一个薄壳，
把「这份 plan（或这份 plan 库）在哪」告诉包，然后调包。两者各自安装、各自更新，但 source of truth 同一处。

## 2. 仓库布局

```
Loomerto/                             ← 仓库根 = python 项目根（GitHub: flmaximwang/Loomerto）
├── pyproject.toml                    包元数据 + console scripts（loomerto / plan）+ 包数据
├── loomerto/                          ★ python 包（纯 stdlib、零依赖、>=3.9）
│   ├── __init__.py   __main__.py      `python -m loomerto` 的入口
│   ├── assets/plan.html              只读可视化模板（**包数据**，跟着包走）
│   ├── assets/canvas.html            `open` 的**可编辑**画布页面（同样随包走）
│   ├── assets/theme.css              **两页共用的主题**：颜色/字体/状态胶囊/按钮/分隔线/进度条
│   │                                 （plan.html 由 render、canvas.html 由 serve 在生成时注入）
│   ├── model.py     数据模型与派生规则：状态机、状态×负责人（STATUS_OWNER）、**块的形状
│   │                 （BLOCK_FIELDS = 键→默认值，唯一一处；new_block() = 建块的唯一字面量；
│   │                 normalize_block() = 老数据缺键只补不改）**、block_deps/edge_deps、ready/waiting 派生、
│   │                环检测、粒度规则（expand/collapse 的结构演算）、事件日志。**纯函数，不碰磁盘。**
│   ├── store.py     磁盘：**plan_path() 定位**（--plan / --plans-root / 当前目录）、原子落盘、
│   │                **唯一写入漏斗 commit(slug, plan)**
│   ├── render.py    plan.json → PLAN.md / plan.canvas / plan.html，**只返回字符串**（写盘归 store）
│   ├── edits.py     **改动的唯一实现**：改状态 / 改字段 / 加任务 / 加块 / 重排 / 移块 —— CLI 与画布共用
│   ├── serve.py     `loomerto open` 的画布服务（http.server，只绑 127.0.0.1，写回同一个 commit）
│   ├── workers.py   子代理线程探活：读转录 + manifest.json，给七种结论
│   └── cli.py       argparse + 12 个一级命令（`plan` / `task` / `block` 是分组，动作都在二级；
│                    共 23 个叶子命令）+ 中文输出。
│                    **唯一允许 print、唯一决定退出码的地方。**
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

## 3. 约定：前端不许自带一套颜色

- **观感只有一份来源 = `loomerto/assets/theme.css`**：颜色、字体、状态色（`--done` / `--running` / …）、
  状态胶囊（`.pill`）、按钮（`.btn`）、分隔线（`#splitter`）、进度条（`.track`）、图例（`.legend`）
  全在那里。两个页面各留一个 CSS 注释标记，`render.py`（plan.html）与 `serve.py`（canvas.html）
  在生成 / 送出时把它换成这份文本 —— 所以两页仍是自包含单文件，但不会各长一套颜色。
- JS 里要状态色就写 `var(--running)`，**不要写十六进制**（plan.html 的 `C` 表就是这么多做的）。
- 页面的 CSS 里只留**布局**（谁在哪、多宽、怎么折行）；宽度变量两页同名 `--detail-w`。
- 改观感 = 改 `theme.css` 一处，然后 `loomerto render`（看板）与重开 `open`（画布）各看一眼。

## 4. 跨 harness / 跨安装方式的六条约定

1. **错误只抛 `PlanError`**（`model.PlanError`，带 `code`＝建议的退出码）。没有 `sys.exit`。
   最外层（`cli.main()` / 未来的服务）把它变成 stderr + 退出码。
2. **所有写入都过 `store.commit()`**。要加约束（协作者校验 R-05、状态前置条件 R-04、画布写回 R-02），
   挂在这里一处就够 —— 不必去每个命令里补。
3. **视图永远派生**：`PLAN.md` / `plan.html` / `plan.canvas` 都由 `plan.json` 生成，且三个文件
   都走 `atomic_write`（同目录临时文件 + `os.replace`），读者不会看到写了一半的文件。
4. **plan 在哪不靠猜、也不认任何 harness**：`store.plan_path()` 只看显式给的 ——
   `--plan <plan 数据文件>`（⇒ 就这一份；数据文件叫什么名都行）→ `--plans-root <目录>` 或
   `$LOOMERTO_PLANS_ROOT` / 调用方塞的 `EMBEDDED_PLANS_ROOT`（⇒ `<目录>/<slug>/plan.json`）→
   当前目录的 `plan.json`（存在才认）→ 都没有就退 2 并打印该给什么。
   **包里没有 profile / hermes 这类概念**（它可能装在 site-packages 里，离任何 harness 都远）；
   路径由调用方交给它。模板同理：`$LOOMERTO_TEMPLATE` → 包自带的 `loomerto/assets/plan.html`。
5. **改动只有一份实现**（`edits.py`）：改状态 / 改字段 / 加任务 / 加块 / 重排都收在那里；
   `cli.py` 与 `serve.py` 都只是薄薄一层适配（一个是参数解析 + print，一个是 HTTP）。
   谁再写第二份「改状态」，`runs` / `feedback` / `exec` 的写法就会开始漂。
6. **块的形状只有一处声明**（`model.BLOCK_FIELDS`）：一个块**有哪些键、默认值是什么**写在那张表里，
   建块的几处（`edits.add_block` / `edits.insert_block` / `cli` 的 `expand`、`collapse`）一律调
   `model.new_block()` —— 谁再手写一份块字典字面量，加一个键时就会漏掉它（曾经四处各抄一遍，
   实库里 9 份 plan 的 158 个块没有 `exec` 就是这么来的）。
   **老数据缺键由 `store.load()` 里的 `model.normalize_block()` 补齐（只补不改、不删）** ——
   读到的块总是完整形状，写不写盘由调用方决定（下一次 `commit()` 顺手材料化，语义不变）。
   历史键（只有 `block collapse` 写的 `folded_from`）**不进表**，所以补不出来、也不会被删掉。

## 5. 薄壳契约（`skills/.../scripts/plan.py`）

1. 若调用方既没给 `--plan` 也没设 `LOOMERTO_PLANS_ROOT`，就把 `<本 skill 所在 home>/workspace/plans` 设上
   （装在 profile 里 = 该 profile 的 plans；在 checkout 里跑 = `<repo>/workspace/plans`，本机自测用）。
2. 找包：`<home>/loomerto`（checkout 优先：改的是哪份，跑的就是哪份）→ `$LOOMERTO_HOME` →
   已安装的 `import loomerto` → 已装好的 `loomerto` 命令（`os.execv` 交给它）。
3. 四条都不成立 ⇒ 打印该装哪一条（`uv tool install --editable <repo>` 等），退出码 2。
   **不抛 ImportError** —— 那种报错会把人引到「谁把这个包删了」，而不是「装它」。

## 6. 怎么接一个新前端（R-02 画布写回已落地第一版；R-06 服务层）

**参考实现就是 `serve.py` + `assets/canvas.html`（`loomerto open <plan 数据文件>`）**——
协议与冲突规则写在 [`canvas-sync.md`](canvas-sync.md)；照它接第二个前端（web 服务 / 别的画布）即可。

```python
from loomerto import store, model, edits      # 装过包就能直接 import

plan = store.load("my-plan")             # 读（plan 在哪由 --plan / --plans-root 说）
edits.set_status(plan, "T-001#B-002", "running", by="me", note="开干")   # 改（唯一实现）
store.commit("my-plan", plan)            # 写 = 落 json + 同步三视图（一步）
for t, b in model.all_blocks(plan): ...  # 算（派生状态一律用 model 的函数，别自己实现一份）
```

- **人在画布上改**（R-02）：前端把改动写成一次 `op`（edit / status / task / block / reorder / move），
  带上自己读到的 `rev`；服务端比对它，对不上回 409 —— 不要另存一份状态、不要自己合并。
  **结构演算全在 `edits` 里**（`reorder` 只改先后、`move` 换 id + 重接引用 + 查环），前端不实现第二份。
- **多 plan 切换**（R-06）：`plans_root()` 下每个 `<slug>/plan.json` 就是一个 plan；
  一个 `open` 服务只服务一份（想要一览就在外层做「每个 slug 起一个/换 target 重开」）。
- **绑定与暴露**：服务只绑本机回环地址、纯 stdlib；跨机器不要开端口，让每台机器读同一份 json。

## 7. 开发与验收（本机实测有效的五道闸）

1. **名字自检**：机械搬迁/新增分支后，先静态查「用到的名字是否都能解析」（拆分那轮抓到 3 处漏 import：
   `re` / `json` / 一个漏改的 `die`），比一条条跑命令看 `NameError` 快，也不漏未覆盖的分支。
2. **对拉**：新代码与改动前的版本（`git show <旧 sha>:<路径>`）对同一串命令比 stdout / stderr / 退出码，
   再比产出的 `plan.json` / `PLAN.md` / `plan.canvas` / `plan.html`。
   **跑另一份 checkout 的代码时别被 cwd 顶掉**：`python3 -m loomerto` 把**当前目录**放在 `sys.path` 最前，
   站在 main 的目录里给 `PYTHONPATH=<worktree>` 跑的其实是 main 那份 —— 对拉会变成自己跟自己比
   （跨泳道拖动这轮踩过：11 份 plan 的「0 处差异」是假的）。要么 `cd` 到那份 checkout，要么在**没有
   `loomerto/` 目录**的地方跑；并且**先证明跑的是哪一份**（两边 `--help` 的子命令表必须不同）。
3. **真数据只读回归**：拿装好的那份对真实 plans 跑只读命令（`list` / `workers` / `check`）。
4. **install 回读**：`uv tool install --editable .` 后从**任意目录**跑 `loomerto --plans-root <某个库> list`
   与 `loomerto --plan <某个 plan 数据文件> current`，确认包数据（模板）与两种定位方式都对；
   skill 侧再跑一次薄壳（模拟「装进 profile」的那条路）。
5. **画布/前端改动要在真浏览器里真拖一次**（2026-10-07 跨泳道拖动这轮定）：用 checkout 起
   `python3 -m loomerto --plan <测试文件> open --port <N>`，在页面里派发真的 `DragEvent`（带 `DataTransfer`）
   走完 dragstart → dragover → drop，再回读页面状态与磁盘 `plan.json`。这一轮靠它抓到两个只在浏览器里
   才现形的 bug：① 前端把「目标泳道 id」当块 id 去查表 → drop 静默什么都不做（服务端日志干净、CLI 全绿）；
   ② `_apply` 改成返回二元组后 `reorder`（同泳道拖）撞 `KeyError: 'ref'`。
   **改页面资产不用重启服务，改 `serve.py` 必须重启** —— 前者每次 `GET /` 都从磁盘重读，后者是已加载的模块。

```bash
# 本机（macOS，系统 python3 是 3.9.6；旧 pip 装不了 editable，所以用 uv）
uv tool install --editable .        # → ~/.local/bin/{loomerto,plan}
python3 -m loomerto --plans-root <plans> list
```
