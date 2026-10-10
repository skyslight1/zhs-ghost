"""通知：Server酱 / 钉钉 / Telegram / 本地响铃。

原项目只有 pushplus 和 bark，且用 GET 拼 URL（中文和特殊字符容易炸）。
这里统一 POST + JSON。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

import requests
from loguru import logger

from .config import NotifyConfig


class Notifier:
    def __init__(self, cfg: Optional[NotifyConfig] = None):
        self.cfg = cfg or NotifyConfig()

    def send(self, title: str, body: str = "") -> None:
        logger.info(f"[通知] {title}" + (f" | {body}" if body else ""))
        if not self.cfg.enabled:
            return
        if self.cfg.serverchan_key:
            self._post(f"https://sctapi.ftqq.com/{self.cfg.serverchan_key}.send",
                       data={"title": title[:100], "desp": body[:2000]})
        if self.cfg.dingtalk_webhook:
            self._post(self.cfg.dingtalk_webhook,
                       json={"msgtype": "text", "text": {"content": f"{title}\n{body}"}})
        if self.cfg.telegram_bot_token and self.cfg.telegram_chat_id:
            self._post(f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage",
                       json={"chat_id": self.cfg.telegram_chat_id, "text": f"{title}\n{body}"})
        if self.cfg.local_beep:
            beep()

    @staticmethod
    def _post(url: str, **kw) -> bool:
        try:
            r = requests.post(url, timeout=10, **kw)
            return r.status_code < 400
        except Exception as e:
            logger.warning(f"通知发送失败: {e}")
            return False


def beep(freq: int = 900, duration: int = 280, times: int = 3) -> None:
    try:
        if sys.platform == "win32":
            import winsound
            for _ in range(times):
                winsound.Beep(freq, duration)
        else:
            print("\a" * times, end="", flush=True)
    except Exception:
        pass
