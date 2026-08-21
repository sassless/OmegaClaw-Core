# Internals — Extension Points

Where to plug in new behavior, in order of increasing depth.

## Add a skill

Most common extension. A skill is callable only when **both** of these are true, so a catalogue line on its own does nothing:

1. The name is in the parser's command set. Either add it to `STATIC_LLM_COMMANDS` (`src/helper.py:18-34`), or register it at runtime with `add-skill`, which calls `helper.add_llm_command` for you. If the name is unknown to the parser, `helper.balance_parentheses` rewrites the call into `(Error UNKNOWN_SKILL_CALL ...)` and the loop reports it back to the model instead of executing anything.
2. A `(= (my-skill $arg) ...)` definition exists — pure MeTTa, or a `py-call` / `translatePredicate` wrapper.

Plus a description line so the model learns the skill exists: a string inside `getStaticSkills` (`src/skills.metta:8`, the literal list; `getSkills` is the function that merges it with the dynamic ones), or the `$description` argument of `add-skill`.

Full walkthrough: [tutorial-03-writing-a-custom-skill.md](./tutorial-03-writing-a-custom-skill.md).

## Register skills, prompt sections and heartbeats at runtime

Everything a plugin adds goes through six functions in `src/skills.metta`. All of them work at any point after `initPlugins`, and all are undone by their `remove-` counterpart.

| Function | Effect |
|---|---|
| `(add-skill $function $description $arguments)` | Registers `$function` with the response parser and adds a catalogue atom `(= (dynamic-skill $function) $text)`. `$arguments` is a tuple of placeholder symbols, `()` when the skill takes none. |
| `(remove-skill $function)` | Drops the catalogue atom and unregisters the name — except for names in `STATIC_LLM_COMMANDS`, which `helper.remove_llm_command` refuses to remove. Returns `True`. |
| `(add-prompt-extension $handle $text)` | Adds `(= (prompt-extension $handle) $text)`. All extensions are joined with newlines by `getPromptExtensions` and inserted between the `SKILLS:` and `OUTPUT_FORMAT:` blocks. |
| `(remove-prompt-extension $handle)` | Removes that block. Returns `True`. |
| `(add-heartbeat-listener $handle $callback)` | Adds `(= (heartbeat-listener $handle $iter) ($callback $iter))`. `$callback` is a lambda of one argument, e.g. `(\|-> ($iter) (my-tick $iter))`. |
| `(remove-heartbeat-listener $handle)` | Unsubscribes. Returns `True`. |

The catalogue line `add-skill` renders is `"- <description>: <function> <arg> <arg>"`, which is exactly the shape of the static entries.

`heartbeat` fires once per iteration, before `receive` and outside the `&loops` gate, so listeners keep running while the agent is idle. That is how the openclaw plugin collects off-loop results.

Each of the three mechanisms has a placeholder equation returning `(empty)` — `(dynamic-skill placeholder)`, `(prompt-extension placeholder)`, `(heartbeat-listener placeholder $_)` — so an agent with nothing registered still evaluates cleanly. Do not remove them.

Live examples: `plugins/workflow/workflow.metta` (two skills plus a prompt extension) and `plugins/openclaw/openclaw.metta` (one skill plus a heartbeat listener).

## Add a channel

Channels are plugins. There is no branching in `src/channels.metta` — it forwards to a registry.

1. New Python module `channels/myadapter.py` with a class implementing the `CommChannel` contract (`src/channels.py:7-24`): `start()`, `stop()`, `receive() -> str`, `send(message)`.
2. A module-level `loadOmegaClawPlugin()` that calls `channels.registerCommChannel("myadapter", MyChannel())`. The loader calls that function and nothing else, so registration must happen inside it. Pattern: `channels/mockchannel.py:41-42`.
3. A record in `config/plugins.yaml` with `loader: python` and `location: "{REPO}/channels"`. The file name must match `name`.
4. Any new parameters declared as `(= (MY_*) (empty))` and bound by `configure`.

Select it at run time with `commchannel=myadapter`. Ids registered at HEAD: `irc`, `telegram`, `slack`, `mattermost`, `websocket`, and `test` — the last one from `channels/mockchannel.py`, which is what CI runs against.

Full walkthrough: [tutorial-04-adding-a-channel.md](./tutorial-04-adding-a-channel.md).

## Add an LLM provider

Providers are plugins too, resolved out of `_llmProviderRegistry` by `(provider)`. `src/loop.metta` contains no provider branching; it calls `(llmProviderChat $send (maxOutputToken) (reasoningMode))`.

1. Implement the `LLMProvider` contract (`src/providers.py:7-20`): `start()`, `stop()`, and `chat(prompt, max_tokens=6000, reasoning_mode="medium") -> str`.
2. Call `providers.registerLLMProvider("MyProvider", MyProvider())` from `loadOmegaClawPlugin()`. Pattern: `providers/mockprovider.py:19-20`.
3. Add the module to `config/plugins.yaml` with `loader: python` and `location: "{REPO}/providers"`.
4. Select it with `provider=MyProvider`, or change the `configure provider ...` default.

An OpenAI-compatible endpoint needs no new module at all: `providers/openaiapi.py` registers `OpenAIAPI` plus two preconfigured instances (`ASICloud`, `Anthropic`) from the same class.

## Change the prompt

The agent's identity and values are in `memory/prompt.txt`; `getPrompt` prefers `memory/prompt_<provider>.txt` when that file exists and falls back to `memory/prompt.txt`, then to an empty string. The run-time template that sandwiches it is `getContext` in `src/loop.metta`. Edit carefully — the output-format instruction is what keeps the LLM emitting lines the response parser can turn into skill calls. To add a block without touching the core, use `add-prompt-extension`.

## Change the embedding model

In `src/memory.metta`, `embed` dispatches on `embeddingprovider`:

```metta
(= (embed $str)
   (if (== (embeddingprovider) Local)
       (py-call (lib_llm_ext.useLocalEmbedding (string-safe $str)))
       (py-call (rag.openai_embed (string-safe $str)))))
```

To add a new backend, add a branch and implement the Python function. Two things are hardcoded on the OpenAI path: the model is the `EMBEDDING_MODEL` constant in `src/rag.py`, and `rag.init_knowledge` accepts only `"Local"` or `"OpenAI"` — any other value raises `ValueError`.

## Change the reasoning library

`lib_nal.metta` and `lib_pln.metta` are plain MeTTa files loaded by `lib_omegaclaw.metta`. Add new rule definitions directly, or swap in a different logic library entirely — the only required surface is whatever operator the LLM invokes through `(metta ...)`.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — the loop is the host for all of the above.
- [reference-python-bridges.md](./reference-python-bridges.md) — bridge conventions.
