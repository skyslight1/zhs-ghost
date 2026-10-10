"""异常体系。

原 fuckZHS 用裸 Exception 传递所有错误，导致：
  * 风控信号和普通网络错误混在一个分支里处理；
  * 上层只能靠 `except Exception` 兜底，真正的风控被淹没在日志噪音里。

这里把"风控"提升为独立异常类型，让控制流能表达它。
"""
from __future__ import annotations

from typing import Any


class ZhsError(Exception):
    """所有本程序异常的基类。"""


class RiskError(ZhsError):
    """服务端风控相关。"""


class CaptchaRequired(RiskError):
    """服务端下发 code=-12，要求人机验证。

    这是**可恢复**状态：Guard 层会自动唤起中继过验证码并重试。
    只有在重试全部失败后才向上冒泡，表示需要人工介入。
    """


class RiskLocked(RiskError):
    """过完验证码依然被拦截。继续跑没有意义，应当停手。"""


class AuthError(ZhsError):
    """登录态失效。"""


class NoCookies(AuthError):
    pass


class UnsupportedCourse(ZhsError):
    """课程类型无法处理。"""


class BudgetExhausted(ZhsError):
    """配额用尽（单日时长 / 会话次数）。

    正常收工信号，不是错误 —— 但需要沿着调用栈一路退出，所以用异常表达。
    """


class Stopped(ZhsError):
    """用户主动停止（GUI 的停止按钮 / Ctrl+C）。

    和 BudgetExhausted 一样属于"正常终止"，调用方应当安静收尾而不是报错。
    """


class TimeLimitExceeded(ZhsError):
    """单门课程的时限用尽。"""


class RelayUnavailable(ZhsError):
    """验证码中继不可用（没装 playwright / 浏览器启动失败）。"""


class ApiError(ZhsError):
    """服务端返回了非预期业务码。"""

    def __init__(self, code: Any, message: str = "", url: str = "", payload: Any = None):
        super().__init__(f"code={code} url={url}\n{message}")
        self.code = code
        self.message = message
        self.url = url
        self.payload = payload
