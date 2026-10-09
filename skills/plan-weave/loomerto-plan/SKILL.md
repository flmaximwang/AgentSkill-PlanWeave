---
name: loomerto-plan
description: "Use when 与人/其他 agent 协同时要维护一份共享 plan。用 loomerto CLI（loomerto --plans-root <库> <子命令> <slug>）改状态、渲染三视图、发提醒；plan.json 是唯一真相，只经 CLI 改。上下文变长（跨 3+ 回合 / 要向接手的人解释背景 / 多条线并行）时先把后续规划、子代理分配与执行落到 plan 上。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [plan, collaboration, multi-agent, loomerto, visualization]
    category: plan-weave
    related_skills: [loomerto-remind, handle-a-recurring-progress-instruction, agent-to-agent-handoff]
---

# 维护一份共享 plan（协作计划记录员的核心动作）

## When to Use

- 与用户**或另一个 agent** 协同做一件事，并且这件事会跨多轮 / 多天 / 多个人。
- 有人问「现在到哪了」「下一步谁做」——这时答案应当来自 plan，而不是来自你的记忆。
- 你要把一段对话的产出固化下来，让下一个接手的人（或 agent）不必读聊天记录。

不适用：一次性能在一个回合里做完的事；只需要一句待办的时候。

## 硬规则 0（先看这条）：改 plan 只走 `loomerto` 命令

**不许自己写脚本改 plan。** 三不许：

1. **不许写 python 去操作 plan** —— 没有 `python3 -c "import loomerto…"`、没有 heredoc、没有新写的 `.py`。
   改状态 / 建块 / 接线 / 登记线程 / 渲染，CLI 全都有命令：敲 `loomerto …`。
2. **不许直接编辑 `plan.json`** —— 它是 JSON，手改看着能跑，但会漏掉**三视图同步**（`PLAN.md` /
   `plan.html` / `plan.canvas` 停在旧内容）、**事件日志**（后人查不到谁在什么时候改了什么）、以及
   **打回 / 收工自动清线程登记**这些语义。唯一写入漏斗是包里的 `edits` + `store.commit()`，
   `loomerto` 是它唯一的对外入口。
3. **不许 `import loomerto` 去写数据** —— 包的核心 API 是给**别的程序**用的（画布服务 `serve.py` 这类），
   不是给你绕开 CLI 用的。验证一份包能不能 import 可以，**改 plan 一律发命令**。

**CLI 现在做不到的动作 → 报给用户，别绕道写脚本**（例：`task` 只建不改 —— 改泳道标题 / 重排泳道顺序
没有命令）。把缺口说清楚（要什么动作、代价多大）交给用户拍板；正路是**给包加一条命令**
（见 `maintain-the-loomerto-package`），不是手改 `plan.json`。

## 会话一长，先把它落到 plan 上

**上下文变长时不要继续在聊天里硬推** —— 把接下来的事写进 plan，用 plan 做进一步的规划、派子代理、按块执行。
「长」的判据不是 token 数，而是这三件里的任一件：一件事已经跨了 3 个以上回合、你开始要向接手的人解释背景、
或者有多条互不相干的线同时在推。到了这一步，聊天里的结论已经开始丢，plan 是唯一不会被压缩掉的那份记录。

固定动作（缺一步就等于没落到 plan 上）：

1. **先读现状**：`loomerto current <slug>`；还没有 plan 就先
   `loomerto plan new <slug> --title "…" --goal "…"`。
2. **把剩下的活写成任务与块**：一个对象 / 一条工作线 = 一条泳道（`task`）；块要带 `doc`（做什么）与
   `done_when`（**别人能重跑**的判据）—— 判据写不成可核验的，说明这一块还没想清楚，别建。
3. **按块派子代理**：一块一个子代理，派完立刻登记线程
   `loomerto block set <slug> <块ref> running --by <谁> --delegation <deleg_id> --task-index N --transcript <转录路径>`。
   **子代理禁止起后台进程**（子代理退出时它的后台进程会接管 thread）；长活按目录 / 前缀分片、每条命令自带超时。
4. **按块收工**：`loomerto workers <slug>` 看在途线程还在不在动、`loomerto check <slug>` 看图质量；
   做完 `loomerto block set <slug> <块ref> done --artifact <产物绝对路径> --note "<做了什么>"`。
5. **回到聊天只留三样**：结论 + 该谁动（块 id）+ 那行 `file://…/plan.html`。

## 唯一真相与目录

```
<profile>/workspace/plans/<slug>/
├── plan.json     机器模型 = 唯一真相（任务图 + 块文档 + 事件日志）
├── PLAN.md       人读摘要（含 mermaid 图），自动生成
├── plan.html     自包含离线可视化（泳道 = 任务），自动生成
└── plan.canvas   Obsidian JSON Canvas 视图，自动生成
```

`plan.json` **只通过 `loomerto` 命令改**；`PLAN.md / plan.html / plan.canvas` **永远不要手改**
（下一次 `loomerto` 落盘就会覆盖）。唯一入口 = **装好的 `loomerto` 命令**
（`uv tool install --editable <repo>` 装出来的；本机在 `~/.local/bin/loomerto`）。
**一份 plan 在哪，永远由调用方说清**（包不认任何 harness 的目录，也没有 profile 这个概念）：

```bash
loomerto --plans-root <目录> <子命令> <slug> …      # 一份库里有好几份时才用
loomerto --plan <plan 数据文件> <子命令> …          # 只认这一份；此后命令里**不写 slug**
```

定位旗标必须写在**子命令之前**。本 profile 的 plans 根 = `<profile home>/workspace/plans`
（default = `~/.hermes/workspace/plans`，其余 profile = `~/.hermes/profiles/<名字>/workspace/plans`）；
在 plan 自己的目录里跑（那里有 `plan.json`）可以省掉旗标。

**实现在仓库根的 loomerto 包里**（纯 stdlib、零依赖）：model（模型与派生规则，纯函数）/ store（磁盘 +
**唯一写入漏斗** `commit()`）/ render（三视图）/ workers（线程探活）/ cli（唯一 print 与退出码）。
这个 skill 自带的 `scripts/plan.py` 是**旧写法**的薄壳（它替你交代 plans 根再调同一个 CLI，与
`loomerto` 等价；脚本位置见 `skill_view` 给的 `skill_dir`）—— **新写的命令一律直接用 `loomerto`**。
包没装的话先装：`uv tool install --editable <repo>`。

