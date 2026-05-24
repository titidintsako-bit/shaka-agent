from __future__ import annotations

from rich.console import Console

import shaka.tui as tui_module
from shaka.automation import TaskStore


class MockAgent:
    def __init__(self):
        self.total_tokens = 0
        self.skills_registry = None
        self.memory = None
        self.user_id = "default"

    def chat(self, message, session_id=None, extra_system_messages=None, disable_tools=False):
        return {
            "response": '{"summary":"review ok","findings":[{"priority":"P2","file":"shaka/tui.py","line":12,"body":"small issue"}],"tests":[],"notes":[]}',
            "tokens_used": 3,
            "elapsed_seconds": 0.2,
            "session_id": session_id or "session_1",
            "tool_calls_executed": 0,
        }


class MockConfig:
    def __init__(self, base_dir="."):
        self.language = "en"

        class Model:
            provider = "ollama"
            model = "qwen2.5:7b"
            api_key = ""
            base_url = "http://localhost:11434"

        self.model = Model()
        self.paths = type("P", (), {"base_dir": str(base_dir)})()


def render_text(renderable):
    console = Console(width=180, record=True)
    console.print(renderable)
    return console.export_text()


def test_tui_review_command_records_review_results():
    class FakeBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def coding_system_prompt(self, mode="review"):
            return "review prompt"

        def build_task_prompt(self, task, mode="review"):
            return f"task:{task}"

        def response_schema(self, mode="review"):
            return "schema"

    original_builder = tui_module.RepoContextBuilder
    tui_module.RepoContextBuilder = FakeBuilder
    try:
        tui = tui_module.ShakaTUI(MockAgent(), MockConfig())
        handled = tui._handle_command("/review check the code style")
    finally:
        tui_module.RepoContextBuilder = original_builder

    assert handled is True
    assert tui.last_review is not None
    assert tui.last_review["summary"] == "review ok"
    assert tui.last_review["findings"][0]["body"] == "small issue"


def test_tui_code_command_routes_through_code_workflow():
    class FakeBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def coding_system_prompt(self, mode="build"):
            return f"{mode}-prompt"

        def build_task_prompt(self, task, mode="build"):
            return f"task:{task}"

        def response_schema(self, mode="build"):
            return "schema"

    class FakeAgent(MockAgent):
        def __init__(self):
            super().__init__()
            self.last_call = None

        def chat(self, message, session_id=None, extra_system_messages=None, disable_tools=False):
            self.last_call = {
                "message": message,
                "extra_system_messages": extra_system_messages,
                "disable_tools": disable_tools,
            }
            return {
                "response": '{"summary":"done","edits":[],"patches":[],"tests":[],"notes":[]}',
                "tokens_used": 4,
                "elapsed_seconds": 0.2,
                "session_id": session_id or "session_1",
                "tool_calls_executed": 0,
            }

    original_builder = tui_module.RepoContextBuilder
    tui_module.RepoContextBuilder = FakeBuilder
    try:
        agent = FakeAgent()
        tui = tui_module.ShakaTUI(agent, MockConfig())
        handled = tui._handle_command("/code update the README")
    finally:
        tui_module.RepoContextBuilder = original_builder

    assert handled is True
    assert agent.last_call is not None
    assert agent.last_call["disable_tools"] is False
    joined = "\n".join(agent.last_call["extra_system_messages"])
    assert "build-prompt" in joined


def test_tui_onboard_command_marks_completion():
    class FakeMemory:
        def __init__(self):
            self.prefs = {}

        def get_preferences(self, user_id):
            return self.prefs.get(user_id, {})

        def set_preference(self, user_id, key, value):
            self.prefs.setdefault(user_id, {})[key] = value

    class FakeAgent(MockAgent):
        def __init__(self):
            super().__init__()
            self.memory = FakeMemory()

    tui = tui_module.ShakaTUI(FakeAgent(), MockConfig())
    handled = tui._handle_command("/onboard complete")

    assert handled is True
    assert tui.agent.memory.get_preferences("default")["onboarding_completed"] is True


