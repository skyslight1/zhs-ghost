"""浏览器验证码中继。

**这是"解决"人机验证而非"绕开"人机验证的部分。**

`code: -12` 是服务端风控下发的信号，网页端表现为播放器弹出滑块/点选验证框；
人过掉之后服务端给这个会话下发新凭证（落在 Cookie 上），上报才恢复。

所以中继做的事是：
  1. 用同一份 Cookie 启动真实浏览器打开学习页；
  2. 让页面播放器自己跑，等风控验证框弹出（最长 wait_captcha_seconds）；
  3. ddddocr 自动过滑块 / 点选；过不了就响铃等人来滑一下；
  4. 把浏览器里拿到的新 Cookie **合并**回 HttpClient（必须合并，不能覆盖）；
  5. 返回 True，由 Guard 重新发起刚才那次上报。

持久化 profile 保证这个"浏览器指纹"一直不变，不会出现"过完验证码又被当成
新设备"的循环。
"""
from __future__ import annotations

import asyncio
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..clock import Clock
from ..util import merge_cookies


@dataclass
class RelayConfig:
    enabled: bool = True
    headless: bool = False
    channel: str = ""                       # "" = 自动挑选；也可填 msedge / chrome
    # 自动挑选时，优先用系统自带的 Edge / Chrome 内核。
    # 打包成 exe 后没有 `playwright install` 这一步，靠系统内核才能开箱即用。
    prefer_system_browser: bool = True
    user_data_dir: str = "./state/browser_profile"
    screenshot_dir: str = "./logs/shots"
    wait_captcha_seconds: float = 75.0
    max_solve_retry: int = 6
    manual_wait_seconds: float = 300.0
    beep_on_manual: bool = True
    # 滑块拖动
    drag_duration_ms: Tuple[int, int] = (900, 1600)
    slider_offset_fix: float = -8.0
    click_settle_ms: Tuple[int, int] = (420, 1100)
    # 页面
    study_url: str = ("https://studyh5.zhihuishu.com/videoStudy.html"
                      "#/studyVideo?recruitAndCourseId={rac}")
    home_url: str = "https://onlineweb.zhihuishu.com/onlineweb.html#/studentIndex"

    def as_solver_cfg(self) -> dict:
        return {"captcha": {
            "drag_duration_ms": list(self.drag_duration_ms),
            "slider_offset_fix": self.slider_offset_fix,
            "click_settle_ms": list(self.click_settle_ms),
        }}


