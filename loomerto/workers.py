"""子代理线程探活：只读转录文件与同目录的 manifest.json，给出七种结论。

**转录在哪由调用方登记**（`exec … --transcript <路径>`）—— 这个模块不猜任何 harness 的目录，
也不读库、不连网，所以跨机器都能跑。代价：它说不出「进程死没死」，只能说「转录还在写吗 /
manifest 说结束了吗」——要更硬的判活，去线程所在的那个 harness 里问它自己的 `delegate_task`。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


# 七种结论
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
    if not tp:
        return "unreachable", (f"只记了线程号（{deleg or '?'}#{idx}），没登记转录路径 —— 看不到这条线程"
                               f"（登记时给 `--transcript <路径>` 才能读）"), []
    p = Path(tp)
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
