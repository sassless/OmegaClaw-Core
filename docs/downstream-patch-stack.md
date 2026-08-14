# ASI:Create downstream patch stack

This branch is rebuilt on the exact upstream `v0.1.18` tag. Keep each feature
as a focused commit so a later upstream version bump can replay, replace, or
drop it independently. The commit column contains the intended subject until
the changes are committed; replace each subject with its resulting hash.

| Feature | Commit | Files/extension points | Upstream status | Drop condition |
| --- | --- | --- | --- | --- |
| ASI runtime environment contract | `fix: preserve ASI runtime environment` | `entrypoint.sh`; scrub allowlist and argument-array reconstruction | The upstream scrub does not preserve `WS_URL`, `WS_TOKEN`, or `MCP_JSON_CONTENT`. | Drop when upstream forwards these declared channel/plugin variables, or provides a generic safe mechanism that preserves them. |
| MCP plugin | `feat: add MCP plugin` | `plugins/mcp/`, `config/plugins.yaml`, `src/helper.py`, `requirements.txt` | The plugin API exists upstream; MCP discovery and invocation do not. | Drop when upstream supplies equivalent SSE and streamable-HTTP MCP support with bounded calls, safe logging, cache refresh, and generic skills. |
| ASI prompt-context plugin | `feat: load ASI Create prompt context dynamically` | `plugins/asi_create_context/`; upstream `prompt-extension` hook | Upstream provides dynamic prompt extensions but no deployment-owned context-file integration. | Drop when upstream has an always-loaded, dynamically reread deployment-context fragment with missing-file semantics equivalent to `(empty)`. |
| WebSocket attachment receive | `feat: receive WebSocket chat attachments` | `channels/chat_attachments.py`, `channels/wschat.py` | Upstream has the resumable WebSocket transport but no attachment descriptors, bounded download, extraction, or retention. | Drop when upstream validates and renders inbound attachments with equivalent origin, size, checksum, filesystem, PDF, retry, and cleanup controls. |
| Channel-registry attachment send | `feat: send attachments through channel registry` | `src/channels.py`, `src/channels.metta`, `src/skills.metta`, `channels/wschat.py` | Upstream's channel abstraction supports text only. | Drop when upstream exposes a generic channel capability for sending existing attachment IDs and preserves idempotent MeTTa behavior. |
| Landlock `REFER` plus persistent Chroma-path invariant | `fix: allow Chroma maintenance under Landlock` | `profile/policy.py`; policy and image-path tests | Upstream `v0.1.18` lacks `AccessFs.REFER`; its Chroma path selection and image symlink are otherwise retained. | Drop the permission patch when upstream includes `REFER`; retain the behavioral path regression until persistence is guaranteed another way. |
| Background knowledge initialization | `feat: initialize knowledge in the background` | `src/rag.py`, `src/loop.metta` | Upstream indexes knowledge synchronously during startup. | Drop when upstream initialization is non-blocking, single-flight, daemonized, and observably reports completion and failure. |
