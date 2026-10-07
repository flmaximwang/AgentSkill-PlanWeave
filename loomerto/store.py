"""存储层：一份 plan 的所有磁盘读写（目录定位 / 原子落盘 / 三个视图的同步）。

`commit()` 是唯一的写入漏斗（未来画布写回 R-02、状态校验 R-04/R-05 都挂在这里），
所以「json 是唯一真相、三个视图永远派生」这条纪律只需要在一个地方守。

plan 目录**不靠猜**：`plans_root()` 先看 `$LOOMERTO_PLANS_ROOT`，再看 `$LOOMERTO_PROFILE`，
最后落到 `~/.hermes/workspace/plans`。包可能装在 site-packages 里，离任何 profile 都远 ——
profile 的位置由调用方显式交给它（skill 里的 shim 就是这么做的）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .model import PlanError, now
from . import render

# 本包所在的目录（模板是包数据，跟着包走）
_SELF = Path(__file__).resolve()
TEMPLATE = Path(os.environ.get("LOOMERTO_TEMPLATE") or (_SELF.parent / "assets" / "plan.html"))


# 嵌入方（skill 薄壳 / 某个 harness）import 之后可以直接设它，给「这份 plan 库在哪」兜底；
# 显式环境变量与 CLI 旗标都优先于它（见 plans_root 的顺序）
EMBEDDED_PLANS_ROOT = ""


def plans_root() -> Path:
    """plan 目录：`$LOOMERTO_PLANS_ROOT` → `$LOOMERTO_PROFILE` → `EMBEDDED_PLANS_ROOT` → `~/.hermes/workspace/plans`。"""
    env = (os.environ.get("LOOMERTO_PLANS_ROOT") or "").strip()
    if env:
        return Path(env).expanduser()
    base = Path.home() / ".hermes"
    prof = (os.environ.get("LOOMERTO_PROFILE") or "").strip()
    if prof:
        return base / "profiles" / prof / "workspace" / "plans"
    if EMBEDDED_PLANS_ROOT:
        return Path(EMBEDDED_PLANS_ROOT).expanduser()
    return base / "workspace" / "plans"


def plan_dir(slug: str) -> Path:
    return plans_root() / slug


def load(slug: str) -> dict:
    p = plan_dir(slug) / "plan.json"
    if not p.exists():
        raise PlanError(f"找不到 plan '{slug}'（{p}）。用 `loomerto new {slug} --title ...` 建一个。")
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
