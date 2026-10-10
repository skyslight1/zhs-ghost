#!/usr/bin/env python3
"""一键打包 zhs-ghost。

用法：

    python packaging/build.py release           # 出全部四个 exe（发版用）
    python packaging/build.py gui               # 只出两个 GUI 版
    python packaging/build.py cli               # 只出两个命令行版
    python packaging/build.py full --gui        # 只出完整版 GUI
    python packaging/build.py full              # 只出完整版命令行

产物在 dist/ 下。打包完会自动跑一次 `--dry-run` / `--selfcheck` 自检，
确认 exe 真能启动，而不是打出个坏文件。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "zhs-ghost.spec")
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")

VARIANT_DEPS = {
    "full": ["playwright", "ddddocr", "cv2", "onnxruntime", "numpy", "PIL"],
    "lite": [],
}

# (variant, gui) 组合
ALL_TARGETS: List[Tuple[str, bool]] = [
    ("full", True), ("lite", True), ("full", False), ("lite", False),
]


def exe_name(variant: str, gui: bool) -> str:
    base = "zhs-ghost" if variant == "full" else "zhs-ghost-lite"
    return f"{base}-gui" if gui else base


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def dir_size(path: str) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total


def check_env(variant: str) -> List[str]:
    problems: List[str] = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problems.append("未安装 PyInstaller：pip install pyinstaller")
    for mod in VARIANT_DEPS.get(variant, []):
        try:
            __import__(mod)
        except ImportError:
            problems.append(f"{variant} 版需要 {mod}：pip install -r requirements.txt")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        problems.append("缺少 tkinter（GUI 版必须）：重装 Python 时勾选 tcl/tk 组件")
    return problems


def kill_stale(name: str) -> int:
    """构建前杀掉同名的残留进程。

    Windows 上正在运行的 exe 会锁住文件，PyInstaller 覆盖时会直接
    `PermissionError: [WinError 5] 拒绝访问`。

    自检阶段会真的把 GUI 启动起来，如果那个进程没被完全回收
    （比如被强杀、或者用户在别处开着），下一次构建就撞上了。
    这里统一清一遍，省得每次都要手动去任务管理器里找。
    """
    if sys.platform != "win32":
        return 0
    try:
        proc = subprocess.run(["taskkill", "/F", "/T", "/IM", f"{name}.exe"],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            print(f"  （已清理残留的 {name}.exe 进程）")
            return 1
    except Exception:
        pass
    return 0


def build_one(variant: str, gui: bool, onefile: bool) -> Tuple[str, float]:
    name = exe_name(variant, gui)
    kill_stale(name)

    env = os.environ.copy()
    env["ZHS_VARIANT"] = variant
    env["ZHS_ONEFILE"] = "1" if onefile else "0"
    env["ZHS_GUI"] = "1" if gui else "0"

    label = f"{name}  ({'GUI' if gui else '命令行'}，{'单文件' if onefile else '目录'})"
    print(f"\n{'=' * 68}")
    print(f"构建 {label}")
    print(f"{'=' * 68}")

    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--log-level", "WARN", "--distpath", DIST, "--workpath", WORK, SPEC],
        env=env, cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"[!] PyInstaller 失败，退出码 {proc.returncode}")

    target = os.path.join(DIST, f"{name}.exe" if onefile else name)
    if not os.path.exists(target):
        raise SystemExit(f"[!] 没找到产物: {target}")

    size = os.path.getsize(target) if onefile else dir_size(target)
    print(f"完成，用时 {time.time() - t0:.0f}s，体积 {human(size)}")
    return target, size


def self_test(variant: str, gui: bool, onefile: bool) -> bool:
    """打包后必须真的把程序跑起来。

    ⚠️ 这里踩过一次大坑：GUI 版原先只跑 `--selfcheck`，而那条路径走的是
    命令行分支，**根本不 import tkinter**。于是 tkinter 被 exclude 掉了
    都没发现 —— 自检全绿，用户一下载就是一屏 traceback。

    所以 GUI 版现在做的是"真的启动它，看窗口进程能不能活下来"。
    """
    name = exe_name(variant, gui)
    exe = os.path.join(DIST, f"{name}.exe") if onefile else os.path.join(DIST, name, f"{name}.exe")
    if not os.path.exists(exe):
        print(f"  [!!] 找不到 {exe}")
        return False

    tmp = tempfile.mkdtemp(prefix="zhsgo-selftest-")
    try:
        if gui:
            ok = _test_gui_launch(exe, tmp)
            # 再走一遍用户真正会走的路：点「扫码登录」→ App 初始化。
            # App 初始化里的 loguru 自递归就是在这条路上炸的，
            # 只开个窗口是测不出来的。
            ok = _test_gui_login(exe, tmp) and ok
            # 顺带跑一次组件自检（覆盖依赖、浏览器内核）
            ok = _test_cli_run(exe, tmp, ["--selfcheck"], "自检通过") and ok
        else:
            ok = _test_cli_run(exe, tmp, ["--dry-run"], "dry-run 结束")
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for junk in ("config.yaml", "state", "logs", "courses.json"):
            p = os.path.join(DIST, junk)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)


def _test_gui_launch(exe: str, cwd: str, wait: float = 12.0) -> bool:
    """启动 GUI，确认它在若干秒后仍然活着（= 窗口真的开起来了）。

    windowed exe 没有 stdout，抓不到 traceback，所以只能靠"进程有没有
    提前退出"来判断。
    """
    print(f"\n自检 {os.path.basename(exe)}（真实启动窗口，观察 {wait:.0f}s）...")
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            [exe], cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except Exception as e:
        print(f"  [!!] 无法启动: {e}")
        return False

    try:
        deadline = time.time() + wait
        while time.time() < deadline:
            if proc.poll() is not None:
                out = ""
                try:
                    out = proc.stdout.read() if proc.stdout else ""
                except Exception:
                    pass
                print(f"  [!!] 进程在 {time.time() - t0:.1f}s 后退出了，"
                      f"退出码 {proc.returncode}")
                for line in (out or "").strip().splitlines()[-16:]:
                    print(f"  | {line}")
                print("  → 窗口版最常见的两种原因：")
                print("     · tkinter 没打进去（检查 spec 的 excludes）")
                print("     · 缺 tcl/tk 数据文件")
                return False
            time.sleep(0.4)
        print(f"  [ok] {wait:.0f}s 后进程仍在运行 —— 窗口已打开")
        return True
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()


def _test_gui_login(exe: str, cwd: str) -> bool:
    """让 exe 自己点一次「扫码登录」，确认窗口不卡死。

    走的是用户真实路径：GUI 启动 → `_ensure_app()` 构造 App →
    `setup_logging()` 把 sys.stderr 注册成 loguru sink → 拉二维码。

    这里炸过一次：`_StreamProxy` 把 stderr 写入转发给 loguru，和
    stderr sink 互相触发，无限递归，用户点一下按钮窗口就未响应。
    源码级测试覆盖不到打包环境，所以必须对着真 exe 跑一遍。
    """
    script = os.path.join(ROOT, "tests", "check_gui_login_no_hang.py")
    if not os.path.isfile(script):
        print("  [--] 跳过登录点击测试（找不到脚本）")
        return True

    print(f"\n自检 {os.path.basename(exe)}（自动点击「扫码登录」）...")
    try:
        proc = subprocess.run(
            [sys.executable, script, exe],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=240,
        )
        for line in (proc.stdout or "").strip().splitlines():
            print(f"  | {line}")
        for line in (proc.stderr or "").strip().splitlines()[-6:]:
            print(f"  | {line}")
        ok = proc.returncode == 0
        print("  自检通过" if ok else "  自检失败")
        return ok
    except subprocess.TimeoutExpired:
        print("  [!!] 超时 —— 窗口大概率卡死了")
        return False
    except Exception as e:
        print(f"  [!!] 异常: {e}")
        return False


def _test_cli_run(exe: str, cwd: str, args: list, marker: str) -> bool:
    print(f"\n自检 {os.path.basename(exe)} ({' '.join(args)}) ...")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [exe] + args, cwd=cwd,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=900,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and marker in out
        print(f"  退出码 {proc.returncode}，用时 {time.time() - t0:.1f}s")
        for line in out.strip().splitlines()[:14]:
            print(f"  | {line}")
        print("  自检通过" if ok else "  自检失败（见上方输出）")
        return ok
    except subprocess.TimeoutExpired:
        print("  [!!] 自检超时")
        return False
    except Exception as e:
        print(f"  [!!] 自检异常: {e}")
        return False


def make_zip(variant: str, gui: bool, onefile: bool) -> str:
    """每个变体单独打一个 zip，里面附教程和示例配置。"""
    name = exe_name(variant, gui)
    src = os.path.join(DIST, f"{name}.exe") if onefile else os.path.join(DIST, name)
    out = os.path.join(DIST, f"{name}-windows-x64.zip")

    print(f"打包 {os.path.basename(out)} ...")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if onefile:
            z.write(src, f"{name}.exe")
        else:
            for base, _dirs, files in os.walk(src):
                for f in files:
                    full = os.path.join(base, f)
                    rel = os.path.relpath(full, src)
                    z.write(full, os.path.join(name, rel))
        for extra, arc in (
            ("config.example.yaml", "config.example.yaml"),
            (os.path.join("docs", "使用教程.md"), "使用教程.md"),
            ("README.md", "README.md"),
            ("LICENSE", "LICENSE"),
        ):
            path = os.path.join(ROOT, extra)
            if os.path.exists(path):
                z.write(path, arc)

    size = os.path.getsize(out)
    print(f"  {out}  ({human(size)})")
    return out


def resolve_targets(ns) -> List[Tuple[str, bool]]:
    v = ns.variant
    if v == "release":
        return list(ALL_TARGETS)
    if v == "gui":
        return [("full", True), ("lite", True)]
    if v == "cli":
        return [("full", False), ("lite", False)]
    return [(v, ns.gui)]


def main() -> int:
    ap = argparse.ArgumentParser(prog="packaging/build.py")
    ap.add_argument("variant", nargs="?", default="release",
                    choices=["full", "lite", "gui", "cli", "release"],
                    help="full/lite 出单个变体；gui/cli 出两个；release 出全部四个（默认）")
    ap.add_argument("--gui", action="store_true", help="配合 full/lite 使用，出图形界面版")
    ap.add_argument("--dir", action="store_true", help="输出目录形态而非单文件")
    ap.add_argument("--no-zip", action="store_true", help="不打 zip")
    ap.add_argument("--no-test", action="store_true", help="跳过后自检")
    ns = ap.parse_args()

    targets = resolve_targets(ns)
    onefile = not ns.dir

    for variant, _gui in targets:
        problems = check_env(variant)
        if problems:
            print(f"[!] {variant} 版环境不满足：")
            for p in problems:
                print(f"    - {p}")
            return 1

    results = []
    for variant, gui in targets:
        target, size = build_one(variant, gui, onefile)
        ok = True if ns.no_test else self_test(variant, gui, onefile)
        results.append((exe_name(variant, gui), target, size, ok))
        if not ns.no_zip and ok:
            make_zip(variant, gui, onefile)

    print(f"\n{'=' * 68}")
    print("结果")
    print(f"{'=' * 68}")
    for name, target, size, ok in results:
        print(f"  [{'OK' if ok else '!!'}] {os.path.relpath(target, ROOT):44} {human(size)}")
    return 0 if all(r[3] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
