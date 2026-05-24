from __future__ import annotations

import asyncio
from pathlib import Path

from shaka.mcp_runtime import build_server, inspect_stdio_server


def test_build_server_exposes_core_tools():
    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert {"ask", "list_skills", "read_memory", "code_plan", "code_review"}.issubset(names)


def test_inspect_stdio_server_lists_tools(tmp_path: Path):
    script = tmp_path / "dummy_mcp.py"
    script.write_text(
        """\
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Dummy")

@mcp.tool(structured_output=False)
def ping() -> str:
    return "pong"

if __name__ == "__main__":
    mcp.run(transport="stdio")
""",
        encoding="utf-8",
    )

    result = asyncio.run(inspect_stdio_server("python", [str(script)]))
    names = {tool["name"] for tool in result["tools"]}

    assert "ping" in names
