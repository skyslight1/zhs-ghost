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
        # 二维码用独立窗口显示（见 show_qr）。主界面里的面积不够，
        # 240x240 的图会被 pack 压成 240x94 —— 看起来就像"没出二维码"。
        # 这里只在主界面留一个状态行。
        self.qr_card = Card(self, "扫码登录")
        self.qr_hint = tk.Label(self.qr_card.body, text="等待扫码…",
                                bg=P["card"], fg=P["muted"], font=fonts()["small"])
        self.qr_hint.pack(anchor="w")
        # 主界面只留一行状态提示，二维码本体在独立窗口里
        self.qr_card.pack(fill="x", padx=18, pady=6)
        self._qr_window: Optional[tk.Toplevel] = None
        self._qr_label: Optional[tk.Label] = None

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
        """用独立窗口显示二维码。

        最早是把它当成主界面里的一张卡片。实测不行：主界面本来就装不下
        （账号卡 142 + 任务卡 218 + 二维码 300 + 按钮行 50 > 可视 593），
        pack 会把二维码压扁 —— 240x240 的图被压成 240x94，看起来就是
        "点了扫码登录但没出二维码"。

        独立窗口顺带解决两个问题：可以放得更大（380px，好扫），
        也不跟主界面的布局互相抢空间。
        """
        from .qr import to_photo

        photo = to_photo(image_bytes, size=380)
        if photo is None:
            self.window.toast("二维码渲染失败，请改用命令行版扫码", "error")
            self.qr_hint.configure(text="二维码渲染失败")
            return

        win = self._qr_window
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self.window)
            win.title("扫码登录 · zhs-ghost")
            win.configure(bg=P["card"])
            win.resizable(False, False)
            win.transient(self.window)
            win.protocol("WM_DELETE_WINDOW", self._on_qr_window_closed)

            holder = tk.Frame(win, bg=P["card"])
            holder.pack(padx=26, pady=22)

            self._qr_label = tk.Label(holder, bg=P["card"], bd=0)
            self._qr_label.pack()

            self._qr_hint = tk.Label(holder, text="用手机「知到」App 扫描上方二维码",
                                     bg=P["card"], fg=P["text"], font=fonts()["sub"])
            self._qr_hint.pack(pady=(14, 2))
            tk.Label(holder, text="扫码并在手机上确认后，本窗口会自动关闭",
                     bg=P["card"], fg=P["muted"], font=fonts()["small"]).pack()

            self._qr_window = win

        self._qr_photo = photo          # 必须持引用，否则被 GC 后显示空白
        self._qr_label.configure(image=photo)
        # 注意：qr_hint（主界面状态行）和 _qr_hint（弹窗里的说明）
        # 是两个不同对象，别写混
        self._qr_hint.configure(text="用手机「知到」App 扫描上方二维码")
        self.qr_hint.configure(text="二维码已打开，请在弹出的窗口中扫码", fg=P["text"])

        win.deiconify()
        win.lift()
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        self._center_qr_window()
        win.update_idletasks()

    def _center_qr_window(self) -> None:
        win = self._qr_window
        if win is None:
            return
        try:
            win.update_idletasks()
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            root = self.window
            x = root.winfo_rootx() + (root.winfo_width() - w) // 2
            y = root.winfo_rooty() + (root.winfo_height() - h) // 2
            win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass

    def _on_qr_window_closed(self) -> None:
        """用户手动关掉二维码窗口 = 放弃这次登录。"""
        self._qr_window = None
        self._qr_photo = None
        self.window.action_stop()
        self.badge_account.set("未登录", "idle")

    def hide_qr(self) -> None:
        if self._qr_window is not None:
            try:
                self._qr_window.destroy()
            except Exception:
                pass
            self._qr_window = None
        self._qr_photo = None
        try:
            self.qr_hint.configure(text="等待扫码…", fg=P["muted"])
        except Exception:
            pass

    def _toggle_pause(self) -> None:
        if self._paused:
            self.window.action_resume()
            self.btn_pause.configure(text="暂停")
            self._paused = False
        else:
            self.window.action_pause()
            self.btn_pause.configure(text="继续")
            self._paused = True
