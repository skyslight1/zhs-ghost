"""业务接口层：只负责协议（组参、加密、签名、错误码），不含节拍与风控策略。"""
from .aicourse import AiCourseApi
from .exam import ExamApi
from .hike import HikeApi
from .passport import Passport
from .zhidao import ZhidaoApi

__all__ = ["Passport", "ZhidaoApi", "HikeApi", "AiCourseApi", "ExamApi"]
