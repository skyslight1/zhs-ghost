"""主页面：账号状态、当前进度、开始/暂停/停止。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

from ..observer import PHASE_DONE, PHASE_ERROR, PHASE_REST, Progress
from .theme import PALETTE as P
from .theme import fonts
from .widgets import Badge, Card, KeyValue


class StudyTab(tk.Frame):
    def __init__(self, parent: tk.Misc, window: Any):
        super().__init__(parent, bg=P["bg"])
        self.window = window
        self._qr_photo = None            # 必须持引用，否则被 GC 后显示空白
        self._paused = False

        pad = {"padx": 18, "pady": 6}

        # ---------------------------------------------------------- 账号
        self.account_card = Card(self, "账号")
        self.account_card.pack(fill="x", **pad)
        body = self.account_card.body

        top = tk.Frame(body, bg=P["card"])
        top.pack(fill="x")
        self.badge_account = Badge(top, "未登录", "idle")
        self.badge_account.pack(side="left")
        ttk.Button(top, text="扫码登录", style="Ghost.TButton",
                   command=window.action_login).pack(side="right")

        self.kv_account = KeyValue(body, "账号", "尚未登录")
        self.kv_account.pack(fill="x", pady=(8, 0))
        self.kv_quota = KeyValue(body, "今日进度", "-")
        self.kv_quota.pack(fill="x")

        # ---------------------------------------------------------- 当前任务
        self.task_card = Card(self, "当前任务")
        self.task_card.pack(fill="x", **pad)
        body = self.task_card.body

        head = tk.Frame(body, bg=P["card"])
        head.pack(fill="x")
        self.badge_task = Badge(head, "空闲", "idle")
        self.badge_task.pack(side="left")
        self.lbl_percent = tk.Label(head, text="", bg=P["card"], fg=P["text"],
                                    font=fonts()["sub"])
        self.lbl_percent.pack(side="right")

        self.kv_course = KeyValue(body, "课程", "-")
        self.kv_course.pack(fill="x", pady=(8, 0))
        self.kv_video = KeyValue(body, "视频", "-")
        self.kv_video.pack(fill="x")
        self.kv_state = KeyValue(body, "状态", "-")
        self.kv_state.pack(fill="x")

        self.progress = ttk.Progressbar(body, mode="determinate", maximum=1000,
                                        style="TProgressbar")
        self.progress.pack(fill="x", pady=(10, 2))
        self.lbl_detail = tk.Label(body, text="", bg=P["card"], fg=P["muted"],
                                   font=fonts()["small"], anchor="w")
        self.lbl_detail.pack(fill="x")

        # ---------------------------------------------------------- 二维码
        self.qr_card = Card(self, "扫码登录")
        self.qr_label = tk.Label(self.qr_card.body, bg=P["card"], bd=0)
        self.qr_label.pack()
        self.qr_hint = tk.Label(self.qr_card.body, text="用「知到」App 扫描上方二维码",
                                bg=P["card"], fg=P["muted"], font=fonts()["small"])
        self.qr_hint.pack(pady=(6, 0))

        # ---------------------------------------------------------- 操作
        actions = tk.Frame(self, bg=P["bg"])
        actions.pack(fill="x", padx=18, pady=(12, 6))

        self.btn_start = ttk.Button(actions, text="开始学习", style="Accent.TButton",
                                    command=window.action_start)
        self.btn_start.pack(side="left")
        self.btn_fetch = ttk.Button(actions, text="拉取课程", command=window.action_fetch)
        self.btn_fetch.pack(side="left", padx=8)
        self.btn_pause = ttk.Button(actions, text="暂停", command=self._toggle_pause,
                                    state="disabled")
        self.btn_pause.pack(side="left")
        self.btn_stop = ttk.Button(actions, text="停止", style="Danger.TButton",
                                   command=window.action_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        ttk.Button(actions, text="打开日志目录", style="Ghost.TButton",
                   command=window.open_log_dir).pack(side="right")

        tk.Label(self, text="提示：同一 IP 上同时跑多个账号是最容易被一起判风控的操作。",
                 bg=P["bg"], fg=P["muted"], font=fonts()["small"],
                 anchor="w").pack(fill="x", padx=18, pady=(4, 0))

    # ------------------------------------------------------------ 状态更新

    def set_account(self, logged_in: bool, uuid: str = "", quota: str = "") -> None:
        if logged_in:
            self.badge_account.set("已登录", "ok")
            self.kv_account.set(uuid or "(已登录)", P["text"])
        else:
            self.badge_account.set("未登录", "idle")
            self.kv_account.set("尚未登录")
        if quota:
            self.kv_quota.set(quota)

    def set_quota(self, text: str) -> None:
        self.kv_quota.set(text)

    def set_busy(self, busy: bool, running: bool = False) -> None:
        state = "disabled" if busy else "normal"
        self.btn_start.configure(state=state)
        self.btn_fetch.configure(state=state)
        self.btn_stop.configure(state="normal" if running else "disabled")
        if running:
            self.btn_pause.configure(state="normal")
        else:
            self.btn_pause.configure(state="disabled", text="暂停")
            self._paused = False

    def update_progress(self, p: Progress) -> None:
        if p.phase == PHASE_REST:
            self.badge_task.set("休息中", "warn")
            self.kv_state.set(p.message, P["warn"])
        elif p.phase == PHASE_DONE:
            self.badge_task.set("完成", "ok")
            self.kv_state.set(p.message, P["ok"])
        elif p.phase == PHASE_ERROR:
            self.badge_task.set("出错", "error")
            self.kv_state.set(p.message, P["err"])
        else:
            self.badge_task.set("学习中", "running")
            self.kv_state.set(p.message, P["text"])

        if p.course:
            self.kv_course.set(p.course)
        if p.video:
            self.kv_video.set(p.video)
        if p.total > 0:
            self.progress.configure(value=p.percent * 1000)
            self.lbl_percent.configure(text=f"{p.percent * 100:.1f}%")
            self.lbl_detail.configure(
                text=f"{p.current:.0f} / {p.total:.0f} 秒"
                     + ("（已暂停）" if p.extra.get("idle") else "")
                     + ("（答题中）" if p.extra.get("quiz") else ""))
        else:
            self.lbl_percent.configure(text="")
            self.lbl_detail.configure(text="")

    def reset_progress(self) -> None:
        self.progress.configure(value=0)
        self.lbl_percent.configure(text="")
        self.lbl_detail.configure(text="")
        self.kv_course.set("-")
        self.kv_video.set("-")
        self.badge_task.set("空闲", "idle")
        self.kv_state.set("-")

    # ------------------------------------------------------------ 二维码

    def show_qr(self, image_bytes: bytes) -> None:
        from .qr import to_photo

        photo = to_photo(image_bytes, size=240)
        if photo is None:
            self.qr_hint.configure(text="二维码图片渲染失败，请改用命令行版扫码")
            return
        self._qr_photo = photo
        self.qr_label.configure(image=photo)
        self.qr_hint.configure(text="用「知到」App 扫描上方二维码")
        if not self.qr_card.winfo_ismapped():
            self.qr_card.pack(fill="x", padx=18, pady=6)

    def hide_qr(self) -> None:
        self.qr_label.configure(image="")
        self._qr_photo = None
        self.qr_card.pack_forget()

    def _toggle_pause(self) -> None:
        if self._paused:
            self.window.action_resume()
            self.btn_pause.configure(text="暂停")
            self._paused = False
        else:
            self.window.action_pause()
            self.btn_pause.configure(text="继续")
            self._paused = True
