---
name: loomerto-remind
description: "Use when 要提醒人或别的 agent 按 plan 推进。先算清该谁动、只推一件事、带上 plan 路径；包含静默与去重纪律。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [reminder, collaboration, multi-agent, notification, noise-control]
    category: loomerto
    related_skills: [loomerto-plan, handle-a-recurring-progress-instruction]
---

# 提醒别人（和别的 agent）按 plan 推进

## When to Use

- 有人/某个 agent 该动下一块了；或一块悬置太久、被评审打回、被阻塞需要决定。
- 定时（cron / 心跳）触发的进度检查。
- **不适用**：没有变化的时候。没变化就一句话说完，不要提醒。
- **会话上下文变长**（跨了 3+ 回合 / 要向接手的人解释背景 / 多条线并行）时：先把后续规划、子代理分配与执行都落成 plan 的块，再按块提醒 —— 动作见 `loomerto-plan` 的「会话一长，先把它落到 plan 上」。

## 一条提醒的构成

给 **agent** 的提醒是这样（`plan.json` / `PLAN.md` 的绝对路径就是它的入口）：

```
📋 <plan 标题> · 3/9 块（33%）· 更新 <时间>
plan: <绝对路径>/PLAN.md — 开工前先读它，状态只通过 loomerto 改
🔔 @<谁> 现在该动：
  · `T-004#B-001` 配自己的 Discord bot（可开始）
```

给 **人**（用户 / 群）的提醒换成 `file://` 看板 URL —— 人看的是浏览器里的看板，不是 JSON，也不下载附件：

```
📋 <plan 标题> · 3/9 块（33%）· 更新 <时间>
file://<本 profile 的 plans 根>/<slug>/plan.html   # 本机现状：plans 根 = /Users/maxim/.hermes/profiles/plan-weave/workspace/plans
🔔 @<谁> 现在该动：
  · `T-004#B-001` 配自己的 Discord bot（可开始）
```

四个要件，缺一个就是唠叨：

1. **块 id** —— 用 `T-004#B-001`，不要用「那个配 token 的事」。
2. **plan 文件的绝对路径** —— 这是别的 agent 唯一的入口，也是你不在场时唯一还站着的东西。
3. **一条命令就能做的下一步**（状态怎么改、产物放哪）。
4. **给人时：`file://` 看板 URL**（默认就带，别等他要），**并且不发附件、不起服务** ——
   用户明确只要能在浏览器里直接看的 URL（原话「我觉得用 file 协议就行，不用起服务」）。
   截图不算这一条（快照，一改就过期）。
   整条提醒要压到**不被拆分** —— Discord 把超长回复拆成 `(1/2)` `(2/2)` 并加尾注，他明确不要这个尾注。

## 什么时候推、推给谁

| 触发 | 推给谁 | 频率 |
|---|---|---|
| 某块变为 ready 且是他的 | 该块的 `owner` | 一次，别重复 |
| 块悬置超时（默认 24h 无更新） | owner + 用户 | 一次；又过一档再说 |
| 评审返回 `needs_changes` | 实现者 | 立即，带 feedback 原文 |
| 全 plan 停滞 / 有 blocked 需要决定 | 用户 | 按 digest 节奏 |
| 定时 digest（默认每 6h） | 全体（各推各的下一步） | 静默时段（默认 23:00–08:00）不发 |

生成用 `loomerto digest <slug> --to <参与方>`；到点发送用：

```bash
hermes send -t discord:<channel>:<thread> "$(loomerto --plans-root <本 profile 的 workspace/plans> digest <slug> --to default)"
```

## 纪律（这部分比上面重要）

1. **一次只推一件事。** 一条消息里塞三个待决项，等于一个都没推。
2. **同一件事不推第二次**，除非它真的又超时了一档。宁可少推，也不要让对方屏蔽你。
3. **只在状态真的变了才推**。没变就沉默或一句「无变化」。
4. **推的是事实，不是猜测**。你不知道的就写成「待确认」，不要替对方宣布完成。
5. **给 agent 的提醒要能被机械执行**：块 id + 文件路径 + 状态怎么改。给「注意一下」这种
   提醒是浪费一次打扰。
6. **别人已经在自己推进时不要插话**（块是 claimed/running 且没过期）。你的价值在「该谁动」，
   不在「催」。
7. 用户明确说过「别再提醒我这件事」→ 写进 plan 的 `cadence`/日志，之后不再提。

## 常见错误

- 把 digest 原文群发：每个人都收到别人的下一步 → 全是噪音。用 `--to`。
- 只发聊天里的一句话，不带路径 → 三天后没人找得到。
- **只发一张 `plan.png` 截图、或塞个 html 附件、不给能在浏览器直接看的 URL** → 对方每次都得追着你要。
  默认项是 `file:///…/plans/<slug>/plan.html` 这一行，**不发附件、不起服务**。
- 用「@所有人」代替「@该动的人」。
- 在用户没要求时把定时提醒开起来（会一直烧 token）——**开之前先问**。
