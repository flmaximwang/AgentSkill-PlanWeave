#!/usr/bin/env python3
"""plan.py — plan-weave profile 的 plan 存储 / 状态机 / 渲染 工具。

一个 plan 就是目录里的一组文件（file-backed，可 git 版本化）：

    <profile>/workspace/plans/<slug>/
    ├── plan.json     机器模型（任务图 + 块文档 + 事件日志）——唯一真相
    ├── PLAN.md       人读摘要（自动生成，含 mermaid 图）
    ├── plan.html     自包含可视化（离线可开，无网络依赖）
    └── plan.canvas   Obsidian JSON Canvas 视图（自动生成）

模型借自 PlanWeave：plan → task（节点）→ block（文档）+ 依赖 + 评审回路 + run 记录。
block 的状态机：pending → ready(派生) → claimed → running → review → done，旁支 blocked / cancelled。
评审打回 = 从 review 回到 claimed（块还是原 owner 的，只是重做一遍），打回原因存进 block.feedback，
次数由 runs 里数出来（plan.html 显示成 ⟲N）。

粒度可以调：一个块太大 → `expand` 把它变成一个任务（块本身成为第一步，`--step` 依次追加后续步骤）；
一个任务的各步太琐碎 → `collapse` 把任务压回一个块。两个动作都把「谁在等它 / 它在等谁」一次改对，
不需要手删重建。

时间戳一律本地时区 ISO8601。全部 stdlib，无第三方依赖。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

HERE = Path(__file__).resolve()
PROFILE_HOME = HERE.parents[4]          # scripts/ -> <skill>/ -> <cat>/ -> skills/ -> profile home
PLANS_ROOT = PROFILE_HOME / "workspace" / "plans"
TEMPLATE = HERE.parent.parent / "assets" / "plan.html"

BLOCK_STATUS = ["pending", "claimed", "running", "review", "done",
                "blocked", "cancelled"]
ACTIVE = {"claimed", "running", "review"}
OPEN = {"pending", "claimed", "running", "review", "blocked"}
KINDS = ["impl", "review", "decision", "research"]


# ---------------------------------------------------------------- helpers

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


def plan_dir(slug: str) -> Path:
    return PLANS_ROOT / slug


def load(slug: str) -> dict:
    p = plan_dir(slug) / "plan.json"
    if not p.exists():
        die(f"找不到 plan '{slug}'（{p}）。用 `plan.py new {slug} --title ...` 建一个。")
    return json.loads(p.read_text(encoding="utf-8"))


def atomic_write(path: Path, text: str) -> None:
    """同目录先写临时文件再 os.replace：读者绝不会看到写了一半/被截断的文件。

    plan.html 每次改状态都重写，浏览器若在截断与写入之间打开就会看到空白页 ——
    必须原子替换（rename 在同一文件系统上是原子的）。
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)      # mkstemp 默认 0600；跟普通 write_text 保持一致
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(slug: str, plan: dict) -> None:
    plan["updated_at"] = now()
    d = plan_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write(d / "plan.json",
                 json.dumps(plan, ensure_ascii=False, indent=2) + "\n")


def commit(slug: str, plan: dict, a=None) -> None:
    """落盘 + 同步刷新三个视图，保证 html/canvas/md 永不落后于 plan.json。"""
    save(slug, plan)
    if a is not None and getattr(a, "no_render", False):
        return
    render_all(slug, plan)


def die(msg: str, code: int = 2, quiet: bool = False) -> NoReturn:
    if not quiet:
        print(msg, file=sys.stderr)
    sys.exit(code)


def all_blocks(plan: dict):
    for t in plan["tasks"]:
        for b in t["blocks"]:
            yield t, b


def find(plan: dict, ref: str, quiet: bool = False):
    """ref = T-001 或 T-001#B-001（也接受 B-003 这种块内唯一后缀）

    quiet=True 时找不到也不打 stderr（给 find_soft 用，见下）。
    """
    if "#" in ref:
        tid, bid = ref.split("#", 1)
        for t, b in all_blocks(plan):
            if t["id"] == tid and b["id"].split("#")[1] == bid:
                return t, b
        die(f"找不到块 {ref}", quiet=quiet)
    for t in plan["tasks"]:
        if t["id"] == ref:
            return t, None
    for t, b in all_blocks(plan):
        if b["id"].split("#")[1] == ref:
            return t, b
    die(f"找不到 {ref}", quiet=quiet)


def blocks_of(plan: dict, tid: str):
    for t in plan["tasks"]:
        if t["id"] == tid:
            return t["blocks"]
    return []


def find_soft(plan: dict, ref: str):
    """find() 但不退出进程（外部引用可能还没建），也不打 stderr。"""
    try:
        return find(plan, ref, quiet=True)
    except SystemExit:
        return None, None


def deps_of(block: dict) -> list[str]:
    return list(block.get("deps") or [])


def owner_of(plan: dict, block: dict) -> dict:
    for t in plan["tasks"]:
        if any(b is block or b["id"] == block["id"] for b in t["blocks"]):
            return t
    return {"deps": [], "blocks": []}


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


def next_ids(plan: dict, prefix: str, existing: list[str]) -> str:
    n = 1
    while f"{prefix}{n:03d}" in existing:
        n += 1
    return f"{prefix}{n:03d}"


def log_event(plan: dict, kind: str, text: str, actor: str = "agent", **extra):
    e = {"at": now(), "actor": actor, "kind": kind, "text": text}
    e.update(extra)
    plan.setdefault("log", []).append(e)
    return e


def stale_blocks(plan: dict, hours: float):
    out = []
    for t, b in all_blocks(plan):
        if block_effective(plan, b, t) in {"claimed", "running", "review"}:
            h = hours_since(b.get("status_since") or plan["updated_at"])
            if h is not None and h >= hours:
                out.append((t, b, h))
    return out


# ---------------------------------------------------------------- 粒度调整

STEP_ORDER = ["pending", "blocked", "claimed", "running", "review", "done"]


def block_graph(plan: dict) -> dict:
    """块级依赖图（任务级依赖已落到块、含 review_of），供环检测。"""
    g = {}
    for t, b in all_blocks(plan):
        g[b["id"]] = [d for d in block_deps(plan, t, b) if find_soft(plan, d)[1] is not None]
    return g


def guard_acyclic(plan: dict, what: str) -> None:
    c = cycle(block_graph(plan))
    if c:
        die(f"{what} 会让块依赖成环：{' → '.join(c)}（没有写入任何东西）")


def parse_step(spec: str, default_kind: str):
    """--step 的写法：`标题 :: 做什么 :: 判据1;判据2 :: kind`（后三段可省）。"""
    parts = [p.strip() for p in spec.split("::")]
    parts += [""] * max(0, 4 - len(parts))
    title, doc, crits, kind = parts[0], parts[1], parts[2], parts[3] or default_kind
    if not title:
        die(f"--step 缺标题：{spec!r}（写法：标题 :: 做什么 :: 判据1;判据2）")
    criteria = [c.strip() for c in re.split(r"[;；]", crits) if c.strip()]
    return title, doc, criteria, kind


def next_block_id(plan: dict, task: dict) -> str:
    return f"{task['id']}#" + next_ids(plan, "B-", [b["id"].split("#")[1] for b in task["blocks"]])


