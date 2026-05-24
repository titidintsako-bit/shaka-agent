"""Tests for deterministic task runner primitives."""

from shaka.automation import RISK_DESTRUCTIVE, RISK_NETWORK, RISK_READ_ONLY, TaskStore
import subprocess

import pytest

from shaka.task_runner import CommandExecutor, CommandPlan, Step, TaskRunner


def test_task_runner_successful_sequence(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Run sequence", "test")
    runner = TaskRunner(store)
    seen = []

    def first(task_record, store_record):
        seen.append((task_record["status"], store_record.get_task(task["id"])["status"]))
        return "ok"

    def second():
        seen.append(("second", "called"))

    result = runner.run(task["id"], [Step("first", first), second])
    steps = store.get_task_steps(task["id"])

    assert result["status"] == "completed"
    assert result["summary"] == "Task completed."
    assert seen == [("running", "running"), ("second", "called")]
    assert [step["kind"] for step in steps] == [
        "status",
        "status",
        "step_started",
        "step_completed",
        "step_started",
        "step_completed",
    ]
    assert steps[3]["metadata"]["result"] == "ok"


def test_task_runner_failure_sequence_captures_error_context(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Fail sequence", "test")
    runner = TaskRunner(store)
    calls = []

    def failing_step(task_record, store_record):
        calls.append(task_record["id"])
        raise RuntimeError("boom")

    def never_called():
        calls.append("never")

    result = runner.run(task["id"], [Step("explode", failing_step), never_called])
    failed_step = store.get_task_steps(task["id"])[-1]

    assert result["status"] == "failed"
    assert result["summary"] == "Task failed at step: explode"
    assert result["error"] == "RuntimeError: boom"
    assert calls == [task["id"]]
    assert failed_step["kind"] == "step_failed"
    assert failed_step["metadata"] == {
        "step": "explode",
        "step_index": 0,
        "error_type": "RuntimeError",
        "error": "boom",
    }


def test_task_runner_stops_when_cancelled_before_step(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Cancel sequence", "test")
    runner = TaskRunner(store)
    calls = []

    def cancel_self(task_record, store_record):
        calls.append("cancel")
        store_record.cancel_task(task_record["id"])

    def never_called():
        calls.append("never")

    result = runner.run(task["id"], [Step("cancel", cancel_self), never_called])
    steps = store.get_task_steps(task["id"])

    assert result["status"] == "cancelled"
    assert result["summary"] == "Task cancelled."
    assert calls == ["cancel"]
    assert steps[-1]["kind"] == "cancelled"
    assert steps[-1]["metadata"] == {"step_index": 1}


def test_command_plan_records_risk_without_executing(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Plan commands", "test")
    runner = TaskRunner(store)

    safe = CommandPlan.create("git status")
    destructive = CommandPlan.create("git reset --hard")
    network = CommandPlan.create("docker push image")

    result = runner.run(task["id"], [Step("plan", lambda task_record, store_record: destructive)])
    approval = store.list_approvals(status="pending")[0]

    assert safe.risk == RISK_READ_ONLY
    assert safe.requires_approval is False
    assert destructive.risk == RISK_DESTRUCTIVE
    assert destructive.requires_approval is True
    assert network.risk == RISK_NETWORK
    assert network.requires_approval is True
    assert result["status"] == "waiting_for_approval"
    assert approval["payload"]["command_plan"] == {
        "command": "git reset --hard",
        "action": "shell",
        "target": "",
        "risk": RISK_DESTRUCTIVE,
        "requires_approval": True,
    }


def test_task_runner_pauses_for_explicit_command_approval(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Approval sequence", "test")
    runner = TaskRunner(store)

    result = runner.run(
        task["id"],
        [
            Step(
                "approval-needed",
                lambda task_record, store_record: CommandPlan.create(
                    "npm install",
                    target=str(tmp_path),
                    requires_approval=True,
                ),
            )
        ],
    )
    approvals = store.list_approvals(status="pending")
    steps = store.get_task_steps(task["id"])

    assert result["status"] == "waiting_for_approval"
    assert len(approvals) == 1
    assert approvals[0]["summary"] == "Approve command plan: npm install"
    assert approvals[0]["payload"]["command_plan"]["command"] == "npm install"
    assert steps[-2]["kind"] == "approval_required"


def test_command_executor_runs_approved_allowlisted_command(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Execute command", "test")
    approval = store.create_approval(
        task["id"],
        action="shell",
        risk=RISK_READ_ONLY,
        summary="Run compileall",
        payload={
            "command_plan": {
                "command": "python -m compileall .",
                "action": "shell",
                "target": str(tmp_path),
                "risk": RISK_READ_ONLY,
                "requires_approval": True,
            }
        },
    )
    store.approve(approval["id"])

    result = CommandExecutor(store).execute_approved(task["id"], approval_id=approval["id"])

    assert result["status"] == "completed"
    assert result["payload"]["last_command_result"]["exit_code"] == 0
    assert store.get_approval(approval["id"])["status"] == "used"


def test_command_executor_redacts_secret_like_command_output(tmp_path, monkeypatch):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Execute command", "test")
    approval = store.create_approval(
        task["id"],
        action="shell",
        risk=RISK_READ_ONLY,
        summary="Run compileall",
        payload={
            "command_plan": {
                "command": "python -m compileall .",
                "action": "shell",
                "target": str(tmp_path),
                "risk": RISK_READ_ONLY,
                "requires_approval": True,
            }
        },
    )
    store.approve(approval["id"])

    def run_with_secret(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="token=abc123\napi_key=sk-test-secret-1234\n",
            stderr="Authorization: Bearer bearer-secret-5678\n",
        )

    monkeypatch.setattr(subprocess, "run", run_with_secret)

    result = CommandExecutor(store).execute_approved(task["id"], approval_id=approval["id"])
    output = result["payload"]["last_command_result"]

    assert "abc123" not in output["stdout"]
    assert "sk-test-secret-1234" not in output["stdout"]
    assert "bearer-secret-5678" not in output["stderr"]
    assert "[REDACTED]" in output["stdout"]
    assert "[REDACTED]" in output["stderr"]


def test_command_executor_blocks_non_allowlisted_command(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Execute blocked command", "test")
    approval = store.create_approval(
        task["id"],
        action="shell",
        risk=RISK_READ_ONLY,
        summary="Run arbitrary Python",
        payload={
            "command_plan": {
                "command": "python -c \"print(1)\"",
                "action": "shell",
                "target": str(tmp_path),
                "risk": RISK_READ_ONLY,
                "requires_approval": True,
            }
        },
    )
    store.approve(approval["id"])

    result = CommandExecutor(store).execute_approved(task["id"], approval_id=approval["id"])

    assert result["status"] == "failed"
    assert "not allowlisted" in result["summary"]
    assert store.get_approval(approval["id"])["status"] == "approved"


def test_command_executor_captures_timeout(tmp_path, monkeypatch):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Timeout command", "test")
    approval = store.create_approval(
        task["id"],
        action="shell",
        risk=RISK_READ_ONLY,
        summary="Run compileall",
        payload={
            "command_plan": {
                "command": "python -m compileall .",
                "action": "shell",
                "target": str(tmp_path),
                "risk": RISK_READ_ONLY,
                "requires_approval": True,
            }
        },
    )
    store.approve(approval["id"])

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1, output="out", stderr="err")

    monkeypatch.setattr(subprocess, "run", timeout)

    result = CommandExecutor(store).execute_approved(task["id"], approval_id=approval["id"], timeout_seconds=1)

    assert result["status"] == "failed"
    assert "timed out" in result["summary"]
    assert result["payload"]["last_command_result"]["timed_out"] is True


def test_command_executor_captures_missing_executable(tmp_path, monkeypatch):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Missing command", "test")
    approval = store.create_approval(
        task["id"],
        action="shell",
        risk=RISK_READ_ONLY,
        summary="Run build",
        payload={
            "command_plan": {
                "command": "npm run build",
                "action": "shell",
                "target": str(tmp_path),
                "risk": RISK_READ_ONLY,
                "requires_approval": True,
            }
        },
    )
    store.approve(approval["id"])

    def missing(*args, **kwargs):
        raise FileNotFoundError("npm was not found")

    monkeypatch.setattr(subprocess, "run", missing)

    result = CommandExecutor(store).execute_approved(task["id"], approval_id=approval["id"])

    assert result["status"] == "failed"
    assert "could not be started" in result["summary"]
    assert "npm was not found" in result["payload"]["last_command_result"]["stderr"]
