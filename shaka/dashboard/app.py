"""Web dashboard for Shaka.

Simple, fast, lightweight dashboard using Flask and vanilla JavaScript.
"""

import os
import sys
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify

# Ensure parent dir is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shaka.config import load_config
from shaka.memory import MemoryManager, SessionDB
from shaka.skills import SkillsRegistry
from shaka.agent import Agent
from shaka.automation import TaskStore
from shaka.email_runtime import GmailRuntime
from shaka.eval_runtime import EvalRunner
from shaka.local_state import runtime_status
from shaka.proof import ProofExporter
from shaka.cron import CronStore
from shaka.providers import is_model_configured
from shaka.repo_memory import RepoMemory
from shaka.web_runtime import WebVerifier
from shaka.website_builder import WebsiteBuilder

AUTH_COOKIE = "shaka_gateway_token"


def create_app(config_path=None, config=None, gateway_token=None, require_token=False):
    """Create the dashboard Flask app."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    config = config or load_config(config_path)
    gateway_token = gateway_token or os.environ.get("SHAKA_GATEWAY_TOKEN", "")
    memory = MemoryManager(config.paths.base_dir)
    try:
        session_db = SessionDB(config.paths.db_path)
    except Exception:
        session_db = None
    task_store = TaskStore(config.paths.base_dir)
    gmail = GmailRuntime(config.paths.base_dir, task_store=task_store)
    repo_memory = RepoMemory(config.paths.base_dir)
    website_builder = WebsiteBuilder(config.paths.base_dir, task_store=task_store)
    web_verifier = WebVerifier(config.paths.base_dir, task_store=task_store)
    cron_store = CronStore(config.paths.base_dir)

    # Initialize skills registry
    skills_registry = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills_core")
    skills_registry.load_core_skills(core_skills_dir, verbose=False)
    skills_registry.load_user_skills(config.paths.skills_dir, verbose=False)
    agent = None

    def request_token() -> str:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header.split(" ", 1)[1].strip()
        return (
            request.headers.get("X-Shaka-Token")
            or request.args.get("token")
            or request.cookies.get(AUTH_COOKIE)
            or ""
        )

    @app.before_request
    def require_gateway_token():
        if not require_token:
            return None
        if request.endpoint in {"health", "static"}:
            return None
        if gateway_token and request_token() == gateway_token:
            return None
        return jsonify({"error": "valid Shaka gateway token required"}), 401

    @app.after_request
    def remember_gateway_token(response):
        if require_token and gateway_token and request.args.get("token") == gateway_token:
            response.set_cookie(
                AUTH_COOKIE,
                gateway_token,
                httponly=True,
                samesite="Strict",
            )
        return response

    def get_agent():
        nonlocal agent
        if agent is None:
            agent = Agent(config, skills_registry, memory)
        return agent

    def workspace_root() -> Path:
        configured = getattr(config.paths, "workspace_dir", "") or ""
        return Path(configured or Path(config.paths.base_dir) / "workspace").expanduser().resolve()

    def require_workspace_path(raw_path: str):
        target = Path(raw_path).expanduser().resolve()
        root = workspace_root()
        if target != root and root not in target.parents:
            return None, (
                jsonify({
                    "error": f"Path must be inside the Shaka workspace: {root}",
                    "workspace": str(root),
                    "path": str(target),
                }),
                403,
            )
        return target, None

    @app.route("/")
    def index():
        """Main dashboard page."""
        stats = session_db.get_stats() if session_db else {
            "total_sessions": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }
        return render_template(
            "index.html",
            stats=stats,
            config=config,
            runtime=runtime_status(config),
            skills=skills_registry.list_skills(),
            sessions=memory.list_sessions("default"),
            tasks=task_store.list_tasks()[:8],
            approvals=task_store.list_approvals(status="pending")[:8],
        )

    @app.route("/api/message", methods=["POST"])
    def send_message():
        """Handle messages from dashboard."""
        data = request.get_json(silent=True) or {}
        message = str(data.get("message", "")).strip()
        session_id = str(data.get("session_id") or f"dashboard_{int(time.time())}")

        if not message:
            return jsonify({"error": "message is required"}), 400

        if not is_model_configured(config):
            return jsonify({
                "error": f"Model provider is not configured. Set {config.model.api_key_env or 'SHAKA_API_KEY'}, run `shaka credentials set {config.model.provider}`, or use Ollama.",
            }), 503

        result = get_agent().chat(message, session_id=session_id)
        return jsonify({
            "session_id": result["session_id"],
            "reply": result["response"],
            "tokens_used": result["tokens_used"],
            "elapsed_seconds": result["elapsed_seconds"],
            "tool_calls_executed": result.get("tool_calls_executed", 0),
        })

    @app.route("/api/memory")
    def api_memory():
        """Get user memory."""
        mem = memory.load_memory("default")
        return jsonify({
            "facts": mem.get("facts", []),
            "wiki_pages": memory.get_wiki_pages("default"),
            "sessions": memory.list_sessions("default"),
        })

    @app.route("/api/memory/search")
    def api_memory_search():
        """Search local memory, wiki pages, and session transcripts."""
        query = request.args.get("q", "")
        limit = int(request.args.get("limit", "10"))
        if request.args.get("index", "1").lower() not in {"0", "false", "no"}:
            memory.index_memory("default")
        return jsonify(memory.search_memory("default", query, limit=limit))

    @app.route("/api/repo-memory")
    def api_repo_memory():
        """Get repo-specific memory."""
        repo_path = request.args.get("path") or os.getcwd()
        return jsonify(repo_memory.load(repo_path))

    @app.route("/api/skills")
    def api_skills():
        """Get available skills."""
        return jsonify(skills_registry.list_skills())

    @app.route("/api/stats")
    def api_stats():
        """Get usage statistics."""
        if session_db:
            return jsonify(session_db.get_stats())
        return jsonify({"error": "No database configured"})

    @app.route("/api/runtime/status")
    def api_runtime_status():
        """Return local gateway runtime state."""
        status = runtime_status(config)
        status["auth_required"] = bool(require_token)
        return jsonify(status)

    @app.route("/api/proof")
    def api_proof():
        """Return secret-safe local runtime proof."""
        return jsonify(ProofExporter(config).build())

    @app.route("/api/proof/export", methods=["POST"])
    def api_proof_export():
        """Write the local runtime proof Markdown report."""
        path = ProofExporter(config).export_markdown()
        return jsonify({"path": str(path)})

    @app.route("/api/tasks")
    def api_tasks():
        """List automation tasks."""
        status = request.args.get("status")
        try:
            return jsonify(task_store.list_tasks(status=status))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/tasks/<task_id>")
    def api_task_detail(task_id):
        """Return a single task with step history."""
        task = task_store.get_task(task_id)
        if not task:
            return jsonify({"error": f"Unknown task: {task_id}"}), 404
        return jsonify(task)

    @app.route("/api/sessions/<session_id>")
    def api_session_detail(session_id):
        """Return a local session transcript."""
        messages = memory.load_session("default", session_id)
        if not messages:
            known = {item["session_id"] for item in memory.list_sessions("default")}
            if session_id not in known:
                return jsonify({"error": f"Unknown session: {session_id}"}), 404
        return jsonify({
            "session_id": session_id,
            "messages": messages,
            "message_count": len(messages),
        })

    @app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
    def api_cancel_task(task_id):
        """Cancel an automation task."""
        try:
            return jsonify(task_store.cancel_task(task_id))
        except KeyError as exc:
            return jsonify({"error": str(exc).strip("'")}), 404

    @app.route("/api/tasks/<task_id>/retry", methods=["POST"])
    def api_retry_task(task_id):
        """Retry a failed or cancelled automation task."""
        try:
            return jsonify(task_store.retry_task(task_id))
        except KeyError as exc:
            return jsonify({"error": str(exc).strip("'")}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.route("/api/approvals")
    def api_approvals():
        """List approvals."""
        status = request.args.get("status")
        try:
            return jsonify(task_store.list_approvals(status=status))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/approvals/<approval_id>/approve", methods=["POST"])
    def api_approve(approval_id):
        """Approve a pending action."""
        try:
            return jsonify(task_store.approve(approval_id))
        except KeyError as exc:
            return jsonify({"error": str(exc).strip("'")}), 404

    @app.route("/api/approvals/<approval_id>/reject", methods=["POST"])
    def api_reject(approval_id):
        """Reject a pending action."""
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(task_store.reject_approval(approval_id, reason=str(data.get("reason", "")).strip()))
        except KeyError as exc:
            return jsonify({"error": str(exc).strip("'")}), 404

    @app.route("/api/email/setup")
    def api_email_setup():
        """Return Gmail setup instructions."""
        return jsonify(gmail.setup_instructions())

    @app.route("/api/email/status")
    def api_email_status():
        """Return Gmail connector status."""
        return jsonify(gmail.connection_status())

    @app.route("/api/email/revoke", methods=["POST"])
    def api_email_revoke():
        """Remove local Gmail token state."""
        return jsonify(gmail.revoke())

    @app.route("/api/email/search")
    def api_email_search():
        """Search locally cached Gmail messages."""
        return jsonify(gmail.search(query=request.args.get("q", ""), limit=int(request.args.get("limit", "10"))))

    @app.route("/api/email/sync", methods=["POST"])
    def api_email_sync():
        """Sync or refresh Gmail snapshot data."""
        data = request.get_json(silent=True) or {}
        return jsonify(gmail.sync_snapshot(
            query=str(data.get("query", "")).strip(),
            limit=int(data.get("limit", 10)),
        ))

    @app.route("/api/email/thread/<thread_id>")
    def api_email_thread(thread_id):
        """Fetch a Gmail thread from connector or local snapshot."""
        return jsonify(gmail.fetch_thread(thread_id))

    @app.route("/api/email/summarize")
    def api_email_summarize():
        """Summarize locally cached Gmail messages."""
        return jsonify(gmail.summarize(query=request.args.get("q", ""), limit=int(request.args.get("limit", "10"))))

    @app.route("/api/email/draft", methods=["POST"])
    def api_email_draft():
        """Create an approval-gated Gmail draft."""
        data = request.get_json(silent=True) or {}
        for field in ("to", "subject", "body"):
            if not str(data.get(field, "")).strip():
                return jsonify({"error": f"{field} is required"}), 400
        return jsonify(gmail.draft_reply(
            str(data["to"]).strip(),
            str(data["subject"]).strip(),
            str(data["body"]).strip(),
            thread_id=str(data.get("thread_id", "")).strip(),
        ))

    @app.route("/api/email/send", methods=["POST"])
    def api_email_send():
        """Send an approved Gmail draft."""
        data = request.get_json(silent=True) or {}
        approval_id = str(data.get("approval_id", "")).strip()
        if not approval_id:
            return jsonify({"error": "approval_id is required"}), 400
        try:
            return jsonify(gmail.send_approved(approval_id))
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

    @app.route("/api/build-site", methods=["POST"])
    def api_build_site():
        """Build a full-stack website scaffold."""
        data = request.get_json(silent=True) or {}
        prompt = str(data.get("prompt", "")).strip()
        path = str(data.get("path", "")).strip()
        if not prompt or not path:
            return jsonify({"error": "prompt and path are required"}), 400
        target_path, error = require_workspace_path(path)
        if error:
            return error
        return jsonify(website_builder.build_site(prompt, target_path))

    @app.route("/api/web/verify", methods=["POST"])
    def api_web_verify():
        """Verify a web URL."""
        data = request.get_json(silent=True) or {}
        url = str(data.get("url", "")).strip()
        if not url:
            return jsonify({"error": "url is required"}), 400
        return jsonify(web_verifier.verify(url, use_browser=bool(data.get("browser", False))))

    @app.route("/api/web/inspect")
    def api_web_inspect():
        """Inspect a website/app project stack."""
        target_path = request.args.get("path") or os.getcwd()
        return jsonify(website_builder.inspect_project(target_path))

    @app.route("/api/web/checks")
    def api_web_checks():
        """Plan install/build/test commands for a website/app project."""
        target_path = request.args.get("path") or os.getcwd()
        return jsonify(website_builder.plan_checks(target_path))

    @app.route("/api/web/fix", methods=["POST"])
    def api_web_fix():
        """Record a website/app fix task."""
        data = request.get_json(silent=True) or {}
        issue = str(data.get("issue", "")).strip()
        target_path = str(data.get("path", ".")).strip() or "."
        if not issue:
            return jsonify({"error": "issue is required"}), 400
        return jsonify(website_builder.record_fix_task(target_path, issue))

    @app.route("/api/web/workflow", methods=["POST"])
    def api_web_workflow():
        """Create an approval-aware website check workflow."""
        data = request.get_json(silent=True) or {}
        target_path = str(data.get("path", ".")).strip() or "."
        return jsonify(website_builder.create_check_workflow(target_path))

    @app.route("/api/web/workflow/<task_id>/resume", methods=["POST"])
    def api_web_workflow_resume(task_id):
        """Resume an approved website check workflow in safety mode."""
        try:
            return jsonify(website_builder.resume_check_workflow(task_id))
        except KeyError as exc:
            return jsonify({"error": str(exc).strip("'")}), 404

    @app.route("/api/web/workflow/<task_id>/execute", methods=["POST"])
    def api_web_workflow_execute(task_id):
        """Execute an approved, allowlisted website workflow command."""
        data = request.get_json(silent=True) or {}
        approval_id = str(data.get("approval_id", "")).strip() or None
        timeout_seconds = int(data.get("timeout_seconds", 120))
        try:
            return jsonify(website_builder.execute_approved_workflow_command(
                task_id,
                approval_id=approval_id,
                timeout_seconds=timeout_seconds,
            ))
        except KeyError as exc:
            return jsonify({"error": str(exc).strip("'")}), 404
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.route("/api/eval", methods=["POST"])
    def api_eval():
        """Run Shaka evals."""
        return jsonify(EvalRunner(config.paths.base_dir).run())

    @app.route("/api/cron/jobs")
    def api_cron_jobs():
        """List local cron jobs."""
        return jsonify(cron_store.list_jobs())

    @app.route("/api/cron/jobs", methods=["POST"])
    def api_cron_add():
        """Add a local cron job."""
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(cron_store.add_job(
                str(data.get("name", "")).strip(),
                str(data.get("schedule", "")).strip(),
                str(data.get("command", "")).strip(),
                cwd=str(data.get("cwd", ".")).strip() or ".",
                enabled=bool(data.get("enabled", True)),
            ))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/cron/tick", methods=["POST"])
    def api_cron_tick():
        """Run due local cron jobs once."""
        data = request.get_json(silent=True) or {}
        return jsonify(cron_store.tick(dry_run=bool(data.get("dry_run", False))))

    @app.route("/health")
    def health():
        """Health check endpoint."""
        return jsonify({
            "status": "healthy",
            "service": "shaka-gateway" if require_token else "shaka-dashboard",
            "auth_required": bool(require_token),
        })

    return app

if __name__ == "__main__":
    from shaka.config import load_config

    config = load_config()
    app = create_app(config=config)
    app.run(host=config.dashboard.host, port=config.dashboard.port, debug=False)
