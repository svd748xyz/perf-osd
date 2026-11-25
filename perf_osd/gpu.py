# -*- coding: utf-8 -*-
"""GPU 占用采集：优先 NVML（NVIDIA 专用，最准），退回 PDH 的 GPU Engine 计数器
（Win10 1709+ 通用，任务管理器用的就是这套，A/N/I 三家的驱动都会注册）。"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes as w

REQUIRED = ("util",)


class GpuSample:
    __slots__ = ("util", "mem_util", "vram_used_mb", "vram_total_mb", "temp", "name", "source")

    def __init__(self) -> None:
        self.util = None          # GPU 核心占用 %
        self.mem_util = None      # 显存控制器占用 %
        self.vram_used_mb = None
        self.vram_total_mb = None
        self.temp = None
        self.name = ""
        self.source = ""

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ------------------------------------------------------------------ NVML
class NvmlGpu:
    name = "nvml"

    def __init__(self, index: int = 0) -> None:
        self.ok = False
        self.reason = ""
        self._lib = None
        self._handle = ctypes.c_void_p()
        self._index = index
        try:
            self._lib = self._load()
        except OSError as e:
            self.reason = f"nvml 不可用: {e}"
            return
        if self._lib.nvmlInit_v2() != 0:
            self.reason = "nvmlInit 失败"
            return
        if self._lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(self._handle)) != 0:
            self.reason = "找不到 GPU"
            return
        self.ok = True

    @staticmethod
    def _load():
        candidates = ["nvml.dll"]
        for p in (
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"),
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll",
        ):
            candidates.append(p)
        last = None
        for c in candidates:
            try:
                lib = ctypes.WinDLL(c)
            except OSError as e:
                last = e
                continue
            try:
                lib.nvmlInit_v2.restype = ctypes.c_int
                lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
                    ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
                lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
                lib.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
                lib.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
                lib.nvmlDeviceGetTemperature.restype = ctypes.c_int
                lib.nvmlDeviceGetName.argtypes = [
                    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
                return lib
            except AttributeError as e:
                last = e
                continue
        raise OSError(str(last) if last else "nvml.dll 加载失败")

    def sample(self) -> GpuSample:
        s = GpuSample()
        s.source = "nvml"
        if not self.ok:
            return s
        lib, h = self._lib, self._handle
        try:
            class Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("mem", ctypes.c_uint)]

            u = Util()
            if lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(u)) == 0:
                s.util = float(u.gpu)
                s.mem_util = float(u.mem)

            class Mem(ctypes.Structure):
                _fields_ = [("total", ctypes.c_ulonglong),
                            ("free", ctypes.c_ulonglong),
                            ("used", ctypes.c_ulonglong)]

            m = Mem()
            if lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0:
                s.vram_total_mb = m.total / 1048576.0
                s.vram_used_mb = m.used / 1048576.0

            t = ctypes.c_uint()
            if lib.nvmlDeviceGetTemperature(h, 0, ctypes.byref(t)) == 0 and t.value < 200:
                s.temp = float(t.value)

            if not s.name:
                buf = ctypes.create_string_buffer(96)
                if lib.nvmlDeviceGetName(h, buf, 96) == 0:
                    self._name = buf.value.decode("utf-8", "replace")
            s.name = getattr(self, "_name", "")
        except Exception:
            pass
        return s

    def close(self) -> None:
        try:
            if self._lib:
                self._lib.nvmlShutdown()
        except Exception:
            pass


# ------------------------------------------------------------------ PDH
class _PdhFmtValue(ctypes.Union):
    _fields_ = [
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("longValue", ctypes.c_long),
    ]


class _PdhFmtCounterValue(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("CStatus", ctypes.c_ulong), ("u", _PdhFmtValue)]


class _PdhFmtItem(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PdhFmtCounterValue)]


PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2


class PdhGpu:
    r"""通用 GPU 占用：\GPU Engine(*)\Utilization Percentage 按 3D 引擎聚合。"""

    name = "pdh"

    def __init__(self) -> None:
        self.ok = False
        self.reason = ""
        try:
            self._pdh = ctypes.WinDLL("pdh.dll")
        except OSError as e:
            self.reason = f"pdh.dll 不可用: {e}"
            return
        pdh = self._pdh
        pdh.PdhOpenQueryW.argtypes = [w.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(w.HANDLE)]
        pdh.PdhAddEnglishCounterW.argtypes = [w.HANDLE, w.LPCWSTR, ctypes.c_size_t,
                                             ctypes.POINTER(w.HANDLE)]
        pdh.PdhCollectQueryData.argtypes = [w.HANDLE]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [
            w.HANDLE, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD),
            ctypes.POINTER(ctypes.c_ubyte)]
        pdh.PdhCloseQuery.argtypes = [w.HANDLE]
        for fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData",
                   "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
            getattr(pdh, fn).restype = ctypes.c_ulong

        self._query = w.HANDLE()
        self._counter = w.HANDLE()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
            self.reason = "PdhOpenQuery 失败"
            return
        rc = pdh.PdhAddEnglishCounterW(
            self._query, r"\GPU Engine(*)\Utilization Percentage", 0,
            ctypes.byref(self._counter))
        if rc != 0:
            self.reason = f"GPU Engine 计数器不可用 (0x{rc & 0xFFFFFFFF:08X})"
            return
        pdh.PdhCollectQueryData(self._query)
        time.sleep(0.25)
        pdh.PdhCollectQueryData(self._query)
        self.ok = True

    def sample(self) -> GpuSample:
        s = GpuSample()
        s.source = "pdh"
        if not self.ok:
            return s
        pdh = self._pdh
        if pdh.PdhCollectQueryData(self._query) != 0:
            return s
        size = w.DWORD(0)
        count = w.DWORD(0)
        flags = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        rc = pdh.PdhGetFormattedCounterArrayW(
            self._counter, flags, ctypes.byref(size), ctypes.byref(count), None)
        if rc != PDH_MORE_DATA or size.value == 0:
            return s
        buf = (ctypes.c_ubyte * size.value)()
        rc = pdh.PdhGetFormattedCounterArrayW(
            self._counter, flags, ctypes.byref(size), ctypes.byref(count), buf)
        if rc != 0:
            return s
        per_gpu: dict[str, float] = {}
        items = ctypes.cast(buf, ctypes.POINTER(_PdhFmtItem))
        for i in range(count.value):
            it = items[i]
            nm = it.szName or ""
            if "engtype_3d" not in nm.lower():
                continue
            val = float(it.FmtValue.doubleValue)
            if val != val:  # NaN
                continue
            key = nm.split("_luid_")[0] if "_luid_" in nm else nm
            if "_luid_" in nm:
                parts = nm.split("_luid_")
                if len(parts) > 1:
                    luid = parts[1].split("_phys_")[0]
                    key = luid
            per_gpu[key] = per_gpu.get(key, 0.0) + val
        if per_gpu:
            s.util = min(100.0, max(per_gpu.values()))
        return s

    def close(self) -> None:
        try:
            if self._query:
                self._pdh.PdhCloseQuery(self._query)
        except Exception:
            pass


def make_gpu(backend: str = "auto", index: int = 0):
    """返回 (后端对象, 说明文本)。"""
    backend = (backend or "auto").lower()
    reason = ""
    if backend in ("auto", "nvml"):
        g = NvmlGpu(index)
        if g.ok:
            return g, "NVIDIA NVML"
        reason = g.reason
        if backend == "nvml":
            return None, reason
    p = PdhGpu()
    if p.ok:
        return p, "PDH GPU Engine"
    return None, (reason or p.reason)