## 模型（借自 PlanWeave）

| 概念 | 是什么 | 约束 |
|---|---|---|
| plan | 一个协作目标 | 一个 slug 一个目录 |
| task（节点） | 一条工作线 | 可带任务级 `deps`（别的任务） |
| block（文档） | 一份可独立认领、可评审的工作 | 有 `doc`（做什么）和 `done_when`（判据），**没有判据的块不许建** |
| run | 一次执行记录 | 改状态时自动追加，带 `by` 和 `note` |
| exec | **谁在做 + 那条子代理线程**（认领之外的第二个身份） | 只记现在时：`by` / `delegation` / `task_index` / `transcript` / `started`；由 `block set <ref> <在途状态> --by … --delegation …` 写，收工自动清掉 |

**派生状态，不要手填**：block 存 `pending/claimed/running/review/done/blocked/cancelled`；`ready` 与
`waiting` 由依赖**与认领**算出来（依赖全 done **且没人认领** ⇒ `ready` 待认领；依赖全 done **且已经有
`owner`** ⇒ `claimed` 已认领；依赖没全 done ⇒ `waiting` 等前置）。想写 `ready` 会被拒绝是**故意的**——
两处真相就是这个系统要消灭的东西。

任务的开工条件 = 它所有任务级前置任务的**全部**块都 done（`block_deps`）；图上的边只从那些任务
的收尾块引出（`edge_deps`），免得一片线。`review_of` 同时是一条依赖边。块的 `deps` 事后要改走 `block deps`
（`--add` / `--rm` / `--deps` 整组替换；查存在性与环）。

## 状态表（图例顺序 = 一个块的一生）

**流程**：待批准? → 等前置 → 待认领 → 已认领 → 进行中 → 待评审 → 已完成；旁支只有 `已取消`。
**图例按这个顺序排**（模板里的 `C`/`ZH` 两个对象的键序即图例序，改顺序就是改那两个对象的键序）。

| 中文名 | 内部值 | 是什么 | 谁该动 |
|---|---|---|---|
| 待批准 | `blocked` | **动不了，等 agent 以外的人/外部条件**。两种进入方式：建块时就置 `--status blocked`（计划内的关卡），或开工后卡住。解锁 = `set <块> pending`（或直接回 `running`），之后按依赖自动变 等前置/待认领 | 被点名的人 |
| 等前置 | `waiting`（派生） | 依赖还没完成，轮不到它（**owner 可以先派好**，轮到他就接手） | — |
| 待认领 | `ready`（派生） | 依赖全 done、**还没人接**（有 owner 的块不是待认领，是已认领） | 谁有空谁接；`loomerto current` 列的就是它 |
| 已认领 | `claimed` | 有人认领了（owner 已定）、还没开干 —— 存储的 `claimed`，或 `pending` + 依赖已就绪 + **有 `owner`**（派生）。**评审打回也是回到这里**：块没换人、也没变新块，只是重做一遍，打回原因进 `feedback`、次数显示成 `⟲N` | 认领人（作用是占位：两个人别抢同一个块） |
| 进行中 | `running` | 正在做 | 认领人 |
| 待评审 | `review` | 做完了、已送审，等别人给结论（送审 = 把做块置 `review`） | 评审人（下游的评审块） |
| 已完成 | `done` | 判据满足、通过 | — |
| 已取消 | `cancelled` | 这块不做了；不计入进度分母、不画依赖边。**图上与「等前置」同色**，靠虚线左框 + 图例空心方框区分（不靠颜色） | — |

**状态 × 负责人是一张表**（`model.STATUS_OWNER`，三档：`never` 不能有 / `required` 必须有 / `may` 可有）：

| 档 | 哪些状态 | 为什么 |
|---|---|---|
| 不能有 | `待认领`（`ready`） | 它的定义就是「还没人接」；有负责人 ⇒ 显示成 `已认领`（不是同一个状态） |
| 必须有 | `已认领` / `进行中` / `待评审` | 「有主」是这三个状态的一部分（谁接的 / 谁在做 / 等谁给结论） |
| 可有 | `待批准` / `等前置` / `已完成` / `已取消` | 待批准 = 等**这个人**点头；等前置 = 可以先派好；已完成 = 留着「谁做的」 |

`不能有` 那档由**派生**兑现（不必人手工同步）；`必须有` 那档由 `check` 发 ⚠ 盯着（硬校验属 R-04）。
**任务是泳道**，它的 `owner` 是「谁负责这条线」，不归这张表管。

**没有「待返工」这个状态**：打回不是"换个人接手"，默认就是原 owner 重做一遍 —— 那正是「已认领」的
语义（有人在手、还没开干）。所以打回 = `set <块> claimed --note "<为什么打回>"`，块回到已认领，
`--note` 落进 `feedback`。状态只有"谁在做/做完没有"，原因和往返次数是属性，不是状态。

**「待批准」只有一个状态**（内部 `blocked`）：无论是"开工前计划好的关卡"还是"开工后卡住"，都是同一
件事 —— 这块离了某个人/某个外部条件就动不了，表现和处置完全一样。区别写在 `--note` 里，不要再拆出
第二个状态（曾经试过 `needs_approval`，两个状态行为相同、只是逼记录员多选一次，已合并）。
**新建块默认就是「待批准」**（`block` 的 `--status` 默认 `blocked`）—— 由 AI 判断这块无需审批就能干时，
才显式写 `--status pending` 放行；`expand --step` 追加的步骤不在默认之列（它是已批准那条活的后续步骤）。
`pending`（待排）不进图例 —— 图上有依赖时它会显示成「等前置」，依赖全就绪后按有没有负责人显示成
「待认领 / 已认领」。

**评审不是回边，返工才是那个 loop —— 但它长在块的「状态」上。** 评审是下游的**独立块**（`kind=review`
+ `--review-of <被审块>`），由评审人持有；被审块送审后停在「待评审」等结论。通过 → 被审块 `done`；
打回 → 被审块回 `claimed`（原 owner，带 `feedback`）。

