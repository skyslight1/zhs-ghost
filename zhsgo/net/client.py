"""HTTP 传输层。

职责边界（这是和原项目最大的结构差异）：
  * `HttpClient` 只干传输：拼头、发请求、解析 JSON、重试传输层错误；
  * **不管节拍** —— 什么时候发由 `risk.Pacer` 决定；
  * **不管风控** —— code -12 由 `risk.Guard` 接管；
  * 不做业务判断。

原项目把这三件事混在 `_apiQuery` / `zhidaoQuery` / 各业务方法里，
导致风控逻辑散落在 60 多个调用点，改一处漏一处。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.cookies import RequestsCookieJar
from urllib3.util.retry import Retry

from ..clock import Clock
from ..errors import ZhsError
from ..util import AttrDict, wrap
from .fingerprint import Fingerprint


class TransportError(ZhsError):
    """网络层失败（连接、超时、非 JSON 响应）。"""


class BadStatus(TransportError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} {url}\n{body[:400]}")
        self.status = status


class HttpClient:
    def __init__(self, fingerprint: Fingerprint, clock: Optional[Clock] = None,
                 proxies: Optional[Dict[str, str]] = None, timeout: float = 15.0):
        self.fp = fingerprint
        self.clock = clock or Clock()
        self.timeout = timeout

        self.session = requests.Session()
        # 清空 requests 默认头，改由 Fingerprint 全量提供 —— 否则 requests 自带的
        # `User-Agent: python-requests/x.y` 会残留，头顺序也会被 session 默认值打乱
        self.session.headers.clear()
        self.session.proxies.update(proxies or {})

        adapter = HTTPAdapter(
            max_retries=Retry(total=4, backoff_factor=0.35, raise_on_status=False,
                              status_forcelist=[500, 502, 503, 504]),
            pool_connections=8, pool_maxsize=16,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.request_log: List[Dict[str, Any]] = []
        self.on_request: List[Callable[[str, str], None]] = []

    # -------------------------------------------------------------- 会话状态

    @property
    def cookies(self) -> RequestsCookieJar:
        return self.session.cookies

    @cookies.setter
    def cookies(self, jar: RequestsCookieJar) -> None:
        self.session.cookies = jar

    # -------------------------------------------------------------- 请求

    def _headers(self, url: str, method: str, content_type: Optional[str]) -> Dict[str, str]:
        h = self.fp.headers(content_type)
        h = self.fp.apply_referer(h, url, method)
        return h

    def _note(self, method: str, url: str) -> None:
        self.request_log.append({"at": self.clock.now(), "method": method, "url": url})
        if len(self.request_log) > 500:
            del self.request_log[:200]
        for cb in self.on_request:
            try:
                cb(method, url)
            except Exception:
                pass

    def _finish(self, resp: requests.Response, url: str, *, expect_json: bool = True) -> AttrDict:
        if resp.status_code >= 400:
            raise BadStatus(resp.status_code, url, resp.text)
        if not expect_json:
            return AttrDict({"_text": resp.text}, default=None)
        try:
            return wrap(resp.json(), default=None)
        except ValueError as e:
            # 有些接口返回 jsonp 包装：`callback({...})`
            text = resp.text.strip()
            if "(" in text and text.endswith(")"):
                inner = text[text.index("(") + 1: -1]
                try:
                    import json
                    return wrap(json.loads(inner), default=None)
                except Exception:
                    pass
            raise TransportError(f"响应不是 JSON: {url}\n{text[:300]}") from e

    def get(self, url: str, params: Optional[dict] = None, *,
            content_type: Optional[str] = None, expect_json: bool = True,
            navigation: bool = False) -> AttrDict:
        method = "GET"
        self._note(method, url)
        headers = self._headers(url, method, content_type)
        if navigation:
            headers = self.fp.headers(None, navigation=True)
            headers.update({"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
                            "Sec-Fetch-User": "?1"})
        try:
            resp = self.session.get(url, params=params, headers=headers,
                                    timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as e:
            raise TransportError(f"GET {url} 失败: {e}") from e
        return self._finish(resp, url, expect_json=expect_json)

    def post(self, url: str, data: Optional[dict] = None, *,
             content_type: str = "form", expect_json: bool = True) -> AttrDict:
        method = "POST"
        self._note(method, url)
        headers = self._headers(url, method, content_type)
        body: Any
        if content_type == "json":
            body = data
            try:
                resp = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                raise TransportError(f"POST {url} 失败: {e}") from e
        else:
            body = data
            try:
                resp = self.session.post(url, data=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                raise TransportError(f"POST {url} 失败: {e}") from e
        return self._finish(resp, url, expect_json=expect_json)

    def raw_get(self, url: str, params: Optional[dict] = None, *, stream: bool = False,
                with_fingerprint: bool = True) -> requests.Response:
        """需要原始 Response 时用（下载视频分片、取图片等）。"""
        headers = self._headers(url, "GET", None) if with_fingerprint else {}
        try:
            return self.session.get(url, params=params, headers=headers,
                                    timeout=self.timeout, stream=stream)
        except requests.RequestException as e:
            raise TransportError(f"GET {url} 失败: {e}") from e

    # -------------------------------------------------------------- 诊断

    def pacing_report(self, window: float = 600.0) -> Dict[str, Any]:
        """最近一段时间的请求间隔统计 —— 用来检查节拍是否真的被打散了。"""
        now = self.clock.now()
        times = [r["at"] for r in self.request_log if now - r["at"] <= window]
        times.sort()
        gaps = [round(times[i + 1] - times[i], 3) for i in range(len(times) - 1)]
        if not gaps:
            return {"count": len(times), "gaps": [], "mean": None, "unique": 0}
        return {
            "count": len(times),
            "gaps": gaps[-20:],
            "mean": round(sum(gaps) / len(gaps), 3),
            "unique": len(set(gaps)),
            "min": min(gaps),
            "max": max(gaps),
        }


class Throttle:
    """最小请求间隔守卫（防止某个分支忘了走 Pacer 而狂发请求）。"""

    def __init__(self, min_gap: float = 0.35, clock: Optional[Clock] = None):
        self.min_gap = min_gap
        self.clock = clock or Clock()
        self._last = 0.0

    def wait(self) -> float:
        now = self.clock.now()
        delta = now - self._last
        if delta < self.min_gap:
            sleep_for = self.min_gap - delta
            self.clock.sleep(sleep_for)
            now = self.clock.now()
        self._last = now
        return now
