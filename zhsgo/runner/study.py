"""学习编排 —— 全部节拍、配额、风控恢复的汇合点。

对照原实现（fucker.py 的 `fuckZhidaoVideo` / `fuckHikeVideo`），这里的结构性改动：

  1. 上报间隔不再写死 30 秒，由 `Pacer.next_report_interval()` 逐次抽取；
  2. 时间戳不再就地 `int(time.time())*1000`，统一走 `Pacer.ts_ms()`；
  3. 暂停时**仍然按节拍上报**（playTimes≈0），而不是只在暂停瞬间补一枪；
  4. 观看点每批不回头重报 0,1；
  5. 每个视频开始前过一遍 `Budget`（会话时长 / 单日总量 / 单课时限）；
  6. 所有 sleep 走 `Clock`，所以整条循环可以在测试里用假时钟秒跑完。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..app import App
from ..errors import BudgetExhausted, CaptchaRequired, TimeLimitExceeded, ZhsError
from ..logger import get as log
from ..net import endpoints as ep
from ..risk import WatchPoint
from ..util import AttrDict, progress_bar, shorten


@dataclass
class ZhidaoContext:
    rac_id: str
    course: AttrDict
    chapters: AttrDict
    videos: Dict[str, AttrDict]
    course_id: Any
    recruit_id: Any
    fucked_time: float = 0.0


@dataclass
class HikeContext:
    course_id: Any
    root: List[AttrDict] = field(default_factory=list)
    fucked_time: float = 0.0


class StudyRunner:
    def __init__(self, app: App):
        self.app = app
        self.cfg = app.cfg
        self.scfg = app.cfg.study
        self.clock = app.clock
        self.pacer = app.pacer
        self.budget = app.budget
        self.zhidao = app.zhidao
        self.hike = app.hike
        self.http = app.http
        self._zhidao_ctx: Dict[str, ZhidaoContext] = {}
        self._hike_ctx: Dict[str, HikeContext] = {}

    # ================================================================== 分派

    def run_course(self, course_id: str) -> None:
        cid = str(course_id)
        if any(ch.isalpha() for ch in cid):
            self.run_zhidao_course(cid)
        else:
            self.run_hike_course(cid)

    def list_courses(self) -> List[dict]:
        out: List[dict] = []
        try:
            for c in self.zhidao.share_course_list():
                out.append({
                    "type": "zhidao",
                    "name": c.get("courseName") or c.get("courseInfo", {}).get("name", ""),
                    "id": c.get("secret"),
                })
        except ZhsError as e:
            log().error(f"拉取共享课列表失败: {e}")
        try:
            for c in self.hike.course_list():
                out.append({
                    "type": "hike",
                    "name": c.get("courseName", ""),
                    "id": str(c.get("courseId")),
                })
        except ZhsError as e:
            log().error(f"拉取校内课列表失败: {e}")
        return out

    def run_all(self) -> None:
        for c in self.list_courses():
            try:
                self.run_course(c["id"])
            except BudgetExhausted:
                raise
            except Exception as e:
                log().error(f"课程 {c['name']}({c['id']}) 处理失败: {e}")

    # ================================================================== 共享课

    def zhidao_context(self, rac_id: str, force: bool = False) -> ZhidaoContext:
        if rac_id in self._zhidao_ctx and not force:
            return self._zhidao_ctx[rac_id]

        log().info(f"拉取共享课上下文 {rac_id}")
        self.zhidao.cross_site_login(rac_id)
        course = self.zhidao.course_info(rac_id)
        chapters = self.zhidao.video_list(rac_id)
        course_id = chapters.get("courseId")
        recruit_id = course.get("recruitId")

        lesson_ids: List[Any] = []
        videos: Dict[str, AttrDict] = {}
        for chapter in chapters.get("videoChapterDtos") or []:
            for lesson in chapter.get("videoLessons") or []:
                lesson_ids.append(lesson.get("id"))
                if "videoId" in lesson:
                    # 单视频课时：把它自己包成一个 smallLesson
                    single = lesson.copy()
                    single.lessonId = lesson.get("id")
                    single.id = 0
                    lesson["videoSmallLessons"] = [single]
                for v in lesson.get("videoSmallLessons") or []:
                    v["chapterId"] = chapter.get("id")
                    videos[str(v.get("videoId"))] = v

        states: AttrDict = self.zhidao.study_state(
            lesson_ids, [v.get("id") for v in videos.values() if v.get("id")], recruit_id)
        lv = states.get("lv") or {}
        by_lesson = states.get("lesson") or {}
        for v in videos.values():
            st = lv.get(str(v.get("id"))) or by_lesson.get(str(v.get("lessonId"))) or {}
            v["watchState"] = st.get("watchState")
            v["studyTotalTime"] = st.get("studyTotalTime") or 0

        ctx = ZhidaoContext(rac_id=rac_id, course=course, chapters=chapters,
                            videos=videos, course_id=course_id, recruit_id=recruit_id)
        self._zhidao_ctx[rac_id] = ctx
        log().info(f"{len(lesson_ids)} 个课时 / {len(videos)} 个视频")
        return ctx

    def run_zhidao_course(self, rac_id: str) -> None:
        ctx = self.zhidao_context(rac_id)
        name = ctx.course.get("courseInfo", {}).get("name") or rac_id
        log().info(f"开始共享课：{name}")
        chapters = ctx.chapters.get("videoChapterDtos") or []
        for chapter in chapters:
            self._tree_print(1, f"章节 {chapter.get('name')}")
            for lesson in chapter.get("videoLessons") or []:
                self._tree_print(2, f"课时 {lesson.get('name')}")
                for video in lesson.get("videoSmallLessons") or []:
                    self._tree_print(3, f"视频 {video.get('name')}")
                    try:
                        self.run_zhidao_video(ctx, video)
                    except TimeLimitExceeded as e:
                        log().warning(f"本课时限用尽，跳过剩余视频: {e}")
                        return
                    except BudgetExhausted:
                        raise
                    except CaptchaRequired as e:
                        log().error(f"风控未能解除，本课程中断: {e}")
                        return
                    except Exception as e:
                        log().error(f"视频 {video.get('videoId')} 处理失败: {e}")
        log().info(f"共享课完成：{name}")

    # -------------------------------------------------------------- 单视频

    def run_zhidao_video(self, ctx: ZhidaoContext, video: AttrDict) -> None:
        rac = ctx.rac_id
        vid = str(video.get("videoId"))
        total_sec = float(video.get("videoSec") or 0)
        played = float(video.get("studyTotalTime") or 0)

        if video.get("watchState") == 1 and self.scfg.end_threshold <= 1.0:
            log().debug(f"跳过已完成视频 {vid}")
            return

        rest = self.budget.before_video(rac)
        if rest > 0:
            log().warning(f"会话休息 {rest / 60:.0f} 分钟")
            self.clock.sleep(rest)

        token = self.zhidao.learning_token(
            self.zhidao.prelearning_note(rac, video, ctx.course_id, ctx.recruit_id))

        questions = self._load_questions(ctx, video, played)

        end_time = max(total_sec * self.scfg.end_threshold, 1.0)
        if questions:
            end_time = max(float(questions[0].get("timeSec") or 0), end_time)
        end_time = min(end_time, self.scfg.max_video_seconds)

        if self.scfg.prime_video:
            self.prime_video(video.get("videoId"))
        self.zhidao.three_dim_ware(rac, video.get("videoId"))

        wp = WatchPoint(interval=2, init=int(played))
        last_submit = played
        since_report = 0.0
        next_report = self.pacer.next_report_interval()
        sample_acc = 0.0
        idle = 0.0
        quiz: Optional[AttrDict] = None
        quiz_delay = 0.0

        warn = self.pacer.clamp_warning(self.scfg.speed)
        if warn:
            log().warning(warn)

        if self.scfg.initial_report:
            wp.add(played)
            wp.add(min(played + 2, end_time))
            self.zhidao.report_progress(rac, video, ctx.course, played, played,
                                        wp.take(), token, initial=True)

        log().info(f"学习中 {shorten(str(video.get('name') or vid), 40)} | "
                   f"{played:.0f}/{total_sec:.0f}s | 目标 {end_time:.0f}s")

        while played < end_time:
            # tick 时长本身带抖动：原实现的裸 sleep(1) 会把上报间隔量化成整数秒，
            # 抹掉本该存在的自然抖动
            tick = self.pacer.tick_seconds()
            self.clock.sleep(tick)
            ctx.fucked_time += tick
            self.budget.tick(tick, rac)
            since_report += tick
            sample_acc += tick

            if idle > 0:
                idle -= tick
            else:
                played = min(played + self.pacer.speed(self.scfg.speed) * tick, end_time)
                pause = self.pacer.roll_pause()
                if pause > 0:
                    idle = pause
                    # 暂停是真前端会发生的上报事件，但不是立刻发一个 1 秒间隔的
                    # 请求（那反而突兀）；隔几秒补一次 playTimes≈0 的报告
                    since_report = 0.0
                    next_report = random.uniform(2.5, 9.0)

            if sample_acc >= 2.0:
                sample_acc = 0.0
                wp.add(played)

            # ---- 弹题
            if quiz is None and quiz_delay <= 0 and questions:
                nxt = questions[-1]
                if played >= float(nxt.get("timeSec") or 0):
                    quiz = self._fetch_quiz(ctx, video, questions.pop())
                    if quiz is not None:
                        quiz_delay = random.uniform(*self.scfg.quiz_delay)
            if quiz is not None:
                if quiz_delay > 0:
                    quiz_delay -= tick
                    idle = max(idle, tick)          # 看题时视频是暂停的
                else:
                    self._submit_quiz(ctx, video, quiz)
                    quiz = None

            # ---- 上报
            if since_report >= next_report or played >= end_time:
                since_report = 0.0
                next_report = self.pacer.next_report_interval()
                wp.add(played)
                self.zhidao.report_progress(rac, video, ctx.course, played,
                                            last_submit, wp.take(), token)
                last_submit = played
                self.budget.save()

            if self.scfg.progress_view:
                prefix = "暂停中" if idle > 0 else f"观看 {vid}"
                if quiz is not None:
                    prefix = "答题中"
                progress_bar(played, end_time, prefix=prefix, suffix="完成")

        if self.scfg.progress_view:
            progress_bar(end_time, end_time, prefix=f"完成 {vid}", suffix="")

        self.clock.sleep(random.uniform(0.5, 2.0))
        # 更新本地进度，避免同一进程内重复处理时重刷
        video["studyTotalTime"] = max(played, end_time)
        video["watchState"] = 1

        rest = self.pacer.rest_between_videos()
        if rest > 0.5:
            log().debug(f"视频间休息 {rest:.0f}s")
            self.clock.sleep(rest)

    # -------------------------------------------------------------- 辅助

    def _load_questions(self, ctx: ZhidaoContext, video: AttrDict,
                        played: float) -> List[AttrDict]:
        try:
            info = self.zhidao.pointer_info(ctx.rac_id, video, ctx.course_id, ctx.recruit_id)
        except ZhsError as e:
            log().warning(f"拉取弹题位置失败: {e}")
            return []
        items = list(info.get("questionPoint") or [])
        if not items:
            return []
        items.sort(key=lambda x: float(x.get("timeSec") or 0), reverse=True)
        while items and float(items[-1].get("timeSec") or 0) <= played:
            items.pop()
        return items

    def _fetch_quiz(self, ctx: ZhidaoContext, video: AttrDict, point: AttrDict) -> Optional[AttrDict]:
        try:
            ret = self.zhidao.popup_exam(ctx.rac_id, video, point.get("questionIds") or [])
            items = ret.get("lessonTestQuestionUseInterfaceDtos") or []
            if not items:
                return None
            return items[0].get("testQuestion")
        except Exception as e:
            log().error(f"拉取弹题内容失败: {e}")
            return None

    def _submit_quiz(self, ctx: ZhidaoContext, video: AttrDict, quiz: AttrDict) -> None:
        options = quiz.get("questionOptions") or []
        ids = [str(o.get("id")) for o in options if str(o.get("result")) == "1"]
        if not ids:
            log().warning(f"弹题 {quiz.get('questionId')} 没有标记正确答案，跳过")
            return
        try:
            self.zhidao.save_popup_answer(ctx.rac_id, video, ctx.course_id,
                                          ctx.recruit_id, quiz.get("questionId"),
                                          ",".join(ids))
            log().debug(f"弹题 {quiz.get('questionId')} 已提交 {ids}")
        except Exception as e:
            log().error(f"提交弹题失败: {e}")

    def prime_video(self, video_id: Any) -> None:
        """拉一次播放地址，并对第一个分片发一个 GET —— 让 CDN 侧留下真实流量痕迹。"""
        try:
            raw = self.http.get(ep.VIDEO_INIT, {
                "jsonpCallBack": "result",
                "videoID": str(video_id),
                "_": self.pacer.ts_ms(),
            })
            lines = ((raw.get("result") or {}).get("lines") or [])
            if not lines:
                return
            url = lines[0].get("lineUrl")
            if not url:
                return
            resp = self.http.raw_get(url)
            text = resp.text[:2000]
            if "#EXTM3U" in text:
                # HLS：再取一个分片
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        base = url.rsplit("/", 1)[0]
                        self.http.raw_get(f"{base}/{line}")
                        break
        except Exception as e:
            log().debug(f"预热视频流失败（不影响学习）: {e}")

    def _tree_print(self, depth: int, text: str) -> None:
        if self.scfg.tree_view:
            print(f"{'  |' * depth}__{text}")

    # ================================================================== 校内课

    def hike_context(self, course_id: str, force: bool = False) -> HikeContext:
        if course_id in self._hike_ctx and not force:
            return self._hike_ctx[course_id]
        root = self.hike.menu_tree(course_id)
        ctx = HikeContext(course_id=course_id, root=root)
        self._hike_ctx[course_id] = ctx
        log().info(f"校内课 {course_id} 顶层章节 {len(root)} 个")
        return ctx

    def run_hike_course(self, course_id: str) -> None:
        ctx = self.hike_context(course_id)
        log().info(f"开始校内课 {course_id}")
        for chapter in ctx.root:
            try:
                self._hike_walk(ctx, chapter, 1)
            except TimeLimitExceeded as e:
                log().warning(f"时限用尽: {e}")
                return
            except BudgetExhausted:
                raise
            except CaptchaRequired as e:
                log().error(f"风控未解除: {e}")
                return
        log().info(f"校内课 {course_id} 完成")

    def _hike_walk(self, ctx: HikeContext, node: AttrDict, depth: int) -> None:
        children = node.get("childList")
        if children:
            self._tree_print(depth, f"章节 {node.get('name')}")
            for child in children:
                self._hike_walk(ctx, child, depth + 1)
            return

        file = node
        self._tree_print(depth, f"文件 {file.get('name')}")
        study_time = float(file.get("studyTime") or 0)
        total_time = float(file.get("totalTime") or 0)
        if total_time > 0 and study_time >= total_time * self.scfg.end_threshold:
            log().debug(f"跳过已完成文件 {file.get('id')}")
            return

        data_type = file.get("dataType")
        try:
            if data_type == 3:
                self.run_hike_video(ctx, file.get("id"), study_time)
            elif data_type is None:
                self._tree_print(depth, "## 未支持的文件类型（可能是测验）")
            else:
                self.hike.view_file(ctx.course_id, file.get("id"))
                self.clock.sleep(random.uniform(1.0, 3.0))
        except BudgetExhausted:
            raise
        except Exception as e:
            log().error(f"处理文件 {file.get('id')} 失败: {e}")

    def run_hike_video(self, ctx: HikeContext, file_id: Any, prev_time: float = 0.0) -> None:
        course_id = ctx.course_id
        rest = self.budget.before_video(str(course_id))
        if rest > 0:
            log().warning(f"会话休息 {rest / 60:.0f} 分钟")
            self.clock.sleep(rest)

        info = self.hike.view_file(course_id, file_id)
        if self.scfg.prime_video:
            self.prime_video(info.get("dataId"))

        total = int(float(info.get("totalTime") or 0))
        end_time = max(total * self.scfg.end_threshold, 1.0)
        start_date = self.pacer.ts_ms()
        played = float(prev_time)
        since_report = 0.0
        next_report = self.pacer.next_report_interval()
        idle = 0.0

        log().info(f"学习中 {shorten(str(info.get('name') or file_id), 40)} | "
                   f"{played:.0f}/{total}s")

        while played < end_time:
            tick = self.pacer.tick_seconds()
            self.clock.sleep(tick)
            ctx.fucked_time += tick
            self.budget.tick(tick, str(course_id))
            since_report += tick

            if idle > 0:
                idle -= tick
            else:
                played = min(played + self.pacer.speed(self.scfg.speed) * tick, end_time)
                idle = self.pacer.roll_pause()

            if played >= end_time or since_report >= next_report:
                ret = self.hike.save_record(course_id, file_id, played, prev_time, start_date)
                # 服务端返回的是它认定的累计时间，比我们自己的大就采纳；
                # 但**绝不把 played 回退** —— 原实现直接 `played = ret`，
                # 一旦服务端返回值原地不动，`while played <= end_time` 就永远成立
                prev_time = ret
                if ret > played:
                    played = min(ret, end_time)
                since_report = 0.0
                next_report = self.pacer.next_report_interval()
                self.budget.save()

            if self.scfg.progress_view:
                progress_bar(played, end_time, prefix=f"观看 {file_id}", suffix="完成")

        self.clock.sleep(random.uniform(0.5, 2.0))
        rest = self.pacer.rest_between_videos()
        if rest > 0.5:
            self.clock.sleep(rest)
