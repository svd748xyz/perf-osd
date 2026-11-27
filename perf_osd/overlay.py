# -*- coding: utf-8 -*-
"""悬浮层：逐像素 alpha、永远点击穿透、始终置顶的无边框窗口。

关键技术点：
  * WS_EX_LAYERED + UpdateLayeredWindow(AC_SRC_ALPHA) → 真透明叠加，不是抠色
  * WS_EX_TRANSPARENT 常驻 + WS_EX_NOACTIVATE → 鼠标事件整块穿过去，下面该点哪儿还点哪儿
  * WS_EX_TOOLWINDOW → 任务栏和 Alt-Tab 里都不出现，只在右侧托盘留一个图标
  * 永远不会解锁拖动：这个窗口从头到尾不接受任何鼠标交互
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes as w

from PIL import Image, ImageDraw, ImageFont

from . import win32
from .win32 import (SW_HIDE, SW_SHOWNOACTIVATE, WM_CLOSE, WM_COMMAND, WM_DESTROY,
                    WM_DISPLAYCHANGE, WM_HOTKEY, WM_SYSCOMMAND, WM_TIMER,
                    WM_TRAYICON, WS_EX_LAYERED, WS_EX_NOACTIVATE,
                    WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP,
                    user32)

log = logging.getLogger(__name__)

# 等宽字体负责数字对齐；中文（例如“需管理员”）必须有中文字形，否则会变成豆腐块
FONT_MONO = [
    (r"C:\Windows\Fonts\consolab.ttf", r"C:\Windows\Fonts\consola.ttf"),
    (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"),
]
FONT_CJK = [
    (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc"),
    (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simhei.ttf"),
    (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttc"),
]

COLORS = {
    "label": (158, 164, 176, 255),
    "value": (240, 244, 252, 255),
    "dim": (122, 128, 140, 255),
    "accent": (108, 226, 255, 255),
    "warn": (255, 190, 84, 255),
    "danger": (255, 98, 98, 255),
    "good": (126, 231, 168, 255),
    "border": (255, 255, 255, 34),
    "border_live": (108, 226, 255, 200),
    "bg": (10, 11, 14, 210),
}


def _needs_cjk(text: str) -> bool:
    return any(ord(ch) > 0x2E7F for ch in text or "")


def _font(size: int, bold: bool = False, cjk: bool = False):
    table = FONT_CJK if cjk else FONT_MONO
    for reg, bold_path in table:
        path = bold_path if bold else reg
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _premultiplied_bgra(img: Image.Image) -> bytes:
    """UpdateLayeredWindow 要预乘 alpha 的 BGRA。

    Pillow 不能直接把 RGBA pack 成 BGRA，所以手动预乘后换通道顺序。
    """
    from PIL import ImageChops

    im = img.convert("RGBA")
    r, g, b, a = im.split()
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    return Image.merge("RGBA", (b, g, r, a)).tobytes("raw", "BGRA")


class Overlay:
    def __init__(self, cfg: dict, on_quit=None,
                 on_restart_admin=None, on_open_config=None, on_changed=None) -> None:
        win32.set_dpi_aware()          # 必须在读 DPI / 屏幕尺寸之前
        self.cfg = cfg
        self.on_quit = on_quit
        self.on_restart_admin = on_restart_admin
        self.on_open_config = on_open_config
        self.on_changed = on_changed
        self.background = bool(cfg.get("background", True))

        self.hwnd = None
        self.surface: win32.LayeredSurface | None = None
        self._wndproc_ref = None
        self._cls_atom = None
        self._lock = threading.Lock()
        self.rows: list[dict] = []
        self.visible = bool(cfg.get("visible", True))
        self.size = (10, 10)
        self._dirty = True
        self._tray = None
        self._icon = None
        self._menu_ids: dict[int, object] = {}
        self._font_cache: dict[tuple[int, bool], object] = {}
        self._glyph_cache: dict[int, tuple[int, int]] = {}

        self.dpi = 96          # create() 拿到窗口后再按真实显示器 DPI 校正
        self.scale = 1.0

    # ---------------------------------------------------------------- 生命周期
    def create(self) -> None:
        win32.set_dpi_aware()
        hinst = win32.kernel32.GetModuleHandleW(None)
        class_name = "PerfOSDOverlayWnd"
        self._wndproc_ref = win32.WNDPROC(self._wndproc)
        wc = win32.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        self._cls_atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not self._cls_atom:
            raise ctypes.WinError(ctypes.get_last_error())

        # TOOLWINDOW：任务栏不给按钮、Alt-Tab 也不列出来，入口只剩右侧托盘图标
        ex = (WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE
              | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
        self.hwnd = user32.CreateWindowExW(
            ex, class_name, "PerfOSD 性能悬浮窗", WS_POPUP,
            0, 0, 200, 120, None, None, hinst, None
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self.dpi = win32.dpi_for_window(self.hwnd)
        self.scale = max(0.75, self.dpi / 96.0)
        log.info("overlay dpi=%s scale=%.2f", self.dpi, self.scale)

        self.surface = win32.LayeredSurface()
        self._register_hotkeys()
        self._build_tray()

        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if self.visible else SW_HIDE)
        user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0,
                            win32.SWP_NOMOVE | win32.SWP_NOSIZE | win32.SWP_NOACTIVATE)
        self.render(force=True)

        interval = max(40, int(self.cfg.get("refresh_ms", 100)))
        user32.SetTimer(self.hwnd, 1, interval, None)
        log.info("overlay created hwnd=%s dpi=%s", self.hwnd, self.dpi)

    def run(self) -> None:
        msg = w.MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def destroy(self) -> None:
        try:
            if self.hwnd:
                user32.KillTimer(self.hwnd, 1)
                for hid in (getattr(self, "_hk_quit", 0),
                            getattr(self, "_hk_toggle", 0),
                            getattr(self, "_hk_anchor", 0),
                            getattr(self, "_hk_bg", 0)):
                    if hid:
                        user32.UnregisterHotKey(self.hwnd, hid)
                user32.DestroyWindow(self.hwnd)
        except Exception:
            pass
        try:
            if self._tray:
                self._tray.remove()
            if self.surface:
                self.surface.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- 外部数据
    def set_rows(self, rows: list[dict]) -> None:
        with self._lock:
            self.rows = rows
            self._dirty = True

    def toggle_visible(self) -> None:
        self.visible = not self.visible
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if self.visible else SW_HIDE)
        if not self.visible:
            self._tray_tip("PerfOSD 已隐藏（Ctrl+Alt+M 呼出）")

    def toggle_background(self) -> None:
        """面板背景（蒙版）开 / 关。关掉就是纯文字贴着桌面，一点不挡画面。"""
        self.background = not self.background
        self.cfg["background"] = self.background
        self._dirty = True
        self.render(force=True)
        self._refresh_menu()
        self._tray_tip("背景已关：纯文字显示" if not self.background else "背景已开：半透明面板")
        if self.on_changed:
            try:
                self.on_changed()
            except Exception:
                pass

    ANCHORS = ["top-right", "bottom-right", "bottom-left", "top-left"]

    def cycle_anchor(self) -> None:
        """窗口不接受鼠标，所以换位置靠热键循环四个角（会写回配置）。"""
        cur = str(self.cfg.get("anchor", "top-right"))
        try:
            idx = self.ANCHORS.index(cur)
        except ValueError:
            idx = 0
        nxt = self.ANCHORS[(idx + 1) % len(self.ANCHORS)]
        self.cfg["anchor"] = nxt
        self.cfg["pos"] = None          # 绝对坐标优先，不清掉锚点不生效
        self._dirty = True
        self.render(force=True)
        self._refresh_menu()
        self._tray_tip(f"已移到 {nxt}")
        if self.on_changed:
            try:
                self.on_changed()
            except Exception:
                pass

    # ---------------------------------------------------------------- 窗口消息
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TIMER:
                if self._dirty:
                    self.render()
                return 0
            if msg == WM_HOTKEY:
                if wparam == self._hk_toggle:
                    self.toggle_visible()
                elif wparam == self._hk_anchor:
                    self.cycle_anchor()
                elif wparam == self._hk_bg:
                    self.toggle_background()
                elif wparam == self._hk_quit:
                    self._quit()
                return 0
            if msg == WM_COMMAND:
                cb = self._menu_ids.get(wparam & 0xFFFF)
                if cb:
                    cb()
                return 0
            if msg == WM_TRAYICON:
                kind = (lparam & 0xFFFF) if lparam else 0
                if kind in (0x0205, 0x007B):      # 右键 / 上下文菜单
                    self._tray.show_menu()
                elif kind == 0x0203:               # 双击
                    self.toggle_visible()
                return 0
            if msg == WM_SYSCOMMAND:
                # 任何来源的最小化（Win+D、显示桌面）都不许把面板藏起来；要关走托盘菜单
                if (wparam & 0xFFF0) == 0xF020:
                    return 0
            if msg == WM_CLOSE:
                self._quit()
                return 0
            if msg == WM_DISPLAYCHANGE:
                self.render(force=True)
                return 0
            if msg in (WM_DESTROY,):
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("wndproc error msg=%s", msg)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _quit(self) -> None:
        if self.on_quit:
            try:
                self.on_quit()
            except Exception:
                pass
        user32.PostQuitMessage(0)

    # ---------------------------------------------------------------- 托盘
    def _tray_tip(self, text: str) -> None:
        try:
            self._tray.nid.szTip = text[:127]
            ctypes.windll.shell32.Shell_NotifyIconW(win32.NIM_MODIFY,
                                                    ctypes.byref(self._tray.nid))
        except Exception:
            pass

    def _build_tray(self) -> None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(here, "assets", "icon.ico")
        self._icon = win32.Icon(ico)
        self._menu_ids = {cid: cb for cid, _l, cb in self._menu_items() if cb}
        self._tray = win32.TrayIcon(self.hwnd, self._icon, "PerfOSD 性能悬浮窗",
                                    self._menu_items())
        if not self._tray.add():
            log.warning("托盘图标添加失败")

    def _menu_items(self) -> list[tuple[int, str, object]]:
        hk = getattr(self, "hk_text", {})

        def label(text: str, action: str) -> str:
            hot = hk.get(action)
            return f"{text} ({hot})" if hot else text

        return [
            (101, label("显示 / 隐藏", "toggle"), self.toggle_visible),
            (102, label("换到下一个角", "anchor"), self.cycle_anchor),
            (108, label(f"背景：{'开' if self.background else '关（纯文字）'}", "background"),
             self.toggle_background),
            (103, None, None),
            (104, "以管理员身份重启（启用 FPS）", self.on_restart_admin or (lambda: None)),
            (105, "打开配置目录", self.on_open_config or (lambda: None)),
            (106, None, None),
            (107, label("退出", "quit"), self._quit),
        ]

    def _refresh_menu(self) -> None:
        """菜单文字会跟着状态变（背景开/关），所以每次切换后重建一次。"""
        try:
            self._menu_ids = {cid: cb for cid, _l, cb in self._menu_items() if cb}
            if self._tray:
                self._tray.items = self._menu_items()
        except Exception:
            log.exception("刷新菜单失败")

    # ---------------------------------------------------------------- 热键
    FALLBACKS = {
        "toggle": ["Ctrl+Alt+M", "Ctrl+Alt+Shift+M", "Ctrl+Alt+F9", "Ctrl+Shift+F9"],
        "anchor": ["Ctrl+Alt+P", "Ctrl+Alt+Shift+P", "Ctrl+Alt+F10", "Ctrl+Shift+F10"],
        "background": ["Ctrl+Alt+B", "Ctrl+Alt+Shift+B", "Ctrl+Alt+F8", "Ctrl+Shift+F8"],
        "quit": ["Ctrl+Alt+Q", "Ctrl+Alt+Shift+Q", "Ctrl+Alt+F12", "Ctrl+Shift+F12"],
    }
    DEFAULTS_HK = {"toggle": "Ctrl+Alt+M", "anchor": "Ctrl+Alt+P",
                   "background": "Ctrl+Alt+B", "quit": "Ctrl+Alt+Q"}

    def _register_hotkeys(self) -> None:
        hk = self.cfg.get("hotkeys", {}) or {}
        self.hk_text: dict[str, str] = {}
        (self._hk_toggle, self.hk_text["toggle"]) = self._hotkey(
            0xA1, "toggle", hk.get("toggle") or self.DEFAULTS_HK["toggle"])
        (self._hk_anchor, self.hk_text["anchor"]) = self._hotkey(
            0xA2, "anchor", hk.get("anchor") or self.DEFAULTS_HK["anchor"])
        (self._hk_bg, self.hk_text["background"]) = self._hotkey(
            0xA4, "background", hk.get("background") or self.DEFAULTS_HK["background"])
        (self._hk_quit, self.hk_text["quit"]) = self._hotkey(
            0xA3, "quit", hk.get("quit") or self.DEFAULTS_HK["quit"])

    def _hotkey(self, hid: int, action: str, text: str) -> tuple[int, str]:
        """注册热键；被别的软件占了就按备选表往后试。"""
        tried: list[str] = []
        for candidate in [text] + self.FALLBACKS.get(action, []):
            if not candidate or candidate in tried:
                continue
            tried.append(candidate)
            parsed = win32.parse_hotkey(candidate)
            if not parsed:
                continue
            mods, vk = parsed
            if user32.RegisterHotKey(self.hwnd, hid, mods, vk):
                if candidate != text:
                    log.warning("热键 %s 被占用，改用 %s", text, candidate)
                return hid, candidate
        log.warning("动作 %s 没有可用的热键，请用托盘菜单", action)
        return 0, ""

    # ---------------------------------------------------------------- 绘制
    def _glyph_box(self, font):
        """以 anchor='ls' 画数字 0 时的 (上边界, 下边界)，都是相对基线的像素偏移。

        有它才能让字形在行高里真正居中——而不是简单地把基线放在 0.8 行高处。
        """
        key = id(font)
        box = self._glyph_cache.get(key)
        if box is None:
            try:
                b = font.getbbox("0", anchor="ls")
                box = (b[1], b[3])
            except Exception:
                box = (0, 0)
            self._glyph_cache[key] = box
        return box

    def _pick_font(self, size: int, bold: bool, cjk: bool = False):
        key = (size, bold, cjk)
        f = self._font_cache.get(key)
        if f is None:
            f = _font(size, bold, cjk)
            self._font_cache[key] = f
        return f

    def _layout(self, rows: list[dict]):
        base = float(self.cfg.get("font_size", 16)) * self.scale
        fs = max(10, int(round(base)))
        # 超紧凑：行高不再按字号倍数铺开，而是量字形的实际高度再加一点点行距；
        # 左右留白只够描边和圆角，一个多余像素都不留。
        stroke = 0 if self.background else (1 if fs < 30 else 2)
        # 纯文字模式的留白只要刚好够描边：1px 描边留 2px，2px 描边留 3px，多一个像素都不给
        pad = max(5, int(round(fs * 0.26))) if self.background else stroke + 1
        gap_x = int(round(fs * 0.34))
        gap2 = int(round(fs * 0.40))
        lead = max(2, int(round(fs * 0.15)))      # 行与行之间露出的空隙

        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))

        def tw(font, text):
            if not text:
                return 0
            box = probe.textbbox((0, 0), text, font=font)
            return box[2] - box[0]

        geo: list[dict] = []
        y = pad
        for r in rows:
            sc = float(r.get("scale", 1.0) or 1.0)
            fs_r = max(10, int(round(fs * sc)))          # 标题行可以单独缩一号
            fs_rd = max(10, int(round(fs_r * 0.90)))
            lab, val, ext = r.get("label", ""), r.get("value", ""), r.get("extra", "")
            f_lab = self._pick_font(fs_r, True, _needs_cjk(lab))
            f_val = self._pick_font(fs_r, True, _needs_cjk(val))
            f_ext = self._pick_font(fs_rd, False, _needs_cjk(ext))
            g_top, g_bottom = self._glyph_box(f_val)
            # 行高 = 这行字形的实高 + 固定行距，而不是字号的 1.18 倍
            lh = max(11, int(round(g_bottom - g_top)) + lead)
            baseline = y + int(round(lh / 2 - (g_top + g_bottom) / 2))
            geo.append(dict(top=y, lh=lh, baseline=baseline,
                            fonts=(f_lab, f_val, f_ext),
                            w_lab=tw(f_lab, lab), w_val=tw(f_val, val), w_ext=tw(f_ext, ext),
                            label=lab, value=val, extra=ext, row=r))
            y += lh
        height = y + pad

        f_main = self._pick_font(fs, True)
        f_dim = self._pick_font(max(10, int(round(fs * 0.90))), False)
        c0 = max([g["w_lab"] for g in geo] + [tw(f_main, "MEM")])
        c1 = max([g["w_val"] for g in geo] + [tw(f_main, "100%")])
        c2 = max([g["w_ext"] for g in geo] + [0])
        width = pad * 2 + c0 + gap_x + c1 + (gap2 + c2 if c2 else 0)
        return dict(fs=fs, pad=pad, gap_x=gap_x, gap2=gap2,
                    line_h=geo[0]["lh"] if geo else 0, gap_y=0, c0=c0, c1=c1, c2=c2,
                    width=max(40, width), height=max(24, height),
                    f_main=f_main, f_dim=f_dim, stroke=stroke, bg=self.background,
                    geo=geo)

    def _paint(self, rows: list[dict]) -> tuple[Image.Image, dict]:
        m = self._layout(rows)
        width, height = m["width"], m["height"]
        ss = 3  # 超采样只用来把圆角磨平
        alpha = int(255 * float(self.cfg.get("opacity", 0.86)))
        bg = (COLORS["bg"][0], COLORS["bg"][1], COLORS["bg"][2], alpha)
        radius = min(int(self.cfg.get("radius", 10) * self.scale), int(m["fs"] * 0.55))

        if m.get("bg", True):
            panel = Image.new("RGBA", (width * ss, height * ss), (0, 0, 0, 0))
            pd = ImageDraw.Draw(panel)
            pd.rounded_rectangle(
                (0, 0, width * ss - 1, height * ss - 1),
                radius=radius * ss, fill=bg,
                outline=COLORS["border"],
                width=ss,
            )
            img = panel.resize((width, height), Image.LANCZOS)
        else:
            # 纯文字：整张图透明，只留字形 + 描边，一个像素的面板都不占
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        draw = ImageDraw.Draw(img)
        pad = m["pad"]
        v_right = pad + m["c0"] + m["gap_x"] + m["c1"]
        x_extra = v_right + m["gap2"]

        stroke = m.get("stroke", 0)
        # 没有蒙版托底，白字压到白色窗口上会看不清，加一圈黑描边解决
        shadow = dict(stroke_width=stroke, stroke_fill=(0, 0, 0, 200)) if stroke else {}
        for g in m["geo"]:
            f_lab, f_val, f_ext = g["fonts"]
            row = g["row"]
            base_y = g["baseline"]
            draw.text((pad, base_y), g["label"], font=f_lab,
                      fill=row.get("label_color") or COLORS["label"], anchor="ls", **shadow)
            level = row.get("level", 0)
            color = {1: COLORS["warn"], 2: COLORS["danger"], 3: COLORS["accent"],
                     4: COLORS["good"]}.get(level, COLORS["value"])
            draw.text((v_right, base_y), g["value"],
                      font=f_val, fill=color, anchor="rs", **shadow)
            if g["extra"]:
                draw.text((x_extra, base_y), g["extra"],
                          font=f_ext, fill=COLORS["dim"], anchor="ls", **shadow)
        return img, m

    def _place(self, width: int, height: int) -> tuple[int, int]:
        pos = self.cfg.get("pos")
        if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
            return int(pos[0]), int(pos[1])
        sw, sh = win32.screen_size()
        anchor = self.cfg.get("anchor", "top-right")
        mx = int(self.cfg.get("margin_x", 16) * self.scale)
        my = int(self.cfg.get("margin_y", 16) * self.scale)
        x = mx if "left" in anchor else sw - width - mx
        y = my if "top" in anchor else sh - height - my
        return max(0, x), max(0, y)

    def render(self, force: bool = False) -> None:
        if not self.hwnd or not self.surface:
            return
        with self._lock:
            rows = list(self.rows)
            self._dirty = False
        if not rows or not self.visible:
            return
        img, m = self._paint(rows)
        w_, h_ = img.size
        if not getattr(self, "_geo_logged", False):
            self._geo_logged = True
            log.info("首帧 %dx%d fs=%d scale=%.2f 行数=%d",
                     w_, h_, m["fs"], self.scale, len(rows))
        x, y = self._place(w_, h_)
        try:
            self.surface.blit(self.hwnd, _premultiplied_bgra(img), w_, h_, (x, y))
            self.size = (w_, h_)
        except OSError as e:
            log.error("blit failed: %s", e)
