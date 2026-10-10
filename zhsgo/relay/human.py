"""拟人化输入层。

核心前提：真实鼠标事件必须走 Playwright 的 page.mouse（底层是 CDP
Input.dispatchMouseEvent），带 isTrusted=true。

页面里 dispatchEvent(new MouseEvent('mousemove')) 合成的事件 isTrusted=false，
风控埋点一过滤就等于没有输入 —— 这是绝大多数"挂机脚本挂久了弹验证码"的
第一个原因。
"""
from __future__ import annotations

import asyncio
import math
import random
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]


# ---------------------------------------------------------------- 鼠标轨迹

def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    m = 1.0 - t
    x = m * m * m * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] + t * t * t * p3[0]
    y = m * m * m * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] + t * t * t * p3[1]
    return x, y


def bezier_path(start: Point, end: Point, steps: Optional[int] = None) -> List[Point]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist < 2.0:
        return [end]
    if steps is None:
        steps = max(6, int(dist / random.uniform(3.5, 8.0)))
    nx, ny = (-dy / dist, dx / dist)
    bow = dist * random.uniform(0.05, 0.18) * random.choice((1.0, -1.0))
    c1 = (start[0] + dx * 0.28 + nx * bow, start[1] + dy * 0.28 + ny * bow)
    c2 = (start[0] + dx * 0.72 + nx * bow * 0.7, start[1] + dy * 0.72 + ny * bow * 0.7)
    out: List[Point] = []
    for i in range(1, steps + 1):
        raw = i / steps
        eased = raw * raw * (3.0 - 2.0 * raw)          # ease-in-out
        t = min(1.0, max(0.0, eased + random.uniform(-0.012, 0.012)))
        out.append(_cubic(start, c1, c2, end, t))
    out[-1] = end
    return out


async def move_to(page, target: Point, lock: Optional[asyncio.Lock] = None) -> None:
    """沿贝塞尔轨迹把鼠标真实移动到 target（视口坐标）。"""

    async def _do() -> None:
        cur = getattr(page, "_lcs_pos", None)
        if cur is None:
            cur = (random.uniform(320, 900), random.uniform(260, 560))
        for (x, y) in bezier_path(cur, target):
            await page.mouse.move(round(x, 1), round(y, 1))
            await asyncio.sleep(random.uniform(0.005, 0.020))
        setattr(page, "_lcs_pos", target)

    if lock is not None:
        async with lock:
            await _do()
    else:
        await _do()


async def random_wander(page, lock: Optional[asyncio.Lock] = None,
                        box: Sequence[int] = (200, 140, 1240, 780)) -> None:
    """在给定矩形内随机移动到一个点，附带 0~2 次停顿。"""
    x = random.uniform(box[0], box[2])
    y = random.uniform(box[1], box[3])
    await move_to(page, (x, y), lock)
    for _ in range(random.randint(0, 2)):
        await asyncio.sleep(random.uniform(0.08, 0.45))
        await move_to(page, (x + random.uniform(-25, 25), y + random.uniform(-18, 18)), lock)


async def micro_jitter(page, lock: Optional[asyncio.Lock] = None) -> None:
    """极小幅度抖动：维持"手搭在鼠标上"的活动特征，不产生任何副作用。"""
    cur = getattr(page, "_lcs_pos", (700.0, 450.0))
    for _ in range(random.randint(2, 5)):
        nx = cur[0] + random.uniform(-6, 6)
        ny = cur[1] + random.uniform(-5, 5)
        if lock is not None:
            async with lock:
                await page.mouse.move(round(nx, 1), round(ny, 1))
        else:
            await page.mouse.move(round(nx, 1), round(ny, 1))
        await asyncio.sleep(random.uniform(0.012, 0.05))


async def wheel_wander(page, lock: Optional[asyncio.Lock] = None) -> None:
    """页面内小幅滚动再回滚，模拟看课件的人。"""
    delta = random.choice((-1, 1)) * random.randint(60, 220)

    async def _do() -> None:
        await page.mouse.wheel(0, delta)
        await asyncio.sleep(random.uniform(0.3, 0.9))
        await page.mouse.wheel(0, -delta)

    if lock is not None:
        async with lock:
            await _do()
    else:
        await _do()


