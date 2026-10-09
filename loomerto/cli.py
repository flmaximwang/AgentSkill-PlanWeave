"""CLI 层：argparse + 24 个叶子命令 —— 一级是**对象/全局动作**（`plan` / `task` / `block` 是分组，
`note` / `digest` / `render` / `check` / `current` / `workers` / `list` / `open` 是单层），
动作一律放到二级（`block set_status` / `task rm`…）。唯一允许 print 与决定退出码的地方。

别的 harness 想用这套能力，要么调这个模块的 `main()`，要么直接 import 模型 / 存储层。
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from typing import NoReturn

from .model import *          # noqa: F401,F403  （机械搬迁：命令层用到的模型符号原样保留）
from .store import *          # noqa: F401,F403
from .render import *         # noqa: F401,F403
from .workers import *        # noqa: F401,F403

from . import store as _store          # 要改 PLAN_FILE（包级状态），不能只拿值
from . import edits                    # 改动的唯一实现：命令层与画布服务共用


def die(msg: str, code: int = 2, quiet: bool = False) -> NoReturn:
    """参数级的硬错误（与模型层的 PlanError 同语义，只是这一层直接说给人听）。"""
    if not quiet:
        print(msg, file=sys.stderr)
    sys.exit(code)

# ------------------------------------------------ 建立
def cmd_new(a):
    p = plan_path(a.slug)
    if p.exists() and not a.force:
        die(f"{p} 已存在（要覆盖加 --force）")
    p.parent.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": "plan-weave/plan@1",
        "slug": a.slug or p.parent.name,
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
    print(f"✓ 建立 {p}")

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
    t = edits.add_task(plan, a.title, id=a.id or "", owner=a.owner or "",
                       deps=a.deps or [], note=a.note or "", actor=a.actor)
    commit(a.slug, plan, a)
    print(f"✓ {t['id']} {t['title']}")

def cmd_block_add(a):
    plan = load(a.slug)
    _t, block = edits.add_block(plan, a.task, title=a.title, kind=a.kind, doc=a.doc or "",
                                done_when=a.done_when or [], deps=a.deps or [],
                                owner=a.owner or "", review_of=a.review_of or "",
                                status=getattr(a, "status", None) or "blocked",
                                actor=a.actor)
    commit(a.slug, plan, a)
    print(f"✓ {block['id']} {block['title']} ({block['kind']})")


def cmd_block_insert(a):
    """把一个新块插到某个块之前/之后（位置级插入，前后接线一次改对）。"""
    plan = load(a.slug)
    if a.before and a.after:
        die("--before 与 --after 只能给一个（一个都不给就是 --before）")
    if a.dry_run:                       # 预演：改一份内存副本，绝不落盘
        plan = copy.deepcopy(plan)
    task, block, rewired, where = edits.insert_block(
        plan, a.ref, before=not a.after, title=a.title, kind=a.kind, doc=a.doc or "",
        done_when=a.done_when or [], owner=a.owner or "", review_of=a.review_of or "",
        status=a.status, note=a.note or "", actor=a.actor)
    head = "[dry-run] " if a.dry_run else "✓ "
    print(f"{head}{block['id']}「{block['title']}」({block['kind']}, {block['status']}) · {where}")
    print(f"{head}  等  {'、'.join(deps_of(block)) or '—'}")
    print(f"{head}改接线的块：{rewired or '（无）'}")
    if a.dry_run:
        print("[dry-run] 没写任何文件")
        return 0
    commit(a.slug, plan, a)
    return 0


# ------------------------------------------------ 状态与身份
def _thread_brief(target) -> str:
    """「在做 @谁 · 线程 x#0」那一行尾巴，外加转录看不到时的提醒（没人登记就空串）。"""
    ex = target.get("exec") or {}
    if not ex.get("by"):
        return ""
    out = f" · 在做 @{ex['by']}"
    if not ex.get("delegation"):
        return out
    out += f" · 线程 {ex['delegation']}#{ex.get('task_index') or 0}"
    if not ex.get("transcript"):
        out += "（⚠ 没给 --transcript：`workers` 只能报「❓ 看不到」）"
    elif not Path(ex["transcript"]).exists():
        out += f"（⚠ 转录现在不在这台机器上：{ex['transcript']}）"
    return out


def _apply_set(a, plan, ref: str, *, is_block: bool):
    """`block set_status` / `task set` 的公共实现：状态 + 身份（谁在做 / 子代理线程）一个入口。

    <状态> 可以省 —— 只给 `--unset` 时用来清线程登记；其余参数按状态卡
    （`edits.check_set_flags`：在途状态才收线程登记，产物只在 done 收）。
    """
    what = "块" if is_block else "任务"
    if a.unset:
        if a.status:
            die("--unset 只清线程登记，不与 <状态> 同时用 —— 要改状态就直接 set"
                "（done / cancelled / pending 本来就会清掉登记）")
        _t, old = edits.clear_exec(plan, ref, note=a.note, actor=a.actor)
        commit(a.slug, plan, a)
        print(f"✓ {ref} 已清线程登记"
              + (f"（原在做 {old.get('by')}）" if old.get("by") else "（本来就没有）"))
        return 0
    if not a.status:
        die(f"{what} {ref} 要改状态就写 <状态>；只清线程登记写 --unset。"
            f"可用状态 {'/'.join(BLOCK_STATUS if is_block else edits.TASK_STATUS)}")
    given = set()
    for flag, val in (("--by", a.by), ("--delegation", a.delegation), ("--transcript", a.transcript)):
        if val:
            given.add(flag)
    if a.task_index is not None:
        given.add("--task-index")
    if getattr(a, "artifact", None):
        given.add("--artifact")
    edits.check_set_flags(a.status, given, is_block=is_block)   # 先按状态卡参数（比「缺 --by」更根本）
    if a.delegation and not a.by:
        die("登记线程要连带说清谁在做：加 --by <参与方 id>")
    if a.task_index is not None and not a.delegation:
        die("--task-index 只在给了 --delegation 时有意义（一个 delegation 下有多个 task-N）")
    target, old = edits.set_status(
        plan, ref, a.status, by=a.by, owner=a.owner, note=a.note, at=a.at,
        doc=getattr(a, "doc", "") or "", done_when=getattr(a, "done_when", None),
        artifacts=getattr(a, "artifact", None) or [], delegation=a.delegation,
        task_index=a.task_index, transcript=a.transcript, actor=a.actor)
    commit(a.slug, plan, a)
    print(f"✓ {target['id']} {old} → {a.status}{_thread_brief(target)}")
    return 0


