"""人机验证中继：真实浏览器 + 自动过检 + 会话回灌。"""
from .browser import BrowserRelay, RelayConfig, to_playwright_cookies

__all__ = ["BrowserRelay", "RelayConfig", "to_playwright_cookies"]
