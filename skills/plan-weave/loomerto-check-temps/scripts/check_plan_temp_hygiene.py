#!/usr/bin/env python3
"""check_plan_temp_hygiene.py — 一份 plan 的「临时文件卫生」校验器。

问三件事，每件都给证据：
  1. 这个 plan 会不会写出临时/中间产物？（扫 doc / done_when / cmds / 产物 / 日志）
  2. 这些临时文件**声明**了吗？（谁产生、在哪、是临时的）
  3. 有没有一个**收尾节点**在流程上排在所有生产节点之后、负责把它们删掉，且判据可核验？

结论词（三值，互不代替 —— 「没查出来」有自己的词，不能被读成「没有」）：
  ✅ 闭环    有生产、有声明、有收尾
  ⚠️ 部分    有生产、收尾也在，但声明缺项或收尾判据不可核验
  ❌ 不闭环  有生产，但没人声明 / 没人收尾（或收尾节点排在生产者之前）→ 退出码 1
  ➖ 无需清理 没检测到会写临时产物的形态（**不等于「一定不产生」**，判据与扫过的字段都打印出来）

退出码：0 = 批准（✅ / ⚠️ / ➖）· 1 = 不闭环（❌）· 2 = 用法错 · 4 = 找不到 plan
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PROFILE_HOME = HERE.parents[4]
DEFAULT_PLANS_ROOT = PROFILE_HOME / "workspace" / "plans"

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_PLAN = 0, 1, 2, 4

# 强证据：文本直接指认「临时 / 中间 / 缓存 / 暂存区」性质的东西
STRONG = [
    (r"/tmp\b", "/tmp"),
    (r"\$TMPDIR\b", "$TMPDIR"),
    (r"临时文件|临时目录|临时产物|临时副本|临时的|临时落点", "「临时…」字样"),
    (r"中间产物|中间文件|中转目录|中转文件", "中间产物"),
    (r"\.tmp\b|\.temp\b|\.part\b|\.partial\b|\.copy[-\w]+\b", ".tmp/.part/.copy 之类"),
    (r"~/\.cache|\.hermes/cache|/\.cache/", "cache 目录"),
    (r"\bscratch\b", "scratch（缓存暂存区）"),
    (r"_migrate\b|\bstaging\b|暂存目录|暂存盘|本地暂存|暂存区里的|暂存的数据", "迁移/暂存区"),
    (r"清空本地暂存|本地暂存已清|删掉暂存|清掉暂存", "本地暂存"),
]
# 中等证据（写文件的形态）：只在 --strict 下一并当证据；单独出现不判「有临时文件」
WRITE_FORM = [
    (r"(?<![0-9])>>?\s*[~/.$A-Za-z0-9_]", "重定向写入（> / >>）"),
    (r"\btee\b", "tee"),
    (r"\bmktemp\b", "mktemp"),
    (r"--out(?:put)?[= ]\S", "--out/--output"),
    (r"\bwget\b[^\n]*\s-O\b", "wget -O"),
    (r"\bcurl\b[^\n]*\s-[oO]\b", "curl -o/-O"),
    (r"\bconver[t]\b|\bffmpeg\b|\bpandoc\b|\bsips\b", "媒体转换产新文件"),
    (r"--screenshot|plan\.png", "截图产物"),
    (r"mysqldump|\.dump\b|导出成 dump|dump 文件", "dump 文件"),
    (r"打包成 tar|tar 包|\.tar\b|tar -c", "tar 包"),
    (r"\bmkdir\b[^\n]*\b(tmp|temp|scratch|staging|_migrate|中转)", "建临时目录"),
    (r"--manifest[= ]\S|--index[= ]\S", "生成清单/索引文件"),
]
# 同音词遮蔽：「暂存」= git staging、「副本」= 工作副本/两份笔记、「残留」= 没留下坏链接、
# 「截图」= 笔记里的附件 —— 这些行讲的都不是临时文件（本工具第一版就在这上面误判过 4 份 plan）
NOT_TEMP = re.compile(r"--cached|git add|pathspec|暂存并|暂存后|暂存了|路径残留|0 残留|零残留|"
                      r"工作副本|份副本|副本比对|不清理|不删除|不删现有|"
                      r"不是[^\n]{0,10}(中间文件|临时文件|临时产物|临时目录)")
# 声明标签：这一行在说「会产生什么临时文件」
DECL_LABEL = re.compile(r"^\s*(?:\*\*)?(临时文件|临时产物|临时目录|临时清单|临时数据|中间产物|"
                        r"暂存目录|本地暂存|scratch 目录)[^\n]{0,24}[:：=]")
# 临时性质的**路径**（出现在产物字段里 = 事实上的声明）
TEMP_PATH = re.compile(r"/tmp/|\$TMPDIR|/\.cache/|\.hermes/cache|scratch/|_migrate/|/staging/|"
                       r"\.tmp\b|\.part\b|临时|暂存|中转")
PATHY = re.compile(r"(~?/[^\s，。；、（）()【】\[\]`]+|[\w.\-]*\*[\w.\-*]+|"
                   r"\S+\.(?:tmp|temp|log|json|jsonl|tsv|csv|txt|png|tar|gz|sha256))")
# 收尾节点：标题里就说这件事，或正文/命令里有删除动作且上下文是临时文件（「收尾」单独不算 ——
# 它常指「收尾某件事」，本工具第一版在这上面误判过）
CLEAN_TITLE_START = re.compile(r"^\s*(清理|清除|删除|打扫|清空|收拾|善后|收尾清理)")
CLEAN_TITLE_ANY = re.compile(r"(清理|清除|删除|清空|打扫|善后)")
CLEAN_VERB = re.compile(r"清理|清除|删除|清空|清掉|移除|善后|撤销软链|摘掉软链|"
                        r"unlink|\brm\b|\bshred\b|clean\s?up|cleanup|trap\s+[^\n]*\bEXIT\b|释放空间")
TEMPISH = re.compile(r"临时|tmp|/tmp|scratch|cache|缓存|中间产物|暂存|中转|_migrate|staging|"
                     r"残留文件|tar 包|dump")
STRIP = re.compile(r"^[\s>*\-•]+")


def short(ids, n=6):
    """列表太长就打前 n 个 + 总数（57 个块 id 铺满屏幕会淹掉结论）。"""
    ids = list(ids)
    if len(ids) <= n:
        return "、".join(ids) if ids else "（无）"
    return "、".join(ids[:n]) + f" 等 {len(ids)} 个"


# ---------------------------------------------------------------- plan 读取

def resolve_plan(arg: str, plans_root: Path | None):
    tried = []
    p = Path(arg).expanduser()
    if p.is_dir():
        tried.append(str(p / "plan.json"))
        if (p / "plan.json").is_file():
            return json.loads((p / "plan.json").read_text(encoding="utf-8")), p / "plan.json"
    elif p.is_file():
        tried.append(str(p))
        return json.loads(p.read_text(encoding="utf-8")), p
    if "/" not in arg:
        for root in ([plans_root] if plans_root else []) + [DEFAULT_PLANS_ROOT]:
            if root is None:
                continue
            cand = Path(root).expanduser() / arg / "plan.json"
            tried.append(str(cand))
            if cand.is_file():
                return json.loads(cand.read_text(encoding="utf-8")), cand
    print("找不到 plan：{}".format(arg), file=sys.stderr)
    for t in tried:
        print("  找过：" + t, file=sys.stderr)
    print("  提示：用 `--plans-root <plans 目录>` 指定，或直接给 plan.json 的路径。",
          file=sys.stderr)
    sys.exit(EXIT_NO_PLAN)


# ---------------------------------------------------------------- 扫描

def text_fields(plan: dict, t: dict, b: dict):
    """(来源名, 文本) —— 顺序即报告里的顺序。"""
    yield "plan.goal", plan.get("goal") or ""
    yield "task.title", t.get("title") or ""
    yield "block.title", b.get("title") or ""
    yield "block.doc", b.get("doc") or ""
    for i, c in enumerate(b.get("done_when") or [], 1):
        yield f"block.done_when[{i}]", c
    for i, c in enumerate(b.get("cmds") or [], 1):
        yield f"block.cmds[{i}]", c
    for i, a in enumerate(b.get("artifacts") or [], 1):
        yield f"block.artifacts[{i}]", a
    for i, r in enumerate(b.get("runs") or [], 1):
        yield f"block.runs[{i}].note", r.get("note") or ""
    yield "block.feedback", b.get("feedback") or ""


def scan_evidence(plan: dict, args):
    """返回证据列表。tier=strong/write；kind=planned/actual（已有 run/日志 = 已经发生过）。"""
    out = []
    for t in plan.get("tasks") or []:
        for b in t.get("blocks") or []:
            if b.get("status") == "cancelled" and not args.include_cancelled:
                continue
            for src, text in text_fields(plan, t, b):
                if not text:
                    continue
                for lineno, raw in enumerate(text.splitlines() or [text], 1):
                    if NOT_TEMP.search(raw):
                        continue      # 同音词遮蔽：这行讲的不是临时文件（git 暂存 / 路径残留 …）
                    for tier, pats in (("strong", STRONG), ("write", WRITE_FORM)):
                        for pat, label in pats:
                            m = re.search(pat, raw, re.I)
                            if m:
                                out.append({
                                    "task": t["id"], "block": b["id"], "block_title": b.get("title", ""),
                                    "status": b.get("status", ""), "source": f"{src}:{lineno}",
                                    "tier": tier, "label": label, "match": m.group(0),
                                    "text": raw.strip()[:220],
                                    "when": "actual" if ("runs" in src or "feedback" in src
                                                         or b.get("status") == "done") else "planned",
                                })
                                break
                        else:
                            continue
                        break
    for i, e in enumerate(plan.get("log") or [], 1):
        raw = e.get("text") or ""
        for tier, pats in (("strong", STRONG), ("write", WRITE_FORM)):
            for pat, label in pats:
                m = re.search(pat, raw, re.I)
                if m and not NOT_TEMP.search(raw):
                    out.append({"task": "-", "block": e.get("ref") or "-", "block_title": "（日志）",
                                "status": "", "source": f"plan.log[{i}]", "tier": tier,
                                "label": label, "match": m.group(0), "text": raw.strip()[:220],
                                "when": "actual"})
                    break
            else:
                continue
            break
    return out


def scan_declarations(plan: dict, args):
    """声明 = 结构化 temps 字段 / 产物字段里指向临时位置的路径 / doc·goal 里「临时文件：…」行。"""
    out = []

    def add(where, what):
        out.append({"where": where, "what": (what or "")[:220]})

    for i, item in enumerate(plan.get("temps") or [], 1):
        add(f"plan.temps[{i}]", json.dumps(item, ensure_ascii=False))
    goal = plan.get("goal") or ""
    for i, raw in enumerate(goal.splitlines(), 1):
        if DECL_LABEL.search(STRIP.sub("", raw)):
            add(f"plan.goal:{i}", STRIP.sub("", raw))
    for t in plan.get("tasks") or []:
        for b in t.get("blocks") or []:
            if b.get("status") == "cancelled" and not args.include_cancelled:
                continue
            for key in ("temps", "tmp_paths"):
                for i, item in enumerate(b.get(key) or [], 1):
                    add(f"{b['id']}.{key}[{i}]", json.dumps(item, ensure_ascii=False))
            for i, a in enumerate(b.get("artifacts") or [], 1):
                if TEMP_PATH.search(a):
                    add(f"{b['id']}.artifacts[{i}]", a)
            lines = (b.get("doc") or "").splitlines()
            for i, raw in enumerate(lines):
                line = STRIP.sub("", raw)
                if DECL_LABEL.search(line) and PATHY.search(" ".join(lines[i:i + 4])):
                    add(f"{b['id']}.doc:{i + 1}", line)
    seen, uniq = set(), []
    for d in out:
        if (d["where"], d["what"]) not in seen:
            seen.add((d["where"], d["what"]))
            uniq.append(d)
    return uniq


def positions(plan: dict) -> dict:
    """块 id -> (任务序, 块序, 任务 id)，用来判「收尾节点排在生产者之后」。"""
    out = {}
    for ti, t in enumerate(plan.get("tasks") or []):
        for bi, b in enumerate(t.get("blocks") or []):
            out[b["id"]] = (ti, bi, t["id"])
    return out


def scan_cleanup(plan: dict, producer_ids: set, pos: dict, args):
    """找收尾节点：清理语义 + 位置 + 判据质量；把「晚于哪些生产者 / 早于哪些」都算出来。"""
    out = []
    for t in plan.get("tasks") or []:
        for b in t.get("blocks") or []:
            if b.get("status") == "cancelled" and not args.include_cancelled:
                continue
            title = b.get("title") or ""
            cmds = "\n".join(b.get("cmds") or [])
            # 只在短字段里找清理语义：doc 往往是长篇散文，什么都提得到（第一版就在这误判过
            # —— lab-migration 的长 doc 让 8 个普通块被判成「收尾节点」）
            body = "\n".join([title, "\n".join(b.get("done_when") or []), cmds])
            strong = bool(CLEAN_TITLE_START.search(title) or CLEAN_TITLE_ANY.search(title)
                          or (CLEAN_VERB.search(body) and TEMPISH.search(body)))
            if not strong:
                continue
            ti, bi, tid = pos[b["id"]]
            out.append({
                "id": b["id"], "title": title, "task": tid, "status": b.get("status", ""),
                "pos": [ti, bi],
                "covered": sorted(p for p in producer_ids if p in pos and pos[p][:2] < (ti, bi)),
                "after_me": sorted(p for p in producer_ids if p in pos and pos[p][:2] > (ti, bi)),
                "ok_pos": not any(p in pos and pos[p][:2] > (ti, bi) for p in producer_ids),
                "has_done_when": bool(b.get("done_when")),
                "done_when": list(b.get("done_when") or []),
                "deletes": (bool(re.search(r"\brm\b|unlink|shred|删除|清除|清理|清空", cmds))
                            if cmds else None),
                "cmds": list(b.get("cmds") or [])})
    out.sort(key=lambda c: tuple(c["pos"]))
    return out


# ---------------------------------------------------------------- 建议

def next_task_id(plan: dict) -> str:
    n, ids = 1, {t["id"] for t in plan.get("tasks") or []}
    while f"T-{n:03d}" in ids:
        n += 1
    return f"T-{n:03d}"


def suggestions(plan: dict, evidence, cleanup):
    """给人/agent 抄的补齐步骤（只在缺件或要完善时才打印）。"""
    slug = plan.get("slug") or "<slug>"
    prod_blocks = sorted({e["block"] for e in evidence if e["block"] != "-"})
    prod_tasks = sorted({e["task"] for e in evidence if e["task"] != "-"})
    newt = next_task_id(plan)
    last_task = prod_tasks[-1] if prod_tasks else ""
    deps_blocks = f" --deps {' '.join(prod_blocks)}" if prod_blocks else ""
    out = []
    if not cleanup:
        out.append("1) 建收尾任务节点（这个 plan 里没有人负责清临时文件）：")
        out.append(f"     py task new {slug} --title \"清理本轮临时文件\" --owner <谁>"
                   + (f" --deps {last_task}" if last_task else ""))
        out.append("2) 在它下面建这一块，把清单与判据写进去：")
        out.append(f"     py block add {slug} --task {newt} --title \"删除本轮临时文件\" --kind impl \\")
        out.append(f"        --doc \"本轮产生的临时文件：<逐项列路径/glob>"
                   f"（产生自 {'、'.join(prod_blocks) or '<生产块>'}）\" \\")
        out.append(f"        --done_when \"逐项给出归属（已在别处存在 / 不再需要），"
                   f"删除后 test ! -e 为空\"{deps_blocks}")
    else:
        c = cleanup[0]
        out.append(f"1) 收尾节点 {c['id']}「{c['title']}」已经在，"
                   f"但它在流程上早于这些也在提临时文件的块：{short(c['after_me'])}")
        out.append("   要么把它移到它们之后（`block set_status` 改不了位置：用 `block expand` / `block compress` 或重建块），"
                   "要么确认那几个块不产生临时文件。")
        out.append(f"2) 补齐判据：{c['id']} 的 done_when "
                   f"{'是空的' if not c['has_done_when'] else '要逐项能核验'}"
                   f" —— 例：\"逐项证明内容已在别处存在（列出归属），删除后 test ! -e 为空\"")
    out.append("3) 声明：把「会产生哪些临时文件」写进生产块的 doc（一行就行），"
               "或让产物字段指到临时路径：")
    out.append(f"     py block set_doc {slug} <生产块 id> \"<原 doc>⏎临时文件：<路径/glob>\"")
    out.append("    # <值> 是整段替换，原 doc 别丢；只想改文档就用 block set_doc（不动状态）")
    return out


# ---------------------------------------------------------------- 主流程

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="check_plan_temp_hygiene.py",
        description="校验一份 plan 会不会留下没人清的临时文件（生产证据 / 声明 / 收尾节点）")
    ap.add_argument("plan", help="slug（在 plans 目录里找）或 plan.json / plan 目录的路径")
    ap.add_argument("--plans-root", default=None, help="plans 根目录（默认按本 profile 推断）")
    ap.add_argument("--strict", action="store_true",
                    help="把「写文件形态」（重定向 / mktemp / 转换器输出…）也算生产证据")
    ap.add_argument("--include-cancelled", action="store_true", help="连已取消的块一起看")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--evidence", action="store_true", help="把全部证据逐条列出（默认最多 8 条）")
    args = ap.parse_args(argv)

    plan, path = resolve_plan(args.plan, Path(args.plans_root) if args.plans_root else None)
    pos = positions(plan)
    all_ev = scan_evidence(plan, args)
    ev = all_ev if args.strict else [e for e in all_ev if e["tier"] == "strong"]
    decls = scan_declarations(plan, args)
    producers = {e["block"] for e in ev if e["block"] != "-"}
    cleanup = scan_cleanup(plan, producers, pos, args)
    good = [c for c in cleanup if c["ok_pos"]]
    warnings = []
    for c in good:
        if not c["has_done_when"]:
            warnings.append(f"收尾节点 {c['id']}「{c['title']}」没有可核验的判据（done_when 为空）"
                            f" —— 删没删干净没人能查")
        if c["cmds"] and not c["deletes"]:
            warnings.append(f"收尾节点 {c['id']}「{c['title']}」的命令里看不出删除动作")
    for c in cleanup:
        if not c["ok_pos"]:
            warnings.append(f"收尾节点 {c['id']}「{c['title']}」排在流程中段，"
                            f"晚于它、也在提临时文件的块：{short(c['after_me'])} —— 那些块产生的文件会留下")

    if not ev:
        verdict, approved = "➖ 无需清理（没检测到）", True
        note = ("没检测到会写临时/中间产物的形态（扫了 doc / done_when / cmds / 产物 / run / 日志）。"
                "注意：**这是「没查出来」，不等于「一定不产生」** —— 判据只看文本，"
                f"强形态 {len(STRONG)} 条、写文件形态 {len(WRITE_FORM)} 条（后者要 --strict 才算数）。")
    elif good and decls and not warnings:
        verdict, approved = "✅ 闭环", True
        note = (f"有生产（{len(ev)} 条证据）· 有声明（{len(decls)} 处）· "
                f"有排在生产者之后的收尾节点（{good[0]['id']}）")
    elif good and decls:
        verdict, approved = "⚠️ 部分", True
        note = (f"生产 {len(ev)} 条 · 声明 {len(decls)} 处 · 收尾节点 {good[0]['id']}"
                f"（有要完善的地方，见下）")
    elif cleanup and decls:
        verdict, approved = "⚠️ 部分", True
        note = (f"有声明（{len(decls)} 处）也有清理语义的块，但它排在流程中段、"
                f"晚于它还在提临时文件的块：{short(cleanup[-1]['after_me'])}")
    elif cleanup:
        verdict, approved = "⚠️ 部分", True
        note = (f"有清理语义的块（{cleanup[0]['id']}），但没人声明会产生哪些临时文件 —— "
                f"清是清了，清单没人写")
    elif decls:
        verdict, approved = "❌ 不闭环", False
        note = f"声明了 {len(decls)} 处临时文件，但整个 plan 里没有一个收尾节点删除它们 —— 文件会留下"
    else:
        verdict, approved = "❌ 不闭环", False
        note = "有生产证据，但既没人声明临时文件、也没有收尾节点删除它们"

    if args.json:
        print(json.dumps({"plan": plan.get("slug"), "path": str(path), "verdict": verdict,
                          "approved": approved, "note": note, "evidence": ev, "warnings": warnings,
                          "declarations": decls, "cleanup_nodes": cleanup,
                          "evidence_all_tiers": len(all_ev)}, ensure_ascii=False, indent=2))
        return EXIT_OK if approved else EXIT_FAIL

    print(f"plan: {plan.get('title') or plan.get('slug')}  ({plan.get('slug')})")
    print("判据：①会不会写出临时/中间产物 ②有没有声明 ③有没有排在生产者之后的收尾节点负责删除")
    print(f"结论：{verdict} —— {note}")
    if warnings:
        print("\n── ⚠️ 要完善的地方 ──")
        for w in warnings:
            print("  ! " + w)
    show = ev if args.evidence else ev[:8]
    if show:
        print(f"\n── 生产证据（{len(ev)} 条{'' if args.evidence else '，只列前 8'}）──")
        for e in show:
            tag = "已发生" if e["when"] == "actual" else "计划中"
            print(f"  [{e['tier']}/{tag}] {e['block']} {e['block_title'][:28]} · {e['source']}")
            print(f"        命中「{e['label']}」（{e['match']}）：{e['text']}")
    print(f"\n── 声明（{len(decls)} 处）──" if decls else "\n── 声明：没有（0 处）──")
    for d in decls:
        print(f"  {d['where']}：{d['what']}")
    print(f"\n── 收尾节点（{len(good)} 个位置正确 / {len(cleanup) - len(good)} 个位置偏早）──")
    for c in cleanup:
        flag = "✅" if c["ok_pos"] else "⚠️"
        tail = (f"覆盖生产块 {short(c['covered'])}" if c["ok_pos"]
                else f"晚于它的生产块：{short(c['after_me'])}")
        print(f"  {flag} {c['id']}「{c['title']}」[{c['status']}] · "
              f"判据 {len(c['done_when'])} 条 · {tail}")
    if not cleanup:
        print("  （没有）")
    if not approved or warnings:
        print("\n── 建议（复制执行，改完重跑本校验）──")
        for line in suggestions(plan, ev, cleanup):
            print("  " + line)
    return EXIT_OK if approved else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
