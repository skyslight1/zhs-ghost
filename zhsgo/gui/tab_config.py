"""配置页：把 config.yaml 里常用的部分做成表单。

不追求覆盖全部字段 —— 冷门项太多，硬塞进来只会让页面不可读。
剩下的一律通过「打开配置文件」直接编辑。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Tuple

from .theme import PALETTE as P
from .theme import fonts
from .widgets import Card, ScrolledFrame, spacer


class ConfigTab(tk.Frame):
    def __init__(self, parent: tk.Misc, window: Any):
        super().__init__(parent, bg=P["bg"])
        self.window = window
        self.vars: Dict[str, tk.Variable] = {}
        self._range_vars: Dict[str, Tuple[tk.StringVar, tk.StringVar]] = {}

        outer = ScrolledFrame(self, bg=P["bg"])
        outer.pack(fill="both", expand=True)
        root = outer.inner
        root.configure(padx=0)

        self._build_auth(root)
        self._build_study(root)
        self._build_budget(root)
        self._build_pacer(root)
        self._build_relay(root)
        self._build_notify(root)
        self._build_misc(root)

        spacer(root, 10)

        bar = tk.Frame(self, bg=P["bg"])
        bar.pack(fill="x", padx=18, pady=(6, 14))
        ttk.Button(bar, text="保存配置", style="Accent.TButton",
                   command=self._save).pack(side="left")
        ttk.Button(bar, text="放弃修改", command=self.reload).pack(side="left", padx=8)
        ttk.Button(bar, text="打开配置文件", style="Ghost.TButton",
                   command=self._open_file).pack(side="right")
        self.status = tk.Label(bar, text="", bg=P["bg"], fg=P["muted"],
                               font=fonts()["small"])
        self.status.pack(side="left", padx=12)

    # ================================================================ 构件

    def _card(self, parent: tk.Misc, title: str) -> tk.Frame:
        card = Card(parent, title)
        card.pack(fill="x", padx=18, pady=(12, 0))
        return card.body

    def _row(self, parent: tk.Misc, label: str, hint: str = "") -> tk.Frame:
        """一行：左边标签+说明，右边控件。

        注意 pack 顺序 —— **右边的控件必须先 pack**。左边用了
        `expand=True` 会吃掉全部剩余空间，如果它先 pack，右边就一点位置
        都分不到（表现为整列输入框凭空消失）。
        """
        row = tk.Frame(parent, bg=P["card"])
        row.pack(fill="x", pady=4)

        right = tk.Frame(row, bg=P["card"])
        right.pack(side="right", anchor="ne")

        left = tk.Frame(row, bg=P["card"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=label, bg=P["card"], fg=P["text"],
                 font=fonts()["base"], anchor="w").pack(anchor="w")
        if hint:
            tk.Label(left, text=hint, bg=P["card"], fg=P["muted"],
                     font=fonts()["small"], anchor="w", justify="left",
                     wraplength=420).pack(anchor="w")
        return right

    def _entry(self, parent: tk.Misc, key: str, width: int = 30,
               show: str = "") -> tk.Entry:
        var = tk.StringVar()
        self.vars[key] = var
        e = tk.Entry(parent, textvariable=var, width=width, show=show,
                     bg="#fbfcfd", fg=P["text"], relief="flat",
                     highlightthickness=1, highlightbackground=P["border"],
                     highlightcolor=P["accent"], font=fonts()["base"],
                     insertbackground=P["text"])
        e.pack(ipady=4)
        return e

    def _check(self, parent: tk.Misc, key: str, text: str = "") -> tk.Checkbutton:
        var = tk.BooleanVar()
        self.vars[key] = var
        c = tk.Checkbutton(parent, text=text, variable=var, bg=P["card"],
                           fg=P["text"], activebackground=P["card"],
                           selectcolor=P["card"], font=fonts()["base"],
                           highlightthickness=0, bd=0)
        c.pack()
        return c

    def _range(self, parent: tk.Misc, key: str, width: int = 7) -> tk.Frame:
        var = (tk.StringVar(), tk.StringVar())
        self._range_vars[key] = var
        f = tk.Frame(parent, bg=P["card"])
        for i, v in enumerate(var):
            if i:
                tk.Label(f, text="~", bg=P["card"], fg=P["muted"],
                         font=fonts()["base"]).pack(side="left", padx=3)
            tk.Entry(f, textvariable=v, width=width, bg="#fbfcfd", fg=P["text"],
                     relief="flat", highlightthickness=1,
                     highlightbackground=P["border"], highlightcolor=P["accent"],
                     font=fonts()["base"], justify="center",
                     insertbackground=P["text"]).pack(side="left", ipady=4)
        f.pack()
        return f

    # ================================================================ 各分组

    def _build_auth(self, parent: tk.Misc) -> None:
        body = self._card(parent, "登录")
        r = self._row(body, "使用扫码登录",
                      "推荐。密码登录容易触发风控（失败几次就会要求验证码）")
        self._check(r, "auth.use_qr")
        r = self._row(body, "账号", "留空则只用扫码登录")
        self._entry(r, "auth.username")
        r = self._row(body, "密码", "会以明文存在 config.yaml 里，注意别外传")
        self._entry(r, "auth.password", show="*")

    def _build_study(self, parent: tk.Misc) -> None:
        body = self._card(parent, "学习")
        r = self._row(body, "播放速度", "0 = 使用默认值。上限 1.5x，再高会被风控抓")
        self._entry(r, "study.speed", width=10)
        r = self._row(body, "完成阈值", "进度高于该比例即视为完成，0.91 是智慧树自己的判定线")
        self._entry(r, "study.end_threshold", width=10)
        r = self._row(body, "预热视频流", "拉一次播放地址和首个分片，制造 CDN 侧流量痕迹")
        self._check(r, "study.prime_video")
        r = self._row(body, "打印课程目录", "在日志里输出章节树")
        self._check(r, "study.tree_view")

    def _build_budget(self, parent: tk.Misc) -> None:
        body = self._card(parent, "时长纪律（影响被风控的概率，建议别调高）")
        r = self._row(body, "单次会话时长", "分钟。连续学满这段时间后强制休息")
        self._range(r, "budget.session_minutes")
        r = self._row(body, "休息时长", "分钟")
        self._range(r, "budget.rest_minutes")
        r = self._row(body, "单日总上限", "分钟。真人不可能一天刷 8 小时")
        self._entry(r, "budget.daily_minutes", width=10)
        r = self._row(body, "单日会话数", "次")
        self._entry(r, "budget.daily_sessions", width=10)
        r = self._row(body, "单门课时限", "分钟，0 = 不限")
        self._entry(r, "budget.per_course_minutes", width=10)

    def _build_pacer(self, parent: tk.Misc) -> None:
        body = self._card(parent, "上报节拍")
        r = self._row(body, "上报间隔", "秒。随机取区间内的值；**不要再改成固定 30 秒**")
        self._range(r, "pacer.report_interval")
        r = self._row(body, "速度硬上限", "超过会被夹回来")
        self._entry(r, "pacer.max_speed", width=10)
        r = self._row(body, "默认速度", "speed=0 时用这个")
        self._entry(r, "pacer.default_speed", width=10)
        r = self._row(body, "微暂停时长", "秒。模拟真人走神/被叫走")
        self._range(r, "pacer.pause_seconds")
        r = self._row(body, "真实毫秒时间戳",
                      "关掉会退化成 *000 结尾的机器人时间戳，强烈建议保持开启")
        self._check(r, "pacer.real_millisecond_ts")

    def _build_relay(self, parent: tk.Misc) -> None:
        body = self._card(parent, "人机验证")
        r = self._row(body, "自动处理验证码", "关掉的话命中风控时会直接停下")
        self._check(r, "relay.enabled")
        r = self._row(body, "无头模式",
                      "看不到浏览器窗口。指纹特征更差，只建议服务器上用")
        self._check(r, "relay.headless")
        r = self._row(body, "等待验证码出现", "秒")
        self._entry(r, "relay.wait_captcha_seconds", width=10)
        r = self._row(body, "自动失败后等人工", "秒。0 = 不等人，直接放弃")
        self._entry(r, "relay.manual_wait_seconds", width=10)
        r = self._row(body, "滑块位置校正",
                      "总是差一点就调这个：拖不到调大，冲过头调小")
        self._entry(r, "relay.slider_offset_fix", width=10)

    def _build_notify(self, parent: tk.Misc) -> None:
        body = self._card(parent, "通知（挂机时建议至少开一个）")
        r = self._row(body, "启用通知", "")
        self._check(r, "notify.enabled")
        r = self._row(body, "Server酱 Key", "微信收推送，https://sct.ftqq.com")
        self._entry(r, "notify.serverchan_key")
        r = self._row(body, "钉钉 Webhook", "")
        self._entry(r, "notify.dingtalk_webhook")
        r = self._row(body, "本地响铃", "需要人工处理验证码时响铃")
        self._check(r, "notify.local_beep")

    def _build_misc(self, parent: tk.Misc) -> None:
        body = self._card(parent, "其他")
        r = self._row(body, "HTTP 代理", "例：http://127.0.0.1:7890，留空直连")
        self._entry(r, "proxies.http")
        r = self._row(body, "日志级别", "INFO / WARNING / DEBUG（DEBUG 会记录账号信息）")
        self._entry(r, "log.level", width=12)

    # ================================================================ 读写

    def reload(self) -> None:
        cfg = self.window.cfg
        self._set_bool("auth.use_qr", cfg.auth.use_qr)
        self._set_text("auth.username", cfg.auth.username)
        self._set_text("auth.password", cfg.auth.password)

        self._set_text("study.speed", cfg.study.speed or "")
        self._set_text("study.end_threshold", cfg.study.end_threshold)
        self._set_bool("study.prime_video", cfg.study.prime_video)
        self._set_bool("study.tree_view", cfg.study.tree_view)

        self._set_range("budget.session_minutes", cfg.budget.session_minutes)
        self._set_range("budget.rest_minutes", cfg.budget.rest_minutes)
        self._set_text("budget.daily_minutes", cfg.budget.daily_minutes)
        self._set_text("budget.daily_sessions", cfg.budget.daily_sessions)
        self._set_text("budget.per_course_minutes", cfg.budget.per_course_minutes)

        self._set_range("pacer.report_interval", cfg.pacer.report_interval)
        self._set_text("pacer.max_speed", cfg.pacer.max_speed)
        self._set_text("pacer.default_speed", cfg.pacer.default_speed)
        self._set_range("pacer.pause_seconds", cfg.pacer.pause_seconds)
        self._set_bool("pacer.real_millisecond_ts", cfg.pacer.real_millisecond_ts)

        self._set_bool("relay.enabled", cfg.relay.enabled)
        self._set_bool("relay.headless", cfg.relay.headless)
        self._set_text("relay.wait_captcha_seconds", cfg.relay.wait_captcha_seconds)
        self._set_text("relay.manual_wait_seconds", cfg.relay.manual_wait_seconds)
        self._set_text("relay.slider_offset_fix", cfg.relay.slider_offset_fix)

        self._set_bool("notify.enabled", cfg.notify.enabled)
        self._set_text("notify.serverchan_key", cfg.notify.serverchan_key)
        self._set_text("notify.dingtalk_webhook", cfg.notify.dingtalk_webhook)
        self._set_bool("notify.local_beep", cfg.notify.local_beep)

        self._set_text("proxies.http", cfg.proxies.get("http", ""))
        self._set_text("log.level", cfg.log.level)

        self.status.configure(text="", fg=P["muted"])

    def _set_text(self, key: str, value: Any) -> None:
        var = self.vars.get(key)
        if var is not None:
            var.set("" if value is None else str(value))

    def _set_bool(self, key: str, value: Any) -> None:
        var = self.vars.get(key)
        if var is not None:
            var.set(bool(value))

    def _set_range(self, key: str, value: Tuple[float, float]) -> None:
        pair = self._range_vars.get(key)
        if pair and value is not None:
            pair[0].set(str(value[0]))
            pair[1].set(str(value[1]))

    # ------------------------------------------------------------ 保存

    def _save(self) -> None:
        errors: List[str] = []

        def num(key: str, cast, current):
            raw = str(self.vars[key].get()).strip()
            if raw == "":
                return current
            try:
                return cast(raw)
            except ValueError:
                errors.append(f"{key} 不是合法数字：{raw!r}")
                return current

        def pair(key: str, cast, current):
            lo_var, hi_var = self._range_vars[key]
            try:
                lo = cast(lo_var.get().strip())
                hi = cast(hi_var.get().strip())
            except ValueError:
                errors.append(f"{key} 区间格式不对")
                return current
            if hi < lo:
                errors.append(f"{key} 上限小于下限")
                return current
            return (lo, hi)

        cfg = self.window.cfg
        cfg.auth.use_qr = bool(self.vars["auth.use_qr"].get())
        cfg.auth.username = self.vars["auth.username"].get().strip()
        cfg.auth.password = self.vars["auth.password"].get()

        raw_speed = str(self.vars["study.speed"].get()).strip()
        cfg.study.speed = float(raw_speed) if raw_speed else None
        cfg.study.end_threshold = num("study.end_threshold", float, cfg.study.end_threshold)
        cfg.study.prime_video = bool(self.vars["study.prime_video"].get())
        cfg.study.tree_view = bool(self.vars["study.tree_view"].get())

        cfg.budget.session_minutes = pair("budget.session_minutes", float, cfg.budget.session_minutes)
        cfg.budget.rest_minutes = pair("budget.rest_minutes", float, cfg.budget.rest_minutes)
        cfg.budget.daily_minutes = num("budget.daily_minutes", float, cfg.budget.daily_minutes)
        cfg.budget.daily_sessions = num("budget.daily_sessions", int, cfg.budget.daily_sessions)
        cfg.budget.per_course_minutes = num("budget.per_course_minutes", float,
                                            cfg.budget.per_course_minutes)

        cfg.pacer.report_interval = pair("pacer.report_interval", float, cfg.pacer.report_interval)
        cfg.pacer.max_speed = num("pacer.max_speed", float, cfg.pacer.max_speed)
        cfg.pacer.default_speed = num("pacer.default_speed", float, cfg.pacer.default_speed)
        cfg.pacer.pause_seconds = pair("pacer.pause_seconds", float, cfg.pacer.pause_seconds)
        cfg.pacer.real_millisecond_ts = bool(self.vars["pacer.real_millisecond_ts"].get())

        cfg.relay.enabled = bool(self.vars["relay.enabled"].get())
        cfg.relay.headless = bool(self.vars["relay.headless"].get())
        cfg.relay.wait_captcha_seconds = num("relay.wait_captcha_seconds", float,
                                             cfg.relay.wait_captcha_seconds)
        cfg.relay.manual_wait_seconds = num("relay.manual_wait_seconds", float,
                                            cfg.relay.manual_wait_seconds)
        cfg.relay.slider_offset_fix = num("relay.slider_offset_fix", float,
                                          cfg.relay.slider_offset_fix)

        cfg.notify.enabled = bool(self.vars["notify.enabled"].get())
        cfg.notify.serverchan_key = self.vars["notify.serverchan_key"].get().strip()
        cfg.notify.dingtalk_webhook = self.vars["notify.dingtalk_webhook"].get().strip()
        cfg.notify.local_beep = bool(self.vars["notify.local_beep"].get())

        proxy = self.vars["proxies.http"].get().strip()
        cfg.proxies = {"http": proxy, "https": proxy} if proxy else {}
        cfg.log.level = self.vars["log.level"].get().strip() or "INFO"

        if errors:
            self.status.configure(text="；".join(errors[:2]), fg=P["err"])
            return

        # 学习任务正在跑的时候改配置没意义 —— 运行中的 App 已经拿着旧值
        if self.window.is_running():
            self.status.configure(text="已生效于下次运行（当前任务仍在用旧配置）", fg=P["warn"])
        else:
            self.status.configure(text="已保存", fg=P["ok"])

        try:
            path = cfg.save()
            self.window.toast(f"配置已写入 {os.path.basename(path)}", "ok")
        except Exception as e:
            self.status.configure(text=f"写入失败：{e}", fg=P["err"])

    def _open_file(self) -> None:
        path = self.window.cfg.config_path
        if not path or not os.path.isfile(path):
            self.window.toast("配置文件不存在", "warn")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.window.toast(f"打不开：{e}", "error")
