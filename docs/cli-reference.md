# `loomerto` 命令行参考（现状清单）

> **这份文件是 CLI 面的现状**，逐条从代码里的 `argparse` 取（2026-10-08 · 代码基线 `3acfd7b`）。
> 需求与缺口看 [`../REQUIREMENTS.md`](../REQUIREMENTS.md)；模型与操作纪律看
> [`../skills/plan-weave/maintain-a-shared-plan/SKILL.md`](../skills/plan-weave/maintain-a-shared-plan/SKILL.md)。
> 重新生成底稿的办法（改过命令后必须重跑，别手抄）：
> ```bash
> for c in plan task block note digest render check current workers list open; do loomerto $c --help; done
> for c in "plan new" "task new" \
>          "task set" "task rm" "task show" \
>          "block new" "block insert" "block set" "block describe" "block assign" "block move" \
>          "block expand" "block collapse" "block rm" "block show"; do loomerto $c --help; done
> ```

## 0. 怎么调用

**一级命令 = 对象或全局动作，动作一律放二级**：`plan` / `task` / `block` 是**分组**（各自带子命令表），
`note` / `digest` / `render` / `check` / `current` / `workers` / `list` / `open` 是单层命令 —— 共 12 个一级名字。
别名只给读命令的顺手写法：`info` = `task show` / `block show`，`threads` = `workers`。

三种等价写法（实现都在仓库根的 `loomerto` 包里，见 [`architecture.md`](architecture.md)）：

```bash
loomerto <全局旗标> <子命令> [参数]            # 装过包：uv tool install --editable <repo> → ~/.local/bin/loomerto
python3 -m loomerto <全局旗标> <子命令> [参数]  # 不装：在仓库根目录里跑
python3 <skill>/scripts/plan.py <全局旗标> <子命令> [参数]   # skill 侧的薄壳：自己交代 plans 根、自己找包
```

```bash
py() { python3 "$P" "$@"; }   # $P = <profile>/skills/plan-weave/maintain-a-shared-plan/scripts/plan.py
```

- 纯 stdlib、零依赖、**不需要服务**；`requires-python >= 3.9`。
- **一份 plan 在哪，永远由调用方说清** —— loomerto 不认任何 harness 的目录，也**没有 profile 这个概念**：
  - `--plan <plan 数据文件>`（= `$LOOMERTO_PLAN_FILE`）：只认这一份；**此后命令里不写 slug**。
    给目录（或目录路径）也行，按其中的 `plan.json` 算；数据文件叫什么名都行（`mine.json` 也可以）。
    例：`loomerto --plan ./plan.json block set T-001#B-002 done`。
  - `--plans-root <目录>`（= `$LOOMERTO_PLANS_ROOT`）：一份 plan 库（里面每个 slug 一个目录）；命令里**要 slug**。
    例：`loomerto --plans-root ~/plans block set my-plan T-001#B-002 done`。
  - 两个都不给：按**当前目录的 `plan.json`** 算（它存在才认，等价于 `--plan ./plan.json`）；都没有就退 2
    并把该给什么打印出来。`plan new` 必须显式说落在哪（`--plan <路径>/plan.json` 或 `--plans-root <目录>` + slug）。
  - 两个都给时**按 `--plan` 算**（打一行 ⚠）。**全局旗标必须写在子命令之前**（写后面会被当成未知参数）；
    `--no-render` = 只改数据不刷视图。
- **文件模式的位置参数左移一位**：命令的第一个位置参数本来是 `slug`，给了 `--plan` 就不写它 ——
  `block set <slug> <ref> <status>` → `<ref> <status>`、`block show|rm|insert|move|expand|collapse <slug> <ref>` → `<ref>`、
  `task set <slug> <ref> <status>` → `<ref> <status>`、`task show|rm <slug> <ref>` → `<ref>`、
  `note <slug> <text>` → `<text>`；其余（`current` / `check` / `workers` / `render` / `digest` / `list` /
  `plan new` / `task new` / `block new`）文件模式下**不写位置参数**。多写一个（如
  `block show myplan T-003#B-004`）退 2，并点明「文件模式下不要再写 slug」。
  `set` 的 `<状态>` 是唯一**可以留空**的格子（只给 `--unset` 清线程登记时）。
