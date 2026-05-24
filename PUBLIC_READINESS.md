# Public Readiness Notes

Shaka is functional and suitable for a public GitHub repository as a local-first developer tool.

## What is ready

- Python package entrypoint through `shaka.cli:main`.
- CLI, TUI, authenticated gateway, skills, memory, proof export, and Docker self-hosting paths.
- Approval-gated workflow execution for higher-risk command paths.
- Test coverage across runtime controls, dashboard routes, memory search, provider configuration, skills metadata, TUI behavior, and website workflow checks.

## What is intentionally not public-hosted

- The live gateway is not exposed as a public SaaS endpoint.
- Provider API keys, gateway tokens, local credentials, user sessions, and memory are expected to stay outside the repo under local runtime state.
- Docker self-hosting is intended for trusted environments.

## Current limitations

- A model provider key or local model setup is required for real chat execution.
- The web dashboard is useful but should stay token-protected.
- Docker runtime health depends on Docker being available on the host.
- The product is still alpha-stage and should be presented as functional local-first infrastructure, not finished SaaS.