def cmd_block_set_status(a):
    plan = load(a.slug)
    _task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— 任务状态用 `task set {a.ref} <状态>`"
            f"（{'/'.join(edits.TASK_STATUS)}）；块状态用 `block set_status <块 ref> <状态>`")
    return _apply_set(a, plan, a.ref, is_block=True)


def cmd_task_set(a):
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is not None:
        die(f"{a.ref} 是块不是任务 —— 块状态用 `block set_status {a.ref} <状态>`"
            f"（{'/'.join(BLOCK_STATUS)}）；任务状态用 `task set <任务 ref> <状态>`")
    return _apply_set(a, plan, a.ref, is_block=False)


def cmd_block_set_attr(a):
    """`set_title` / `set_doc` / `set_type` / `set_input` / `set_output` / `set_command` /
    `set_audit` 共用的实现：改块的**一个**属性（值可以留空 = 清空；`set_audit` 的值里用
    `;` 分隔多条判据）—— 不动状态，改动记进日志。

    分工：状态 + 身份（谁在做 / 线程）走 `block set_status`，认领人走 `block assign`，
    其余属性一条命令一个（`a.attr` 是块的键，见 `edits.set_field`）。没变化 ⇒ `PlanError`（退 2）。
    """
    plan = load(a.slug)
    block, old, new = edits.set_field(plan, a.ref, a.attr, a.value or "",
                                      note=a.note or "", actor=a.actor)
    commit(a.slug, plan, a)
    if a.attr == "done_when":
        print(f"✓ {block['id']} 判据 {len(new)} 条" + (f"（原 {len(old or [])} 条）" if old else ""))
        for c in new:
            print(f"    · {c}")
        return 0
    zh = edits.FIELD_ZH.get(a.attr, a.attr)
    shown = new if isinstance(new, str) else "、".join(new)
    print(f"✓ {block['id']} 的{zh}：" + (f"{old} → " if old else "") + (shown or "（清空）"))
    if not shown:
        print(f"    这块现在没有「{zh}」了 —— `check` / 看板会照空着显示")
    return 0


def cmd_block_assign(a):
    """把一个块指派给某个参与方 —— 不动状态，改动记进日志。"""
    plan = load(a.slug)
    _task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— assign 只对块有用（任务级的认领在 `task new --owner`）")
    if a.to and a.unset:
        die("--to 与 --unset 只能给一个")
    if not a.to and not a.unset:
        die("要说清给谁：--to <参与方 id>（清掉指派用 --unset）")
    block, old = edits.assign_block(plan, a.ref, "" if a.unset else a.to,
                                    note=a.note, actor=a.actor)
    commit(a.slug, plan, a)
    if a.unset:
        print(f"✓ {block['id']} 清掉指派" + (f"（原 {old}）" if old else "（本来就没指派）"))
        return 0
    print(f"✓ {block['id']} 指派给 {a.to}" + (f"（原 {old}）" if old else ""))
    known = [p.get("id") for p in (plan.get("participants") or [])]
    if known and a.to not in known:
        print(f"⚠ {a.to} 不在参与方名单里（{'、'.join(known)}）—— 记上了，但这个 id 谁也不是")
    ex = block.get("exec") or {}
    if ex.get("by") and ex["by"] != block.get("owner"):
        print(f"⚠ 这一块登记的「在做」是 {ex['by']}，与认领人 {block.get('owner') or '未指派'} 不一致"
              f"（换在做的人走 `set … <在途状态> --by`）")
    return 0


def cmd_block_deps(a):
    """改一个块的**前置依赖**：`--deps` 整组替换 / `--add` 加 / `--rm` 去掉（空的前置 = 谁都不等）。

    依赖是接线不是字段，所以三道闸（存在性 · 自指 · 环）都在 `edits.set_deps` 一处；成环时
    它抛错 ⇒ 这里拿不到返回值 ⇒ 不 `commit()`，一个字都不写。
    """
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— 块的前置用 `block deps <块 ref> --add/--rm`；"
            f"任务级依赖只能建任务时给（`task new --deps`）")
    block, old, new = edits.set_deps(plan, a.ref, deps=a.deps, add=a.add, rm=a.rm,
                                     note=a.note or "", actor=a.actor)
    commit(a.slug, plan, a)
    print(f"✓ {block['id']} 的前置：{'、'.join(old) or '（无）'} → {'、'.join(new) or '（无）'}")
    for d in new:
        if d in old:
            continue
        _t, db = find_soft(plan, d)
        if db is not None and db["status"] == "cancelled":
            print(f"⚠ 新等上的 {d} 是 cancelled —— 它不会变 done，这块会一直「等前置」")
    if task.get("deps"):
        print(f"⚠ 它所属任务 {task['id']} 的任务级依赖（{'、'.join(task['deps'])}）也算它的前置"
              f"（`block show {block['id']}` 里那几条标着「任务级」）")
    return 0


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

