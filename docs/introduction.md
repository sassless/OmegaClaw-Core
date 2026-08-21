# Introduction

OmegaClaw is a **hybrid agentic AI framework** implemented in MeTTa on OpenCog Hyperon. A large language model (LLM) works together with formal logic engines — **NAL** and **PLN** — to reason about the world, track uncertainty, combine evidence, and produce conclusions that are mathematically grounded rather than just plausible-sounding.

The MeTTa core in `src/` is about **400 significant lines**, of which the agent loop itself is the smallest part.

> Most AI assistants generate answers that sound right. OmegaClaw-hosted agents generate answers that come with a **mathematical receipt** showing exactly how confident each conclusion is and what evidence supports it. When the agent says it is 72% confident, that number comes from formal inference — not a feeling.

This page is the conceptual introduction: what OmegaClaw is, why the hybrid architecture exists, how the pieces connect at runtime, the vocabulary used throughout the rest of the docs, and the honest limits of the current system. For getting a running instance, see [installation instruction](/README.md#installation). For hands-on walkthroughs, see the tutorials listed at the end.

---

## What OmegaClaw does

- Runs a token-efficient agentic loop that receives messages, selects skills, and acts.
- Delegates reasoning to one of two formal engines, orchestrated by the LLM:
  - **NAL** — Non-Axiomatic Logic, symbolic inference under uncertainty.
  - **PLN** — Probabilistic Logic Networks, probabilistic higher-order reasoning.
  - ONA (OpenNARS for Applications) is a planned third engine but is **not installed by default** — see [reference-lib-ona.md](./reference-lib-ona.md) for the current experimental status.
- Maintains a **two-tier memory** architecture (episodic history and long-term embedding memory — described below), on top of the AtomSpace that the MeTTa runtime itself provides.
- Exposes an extensible **skill system** covering memory, shell and file I/O, communication channels, web search, and formal reasoning. Channels, LLM providers and additional skills are loaded as plugins listed in [`config/plugins.yaml`](/config/plugins.yaml).

---

## The hybrid thesis

### Two kinds of reasoning, one pipeline

| Aspect | LLM (neural) | Formal engine (symbolic) |
|---|---|---|
| Natural language understanding | ✅ | ❌ |
| Premise formulation from text | ✅ | ❌ |
| Inference orchestration (which rule when) | ✅ | ❌ |
| Truth-value propagation | ❌ | ✅ |
| Confidence decay through chains | ❌ | ✅ |
| Formal contradiction detection | ❌ | ✅ |
| Auditable conclusion path | ❌ | ✅ |

The LLM turns ambiguous natural language into structured atoms with explicit truth values. The formal engine takes those atoms and applies rules whose truth-value arithmetic is deterministic and auditable.

When the agent outputs a conclusion, you can trace it back through every step: which premises fed into which rule, what truth value each premise carried, and what the math produced.

### The orchestration cycle (call-and-wait)

Each reasoning hop is a synchronous five-step dance:

```
1. NEURAL PHASE
   LLM synthesizes context, emits a formal command
   (e.g. (metta "(|- ...)"))

2. INTERCEPTION
   The agent framework intercepts the command;
   LLM generation is suspended.

3. SYMBOLIC PHASE
   Framework passes the s-expression to the MeTTa /
   Hyperon interpreter. The engine executes logic
   independently of the LLM.

4. RESULT CAPTURE
   Engine returns deterministic result atoms
   (e.g. (robin --> animal) (stv 0.72 0.32)).

5. INJECTION & RESUMPTION
   Results are injected into the next prompt context
   as immutable data. The LLM resumes, reads the data,
   and decides the next move.
```

Step 3 is **opaque to the LLM in a useful way** — the LLM cannot tamper with the truth-value math. Confidence cannot be inflated by rhetoric.

---

## Architecture

A thin MeTTa core drives the two formal reasoning engines and a handful of Python bridges for LLM calls, embeddings, and network I/O.

### Layered view

```
┌─────────────────────────────────────────────────┐
│  LLM Layer                                      │
│  - Natural language understanding               │
│  - Premise formulation (atomization)            │
│  - Inference orchestration                      │
│  - Contextual steering                          │
└────────────────────┬────────────────────────────┘
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
┌──────────┐                 ┌──────────┐
│ NAL   |- │                 │ PLN   |~ │
│ Engine   │                 │ Engine   │
└────┬─────┘                 └────┬─────┘
     │                            │
     └─────────────┬──────────────┘
                   │
       ┌────────────┴────────────┐
       ▼                         ▼
┌────────────────┐     ┌──────────────────┐
│ Memory         │     │ Shell / Files /  │
│ - history      │     │ Channels / Web   │
│ - remember LT  │     │                  │
└────────────────┘     └──────────────────┘
```

The **LLM layer** is opaque and creative. The **engine layer** is deterministic and auditable.

### Module map

```
run.metta                 entry point: (omegaclaw)
lib_omegaclaw.metta       loads all submodules
├── src/loop.metta        agentic loop, turn structure
├── src/memory.metta      long-term memory + history
├── src/skills.metta      callable skill surface
├── src/channels.metta    send/receive wrappers, outgoing de-duplication
├── src/utils.metta       utility, string ops, time
├── src/config.metta      configure
├── src/plugin.metta      MeTTa side of the plugin loader
├── src/helper.py         response parsing, LLM_COMMANDS, normalization
├── src/config.py         parameter resolution
├── src/plugin.py         plugin loader
├── src/channels.py       channel registry
├── src/providers.py      LLM provider registry
├── src/fileio.py         file skills
├── src/rag.py            embeddings and ChromaDB access
├── src/logger.py         logging
├── src/skills.pl         Prolog helpers (shell, first_char)
├── src/websearch.py      web search
├── lib_nal.metta         NAL truth functions
└── lib_pln.metta         PLN rules

config/plugins.yaml       the list of plugins loaded at startup
config/config.yaml        default values for every runtime parameter

channels/irc.py           IRC adapter
channels/telegram.py      Telegram adapter
channels/slack.py         Slack adapter
channels/mattermost.py    Mattermost adapter
channels/wschat.py        WebSocket adapter
channels/mockchannel.py   in-process adapter used by the tests (`test`)
channels/auth.py          channel ownership check
channels/delivery_queue.py  messages produced before the channel is up

providers/lib_llm_ext.py  shared provider base, proxy routing
providers/openaiapi.py    Anthropic, ASICloud and OpenAIAPI
providers/openai.py       OpenAI
providers/openrouter.py   OpenRouter
providers/asione.py       ASI:One
providers/mockprovider.py mock provider used by the tests (`Test`)

plugins/workflow/         multi-step workflow skills
plugins/openclaw/         delegation to an OpenClaw execution agent

proxy/nginx.conf.template outbound proxy that holds the API keys
entrypoint.sh             starts the proxy, scrubs the environment, drops privileges

memory/prompt.txt         system prompt (agent identity + values)
memory/history.metta      episodic trace (written at runtime)
```

### The agentic turn

Each iteration of `(omegaclaw $k)` in `src/loop.metta` performs:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. receive()        pull latest message from channel        │
│ 2. getContext()     PROMPT + SKILLS +                       │
│                     LAST_SKILL_USE_RESULTS +                │
│                     HISTORY + TIME                          │
│ 3. LLM call         whichever provider `provider` selects   │
│ 4. sread / balance  parse response into skill s-exprs       │
│ 5. eval each skill  (remember ...), (metta ...), ...        │
│ 6. addToHistory     append human msg + response +           │
│                     any errors                              │
│ 7. sleep            sleepInterval seconds                   │
│ 8. recurse          (omegaclaw (+ 1 $k))                    │
└─────────────────────────────────────────────────────────────┘
```

If no new message arrives and the `loops` counter hits zero, the agent idles until `nextWakeAt`, then runs one wake loop for background work.

The neural↔symbolic sub-cycle described in [The hybrid thesis](#the-hybrid-thesis) above kicks in **inside** step 5 whenever a skill-tuple contains `(metta (|- ...))` or `(metta (|~ ...))`.

### Division of labor

| Controlled by the LLM (opaque) | Controlled by the engine (transparent) |
|---|---|
| Which premises to include | How truth values propagate |
| Initial `(stv f c)` assignments | Confidence decay through chains |
| Which inference rule to invoke | The math of the rule |
| When to stop reasoning | Whether the conclusion follows |

See [reference-orchestration.md](./reference-orchestration.md) for the LLM's side of the policy.

### Data flow — a grounded memory write

```
user message
   │
   ▼
(receive) ─► channel adapter ─► loop input
                                   │
                                   ▼
                            LLM atomizes:
                            (remember "...")
                                   │
                                   ▼
              src/memory.metta ─► embed() ─► lib_llm_ext ─► vector
                                   │
                                   ▼
                  lib_chromadb.remember(str, vec, timestamp)
```

For a **grounded** write with provenance, the pattern is the same, but the LLM first queries memory, then fetches from a verified source before calling `remember`. See [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md).

### Memory tiers in a reasoning turn

A reasoning-heavy turn typically uses all three memory tiers:

```
1. query long-term memory for relevant past findings
        │
        ▼
2. atomize the relevant knowledge into premises
        │
        ▼
3. reason over atoms via (metta (|- ...)) or (|~ ...)
        │
        ▼
4. remember novel conclusions with provenance
        │
        ▼
5. pin reasoning state for the next cycle
```

### Configuration

Runtime parameters are declared as `(empty)` at module top and filled by `configure` calls during `initLoop`, `initMemory`, and `initChannels`. `configure` is defined in `src/config.metta` and resolves each key through `src/config.py`, which consults, in order, the command line, an `OMEGACLAW_<key>` environment variable, `config/config.yaml`, and the built-in default. Full list in [reference-configuration.md](./reference-configuration.md).

---

## Core concepts

Vocabulary used throughout the rest of the documentation. Skim once; come back when a term shows up in another page.

### AtomSpace

The knowledge substrate provided by Hyperon / MeTTa. Every fact, memory item, and program fragment in OmegaClaw lives in the same AtomSpace, so memory is directly interrogable by other Hyperon components.

### Atomization

The act of converting natural-language facts into AtomSpace atoms with explicit truth values. Example:

Natural: *"Sam and Garfield are friends, and Garfield is an animal."*

Atomized:

```metta
(--> (× sam garfield) friend)  (stv 1.0 0.9)
(--> garfield animal)          (stv 1.0 0.9)
```

Atomization is a first-class step — raw text cannot participate in formal inference. Each atom carries an **explicit relationship type** (inheritance, implication, similarity) and an **explicit truth value**.

### `stv` — subjective truth value

Every atom carries `(stv frequency confidence)`:

- **frequency** ∈ [0.0, 1.0] — how often the statement held among observed evidence.
- **confidence** ∈ [0.0, 1.0] — how much evidence we have.

Negation is `(stv 0.0 c)` — strong evidence *against* the statement.

### Expectation

A scalar derived from `(stv f c)`:

```
exp = c × (f - 0.5) + 0.5
```

Maps an `(f, c)` pair to a single value in `[0, 1]`, useful for priority queues and ranking.

### The reasoning engines

| Engine | MeTTa operator | Strength |
|---|---|---|
| **NAL** — Non-Axiomatic Logic | `\|-` | Symbolic inference under uncertainty, revision, evidence merging |
| **PLN** — Probabilistic Logic Networks | `\|~` | Probabilistic higher-order reasoning |

Dedicated pages: [reference-lib-nal.md](./reference-lib-nal.md), [reference-lib-pln.md](./reference-lib-pln.md), [reference-lib-ona.md](./reference-lib-ona.md) (experimental, not installed).

### Memory tiers

Two stores persist state, and the AtomSpace sits behind them as the runtime substrate:

1. **Episodic history (`history.metta`)** — an append-only trace of the messages and
   responses of each turn, replayed into the prompt up to `maxHistory`. This is also where
   `pin` becomes visible: `pin` itself does not write anywhere, it returns a success atom,
   and the pinned text reaches the next turn only because the whole response is appended to
   the history.
2. **Long-term embedding memory (`remember` / `query`)** — persistent semantic recall backed
   by ChromaDB. Survives restarts, and is not written automatically: an item enters it only
   through an explicit `remember`.
3. **AtomSpace** — the knowledge substrate of the MeTTa runtime, reachable from the agent
   through the `metta` skill. OmegaClaw does not keep a belief store in it: `|-` and `|~`
   take their premises as call arguments, so atomized knowledge lives only for the duration
   of the call unless the agent writes it somewhere itself.

Full detail in [reference-internals-memory-store.md](./reference-internals-memory-store.md).

### Skills

The set of callable operations available to the agent at each turn — plain MeTTa s-expressions like `(remember "...")`, `(shell "ls")`, `(metta (|- ...))`. Defined in `src/skills.metta` and `src/memory.metta`, and advertised to the model by `getStaticSkills`.

Being defined is not sufficient for a skill to be callable. The response parser decides where one command ends and the next begins by looking up the first token of a line in the `LLM_COMMANDS` set in `src/helper.py`. A name that is missing from that set is not recognised as the start of a command, so the line is absorbed into the argument of the command above it. Skills registered at runtime through `add-skill` add themselves to the set; built-in skills are listed there statically.

### Channels

Abstract communication endpoints. `(send ...)` and `(receive)` delegate to the active channel adapter (IRC, Telegram, Slack, Mattermost, WebSocket, or the in-process `test` channel used by the automated tests). See [reference-channels.md](./reference-channels.md).

`(send ...)` drops a message whose text is identical to the previous one it sent, so an agent can produce a correct answer that never reaches the channel.

### Orchestration

The LLM's policy for picking which engine (or no engine) to invoke for a given task, plus when to stop reasoning. Full table in [reference-orchestration.md](./reference-orchestration.md).

### Action thresholds

Three decision tiers applied to any `(f, c)` before acting on the conclusion:

| Tier | Gate |
|---|---|
| ACT | `f ≥ 0.6 AND c ≥ 0.5` |
| HYPOTHESIZE | `f ≥ 0.3 AND c ≥ 0.2` |
| IGNORE | below |

Full context in [reference-orchestration.md](./reference-orchestration.md).

### The defense stack

Four layers the agent is asked to apply to incoming evidence in order to resist noise and adversarial input. They are policy rather than machinery: nothing in the runtime enforces them, and the fourth has no test suite behind it. See [reference-orchestration.md](./reference-orchestration.md) for what is and is not implemented.

1. **Novelty modulation** — new claims enter with `c × (1 − novelty)`.
2. **Action thresholds** — the tiers above.
3. **Attention budgeting** — priority queue by expectation, with per-cycle step limits.
4. **Adversarial premise testing** — regression suite for confident lies, contradictions, and gradual poisoning.

See [reference-orchestration.md](./reference-orchestration.md) for each layer.

### External grounding

The pattern of anchoring a premise's confidence on a verified external source rather than the LLM's prior. The primary mitigation for premise-formulation errors. See [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md).

### Revision

An inference rule that merges independent evidence about the same statement. Increases confidence when sources agree; produces a middle frequency with high confidence when they disagree, making contradiction visible.

### GIGO amplification

The failure mode where a flawed premise is run through the formal engine and emerges with a mathematically-authoritative-looking conclusion. Why the mitigations matter. See [reference-failure-modes.md](./reference-failure-modes.md).

## Design goals and honest limits

### Design goals

- **Transparency by design, not by post-hoc explanation.** Every conclusion can be traced to its premises, rule, and truth-value math.
- **Simplicity.** A small core that is readable end-to-end.
- **Extensibility.** New skills, channels, tools, and engines are short additions — see [reference-internals-extension-points.md](./reference-internals-extension-points.md).
- **Flexibility in memory representation.** Memory items coexist with other Hyperon components in the same AtomSpace; no single representation is hardcoded.

### When to use OmegaClaw

- a small, auditable agent that can explain **why** it reached a conclusion;
- reasoning with explicit uncertainty (`stv frequency confidence`) rather than opaque probabilities;
- a platform for experimenting with NAL and PLN inside an agent loop;
- a chat-facing agent over IRC, Telegram, Slack, Mattermost, WebSocket, or a channel you add yourself.

### Honest limits

The hybrid design moves the failure mode — it does not eliminate it. Known issues, quantified on the reference deployment:

- LLM premise formulation errors (up to ~16.6% on asymmetric relations).
- LLM confidence overestimation (~15 percentage points on self-assigned truth values).
- Confidence decays through deduction chains. `Truth_Deduction` multiplies the confidences of both premises (and, for non-certain premises, their frequencies too), so a chain of certain premises at `(stv 1.0 0.9)` yields `c` = 0.81, 0.73, 0.66, 0.59, 0.53 over successive hops and first falls below 0.5 on the sixth. Chains over uncertain premises decay considerably faster, because the frequency product enters the confidence as well.

**Garbage In, Garbage Out** applies with a twist: the formal engine does not merely pass through garbage, it **amplifies** it by lending mathematical authority to conclusions derived from flawed premises.

The mitigations (external grounding, revision, action thresholds, the defense stack) are documented and non-optional for production use. See [reference-failure-modes.md](./reference-failure-modes.md) for the full catalogue and [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) for strategy.

---

## Where to go next

- [tutorial-01-teaching-memories.md](./tutorial-01-teaching-memories.md) — hands-on first session.
- [reference-orchestration.md](./reference-orchestration.md) — engine selection, stopping criteria, action thresholds, defense stack.
- [reference-internals-loop.md](./reference-internals-loop.md) — turn structure in detail.
- [reference-internals-memory-store.md](./reference-internals-memory-store.md) — the memory tiers in detail.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to plug in new behavior.
