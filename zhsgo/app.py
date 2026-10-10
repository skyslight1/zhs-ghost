"""应用组装：把各层接成一个对象，并持有跨进程状态。

装配顺序体现依赖方向：
    clock → pacer/budget → fingerprint → http → guard(relay) → apis → runner
Guard 必须在 http 之后创建（它要 bind http 以便中继回灌 cookie），
而 API 层只拿到 Guard 的引用 —— 它们永远看不到验证码。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .ai.client import Backend, OpenAICompatBackend, ZhsLlmBackend
from .api import AiCourseApi, ExamApi, HikeApi, Passport, ZhidaoApi
from .clock import Clock
from .config import Config
from .errors import ZhsError
from .logger import get as log
from .logger import setup as setup_logging
from .net import HttpClient
from .net.fingerprint import Fingerprint
from .notify import Notifier
from .risk import Budget, Guard, Pacer
from .risk.guard import NullRelay
from .relay import BrowserRelay
from .util import jar_from_list, jar_to_list, stderr_safe


@dataclass
class AppState:
    data: Dict[str, Any]

    @property
    def cookies(self) -> List[dict]:
        return self.data.get("cookies") or []

    @cookies.setter
    def cookies(self, items: List[dict]) -> None:
        self.data["cookies"] = items


class App:
    def __init__(self, cfg: Config, clock: Optional[Clock] = None):
        stderr_safe()
        self.cfg = cfg
        setup_logging(cfg.log.dir, cfg.log.level)

        self.clock = clock or Clock()
        self.state = AppState(self._load_state())

        # 指纹生成一次就固定下来：换号不换指纹，别每次运行都刷新
        stored = self.state.data.get("fingerprint")
        if stored:
            self.fingerprint = Fingerprint.from_dict(stored)
        else:
            self.fingerprint = Fingerprint.generate()
            self.state.data["fingerprint"] = self.fingerprint.to_dict()
            self.save_state()

        self.pacer = Pacer(cfg.pacer, self.clock)
        self.budget = Budget(cfg.budget, self.clock, self.state.data)
        self.notifier = Notifier(cfg.notify)

        self.http = HttpClient(self.fingerprint, self.clock, cfg.proxies, cfg.timeout)

        if cfg.relay.enabled:
            self.relay: Any = BrowserRelay(cfg.relay, self.clock, self.notifier.send)
        else:
            self.relay = NullRelay()
            log().warning("relay.enabled=false：验证码将无法自动处理")

        self.guard = Guard(cfg.guard, self.relay, self.clock, self.http, self.notifier.send)

        self.passport = Passport(self.http, self.clock, cfg.proxies)
        self.zhidao = ZhidaoApi(self.http, self.guard, self.pacer, self._uuid)
        self.hike = HikeApi(self.http, self.guard, self.pacer, self._uuid)
        self.ai_course = AiCourseApi(self.zhidao)
        self.exam = ExamApi(self.zhidao)

        self._backend: Optional[Backend] = None

        if cfg.auth.save_cookies and self.state.cookies:
            try:
                self.http.cookies = jar_from_list(self.state.cookies)
                uid = self.passport.adopt(self.http.cookies)
                log().info(f"已恢复上次的登录态 (uuid={uid})")
            except Exception as e:
                log().warning(f"恢复登录态失败，需要重新登录: {e}")
                self.http.cookies.clear()
                self.state.cookies = []
                self.save_state()

    # ---------------------------------------------------------------- 状态

    def _load_state(self) -> Dict[str, Any]:
        path = self.cfg.state_file
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                log().warning(f"读取 state 失败，重建: {e}")
        return {}

    def save_state(self) -> None:
        path = self.cfg.state_file
        if not path:
            return
        try:
            if self.cfg.auth.save_cookies and self.http.cookies:
                self.state.cookies = jar_to_list(self.http.cookies)
            self.budget.save()
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.state.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log().warning(f"保存 state 失败: {e}")

    def _uuid(self) -> str:
        """传给 API 层的 uuid 取值器（闭包绑定在实例上，登录后自动生效）。"""
        return self.passport.uuid or ""

    # ---------------------------------------------------------------- 登录

    def login(self, on_qr=None, *, force: bool = False, qr: bool = False,
              cancel_event=None) -> None:
        cfg = self.cfg.auth
        if not force and self.http.cookies and len(self.http.cookies) and self.passport.uuid:
            log().info("已有登录态，跳过登录")
            return

        old_cookies = self.http.cookies.copy()
        old_uuid = self.passport.uuid
        try:
            if force:
                # 强制重新扫码时隔离旧账号的 cookie，避免智慧树把新旧会话混在一起。
                self.http.cookies.clear()
                self.passport.uuid = None
            if qr or cfg.use_qr or not (cfg.username and cfg.password):
                jar = self.passport.login_qr(on_qr, cancel_event=cancel_event)
            else:
                jar = self.passport.login_password(cfg.username, cfg.password)

            self.http.cookies = jar
            self.save_state()
            log().info(f"登录完成，uuid={self.passport.uuid}")
        except Exception:
            self.http.cookies = old_cookies
            self.passport.uuid = old_uuid
            raise

    # ---------------------------------------------------------------- LLM

    def backend(self) -> Optional[Backend]:
        if not self.cfg.ai.enabled:
            return None
        if self._backend is not None:
            return self._backend

        ai = self.cfg.ai
        if ai.backend == "zhidao":
            self._backend = ZhsLlmBackend(self.http, stream=ai.openai.stream)
            log().info("AI 作答后端：智慧树自带大模型")
        else:
            self._backend = OpenAICompatBackend(
                ai.openai.base_url, ai.openai.api_key, ai.openai.model,
                stream=ai.openai.stream)
            log().info(f"AI 作答后端：{ai.openai.base_url} / {ai.openai.model}")
        return self._backend

    # ---------------------------------------------------------------- 生命周期

    def close(self) -> None:
        self.save_state()
        log().info(f"收工 | {self.budget.report()} | {self.guard.report()}")

    def __enter__(self) -> "App":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
