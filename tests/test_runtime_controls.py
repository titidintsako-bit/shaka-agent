import json
import sys
import types
import threading

from click.testing import CliRunner

from shaka import cli as cli_module
from shaka.config import DataPaths, ShakaConfig
from shaka.credentials import CredentialStore
from shaka.daemon import DaemonManager, DaemonSchedulerLoop


def test_credential_cli_stores_and_masks_secret(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["credentials", "set", "groq", "--value", "sk-test-secret-1234"])
    listed = runner.invoke(cli_module.cli, ["credentials", "list"])

    assert result.exit_code == 0, result.output
    assert listed.exit_code == 0, listed.output
    assert "sk-test-secret-1234" not in result.output
    assert "sk-test-secret-1234" not in listed.output
    assert "********1234" in listed.output
    assert CredentialStore(str(tmp_path)).get("groq") == "sk-test-secret-1234"


def test_credential_cli_delete_removes_secret(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    CredentialStore(str(tmp_path)).set("groq", "sk-test-secret-1234")

    result = CliRunner().invoke(cli_module.cli, ["credentials", "delete", "groq"])

    assert result.exit_code == 0, result.output
    assert CredentialStore(str(tmp_path)).get("groq") == ""


def test_daemon_install_records_command_without_starting_process(tmp_path):
    manager = DaemonManager(str(tmp_path))

    installed = manager.install(host="127.0.0.1", port=18789)
    status = manager.status()

    assert installed["installed"] is True
    assert installed["port"] == 18789
    assert status["running"] is False
    assert "gateway" in installed["command"]


def test_daemon_cli_status_outputs_json(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    result = CliRunner().invoke(cli_module.cli, ["daemon", "status"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["running"] is False


def test_dashboard_cli_starts_with_gateway_token_auth(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    calls = {}

    import shaka.dashboard.app as dashboard_app

    def fake_create_app(config_path=None, config=None, gateway_token=None, require_token=False):
        calls["config_path"] = config_path
        calls["gateway_token"] = gateway_token
        calls["require_token"] = require_token
        return object()

    def fake_serve(app, host, port):
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(dashboard_app, "create_app", fake_create_app)
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=fake_serve))

    result = CliRunner().invoke(cli_module.cli, ["dashboard", "--host", "0.0.0.0", "--port", "18000"])

    assert result.exit_code == 0, result.output
    assert calls["require_token"] is True
    assert calls["gateway_token"]
    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 18000
    assert "token=" in result.output


def test_gateway_cli_starts_and_stops_scheduler_with_server(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    events = []

    import shaka.dashboard.app as dashboard_app
    import shaka.daemon as daemon_module

    class FakeScheduler:
        def start(self):
            events.append("start")
            return threading.Thread()

        def stop(self):
            events.append("stop")

    def fake_create_app(*args, **kwargs):
        return object()

    def fake_serve(app, host, port):
        events.append(("serve", host, port))

    monkeypatch.setattr(dashboard_app, "create_app", fake_create_app)
    monkeypatch.setattr(DaemonSchedulerLoop, "start", FakeScheduler().start)
    monkeypatch.setattr(DaemonSchedulerLoop, "stop", FakeScheduler().stop)
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=fake_serve))

    result = CliRunner().invoke(cli_module.cli, ["gateway", "--host", "127.0.0.1", "--port", "18001", "--hide-token"])

    assert result.exit_code == 0, result.output
    assert events[0] == "start"
    assert ("serve", "127.0.0.1", 18001) in events
    assert events[-1] == "stop"


def test_demo_local_project_creates_workspace_workflow(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    result = CliRunner().invoke(cli_module.cli, ["demo", "local-project", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["build"]["status"] == "completed"
    assert data["workflow"]["status"] == "waiting_for_approval"
