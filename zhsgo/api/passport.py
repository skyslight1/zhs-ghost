"""登录：账号密码 + 二维码。

原项目里 `Fucker.cookies` 的 setter 有个副作用：解析 CASLOGC 拿 uuid。
这里把它显式拆成 `Passport.uuid_from(cookies)`，避免"赋值 cookie"这种
读起来无害的操作抛出 `ValueError("Cookies invalid")`。
"""
from __future__ import annotations

import json
import time
from base64 import b64decode
from typing import Any, Callable, Dict, Optional
from urllib.parse import unquote_plus

from requests.cookies import RequestsCookieJar

from ..clock import Clock
from ..errors import ApiError, AuthError, NoCookies
from ..logger import get as log
from ..net import HttpClient, endpoints as ep
from ..util import AttrDict, jar_from_dict

QR_POLL_INTERVAL = 0.6
QR_MAX_WAIT = 180.0


class Passport:
    def __init__(self, http: HttpClient, clock: Optional[Clock] = None,
                 proxies: Optional[Dict[str, str]] = None):
        self.http = http
        self.clock = clock or Clock()
        self.proxies = proxies or {}
        self.uuid: Optional[str] = None

    # ------------------------------------------------------------ uuid

    @staticmethod
    def uuid_from(cookies: RequestsCookieJar) -> Optional[str]:
        try:
            raw = cookies.get("CASLOGC")
            if not raw:
                return None
            return json.loads(unquote_plus(raw))["uuid"]
        except Exception:
            return None

    def adopt(self, cookies: RequestsCookieJar) -> str:
        """接管一份 cookie，解析出 uuid 并打上 exitRecod 标记。"""
        if not cookies or not len(cookies):
            raise NoCookies("cookie 为空")
        uid = self.uuid_from(cookies)
        if not uid:
            raise AuthError("cookie 里没有 CASLOGC，无法解析 uuid（大概率是登录态已失效）")
        self.uuid = uid
        cookies[f"exitRecod_{uid}"] = "2"
        self.http.cookies = cookies
        return uid

    # ------------------------------------------------------------ 账号密码

    def login_password(self, username: str, password: str) -> RequestsCookieJar:
        if not username or not password:
            raise AuthError("账号或密码为空")

        self.http.get(ep.LOGIN_PAGE, navigation=True)
        info = self.http.post(ep.VALIDATE_ACCOUNT, {"account": username, "password": password})

        status = info.get("status")
        if status == ep.CODE_LOGIN_BAD_PASSWORD:
            raise AuthError("账号或密码错误")
        if status == ep.CODE_LOGIN_TOO_MANY:
            raise AuthError("失败次数过多，需要验证码 —— 请改用二维码登录")
        if status == ep.CODE_LOGIN_NEED_SMS:
            raise AuthError("该账号需要短信验证 —— 请先用浏览器登录一次，把设备加入白名单")

        uid = info.get("uuid")
        if not uid:
            raise AuthError(f"登录响应缺少 uuid: {info}")

        need = self.http.get(ep.CHECK_NEED_AUTH, {"uuid": uid}).get("rt", {}) or {}
        if need.get("needAuth"):
            raise AuthError("账号需要额外认证 —— 请先用浏览器完成一次登录")

        pwd = info.get("pwd")
        self.http.get(ep.LOGIN_PAGE, {"account": username, "pwd": pwd, "validate": 0},
                      navigation=True)
        jar = self.http.cookies.copy()
        self.adopt(jar)
        log().info("账号密码登录成功")
        return jar

    # ------------------------------------------------------------ 二维码

    def login_qr(self, on_qr: Optional[Callable[[bytes], None]] = None,
                 *, timeout: float = QR_MAX_WAIT, poll: float = QR_POLL_INTERVAL) -> RequestsCookieJar:
        self.http.get(ep.LOGIN_PAGE, navigation=True)
        raw = self.http.get(ep.QR_IMAGE)
        token = raw.get("qrToken")
        img_b64 = raw.get("img")
        if not token or not img_b64:
            raise AuthError(f"获取二维码失败: {raw}")

        image = b64decode(img_b64)
        if on_qr:
            on_qr(image)

        deadline = self.clock.now() + timeout
        scanned = False
        while self.clock.now() < deadline:
            self.clock.sleep(poll)
            info = self.http.get(ep.QR_INFO, {"qrToken": token})
            status = info.get("status")
            message = info.get("msg", "")

            if status == -1:
                continue
            if status == 0:
                if not scanned:
                    scanned = True
                    log().info(f"二维码已扫描: {message}")
                continue
            if status == 1:
                log().info("已获取一次性登录凭证")
                self.http.get(ep.LOGIN_PAGE, {"pwd": info.get("oncePassword")}, navigation=True)
                jar = self.http.cookies.copy()
                self.adopt(jar)
                log().info("二维码登录成功")
                return jar
            if status == 2:
                raise AuthError(f"二维码已过期: {message}")
            if status == 3:
                raise AuthError("用户在手机上取消了登录")
            raise AuthError(f"二维码登录未知状态 {status}: {message}")

        raise AuthError(f"等待扫码超时（{timeout:.0f}s）")

    # ------------------------------------------------------------ 校验

    def ensure_alive(self) -> None:
        if not self.http.cookies or not len(self.http.cookies):
            raise NoCookies("尚未登录")
        if not self.uuid:
            self.adopt(self.http.cookies)
