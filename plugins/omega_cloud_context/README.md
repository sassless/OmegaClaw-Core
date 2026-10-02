# Omega Cloud context plugin

This MeTTa plugin uses Omega's `prompt-extension` hook to add text from
`asi_create_context.txt` to the agent's system prompt. It reads the file each
time Omega builds a prompt, so changes do not require an image rebuild. A
missing or empty file contributes no text.

The current fork defaults to its repository `memory/asi_create_context.txt`.
For Omega 2.0, set `asiCreateContextPath` in Omega's configuration to an
absolute path under the persistent memory directory. The deployment template
uses `/PeTTa/repos/Omega/memory/asi_create_context.txt`.
