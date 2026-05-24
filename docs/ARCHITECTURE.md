# Shaka Architecture

Shaka is a local-first open-source AI agent runtime. It is designed to run on a user's machine first, then expose the same capabilities through CLI, TUI, dashboard, and localhost gateway surfaces.

Cloud infrastructure is optional. The core runtime does not require Supabase, Railway, hosted queues, hosted databases, or a SaaS control plane.

## Local State Layout

The default local home is `~/.shaka`:

- `config.json` stores local defaults, provider metadata, gateway host/port, and the generated gateway token.
- `workspace/` stores local projects and demo workflows managed by Shaka.
- `sessions/` stores local conversation/session transcripts.
- `memory/` stores user memory, preferences, and wiki-style local notes.
- `skills/` stores user-installed skills.
- `credentials/` is reserved for local credential files when env vars are insufficient.
- `runtime/` stores the task/approval JSON store, cron metadata, daemon metadata, and SQLite runtime stats.
- `runtime/cron.json` stores local scheduled jobs, next-run timestamps, and last-run task references.
- `logs/` stores local runtime logs.

Legacy `config.yaml` is still readable, but the product direction is `~/.shaka/config.json` plus local state directories.

## Runtime Model

The runtime is a Python application that coordinates user input, model providers, local memory, skills, connectors, and approval-gated actions.

Core responsibilities:

- Route requests from the CLI, terminal UI, or web dashboard into one shared backend.
- Keep local state in memory stores rather than assuming a cloud workspace.
- Call model providers such as OpenAI, Anthropic, Groq, Gemini, OpenRouter, Ollama, and OpenAI-compatible endpoints through a provider abstraction.
- Load skills and connectors as explicit capabilities instead of hidden side effects.
- Require approval before risky actions such as sending email, writing files, or running destructive commands.
- Expose an authenticated localhost gateway for the dashboard and API.

## User Surfaces

Shaka supports multiple front ends over the same backend:

- **CLI** for one-shot commands, coding workflows, evals, health checks, MCP, and automation control.
- **TUI** for interactive laptop workflows in the terminal.
- **Local gateway** for token-authenticated dashboard/API access on `127.0.0.1:18789` by default.
- **Dashboard** for runtime status, active sessions, installed skills, provider status, recent tasks, and approval inboxes.
- **Daemon manager** for running the same gateway as a local background process without introducing hosted infrastructure.
- **Cron runtime** for scheduled local maintenance or workflow commands, persisted under `~/.shaka/runtime/cron.json`.

The goal is parity across surfaces: features should be implemented in backend services first, then exposed through the interface that fits the workflow.

## Gateway Security

The gateway binds to loopback by default and requires a generated local token for dashboard/API requests. `/health` is intentionally unauthenticated for process managers and Docker health checks. Runtime inspection lives at `/api/runtime/status` and reports local state without exposing API key values.

For Docker self-hosting, Shaka binds to `0.0.0.0` inside the container and persists `/home/shaka/.shaka` through a named volume. Operators should set a strong `SHAKA_GATEWAY_TOKEN` before exposing the port outside a trusted host.

## Credentials

Hosted provider keys can come from environment variables or the local credential store:

- `SHAKA_API_KEY` remains the simplest BYOK path.
- Provider-specific env vars are supported, including `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, and `OPENROUTER_API_KEY`.
- `shaka credentials set <provider>` stores a provider key under `~/.shaka/credentials/providers.json`.
- CLI, dashboard, and status surfaces only show masked fingerprints.
- `shaka credentials delete <provider>` removes a stored credential.

The credential store is intentionally local and repo-ignored. A future hardening step can add OS keychain backends while keeping the same CLI contract.

## Daemon Mode

`shaka daemon install/start/stop/status` manages a background gateway process using the same local config and token. It records process metadata in `~/.shaka/runtime/daemon.json` and writes logs under `~/.shaka/logs/`.

This is a local process manager, not a cloud service.

## Approval Gates

Shaka separates intent from execution. The agent can draft plans, propose edits, or prepare external actions, but high-impact operations should pause for explicit user approval.

Approval-gated examples:

- Applying generated code changes.
- Sending or replying to email.
- Starting long-running automation.
- Touching external services through connectors.
- Running commands that modify local state.

This keeps autonomy useful without making local development unsafe.

## Connector Layer

Connectors wrap external systems behind narrow, reviewable interfaces. Current and planned connectors include:

- Code and filesystem context.
- Browser and website verification.
- Gmail workflows.
- MCP server inspection and serving.
- Messaging integrations such as WhatsApp or Telegram.

Connectors should expose capabilities, inputs, outputs, and approval requirements clearly so the runtime can decide what is safe to execute automatically.

## Skills

Skills are lightweight Python modules with YAML metadata. They provide local tools that can be installed, listed, and triggered by the agent.

Built-in skills currently cover starter workflows such as greetings, web search, and South African context like load shedding. The skill format is intentionally simple so contributors can add capabilities without changing the core runtime.

CLI entry points:

- `shaka skills` and `shaka skills list` list core and user-installed skills.
- `shaka skills install ./skill-dir` copies a local skill into `~/.shaka/skills`.

## Dashboard Workflow UX

The dashboard task timeline is an operational control surface, not just a log. Selecting a workflow task loads `/api/tasks/<task_id>` and exposes safe actions based on task state:

- Waiting workflow: approve the pending command plan.
- Approved queued workflow: either resume record-only or execute the approved allowlisted check.
- Failed/cancelled task: retry.
- Active non-terminal task: cancel.

Execution still flows through the same backend approval and allowlist checks as the CLI.

## Eval Harness

`shaka eval` is the deterministic evaluation entry point. It exists to keep agent behavior testable as capabilities expand.

The harness should cover:

- Command routing and provider fallback behavior.
- Skill discovery and execution.
- Approval-gate boundaries.
- Connector behavior with mocked external systems.
- Coding workflow output quality and safety constraints.

Evals are part of the architecture, not a separate demo layer. New high-impact features should add checks before being treated as stable.
