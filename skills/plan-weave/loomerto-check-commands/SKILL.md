---
name: loomerto-check-commands
description: "Use when 要看一份 plan 每个节点有没有能直接跑的命令、可替换的变量有没有定义。缺命令或变量没定义就不批准（exit 1）。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [plan, collaboration, commands, variables, validation]
    category: plan-weave
    related_skills: [loomerto-plan, loomerto-check-temps, loomerto-remind]
---

# 一份 plan 的节点命令校验

## When to Use

- 一份 plan 要建块 / 送审 / 交接，先回答「每个节点是不是都能照抄一条命令直接跑」。
- 有人问「这个 plan 的节点有没有可直接执行的命令」「命令里的变量定义了吗」。
- 你要给块补命令或补变量定义，先跑一遍看哪些块缺、缺哪个变量。
- **会话上下文变长**（跨了 3+ 回合 / 要向接手的人解释背景 / 多条线并行）时：先把后续规划、子代理分配与执行都落成 plan 的块，再按块推进 —— 动作见 `loomerto-plan` 的「会话一长，先把它落到 plan 上」。

**不属于本 skill**：
- 临时文件有没有声明、有没有收尾节点删除 → `loomerto-check-temps`（那条管临时文件闭环）。
- 图质量（环 / 悬空依赖 / 无主就绪块）→ `loomerto check`。

## 判据（两条，不满足就不批准）

1. **每个任务节点（= 块；块是唯一能承载 doc / 判据 / 命令的单元）至少有一条可直接执行的命令**，
   写在该块的 `cmds` 字段、doc 的代码围栏、或 doc / done_when 的行内反引号里。
2. **命令里出现的每一个可替换变量都有明确来源**：
   块 `vars` / plan 级 `vars` / 块 doc 里的定义行（`<名> = 值`）/ 同一块命令里的赋值（`P=…`）。

| 结论 | 含义 | 退出码 |
|---|---|---|
| ✅ 批准 | 每块都有命令、每个变量都有定义 | 0 |
| ⚠️ 通过但有疑点 | 首词本机不认识 / 脚本名没带路径 / 定义是空话 | 0 |
| ❌ 不批准 | 有块缺命令、或变量没定义、或占位符是描述（填不进去） | 1 |

## 命令与变量是怎么认出来的（口径）

- **命令来源优先级**：`cmds` 字段 > doc 的 ``` 围栏 > doc / done_when 的行内反引号。
  围栏里的**目录树、预期输出、散文**不算命令 —— 只认「分段首词是程序 / 路径 / 变量」的行
  （`$ ` 提示符会被剥掉，`#` 注释行跳过）。
- **首词三档**：已知程序表（含本机常用工具与结构生物学程序）或 PATH 里能找到 → ✅；
  路径形态（`/x`、`./x`、`~/x`、`*.py`）→ ✅；小写程序名形态但本机没有 → ⚠️（可能装在别的机器上）。
- **环境变量不算待填变量**：`$HOME`、`$TMPDIR`、`$VIRTUAL_ENV`、代理变量等是环境自带的（`AMBIENT_ENV`），
  不要求人替换，所以不判缺定义。
- **占位符三种写法分开判**：`<name>`（要求定义）、`$VAR` / `${VAR}`（要求定义或同块赋值）、
  `{{name}}`（要求定义）；**中文描述型占位符**（`<路径>`、`<目标目录>`、`<这里>`）直接判 ❌：
  它是「填不进去的描述」，不是变量名。

## Workflow

