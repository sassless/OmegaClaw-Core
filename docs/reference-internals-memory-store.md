# Internals — Memory Store

OmegaClaw uses a **three-tier memory architecture**. Each tier has distinct semantics, persistence, and purpose. Choosing the wrong tier is one of the easier performance and reliability foot-guns.

## Overview

| Tier | Skill | Persistence | Role |
|---|---|---|---|
| 1. Working memory | `pin` | No store of its own — the text survives only as part of the turn's response: in `LAST_SKILL_USE_RESULTS` for one turn, and in the `HISTORY` tail until it scrolls out | Task state — "what am I doing right now?" |
| 2. Long-term embedding memory | `remember` / `query` | Persistent across sessions | Accumulated knowledge, semantic recall |
| 3. AtomSpace | `(metta ...)` | Lives for the life of the process; the entailment operators themselves are stateless | Formal reasoning over truth-valued atoms |

---

## 1. Working memory — `pin`

### Purpose
Holds the agent's current task state: what it is doing, what step comes next, what intermediate results matter.

### How it actually works

`pin` is a constant function:

```metta
(= (pin $x) PIN-SUCCESS)
```

It writes nothing and cannot fail. What carries the note forward is the turn machinery around it:

- the whole normalized response string — `(pin "…")` included, verbatim — is appended to `memory/history.metta`, so it comes back in the `HISTORY` block until it falls out of the trailing `maxHistory` characters, and it survives a restart because that file is on disk;
- `COMMAND_RETURN: ((pin "…") PIN-SUCCESS)` lands in `&lastresults`, which the next prompt shows as `LAST_SKILL_USE_RESULTS` and which is overwritten on the turn after that.

### Characteristics
- **Cheap, unindexed, short-horizon.**
- Several `pin` calls in one turn all survive; there is no single slot being overwritten.
- Ages out of the prompt as `HISTORY` scrolls, not on a fixed number of cycles.

### Use it for
- Multi-step plans currently in flight.
- Intermediate results the next turn needs to see.
- Checklists that do not need to outlive the current task.

### Do not use it for
- Anything you want to retrieve deliberately later — nothing indexes it; use `remember`.
- Structured knowledge the reasoner should act on — atomize into AtomSpace via `(metta ...)`.

---

## 2. Long-term embedding memory — `remember` / `query`

Backed by ChromaDB via a Python bridge (`lib_chromadb`, invoked from `src/memory.metta`).

### Storage format
Each item is a string, its embedding vector, and a timestamp.

- `atom` — the string exactly as the skill received it. `string-safe` is applied only to the copy handed to `embed`, not to what is stored.
- `embedding` — vector from `embed $str`, dispatching on `embeddingprovider`:
  - `Local` → `lib_llm_ext.useLocalEmbedding`.
  - anything else → `rag.openai_embed`, which uses the `text-embedding-3-large` model hardcoded in `src/rag.py` and routes through `GATEWAY_URL` when that key is set.
- `timestamp` — produced by `get_time_as_string`, format `"%Y-%m-%d %H:%M:%S"`.

### Write path

```
(remember $str)
  → py-call (lib_chromadb.remember $str (embed $str) (get_time_as_string))
```

The Python return value is discarded — the skill always answers with the constant `REMEMBER-SUCCESS`, so a failed Chroma write is indistinguishable from a successful one at the skill level.

### Semantic read

```
(query $str)
  → py-call (lib_chromadb.query (embed $str) (maxRecallItems))
```

Returns the top-`k` items by embedding similarity. **Known issue:** query can miss relevant results when embedding similarity thresholds do not match the query phrasing.

### Time-window read

```
(episodes $time)
  → py-call (helper.around_time $time (maxEpisodeRecallLines))
```

Reads lines around `$time` from the **episodic trace**, not the embedding store. See §4 below. The path is hardcoded inside `helper.around_time` as `repos/OmegaClaw-Core/memory/history.metta` and resolved against the process working directory — it is not derived from `memoryDirectory`, so the skill only finds the trace when the agent runs from the expected layout.

### Startup knowledge priors

At startup, OmegaClaw also checks for a folder named `knowledge-priors` in the OmegaClaw-Core project root. If that folder exists and contains Markdown files (`*.md`), their contents are chunked, embedded, and loaded into the ChromaDB `memories` collection for semantic lookup.

