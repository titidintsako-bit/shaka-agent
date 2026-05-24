from shaka.agent import Agent
from shaka.automation import RISK_RISKY_WRITE, TaskStore
from shaka.config import DataPaths, ShakaConfig
from shaka.memory import MemoryManager


class FakeProvider:
    def __init__(self, tool_call):
        self.tool_call = tool_call
        self.calls = 0
        self.tool_result_messages = []

    def generate(self, messages, tools=None, model=None):
        self.calls += 1
        self.tool_result_messages.extend(item for item in messages if item.get("role") == "tool")
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [self.tool_call],
                "tokens_used": 1,
            }
        return {
            "content": self.tool_result_messages[-1]["content"] if self.tool_result_messages else "done",
            "tool_calls": [],
            "tokens_used": 1,
        }


class FakeSkills:
    def __init__(self, listed_skills=None):
        self.executed = []
        self._listed_skills = listed_skills or []

    def get_tools_definition(self):
        return [{"type": "function", "function": {"name": "fileops", "parameters": {"type": "object"}}}]

    def execute_tool(self, tool_name, **kwargs):
        self.executed.append((tool_name, kwargs))
        return f"executed {tool_name} {kwargs}"

    def find_skill_for_message(self, message):
        return None

    def list_skills(self):
        return list(self._listed_skills)


def _agent(tmp_path, tool_call, listed_skills=None):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    skills = FakeSkills(listed_skills=listed_skills)
    agent = Agent(config, skills, MemoryManager(str(tmp_path)))
    agent.provider = FakeProvider(tool_call)
    return agent, skills


def test_agent_pauses_codeexec_tool_call_for_approval(tmp_path):
    agent, skills = _agent(
        tmp_path,
        {
            "id": "call_1",
            "name": "codeexec",
            "arguments": {"language": "python", "code": "print('secret=sk-test-secret-1234')"},
        },
    )

    result = agent.chat("run this", session_id="s1")
    approvals = TaskStore(str(tmp_path)).list_approvals(status="pending")

    assert skills.executed == []
    assert result["tool_calls_executed"] == 0
    assert result["tool_calls_pending_approval"] == 1
    assert approvals[0]["action"] == "tool:codeexec"
    assert approvals[0]["risk"] == RISK_RISKY_WRITE
    assert "sk-test-secret-1234" not in str(approvals[0])
    assert "Approval required" in result["response"]


def test_agent_pauses_fileops_write_but_allows_fileops_read(tmp_path):
    read_file = tmp_path / "note.txt"
    read_file.write_text("hello", encoding="utf-8")
    write_agent, write_skills = _agent(
        tmp_path,
        {
            "id": "call_2",
            "name": "fileops",
            "arguments": {"action": "write", "path": str(tmp_path / "write.txt"), "content": "hello"},
        },
    )
    read_agent, read_skills = _agent(
        tmp_path,
        {
            "id": "call_3",
            "name": "fileops",
            "arguments": {"action": "read", "path": str(read_file)},
        },
    )

    write_result = write_agent.chat("write", session_id="s-write")
    read_result = read_agent.chat("read", session_id="s-read")

    assert write_skills.executed == []
    assert write_result["tool_calls_pending_approval"] == 1
    assert read_skills.executed == [("fileops", {"action": "read", "path": str(read_file)})]
    assert read_result["tool_calls_executed"] == 1
    assert "executed fileops" in read_result["response"]


def test_agent_allows_fileops_read_even_when_skill_metadata_is_mutating(tmp_path):
    read_file = tmp_path / "note.txt"
    read_file.write_text("hello", encoding="utf-8")
    agent, skills = _agent(
        tmp_path,
        {
            "id": "call_4",
            "name": "fileops",
            "arguments": {"action": "read", "path": str(read_file)},
        },
        listed_skills=[
            {
                "name": "fileops",
                "risk": {
                    "level": RISK_RISKY_WRITE,
                    "mutating": True,
                    "approval_required": True,
                },
            }
        ],
    )

    result = agent.chat("read", session_id="s-read-metadata")

    assert skills.executed == [("fileops", {"action": "read", "path": str(read_file)})]
    assert result["tool_calls_executed"] == 1
    assert result["tool_calls_pending_approval"] == 0


def test_agent_honors_skill_approval_metadata_for_registered_tools(tmp_path):
    agent, skills = _agent(
        tmp_path,
        {
            "id": "call_5",
            "name": "custom_mutator",
            "arguments": {"target": "workspace"},
        },
        listed_skills=[
            {
                "name": "custom_mutator",
                "risk": {
                    "level": RISK_RISKY_WRITE,
                    "mutating": True,
                    "approval_required": True,
                },
            }
        ],
    )

    result = agent.chat("mutate workspace", session_id="s-custom")
    approvals = TaskStore(str(tmp_path)).list_approvals(status="pending")

    assert skills.executed == []
    assert result["tool_calls_executed"] == 0
    assert result["tool_calls_pending_approval"] == 1
    assert approvals[0]["action"] == "tool:custom_mutator"
    assert approvals[0]["risk"] == RISK_RISKY_WRITE
