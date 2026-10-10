"""命令行入口。

参数名沿用原项目（`-c/-v/-u/-p/-s/-t/-l/-f/-ai`），老用户不用重新学；
新增的几个都跟风控有关：
    --no-relay   关掉验证码中继（只想看它多久会被拦时有用）
    --dry-run    打印生效配置与自检结果，不连网站
    --budget     显示今日配额与本次运行的风控统计
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, List, Optional

from . import __version__
from .app import App
from .config import Config
from .errors import AuthError, BudgetExhausted, CaptchaRequired, RiskLocked, ZhsError
from .logger import get as log
from .runner import AiCourseRunner, StudyRunner
from .util import stderr_safe


# ---------------------------------------------------------------------- 二维码

def save_and_render_qr(image_bytes: bytes, target_dir: str, in_terminal: bool = True) -> str:
    path = os.path.join(target_dir, "login_qr.png")
    try:
        os.makedirs(target_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(image_bytes)
    except Exception:
        path = ""
    if in_terminal:
        try:
            render_terminal_qr(image_bytes)
        except Exception as e:
            log().warning(f"终端二维码渲染失败（可打开 {path} 扫描）: {e}")
    return path


def render_terminal_qr(image_bytes: bytes) -> None:
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    img = ImageOps.invert(img)
    img = img.resize((45, 45), Image.Resampling.NEAREST)
    px = img.load()
    lines = []
    for y in range(0, 45, 2):
        row = ["\033[0;37;47m  "]
        for x in range(45):
            top = px[x, y] > 128
            bottom = px[x, y + 1] > 128 if y + 1 < 45 else False
            if top and bottom:
                row.append("\033[0;37;40m  ")
            elif top and not bottom:
                row.append("\033[0;37;40m▀▀")
            elif not top and bottom:
                row.append("\033[0;37;40m▄▄")
            else:
                row.append("\033[0;37;47m  ")
        row.append("\033[0m")
        lines.append("".join(row))
    print("\n".join(lines))
    print("请用手机 App 扫描上方二维码（或打开 state/login_qr.png）")


# ---------------------------------------------------------------------- 参数

def install_browser() -> int:
    """下载 playwright 内置 chromium。

    打包成 exe 后既没有 pip 也没有 playwright 命令行，只能走它内部的
    driver 安装器。正常情况用不到 —— relay 默认优先用系统自带的 Edge。
    """
    print("=" * 68)
    print("下载 playwright 内置 chromium")
    print("提示：Windows 自带的 Edge 已经能直接用，通常不需要这一步。")
    print("     只有 Edge 不可用（被卸载或损坏）时才需要装 chromium。")
    print("=" * 68)
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except Exception as e:
        print(f"[!] 无法调用 playwright 安装器: {e}")
        print("    源码运行请直接执行：python -m playwright install chromium")
        return 1

    try:
        import subprocess

        spec = compute_driver_executable()
        if isinstance(spec, (tuple, list)):
            node, cli = spec
        else:
            node, cli = None, spec
        cmd = ([str(cli), "install", "chromium"] if node is None
               else [str(node), str(cli), "install", "chromium"])
        print(f"执行: {' '.join(cmd)}")
        rc = subprocess.call(cmd, env=get_driver_env())
        print("下载完成" if rc == 0 else f"[!] 安装器退出码 {rc}")
        return rc
    except Exception as e:
        print(f"[!] 下载失败: {e}")
        return 1


def selfcheck() -> int:
    """逐项检查打包是否完整 —— 打包版出问题时先跑这个。"""
    from .paths import is_frozen, runtime_label, variant

    v = variant()
    print("=" * 68)
    print(f"组件自检 · {runtime_label()} · variant={v}")
    print("=" * 68)

    checks = [
        ("yaml", "配置解析"),
        ("loguru", "日志"),
        ("requests", "网络请求"),
        ("Crypto.Cipher.AES", "请求加密"),
        ("PIL.Image", "图片处理"),
        # GUI 版必须要它，命令行版的 --gui 也要。
        # 这条曾经漏掉：spec 里把 tkinter exclude 掉了，而自检走的又是
        # 命令行分支（根本不 import tkinter），于是全绿通过、用户一开就崩。
        ("tkinter", "图形界面"),
        ("tkinter.ttk", "界面控件"),
    ]
    if v != "lite":
        checks += [
            ("playwright", "浏览器中继"),
            ("playwright._impl._driver", "中继驱动"),
            ("ddddocr", "验证码识别"),
            ("cv2", "图像处理"),
            ("onnxruntime", "OCR 推理引擎"),
        ]

    ok = True
    for mod, desc in checks:
        try:
            __import__(mod)
            print(f"  [ok]  {desc:<14} {mod}")
        except Exception as e:
            print(f"  [!!]  {desc:<14} {mod}  →  {e}")
            ok = False

    # 浏览器内核：打包版靠系统 Edge 才能开箱即用
    print("-" * 68)
    browsers = _detect_browsers()
    if browsers:
        for line in browsers:
            print(f"  [ok]  系统浏览器     {line}")
    else:
        print("  [!!]  系统浏览器     没找到 Edge / Chrome")

    if v != "lite":
        try:
            from playwright._impl._driver import compute_driver_executable  # noqa: F401
            print("  [ok]  playwright 驱动可调用")
        except Exception as e:
            print(f"  [!!]  playwright 驱动不可用 → {e}")

    print("=" * 68)
    print("自检通过" if ok else "自检发现问题（见上方 [!!] 行）")
    return 0 if ok else 1


def _detect_browsers() -> List[str]:
    candidates = {
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
    }
    found: List[str] = []
    for name, paths in candidates.items():
        for p in paths:
            if os.path.exists(p):
                found.append(f"{name} → {p}")
                break
    if not found:
        import shutil as _sh
        for exe in ("msedge", "chrome", "chromium"):
            p = _sh.which(exe)
            if p:
                found.append(f"{exe} → {p}")
    return found


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zhsgo",
        description="智慧树自动学习工具（内置人机验证中继）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python main.py -c 1919                 刷校内课 1919\n"
            "  python main.py -c <racId>              刷共享课\n"
            "  python main.py -f                      拉取课程清单到 courses.json\n"
            "  python main.py -ai 114514 4444         刷 AI 课程\n"
            "  python main.py --dry-run               只做自检，不连网站\n"
        ),
    )
    p.add_argument("--config", default=None, help="配置文件路径（默认 ./config.yaml）")
    p.add_argument("-c", "--course", nargs="+", help="课程 ID（多个）")
    p.add_argument("-v", "--videos", nargs="+", help="视频 ID（多个，需配合 -c）")
    p.add_argument("-u", "--username", help="账号")
    p.add_argument("-p", "--password", help="密码（会留在命令历史里，慎用）")
    p.add_argument("-q", "--qrlogin", action="store_true", help="强制使用二维码登录")
    p.add_argument("-s", "--speed", type=float, help="播放速度（会被夹到前端上限）")
    p.add_argument("-t", "--threshold", type=float, help="完成判定阈值，默认 0.91")
    p.add_argument("-l", "--limit", type=float, help="单门课时限（分钟）")
    p.add_argument("-f", "--fetch", action="store_true", help="拉取课程清单")
    p.add_argument("-ai", "--aicourse", nargs=2, metavar=("COURSE_ID", "CLASS_ID"),
                   help="刷 AI 课程")
    p.add_argument("--no-exam", action="store_true", help="AI 课程只刷视频不做题")
    p.add_argument("--no-relay", action="store_true", help="关闭验证码中继")
    p.add_argument("--install-browser", action="store_true",
                   help="下载 playwright 内置 chromium（一般用不到，系统 Edge 可直接用）")
    p.add_argument("--selfcheck", action="store_true",
                   help="检查各组件是否完好（打包版出问题时先跑这个）")
    p.add_argument("--dry-run", action="store_true", help="只打印配置与自检，不连网站")
    p.add_argument("--gui", action="store_true", help="启动图形界面（等同 zhs-ghost-gui.exe）")
    p.add_argument("--budget", action="store_true", help="显示配额与风控统计后退出")
    p.add_argument("-d", "--debug", action="store_true", help="调试日志")
    p.add_argument("--json", action="store_true", help="清单以 JSON 输出")
    p.add_argument("--version", action="version", version=f"zhsgo {__version__}")
    return p


def apply_cli_overrides(cfg: Config, args: argparse.Namespace) -> None:
    if args.username:
        cfg.auth.username = args.username
    if args.password:
        cfg.auth.password = args.password
    if args.qrlogin:
        cfg.auth.use_qr = True
    if args.speed is not None:
        cfg.study.speed = args.speed
    if args.threshold is not None:
        cfg.study.end_threshold = args.threshold
    if args.limit is not None:
        cfg.budget.per_course_minutes = args.limit
    if args.no_relay:
        cfg.relay.enabled = False
    if args.no_exam:
        cfg.ai.skip_exam = True
    if args.debug:
        cfg.log.level = "DEBUG"


# ---------------------------------------------------------------------- 主流程

def print_config(cfg: Config, problems: List[str], mode: str = "") -> None:
    from .paths import variant

    if not cfg.relay.enabled:
        relay_line = "关闭"
    elif variant() == "lite":
        relay_line = "开启（精简版：验证码需手动滑）"
    elif cfg.relay.headless:
        relay_line = "开启（无头浏览器）"
    else:
        relay_line = "开启（有头浏览器，可自动识别）"

    lines = [
        "=" * 72,
        f"zhsgo {__version__}" + (f"  [{mode}]" if mode else ""),
        "-" * 72,
        f"  配置文件      {cfg.config_path or '(内置默认)'}",
        f"  状态文件      {cfg.state_file}",
        f"  代理          {cfg.proxies or '（直连）'}",
        f"  指纹          {cfg.fingerprint.describe() if hasattr(cfg.fingerprint, 'describe') else cfg.fingerprint}",
        f"  播放速度上限  {cfg.pacer.max_speed}x  (默认 {cfg.pacer.default_speed}x)",
        f"  上报间隔      {cfg.pacer.report_interval[0]:.0f}~{cfg.pacer.report_interval[1]:.0f}s "
        f"σ={cfg.pacer.report_sigma}",
        f"  微暂停        {cfg.pacer.pause_chance * 100:.2f}%/s，时长 "
        f"{cfg.pacer.pause_seconds[0]:.0f}~{cfg.pacer.pause_seconds[1]:.0f}s",
        f"  时间戳        {'真实毫秒+抖动' if cfg.pacer.real_millisecond_ts else '秒级（*000，风险高）'}",
        f"  会话纪律      单次 {cfg.budget.session_minutes[0]:.0f}~{cfg.budget.session_minutes[1]:.0f} 分钟，"
        f"休息 {cfg.budget.rest_minutes[0]:.0f}~{cfg.budget.rest_minutes[1]:.0f} 分钟",
        f"  单日上限      {cfg.budget.daily_minutes:.0f} 分钟 / {cfg.budget.daily_sessions} 次会话",
        f"  验证码中继    {relay_line}",
        f"  AI 作答       {'开启，后端=' + cfg.ai.backend if cfg.ai.enabled else '关闭'}",
        "=" * 72,
    ]
    for line in lines:
        print(line)
    if problems:
        print("\n配置自检发现问题：")
        for item in problems:
            print(f"  [!] {item}")
        print()
    else:
        print("配置自检通过\n")


def _run(argv: List[str]) -> int:
    stderr_safe()

    from .paths import app_root, is_frozen, runtime_label

    if is_frozen():
        # 打包后双击启动时 cwd 可能是 system32 或无权限目录，
        # 必须切到 exe 所在目录，配置文件才好找
        try:
            os.chdir(app_root())
        except Exception:
            pass

    args = build_parser().parse_args(argv)

    if args.gui:
        from .gui import launch
        return launch(args.config)

    if args.install_browser:
        return install_browser()

    if args.selfcheck:
        return selfcheck()

    cfg = Config.load(args.config)
    apply_cli_overrides(cfg, args)
    problems = cfg.validate()
    print_config(cfg, problems, runtime_label())

    if args.dry_run:
        print("dry-run 结束（没有连接任何服务）")
        return 0

    try:
        with App(cfg) as app:
            if args.budget and not args.course and not args.aicourse and not args.fetch:
                log().info(app.budget.report())
                log().info("节拍分布：\n" + app.pacer.histogram())
                log().info("请求间隔样本：" + json.dumps(app.http.pacing_report(), ensure_ascii=False))
                return 0

            app.login(on_qr=lambda img: save_and_render_qr(img, os.path.dirname(cfg.state_file)))

            if args.fetch:
                courses = StudyRunner(app).list_courses()
                path = os.path.join(cfg.base_dir, "courses.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(courses, f, indent=2, ensure_ascii=False)
                log().info(f"课程清单已写入 {path}（{len(courses)} 门）")
                if args.json:
                    print(json.dumps(courses, indent=2, ensure_ascii=False))
                return 0

            if args.aicourse:
                course_id, class_id = args.aicourse
                AiCourseRunner(app).run(_maybe_int(course_id), _maybe_int(class_id))
                return 0

            runner = StudyRunner(app)

            if args.course:
                if args.videos:
                    for cid in args.course:
                        for vid in args.videos:
                            runner.run_course(cid)
                    return 0
                for cid in args.course:
                    runner.run_course(cid)
                return 0

            log().info("未指定课程，自动处理全部课程")
            runner.run_all()
            return 0

    except BudgetExhausted as e:
        log().warning(f"配额用尽，正常收工: {e}")
        return 0
    except CaptchaRequired as e:
        log().error(f"人机验证未能自动通过，需要人工介入: {e}")
        return 3
    except RiskLocked as e:
        log().error(f"风控锁定，建议今天先停手: {e}")
        return 4
    except AuthError as e:
        log().error(f"登录问题: {e}")
        return 2
    except KeyboardInterrupt:
        log().warning("用户中断")
        return 130
    except ZhsError as e:
        log().error(f"运行失败: {e}")
        return 1


def _maybe_int(value: str) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def main(argv: Optional[List[str]] = None) -> int:
    from .paths import is_frozen

    raw = list(sys.argv[1:] if argv is None else argv)
    code = _run(raw)

    # 双击运行时控制台窗口会随进程退出立刻关闭 —— 出错的话用户根本
    # 没机会看到原因。带参数调用（脚本、CI）时不阻塞。
    if not raw and is_frozen():
        try:
            input("\n（按回车键关闭窗口）")
        except Exception:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
