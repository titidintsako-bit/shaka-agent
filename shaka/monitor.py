"""System Monitor for Shaka.

Provides real-time CPU, memory, disk, network, and process stats using psutil.
Designed to be called from any thread (Textual updates or agent context).
"""

import os
import time
import psutil
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SystemStats:
    """Snapshot of current system metrics."""
    cpu_percent: float = 0.0
    cpu_cores_logical: int = 0
    cpu_cores_physical: int = 0
    cpu_freq_current: float = 0.0
    cpu_freq_max: float = 0.0

    mem_total: float = 0.0
    mem_used: float = 0.0
    mem_available: float = 0.0
    mem_percent: float = 0.0
    swap_total: float = 0.0
    swap_percent: float = 0.0

    disk_total: float = 0.0
    disk_used: float = 0.0
    disk_percent: float = 0.0

    net_sent: float = 0.0
    net_recv: float = 0.0

    boot_time: float = 0.0
    uptime_seconds: float = 0.0


class Monitor:
    """Thread-safe system monitor that refreshes periodically."""

    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._stats = SystemStats()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Take initial reading (psutil cpu_percent needs a warmup call)
        psutil.cpu_percent()
        self._refresh()

    def _bytes_to_gb(self, b: float) -> float:
        return round(b / (1024 ** 3), 1)

    def _refresh(self):
        """Refresh stats. Thread-safe via caller locking."""
        now = time.time()

        cpu = psutil.cpu_percent(interval=0)
        freq = psutil.cpu_freq()
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()

        boot = psutil.boot_time()
        uptime = now - boot

        self._stats = SystemStats(
            cpu_percent=cpu,
            cpu_cores_logical=psutil.cpu_count(logical=True),
            cpu_cores_physical=psutil.cpu_count(logical=False) or 0,
            cpu_freq_current=freq.current if freq else 0.0,
            cpu_freq_max=freq.max if freq else 0.0,
            mem_total=self._bytes_to_gb(mem.total),
            mem_used=self._bytes_to_gb(mem.used),
            mem_available=self._bytes_to_gb(mem.available),
            mem_percent=mem.percent,
            swap_total=self._bytes_to_gb(swap.total),
            swap_percent=swap.percent,
            disk_total=self._bytes_to_gb(disk.total),
            disk_used=self._bytes_to_gb(disk.used),
            disk_percent=disk.percent,
            net_sent=self._bytes_to_gb(net.bytes_sent),
            net_recv=self._bytes_to_gb(net.bytes_recv),
            boot_time=boot,
            uptime_seconds=uptime,
        )

    def _loop(self):
        """Background refresh loop."""
        while self._running:
            with self._lock:
                self._refresh()
            time.sleep(self.interval)

    def start(self):
        """Start the background refresh thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background refresh thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def get(self) -> SystemStats:
        """Get the latest stats snapshot."""
        with self._lock:
            return SystemStats(**self._stats.__dict__)

    @staticmethod
    def format_uptime(seconds: float) -> str:
        """Format uptime as a human-readable string."""
        total_minutes = int(seconds / 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours >= 24:
            days = hours // 24
            hours = hours % 24
            return f"{days}d {hours}h {minutes}m"
        return f"{hours}h {minutes}m"

    @staticmethod
    def bar(percent: float, width: int = 10, filled_char: str = "█", empty_char: str = "░") -> str:
        """Generate a text progress bar."""
        filled = int(width * percent / 100)
        filled = max(0, min(width, filled))
        return (filled_char * filled) + (empty_char * (width - filled))