The loader skips the step when the folder is missing, or when the folder exists but has no `.md` files. Files whose MD5 is unchanged since the previous run are skipped. Indexed chunks are tagged with `time = knowledge_prior` instead of an actual time.

### Use it for
- Facts that must persist across sessions.
- Verified, grounded premises (attach provenance in the atom body).
- Accumulated user preferences, skills learned, lessons.

### Do not use it for
- Ephemeral scratchpad state — use `pin`.
- Knowledge you intend to reason over in the same turn — atomize via `(metta ...)`.

---

## 3. AtomSpace — where reasoning happens

### Purpose
When the agent needs to **reason rather than just recall**, knowledge must be decomposed into atomic logical statements and loaded into MeTTa's AtomSpace.

### Atomization

Natural-language fact:

> Sam and Garfield are friends, and Garfield is an animal.

Atomized:

```metta
(--> (× sam garfield) friend)  (stv 1.0 0.9)
(--> garfield animal)          (stv 1.0 0.9)
```

Each atom has an **explicit relationship type** and an **explicit truth value**. This is not formatting — it unlocks operations impossible on raw text:

1. **Composable inference** — atoms combined by the engine to derive new knowledge.
2. **Evidence tracking** — when two sources confirm the same fact, revision merges them into stronger belief.
3. **Formal contradiction detection** — an atom with `(stv 0.0 0.9)` explicitly represents strong evidence of negation.
4. **Surgical updates** — individual atoms can be revised without touching the rest of the knowledge base.

### Critical structural constraint

> The NAL and PLN entailment operators are pure functions of their two premise arguments. Each collapses the rule set over the pair it was given; neither reads from the AtomSpace nor writes to it. Whatever a call is meant to reason over has to appear in that call's own arguments.

So a chain of `(metta (|- ...))` calls carries nothing forward by itself: the LLM has to pass the previous conclusion into the next call, pin it, or write it to long-term memory and re-load it on the next cycle.

The enclosing `metta` skill is a different matter. It is `(sread $str)` followed by `eval` **in `&self`**, the live agent space — an `add-atom` issued through `metta` persists for the rest of the process and can change how the agent behaves. The result the skill returns is the serialized form of the evaluated atom, not the atom itself.

---

## 4. The episodic trace

A fourth, plainer store lives alongside the three tiers above: the plain-text file `memory/history.metta`, written by `addToHistory` → `appendToHistory` → `append-file-raw`, a Prolog append that creates the file when it is missing.

The write is conditional: a turn with no new human message **and** an empty command tuple appends nothing.

Each appended block contains:

- Timestamp.
- `HUMAN_MESSAGE:` line when new input arrived.
- The LLM's response as the normalized string — every command it emitted, verbatim.
- `ERROR_FEEDBACK:` when the loop captured an error.

The trailing `maxHistory` characters are loaded back into the prompt as `HISTORY` context; `read_file_tail` seeks from the end of the file, so a long trace still costs a constant read. `(episodes ts)` reads lines around a timestamp.

The episodic trace is not a separate "tier" in the same sense — it is the running log that makes the short-horizon loop work. It is also the only reason `pin` has any effect: the pinned text is part of the response echoed into this file. `remember` writes around it.

---

## The three-tier interaction loop

A reasoning-heavy turn typically cycles through all three tiers:

```
1. query     — recall relevant past findings (Tier 2)
2. atomize   — convert relevant knowledge into MeTTa atoms (Tier 3)
3. reason    — (metta (|- ...)) over atoms
4. remember  — store novel conclusions with provenance (Tier 2)
5. pin       — restate reasoning state so the next turn reads it back (Tier 1)
```

---

## Why two persistent stores

- **Long-term memory** uses embeddings for semantic recall across arbitrary time spans. Content is natural language.
- **AtomSpace** uses formal atoms with explicit truth values for inference. Content is structured, not text.

They are complementary, not overlapping. Long-term memory *feeds* the AtomSpace by supplying candidate facts; the AtomSpace *reasons over* them; novel conclusions are *stored back* into long-term memory as atomized strings.

---

## See also

- [reference-skills-memory.md](./reference-skills-memory.md) — user-facing surface.
- [reference-configuration.md](./reference-configuration.md) — memory tunables.
- [introduction.md#the-hybrid-thesis](./introduction.md#the-hybrid-thesis) — why this layout exists.
- [tutorial-01-teaching-memories.md](./tutorial-01-teaching-memories.md) — hands-on use.
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — storing facts with provenance.
