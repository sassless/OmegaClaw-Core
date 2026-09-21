# Omega 2.0 plugin spike

This spike runs the upstream Omega 2.0 development image with the existing MCP
client mounted as a plugin. It uses Omega's `Test` provider and mock channel, so
it does not need or forward an LLM API key.

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
Plugin mcp is loaded
```

Stop the test container while keeping the downloaded and derived images cached:

```sh
docker compose -f deploy/omega2-spike/compose.yaml down
```

The compatibility wrapper registers `call-mcp` as a two-argument command and
ignores the fork-only dynamic MCP command alias hook. Remote tools remain
available through `call-mcp <tool_name> <arguments_json>`.