def refs_to(plan: dict, ids: set) -> list:
    """哪些块把 ids 里的任一 id 当依赖或评审对象（含任务级依赖落下来的）。"""
    out = []
    for _t, b in all_blocks(plan):
        if b["id"] in ids:
            continue
        if set(deps_of(b)) & ids or (b.get("review_of") in ids):
            out.append(b["id"])
    return out


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


def hermes_home(profile: str) -> Path:
    """线程号 → 转录路径时用的 hermes home；空 / default ⇒ 本机默认 profile 的 ~/.hermes。"""
    base = Path.home() / ".hermes"
    p = (profile or "").strip()
    return base if p in ("", "default") else base / "profiles" / p


def live_root(profile: str) -> Path:
    return hermes_home(profile) / "cache" / "delegation" / "live"


def transcript_path(profile: str, delegation: str, idx: int) -> Path:
    return live_root(profile) / delegation / f"task-{idx}.log"


# ---------------------------------------------------------------- commands

def cmd_new(a):
    d = plan_dir(a.slug)
    if (d / "plan.json").exists() and not a.force:
        die(f"{d}/plan.json 已存在（要覆盖加 --force）")
    d.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": "plan-weave/plan@1",
        "slug": a.slug,
        "title": a.title or a.slug,
        "goal": a.goal or "",
        "status": "active",
        "created_at": now(),
        "updated_at": now(),
        "cadence": {"digest_hours": a.digest_hours, "quiet_hours": a.quiet_hours},
        "participants": [],
        "tasks": [],
        "log": [],
    }
    for spec in a.owner or []:
        add_participant(plan, spec)
    add_participant(plan, "you=human:本人")
    log_event(plan, "created", f"建立 plan：{plan['title']}", actor="agent")
    commit(a.slug, plan, a)
    print(f"✓ 建立 {d}/plan.json")


def add_participant(plan: dict, spec: str):
    """spec: id=kind:label[@channel]   kind ∈ human|agent（缺省 agent）
    例：you=human:本人@discord:1556845249790484511 / rdm-assistance=agent:RdmAsst3813"""
    pid, _, rest = spec.partition("=")
    kind, _, label = rest.partition(":")
    if kind not in ("human", "agent"):
        label = f"{kind}:{label}" if label else kind
        kind = "agent"
    label, _, channel = label.partition("@")
    plan["participants"] = [p for p in plan.get("participants", []) if p["id"] != pid]
    plan["participants"].append(
        {"id": pid or label, "kind": kind, "label": label or pid, "channel": channel})


def cmd_task(a):
    plan = load(a.slug)
    ids = [t["id"] for t in plan["tasks"]]
    tid = a.id or next_ids(plan, "T-", ids)
    if tid in ids:
        die(f"任务 {tid} 已存在")
    plan["tasks"].append({
        "id": tid, "title": a.title, "owner": a.owner or "", "status": "pending",
        "deps": a.deps or [], "blocks": [], "note": a.note or "", "exec": {},
    })
    log_event(plan, "task", f"新增任务 {tid}「{a.title}」", actor=a.actor, ref=tid)
    commit(a.slug, plan, a)
    print(f"✓ {tid} {a.title}")


def cmd_block(a):
    plan = load(a.slug)
    task, _ = find(plan, a.task)
    if task is None:
        die(f"{a.task} 是任务不是块")
    bids = [b["id"] for b in task["blocks"]]
    bid = f"{task['id']}#" + next_ids(plan, "B-", [b.split('#')[1] for b in bids])
    block = {
        "id": bid, "title": a.title, "kind": a.kind,
        "status": getattr(a, "status", None) or "pending",
        "owner": a.owner or task.get("owner", ""), "doc": a.doc or "",
        "done_when": a.done_when or [], "artifacts": [], "deps": a.deps or [],
        "review_of": a.review_of or "", "feedback": "", "exec": {},
        "status_since": now(), "runs": [],
    }
    task["blocks"].append(block)
    log_event(plan, "block", f"新增块 {bid}「{a.title}」", actor=a.actor, ref=bid)
    commit(a.slug, plan, a)
    print(f"✓ {bid} {a.title} ({a.kind})")


def cmd_set(a):
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    target = block or task
    if block:
        if a.status not in BLOCK_STATUS:
            die(f"block 状态只能是 {BLOCK_STATUS}")
    elif a.status not in ("pending", "running", "done", "blocked", "cancelled"):
        die("task 状态只能是 pending/running/done/blocked/cancelled")
    old = target["status"]
    target["status"] = a.status
    target["status_since"] = a.at or now()
    if a.owner:
        target["owner"] = a.owner
    if block and a.doc:
        target["doc"] = a.doc
    if block and a.done_when:
        target["done_when"] = a.done_when
    if block and a.status in ("claimed", "running", "review", "done", "blocked"):
        block.setdefault("runs", []).append({
            "at": a.at or now(), "by": a.by or target.get("owner") or a.actor,
            "from": old, "to": a.status, "note": a.note or ""})
    # 评审打回 = 从 review 走出去、且不是 done：块回到原 owner 手上（claimed），原因记进 feedback
    if block and old == "review" and a.status != "done" and a.note:
        block["feedback"] = a.note
    if block and a.status == "done" and a.artifact:
        block.setdefault("artifacts", []).extend(a.artifact)
    # 「谁在做」跟着状态自动走：claimed/running/review 记下动手的那个（owner 只是认领人）；
    # 收工（done/cancelled）或退回（pending）就清掉线程登记 —— 谁做过的历史留在 runs 里。
    if a.status in ("claimed", "running", "review"):
        ex = dict(target.get("exec") or {})
        by = a.by or ex.get("by") or target.get("owner") or a.actor
        if ex.get("by") and ex.get("by") != by:      # 换人了：旧线程不再代表这一块
            ex = {}
        ex["by"] = by
        ex["started"] = ex.get("started") or (a.at or now())
        ex.setdefault("profile", "default")
        target["exec"] = ex
    elif target.get("exec"):
        prev = (target.get("exec") or {}).get("by") or "?"
        target["exec"] = {}
        log_event(plan, "exec", f"{target['id']}: 线程登记已清除（@{prev} 收工）",
                  actor=a.actor, ref=target["id"])
    log_event(plan, "status", f"{target['id']}: {old} → {a.status}"
              + ("（doc 已更新）" if (block and a.doc) else "")
              + ("（done_when 已更新）" if (block and a.done_when) else "")
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=target["id"])
    commit(a.slug, plan, a)
    print(f"✓ {target['id']} {old} → {a.status}")


def refs_of_block(plan: dict, bid: str) -> list[str]:
    """哪些块把这个块 id 当依赖 / 评审对象（删之前要看）。"""
    out = []
    for _t, b in all_blocks(plan):
        if b["id"] == bid:
            continue
        if bid in deps_of(b) or b.get("review_of") == bid:
            out.append(b["id"])
    return out


