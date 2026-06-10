"""Network telemetry: latency (TCP connect), public IP, online/offline state.

Throughput history is kept here too (filled from SystemMetricsService snapshots
by the hub) so the network sparkline has a single source.
"""

from __future__ import annotations

import socket
import time
from collections import deque

from ui.services.base import PolledService
from ui.services.http import get_text

_PING_HOST = ("1.1.1.1", 443)
_PING_FALLBACK = ("8.8.8.8", 443)
_IPIFY = "https://api.ipify.org"


class NetworkService(PolledService):
    HISTORY = 120

    def __init__(self, interval: float = 15.0):
        super().__init__(interval, name="network", cache_key="net_pub_ip", cache_ttl=3600)
        self._down_hist: deque[float] = deque(maxlen=self.HISTORY)
        self._up_hist: deque[float] = deque(maxlen=self.HISTORY)
        self._ip_checked_t = 0.0
        self._public_ip: str | None = None

    # Throughput is pushed in from the metrics snapshot (single sampling source).
    def push_throughput(self, down_mbs: float, up_mbs: float) -> None:
        self._down_hist.append(max(0.0, down_mbs))
        self._up_hist.append(max(0.0, up_mbs))

    @property
    def down_history(self) -> list[float]:
        return list(self._down_hist)

    @property
    def up_history(self) -> list[float]:
        return list(self._up_hist)

    def poll(self) -> dict:
        latency_ms, host = self._tcp_latency()
        online = latency_ms is not None

        # Refresh public IP at most every 15 min, and only while online.
        if online and (time.time() - self._ip_checked_t > 900 or self._public_ip is None):
            try:
                self._public_ip = get_text(_IPIFY, timeout=4.0).strip()
                self._ip_checked_t = time.time()
            except Exception:
                pass  # keep prior IP

        if not online:
            raise RuntimeError("offline")

        return {
            "online": online,
            "latency_ms": latency_ms,
            "ping_host": host,
            "public_ip": self._public_ip,
        }

    def _tcp_latency(self) -> tuple[float | None, str]:
        for host, port in (_PING_HOST, _PING_FALLBACK):
            try:
                start = time.perf_counter()
                with socket.create_connection((host, port), timeout=3.0):
                    pass
                return (time.perf_counter() - start) * 1000.0, host
            except Exception:
                continue
        return None, _PING_HOST[0]
