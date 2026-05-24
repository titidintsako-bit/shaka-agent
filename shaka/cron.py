"""Local-first cron/scheduler runtime for Shaka."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shaka.automation import TaskStore, utc_ts
from shaka.redaction import redact_text
from shaka.task_runner import CommandExecutor


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _interval_seconds(schedule: str) -> int:
    text = schedule.strip().lower()
    if text == "@hourly":
        return 3600
    if text == "@daily":
        return 86400
    if text.startswith("@every "):
        value = text.split(" ", 1)[1].strip()
        unit = value[-1]
        amount = int(value[:-1] or "0")
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        if unit not in multipliers or amount <= 0:
            raise ValueError("Use @every with a positive interval like @every 5m")
        return amount * multipliers[unit]
    if text.startswith("*/") and text.endswith(" * * * *"):
        minutes = int(text.split(" ", 1)[0][2:])
        if minutes <= 0:
            raise ValueError("Cron minute interval must be positive")
        return minutes * 60
    if text == "* * * * *":
        return 60
    raise ValueError("Supported schedules: @every 5m, @hourly, @daily, */5 * * * *, * * * * *")


def _next_run(schedule: str, from_ts: str | None = None) -> str:
    base = _parse_ts(from_ts) or _now()
    return _format_ts(base + timedelta(seconds=_interval_seconds(schedule)))


class CronStore:
    """JSON-backed local cron job store."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser()
        self.runtime_dir = self.base_dir / "runtime"
        self.path = self.runtime_dir / "cron.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.task_store = TaskStore(str(self.base_dir))

    def _empty(self) -> dict[str, Any]:
        return {"jobs": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
        except json.JSONDecodeError:
            return self._empty()
        data.setdefault("jobs", [])
        return data

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, self.path)

    def list_jobs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        jobs = self._load()["jobs"]
        if enabled_only:
            jobs = [job for job in jobs if job.get("enabled", True)]
        return sorted(jobs, key=lambda item: item.get("created_at", ""))

    def add_job(
        self,
        name: str,
        schedule: str,
        command: str,
        *,
        cwd: str = ".",
        enabled: bool = True,
    ) -> dict[str, Any]:
        name = name.strip()
        command = command.strip()
        if not name:
            raise ValueError("name is required")
        if not command:
            raise ValueError("command is required")
        next_run = _next_run(schedule)
        data = self._load()
        job = {
            "id": f"cron_{uuid.uuid4().hex[:10]}",
            "name": name,
            "schedule": schedule.strip(),
            "command": command,
            "cwd": cwd,
            "enabled": bool(enabled),
            "created_at": utc_ts(),
            "updated_at": utc_ts(),
            "next_run_at": next_run,
            "last_run_at": "",
            "last_status": "",
            "last_task_id": "",
            "run_count": 0,
        }
        data["jobs"].append(job)
        self._save(data)
        return job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        for job in self._load()["jobs"]:
            if job.get("id") == job_id:
                return job
        return None

    def update_job(self, job: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        for index, existing in enumerate(data["jobs"]):
            if existing.get("id") == job.get("id"):
                job["updated_at"] = utc_ts()
                data["jobs"][index] = job
                self._save(data)
                return job
        raise KeyError(f"Unknown cron job: {job.get('id')}")

    def delete_job(self, job_id: str) -> bool:
        data = self._load()
        before = len(data["jobs"])
        data["jobs"] = [job for job in data["jobs"] if job.get("id") != job_id]
        deleted = len(data["jobs"]) != before
        if deleted:
            self._save(data)
        return deleted

    def due_jobs(self, *, now: str | None = None) -> list[dict[str, Any]]:
        current = _parse_ts(now) or _now()
        due = []
        for job in self.list_jobs(enabled_only=True):
            next_run = _parse_ts(job.get("next_run_at"))
            if next_run and next_run <= current:
                due.append(job)
        return due

    def record_run(self, job_id: str, *, status: str, task_id: str = "", now: str | None = None) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Unknown cron job: {job_id}")
        current = now or utc_ts()
        job["last_run_at"] = current
        job["last_status"] = status
        job["last_task_id"] = task_id
        job["run_count"] = int(job.get("run_count", 0)) + 1
        job["next_run_at"] = _next_run(job["schedule"], current)
        return self.update_job(job)

    def run_job(self, job_id: str, *, dry_run: bool = False, timeout_seconds: int = 120) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Unknown cron job: {job_id}")
        task = self.task_store.create_task(
            title=f"Cron: {job['name']}",
            kind="cron",
            payload={"job_id": job["id"], "command": job["command"], "cwd": job.get("cwd", ".")},
            status="queued",
        )
        if dry_run:
            self.task_store.update_task(task["id"], status="completed", summary=f"Dry run: {job['command']}")
            self.record_run(job_id, status="dry_run", task_id=task["id"])
            return {"job": self.get_job(job_id), "task": self.task_store.get_task(task["id"]), "status": "dry_run"}

        executor = CommandExecutor(self.task_store)
        if not executor.is_allowed_command(job["command"]):
            reason = f"Cron command is not allowlisted: {job['command']}"
            self.task_store.add_step(task["id"], reason, kind="command_blocked", metadata={"job_id": job["id"]})
            self.task_store.update_task(task["id"], status="failed", summary=reason, error=reason)
            self.record_run(job_id, status="failed", task_id=task["id"])
            return {"job": self.get_job(job_id), "task": self.task_store.get_task(task["id"]), "status": "failed"}

        cwd = Path(job.get("cwd") or ".").expanduser().resolve()
        if not cwd.exists():
            reason = f"Cron cwd does not exist: {cwd}"
            self.task_store.update_task(task["id"], status="failed", summary=reason, error=reason)
            self.record_run(job_id, status="failed", task_id=task["id"])
            return {"job": self.get_job(job_id), "task": self.task_store.get_task(task["id"]), "status": "failed"}

        self.task_store.update_task(task["id"], status="running")
        self.task_store.add_step(task["id"], f"Running cron command: {job['command']}", kind="command_started")
        try:
            completed = subprocess.run(
                shlex.split(job["command"], posix=os.name != "nt"),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )
            output = {
                "exit_code": completed.returncode,
                "stdout": redact_text(completed.stdout)[-4000:],
                "stderr": redact_text(completed.stderr)[-4000:],
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            output = {"exit_code": None, "stdout": "", "stderr": redact_text(str(exc))[-4000:]}
            self.task_store.add_step(task["id"], "Cron command failed to start.", kind="command_failed", metadata=output)
            self.task_store.update_task(task["id"], status="failed", summary="Cron command failed.", error=str(exc))
            self.record_run(job_id, status="failed", task_id=task["id"])
            return {"job": self.get_job(job_id), "task": self.task_store.get_task(task["id"]), "status": "failed"}

        self.task_store.add_step(task["id"], "Cron command completed.", kind="command_completed", metadata=output)
        status = "completed" if output["exit_code"] == 0 else "failed"
        self.task_store.update_task(
            task["id"],
            status=status,
            summary="Cron command completed." if status == "completed" else f"Cron command failed with exit code {output['exit_code']}.",
            error="" if status == "completed" else (output["stderr"] or output["stdout"]),
            payload={**task.get("payload", {}), "last_command_result": output},
        )
        self.record_run(job_id, status=status, task_id=task["id"])
        return {"job": self.get_job(job_id), "task": self.task_store.get_task(task["id"]), "status": status}

    def tick(self, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        due = self.due_jobs(now=now)
        results = [self.run_job(job["id"], dry_run=dry_run) for job in due]
        return {"checked": len(due), "ran": len(results), "results": results}
