import json

from click.testing import CliRunner

from shaka import cli as cli_module
from shaka.config import DataPaths, ShakaConfig
from shaka.cron import CronStore


def test_cron_store_adds_due_job_and_records_run(tmp_path):
    store = CronStore(str(tmp_path))
    job = store.add_job("tests", "@every 1m", "python -m pytest tests/test_basic.py")

    due = store.due_jobs(now=job["next_run_at"])
    run = store.record_run(job["id"], status="completed", task_id="task_123")

    assert due[0]["id"] == job["id"]
    assert run["last_status"] == "completed"
    assert run["last_task_id"] == "task_123"
    assert run["run_count"] == 1


def test_cron_cli_add_list_and_run_once(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)

    runner = CliRunner()
    added = runner.invoke(
        cli_module.cli,
        ["cron", "add", "doctor", "--schedule", "@hourly", "--command", "python -m compileall shaka"],
    )
    listed = runner.invoke(cli_module.cli, ["cron", "list", "--json"])
    job_id = json.loads(listed.output)[0]["id"]
    run = runner.invoke(cli_module.cli, ["cron", "run", job_id, "--dry-run"])

    assert added.exit_code == 0, added.output
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["name"] == "doctor"
    assert run.exit_code == 0, run.output
    assert "Dry run" in run.output


def test_cron_tick_runs_due_allowlisted_job(tmp_path):
    store = CronStore(str(tmp_path))
    job = store.add_job("compile", "@every 1m", "python -m compileall shaka", cwd=".")
    job["next_run_at"] = "2000-01-01T00:00:00Z"
    store.update_job(job)

    result = store.tick(now="2000-01-01T00:00:00Z")

    assert result["checked"] == 1
    assert result["ran"] == 1
    assert result["results"][0]["status"] in {"completed", "failed"}
