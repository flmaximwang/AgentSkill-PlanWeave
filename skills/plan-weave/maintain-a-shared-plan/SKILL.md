---
name: maintain-a-shared-plan
description: "Use when 与人/其他 agent 协同时要维护一份共享 plan。用 plan.py 总结工作、改状态、渲染三视图、发提醒；plan.json 是唯一真相。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [plan, collaboration, multi-agent, loomerto, visualization]
    category: plan-weave
    related_skills: [remind-collaborators, handle-a-recurring-progress-instruction, agent-to-agent-handoff]
---

# 维护一份共享 plan（协作计划记录员的核心动作）

## When to Use

- 与用户**或另一个 agent** 协同做一件事，并且这件事会跨多轮 / 多天 / 多个人。
- 有人问「现在到哪了」「下一步谁做」——这时答案应当来自 plan，而不是来自你的记忆。
- 你要把一段对话的产出固化下来，让下一个接手的人（或 agent）不必读聊天记录。

不适用：一次性能在一个回合里做完的事；只需要一句待办的时候。

## 唯一真相与目录

```
<profile>/workspace/plans/<slug>/
├── plan.json     机器模型 = 唯一真相（任务图 + 块文档 + 事件日志）
├── PLAN.md       人读摘要（含 mermaid 图），自动生成
├── plan.html     自包含离线可视化（泳道 = 任务），自动生成
└── plan.canvas   Obsidian JSON Canvas 视图，自动生成
```

`plan.json` 只通过 `plan.py` 改；`PLAN.md / plan.html / plan.canvas` **永远不要手改**（下一次
`plan.py` 落盘就会覆盖）。工具：

```
$P = <profile>/skills/plan-weave/maintain-a-shared-plan/scripts/plan.py
```

**实现在仓库根的 loomerto 包里**（纯 stdlib、零依赖）：model（模型与派生规则，纯函数）/ store（磁盘 +
**唯一写入漏斗** `commit()`）/ render（三视图）/ workers（线程探活）/ cli（唯一 print 与退出码）。
这个 skill 只带一个**薄壳** `scripts/plan.py`：它把「本 skill 所在 profile 的 `<home>/workspace/plans`」
交给包，再按 `checkout → $LOOMERTO_HOME → 已安装的 import → 已装好的 loomerto 命令` 的顺序找包；
四条都不成立时会打印该装哪一条（退出码 2），**不会抛看不懂的 ImportError**。
包没装的话先装：`uv tool install --editable <repo>`（本机已装好，`loomerto` / `plan` 在 `~/.local/bin`）。
**别的 harness 不必走命令行**：装过包就能 `from loomerto import store` 直接读写同一份 plan.json。
`loomerto`（或 `python3 -m loomerto`）与 `$P` 完全等价。
**一份 plan 在哪，永远由调用方说清**（包不认任何 harness 的目录）：

```bash
loomerto --plan <plan 数据文件> <子命令> …          # 只认这一份；命令里不用再写 slug
loomerto --plans-root <目录> <子命令> <slug> …      # 一份库里有好几份时才用
```

## 模型（借自 PlanWeave）

| 概念 | 是什么 | 约束 |
|---|---|---|
| plan | 一个协作目标 | 一个 slug 一个目录 |
| task（节点） | 一条工作线 | 可带任务级 `deps`（别的任务） |
| block（文档） | 一份可独立认领、可评审的工作 | 有 `doc`（做什么）和 `done_when`（判据），**没有判据的块不许建** |
| run | 一次执行记录 | 改状态时自动追加，带 `by` 和 `note` |
| exec | **谁在做 + 那条子代理线程**（认领之外的第二个身份） | 只记现在时：`by` / `delegation` / `task_index` / `transcript` / `started`；由 `block set <ref> <在途状态> --by … --delegation …` 写，收工自动清掉 |

**派生状态，不要手填**：block 存 `pending/claimed/running/review/done/blocked/cancelled`；`ready` 与
`waiting` 由依赖算出来（依赖全 done ⇒ ready）。想写 `ready` 会被拒绝是**故意的**——两处真相就是这个
系统要消灭的东西。

任务的开工条件 = 它所有任务级前置任务的**全部**块都 done（`block_deps`）；图上的边只从那些任务
的收尾块引出（`edge_deps`），免得一片线。`review_of` 同时是一条依赖边。

## 状态表（图例顺序 = 一个块的一生）

**流程**：待批准? → 等前置 → 待认领 → 已认领 → 进行中 → 待评审 → 已完成；旁支只有 `已取消`。
**图例按这个顺序排**（模板里的 `C`/`ZH` 两个对象的键序即图例序，改顺序就是改那两个对象的键序）。