def cmd_block_remove(a):
    """真删一个块（取消 ≠ 删除；用户说删就删）。"""
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— 删块用 `block remove <块 ref>`；"
            f"连它的块一起删掉这个任务用 `task rm {a.ref}`")
    users = refs_of_block(plan, block["id"])
    if users and not a.force:
        die(f"{block['id']} 还被这些块引用：{users} —— 确认后加 --force")
    old = block["status"]
    task["blocks"] = [b for b in task["blocks"] if b["id"] != block["id"]]
    log_event(plan, "remove", f"删除块 {block['id']}「{block['title']}」（原状态 {old}）"
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=block["id"])
    commit(a.slug, plan, a)
    print(f"✓ 已删除块 {block['id']}（原状态 {old}）")


def cmd_task_rm(a):
    """真删一条任务（连同它的块；取消 ≠ 删除）。"""
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is not None:
        die(f"{a.ref} 是块不是任务 —— 删这一个块用 `block remove {a.ref}`；"
            f"删它所属的任务用 `task rm {task['id']}`（连它的块一起删）")
    holders = [t["id"] for t in plan["tasks"]
               if task["id"] in (t.get("deps") or []) and t["id"] != task["id"]]
    if holders and not a.force:
        die(f"任务 {task['id']} 还被这些任务依赖：{holders} —— 确认后加 --force")
    ids = {b["id"] for b in (task.get("blocks") or [])}
    outs = [x for x in refs_to(plan, ids) if x.split("#")[0] != task["id"]]
    if outs and not a.force:
        die(f"任务 {task['id']} 的块还被别的块依赖：{outs} —— 确认后加 --force"
            f"（不然那几条依赖会变成悬空，check 会一直报）")
    n = len(task.get("blocks") or [])
    plan["tasks"] = [t for t in plan["tasks"] if t["id"] != task["id"]]
    log_event(plan, "remove", f"删除任务 {task['id']}「{task['title']}」（含 {n} 个块）"
              + (f"（{a.note}）" if a.note else ""), actor=a.actor, ref=task["id"])
    commit(a.slug, plan, a)
    print(f"✓ 已删除任务 {task['id']}（含 {n} 个块）")

def cmd_block_move(a):
    """把一个块移到**另一条任务**（泳道）—— 画布上的跨泳道拖动走同一条 `edits.move_block`。

    换泳道 = 换块 id + 把引用旧 id 的 `deps` / `review_of` 全部重接；成环则拒改（什么都不写）。
    """
    plan = load(a.slug)
    block, notes = edits.move_block(plan, a.ref, a.task, index=a.index,
                                    note=a.note, actor=a.actor)
    commit(a.slug, plan, a)
    print(f"✓ {a.ref} → {block['id']}")
    for n in notes:
        print(f"    {n}")
    return 0


def cmd_block_bypass(a):
    """把一个**中间块**从链上摘掉：它在等的前置，改成原来等它的那些块直接等（前后接起来）。

    与 `block remove` 的分工：remove 看见还有人引用就停手（要人加 `--force` 承担悬空），
    bypass 就是**替人把那几处接线改对再删** —— 图上不留悬空、也不会凭空少掉一段前置。
    """
    plan = load(a.slug)
    block, preds, users, notes = edits.bypass_block(plan, a.ref, note=a.note, actor=a.actor)
    commit(a.slug, plan, a)
    print(f"✓ 绕过 {block['id']}「{block['title']}」（原状态 {block['status']}）")
    print(f"    它等的前置 {('、'.join(preds)) or '（无）'} → 直接接给 {('、'.join(users)) or '（没人等它）'}")
    for n in notes:
        print(f"    {n}")
    return 0


def cmd_block_expand(a):
    """把一个块（B）展开成一个任务（T）：原块成为第一步，--step 依次追加后续步骤。

    前后关系一次改对：等这个块的块改等新链尾；这个块自己的前置原样成为第一步的前置。
    """
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— expand 作用于块（T-001#B-002 或 B-002）；"
            f"要把任务的块合并起来用 compress")
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
        nb = new_block(f"{tid}#B-{i:03d}", title=t_, kind=k_, status="pending",
                       owner=owner, doc=d_, done_when=c_, deps=[chain[-1]["id"]])
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

