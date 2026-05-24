"""Shaka terminal UI.

The old implementation mixed a lot of decorative effects with a broken
event loop. This version keeps the cyberpunk inspiration but focuses on
being usable: clear layout, readable state, working commands, and a real
chat loop.
"""

from __future__ import annotations

import math
import json
import os
import platform
import random
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from .logo_ascii import LOGO as ASCII_LOGO
from .code_workflow import RepoContextBuilder

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style as PTStyle

    PROMPT_TOOLKIT_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    PromptSession = None  # type: ignore
    AutoSuggestFromHistory = None  # type: ignore
    HTML = None  # type: ignore
    InMemoryHistory = None  # type: ignore
    PTStyle = None  # type: ignore
    PROMPT_TOOLKIT_AVAILABLE = False


console = Console()

VERSION = "0.1.0"
ACTIVE_GREEN = "#00FF8A"
GREEN = "#00C46A"
DIM_GREEN = "#0A5C35"
CYAN = "#4BE3FF"
AMBER = "#F6C358"
MAGENTA = "#FF5CE1"
WHITE = "#E6FFF4"
BLACK = "#000000"

TAB_LABELS = ("SUMMARY", "FIXED", "BOOT", "REVIEW", "MORE+")


def _bar(percent: float, width: int = 18, fill: str = "=", empty: str = ".") -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(round((percent / 100.0) * width))
    return fill * filled + empty * (width - filled)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _command_parts(command: str) -> list[str]:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    return [part.strip("\"'") for part in parts]


def _split_code_blocks(content: str) -> List[Tuple[str, bool, str]]:
    """Return a list of (segment, is_code, language)."""
    pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    last_end = 0
    parts: List[Tuple[str, bool, str]] = []

    for match in pattern.finditer(content):
        if match.start() > last_end:
            plain = content[last_end:match.start()].strip()
            if plain:
                parts.append((plain, False, ""))

        language = match.group(1) or "text"
        code = match.group(2).strip()
        parts.append((code, True, language))
        last_end = match.end()

    if last_end < len(content):
        tail = content[last_end:].strip()
        if tail:
            parts.append((tail, False, ""))

    return parts or [(content, False, "")]


def _detect_language(code: str) -> str:
    sample = code.lower()
    if "def " in sample or "class " in sample or "import " in sample:
        return "python"
    if "function " in sample or "const " in sample or "let " in sample:
        return "javascript"
    if "package " in sample or "func " in sample:
        return "go"
    if "fn " in sample or "let mut" in sample:
        return "rust"
    if "<html" in sample or "<!doctype" in sample:
        return "html"
    return "text"


def _render_code_or_text(content: str, style: str) -> RenderableType:
    parts = _split_code_blocks(content)
    if len(parts) == 1 and not parts[0][1]:
        return Text(parts[0][0], style=style)

    blocks: List[RenderableType] = []
    for segment, is_code, language in parts:
        if is_code:
            lang = language or _detect_language(segment)
            blocks.append(
                Syntax(
                    segment,
                    lang,
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=True,
                )
            )
        else:
            blocks.append(Text(segment, style=style))
    return Group(*blocks)


