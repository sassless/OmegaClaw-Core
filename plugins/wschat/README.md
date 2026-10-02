# WebSocket plugin

`wschat.metta` is the entry point for Omega 2.0. It registers the Python
WebSocket channel and adds the `send-attachment attachment_id message` skill
through Omega's plugin API. `asi_wschat.py` handles WebSocket messages and
`chat_attachments.py` downloads and processes incoming files.

The unique Python module name avoids a collision with the default
`channels/wschat.py` in the upstream image.

Set `wschatManageStartupMessages: true` in Omega 2.0's `config.yaml` to send
the Omega Cloud greeting when the channel starts and suppress Omega's automatic
version message. A later version reply requested by the user is still sent.
Leave this setting unset in the current fork, which already sends its greeting.

The attachment id must come from an uploaded file, for example from an MCP
`upload_file` call. One id is sent at most once by the skill. The plugin sends
the id in an `agent_message`; it does not upload file bytes over WebSocket.

The old `channels/` paths are compatibility symlinks for the current fork.
The Omega 2.0 release bundle and Compose deployment use the files here.
