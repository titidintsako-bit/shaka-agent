import json

from click.testing import CliRunner

from shaka import cli as cli_module
from shaka.config import DataPaths, ShakaConfig, load_config, save_config
from shaka.credentials import CredentialStore
from shaka.dashboard.app import create_app
from shaka.local_state import ensure_local_state, provider_status
from shaka.providers import get_provider_spec, provider_names


def test_provider_catalog_includes_local_and_hosted_options():
    names = provider_names()

    assert "ollama" in names
    assert "openai" in names
    assert "anthropic" in names
    assert "groq" in names
    assert get_provider_spec("openrouter").api_key_env == "OPENROUTER_API_KEY"


def test_load_config_uses_provider_specific_env_var(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ensure_local_state(
        home,
        provider="openai",
        model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test-1234")

    config = load_config(str(home / "config.json"))

    assert config.model.provider == "openai"
    assert config.model.api_key == "sk-openai-test-1234"
    assert provider_status(config)["source"] == "environment"


def test_dashboard_message_accepts_local_credential_provider(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ensure_local_state(home, provider="openai", model="gpt-4o-mini")
    CredentialStore(str(home)).set("openai", "sk-openai-test-1234")
    config = load_config(str(home / "config.json"))
    app = create_app(config=config)
    client = app.test_client()

    class FakeAgent:
        def chat(self, message, session_id=None):
            return {
                "session_id": session_id,
                "response": f"echo: {message}",
                "tokens_used": 1,
                "elapsed_seconds": 0.01,
                "tool_calls_executed": 0,
            }

    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    monkeypatch.setattr("shaka.dashboard.app.Agent", lambda *_args, **_kwargs: FakeAgent())

    response = client.post("/api/message", json={"message": "hello"})

    assert response.status_code == 200
    assert response.get_json()["reply"] == "echo: hello"


def test_provider_configure_cli_updates_local_config_without_secret(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    save_config(config, str(tmp_path / "config.json"))
    monkeypatch.setenv("SHAKA_HOME", str(tmp_path))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: load_config(str(tmp_path / "config.json")))

    result = CliRunner().invoke(
        cli_module.cli,
        [
            "providers",
            "configure",
            "anthropic",
            "--model",
            "claude-3-5-haiku-latest",
            "--api-key-env",
            "ANTHROPIC_API_KEY",
        ],
    )
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))

    assert result.exit_code == 0, result.output
    assert data["model"]["provider"] == "anthropic"
    assert data["model"]["model"] == "claude-3-5-haiku-latest"
    assert data["model"]["api_key_env"] == "ANTHROPIC_API_KEY"
    assert "api_key" not in data["model"]