def cmd_rm(a):
    """真删一个块或任务（取消 ≠ 删除；用户说删就删）。"""
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block:
        users = refs_of_block(plan, block["id"])
        if users and not a.force:
            die(f"{block['id']} 还被这些块引用：{users} —— 确认后加 --force")
        old = block["status"]
        task["blocks"] = [b for b in task["blocks"] if b["id"] != block["id"]]
        log_event(plan, "remove", f"删除块 {block['id']}「{block['title']}」（原状态 {old}）"
                  + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=block["id"])
        commit(a.slug, plan, a)
        print(f"✓ 已删除块 {block['id']}（原状态 {old}）")
        return
    holders = [t["id"] for t in plan["tasks"]
               if task["id"] in (t.get("deps") or []) and t["id"] != task["id"]]
    if holders and not a.force:
        die(f"任务 {task['id']} 还被这些任务依赖：{holders} —— 确认后加 --force")
    n = len(task.get("blocks") or [])
    plan["tasks"] = [t for t in plan["tasks"] if t["id"] != task["id"]]
    log_event(plan, "remove", f"删除任务 {task['id']}「{task['title']}」（含 {n} 个块）"
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=task["id"])
    commit(a.slug, plan, a)
    print(f"✓ 已删除任务 {task['id']}（含 {n} 个块）")


# ---------------------------------------------------------------- 谁在做 + 子代理线程

THREAD_VERDICT = [
    ("finished", "⚠ 线程已结束"),
    ("wrong", "❌ 号记错"),
    ("quiet", "⏳ 静默"),
    ("stale", "➖ 已无意义"),
    ("unreachable", "❓ 看不到"),
    ("absent", "➖ 无线程"),
    ("ok", "✅ 在动"),
]


def fmt_age(minutes: float) -> str:
    if minutes < 1:
        return f"{int(minutes * 60)}s"
    if minutes < 90:
        return f"{minutes:.0f}m"
    if minutes < 60 * 48:
        return f"{minutes / 60:.1f}h"
    return f"{minutes / 1440:.1f}d"


def probe_thread(ex: dict, stale_min: float):
    """看一眼这条子代理线程现在什么样 —— 只用文件（转录 + manifest），不读任何库。

    返回 (verdict, 证据行, 详情行)；verdict 见 THREAD_VERDICT。
    四值不是三值：❓「看不到」与 ❌「号记错」分开 —— 前者可能是线程在别的机器上、
    或已过 7 天保留期，把它读成「子代理没在跑」就是伪造结论。
    """
    tp = (ex.get("transcript") or "").strip()
    deleg, idx = ex.get("delegation") or "", ex.get("task_index") or 0
    if not tp and not deleg:
        who = (ex.get("by") or "").strip()
        if who:
            return "absent", f"只登记了在做 @{who}，没有子代理线程（人在做 / 还没派给子代理）", []
        return "absent", "块在途，但执行者与线程都没登记（谁在做？）", []
    p = Path(tp or transcript_path(ex.get("profile") or "", deleg, idx))
    if not p.exists():
        if p.parent.exists():
            sibs = sorted(x.name for x in p.parent.glob("task-*.log"))
            return "wrong", f"这个 delegation 目录在，但没有它的转录（目录里是 {sibs or '空'}）", [str(p)]
        return "unreachable", "看不到这条线程（已过 7 天保留期 / 在别的机器上 / 号记错）", [str(p)]
    age_min = (dt.datetime.now().timestamp() - p.stat().st_mtime) / 60.0
    last = ""
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    last = line.rstrip("\n")
    except OSError as exc:
        return "unreachable", f"转录读不了（{exc}）", [str(p)]
    st, exit_reason = "running", ""
    mp = p.parent / "manifest.json"
    if mp.exists():
        try:
            man = json.loads(mp.read_text(encoding="utf-8-sig"))
            for t in man.get("tasks") or []:
                if t.get("index") == idx or (t.get("log") or "") == tp:
                    st = t.get("status") or "running"
                    exit_reason = t.get("exit_reason") or ""
                    break
        except Exception:
            st = "running"          # manifest 坏了不算线程结束，别把读不了读成「已死」
    if st != "running":
        how = st if st == exit_reason or not exit_reason else f"{st}/{exit_reason}"
        return "finished", (f"manifest 说这条线程已经 {how}，块还挂在这里 —— "
                            f"该对账：改状态或重派"), [str(p)]
    if age_min >= stale_min:
        return "quiet", f"静默 {fmt_age(age_min)}（≥{stale_min:g} 分钟没写一行）—— 可能卡住或已死", [str(p)]
    ev = f"转录 {fmt_age(age_min)} 前还写过"
    ev += f"，末行 {last[:110]}" if last else "（还只有表头）"
    return "ok", ev, [str(p)]


def cmd_exec(a):
    """登记「谁在做 + 那条子代理线程」——认领(owner)之外的第二个身份。"""
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    target = block or task
    if a.unset:
        old = target.get("exec") or {}
        target["exec"] = {}
        log_event(plan, "exec", f"{target['id']}: 线程登记已清除"
                  + (f"（原在做 {old.get('by')}）" if old.get("by") else "")
                  + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=target["id"])
        commit(a.slug, plan, a)
        print(f"✓ {target['id']} 已清线程登记")
        return
    if not a.by:
        die("exec 要说清谁在做：--by <参与方 id>（要清掉登记用 --unset）")
    if a.task_index is not None and not a.delegation:
        die("--task-index 只在给了 --delegation 时有意义（一个 delegation 下有多个 task-N）")
    profile = (a.profile or "").strip()
    deleg = (a.delegation or "").strip()
    idx = a.task_index if a.task_index is not None else 0
    tp = a.transcript or (str(transcript_path(profile, deleg, idx)) if deleg else "")
    ex = {"by": a.by, "started": a.at or now(), "profile": profile or "default"}
    if deleg:
        ex["delegation"], ex["task_index"] = deleg, idx
    if tp:
        ex["transcript"] = tp
    if a.note:
        ex["note"] = a.note
    target["exec"] = ex
    log_event(plan, "exec", f"{target['id']}: 在做 @{a.by}"
              + (f" · 线程 {deleg}#{idx}" if deleg else "")
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=target["id"])
    commit(a.slug, plan, a)
    print(f"✓ {target['id']} 在做 @{a.by}" + (f" · 线程 {deleg}#{idx}" if deleg else ""))
    if tp and not Path(tp).exists():
        print(f"⚠ 转录现在不在这台机器上：{tp}"
              f"（还没建 / 在别的机器 / 号记错 —— 跑 `workers` 会一直这么报）")


