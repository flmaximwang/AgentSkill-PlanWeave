"""对一份 plan 的**所有改动**都收在这一层：命令层（`cli.py`）与画布服务（`serve.py`）共用同一套语义。

这里只改 dict —— 不落盘、不 print、不 `sys.exit`；出错抛 `PlanError`（带建议的退出码），
由最外层决定怎么显示。**落盘由调用方做 `store.commit()`**（它同时同步三个视图）。

为什么单开一层：状态机（`runs` / `feedback` / `exec` / `log` 的写法）只能有一份 ——
命令一层、画布服务再来一份，两边迟早漂；「改状态」的语义（打回、收工清线程登记…）是这套东西
最容易走样的地方，必须只有一个实现。
"""

from __future__ import annotations

import re

from .model import (BLOCK_FIELDS, BLOCK_STATUS, KINDS, PlanError, all_blocks, deps_of, find,
                    find_soft, guard_acyclic, log_event, new_block, next_block_id, next_ids, now)

TASK_STATUS = ["pending", "running", "done", "blocked", "cancelled"]

FIELD_ZH = {"title": "标题", "doc": "做什么", "kind": "类型", "owner": "认领人",
            "input": "输入", "output": "输出", "command": "命令", "done_when": "判据"}

# 「改状态」时每种状态收哪些旗标 —— `set` 一个入口同时管「状态」与「身份（谁在做 + 线程）」，
# 参数按状态限制：不是这个状态的语义就别在这个状态上给（给了 ⇒ 退 2 并列出该状态收什么）。
_THREAD = {"--by", "--delegation", "--task-index", "--transcript"}
_DOC = {"--owner", "--note", "--at", "--doc", "--done-when"}
BLOCK_SET_FLAGS = {
    "pending":   _DOC,
    "claimed":   _DOC | _THREAD,
    "running":   _DOC | _THREAD,
    "review":    _DOC | _THREAD,
    "done":      _DOC | {"--by", "--artifact"},
    "blocked":   _DOC | {"--by"},
    "cancelled": _DOC,
}
TASK_SET_FLAGS = {
    "pending":   {"--owner", "--note", "--at"},
    "running":   {"--owner", "--note", "--at"} | _THREAD,
    "done":      {"--owner", "--note", "--at"},
    "blocked":   {"--owner", "--note", "--at"},
    "cancelled": {"--owner", "--note", "--at"},
}


def check_set_flags(status: str, given, *, is_block: bool) -> None:
    """按状态卡参数：这个状态不收的旗标 ⇒ PlanError（并把该状态收什么列出来）。"""
    table = BLOCK_SET_FLAGS if is_block else TASK_SET_FLAGS
    if status not in table:        # 状态本身就不合法：留给 set_status 报（这里不抢它的话说）
        return
    bad = sorted(set(given) - table[status])
    if bad:
        raise PlanError(
            f"{'块' if is_block else '任务'}状态 {status} 不收 {'、'.join(bad)} —— "
            f"它收 {'、'.join(sorted(table[status]))}"
            + ("" if is_block else "（任务的线程登记只在 running 时记）"))


