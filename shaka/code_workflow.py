"""Utilities for Shaka's coding workflow.

This module builds a compact repository context that can be fed to the LLM
when the user asks Shaka to work on code. The goal is to give the model enough
signal to inspect files, patch the right areas, and verify its changes without
dumping the entire repo into the prompt.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
    "venv",
    ".venv",
    "shaka-desktop",
}

KEY_FILES = (
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "config.yaml",
)

PRIMARY_SOURCE_FILES = (
    "shaka/cli.py",
    "shaka/agent.py",
    "shaka/tui.py",
    "shaka/skills.py",
    "shaka/memory.py",
    "shaka/message_builder.py",
    "shaka/config.py",
)


@dataclass
class RepoFile:
    path: Path
    content: str


class RepoContextBuilder:
    """Builds a compact repo snapshot for coding tasks."""

    MODES = ("plan", "build", "review")

    def __init__(self, workspace_root: str | Path, focus_path: str | Path | None = None, max_files: int = 8, max_lines: int = 120):
        self.workspace_root = Path(workspace_root).resolve()
        self.focus_path = Path(focus_path).resolve() if focus_path else None
        self.max_files = max_files
        self.max_lines = max_lines

    def _is_ignored(self, path: Path) -> bool:
        return any(part in IGNORED_DIRS for part in path.parts)

    def _iter_files(self) -> Iterable[Path]:
        for path in sorted(self.workspace_root.rglob("*")):
            if not path.is_file():
                continue
            if self._is_ignored(path):
                continue
            yield path

    def _read_snippet(self, path: Path, max_lines: Optional[int] = None) -> str:
        limit = max_lines or self.max_lines
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"<<unable to read {path.name}: {exc}>>"

        lines = text.splitlines()
        if len(lines) > limit:
            trimmed = "\n".join(lines[:limit])
            return f"{trimmed}\n<<trimmed to first {limit} lines>>"
        return text

    def _candidate_paths(self) -> List[Path]:
        candidates: List[Path] = []
        seen = set()

        def add(path: Path) -> None:
            key = str(path)
            if key not in seen and path.exists() and path.is_file():
                seen.add(key)
                candidates.append(path)

        if self.focus_path and self.focus_path.exists():
            if self.focus_path.is_file():
                add(self.focus_path)
            else:
                for child in self.focus_path.rglob("*"):
                    if child.is_file() and not self._is_ignored(child):
                        add(child)
                        if len(candidates) >= self.max_files:
                            return candidates

        for rel in PRIMARY_SOURCE_FILES:
            add(self.workspace_root / rel)

        for rel in KEY_FILES:
            add(self.workspace_root / rel)

        for path in self._iter_files():
            if len(candidates) >= self.max_files:
                break
            if path in candidates:
                continue
            if path.suffix in {".py", ".md", ".toml", ".txt", ".yaml", ".yml"}:
                add(path)

        return candidates[: self.max_files]

    def build_tree(self, max_depth: int = 2) -> str:
        lines: List[str] = [f"{self.workspace_root.name}/"]

        def walk(directory: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except Exception:
                return
            for entry in entries:
                if self._is_ignored(entry):
                    continue
                prefix = "  " * depth + ("- " if entry.is_file() else "+ ")
                lines.append(f"{prefix}{entry.name}")
                if entry.is_dir():
                    walk(entry, depth + 1)

        walk(self.workspace_root, 1)
        return "\n".join(lines)

    def build_context(self) -> str:
        snippets: List[str] = []
        for path in self._candidate_paths():
            rel = path.relative_to(self.workspace_root)
            snippet = self._read_snippet(path)
            snippets.append(f"FILE: {rel}\n```text\n{snippet}\n```")
        return "\n\n".join(snippets)

    def normalize_mode(self, mode: str | None) -> str:
        normalized = (mode or "build").strip().lower()
        if normalized not in self.MODES:
            raise ValueError(f"Unsupported coding mode: {mode}")
        return normalized

    def coding_system_prompt(self, mode: str = "build") -> str:
        mode = self.normalize_mode(mode)
        if mode == "plan":
            return (
                "You are Shaka in plan mode. Inspect the repository, identify the "
                "minimal path to solve the task, and produce a structured plan. "
                "Do not invent edits. Focus on risks, dependencies, and the exact "
                "files that should change."
            )
        if mode == "review":
            return (
                "You are Shaka in review mode. Inspect the repository and evaluate "
                "the requested change for correctness, maintainability, security, and "
                "test coverage. Do not make edits. Return concrete findings and "
                "actionable recommendations."
            )
        return (
            "You are Shaka in build mode. Your job is to inspect the repository, "
            "make the smallest correct change, verify it, and explain the result. "
            "Use the available file and code execution tools aggressively but only "
            "for the files and checks that matter. Inspect the relevant files before "
            "editing. Verify the change after editing. Prefer incremental changes "
            "over broad rewrites. If the task is underspecified, ask for the missing "
            "constraints before editing anything."
        )

    def build_task_prompt(self, task: str, mode: str = "build") -> str:
        mode = self.normalize_mode(mode)
        mode_goal = {
            "plan": "Produce a change plan without editing files.",
            "build": "Implement the requested change with the smallest safe patch.",
            "review": "Review the requested change and report findings without editing files.",
        }[mode]
        return (
            f"Mode: {mode}\n"
            f"Goal: {mode_goal}\n\n"
            f"Task:\n{task}\n\n"
            f"Workspace root: {self.workspace_root}\n"
            f"Focus path: {self.focus_path or self.workspace_root}\n\n"
            f"Repository tree:\n{self.build_tree()}\n\n"
            f"Relevant files:\n{self.build_context()}\n\n"
            "If you need more context, use the file and code execution tools "
            "before answering. Return a concise, structured response."
        )

    def response_schema(self, mode: str = "build") -> str:
        mode = self.normalize_mode(mode)
        if mode == "plan":
            return (
                'Return exactly one JSON object and nothing else. '
                'Schema: {"summary": string, "plan": [string], "tests": [string], '
                '"risks": [string], "notes": [string]}. '
                "Use empty arrays when no items apply."
            )
        if mode == "review":
            return (
                'Return exactly one JSON object and nothing else. '
                'Schema: {"summary": string, "findings": [{"priority": "P0|P1|P2|P3", "file": string, "line": number, "body": string}], '
                '"tests": [string], "notes": [string]}. '
                "Use empty arrays when no findings, tests, or notes apply."
            )
        return (
            'Return exactly one JSON object and nothing else. '
            'Schema: {"summary": string, "edits": [{"path": string, "action": "replace|write|delete", "content": string}], '
            '"patches": [{"path": string, "diff": string}], "tests": [string], "notes": [string]}. '
            "Use empty arrays when no edits, tests, or notes apply."
        )

    def apply_unified_patch(self, patch_text: str) -> str:
        if not patch_text.strip():
            raise ValueError("Empty patch text")

        try:
            result = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                input=patch_text,
                text=True,
                capture_output=True,
                cwd=str(self.workspace_root),
                timeout=120,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("git is required to apply unified diffs") from exc

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git apply failed")

        return "git apply succeeded"

    def apply_unified_patches(self, patches: List[dict]) -> List[str]:
        applied: List[str] = []
        for patch in patches:
            path = patch.get("path")
            diff = patch.get("diff", "")
            if not path or not diff:
                continue
            applied.append(f"patch: {path}")
            applied.append(self.apply_unified_patch(diff))
        return applied
