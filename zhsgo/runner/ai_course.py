"""AI 课程编排。

AI 课的进度模型与普通课不同：不按秒累计，而是**按资源打点**。
视频资源才需要上报观看进度，文本/PPT 只要调一次"标记完成"即可。

原实现把所有分支写在一个 250 行的 for 嵌套里，且 `resourceType` /
`resourceDistributeType` 的裸数字散落各处。这里把资源类型收敛成常量，
并把"看视频"和"打标完成"拆成两个方法。
"""
from __future__ import annotations

import os
import random
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ..ai.prompts import AnswerContext
from ..app import App
from ..logger import get as log
from ..util import progress_bar, shorten
from .exam import AiExamRunner, AnswerCache
from .study import StudyRunner

# 资源类型编码（来自前端）
RES_TEXT = (2, 1)
RES_PPT = (1, 4)
RES_VIDEO = (1, 3)
RES_COURSE_VIDEO = (2, 2)

VIDEO_KINDS = (RES_VIDEO, RES_COURSE_VIDEO)
COMPLETE_KINDS = (RES_TEXT, RES_PPT)


class AiCourseRunner:
    def __init__(self, app: App, study: Optional[StudyRunner] = None):
        self.app = app
        self.cfg = app.cfg
        self.scfg = app.cfg.study
        self.ai = app.ai_course
        self.clock = app.clock
        self.pacer = app.pacer
        self.study = study or StudyRunner(app)

        base = os.path.dirname(os.path.abspath(app.cfg.state_file)) or "."
        self.cache_dir = os.path.join(base, "answers")

    # ---------------------------------------------------------------- 入口

    def run(self, course_id: Any, class_id: Any) -> None:
        info = self.ai.knowledge_points(course_id, class_id)
        name = info.get("courseName", str(course_id))
        log().info(f"开始 AI 课程：{name}")

        themes = info.get("cakeThemeList") or []
        for theme in themes:
            theme_name = theme.get("themeName", "")
            self._tree(1, f"主题 {theme_name}")
            for knowledge in theme.get("knowledgeList") or []:
                self._knowledge(course_id, class_id, theme_name, knowledge)

        log().info(f"AI 课程完成：{name}")

    # ---------------------------------------------------------------- 知识点

    def _knowledge(self, course_id: Any, class_id: Any, theme_name: str,
                   knowledge: Any) -> None:
        kid = knowledge.get("knowledgeId")
        kname = knowledge.get("knowledgeName", str(kid))
        progress = float(knowledge.get("studyProgress") or 0)
        self._tree(2, f"知识点 {kname} ({progress:.0f}%)")

        ppts: List[dict] = []

        if progress < 100:
            try:
                resources = self.ai.resources(course_id, class_id, kid)
            except Exception as e:
                log().error(f"知识点 {kname} 资源列表获取失败: {e}")
                return
            items = resources.get("resourceList") or []
            for idx, resource in enumerate(items, 1):
                self.clock.sleep(random.uniform(0.3, 2.0))
                self._resource(course_id, class_id, kid, resource, ppts)
                if self.scfg.progress_view:
                    progress_bar(idx, len(items), prefix="资源", suffix="")
        else:
            # 已完成的也把 PPT 收上来，考试时当参考资料
            try:
                resources = self.ai.resources(course_id, class_id, kid)
                for resource in resources.get("resourceList") or []:
                    self._collect_ppt(resource, ppts)
            except Exception:
                pass
            self._tree(3, "知识点已完成")

        if not self.cfg.ai.skip_exam:
            self._exam_loop(course_id, class_id, kid, kname, theme_name, ppts)

    # ---------------------------------------------------------------- 资源

    def _resource(self, course_id: Any, class_id: Any, kid: Any,
                  resource: Any, ppts: List[dict]) -> None:
        detail = resource.get("resourcesDetail") or {}
        rtype = detail.get("resourcesType")
        rdist = detail.get("resourcesDistributeType")
        rname = detail.get("resourcesName", "")
        kind = (rtype, rdist)
        self._tree(3, f"资源 {shorten(rname, 50)} [{rtype}/{rdist}]")

        if kind in COMPLETE_KINDS:
            self._collect_ppt(resource, ppts)
            try:
                self.ai.complete_resource(course_id, class_id, kid, detail.get("resourcesUid"), 1)
                self._tree(4, "已标记完成")
            except Exception as e:
                log().error(f"标记资源完成失败: {e}")
            return

        if kind in VIDEO_KINDS:
            try:
                self._watch_video(course_id, class_id, detail.get("resourcesFileId"), kid, 1)
                self._tree(4, "视频已完成")
            except Exception as e:
                log().error(f"AI 视频处理失败: {e}")
            return

        # 未知类型：能打标就打标，打不了就跳过
        try:
            self.ai.complete_resource(course_id, class_id, kid, detail.get("resourcesUid"), 1)
            self._tree(4, f"未知类型 [{rtype}/{rdist}]，已尝试标记完成")
        except Exception:
            self._tree(4, f"未知类型 [{rtype}/{rdist}]，跳过")

    @staticmethod
    def _collect_ppt(resource: Any, ppts: List[dict]) -> None:
        detail = resource.get("resourcesDetail") or {}
        if (detail.get("resourcesType"), detail.get("resourcesDistributeType")) == RES_PPT:
            url = detail.get("resourcesUrl")
            if url:
                ppts.append({"name": detail.get("resourcesName", ""), "url": url})

    def _watch_video(self, course_id: Any, class_id: Any, file_id: Any,
                     kid: Any, watch_uid: int = 1, start_at: int = 0) -> None:
        length = self.ai.video_length(course_id, class_id, file_id)
        if self.scfg.prime_video:
            self.study.prime_video(file_id)

        played = int(start_at)
        since_report = 0.0
        next_report = self.pacer.next_report_interval()
        rate = self.pacer.speed(self.scfg.speed)

        while played < length:
            self.clock.sleep(2.0)
            played = min(int(round(played + rate * 2)), length)
            since_report += 2.0

            if since_report >= next_report or played >= length:
                self.ai.report_video(course_id, class_id, file_id, kid, played,
                                     watch_uid=watch_uid)
                since_report = 0.0
                next_report = self.pacer.next_report_interval()

            if self.scfg.progress_view:
                progress_bar(played, length, prefix=f"AI视频 {file_id}", suffix="")

    # ---------------------------------------------------------------- 考试

    def _exam_loop(self, course_id: Any, class_id: Any, kid: Any, kname: str,
                   theme_name: str, ppts: List[dict]) -> None:
        cache = AnswerCache(os.path.join(self.cache_dir, f"{course_id}.json"))
        ai_cfg = self.cfg.ai
        attempts = 0

        while True:
            paper = self.ai.exam_paper(course_id, class_id, kid)
            if not paper or not paper.get("paperId"):
                self._tree(3, "无可用试卷")
                return

            mastery = float(paper.get("masteryScore") or 0)
            if mastery > ai_cfg.target_mastery:
                self._tree(3, f"掌握度已达 {mastery:.0f}，跳过")
                return
            if mastery < ai_cfg.give_up_below and attempts > 4:
                self._tree(3, f"掌握度 {mastery:.0f} 过低且尝试 {attempts} 次，放弃")
                return
            if attempts >= ai_cfg.max_exam_attempts:
                self._tree(3, f"已达最大尝试次数 {attempts}，放弃")
                return

            attempts += 1
            self._tree(3, f"开始考试（第 {attempts} 次，当前掌握度 {mastery:.0f}）")

            context: AnswerContext = replace(
                self.cfg.ai.context, theme=theme_name, knowledge_point=kname)

            runner = AiExamRunner(
                self.app,
                course_id=course_id, knowledge_id=kid,
                exam_test_id=paper.get("examTestId"), paper_id=paper.get("paperId"),
                context=context, cache=cache,
                materials=ppts or None,
                progress=self.scfg.progress_view,
            )
            outcome = runner.run()
            self._tree(4, f"本次成绩 {outcome.describe()}")

            if outcome.success:
                return
            self.clock.sleep(random.uniform(2.0, 6.0))

    # ---------------------------------------------------------------- 输出

    def _tree(self, depth: int, text: str) -> None:
        if self.scfg.tree_view:
            print(f"{'  |' * depth}__{text}")