def cmd_workers(a):
    """逐个看一眼：在途的那些块，登记的子代理线程是不是真的在动。"""
    plan = load(a.slug)
    rows = []
    for t, b in all_blocks(plan):
        e = block_effective(plan, b, t)
        ex = b.get("exec") or {}
        if not ex.get("by") and e not in ACTIVE:
            continue
        if ex.get("by") and e not in ACTIVE:
            v, ev, det = "stale", (f"块现在是「{STATUS_ZH.get(e, e)}」不在途，却还挂着线程登记"
                                   f"（要么把状态改对，要么 `exec … --unset` 清掉）"), []
        else:
            v, ev, det = probe_thread(ex, a.stale_min)
        cby, cat = claim_of(b)
        rows.append({"block": b["id"], "title": b["title"], "status": e, "owner": b.get("owner") or "",
                     "claimed_by": cby, "claimed_at": cat, "exec": ex, "verdict": v,
                     "evidence": ev, "transcript": (det[0] if det else "")})
    order = {k: i for i, (k, _) in enumerate(THREAD_VERDICT)}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["block"]))
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    hard = counts.get("finished", 0) + counts.get("wrong", 0)
    if a.json:
        print(json.dumps({"plan": plan["slug"], "checked": len(rows), "counts": counts,
                          "exit": 1 if hard else 0, "blocks": rows}, ensure_ascii=False, indent=2))
        return 1 if hard else 0
    print(f"plan: {plan['title']}  ({plan['slug']})")
    print(f"看 {len(rows)} 个块 · " + (" · ".join(
        f"{zh} {counts.get(k, 0)}" for k, zh in THREAD_VERDICT if counts.get(k)) or "（没有要看的块）"))
    if not rows:
        print("  没有在途块，也没有线程登记 —— 没什么可查的。")
        return 0
    for r in rows:
        zh = dict(THREAD_VERDICT)[r["verdict"]]
        print(f"\n[{r['status']}] {r['block']}  {r['title']}")
        claim = f"认领 @{r['claimed_by']}" + (f"（{r['claimed_at'][:16].replace('T', ' ')}）"
                                             if r["claimed_at"] else "")
        if not r["claimed_by"]:
            claim = f"认领 @{r['owner'] or '未指派'}"
        print(f"    {claim} · 在做 @{r['exec'].get('by') or '未登记'}")
        print(f"    线程 {r['exec'].get('delegation') or '—'}"
              f"{'#' + str(r['exec'].get('task_index') or 0) if r['exec'].get('delegation') else ''}"
              f"  {zh}：{r['evidence']}")
        if r["transcript"]:
            print(f"      {r['transcript']}")
    if hard:
        print(f"\n退出码 1：{hard} 个块的线程已经结束或记错了 —— 先对账（改状态 / 重派 / 修线程号），再往下走。")
    return 1 if hard else 0


def cmd_expand(a):
    """把一个块（B）展开成一个任务（T）：原块成为第一步，--step 依次追加后续步骤。

    前后关系一次改对：等这个块的块改等新链尾；这个块自己的前置原样成为第一步的前置。
    """
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— expand 作用于块（T-001#B-002 或 B-002）；"
            f"要把任务的块合并起来用 collapse")
    pre = {b["id"]: set(block_deps(plan, t, b)) for t, b in all_blocks(plan)}
    src, xid, xpos = task, block["id"], task["blocks"].index(block)
    tid = next_ids(plan, "T-", [t["id"] for t in plan["tasks"]])
    title = a.title or block["title"]
    owner = a.owner or block.get("owner") or src.get("owner", "")
    steps = [parse_step(s, block.get("kind") or "impl") for s in (a.step or [])]
    tail = f"{tid}#B-{len(steps) + 1:03d}"
    users = [b["id"] for _t, b in all_blocks(plan) if b["id"] != xid and xid in pre.get(b["id"], set())]

    if a.dry_run:
        print(f"[dry-run] 新任务 {tid}「{title}」（插在 {src['id']} 之后 · owner={owner or '-'}）")
        print(f"[dry-run]   {xid}「{block['title']}」→ {tid}#B-001（原地保留，只换 id）")
        for i, (t_, d_, c_, k_) in enumerate(steps, start=2):
            print(f"[dry-run]   第 {i} 步 {tid}#B-{i:03d}「{t_}」({k_}) · 判据 {len(c_)} 条")
        print(f"[dry-run] 改等新链尾 {tail} 的块：{users or '（无）'}")
        if block["status"] in ("done", "cancelled"):
            print(f"[dry-run] ⚠ 原块是 {block['status']}：新加步骤是 pending ⇒ 等于把这段活重新打开")
        if not src["blocks"]:
            print(f"[dry-run] {src['id']} 会是空的 → 删除，并把指向它的任务级依赖转给 {tid}")
        print("[dry-run] 没写任何文件")
        return

    new_task = {
        "id": tid, "title": title, "owner": owner, "status": "pending",
        "deps": [], "blocks": [], "note": a.note or "",
        "expanded_from": {"task": src["id"], "block": xid, "index": xpos},
    }
    src["blocks"] = [b for b in src["blocks"] if b["id"] != xid]
    block["id"] = f"{tid}#B-001"
    new_task["blocks"].append(block)
    chain = [block]
    for i, (t_, d_, c_, k_) in enumerate(steps, start=2):
        nb = {"id": f"{tid}#B-{i:03d}", "title": t_, "kind": k_, "status": "pending",
              "owner": owner, "doc": d_, "done_when": c_, "artifacts": [],
              "deps": [chain[-1]["id"]], "review_of": "", "feedback": "", "exec": {},
              "status_since": now(), "runs": []}
        new_task["blocks"].append(nb)
        chain.append(nb)
    plan["tasks"].insert(plan["tasks"].index(src) + 1, new_task)

    rewired = []
    for _t, b in all_blocks(plan):
        if b["id"].split("#")[0] == tid or xid not in pre.get(b["id"], set()):
            continue
        if b.get("review_of") == xid:
            b["review_of"] = tail
            moved_review = True
        else:
            moved_review = False
        if xid in deps_of(b):
            b["deps"] = [tail if d == xid else d for d in b["deps"]]
        elif not moved_review and tail not in deps_of(b):
            b.setdefault("deps", []).append(tail)
        rewired.append(b["id"])

    dropped = ""
    if not src["blocks"]:
        for t in plan["tasks"]:
            if t["id"] != tid and src["id"] in (t.get("deps") or []):
                t["deps"] = [tid if d == src["id"] else d for d in t["deps"]]
        plan["tasks"].remove(src)
        dropped = f"；原任务 {src['id']} 已空 → 删除，指向它的任务级依赖转给 {tid}"
    warn = ""
    if block["status"] in ("done", "cancelled"):
        warn = (f"⚠ 原块是「{STATUS_ZH.get(block['status'], block['status'])}」：新加的 {len(steps)} 步是 pending，"
                f"等它的块改等这些新步骤 —— 等于把这段活重新打开（下游会回到「等前置」）。"
                f"只想补记录就把新步骤也置 done。")
    guard_acyclic(plan, f"把 {xid} 展开成任务 {tid}")
    log_event(plan, "expand",
              f"展开块 {xid} → 任务 {tid}「{title}」"
              f"（{len(chain)} 步：{' → '.join(b['id'] for b in chain)}）"
              + (f"（原块 {block['status']}、新步骤 pending）" if warn else "")
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=tid)
    commit(a.slug, plan, a)
    print(f"✓ {xid} → {tid}「{title}」（{len(chain)} 步 · owner={owner or '-'}）")
    for b in chain:
        print(f"    {b['id']}  {b['title']}"
              + (f"  ⟵ 等 {b['deps']}" if b.get("deps") else ""))
    print(f"  改等链尾的块：{rewired or '（无）'}{dropped}")
    if warn:
        print(warn)


