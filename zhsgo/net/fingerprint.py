"""浏览器指纹：UA 与 Client Hints 必须内部自洽。

原项目写死的头存在三处硬伤（也是"挂久了必吃 -12"的第一层原因）：

    sec-ch-ua:        " Not A;Brand";v="99", "Chromium";v="101", "Google Chrome";v="101"
    User-Agent:       ...Chrome/100.0.4896.127...
    Accept-Language:  en-GB,en;q=0.9

1. Chrome 100 的 UA 配 Chrome 101 的 Client Hints，版本号自相矛盾；
2. 一个刷中国高校网课的人用英式英语浏览器；
3. 这套头是全网脚本用户共用的 —— 风控按指纹聚类一刀切，指纹群一脏，
   所有后来者挂久都被连带打上 -12。

所以这里：生成一套自洽的指纹 → 持久化固定 → 每次请求带上匹配的
Referer / Origin / Sec-Fetch-*。
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

# 各接口对应的真实来源页：(Referer, Origin, Sec-Fetch-Site)
REFERER_RULES: Dict[str, Tuple[str, str, str]] = {
    "studyservice-api.zhihuishu.com": ("https://studyh5.zhihuishu.com/", "https://studyh5.zhihuishu.com", "same-site"),
    "onlineservice-api.zhihuishu.com": ("https://onlineweb.zhihuishu.com/", "https://onlineweb.zhihuishu.com", "same-site"),
    "studyresources.zhihuishu.com": ("https://onlineweb.zhihuishu.com/", "https://onlineweb.zhihuishu.com", "same-site"),
    "hike-teaching.zhihuishu.com": ("https://hike.zhihuishu.com/", "https://hike.zhihuishu.com", "same-site"),
    "hikeservice.zhihuishu.com": ("https://hike.zhihuishu.com/", "https://hike.zhihuishu.com", "same-site"),
    "newbase.zhihuishu.com": ("https://studyh5.zhihuishu.com/", "https://studyh5.zhihuishu.com", "same-site"),
    "kg-ai-run.zhihuishu.com": ("https://ai.zhihuishu.com/", "https://ai.zhihuishu.com", "same-site"),
    "studentexamtest.zhihuishu.com": ("https://ai.zhihuishu.com/", "https://ai.zhihuishu.com", "same-site"),
    "appcomm-user.zhihuishu.com": ("https://passport.zhihuishu.com/", "https://passport.zhihuishu.com", "same-site"),
    "passport.zhihuishu.com": ("https://passport.zhihuishu.com/", "https://passport.zhihuishu.com", "same-origin"),
    "ai-knowledge-map-platform.zhihuishu.com": ("https://ai.zhihuishu.com/", "https://ai.zhihuishu.com", "same-site"),
}

_ZHS_HOST = "zhihuishu.com"


def sec_ch_ua(major: int) -> str:
    """Client Hints 的品牌顺序和值随 Chrome 大版本变化，必须对照生成。"""
    if major >= 120:
        return f'"Not_A Brand";v="8", "Chromium";v="{major}", "Google Chrome";v="{major}"'
    if major >= 116:
        return f'"Not/A)Brand";v="99", "Google Chrome";v="{major}", "Chromium";v="{major}"'
    return f'" Not A;Brand";v="99", "Chromium";v="{major}", "Google Chrome";v="{major}"'


def user_agent(major: int, platform: str) -> str:
    if platform == "macOS":
        return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    if platform == "Linux":
        return ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")


@dataclass
class Fingerprint:
    chrome_major: int = 126
    platform: str = "Windows"
    accept_language: str = "zh-CN,zh;q=0.9,en;q=0.8"

    @classmethod
    def generate(cls, majors=None, platforms=None) -> "Fingerprint":
        return cls(
            chrome_major=int(random.choice(majors or [120, 124, 126, 128, 130])),
            platform=random.choice(platforms or ["Windows", "macOS"]),
        )

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Fingerprint":
        if not data:
            return cls.generate()
        return cls(
            chrome_major=int(data.get("chrome_major", 126)),
            platform=data.get("platform", "Windows"),
            accept_language=data.get("accept_language", "zh-CN,zh;q=0.9,en;q=0.8"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    # ------------------------------------------------------------ 构造头

    @property
    def user_agent(self) -> str:
        return user_agent(self.chrome_major, self.platform)

    @property
    def sec_ch_ua(self) -> str:
        return sec_ch_ua(self.chrome_major)

    def headers(self, content_type: Optional[str] = None, *, navigation: bool = False) -> Dict[str, str]:
        """按真实 Chrome 的 XHR / 导航请求顺序构造头。"""
        h: Dict[str, str] = {}
        h["sec-ch-ua"] = self.sec_ch_ua
        h["sec-ch-ua-mobile"] = "?0"
        h["sec-ch-ua-platform"] = f'"{self.platform}"'
        if navigation:
            h["Upgrade-Insecure-Requests"] = "1"
        h["User-Agent"] = self.user_agent
        h["Accept"] = ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                       "image/webp,*/*;q=0.8") if navigation else "application/json, text/plain, */*"
        h["Accept-Encoding"] = "gzip, deflate"
        h["Accept-Language"] = self.accept_language
        if content_type == "form":
            h["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        elif content_type == "json":
            h["Content-Type"] = "application/json;charset=UTF-8"
        return h

    def referer_for(self, url: str) -> Tuple[str, str, str]:
        host = urlparse(url).netloc.lower()
        for key, rule in REFERER_RULES.items():
            if host == key or host.endswith("." + key):
                return rule
        if host.endswith(_ZHS_HOST):
            base = f"https://{host}/"
            return base, f"https://{host}", "same-site"
        return "", "", "cross-site"

    def apply_referer(self, headers: Dict[str, str], url: str, method: str) -> Dict[str, str]:
        referer, origin, site = self.referer_for(url)
        if referer:
            headers["Referer"] = referer
            headers["Sec-Fetch-Site"] = site
            headers["Sec-Fetch-Mode"] = "cors"
            headers["Sec-Fetch-Dest"] = "empty"
            if method.upper() != "GET" and origin:
                headers["Origin"] = origin
        return headers

    def describe(self) -> str:
        return f"Chrome/{self.chrome_major} on {self.platform}"