def set_status(plan: dict, ref: str, status: str, *, by: str = "", owner: str = "",
               note: str = "", at: str = "", doc: str = "", done_when=None,
               artifacts=(), delegation: str = "", task_index=None, transcript: str = "",
               actor: str = "agent"):
    """改状态（顺带改 owner / doc / done_when、收产物、登记谁在做 + 那条子代理线程）。

    返回 `(target, old)`。
    语义（与 SKILL.md 的状态表一一对应）：
    - `claimed` / `running` / `review` 记「谁在做」（`exec.by`）；换人时旧线程登记被清掉。
    - `done` / `cancelled` / `pending` 清掉线程登记 —— 谁做过的历史留在 `runs` 里。
    - 从 `review` 走出去、且不是 `done` ⇒ 打回：回到原 owner 手上，`note` 落进 `feedback`。
    - `--delegation` / `--transcript` 只在在途状态（claimed/running/review）收；
      `--artifact` 只在 done 收 —— 表见 `BLOCK_SET_FLAGS` / `TASK_SET_FLAGS`。
    """
    task, block = find(plan, ref)
    target = block or task
    if block:
        if status not in BLOCK_STATUS:
            raise PlanError(f"block 状态只能是 {BLOCK_STATUS}")
    elif status not in TASK_STATUS:
        raise PlanError("task 状态只能是 " + "/".join(TASK_STATUS))
    given = set()
    for flag, val in (("--by", by), ("--owner", owner), ("--note", note), ("--at", at),
                      ("--delegation", delegation), ("--transcript", transcript)):
        if val:
            given.add(flag)
    if task_index is not None:
        given.add("--task-index")
    if artifacts:
        given.add("--artifact")
    if block is not None:
        if doc:
            given.add("--doc")
        if done_when:
            given.add("--done-when")
    check_set_flags(status, given, is_block=block is not None)
    ts = at or now()
    old = target["status"]
    target["status"] = status
    target["status_since"] = ts
    if owner:
        target["owner"] = owner
    if block and doc:
        target["doc"] = doc
    if block and done_when:
        target["done_when"] = list(done_when)
    if block and status in ("claimed", "running", "review", "done", "blocked"):
        block.setdefault("runs", []).append({
            "at": ts, "by": by or target.get("owner") or actor,
            "from": old, "to": status, "note": note or ""})
    if block and old == "review" and status != "done" and note:
        block["feedback"] = note
    if block and status == "done" and artifacts:
        block.setdefault("artifacts", []).extend(artifacts)
    if status in ("claimed", "running", "review"):
        ex = dict(target.get("exec") or {})
        who = by or ex.get("by") or target.get("owner") or actor
        if ex.get("by") and ex.get("by") != who:      # 换人了：旧线程不再代表这一块
            ex = {}
        ex["by"] = who
        ex["started"] = ex.get("started") or ts
        target["exec"] = ex
    elif target.get("exec"):
        prev = (target.get("exec") or {}).get("by") or "?"
        target["exec"] = {}
        log_event(plan, "exec", f"{target['id']}: 线程登记已清除（@{prev} 收工）",
                  actor=actor, ref=target["id"])
    if delegation or transcript:       # 在途状态才收（上面的状态闸已经卡过）
        ex = dict(target.get("exec") or {})
        if delegation:
            ex["delegation"], ex["task_index"] = delegation, task_index or 0
        if transcript:
            ex["transcript"] = transcript
        if note:
            ex["note"] = note
        target["exec"] = ex
        log_event(plan, "exec", f"{target['id']}: 登记线程 {delegation or '（未记线程号）'}"
                  + (f"#{ex.get('task_index') or 0}" if delegation else "")
                  + (f" @{ex.get('by')}" if ex.get("by") else "")
                  + (f" · 转录 {transcript}" if transcript else "（没有转录）")
                  + (f"（{note}）" if note else ""), actor=actor, ref=target["id"])
    log_event(plan, "status", f"{target['id']}: {old} → {status}"
              + ("（doc 已更新）" if (block and doc) else "")
              + ("（done_when 已更新）" if (block and done_when) else "")
              + (f"（{note}）" if note else ""), actor=actor, ref=target["id"])
    return target, old


def edit_block(plan: dict, ref: str, *, title=None, doc=None, done_when=None, owner=None,
               kind=None, note: str = "", actor: str = "agent"):
    """只改块的文档字段（**不动状态**）—— 画布上「保存字段」走这条。返回 `(block, changed)`。

    `done_when=[]` 表示「把判据清空」（与「没给」不同，用 `None` 表示没给）。
    """
    _task, block = find(plan, ref)
    if block is None:
        raise PlanError(f"{ref} 是任务，不是块")
    if kind is not None and kind not in KINDS:
        raise PlanError(f"块类型只能是 {KINDS}")
    vals = {"title": title, "doc": doc, "kind": kind, "owner": owner}
    changed = [FIELD_ZH[k] for k, v in vals.items() if v not in (None, "")]
    for k, v in vals.items():
        if v not in (None, ""):
            block[k] = v
    if done_when is not None:
        block["done_when"] = list(done_when)
        changed.append("判据")
    if not changed:
        return block, []
    log_event(plan, "block", f"{block['id']} 改了 {'、'.join(changed)}"
              + (f"（{note}）" if note else ""), actor=actor, ref=block["id"])
    return block, changed


