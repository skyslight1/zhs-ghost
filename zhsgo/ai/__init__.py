"""AI 作答：大模型后端、提示词模板、答案解析。"""
from .client import Answerer, AnswerResult, Backend, OpenAICompatBackend, ZhsLlmBackend
from .prompts import TYPE_JUDGE, TYPE_MULTIPLE, TYPE_SINGLE, AnswerContext

__all__ = [
    "Answerer", "AnswerResult", "Backend", "OpenAICompatBackend", "ZhsLlmBackend",
    "AnswerContext", "TYPE_SINGLE", "TYPE_MULTIPLE", "TYPE_JUDGE",
]