重做的环是：待评审 →（打回）已认领 →（重做）进行中 →（再送审）待评审。`plan.html` 在节点状态后用
`⟲N` 标出被打回次数（数该块 runs 里"从 `review` 走出去且不是 `done`"的次数）。**别把它画成块之间的
回边**：块自己没换、owner 也没换，画边是范畴错误；而且依赖图一旦有环，`loomerto check` 会报错，
"谁在等谁"（深度/拓扑）也没法算。返工不会波及下游 —— 打回发生在做块 `done` 之前，下游一直卡在
「等前置」，这也正是把评审卡在 done 之前的意义。

## 粒度调整：块（B）⇄ 任务（T）与定点插入

计划开工后粒度会变：一个块干着干着发现是**三件事**（该升成一条工作线），或者一个任务拆得太碎、
几步其实一个人一次做完（该压回一块）；也可能只是**漏了一步**要补在中间。三个命令把结构一次改对，
**不要手删重建** —— 重建会丢 runs / feedback / 判据，还得手工接依赖。

```bash
$LT block insert <slug> <锚块ref> [--before|--after] --title "…" [--doc "…"] [--done-when "…"] \
      [--owner x] [--status 状态] [--note "为什么插"] [--dry-run]
                                    # 插在锚块之前/之后，把前后接线一次改对（不给就是「之前」）
$LT block expand <slug> <块ref> [--title "…"] [--owner x] [--note "为什么"]
      [--step "标题 :: 做什么 :: 判据1;判据2 :: kind"]...   # 可多次，按顺序追加
$LT block collapse <slug> <任务ref> [--into <块ref|任务ref>] [--keep-task]
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

**`block move`：把一个块换到另一条任务（泳道）。** 块 id 就是它的位置，所以换泳道 = 换 id
（目标任务里取最小空位）+ 把引用旧 id 的 `deps` / `review_of` / `expanded_from.block` **一次重接**；
`--index N` 指定插到第几位（不给就是末尾），`--task` 给的是它自己时只改先后（id 与接线都不动）。
成环拒改且一个字不写；源任务被搬空**不删任务**（空泳道留着）。**画布上拖到别的泳道走的就是这条**
（`edits.move_block` 一份实现）。

**「每个 <对象> 是 1 个泳道」= 把一个任务里的 N 个块升格成 N 条泳道。** 用户报一串要处理的对象
（一批源、一批目录、一批构建体）并把它们逐个念出来时，先按「一个对象一条泳道」建，**不要**把它们
塞成一条任务里的 N 个块——他会在半路上纠正，改起来要搬一遍。做法：① 每个对象 `task new --title "<动作>：<对象>"`
并**从输出里解析出真实 T id**；② `block move <块ref> --task <新 T id>` 把原块搬过去（块在新泳道里取
`#B-001`，deps 自动重接）；③ 共享的前置/收尾（盘点·决策·建库 / 总校验·收口）单独留一条「准备」与一条
「收尾」泳道，别摊到每条对象泳道里。批量搬完 `block move` 会重写所有指过来的 `deps`，**搬完必须读回**
每个下游块的 deps 条数与新 id。

**建新 task 之前先读同 plan 里已有的同类 task**（`task show <slug> <T>`）并照它的块形状与现成脚本建：
同一类活（「每个对象一条泳道」vs「一个批次一条线」）通常已经有一份可复用的映射/搬运脚本，
另造一套就是在同一份 plan 里维护两套形状，发现后要整体返工。判据与脚本都能沿用先例的，就沿用。

**两个都先查环、都能空跑**：结构改完若块依赖成环，直接报错**且 plan.json 一个字都不写**；
`--dry-run` 只打印会改什么（新任务/新链、落点、哪些块改接线、哪些任务被删），也什么都不写 ——
动真 plan 之前先看一眼。

## 谁认领了 / 谁在做 / 线程在哪

一个块上站着**两个人**：**认领人**（接了这块的人/agent，`owner`）与**在做的人**（此刻真正动手的那个，
`exec.by`）—— 记录员认领、子代理动手时两者不是同一个人，所以必须分开写。第三个问题是**那条子代理线程在哪**，
这是「检查子代理是否正常工作」唯一的入口。

| 问 | 看哪 | 怎么写 |
|---|---|---|
| 谁认领了 | 块的 `owner` + runs 里最后一条进入 `claimed` 的记录 | `loomerto block set <slug> <ref> claimed --by <谁> [--owner <谁>]`；只换人不改状态用 `loomerto block assign <slug> <ref> --to <谁>`（`--unset` 清掉） |
| 谁在做 | `exec.by` | `loomerto block set … running --by <谁>` 自动写上；换人时旧线程登记会被清掉 |
| 线程在哪 | `exec.delegation` + `exec.task_index` + `exec.transcript` | `loomerto block set <slug> <ref> running --by <谁> --delegation deleg_xxxxxxxx [--task-index N]` |

```bash
$LT block set <slug> T-002#B-001 running --by default --delegation deleg_05e3c787 --task-index 0 \
        --transcript <转录文件绝对路径> --note "前半段：写脚本"
                                    # 转录在哪由你给（Hermes 侧 = <hermes home>/cache/delegation/live/<deleg>/task-<n>.log）
                                    # 不给 --transcript 就只记线程号，workers 只能报「❓ 看不到」
$LT block set <slug> T-002#B-001 --unset   # 线程收工 / 交回别人（状态不动，<状态> 这时可以省）
$LT workers <slug>                   # ← 检查：每个在途块登记的线程还在动吗
$LT block show <slug> T-002#B-001    # ← 一次读全：状态 · 认领人(含认领时刻) · 在做+线程+转录 · 判据 · run（只读）
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
- **线程登记是现在时，不是简历**：收工（`done`/`cancelled`）或退回（`pending`）时 CLI 会自动清掉它；
  「谁做过的」留在该块的 `runs`（每条带 `by`）与日志里。
- **线程登记短命，产物才长命**：live 转录 7 天后回收，所以线程结束前要把真正要留的证据写进块的
  `artifacts` 或 run 的 `note`（`loomerto block set … --artifact <路径>`），别指望以后还能回读转录。

## 一次协作回合的固定动作

> 下面写的 `loomerto <子命令>` 都要带定位旗标，完整形态是
> `loomerto --plans-root <本 profile 的 workspace/plans> <子命令> <slug>`（在 plan 目录里跑可省；
> `--plan <数据文件>` 模式则命令里不写 slug）。

1. **读**：`loomerto current <slug>` —— 现在能动的块；先看这个再说话。
2. **总结**：`loomerto note <slug> "<这一段发生了什么>" --actor <谁>`
   —— 只写真正发生的；拿不准的写成「待确认」。
3. **改状态**：`loomerto block set <slug> T-002#B-002 running --by <谁> --note "<一句话>"`
   - 认领 → `claimed`；开干 → `running`；送审 → `review`；通过 → `done`；打回 → `claimed`
     （`--note` 会存成 `feedback`；打回默认就是原 owner 重做，所以不换人、不建新块）。
   - 参数按状态卡：线程登记（`--delegation` / `--task-index` / `--transcript`）只在 `claimed`/`running`/`review`
     收，`--artifact` 只在 `done` 收 —— 给错状态会退 2 并列出该状态收什么。
   - 补记过去的时间用 `--at <ISO8601>`，不要假装是现在。
