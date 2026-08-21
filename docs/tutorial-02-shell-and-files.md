# Tutorial 02 — Shell and Files

**Goal:** let OmegaClaw inspect and modify its environment using `shell`, `read-file`, `write-file`, and `append-file`.

## Prerequisites

- A running OmegaClaw (see [Usage](/README.md#usage)).
- Awareness that these skills run with the permissions of the OmegaClaw process.

## The four I/O skills

| Skill | Purpose |
|---|---|
| `(shell "cmd")` | Run a shell command under `timeout -k 1s 5s`; returns stdout and stderr merged into one result, or `timeout_error` if the limit is hit. |
| `(read-file "path")` | Return the file contents as a string. |
| `(write-file "path" "contents")` | Overwrite the file. |
| `(append-file "path" "line")` | Append a line (with trailing newline) to the file. |

See [reference-skills-io.md](./reference-skills-io.md) for exact signatures.

## 1. Inspect the environment

```
what version of python is available?
```

Expected skill call: `(shell "python3 --version")`.

## 2. Produce a file

```
write a haiku about reasoning under uncertainty to /tmp/haiku.txt
```

Expected: `(write-file "/tmp/haiku.txt" "...")`, then on the next turn `(read-file "/tmp/haiku.txt")` to confirm.

## 3. Keep a running log

```
start a log at /tmp/session.log and append a line summarizing every turn
```

The agent should `(append-file "/tmp/session.log" "...")` on each subsequent turn. Inspect cat `/tmp/session.log`.

## Safety notes

- **Avoid apostrophes in `shell` arguments.** The system prompt tells the model not to use them, but nothing in the Prolog helper enforces it — an apostrophe reaches `sh -c` and can break the command in confusing ways. Quote text with double quotes instead, or write it to a file first and operate on the file.
- **Commands are killed after five seconds** (`timeout -k 1s 5s`). Anything longer has to be backgrounded or split across turns.
- **The filesystem is restricted, but the shell is not.** A Landlock policy from `profile/policy.yaml` limits which paths the agent process can read and write; use `get-io-policy` to see the allowed roots. Nothing filters the command text itself, so a destructive command inside the permitted area does what it says. Run in Docker and treat the container as ephemeral.
- **`write-file` and `append-file` read the file back** after writing and return its size, sha256 and a snippet. Relay that result rather than reporting a write as successful on its own.
- File paths are resolved relative to the OmegaClaw working directory unless absolute.

## Verification

- Log shows a `(shell ...)` call and its captured stdout.
- Files created by `write-file` / `append-file` exist on disk inside the container.

## Next steps

- [tutorial-03-writing-a-custom-skill.md](./tutorial-03-writing-a-custom-skill.md) — extend the surface with your own skill.
- [reference-skills-io.md](./reference-skills-io.md) — full details and edge cases.
