"""会话与配额管理 —— 解决"长时间挂机"这件事本身。

风控最终判据里有一维误伤率最低、最安全：**时长**。真人不可能

  * 连续在线 8 小时不间断；
  * 一天刷 10 小时课；
  * 凌晨三点到早上七点满速推进。

原项目完全没有这一层（只有个可选的 `-l` 单课时限）。这里把它做成硬性纪律，
并跨进程持久化 —— 中途重启脚本也接得上，不会又从头算 4 小时。
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from ..clock import Clock
from ..errors import BudgetExhausted
from ..logger import risk as risk_log


@dataclass
class BudgetConfig:
    enabled: bool = True
    state_file: str = "./state/budget.json"
    session_minutes: Tuple[float, float] = (95.0, 160.0)
    rest_minutes: Tuple[float, float] = (20.0, 55.0)
    daily_minutes: float = 250.0
    daily_sessions: int = 4
    # 单门课程的时限（分钟），0 表示不限。对应原项目 -l
    per_course_minutes: float = 0.0


class Budget:
    def __init__(self, cfg: Optional[BudgetConfig] = None, clock: Optional[Clock] = None,
                 state: Optional[dict] = None):
        self.cfg = cfg or BudgetConfig()
        self.clock = clock or Clock()
        self.state = state if state is not None else {}
        if self.cfg.state_file:
            self.state.setdefault("budget", {})
            self._load()
        self._roll_if_new_day()
        self._session_started: Optional[float] = self.q.get("session_started")
        self._course_time: dict = self.q.setdefault("course_time", {})

    # ------------------------------------------------------------ 持久化

    def _load(self) -> None:
        path = self.cfg.state_file
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    disk = json.load(f) or {}
                if isinstance(disk, dict) and "budget" in disk:
                    self.state["budget"] = disk["budget"]
        except Exception:
            pass

    def save(self) -> None:
        if not self.cfg.state_file:
            return
        path = self.cfg.state_file
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    @property
    def q(self) -> dict:
        return self.state.setdefault("budget", {})

    def _roll_if_new_day(self) -> None:
        today = date.today().isoformat()
        q = self.q
        if q.get("date") != today:
            if q.get("date"):
                risk_log(f"跨天重置配额：{q.get('date')} 已学 "
                         f"{float(q.get('seconds', 0)) / 60:.0f} 分钟")
            q.clear()
            q.update({"date": today, "seconds": 0.0, "sessions": 0, "course_time": {}})

    # ------------------------------------------------------------ 纪律

    def _roll_session_target(self) -> float:
        lo, hi = self.cfg.session_minutes
        return random.triangular(lo, hi, lo) * 60.0

    def before_video(self, course_id: Optional[str] = None) -> float:
        """进入下一个视频前调用。返回需要先休息的秒数（0 = 立即继续）。"""
        if not self.cfg.enabled:
            return 0.0

        total = float(self.q.get("seconds", 0.0))
        if total >= self.cfg.daily_minutes * 60.0:
            raise BudgetExhausted(
                f"今日已学习 {total / 60:.1f} 分钟，达到上限 "
                f"{self.cfg.daily_minutes:.0f} 分钟，收工"
            )

        if course_id is not None and self.cfg.per_course_minutes > 0:
            used = float(self._course_time.get(str(course_id), 0.0))
            if used >= self.cfg.per_course_minutes * 60.0:
                raise BudgetExhausted(
                    f"课程 {course_id} 已达单课时限 {self.cfg.per_course_minutes:.0f} 分钟"
                )

        now = self.clock.now()
        if self._session_started is None:
            sessions = int(self.q.get("sessions", 0))
            if sessions >= self.cfg.daily_sessions:
                raise BudgetExhausted(
                    f"今日已完成 {sessions} 次会话，达到上限 {self.cfg.daily_sessions} 次"
                )
            self._session_started = now
            self.q["session_started"] = now
            self.q["sessions"] = sessions + 1
            self.q["target_seconds"] = self._roll_session_target()
            risk_log(f"开始第 {self.q['sessions']}/{self.cfg.daily_sessions} 次会话，"
                     f"本次目标 {self.q['target_seconds'] / 60:.0f} 分钟")
            self.save()
            return 0.0

        elapsed = now - self._session_started
        target = float(self.q.get("target_seconds") or self._roll_session_target())
        if elapsed >= target:
            lo, hi = self.cfg.rest_minutes
            rest = random.uniform(lo, hi) * 60.0
            risk_log(f"本次会话已连续 {elapsed / 60:.0f} 分钟，强制休息 {rest / 60:.0f} 分钟")
            self._session_started = None
            self.q.pop("session_started", None)
            self.q.pop("target_seconds", None)
            self.save()
            return rest
        return 0.0

    def tick(self, seconds: float, course_id: Optional[str] = None) -> None:
        """累加学习时长；超过单日上限时抛 `BudgetExhausted` 中断循环。

        让 tick 抛异常而不是返回布尔值，是因为"到点收工"必须沿着嵌套的
        课程/章节/视频循环一路退出 —— 异常是最省事也最不容易漏的通道。
        """
        if not self.cfg.enabled or seconds <= 0:
            return
        self.q["seconds"] = float(self.q.get("seconds", 0.0)) + seconds
        if course_id is not None:
            key = str(course_id)
            self._course_time[key] = float(self._course_time.get(key, 0.0)) + seconds

        if self.daily_seconds() >= self.cfg.daily_minutes * 60.0:
            raise BudgetExhausted(
                f"今日已学习 {self.daily_seconds() / 60:.1f} 分钟，"
                f"达到上限 {self.cfg.daily_minutes:.0f} 分钟，收工"
            )

    def session_elapsed(self) -> float:
        if self._session_started is None:
            return 0.0
        return self.clock.now() - self._session_started

    def daily_seconds(self) -> float:
        return float(self.q.get("seconds", 0.0))

    def report(self) -> str:
        return (f"今日 {self.daily_seconds() / 60:.1f}/{self.cfg.daily_minutes:.0f} 分钟 | "
                f"会话 {self.q.get('sessions', 0)}/{self.cfg.daily_sessions} | "
                f"本次会话已 {self.session_elapsed() / 60:.0f} 分钟")

    def close_session(self) -> None:
        self._session_started = None
        self.q.pop("session_started", None)
        self.q.pop("target_seconds", None)
        self.save()
