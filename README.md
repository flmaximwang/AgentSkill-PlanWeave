# loomerto（GitHub 仓库 `flmaximwang/Loomerto`；原名 `AgentSkill-PlanWeave`，旧地址由 GitHub 重定向）

**一个 AI 原生的 python 包 + 随包发布的 skill 集**：跨 harness 的协作工作台 —— 一份 `plan.json` 是唯一真相，
人和 AI 在同一块画布上对齐（谁认领 / 谁在做 / 那条子代理线程 / 下一步该谁动），下一个接手的人或 agent
不必去读聊天记录。命令行只是它的一层适配器：任何 harness 都能 import 这个包。

- **包**：仓库根目录的 `loomerto/`（纯 stdlib、零依赖、`requires-python >= 3.9`）。
  名字 = **loom + concerto**：协奏曲里**独奏与乐队主次分明、却同演一曲** —— 正对「一个人 + 几个 agent
  在同一份 plan 上各按自己的声部推进，谁主谁次写在脸上」；loom 那一半接着说多条工作线被织成一块布。
- **skill**：`skills/` 下的五条，随包发布（本机装在 **default** profile、类目 `loomerto`；其中
  `intake-a-running-collaboration` 按仓库路径归 `agent-orchestration`）。skill 不夹带实现，
  只带一个薄壳（`scripts/plan.py`）去调这个包。
- **public 仓库**：内容与具体机器无关，可分享。

## 文档地图（先读哪个）

- **要什么 / 做到哪了 / 缺什么** → [`REQUIREMENTS.md`](REQUIREMENTS.md) —— **需求的唯一入口**，
  它里面有一张完整的文档地图（哪类细节去哪份文件）。需求不散落在各 skill 正文里。
- **包怎么分层 / 怎么接新前端（画布写回、web 服务）/ 改代码前的三道闸** → [`docs/architecture.md`](docs/architecture.md)。
- **敲命令 / 核对 CLI 面** → [`docs/cli-reference.md`](docs/cli-reference.md)（15 个子命令逐条，含退出码与全局旗标）。
- **动手改一份 plan** → [`skills/plan-weave/maintain-a-shared-plan/SKILL.md`](skills/plan-weave/maintain-a-shared-plan/SKILL.md)（模型 / 状态表 / 谁在做+线程 / 坑）。
- 本文件剩下的部分 = 仓库索引：五条 skill 各是什么、怎么装、盲测记录。

## 装什么（两条腿）

**1）包**（让命令能跑；任何 harness 都能 import 它）：

```bash
uv tool install --editable .    # 推荐：装出 loomerto / plan 两个命令（本机 ~/.local/bin），代码跟着 checkout 走
# 或
cd <repo> && python3 -m loomerto …        # 不装，直接在仓库里跑
export LOOMERTO_HOME=<repo>               # 让别的 python 也能 import loomerto（把它加进 sys.path）
```

plan 在哪**不靠猜、也不认任何 harness**：`--plan <plan 数据文件>`（= `$LOOMERTO_PLAN_FILE`）只认这一份；
`--plans-root <目录>`（= `$LOOMERTO_PLANS_ROOT`）是一份 plan 库（命令里再给 slug）；两个都不给就看当前目录的
`plan.json`。例：`loomerto --plan ./plan.json block show T-001#B-002`、`loomerto --plans-root ~/plans list`。

**2）skill**（把「怎么用这个包」交给 AI；三段式标识符，按仓库内路径，**不需要 tap**；`--category` 只决定落点）：

```bash
for s in "plan-weave/maintain-a-shared-plan:loomerto" \
         "plan-weave/remind-collaborators:loomerto" \
         "plan-weave/check-plan-temp-hygiene:loomerto" \
         "plan-weave/check-plan-node-commands:loomerto" \
         "agent-orchestration/intake-a-running-collaboration:agent-orchestration"; do
  path="${s%%:*}"; cat="${s##*:}"
  hermes skills install \
    "flmaximwang/Loomerto/skills/$path" --category "$cat" -y
done
```

`--category` **只在安装时读取**：换分类 = uninstall + 带新 `--category` 重装（「改类目」是一次显式的退役 +
重装，不是原地改名）。skill 目录是 per-profile 的（default 是 `~/.hermes/skills/`，其余 profile 是
`$HERMES_HOME/profiles/<名字>/skills/`），别的 profile 要用就在那个 profile 里重跑同一条命令。

