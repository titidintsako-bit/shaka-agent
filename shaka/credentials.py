"""Local credential storage for Shaka providers.

The default path is outside the repo under ~/.shaka/credentials. Values are
stored only for local runtime use and are never printed by CLI/status surfaces.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CredentialStore:
    """Small JSON-backed local credential vault."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser()
        self.credentials_dir = self.base_dir / "credentials"
        self.path = self.credentials_dir / "providers.json"
        self.credentials_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"providers": {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
        except json.JSONDecodeError:
            data = {}
        data.setdefault("providers", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def set(self, provider: str, secret: str, *, label: str = "api_key") -> dict[str, Any]:
        provider = provider.strip().lower()
        secret = secret.strip()
        if not provider:
            raise ValueError("provider is required")
        if not secret:
            raise ValueError("secret is required")
        data = self._load()
        data["providers"][provider] = {
            "label": label,
            "secret": secret,
            "created_at": data["providers"].get(provider, {}).get("created_at", _utc_now()),
            "updated_at": _utc_now(),
        }
        self._save(data)
        return self.describe(provider)

    def get(self, provider: str) -> str:
        provider = provider.strip().lower()
        return str(self._load().get("providers", {}).get(provider, {}).get("secret", ""))

    def delete(self, provider: str) -> bool:
        provider = provider.strip().lower()
        data = self._load()
        existed = provider in data.get("providers", {})
        if existed:
            del data["providers"][provider]
            self._save(data)
        return existed

    def list(self) -> list[dict[str, Any]]:
        providers = self._load().get("providers", {})
        return [self._describe_record(name, record) for name, record in sorted(providers.items())]

    def describe(self, provider: str) -> dict[str, Any]:
        provider = provider.strip().lower()
        record = self._load().get("providers", {}).get(provider)
        if not record:
            raise KeyError(f"Unknown credential provider: {provider}")
        return self._describe_record(provider, record)

    def _describe_record(self, provider: str, record: dict[str, Any]) -> dict[str, Any]:
        secret = str(record.get("secret", ""))
        fingerprint = ""
        if secret:
            fingerprint = f"{'*' * 8}{secret[-4:]}"
        return {
            "provider": provider,
            "label": record.get("label", "api_key"),
            "configured": bool(secret),
            "fingerprint": fingerprint,
            "updated_at": record.get("updated_at", ""),
            "path": str(self.path),
        }
