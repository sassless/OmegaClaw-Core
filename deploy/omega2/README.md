# Omega 2.0 deployment

This Compose project runs the pinned upstream Omega 2.0 image with the MCP and
attachment-aware WebSocket integrations mounted as downstream plugins. The
derived image adds only the plugins' Python dependencies.

## Configure

Copy `.env.example` to the ignored repository-root `.env`, or export the same
variables in the shell. Replace both example file paths with files containing
the real MCP configuration and WebSocket bearer token. Keep those files out of
Git.

The secret files are mounted below `/PeTTa/repos/Omega`, where Omega's runtime
policy permits reads. `/run/secrets` is not used because the current upstream
policy blocks that path. The ASI API key remains an environment variable
because Omega's entrypoint passes it to its local provider proxy before
scrubbing the agent environment.

## Validate and run

```sh
docker compose --env-file .env -f deploy/omega2/compose.yaml config --quiet
docker compose --env-file .env -f deploy/omega2/compose.yaml build
docker compose --env-file .env -f deploy/omega2/compose.yaml up -d
docker compose --env-file .env -f deploy/omega2/compose.yaml logs --no-color omega
```

The named `omega-memory` volume survives container replacement. Stop the
deployment without deleting that volume or the cached image:

```sh
docker compose --env-file .env -f deploy/omega2/compose.yaml stop
```

Before replacing the fork deployment, verify MCP tool discovery and one tool
call, WebSocket messaging with an attachment, and memory after a container
restart. Container stdout/stderr can be collected directly; add Fluent Bit
only when the production log destination and required metadata are known.
