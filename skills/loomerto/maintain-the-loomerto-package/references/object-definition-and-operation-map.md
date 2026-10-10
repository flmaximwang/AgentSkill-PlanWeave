# plan / task / block 的「定义」与「操作」分布图

用途：用户问「每个对象是怎么定义的」「把定义与操作按对象分 module」时，先看这张图再回答或动手。
**函数名是主键，行号会随提交漂** —— 引行号前重跑：

```bash
cd /Users/maxim/Repositories/Repo/Loomerto
grep -n "^def " loomerto/cli.py
grep -n "^[A-Z_]* = " loomerto/*.py
```

## 一句话

三个对象的定义与操作混在 `model.py` / `edits.py` / `cli.py` 三个文件里，**看全一个对象要开三个文件**；
只有 block 的**形状**有声明，plan 与 task 的键只以字典字面量出现在建对象的那个函数里。

`store.py`（定位 + 原子落盘 + 唯一写入漏斗 `commit()`）/ `render.py`（三视图）/ `workers.py`（线程探活）/
`serve.py`（画布服务）是**整份 plan 级**的，按对象切没有意义。

## plan

- **定义**：没有形状声明。11 个键只在 `cli.cmd_new` 的字典字面量里 ——
  `schema / slug / title / goal / status / created_at / updated_at / cadence{} / participants[] / tasks[] / log[]`
  （`"status": "active"` 是硬编码的；`cadence` 由 `--digest-hours` / `--quiet-hours` 填）。
- **操作**：`cli.cmd_new` / `cli.add_participant`（`id=kind:label[@channel]`）/ `cli.cmd_list` + `_plan_row` /
  `cli.cmd_digest` / `cli.cmd_render` / `cli.cmd_open`；`model.progress` / `log_event` / `normalize_plan` / `now`。

## task

- **定义**：没有形状声明。8 个键只在 `edits.add_task` 的字面量里 ——
  `id / title / owner / status / deps[] / blocks[] / note / exec{}`；任务状态集合 = `edits.TASK_STATUS`
  （`pending / running / done / blocked / cancelled` —— **没有** `claimed` / `review`，那是块的）。
  还有一个历史键 `expanded_from`：只有 `block expand` 写、`compress` 读。
- **操作**：`edits.add_task` / `edits.set_status`（task 分支）/ `edits.check_set_flags` + `edits.TASK_SET_FLAGS`；
  `cli.cmd_task_add`（= `task add`）/ `cmd_task_set_status` / `cmd_task_remove` / `cmd_task_show`，以及 `cli.cmd_block_expand` /
  `cmd_block_collapse`（也建 / 删任务）；`model.task_status`（由块的派生状态折叠）/ `blocks_of` / `owner_of`。

## block

- **定义**：唯一一处 = `model.BLOCK_FIELDS`（键 → 默认值 / 工厂）+ `model.new_block()`（建块唯一字面量）+
  `model.normalize_block` / `normalize_plan`（老数据缺键只补不改）。配套常量：`BLOCK_STATUS` / `ACTIVE` /
  `OPEN` / `KINDS` / `STATUS_OWNER`（状态 × 负责人三档）/ `BLOCK_HISTORY_FIELDS`（`folded_from`，不进那张表）。
  块现在 17 个键，其中 `input` / `output` / `command` 是 R-23 加的（R-19 之前那份形状表只有 14 个）——
  数键别照抄旧笔记，直接 `python3 -c "from loomerto import model; print(list(model.BLOCK_FIELDS))"`。
- **操作**：`edits.add_block` / `insert_block` / `set_status`（block 分支：runs / feedback / exec / 打回）/
  `edit_block` / `set_field`（`block set_*` 那七条的共同实现）/ `assign_block` / `set_deps` / `move_block` /
  `bypass_block` / `reorder_blocks` + `BLOCK_SET_FLAGS` / `FIELD_ZH`；`cli` 的 18 个 `cmd_block_*`
  （`add` / `remove` / `insert` / `bypass` / `expand` / `compress` / `show` / `deps` / `assign` / `move` /
  `set_type|set_title|set_doc|set_status|set_input|set_output|set_command|set_audit`，后七条共用一个
  `cmd_block_set_attr` + `cli._SET_ATTRS`）；
  `model.block_effective`（派生 ready / waiting / claimed）/ `block_deps` / `edge_deps` / `block_graph` / `cycle` /
  `guard_acyclic` / `refs_to` / `stale_blocks` / `exec_brief` / `claim_of` / `next_block_id` / `parse_step` /
  `find` / `find_soft`。

## 按对象切不动的地方（拆模块前必须先处理）

1. `edits.set_status` **一个函数同时管 task 与 block**（两条分支）；`edits.check_set_flags` + 两张表
   （`BLOCK_SET_FLAGS` / `TASK_SET_FLAGS`）也同处管两个对象。
2. **任务级 `deps` 落到块**：`model.block_deps` / `edge_deps` 读任务、结果挂在 block 的派生上 —— 依赖这条线
   天生横跨 task 与 block。
3. `cli.cmd_block_expand` / `cmd_block_compress` 是**结构演算却住在 cli 层**（现存偏移，与是否拆模块无关）；
   搬模块时会撞见 —— 别顺势把它们当纯函数挪进 `model` 而把它的 print 一起带过去。
4. `cli._apply_set` / `cli._apply_file_mode` 与 `store.plan_path` 是三个对象共用的适配层。
5. `store` / `render` / `workers` / `serve` 按对象切没有意义（写入漏斗与三视图是整份 plan 级的）。

## 与硬规则 4 的关系

- **拆成对象模块 = 让 `model` 与 `edits` 并进同一个文件**（纯函数区 + 改动区，用小节隔开），
  **「`cli` 是唯一 print / 退出码」这一半不变**。这是对硬规则 4 的有意放宽，**必须由用户重新拍板**。
- **只给 plan / task 补形状声明**（`PLAN_FIELDS` / `TASK_FIELDS` + `new_plan()` / `new_task()`，照
  `BLOCK_FIELDS` 的样子）**不碰硬规则 4**，是这一族改动里最小的一档。
- 硬规则 1（一份 plan 在哪由调用方说清）、3（纯 stdlib / `plan.json` 唯一真相）、5（文件模式位置参数左移）
  与对象划分无关，任何拆法都不该碰。