**本机现状（2026-10-07）：** 包用 `uv tool install --editable <repo>` 装好（`loomerto` / `plan` 在
`~/.local/bin`）；五条 skill 装在 **default** profile、类目 `loomerto`（intake 那条按仓库路径归
`agent-orchestration`），lock 的 identifier/URL 已指向 **`flmaximwang/Loomerto`**、`source_revision` =
`7eed38f`，装好的副本与仓库**逐份 `diff -rq` 一致**。
`plan-weave` profile 里还留着**旧一代**（类目 `plan-weave`，revision 停在 `c6f071b`/`19724db`，
identifier 仍是旧仓库名）—— 那台记录员 bot 退役时要一起清。

**skill 里的 `scripts/plan.py` 是薄壳**：它把「本 skill 所在 profile 的 `<home>/workspace/plans`」交给包，
再按 `checkout → $LOOMERTO_HOME → 已安装的 import → 已装好的 loomerto 命令` 的顺序找包；四条都不成立时，
它会明确告诉你 `uv tool install --editable <repo>`（而不是抛一个看不懂的 ImportError）。

**本仓库是这些 skill 与这个包的唯一 source of truth**：改这里 → `git push` → `hermes skills update <name>` 取新版。

## 索引

| skill | 用途 | 可执行入口 |
|---|---|---|
| [maintain-a-shared-plan](skills/plan-weave/maintain-a-shared-plan/SKILL.md) | **核心动作**：一份 plan 的建立、改状态、渲染三视图（`PLAN.md` / `plan.html` / `plan.canvas`）、图质量自检。`plan.json` 是唯一真相，视图永远自动生成 | `loomerto <command> <slug>`（skill 里另有薄壳 `scripts/plan.py`） |
| [remind-collaborators](skills/plan-weave/remind-collaborators/SKILL.md) | **提醒的那一半**：一条提醒的四个要件（块 id / plan 绝对路径 / 一条能做的下一步 / 给人时那行 `plan.html` 的 `file://` URL），以及「什么时候不推」的静默与去重纪律 | `loomerto digest <slug> --to <参与方>` |
| [check-plan-temp-hygiene](skills/plan-weave/check-plan-temp-hygiene/SKILL.md) | **交付前校验之一**：这份 plan 会不会留下没人清的临时文件（生产证据 / 声明 / 收尾节点三问），`❌ 不闭环` 时给出要补的任务节点与声明命令 | `scripts/check_plan_temp_hygiene.py <slug>` |
| [check-plan-node-commands](skills/plan-weave/check-plan-node-commands/SKILL.md) | **交付前校验之二**：每个节点有没有可直接执行的命令、可替换的变量有没有定义；缺则**不批准**（exit 1），并逐块给出补法 | `scripts/check_plan_node_commands.py <slug>` |
| [intake-a-running-collaboration](skills/agent-orchestration/intake-a-running-collaboration/SKILL.md) | **后进来的人**：用户把你 @ 进一段别人已经在跑的协作时，先用秒级只读证据（进度行 / `/proc` 判活 / 双测速率 / mtime 归属）把状态写成记录，且不碰对方正在跑的东西 | `references/read-only-evidence-recipes.md` |

五条 skill 的类目不统一（四条 `plan-weave`、一条 `agent-orchestration`），因为类目是**安装落点**，
而 `intake-a-running-collaboration` 与 `agent-orchestration` 类目下的
`agent-to-agent-handoff` / `agent-handoff-and-review` / `agent-handoff-spec` 是同一套协作程序的两半。
仓库内路径的第一段与安装类目保持一致，安装后 profile 里的树形与仓库逐字节相同。

> 搬进来之前它们只活在那个 profile 的 `skills/` 目录里（**无 lock 条目** —— 没有仓库、没有更新路径，
> `check` / `update` / `uninstall` 都看不见它们）。搬迁拆成两个提交：`06d14b9` 是**逐字节原样**的落点
> （`git show 06d14b9:skills/<cat>/<name>/<file> | shasum -a 256` 逐个对得上 profile 那份的 sha256），
> 之后的改写另开提交。

## 盲测（description 路由）

新建 skill / 改 description 头部之后，按 skill `skill-routing-blind-test` 的协议跑一轮：候选只给
`description` 的前 57 字符，两个独立判官只读同一份判官输入，逐题选「最该被调用的 skill」，对着金标落矩阵。