def cmd_collapse(a):
    """把一个任务（T）压成一个块（B）：各步合成一块，前后接线一次改对。

    块必须住在某个任务里，所以「压」要交代落点：--keep-task（留在本任务，只剩这一块）、
    --into <块/任务>（插到别处）、默认回展开前的位置，再不行落进它等着的那个任务。
    """
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is not None:
        die(f"{a.ref} 是块不是任务 —— collapse 作用于任务（T-001）")
    if a.into and a.keep_task:
        die("--into 与 --keep-task 只能给一个")
    live = [b for b in task["blocks"] if b["status"] != "cancelled"]
    if not live:
        die(f"任务 {task['id']} 没有在册的块（空的或全 cancelled），没什么可压")
    all_ids = {b["id"] for b in task["blocks"]}
    live_ids = {b["id"] for b in live}
    pre = {b["id"]: set(block_deps(plan, t, b)) for t, b in all_blocks(plan)}
    norm = ["pending" if block_effective(plan, b, task) in ("ready", "waiting")
            else block_effective(plan, b, task) for b in live]
    uniq = sorted(set(norm), key=lambda s: STEP_ORDER.index(s))
    if len(uniq) > 1 and not a.force:
        die("任务里各块状态不一致：" + "、".join(f"{b['id']}={e}" for b, e in zip(live, norm))
            + " —— 压成一块会丢掉这个区别，确认后加 --force（会取最靠前的那个状态）")
    status = uniq[0]

    # 落点
    home, insert_at, where = None, None, ""
    if a.keep_task:
        home, insert_at = task, min(i for i, b in enumerate(task["blocks"]) if b["id"] in live_ids)
        where = f"--keep-task（留在 {task['id']}）"
    elif a.into:
        ht, hb = find(plan, a.into)
        if ht["id"] == task["id"]:
            die(f"--into 指回同一个任务（{task['id']}）—— 要在原位合并就用 --keep-task")
        home = ht
        insert_at = ([b["id"] for b in ht["blocks"]].index(hb["id"]) + 1) if hb else len(ht["blocks"])
        where = f"--into {a.into}"
    else:
        ef = task.get("expanded_from") or {}
        ot, _ = find_soft(plan, ef.get("task") or "")
        if ot is not None:
            home, insert_at = ot, min(ef.get("index") or 0, len(ot["blocks"]))
            where = f"回展开前的位置（{ot['id']}）"
        else:
            preds = {}
            entries = [b for b in live if not (set(deps_of(b)) & live_ids)]   # 链的入口块
            for b in entries:
                for d in pre.get(b["id"], set()):
                    pt, _pb = find_soft(plan, d)
                    if pt is not None and pt["id"] != task["id"]:
                        preds[pt["id"]] = pt
            if len(preds) == 1:
                home = list(preds.values())[0]
                insert_at = len(home["blocks"])
                where = f"落到它等着的任务（{home['id']}）末尾"
            else:
                die("不知道把压出来的块放在哪：给 --into <块或任务>（明确插到某处）或 --keep-task"
                    "（留在本任务里只剩一块）。\n"
                    f"  它等的任务：{sorted(preds) or '（无）'}；"
                    f"依赖它的任务：{[t['id'] for t in plan['tasks'] if task['id'] in (t.get('deps') or [])]}")

    # 合并后这一块的内容：能逐字保留的都逐字保留
    doc = a.doc or (live[0].get("doc") or "" if len(live) == 1 else
                    "\n".join(f"{i}. {b['title']}：{b.get('doc') or '（无说明）'}"
                              for i, b in enumerate(live, 1)))
    if a.done_when:
        crit = list(a.done_when)
    else:
        crit, seen = [], set()
        for b in live:
            for c in (b.get("done_when") or []):
                if c not in seen:
                    seen.add(c)
                    crit.append(c)
    kinds = {b.get("kind") for b in live}
    kind = a.kind or (kinds.pop() if len(kinds) == 1 else "impl")
    ext = []
    for b in live:
        for d in deps_of(b):
            if d not in all_ids and d not in ext:
                _, db = find_soft(plan, d)
                if db is not None:
                    ext.append(d)
    if home is not task:      # 落在本任务里时，任务级依赖照样生效，不必再落成显式 deps
        for dep_tid in (task.get("deps") or []):
            for t2 in plan["tasks"]:
                if t2["id"] == dep_tid:
                    for b2 in t2["blocks"]:
                        if b2["status"] != "cancelled" and b2["id"] not in ext:
                            ext.append(b2["id"])
    rviews = {b["review_of"] for b in live if b.get("review_of") and b["review_of"] not in all_ids}
    arts = []
    for b in live:
        arts += [x for x in (b.get("artifacts") or []) if x not in arts]
    runs = sorted([dict(r, block=b["id"]) for b in live for r in (b.get("runs") or [])],
                  key=lambda r: r.get("at") or "")
    exe = {}
    for b in live:                                  # 压成一块后「谁在做」取最后一次登记的那个
        if (b.get("exec") or {}).get("by"):
            exe = dict(b["exec"])
    folded = [{"id": b["id"], "title": b["title"], "kind": b.get("kind"), "status": b["status"],
               "doc": b.get("doc") or "", "done_when": list(b.get("done_when") or [])}
              for b in task["blocks"]]
    mid = next_block_id(plan, home)
    merged = {"id": mid, "title": a.title or task["title"], "kind": kind, "status": status,
              "owner": a.owner or task.get("owner") or live[0].get("owner") or "",
              "doc": doc, "done_when": crit, "artifacts": arts, "deps": ext,
              "review_of": (rviews.pop() if len(rviews) == 1 else ""),
              "feedback": (live[0].get("feedback") or "") if len(live) == 1 else "",
              "status_since": now(), "runs": runs, "folded_from": folded, "exec": exe}

    if a.dry_run:
        print(f"[dry-run] {task['id']}「{task['title']}」（{len(live)} 块）→ 1 块 {mid}「{merged['title']}」")
        for b, e in zip(live, norm):
            print(f"[dry-run]   {b['id']} [{e}] {b['title']}")
        print(f"[dry-run] 状态 {status}（{'/'.join(uniq)}）· 判据 {len(crit)} 条 · "
              f"入口依赖 {ext or '（无）'} · kind {kind}")
        print(f"[dry-run] 落点：{where}"
              + ("（任务会删除）" if home is not task else "（任务保留）"))
        print(f"[dry-run] 改接线的块：{refs_to(plan, all_ids) or '（无）'}")
        print("[dry-run] 没写任何文件")
        return

    if home is task:
        task["blocks"] = [b for b in task["blocks"] if b["id"] not in all_ids]
        task["blocks"].insert(insert_at, merged)
        removed = False
    else:
        home["blocks"].insert(insert_at, merged)
        plan["tasks"].remove(task)
        removed = True

    rewired = []
    for t, b in all_blocks(plan):
        if b["id"] == mid or b["id"] in all_ids:
            continue
        changed = False
        if b.get("review_of") in all_ids:
            b["review_of"] = mid
            changed = True
        if set(deps_of(b)) & all_ids:
            keep = []
            for d in deps_of(b):
                nd = mid if d in all_ids else d
                if nd not in keep:
                    keep.append(nd)
            b["deps"] = keep
            changed = True
        if changed:
            rewired.append(b["id"])
    if removed:
        for t in plan["tasks"]:
            if task["id"] in (t.get("deps") or []):
                t["deps"] = [d for d in t["deps"] if d != task["id"]]
                for b in t["blocks"]:
                    if pre.get(b["id"], set()) & live_ids and mid not in deps_of(b):
                        b.setdefault("deps", []).append(mid)
                        if b["id"] not in rewired:
                            rewired.append(b["id"])
    cyc = cycle(block_graph(plan))
    if cyc:
        hint = ""
        if home is not task and (home.get("deps") or []):
            hint = (f"\n  提示：落点任务 {home['id']} 有任务级依赖 {home.get('deps')}，"
                    f"它里面的块会自动等那些任务的**所有**块 —— 换个 --into，或用 --keep-task")
        die(f"把任务 {task['id']} 压成块 {mid} 会让块依赖成环：{' → '.join(cyc)}"
            f"（没有写入任何东西）{hint}")
    log_event(plan, "collapse",
              f"压缩任务 {task['id']}「{task['title']}」（{len(live)} 块 → 1 块）为 {mid}「{merged['title']}」"
              + ("（任务已删除）" if removed else "（任务保留）")
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=mid)
    commit(a.slug, plan, a)
    print(f"✓ {task['id']}（{len(live)} 块）→ {mid}「{merged['title']}」 [{status}]"
          + ("" if removed else "（任务保留）"))
    for b, e in zip(live, norm):
        print(f"    {b['id']} [{e}] {b['title']}")
    print(f"  落点：{where} · 判据 {len(crit)} 条 · 入口依赖 {ext or '（无）'}")
    print(f"  改接线的块：{rewired or '（无）'}")