class BrowserRelay:
    """满足 `risk.Relay` 协议。"""

    def __init__(self, cfg: Optional[RelayConfig] = None, clock: Optional[Clock] = None,
                 notifier: Optional[Any] = None):
        self.cfg = cfg or RelayConfig()
        self.clock = clock or Clock()
        self.notifier = notifier
        self._lock = threading.Lock()
        self.unlock_count = 0
        if self.cfg.user_data_dir:
            os.makedirs(self.cfg.user_data_dir, exist_ok=True)
        if self.cfg.screenshot_dir:
            os.makedirs(self.cfg.screenshot_dir, exist_ok=True)

    # ---------------------------------------------------------------- 对外

    def unlock(self, http: Any, rac_id: Optional[str]) -> bool:
        if not self.cfg.enabled:
            logger.warning("中继未启用，无法自动过验证码")
            return False
        if not self._lock.acquire(blocking=False):
            logger.warning("已有中继任务在运行，跳过本次")
            return False
        try:
            return asyncio.run(self._unlock(http, rac_id))
        except RuntimeError:
            # 已经在事件循环里（被 async 调用），换子线程
            return self._unlock_in_thread(http, rac_id)
        except Exception as e:
            logger.exception(f"中继失败: {e}")
            return False
        finally:
            self._lock.release()

    def _unlock_in_thread(self, http: Any, rac_id: Optional[str]) -> bool:
        box: Dict[str, Any] = {}

        def job() -> None:
            try:
                box["r"] = asyncio.run(self._unlock(http, rac_id))
            except Exception as e:      # pragma: no cover
                box["e"] = e

        t = threading.Thread(target=job, daemon=True, name="captcha-relay")
        t.start()
        t.join()
        if "e" in box:
            raise box["e"]
        return bool(box.get("r"))

    # ---------------------------------------------------------------- 启动

    def channel_chain(self) -> List[Optional[str]]:
        if self.cfg.channel:
            return [self.cfg.channel]
        if self.cfg.prefer_system_browser:
            # Windows 10/11 一定自带 Edge；配上就知道为什么打包成 exe 后
            # 不需要 `playwright install chromium` 也能开箱即用
            return ["msedge", "chrome", None]
        return [None]

    async def _launch(self, p):
        """按候选顺序试浏览器内核，返回 (context, channel)。"""
        from .stealth import ANTI_THROTTLE_ARGS, IGNORE_DEFAULT_ARGS

        base: Dict[str, Any] = dict(
            user_data_dir=self.cfg.user_data_dir,
            headless=self.cfg.headless,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=ANTI_THROTTLE_ARGS,
            ignore_default_args=IGNORE_DEFAULT_ARGS,
        )
        failures: List[str] = []
        for channel in self.channel_chain():
            kwargs = dict(base)
            if channel:
                kwargs["channel"] = channel
            try:
                ctx = await p.chromium.launch_persistent_context(**kwargs)
                logger.info(f"浏览器内核：{channel or 'playwright 内置 chromium'}")
                return ctx, channel
            except Exception as e:
                failures.append(f"{channel or 'chromium'} → {_brief(e)}")

        logger.error(
            "浏览器内核全部启动失败：\n  " + "\n  ".join(failures)
            + "\n\n排查建议：\n"
              "  1) Windows 自带 Edge 正常应该能直接用；失败说明 Edge 被卸载或损坏\n"
              "  2) 想改用 playwright 内置 chromium：\n"
              "       源码版  python -m playwright install chromium\n"
              "       exe 版   zhs-ghost.exe --install-browser\n"
              "  3) 也可以先把 relay.enabled 改成 false，暂时跳过自动过验证码"
        )
        return None, None

    # ---------------------------------------------------------------- 主流程

    async def _unlock(self, http: Any, rac_id: Optional[str]) -> bool:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "未安装 playwright，验证码中继不可用。请执行：\n"
                "    pip install playwright\n"
                "    python -m playwright install chromium"
            )
            return False

        from . import captcha as capmod
        from . import detector, human
        from .captcha import CaptchaSolver
        from .stealth import ANTI_THROTTLE_ARGS, IGNORE_DEFAULT_ARGS, STEALTH_JS

        cookies = to_playwright_cookies(http.cookies)
        logger.warning(f"启动浏览器过验证码（注入 {len(cookies)} 个 cookie）")

        async with async_playwright() as p:
            ctx, _used = await self._launch(p)
            if ctx is None:
                return False
            try:
                await ctx.add_init_script(STEALTH_JS)
                if cookies:
                    try:
                        await ctx.add_cookies(cookies)
                    except Exception as e:
                        logger.warning(f"部分 cookie 注入失败（继续）: {e}")

                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                page.set_default_timeout(30000)

                url = self.cfg.study_url.format(rac=rac_id) if rac_id else self.cfg.home_url
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    logger.warning(f"打开学习页超时（继续等待验证码）: {e}")

                await asyncio.sleep(random.uniform(3.0, 6.5))

                # 用真实 CDP 输入激活 userActivation 与页面行为采集
                try:
                    await human.random_wander(page)
                    await asyncio.sleep(random.uniform(0.4, 1.2))
                    await human.random_wander(page)
                except Exception:
                    pass

                solver = CaptchaSolver(self.cfg.as_solver_cfg(), mouse_lock=asyncio.Lock())
                passed = await self._wait_and_solve(page, solver, detector, capmod)

                raw = await ctx.cookies()
                changed = merge_cookies(http.cookies, raw)
                # CASLOGC 可能被刷新，uuid 跟着重解析
                uid = _extract_uuid(http.cookies)
                if uid:
                    http.session.cookies[f"exitRecod_{uid}"] = "2"
                self.unlock_count += 1
                logger.success(f"会话凭证已回灌，变化 {len(changed)} 项: {changed[:12]}")
                if not passed:
                    logger.warning("未观察到验证码消失，但仍然刷新了凭证，交给上层重试判定")
                return True
            finally:
                try:
                    await ctx.close()
                except Exception:
                    pass

    async def _wait_and_solve(self, page, solver, detector, capmod) -> bool:
        await detector.install_watcher(page)
        deadline = time.time() + self.cfg.wait_captcha_seconds
        seen = False
        fails = 0
        manual_announced = False

        while time.time() < deadline:
            try:
                info = await detector.get_captcha(page)
            except Exception:
                info = None

            if not info:
                if seen:
                    logger.success("验证码已消失")
                    await asyncio.sleep(random.uniform(3.0, 7.0))
                    return True
                await asyncio.sleep(1.5)
                continue

            seen = True
            logger.warning(f"弹出验证码: {info.get('selector')} / {info.get('text')!r}")
            if fails >= self.cfg.max_solve_retry and not manual_announced and self.cfg.manual_wait_seconds > 0:
                manual_announced = True
                self._alert_manual()
            try:
                await capmod.handle_captcha(page, info, solver, self.cfg.screenshot_dir)
            except Exception as e:
                logger.exception(f"过检异常: {e}")
            await asyncio.sleep(2.0)
            if await detector.get_captcha(page) is None:
                logger.success("验证码已通过")
                await asyncio.sleep(random.uniform(4.0, 9.0))
                return True
            fails += 1
            logger.warning(f"过检失败 {fails}/{self.cfg.max_solve_retry}")
            if fails >= self.cfg.max_solve_retry:
                await asyncio.sleep(3.0)

        logger.error("等待验证码超时")
        return False

    def _alert_manual(self) -> None:
        logger.error("自动过检连续失败，转为人工等待（浏览器窗口已打开）")
        if self.cfg.beep_on_manual:
            _beep(1200, 420, 6)
        if self.notifier:
            try:
                self.notifier("【zhsgo】需要人工过验证码",
                              f"浏览器窗口已打开，请在 {self.cfg.manual_wait_seconds/60:.0f} 分钟内滑一下")
            except Exception:
                pass


# ---------------------------------------------------------------------- 辅助

def to_playwright_cookies(jar) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in jar:
        if not c.name or c.value is None:
            continue
        item: Dict[str, Any] = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain or ".zhihuishu.com",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": bool((getattr(c, "_rest", None) or {}).get("HttpOnly")),
        }
        if c.expires:
            try:
                item["expires"] = float(c.expires)
            except Exception:
                pass
        same_site = (getattr(c, "_rest", None) or {}).get("SameSite")
        if same_site in ("Strict", "Lax", "None"):
            item["sameSite"] = same_site
        out.append(item)
    return out


def _extract_uuid(jar) -> Optional[str]:
    try:
        from urllib.parse import unquote_plus
        import json as _json
        raw = jar.get("CASLOGC")
        if raw:
            return _json.loads(unquote_plus(raw))["uuid"]
    except Exception:
        pass
    return None


def _brief(exc: Exception, limit: int = 90) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _beep(freq: int, duration: int, times: int) -> None:
    try:
        import sys
        if sys.platform == "win32":
            import winsound
            for _ in range(times):
                winsound.Beep(freq, duration)
        else:
            print("\a" * times, end="", flush=True)
    except Exception:
        pass
