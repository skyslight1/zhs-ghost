# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 通过环境变量控制出哪个版本。

    ZHS_VARIANT = full | lite       默认 full
    ZHS_ONEFILE = 1 | 0             默认 1（单文件 exe）

full 版把 playwright / ddddocr / onnxruntime / opencv 都打进去，双击即用；
lite 版只保留核心，遇到人机验证时直接开浏览器让人手动滑。
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

VARIANT = os.environ.get("ZHS_VARIANT", "full").lower()
ONEFILE = os.environ.get("ZHS_ONEFILE", "1") == "1"
GUI = os.environ.get("ZHS_GUI", "0") == "1"

# SPECPATH = 本文件所在目录（packaging/），仓库根是它的上级
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

if VARIANT == "full":
    NAME = "zhs-ghost-gui" if GUI else "zhs-ghost"
else:
    NAME = "zhs-ghost-lite-gui" if GUI else "zhs-ghost-lite"

ENTRY = os.path.join(ROOT, "gui.py" if GUI else "main.py")


def _need(rel):
    path = os.path.join(ROOT, rel)
    return os.path.exists(path)


# ------------------------------------------------------------------ 数据文件
datas = []

for rel, dest in (
    ("config.example.yaml", "."),
    ("README.md", "."),
    ("LICENSE", "."),
    (os.path.join("docs", "使用教程.md"), "docs"),
):
    if _need(rel):
        datas.append((os.path.join(ROOT, rel), dest))

if os.path.isdir(os.path.join(ROOT, "docs")):
    datas.append((os.path.join(ROOT, "docs"), "docs"))

binaries = []

# ------------------------------------------------------------------ 隐藏导入
hiddenimports = [
    "zhsgo",
    "yaml",
    "loguru",
    "requests",
    "Crypto",
    "Crypto.Cipher",
    "Crypto.Cipher.AES",
    "PyInstaller",
]

# ------------------------------------------------------------------ 排除项
excludes = [
    "tkinter",
    "matplotlib",
    "pandas",
    "scipy",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "jupyter",
    "pytest",
    "notebook",
    # 本项目用的是 requests 直连 OpenAI 兼容接口，不需要官方 SDK
    "openai",
    "tiktoken",
    "transformers",
    "torch",
    # 只给测试用，打包版不需要
    "tests",
]

# ------------------------------------------------------------------ 变体差异
if VARIANT == "full":
    # ddddocr 带着模型文件，必须一起打包
    datas += collect_data_files("ddddocr")
    # playwright 的 driver（node + cli.js）在包数据里
    datas += collect_data_files("playwright")
    # onnxruntime 的 DLL 不会被自动收集
    binaries += collect_dynamic_libs("onnxruntime")
    hiddenimports += [
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",
        "playwright._impl._driver",
        "ddddocr",
        "onnxruntime",
        "cv2",
        "numpy",
        "PIL",
        "PIL.Image",
        "PIL.ImageOps",
    ]
else:
    excludes += ["playwright", "ddddocr", "onnxruntime", "cv2", "numpy"]


# ------------------------------------------------------------------ 构建
a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_common = dict(
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压缩会让 Windows Defender 误报率明显上升，宁可包大一点
    upx=False,
    upx_exclude=[],
    # GUI 版关掉控制台，避免双击时弹出一个黑框
    console=not GUI,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=os.path.join(ROOT, "packaging", "version_info.txt")
    if _need(os.path.join("packaging", "version_info.txt")) else None,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **_common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_common)
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False, name=NAME,
    )
