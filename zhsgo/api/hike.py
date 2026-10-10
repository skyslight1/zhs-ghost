"""校内学分课（hike / courseId）接口。

与共享课完全不同的另一套 API：
  * 明文 GET 参数 + MD5 签名（盐 `o6xpt3b#Qy$Z`）；
  * 进度上报返回**服务端累计时间**，必须用它回写本地，否则会重复计进度。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Sequence

from ..crypto import hike_sign
from ..errors import ApiError, CaptchaRequired
from ..net import HttpClient, endpoints as ep
from ..risk import Guard, Pacer
from ..util import AttrDict


class HikeApi:
    def __init__(self, http: HttpClient, guard: Guard, pacer: Pacer,
                 uuid_provider: Callable[[], str]):
        self.http = http
        self.guard = guard
        self.pacer = pacer
        self.uuid_provider = uuid_provider

    # ------------------------------------------------------------- 传输

    def call(self, url: str, params: Dict[str, Any], *, sign: bool = False,
             ok_code: Any = ep.CODE_OK_HIKE, method: str = "GET",
             context: str = "") -> AttrDict:
        data = {k: ("" if v is None else v) for k, v in params.items()}
        data["_"] = self.pacer.ts_ms()
        if sign:
            str_data = {k: str(v) for k, v in data.items()}
            data = str_data
            data["signature"] = hike_sign(data)

        def send() -> AttrDict:
            body = dict(data)
            body["_"] = self.pacer.ts_ms()
            if sign:
                body["signature"] = hike_sign(body)
            if method.upper() == "POST":
                return self.http.post(url, body)
            return self.http.get(url, body)

        ret = send()
        status = ret.get("status")
        if ok_code is not None and int(status or 0) != ok_code:
            raise ApiError(status, ret.get("message") or json.dumps(
                {k: v for k, v in ret.items() if k != "rt"}, ensure_ascii=False, default=str), url)
        return ret

    # ------------------------------------------------------------- 课程

    def course_list(self) -> list:
        ret = self.http.get(ep.HIKE_COURSE_LIST, {
            "uuid": self.uuid_provider(),
            "data": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        })
        result = ret.get("result") or AttrDict({}, default=None)
        return result.get("startInngcourseList") or []

    def menu_tree(self, course_id: Any) -> list:
        ret = self.call(ep.HIKE_MENU_TREE, {"courseId": course_id}, context="查询课程目录")
        return ret.get("rt") or []

    def view_file(self, course_id: Any, file_id: Any) -> AttrDict:
        ret = self.call(ep.HIKE_VIEW_FILE, {"courseId": course_id, "fileId": file_id},
                        context="查询文件信息")
        rt = ret.get("rt")
        if not rt:
            raise ApiError("empty", "stuViewFile 返回空", ep.HIKE_VIEW_FILE)
        return rt

    # ------------------------------------------------------------- 进度

    def save_record(self, course_id: Any, file_id: Any, played_time: float,
                    prev_time: float, start_date: int) -> float:
        """上报一次观看记录，返回服务端认定的累计播放时间。"""
        params = {
            "uuid": self.uuid_provider(),
            "courseId": course_id,
            "fileId": file_id,
            "studyTotalTime": int(played_time - prev_time),
            "startWatchTime": int(prev_time),
            "endWatchTime": int(played_time),
            "startDate": start_date,
            "endDate": self.pacer.ts_ms(),
        }
        ret = self.call(ep.HIKE_SAVE_RECORD, params, sign=True,
                        ok_code=ep.CODE_OK_HIKE, context="上报校内课进度")
        rt = ret.get("rt")
        if rt is None:
            raise ApiError("null", "保存学习记录失败（rt 为空，常见原因是签名不匹配）",
                           ep.HIKE_SAVE_RECORD, params)
        return float(rt)
