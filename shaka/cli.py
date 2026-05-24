"""CLI Interface for Shaka.

Commands:
  shaka init      - Initialize configuration
  shaka run       - Start interactive chat session
  shaka ask       - Send a single message and get response
  shaka skills    - List/manage skills
  shaka memory    - View/clear memory
  shaka doctor    - System health check
  shaka dashboard - Start web dashboard
"""

import os
import sys
import asyncio
import uuid
import click
import json
import time
import subprocess
import shlex
import re
from pathlib import Path

# Ensure the parent directory is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shaka.config import load_config, create_default_config
from shaka.skills import SkillsRegistry
from shaka.memory import MemoryManager, SessionDB
from shaka.agent import Agent
from shaka.code_workflow import RepoContextBuilder
from shaka.connectors import collect_connector_context
from shaka.mcp_runtime import inspect_stdio_server, run_server
from shaka.credentials import CredentialStore
from shaka.cron import CronStore
from shaka.daemon import DaemonManager
from shaka.local_state import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    ensure_local_state,
    get_gateway_token,
    install_skill,
)
from shaka.providers import get_provider_spec, is_model_configured, provider_catalog, provider_names
from shaka.i18n import gettext as _
from shaka.tui import ShakaTUI
from shaka.ui_textual import NeonTextualApp, TEXTUAL_AVAILABLE

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version='0.1.0', prog_name='Shaka')
@click.option('--config', '-c', default=None, help='Path to config file')
@click.pass_context
def cli(ctx, config):
    """Shaka - South African AI developer agent

    Commands:
      shaka init      - Initialize configuration
      shaka run       - Start interactive chat session (default: Textual UI)
      shaka run --no-textual  - Start with Rich TUI fallback
      shaka run --raw - Plain text mode
      shaka ask       - Send a single message and get response
      shaka skills    - List/manage local skills
      shaka memory    - View/clear memory
      shaka doctor    - System health check
      shaka onboard   - First-time setup wizard
      shaka gateway   - Authenticated localhost control plane
      shaka dev       - One-command local startup
      shaka proof     - Export portfolio proof of local runtime state
      shaka daemon    - Background local gateway process
      shaka credentials - Manage local provider credentials
      shaka personality - Customize personality
      shaka code      - Coding mode for repo work
      shaka tui       - Start Rich TUI
      shaka mcp serve - Run as MCP server
    """
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config
    ctx.obj['config'] = load_config(config)
    
    # Load translations based on config language
    from shaka.i18n import load_translations
    load_translations(ctx.obj["config"].language)

@cli.command()
@click.option("--home", default=None, help="Local Shaka home directory")
@click.option("--legacy-yaml/--local-json", default=False, help="Create legacy ./config.yaml instead of ~/.shaka/config.json")
def init(home, legacy_yaml):
    """Initialize Shaka local configuration."""
    if legacy_yaml:
        config_path = os.path.join(os.getcwd(), "config.yaml")
        if os.path.exists(config_path):
            click.echo(_("Config already exists at: {}").format(config_path))
            click.echo(_("Edit it manually or run 'shaka doctor' to check it."))
            return
        create_default_config(config_path)
    else:
        local = ensure_local_state(home)
        config_path = local["_config_path"]

    click.echo("=" * 50)
    click.echo(_("  SHAKA - South African AI Developer Agent"))
    click.echo(_("  Built in South Africa, for the world."))
    click.echo("=" * 50)
    click.echo("")
    click.echo(f"Created: {config_path}")
    click.echo("")
    click.echo(_("To get started:"))
    click.echo(_("  1. Get an API key:"))
    click.echo(_("     - Groq (free): https://console.groq.com/keys"))
    click.echo(_("     - Gemini (free): https://aistudio.google.com/apikey"))
    click.echo(_(f"  2. Set {DEFAULT_API_KEY_ENV}=your_key_here or use Ollama"))
    click.echo("  3. Run 'shaka gateway' for the local control plane")
    click.echo("  4. Run 'shaka doctor' to verify everything")
    click.echo("")

@cli.command()
@click.argument('message', nargs=-1)
@click.option('--session', '-s', default=None, help='Session ID (auto-generated if not provided)')
@click.pass_context
def ask(ctx, message, session):
    """Send a message to Shaka and get a response."""
    if not message:
        click.echo("Usage: shaka ask 'your message here'")
        return

    message_text = ' '.join(message)
    config = ctx.obj['config']

    if not is_model_configured(config):
        click.echo(_("ERROR: No API key configured."))
        click.echo(_(f"Set {config.model.api_key_env or DEFAULT_API_KEY_ENV}, run `shaka credentials set {config.model.provider}`, or use Ollama."))
        return

    memory = MemoryManager(config.paths.base_dir)
    skills = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(__file__), "skills_core")
    skills.load_core_skills(core_skills_dir)

    agent = Agent(config, skills, memory)
    
    click.echo(f"Shaka: Thinking...")
    start = time.time()
    result = agent.chat(message_text, session_id=session)
    elapsed = time.time() - start

    click.echo("")
    click.echo(f"Shaka: {result['response']}")
    click.echo("")
    click.echo(f"[Tokens: {result['tokens_used']} | Time: {result['elapsed_seconds']}s]")
    if result.get("tool_calls_executed"):
        click.echo(f"[Tools used: {result['tool_calls_executed']}]")
    click.echo(f"[Session: {result['session_id']}]")

@cli.command()
@click.option('--textual/--no-textual', default=True, help='Use Textual UI (default: True)')
@click.option('--raw/--no-raw', default=False, help='Use plain text mode')
@click.pass_context
def run(ctx, textual, raw):
    """Start interactive chat session with Shaka."""
    config = ctx.obj['config']

    if not is_model_configured(config):
        click.echo(_("ERROR: No API key configured."))
        click.echo(_(f"Set {config.model.api_key_env or DEFAULT_API_KEY_ENV}, run `shaka credentials set {config.model.provider}`, or use Ollama."))
        return

    memory = MemoryManager(config.paths.base_dir)
    session_db = SessionDB(config.paths.db_path)
    skills = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(__file__), "skills_core")
    skills.load_core_skills(core_skills_dir)

    agent = Agent(config, skills, memory)

    if raw:
        session_id = f"session_{int(time.time())}"
        click.echo("=" * 60)
        click.echo(_("  SHAKA - Interactive Mode (Plain Text)"))
        click.echo("  Type 'quit' or 'exit' to stop")
        click.echo("  Type 'clear' to clear session")
        click.echo("  Type 'memory' to view stored memories")
        click.echo("  Type 'skills' to list skills")
        click.echo("=" * 60)
        click.echo("")

        try:
            while True:
                user_input = click.prompt("You", prompt_suffix="> ")
                user_input = user_input.strip()
                if not user_input:
                    continue
                if user_input.lower() in ('quit', 'exit', 'q'):
                    click.echo(_("Shaka: See you later!"))
                    break
                if user_input.lower() == 'clear':
                    agent.session_messages = []
                    session_id = f"session_{int(time.time())}"
                    click.echo(_("Session cleared."))
                    continue
                if user_input.lower() == 'memory':
                    facts = memory.get_facts("default")
                    if facts:
                        click.echo(_("\nStored memories:"))
                        for f in facts:
                            click.echo(f"  - {f.get('text', f) if isinstance(f, dict) else f}")
                    else:
                        click.echo(_("No memories stored yet."))
                    continue
                if user_input.lower() == 'skills':
                    skill_list = skills.list_skills()
                    click.echo(_("\nAvailable skills:"))
                    for s in skill_list:
                        click.echo(f"  - {s['name']}: {s['description']}")
                    continue
                result = agent.chat(user_input, session_id=session_id)
                click.echo(f"\nShaka: {result['response']}")
                click.echo(f"[Session: {result['session_id']} | Tokens: {result['tokens_used']} | {result['elapsed_seconds']}s]")
                if result.get("tool_calls_executed"):
                    click.echo(f"[Tools used: {result['tool_calls_executed']}]")
                click.echo("")
        except KeyboardInterrupt:
            click.echo(_("\n\nShaka: Interrupted. Goodbye!"))
            return
        except Exception as e:
            click.echo(f"\nError: {e}")
            click.echo("Run 'shaka doctor' to diagnose issues.")
        return

    if textual and TEXTUAL_AVAILABLE:
        tui_instance = NeonTextualApp(agent, config)
        tui_instance.run()
    else:
        if textual and not TEXTUAL_AVAILABLE:
            click.echo(_("Textual not available. Falling back to Rich TUI..."))
        tui_instance = ShakaTUI(agent, config)
        tui_instance.run()

