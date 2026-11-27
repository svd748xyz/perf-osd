# -*- coding: utf-8 -*-
"""生成 docs/ 里的两张预览图。

背景是脚本画出来的渐变，**不是屏幕截图**——不包含任何桌面内容。
数字是写死的样例值（不采集本机），所以每次生成的图都一样。

用法:
    python tools/make_preview.py
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from PIL import Image, ImageDraw  # noqa: E402

from perf_osd.config import DEFAULTS  # noqa: E402
from perf_osd.overlay import Overlay  # noqa: E402

SCALE = 1.25        # 按 125% 缩放出图，和文档里写的像素数一致
MARGIN = 26         # 图里给面板留的白边

SAMPLE_ROWS = [
    {"label": "CPU", "value": " 51%", "extra": "", "level": 0},
    {"label": "MEM", "value": " 51%", "extra": "16.3/32G", "level": 0},
    {"label": "GPU", "value": " 36%", "extra": "48°C", "level": 0},
]


def backdrop(size: tuple[int, int], dark: bool) -> Image.Image:
    """造一张渐变当"桌面"，深色配面板模式，浅色配纯文字模式。"""
    w, h = size
    top = (18, 22, 34) if dark else (236, 239, 244)
    bot = (44, 58, 96) if dark else (198, 206, 220)
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)],
               fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return im


def render(background: bool) -> tuple[Image.Image, tuple[int, int]]:
    cfg = dict(DEFAULTS)
    cfg["background"] = background
    ov = Overlay(cfg)
    ov.scale = SCALE
    img, _ = ov._paint(SAMPLE_ROWS)
    pad = MARGIN
    canvas = backdrop((img.width + pad * 2, img.height + pad * 2),
                      dark=background).convert("RGBA")
    canvas.alpha_composite(img, (pad, pad))
    return canvas.convert("RGB"), img.size


def main() -> int:
    out_dir = os.path.join(BASE, "docs")
    os.makedirs(out_dir, exist_ok=True)
    for background, name in ((True, "preview.png"), (False, "preview-text.png")):
        canvas, size = render(background)
        path = os.path.join(out_dir, name)
        canvas.save(path)
        print(f"{name:18s} 面板 {size[0]}x{size[1]}  图 {canvas.width}x{canvas.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
