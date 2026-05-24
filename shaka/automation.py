"""Shared task runtime and approval gates for Shaka."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


TASK_STATUSES = {
    "queued",
    "running",
    "waiting_for_approval",
    "completed",
    "failed",
    "cancelled",
}

APPROVAL_STATUSES = {"pending", "approved", "rejected", "used"}

RISK_READ_ONLY = "read_only"
RISK_SAFE_WRITE = "safe_write"
RISK_RISKY_WRITE = "risky_write"
RISK_DESTRUCTIVE = "destructive"
RISK_NETWORK = "network"
RISK_SECRET = "secret_sensitive"
RISK_PAID = "paid_external"

APPROVAL_REQUIRED_RISKS = {
    RISK_RISKY_WRITE,
    RISK_DESTRUCTIVE,
    RISK_NETWORK,
    RISK_SECRET,
    RISK_PAID,
}


def utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class RiskClassifier:
    """Classify actions before automation executes them."""

    destructive_terms = {
        "rm",
        "remove-item",
        "del",
        "delete",
        "rmdir",
        "format",
        "drop",
        "truncate",
        "reset --hard",
    }
    network_terms = {"deploy", "curl", "wget", "gh release", "docker push", "npm publish"}
    secret_terms = {"token", "secret", "password", "credential", "oauth", "api_key", "apikey"}
    paid_terms = {"paid", "billing", "charge", "payment", "subscription"}

    @classmethod
    def classify(cls, action: str, target: str = "", command: str = "") -> str:
        sample = f"{action} {target} {command}".lower()
        if any(term in sample for term in cls.secret_terms):
            return RISK_SECRET
        if any(term in sample for term in cls.paid_terms):
            return RISK_PAID
        if any(term in sample for term in cls.destructive_terms):
            return RISK_DESTRUCTIVE
        if any(term in sample for term in cls.network_terms):
            return RISK_NETWORK
        if action.lower() in {"write_file", "create_file", "build_site", "email_draft"}:
            return RISK_SAFE_WRITE
        if action.lower() in {"email_send", "browser_login", "deploy"}:
            return RISK_RISKY_WRITE
        return RISK_READ_ONLY

    @staticmethod
    def requires_approval(risk: str, action: str = "") -> bool:
        if action.lower() in {"email_send", "browser_login", "deploy"}:
            return True
        return risk in APPROVAL_REQUIRED_RISKS


class TaskStore:
    """JSON-backed task and approval store shared by CLI, TUI, and dashboard."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser()
        self.runtime_dir = self.base_dir / "runtime"
        self.path = self.runtime_dir / "tasks.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def _empty(self) -> dict[str, Any]:
        return {"tasks": [], "approvals": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
        except json.JSONDecodeError:
            return self._empty()
        data.setdefault("tasks", [])
        data.setdefault("approvals", [])
        return data

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            last_error: PermissionError | None = None
            for _ in range(5):
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05)
            if last_error:
                raise last_error
        finally:
            if tmp.exists():
                tmp.unlink()

    def create_task(
        self,
        title: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        if status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        data = self._load()
        task = {
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "title": title,
            "kind": kind,
            "status": status,
            "payload": payload or {},
            "steps": [],
            "summary": "",
            "error": "",
            "created_at": utc_ts(),
            "updated_at": utc_ts(),
        }
        data["tasks"].append(task)
        self._save(data)
        return task

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        if status and status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        tasks = self._load()["tasks"]
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        return sorted(tasks, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        for task in self._load()["tasks"]:
            if task.get("id") == task_id:
                return task
        return None

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        error: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status and status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        data = self._load()
        for task in data["tasks"]:
            if task.get("id") == task_id:
                if status:
                    task["status"] = status
                if summary is not None:
                    task["summary"] = summary
                if error is not None:
                    task["error"] = error
                if payload is not None:
                    task["payload"] = payload
                task["updated_at"] = utc_ts()
                self._save(data)
                return task
        raise KeyError(f"Unknown task: {task_id}")

    def add_step(
        self,
        task_id: str,
        message: str,
        *,
        kind: str = "log",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._load()
        step = {
            "id": f"step_{uuid.uuid4().hex[:10]}",
            "kind": kind,
            "message": message,
            "metadata": metadata or {},
            "created_at": utc_ts(),
        }
        for task in data["tasks"]:
            if task.get("id") == task_id:
                task.setdefault("steps", []).append(step)
                task["updated_at"] = utc_ts()
                self._save(data)
                return step
        raise KeyError(f"Unknown task: {task_id}")

    def get_task_steps(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            raise KeyError(f"Unknown task: {task_id}")
        return list(task.get("steps", []))

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        data = self._load()
        for task in data["tasks"]:
            if task.get("id") == task_id:
                task["status"] = "cancelled"
                task["summary"] = "Task cancelled."
                task.setdefault("steps", []).append({
                    "id": f"step_{uuid.uuid4().hex[:10]}",
                    "kind": "cancelled",
                    "message": "Task cancelled.",
                    "metadata": {},
                    "created_at": utc_ts(),
                })
                task["updated_at"] = utc_ts()
                self._save(data)
                return task
        raise KeyError(f"Unknown task: {task_id}")

    def retry_task(self, task_id: str) -> dict[str, Any]:
        data = self._load()
        for task in data["tasks"]:
            if task.get("id") == task_id:
                status = task.get("status")
                if status not in {"failed", "cancelled"}:
                    raise ValueError(f"Only failed or cancelled tasks can be retried: {task_id}")
                task["status"] = "queued"
                task["error"] = ""
                task.setdefault("steps", []).append({
                    "id": f"step_{uuid.uuid4().hex[:10]}",
                    "kind": "retry",
                    "message": f"Retry queued from {status}.",
                    "metadata": {"previous_status": status},
                    "created_at": utc_ts(),
                })
                task["updated_at"] = utc_ts()
                self._save(data)
                return task
        raise KeyError(f"Unknown task: {task_id}")

    def create_approval(
        self,
        task_id: str,
        action: str,
        risk: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.get_task(task_id):
            raise KeyError(f"Unknown task: {task_id}")
        data = self._load()
        approval = {
            "id": f"approval_{uuid.uuid4().hex[:12]}",
            "task_id": task_id,
            "action": action,
            "risk": risk,
            "summary": summary,
            "payload": payload or {},
            "status": "pending",
            "created_at": utc_ts(),
            "updated_at": utc_ts(),
        }
        data["approvals"].append(approval)
        for task in data["tasks"]:
            if task.get("id") == task_id:
                task["status"] = "waiting_for_approval"
                task["updated_at"] = utc_ts()
                task.setdefault("steps", []).append({
                    "id": f"step_{uuid.uuid4().hex[:10]}",
                    "kind": "approval",
                    "message": f"Approval required: {summary}",
                    "metadata": {"approval_id": approval["id"], "risk": risk},
                    "created_at": utc_ts(),
                })
        self._save(data)
        return approval

    def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        if status and status not in APPROVAL_STATUSES:
            raise ValueError(f"Unsupported approval status: {status}")
        approvals = self._load()["approvals"]
        if status:
            approvals = [item for item in approvals if item.get("status") == status]
        return sorted(approvals, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        for approval in self._load()["approvals"]:
            if approval.get("id") == approval_id:
                return approval
        return None

    def set_approval_status(self, approval_id: str, status: str) -> dict[str, Any]:
        if status not in APPROVAL_STATUSES:
            raise ValueError(f"Unsupported approval status: {status}")
        data = self._load()
        for approval in data["approvals"]:
            if approval.get("id") == approval_id:
                approval["status"] = status
                approval["updated_at"] = utc_ts()
                self._save(data)
                return approval
        raise KeyError(f"Unknown approval: {approval_id}")

    def approve(self, approval_id: str) -> dict[str, Any]:
        approval = self.set_approval_status(approval_id, "approved")
        self.update_task(approval["task_id"], status="queued")
        self.add_step(approval["task_id"], f"Approved {approval_id}.", kind="approval")
        return approval

    def reject_approval(self, approval_id: str, reason: str = "") -> dict[str, Any]:
        data = self._load()
        for approval in data["approvals"]:
            if approval.get("id") == approval_id:
                approval["status"] = "rejected"
                approval["updated_at"] = utc_ts()
                reason_text = reason.strip()
                summary = "Approval rejected."
                if reason_text:
                    summary = f"{summary} Reason: {reason_text}"
                for task in data["tasks"]:
                    if task.get("id") == approval.get("task_id"):
                        task["status"] = "cancelled"
                        task["summary"] = summary
                        task.setdefault("steps", []).append({
                            "id": f"step_{uuid.uuid4().hex[:10]}",
                            "kind": "approval",
                            "message": f"Rejected {approval_id}.",
                            "metadata": {"approval_id": approval_id, "reason": reason_text},
                            "created_at": utc_ts(),
                        })
                        task["updated_at"] = utc_ts()
                        self._save(data)
                        return approval
                self._save(data)
                raise KeyError(f"Unknown task: {approval.get('task_id')}")
        raise KeyError(f"Unknown approval: {approval_id}")

    def mark_approval_used(self, approval_id: str) -> dict[str, Any]:
        return self.set_approval_status(approval_id, "used")