def set_field(plan: dict, ref: str, key: str, value, *, note: str = "", actor: str = "agent"):
    """改块的**一个**属性（`block set_title` / `set_doc` / `set_type` / `set_input` /
    `set_output` / `set_command` / `set_audit` 共用的实现）—— 不动状态。返回 `(block, 原值, 新值)`。

    与 `edit_block`（画布上「保存字段」一次改好几个、且只改非空的）的分工：这里是命令层的
    「一条命令一个属性」，值**整组替换**、空串 = 清空（`title` 除外 —— 块必须有标题）。

    加一个可设属性 = `model.BLOCK_FIELDS` 一处 + cli 的 `_SET_ATTRS` 一处，不必再写一条命令。
    没有变化 ⇒ 抛 `PlanError`：调用方拿不到返回值 ⇒ 不 `commit()`（「我明明改了」而文件没动，
    比直接报错难查得多 —— 与 `set_deps` 同一纪律）。
    """
    _task, block = find(plan, ref)
    if block is None:
        raise PlanError(f"{ref} 是任务不是块 —— `block set_*` 这几个都只改块（改任务用 `task set_status`）")
    if key not in BLOCK_FIELDS:
        raise PlanError(f"{key} 不是块的属性 —— 能设的见 `model.BLOCK_FIELDS`")
    if key == "kind":
        new = (value or "").strip()
        if new not in KINDS:
            raise PlanError(f"块类型只能是 {KINDS}")
    elif key == "title":
        new = (value or "").strip()
        if not new:
            raise PlanError("块要有标题 —— 清空标题不是一条能设的属性"
                            "（真不要这个块了用 `block remove`）")
    elif key == "done_when":
        # 值是列表（每条 --audit 一个元素）或空串（清空）；元素里的 `;` 仍算分隔
        parts = value if isinstance(value, list) else [value or ""]
        new = [c.strip() for v in parts for c in re.split(r"[;；]", v or "") if c.strip()]
    else:
        new = (value or "").strip()
    old = block.get(key)
    if old == new:
        shown = "、".join(old or []) if isinstance(old, list) else (old or "空")
        raise PlanError(f"{block['id']} 的{FIELD_ZH.get(key, key)}没变（{shown}）"
                        f"—— 没有写入任何东西")
    block[key] = new
    log_event(plan, "block", f"{block['id']} 改了 {FIELD_ZH.get(key, key)}"
              + (f"（{note}）" if note else ""), actor=actor, ref=block["id"])
    return block, old, new


def add_task(plan: dict, title: str, *, id: str = "", owner: str = "", deps=None,
             note: str = "", actor: str = "agent"):
    """加一条任务（泳道）。返回新任务 dict。"""
    if not (title or "").strip():
        raise PlanError("任务要有标题")
    ids = [t["id"] for t in plan["tasks"]]
    tid = id or next_ids(plan, "T-", ids)
    if tid in ids:
        raise PlanError(f"任务 {tid} 已存在")
    task = {"id": tid, "title": title, "owner": owner or "", "status": "pending",
            "deps": list(deps or []), "blocks": [], "note": note or "", "exec": {}}
    plan["tasks"].append(task)
    log_event(plan, "task", f"新增任务 {tid}「{title}」", actor=actor, ref=tid)
    return task


def add_block(plan: dict, task_ref: str, *, title: str, kind: str = "impl", doc: str = "",
              done_when=(), deps=(), owner: str = "", review_of: str = "",
              status: str = "blocked", actor: str = "agent"):
    """给任务加一个块。返回 `(task, block)`。

    `status` 默认 `blocked`（= 待批准，等有人点头）—— 与 R-10 一致：只有判断这块无需审批
    才能干时才显式给 `pending`。

    形状（有哪些键、默认值）全在 `model.BLOCK_FIELDS`，这里只给值 —— 建块的唯一一处字面量是
    `model.new_block()`。
    """
    task, _ = find(plan, task_ref)
    if not (title or "").strip():
        raise PlanError("块要有标题")
    if kind not in KINDS:
        raise PlanError(f"块类型只能是 {KINDS}")
    if status not in BLOCK_STATUS:
        raise PlanError(f"block 状态只能是 {BLOCK_STATUS}")
    bid = next_block_id(plan, task)
    block = new_block(bid, title=title, kind=kind, status=status or "blocked",
                      owner=owner or task.get("owner", ""), doc=doc or "",
                      done_when=done_when, deps=deps, review_of=review_of or "")
    task["blocks"].append(block)
    log_event(plan, "block", f"新增块 {bid}「{title}」", actor=actor, ref=bid)
    return task, block


