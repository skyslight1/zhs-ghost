"""课程列表页：勾选要刷的课。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List

from .theme import PALETTE as P
from .theme import fonts

CHECKED = "☑"
UNCHECKED = "☐"

TYPE_LABEL = {"zhidao": "共享课", "hike": "校内课", "ai": "AI 课"}


class CoursesTab(tk.Frame):
    def __init__(self, parent: tk.Misc, window: Any):
        super().__init__(parent, bg=P["bg"])
        self.window = window
        self._rows: Dict[str, dict] = {}
        self._picked: Dict[str, bool] = {}

        toolbar = tk.Frame(self, bg=P["bg"])
        toolbar.pack(fill="x", padx=18, pady=(14, 6))

        ttk.Button(toolbar, text="刷新列表", style="Accent.TButton",
                   command=self.window.action_fetch).pack(side="left")
        ttk.Button(toolbar, text="全选", style="Ghost.TButton",
                   command=lambda: self._set_all(True)).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="全不选", style="Ghost.TButton",
                   command=lambda: self._set_all(False)).pack(side="left")
        ttk.Button(toolbar, text="刷选中课程", style="Accent.TButton",
                   command=self._start_selected).pack(side="right")

        self.hint = tk.Label(self, text="还没有课程列表 —— 点「刷新列表」拉取。",
                             bg=P["bg"], fg=P["muted"], font=fonts()["small"], anchor="w")
        self.hint.pack(fill="x", padx=18)

        holder = tk.Frame(self, bg=P["bg"])
        holder.pack(fill="both", expand=True, padx=18, pady=(6, 14))

        self.tree = ttk.Treeview(
            holder, columns=("pick", "type", "name", "id"),
            show="headings", selectmode="browse",
        )
        self.tree.heading("pick", text="")
        self.tree.heading("type", text="类型")
        self.tree.heading("name", text="课程名称")
        self.tree.heading("id", text="课程 ID")
        self.tree.column("pick", width=38, anchor="center", stretch=False)
        self.tree.column("type", width=80, anchor="center", stretch=False)
        self.tree.column("name", width=360, anchor="w")
        self.tree.column("id", width=240, anchor="w", stretch=False)

        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double)

    # ------------------------------------------------------------ 数据

    def set_courses(self, courses: List[dict]) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        self._picked.clear()

        for c in courses:
            cid = str(c.get("id", ""))
            if not cid:
                continue
            kind = TYPE_LABEL.get(c.get("type", ""), c.get("type", ""))
            self._rows[cid] = c
            self._picked[cid] = True          # 默认全选，符合"我就是要刷课"的意图
            self.tree.insert("", "end", iid=cid,
                             values=(CHECKED, kind, c.get("name", ""), cid))

        if courses:
            self.hint.configure(text=f"共 {len(self._rows)} 门课。点击第一列可以勾选/取消。")
        else:
            self.hint.configure(text="没查到课程 —— 确认已登录，或者你的账号下确实没有进行中的课。")

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        self._picked.clear()

    def selected_ids(self) -> List[str]:
        return [cid for cid, ok in self._picked.items() if ok]

    def has_courses(self) -> bool:
        return bool(self._rows)

    # ------------------------------------------------------------ 交互

    def _on_click(self, event) -> None:
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _on_double(self, event) -> None:
        """双击 = 只刷这一门。"""
        iid = self.tree.identify_row(event.y)
        if iid and iid in self._rows:
            self.window.action_start([iid])

    def _toggle(self, iid: str) -> None:
        self._picked[iid] = not self._picked.get(iid, False)
        self.tree.set(iid, "pick", CHECKED if self._picked[iid] else UNCHECKED)

    def _set_all(self, value: bool) -> None:
        for iid in self._rows:
            self._picked[iid] = value
            self.tree.set(iid, "pick", CHECKED if value else UNCHECKED)

    def _start_selected(self) -> None:
        picked = self.selected_ids()
        if not picked:
            self.window.toast("没有勾选任何课程", "warn")
            return
        self.window.action_start(picked)
