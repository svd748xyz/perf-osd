# -*- coding: utf-8 -*-
"""CPU / 内存占用采集，纯 ctypes，取的是任务管理器同一套数据源。"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes as w

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", w.DWORD), ("dwHighDateTime", w.DWORD)]


def _ft(v: FILETIME) -> int:
    return (v.dwHighDateTime << 32) | v.dwLowDateTime


kernel32.GetSystemTimes.argtypes = [
    ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)
]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", w.DWORD),
        ("dwMemoryLoad", w.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class CpuMeter:
    """GetSystemTimes 做差分：和任务管理器总 CPU 基本一致。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idle = FILETIME()
        self._kernel = FILETIME()
        self._user = FILETIME()
        self._last = None
        self.percent = 0.0
        kernel32.GetSystemTimes(
            ctypes.byref(self._idle), ctypes.byref(self._kernel), ctypes.byref(self._user)
        )
        self._last = (_ft(self._idle), _ft(self._kernel), _ft(self._user))

    def sample(self) -> float:
        with self._lock:
            idle_f, kernel_f, user_f = FILETIME(), FILETIME(), FILETIME()
            kernel32.GetSystemTimes(
                ctypes.byref(idle_f), ctypes.byref(kernel_f), ctypes.byref(user_f)
            )
            cur = (_ft(idle_f), _ft(kernel_f), _ft(user_f))
            p_idle, p_kernel, p_user = self._last
            self._last = cur
            d_idle = cur[0] - p_idle
            d_kernel = cur[1] - p_kernel   # kernel 含 idle
            d_user = cur[2] - p_user
            total = d_kernel + d_user
            if total <= 0:
                return self.percent
            busy = total - d_idle
            pct = max(0.0, min(100.0, busy * 100.0 / total))
            # 轻微平滑，避免数字乱跳
            self.percent = pct if self.percent == 0 else self.percent * 0.55 + pct * 0.45
            return self.percent


class MemMeter:
    def __init__(self) -> None:
        self.percent = 0.0
        self.used_mb = 0.0
        self.total_mb = 0.0

    def sample(self) -> tuple[float, float, float]:
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return self.percent, self.used_mb, self.total_mb
        total = st.ullTotalPhys / 1048576.0
        avail = st.ullAvailPhys / 1048576.0
        self.total_mb = total
        self.used_mb = max(0.0, total - avail)
        self.percent = float(st.dwMemoryLoad)
        return self.percent, self.used_mb, self.total_mb
