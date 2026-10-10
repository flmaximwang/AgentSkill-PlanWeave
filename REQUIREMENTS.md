# loomerto · 需求（单一入口）

**这份文件是 loomerto 需求的唯一入口。** 想知道「要什么、做到哪了、细节在哪」，从这里出发；
不要另建需求清单、也不要把需求散在各个 skill 的正文里 —— 正文只写「怎么做」，需求写在这。

> 最后对齐：2026-10-09 · **main 上的代码基线 `0e153a1`**（R-18 的 `5656229`、R-19 的 `f9b91b0`、
> R-22 的 `0e153a1` **都已经合进 main** —— 本文件头写过的「还没合入」已作废）；**R-23「block 命令面重排」
> 落在分支 `feat/block-cmd-surface`（代码 `804a898`），还没合进 main**；default profile 里的 skill 副本
> 已按 B 档 / R-22 / R-23 拉平（见 §4 末尾的拉平记录），`plan-weave` profile 那份仍是旧一代，待随该 bot
> 退役一并清。
> 变更纪律：需求条目只在**用户明确说了**或**用户拍板**之后才增删；实现状态变了改「现状」列，不新开一份。

## 0. 文档地图（每个细节去哪看）

| 文档 | 承担什么 | 什么时候读 |
|---|---|---|
| **本文件 `REQUIREMENTS.md`** | **需求单一入口**：目标 / 需求条目 / 现状 / 缺口 / 决策点 | 先读这个 |
| [`README.md`](README.md) | 仓库索引：这是干什么的、五个 skill 各是什么、安装 loop、盲测表 | 想装它 / 想找某个 skill |
| [`docs/cli-reference.md`](docs/cli-reference.md) | `plan.py` 全部子命令、参数、退出码（**现状清单**，逐条可与实现核对） | 要敲命令 / 要核对 CLI 面 |
| [`skills/loomerto/loomerto-plan/SKILL.md`](skills/loomerto/loomerto-plan/SKILL.md) | **操作细节**：模型（plan/task/block/run/exec）、状态表、粒度调整、谁在做+线程、一次回合的固定动作、坑 | 要动手改一份 plan |
| [`skills/loomerto/loomerto-remind/SKILL.md`](skills/loomerto/loomerto-remind/SKILL.md) | 提醒纪律：何时推、推给谁、静默与去重 | 要发提醒 |
| [`skills/loomerto/loomerto-check-temps/SKILL.md`](skills/loomerto/loomerto-check-temps/SKILL.md) | 交付前校验之一：临时文件闭环 | 送审 / 交接 / 收尾 |
| [`skills/loomerto/loomerto-check-commands/SKILL.md`](skills/loomerto/loomerto-check-commands/SKILL.md) | 交付前校验之二：每个节点的可执行命令与变量定义 | 送审 / 交接 / 收尾 |
| [`skills/loomerto/loomerto-intake/SKILL.md`](skills/loomerto/loomerto-intake/SKILL.md) | 后进来的人怎么用秒级只读证据接上（含 `references/read-only-evidence-recipes.md`） | 被 @ 进一段已经在跑的协作 |
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
| **R-01** | 每个节点要表明**谁认领了 / 谁在做**，并能给出**具体的子代理线程**，以便检查子代理是否正常 | `block.owner`（认领人）+ `block.exec`（`by`/`delegation`/`task_index`/`transcript`/`started`）+ 命令 `block set_status`（`--by`）/ `task set_status`、`workers`（七值，⚠/❌ 退 1）；三视图都显示「@认领人→@在做的人」与线程路径。SKILL.md 有专节 | 已落地 `3d774bd` |
| **R-02** | **人与 AI 双向对齐**：用户可以直接在画布上改 plan（改完自动同步 json 与 md）；AI 通过命令改 json 并同步 md 与画布。目的是不必用语言描述复杂流程 | **已落地**：`loomerto open <plan 数据文件>` 起本地服务（只绑 `127.0.0.1`、纯 stdlib），画布上可改 块的标题/做什么/判据/认领人/类型/**状态**、新建任务与新建块、拖动卡片改同泳道先后、**拖到别的泳道 = 换任务**（R-16）；每次改动走 `edits`（唯一实现）→ `store.commit()`，所以 json 与 `PLAN.md`/`plan.html`/`plan.canvas` 同时更新；前端带 `rev`（= `updated_at`），过期回 **409** 不自动合并。协议 = [`docs/canvas-sync.md`](docs/canvas-sync.md)。**故意不做**：删块/删任务、直接改 `deps`/`review_of`（会一脚踩坏判据或接线 ⇒ 走 `block remove` / `block bypass` / `block move` / `block expand` / `block compress`）；**命令层**后来按用户要求补了 `block deps`（R-22），画布上仍然不做 | 已落地 |
| **R-03** | AI 能用 CLI 做节点级结构编辑：**在某个节点之后 / 两个节点之间 / 最早的节点之前插入节点**；**删除节点**；**把一个节点拆成一个任务流程** | 拆成任务流程 = `block expand`（块→任务，含后续 `--step`）；删除 = `block remove`（块）/ `task remove`（任务，连带它的块）——**要把引用一起改对就用 `block bypass`**（R-23）；**定点插入 = `block insert`**（`--before` / `--after`：插到锚块之前时新块接手锚块原来等的东西、锚块改成只等新块；插到之后时原来等锚块/评审锚块的改成等新块）—— 「两节点之间」= 插到后一个之前，「最早节点之前」= 插到该任务第一个块之前；成环报错且一字不写，`--dry-run` 只改内存副本 | 已落地 `d47d2ed` |
| **R-04** | CLI 能快速改状态，但**带约束**：改为「已认领」必须附上**被谁认领**；改为「进行中」必须附上**主代理或子代理 pid** | `block set_status … --by` 会写 `exec.by`（认得人是谁），同一句里 `--delegation` / `--task-index` / `--transcript` 认得线程与转录；**状态已会卡参数**（在途状态才收线程登记、产物只在 done 收），但**没有强制校验**（`--by` 仍可省、也无 pid 字段，改为 claimed/running 时不缺信息也能过）。2026-10-08 起 `check` 会盯住这条的镜像面：「已认领 / 进行中 / 待评审 却没有负责人」发 ⚠（R-18）—— 仍是告警，不是硬校验 | 待做 |
| **R-05** | 每个项目要先登记**协作者**（人类 / agent），节点必须派给协作者中的一员 | `plan new --owner "id=kind:label[@channel]"` 写 `participants`，`block add --owner` / `block assign --to` 只是个自由字符串（assign 会在 id 不在名单里时打一行 ⚠）；**不校验** owner 是否在 participants 里，也不强制「先有协作者」 | 部分 |
| **R-06** | 给用户的界面**不一定是 html 文件**：也可以是一个 Python 起的本地 web 服务，能在**多个 plan 之间切换** | **服务层有了**：`loomerto open` 就是纯 stdlib 的本地服务（一个进程服务一份 plan，`Ctrl-C` 停）。**还缺**：多 plan 一览与切换的界面（`list` 仍是一行文本；换一份要重开一次 `open`） | 部分 |
| **R-07** | **需求要在 skill repo 里留档**，方便后期对齐；文档要有**单一入口**，入口要**完整指路**到细节文档 | 本文件 + [`docs/cli-reference.md`](docs/cli-reference.md) 就是这次的产物；README 加了「文档地图」指向这里 | 已落地（本次提交） |
| **R-08** | 工程形态：能当**跨 harness 的工作台**，同时**自己不是 harness 应用**；核心可被别的程序用，CLI 只是其中一层 | 已拆成 6 层，包在**仓库根** `loomerto/`：`model` / `store` / `render` / `edits` / `serve` / `workers` / `cli`。核心不 print、不 `sys.exit`（抛 `PlanError`），所有写入过 `store.commit()` 一处、所有改动过 `edits` 一处；别的程序 `import loomerto` 即可用；skill 侧只留一个薄壳 `scripts/plan.py` | 已落地 |
| **R-09** | 把目前支持的 CLI 操作**整理出来回报** | [`docs/cli-reference.md`](docs/cli-reference.md)：12 个一级命令（`plan` / `task` / `block` 三个分组 + 8 个单层动作）逐条列参数与退出码；改过命令就重跑文件头那段 `for c in … --help` 生成底稿，别手抄 | 已落地 |
| **R-10** | **新建节点默认是「待批准」**（`blocked`），而不是 `pending`；只有当 AI 判断这块无需审批就能干时，才用 `pending` | `block add` / `block insert` 的 `--status` 默认是 `blocked`（=界面上「待批准」，等有人点头）；`--status pending` 是显式放行。`block expand --step` 追加的步骤仍是 `pending`（见 §4 说明） | 已落地 |
| **R-11** | **这个 repo 本身升级成一个「带 skill 的 AI 原生 python 包」**：包放仓库根目录，skill 随包发布；包名要**与 GitHub 上已有的项目区分开** | 包已落在仓库根 `loomerto/`（`pyproject.toml` + console scripts `loomerto`／`plan` + 包数据 `assets/plan.html`）；skill 只带薄壳。**命名依据**：① `PlanWeave` 已被 [`GaosCode/PlanWeave`](https://github.com/GaosCode/PlanWeave)（★411，正是我们借模型的那个项目）占用，`planweave` 与它直接撞名；② 最终名 **loomerto = loom + concerto**，取协奏曲「独奏与乐队主次分明、却同演一曲」的意象（一个人 + 几个 agent 各按声部推进同一份 plan）。冲突筛查（2026-10-07 实测）：PyPI `loomerto` **未注册**、GitHub **无同名仓库**（比前一个候选 `loomery` 更干净 —— 后者 PyPI 未注册但 GitHub 有 ★3 同名小仓库）。**装机现状**：default profile 五条 skill 装在类目 `loomerto`（仓库与 profile 两侧统一为 `loomerto`，含 intake 与 maintain-the-loomerto-package），lock 的 identifier/URL 指向 `flmaximwang/Loomerto`、revision `7eed38f`，装好的副本与仓库逐份 `diff -rq` 一致；`plan-weave` profile 里是旧一代（类目 `plan-weave`，identifier 仍是旧仓库名），待随该 bot 退役一并清 | 已落地 |
| **R-12** | 「**给一个 cli 入口**」—— 要能按 ref（`T-003#B-004` 这种）查**一个块/一条任务**的详细信息，而不是只给命令清单 | 两个只读入口（都带别名 `info`）：`py block show <slug> <块ref> [--json] [--runs N]` 给 状态/类型/归属/认领(含时刻)/在做+线程+转录/做什么/判据/依赖/评审/返工 ⟲N/产物/run/三视图路径；`py task show <slug> <任务ref> [--json]` 给 状态/认领/前置/块一览。纯只读（不落盘、不重渲、不写日志），ref 与对象类型不符退 2 并点明该用哪个 | 已落地 `d47d2ed` |
| **R-13** | **调用式**：「我希望的格式是 `loomerto --plan <plan data file> command`」；并且「**不要支持 profile** —— 我从来没有定义过 loomerto 就是给 hermes 用的」 | 全局旗标换成 **`--plan <plan 数据文件>`**（= `$LOOMERTO_PLAN_FILE`；给目录也行）：只认这一份，**命令里不再写 slug**（位置参数整体左移一位：`block set <ref> <status>`、`task set_status <ref> <status>`、`block show/rm/insert/move/expand/collapse <ref>`、`task show/rm <ref>`、`note <text>`）。`--plans-root`（= `$LOOMERTO_PLANS_ROOT`）保留给「一份库里有好几份」。**`--profile` / `$LOOMERTO_PROFILE` 已从包里删除**：`plans_root()` 不再推断 `~/.hermes/...`，`exec --profile` 也删了（转录路径改由调用方 `--transcript <路径>` 给，`workers.py` 里那三个 hermes_home/live_root/transcript_path 助手一并删掉）；两个都没给时只看**当前目录的 `plan.json`**（没有就退 2 并打印该给什么）。 | 已落地 `c0ad8c8` |

| **R-14** | **命令分组**：「`loomerto new` 改成 `loomerto plan new`；`loomerto task` 改成 `loomerto task new`」 | `plan` 与 `task` 成了**分组**（各带子命令表），`plan new` = 原来的 `new`、`task add` = 原来的 `task`；顶层的 `new` / `task` **已不存在**（旧写法会退 2 并列出可用命令）。后续 R-17 把 `block` 也升成分组、`set`/`rm`/`expand`/`collapse`/`show`/`move` 全部挪进分组，顶层的平铺动作只剩 8 个 | 已落地 `c0ad8c8`（R-17 再改） |
| **R-15** | 「还要有一个 `loomerto open` 命令，用以**从 1 个 json 打开可编辑的画布**」 | `open`：起纯 stdlib 本地服务（只绑 `127.0.0.1`，默认自动挑端口 + 开浏览器），画布可改 标题/做什么/判据/认领人/类型/状态、新建任务与块、拖动改同泳道先后、跨泳道拖 = 换任务（R-16）；写回走 `edits` → `store.commit()`（json + 三视图同步），带 `rev` 冲突检查（409）；**观感与只读看板共用 `loomerto/assets/theme.css`**（颜色/字体/状态胶囊/按钮/分隔线/进度条/图例一份来源，两页不会各长一套）。实现 = `loomerto/serve.py` + `loomerto/assets/canvas.html`；协议 = [`docs/canvas-sync.md`](docs/canvas-sync.md) | 已落地 |
| **R-16** | 「Loomerto 画布现在要支持**跨 task 拖动 block**」（2026-10-07，要求在新 worktree 里实现） | 画布上把卡片拖到**别的泳道**（卡片之间＝插在那张卡前面；泳道空白处＝追加到末尾）即换任务。**块 id 是位置即身份**，所以一次 `move` 做三件事：换 id（目标任务里取最小空位）→ 把引用旧 id 的 `deps` / `review_of` / `expanded_from.block` **一次重接** → **查环，成环就拒改且一个字不写**（400，界面显示原因）。落点是 `edits.move_block`（CLI 与画布共用）；命令入口 = `loomerto block move <ref> --task T-00N [--index N]`；协议第六个 op = `move`（响应带 `ref` = 新 id，前端靠它保住选中）。源任务被搬空**不删任务**（空泳道留着）。故意不做：只在画布上做「拖」，不做「拖的同时顺带改字段」 | 已落地 `7b71629`（合入 main；装好的 `loomerto` 也会立刻认 `move` —— editable 安装指的就是这个 checkout） |

| **R-17** | **命令面按对象分组（第二轮）**：「`block` 命令也升级为分类命令，原 `block` 改为 `block new`，`set` 改为 `block set`，`expand`/`collapse` 都改成 `block` 子命令，`rm` 拆份到 `task` 和 `block` 中，还要加 `insert` 命令，`show` 也拆份到 `task` 和 `block` 中」；「`block describe` 用于修改 block 详情（要留日志）」；「`block assign` 用于为参与者分配 block」；「exec 命令与 set 命令有交叉，把 exec 并入 set」；「set 需要支持在设置不同的 status 时限制不同的参数」；「在新的 worktree 中操作」 | 一级命令 **18 → 12**：`plan` / `task` / `block` 三个分组 + `note` / `digest` / `render` / `check` / `current` / `workers` / `list` / `open` 八个单层动作（共 23 个叶子命令）。`task` 组 = `new` / `set` / `rm` / `show`；`block` 组 = `new` / `insert` / `set` / `describe` / `assign` / `move` / `expand` / `collapse` / `rm` / `show`。**`exec` 并入 `set`**（`--by` / `--delegation` / `--task-index` / `--transcript` / `--unset` 都成了 `set` 的旗标，`doing` 别名随之删除），顶层 `set` / `rm` / `move` / `expand` / `collapse` / `show` 一律删除（旧写法退 2 并列可用命令）。**`block insert` 新增**（见 R-03）；**`block move` 是 R-16 那条 move 的新家**（顶层 `move` 删掉，画布与服务不受影响）。**`block describe`**：只改块的详情（标题/做什么/判据/类型），不动状态、改动记进日志。**`block assign`**：把块指派给某个参与方（`--to` / `--unset`），不动状态，记 `kind=assign`。**`set` 按状态卡参数**：`edits.BLOCK_SET_FLAGS` / `TASK_SET_FLAGS` 一张表 —— 在途状态才收 `--by`/线程三件套、`--artifact` 只在 `done`，命令与画布同一处受约束。跨组错用给人话错误（`task set_status <块ref>` → 「这是块不是任务 —— 块状态用 `block set`」）。**顺带补的守卫**：`task remove` 除任务级 `deps` 外，现在还拒删「有别的任务的块依赖它」的任务（`--force` 才删），不然那几条依赖会变悬空 | 已落地 `d47d2ed` + 合并分支（见文件头基线） |

| **R-18** | **「Loomerto 现在要求待认领状态不能有负责人」**；并「顺便理一下每个状态和负责人的关系」（2026-10-08，要求在新 worktree 里做） | **一张表 + 一条派生**。①`model.STATUS_OWNER` 把「显示状态 × 负责人」写成三档：`never`（待认领）/ `required`（已认领、进行中、待评审）/ `may`（待批准、等前置、已完成、已取消）。任务是泳道，它的 `owner` 是「谁负责这条线」，不归这张表管。②`block_effective` 兑现 `never`：**`pending` + 依赖就绪时 —— 有 owner ⇒ 派生 `claimed`（已认领：有人接了、还没开干）；无 owner ⇒ `ready`（待认领）** —— 「待认领」的定义里就含「还没人接」，靠派生保证（写 `ready` 仍被拒），不必人手工同步；等前置 / 待批准 可以有 owner（先派活、写「等谁点头」）。③`required` 那侧由 `check` 盯：**已认领 / 进行中 / 待评审 却没有负责人 → ⚠**（硬校验属 R-04）。④`stale_blocks` / `workers` 的「在途」改按**存储**状态判 —— 派生出来的已认领既没登记线程、也没有开工时刻（`status_since` 还是当初置 `pending` 那一刻），否则悬置/线程报告会误报。⑤前端两份资产同一规则：`plan.html` 的 `eff()` 加 owner 分支；`canvas.html` 的派生说明改成按情形解释。**实测影响（真实 11 份 plan 逐份对拉）**：14 个块 待认领→已认领、10 条泳道 ready→running（**全部是本来就写了 owner 的块**，没有改一个字数据）；`check` / `list` / `workers` 输出**逐字节不变**；`insert`/`expand`/`collapse` 的 `--dry-run` sha 一字不变 | 已落地 `5656229`（**已合入 main**） |
| **R-19** | **「能不能把 Block 整理成一个单独的 class？」**；拍板：「**先按 B 做吧，让整套代码更容易查看**，C、D 先计入 issue」（2026-10-08） | **B 档 = 只收口「形状」，不改任何对外形状。** ①`model.BLOCK_FIELDS`：键 → 默认值/工厂（`list` / `dict` 写成工厂，可变默认值不共享对象），**一个块有哪些键只有这一处**；`BLOCK_HISTORY_FIELDS` 单独记下只有 `block collapse` 会写的 `folded_from`（不是每个块都有，所以不进表，但 `normalize_block` 不许删）。②`model.new_block(bid, …)`：**建块的唯一一处字面量** —— 以前同一份字典在四处各抄一遍（`edits.add_block` / `edits.insert_block` / `cli` 的 `expand` 步骤与 `collapse` 合并块），加一个键要追四处、漏一处不报错；`**history` 只收历史键，别的键绕不进去（`PlanError`）。③`model.normalize_block` / `normalize_plan` + `store.load()`：**老数据缺键只补不改、不删**（实库 9 份 plan 的 158 个块没有 `exec` 就是这个后果）；读到的块总是完整形状，**要不要落盘由调用方决定**（下一次 `commit()` 顺手材料化，`exec: {}` 就是「没登记线程」，语义不变）。**行为差异（有意，逐条对拉过）**：新建块键顺序统一成表里的顺序（以前只有 collapse 那条路把 `exec` 写在最后）；`--step "…:: kind"` 给了 `KINDS` 以外的类型，以前会静默写进 plan.json，现在按建块同一道闸退 2 且什么都不写。**其余逐字节不变**：文件模式 + 库模式跑完所有叶子命令（含 9 条负例）、真实 11 份 plan × 6 条只读命令（66 条，改动前后的两份 checkout 对拉）stdout 全同 | 已落地 `f9b91b0`（分支 `feat/block-schema`，**未合入 main**） |
| **R-20** | **C 档：块的只读轻量包装类 `Block`**（叠在 `BLOCK_FIELDS` 之上，只给读的一侧用） | **待做**：见 [issue #1](https://github.com/flmaximwang/Loomerto/issues/1)。范围先划死 —— 只读属性代理 + `to_dict()`，**不提供 setter**、不承担不变式；写入仍只走 `edits.*`，`plan.json` 结构不变。之所以单开一档：`loomerto/*.py` 里有 ~155 处直接摸块字典，且要过 `canvas-sync` 的 op 与两个前端的 `GET /api/plan` 这两条跨 JSON 边界 | 待做（issue #1） |
| **R-21** | **D 档：`plan`/`task`/`block` 变成对象图（ORM 式）**，dict 只出现在序列化时 | **待做 / 不排期**：见 [issue #2](https://github.com/flmaximwang/Loomerto/issues/2)。与三条硬约束正面冲突：`plan.json` 是唯一真相且协议就是 JSON（两个前端各有一份内联 JS 直读键）、块的 id 就是位置（`move_block` 靠它换号重接）、零依赖 + `>=3.9`（`dataclass` 可以，`pydantic`/`attrs` 不行）。真要做先想清楚 issue 里列的四件事 | 待做（issue #2） |

| **R-22** | **「loomerto block 现在没有修改块依赖的功能，添加一下」**（2026-10-08 · 用户原话） | **新增 `block deps <块ref>`**：`--deps <一串>` **整组替换**（给空 = 清空前置）、`--add` / `--rm` 加减 —— 三种改法只能选一种，一个都不给退 2。三道闸收在 `edits.set_deps` **一处**（命令层只管参数，将来任何前端共用）：① 每条依赖必须**已经存在**（悬空依赖 `check` 会一直报错，块挂在那儿永远等不到）——依赖写成任务（`T-002`）也拒（块只能等另一个块）；② 引用当场**规整成规范 id 并去重**（`B-003` → `T-002#B-003`）；③ 改完**查环**，成环抛 `PlanError` ⇒ 不 `commit()`、**一个字都不写**（与 `move` / `insert` / `expand` / `collapse` 同一纪律）。`--rm` 一条本来就不等的 ⇒ **退 2**，不许静默成功。改完打两行 ⚠（按需）：所属任务的**任务级**依赖也算它的前置；新等上的块是 `cancelled`（永远不会 done ⇒ 这块一直「等前置」）。日志 `kind=deps`（`note --kind` 也收它）。**画布上仍然不做**（R-02 的「故意不做」不变：手改接线会一脚踩坏图）。**验收**：文件模式 + 库模式逐条跑完 24 个叶子命令、9 条负例（自指 / 不存在 / 写成任务 / `--deps`+`--add` 同给 / 什么都不给 / ref 是任务 / 找不到对象 / 成环 / 无变化）、真实 11 份 plan × 7 条只读命令与改动前**逐条对拉 77/77 逐字节相同** | 已落地 `0e153a1`（**已合入 main**；命令名见 R-23） |

| **R-23** | **「重排一下 loomerto block 的命令顺序与名称」**（2026-10-09 · 用户原话 + 逐条拍板）—— ① `new`→`add`、② `rm`→`remove`、③ `insert`、④ **新增 `bypass`**（删掉中间节点，把前后节点直接连起来）、⑤ `expand`、⑥ `compress`（**删掉 `collapse` 子命令**）、⑦ `show`、⑧ `set`→`set_status`、⑨ `describe`→`set_desc`；追加拍板：⑩ `deps` ⑪ `assign` ⑫ `move` **保留**、排在这九条之后；`set_desc` **继续拆成** `set_title` / `set_doc`；再加 `set_type` / `set_input` / `set_output` / `set_command`（「设置具体的执行命令」）/ `set_audit`（「设置验收标准」），并交代「**后面添加其他直接设置 block 属性的方法**」 | **`block` 组 = 18 条，顺序与名字以 `block --help` 为准**（逐条表见 `docs/cli-reference.md` §0）：`add / remove / insert / bypass / expand / compress / show / deps / assign / move / set_type / set_title / set_doc / set_status / set_input / set_output / set_command / set_audit`。旧名 `new` / `rm` / `set` / `describe` / `collapse` **一律退 2**（不留别名）；`info` / `threads` 两个读命令别名照旧。**`bypass <块ref>`**：把一个中间块从链上摘掉（`A → B → C` ⇒ `A → C`）—— 它等的前置（`deps` + `review_of`）直接接给「原来等它的块」；与 `remove` 的分工是「谁替你把引用改对」：`remove` 见有人引用就停手（要人加 `--force` 承担悬空），`bypass` 替人改对再删。退化情形（它谁也不等 / 没人等它）照做但打 ⚠；唯一拒改的是「有块评审它、而它自己谁也不等」。**一条属性一条命令**：`block set_<属性> <块ref> <值>`，值**整组替换**、留空 = 清空（标题除外），共用 `edits.set_field`；**没有变化 ⇒ 退 2 且一个字不写**（与 `set_deps` 同一纪律）；`set_audit` 的值**一条判据一个位置参数**（`block set_audit <块ref> <判据1> <判据2> …`，参数里的 `;` 仍算分隔）。加一条属性 = `model.BLOCK_FIELDS` 一处 + `cli._SET_ATTRS` 一处 + `_parser()` 里一行 —— 这就是「后面添加其他属性方法」那条路。**块新增三个键** `input` / `output` / `command`（走 `BLOCK_FIELDS` 唯一声明处；老数据由 `normalize_block` 只补不改 —— 只读命令一个字节都不动），`block show` 把它们显示出来。**`task` 组跟着改名**（追加拍板「都做」）：`task add` / `task set_status` / `task remove` / `task show`（+`info` 别名），旧名 `task new` / `set` / `rm` 一律退 2。**不动的**：`set_status` 的旗标与「按状态卡参数」的表（`BLOCK_SET_FLAGS`）、画布走的那两条（`edits.set_status` / `edit_block`）。日志里 `compress` 事件的 `kind` 从 `collapse` 改成 `compress`（`note --kind` 两个都收）。**验收**：库模式逐条跑完 34 个叶子命令 + 51 条正向/负例（5 个 block 旧名、3 个 task 旧名一律退 2）；真实计划库 `list` / `current` / `check` / `workers` 对 `d062f32` **逐字节相同**；薄壳 `plan.py` 跑通（它只注入 `--plans-root`，不认命令名） | 已落地 `804a898` + 后续提交（分支 `feat/block-cmd-surface`） |

## 3. CLI 现状（摘要，细节见 `docs/cli-reference.md`）

12 个一级命令（`plan` / `task` / `block` 是**分组**，动作都在二级；其余 8 个是单层动作）+ 2 个别名
（`info` = `task show` / `block show`、`threads` = `workers`）；块的一级动作共 **31 个叶子命令**
（+3 个别名）。**`block` 组的顺序与名字以 `block --help` 为准**（R-23 重排）：

- **`plan`**：`new`（一份 plan）
- **`task`**：`new`（任务线）｜`set`（任务状态；在途时才登记在做的人与线程）｜`rm`（真删任务，连带它的块）｜
  `show`（一条任务的详情，只读）
- **`block`**：`add`（追加到任务末尾）｜`remove`（真删块，被引用时默认拒删）｜`insert`（插到某块之前/之后，
  接线自动改对）｜`bypass`（把一个中间块从链上摘掉，前后直接接起来）｜`expand`（块→任务流程）｜
  `compress`（任务→块）｜`show`（**一个**块的详情，只读）｜`deps`（**事后改前置依赖**：`--deps` 整组替换 /
  `--add` / `--rm`，查存在性·自指·环）｜`assign`（把块指派给某个参与方）｜`move`（换泳道：换 id + 重接引用 + 查环）｜
  `set_type` / `set_title` / `set_doc` / `set_input` / `set_output` / `set_command` / `set_audit`
  （**一条属性一条命令**：`block set_<属性> <块ref> <值>`，值整组替换、留空 = 清空）｜
  `set_status`（改状态 + 谁在做 + 子代理线程 —— 原 `set`，旗标与「按状态卡参数」的表一律不变）
- **单层**：`note`（写日志）｜`current`（现在该谁动）｜`check`（图质量，有错退 1）｜
  `workers`（线程还在动吗，⚠/❌ 退 1）｜`render`（重渲 md/html/canvas）｜`digest`（提醒文本）｜`list`｜
  `open`（起本地服务，从 1 个 json 打开**可编辑**的画布；只绑 127.0.0.1）

退出码约定：参数错 / 找不到对象 → **2**；`check` 有错误 → **1**；`workers` 有 ⚠/❌ → **1**；其余 → 0。

## 4. 缺口（拆完之后的落点）

**拆分（R-08）已落地** ⇒ 下面每个缺口现在都有明确落点，不必再散着补：

| 缺口 | 落在哪 |
|---|---|
| R-02 画布写回的**剩余部分**（删块、删任务、直接改 `deps`/`review_of`） | 协议与冲突规则已写定（[`docs/canvas-sync.md`](docs/canvas-sync.md)）。**跨泳道移动已落地**（R-16）：结构演算在 `edits.move_block`（换 id + 重接 `deps`/`review_of` + 查环），CLI（`block move`）与画布共用。剩下的「删块 / 删任务」要在**界面口径**上先想清楚（`block remove` 会检查谁引用它、被引用时要人点头；要连着接线一起改对走 `block bypass`，R-23）；「改依赖接线」已有命令层入口 **`block deps`**（R-22，含查环），画布上仍不做 |
| R-04 状态约束 / R-05 协作者校验 | **改动现在只有一份实现**（`edits.py`）：加一个 `validate(plan, who, what)` 在 `set_status` / `add_block` / `add_task` 入口处调用即可 —— 命令与画布同时受约束，不必动每一条叶子命令 |
| R-06 多 plan 切换 | 服务层已在 `serve.py`（只 import `store` + `edits` + `model`）；要一览就照 `cmd_list` 的路子遍历 `plans_root()` 下每个 `<slug>/plan.json`。**不许在服务里另存状态** |
| R-19 顺带给 `check` 补一条「块形状」硬校验（缺键 / 类型不对 ⇒ ✗ 退 1） | 落点 = `cli.cmd_check`：`model.normalize_block` 只补不改，所以「缺什么」要**在补之前**读（`store.load()` 已经补过了 ⇒ 校验得改成读原始文件，或让 `load()` 把「补了哪些键」带出来）。**难度在这**：`load()` 现在是无返回值地补齐，`check` 想报「这份 plan 的哪几个块缺键」就得先想清这条信息怎么传（不建议让 `list`/`current` 这些只读命令也跟着报）。B 档只做收口，这条留待拍板 |
| R-20 C 档 / R-21 D 档 | 都已开 issue（[#1](https://github.com/flmaximwang/Loomerto/issues/1) / [#2](https://github.com/flmaximwang/Loomerto/issues/2)）；真要做时落点都在 `model`（形状与派生之上），**不动 `plan.json` 结构、不动 `canvas-sync` 协议** |

**skill 副本的拉平记录（2026-10-08，B 档）**：`skills/loomerto/loomerto-plan/SKILL.md` 与
`skills/loomerto/loomerto-check-commands/SKILL.md` 是**发布源**；default profile 里装的副本在
`~/.hermes/skills/loomerto/<同名目录>/`，改完 `cp` 过去再 `diff -rq`（除 `.DS_Store` 外应为空）。
`plan-weave` profile 那份（`~/.hermes/profiles/plan-weave/skills/loomerto/`）是旧一代，**不动**。

**R-22 的拉平（2026-10-08）**：`block deps` 那几段在**两份都改了**（仓库源 + `~/.hermes/skills/loomerto/loomerto-plan/SKILL.md`）
—— 没有整份 `cp`：default profile 的副本目前**另有会话写进去的段落**（约 100 行：`--no-render` 收尾、并行建块、
`--artifact` 一串写法等），仓库源还没有那份回移植。所以这一轮的拉平是「同一段改动分别打在两份上」，
`diff -rq` **不为空是预期的**，别拿它当漏改的判据（用 `grep -c "block deps"` 两份都该有：仓库源 4 处、profile 副本 6 处
—— 多出的两处是副本先行段落里的同段改写）。

**R-23 的拉平（2026-10-09）**：这一轮改的是**命令名**（跨文件主键），所以四份 skill 一起动了。
改之前先核过方向：**仓库源与 default profile 副本当时逐字节相同**（`diff -q` 四份全空 —— R-22 那份「副本先行」
的段落早前已被回移植），所以这次是**整份 `cp`**（仓库源 → 副本），没有覆盖任何只在副本里的段落；
拉平后 `diff -rq skills/<类目>/<名> ~/.hermes/skills/<类目>/<名>`（除 `.DS_Store`）**全空**。
判据（两份都要相同）：`grep -c "block set_status\|block set_title\|block set_doc\|block set_type\|block set_audit\|block set_input\|block set_output\|block set_command\|block bypass\|block add\|block remove\|block compress"`
两份各 **42** 处。**还改了 profile 里的自维护 skill**：`~/.hermes/skills/loomerto/maintain-the-loomerto-package/`
（SKILL.md 硬规则 5/6 + 新加的「改命令面」一节 + 两份 `references/`）—— 它在仓库里没有源，只在 profile 里，
所以不在 `diff -rq` 的对照表里。**绑定关系**：profile 副本里的新命令名只在「装好的 CLI（= 主 checkout 当前那一支
= `feat/block-cmd-surface`）」上成立 —— 主 checkout 切回 `main` 之前，要么先把这个分支合进 main，要么知道
「副本比 CLI 新」这件事。

**R-10 的一个边界（在此写定，免得日后反复问）**：默认 `blocked` 只管**显式建块**（`block add` / `block insert`）；
`block expand --step` 追加的步骤留在 `pending` —— 它是「已经批过的那条活」的后续步骤，不是新提议。

**R-11 的落法**：包在仓库根，`skills/` 只带薄壳；调用约定对使用者不变（skill 里仍是
`python3 <skill>/scripts/plan.py <子命令> <slug>`），但**薄壳要先能找到包** —— 见
[`docs/architecture.md`](docs/architecture.md) §4 的四步查找与失败提示。

## 5. 决策点（待用户拍板）

1. **R-04 的「pid」到底要哪种**：主代理的进程 pid（本机可判活）、还是 Hermes 的 session/delegation id
   （跨机器可读）？我建议两者都收：`--agent-pid`（本机主代理）+ 现有的 `--delegation`（子代理线程），
   校验时至少给一个 —— 只有 pid 的话，跨机器/跨 profile 就没法回查。
2. **R-02 的写回边界**（**已落地**，含后来补的 R-16）：位置与结构 = 拖拽改同泳道先后 + 跨泳道换任务；
   字段编辑 = 标题/做什么/判据/认领人/类型；**另加了「改状态」**（认领·开干·送审·打回·收工）——
   它走的是与 `loomerto block set_status` / `task set_status` **完全同一份实现**（`edits.set_status`）+ 枚举限制 + `rev` 冲突检查，
   不会两处漂；而「删块」「删任务」仍然不做（那会一脚踩坏判据或接线），留命令层。「改依赖接线」原先也不做，
   2026-10-08 用户要求后落成命令层入口 **`block deps`**（R-22：三条闸 + 查环，成环一个字不写）；
   跨泳道换任务是把 id 与引用**一次改对**，与「手改接线」不是一回事。
3. **R-06 的服务边界**：本地 web 服务只绑 127.0.0.1、纯 stdlib（`http.server`），还是要能被别的机器访问？
   我建议**先只绑本机**，跨机器走 `file://` 共享目录或让每个 harness 读同一份 json。
