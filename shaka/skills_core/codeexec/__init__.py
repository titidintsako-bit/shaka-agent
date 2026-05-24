"""Code Execution Skill for Shaka.

Safely executes code in Python and Bash, returning the output.
"""

import os
import subprocess
import tempfile
import sys
import shutil
from pathlib import Path


class SkillHandler:
    """Handles code execution."""

    def __init__(self):
        # Security: restrict execution to certain directories and timeouts
        self.allowed_paths = [
            os.path.expanduser("~"),  # User's home
            os.getcwd(),  # Current working directory
            str(Path(__file__).resolve().parents[3]),  # Shaka project directory
            "/tmp",  # Temporary files
        ]
        self.timeout = 30  # seconds

    def _is_path_allowed(self, path: str) -> bool:
        """Check if a path is within allowed directories."""
        try:
            # Resolve the path to avoid symlink tricks
            resolved_path = os.path.realpath(path)
            
            # Check if it's within any allowed path
            for allowed in self.allowed_paths:
                allowed_real = os.path.realpath(allowed)
                if resolved_path.startswith(allowed_real):
                    return True
            return False
        except Exception:
            return False

    def get_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "codeexec",
                "description": "Execute code in Python or Bash and return the output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
                            "description": "Programming language to execute",
                    "enum": ["python", "bash", "sh", "powershell", "ps1"]
                        },
                        "code": {
                            "type": "string",
                            "description": "The code to execute"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default: 30)",
                            "default": 30
                        }
                    },
                    "required": ["language", "code"]
                }
            }
        }

    def run(self, message: str, context: dict) -> str:
        """Main entry point for code execution."""
        kwargs = context.get("kwargs", {})
        
        language = kwargs.get("language")
        code = kwargs.get("code")
        timeout = kwargs.get("timeout", self.timeout)
        
        if not language or not code:
            return "Error: Both 'language' and 'code' parameters are required."
        
        if language not in ["python", "bash", "sh", "powershell", "ps1"]:
            return f"Error: Unsupported language '{language}'. Supported: python, bash, sh, powershell, ps1"
        
        try:
            if language == "python":
                return self._execute_python(code, timeout)
            elif language in ["bash", "sh"]:
                return self._execute_bash(code, timeout)
            elif language in ["powershell", "ps1"]:
                return self._execute_powershell(code, timeout)
            else:
                return f"Error: Unsupported language '{language}'"
                
        except Exception as e:
            return f"Error executing code: {str(e)}"

    def _execute_python(self, code: str, timeout: int) -> str:
        """Execute Python code safely."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        try:
            # Execute the Python code
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            output_lines = []
            if result.stdout:
                output_lines.append("STDOUT:")
                output_lines.append(result.stdout)
            if result.stderr:
                output_lines.append("STDERR:")
                output_lines.append(result.stderr)
            
            output_lines.append(f"Exit code: {result.returncode}")
            
            output = "\\n".join(output_lines)
            
            if result.returncode == 0:
                return output
            else:
                return f"Execution failed:\\n{output}"
                
        except subprocess.TimeoutExpired:
            return f"Error: Code execution timed out after {timeout} seconds."
        except Exception as e:
            return f"Error executing Python code: {str(e)}"
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except:
                pass

    def _execute_bash(self, code: str, timeout: int) -> str:
        """Execute Bash code safely."""
        try:
            bash_exe = shutil.which("bash") or shutil.which("sh")
            if not bash_exe:
                return "Error: Bash shell is not available on this system."

            result = subprocess.run(
                [bash_exe, "-lc", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            output_lines = []
            if result.stdout:
                output_lines.append("STDOUT:")
                output_lines.append(result.stdout)
            if result.stderr:
                output_lines.append("STDERR:")
                output_lines.append(result.stderr)
            
            output_lines.append(f"Exit code: {result.returncode}")
            
            output = "\\n".join(output_lines)
            
            if result.returncode == 0:
                return output
            else:
                return f"Execution failed:\\n{output}"
                
        except subprocess.TimeoutExpired:
            return f"Error: Code execution timed out after {timeout} seconds."
        except Exception as e:
            return f"Error executing Bash code: {str(e)}"

    def _execute_powershell(self, code: str, timeout: int) -> str:
        """Execute PowerShell code safely."""
        try:
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                return "Error: PowerShell is not available on this system."

            result = subprocess.run(
                [shell, "-NoProfile", "-Command", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            output_lines = []
            if result.stdout:
                output_lines.append("STDOUT:")
                output_lines.append(result.stdout)
            if result.stderr:
                output_lines.append("STDERR:")
                output_lines.append(result.stderr)

            output_lines.append(f"Exit code: {result.returncode}")

            output = "\n".join(output_lines)

            if result.returncode == 0:
                return output
            return f"Execution failed:\n{output}"

        except subprocess.TimeoutExpired:
            return f"Error: Code execution timed out after {timeout} seconds."
        except Exception as e:
            return f"Error executing PowerShell code: {str(e)}"
