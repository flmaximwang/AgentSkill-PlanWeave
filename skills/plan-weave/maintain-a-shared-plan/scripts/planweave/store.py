"""存储层：一份 plan 的所有磁盘读写（目录定位 / 原子落盘 / 三个视图的同步）。

`commit()` 是唯一的写入漏斗（未来画布写回 R-02、状态校验 R-04/R-05 都挂在这里），
所以「json 是唯一真相、三个视图永远派生」这条纪律只需要在一个地方守。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .model import PlanError, now
from . import render

# 目录：<profile home>/workspace/plans/<slug>/（本文件在 <skill>/scripts/planweave/ 下）
_SELF = Path(__file__).resolve()
PROFILE_HOME = _SELF.parents[5]      # planweave/ -> scripts/ -> <skill>/ -> <cat>/ -> skills/ -> profile home
PLANS_ROOT = PROFILE_HOME / "workspace" / "plans"
TEMPLATE = _SELF.parents[2] / "assets" / "plan.html"

def plan_dir(slug: str) -> Path:
    return PLANS_ROOT / slug

def load(slug: str) -> dict:
    p = plan_dir(slug) / "plan.json"
    if not p.exists():
        raise PlanError(f"找不到 plan '{slug}'（{p}）。用 `plan.py new {slug} --title ...` 建一个。")
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

def render_all(slug: str, plan: dict | None = None):
    plan = plan or load(slug)
    d = plan_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write(d / "PLAN.md", render.render_md(plan))
    atomic_write(d / "plan.canvas", render.render_canvas(plan))
    atomic_write(d / "plan.html", render.render_html(plan, TEMPLATE))
    return d