def clear_exec(plan: dict, ref: str, *, note: str = "", actor: str = "agent"):
    """清掉「谁在做 + 线程」的登记（状态不动）。返回 `(target, 原登记)`。

    用在：线程已结束 / 交回别人 / 记错了 —— 不清的话 `workers` 会一直报「不在途却挂着登记」。
    """
    task, block = find(plan, ref)
    target = block or task
    old = dict(target.get("exec") or {})
    target["exec"] = {}
    log_event(plan, "exec", f"{target['id']}: 线程登记已清除"
              + (f"（原在做 {old.get('by')}）" if old.get("by") else "（本来就没有）")
              + (f"（{note}）" if note else ""), actor=actor, ref=target["id"])
    return target, old


def assign_block(plan: dict, ref: str, who: str, *, note: str = "", actor: str = "agent"):
    """把一个块指派给某个参与方（`owner`）；`who=""` 表示清掉指派。返回 `(block, 原认领人)`。

    与 `set --owner` 的分工：assign 只管「这块归谁」，不改状态；改状态的同时换人走 `set --owner`。
    """
    _task, block = find(plan, ref)
    if block is None:
        raise PlanError(f"{ref} 是任务不是块 —— assign 只对块有用（任务级的认领在 `task add --owner`）")
    old = block.get("owner") or ""
    who = (who or "").strip()
    if old == who:
        return block, old
    block["owner"] = who
    log_event(plan, "assign",
              (f"{block['id']} 指派给 {who}" if who else f"{block['id']} 清掉指派")
              + (f"（原 {old}）" if old else "")
              + (f"（{note}）" if note else ""), actor=actor, ref=block["id"])
    return block, old


def set_deps(plan: dict, ref: str, *, deps=None, add=(), rm=(), note: str = "", actor: str = "agent"):
    """改一个块的**前置依赖**：`deps` 整组替换（`[]` = 清空）/ `add` 加 / `rm` 去掉。返回 `(block, 原, 新)`。

    依赖是**接线**不是字段（写错一条就是一张假图），所以三道闸都放在这一处，命令层只管参数：
    ① 每条依赖必须**已经存在** —— 悬空依赖 `check` 会一直报错（挂在那儿的块永远等不到）；
    ② 引用当场规整成规范 id（`B-003` → `T-002#B-003`）、去重，免得同一件事写成两种写法；
    ③ 改完**查环**，成环抛 `PlanError`（调用方拿不到返回值 ⇒ 不要 `commit()`，一个字都不写）。

    `deps=None` = 没给（与 `deps=[]`＝清空不同）；`rm` 去掉一条本来就不等的 ⇒ 什么都没变 ⇒ 报错，
    不许静默成功（「我明明删了那条依赖」却还在图上，比报错难查得多）。
    """
    _task, block = find(plan, ref)
    if block is None:
        raise PlanError(f"{ref} 是任务不是块 —— 块的前置用 `block deps <块 ref> --add/--rm`；"
                        f"任务级依赖只能建任务时给（`task add --deps`）")
    if deps is not None and (add or rm):
        raise PlanError("--deps 是整组替换，与 --add / --rm 不能同时给")
    if deps is None and not add and not rm:
        raise PlanError("要说清怎么改：--deps <新的一组>（整组替换，给空=清空）/ --add <加> / --rm <去掉>")
    drop = set()
    for r in rm:
        _rt, rb = find_soft(plan, r)
        drop.add(rb["id"] if rb is not None else r)      # 悬空依赖也能按原样去掉（它解析不出来）
    want = list(deps) if deps is not None else list(deps_of(block)) + list(add)
    new, seen = [], set()
    for d in want:
        dt_, db = find_soft(plan, d)
        if db is None:
            if d in drop:
                continue
            raise PlanError(
                f"依赖 {d} 不是这一份 plan 里的块"
                + ("（它是任务）—— 块只能等另一个块；要等一整条任务，把那条依赖写进任务级依赖"
                   "（`task add --deps`）" if dt_ is not None else
                   " —— 依赖只能写已经存在的块（先建它，或换一条）"))
        if db["id"] == block["id"]:
            raise PlanError(f"{block['id']} 不能等自己")
        if db["id"] in drop or db["id"] in seen:
            continue
        seen.add(db["id"])
        new.append(db["id"])
    old = deps_of(block)
    if new == old:
        raise PlanError(f"{block['id']} 的前置没变（{'、'.join(old) or '无'}）—— 没有写入任何东西")
    block["deps"] = new
    guard_acyclic(plan, f"改 {block['id']} 的前置")
    log_event(plan, "deps",
              f"{block['id']} 的前置：{'、'.join(old) or '（无）'} → {'、'.join(new) or '（无）'}"
              + (f"（{note}）" if note else ""), actor=actor, ref=block["id"])
    return block, old, new


