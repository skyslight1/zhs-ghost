"""日志页：实时日志 + 等级过滤。"""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Any, List, Optional

from .theme import PALETTE as P
from .theme import fonts

LEVELS = ("全部", "INFO", "WARNING", "ERROR", "DEBUG")
LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
TAG_COLORS = {
    "DEBUG": "#8a93a0",
    "INFO": P["text"],
    "WARNING": P["warn"],
    "ERROR": P["err"],
    "CRITICAL": P["err"],
    "SUCCESS": P["ok"],
}

# 保留的最大行数。挂机几小时日志会很长，不做限制迟早卡死
MAX_LINES = 4000


class LogTab(tk.Frame):
    def __init__(self, parent: tk.Misc, window: Any):
        super().__init__(parent, bg=P["bg"])
        self.window = window
        self._min_level = "INFO"
        self._buffer: List[str] = []

        bar = tk.Frame(self, bg=P["bg"])
        bar.pack(fill="x", padx=18, pady=(14, 6))

        tk.Label(bar, text="最低等级", bg=P["bg"], fg=P["muted"],
                 font=fonts()["small"]).pack(side="left")
        self.level_var = tk.StringVar(value="INFO")
        combo = ttk.Combobox(bar, textvariable=self.level_var, values=LEVELS,
                             state="readonly", width=10)
        combo.pack(side="left", padx=(6, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter())

        self.autoscroll = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="自动滚动", variable=self.autoscroll, bg=P["bg"],
                       fg=P["text"], activebackground=P["bg"], selectcolor=P["bg"],
                       font=fonts()["small"], highlightthickness=0, bd=0).pack(side="left")

        ttk.Button(bar, text="打开日志目录", style="Ghost.TButton",
                   command=self.window.open_log_dir).pack(side="right")
        ttk.Button(bar, text="清空", style="Ghost.TButton",
                   command=self.clear).pack(side="right", padx=(0, 8))

        holder = tk.Frame(self, bg=P["bg"])
        holder.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        self.text = tk.Text(holder, wrap="word", bg="#fbfcfd", fg=P["text"],
                            relief="flat", highlightthickness=1,
                            highlightbackground=P["border"], font=fonts()["mono"],
                            state="disabled", padx=10, pady=8,
                            insertbackground=P["text"])
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for tag, color in TAG_COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("TS", foreground=P["muted"])

    # ------------------------------------------------------------ 写入

    def append(self, line: str, level: str = "INFO") -> None:
        level = level.upper()
        self._buffer.append(f"{level}\x00{line}")
        if len(self._buffer) > MAX_LINES:
            del self._buffer[: len(self._buffer) - MAX_LINES]
            self._render(reset=True)
            return
        if LEVEL_RANK.get(level, 20) >= LEVEL_RANK.get(self._min_level, 20):
            self._insert(line, level)

    def _insert(self, line: str, level: str) -> None:
        self.text.configure(state="normal")
        stamp, _, body = line.partition("  ")
        if body:
            self.text.insert("end", stamp + "  ", "TS")
            self.text.insert("end", body + "\n", level)
        else:
            self.text.insert("end", line + "\n", level)
        self.text.configure(state="disabled")
        if self.autoscroll.get():
            self.text.see("end")

    def clear(self) -> None:
        self._buffer.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _apply_filter(self) -> None:
        selected = self.level_var.get()
        self._min_level = "DEBUG" if selected == "全部" else selected
        self._render(reset=True)

    def _render(self, reset: bool = False) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        threshold = LEVEL_RANK.get(self._min_level, 20)
        for raw in self._buffer:
            level, _, line = raw.partition("\x00")
            if LEVEL_RANK.get(level, 20) >= threshold:
                self._insert(line, level)

    # ------------------------------------------------------------ 落盘

    def export(self, path: str) -> Optional[str]:
        try:
            with open(path, "w", encoding="utf-8") as f:
                for raw in self._buffer:
                    _level, _, line = raw.partition("\x00")
                    f.write(line + "\n")
            return path
        except Exception:
            return None


def install_gui_sink(bridge: Any, log_tab: LogTab):
    """把 loguru 的输出接到 GUI。

    注意：`App()` 内部会调 `setup_logging()`，那里执行了 `logger.remove()`，
    所以这个 sink 必须在 App 创建**之后**再挂，否则会被清掉。
    """
    from loguru import logger

    def sink(message: Any) -> None:
        try:
            record = message.record
            level = record["level"].name
            stamp = record["time"].strftime("%H:%M:%S")
            text = record["message"]
        except Exception:
            level, stamp, text = "INFO", "--:--:--", str(message).rstrip()
        line = f"{stamp}  {level:<7} {text}"
        bridge.post(log_tab.append, line, level)

    return logger.add(sink, level="DEBUG", format="{message}", backtrace=False,
                      diagnose=False, enqueue=False)
