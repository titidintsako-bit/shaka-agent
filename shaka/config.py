"""Configuration management for Shaka.

Handles loading, saving, and validating local-first JSON config and legacy YAML.
"""

import json
import os
import secrets
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ModelConfig:
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    api_key: str = ""
    api_key_env: str = "SHAKA_API_KEY"
    base_url: str = ""  # for openrouter/ollama

@dataclass
class WhatsAppConfig:
    enabled: bool = False
    qr_code: str = ""
    instance_name: str = "shaka"

@dataclass
class DashboardConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 18789

@dataclass
class DataPaths:
    base_dir: str = field(default_factory=lambda: os.path.expanduser(os.environ.get("SHAKA_HOME", "~/.shaka")))
    users_dir: str = ""
    skills_dir: str = ""
    db_path: str = ""
    workspace_dir: str = ""
    sessions_dir: str = ""
    memory_dir: str = ""
    credentials_dir: str = ""
    runtime_dir: str = ""
    logs_dir: str = ""

    def __post_init__(self):
        self.base_dir = os.path.expanduser(self.base_dir)
        if not self.workspace_dir:
            self.workspace_dir = os.path.join(self.base_dir, "workspace")
        if not self.sessions_dir:
            self.sessions_dir = os.path.join(self.base_dir, "sessions")
        if not self.memory_dir:
            self.memory_dir = os.path.join(self.base_dir, "memory")
        if not self.users_dir:
            self.users_dir = os.path.join(self.memory_dir, "users")
        if not self.skills_dir:
            self.skills_dir = os.path.join(self.base_dir, "skills")
        if not self.credentials_dir:
            self.credentials_dir = os.path.join(self.base_dir, "credentials")
        if not self.runtime_dir:
            self.runtime_dir = os.path.join(self.base_dir, "runtime")
        if not self.logs_dir:
            self.logs_dir = os.path.join(self.base_dir, "logs")
        if not self.db_path:
            self.db_path = os.path.join(self.runtime_dir, "shaka.db")

@dataclass
class ShakaConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    paths: DataPaths = field(default_factory=DataPaths)
    name: str = "Shaka"
    language: str = "en"
    system_prompt: str = ""
    personality: dict = field(default_factory=dict)


DEFAULT_PERSONALITY = {
    "default_preset": "warm",
    "default_profile": "Warm, practical, direct.",
    "instructions": "Be clear, helpful, and concise unless the user asks for detail.",
    "presets": {
        "warm": "Warm, practical, direct, and encouraging.",
        "concise": "Direct, minimal, and efficient.",
        "technical": "Precise, engineering-focused, and implementation-oriented.",
        "mentor": "Patient, explanatory, and step-by-step.",
        "playful": "Lightly playful while staying useful and respectful.",
    },
}

DEFAULT_SYSTEM_PROMPT = """You are Shaka, a South African AI developer agent created by Ntsako.
You are running on a user's local machine and have access to tools via function calling.

IMPORTANT RULES:
- When a user asks you to search the web, look up information, check load shedding, or do other tasks available as tools, you MUST use the provided tool_call mechanism. Call the tool directly via the tool_calls array in your response. Do NOT write code to perform these actions.
- If you are unsure whether a tool is available, check the tools list.
- Be concise, friendly, and helpful.
- For coding tasks, be practical and direct. If the user asks for code changes, debugging, refactors, or repo work, treat that as a real engineering task and help them solve it.
- When you don't know something, say so honestly.
- Never pretend to have capabilities you don't have.
- You can remember information across conversations.
- You are South African and understand local context (load shedding, EskomSePush, local bandwidth/cost constraints, etc).
"""

def default_config_path() -> str:
    """Return the default local-first config path."""
    configured = os.environ.get("SHAKA_CONFIG")
    if configured:
        return os.path.expanduser(configured)
    return os.path.join(os.path.expanduser(os.environ.get("SHAKA_HOME", "~/.shaka")), "config.json")


def _select_config_path(config_path: Optional[str] = None) -> str:
    if config_path:
        return os.path.expanduser(config_path)

    local_path = default_config_path()
    if os.path.exists(local_path):
        return local_path

    legacy_path = os.path.join(os.getcwd(), "config.yaml")
    if os.path.exists(legacy_path):
        return legacy_path

    return local_path