def _load_cli_skills(config):
    skills_registry = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(__file__), "skills_core")
    skills_registry.load_core_skills(core_skills_dir)
    skills_registry.load_user_skills(config.paths.skills_dir)
    return skills_registry


def _print_skills(skills_registry: SkillsRegistry) -> None:
    click.echo(_("Available Skills:"))
    click.echo("-" * 50)

    for skill in skills_registry.list_skills():
        click.echo(f"  {skill['name']}")
        click.echo(f"    {skill['description']}")
        triggers = ', '.join(skill.get('triggers', []))
        if triggers:
            click.echo(f"    Triggers: {triggers}")
        click.echo("")


@cli.group(invoke_without_command=True)
@click.pass_context
def skills(ctx):
    """List and install local skills."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(skills_list)


@skills.command("list")
@click.pass_context
def skills_list(ctx):
    """List core and user-installed skills."""
    _print_skills(_load_cli_skills(ctx.obj["config"]))


@skills.command("install")
@click.argument("source")
@click.pass_context
def skills_install(ctx, source):
    """Install a local skill directory into ~/.shaka/skills."""
    try:
        target = install_skill(source, ctx.obj["config"])
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Installed skill: {target}")

def _print_memory_summary(config):
    memory = MemoryManager(config.paths.base_dir)

    user_mem = memory.load_memory("default")
    facts = user_mem.get("facts", [])

    click.echo(_("Stored Memories:"))
    click.echo("-" * 50)

    if facts:
        for i, fact in enumerate(facts):
            if isinstance(fact, dict):
                click.echo(f"  {i+1}. {fact.get('text', '')}")
            else:
                click.echo(f"  {i+1}. {fact}")
    else:
        click.echo(_("  (no memories yet)"))

    click.echo("")
    click.echo(f"Wiki pages: {', '.join(memory.get_wiki_pages('default')) or '(none)'}")
    sessions = memory.list_sessions("default")
    click.echo(f"Sessions: {len(sessions)}")


@cli.group(invoke_without_command=True)
@click.pass_context
def memory(ctx):
    """View and manage stored memories."""
    if ctx.invoked_subcommand is None:
        _print_memory_summary(ctx.obj["config"])


@memory.command("search")
@click.argument("query")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--index/--no-index", default=True, show_default=True, help="Refresh the local recall index before searching")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON results")
@click.pass_context
def memory_search(ctx, query, limit, index, as_json):
    """Search local facts, wiki pages, and session transcripts."""
    memory_manager = MemoryManager(ctx.obj["config"].paths.base_dir)
    if index:
        memory_manager.index_memory("default")
    results = memory_manager.search_memory("default", query, limit=limit)
    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    if not results:
        click.echo("No memory matches.")
        return
    for item in results:
        click.echo(f"{item['type']}  {item['source']}  score={item['score']}")
        click.echo(f"  {item['text']}")


@cli.group()
def credentials():
    """Manage local provider credentials."""


@credentials.command("set")
@click.argument("provider")
@click.option("--value", default=None, help="Secret value. If omitted, Shaka prompts without echo.")
@click.option("--label", default="api_key", show_default=True, help="Credential label")
@click.pass_context
def credentials_set(ctx, provider, value, label):
    """Store a provider credential under ~/.shaka/credentials."""
    secret = value
    if secret is None:
        secret = click.prompt("Credential value", hide_input=True, confirmation_prompt=True)
    try:
        record = CredentialStore(ctx.obj["config"].paths.base_dir).set(provider, secret, label=label)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Stored credential for {record['provider']}: {record['fingerprint']}")
    click.echo(f"Path: {record['path']}")


@credentials.command("list")
@click.pass_context
def credentials_list(ctx):
    """List configured local credentials without printing secret values."""
    records = CredentialStore(ctx.obj["config"].paths.base_dir).list()
    if not records:
        click.echo("No local credentials configured.")
        return
    for record in records:
        click.echo(f"{record['provider']}  {record['label']}  {record['fingerprint']}  {record['updated_at']}")


@credentials.command("delete")
@click.argument("provider")
@click.pass_context
def credentials_delete(ctx, provider):
    """Delete a local provider credential."""
    deleted = CredentialStore(ctx.obj["config"].paths.base_dir).delete(provider)
    if deleted:
        click.echo(f"Deleted credential for {provider.lower()}.")
    else:
        click.echo(f"No credential found for {provider.lower()}.")


@cli.group()
def providers():
    """List and configure model providers."""


@providers.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print provider catalog as JSON")
def providers_list(as_json):
    """List supported local/BYOK model providers."""
    catalog = provider_catalog()
    if as_json:
        click.echo(json.dumps(catalog, indent=2))
        return
    for item in catalog:
        key_hint = item["api_key_env"] or "(none)"
        click.echo(f"{item['name']}  {item['default_model']}  env={key_hint}  mode={item['mode']}")


@providers.command("configure")
@click.argument("provider", type=click.Choice(provider_names(), case_sensitive=False))
@click.option("--model", default=None, help="Model name")
@click.option("--api-key-env", default=None, help="Provider API key environment variable")
@click.option("--base-url", default=None, help="Override provider base URL")
@click.option("--home", default=None, help="Local Shaka home directory")
@click.pass_context
def providers_configure(ctx, provider, model, api_key_env, base_url, home):
    """Set the default provider in ~/.shaka/config.json without storing secrets."""
    from shaka.local_state import load_local_config_data, save_local_config_data

    spec = get_provider_spec(provider)
    root = home or ctx.obj["config"].paths.base_dir
    ensure_local_state(root)
    data = load_local_config_data(root)
    data.setdefault("model", {})
    data["model"]["provider"] = spec.name
    data["model"]["model"] = model or spec.default_model
    data["model"]["api_key_env"] = api_key_env or spec.api_key_env or DEFAULT_API_KEY_ENV
    data["model"]["base_url"] = base_url if base_url is not None else spec.base_url
    data["model"].pop("api_key", None)
    path = save_local_config_data(data, root)
    click.echo(f"Configured provider: {spec.name} / {data['model']['model']}")
    if spec.requires_api_key:
        click.echo(f"API key source: {data['model']['api_key_env']} or shaka credentials set {spec.name}")
    else:
        click.echo("API key source: not required")
    click.echo(f"Config: {path}")


@providers.command("status")
@click.pass_context
def providers_status(ctx):
    """Show active provider status without printing secrets."""
    from shaka.local_state import provider_status

    click.echo(json.dumps(provider_status(ctx.obj["config"]), indent=2))


@cli.group()
def cron():
    """Manage local-first scheduled jobs."""


@cron.command("add")
@click.argument("name")
@click.option("--schedule", required=True, help="Schedule: @every 5m, @hourly, @daily, */5 * * * *")
@click.option("--command", "command_text", required=True, help="Allowlisted command to run")
@click.option("--cwd", default=".", show_default=True, help="Working directory")
@click.option("--disabled/--enabled", default=False, show_default=True, help="Create job disabled")
@click.pass_context
def cron_add(ctx, name, schedule, command_text, cwd, disabled):
    """Add a local scheduled job."""
    try:
        job = CronStore(ctx.obj["config"].paths.base_dir).add_job(
            name,
            schedule,
            command_text,
            cwd=cwd,
            enabled=not disabled,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Added cron job {job['id']}: {job['name']}")
    click.echo(f"Next run: {job['next_run_at']}")


@cron.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print jobs as JSON")
@click.pass_context
def cron_list(ctx, as_json):
    """List local scheduled jobs."""
    jobs = CronStore(ctx.obj["config"].paths.base_dir).list_jobs()
    if as_json:
        click.echo(json.dumps(jobs, indent=2))
        return
    if not jobs:
        click.echo("No cron jobs configured.")
        return
    for job in jobs:
        state = "enabled" if job.get("enabled", True) else "disabled"
        click.echo(f"{job['id']}  {state}  {job['schedule']}  next={job['next_run_at']}  {job['name']}")
        click.echo(f"  {job['command']}")


@cron.command("remove")
@click.argument("job_id")
@click.pass_context
def cron_remove(ctx, job_id):
    """Remove a local scheduled job."""
    deleted = CronStore(ctx.obj["config"].paths.base_dir).delete_job(job_id)
    click.echo(f"Removed {job_id}." if deleted else f"No cron job found: {job_id}")


@cron.command("run")
@click.argument("job_id")
@click.option("--dry-run/--execute", default=False, show_default=True, help="Record without executing")
@click.option("--timeout", "timeout_seconds", default=120, show_default=True, type=int)
@click.pass_context
def cron_run(ctx, job_id, dry_run, timeout_seconds):
    """Run a scheduled job now."""
    try:
        result = CronStore(ctx.obj["config"].paths.base_dir).run_job(
            job_id,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )
    except KeyError as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    label = "Dry run" if dry_run else "Run"
    click.echo(f"{label} {result['status']}: {result['task']['id']}")


@cron.command("tick")
@click.option("--dry-run/--execute", default=False, show_default=True, help="Record due jobs without executing")
@click.pass_context
def cron_tick(ctx, dry_run):
    """Run all due enabled jobs once."""
    result = CronStore(ctx.obj["config"].paths.base_dir).tick(dry_run=dry_run)
    click.echo(json.dumps(result, indent=2))


@cli.group()
def daemon():
    """Manage the background local gateway process."""


@daemon.command("install")
@click.option('--host', default=DEFAULT_GATEWAY_HOST, show_default=True, help='Gateway bind host')
@click.option('--port', default=DEFAULT_GATEWAY_PORT, show_default=True, type=int, help='Gateway port')
@click.pass_context
def daemon_install(ctx, host, port):
    """Write local daemon metadata and startup command."""
    ensure_local_state(ctx.obj["config"].paths.base_dir, host=host, port=port)
    result = DaemonManager(ctx.obj["config"].paths.base_dir).install(host=host, port=port)
    click.echo("Daemon metadata installed.")
    click.echo(f"Command: {' '.join(result['command'])}")


@daemon.command("start")
@click.option('--host', default=DEFAULT_GATEWAY_HOST, show_default=True, help='Gateway bind host')
@click.option('--port', default=DEFAULT_GATEWAY_PORT, show_default=True, type=int, help='Gateway port')
@click.pass_context
def daemon_start(ctx, host, port):
    """Start Shaka gateway in the background."""
    ensure_local_state(ctx.obj["config"].paths.base_dir, host=host, port=port)
    result = DaemonManager(ctx.obj["config"].paths.base_dir).start(host=host, port=port)
    click.echo(f"Daemon running: {result['running']}")
    click.echo(f"PID: {result.get('pid', 0)}")
    click.echo(f"Gateway: http://{result.get('host', host)}:{result.get('port', port)}")
    if result.get("stdout"):
        click.echo(f"Logs: {result['stdout']}")


@daemon.command("stop")
@click.pass_context
def daemon_stop(ctx):
    """Stop the background Shaka gateway process."""
    result = DaemonManager(ctx.obj["config"].paths.base_dir).stop()
    click.echo(f"Daemon running: {result['running']}")
    if result.get("stopped_at"):
        click.echo(f"Stopped at: {result['stopped_at']}")


@daemon.command("status")
@click.pass_context
def daemon_status(ctx):
    """Show background gateway status."""
    result = DaemonManager(ctx.obj["config"].paths.base_dir).status()
    click.echo(json.dumps(result, indent=2))


@daemon.command("restart")
@click.option('--host', default=DEFAULT_GATEWAY_HOST, show_default=True, help='Gateway bind host')
@click.option('--port', default=DEFAULT_GATEWAY_PORT, show_default=True, type=int, help='Gateway port')
@click.pass_context
def daemon_restart(ctx, host, port):
    """Restart the background Shaka gateway process."""
    manager = DaemonManager(ctx.obj["config"].paths.base_dir)
    manager.stop()
    result = manager.start(host=host, port=port)
    click.echo(f"Daemon running: {result['running']}")
    click.echo(f"PID: {result.get('pid', 0)}")


@cli.group("repo-memory")
def repo_memory_command():
    """Inspect and update repo-specific developer memory."""


@repo_memory_command.command("show")
@click.option("--path", "repo_path", default=".", show_default=True, help="Repository path")
@click.pass_context
def repo_memory_show(ctx, repo_path):
    """Show memory for a repository."""
    from shaka.repo_memory import RepoMemory

    memory = RepoMemory(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(memory.load(repo_path), indent=2))


@repo_memory_command.command("command")
@click.argument("command_text")
@click.option("--result", default="", help="Command outcome or note")
@click.option("--path", "repo_path", default=".", show_default=True, help="Repository path")
@click.pass_context
def repo_memory_remember_command(ctx, command_text, result, repo_path):
    """Remember a command that worked or failed in this repo."""
    from shaka.repo_memory import RepoMemory

    memory = RepoMemory(ctx.obj["config"].paths.base_dir)
    saved = memory.remember_command(repo_path, command_text, result)
    click.echo(f"Remembered command for {saved['repo_path']}.")


@repo_memory_command.command("decision")
@click.argument("decision")
@click.option("--path", "repo_path", default=".", show_default=True, help="Repository path")
@click.pass_context
def repo_memory_remember_decision(ctx, decision, repo_path):
    """Remember an architectural or workflow decision for this repo."""
    from shaka.repo_memory import RepoMemory

    memory = RepoMemory(ctx.obj["config"].paths.base_dir)
    saved = memory.remember_decision(repo_path, decision)
    click.echo(f"Remembered decision for {saved['repo_path']}.")

@cli.command()
@click.option('--preset', default=None, help='Set a named personality preset for the default user')
@click.option('--set', 'set_value', default=None, help='Set a custom personality preference for the default user')
@click.option('--list/--no-list', 'show_list', default=False, show_default=True, help='Show available presets')
@click.pass_context
def personality(ctx, preset, set_value, show_list):
    """View or set the current user's personality."""
    config = ctx.obj['config']
    memory = MemoryManager(config.paths.base_dir)
    prefs = memory.get_preferences("default")
    presets = _personality_catalog(config)

    if preset:
        if preset not in presets:
            click.echo(_("Unknown personality preset."))
            click.echo(f"Available presets: {', '.join(sorted(presets)) or '(none)'}")
            return
        _set_personality_value(memory, "default", preset=preset)
        click.echo(_("Personality preset updated."))
        click.echo(f"{preset}: {presets[preset]}")
        return

    if set_value:
        _set_personality_value(memory, "default", custom=set_value)
        click.echo(_("Personality updated."))
        click.echo(f"{set_value}")
        return

    current_preset = prefs.get("personality_preset", "(not set)")
    current_custom = prefs.get("personality_custom") or prefs.get("personality", "(not set)")
    click.echo(_("Current personality preference:"))
    click.echo(f"  preset: {current_preset}")
    click.echo(f"  custom: {current_custom}")
    click.echo("")
    if show_list:
        click.echo(_("Available presets:"))
        for name, description in presets.items():
            click.echo(f"  - {name}: {description}")
        click.echo("")
    click.echo(_("Examples:"))
    click.echo("  shaka personality --preset technical")
    click.echo("  shaka personality --set \"warm and concise\"")


