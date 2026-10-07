#!/usr/bin/env python3
"""check_plan_node_commands.py — 一份 plan 的「节点命令」校验器。

判据（口径来自用户 2026-10-07 定的规矩）：
  1. 每个任务节点（= 块；块是唯一能承载 doc / 判据 / 命令的单元）必须提供**可直接执行的命令**：
     至少一条命令形态的文本 —— 写在块内联命令出处里（优先 `cmds` 字段，其次 doc 的代码围栏，
     其次 doc / done_when 里的行内反引号）。
  2. 命令里出现的**每一个可替换变量**必须有明确来源：块 doc 里的定义行（`<名> = 值`）、
     块 `vars`、plan 级 `vars`、或同一块命令里的赋值（`P=…` / `export P=…`）。
  3. 不满足 → 不批准（退出码 1）。

输出：结论先行的一行判定 + 逐块证据（缺什么、在哪、怎么补）。命令可用 `--json` 取机器可读结果。

退出码：0 = 批准（✅ / 只有 ⚠️）· 1 = 不批准（有 ❌）· 2 = 用法错 · 4 = 找不到 plan
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PROFILE_HOME = HERE.parents[4]                 # scripts/ -> <skill>/ -> plan-weave/ -> skills/ -> <profile>
DEFAULT_PLANS_ROOT = PROFILE_HOME / "workspace" / "plans"

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_PLAN = 0, 1, 2, 4

# 本机/生态里常见的可执行程序（首词命中即视为「像真的能跑」）。不是白名单，只用来区分
# 「一条命令」和「一句伪代码」：认不出的首词只降到 ⚠️，不判 ❌。
KNOWN_PROGRAMS = {
    # 本 pack / Hermes / 数据层
    "plan.py", "py", "hermes", "dolt", "sqlite3", "zot", "jq", "yq",
    # 通用 shell 内建与工具
    "sh", "bash", "zsh", "cd", "echo", "printf", "export", "source", "set", "unset",
    "test", "true", "false", "read", "trap", "wait", "env", "nohup", "time", "watch", "xargs",
    "ls", "cp", "mv", "rm", "rmdir", "mkdir", "ln", "chmod", "chown", "touch", "stat", "file",
    "cat", "head", "tail", "less", "wc", "sort", "uniq", "cut", "tr", "tee", "diff", "cmp",
    "grep", "rg", "sed", "awk", "find", "which", "dirname", "basename", "realpath", "mktemp",
    "tar", "gzip", "gunzip", "zip", "unzip", "ditto", "hdiutil", "du", "df", "sync", "mount",
    "ps", "kill", "pkill", "pgrep", "launchctl", "defaults", "osascript", "open", "pbcopy",
    "shasum", "sha256sum", "md5", "md5sum", "openssl", "base64", "date", "sleep", "at", "cron",
    "gtimeout", "timeout", "perl", "python", "python3", "pip", "pip3", "uv", "mamba", "conda",
    "node", "npm", "npx", "deno", "bun", "ruby", "gem", "go", "cargo", "rustc", "make", "cmake",
    "gcc", "clang", "cc", "ld", "pkg-config", "brew", "port", "apt", "apt-get", "yum", "dnf",
    "systemctl", "service", "docker", "podman", "kubectl", "gh", "git", "git-annex", "annex",
    "ssh", "ssh-keygen", "ssh-copy-id", "scp", "sftp", "rsync", "curl", "wget", "nc", "ping",
    "dig", "nslookup", "host", "lsof", "netstat", "ss", "ifconfig", "ipconfig", "route",
    # 图像 / 文档 / 多媒体
    "sips", "convert", "magick", "ffmpeg", "ffprobe", "pandoc", "pdftoppm", "pdfinfo", "qpdf",
    "gs", "tesseract", "exiftool", "img2pdf", "textutil", "qlmanage", "screencapture",
    # 结构生物学 / SAXS / 组学（本用户常用）
    "pymol", "chimerax", "gnom", "dammin", "dammif", "damaver", "damfilt", "damsel", "damstart",
    "primus", "crysol", "crysolm", "datgnom", "datcmp", "datporod", "atsas", "raw", "bioxtasraw",
    "phenix", "cctbx.xfel", "ccp4", "aimless", "pointless", "xds", "xia2", "adxv", "hkl2000",
    "colabfold_batch", "alphafold", "boltz", "rfdiffusion", "bindcraft", "samtools", "bcftools",
    "bwa", "minimap2", "blastp", "blastn", "makeblastdb", "mafft", "muscle", "iqtree", "gmx",
    "vmd", "namd", "openmm", "reduce", "pdb2pqr", "fpocket", "autodock", "vina", "gromacs",
    "dssp", "mkdssp", "pdb-tools", "biopython", "Rscript", "R",
}

RE_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
RE_INLINE = re.compile(r"`([^`\n]+)`")
RE_SEG = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")
RE_ASSIGN = re.compile(r"(?:^|[;&|]\s*|\s)(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
RE_ANGLE = re.compile(r"<([^<>\n]{1,60})>")
RE_DOLLAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
RE_BRACE = re.compile(r"\{\{\s*([^{}\n]{1,60}?)\s*\}\}")
RE_CN = re.compile(r"[\u4e00-\u9fff]")
RE_NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]*$")
RE_LC_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[_.+-][a-z0-9]+)*$")   # 小写程序名形态（真命令的常态）
RE_TREE = re.compile(r"^[\s│├└┌┗┏━─┃·|+*｡•‣·]*(│|├|└|┌|┗|┏|━|─|┃)")
AMBIENT_ENV = {                      # 环境自带、不需要人替换的变量（不是「可替换变量」）
    "HOME", "USER", "LOGNAME", "PWD", "OLDPWD", "TMPDIR", "TEMP", "TMP", "SHELL", "PATH",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "HOSTNAME", "HOST", "TZ", "OSTYPE", "RANDOM",
    "EDITOR", "VISUAL", "PAGER", "DISPLAY", "SECONDS", "SHLVL", "IFS",
    "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONPATH",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
}
EMPTY_WORDS = ("待定", "待补", "todo", "tbd", "见上", "同上", "略", "任意", "随便", "自己填",
               "视情况", "稍后", "稍候", "n/a", "na", "xxx", "无", "-", "…", "...")


# ---------------------------------------------------------------- plan 读取

def resolve_plan(arg: str, plans_root: Path | None):
    """arg 可以是 slug、plan.json 的路径、或 plan 目录。返回 (plan, path)。"""
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


def iter_blocks(plan: dict):
    for t in plan.get("tasks") or []:
        for b in t.get("blocks") or []:
            yield t, b


# ---------------------------------------------------------------- 命令识别

def segments(line: str):
    return [s for s in (x.strip() for x in RE_SEG.split(line)) if s]


def first_token(seg: str):
    """取命令段的「程序名」——跳过变量赋值前缀与外壳命令。"""
    toks = seg.split()
    i = 0
    while i < len(toks) and re.fullmatch(r"(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*=\S*", toks[i]):
        i += 1
    while i < len(toks) and toks[i] in {"env", "nohup", "time", "caffeinate", "arch"}:
        i += 1
    if i >= len(toks):
        return None
    tok = toks[i].strip("\"'")
    return tok or None


def classify(seg: str, check_which: bool) -> str:
    """判断一个命令分段有多像「一条真命令」。

    known = 首词在已知程序表里（或用 PATH 探到了）
    path  = 首词是路径形态（/x、./x、~/x）或脚本名（.py/.sh/…）
    var   = 首词是变量（"$P" …）—— 单独的 `$VAR` 不算命令，要有第二段才算
    maybe = 首词是小写程序名形态（可能在别的机器上 / 本机没装）—— 只在 ≥2 段时才算
    none  = 其它：中文、伪代码、文件名、单 token 的散文词、目录树行
    """
    toks = seg.split()
    tok = first_token(seg)
    if tok is None:
        return "none"
    n = len(toks)
    if tok.startswith("$"):
        return "var" if n >= 2 else "none"
    if tok in KNOWN_PROGRAMS:
        return "known"
    if tok.startswith(("/", "./", "~/", "../")) or tok.endswith((".py", ".sh", ".pl", ".rb", ".js")):
        return "path"
    if RE_LC_NAME.match(tok):
        if check_which and shutil.which(tok):
            return "known"
        return "maybe" if n >= 2 else "none"
    return "none"


class Cmd:
    __slots__ = ("text", "source", "loc")

    def __init__(self, text, source, loc):
        self.text, self.source, self.loc = text, source, loc


def candidates_from_text(text: str, source: str):
    """doc / done_when 里抽候选命令：先围栏，再行内反引号。"""
    out = []
    for i, m in enumerate(RE_FENCE.finditer(text), 1):
        buf = ""
        for ln in m.group(1).splitlines():
            if not ln.strip():
                if buf.strip():
                    out.append((buf, f"{source} 围栏#{i}"))
                buf = ""
                continue
            buf = f"{buf} {ln.strip()}" if buf else ln.strip()
            buf = buf.rstrip("\\").rstrip()          # 续行符吃掉，拼成一条完整命令
            if not ln.rstrip().endswith("\\"):
                out.append((buf, f"{source} 围栏#{i}"))
                buf = ""
        if buf.strip():
            out.append((buf, f"{source} 围栏#{i}"))
    strip_rest = RE_FENCE.sub("\n", text)
    for m in RE_INLINE.finditer(strip_rest):
        out.append((m.group(1), f"{source} 反引号"))
    return out


def extract_commands(block: dict, check_which: bool):
    """返回 (commands, csr) —— csr 是「像命令但不是命令」的候选数（供 ⚠️ 提示用）。"""
    cmds, skipped = [], 0
    for i, raw in enumerate(block.get("cmds") or [], 1):
        s = (raw or "").strip()
        if s:
            cmds.append(Cmd(s, f"cmds[{i}]", i))
    text_sources = [((block.get("doc") or ""), "doc")]
    if block.get("done_when"):
        text_sources.append(("\n".join(block["done_when"]), "done_when"))
    for text, name in text_sources:
        if not text.strip():
            continue
        for raw, loc in candidates_from_text(text, name):
            line = raw.strip()
            if not line or line.startswith("#") or RE_TREE.match(line):
                continue
            line = re.sub(r"^[>$]\s+", "", line)
            if not line:
                continue
            kinds = [classify(s, check_which) for s in segments(line)]
            if not kinds:
                continue
            if any(k in {"known", "path", "var", "maybe"} for k in kinds):
                cmds.append(Cmd(line, loc, raw))
            else:
                skipped += 1
    # 去重（同一条命令在 doc 里出现两次只报一次），保留最先出现的出处
    seen, uniq = set(), []
    for c in cmds:
        if c.text not in seen:
            seen.add(c.text)
            uniq.append(c)
    return uniq, skipped


# ---------------------------------------------------------------- 变量

def var_definitions(plan: dict, block: dict):
    """名字 -> (出处, 定义文本)。三处：block.vars / plan.vars / doc 里的定义行。"""
    out = {}
    for src, holder in (("plan.vars", plan.get("vars") or {}), ("block.vars", block.get("vars") or {})):
        if isinstance(holder, dict):
            items = holder.items()
        else:                                          # 也接受 ["名=值", ...] 形态
            items = []
            for it in holder or []:
                k, _, v = str(it).partition("=")
                items.append((k.strip(), v.strip()))
        for k, v in items:
            if str(k).strip():
                out.setdefault(str(k).strip(), (src, str(v).strip()))
    doc = block.get("doc") or ""
    for name in set(list_defs_candidates(doc)):
        for pat in (r"={1}", r"＝", r"：", r":", r"→", r"=>"):
            m = re.search(r"(?:^|[\s`（(【\[<{\"'])" + re.escape(name)
                          + r"\s*(?:\}|>|\})?>?\s*" + pat + r"\s*(\S[^\n]*)", doc, re.M)
            if m and m.group(1).strip():
                out.setdefault(name, ("doc 定义行", m.group(1).strip()))
                break
    return out


def list_defs_candidates(doc: str):
    """doc 里「像变量名」的词：反引号 / 尖括号 / $ 形态里出现的短标识符。"""
    names = set()
    for m in re.finditer(r"[`<（(\[\"'{]{1,2}\$?\{?([A-Za-z_][A-Za-z0-9_.\-]{0,40})\}?[>`）)\]\"'}]{1,2}", doc):
        names.add(m.group(1))
    for m in re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", doc):
        names.add(m.group(1))
    for m in re.finditer(r"^\s*(?:var|变量)\s*[:：]?\s*([A-Za-z_][A-Za-z0-9_.\-]{0,40})", doc, re.M):
        names.add(m.group(1))
    return names


def placeholders(text: str):
    """返回 [(显示名, 原名, 种类)]，种类 ∈ angle / angle_cn / dollar / brace。"""
    out = []
    for m in RE_ANGLE.finditer(text):
        name = m.group(1).strip()
        kind = "angle_cn" if RE_CN.search(name) else "angle"
        out.append((m.group(0), name, kind))
    for m in RE_DOLLAR.finditer(text):
        out.append((m.group(0), m.group(1) or m.group(2), "dollar"))
    for m in RE_BRACE.finditer(text):
        out.append((m.group(0), m.group(1), "brace"))
    return out


def is_empty_word(v: str) -> bool:
    t = v.strip().strip("`\"'。.(").lower()
    return (not t) or t in EMPTY_WORDS or len(t) <= 1


# ---------------------------------------------------------------- 校验

def check_block(plan: dict, task: dict, block: dict, args):
    cmds, skipped = extract_commands(block, not args.no_which)
    res = {"id": block["id"], "title": block.get("title", ""), "kind": block.get("kind", ""),
           "status": block.get("status", ""), "owner": block.get("owner", ""),
           "task": task["id"], "commands": [], "fails": [], "warns": [], "skipped": skipped}
    if not cmds:
        res["fails"].append({
            "kind": "no_command", "msg": "doc / done_when / cmds 里都没有任何命令形态的文本",
            "evidence": "扫过：cmds 字段（无）· doc（%d 字）· done_when（%d 条）"
                        % (len(block.get("doc") or ""), len(block.get("done_when") or []))})
        return res

    defs = var_definitions(plan, block)
    assign = set()
    for c in cmds:
        assign |= {m.group(1) for m in RE_ASSIGN.finditer(c.text)}
    for c in cmds:
        segs = [s for s in segments(c.text)]
        kinds = [classify(s, not args.no_which) for s in segs]
        kinds = [k for k in kinds if k]
        res["commands"].append({"text": c.text, "source": c.source})
        # 未知首词 / 只有赋值 → ⚠️
        if kinds and all(k == "maybe" for k in kinds):
            res["warns"].append({
                "kind": "unknown_program",
                "msg": "首词 %r 不在已知程序表里、本机 PATH 也找不到（可能只在别的机器上，或这是伪代码）"
                       % (first_token(segs[0]) or ""),
                "evidence": c.text[:160], "source": c.source})
        bare = [t for t in (first_token(sg) for sg in segs)
                if t and not t.startswith(("/", "./", "~/", "../"))
                and t.endswith((".py", ".sh", ".pl", ".rb", ".js")) and not shutil.which(t)]
        if bare and not args.no_which:
            res["warns"].append({
                "kind": "bare_script",
                "msg": "脚本名 %r 没带路径（照抄粘贴会 command not found；写成 ./%s 或绝对路径）"
                       % (bare[0], bare[0]),
                "evidence": c.text[:160], "source": c.source})
        if kinds and "none" in kinds and "known" not in kinds and "path" not in kinds:
            res["warns"].append({
                "kind": "not_runnable",
                "msg": "这段里有的分段首词既不是程序名也不是路径（像中文/伪代码）",
                "evidence": c.text[:160], "source": c.source})
        for disp, name, pkind in placeholders(c.text):
            if pkind == "angle_cn":
                res["fails"].append({
                    "kind": "hole", "msg": "占位符 %s 是描述而不是变量名（填不进去）" % disp,
                    "evidence": c.text[:160], "source": c.source,
                    "fix": "换成有明确取值的变量名，并在块 doc 里给一行定义"})
                continue
            if name in assign or name in AMBIENT_ENV:
                continue
            if name in defs:
                src, val = defs[name]
                if is_empty_word(val):
                    res["warns"].append({
                        "kind": "empty_def", "msg": "变量 %s 的定义是空的/没说是什么（%s：%r）"
                                                    % (disp, src, val[:60]),
                        "evidence": c.text[:160], "source": c.source})
                elif placeholders(val):
                    res["warns"].append({
                        "kind": "def_has_placeholder",
                        "msg": "变量 %s 的定义里还有占位符（%s：%r）" % (disp, src, val[:60]),
                        "evidence": c.text[:160], "source": c.source})
                continue
            res["fails"].append({
                "kind": "undef_var",
                "msg": "变量 %s 没有定义（plan 级 / 块级 vars、块 doc 的定义行、同块赋值里都没有）" % disp,
                "evidence": c.text[:160], "source": c.source,
                "fix": "在块 doc 加一行：`%s = <取值或取值方式>`（或 plan 级 vars）" % name})
    return res


def build(plan: dict, args):
    rows = []
    for t, b in iter_blocks(plan):
        if b.get("status") == "cancelled" and not args.include_cancelled:
            continue
        if args.only and args.only not in (b["id"], b["id"].split("#")[1]) and args.only != t["id"]:
            continue
        rows.append(check_block(plan, t, b, args))
    return rows


def report(plan: dict, rows, args):
    blocks = len(rows)
    bad = [r for r in rows if r["fails"]]
    warn = [r for r in rows if not r["fails"] and r["warns"]]
    good = [r for r in rows if not r["fails"] and not r["warns"]]
    no_cmd = sum(1 for r in bad if any(f["kind"] == "no_command" for f in r["fails"]))
    undef = sum(1 for r in bad if any(f["kind"] == "undef_var" for f in r["fails"]))
    holes = sum(1 for r in bad if any(f["kind"] == "hole" for f in r["fails"]))
    print(f"plan: {plan.get('title') or plan.get('slug')}  ({plan.get('slug')})")
    print("判据：每块 ≥1 条可直接执行的命令；命令里每个可替换变量必须有明确定义")
    print(f"结论：{'✅ 批准' if not bad else '❌ 不批准'}"
          f" —— 块 {blocks} · ✅ {len(good)} · ⚠️ {len(warn)} · ❌ {len(bad)}"
          f"（缺命令 {no_cmd} · 变量未定义 {undef} · 占位符填不进去 {holes}）")
    if bad:
        print("\n── ❌ 不通过的块 ──")
        for r in bad:
            print(f"  {r['id']}  {r['title']}  [{r['kind']}/{r['status']}] @{r['owner'] or '未指派'}")
            for f in r["fails"]:
                print(f"      ✗ {f['msg']}")
                if f.get("source"):
                    print(f"        出处：{f['source']}")
                print(f"        证据：{f['evidence']}")
                if f.get("fix"):
                    print(f"        怎么补：{f['fix']}")
    if warn:
        print("\n── ⚠️ 通过但有疑点 ──")
        for r in warn:
            print(f"  {r['id']}  {r['title']}")
            for w in r["warns"]:
                print(f"      ! {w['msg']}")
                if w.get("source"):
                    print(f"        出处：{w['source']} · 证据：{w['evidence']}")
    if args.verbose and good:
        print("\n── ✅ 通过 ──")
        for r in good:
            src = ", ".join(sorted({c["source"] for c in r["commands"]})[:3])
            print(f"  {r['id']}  命令 {len(r['commands'])} 条（{src}）")
    if bad:
        print(f"\n补法：把命令写进块 doc 的 ```bash 围栏，并给每个变量一行定义 —— "
              f"`plan.py set {plan.get('slug')} <块 id> <当前状态> --doc \"<原 doc + 命令段>\"`；"
              f"改完重跑本校验，exit 0 才算批准。")
    return EXIT_FAIL if bad else EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check_plan_node_commands.py",
                                 description="校验一份 plan 的每个块有没有可直接执行的命令、变量有没有定义")
    ap.add_argument("plan", help="slug（在 plans 目录里找）或 plan.json / plan 目录的路径")
    ap.add_argument("--plans-root", default=None, help="plans 根目录（默认按本 profile 推断）")
    ap.add_argument("--only", default="", help="只看某个任务/块（T-003 或 T-003#B-002 或 B-002）")
    ap.add_argument("--include-cancelled", action="store_true", help="连已取消的块一起看")
    ap.add_argument("--no-which", action="store_true", help="不用 PATH 探测首词（跨机器跑时更稳）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--verbose", action="store_true", help="把通过的块也列出来")
    args = ap.parse_args(argv)
    plan, path = resolve_plan(args.plan, Path(args.plans_root) if args.plans_root else None)
    rows = build(plan, args)
    if not rows:
        print("没有可校验的块（plan 里没有块，或 --only 之类的过滤把块排空了）", file=sys.stderr)
        return EXIT_FAIL
    if args.json:
        bad = [r for r in rows if r["fails"]]
        print(json.dumps({"plan": plan.get("slug"), "path": str(path),
                          "approved": not bad, "blocks": len(rows),
                          "fails": len(bad),
                          "warns": sum(1 for r in rows if not r["fails"] and r["warns"]),
                          "rows": rows}, ensure_ascii=False, indent=2))
        return EXIT_FAIL if bad else EXIT_OK
    return report(plan, rows, args)


if __name__ == "__main__":
    sys.exit(main())
