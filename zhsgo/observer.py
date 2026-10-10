"""进度观察者 —— 让业务层不依赖具体前端。

CLI 用 `NullObserver`，行为跟以前完全一致；GUI 用它把状态推到界面上。

同时提供两个控制闸，都在学习循环里逐 tick 检查（响应延迟 ≤ 1 秒）：

  * `should_stop()` —— 用户点了停止 → 抛出 `Stopped` 沿调用栈退出
  * `gate()`        —— 用户点了暂停 → 在这里阻塞，直到恢复或停止

放在这里而不是写进 StudyRunner，是为了让"能不能暂停/停止"成为
业务层的固有能力，而不是 GUI 硬塞进去的补丁。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# 阶段常量（GUI 据此决定显示什么）
PHASE_IDLE = "idle"
PHASE_LOGIN = "login"
PHASE_FETCH = "fetch"
PHASE_STUDY = "study"
PHASE_EXAM = "exam"
PHASE_REST = "rest"
PHASE_DONE = "done"
PHASE_ERROR = "error"


@dataclass
class Progress:
    phase: str = PHASE_IDLE
    message: str = ""
    course: str = ""
    video: str = ""
    current: float = 0.0
    total: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.current / self.total))

    def describe(self) -> str:
        if self.total > 0:
            return f"{self.message} {self.percent * 100:.1f}%"
        return self.message


class Observer:
    """默认实现：全部空转。"""

    def progress(self, p: Progress) -> None:
        pass

    def should_stop(self) -> bool:
        return False

    def gate(self) -> None:
        pass

    def is_paused(self) -> bool:
        return False


class NullObserver(Observer):
    """什么都没发生。CLI 用它，保证和加观察者之前的行为逐字节一致。"""


class ControlObserver(Observer):
    """带停止/暂停闸门的观察者 —— GUI 用。"""

    def __init__(self, stop_event: Optional[threading.Event] = None,
                 pause_event: Optional[threading.Event] = None):
        self._stop = stop_event or threading.Event()
        self._pause = pause_event or threading.Event()

    # ------------------------------------------------------------ 闸门

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def is_paused(self) -> bool:
        return self._pause.is_set()

    def gate(self) -> None:
        """暂停期间阻塞在这里。

        粒度 0.2 秒：既不会让 CPU 空转，也能保证点了停止后立刻响应。
        """
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.2)

    # ------------------------------------------------------------ 外部控制

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()      # 暂停中也要能停

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def reset(self) -> None:
        self._stop.clear()
        self._pause.clear()
