"""登录：账号密码 + 二维码。

原项目里 `Fucker.cookies` 的 setter 有个副作用：解析 CASLOGC 拿 uuid。
这里把它显式拆成 `Passport.uuid_from(cookies)`，避免"赋值 cookie"这种
读起来无害的操作抛出 `ValueError("Cookies invalid")`。
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Callable, Dict, Optional
from urllib.parse import unquote_plus

from requests.cookies import RequestsCookieJar

from ..clock import Clock
from ..errors import ApiError, AuthError, NoCookies, Stopped
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

    @staticmethod
    def _payload(raw: Any) -> AttrDict:
        """把智慧树登录接口的响应统一成一层字典。"""
        if not isinstance(raw, dict):
            raise AuthError(f"智慧树登录接口返回格式异常: {raw!r}")
        payload = raw
        for key in ("data", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                payload = nested
                break
        return AttrDict(payload, default=None)

    @staticmethod
    def _decode_qr_image(value: Any) -> bytes:
        if not isinstance(value, str) or not value.strip():
            raise AuthError("智慧树二维码图片为空")
        text = value.strip()
        if "," in text and text.lower().startswith("data:image/"):
            text = text.split(",", 1)[1]
        text = "".join(text.split())
        text += "=" * (-len(text) % 4)
        try:
            image = base64.b64decode(text, altchars=b"-_", validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AuthError("智慧树二维码图片不是有效的 Base64") from exc
        if not image:
            raise AuthError("智慧树二维码图片为空")
        return image

    @staticmethod
    def _check_cancel(cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise Stopped("二维码登录已取消")

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

        self.http.get(ep.LOGIN_PAGE, navigation=True, expect_json=False)

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
                      navigation=True, expect_json=False)
        jar = self.http.cookies.copy()
        self.adopt(jar)
        log().info("账号密码登录成功")
        return jar

    # ------------------------------------------------------------ 二维码

    def login_qr(self, on_qr: Optional[Callable[[bytes], None]] = None,
                 *, timeout: float = QR_MAX_WAIT, poll: float = QR_POLL_INTERVAL,
                 cancel_event: Any = None) -> RequestsCookieJar:
        self._check_cancel(cancel_event)
        self.http.get(ep.LOGIN_PAGE, navigation=True, expect_json=False)
        self._check_cancel(cancel_event)

        raw = self._payload(self.http.get(ep.QR_IMAGE))
        token = raw.get("qrToken") or raw.get("token")
        img_b64 = raw.get("img") or raw.get("image") or raw.get("qrImg")
        if not token:
            raise AuthError(f"获取智慧树二维码失败：响应缺少 qrToken: {raw}")
        image = self._decode_qr_image(img_b64)
        self._check_cancel(cancel_event)
        if on_qr:
            on_qr(image)

        deadline = self.clock.now() + timeout
        scanned = False
        while self.clock.now() < deadline:
            self._check_cancel(cancel_event)
            self.clock.sleep(poll)
            self._check_cancel(cancel_event)
            info = self._payload(self.http.get(ep.QR_INFO, {"qrToken": token}))
            status = info.get("status")
            message = info.get("msg") or info.get("message") or ""

            if status == -1:
                continue
            if status == 0:
                if not scanned:
                    scanned = True
                    log().info(f"二维码已扫描: {message}")
                continue
            if status == 1:
                once_password = info.get("oncePassword") or info.get("pwd")
                if not once_password:
                    raise AuthError(f"智慧树登录成功响应缺少一次性凭证: {info}")
                self._check_cancel(cancel_event)
                log().info("已获取一次性登录凭证")
                self.http.get(ep.LOGIN_PAGE, {"pwd": once_password},
                              navigation=True, expect_json=False)
                self._check_cancel(cancel_event)
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
