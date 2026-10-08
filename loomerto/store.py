"""存储层：一份 plan 的所有磁盘读写（目录定位 / 原子落盘 / 三个视图的同步）。

`commit()` 是唯一的写入漏斗（未来画布写回 R-02、状态校验 R-04/R-05 都挂在这里），
所以「json 是唯一真相、三个视图永远派生」这条纪律只需要在一个地方守。

定位**不猜、也不认任何 harness**：`--plan <plan 数据文件>` 直接指定那一份；要给一份 plan 库就
`--plans-root <目录>`；两个都没给时只看当前目录有没有 `plan.json`。loomerto 里没有
「Hermes profile」这类概念 —— 路径由调用方（人 / skill 的 shim / 别的 harness）显式交给它。
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from .model import PlanError, now
from . import model
from . import render

# 本包所在的目录（模板是包数据，跟着包走）
_SELF = Path(__file__).resolve()
TEMPLATE = Path(os.environ.get("LOOMERTO_TEMPLATE") or (_SELF.parent / "assets" / "plan.html"))


# 嵌入方（skill 薄壳 / 某个 harness）import 之后可以直接设它，给「这份 plan 库在哪」兜底；
# 显式环境变量与 CLI 旗标都优先于它（见 plans_root 的顺序）
EMBEDDED_PLANS_ROOT = ""

# 显式指定的**那一份 plan 数据文件**（`--plan` / `$LOOMERTO_PLAN_FILE`）：给了它就只认这一份，
# plans_root / slug 都不再参与定位（视图 PLAN.md / plan.html / plan.canvas 与数据文件同目录）。
PLAN_FILE = ""


def plan_file() -> str:
    """当前指定的 plan 数据文件（显式赋值优先，其次 `$LOOMERTO_PLAN_FILE`）；没指定就返回空串。"""
    return (PLAN_FILE or os.environ.get("LOOMERTO_PLAN_FILE") or "").strip()


def plans_root():
    """多份 plan 的目录：`$LOOMERTO_PLANS_ROOT` → 调用方塞的 `EMBEDDED_PLANS_ROOT`；都没给 ⇒ `None`。

    **loomerto 不推断任何 harness 的目录**（它可能装在 site-packages 里，离任何 harness 都远）——
    这份 plan 库在哪，由调用方显式给（`--plans-root` 或环境变量）。
    """
    env = (os.environ.get("LOOMERTO_PLANS_ROOT") or "").strip()
    if env:
        return Path(env).expanduser()
    if EMBEDDED_PLANS_ROOT:
        return Path(EMBEDDED_PLANS_ROOT).expanduser()
    return None


def file_mode() -> bool:
    """单文件模式？给了 `--plan`/`$LOOMERTO_PLAN_FILE` ⇒ 是；

    什么都没给、而当前目录正好有一份 `plan.json` ⇒ 也是（等价于 `--plan ./plan.json`）。
    """
    if plan_file():
        return True
    if plans_root() is not None:
        return False
    return (Path.cwd() / "plan.json").exists()


_NO_LOCATION = (
    "不知道去哪找 plan。任选一条：\n"
    "  · loomerto --plan <plan 数据文件> <子命令>            # 只认这一份\n"
    "  · loomerto --plans-root <目录> <子命令> <slug>       # 一份库里有好几份\n"
    "  · 在本目录放一份 plan.json（不给旗标时按它算）\n"
    "新建：loomerto --plan <路径>/plan.json new <slug> --title \"…\"")


def plan_path(slug: str = "") -> Path:
    """这一份 plan 的**数据文件**路径（默认就叫 `plan.json`）。

    顺序：`--plan <文件|目录>` → 当前目录的 `plan.json`（没给库目录、且它存在时）
    → `<plans_root>/<slug>/plan.json`。哪一条都指不到 ⇒ `PlanError`（把该给什么说清楚）。
    """
    f = plan_file()
    if f:
        p = Path(f).expanduser()
        return p / "plan.json" if p.is_dir() else p
    root = plans_root()
    if root is None:
        cwd = Path.cwd() / "plan.json"
        if cwd.exists():
            return cwd
        raise PlanError(_NO_LOCATION)
    if not slug:
        raise PlanError(f"{root} 里可能有好几份 plan —— 要给 slug："
                        f"`loomerto --plans-root {root} <子命令> <slug>`（或 `--plan <数据文件>`）")
    return root / slug / "plan.json"


def plan_dir(slug: str) -> Path:
    """plan 目录：数据文件与三个视图同住的地方（`--plan` 给文件时就是它所在的目录）。"""
    return plan_path(slug).parent


def load(slug: str) -> dict:
    p = plan_path(slug)
    if not p.exists():
        raise PlanError(f"找不到 plan 数据文件（{p}）"
                        + ("" if plan_file() else f" —— slug '{slug}'")
                        + f"。用 `loomerto --plan {p} new {slug or '<slug>'} --title ...` 建一个。")
    plan = json.loads(p.read_text(encoding="utf-8"))
    # 老数据缺键在这里补齐（只补不改、不落盘）：读到的块总是完整形状，读者不必各自 `.get()`
    # 兜着。落盘与否由调用方决定 —— 下一次 `commit()` 顺手材料化（语义不变）。
    normalize(plan)
    return plan


def normalize(plan: dict) -> dict:
    """把一份 plan 里每个块按 `model.BLOCK_FIELDS` 补齐缺键（只补不改）。返回 `{块 id: 补了哪些键}`。"""
    return model.normalize_plan(plan)


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
    p = plan_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(p, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")


def commit(slug: str, plan: dict, a=None) -> None:
    """落盘 + 同步刷新三个视图，保证 html/canvas/md 永不落后于 plan.json。

    顺手换一个 `rev`（版本号）：写回方靠它认「我读的是哪一版」。**不能用 `updated_at` 当版本号** ——
    秒级时间戳在同一秒里的两次写入会撞成同一个值（画布上连着改两下就会漏掉冲突）。
    """
    plan["rev"] = uuid.uuid4().hex[:12]
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
