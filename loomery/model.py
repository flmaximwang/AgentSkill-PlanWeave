"""plan 的数据模型：状态机、派生状态、依赖与图、粒度规则 —— 纯函数，不碰磁盘、不 print、不 exit。

跨 harness 约定：这一层可以被任何程序 import；出错抛 `PlanError`（带建议的退出码），
由最外层（cli.py / 未来的 web 服务）决定怎么显示。
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path


class PlanError(Exception):
    """模型层唯一的错误出口：`code` 是建议的进程退出码（沿用老的 die() 语义）。"""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code

# 状态与类型
BLOCK_STATUS = ["pending", "claimed", "running", "review", "done",
                "blocked", "cancelled"]
ACTIVE = {"claimed", "running", "review"}
OPEN = {"pending", "claimed", "running", "review", "blocked"}
KINDS = ["impl", "review", "decision", "research"]


# 时间
def now() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def parse_ts(s: str):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def hours_since(ts: str) -> float | None:
    t = parse_ts(ts)
    if not t:
        return None
    return (dt.datetime.now().astimezone() - t).total_seconds() / 3600.0


# 找对象
def all_blocks(plan: dict):
    for t in plan["tasks"]:
        for b in t["blocks"]:
            yield t, b

def blocks_of(plan: dict, tid: str):
    for t in plan["tasks"]:
        if t["id"] == tid:
            return t["blocks"]
    return []

def deps_of(block: dict) -> list[str]:
    return list(block.get("deps") or [])

def owner_of(plan: dict, block: dict) -> dict:
    for t in plan["tasks"]:
        if any(b is block or b["id"] == block["id"] for b in t["blocks"]):
            return t
    return {"deps": [], "blocks": []}

def next_ids(plan: dict, prefix: str, existing: list[str]) -> str:
    n = 1
    while f"{prefix}{n:03d}" in existing:
        n += 1
    return f"{prefix}{n:03d}"

def next_block_id(plan: dict, task: dict) -> str:
    return f"{task['id']}#" + next_ids(plan, "B-", [b["id"].split("#")[1] for b in task["blocks"]])


# 依赖与派生状态
def block_deps(plan: dict, task: dict, block: dict) -> list[str]:
    """块的实际前置 = 块自身 deps ∪ 所属任务的所有任务级 deps 里的每一个块（非 cancelled）。

    任务级依赖要落到块级，否则「T-004 依赖 T-003」在图上看不出来，
    一个实际还不能开工的块会被算成 ready。
    """
    out = list(deps_of(block))
    if block.get("review_of"):
        out.append(block["review_of"])
    for tid in (task.get("deps") or []):
        for t in plan["tasks"]:
            if t["id"] == tid:
                out += [b["id"] for b in t["blocks"] if b["status"] != "cancelled"]
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq

def edge_deps(plan: dict, task: dict, block: dict) -> list[str]:
    """画边/排版用的前置：显式 deps + review_of + 每个任务级前置任务的**最后一个**块。

    与 block_deps 的区别：block_deps 是「开工条件」（要求前置任务全部完成），
    edge_deps 只取该任务的收尾块，避免一个任务对另一个任务画出一片线。
    """
    out = list(deps_of(block))
    if block.get("review_of"):
        out.append(block["review_of"])
    live_self = [b["id"] for b in task["blocks"] if b["status"] != "cancelled"]
    if not live_self or live_self[0] == block["id"]:      # 任务级边只从本任务首块引出
        for tid in (task.get("deps") or []):
            for t in plan["tasks"]:
                if t["id"] == tid:
                    live = [b["id"] for b in t["blocks"] if b["status"] != "cancelled"]
                    if live:
                        out.append(live[-1])
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq

def block_effective(plan: dict, block: dict, task: dict | None = None) -> str:
    """派生状态：pending + 依赖全 done => ready；pending + 依赖未全 done => waiting。"""
    st = block["status"]
    if st != "pending":
        return st
    if task is None:
        task = owner_of(plan, block)
    for d in block_deps(plan, task, block):
        _, db = find_soft(plan, d)
        if db is None or db["status"] != "done":
            return "waiting"
    return "ready"

def task_status(plan: dict, task: dict) -> str:
    eff = [block_effective(plan, b, task) for b in task["blocks"]] or ["pending"]
    if all(e == "done" for e in eff):
        return "done"
    if all(e == "cancelled" for e in eff):
        return "cancelled"
    if any(e in ACTIVE for e in eff):
        return "running"
    if any(e == "blocked" for e in eff) and not any(e in {"ready", "waiting"} for e in eff):
        return "blocked"
    if any(e == "ready" for e in eff):
        return "ready"
    return "pending"

def progress(plan: dict) -> tuple[int, int]:
    bs = [b for _, b in all_blocks(plan)]
    live = [b for b in bs if b["status"] != "cancelled"]
    done = [b for b in live if b["status"] == "done"]
    return len(done), len(live)

def stale_blocks(plan: dict, hours: float):
    out = []
    for t, b in all_blocks(plan):
        if block_effective(plan, b, t) in {"claimed", "running", "review"}:
            h = hours_since(b.get("status_since") or plan["updated_at"])
            if h is not None and h >= hours:
                out.append((t, b, h))
    return out


# 图：环与守卫
def block_graph(plan: dict) -> dict:
    """块级依赖图（任务级依赖已落到块、含 review_of），供环检测。"""
    g = {}
    for t, b in all_blocks(plan):
        g[b["id"]] = [d for d in block_deps(plan, t, b) if find_soft(plan, d)[1] is not None]
    return g

def cycle(graph: dict):
    """返回环上的节点序列（含闭合点），无环返回 None。"""
    WHITE, GREY, BLACK = 0, 1, 2
    color, stack = {}, []

    def dfs(n):
        color[n] = GREY
        stack.append(n)
        for m in graph.get(n, []):
            c = color.get(m, WHITE)
            if c == GREY:
                return stack[stack.index(m):] + [m]
            if c == WHITE:
                r = dfs(m)
                if r:
                    return r
        stack.pop()
        color[n] = BLACK
        return None

    for n in graph:
        if color.get(n, WHITE) == WHITE:
            r = dfs(n)
            if r:
                return r
    return None

def guard_acyclic(plan: dict, what: str) -> None:
    c = cycle(block_graph(plan))
    if c:
        raise PlanError(f"{what} 会让块依赖成环：{' → '.join(c)}（没有写入任何东西）")


# 粒度规则
STEP_ORDER = ["pending", "blocked", "claimed", "running", "review", "done"]

def parse_step(spec: str, default_kind: str):
    """--step 的写法：`标题 :: 做什么 :: 判据1;判据2 :: kind`（后三段可省）。"""
    parts = [p.strip() for p in spec.split("::")]
    parts += [""] * max(0, 4 - len(parts))
    title, doc, crits, kind = parts[0], parts[1], parts[2], parts[3] or default_kind
    if not title:
        raise PlanError(f"--step 缺标题：{spec!r}（写法：标题 :: 做什么 :: 判据1;判据2）")
    criteria = [c.strip() for c in re.split(r"[;；]", crits) if c.strip()]
    return title, doc, criteria, kind

def refs_to(plan: dict, ids: set) -> list:
    """哪些块把 ids 里的任一 id 当依赖或评审对象（含任务级依赖落下来的）。"""
    out = []
    for _t, b in all_blocks(plan):
        if b["id"] in ids:
            continue
        if set(deps_of(b)) & ids or (b.get("review_of") in ids):
            out.append(b["id"])
    return out


# 「谁在做」的读法
def exec_brief(obj: dict) -> str:
    """「谁在做」的一行摘要（` · 在做 @x（线程 deleg_xxx#0）`），没人登记就返回空串。"""
    ex = obj.get("exec") or {}
    if not ex.get("by"):
        return ""
    t = f"（线程 {ex['delegation']}#{ex.get('task_index') or 0}）" if ex.get("delegation") else ""
    return f" · 在做 @{ex['by']}{t}"

def claim_of(obj: dict):
    """(谁认领的, 什么时候认领的) —— runs 里最后一次进入 claimed 的那条。"""
    for r in reversed(obj.get("runs") or []):
        if r.get("to") == "claimed":
            return r.get("by") or "", r.get("at") or ""
    return "", ""


# 事件日志（只往 dict 里追加，不管落盘）
def log_event(plan: dict, kind: str, text: str, actor: str = "agent", **extra):
    e = {"at": now(), "actor": actor, "kind": kind, "text": text}
    e.update(extra)
    plan.setdefault("log", []).append(e)
    return e


# 查找（找不到 ⇒ PlanError）
def find(plan: dict, ref: str):
    """ref = T-001 或 T-001#B-001（也接受 B-003 这种块内唯一后缀）。找不到 ⇒ PlanError。"""
    if "#" in ref:
        tid, bid = ref.split("#", 1)
        for t, b in all_blocks(plan):
            if t["id"] == tid and b["id"].split("#")[1] == bid:
                return t, b
        raise PlanError(f"找不到块 {ref}")
    for t in plan["tasks"]:
        if t["id"] == ref:
            return t, None
    for t, b in all_blocks(plan):
        if b["id"].split("#")[1] == ref:
            return t, b
    raise PlanError(f"找不到 {ref}")

def find_soft(plan: dict, ref: str):
    """find() 但不抛错（外部引用可能还没建）。"""
    try:
        return find(plan, ref)
    except PlanError:
        return None, None
