#!/usr/bin/env python3
"""
Simple test to verify WhatsApp adapter works with mock agent.
"""

import os
import sys
import time
import json
import tempfile
from unittest.mock import MagicMock
from pathlib import Path

# Add current directory to path so we can import shaka modules
sys.path.insert(0, str(Path(__file__).parent))

def test_adapter():
    print("Testing WhatsApp adapter with mock agent...")
    
    # Import after setting up path
    from shaka.adapters.whatsapp.adapter import WhatsAppAdapter
    from shaka.config import ShakaConfig
    from shaka.skills import SkillsRegistry
    from shaka.memory import MemoryManager
    
    # Create a mock agent
    mock_agent = MagicMock()
    mock_agent.chat.return_value = {
        "response": "Sawubona! Ngiyaphila. Unjani wena?",  # Zulu: Hello! I'm fine. How are you?
        "session_id": "mock_session_123",
        "tokens_used": 15
    }

    # Set up the adapter with the mock agent
    config = ShakaConfig()

    with tempfile.TemporaryDirectory(prefix="shaka_whatsapp_test_") as temp_dir:
        config.paths.base_dir = temp_dir

        skills = SkillsRegistry()
        memory = MemoryManager(config.paths.base_dir)

        # Create adapter
        adapter = WhatsAppAdapter(
            config=config,
            skills_registry=skills,
            memory_manager=memory,
            user_id="mock_user",
            data_dir=os.path.join(config.paths.base_dir, "whatsapp_test")
        )

        # Replace the agent with our mock
        adapter.agent = mock_agent

        print(f"✓ Adapter initialized for user: mock_user")
        print(f"✓ Data directory: {adapter.data_dir}")

        # Create a test message in Zulu
        test_message = {
            "id": "test_001",
            "from": "+27123456789",
            "text": "Sawubona Shaka! Unjani?",  # Zulu: Hello Shaka! How are you?
            "timestamp": time.time()
        }

        print(f"✓ Created test message: {test_message['text']}")

        # Write the incoming message
        adapter._write_json_file(adapter.incoming_file, [test_message])
        print("✓ Wrote incoming message to file")

        # Process the message
        responses = adapter.process_incoming()
        print(f"✓ Processed {len(responses)} response(s)")

        # Check responses
        assert len(responses) == 1, f"Expected 1 response, got {len(responses)}"
        response = responses[0]
        assert response["text"] == "Sawubona! Ngiyaphila. Unjani wena?"
        assert response["to"] == "+27123456789"
        assert response["from"] == "mock_user"
        assert "timestamp" in response
        assert response["session_id"] == "mock_session_123"
        print("✓ Response validation passed")

        # Check that incoming file is now empty
        incoming = adapter._read_json_file(adapter.incoming_file)
        assert incoming == [], "Incoming file should be empty after processing"
        print("✓ Incoming file correctly cleared")

        # Check outgoing file has the response
        outgoing = adapter._read_json_file(adapter.outgoing_file)
        assert len(outgoing) == 1, f"Expected 1 outgoing message, got {len(outgoing)}"
        assert outgoing[0]["text"] == "Sawubona! Ngiyaphila. Unjani wena?"
        print("✓ Outgoing file contains correct response")

        print("\n" + "="*50)
        print("🎉 ALL TESTS PASSED!")
        print("The WhatsApp adapter is working correctly.")
        print("="*50)
        
        # Show what was created
        print(f"\nFiles created in: {adapter.data_dir}")
        print(f"  - incoming.json: {os.path.getsize(adapter.incoming_file)} bytes")
        print(f"  - outgoing.json: {os.path.getsize(adapter.outgoing_file)} bytes")
    
if __name__ == "__main__":
    try:
        test_adapter()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