- `list`：给了 `--plan` 就只列这一份；否则列 `--plans-root` 库里的全部。
- `ref` 的写法：`T-002`（任务）/ `T-002#B-001`（块）/ `B-001`（块内唯一后缀）。
- **跨组错用会给人话错误**（退 2）：`task set T-001#B-001` 会说「这是块不是任务 —— 块状态用 `block set`」，
  `block rm T-002` 会说「这是任务不是块 —— 连块一起删用 `task rm`」。命令名字面量按对象选，不对就当场点明。
- **退出码**：参数错、找不到对象 → **2**；`check` 发现图错误 → **1**；`workers` 发现 ⚠/❌ → **1**；其余 → **0**。
  出错原因走 stderr（中文），stdout 只放给人/给 agent 读的结果。

## 1. 建立

### `plan new` — 新建一份 plan
`py plan new <slug> [--title TITLE] [--goal GOAL] [--owner OWNER]… [--digest-hours 6] [--quiet-hours 23:00-08:00] [--force]`
- 落在哪必须说清：`--plan <路径>/plan.json`（就建这个文件；`slug` 可省，取目录名）或 `--plans-root <目录>` + `slug`。
- `--owner` 可多次，写法 `id=kind:label[@channel]`（`kind` ∈ `human|agent`），例：
  `--owner "rdm-assistance=agent:RdmAsst3813"`；不给 kind 时按 agent 处理。
- 落盘后渲出三个视图；目标已存在时**必须 `--force`**。
- 注意：`plan new` 之后无条件再补一个 `you=human:本人`，会覆盖同 id 的 `--owner`（要带 Discord 身份就另起 id）。

### `task new` — 加一条任务（泳道）
`py task new <slug> --title TITLE [--id T-00N] [--owner x] [--deps T-001 …] [--note "…"]`
- `--deps` 是**任务级**依赖；开工条件 = 那些任务的**全部**块都 done。

### `block new` — 往一条任务**末尾**加块（可独立认领、可评审的工作）
`py block new <slug> --task T-001 --title "…" [--kind impl|review|decision|research] [--doc "做什么"] [--done-when "判据"]… [--deps T-00N#B-00N …] [--owner x] [--review-of T-00N#B-00N] [--status 状态]`
- **`--status` 默认 `blocked`（=待批准，等有人点头）**：只有 AI 判断这块无需审批就能干，才显式给
  `--status pending`。`block expand --step` 追加的步骤不在此列 —— 它们是「已经批过的那条活」的后续，仍是 `pending`。
- `doc`（做什么）与 `done_when`（**可核验**的判据）是块的本体；没有判据的块不许建。
- 要插在**中间**（不是追加到末尾）用 `block insert`；块的 `deps` 事后要改只有
  `insert` / `expand` / `collapse` / `rm` 重建四条路。

## 2. 结构编辑

### `block insert` — 插一个块到某个块**之前/之后**（位置级插入，接线一次改对）
`py block insert <slug> <锚块ref> [--before | --after] --title "…" [--kind …] [--doc "…"] [--done-when "…"]… [--owner x] [--review-of …] [--status 状态] [--note "为什么插"] [--dry-run]`
- 位置三种写法都对：**某个节点之后** = `--after <它>`；**两个节点之间** = `<后一个> --before`；
  **最早节点之前** = `<该任务第一个块> --before`（不给 `--before/--after` 就是 `--before`）。
- **接线自动改对**：
  - 插在锚块**之前**：新块接手锚块原来等的东西（锚块的显式 `deps` + 它的 `review_of`），锚块改成只等新块；
    锚块的下游不用动 —— 顺序仍是 `… → 新块 → 锚块 → 下游`。
  - 插在锚块**之后**：新块等锚块；原来等锚块（或评审锚块）的改成等新块 ——
    `… → 锚块 → 新块 → 下游`（不这么改的话下游会在新块还没做完时就开跑）。
- 认领人默认沿用锚块的（`--owner` 可覆盖）；`--status` 同 `block new`（默认 `blocked`）。
- 成环则报错且一个字不写；`--dry-run` 只打印会改什么（改的是内存副本，文件一个字节都不动）。

### `block rm` — 真删一个块（取消 ≠ 删除）
`py block rm <slug> <块ref> [--note "为什么删"] [--force]`
- 被别的块当依赖/评审对象时**默认拒删**（列出是哪些块，`--force` 才删）。
- 删**块**不会自动重接引用：`--force` 留下的 `deps` / `review_of` 会变成悬空（`check` 会报）。
  只想把块换个地方就先用 `block move`（它会把引用一起改对）。