| 中文名 | 内部值 | 是什么 | 谁该动 |
|---|---|---|---|
| 待批准 | `blocked` | **动不了，等 agent 以外的人/外部条件**。两种进入方式：建块时就置 `--status blocked`（计划内的关卡），或开工后卡住。解锁 = `set <块> pending`（或直接回 `running`），之后按依赖自动变 等前置/待认领 | 被点名的人 |
| 等前置 | `waiting`（派生） | 依赖还没完成，轮不到它 | — |
| 待认领 | `ready`（派生） | 依赖全 done、还没人接 | 谁有空谁接；`plan.py current` 列的就是它 |
| 已认领 | `claimed` | 有人认领了（owner 已定）、还没开干。**评审打回也是回到这里**：块没换人、也没变新块，只是重做一遍，打回原因进 `feedback`、次数显示成 `⟲N` | 认领人（作用是占位：两个人别抢同一个块） |
| 进行中 | `running` | 正在做 | 认领人 |
| 待评审 | `review` | 做完了、已送审，等别人给结论（送审 = 把做块置 `review`） | 评审人（下游的评审块） |
| 已完成 | `done` | 判据满足、通过 | — |
| 已取消 | `cancelled` | 这块不做了；不计入进度分母、不画依赖边。**图上与「等前置」同色**，靠虚线左框 + 图例空心方框区分（不靠颜色） | — |

**没有「待返工」这个状态**：打回不是"换个人接手"，默认就是原 owner 重做一遍 —— 那正是「已认领」的
语义（有人在手、还没开干）。所以打回 = `set <块> claimed --note "<为什么打回>"`，块回到已认领，
`--note` 落进 `feedback`。状态只有"谁在做/做完没有"，原因和往返次数是属性，不是状态。

**「待批准」只有一个状态**（内部 `blocked`）：无论是"开工前计划好的关卡"还是"开工后卡住"，都是同一
件事 —— 这块离了某个人/某个外部条件就动不了，表现和处置完全一样。区别写在 `--note` 里，不要再拆出
第二个状态（曾经试过 `needs_approval`，两个状态行为相同、只是逼记录员多选一次，已合并）。
**新建块默认就是「待批准」**（`block` 的 `--status` 默认 `blocked`）—— 由 AI 判断这块无需审批就能干时，
才显式写 `--status pending` 放行；`expand --step` 追加的步骤不在默认之列（它是已批准那条活的后续步骤）。
`pending`（待排）不进图例 —— 图上有依赖时它会显示成「待认领 / 等前置」。

**评审不是回边，返工才是那个 loop —— 但它长在块的「状态」上。** 评审是下游的**独立块**（`kind=review`
+ `--review-of <被审块>`），由评审人持有；被审块送审后停在「待评审」等结论。通过 → 被审块 `done`；
打回 → 被审块回 `claimed`（原 owner，带 `feedback`）。

重做的环是：待评审 →（打回）已认领 →（重做）进行中 →（再送审）待评审。`plan.html` 在节点状态后用
`⟲N` 标出被打回次数（数该块 runs 里"从 `review` 走出去且不是 `done`"的次数）。**别把它画成块之间的
回边**：块自己没换、owner 也没换，画边是范畴错误；而且依赖图一旦有环，`plan.py check` 会报错，
"谁在等谁"（深度/拓扑）也没法算。返工不会波及下游 —— 打回发生在做块 `done` 之前，下游一直卡在
「等前置」，这也正是把评审卡在 done 之前的意义。

## 粒度调整：块（B）⇄ 任务（T）与定点插入

计划开工后粒度会变：一个块干着干着发现是**三件事**（该升成一条工作线），或者一个任务拆得太碎、
几步其实一个人一次做完（该压回一块）；也可能只是**漏了一步**要补在中间。三个命令把结构一次改对，
**不要手删重建** —— 重建会丢 runs / feedback / 判据，还得手工接依赖。

```bash
py block insert <slug> <锚块ref> [--before|--after] --title "…" [--doc "…"] [--done-when "…"] \
      [--owner x] [--status 状态] [--note "为什么插"] [--dry-run]
                                    # 插在锚块之前/之后，把前后接线一次改对（不给就是「之前」）
py block expand <slug> <块ref> [--title "…"] [--owner x] [--note "为什么"]
      [--step "标题 :: 做什么 :: 判据1;判据2 :: kind"]...   # 可多次，按顺序追加
py block collapse <slug> <任务ref> [--into <块ref|任务ref>] [--keep-task]
      [--title …] [--doc …] [--done-when …] [--kind impl|review|decision|research]
      [--force] [--dry-run]
```

**`block insert`：往中间插一步。** 「某个节点之后 / 两个节点之间 / 最早节点之前」都靠它：插在锚块
**之前**时，新块接手锚块原来等的东西（它的显式 `deps` + `review_of`），锚块改成只等新块；插在锚块
**之后**时，新块等锚块，原来等锚块（或评审锚块）的改成等新块 —— 顺序与依赖一起改对；不这么改，
下游会在新块还没做完时就开跑。锚块的认领人默认被沿用，`--status` 同 `block new`（默认 `blocked`）。

**`block expand`：一个块 → 一个任务。** 原块**原地升级**成新任务的第一步（标题/doc/判据/runs 逐字保留，
只换 id），`--step` 给的步骤按顺序串在后面（第 N 步依赖第 N−1 步）。新任务插在原任务之后
（泳道顺序 = 流程顺序）。