1. **跑**：`python3 "$C" <slug>` —— 结论先行一行（`✅ 批准` / `❌ 不批准` + 各类块的计数），再逐块列证据。
2. **逐条核证据**：每个 ❌ 都给出 `出处（doc 围栏#N / 反引号 / cmds[i]）`、`证据原文`、`怎么补`。
3. **补**：把命令写进块 doc 的 ```bash 围栏，并在同一块 doc 里给每个变量一行定义，然后
   `loomerto block describe <slug> <块 id> --doc "<原 doc + 命令段>"`（`--doc` 是整段替换，原 doc 别丢）。
4. **重跑**：`exit 0`（只剩 ⚠️ 也算过）才算批准。

## 命令速查

```bash
# 脚本就在本 skill 的 scripts/ 下（`skill_view` 给的 `skill_dir`）；路径与本 profile 无关：
C=$(ls ~/.hermes/skills/*/loomerto-check-commands/scripts/check_plan_node_commands.py \
       ~/.hermes/profiles/*/skills/*/loomerto-check-commands/scripts/check_plan_node_commands.py 2>/dev/null | head -1)
python3 "$C" build-plan-weave            # 结论 + 逐块 ❌/⚠️ 证据 + 怎么补
python3 "$C" build-plan-weave --verbose  # 连通过的块也列出来
python3 "$C" build-plan-weave --only T-003        # 只看某个任务
python3 "$C" build-plan-weave --only T-003#B-002  # 只看某个块
python3 "$C" build-plan-weave --json     # 机器可读：approved / rows[].fails / rows[].warns
python3 "$C" build-plan-weave --no-which # 跨机器跑：不用 PATH 探测首词
```

退出码：`0` 批准（含只有 ⚠️）· `1` 不批准 · `2` 用法错 · `4` 找不到 plan。

## 检查点

| 触发 | 动作 |
|---|---|
| 块标了 `cancelled` | 默认跳过（不做的活不要求命令）；要一起看用 `--include-cancelled` |
| 判 ❌「变量没定义」 | 只补定义、不要删变量 —— 删了变量这条命令就不通了 |
| 判 ⚠️「首词本机不认识」 | 先确认那是别的机器上的程序名（不是伪代码）再放过 |
| 想把「批准」当验收 | 验收判据是 `exit 0` + 结论行；不要只看有没有输出 |

## 坑（规则 + 机制）

- **块是唯一粒度**：任务（`T-00N`）只有标题与依赖，没有 doc / 判据 / 命令 —— 「每个任务节点都要有命令」
  只能落到块上。**别去给任务加命令字段**，那会和「一个块一件事」的模型打架。
- **反引号里的东西不都是命令**：`Pasted image.png`、`E. coli > WM3064`、`bb2af00b5`、`repo05-annex-recovery`
  这些都是笔记正文里的反引号片段，第一版因为「首词像程序名」把它们当命令（实测 6 个块误判）。
  现在的口径：**小写程序名形态 + ≥2 个分段**才算候选，且单独出现最多只给 ⚠️。
- **`$HOME` 不是「未定义的变量」**：它是环境变量，人不需要替换它。第一版把它判成缺定义，
  在 lab-migration 上凭空造出 79 条「变量未定义」。要加白名单就往 `AMBIENT_ENV` 里加，别改判定逻辑。
- **`--doc` 是整段替换**：补命令时要把原 doc 一起带上（`block describe` / `block set --doc` 都没有「追加」语义），否则就是把
  原来的「做什么」删掉。补完用 `loomerto render <slug>` 刷一下 PLAN.md，人看的那两份也跟着更新。
- **别为了让它过就把命令写成伪代码**（`跑一遍校验`、`<路径>`）：校验器认的是「能照抄进 shell」的形态，
  伪代码只会换一种方式被抓住（中文占位符那条判据）。

## 实测基线（2026-10-07 · plan-weave profile 的 9 份 plan）

**9/9 都不批准**（这是口径的预期结果：现在的块文档写的是散文，没人写命令）：

| plan | 块 | ✅ | ⚠️ | ❌ | 缺命令 | 变量未定义 | 中文占位 |
|---|---|---|---|---|---|---|---|
| agentskill-labproject-migration | 22 | 0 | 0 | 22 | 22 | 0 | 0 |
| build-plan-weave | 11 | 0 | 0 | 11 | 11 | 0 | 0 |
| drive-sync | 18 | 0 | 0 | 18 | 18 | 0 | 0 |
| knowledge-delink | 20 | 2 | 0 | 18 | 18 | 0 | 0 |
| lab-migration | 137 | 38 | 0 | 99 | 1 | 79 | 98 |
| labmig-test2 | 5 | 2 | 1 | 2 | 0 | 1 | 1 |
| ledger-box-registry | 11 | 0 | 0 | 11 | 11 | 0 | 0 |
| repo05-annex-recovery | 35 | 0 | 0 | 35 | 35 | 0 | 0 |
| zsqlab10-hisprobe-4constructs | 17 | 0 | 0 | 17 | 17 | 0 | 0 |
| **合计** | **276**（另 61 块已取消、默认跳过） | **42** | **1** | **233** | **133** | **80** | **99** |

lab-migration 是唯一一份「写了命令但没写变量定义」的（98 处中文占位符 `cp -a <源> <目标>` 之类）——
它说明这条判据不是空转：命令有了，缺的就是「变量从哪来」。基线是快照，不是验收线。

## Support files

| 文件 | 承担什么 |
|---|---|
| `scripts/check_plan_node_commands.py` | 命令抽取（cmds / 围栏 / 反引号）+ 变量定义四来源 + 逐块判定；纯 stdlib，支持 `--json` |
| `test-prompts.json` | 触发路由的正例与兄弟诱饵（分界：命令可执行性 vs 临时文件闭环） |
| `test-results.md` | 路由盲测 r1 的结论与「接受的代价」（判官 A/B 16/16 一致，定版） |
