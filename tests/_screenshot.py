#!/usr/bin/env python3
"""开发用：给 GUI 各标签页截图，方便检查视觉效果。

    python tests/_screenshot.py

产物在 tests/shots/ 下。不属于常规测试，CI 不跑它。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

OUT = os.path.join(HERE, "docs", "images")
os.makedirs(OUT, exist_ok=True)


def _dpi_aware() -> None:
    """必须在创建 Tk() 之前调用。

    否则进程是 DPI-unaware：`winfo_*` / `GetWindowRect` 返回被系统虚拟化过的
    逻辑坐标，而 ImageGrab 抓的是物理像素 —— 150% 缩放下两者差 1.5 倍，
    截出来的图只覆盖窗口左上角的一小块（看起来就像界面被裁了）。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    _dpi_aware()
    from PIL import ImageGrab

    from zhsgo.gui.window import MainWindow
    from zhsgo.observer import PHASE_STUDY, Progress

    win = MainWindow()
    win.geometry("1000x760+40+40")
    win.update()
    # 不加这两行的话，截图会抓到盖在它上面的别的窗口
    win.attributes("-topmost", True)
    win.lift()
    win.focus_force()
    win.update()

    # 填充一些假数据，不然截图里全是 "-"
    win.tab_study.set_account(True, "b3f1c0a2-9d4e-4a17-8c55-1e2f3a4b5c6d",
                              "今日 45.2/250 分钟 | 会话 1/4 | 本次会话已 12 分钟")
    win.tab_study.update_progress(Progress(
        phase=PHASE_STUDY, course="中国近现代史纲要", video="第一章 进入近代中国 / 1.1 鸦片战争前的中国",
        message="学习中 1.1 鸦片战争前的中国", current=186.0, total=1111.0,
        extra={"reported": 150.0}))
    win.tab_courses.set_courses([
        {"type": "zhidao", "name": "中国近现代史纲要", "id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"},
        {"type": "zhidao", "name": "思想道德与法治", "id": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5"},
        {"type": "hike", "name": "高等数学（上）", "id": "1919"},
        {"type": "hike", "name": "大学英语视听说", "id": "2048"},
    ])
    for line, lvl in (
        ("17:32:01  INFO    开始共享课：中国近现代史纲要", "INFO"),
        ("17:32:03  INFO    学习中 导论 | 186/1111s | 目标 1011s", "INFO"),
        ("17:32:44  INFO    上报学习进度 成功", "INFO"),
        ("17:34:10  WARNING 风控触发 code=-12 | 场景: 上报学习进度", "WARNING"),
        ("17:34:12  INFO    启动浏览器过验证码（注入 5 个 cookie）", "INFO"),
        ("17:34:15  INFO    浏览器内核：msedge", "INFO"),
        ("17:34:31  INFO    滑块缺口 x=182.4, 换算位移=176.2px", "INFO"),
        ("17:34:33  SUCCESS 会话凭证已回灌，变化 2 项: ['acw_tc', 'SESSION']", "SUCCESS"),
        ("17:34:41  WARNING 风控已解除（第 1 次重试成功）", "WARNING"),
        ("17:35:02  INFO    上报学习进度 成功", "INFO"),
    ):
        win.tab_log.append(line, lvl)

    win.tab_config.reload()
    win.update()

    def capture(index: int, name: str) -> None:
        win.notebook.select(index)
        win.update()
        win.after(220, lambda: _grab(win, index, name, done))

    def done() -> None:
        win.destroy()

    sequence = [(0, "gui-study"), (1, "gui-courses"),
                (2, "gui-config"), (3, "gui-log")]

    def step(i: int = 0) -> None:
        if i >= len(sequence):
            done()
            return
        idx, name = sequence[i]
        win.notebook.select(idx)
        win.update()
        win.after(200, lambda: (_grab(win, idx, name), step(i + 1)))

    win.after(500, lambda: step(0))
    win.mainloop()
    print(f"截图已保存到 {OUT}")
    return 0


def _window_rect(win) -> tuple:
    """拿窗口的真实屏幕矩形。

    `winfo_rootx/rooty` 在 Windows 上给的是客户区坐标，不含标题栏和边框，
    直接拿来裁剪会偏 —— 截出来的图会少一块、还会带进旁边的窗口。
    GetWindowRect 才是屏幕物理坐标。
    """
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(win.wm_frame(), 16)
        rect = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    x, y = win.winfo_rootx(), win.winfo_rooty()
    return (x, y, x + win.winfo_width(), y + win.winfo_height())


def _grab(win, _index: int, name: str) -> None:
    from PIL import ImageGrab

    win.attributes("-topmost", True)
    win.lift()
    win.update()

    left, top, right, bottom = _window_rect(win)
    img = ImageGrab.grab(bbox=(left, top, right, bottom))
    path = os.path.join(OUT, f"{name}.png")
    img.save(path)
    print(f"  {path}  ({img.width}x{img.height})")


if __name__ == "__main__":
    raise SystemExit(main())