@cli.command()
@click.option('--provider', default=None, type=click.Choice(provider_names(), case_sensitive=False), help='Model provider')
@click.option('--model', default=None, help='Model name')
@click.option('--api-key-env', default=DEFAULT_API_KEY_ENV, show_default=True, help='Environment variable that holds the provider API key')
@click.option('--host', default=DEFAULT_GATEWAY_HOST, show_default=True, help='Gateway bind host')
@click.option('--port', default=DEFAULT_GATEWAY_PORT, show_default=True, type=int, help='Gateway port')
@click.option('--home', default=None, help='Local Shaka home directory')
@click.option('--rotate-token/--keep-token', default=False, show_default=True, help='Rotate the local gateway token')
@click.option('--yes', 'assume_yes', is_flag=True, help='Use defaults without interactive prompts')
@click.option('--show-token/--hide-token', default=False, show_default=True, help='Print the generated local gateway token')
@click.option('--complete/--no-complete', default=False, show_default=True, help='Mark onboarding as completed')
@click.pass_context
def onboard(ctx, provider, model, api_key_env, host, port, home, rotate_token, assume_yes, show_token, complete):
    """Run the local-first onboarding wizard."""
    interactive = sys.stdin.isatty() and not assume_yes
    if interactive:
        provider = click.prompt(
            "Model provider",
            default=provider or ctx.obj["config"].model.provider,
            type=click.Choice(provider_names(), case_sensitive=False),
        )
        selected_spec = get_provider_spec(provider)
        default_model = model or selected_spec.default_model or ctx.obj["config"].model.model
        model = click.prompt("Model", default=default_model)
        api_key_env = click.prompt("API key environment variable", default=api_key_env or selected_spec.api_key_env or DEFAULT_API_KEY_ENV)
        host = click.prompt("Gateway bind host", default=host)
        port = click.prompt("Gateway port", default=port, type=int)

    local = ensure_local_state(
        home or ctx.obj["config"].paths.base_dir,
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        host=host,
        port=port,
        rotate_token=rotate_token,
    )
    config = load_config(local["_config_path"])
    ctx.obj["config"] = config
    memory = MemoryManager(config.paths.base_dir)
    click.echo(_format_onboarding_steps(config, memory))
    click.echo("")
    click.echo("Local state initialized:")
    click.echo(f"  Home: {config.paths.base_dir}")
    click.echo(f"  Config: {local['_config_path']}")
    click.echo(f"  Workspace: {Path(config.paths.base_dir).expanduser() / 'workspace'}")
    click.echo(f"  Gateway: http://{config.dashboard.host}:{config.dashboard.port}")
    click.echo(f"  Provider: {config.model.provider} / {config.model.model}")
    if not is_model_configured(config):
        click.echo(f"  API key: set {config.model.api_key_env or api_key_env}=your_key_here or run `shaka credentials set {config.model.provider}`")
    else:
        click.echo("  API key: configured through environment or not required")
    if show_token:
        click.echo(f"  Gateway token: {local['gateway']['token']}")
    click.echo("")
    click.echo("Next commands:")
    click.echo("  shaka doctor")
    click.echo(f"  shaka gateway --port {config.dashboard.port}")
    click.echo(f"  shaka build-site \"local portfolio demo\" --path \"{Path(config.paths.base_dir).expanduser() / 'workspace' / 'portfolio-demo'}\"")
    if complete:
        memory.set_preference("default", "onboarding_completed", True)
        click.echo("")
        click.echo(_("Onboarding marked as completed."))

