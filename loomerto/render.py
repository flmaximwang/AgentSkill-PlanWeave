"""视图层：`plan.json` → PLAN.md / plan.canvas / plan.html —— 只读模型、只返回字符串，不写盘。

写盘由 store.render_all() 负责（同一处守「三个视图永远原子替换」）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import (all_blocks, block_deps, block_effective, claim_of, deps_of,
                    edge_deps, exec_brief, progress, task_status)

# 状态的中文名（图例顺序 = 一个块的一生，改顺序就是改 plan.html 里 C/ZH 的键序）
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

def theme_css(template: Path) -> str:
    """**共用主题**（plan.html 与 canvas.html 都注入它）：与模板同目录的 `theme.css`。

    颜色 / 字体 / 状态胶囊 / 按钮 / 分隔线 / 进度条只有这一份来源 —— 两页因此不会各长一套观感。
    模板被 `$LOOMERTO_TEMPLATE` 指到别处、同目录没有 theme.css 时，退回包自带的那一份。
    """
    local = Path(template).with_name("theme.css")
    if local.is_file():
        return local.read_text(encoding="utf-8")
    return (Path(__file__).resolve().parent / "assets" / "theme.css").read_text(encoding="utf-8")


def render_html(plan: dict, template: Path) -> str:
    """模板路径由 store 传进来：视图层不碰路径常量，免得两层互相 import。"""
    tpl = Path(template).read_text(encoding="utf-8")
    data = json.dumps(plan, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("/*__PLAN_DATA__*/null", data).replace("/*__THEME__*/", theme_css(template))