def insert_block(plan: dict, anchor_ref: str, *, before: bool = True, title: str,
                 kind: str = "impl", doc: str = "", done_when=(), owner: str = "",
                 review_of: str = "", status: str = "blocked", note: str = "",
                 actor: str = "agent"):
    """把一个新块插到某个块之前/之后（块**位置**级插入），并把前后接线一次改对。

    - `before=True`（默认）：新块接手锚块原来等的东西（锚块的显式 deps + 它的 review_of），
      锚块改成只等新块。锚块的下游不用动 —— 顺序仍是 `… → 新块 → 锚块 → 下游`。
    - `before=False`：新块等锚块；原来等锚块（或评审锚块）的改成等新块 ——
      `… → 锚块 → 新块 → 下游`（不这么改的话下游会在新块还没做完时就开跑）。

    「两节点之间」= 插到后一个块之前；「最早节点之前」= 插到该任务的第一个块之前。
    返回 `(task, 新块, 改过接线的块 id 列表, 落点说明)`；只改 dict，落盘由调用方 commit。
    """
    task, anchor = find(plan, anchor_ref)
    if anchor is None:
        raise PlanError(f"{anchor_ref} 是任务不是块 —— insert 作用于块（T-001#B-002 或 B-002）；"
                        f"要往任务末尾加块用 `block add --task {task['id']}`")
    if not (title or "").strip():
        raise PlanError("块要有标题")
    if kind not in KINDS:
        raise PlanError(f"块类型只能是 {KINDS}")
    if status not in BLOCK_STATUS:
        raise PlanError(f"block 状态只能是 {BLOCK_STATUS}")
    idx = task["blocks"].index(anchor)
    bid = next_block_id(plan, task)
    inherited = []
    if before:
        inherited = list(deps_of(anchor))
        if anchor.get("review_of"):
            inherited.append(anchor["review_of"])
    nb = new_block(bid, title=title, kind=kind, status=status,
                   owner=owner or anchor.get("owner") or task.get("owner", ""),
                   doc=doc or "", done_when=done_when,
                   deps=[anchor["id"]] if not before else inherited,
                   review_of=review_of or "")
    where = (f"插在 {anchor['id']}「{anchor['title']}」{'之前' if before else '之后'}"
             f"（{task['id']} 第 {idx + (0 if before else 1) + 1} 位）")
    rewired = []
    if before:
        anchor["deps"] = [bid]
        task["blocks"].insert(idx, nb)
    else:
        task["blocks"].insert(idx + 1, nb)
        aid = anchor["id"]
        for _t, b in all_blocks(plan):
            if b["id"] == bid:
                continue
            if aid in deps_of(b):
                b["deps"] = [bid if d == aid else d for d in b["deps"]]
                rewired.append(b["id"])
            if b.get("review_of") == aid:
                b["review_of"] = bid
                if b["id"] not in rewired:
                    rewired.append(b["id"])
    guard_acyclic(plan, f"把 {bid} 插到 {anchor_ref} {'之前' if before else '之后'}")
    log_event(plan, "insert", f"插入块 {bid}「{title}」{where}"
              + (f"（{note}）" if note else ""), actor=actor, ref=bid)
    return task, nb, rewired, where