| 轮次 | 日期 | 范围 | 候选 | 题数 | 判官 | 得分 | 结论 |
|---|---|---|---|---|---|---|---|
| r1 | 2026-10-07 | 两个新校验 skill 的正例与变体 + 既有 3 个 skill 的触发题 + 2 条诱饵 | 13 | 16 | A / B | A 16/16 · B 16/16（逐题 picks 完全一致） | 定版，不开第二轮 |

产物在 `blind-tests/r1/`（题面 / 金标 / 判官输入 / 判官 A·B / 得分矩阵 / 轮次说明）；逐题矩阵与
「接受的代价」（下一轮往窗口塞新钩子时不许挤掉的区分词）在各 skill 的 `test-results.md`。

## skills/plan-weave/maintain-a-shared-plan

**一份 plan 的全生命周期**。模型借自 [GaosCode/PlanWeave](https://github.com/GaosCode/PlanWeave)（那个项目另有其名与本包无关）：
plan → task（节点，可带任务级 `deps`）→ block（**一份可独立认领、可被评审的工作**，约定上要有 `doc` 与
`done_when`）→ run（改状态时自动追加的执行记录）。
**块的形状只有一处声明**：`model.BLOCK_FIELDS`（键 → 默认值/工厂）+ `model.new_block()`（建块的唯一字面量），
老数据缺键由 `model.normalize_block()` 在 `store.load()` 里**只补不改**地补齐（实库里 9 份 plan 的 158 个块
没有 `exec` 就是这么来的；补出来的键在下一次 `commit()` 才落盘）。

- **目录**：`<plans root>/<slug>/`（plans root 见上面「装什么」；profile 场景 = `<profile>/workspace/plans`），
  `plan.json` 是唯一真相；`PLAN.md`（人读摘要 + mermaid）、`plan.html`（自包含离线泳道看板）、
  `plan.canvas`（Obsidian JSON Canvas）三个视图**永远不要手改** —— 下一次落盘就覆盖。
- **派生状态，不要手填**：block 存 `pending/claimed/running/review/done/blocked/cancelled`；
  `ready` 与 `waiting` 由依赖**与认领**算出来（依赖全 done **且没人认领** ⇒ `ready` 待认领；依赖全 done
  **且有 `owner`** ⇒ `claimed` 已认领；依赖没全 done ⇒ `waiting`）。写 `ready` 会被拒绝是**故意的** ——
  两处真相就是这个系统要消灭的东西。**新建块默认 `blocked`（待批准）**，AI 判断无需审批才写 `pending`。
- **状态 × 负责人**（`model.STATUS_OWNER`）：`待认领` **不能**有负责人（定义就是「还没人接」）；`已认领` /
  `进行中` / `待评审` **必须**有；`待批准` / `等前置` / `已完成` / `已取消` 可有可无。
- **一次协作回合的固定动作**：`current`（先看现在能动的块）→ `note`（总结这一段真正发生了什么，
  拿不准的写「待确认」）→ `block set`（只改受影响的块，带 `--by` / `--note`；派给子代理时同一句里
  补 `--delegation` / `--transcript`）→ `check`（环 / 悬空依赖 / 已认领却没写负责人 / 悬置超时，
  **有错误就别往下走**）→ `workers`（每个在途块的线程还在动吗）→ `digest`（提醒，纪律见
  `remind-collaborators`）。
  补记过去的时间用 `--at <ISO8601>`，不要假装是现在。
- **谁认领了 / 谁在做 / 线程在哪**：一个块上站着两个人 —— `owner`（认领人）与 `exec.by`（此刻动手的那个），
  第三个字段 `exec.delegation` / `transcript` 给出**具体的子代理线程**（`deleg_05e3c787#0` 与它的转录文件）。
  `workers` 七种结论：`✅ 在动` / `⏳ 静默` / `⚠ 线程已结束` / `❌ 号记错` / `❓ 看不到` / `➖ 无线程` /
  `➖ 已无意义`，只有 `⚠` 与 `❌` 退 1。live 转录 7 天回收，`❓ 看不到` 不等于「子代理没在跑」。
- **交付给人的默认包**：`plan.html` 的 `file://` URL **一行**，**不发附件**（用户 2026-10-06 定：
  「我只想要可以直接在浏览器中查看的 URL，不要附件」；`file://` 文本在 Discord 里不可点没关系 ——
  他和你在同一台机器上，粘进地址栏即开）。整条消息压到不被 Discord 拆成 `(1/2)`；机制、字段清单、判据
  都放 plan 文件里。**截图只在明确索取时才发一次，且永远不许顶掉那行 URL**（截图一改就过期）。
  给 **agent** 的是另一份：`plan.json` / `PLAN.md` 的绝对路径。
- **粒度可调（`block expand` / `block collapse`）**：一个块干着干着发现是三件事 → `block expand` 把它升级成**一个任务**
  （原块原地成为第一步，`--step` 追加后续步骤）；一个任务拆得太碎 → `block collapse` 压回**一个块**
  （默认回展开前的位置，也可 `--into <块/任务>` 或 `--keep-task`）。两者都把「谁在等它 / 它在等谁」
  一次改对（含任务级依赖与 `review_of`）、先查环（成环就报错且一个字不写）、支持 `--dry-run`。
  要往**中间**插一步（不是追加到末尾）用 `block insert <锚块> [--before|--after]`，它同样把接线改对。
- **实现**在仓库根的 `loomerto/` 包里（`model` / `store` / `render` / `workers` / `cli` 五层，见
  [`docs/architecture.md`](docs/architecture.md)）；命令速查表在 SKILL.md，可直接复制。

## skills/plan-weave/remind-collaborators

提醒的那一半 —— **这条 skill 里纪律比格式重要**。一条合格的提醒有四个要件，缺一个就是唠叨：
块 id（`T-004#B-001`，不是「那个配 token 的事」）、plan 文件的绝对路径（这是别的 agent 唯一的入口，
也是你不在场时唯一还站着的东西）、一条命令就能做的下一步、以及给人时那行 `plan.html` 的 `file://` URL。

- **什么时候推**：块变 ready 且是他的 → 推该块 owner 一次；悬置超时（默认 24h）→ owner + 用户；
  评审打回 → 实现者，带 feedback 原文；全 plan 停滞 / 有 blocked 需要决定 → 用户。
  定时 digest 默认每 6h，**静默时段（默认 23:00–08:00）不发**。
- **静默与去重**：一次只推一件事；同一件事不推第二次（除非真的又超时一档）；只在状态真的变了才推，
  没变就一句话「无变化」；别人已经在自己推进（claimed/running 且没过期）时不要插话。
  用户说「别再提醒我这件事」→ 写进 plan 的 `cadence`/日志，之后不再提。
- **常见错误**：把 digest 原文群发（每个人都收到别人的下一步 → 全是噪音，要用 `--to`）；
  只发聊天里一句话不带路径（三天后没人找得到）；用「@所有人」代替「@该动的人」；
  用户没要求就把定时提醒开起来（会一直烧 token —— **开之前先问**）。

## skills/agent-orchestration/intake-a-running-collaboration

**你是后进来的那个**：用户把你 @ 进一条已经有别的 agent 在跑的 thread（典型开场
「come and help us」），工作正在同时进行，而你**不能碰**他正在跑的东西。你的产物是**记录**，不是他的动作。

- **硬前提**：同一个 thread 里常有多个 bot（执行方、台账方、记录员）—— 先确认你是哪一半，不跟对方抢
  同一个动作；**不采信自述，也不替对方定罪**（他给的结论与你实测到的分开写，没测到的标「待确认」）；
  每个动作先算成本（这类 thread 里通常已经有人因为一次重查询拖垮机器而被批评过）。
- **证据只要秒级的**：日志尾部 / `/proc/[0-9]*/cmdline` 判活（**不要** `ps | grep <脚本名>` —— busybox
  会截断命令名，得到假阴性）/ 同一计数隔 20 秒测两次（差值 ⇒ 速率，同时证明进程活着）/
  对具体路径 `ls -l` 证产物存在。**全库扫描先算成本**：`du`、对数万文件逐个 `stat` 在弱 NAS 上要十几分钟，
  还会饿死对方正在跑的进程 —— 只要一个数就换只读单点 + 抽样换算。
- **两个假警报要先排除**：名字不符合你的假设 ≠ 异常（git-annex 的 hashdir 是 **base62**，`0G`/`2z`/`Pk`
  都合法，用 `^[0-9a-f]{2}$` 过滤会把大批合法目录算成「有人在写这个库」，凭空造出一场数据危机）；
  用 **mtime** 判时段，不要用推断链 —— 用户对自己机器上亲眼所见现象的观察优先于你的推断。
- **先找已有的共享产物再决定建不建**：同一目标已有 plan / 台账 → 续写它；没有 → 才新建。
  同一目标两份真相 = 这套体系要消灭的东西。
- 可直接抄的命令片段（thread 溢出文件解析、`/proc` 判活、双测速率、抽样换算、mtime 归属）在
  `references/read-only-evidence-recipes.md`；所有远端检查都套在 `perl -e 'alarm shift; exec @ARGV' 60`
  里（macOS 没有 GNU `timeout`，挂住的命令永远不会返回）。

## skills/plan-weave/check-plan-temp-hygiene

**交付前的第一问：跑完之后会不会在盘上留下一堆没人管的临时文件。** 判据三问，每问都给证据：

- **生产**：扫 doc / done_when / cmds / 产物 / run / 日志，找会写临时或中间产物的形态（`/tmp`、
  `$TMPDIR`、`scratch`、`~/.cache`、`_migrate`、`.tmp`/`.part`、`临时文件`/`中间产物`/`暂存目录`…）。
- **声明**：块 doc 里一行 `临时文件：<路径/glob>`、产物字段指向临时路径、或 `temps` 字段。
- **收尾**：一个节点在**流程上排在所有生产块之后**、负责删除它们，且 `done_when` 可核验。

结论四值：`✅ 闭环` / `⚠️ 部分`（收尾在，但声明缺项或位置偏早）/ `❌ 不闭环`（有生产、没人收尾，exit 1）/
`➖ 无需清理（没检测到）`。**`➖` 是「没查出来」，不是「没有」** —— 判据只看文本，拿不准就加 `--strict`。

- **给的是能照抄的补法**：`❌` 时直接打印按你的 plan 现算的 `task new` / `block new` / `block set` 命令
  （含任务号、`--deps`、清单与判据骨架），照抄即可把「删除临时文件」这个收尾任务节点建起来。
- **同音词是主要误报源**（第一版实测误判 4 份真 plan）：「暂存」= git staging、「副本」= 工作副本、
  「残留」= 没留下坏链接、「截图」= 笔记里的附件 —— 都不是临时文件；强判据只认能指认
  「临时 / 中间 / 缓存」性质的字样。
- 实测基线（2026-10-07，9 份 plan / 337 块）：`➖` 6 份 · `⚠️` 1（drive-sync）· `❌` 2
  （lab-migration 的 `/Volumes/SSD/_migrate/*` 暂存区、repo05-annex-recovery 的 `/tmp/quarantine_move.sh`）。

## skills/plan-weave/check-plan-node-commands

**交付前的第二问：每个节点是不是都能照抄一条命令直接跑。** 两条判据：每个块至少一条可直接执行的命令
（`cmds` 字段 / doc 的代码围栏 / 行内反引号，三处任一）；命令里每个可替换变量都有明确来源（块 `vars`、
plan 级 `vars`、块 doc 的 `<名> = 值` 定义行、同块赋值）。**缺则 `❌ 不批准`（exit 1）**，并逐块给出
出处、证据原文与补法。

- **命令形态识别**：只认「分段首词是程序 / 路径 / 变量」的行 —— 围栏里的目录树、预期输出、笔记片段不算；
  首词本机不认识只给 `⚠️`（可能装在别的机器上）；脚本名没带路径（如 `scripts/x.sh`）也 `⚠️`
  （照抄粘贴会 `command not found`）。
- **环境变量不是待填变量**：`$HOME`、`$TMPDIR` 这些属 `AMBIENT_ENV`，不要求定义（第一版把 `$HOME`
  判成缺定义，在 lab-migration 上凭空造出 79 条「变量未定义」）。
- **中文描述型占位符直接判 ❌**：`<路径>`、`<目标目录>` 是「填不进去的描述」，不是变量名。
- 实测基线（2026-10-07，9 份 plan / 276 个在册块，另 61 块已取消默认跳过）：**9/9 都不批准** ——
  缺命令 133 块、变量未定义 80 块、中文占位 99 处，只有 42 块全过。这是口径的预期结果：
  现在的块文档写的是散文，没人写命令。
