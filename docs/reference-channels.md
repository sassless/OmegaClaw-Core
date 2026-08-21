# Reference — Channels

Channels are the I/O surface the agent uses to talk to the outside world. Adapters live in `channels/`; the registry they plug into is `src/channels.py`, and `src/channels.metta` is a thin MeTTa wrapper over that registry.

## The adapter contract

An adapter is a Python module that subclasses `channels.CommChannel` (defined in `src/channels.py`) and exposes a module-level `loadOmegaClawPlugin()` that registers an instance of it:

| Method | Purpose |
|---|---|
| `start(self)` | Read the adapter's configuration keys, open sockets, spawn listener threads. |
| `stop(self)` | Stop the channel and release its resources. |
| `receive(self) -> str` | Return the next unread inbound message as a string. Returns `""` if none. |
| `send(self, message)` | Post an outbound message. |

All four raise `NotImplementedError` in the base class. `stop()` is implemented by every adapter but nothing calls it: `src/channels.py` has no `commChannelStop` and `src/channels.metta` has no wrapper for one.

```python
import channels

class MyChannel(channels.CommChannel):
    ...

def loadOmegaClawPlugin():
    channels.registerCommChannel("myname", MyChannel())
```

`loadOmegaClawPlugin` is mandatory — the plugin loader raises `RuntimeError` for a module that does not define it (`src/plugin.py`). The id passed to `registerCommChannel`, not the module filename, is what `commchannel` has to be set to, and for two adapters the two differ:

| Module | Registered id |
|---|---|
| `channels/irc.py` | `irc` |
| `channels/telegram.py` | `telegram` |
| `channels/slack.py` | `slack` |
| `channels/mattermost.py` | `mattermost` |
| `channels/wschat.py` | `websocket` |
| `channels/mockchannel.py` | `test` |

Function names such as `start_irc` or `send_message` are an internal convention of the existing adapters. The engine never looks for them.

## Dispatch

The MeTTa side does not branch on `commchannel`. `src/channels.metta` forwards straight into the Python registry:

```metta
(= (initChannels)
   (progn (log INFO "channels" "Initializing channels")
          (configure commchannel irc)
          (commChannelStart (commchannel))))

(= (receive)
   (commChannelReceive))
```

`commChannelStart` looks the id up in `_commChannelRegistry`, keeps the channel it found and calls `.start()` on it. `commChannelReceive` and `commChannelSend` then forward to `.receive()` and `.send()` of that one channel.

Every channel module listed in `config/plugins.yaml` is loaded on every start, whatever `commchannel` says — all six register themselves. `commchannel` only decides which registered object gets started. Two consequences:

- An import error in any channel module breaks startup even when that channel is not the selected one.
- An id that was never registered makes `commChannelStart` fail. `scripts/omegaclaw` rejects unknown `-t` values before the container is started at all.

Outbound text is deduplicated in `src/channels.metta`: `(send $msg)` compares `$msg` with `&lastsend`, the previously sent message, and skips `commChannelSend` entirely on an exact match. The agent can answer correctly and still put nothing on the wire, so check sends against `COMMAND_RETURN: ((send ...)` in the log rather than against the channel alone. The version banner emitted right after `initChannels` calls `commChannelSend` directly and bypasses both the dedup and the newline escaping.

## `channels/irc.py`

IRC adapter over a raw TCP socket.

