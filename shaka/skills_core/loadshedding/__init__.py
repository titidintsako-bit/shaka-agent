"""Load Shedding Skill for Shaka.

Uses EskomSePush API (free tier) to check load shedding schedules.
User can set their area once, and it remembers.
"""

import os
import requests
from datetime import datetime

# Free tier: https://eskomsepush.gumroad.com/l/api
ESKOM_API_URL = "https://developer.sepush.co.za/business/2.0"

class SkillHandler:
    """Handles load shedding queries."""

    def __init__(self):
        self.api_token = os.environ.get("ESKOMSEUSH_TOKEN", "")

    def get_tool_def(self) -> dict:
        """Return OpenAI-style tool definition."""
        return {
            "type": "function",
            "function": {
                "name": "loadshedding",
                "description": "Check Eskom load shedding schedule for a South African area",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "area": {"type": "string", "description": "Area name (e.g., 'Cape Town', 'Johannesburg')"},
                        "action": {"type": "string", "enum": ["check", "schedule", "status"],
                                   "description": "What to check: current stage, schedule, or status"},
                    },
                    "required": ["action"],
                },
            },
        }

    def run(self, message: str, context: dict) -> str:
        """Main entry point for the skill."""
        action = context.get("kwargs", {}).get("action", "check")
        area = context.get("kwargs", {}).get("area", "")

        if not self.api_token:
            return (
                "Load shedding skill needs an EskomSePush API token.\n"
                "Get one free at: https://eskomsepush.gumroad.com/l/api\n"
                "Then set: export ESKOMSEUSH_TOKEN='your_token_here'"
            )

        try:
            headers = {"token": self.api_token}

            if action == "status":
                return self._check_status(headers)
            elif action == "schedule":
                if not area:
                    return "Please provide your area (e.g., 'Cape Town', 'Sandton')"
                return self._check_schedule(headers, area)
            else:  # check
                if not area:
                    return "Please provide your area (e.g., 'Cape Town', 'Sandton')"
                return self._check_area(headers, area)

        except Exception as e:
            return f"Error checking load shedding: {str(e)}"

    def _check_status(self, headers: dict) -> str:
        """Check current national load shedding stage."""
        response = requests.get(f"{ESKOM_API_URL}/national", headers=headers, timeout=10)
        data = response.json()

        if "status" in data:
            stage = data["status"].get("stage", 0)
            if stage <= 0:
                return "No load shedding currently scheduled nationally."
            return f"Current national load shedding: Stage {stage}"

        return "Unable to fetch load shedding status."

    def _check_schedule(self, headers: dict, area: str) -> str:
        """Check load shedding schedule for an area."""
        # First search for the area
        search_url = f"{ESKOM_API_URL}/search"
        response = requests.get(
            search_url,
            headers=headers,
            params={"q": area},
            timeout=10
        )
        search_data = response.json()

        if "results" not in search_data or not search_data["results"]:
            return f"Could not find area '{area}'. Try a different name."

        # Get the first result's ID
        area_id = search_data["results"][0]["id"]

        # Get schedule
        schedule_url = f"{ESKOM_API_URL}/area"
        response = requests.get(
            schedule_url,
            headers=headers,
            params={"id": area_id},
            timeout=10
        )
        schedule_data = response.json()

        if "events" not in schedule_data or not schedule_data["events"]:
            return f"No load shedding events found for '{area}' in the next few days."

        events = schedule_data["events"]
        now = datetime.now()
        response_parts = [f"Load shedding schedule for '{area}':", ""]

        for event in events[:5]:
            start = datetime.fromisoformat(event["start"].replace("+02:00", ""))
            end = datetime.fromisoformat(event["end"].replace("+02:00", ""))
            stage = event.get("stage", 0)

            if start < now < end:
                response_parts.append(f"  [NOW] Stage {stage}: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
            elif start > now:
                response_parts.append(f"  [UPCOMING] Stage {stage}: {start.strftime('%d %b %H:%M')} - {end.strftime('%H:%M')}")

        return "\n".join(response_parts)

    def _check_area(self, headers: dict, area: str) -> str:
        """Combined check: status + next event."""
        status = self._check_status(headers)
        schedule = self._check_schedule(headers, area)
        return f"{status}\n\n{schedule}"
