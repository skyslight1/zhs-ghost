"""校内课（hike）接口的 MD5 签名。

盐值是固定的：`o6xpt3b#Qy$Z`，拼接顺序在下面的 SALT_ORDER 里固化。
字段顺序错一位签名就废，所以做成显式常量。
"""
from __future__ import annotations

from hashlib import md5
from typing import Any, Mapping, Sequence

SALT = "o6xpt3b#Qy$Z"

SALT_ORDER: Sequence[str] = (
    "uuid", "courseId", "fileId", "studyTotalTime",
    "startDate", "endDate", "endWatchTime", "startWatchTime", "uuid",
)


def hike_sign(params: Mapping[str, Any]) -> str:
    """按前端顺序拼盐 + 字段，返回 md5 hex。

    注意 uuid 出现两次（开头和结尾），这不是笔误，是前端混淆代码里的原样。
    """
    parts = []
    for field in SALT_ORDER:
        value = params.get(field, "")
        parts.append("" if value is None else str(value))
    return md5((SALT + "".join(parts)).encode("utf-8")).hexdigest()