@cli.command()
@click.pass_context
def doctor(ctx):
    """Check system health and configuration."""
    config = ctx.obj['config']

    click.echo(_("SHAKA SYSTEM CHECK"))
    click.echo("=" * 50)
    click.echo("")

    # Config check
    click.echo("[Config] ", nl=False)
    if is_model_configured(config):
        click.echo(_("OK - Model configured"))
    else:
        click.echo(_(f"WARNING - Provider key missing. Set {config.model.api_key_env or DEFAULT_API_KEY_ENV}, use local credentials, or switch to Ollama"))

    # Model provider
    click.echo(f"  Provider: {config.model.provider}")
    click.echo(f"  Model: {config.model.model}")
    click.echo(f"  API Key Env: {config.model.api_key_env or DEFAULT_API_KEY_ENV}")
    if config.model.api_key:
        click.echo(f"  API Key: {'*' * 8}{config.model.api_key[-4:]}")
    click.echo("")

    # Local credential check
    click.echo("[Credentials] ", nl=False)
    credential_records = CredentialStore(config.paths.base_dir).list()
    if credential_records:
        click.echo(f"OK - {len(credential_records)} local provider credential(s) configured")
        for record in credential_records:
            click.echo(f"  - {record['provider']}: {record['fingerprint']}")
    else:
        click.echo("OK - no local credential files configured")
    click.echo("")

    # Skills check
    click.echo("[Skills] ", nl=False)
    skills_registry = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(__file__), "skills_core")
    if os.path.exists(core_skills_dir):
        skills_registry.load_core_skills(core_skills_dir)
        count = len(skills_registry.list_skills())
        click.echo(f"OK - {count} skills loaded")
    else:
        click.echo(_("ERROR - Core skills directory not found"))

    for skill in skills_registry.list_skills():
        click.echo(f"  - {skill['name']}")
    click.echo("")

    # Memory check
    click.echo("[Memory] ", nl=False)
    memory = MemoryManager(config.paths.base_dir)
    try:
        memory.load_memory("default")
        click.echo(_("OK - Memory system working"))
    except Exception as e:
        click.echo(f"ERROR - {e}")

    # Data dirs
    click.echo("[Data] ", nl=False)
    base_dir = config.paths.base_dir
    if os.path.exists(base_dir):
        click.echo(f"OK - {base_dir}")
    else:
        click.echo(f"WARNING - Data directory doesn't exist: {base_dir}")
    click.echo("")
    for label, directory in [
        ("Workspace", getattr(config.paths, "workspace_dir", os.path.join(base_dir, "workspace"))),
        ("Sessions", getattr(config.paths, "sessions_dir", os.path.join(base_dir, "sessions"))),
        ("Memory", getattr(config.paths, "memory_dir", os.path.join(base_dir, "memory"))),
        ("Skills", config.paths.skills_dir),
        ("Credentials", getattr(config.paths, "credentials_dir", os.path.join(base_dir, "credentials"))),
        ("Runtime", getattr(config.paths, "runtime_dir", os.path.join(base_dir, "runtime"))),
        ("Logs", getattr(config.paths, "logs_dir", os.path.join(base_dir, "logs"))),
    ]:
        click.echo(f"  {label}: {directory} {'OK' if os.path.exists(directory) else 'missing'}")
    click.echo("")

    # Gateway check
    click.echo("[Gateway] ", nl=False)
    try:
        token = get_gateway_token(base_dir)
        bind_status = "loopback" if config.dashboard.host in {"127.0.0.1", "localhost", "::1"} else "external"
        click.echo(f"OK - {config.dashboard.host}:{config.dashboard.port} ({bind_status}, token {'set' if token else 'missing'})")
    except Exception as e:
        click.echo(f"WARNING - {e}")
    click.echo("")

    # Python version
    click.echo(f"[Python] {sys.version}")

    click.echo("")
    click.echo(_("All checks complete."))

