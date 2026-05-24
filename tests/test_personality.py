from __future__ import annotations

from click.testing import CliRunner

from shaka import cli as cli_module
from shaka.config import ShakaConfig
from shaka.memory import MemoryManager
from shaka.message_builder import MessageBuilder
from shaka.skills import SkillsRegistry
import shaka.tui as tui_module


def test_message_builder_injects_personality_preferences(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path)
    config.personality = {
        "default_profile": "warm, practical, direct",
        "instructions": "Stay concise.",
    }
    memory = MemoryManager(str(tmp_path))
    memory.set_preference("default", "personality", "formal and technical")
    builder = MessageBuilder(config, SkillsRegistry(), memory)

    messages = builder.build_messages("hello", "session_1")
    joined = "\n".join(msg["content"] for msg in messages if msg["role"] == "system")

    assert "Default personality" in joined
    assert "formal and technical" in joined


def test_message_builder_adds_coding_and_research_guidance(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path)
    memory = MemoryManager(str(tmp_path))
    builder = MessageBuilder(config, SkillsRegistry(), memory)

    messages = builder.build_messages("can you research the latest news and build a website?", "session_1")
    joined = "\n".join(msg["content"] for msg in messages if msg["role"] == "system")

    assert "Coding request detected" in joined
    assert "Research request detected" in joined
    assert "websearch" in joined


def test_cli_personality_command_can_set_preference(tmp_path, monkeypatch):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path)
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["personality", "--set", "playful but professional"])

    assert result.exit_code == 0, result.output
    memory = MemoryManager(str(tmp_path))
    assert memory.get_preferences("default")["personality"] == "playful but professional"


def test_cli_personality_command_can_set_preset(tmp_path, monkeypatch):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path)
    config.personality["presets"] = {
        "technical": "Precise and engineering-focused.",
    }
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["personality", "--preset", "technical"])

    assert result.exit_code == 0, result.output
    memory = MemoryManager(str(tmp_path))
    prefs = memory.get_preferences("default")
    assert prefs["personality_preset"] == "technical"
    assert prefs["personality_custom"] == ""


def test_cli_onboard_command_prints_checklist(tmp_path, monkeypatch):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path)
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["onboard"])

    assert result.exit_code == 0, result.output
    assert "SHAKA ONBOARDING" in result.output
    assert "shaka doctor" in result.output


def test_tui_personality_command_sets_memory_preference(tmp_path):
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

    class Agent:
        def __init__(self):
            self.memory = memory
            self.user_id = "default"
            self.skills_registry = skills
            self.total_tokens = 0

        def chat(self, *args, **kwargs):
            return {"response": "ok", "tokens_used": 0, "elapsed_seconds": 0.0, "session_id": "s1", "tool_calls_executed": 0}

    class DummyBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def coding_system_prompt(self, mode="review"):
            return "prompt"

        def build_task_prompt(self, task, mode="review"):
            return "task"

        def response_schema(self, mode="review"):
            return "schema"

    original_builder = tui_module.RepoContextBuilder
    tui_module.RepoContextBuilder = DummyBuilder
    try:
        tui = tui_module.ShakaTUI(Agent(), config)
        handled = tui._handle_command("/personality calm, concise, and practical")
    finally:
        tui_module.RepoContextBuilder = original_builder

    assert handled is True
    assert memory.get_preferences("default")["personality"] == "calm, concise, and practical"
