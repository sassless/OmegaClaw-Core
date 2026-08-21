# Reference — Communication Skills

`send` and `receive` are defined in `src/channels.metta`; `websearch` and `version` in `src/skills.metta`. Which transport `send` and `receive` talk to is decided once, at `initChannels` time, by the `commchannel` configuration parameter (see [reference-configuration.md](./reference-configuration.md)).

---

## `send`

### Signature
```metta
(send "message")
```

### Purpose
Send a message to the currently active communication channel — `irc`, `telegram`, `slack`, `mattermost`, `websocket`, or `test`, the mock channel the autotests run against.

### Parameters
- `message` — the text to send. Newlines are replaced with `\n` before transmission.

### Returns
Nothing meaningful on a delivery. A suppressed duplicate returns the bare atom `_`, which is the only way to tell the two apart.

### Examples
```metta
(send "Hello — deployment completed at 10:02.")
```

### Notes / Limits
- **Deduplication:** `send` drops the call when `message` is identical to the previously sent one. Details worth knowing:
  - The comparison is on the raw argument, before newline escaping; `&lastsend` holds the raw form too.
  - It is one slot, not a set. `A, B, A` sends all three messages; `A, A` sends one.
  - `&lastsend` is written *before* the transport call, so a delivery that fails still blocks an identical retry.
  - In the log, a delivered message shows as `COMMAND_RETURN: ((send "…") …)`; a suppressed one shows the bare `_`. The channel alone cannot tell you which happened.
- A `(cut)` sits immediately before the transport call so that backtracking inside the command dispatch cannot replay a `send`.
- Channel selection is set at `initChannels` time via `commchannel` and cannot be changed afterwards.

---

## `receive`

### Signature
```metta
(receive)
```

### Purpose
Return the latest message received on the active channel since the previous call. Invoked once per loop iteration by `src/loop.metta`.

**This is loop machinery, not an agent skill.** `receive` is not in the parser's command set, so a model that emits `receive` gets `UNKNOWN_SKILL_CALL` back rather than a message.

### Parameters
None.

### Returns
A string. Empty if nothing new has arrived.

### Examples
The loop wraps it:

```metta
(let $msgrcv (string-safe (repr (receive))) ...)
```

### Notes / Limits
- Resolves through the registry, not through per-channel branching: `(receive)` → `commChannelReceive` → `channels.commChannelReceive()` → `.receive()` on whichever object the active plugin registered under `commchannel`. The contract every adapter implements is `CommChannel` in `src/channels.py` — `start`, `stop`, `receive`, `send`.
- The loop treats an unchanged message as "no new input" via the `&prevmsg` state.

---

## `websearch`

### Signature
```metta
(websearch "query")
```

### Purpose
Perform a web search through the `src/websearch.py` adapter.

### Parameters
- `query` — the search string.

### Returns
A pseudo-s-expression of the form `((TITLE: … SNIPPET: …) …)`, ready to feed back into the prompt.

### Examples
```metta
(websearch "MeTTa AtomSpace tutorial")
```

### Notes / Limits
- Backed by DuckDuckGo through the `ddgs` package. It needs no API key and is the one Python-side call that goes out directly rather than through `GATEWAY_URL`.
- Result URLs are dropped: the adapter collects `title`, `url` and `snippet` but renders only title and snippet, so the agent cannot cite or follow a link.
- The result count is fixed at 10; the `max_results` parameter of `websearch.search` is declared but never passed on.
- Any exception returns the empty string, which is indistinguishable from "no results".
- `search` also appears in the parser's allowlist but has no MeTTa definition — a `search …` call is not rejected and evaluates to nothing useful. Use `websearch`.

---

## `version`

### Signature
```metta
(version)
```

### Purpose
Report which build of OmegaClaw is running. The loop also calls it once at startup and sends the result to the channel.

### Parameters
None.

### Returns
`OmegaClaw version=<git describe --tags --dirty --always>` when the checkout is a git repository. Otherwise the contents of the `version` file baked into the image, in the same `OmegaClaw version=…` shape, and `OmegaClaw unknown` when neither is available.

### Examples
```metta
(version)
```

### Notes / Limits
- Implemented by `helper.omegaclaw_version`.
- The `git describe` call is skipped unless the project root itself contains `.git`, so it cannot pick up the version of a parent repository, and it is capped at 3 seconds.