### `block move` — 把一个块换到另一条任务（泳道）
`py block move <slug> <块ref> --task T-00N [--index N] [--note "为什么移"]`
- 块的 id 是 `T-00N#B-00N`（**位置即身份**），所以换泳道 = **换 id**（在目标任务里取最小空位）+
  把**引用旧 id 的接线全部重接**：别的块写进 `deps` / `review_of` 的，以及别的任务的 `expanded_from.block`。
  历史字段（`folded_from` / `runs[].block`）是记录，不动。
- `--index N` = 插到目标任务的第几位（0 起）；不给就追加到末尾。**同一条任务内**（`--task` 给的是它自己）
  只改先后，此时 id 与接线都不动 —— 等价 `reorder`，画布上的同泳道拖动走的就是这条。
- **成环则拒改，且一个字都不写**（与 `block expand` / `block collapse` 同一道闸）。最容易踩的一种：目标任务的
  任务级 `deps` 在块搬进来后会落到它身上，而源任务里正好有块等它 —— 报错会点名是哪条任务级依赖。
- 源任务被搬空**不删任务**（空泳道留着）；删任务走 `task rm`。
- 命令会打印换了什么：新 id、哪些块改等它、目标任务的任务级依赖从此算它的前置、源任务是否空了。

### `task rm` — 真删一条任务（连同它的块）
`py task rm <slug> <任务ref> [--note "为什么删"] [--force]`
- 两种拒删：① 还有别的任务依赖它（任务级 `deps`）；② 它的块还被**别的任务**的块依赖
  （删了那些依赖会变悬空、`check` 会一直报）。都要 `--force`。

### `block expand` — 一个块 → 一个任务流程（块原地成为第一步）
`py block expand <slug> <块ref> [--title "…"] [--step "标题 :: 做什么 :: 判据1;判据2 :: kind"]… [--owner x] [--note "为什么"] [--dry-run]`
- `--step` 可多次、按顺序串在第 1 步之后（第 N 步依赖第 N−1 步）。
- 前后接线一次改对：等这个块的改等**新链尾**，它自己的前置成为第一步的前置；成环则报错且一个字不写。
- 展开已完成/已取消的块 = **把那段活重新打开**（命令会打 ⚠，不拦）。

### `block collapse` — 一个任务 → 一个块（`compress` 是它的别名）
`py block collapse <slug> <任务ref> [--into <块ref|任务ref>] [--keep-task] [--title …] [--doc …] [--done-when …]… [--kind …] [--owner x] [--note …] [--force] [--dry-run]`
- 作用对象是**任务**（它和 `block expand` 互为逆操作，所以归在 `block` 组里）；给块 ref 会退 2 并点明用 `block rm`。
- 落点按 `--keep-task` → `--into` → 回展开前的位置 → 唯一前置任务；还说不清就报错列候选（不猜）。
- 各块状态不一致时默认拒压（`--force` 才压，取最靠前的那个状态）。

## 3. 状态与身份

### `block set` — 改块状态（**同一个入口**登记谁在做 + 那条子代理线程）
`py block set <slug> <块ref> <状态> [--by 谁] [--delegation deleg_xxxxxxxx] [--task-index N] [--transcript <路径>] [--note "…"] [--owner x] [--at ISO8601] [--artifact 路径]… [--doc "…"] [--done-when "…"]… [--actor 谁]`

### `task set` — 改任务状态（在途时才登记在做的人与线程）
`py task set <slug> <任务ref> <状态> [--by 谁] [--delegation …] [--task-index N] [--transcript <路径>] [--note "…"] [--owner x] [--at ISO8601] [--actor 谁]`
- 块状态：`pending` / `claimed` / `running` / `review` / `done` / `blocked` / `cancelled`；
  任务状态只有 `pending` / `running` / `done` / `blocked` / `cancelled`。
