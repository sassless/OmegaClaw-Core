# ASI Omega plugins

This directory defines the release metadata for the ASI plugins used with
the pinned upstream Omega 2 runtime. The release bundle contains the MCP plugin,
the attachment-aware WebSocket channel and `send-attachment` skill, the ASI
Create prompt-context plugin, the Omega plugin registry, and their Python
requirements.

The bundle also includes the team's complete `prompt.txt` and
`prompt_ASICloud.txt`. Deployment mounts them over the corresponding files in
Omega's persistent memory directory; prompt edits are therefore part of the
versioned plugin release.

Build the bundle from the repository root:

```sh
python3 scripts/build_omega2_plugin_bundle.py
```

The command writes a versioned archive and SHA-256 checksum to `dist/`. The
builder maps repository source files into the standalone release layout
recorded in `manifest.json`.

To publish a new release, update `VERSION` and the matching `version` field in
`manifest.json`, then build and validate the archive. Change the pinned Omega
image and commit together only after compatibility testing that upstream
runtime.
