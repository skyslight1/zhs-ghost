"""可替换的时钟。

学习循环里到处是 `sleep` 和 `time.time()`。把它们收敛到一个对象上，
测试就能换成假时钟把 3 小时的会话在毫秒内跑完，从而真正验证节拍逻辑，
而不是靠肉眼看代码猜。
"""
from __future__ import annotations

import time


class Clock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def ts_ms(self) -> int:
        return int(self.now() * 1000)

    # 便于 `with clock.hijack(x)` 之类的写法扩展
    def __repr__(self) -> str:  # pragma: no cover
        return f"<Clock {self.now():.0f}>"


class FakeClock(Clock):
    """测试用：sleep 只推进虚拟时间，不真的等。

    起始时间故意带非零毫秒 —— 真实 `time.time()` 的毫秒位是均匀分布的，
    从整秒开始会让"毫秒位为 0"的统计失真。
    """

    def __init__(self, start: float = 1_700_000_000.437):
        self.t = float(start)
        self.total_slept = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += float(seconds)
            self.total_slept += float(seconds)

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)
