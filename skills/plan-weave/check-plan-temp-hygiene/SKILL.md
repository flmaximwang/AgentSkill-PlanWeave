---
name: check-plan-temp-hygiene
description: "Use when 要看一份 plan 会不会留下没人清的临时文件。逐块扫生产证据 / 声明 / 收尾节点，给 ✅⚠️❌➖ 判定，并给出要补的 plan.py 命令。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [plan, collaboration, hygiene, temporary-files, validation]
    category: plan-weave
    related_skills: [maintain-a-shared-plan, check-plan-node-commands, remind-collaborators]
---

# 一份 plan 的临时文件卫生校验

## When to Use

- 一份 plan 快收尾 / 要送审了，先回答「跑完之后会不会在盘上留下一堆没人管的临时文件」。
- 有人问「这个 plan 有没有人清临时文件」「会不会留下混乱的中间产物」。
- 你要给一份 plan 补「临时文件声明 + 收尾节点」，先跑一遍看缺什么。

**不属于本 skill**：
- 命令本身能不能直接跑、可替换的变量有没有定义 → `check-plan-node-commands`（那条管命令，这条管**临时文件闭环**）。
- 图质量（环 / 悬空依赖 / 无主就绪块 / 悬置超时）→ `plan.py check`。
- 提醒的时机与去重 → `remind-collaborators`。

## 判据（三问，每问都给证据）

1. **生产**：这个 plan 会不会写出临时 / 中间产物？（扫 doc / done_when / cmds / 产物 / run / 日志）
2. **声明**：这些临时文件在哪里被写清楚了（谁产生、在哪）？
3. **收尾**：有没有一个节点在**流程上排在所有生产块之后**、负责把它们删掉，且判据可核验？

| 结论 | 含义 | 退出码 |
|---|---|---|
| ✅ 闭环 | 有生产 + 有声明 + 有排在最后的收尾节点 | 0 |
| ⚠️ 部分 | 收尾在，但声明缺项 / 收尾节点排在流程中段 / 判据不可核验 | 0 |
| ❌ 不闭环 | 有生产，但整个 plan 没人收尾（或只声明了、没人删） | 1 |
| ➖ 无需清理（没检测到） | 没扫到会写临时产物的形态 | 0 |

**➖ 是「没查出来」，不是「没有」**：判据只看文本，plan 里没写的东西它看不见。
拿不准就用 `--strict`（把重定向、`mktemp`、转换器输出这类「写文件形态」也算证据）。

## Workflow

1. **跑**：`python3 "$C" <slug>` —— 结论先行一行，然后三类清单（生产证据 / 声明 / 收尾节点）+ 建议命令。
2. **读证据**：每条证据都写明 `块 id · 字段:行号 · 命中词 · 原文`，逐条核一遍它是不是真的会写临时文件。
3. **按建议补 plan**（`plan.py` 现成命令，不需要改模型；工具按你的 plan 现算任务号与依赖块）：
   ```
   py task  <slug> --title "清理本轮临时文件" --owner <谁> --deps <最后一个生产任务>
   py block <slug> --task T-00N --title "删除本轮临时文件" --kind impl \
      --doc "本轮产生的临时文件：<逐项列路径/glob>（产生自 <生产块 id>）" \
      --done_when "逐项给出归属（已在别处存在 / 不再需要），删除后 test ! -e 为空" \
      --deps <最后一个生产块>
   py set   <slug> <生产块 id> <它现在的状态> --doc "<原 doc>⏎临时文件：<路径/glob>"
   ```
4. **重跑**：改完再跑一次；`exit 0` 且结论不是 ❌ 才算过。

## 命令速查

```bash
C=~/.hermes/profiles/plan-weave/skills/plan-weave/check-plan-temp-hygiene/scripts/check_plan_temp_hygiene.py
python3 "$C" drive-sync                 # 默认：结论 + 前 8 条证据 + 声明 + 收尾节点 + 建议
python3 "$C" drive-sync --evidence      # 证据全列
python3 "$C" drive-sync --strict        # 把「写文件形态」也算生产证据
python3 "$C" drive-sync --json          # 机器可读：verdict / approved / evidence / declarations / cleanup_nodes
python3 "$C" /path/to/plan.json         # 也可以直接指路径（或给 plan 目录）
python3 "$C" <slug> --plans-root <dir>  # 不在本 profile 的 plans 目录里时
```