4. **验证**：`loomerto check <slug>` —— 环 / 悬空依赖 / 已认领却没写负责人 / 缺判据 / 悬置超时（悬置只数**存储**状态在途的块）。
   **有错误就别往下走**；告警要念给用户听。
5. **登记线程**（把块派给子代理时）：`loomerto block set <slug> <ref> running --by <谁> --delegation <deleg_id>
   [--task-index N] [--transcript <路径>]` —— 之后随时 `loomerto workers <slug>` 就能看出这条线程是不是还在动
   （`⚠ 线程已结束` / `❌ 号记错` 退 1：先对账再往下走）。收工或换人时 `block set … --unset`
   （`set … done` 也会自动清）。
6. **提醒**：`loomerto digest <slug> --to <参与方>`，纪律见 skill `loomerto-remind`。
7. **交付前两条校验**（送审 / 交接 / 收尾时跑，不是每次改状态都跑）：
   - `loomerto-check-commands`：每个块有没有可直接执行的命令、变量有没有定义 —— 缺则**不批准**（exit 1）。
   - `loomerto-check-temps`：这份 plan 会不会留下没人清的临时文件 —— `❌ 不闭环` 时按它打印的
     `loomerto task new` / `loomerto block new` / `loomerto block set` 命令补一个收尾任务节点与「临时文件：…」声明。
   改完重跑；两条都要 `exit 0` 才往下走。

改状态时 `loomerto` 会自动重渲染三个视图（`--no-render` 可跳过）。

## 踩过的坑

- **`--no-render` 必须配对一句收尾 `render`**：批量写入时省渲染没问题，但忘了收尾，用户就会看着旧看板说「我没在 011 里看到新节点」（他已经这么报过一次）。一批写入串在一条命令里时，最后补 `loomerto render <slug>` 并读回 `PLAN.md`/`plan.html` 的 mtime 与节点标题，别只看命令的成功回显。**`--no-render` 还是全局旗标、得写在子命令之前**（`loomerto --no-render block new …`）；写在子命令之后会退 2 报 `unrecognized arguments: --no-render`。
- **跑 CLI 走 `terminal`，别包进 `execute_code` / Python subprocess**：Hermes 的危险判定是**按命令字面量**匹配的（`rm -rf` 这类串会被标成 recursive delete）。在 `terminal` 里 smart approval 会自动放行，在 `execute_code` 里却会弹同意框——60 s 没人点就超时，整个脚本**一个字都不执行**（报 BLOCKED）。所以状态写入永远直接跑 `loomerto …`，而且 **note/doc 里也不要写字面量 `rm -rf`**（写「删除」），否则同一条 `block set` 会在另一条通道被拦下。

## 命令速查

```bash
# 唯一入口 = 装好的 loomerto 命令。plans 根由调用方交代（包不认任何 harness 的目录）：
LT="loomerto --plans-root <本 profile 的 workspace/plans>"
#   换成 --plan <plan 数据文件> 则只认这一份，此后命令里**不写 slug**（位置参数整体左移一位）
#   例：loomerto --plan ./plan.json block set T-001#B-002 done
# 一级命令 = 对象/全局动作，动作在二级：plan / task / block 是分组，其余是单层动作
$LT list                                  # 所有 plan + 进度
$LT plan new <slug> --title "…" --goal "…" --owner "you=human:本人@discord:<ch>" \
   --owner "rdm-assistance=agent:RdmAsst3813"
$LT task new <slug> --title "…" [--deps T-001] [--owner x]
$LT task set <slug> <任务ref> <状态> [--by x] [--note "…"]        # 任务状态；线程登记只在 running 收
$LT task show <slug> <任务ref> [--json]                           # 一条任务的详情（只读）
$LT task rm <slug> <任务ref> [--force]                            # 真删任务（连带它的块）
$LT block new <slug> --task T-001 --title "…" --kind impl|review|decision|research \
   --doc "做什么" --done-when "可核验的判据" [--deps T-001#B-002] [--review-of T-001#B-002] \
   [--owner x] [--status 状态]      # --status 默认 blocked（待批准）；无需审批才显式给 pending
$LT block insert <slug> <锚块ref> [--before|--after] --title "…" [--doc "…"] [--done-when "…"] \
   [--owner x] [--status 状态] [--dry-run]     # 插到某块之前/之后，接线一次改对
$LT block set <slug> <ref> <状态> [--by x] [--note "…"] [--artifact <路径>] [--at ISO] \
      [--delegation deleg_xxxxxxxx] [--task-index N] [--transcript <路径>] [--unset] \
      [--doc "…"] [--done-when "…"]   # 状态 + 谁在做 + 子代理线程一个入口；参数按状态卡
$LT block describe <slug> <块ref> [--title "…"] [--doc "…"] [--done-when "…"] [--kind …] [--note "为什么"]
                                      # 只改详情、不动状态（改了会进日志）
$LT block assign <slug> <块ref> [--to <参与方 id> | --unset] [--note "为什么"]
                                      # 指派/取消指派认领人（不动状态）
$LT block deps <slug> <块ref> [--deps <一串ref> | --add <一串> | --rm <一串>] [--note "为什么"]
                                      # 接线事后改：存在性/自指/环三道闸，成环退 2 一个字不写；
                                      # --deps 整组替换（给空 = 清空），不能与 --add/--rm 同给
$LT workers <slug> [--stale-min 30] [--json]
                                         # 在途块的线程还在动吗（已结束/号记错 ⇒ exit 1）
$LT block expand <slug> <块ref> [--title "…"] [--step "标题 :: 做什么 :: 判据1;判据2"] [--dry-run]
                                         # 一个块 → 一个任务（块成为第一步）
$LT block collapse <slug> <任务ref> [--into <块ref|任务ref>] [--keep-task] [--force] [--dry-run]
                                         # 一个任务 → 一个块（默认回展开前的位置）
$LT block move <slug> <块ref> --task T-00N [--index N] [--note "…"]
                                         # 一个块 → 另一条任务（泳道）：换块 id + 重接 deps/review_of；
                                         # 成环则拒改（一个字不写）；源任务空了不删。画布上的跨泳道拖走这条
$LT block rm <slug> <块ref> [--force]     # 真删一个块（被引用时默认拒删）
$LT note <slug> "…" --kind summary|decision|reminder [--ref T-001#B-001]
                                         # --kind note 非法（退 2，会列出全部候选）；「这段发生了什么」用 summary
$LT current <slug>                        # 现在该谁动
$LT block show <slug> <块ref> [--json] [--runs N]   # 一个块的详情（只读；--runs 0 = 全列 run）
$LT check <slug>                          # 图质量（有错误 exit 1）
$LT digest <slug> [--to <参与方>] [--stale-hours 24]
$LT render <slug>                         # 手动刷新三个视图
$LT open <plan 数据文件> [--port N]        # 起本地服务，把这份 plan 开成**可编辑的画布**（只绑 127.0.0.1）
```

