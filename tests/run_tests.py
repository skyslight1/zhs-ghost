#!/usr/bin/env python3
"""零依赖自测：不联网、不登录，验证每个模块的核心行为。

    python tests/run_tests.py

用假时钟把 300 秒的视频循环在毫秒内跑完，从而能真正断言节拍逻辑，
而不是靠肉眼看代码猜。
"""
from __future__ import annotations

import io
import json
import os
import random
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from zhsgo.ai.client import Answerer  # noqa: E402
from zhsgo.clock import FakeClock  # noqa: E402
from zhsgo.config import Config  # noqa: E402
from zhsgo.crypto import AI_KEY, EXAM_KEY, HOME_KEY, QA_KEY, VIDEO_KEY, AesCbc, get_ev, hike_sign, rev_ev  # noqa: E402
from zhsgo.errors import BudgetExhausted, CaptchaRequired  # noqa: E402
from zhsgo.net.fingerprint import Fingerprint, sec_ch_ua  # noqa: E402
from zhsgo.risk import Budget, Guard, Pacer, WatchPoint  # noqa: E402
from zhsgo.risk.budget import BudgetConfig  # noqa: E402
from zhsgo.risk.guard import GuardConfig  # noqa: E402
from zhsgo.risk.pacer import PacerConfig  # noqa: E402
from zhsgo.runner.study import StudyRunner, ZhidaoContext  # noqa: E402
from zhsgo.util import AttrDict  # noqa: E402