def _bios_wrap(text: str, width: int) -> List[str]:
    words = text.split()
    if not words:
        return [""]

    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class ShakaTUI:
    """Cyberpunk-style, but functional, terminal UI for Shaka."""

    def __init__(self, agent, config):
        self.agent = agent
        self.config = config
        self.session_id = f"s_{int(time.time())}"
        self.mode = "SUMMARY"
        self.history: List[Tuple[str, str]] = []
        self.start_time = time.time()
        self.last_frame_time = 0.0
        self.frame = 0
        self._frame_count = 0
        self.running = True
        self._booted = False
        self._show_startup = True
        self._last_system_update = 0.0
        self.system_info = self._get_system_info()
        self.input_buffer = ""
        self.command_history: List[str] = []
        self._history_index = 0
        self._flash = False
        self._prompt_session = None
        self._prompt_history = None
        self._prompt_style = None
        self.last_review = None

    # ------------------------------------------------------------------
    # Compatibility helpers for older tests and scripts
    # ------------------------------------------------------------------

    def banner(self):
        return self.render_boot_screen()

    def build_layout(self):
        return self.render_screen()

    def cmd_help(self):
        return self.render_help_panel()

    def cmd_skills(self):
        return self.render_skills_panel()

    def cmd_memory(self):
        return self.render_memory_panel()

    def cmd_clear(self):
        self.history.clear()
        self.session_id = f"s_{int(time.time())}"
        self.input_buffer = ""
        self.command_history.clear()
        self._history_index = 0
        return Panel("Conversation cleared.", border_style=ACTIVE_GREEN, box=box.SQUARE)

    def cmd_stats(self):
        return self.render_status_panel()

    def cmd_language(self):
        return Panel(
            f"Language: {getattr(self.config, 'language', 'en')}",
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
        )

    def cmd_personality(self):
        preferences = {}
        try:
            memory = getattr(self.agent, "memory", None)
            user_id = getattr(self.agent, "user_id", "default")
            if memory is not None:
                preferences = memory.get_preferences(user_id)
        except Exception:
            preferences = {}
        personality_cfg = getattr(self.config, "personality", {}) or {}
        presets = personality_cfg.get("presets", {}) if isinstance(personality_cfg, dict) else {}
        current_preset = preferences.get("personality_preset", "(not set)")
        current = preferences.get("personality_custom") or preferences.get("personality", "(not set)")
        return Panel(
            Group(
                Text("PERSONALITY", style=f"bold {ACTIVE_GREEN}"),
                Text(""),
                Text(f"Preset: {current_preset}", style=WHITE),
                Text(f"Current: {current}", style=WHITE),
                Text(""),
                Text("Use /personality preset <name> or /personality <text>.", style="dim"),
                Text("Available presets:", style="dim"),
                *[Text(f"  - {name}: {desc}", style="dim") for name, desc in list(presets.items())[:5]],
            ),
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
        )

    def render_startup_animation(self):
        if self._frame_count > 30:
            self._show_startup = False
        return self.render_boot_screen()

    def render_header(self):
        return self.render_top_bar()

    def render_chat(self):
        return self.render_conversation()

    def render_status(self):
        return self.render_status_panel()

    def render_memory(self):
        return self.render_memory_panel()

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_system_info(self) -> dict:
        try:
            if psutil is not None:
                cpu = psutil.cpu_percent(interval=0.05)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage(os.getcwd())
                uptime = max(0, time.time() - psutil.boot_time())
                hours, remainder = divmod(int(uptime), 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                return {
                    "cpu": cpu,
                    "memory": mem.percent,
                    "disk": disk.percent,
                    "uptime": uptime_str,
                    "platform": f"{platform.system()} {platform.release()}",
                }
        except Exception:
            pass

        return {
            "cpu": 0.0,
            "memory": 0.0,
            "disk": 0.0,
            "uptime": "N/A",
            "platform": platform.platform(),
        }

    def _refresh_system_info(self) -> None:
        if time.time() - self._last_system_update > 3.0:
            self.system_info = self._get_system_info()
            self._last_system_update = time.time()

    def _greeting(self) -> str:
        hour = time.localtime().tm_hour
        if 5 <= hour < 12:
            return "GOOD MORNING"
        if 12 <= hour < 18:
            return "GOOD AFTERNOON"
        return "GOOD EVENING"

    def _available_skills(self) -> List[dict]:
        registry = getattr(self.agent, "skills_registry", None)
        if registry is None:
            return []
        try:
            return registry.list_skills()
        except Exception:
            return []

    def _memory_snapshot(self) -> dict:
        memory = getattr(self.agent, "memory", None)
        user_id = getattr(self.agent, "user_id", "default")
        if memory is None:
            return {"facts": [], "wiki": [], "sessions": []}
        try:
            loaded = memory.load_memory(user_id)
        except Exception:
            loaded = {}
        facts = loaded.get("facts", []) if isinstance(loaded, dict) else []
        wiki = []
        sessions = []
        try:
            wiki = memory.get_wiki_pages(user_id)
        except Exception:
            pass
        try:
            sessions = memory.list_sessions(user_id)
        except Exception:
            pass
        return {"facts": facts, "wiki": wiki, "sessions": sessions}

    def _onboarding_state(self) -> tuple[bool, dict]:
        memory = getattr(self.agent, "memory", None)
        user_id = getattr(self.agent, "user_id", "default")
        if memory is None:
            return False, {}
        try:
            prefs = memory.get_preferences(user_id)
        except Exception:
            prefs = {}
        return bool(prefs.get("onboarding_completed")), prefs

    def _automation_store(self):
        from .automation import TaskStore

        return TaskStore(self.config.paths.base_dir)

    def _task_status_style(self, status: str) -> str:
        if status in {"completed", "approved", "used"}:
            return f"bold {ACTIVE_GREEN}"
        if status in {"failed", "cancelled", "rejected"}:
            return f"bold {AMBER}"
        if status in {"running", "waiting_for_approval"}:
            return f"bold {CYAN}"
        return WHITE

    def _risk_style(self, risk: str) -> str:
        if risk in {"destructive", "external_send", "risky_write"}:
            return f"bold {AMBER}"
        if risk in {"safe_read", "safe"}:
            return f"bold {ACTIVE_GREEN}"
        return WHITE

    def _meter_table(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_row(
            f"[dim]CPU[/] {_bar(self.system_info['cpu'])} [bold]{self.system_info['cpu']:.0f}%[/]",
            f"[dim]MEM[/] {_bar(self.system_info['memory'])} [bold]{self.system_info['memory']:.0f}%[/]",
            f"[dim]DSK[/] {_bar(self.system_info['disk'])} [bold]{self.system_info['disk']:.0f}%[/]",
        )
        return table

    def _mode_body(self) -> RenderableType:
        if self.mode == "FIXED":
            return self.render_memory_panel()
        if self.mode == "BOOT":
            return self.render_boot_panel()
        if self.mode == "REVIEW":
            return self.render_review_panel()
        if self.mode == "SEQ":
            return self.render_sequence_panel()
        if self.mode == "MORE+":
            return self.render_help_panel()
        return self.render_summary_panel()

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def render_boot_screen(self) -> Panel:
        body = Text()
        body.append("SHAKA BIOS INITIALIZATION\n", style=f"bold {ACTIVE_GREEN}")
        body.append(f"{self._greeting()}  {getattr(self.config, 'name', 'Shaka')}\n", style=WHITE)
        body.append(f"version {VERSION}    session {self.session_id}\n", style="dim")
        body.append(f"provider {self.config.model.provider}    model {self.config.model.model}\n", style="dim")
        body.append("\nBOOT SEQUENCE\n", style=f"bold {CYAN}")
        body.append("01 power rail check .......... OK\n", style=WHITE)
        body.append("02 local memory mount ........ OK\n", style=WHITE)
        body.append("03 skill registry ............ OK\n", style=WHITE)
        body.append("04 terminal renderer ......... ONLINE\n", style=WHITE)
        return Panel(
            Align.center(body, vertical="middle"),
            border_style=ACTIVE_GREEN,
            box=box.DOUBLE,
            padding=(1, 2),
            title="[bold green]BOOT[/]",
        )

    def render_top_bar(self) -> Panel:
        top = Table.grid(expand=True)
        top.add_column(ratio=2)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_column(ratio=1)
        top.add_row(
            f"[bold {ACTIVE_GREEN}]MR BIOS (TM)[/]  [dim]{getattr(self.config, 'name', 'SHAKA')} CONTROL SURFACE[/]",
            f"[dim]VER[/] {VERSION}",
            f"[dim]PORT[/] 3",
            f"[dim]SESSION[/] {self.session_id}",
        )
        return Panel(top, box=box.SQUARE, border_style=DIM_GREEN, padding=(0, 1))

    def render_tabs(self) -> Panel:
        table = Table.grid(expand=True)
        for _ in TAB_LABELS:
            table.add_column(justify="center")

        cells = []
        for label in TAB_LABELS:
            if label == self.mode:
                cells.append(f"[bold {ACTIVE_GREEN}]{label}[/]")
            else:
                cells.append(f"[dim]{label}[/]")
        table.add_row(*cells)

        return Panel(table, box=box.SQUARE, border_style=ACTIVE_GREEN, padding=(0, 1))

    def render_conversation(self, max_messages: int = 8) -> Panel:
        if not self.history:
            intro = Group(
                Text("SUMMARY", style=f"bold {ACTIVE_GREEN}"),
                Text(""),
                Text("[01] READY  [02] WAITING FOR INPUT  [03] MEMORY LINK: LOCAL", style=WHITE),
                Text("[04] TYPE A MESSAGE AND PRESS ENTER.", style=WHITE),
                Text(""),
                Text("COMMANDS", style=f"bold {CYAN}"),
                Text("/help  /tasks  /approvals  /task <id>  /web-verify <url>  /exit", style=WHITE),
            )
            return Panel(
                Align.center(intro, vertical="middle"),
                border_style=ACTIVE_GREEN,
                box=box.DOUBLE,
                title="[bold green]SUMMARY[/]",
                padding=(1, 2),
            )

        transcript = Table.grid(expand=True)
        transcript.add_column(ratio=1)
        visible_history = self.history[-max_messages:]
        hidden_count = max(0, len(self.history) - len(visible_history))
        if hidden_count:
            transcript.add_row(Text(f"... {hidden_count} earlier messages hidden ...", style="dim"))

        for idx, (role, content) in enumerate(visible_history, start=max(1, len(self.history) - len(visible_history) + 1)):
            prefix = "[USER]" if role == "user" else "[SHAKA]"
            line = Text()
            line.append(f"{idx:02d} {prefix:<7} ", style=f"bold {CYAN if role == 'user' else ACTIVE_GREEN}")
            text = _truncate(content.replace("\n", " ").strip(), 96)
            line.append(text, style="white" if role == "user" else CYAN)
            transcript.add_row(line)
        return Panel(
            transcript,
            border_style=ACTIVE_GREEN,
            box=box.DOUBLE,
            title="[bold green]CONVERSATION[/]",
            padding=(1, 1),
        )

    def render_waveform(self, width: int = 42, height: int = 16) -> Panel:
        grid = [[" " for _ in range(width)] for _ in range(height)]
        phase = self.frame / 4.0

        for x in range(width):
            pos = (x / max(1, width - 1)) * math.tau * 1.25 + phase
            amplitude = (
                math.sin(pos) * 0.5
                + math.sin(pos * 2.1 + 1.2) * 0.22
                + math.sin(pos * 3.7 + 0.5) * 0.1
            )
            level = int(round(((amplitude + 1.0) / 2.0) * (height - 3))) + 1
            level = max(1, min(height - 1, level))
            for y in range(height - 1, height - 1 - level, -1):
                grid[y][x] = "#"

            crest = height - level - 1
            if 0 <= crest < height:
                grid[crest][x] = "/" if x % 2 == 0 else "\\"

            if x % 7 == 0:
                for y in range(height):
                    if grid[y][x] == " " and y < height - 2:
                        grid[y][x] = "|"

        lines = ["".join(row) for row in grid]
        art = Text("\n".join(lines), style=f"bold {ACTIVE_GREEN}")
        return Panel(
            Align.center(art),
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]SEQ[/]",
            padding=(0, 1),
        )

    def render_status_panel(self) -> Panel:
        system = self.system_info
        status = Table.grid(expand=True)
        status.add_column(justify="left")
        status.add_column(justify="right")
        status.add_row("[bold green]SESSION[/]", self.session_id)
        status.add_row("[dim]mode[/]", self.mode)
        status.add_row("[dim]provider[/]", self.config.model.provider)
        status.add_row("[dim]model[/]", _truncate(self.config.model.model, 24))
        status.add_row("[dim]language[/]", getattr(self.config, "language", "en"))
        status.add_row("[dim]elapsed[/]", f"{time.time() - self.start_time:.1f}s")
        status.add_row("[dim]tokens[/]", str(getattr(self.agent, "total_tokens", 0)))
        status.add_row("[dim]tools[/]", str(sum(1 for _ in self.history if _[0] == "tool")))
        status.add_row("[dim]uptime[/]", system["uptime"])
        status.add_row("[dim]platform[/]", _truncate(system["platform"], 24))
        status.add_row("[dim]CPU[/]", f"{system['cpu']:.0f}%")
        status.add_row("[dim]MEM[/]", f"{system['memory']:.0f}%")
        return Panel(
            Group(status, Rule(style=DIM_GREEN), self._meter_table()),
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]STATUS[/]",
            padding=(1, 1),
        )

    def render_summary_panel(self) -> Panel:
        skills = self._available_skills()
        snapshot = self._memory_snapshot()
        facts = snapshot["facts"][-3:]
        onboarding_complete, _ = self._onboarding_state()

        summary = Table.grid(expand=True)
        summary.add_column()
        summary.add_row(Text("SHAKA MANIFEST", style=f"bold {ACTIVE_GREEN}"))
        summary.add_row(Text(f"Session: {self.session_id}", style=WHITE))
        summary.add_row(Text(f"Mode: {self.mode}  Provider: {self.config.model.provider}", style=WHITE))
        summary.add_row(Text(f"Model: {self.config.model.model}", style=WHITE))
        summary.add_row(Text(f"Tokens: {getattr(self.agent, 'total_tokens', 0)}  Elapsed: {time.time() - self.start_time:.1f}s", style=WHITE))
        summary.add_row(Text(f"Skills: {len(skills)}  Wiki: {len(snapshot['wiki'])}  Facts: {len(snapshot['facts'])}", style=WHITE))
        summary.add_row(Text("", style=""))
        summary.add_row(Text("LATEST FACTS", style=f"bold {CYAN}"))
        if facts:
            for fact in facts:
                value = fact.get("text", str(fact)) if isinstance(fact, dict) else str(fact)
                summary.add_row(Text(f"- {_truncate(value, 42)}", style=WHITE))
        else:
            summary.add_row(Text("No facts stored.", style="dim"))
        summary.add_row(Text("", style=""))
        summary.add_row(Text("RECENT", style=f"bold {MAGENTA}"))
        for role, content in self.history[-4:]:
            tag = "U" if role == "user" else "S"
            summary.add_row(Text(f"[{tag}] {_truncate(content.replace(chr(10), ' '), 42)}", style=WHITE))

        if self.last_review:
            summary.add_row(Text("", style=""))
            summary.add_row(Text("LAST REVIEW", style=f"bold {CYAN}"))
            review_summary = self.last_review.get("summary", "")
            if review_summary:
                summary.add_row(Text(_truncate(review_summary, 42), style=WHITE))
            findings = self.last_review.get("findings", []) or []
            summary.add_row(Text(f"Findings: {len(findings)}", style=WHITE))

        if not self.history and not onboarding_complete:
            summary.add_row(Text("", style=""))
            summary.add_row(Text("ONBOARDING", style=f"bold {GREEN}"))
            summary.add_row(Text("Run /onboard for a setup checklist.", style=WHITE))
            summary.add_row(Text("Set a personality with /personality --preset technical.", style=WHITE))

        return Panel(
            Group(
                Text(ASCII_LOGO, style=DIM_GREEN),
                Rule(style=DIM_GREEN),
                summary,
            ),
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]SUMMARY[/]",
            padding=(1, 1),
        )

    def render_input_panel(self) -> Panel:
        cursor = "_" if self._flash else " "
        visible = _truncate(self.input_buffer, 64)
        line = Text()
        line.append("Shaka>", style=f"bold {ACTIVE_GREEN}")
        line.append(cursor, style=f"bold {CYAN}")
        line.append(" ", style="dim")
        line.append(visible or "", style=WHITE)
        helper = Text()
        helper.append("/help /tasks /task /approvals /approve /reject /retry /web-verify /exit", style=f"bold {CYAN}")
        helper.append("  ", style="dim")
        helper.append(f"[{len(self.command_history)} history]", style="dim")
        history_preview = Text()
        recent = self.command_history[-3:]
        if recent:
            history_preview.append("recent: ", style="dim")
            history_preview.append(" | ".join(_truncate(cmd, 18) for cmd in recent), style=WHITE)
        return Panel(
            Group(line, Text(""), helper, Text(""), history_preview),
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]INPUT[/]",
            padding=(0, 1),
        )

    def render_tasks_panel(self, limit: int = 10) -> Panel:
        try:
            store = self._automation_store()
            tasks = store.list_tasks()[:limit]
        except Exception as exc:
            return Panel(f"Could not load tasks: {exc}", border_style=AMBER, box=box.SQUARE)

        if not tasks:
            body = Group(
                Text("No automation tasks yet.", style="dim"),
                Text("Hint: /build-site <path> <prompt> or /web-verify <url>", style=CYAN),
            )
            return Panel(body, title="[bold green]TASKS[/]", border_style=ACTIVE_GREEN, box=box.SQUARE)

        table = Table(expand=True, box=box.SIMPLE, show_header=True, header_style=f"bold {CYAN}")
        table.add_column("ID", no_wrap=True)
        table.add_column("STATUS", no_wrap=True)
        table.add_column("KIND", no_wrap=True)
        table.add_column("SUMMARY")
        table.add_column("NEXT")
        for task in tasks:
            task_id = str(task.get("id", ""))
            status = str(task.get("status", ""))
            summary = task.get("summary") or task.get("error") or task.get("title", "")
            next_hint = f"/task {task_id}"
            if status in {"failed", "cancelled"}:
                next_hint = f"/retry {task_id}"
            if status == "waiting_for_approval":
                next_hint = "/approvals"
            table.add_row(
                task_id,
                Text(status, style=self._task_status_style(status)),
                str(task.get("kind", "")),
                _truncate(str(summary), 72),
                next_hint,
            )
        return Panel(table, title="[bold green]TASKS[/]", border_style=ACTIVE_GREEN, box=box.SQUARE, padding=(1, 1))

    def render_task_detail_panel(self, task_id: str) -> Panel:
        try:
            store = self._automation_store()
            task = store.get_task(task_id)
            if not task:
                return Panel(f"Unknown task: {task_id}", border_style=AMBER, box=box.SQUARE)
            steps = store.get_task_steps(task_id)[-8:]
        except Exception as exc:
            return Panel(f"Could not load task: {exc}", border_style=AMBER, box=box.SQUARE)

        status = str(task.get("status", ""))
        rows = Table.grid(expand=True)
        rows.add_column(ratio=1)
        rows.add_row(Text(f"ID: {task.get('id', '')}", style=WHITE))
        rows.add_row(Text(f"Status: {status}", style=self._task_status_style(status)))
        rows.add_row(Text(f"Kind: {task.get('kind', '')}", style=WHITE))
        rows.add_row(Text(f"Title: {task.get('title', '')}", style=WHITE))
        summary = task.get("summary") or task.get("error") or "(no summary yet)"
        rows.add_row(Text(f"Summary: {summary}", style=WHITE))
        rows.add_row(Text("", style=""))
        rows.add_row(Text("STEPS", style=f"bold {CYAN}"))
        if steps:
            for step in steps:
                rows.add_row(Text(f"- {step.get('kind', 'log')}: {step.get('message', '')}", style=WHITE))
        else:
            rows.add_row(Text("No task steps recorded.", style="dim"))
        rows.add_row(Text("", style=""))
        hint = f"/task {task_id}"
        if status in {"failed", "cancelled"}:
            hint = f"/retry {task_id}"
        elif status == "waiting_for_approval":
            hint = "/approvals"
        rows.add_row(Text(f"Next: {hint}", style=CYAN))
        return Panel(rows, title="[bold green]TASK DETAIL[/]", border_style=ACTIVE_GREEN, box=box.SQUARE, padding=(1, 1))

    def render_approvals_panel(self, limit: int = 10) -> Panel:
        try:
            approvals = self._automation_store().list_approvals(status="pending")[:limit]
        except Exception as exc:
            return Panel(f"Could not load approvals: {exc}", border_style=AMBER, box=box.SQUARE)

        if not approvals:
            body = Group(
                Text("No pending approvals.", style="dim"),
                Text("Hint: /tasks shows automation task state.", style=CYAN),
            )
            return Panel(body, title="[bold green]APPROVALS[/]", border_style=ACTIVE_GREEN, box=box.SQUARE)

        table = Table(expand=True, box=box.SIMPLE, show_header=True, header_style=f"bold {CYAN}")
        table.add_column("ID", no_wrap=True)
        table.add_column("RISK", no_wrap=True)
        table.add_column("TASK", no_wrap=True)
        table.add_column("SUMMARY")
        table.add_column("NEXT")
        for approval in approvals:
            approval_id = str(approval.get("id", ""))
            risk = str(approval.get("risk", ""))
            table.add_row(
                approval_id,
                Text(risk, style=self._risk_style(risk)),
                str(approval.get("task_id", "")),
                _truncate(str(approval.get("summary", "")), 72),
                f"/approve {approval_id} | /reject {approval_id} <reason>",
            )
        return Panel(table, title="[bold green]APPROVALS[/]", border_style=ACTIVE_GREEN, box=box.SQUARE, padding=(1, 1))

    def render_repo_memory_panel(self, repo_path: str | None = None) -> Panel:
        try:
            from .repo_memory import RepoMemory

            target = repo_path or "."
            memory = RepoMemory(self.config.paths.base_dir).load(target)
        except Exception as exc:
            return Panel(f"Could not load repo memory: {exc}", border_style=AMBER, box=box.SQUARE)

        rows = Table.grid(expand=True)
        rows.add_column()
        rows.add_row(Text(f"Repo: {memory.get('repo_path', '')}", style=WHITE))
        rows.add_row(Text(f"Summary: {memory.get('summary') or '(none)'}", style=WHITE))
        rows.add_row(Text("", style=""))
        rows.add_row(Text("COMMANDS", style=f"bold {CYAN}"))
        for item in (memory.get("commands") or [])[-5:]:
            rows.add_row(Text(f"- {item.get('command', '')}: {item.get('result', '')}", style=WHITE))
        if not memory.get("commands"):
            rows.add_row(Text("No command memory.", style="dim"))
        rows.add_row(Text("", style=""))
        rows.add_row(Text("DECISIONS", style=f"bold {MAGENTA}"))
        for decision in (memory.get("decisions") or [])[-5:]:
            rows.add_row(Text(f"- {decision}", style=WHITE))
        if not memory.get("decisions"):
            rows.add_row(Text("No decisions recorded.", style="dim"))
        return Panel(rows, title="[bold green]REPO MEMORY[/]", border_style=ACTIVE_GREEN, box=box.SQUARE, padding=(1, 1))

    def render_memory_panel(self) -> Panel:
        snapshot = self._memory_snapshot()
        facts = snapshot["facts"][-4:]
        wiki = snapshot["wiki"][-4:]
        sessions = snapshot["sessions"][:3]

        body = Table.grid(expand=True)
        body.add_column(ratio=1)
        body.add_row(Text("MEMORY", style=f"bold {ACTIVE_GREEN}"))
        if facts:
            for fact in facts:
                value = fact.get("text", str(fact)) if isinstance(fact, dict) else str(fact)
                body.add_row(Text(f"- {_truncate(value, 48)}", style=WHITE))
        else:
            body.add_row(Text("No facts stored.", style="dim"))

        body.add_row(Text("", style=""))
        body.add_row(Text("WIKI", style=f"bold {CYAN}"))
        if wiki:
            for page in wiki:
                body.add_row(Text(f"- {page}", style=WHITE))
        else:
            body.add_row(Text("No wiki pages.", style="dim"))

        body.add_row(Text("", style=""))
        body.add_row(Text("SESSIONS", style=f"bold {MAGENTA}"))
        if sessions:
            for session in sessions:
                body.add_row(Text(f"- {session.get('session_id', '')}", style=WHITE))
        else:
            body.add_row(Text("No sessions yet.", style="dim"))

        return Panel(body, border_style=ACTIVE_GREEN, box=box.SQUARE, title="[bold green]FIXED[/]", padding=(1, 1))

    def render_review_panel(self) -> Panel:
        if not self.last_review:
            return Panel(
                Text("No review results yet. Use /review <task> to inspect a change.", style="dim"),
                border_style=ACTIVE_GREEN,
                box=box.SQUARE,
                title="[bold green]REVIEW[/]",
                padding=(1, 1),
            )

        findings = self.last_review.get("findings", []) or []
        body = Table.grid(expand=True)
        body.add_column()
        body.add_row(Text("REVIEW SUMMARY", style=f"bold {ACTIVE_GREEN}"))
        summary = self.last_review.get("summary", "")
        if summary:
            body.add_row(Text(_truncate(summary, 80), style=WHITE))
        if findings:
            body.add_row(Text("", style=""))
            body.add_row(Text("FINDINGS", style=f"bold {CYAN}"))
            for finding in findings[:6]:
                priority = finding.get("priority", "P2")
                location = finding.get("file", "")
                line = finding.get("line", "")
                body.add_row(
                    Text(
                        f"- [{priority}] {location}:{line} {finding.get('body', '')}",
                        style=WHITE,
                    )
                )
        else:
            body.add_row(Text("No findings.", style="dim"))
        return Panel(body, border_style=ACTIVE_GREEN, box=box.SQUARE, title="[bold green]REVIEW[/]", padding=(1, 1))

    def render_boot_panel(self) -> Panel:
        logs = Table.grid(expand=True)
        logs.add_column()
        entries = [
            "[dim]>[/] checking local config",
            "[dim]>[/] loading skills",
            "[dim]>[/] mounting memory",
            "[dim]>[/] calibrating neon renderer",
            "[dim]>[/] boot complete",
        ]
        for entry in entries:
            logs.add_row(Text(entry, style=WHITE))
        return Panel(
            logs,
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]BOOT[/]",
            padding=(1, 1),
        )

    def render_sequence_panel(self) -> Panel:
        sequence = Table.grid(expand=True)
        sequence.add_column()
        sequence.add_row(Text("MESSAGE SEQUENCE", style=f"bold {ACTIVE_GREEN}"))
        if not self.history:
            sequence.add_row(Text("No conversation sequence yet.", style="dim"))
        else:
            for idx, (role, content) in enumerate(self.history[-8:], start=1):
                prefix = "U" if role == "user" else "S"
                sequence.add_row(
                    Text(f"{idx:02d}. [{prefix}] {_truncate(content.replace(chr(10), ' '), 56)}", style=WHITE)
                )
        return Panel(
            sequence,
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]SEQ[/]",
            padding=(1, 1),
        )

    def render_help_panel(self) -> Panel:
        help_table = Table.grid(expand=True)
        help_table.add_column()
        rows = [
            ("/help", "show this panel"),
            ("/skills", "list loaded skills"),
            ("/memory", "show stored facts and wiki pages"),
            ("/stats", "show session stats"),
            ("/tasks", "show automation tasks"),
            ("/task <task_id>", "show task detail, summary, steps, and next action"),
            ("/approvals", "show pending approvals"),
            ("/approve <approval_id>", "approve a pending action"),
            ("/reject <approval_id> [reason]", "reject a pending action"),
            ("/retry <task_id>", "retry a failed or cancelled task"),
            ("/repo-memory [path]", "show repository-specific memory"),
            ("/web-verify <url>", "run web verification and record a task"),
            ("/build-site <path> <prompt>", "scaffold a website and record a task"),
            ("/onboard", "show the onboarding checklist"),
            ("/personality", "view or set personality"),
            ("/code <task>", "run the coding workflow"),
            ("/review <task>", "run a read-only code review"),
            ("/clear", "reset the visible conversation"),
            ("/mode summary|fixed|boot|review|seq|more+", "switch the active dashboard"),
            ("/exit", "quit Shaka"),
        ]
        for cmd, desc in rows:
            help_table.add_row(Text(f"{cmd:<34} {desc}", style=WHITE))
        return Panel(
            help_table,
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]MORE+[/]",
            padding=(1, 1),
        )

    def render_skills_panel(self) -> Panel:
        skills = self._available_skills()
        table = Table.grid(expand=True)
        table.add_column()
        table.add_row(Text("SKILLS", style=f"bold {ACTIVE_GREEN}"))
        if not skills:
            table.add_row(Text("No skills loaded.", style="dim"))
        else:
            for skill in skills:
                table.add_row(
                    Text(
                        f"- {skill['name']}: {_truncate(skill.get('description', ''), 50)}",
                        style=WHITE,
                    )
                )
        return Panel(
            table,
            border_style=ACTIVE_GREEN,
            box=box.SQUARE,
            title="[bold green]SKILLS[/]",
            padding=(1, 1),
        )

    def render_onboarding_panel(self) -> Panel:
        _, prefs = self._onboarding_state()
        done = bool(prefs.get("onboarding_completed"))
        personality = prefs.get("personality_preset") or prefs.get("personality_custom") or prefs.get("personality", "(not set)")

        body = Table.grid(expand=True)
        body.add_column()
        body.add_row(Text("ONBOARDING", style=f"bold {ACTIVE_GREEN}"))
        body.add_row(Text("1. Run `shaka doctor` to verify your setup.", style=WHITE))
        body.add_row(Text("2. Set a personality preset with /personality --preset technical.", style=WHITE))
        body.add_row(Text("3. Use /code for repo work and /review for code review.", style=WHITE))
        body.add_row(Text("4. Use /memory and /skills to inspect capabilities.", style=WHITE))
        body.add_row(Text("5. When ready, mark this as done with /onboard complete.", style=WHITE))
        body.add_row(Text("", style=""))
        body.add_row(Text(f"Completed: {'yes' if done else 'no'}", style=CYAN))
        body.add_row(Text(f"Personality: {personality}", style=WHITE))
        return Panel(body, border_style=ACTIVE_GREEN, box=box.SQUARE, title="[bold green]ONBOARD[/]", padding=(1, 1))

    def render_footer(self) -> Panel:
        bank = Table.grid(expand=True)
        bank.add_column(ratio=1)
        bank.add_column(ratio=1)
        bank.add_column(ratio=1)
        bank.add_row(
            Text("BANK 1  ACTIVE", style=f"bold {ACTIVE_GREEN}"),
            Text("BANK 2  ACTIVE", style=f"bold {ACTIVE_GREEN}"),
            Text("BANK 3  ACTIVE", style=f"bold {ACTIVE_GREEN}"),
        )

        brand = Text()
        brand.append("SHAKA", style=f"bold {ACTIVE_GREEN}")
        brand.append("  ", style="dim")
        brand.append("CONTROL SURFACE", style=f"bold {CYAN}")

        shortcuts = Text()
        shortcuts.append("ENTER", style=f"bold {ACTIVE_GREEN}")
        shortcuts.append(" send  ")
        shortcuts.append("/help", style=f"bold {CYAN}")
        shortcuts.append("  /tasks", style=f"bold {CYAN}")
        shortcuts.append("  /approvals", style=f"bold {CYAN}")
        shortcuts.append("  /approve", style=f"bold {CYAN}")
        shortcuts.append("  /reject", style=f"bold {CYAN}")
        shortcuts.append("  /exit", style=f"bold {CYAN}")
        return Panel(
            Group(bank, Text(""), Align.center(brand), Text(""), Align.center(shortcuts)),
            border_style=DIM_GREEN,
            box=box.SQUARE,
            padding=(0, 1),
        )

    def render_screen(self) -> Layout:
        self._refresh_system_info()
        self.frame += 1
        self._frame_count += 1
        console_size = console.size
        body_height = max(10, console_size.height - 11)
        max_messages = max(4, min(10, body_height - 6))

        layout = Layout(name="root")
        layout.split(
            Layout(self.render_top_bar(), name="top", size=3),
            Layout(self.render_tabs(), name="tabs", size=3),
            Layout(name="body", ratio=1),
            Layout(self.render_input_panel(), name="input", size=5),
        )
        layout["body"].split_row(
            Layout(self.render_conversation(max_messages=max_messages), name="left", ratio=3),
            Layout(self._mode_body(), name="right", ratio=1),
        )
        return layout

    # ------------------------------------------------------------------
    # Input / actions
    # ------------------------------------------------------------------

    def _print_panel(self, panel: Panel) -> None:
        console.clear()
        console.print(panel)

    def _show_command_output(self, renderable: RenderableType) -> None:
        console.print()
        console.print(renderable)
        console.print()

    def _normalize_input(self, value: str) -> str:
        return value.replace("\r", "").replace("\n", " ").strip()

    def _ensure_prompt_backend(self) -> bool:
        if self._prompt_session is not None or not PROMPT_TOOLKIT_AVAILABLE:
            return self._prompt_session is not None

        try:
            self._prompt_history = InMemoryHistory()
            self._prompt_session = PromptSession(
                history=self._prompt_history,
                auto_suggest=AutoSuggestFromHistory(),
                complete_while_typing=False,
            )
            self._prompt_style = PTStyle.from_dict(
                {
                    "default": "#E6FFF4",
                }
            )
            return True
        except Exception:
            self._prompt_session = None
            self._prompt_history = None
            self._prompt_style = None
            return False

    def _handle_history_navigation(self, key: str) -> bool:
        if not self.command_history:
            return False
        if key == "up":
            self._history_index = max(0, self._history_index - 1)
            self.input_buffer = self.command_history[self._history_index]
            return True
        if key == "down":
            self._history_index = min(len(self.command_history), self._history_index + 1)
            if self._history_index >= len(self.command_history):
                self.input_buffer = ""
            else:
                self.input_buffer = self.command_history[self._history_index]
            return True
        return False

    def _handle_command(self, text: str) -> bool:
        command = text.strip()
        lower = command.lower()

        if lower in {"exit", "quit", "q", "/exit"}:
            self.running = False
            return True

        if lower in {"/help", "help"}:
            self._show_command_output(self.render_help_panel())
            return True

        if lower in {"/skills", "skills"}:
            self._show_command_output(self.render_skills_panel())
            return True

        if lower in {"/memory", "memory"}:
            self._show_command_output(self.render_memory_panel())
            return True

        if lower in {"/stats", "stats"}:
            self._show_command_output(self.render_status_panel())
            return True

        if lower in {"/tasks", "tasks"}:
            self._show_command_output(self.render_tasks_panel())
            return True

        if lower in {"/approvals", "approvals"}:
            self._show_command_output(self.render_approvals_panel())
            return True

        if lower.startswith("/approve "):
            approval_id = command.split(" ", 1)[1].strip()
            try:
                approval = self._automation_store().approve(approval_id)
                self._show_command_output(
                    Panel(
                        f"Approved {approval['id']} for task {approval['task_id']}. Next: /task {approval['task_id']}",
                        border_style=ACTIVE_GREEN,
                        box=box.SQUARE,
                    )
                )
            except Exception as exc:
                self._show_command_output(Panel(f"Approval failed: {exc}", border_style=AMBER, box=box.SQUARE))
            return True

        if lower.startswith("/reject "):
            remainder = command.split(" ", 1)[1].strip()
            approval_id, _, reason = remainder.partition(" ")
            if not approval_id:
                self._show_command_output(Panel("Usage: /reject <approval_id> [reason]", border_style=AMBER, box=box.SQUARE))
                return True
            try:
                approval = self._automation_store().reject_approval(approval_id, reason=reason)
                self._show_command_output(
                    Panel(
                        f"Rejected {approval['id']} for task {approval['task_id']}. Next: /task {approval['task_id']}",
                        border_style=ACTIVE_GREEN,
                        box=box.SQUARE,
                    )
                )
            except Exception as exc:
                self._show_command_output(Panel(f"Reject failed: {exc}", border_style=AMBER, box=box.SQUARE))
            return True

        if lower.startswith("/retry "):
            task_id = command.split(" ", 1)[1].strip()
            try:
                task = self._automation_store().retry_task(task_id)
                self._show_command_output(
                    Panel(
                        f"Retried {task['id']} and moved it to {task['status']}. Next: /task {task['id']}",
                        border_style=ACTIVE_GREEN,
                        box=box.SQUARE,
                    )
                )
            except Exception as exc:
                self._show_command_output(Panel(f"Retry failed: {exc}", border_style=AMBER, box=box.SQUARE))
            return True

        if lower.startswith("/task "):
            task_id = command.split(" ", 1)[1].strip()
            self._show_command_output(self.render_task_detail_panel(task_id))
            return True

        if lower.startswith("/repo-memory"):
            parts = _command_parts(command)
            repo_path = parts[1] if len(parts) > 1 else "."
            self._show_command_output(self.render_repo_memory_panel(repo_path))
            return True

        if lower.startswith("/web-verify "):
            url = command.split(" ", 1)[1].strip()
            if not url:
                self._show_command_output(Panel("Usage: /web-verify <url>", border_style=AMBER, box=box.SQUARE))
                return True
            self._show_command_output(Panel("Verifying website...", border_style=DIM_GREEN, box=box.SQUARE))
            try:
                from .web_runtime import WebVerifier

                result = WebVerifier(self.config.paths.base_dir).verify(url, use_browser=False)
                status = "OK" if result.get("ok") else "FAILED"
                self._show_command_output(
                    Panel(
                        Group(
                            Text(f"{status}: {url}", style=f"bold {ACTIVE_GREEN if result.get('ok') else AMBER}"),
                            Text(f"HTTP: {result.get('status_code')}  Time: {result.get('response_time_ms')}ms", style=WHITE),
                            Text(f"Task: {result.get('task_id')}  Next: /task {result.get('task_id')}", style=CYAN),
                        ),
                        title="[bold green]WEB VERIFY[/]",
                        border_style=ACTIVE_GREEN if result.get("ok") else AMBER,
                        box=box.SQUARE,
                    )
                )
            except Exception as exc:
                self._show_command_output(Panel(f"Web verification failed: {exc}", border_style=AMBER, box=box.SQUARE))
            return True

        if lower.startswith("/build-site "):
            parts = _command_parts(command)
            if len(parts) < 3:
                self._show_command_output(Panel("Usage: /build-site <path> <prompt>", border_style=AMBER, box=box.SQUARE))
                return True
            target_path = parts[1]
            prompt = " ".join(parts[2:]).strip()
            self._show_command_output(Panel("Building site scaffold...", border_style=DIM_GREEN, box=box.SQUARE))
            try:
                from .website_builder import WebsiteBuilder

                task = WebsiteBuilder(self.config.paths.base_dir).build_site(prompt, target_path)
                self._show_command_output(
                    Panel(
                        Group(
                            Text(f"{task.get('status')}: {task.get('summary', '')}", style=WHITE),
                            Text(f"Task: {task.get('id')}  Next: /task {task.get('id')}", style=CYAN),
                            Text(f"Path: {Path(target_path).expanduser().resolve()}", style=WHITE),
                        ),
                        title="[bold green]BUILD SITE[/]",
                        border_style=ACTIVE_GREEN,
                        box=box.SQUARE,
                    )
                )
            except Exception as exc:
                self._show_command_output(Panel(f"Build site failed: {exc}", border_style=AMBER, box=box.SQUARE))
            return True

        if lower in {"/onboard", "onboard"}:
            self._show_command_output(self.render_onboarding_panel())
            return True

        if lower.startswith("/onboard "):
            action = command.split(" ", 1)[1].strip().lower()
            if action in {"complete", "done", "finish"}:
                try:
                    memory = getattr(self.agent, "memory", None)
                    user_id = getattr(self.agent, "user_id", "default")
                    if memory is not None:
                        memory.set_preference(user_id, "onboarding_completed", True)
                    self._show_command_output(
                        Panel("Onboarding marked as completed.", border_style=ACTIVE_GREEN, box=box.SQUARE)
                    )
                except Exception as exc:
                    self._show_command_output(
                        Panel(f"Could not update onboarding state: {exc}", border_style=AMBER, box=box.SQUARE)
                    )
            else:
                self._show_command_output(self.render_onboarding_panel())
            return True

        if lower in {"/personality", "personality"}:
            self._show_command_output(self.cmd_personality())
            return True

        if lower.startswith("/personality "):
            remainder = command.split(" ", 1)[1].strip()
            tokens = remainder.split(maxsplit=1)
            preset_names = set((getattr(self.config, "personality", {}) or {}).get("presets", {}).keys())
            try:
                memory = getattr(self.agent, "memory", None)
                user_id = getattr(self.agent, "user_id", "default")
                if tokens and tokens[0].lower() in {"preset", "--preset"} and len(tokens) > 1:
                    preset = tokens[1].strip()
                    if preset not in preset_names:
                        self._show_command_output(
                            Panel(
                                f"Unknown preset: {preset}. Use /personality to list options.",
                                border_style=AMBER,
                                box=box.SQUARE,
                            )
                        )
                        return True
                    if memory is not None:
                        memory.set_preference(user_id, "personality_preset", preset)
                        memory.set_preference(user_id, "personality_custom", "")
                        memory.set_preference(user_id, "personality", "")
                    self._show_command_output(
                        Panel(f"Personality preset set to: {preset}", border_style=ACTIVE_GREEN, box=box.SQUARE)
                    )
                    return True

                if tokens and tokens[0].lower() in {"custom", "--set", "set"} and len(tokens) > 1:
                    value = tokens[1].strip()
                else:
                    value = remainder

                if value:
                    if memory is not None:
                        memory.set_preference(user_id, "personality_custom", value)
                        memory.set_preference(user_id, "personality_preset", "")
                        memory.set_preference(user_id, "personality", value)
                    self._show_command_output(
                        Panel(f"Personality set to: {value}", border_style=ACTIVE_GREEN, box=box.SQUARE)
                    )
                else:
                    self._show_command_output(self.cmd_personality())
            except Exception as exc:
                self._show_command_output(
                    Panel(f"Could not set personality: {exc}", border_style=AMBER, box=box.SQUARE)
                )
            return True

        if lower.startswith("/code "):
            task = command.split(" ", 1)[1].strip()
            if not task:
                self._show_command_output(
                    Panel("Usage: /code <task>", border_style=AMBER, box=box.SQUARE)
                )
                return True
            self._show_command_output(Panel("Coding...", border_style=DIM_GREEN, box=box.SQUARE))
            try:
                result = self._run_code_task(task)
                response = result.get("response", "")
                self._append_history("assistant", response)
                self.agent.total_tokens = getattr(self.agent, "total_tokens", 0) + int(result.get("tokens_used", 0) or 0)
                self._show_command_output(
                    Panel(
                        _render_code_or_text(response, CYAN),
                        title="[bold green]CODE[/]",
                        border_style=ACTIVE_GREEN,
                        box=box.SQUARE,
                        padding=(1, 1),
                    )
                )
            except Exception as exc:
                self._show_command_output(
                    Panel(f"Code task failed: {exc}", border_style=AMBER, box=box.SQUARE)
                )
            return True

        if lower.startswith("/review "):
            task = command.split(" ", 1)[1].strip()
            if not task:
                self._show_command_output(
                    Panel("Usage: /review <task>", border_style=AMBER, box=box.SQUARE)
                )
                return True
            self._show_command_output(Panel("Reviewing...", border_style=DIM_GREEN, box=box.SQUARE))
            result = self._run_review_task(task)
            response = result.get("response", "")
            self._append_history("assistant", response)
            self.agent.total_tokens = getattr(self.agent, "total_tokens", 0) + int(result.get("tokens_used", 0) or 0)
            self._show_command_output(self.render_review_panel())
            if response:
                self._show_command_output(
                    Panel(
                        _render_code_or_text(response, CYAN),
                        title="[bold green]REVIEW[/]",
                        border_style=ACTIVE_GREEN,
                        box=box.SQUARE,
                        padding=(1, 1),
                    )
                )
            return True

        if lower in {"/clear", "clear"}:
            self.history.clear()
            self.session_id = f"s_{int(time.time())}"
            self._show_command_output(Panel("Conversation cleared.", border_style=ACTIVE_GREEN, box=box.SQUARE))
            return True

        if lower.startswith("/mode "):
            mode = command.split(" ", 1)[1].strip().upper()
            if mode in TAB_LABELS:
                self.mode = mode
                self._show_command_output(
                    Panel(f"Mode switched to {self.mode}.", border_style=ACTIVE_GREEN, box=box.SQUARE)
                )
            else:
                self._show_command_output(
                    Panel(
                        f"Unknown mode: {mode}. Use one of {', '.join(TAB_LABELS)}.",
                        border_style=AMBER,
                        box=box.SQUARE,
                    )
                )
            return True

        return False

    def _run_boot_animation(self) -> None:
        frames = [
            "booting local shell...",
            "loading dashboard geometry...",
            "aligning signal and memory...",
        ]
        for idx, line in enumerate(frames, start=1):
            panel = Panel(
                Group(
                    Text("SHAKA", style=f"bold {ACTIVE_GREEN}"),
                    Text(""),
                    Text(line, style=WHITE),
                    Text(f"step {idx}/{len(frames)}", style="dim"),
                ),
                border_style=ACTIVE_GREEN,
                box=box.DOUBLE,
                padding=(1, 2),
            )
            console.clear()
            console.print(panel)
            time.sleep(0.12)
        self._booted = True
        self._show_startup = False

    def _append_history(self, role: str, content: str) -> None:
        self.history.append((role, content))

    def _call_agent(self, message: str) -> dict:
        return self.agent.chat(message, session_id=self.session_id)

    def _parse_json_response(self, response: str) -> dict:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        if start == -1:
            raise ValueError("No JSON object found in response.")
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        return obj

    def _run_review_task(self, task: str) -> dict:
        builder = RepoContextBuilder(Path.cwd(), max_files=6, max_lines=100)
        response = self.agent.chat(
            task,
            session_id=self.session_id,
            extra_system_messages=[
                builder.coding_system_prompt("review"),
                builder.build_task_prompt(task, "review"),
                builder.response_schema("review"),
            ],
            disable_tools=True,
        )

        parsed = {}
        try:
            parsed = self._parse_json_response(response.get("response", ""))
        except Exception:
            parsed = {
                "summary": response.get("response", ""),
                "findings": [],
                "tests": [],
                "notes": [],
            }

        self.last_review = parsed
        return response

    def _run_code_task(self, task: str) -> dict:
        builder = RepoContextBuilder(Path.cwd(), max_files=8, max_lines=120)
        return self.agent.chat(
            task,
            session_id=self.session_id,
            extra_system_messages=[
                builder.coding_system_prompt("build"),
                builder.build_task_prompt(task, "build"),
                builder.response_schema("build"),
            ],
            disable_tools=False,
        )

    def _prompt(self) -> str:
        if self._ensure_prompt_backend() and self._prompt_session is not None:
            try:
                value = self._prompt_session.prompt(
                    HTML("<ansigreen>Shaka&gt;</ansigreen> "),
                    default=self.input_buffer,
                    style=self._prompt_style,
                    bottom_toolbar=HTML("<ansicyan>/help /tasks /task /approvals /approve /reject /retry /web-verify /exit</ansicyan>"),
                    refresh_interval=0.2,
                )
            except EOFError:
                return "/exit"
            return self._normalize_input(value)

        try:
            from rich.prompt import Prompt

            value = Prompt.ask(
                f"[bold {ACTIVE_GREEN}]Shaka[/]",
                default=self.input_buffer,
                console=console,
            )
            return self._normalize_input(value)
        except Exception:
            try:
                return self._normalize_input(input("Shaka> "))
            except EOFError:
                return "/exit"

    def run(self) -> None:
        if not self._booted:
            self._run_boot_animation()

        console.clear()

        try:
            while self.running:
                console.clear()
                console.print(self.render_screen())

                user_input = self._prompt()
                if not user_input:
                    self._flash = not self._flash
                    continue

                self.command_history.append(user_input)
                self._history_index = len(self.command_history)
                if self._prompt_history is not None:
                    self._prompt_history.append_string(user_input)

                if self._handle_command(user_input):
                    continue

                self._append_history("user", user_input)
                console.print(Panel("Thinking...", border_style=DIM_GREEN, box=box.SQUARE))

                started = time.time()
                try:
                    result = self._call_agent(user_input)
                except Exception as exc:
                    error_message = f"Provider error: {exc}"
                    self._append_history("assistant", error_message)
                    self._show_command_output(
                        Panel(error_message, border_style=AMBER, box=box.SQUARE)
                    )
                    self.input_buffer = ""
                    self._flash = not self._flash
                    continue
                elapsed = time.time() - started

                response = result.get("response", "")
                self._append_history("assistant", response)
                self.agent.total_tokens = getattr(self.agent, "total_tokens", 0) + int(result.get("tokens_used", 0) or 0)

                tool_calls = int(result.get("tool_calls_executed", 0) or 0)
                meta = Text()
                meta.append("response received ", style=f"bold {ACTIVE_GREEN}")
                meta.append(f"{elapsed:.1f}s", style=WHITE)
                meta.append("  ", style=WHITE)
                meta.append(f"tokens {result.get('tokens_used', 0)}", style=WHITE)
                meta.append("  ", style=WHITE)
                meta.append(f"tools {tool_calls}", style=WHITE)
                self._show_command_output(Panel(meta, border_style=ACTIVE_GREEN, box=box.SQUARE))

                if response:
                    self._show_command_output(
                        Panel(
                            _render_code_or_text(response, CYAN),
                            title="[bold green]SHAKA[/]",
                            border_style=ACTIVE_GREEN,
                            box=box.SQUARE,
                            padding=(1, 1),
                        )
                    )
                self.input_buffer = ""
                self._flash = not self._flash

        except KeyboardInterrupt:
            console.print(Panel("Interrupted. Goodbye.", border_style=ACTIVE_GREEN, box=box.SQUARE))
        except Exception as exc:
            console.print(Panel(f"Error in TUI: {exc}", border_style="red", box=box.SQUARE))
            raise
