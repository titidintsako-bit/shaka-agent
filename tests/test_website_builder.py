"""Tests for website builder workflows."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from shaka.web_runtime import WebVerifier
from shaka.website_builder import StackDetector, WebsiteBuilder, inspect_project, plan_checks, record_fix_task


def test_build_site_creates_full_stack_scaffold(tmp_path):
    target = tmp_path / "new-app"
    task = WebsiteBuilder(str(tmp_path)).build_site("developer portfolio app", target)

    assert task["status"] == "completed"
    assert (target / "frontend" / "src" / "App.jsx").exists()
    assert (target / "backend" / "app" / "main.py").exists()
    assert "vite" in StackDetector.detect(target / "frontend")["stack"]
    assert [step["kind"] for step in task["steps"]] == [
        "detect",
        "scaffold",
        "write",
        "write",
        "write",
        "write-summary",
    ]


def test_build_site_writes_portfolio_scaffold_content(tmp_path):
    target = tmp_path / "new-app"
    WebsiteBuilder(str(tmp_path)).build_site("developer portfolio app", target)

    readme = (target / "README.md").read_text(encoding="utf-8")
    app = (target / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    backend = (target / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert "Run the backend" in readme
    assert "Run the frontend" in readme
    assert "Shaka verification commands" in readme
    assert "python -m pytest tests/test_website_builder.py" in readme
    assert "inspect_project" in readme
    assert "plan_checks" in readme
    assert "VITE_API_BASE_URL" in app
    assert "API status" in app
    assert "CORSMiddleware" in backend
    assert '@app.get("/health")' in backend
    assert '@app.get("/api/status")' in backend
    assert "CREATE TABLE IF NOT EXISTS events" in backend


def test_existing_project_is_detected_and_not_overwritten(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "package.json"
    marker.write_text('{"dependencies":{"react":"latest"}}', encoding="utf-8")

    task = WebsiteBuilder(str(tmp_path)).build_site("do not overwrite", target)

    assert task["status"] == "completed"
    assert task["summary"].startswith("Existing project detected")
    assert marker.read_text(encoding="utf-8") == '{"dependencies":{"react":"latest"}}'


def test_inspect_project_recommends_node_commands_from_scripts(tmp_path):
    target = tmp_path / "frontend"
    target.mkdir()
    (target / "package.json").write_text(
        '{"scripts":{"dev":"vite","build":"vite build","test":"vitest"},"dependencies":{"vite":"latest","react":"latest"}}',
        encoding="utf-8",
    )

    result = inspect_project(target)

    assert result["stack"] == ["node", "vite", "react"]
    assert result["package_manager"] == "npm"
    assert result["recommended_commands"] == {
        "install": "npm install",
        "build": "npm run build",
        "test": "npm run test",
        "dev": "npm run dev",
    }


def test_inspect_project_recommends_python_fastapi_commands(tmp_path):
    target = tmp_path / "backend"
    app = target / "app"
    app.mkdir(parents=True)
    (target / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (app / "main.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")

    result = inspect_project(target)

    assert "python" in result["stack"]
    assert "fastapi" in result["stack"]
    assert result["recommended_commands"]["install"] == "python -m pip install -r requirements.txt"
    assert result["recommended_commands"]["test"] == "python -m pytest"
    assert result["recommended_commands"]["dev"] == "python -m uvicorn app.main:app --reload --port 8000"


def test_plan_checks_returns_frontend_backend_command_plan_without_running(tmp_path):
    target = tmp_path / "app"
    WebsiteBuilder(str(tmp_path)).build_site("developer portfolio app", target)

    inspection = inspect_project(target)
    result = plan_checks(target)

    assert {"node", "vite", "react", "python", "fastapi"}.issubset(set(inspection["stack"]))
    assert set(inspection["recommended_commands"]) == {"frontend", "backend"}
    commands = [item["command"] for item in result["checks"]]
    assert "npm install" in commands
    assert "npm run build" in commands
    assert "python -m pip install -r requirements.txt" in commands
    assert "python -m pytest" in commands
    assert all(item["run_by_default"] is False for item in result["checks"])
    assert {item["area"] for item in result["checks"]} == {"frontend", "backend"}


def test_record_fix_task_records_inspect_plan_and_fix_needed_steps(tmp_path):
    target = tmp_path / "app"
    WebsiteBuilder(str(tmp_path)).build_site("developer portfolio app", target)

    task = record_fix_task(target, "frontend build fails", WebsiteBuilder(str(tmp_path)).task_store)

    assert task["kind"] == "website-fix"
    assert task["status"] == "queued"
    assert task["summary"] == "Recorded fix-loop task; no code edits were performed."
    assert task["payload"]["issue"] == "frontend build fails"
    assert [step["kind"] for step in task["steps"]] == ["inspect", "plan", "fix-needed"]
    assert task["steps"][1]["metadata"]["checks"][0]["run_by_default"] is False


def test_create_check_workflow_pauses_for_command_approval(tmp_path):
    target = tmp_path / "app"
    builder = WebsiteBuilder(str(tmp_path))
    builder.build_site("developer portfolio app", target)

    task = builder.create_check_workflow(target)
    approvals = builder.task_store.list_approvals(status="pending")

    assert task["kind"] == "website-workflow"
    assert task["status"] == "waiting_for_approval"
    assert task["payload"]["workflow"] == "check"
    assert task["payload"]["pending_command_plan"]["command"] == "npm run build"
    assert len(approvals) == 1
    assert approvals[0]["payload"]["command_plan"]["command"] == "npm run build"
    assert [step["kind"] for step in task["steps"]][-2:] == ["approval_required", "approval"]


def test_resume_check_workflow_records_approved_command_without_shell_execution(tmp_path):
    target = tmp_path / "app"
    builder = WebsiteBuilder(str(tmp_path))
    builder.build_site("developer portfolio app", target)
    task = builder.create_check_workflow(target)
    approval = builder.task_store.list_approvals(status="pending")[0]
    builder.task_store.approve(approval["id"])

    resumed = builder.resume_check_workflow(task["id"])

    assert resumed["status"] == "completed"
    assert resumed["summary"] == "Workflow resumed after approval; command plan recorded without shell execution."
    assert resumed["payload"]["approved_command_plans"][0]["command"] == "npm run build"
    assert resumed["payload"]["safety_mode"] == "record_only"
    assert builder.task_store.get_approval(approval["id"])["status"] == "used"


def test_execute_approved_workflow_command_runs_allowlisted_check(tmp_path):
    target = tmp_path / "python-app"
    target.mkdir()
    (target / "requirements.txt").write_text("", encoding="utf-8")
    (target / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    builder = WebsiteBuilder(str(tmp_path))
    task = builder.create_check_workflow(target)
    approval = builder.task_store.list_approvals(status="pending")[0]
    builder.task_store.approve(approval["id"])

    executed = builder.execute_approved_workflow_command(task["id"], approval_id=approval["id"])

    assert executed["status"] == "completed"
    assert executed["summary"] == "Approved command executed successfully."
    assert executed["payload"]["last_command_result"]["command"] == "python -m pytest"
    assert executed["payload"]["last_command_result"]["exit_code"] == 0


def test_web_verifier_includes_timing_and_task_steps(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(204)
            self.end_headers()

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = WebVerifier(str(tmp_path)).verify(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert result["ok"] is True
    assert result["status_code"] == 204
    assert result["response_time_ms"] >= 0
    assert result["task_steps"][0]["kind"] == "http"
    assert result["task_steps"][0]["message"] == "Starting HTTP verification."


def test_browser_verification_missing_playwright_keeps_http_result(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            return None

    def missing_playwright(url):
        return {
            "browser": "unavailable",
            "errors": ["Browser verification requested, but Playwright is not installed. Install it to capture screenshots."],
            "screenshot": "",
        }

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    verifier = WebVerifier(str(tmp_path))
    monkeypatch.setattr(verifier, "_playwright_snapshot", missing_playwright)
    try:
        result = verifier.verify(f"http://127.0.0.1:{server.server_port}", use_browser=True)
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["browser"] == "unavailable"
    assert result["errors"] == ["Browser verification requested, but Playwright is not installed. Install it to capture screenshots."]
    assert result["task_steps"][-1]["message"] == "Browser verification skipped because Playwright is not installed."