- Configuration: `IRC_channel` (`##omegaclaw`), `IRC_server` (`irc.quakenet.org`), `IRC_port` (`6667`), `IRC_user` (`omegaclaw`).
- Reconnects automatically with exponential backoff, 1s doubling up to 30s.
- Outbound text is wrapped at 400 characters and queued through `PendingMessages`.
- Inbound traffic is gated by `channels/auth.py`. While the gate is enabled, the first nick to send `auth <secret>` or `/auth <secret>` becomes the owner and every other speaker is ignored; nicks are compared stripped and lowercased. While the gate is disabled — no secret configured, or the proxy status endpoint unreachable — every speaker is allowed through. The owner is persisted and survives a restart, see [`channels/auth.py`](#channelsauthpy) below.
- Does not use the nginx proxy.

## `channels/mattermost.py`

Mattermost adapter: REST for posting, a WebSocket for receiving.

- Configuration: `MM_URL` (`https://chat.singularitynet.io`), `MM_CHANNEL_ID` (a hardcoded default that the source itself annotates as a channel *name* rather than an id).
- With `GATEWAY_URL` set — always the case inside the container — requests go to `{proxy}/mattermost` and nginx injects the credentials. `MM_BOT_TOKEN` is read from the environment only in direct mode.
- Reconnects with exponential backoff, 1s doubling up to 30s.
- Outbound messages are not chunked; long text is posted in one piece.
- Uses the same `auth <secret>` ownership gate as the IRC, Telegram, and Slack adapters.
- `scripts/omegaclaw` lists `mattermost` in its `-t` help text, but its channel validation accepts only `irc`, `telegram`, `slack`, `websocket`, and `test`. `-t mattermost` exits with `Unsupported commchannel: mattermost`; select the channel with `commchannel=mattermost` on the MeTTa command line instead.

## `channels/telegram.py`

Telegram adapter using Bot API long polling.

- Configuration: `TG_CHAT_ID` (empty — auto-binds to the first valid inbound chat), `TG_POLL_TIMEOUT` (`20`).
- With `GATEWAY_URL` set, calls go to `{proxy}/telegram` and nginx rewrites the bot token into the request path. `TG_BOT_TOKEN` is read from the environment only in direct mode.
- Messages from other chats are dropped before the auth gate is consulted.
- Outbound messages are chunked at 3900 characters and queued through `PendingMessages`.
- Uses the same one-time `auth <secret>` ownership gate as the other adapters.

## `channels/slack.py`

Slack adapter using Slack Web API polling.

- Configuration: `SL_CHANNEL_ID` (empty — auto-binds to the first channel where auth succeeds), `SL_POLL_INTERVAL` (`60`), `SL_MAX_FILE_SIZE_MB` (`5`).
- The bot user must already be invited to the target channel.
- With `GATEWAY_URL` set, Web API calls go to `{proxy}/slack` and nginx injects the bot token. `SL_BOT_TOKEN` is read from the environment only in direct mode.
- Adapter respects Slack `Retry-After` backoff on HTTP 429.
- `SL_POLL_INTERVAL` is a ceiling, not a floor: `start_slack` clamps it with `min(60, value)`, so anything above 60 becomes 60, and the poll loop sleeps `max(1, value)` seconds. `scripts/omegaclaw` passes `SL_POLL_INTERVAL=2` by default, so a normal launch polls every two seconds.
- Uses the same one-time `auth <secret>` ownership gate as the other adapters.

### Attachments

Slack is the only adapter that handles attachments, and only inbound ones — nothing in the codebase sends a file.

- Messages carrying a `subtype` are skipped, except `file_share`.
- Files are fetched only after the sender has passed the auth gate with `allow`.
- Each file contributes a line `[ATTACHMENT: {name} | {mimetype} | {size} bytes | {url}]` to the message text handed to the model.
- A file whose Slack-reported `size` is within `SL_MAX_FILE_SIZE_MB` is downloaded to `/tmp/slack_attachment_{name}`, with `/` in the name replaced by `_`, and a `[SAVED: {path}]` line is appended. The agent then reads it with its own `read-file` or `shell` skills; the bytes never travel through the channel API. Attachments with the same name overwrite each other.
- Failures are reported to the model as text rather than raised: `[ATTACHMENT DOWNLOAD FAILED: ...]`, `[ATTACHMENT DOWNLOAD FAILED, NO DATA: ...]`, `[ATTACHMENT DOWNLOAD SIZE TOO LARGE, FAILED: ...]`, `[ATTACHMENT DOWNLOAD BAD URL, FAILED: ...]`.
- Downloads accept only `https` URLs whose host is `files.slack.com` or `slack-files.com`. In proxy mode the original path is re-pointed at `{proxy}/slack-files` and nginx adds the bot token. A response whose `Content-Type` contains `text/html` is treated as a login or error page and discarded.
- `/tmp` inside the container is a 64 MB tmpfs shared with the nginx temporary files, which bounds how much can usefully be downloaded.

## `channels/wschat.py`

Minimal JSON chat adapter over a WebSocket connection. Selected with `commchannel=websocket` — the Python module is `wschat`, exposing `start_websocket` / `stop_websocket` alongside the usual `getLastMessage` / `send_message`.

- `start_websocket(ws_url, ws_token)` — connect and spawn the listener thread. `WSChannel.start()` resolves both values through the configuration first (`WS_URL`, `WS_TOKEN`); the `WS_URL` / `WS_TOKEN` environment variables are consulted only when the resolved value is empty. `WS_URL` is required when `commchannel=websocket`; if it is missing, OmegaClaw still starts, the adapter logs that the WebSocket channel is disabled, and the process continues without an active WebSocket connection.
- `stop_websocket()` — stop the listener thread and close the socket.
- Requires the `websockets` Python package. It is imported lazily, so a missing package disables this channel instead of breaking startup.
- When `WS_TOKEN` is set it is sent as an `Authorization: Bearer <token>` header. Unlike the IRC/Telegram/Slack adapters there is no one-time `auth <secret>` gate — `channels/auth.py` is not imported at all, and trust is established by the endpoint URL and bearer token.
- Reconnects automatically with exponential backoff (1s → 30s, ±20% jitter) and is safe to start once at process startup.

### Frame protocol

All frames are UTF-8 JSON objects with a `type` field; unknown types are logged and ignored.

| Direction | `type` | Payload |
|---|---|---|
| server → client | `user_message` | `{seq, text}` — a new inbound message. `seq` is a server-assigned, monotonically increasing integer used for ordering and dedup. |
| server → client | `ack` | `{seq, client_seq}` — acknowledges a previously sent `agent_message`. Informational; logged only. |
| server → client | `error` | `{code, message}` — server-side error. Logged; the connection is left open. |
| client → server | `agent_message` | `{client_seq, text}` — an outbound message. `client_seq` is a client-generated UUID idempotency key so the server can dedupe retries after reconnect. |
| client → server | `resume` | `{last_seen_seq}` — sent on every (re)connect so the server can replay any `user_message` with `seq > last_seen_seq` (null on the first connect). |

### Delivery semantics

- Inbound messages buffer in a bounded inbox (256 entries). `getLastMessage` drains it, joins pending texts with `" | "`, and advances `last_seen_seq`.
- Outbound messages produced while disconnected queue in a bounded outbox (100 entries) and flush after the next successful connect, before any new inbound traffic is processed. This adapter uses its own deque, not `PendingMessages`.
- Duplicate `user_message` frames (`seq <= last_seen_seq`, or already buffered) are dropped, so server replays after `resume` are idempotent.

## `channels/mockchannel.py`

The channel the automated tests run against. It registers as `test`, so `commchannel=test` or `-t test` selects it; the module filename deliberately does not match the id.

- Connects over TCP to the mock controller in `Autotests/mock/comm.py`, addressed by the `TEST_SERVER_IP` environment variable. That variable is its only input — it never calls `config_get_by_key`.
- No auth gate. It does not import `channels/auth.py`, so every message from the mock server reaches the agent and no channel owner is ever recorded. Ownership scenarios cannot be exercised on this channel; their coverage lives in `tests/test_auth_standalone.py` and `tests/test_channel_auth_gating.py` instead.
- No delivery queue, no message chunking, no reconnect, no logging, no proxy.

`.github/workflows/autotests.yml` runs the whole mandatory suite against a single container started with `-p Test -t test`.

## `channels/auth.py`

Shared ownership gate. `irc`, `telegram`, `slack`, and `mattermost` import it; `wschat` and `mockchannel` do not.

- `is_auth_enabled()` decides whether gating happens at all, and caches the answer for the lifetime of the process. Without a proxy it is true when `OMEGACLAW_AUTH_SECRET` is non-empty. With `GATEWAY_URL` set it reads `enabled` from `{proxy}/auth/status`. Any failure — timeout, unreachable proxy, malformed JSON — is logged as a warning and treated as *disabled*, after which the channel accepts everyone.
- `verify_token(candidate)` compares the candidate with the secret, either locally through `hmac.compare_digest` or through `{proxy}/auth/verify` with an `X-Auth-Token` header. Here a failure denies.
- A candidate token is produced only when the message starts with `auth` or `/auth` followed by a space; ordinary text is never passed as one.
- `authenticate_channel_user(channel_identifier, user_id, auth_candidate)` returns `allow`, `auth_bound`, or `ignore`. A persisted owner outranks the secret: once one exists for that channel, the matching user gets `allow` and everybody else `ignore`, restart or not.
- The owner is appended as a JSON line to `memory/.channel/authenticated-user.json`. The directory is derived from the repository root, not from the `memoryDirectory` configuration key. Under Docker that path is on the `omegaclaw-memory` volume, so the binding outlives the container.
- Only one owner is recorded per process; a second binding attempt is refused with a warning.
- A message that resolves to `ignore` is dropped silently — no reply is sent and nothing enters the agent's inbox. On `auth_bound` the adapter answers `Authentication successful for <name>.` through its own `send_message`, bypassing the MeTTa `send` path and its dedup; the message carrying the secret never reaches the prompt.

## `channels/delivery_queue.py`

`PendingMessages`, a thread-safe ordered outbox used by `irc`, `telegram`, `slack`, and `mattermost`.

- `put` / `extend` append to the tail; `flush(deliver, ready)` delivers in FIFO order for as long as `ready()` holds. Each adapter supplies its own `ready` — typically "connected, and a target channel is known".
- `flush` acquires its lock non-blocking: when another thread is already flushing, the call returns immediately instead of queueing behind it.
- The head is removed only after `deliver` returns. A failing send therefore retains the message and lets the exception reach the adapter's `_flush_outbox` wrapper, which logs a warning. Delivery is at-least-once — a request that arrived but whose response was lost is sent again.
- The queue is in-memory only; anything undelivered is lost when the process restarts.

## Web search

`websearch` is a skill, not a channel, and its backend lives in `src/websearch.py` rather than in `channels/`. See [reference-python-bridges.md](./reference-python-bridges.md).

## Adding a new channel

See [tutorial-04-adding-a-channel.md](./tutorial-04-adding-a-channel.md).

## Related reference

- [reference-skills-communication.md](./reference-skills-communication.md) — the MeTTa surface (`send`, `receive`, `websearch`).
- [reference-configuration.md](./reference-configuration.md) — channel parameters.
