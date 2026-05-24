"""Skills system for Shaka.

Skills are pluggable Python modules with YAML metadata.
Each skill can declare capabilities and handle specific message patterns.
"""

import os
import yaml
import importlib.util
from typing import Optional, Dict, List, Any


def _normalize_risk(meta: dict) -> dict:
    """Return display-only risk metadata from skill.yaml."""
    risk = meta.get("risk") or {}
    if not isinstance(risk, dict):
        risk = {}

    mutating = bool(risk.get("mutating", False))
    approval_required = bool(risk.get("approval_required", False))
    risk_level = str(risk.get("level") or ("mutating" if mutating else "read_only"))
    notes = str(risk.get("notes") or "")

    return {
        "level": risk_level,
        "mutating": mutating,
        "read_only": not mutating,
        "approval_required": approval_required,
        "notes": notes,
    }

class Skill:
    """A single skill/plugin for Shaka."""

    def __init__(self, name: str, meta: dict, handler: Any):
        self.name = name
        self.meta = meta
        self.handler = handler
        self.description = meta.get('description', '')
        self.triggers = meta.get('triggers', [])
        self.usage = meta.get('usage', '')
        self.author = meta.get('author', '')
        self.version = meta.get('version', '0.1.0')
        self.path = meta.get('path', '')
        self.risk = _normalize_risk(meta)

    def should_handle(self, message: str) -> bool:
        """Check if this skill should handle the given message."""
        message_lower = message.lower()
        for trigger in self.triggers:
            if isinstance(trigger, str) and trigger.lower() in message_lower:
                return True
        return False

    def handle(self, message: str, context: dict) -> str:
        """Execute the skill and return a response."""
        if hasattr(self.handler, 'run'):
            return self.handler.run(message, context)
        return f"Skill '{self.name}' has no run method."

class SkillsRegistry:
    """Manages all installed skills."""

    def __init__(self, skills_dirs: List[str] = None):
        self.skills: Dict[str, Skill] = {}
        self.skills_dirs = skills_dirs or []

    def register_skill(self, skill: Skill):
        """Register a skill in the registry."""
        self.skills[skill.name] = skill

    def load_skill(self, skill_dir: str) -> Optional[Skill]:
        """Load a skill from a directory."""
        yaml_path = os.path.join(skill_dir, "skill.yaml")
        if not os.path.exists(yaml_path):
            return None

        with open(yaml_path, 'r') as f:
            meta = yaml.safe_load(f) or {}

        name = meta.get('name', os.path.basename(skill_dir))
        meta["path"] = skill_dir

        # Look for Python handler
        handler = None
        py_path = os.path.join(skill_dir, "__init__.py")
        if os.path.exists(py_path):
            spec = importlib.util.spec_from_file_location(name, py_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, 'SkillHandler'):
                handler = module.SkillHandler()

        skill = Skill(name=name, meta=meta, handler=handler)
        self.register_skill(skill)
        return skill

    def load_core_skills(self, core_dir: str, verbose: bool = True):
        """Load all core skills from a directory."""
        if not os.path.exists(core_dir):
            return

        for entry in os.listdir(core_dir):
            skill_dir = os.path.join(core_dir, entry)
            if os.path.isdir(skill_dir) and os.path.exists(os.path.join(skill_dir, "skill.yaml")):
                skill = self.load_skill(skill_dir)
                if skill and verbose:
                    print(f"  Loaded core skill: {skill.name}")

    def load_user_skills(self, user_skills_dir: str, verbose: bool = True):
        """Load user-installed skills."""
        if not os.path.exists(user_skills_dir):
            return

        for entry in os.listdir(user_skills_dir):
            skill_dir = os.path.join(user_skills_dir, entry)
            if os.path.isdir(skill_dir) and os.path.exists(os.path.join(skill_dir, "skill.yaml")):
                skill = self.load_skill(skill_dir)
                if skill and verbose:
                    print(f"  Loaded user skill: {skill.name}")

    def find_skill_for_message(self, message: str) -> Optional[Skill]:
        """Find the best skill to handle a message."""
        for skill in self.skills.values():
            if skill.should_handle(message):
                return skill
        return None

    def list_skills(self) -> List[dict]:
        """List all registered skills."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "author": s.author,
                "triggers": s.triggers,
                "path": s.path,
                "risk": s.risk,
                "mutating": s.risk["mutating"],
                "read_only": s.risk["read_only"],
                "approval_required": s.risk["approval_required"],
                "risk_level": s.risk["level"],
                "risk_notes": s.risk["notes"],
            }
            for s in self.skills.values()
        ]

    def get_tools_definition(self) -> list:
        """Get all skills as LLM tool definitions."""
        tools = []
        for skill in self.skills.values():
            if hasattr(skill.handler, 'get_tool_def'):
                tools.append(skill.handler.get_tool_def())
        return tools

    def execute_tool(self, tool_name: str, **kwargs) -> str:
        """Execute a tool by name."""
        if tool_name in self.skills:
            skill = self.skills[tool_name]
            context = {"kwargs": kwargs}
            return skill.handle("", context)
        return f"Unknown tool: {tool_name}"