@cli.command()
@click.option('--host', default=None, help='Host to bind to')
@click.option('--port', default=None, type=int, help='Port to bind to')
@click.pass_context
def dashboard(ctx, host, port):
    """Start the web dashboard."""
    config = ctx.obj['config']
    selected_host = host or os.environ.get("SHAKA_HOST") or config.dashboard.host
    selected_port = port or int(os.environ.get("SHAKA_PORT") or config.dashboard.port)
    local = ensure_local_state(
        config.paths.base_dir,
        provider=config.model.provider,
        model=config.model.model,
        host=selected_host,
        port=selected_port,
    )
    config = load_config(local["_config_path"])
    config.dashboard.host = selected_host
    config.dashboard.port = selected_port
    ctx.obj["config"] = config
    token = local["gateway"]["token"]

    from shaka.dashboard.app import create_app

    app = create_app(ctx.obj.get('config_path'), config=config, gateway_token=token, require_token=True)
    click.echo(_("Starting Shaka Dashboard..."))
    click.echo(f"http://{config.dashboard.host}:{config.dashboard.port}/?token={token}")
    click.echo(f"Gateway token: {token}")

    try:
        from waitress import serve
    except ImportError:
        app.run(host=config.dashboard.host, port=config.dashboard.port, debug=False)
        return

    serve(app, host=config.dashboard.host, port=config.dashboard.port)


@cli.command()
@click.option('--host', default=None, help='Host to bind to; defaults to 127.0.0.1')
@click.option('--port', default=None, type=int, help='Port to bind to; defaults to 18789')
@click.option('--rotate-token/--keep-token', default=False, show_default=True, help='Rotate the local gateway token before starting')
@click.option('--show-token/--hide-token', default=True, show_default=True, help='Print the local gateway token')
@click.pass_context
def gateway(ctx, host, port, rotate_token, show_token):
    """Start the authenticated local gateway and dashboard."""
    config = ctx.obj['config']
    selected_host = host or os.environ.get("SHAKA_HOST") or config.dashboard.host or DEFAULT_GATEWAY_HOST
    selected_port = port or int(os.environ.get("SHAKA_PORT") or config.dashboard.port or DEFAULT_GATEWAY_PORT)
    local = ensure_local_state(
        config.paths.base_dir,
        provider=config.model.provider,
        model=config.model.model,
        host=selected_host,
        port=selected_port,
        rotate_token=rotate_token,
    )
    config = load_config(local["_config_path"])
    config.dashboard.host = selected_host
    config.dashboard.port = selected_port
    ctx.obj["config"] = config

    token = local["gateway"]["token"]
    from shaka.dashboard.app import create_app
    from shaka.daemon import DaemonManager

    app = create_app(ctx.obj.get('config_path'), config=config, gateway_token=token, require_token=True)
    click.echo(_("Starting Shaka Gateway..."))
    click.echo(f"http://{config.dashboard.host}:{config.dashboard.port}/?token={token}")
    if show_token:
        click.echo(f"Gateway token: {token}")
    click.echo(f"State: {config.paths.base_dir}")

    scheduler = DaemonManager(config.paths.base_dir).scheduler()
    scheduler.start()
    try:
        try:
            from waitress import serve
        except ImportError:
            app.run(host=config.dashboard.host, port=config.dashboard.port, debug=False)
            return

        serve(app, host=config.dashboard.host, port=config.dashboard.port)
    finally:
        scheduler.stop()


@cli.command()
@click.option('--port', default=DEFAULT_GATEWAY_PORT, show_default=True, type=int, help='Gateway port')
@click.pass_context
def dev(ctx, port):
    """One-command local startup for development."""
    ctx.invoke(gateway, host=DEFAULT_GATEWAY_HOST, port=port, rotate_token=False, show_token=True)


@cli.group()
def proof():
    """Export portfolio proof of local runtime state."""


@proof.command("export")
@click.option("--output", "-o", default=None, help="Markdown output path; defaults to ~/.shaka/runtime/proof.md")
@click.option("--json", "as_json", is_flag=True, help="Print secret-safe JSON instead of writing Markdown")
@click.pass_context
def proof_export(ctx, output, as_json):
    """Export a local-first runtime proof report."""
    from shaka.proof import ProofExporter

    exporter = ProofExporter(ctx.obj["config"])
    if as_json:
        click.echo(exporter.to_json())
        return

    path = exporter.export_markdown(output)
    click.echo(f"Proof report written: {path}")


@cli.command("tasks")
@click.option("--status", default=None, help="Filter by task status")
@click.option("--json", "as_json", is_flag=True, help="Print raw task records as JSON")
@click.pass_context
def tasks_command(ctx, status, as_json):
    """List automation tasks."""
    from shaka.automation import TaskStore

    store = TaskStore(ctx.obj["config"].paths.base_dir)
    try:
        tasks = store.list_tasks(status=status)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(tasks, indent=2))
        return
    if not tasks:
        click.echo("No tasks found.")
        return
    for task in tasks:
        click.echo(f"{task['id']}  {task['status']}  {task['kind']}  {task['title']}")
        if task.get("summary"):
            click.echo(f"  {task['summary']}")


@cli.command("approve")
@click.argument("approval_id")
@click.pass_context
def approve_command(ctx, approval_id):
    """Approve a pending automation action."""
    from shaka.automation import TaskStore

    store = TaskStore(ctx.obj["config"].paths.base_dir)
    try:
        approval = store.approve(approval_id)
    except KeyError as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    click.echo(f"Approved {approval['id']} for task {approval['task_id']}.")


@cli.command("reject")
@click.argument("approval_id")
@click.option("--reason", default="", help="Reason shown in task history")
@click.pass_context
def reject_command(ctx, approval_id, reason):
    """Reject a pending automation action."""
    from shaka.automation import TaskStore

    store = TaskStore(ctx.obj["config"].paths.base_dir)
    try:
        approval = store.reject_approval(approval_id, reason=reason)
    except KeyError as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    click.echo(f"Rejected {approval['id']} for task {approval['task_id']}.")


@cli.command("cancel")
@click.argument("task_id")
@click.pass_context
def cancel_command(ctx, task_id):
    """Cancel an automation task."""
    from shaka.automation import TaskStore

    store = TaskStore(ctx.obj["config"].paths.base_dir)
    try:
        task = store.cancel_task(task_id)
    except KeyError as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    click.echo(f"Cancelled {task['id']}.")


@cli.command("retry")
@click.argument("task_id")
@click.pass_context
def retry_command(ctx, task_id):
    """Retry a failed or cancelled automation task."""
    from shaka.automation import TaskStore

    store = TaskStore(ctx.obj["config"].paths.base_dir)
    try:
        task = store.retry_task(task_id)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    click.echo(f"Retried {task['id']} and moved it to {task['status']}.")


@cli.group()
def email():
    """Gmail workflows with approval-gated sends."""