def _config_from_dict(data: dict) -> ShakaConfig:
    """Build a ShakaConfig from either local JSON or legacy YAML data."""
    model_data = data.get('model', {}) or {}
    whatsapp_data = data.get('whatsapp', {}) or {}
    dashboard_data = data.get('dashboard') or data.get('gateway', {}) or {}
    paths_data = data.get('paths', {}) or {}

    paths = DataPaths(
        base_dir=paths_data.get('base_dir', os.path.expanduser(os.environ.get("SHAKA_HOME", "~/.shaka"))),
        users_dir=paths_data.get('users_dir', ''),
        skills_dir=paths_data.get('skills') or paths_data.get('skills_dir', ''),
        db_path=paths_data.get('db_path', ''),
        workspace_dir=paths_data.get('workspace') or paths_data.get('workspace_dir', ''),
        sessions_dir=paths_data.get('sessions') or paths_data.get('sessions_dir', ''),
        memory_dir=paths_data.get('memory') or paths_data.get('memory_dir', ''),
        credentials_dir=paths_data.get('credentials') or paths_data.get('credentials_dir', ''),
        runtime_dir=paths_data.get('runtime') or paths_data.get('runtime_dir', ''),
        logs_dir=paths_data.get('logs') or paths_data.get('logs_dir', ''),
    )

    loaded_personality = data.get('personality', {}) or {}
    merged_personality = dict(DEFAULT_PERSONALITY)
    merged_personality.update({k: v for k, v in loaded_personality.items() if k != "presets"})
    merged_personality["presets"] = dict(DEFAULT_PERSONALITY["presets"])
    merged_personality["presets"].update(loaded_personality.get("presets", {}) or {})

    return ShakaConfig(
        model=ModelConfig(
            provider=model_data.get('provider', 'groq'),
            model=model_data.get('model', 'llama-3.3-70b-versatile'),
            api_key=model_data.get('api_key', ''),
            api_key_env=model_data.get('api_key_env', ''),
            base_url=model_data.get('base_url', ''),
        ),
        whatsapp=WhatsAppConfig(
            enabled=whatsapp_data.get('enabled', False),
            qr_code=whatsapp_data.get('qr_code', ''),
            instance_name=whatsapp_data.get('instance_name', 'shaka'),
        ),
        dashboard=DashboardConfig(
            enabled=dashboard_data.get('enabled', True),
            host=dashboard_data.get('host', '127.0.0.1'),
            port=int(dashboard_data.get('port', 18789)),
        ),
        paths=paths,
        name=data.get('name', 'Shaka'),
        language=data.get('language', 'en'),
        system_prompt=data.get('system_prompt', DEFAULT_SYSTEM_PROMPT),
        personality=merged_personality,
    )


def _config_to_dict(config: ShakaConfig, *, include_gateway: bool = True) -> dict:
    data = {
        'name': config.name,
        'language': config.language,
        'system_prompt': config.system_prompt,
        'personality': config.personality,
        'model': {
            'provider': config.model.provider,
            'model': config.model.model,
            'api_key': config.model.api_key,
            'api_key_env': config.model.api_key_env,
            'base_url': config.model.base_url,
        },
        'whatsapp': {
            'enabled': config.whatsapp.enabled,
            'instance_name': config.whatsapp.instance_name,
        },
        'dashboard': {
            'enabled': config.dashboard.enabled,
            'host': config.dashboard.host,
            'port': config.dashboard.port,
        },
        'paths': {
            'base_dir': config.paths.base_dir,
            'workspace': config.paths.workspace_dir,
            'sessions': config.paths.sessions_dir,
            'memory': config.paths.memory_dir,
            'skills': config.paths.skills_dir,
            'credentials': config.paths.credentials_dir,
            'runtime': config.paths.runtime_dir,
            'logs': config.paths.logs_dir,
        }
    }
    if include_gateway:
        data['gateway'] = {
            'host': config.dashboard.host,
            'port': config.dashboard.port,
        }
    return data


