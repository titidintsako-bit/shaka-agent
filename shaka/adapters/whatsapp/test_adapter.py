"""
Tests for the WhatsApp adapter.
"""

import json
import os
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest

# Add the shaka package to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shaka.adapters.whatsapp.adapter import WhatsAppAdapter
from shaka.config import ShakaConfig
from shaka.skills import SkillsRegistry
from shaka.memory import MemoryManager


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    agent = MagicMock()
    agent.chat.return_value = {
        "response": "This is a test response",
        "session_id": "test_session",
        "tokens_used": 10
    }
    return agent


@pytest.fixture
def adapter(temp_dir, mock_agent):
    """Create a WhatsApp adapter with mocked dependencies."""
    config = ShakaConfig()
    # Override the base_dir to use our temp directory
    config.paths.base_dir = temp_dir
    
    skills = SkillsRegistry()
    memory = MemoryManager(temp_dir)
    
    # Patch the Agent constructor to return our mock
    with patch('shaka.adapters.whatsapp.adapter.Agent', return_value=mock_agent):
        adapter = WhatsAppAdapter(
            config=config,
            skills_registry=skills,
            memory_manager=memory,
            user_id="test_user",
            data_dir=os.path.join(temp_dir, "whatsapp")
        )
        # Replace the agent with our mock
        adapter.agent = mock_agent
        yield adapter


def test_adapter_initialization(adapter, temp_dir):
    """Test that the adapter initializes correctly."""
    assert adapter.user_id == "test_user"
    # data_dir is a Path object, so convert to string for comparison
    assert str(adapter.data_dir) == os.path.join(temp_dir, "whatsapp")
    assert str(adapter.incoming_file) == os.path.join(temp_dir, "whatsapp", "incoming.json")
    assert str(adapter.outgoing_file) == os.path.join(temp_dir, "whatsapp", "outgoing.json")
    
    # Check that the files were created
    assert os.path.exists(adapter.incoming_file)
    assert os.path.exists(adapter.outgoing_file)
    
    # Check that the files contain empty lists
    with open(adapter.incoming_file, 'r') as f:
        incoming = json.load(f)
        assert incoming == []
        
    with open(adapter.outgoing_file, 'r') as f:
        outgoing = json.load(f)
        assert outgoing == []


def test_read_write_json_file(adapter):
    """Test reading and writing JSON files."""
    test_data = [{"id": "test", "text": "hello"}]
    
    # Test writing
    adapter._write_json_file(adapter.incoming_file, test_data)
    
    # Test reading
    result = adapter._read_json_file(adapter.incoming_file)
    assert result == test_data


def test_get_incoming_messages(adapter):
    """Test getting incoming messages."""
    # Add some test messages
    test_messages = [
        {"id": "msg1", "text": "Hello"},
        {"id": "msg2", "text": "How are you?"}
    ]
    adapter._write_json_file(adapter.incoming_file, test_messages)
    
    # Get messages
    messages = adapter.get_incoming_messages()
    assert messages == test_messages
    
    # Check that the file is now empty
    with open(adapter.incoming_file, 'r') as f:
        incoming = json.load(f)
        assert incoming == []


def test_send_message(adapter):
    """Test sending a message."""
    message = {"id": "resp1", "text": "Hi there!"}
    adapter.send_message(message)
    
    # Check that the message was added to outgoing
    outgoing = adapter._read_json_file(adapter.outgoing_file)
    assert len(outgoing) == 1
    assert outgoing[0] == message


def test_process_incoming(adapter, mock_agent):
    """Test processing incoming messages."""
    # Set up incoming message
    incoming_msg = {
        "id": "msg_001",
        "from": "+27123456789",
        "text": "Hello Shaka!",
        "timestamp": time.time()
    }
    adapter._write_json_file(adapter.incoming_file, [incoming_msg])
    
    # Process incoming messages
    responses = adapter.process_incoming()
    
    # Verify agent was called correctly
    mock_agent.chat.assert_called_once()
    args, kwargs = mock_agent.chat.call_args
    assert args[0] == "Hello Shaka!"  # The message text
    assert "session_id" in kwargs
    
    # Verify response
    assert len(responses) == 1
    response = responses[0]
    assert response["text"] == "This is a test response"
    assert response["to"] == "+27123456789"
    assert response["from"] == "test_user"
    assert "timestamp" in response
    assert response["session_id"] == "test_session"


def test_process_multiple_incoming(adapter, mock_agent):
    """Test processing multiple incoming messages."""
    # Set up multiple incoming messages
    incoming_msgs = [
        {
            "id": "msg_001",
            "from": "+27111111111",
            "text": "First message",
            "timestamp": time.time()
        },
        {
            "id": "msg_002",
            "from": "+27222222222",
            "text": "Second message",
            "timestamp": time.time()
        }
    ]
    adapter._write_json_file(adapter.incoming_file, incoming_msgs)
    
    # Process incoming messages
    responses = adapter.process_incoming()
    
    # Verify agent was called twice
    assert mock_agent.chat.call_count == 2
    
    # Verify responses
    assert len(responses) == 2
    for response in responses:
        assert response["text"] == "This is a test response"
        assert "timestamp" in response
        assert response["session_id"] == "test_session"


def test_process_empty_incoming(adapter):
    """Test processing when there are no incoming messages."""
    # File already contains empty list from initialization
    responses = adapter.process_incoming()
    assert responses == []


def test_process_incoming_with_empty_text(adapter, mock_agent):
    """Test processing messages with empty text."""
    incoming_msg = {
        "id": "msg_001",
        "from": "+27123456789",
        "text": "",  # Empty text
        "timestamp": time.time()
    }
    adapter._write_json_file(adapter.incoming_file, [incoming_msg])
    
    responses = adapter.process_incoming()
    
    # Should not call the agent for empty text
    mock_agent.chat.assert_not_called()
    assert responses == []


def test_run_once(adapter, mock_agent):
    """Test the run_once method."""
    incoming_msg = {
        "id": "msg_001",
        "from": "+27123456789",
        "text": "Test message",
        "timestamp": time.time()
    }
    adapter._write_json_file(adapter.incoming_file, [incoming_msg])
    
    responses = adapter.run_once()
    
    assert len(responses) == 1
    mock_agent.chat.assert_called_once()


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])