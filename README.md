# Shaka

<img src="https://img.shields.io/badge/version-0.1.0-blue" alt="version">
<img src="https://img.shields.io/badge/python-3.10+-green" alt="python">
<img src="https://img.shields.io/badge/license-MIT-orange" alt="license">

**Local-first open-source AI agent runtime.**

Built with Python. Runs on your machine. Connects to your code, email, browser checks, skills, and local workspace.
Users bring their own model keys, keep state under `~/.shaka`, and can self-host with Docker without Supabase, Railway, or a hosted database.

## Public Status

This repository is a functional local-first agent runtime, not a hosted SaaS product. The gateway is intended for localhost or trusted self-hosting and requires a token for dashboard/API access. Provider keys, gateway tokens, memory, sessions, and local credentials are stored outside the repository.

## Why Shaka?

OpenClaw and big AI agents are built for expensive laptops, cloud APIs, and Slack.
Shaka is different:

- **Laptop-first** - Primary surfaces are a terminal TUI and local web dashboard
- **Zero-cost** - Works with free API tiers (Groq, Gemini)
- **Offline memory** - Your data stays on your machine
- **Easy skills** - Python + YAML, anyone can contribute
- **South African context** - Pre-loaded with local skills (load shedding, translations)
- **Approval-gated autonomy** - Risky actions wait for explicit approval

## Local-First Architecture

Shaka is not SaaS-first. The core runtime lives on the user machine:

- `~/.shaka/config.json` - local config, provider choice, gateway defaults, token metadata
- `~/.shaka/workspace/` - local projects and demo workflows
- `~/.shaka/sessions/` - local chat/session transcripts
- `~/.shaka/memory/` - user memory and preferences
- `~/.shaka/skills/` - user-installed Python/YAML skills
- `~/.shaka/credentials/` - local credential files when env vars are not enough
- `~/.shaka/runtime/` - task store, approvals, SQLite stats
- `~/.shaka/runtime/cron.json` - local scheduled jobs and last-run metadata
- `~/.shaka/logs/` - local runtime logs

The local gateway binds to `127.0.0.1:18789` by default and uses a generated token for dashboard/API access. A future Shaka HQ can exist as optional monitoring or sync, but the agent runtime does not depend on hosted infrastructure.

## Quick Start

```bash
# 1. Install
pip install -e .

# 2. Create local state and config under ~/.shaka
shaka onboard --yes

# 3. Bring your own key, or use Ollama
$env:SHAKA_API_KEY="your_key_here"   # PowerShell
# export SHAKA_API_KEY=your_key_here # macOS/Linux
# Or store it locally outside the repo:
shaka credentials set groq

# Provider-specific setup is also supported
shaka providers list
shaka providers configure openai --model gpt-4o-mini --api-key-env OPENAI_API_KEY
shaka providers configure anthropic --model claude-3-5-haiku-latest --api-key-env ANTHROPIC_API_KEY

# 4. Start the authenticated local gateway
shaka gateway

# Or run the interactive terminal UI
shaka run
```

## Commands

