"""Tests for Shaka automation runtime."""

import pytest

from shaka.automation import RiskClassifier, TaskStore


def test_task_state_transitions(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Ship feature", "repo")
    store.add_step(task["id"], "planned")
    updated = store.update_task(task["id"], status="completed", summary="done")

    assert updated["status"] == "completed"
    assert updated["summary"] == "done"
    assert store.get_task(task["id"])["steps"][0]["message"] == "planned"


def test_approval_lifecycle(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Send email", "email")
    approval = store.create_approval(task["id"], "email_send", "risky_write", "Send reply")

    assert store.get_task(task["id"])["status"] == "waiting_for_approval"
    approved = store.approve(approval["id"])

    assert approved["status"] == "approved"
    assert store.get_task(task["id"])["status"] == "queued"


def test_retry_task_requeues_failed_and_cancelled_tasks(tmp_path):
    store = TaskStore(str(tmp_path))
    failed = store.create_task("Retry failed", "repo", status="failed")
    cancelled = store.create_task("Retry cancelled", "repo", status="cancelled")

    retried_failed = store.retry_task(failed["id"])
    retried_cancelled = store.retry_task(cancelled["id"])

    assert retried_failed["status"] == "queued"
    assert retried_cancelled["status"] == "queued"
    assert retried_failed["error"] == ""
    assert store.get_task_steps(failed["id"])[-1]["kind"] == "retry"
    assert store.get_task_steps(cancelled["id"])[-1]["metadata"] == {
        "previous_status": "cancelled",
    }


def test_retry_task_rejects_non_terminal_task(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Not ready", "repo")

    with pytest.raises(ValueError):
        store.retry_task(task["id"])


def test_reject_approval_cancels_task_and_logs_reason(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Deploy site", "deploy")
    approval = store.create_approval(task["id"], "deploy", "risky_write", "Deploy")

    rejected = store.reject_approval(approval["id"], reason="Needs staging validation")
    updated = store.get_task(task["id"])
    step = store.get_task_steps(task["id"])[-1]

    assert rejected["status"] == "rejected"
    assert updated["status"] == "cancelled"
    assert updated["summary"] == "Approval rejected. Reason: Needs staging validation"
    assert step["kind"] == "approval"
    assert step["metadata"] == {
        "approval_id": approval["id"],
        "reason": "Needs staging validation",
    }


def test_cancel_task_logs_step(tmp_path):
    store = TaskStore(str(tmp_path))
    task = store.create_task("Cancel me", "repo")

    cancelled = store.cancel_task(task["id"])

    assert cancelled["status"] == "cancelled"
    assert store.get_task_steps(task["id"])[-1]["message"] == "Task cancelled."


def test_invalid_status_filters_are_rejected(tmp_path):
    store = TaskStore(str(tmp_path))

    with pytest.raises(ValueError):
        store.list_tasks(status="missing")
    with pytest.raises(ValueError):
        store.list_approvals(status="missing")


def test_unknown_status_is_rejected(tmp_path):
    store = TaskStore(str(tmp_path))
    with pytest.raises(ValueError):
        store.create_task("Bad task", "eval", status="unknown")


def test_risk_classifier_blocks_dangerous_actions():
    assert RiskClassifier.classify("shell", command="git reset --hard") == "destructive"
    assert RiskClassifier.requires_approval("risky_write", "email_send")
