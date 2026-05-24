"""Hello Skill for Shaka.

Provides greeting and introduction.
"""

class SkillHandler:
    """Handles hello skill."""

    def get_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "hello",
                "description": "Get a greeting and introduction to Shaka",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }

    def run(self, message: str, context: dict) -> str:
        """Return a friendly greeting."""
        from shaka.i18n import gettext as _
        return _("""Hello! I'm Shaka, your personal AI assistant from Africa.
I can help you with:
- Answering questions
- Executing code
- Reading and writing files
- Checking load shedding schedules (South Africa)
- Getting weather information
- Translating languages (including Zulu)
- And much more through skills!

Just ask me anything, or try:
- 'shaka ask "What is the weather in Cape Town?"'
- 'shaka skills' to see all available skills
- 'shaka memory' to view what I remember

I'm designed to be zero-cost, privacy-first, and work on your machine.
How can I assist you today?""")