- **前后关系一次改对**：凡是等这个块的（显式 `deps`、`review_of`、以及靠任务级依赖落下来的）
  一律改等**新任务的链尾**；这个块自己的前置原样成为第一步的前置。`review_of` 本身就含依赖边，
  所以那条不会再重复欠一条 `deps`。
- **原任务空掉就清掉**：这个块是任务里最后一块时，任务被删掉，别的任务对它的**任务级依赖转给新任务**
  —— 语义等价（原来等「那个任务的所有块」，现在等新链的全部块），不转就是一条悬空引用。
- `expanded_from` 记下「从哪个任务的第几块展开来的」，`collapse` 靠它回原位。
- **展开一个已完成/已取消的块 = 把那段活重新打开**：新加的步骤是 `pending`，等它的块改等新步骤 ⇒
  下游从「已就绪」退回「等前置」。命令会为此打一行 ⚠ 并写进日志（**不拦** —— 把做完的活拆成几步
  本来就是「还有活」这个意思）；只想补记录，就把新步骤也 `set … done`。

**`collapse`：一个任务 → 一个块。** 块必须住在某个任务里，所以「压」要交代落点，按这个顺序定：

1. `--keep-task`：留在本任务，只剩这一块（任务还在；插在第一块原来的位置）；
2. `--into <块ref>`：插到那个块之后（在那块所在的任务里）；`--into <任务ref>`：追加到那个任务末尾；
3. 都不给：有 `expanded_from` → **回展开前的位置**；否则若这条链只从**一个**别的任务起步 →
   落到那个任务末尾；
4. 还说不清就**报错并列出候选**（不猜）—— 猜错了就是把活安到错的泳道里。

- **合并块的字段**：标题 = 任务标题（`--title` 可改）；`doc` = 单块时逐字沿用、多块时拼成
  「1. 标题：doc」；`done_when` = 各步判据的**并集**（逐字，不重写）；`artifacts` 取并集；
  各步的 `runs` 按时间搬进来并标 `block=<原块 id>`；`folded_from` 记下被折进来的每一块
  （id/标题/kind/状态/doc/判据）。落在**本任务**里时不再把任务级依赖落成显式 `deps`（任务级依赖照样生效）。
- **状态**：各块状态一致就取那个；不一致时**默认拒绝**（`--force` 才压），且取**最靠前**的那个
  （`pending < blocked < claimed < running < review < done`）—— 还没做完就不许记成做完。
- **接线**：各步对外部的前置合并成新块的 `deps`（任务内部的前置消掉）；等这些块的（含 `review_of`）
  改等新块；被删任务的任务级依赖摘掉、改由下游块显式等新块。
- **回原位可能正好拿回原来的 id**：id 取「当前最小的空位」，所以 expand → collapse 走一趟，
  块往往还叫 `T-001#B-002`（锚点是位置，不是身份）。

**两个都先查环、都能空跑**：结构改完若块依赖成环，直接报错**且 plan.json 一个字都不写**；
`--dry-run` 只打印会改什么（新任务/新链、落点、哪些块改接线、哪些任务被删），也什么都不写 ——
动真 plan 之前先看一眼。

## 谁认领了 / 谁在做 / 线程在哪

一个块上站着**两个人**：**认领人**（接了这块的人/agent，`owner`）与**在做的人**（此刻真正动手的那个，
`exec.by`）—— 记录员认领、子代理动手时两者不是同一个人，所以必须分开写。第三个问题是**那条子代理线程在哪**，
这是「检查子代理是否正常工作」唯一的入口。

| 问 | 看哪 | 怎么写 |
|---|---|---|
| 谁认领了 | 块的 `owner` + runs 里最后一条进入 `claimed` 的记录 | `py block set <slug> <ref> claimed --by <谁> [--owner <谁>]`；只换人不改状态用 `py block assign <slug> <ref> --to <谁>`（`--unset` 清掉） |
| 谁在做 | `exec.by` | `py block set … running --by <谁>` 自动写上；换人时旧线程登记会被清掉 |
| 线程在哪 | `exec.delegation` + `exec.task_index` + `exec.transcript` | `py block set <slug> <ref> running --by <谁> --delegation deleg_xxxxxxxx [--task-index N]` |

```bash
py block set <slug> T-002#B-001 running --by default --delegation deleg_05e3c787 --task-index 0 \
        --transcript <转录文件绝对路径> --note "前半段：写脚本"
                                    # 转录在哪由你给（Hermes 侧 = <hermes home>/cache/delegation/live/<deleg>/task-<n>.log）
                                    # 不给 --transcript 就只记线程号，workers 只能报「❓ 看不到」
py block set <slug> T-002#B-001 --unset   # 线程收工 / 交回别人（状态不动，<状态> 这时可以省）
py workers <slug>                   # ← 检查：每个在途块登记的线程还在动吗
py block show <slug> T-002#B-001    # ← 一次读全：状态 · 认领人(含认领时刻) · 在做+线程+转录 · 判据 · run（只读）
```

