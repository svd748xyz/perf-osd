# -*- coding: utf-8 -*-
"""Win32 底层封装：DPI、分层窗口、DIB 位图、热键、托盘、后台进程查询。

全部走 ctypes，不依赖 pywin32。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

# ---------------------------------------------------------------- 常量
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000

WS_VISIBLE = 0x10000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0

BI_RGB = 0

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_PAINT = 0x000F
WM_TIMER = 0x0113
WM_HOTKEY = 0x0312
WM_COMMAND = 0x0111
WM_SYSCOMMAND = 0x0112
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONDBLCLK = 0x0203
WM_DISPLAYCHANGE = 0x007E
WM_EXITSIZEMOVE = 0x0232
WM_NCLBUTTONDOWN = 0x00A1
WM_RBUTTONUP = 0x0205
HTCAPTION = 2

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 20

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NOTIFYICON_VERSION_4 = 4

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
TPM_LEFTALIGN = 0x0000

SM_CXSCREEN = 0
SM_CYSCREEN = 1

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", w.DWORD),
        ("Data2", w.WORD),
        ("Data3", w.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("hWnd", w.HWND),
        ("uID", w.UINT),
        ("uFlags", w.UINT),
        ("uCallbackMessage", w.UINT),
        ("hIcon", w.HICON),
        ("szTip", w.WCHAR * 128),
        ("dwState", w.DWORD),
        ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256),
        ("uVersion", w.UINT),
        ("szInfoTitle", w.WCHAR * 64),
        ("dwInfoFlags", w.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", w.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.UINT),
        ("style", w.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE),
        ("hIcon", w.HICON),
        ("hCursor", w.HANDLE),
        ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
        ("hIconSm", w.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


# ---------------------------------------------------------------- 原型声明
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = w.ATOM
user32.CreateWindowExW.argtypes = [
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID,
]
user32.CreateWindowExW.restype = w.HWND
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [w.HWND]
user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.UpdateLayeredWindow.argtypes = [
    w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE),
    w.HDC, ctypes.POINTER(w.POINT), w.DWORD,
    ctypes.POINTER(BLENDFUNCTION), w.DWORD,
]
user32.UpdateLayeredWindow.restype = w.BOOL
user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, w.UINT]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, w.LPVOID]
user32.KillTimer.argtypes = [w.HWND, ctypes.c_size_t]
user32.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
user32.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
try:
    user32.GetDpiForSystem.restype = w.UINT
    user32.GetDpiForWindow.argtypes = [w.HWND]
    user32.GetDpiForWindow.restype = w.UINT
except AttributeError:
    pass
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.ReleaseCapture.argtypes = []
user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.CreatePopupMenu.restype = w.HMENU
user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
user32.TrackPopupMenuEx.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int,
                                    w.HWND, w.LPVOID]
user32.DestroyMenu.argtypes = [w.HMENU]
user32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int,
                              ctypes.c_int, w.UINT]
user32.LoadImageW.restype = w.HANDLE
user32.DestroyIcon.argtypes = [w.HICON]
user32.SystemParametersInfoW.argtypes = [w.UINT, w.UINT, w.LPVOID, w.UINT]

gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.CreateDIBSection.argtypes = [w.HDC, ctypes.POINTER(BITMAPINFO), w.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
gdi32.CreateDIBSection.restype = w.HBITMAP
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]

kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HINSTANCE
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR,
                                               ctypes.POINTER(w.DWORD)]
kernel32.GetCurrentProcess.restype = w.HANDLE
kernel32.GetCurrentProcessId.restype = w.DWORD


if hasattr(user32, "SetWindowLongPtrW"):
    _set_style = user32.SetWindowLongPtrW
else:  # 32 位 Python
    _set_style = user32.SetWindowLongW
_set_style.argtypes = [w.HWND, ctypes.c_int, ctypes.c_void_p]
_set_style.restype = ctypes.c_void_p

_get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
_get_style.argtypes = [w.HWND, ctypes.c_int]
_get_style.restype = ctypes.c_void_p


# ---------------------------------------------------------------- 基础工具
def set_dpi_aware() -> None:
    """开启 Per-Monitor DPI 感知，保证在缩放屏上像素级清晰、坐标不用换算。"""
    try:
        # PER_MONITOR_AWARE_V2 = -4
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def get_dpi() -> int:
    """系统 DPI。GetDeviceCaps 在刚设置完感知模式时会给出旧值，所以优先用新 API。"""
    try:
        return int(user32.GetDpiForSystem()) or 96
    except Exception:
        pass
    try:
        hdc = user32.GetDC(None)
        dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(None, hdc)
        return dpi or 96
    except Exception:
        return 96


def dpi_for_window(hwnd) -> int:
    """窗口所在显示器的 DPI，最靠谱的一条路。"""
    try:
        dpi = int(user32.GetDpiForWindow(hwnd))
        if dpi:
            return dpi
    except Exception:
        pass
    return get_dpi()


def screen_size() -> tuple[int, int]:
    return (user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN))


def cursor_pos() -> tuple[int, int]:
    pt = w.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def is_admin() -> bool:
    """是否已提权（PresentMon 采集 ETW 需要管理员）。"""
    try:
        advapi32 = ctypes.WinDLL("advapi32")
        shell32 = ctypes.WinDLL("shell32")
        shell32.IsUserAnAdmin.restype = w.BOOL
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def foreground_process() -> tuple[int, str]:
    """返回前台窗口的 (pid, exe 名)。无前台窗口时返回 (0, '')。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return 0, ""
    return pid.value, process_name(int(pid.value))


