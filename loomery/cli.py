"""CLI 层：argparse + 15 个子命令 + 人读输出 —— 唯一允许 print 与决定退出码的地方。

别的 harness 想用这套能力，要么调这个模块的 `main()`，要么直接 import 模型 / 存储层。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import NoReturn

from .model import *          # noqa: F401,F403  （机械搬迁：命令层用到的模型符号原样保留）
from .store import *          # noqa: F401,F403
from .render import *         # noqa: F401,F403
from .workers import *        # noqa: F401,F403


def die(msg: str, code: int = 2, quiet: bool = False) -> NoReturn:
    """参数级的硬错误（与模型层的 PlanError 同语义，只是这一层直接说给人听）。"""
    if not quiet:
        print(msg, file=sys.stderr)
    sys.exit(code)

# ------------------------------------------------ 建立
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
        "status": getattr(a, "status", None) or "blocked",
        "owner": a.owner or task.get("owner", ""), "doc": a.doc or "",
        "done_when": a.done_when or [], "artifacts": [], "deps": a.deps or [],
        "review_of": a.review_of or "", "feedback": "", "exec": {},
        "status_since": now(), "runs": [],
    }
    task["blocks"].append(block)
    log_event(plan, "block", f"新增块 {bid}「{a.title}」", actor=a.actor, ref=bid)
    commit(a.slug, plan, a)
    print(f"✓ {bid} {a.title} ({a.kind})")


# ------------------------------------------------ 状态与身份
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


# ------------------------------------------------ 结构
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


# ------------------------------------------------ 看与出
def cmd_note(a):
    plan = load(a.slug)
    log_event(plan, a.kind, a.text, actor=a.actor, ref=a.ref or "")
    commit(a.slug, plan, a)
    print("✓ 已记入日志")

def cmd_list(a):
    if not plans_root().exists():
        print("（还没有 plan）")
        return
    rows = []
    for d in sorted(plans_root().iterdir()):
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
             f"plan: `{d}/PLAN.md` — 开工前先读它，状态只通过 `loomery`（或 skill 里的 `plan.py`）改。"]
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


# ------------------------------------------------ argparse 与入口
def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="loomery", description="loomery —— 一份 plan 的工具（谁认领/谁在做/下一步该谁动）")
    ap.add_argument("--no-render", action="store_true",
                    help="只改数据，不刷新 PLAN.md/plan.html/plan.canvas")
    ap.add_argument("--plans-root", dest="plans_root", default="",
                    help="plan 目录（等价于 $LOOMERY_PLANS_ROOT）—— 跨机器/多份 plan 库时显式指定")
    ap.add_argument("--profile", default="",
                    help="用某个 Hermes profile 的 plans（等价于 $LOOMERY_PROFILE），例：--profile plan-weave")
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
    p.add_argument("--status", default="blocked", choices=BLOCK_STATUS,
                   help="建块时的初始状态。默认 blocked（=待批准：等有人点头）；"
                        "AI 判断这块无需审批就能干，就显式给 --status pending")
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

    return ap


def main(argv=None):
    """任何 harness 的入口：返回退出码（0/1/2），自己不 sys.exit。"""
    a = _parser().parse_args(argv)
    # 显式旗标优先：--plans-root 直接定死；--profile 则要让 profile 那条生效（清掉可能已设的 plans root）
    if getattr(a, "plans_root", ""):
        os.environ["LOOMERY_PLANS_ROOT"] = a.plans_root
    elif getattr(a, "profile", ""):
        os.environ.pop("LOOMERY_PLANS_ROOT", None)
        os.environ["LOOMERY_PROFILE"] = a.profile
    try:
        if a.cmd == "list":
            return cmd_list(a) or 0
        r = a.f(a)
        return r if isinstance(r, int) else 0
    except PlanError as e:          # 模型层/存储层的硬错误：说给人听 + 用建议的退出码
        print(str(e), file=sys.stderr)
        return e.code
