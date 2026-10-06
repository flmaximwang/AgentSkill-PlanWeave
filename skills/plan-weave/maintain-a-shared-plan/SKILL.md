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

**派生状态，不要手填**：block 存 `pending/claimed/running/review/done/needs_changes/blocked/
cancelled`；`ready` 与 `waiting` 由依赖算出来（依赖全 done ⇒ ready）。想写 `ready` 会被拒绝是
**故意的**——两处真相就是这个系统要消灭的东西。

任务的开工条件 = 它所有任务级前置任务的**全部**块都 done（`block_deps`）；图上的边只从那些任务
的收尾块引出（`edge_deps`），免得一片线。`review_of` 同时是一条依赖边。

## 一次协作回合的固定动作

1. **读**：`plan.py current <slug>` —— 现在能动的块；先看这个再说话。
2. **总结**：`plan.py note <slug> "<这一段发生了什么>" --actor <谁>`
   —— 只写真正发生的；拿不准的写成「待确认」。
3. **改状态**：`plan.py set <slug> T-002#B-002 running --by <谁> --note "<一句话>"`
   - 认领 → `claimed`；开干 → `running`；送审 → `review`；通过 → `done`；打回 → `needs_changes`
     （`--note` 会存成 `feedback`，并自动回到 ready）。
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
   --doc "做什么" --done-when "可核验的判据" [--deps T-001#B-002] [--review-of T-001#B-002] [--owner x]
py set <slug> <ref> <status> [--by x] [--note "…"] [--artifact <路径>] [--at ISO]
py note <slug> "…" --kind summary|decision|reminder [--ref T-001#B-001]
py current <slug>                        # 现在该谁动
py check <slug>                          # 图质量（有错误 exit 1）
py digest <slug> [--to <参与方>] [--stale-hours 24]
py render <slug>                         # 手动刷新三个视图
```

`ref` 可以写 `T-002`（任务）或 `T-002#B-001`（块），块也可以只写 `B-001`。

## 交付给人的默认包（默认就发，不用等他要）

给人类（用户 / 群）的每一条 plan 消息 —— 汇报、接管、digest、提醒 —— **默认**带这两样：

```
file:///Users/maxim/.hermes/profiles/plan-weave/workspace/plans/<slug>/plan.html
MEDIA:/Users/maxim/.hermes/profiles/plan-weave/workspace/plans/<slug>/plan.html
```

第一行是 URL（写全、单独一行、可直接贴进浏览器），第二行是附件（`hermes send` 与人格回复都认
消息里的 `MEDIA:`）。两条都要，原因不同：**`file://` 文本在 Discord 里不可点**，他拿到的是能一眼
确认的路径；**附件在 Discord 里才会变成可点的链接**，而且是唯一能在手机上看的形式。

- 截图（`plan.png`）**降为可选补充**：只有对方明确要图、或要贴给打不开文件的人时才生成。
- **永远不许用截图顶掉上面两条。** 截图是拍下来的快照，plan 一改就过期；URL 指向的文件永远最新 ——
  用户的原话就是这个抱怨：「默认不会发我 html 的 URL，只会发一个截图，我每次都得问他要才报告」。
- 对方问「html 呢 / 给我 html / URL 呢」= 这条本来没做到，不是新需求。
- 给 **agent** 的不是这套：agent 要 `plan.json` / `PLAN.md` 的绝对路径。
- 例外只有一个：纯「什么都没变」的一句话汇报可以不带。

## 几条硬规则

1. **一个块一件事**，判据要能被别人核验（「文件存在且能打开」而不是「做完了」）。
2. **状态只从真实证据来**。别人说「我提交了」而你看不到产物 —— 记 run，状态留在 `running`，
   在 digest 里问一句。
3. **只在状态变了才动 plan**。没变化就一句话汇报完停下，不要为了填时间线发明工作。
4. **跨 agent 协作的入口就是这个文件**：提醒别人时永远给 `PLAN.md` 的绝对路径 + 块 id。
   本机其他 profile 可以直读此路径，不需要经用户转达。
5. **用户的人看的是 html/canvas，agent 看的是 plan.json**。给人交付 plan 时**默认**给
   `plan.html` 的 `file://` URL + `plan.html` 附件（见下节「交付给人的默认包」）；截图只是补充，
   **不许**代替它们（`plan.canvas` 直接丢进 Obsidian）。
6. 破坏性的重排（改 slug、拆 plan、批量改 id）**先获批准**。

## 坑

- **新接上的 bot 头一两分钟会对所有频道返回 403 `Missing Access`（权限传播延迟）**，看起来非常像
  「私有 thread 没邀请它」或「服务器权限配错了」。先等 1–2 分钟重试，**不要**立刻去改服务器权限。
  判据：同一个 token 读一个它显然看得见的频道 `/channels/<id>/messages?limit=1`，从 403 变 200。
- 传播期内 `PUT /channels/<thread>/thread-members/@me` 也会 403，**它单独不能证明 thread 是私有的**。
- 判断「提醒通道真的通了」的唯一判据不是 `hermes send` 回显 `sent`，而是**回读那条消息的 author.id**
  等于本 profile bot 自己的 user id（`/users/@me`）。否则可能发成了别的 profile 的 bot。
- `set` 不接受 `ready`/`waiting`（派生状态）；写 `pending` 让依赖去决定。
- 任务级依赖不写进块里，但**会被算进开工条件**：块看起来"没人挡着"却动不了时，查它所属任务的 `deps`。
- `plan.html` 用 `file://` 打开即可，不需要服务器；依赖 Chrome/Safari 的现代 JS（无构建步骤）。
- 要发给用户/群的**静态图**（**可选补充** —— 默认交付是 `plan.html` 的 URL + 附件，见上节；
  只有对方明确要图时才做）：本机 Chrome headless 会挂住不退出（`--screenshot` 其实已经写出了 png），
  必须用 `perl` 的 alarm 兜住，否则命令永远不返回：

  ```bash
  perl -e 'alarm shift; exec @ARGV' 45 \
    env -u HTTP_PROXY -u HTTPS_PROXY "$CHROME" --headless --disable-gpu --no-sandbox \
    --no-proxy-server --hide-scrollbars --user-data-dir=/tmp/cr-shot \
    --window-size=1560,1200 --virtual-time-budget=4000 \
    --screenshot=<plan 目录>/plan.png "file://<plan 目录>/plan.html"
  ```

  跑完 `pkill -9 -f cr-shot` 收尾。截图前先跑 `plan.py render`。
- 渲染看板时若所有块都 done，泳道会折叠成空图 —— 这是正常现象（去掉「隐藏已完成」即可）。
- 改 `assets/plan.html` 后不用开浏览器验证布局：用 node 打桩跑一遍内联脚本，能直接拿到每个节点的
  坐标并暴露渲染异常（本 skill 就是这么发现"隐藏已完成后节点被推到屏幕外"的）。

## Support files

| 文件 | 承担什么 |
|---|---|
| `scripts/plan.py` | 全部命令：模型 / 状态机 / digest / 三视图渲染 |
| `assets/plan.html` | 可视化模板（`/*__PLAN_DATA__*/null` 处注入 plan.json） |

静态图（给聊天/群用）落在 plan 目录的 `plan.png` —— **可选补充，默认不发**；默认给的是 `plan.html`
的 `file://` URL + 附件，生成方法见文末「坑」。