def move_block(plan: dict, ref: str, to_task_ref: str, *, index=None, note: str = "",
               actor: str = "agent"):
    """把一个块移到**另一条任务**（泳道）里 —— 画布上的跨泳道拖动走这条。

    块的 id 是 `T-00N#B-00N`（**位置即身份**），所以「换泳道」比「换先后」多两件事：
    换成一个新 id（在目标任务里取最小空位），并把**引用旧 id 的接线全部重接** ——
    别的块把它写进 `deps` / `review_of` 的，以及别的任务的 `expanded_from.block`。
    历史字段（`folded_from` / `runs[].block`）是记录，不动。

    `index` = 插到目标任务的第几位（0 起，默认追加到末尾）；同一条任务内则只改先后
    （等价 `reorder_blocks`，此时 id 与接线都不动）。

    返回 `(block, notes)`：`notes` 是给人看的几行（换了 id / 谁改等它 / 空泳道提醒）。
    **前后关系会成环时抛 `PlanError`** —— 与 `expand` / `compress` 一样，调用方必须在
    拿到返回之后才 `commit()`（抛错时内存里的 dict 已经是脏的，别落盘）。
    """
    src, block = find(plan, ref)
    if block is None:
        raise PlanError(f"{ref} 是任务不是块 —— move 作用于块（T-001#B-002 或 B-002）；"
                        f"要把整个任务挪走，先 `block expand` / `block compress` 调整粒度")
    dst, _ = find(plan, to_task_ref)
    old = block["id"]
    if dst["id"] == src["id"]:                     # 同一条泳道：只改先后
        rest = [b["id"] for b in src["blocks"] if b["id"] != old]
        at = len(rest) if index is None else max(0, min(int(index), len(rest)))
        reorder_blocks(plan, src["id"], rest[:at] + [old] + rest[at:])
        return block, [f"留在 {src['id']} 里，只改了先后（第 {at + 1} 位）"]

    new = next_block_id(plan, dst)
    block["id"] = new
    notes = [f"id 换成 {new}（块 id 就是它的位置，换泳道就换 id）"]
    rewired = []
    for _t, b in all_blocks(plan):
        if b is block:
            continue
        hit = False
        if old in deps_of(b):
            b["deps"] = [new if d == old else d for d in b["deps"]]
            hit = True
        if b.get("review_of") == old:
            b["review_of"] = new
            hit = True
        if hit:
            rewired.append(b["id"])
    for t in plan["tasks"]:                        # 展开记录里那个块 id 也是活的引用
        ef = t.get("expanded_from")
        if ef and ef.get("block") == old:
            ef["block"] = new
    if rewired:
        notes.append("改等它的块：" + "、".join(rewired) + "（deps / review_of 已重接）")

    src["blocks"] = [b for b in src["blocks"] if b is not block]
    at = len(dst["blocks"]) if index is None else max(0, min(int(index), len(dst["blocks"])))
    dst["blocks"].insert(at, block)

    try:
        guard_acyclic(plan, f"把 {old} 移到 {dst['id']}")
    except PlanError as e:
        hint = (f"\n  {dst['id']} 的任务级依赖（{'、'.join(dst['deps'])}）在块搬进来后会落到它身上"
                " —— 换个落点，或先解开那条任务级依赖" if dst.get("deps") else "")
        raise PlanError(str(e) + hint) from e
    if dst.get("deps"):
        notes.append(f"⚠ {dst['id']} 的任务级依赖（{'、'.join(dst['deps'])}）从此也算这块的前置"
                     " —— 它可能会退回「等前置」")
    if not src["blocks"]:
        notes.append(f"⚠ 源任务 {src['id']} 现在一个块都没有了（空泳道留着；删任务走 `task remove`）")
    log_event(plan, "move", f"{old} 移到 {dst['id']}（新 id {new}，第 {at + 1} 位）"
              + (f"；重接接线 {len(rewired)} 处：{'、'.join(rewired)}" if rewired else "")
              + (f"（{note}）" if note else ""), actor=actor, ref=new)
    return block, notes


