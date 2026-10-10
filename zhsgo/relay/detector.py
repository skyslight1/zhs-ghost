"""验证码弹出检测。

用 MutationObserver 在页面里挂一个钩子，把"当前是否出现验证码容器"写到
window.__lcs_captcha__，Python 侧轮询取值。比 Python 侧高频 locator 查询便宜，
也不会因为高频 DOM 查询本身被当成异常行为。
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional

from loguru import logger

# 覆盖：数美(shumei)、极验(geetest)、网易易盾(yidun)、阿里 nc、以及自研通用类名
CAPTCHA_SELECTORS = [
    ".yidun_panel", ".yidun_modal", ".yidun_intellisense", ".yidun_popup",
    ".geetest_panel", ".geetest_box", ".geetest_widget", ".geetest_panel_box",
    "#nc_1_wrapper", "#nc_1_n1z", ".nc-container", ".nc_wrapper", ".nc_scale",
    ".shumei_captcha", ".shumei_captcha_wrapper",
    ".verifyBox", ".verify-box", ".verify-wrap", ".verify-wrap-panel",
    ".captcha-box", ".captchaBox", "#captchaBox", "#captcha_box",
    ".dialog-verify", ".exam-verify", ".checkCode",
    "[class*='sliderContainer']", "[class*='slide-verify']",
    "[class*='captcha' i]", "[class*='verifyimg']",
    "iframe[src*='captcha']", "iframe[src*='verify']", "iframe[src*='gt.js']",
    "iframe[src*='yidun']", "iframe[src*='shumei']", "iframe[src*='gee']",
]

CAPTCHA_TEXT_KEYS = [
    "请完成安全验证", "拖动滑块", "向右滑动", "请依次点击", "点击文字",
    "安全验证", "人机验证", "请按住滑块", "verify", "滑块验证",
]

WATCH_JS = r"""
(() => {
  if (window.__lcs_captcha_hook__) return;
  window.__lcs_captcha_hook__ = true;
  window.__lcs_captcha__ = null;

  const SEL = %(selectors)s;
  const KEYS = %(keys)s;

  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return false;
    if (r.bottom < 0 || r.top > (window.innerHeight + 200)) return false;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return false;
    if (parseFloat(st.opacity) === 0) return false;
    if (st.pointerEvents === 'none' && st.zIndex === 'auto') return false;
    return true;
  };

  const scan = () => {
    for (const s of SEL) {
      let el = null;
      try { el = document.querySelector(s); } catch (e) { continue; }
      if (!el || !visible(el)) continue;
      window.__lcs_captcha__ = {
        selector: s,
        cls: (el.className && el.className.toString ? el.className.toString() : '') || '',
        text: ((el.innerText || el.textContent || '') + '').trim().slice(0, 160),
        tag: el.tagName,
        src: el.getAttribute ? (el.getAttribute('src') || '') : '',
        ts: Date.now(),
      };
      return;
    }
    // 文本兜底：有些自研验证不挂特征类名
    const body = document.body ? (document.body.innerText || '') : '';
    for (const k of KEYS) {
      if (body.includes(k) && body.length < 4000) {
        window.__lcs_captcha__ = { selector: 'text:' + k, cls: '', text: k, tag: 'TEXT', src: '', ts: Date.now() };
        return;
      }
    }
    window.__lcs_captcha__ = null;
  };

  scan();
  try {
    new MutationObserver(() => { clearTimeout(window.__lcs_t__);
      window.__lcs_t__ = setTimeout(scan, 120); })
      .observe(document.documentElement, { childList: true, subtree: true, attributes: true });
  } catch (e) {}
  setInterval(scan, 2500);
})();
"""


def build_watch_js() -> str:
    import json
    return WATCH_JS % {
        "selectors": json.dumps(CAPTCHA_SELECTORS),
        "keys": json.dumps(CAPTCHA_TEXT_KEYS, ensure_ascii=False),
    }


async def install_watcher(page) -> None:
    """在主 frame 与所有子 frame 安装钩子。"""
    js = build_watch_js()
    try:
        await page.evaluate(js)
    except Exception:
        pass
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            await fr.evaluate(js)
        except Exception:
            continue


async def get_captcha(page) -> Optional[Dict]:
    """返回当前验证码信息，无则 None。会先尝试补装钩子。"""
    info = None
    for ctx in [page] + [f for f in page.frames if f != page.main_frame]:
        try:
            info = await ctx.evaluate(
                "(() => { if (!window.__lcs_captcha_hook__) return '__NO_HOOK__';"
                " return window.__lcs_captcha__ || null; })()"
            )
        except Exception:
            continue
        if info == "__NO_HOOK__":
            try:
                await install_watcher(page)
            except Exception:
                pass
            return None
        if info:
            return info
    return None


async def wait_gone(page, timeout: float = 20.0) -> bool:
    """等待验证码消失。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await get_captcha(page) is None:
            return True
        await asyncio.sleep(0.6)
    return False


async def captcha_watch_loop(page, solver, cfg, stop_event: asyncio.Event) -> None:
    """后台任务：发现验证码 -> 尝试解决 -> 连续失败则拉停整个会话。"""
    max_retry = int(cfg["captcha"].get("max_retry", 5))
    give_up = int(cfg["captcha"].get("give_up_after", 3))
    shot_dir = cfg["log"].get("screenshot_dir", "./logs/shots")
    fails = 0
    await install_watcher(page)

    while not stop_event.is_set():
        await asyncio.sleep(1.2)
        try:
            info = await get_captcha(page)
        except Exception:
            continue
        if not info:
            continue

        logger.warning("弹窗命中人机验证，开始自动过检")
        from . import captcha as cap
        ok = False
        for attempt in range(1, max_retry + 1):
            try:
                ok = await cap.handle_captcha(page, info, solver, shot_dir)
            except Exception as e:
                logger.exception(f"过检异常: {e}")
                ok = False
            await asyncio.sleep(2.0)
            if await get_captcha(page) is None:
                logger.success(f"人机验证已通过 (第 {attempt} 次)")
                fails = 0
                break
            info = (await get_captcha(page)) or info
            logger.warning(f"过检失败，重试 {attempt}/{max_retry}")
            await asyncio.sleep(1.5 + attempt)

        if await get_captcha(page) is not None:
            fails += 1
            logger.error(f"本轮过检彻底失败 ({fails}/{give_up})")
            if fails >= give_up:
                logger.error("连续失败达阈值，暂停会话等待人工介入")
                stop_event.set()
                return
        else:
            fails = 0
