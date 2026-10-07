# loomerto · 需求（单一入口）

**这份文件是 loomerto 需求的唯一入口。** 想知道「要什么、做到哪了、细节在哪」，从这里出发；
不要另建需求清单、也不要把需求散在各个 skill 的正文里 —— 正文只写「怎么做」，需求写在这。

> 最后对齐：2026-10-07 · 代码基线 `11b33c3`（= 本机 default profile 里那五条 skill 与包所 pin 的 revision）
> 变更纪律：需求条目只在**用户明确说了**或**用户拍板**之后才增删；实现状态变了改「现状」列，不新开一份。

## 0. 文档地图（每个细节去哪看）

| 文档 | 承担什么 | 什么时候读 |
|---|---|---|
| **本文件 `REQUIREMENTS.md`** | **需求单一入口**：目标 / 需求条目 / 现状 / 缺口 / 决策点 | 先读这个 |
| [`README.md`](README.md) | 仓库索引：这是干什么的、五个 skill 各是什么、安装 loop、盲测表 | 想装它 / 想找某个 skill |
| [`docs/cli-reference.md`](docs/cli-reference.md) | `plan.py` 全部子命令、参数、退出码（**现状清单**，逐条可与实现核对） | 要敲命令 / 要核对 CLI 面 |
| [`skills/plan-weave/maintain-a-shared-plan/SKILL.md`](skills/plan-weave/maintain-a-shared-plan/SKILL.md) | **操作细节**：模型（plan/task/block/run/exec）、状态表、粒度调整、谁在做+线程、一次回合的固定动作、坑 | 要动手改一份 plan |
| [`skills/plan-weave/remind-collaborators/SKILL.md`](skills/plan-weave/remind-collaborators/SKILL.md) | 提醒纪律：何时推、推给谁、静默与去重 | 要发提醒 |
| [`skills/plan-weave/check-plan-temp-hygiene/SKILL.md`](skills/plan-weave/check-plan-temp-hygiene/SKILL.md) | 交付前校验之一：临时文件闭环 | 送审 / 交接 / 收尾 |
| [`skills/plan-weave/check-plan-node-commands/SKILL.md`](skills/plan-weave/check-plan-node-commands/SKILL.md) | 交付前校验之二：每个节点的可执行命令与变量定义 | 送审 / 交接 / 收尾 |
| [`skills/agent-orchestration/intake-a-running-collaboration/SKILL.md`](skills/agent-orchestration/intake-a-running-collaboration/SKILL.md) | 后进来的人怎么用秒级只读证据接上（含 `references/read-only-evidence-recipes.md`） | 被 @ 进一段已经在跑的协作 |
| [`blind-tests/r1/`](blind-tests/r1/README.md) | description 路由盲测：题面 / 金标 / 判官 A·B / 得分矩阵 | 改了 skill 头部之后 |
| [`docs/architecture.md`](docs/architecture.md) | 拆分后的模块边界、跨 harness 的三条约定、怎么接新前端（画布写回 / web 服务）、改代码前的三道闸 | 要动结构 / 要接别的 harness |
| [`docs/canvas-sync.md`](docs/canvas-sync.md) | **画布写回协议**（R-02）：`GET/POST /api/plan` 的字段、五个 `op`、`rev` 冲突与幂等、以及**故意不做**的四件事 | 要改画布 / 接第二个前端 |

## 1. 定位（一句话）

**跨 harness 的工作台，它自己不是一个 harness 应用。** 一份 `plan.json` 是唯一真相，任何 harness
（Hermes / 别的 agent 框架 / 一个 Python 起的本地 web 服务）都能读它、改它；人看的是派生的画布，
AI 敲的是命令或直接改 json，两边改完都落到同一份 json，再同步出 md 与画布 —— 这样「复杂流程」不必
靠语言描述清楚，而是**改在自己眼前的图上**。

三个硬约束（来自用户，不随实现变）：
1. **单一真相**：`plan.json` 是唯一真相；`PLAN.md` / `plan.html` / `plan.canvas` 永远是派生物，不许手改。
2. **两边都能改**（R-02）：人改画布 → 落 json → 再同步 md/画布；AI 改 json（或命令）→ 同步 md/画布。
3. **可搬**：纯 stdlib、文件驱动、`python3 <绝对路径> <子命令>` 到处能跑；不许引入必须 pip 安装才能用的东西。

## 2. 需求条目

状态只有三种：`已落地` / `部分` / `待做`。「现状」一列写的是**代码里真实存在的东西**，不是设想。

