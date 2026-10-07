# `plan.py` 命令行参考（现状清单）

> **这份文件是 CLI 面的现状**，逐条从代码里的 `argparse` 取（2026-10-07 · 代码基线 `3d774bd`）。
> 需求与缺口看 [`../REQUIREMENTS.md`](../REQUIREMENTS.md)；模型与操作纪律看
> [`../skills/plan-weave/maintain-a-shared-plan/SKILL.md`](../skills/plan-weave/maintain-a-shared-plan/SKILL.md)。
> 重新生成底稿的办法（改过命令后必须重跑，别手抄）：
> `for c in new task block set exec rm expand collapse note digest render check current workers list; do loomerto $c --help; done`

## 0. 怎么调用

三种等价写法（实现都在仓库根的 `loomerto` 包里，见 [`architecture.md`](architecture.md)）：

```bash
loomerto <子命令> [参数]                        # 装过包：uv tool install --editable <repo> → ~/.local/bin/loomerto
python3 -m loomerto <子命令> [参数]              # 不装：在仓库根目录里跑
python3 <skill>/scripts/plan.py <子命令> [参数]  # skill 侧的薄壳：自己交代 plans 根、自己找包
```

```bash
py() { python3 "$P" "$@"; }   # $P = <profile>/skills/plan-weave/maintain-a-shared-plan/scripts/plan.py
```

- 纯 stdlib、零依赖、**不需要服务**；`requires-python >= 3.9`。
- **全局旗标必须写在子命令之前**（写在后面会被当成未知参数）：
  `--no-render`（只改数据不刷视图）· `--plans-root <路径>`（直接指定 plan 目录）·
  `--profile <名字>`（用 `~/.hermes/profiles/<名字>/workspace/plans`）。
  例：`loomerto --profile plan-weave current my-plan`。
  不显式给的话按 `$LOOMERTO_PLANS_ROOT` → `$LOOMERTO_PROFILE` → `~/.hermes/workspace/plans` 找。
- `ref` 的写法：`T-002`（任务）/ `T-002#B-001`（块）/ `B-001`（块内唯一后缀）。
- **退出码**：参数错、找不到对象 → **2**；`check` 发现图错误 → **1**；`workers` 发现 ⚠/❌ → **1**；其余 → **0**。
  出错原因走 stderr（中文），stdout 只放给人/给 agent 读的结果。

## 1. 建立

### `new` — 新建一份 plan
`py new <slug> [--title TITLE] [--goal GOAL] [--owner OWNER]… [--digest-hours 6] [--quiet-hours 23:00-08:00] [--force]`
- `--owner` 可多次，写法 `id=kind:label[@channel]`（`kind` ∈ `human|agent`），例：
  `--owner "rdm-assistance=agent:RdmAsst3813"`；不给 kind 时按 agent 处理。
- 落盘 `<plans>/<slug>/plan.json` 并渲出三个视图；同 slug 已存在时**必须 `--force`**。
- 注意：`new` 之后无条件再补一个 `you=human:本人`，会覆盖同 id 的 `--owner`（要带 Discord 身份就另起 id）。

### `task` — 加一条任务（泳道）
`py task <slug> --title TITLE [--id T-00N] [--owner x] [--deps T-001 …] [--note "…"]`
- `--deps` 是**任务级**依赖；开工条件 = 那些任务的**全部**块都 done。

### `block` — 给任务加一个块（可独立认领、可评审的工作）
`py block <slug> --task T-001 --title "…" [--kind impl|review|decision|research] [--doc "做什么"] [--done-when "判据"]… [--deps T-00N#B-00N …] [--owner x] [--review-of T-00N#B-00N] [--status 状态]`
- **`--status` 默认 `blocked`（=待批准，等有人点头）**：只有 AI 判断这块无需审批就能干，才显式给
  `--status pending`。`expand --step` 追加的步骤不在此列 —— 它们是「已经批过的那条活」的后续，仍是 `pending`。
