"""Comprehensive tests for the Textual-based UI integration."""

import pytest
import time


class MockAgent:
    def __init__(self):
        self.memory = None
        self.chat_called = False
        self.last_message = None
        self.last_session_id = None

    def chat(self, message, session_id=None):
        self.chat_called = True
        self.last_message = message
        self.last_session_id = session_id
        return {
            "content": f"Echo: {message}",
            "tokens_used": len(f"Echo: {message}")
        }


class MockConfig:
    def __init__(self):
        self.language = 'en'

        class Model:
            provider = 'groq'
            model = 'llama-3.3-70b-versatile'
            api_key = 'mock'
            base_url = ''

        self.model = Model()
        self.paths = type('P', (), {'base_dir': '/tmp'})()


def test_import_neon_textual_app():
    """Verify NeonTextualApp is importable."""
    from shaka.ui_textual import NeonTextualApp
    assert NeonTextualApp is not None


def test_instantiation_with_mock_agent():
    """Verify NeonTextualApp initializes with mock agent."""
    from shaka.ui_textual import NeonTextualApp
    agent = MockAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)
    assert app is not None
    assert app.agent is agent
    assert app.config is config
    assert hasattr(app, 'input_buffer')
    assert hasattr(app, 'logs')
    assert hasattr(app, 'session_id')
    assert hasattr(app, 'total_tokens')


def test_session_id_format():
    """Verify session_id has expected format."""
    from shaka.ui_textual import NeonTextualApp
    agent = MockAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)
    assert app.session_id.startswith('s_')
    assert len(app.session_id) > 2


def test_initial_state():
    """Verify initial state is correct."""
    from shaka.ui_textual import NeonTextualApp
    agent = MockAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)
    assert app.input_buffer == ""
    assert app.logs == []
    assert app.total_tokens == 0


def test_textual_app_mounts_with_installed_textual():
    """Verify the Textual app starts with the installed Textual API."""
    import asyncio

    from shaka.ui_textual import NeonTextualApp, TEXTUAL_AVAILABLE
    if not TEXTUAL_AVAILABLE:
        pytest.skip("Textual is not installed")

    async def run_app_smoke():
        agent = MockAgent()
        config = MockConfig()
        app = NeonTextualApp(agent, config)
        async with app.run_test(size=(100, 32)):
            assert app.panel_conv is not None
            assert app.panel_right is not None
            assert app.input_line is not None

    asyncio.run(run_app_smoke())


def test_logs_accumulation():
    """Verify logs accumulate correctly."""
    from shaka.ui_textual import NeonTextualApp
    agent = MockAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)
    app.logs.append("USER: hello")
    app.logs.append("ASSISTANT: Echo: hello")
    assert len(app.logs) == 2
    assert app.logs[0] == "USER: hello"
    assert app.logs[1] == "ASSISTANT: Echo: hello"


def test_call_agent_returns_expected_response():
    """Verify _call_agent returns expected response."""
    import asyncio

    from shaka.ui_textual import NeonTextualApp
    agent = MockAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = loop.run_until_complete(app._call_agent("test message"))
        assert response is not None
        assert isinstance(response, dict)
        assert "content" in response
        assert "tokens_used" in response
        assert response["content"] == "Echo: test message"
        assert response["tokens_used"] == len("Echo: test message")
    finally:
        loop.close()


def test_call_agent_populates_mock_agent_state():
    """Verify _call_agent calls agent.chat with correct arguments."""
    import asyncio

    from shaka.ui_textual import NeonTextualApp
    agent = MockAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)
    app.session_id = "test_s_123"

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(app._call_agent("hello world"))
        assert agent.chat_called
        assert agent.last_message == "hello world"
        assert agent.last_session_id == "test_s_123"
    finally:
        loop.close()


def test_call_agent_handles_string_response():
    """Verify _call_agent handles string responses from agent.chat."""
    import asyncio

    from shaka.ui_textual import NeonTextualApp

    class StringAgent:
        def chat(self, message, session_id=None):
            return "simple string response"

    agent = StringAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = loop.run_until_complete(app._call_agent("test"))
        assert response is not None
        assert isinstance(response, dict)
        assert "content" in response
        assert response["content"] == "simple string response"
    finally:
        loop.close()