- **线程号从哪来**：`delegate_task` 返回的 `delegation_id`（`deleg_xxxxxxxx`）与它在该批次里的
  `task_index`（本文档一律写成 `deleg_05e3c787#0` 这种形式）。**转录路径由调用方登记**
  （`block set … --transcript <路径>`）—— 包不猜 harness 的目录；Hermes 侧的对应写法是 hermes home 下的
  `cache/delegation/live/<delegation_id>/task-<n>.log`（default profile 的 home 是 `~/.hermes`，
  其余是 `~/.hermes/profiles/<名字>/`）。不给 `--transcript` 时只记线程号，`workers` 会报「❓ 看不到」。
- **`workers` 七种结论，一个都不许合并**：`✅ 在动`（转录最近还在写）/ `⏳ 静默`（超 `--stale-min`
  —— 默认 30 分钟没写一行，可能卡住或已死）/ `⚠ 线程已结束`（manifest 说这条线程已 completed/failed，
  而块还挂在 running ⇒ **该对账**）/ `❌ 号记错`（delegation 目录在，但没有这个 task 的转录）/
  `❓ 看不到`（连目录都不在：过了 7 天保留期 / 在别的机器上 / 号记错）/ `➖ 无线程`（人在做，或谁在做
  都没登记）/ `➖ 已无意义`（块已不在途，登记还挂着）。**只有 `⚠` 与 `❌` 退 1**（先对账再往下走）；
  `⏳ ❓ ➖` 只提示、退 0。`--json` 给 agent 读。
- **`❓ 看不到` ≠「子代理没在跑」**：live 转录 7 天就被回收，跨机器也看不到。说得出「看不到」，
  说不出「没在跑」。要更硬的判活，去**线程所在的那个 profile** 里用 `delegate_task action='list'`
  （那里比 pid + 进程启动时间指纹），别在这边把「读不到」写成结论。
- **它只看文件、不读库**：`workers` 只读转录与同目录的 `manifest.json`（纯 stdlib、跨 profile、跨机器
  都能跑）。所以它能回答「还在写吗 / 结束了吗」，回答不了「进程还活着吗」—— 后者走上面那条升级路径。
- **线程登记是现在时，不是简历**：收工（`done`/`cancelled`）或退回（`pending`）时 `plan.py` 会自动清掉它；
  「谁做过的」留在该块的 `runs`（每条带 `by`）与日志里。
- **线程登记短命，产物才长命**：live 转录 7 天后回收，所以线程结束前要把真正要留的证据写进块的
  `artifacts` 或 run 的 `note`（`py block set … --artifact <路径>`），别指望以后还能回读转录。

## 一次协作回合的固定动作

1. **读**：`plan.py current <slug>` —— 现在能动的块；先看这个再说话。
2. **总结**：`plan.py note <slug> "<这一段发生了什么>" --actor <谁>`
   —— 只写真正发生的；拿不准的写成「待确认」。
3. **改状态**：`plan.py block set <slug> T-002#B-002 running --by <谁> --note "<一句话>"`
   - 认领 → `claimed`；开干 → `running`；送审 → `review`；通过 → `done`；打回 → `claimed`
     （`--note` 会存成 `feedback`；打回默认就是原 owner 重做，所以不换人、不建新块）。
   - 参数按状态卡：线程登记（`--delegation` / `--task-index` / `--transcript`）只在 `claimed`/`running`/`review`
     收，`--artifact` 只在 `done` 收 —— 给错状态会退 2 并列出该状态收什么。
   - 补记过去的时间用 `--at <ISO8601>`，不要假装是现在。
4. **验证**：`plan.py check <slug>` —— 环 / 悬空依赖 / 无主就绪块 / 悬置超时。
   **有错误就别往下走**；告警要念给用户听。
5. **登记线程**（把块派给子代理时）：`plan.py block set <slug> <ref> running --by <谁> --delegation <deleg_id>
   [--task-index N] [--transcript <路径>]` —— 之后随时 `plan.py workers <slug>` 就能看出这条线程是不是还在动
   （`⚠ 线程已结束` / `❌ 号记错` 退 1：先对账再往下走）。收工或换人时 `block set … --unset`
   （`set … done` 也会自动清）。
6. **提醒**：`plan.py digest <slug> --to <参与方>`，纪律见 skill `remind-collaborators`。
7. **交付前两条校验**（送审 / 交接 / 收尾时跑，不是每次改状态都跑）：
   - `check-plan-node-commands`：每个块有没有可直接执行的命令、变量有没有定义 —— 缺则**不批准**（exit 1）。
   - `check-plan-temp-hygiene`：这份 plan 会不会留下没人清的临时文件 —— `❌ 不闭环` 时按它打印的
     `py task new` / `py block new` / `py block set` 命令补一个收尾任务节点与「临时文件：…」声明。
   改完重跑；两条都要 `exit 0` 才往下走。

改状态时 `plan.py` 会自动重渲染三个视图（`--no-render` 可跳过）。

## 命令速查

