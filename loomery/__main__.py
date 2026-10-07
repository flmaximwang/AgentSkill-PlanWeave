"""`python -m loomery <子命令>` 的入口（等价于 `loomery <子命令>`）。"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
