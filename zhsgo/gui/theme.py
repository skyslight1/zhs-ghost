"""界面主题：调色板 + ttk 样式。

Tkinter 默认在 Windows 上用的是 "vista" 主题，很多控件颜色改不动。
这里统一切到 "clam"，然后自己配一套颜色，换来可控的外观。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTE = {
    "bg": "#f4f5f7",
    "card": "#ffffff",
    "border": "#e2e5ea",
    "text": "#1f2430",
    "muted": "#7a8391",
    "accent": "#2f6feb",
    "accent_hover": "#1e5fd8",
    "accent_soft": "#eaf1fe",
    "ok": "#1a9c53",
    "ok_soft": "#e8f6ee",
    "warn": "#c77800",
    "warn_soft": "#fdf3e3",
    "err": "#d13438",
    "err_soft": "#fdecec",
    "track": "#e6e9ee",
}

FONT_CANDIDATES = (
    "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
    "Noto Sans CJK SC", "Source Han Sans SC", "Segoe UI", "Helvetica",
)

MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "JetBrains Mono",
                   "DejaVu Sans Mono", "Courier New")

_sizes = {"base": 10, "small": 9, "title": 15, "sub": 11, "mono": 9}

# apply() 之后填充。各处 widget 直接取，省得层层传参。
_FONTS: dict = {
    "family": "TkDefaultFont", "mono": "TkFixedFont",
    "base": ("TkDefaultFont", 10), "small": ("TkDefaultFont", 9),
    "title": ("TkDefaultFont", 15, "bold"), "sub": ("TkDefaultFont", 11, "bold"),
    "button": ("TkDefaultFont", 11), "mono": ("TkFixedFont", 9),
}


def fonts() -> dict:
    return _FONTS


def pick_family(root: tk.Misc, candidates=FONT_CANDIDATES) -> str:
    try:
        available = set(tkfont.families(root))
    except Exception:
        return "TkDefaultFont"
    for name in candidates:
        if name in available:
            return name
    return "TkDefaultFont"


def apply(root: tk.Tk) -> dict:
    """配置 ttk 样式，返回字体字典供各页面复用。"""
    family = pick_family(root)
    mono = pick_family(root, MONO_CANDIDATES)

    fonts = {
        "family": family,
        "mono": mono,
        "base": (family, _sizes["base"]),
        "small": (family, _sizes["small"]),
        "title": (family, _sizes["title"], "bold"),
        "sub": (family, _sizes["sub"], "bold"),
        "button": (family, _sizes["base"] + 1),
        "mono": (mono, _sizes["mono"]),
    }

    root.configure(bg=PALETTE["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    p = PALETTE

    # ---- 基础容器
    style.configure(".", font=fonts["base"], background=p["bg"],
                    foreground=p["text"], focuscolor=p["accent"])
    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["card"], relief="flat")
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Card.TLabel", background=p["card"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"], font=fonts["small"])
    style.configure("CardMuted.TLabel", background=p["card"], foreground=p["muted"],
                    font=fonts["small"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"], font=fonts["title"])
    style.configure("Sub.TLabel", background=p["card"], foreground=p["text"], font=fonts["sub"])
    style.configure("Ok.TLabel", background=p["card"], foreground=p["ok"])
    style.configure("Warn.TLabel", background=p["card"], foreground=p["warn"])
    style.configure("Err.TLabel", background=p["card"], foreground=p["err"])

    # ---- 按钮
    style.configure("TButton", padding=(14, 7), font=fonts["button"],
                    background="#eceef1", foreground=p["text"],
                    borderwidth=0, focusthickness=0)
    style.map("TButton",
              background=[("active", "#e1e4e9"), ("disabled", "#f2f3f5")],
              foreground=[("disabled", "#a8aeb8")])

    style.configure("Accent.TButton", padding=(16, 8), font=fonts["button"],
                    background=p["accent"], foreground="#ffffff",
                    borderwidth=0, focusthickness=0)
    style.map("Accent.TButton",
              background=[("active", p["accent_hover"]), ("disabled", "#b7cbf5")],
              foreground=[("disabled", "#eef3fe")])

    style.configure("Danger.TButton", padding=(14, 7), font=fonts["button"],
                    background=p["err_soft"], foreground=p["err"],
                    borderwidth=0, focusthickness=0)
    style.map("Danger.TButton", background=[("active", "#fbdcdd"), ("disabled", "#f2f3f5")])

    style.configure("Ghost.TButton", padding=(10, 5), font=fonts["small"],
                    background=p["card"], foreground=p["accent"],
                    borderwidth=0, focusthickness=0)
    style.map("Ghost.TButton", background=[("active", p["accent_soft"])])

    # ---- 输入
    style.configure("TEntry", padding=6, fieldbackground=p["card"],
                    bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"],
                    borderwidth=1, relief="flat")
    style.map("TEntry", bordercolor=[("focus", p["accent"])])

    style.configure("TCombobox", padding=6, fieldbackground=p["card"],
                    bordercolor=p["border"], arrowcolor=p["muted"], borderwidth=1)
    style.map("TCombobox", bordercolor=[("focus", p["accent"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"],
                    focuscolor=p["bg"])
    style.map("TCheckbutton", background=[("active", p["bg"])])
    style.configure("Card.TCheckbutton", background=p["card"], foreground=p["text"])
    style.map("Card.TCheckbutton", background=[("active", p["card"])])

    style.configure("TScale", background=p["card"], troughcolor=p["track"],
                    bordercolor=p["card"], lightcolor=p["accent"], darkcolor=p["accent"])

    # ---- 分组框
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"],
                    borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["muted"],
                    font=fonts["small"])

    # ---- 标签页
    style.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.configure("TNotebook.Tab", padding=(20, 9), font=fonts["base"],
                    background=p["bg"], foreground=p["muted"], borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", p["card"])],
              foreground=[("selected", p["accent"])])

    # ---- 进度条
    style.configure("TProgressbar", troughcolor=p["track"], background=p["accent"],
                    borderwidth=0, thickness=10)
    style.configure("Ok.Horizontal.TProgressbar", troughcolor=p["track"],
                    background=p["ok"], borderwidth=0, thickness=10)

    # ---- 表格
    style.configure("Treeview", background=p["card"], fieldbackground=p["card"],
                    foreground=p["text"], rowheight=28, borderwidth=0,
                    font=fonts["base"])
    style.configure("Treeview.Heading", background="#f0f2f5", foreground=p["muted"],
                    font=fonts["small"], relief="flat", padding=(8, 6))
    style.map("Treeview.Heading", background=[("active", "#e7eaee")])
    style.map("Treeview", background=[("selected", p["accent_soft"])],
              foreground=[("selected", p["text"])])

    # ---- 滚动条
    style.configure("Vertical.TScrollbar", background="#d6dae0", troughcolor=p["bg"],
                    borderwidth=0, arrowsize=13, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", "#c2c8d0")])
    style.configure("Horizontal.TScrollbar", background="#d6dae0", troughcolor=p["bg"],
                    borderwidth=0, arrowsize=13, relief="flat")

    # ---- 分隔线
    style.configure("TSeparator", background=p["border"])

    _FONTS.clear()
    _FONTS.update(fonts)
    return fonts


def status_color(state: str) -> tuple[str, str]:
    """状态 → (前景色, 背景色)。"""
    p = PALETTE
    return {
        "idle": (p["muted"], p["card"]),
        "running": (p["accent"], p["accent_soft"]),
        "ok": (p["ok"], p["ok_soft"]),
        "warn": (p["warn"], p["warn_soft"]),
        "error": (p["err"], p["err_soft"]),
    }.get(state, (p["muted"], p["card"]))
