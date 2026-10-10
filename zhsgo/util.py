"""通用工具：带属性访问的 dict、时间格式化、进度条、cookie 转换。

关于 AttrDict：原项目用 ObjDict，功能很全但有个隐蔽的坑 —— `default` 会
沿树向下扩散到所有子 dict，某处无心设置就能让别处的 `KeyError` 变成静默
返回假值。解析接口响应时这个坑很难查。

这里保留属性访问和可选 default，但把 default 的作用域限制在**显式设置它的
那一层**，子节点不继承。
"""
from __future__ import annotations

import copy
import os
import random
import sys
from datetime import timedelta
from typing import Any, Iterable, Iterator, List, Optional, Sequence

from requests.cookies import RequestsCookieJar, create_cookie

_MISSING = object()


class AttrDict(dict):
    """支持 `obj.key` 访问的 dict。缺键时按 default 决定行为。"""

    def __init__(self, data: Optional[dict] = None, default: Any = _MISSING,
                 recursive: bool = True, _convert: bool = True):
        super().__init__()
        object.__setattr__(self, "_default", default)
        object.__setattr__(self, "_recursive", recursive)
        if data:
            for k, v in dict(data).items():
                dict.__setitem__(self, k, self._wrap(v) if _convert else v)

    # ---------------------------------------------------------------- 内部

    def _wrap(self, v: Any) -> Any:
        if not object.__getattribute__(self, "_recursive"):
            return v
        if isinstance(v, AttrDict):
            return v
        if isinstance(v, dict):
            return AttrDict(v, default=object.__getattribute__(self, "_default"))
        if isinstance(v, list):
            return [self._wrap(i) for i in v]
        if isinstance(v, tuple):
            return tuple(self._wrap(i) for i in v)
        return v

    @property
    def default(self) -> Any:
        return object.__getattribute__(self, "_default")

    @default.setter
    def default(self, value: Any) -> None:
        object.__setattr__(self, "_default", value)

    def snapshot(self) -> dict:
        """转回普通 dict（递归）。"""
        out: dict = {}
        for k, v in dict.items(self):
            if isinstance(v, AttrDict):
                out[k] = v.snapshot()
            elif isinstance(v, list):
                out[k] = [i.snapshot() if isinstance(i, AttrDict) else i for i in v]
            else:
                out[k] = v
        return out

    # ---------------------------------------------------------------- 访问

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(f"{name} not found") from e

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self[name] = value

    def __getitem__(self, key: Any) -> Any:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        d = object.__getattribute__(self, "_default")
        if d is _MISSING:
            raise KeyError(key)
        value = copy.deepcopy(d)
        dict.__setitem__(self, key, value)
        return value

    def __setitem__(self, key: Any, value: Any) -> None:
        dict.__setitem__(self, key, self._wrap(value))

    def get(self, key: Any, default: Any = None) -> Any:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        d = object.__getattribute__(self, "_default")
        if d is not _MISSING:
            value = copy.deepcopy(d)
            dict.__setitem__(self, key, value)
            return value
        return default

    def update(self, other: Any = None, **kw: Any) -> None:
        if other:
            items = other.items() if hasattr(other, "items") else other
            for k, v in items:
                self[k] = v
        for k, v in kw.items():
            self[k] = v

    def copy(self) -> "AttrDict":
        return AttrDict(dict(self), default=object.__getattribute__(self, "_default"),
                        recursive=False, _convert=False)

    def __iter__(self) -> Iterator[Any]:
        return dict.__iter__(self)


def wrap(data: Any, default: Any = _MISSING) -> Any:
    """把任意 JSON 响应包成 AttrDict。"""
    if isinstance(data, AttrDict):
        return data
    if isinstance(data, dict):
        return AttrDict(data, default=default)
    if isinstance(data, list):
        return [wrap(i, default) for i in data]
    return data


# -------------------------------------------------------------------- 时间