def _apply_env_overrides(config: ShakaConfig) -> ShakaConfig:
    from shaka.providers import get_provider_spec, normalize_provider, resolve_api_key

    if os.environ.get('SHAKA_HOME'):
        config.paths = DataPaths(base_dir=os.environ['SHAKA_HOME'])
    if os.environ.get('SHAKA_PROVIDER'):
        config.model.provider = normalize_provider(os.environ['SHAKA_PROVIDER'])
    else:
        config.model.provider = normalize_provider(config.model.provider)
    try:
        spec = get_provider_spec(config.model.provider)
        if not config.model.model:
            config.model.model = spec.default_model
        if not config.model.api_key_env:
            config.model.api_key_env = spec.api_key_env
        if not config.model.base_url and spec.base_url:
            config.model.base_url = spec.base_url
    except KeyError:
        if not config.model.api_key_env:
            config.model.api_key_env = "SHAKA_API_KEY"
    if os.environ.get('SHAKA_MODEL'):
        config.model.model = os.environ['SHAKA_MODEL']
    api_key, _source = resolve_api_key(config)
    if api_key:
        config.model.api_key = api_key
    if os.environ.get('SHAKA_BASE_URL'):
        config.model.base_url = os.environ['SHAKA_BASE_URL']
    if os.environ.get('SHAKA_LANGUAGE'):
        config.language = os.environ['SHAKA_LANGUAGE']
    if os.environ.get('SHAKA_HOST'):
        config.dashboard.host = os.environ['SHAKA_HOST']
    if os.environ.get('SHAKA_PORT'):
        config.dashboard.port = int(os.environ['SHAKA_PORT'])
    return config


def load_config(config_path: Optional[str] = None) -> ShakaConfig:
    """Load configuration from JSON/YAML or create local-first defaults."""
    if config_path is None:
        config_path = _select_config_path(config_path)

    if not os.path.exists(config_path):
        return create_default_config(config_path)

    with open(config_path, 'r', encoding="utf-8") as f:
        if str(config_path).lower().endswith(".json"):
            data = json.load(f) or {}
        else:
            data = yaml.safe_load(f) or {}

    return _apply_env_overrides(_config_from_dict(data))

def create_default_config(config_path: str) -> ShakaConfig:
    """Create a default configuration file and return it."""
    config_path = os.path.expanduser(config_path)
    config = ShakaConfig(paths=DataPaths(base_dir=os.path.dirname(config_path) if str(config_path).endswith("config.json") else os.path.expanduser(os.environ.get("SHAKA_HOME", "~/.shaka"))))

    os.makedirs(os.path.dirname(config_path) if os.path.dirname(config_path) else '.', exist_ok=True)

    # Ensure data directories exist
    for directory in (
        config.paths.workspace_dir,
        config.paths.sessions_dir,
        config.paths.memory_dir,
        config.paths.users_dir,
        config.paths.skills_dir,
        config.paths.credentials_dir,
        config.paths.runtime_dir,
        config.paths.logs_dir,
    ):
        os.makedirs(directory, exist_ok=True)

    data = _config_to_dict(config)
    if config_path.lower().endswith(".json"):
        data["model"].pop("api_key", None)
        data["model"]["api_key_env"] = config.model.api_key_env or "SHAKA_API_KEY"
        data["gateway"]["token"] = os.environ.get("SHAKA_GATEWAY_TOKEN") or secrets.token_urlsafe(32)
        data["security"] = {
            "bind_loopback_by_default": True,
            "store_secrets_in_config": False,
            "credentials_dir": config.paths.credentials_dir,
        }

    with open(config_path, 'w', encoding="utf-8") as f:
        if config_path.lower().endswith(".json"):
            json.dump(data, f, indent=2)
            f.write("\n")
        else:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    print(f"Created default config: {config_path}")
    return _apply_env_overrides(config)

def save_config(config: ShakaConfig, config_path: str):
    """Save configuration to YAML file."""
    config_path = os.path.expanduser(config_path)
    data = _config_to_dict(config)
    if config_path.lower().endswith(".json"):
        data["model"].pop("api_key", None)
        data["model"]["api_key_env"] = config.model.api_key_env or "SHAKA_API_KEY"
        data.setdefault("security", {
            "bind_loopback_by_default": True,
            "store_secrets_in_config": False,
            "credentials_dir": config.paths.credentials_dir,
        })

    with open(config_path, 'w', encoding="utf-8") as f:
        if config_path.lower().endswith(".json"):
            json.dump(data, f, indent=2)
            f.write("\n")
        else:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
