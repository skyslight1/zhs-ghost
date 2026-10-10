#!/usr/bin/env python3
"""一键打包 zhs-ghost。

用法：

    python packaging/build.py lite            # 精简版单文件 exe
    python packaging/build.py full            # 完整版单文件 exe（含验证码识别）
    python packaging/build.py all             # 两个都出
    python packaging/build.py full --dir      # 目录形态（启动快，适合自己用）
    python packaging/build.py full --no-zip   # 不打 zip

产物在 dist/ 下。打包完会自动跑一次 `--dry-run` 自检，确认 exe 真能启动。
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "zhs-ghost.spec")
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")

VARIANT_DEPS = {
    "full": ["playwright", "ddddocr", "cv2", "onnxruntime", "numpy", "PIL"],
    "lite": [],
}


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


def check_env(variant: str) -> list[str]:
    problems: list[str] = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problems.append("未安装 PyInstaller：pip install pyinstaller")
    for mod in VARIANT_DEPS.get(variant, []):
        try:
            __import__(mod)
        except ImportError:
            problems.append(f"{variant} 版需要 {mod}：pip install -r requirements.txt")
    return problems


def build_one(variant: str, onefile: bool) -> tuple[str, float]:
    name = "zhs-ghost" if variant == "full" else "zhs-ghost-lite"
    env = os.environ.copy()
    env["ZHS_VARIANT"] = variant
    env["ZHS_ONEFILE"] = "1" if onefile else "0"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level", "WARN",
        "--distpath", DIST,
        "--workpath", WORK,
        SPEC,
    ]

    print(f"\n{'=' * 68}")
    print(f"构建 {name}  ({'单文件' if onefile else '目录'})")
    print(f"{'=' * 68}")
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"[!] PyInstaller 失败，退出码 {proc.returncode}")

    target = os.path.join(DIST, f"{name}.exe" if onefile else name)
    if not os.path.exists(target):
        raise SystemExit(f"[!] 没找到产物: {target}")

    size = os.path.getsize(target) if onefile else dir_size(target)
    print(f"完成，用时 {time.time() - t0:.0f}s，体积 {human(size)}")
    return target, size


def self_test(variant: str, onefile: bool) -> bool:
    """跑一次 --dry-run，确认 exe 真能启动（而不是打出来一个坏文件）。"""
    name = "zhs-ghost" if variant == "full" else "zhs-ghost-lite"
    exe = os.path.join(DIST, f"{name}.exe") if onefile else os.path.join(DIST, name, f"{name}.exe")
    if not os.path.exists(exe):
        print(f"  [!!] 找不到 {exe}")
        return False

    print(f"\n自检 {os.path.basename(exe)} ...")
    tmp = tempfile.mkdtemp(prefix="zhsgo-selftest-")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [exe, "--dry-run"], cwd=tmp,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=900,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and "dry-run 结束" in out
        print(f"  退出码 {proc.returncode}，用时 {time.time() - t0:.1f}s")
        for line in out.strip().splitlines()[:16]:
            print(f"  | {line}")
        print("  自检通过" if ok else "  自检失败（见上方输出）")
        return ok
    except subprocess.TimeoutExpired:
        print("  [!!] 自检超时（900s）—— 单文件版首次启动需要解压，体积大时可能很慢")
        return False
    except Exception as e:
        print(f"  [!!] 自检异常: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        # exe 启动时会 chdir 到自己所在目录，所以配置/状态会落在 dist/ 里，
        # 别把它们混进产物目录
        for junk in ("config.yaml", "state", "logs", "courses.json"):
            p = os.path.join(DIST, junk)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)


def make_zip(variant: str, onefile: bool) -> str:
    name = "zhs-ghost" if variant == "full" else "zhs-ghost-lite"
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
        # 顺带把使用教程和示例配置放进压缩包，解压就能看
        for extra, arc in (("config.example.yaml", "config.example.yaml"),
                           (os.path.join("docs", "使用教程.md"), "使用教程.md"),
                           ("README.md", "README.md"),
                           ("LICENSE", "LICENSE")):
            path = os.path.join(ROOT, extra)
            if os.path.exists(path):
                z.write(path, arc)

    size = os.path.getsize(out)
    print(f"  {out}  ({human(size)})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="packaging/build.py")
    ap.add_argument("variant", choices=["full", "lite", "all"])
    ap.add_argument("--dir", action="store_true", help="输出目录形态而非单文件")
    ap.add_argument("--no-zip", action="store_true", help="不打 zip")
    ap.add_argument("--no-test", action="store_true", help="跳过后自检")
    args = ap.parse_args()

    variants = ["full", "lite"] if args.variant == "all" else [args.variant]

    # 环境检查
    for v in variants:
        problems = check_env(v)
        if problems:
            print(f"[!] {v} 版环境不满足：")
            for p in problems:
                print(f"    - {p}")
            return 1

    onefile = not args.dir
    results = []
    for v in variants:
        target, size = build_one(v, onefile)
        ok = True if args.no_test else self_test(v, onefile)
        results.append((v, target, size, ok))
        if not args.no_zip and ok:
            make_zip(v, onefile)

    print(f"\n{'=' * 68}")
    print("结果")
    print(f"{'=' * 68}")
    for v, target, size, ok in results:
        mark = "OK " if ok else "!! "
        print(f"  [{mark}] {os.path.relpath(target, ROOT)}  {human(size)}")
    return 0 if all(r[3] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
