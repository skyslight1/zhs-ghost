"""节拍整形 —— 决定"挂久了会不会被风控"的最大权重项。

对照原实现（fucker.py 主循环）：

    db_interval = 30
    while played_time < end_time:
        time.sleep(1)
        played_time += speed
        if elapsed_time % db_interval == 0:
            saveDatabaseIntervalTimeV2(...)

服务端能观测到的特征，条条都是机器人签名：

  1. 上报间隔恒定 30.000 秒。`elapsed_time` 每次 +1、循环体 sleep(1)，
     参数化后实际间隔永远贴在 30.0；真人会因为 tab 切换、GC、重传产生
     至少 ±2 秒抖动。时间序列是风控最廉价也最准的判据。
  2. `dateFormate = int(time.time())*1000`：先把毫秒抹掉再乘 1000，
     所有请求毫秒位恒为 000。统计"毫秒位为 0 的占比"，脚本用户≈100%，真人≈1%。
  3. 进度线性单调、零卡顿、零回退、跨视频无缝衔接。
  4. `-s 444` 直接把 Δprogress/Δtime 打到 444，而前端上限只有 1.5。

Pacer 把这些逐个打散，并且**所有涉及时间戳的地方都必须经过它** ——
这正是原项目做不到的：它的时间戳在 zhidaoQuery 里硬编码，没有统一出口。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional, Tuple

from ..clock import Clock


@dataclass
class PacerConfig:
    enabled: bool = True
    # 前端允许的上限：共享课 1.5x，校内课 1.25x。超过这个值等于自己举手。
    max_speed: float = 1.5
    default_speed: float = 1.25
    speed_jitter: float = 0.015
    # 单次循环 tick 的时长抖动（秒）。原实现是裸 sleep(1)，节拍过于整齐。
    tick_jitter: float = 0.06
    # 上报间隔（秒）。对数正态生成，右偏 —— describe() 里能看到实际分布。
    report_interval: Tuple[float, float] = (22.0, 47.0)
    report_sigma: float = 0.20
    # 微暂停：模拟真人离开/走神/被叫走
    pause_chance: float = 0.0025
    pause_seconds: Tuple[float, float] = (10.0, 70.0)
    # 偶发"长时间离开"，直接把下一次上报间隔拉长
    away_chance: float = 0.05
    away_extra: Tuple[float, float] = (70.0, 200.0)
    # 视频之间的休息
    inter_video_rest: Tuple[float, float] = (4.0, 90.0)
    # 时间戳
    real_millisecond_ts: bool = True
    ts_jitter_ms: Tuple[int, int] = (-40, 40)


class Pacer:
    def __init__(self, cfg: Optional[PacerConfig] = None, clock: Optional[Clock] = None):
        self.cfg = cfg or PacerConfig()
        self.clock = clock or Clock()
        self._last_ts = 0
        self._emitted: list[float] = []

    # ------------------------------------------------------------ 播放速度

    def speed(self, requested: Optional[float] = None) -> float:
        """夹到前端允许的上限内，并叠加真实播放器的微抖动。

        注意抖动的方向：当目标速度已经顶到上限时，只能往下抖 ——
        否则抖动会被 clamp 吃掉，速度退化成恒定的 max_speed，
        那反而变成了一个稳定特征。
        """
        c = self.cfg
        if not c.enabled:
            return float(requested or c.default_speed)
        target = float(requested or c.default_speed)
        base = max(1.0, min(target, c.max_speed))
        if base >= c.max_speed:
            delta = random.uniform(-c.speed_jitter, 0.0)
        else:
            delta = random.uniform(-c.speed_jitter, c.speed_jitter)
        return max(1.0, min(c.max_speed, base + delta))

    def tick_seconds(self) -> float:
        """单次循环 tick 的实际时长。

        原实现是裸 `time.sleep(1)`，每 tick 严格 1.000 秒。真人播放器的
        循环节拍不可能这么齐 —— 而"每 tick 恰好 1 秒"会让上报间隔被量化
        成整数秒，抹掉本应存在的自然抖动。
        """
        c = self.cfg
        if not c.enabled or c.tick_jitter <= 0:
            return 1.0
        return 1.0 + random.uniform(-c.tick_jitter, c.tick_jitter)

    def clamp_warning(self, requested: Optional[float]) -> Optional[str]:
        if requested and requested > self.cfg.max_speed:
            return (f"请求速度 {requested}x 超过前端上限 {self.cfg.max_speed}x，"
                    f"已夹紧（超高倍速是最容易被判风控的行为）")
        return None

    # ------------------------------------------------------------ 时间戳

    def ts_ms(self) -> int:
        """上报用时间戳。原实现的 `int(time.time())*1000` 毫秒位恒为 000。"""
        c = self.cfg
        if not (c.enabled and c.real_millisecond_ts):
            return int(self.clock.now()) * 1000
        now = int(self.clock.now() * 1000)
        now += random.randint(int(c.ts_jitter_ms[0]), int(c.ts_jitter_ms[1]))
        # Date.now() 单调递增；同一毫秒内连续两次调用也不该撞值
        if now <= self._last_ts:
            now = self._last_ts + random.randint(1, 9)
        self._last_ts = now
        return now

    # ------------------------------------------------------------ 上报节拍

    def next_report_interval(self) -> float:
        """下一次上报距离现在多少秒。"""
        c = self.cfg
        if not c.enabled:
            return 30.0
        lo, hi = c.report_interval
        mu = math.log((lo + hi) / 2.0)
        value = random.lognormvariate(mu, c.report_sigma)
        value = min(max(value, lo * 0.85), hi * 1.20)
        if random.random() < c.away_chance:
            value += random.uniform(*c.away_extra)
        self._emitted.append(value)
        if len(self._emitted) > 200:
            del self._emitted[:-200]
        return value

    # ------------------------------------------------------------ 暂停

    def roll_pause(self) -> float:
        """本 tick 是否触发一次微暂停，返回秒数（0 表示不暂停）。"""
        c = self.cfg
        if not c.enabled or random.random() >= c.pause_chance:
            return 0.0
        lo, hi = c.pause_seconds
        return random.triangular(lo, hi, lo)

    def rest_between_videos(self) -> float:
        c = self.cfg
        if not c.enabled:
            return 0.0
        return random.uniform(*c.inter_video_rest)

    # ------------------------------------------------------------ 诊断

    def describe(self) -> str:
        return (f"上报间隔∈[{self.cfg.report_interval[0]:.0f},{self.cfg.report_interval[1]:.0f}]s"
                f"(σ={self.cfg.report_sigma}) 速度≤{self.cfg.max_speed}x")

    def histogram(self, buckets: int = 6) -> str:
        """把已发出的间隔画成直方图，用来确认节拍真的被打散了。"""
        if not self._emitted:
            return "(无上报记录)"
        lo, hi = min(self._emitted), max(self._emitted)
        if hi - lo < 1e-6:
            return f"全部相同: {lo:.1f}s ← 说明节拍没生效"
        width = (hi - lo) / buckets
        counts = [0] * buckets
        for v in self._emitted:
            counts[min(buckets - 1, int((v - lo) / width))] += 1
        peak = max(counts)
        lines = []
        for i, c in enumerate(counts):
            bar = "#" * int(30 * c / peak)
            lines.append(f"  {lo + i * width:6.1f}~{lo + (i + 1) * width:6.1f}s | {bar} {c}")
        return "\n".join(lines)