`ref` 可以写 `T-002`（任务）或 `T-002#B-001`（块），块也可以只写 `B-001`。

## 可编辑的画布（`loomerto open`）

只读看板是 `plan.html`（`file://` 打开，**不起服务、不发附件**）；**要动手改**就用 `open`：

```bash
loomerto --plan <plan 数据文件> open      # 等价：loomerto open <plan 数据文件>
```

- 起一个**只绑 `127.0.0.1`** 的本地服务（纯 stdlib `http.server`），默认自动挑空闲端口并打开浏览器；`Ctrl-C` 停。
- 画布上能改：块的 **标题 / 做什么 / 判据 / 认领人 / 类型 / 状态**（认领 · 开干 · 送审 · 打回 · 收工）、
  **新建任务**（顶栏与泳道下方各一个入口）、**新建块**、**拖动卡片改同一条泳道里的先后**、
  **拖到别的泳道 = 换任务**（拖到某张卡上＝插在它前面，拖到泳道空白处＝追加到末尾）。
- **跨泳道拖 = `block move`，不是「改个字段」**：块的 id 是 `T-00N#B-00N`（**位置即身份**），所以服务端
  要换 id（目标任务里取最小空位）+ 把引用旧 id 的 `deps` / `review_of` / `expanded_from.block` 一次重接，
  **成环就拒改**（400、一个字不写，界面把原因显示在顶栏）。源任务被搬空**不删任务**（空泳道留着）。
  这套演算只有一份（`edits.move_block`），命令 `loomerto block move <ref> --task T-00N [--index N]` 与画布共用。
- **观感与只读看板同源**：两页共用 `loomerto/assets/theme.css`（颜色/字体/状态胶囊/按钮/分隔线/进度条/图例）；
  右侧详情栏是常驻栏，**拖那条分隔线调宽度**（双击复位，宽度记在浏览器里；`Esc` / 「清空」只清内容）。
- 每次改动走 `edits`（改动的唯一实现）→ `store.commit()`：数据文件与 `PLAN.md` / `plan.html` / `plan.canvas`
  **同时**更新；前端带 `rev`（= `updated_at`），对不上回 **409** —— 让人先「刷新」再改（**不做自动合并**）。
- **不做**：删块 / 删任务、直接改 `deps` / `review_of` —— 那些会一脚踩坏判据或接线，
  走 `block rm` / `block move` / `block expand` / `block collapse` / `block new` 更安全。
- 要接第二个前端（别的 web 服务 / 别的画布）就读协议：`docs/canvas-sync.md`。

## 交付给人的默认包（默认就给，不用等他要）

给人类（用户 / 群）的每一条 plan 消息 —— 汇报、接管、digest、提醒 —— **默认**带一行 `file://` URL：

```
file://<本 profile 的 plans 根>/<slug>/plan.html
# 本机现状：plans 根 = /Users/maxim/.hermes/profiles/plan-weave/workspace/plans（在用的 plan 都在那儿）
```

- **只给这一行，不发附件。** 用户的原话：「我只想要可以直接在浏览器中查看的 URL，不要附件」，
  以及「我觉得用 file 协议就行，不用起服务」。不发 `plan.html` 附件，也不发 `plan.png`。
- **整条消息压到不被拆分**：Discord 会把超长回复拆成 `(1/2)` `(2/2)` 并加尾注，用户 2026-10-06
  明确不要这个尾注。机制、字段清单、判据原文放 plan 文件里（那正是 plan 的用途），聊天里只留
  结论 + 该谁动 + 那行 URL —— 想多讲就写进 plan 的块文档或日志，而不是拉长聊天。
- 为什么 `file://` 够用：`plan.html` 就是本机上的一个文件，他和你在同一台机器上，浏览器地址栏粘进去
  即开；`loomerto` 改状态时就地重渲，URL 不变、内容永远最新。
- **别再为它起服务**（http.server / 端口 / 保活 cron 都已经被否掉一版）—— 那只会多一个会挂的东西。
  **唯一例外 = 要让人动手改**：那就 `loomerto --plan <数据文件> open`（见上一节），它随开随停、只绑本机。
- **别在本 profile 的 `skills/` 上裸 `grep -r`**：目录里有 `.curator_ledger.jsonl` 与缓存索引（几十 MB 的单行 JSON），
  一次检索就能喷出几十 MB 到终端、白烧一轮。查“还有谁提过这个约定”就指名文件（`grep -n "<词>" skills/**/SKILL.md`），
  或先 `--include='*.md'` 限定。
