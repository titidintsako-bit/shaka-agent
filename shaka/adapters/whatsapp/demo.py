#!/usr/bin/env python3
"""
Demo script for WhatsApp adapter.
Shows how to use the file-based WhatsApp adapter with Shaka.
"""

import os
import sys
import time
import json
from pathlib import Path

# Add the shaka package to path
# We need to go up four levels from this file to reach the project root
# __file__: .../shaka/adapters/whatsapp/demo.py
# -> whatsapp
# -> adapters
# -> shaka (package)
# -> project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

from shaka.adapters.whatsapp.adapter import WhatsAppAdapter, create_demo_conversation
from shaka.config import ShakaConfig
from shaka.skills import SkillsRegistry
from shaka.memory import MemoryManager


def demo_basic_usage():
    """Demonstrate basic usage of the WhatsApp adapter."""
    print("=" * 60)
    print("SHAKA WHATSAPP ADAPTER DEMO")
    print("=" * 60)
    print()

    # Create adapter instance
    config = ShakaConfig()
    skills = SkillsRegistry()
    memory = MemoryManager(config.paths.base_dir)
    
    # Load core skills (normally done by CLI)
    core_skills_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'shaka', 'skills_core')
    if os.path.exists(core_skills_dir):
        skills.load_core_skills(core_skills_dir)

    adapter = WhatsAppAdapter(
        config=config,
        skills_registry=skills,
        memory_manager=memory,
        user_id="demo_user",
        data_dir=os.path.join(config.paths.base_dir, "whatsapp_demo")
    )

    print(f"Adapter initialized for user: demo_user")
    print(f"Data directory: {adapter.data_dir}")
    print()

    # Create a test message
    test_message = {
        "id": "demo_001",
        "from": "+27123456789",
        "text": "Sawubona Shaka! Unjani ngosuku lolu?",  # Zulu: Hello Shaka! How are you today?
        "timestamp": time.time()
    }

    print("Sending test message to Shaka...")
    print(f"From: {test_message['from']}")
    print(f"Message: {test_message['text']}")
    print()

    # Write the incoming message
    adapter._write_json_file(adapter.incoming_file, [test_message])

    # Process the message
    print("Processing message...")
    responses = adapter.process_incoming()

    print(f"Received {len(responses)} response(s):")
    for i, response in enumerate(responses, 1):
        print(f"  Response {i}:")
        print(f"    To: {response['to']}")
        print(f"    Text: {response['text']}")
        print(f"    Tokens used: {response['tokens_used']}")
        print()

    # Show the files created
    print("Files created:")
    print(f"  Incoming:  {adapter.incoming_file}")
    print(f"  Outgoing:  {adapter.outgoing_file}")
    print()

    # Show the content of the files
    print("Incoming file content:")
    print(json.dumps(adapter._read_json_file(adapter.incoming_file), indent=2))
    print()
    
    print("Outgoing file content:")
    print(json.dumps(adapter._read_json_file(adapter.outgoing_file), indent=2))
    print()


def demo_multiple_messages():
    """Demonstrate processing multiple messages."""
    print("=" * 60)
    print("MULTIPLE MESSAGES DEMO")
    print("=" * 60)
    print()

    # Setup
    config = ShakaConfig()
    skills = SkillsRegistry()
    memory = MemoryManager(config.paths.base_dir)
    
    core_skills_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'shaka', 'skills_core')
    if os.path.exists(core_skills_dir):
        skills.load_core_skills(core_skills_dir)

    adapter = WhatsAppAdapter(
        config=config,
        skills_registry=skills,
        memory_manager=memory,
        user_id="multi_user",
        data_dir=os.path.join(config.paths.base_dir, "whatsapp_multi")
    )

    # Create multiple test messages
    messages = [
        {
            "id": "multi_001",
            "from": "+27111111111",
            "text": "What's the weather like in Cape Town today?",
            "timestamp": time.time()
        },
        {
            "id": "multi_002",
            "from": "+27222222222",
            "text": "Remember that my name is Thandi and I'm from Durban",
            "timestamp": time.time()
        },
        {
            "id": "multi_003",
            "from": "+27333333333",
            "text": "Can you help me with a simple Python function to calculate factorial?",
            "timestamp": time.time()
        }
    ]

    print(f"Sending {len(messages)} test messages...")
    for msg in messages:
        print(f"  From {msg['from']}: {msg['text'][:50]}{'...' if len(msg['text']) > 50 else ''}")
    print()

    # Write all incoming messages
    adapter._write_json_file(adapter.incoming_file, messages)

    # Process all messages
    print("Processing all messages...")
    responses = adapter.process_incoming()

    print(f"Received {len(responses)} response(s):")
    for i, (msg, resp) in enumerate(zip(messages, responses), 1):
        print(f"  Exchange {i}:")
        print(f"    User: {msg['text']}")
        print(f"    Shaka: {resp['text'][:100]}{'...' if len(resp['text']) > 100 else ''}")
        print()

    print("Files created:")
    print(f"  Incoming:  {adapter.incoming_file} (now empty after processing)")
    print(f"  Outgoing:  {adapter.outgoing_file}")
    print()


if __name__ == "__main__":
    # Run the demos
    demo_basic_usage()
    print("\n" + "="*60 + "\n")
    demo_multiple_messages()
    print("Demo completed successfully!")