# Shaka Local Deployment

## Overview

Shaka is deployed as a local-first Python runtime. The primary surfaces are:

- `shaka gateway` for the authenticated localhost dashboard/API.
- `shaka run` or `shaka tui` for terminal workflows.
- Docker Compose for optional self-hosting with a persistent local-state volume.

The core runtime does not require Supabase, Railway, hosted queues, or a hosted database.

## Local Install

```bash
pip install -e .
shaka onboard --yes
shaka doctor
shaka gateway --port 18789
```

Set `SHAKA_API_KEY` for hosted BYOK providers, or run `shaka credentials set <provider>` to store a local credential outside the repo. Use `SHAKA_PROVIDER=ollama` for a local model path.

For a background local process:

```bash
shaka daemon install
shaka daemon start
shaka daemon status
```

## Docker Self-Hosting

```bash
copy .env.example .env
docker compose up --build
```

Docker exposes `18789` and persists `/home/shaka/.shaka` through the `shaka-home` named volume.

Important behavior:

- `/health` is unauthenticated for container health checks.
- Dashboard/API routes require the gateway token.
- `SHAKA_GATEWAY_TOKEN` can be set in `.env`; otherwise Shaka generates one in the persisted config.
- Provider API keys are read from environment variables and should not be committed.

## Verification

```bash
python -m pytest -q
shaka doctor
shaka demo local-project
```

## Security

- Bind to `127.0.0.1` for normal local use.
- Only bind to `0.0.0.0` inside Docker or trusted self-hosting environments.
- Rotate the gateway token with `shaka onboard --rotate-token`.
- Delete local credential files under `~/.shaka/credentials/` when revoking access.