def test_tui_tasks_and_approvals_show_status_risk_summary_and_hints(tmp_path):
    store = TaskStore(str(tmp_path))
    failed = store.create_task("Broken deployment", "web", status="failed")
    store.update_task(failed["id"], error="npm test failed", summary="Deploy failed")
    waiting = store.create_task("Send draft", "email")
    approval = store.create_approval(waiting["id"], "email_send", "external_send", "Send email to user")

    tui = tui_module.ShakaTUI(MockAgent(), MockConfig(tmp_path))

    tasks_text = render_text(tui.render_tasks_panel())
    approvals_text = render_text(tui.render_approvals_panel())

    assert failed["id"] in tasks_text
    assert "failed" in tasks_text
    assert "Deploy failed" in tasks_text
    assert f"/retry {failed['id']}" in tasks_text
    assert approval["id"] in approvals_text
    assert "external_send" in approvals_text
    assert "Send email to user" in approvals_text
    assert f"/approve {approval['id']}" in approvals_text
    assert f"/reject {approval['id']} <reason>" in approvals_text


def test_tui_reject_retry_and_task_commands_update_task_store(tmp_path):
    store = TaskStore(str(tmp_path))
    waiting = store.create_task("Approval gated action", "web")
    approval = store.create_approval(waiting["id"], "deploy", "risky_write", "Deploy the app")
    failed = store.create_task("Failed job", "web", status="failed")

    outputs = []
    tui = tui_module.ShakaTUI(MockAgent(), MockConfig(tmp_path))
    tui._show_command_output = outputs.append

    assert tui._handle_command(f"/reject {approval['id']} not safe") is True
    assert store.get_approval(approval["id"])["status"] == "rejected"
    assert store.get_task(waiting["id"])["status"] == "cancelled"

    assert tui._handle_command(f"/retry {failed['id']}") is True
    assert store.get_task(failed["id"])["status"] == "queued"

    assert tui._handle_command(f"/task {failed['id']}") is True
    assert "Next:" in render_text(outputs[-1])


def test_tui_repo_memory_help_and_toolbar_include_automation_commands(tmp_path):
    tui = tui_module.ShakaTUI(MockAgent(), MockConfig(tmp_path))
    help_text = render_text(tui.render_help_panel())
    input_text = render_text(tui.render_input_panel())

    assert "/reject <approval_id> [reason]" in help_text
    assert "/retry <task_id>" in help_text
    assert "/repo-memory [path]" in help_text
    assert "/web-verify <url>" in help_text
    assert "/build-site <path> <prompt>" in help_text
    assert "/approve" in input_text
    assert "/web-verify" in input_text


def test_tui_web_verify_and_build_site_commands_route_without_model(tmp_path, monkeypatch):
    class FakeVerifier:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def verify(self, url, use_browser=False):
            return {
                "url": url,
                "ok": True,
                "status_code": 200,
                "response_time_ms": 12.5,
                "task_id": "task_web",
            }

    class FakeBuilder:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def build_site(self, prompt, path):
            return {
                "id": "task_site",
                "status": "completed",
                "summary": f"built {path}: {prompt}",
            }

    import shaka.web_runtime as web_runtime
    import shaka.website_builder as website_builder

    monkeypatch.setattr(web_runtime, "WebVerifier", FakeVerifier)
    monkeypatch.setattr(website_builder, "WebsiteBuilder", FakeBuilder)

    outputs = []
    tui = tui_module.ShakaTUI(MockAgent(), MockConfig(tmp_path))
    tui._show_command_output = outputs.append

    assert tui._handle_command("/web-verify http://example.test") is True
    assert "task_web" in render_text(outputs[-1])

    assert tui._handle_command('/build-site "site dir" landing page') is True
    assert "task_site" in render_text(outputs[-1])
    assert "built site dir: landing page" in render_text(outputs[-1])
