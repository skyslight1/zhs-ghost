#!/usr/bin/env python3
"""验证：点「扫码登录」之后窗口不会卡死。

复现的是用户实际走的那条路径 —— 打包后的 GUI 启动 → App 初始化
（里面会 setup_logging，把 sys.stderr 注册成 loguru sink）→ 触发登录。

App 初始化里的 loguru 自递归就是这么炸的，而源码级测试覆盖不到打包环境，
所以这个检查必须对着真 exe 跑。

    python tests/check_gui_login_no_hang.py dist\\zhs-ghost-lite-gui.exe

返回 0 表示窗口点完仍然响应。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

APP_TITLE_PREFIX = "zhs-ghost"   # 主窗口标题带版本号（v1.3.0 起），按前缀找更稳
WAIT_BEFORE = 6.0     # 等窗口起来
WAIT_AFTER = 18.0     # 点完按钮后观察多久


def _find_window(title_prefix: str) -> int:
    """按标题前缀找顶层窗口（需要进程 DPI aware，所以调用方要先设好）。"""
    import ctypes

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value.startswith(title_prefix):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(_enum, 0)
    return found[0] if found else 0


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: check_gui_login_no_hang.py <exe>")
        return 2
    if sys.platform != "win32":
        print("仅 Windows 可用，跳过")
        return 0

    exe = os.path.abspath(sys.argv[1])
    if not os.path.exists(exe):
        print(f"[!!] 找不到 {exe}")
        return 1

    _dpi_aware()
    import ctypes

    user32 = ctypes.windll.user32

    env = os.environ.copy()
    env["ZHS_AUTOTEST_LOGIN"] = "1"      # 让程序自己点那次按钮

    print(f"启动 {os.path.basename(exe)}（自动触发扫码登录）...")
    proc = subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hwnd = 0
    try:
        time.sleep(WAIT_BEFORE)
        if proc.poll() is not None:
            print(f"[!!] 进程在启动阶段就退出了，退出码 {proc.returncode}")
            return 1

        hwnd = _find_window(APP_TITLE_PREFIX)
        if not hwnd:
            print("[!!] 找不到窗口")
            return 1
        print(f"[ok] 窗口已找到 (hwnd=0x{hwnd:X})")

        # 等自动点击 + App 初始化 + 二维码拉取走完
        deadline = time.time() + WAIT_AFTER
        while time.time() < deadline:
            if proc.poll() is not None:
                print(f"[!!] 进程中途退出，退出码 {proc.returncode}")
                return 1
            if user32.IsHungAppWindow(hwnd):
                print("[!!] 窗口无响应（IsHungAppWindow 返回真）—— 又是卡死")
                return 1
            time.sleep(0.5)

        print(f"[ok] 点击后 {WAIT_AFTER:.0f}s 窗口持续响应，进程存活")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
