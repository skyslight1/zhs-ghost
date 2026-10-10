"""人机验证的检测、识别与自动过检。

三类目标：
  1) 滑块拼图（自研 / 数美 / 极验的老版 slide）—— ddddocr 求缺口 x，再按拟人轨迹拖。
  2) 文字点选 —— ddddocr 目标检测定位候选方块，逐块 OCR，按提示语顺序点击。
  3) 检测到但无法自动处理 —— 抛 CaptchaUnsolvable，交给上层暂停 + 告警。

关键：所有坐标都要按 DPR 和容器缩放还原成"页面坐标"，否则拖不到位置。
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from loguru import logger

from . import human


class CaptchaUnsolvable(Exception):
    pass


# ------------------------------------------------------------------ 选择器

SLIDER_HANDLE_SELECTORS: Sequence[str] = (
    ".yidun_slider", ".yidun_jigsaw",
    ".geetest_slider_button", ".geetest_btn",
    ".nc_iconfont.btn_slide", "[class*='btn_slide']",
    ".verify-move-block", ".slider-btn", ".slide-btn",
    "[class*='sliderIcon']", "[class*='drag-button']",
    ".shumei_slider", "[class*='slideBlock']",
)

SLIDER_BG_SELECTORS: Sequence[str] = (
    ".yidun_bg-img", ".yidun_bgimg",
    ".geetest_canvas_bg", ".geetest_bg",
    ".nc-lang-cnt img", ".nc-container canvas",
    ".verify-img-panel", ".slide-bg",
    "[class*='bg-img']", "[class*='slideBg']",
)

SLIDER_FRONT_SELECTORS: Sequence[str] = (
    ".yidun_jigsaw", ".geetest_canvas_slice", ".geetest_slice",
    ".verify-sub-block", "[class*='slideBlock']",
    "[class*='jigsaw']",
)

CLICK_IMG_SELECTORS: Sequence[str] = (
    ".yidun_bg-img", ".geetest_item_img", ".verify-img-panel",
    ".nc-container canvas", "[class*='clickImg']", "[class*='captcha-img']",
)

CLICK_WORD_SELECTORS: Sequence[str] = (
    ".yidun_tips__text", ".geetest_tip", ".verify-tip",
    "[class*='tips']", "[class*='prompt']", "[class*='question']",
)


# ------------------------------------------------------------------ 工具

async def _first_visible(root, selectors: Sequence[str], min_size: int = 12):
    """在 root（page 或 frame）里返回第一个可见且足够大的元素。"""
    for sel in selectors:
        try:
            loc = root.locator(sel).first
            if await loc.count() == 0:
                continue
            if not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if not box or box["width"] < min_size or box["height"] < min_size:
                continue
            return loc, box
        except Exception:
            continue
    return None, None


async def _screenshot_bytes(elem) -> bytes:
    return await elem.screenshot(type="png")


def _to_png_bytes(raw: bytes) -> bytes:
    return raw


# ------------------------------------------------------------------ 求解器

class CaptchaSolver:
    def __init__(self, cfg: Dict, mouse_lock: Optional[asyncio.Lock] = None):
        self.cfg = cfg.get("captcha", {}) if hasattr(cfg, "get") else {}
        self.mouse_lock = mouse_lock
        self._slide_ocr = None
        self._det_ocr = None
        self._cls_ocr = None

    @staticmethod
    def _load_ddddocr():
        try:
            import ddddocr
            return ddddocr
        except ImportError:
            logger.error(
                "未安装 ddddocr，自动过验证码不可用。请执行：\n"
                "    pip install ddddocr opencv-python numpy"
            )
            raise

    # ddddocr 懒加载：初始化要几百毫秒，别在启动时就吃掉
    @property
    def slide_ocr(self):
        if self._slide_ocr is None:
            ddddocr = self._load_ddddocr()
            self._slide_ocr = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        return self._slide_ocr

    @property
    def det_ocr(self):
        if self._det_ocr is None:
            ddddocr = self._load_ddddocr()
            self._det_ocr = ddddocr.DdddOcr(det=True, ocr=False, show_ad=False)
        return self._det_ocr

    @property
    def cls_ocr(self):
        if self._cls_ocr is None:
            ddddocr = self._load_ddddocr()
            self._cls_ocr = ddddocr.DdddOcr(det=False, ocr=True, show_ad=False)
        return self._cls_ocr

    # -------------------------------------------------------------- 分类

    @staticmethod
    def classify(info: Dict) -> str:
        text = (info.get("text") or "") + " " + (info.get("cls") or "") + " " + (info.get("src") or "")
        text = text.lower()
        if any(k in text for k in ("拖动", "滑块", "向右滑", "drag", "slide", "拼图", "缺口")):
            return "slide"
        if any(k in text for k in ("依次点击", "点击文字", "请点击", "依次选", "按顺序", "click")):
            return "click"
        if any(k in text for k in ("yidun", "geetest", "nc_", "shumei", "verify")):
            return "slide"      # 默认按滑块处理，失败后上层会再走点选
        return "unknown"

    # -------------------------------------------------------------- 滑块

    async def solve_slide(self, root, bg_bytes: bytes, front_bytes: bytes,
                          handle, container_width: float) -> bool:
        """求缺口偏移并拖动。返回是否执行了拖动。"""
        # 1) 识别缺口
        gap_x = None
        try:
            res = self.slide_ocr.slide_match(front_bytes, bg_bytes, simple_target=False)
            if isinstance(res, dict) and res.get("target"):
                x1, _, x2, _ = res["target"]
                gap_x = (x1 + x2) / 2.0
        except Exception as e:
            logger.warning(f"ddddocr slide_match 失败，回退 OpenCV: {e}")

        if gap_x is None:
            gap_x = self._opencv_gap(bg_bytes, front_bytes)

        if gap_x is None:
            logger.error("缺口识别失败")
            return False

        # 2) 换算成目标位移
        # 背景图显示宽度 -> 容器宽度 的比例
        bg_loc, bg_box = await _first_visible(root, SLIDER_BG_SELECTORS)
        if bg_box is None:
            bg_box = {"width": container_width}
        ratio = container_width / max(bg_box["width"], 1.0)

        handle_box = await handle.bounding_box()
        distance = gap_x * ratio + float(self.cfg.get("slider_offset_fix", -8))
        # 拖动距离还要减去把手初始相对位置带来的偏差
        if handle_box and bg_box:
            distance += (handle_box["x"] - bg_box["x"]) * 0.0

        distance = max(distance, 6.0)
        logger.info(f"滑块缺口 x={gap_x:.1f}, 换算位移={distance:.1f}px")

        await human.drag_slider(
            page=root.page if hasattr(root, "page") else root,
            handle=handle,
            distance=distance,
            lock=self.mouse_lock,
            settle=tuple(self.cfg.get("drag_duration_ms", [900, 1600])),
        )
        return True

    @staticmethod
    def _opencv_gap(bg_bytes: bytes, front_bytes: bytes) -> Optional[float]:
        """无依赖外的兜底：Canny 边缘 + 模板匹配。"""
        try:
            import cv2
            import numpy as np
        except Exception:
            return None
        bg = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        ft = cv2.imdecode(np.frombuffer(front_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        if bg is None or ft is None:
            return None
        bg_e = cv2.Canny(bg, 100, 200)
        ft_e = cv2.Canny(ft, 100, 200)
        res = cv2.matchTemplate(bg_e, ft_e, cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc = cv2.minMaxLoc(res)
        return float(max_loc[0] + ft.shape[1] / 2.0)

    # -------------------------------------------------------------- 点选

    async def solve_click(self, root, img_bytes: bytes, prompt: str,
                          img_box: Optional[Dict] = None) -> bool:
        """文字点选：目标检测 -> 逐块 OCR -> 按提示顺序点击。"""
        try:
            import cv2
            import numpy as np
        except Exception as e:
            logger.error(f"点选需要 opencv: {e}")
            return False

        arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            return False

        bboxes = []
        try:
            bboxes = self.det_ocr.detection(img_bytes)
        except Exception as e:
            logger.warning(f"detection 失败: {e}")

        if not bboxes:
            logger.warning("未检测到候选方块")
            return False

        # 逐块裁剪 + 识别
        chars: List[Tuple[str, int, int, int, int]] = []
        for (x1, y1, x2, y2) in bboxes:
            pad = 2
            crop = arr[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
            if crop.size == 0:
                continue
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                continue
            try:
                ch = self.cls_ocr.classification(buf.tobytes())
            except Exception:
                ch = ""
            chars.append((ch or "", x1, y1, x2, y2))

        logger.info(f"点选候选: {[(c[0], c[1], c[2]) for c in chars]}")

        order = self._match_order(prompt, chars)
        if not order:
            logger.warning(f"无法匹配提示词 [{prompt}] 与候选字")
            return False

        # 图片尺寸 -> 页面尺寸
        scale_x = scale_y = 1.0
        box = img_box
        if box:
            scale_x = box["width"] / max(arr.shape[1], 1)
            scale_y = box["height"] / max(arr.shape[0], 1)

        origin_x = box["x"] if box else 0.0
        origin_y = box["y"] if box else 0.0
        page = root.page if hasattr(root, "page") else root

        for (ch, x1, y1, x2, y2) in order:
            cx = origin_x + (x1 + x2) / 2.0 * scale_x
            cy = origin_y + (y1 + y2) / 2.0 * scale_y
            await human.move_to(page, (cx, cy), self.mouse_lock)
            await asyncio.sleep(random.uniform(0.06, 0.22))
            await page.mouse.click(cx, cy)
            await asyncio.sleep(random.uniform(*[v / 1000.0 for v in
                                                 self.cfg.get("click_settle_ms", [420, 1100])]))
            logger.info(f"点击 [{ch}] @ ({cx:.0f},{cy:.0f})")
        return True

    @staticmethod
    def _match_order(prompt: str,
                     chars: List[Tuple[str, int, int, int, int]]):
        """按提示语里的字符顺序，从候选块中挑出对应方块。"""
        if not prompt:
            return [c for c in sorted(chars, key=lambda c: c[1])]
        queue = [ch for ch in prompt if "\u4e00" <= ch <= "\u9fff"]
        if not queue:
            queue = list(prompt.strip())
        used = set()
        order = []
        for want in queue:
            best = None
            for idx, item in enumerate(chars):
                if idx in used:
                    continue
                got = item[0].strip()
                if not got:
                    continue
                if want == got or want in got or got in want:
                    best = idx
                    break
            if best is not None:
                used.add(best)
                order.append(chars[best])
        return order


# ------------------------------------------------------------------ 过检入口

async def handle_captcha(page, info: Dict, solver: CaptchaSolver,
                         shot_dir: str) -> bool:
    """对当前检测到的验证码尝试过一次。返回 True 表示已提交。"""
    kind = CaptchaSolver.classify(info)
    logger.warning(f"检测到人机验证 kind={kind} selector={info.get('selector')} text={info.get('text')!r}")

    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        await page.screenshot(path=f"{shot_dir}/captcha_{ts}_{kind}.png", full_page=False)
    except Exception:
        pass

    root = page
    # 验证码可能在 iframe 里
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            el = fr.locator("canvas, [class*='slide'], [class*='slider'], [class*='captcha']").first
            if await el.count() > 0:
                root = fr
                break
        except Exception:
            continue

    if kind == "click":
        img_loc, img_box = await _first_visible(root, CLICK_IMG_SELECTORS, min_size=60)
        prompt = ""
        for sel in CLICK_WORD_SELECTORS:
            try:
                loc = root.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    prompt = (await loc.inner_text()).strip()
                    break
            except Exception:
                continue
        if img_loc is not None:
            img_bytes = await img_loc.screenshot(type="png")
            if await solver.solve_click(root, img_bytes, prompt, img_box):
                return True

    # 默认按滑块走（也覆盖 click 解失败后的兜底）
    handle, _ = await _first_visible(root, SLIDER_HANDLE_SELECTORS, min_size=8)
    if handle is None:
        logger.error("找不到滑块把手，本次无法自动过检")
        return False

    bg_loc, bg_box = await _first_visible(root, SLIDER_BG_SELECTORS, min_size=40)
    front_loc, _ = await _first_visible(root, SLIDER_FRONT_SELECTORS, min_size=8)

    if bg_loc is None:
        logger.error("找不到滑块背景图")
        return False

    bg_bytes = await bg_loc.screenshot(type="png")
    if front_loc is not None:
        try:
            front_bytes = await front_loc.screenshot(type="png")
        except Exception:
            front_bytes = bg_bytes
    else:
        # 有些实现把拼图块和把手绑在同一个元素里，退回用把手自身当模板
        try:
            front_bytes = await handle.screenshot(type="png")
        except Exception:
            logger.error("既找不到拼图块也无法截取把手，放弃本次过检")
            return False

    container_width = (bg_box or {}).get("width", 280)
    return await solver.solve_slide(root, bg_bytes, front_bytes, handle, container_width)