def cmd_block_compress(a):
    """把一个任务（T）压成一个块（B）：各步合成一块，前后接线一次改对。

    块必须住在某个任务里，所以「压」要交代落点：--keep-task（留在本任务，只剩这一块）、
    --into <块/任务>（插到别处）、默认回展开前的位置，再不行落进它等着的那个任务。
    """
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is not None:
        die(f"{a.ref} 是块不是任务 —— compress 作用于任务（T-001），它和 `block expand` 互为逆操作；"
            f"要把一个块单独删掉用 `block remove`")
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
    merged = new_block(mid, title=a.title or task["title"], kind=kind, status=status,
                       owner=a.owner or task.get("owner") or live[0].get("owner") or "",
                       doc=doc, done_when=crit, artifacts=arts, deps=ext,
                       review_of=(rviews.pop() if len(rviews) == 1 else ""),
                       feedback=(live[0].get("feedback") or "") if len(live) == 1 else "",
                       runs=runs, exec=exe, folded_from=folded)

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
    log_event(plan, "compress",
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

def _plan_row(p: Path):
    pp = json.loads(p.read_text(encoding="utf-8"))
    done, tot = progress(pp)
    return (pp["slug"], pp["title"], f"{done}/{tot}", pp.get("status", ""), pp.get("updated_at", "")[:16])


def _print_rows(rows):
    if not rows:
        print("（还没有 plan）")
        return
    w = max([len(r[0]) for r in rows] + [4])
    for r in rows:
        print(f"{r[0]:<{w}}  {r[2]:>6}  {r[3]:<9} {r[4]}  {r[1]}")


def cmd_list(a):
    """列 plan：给了 `--plan` 就只列这一份；否则列 `--plans-root` 那个库里的全部。"""
    if plan_file():
        p = plan_path("")
        if not p.exists():
            print(f"（没有这份 plan 数据文件：{p}）")
            return
        _print_rows([_plan_row(p)])
        return
    root = plans_root()
    if root is None:
        print("（没给 plan 库目录 —— `loomerto --plans-root <目录> list`；"
              "只想列一份用 `loomerto --plan <数据文件> list`）")
        return
    if not root.exists():
        print(f"（{root} 还不存在）")
        return
    _print_rows([_plan_row(d / "plan.json") for d in sorted(root.iterdir())
                 if (d / "plan.json").exists()])

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

def cmd_task_show(a):
    """看一条任务的详细信息（含它的块一览）—— 只读。"""
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is not None:
        die(f"{a.ref} 是块不是任务 —— 看块用 `block show {a.ref}`；"
            f"看任务全景用 `task show {task['id']}`")
    d = plan_dir(a.slug)
    rows = [{"id": x["id"], "title": x["title"], "kind": x.get("kind", ""),
             "status": block_effective(plan, x, task), "owner": x.get("owner") or ""}
            for x in task.get("blocks") or []]
    if a.json:
        print(json.dumps({"kind": "task", "plan": plan["slug"], "id": task["id"],
                          "title": task.get("title", ""), "status": task_status(plan, task),
                          "owner": task.get("owner") or "", "deps": list(task.get("deps") or []),
                          "blocks": rows}, ensure_ascii=False, indent=2))
        return 0
    print(f"plan: {plan['title']}  ({plan['slug']})")
    st = task_status(plan, task)
    print(f"{task['id']}  {task.get('title', '')}  [{STATUS_ZH.get(st, st)}]")
    print(f"  认领  @{task.get('owner') or '未指派'}")
    print(f"  前置  {'、'.join(task.get('deps') or []) or '—'}")
    print(f"  块    {len(rows)} 个")
    for r in rows:
        print(f"    [{STATUS_ZH.get(r['status'], r['status'])}] {r['id']}  {r['title']}"
              f"  @{r['owner'] or '未指派'}")
    print(f"  视图  {d}/PLAN.md · file://{d}/plan.html")
    return 0


def cmd_block_show(a):
    """看一个块的详细信息 —— 只读（状态·认领·在做·线程·做什么·判据·依赖·run）。"""
    plan = load(a.slug)
    task, block = find(plan, a.ref)
    if block is None:
        die(f"{a.ref} 是任务不是块 —— 看任务全景用 `task show {a.ref}`；"
            f"看块用 `block show <块 ref>`（B-001 或 {task['id']}#B-001）")
    d = plan_dir(a.slug)
    eff = block_effective(plan, block, task)
    cby, cat = claim_of(block)
    runs = block.get("runs") or []
    shown = runs[-a.runs:] if a.runs > 0 else runs
    rework = sum(1 for r in runs if r.get("from") == "review" and r.get("to") != "done")
    ex = block.get("exec") or {}
    obj = {"kind": "block", "plan": plan["slug"], "id": block["id"], "title": block["title"],
           "status": eff, "status_since": block.get("status_since", ""), "type": block.get("kind", ""),
           "task": {"id": task["id"], "title": task.get("title", "")},
           "owner": block.get("owner") or "", "claimed_by": cby, "claimed_at": cat,
           "doc": block.get("doc", ""), "done_when": list(block.get("done_when") or []),
           "input": block.get("input", ""), "output": block.get("output", ""),
           "command": block.get("command", ""),
           "deps": block_deps(plan, task, block), "own_deps": list(block.get("deps") or []),
           "review_of": block.get("review_of", ""), "feedback": block.get("feedback", ""),
           "rework": rework, "artifacts": list(block.get("artifacts") or []), "exec": ex,
           "runs": shown, "views": {"md": f"{d}/PLAN.md", "html": f"{d}/plan.html",
                                    "canvas": f"{d}/plan.canvas"}}
    if a.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return 0

    since = (block.get("status_since") or "")[:16].replace("T", " ")
    print(f"plan: {plan['title']}  ({plan['slug']})")
    print(f"{block['id']}  {block['title']}")
    print(f"  状态  {STATUS_ZH.get(eff, eff)}（{eff}）" + (f" · 自 {since}" if since else ""))
    print(f"  类型  {block.get('kind', '')}")
    print(f"  归属  {task['id']} {task.get('title', '')}")
    print(f"  认领  @{cby or block.get('owner') or '未指派'}"
          + (f"（{cat[:16].replace('T', ' ')}）" if cat else ""))
    eb = exec_brief(block)
    print(f"  在做  {eb[3:] if eb else '未登记'}")
    if ex.get("transcript"):
        print(f"        转录 {ex['transcript']}")
    print(f"  做什么 {block.get('doc') or '——'}")
    for zh, k in (("输入", "input"), ("输出", "output"), ("命令", "command")):
        if block.get(k):
            print(f"  {zh}  {block[k]}")
    dw = block.get("done_when") or []
    for i, c in enumerate(dw):
        print(f"  {'判据' if i == 0 else '    '}  {c}")
    if not dw:
        print("  判据  ——（缺，check 会告警）")
    print(f"  依赖  {'、'.join(obj['deps']) or '—'}")
    if block.get("review_of"):
        print(f"  评审  {block['review_of']}")
    if rework or block.get("feedback"):
        print(f"  返工  ⟲{rework}" + (f" · {block['feedback']}" if block.get("feedback") else ""))
    arts = block.get("artifacts") or []
    for i, p in enumerate(arts):
        print(f"  {'产物' if i == 0 else '    '}  {p}")
    print(f"  run   {len(runs)} 条" + (f"（列最近 {len(shown)}）" if len(shown) < len(runs) else ""))
    for r in shown:
        print(f"    · {(r.get('at') or '')[:16].replace('T', ' ')} {r.get('by', '')}"
              f" {r.get('from', '')}→{r.get('to', '')}  {r.get('note', '')}".rstrip())
    print(f"  视图  {d}/PLAN.md · file://{d}/plan.html")
    return 0

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
        eff = block_effective(plan, b, t)
        if owner_rule(eff) == "required" and not (b.get("owner") or "").strip():
            warns.append(f"{b['id']} 是「{STATUS_ZH.get(eff, eff)}」却没有负责人 —— "
                         f"谁接的要说清（`block assign {b['id']} --to <参与方>`）")
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
        raw = b.get("status") or ""
        # 「在途」按**存储**状态判：派生出来的「已认领」（`pending` + 有 owner）既没登记过线程、
        # 也没有开工时刻 —— 它不该出现在这份报告里（见 model.STATUS_OWNER）。
        if not ex.get("by") and raw not in ACTIVE:
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
             f"plan: `{d}/PLAN.md` — 开工前先读它，状态只通过 `loomerto`（或 skill 里的 `plan.py`）改。"]
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
# 一条命令一个属性：命令名那截 → (块的键, 值那一格的说明)。加一条属性 = `model.BLOCK_FIELDS`
# 加一个键（若还没有）+ 这里加一行 + 在 `_parser()` 的 block 组里按想要的顺序 `_add_set_attr()`。
_SET_ATTRS = {
    "title":   ("title",     "新标题，不能清空（块必须有标题）"),
    "doc":     ("doc",       "留空 = 清空"),
    "type":    ("kind",      " / ".join(KINDS)),
    "input":   ("input",     "这一步吃什么（数据 / 路径 / 前提），留空 = 清空"),
    "output":  ("output",    "这一步吐什么（产物长什么样），留空 = 清空"),
    "command": ("command",   "具体跑什么命令，留空 = 清空"),
    "audit":   ("done_when", "验收标准，多条用 ; 分隔、整组替换，留空 = 清空"),
}