def test_call_agent_handles_exception():
    """Verify _call_agent handles exceptions gracefully."""
    import asyncio

    from shaka.ui_textual import NeonTextualApp

    class FailingAgent:
        def chat(self, message, session_id=None):
            raise ValueError("Test exception")

    agent = FailingAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = loop.run_until_complete(app._call_agent("test"))
        assert response is not None
        assert isinstance(response, dict)
        assert "content" in response
        assert "[error]" in response["content"]
        assert "Test exception" in response["content"]
    finally:
        loop.close()


def test_call_agent_no_agent():
    """Verify _call_agent handles missing agent gracefully."""
    import asyncio

    from shaka.ui_textual import NeonTextualApp

    class NoChatAgent:
        pass

    agent = NoChatAgent()
    config = MockConfig()
    app = NeonTextualApp(agent, config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = loop.run_until_complete(app._call_agent("test"))
        assert response is not None
        assert isinstance(response, dict)
        assert "content" in response
        assert "tokens_used" in response
        assert response["tokens_used"] == 0
    finally:
        loop.close()


def test_ascii_logo_import():
    """Verify ASCII logo can be imported."""
    from shaka.logo_ascii import LOGO
    assert LOGO is not None
    assert len(LOGO) > 0
    assert isinstance(LOGO, str)


def test_parse_markdown_code_blocks():
    """Verify code block parsing works correctly."""
    from shaka.ui_textual import parse_markdown_code_blocks

    text = "Hello\n```python\nprint('hello')\n```\nWorld"
    parts = parse_markdown_code_blocks(text)
    assert len(parts) == 3
    assert "Hello" in parts[0][0]
    assert parts[0][1] is False
    assert len(parts[1]) == 3
    assert "print('hello')" in parts[1][0]
    assert parts[1][1] is True
    assert parts[1][2] == "python"
    assert "World" in parts[2][0]
    assert parts[2][1] is False


def test_parse_markdown_code_blocks_no_code():
    """Verify plain text without code blocks is handled correctly."""
    from shaka.ui_textual import parse_markdown_code_blocks

    text = "Hello World"
    parts = parse_markdown_code_blocks(text)
    assert len(parts) == 1
    assert parts[0] == ("Hello World", False)


def test_parse_markdown_code_blocks_multiple():
    """Verify multiple code blocks are parsed correctly."""
    from shaka.ui_textual import parse_markdown_code_blocks

    text = "```python\ncode1\n```\ntext\n```javascript\ncode2\n```"
    parts = parse_markdown_code_blocks(text)
    assert len(parts) == 3
    assert parts[0][1] is True
    assert "code1" in parts[0][0]
    assert parts[1][1] is False
    assert "text" in parts[1][0]
    assert parts[2][1] is True
    assert "code2" in parts[2][0]


def test_get_panel_text_empty():
    """Verify get_panel_text handles empty logs."""
    from shaka.ui_textual import get_panel_text
    result = get_panel_text([], max_lines=80)
    assert result == ""


def test_get_panel_text_with_logs():
    """Verify get_panel_text formats logs correctly."""
    from shaka.ui_textual import get_panel_text
    logs = ["USER: hello", "ASSISTANT: Echo: hello"]
    result = get_panel_text(logs, max_lines=80)
    assert "USER: hello" in result
    assert "ASSISTANT: Echo: hello" in result


def test_rich_panel_import():
    """Verify Rich Panel is available."""
    from rich.panel import Panel
    from rich import box
    assert Panel is not None
    assert box is not None


if __name__ == "__main__":
    test_import_neon_textual_app()
    test_instantiation_with_mock_agent()
    test_session_id_format()
    test_initial_state()
    test_logs_accumulation()
    test_call_agent_returns_expected_response()
    test_call_agent_populates_mock_agent_state()
    test_call_agent_handles_string_response()
    test_call_agent_handles_exception()
    test_call_agent_no_agent()
    test_ascii_logo_import()
    test_parse_markdown_code_blocks()
    test_parse_markdown_code_blocks_no_code()
    test_parse_markdown_code_blocks_multiple()
    test_get_panel_text_empty()
    test_get_panel_text_with_logs()
    test_rich_panel_import()
    print("All tests passed.")
