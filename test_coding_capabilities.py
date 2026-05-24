#!/usr/bin/env python3
"""Portable coding-capability smoke test for Shaka."""

from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path

from shaka.skills import SkillsRegistry


ROOT = Path(__file__).resolve().parent
SKILLS_DIR = ROOT / "shaka" / "skills_core"


def _load_registry() -> SkillsRegistry:
    registry = SkillsRegistry()
    registry.load_core_skills(str(SKILLS_DIR))
    return registry


def test_file_operations() -> None:
    print("=" * 60)
    print("Testing File Operations Skill")
    print("=" * 60)

    registry = _load_registry()

    with tempfile.TemporaryDirectory(prefix="shaka_coding_") as temp_dir:
        temp_root = Path(temp_dir)
        demo_file = temp_root / "demo_test.txt"

        print("\n1. Listing directory contents:")
        result = registry.execute_tool("fileops", action="list", path=temp_dir)
        assert "Contents of" in result or "empty" in result
        print(result[:200] + "..." if len(result) > 200 else result)

        print("\n2. Creating a test file:")
        result = registry.execute_tool(
            "fileops",
            action="create",
            path=str(demo_file),
            content="Hello from Shaka's file operations skill.\nThis file proves the coding path works.",
        )
        assert "Successfully created" in result
        print(result)

        print("\n3. Reading the test file:")
        result = registry.execute_tool("fileops", action="read", path=str(demo_file))
        assert "Contents of" in result
        print(result)

        print("\n4. Cleaning up test file:")
        result = registry.execute_tool("fileops", action="delete", path=str(demo_file))
        assert "Successfully deleted" in result
        print(result)


def test_code_execution() -> None:
    print("\n" + "=" * 60)
    print("Testing Code Execution Skill")
    print("=" * 60)

    registry = _load_registry()

    print("\n1. Executing Python code:")
    result = registry.execute_tool(
        "codeexec",
        language="python",
        code="""
def add(a, b):
    return a + b

print("add(2, 2) =", add(2, 2))
""".strip(),
    )
    assert "add(2, 2) = 4" in result
    print(result)

    if platform.system() == "Windows":
        print("\n2. Executing PowerShell code:")
        result = registry.execute_tool(
            "codeexec",
            language="powershell",
            code='Write-Output "Shaka coding check"; Write-Output "OK"',
        )
        assert "Shaka coding check" in result
        print(result)
    else:
        print("\n2. Executing Bash code:")
        result = registry.execute_tool(
            "codeexec",
            language="bash",
            code='echo "Shaka coding check"; echo "OK"',
        )
        assert "Shaka coding check" in result
        print(result)


def test_integration_scenario() -> None:
    print("\n" + "=" * 60)
    print("Testing Integration Scenario: Create and Run a Script")
    print("=" * 60)

    registry = _load_registry()

    with tempfile.TemporaryDirectory(prefix="shaka_script_") as temp_dir:
        temp_root = Path(temp_dir)
        script_path = temp_root / "demo_script.py"

        script_content = '''#!/usr/bin/env python3
def greet(name):
    return f"Hello, {name}! Welcome to Shaka."

def main():
    print(greet("Mzansi"))
    print("Shaka can read, write, and execute code.")

if __name__ == "__main__":
    main()
'''

        print("\n1. Creating a Python script:")
        result = registry.execute_tool(
            "fileops",
            action="create",
            path=str(script_path),
            content=script_content,
        )
        assert "Successfully created" in result
        print(result)

        print("\n2. Reading the script back:")
        result = registry.execute_tool("fileops", action="read", path=str(script_path))
        assert "Hello, " in result
        print(result)

        print("\n3. Running the script:")
        result = registry.execute_tool(
            "codeexec",
            language="python",
            code=f"exec(open(r'{script_path}').read())",
        )
        assert "Welcome to Shaka" in result
        print(result)

        print("\n4. Cleaning up demo files:")
        result = registry.execute_tool("fileops", action="delete", path=str(script_path))
        assert "Successfully deleted" in result
        print(result)


if __name__ == "__main__":
    print("Shaka Coding Capabilities Demo")
    print("This demonstrates that Shaka can perform coding-related tasks.")

    test_file_operations()
    test_code_execution()
    test_integration_scenario()

    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("Shaka coding tools exercised:")
    print("  - fileops: file and directory operations")
    print("  - codeexec: Python and Bash execution")
    print("=" * 60)
