"""运行时路径解析 —— 同时兼容源码运行和 PyInstaller 打包。

打包后有两套目录，必须区分开：

  * **app_root** —— 可写目录，= exe 所在目录。
    `config.yaml` / `state/` / `logs/` 都放这儿，用户能直接看到和编辑。

  * **bundle_root** —— 只读资源目录，打包后是 PyInstaller 的解压临时目录
    (`sys._MEIPASS`)。`config.example.yaml` 这类模板从这里取。

查找资源时先看 app_root 再看 bundle_root，这样用户可以放一个同名文件
到 exe 旁边做覆盖，而不需要重新打包。
"""
from __future__ import annotations

import os
import sys
from typing import Optional


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> str:
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_root() -> str:
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_root())
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidate_roots() -> tuple[str, ...]:
    roots = [app_root(), bundle_root()]
    # 去重同时保持顺序
    seen: list[str] = []
    for r in roots:
        if r and r not in seen:
            seen.append(r)
    return tuple(seen)


def find_resource(name: str) -> Optional[str]:
    """在 app_root / bundle_root 里找文件。"""
    for base in candidate_roots():
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return None


def runtime_label() -> str:
    if not is_frozen():
        return "源码版"
    return "精简版" if variant() == "lite" else "完整版"


def variant() -> str:
    """构建变体：source / full / lite。

    打包时靠 exe 文件名区分 —— spec 里就是按这个名字出的产物。
    """
    if not is_frozen():
        return "source"
    name = os.path.basename(sys.executable).lower()
    return "lite" if "lite" in name else "full"