退出码：`0` 批准（✅ / ⚠️ / ➖）· `1` 不闭环（❌）· `2` 用法错 · `4` 找不到 plan
（找不到时会打印「找过哪些路径」）。

## 检查点

| 触发 | 动作 |
|---|---|
| 结论是 ❌ / ⚠️ | 先补 plan（建收尾任务节点 / 补声明），**不要**为了让判据变 ✅ 去放宽校验器 |
| 证据里出现你没见过的路径 | 先确认那是不是真的临时文件 —— 人写的散文会骗过正则 |
| 你要说「这个 plan 不产生临时文件」 | 只有在结论是 ➖ **且**你已用 `--strict` 复核过时才能这么说 |
| 收尾节点位置被报偏早 | 看它点名的那几个块是否真的产生临时文件；是 → 把收尾块挪到最后，否 → 属噪声，在报告里说明 |

## 坑（规则 + 机制）

- **同音词会骗过正则**（本工具第一版实测误判 4 份真 plan）：「暂存」常指 git staging、「副本」常指
  工作副本 / 两份笔记、「残留」常指「没留下坏链接」、「截图」常指笔记里的附件 —— 都不是临时文件。
  机制：中文里没有词形变化，只能靠上下文判；所以强判据只认能指认「临时 / 中间 / 缓存 / 暂存区」
  性质的字样，`NOT_TEMP` 那条正则专门遮住这些同音行。**放宽它之前先想会不会把 git 暂存又算回来。**
- **别在长 doc 里判「清理语义」**：lab-migration 单个块的 doc 到 18KB，什么词都有 —— 第一版拿整篇
  doc 找「删除 + 临时」，把 8 个普通块判成收尾节点。收尾语义只在**标题 / done_when / cmds** 里找。
- **「收尾」单独不算清理语义**：drive-sync 有一块叫「2019 账本收尾」，那是收尾某件事，不是清文件。
- **位置判据是软的，所以只报 ⚠️**：收尾节点是否「晚于所有生产块」按 `plan.json` 里的顺序
  （任务序 → 块序）算，而生产块集合来自文本证据、可能有噪声 ⇒ 位置偏早时**点名**晚于它的块，让人判。
- **`plan.py` 改不了块的位置**：`set` 只能改状态与文档；移位置要 `expand` / `collapse` 或重建块
  （见 `maintain-a-shared-plan`）。
- **声明有四种写法，任一即算**：① 块 doc 里一行 `临时文件：<路径/glob>`；② 产物（`artifacts`）字段
  指向临时路径（`/tmp`、`scratch`、`_migrate` …）；③ `temps` / `tmp_paths` 结构化字段；④ plan 的 goal 里
  一行同形声明。**不要**把「声明」理解成必须新建字段 —— 这个 pack 里没人用 `temps`，产物字段就够。

## 实测基线（2026-10-07 · plan-weave profile 的 9 份 plan / 337 块）

| 结论 | 份数 | 哪几份 |
|---|---|---|
| ➖ 无需清理 | 6 | agentskill-labproject-migration · build-plan-weave · knowledge-delink · labmig-test2 · ledger-box-registry · zsqlab10-hisprobe-4constructs |
| ⚠️ 部分 | 1 | drive-sync（15 条证据 / 5 处声明 / 收尾节点 `T-004#B-003` 位置正确；`T-003#B-010` 位置偏早被点名） |
| ❌ 不闭环 | 2 | lab-migration（582 条证据，主力是 `/Volumes/SSD/_migrate/*` 暂存区）· repo05-annex-recovery（`/tmp/quarantine_move.sh` 与 `.hermes/cache` 产物，无人收尾） |

基线是**快照**，不是验收线：plan 是活数据，别人改一块就变。合成样例（成功路径）同一次实测跑通：
`temp-ok` → ✅ 闭环（exit 0）· `temp-mid` → ⚠️ 位置偏早 · 无生产证据 → ➖ · 找不到 plan → exit 4 ·
同一输入跑两次逐字节相同。

## Support files

| 文件 | 承担什么 |
|---|---|
| `scripts/check_plan_temp_hygiene.py` | 全部判据：生产证据 / 声明 / 收尾节点 / 建议命令；纯 stdlib，支持 `--json` |
| `test-prompts.json` | 触发路由的正例与兄弟诱饵（分界：临时文件 vs 命令可执行性 vs 图质量） |
| `test-results.md` | 路由盲测 r1 的结论与「接受的代价」（判官 A/B 16/16 一致，定版） |
