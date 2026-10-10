"""观看点（`ewssw` / `watchPoint`）。

原实现（zd_utils.WatchPoint）每次 `reset()` 都把 wp 重置成 `[0, 1]`，
而上报循环每批次结束都会 reset 一次，于是**每一批 ewssw 都以固定的
`0,1` 开头**，之后才接本批新增的点。

真前端的观看点是一条**连续推进的已观看时间轴**，只在视频开头出现一次起点。
每批都回头重报 0 和 1 是一个稳定的模式特征。

这里改成：视频开始时写入起点，之后每批只发本批新覆盖到的点，
`take()` 取出后游标继续向前，不回头。
"""
from __future__ import annotations


class WatchPoint:
    def __init__(self, interval: int = 2, init: float = 0, include_origin: bool = True):
        self.interval = max(1, int(interval))
        self.include_origin = include_origin
        self._last = 0
        self._pending: list[int] = []
        self._reset(init)

    # ---------------------------------------------------------------- 内部

    def _reset(self, init: float) -> None:
        self._last = int(init) or 1
        self._pending = [0, 1] if self.include_origin else []

    @staticmethod
    def encode(t: int) -> int:
        """与前端一致：`floor(t / 5) + 2`。"""
        return int(t // 5 + 2)

    # ---------------------------------------------------------------- 对外

    def add(self, end: float, start: float | None = None) -> None:
        """把 [start 或上次游标, end] 之间新增的点登记进去。"""
        end_i = int(end)
        start_i = self._last if start is None else int(start)
        if end_i <= start_i:
            self._last = max(self._last, end_i)
            return
        for t in range(start_i + self.interval, end_i + 1, self.interval):
            self._pending.append(self.encode(t))
        self._last = end_i

    def mark(self, t: float) -> None:
        self._last = max(self._last, int(t))

    def get(self) -> str:
        return ",".join(map(str, self._pending))

    def take(self) -> str:
        """取出本批并清空；游标保持连续，下一批不会回头。"""
        out = self.get()
        self._pending = []
        return out

    def reset_for_video(self, init: float = 0) -> None:
        self._reset(init)

    @property
    def last(self) -> int:
        return self._last

    def __len__(self) -> int:
        return len(self._pending)
