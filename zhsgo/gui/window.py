"""主窗口：标签页组装 + 后台任务编排。

任务编排的三条原则：

  1. **主线程只碰界面**。所有网络/磁盘操作在 `Worker` 线程里跑，
     结果通过 `Bridge` 回主线程。
  2. **一个任务在跑时不让开第二个**。两个线程同时写 `state.json`
     会把登录态和配额写坏。
  3. **停止是立即的**。`ControlObserver` 每 tick 检查一次 stop 标志，
     连几十分钟的会话休息也能被打断（见 StudyRunner._rest）。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Any, Callable, List, Optional

from ..app import App
from ..config import Config
from ..errors import BudgetExhausted, CaptchaRequired, RiskLocked, Stopped, ZhsError
from ..logger import get as log
from ..observer import PHASE_ERROR, PHASE_IDLE, ControlObserver, Progress
from ..runner import StudyRunner
from . import theme
from .bridge import Bridge, Worker
from .tab_config import ConfigTab
from .tab_courses import CoursesTab
from .tab_log import LogTab, install_gui_sink
from .tab_study import StudyTab

APP_TITLE = "zhs-ghost · 智慧树自动学习"


class GuiObserver(ControlObserver):
    """把业务层的进度推到界面。

    带节流：学习循环本身是每秒一次，但真跑起来可能因为重试等触发更频繁，
    不节流的话 Tk 的主循环会被淹没。
    """

    def __init__(self, bridge: Bridge, sink: Callable[[Progress], None],
                 stop_event: threading.Event, pause_event: threading.Event):
        super().__init__(stop_event, pause_event)
        self.bridge = bridge
        self._sink = sink
        self._last = 0.0

    def progress(self, p: Progress) -> None:
        now = time.time()
        if now - self._last < 0.1 and p.percent < 1.0:
            return
        self._last = now
        self.bridge.post(self._sink, p)


class MainWindow(tk.Tk):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x740")
        self.minsize(900, 660)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.fonts = theme.apply(self)
        self.bridge = Bridge(self)

        self.cfg = Config.load(config_path)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.observer = GuiObserver(self.bridge, self._on_progress,
                                    self.stop_event, self.pause_event)
        self.worker = Worker()
        self.app: Optional[App] = None
        self._log_sink = None
        self._toast_timer: Optional[str] = None

        self._build_header()
        self._build_tabs()
        self._build_statusbar()

        # 窗口被别的方式销毁时（比如测试里直接 destroy），也要把 after 轮询停掉
        self.bind("<Destroy>", self._on_destroy)

        self.tab_config.reload()
        self._autostart_id: Optional[str] = self.after(120, self._autostart)

        # ---------------------------------------------------------------
        # 自动化测试钩子。
        #
        # 打包后必须能验证"点扫码登录不会卡死"这条真实路径 —— 之前 App
        # 初始化里的 loguru 递归就是在这条路上炸的，而源码级测试覆盖不到
        # 打包环境。设了这个环境变量，启动 2.5 秒后自动点一次按钮；
        # 手动使用永远不触发。
        # ---------------------------------------------------------------
        if os.environ.get("ZHS_AUTOTEST_LOGIN"):
            self.after(2500, self.action_login)

    def _on_destroy(self, event: Any) -> None:
        if event.widget is not self:
            return
        # 所有待执行的 after 都要显式取消：widget 销毁后 Tk 找不到回调命令，
        # 会在 stderr 刷一串 "invalid command name ..."
        for attr in ("_autostart_id", "_toast_timer"):
            timer = getattr(self, attr, None)
            if timer is not None:
                try:
                    self.after_cancel(timer)
                except Exception:
                    pass
                setattr(self, attr, None)
        self.bridge.close()

    # ================================================================ 布局

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=theme.PALETTE["bg"])
        header.pack(fill="x", padx=18, pady=(14, 4))

        left = tk.Frame(header, bg=theme.PALETTE["bg"])
        left.pack(side="left")
        tk.Label(left, text="zhs-ghost", bg=theme.PALETTE["bg"],
                 fg=theme.PALETTE["text"], font=self.fonts["title"]).pack(side="left")
        tk.Label(left, text="  智慧树自动学习 · 风控感知",
                 bg=theme.PALETTE["bg"], fg=theme.PALETTE["muted"],
                 font=self.fonts["small"]).pack(side="left", pady=(6, 0))

        right = tk.Frame(header, bg=theme.PALETTE["bg"])
        right.pack(side="right")
        ttk.Button(right, text="使用教程", style="Ghost.TButton",
                   command=self.open_docs).pack(side="right")
        ttk.Button(right, text="免责声明", style="Ghost.TButton",
                   command=self.open_disclaimer).pack(side="right", padx=(0, 4))
        ttk.Button(right, text="组件自检", style="Ghost.TButton",
                   command=self.action_selfcheck).pack(side="right", padx=(0, 4))

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self.tab_study = StudyTab(self.notebook, self)
        self.tab_courses = CoursesTab(self.notebook, self)
        self.tab_config = ConfigTab(self.notebook, self)
        self.tab_log = LogTab(self.notebook, self)

        self.notebook.add(self.tab_study, text="   学习   ")
        self.notebook.add(self.tab_courses, text="   课程   ")
        self.notebook.add(self.tab_config, text="   配置   ")
        self.notebook.add(self.tab_log, text="   日志   ")

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=theme.PALETTE["bg"], height=30)
        bar.pack(fill="x", padx=18, pady=(2, 10))

        self.status_label = tk.Label(bar, text="就绪", bg=theme.PALETTE["bg"],
                                     fg=theme.PALETTE["muted"], font=self.fonts["small"])
        self.status_label.pack(side="left")

        self.quota_label = tk.Label(bar, text="", bg=theme.PALETTE["bg"],
                                    fg=theme.PALETTE["muted"], font=self.fonts["small"])
        self.quota_label.pack(side="right")
        self._refresh_quota()

    # ================================================================ 基础设施

    def _ensure_app(self) -> App:
        if self.app is None:
            self.app = App(self.cfg)
            self._attach_log_sink()
            uid = self.app.passport.uuid or ""
            self.tab_study.set_account(bool(uid), uid)
        return self.app

    def _attach_log_sink(self) -> None:
        """必须等 App 建好再挂 —— `App.__init__` 里的 setup_logging 会
        `logger.remove()`，先挂就被清掉了。"""
        if self._log_sink is None:
            self._log_sink = install_gui_sink(self.bridge, self.tab_log)

    def _on_progress(self, p: Progress) -> None:
        self.tab_study.update_progress(p)
        self._refresh_quota()

    def _refresh_quota(self) -> None:
        if self.app is None:
            self.quota_label.configure(text="")
            return
        try:
            text = self.app.budget.report()
        except Exception:
            text = ""
        self.quota_label.configure(text=text)
        self.tab_study.set_quota(text)

    def set_status(self, text: str, state: str = "idle", sticky: bool = False) -> None:
        color = {
            "idle": theme.PALETTE["muted"], "running": theme.PALETTE["accent"],
            "ok": theme.PALETTE["ok"], "warn": theme.PALETTE["warn"],
            "error": theme.PALETTE["err"],
        }.get(state, theme.PALETTE["muted"])
        self.status_label.configure(text=text, fg=color)
        if self._toast_timer is not None:
            try:
                self.after_cancel(self._toast_timer)
            except Exception:
                pass
            self._toast_timer = None
        if not sticky:
            self._toast_timer = self.after(6000, lambda: self.status_label.configure(
                text="就绪", fg=theme.PALETTE["muted"]))

    def toast(self, text: str, state: str = "ok") -> None:
        self.set_status(text, state)

    def is_running(self) -> bool:
        return self.worker.busy

    # ================================================================ 任务

    def _run_job(self, name: str, fn: Callable[[], Any], *,
                 running: bool = True, on_done: Optional[Callable[[Any], None]] = None) -> None:
        if self.worker.busy:
            self.toast("已有任务在运行，请先停止", "warn")
            return

        self.tab_study.set_busy(True, running=running)
        self.set_status(f"{name}中…", "running", sticky=True)

        def target() -> Any:
            try:
                return fn()
            except Stopped:
                self.bridge.post(self._job_finished, f"{name}已停止", "warn", None)
            except BudgetExhausted as e:
                self.bridge.post(self._job_finished, f"配额用尽，正常收工：{e}", "ok", None)
            except CaptchaRequired as e:
                self.bridge.post(self._job_finished, f"人机验证未能通过：{e}", "error", None)
            except RiskLocked as e:
                self.bridge.post(self._job_finished, f"风控锁定，建议今天停手：{e}", "error", None)
            except ZhsError as e:
                self.bridge.post(self._job_finished, f"{name}失败：{e}", "error", None)
            except Exception as e:  # noqa: BLE001
                log().exception(e)
                self.bridge.post(self._job_finished, f"{name}异常：{e}", "error", None)
            return None

        def done(result: Any) -> None:
            if on_done:
                self.bridge.post(on_done, result)
            self.bridge.post(self._job_finished, f"{name}完成", "ok", result)

        if not self.worker.start(target, on_done=done,
                                 on_error=lambda e: self.bridge.post(
                                     self._job_finished, f"{name}异常：{e}", "error", None)):
            self.tab_study.set_busy(False)
            self.toast("已有任务在运行", "warn")

    def _job_finished(self, message: str, state: str, _result: Any) -> None:
        self.tab_study.set_busy(False)
        self._refresh_quota()
        self.set_status(message, state)
        if state == "error":
            self.notebook.select(self.tab_log)

    # ---------------------------------------------------------------- 动作

    def action_login(self) -> None:
        app = self._ensure_app()

        def job() -> None:
            app.login(on_qr=lambda img: self.bridge.post(self.tab_study.show_qr, img))

        def done(_r: Any) -> None:
            uid = app.passport.uuid or ""
            self.tab_study.hide_qr()
            self.tab_study.set_account(bool(uid), uid)
            self._refresh_quota()

        # running=True：扫码期间「停止」要保持可用，用户得能放弃这次登录
        self._run_job("登录", job, running=True, on_done=done)

    def action_fetch(self) -> None:
        app = self._ensure_app()

        def job() -> List[dict]:
            if not app.passport.uuid:
                app.login()
            return StudyRunner(app).list_courses()

        def done(courses: Any) -> None:
            self.tab_courses.set_courses(courses or [])
            self.tab_study.set_account(bool(app.passport.uuid), app.passport.uuid or "")

        self._run_job("拉取课程", job, running=False, on_done=done)

    def action_start(self, course_ids: Optional[List[str]] = None) -> None:
        app = self._ensure_app()
        if not app.passport.uuid:
            self.toast("请先登录", "warn")
            self.notebook.select(self.tab_study)
            return

        ids = list(course_ids) if course_ids else self.tab_courses.selected_ids()
        self.stop_event.clear()
        self.pause_event.clear()
        self.tab_study.reset_progress()
        runner = StudyRunner(app, self.observer)

        def job() -> None:
            if ids:
                for cid in ids:
                    self.observer.progress(Progress(
                        phase="study", course=str(cid), message=f"处理课程 {cid}"))
                    runner.run_course(str(cid))
            else:
                if not self.tab_courses.has_courses():
                    self.observer.progress(Progress(
                        phase="study", message="未指定课程，自动处理全部"))
                runner.run_all()

        self._run_job("学习", job)

    def action_stop(self) -> None:
        if not self.worker.busy:
            return
        self.stop_event.set()
        self.pause_event.clear()
        self.set_status("正在停止…", "warn", sticky=True)

    def action_pause(self) -> None:
        self.pause_event.set()
        self.set_status("已暂停", "warn", sticky=True)

    def action_resume(self) -> None:
        self.pause_event.clear()
        self.set_status("已继续", "running", sticky=True)

    def action_selfcheck(self) -> None:
        """组件自检。

        必须放后台线程：它会 import playwright / ddddocr（几百毫秒起步），
        还会 print 几十行输出。在主线程里跑同样会让窗口卡住。
        输出重定向到日志页，否则 windowed exe 里用户什么都看不到。
        """
        import io
        from contextlib import redirect_stdout

        from ..cli import selfcheck as run_selfcheck

        self.notebook.select(self.tab_log)

        def job() -> int:
            buf = io.StringIO()
            code = 1
            try:
                with redirect_stdout(buf):
                    code = run_selfcheck()
            except Exception as e:
                buf.write(f"[!] 自检异常: {e}")
            for line in buf.getvalue().splitlines():
                self.bridge.post(self.tab_log.append, line, "INFO")
            return code

        def done(code: Any) -> None:
            ok = code == 0
            self.set_status("组件自检通过" if ok else "组件自检发现问题（见日志）",
                            "ok" if ok else "error")

        self._run_job("组件自检", job, running=False, on_done=done)

    def open_log_dir(self) -> None:
        self._open_path(self.cfg.log.dir)

    def open_docs(self) -> None:
        self._open_doc("docs/使用教程.md",
                       "https://github.com/skyslight1/zhs-ghost/blob/main/docs/使用教程.md")

    def open_disclaimer(self) -> None:
        self._open_doc("DISCLAIMER.md",
                       "https://github.com/skyslight1/zhs-ghost/blob/main/DISCLAIMER.md")

    def _open_doc(self, relative: str, fallback_url: str) -> None:
        """优先打开本地文件（打包时随包分发），找不到再回落到 GitHub。"""
        from ..paths import candidate_roots

        names = (relative, os.path.basename(relative))
        for root in candidate_roots():
            for name in names:
                path = os.path.join(root, name)
                if os.path.isfile(path):
                    self._open_path(path)
                    return
        webbrowser.open(fallback_url)

    @staticmethod
    def _open_path(path: str) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
        except Exception:
            pass

    # ---------------------------------------------------------------- 生命周期

    def _autostart(self) -> None:
        """双击启动时的默认行为：没登录就提示一下，别自己乱跑。

        自动开始刷课听起来贴心，实际很危险 —— 用户可能只是打开看看，
        结果后台开始连发几个小时的上报。
        """
        if self.cfg.auth.use_qr or not (self.cfg.auth.username and self.cfg.auth.password):
            self.set_status("请先点「扫码登录」", "idle")
        else:
            self.set_status("已读取账号配置，点「开始学习」即可", "idle")

    def on_close(self) -> None:
        if self.worker.busy:
            if not messagebox.askyesno(APP_TITLE, "学习任务还在运行，确定要退出吗？\n退出会保存当前进度。"):
                return
            self.stop_event.set()
            self.worker.join(4.0)

        try:
            if self.app is not None:
                self.app.close()
            self.cfg.save()
        except Exception:
            pass

        if self._log_sink is not None:
            try:
                from loguru import logger
                logger.remove(self._log_sink)
            except Exception:
                pass

        self.bridge.close()
        self.destroy()


# ====================================================================== 启动

class _StreamProxy:
    """windowed exe 的 stdout / stderr 兜底。

    ⚠️ 绝对不能把写入转发给 loguru。

    踩过的坑：App 初始化时 `setup_logging()` 会把 `sys.stderr` 注册成一个
    loguru sink。如果这里的 write() 又去调 loguru，就变成：

        写日志 → 触发 stderr sink → _StreamProxy.write → 再调 loguru
              → 再触发 stderr sink → …

    无限递归，最后一屏 `RecursionError: maximum recursion depth exceeded`
    加一句 `lost sys.stderr`。因为 App 是在主线程里构造的，
    用户看到的就是：**点一下「扫码登录」，窗口直接未响应**。

    所以这里直接落文件，绕开 loguru。
    """

    def __init__(self, path: str = ""):
        self._path = path
        self._fh = None
        self._failed = False

    def _file(self):
        if self._fh is None and self._path and not self._failed:
            try:
                parent = os.path.dirname(os.path.abspath(self._path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                self._fh = open(self._path, "a", encoding="utf-8", errors="replace")
            except Exception:
                self._failed = True
                self._fh = None
        return self._fh

    def write(self, text: str) -> int:
        if not text:
            return 0
        fh = self._file()
        if fh is not None:
            try:
                fh.write(text)
                fh.flush()
            except Exception:
                self._failed = True
        return len(text)

    def flush(self) -> None:
        if self._fh is not None:
            try:
                self._fh.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"


def _redirect_streams(log_dir: str = "") -> None:
    """给 windowed exe 补上 stdout / stderr。

    不做这一步的话，任何一句 `print()` 都会因为 `sys.stdout is None`
    直接抛 AttributeError。
    """
    from ..paths import app_root

    if not log_dir:
        log_dir = os.path.join(app_root(), "logs")
    if sys.stdout is None:
        sys.stdout = _StreamProxy(os.path.join(log_dir, "stdout.log"))
    if sys.stderr is None:
        sys.stderr = _StreamProxy(os.path.join(log_dir, "stderr.log"))


def launch(config_path: Optional[str] = None) -> int:
    from ..paths import app_root, is_frozen

    # 双击启动时 cwd 可能是 system32，切到 exe 所在目录
    if is_frozen():
        try:
            os.chdir(app_root())
        except Exception:
            pass

    _redirect_streams()
    try:
        window = MainWindow(config_path)
    except Exception as e:
        # 建窗口就炸的话，除了弹框没别的办法让用户知道
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_TITLE, f"启动失败：\n{e}")
            root.destroy()
        except Exception:
            print(f"启动失败: {e}")
        raise
    window.mainloop()
    return 0
