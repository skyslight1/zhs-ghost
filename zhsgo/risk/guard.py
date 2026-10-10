"""风控总控。

这是整个重写最核心的结构改动。

原项目的 code -12 处理是：
    if ret.code != ok_code:
        case -12: raise CaptchaException  →  fuckZhidaoCourse 直接 return
损失的是整门课，而且它和"网络错误""答案不存在"挤在同一个 except 分支里。

这里把风控抬成**请求层的可恢复状态**：
    ZhidaoApi 拼好请求 → Guard.call() → 命中 -12 → 唤中继过验证码 → 重发 → 返回结果
业务代码根本感知不到验证码存在，除非确实恢复失败才会抛 CaptchaRequired。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from ..clock import Clock
from ..errors import CaptchaRequired, RiskLocked
from ..logger import captcha as captcha_log
from ..logger import risk as risk_log
from ..util import AttrDict


class Relay(Protocol):
    """验证码中继协议：把浏览器拿到的会话凭证回灌进 HttpClient 并返回是否成功。"""

    def unlock(self, http: Any, rac_id: Optional[str]) -> bool: ...


class NullRelay:
    """没装 playwright 时的空实现：解锁必然失败，风控直接冒泡给上层。"""

    def unlock(self, http: Any, rac_id: Optional[str]) -> bool:
        return False


@dataclass
class GuardConfig:
    enabled: bool = True
    retry_after_unlock: int = 3
    settle_seconds: tuple[float, float] = (3.0, 9.0)
    # 单次运行允许触发的验证码次数上限，防止和中继一起陷入死循环
    max_captcha_events: int = 15
    # 中继失败后是否直接判定锁定
    soft_fail: bool = False


@dataclass
class GuardStats:
    captcha_events: int = 0
    recovered: int = 0
    failed: int = 0
    last_context: str = ""

    def describe(self) -> str:
        if not self.captcha_events:
            return "本次运行未触发验证码"
        return (f"触发验证码 {self.captcha_events} 次 | 自动恢复 {self.recovered} 次 | "
                f"失败 {self.failed} 次")


class Guard:
    def __init__(self, cfg: Optional[GuardConfig] = None, relay: Optional[Relay] = None,
                 clock: Optional[Clock] = None, http: Any = None,
                 notifier: Optional[Callable[[str, str], None]] = None):
        self.cfg = cfg or GuardConfig()
        self.relay = relay or NullRelay()
        self.clock = clock or Clock()
        self.http = http
        self.notifier = notifier
        self.stats = GuardStats()

    def bind(self, http: Any) -> None:
        self.http = http

    # ------------------------------------------------------------ 主入口

    def call(self, code_getter: Callable[[], AttrDict], retry: Callable[[], AttrDict], *,
             context: str = "", rac_id: Optional[str] = None,
             ok_code: Any = 0) -> AttrDict:
        """执行一次带风控恢复的请求。

        * `code_getter` 首次调用（已经发过一次的话可以复用结果）
        * `retry` 重发函数（每次调用都要重新构造 payload —— 密文带随机 IV，
          复用同一份密文是很明显的特征）
        """
        ret = code_getter()
        if not self.cfg.enabled or ok_code is None or ret.code == ok_code:
            return ret
        if ret.code != -12:
            return ret
        return self.recover(retry, context=context, rac_id=rac_id, ok_code=ok_code)

    def recover(self, retry: Callable[[], AttrDict], *, context: str = "",
                rac_id: Optional[str] = None, ok_code: Any = 0) -> AttrDict:
        self.stats.captcha_events += 1
        self.stats.last_context = context
        risk_log(f"风控触发 code=-12 | 场景: {context} | 第 {self.stats.captcha_events} 次")

        if self.stats.captcha_events > self.cfg.max_captcha_events:
            self.stats.failed += 1
            self._alert("验证码触发过于频繁", f"本次运行已触发 {self.stats.captcha_events} 次，停手")
            raise RiskLocked(f"验证码触发次数超过上限 {self.cfg.max_captcha_events}，停手")

        attempts = max(1, int(self.cfg.retry_after_unlock))
        last: Optional[AttrDict] = None

        for attempt in range(1, attempts + 1):
            ok = False
            try:
                ok = bool(self.relay.unlock(self.http, rac_id))
            except Exception as e:  # 中继自身出问题不该把整个流程炸掉
                captcha_log(f"中继异常: {e}")
            if not ok:
                captcha_log(f"第 {attempt}/{attempts} 次中继未能完成")
                break

            settle = random.uniform(*self.cfg.settle_seconds)
            self.clock.sleep(settle)

            try:
                last = retry()
            except Exception as e:
                captcha_log(f"重发失败，继续重试: {e}")
                continue

            if last.code == ok_code:
                self.stats.recovered += 1
                risk_log(f"风控已解除（第 {attempt} 次重试成功）")
                return last
            if last.code != -12:
                risk_log(f"重试返回了新的错误码 {last.code}，交给上层处理")
                return last
            captcha_log(f"仍然 -12，准备第 {attempt + 1} 次过检")

        self.stats.failed += 1
        self._alert("风控未能解除", f"场景 {context}，过检 {attempts} 次后仍被拦截")
        if self.cfg.soft_fail and last is not None:
            return last
        raise CaptchaRequired(
            f"过检后依旧被风控拦截（场景 {context}）"
        )

    # ------------------------------------------------------------ 告警

    def _alert(self, title: str, body: str) -> None:
        if not self.notifier:
            return
        try:
            self.notifier(f"【zhsgo】{title}", body)
        except Exception:
            pass

    def report(self) -> str:
        return self.stats.describe()
