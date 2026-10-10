"""基础小部件：卡片、键值行、状态徽章、可滚动容器。

Tkinter 没有圆角和阴影，这里用 1px 描边 + 留白来做出层次感。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from .theme import PALETTE as P
from .theme import fonts


class Card(tk.Frame):
    """白底描边容器，可选标题。"""

    def __init__(self, parent: tk.Misc, title: str = "", pad: tuple = (16, 14)):
        super().__init__(parent, bg=P["card"], highlightbackground=P["border"],
                         highlightcolor=P["border"], highlightthickness=1, bd=0)
        self._pad = pad
        if title:
            tk.Label(self, text=title, bg=P["card"], fg=P["muted"],
                     font=fonts()["small"], anchor="w").pack(
                fill="x", padx=pad[0], pady=(pad[1] - 2, 0))
            self.body = tk.Frame(self, bg=P["card"])
            self.body.pack(fill="both", expand=True, padx=pad[0], pady=(6, pad[1]))
        else:
            self.body = tk.Frame(self, bg=P["card"])
            self.body.pack(fill="both", expand=True, padx=pad[0], pady=pad[1])


class KeyValue(tk.Frame):
    """左标签右值的一行。`set()` 只更新值，避免整页重绘。"""

    def __init__(self, parent: tk.Misc, key: str, value: str = "-", width: int = 12):
        super().__init__(parent, bg=P["card"])
        tk.Label(self, text=key, bg=P["card"], fg=P["muted"], font=fonts()["small"],
                 width=width, anchor="w").pack(side="left")
        self._var = tk.StringVar(value=value)
        self._label = tk.Label(self, textvariable=self._var, bg=P["card"], fg=P["text"],
                               font=fonts()["base"], anchor="w", justify="left")
        self._label.pack(side="left", fill="x", expand=True)

    def set(self, value: Any, color: Optional[str] = None) -> None:
        self._var.set(str(value))
        self._label.configure(fg=color or P["text"])


class Badge(tk.Label):
    """圆角状态徽章（用带内边距的 Label 模拟）。"""

    def __init__(self, parent: tk.Misc, text: str, state: str = "idle"):
        super().__init__(parent, text=text, font=fonts()["small"], bd=0,
                         padx=10, pady=3)
        self.set(text, state)

    def set(self, text: str, state: str = "idle") -> None:
        colors = {
            "idle": (P["muted"], "#eef0f3"),
            "running": (P["accent"], P["accent_soft"]),
            "ok": (P["ok"], P["ok_soft"]),
            "warn": (P["warn"], P["warn_soft"]),
            "error": (P["err"], P["err_soft"]),
        }
        fg, bg = colors.get(state, colors["idle"])
        self.configure(text=text, fg=fg, bg=bg)


class ScrolledFrame(tk.Frame):
    """竖直可滚动的容器，内容放进 `.inner`。"""

    def __init__(self, parent: tk.Misc, bg: Optional[str] = None):
        bg = bg or P["bg"]
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda _e: self._bind_wheel())
        self.canvas.bind("<Leave>", lambda _e: self._unbind_wheel())
        self.inner.bind("<Enter>", lambda _e: self._bind_wheel())

    def _on_inner(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    # 滚轮只在指针进入时接管，否则会把别的页面也滚起来
    def _bind_wheel(self) -> None:
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)

    def _unbind_wheel(self) -> None:
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(seq)

    def _wheel(self, event) -> None:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


class FormRow(tk.Frame):
    """配置页的一行：标签 + 说明 + 控件。"""

    def __init__(self, parent: tk.Misc, label: str, hint: str = "",
                 widget_factory: Optional[Callable[[tk.Misc], tk.Widget]] = None):
        super().__init__(parent, bg=P["card"])
        left = tk.Frame(self, bg=P["card"])
        left.pack(side="left", fill="y", pady=3)
        tk.Label(left, text=label, bg=P["card"], fg=P["text"],
                 font=fonts()["base"], anchor="w", width=22).pack(anchor="w")
        if hint:
            tk.Label(left, text=hint, bg=P["card"], fg=P["muted"],
                     font=fonts()["small"], anchor="w", justify="left",
                     wraplength=330).pack(anchor="w")

        self.widget: Optional[tk.Widget] = None
        if widget_factory is not None:
            holder = tk.Frame(self, bg=P["card"])
            holder.pack(side="right", anchor="ne")
            self.widget = widget_factory(holder)
            self.widget.pack(anchor="e")


def hline(parent: tk.Misc, bg: str = P["border"], pad: int = 0) -> tk.Frame:
    f = tk.Frame(parent, bg=bg, height=1)
    f.pack(fill="x", pady=pad)
    return f


def spacer(parent: tk.Misc, height: int = 8, bg: Optional[str] = None) -> tk.Frame:
    f = tk.Frame(parent, bg=bg or P["bg"], height=height)
    f.pack(fill="x")
    return f