- **截图/附件**只在对方明确索取时才发一次，且永远不许顶替那行 URL（截图是拍下来的快照，一改就过期）。
- 对方问「html 呢 / URL 呢」= 这条本来没做到，不是新需求。
- 给 **agent** 的不是这套：agent 要 `plan.json` / `PLAN.md` 的绝对路径。
- 例外只有一个：纯「什么都没变」的一句话汇报可以不带。
- **先给他问的那个数，口径与例外放后面。** 他问「覆盖了多少」就先用 `<覆盖>/<总数>` 形状的数字打头，再写分母怎么算、
  哪几条是例外；把方法、命令、核对过程混进结论＝「你报的事实太混乱了」。聊天的三样是结论 / 该谁动 / 那行 URL，其余写进 plan。
- **每轮汇报带一行块进度 `<已完成>/<总数>`**：他在多轮里就是靠这个数看推进；改完状态 / 记完档就给，不用等他问。
- **未经请求不提建议。** 原话「不用为我提出建议，直到我要求你」：汇报只给事实 + 该谁动；「要不要我顺手…」这类话在他
  问「怎么办 / 给个推荐」之前不要出现，方案与推荐留到他开口要的时候。
- **自己起的在途块，产物落地就收工**：`block set <slug> <ref> done --owner <谁> --artifact <路径> --note "<举证>"`。
  裸挂 `running` 会让 `workers` 与悬置报告失真，也让人以为还有活在跑。

## 几条硬规则

1. **一个块一件事**，判据要能被别人核验（「文件存在且能打开」而不是「做完了」）。
   **检查/校验类的块，判据写「检查的交付物」而不是期望结果**：写成「源 N 文件逐条命中/缺口明细落 `<TSV>`、
   结论写明、缺口按目录分布」，不要写「缺 0」—— 那是期望结果；结果一旦是否定的，块按自己的判据就不该 done，
   你只能回头改判据（本 skill 踩过）。**否定结果也照实收工**：结论与缺口分布写进 `doc` / `--note`，
   缺口处置当**待决项**交给用户，**不许为了让块通过而改判据**。
   **自己动手造成的缺陷更不许记成 done**：会改写/删除用户数据的 impl 块，收工前自检一句
   「有没有东西被删掉却没打算删」—— 跑批退出码 0 不等于没损失。有缺陷就把块置回 `blocked`
   （owner = 决定怎么处置的人），`--note` 写全四样：缺陷是什么 · 影响范围（多少项 / 多少字节 / 哪些目录）·
   恢复路径（逐条清单与恢复脚本的**绝对路径**）· 「不可恢复」这句结论的判定依据（试过哪几条路、各自结果）；
   清单与恢复脚本挂成 `--artifact`，好让下一个人直接照着回补。
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
- **`block set` / `task set` 不接受 `ready`/`waiting`（派生状态）；写 `pending` 让依赖去决定。**
- **`note --kind note` 不存在**：合法 kind = `summary|decision|reminder|created|task|block|status|insert|assign|remove|move|expand|collapse`。写 `note` 会退 2 并把这串候选列出来；记「这一段发生了什么」用 `--kind summary`。同族提醒：**任何旗标被拒时，先读它自己打印的候选清单再重试** —— 换一个近义词继续猜（note→summary）会白多烧一轮。
- **`block set … done` 的 `--artifact` 收多条：写完读回条数**（`block show <ref>`），只看到「✓ done」看不出少登记了哪条证据。
- **「待认领」= 依赖就绪 且没人接**（2026-10-08 起）：一个块只要有负责人，依赖一就绪就显示成**已认领** ——
  别指望「先派活、还显示待认领」。想让它回到待认领（谁都有空谁接）就 `block assign <ref> --unset`。
  反过来 `等前置` / `待批准` 照样可以有 owner（先派活、写「等谁点头」）。
  「已认领 / 进行中 / 待评审 却没有负责人」会被 `check` 报 ⚠（谁接的没说清）。
  连带：泳道摘要（`task show` 的 `[已认领…]`）会把「只有已派活未开工的块」算成进行中；悬置超时与
  `workers` 只数**存储**状态在途的块，派生出来的已认领不进这两份报告。
- **`block set` 会自动把 `--by` 写进 `exec.by`**（没给 `--by` 就落到 owner），所以「谁在做」不用另起一道仪式；
  **换人（`--by` 与原来不同）会连带清掉旧的 `delegation`/`transcript`** —— 旧线程不再代表这一块，这是故意的。
- **`workers` 是 `check` 的姊妹**：`check` 查图（环 / 悬空依赖 / 已认领却没写负责人），`workers` 查「干活的那个人」。
  只把 `⚠ 线程已结束` 与 `❌ 号记错` 当硬信号（退 1）；`❓ 看不到` 与 `➖` 是提示 —— 但它们出现时别默认「没事」，
  要说清是「看不到」还是「没在跑」。
- **线程号短命，别把它当档案号**：live 转录 7 天回收、跨机器的路径在这边根本看不到。要让后人知道
  「这块是谁做的、证据在哪」，写进 `artifacts` 与 run 的 `note`；线程登记只保证**现在**能查在动没在动。
- **改一条已经建好的接线走 `block deps`**：`--add` / `--rm` / `--deps`（整组替换，给空即清空），
  三道闸都在一处 —— 依赖必须**已经存在**（悬空依赖 `check` 会一直报）、引用当场规整成规范 id 并去重、
  改完**查环**（成环退 2 且一个字不写）。它是独立命令而不是给 `set` / `describe` 加旗标，因为「补一条依赖」
  改的是**接线**（前后顺序），不是字段。**`--rm` 一条本来就不等的 = 什么都没变 ⇒ 退 2**，别把它当成功
  （说明你写的 ref 或对象不对）。改完它会打一行 ⚠：所属任务的**任务级**依赖也算它的前置（`block show` 里
  标「任务级」的那几条）。换地方（换泳道）仍走 `block move`，换粒度走 `expand` / `collapse`（顺手重接）。
