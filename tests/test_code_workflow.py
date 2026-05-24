from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shaka.agent import Agent
from shaka import cli as cli_module
from shaka.code_workflow import RepoContextBuilder
from shaka.connectors import GitHubIssueSource, collect_connector_context
from shaka.config import ShakaConfig
from shaka.memory import MemoryManager
from shaka.skills import SkillsRegistry


def test_repo_context_builder_includes_key_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "shaka").mkdir()
    (tmp_path / "shaka" / "cli.py").write_text("print('cli')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    builder = RepoContextBuilder(tmp_path, focus_path=tmp_path / "shaka" / "cli.py", max_files=5, max_lines=20)

    tree = builder.build_tree()
    context = builder.build_context()
    prompt = builder.build_task_prompt("fix the cli")

    assert "README.md" in tree
    assert "cli.py" in context
    assert "fix the cli" in prompt
    assert "Repository tree" in prompt


def test_repo_context_builder_modes_are_distinct(tmp_path: Path) -> None:
    builder = RepoContextBuilder(tmp_path)

    plan_prompt = builder.coding_system_prompt("plan")
    review_prompt = builder.coding_system_prompt("review")
    build_prompt = builder.coding_system_prompt("build")

    assert "plan mode" in plan_prompt.lower()
    assert "review mode" in review_prompt.lower()
    assert "build mode" in build_prompt.lower()
    assert "plan" in builder.response_schema("plan").lower()
    assert "findings" in builder.response_schema("review").lower()
    assert "edits" in builder.response_schema("build").lower()


def test_agent_passes_extra_system_messages(tmp_path: Path) -> None:
    class Model:
        provider = "ollama"
        model = "qwen2.5:7b"
        api_key = ""
        base_url = "http://localhost:11434"

    config = ShakaConfig()
    config.model = Model()
    config.paths.base_dir = str(tmp_path)

    memory = MemoryManager(str(tmp_path))
    skills = SkillsRegistry()
    agent = Agent(config, skills, memory)

    captured = {}

    class FakeProvider:
        def generate(self, messages, tools=None, model=None):
            captured["messages"] = messages
            return {"content": "ok", "tool_calls": [], "tokens_used": 1}

    agent.provider = FakeProvider()
    result = agent.chat("hello", extra_system_messages=["extra-coding-context"])

    assert result["response"] == "ok"
    assert any(msg["content"] == "extra-coding-context" for msg in captured["messages"] if msg["role"] == "system")


def test_agent_can_disable_tools(tmp_path: Path) -> None:
    class Model:
        provider = "ollama"
        model = "qwen2.5:7b"
        api_key = ""
        base_url = "http://localhost:11434"

    config = ShakaConfig()
    config.model = Model()
    config.paths.base_dir = str(tmp_path)

    memory = MemoryManager(str(tmp_path))
    skills = SkillsRegistry()
    agent = Agent(config, skills, memory)

    captured = {}

    class FakeProvider:
        def generate(self, messages, tools=None, model=None):
            captured["tools"] = tools
            return {"content": "ok", "tool_calls": [], "tokens_used": 1}

    agent.provider = FakeProvider()
    agent.chat("hello", disable_tools=True)

    assert captured["tools"] is None


def test_code_command_review_mode_is_read_only(tmp_path: Path, monkeypatch) -> None:
    class Model:
        provider = "ollama"
        model = "qwen2.5:7b"
        api_key = ""
        base_url = "http://localhost:11434"

    config = ShakaConfig()
    config.model = Model()
    config.paths.base_dir = str(tmp_path)

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def chat(self, message, session_id=None, extra_system_messages=None, disable_tools=False):
            self.calls.append(
                {
                    "message": message,
                    "session_id": session_id,
                    "extra_system_messages": extra_system_messages,
                    "disable_tools": disable_tools,
                }
            )
            return {
                "response": '{"summary":"review ok","findings":[{"priority":"P2","file":"shaka/tui.py","line":12,"body":"small issue"}],"tests":[],"notes":[]}',
                "tokens_used": 1,
                "elapsed_seconds": 0.1,
                "session_id": session_id or "session_1",
                "tool_calls_executed": 0,
            }

    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    monkeypatch.setattr(cli_module, "Agent", FakeAgent)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        ["code", "--mode", "review", "--path", str(tmp_path), "check", "layout"],
    )

    assert result.exit_code == 0, result.output
    assert "Mode: review" in result.output
    assert "Findings:" in result.output
    assert "This mode is read-only" in result.output


def test_repo_context_builder_applies_unified_patch(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    target = tmp_path / "hello.txt"
    target.write_text("old\n", encoding="utf-8")

    patch = """\
diff --git a/hello.txt b/hello.txt
index 3367afdb..b77b4a5c 100644
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-old
+new
"""
    builder = RepoContextBuilder(tmp_path)
    result = builder.apply_unified_patch(patch)

    assert "git apply succeeded" in result
    assert target.read_text(encoding="utf-8") == "new\n"


def test_collect_connector_context_reads_file_and_issue(monkeypatch, tmp_path: Path) -> None:
    ctx_file = tmp_path / "context.md"
    ctx_file.write_text("Focus on the auth flow.", encoding="utf-8")

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        if url.endswith("/comments"):
            return Response([{"user": {"login": "reviewer"}, "body": "Please keep this small."}])
        return Response({
            "title": "Fix login bug",
            "body": "Users cannot sign in.",
            "labels": [{"name": "bug"}],
        })

    monkeypatch.setattr("shaka.connectors.requests.get", fake_get)

    contexts = collect_connector_context(
        issue_url="https://github.com/example/demo/issues/12",
        context_file=ctx_file,
        extra_notes=["Do not change API shapes."],
    )

    labels = {item.label for item in contexts}
    joined = "\n".join(item.text for item in contexts)

    assert "file:context.md" in labels
    assert "github" in labels
    assert "note" in labels
    assert "Fix login bug" in joined
    assert "Focus on the auth flow." in joined
    assert "Do not change API shapes." in joined
    assert any(url.endswith("/issues/12") for url in calls)


def test_code_command_collects_clarifying_context(tmp_path: Path, monkeypatch) -> None:
    class Model:
        provider = "ollama"
        model = "qwen2.5:7b"
        api_key = ""
        base_url = "http://localhost:11434"

    config = ShakaConfig()
    config.model = Model()
    config.paths.base_dir = str(tmp_path)

    recorded = {}

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, message, session_id=None, extra_system_messages=None, disable_tools=False):
            recorded["extra_system_messages"] = extra_system_messages
            recorded["disable_tools"] = disable_tools
            return {
                "response": '{"summary":"ok","edits":[],"patches":[],"tests":[],"notes":[]}',
                "tokens_used": 1,
                "elapsed_seconds": 0.1,
                "session_id": session_id or "session_1",
                "tool_calls_executed": 0,
            }

    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    monkeypatch.setattr(cli_module, "Agent", FakeAgent)
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: True)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        ["code", "--mode", "build", "--path", str(tmp_path), "update", "docs"],
        input="src/app.py\nKeep the public API stable.\nDo not change tests.\n",
    )

    assert result.exit_code == 0, result.output
    joined = "\n".join(recorded["extra_system_messages"])
    assert "User-provided context" in joined
    assert "Keep the public API stable." in joined
    assert recorded["disable_tools"] is False
