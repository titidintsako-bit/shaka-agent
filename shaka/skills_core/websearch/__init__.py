"""Web Search Skill for Shaka.

Uses ddgs (free, no API key) to search the web.
Returns concise markdown results for the agent to use.
"""

import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


class SkillHandler:
    """Handles web search queries."""

    def __init__(self):
        pass

    def get_tool_def(self) -> dict:
        """Return OpenAI-style tool definition."""
        return {
            "type": "function",
            "function": {
                "name": "websearch",
                "description": "Search the web for information. Returns formatted results.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The specific search query"},
                    },
                    "required": ["query"],
                },
            },
        }

    def run(self, message: str, context: dict) -> str:
        """Main entry point for the skill."""
        query = context.get("kwargs", {}).get("query", "")
        if not query:
            return "I need a search query to look up."

        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                return "Web search tool not installed. Run: pip install ddgs"

        try:
            with DDGS() as ddgs_instance:
                results = list(ddgs_instance.text(query, max_results=5))

            if not results:
                return f"No results found for '{query}'."

            parts = [f"### Search Results for '{query}'", ""]

            for i, r in enumerate(results, 1):
                parts.append(f"**{i}. {r.get('title', 'No Title')}**")
                parts.append(f"   - {r.get('body', '')}")
                parts.append(f"   - [Link]({r.get('href', '')})")
                parts.append("")

            return "\n".join(parts)

        except Exception as e:
            return f"Search error: {str(e)}"