def cmd_note(a):
    plan = load(a.slug)
    log_event(plan, a.kind, a.text, actor=a.actor, ref=a.ref or "")
    commit(a.slug, plan, a)
    print("✓ 已记入日志")


def cmd_list(a):
    if not PLANS_ROOT.exists():
        print("（还没有 plan）")
        return
    rows = []
    for d in sorted(PLANS_ROOT.iterdir()):
        if (d / "plan.json").exists():
            p = json.loads((d / "plan.json").read_text(encoding="utf-8"))
            done, tot = progress(p)
            rows.append((p["slug"], p["title"], f"{done}/{tot}",
                         p.get("status", ""), p.get("updated_at", "")[:16]))
    w = max([len(r[0]) for r in rows] + [4])
    for r in rows:
        print(f"{r[0]:<{w}}  {r[2]:>6}  {r[3]:<9} {r[4]}  {r[1]}")


def cmd_current(a):
    plan = load(a.slug)
    rows = []
    for t, b in all_blocks(plan):
        e = block_effective(plan, b, t)
        if e in {"ready", "claimed", "running", "review", "blocked"}:
            rows.append((e, t["id"], b["id"], b["title"], b.get("owner", ""), b.get("exec") or {}))
    order = {"blocked": 0, "review": 1, "running": 2, "claimed": 3, "ready": 4}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[2]))
    for e, tid, bid, title, owner, ex in rows:
        print(f"[{e:<8}] {bid}  {title}  @{owner or '未指派'}"
              + exec_brief({"exec": ex}))


def cmd_check(a):
    plan = load(a.slug)
    errs, warns = [], []
    seen_ids = set()
    for t, b in all_blocks(plan):
        if b["id"] in seen_ids:
            errs.append(f"重复块 id {b['id']}")
        seen_ids.add(b["id"])
        for d in block_deps(plan, t, b):
            if find_soft(plan, d)[1] is None:
                errs.append(f"{b['id']} 依赖不存在的 {d}")
        if block_effective(plan, b, t) == "ready" and not b.get("owner"):
            warns.append(f"{b['id']} 已就绪但无人认领")
        if not b.get("done_when"):
            warns.append(f"{b['id']} 没有可核验的完成判据（done_when 为空）")
        if b["kind"] == "review" and not b.get("review_of"):
            warns.append(f"{b['id']} 是评审块但没写 review_of")
    for t in plan["tasks"]:
        for d in t.get("deps") or []:
            if d not in [x["id"] for x in plan["tasks"]]:
                errs.append(f"任务 {t['id']} 依赖不存在的 {d}")
    # 任务级环
    graph = {t["id"]: list(t.get("deps") or []) for t in plan["tasks"]}
    if cycle(graph):
        errs.append(f"任务依赖成环：{' → '.join(cycle(graph))}")
    for t, b, h in stale_blocks(plan, a.stale_hours):
        warns.append(f"{b['id']} 悬置 {h:.0f}h（{b['status']}，@{b.get('owner') or '未指派'}）")
    print(f"plan: {plan['title']}  ({plan['slug']})")
    print(f"错误 {len(errs)} · 告警 {len(warns)}")
    for e in errs:
        print("  ✗", e)
    for w in warns:
        print("  !", w)
    return 1 if errs else 0


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


# ---------------------------------------------------------------- render

STATUS_ZH = {
    "done": "已完成", "running": "进行中", "claimed": "已认领", "review": "待评审",
    "ready": "待认领", "waiting": "等前置", "pending": "待排", "blocked": "待批准",
    "cancelled": "已取消",
}


def mermaid(plan: dict) -> str:
    lines = ["```mermaid", "flowchart LR"]
    for t, b in all_blocks(plan):
        label = f"{b['id'].split('#')[1]} {b['title']}"
        label = label.replace('"', "'")
        lines.append(f'  {b["id"].replace("#", "_")}["{label}"]')
    idx = {}
    for t in plan["tasks"]:
        for b in t["blocks"]:
            idx[b["id"]] = b
    for t, b in all_blocks(plan):
        for d in edge_deps(plan, t, b):
            if d in idx:
                lines.append(f'  {d.replace("#", "_")} --> {b["id"].replace("#", "_")}')
    cls = {}
    for t, b in all_blocks(plan):
        cls.setdefault(block_effective(plan, b, t), []).append(b["id"].replace("#", "_"))
    for st, ids in cls.items():
        lines.append(f"  classDef {st} stroke-width:1px;")
        lines.append(f"  class {','.join(ids)} {st};")
    lines.append("```")
    return "\n".join(lines)


def render_md(plan: dict) -> str:
    done, tot = progress(plan)
    pct = int(round(100 * done / tot)) if tot else 0
    out = [f"# {plan['title']}", "",
           f"> {plan['goal']}", "",
           f"**进度** {done}/{tot} 块（{pct}%） · 状态 `{plan['status']}` · "
           f"更新于 {plan['updated_at'][:16].replace('T', ' ')}", ""]
    if plan.get("participants"):
        out += ["**参与方** " + " · ".join(
            f"{p['label']}({p['kind']})" for p in plan["participants"]), ""]
    out += ["## 现在该谁动（NOW / NEXT）", ""]
    rows = []
    for t, b in all_blocks(plan):
        e = block_effective(plan, b, t)
        if e in {"ready", "claimed", "running", "review", "blocked"}:
            rows.append((e, b, t))
    order = {"blocked": 0, "review": 1, "running": 2, "claimed": 3, "ready": 4}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[1]["id"]))
    if not rows:
        out.append("- （没有在途工作）")
    for e, b, t in rows:
        out.append(f"- `{b['id']}` **{b['title']}** — {STATUS_ZH.get(e, e)} · "
                   f"@{b.get('owner') or '未指派'}" + exec_brief(b)
                   + (f" · ⚠ {b['feedback']}" if b.get("feedback") else ""))
    out += ["", "## 图", "", mermaid(plan), "", "## 任务", ""]
    for t in plan["tasks"]:
        out.append(f"### {t['id']} {t['title']} — {STATUS_ZH.get(task_status(plan, t), '')}")
        meta = []
        if t.get("owner"):
            meta.append(f"@{t['owner']}")
        if t.get("deps"):
            meta.append("前置 " + ", ".join(t["deps"]))
        if meta:
            out.append(" · ".join(meta))
        for b in t["blocks"]:
            e = block_effective(plan, b, t)
            out.append(f"- [{'x' if b['status'] == 'done' else ' '}] `{b['id']}` "
                       f"**{b['title']}** _{b['kind']}_ — {STATUS_ZH.get(e, e)}"
                       f"{(' @' + b['owner']) if b.get('owner') else ''}")
            if b.get("doc"):
                out.append(f"    - 做什么：{b['doc']}")
            for c in b.get("done_when") or []:
                out.append(f"    - 判据：{c}")
            for d in block_deps(plan, t, b):
                out.append(f"    - 依赖：{d}" + ("" if d in deps_of(b) else "（任务级）"))
            for art in b.get("artifacts") or []:
                out.append(f"    - 产物：`{art}`")
            cby, cat = claim_of(b)
            if cby:
                out.append(f"    - 认领：@{cby}（{cat[:16].replace('T', ' ')}）")
            ex = b.get("exec") or {}
            if ex.get("by"):
                line = f"    - 在做：@{ex['by']}"
                if ex.get("delegation"):
                    line += f" · 线程 {ex['delegation']}#{ex.get('task_index') or 0}"
                if ex.get("transcript"):
                    line += f" · `{ex['transcript']}`"
                out.append(line)
            if b.get("feedback"):
                out.append(f"    - 评审意见：{b['feedback']}")
            for r in (b.get("runs") or [])[-3:]:
                out.append(f"    - run {r['at'][:16].replace('T', ' ')} {r.get('by','')} "
                           f"{r.get('from','')}→{r.get('to','')} {r.get('note','')}")
        out.append("")
    if plan.get("log"):
        out += ["## 日志（近 20 条）", ""]
        for e in plan["log"][-20:]:
            out.append(f"- `{e['at'][:16].replace('T', ' ')}` **{e['actor']}** "
                       f"[{e['kind']}] {e['text']}")
        out.append("")
    out += ["---", f"plan.json 是唯一真相；本文件与 plan.html / plan.canvas 由 "
                   f"`plan.py render {plan['slug']}` 生成。", ""]
    return "\n".join(out)


