"""日志。

原项目自研的 MonoLogger 把 5 个级别拆成 5 个 logger，各自的 handler 再被
统一 add/remove，行为很绕（`logger.info` 实际上写的是 "-info" 这个 logger）。

这里直接落在 loguru 上：一个 sink 到终端、一个 sink 到按天轮转的文件，
风控事件单独再落一份 risk.log，方便事后复盘"到底哪一步恶化成 -12"。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

from loguru import logger

_CONFIGURED = False


def setup(log_dir: str = "./logs", level: str = "INFO", to_console: bool = True) -> Any:
    global _CONFIGURED
    os.makedirs(log_dir, exist_ok=True)
    logger.remove()

    if to_console:
        logger.add(
            sys.stderr, level=level, colorize=True,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>",
        )
    logger.add(
        os.path.join(log_dir, "zhsgo_{time:YYYY-MM-DD}.log"),
        level="DEBUG", rotation="00:00", retention="14 days", encoding="utf-8",
        enqueue=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} | {message}",
    )
    # 风控事件单独留档：复盘 -12 的触发序列时只翻这一个文件
    logger.add(
        os.path.join(log_dir, "risk_{time:YYYY-MM-DD}.log"),
        level="WARNING", rotation="00:00", retention="30 days", encoding="utf-8",
        filter=lambda rec: "risk" in rec["extra"] or "captcha" in rec["extra"],
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {message}",
    )
    _CONFIGURED = True
    return logger


def get() -> Any:
    if not _CONFIGURED:
        setup()
    return logger


def risk(msg: str, **fields: Any) -> None:
    """记录一条风控相关事件（会进 risk.log）。"""
    logger.bind(risk=True).warning(msg, **fields)


def captcha(msg: str, **fields: Any) -> None:
    logger.bind(captcha=True).warning(msg, **fields)
