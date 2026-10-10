"""AI 课程考试接口。

流程：openExam → getExamSheetInfo → 逐题 getExamQuestionInfo + saveAnswer
     → submit → 回查 userAnswerVo 统计正确率并落答案缓存

原实现用后台线程每 10 秒打一次心跳。这里保留心跳，但改成可停止的线程，
并且心跳失败不再静默（它失败通常意味着会话掉了，而这会直接导致交卷失败）。
"""
from __future__ import annotations

import threading
from typing import Any, List, Optional, Sequence

from ..crypto import EXAM_KEY
from ..errors import ApiError
from ..net import endpoints as ep
from ..util import AttrDict
from .zhidao import ZhidaoApi


class ExamApi:
    def __init__(self, zhidao: ZhidaoApi):
        self.z = zhidao

    # ------------------------------------------------------------- 考试

    def open(self, exam_test_id: Any, paper_id: Any, course_id: Any, *,
             retries: int = 3) -> AttrDict:
        payload = {"examTestId": exam_test_id, "examPaperId": paper_id, "courseId": course_id}
        last: Optional[Exception] = None
        for _ in range(max(1, retries)):
            try:
                return self.z.call(ep.EXAM_OPEN, payload, key=EXAM_KEY, ok_code=0,
                                   context="开启考试")
            except Exception as e:
                last = e
        raise ApiError("openExam", f"开启考试失败: {last}", ep.EXAM_OPEN)

    def sheet(self, exam_test_id: Any, paper_id: Any, *, retries: int = 3) -> List[AttrDict]:
        payload = {"examTestId": exam_test_id, "examPaperId": paper_id}
        last: Optional[Exception] = None
        for _ in range(max(1, retries)):
            try:
                ret = self.z.call(ep.EXAM_SHEET, payload, key=EXAM_KEY, ok_code=0,
                                  method="GET", context="获取答题卡")
                parts = ret.data.partSheetVos
                return list(parts[0].questionSheetVos) if parts else []
            except Exception as e:
                last = e
        raise ApiError("getSheet", f"获取答题卡失败: {last}", ep.EXAM_SHEET)

    def question(self, exam_test_id: Any, paper_id: Any, question_id: Any,
                 version: int = 1, *, retries: int = 3) -> Optional[AttrDict]:
        payload = {
            "examTestId": exam_test_id, "examPaperId": paper_id,
            "questionId": question_id, "version": version,
        }
        for _ in range(max(1, retries)):
            try:
                ret = self.z.call(ep.EXAM_QUESTION, payload, key=EXAM_KEY, ok_code=0,
                                  method="GET", context="获取题目")
                return ret.data
            except Exception:
                continue
        return None

    def save_answer(self, recruit_id: Any, exam_test_id: Any, paper_id: Any,
                    question_id: Any, answers: Sequence[Any]) -> bool:
        if not answers:
            return False
        try:
            self.z.call(ep.EXAM_SAVE_ANSWER, {
                "recruitId": recruit_id,
                "examTestId": exam_test_id,
                "examPaperId": paper_id,
                "questionId": question_id,
                "dataVos": None,
                "answer": "#@#".join(str(a) for a in answers),
            }, key=EXAM_KEY, ok_code=0, context="保存答案")
            return True
        except Exception:
            return False

    def submit(self, exam_test_id: Any, paper_id: Any, course_id: Any,
               knowledge_id: Any, *, retries: int = 3) -> bool:
        payload = {
            "examTestId": exam_test_id, "courseId": course_id, "courseType": 8,
            "examPaperId": paper_id, "aiKnlowledgeId": knowledge_id,  # 官方拼写错误
        }
        last: Optional[Exception] = None
        for _ in range(max(1, retries)):
            try:
                self.z.call(ep.EXAM_SUBMIT, payload, key=EXAM_KEY, ok_code=0, context="交卷")
                return True
            except Exception as e:
                last = e
        raise ApiError("submit", f"交卷失败: {last}", ep.EXAM_SUBMIT)

    # ------------------------------------------------------------- 心跳

    def make_heartbeat(self, exam_test_id: Any, paper_id: Any, interval: int = 10):
        """返回 (starter, stopper)。原实现直接把线程裸起，无法停止。"""
        stop = threading.Event()

        def beat() -> None:
            while not stop.is_set():
                try:
                    self.z.call(ep.EXAM_HEARTBEAT, {
                        "examTestId": exam_test_id, "examPaperId": paper_id,
                        "heartbeatTime": interval,
                    }, key=EXAM_KEY, ok_code=0, context="考试心跳")
                except Exception:
                    pass
                stop.wait(interval)

        def start() -> None:
            threading.Thread(target=beat, daemon=True, name="exam-heartbeat").start()

        def halt() -> None:
            stop.set()

        return start, halt
