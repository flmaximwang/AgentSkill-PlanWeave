---
name: maintain-a-shared-plan
description: "Use when 与人/其他 agent 协同时要维护一份共享 plan。用 plan.py 总结工作、改状态、渲染三视图、发提醒；plan.json 是唯一真相。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [plan, collaboration, multi-agent, planweave, visualization]
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
$P = ~/.hermes/profiles/plan-weave/skills/plan-weave/maintain-a-shared-plan/scripts/plan.py
```

纯 stdlib，单文件，可直接 `python3 "$P" ...`。

## 模型（借自 PlanWeave）

| 概念 | 是什么 | 约束 |
|---|---|---|
| plan | 一个协作目标 | 一个 slug 一个目录 |
| task（节点） | 一条工作线 | 可带任务级 `deps`（别的任务） |
| block（文档） | 一份可独立认领、可评审的工作 | 有 `doc`（做什么）和 `done_when`（判据），**没有判据的块不许建** |
| run | 一次执行记录 | 改状态时自动追加，带 `by` 和 `note` |

**派生状态，不要手填**：block 存 `pending/claimed/running/review/done/blocked/cancelled`；`ready` 与
`waiting` 由依赖算出来（依赖全 done ⇒ ready）。想写 `ready` 会被拒绝是**故意的**——两处真相就是这个
系统要消灭的东西。

任务的开工条件 = 它所有任务级前置任务的**全部**块都 done（`block_deps`）；图上的边只从那些任务
的收尾块引出（`edge_deps`），免得一片线。`review_of` 同时是一条依赖边。

## 状态表（图例顺序 = 一个块的一生）

**流程**：待批准? → 等前置 → 待认领 → 已认领 → 进行中 → 待评审 → 已完成；旁支只有 `已取消`。
**图例按这个顺序排**（`assets/plan.html` 里 `C`/`ZH` 的键序即图例序，改顺序就是改那两个对象的键序）。

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
`pending`（待排）不进图例 —— 图上有依赖时它会显示成「待认领 / 等前置」。

**评审不是回边，返工才是那个 loop —— 但它长在块的「状态」上。** 评审是下游的**独立块**（`kind=review`
+ `--review-of <被审块>`），由评审人持有；被审块送审后停在「待评审」等结论。通过 → 被审块 `done`；
打回 → 被审块回 `claimed`（原 owner，带 `feedback`）。

重做的环是：待评审 →（打回）已认领 →（重做）进行中 →（再送审）待评审。`plan.html` 在节点状态后用
`⟲N` 标出被打回次数（数该块 runs 里"从 `review` 走出去且不是 `done`"的次数）。**别把它画成块之间的
回边**：块自己没换、owner 也没换，画边是范畴错误；而且依赖图一旦有环，`plan.py check` 会报错，
"谁在等谁"（深度/拓扑）也没法算。返工不会波及下游 —— 打回发生在做块 `done` 之前，下游一直卡在
「等前置」，这也正是把评审卡在 done 之前的意义。

## 一次协作回合的固定动作

1. **读**：`plan.py current <slug>` —— 现在能动的块；先看这个再说话。
2. **总结**：`plan.py note <slug> "<这一段发生了什么>" --actor <谁>`
   —— 只写真正发生的；拿不准的写成「待确认」。
3. **改状态**：`plan.py set <slug> T-002#B-002 running --by <谁> --note "<一句话>"`
   - 认领 → `claimed`；开干 → `running`；送审 → `review`；通过 → `done`；打回 → `claimed`
     （`--note` 会存成 `feedback`；打回默认就是原 owner 重做，所以不换人、不建新块）。
   - 补记过去的时间用 `--at <ISO8601>`，不要假装是现在。
4. **验证**：`plan.py check <slug>` —— 环 / 悬空依赖 / 无主就绪块 / 悬置超时。
   **有错误就别往下走**；告警要念给用户听。
5. **提醒**：`plan.py digest <slug> --to <参与方>`，纪律见 skill `remind-collaborators`。

改状态时 `plan.py` 会自动重渲染三个视图（`--no-render` 可跳过）。

## 命令速查

```bash
py() { python3 "$P" "$@"; }
py list                                  # 所有 plan + 进度
py new <slug> --title "…" --goal "…" --owner "you=human:本人@discord:<ch>" \
   --owner "rdm-assistance=agent:RdmAsst3813"
py task <slug> --title "…" [--deps T-001] [--owner x]
py block <slug> --task T-001 --title "…" --kind impl|review|decision|research \
   --doc "做什么" --done-when "可核验的判据" [--deps T-001#B-002] [--review-of T-001#B-002] \
   [--owner x] [--status blocked]
py set <slug> <ref> <status> [--by x] [--note "…"] [--artifact <路径>] [--at ISO]
      [--doc "…"] [--done-when "…"]      # 事实变了就改块原文，别只写在日志里
py note <slug> "…" --kind summary|decision|reminder [--ref T-001#B-001]
py current <slug>                        # 现在该谁动
py check <slug>                          # 图质量（有错误 exit 1）
py digest <slug> [--to <参与方>] [--stale-hours 24]
py render <slug>                         # 手动刷新三个视图
```

`ref` 可以写 `T-002`（任务）或 `T-002#B-001`（块），块也可以只写 `B-001`。

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
- `set` 不接受 `ready`/`waiting`（派生状态）；写 `pending` 让依赖去决定。
- **块的 `deps` 只能在建块时一次给全**：`plan.py` 没有「给已有块加依赖」的命令（`set` 不接受 `--deps`）。
  想拆成「先建块、再补依赖」两步，只会建出一堆空标题的重复块 —— 建块时就把 `--deps <task>#<block>` 传对。
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
- 泳道里的块是**一行平铺**的；一条任务超过 4 个块就会横向溢出到 #graph 可视区之外（有 overflow:auto，不是丢数据，但截图/首屏看不到，用户会以为「块没了」）。2026-10-06 已改成每行 4 块自动换行（`PER` 常量在 `graph()` 里）。改布局后必须重新截图确认块数 == plan.json 里的块数。
- 渲染看板时若所有块都 done，泳道会折叠成空图 —— 这是正常现象（去掉「隐藏已完成」即可）。
- 改 `assets/plan.html` 后不用开浏览器验证布局：用 node 打桩跑一遍内联脚本，能直接拿到每个节点的
  坐标并暴露渲染异常（本 skill 就是这么发现"隐藏已完成后节点被推到屏幕外"的）。

## Support files

| 文件 | 承担什么 |
|---|---|
| `scripts/plan.py` | 全部命令：模型 / 状态机 / digest / 三视图渲染 |
| `assets/plan.html` | 可视化模板（`/*__PLAN_DATA__*/null` 处注入 plan.json） |

静态图（给聊天/群用，**只在被明确索取时才做**）落在 plan 目录的 `plan.png`；默认交付是 `file://`
看板 URL（**不发附件、不起服务**），生成方法见文末「坑」。
