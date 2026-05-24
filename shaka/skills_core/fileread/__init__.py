"""File Read Skill for Shaka.

Reads and returns the contents of a file.
"""

import os
from pathlib import Path


class SkillHandler:
    """Handles file reading."""

    def __init__(self):
        project_root = Path(__file__).resolve().parents[3]
        # Security: restrict to user's home directory, current workspace, and package checkout.
        self.allowed_paths = [
            os.path.expanduser("~"),  # User's home
            os.getcwd(),  # Current working directory
            str(project_root),
        ]

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
                "name": "fileread",
                "description": "Read the complete contents of a text file and return it as text. Use this to examine or view file contents like config.yaml, source code, or text documents.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path to read"
                        },
                        "encoding": {
                            "type": "string",
                            "description": "File encoding (default: utf-8)",
                            "default": "utf-8"
                        }
                    },
                    "required": ["path"]
                }
            }
        }

    def run(self, message: str, context: dict) -> str:
        """Main entry point for file reading."""
        kwargs = context.get("kwargs", {})
        
        path = kwargs.get("path")
        encoding = kwargs.get("encoding", "utf-8")
        
        if not path:
            return "Error: 'path' parameter is required."
        
        # Security check
        if not self._is_path_allowed(path):
            return f"Error: Access to path '{path}' is not allowed for security reasons."
        
        try:
            if not os.path.isfile(path):
                return f"Error: File '{path}' does not exist or is not a file."
            
            with open(path, 'r', encoding=encoding) as f:
                content = f.read()
            
            return content
            
        except Exception as e:
            return f"Error reading file: {str(e)}"
