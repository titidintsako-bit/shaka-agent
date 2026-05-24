import json

from shaka.config import DataPaths, ShakaConfig, load_config
from shaka.credentials import CredentialStore
from shaka.dashboard.app import create_app
from shaka.local_state import LOCAL_STATE_DIRS, ensure_local_state, runtime_status


def test_ensure_local_state_creates_layout_and_config(tmp_path):
    home = tmp_path / "home"

    data = ensure_local_state(home, provider="ollama", model="qwen2.5:7b")

    for dirname in LOCAL_STATE_DIRS:
        assert (home / dirname).is_dir()
    assert (home / "config.json").exists()
    assert data["gateway"]["token"]
    assert "api_key" not in data["model"]

    config = load_config(str(home / "config.json"))

    assert config.paths.base_dir == str(home)
    assert config.model.provider == "ollama"
    assert config.model.model == "qwen2.5:7b"
    assert config.dashboard.host == "127.0.0.1"
    assert config.dashboard.port == 18789


def test_gateway_runtime_status_requires_token(tmp_path):
    home = tmp_path / "home"
    local = ensure_local_state(home, provider="groq", model="llama-3.3-70b-versatile")
    config = ShakaConfig(paths=DataPaths(base_dir=str(home)))
    config.model.provider = "groq"
    config.model.model = "llama-3.3-70b-versatile"
    config.dashboard.host = "127.0.0.1"
    config.dashboard.port = 18789

    app = create_app(config=config, gateway_token=local["gateway"]["token"], require_token=True)
    client = app.test_client()

    health = client.get("/health")
    blocked = client.get("/api/runtime/status")
    allowed = client.get("/api/runtime/status", headers={"X-Shaka-Token": local["gateway"]["token"]})

    assert health.status_code == 200
    assert health.get_json()["auth_required"] is True
    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.get_json()["workspace_path"] == str(home / "workspace")


def test_local_config_does_not_store_secret_values(tmp_path):
    home = tmp_path / "home"

    ensure_local_state(home, provider="groq", api_key_env="SHAKA_API_KEY")
    data = json.loads((home / "config.json").read_text(encoding="utf-8"))

    assert data["model"]["api_key_env"] == "SHAKA_API_KEY"
    assert "api_key" not in data["model"]
    assert data["security"]["store_secrets_in_config"] is False


def test_runtime_status_reports_credentials_without_secret(tmp_path):
    home = tmp_path / "home"
    ensure_local_state(home)
    CredentialStore(str(home)).set("groq", "sk-test-secret-1234")
    config = ShakaConfig(paths=DataPaths(base_dir=str(home)))

    status = runtime_status(config)

    assert status["credential_count"] == 1
    assert status["credentials"][0]["fingerprint"] == "********1234"
    assert "sk-test-secret-1234" not in json.dumps(status)