def _force_utf8() -> None:
    """Windows 上 stdout 可能是 cp1252，打印中文会 UnicodeEncodeError。

    本地开发机通常是 UTF-8 所以看不出来，但 GitHub Actions 的
    windows-latest 就是 cp1252 —— 这个函数是那次 CI 失败的产物。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8()

RESULTS: List[tuple[bool, str]] = []


def check(cond: bool, msg: str) -> None:
    RESULTS.append((bool(cond), msg))
    print(("  [ok]  " if cond else "  [!!]  ") + msg)


def section(title: str) -> None:
    print(f"\n== {title} ==")


# ============================================================== crypto

def test_crypto() -> None:
    section("crypto")
    for name, key in (("HOME", HOME_KEY), ("VIDEO", VIDEO_KEY), ("QA", QA_KEY),
                      ("AI", AI_KEY), ("EXAM", EXAM_KEY)):
        c = AesCbc(key)
        for text in ("", "a", "x" * 15, "x" * 16, "中文测试" * 33, '{"a":1}'):
            check(c.decrypt(c.encrypt(text)) == text, f"{name} AES 往返：len={len(text)}")
            break
        plain = json.dumps({"courseId": "1839576198548688896", "classId": 4239, "t": 1729175218000})
        check(c.decrypt(c.encrypt(plain)) == plain, f"{name} AES 往返：真实报文")

    payload = [1919, 42, 300, 1700000000000, "abc123def456"]
    ev = get_ev(payload)
    check(rev_ev(ev) == ";".join(map(str, payload)), f"ev 编解码往返: {ev[:24]}…")
    check(get_ev([1, 2, 3]) == get_ev([1, 2, 3]), "ev 编码确定性")
    check(get_ev([1, 2, 3], key="zhihuishu") != get_ev([1, 2, 3]), "换密钥输出不同")

    p = {"uuid": "abc123", "courseId": "1919", "fileId": "42", "studyTotalTime": "30",
         "startDate": "1700000000000", "endDate": "1700000030000",
         "endWatchTime": "30", "startWatchTime": "0"}
    s1, s2 = hike_sign(p), hike_sign(dict(p))
    check(s1 == s2 and len(s1) == 32, f"hike 签名确定性: {s1}")
    changed = dict(p, fileId="43")
    check(hike_sign(changed) != s1, "改任一字段签名随之变化")
    check(hike_sign({"uuid": "a"}) == hike_sign({"uuid": "a"}), "缺字段时按空串补齐")


# ============================================================== fingerprint

def test_fingerprint() -> None:
    section("fingerprint")
    for major in (100, 101, 116, 120, 128, 131):
        fp = Fingerprint(chrome_major=major, platform="Windows")
        ua, ch = fp.user_agent, fp.sec_ch_ua
        check(f"Chrome/{major}." in ua and f'"{major}"' in ch,
              f"Chrome {major}: UA 与 Client Hints 版本一致")
    fp = Fingerprint(chrome_major=126, platform="macOS")
    h = fp.headers("form")
    check(h["Accept-Language"].startswith("zh-CN"), "Accept-Language 是 zh-CN")
    check("Content-Type" in h, "表单请求带 Content-Type")
    check(h["sec-ch-ua-platform"] == '"macOS"', "platform 与 UA 一致")
    h2 = fp.apply_referer(dict(h), "https://studyservice-api.zhihuishu.com/x", "POST")
    check(h2["Referer"] == "https://studyh5.zhihuishu.com/", f"共享课 Referer: {h2['Referer']}")
    check(h2["Origin"] == "https://studyh5.zhihuishu.com", "POST 带 Origin")
    h3 = fp.apply_referer(dict(h), "https://hike-teaching.zhihuishu.com/x", "GET")
    check("Origin" not in h3, "GET 不带 Origin")
    check(sec_ch_ua(120).startswith('"Not_A Brand"'), "Chrome>=120 品牌串正确")


# ============================================================== pacer

def test_pacer() -> None:
    section("pacer")
    clock = FakeClock()
    p = Pacer(PacerConfig(), clock)

    speeds = [p.speed(444) for _ in range(500)]
    check(max(speeds) <= 1.5 + 1e-9, f"444x 被夹到 {max(speeds):.4f}x")
    check(min(speeds) >= 1.0, "速度不会低于 1.0x")
    check(len(set(round(s, 6) for s in speeds)) > 400, "速度带真实播放器抖动")
    check(p.clamp_warning(444) is not None, "超高倍速会产生告警")
    check(p.clamp_warning(1.2) is None, "合法倍速不告警")

    gaps = [p.next_report_interval() for _ in range(4000)]
    check(len(set(round(g, 4) for g in gaps)) > 3500, "上报间隔是连续随机值")
    mean = sum(gaps) / len(gaps)
    check(20 < mean < 90, f"上报间隔均值合理 ({mean:.1f}s)")
    check(max(gaps) > 60, f"存在'人离开'的长间隔 ({max(gaps):.0f}s)")

    ts = [p.ts_ms() for _ in range(400)]
    ms = [t % 1000 for t in ts]
    zero_ratio = sum(1 for m in ms if m == 0) / len(ms)
    check(zero_ratio < 0.2,
          f"毫秒位为 0 的比例 {zero_ratio * 100:.1f}%（原实现恒为 100%）")
    check(len(set(ms)) > 100, f"毫秒位是分散的（{len(set(ms))} 个不同值）")
    check(all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)), "时间戳严格单调递增")
    check(len(set(ts)) == len(ts), "时间戳无重复")

    pauses = [p.roll_pause() for _ in range(200000)]
    hits = [x for x in pauses if x > 0]
    rate = len(hits) / len(pauses)
    check(0.001 < rate < 0.006, f"微暂停触发率 {rate * 100:.2f}%/s")
    check(len(set(hits)) > 30, f"暂停时长随机（{len(set(hits))} 种）")

    # 关掉整形后应退化成原行为（用于对照）
    p2 = Pacer(PacerConfig(enabled=False), clock)
    check(p2.next_report_interval() == 30.0, "enabled=false 时退回固定 30s（对照）")
    check(p2.ts_ms() % 1000 == 0, "enabled=false 时时间戳 *000（对照）")


# ============================================================== watchpoint

def test_watchpoint() -> None:
    section("watchpoint")
    wp = WatchPoint(interval=2, init=0)
    wp.add(10)
    b1 = wp.take()
    check(b1.startswith("0,1,"), f"首批带起点: {b1}")
    wp.add(22)
    b2 = wp.take()
    check(not b2.startswith("0,1,"), f"后续批次不再回头重报 0,1: {b2}")
    v1 = [int(x) for x in b1.split(",")]
    v2 = [int(x) for x in b2.split(",")]
    check(v1 == sorted(v1) and v2 == sorted(v2), "批次内单调递增")
    check(v2[0] >= v1[-1], f"跨批次单调推进 {v1[-1]} → {v2[0]}")

    wp.add(40)
    b3 = wp.take()
    v3 = [int(x) for x in b3.split(",")]
    check(v3[0] >= v2[-1], "第三批继续向前")

    # 对照：原实现在每次 reset 后都会重新塞 [0,1]
    old = [0, 1]
    for _ in range(3):
        old = [0, 1] + [int(t // 5 + 2) for t in range(3, 31, 2)]
    check(old[:2] == [0, 1], "原实现每批都以 0,1 开头（对照）")

    check(WatchPoint.encode(0) == 2 and WatchPoint.encode(5) == 3, "gen(t)=t//5+2 与前端一致")


# ============================================================== budget

def test_budget() -> None:
    section("budget")
    clock = FakeClock()
    state: Dict[str, Any] = {}
    cfg = BudgetConfig(state_file="", session_minutes=(60, 60), rest_minutes=(10, 10),
                       daily_minutes=200, daily_sessions=2)
    b = Budget(cfg, clock, state)

    check(b.before_video("c1") == 0.0, "首次调用直接开始")
    check(b.q["sessions"] == 1, "会话计数 +1")
    b.tick(1800, "c1")
    clock.advance(3600)          # 真实时钟靠 sleep 推进，这里手动推
    check(abs(b.daily_seconds() - 1800) < 1e-6, "tick 累加正确")
    check(abs(b.before_video("c1") - 600) < 1e-6, "满 60 分钟后返回 600s 休息")
    check(b.q.get("session_started") is None, "休息后会话计时清零")

    b.tick(300, "c1")
    b.before_video("c1")
    check(b.q["sessions"] == 2, "第二次会话计数")
    raised = None
    try:
        b.q["sessions"] = 2
        b._session_started = None
        b.before_video("c1")
    except BudgetExhausted as e:
        raised = e
    check(raised is not None, f"超过单日会话数抛 BudgetExhausted: {raised}")

    # 单课时限
    b2 = Budget(BudgetConfig(state_file="", per_course_minutes=30, daily_minutes=1000,
                             daily_sessions=99), clock, {})
    b2.before_video("c9")
    b2.tick(1900, "c9")
    hit = None
    try:
        b2.before_video("c9")
    except BudgetExhausted as e:
        hit = e
    check(hit is not None, f"单课时限生效: {hit}")

    # 跨天重置
    state3: Dict[str, Any] = {"budget": {"date": "2000-01-01", "seconds": 99999.0, "sessions": 9}}
    b3 = Budget(BudgetConfig(state_file=""), clock, state3)
    check(b3.daily_seconds() == 0.0, "跨天自动清零")
    check(b3.q["date"] != "2000-01-01", "配额日期已更新")


# ============================================================== guard

class FakeRelay:
    def __init__(self, succeed: bool = True, times: int = 1):
        self.succeed = succeed
        self.times = times
        self.calls = 0

    def unlock(self, http, rac_id):
        self.calls += 1
        return self.succeed and self.calls <= self.times


class FakeResp(AttrDict):
    pass


def test_guard() -> None:
    section("guard")
    clock = FakeClock()

    # 1) 一次过检就恢复
    relay = FakeRelay(True, 1)
    g = Guard(GuardConfig(retry_after_unlock=3), relay, clock)
    state = {"n": 0}

    def retry():
        state["n"] += 1
        return FakeResp({"code": 0, "message": "OK"}, default=None)

    def first():
        return FakeResp({"code": -12, "message": "captcha"}, default=None)

    ret = g.call(first, retry, context="上报进度", ok_code=0)
    check(ret.code == 0, "过检后恢复成功")
    check(relay.calls == 1, f"中继调用 1 次（实际 {relay.calls}）")
    check(g.stats.recovered == 1, "统计里记录为已恢复")
    check(clock.total_slept >= 3.0, f"过检后有等待让风控生效 ({clock.total_slept:.1f}s)")

    # 2) 一直返回 -12 → 抛 CaptchaRequired
    relay2 = FakeRelay(True, 99)
    g2 = Guard(GuardConfig(retry_after_unlock=2), relay2, clock)
    err = None
    try:
        g2.call(first, first, context="x", ok_code=0)
    except CaptchaRequired as e:
        err = e
    check(err is not None, f"始终 -12 时抛 CaptchaRequired: {err}")
    check(g2.stats.failed == 1, "统计里记录为失败")

    # 3) 中继本身失败 → 立即停止重试
    relay3 = FakeRelay(False, 0)
    g3 = Guard(GuardConfig(retry_after_unlock=5), relay3, clock)
    err3 = None
    try:
        g3.call(first, first, context="y", ok_code=0)
    except CaptchaRequired:
        err3 = True
    check(err3 and relay3.calls == 1, "中继失败时只试 1 次就放弃")

    # 4) 非 -12 的错误码原样返回，不触发中继
    relay4 = FakeRelay(True, 99)
    g4 = Guard(GuardConfig(), relay4, clock)
    other = FakeResp({"code": 1001, "message": "业务错误"}, default=None)
    out = g4.call(lambda: other, retry, context="z", ok_code=0)
    check(out.code == 1001 and relay4.calls == 0, "非风控错误码不唤中继")

    # 5) 触发次数上限
    relay5 = FakeRelay(True, 999)
    g5 = Guard(GuardConfig(max_captcha_events=2, retry_after_unlock=1), relay5, clock)
    from zhsgo.errors import RiskLocked
    locked = None
    for _ in range(4):
        try:
            g5.call(first, first, context="loop", ok_code=0)
        except (CaptchaRequired, RiskLocked) as e:
            locked = e
            if isinstance(e, RiskLocked):
                break
    check(isinstance(locked, RiskLocked), f"超过触发上限后抛 RiskLocked: {type(locked).__name__}")


# ============================================================== 学习循环

class FakeHttp:
    def __init__(self, clock):
        self.clock = clock
        self.cookies = _FakeJar()

    def get(self, *a, **k):
        return AttrDict({}, default=None)

    def raw_get(self, url, *a, **k):
        return _FakeResp()

    def post(self, *a, **k):
        return AttrDict({}, default=None)


class _FakeJar(dict):
    def copy(self):
        return _FakeJar(self)


class _FakeResp:
    text = "#EXTM3U\n#EXTINF:10,\nseg1.ts\n"


class FakeZhidao:
    """记录每次上报的虚拟时刻、进度和 watching point。"""

    def __init__(self, clock):
        self.clock = clock
        self.reports: List[Dict[str, Any]] = []
        self.quiz_subs: List[Any] = []

    def learning_token(self, note):
        return "dG9rZW4="

    def prelearning_note(self, *a, **k):
        return AttrDict({}, default=None)

    def pointer_info(self, *a, **k):
        return AttrDict({"questionPoint": None}, default=None)

    def three_dim_ware(self, *a, **k):
        return AttrDict({}, default=None)

    def report_progress(self, rac, video, course, played, last_submit, wp, token, initial=False):
        self.reports.append({
            "at": self.clock.now(), "played": played, "delta": played - last_submit,
            "wp": wp, "initial": initial,
        })
        return AttrDict({}, default=None)

    def popup_exam(self, *a, **k):
        return AttrDict({"lessonTestQuestionUseInterfaceDtos": []}, default=None)

    def save_popup_answer(self, *a, **k):
        self.quiz_subs.append(a)
        return AttrDict({}, default=None)


class FakeHike:
    def __init__(self, clock, total=120):
        self.clock = clock
        self.saves: List[Dict[str, Any]] = []
        self.total = total

    def view_file(self, course_id, file_id):
        return AttrDict({"dataId": "d1", "totalTime": self.total, "name": "f"}, default=None)

    def save_record(self, course_id, file_id, played, prev, start):
        self.saves.append({"at": self.clock.now(), "played": played,
                           "delta": played - prev, "start": start})
        return played


@dataclass
class FakeApp:
    cfg: Config
    clock: FakeClock
    pacer: Pacer
    budget: Budget
    zhidao: Any
    hike: Any
    http: Any
    guard: Any


def make_app(clock: FakeClock, **overrides) -> FakeApp:
    raw = {
        "state_file": os.path.join(HERE, "tests", "_tmp_state.json"),
        "pacer": {"report_interval": [22, 47]},
        "budget": {"enabled": True, "state_file": "", "session_minutes": [999, 999],
                   "rest_minutes": [0, 0], "daily_minutes": 10000, "daily_sessions": 99},
        "study": {"tree_view": False, "progress_view": False, "initial_report": False,
                  "prime_video": False, "quiz_delay": [1, 1], "inter_video_rest": [0, 0]},
        "relay": {"enabled": False},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(raw.get(k), dict):
            raw[k].update(v)
        else:
            raw[k] = v
    cfg = Config.from_dict(raw, HERE)
    pacer = Pacer(cfg.pacer, clock)
    budget = Budget(cfg.budget, clock, {})
    return FakeApp(cfg=cfg, clock=clock, pacer=pacer, budget=budget,
                   zhidao=FakeZhidao(clock), hike=FakeHike(clock), http=FakeHttp(clock),
                   guard=Guard(GuardConfig(), None, clock))


def make_video(vid="v1", secs=300.0, played=0.0, state=0) -> AttrDict:
    return AttrDict({
        "videoId": vid, "id": 11, "lessonId": 22, "chapterId": 33,
        "name": f"视频{vid}", "videoSec": secs, "studyTotalTime": played,
        "watchState": state,
    }, default=None)


def test_study_loop() -> None:
    section("学习循环（共享课）")
    clock = FakeClock()
    app = make_app(clock)
    runner = StudyRunner(app)
    ctx = ZhidaoContext(
        rac_id="rc1",
        course=AttrDict({"recruitId": 7, "courseInfo": {"courseId": 99}}, default=None),
        chapters=AttrDict({}, default=None), videos={}, course_id=99, recruit_id=7,
    )
    video = make_video(secs=300.0)
    runner.run_zhidao_video(ctx, video)

    reports = app.zhidao.reports
    check(len(reports) >= 4, f"300 秒视频产生 {len(reports)} 次上报")
    gaps = [round(reports[i + 1]["at"] - reports[i]["at"], 2) for i in range(len(reports) - 1)]
    check(len(set(gaps)) >= max(2, len(gaps) - 1), f"上报间隔互不相同: {gaps}")
    check(all(g >= 2.0 for g in gaps), f"最短间隔 {min(gaps)}s")
    check(all(abs(g - 30.0) > 0.01 for g in gaps), "没有任何一次恰好落在 30.0s（对照原实现）")
    check(all(not r["wp"].startswith("0,1") for r in reports[1:]), "除首批外观看点不回头")

    # 进度一致性：ΣplayTimes 应等于最终播放进度
    total_delta = sum(r["delta"] for r in reports)
    check(abs(total_delta - video["studyTotalTime"]) < 2.0,
          f"ΣplayTimes({total_delta:.1f}) ≈ 最终进度({video['studyTotalTime']:.1f})")

    check(video["watchState"] == 1, "完成后标记 watchState=1")
    elapsed = clock.total_slept
    # end_time = 300 * 0.91 = 273；1.25x 走完约需 218s，加上暂停与视频间休息
    check(190 < elapsed < 500, f"273s 目标进度用了 {elapsed:.0f}s 虚拟时间")


def test_study_loop_pause_reports() -> None:
    section("学习循环（暂停行为）")
    clock = FakeClock()
    app = make_app(clock, pacer={"pause_chance": 0.0, "pause_seconds": [100, 100]})

    # 第 5 次判定时触发一次 100 秒暂停，其余不暂停 —— 确定性验证
    calls = {"n": 0}

    def roll():
        calls["n"] += 1
        return 100.0 if calls["n"] == 5 else 0.0

    app.pacer.roll_pause = roll

    runner = StudyRunner(app)
    ctx = ZhidaoContext(rac_id="rc2",
                        course=AttrDict({"recruitId": 7, "courseInfo": {"courseId": 99}}, default=None),
                        chapters=AttrDict({}, default=None), videos={}, course_id=99, recruit_id=7)
    video = make_video("v2", secs=400.0)
    runner.run_zhidao_video(ctx, video)

    reports = app.zhidao.reports
    check(calls["n"] >= 1, f"暂停判定被调用 {calls['n']} 次")
    gaps = [round(reports[i + 1]["at"] - reports[i]["at"], 2) for i in range(len(reports) - 1)]

    # 暂停期间 played 不再推进 → 会出现连续两次上报进度完全相同
    frozen = [i for i in range(len(reports) - 1)
              if abs(reports[i + 1]["played"] - reports[i]["played"]) < 1e-6]
    check(len(frozen) >= 1,
          f"暂停期间仍按节拍上报（进度冻结的相邻上报 {len(frozen)} 对）")

    check(len(reports) >= 4, f"暂停没有打断整体节拍（共 {len(reports)} 次上报）")
    check(all(abs(g - 30.0) > 0.01 for g in gaps), "没有固定 30s 间隔")


def test_hike_loop() -> None:
    section("学习循环（校内课）")
    from zhsgo.runner.study import HikeContext

    clock = FakeClock()
    app = make_app(clock)
    runner = StudyRunner(app)
    app.hike.menu_tree = lambda cid: []
    ctx = HikeContext(course_id="1919", root=[])
    runner.run_hike_video(ctx, "f1", 0.0)

    saves = app.hike.saves
    check(len(saves) >= 2, f"120 秒视频产生 {len(saves)} 次上报")
    gaps = [round(saves[i + 1]["at"] - saves[i]["at"], 2) for i in range(len(saves) - 1)]
    if gaps:
        check(len(set(gaps)) >= max(1, len(gaps) - 1), f"间隔互不相同: {gaps}")
        check(all(abs(g - 30.0) > 0.01 for g in gaps), "没有固定 30s 间隔")
    check(saves[-1]["played"] >= 120 * 0.91 - 1, f"到达完成阈值 ({saves[-1]['played']:.0f})")
    # 服务端返回原地不动时循环也必须能退出（原实现 `played = ret` 会死循环）
    check(clock.total_slept < 700, f"循环正常退出（{clock.total_slept:.0f}s 虚拟时间）")


def test_budget_interrupts_loop() -> None:
    section("配额在循环中生效")
    clock = FakeClock()
    app = make_app(clock, budget={"daily_minutes": 0.05, "state_file": ""})
    runner = StudyRunner(app)
    ctx = ZhidaoContext(rac_id="rc3",
                        course=AttrDict({"recruitId": 7, "courseInfo": {"courseId": 99}}, default=None),
                        chapters=AttrDict({}, default=None), videos={}, course_id=99, recruit_id=7)
    hit = None
    try:
        runner.run_zhidao_video(ctx, make_video("v3", secs=600.0))
    except BudgetExhausted as e:
        hit = e
    check(hit is not None, f"单日上限在循环内触发并冒泡: {hit}")


# ============================================================== 答案解析

def test_answer_parsing() -> None:
    section("答案解析")
    text = (
        "根据教材第三章……\n\n"
        "```answer\n"
        '[{"id": 652308395, "content": "<p>选项A</p>"}]\n'
        "```\n\n"
        "依据：……"
    )
    ids = Answerer.parse(text)
    check(ids == [652308395], f"标准 answer 块解析: {ids}")

    multi = '```answer\n[{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]\n```'
    check(Answerer.parse(multi) == [1, 2], "多选解析")

    single_quoted = "```answer\n[{'id': 7, 'content': 'a'}]\n```"
    check(Answerer.parse(single_quoted) == [7], "单引号 fallback（ast.literal_eval）")

    for bad in ("没有代码块", "```answer\n不是列表\n```", "```answer\n[1,2]\n```"):
        ok = False
        try:
            Answerer.parse(bad)
        except Exception:
            ok = True
        check(ok, f"非法输入被拒绝: {bad[:18]!r}")

    # 无后端时回退随机，不抛异常
    a = Answerer(None)
    res = a.answer(1, "q", [{"id": 1, "content": "x"}, {"id": 2, "content": "y"}])
    check(res.source == "random" and len(res.ids) == 1, f"无后端时随机作答: {res.source}")
    single = a.answer(1, "q", [{"id": 9, "content": "唯一"}])
    check(single.source == "single-option" and single.ids == [9], "单选项直接命中")


# ============================================================== 配置

def test_config() -> None:
    section("配置")
    cfg = Config.from_dict({
        "state_file": "./state/s.json",
        "pacer": {"report_interval": [25, 60], "max_speed": 1.4},
        "budget": {"daily_minutes": 200},
        "ai": {"enabled": True, "backend": "openai",
               "openai": {"api_key": "sk-x", "model": "m"},
               "context": {"course_name": "测试课"}},
        "unknown_key_should_be_ignored": 123,
    }, HERE)
    check(cfg.pacer.report_interval == (25.0, 60.0), f"tuple 字段转换: {cfg.pacer.report_interval}")
    check(cfg.pacer.max_speed == 1.4, "顶层字段覆盖")
    check(cfg.budget.daily_minutes == 200 and cfg.study.end_threshold == 0.91,
          "未覆盖的字段保留默认值")
    check(cfg.ai.openai.api_key == "sk-x" and cfg.ai.openai.model == "m",
          "嵌套 dataclass 解析")
    check(cfg.ai.context.course_name == "测试课", "AnswerContext 解析")
    check(os.path.isabs(cfg.state_file), f"相对路径已绝对化: {cfg.state_file}")

    bad = Config.from_dict({"pacer": {"max_speed": 8}, "budget": {"daily_minutes": 1000},
                            "pacer_typo": {}}, HERE)
    problems = bad.validate()
    check(any("1.5x" in p for p in problems), f"检出超速配置: {problems}")

    example = os.path.join(HERE, "config.example.yaml")
    if os.path.isfile(example):
        cfg2 = Config.load(example)
        check(cfg2.pacer.max_speed <= 1.5, "示例配置通过速度自检")
        errs = [p for p in cfg2.validate() if "未安装" not in p]
        check(not errs, f"示例配置无硬性问题: {errs}")


# ============================================================== main

def main() -> int:
    tests = [
        test_config, test_crypto, test_fingerprint, test_pacer, test_watchpoint,
        test_budget, test_guard, test_study_loop, test_study_loop_pause_reports,
        test_hike_loop, test_budget_interrupts_loop, test_answer_parsing,
    ]
    for i, fn in enumerate(tests):
        # 节拍本身是随机的，但测试必须可复现 —— 每个用例用独立种子，
        # 既能固定结果，又不会让不同用例吃到同一段随机序列
        random.seed(20240101 + i * 7919)
        try:
            fn()
        except Exception:
            print(f"\n!! {fn.__name__} 抛异常:")
            traceback.print_exc()
            RESULTS.append((False, f"{fn.__name__} 崩溃"))

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = [(ok, m) for ok, m in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"通过 {passed}/{len(RESULTS)}")
    if failed:
        print("失败项：")
        for _, m in failed:
            print(f"  - {m}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