- **一块要等齐 N 条上游时，`kind=review` 会永久留一条 ⚠**（`是评审块但没写 review_of`）：`--review-of` 只收**一条** ref ⇒ 等齐 N 条的那种校验/收尾步建 `kind=impl`，前置写成一个给全的 `--deps A B C`。别为了消掉告警硬给一个上游，那等于声明它只审那一条。
- **让 N 个下游块间接等一个共享前置：把前置挂到链上中间那一块**（`block new <中间块> --deps <共享前置>`，下游只等中间块），比逐个给下游挂 `deps` 干净（逐个挂要用 `block deps <下游块> --add <共享前置>`，各写一条接线，多一片线）。
- **`--deps` 是 `nargs='*'`：重复写多个 `--deps` 只有最后一个生效。** 一个块要多条前置，写成
  `--deps T-004#B-001 T-005#B-001 T-006#B-001`（一个旗标跟一串），**不要** `--deps A --deps B` ——
  后者静默只留 B，图上看起来「有依赖」，实际只等一条（本 skill 踩过：总校验块本该等齐 13 条归档块，
  结果只挂了最后一条，而 `check` 不会有任何意见）。同理 `--review-of` 也只看最后一次。
  同一族的 `--artifact`（只在 `done` 收，用来登记证据路径）也不要假设重复旗标会累积：**要登记多条证据，
  就一个旗标跟一串（`--artifact a b c`），或分几条 `block set … done --artifact <一个>`（每条追一条 run）；
  写完 `block show <ref>` 读回 artifact 的条数** —— 只回显「✓ done」看不出少了哪几条。
  **批量建块 / 批量写证据后的读回断言要查这些字段**，别只查「doc / done_when 非空」—— 接线与证据正是那一档漏掉的。
- **修接线错首选 `block deps <块> --deps A B C`（或 `--add` / `--rm`）**；确实要重建整块时才用下面这招 ——
  **倒着 rm 再重建**（块被下游引用时正向删会被拒）：`block rm <收口块>` →
  `block rm <校验块>` → 用一次给全的 `--deps` 重建校验块（`--no-render`）→ 再重建收口块并 `--deps`
  指回校验块 → `render` + `check`。两块都还没开工（`blocked`）时无损；有 runs 的块要按
  `block set … <状态> --by <原 actor> --at <原 ISO> --note "<原 note>"` 把 run 补回。
- **`task` 只建不改：没有改名、没有重排命令。** 改泳道标题或调整泳道顺序只能改 `plan.json`：
  先 `cp plan.json plan.json.bak-<时间戳>`，只动那几个 `title` 字段 / `tasks` 列表顺序，再 `check` →
  `render`，然后**读回一条**确认（标题不是状态，不为它破坏「状态只经 CLI 改」，但改完必须 check）。
  任务顺序 = 看板泳道顺序 = 流程顺序；用户说「按 X 排序／我们先做最简单的」时，就是重排 `tasks` 列表，
  **块的 id 不动**（id 是位置不是身份），所以重排后要把「新顺序 ↔ 旧 T id」的对照念给用户。
- **`block collapse --into` 落进一个有任务级依赖的任务会继承它的全部块**：`block_deps` 会把落点任务的
  任务级前置展开成「那些任务的每一个块」，所以压出来的块可能凭空多等一批块、甚至成环。
  报错里会点名是哪个任务级依赖；换个落点或用 `--keep-task` 即可。
- **`new --owner "you=…"` 传了也没用**：`cmd_new` 在循环之后无条件再 `add_participant(plan, "you=human:本人")`，
  把你刚填的 label/channel 覆盖掉（同名 id 先删后加）。要让人类参与方带上 Discord 身份，就**另起一个 id**
  （如 `stronghold=human:Stronghold3369@discord:<thread>`），块上仍用 `you` 当 owner（digest `--to you` 会显示「你」）。
- **别把「涉及删除」自动升级成用户审批。** 用户的规矩是「删/清理前逐项证明内容已在别处存在」——
  举证满足即可由执行方完成。把这条写进块的 `done_when`（如「逐个 cmp 证明目标处内容逐字节相同才删」），
  而不是把块置 `blocked` 等用户点头：挡得过头会把「其实没事」做成待决项，用户会反问「为什么要我审核」。
  **他明确批准、但仍要前置时**（原话「我直接批准，但是必须要前置完成才能执行」）：建删除块用
  `--deps <检查块> --status claimed --owner <执行方>`，【前置】写进 `doc`，**不要置 `blocked`** ——
  那等于把已经给出的批准又收回去。谁动手由他定（他自己删 / 让 agent 起后台进程删），删完回读
  「路径不存在 + 体积回收」再收工。
- **block 的 `doc` 写错了要改原文**（`set … --doc`），不要把更正只留在日志里：人和 agent 读的是
  html / PLAN.md 里的 doc 原文，日志里的「纠正」救不了他 —— 他会拿着错前提来问你。
- **改错时连带把过期的证据路径改掉**：`--artifact` 还指着被纠正前的旧路径，看板就挂一条假证据（路径已不存在）。已 `done` 的块再发一次 `block set <ref> done --artifact <新路径> --note "<为什么改>"` 即可（已 done 再收一次会追加一条 run，不报错）。
- **用户纠正「形状」时把它落成约定，别只改这一次**：路径层级 / 命名这类形状被纠正后，`note --kind decision` 记一条（「层级 = …」）并在块的 `doc` 里引用，否则下一批同类块还会照错的形状建。
- **用户报了几块就建几块；范围重叠用「显式排除」解决，不要提议合并**：两个删除块若按目录跑会互相吞（后一块的范围里包含前一块要处理的文件）。
  做法是在后一块的 `doc` 里写「本块删除范围 = … 减去 `<文件>`（由 `T-00N#B-00N` 单列处理）」并把它写进判据；
  把「要么合成一块」这种选项提出来会被否（用户原话「2 个 block，不是一个 block」）。同理，两块有先后就老实给 `--deps`
>   （事后要加用 `block deps <后一块> --add <前一块>`）。
- **`blocked` 在 html/canvas 里就显示为「待批准」**，所以「某块需要人点头」的表达方式就是把它置
  `blocked` 并把 owner 改成那个人；不要另外造一个「待批准」状态。
- **改状态前先看这个块是不是已经完成**：执行方与记录员同时动手会撞出「标记 blocked / 实际已 done」的
  矛盾（曾 15 秒内撞车）。落状态前先读最新 run 与 PLAN.md 的更新时间，再决定动不动它。
