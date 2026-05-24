"""Deterministic task runner primitives for Shaka."""

from __future__ import annotations

import inspect
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from shaka.automation import RiskClassifier, TaskStore
from shaka.redaction import redact_text


class StepCallable(Protocol):
    def __call__(self, task: dict[str, Any], store: TaskStore) -> Any:
        ...


@dataclass(frozen=True)
class Step:
    """A deterministic unit of work for a stored task."""

    name: str
    run: StepCallable
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandPlan:
    """Records command intent without executing anything."""

    command: str
    action: str = "shell"
    target: str = ""
    risk: str = ""
    requires_approval: bool = False

    def __post_init__(self) -> None:
        requested_approval = self.requires_approval
        risk = self.risk or RiskClassifier.classify(
            self.action,
            target=self.target,
            command=self.command,
        )
        object.__setattr__(self, "risk", risk)
        object.__setattr__(
            self,
            "requires_approval",
            requested_approval or RiskClassifier.requires_approval(risk, self.action),
        )

    @classmethod
    def create(
        cls,
        command: str,
        *,
        action: str = "shell",
        target: str = "",
        requires_approval: bool = False,
    ) -> "CommandPlan":
        return cls(
            command=command,
            action=action,
            target=target,
            requires_approval=requires_approval,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "action": self.action,
            "target": self.target,
            "risk": self.risk,
            "requires_approval": self.requires_approval,
        }


