#!/usr/bin/env python3
"""GUI 冒烟测试：建窗口、切换标签页、模拟进度更新、销毁。

    python tests/gui_smoke.py

不需要显示器也能跑（Tk 会退化到无头模式时自动跳过）。
目的是抓住"import 就报错""控件属性写错""布局参数非法"这类低级问题 ——
这些在真正的用户点开之前是看不见的。
"""
from __future__ import annotations

import os
import sys
import traceback

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

results = []


def check(cond: bool, msg: str) -> None:
    results.append((bool(cond), msg))
    print(("  [ok]  " if cond else "  [!!]  ") + msg)


def main() -> int:
    try:
        import tkinter as tk
    except ImportError as e:
        print(f"没有 tkinter，跳过 GUI 测试: {e}")
        return 0

    # 先确认能建窗口（无头环境会在这里失败）
    try:
        probe = tk.Tk()
        probe.withdraw()
        probe.destroy()
    except Exception as e:
        print(f"当前环境无法创建窗口，跳过 GUI 测试: {e}")
        return 0

    print("\n== GUI 冒烟 ==")
    try:
        from zhsgo.gui.window import MainWindow
        from zhsgo.observer import PHASE_REST, PHASE_STUDY, Progress

        win = MainWindow()
        win.update()
        check(True, "主窗口构建成功")

        tabs = win.notebook.index("end")
        check(tabs == 4, f"标签页数量 = {tabs}")

        for i in range(tabs):
            win.notebook.select(i)
            win.update()
        check(True, "四个标签页都能渲染")

        # 二维码弹窗生命周期：使用一个有效 PNG，确认显示对象持有引用，关闭后真正销毁。
        try:
            import base64
            qr_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            win.tab_study.show_qr(qr_bytes)
            win.update()
            qr_win = win.tab_study._qr_window
            check(qr_win is not None and qr_win.winfo_exists(), "二维码弹窗创建")
            check(win.tab_study._qr_photo is not None, "二维码图片引用被保留")
            win.tab_study._on_qr_window_closed()
            win.update()
            check(win.tab_study._qr_window is None, "关闭二维码后弹窗引用清理")
        except Exception as e:
            check(False, f"二维码弹窗生命周期异常: {e}")

        win.tab_study.update_progress(Progress(
            phase=PHASE_STUDY, course="测试课程", video="第 1 讲",
            message="学习中", current=45.0, total=100.0))
        win.update()
        check(win.tab_study.lbl_percent.cget("text") == "45.0%",
              f"进度百分比渲染: {win.tab_study.lbl_percent.cget('text')}")

        win.tab_study.update_progress(Progress(
            phase=PHASE_REST, course="测试课程", message="休息中", current=10, total=60))
        win.update()
        check("休息" in win.tab_study.kv_state._var.get(), "休息状态渲染")

        # 课程表格
        win.tab_courses.set_courses([
            {"type": "hike", "name": "高等数学", "id": "1919"},
            {"type": "zhidao", "name": "中国近现代史", "id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"},
        ])
        win.update()
        check(len(win.tab_courses.tree.get_children()) == 2, "课程表格填充")
        check(len(win.tab_courses.selected_ids()) == 2, "默认全选")
        win.tab_courses._set_all(False)
        check(win.tab_courses.selected_ids() == [], "取消全选")

        # 配置页读写
        win.tab_config.vars["pacer.max_speed"].set("1.4")
        win.tab_config.vars["budget.daily_minutes"].set("200")
        win.tab_config._save()
        win.update()
        check(abs(win.cfg.pacer.max_speed - 1.4) < 1e-9, "配置保存：pacer.max_speed")
        check(abs(win.cfg.budget.daily_minutes - 200) < 1e-9, "配置保存：budget.daily_minutes")

        # 非法输入不应崩，且要提示
        win.tab_config.vars["budget.daily_minutes"].set("abc")
        win.tab_config._save()
        win.update()
        check("不是合法数字" in win.tab_config.status.cget("text"), "非法输入被拦下并提示")
        win.tab_config.vars["budget.daily_minutes"].set("200")

        # 日志页
        win.tab_log.append("12:00:00  INFO    测试日志", "INFO")
        win.tab_log.append("12:00:01  ERROR   测试错误", "ERROR")
        win.tab_log._apply_filter()
        win.update()
        content = win.tab_log.text.get("1.0", "end")
        check("测试日志" in content, "日志写入")
        win.tab_log.append("12:00:02  DEBUG   详细调试", "DEBUG")
        win.update()
        check("详细调试" not in win.tab_log.text.get("1.0", "end"),
              "DEBUG 在 INFO 阈值下被过滤")

        # 观察者节流
        from zhsgo.gui.window import GuiObserver
        import threading
        calls = []
        obs = GuiObserver(win.bridge, lambda p: calls.append(p),
                          threading.Event(), threading.Event())
        for _ in range(50):
            obs.progress(Progress(phase=PHASE_STUDY, current=1, total=100))
        win.update()
        win.bridge._pump()
        check(len(calls) < 50, f"进度回调被节流（50 次调用只推了 {len(calls)} 次）")

        # 停止闸门
        ev = threading.Event()
        obs2 = GuiObserver(win.bridge, lambda p: None, ev, threading.Event())
        check(obs2.should_stop() is False, "未停止时 should_stop() = False")
        obs2.stop()
        check(obs2.should_stop() is True, "调用 stop() 后 should_stop() = True")

        # 走正常关闭路径（WM_DELETE_WINDOW → on_close → 先停 after 再 destroy）。
        # 直接 destroy 的话，Tk 的 after 队列里会留下指向已删除命令的条目，
        # 之后在 stderr 刷一串 "invalid command name ..._pump"。
        win.on_close()
        check(True, "窗口正常销毁")

    except Exception:
        traceback.print_exc()
        check(False, "GUI 冒烟过程抛异常")

    # 布局越界检查单独跑一次（窗口已经销毁的话就重开一个）
    try:
        from zhsgo.gui.window import MainWindow as MW

        win2 = MW()
        win2.geometry("1000x760")
        win2.update()
        win2.notebook.select(0)
        win2.update()

        def overflows(widget):
            bad = []
            pw = widget.winfo_width()
            for child in widget.winfo_children():
                try:
                    if child.winfo_ismapped():
                        cw = child.winfo_width()
                        if pw > 1 and cw > pw + 4:
                            bad.append(f"{child.winfo_class()}({cw}>{pw})")
                except Exception:
                    pass
                bad.extend(overflows(child))
            return bad

        bad = overflows(win2)
        check(not bad, "没有控件溢出父容器" + (f" —— {bad[:4]}" if bad else ""))
        win2.on_close()
    except Exception:
        traceback.print_exc()
        check(False, "布局检查抛异常")

    # ---------------------------------------------------------------- 回归
    # windowed exe 的 stdout/stderr 代理曾经把写入转发给 loguru，而 App 初始化
    # 又会把 sys.stderr 注册成 loguru sink —— 于是写日志和写 stderr 互相触发，
    # 无限递归。表现是"点一下扫码登录窗口就未响应"。
    # 这个 bug 只有真跑一遍 setup_logging 才暴露，所以单起一个进程验证，
    # 并用超时兜住（万一又递归会挂住）。
    print("\n== 回归：stream 代理 vs loguru ==")
    import subprocess

    script = os.path.join(HERE, "tests", "check_stream_proxy.py")
    try:
        proc = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        ok = proc.returncode == 0 and "STREAM_PROXY_OK" in (proc.stdout or "")
        detail = "" if ok else f" —— {(proc.stderr or proc.stdout or '')[-220:]}"
        check(ok, "stream 代理不会与 loguru 互相递归" + detail)
    except subprocess.TimeoutExpired:
        check(False, "stream 代理测试超时（递归或死锁）")
    except Exception as e:
        check(False, f"stream 代理测试异常: {e}")

    print()
    failed = [m for ok, m in results if not ok]
    if failed:
        print(f"FAILED: {len(failed)}/{len(results)}")
        for m in failed:
            print("  - " + m)
        return 1
    print(f"ALL PASS ({len(results)} 项)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
