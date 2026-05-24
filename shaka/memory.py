"""Memory system for Shaka.

Manages per-user memory, session history, and the wiki.
All stored locally in JSON + SQLite.
"""

import os
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from datetime import datetime

class MemoryManager:
    """Handles all memory operations for Shaka."""

    _SECRET_PATTERNS = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
        re.compile(r"\b(?:[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))=([^\s,;]+)"),
        re.compile(r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)", re.IGNORECASE),
    )

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.memory_dir = os.path.join(base_dir, "memory")
        self.sessions_dir = os.path.join(base_dir, "sessions")
        self.users_dir = os.path.join(self.memory_dir, "users")
        self.legacy_users_dir = os.path.join(base_dir, "users")
        self.search_db_path = os.path.join(self.memory_dir, "search.sqlite3")
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)
        os.makedirs(self.users_dir, exist_ok=True)
        self._init_search_index()

    def get_user_dir(self, user_id: str) -> str:
        """Get the memory directory for a specific user."""
        user_dir = os.path.join(self.users_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(os.path.join(user_dir, "skills"), exist_ok=True)
        return user_dir

    def get_session_dir(self, user_id: str) -> str:
        """Get the top-level session directory for a specific user."""
        session_dir = os.path.join(self.sessions_dir, user_id)
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    def get_legacy_user_dir(self, user_id: str) -> str:
        """Return the legacy ~/.shaka/users/<user> path for migration reads."""
        return os.path.join(self.legacy_users_dir, user_id)

    def load_memory(self, user_id: str) -> dict:
        """Load a user's persistent memory."""
        user_dir = self.get_user_dir(user_id)
        memory_path = os.path.join(user_dir, "memory.json")

        if os.path.exists(memory_path):
            with open(memory_path, 'r') as f:
                return json.load(f)

        legacy_memory_path = os.path.join(self.get_legacy_user_dir(user_id), "memory.json")
        if os.path.exists(legacy_memory_path):
            with open(legacy_memory_path, 'r') as f:
                return json.load(f)

        return {
            "user_id": user_id,
            "name": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "facts": [],
            "preferences": {},
            "skills_installed": [],
            "wiki": {},
        }

    def save_memory(self, user_id: str, memory: dict):
        """Save a user's persistent memory."""
        user_dir = self.get_user_dir(user_id)
        memory_path = os.path.join(user_dir, "memory.json")
        memory["updated_at"] = datetime.now().isoformat()

        with open(memory_path, 'w') as f:
            json.dump(memory, f, indent=2)

    def add_fact(self, user_id: str, fact: str):
        """Add a fact to user's memory."""
        memory = self.load_memory(user_id)
        memory["facts"].append({
            "text": fact,
            "timestamp": datetime.now().isoformat(),
        })
        self.save_memory(user_id, memory)
        return memory

    def get_facts(self, user_id: str) -> list:
        """Get all facts about a user."""
        memory = self.load_memory(user_id)
        return memory.get("facts", [])

    # Session history

    def load_session(self, user_id: str, session_id: str) -> list:
        """Load a conversation session."""
        session_path = os.path.join(self.get_session_dir(user_id), f"{session_id}.json")

        if os.path.exists(session_path):
            with open(session_path, 'r') as f:
                return json.load(f)

        legacy_session_path = os.path.join(self.get_legacy_user_dir(user_id), "sessions", f"{session_id}.json")
        if os.path.exists(legacy_session_path):
            with open(legacy_session_path, 'r') as f:
                return json.load(f)
        return []

    def save_session(self, user_id: str, session_id: str, messages: list):
        """Save a conversation session."""
        session_path = os.path.join(self.get_session_dir(user_id), f"{session_id}.json")

        with open(session_path, 'w') as f:
            json.dump(messages, f, indent=2)

    def list_sessions(self, user_id: str) -> list:
        """List all sessions for a user."""
        sessions_dir = self.get_session_dir(user_id)

        if not os.path.exists(sessions_dir):
            return []

        sessions = []
        seen = set()
        candidate_dirs = [
            sessions_dir,
            os.path.join(self.get_legacy_user_dir(user_id), "sessions"),
        ]
        for candidate_dir in candidate_dirs:
            if not os.path.exists(candidate_dir):
                continue
            for filename in os.listdir(candidate_dir):
                if not filename.endswith('.json'):
                    continue
                session_id = filename.replace('.json', '')
                if session_id in seen:
                    continue
                seen.add(session_id)
                path = os.path.join(candidate_dir, filename)
                stat = os.stat(path)
                sessions.append({
                    "session_id": session_id,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "updated": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "path": path,
                })

        return sorted(sessions, key=lambda x: x["updated"], reverse=True)

    def get_recent_messages(self, user_id: str, session_id: str, limit: int = 10) -> list:
        """Get the last N messages from a session."""
        session = self.load_session(user_id, session_id)
        return session[-limit:]

    # Wiki

    def save_wiki_page(self, user_id: str, title: str, content: str):
        """Save a wiki page."""
        memory = self.load_memory(user_id)
        if "wiki" not in memory:
            memory["wiki"] = {}

        memory["wiki"][title] = {
            "content": content,
            "updated": datetime.now().isoformat(),
        }
        self.save_memory(user_id, memory)

    def load_wiki_page(self, user_id: str, title: str) -> str:
        """Load a wiki page."""
        memory = self.load_memory(user_id)
        page = memory.get("wiki", {}).get(title)
        return page["content"] if page else ""

    def get_wiki_pages(self, user_id: str) -> list:
        """List all wiki pages."""
        memory = self.load_memory(user_id)
        return list(memory.get("wiki", {}).keys())

    def get_preferences(self, user_id: str) -> dict:
        """Get user preferences stored in memory."""
        memory = self.load_memory(user_id)
        return memory.get("preferences", {})

    def set_preference(self, user_id: str, key: str, value):
        """Set a single user preference."""
        memory = self.load_memory(user_id)
        if "preferences" not in memory or not isinstance(memory["preferences"], dict):
            memory["preferences"] = {}
        memory["preferences"][key] = value
        self.save_memory(user_id, memory)
        return memory

    # Search

    def index_memory(self, user_id: str) -> int:
        """Index facts, wiki pages, and sessions for local SQLite recall."""
        with closing(sqlite3.connect(self.search_db_path)) as conn:
            conn.execute("DELETE FROM memory_search WHERE user_id = ?", (user_id,))
            conn.commit()

        indexed = 0
        memory = self.load_memory(user_id)

        for index, fact in enumerate(memory.get("facts", []), start=1):
            text = self._coerce_text(fact.get("text") if isinstance(fact, dict) else fact)
            if not text.strip():
                continue
            metadata = {
                "timestamp": fact.get("timestamp") if isinstance(fact, dict) else None,
            }
            self._index_search_document(user_id, "fact", f"fact:{index}", text, metadata)
            indexed += 1

        for title, page in memory.get("wiki", {}).items():
            content = self._coerce_text(page.get("content") if isinstance(page, dict) else page)
            text = f"{title}\n{content}".strip()
            if not text:
                continue
            metadata = {
                "title": str(title),
                "updated": page.get("updated") if isinstance(page, dict) else None,
            }
            self._index_search_document(user_id, "wiki", f"wiki:{title}", text, metadata)
            indexed += 1

        for session in self.list_sessions(user_id):
            indexed += self.index_session(user_id, session["session_id"])

        return indexed

    def index_session(self, user_id: str, session_id: str) -> int:
        """Index one JSON session into the local SQLite recall index."""
        session_prefix = f"session:{session_id}:"
        with closing(sqlite3.connect(self.search_db_path)) as conn:
            conn.execute(
                "DELETE FROM memory_search WHERE user_id = ? AND source LIKE ?",
                (user_id, f"{session_prefix}%"),
            )
            conn.commit()

        indexed = 0
        for message_index, message in enumerate(self.load_session(user_id, session_id)):
            text = self._message_text(message)
            if not text.strip():
                continue
            metadata = {
                "session_id": session_id,
                "message_index": message_index,
                "role": message.get("role") if isinstance(message, dict) else None,
            }
            self._index_search_document(
                user_id,
                "session",
                f"{session_prefix}{message_index}",
                text,
                metadata,
            )
            indexed += 1

        return indexed

    def search_memory(self, user_id: str, query: str, limit: int = 20) -> list:
        """Search the local SQLite recall index and return ranked documents."""
        normalized = (query or "").strip()
        if not normalized:
            return []

        terms = self._search_terms(normalized)
        if not terms:
            return []

        with closing(sqlite3.connect(self.search_db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conditions = " OR ".join("LOWER(text) LIKE ?" for _ in terms)
            rows = conn.execute(
                f"""
                SELECT type, source, text, metadata_json, updated_at
                FROM memory_search
                WHERE user_id = ? AND ({conditions})
                """,
                (user_id, *(f"%{term}%" for term in terms)),
            ).fetchall()

        results = []
        for row in rows:
            text = self._redact_secrets(row["text"])
            score = self._score_search_result(row["text"], normalized, terms)
            metadata = json.loads(row["metadata_json"] or "{}")
            result = {
                "type": row["type"],
                "source": row["source"],
                "text": text,
                "score": score,
                "updated_at": row["updated_at"],
            }
            if metadata:
                result["metadata"] = metadata
            results.append(result)

        results.sort(key=lambda item: (-item["score"], item["type"], item["source"]))
        return results[:limit]

    def search(self, user_id: str, query: str, limit: int = 20) -> list:
        """Search facts, wiki pages, and sessions for a user.

        Returns lightweight result dictionaries with redacted snippets so local
        search can be surfaced safely in CLI, dashboard, or MCP callers.
        """
        normalized = (query or "").strip().lower()
        if not normalized:
            return []

        results = []
        memory = self.load_memory(user_id)

        for index, fact in enumerate(memory.get("facts", [])):
            text = self._coerce_text(fact.get("text") if isinstance(fact, dict) else fact)
            if self._matches(text, normalized):
                results.append({
                    "type": "fact",
                    "title": f"Fact {index + 1}",
                    "snippet": self._snippet(text, normalized),
                    "timestamp": fact.get("timestamp") if isinstance(fact, dict) else None,
                })

        for title, page in memory.get("wiki", {}).items():
            content = self._coerce_text(page.get("content") if isinstance(page, dict) else page)
            if self._matches(f"{title}\n{content}", normalized):
                results.append({
                    "type": "wiki",
                    "title": self._redact_secrets(str(title)),
                    "snippet": self._snippet(content or str(title), normalized),
                    "updated": page.get("updated") if isinstance(page, dict) else None,
                })

        for session in self.list_sessions(user_id):
            session_id = session["session_id"]
            messages = self.load_session(user_id, session_id)
            for message_index, message in enumerate(messages):
                text = self._message_text(message)
                if not self._matches(text, normalized):
                    continue
                results.append({
                    "type": "session",
                    "title": f"Session {self._redact_secrets(session_id)}",
                    "session_id": session_id,
                    "message_index": message_index,
                    "snippet": self._snippet(text, normalized),
                    "updated": session.get("updated"),
                })
                break

        return results[:limit]

    def _matches(self, text: str, normalized_query: str) -> bool:
        return normalized_query in text.lower()

    def _snippet(self, text: str, normalized_query: str, radius: int = 80) -> str:
        clean_text = " ".join(self._coerce_text(text).split())
        lower_text = clean_text.lower()
        index = lower_text.find(normalized_query)
        if index < 0:
            snippet = clean_text[: radius * 2]
        else:
            start = max(index - radius, 0)
            end = min(index + len(normalized_query) + radius, len(clean_text))
            snippet = clean_text[start:end]
            if start:
                snippet = "..." + snippet
            if end < len(clean_text):
                snippet = snippet + "..."
        return self._redact_secrets(snippet)

    def _message_text(self, message) -> str:
        if isinstance(message, dict):
            role = self._coerce_text(message.get("role"))
            content = self._coerce_text(message.get("content"))
            return f"{role}: {content}" if role else content
        return self._coerce_text(message)

    def _coerce_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)

    def _redact_secrets(self, text: str) -> str:
        redacted = text
        redacted = self._SECRET_PATTERNS[0].sub("[redacted]", redacted)
        for pattern in self._SECRET_PATTERNS[1:]:
            redacted = pattern.sub(lambda match: match.group(0).replace(match.group(1), "[redacted]"), redacted)
        return redacted

    def _init_search_index(self):
        with closing(sqlite3.connect(self.search_db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_search (
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, source)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_search_user_type
                ON memory_search (user_id, type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_search_source
                ON memory_search (source)
            """)
            conn.commit()

    def _index_search_document(
        self,
        user_id: str,
        document_type: str,
        source: str,
        text: str,
        metadata: dict | None = None,
    ):
        with closing(sqlite3.connect(self.search_db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_search
                    (user_id, type, source, text, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    document_type,
                    source,
                    text,
                    json.dumps(metadata or {}, sort_keys=True),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def _search_terms(self, query: str) -> list[str]:
        return [term.lower() for term in re.findall(r"[A-Za-z0-9_]+", query)]

    def _score_search_result(self, text: str, query: str, terms: list[str]) -> int:
        lower_text = text.lower()
        lower_query = query.lower()
        score = 0
        if lower_query in lower_text:
            score += 10
        for term in terms:
            score += lower_text.count(term)
        return score

class SessionDB:
    """SQLite database for cross-session analytics and stats."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    message_count INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    user_id TEXT,
                    installed_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def record_session(self, user_id: str, session_id: str):
        """Record a new session."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (user_id, session_id, started_at) VALUES (?, ?, ?)",
                (user_id, session_id, datetime.now().isoformat())
            )
            conn.commit()

    def update_session(self, session_id: str, message_count: int, tokens_used: int, cost: float):
        """Update session stats."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE sessions SET message_count = ?, tokens_used = ?, cost = ?, ended_at = ? WHERE session_id = ?",
                (message_count, tokens_used, cost, datetime.now().isoformat(), session_id)
            )
            conn.commit()

    def get_stats(self) -> dict:
        """Get usage statistics."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(tokens_used) FROM sessions")
            total_tokens = cursor.fetchone()[0] or 0

            cursor.execute("SELECT SUM(cost) FROM sessions")
            total_cost = cursor.fetchone()[0] or 0.0

            return {
                "total_sessions": total_sessions,
                "total_tokens": int(total_tokens),
                "total_cost": round(total_cost, 2),
            }