def depth_map(plan: dict) -> dict:
    blocks = {b["id"]: b for _, b in all_blocks(plan)}
    owner = {}
    for t, b in all_blocks(plan):
        owner[b["id"]] = t
    depth = {}

    def d(bid, seen=None):
        seen = seen or set()
        if bid in depth:
            return depth[bid]
        if bid in seen or bid not in blocks:
            return 0
        seen.add(bid)
        dd = 0
        for dep in edge_deps(plan, owner[bid], blocks[bid]):
            if dep in blocks:
                dd = max(dd, d(dep, seen) + 1)
        seen.discard(bid)
        depth[bid] = dd
        return dd

    for bid in blocks:
        d(bid)
    return depth


def render_canvas(plan: dict) -> str:
    depth = depth_map(plan)
    nodes, edges = [], []
    col, y = {}, 24
    per_col = {}
    for t in plan["tasks"]:
        for b in t["blocks"]:
            dd = depth.get(b["id"], 0)
            i = per_col.get(dd, 0)
            per_col[dd] = i + 1
            x = 40 + dd * 340
            yy = 40 + i * 130
            col[b["id"]] = (x, yy)
            nodes.append({
                "id": b["id"], "type": "text", "x": x, "y": yy, "width": 300, "height": 110,
                "color": {"done": "4", "running": "5", "review": "6", "ready": "3",
                          "blocked": "1", "waiting": "0"}.get(block_effective(plan, b, t), "0"),
                "text": f"### {b['id']}\n{b['title']}\n\n`{block_effective(plan, b, t)}` · "
                        f"@{b.get('owner') or '-'}" + exec_brief(b) + "\n\n"
                        + (b.get('doc') or '')[:160]})
    for t, b in all_blocks(plan):
        for dep in edge_deps(plan, t, b):
            if dep in col:
                edges.append({"id": f"e{len(edges)}", "fromNode": dep, "toNode": b["id"],
                              "fromSide": "right", "toSide": "left",
                              "label": "", "color": "6"})
    return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=1)


