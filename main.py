#!/usr/bin/env python3
"""zhsgo 入口。

    python main.py -c 1919
    python main.py --fetch
    python main.py --dry-run
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zhsgo.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
