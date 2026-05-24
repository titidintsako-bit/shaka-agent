# Shaka Roadmap

This roadmap tracks the next phase of Shaka as a laptop-first developer agent with shared CLI, TUI, dashboard, connector, and eval infrastructure.

## Completed

- CLI entry points for setup, chat, one-shot questions, skills, memory, health checks, and automation control.
- Multi-provider model support for hosted and local backends.
- Local memory and skill loading.
- Repo-aware `shaka code` workflow with plan, build, and review modes.
- Approval-gated actions for higher-risk workflows.
- Web dashboard with Docker deployment path and health check.
- MCP server and inspection commands.
- Gmail, web verification, and site-building command surfaces.
- Deterministic eval command entry point.

## Current Phase

- Tighten the shared backend used by CLI, TUI, and dashboard.
- Make approval gates consistent across code, email, connector, and automation workflows.
- Improve connector boundaries so external services are explicit and testable.
- Expand eval coverage for routing, skills, approvals, and coding workflows.
- Document architecture, roadmap, and brand direction for portfolio review.
- Stabilize dashboard and TUI behavior around the same runtime state.

## Next Milestones

- Connector hardening for browser verification, Gmail, MCP, and messaging adapters.
- WhatsApp or Telegram integration behind approval-aware connector contracts.
- Expanded multilingual and South African-local workflows.
- Skill packaging conventions and contribution guidance.
- Hosted demo path that preserves local-first assumptions where possible.
- Broader eval fixtures for regression testing before releases.
- Cleaner onboarding for new contributors and portfolio reviewers.

## Later Options

- Voice or USSD experiments if they fit the local-first product direction.
- Skill marketplace or registry once skill interfaces are stable.
- Team workspace features after single-user laptop workflows are reliable.
- Additional model routing policies for cost, latency, privacy, and offline use.