class TaskRunner:
    """Runs task steps sequentially through the public TaskStore API."""

    def __init__(self, store: TaskStore):
        self.store = store

    def run(self, task_id: str, steps: list[Step | Callable[..., Any]]) -> dict[str, Any]:
        task = self._require_task(task_id)
        if task.get("status") == "cancelled":
            self.store.add_step(task_id, "Task cancelled before runner start.", kind="cancelled")
            return self._require_task(task_id)

        self.store.update_task(task_id, status="queued", error="")
        self.store.add_step(task_id, "Task queued.", kind="status", metadata={"status": "queued"})
        self.store.update_task(task_id, status="running")
        self.store.add_step(task_id, "Task running.", kind="status", metadata={"status": "running"})

        for index, raw_step in enumerate(steps):
            current = self._require_task(task_id)
            if current.get("status") == "cancelled":
                self.store.add_step(
                    task_id,
                    f"Task cancelled before step {index + 1}.",
                    kind="cancelled",
                    metadata={"step_index": index},
                )
                return self._require_task(task_id)

            step = self._coerce_step(raw_step)
            self.store.add_step(
                task_id,
                f"Starting step: {step.name}",
                kind="step_started",
                metadata={"step": step.name, "step_index": index, **step.metadata},
            )
            try:
                result = step.run(self._require_task(task_id), self.store)
            except Exception as exc:  # noqa: BLE001 - task errors must be captured.
                error_context = {
                    "step": step.name,
                    "step_index": index,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                self.store.add_step(
                    task_id,
                    f"Step failed: {step.name}",
                    kind="step_failed",
                    metadata=error_context,
                )
                return self.store.update_task(
                    task_id,
                    status="failed",
                    summary=f"Task failed at step: {step.name}",
                    error=f"{exc.__class__.__name__}: {exc}",
                )

            if isinstance(result, CommandPlan) and result.requires_approval:
                self.store.add_step(
                    task_id,
                    f"Step paused for approval: {step.name}",
                    kind="approval_required",
                    metadata={
                        "step": step.name,
                        "step_index": index,
                        "command_plan": result.to_dict(),
                    },
                )
                self.store.create_approval(
                    task_id,
                    action=result.action,
                    risk=result.risk,
                    summary=f"Approve command plan: {result.command}",
                    payload={
                        "step": step.name,
                        "step_index": index,
                        "command_plan": result.to_dict(),
                    },
                )
                return self._require_task(task_id)

            self.store.add_step(
                task_id,
                f"Completed step: {step.name}",
                kind="step_completed",
                metadata={
                    "step": step.name,
                    "step_index": index,
                    "result": self._safe_result(result),
                },
            )

        return self.store.update_task(task_id, status="completed", summary="Task completed.")

    def _require_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if not task:
            raise KeyError(f"Unknown task: {task_id}")
        return task

    def _coerce_step(self, step: Step | Callable[..., Any]) -> Step:
        if isinstance(step, Step):
            return step
        name = getattr(step, "__name__", step.__class__.__name__)
        return Step(name=name, run=self._adapt_callable(step))

    def _adapt_callable(self, callback: Callable[..., Any]) -> StepCallable:
        signature = inspect.signature(callback)
        parameters = signature.parameters

        if len(parameters) == 0:
            return lambda task, store: callback()
        if len(parameters) == 1:
            return lambda task, store: callback(task)
        return lambda task, store: callback(task, store)

    def _safe_result(self, result: Any) -> Any:
        if isinstance(result, CommandPlan):
            return result.to_dict()
        if result is None or isinstance(result, (str, int, float, bool, list, tuple, dict)):
            return result
        return repr(result)


class CommandExecutor:
    """Executes approved command plans through a narrow allowlist."""

    DEFAULT_ALLOWED_PREFIXES = (
        ("python", "-m", "pytest"),
        ("python", "-m", "compileall"),
        ("npm", "run", "build"),
        ("npm", "run", "test"),
        ("npm", "test"),
        ("pnpm", "run", "build"),
        ("pnpm", "run", "test"),
        ("pnpm", "test"),
        ("yarn", "build"),
        ("yarn", "test"),
    )

    def __init__(
        self,
        store: TaskStore,
        *,
        allowed_prefixes: tuple[tuple[str, ...], ...] | None = None,
        timeout_seconds: int = 120,
    ):
        self.store = store
        self.allowed_prefixes = allowed_prefixes or self.DEFAULT_ALLOWED_PREFIXES
        self.timeout_seconds = timeout_seconds

    def execute_approved(
        self,
        task_id: str,
        *,
        approval_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        approval = self._resolve_approved_command(task_id, approval_id)
        command_plan = approval.get("payload", {}).get("command_plan", {})
        command = str(command_plan.get("command", "")).strip()
        cwd = Path(command_plan.get("target") or ".").expanduser().resolve()
        timeout = timeout_seconds or self.timeout_seconds

        if not command:
            return self._block(task_id, "Approved payload does not contain a command plan.", approval, command_plan)
        if not cwd.exists() or not cwd.is_dir():
            return self._block(task_id, f"Command working directory does not exist: {cwd}", approval, command_plan)

        args = self._split(command)
        if not self._is_allowed(args):
            return self._block(task_id, f"Command is not allowlisted: {command}", approval, command_plan)

        self.store.update_task(task_id, status="running")
        self.store.add_step(
            task_id,
            f"Executing approved command: {command}",
            kind="command_started",
            metadata={"approval_id": approval["id"], "command_plan": command_plan, "cwd": str(cwd), "timeout_seconds": timeout},
        )
        try:
            completed = subprocess.run(
                args,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            result = {
                "command": command,
                "cwd": str(cwd),
                "exit_code": None,
                "timed_out": True,
                "stdout": self._tail(exc.stdout or ""),
                "stderr": self._tail(exc.stderr or ""),
            }
            self.store.add_step(task_id, "Approved command timed out.", kind="command_timeout", metadata=result)
            return self.store.update_task(
                task_id,
                status="failed",
                summary=f"Command timed out after {timeout}s.",
                error=f"TimeoutExpired: {command}",
                payload={**(self.store.get_task(task_id) or {}).get("payload", {}), "last_command_result": result},
            )
        except OSError as exc:
            result = {
                "command": command,
                "cwd": str(cwd),
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": self._tail(str(exc)),
            }
            self.store.add_step(task_id, "Approved command could not be started.", kind="command_failed", metadata=result)
            return self.store.update_task(
                task_id,
                status="failed",
                summary=f"Command could not be started: {command}",
                error=f"{type(exc).__name__}: {exc}",
                payload={**(self.store.get_task(task_id) or {}).get("payload", {}), "last_command_result": result},
            )

        result = {
            "command": command,
            "cwd": str(cwd),
            "exit_code": completed.returncode,
            "timed_out": False,
            "stdout": self._tail(completed.stdout),
            "stderr": self._tail(completed.stderr),
        }
        self.store.add_step(task_id, "Approved command completed.", kind="command_completed", metadata=result)
        self.store.mark_approval_used(approval["id"])
        payload = {**(self.store.get_task(task_id) or {}).get("payload", {}), "last_command_result": result}
        if completed.returncode == 0:
            return self.store.update_task(
                task_id,
                status="completed",
                summary="Approved command executed successfully.",
                payload=payload,
            )
        return self.store.update_task(
            task_id,
            status="failed",
            summary=f"Approved command failed with exit code {completed.returncode}.",
            error=result["stderr"] or result["stdout"],
            payload=payload,
        )

    def _resolve_approved_command(self, task_id: str, approval_id: str | None) -> dict[str, Any]:
        if approval_id:
            approval = self.store.get_approval(approval_id)
            if not approval or approval.get("task_id") != task_id:
                raise KeyError(f"Unknown approval for task: {approval_id}")
            if approval.get("status") != "approved":
                raise PermissionError(f"Approval {approval_id} is not approved.")
            return approval

        matches = [
            item for item in self.store.list_approvals(status="approved")
            if item.get("task_id") == task_id and item.get("payload", {}).get("command_plan")
        ]
        if not matches:
            raise PermissionError(f"No approved command plan found for task: {task_id}")
        if len(matches) > 1:
            raise ValueError(f"Multiple approved command plans found for task: {task_id}")
        return matches[0]

    def _block(
        self,
        task_id: str,
        reason: str,
        approval: dict[str, Any],
        command_plan: dict[str, Any],
    ) -> dict[str, Any]:
        self.store.add_step(
            task_id,
            reason,
            kind="command_blocked",
            metadata={"approval_id": approval["id"], "command_plan": command_plan},
        )
        return self.store.update_task(
            task_id,
            status="failed",
            summary=reason,
            error=reason,
        )

    def _split(self, command: str) -> list[str]:
        return shlex.split(command, posix=os.name != "nt")

    def is_allowed_command(self, command: str) -> bool:
        return self._is_allowed(self._split(command))

    def _is_allowed(self, args: list[str]) -> bool:
        normalized = [item.lower() for item in args]
        for prefix in self.allowed_prefixes:
            if normalized[: len(prefix)] == [item.lower() for item in prefix]:
                return True
        return False

    def _tail(self, value: str, limit: int = 4000) -> str:
        text = redact_text(value)
        if len(text) <= limit:
            return text
        return text[-limit:]
