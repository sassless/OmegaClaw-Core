# Tutorial 03 — Writing a Custom Skill

**Goal:** add a new skill the agent can call, end-to-end.

## Prerequisites

- A local clone of OmegaClaw-Core (so you can edit MeTTa source).
- Familiarity with running the agent — see [Usage](/README.md#usage).

## The anatomy of a skill

A skill is three things:

1. **A name the response parser recognizes.** The parser checks the head of every command against the `LLM_COMMANDS` set in `src/helper.py`. An unrecognized head never reaches evaluation — it is rewritten into `(Error UNKNOWN_SKILL_CALL …)` and reported back to the model. This is the step that is easy to miss and the one that makes a skill silently uncallable.
2. **A MeTTa definition** of how the skill executes. Pure-MeTTa skills are written directly; skills that need system access delegate to Python or Prolog.
3. **An entry in the skill catalogue** — the `getStaticSkills` list in `src/skills.metta` — so the LLM learns the skill exists. (`getSkills` is the function that merges that list with the skills plugins add at run time; the literal list is `getStaticSkills`.)

Plus optional Python/Prolog glue imported through `py-call` or `translatePredicate`.

## Example: a `char-count` skill

We'll add `(char-count "some text")` that returns the number of characters in a string.

### Step 1 — Let the parser through

In `src/helper.py`, add the name to `STATIC_LLM_COMMANDS`:

```python
STATIC_LLM_COMMANDS = {
    "append-file",
    "char-count",
    "episodes",
    ...
}
```

Without this line the agent gets `ALERT_FAILED UNKNOWN_SKILL_CALL` instead of a result, no matter how correct the rest of the skill is.

### Step 2 — Define the implementation

In `src/skills.metta`, add:

```metta
(= (char-count $str)
   (string_length $str))
```

`string_length` is one of the SWI-Prolog predicates already imported by `src/utils.metta`, so nothing else needs importing. If you prefer Python, put the function in a `.py` module, add `!(import! &self (library OmegaClaw-Core ./src/mymodule.py))` to `lib_omegaclaw.metta`, and call `(py-call (mymodule.char_count $str))` — the import line is what makes `py-call` able to see the module.

### Step 3 — Declare it in `getStaticSkills`

Still in `src/skills.metta`, add a line inside the `getStaticSkills` tuple:

```metta
"- Count the characters in a string: char-count string"
```

The existing entries show the shape: a dash, the description, a colon, then the call the model should type — the skill name followed by bare argument names. This text is concatenated into the prompt.

### Step 4 — Test

Restart the agent. Ask:

```
how many characters are in "the quick brown fox"?
```

The model types `char-count the quick brown fox`, the parser turns that into `(char-count "the quick brown fox")`, and the log shows `COMMAND_RETURN: ((char-count "the quick brown fox") 19)`.

## Alternative: register the skill from a plugin

If the skill belongs to a plugin rather than the core, none of the three edits above are needed. `add-skill` does all of it at run time:

```metta
(add-skill char-count "Count the characters in a string" (string_in_quotes))
```

It registers the name with the parser, renders the catalogue line as `"- <description>: <function> <args>"`, and adds it to the prompt. You still supply the `(= (char-count $str) ...)` definition. `remove-skill` reverses it — except for names baked into `STATIC_LLM_COMMANDS`, which it refuses to unregister. See [reference-internals-extension-points.md](./reference-internals-extension-points.md).

## Conventions

- Skill names are lowercase, hyphen-separated.
- **One argument by default.** Only `write-file`, `append-file` and `write-file-b64` get their arguments split by the parser. For every other skill the entire rest of the model's line becomes a single quoted argument. A multi-argument skill works only when the model quotes each argument itself — `(my-skill "a" "b")` passes through unchanged, `my-skill a b` arrives as one string `"a b"`.
- Arguments arrive as quoted strings, but that is the parser's doing, not the model's: the prompt asks for bare `toolName arg` lines and the quoting is applied afterwards. The "no variables" rule is likewise an instruction in the prompt with nothing enforcing it — the only thing actually checked is that the head is a known skill name.
- Return a value that is safe to render into the `LAST_SKILL_USE_RESULTS` context — the loop runs the result through `helper.normalize_string`.
- If your skill may fail, wrap error-producing subcalls in `catch` or let them fall through to the loop's `HandleError`, which reports `SINGLE_COMMAND_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY` and lets the other commands in the same turn run.

## Verification

- The new skill appears in the prompt (search the log for `char-count` in the `SKILLS:` block).
- The log shows `COMMAND_RETURN: ((char-count …) …)` rather than `ALERT_FAILED UNKNOWN_SKILL_CALL` — the latter means Step 1 is missing.
- The return value shows up in `LAST_SKILL_USE_RESULTS` on the next turn.

## Next steps

- [reference-internals-skill-dispatch.md](./reference-internals-skill-dispatch.md) — how dispatch works.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — other places to hook in.
