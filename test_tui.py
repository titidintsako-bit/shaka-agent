#!/usr/bin/env python3
"""Test the enhanced TUI with a mock agent."""

import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Mock classes to avoid needing real API key
class MockAgent:
    def __init__(self):
        self.session_messages = []
        # Mock skills registry
        from shaka.skills import SkillsRegistry
        self.skills_registry = SkillsRegistry()
        self.skills_registry.load_core_skills(str(Path(__file__).parent / "shaka" / "skills_core"))
        # Mock memory
        from shaka.memory import MemoryManager
        self.memory = MemoryManager("/tmp/shaka_test")
    
    def chat(self, message, session_id=None):
        # Return a mock response without calling LLM
        return {
            "response": f"Mock response to: {message}",
            "session_id": session_id or "test_session",
            "tokens_used": 10,
            "elapsed_seconds": 0.5,
            "tool_calls_executed": 0
        }

class MockConfig:
    def __init__(self):
        self.language = "en"
        # Mock nested config
        class Model:
            provider = "groq"
            model = "llama-3.3-70b-versatile"
            api_key = "mock-key"
            base_url = ""
        self.model = Model()
        self.whatsapp = {"enabled": False}
        self.dashboard = {"enabled": False}
        self.paths = type('Paths', (), {"base_dir": "/tmp/shaka_test"})()

def test_tui_methods():
    """Test the TUI methods without running the full UI."""
    from shaka.tui import ShakaTUI
    
    agent = MockAgent()
    config = MockConfig()
    tui = ShakaTUI(agent, config)
    
    print("Testing TUI methods:")
    print("=" * 50)
    
    # Test banner (just see if it runs without error)
    try:
        tui.banner()
        print("✓ banner() runs")
    except Exception as e:
        print(f"✗ banner() failed: {e}")
    
    # Test cmd_help
    try:
        tui.cmd_help()
        print("✓ cmd_help() runs")
    except Exception as e:
        print(f"✗ cmd_help() failed: {e}")
    
    # Test cmd_skills
    try:
        tui.cmd_skills()
        print("✓ cmd_skills() runs")
    except Exception as e:
        print(f"✗ cmd_skills() failed: {e}")
    
    # Test cmd_memory
    try:
        tui.cmd_memory()
        print("✓ cmd_memory() runs")
    except Exception as e:
        print(f"✗ cmd_memory() failed: {e}")
    
    # Test cmd_clear
    try:
        tui.cmd_clear()
        print("✓ cmd_clear() runs")
    except Exception as e:
        print(f"✗ cmd_clear() failed: {e}")
    
    # Test cmd_stats
    try:
        tui.cmd_stats()
        print("✓ cmd_stats() runs")
    except Exception as e:
        print(f"✗ cmd_stats() failed: {e}")
    
    # Test cmd_language
    try:
        tui.cmd_language()
        print("✓ cmd_language() runs")
    except Exception as e:
        print(f"✗ cmd_language() failed: {e}")
    
    print("=" * 50)
    print("All method tests completed.")

if __name__ == "__main__":
    test_tui_methods()
