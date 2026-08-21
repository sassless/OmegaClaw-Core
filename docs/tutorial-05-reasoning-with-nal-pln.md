# Tutorial 05 — Reasoning with NAL and PLN

**Goal:** invoke Non-Axiomatic Logic and Probabilistic Logic Networks from inside OmegaClaw using the `(metta ...)` skill, and read the truth values the engines emit.

## Prerequisites

- A running OmegaClaw.
- Reading familiarity with `(stv frequency confidence)` truth values.

## The `metta` skill

```metta
(metta sexpression)
```

`metta` evaluates an arbitrary MeTTa s-expression in the agent's AtomSpace. NAL and PLN are plain MeTTa libraries (`lib_nal.metta`, `lib_pln.metta`) — you reach them by passing the right expression to `metta`.

---

## NAL — the `|-` operator

### Example 1 — Deduction (golden retriever → family friendly)

```metta
(metta (|- ((--> golden_retriever friendly)         (stv 1.0 0.9))
           ((--> friendly         family_friendly)  (stv 0.9 0.85))))
```

Expected conclusion:

```
(--> golden_retriever family_friendly) (stv 0.9 0.6885)
```

Where `c = 1.0 × 0.9 × 0.9 × 0.85 = 0.6885`. This is above the ACT threshold (`c ≥ 0.5`) so the conclusion is actionable.

### Example 2 — Abduction (wet grass ← rained)

```metta
(metta (|- ((==> rained wetGrass) (stv 1.0 0.9))
           (wetGrass               (stv 1.0 0.9))))
```

Abduction output confidence is bounded at ~0.45. The output correctly tells you **"probably rained, but do not act on this alone — corroborate."**

### Example 3 — Revision (three sources agree)

```metta
(metta (|- ((--> wolf animal) (stv 1.0 0.45))
           ((--> wolf animal) (stv 1.0 0.45))))
```

First revision: `(stv 1.0 0.621)`. Revising a third source at `(stv 1.0 0.45)` in:

```
→ (--> wolf animal) (stv 1.0 0.711)
```

Five independent sources at the same level revise to `(stv 1.0 0.804)` — solidly in ACT territory.

The frequency stays at 1.0 throughout. Revision returns the evidence-weighted average of the input frequencies, so sources that agree can only raise the confidence.

### Example 4 — Contradiction detection

```metta
(metta (|- ((--> cat dangerous) (stv 0.2 0.8))  ; most cats not dangerous
           ((--> cat dangerous) (stv 0.9 0.5))  ; someone claims dangerous
           ))
```

Output:

```
(--> cat dangerous) (stv 0.34 0.833)
```

`f = 0.34, c = 0.833` is the engine saying: *"substantial but conflicting evidence."* Do not pick a side — surface the disagreement with both source citations. See [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) §8.

The result sits closer to the sceptical source than to the midpoint, because revision weighs each input by `c / (1 − c)`: the source at `c = 0.8` carries weight 4, the one at `c = 0.5` carries weight 1.

### Example 5 — Implication with variables

```metta
(metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))
           ((--> (× tiger elephant) eat)                            (stv 1.0 0.9))))
```

`$1` is an independent variable. The engine unifies `$1 = tiger` and emits `(--> tiger ([] dangerous))`.

### Example 6 — Analogy (weaker transfer)

```metta
(metta (|- ((<-> golden_retriever poodle)  (stv 0.25 0.4))   ; share playful, friendly
           ((--> poodle           smart)   (stv 1.0  0.9))))
```

Conclusion: `(--> golden_retriever smart) (stv 0.25 0.09)`. The low confidence correctly signals *analogical transfer, not direct evidence*.

`Truth_Analogy` computes `c = c₁ × c₂ × f₂`, where the second premise is the similarity. The similarity's own frequency enters the confidence, so a weak resemblance at `f = 0.25` cuts the result to a quarter of what the two confidences alone would give.

---

## PLN — the `|~` operator

### Example 7 — Forward chaining (Modus Ponens)

```metta
(metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))
                         (Inheritance $1 Bird)) (stv 1.0 0.9))
           ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9))))
```

Conclusion: `(Inheritance Pingu Bird) (stv 1.0 0.81)`.

PLN Modus Ponens is close to NAL deduction but not identical: `f = f_P × f_PQ + 0.02 × (1 − f_P)`, `c = (f_P × f_PQ) × (c_P × c_PQ)`. The extra term vanishes here because `f_P = 1.0`, and shows up as soon as the antecedent is uncertain.

### Example 8 — PLN abduction on inheritance

```metta
(metta (|~ ((Inheritance bird flyer)  (stv 1.0 0.9))
           ((Inheritance robin flyer) (stv 1.0 0.9))))
```

Both premises share their second term, so the rule matches in both premise orderings and the call returns two conclusions — `(Inheritance robin bird)` and `(Inheritance bird robin)` — each at `(stv 1.0 0.448)`.

The confidence is what matters here: two premises at `c = 0.9` collapse to `0.448`, below ACT. Treat the output as a hypothesis to verify, and expect to pick the direction you meant out of a two-element result rather than receiving a single answer.

---

## Using reasoning inside the agent loop

Ask the agent a question that requires inference:

```
given that pingu has feathers and feathered things are birds,
is pingu a bird?
```

A well-behaved response:

1. Atomizes the two premises.
2. Emits `(metta (|~ ...))` with those premises.
3. Reads the `(stv ...)` of the conclusion.
4. Checks the action threshold (ACT / HYPOTHESIZE / IGNORE).
5. `send`s an answer that includes the derived confidence and the rule used.

---

## Multi-hop degradation — a warning

Starting with each premise at `c = 0.9`:

| Hop | Output `c` |
|---|---|
| 1 | 0.81 |
| 2 | 0.73 |
| 3 | **< 0.5** (below ACT) |
| 4 | ~0.25 (IGNORE) |

**Practical implication:** keep deduction chains to 2–3 hops; use revision with independent evidence to restore confidence before continuing. See [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md).

---

## Verification

- Logs show the `(metta (|- ...))` or `(metta (|~ ...))` call and its conclusion with an updated `(stv ...)`.
- Revision on shared terms produces confidence **strictly greater** than either input — this is a quick sanity check that revision is firing.
- Deduction confidence matches `f₁ × f₂ × c₁ × c₂` within rounding.

---

## Common mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Term order reversed | Inference returns empty | Verify which term is the subject vs. predicate. Asymmetric swap errors run ~16.6%. |
| Wrong copula | Empty or nonsensical result | `-->` (inheritance), `==>` (implication), `<->` (similarity) — choose carefully. |
| Chain too long | Conclusion below ACT | Insert revision with independent evidence. |
| Self-assigned confidence | Overconfident conclusions | Ground the premise externally — see [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md). |

---

## Next steps

- [reference-lib-nal.md](./reference-lib-nal.md) — every NAL rule and truth formula.
- [reference-lib-pln.md](./reference-lib-pln.md) — PLN rule catalogue.
- [reference-lib-ona.md](./reference-lib-ona.md) — the planned temporal engine (experimental, not installed).
- [reference-skills-reasoning.md](./reference-skills-reasoning.md) — the `metta` skill signature.
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — external grounding.
- [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) — best practices.
