# Reference — Python and Prolog Bridges

MeTTa handles reasoning and control flow; bridges handle everything that needs a library ecosystem.

Most `src/*.metta` modules are thin wrappers: the MeTTa side declares a function, and the body is a single `py-call` into the module of the same name. The exceptions are `loop.metta`, `skills.metta` and `memory.metta`, which carry real logic.

## `src/logger.py`

Centralized logging setup. Called once at startup from `loop.metta`; all Python modules obtain a logger through `get_logger` rather than calling `logging.getLogger` directly.

| Function | Purpose |
|---|---|
| `setup_logging()` | Configures the root logger using the configuration script passed as a parameter. Idempotent — safe to import from multiple modules. Falls back to stderr-only if the configuration script is not found. |
| `get_logger(name)` | Returns `logging.getLogger(name)`. Use this instead of calling `logging.getLogger` directly so the relationship to the shared setup is explicit. |
| `log_debug(msg, module)` | MeTTa bridge — write a DEBUG entry under logger `module`. |
| `log_info(msg, module)` | MeTTa bridge — write an INFO entry under logger `module`. |
| `log_warning(msg, module)` | MeTTa bridge — write a WARNING entry under logger `module`. |
| `log_error(msg, module)` | MeTTa bridge — write an ERROR entry under logger `module`. |

The MeTTa bridge functions are invoked by calling `log` helper function defined in `src/log.metta`, passing the source filename as `module` so log lines are attributed correctly:

```metta
(log INFO "memory" "Initializing memory")
```

**Logging configuration**

By default, logging is configured from:

```text
config/logging.conf
```

The default configuration writes logs to stderr using the format:

```text
YYYY-MM-DD HH:MM:SS | LEVEL    | module | message
```

Docker container stdout/stderr is captured automatically and can be viewed with:

```bash
docker logs -f omegaclaw
```

**Custom logging configuration**

Users can provide their own Python logging config file to control log levels, handlers, formatters, output destinations, and per-module logging behavior.

When starting OmegaClaw through the launcher script, pass:

```bash
scripts/omegaclaw start -l /path/to/logging.conf
```

For standalone runs without Docker, pass the config path to the MeTTa runtime:

```bash
sh run.sh run.metta logConfigPath=/path/to/logging.conf
```

If no custom config is provided, OmegaClaw uses `config/logging.conf`. If the configured file is missing, OmegaClaw falls back to basic stderr logging.

## `src/config.py`

Parameter resolution. Backs `configure` and `configGetByKey` in `src/config.metta`.

| Function | Purpose |
|---|---|
| `init_config(command_line)` | Parses the MeTTa command line, loads the configuration file, and clears the resolution cache. Called first in the startup sequence. |
| `config_get_by_key(key, default=None)` | Resolves one parameter from the command line, then `OMEGACLAW_<key>`, then the configuration file, then `default`. |
| `command_line_to_dict(list)` | Turns `key=value` arguments into a dictionary. Built in a loop, so a repeated key keeps its **last** value. |

The first value resolved for a key is cached for the lifetime of the process, including when the value came from the default. See [reference-configuration.md](./reference-configuration.md) for the full parameter list and for why the environment level has no effect inside the Docker image.

## `src/plugin.py`

Plugin loader. Reads [`config/plugins.yaml`](/config/plugins.yaml), whose path is fixed relative to the repository root and cannot be redirected through configuration.

| Function | Purpose |
|---|---|
| `listPlugins()` | Returns `(loader, name, location)` triples from the YAML file. `loader` is `python` or `metta`; `{REPO}` in `location` expands to the repository root. |
| `loadPythonPlugin(name, location)` | Imports `<location>/<name>.py`, adds the folder to `sys.path` so multi-file plugins can import their own modules, then calls the module's `loadOmegaClawPlugin()`. |
| `addLocationToPath(location)` | Puts a plugin's folder on `sys.path`. Also used by the MeTTa loader, so a MeTTa plugin can `py-call` into its own Python file. |

Every plugin module must define `loadOmegaClawPlugin()`. That function is where the plugin registers its callbacks — a channel, a provider, or a MeTTa skill.

Failures are not symmetric. A MeTTa plugin that fails to load is logged and skipped; a Python plugin that raises during import aborts startup, because nothing wraps the module execution. Since channels and providers are themselves plugins and all of them are loaded regardless of `commchannel` and `provider`, a broken import in a component you do not use still stops the agent.

## `src/channels.py` and `src/providers.py`

Two registries with the same shape.

| Function | Purpose |
|---|---|
| `registerCommChannel(id, channel)` | Adds a `CommChannel` implementation under the name used by `commchannel`. |
| `commChannelStart(commchannel)` | Looks the name up and calls `start()` on it. |
| `commChannelReceive()` / `commChannelSend(message)` | Forward to the selected channel. |
| `registerLLMProvider(id, provider)` | Adds an `LLMProvider` implementation under the name used by `provider`. |
| `llmProviderStart(provider)` | Looks the name up and calls `start()` on it. |
| `llmProviderChat(prompt, max_tokens, reasoning_mode)` | Forwards to the selected provider. |

The `CommChannel` and `LLMProvider` base classes in these modules define the contract a plugin has to satisfy: `start`, `stop`, and either `receive`/`send` or `chat`.

## `providers/lib_llm_ext.py`

Shared implementation behind the concrete providers in `providers/`. Provider classes derive from it rather than exporting per-vendor functions.

