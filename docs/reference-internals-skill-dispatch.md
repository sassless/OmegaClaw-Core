# Internals — Skill Dispatch

This page traces what happens between an LLM response landing in the loop and a skill actually running.

## Expected LLM output shape

The prompt asks for up to five plain lines, one command each:

```
toolName1 arg1
toolName2 arg2
```

with the explicit instructions *do not wrap quotes around args* and *do not use variables* (`src/loop.metta:35`). The tuple of quoted s-expressions

```
((skillName1 "arg1") (skillName2 "arg2") ...)
```

is the **output** of `helper.balance_parentheses`, not what the model is asked to produce. Quoting is applied by `helper.quote_arg` after the response has been split into commands. Neither rule is enforced anywhere: a model that emits its own quotes is accepted (`quote_arg` returns an already-quoted string unchanged, which is also how a plugin skill receives more than one argument), and nothing rejects a MeTTa variable.

Only the three file-writing commands take two arguments. For every other command, the entire remainder of the block becomes one quoted argument, newlines included.

## Step-by-step dispatch

From `src/loop.metta`:

1. **Raw LLM string** → `$respi`.
2. **Normalization** — `helper.balance_parentheses $respi` → `$resp`. This is the response parser, not a paren repair: it decodes the `_quote_` / `_newline_` placeholders, cuts the reply into blocks (a new block starts only at a line whose first token is a known command, so prose after a command is swallowed into its argument), rewrites a leading `-` or `(-` into `pin`, strips one outer paren pair, splits filename from content for `write-file` / `append-file` / `write-file-b64`, quotes the arguments, and re-wraps everything in a single outer pair. It never inserts a missing closing paren — an unbalanced tail just ends up inside a string literal.
3. **Command-name check** — still inside `balance_parentheses`: if the head of a block is not in the Python `LLM_COMMANDS` set (`src/helper.py:35`), the block is replaced by `(Error UNKNOWN_SKILL_CALL "<line>")`. The gate is that Python set, not the AtomSpace — a definition that exists in MeTTa but whose name is unknown to the parser can never be reached by a model-issued command.
4. **First-character check** — if `$resp` does not start with `(`, the agent receives a reminder prompt instead of a real dispatch; the LLM tries again next turn.
5. **Parse** — `catch (sread $response)` → `$sexpr`. On parse failure, `HandleError` records `MULTI_COMMAND_FAILURE_NOTHING_WAS_DONE_PLEASE_CORRECT_PARENTHESES_AND_USE_QUOTES_AND_RETRY` and the dispatch is skipped entirely.
6. **Fan out** — `(superpose $sexpr)` produces one binding per skill call in the tuple, all of it inside a `collapse`. The `collapse` is mandatory: without it every step after `$results` — history write, `&lastresults`, `sleep`, the recursive call — would re-run once per command.
7. **Unknown-call pre-check** — `HandleError UNKNOWN_SKILL_CALL $s $s` runs on each branch *before* evaluation. If the branch is the `(Error UNKNOWN_SKILL_CALL ...)` atom from step 3, it is recorded and turned into `(ALERT_FAILED UNKNOWN_SKILL_CALL "<line>")` without ever being evaluated.
8. **Evaluate each** — `(catch (eval $s))`. On success, the result is normalized via `helper.normalize_string`. On failure, `HandleError` records `SINGLE_COMMAND_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY`; the remaining commands still run.
9. **Aggregate** — all results are collapsed into `RESULTS: ((COMMAND_RETURN: (cmd result)) ...)`.
10. **Feedback** — stored as `&lastresults`, fed back into the next prompt as `LAST_SKILL_USE_RESULTS`.

## How `eval $s` resolves to a skill

MeTTa evaluates the head of the expression against the AtomSpace. Most skills are plain equations:

```metta
(= (remember $str) ...)
(= (metta $str)    ...)
(= (websearch $msg) ...)
```

So `(remember "note")` matches the equation for `remember` and runs its body.

Not everything is an equation. `shell`, `first_char`, `gc` and `read_file_tail` are SWI-Prolog predicates pulled in by `!(import_prolog_functions_from_file (library OmegaClaw-Core ./src/skills.pl) (shell first_char gc read_file_tail))` in `src/skills.metta`; `(shell "ls")` resolves to `shell/2`, not to a MeTTa equation.

Skills added at runtime resolve the same way. `add-skill` writes a catalogue atom `(= (dynamic-skill $function) $text)` and registers the name with the parser, while the function itself is an ordinary equation defined by the plugin — so plugin and workflow skills reach `eval` through exactly the path above. See [reference-internals-extension-points.md](./reference-internals-extension-points.md).

Bridges enter via:

- `(py-call (module.function args))` for Python.
- `(translatePredicate (predicate ...))` and `!(import_prolog_function name)` for Prolog.

## Errors propagate via `&error`

`HandleError` appends to the `&error` state. When `addToHistory` runs, if `&error` is non-empty it is concatenated as `ERROR_FEEDBACK:`. On the next turn the agent sees the error and has the opportunity to correct course.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — the full turn structure.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to hook in new skills.
- [tutorial-03-writing-a-custom-skill.md](./tutorial-03-writing-a-custom-skill.md) — end-to-end skill addition.
