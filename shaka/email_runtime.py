"""Gmail-oriented email workflows for Shaka.

The first implementation is intentionally approval-gated. Real Gmail OAuth can
be added behind the same interface; local snapshots keep tests and demos safe.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .automation import RISK_RISKY_WRITE, TaskStore


class GmailRuntime:
    """Search, summarize, draft, and approval-gate Gmail actions."""

    READ_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
    ]
    SEND_SCOPES = [
        "https://www.googleapis.com/auth/gmail.send",
    ]

    def __init__(self, base_dir: str, task_store: TaskStore | None = None, mode: str | None = None):
        self.base_dir = Path(base_dir).expanduser()
        self.email_dir = self.base_dir / "email"
        self.email_dir.mkdir(parents=True, exist_ok=True)
        self.token_path = self.email_dir / "gmail_token.json"
        self.snapshot_path = self.email_dir / "gmail_snapshot.json"
        self.sent_path = self.email_dir / "sent_log.json"
        self.task_store = task_store or TaskStore(base_dir)
        self.mode = mode or os.environ.get("SHAKA_GMAIL_MODE", "local_log")
        if self.mode not in {"local_log", "gmail_api"}:
            self.mode = "local_log"

    def setup_instructions(self) -> dict[str, Any]:
        status = self.connection_status()
        return {
            "provider": "gmail",
            "mode": self.mode,
            "token_path": str(self.token_path),
            "status": status["status"],
            "scopes": {
                "read": self.READ_SCOPES,
                "send": self.SEND_SCOPES,
            },
            "steps": [
                "Create a Google Cloud OAuth client for a desktop app.",
                "Enable the Gmail API.",
                "Store the OAuth token JSON at the token_path shown here.",
                "Use read scopes for search/summarize and send scope only when you need approved sends.",
                "Set SHAKA_GMAIL_MODE=gmail_api or construct GmailRuntime(..., mode='gmail_api') to use the API.",
                "To reset or disconnect, call revoke() or delete the token_path file.",
            ],
            "revoke": {
                "method": "revoke()",
                "effect": "Attempts credential revocation when supported, then removes the local token file.",
            },
        }

    def _google_dependencies(self) -> dict[str, Any]:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except Exception as exc:
            return {
                "available": False,
                "reason": f"{exc.__class__.__name__}: {exc}",
                "Request": None,
                "Credentials": None,
                "build": None,
            }
        return {
            "available": True,
            "reason": "",
            "Request": Request,
            "Credentials": Credentials,
            "build": build,
        }

    def _load_credentials(self, deps: dict[str, Any] | None = None) -> Any | None:
        deps = deps or self._google_dependencies()
        if not deps.get("available") or not self.token_path.exists():
            return None
        scopes = self.READ_SCOPES + self.SEND_SCOPES
        try:
            return deps["Credentials"].from_authorized_user_file(str(self.token_path), scopes)
        except Exception:
            return None

    def _build_gmail_service(self) -> Any | None:
        deps = self._google_dependencies()
        if not deps.get("available"):
            return None
        creds = self._load_credentials(deps)
        if creds is None:
            return None
        try:
            if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
                creds.refresh(deps["Request"]())
                with self.token_path.open("w", encoding="utf-8") as handle:
                    handle.write(creds.to_json())
            if not getattr(creds, "valid", False):
                return None
            return deps["build"]("gmail", "v1", credentials=creds)
        except Exception:
            return None

    def connection_status(self) -> dict[str, Any]:
        deps = self._google_dependencies()
        token_exists = self.token_path.exists()
        creds = self._load_credentials(deps) if token_exists else None
        configured = bool(token_exists and deps.get("available") and creds is not None)
        if configured:
            status = "configured"
        elif token_exists and not deps.get("available"):
            status = "unavailable"
        elif token_exists:
            status = "unavailable"
        else:
            status = "not_connected"
        return {
            "provider": "gmail",
            "mode": self.mode,
            "status": status,
            "token_path": str(self.token_path),
            "token_exists": token_exists,
            "google_dependencies_available": bool(deps.get("available")),
            "google_dependencies_error": deps.get("reason", ""),
            "scopes": self.READ_SCOPES + self.SEND_SCOPES,
            "can_use_gmail_api": configured and self.mode == "gmail_api",
        }

    def revoke(self) -> dict[str, Any]:
        deps = self._google_dependencies()
        creds = self._load_credentials(deps)
        revoked_remote = False
        revoke_error = ""
        if creds is not None and deps.get("available"):
            try:
                revoke = getattr(creds, "revoke", None)
                if callable(revoke):
                    revoke(deps["Request"]())
                    revoked_remote = True
            except Exception as exc:
                revoke_error = f"{exc.__class__.__name__}: {exc}"

        removed_local_token = False
        if self.token_path.exists():
            self.token_path.unlink()
            removed_local_token = True

        return {
            "provider": "gmail",
            "mode": self.mode,
            "status": "not_connected",
            "token_path": str(self.token_path),
            "removed_local_token": removed_local_token,
            "revoked_remote": revoked_remote,
            "revoke_error": revoke_error,
            "reset_guidance": "Recreate the OAuth token JSON at token_path to reconnect.",
        }

    def _load_messages(self) -> list[dict[str, Any]]:
        if not self.snapshot_path.exists():
            return []
        with self.snapshot_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle) or []
        if isinstance(payload, dict):
            payload = payload.get("messages", [])
        return payload if isinstance(payload, list) else []

    def search(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        query_lower = query.lower().strip()
        messages = self._load_messages()
        if query_lower:
            messages = [
                item for item in messages
                if query_lower in json.dumps(item, ensure_ascii=False).lower()
            ]
        return messages[: self._safe_limit(limit)]

    def summarize(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        messages = self.search(query=query, limit=limit)
        action_items = []
        for item in messages:
            subject = item.get("subject", "(no subject)")
            sender = item.get("from", "unknown")
            snippet = item.get("snippet") or item.get("body", "")
            action_items.append({
                "thread_id": item.get("thread_id") or item.get("id", ""),
                "priority": self._classify_priority(item),
                "summary": f"{sender}: {subject} - {snippet[:160]}",
            })
        return {
            "query": query,
            "count": len(messages),
            "action_items": action_items,
        }

    def sync_snapshot(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        if self.mode == "gmail_api":
            service = self._build_gmail_service()
            if service is not None:
                try:
                    messages = self._sync_snapshot_from_service(service, query=query, limit=limit)
                    self.seed_snapshot(messages)
                    return {
                        "provider": "gmail",
                        "mode": "gmail_api",
                        "query": query,
                        "count": len(messages),
                        "messages": messages,
                    }
                except Exception as exc:
                    return self._local_snapshot_result(query, limit, error=f"{exc.__class__.__name__}: {exc}")
        return self._local_snapshot_result(query, limit)

    def fetch_thread(self, thread_id: str) -> dict[str, Any]:
        if self.mode == "gmail_api":
            service = self._build_gmail_service()
            if service is not None:
                try:
                    thread = service.users().threads().get(
                        userId="me",
                        id=thread_id,
                        format="full",
                    ).execute()
                    messages = [
                        self._normalize_gmail_message(item)
                        for item in thread.get("messages", [])
                    ]
                    return {
                        "provider": "gmail",
                        "mode": "gmail_api",
                        "thread_id": thread.get("id", thread_id),
                        "messages": messages,
                        "count": len(messages),
                    }
                except Exception as exc:
                    return self._fetch_thread_from_snapshot(thread_id, error=f"{exc.__class__.__name__}: {exc}")
        return self._fetch_thread_from_snapshot(thread_id)

    def _local_snapshot_result(self, query: str, limit: int, error: str = "") -> dict[str, Any]:
        messages = self.search(query=query, limit=limit)
        return {
            "provider": "gmail",
            "mode": "local_log",
            "query": query,
            "count": len(messages),
            "messages": messages,
            "fallback_reason": error,
        }

    def _fetch_thread_from_snapshot(self, thread_id: str, error: str = "") -> dict[str, Any]:
        messages = [
            item for item in self._load_messages()
            if item.get("thread_id") == thread_id or item.get("id") == thread_id
        ]
        return {
            "provider": "gmail",
            "mode": "local_log",
            "thread_id": thread_id,
            "messages": messages,
            "count": len(messages),
            "fallback_reason": error,
        }

    def _sync_snapshot_from_service(self, service: Any, query: str, limit: int) -> list[dict[str, Any]]:
        response = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=self._safe_limit(limit),
        ).execute()
        summaries = response.get("messages", []) or []
        messages = []
        for item in summaries[: self._safe_limit(limit)]:
            message_id = item.get("id")
            if not message_id:
                continue
            raw_message = service.users().messages().get(
                userId="me",
                id=message_id,
                format="full",
            ).execute()
            messages.append(self._normalize_gmail_message(raw_message))
        return messages

    def _normalize_gmail_message(self, raw: dict[str, Any]) -> dict[str, Any]:
        headers = {
            item.get("name", "").lower(): item.get("value", "")
            for item in raw.get("payload", {}).get("headers", [])
            if isinstance(item, dict)
        }
        return {
            "id": raw.get("id", ""),
            "thread_id": raw.get("threadId", raw.get("thread_id", "")),
            "from": headers.get("from", raw.get("from", "")),
            "to": headers.get("to", raw.get("to", "")),
            "subject": headers.get("subject", raw.get("subject", "")),
            "date": headers.get("date", raw.get("date", "")),
            "snippet": raw.get("snippet", ""),
            "label_ids": raw.get("labelIds", raw.get("label_ids", [])),
        }

    def _safe_limit(self, limit: int) -> int:
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return 10

    def _classify_priority(self, message: dict[str, Any]) -> str:
        sample = json.dumps(message, ensure_ascii=False).lower()
        if any(term in sample for term in ["urgent", "asap", "overdue", "blocked"]):
            return "high"
        if any(term in sample for term in ["invoice", "interview", "meeting", "deadline"]):
            return "medium"
        return "normal"

    def draft_reply(self, to: str, subject: str, body: str, thread_id: str = "") -> dict[str, Any]:
        task = self.task_store.create_task(
            title=f"Draft email reply to {to}",
            kind="email",
            payload={
                "provider": "gmail",
                "to": to,
                "subject": subject,
                "body": body,
                "thread_id": thread_id,
            },
            status="waiting_for_approval",
        )
        approval = self.task_store.create_approval(
            task["id"],
            action="email_send",
            risk=RISK_RISKY_WRITE,
            summary=f"Send Gmail reply to {to}: {subject}",
            payload=task["payload"],
        )
        return {"task": task, "approval": approval}

    def _resolve_approval(self, approval_or_task_id: str) -> dict[str, Any] | None:
        approval = self.task_store.get_approval(approval_or_task_id)
        if approval:
            return approval

        matches = [
            item for item in self.task_store.list_approvals()
            if item.get("task_id") == approval_or_task_id
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def send_approved(self, approval_id: str) -> dict[str, Any]:
        approval = self._resolve_approval(approval_id)
        if not approval:
            raise KeyError(f"Unknown approval: {approval_id}")
        if approval.get("status") != "approved":
            raise PermissionError(f"Approval {approval['id']} is not approved.")

        payload = approval.get("payload", {})
        sent = {
            "id": f"sent_{uuid.uuid4().hex[:12]}",
            "provider": "gmail",
            "approval_id": approval["id"],
            "to": payload.get("to", ""),
            "subject": payload.get("subject", ""),
            "body": payload.get("body", ""),
            "thread_id": payload.get("thread_id", ""),
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mode": "local_log",
        }
        if self.mode == "gmail_api":
            service = self._build_gmail_service()
            if service is not None:
                sent = self._send_with_gmail_api(service, approval, payload)

        existing = []
        if self.sent_path.exists():
            with self.sent_path.open("r", encoding="utf-8") as handle:
                existing = json.load(handle) or []
        existing.append(sent)
        with self.sent_path.open("w", encoding="utf-8") as handle:
            json.dump(existing, handle, indent=2)

        self.task_store.mark_approval_used(approval["id"])
        if sent["mode"] == "gmail_api":
            summary = "Email sent through Gmail API."
            step = "Email sent through Gmail API."
        else:
            summary = "Email send recorded."
            step = "Email send recorded in local log."
        self.task_store.update_task(approval["task_id"], status="completed", summary=summary)
        self.task_store.add_step(approval["task_id"], step, kind="email")
        return sent

    def _send_with_gmail_api(self, service: Any, approval: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        message = EmailMessage()
        message["To"] = payload.get("to", "")
        message["Subject"] = payload.get("subject", "")
        message.set_content(payload.get("body", ""))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        body: dict[str, Any] = {"raw": raw}
        if payload.get("thread_id"):
            body["threadId"] = payload["thread_id"]
        response = service.users().messages().send(userId="me", body=body).execute()
        return {
            "id": response.get("id", f"sent_{uuid.uuid4().hex[:12]}"),
            "provider": "gmail",
            "approval_id": approval["id"],
            "to": payload.get("to", ""),
            "subject": payload.get("subject", ""),
            "body": payload.get("body", ""),
            "thread_id": response.get("threadId", payload.get("thread_id", "")),
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mode": "gmail_api",
        }

    def seed_snapshot(self, messages: list[dict[str, Any]]) -> None:
        with self.snapshot_path.open("w", encoding="utf-8") as handle:
            json.dump(messages, handle, indent=2)
