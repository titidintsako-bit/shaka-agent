"""Model provider catalog and local credential resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    api_key_env: str
    default_model: str
    base_url: str = ""
    mode: str = "byok"
    openai_compatible: bool = False
    requires_api_key: bool = True


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "ollama": ProviderSpec(
        name="ollama",
        label="Ollama",
        api_key_env="",
        default_model="qwen2.5:7b",
        base_url="http://localhost:11434",
        mode="local",
        openai_compatible=True,
        requires_api_key=False,
    ),
    "openai": ProviderSpec(
        name="openai",
        label="OpenAI",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        openai_compatible=True,
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        label="Anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-3-5-haiku-latest",
    ),
    "groq": ProviderSpec(
        name="groq",
        label="Groq",
        api_key_env="GROQ_API_KEY",
        default_model="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        openai_compatible=True,
    ),
    "gemini": ProviderSpec(
        name="gemini",
        label="Google Gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.0-flash",
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        label="OpenRouter",
        api_key_env="OPENROUTER_API_KEY",
        default_model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
        openai_compatible=True,
    ),
    "mistral": ProviderSpec(
        name="mistral",
        label="Mistral",
        api_key_env="MISTRAL_API_KEY",
        default_model="mistral-small-latest",
        base_url="https://api.mistral.ai/v1",
        openai_compatible=True,
    ),
    "together": ProviderSpec(
        name="together",
        label="Together AI",
        api_key_env="TOGETHER_API_KEY",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        base_url="https://api.together.xyz/v1",
        openai_compatible=True,
    ),
    "fireworks": ProviderSpec(
        name="fireworks",
        label="Fireworks AI",
        api_key_env="FIREWORKS_API_KEY",
        default_model="accounts/fireworks/models/llama-v3p1-8b-instruct",
        base_url="https://api.fireworks.ai/inference/v1",
        openai_compatible=True,
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        label="DeepSeek",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        base_url="https://api.deepseek.com",
        openai_compatible=True,
    ),
    "xai": ProviderSpec(
        name="xai",
        label="xAI",
        api_key_env="XAI_API_KEY",
        default_model="grok-2-latest",
        base_url="https://api.x.ai/v1",
        openai_compatible=True,
    ),
    "cerebras": ProviderSpec(
        name="cerebras",
        label="Cerebras",
        api_key_env="CEREBRAS_API_KEY",
        default_model="llama3.1-8b",
        base_url="https://api.cerebras.ai/v1",
        openai_compatible=True,
    ),
    "perplexity": ProviderSpec(
        name="perplexity",
        label="Perplexity",
        api_key_env="PERPLEXITY_API_KEY",
        default_model="sonar",
        base_url="https://api.perplexity.ai",
        openai_compatible=True,
    ),
}


ALIASES = {
    "google": "gemini",
    "google-ai": "gemini",
    "googleai": "gemini",
    "open-router": "openrouter",
    "open_router": "openrouter",
    "togetherai": "together",
    "fireworksai": "fireworks",
    "deepseek-ai": "deepseek",
    "grok": "xai",
    "local": "ollama",
}


def normalize_provider(name: str | None) -> str:
    selected = (name or "groq").strip().lower()
    return ALIASES.get(selected, selected)


def provider_names() -> list[str]:
    return sorted(PROVIDER_SPECS)


def get_provider_spec(name: str | None) -> ProviderSpec:
    provider = normalize_provider(name)
    if provider not in PROVIDER_SPECS:
        raise KeyError(f"Unknown provider: {provider}")
    return PROVIDER_SPECS[provider]


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "label": spec.label,
            "api_key_env": spec.api_key_env,
            "default_model": spec.default_model,
            "base_url": spec.base_url,
            "mode": spec.mode,
            "openai_compatible": spec.openai_compatible,
            "requires_api_key": spec.requires_api_key,
        }
        for spec in sorted(PROVIDER_SPECS.values(), key=lambda item: item.name)
    ]


def configured_api_key_env(config: Any) -> str:
    provider = normalize_provider(getattr(config.model, "provider", "groq"))
    explicit = getattr(config.model, "api_key_env", "") or ""
    if explicit:
        return explicit
    try:
        from shaka.local_state import load_local_config_data

        local_data = load_local_config_data(config.paths.base_dir)
        explicit = local_data.get("model", {}).get("api_key_env") or ""
    except Exception:
        explicit = ""
    if explicit:
        return str(explicit)
    try:
        return get_provider_spec(provider).api_key_env
    except KeyError:
        return "SHAKA_API_KEY"


def resolve_api_key(config: Any) -> tuple[str, str]:
    """Return (api_key, source) without printing secret values."""
    provider = normalize_provider(getattr(config.model, "provider", "groq"))
    try:
        spec = get_provider_spec(provider)
    except KeyError:
        spec = None
    if spec and not spec.requires_api_key:
        return "", "local_provider"

    env_name = configured_api_key_env(config)
    for candidate in [env_name, "SHAKA_API_KEY"]:
        if candidate and os.environ.get(candidate):
            return os.environ[candidate], "environment"

    if getattr(config.model, "api_key", ""):
        return config.model.api_key, "runtime_config"

    try:
        from shaka.credentials import CredentialStore

        secret = CredentialStore(config.paths.base_dir).get(provider)
        if secret:
            return secret, "local_credentials"
    except Exception:
        pass
    return "", "none"


def is_model_configured(config: Any) -> bool:
    provider = normalize_provider(getattr(config.model, "provider", "groq"))
    try:
        spec = get_provider_spec(provider)
    except KeyError:
        spec = None
    if spec and not spec.requires_api_key:
        return True
    api_key, _source = resolve_api_key(config)
    return bool(api_key)
