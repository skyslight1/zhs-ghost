"""AES-CBC + Base64 的请求体加密。

智慧树的共享课接口把整个请求体塞进 `secretStr` 字段，密钥按接口分组，
IV 全局固定。
"""
from __future__ import annotations

from base64 import b64decode, b64encode
from typing import Union

from Crypto.Cipher import AES

IV = b"1g3qqdh4jvbskb9x"

HOME_KEY = b"7q9oko0vqb3la20r"
AI_KEY = b"hw2fdlwcj4cs1mx7"
VIDEO_KEY = b"azp53h0kft7qi78q"
QA_KEY = b"kcGOlISPkYKRksSK"
EXAM_KEY = b"onbfhdyvz8x7otrp"


class AesCbc:
    """AES-128-CBC / PKCS#7 / Base64。"""

    def __init__(self, key: bytes = VIDEO_KEY, iv: bytes = IV):
        if len(key) not in (16, 24, 32):
            raise ValueError(f"AES key 长度非法: {len(key)}")
        self.key = key
        self.iv = iv

    @staticmethod
    def _pad(data: str) -> bytes:
        raw = data.encode("utf-8")
        n = 16 - (len(raw) % 16)
        return raw + bytes([n]) * n

    @staticmethod
    def _unpad(data: bytes) -> str:
        if not data:
            return ""
        n = data[-1]
        if 1 <= n <= 16:
            data = data[:-n]
        return data.decode("utf-8", errors="replace")

    def encrypt(self, data: str) -> str:
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        return b64encode(cipher.encrypt(self._pad(data))).decode()

    def decrypt(self, data: Union[str, bytes]) -> str:
        if isinstance(data, str):
            data = data.encode()
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        return self._unpad(cipher.decrypt(b64decode(data)))