| Symbol | Purpose |
|---|---|
| `AbstractAIProvider` | The interface: `name`, `chat`, `is_available`, `stop`. |
| `AIProvider` | OpenAI-compatible implementation used by every shipped provider. Holds the client, splits the prompt, sends the request, cleans the reply. |
| `initLocalEmbedding()` | Loads the local embedding model once at startup. |

`AIProvider` splits the incoming content on the `:-:-:-:` separator into a system part and a user part, and routes the request through `GATEWAY_URL` when it is set. The proxy path is derived from the provider name in lower case, which is why each provider has a matching `location` block in [`proxy/nginx.conf.template`](/proxy/nginx.conf.template).

The `reasoning` argument is accepted by `AIProvider.chat` but not placed in the request body; only the `OpenAI` provider forwards it, and `ASIOne` substitutes a fixed thinking budget.

## `src/rag.py`

Embeddings and the ChromaDB collection behind `remember`, `query` and the knowledge import.

| Function | Purpose |
|---|---|
| `init_knowledge(embedding_selection)` | Seeds the collection from the knowledge-priors markdown, skipping files whose stored hash is unchanged. |
| `local_embed_batch(texts)` | Embeds with the model bundled into the image. Used when `embeddingprovider = Local`. |
| `openai_embed(text)` / `openai_embed_batch(texts)` | Embeds through the OpenAI API. Used when `embeddingprovider = OpenAI`; the model name is a constant in this module. |

The database path comes from `CHROMA_DB_PATH` and defaults to `/PeTTa/chroma_db`. The collection is created without an embedding function, so vectors are always supplied by the caller.

## `src/fileio.py`

Backs the file-writing skills.

| Function | Purpose |
|---|---|
| `write_file(path, content)` | Writes the file, then reads it back and returns size, sha256 and a snippet, so the agent reports what actually landed on disk rather than what it intended to write. |
| `append_file(path, content)` | Appends, inserting a newline first when the existing file does not end with one. Same read-back result. |
| `write_file_b64(path, content_b64)` | Decodes base64 and writes the bytes. Preferred when the content contains quotes, backslashes or newlines. |

This module enforces no path restrictions of its own. Access control comes from the Landlock policy in `profile/policy.yaml`, applied at startup.

## `src/helper.py`

Parsing of the model's reply, plus small utilities used by the loop.

| Function | Purpose |
|---|---|
| `balance_parentheses(s)` | Turns the model's raw reply into a list of skill calls. Despite the name it does not repair unbalanced parentheses: it splits the reply into command blocks, strips one layer of wrapping, quotes the arguments, and returns whatever s-expressions result. An unterminated argument stays unterminated. |
| `split_command_blocks(s)` | Splits the reply into blocks. A line begins a new block only when `starts_command_line` accepts it; every other line is appended to the block above. This is how multi-line arguments work — there is no separate syntax for them. |
| `starts_command_line(line)` | Strips one opening parenthesis, takes the first token, and reports whether it is in `LLM_COMMANDS`. |
| `add_llm_command(command)` / `remove_llm_command(command)` | Register and unregister a runtime skill name. `remove_llm_command` refuses to drop a statically defined name. |
| `quote_arg(x)` | Adds the quoting the parser stripped, after the block boundaries are known. |
| `normalize_string(x)` | Renders a skill return value into a string safe to embed in the next prompt. |
| `around_time(ts, k)` | Backs `(episodes ts)` — returns `k` lines of `memory/history.metta` around `ts`. |
| `omegaclaw_version(repo_root=None)` | Returns the version string baked in at image build time. |

`LLM_COMMANDS` is the gate that decides where one command ends and the next begins. It starts as a copy of `STATIC_LLM_COMMANDS` and grows when a skill registers itself through `add-skill`. A name that is not in the set is not recognised as the start of a command, so the line is swallowed into the argument of the command above it — which is why defining a skill in MeTTa is not on its own enough to make it callable.

The check is positional. A name the parser does not know produces `UNKNOWN_SKILL_CALL` only when it opens a block; the same name further down a block is absorbed silently.

## `src/websearch.py`

DuckDuckGo search through `ddgs`. The only component that reaches the network without going through the proxy, and the only one that needs no credentials.

| Function | Purpose |
|---|---|
| `search_(query, max_results=10)` | Performs a DuckDuckGo text search and returns a list of dictionaries containing `title`, `url` and `snippet`. |
| `search(query, max_results=10)` | Wraps `search_` and formats the results into a MeTTa-like parenthesized string of titles and snippets. Returns an empty string when the search fails, which is indistinguishable from a search that found nothing. |

## `src/skills.pl`

Prolog helpers imported via `import_prolog_functions_from_file`.

| Predicate | Purpose |
|---|---|
| `shell/2` | Runs a command through `timeout -k 1s 5s sh -c`, capturing stdout and stderr into the same result. Returns `timeout_error` when the limit is hit. |
| `first_char/2` | Returns the first character of a string — used by the loop to detect whether the LLM produced a valid s-expression. |
| `gc/1` | Forces a garbage collection. |
| `read_file_tail/3` | Reads the last `MaxChars` characters of a file. Backs the `maxHistory` window over `memory/history.metta`. |

`shell/2` performs no filtering of the command text. The instruction to avoid apostrophes lives in the system prompt, not in this predicate.

## Calling conventions

- MeTTa to Python: `(py-call (module.function arg1 arg2 ...))`.
- MeTTa to Prolog: `(translatePredicate (predicate ...))` for side-effecting predicates, or `!(import_prolog_function name)` to lift a Prolog function into MeTTa.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — where these bridges are invoked.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to add new bridges.
- [reference-configuration.md](./reference-configuration.md) — the parameters these modules read.
