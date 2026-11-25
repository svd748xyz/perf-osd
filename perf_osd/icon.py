# -*- coding: utf-8 -*-
"""程序图标：深色圆角底 + 青色上升柱状条，16px 下也认得出。

图标只有一个来源（这里），启动器、快捷方式、托盘都指向 assets/icon.ico。
"""
from __future__ import annotations

import os

ICO_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
             (64, 64), (128, 128), (256, 256)]

BG_TOP = (23, 27, 36, 255)
BG_BOTTOM = (9, 11, 15, 255)
EDGE = (86, 196, 236, 210)
BAR_TOP = (128, 232, 255, 255)
BAR_BOTTOM = (46, 116, 255, 255)


def _vgradient(size: int, top: tuple, bottom: tuple):
    from PIL import Image

    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return grad.resize((size, size), Image.BILINEAR)


def draw_icon(size: int = 256):
    """返回一张 RGBA 图标。几何按 256 设计，按超采样倍数放大绘制。"""
    from PIL import Image, ImageDraw, ImageFilter

    ss = 4                       # 超采样，缩到 16px 也不糊
    S = 256 * ss

    def u(v: float) -> int:      # 256 坐标 -> 画布坐标
        return int(round(v * ss))

    radius = u(58)

    # ---- 底板
    plate = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    plate_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(plate_mask).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=radius, fill=255)
    plate.paste(_vgradient(S, BG_TOP, BG_BOTTOM), (0, 0), plate_mask)

    # ---- 外圈一道青边
    edge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=radius, outline=EDGE, width=max(2, u(1.6)))
    plate.alpha_composite(edge)

    # ---- 三根递增的柱状条（居中，底边 190）
    bottom, bar_w = 190, 40
    bars = [(58, 130), (108, 94), (158, 58)]      # (x, top)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for x, top in bars:
        h = bottom - top
        grad = _vgradient(u(h), BAR_TOP, BAR_BOTTOM).resize((u(bar_w), u(h)), Image.BILINEAR)
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (u(x), u(top), u(x + bar_w) - 1, u(bottom) - 1), radius=u(bar_w / 2), fill=255)
        tmp = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        tmp.paste(grad, (u(x), u(top)))
        layer.paste(tmp, (0, 0), mask)

    plate.alpha_composite(layer.filter(ImageFilter.GaussianBlur(u(2.2))))  # 外发光
    plate.alpha_composite(layer)

    icon = plate.resize((256, 256), Image.LANCZOS)
    if size != 256:
        icon = icon.resize((size, size), Image.LANCZOS)
    return icon


def ensure(path: str, force: bool = False) -> str:
    """生成（或刷新）多尺寸 .ico。"""
    try:
        icon = draw_icon(256)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if force or not os.path.exists(path):
            icon.save(path, format="ICO", sizes=ICO_SIZES)
            return path
        # 已存在：用文件大小粗判是不是老版本图标
        if os.path.getsize(path) < 8000:
            icon.save(path, format="ICO", sizes=ICO_SIZES)
        return path
    except Exception:
        return path
