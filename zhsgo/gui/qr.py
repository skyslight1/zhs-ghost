"""二维码渲染（终端 + 图形界面都用得上）。"""
from __future__ import annotations

import io
from typing import Optional


def to_photo(image_bytes: bytes, size: int = 260):
    """PNG 字节 → ImageTk.PhotoImage。

    调用方**必须**持有返回值的引用：PhotoImage 被 GC 后 Label 会显示空白，
    这是 Tkinter 里最经典的坑之一。
    """
    try:
        from PIL import Image, ImageTk
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = img.resize((size, size), Image.Resampling.NEAREST)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def render_terminal(image_bytes: bytes, margin: int = 1) -> str:
    """用半块字符在终端画二维码（给命令行版用）。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return ""
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    img = ImageOps.invert(img)
    size = 45
    img = img.resize((size, size), Image.Resampling.NEAREST)
    px = img.load()

    lines = []
    border = "\033[0;37;47m" + "  " * (size + margin * 2) + "\033[0m"
    for _ in range(margin):
        lines.append(border)
    for y in range(0, size, 2):
        row = ["\033[0;37;47m" + "  " * margin]
        for x in range(size):
            top = px[x, y] > 128
            bottom = px[x, y + 1] > 128 if y + 1 < size else False
            if top and bottom:
                row.append("\033[0;37;40m  ")
            elif top and not bottom:
                row.append("\033[0;37;40m▀▀")
            elif not top and bottom:
                row.append("\033[0;37;40m▄▄")
            else:
                row.append("\033[0;37;47m  ")
        row.append("\033[0m")
        lines.append("".join(row))
    for _ in range(margin):
        lines.append(border)
    return "\n".join(lines)


def save_png(image_bytes: bytes, path: str) -> Optional[str]:
    try:
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path
    except Exception:
        return None