```bash
py() { python3 "$P" "$@"; }
# 一级命令 = 对象/全局动作，动作在二级：plan / task / block 是分组，其余是单层动作
# 定位这一份 plan（都得自带，包不认任何 harness 的目录）：
#   --plan <plan 数据文件>    只认这一份；此后命令里**不写 slug**（位置参数整体左移一位）
#                            例：loomerto --plan ./plan.json block set T-001#B-002 done
#   --plans-root <目录> <slug>  一份库里有好几份时才用
py list                                  # 所有 plan + 进度
py plan new <slug> --title "…" --goal "…" --owner "you=human:本人@discord:<ch>" \
   --owner "rdm-assistance=agent:RdmAsst3813"
py task new <slug> --title "…" [--deps T-001] [--owner x]
py task set <slug> <任务ref> <状态> [--by x] [--note "…"]        # 任务状态；线程登记只在 running 收
py task show <slug> <任务ref> [--json]                           # 一条任务的详情（只读）
py task rm <slug> <任务ref> [--force]                            # 真删任务（连带它的块）
py block new <slug> --task T-001 --title "…" --kind impl|review|decision|research \
   --doc "做什么" --done-when "可核验的判据" [--deps T-001#B-002] [--review-of T-001#B-002] \
   [--owner x] [--status 状态]      # --status 默认 blocked（待批准）；无需审批才显式给 pending
py block insert <slug> <锚块ref> [--before|--after] --title "…" [--doc "…"] [--done-when "…"] \
   [--owner x] [--status 状态] [--dry-run]     # 插到某块之前/之后，接线一次改对
py block set <slug> <ref> <状态> [--by x] [--note "…"] [--artifact <路径>] [--at ISO] \
      [--delegation deleg_xxxxxxxx] [--task-index N] [--transcript <路径>] [--unset] \
      [--doc "…"] [--done-when "…"]   # 状态 + 谁在做 + 子代理线程一个入口；参数按状态卡
py block describe <slug> <块ref> [--title "…"] [--doc "…"] [--done-when "…"] [--kind …] [--note "为什么"]
                                      # 只改详情、不动状态（改了会进日志）
py block assign <slug> <块ref> [--to <参与方 id> | --unset] [--note "为什么"]
                                      # 指派/取消指派认领人（不动状态）
py workers <slug> [--stale-min 30] [--json]
                                         # 在途块的线程还在动吗（已结束/号记错 ⇒ exit 1）
py block expand <slug> <块ref> [--title "…"] [--step "标题 :: 做什么 :: 判据1;判据2"] [--dry-run]
                                         # 一个块 → 一个任务（块成为第一步）
py block collapse <slug> <任务ref> [--into <块ref|任务ref>] [--keep-task] [--force] [--dry-run]
                                         # 一个任务 → 一个块（默认回展开前的位置）
py block rm <slug> <块ref> [--force]     # 真删一个块（被引用时默认拒删）
py note <slug> "…" --kind summary|decision|reminder [--ref T-001#B-001]
py current <slug>                        # 现在该谁动
py block show <slug> <块ref> [--json] [--runs N]   # 一个块的详情（只读；--runs 0 = 全列 run）
py check <slug>                          # 图质量（有错误 exit 1）
py digest <slug> [--to <参与方>] [--stale-hours 24]
py render <slug>                         # 手动刷新三个视图
py open <plan 数据文件> [--port N]        # 起本地服务，把这份 plan 开成**可编辑的画布**（只绑 127.0.0.1）
```

`ref` 可以写 `T-002`（任务）或 `T-002#B-001`（块），块也可以只写 `B-001`。

## 可编辑的画布（`loomerto open`）

只读看板是 `plan.html`（`file://` 打开，**不起服务、不发附件**）；**要动手改**就用 `open`：

```bash
loomerto --plan <plan 数据文件> open      # 等价：loomerto open <plan 数据文件>
```

- 起一个**只绑 `127.0.0.1`** 的本地服务（纯 stdlib `http.server`），默认自动挑空闲端口并打开浏览器；`Ctrl-C` 停。
- 画布上能改：块的 **标题 / 做什么 / 判据 / 认领人 / 类型 / 状态**（认领 · 开干 · 送审 · 打回 · 收工）、
  **新建任务**（顶栏与泳道下方各一个入口）、**新建块**、**拖动卡片改同一条泳道里的先后**。
- **观感与只读看板同源**：两页共用 `loomerto/assets/theme.css`（颜色/字体/状态胶囊/按钮/分隔线/进度条/图例）；
  右侧详情栏是常驻栏，**拖那条分隔线调宽度**（双击复位，宽度记在浏览器里；`Esc` / 「清空」只清内容）。
- 每次改动走 `edits`（改动的唯一实现）→ `store.commit()`：数据文件与 `PLAN.md` / `plan.html` / `plan.canvas`
  **同时**更新；前端带 `rev`（= `updated_at`），对不上回 **409** —— 让人先「刷新」再改（**不做自动合并**）。
- **不做**：删块 / 删任务、跨泳道拖动、直接改 `deps` / `review_of` —— 那些会改块 id 或依赖接线，
  走 `rm` / `expand` / `collapse` / `block` 更安全。
- 要接第二个前端（别的 web 服务 / 别的画布）就读协议：`docs/canvas-sync.md`。

## 交付给人的默认包（默认就给，不用等他要）

给人类（用户 / 群）的每一条 plan 消息 —— 汇报、接管、digest、提醒 —— **默认**带一行 `file://` URL：

