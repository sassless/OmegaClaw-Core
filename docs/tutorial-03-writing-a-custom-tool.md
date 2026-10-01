# Tutorial 03 — Writing a Custom Tool

**Goal:** add a new tool the agent can call, end-to-end.

## Prerequisites

- A local clone of Omega (so you can edit MeTTa source).
- Familiarity with running the agent — see [Usage](/README.md#usage).

## The anatomy of a tool

A tool is three things:

1. **An entry in the tool list** in `src/skills.metta` (the `getSkills` list) so the LLM learns it exists.
2. **A MeTTa definition** of how the tool executes. Pure-MeTTa tools are written directly; tools that need system access delegate to Python or Prolog.
3. **Optional Python/Prolog glue** imported through `py-call` or `translatePredicate`.

## Example: a `word-count` tool

We'll add `(word-count "some text")` that returns the number of whitespace-separated tokens.

### Step 1 — Declare it in `getSkills`

Open `src/skills.metta` and add a line inside the `getSkills` list:

```metta
"- Count whitespace-separated words in a string: (word-count string_in_quotes)"
```

This text is concatenated into the prompt so the LLM knows the tool is callable.

### Step 2 — Define the implementation

Still in `src/skills.metta`, add:

```metta
(= (word-count $str)
   (progn (translatePredicate (split_string $str " " "" $parts))
          (length $parts)))
```

If you prefer Python, register a function in a `.py` module and call `(py-call (mymodule.word_count $str))`.

### Step 3 — Test

Restart the agent. Ask:

```
how many words are in "the quick brown fox"?
```

The LLM should emit `(word-count "the quick brown fox")` and respond with `4`.

## Conventions

- Tool names are lowercase, hyphen-separated.
- Every argument is a string literal in quotes. Variables are forbidden in LLM-generated tool calls (the loop rejects them in `getContext`).
- Return a value that is safe to render into the `LAST_SKILL_USE_RESULTS` context — the loop runs the result through `helper.normalize_string`.
- If your tool may fail, wrap error-producing subcalls in `catch` or let them fall through to the loop's `HandleError`.

## Verification

- The new tool appears in the prompt (search logs for `word-count`).
- The LLM invokes it without prompting tweaks.
- The return value shows up in `LAST_SKILL_USE_RESULTS` on the next turn.

## Next steps

- [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) — how dispatch works.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — other places to hook in.
