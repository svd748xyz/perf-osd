# -*- coding: utf-8 -*-
"""PerfOSD —— 桌面实时性能悬浮窗（CPU / 内存 / GPU / FPS）。

用法:
    python main.py              正常启动（无控制台）
    python main.py --console    带控制台，输出日志
    python main.py --probe      只采集并打印，不创建悬浮窗（自检用）
    python main.py --elevate    不足管理员权限时自动提权重启（FPS 需要）
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from perf_osd import win32                      # noqa: E402
from perf_osd.config import Config              # noqa: E402
from perf_osd.fps import FpsTracker, PresentMonRunner  # noqa: E402
from perf_osd.gpu import make_gpu               # noqa: E402
from perf_osd.metrics import CpuMeter, MemMeter  # noqa: E402
from perf_osd.overlay import COLORS, Overlay    # noqa: E402

log = logging.getLogger("perfosd")

LEVEL_NORMAL, LEVEL_WARN, LEVEL_DANGER, LEVEL_ACCENT, LEVEL_GOOD = 0, 1, 2, 3, 4
MUTEX_NAME = "Local\\PerfOSD.SingleInstance.v1"


# ------------------------------------------------------------------ 小工具
def setup_logging(console: bool) -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(
        os.path.join(BASE, "perf-osd.log"), encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)


def ensure_icon() -> str:
    """图标只在 perf_osd/icon.py 里定义，这里只负责确保文件存在。"""
    path = os.path.join(BASE, "assets", "icon.ico")
    try:
        from perf_osd.icon import ensure
        return ensure(path)
    except Exception as e:  # 图标不是必需品
        log.warning("生成图标失败: %s", e)
    return path


def single_instance_guard():
    """同名互斥体，避免开了两份互相抢 PresentMon 会话。"""
    h = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return h


def relaunch_as_admin() -> bool:
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    script = os.path.join(BASE, "main.py")
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, f'"{script}" --elevate', BASE, 0)
        return int(rc) > 32
    except Exception as e:
        log.error("提权失败: %s", e)
        return False


def load_level(pct: float | None) -> int:
    if pct is None:
        return LEVEL_NORMAL
    if pct >= 92:
        return LEVEL_DANGER
    if pct >= 80:
        return LEVEL_WARN
    return LEVEL_NORMAL


# ------------------------------------------------------------------ 采样线程
class Sampler(threading.Thread):
    def __init__(self, cfg: Config, overlay: Overlay, tracker: FpsTracker,
                 stop_event: threading.Event) -> None:
        super().__init__(daemon=True)
        self.cfg = cfg
        self.overlay = overlay
        self.tracker = tracker
        self.stop = stop_event
        self.shared = {"fps_status": "", "fps_pid": 0, "fps_app": "",
                       "gpu_desc": "", "fps_admin_blocked": False}

    # -------------------------------------------------------------- 采一次
    def collect(self) -> list[dict]:
        c = self.cfg.data
        cpu_pct = self.cpu.sample()
        mem_pct, mem_used, mem_total = self.mem.sample()

        gpu_util = gpu_temp = None
        vram_used = vram_total = None
        if self.gpu:
            s = self.gpu.sample()
            gpu_util = s.util
            gpu_temp = s.temp
            vram_used = s.vram_used_mb
            vram_total = s.vram_total_mb

        # ---- 帧率：优先前台进程，其次是最近最活跃的进程
        fg_pid, fg_name = win32.foreground_process()
        pin = str(c.get("fps", {}).get("pin_process") or "").strip()
        if pin:
            pinned = self._find_pid(pin)
            if pinned:
                fg_pid, fg_name = pinned, pin
        chosen_pid, fps = None, None
        best = self.tracker.best(prefer_pid=fg_pid, max_age=2.0)
        if best:
            chosen_pid, fps = best
        fps_app = self.tracker.app_name(chosen_pid) if chosen_pid else ""
        frametime = (1000.0 / fps) if fps else None

        rows: list[dict] = []

        if c.get("show_app", True) and fps_app:
            name = fps_app
            if name.lower().endswith(".exe"):
                name = name[:-4]
            rows.append({
                "label": name[:13],
                "value": "",
                "extra": "",
                "level": LEVEL_NORMAL,
                "label_color": COLORS["dim"],
                "scale": 0.82,          # 标题行缩一号，省一截左列宽度
            })

        rows.append({"label": "CPU", "value": f"{cpu_pct:3.0f}%", "extra": "",
                     "level": load_level(cpu_pct)})

        mem_extra = f"{mem_used / 1024:4.1f}/{mem_total / 1024:.0f}G"
        rows.append({"label": "MEM", "value": f"{mem_pct:3.0f}%",
                     "extra": mem_extra, "level": load_level(mem_pct)})

        if self.gpu:
            gpu_extra = ""
            if gpu_temp is not None and c.get("show_temp", True):
                gpu_extra = f"{gpu_temp:.0f}°C"
            rows.append({"label": "GPU",
                         "value": f"{gpu_util:3.0f}%" if gpu_util is not None else "  --",
                         "extra": gpu_extra, "level": load_level(gpu_util)})
            if (c.get("show_vram", True) and vram_total
                    and vram_used is not None and vram_total > 0):
                used_g = vram_used / 1024.0
                total_g = vram_total / 1024.0
                rows.append({"label": "VRAM", "value": f"{used_g:4.1f}G",
                             "extra": f"/{total_g:.1f}G",
                             "level": LEVEL_NORMAL})
        else:
            rows.append({"label": "GPU", "value": "  --", "extra": "", "level": LEVEL_NORMAL})

        if fps and c.get("fps", {}).get("enabled", True):
            extra = f"{frametime:.1f}ms" if (frametime and c.get("show_frametime", True)) else ""
            rows.append({"label": "FPS", "value": f"{fps:3.0f}", "extra": extra,
                         "level": LEVEL_ACCENT})
        else:
            extra = ""
            if self.shared.get("fps_admin_blocked"):
                extra = "需管理员"
            rows.append({"label": "FPS", "value": "  --", "extra": extra,
                         "level": LEVEL_NORMAL})
        return rows

    def _find_pid(self, name: str) -> int:
        """按 exe 名找 pid；枚举全进程不便宜，缓存 5 秒。"""
        name = name.lower()
        now = time.monotonic()
        cache = getattr(self, "_pin_cache", None)
        if cache and cache[0] == name and now - cache[2] < 5.0:
            if not cache[1] or win32.process_name(cache[1]):
                return cache[1]
        pid = 0
        for p, exe in win32.list_processes().items():
            if exe.lower() == name:
                pid = p
                break
        self._pin_cache = (name, pid, now)
        return pid

    def run(self) -> None:
        self.cpu = CpuMeter()
        self.mem = MemMeter()
        gcfg = self.cfg.data.get("gpu", {})
        self.gpu, desc = make_gpu(gcfg.get("backend", "auto"), int(gcfg.get("index", 0)))
        self.shared["gpu_desc"] = desc
        log.info("GPU 后端: %s (ok=%s)", desc, bool(self.gpu))
        interval = max(0.1, float(self.cfg.data.get("sample_ms", 500)) / 1000.0)
        # 预热：第一次采样数值没意义
        self.cpu.sample()
        self.mem.sample()
        n = 0
        while not self.stop.is_set():
            try:
                self.overlay.set_rows(self.collect())
            except Exception:
                log.exception("采样失败")
            if n % 20 == 0:
                self.tracker.prune()
            n += 1
            self.stop.wait(interval)


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="PerfOSD 性能悬浮窗")
    ap.add_argument("--console", action="store_true", help="日志同时打到控制台")
    ap.add_argument("--probe", action="store_true", help="只打印采样值，不开窗")
    ap.add_argument("--elevate", action="store_true", help="需要时提权重启")
    ap.add_argument("--no-elevate", action="store_true", help="禁止自动提权")
    args = ap.parse_args()

    setup_logging(args.console or args.probe)
    ensure_icon()

    if args.elevate and not win32.is_admin() and not args.no_elevate:
        if relaunch_as_admin():
            log.info("已请求管理员权限，本进程退出")
            return 0
        log.warning("提权被拒绝，以普通权限继续（FPS 将不可用）")

    cfg = Config(os.path.join(BASE, "config.json"))

    if args.probe:
        return probe(cfg)

    guard = single_instance_guard()
    if guard is None:
        log.warning("已经有一个 PerfOSD 在运行")
        return 0

    admin = win32.is_admin()
    log.info("启动: admin=%s dpi=%s", admin, win32.get_dpi())

    stop = threading.Event()
    tracker = FpsTracker(cfg.data["fps"].get("window_s", 1.0))

    def on_quit():
        stop.set()

    def on_restart_admin():
        if win32.is_admin():
            return
        if relaunch_as_admin():
            stop.set()
            ctypes.windll.user32.PostQuitMessage(0)

    def on_open_config():
        os.startfile(BASE)

    overlay = Overlay(cfg.data, on_quit=on_quit,
                      on_restart_admin=on_restart_admin, on_open_config=on_open_config,
                      on_changed=cfg.save)
    overlay.create()

    sampler = Sampler(cfg, overlay, tracker, stop)
    sampler.start()

    runner = None
    fcfg = cfg.data["fps"]
    if fcfg.get("enabled", True):
        if admin:
            exe = os.path.join(BASE, fcfg.get("presentmon", "tools/PresentMon.exe"))
            runner = PresentMonRunner(
                exe, tracker,
                lambda s: sampler.shared.__setitem__("fps_status", s),
                session_name=fcfg.get("session_name", "PerfOSD"),
            )
            runner.start()
            log.info("PresentMon 已启动: %s", exe)
        else:
            sampler.shared["fps_admin_blocked"] = True
            log.warning("未提权，FPS 采集停用")

    try:
        overlay.run()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if runner:
            runner.stop()
        overlay.destroy()
        cfg.save()
        log.info("已退出")
    return 0


def probe(cfg: Config) -> int:
    """自检：把四个指标连采 6 次打印出来。"""
    cpu, mem = CpuMeter(), MemMeter()
    g, desc = make_gpu(cfg.data.get("gpu", {}).get("backend", "auto"))
    print(f"admin={win32.is_admin()} dpi={win32.get_dpi()} screen={win32.screen_size()}")
    print(f"gpu backend: {desc}")
    cpu.sample()
    for i in range(6):
        time.sleep(0.4)
        cp = cpu.sample()
        mp, mu, mt = mem.sample()
        line = f"CPU {cp:5.1f}%  MEM {mp:5.1f}% ({mu / 1024:.1f}/{mt / 1024:.1f}G)"
        if g:
            s = g.sample()
            line += f"  GPU {s.util or 0:5.1f}%  {s.temp or 0:.0f}C"
            if s.vram_total_mb:
                line += f"  VRAM {s.vram_used_mb / 1024:.1f}/{s.vram_total_mb / 1024:.1f}G"
        print(line)
    if g:
        g.close()
    return 0


def _fatal(exc: BaseException) -> None:
    """pythonw 下没有控制台，启动失败必须弹个框，不然用户只看到什么都没发生。"""
    import traceback
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error("启动失败: %s", text)
    try:
        ctypes.windll.user32.MessageBoxW(
            0, f"PerfOSD 启动失败：\n\n{exc}\n\n详情见 {os.path.join(BASE, 'perf-osd.log')}",
            "PerfOSD", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        import PIL  # noqa: F401
    except ImportError:
        _fatal(RuntimeError("缺少 Pillow，请先执行: pip install pillow"))
        sys.exit(1)
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001
        _fatal(e)
        sys.exit(1)
