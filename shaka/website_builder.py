"""Website and full-stack app builder workflows for Shaka."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .automation import TaskStore
from .task_runner import CommandExecutor, CommandPlan, Step, TaskRunner


def _read_package_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _node_command(package_manager: str, script: str) -> str:
    if package_manager == "yarn":
        return f"yarn {script}"
    if package_manager == "pnpm":
        return f"pnpm {script}"
    return f"npm run {script}"


def _node_install_command(package_manager: str) -> str:
    if package_manager == "yarn":
        return "yarn install"
    if package_manager == "pnpm":
        return "pnpm install"
    return "npm install"


def _python_install_command(root: Path) -> str:
    if (root / "requirements.txt").exists():
        return "python -m pip install -r requirements.txt"
    if (root / "pyproject.toml").exists():
        return "python -m pip install -e ."
    return "python -m pip install -r requirements.txt"


def _command_plan(area: str, cwd: Path, command: str, reason: str) -> dict[str, Any]:
    return {
        "area": area,
        "cwd": str(cwd),
        "command": command,
        "reason": reason,
        "run_by_default": False,
    }


def _flatten_check_commands(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return list(plan.get("checks", []))


def _project_roots(root: Path) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    frontend = root / "frontend"
    backend = root / "backend"
    if frontend.exists():
        roots.append(("frontend", frontend))
    if backend.exists():
        roots.append(("backend", backend))
    if not roots:
        roots.append(("project", root))
    return roots


def inspect_project(path: str | Path) -> dict[str, Any]:
    """Return deterministic stack detection and recommended commands without running them."""

    root = Path(path).expanduser().resolve()
    detector = StackDetector.detect(root)
    package_path = root / "package.json"
    package = _read_package_json(package_path) if package_path.exists() else {}
    scripts = package.get("scripts", {}) if isinstance(package.get("scripts", {}), dict) else {}
    package_manager = _node_package_manager(root) if package_path.exists() else ""

    commands: dict[str, Any] = {}
    if package_path.exists():
        commands["install"] = _node_install_command(package_manager)
        if "build" in scripts:
            commands["build"] = _node_command(package_manager, "build")
        if "test" in scripts:
            commands["test"] = _node_command(package_manager, "test")
        if "dev" in scripts:
            commands["dev"] = _node_command(package_manager, "dev")
    if "python" in detector["stack"]:
        commands.setdefault("install", _python_install_command(root))
        if (root / "app" / "main.py").exists():
            commands.setdefault("dev", "python -m uvicorn app.main:app --reload --port 8000")
        commands.setdefault("test", "python -m pytest")

    components: list[dict[str, Any]] = []
    if detector["stack"] == ["unknown"]:
        for area, candidate in _project_roots(root):
            if area == "project":
                continue
            component = inspect_project(candidate)
            component["area"] = area
            components.append(component)

    if components:
        stack: list[str] = []
        grouped_commands: dict[str, dict[str, str]] = {}
        for component in components:
            for item in component["stack"]:
                if item not in stack and item != "unknown":
                    stack.append(item)
            grouped_commands[component["area"]] = component["recommended_commands"]
        detector = {**detector, "stack": stack or ["unknown"]}
        commands = grouped_commands

    return {
        **detector,
        "package_manager": package_manager,
        "scripts": scripts,
        "recommended_commands": commands,
        "components": components,
    }


def plan_checks(path: str | Path) -> dict[str, Any]:
    """Plan frontend/backend check commands without executing package managers or tests."""

    root = Path(path).expanduser().resolve()
    checks: list[dict[str, Any]] = []
    for area, candidate in _project_roots(root):
        inspection = inspect_project(candidate)
        commands = inspection["recommended_commands"]
        stack = inspection["stack"]
        if "node" in stack:
            if "install" in commands:
                checks.append(_command_plan(area, candidate, commands["install"], "Install frontend dependencies if missing."))
            if "build" in commands:
                checks.append(_command_plan(area, candidate, commands["build"], "Validate production frontend build."))
            if "test" in commands:
                checks.append(_command_plan(area, candidate, commands["test"], "Run frontend test script."))
        if "python" in stack:
            checks.append(_command_plan(area, candidate, commands["install"], "Install backend Python dependencies if missing."))
            checks.append(_command_plan(area, candidate, commands["test"], "Run backend Python tests."))
            if "fastapi" in stack and "dev" in commands:
                checks.append(_command_plan(area, candidate, commands["dev"], "Start backend development server for manual smoke checks."))

    return {
        "path": str(root),
        "checks": checks,
    }


def record_fix_task(path: str | Path, issue: str, task_store: TaskStore | None = None) -> dict[str, Any]:
    """Record an inspect/plan/fix-needed task without pretending code was edited."""

    root = Path(path).expanduser().resolve()
    store = task_store or TaskStore(str(root))
    inspection = inspect_project(root)
    plan = plan_checks(root)
    task = store.create_task(
        title=f"Fix needed for {root.name}",
        kind="website-fix",
        payload={"path": str(root), "issue": issue, "inspection": inspection, "plan": plan},
        status="queued",
    )
    store.add_step(task["id"], "Inspected project stack and recommended commands.", kind="inspect", metadata=inspection)
    store.add_step(task["id"], "Planned deterministic checks; no package managers or tests were run.", kind="plan", metadata=plan)
    store.add_step(task["id"], "Fix is needed before verification can be marked complete.", kind="fix-needed", metadata={"issue": issue})
    store.update_task(task["id"], summary="Recorded fix-loop task; no code edits were performed.")
    return store.get_task(task["id"]) or task


class StackDetector:
    """Detect common project stacks before Shaka edits or creates apps."""

    @staticmethod
    def detect(path: str | Path) -> dict[str, Any]:
        root = Path(path).expanduser().resolve()
        markers = {
            "package.json": root / "package.json",
            "vite.config": root / "vite.config.ts",
            "pyproject.toml": root / "pyproject.toml",
            "requirements.txt": root / "requirements.txt",
            "fastapi": root / "app" / "main.py",
        }
        stack: list[str] = []
        if markers["package.json"].exists():
            stack.append("node")
            try:
                package = json.loads(markers["package.json"].read_text(encoding="utf-8"))
                deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
                if "vite" in deps:
                    stack.append("vite")
                if "react" in deps:
                    stack.append("react")
            except Exception:
                pass
        if markers["pyproject.toml"].exists() or markers["requirements.txt"].exists():
            stack.append("python")
        if markers["fastapi"].exists():
            stack.append("fastapi")
        return {
            "path": str(root),
            "exists": root.exists(),
            "stack": stack or ["unknown"],
            "is_empty": root.exists() and not any(root.iterdir()) if root.exists() else True,
        }


class WebsiteBuilder:
    """Create a Vite React + FastAPI + SQLite starter app."""

    def __init__(self, base_dir: str, task_store: TaskStore | None = None):
        self.task_store = task_store or TaskStore(base_dir)

    def build_site(self, prompt: str, path: str | Path) -> dict[str, Any]:
        root = Path(path).expanduser().resolve()
        task = self.task_store.create_task(
            title=f"Build site at {root.name}",
            kind="website",
            payload={"prompt": prompt, "path": str(root), "stack": "vite-react-fastapi-sqlite"},
            status="running",
        )
        try:
            detector = StackDetector.detect(root)
            self.task_store.add_step(
                task["id"],
                "Detected target project state.",
                kind="detect",
                metadata=detector,
            )
            if detector["exists"] and not detector["is_empty"]:
                self.task_store.add_step(task["id"], "Existing app detected; no scaffold overwritten.", kind="detect", metadata=detector)
                self.task_store.update_task(
                    task["id"],
                    status="completed",
                    summary="Existing project detected. Shaka recorded stack metadata and skipped scaffolding.",
                    payload={**task["payload"], "detected": detector},
                )
                return self.task_store.get_task(task["id"]) or task

            self.task_store.add_step(
                task["id"],
                "Scaffolding deterministic Vite React, FastAPI, and SQLite app.",
                kind="scaffold",
                metadata={"frontend": "vite-react", "backend": "fastapi", "database": "sqlite"},
            )
            self._write_scaffold(root, prompt)
            self.task_store.add_step(task["id"], "Created Vite React frontend.", kind="write")
            self.task_store.add_step(task["id"], "Created FastAPI backend with health, status, CORS, and SQLite initialization.", kind="write")
            self.task_store.add_step(task["id"], "Created README with run instructions.", kind="write")
            self.task_store.update_task(
                task["id"],
                status="completed",
                summary="Created full-stack Vite React + FastAPI + SQLite app scaffold.",
            )
            self.task_store.add_step(
                task["id"],
                "Wrote build summary.",
                kind="write-summary",
                metadata={"summary": "Created full-stack Vite React + FastAPI + SQLite app scaffold."},
            )
            return self.task_store.get_task(task["id"]) or task
        except Exception as exc:
            self.task_store.update_task(task["id"], status="failed", error=str(exc), summary="Website build failed.")
            raise

    def inspect_project(self, path: str | Path) -> dict[str, Any]:
        return inspect_project(path)

    def plan_checks(self, path: str | Path) -> dict[str, Any]:
        return plan_checks(path)

    def record_fix_task(self, path: str | Path, issue: str) -> dict[str, Any]:
        return record_fix_task(path, issue, self.task_store)

    def create_check_workflow(self, path: str | Path) -> dict[str, Any]:
        """Create and run a deterministic website check workflow until approval is needed."""

        root = Path(path).expanduser().resolve()
        task = self.task_store.create_task(
            title=f"Check workflow for {root.name}",
            kind="website-workflow",
            payload={"path": str(root), "workflow": "check", "safety_mode": "approval_required"},
            status="queued",
        )
        return self._run_check_workflow(task["id"])

    def resume_check_workflow(self, task_id: str) -> dict[str, Any]:
        """Resume a check workflow after command approval without executing shell commands."""

        task = self.task_store.get_task(task_id)
        if not task:
            raise KeyError(f"Unknown task: {task_id}")
        approvals = [
            item for item in self.task_store.list_approvals(status="approved")
            if item.get("task_id") == task_id
        ]
        if not approvals:
            self.task_store.add_step(
                task_id,
                "Workflow resume requested, but no approved command plan was found.",
                kind="resume",
            )
            return self.task_store.update_task(
                task_id,
                status="waiting_for_approval",
                summary="Waiting for command plan approval.",
            )

        approval = approvals[0]
        command_plan = approval.get("payload", {}).get("command_plan", {})
        self.task_store.mark_approval_used(approval["id"])
        self.task_store.add_step(
            task_id,
            "Approved command plan recorded. Shell execution is still disabled in safety mode.",
            kind="approved-command",
            metadata={"approval_id": approval["id"], "command_plan": command_plan},
        )
        payload = {**task.get("payload", {})}
        payload.setdefault("approved_command_plans", []).append(command_plan)
        payload["safety_mode"] = "record_only"
        return self.task_store.update_task(
            task_id,
            status="completed",
            summary="Workflow resumed after approval; command plan recorded without shell execution.",
            payload=payload,
        )

    def execute_approved_workflow_command(
        self,
        task_id: str,
        *,
        approval_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Execute an approved, allowlisted workflow command with captured logs."""

        executor = CommandExecutor(self.task_store)
        return executor.execute_approved(
            task_id,
            approval_id=approval_id,
            timeout_seconds=timeout_seconds,
        )

    def _run_check_workflow(self, task_id: str) -> dict[str, Any]:
        runner = TaskRunner(self.task_store)

        def inspect_step(task: dict[str, Any], store: TaskStore) -> dict[str, Any]:
            root = Path(task["payload"]["path"])
            inspection = inspect_project(root)
            payload = {**task.get("payload", {}), "inspection": inspection}
            store.update_task(task["id"], payload=payload)
            return inspection

        def plan_step(task: dict[str, Any], store: TaskStore) -> dict[str, Any]:
            root = Path(task["payload"]["path"])
            plan = plan_checks(root)
            payload = {**task.get("payload", {}), "plan": plan}
            store.update_task(task["id"], payload=payload)
            return plan

        def approval_step(task: dict[str, Any], store: TaskStore) -> dict[str, Any] | CommandPlan:
            plan = task.get("payload", {}).get("plan") or plan_checks(task["payload"]["path"])
            commands = _flatten_check_commands(plan)
            if not commands:
                return {"message": "No check commands detected.", "commands": []}
            executor = CommandExecutor(store)
            first = next(
                (item for item in commands if executor.is_allowed_command(str(item.get("command", "")))),
                commands[0],
            )
            payload = {**task.get("payload", {}), "pending_command_plan": first}
            store.update_task(task["id"], payload=payload)
            return CommandPlan.create(
                str(first["command"]),
                action="shell",
                target=str(first.get("cwd", "")),
                requires_approval=True,
            )

        return runner.run(
            task_id,
            [
                Step("inspect-project", inspect_step),
                Step("plan-checks", plan_step),
                Step("request-command-approval", approval_step),
            ],
        )

    def _write_scaffold(self, root: Path, prompt: str) -> None:
        frontend = root / "frontend"
        backend = root / "backend"
        frontend_src = frontend / "src"
        backend_app = backend / "app"
        frontend_src.mkdir(parents=True, exist_ok=True)
        backend_app.mkdir(parents=True, exist_ok=True)

        (root / "README.md").write_text(
            f"""# Shaka Built Portfolio App

Generated from this brief:
{prompt}

## What is included

- Vite + React frontend with a portfolio-ready landing page and API status wiring.
- FastAPI backend with `/health` and `/api/status` endpoints.
- SQLite initialization at `backend/app.db` for a simple persistence path.
- CORS configured for local frontend development.

## Run the backend

```bash
cd backend
python -m venv .venv
.venv\\Scripts\\pip install -r requirements.txt
.venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000
```

On macOS/Linux, use `.venv/bin/pip` and `.venv/bin/python` instead.

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, usually `http://localhost:5173`.

## Verification

- Backend health: `http://localhost:8000/health`
- API status: `http://localhost:8000/api/status`

## Shaka verification commands

These commands are listed for deterministic verification. Shaka records them but does not run package managers by default.

```bash
python -m pytest tests/test_website_builder.py
python -c "from shaka.website_builder import inspect_project, plan_checks; print(inspect_project('.')); print(plan_checks('.'))"
```
""",
            encoding="utf-8",
        )
        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
                    "dependencies": {"@vitejs/plugin-react": "^4.0.0", "vite": "^5.0.0", "react": "^18.2.0", "react-dom": "^18.2.0"},
                    "devDependencies": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (frontend / "index.html").write_text(
            """<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Shaka App</title></head>
  <body><div id="root"></div><script type="module" src="/src/App.jsx"></script></body>
</html>
""",
            encoding="utf-8",
        )
        (frontend_src / "App.jsx").write_text(
            f"""import React, {{ useEffect, useState }} from 'react';
import {{ createRoot }} from 'react-dom/client';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function App() {{
  const [apiStatus, setApiStatus] = useState({{ state: 'checking', detail: 'Contacting backend...' }});

  useEffect(() => {{
    let active = true;
    fetch(`${{API_BASE}}/api/status`)
      .then((response) => {{
        if (!response.ok) {{
          throw new Error(`API returned ${{response.status}}`);
        }}
        return response.json();
      }})
      .then((data) => {{
        if (active) {{
          setApiStatus({{ state: 'online', detail: `${{data.service}} with ${{data.database_status}} database` }});
        }}
      }})
      .catch((error) => {{
        if (active) {{
          setApiStatus({{ state: 'offline', detail: error.message }});
        }}
      }});
    return () => {{
      active = false;
    }};
  }}, []);

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Portfolio-grade full-stack starter</p>
        <h1>{self._escape_jsx_title(prompt)}</h1>
        <p className="copy">A focused React experience backed by FastAPI, CORS-ready local development, and a SQLite persistence path.</p>
        <div className="actions">
          <a href={{API_BASE + '/health'}}>Backend health</a>
          <a href={{API_BASE + '/api/status'}}>API status</a>
        </div>
      </section>
      <section className="status-card" aria-live="polite">
        <span className={{'status-dot ' + apiStatus.state}} />
        <div>
          <p className="label">API status</p>
          <p>{{apiStatus.detail}}</p>
        </div>
      </section>
      <section className="grid">
        <article>
          <p className="label">Frontend</p>
          <h2>Clear product narrative</h2>
          <p>Hero, proof points, and calls to action are separated so the app can grow into a credible portfolio case study.</p>
        </article>
        <article>
          <p className="label">Backend</p>
          <h2>Operational endpoints</h2>
          <p>Health and status routes make smoke testing and browser verification straightforward from day one.</p>
        </article>
        <article>
          <p className="label">Data</p>
          <h2>SQLite initialized</h2>
          <p>The backend creates its database on startup and reports its path through the status endpoint.</p>
        </article>
      </section>
    </main>
  );
}}

createRoot(document.getElementById('root')).render(<App />);
""",
            encoding="utf-8",
        )
        (frontend_src / "styles.css").write_text(
            """:root { color-scheme: dark; --ink: #f6efe4; --muted: #b8ad9e; --panel: rgba(18, 24, 32, 0.82); --line: rgba(246, 239, 228, 0.16); --accent: #f2b84b; --ok: #41d18e; --bad: #ff6b6b; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Georgia, 'Times New Roman', serif; background: radial-gradient(circle at top left, #26384a 0, transparent 34%), linear-gradient(135deg, #101419 0%, #18212b 52%, #0e1116 100%); color: var(--ink); }
.shell { width: min(1120px, calc(100% - 32px)); min-height: 100vh; margin: 0 auto; padding: 56px 0; }
.hero { border: 1px solid var(--line); border-radius: 28px; padding: clamp(32px, 6vw, 72px); background: var(--panel); box-shadow: 0 24px 80px rgba(0, 0, 0, 0.34); }
.eyebrow, .label { color: var(--accent); text-transform: uppercase; letter-spacing: 0.12em; font: 700 12px/1.4 ui-sans-serif, system-ui, sans-serif; }
h1 { max-width: 900px; font-size: clamp(44px, 9vw, 92px); line-height: 0.92; margin: 14px 0; }
h2 { margin: 8px 0 12px; font-size: 24px; }
.copy { max-width: 720px; color: var(--muted); font-size: 20px; line-height: 1.6; }
.actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 28px; }
a { color: #15120a; background: var(--accent); padding: 12px 16px; border-radius: 999px; text-decoration: none; font: 800 14px/1 ui-sans-serif, system-ui, sans-serif; }
.status-card, article { border: 1px solid var(--line); border-radius: 22px; background: rgba(7, 10, 14, 0.54); }
.status-card { display: flex; gap: 14px; align-items: center; margin: 18px 0; padding: 18px; }
.status-card p { margin: 0; }
.status-dot { width: 14px; height: 14px; border-radius: 999px; background: var(--accent); box-shadow: 0 0 0 6px rgba(242, 184, 75, 0.12); }
.status-dot.online { background: var(--ok); box-shadow: 0 0 0 6px rgba(65, 209, 142, 0.12); }
.status-dot.offline { background: var(--bad); box-shadow: 0 0 0 6px rgba(255, 107, 107, 0.12); }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
article { padding: 24px; }
article p:last-child { color: var(--muted); line-height: 1.55; }
@media (max-width: 760px) { .grid { grid-template-columns: 1fr; } .hero { border-radius: 22px; } }
""",
            encoding="utf-8",
        )
        (backend / "requirements.txt").write_text("fastapi>=0.110\nuvicorn>=0.27\n", encoding="utf-8")
        (backend_app / "__init__.py").write_text("", encoding="utf-8")
        (backend_app / "main.py").write_text(
            """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from pathlib import Path

app = FastAPI(title="Shaka Built App")
DB_PATH = Path(__file__).resolve().parent.parent / "app.db"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT OR IGNORE INTO events (id, name) VALUES (1, 'scaffold-created')")


def database_ready():
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return count


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "shaka-built-app"}


@app.get("/api/status")
def status():
    return {
        "service": "shaka-built-app",
        "database": str(DB_PATH),
        "database_status": "ready",
        "events": database_ready(),
    }
""",
            encoding="utf-8",
        )

    @staticmethod
    def _escape_jsx_title(prompt: str) -> str:
        cleaned = " ".join(prompt.strip().split()) or "Full-stack app"
        return cleaned.replace("{", "").replace("}", "").replace("<", "").replace(">", "")[:90]
