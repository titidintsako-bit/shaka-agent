"""Fact extractor for remembering important information from conversation."""

import re
from typing import List, Dict, Any


class FactExtractor:
    """Extracts and remembers important facts from conversation."""

    def extract_facts(self, user_msg: str, assistant_msg: str) -> List[str]:
        """Extract facts from user and assistant messages."""
        facts_to_remember = []

        # Simple heuristic: if user states personal info, remember it
        lower_msg = user_msg.lower()
        patterns = [
            ("my name is ", "name"),
            ("i am from ", "location"),
            ("i live in ", "location"),
            ("my email is ", "email"),
            ("my phone is ", "phone"),
            ("my address is ", "address"),
            ("i work at ", "work"),
            ("i study at ", "education"),
        ]

        for pattern, fact_type in patterns:
            if pattern in lower_msg:
                # Extract the value after the pattern
                value = user_msg.lower().split(pattern, 1)[1].strip().rstrip('.')
                # Clean up: take first sentence or until punctuation
                value = value.split('.')[0].split('!')[0].split('?')[0].strip()
                if value:
                    fact_text = f"User's {fact_type}: {value}"
                    facts_to_remember.append(fact_text)

        # Also look for explicit statements like "Remember that..."
        remember_patterns = [
            r"remember that (.+)",
            r"please remember (.+)",
            r"keep in mind (.+)",
        ]

        for pattern in remember_patterns:
            matches = re.findall(pattern, lower_msg)
            for match in matches:
                fact_text = f"User said to remember: {match.strip()}"
                facts_to_remember.append(fact_text)

        return facts_to_remember