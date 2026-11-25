# -*- coding: utf-8 -*-
"""帧率采集：把 PresentMon 的 CSV 流解析成每个进程的 FPS。

PresentMon 走 ETW 抓 DXGI/D3D Present 事件，不需要往游戏里注入任何 DLL，
安全性和兼容性都比 hook 强（MSI Afterburner 的 RTSS 是注入式）。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import defaultdict, deque

CREATE_NO_WINDOW = 0x08000000


class FpsTracker:
    """按进程维护最近 window_s 秒的呈现帧，算出 FPS / 帧生成时间。"""

    def __init__(self, window_s: float = 1.0) -> None:
        self.window_s = float(window_s)
        self._lock = threading.Lock()
        self._frames: dict[int, deque] = defaultdict(deque)
        self._names: dict[int, str] = {}
        self._last: dict[int, float] = {}

    def feed(self, pid: int, app: str, dt_ms: float) -> None:
        if pid <= 0 or dt_ms <= 0 or dt_ms > 10000:
            return
        now = time.monotonic()
        budget = max(0.2, self.window_s) * 1000.0
        with self._lock:
            q = self._frames[pid]
            q.append((now, dt_ms))
            self._names[pid] = app or self._names.get(pid, "")
            self._last[pid] = now
            # 按帧自身时长裁剪窗口，比看墙钟更抗 PresentMon 的批量输出
            total = sum(f[1] for f in q)
            while len(q) > 2 and total > budget:
                total -= q.popleft()[1]

    def fps(self, pid: int) -> float | None:
        """窗口内帧数 / 窗口总时长。用帧时长求和，不受读取延迟影响。"""
        now = time.monotonic()
        with self._lock:
            q = self._frames.get(pid)
            if not q or len(q) < 2:
                return None
            if now - self._last.get(pid, 0.0) > 1.2:   # 已经不出帧了
                return None
            total = sum(f[1] for f in q)
            if total <= 0:
                return None
            return 1000.0 * len(q) / total

    def last_seen(self, pid: int) -> float:
        with self._lock:
            return self._last.get(pid, 0.0)

    def app_name(self, pid: int) -> str:
        with self._lock:
            return self._names.get(pid, "")

    def best(self, prefer_pid: int = 0, max_age: float = 2.0) -> tuple[int, float] | None:
        """优先返回前台进程；前台没在出帧就返回最近最活跃的那个。"""
        now = time.monotonic()
        with self._lock:
            items = [(pid, self._last.get(pid, 0.0), len(q))
                     for pid, q in self._frames.items() if q]
        items = [i for i in items if now - i[1] <= max_age]
        if not items:
            return None
        if prefer_pid:
            for pid, _t, n in items:
                if pid == prefer_pid and n >= 2:
                    value = self.fps(pid)
                    if value:
                        return pid, value
        pid = max(items, key=lambda i: (i[2], i[1]))[0]
        value = self.fps(pid)
        if not value:
            return None
        return pid, value

    def prune(self) -> None:
        now = time.monotonic()
        with self._lock:
            dead = [pid for pid, t in self._last.items() if now - t > 30]
            for pid in dead:
                self._frames.pop(pid, None)
                self._names.pop(pid, None)
                self._last.pop(pid, None)


class PresentMonRunner(threading.Thread):
    """子进程跑 PresentMon，把 stdout 的 CSV 行喂给 FpsTracker。"""

    def __init__(self, exe: str, tracker: FpsTracker, on_status,
                 session_name: str = "PerfOSD") -> None:
        super().__init__(daemon=True)
        self.exe = exe
        self.tracker = tracker
        self.on_status = on_status
        self.session_name = session_name
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self.status = ""
        self.cols: dict[str, int] | None = None
        self.frames_seen = 0

    # ---------------------------------------------------------------- 控制
    def stop(self) -> None:
        self._stop.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def _set_status(self, text: str) -> None:
        if text != self.status:
            self.status = text
            try:
                self.on_status(text)
            except Exception:
                pass

    # ---------------------------------------------------------------- 主循环
    def run(self) -> None:
        fails = 0
        while not self._stop.is_set():
            if not os.path.exists(self.exe):
                self._set_status(f"缺少 {os.path.basename(self.exe)}")
                time.sleep(5)
                continue
            cmd = [
                self.exe,
                "--output_stdout",
                "--no_console_stats",
                "--stop_existing_session",
                "--session_name", self.session_name,
            ]
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    cwd=os.path.dirname(self.exe) or None,
                )
            except OSError as e:
                self._set_status(f"启动 PresentMon 失败: {e}")
                time.sleep(3)
                continue

            self.cols = None
            self._set_status("启动抓帧会话…")
            try:
                self._read_loop()
            except Exception:
                pass

            rc = self._proc.poll() if self._proc else -1
            self._proc = None
            if self._stop.is_set():
                break
            fails = fails + 1 if rc not in (0, None) else 0
            if fails >= 3:
                self._set_status("PresentMon 反复退出（多半需要管理员权限）")
                time.sleep(8)
                fails = 0
            else:
                self._set_status("抓帧会话中断，1 秒后重连…")
                time.sleep(1)

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        stream = self._proc.stdout
        for raw in iter(stream.readline, b""):
            if self._stop.is_set():
                break
            try:
                line = raw.decode("utf-8", "replace").lstrip("\ufeff").strip()
            except Exception:
                continue
            if not line:
                continue
            if "," not in line:
                low = line.lower()
                if "access denied" in low or "administrative" in low:
                    self._set_status("FPS 需要管理员权限")
                elif "error:" in low:
                    self._set_status(line[:80])
                continue
            cols = self.cols
            if cols is None:
                if "application" in line.lower() and "processid" in line.lower():
                    self._parse_header(line)
                    self._set_status("抓帧中")
                continue
            self._parse_row(line)

    def _parse_header(self, line: str) -> None:
        names = [c.strip().lower() for c in line.split(",")]
        cols: dict[str, int] = {}
        for i, name in enumerate(names):
            if name in ("application", "app"):
                cols["app"] = i
            elif name == "processid":
                cols["pid"] = i
            elif name in ("msbetweenpresents", "msbetweenpresent"):
                cols["dt"] = i
        if "pid" in cols and "dt" in cols:
            self.cols = cols

    def _parse_row(self, line: str) -> None:
        cols = self.cols
        if not cols:
            return
        parts = line.split(",")
        need = max(cols.values())
        if len(parts) <= need:
            return
        try:
            pid = int(parts[cols["pid"]])
        except ValueError:
            return
        try:
            dt = float(parts[cols["dt"]])
        except ValueError:
            return
        app = parts[cols["app"]] if "app" in cols else ""
        self.tracker.feed(pid, app, dt)
        self.frames_seen += 1
