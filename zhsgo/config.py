"""配置：yaml → dataclass。

每个子系统的配置就在它自己的模块里定义（`PacerConfig` 在 pacer.py 等），
这里只负责读 yaml 并组装。好处是加一个旋钮时不用改两处。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

import yaml

from .ai.prompts import AnswerContext
from .errors import ZhsError
from .net.fingerprint import Fingerprint
from .risk.budget import BudgetConfig
from .risk.guard import GuardConfig
from .risk.pacer import PacerConfig
from .relay.browser import RelayConfig

T = TypeVar("T")

DEFAULT_CONFIG_NAME = "config.yaml"


# ---------------------------------------------------------------------- 子配置

@dataclass
class StudyConfig:
    speed: Optional[float] = None           # None = 用 Pacer 的 default_speed
    end_threshold: float = 0.91             # 高于此比例视为完成
    tree_view: bool = True
    progress_view: bool = True
    # 进视频时先发一次初始化上报（前端确实会发，开了更像真人）
    initial_report: bool = True
    # 同时发 cache 层上报（前端两条链路都会发）
    cache_report: bool = False
    # 请求 initVideo 拉一次播放地址，制造 CDN 侧流量痕迹
    prime_video: bool = True
    # 弹题：从题目出现到提交之间的人为延迟（秒）
    quiz_delay: Tuple[float, float] = (2.0, 6.0)
    # 单视频上报前的最大等待，用于避免极端长视频卡死
    max_video_seconds: float = 4 * 3600.0


@dataclass
class AuthConfig:
    username: str = ""
    password: str = ""
    use_qr: bool = True                     # 账号密码登录目前容易触发风控，默认扫码
    save_cookies: bool = True
    qr_in_terminal: bool = True


@dataclass
class OpenAIConfig:
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    stream: bool = False


@dataclass
class AiConfig:
    enabled: bool = False
    backend: str = "zhidao"                 # zhidao | openai
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    context: AnswerContext = field(default_factory=AnswerContext)
    skip_exam: bool = False
    max_exam_attempts: int = 5
    give_up_below: float = 30.0             # masteryScore 低于此值且尝试多次就放弃
    target_mastery: float = 90.0


@dataclass
class NotifyConfig:
    enabled: bool = True
    serverchan_key: str = ""
    dingtalk_webhook: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    local_beep: bool = True


@dataclass
class LogConfig:
    dir: str = "./logs"
    level: str = "INFO"


# ---------------------------------------------------------------------- 主配置

@dataclass
class Config:
    base_dir: str = "."
    config_path: str = ""
    state_file: str = "./state/state.json"
    proxies: Dict[str, str] = field(default_factory=dict)
    timeout: float = 15.0

    fingerprint: Fingerprint = field(default_factory=Fingerprint)
    pacer: PacerConfig = field(default_factory=PacerConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    study: StudyConfig = field(default_factory=StudyConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    log: LogConfig = field(default_factory=LogConfig)

    # ---------------------------------------------------------------- 加载

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        from .paths import app_root, find_resource

        path = path or os.path.join(app_root(), DEFAULT_CONFIG_NAME)
        if not os.path.isfile(path):
            _bootstrap_config(path)
        data: Dict[str, Any] = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        base = os.path.dirname(os.path.abspath(path))
        cfg = cls.from_dict(data, base)
        cfg.config_path = path
        return cfg

    @classmethod
    def from_dict(cls, data: Dict[str, Any], base_dir: str = ".") -> "Config":
        cfg = cls()
        cfg.base_dir = base_dir

        for key in ("state_file", "timeout"):
            if key in data:
                setattr(cfg, key, data[key])
        cfg.proxies = dict(data.get("proxies") or {})

        fp_raw = dict(data.get("fingerprint") or {})
        fp = _build(Fingerprint, fp_raw) or Fingerprint()
        # 允许用 0 / "" 表示"自动挑选"：这两个值若直接落进 Fingerprint，
        # 会生成 `Chrome/0` 这种自相矛盾的指纹，反而更容易被识别
        majors = [fp.chrome_major] if fp.chrome_major else None
        platforms = [fp.platform] if fp.platform else None
        if not (majors and platforms):
            picked = Fingerprint.generate(majors, platforms)
            fp.chrome_major = fp.chrome_major or picked.chrome_major
            fp.platform = fp.platform or picked.platform
        cfg.fingerprint = fp
        cfg.pacer = _build(PacerConfig, data.get("pacer")) or PacerConfig()
        cfg.budget = _build(BudgetConfig, data.get("budget")) or BudgetConfig()
        cfg.guard = _build(GuardConfig, data.get("guard")) or GuardConfig()
        cfg.relay = _build(RelayConfig, data.get("relay")) or RelayConfig()
        cfg.study = _build(StudyConfig, data.get("study")) or StudyConfig()
        cfg.auth = _build(AuthConfig, data.get("auth")) or AuthConfig()
        cfg.notify = _build(NotifyConfig, data.get("notify")) or NotifyConfig()
        cfg.log = _build(LogConfig, data.get("log")) or LogConfig()

        ai_raw = dict(data.get("ai") or {})
        ctx_raw = ai_raw.pop("context", {}) or {}
        cfg.ai = _build(AiConfig, ai_raw) or AiConfig()
        cfg.ai.context = _build(AnswerContext, ctx_raw) or AnswerContext()

        cfg._absolutize()
        return cfg

    def _absolutize(self) -> None:
        def fix(value: str) -> str:
            if not value:
                return value
            return value if os.path.isabs(value) else os.path.normpath(
                os.path.join(self.base_dir, value))

        self.state_file = fix(self.state_file)
        self.log.dir = fix(self.log.dir)
        self.relay.user_data_dir = fix(self.relay.user_data_dir)
        self.relay.screenshot_dir = fix(self.relay.screenshot_dir)
        state_dir = os.path.dirname(self.state_file)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

    # ---------------------------------------------------------------- 保存

    def to_dict(self) -> Dict[str, Any]:
        """导出成可写回 yaml 的结构。

        两个细节：
          * 绝对路径要转回相对路径，否则配置换台机器就废了；
          * tuple 必须转 list —— `yaml.safe_dump` 序列化不了 tuple。
        """
        from dataclasses import asdict

        relay = _tuples_to_lists(asdict(self.relay))
        relay["user_data_dir"] = self._relativize(relay.get("user_data_dir", ""))
        relay["screenshot_dir"] = self._relativize(relay.get("screenshot_dir", ""))

        log_cfg = asdict(self.log)
        log_cfg["dir"] = self._relativize(log_cfg.get("dir", ""))

        return {
            "state_file": self._relativize(self.state_file),
            "proxies": dict(self.proxies),
            "timeout": self.timeout,
            "auth": asdict(self.auth),
            "fingerprint": self.fingerprint.to_dict(),
            "pacer": _tuples_to_lists(asdict(self.pacer)),
            "budget": _tuples_to_lists(asdict(self.budget)),
            "guard": _tuples_to_lists(asdict(self.guard)),
            "relay": relay,
            "study": _tuples_to_lists(asdict(self.study)),
            "ai": _tuples_to_lists(asdict(self.ai)),
            "notify": asdict(self.notify),
            "log": log_cfg,
        }

    def _relativize(self, value: str) -> str:
        if not value:
            return value
        try:
            rel = os.path.relpath(value, self.base_dir)
        except Exception:
            return value
        # 爬到上级目录说明这个路径本来就不在项目内，保持绝对更安全
        return value if rel.startswith("..") else rel.replace(os.sep, "/")

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.config_path or os.path.join(self.base_dir, DEFAULT_CONFIG_NAME)
        with open(target, "w", encoding="utf-8") as f:
            f.write("# zhsgo 配置 —— 由图形界面 / 程序写回\n")
            yaml.safe_dump(self.to_dict(), f, allow_unicode=True,
                           sort_keys=False, default_flow_style=False)
        self.config_path = target
        return target

    # ---------------------------------------------------------------- 校验

    def validate(self) -> List[str]:
        problems: List[str] = []
        if self.pacer.max_speed > 1.5:
            problems.append(f"pacer.max_speed={self.pacer.max_speed} 超过前端上限 1.5x，会被风控直接命中")
        if self.budget.daily_minutes > 480:
            problems.append(f"budget.daily_minutes={self.budget.daily_minutes} 分钟过长，真人不可能")
        if self.pacer.report_interval[1] - self.pacer.report_interval[0] < 5:
            problems.append("pacer.report_interval 区间太窄，节拍会退化成固定值")
        if self.ai.enabled and self.ai.backend == "openai" and not self.ai.openai.api_key:
            problems.append("ai.backend=openai 但未填 api_key")
        if self.relay.enabled:
            from .paths import variant

            # 精简版是**故意**不带 ddddocr / playwright 自动识别的，
            # 不该被报成"缺依赖"
            if variant() == "lite":
                pass
            else:
                try:
                    import playwright  # noqa: F401
                except ImportError:
                    problems.append("relay.enabled=true 但未安装 playwright（pip install playwright）")
                try:
                    import ddddocr  # noqa: F401
                except ImportError:
                    problems.append("relay.enabled=true 但未安装 ddddocr（pip install ddddocr）")
        return problems


# ---------------------------------------------------------------------- 工具

def _build(cls: Type[T], data: Optional[dict]) -> Optional[T]:
    """按 dataclass 字段名筛一遍再构造，忽略 yaml 里的未知键。"""
    if data is None:
        return None
    if not is_dataclass(cls):
        return None
    data = dict(data)
    kwargs: Dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if is_dataclass(f.type) and isinstance(value, dict):
            value = _build(f.type, value)
        elif isinstance(value, list) and _is_tuple_field(f):
            value = tuple(value)
        kwargs[f.name] = value
    # 嵌套 dataclass 特殊处理（OpenAIConfig / AnswerContext）
    for name, ftype in (("openai", OpenAIConfig), ("context", AnswerContext)):
        if name in data and isinstance(data[name], dict):
            kwargs[name] = _build(ftype, data[name])
    return cls(**kwargs)


def _is_tuple_field(f) -> bool:
    tp = f.type
    if isinstance(tp, str):
        return tp.startswith("Tuple") or "tuple" in tp
    return getattr(tp, "__origin__", None) is tuple


def _tuples_to_lists(value: Any) -> Any:
    """递归把 tuple 转成 list —— yaml.safe_dump 序列化不了 tuple。"""
    if isinstance(value, tuple):
        return [_tuples_to_lists(v) for v in value]
    if isinstance(value, dict):
        return {k: _tuples_to_lists(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_tuples_to_lists(v) for v in value]
    return value


# ---------------------------------------------------------------- 首次运行

_FALLBACK_CONFIG = """\
# zhsgo 最小配置（首次运行自动生成）
# 带完整注释的版本见仓库里的 config.example.yaml
state_file: "./state/state.json"
auth:
  use_qr: true
  save_cookies: true
pacer:
  max_speed: 1.5
  default_speed: 1.25
  report_interval: [22, 47]
budget:
  daily_minutes: 250
  daily_sessions: 4
relay:
  enabled: true
  headless: false
"""


def _bootstrap_config(target: str) -> None:
    """首次运行：生成 config.yaml，做到真正开箱即用。

    不直接复制文件，而是读内容后重新写出 —— 打包版的示例文件位于
    PyInstaller 的解压目录，那个路径随时可能失效。
    """
    from .paths import find_resource

    text = ""
    example = find_resource("config.example.yaml")
    if example:
        try:
            with open(example, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""
    if not text.strip():
        text = _FALLBACK_CONFIG

    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        print("=" * 68)
        print("未找到配置文件，已生成默认配置：")
        print(f"  {target}")
        print("")
        print("默认使用【扫码登录】—— 账号密码留空即可直接运行。")
        print("只想先看它会做什么：")
        print("  zhs-ghost.exe --dry-run")
        print("=" * 68)
    except Exception as e:  # pragma: no cover
        print(f"[!] 生成默认配置失败: {e}")

