"""图形界面（Tkinter）。

刻意不引入任何第三方 UI 库：Tkinter 是 Python 标准库，打包后不增加
体积，也不会像 PySide6 那样让 exe 凭空多出 80MB。代价是要自己写样式，
所以有 `theme.py`。
"""
from .window import MainWindow, launch

__all__ = ["MainWindow", "launch"]
