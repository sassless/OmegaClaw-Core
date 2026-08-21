# Reference — `lib_pln.metta`

Probabilistic Logic Networks (PLN) — a higher-order probabilistic reasoning framework compatible with the AtomSpace. PLN is the engine to reach for when a problem is best expressed as **property-based categorical inference** rather than the asymmetric inheritance chains NAL specializes in.

---

## Relations

| Atom | Meaning |
|---|---|
| `Inheritance` | Probabilistic "is-a" relation. |
| `Implication` | Conditional probability — `(Implication P Q)` ≈ `P(Q \| P)`. |
| `Similarity` | Symmetric resemblance. Also `IntensionalSimilarity`, `ExtensionalSimilarity`. |
| `Evaluation` / `Predicate` / `List` | Predicate application over concepts. |
| `Member` | Membership of an element in a concept. |
| `IntSet` | Intensional set — members share a property. |
| `Not` | Negation. |

Truth values share NAL's `(stv frequency confidence)` format, interpreted probabilistically.

---

## The `|~` operator

```metta
(= (|~ $a $b)
   (unique-atom (collapse (superpose ((|~pln $a $b) (|~pln $b $a))))))
```

Three consequences follow from this definition, and they explain most surprises:

- **`|~` takes exactly two premises.** `lib_pln.metta` defines seventeen `|~pln` rules, and five of them accept a single premise. Those five — negation, inheritance inversion, implication inversion, and the two equivalence-to-implication rules — cannot be reached through `|~` at all. Twelve rules are reachable.
- **Both orderings are tried**, so a symmetric premise pair can match a rule twice with the roles swapped and produce two conclusions.
- **The result is a set**, not a single atom. `unique-atom (collapse ...)` gathers every conclusion that matched.

### Node strengths are a constant

Deduction, induction and abduction in PLN take the strengths of the three terms as separate arguments. `lib_pln.metta` supplies them from a forward declaration that was never replaced:

```metta
(= (STV $X) (stv (/ 1.0 10.0) 0.9))
```

Every term therefore contributes `(stv 0.1 0.9)` regardless of what it actually is. The conclusions of those three rules are shaped by the premise truth values and by this constant, not by any per-term knowledge — there is no belief store for the engine to look a term up in.

---

## Rule catalogue

Twelve rules are reachable through `|~`.

| Rule | Premise shape | Notes |
|---|---|---|
| Revision | two beliefs about the same statement | Same formula as NAL revision. |
| Modus Ponens | `P` and `(Implication P Q)` | Yields `Q`. |
| Symmetric Modus Ponens | `A` and `(Link A B)` | Only for `Similarity`, `IntensionalSimilarity`, `ExtensionalSimilarity`. |
| Deduction | `(Link A B)` and `(Link B C)` | Only for `Inheritance` and `Implication`. Has consistency preconditions; when they fail the result is `(stv 1 0)`. |
| Induction | `(Link C A)` and `(Link C B)` | Shared first term. Same link guard. |
| Abduction | `(Link A C)` and `(Link B C)` | Shared second term. Same link guard. |
| Predicate inheritance (unary) | `(Evaluation (Predicate x) (List (Concept C)))` and an `Inheritance` | Substitutes a concept into a predicate application. |
| Predicate inheritance (binary) | the two-concept form of the above | Two rules, one per argument position. |
| Transitive similarity | `(Similarity A B)` and `(Similarity B C)` | |
| Evaluation over implication | `(Evaluation A B)` and `(Implication A C)` | |
| Member deduction | `(Member A B)` and `(Inheritance B C)` | |

The five single-premise rules — `Not` elimination, `Inheritance` and `Implication` inversion, and `Equivalence` to `Implication` in both directions — are present in the file but unreachable from the `|~` entry point.

---

## Truth functions

### Modus Ponens

```
f = f_P × f_PQ + 0.02 × (1 − f_P)
c = (f_P × f_PQ) × (c_P × c_PQ)
```

The `0.02 × (1 − f_P)` term is a floor contributed by the cases where the antecedent does not hold; it matters whenever the antecedent is uncertain. With `f_P = 1.0` it vanishes.

Worked check: premise `(stv 0.8 0.9)` with implication `(stv 0.9 0.9)` gives `(stv 0.724 0.5832)`. Dropping the second term would give `0.72`.

### Revision

```
w = c / (1 − c)
w_total = Σ w_i
c_out = w_total / (w_total + 1)
f_out = weighted average of f_i by w_i
```

Identical to NAL revision, so evidence can be merged across PLN conclusions, NAL conclusions, or both.

### Deduction, induction, abduction

All three take five arguments: the strengths of the three terms (always the `(stv 0.1 0.9)` constant described above) followed by the two premise truth values. Confidence passes through `w2c(w) = w / (w + 1)`, which is why these rules cap out well below the premise confidence — see the worked example below.

---

## Invocation

Through the `(metta ...)` skill. Variables use `$1`, `$2`, …

### Modus Ponens example

```metta
(metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))
                         (Inheritance $1 Bird)) (stv 1.0 0.9))
           ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9))))
```

Conclusion: `(Inheritance Pingu Bird) (stv 1.0 0.81)`.

### Abduction example

```metta
(metta (|~ ((Inheritance bird flyer)  (stv 1.0 0.9))
           ((Inheritance robin flyer) (stv 1.0 0.9))))
```

Both premises share their second term, so the abduction rule matches in both orderings and the call returns two conclusions, `(Inheritance bird robin)` and `(Inheritance robin bird)`, each with `(stv 1.0 0.448)`.

The confidence is the point to take away. Two premises at `c = 0.9` yield `c = 0.448`, because `w2c(0.9 × 0.9) = 0.81 / 1.81`. Abduction produces *hypotheses worth testing*, not *actionable conclusions* — the same lesson as in NAL, arrived at by a different formula.

---

## Limits of the current deployment

| Pattern | Status |
|---|---|
| Single-premise rules | Present in the file, unreachable through the two-argument `\|~`. |
| Per-term strengths | Not modelled. Every term contributes the `(stv 0.1 0.9)` constant. |
| Backward inference | Not implemented. Forward inference only. |
| Deduction with inconsistent premises | Returns `(stv 1 0)` rather than failing loudly. |

If `|~` returns nothing, the premise pair matched no rule — check the link type against the guards above, since deduction, induction and abduction accept only `Inheritance` and `Implication`. See recovery guidance in [reference-orchestration.md](./reference-orchestration.md).

---

## NAL vs. PLN — which to use

| Situation | Engine |
|---|---|
| Asymmetric chain `A → B → C` | NAL `\|-` |
| Observed effect, seeking cause (simple) | NAL `\|-` abduction |
| Merging independent evidence | Either (identical formula) |
| Property-based categorical inference | PLN `\|~` |
| Higher-order structures (`Implication` over `Inheritance`) | PLN `\|~` |
| Real-time or temporal reasoning | Not served by a stock engine — ONA is the planned future target (see [reference-lib-ona.md](./reference-lib-ona.md), experimental, not installed). Current fallback: NAL with external temporal grounding. |

When in doubt, try NAL first; PLN shines on `Implication` over `Inheritance` chains.

---

## See also

- [reference-lib-nal.md](./reference-lib-nal.md) — sibling symbolic engine.
- [reference-lib-ona.md](./reference-lib-ona.md) — planned temporal engine (experimental, not installed).
- [reference-orchestration.md](./reference-orchestration.md) — engine selection.
- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — worked examples.
