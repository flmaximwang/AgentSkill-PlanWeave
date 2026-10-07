#!/usr/bin/env python3
"""plan.py — loomerto 在 **skill 这一侧**的入口（薄壳）。

loomerto 是一个 python 包（仓库根目录的 loomerto/）；这个壳只做三件事：

1. **找到包**：checkout 里的 `<home>/loomerto`（改的是哪份，跑的就是哪份）→ `$LOOMERTO_HOME`
   → 已安装的 `import loomerto` → 已装好的 `loomerto` 命令（把进程交给它）。
2. **把「本 skill 所在 home」的 plans 根交给包**：`<home>/workspace/plans`。在 profile 里装着的 skill
   ⇒ 那就是这个 profile 的 plans；在仓库 checkout 里跑 ⇒ 那就是 `<repo>/workspace/plans`（本机自测用）。
   包自己不猜路径 —— 它可能装在 site-packages 里，离任何 profile 都远。
   交代方式有两种，都不覆盖调用方的显式选择（`--plan` / `--plans-root` / 同名环境变量仍优先）：
   - 进程内：给包设 `store.EMBEDDED_PLANS_ROOT`；
   - 交给 CLI：在 argv 前面补 `--plans-root <路径>`（调用方自己给过就不补）。
3. 调 `loomerto.cli.main()`，退出码原样透传。

四条都不成立时，明确告诉你该装哪一条，而不是抛一个看不懂的 ImportError。
"""

from __future__ import annotations

import os
import pathlib
import sys

_SELF = pathlib.Path(__file__).resolve()
# scripts/ -> <skill>/ -> <cat>/ -> skills/ -> <home>（profile 里 = profile home；checkout 里 = 仓库根）
_HOME = _SELF.parents[4]
_PLANS = str(_HOME / "workspace" / "plans")

_NO_PACKAGE = """\
找不到 loomerto 包。装它（任选一条）：
  uv tool install --editable {home}       # 推荐：装出 loomerto / plan 命令，代码跟着 checkout 走
  python3 -m pip install --user -e {home} # 让这台机器的 python3 直接 import 到它（旧 pip 装不了 editable 就用上面那条）
  python3 -m pip install loomerto          # 从 PyPI 装发行版
或者把 checkout 路径告诉这个壳：LOOMERTO_HOME=/path/to/repo python3 {self} <子命令> …\
"""


def _find_package() -> bool:
    """checkout 优先 → $LOOMERTO_HOME → 已安装的 import。找到就往 sys.path 或环境里落好。"""
    for cand in (_HOME, os.environ.get("LOOMERTO_HOME", "")):
        if cand and (pathlib.Path(cand) / "loomerto" / "__init__.py").is_file():
            sys.path.insert(0, str(cand))
            return True
    try:
        import loomerto  # noqa: F401
        return True
    except ImportError:
        return False


def _hand_off_to_cli() -> None:
    """包已装成命令：把进程交给它，并把本 skill 的 plans 根带过去。"""
    import shutil

    args = sys.argv[1:]
    gave = any(a in ("--plan", "--plans-root")
               or a.startswith(("--plan=", "--plans-root=")) for a in args)
    if not gave:
        args = ["--plans-root", _PLANS] + args
    for exe in (shutil.which("loomerto"), str(pathlib.Path.home() / ".local" / "bin" / "loomerto")):
        if exe and pathlib.Path(exe).is_file():
            os.execv(exe, [exe] + args)


def _bootstrap() -> None:
    if not _find_package():
        _hand_off_to_cli()          # 有命令就交给它；没有就往下走到报错
        print(_NO_PACKAGE.format(home=_HOME, self=_SELF), file=sys.stderr)
        sys.exit(2)
    from loomerto import store  # noqa: E402

    store.EMBEDDED_PLANS_ROOT = _PLANS


_bootstrap()

from loomerto.cli import main  # noqa: E402  （必须在 _bootstrap 之后）

if __name__ == "__main__":
    sys.exit(main())
