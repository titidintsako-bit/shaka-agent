"""Dashboard tests."""

from pathlib import Path

from shaka.config import ShakaConfig
from shaka.dashboard.app import create_app


def test_dashboard_health_endpoint(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_dashboard_index_includes_task_workflow_controls(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="task-actions"' in body
    assert 'id="task-approve"' in body
    assert 'id="task-resume"' in body
    assert 'id="task-execute"' in body


def test_dashboard_index_includes_portfolio_proof_panel(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-target="proof"' in body
    assert 'id="proof-section"' in body
    assert 'id="proof-export"' in body


def test_dashboard_proof_api_and_export_route(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    proof = client.get("/api/proof")
    exported = client.post("/api/proof/export")

    assert proof.status_code == 200
    assert proof.get_json()["local_first"] is True
    assert exported.status_code == 200
    assert exported.get_json()["path"].endswith("proof.md")


def test_dashboard_gmail_is_skills_capability_not_top_nav(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-target="email"' not in body
    assert 'id="email-section"' not in body
    assert 'id="email-draft-form"' in body
    assert body.index('id="skills-section"') < body.index('id="email-draft-form"')


def test_dashboard_message_requires_text(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.post("/api/message", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "message is required"


def test_dashboard_message_requires_configured_model(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    config.model.api_key = ""
    config.model.provider = "groq"
    app = create_app(config=config)
    client = app.test_client()

    response = client.post("/api/message", json={"message": "hello"})

    assert response.status_code == 503
    assert "Model provider is not configured" in response.get_json()["error"]


def test_dashboard_task_and_approval_routes_share_runtime(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    draft = client.post("/api/email/draft", json={
        "to": "dev@example.com",
        "subject": "Hello",
        "body": "Approved later.",
    })
    assert draft.status_code == 200
    approval_id = draft.get_json()["approval"]["id"]

    approvals = client.get("/api/approvals?status=pending")
    assert approval_id in {item["id"] for item in approvals.get_json()}

    approved = client.post(f"/api/approvals/{approval_id}/approve")
    assert approved.status_code == 200
    assert approved.get_json()["status"] == "approved"


def test_dashboard_rejects_approval_and_cancels_task(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    draft = client.post("/api/email/draft", json={
        "to": "dev@example.com",
        "subject": "Hello",
        "body": "Approved later.",
    })
    approval_id = draft.get_json()["approval"]["id"]
    task_id = draft.get_json()["task"]["id"]

    rejected = client.post(
        f"/api/approvals/{approval_id}/reject",
        json={"reason": "Needs review"},
    )
    tasks = client.get("/api/tasks").get_json()

    assert rejected.status_code == 200
    assert rejected.get_json()["status"] == "rejected"
    assert next(item for item in tasks if item["id"] == task_id)["status"] == "cancelled"


def test_dashboard_retries_cancelled_task(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    draft = client.post("/api/email/draft", json={
        "to": "dev@example.com",
        "subject": "Hello",
        "body": "Approved later.",
    })
    task_id = draft.get_json()["task"]["id"]

    assert client.post(f"/api/tasks/{task_id}/cancel").status_code == 200
    retried = client.post(f"/api/tasks/{task_id}/retry")

    assert retried.status_code == 200
    assert retried.get_json()["status"] == "queued"


def test_dashboard_task_detail_route_returns_steps(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    draft = client.post("/api/email/draft", json={
        "to": "dev@example.com",
        "subject": "Hello",
        "body": "Approved later.",
    }).get_json()

    response = client.get(f"/api/tasks/{draft['task']['id']}")

    assert response.status_code == 200
    assert response.get_json()["id"] == draft["task"]["id"]
    assert response.get_json()["steps"]


def test_dashboard_missing_task_detail_returns_404(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/api/tasks/missing")

    assert response.status_code == 404


def test_dashboard_invalid_runtime_filter_returns_400(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/api/tasks?status=bad")

    assert response.status_code == 400
    assert "Unsupported task status" in response.get_json()["error"]


def test_dashboard_repo_memory_route(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/api/repo-memory", query_string={"path": str(tmp_path)})

    assert response.status_code == 200
    assert response.get_json()["repo_path"] == str(tmp_path.resolve())


def test_dashboard_email_status_and_sync_routes(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    status = client.get("/api/email/status")
    sync = client.post("/api/email/sync", json={"query": "interview", "limit": 3})

    assert status.status_code == 200
    assert status.get_json()["provider"] == "gmail"
    assert sync.status_code == 200
    assert sync.get_json()["mode"] in {"local_log", "gmail_api", "unavailable"}


def test_dashboard_email_thread_route_uses_snapshot(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()
    email_dir = tmp_path / "data" / "email"
    email_dir.mkdir(parents=True, exist_ok=True)
    (email_dir / "gmail_snapshot.json").write_text(
        '[{"id":"m1","thread_id":"t1","subject":"Hello","snippet":"Body"}]',
        encoding="utf-8",
    )

    response = client.get("/api/email/thread/t1")

    assert response.status_code == 200
    assert response.get_json()["thread_id"] == "t1"
    assert len(response.get_json()["messages"]) == 1


def test_dashboard_web_inspect_checks_and_fix_routes(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()
    project = tmp_path / "site"
    project.mkdir()

    inspect_response = client.get("/api/web/inspect", query_string={"path": str(project)})
    checks_response = client.get("/api/web/checks", query_string={"path": str(project)})
    fix_response = client.post("/api/web/fix", json={"path": str(project), "issue": "Button is broken"})

    assert inspect_response.status_code == 200
    assert "stack" in inspect_response.get_json()
    assert checks_response.status_code == 200
    assert "checks" in checks_response.get_json()
    assert fix_response.status_code == 200
    assert fix_response.get_json()["kind"] == "website-fix"


def test_dashboard_web_workflow_and_resume_routes(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    config.paths.workspace_dir = str(tmp_path / "data" / "workspace")
    app = create_app(config=config)
    client = app.test_client()
    project = Path(config.paths.workspace_dir) / "site"

    build = client.post("/api/build-site", json={"prompt": "portfolio app", "path": str(project)})
    assert build.status_code == 200

    workflow = client.post("/api/web/workflow", json={"path": str(project)})
    workflow_data = workflow.get_json()
    approval_id = workflow_data["steps"][-1]["metadata"]["approval_id"]

    assert workflow.status_code == 200
    assert workflow_data["status"] == "waiting_for_approval"

    approved = client.post(f"/api/approvals/{approval_id}/approve")
    resumed = client.post(f"/api/web/workflow/{workflow_data['id']}/resume")

    assert approved.status_code == 200
    assert resumed.status_code == 200
    assert resumed.get_json()["status"] == "completed"
    assert resumed.get_json()["payload"]["approved_command_plans"][0]["command"] == "npm run build"


def test_dashboard_web_workflow_execute_route(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()
    project = tmp_path / "python-site"
    project.mkdir()
    (project / "requirements.txt").write_text("", encoding="utf-8")
    (project / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    workflow = client.post("/api/web/workflow", json={"path": str(project)})
    workflow_data = workflow.get_json()
    approval_id = workflow_data["steps"][-1]["metadata"]["approval_id"]
    approved = client.post(f"/api/approvals/{approval_id}/approve")
    executed = client.post(
        f"/api/web/workflow/{workflow_data['id']}/execute",
        json={"approval_id": approval_id, "timeout_seconds": 30},
    )

    assert approved.status_code == 200
    assert executed.status_code == 200
    assert executed.get_json()["status"] == "completed"
    assert executed.get_json()["payload"]["last_command_result"]["command"] == "python -m pytest"


def test_dashboard_build_site_route(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    config.paths.workspace_dir = str(tmp_path / "data" / "workspace")
    app = create_app(config=config)
    client = app.test_client()
    target = Path(config.paths.workspace_dir) / "built-site"

    response = client.post("/api/build-site", json={"prompt": "portfolio app", "path": str(target)})

    assert response.status_code == 200
    assert response.get_json()["status"] == "completed"
    assert (target / "frontend" / "src" / "App.jsx").exists()


def test_dashboard_build_site_rejects_paths_outside_workspace(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    config.paths.workspace_dir = str(tmp_path / "data" / "workspace")
    app = create_app(config=config)
    client = app.test_client()

    response = client.post(
        "/api/build-site",
        json={"prompt": "portfolio app", "path": str(tmp_path / "outside-site")},
    )

    assert response.status_code == 403
    assert "workspace" in response.get_json()["error"]


def test_dashboard_eval_route(tmp_path):
    config = ShakaConfig()
    config.paths.base_dir = str(tmp_path / "data")
    config.paths.users_dir = str(tmp_path / "data" / "users")
    config.paths.skills_dir = str(tmp_path / "data" / "skills")
    config.paths.db_path = str(tmp_path / "data" / "shaka.db")
    app = create_app(config=config)
    client = app.test_client()

    response = client.post("/api/eval")

    assert response.status_code == 200
    assert response.get_json()["failed"] == 0
