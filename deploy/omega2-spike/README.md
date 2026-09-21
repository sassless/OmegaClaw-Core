# Omega 2.0 plugin spike

This spike runs the upstream Omega 2.0 development image with the existing MCP
client and attachment-aware WebSocket channel mounted as plugins. It uses
Omega's `Test` provider and mock channel, so it does not need or forward an LLM
API key.

The base image is pinned by digest. The derived image adds `python3-pip` and the
Python packages in `requirements.txt`; plugin code and `plugins.yaml` are mounted
read-only by Compose.

## Run

```sh
docker compose -f deploy/omega2-spike/compose.yaml build
docker compose -f deploy/omega2-spike/compose.yaml up -d
docker compose -f deploy/omega2-spike/compose.yaml logs --no-color omega
```

Successful startup includes this log line:

```text
registerCommChannel: registering communication channel websocket
Plugin mcp is loaded
```

Stop the test container while keeping the downloaded and derived images cached:

```sh
docker compose -f deploy/omega2-spike/compose.yaml down
```

The mounted `plugins/mcp` extension registers `call-mcp` as a two-argument
command. It uses the optional dynamic command alias hook when an older
OmegaClaw helper provides it, while Omega 2.0 uses the structured `call-mcp`
tool directly.

The `wschat` registry entry points to the mounted `channels/wschat.py` and
`channels/chat_attachments.py` files. The channel remains inactive in this
smoke test because `commchannel=test`; selecting `commchannel=wschat` requires
`WS_URL` and, when the server requires it, `WS_TOKEN`.
