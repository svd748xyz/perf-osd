# -*- coding: utf-8 -*-
"""配置文件读写（JSON，缺失键自动补默认值）。"""
from __future__ import annotations

import copy
import json
import os

DEFAULTS: dict = {
    # 外观
    "font_size": 16,         # 基准字号（96 DPI 下），高 DPI 自动放大
    "opacity": 0.86,         # 背景不透明度
    "radius": 10,            # 圆角
    "anchor": "top-right",   # top-right / top-left / bottom-right / bottom-left
    "margin_x": 16,
    "margin_y": 16,
    "pos": None,             # 拖动后会写入这里，覆盖 anchor
    "visible": True,
    "background": True,      # false = 纯文字，无蒙版背景
    # 刷新
    "refresh_ms": 100,       # 重绘间隔
    "sample_ms": 500,        # 采样间隔
    # 显示项
    "show_app": True,        # 显示正在统计帧率的进程名
    "show_frametime": True,  # FPS 后面附带帧生成时间 ms
    "show_temp": True,       # GPU 温度
    "show_vram": True,       # 显存占用
    "gpu": {"backend": "auto", "index": 0},
    "fps": {
        "enabled": True,
        "window_s": 1.0,
        "pin_process": "",           # 填 exe 名可锁定某个游戏
        "presentmon": "tools/PresentMon.exe",
        "session_name": "PerfOSD",
    },
    "hotkeys": {
        "toggle": "Ctrl+Alt+M",
        "anchor": "Ctrl+Alt+P",
        "background": "Ctrl+Alt+B",
        "quit": "Ctrl+Alt+Q",
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data = deep_merge(DEFAULTS, {})
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.data = deep_merge(DEFAULTS, raw)
        except FileNotFoundError:
            self.save()
        except (json.JSONDecodeError, OSError):
            self.data = deep_merge(DEFAULTS, {})
            self.save()

    def save(self) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(parent, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # 便捷访问
    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]
