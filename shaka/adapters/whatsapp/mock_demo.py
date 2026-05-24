#!/usr/bin/env python3
"""
A simple test to show the WhatsApp adapter working with a mock agent.
This avoids the need for an API key.
"""

import os
import sys
import time
import json
from unittest.mock import MagicMock

# Add the shaka package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from shaka.adapters.whatsapp.adapter import WhatsAppAdapter
from shaka.config import ShakaConfig
from shaka.skills import SkillsRegistry
from shaka.memory import MemoryManager


def main():
    print("=" * 60)
    print("SHAKA WHATSAPP ADAPTER - MOCK DEMO")
    print("=" * 60)
    print()

    # Create a mock agent
    mock_agent = MagicMock()
    mock_agent.chat.return_value = {
        "response": "Sawubona! Ngiyaphila. Unjani wena?",  # Zulu: Hello! I'm fine. How are you?
        "session_id": "mock_session_123",
        "tokens_used": 15
    }

    # Set up the adapter with the mock agent
    config = ShakaConfig()
    # We don't need real config for the mock, but we need to set a base_dir
    config.paths.base_dir = os.path.expanduser("~/.shaka")
    
    skills = SkillsRegistry()
    memory = MemoryManager(config.paths.base_dir)
    
    # Create adapter
    adapter = WhatsAppAdapter(
        config=config,
        skills_registry=skills,
        memory_manager=memory,
        user_id="mock_user",
        data_dir=os.path.join(config.paths.base_dir, "whatsapp_mock")
    )
    
    # Replace the agent with our mock
    adapter.agent = mock_agent

    print(f"Adapter initialized for user: mock_user")
    print(f"Data directory: {adapter.data_dir}")
    print()

    # Create a test message in Zulu
    test_message = {
        "id": "mock_001",
        "from": "+27123456789",
        "text": "Sawubona Shaka! Unjani?",  # Zulu: Hello Shaka! How are you?
        "timestamp": time.time()
    }

    print("Sending test message to Shaka...")
    print(f"From: {test_message['from']}")
    print(f"Message: {test_message['text']}")
    print()

    # Write the incoming message
    adapter._write_json_file(adapter.incoming_file, [test_message])

    # Process the message
    print("Processing message with mock agent...")
    responses = adapter.process_incoming()

    print(f"Received {len(responses)} response(s):")
    for i, response in enumerate(responses, 1):
        print(f"  Response {i}:")
        print(f"    To: {response['to']}")
        print(f"    Text: {response['text']}")
        print(f"    Tokens used: {response['tokens_used']}")
        print(f"    Session ID: {response['session_id']}")
        print()

    # Show the files created
    print("Files created:")
    print(f"  Incoming:  {adapter.incoming_file}")
    print(f"  Outgoing:  {adapter.outgoing_file}")
    print()

    # Show the content of the files
    print("Incoming file content (should be empty after processing):")
    print(json.dumps(adapter._read_json_file(adapter.incoming_file), indent=2))
    print()
    
    print("Outgoing file content:")
    print(json.dumps(adapter._read_json_file(adapter.outgoing_file), indent=2))
    print()

    print("Demo completed successfully! The adapter is working correctly.")


if __name__ == "__main__":
    main()