def bypass_block(plan: dict, ref: str, *, note: str = "", actor: str = "agent"):
    """把一个**中间块**从链上摘掉：它在等的前置，改成「原来等它的那些块」直接等（前后接起来）。

    与 `remove` 的分工：`remove` 看见「还有别的块引用它」就停手（要人加 `--force` 自己承担
    悬空）；`bypass` 的整个意思就是**替你把那几处接线改对再删** —— 图上不留悬空依赖，
    也不会凭空少掉一段前置（A → B → C 摘掉 B 之后是 A → C，不是「C 谁也不等」）。

    接线的语义是「等它的**全部**前置」（`deps` 是交集），所以「接起来」= 把 B 从它们的 `deps`
    里去掉、换成 **B 自己等的那几条**（`deps` + `review_of`）。

    返回 `(block, preds, users, notes)`；**成环时抛 `PlanError`** —— 与 `move` / `insert` /
    `expand` / `compress` 同一纪律：调用方拿到返回之后才 `commit()`，抛错时一个字都不写。
    """
    task, block = find(plan, ref)
    if block is None:
        raise PlanError(f"{ref} 是任务不是块 —— bypass 作用于块（T-001#B-002 或 B-002）；"
                        f"整条任务删掉用 `task remove {task['id']}`")
    bid = block["id"]
    preds, seen = [], set()
    for d in list(deps_of(block)) + ([block["review_of"]] if block.get("review_of") else []):
        _t, db = find_soft(plan, d)                 # 悬空依赖解析不出来就跳过（图上本来就没有它）
        if db is not None and db["id"] != bid and db["id"] not in seen:
            seen.add(db["id"])
            preds.append(db["id"])
    users, notes = [], []
    for _t, b in all_blocks(plan):
        if b is block:
            continue
        hit = False
        if bid in deps_of(b):
            b["deps"] = [d for d in b["deps"] if d != bid] + [p for p in preds if p not in b["deps"]]
            hit = True
        if b.get("review_of") == bid:
            if not preds:
                raise PlanError(
                    f"{b['id']} 评审的就是 {bid}，而 {bid} 自己不等任何东西 —— 绕过它会留下一个"
                    f"没头没尾的评审（`check` 会一直报）。先给 {b['id']} 换个评审对象，"
                    f"或改走 `block remove {bid} --force` 自己承担那条悬空")
            b["review_of"] = preds[-1]
            hit = True
        if hit:
            users.append(b["id"])
    if not preds and users:
        notes.append("⚠ 它自己不等任何东西 ⇒ 原来等它的块现在谁也不等（成了新的链头）")
    if not users:
        notes.append("没有别的块引用它 ⇒ 等于一次 `block remove`")
    task["blocks"] = [b for b in task["blocks"] if b is not block]
    guard_acyclic(plan, f"绕过 {bid}")
    if not task["blocks"]:
        notes.append(f"⚠ 任务 {task['id']} 现在一个块都没有了（空泳道留着；删任务走 `task remove`）")
    log_event(plan, "bypass",
              f"绕过块 {bid}「{block['title']}」：它等的前置（{'、'.join(preds) or '无'}）"
              f"直接接给 {'、'.join(users) or '（没人等它）'}"
              + (f"（{note}）" if note else ""), actor=actor, ref=bid)
    return block, preds, users, notes


def reorder_blocks(plan: dict, task_ref: str, order):
    """把一条任务里的块按 `order`（块 id / 块内后缀都行）重排 —— 画布上拖块排序用。

    只改 list 顺序（PLAN.md 与图上的先后），**不碰 deps**：真正的先后由依赖决定。
    清单与任务里的块对不上就抛错（宁可不改，也不悄悄丢块）。
    """
    task, _ = find(plan, task_ref)
    have = [b["id"] for b in task["blocks"]]
    want = [(x if "#" in x else f"{task['id']}#{x}") for x in order]
    if sorted(want) != sorted(have):
        raise PlanError(f"重排清单与任务里的块对不上：给了 {want}，任务里是 {have}")
    if want == have:
        return want
    byid = {b["id"]: b for b in task["blocks"]}
    task["blocks"] = [byid[x] for x in want]
    log_event(plan, "block", f"{task['id']} 的块顺序改为 "
              + "、".join(x.split("#")[1] for x in want), ref=task["id"])
    return want
