"""Message builder for constructing LLM prompts with context."""

import re
from typing import List, Dict, Optional
from .config import ShakaConfig
from .skills import SkillsRegistry
from .memory import MemoryManager


class MessageBuilder:
    """Builds message context for LLM calls."""

    def __init__(
        self,
        config: ShakaConfig,
        skills_registry: SkillsRegistry,
        memory_manager: MemoryManager,
        user_id: str = "default"
    ):
        self.config = config
        self.skills_registry = skills_registry
        self.memory = memory_manager
        self.user_id = user_id

    def _resolve_personality(self) -> str:
        personality = getattr(self.config, "personality", {}) or {}
        presets = personality.get("presets", {}) if isinstance(personality, dict) else {}
        default_profile = personality.get("default_profile", "") if isinstance(personality, dict) else ""
        default_instructions = personality.get("instructions", "") if isinstance(personality, dict) else ""

        prefs = self.memory.get_preferences(self.user_id)
        preset_name = prefs.get("personality_preset", "") if isinstance(prefs, dict) else ""
        custom_personality = prefs.get("personality_custom", "") if isinstance(prefs, dict) else ""
        legacy_personality = prefs.get("personality", "") if isinstance(prefs, dict) else ""

        parts = []
        if default_profile:
            parts.append(f"Default personality: {default_profile}.")
        if default_instructions:
            parts.append(default_instructions)

        if preset_name and isinstance(presets, dict):
            preset_text = presets.get(preset_name, "")
            if preset_text:
                parts.append(f"User personality preset '{preset_name}': {preset_text}")
                return "\n".join(parts)

        if custom_personality:
            parts.append(f"User personality preference: {custom_personality}")
            return "\n".join(parts)

        if legacy_personality:
            parts.append(f"User personality preference: {legacy_personality}")
            return "\n".join(parts)

        return "\n".join(parts)

    def build_messages(
        self,
        user_message: str,
        session_id: str,
        extra_system_messages: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Build the full message context for the LLM."""
        messages = []

        # System prompt
        system_prompt = self.config.system_prompt
        messages.append({"role": "system", "content": system_prompt})

        resolved_personality = self._resolve_personality()
        if resolved_personality:
            messages.append({
                "role": "system",
                "content": resolved_personality,
            })

        if extra_system_messages:
            for extra in extra_system_messages:
                if extra:
                    messages.append({"role": "system", "content": extra})

        # Give the model a concise view of loaded capabilities so it can answer
        # accurately instead of claiming that tools do not exist.
        available_tools = self.skills_registry.list_skills()
        if available_tools:
            tool_lines = []
            for tool in available_tools[:16]:
                desc = tool.get("description", "")
                tool_lines.append(f"- {tool.get('name', '')}: {desc}")
            messages.append({
                "role": "system",
                "content": (
                    "Available Shaka capabilities:\n"
                    + "\n".join(tool_lines)
                    + "\n\nIf a user asks about coding, websites, files, or web research, "
                    "prefer using the relevant capability instead of saying the task is impossible."
                ),
            })

        message_lower = user_message.lower() if user_message else ""
        if re.search(r"\b(code|coding|build|website|web app|bug|fix|refactor|debug|python|javascript|repo|agent)\b", message_lower):
            messages.append({
                "role": "system",
                "content": (
                    "Coding request detected. Treat this as a real engineering task. "
                    "If the user asked for code, debugging, refactoring, repository work, "
                    "or a website/app, help solve it directly. Ask for missing file paths, "
                    "target scope, or acceptance criteria only when they are actually needed."
                ),
            })

        if re.search(r"\b(search|research|news|latest|current|look up|find)\b", message_lower):
            messages.append({
                "role": "system",
                "content": (
                    "Research request detected. If the websearch capability is available, "
                    "use the tool named websearch rather than claiming web search is unavailable."
                ),
            })

        # Inject memory context
        memory = self.memory.load_memory(self.user_id)
        facts = memory.get("facts", [])
        if facts:
            facts_text = "\n".join([
                f"- {f.get('text', f) if isinstance(f, dict) else f}"
                for f in facts[:20]
            ])
            messages.append({
                "role": "system",
                "content": f"User facts you remember:\n{facts_text}",
            })

        # Inject skill context
        if user_message:
            skill = self.skills_registry.find_skill_for_message(user_message)
            if skill:
                messages.append({
                    "role": "system",
                    "content": f"Active skill: {skill.name}. {skill.description}",
                })

        # Load recent conversation history
        recent = self.memory.get_recent_messages(self.user_id, session_id, limit=8)
        messages.extend(recent)

        # Add user message
        messages.append({"role": "user", "content": user_message})

        return messages