- **写 `ready`/`waiting` 会被拒绝**（派生状态，由依赖算出来）——两处真相是这套东西要消灭的。
- **参数按状态卡**（`set` 一个入口同时管状态与身份，所以给错状态的旗标会退 2 并列出该状态收什么）：

  | 状态 | 收哪些旗标（除通用的 `--actor`） |
  |---|---|
  | 块 `pending` / `cancelled` | `--owner --note --at --doc --done-when` |
  | 块 `claimed` / `running` / `review` | 上面全部 + `--by --delegation --task-index --transcript` |
  | 块 `done` | 上面通用那组 + `--by --artifact` |
  | 块 `blocked` | 上面通用那组 + `--by` |
  | 任务 `running` | `--owner --note --at --by --delegation --task-index --transcript` |
  | 任务 `pending` / `done` / `blocked` / `cancelled` | `--owner --note --at` |

  例：`block set X done --delegation d1` → 「块状态 done 不收 --delegation —— 它收 --artifact、--at、--by、…」。
- 打回 = `block set <块> claimed --note "<为什么打回>"`；`--note` 会落进 `feedback`，返工次数由图上的 `⟲N` 显示。
- `--at` 用于补记过去的时间（别假装是现在）。
- **会自动记「谁在做」**：改为 `claimed`/`running`/`review` 时把 `--by`（没给就用 owner）写进 `exec.by`；
  **换人**（`--by` 与原来不同）会连带清掉旧的 `delegation`/`transcript`；改为 `done`/`cancelled`/`pending` 会清空 `exec`。
- **线程登记**（子代理）就在这个入口：`--delegation` 要连带 `--by`（不然退 2），`--task-index` 只在给了
  `--delegation` 时有意义。**转录在哪由调用方给**（`--transcript <路径>`）：loomerto 不猜任何 harness 的目录。
  Hermes 侧的写法是 `<hermes home>/cache/delegation/live/<deleg>/task-<n>.log`（default profile 的 home 是
  `~/.hermes`，其余是 `~/.hermes/profiles/<名字>/`），这个约定写在 skill 里，不写在包里。
  不给 `--transcript` 时只登记线程号（打一行 ⚠）——`workers` 只能报「❓ 看不到」；登记时顺手检查转录在不在，
  不在就打印一行 ⚠（不拦）。
- `--unset` 清掉「在做 + 线程」登记（线程收工 / 交回别人）：这时**`<状态>` 可以省**，状态不动；
  `<状态>` 与 `--unset` 同时给退 2（`done`/`cancelled`/`pending` 本来就会清登记）。
- 目前是**自由登记**：不校验 `--by` 是不是协作者、也不是必须给 pid（R-04 待做）。

### `block describe` — 改块的**详情**（不动状态，改动记进日志）
`py block describe <slug> <块ref> [--title "…"] [--doc "…"] [--done-when "…"]… [--kind …] [--owner x] [--note "为什么改"]`
- 只管「这块是什么」：标题 / 做什么 / 判据 / 类型（`--owner` 只作为兜底，换人用 `assign`）。
- `--done-when` 一旦给了就是**整组替换**；什么都不给就退 2（没有字段要改）。
- 与 `set` 分工：**状态与身份走 `set`，详情走 `describe`**；改了什么会进日志（`--note` 也记进去）。

### `block assign` — 把一个块指派给某个参与方
`py block assign <slug> <块ref> [--to <参与方 id> | --unset] [--note "为什么"]`
- 只改 `owner`（认领人），**不动状态**，改动记进日志（`kind=assign`）。
- `--to / --unset` 必须给一个且只给一个（`--unset` = 清掉指派回「未指派」）。
- `--to` 不在 `plan.json` 的 `participants` 里时**打一行 ⚠ 照记**（R-05 的强制校验还没做）；
  块的「在做的人」与认领人不一致时再打一行 ⚠（换在做的人走 `set … <在途状态> --by`）。

### `note` — 写一条总结/决定进日志
`py note <slug> "…" [--kind summary|decision|reminder|created|task|block|status|insert|assign|remove|expand|collapse] [--ref T-00N#B-00N] [--actor 谁]`

## 4. 看

### `list` — 所有 plan + 进度
`py list`

### `current` — 现在能动的块（该谁动）
`py current <slug>` — 按 待批准 → 待评审 → 进行中 → 已认领 → 待认领 排序，带「在做 @谁（线程 …）」。

### `block show` — 看一个块的详细信息（**只读**；`info` 是它的别名）
`py block show <slug> <块ref> [--json] [--runs N]`
- 状态（+自何时）· 类型 · 归属任务 · 认领人（+认领时刻）· 在做的人（+线程号与转录路径）·
  做什么 · 判据 · 依赖（含任务级展开）· 评审对象 · 返工 `⟲N` 与 feedback · 产物 · run 记录 · 三视图路径。
