"""对一份 plan 的**所有改动**都收在这一层：命令层（`cli.py`）与画布服务（`serve.py`）共用同一套语义。

这里只改 dict —— 不落盘、不 print、不 `sys.exit`；出错抛 `PlanError`（带建议的退出码），
由最外层决定怎么显示。**落盘由调用方做 `store.commit()`**（它同时同步三个视图）。

为什么单开一层：状态机（`runs` / `feedback` / `exec` / `log` 的写法）只能有一份 ——
命令一层、画布服务再来一份，两边迟早漂；「改状态」的语义（打回、收工清线程登记…）是这套东西
最容易走样的地方，必须只有一个实现。
"""

from __future__ import annotations

from .model import (BLOCK_STATUS, KINDS, PlanError, find, log_event, next_ids, now)

TASK_STATUS = ["pending", "running", "done", "blocked", "cancelled"]

FIELD_ZH = {"title": "标题", "doc": "做什么", "kind": "类型", "owner": "认领人"}


def set_status(plan: dict, ref: str, status: str, *, by: str = "", owner: str = "",
               note: str = "", at: str = "", doc: str = "", done_when=None,
               artifacts=(), actor: str = "agent"):
    """改状态（顺带改 owner / doc / done_when、收产物）。返回 `(target, old)`。

    语义（与 SKILL.md 的状态表一一对应）：
    - `claimed` / `running` / `review` 记「谁在做」（`exec.by`）；换人时旧线程登记被清掉。
    - `done` / `cancelled` / `pending` 清掉线程登记 —— 谁做过的历史留在 `runs` 里。
    - 从 `review` 走出去、且不是 `done` ⇒ 打回：回到原 owner 手上，`note` 落进 `feedback`。
    """
    task, block = find(plan, ref)
    target = block or task
    if block:
        if status not in BLOCK_STATUS:
            raise PlanError(f"block 状态只能是 {BLOCK_STATUS}")
    elif status not in TASK_STATUS:
        raise PlanError("task 状态只能是 " + "/".join(TASK_STATUS))
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
    """
    task, _ = find(plan, task_ref)
    if not (title or "").strip():
        raise PlanError("块要有标题")
    if kind not in KINDS:
        raise PlanError(f"块类型只能是 {KINDS}")
    if status not in BLOCK_STATUS:
        raise PlanError(f"block 状态只能是 {BLOCK_STATUS}")
    bids = [b["id"] for b in task["blocks"]]
    bid = f"{task['id']}#" + next_ids(plan, "B-", [b.split("#")[1] for b in bids])
    block = {"id": bid, "title": title, "kind": kind, "status": status or "blocked",
             "owner": owner or task.get("owner", ""), "doc": doc or "",
             "done_when": list(done_when or []), "artifacts": [], "deps": list(deps or []),
             "review_of": review_of or "", "feedback": "", "exec": {},
             "status_since": now(), "runs": []}
    task["blocks"].append(block)
    log_event(plan, "block", f"新增块 {bid}「{title}」", actor=actor, ref=bid)
    return task, block


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
