"""WhatsApp adapter for Shaka using file-based message queue.

This adapter simulates WhatsApp communication by reading incoming messages
from a JSON file and writing responses to another JSON file.
"""

import json
import os
import time
from typing import List, Dict, Any
from pathlib import Path

from shaka.agent import Agent
from shaka.config import ShakaConfig
from shaka.memory import MemoryManager
from shaka.skills import SkillsRegistry


class WhatsAppAdapter:
    """Adapter that connects Shaka to WhatsApp via file-based message queue."""

    def __init__(
        self,
        config: ShakaConfig,
        skills_registry: SkillsRegistry,
        memory_manager: MemoryManager,
        user_id: str = "default",
        data_dir: str = None
    ):
        self.config = config
        self.skills_registry = skills_registry
        self.memory = memory_manager
        self.user_id = user_id
        self.agent = Agent(config, skills_registry, memory_manager, user_id)

        # Set up data directory for WhatsApp messages
        if data_dir is None:
            data_dir = os.path.join(config.paths.base_dir, "whatsapp")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.incoming_file = self.data_dir / "incoming.json"
        self.outgoing_file = self.data_dir / "outgoing.json"

        # Initialize files if they don't exist
        if not self.incoming_file.exists():
            self._write_json_file(self.incoming_file, [])
        if not self.outgoing_file.exists():
            self._write_json_file(self.outgoing_file, [])

    def _read_json_file(self, filepath: Path) -> List[Dict[str, Any]]:
        """Read a JSON file and return its contents as a list."""
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_json_file(self, filepath: Path, data: List[Dict[str, Any]]) -> None:
        """Write a list of dicts to a JSON file."""
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def get_incoming_messages(self) -> List[Dict[str, Any]]:
        """Get and clear incoming messages."""
        messages = self._read_json_file(self.incoming_file)
        # Clear the incoming file after reading
        self._write_json_file(self.incoming_file, [])
        return messages

    def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message by appending to outgoing file."""
        outgoing = self._read_json_file(self.outgoing_file)
        outgoing.append(message)
        self._write_json_file(self.outgoing_file, outgoing)

    def process_incoming(self) -> List[Dict[str, Any]]:
        """Process all incoming messages and return the responses."""
        incoming_messages = self.get_incoming_messages()
        responses = []

        for msg in incoming_messages:
            # Extract the text content
            text = msg.get("text", "")
            if not text:
                continue

            # Get response from Shaka agent
            result = self.agent.chat(text, session_id=f"whatsapp_{msg.get('id', 'unknown')}")

            # Build response message
            response_msg = {
                "id": f"resp_{int(time.time())}_{len(responses)}",
                "from": self.user_id,  # Our user ID (the agent)
                "to": msg.get("from", "unknown"),  # Original sender
                "text": result["response"],
                "timestamp": time.time(),
                "session_id": result["session_id"],
                "tokens_used": result["tokens_used"]
            }

            responses.append(response_msg)
            self.send_message(response_msg)

        return responses

    def run_once(self) -> List[Dict[str, Any]]:
        """Run one cycle: process incoming messages and return responses."""
        return self.process_incoming()

    def run_daemon(self, poll_interval: float = 5.0) -> None:
        """Run continuously, polling for new messages."""
        print(f"WhatsApp adapter started for user {self.user_id}")
        print(f"Monitoring {self.incoming_file} for incoming messages")
        print("Press Ctrl+C to stop")

        try:
            while True:
                responses = self.process_incoming()
                if responses:
                    print(f"Processed {len(responses)} message(s)")
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nWhatsApp adapter stopped.")


def create_demo_conversation():
    """Create a demo conversation for testing and videos."""
    # This function creates sample incoming messages for demo purposes
    demo_messages = [
        {
            "id": "msg_001",
            "from": "+27123456789",  # Example South African number
            "text": "Hello Shaka! How are you today?",
            "timestamp": time.time() - 10
        },
        {
            "id": "msg_002",
            "from": "+27123456789",
            "text": "Can you tell me about load shedding in Johannesburg?",
            "timestamp": time.time() - 5
        }
    ]

    # Write demo messages to incoming file
    adapter = WhatsAppAdapter(
        config=ShakaConfig(),  # This will load default config
        skills_registry=SkillsRegistry(),
        memory_manager=MemoryManager(".")
    )
    adapter._write_json_file(adapter.incoming_file, demo_messages)
    print(f"Created demo conversation in {adapter.incoming_file}")
    print("Run the adapter to see Shaka's responses!")


if __name__ == "__main__":
    # If run directly, create a demo conversation
    create_demo_conversation()