"""Local daemon process management for Shaka."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shaka.local_state import load_local_config_data, save_local_config_data


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DaemonSchedulerLoop:
    """Small stoppable loop that lets the daemon own cron ticking."""

    def __init__(
        self,
        cron_store: Any,
        *,
        interval_seconds: float = 60.0,
        dry_run: bool = False,
        stop_event: threading.Event | None = None,
    ):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.cron_store = cron_store
        self.interval_seconds = float(interval_seconds)
        self.dry_run = bool(dry_run)
        self.stop_event = stop_event or threading.Event()
        self.last_tick: dict[str, Any] | None = None
        self.last_error: str = ""
        self.last_tick_at: str = ""
        self.tick_count = 0
        self._thread: threading.Thread | None = None

    def tick_once(self) -> dict[str, Any]:
        try:
            self.last_tick = self.cron_store.tick(dry_run=self.dry_run)
            self.last_error = ""
        except Exception as exc:  # pragma: no cover - defensive daemon guard
            self.last_error = str(exc)
            self.last_tick = {"error": self.last_error}
        self.last_tick_at = _utc_now()
        self.tick_count += 1
        return self.last_tick

    def state(self) -> dict[str, Any]:
        return {
            "daemon_capable": True,
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval_seconds,
            "dry_run": self.dry_run,
            "tick_count": self.tick_count,
            "last_tick_at": self.last_tick_at,
            "last_tick": self.last_tick,
            "last_error": self.last_error,
        }

    def start(self) -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(target=self.run_forever, name="shaka-cron-scheduler", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            self.tick_once()
            if self.stop_event.is_set():
                break
            self.stop_event.wait(self.interval_seconds)


class DaemonManager:
    """Manage a local foreground-compatible gateway daemon process."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser()
        self.runtime_dir = self.base_dir / "runtime"
        self.logs_dir = self.base_dir / "logs"
        self.state_path = self.runtime_dir / "daemon.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def install(self, *, host: str, port: int) -> dict[str, Any]:
        config = load_local_config_data(self.base_dir)
        config.setdefault("daemon", {})
        config["daemon"].update({
            "installed": True,
            "host": host,
            "port": int(port),
            "command": self.command(host=host, port=port),
            "updated_at": _utc_now(),
        })
        save_local_config_data(config, self.base_dir)
        return config["daemon"]

    def command(self, *, host: str, port: int) -> list[str]:
        return [
            sys.executable,
            "-m",
            "shaka.cli",
            "gateway",
            "--host",
            host,
            "--port",
            str(port),
            "--hide-token",
        ]

    def scheduler(
        self,
        *,
        interval_seconds: float = 60.0,
        dry_run: bool = False,
        cron_store: Any | None = None,
        stop_event: threading.Event | None = None,
    ) -> DaemonSchedulerLoop:
        if cron_store is None:
            from shaka.cron import CronStore

            cron_store = CronStore(str(self.base_dir))
        return DaemonSchedulerLoop(
            cron_store,
            interval_seconds=interval_seconds,
            dry_run=dry_run,
            stop_event=stop_event,
        )

    def run_scheduler(
        self,
        *,
        interval_seconds: float = 60.0,
        dry_run: bool = False,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.scheduler(
            interval_seconds=interval_seconds,
            dry_run=dry_run,
            stop_event=stop_event,
        ).run_forever()

    def start(self, *, host: str, port: int) -> dict[str, Any]:
        status = self.status()
        if status["running"]:
            return status

        stdout_path = self.logs_dir / "daemon.out.log"
        stderr_path = self.logs_dir / "daemon.err.log"
        stdout = stdout_path.open("a", encoding="utf-8")
        stderr = stderr_path.open("a", encoding="utf-8")
        env = os.environ.copy()
        env["SHAKA_HOME"] = str(self.base_dir)
        env.setdefault("SHAKA_HOST", host)
        env.setdefault("SHAKA_PORT", str(port))

        creationflags = 0
        start_new_session = True
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            start_new_session = False

        proc = subprocess.Popen(
            self.command(host=host, port=port),
            cwd=str(Path.cwd()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        stdout.close()
        stderr.close()
        state = {
            "pid": proc.pid,
            "host": host,
            "port": int(port),
            "running": True,
            "started_at": _utc_now(),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "command": self.command(host=host, port=port),
        }
        self._save_state(state)
        return self.status()

    def stop(self) -> dict[str, Any]:
        state = self._load_state()
        pid = int(state.get("pid") or 0)
        if not pid:
            state["running"] = False
            self._save_state(state)
            return self.status()

        if self._pid_running(pid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
            else:
                os.kill(pid, signal.SIGTERM)

        state["running"] = False
        state["stopped_at"] = _utc_now()
        self._save_state(state)
        return self.status()

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        pid = int(state.get("pid") or 0)
        was_running = bool(state.get("running"))
        running = bool(pid and self._pid_running(pid))
        state["running"] = running
        if pid and was_running and not running:
            state["stopped_at"] = _utc_now()
        self._save_state(state)
        return state

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"running": False, "pid": 0, "state_path": str(self.state_path)}
        import json

        with self.state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
        data.setdefault("state_path", str(self.state_path))
        return data

    def _save_state(self, state: dict[str, Any]) -> None:
        import json

        state["state_path"] = str(self.state_path)
        tmp = self.state_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, self.state_path)

    def _pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return str(pid) in result.stdout
            os.kill(pid, 0)
            return True
        except (OSError, subprocess.SubprocessError):
            return False
