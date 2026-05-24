"""File Operations Skill for Shaka.

Handles reading, writing, creating, and managing files and directories.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any


class SkillHandler:
    """Handles file operations."""

    def __init__(self):
        # Security: restrict to user's home directory and project directory
        self.allowed_paths = [
            os.path.expanduser("~"),  # User's home
            os.getcwd(),  # Current working directory
            str(Path(__file__).resolve().parents[3]),  # Shaka project directory
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

    def _safe_join(self, base: str, subpath: str) -> str:
        """Safely join base and subpath, preventing directory traversal."""
        # Normalize the subpath
        subpath = os.path.normpath(subpath)
        if subpath.startswith("..") or subpath.startswith("/"):
            # Prevent absolute paths and parent directory traversal
            return None
        
        full_path = os.path.join(base, subpath)
        return self._is_path_allowed(full_path) and full_path or None

    def get_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "fileops",
                "description": "Perform file operations: read, write, create, list, delete files/directories",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Action to perform: read, write, create, list, delete, exists",
                            "enum": ["read", "write", "create", "list", "delete", "exists"]
                        },
                        "path": {
                            "type": "string",
                            "description": "File or directory path"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write (for write action)"
                        },
                        "encoding": {
                            "type": "string",
                            "description": "File encoding (default: utf-8)",
                            "default": "utf-8"
                        }
                    },
                    "required": ["action", "path"]
                }
            }
        }

    def run(self, message: str, context: dict) -> str:
        """Main entry point for file operations."""
        kwargs = context.get("kwargs", {})
        
        action = kwargs.get("action")
        path = kwargs.get("path")
        content = kwargs.get("content", "")
        encoding = kwargs.get("encoding", "utf-8")
        
        if not action or not path:
            return "Error: Both 'action' and 'path' parameters are required."
        
        # Security check
        if not self._is_path_allowed(path):
            return f"Error: Access to path '{path}' is not allowed for security reasons."
        
        try:
            if action == "read":
                return self._read_file(path, encoding)
            elif action == "write":
                return self._write_file(path, content, encoding)
            elif action == "create":
                return self._create_file(path, content, encoding)
            elif action == "list":
                return self._list_directory(path)
            elif action == "delete":
                return self._delete_path(path)
            elif action == "exists":
                return self._path_exists(path)
            else:
                return f"Error: Unknown action '{action}'. Supported actions: read, write, create, list, delete, exists"
                
        except Exception as e:
            return f"Error performing file operation: {str(e)}"

    def _read_file(self, path: str, encoding: str) -> str:
        """Read a file and return its contents."""
        if not os.path.isfile(path):
            return f"Error: File '{path}' does not exist or is not a file."
        
        with open(path, 'r', encoding=encoding) as f:
            content = f.read()
        
        return f"Contents of '{path}':\\n\\n{content}"

    def _write_file(self, path: str, content: str, encoding: str) -> str:
        """Write content to a file."""
        # Create directory if it doesn't exist
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        with open(path, 'w', encoding=encoding) as f:
            f.write(content)
        
        return f"Successfully wrote {len(content)} characters to '{path}'."

    def _create_file(self, path: str, content: str, encoding: str) -> str:
        """Create a new file (fails if file already exists)."""
        if os.path.exists(path):
            return f"Error: File '{path}' already exists. Use 'write' action to overwrite."
        
        # Create directory if it doesn't exist
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        with open(path, 'w', encoding=encoding) as f:
            f.write(content)
        
        return f"Successfully created file '{path}' with {len(content)} characters."

    def _list_directory(self, path: str) -> str:
        """List contents of a directory."""
        if not os.path.isdir(path):
            return f"Error: '{path}' is not a directory or does not exist."
        
        items = []
        try:
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    items.append(f"📁 {item}/")
                else:
                    size = os.path.getsize(item_path)
                    items.append(f"📄 {item} ({size} bytes)")
            
            if not items:
                return f"Directory '{path}' is empty."
            
            return f"Contents of '{path}':\\n" + "\\n".join(items)
        except PermissionError:
            return f"Error: Permission denied accessing directory '{path}'."

    def _delete_path(self, path: str) -> str:
        """Delete a file or directory."""
        if not os.path.exists(path):
            return f"Error: '{path}' does not exist."
        
        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
            return f"Successfully deleted file '{path}'."
        elif os.path.isdir(path):
            # Check if directory is empty
            if not os.listdir(path):
                os.rmdir(path)
                return f"Successfully deleted empty directory '{path}'."
            else:
                return f"Error: Directory '{path}' is not empty. Please delete contents first or use recursive delete (not implemented for safety)."
        else:
            return f"Error: Unknown path type for '{path}'."

    def _path_exists(self, path: str) -> str:
        """Check if a path exists."""
        if os.path.exists(path):
            if os.path.isfile(path):
                return f"✅ File '{path}' exists."
            elif os.path.isdir(path):
                return f"✅ Directory '{path}' exists."
            else:
                return f"✅ Path '{path}' exists (other type)."
        else:
            return f"❌ Path '{path}' does not exist."
