"""Repo-specific developer memory for Shaka."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RepoMemory:
    """Store project summaries, commands, and preferences per repository."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser() / "repo-memory"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _repo_key(self, repo_path: str | Path) -> str:
        resolved = str(Path(repo_path).expanduser().resolve()).lower()
        return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]

    def _path(self, repo_path: str | Path) -> Path:
        return self.base_dir / f"{self._repo_key(repo_path)}.json"

    def load(self, repo_path: str | Path) -> dict[str, Any]:
        path = self._path(repo_path)
        if not path.exists():
            return {
                "repo_path": str(Path(repo_path).expanduser().resolve()),
                "summary": "",
                "commands": [],
                "decisions": [],
                "failures": [],
                "preferences": {},
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, repo_path: str | Path, memory: dict[str, Any]) -> dict[str, Any]:
        path = self._path(repo_path)
        path.write_text(json.dumps(memory, indent=2), encoding="utf-8")
        return memory

    def remember_command(self, repo_path: str | Path, command: str, result: str) -> dict[str, Any]:
        memory = self.load(repo_path)
        memory.setdefault("commands", []).append({"command": command, "result": result})
        return self.save(repo_path, memory)

    def remember_decision(self, repo_path: str | Path, decision: str) -> dict[str, Any]:
        memory = self.load(repo_path)
        memory.setdefault("decisions", []).append(decision)
        return self.save(repo_path, memory)
