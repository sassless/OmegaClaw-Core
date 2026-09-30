# Omega 2.0 deployment

This Compose project runs the pinned upstream Omega 2.0 image with the MCP and
attachment-aware WebSocket integrations mounted as downstream plugins. The
derived image adds only the plugins' Python dependencies.

The WebSocket extension is loaded as a MeTTa plugin. It registers the Python
channel and the `send-attachment attachment_id message` skill through Omega's
plugin API, so sending an uploaded file does not require changes to upstream
`src/channels.py` or `src/skills.metta`. Its source is in `plugins/wschat/`.
The deployment enables `wschatManageStartupMessages` so this channel sends the
Omega Cloud greeting and suppresses Omega's automatic startup version message.

The `omega_cloud_context` plugin reads
`/PeTTa/repos/Omega/memory/asi_create_context.txt` from the persistent memory
volume when Omega builds a prompt. The space-service backend currently writes
this file to the fork's `/PeTTa/repos/OmegaClaw-Core/memory` path. Update its
deployment and prompt-refresh paths to target the Omega 2.0 memory volume before
using automated VM deployment. For local Compose testing, provide the file in
the `omega-memory` volume. An absent file adds no prompt text; edits are picked
up on the next prompt without rebuilding the image.

The deployment also mounts the repository's `memory/prompt.txt` and
`memory/prompt_ASICloud.txt` read-only over Omega's corresponding prompt files.
These are the complete team-edited base prompts, including changed and removed
instructions. Keep edits in the tracked source files and rebuild the extension
archive for a release; the ASI context file is for additional runtime context.

The deployable plugin release is built separately from the repository root:

```sh
python3 scripts/build_omega2_extension_bundle.py
```

This produces `dist/asi-omega-extensions-<version>.tar.gz` and its SHA-256
checksum. The archive packages the files intended for automated VM deployment;
space-service does not consume it yet. This Compose project mounts repository
source directly for local testing.

## Configure

Copy `.env.example` to the ignored repository-root `.env`, or export the same
variables in the shell. Replace both example file paths with files containing
the real MCP configuration and WebSocket bearer token. Keep those files out of
Git.

The pinned Omega image runs the agent as UID/GID `65534`. On a Linux host,
protect the mounted secret files while keeping them readable by that runtime
user:

```sh
chown 65534:65534 /path/to/mcp.json /path/to/ws-token
chmod 0400 /path/to/mcp.json /path/to/ws-token
```

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
