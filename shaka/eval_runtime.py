"""Local eval harness for Shaka core workflows."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .automation import RiskClassifier, TaskStore
from .email_runtime import GmailRuntime
from .website_builder import StackDetector, WebsiteBuilder


class EvalRunner:
    """Run deterministic checks for agent infrastructure."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def run(self) -> dict[str, Any]:
        results = [
            self._task_eval(),
            self._approval_eval(),
            self._email_eval(),
            self._website_eval(),
        ]
        passed = sum(1 for item in results if item["passed"])
        return {
            "passed": passed,
            "failed": len(results) - passed,
            "results": results,
        }

    def _task_eval(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)
            task = store.create_task("Eval task", "eval")
            store.add_step(task["id"], "step ok")
            store.update_task(task["id"], status="completed", summary="done")
            loaded = store.get_task(task["id"])
            ok = loaded is not None and loaded["status"] == "completed" and len(loaded["steps"]) == 1
            return {"name": "task_state_transitions", "passed": ok}

    def _approval_eval(self) -> dict[str, Any]:
        risk = RiskClassifier.classify("email_send")
        ok = RiskClassifier.requires_approval(risk, "email_send")
        return {"name": "approval_policy_email_send", "passed": ok, "risk": risk}

    def _email_eval(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            gmail = GmailRuntime(tmp)
            draft = gmail.draft_reply("dev@example.com", "Test", "Approved draft")
            approval = draft["approval"]
            try:
                gmail.send_approved(approval["id"])
                before_approval_blocked = False
            except PermissionError:
                before_approval_blocked = True
            gmail.task_store.approve(approval["id"])
            sent = gmail.send_approved(approval["id"])
            return {
                "name": "gmail_send_requires_approval",
                "passed": before_approval_blocked and sent["to"] == "dev@example.com",
            }

    def _website_eval(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "app"
            builder = WebsiteBuilder(tmp)
            task = builder.build_site("Portfolio app for engineers", target)
            detected = StackDetector.detect(target / "frontend")
            ok = task["status"] == "completed" and "vite" in detected["stack"] and (target / "backend" / "app" / "main.py").exists()
            return {"name": "website_scaffold_generation", "passed": ok}
