"""Task context connectors for Shaka.

These provide lightweight, local-first equivalents of MCP-style task sources.
They can ingest task context from files or GitHub issues so Shaka has more
project-specific detail before it starts coding.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests


@dataclass
class ConnectorContext:
    label: str
    text: str


class ContextSource:
    def load(self) -> Optional[ConnectorContext]:
        raise NotImplementedError


class FileContextSource(ContextSource):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    def load(self) -> Optional[ConnectorContext]:
        if not self.path.exists() or not self.path.is_file():
            return None
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ConnectorContext(label=f"file:{self.path.name}", text=f"Unable to read {self.path}: {exc}")
        return ConnectorContext(label=f"file:{self.path.name}", text=text)


class GitHubIssueSource(ContextSource):
    ISSUE_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)", re.IGNORECASE)

    def __init__(self, issue_url: str, token: str | None = None, timeout: int = 20):
        self.issue_url = issue_url
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def load(self) -> Optional[ConnectorContext]:
        match = self.ISSUE_RE.search(self.issue_url)
        if not match:
            return ConnectorContext(label="github", text=f"Unsupported GitHub issue URL: {self.issue_url}")

        owner, repo, number = match.group(1), match.group(2), match.group(3)
        issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
        comments_url = f"{issue_url}/comments"

        try:
            issue = requests.get(issue_url, headers=self._headers(), timeout=self.timeout)
            issue.raise_for_status()
            payload = issue.json()

            comments_resp = requests.get(comments_url, headers=self._headers(), timeout=self.timeout)
            comments_resp.raise_for_status()
            comments = comments_resp.json() if isinstance(comments_resp.json(), list) else []
        except Exception as exc:
            return ConnectorContext(label="github", text=f"Unable to fetch issue context for {self.issue_url}: {exc}")

        labels = ", ".join(label.get("name", "") for label in payload.get("labels", []))
        body = payload.get("body") or ""
        title = payload.get("title") or f"Issue {number}"

        blocks = [
            f"GitHub Issue: {owner}/{repo}#{number}",
            f"Title: {title}",
        ]
        if labels:
            blocks.append(f"Labels: {labels}")
        if body:
            blocks.append("Body:\n" + body)

        if comments:
            blocks.append("Recent comments:")
            for comment in comments[-3:]:
                author = comment.get("user", {}).get("login", "unknown")
                text = (comment.get("body") or "").strip()
                blocks.append(f"- {author}: {text}")

        return ConnectorContext(label="github", text="\n\n".join(blocks))


def collect_connector_context(
    *,
    issue_url: str | None = None,
    context_file: str | Path | None = None,
    extra_notes: List[str] | None = None,
) -> List[ConnectorContext]:
    sources: List[ContextSource] = []
    if issue_url:
        sources.append(GitHubIssueSource(issue_url))
    if context_file:
        sources.append(FileContextSource(context_file))

    contexts: List[ConnectorContext] = []
    for source in sources:
        item = source.load()
        if item and item.text.strip():
            contexts.append(item)

    for note in extra_notes or []:
        note = note.strip()
        if note:
            contexts.append(ConnectorContext(label="note", text=note))

    return contexts

