"""Portfolio proof reports for the local Shaka runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shaka.config import ShakaConfig
from shaka.local_state import LOCAL_STATE_DIRS, runtime_status, utc_now
from shaka.redaction import redact_text


class ProofExporter:
    """Build safe, shareable summaries of local Shaka runtime state."""

    def __init__(self, config: ShakaConfig):
        self.config = config

    def build(self) -> dict[str, Any]:
        """Return a secret-safe proof payload for Markdown or JSON export."""
        status = runtime_status(self.config)
        provider = status.get("provider", {}) or {}
        gateway = status.get("gateway", {}) or {}
        state = status.get("state", {}) or {}

        return {
            "generated_at": utc_now(),
            "service": status.get("service", "shaka-gateway"),
            "status": status.get("status", "unknown"),
            "local_first": bool(status.get("local_first")),
            "home": status.get("home", ""),
            "config_path": status.get("config_path", ""),
            "workspace_path": status.get("workspace_path", ""),
            "gateway": {
                "host": gateway.get("host", "127.0.0.1"),
                "port": gateway.get("port", 18789),
                "auth": gateway.get("auth", "token"),
                "binds_loopback": bool(gateway.get("binds_loopback")),
            },
            "provider": {
                "provider": provider.get("provider", ""),
                "label": provider.get("label", ""),
                "model": provider.get("model", ""),
                "base_url": provider.get("base_url", ""),
                "api_key_env": provider.get("api_key_env", ""),
                "configured": bool(provider.get("configured")),
                "credential_configured": bool(provider.get("credential_configured")),
                "source": provider.get("source", ""),
                "mode": provider.get("mode", ""),
            },
            "counts": {
                "sessions": int(status.get("session_count", 0)),
                "skills": int(status.get("skill_count", 0)),
                "tasks": int(status.get("task_count", 0)),
                "pending_approvals": int(status.get("pending_approval_count", 0)),
                "cron_jobs": int(status.get("cron_job_count", 0)),
                "credentials": int(status.get("credential_count", 0)),
                "recent_tool_calls": len(status.get("recent_tool_calls", []) or []),
            },
            "state_dirs": [
                {
                    "name": name,
                    "path": (state.get(name) or {}).get("path", ""),
                    "exists": bool((state.get(name) or {}).get("exists")),
                }
                for name in LOCAL_STATE_DIRS
            ],
            "capabilities": self._capability_matrix(status),
            "sessions": self._summarize_sessions(status.get("sessions", []) or []),
            "skills": self._summarize_skills(status.get("skills", []) or []),
            "tasks": self._summarize_tasks(status.get("tasks", []) or []),
            "pending_approvals": self._summarize_approvals(status.get("pending_approvals", []) or []),
            "cron_jobs": self._summarize_cron(status.get("cron_jobs", []) or []),
            "recent_tool_calls": self._summarize_tool_calls(status.get("recent_tool_calls", []) or []),
            "demo_commands": [
                "python -m shaka.cli onboard --yes",
                "python -m shaka.cli doctor",
                "python -m shaka.cli gateway --port 18789",
                "python -m shaka.cli demo local-project",
                "python -m shaka.cli proof export",
            ],
            "security_notes": [
                "Gateway binds to loopback by default.",
                "Dashboard/API access uses a local gateway token.",
                "Provider keys should come from environment variables or local credentials, never repo files.",
                "Delete or rotate credentials with `python -m shaka.cli credentials delete <provider>` and `python -m shaka.cli credentials set <provider>`.",
            ],
        }

    def export_markdown(self, output: str | Path | None = None) -> Path:
        """Write a Markdown proof report and return the output path."""
        report = self.build()
        path = Path(output).expanduser() if output else Path(report["home"]).expanduser() / "runtime" / "proof.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(report), encoding="utf-8")
        return path

    def to_json(self, report: dict[str, Any] | None = None) -> str:
        """Serialize a safe proof payload."""
        return json.dumps(report or self.build(), indent=2)

    def to_markdown(self, report: dict[str, Any] | None = None) -> str:
        """Render a proof payload as portfolio-ready Markdown."""
        data = report or self.build()
        gateway = data["gateway"]
        provider = data["provider"]
        counts = data["counts"]
        provider_label = f"{provider.get('provider') or 'unknown'} / {provider.get('model') or 'unconfigured'}"
        gateway_url = f"http://{gateway.get('host')}:{gateway.get('port')}"

        sections = [
            "# Shaka Local Runtime Proof",
            "",
            f"Generated: `{self._cell(data['generated_at'])}`",
            "",
            "## Local-first architecture",
            "",
            "Shaka is running as a local-first AI agent runtime. The core state, workspace, skills, sessions, memory, credentials, runtime metadata, and logs live on this machine under the local Shaka home directory.",
            "",
            "| Surface | Value |",
            "| --- | --- |",
            f"| Runtime home | `{self._cell(data['home'])}` |",
            f"| Config | `{self._cell(data['config_path'])}` |",
            f"| Workspace | `{self._cell(data['workspace_path'])}` |",
            f"| Gateway | `{self._cell(gateway_url)}` |",
            f"| Gateway auth | `{self._cell(gateway.get('auth'))}` |",
            f"| Loopback binding | `{str(bool(gateway.get('binds_loopback'))).lower()}` |",
            f"| Provider | `{self._cell(provider_label)}` |",
            f"| Provider configured | `{str(bool(provider.get('configured'))).lower()}` |",
            f"| API key source | `{self._cell(provider.get('source') or provider.get('api_key_env') or 'none')}` |",
            "",
            "## Runtime snapshot",
            "",
            "| Metric | Count |",
            "| --- | ---: |",
            f"| Sessions | {counts['sessions']} |",
            f"| Skills | {counts['skills']} |",
            f"| Tasks | {counts['tasks']} |",
            f"| Pending approvals | {counts['pending_approvals']} |",
            f"| Cron jobs | {counts['cron_jobs']} |",
            f"| Local credentials | {counts['credentials']} |",
            "",
            "## Capability matrix",
            "",
            self._table(
                ["Capability", "Status", "Evidence"],
                [[item["name"], item["status"], item["evidence"]] for item in data["capabilities"]],
            ),
            "",
            "## Local state directories",
            "",
            "| Directory | Path | Exists |",
            "| --- | --- | --- |",
        ]
        sections.extend(
            f"| {self._cell(item['name'])} | `{self._cell(item['path'])}` | {str(bool(item['exists'])).lower()} |"
            for item in data["state_dirs"]
        )
        sections.extend([
            "",
            "## Installed skills",
            "",
            self._table(
                ["Skill", "Access", "Approval", "Risk", "Notes"],
                [
                    [
                        item["name"],
                        "mutating" if item["mutating"] else "read-only",
                        "needed" if item["approval_required"] else "not required",
                        item["risk_level"],
                        item["risk_notes"],
                    ]
                    for item in data["skills"]
                ],
            ),
            "",
            "## Recent tasks",
            "",
            self._table(
                ["ID", "Status", "Kind", "Title", "Summary"],
                [[item["id"], item["status"], item["kind"], item["title"], item["summary"]] for item in data["tasks"]],
            ),
            "",
            "## Pending approvals",
            "",
            self._table(
                ["ID", "Risk", "Action", "Task", "Summary"],
                [[item["id"], item["risk"], item["action"], item["task_id"], item["summary"]] for item in data["pending_approvals"]],
            ),
            "",
            "## Cron jobs",
            "",
            self._table(
                ["ID", "Name", "Schedule", "Enabled", "Next run", "Last status"],
                [
                    [
                        item["id"],
                        item["name"],
                        item["schedule"],
                        str(bool(item["enabled"])).lower(),
                        item["next_run_at"],
                        item["last_status"],
                    ]
                    for item in data["cron_jobs"]
                ],
            ),
            "",
            "## Recent tool calls",
            "",
            self._table(
                ["Task", "Kind", "Message", "Created"],
                [[item["task_id"], item["kind"], item["message"], item["created_at"]] for item in data["recent_tool_calls"]],
            ),
            "",
            "## Demo commands",
            "",
        ])
        sections.extend(f"- `{command}`" for command in data["demo_commands"])
        sections.extend([
            "",
            "## Security notes",
            "",
        ])
        sections.extend(f"- {note}" for note in data["security_notes"])
        sections.append("")
        return "\n".join(sections)

    @staticmethod
    def _summarize_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "session_id": item.get("session_id") or item.get("id", ""),
                "message_count": item.get("message_count", 0),
                "updated_at": item.get("updated_at") or item.get("created_at", ""),
            }
            for item in sessions[:8]
        ]

    @staticmethod
    def _capability_matrix(status: dict[str, Any]) -> list[dict[str, str]]:
        gateway = status.get("gateway", {}) or {}
        daemon = status.get("daemon", {}) or {}
        session_count = int(status.get("session_count", 0))
        skill_count = int(status.get("skill_count", 0))
        task_count = int(status.get("task_count", 0))
        approval_count = int(status.get("pending_approval_count", 0))
        cron_count = int(status.get("cron_job_count", 0))

        gateway_status = "secured" if gateway.get("auth") == "token" and gateway.get("binds_loopback") else "needs-review"
        cron_status = "configured" if cron_count else "available"
        daemon_status = "running" if daemon.get("running") else "available"
        return [
            {
                "name": "Local memory",
                "status": "available",
                "evidence": f"{session_count} session(s) plus local memory directories under Shaka home.",
            },
            {
                "name": "Skills",
                "status": "available",
                "evidence": f"{skill_count} core/user skill(s) loaded from local skill folders.",
            },
            {
                "name": "Approval gates",
                "status": "available",
                "evidence": f"{approval_count} pending approval(s); task store tracks {task_count} task(s).",
            },
            {
                "name": "Cron scheduling",
                "status": cron_status,
                "evidence": f"{cron_count} persisted cron job(s) in the local runtime store.",
            },
            {
                "name": "Gateway/dashboard",
                "status": gateway_status,
                "evidence": f"{gateway.get('host')}:{gateway.get('port')} with {gateway.get('auth', 'unknown')} auth.",
            },
            {
                "name": "MCP server",
                "status": "available",
                "evidence": "Exposed through `shaka mcp serve` and inspectable through `shaka mcp inspect`.",
            },
            {
                "name": "Daemon mode",
                "status": daemon_status,
                "evidence": f"State file: {daemon.get('state_path', '')}",
            },
        ]

    @staticmethod
    def _summarize_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "path": item.get("path", ""),
                "mutating": bool(item.get("mutating", False)),
                "read_only": bool(item.get("read_only", not bool(item.get("mutating", False)))),
                "approval_required": bool(item.get("approval_required", False)),
                "risk_level": item.get("risk_level", ""),
                "risk_notes": item.get("risk_notes", ""),
            }
            for item in skills[:12]
        ]

    @staticmethod
    def _summarize_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": item.get("id", ""),
                "status": item.get("status", ""),
                "kind": item.get("kind", ""),
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "updated_at": item.get("updated_at", ""),
            }
            for item in tasks[:10]
        ]

    @staticmethod
    def _summarize_approvals(approvals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": item.get("id", ""),
                "task_id": item.get("task_id", ""),
                "action": item.get("action", ""),
                "risk": item.get("risk", ""),
                "summary": item.get("summary", ""),
                "created_at": item.get("created_at", ""),
            }
            for item in approvals[:10]
        ]

    @staticmethod
    def _summarize_cron(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "schedule": item.get("schedule", ""),
                "enabled": bool(item.get("enabled", True)),
                "next_run_at": item.get("next_run_at", ""),
                "last_status": item.get("last_status", ""),
                "run_count": item.get("run_count", 0),
            }
            for item in jobs[:10]
        ]

    @staticmethod
    def _summarize_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "task_id": item.get("task_id", ""),
                "kind": item.get("kind", ""),
                "message": item.get("message", ""),
                "created_at": item.get("created_at", ""),
            }
            for item in calls[:12]
        ]

    @classmethod
    def _table(cls, headers: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "_None recorded._"
        header = "| " + " | ".join(cls._cell(item) for item in headers) + " |"
        divider = "| " + " | ".join("---" for _ in headers) + " |"
        body = [
            "| " + " | ".join(cls._cell(value) for value in row) + " |"
            for row in rows
        ]
        return "\n".join([header, divider, *body])

    @staticmethod
    def _cell(value: Any) -> str:
        text = "" if value is None else str(value)
        text = redact_text(text)
        return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
