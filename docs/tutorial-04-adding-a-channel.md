# Tutorial 04 — Adding a Channel

**Goal:** plug OmegaClaw into a new communication surface (Slack, Discord, a REST endpoint, a terminal) by writing a channel adapter.

## Prerequisites

- A local clone.
- Familiarity with the existing adapters in `channels/irc.py`, `channels/telegram.py`, and `channels/slack.py`.

## The channel contract

A channel adapter is a Python module that defines a subclass of `channels.CommChannel` — the base class in `src/channels.py` — and a module-level `loadOmegaClawPlugin()` that registers an instance of it:

- `start(self)` — read the adapter's configuration keys and open whatever sockets and background threads it needs.
- `stop(self)` — shut the channel down and release its resources.
- `receive(self) -> str` — return the next unread inbound message, or an empty string if none.
- `send(self, message)` — post a string outbound.
- `loadOmegaClawPlugin()` — module level, not a method. Calls `channels.registerCommChannel(<id>, <instance>)`. The plugin loader raises `RuntimeError` if a module does not define it.

There is no dispatch in `src/channels.metta` to extend. It only forwards into the Python registry:

```metta
(= (commChannelStart $commchannel)
   (py-call (channels.commChannelStart $commchannel)))

(= (receive)
   (commChannelReceive))
```

`commChannelStart` looks the configured `commchannel` up in the registry and calls `.start()` on whatever was registered under that id; `receive` and `send` then go to that same object. Your adapter adds a registry entry, not a branch.

`stop()` is part of the contract and every existing adapter implements it, but nothing calls it today — there is no `commChannelStop` in `src/channels.py`.

## 1. Write the adapter

Create `channels/myadapter.py`. Model the file on `channels/wschat.py`, which is the smallest complete example:

```python
import channels
from config import config_get_by_key

_inbox = []

class MyChannel(channels.CommChannel):

    def start(self) -> None:
        # read your own parameters here, one config_get_by_key call per key
        endpoint = config_get_by_key("MY_ENDPOINT", "")
        # open a socket, spawn a listener thread, etc.

    def stop(self) -> None:
        ...

    def receive(self) -> str:
        if _inbox:
            return _inbox.pop(0)
        return ""

    def send(self, message: str) -> None:
        # publish message to your surface
        ...

def loadOmegaClawPlugin():
    channels.registerCommChannel("myname", MyChannel())
```

Two details worth getting right the first time:

- Parameters are read in `start()` through `config_get_by_key`, in Python. No MeTTa declaration is involved: adapters do not add `(= (MY_*) (empty))` entries anywhere.
- The id passed to `registerCommChannel` is what `commchannel` has to match. It does not have to equal the module name — `wschat.py` registers as `websocket` and `mockchannel.py` as `test`.

## 2. Register the plugin

An adapter that merely sits in `channels/` is never loaded. Add a record to `config/plugins.yaml`:

```yaml
- name: myadapter
  loader: python
  location: "{REPO}/channels"
```

`name` is the module filename without `.py`, `location` is the directory holding it, and `{REPO}` expands to the repository root. On startup `initPlugins` reads this file, imports each listed module by path and calls its `loadOmegaClawPlugin()` — that call is the only thing that puts a channel into the registry. Without the record, `commChannelStart` fails with `Communication channel plugin myadapter is not registered`.

Every channel in the list is loaded on every run, regardless of which one is selected, and `src/plugin.py` does not wrap `exec_module` in a `try`. An import error in your new module therefore takes down agent startup even when a different channel is active — keep heavyweight or optional imports inside `start()`, the way `channels/wschat.py` defers `websockets`.

## 3. Select the channel

Set `commchannel` to the id you registered. Resolution order is command line, then `OMEGACLAW_commchannel`, then `config/config.yaml`, then the `irc` default:

```bash
sh run.sh run.metta commchannel=myname MY_ENDPOINT=https://example.test
```

`scripts/omegaclaw -t` will not accept the new name: the launcher validates `-t` against a closed list of `irc`, `telegram`, `slack`, `websocket`, and `test`, and exits with `Unsupported commchannel: <name>` for anything else. Add a branch there if you want the new channel startable through the script.

## 4. Optional — ownership gate and outbox

Neither comes for free. An adapter written from the steps above behaves like `wschat`: no access control, no retry on a failed send.

- **Ownership gate.** Follow `channels/irc.py`: call `auth.is_auth_enabled()`, pass an auth candidate to `auth.authenticate_channel_user(<CHANNEL>, user_id, candidate)` only when the message begins with `auth` or `/auth` followed by a space, then act on `allow` / `auth_bound` / `ignore`. See [reference-channels.md](./reference-channels.md) for what the gate persists and when it fails open.
- **Outbox.** Instantiate `PendingMessages` from `channels/delivery_queue.py`, push outbound text into it from `send`, and flush it with a `ready()` predicate once the transport is connected.

## Verification

- On startup the log shows `_initPythonPlugin: loading myadapter plugin from <path> using Python module loader` followed by `registerCommChannel: registering communication channel myname`. That second line is what separates "registered" from "the file exists but nothing loaded it". Python plugins do not emit a `Plugin ... is loaded` line — that one belongs to the MeTTa loader.
- Your adapter's own initialization line appears after `Initializing channels`.
- Messages sent through your surface land in `receive()` and trigger a `HUMAN-LAST-MSG` in the loop.
- `(send ...)` calls reach the surface. Vary the text between attempts: `src/channels.metta` drops a message whose text is identical to the previous one sent, so repeating the same probe looks like a broken channel.

## Next steps

- [reference-channels.md](./reference-channels.md) — the full adapter reference.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — other extension seams.
