# Internals — `src/loop.metta`

The heart of OmegaClaw. One function, `omegaclaw`, tail-recurses forever.

## Entry

```metta
(= (omegaclaw) (omegaclaw 1))
```

Outer `run.metta` simply calls `(omegaclaw)`.

## On turn 1 (`$k == 1`)

Ten calls run, in this order:

1. `(initConfig)` — resets the configuration cache and loads `config/config.yaml` (`src/config.metta:3-6`).
2. `(initLoop)` — configures all loop parameters (see [reference-configuration.md](./reference-configuration.md)).
3. `(initLogger)` — applies `logConfigPath` (`src/log.metta:5-8`).
4. `(applySecurityPolicy)` — applies the Landlock policy named by `securityPolicyPath` (`profile/policy.metta:5-9`).
5. `(initMemory)` — configures memory parameters and loads the local embedding model when `embeddingprovider` is `Local`.
6. `(initKnowledge)` — indexes `knowledge-priors/*.md` into ChromaDB, if that folder exists.
7. `(initPlugins)` — loads every plugin listed in `config/plugins.yaml`.
8. `(initChannels)` — opens the active communication channel.
9. `(commChannelSend (version))` — announces the running version on that channel.
10. `(llmProviderStart (provider))` — starts the selected LLM provider.

Three of those orderings are load-bearing:

- `initPlugins` must precede `initChannels` and `llmProviderStart`. Channels and providers are plugins; both are looked up in registries that plugin loading fills (`src/channels.py:34-41`, `src/providers.py:30-36`).
- `initLoop` must precede `llmProviderStart`, because `(provider)` only acquires a value from `configure provider Anthropic`.
- `initMemory` must precede `initKnowledge`, because `initKnowledge` branches on `(embeddingprovider)`, which `initMemory` sets.

Also creates shared state slots:

- `&prevmsg` — last received human message.
- `&lastresults` — previous turn's skill results, for the next prompt.
- `&loops` — countdown until the agent goes idle.
- `&error` — the current turn's error list, emptied at the start of every dispatch.
- `&nextWakeAt` — the timestamp after which an idle agent grants itself extra turns.
- `&lastsend` — the last message handed to the channel, created when `src/channels.metta` loads and used for `send` deduplication.

## Every turn

1. **Decrement `&loops`** (turns > 1 only).
2. **Build the prompt** — `getContext` assembles `PROMPT + SKILLS + <prompt extensions> + OUTPUT_FORMAT + SAVE_PERMANENT_FILES_DIR + LAST_SKILL_USE_RESULTS + HISTORY + TIME`. The output-format block asks for up to five bare `toolName arg` lines and tells the model **not** to wrap arguments in quotes and not to use variables — the tuple form and the quoting are produced afterwards by `helper.balance_parentheses`, not by the model.
3. **Heartbeat** — `(heartbeat $k)` fires every registered listener. It runs before `receive` and outside the `&loops` gate, so listeners also run on idle turns.
4. **Receive** — `(receive)` via the active channel.
5. **Detect new input** — compare against `&prevmsg`. If different and non-empty, reset `&loops` to `maxNewInputLoops`.
6. **Set next wake** — `&nextWakeAt := now + wakeupInterval`. This sits inside the active branch, so an idle turn does not push the wake time out.
7. **Call the LLM** — `(llmProviderChat $send (maxOutputToken) (reasoningMode))` goes through `src/providers.metta` into `providers.llmProviderChat`, which calls `chat()` on whatever object is registered under `(provider)` in `_llmProviderRegistry`. Registered ids at HEAD: `OpenAIAPI`, `ASICloud`, `Anthropic` (all three from `providers/openaiapi.py`), `ASIOne`, `OpenAI`, `OpenRouter`, `Test`.
8. **Normalize the response** — `helper.balance_parentheses` turns the model's text into a command tuple: it decodes the `_quote_` / `_newline_` placeholders, splits the reply into blocks on lines that begin with a known command name, rewrites a leading `-` into `pin`, strips one outer paren pair, quotes each argument, splits filename from content for `write-file` / `append-file` / `write-file-b64`, and replaces an unrecognized command name with `(Error UNKNOWN_SKILL_CALL "<line>")`. Despite the name it does not add missing parentheses; an unbalanced tail simply ends up inside a quoted argument.
9. **First-character check** — if the result does not start with `(`, it is logged and replaced by a reminder atom, so no dispatch happens this turn.
10. **Parse** — `sread` on the normalized string.
11. **Dispatch skills** — `(collapse (superpose $sexpr))` evaluates one command per branch. `collapse` is what keeps the rest of the turn from re-running once per command.
12. **Record** — `addToHistory` appends human message + response + any errors to `memory/history.metta`, but only when a new message arrived or the command tuple was non-empty.
13. **Save last results** — into `&lastresults` for the next turn's prompt.
14. **Sleep** — `(sleep (sleepInterval))`.
15. **Trim** — `(cut)` discards the iteration's choicepoints, then `(gc)` runs the SWI-Prolog collectors. Without them the endless recursion grows the Prolog stack.
16. **Recurse** — `(omegaclaw (+ 1 $k))`.

## Idle behavior

When `&loops` hits zero and no new message has arrived, the loop skips the LLM call. When `now > &nextWakeAt`, it grants `maxWakeLoops + 1` extra turns so the agent can do self-initiated work (cleanup, summarization, etc.).

## Error handling

Three kinds of error are reported back into `&error`:

- **Parse failure** (`MULTI_COMMAND_FAILURE_NOTHING_WAS_DONE_PLEASE_CORRECT_PARENTHESES_AND_USE_QUOTES_AND_RETRY`) — `sread` did not produce a valid s-expression. The whole dispatch is skipped.
- **Unknown skill name** (`UNKNOWN_SKILL_CALL`) — the command head was not in the parser's `LLM_COMMANDS` set. `helper.balance_parentheses` already turned it into an `(Error ...)` atom, and a pre-check in the loop intercepts it **before** `eval`, so nothing is executed.
- **Per-skill failure** (`SINGLE_COMMAND_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY`) — one skill call raised. The other commands in the same tuple still run.

Each is recorded by `HandleError`, which appends `($msg $cmd)` to `&error` and returns `(ALERT_FAILED $a $b)` in place of the result. Errors are appended to the episodic trace as `ERROR_FEEDBACK:` so the agent sees them and can self-correct.

## See also

- [introduction.md#architecture](./introduction.md#architecture) — the architecture diagram.
- [reference-internals-skill-dispatch.md](./reference-internals-skill-dispatch.md) — how individual skills resolve.