| # | 需求（用户原话的意思） | 现状（代码里真有的） | 状态 |
|---|---|---|---|
| **R-01** | 每个节点要表明**谁认领了 / 谁在做**，并能给出**具体的子代理线程**，以便检查子代理是否正常 | `block.owner`（认领人）+ `block.exec`（`by`/`delegation`/`task_index`/`transcript`/`started`）+ 命令 `exec`、`workers`（七值，⚠/❌ 退 1）；三视图都显示「@认领人→@在做的人」与线程路径。SKILL.md 有专节 | 已落地 `3d774bd` |
| **R-02** | **人与 AI 双向对齐**：用户可以直接在画布上改 plan（改完自动同步 json 与 md）；AI 通过命令改 json 并同步 md 与画布。目的是不必用语言描述复杂流程 | **第一版已落地**：`loomerto open <plan 数据文件>` 起本地服务（只绑 `127.0.0.1`、纯 stdlib），画布上可改 块的标题/做什么/判据/认领人/类型/**状态**、新建任务与新建块、拖动卡片改同泳道先后；每次改动走 `edits`（唯一实现）→ `store.commit()`，所以 json 与 `PLAN.md`/`plan.html`/`plan.canvas` 同时更新；前端带 `rev`（= `updated_at`），过期回 **409** 不自动合并。协议 = [`docs/canvas-sync.md`](docs/canvas-sync.md)。**故意不做**：删块/删任务、跨泳道拖动、改 `deps`/`review_of`（会改块 id 或接线 ⇒ 走 `rm`/`expand`/`collapse`） | 已落地（第一版） |
| **R-03** | AI 能用 CLI 做节点级结构编辑：**在某个节点之后 / 两个节点之间 / 最早的节点之前插入节点**；**删除节点**；**把一个节点拆成一个任务流程** | 拆成任务流程 = `expand`（块→任务，含后续 `--step`）；删除 = `rm`；插入只有 `expand/collapse` 的副产品（`--into <块>` 插到某块之后、`--into <任务>` 追到末尾）。**缺**：显式「插到指定节点之前/之后」、**「两节点之间」**、**「最早节点之前」** | 部分 |
| **R-04** | CLI 能快速改状态，但**带约束**：改为「已认领」必须附上**被谁认领**；改为「进行中」必须附上**主代理或子代理 pid** | `set … --by` 会写 `exec.by`（认得人是谁），`exec --delegation` 认得线程号；**但没有强制校验**（`--by` 可省、也无 pid 字段，改为 claimed/running 时不缺信息也能过） | 待做 |
| **R-05** | 每个项目要先登记**协作者**（人类 / agent），节点必须派给协作者中的一员 | `plan new --owner "id=kind:label[@channel]"` 写 `participants`，`block --owner` 只是个自由字符串；**不校验** owner 是否在 participants 里，也不强制「先有协作者」 | 部分 |
| **R-06** | 给用户的界面**不一定是 html 文件**：也可以是一个 Python 起的本地 web 服务，能在**多个 plan 之间切换** | **服务层有了**：`loomerto open` 就是纯 stdlib 的本地服务（一个进程服务一份 plan，`Ctrl-C` 停）。**还缺**：多 plan 一览与切换的界面（`list` 仍是一行文本；换一份要重开一次 `open`） | 部分 |
| **R-07** | **需求要在 skill repo 里留档**，方便后期对齐；文档要有**单一入口**，入口要**完整指路**到细节文档 | 本文件 + [`docs/cli-reference.md`](docs/cli-reference.md) 就是这次的产物；README 加了「文档地图」指向这里 | 已落地（本次提交） |
| **R-08** | 工程形态：能当**跨 harness 的工作台**，同时**自己不是 harness 应用**；核心可被别的程序用，CLI 只是其中一层 | 已拆成 6 层，包在**仓库根** `loomerto/`：`model` / `store` / `render` / `edits` / `serve` / `workers` / `cli`。核心不 print、不 `sys.exit`（抛 `PlanError`），所有写入过 `store.commit()` 一处、所有改动过 `edits` 一处；别的程序 `import loomerto` 即可用；skill 侧只留一个薄壳 `scripts/plan.py` | 已落地 |
| **R-09** | 把目前支持的 CLI 操作**整理出来回报** | [`docs/cli-reference.md`](docs/cli-reference.md)：17 个子命令（含 `plan new` / `task new` 两个分组，另 4 个别名）逐条列参数与退出码 | 已落地 |
| **R-10** | **新建节点默认是「待批准」**（`blocked`），而不是 `pending`；只有当 AI 判断这块无需审批就能干时，才用 `pending` | `block` 的 `--status` 默认已改成 `blocked`（=界面上「待批准」，等有人点头）；`--status pending` 是显式放行。`expand --step` 追加的步骤仍是 `pending`（见 §4 说明） | 已落地 |
| **R-11** | **这个 repo 本身升级成一个「带 skill 的 AI 原生 python 包」**：包放仓库根目录，skill 随包发布；包名要**与 GitHub 上已有的项目区分开** | 包已落在仓库根 `loomerto/`（`pyproject.toml` + console scripts `loomerto`／`plan` + 包数据 `assets/plan.html`）；skill 只带薄壳。**命名依据**：① `PlanWeave` 已被 [`GaosCode/PlanWeave`](https://github.com/GaosCode/PlanWeave)（★411，正是我们借模型的那个项目）占用，`planweave` 与它直接撞名；② 最终名 **loomerto = loom + concerto**，取协奏曲「独奏与乐队主次分明、却同演一曲」的意象（一个人 + 几个 agent 各按声部推进同一份 plan）。冲突筛查（2026-10-07 实测）：PyPI `loomerto` **未注册**、GitHub **无同名仓库**（比前一个候选 `loomery` 更干净 —— 后者 PyPI 未注册但 GitHub 有 ★3 同名小仓库）。**装机现状**：default profile 五条 skill 装在类目 `loomerto`（intake 归 `agent-orchestration`），lock 的 identifier/URL 指向 `flmaximwang/Loomerto`、revision `7eed38f`，装好的副本与仓库逐份 `diff -rq` 一致；`plan-weave` profile 里是旧一代（类目 `plan-weave`，identifier 仍是旧仓库名），待随该 bot 退役一并清 | 已落地 |
| **R-12** | 「**给一个 cli 入口**」—— 要能按 ref（`T-003#B-004` 这种）查**一个块/一条任务**的详细信息，而不是只给命令清单 | `show` 子命令（别名 `info`）：`py show <slug> <ref> [--json] [--runs N]` —— 块视角给 状态/类型/归属/认领(含时刻)/在做+线程+转录/做什么/判据/依赖/评审/返工 ⟲N/产物/run/三视图路径，任务视角给 状态/前置/块一览；纯只读（不落盘、不重渲、不写日志），找不到 ref 退 2 | 已落地 `09250db` |
| **R-13** | **调用式**：「我希望的格式是 `loomerto --plan <plan data file> command`」；并且「**不要支持 profile** —— 我从来没有定义过 loomerto 就是给 hermes 用的」 | 全局旗标换成 **`--plan <plan 数据文件>`**（= `$LOOMERTO_PLAN_FILE`；给目录也行）：只认这一份，**命令里不再写 slug**（位置参数整体左移一位：`set <ref> <status>`、`exec/show/rm/expand/collapse <ref>`、`note <text>`）。`--plans-root`（= `$LOOMERTO_PLANS_ROOT`）保留给「一份库里有好几份」。**`--profile` / `$LOOMERTO_PROFILE` 已从包里删除**：`plans_root()` 不再推断 `~/.hermes/...`，`exec --profile` 也删了（转录路径改由调用方 `--transcript <路径>` 给，`workers.py` 里那三个 hermes_home/live_root/transcript_path 助手一并删掉）；两个都没给时只看**当前目录的 `plan.json`**（没有就退 2 并打印该给什么）。 | 已落地 `c0ad8c8` |

| **R-14** | **命令分组**：「`loomerto new` 改成 `loomerto plan new`；`loomerto task` 改成 `loomerto task new`」 | `plan` 与 `task` 成了**分组**（各带子命令表），`plan new` = 原来的 `new`、`task new` = 原来的 `task`；顶层的 `new` / `task` **已不存在**（旧写法会退 2 并列出可用命令）。其余 15 个命令仍是平铺的 | 已落地 `c0ad8c8` 之后 |
| **R-15** | 「还要有一个 `loomerto open` 命令，用以**从 1 个 json 打开可编辑的画布**」 | `open`：起纯 stdlib 本地服务（只绑 `127.0.0.1`，默认自动挑端口 + 开浏览器），画布可改 标题/做什么/判据/认领人/类型/状态、新建任务与块、拖动改同泳道先后；写回走 `edits` → `store.commit()`（json + 三视图同步），带 `rev` 冲突检查（409）。实现 = `loomerto/serve.py` + `loomerto/assets/canvas.html`；协议 = [`docs/canvas-sync.md`](docs/canvas-sync.md) | 已落地 |

## 3. CLI 现状（摘要，细节见 `docs/cli-reference.md`）

17 个子命令（其中 `plan new` / `task new` 是分组）+ 4 个别名（`doing`=exec、`threads`=workers、
`compress`=collapse、`info`=show）：

- **建**：`plan new`（一份 plan）｜`task new`（任务线）｜`block`（可认领的块，带 `doc` + `done_when` 最好）
- **结构**：`expand`（块→任务流程）｜`collapse`（任务→块）｜`rm`（真删，被引用时默认拒删）
- **状态与身份**：`set`（改状态，自动记「谁在做」）｜`exec`（谁在做 + 子代理线程）｜`note`（写日志）
- **看**：`list`｜`current`（现在该谁动）｜`show`（**一个**块/任务的详情，只读）｜`check`（图质量，有错退 1）｜`workers`（线程还在动吗，⚠/❌ 退 1）
- **出**：`render`（重渲 md/html/canvas）｜`digest`（提醒文本）
- **画布**：`open`（起本地服务，从 1 个 json 打开**可编辑**的画布；只绑 127.0.0.1）

退出码约定：参数错 / 找不到对象 → **2**；`check` 有错误 → **1**；`workers` 有 ⚠/❌ → **1**；其余 → 0。

## 4. 缺口（拆完之后的落点）

**拆分（R-08）已落地** ⇒ 下面每个缺口现在都有明确落点，不必再散着补：

| 缺口 | 落在哪 |
|---|---|
| R-02 画布写回的**剩余部分**（删块、跨泳道移动、改 `deps`/`review_of`） | 协议与冲突规则已写定（[`docs/canvas-sync.md`](docs/canvas-sync.md)）；剩下这三类都**先要在 `model.py` 里长出结构演算**（移动块 = 改 id + 把引用它的 `deps` / `review_of` 全部重接 —— 现在只有 `expand` / `collapse` 会做这件事），画布层才可能接上 |
| R-04 状态约束 / R-05 协作者校验 | **改动现在只有一份实现**（`edits.py`）：加一个 `validate(plan, who, what)` 在 `set_status` / `add_block` / `add_task` 入口处调用即可 —— 命令与画布同时受约束，不必动 17 个命令 |
| R-06 多 plan 切换 | 服务层已在 `serve.py`（只 import `store` + `edits` + `model`）；要一览就照 `cmd_list` 的路子遍历 `plans_root()` 下每个 `<slug>/plan.json`。**不许在服务里另存状态** |
| R-03 定点插入 | 结构演算在 `model.py`（`refs_to` / `block_deps` / `guard_acyclic` 同层加纯函数），CLI 只做参数解析与打印 |

**R-10 的一个边界（在此写定，免得日后反复问）**：默认 `blocked` 只管**显式建块**（`block` 命令）；
`expand --step` 追加的步骤留在 `pending` —— 它是「已经批过的那条活」的后续步骤，不是新提议。

**R-11 的落法**：包在仓库根，`skills/` 只带薄壳；调用约定对使用者不变（skill 里仍是
`python3 <skill>/scripts/plan.py <子命令> <slug>`），但**薄壳要先能找到包** —— 见
[`docs/architecture.md`](docs/architecture.md) §4 的四步查找与失败提示。

## 5. 决策点（待用户拍板）

1. **R-04 的「pid」到底要哪种**：主代理的进程 pid（本机可判活）、还是 Hermes 的 session/delegation id
   （跨机器可读）？我建议两者都收：`--agent-pid`（本机主代理）+ 现有的 `--delegation`（子代理线程），
   校验时至少给一个 —— 只有 pid 的话，跨机器/跨 profile 就没法回查。
2. **R-02 的写回边界**（**已按建议落地第一版**，并加了一条）：位置与结构 = 拖拽改同泳道先后；
   字段编辑 = 标题/做什么/判据/认领人/类型；**另加了「改状态」**（认领·开干·送审·打回·收工）——
   它走的是与 `loomerto set` **完全同一份实现**（`edits.set_status`）+ 枚举限制 + `rev` 冲突检查，
   不会两处漂；而「删块」「跨泳道移动」「改依赖接线」仍然不做（那会改块 id 或一脚踩坏判据，留命令层）。
3. **R-06 的服务边界**：本地 web 服务只绑 127.0.0.1、纯 stdlib（`http.server`），还是要能被别的机器访问？
   我建议**先只绑本机**，跨机器走 `file://` 共享目录或让每个 harness 读同一份 json。