- `--json` 给 agent 读（字段名与 `plan.json` 对齐）；`--runs N` 只列最近 N 条 run（默认 5，`0` = 全列）。
- **什么都不改**：不落盘、不重渲、不写日志。给任务 ref 会退 2 并点明用 `task show`。

### `task show` — 看一条任务的详细信息（含它的块一览，只读；`info` 是它的别名）
`py task show <slug> <任务ref> [--json]`
- 任务状态 / 认领 / 前置（任务级 `deps`）/ 块一览（逐块状态与认领人）/ 三视图路径；`--json` 给 agent 读。
- 要「一批块」看 `current`（现在该谁动）。

### `check` — 图质量（有错误退 1）
`py check <slug> [--stale-hours 24]`
- 查：重复块 id / 悬空依赖 / 任务级环 / 已就绪但无人认领 / 缺 `done_when` / 评审块缺 `review_of` / 悬置超时。
- **有错误就别往下走**；告警要念给用户听。

### `workers` — 在途块登记的子代理线程还在动吗（`threads` 是它的别名）
`py workers <slug> [--stale-min 30] [--json]`
- 七种结论：`✅ 在动` / `⏳ 静默`（超 `--stale-min` 没写一行）/ `⚠ 线程已结束`（manifest 说 completed/failed
  而块还挂在 running ⇒ 该对账）/ `❌ 号记错`（delegation 目录在、没这个 task 的转录）/ `❓ 看不到`（过了 7 天
  保留期 / 在别的机器上 / 号记错）/ `➖ 无线程`（人在做，或谁在做都没登记）/ `➖ 已无意义`（块不在途还挂着登记）。
- **只有 `⚠` 与 `❌` 退 1**；`⏳ ❓ ➖` 只提示、退 0。`--json` 给 agent 读。
- 只读文件（转录 + 同目录 `manifest.json`）：能说「还在写吗/结束了吗」，**不能**说「进程死了没有」。

## 5. 出

### `render` — 重渲三个视图
`py render <slug>` → `PLAN.md` / `plan.html` / `plan.canvas`（三者都由 `plan.json` 派生，**永远不要手改**）。
- 改状态时会自动重渲（`--no-render` 可跳过）；三个文件都是**原子替换**写入，读者不会看到半截文件。

### `digest` — 生成提醒/摘要文本
`py digest <slug> [--to <参与方 id 或 you>] [--format discord|md] [--stale-hours 24]`
- 提醒的四个要件与「什么时候不推」的纪律见 skill `remind-collaborators`。

## 6. 打开可编辑的画布

### `open` — 把一份 plan 当**可编辑的画布**打开
`py open [<plan 数据文件>] [--port N] [--no-open]`
- 起一个**只绑 `127.0.0.1`** 的本地服务（纯 stdlib `http.server`），默认自动挑空闲端口并打开浏览器；
  `Ctrl-C` 停。位置参数给 plan 数据文件（或它所在目录）；**给了 `--plans-root` 时可以只写 slug**。
- **观感与只读看板同源**：两页都注入 `loomerto/assets/theme.css`（颜色/字体/状态胶囊/按钮/分隔线/进度条/图例）；
  右侧详情栏与看板一样是常驻栏，**拖动那条分隔线调宽度**（双击复位，宽度记在浏览器里）。
- 画布上能改：块的 标题 / 做什么 / 判据 / 认领人 / 类型 / **状态**（认领·开干·送审·打回·收工）、
  新建任务、新建块、**拖动卡片改同一条泳道里的先后**。
- **不做**（故意的）：删块 / 删任务、跨泳道拖动、直接改 `deps` / `review_of` —— 那些会改块 id 或接线，
  走 `block rm` / `block insert` / `block expand` / `block collapse` 更安全。理由与协议见 [`canvas-sync.md`](canvas-sync.md)。
- **写回**：每次改动都走 `edits`（改动的唯一实现）→ `store.commit()`，所以数据文件与三个视图**同时**更新；
  前端每次保存都带上自己读到的 `rev`（= `updated_at`），对不上回 **409** 并让人先刷新（不做自动合并）。
- 失败不改任何东西：先改内存，出错抛 `PlanError` → 400（中文原因）；服务不会因为一次坏请求就死。