def render_html(plan: dict) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(plan, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("/*__PLAN_DATA__*/null", data)


def render_all(slug: str, plan: dict | None = None):
    plan = plan or load(slug)
    d = plan_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write(d / "PLAN.md", render_md(plan))
    atomic_write(d / "plan.canvas", render_canvas(plan))
    atomic_write(d / "plan.html", render_html(plan))
    return d


def cmd_render(a):
    plan = load(a.slug)
    d = render_all(a.slug, plan)
    print(f"✓ {d}/PLAN.md")
    print(f"✓ {d}/plan.html")
    print(f"✓ {d}/plan.canvas")


def cmd_digest(a):
    plan = load(a.slug)
    done, tot = progress(plan)
    pct = int(round(100 * done / tot)) if tot else 0
    d = plan_dir(a.slug)
    stale = {b["id"]: h for _, b, h in stale_blocks(plan, a.stale_hours)}
    mine = []
    for t, b in all_blocks(plan):
        if a.to in (b.get("owner"), "") and block_effective(plan, b, t) in \
                {"ready", "claimed", "running", "review", "blocked"}:
            mine.append((t, b))
    mine.sort(key=lambda tb: tb[1]["id"])
    lines = [f"📋 **{plan['title']}** · {done}/{tot} 块（{pct}%）· 更新 {plan['updated_at'][:16].replace('T',' ')}",
             f"plan: `{d}/PLAN.md` — 开工前先读它，状态只通过 `plan.py` 改。"]
    if a.to:
        who = "你" if a.to == "you" else a.to
        if mine:
            lines.append(f"🔔 **@{who} 现在该动**：")
            for t, b in mine[:3]:
                e = block_effective(plan, b, t)
                lines.append(f"  · `{b['id']}` {b['title']}（{e}）" + exec_brief(b)
                             + (f" · ⚠{b['feedback']}" if b.get("feedback") else ""))
        else:
            lines.append(f"🔔 @{who} 名下暂时没有可动的块。")
    else:
        rows = []
        for t, b in all_blocks(plan):
            e = block_effective(plan, b, t)
            if e in {"ready", "claimed", "running", "review", "blocked"}:
                rows.append((e, b))
        order = {"blocked": 0, "review": 1, "running": 2, "claimed": 3, "ready": 4}
        rows.sort(key=lambda r: (order.get(r[0], 9), r[1]["id"]))
        if rows:
            lines.append("▶ **在途**：")
            for e, b in rows[:8]:
                tag = "⚠ 待批准" if e == "blocked" else STATUS_ZH.get(e, e)
                lines.append(f"  · `{b['id']}` {b['title']} — {tag} @{b.get('owner') or '未指派'}"
                             + exec_brief(b) + (f" · ⚠{b['feedback']}" if b.get("feedback") else ""))
        else:
            lines.append("▶ 没有在途工作。")
    blocked = [b for _, b in all_blocks(plan) if block_effective(plan, b, owner_of(plan, b)) == "blocked"]
    for b in blocked:
        lines.append(f"⚠ `{b['id']}` {b['title']}：{b.get('feedback') or '待批准，需决定'}")
    for bid, h in list(stale.items())[:5]:
        lines.append(f"⏳ `{bid}` 悬置 {h:.0f}h 无更新")
    if a.format == "md":
        lines += ["", f"图形视图：`{d}/plan.html`（浏览器打开）/ `{d}/plan.canvas`（Obsidian）"]
    print("\n".join(lines))


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(prog="plan.py", description="plan-weave 的 plan 工具")
    ap.add_argument("--no-render", action="store_true",
                    help="只改数据，不刷新 PLAN.md/plan.html/plan.canvas")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="新建 plan")
    p.add_argument("slug")
    p.add_argument("--title")
    p.add_argument("--goal")
    p.add_argument("--owner", action="append", help="id=kind:label[:channel]，可多次")
    p.add_argument("--digest-hours", type=float, default=6)
    p.add_argument("--quiet-hours", default="23:00-08:00")
    p.add_argument("--force", action="store_true")
    p.set_defaults(f=cmd_new)

    p = sub.add_parser("task", help="加任务（节点）")
    p.add_argument("slug")
    p.add_argument("--title", required=True)
    p.add_argument("--id")
    p.add_argument("--owner", default="")
    p.add_argument("--deps", nargs="*", default=[])
    p.add_argument("--note", default="")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_task)

    p = sub.add_parser("block", help="给任务加块（文档）")
    p.add_argument("slug")
    p.add_argument("--task", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--kind", default="impl", choices=KINDS)
    p.add_argument("--doc", default="")
    p.add_argument("--done-when", action="append", default=[])
    p.add_argument("--deps", nargs="*", default=[])
    p.add_argument("--owner", default="")
    p.add_argument("--review-of", default="")
    p.add_argument("--status", default="pending", choices=BLOCK_STATUS,
                   help="建块时的初始状态；要「等人点头」的块用 blocked（显示为待批准）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block)

    p = sub.add_parser("set", help="改状态")
    p.add_argument("slug")
    p.add_argument("ref")
    p.add_argument("status")
    p.add_argument("--note", default="")
    p.add_argument("--owner", default="")
    p.add_argument("--by", default="")
    p.add_argument("--at", default="", help="补记时间（ISO8601），默认现在")
    p.add_argument("--artifact", action="append", default=[])
    p.add_argument("--doc", default="", help="改块文档（做什么）——事实变了就改原文，别只写在日志里")
    p.add_argument("--done-when", dest="done_when", action="append", default=[],
                   help="改判据，可多次")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_set)

    p = sub.add_parser("exec", aliases=["doing"],
                       help="登记谁在做 + 那条子代理线程（认领之外的第二个身份）")
    p.add_argument("slug")
    p.add_argument("ref", help="块或任务：T-002#B-001 / B-001 / T-002")
    p.add_argument("--by", default="", help="谁在做（参与方 id：agent 名或人）")
    p.add_argument("--delegation", default="", help="子代理线程号 deleg_xxxxxxxx")
    p.add_argument("--task-index", dest="task_index", type=int, default=None,
                   help="这条线程下第几个 task（默认 0）")
    p.add_argument("--profile", default="",
                   help="这条线程属于哪个 profile（默认 default）—— 用来算转录路径")
    p.add_argument("--transcript", default="",
                   help="转录文件绝对路径；不给就按 --profile + 线程号算")
    p.add_argument("--note", default="", help="在做的是哪一段（会记进日志）")
    p.add_argument("--at", default="", help="补记时间（ISO8601），默认现在")
    p.add_argument("--unset", action="store_true", help="清掉线程登记（线程结束 / 交回别人）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_exec)

    p = sub.add_parser("rm", help="真删一个块或任务（取消 ≠ 删除；被引用时默认拒删）")
    p.add_argument("slug")
    p.add_argument("ref")
    p.add_argument("--note", default="", help="为什么删（会记进日志）")
    p.add_argument("--force", action="store_true", help="已被别的块引用时仍然删")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_rm)

    p = sub.add_parser("expand", help="把一个块展开成一个任务（块成为第一步，--step 追加后续步骤）")
    p.add_argument("slug")
    p.add_argument("ref", help="要展开的块：T-001#B-002 或 B-002")
    p.add_argument("--title", default="", help="新任务的标题（默认沿用块标题）")
    p.add_argument("--step", action="append", default=[],
                   help="追加的后续步骤，可多次、按顺序：标题 :: 做什么 :: 判据1;判据2 :: kind")
    p.add_argument("--owner", default="")
    p.add_argument("--note", default="", help="为什么展开（会记进日志）")
    p.add_argument("--dry-run", action="store_true", help="只打印会改什么，不落盘")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_expand)

    p = sub.add_parser("collapse", aliases=["compress"],
                       help="把一个任务压成一个块（默认回展开前的位置）")
    p.add_argument("slug")
    p.add_argument("ref", help="要压缩的任务：T-001")
    p.add_argument("--into", default="",
                   help="压出来的块放哪：块 ref（插到它之后）或任务 ref（追加到末尾）")
    p.add_argument("--keep-task", dest="keep_task", action="store_true",
                   help="保留本任务，只把各块并成一块（不删任务）")
    p.add_argument("--title", default="")
    p.add_argument("--doc", default="", help="合并块的「做什么」；不给就拼各步的")
    p.add_argument("--done-when", dest="done_when", action="append", default=[],
                   help="合并块的判据；不给就取各步判据的并集（逐字保留）")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--owner", default="")
    p.add_argument("--note", default="", help="为什么压缩（会记进日志）")
    p.add_argument("--force", action="store_true", help="各块状态不一致时仍然压")
    p.add_argument("--dry-run", action="store_true", help="只打印会改什么，不落盘")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_collapse)

    p = sub.add_parser("note", help="写一条总结/决定进日志")
    p.add_argument("slug")
    p.add_argument("text")
    p.add_argument("--kind", default="summary",
                   choices=["summary", "decision", "reminder", "created", "task",
                            "block", "status", "expand", "collapse"])
    p.add_argument("--ref", default="")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_note)

    p = sub.add_parser("digest", help="生成提醒/摘要文本")
    p.add_argument("slug")
    p.add_argument("--to", default="", help="只提醒某个参与方（id，或 you）")
    p.add_argument("--format", default="discord", choices=["discord", "md"])
    p.add_argument("--stale-hours", type=float, default=24)
    p.set_defaults(f=cmd_digest)

    p = sub.add_parser("render", help="重新生成 PLAN.md / plan.html / plan.canvas")
    p.add_argument("slug")
    p.set_defaults(f=cmd_render)

    p = sub.add_parser("check", help="图质量检查")
    p.add_argument("slug")
    p.add_argument("--stale-hours", type=float, default=24)
    p.set_defaults(f=cmd_check)

    p = sub.add_parser("current", help="现在可动的块")
    p.add_argument("slug")
    p.set_defaults(f=cmd_current)

    p = sub.add_parser("workers", aliases=["threads"],
                       help="检查每个在途块登记的子代理线程是否还在动（已结束/记错 ⇒ exit 1）")
    p.add_argument("slug")
    p.add_argument("--stale-min", dest="stale_min", type=float, default=30,
                   help="转录多久没写一行就算静默（默认 30 分钟）")
    p.add_argument("--json", action="store_true", help="机器可读输出（给 agent 用）")
    p.set_defaults(f=cmd_workers)

    p = sub.add_parser("list", help="列出所有 plan")
    p.set_defaults(f=cmd_list)

    a = ap.parse_args(argv)
    if a.cmd == "list":
        return cmd_list(a)
    r = a.f(a)
    return r if isinstance(r, int) else 0


if __name__ == "__main__":
    sys.exit(main())
