"""大模型客户端 + 答案解析。

两个后端：
  * `OpenAICompatBackend` —— 任意 OpenAI 兼容接口（deepseek / moonshot / 本地 vLLM…）
  * `ZhsLlmBackend`        —— 智慧树自带的大模型（`ai-knowledge-map-platform`），
                              不需要额外的 API key，登录态就能用

后者的签名来自反混淆前端：`md5("8ZflKEagfL" + minified_json)`，放在 query 的
`sign` 参数上，还要一个 `chatcmpl-` 前缀的 sessionNid。
"""
from __future__ import annotations

import ast
import hashlib
import json
import random
import re
import string
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from loguru import logger

from ..errors import ZhsError
from ..net import endpoints as ep
from ..net.client import HttpClient
from ..util import AttrDict
from .prompts import ANSWER_BLOCK, AnswerContext, build_prompt


class CompletionError(ZhsError):
    pass


def parse_stream(response: requests.Response, start: str, end: str) -> str:
    """从 SSE 流里累积内容，直到出现完整的 `start … end` 块。"""
    cache = ""
    striped = re.compile(f"{re.escape(start)}(.*?){re.escape(end)}", re.DOTALL)
    for line in response.iter_lines():
        if not line:
            continue
        try:
            payload = json.loads(line.decode("utf-8")[5:])       # 跳过 "data:"
        except Exception:
            continue
        content = payload.get("choices", [{}])[0].get("delta", {}).get("content", "")
        if not content:
            continue
        cache += content
        if striped.search(cache):
            return cache
    return cache


# ---------------------------------------------------------------------- 后端

class Backend:
    is_stream: bool = False

    def complete(self, prompt: str) -> str:  # pragma: no cover - 接口定义
        raise NotImplementedError


class OpenAICompatBackend(Backend):
    def __init__(self, base_url: str, api_key: str, model: str,
                 stream: bool = False, timeout: float = 60.0, retries: int = 3):
        if not api_key:
            raise CompletionError("缺少 api_key")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.stream = stream
        self.timeout = timeout
        self.retries = retries

    def complete(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.api_key}"}
        body = {"model": self.model, "stream": self.stream,
                "messages": [{"role": "user", "content": prompt}]}

        last: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=body,
                                     timeout=self.timeout, stream=self.stream)
                resp.raise_for_status()
                if self.stream:
                    return parse_stream(resp, "```answer", "```")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                last = e
                logger.warning(f"LLM 第 {attempt}/{self.retries} 次失败: {e}")
        raise CompletionError(f"调用外部 LLM 失败: {last}")


class ZhsLlmBackend(Backend):
    """智慧树自带的问答大模型。"""

    PREFIX = "8ZflKEagfL"

    def __init__(self, http: HttpClient, model: str = "moonshot-v1-32k",
                 stream: bool = True, retries: int = 3):
        self.http = http
        self.model = model
        self.stream = stream
        self.retries = retries

    # ---------------------------------------------------------- 签名

    @staticmethod
    def _session_nid() -> str:
        pool = string.ascii_lowercase + string.digits
        return "chatcmpl-" + "".join(random.choice(pool) for _ in range(24))

    @classmethod
    def _input_string(cls, model_code: str, session_nid: str, stream: bool) -> str:
        raw = json.dumps({
            "messageList": "[object Object]",
            "modelCode": model_code,
            "sessionNid": session_nid,
            "stream": stream,
        }, separators=(",", ":"))
        return raw.replace('"true"', "true").replace('"false"', "false")

    @classmethod
    def sign_url(cls, url: str, body: dict) -> str:
        scheme, netloc, path, query, fragment = urlsplit(url)
        params = dict(parse_qsl(query))
        nid = body.setdefault("sessionNid", cls._session_nid())
        raw = cls._input_string(body.get("modelCode", ""), nid, body.get("stream", False))
        params["sign"] = hashlib.md5((cls.PREFIX + raw).encode("utf-8")).hexdigest()
        return urlunsplit((scheme, netloc, path, urlencode(params), fragment))

    # ---------------------------------------------------------- 调用

    def complete(self, prompt: str) -> str:
        body = {
            "messageList": [{"role": "user", "content": prompt}],
            "modelCode": self.model,
            "stream": self.stream,
        }
        last: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                signed = self.sign_url(ep.ZHS_LLM_STREAM, body)
                if self.stream:
                    resp = self.http.session.post(
                        signed, json=body, timeout=60, stream=True,
                        headers=self.http._headers(signed, "POST", "json"))
                    resp.raise_for_status()
                    return parse_stream(resp, "```answer", "```")
                resp = self.http.session.post(
                    signed, json=body, timeout=60,
                    headers=self.http._headers(signed, "POST", "json"))
                resp.raise_for_status()
                return json.loads(resp.text[5:])["choices"][0]["message"]["content"]
            except Exception as e:
                last = e
                logger.warning(f"智慧树 LLM 第 {attempt}/{self.retries} 次失败: {e}")
        raise CompletionError(f"调用智慧树大模型失败: {last}")


# ---------------------------------------------------------------------- 答题

@dataclass
class AnswerResult:
    ids: List[Any]
    source: str                      # ai / cache / random / single-option
    raw: str = ""


class Answerer:
    def __init__(self, backend: Optional[Backend], ctx: Optional[AnswerContext] = None,
                 max_prompt_chars: int = 60000):
        self.backend = backend
        self.ctx = ctx or AnswerContext()
        self.max_prompt_chars = max_prompt_chars

    # ---------------------------------------------------------- 截断

    def _trim(self, prompt: str) -> str:
        if len(prompt) <= self.max_prompt_chars:
            return prompt
        logger.warning(f"prompt 过长({len(prompt)} 字符)，截断到 {self.max_prompt_chars}")
        return prompt[-self.max_prompt_chars:]

    # ---------------------------------------------------------- 解析

    @staticmethod
    def parse(text: str) -> List[Any]:
        match = re.search(ANSWER_BLOCK, text, re.DOTALL)
        if not match:
            raise ValueError("响应里没有找到 ```answer 代码块")
        raw = match.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = ast.literal_eval(raw)
        if not isinstance(data, list):
            raise ValueError(f"答案应为列表，实际是 {type(data)}")
        ids = []
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                raise ValueError(f"答案项缺少 id: {item}")
            ids.append(item["id"])
        return ids

    # ---------------------------------------------------------- 主入口

    def answer(self, question_type: int, question: str, choices: List[dict],
               materials: Optional[Sequence[dict]] = None) -> AnswerResult:
        if len(choices) == 1:
            return AnswerResult([choices[0]["id"]], "single-option")

        if self.backend is None:
            return AnswerResult(self.random_pick(choices, question_type), "random")

        prompt = build_prompt(self.ctx, question_type, question, choices, materials)
        try:
            text = self.backend.complete(self._trim(prompt))
            return AnswerResult(self.parse(text), "ai", text)
        except Exception as e:
            logger.error(f"AI 作答失败，回退随机: {e}")
            return AnswerResult(self.random_pick(choices, question_type), "random")

    @staticmethod
    def random_pick(choices: List[dict], question_type: int) -> List[Any]:
        n = 1 if question_type in (1, 14) else 2
        n = min(n, len(choices))
        return [c["id"] for c in random.sample(choices, n)]