- `doc`（做什么）与 `done_when`（**可核验**的判据）是块的本体；没有判据的块不许建。
- 块的 `deps` **只能在建块时一次给全**：事后要改依赖只有 `expand` / `collapse` / `rm` 重建三条路。

## 2. 结构编辑

### `rm` — 真删一个块或任务（取消 ≠ 删除）
`py rm <slug> <ref> [--note "为什么删"] [--force]`
- 被别的块当依赖/评审对象时**默认拒删**（`--force` 才删）；删任务会连带它所有的块。

### `expand` — 一个块 → 一个任务流程（块原地成为第一步）
`py expand <slug> <块ref> [--title "…"] [--step "标题 :: 做什么 :: 判据1;判据2 :: kind"]… [--owner x] [--note "为什么"] [--dry-run]`
- `--step` 可多次、按顺序串在第 1 步之后（第 N 步依赖第 N−1 步）。
- 前后接线一次改对：等这个块的改等**新链尾**，它自己的前置成为第一步的前置；成环则报错且一个字不写。
- 展开已完成/已取消的块 = **把那段活重新打开**（命令会打 ⚠，不拦）。

### `collapse` — 一个任务 → 一个块（`compress` 是它的别名）
`py collapse <slug> <任务ref> [--into <块ref|任务ref>] [--keep-task] [--title …] [--doc …] [--done-when …]… [--kind …] [--owner x] [--note …] [--force] [--dry-run]`
- 落点按 `--keep-task` → `--into` → 回展开前的位置 → 唯一前置任务；还说不清就报错列候选（不猜）。
- 各块状态不一致时默认拒压（`--force` 才压，取最靠前的那个状态）。

## 3. 状态与身份

### `set` — 改状态
`py set <slug> <ref> <status> [--note "…"] [--owner x] [--by 谁] [--at ISO8601] [--artifact 路径]… [--doc "…"] [--done-when "…"]…`
- 块状态：`pending` / `claimed` / `running` / `review` / `done` / `blocked` / `cancelled`；任务状态只有 `pending` / `running` / `done` / `blocked` / `cancelled`。
- **写 `ready`/`waiting` 会被拒绝**（派生状态，由依赖算出来）——两处真相是这套东西要消灭的。
- 打回 = `set <块> claimed --note "<为什么打回>"`；`--note` 会落进 `feedback`，返工次数由图上的 `⟲N` 显示。
- `--at` 用于补记过去的时间（别假装是现在）；`--artifact` 只在状态置 `done` 时收下。
- **会自动记「谁在做」**：改为 `claimed`/`running`/`review` 时把 `--by`（没给就用 owner）写进 `exec.by`；
  **换人**（`--by` 与原来不同）会连带清掉旧的 `delegation`/`transcript`；改为 `done`/`cancelled`/`pending` 会清空 `exec`。

### `exec` — 谁在做 + 那条子代理线程（`doing` 是它的别名）
`py exec <slug> <块/任务ref> --by 谁 [--delegation deleg_xxxxxxxx] [--task-index N] [--profile <profile>] [--transcript <绝对路径>] [--note "…"] [--at ISO] [--unset]`
- 转录路径不给就按 `--profile` + 线程号算：`<hermes home>/cache/delegation/live/<deleg>/task-<n>.log`
  （default profile 的 home 是 `~/.hermes`，其余是 `~/.hermes/profiles/<profile>/`）；跨机器用 `--transcript` 直给。
- 登记时会当场检查转录在不在，不在就打印一行 ⚠（不拦）。
- `--unset` 清掉登记（线程收工 / 交回别人）。
- 目前是**自由登记**：不校验 `--by` 是不是协作者、也不是必须给 pid（R-04 待做）。

### `note` — 写一条总结/决定进日志
`py note <slug> "…" [--kind summary|decision|reminder|created|task|block|status|expand|collapse] [--ref T-00N#B-00N] [--actor 谁]`

## 4. 看

### `list` — 所有 plan + 进度
`py list`

### `current` — 现在能动的块（该谁动）
`py current <slug>` — 按 待批准 → 待评审 → 进行中 → 已认领 → 待认领 排序，带「在做 @谁（线程 …）」。

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
