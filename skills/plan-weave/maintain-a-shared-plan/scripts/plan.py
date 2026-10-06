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

时间戳一律本地时区 ISO8601。全部 stdlib，无第三方依赖。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

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


def save(slug: str, plan: dict) -> None:
    plan["updated_at"] = now()
    d = plan_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def commit(slug: str, plan: dict, a=None) -> None:
    """落盘 + 同步刷新三个视图，保证 html/canvas/md 永不落后于 plan.json。"""
    save(slug, plan)
    if a is not None and getattr(a, "no_render", False):
        return
    render_all(slug, plan)


def die(msg: str, code: int = 2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def all_blocks(plan: dict):
    for t in plan["tasks"]:
        for b in t["blocks"]:
            yield t, b


def find(plan: dict, ref: str):
    """ref = T-001 或 T-001#B-001（也接受 B-003 这种块内唯一后缀）"""
    if "#" in ref:
        tid, bid = ref.split("#", 1)
        for t, b in all_blocks(plan):
            if t["id"] == tid and b["id"].split("#")[1] == bid:
                return t, b
        die(f"找不到块 {ref}")
    for t in plan["tasks"]:
        if t["id"] == ref:
            return t, None
    for t, b in all_blocks(plan):
        if b["id"].split("#")[1] == ref:
            return t, b
    die(f"找不到 {ref}")


def blocks_of(plan: dict, tid: str):
    for t in plan["tasks"]:
        if t["id"] == tid:
            return t["blocks"]
    return []


def find_soft(plan: dict, ref: str):
    """find() 但不退出进程（外部引用可能还没建）。"""
    try:
        return find(plan, ref)
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
        "deps": a.deps or [], "blocks": [], "note": a.note or "",
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
        "review_of": a.review_of or "", "feedback": "",
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
    log_event(plan, "status", f"{target['id']}: {old} → {a.status}"
              + ("（doc 已更新）" if (block and a.doc) else "")
              + ("（done_when 已更新）" if (block and a.done_when) else "")
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=target["id"])
    commit(a.slug, plan, a)
    print(f"✓ {target['id']} {old} → {a.status}")


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
            rows.append((e, t["id"], b["id"], b["title"], b.get("owner", "")))
    order = {"blocked": 0, "review": 1, "running": 2, "claimed": 3, "ready": 4}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[2]))
    for e, tid, bid, title, owner in rows:
        print(f"[{e:<8}] {bid}  {title}  @{owner or '未指派'}")


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
                   f"@{b.get('owner') or '未指派'}"
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
                        f"@{b.get('owner') or '-'}\n\n{(b.get('doc') or '')[:160]}"})
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
    (d / "PLAN.md").write_text(render_md(plan), encoding="utf-8")
    (d / "plan.canvas").write_text(render_canvas(plan), encoding="utf-8")
    (d / "plan.html").write_text(render_html(plan), encoding="utf-8")
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
                lines.append(f"  · `{b['id']}` {b['title']}（{e}）"
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
                             + (f" · ⚠{b['feedback']}" if b.get("feedback") else ""))
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

    p = sub.add_parser("note", help="写一条总结/决定进日志")
    p.add_argument("slug")
    p.add_argument("text")
    p.add_argument("--kind", default="summary",
                   choices=["summary", "decision", "reminder", "created", "task",
                            "block", "status"])
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

    p = sub.add_parser("list", help="列出所有 plan")
    p.set_defaults(f=cmd_list)

    a = ap.parse_args(argv)
    if a.cmd == "list":
        return cmd_list(a)
    r = a.f(a)
    return r if isinstance(r, int) else 0


if __name__ == "__main__":
    sys.exit(main())