```
file:///Users/maxim/.hermes/profiles/plan-weave/workspace/plans/<slug>/plan.html
```

- **只给这一行，不发附件。** 用户的原话：「我只想要可以直接在浏览器中查看的 URL，不要附件」，
  以及「我觉得用 file 协议就行，不用起服务」。不发 `plan.html` 附件，也不发 `plan.png`。
- **整条消息压到不被拆分**：Discord 会把超长回复拆成 `(1/2)` `(2/2)` 并加尾注，用户 2026-10-06
  明确不要这个尾注。机制、字段清单、判据原文放 plan 文件里（那正是 plan 的用途），聊天里只留
  结论 + 该谁动 + 那行 URL —— 想多讲就写进 plan 的块文档或日志，而不是拉长聊天。
- 为什么 `file://` 够用：`plan.html` 就是本机上的一个文件，他和你在同一台机器上，浏览器地址栏粘进去
  即开；`plan.py` 改状态时就地重渲，URL 不变、内容永远最新。
- **别再为它起服务**（http.server / 端口 / 保活 cron 都已经被否掉一版）—— 那只会多一个会挂的东西。
  **唯一例外 = 要让人动手改**：那就 `loomerto --plan <数据文件> open`（见上一节），它随开随停、只绑本机。
- **别在本 profile 的 `skills/` 上裸 `grep -r`**：目录里有 `.curator_ledger.jsonl` 与缓存索引（几十 MB 的单行 JSON），
  一次检索就能喷出几十 MB 到终端、白烧一轮。查“还有谁提过这个约定”就指名文件（`grep -n "<词>" skills/**/SKILL.md`），
  或先 `--include='*.md'` 限定。
- **截图/附件**只在对方明确索取时才发一次，且永远不许顶替那行 URL（截图是拍下来的快照，一改就过期）。
- 对方问「html 呢 / URL 呢」= 这条本来没做到，不是新需求。
- 给 **agent** 的不是这套：agent 要 `plan.json` / `PLAN.md` 的绝对路径。
- 例外只有一个：纯「什么都没变」的一句话汇报可以不带。

## 几条硬规则

1. **一个块一件事**，判据要能被别人核验（「文件存在且能打开」而不是「做完了」）。
2. **状态只从真实证据来**。别人说「我提交了」而你看不到产物 —— 记 run，状态留在 `running`，
   在 digest 里问一句。
3. **只在状态变了才动 plan**。没变化就一句话汇报完停下，不要为了填时间线发明工作。
4. **跨 agent 协作的入口就是这个文件**：提醒别人时永远给 `PLAN.md` 的绝对路径 + 块 id。
   本机其他 profile 可以直读此路径，不需要经用户转达。
5. **用户的人看的是 html/canvas，agent 看的是 plan.json**。给人交付 plan 时**默认**给 `file://` 看板
   URL（见「交付给人的默认包」）；不发附件、不起服务，截图只在明确索取时才做（`plan.canvas` 直接
   丢进 Obsidian）。
6. 破坏性的重排（改 slug、拆 plan、批量改 id）**先获批准**。

## 坑

- **新接上的 bot 头一两分钟会对所有频道返回 403 `Missing Access`（权限传播延迟）**，看起来非常像
  「私有 thread 没邀请它」或「服务器权限配错了」。先等 1–2 分钟重试，**不要**立刻去改服务器权限。
  判据：同一个 token 读一个它显然看得见的频道 `/channels/<id>/messages?limit=1`，从 403 变 200。
- 传播期内 `PUT /channels/<thread>/thread-members/@me` 也会 403，**它单独不能证明 thread 是私有的**。
- 判断「提醒通道真的通了」的唯一判据不是 `hermes send` 回显 `sent`，而是**回读那条消息的 author.id**
  等于本 profile bot 自己的 user id（`/users/@me`）。否则可能发成了别的 profile 的 bot。
- `block set` / `task set` 不接受 `ready`/`waiting`（派生状态）；写 `pending` 让依赖去决定。
- **`block set` 会自动把 `--by` 写进 `exec.by`**（没给 `--by` 就落到 owner），所以「谁在做」不用另起一道仪式；
  **换人（`--by` 与原来不同）会连带清掉旧的 `delegation`/`transcript`** —— 旧线程不再代表这一块，这是故意的。
- **`workers` 是 `check` 的姊妹**：`check` 查图（环 / 悬空依赖 / 无主就绪块），`workers` 查「干活的那个人」。
  只把 `⚠ 线程已结束` 与 `❌ 号记错` 当硬信号（退 1）；`❓ 看不到` 与 `➖` 是提示 —— 但它们出现时别默认「没事」，
  要说清是「看不到」还是「没在跑」。
- **线程号短命，别把它当档案号**：live 转录 7 天回收、跨机器的路径在这边根本看不到。要让后人知道
  「这块是谁做的、证据在哪」，写进 `artifacts` 与 run 的 `note`；线程登记只保证**现在**能查在动没在动。