def _add_set_attr(g, name: str) -> None:
    """`block set_title` / `set_doc` / `set_type` / `set_input` / `set_output` / `set_command` /
    `set_audit` 这一族解析器 —— 形状一样（`<块ref> <值>`），只有那一格的说明不同。

    `<值>` 可以留空（= 清空）：文件模式下位置参数整体左移，所以它得登记在 `optional` 里
    （见 `_apply_file_mode`），不然合法的「只给 ref」会被判成「少写了参数」。
    """
    key, what = _SET_ATTRS[name]
    p = g.add_parser(f"set_{name}",
                     help=f"改块的「{edits.FIELD_ZH.get(key, key)}」—— {what}；不动状态，改动记进日志")
    p.add_argument("slug", nargs="?")
    p.add_argument("ref", nargs="?", default=None, help="块：T-002#B-001 或 B-001")
    p.add_argument("value", nargs="?", default=None, help=f"新值：{what}")
    p.add_argument("--note", default="", help="为什么改（会记进日志）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_set_attr, attr=key, shift=["ref", "value"], optional=["value"])


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="loomerto", description="loomerto —— 一份 plan 的工具（谁认领/谁在做/下一步该谁动）")
    ap.add_argument("--no-render", action="store_true",
                    help="只改数据，不刷新 PLAN.md/plan.html/plan.canvas")
    ap.add_argument("--plan", dest="plan_file", default="",
                    help="直接指定那一份 plan 数据文件（plan.json；给目录就取其中的 plan.json）"
                         "—— 等价于 $LOOMERTO_PLAN_FILE；给了它，命令里就不必再写 slug")
    ap.add_argument("--plans-root", dest="plans_root", default="",
                    help="一份 plan 库的目录（等价于 $LOOMERTO_PLANS_ROOT）—— 库里有多份 plan、要按 slug 选时才用")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # —— plan 组：一份 plan 本身
    g = sub.add_parser("plan", help="plan 本身的操作（new）").add_subparsers(dest="sub", required=True)
    p = g.add_parser("new", help="新建一份 plan")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--title")
    p.add_argument("--goal")
    p.add_argument("--owner", action="append", help="id=kind:label[:channel]，可多次")
    p.add_argument("--digest-hours", type=float, default=6)
    p.add_argument("--quiet-hours", default="23:00-08:00")
    p.add_argument("--force", action="store_true")
    p.set_defaults(f=cmd_new)

    # —— task 组：任务（泳道）
    g = sub.add_parser("task", help="任务（泳道）：new / set / rm / show"
                       ).add_subparsers(dest="sub", required=True)
    p = g.add_parser("new", help="加一条任务（泳道）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--title", required=True)
    p.add_argument("--id")
    p.add_argument("--owner", default="")
    p.add_argument("--deps", nargs="*", default=[])
    p.add_argument("--note", default="")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_task)

    p = g.add_parser("set", help="改任务状态（pending/running/done/blocked/cancelled）"
                                 "；登记在做的人与线程只在 running 时收")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="任务：T-002")
    p.add_argument("status", nargs="?", default=None,
                   help="目标状态；只清线程登记（--unset）时可以不写")
    p.add_argument("--note", default="")
    p.add_argument("--owner", default="")
    p.add_argument("--by", default="", help="谁在做（只在 running 时收）")
    p.add_argument("--delegation", default="", help="子代理线程号 deleg_xxxxxxxx（只在 running 时收）")
    p.add_argument("--task-index", dest="task_index", type=int, default=None,
                   help="这条线程下第几个 task（默认 0；只在给 --delegation 时收）")
    p.add_argument("--transcript", default="",
                   help="转录文件路径 —— 转录放在哪是调用方的事，loomerto 不猜任何 harness 的目录")
    p.add_argument("--at", default="", help="补记时间（ISO8601），默认现在")
    p.add_argument("--unset", action="store_true",
                   help="清掉「在做 + 线程」登记（<状态> 这时可以省）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_task_set, shift=["ref", "status"], optional=["status"])

    p = g.add_parser("rm", help="真删一条任务（连同它的块；取消 ≠ 删除）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="任务：T-002")
    p.add_argument("--note", default="", help="为什么删（会记进日志）")
    p.add_argument("--force", action="store_true", help="已被别的任务依赖时仍然删")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_task_rm, shift=["ref"])

    p = g.add_parser("show", aliases=["info"], help="看一条任务的详细信息（含它的块一览，只读）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="任务：T-002")
    p.add_argument("--json", action="store_true", help="机器可读输出（给 agent 用）")
    p.set_defaults(f=cmd_task_show, shift=["ref"])

    # —— block 组：任务里的块（状态、文档、结构都落在这）
    # 顺序 = 用户拍板的那一份（结构 → 粒度 → 读 → 接线 → 身份 → 属性，属性一组一条命令）。
    g = sub.add_parser(
        "block",
        help="块：add / remove / insert / bypass / expand / compress / show / deps / assign / move / "
             "set_title / set_doc / set_type / set_status / set_input / set_output / set_command / set_audit"
        ).add_subparsers(dest="sub", required=True)
    p = g.add_parser("add", help="往一条任务末尾加块（文档）")
    p.add_argument("slug", nargs="?")
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
    p.set_defaults(f=cmd_block_add)

    p = g.add_parser("remove", help="真删一个块（取消 ≠ 删除；被别的块引用时默认拒删 —— "
                                    "要连同接线一起改对用 `block bypass`）")
    p.add_argument("slug", nargs="?")
    p.add_argument("ref", nargs="?", default=None, help="块：T-002#B-001 或 B-001")
    p.add_argument("--note", default="", help="为什么删（会记进日志）")
    p.add_argument("--force", action="store_true", help="已被别的块引用时仍然删")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_remove, shift=["ref"])

    p = g.add_parser("insert", help="插一个块到某个块之前/之后（前后接线一次改对）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="锚块：T-002#B-001 或 B-001")
    p.add_argument("--before", action="store_true", help="插到锚块之前（不给就是它）")
    p.add_argument("--after", action="store_true", help="插到锚块之后")
    p.add_argument("--title", required=True)
    p.add_argument("--kind", default="impl", choices=KINDS)
    p.add_argument("--doc", default="")
    p.add_argument("--done-when", action="append", default=[])
    p.add_argument("--owner", default="", help="默认沿用锚块的认领人")
    p.add_argument("--review-of", default="")
    p.add_argument("--status", default="blocked", choices=BLOCK_STATUS,
                   help="同 block add：默认 blocked（待批准）")
    p.add_argument("--note", default="", help="为什么插（会记进日志）")
    p.add_argument("--dry-run", action="store_true", help="只打印会改什么，不落盘")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_insert, shift=["ref"])

    p = g.add_parser("bypass", help="把一个中间块从链上摘掉：它在等的前置，改成原来等它的块直接等"
                                    "（前后接起来；成环则拒改）")
    p.add_argument("slug", nargs="?")
    p.add_argument("ref", nargs="?", default=None, help="要绕过的块：T-001#B-002 或 B-002")
    p.add_argument("--note", default="", help="为什么绕过（会记进日志）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_bypass, shift=["ref"])

    p = g.add_parser("expand", help="把一个块展开成一个任务（块成为第一步，--step 追加后续步骤）")
    p.add_argument("slug", nargs="?")
    p.add_argument("ref", nargs="?", default=None, help="要展开的块：T-001#B-002 或 B-002")
    p.add_argument("--title", default="", help="新任务的标题（默认沿用块标题）")
    p.add_argument("--step", action="append", default=[],
                   help="追加的后续步骤，可多次、按顺序：标题 :: 做什么 :: 判据1;判据2 :: kind")
    p.add_argument("--owner", default="")
    p.add_argument("--note", default="", help="为什么展开（会记进日志）")
    p.add_argument("--dry-run", action="store_true", help="只打印会改什么，不落盘")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_expand, shift=["ref"])

    p = g.add_parser("compress", help="把一个任务压成一个块（默认回展开前的位置）；"
                                      "与 `block expand` 互为逆操作（旧名 collapse 已删）")
    p.add_argument("slug", nargs="?")
    p.add_argument("ref", nargs="?", default=None, help="要压缩的任务：T-001")
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
    p.set_defaults(f=cmd_block_compress, shift=["ref"])

    p = g.add_parser("show", aliases=["info"],
                     help="看一个块的详细信息（只读：状态·认领·在做·线程·做什么·输入·输出·命令·判据·依赖·run）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="块：T-002#B-001 或 B-001")
    p.add_argument("--json", action="store_true", help="机器可读输出（给 agent 用）")
    p.add_argument("--runs", type=int, default=5, help="列最近几条 run（0 = 全列，默认 5）")
    p.set_defaults(f=cmd_block_show, shift=["ref"])

    p = g.add_parser("deps", help="改一个块的**前置依赖**（整组替换或加减；成环则拒改、什么都不写）")
    p.add_argument("slug", nargs="?")
    p.add_argument("ref", nargs="?", default=None, help="块：T-002#B-001 或 B-001")
    p.add_argument("--deps", nargs="*", default=None,
                   help="整组替换（给空 = 清空前置）；与 --add / --rm 不能同时给")
    p.add_argument("--add", nargs="*", default=[], help="加几条前置（已在里面的跳过）")
    p.add_argument("--rm", nargs="*", default=[], help="去掉几条前置")
    p.add_argument("--note", default="", help="为什么改（会记进日志）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_deps, shift=["ref"])

    p = g.add_parser("assign", help="把一个块指派给某个参与方（不动状态，改动记进日志）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="块：T-002#B-001 或 B-001")
    p.add_argument("--to", default="", help="参与方 id（plan.json 里 participants 的 id）")
    p.add_argument("--unset", action="store_true", help="清掉指派（回到未指派）")
    p.add_argument("--note", default="", help="为什么（会记进日志）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_assign, shift=["ref"])

    p = g.add_parser("move", help="把一个块移到另一条任务（泳道）：换块 id + 重接依赖接线（成环则拒改）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="要移的块：T-001#B-002 或 B-002")
    p.add_argument("--task", required=True, help="落到哪条任务（泳道）：T-003")
    p.add_argument("--index", type=int, default=None,
                   help="插到该任务的第几位（0 起；默认追加到末尾）")
    p.add_argument("--note", default="", help="为什么移（会记进日志）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_move, shift=["ref"])

    # —— 属性各一条：`block set_<属性> <块ref> <值>`（值留空 = 清空；加一条见 `_SET_ATTRS`）
    _add_set_attr(g, "type")
    _add_set_attr(g, "title")
    _add_set_attr(g, "doc")

    p = g.add_parser("set_status", help="改块状态（pending/claimed/running/review/done/blocked/cancelled）"
                                        "；登记在做的人与线程只在在途状态收（表见 docs/cli-reference.md）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("ref", nargs="?", default=None, help="块：T-002#B-001 或 B-001")
    p.add_argument("status", nargs="?", default=None,
                   help="目标状态；只清线程登记（--unset）时可以不写")
    p.add_argument("--note", default="", help="为什么（review 打回时落进 feedback）")
    p.add_argument("--owner", default="")
    p.add_argument("--by", default="", help="谁在做（在途状态才收）")
    p.add_argument("--delegation", default="", help="子代理线程号（在途状态才收）")
    p.add_argument("--task-index", dest="task_index", type=int, default=None,
                   help="这条线程下第几个 task（默认 0；只在给 --delegation 时收）")
    p.add_argument("--transcript", default="",
                   help="转录文件路径 —— 转录放在哪是调用方的事，loomerto 不猜任何 harness 的目录")
    p.add_argument("--at", default="", help="补记时间（ISO8601），默认现在")
    p.add_argument("--artifact", action="append", default=[], help="收工产物（只在 done 收）")
    p.add_argument("--doc", default="", help="改块文档（做什么）——事实变了就改原文，别只写在日志里")
    p.add_argument("--done-when", dest="done_when", action="append", default=[],
                   help="改判据，可多次")
    p.add_argument("--unset", action="store_true",
                   help="清掉「在做 + 线程」登记（<状态> 这时可以省）")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_block_set_status, shift=["ref", "status"], optional=["status"])

    _add_set_attr(g, "input")
    _add_set_attr(g, "output")
    _add_set_attr(g, "command")
    _add_set_attr(g, "audit")


    # —— 单层命令：对整份 plan 的动作（不改一个具体对象）
    p = sub.add_parser("note", help="写一条总结/决定进日志")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("text", nargs="?", default=None)
    p.add_argument("--kind", default="summary",
                   choices=["summary", "decision", "reminder", "created", "task",
                            "block", "status", "insert", "assign", "deps", "remove", "move",
                            "bypass", "expand", "collapse", "compress"])
    p.add_argument("--ref", default="")
    p.add_argument("--actor", default="agent")
    p.set_defaults(f=cmd_note, shift=["text"])

    p = sub.add_parser("digest", help="生成提醒/摘要文本")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--to", default="", help="只提醒某个参与方（id，或 you）")
    p.add_argument("--format", default="discord", choices=["discord", "md"])
    p.add_argument("--stale-hours", type=float, default=24)
    p.set_defaults(f=cmd_digest)

    p = sub.add_parser("render", help="重新生成 PLAN.md / plan.html / plan.canvas")
    p.add_argument("slug", nargs="?", default="")
    p.set_defaults(f=cmd_render)

    p = sub.add_parser("check", help="图质量检查")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--stale-hours", type=float, default=24)
    p.set_defaults(f=cmd_check)

    p = sub.add_parser("current", help="现在可动的块")
    p.add_argument("slug", nargs="?", default="")
    p.set_defaults(f=cmd_current)

    p = sub.add_parser("workers", aliases=["threads"],
                       help="检查每个在途块登记的子代理线程是否还在动（已结束/记错 ⇒ exit 1）")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--stale-min", dest="stale_min", type=float, default=30,
                   help="转录多久没写一行就算静默（默认 30 分钟）")
    p.add_argument("--json", action="store_true", help="机器可读输出（给 agent 用）")
    p.set_defaults(f=cmd_workers)

    p = sub.add_parser("list", help="列出所有 plan")
    p.set_defaults(f=cmd_list)

    p = sub.add_parser("open", help="把一份 plan 当**可编辑的画布**打开（本地服务，只绑 127.0.0.1）")
    p.add_argument("target", nargs="?", default="",
                   help="plan 数据文件（也可以给目录）；给了 --plans-root 时这里可以写 slug")
    p.add_argument("--port", type=int, default=0, help="端口（默认 0 = 自动挑一个空闲的）")
    p.add_argument("--no-open", dest="no_open", action="store_true", help="不要自动打开浏览器")
    p.set_defaults(f=cmd_open)

    return ap


def cmd_open(a):
    """把一份 plan 当**可编辑的画布**打开：起一个只绑 127.0.0.1 的本地服务，改一下写回 json。"""
    load(a.slug)                 # 先读一遍：数据文件不在就当场报错，别等浏览器弹出来才发现
    from . import serve          # 再 import：平时不跑服务的人不必付 http.server 的代价
    return serve.run(a.slug, port=a.port, open_browser=not a.no_open)


def _slug_of_data_file() -> str:
    """数据文件里的 slug（文件还没有 / 读不动就取它所在目录名）。"""
    p = plan_path("")
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("slug") or p.parent.name
    except (OSError, ValueError):
        return p.parent.name


def _cmd_name(a) -> str:
    """命令的完整写法（`plan new` / `set`），出错提示里用。"""
    sub = getattr(a, "sub", "") or ""
    return f"{a.cmd} {sub}" if sub else a.cmd


def _apply_file_mode(a) -> int:
    """单文件模式（`--plan <数据文件>`，或当前目录正好有 plan.json）：把 slug 那一位让出来。

    这些命令的第一个位置参数本来是 slug —— 文件模式下它其实是**下一个**参数
    （`block set_status <ref> <status>` / `block show <ref>` / `note <text>`…），所以整体左移一位：
    `loomerto --plan ./plan.json block set_status T-001#B-002 done`。返回非 0 表示已经报错，当退出码用。
    """
    dests = list(getattr(a, "shift", []) or [])
    opt = set(getattr(a, "optional", []) or [])     # 允许留空的格子（如 `set` 的 <状态>：只给 --unset 时）
    slug = getattr(a, "slug", "")          # `open` 这类命令没有 slug 位（它的位置参数是 target）
    if dests:
        if getattr(a, dests[-1], None) not in (None, ""):
            print(f"文件模式（--plan）下不要再写 slug —— 位置参数整体左移一位，例：\n"
                  f"  loomerto --plan <plan 数据文件> {_cmd_name(a)} "
                  + " ".join(f"<{d}>" for d in dests), file=sys.stderr)
            return 2
        vals = [slug] + [getattr(a, d) for d in dests]
        for d, v in zip(dests, vals):
            setattr(a, d, v)
        slug = ""
        missing = [d for d in dests if getattr(a, d) in (None, "") and d not in opt]
        if missing:
            print(f"{_cmd_name(a)} 要 " + " ".join(f"<{d}>" for d in dests)
                  + "（文件模式下不用写 slug）", file=sys.stderr)
            return 2
    real = _slug_of_data_file()
    new_plan = (a.cmd == "plan" and (getattr(a, "sub", "") or "") == "new")
    if slug and not new_plan and slug != real:
        print(f"--plan 指的是 '{real}'，命令里却还写着 slug '{slug}' —— "
              f"文件模式下不要再写 slug", file=sys.stderr)
        return 2
    a.slug = slug or real
    return 0


def main(argv=None):
    """任何 harness 的入口：返回退出码（0/1/2），自己不 sys.exit。"""
    a = _parser().parse_args(argv)
    # 定位这一份 plan：`--plans-root` 给库；`--plan` 钉死那一份数据文件；
    # `open` 的位置参数两条路都认（带 / 或 .json 结尾 = 路径，否则在库模式下当 slug）
    if getattr(a, "plans_root", ""):
        os.environ["LOOMERTO_PLANS_ROOT"] = a.plans_root
    tgt = (getattr(a, "target", "") or "").strip() if a.cmd == "open" else ""
    if tgt and not ("/" in tgt or tgt.endswith(".json")) and plans_root() is not None:
        a.slug = tgt
        tgt = ""
    if tgt:
        _store.PLAN_FILE = str(Path(tgt).expanduser())
        if getattr(a, "plan_file", ""):
            print("⚠ open 的位置参数与 --plan 都给了 —— 按位置参数算", file=sys.stderr)
    elif getattr(a, "plan_file", ""):
        _store.PLAN_FILE = str(Path(a.plan_file).expanduser())
        if getattr(a, "plans_root", ""):
            print("⚠ 同时给了 --plan 与 --plans-root —— 按 --plan 算", file=sys.stderr)
    try:
        if a.cmd == "list":
            return cmd_list(a) or 0
        if _store.file_mode():
            rc = _apply_file_mode(a)
            if rc:
                return rc
        elif not getattr(a, "slug", ""):
            print("要给 slug（或改用 `--plan <plan 数据文件>`）：\n"
                  "  loomerto --plans-root <目录> <子命令> <slug>\n"
                  "  loomerto --plan <plan 数据文件> <子命令>", file=sys.stderr)
            return 2
        r = a.f(a)
        return r if isinstance(r, int) else 0
    except PlanError as e:          # 模型层/存储层的硬错误：说给人听 + 用建议的退出码
        print(str(e), file=sys.stderr)
        return e.code
