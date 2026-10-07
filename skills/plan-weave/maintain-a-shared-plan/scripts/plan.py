#!/usr/bin/env python3
"""plan.py — CLI 入口（薄壳）。

实现全在同目录的 `planweave/` 包里；这个壳只做两件事：把本目录塞进 `sys.path`、调 `cli.main()`。
别的 harness 不必经过命令行 —— `from planweave import store` 就能读写同一份 plan.json。
包内分工与跨 harness 约定见 `planweave/__init__.py`。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from planweave.cli import main  # noqa: E402  （必须先插 sys.path）

if __name__ == "__main__":
    sys.exit(main())
