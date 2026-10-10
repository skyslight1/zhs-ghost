"""`ev` 参数编解码（异或 + hex 拼装）。

前端把一串观看记录字段拼成 `;` 分隔的字符串，逐字符与循环密钥异或，
再把每个字节的 hex 形式拼起来。这里保持与原前端完全一致的实现。
"""
from __future__ import annotations

from typing import Iterator, List, Sequence

DEFAULT_KEY = "zzpttjd"
ALT_KEY = "zhihuishu"


def _key_stream(key: str) -> Iterator[int]:
    while True:
        for ch in key:
            yield ord(ch)


def get_ev(data: Sequence, key: str = DEFAULT_KEY) -> str:
    """把字段列表编码成 `ev` 参数。

    * `key="zzpttjd"` 对应 `d26666`
    * `key="zhihuishu"` 对应 `d24444`
    """
    stream = _key_stream(key)
    joined = ";".join(map(str, data))
    out: List[str] = []
    for ch in joined:
        piece = hex(ord(ch) ^ next(stream)).replace("0x", "")
        if len(piece) < 2:
            piece = "0" + piece
        # 前端源码里写的是取后 4 位（实际后 2 位就够，但保持原样以免对不上）
        out.append(piece[-4:])
    return "".join(out)


def rev_ev(ev: str, key: str = DEFAULT_KEY) -> str:
    """`get_ev` 的逆运算，用于调试时还原服务端返回值。

    限制：按固定 2 位一组解码，因此只对原始字符 ≤ 0xFF 的 `ev` 有效。
    实际上报字段全是数字和 ASCII（uuid / 时间戳 / 时长），都落在这个范围内。
    中文等多字节字符编码后是 4 位 hex，从码流里无法区分宽度 ——
    那种情况本函数解不出来，这点原实现同样如此，不是回归。
    """
    stream = _key_stream(key)
    chars = list(ev)
    codes: List[int] = []
    while len(chars) >= 2:
        hi = chars.pop()
        lo = chars.pop()
        codes.append(int(lo + hi, 16))
    return "".join(chr(c ^ next(stream)) for c in codes[::-1])