| Command | Description |
|---------|-------------|
| `shaka init` | Create default configuration |
| `shaka onboard` | Create `~/.shaka`, config, workspace, and gateway token |
| `shaka gateway --port 18789` | Start authenticated localhost dashboard/API |
| `shaka dev` | One-command local gateway startup |
| `shaka daemon install/start/stop/status` | Manage the background local gateway process |
| `shaka providers list/configure/status` | Select OpenAI, Anthropic, Groq, Gemini, OpenRouter, Ollama, and compatible providers |
| `shaka credentials set/list/delete` | Manage local provider credentials outside the repo |
| `shaka cron add/list/run/tick/remove` | Manage local scheduled jobs under `~/.shaka/runtime/cron.json` |
| `shaka demo local-project` | Create, inspect, and queue a local portfolio demo workflow |
| `shaka proof export` | Write a secret-safe local runtime proof report to `~/.shaka/runtime/proof.md` |
| `shaka run` | Interactive terminal mode |
| `shaka run --no-textual` | Rich TUI fallback |
| `shaka run --raw` | Plain text mode |
| `shaka ask "message"` | One-shot query |
| `shaka code "task"` | Repo-aware coding workflow with plan/build/review modes |
| `shaka skills` / `shaka skills list` | List core and user-installed skills |
| `shaka skills install ./my-skill` | Install a local skill into `~/.shaka/skills` |
| `shaka memory` | View stored memories |
| `shaka repo-memory show` | Inspect repo-specific developer memory |
| `shaka personality` | View or set the default personality preference |
| `shaka doctor` | System health check |
| `shaka tui` | Start Rich TUI explicitly |
| `shaka mcp serve` | Run Shaka as an MCP server |
| `shaka mcp inspect` | Inspect another MCP server's tools |
| `shaka tasks` | List automation tasks |
| `shaka approve <approval_id>` | Approve a pending risky action |
| `shaka reject <approval_id>` | Reject a pending risky action |
| `shaka cancel <task_id>` | Cancel an automation task |
| `shaka retry <task_id>` | Retry a failed or cancelled automation task |
| `shaka email ...` | Search, summarize, draft, and approved-send Gmail workflows |
| `shaka build-site "prompt"` | Scaffold a full-stack Vite React + FastAPI + SQLite app |
| `shaka web verify --url URL` | Verify a website or local app with optional browser proof |
| `shaka web workflow --path DIR` | Create an approval-aware website check workflow |
| `shaka web execute <task_id>` | Execute an approved, allowlisted workflow command |
| `shaka eval` | Run deterministic Shaka evals |

## Docker Self-Hosting

Docker is optional. It runs the same local gateway with a persistent volume mounted at `/home/shaka/.shaka`.

```bash
# Optional: copy defaults and add your provider key
copy .env.example .env   # PowerShell
# cp .env.example .env   # macOS/Linux

docker compose up --build
```

The gateway listens on `http://localhost:18789`, exposes `/health`, and persists config/state in the `shaka-home` Docker volume. It does not require Supabase, Railway, or any hosted database.

For non-Docker development, use `shaka gateway --port 18789`.

## Security Notes

- Gateway binds to loopback by default.
- `shaka gateway` prints a tokenized URL and requires the token for dashboard/API access.
- Provider keys should come from env vars such as `SHAKA_API_KEY` or `shaka credentials set <provider>`; onboarding does not write secrets into repo files.
- Local runtime paths, credentials, `.env`, DBs, and logs are ignored by git.
- Rotate the gateway token with `shaka onboard --rotate-token`.
- Delete local provider credentials with `shaka credentials delete <provider>` and clear relevant env vars.

## Portfolio Demo

```bash
shaka onboard --yes
shaka doctor
shaka gateway
shaka demo local-project
shaka proof export
```

This shows the local-first loop: initialize state, verify runtime health, run the authenticated gateway, create a project inside the local workspace, inspect it, generate an approval-aware workflow, and export `~/.shaka/runtime/proof.md` for portfolio review. The dashboard task timeline can open task detail JSON with payload and step history, and the Proof tab can export the same Markdown report from the browser.

### Runtime Proof Report

`shaka proof export` creates a secret-safe Markdown snapshot of the local runtime:

- local home, config, workspace, gateway, provider, and API key source
- counts for sessions, skills, tasks, approvals, credentials, and cron jobs
- recent task, approval, cron, and tool-call tables
- demo commands and security notes for reviewers

Use JSON for automation:

```bash
shaka proof export --json
shaka proof export --output ./proof.md
```

Dashboard workflow controls:

- Select a task from the timeline.
- Use `Approve Plan` when a workflow is waiting for approval.
- After approval, choose `Resume Record-Only` to record the approved plan without shell execution, or `Execute Check` to run the approved allowlisted command.

### Local Cron Jobs

Cron jobs run locally and persist under `~/.shaka/runtime/cron.json`. They are intentionally narrow: Shaka only executes commands that pass the existing allowlist, such as `python -m pytest`, `python -m compileall`, and package build/test commands.

```bash
shaka cron add nightly-tests --schedule "@daily" --command "python -m pytest -q"
shaka cron list
shaka cron tick
shaka cron run <cron_id> --dry-run
```