- **同一份 plan 上可能有人（另一个 profile / 另一个会话）在并行加块**：任务图会在你眼皮底下变（实测块数 46 → 56，
  多出两条新任务且已有块在 `running`）。所以 ① 汇报进度用**刚读到的实时数**，别用几轮前的；② 建块前先读一遍，避免重复建；
  ③ 不是自己建的块**只报告、不接管** —— 除非用户明确说「直接认领并执行即可」，那就是接手（哪怕它已被别人 `claimed` / 挂在 `running`）：
  `block set <slug> <ref> running --by <你>` → 干完按它自己的判据 `done --artifact … --note …`，**不换 owner**（除非用户要换）。
- **没有 `status` 子命令**：每轮汇报用的 `<已完成>/<总数>` 用 `loomerto list`（自带进度）拿，或**只读** `plan.json` 数一遍状态；
  只读计数可以读文件，**写入一律走 CLI**。
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

  跑完 `pkill -9 -f cr-shot` 收尾。截图前先跑 `loomerto render`。
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
- **改画布（`canvas.html` / `serve.py`）必须在真浏览器里真拖一次**，别只跑 CLI 与 curl（2026-10-07 跨泳道
  拖动这轮）：CLI 全绿、服务端没有一行报错，而页面上 `drop` **静默什么都不做** —— 前端把「目标泳道 id」
  当块 id 去查表，`moveTo` 直接 return 了。派发合成事件的写法：
  `const dt=new DataTransfer(); src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,cancelable:true,dataTransfer:dt})); dst.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));`
  然后在页面里读回泳道→卡片 id 的顺序、`#msg` 文本、选中卡片；**再回读磁盘上的 `plan.json`**（页面对了
  而文件没变 = 写回那条路断了）。
- **`serve.py` 是已加载的模块，改它必须重启服务；`canvas.html` 不用**（`GET /` 每次都从磁盘重读资产）。
  不重启就会拿旧代码验收 —— 会得到「改了却没生效」或「本该好的地方报 KeyError」这类假结果（两个都踩过）。
- **`_apply` 的返回值是 `(msg, ref)` 二元组**（`ref` = 这次动到的块的当前 id，跨泳道换 id 时前端靠它保住
  选中）：加/改一个 op 时**所有分支都要给全**，前端没传的可选键一律 `p.get(...)` —— 曾经 `reorder` 用了
  `p["ref"]`，同泳道一拖就 `KeyError`（而跨泳道那条路是好的）。
- **块的 id 就是位置**：跨泳道移动会换成目标任务里的**最小空位**，可能正好拿回刚腾出来的老号（`T-002#B-001`
  换泳道后又变回 `T-002#B-001`，但已经是另一块了）。历史字段（`runs[].block` / `folded_from`）留着原样 ——
  那是记录不是引用；要追溯就用 `log` 里那条 `move`（它同时写了旧 id 与新 id）。
- **跑「另一份 checkout 的代码」要小心 `python3 -m` 的 cwd 优先**：`-m` 把**当前目录**放在 `sys.path` 最前，
  所以在 main 的目录里写 `PYTHONPATH=<worktree> python3 -m loomerto` 跑的其实是 **main 那份** ——
  「改动前 vs 改动后」的对拉会变成自己跟自己比（本 skill 踩过：11 份 plan 报「0 处差异」是假的）。
  要跑另一份代码，先 `cd` 到那份 checkout 的根，或者在**没有 `loomerto/` 目录**的地方显式给 `PYTHONPATH`；
  并且**先证明跑的是哪一份**。证明办法要挑**这次改动真的动了的东西**：拿 `--help` 的子命令表当判据只在
  「改了命令面」时成立 —— 只动模型/内部实现时两份 `--help` **一模一样**（这轮 B 档就是这样），
  这时印一个代码里的记号才对，例如
  `python3 -c "from loomerto import model; print('BLOCK_FIELDS' in dir(model))"`。
- **块的形状只有一处声明 = `model.BLOCK_FIELDS`**（键 → 默认值/工厂）。**加一个块级键就改它一处**：
  `model.new_block()` 是建块的唯一字面量，`edits.add_block` / `edits.insert_block` / `cli` 的 `expand` 步骤
  与 `collapse` 合并块都调它 —— 别再手写块字典（以前四处各抄一遍，实库里 9 份 plan 的 158 个块没有
  `exec` 就是这么来的）。只有 `block collapse` 会写的 `folded_from` 属于 `BLOCK_HISTORY_FIELDS`，
  **不进那张表**（不是每个块都有），`normalize_block()` 也不许删它。
- **老 plan 的缺键是「读时补齐、写时落盘」**：`store.load()` 按 `BLOCK_FIELDS` 只补不改地补齐每个块，
  但**不因此落盘** —— 只读命令（`block show` / `check` / `current` / `workers` / `digest`）跑完，
  `plan.json` 一个字节不变；对它做**任何写操作**才会让这些键材料化进文件（`exec: {}` 就是「没登记线程」，
  语义不变；`commit()` 里顺手写掉）。所以「老 plan 文件里突然多出 `exec`」不是数据被动过，
  也不是新 bug；要拿它当证据时得先说清是读出来的还是写出来的。

## Support files

| 文件 | 承担什么 |
|---|---|
| `scripts/plan.py` | skill 侧的**旧写法薄壳**：交代 plans 根 → 找包 → 调 `loomerto.cli.main()`（找不到包时打印装法，退出码 2）。**新写命令请直接用 `loomerto`** |
| loomerto 包（仓库根） | 实现在那里：model（模型/派生）/ store（磁盘 + 唯一写入漏斗 `commit()`）/ render（三视图）/ workers（线程探活）/ cli（唯一 print、唯一退出码）。**改实现去那里，改「怎么用」才改本文件** |
| 兄弟 skill | `loomerto-check-commands`（每个块的命令与变量定义）、`loomerto-check-temps`（临时文件闭环）、`loomerto-remind`（提醒纪律） |

静态图（给聊天/群用，**只在被明确索取时才做**）落在 plan 目录的 `plan.png`；默认交付是 `file://`
看板 URL（**不发附件、不起服务**），生成方法见文末「坑」。
