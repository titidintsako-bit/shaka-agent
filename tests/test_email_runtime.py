"""Tests for Gmail workflow safety."""

import pytest

from shaka.email_runtime import GmailRuntime


def _missing_google_dependencies(self):
    return {
        "available": False,
        "reason": "missing test dependency",
        "Request": None,
        "Credentials": None,
        "build": None,
    }


def test_gmail_draft_requires_approval_before_send(tmp_path):
    gmail = GmailRuntime(str(tmp_path))
    result = gmail.draft_reply("dev@example.com", "Interview", "Thanks for reaching out.")
    approval_id = result["approval"]["id"]

    with pytest.raises(PermissionError):
        gmail.send_approved(approval_id)

    gmail.task_store.approve(approval_id)
    sent = gmail.send_approved(approval_id)

    assert sent["to"] == "dev@example.com"
    assert sent["mode"] == "local_log"


def test_gmail_search_and_summarize_snapshot(tmp_path):
    gmail = GmailRuntime(str(tmp_path))
    gmail.seed_snapshot([
        {"id": "1", "from": "recruiter@example.com", "subject": "Interview", "snippet": "Can we meet tomorrow?"},
        {"id": "2", "from": "friend@example.com", "subject": "Lunch", "snippet": "Food?"},
    ])

    matches = gmail.search("interview")
    summary = gmail.summarize("interview")

    assert len(matches) == 1
    assert summary["count"] == 1
    assert summary["action_items"][0]["priority"] == "medium"


def test_gmail_send_accepts_task_id_for_single_approval(tmp_path):
    gmail = GmailRuntime(str(tmp_path))
    result = gmail.draft_reply("dev@example.com", "Hello", "Draft body")
    task_id = result["task"]["id"]
    approval_id = result["approval"]["id"]

    gmail.task_store.approve(approval_id)
    sent = gmail.send_approved(task_id)

    assert sent["approval_id"] == approval_id
    assert sent["to"] == "dev@example.com"


def test_gmail_connection_status_reports_missing_google_libs_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(GmailRuntime, "_google_dependencies", _missing_google_dependencies)
    gmail = GmailRuntime(str(tmp_path), mode="gmail_api")
    gmail.token_path.write_text("{}", encoding="utf-8")

    status = gmail.connection_status()
    instructions = gmail.setup_instructions()

    assert status["status"] == "unavailable"
    assert status["google_dependencies_available"] is False
    assert status["can_use_gmail_api"] is False
    assert instructions["scopes"]["read"] == GmailRuntime.READ_SCOPES
    assert instructions["scopes"]["send"] == GmailRuntime.SEND_SCOPES
    assert "revoke()" in instructions["revoke"]["method"]


def test_gmail_revoke_removes_local_token_when_google_libs_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(GmailRuntime, "_google_dependencies", _missing_google_dependencies)
    gmail = GmailRuntime(str(tmp_path), mode="gmail_api")
    gmail.token_path.write_text("{}", encoding="utf-8")

    result = gmail.revoke()

    assert result["status"] == "not_connected"
    assert result["removed_local_token"] is True
    assert result["revoked_remote"] is False
    assert not gmail.token_path.exists()


def test_gmail_fetch_thread_uses_local_snapshot_by_default(tmp_path):
    gmail = GmailRuntime(str(tmp_path))
    gmail.seed_snapshot([
        {"id": "1", "thread_id": "thread-a", "subject": "First", "snippet": "One"},
        {"id": "2", "thread_id": "thread-a", "subject": "Second", "snippet": "Two"},
        {"id": "3", "thread_id": "thread-b", "subject": "Third", "snippet": "Three"},
    ])

    thread = gmail.fetch_thread("thread-a")

    assert thread["mode"] == "local_log"
    assert thread["count"] == 2
    assert [item["id"] for item in thread["messages"]] == ["1", "2"]


def test_gmail_sync_snapshot_falls_back_to_local_snapshot_when_api_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(GmailRuntime, "_google_dependencies", _missing_google_dependencies)
    gmail = GmailRuntime(str(tmp_path), mode="gmail_api")
    gmail.seed_snapshot([
        {"id": "1", "thread_id": "thread-a", "subject": "Interview", "snippet": "Meet tomorrow"},
        {"id": "2", "thread_id": "thread-b", "subject": "Lunch", "snippet": "Food"},
    ])

    result = gmail.sync_snapshot(query="interview", limit=10)

    assert result["mode"] == "local_log"
    assert result["count"] == 1
    assert result["messages"][0]["id"] == "1"


def test_gmail_sync_snapshot_can_use_stubbed_gmail_service(tmp_path, monkeypatch):
    class Execute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class Messages:
        def list(self, **kwargs):
            assert kwargs["q"] == "interview"
            return Execute({"messages": [{"id": "api-1"}]})

        def get(self, **kwargs):
            assert kwargs["id"] == "api-1"
            return Execute({
                "id": "api-1",
                "threadId": "api-thread",
                "snippet": "API snippet",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "recruiter@example.com"},
                        {"name": "Subject", "value": "Interview"},
                    ],
                },
            })

    class Users:
        def messages(self):
            return Messages()

    class Service:
        def users(self):
            return Users()

    monkeypatch.setattr(GmailRuntime, "_build_gmail_service", lambda self: Service())
    gmail = GmailRuntime(str(tmp_path), mode="gmail_api")

    result = gmail.sync_snapshot(query="interview")

    assert result["mode"] == "gmail_api"
    assert result["count"] == 1
    assert result["messages"][0]["thread_id"] == "api-thread"
    assert gmail.search("api snippet")[0]["id"] == "api-1"