# ---------------------------------------------------------------- 滑块轨迹

def slide_track(distance: float) -> List[Tuple[float, float, float]]:
    """生成滑块拖动轨迹 [(dx, dy, sleep_s), ...]，含过冲与回拉、偶发停顿。

    物理模型：加速段 → 匀速段 → 减速段 → 冲过头 → 小幅回拉。
    全程带随机 y 抖动和帧间隔抖动，绝不使用等距等时采样。
    """
    distance = max(float(distance), 1.0)
    overshoot = random.uniform(4.0, 13.0)
    total = distance + overshoot

    tracks: List[Tuple[float, float, float]] = []
    cur = 0.0
    v = 0.0
    accel_len = random.uniform(0.13, 0.20) * distance
    a = random.uniform(0.9, 1.9) / max(accel_len, 1.0)
    decel_at = distance * random.uniform(0.76, 0.88)

    guard = 0
    while cur < total and guard < 400:
        guard += 1
        v += a * random.uniform(0.65, 1.35)
        if cur >= decel_at:
            v -= a * random.uniform(1.05, 1.75)
        step = max(v, 0.38)
        cur = min(total, cur + step)
        y = random.uniform(-1.3, 1.3) if random.random() < 0.35 else 0.0
        delay = random.uniform(0.008, 0.024)
        if random.random() < 0.025:                 # 中途一次人类级别的犹豫
            delay += random.uniform(0.09, 0.28)
        tracks.append((round(cur, 2), round(y, 2), delay))

    # 回拉：分 2~4 步退回目标位置
    back_steps = random.randint(2, 4)
    start_back = tracks[-1][0]
    for i in range(1, back_steps + 1):
        x = start_back - overshoot * (i / back_steps)
        tracks.append((round(x, 2), round(random.uniform(-0.6, 0.6), 2),
                       random.uniform(0.02, 0.07)))
    tracks.append((round(distance, 2), 0.0, random.uniform(0.06, 0.16)))
    return tracks


async def drag_slider(page, handle, distance: float, lock: Optional[asyncio.Lock] = None,
                      settle: Tuple[int, int] = (60, 200)) -> None:
    """按住 handle，按拟人轨迹拖到 distance 像素处，再松手。"""
    box = await handle.bounding_box()
    if not box:
        raise RuntimeError("slider handle has no bounding box")
    sx = box["x"] + box["width"] / 2
    sy = box["y"] + box["height"] / 2

    await move_to(page, (sx, sy), lock)
    await asyncio.sleep(random.uniform(0.08, 0.24))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.05, 0.16))

    for dx, dy, delay in slide_track(distance):
        if lock is not None:
            async with lock:
                await page.mouse.move(round(sx + dx, 1), round(sy + dy, 1))
        else:
            await page.mouse.move(round(sx + dx, 1), round(sy + dy, 1))
        await asyncio.sleep(delay)

    await asyncio.sleep(random.uniform(0.05, 0.18))
    await page.mouse.up()
    await asyncio.sleep(random.uniform(settle[0], settle[1]) / 1000.0)


# ---------------------------------------------------------------- 键盘

async def type_like(page, text: str) -> None:
    """打字机式输入，键间延迟服从对数正态，偶发长停顿。"""
    for ch in text:
        await page.keyboard.type(ch)
        d = random.lognormvariate(-3.4, 0.5)
        if random.random() < 0.04:
            d += random.uniform(0.25, 0.9)
        await asyncio.sleep(min(d, 1.2))


# ---------------------------------------------------------------- 通用

def pick(rng: Sequence[float]) -> float:
    """从 [min, max] 区间取随机值，偏向中位数附近（三角分布）。"""
    lo, hi = float(rng[0]), float(rng[1])
    return random.triangular(lo, hi, (lo + hi) / 2.0)
