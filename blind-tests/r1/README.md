# 路由盲测 r1（2026-10-07）—— 两个新校验 skill 的 description 定版

按 skill `skill-routing-blind-test` 的协议跑的**第一轮**：候选只有每个 skill `description` 的
**前 57 字符 + `…`**，两个独立判官（`delegate_task`，不共享上下文）只读同一份
`judge-input-r1.txt`，逐题选「最该被调用的 skill」，对着金标落逐题矩阵。

## 结论

| 项 | 值 |
|---|---|
| 候选 | 13 个 skill（plan-weave profile 里全部已装技能，生成器断言「候选集合 == 磁盘上的 skill 集合」） |
| 题数 | 16（4 正例 + 1 变体 ×2 个新 skill；既有 3 个 skill 的 4 条触发题；2 条诱饵） |
| 判官 | 2 个独立会话（A / B），各自把 picks 写进 `blind-judge-r1-{A,B}.txt`（两份内容 md5 相同：`66beaad6a855115c62b98a37c4a77469`） |
| 得分 | **A 16/16 · B 16/16 · 逐题 picks 完全一致 16/16** |
| 定版 | **两判官一致 ⇒ 定版，不开第二轮**（协议：「两判官逐题一致即定版」） |

逐题矩阵见 `blind-score-r1.txt`。

## 金标的一处修正（打分前做，题面与 picks 一字未动）

诱饵题 P15（「plan.py check 报了几个告警 …… 有没有环、有没有无主块」）与 P16（「帮我改某个块的
doc，顺便说下 plan.py set 能改哪些字段」）在第一版金标里把 `owner` 写成了**正确答案**
（`maintain-a-shared-plan`），而诱饵题的语义应当是「**不该被触发的那个 skill**」。打分前改成：
`owner = check-plan-temp-hygiene`（P15）/ `check-plan-node-commands`（P16），`kind = should_not_trigger`，
并给全部 16 题补 `expect_pick`（正确答案）。修正只改这两条的语义标注，题面、题号、判官 picks 都没动。

## 五件套

| 文件 | 是什么 |
|---|---|
| `blind-prompts-r1.json` | 冻结的题面（`instructions` + `prompts[]`，题号 P01–P16） |
| `blind-key-r1.json` | 金标（`owner` / `kind` / `expect_pick`） |
| `judge-input-r1.txt` | 判官输入（候选 57 字符列表 + 题面；不含金标）—— 由脚本生成，三道自检：候选覆盖全部 skill、截断口径与磁盘一致、每道题逐字命中 |
| `blind-judge-r1-A.txt` / `-B.txt` | 两个判官的原始 picks + `DONE` |
| `blind-score-r1.txt` | 逐题矩阵与得分 |

## 这一轮证明了什么（与本轮相关的三条）

1. 两个新 skill 的正例**全部命中自己**，两条诱饵都落在 `maintain-a-shared-plan` 上 —— 没被新 skill 吃掉。
2. 既有三个 skill（`maintain-a-shared-plan` / `remind-collaborators` / `intake-a-running-collaboration`）
   的触发题**一题都没被抢走**。
3. 两个窗口都以 `Use when 要看一份 plan` 开头，靠后半句区分（「会不会留下没人清的临时文件」 vs
   「每个节点有没有能直接跑的命令」）。**下一轮若要在窗口里塞新钩子，先看会不会把这两个区分词挤出去** ——
   挤掉哪个，对应那 4 条正例就会整批转投另一半。
