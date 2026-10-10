"""AI 课程考试。

原实现把答案缓存、重试、进度条、LLM 调用、结果复核全塞在一个 460 行的
`ExamCtx.startFuck()` 里，且缓存路径是相对进程 cwd 的固定目录。

这里拆开：
  * `AnswerCache` 负责读写（显式路径，可测试）；
  * `AiExamRunner` 负责一次考试的生命周期；
  * 复核逻辑单独成方法 —— 它是**唯一**能把正确答案沉淀进缓存的地方。

复核这一步是关键：第一次靠 AI 猜，交卷后服务端会把每道题的正确选项
（`optionVos[].isCorrect`）返回，抓下来存进缓存，下次同题直接命中。
原项目的 `correct_questions == total` 判定只用来决定要不要重考，
没有把"答对的答案"和"猜对的答案"区分开，导致缓存质量参差。
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..ai.client import Answerer
from ..ai.prompts import AnswerContext
from ..app import App
from ..errors import ZhsError
from ..logger import get as log
from ..util import progress_bar


@dataclass
class ExamOutcome:
    success: bool
    correct: int
    total: int
    submitted: bool = True

    def describe(self) -> str:
        return f"{self.correct}/{self.total}" + ("" if self.submitted else " (未交卷)")


class AnswerCache:
    """按课程存放答案缓存。key 为 `questionId` 或 `questionId_version`。"""

    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f) or {}
        except Exception as e:
            log().warning(f"答案缓存读取失败，忽略: {e}")
            self.data = {}

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log().warning(f"答案缓存写入失败: {e}")

    @staticmethod
    def key(question_id: Any, version: int = 1) -> str:
        return str(question_id) if version in (1, None) else f"{question_id}_{version}"

    def get(self, question_id: Any, version: int = 1) -> Optional[List[str]]:
        item = self.data.get(self.key(question_id, version))
        if not item:
            return None
        raw = item.get("answer") or ""
        if not raw:
            return None
        return raw.split("#@#")

    def put(self, question_id: Any, version: int, question: str, answers: Sequence[Any],
            answer_contents: Sequence[str] = (), raw: Any = None) -> None:
        self.data[self.key(question_id, version)] = {
            "version": version,
            "question": question,
            "answer": "#@#".join(str(a) for a in answers),
            "answer_content": "\n".join(answer_contents),
            "questionDict": raw or {},
        }

    def __len__(self) -> int:
        return len(self.data)


class AiExamRunner:
    def __init__(self, app: App, *, course_id: Any, knowledge_id: Any,
                 exam_test_id: Any, paper_id: Any, context: AnswerContext,
                 cache: AnswerCache, materials: Optional[Sequence[dict]] = None,
                 progress: bool = True):
        self.app = app
        self.exam = app.exam
        self.clock = app.clock
        self.course_id = course_id
        self.knowledge_id = knowledge_id
        self.exam_test_id = exam_test_id
        self.paper_id = paper_id
        self.cache = cache
        self.materials = materials or []
        self.progress = progress
        self.answerer = Answerer(app.backend(), context)

    # ---------------------------------------------------------------- 主流程

    def run(self) -> ExamOutcome:
        start_beat, stop_beat = self.exam.make_heartbeat(self.exam_test_id, self.paper_id)
        started = False
        try:
            self.exam.open(self.exam_test_id, self.paper_id, self.course_id)
            started = True
            start_beat()

            sheet = self.exam.sheet(self.exam_test_id, self.paper_id)
            if not sheet:
                log().warning(f"试卷 {self.exam_test_id} 为空")
                return ExamOutcome(False, 0, 0, submitted=False)

            total = len(sheet)
            for index, item in enumerate(sheet, 1):
                self._answer_one(item)
                if self.progress:
                    progress_bar(index, total, prefix="答题", suffix="")

            self.exam.submit(self.exam_test_id, self.paper_id, self.course_id, self.knowledge_id)
        except ZhsError as e:
            log().error(f"考试 {self.exam_test_id} 失败: {e}")
            return ExamOutcome(False, 0, 0, submitted=False)
        finally:
            if started:
                stop_beat()

        return self._review(sheet)

    # ---------------------------------------------------------------- 单题

    def _answer_one(self, item: Any) -> None:
        qid = item.get("questionId")
        version = int(item.get("version", 1) or 1)

        cached = self.cache.get(qid, version)
        if cached:
            log().debug(f"题目 {qid} 命中缓存")
            self.exam.save_answer(self.course_id, self.exam_test_id, self.paper_id, qid, cached)
            self.clock.sleep(random.uniform(1.0, 2.5))
            return

        q = self.exam.question(self.exam_test_id, self.paper_id, qid, version)
        if not q:
            log().warning(f"题目 {qid} 内容获取失败，跳过")
            return

        choices = [{"id": o.get("id"), "content": o.get("content")}
                   for o in (q.get("optionVos") or [])
                   if "id" in o and "content" in o]
        if not choices:
            log().warning(f"题目 {qid} 没有可用选项，跳过")
            return

        result = self.answerer.answer(int(q.get("questionType") or 1),
                                      q.get("content", ""), choices, self.materials)
        log().debug(f"题目 {qid} 作答来源={result.source} 选项={result.ids}")

        if result.source != "random":
            self.cache.put(qid, version, q.get("content", ""), result.ids, raw=q.snapshot()
                           if hasattr(q, "snapshot") else dict(q))
            self.cache.save()

        self.exam.save_answer(self.course_id, self.exam_test_id, self.paper_id, qid, result.ids)
        # 人答题不是零延迟的
        self.clock.sleep(random.uniform(1.5, 4.0))

    # ---------------------------------------------------------------- 复核

    def _review(self, sheet: Sequence[Any]) -> ExamOutcome:
        total = len(sheet)
        correct = 0
        for item in sheet:
            qid = item.get("questionId")
            version = int(item.get("version", 1) or 1)
            q = self.exam.question(self.exam_test_id, self.paper_id, qid, version)
            if not q:
                continue

            used = q.get("userAnswerVo")
            if used and used[0].get("isCorrect") == 1:
                correct += 1

            # 服务端会把正确选项标出来 —— 这是把"猜对"变成"知道"的唯一机会
            right = [o for o in (q.get("optionVos") or []) if o.get("isCorrect") == 1]
            if right:
                self.cache.put(
                    qid, version,
                    q.get("content", ""),
                    [o.get("id") for o in right],
                    [o.get("content", "") for o in right],
                    raw=q.snapshot() if hasattr(q, "snapshot") else dict(q),
                )
        self.cache.save()

        ok = correct == total and total > 0
        log().info(f"考试 {self.exam_test_id} 复核：{correct}/{total}，缓存 {len(self.cache)} 条")
        return ExamOutcome(ok, correct, total)
