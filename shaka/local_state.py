"""Local-first runtime state for Shaka."""

from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shaka.automation import TaskStore
from shaka.config import ShakaConfig
from shaka.cron import CronStore
from shaka.credentials import CredentialStore
from shaka.memory import MemoryManager
from shaka.providers import get_provider_spec, normalize_provider, provider_catalog, resolve_api_key
from shaka.skills import SkillsRegistry


DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 18789
DEFAULT_API_KEY_ENV = "SHAKA_API_KEY"
LOCAL_STATE_DIRS = (
    "workspace",
    "sessions",
    "memory",
    "skills",
    "credentials",
    "runtime",
    "logs",
)


def utc_now() -> str:
    """Return a compact UTC timestamp for local metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def shaka_home(home: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the local Shaka home directory."""
    selected = home or os.environ.get("SHAKA_HOME") or "~/.shaka"
    return Path(selected).expanduser()


def local_config_path(home: str | os.PathLike[str] | None = None) -> Path:
    """Return the local-first config path."""
    return shaka_home(home) / "config.json"


def default_local_config(
    home: str | os.PathLike[str] | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
    token: str | None = None,
) -> dict[str, Any]:
    """Build the default config payload stored at ~/.shaka/config.json."""
    root = shaka_home(home)
    provider_name = normalize_provider(provider or os.environ.get("SHAKA_PROVIDER") or "groq")
    try:
        spec = get_provider_spec(provider_name)
    except KeyError:
        spec = get_provider_spec("groq")
    model_name = model or os.environ.get("SHAKA_MODEL") or spec.default_model
    return {
        "version": 1,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "model": {
            "provider": provider_name,
            "model": model_name,
            "api_key_env": api_key_env,
            "base_url": os.environ.get("SHAKA_BASE_URL", spec.base_url),
        },
        "gateway": {
            "host": host,
            "port": int(port),
            "token": token or os.environ.get("SHAKA_GATEWAY_TOKEN") or secrets.token_urlsafe(32),
        },
        "paths": {
            "base_dir": str(root),
            "workspace": str(root / "workspace"),
            "sessions": str(root / "sessions"),
            "memory": str(root / "memory"),
            "skills": str(root / "skills"),
            "credentials": str(root / "credentials"),
            "runtime": str(root / "runtime"),
            "logs": str(root / "logs"),
        },
        "security": {
            "bind_loopback_by_default": True,
            "store_secrets_in_config": False,
            "credentials_dir": str(root / "credentials"),
        },
    }