@email.command("setup")
@click.pass_context
def email_setup(ctx):
    """Show Gmail setup instructions."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.setup_instructions(), indent=2))


@email.command("status")
@click.pass_context
def email_status(ctx):
    """Show Gmail connector status."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.connection_status(), indent=2))


@email.command("revoke")
@click.pass_context
def email_revoke(ctx):
    """Remove locally stored Gmail token state."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.revoke(), indent=2))


@email.command("search")
@click.argument("query", required=False, default="")
@click.option("--limit", default=10, show_default=True, type=int)
@click.pass_context
def email_search(ctx, query, limit):
    """Search locally cached Gmail messages."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.search(query=query, limit=limit), indent=2))


@email.command("sync")
@click.argument("query", required=False, default="")
@click.option("--limit", default=10, show_default=True, type=int)
@click.pass_context
def email_sync(ctx, query, limit):
    """Sync or refresh Gmail snapshot data."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.sync_snapshot(query=query, limit=limit), indent=2))


@email.command("thread")
@click.argument("thread_id")
@click.pass_context
def email_thread(ctx, thread_id):
    """Fetch a Gmail thread from the connector or local snapshot."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.fetch_thread(thread_id), indent=2))


@email.command("summarize")
@click.argument("query", required=False, default="")
@click.option("--limit", default=10, show_default=True, type=int)
@click.pass_context
def email_summarize(ctx, query, limit):
    """Summarize locally cached Gmail messages."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(gmail.summarize(query=query, limit=limit), indent=2))


@email.command("draft")
@click.option("--to", "to_addr", required=True, help="Recipient email address")
@click.option("--subject", required=True, help="Email subject")
@click.option("--body", required=True, help="Email body")
@click.option("--thread-id", default="", help="Gmail thread ID")
@click.pass_context
def email_draft(ctx, to_addr, subject, body, thread_id):
    """Create an approval-gated Gmail reply draft."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    result = gmail.draft_reply(to_addr, subject, body, thread_id=thread_id)
    click.echo(f"Draft created for {to_addr}.")
    click.echo(f"Task: {result['task']['id']}")
    click.echo(f"Approval: {result['approval']['id']}")


@email.command("send")
@click.option("--approval-id", required=True, help="Approved approval ID or its task ID")
@click.pass_context
def email_send(ctx, approval_id):
    """Send a previously approved Gmail draft."""
    from shaka.email_runtime import GmailRuntime

    gmail = GmailRuntime(ctx.obj["config"].paths.base_dir)
    try:
        sent = gmail.send_approved(approval_id)
    except KeyError as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    except PermissionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Email send recorded: {sent['id']} to {sent['to']}")


@cli.command("build-site")
@click.argument("prompt", nargs=-1, required=True)
@click.option("--path", "target_path", default="shaka-built-site", show_default=True, help="Target directory")
@click.pass_context
def build_site_command(ctx, prompt, target_path):
    """Build a full-stack website scaffold."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    task = builder.build_site(" ".join(prompt).strip(), target_path)
    click.echo(f"{task['status']}: {task['summary']}")
    click.echo(f"Task: {task['id']}")
    click.echo(f"Path: {Path(target_path).expanduser().resolve()}")


@cli.group()
def demo():
    """Create local portfolio proof workflows."""


@demo.command("local-project")
@click.option("--path", "target_path", default=None, help="Target directory under the Shaka workspace")
@click.option("--json", "as_json", is_flag=True, help="Print demo records as JSON")
@click.pass_context
def demo_local_project(ctx, target_path, as_json):
    """Create, inspect, and queue a local demo project workflow."""
    from shaka.website_builder import WebsiteBuilder

    config = ctx.obj["config"]
    ensure_local_state(config.paths.base_dir)
    workspace = Path(getattr(config.paths, "workspace_dir", Path(config.paths.base_dir) / "workspace")).expanduser()
    target = Path(target_path).expanduser() if target_path else workspace / "portfolio-demo"
    builder = WebsiteBuilder(config.paths.base_dir)
    build = builder.build_site("local portfolio demo for an AI-native developer", str(target))
    inspect_result = builder.inspect_project(str(target))
    workflow = builder.create_check_workflow(str(target))
    result = {
        "workspace": str(workspace),
        "path": str(target.resolve()),
        "build": build,
        "inspect": inspect_result,
        "workflow": workflow,
    }
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo("Local project demo created.")
    click.echo(f"Path: {result['path']}")
    click.echo(f"Build task: {build['id']} ({build['status']})")
    click.echo(f"Workflow task: {workflow['id']} ({workflow['status']})")
    if workflow.get("steps"):
        approval_id = workflow["steps"][-1].get("metadata", {}).get("approval_id")
        if approval_id:
            click.echo(f"Approval: {approval_id}")
            click.echo(f"Next: shaka approve {approval_id}")
            click.echo(f"Then: shaka web resume {workflow['id']}")


@cli.group()
def web():
    """Browser and web verification workflows."""


@web.command("verify")
@click.option("--url", required=True, help="URL to verify")
@click.option("--browser/--no-browser", default=False, show_default=True, help="Use Playwright if installed")
@click.pass_context
def web_verify(ctx, url, browser):
    """Verify a website or local app."""
    from shaka.web_runtime import WebVerifier

    verifier = WebVerifier(ctx.obj["config"].paths.base_dir)
    result = verifier.verify(url, use_browser=browser)
    click.echo(json.dumps(result, indent=2))


@web.command("screenshot")
@click.option("--url", required=True, help="URL to capture")
@click.pass_context
def web_screenshot(ctx, url):
    """Capture a browser screenshot with Playwright."""
    from shaka.web_runtime import WebVerifier

    verifier = WebVerifier(ctx.obj["config"].paths.base_dir)
    result = verifier.screenshot(url)
    click.echo(json.dumps(result, indent=2))


@web.command("fix")
@click.argument("task", nargs=-1, required=True)
@click.option("--path", "target_path", default=".", show_default=True, help="Project path")
@click.pass_context
def web_fix(ctx, task, target_path):
    """Create a review task for fixing a website/app issue."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    issue = " ".join(task).strip()
    if hasattr(builder, "record_fix_task"):
        item = builder.record_fix_task(target_path, issue)
    else:
        from shaka.automation import TaskStore

        store = TaskStore(ctx.obj["config"].paths.base_dir)
        item = store.create_task(
            title="Fix web issue",
            kind="web",
            payload={"task": issue, "path": str(Path(target_path).resolve())},
            status="queued",
        )
        store.add_step(item["id"], "Queued web fix task for agent review.", kind="web")
    click.echo(f"Queued {item['id']}.")


@web.command("inspect")
@click.option("--path", "target_path", default=".", show_default=True, help="Project path")
@click.pass_context
def web_inspect(ctx, target_path):
    """Inspect a website/app project stack."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(builder.inspect_project(target_path), indent=2))


@web.command("checks")
@click.option("--path", "target_path", default=".", show_default=True, help="Project path")
@click.pass_context
def web_checks(ctx, target_path):
    """Plan install/build/test commands for a website/app project."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    click.echo(json.dumps(builder.plan_checks(target_path), indent=2))


@web.command("workflow")
@click.option("--path", "target_path", default=".", show_default=True, help="Project path")
@click.pass_context
def web_workflow(ctx, target_path):
    """Create an approval-aware website check workflow."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    task = builder.create_check_workflow(target_path)
    click.echo(json.dumps(task, indent=2))


@web.command("resume")
@click.argument("task_id")
@click.pass_context
def web_resume(ctx, task_id):
    """Resume an approved website check workflow in safety mode."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    try:
        task = builder.resume_check_workflow(task_id)
    except KeyError as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    click.echo(json.dumps(task, indent=2))


