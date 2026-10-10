#!/usr/bin/env python3
"""zhs-ghost 图形界面入口。

    python gui.py                 打开窗口
    python gui.py --selfcheck     组件自检（不开窗口）

打包后是 zhs-ghost-gui.exe —— 带参数时它表现得和命令行版一样，
不带参数才开窗口。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _prepare_streams() -> None:
    """windowed exe 没有 stdout/stderr，`print` 会直接抛异常。

    先从命令行启动的话可以接管父进程的控制台（AttachConsole），
    拿不到就退化成丢弃 —— 至少不会因为一句 print 崩掉。
    """
    if sys.platform == "win32" and sys.stdout is None:
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        except Exception:
            pass

    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass


def main() -> int:
    argv = sys.argv[1:]
    if argv:
        # GUI 版保留完整命令行能力：--selfcheck / --dry-run / -c ...
        # 这样用户排查问题时不需要再下一个命令行版。
        _prepare_streams()
        from zhsgo.cli import main as cli_main

        return cli_main(argv)

    from zhsgo.gui import launch

    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
