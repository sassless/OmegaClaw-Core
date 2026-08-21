# Reference — I/O Skills

Defined in `src/skills.metta`. The `shell` primitive is backed by `src/skills.pl`, the write skills by `src/fileio.py`, and `get-io-policy` by `profile/policy.py`.

---

## `shell`

### Signature
```metta
(shell "command")
```

### Purpose
Execute a shell command and return its output.

### Parameters
- `command` — the command line, passed to `sh -c` unchanged. The skill description asks the model to avoid apostrophes, but nothing rejects them: `src/skills.pl` performs no filtering.

### Returns
Standard output and standard error, merged — both streams are redirected into the same temporary file, which is read back as one string.

### Examples
```metta
(shell "ls -la /app")
(shell "python3 --version")
```

### Notes / Limits
- Runs with the permissions of the OmegaClaw process.
- No sandboxing beyond the container and the Landlock policy. Run in a container for anything resembling untrusted use.
- **Hard 5-second wall clock.** The command runs under `timeout -k 1s 5s`; if it is killed the skill returns the atom `timeout_error` and no output at all, so a slow command loses whatever it had already printed.
- The whole remainder of the model's line becomes the command, newlines included. A heredoc therefore survives only as long as none of its lines starts with a known skill name — such a line starts a new command block and cuts the heredoc in half.
- Prefer writing complex commands to a file and invoking the file rather than embedding quotes-within-quotes.

---

## `read-file`

### Signature
```metta
(read-file "path")
```

### Purpose
Read a file into a string.

### Parameters
- `path` — absolute or relative filesystem path. MeTTa library paths of the form `(library OmegaClaw-Core ./memory/prompt.txt)` are also accepted (see `getPrompt`).

### Returns
The file's contents as a single string.

### Examples
```metta
(read-file "/tmp/notes.txt")
```

### Notes / Limits
- Fails if the file does not exist (the call checks `exists_file` first).

---

## `write-file`

### Signature
```metta
(write-file "path" "contents")
```

### Purpose
Create or overwrite a file with the given contents.

### Parameters
- `path` — target filesystem path.
- `contents` — the exact bytes to write.

### Returns
A verification string read back from disk after the write:
`WRITE-VERIFIED file=<path> bytes=<size> sha256=<16 hex chars> head='<first 80 bytes>' tail='<last 80 bytes>'`
— or `WRITE-FAILED file=<path>: <error>` on failure (the skill returns, never raises).

### Examples
```metta
(write-file "/tmp/note.txt" "hello world")
```

### Notes / Limits
- Overwrites unconditionally — there is no confirm step.
- Writes the exact bytes given — no implicit trailing newline.
- For files up to 160 bytes the `tail` snippet is empty (`head` plus `sha256` already cover the content); for files over 2 MB the hash is reported as `sha256=skipped(large)`.
- For incremental writes, use `append-file`. For content containing quotes, backslashes
  or newlines, prefer `write-file-b64`.

---

## `write-file-b64`

### Signature
```metta
(write-file-b64 "path" "base64content")
```

### Purpose
Create or overwrite a file with base64-decoded content — byte-exact for content containing
quotes, backslashes or newlines, which the plain-text argument path can mangle.

### Parameters
- `path` — target filesystem path.
- `base64content` — base64 encoding of the exact bytes to write, as a single line
  (whitespace inside the argument is tolerated).

### Returns
The same `WRITE-VERIFIED …` / `WRITE-FAILED …` string as `write-file`.

### Examples
```metta
(write-file-b64 "/tmp/script.sh" "IyEvYmluL2Jhc2gKZWNobyAiYVwiYiIgJ2MnCg==")
```

### Notes / Limits
- Invalid base64 fails without writing anything.
- Binary-safe: the decoded bytes are written verbatim.

---

## `append-file`

### Signature
```metta
(append-file "path" "line")
```

### Purpose
Append a line to an existing file, followed by a newline.

### Parameters
- `path` — target filesystem path. File must exist.
- `line` — string to append.

### Returns
`APPEND-VERIFIED file=<path> bytes=<file size after append> sha256=<16 hex chars> head='…' tail='…'`
read back from disk — or `APPEND-FAILED file=<path>: <error>` (e.g. when the file does not exist).

### Examples
```metta
(append-file "/tmp/session.log" "turn 42 summary: ...")
```

### Notes / Limits
- Fails if the file does not exist (the skill checks existence first). Create it with `write-file` first if needed.
- For files up to 160 bytes the `tail` snippet is empty (`head` plus `sha256` already cover the content); for files over 2 MB the hash is reported as `sha256=skipped(large)`.
- A trailing newline is always added. A leading one is added too when the file does not already end with a newline, so the appended text always starts on its own line — expect up to two more bytes than the argument itself.

---

## `get-io-policy`

### Signature

```metta
(get-io-policy)
```

### Purpose

Return the filesystem paths allowed by OmegaClaw's active security policy.

Agent should use this skill before reading, writing, appending, or otherwise modifying a
file when the target path is not known to be allowed.

### Parameters

This skill does not take any parameters. It reads the policy file configured
by the `securityPolicyPath` runtime option, through `policy.get_allowed_policy_paths`
in `profile/policy.py`.

### Returns

A JSON-formatted string with two fields:

- `read_only` — paths that may be read;
- `read_write` — paths that may be read and modified.

Example:

```json
{
  "read_only": ["/usr", "/opt", "/var/log"],
  "read_write": ["/tmp", "/var/tmp"]
}
```

If no security policy is configured, the skill returns:

```text
Could not retrieve policy: policy is not set
```

If the policy cannot be loaded, it returns:

```text
Could not retrieve a policy: unexpected exception
```

### Examples

```metta
(get-io-policy)
```

A typical workflow before writing a file is:

1. Call `get-io-policy`.
2. Check whether the target path is covered by a `read_write` path.
3. Call `write-file` or `append-file` only if the path is allowed.

### Notes / Limits

- The skill reports configured policy paths; it does not grant permissions.
- Paths in `read_only` must not be used for writing.
- Paths in `read_write` may be read and modified.
- The skill does not check a particular requested path automatically.
- The result contains policy paths, not the contents of the policy file.
- Does not reveal the complete security-policy configuration to the user.
- If a requested path is denied, suggest using `/tmp` when appropriate.
- If `securityPolicyPath` is empty, the skill reports that the policy is not
  set.
