"""System telemetry: CPU (total + per-core), RAM, GPU, disk, network rate, battery, uptime.

Polls on its own thread via PolledService. GPU is best-effort: NVIDIA via nvidia-smi
or pynvml if present, otherwise reported as None (widget auto-hides).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time

import psutil

from ui.services.base import PolledService

_OS = platform.system()
_CREATE_NO_WINDOW = 0x08000000 if _OS == "Windows" else 0


class SystemMetricsService(PolledService):
    def __init__(self, interval: float = 2.0):
        super().__init__(interval, name="system")
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._gpu_available: bool | None = None
        # Prime cpu_percent so the first reading isn't 0/garbage.
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    def poll(self) -> dict:
        cpu = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()

        nc = psutil.net_io_counters()
        now = time.time()
        dt = now - self._last_net_t
        if dt > 0:
            up = (nc.bytes_sent - self._last_net.bytes_sent) / dt / (1024 * 1024)
            down = (nc.bytes_recv - self._last_net.bytes_recv) / dt / (1024 * 1024)
        else:
            up = down = 0.0
        self._last_net = nc
        self._last_net_t = now

        disks = self._disks()
        gpu = self._gpu()
        battery = self._battery()

        try:
            uptime = time.time() - psutil.boot_time()
        except Exception:
            uptime = 0.0

        try:
            proc_count = len(psutil.pids())
        except Exception:
            proc_count = 0

        return {
            "cpu": cpu,
            "per_core": per_core,
            "core_count": len(per_core),
            "mem_pct": mem.percent,
            "mem_used_gb": mem.used / (1024 ** 3),
            "mem_total_gb": mem.total / (1024 ** 3),
            "net_up_mbs": max(0.0, up),
            "net_down_mbs": max(0.0, down),
            "disks": disks,
            "gpu": gpu,
            "battery": battery,
            "uptime_sec": uptime,
            "proc_count": proc_count,
        }

    def _disks(self) -> list[dict]:
        out = []
        seen = set()
        try:
            for part in psutil.disk_partitions(all=False):
                if part.mountpoint in seen:
                    continue
                if _OS == "Windows" and "cdrom" in (part.opts or "").lower():
                    continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except (PermissionError, OSError):
                    continue
                seen.add(part.mountpoint)
                out.append({
                    "mount": part.mountpoint,
                    "device": part.device,
                    "pct": usage.percent,
                    "used_gb": usage.used / (1024 ** 3),
                    "total_gb": usage.total / (1024 ** 3),
                })
        except Exception:
            pass
        return out

    def _battery(self) -> dict | None:
        try:
            b = psutil.sensors_battery()
        except Exception:
            b = None
        if b is None:
            return None
        return {
            "percent": b.percent,
            "plugged": bool(b.power_plugged),
            "secsleft": None if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else b.secsleft,
        }

    def _gpu(self) -> dict | None:
        if self._gpu_available is False:
            return None
        # Try pynvml first (no subprocess), then nvidia-smi.
        data = self._gpu_pynvml() or self._gpu_smi()
        self._gpu_available = data is not None
        return data

    def _gpu_pynvml(self) -> dict | None:
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            meminfo = pynvml.nvmlDeviceGetMemoryInfo(h)
            try:
                temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                temp = None
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "ignore")
            return {
                "util": float(util.gpu),
                "mem_pct": 100.0 * meminfo.used / meminfo.total if meminfo.total else 0.0,
                "temp": temp,
                "name": name,
            }
        except Exception:
            return None

    def _gpu_smi(self) -> dict | None:
        if not shutil.which("nvidia-smi"):
            return None
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=3,
                creationflags=_CREATE_NO_WINDOW,
            )
            line = out.stdout.strip().splitlines()[0]
            util, mem_used, mem_total, temp, name = [x.strip() for x in line.split(",")]
            return {
                "util": float(util),
                "mem_pct": 100.0 * float(mem_used) / float(mem_total) if float(mem_total) else 0.0,
                "temp": float(temp) if temp.replace(".", "").isdigit() else None,
                "name": name,
            }
        except Exception:
            return None
