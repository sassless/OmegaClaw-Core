# ASI Omega extensions

This directory defines the release metadata for the ASI extensions used with
the pinned upstream Omega 2 runtime. The release bundle contains the MCP plugin,
the attachment-aware WebSocket channel, the Omega plugin registry, and their
Python requirements.

Build the bundle from the repository root:

```sh
python3 scripts/build_omega2_extension_bundle.py
```

The command writes a versioned archive and SHA-256 checksum to `dist/`. Plugin
source remains in its existing repository locations during the migration so the
current fork deployment and its tests continue to work. The builder maps those
files into the standalone release layout recorded in `manifest.json`.

To publish a new release, update `VERSION` and the matching `version` field in
`manifest.json`, then build and validate the archive. Change the pinned Omega
image and commit together only after compatibility testing that upstream
runtime.