Supported schedules are `@every 5m`, `@hourly`, `@daily`, `*/5 * * * *`, and `* * * * *`.

### Coding Workflow

`shaka code` is the repo-aware coding command. It supports three modes:

- `--mode plan` for read-only implementation planning
- `--mode build` for generating and optionally applying edits
- `--mode review` for read-only code review and findings

By default the command is safe: it previews the model output and does not write files unless you pass `--apply` in `build` mode.

It can also pull extra task context from:

- `--issue-url https://github.com/.../issues/123`
- `--context-file path/to/context.md`
- `--note "extra constraint"` repeated as needed

When run interactively, Shaka asks for a little more context before building so it can target the right files and preserve the right constraints.

You can also switch the personality for the default user with `shaka personality --set "warm and concise"`. Each user's preference is stored locally in their memory profile, so different people can have different tones on the same machine.

Named presets are built in:

- `warm`
- `concise`
- `technical`
- `mentor`
- `playful`

Use `shaka personality --preset technical` to switch to one of them, or keep using `--set` for a fully custom tone.

The `shaka onboard` command prints the setup checklist, including API key setup, personality selection, and the repo-workflow commands.

### MCP

Shaka now exposes a real Model Context Protocol surface. You can run it as a server with `shaka mcp serve`, then connect external tools or editors to it over stdio, SSE, or streamable HTTP.

You can also inspect another MCP server with `shaka mcp inspect --command ...` to see what tools it exposes before wiring it into a workflow.

## Skills

Skills are Python modules with YAML metadata. Drop them in `~/.shaka/skills/` to install.

### Built-in Skills
- **hello** - Greeting and introduction
- **loadshedding** - Eskom load shedding schedules (South Africa)
- **websearch** - DuckDuckGo web search

### Creating a Skill

Create a folder with two files:

**skill.yaml**
```yaml
name: myskill
description: What this skill does
version: 0.1.0
triggers:
  - trigger words
  - that activate this skill
```

**__init__.py**
```python
class SkillHandler:
    def get_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "myskill",
                "description": "...",
                "parameters": {...}
            },
        }

    def run(self, message, context):
        return "Result from my skill"
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the runtime model, approval gates, shared CLI/TUI/dashboard backend, connector layer, and eval harness.

## Model Providers

| Provider | Env Var | Default Model |
|----------|---------|---------------|
| Ollama | none | qwen2.5:7b |
| OpenAI | OPENAI_API_KEY | gpt-4o-mini |
| Anthropic | ANTHROPIC_API_KEY | claude-3-5-haiku-latest |
| Groq | GROQ_API_KEY or SHAKA_API_KEY | llama-3.3-70b-versatile |
| Gemini | GEMINI_API_KEY | gemini-2.0-flash |
| OpenRouter | OPENROUTER_API_KEY | openai/gpt-4o-mini |
| Mistral | MISTRAL_API_KEY | mistral-small-latest |
| Together | TOGETHER_API_KEY | meta-llama/Llama-3.3-70B-Instruct-Turbo |
| Fireworks | FIREWORKS_API_KEY | accounts/fireworks/models/llama-v3p1-8b-instruct |
| DeepSeek | DEEPSEEK_API_KEY | deepseek-chat |
| xAI | XAI_API_KEY | grok-2-latest |
| Cerebras | CEREBRAS_API_KEY | llama3.1-8b |
| Perplexity | PERPLEXITY_API_KEY | sonar |

Use `shaka providers status` to see the active provider without exposing secret values. Secrets can come from provider-specific env vars, the generic `SHAKA_API_KEY`, or `shaka credentials set <provider>`.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for completed, current, and next milestones.

Brand and UI direction lives in [docs/BRAND.md](docs/BRAND.md).

## Contributing

We welcome contributions from everywhere, especially Africa!

```bash
git clone https://github.com/yourusername/shaka.git
cd shaka
pip install -r requirements.txt
python3 -m shaka.cli doctor
```

## License

MIT

---

**Built in South Africa, for the world.**
