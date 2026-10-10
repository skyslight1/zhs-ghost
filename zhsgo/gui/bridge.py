"""后台线程 ↔ Tk 主线程 的桥。

Tkinter 不是线程安全的 —— 任何 widget 操作都必须在主线程执行。
学习任务要跑几分钟到几小时，绝不能塞在主线程里（界面会假死），

所以约定：
  * 后台线程只做网络/计算，完成后把回调 `bridge.post(fn, ...)` 丢进队列；
  * 主线程每 40ms 取一次队列并执行。

这个模式贯穿整个 GUI，是它不会卡死的唯一原因。
"""
from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable, Optional, Tuple


class Bridge:
    def __init__(self, root: Any, interval_ms: int = 40):
        self.root = root
        self.interval_ms = interval_ms
        self._queue: "queue.Queue[Tuple[Callable, tuple, dict]]" = queue.Queue()
        self._closed = False
        self._timer: Optional[str] = None
        self._schedule()

    # ------------------------------------------------------------ 投递

    def post(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        """从任意线程投递一个"在主线程执行"的调用。"""
        if not self._closed:
            self._queue.put((fn, args, kwargs))

    # ------------------------------------------------------------ 消费

    def _schedule(self) -> None:
        if self._closed:
            return
        try:
            self._timer = self.root.after(self.interval_ms, self._pump)
        except Exception:
            # 窗口已经销毁，after 会抛 TclError。
            # 这里必须自己收尾，否则每次销毁窗口都会在 stderr 留下一串
            # "while executing ..._pump" 的噪音。
            self._closed = True
            self._timer = None

    def _pump(self) -> None:
        if self._closed:
            return
        handled = 0
        try:
            while handled < 200:          # 单次最多处理 200 条，避免饿死界面
                fn, args, kwargs = self._queue.get_nowait()
                handled += 1
                try:
                    fn(*args, **kwargs)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self._schedule()

    def close(self) -> None:
        self._closed = True
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None


class Worker:
    """单实例后台任务线程。

    同一时刻只允许一个任务在跑（登录 / 拉清单 / 学习互斥），
    否则会出现两个线程同时写 `state.json` 的情况。
    """

    def __init__(self, name: str = "zhsgo-worker"):
        self.name = name
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, target: Callable[[], Any], on_done: Optional[Callable] = None,
              on_error: Optional[Callable[[BaseException], None]] = None) -> bool:
        if self.busy:
            return False

        def _run() -> None:
            try:
                result = target()
            except BaseException as e:      # noqa: BLE001 —— 后台线程必须兜住一切
                if on_error:
                    on_error(e)
            else:
                if on_done:
                    on_done(result)
            finally:
                with self._lock:
                    self._thread = None

        with self._lock:
            self._thread = threading.Thread(target=_run, name=self.name, daemon=True)
            self._thread.start()
        return True

    def join(self, timeout: Optional[float] = None) -> None:
        with self._lock:
            t = self._thread
        if t is not None:
            t.join(timeout)
