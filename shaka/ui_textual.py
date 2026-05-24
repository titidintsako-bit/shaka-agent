"""Textual Neon UI for Shaka (Matrix Neon Edition).

This module provides a production-grade TUI using Textual as the primary UI
and Rich for rendering. It is designed to be a polished, keyboard-driven UI
with panels for Conversation, Status, Memory, and Input. A Rich fallback
UI (ShakaTUI) remains available if Textual cannot be installed or on
Windows environments that block terminal features.

Step C: Code rendering for fenced code blocks with syntax highlighting.
"""

import time
import asyncio
import re
from typing import Optional, List, Tuple

try:
    from textual.app import App  # type: ignore
    from textual.widgets import Static  # type: ignore
    from textual import events  # type: ignore
    TEXTUAL_AVAILABLE = True
except Exception:
    TEXTUAL_AVAILABLE = False

from .logo_ascii import LOGO as ASCII_LOGO
from rich.panel import Panel
from rich import box
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text


def parse_markdown_code_blocks(text: str) -> List[Tuple[str, bool]]:
    """Parse text and separate code blocks from regular text.

    Returns a list of (content, is_code) tuples.
    """
    parts = []
    code_block_pattern = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
    last_end = 0

    for match in code_block_pattern.finditer(text):
        before = text[last_end:match.start()]
        if before:
            parts.append((before, False))
        lang = match.group(1)
        code = match.group(2)
        parts.append((code, True, lang))
        last_end = match.end()

    remaining = text[last_end:]
    if remaining:
        parts.append((remaining, False))

    return parts


def render_conversation(logs: List[str], max_lines: int = 80, console_width: int = 120) -> str:
    """Render conversation logs with code syntax highlighting."""
    if not logs:
        return ""

    lines = []
    for log in logs[-max_lines:]:
        label_end = log.find(": ", 2) if log.startswith("USER:") or log.startswith("ASSISTANT:") else -1
        if label_end == -1:
            lines.append(log)
            continue

        label = log[:label_end + 2]
        content = log[label_end + 2:]
        parts = parse_markdown_code_blocks(content)

        content_rendered = ""
        for part in parts:
            if len(part) == 3:
                code, is_code, lang = part
                if is_code:
                    try:
                        syntax = Syntax(code, lang if lang else "python", theme="monokai", line_numbers=True)
                        console = Console()
                        with console.capture() as capture:
                            console.print(syntax)
                        content_rendered += capture.get() + "\n"
                    except Exception:
                        content_rendered += f"[code]{code}[/code]\n"
                else:
                    content_rendered += part[0]
            elif not is_code:
                content_rendered += part[0]

        lines.append(label + content_rendered.rstrip("\n"))

    return "\n".join(lines)


def get_panel_text(logs: List[str], max_lines: int = 80) -> str:
    """Get plain text for panel display without syntax highlighting."""
    if not logs:
        return ""
    return "\n".join(logs[-max_lines:])


if TEXTUAL_AVAILABLE:
    class NeonTextualApp(App):
        """Minimal Neon Textual App for Shaka."""
        CSS = """
        Screen { background: #000000; color: #00FF41; }
        #logo { color: #00FF41; height: 7; }
        #panel_conv { height: 1fr; }
        #panel_right { height: 8; }
        #input_line { height: 3; }
        .panel { border: solid #00FF41; padding: 1; margin: 1; }
        """

        def __init__(self, agent, config):
            super().__init__()
            self.agent = agent
            self.config = config
            self.input_buffer = ""
            self.logs = []
            self.session_id = f"s_{int(time.time())}"
            self.total_tokens = 0
            self.panel_conv = None
            self.panel_right = None
            self.input_line = None

        async def on_mount(self) -> None:
            self.logo = Static(ASCII_LOGO, id="logo")
            self.panel_conv = Static("Conversation placeholder...", id="panel_conv")
            self.panel_right = Static("STATUS:\nModel: --\nTokens: 0\n\nMEMORY:\nNo memories yet", id="panel_right")
            self.input_line = Static("Input: ", id="input_line")
            await self.mount(self.logo)
            await self.mount(self.panel_conv)
            await self.mount(self.panel_right)
            await self.mount(self.input_line)

        async def on_key(self, event: events.Key) -> None:
            if event.key == "ctrl+c":
                await self.action_quit()
            elif event.key == "enter":
                text = self.input_buffer.strip()
                if text:
                    self.logs.append(f"USER: {text}")
                    self.input_buffer = ""
                    panel_text = get_panel_text(self.logs, max_lines=80)
                    self.panel_conv.update(Panel(panel_text, border_style="#00FF41", box=box.ROUNDED))
                    self.refresh()
                    if getattr(self, 'agent', None) is not None:
                        try:
                            response = await self._call_agent(text)
                            if response:
                                self.logs.append(f"ASSISTANT: {response.get('content', str(response))}")
                                self.total_tokens += int(response.get("tokens_used", 0) or 0)
                                panel_text = get_panel_text(self.logs, max_lines=80)
                                self.panel_conv.update(Panel(panel_text, border_style="#00FF41", box=box.ROUNDED))
                                self.panel_right.update(Panel(f"STATUS:\nModel: --\nTokens: {self.total_tokens}\n\nMEMORY:\nNo memories yet", border_style="#00FF41", box=box.ROUNDED))
                                self.refresh()
                        except Exception:
                            pass
            elif len(event.key) == 1:
                self.input_buffer += event.key
                self.input_line.update(Panel("Input: " + self.input_buffer, border_style="#00FF41", box=box.ROUNDED))
                self.refresh()
            elif event.key == "backspace":
                self.input_buffer = self.input_buffer[:-1]
                self.input_line.update(Panel("Input: " + self.input_buffer, border_style="#00FF41", box=box.ROUNDED))
                self.refresh()

        async def _call_agent(self, text: str):
            """Call the agent and return the response."""
            if not getattr(self, 'agent', None):
                return {"content": "", "tokens_used": 0}
            loop = asyncio.get_event_loop()
            try:
                response = await loop.run_in_executor(None, lambda: self.agent.chat(text, session_id=self.session_id))
                return response if isinstance(response, dict) else {"content": str(response), "tokens_used": 0}
            except Exception as e:
                return {"content": f"[error] {str(e)}", "tokens_used": 0}
else:
    class NeonTextualApp:
        def __init__(self, *args, **kwargs):
            pass
        def run(self):
            raise RuntimeError("Textual not available; falling back to Rich UI.")