def process_name(pid: int) -> str:
    if not pid:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def list_processes() -> dict[int, str]:
    """pid -> exe 名（仅枚举用户有权限查询的进程）。"""
    psapi.EnumProcesses.argtypes = [ctypes.POINTER(w.DWORD), w.DWORD,
                                    ctypes.POINTER(w.DWORD)]
    cap = 4096
    while True:
        arr = (w.DWORD * cap)()
        need = w.DWORD()
        if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(need)):
            return {}
        count = need.value // ctypes.sizeof(w.DWORD)
        if count < cap:
            break
        cap *= 2
        if cap > 65536:
            break
    out: dict[int, str] = {}
    for i in range(count):
        pid = int(arr[i])
        if pid <= 0:
            continue
        name = process_name(pid)
        if name:
            out[pid] = name
    return out


# ---------------------------------------------------------------- 分层窗口
class LayeredSurface:
    """用 DIB Section + UpdateLayeredWindow 画逐像素 alpha 的悬浮层。"""

    def __init__(self) -> None:
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        self.hbmp = None
        self.old_bmp = None
        self.bits = None
        self.width = 0
        self.height = 0
        self._bmi = BITMAPINFO()

    def _ensure(self, width: int, height: int) -> None:
        if self.hbmp and self.width == width and self.height == height:
            return
        self.release_bitmap()
        bi = self._bmi
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = width
        bi.bmiHeader.biHeight = -height  # 负数 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = BI_RGB
        bi.bmiHeader.biSizeImage = width * height * 4
        bits = ctypes.c_void_p()
        self.hbmp = gdi32.CreateDIBSection(
            self.screen_dc, ctypes.byref(bi), DIB_RGB_COLORS,
            ctypes.byref(bits), None, 0
        )
        if not self.hbmp:
            raise OSError("CreateDIBSection failed")
        self.bits = bits
        self.old_bmp = gdi32.SelectObject(self.mem_dc, self.hbmp)
        self.width, self.height = width, height

    def release_bitmap(self) -> None:
        if self.hbmp:
            if self.old_bmp:
                gdi32.SelectObject(self.mem_dc, self.old_bmp)
                self.old_bmp = None
            gdi32.DeleteObject(self.hbmp)
            self.hbmp = None
            self.bits = None

    def blit(self, hwnd, data: bytes, width: int, height: int,
             pos: tuple[int, int] | None) -> None:
        """data 必须是预乘 alpha 的 BGRA 原始字节。"""
        self._ensure(width, height)
        ctypes.memmove(self.bits, data, len(data))
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        size = w.SIZE(width, height)
        pt_src = w.POINT(0, 0)
        if pos is None:
            pt_dst = None
        else:
            pt_dst = w.POINT(int(pos[0]), int(pos[1]))
        ok = user32.UpdateLayeredWindow(
            hwnd, self.screen_dc, pt_dst, ctypes.byref(size),
            self.mem_dc, ctypes.byref(pt_src), 0,
            ctypes.byref(blend), ULW_ALPHA,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        self.release_bitmap()
        if self.mem_dc:
            gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = None
        if self.screen_dc:
            user32.ReleaseDC(None, self.screen_dc)
            self.screen_dc = None


# ---------------------------------------------------------------- 消息与托盘
def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+M' -> (mods, vk)。解析失败返回 None。"""
    if not text:
        return None
    mods = MOD_NOREPEAT
    vk = None
    table = {
        "CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
        "ALT": MOD_ALT, "SHIFT": MOD_SHIFT, "WIN": MOD_WIN,
    }
    for part in str(text).replace(" ", "").split("+"):
        up = part.upper()
        if up in table:
            mods |= table[up]
        elif len(part) == 1:
            vk = ord(part.upper())
        elif up.startswith("F") and up[1:].isdigit():
            n = int(up[1:])
            if 1 <= n <= 24:
                vk = 0x70 + n - 1
        elif up in ("ESC", "ESCAPE"):
            vk = 0x1B
        elif up in ("ENTER", "RETURN"):
            vk = 0x0D
        else:
            return None
    if vk is None:
        return None
    return mods, vk


class Icon:
    """从 .ico 文件加载托盘图标。"""

    def __init__(self, path: str) -> None:
        self.hwnd_icon = None
        if path and os.path.exists(path):
            self.hwnd_icon = user32.LoadImageW(
                None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
        if not self.hwnd_icon:
            self.hwnd_icon = user32.LoadIconW(None, ctypes.c_wchar_p(32512))  # IDI_APPLICATION

    def close(self) -> None:
        if self.hwnd_icon:
            user32.DestroyIcon(self.hwnd_icon)
            self.hwnd_icon = None


class TrayIcon:
    """系统托盘图标 + 右键菜单。菜单命令通过 callback 回传。"""

    def __init__(self, hwnd: int, icon: Icon, tip: str,
                 items: list[tuple[int, str, object]], uid: int = 1) -> None:
        self.hwnd = hwnd
        self.uid = uid
        self.items = items  # [(id, label_or_None, cb)]，label 为 None 表示分隔线
        self.nid = NOTIFYICONDATAW()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = hwnd
        self.nid.uID = uid
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAYICON
        self.nid.hIcon = icon.hwnd_icon
        self.nid.szTip = tip[:127]
        self.added = False

    def add(self) -> bool:
        from ctypes import windll  # noqa: F401  (仅确保加载)
        ok = ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))
        self.added = bool(ok)
        return self.added

    def remove(self) -> None:
        if self.added:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.added = False

    def show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        try:
            for cid, label, _cb in self.items:
                if label is None:
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                else:
                    user32.AppendMenuW(menu, MF_STRING, cid, label)
            pt = w.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self.hwnd)
            user32.TrackPopupMenuEx(
                menu, TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_BOTTOMALIGN,
                pt.x, pt.y, self.hwnd, None
            )
        finally:
            user32.DestroyMenu(menu)

    def dispatch(self, cmd_id: int) -> bool:
        for cid, _label, cb in self.items:
            if cid == cmd_id:
                if cb:
                    cb()
                return True
        return False
