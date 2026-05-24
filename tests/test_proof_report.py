import json

from click.testing import CliRunner

from shaka import cli as cli_module
from shaka.automation import TaskStore
from shaka.config import DataPaths, ShakaConfig
from shaka.credentials import CredentialStore
from shaka.cron import CronStore
from shaka.local_state import ensure_local_state
from shaka.proof import ProofExporter


def _config_for(home):
    config = ShakaConfig(paths=DataPaths(base_dir=str(home)))
    config.model.provider = "ollama"
    config.model.model = "qwen2.5:7b"
    config.dashboard.host = "127.0.0.1"
    config.dashboard.port = 18789
    return config


def test_proof_exporter_builds_local_first_markdown_without_secrets(tmp_path):
    home = tmp_path / "home"
    ensure_local_state(home, provider="ollama", model="qwen2.5:7b")
    CredentialStore(str(home)).set("ollama", "local-secret-1234")
    task_store = TaskStore(str(home))
    task = task_store.create_task("Inspect local project", "demo", status="completed")
    task_store.update_task(task["id"], summary="Project files inspected.")
    task_store.create_approval(task["id"], "email_send", "risky_write", "Send drafted update")
    CronStore(str(home)).add_job("nightly proof", "@daily", "python -m shaka.cli proof export")

    exporter = ProofExporter(_config_for(home))
    report = exporter.build()
    markdown = exporter.to_markdown(report)

    assert report["local_first"] is True
    assert report["counts"]["tasks"] == 1
    assert report["counts"]["pending_approvals"] == 1
    assert report["counts"]["cron_jobs"] == 1
    capability_names = {item["name"] for item in report["capabilities"]}
    assert {"Local memory", "Skills", "Approval gates", "Cron scheduling", "MCP server"}.issubset(capability_names)
    assert "# Shaka Local Runtime Proof" in markdown
    assert "## Capability matrix" in markdown
    assert "## Installed skills" in markdown
    assert "Approval gates" in markdown
    assert "MCP server" in markdown
    assert "fileops" in markdown
    assert "codeexec" in markdown
    assert "mutating" in markdown
    assert "needed" in markdown
    assert "risky_write" in markdown
    skills = {item["name"]: item for item in report["skills"]}
    assert skills["fileops"]["mutating"] is True
    assert skills["fileops"]["approval_required"] is True
    assert skills["codeexec"]["mutating"] is True
    assert skills["codeexec"]["approval_required"] is True
    assert str(home / "workspace") in markdown
    assert "ollama / qwen2.5:7b" in markdown
    assert "Inspect local project" in markdown
    assert "nightly proof" in markdown
    assert "python -m shaka.cli proof export" in markdown
    assert "local-secret-1234" not in markdown


def test_proof_exporter_writes_markdown_and_json(tmp_path):
    home = tmp_path / "home"
    ensure_local_state(home, provider="ollama", model="qwen2.5:7b")
    exporter = ProofExporter(_config_for(home))

    markdown_path = exporter.export_markdown(home / "runtime" / "proof.md")
    json_payload = exporter.to_json(exporter.build())

    assert markdown_path.exists()
    assert "# Shaka Local Runtime Proof" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_payload)["provider"]["provider"] == "ollama"


def test_proof_cli_export_writes_report(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ensure_local_state(home, provider="ollama", model="qwen2.5:7b")
    config = _config_for(home)
    output = tmp_path / "proof.md"
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    result = CliRunner().invoke(cli_module.cli, ["proof", "export", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert "Proof report written:" in result.output
    assert output.exists()
    assert "Local-first architecture" in output.read_text(encoding="utf-8")


def test_proof_cli_export_json_prints_payload(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ensure_local_state(home, provider="ollama", model="qwen2.5:7b")
    config = _config_for(home)
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    result = CliRunner().invoke(cli_module.cli, ["proof", "export", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["home"] == str(home)