- **块的 `deps` 仍然不能事后直接改**：`block set` / `block describe` 都不接受 `--deps`（给已有块「补一条依赖」
  这件事本身就会改前后顺序，得让命令把接线一次改对并查环）。要改接线的三条路：`block insert`
  （把新步插进去、接手或改接前后依赖）、`block expand` / `block collapse`（粒度升降，顺手重接），
  再不行 `block rm` 重建 —— 建块时就把 `--deps <task>#<block>` 传对最省事。
- **`block collapse --into` 落进一个有任务级依赖的任务会继承它的全部块**：`block_deps` 会把落点任务的
  任务级前置展开成「那些任务的每一个块」，所以压出来的块可能凭空多等一批块、甚至成环。
  报错里会点名是哪个任务级依赖；换个落点或用 `--keep-task` 即可。
- **`new --owner "you=…"` 传了也没用**：`cmd_new` 在循环之后无条件再 `add_participant(plan, "you=human:本人")`，
  把你刚填的 label/channel 覆盖掉（同名 id 先删后加）。要让人类参与方带上 Discord 身份，就**另起一个 id**
  （如 `stronghold=human:Stronghold3369@discord:<thread>`），块上仍用 `you` 当 owner（digest `--to you` 会显示「你」）。
- **别把「涉及删除」自动升级成用户审批。** 用户的规矩是「删/清理前逐项证明内容已在别处存在」——
  举证满足即可由执行方完成。把这条写进块的 `done_when`（如「逐个 cmp 证明目标处内容逐字节相同才删」），
  而不是把块置 `blocked` 等用户点头：挡得过头会把「其实没事」做成待决项，用户会反问「为什么要我审核」。
- **block 的 `doc` 写错了要改原文**（`set … --doc`），不要把更正只留在日志里：人和 agent 读的是
  html / PLAN.md 里的 doc 原文，日志里的「纠正」救不了他 —— 他会拿着错前提来问你。
- **`blocked` 在 html/canvas 里就显示为「待批准」**，所以「某块需要人点头」的表达方式就是把它置
  `blocked` 并把 owner 改成那个人；不要另外造一个「待批准」状态。
- **改状态前先看这个块是不是已经完成**：执行方与记录员同时动手会撞出「标记 blocked / 实际已 done」的
  矛盾（曾 15 秒内撞车）。落状态前先读最新 run 与 PLAN.md 的更新时间，再决定动不动它。
- 任务级依赖不写进块里，但**会被算进开工条件**：块看起来"没人挡着"却动不了时，查它所属任务的 `deps`。
- `plan.html` 用 `file://` 打开即可，**不需要服务器**（不要为它起 http 服务）；依赖 Chrome/Safari 的
  现代 JS（无构建步骤）。
- 要发给用户/群的**静态图**（**只在对方明确索取时才做** —— 默认交付是看板 URL，见上节）：本机
  Chrome headless 会挂住不退出（`--screenshot` 其实已经写出了 png），
  必须用 `perl` 的 alarm 兜住，否则命令永远不返回：

  ```bash
  perl -e 'alarm shift; exec @ARGV' 45 \
    env -u HTTP_PROXY -u HTTPS_PROXY "$CHROME" --headless --disable-gpu --no-sandbox \
    --no-proxy-server --hide-scrollbars --user-data-dir=/tmp/cr-shot \
    --window-size=1560,1200 --virtual-time-budget=4000 \
    --screenshot=<plan 目录>/plan.png "file://<plan 目录>/plan.html"
  ```

  跑完 `pkill -9 -f cr-shot` 收尾。截图前先跑 `plan.py render`。
- **三视图必须原子落盘**（`atomic_write`：同目录 tmp + fsync + `os.replace`）。旧写法 `write_text` 是「先截断再写」，而 `plan.html` 每次改状态都重写；读者（用户浏览器）只要正好落在那一瞬，就会看到**空白页**。用户报「你发的 file 链接是空的」时先怀疑这个，别去查浏览器。
- 排查用另存一份**死文件** `plan-snapshot.html`（不随重渲更新），用来区分「文件问题」还是「打开方式问题」；给用户的日常 URL 永远是会自动重渲的 `plan.html`。
- **节点宽度与「一行几块」是按 `#graph` 的宽度算出来的，不是常量**（2026-10-07 用户要求：「这么大的空间，
  节点却要换行」）：`graph()` 先用 `WMIN=216` / `GXMIN=56` 估出这一屏放得下几列（列数不超过「块最多的那条
  泳道」，多出来的列本来也是空的），再把剩余宽度摊到每列；被 `WMAX=380` / `WMIN` 夹住时剩余空间摊到列间距
  （`GAPCAP=120`）。节点宽度写进行内样式，窗口 resize 用 rAF 合帧重排。**改布局时别再写死宽度**——
  原先的 `PER=4` + `W=216` 在宽屏上会让块无故折到第二行、右边空一大片（用户截图就是这个症状）。
- 一条任务的块数超过这一屏的列数时仍会折行（如 11 块 / 每行 9 列），这是宽度上限内的正常行为；
  `overflow:auto` 保证不丢数据。
