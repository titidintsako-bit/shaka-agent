"""System Info Skill for Shaka.

Returns CPU, RAM, disk usage, OS info.
"""

import platform
import os


class SkillHandler:
    """Handles system info queries."""

    def __init__(self):
        pass

    def get_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "systeminfo",
                "description": "Get system information about the host machine",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    def run(self, message: str, context: dict) -> str:
        """Main entry point."""
        try:
            import psutil
        except ImportError:
            return "psutil package required: pip install psutil"

        info = []

        # OS
        os_info = f"{platform.system()} {platform.release()}"
        if platform.system() == "Linux":
            try:
                with open("/proc/version") as f:
                    os_info = f.readline().split("(")[0].strip()
            except:
                pass
        info.append(f"**OS**: {os_info}")

        # CPU
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        freq_str = f"{cpu_freq.current:.0f} MHz" if cpu_freq else "Unknown"
        cpu_pct = psutil.cpu_percent(interval=0.1)
        info.append(f"**CPU**: {cpu_count} cores @ {freq_str} (usage: {cpu_pct}%)")

        # RAM
        mem = psutil.virtual_memory()
        info.append(f"**RAM**: {self._format_bytes(mem.used)} / {self._format_bytes(mem.total)} ({mem.percent}% used)")

        # Disk
        disk = psutil.disk_usage('/')
        info.append(f"**Disk**: {self._format_bytes(disk.used)} / {self._format_bytes(disk.total)} ({disk.percent}% used)")

        # Python
        info.append(f"**Python**: {platform.python_version()}")

        # Arch
        info.append(f"**Arch**: {platform.machine()}")

        return "\n".join(info)

    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} PB"