@web.command("execute")
@click.argument("task_id")
@click.option("--approval-id", default=None, help="Approved command-plan approval ID")
@click.option("--timeout", "timeout_seconds", default=120, show_default=True, type=int, help="Command timeout in seconds")
@click.pass_context
def web_execute(ctx, task_id, approval_id, timeout_seconds):
    """Execute an approved, allowlisted website workflow command."""
    from shaka.website_builder import WebsiteBuilder

    builder = WebsiteBuilder(ctx.obj["config"].paths.base_dir)
    try:
        task = builder.execute_approved_workflow_command(
            task_id,
            approval_id=approval_id,
            timeout_seconds=timeout_seconds,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise click.ClickException(str(exc).strip("'")) from exc
    click.echo(json.dumps(task, indent=2))


@cli.command("eval")
@click.pass_context
def eval_command(ctx):
    """Run deterministic Shaka evals."""
    from shaka.eval_runtime import EvalRunner

    result = EvalRunner(ctx.obj["config"].paths.base_dir).run()
    click.echo(json.dumps(result, indent=2))
    if result["failed"]:
        raise click.ClickException(f"{result['failed']} eval(s) failed")


@cli.group()
def mcp():
    """Protocol-level MCP commands."""


@mcp.command()
@click.option('--config', default=None, help='Path to config file')
@click.option('--transport', type=click.Choice(['stdio', 'sse', 'streamable-http'], case_sensitive=False), default='stdio', show_default=True, help='MCP transport to use')
@click.option('--mount-path', default=None, help='Mount path for HTTP transports')
def serve(config, transport, mount_path):
    """Run Shaka as an MCP server."""
    run_server(config_path=config, transport=transport, mount_path=mount_path)


@mcp.command()
@click.option('--command', 'server_command', required=True, help='Command that starts the external MCP server')
@click.option('--arg', 'server_args', multiple=True, help='Argument to pass to the server command; can be repeated')
@click.option('--env', 'server_env', multiple=True, help='Environment variable override in KEY=VALUE form')
def inspect(server_command, server_args, server_env):
    """Inspect an external MCP server and list its tools."""
    env = {}
    for item in server_env:
        if "=" not in item:
            raise click.BadParameter("Environment entries must use KEY=VALUE form")
        key, value = item.split("=", 1)
        env[key] = value

    result = asyncio.run(inspect_stdio_server(server_command, server_args, env))
    click.echo("MCP tools:")
    for tool in result.get("tools", []):
        click.echo(f"  - {tool['name']}")
        if tool.get("description"):
            click.echo(f"    {tool['description']}")

def _extract_json_object(text: str):
    """Extract the first JSON object from a model response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response.")

    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(cleaned[start:])
    return obj

def _apply_code_edits(workspace: Path, edits: list[dict]) -> list[str]:
    """Apply structured file edits inside the workspace."""
    applied = []
    workspace_root = workspace.resolve()

    for edit in edits:
        path_value = edit.get("path")
        action = edit.get("action", "replace")
        if not path_value:
            continue

        target = (workspace_root / path_value).resolve()
        if workspace_root not in target.parents and target != workspace_root:
            raise ValueError(f"Path outside workspace: {path_value}")

        if action in {"replace", "write"}:
            content = edit.get("content", "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            applied.append(f"{action}: {path_value}")
        elif action == "delete":
            if target.is_dir():
                raise ValueError(f"Refusing to delete directory: {path_value}")
            if target.exists():
                target.unlink()
            applied.append(f"delete: {path_value}")
        else:
            raise ValueError(f"Unsupported edit action: {action}")

    return applied

def _prompt_for_context(task_text: str, focus_path: Path) -> list[str]:
    """Collect a small amount of extra context before coding."""
    prompts = [
        (
            "Which file(s) or area should I focus on?",
            str(focus_path if focus_path else "."),
        ),
        (
            "What does success look like?",
            task_text,
        ),
        (
            "What should I avoid changing?",
            "No extra constraints provided.",
        ),
    ]

    context = []
    for label, default in prompts:
        try:
            answer = click.prompt(label, default=default, show_default=True)
        except (click.Abort, EOFError):
            break
        answer = str(answer).strip()
        if answer:
            context.append(answer)
    return context


def _personality_catalog(config) -> dict:
    personality = getattr(config, "personality", {}) or {}
    presets = personality.get("presets", {}) if isinstance(personality, dict) else {}
    if not isinstance(presets, dict):
        presets = {}
    return presets


def _format_onboarding_steps(config, memory: MemoryManager) -> str:
    presets = _personality_catalog(config)
    prefs = memory.get_preferences("default")
    onboarding_done = bool(prefs.get("onboarding_completed"))
    current_preset = prefs.get("personality_preset", "(not set)")
    current_personality = prefs.get("personality_custom") or prefs.get("personality", "(not set)")

    lines = [
        "SHAKA ONBOARDING",
        "=" * 50,
        "1. Keep Shaka state under ~/.shaka/config.json and sibling local folders.",
        "2. Set your provider key with SHAKA_API_KEY, or use Ollama without a hosted key.",
        "3. Run `shaka doctor` to verify skills, memory, local state, and gateway defaults.",
        "4. Start the control plane with `shaka gateway` or the shortcut `shaka dev`.",
        "5. Use `shaka skills list/install` and `shaka build-site` to prove local workflows.",
        "",
        f"Onboarding complete: {'yes' if onboarding_done else 'no'}",
        f"Current preset: {current_preset}",
        f"Current personality: {current_personality}",
        f"Local home: {config.paths.base_dir}",
        f"Gateway: http://{config.dashboard.host}:{config.dashboard.port}",
        "",
        "Available presets:",
    ]

    if presets:
        for name, description in presets.items():
            lines.append(f"  - {name}: {description}")
    else:
        lines.append("  - (none configured)")

    lines.extend([
        "",
        "Examples:",
        "  shaka onboard --provider groq --api-key-env SHAKA_API_KEY",
        "  shaka gateway --port 18789",
        "  shaka personality --preset technical",
        "  shaka personality --set \"warm and concise\"",
        "",
        "If you want Shaka to remember that you completed onboarding, run `shaka onboard --complete`.",
    ])
    return "\n".join(lines)


def _set_personality_value(memory: MemoryManager, user_id: str, preset: str | None = None, custom: str | None = None) -> None:
    if preset:
        memory.set_preference(user_id, "personality_preset", preset)
        memory.set_preference(user_id, "personality_custom", "")
        memory.set_preference(user_id, "personality", "")
        return
    if custom:
        memory.set_preference(user_id, "personality_custom", custom)
        memory.set_preference(user_id, "personality_preset", "")
        memory.set_preference(user_id, "personality", custom)
        return
    raise ValueError("No personality value provided")

@cli.command()
@click.argument('task', nargs=-1)
@click.option('--path', '-p', default='.', help='Workspace root or focus file')
@click.option('--session', '-s', default=None, help='Session ID (auto-generated if not provided)')
@click.option('--mode', type=click.Choice(['plan', 'build', 'review'], case_sensitive=False), default='build', show_default=True, help='Coding workflow mode')
@click.option('--issue-url', default=None, help='GitHub issue URL to pull task context from')
@click.option('--context-file', default=None, type=click.Path(path_type=Path), help='File with extra task context')
@click.option('--note', 'notes', multiple=True, help='Extra context note; can be supplied multiple times')
@click.option('--clarify/--no-clarify', default=True, show_default=True, help='Ask for extra context before coding')
@click.option('--max-files', default=8, type=int, show_default=True, help='Maximum files to include in repo context')
@click.option('--max-lines', default=120, type=int, show_default=True, help='Maximum lines per file snippet')
@click.option('--apply/--preview', default=False, show_default=True, help='Write returned edits to disk')
@click.option('--verify/--no-verify', default=True, show_default=True, help='Run a verification command after the coding pass')
@click.option('--test-command', default='python -m pytest -q', show_default=True, help='Verification command to run after changes')
@click.pass_context
def code(ctx, task, path, session, mode, issue_url, context_file, notes, clarify, max_files, max_lines, apply, verify, test_command):
    """Run Shaka in coding mode against the current workspace."""
    config = ctx.obj['config']

    if not task:
        click.echo(_("Usage: shaka code \"fix the failing test\""))
        return

    if not is_model_configured(config):
        click.echo(_("ERROR: No API key configured."))
        click.echo(_(f"Set {config.model.api_key_env or DEFAULT_API_KEY_ENV}, run `shaka credentials set {config.model.provider}`, or use Ollama."))
        return

    workspace = Path(path).resolve()
    focus_path = workspace if workspace.is_file() else workspace
    if workspace.is_file():
        workspace = workspace.parent

    memory = MemoryManager(config.paths.base_dir)
    skills = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(__file__), "skills_core")
    skills.load_core_skills(core_skills_dir)
    agent = Agent(config, skills, memory)

    builder = RepoContextBuilder(
        workspace_root=workspace,
        focus_path=focus_path,
        max_files=max_files,
        max_lines=max_lines,
    )
    mode = builder.normalize_mode(mode)
    connector_contexts = collect_connector_context(
        issue_url=issue_url,
        context_file=context_file,
        extra_notes=list(notes),
    )

    task_text = " ".join(task).strip()
    click.echo(_("Shaka coding mode"))
    click.echo(f"Mode: {mode}")
    click.echo(f"Workspace: {workspace}")
    click.echo(f"Focus: {focus_path}")
    click.echo("")

    clarifying_context = []
    if clarify and mode == "build":
        try:
            clarifying_context = _prompt_for_context(task_text, focus_path)
        except Exception:
            clarifying_context = []
        if not clarifying_context and not connector_contexts:
            clarifying_context = [
                f"Target area: {focus_path}",
                f"Requested outcome: {task_text}",
            ]

    if mode != "build" and apply:
        click.echo("Apply is only valid in build mode. Falling back to preview.")
        apply = False

    extra_system_messages = [
        builder.coding_system_prompt(mode),
        builder.build_task_prompt(task_text, mode),
        builder.response_schema(mode),
    ]

    if connector_contexts:
        for item in connector_contexts:
            extra_system_messages.append(f"External context [{item.label}]:\n{item.text}")

    if clarifying_context:
        extra_system_messages.append(
            "User-provided context:\n" + "\n".join(f"- {item}" for item in clarifying_context)
        )

    response = agent.chat(
        task_text,
        session_id=session,
        extra_system_messages=extra_system_messages,
        disable_tools=(mode != "build"),
    )

    click.echo(_("Shaka response received."))
    click.echo("")
    click.echo(f"[Tokens: {response['tokens_used']} | Time: {response['elapsed_seconds']}s | Tools used: {response.get('tool_calls_executed', 0)}]")
    click.echo(f"[Session: {response['session_id']}]")

    parsed = None
    try:
        parsed = _extract_json_object(response["response"])
    except Exception as exc:
        click.echo("")
        click.echo(f"Could not parse structured code response: {exc}")
        click.echo(response["response"])
        return

    summary = parsed.get("summary", "")
    edits = parsed.get("edits", []) or []
    patches = parsed.get("patches", []) or []
    notes = parsed.get("notes", []) or []
    tests = parsed.get("tests", []) or []
    plan_steps = parsed.get("plan", []) or []
    risks = parsed.get("risks", []) or []
    findings = parsed.get("findings", []) or []

    if summary:
        click.echo("")
        click.echo(summary)

    click.echo("")
    if mode == "plan":
        if plan_steps:
            click.echo("Plan:")
            for index, step in enumerate(plan_steps, start=1):
                click.echo(f"  {index}. {step}")
        if risks:
            click.echo("Risks:")
            for risk in risks:
                click.echo(f"  - {risk}")
        if tests:
            click.echo("Suggested checks:")
            for item in tests:
                click.echo(f"  - {item}")
    elif mode == "review":
        if findings:
            click.echo("Findings:")
            for finding in findings:
                location = finding.get("file", "")
                line = finding.get("line", "")
                priority = finding.get("priority", "P2")
                body = finding.get("body", "")
                suffix = f" {location}" if location else ""
                if line not in ("", None):
                    suffix += f":{line}"
                click.echo(f"  - [{priority}]{suffix} {body}")
        else:
            click.echo("No findings were returned.")
    else:
        if edits:
            click.echo("Proposed edits:")
            for edit in edits:
                click.echo(f"  - {edit.get('action', 'replace')}: {edit.get('path', '')}")
        elif patches:
            click.echo("Proposed patches:")
            for patch in patches:
                click.echo(f"  - patch: {patch.get('path', '')}")
        else:
            click.echo("No edits were returned.")

    if tests:
        click.echo("")
        click.echo("Checks:")
        for item in tests:
            click.echo(f"  - {item}")

    if notes:
        click.echo("")
        click.echo("Notes:")
        for note in notes:
            click.echo(f"  - {note}")

    if not apply:
        click.echo("")
        if mode == "build":
            click.echo("Preview only. Re-run with --apply to write the returned edits.")
        else:
            click.echo("This mode is read-only. Re-run in build mode with --apply to write edits.")
        return

    if mode != "build":
        click.echo("")
        click.echo("This mode is read-only; no files were changed.")
        return

    applied = []
    if edits:
        applied.extend(_apply_code_edits(workspace, edits))
    if patches:
        applied.extend(builder.apply_unified_patches(patches))
    if not applied:
        click.echo("")
        click.echo("Nothing to apply.")
        return
    click.echo("")
    click.echo("Applied edits:")
    for item in applied:
        click.echo(f"  - {item}")

    if verify:
        click.echo("")
        click.echo(_("Verification: running {}").format(test_command))
        try:
            args = shlex.split(test_command, posix=os.name != "nt")
            result = subprocess.run(
                args,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.stdout:
                click.echo(result.stdout.rstrip())
            if result.stderr:
                click.echo(result.stderr.rstrip())
            click.echo(f"[Verify exit code: {result.returncode}]")
        except Exception as exc:
            click.echo(f"Verification failed: {exc}")

@cli.command()
@click.option('--session', '-s', default=None, help='Resume a specific session ID')
@click.pass_context
def tui(ctx, session):
    """Start full Rich TUI (beautiful terminal interface)."""
    config = ctx.obj['config']

    if not is_model_configured(config):
        click.echo(_("ERROR: No API key configured."))
        click.echo(_(f"Set {config.model.api_key_env or DEFAULT_API_KEY_ENV}, run `shaka credentials set {config.model.provider}`, or use Ollama."))
        return

    memory = MemoryManager(config.paths.base_dir)
    session_db = SessionDB(config.paths.db_path)
    skills = SkillsRegistry()
    core_skills_dir = os.path.join(os.path.dirname(__file__), "skills_core")
    skills.load_core_skills(core_skills_dir)

    agent = Agent(config, skills, memory)
    tui_instance = ShakaTUI(agent, config)

    if session:
        agent.session_messages = memory.load_session("default", session)
        tui_instance.session_id = session

    tui_instance.run()

def main():
    """Entry point for the shaka CLI."""
    cli()

if __name__ == '__main__':
    main()