- **详情栏是常驻的右侧固定栏**（2026-10-07 用户定，两轮：① 不用拖来拖去、贴右占满整页高、画布为它让出一段
  宽度、一条分隔线同时改两边的宽；② **常驻，不要「点开才跳出」**——点节点只换内容，页面布局一次都不许跳）：
  `--detail-w` 一个变量同时驱动 `#detailpanel` 的宽度和 `body{padding-right}`，所以画布 `#graph` 的
  `clientWidth` 跟着变、`graph()` 自动重排。**只有「宽度真的变了」才重排**（拖分隔线、窗口 resize、
  隐藏已完成）；点节点 / 点卡片 / 清空 **绝不重排**。清空 = 把 `#detail` 写回载入时那段提示
  （`DETAIL_HINT` 直接从 DOM 里取，别在 JS 里另抄一份文案）+ 取消高亮，入口两个：详情栏标题行的
  「清空」按钮与 Esc；**没有关闭边栏的入口**（`body{padding-right}` 常驻，载入时布局就已经是最终
  样子 —— 用户要的就是这个）。拖完把宽度写进 localStorage（`plan.detailw.<slug>`），
  窗口 resize 时先夹进窗口再重排。
  **这段初始化代码必须排在第一个 `view('graph', graph)` 之前**：否则首帧按默认宽度排一遍、再按记住的
  宽度排第二遍，用户就会看见跳一下（本 skill 踩过）。**别退回「浮窗 + 拖标题栏」**：浮窗会盖住节点，
  用户明确否过。
- 详情栏的几何判据（真 Chrome，把测试脚本追加进真 `<plan>.html` 里跑 `--dump-dom`）：载入即
  `#detailpanel` 的 `top==0 && bottom==innerHeight && right==innerWidth`、`#splitter.right ≈ panel.left`、
  `body` 的 `padding-right == panel.width`、节点最右缘 ≤ `panel.left`；**点节点前后取「所有节点
  `style.cssText` + `#graph.clientWidth` 的签名，必须逐字符相同**（这条就是用户要的「布局不跳」）；
  点节点后按 Esc / 点「清空」按钮：`#detail` 应回到载入时那段提示、`.sel` 清零、签名仍不变，
  空态再按 Esc 无副作用；
  拖到 560 后等一帧 `gcw` 应变小且最右缘 ≤ `panel.left`；拖到低于 240 夹回 240；同一 profile 重新载入
  沿用记住的宽度。
- 截图验详情栏之前**先把页面滚回顶部**：点节点会触发 `scrollIntoView`，而 headless Chrome 在「已经滚动过」
  的那一态会把固定定位元素画错位、并留一片未绘制的空白带（看着像布局塌了；旧版同样复现 ⇒ headless 伪影，
  不是产物缺陷）。这一态只信几何数字：`#detailpanel` 满足 `top==0 && bottom==innerHeight && right==innerWidth`、
  `#splitter.right ≈ panel.left`、`body` 的 `padding-right == panel.width`、且节点最右缘 ≤ `panel.left`。
- 改模板（随包发布的 `plan.html`）后的自检（2026-10-07 实测）：`loomerto render <slug>` 后拿 headless Chrome
  `--dump-dom`（同样要 `perl -e 'alarm shift; exec @ARGV' 12` 兜住不退出）读 `#graph` 的 `clientWidth`
  与每个节点的 `style="left/top/width"`，判据是「各泳道行数 == ceil(块数 / 每行块数)」+「最右缘 ≈
  `#graph` 宽 − PAD」+「块数 == plan.json 里的块数」。想验「按容器宽度重排」不必真改窗口：
  `function graph(){}` 是顶层函数声明（在 `window` 上），测试脚本里改 `#graph` 的 `style.width` 之后
  直接调 `window.graph()` 再量一次即可；resize 事件那条路（rAF 合帧）用 `dispatchEvent(new Event('resize'))`
  + 两层 `requestAnimationFrame` 量。
- 渲染看板时若所有块都 done，泳道会折叠成空图 —— 这是正常现象（去掉「隐藏已完成」即可）。
- 改模板（随包的 `plan.html`）后不用开浏览器验证布局：用 node 打桩跑一遍内联脚本，能直接拿到每个节点的
  坐标并暴露渲染异常（本 skill 就是这么发现"隐藏已完成后节点被推到屏幕外"的）。

## Support files

| 文件 | 承担什么 |
|---|---|
| `scripts/plan.py` | skill 侧的**薄壳**：交代 plans 根 → 找包 → 调 `loomerto.cli.main()`（找不到包时打印装法，退出码 2） |
| loomerto 包（仓库根） | 实现在那里：model（模型/派生）/ store（磁盘 + 唯一写入漏斗 `commit()`）/ render（三视图）/ workers（线程探活）/ cli（唯一 print、唯一退出码）。**改实现去那里，改「怎么用」才改本文件** |
| 兄弟 skill | `check-plan-node-commands`（每个块的命令与变量定义）、`check-plan-temp-hygiene`（临时文件闭环）、`remind-collaborators`（提醒纪律） |

静态图（给聊天/群用，**只在被明确索取时才做**）落在 plan 目录的 `plan.png`；默认交付是 `file://`
看板 URL（**不发附件、不起服务**），生成方法见文末「坑」。
