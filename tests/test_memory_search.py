import json

from click.testing import CliRunner

from shaka import cli as cli_module
from shaka.config import DataPaths, ShakaConfig
from shaka.dashboard.app import create_app
from shaka.memory import MemoryManager


def test_memory_search_returns_fact_wiki_and_session_snippets(tmp_path):
    memory = MemoryManager(str(tmp_path))
    memory.add_fact("default", "Phoenix prefers deployment notes with exact commands.")
    memory.save_wiki_page("default", "Runbook", "The Phoenix runbook keeps dashboard recovery steps.")
    memory.save_session(
        "default",
        "session_1",
        [
            {"role": "user", "content": "Can you inspect the Phoenix dashboard?"},
            {"role": "assistant", "content": "The dashboard route is healthy."},
        ],
    )

    results = memory.search("default", "phoenix")

    result_types = {item["type"] for item in results}
    assert {"fact", "wiki", "session"}.issubset(result_types)
    assert all("phoenix" in item["snippet"].lower() for item in results)
    assert any(item["title"] == "Runbook" for item in results)
    assert any(item.get("session_id") == "session_1" for item in results)


def test_memory_search_redacts_secrets_from_snippets(tmp_path):
    memory = MemoryManager(str(tmp_path))
    memory.add_fact("default", "Phoenix token is sk-test-secret-1234 and should stay private.")
    memory.save_session(
        "default",
        "session_secret",
        [{"role": "user", "content": "Phoenix env uses SHAKA_API_KEY=super-secret-value"}],
    )

    results = memory.search("default", "phoenix")
    serialized = json.dumps(results)

    assert results
    assert "sk-test-secret-1234" not in serialized
    assert "super-secret-value" not in serialized
    assert "[redacted]" in serialized


def test_indexed_memory_search_returns_ranked_facts_wiki_and_session_messages(tmp_path):
    memory = MemoryManager(str(tmp_path))
    memory.add_fact("default", "Hermes recall should prioritize deployment runbooks.")
    memory.save_wiki_page(
        "default",
        "Deployment Runbook",
        "Hermes recall keeps recovery commands and deploy notes together.",
    )
    memory.save_session(
        "default",
        "deploy_chat",
        [
            {"role": "user", "content": "Please remember Hermes deployment evidence."},
            {"role": "assistant", "content": "The deployment evidence is now indexed."},
        ],
    )

    indexed = memory.index_memory("default")
    results = memory.search_memory("default", "Hermes deployment", limit=10)

    assert indexed >= 4
    assert [result["score"] for result in results] == sorted(
        [result["score"] for result in results],
        reverse=True,
    )
    assert {"fact", "wiki", "session"}.issubset({result["type"] for result in results})
    assert all({"type", "source", "text", "score"}.issubset(result) for result in results)
    assert any(result["source"] == "fact:1" for result in results)
    assert any(result["source"] == "wiki:Deployment Runbook" for result in results)
    assert any(result["source"] == "session:deploy_chat:0" for result in results)


def test_index_session_updates_sqlite_index_without_rewriting_json(tmp_path):
    memory = MemoryManager(str(tmp_path))
    memory.save_session(
        "default",
        "recall_chat",
        [
            {"role": "user", "content": "Atlas prefers local recall only."},
            {"role": "assistant", "content": "Local recall avoids cloud dependencies."},
        ],
    )

    indexed = memory.index_session("default", "recall_chat")
    reloaded = MemoryManager(str(tmp_path))
    results = reloaded.search_memory("default", "cloud dependencies")

    assert indexed == 2
    assert results
    assert results[0]["type"] == "session"
    assert results[0]["source"] == "session:recall_chat:1"
    assert "cloud dependencies" in results[0]["text"].lower()


def test_memory_search_cli_and_dashboard_route(tmp_path, monkeypatch):
    config = ShakaConfig(paths=DataPaths(base_dir=str(tmp_path)))
    monkeypatch.setattr(cli_module, "load_config", lambda _=None: config)
    memory = MemoryManager(str(tmp_path))
    memory.add_fact("default", "Hermes style recall needs local evidence.")

    cli_result = CliRunner().invoke(cli_module.cli, ["memory", "search", "Hermes", "--json"])
    app = create_app(config=config)
    api_result = app.test_client().get("/api/memory/search", query_string={"q": "Hermes"})

    assert cli_result.exit_code == 0, cli_result.output
    assert json.loads(cli_result.output)[0]["type"] == "fact"
    assert api_result.status_code == 200
    assert api_result.get_json()[0]["source"] == "fact:1"
