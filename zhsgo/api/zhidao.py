"""共享课（知到 / recruitAndCourseId）接口。

协议总结（来自抓包 + 反混淆前端）：
  * 所有业务参数 JSON 序列化后 AES-CBC 加密，塞进 `secretStr` 字段；
  * 同时明文带一个 `dateFormate` 毫秒时间戳；
  * 密钥按接口分组（HOME / VIDEO / QA / EXAM / AI）；
  * **所有时间戳必须走 `Pacer.ts_ms()`** —— 这是统一出口，别的地方不许自己造
    时间戳（原项目在这里硬编码 `int(time.time())*1000`，毫秒位恒为 000）。
"""
from __future__ import annotations

import json
from base64 import b64encode
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..crypto import AI_KEY, EXAM_KEY, HOME_KEY, QA_KEY, VIDEO_KEY, AesCbc, get_ev
from ..errors import ApiError, CaptchaRequired
from ..net import HttpClient, endpoints as ep
from ..risk import Guard, Pacer
from ..util import AttrDict, hms, wrap


class ZhidaoApi:
    # 上报参数里 `studyStatus` 恒定 0；`uuid + "zhs"` 是前端尾部标记
    UUID_SUFFIX = "zhs"

    def __init__(self, http: HttpClient, guard: Guard, pacer: Pacer,
                 uuid_provider: Callable[[], str]):
        self.http = http
        self.guard = guard
        self.pacer = pacer
        self.uuid_provider = uuid_provider
        self.guard.bind(http)

    # ------------------------------------------------------------- 传输

    def _encode(self, data: Dict[str, Any], key: bytes, encrypt: bool, stamp: bool) -> Dict[str, Any]:
        payload = dict(data)
        if stamp:
            payload["dateFormate"] = self.pacer.ts_ms()
        if encrypt:
            form: Dict[str, Any] = {"secretStr": AesCbc(key).encrypt(json.dumps(payload, ensure_ascii=False))}
        else:
            form = dict(payload)
        if stamp:
            form["dateFormate"] = payload["dateFormate"]
        return form

    def call(self, url: str, data: Dict[str, Any], *, key: bytes = VIDEO_KEY,
             encrypt: bool = True, ok_code: Any = 0, method: str = "POST",
             content_type: str = "form", stamp: bool = True,
             context: str = "", rac_id: Optional[str] = None) -> AttrDict:
        """带风控恢复的请求。每次重发都重新加密（密文含随机 IV）。"""

        def send() -> AttrDict:
            form = self._encode(data, key, encrypt, stamp)
            if method.upper() == "POST":
                return self.http.post(url, form, content_type=content_type)
            return self.http.get(url, form, content_type=content_type)

        ret = send()
        if ok_code is not None and ret.code != ok_code:
            if ret.code == ep.CODE_CAPTCHA:
                ret = self.guard.call(lambda: ret, send,
                                      context=context or url, rac_id=rac_id, ok_code=ok_code)
            if ret.code != ok_code:
                raise ApiError(ret.code, ret.get("message") or json.dumps(
                    {k: v for k, v in ret.items() if k != "data"}, ensure_ascii=False,
                    default=str), url)
        return ret

    # ------------------------------------------------------------- 课程

    def share_course_list(self, page_size: int = 10) -> List[AttrDict]:
        """全部共享课。"""
        out: List[AttrDict] = []
        page = 1
        while True:
            ret = self.call(
                ep.ZHIDAO_SHARE_LIST,
                {"status": 0, "pageNo": page, "pageSize": page_size},
                key=HOME_KEY, ok_code=ep.CODE_OK_HOME, context="查询共享课列表",
            )
            result = ret.result
            result.default = None
            courses = result.courseOpenDtos or []
            out.extend(courses)
            total = int(result.totalCount or 0)
            if not courses or len(out) >= total:
                break
            page += 1
            if page > 200:          # 防御性上限
                break
        return out

    def cross_site_login(self, rac_id: str) -> None:
        """跨站登录：给 studyh5 域建立会话。"""
        self.http.get(ep.ZHIDAO_GOLOGIN, {
            "fromurl": f"https://studyh5.zhihuishu.com/videoStudy.html#/studyVideo?recruitAndCourseId={rac_id}"
        })

    def course_info(self, rac_id: str) -> AttrDict:
        return self.call(ep.ZHIDAO_QUERY_COURSE, {"recruitAndCourseId": rac_id},
                         context="查询课程信息", rac_id=rac_id).data

    def video_list(self, rac_id: str) -> AttrDict:
        return self.call(ep.ZHIDAO_VIDEO_LIST, {"recruitAndCourseId": rac_id},
                         context="查询视频列表", rac_id=rac_id).data

    def study_state(self, lesson_ids: Sequence, video_ids: Sequence, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_STUDY_INFO, {
            "lessonIds": list(lesson_ids),
            "lessonVideoIds": list(video_ids),
            "recruitId": recruit_id,
        }, context="查询学习状态", ok_code=0).data

    def study_read_before(self, course_id: Any, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_STUDY_READ_BEFORE,
                         {"courseId": course_id, "recruitId": recruit_id},
                         ok_code=None).data

    def last_video(self, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_LAST_VIDEO, {"recruitId": recruit_id},
                         context="查询最近观看").data

    # ------------------------------------------------------------- 单视频

    def prelearning_note(self, rac_id: str, video: AttrDict, course_id: Any,
                         recruit_id: Any) -> AttrDict:
        ret = self.call(ep.ZHIDAO_PRELEARNING_NOTE, {
            "ccCourseId": course_id,
            "chapterId": video.chapterId,
            "isApply": 1,
            "lessonId": video.lessonId,
            "lessonVideoId": video.id,
            "recruitId": recruit_id,
            "videoId": video.videoId,
        }, context="获取 learningToken", rac_id=rac_id)
        return ret.data

    @staticmethod
    def learning_token(note: AttrDict) -> str:
        raw = note.studiedLessonDto.id
        return b64encode(str(raw).encode()).decode()

    def pointer_info(self, rac_id: str, video: AttrDict, course_id: Any, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_POINTER_INFO, {
            "lessonId": video.lessonId,
            "lessonVideoId": video.id,
            "recruitId": recruit_id,
            "courseId": course_id,
        }, context="获取弹题位置", rac_id=rac_id).data

    def popup_exam(self, rac_id: str, video: AttrDict, question_ids: Sequence) -> AttrDict:
        return self.call(ep.ZHIDAO_POPUP_EXAM, {
            "lessonId": video.lessonId,
            "lessonVideoId": video.id,
            "questionIds": list(question_ids),
        }, context="拉取弹题", rac_id=rac_id).data

    def save_popup_answer(self, rac_id: str, video: AttrDict, course_id: Any,
                          recruit_id: Any, question_id: Any, answer_ids: str) -> AttrDict:
        return self.call(ep.ZHIDAO_POPUP_SAVE_ANSWER, {
            "courseId": course_id,
            "recruitId": recruit_id,
            "testQuestionId": question_id,
            "isCurrent": "1",       # 前端原样传 1，字段名是 isCorrect 但值是 isCurrent
            "lessonId": video.lessonId,
            "lessonVideoId": video.id,
            "answer": answer_ids,
            "testType": 0,
        }, key=QA_KEY, context="提交弹题答案", rac_id=rac_id).data

    def three_dim_ware(self, rac_id: str, video_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_THREE_DIM, {"videoId": video_id},
                         method="GET", context="三维课件", rac_id=rac_id).data

    # ------------------------------------------------------------- 进度上报

    def report_progress(self, rac_id: str, video: AttrDict, course: AttrDict,
                        played_time: float, last_submit: float, watch_point: str,
                        token_id: str, *, initial: bool = False) -> AttrDict:
        """核心上报接口。字段顺序与前端一致，缺一不可。"""
        uuid = self.uuid_provider()
        total = int(played_time)
        watch_hms = hms(seconds=min(video.videoSec, total))

        if initial:
            # 打开视频时的初始化上报：尾部是裸 uuid，且不带 courseId
            raw_ev = [
                course.recruitId,
                video.chapterId,
                course.courseInfo.courseId,
                video.lessonId,
                watch_hms,
                total,
                video.videoId,
                "0",
                total,
                uuid,
            ]
            data = {
                "ewssw": watch_point,
                "sdsew": get_ev(raw_ev),
                "zwsds": token_id,
            }
        else:
            raw_ev = [
                course.recruitId,
                video.lessonId,
                video.id,
                video.videoId,
                video.chapterId,
                "0",
                int(played_time - last_submit),
                total,
                watch_hms,
                uuid + self.UUID_SUFFIX,
            ]
            data = {
                "ewssw": watch_point,
                "sdsew": get_ev(raw_ev),
                "zwsds": token_id,
                "courseId": course.courseInfo.courseId,
            }
        return self.call(ep.ZHIDAO_SAVE_DB_V2, data,
                         context="上报学习进度", rac_id=rac_id).data

    def report_cache(self, rac_id: str, video: AttrDict, course: AttrDict,
                     played_time: float, last_submit: float, watch_point: str,
                     token_id: str) -> AttrDict:
        """缓存层上报。字段结构与数据库层不同，勿混用。"""
        raw_ev = [
            course.recruitId,
            video.chapterId,
            video.lessonId,
            video.id,
            hms(seconds=min(video.videoSec, int(played_time))),
            int(played_time),
            video.videoId,
            video.id,
            int(played_time - last_submit),
        ]
        return self.call(ep.ZHIDAO_SAVE_CACHE, {
            "watchPoint": watch_point,
            "ev": get_ev(raw_ev),
            "learningTokenId": token_id,
        }, context="上报缓存进度", rac_id=rac_id).data
