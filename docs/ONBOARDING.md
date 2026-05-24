# Shaka - Local-first AI agent runtime

## Quick Start (3 Steps)

### 1. Install
```bash
git clone <your-repo>
cd shaka
pip install -e .
```

### 2. Configure
Create local state and choose your provider:
```bash
shaka onboard --yes
```

### 3. Run
```bash
shaka gateway
```

The gateway prints a tokenized localhost URL. Use `shaka run` when you want the terminal UI instead.

For a background gateway:

```bash
shaka daemon install
shaka daemon start
shaka daemon status
```

## Local State

Shaka stores runtime state under `~/.shaka` by default:

| Path | Purpose |
|------|---------|
| `config.json` | Local config, provider metadata, gateway defaults, token |
| `workspace/` | Projects and demo workflows |
| `sessions/` | Local session transcripts |
| `memory/` | User memory and preferences |
| `skills/` | User-installed skills |
| `credentials/` | Optional local credential files |
| `runtime/` | Tasks, approvals, runtime DB |
| `logs/` | Runtime logs |

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| SHAKA_PROVIDER | groq | LLM provider (groq, gemini, openrouter, ollama) |
| SHAKA_API_KEY | - | API key for your chosen provider |
| SHAKA_MODEL | llama-3.3-70b-versatile | Model to use |
| SHAKA_BASE_URL | - | Custom endpoint (for OpenRouter, etc.) |
| SHAKA_LANGUAGE | en | UI language |
| SHAKA_HOME | ~/.shaka | Local state directory |
| SHAKA_HOST | 127.0.0.1 | Gateway bind host |
| SHAKA_PORT | 18789 | Gateway port |
| SHAKA_GATEWAY_TOKEN | generated | Local gateway token override |

## Providers Setup

### Groq (Recommended - Fast & Free Tier)
1. Get a key at https://console.groq.com/keys
2. Set `SHAKA_PROVIDER=groq`
3. No base URL needed

### Gemini
1. Get a key at https://aistudio.google.com/app/apikey
2. Set `SHAKA_PROVIDER=gemini`

### OpenRouter
1. Get a key at https://openrouter.ai/keys
2. Set `SHAKA_PROVIDER=openrouter`
3. Set `SHAKA_BASE_URL=https://openrouter.ai/api/v1`

### Ollama (Local)
1. Install Ollama from https://ollama.ai
2. Set `SHAKA_PROVIDER=ollama`
3. Set `SHAKA_BASE_URL=http://localhost:11434`

## Docker

```bash
copy .env.example .env
docker compose up --build
```

Docker persists `/home/shaka/.shaka` in the `shaka-home` volume and exposes `18789`. It does not require a hosted database.

## CLI Commands

```bash
shaka run          # Start the TUI
shaka gateway      # Start authenticated localhost gateway
shaka dev          # Shortcut for local gateway startup
shaka daemon start # Start gateway in the background
shaka doctor       # Health check
shaka onboard      # First-time local setup wizard
shaka credentials set groq # Store a provider key outside the repo
shaka skills list  # List core and installed skills
shaka demo local-project # Create a local workspace proof workflow
shaka personality  # Customize personality
```

## Dashboard Workflow Controls

Open the gateway URL, select a workflow task from the task timeline, then use the task detail controls:

- `Approve Plan` approves the pending command plan.
- `Resume Record-Only` records the approved plan without running a shell command.
- `Execute Check` runs the approved allowlisted command and captures output in the task payload.

## Troubleshooting

**"No module named 'textual'"**
```bash
pip install textual>=0.29.0
```

**"Connection error"**
- Check your API key is correct
- Verify internet connection
- Try a different provider

**"valid Shaka gateway token required"**
- Open the URL printed by `shaka gateway`
- Or pass `X-Shaka-Token: <token>` / `Authorization: Bearer <token>` to API requests
- Rotate the token with `shaka onboard --rotate-token`

**"No API key or Ollama configured"**
- Set `SHAKA_API_KEY`
- Or run `shaka credentials set groq`
- Or use `SHAKA_PROVIDER=ollama`

**UI looks broken**
- Ensure terminal supports ANSI colors
- Try zooming in/out (Ctrl+scroll)
- Report issues at https://github.com/your-repo/issues

## Need Help?
- Run `shaka doctor` for diagnostics
- Check `docs/DEPLOYMENT_README.md` for advanced setup
