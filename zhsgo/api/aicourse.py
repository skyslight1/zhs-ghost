"""AI 课程接口。

AI 课的进度模型和普通课完全不同：不按秒累计，而是**按资源打点**
（看完一个资源 = 该知识点 +1 分）。视频资源才需要上报观看进度。
所以这里的节拍策略也不同：报告间隔固定 2 秒是原项目的做法，
这里改成由 Pacer 决定，并且复用同一套风控恢复。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..crypto import AI_KEY, HOME_KEY
from ..net import endpoints as ep
from ..util import AttrDict
from .zhidao import ZhidaoApi

# 资源类型编码（来自前端）
RES_TEXT = (2, 1)
RES_PPT = (1, 4)
RES_VIDEO = (1, 3)
RES_COURSE_VIDEO = (2, 2)


class AiCourseApi:
    def __init__(self, zhidao: ZhidaoApi):
        self.z = zhidao

    def course_list(self) -> Any:
        ret = self.z.call(ep.AI_COURSE_LIST, {"status": 3},
                          key=HOME_KEY, ok_code=None, context="查询 AI 课列表")
        return ret.get("rt")

    def knowledge_points(self, course_id: int, class_id: int) -> AttrDict:
        ret = self.z.call(ep.AI_COURSE_BASIC, {"courseId": course_id, "classId": class_id},
                          key=AI_KEY, ok_code=200, content_type="json",
                          context="查询 AI 课知识点")
        return ret.data

    def resources(self, course_id: int, class_id: int, knowledge_id: int) -> AttrDict:
        ret = self.z.call(ep.AI_RESOURCE_LIST, {
            "courseId": course_id, "classId": class_id, "knowledgeId": knowledge_id,
        }, key=AI_KEY, ok_code=200, content_type="json", context="查询知识点资源")
        return ret.data

    def complete_resource(self, course_id: int, class_id: int, knowledge_id: int,
                          resources_uid: Any, watch_uid: int = 1) -> AttrDict:
        ret = self.z.call(ep.AI_RESOURCE_COMPLETE, {
            "courseId": course_id, "classId": class_id, "knowledgeId": knowledge_id,
            "resourcesUid": resources_uid, "watchUId": watch_uid,
        }, key=AI_KEY, ok_code=200, content_type="json", context="标记资源完成")
        return ret.data

    def video_length(self, course_id: int, class_id: int, file_id: Any) -> int:
        ret = self.z.call(ep.AI_VIDEO_TIME, {
            "courseId": course_id, "classId": class_id, "videoIdList": [file_id],
        }, key=AI_KEY, ok_code=200, content_type="json", context="查询 AI 视频时长")
        data = ret.data
        if not data:
            raise ValueError(f"无法获取视频时长: fileId={file_id}")
        return int(data[0].time)

    def report_video(self, course_id: int, class_id: int, file_id: Any,
                     knowledge_id: int, last_watch_time: int,
                     study_total_time: int = 10, share_course_id: str = "",
                     node_type: int = 0, watch_uid: int = 1) -> bool:
        try:
            self.z.call(ep.AI_REPORT, {
                "courseId": course_id, "classId": class_id, "fileId": file_id,
                "knowledgeId": knowledge_id, "lastWatchTime": last_watch_time,
                "studyTotalTime": study_total_time, "shareCourseId": share_course_id,
                "nodeType": node_type, "watchUId": watch_uid,
                "dateFormate": self.z.pacer.ts_ms(),
            }, key=AI_KEY, ok_code=200, content_type="json", context="上报 AI 视频进度")
            return True
        except Exception:
            return False

    def exam_paper(self, course_id: int, class_id: int, knowledge_id: int) -> Dict:
        ret = self.z.call(ep.AI_EXAM_PAPER, {
            "scMapId": course_id, "courseId": class_id, "classId": class_id,
            "knowledgeId": knowledge_id,
        }, key=AI_KEY, ok_code=200, content_type="json", context="查询 AI 试卷")
        return ret.data or {}
