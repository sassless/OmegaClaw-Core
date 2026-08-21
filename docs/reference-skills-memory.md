# Reference — Memory Skills

`remember`, `query` and `episodes` are defined in `src/memory.metta`; `pin` is defined in `src/skills.metta`. All four are catalogued in `getStaticSkills` (`src/skills.metta`) and allowlisted in `STATIC_LLM_COMMANDS` (`src/helper.py`).

The prompt asks the model to emit bare `skill arg` lines; the response parser quotes each argument before the call is evaluated. Variables are not permitted in LLM-generated calls, but nothing enforces that — it is an instruction in the prompt.

---

## `remember`

### Signature
```metta
(remember "string")
```

### Purpose
Store a string in long-term embedding memory together with its embedding vector and a timestamp.

### Parameters
- `string` — the text to remember. Use short, self-contained phrases for best recall.

### Returns
The constant `REMEMBER-SUCCESS`. The ChromaDB return value is discarded, so a failed write looks exactly like a successful one — treat the result as "the call was made", not "the write landed".

### Examples
```metta
(remember "user prefers dark mode")
(remember "to deploy: run make release then docker push")
```

### Notes / Limits
- The text is stored **unmodified**. `string-safe` is applied only to the copy handed to `embed`, where it swaps doubled quotes, newlines and apostrophes for the `_quote_` / `_newline_` / `_apostrophe_` placeholders.
- Embedding provider is selected by `embeddingprovider` (`Local` or `OpenAI`).
- Nothing deduplicates automatically — repeated `remember` calls store multiple items.

---

## `query`

### Signature
```metta
(query "string")
```

### Purpose
Return up to `maxRecallItems` memory entries whose embeddings are closest to the embedding of `string`.

### Parameters
- `string` — a short descriptive phrase. Over-long queries dilute similarity scores.

### Returns
A list-shaped result containing the nearest memory items.

### Examples
```metta
(query "deployment steps")
(query "user preferences")
```

### Notes / Limits
- `maxRecallItems` default is 20 (see `initMemory`).
- Similarity is purely embedding-based; exact string match is not guaranteed.

---

## `episodes`

### Signature
```metta
(episodes "YYYY-MM-DD HH:MM:SS")
```

### Purpose
Return the lines of the episodic trace around the given timestamp: the line whose timestamp is closest to it, plus `maxEpisodeRecallLines` lines on each side, each prefixed with its line number.

### Parameters
- `timestamp` — must match the format produced by `get_time_as_string`.

### Returns
A block of numbered lines from `memory/history.metta`.

### Examples
```metta
(episodes "2026-04-15 14:30:00")
```

### Notes / Limits
- Implemented by `helper.around_time`, which opens the **hardcoded** path `repos/OmegaClaw-Core/memory/history.metta` relative to the process working directory. It ignores `memoryDirectory`, so outside the expected layout the call fails to find the trace.
- Useful for answering questions like "what was I doing around X?"

---

## `pin`

### Signature
```metta
(pin "string")
```

### Purpose
Mark a working-memory note so it shows up again on the next turn.

### Parameters
- `string` — the note. Typical uses: intermediate results, plans for the next turn, checklists.

### Returns
The constant `PIN-SUCCESS`. `(= (pin $x) PIN-SUCCESS)` is the whole definition — the skill stores nothing and cannot fail.

### Examples
```metta
(pin "candidates: A) Launch Day B) We're Live C) Out Now")
(pin "next step: pick best candidate and send")
```

### Notes / Limits
- The note reaches the next prompt only because the loop echoes the whole response verbatim: once through `LAST_SKILL_USE_RESULTS`, which lasts a single turn, and once through `memory/history.metta`, which the prompt reads back as the trailing `maxHistory` characters of `HISTORY`.
- `pin` is not semantically indexed. For anything you want to recall days later, use `remember` instead.
- A model response that opens with `-` is rewritten into `pin` by the response parser, so bullet-point commentary arrives as a pin.