def hms(seconds: float = 0, **kw: Any) -> str:
    """`00:12:34` 形式，与前端上报格式一致。"""
    return str(timedelta(seconds=int(seconds), **kw))


# -------------------------------------------------------------------- 终端

def terminal_width(fallback: int = 80) -> int:
    try:
        return max(60, os.get_terminal_size().columns - 1)
    except OSError:
        return fallback


def wipe_line() -> None:
    try:
        width = os.get_terminal_size().columns
    except OSError:
        width = 80
    print("\r" + " " * width, end="\r", flush=True)


def progress_bar(iteration: float, total: float, prefix: str = "", suffix: str = "",
                 length: Optional[int] = None, fill: str = "#", enabled: bool = True) -> None:
    if not enabled or total <= 0:
        return
    if not length:
        length = terminal_width() - 3
    ratio = min(1.0, max(0.0, iteration / float(total)))
    head = f"{prefix} |"
    tail = f"| {ratio * 100:.1f}% {suffix}"
    bar_len = max(1, length - len(head) - len(tail))
    filled = int(bar_len * ratio)
    bar = fill * filled + " " * (bar_len - filled)
    print(f"\r{head}{bar}{tail}", end="\r" if ratio < 1.0 else "\n", flush=True)


# -------------------------------------------------------------------- Cookie

def jar_from_dict(data: dict) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for k, v in (data or {}).items():
        jar.set(k, v)
    return jar


def jar_to_list(jar: RequestsCookieJar) -> List[dict]:
    out = []
    for c in jar:
        out.append({
            "name": c.name, "value": c.value, "domain": c.domain, "port": c.port,
            "path": c.path, "expires": c.expires, "secure": c.secure,
            "rest": c.__dict__.get("_rest", {}), "version": c.version,
            "comment": c.comment, "comment_url": c.comment_url,
            "rfc2109": c.rfc2109, "discard": c.discard,
        })
    return out


def jar_from_list(items: Iterable[dict]) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for d in items:
        jar.set_cookie(create_cookie(
            name=d["name"], value=d.get("value"), domain=d.get("domain", ""),
            port=d.get("port"), path=d.get("path", "/"), expires=d.get("expires"),
            secure=d.get("secure", False), rest=d.get("rest", {"HttpOnly": None}),
            version=d.get("version", 0), comment=d.get("comment"),
            comment_url=d.get("comment_url"), rfc2109=d.get("rfc2109", False),
            discard=d.get("discard", True),
        ))
    return jar


def merge_cookies(jar: RequestsCookieJar, items: Iterable[dict]) -> List[str]:
    """把一批 cookie 合并进 jar，返回发生变化的 cookie 名。"""
    changed: List[str] = []
    for c in items:
        name = c.get("name")
        if not name:
            continue
        value = c.get("value", "")
        try:
            old = jar.get(name)
        except Exception:
            old = None
        try:
            jar.set(name, value, domain=c.get("domain"), path=c.get("path") or "/")
        except Exception:
            jar.set(name, value)
        if old != value:
            changed.append(name)
    return changed


# -------------------------------------------------------------------- 随机

def tri(lo: float, hi: float, mode: Optional[float] = None) -> float:
    """三角分布取随机值（偏向 lo/flo 与 hi 之间的中位数，更接近人类行为）。"""
    if hi <= lo:
        return float(lo)
    return random.triangular(float(lo), float(hi), float(mode if mode is not None else lo))


def chance(p: float) -> bool:
    return random.random() < p


def shorten(text: str, limit: Optional[int] = None) -> str:
    limit = limit or terminal_width()
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_zhidao_id(course_id: str) -> bool:
    """共享课 ID 是 32 位 hex（recruitAndCourseId），校内课是纯数字 courseId。"""
    return any(ch.isalpha() for ch in str(course_id))


def stderr_safe() -> None:
    """Windows 控制台重定向时避免 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
