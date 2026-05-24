"""Protocol-level MCP support for Shaka.

This module exposes Shaka as an MCP server and provides a small inspection
client for connecting to external MCP servers from the CLI.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

from shaka.agent import Agent
from shaka.code_workflow import RepoContextBuilder
from shaka.config import load_config
from shaka.memory import MemoryManager
from shaka.skills import SkillsRegistry


@dataclass
class MCPToolPreview:
    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None


def _build_registry(config_path: str | None = None):
    config = load_config(config_path)
    memory = MemoryManager(config.paths.base_dir)
    skills = SkillsRegistry()
    core_skills_dir = Path(__file__).resolve().parent / "skills_core"
    skills.load_core_skills(str(core_skills_dir))
    agent = Agent(config, skills, memory)
    return config, memory, skills, agent


def build_server(config_path: str | None = None) -> FastMCP:
    """Create an MCP server exposing Shaka's core workflows."""
    config, memory, skills, agent = _build_registry(config_path)
    server = FastMCP("Shaka")

    @server.tool(structured_output=False)
    def ask(message: str, session_id: str | None = None) -> dict[str, Any]:
        """Send a message to Shaka and receive a response."""
        return agent.chat(message, session_id=session_id)

    @server.tool(structured_output=False)
    def list_skills() -> list[dict[str, Any]]:
        """List loaded skills."""
        return skills.list_skills()

    @server.tool(structured_output=False)
    def read_memory(user_id: str = "default") -> dict[str, Any]:
        """Read the local memory snapshot for a user."""
        memory_snapshot = memory.load_memory(user_id)
        return {
            "facts": memory_snapshot.get("facts", []),
            "wiki_pages": memory.get_wiki_pages(user_id),
            "sessions": memory.list_sessions(user_id),
        }

    @server.tool(structured_output=False)
    def code_plan(
        task: str,
        path: str = ".",
        issue_url: str | None = None,
        context_file: str | None = None,
        note: list[str] | None = None,
    ) -> dict[str, Any]:
        """Produce a read-only coding plan."""
        workspace = Path(path).resolve()
        focus_path = workspace if workspace.is_file() else workspace
        if workspace.is_file():
            workspace = workspace.parent

        builder = RepoContextBuilder(workspace_root=workspace, focus_path=focus_path)
        response = agent.chat(
            task,
            extra_system_messages=[
                builder.coding_system_prompt("plan"),
                builder.build_task_prompt(task, "plan"),
                builder.response_schema("plan"),
            ],
            disable_tools=True,
        )

        return {
            "mode": "plan",
            "response": response,
            "workspace": str(workspace),
            "focus_path": str(focus_path),
            "issue_url": issue_url,
            "context_file": context_file,
            "notes": note or [],
        }

    @server.tool(structured_output=False)
    def code_review(
        task: str,
        path: str = ".",
        issue_url: str | None = None,
        context_file: str | None = None,
        note: list[str] | None = None,
    ) -> dict[str, Any]:
        """Produce a read-only code review."""
        workspace = Path(path).resolve()
        focus_path = workspace if workspace.is_file() else workspace
        if workspace.is_file():
            workspace = workspace.parent

        builder = RepoContextBuilder(workspace_root=workspace, focus_path=focus_path)
        response = agent.chat(
            task,
            extra_system_messages=[
                builder.coding_system_prompt("review"),
                builder.build_task_prompt(task, "review"),
                builder.response_schema("review"),
            ],
            disable_tools=True,
        )

        return {
            "mode": "review",
            "response": response,
            "workspace": str(workspace),
            "focus_path": str(focus_path),
            "issue_url": issue_url,
            "context_file": context_file,
            "notes": note or [],
        }

    @server.resource("shaka://status")
    def status() -> dict[str, Any]:
        """Return a concise status snapshot."""
        return {
            "name": config.name,
            "provider": config.model.provider,
            "model": config.model.model,
            "language": config.language,
            "skills": len(skills.list_skills()),
            "base_dir": config.paths.base_dir,
        }

    return server


def run_server(config_path: str | None = None, transport: str = "stdio", mount_path: str | None = None) -> None:
    """Run the Shaka MCP server."""
    server = build_server(config_path)
    server.run(transport=transport, mount_path=mount_path)


async def inspect_stdio_server(command: str, args: Iterable[str] | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Inspect a stdio MCP server and return its advertised tools."""
    params = StdioServerParameters(command=command, args=list(args or []), env=env or {})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {
                "tools": [
                    asdict(MCPToolPreview(name=tool.name, description=getattr(tool, "description", None), input_schema=getattr(tool, "inputSchema", None)))
                    for tool in tools.tools
                ]
            }