def load_local_config_data(home: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read ~/.shaka/config.json if it exists."""
    path = local_config_path(home)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def save_local_config_data(data: dict[str, Any], home: str | os.PathLike[str] | None = None) -> Path:
    """Write ~/.shaka/config.json."""
    path = local_config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    return path


def ensure_local_state(
    home: str | os.PathLike[str] | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
    rotate_token: bool = False,
) -> dict[str, Any]:
    """Create the local Shaka home, directory layout, and config file."""
    root = shaka_home(home)
    root.mkdir(parents=True, exist_ok=True)
    for dirname in LOCAL_STATE_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)

    credentials_readme = root / "credentials" / "README.md"
    if not credentials_readme.exists():
        credentials_readme.write_text(
            "Place local credential files here when needed. Prefer environment variables for API keys.\n",
            encoding="utf-8",
        )

    workspace_readme = root / "workspace" / "README.md"
    if not workspace_readme.exists():
        workspace_readme.write_text(
            "# Shaka Workspace\n\nUse this folder for local projects and demo workflows managed by Shaka.\n",
            encoding="utf-8",
        )

    data = load_local_config_data(root)
    if not data:
        data = default_local_config(
            root,
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            host=host,
            port=port,
        )
    else:
        data.setdefault("version", 1)
        data.setdefault("created_at", utc_now())
        data.setdefault("model", {})
        data.setdefault("gateway", {})
        data.setdefault("paths", {})
        data.setdefault("security", {})
        data["model"].setdefault("api_key_env", api_key_env)
        data["gateway"].setdefault("host", host)
        data["gateway"].setdefault("port", int(port))
        if rotate_token or not data["gateway"].get("token"):
            data["gateway"]["token"] = os.environ.get("SHAKA_GATEWAY_TOKEN") or secrets.token_urlsafe(32)
        data["security"].setdefault("store_secrets_in_config", False)

    if provider:
        data["model"]["provider"] = normalize_provider(provider)
        try:
            spec = get_provider_spec(provider)
            data["model"].setdefault("model", spec.default_model)
            data["model"].setdefault("base_url", spec.base_url)
        except KeyError:
            pass
    if model:
        data["model"]["model"] = model
    if api_key_env:
        data["model"].setdefault("api_key_env", api_key_env)
    if host:
        data["gateway"]["host"] = host
    if port:
        data["gateway"]["port"] = int(port)

    for dirname in LOCAL_STATE_DIRS:
        data["paths"][dirname] = str(root / dirname)
    data["paths"]["base_dir"] = str(root)

    path = save_local_config_data(data, root)
    data["_config_path"] = str(path)
    return data


def apply_local_config(config: ShakaConfig, local_data: dict[str, Any]) -> ShakaConfig:
    """Apply local config JSON fields to a loaded ShakaConfig instance."""
    paths = local_data.get("paths", {}) if isinstance(local_data, dict) else {}
    model = local_data.get("model", {}) if isinstance(local_data, dict) else {}
    gateway = local_data.get("gateway", {}) if isinstance(local_data, dict) else {}

    if paths.get("base_dir"):
        config.paths.base_dir = str(Path(paths["base_dir"]).expanduser())
    if paths.get("skills"):
        config.paths.skills_dir = str(Path(paths["skills"]).expanduser())
    if paths.get("runtime"):
        config.paths.db_path = str(Path(paths["runtime"]).expanduser() / "shaka.db")

    if model.get("provider"):
        config.model.provider = normalize_provider(str(model["provider"]))
    if model.get("model"):
        config.model.model = str(model["model"])
    if model.get("api_key_env"):
        config.model.api_key_env = str(model["api_key_env"])
    if model.get("base_url"):
        config.model.base_url = str(model["base_url"])
    if gateway.get("host"):
        config.dashboard.host = str(gateway["host"])
    if gateway.get("port"):
        config.dashboard.port = int(gateway["port"])
    return config


def get_gateway_token(home: str | os.PathLike[str] | None = None) -> str:
    """Return the local gateway token, creating one if necessary."""
    data = ensure_local_state(home)
    return str(data.get("gateway", {}).get("token", ""))


def rotate_gateway_token(home: str | os.PathLike[str] | None = None) -> str:
    """Rotate the local gateway token."""
    data = ensure_local_state(home, rotate_token=True)
    return str(data.get("gateway", {}).get("token", ""))


def provider_status(config: ShakaConfig) -> dict[str, Any]:
    """Return provider metadata without exposing secret values."""
    provider = normalize_provider(config.model.provider)
    try:
        spec = get_provider_spec(provider)
    except KeyError:
        spec = get_provider_spec("groq")
    env_name = config.model.api_key_env or spec.api_key_env or DEFAULT_API_KEY_ENV
    credential_configured = False
    try:
        credential_configured = bool(CredentialStore(config.paths.base_dir).get(provider))
    except Exception:
        credential_configured = False
    api_key, source = resolve_api_key(config)
    if credential_configured and source == "runtime_config":
        source = "local_credentials"
    configured = bool(api_key or not spec.requires_api_key or credential_configured)
    return {
        "provider": provider,
        "label": spec.label,
        "model": config.model.model,
        "base_url": config.model.base_url or spec.base_url,
        "api_key_env": env_name,
        "configured": configured or credential_configured,
        "credential_configured": credential_configured,
        "source": source,
        "mode": spec.mode,
        "supported": provider in {item["name"] for item in provider_catalog()},
    }


def load_skills(config: ShakaConfig) -> SkillsRegistry:
    """Load core and user-installed skills quietly for status surfaces."""
    registry = SkillsRegistry()
    core_skills_dir = Path(__file__).resolve().parent / "skills_core"
    registry.load_core_skills(str(core_skills_dir), verbose=False)
    registry.load_user_skills(config.paths.skills_dir, verbose=False)
    return registry


def install_skill(source: str, config: ShakaConfig) -> Path:
    """Install a local skill directory into ~/.shaka/skills."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists() or not source_path.is_dir():
        raise FileNotFoundError(f"Skill source directory not found: {source}")
    if not (source_path / "skill.yaml").exists():
        raise ValueError("Skill source must contain skill.yaml")

    target_root = Path(config.paths.skills_dir).expanduser()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / source_path.name
    if target.exists():
        raise FileExistsError(f"Skill already installed: {target}")
    shutil.copytree(source_path, target)
    return target


def runtime_status(config: ShakaConfig) -> dict[str, Any]:
    """Return local runtime state for the gateway and dashboard."""
    root = Path(config.paths.base_dir).expanduser()
    ensure_local_state(root)
    memory = MemoryManager(str(root))
    task_store = TaskStore(str(root))
    skills = load_skills(config).list_skills()
    sessions = memory.list_sessions("default")
    tasks = task_store.list_tasks()
    approvals = task_store.list_approvals(status="pending")
    credentials = CredentialStore(str(root)).list()
    cron = CronStore(str(root))
    daemon_path = root / "runtime" / "daemon.json"
    daemon = {"running": False, "state_path": str(daemon_path)}
    if daemon_path.exists():
        try:
            with daemon_path.open("r", encoding="utf-8") as handle:
                daemon.update(json.load(handle) or {})
        except json.JSONDecodeError:
            daemon["error"] = "daemon state is not valid JSON"

    recent_tool_calls = []
    for task in tasks[:8]:
        for step in task.get("steps", [])[-3:]:
            recent_tool_calls.append({
                "task_id": task.get("id"),
                "kind": step.get("kind"),
                "message": step.get("message"),
                "created_at": step.get("created_at"),
            })

    return {
        "service": "shaka-gateway",
        "status": "ok",
        "local_first": True,
        "home": str(root),
        "config_path": str(local_config_path(root)),
        "workspace_path": str(root / "workspace"),
        "state": {
            dirname: {
                "path": str(root / dirname),
                "exists": (root / dirname).exists(),
            }
            for dirname in LOCAL_STATE_DIRS
        },
        "gateway": {
            "host": config.dashboard.host,
            "port": config.dashboard.port,
            "auth": "token",
            "binds_loopback": config.dashboard.host in {"127.0.0.1", "localhost", "::1"},
        },
        "provider": provider_status(config),
        "credential_count": len(credentials),
        "credentials": credentials,
        "providers": provider_catalog(),
        "cron_jobs": cron.list_jobs(),
        "cron_job_count": len(cron.list_jobs()),
        "daemon": daemon,
        "sessions": sessions[:12],
        "session_count": len(sessions),
        "skills": skills,
        "skill_count": len(skills),
        "tasks": tasks[:12],
        "task_count": len(tasks),
        "pending_approvals": approvals,
        "pending_approval_count": len(approvals),
        "recent_tool_calls": recent_tool_calls[:12],
    }
