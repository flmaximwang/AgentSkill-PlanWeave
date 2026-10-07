# 画布写回协议（R-02 · `loomerto open`）

> 这份文件写给**接第二个前端**的人（另一个 web 服务、别的画布、一个 IDE 插件）。
> 参考实现 = `loomerto/serve.py` + `loomerto/assets/canvas.html`。模型与操作纪律见
> [`../skills/plan-weave/maintain-a-shared-plan/SKILL.md`](../skills/plan-weave/maintain-a-shared-plan/SKILL.md)，
> 需求见 [`../REQUIREMENTS.md`](../REQUIREMENTS.md)。

## 0. 三条不许破的规矩

0. **观感不许自带一套颜色**：画布与只读看板（`plan.html`）共用 `loomerto/assets/theme.css`
   （颜色 / 字体 / 状态胶囊 `.pill` / 按钮 `.btn` / 分隔线 `#splitter` / 进度条 `.track` / 图例 `.legend`），
   由 `serve.py` 在送出画布页时注入。要状态色就在 JS 里写 `var(--running)`；页面 CSS 只留布局。
   接第二个前端时同理：注同一份主题，别自己调色。
1. **`plan.json` 是唯一真相**。画布不存状态：每次刷新都从数据文件读，每次改动都立刻写回。
2. **写只能走 `edits` + `store.commit()`**。别自己 `json.dump` —— 那会漏掉三个视图的同步、
   事件日志、以及「打回 / 收工清线程登记」这些语义（`edits` 是它们的唯一实现）。
3. **服务只绑 `127.0.0.1`**，纯 stdlib，无认证（本机单用户）。不要 `0.0.0.0`、不要开端口给外网。

## 1. 读

```
GET /api/plan  →  200 {"ok": true, "view": {…}}
```

`view` 由 `serve.view_model(plan)` 算好，**派生一律由 Python 侧的 `model` 算**（别让前端再实现一遍）：

| 字段 | 是什么 |
|---|---|
| `slug` / `title` / `goal` / `status` / `file` | plan 的基本信息与数据文件绝对路径 |
| `rev` | = `plan["updated_at"]`。**写回时必须原样带回** |
| `progress` | `[done, tot]`（`model.progress`） |
| `tasks[]` | 每条泳道：`id/title/status/owner/deps/note` + `blocks[]` |
| `tasks[].blocks[]` | 每个块：`id/title/kind/status(派生)/raw_status/owner/claimed_by/claimed_at/exec/doc/done_when/deps(含任务级展开)/own_deps/review_of/feedback/artifacts/runs(最近 5 条)/rework` |
| `edges` | `[[from, to], …]`（`edge_deps` 算出的依赖边；指向不存在的 id 由前端忽略） |
| `block_statuses` / `task_statuses` / `kinds` | 枚举，给下拉框用（别在前端硬编码） |

## 2. 写

```
POST /api/plan  {"op": …, "rev": "<读到的 rev>", "by": "<谁>", "note": "…", …}
  → 200 {"ok": true, "msg": "T-002#B-001 claimed → running", "view": {…(新的一屏)…}}
  → 400 {"ok": false, "error": "<中文原因>"}        参数 / 模型层说不行（状态非法、找不到块、重排清单对不上…）
  → 409 {"ok": false, "error": "这份 plan 在别处被改过了 —— 先刷新再改"}   rev 过期
```

五个 `op`：

| op | 还要给 | 落到哪 |
|---|---|---|
| `edit` | `ref` + `title?` `doc?` `done_when?[]` `owner?` `kind?` `note?` | `edits.edit_block` —— **只改文档字段，不动状态** |
| `status` | `ref` + `status` + 可选 `by` `note` `owner` | `edits.set_status` —— 与 `loomerto block set` / `task set` 完全同一套（runs / feedback / exec 的写法同一处） |
| `task` | `title` + 可选 `owner` `deps[]` | `edits.add_task` |
| `block` | `task` + `title` + 可选 `kind` `doc` `done_when[]` `owner` `status` | `edits.add_block`（画布默认 `pending`：建块的人就是在画布上批准它的人） |
| `reorder` | `task` + `order[]`（块 id 或块内后缀，**必须与任务里的块一一对应**） | `edits.reorder_blocks` —— 只改 list 顺序，**不碰 deps** |

- **`status` 只收块/任务的真状态**（`BLOCK_STATUS` / `TASK_STATUS`）；写 `ready` / `waiting`（派生）会被拒。
- 一次请求 = 一次 `commit()`：json 落盘与三个视图（`PLAN.md` / `plan.html` / `plan.canvas`）同步完成。
- 失败**不改任何东西**（先改内存 dict，出错直接抛，不落盘）。

## 3. 冲突与幂等

- `rev` 是 `commit()` 每次落盘换的新版本号（`plan["rev"]`，12 位随机）。**不要拿 `updated_at` 当版本号** ——
  它有秒级粒度，同一秒里的两次写入会撞成同一个值。老 plan 没有 `rev` 字段时退回 `updated_at`。
- **任何写入都会换 `rev`** ⇒ 手里拿着旧 `rev` 的写者一定拿到 409。
- 冲突时**不做自动合并**：界面提示「先刷新」——本机单人使用，读-改-写的窗口极小，
  宁可让人重看一眼，也不要把别人的改动悄悄盖掉。
- **不要自动重试**：`status` 这类 op 每次都会往 `runs` 里追加一条，重复提交就是两份历史。
  前端应把 409 呈现给人，由人来点「刷新 → 重做」。

## 4. 这一版画布**不做**什么（故意的）

| 不做 | 为什么 |
|---|---|
| 删块 / 删任务 | 一脚踩坏判据与历史；`loomerto block rm` / `task rm` 会检查谁引用它，界面上做不出口径 |
| 跨泳道拖动 | 块的 id 是 `T-00N#B-00N`（**位置即身份**）：换任务要改 id、并把所有 `deps` / `review_of` 接线跟着改 —— 那是 `block expand` / `block collapse` 的活 |
| 改 `deps` / `review_of` | 同上：依赖是结构，不是摆设；改错了就是一张假图 |
| 改块的派生状态显示 | 派生值只从依赖算，人不手填（写 `ready` 会被模型拒绝） |

要这些操作就用命令（`loomerto block rm / block insert / block expand / block collapse / block new`）——**界面上只做「看得见、调得动」的那部分**，
其余留在命令里，是刻意的分工。
