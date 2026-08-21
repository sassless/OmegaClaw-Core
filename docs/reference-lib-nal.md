# Reference — `lib_nal.metta`

Non-Axiomatic Logic (NAL) — a logic of uncertain reasoning with explicit evidence-based truth values. NAL is the primary symbolic engine for OmegaClaw's inheritance and implication reasoning.

---

## Truth value format

Every NAL statement carries `(stv frequency confidence)`:

- `frequency` ∈ [0.0, 1.0] — how often the statement held among observed evidence.
- `confidence` ∈ [0.0, 1.0] — how much evidence supports that frequency.

**Negation** is `(stv 0.0 c)`.

`w2c` in the formulas below denotes the NAL evidence-weight-to-confidence mapping; it is the standard NAL formula.

---

## Core relations

| Relation | Meaning |
|---|---|
| `-->` | **Inheritance.** `(--> a b)` ≈ "`a` is a kind of `b`". Asymmetric. |
| `==>` | **Implication.** `(==> P Q)` ≈ "if `P` then `Q`". |
| `<->` | **Similarity.** `(<-> a b)` ≈ "`a` and `b` are similar". Symmetric in principle but see limits below. |
| `×` | **Product.** `(× sam garfield)` ≈ the ordered pair. |
| `[]` | **Property set.** `([] dangerous)` ≈ the set of dangerous things. |
| `{}` | **Extensional set** — the compound listing its members. |
| `IntSet` / `ExtSet` | **Intensional / extensional set** (NAL-2 form; `IntSet` also shows up in the PLN examples). |
| `∩` `∪` | **Intersection / union** of terms (NAL-3). |
| `~` `−` | **Extensional / intensional difference** (NAL-3). |
| `¬` `∧` `∨` | **Negation, conjunction, disjunction** over statements (NAL-5). |

Not every operator here has a rule that `|-` can reach — see [The `|-` operator](#the---operator) and [Rules NOT to rely on](#rules-not-to-rely-on).

---

## The `|-` operator

```metta
lib_nal.metta:201-202
(= (|- $a $b)
   (unique-atom (collapse (superpose ((|-nal $a $b) (|-nal $b $a))))))
```

`|-` applies NAL inference, selecting rules from the `|-nal` clause set by premise shape. Two properties of this entry point govern everything below.

**`|-` takes exactly two premises.** It tries both premise orders, so argument order does not matter — but a third premise is not accepted, and a clause written against a *single* premise can never be selected. 20 of the 74 `|-nal` clauses are single-premise (`lib_nal.metta:117, 126, 127, 130, 131, 135-138, 140-147, 183-185`) and are unreachable through `|-` for that reason alone. Most entries in [Rules NOT to rely on](#rules-not-to-rely-on) are instances of this, not broken rules.

**`|-` returns a set of conclusions, not one conclusion.** `collapse` gathers every clause that matched, `unique-atom` removes duplicates. A single call routinely yields several results — deduction and exemplification both fire on the same pair of `-->` premises, and revision on two identical premises additionally emits two degenerate self-inheritances (see [Revision on shared term](#revision-on-shared-term)). Read the whole returned expression, not its first element.

---

## Rule catalogue

### Deduction — the workhorse

**Shape:** `(--> A B)` and `(--> B C)` ⊢ `(--> A C)` (`lib_nal.metta:110`).

**Truth function** (`lib_nal.metta:8-10`)**:**

```
f = f₁ × f₂
c = f₁ × f₂ × c₁ × c₂
```

Exemplification (`lib_nal.metta:113`) matches the same premise shape, so every `-->` deduction call also returns the reversed conclusion — two atoms out of one call.

### Abduction

**Shape:** `(--> A C)` and `(--> B C)` ⊢ `(--> B A)` (`lib_nal.metta:112`) — the premises share a **predicate**, and the conclusion runs from the second subject to the first.

**Truth function** (`lib_nal.metta:12-14`)**:**

```
f = f₂
c = w2c(f₁ × c₁ × c₂)
```

**Known limit:** confidence passes through `w2c`, which is bounded above by 0.5 no matter how strong the premises are. With `f₁ = 1.0` and both premises at `c = 0.9` the output is `w2c(0.81) = 0.4475` — where the familiar **~0.45 ceiling** comes from. Raising both premises to `c = 0.99` only buys `w2c(0.9801) = 0.4950`.

### Induction

**Shape:** `(--> A B)` and `(--> A C)` ⊢ `(--> C B)` (`lib_nal.metta:111`) — the premises share a **subject**, which is what makes this a generalization over things known about `A`.

**Truth function** — abduction with the premises swapped (`lib_nal.metta:16-17`)**:**

```
f = f₁
c = w2c(f₂ × c₁ × c₂)
```

The same `w2c` ceiling applies. Two instances of the same generalization at `c = 0.42` revise to `c = 0.5915` — use revision to combine multiple instances.

### Revision — merging independent evidence

**Shape:** two beliefs about the same statement (`lib_nal.metta:108`).

**Truth function** (`lib_nal.metta:92-99`)**:**

```
w = c / (1 - c)            per premise
w_total = w₁ + w₂
f_out = min(1.0, weighted average of f_i by w_i)
c_out = min(0.99, max(w2c(w_total), c₁, c₂))
```

The two clamps are easy to miss and both matter: confidence is capped at **0.99**, and it never comes out **below the better of the two inputs**, whatever the weights say.

Confidence rises strictly when evidence agrees. When evidence disagrees, frequency drifts toward the middle while confidence still grows — contradiction becomes mathematically visible.

**Check points, computed from the formula above:**

- Two sources at `(stv 1.0 0.45)` → `(stv 1.0 0.6207)`.
- A third source at `(stv 1.0 0.45)` → `(stv 1.0 0.7105)`.
- A fifth → `(stv 1.0 0.8036)`.

`|-` is two-place, so "three sources" means two successive calls, feeding the previous result back in as one premise. Note that `f` stays pinned at 1.0 across the whole series: when every input has `f = 1.0`, the weighted average is 1.0 by construction and no number of agreeing sources can move it.

### Exemplification

**Shape:** produced alongside deduction for `-->` premises.

**Truth function:**

```
f = 1.0
c = w2c(f₁ × f₂ × c₁ × c₂)
```

### Conditional deduction (modus ponens)

**Shape:** `(==> P Q)` and `P` ⊢ `Q` (`lib_nal.metta:191`).

**Truth function:** same as deduction (`f = f₁ × f₂, c = f₁ × f₂ × c₁ × c₂`). Both premises at `(stv 1.0 0.9)` give `(stv 1.0 0.81)`.

### Conditional syllogism (`==>` chaining)

Works with nested `-->` inside `==>`. Same deduction-style formula.

### Conditional abduction

**Shape:** `(==> P Q)` + observed `Q` ⊢ `P` (`lib_nal.metta:197`).

Frequency comes from the *implication* premise, confidence from the abduction formula. Observed `Q` at `(stv 1.0 0.9)` against `(==> P Q)` at `(stv 0.9 0.9)` gives `P (stv 0.9 0.4475)`: `f = f₂ = 0.9`, `c = w2c(1.0 × 0.9 × 0.9)`. As with plain abduction the confidence stays under 0.5.

### Conjunctive antecedents

**Shape:** `A` and `(==> (∧ A B) C)` ⊢ `(==> B C)` (`lib_nal.metta:194`), with negated variants at `lib_nal.metta:195-196`.

`(==> (∧ A B) C)` is directly representable, and these clauses are two-premise, so `|-` reaches them: supplying one conjunct discharges it and returns the residual implication under the deduction truth function. What is *not* reachable is splitting a bare `(∧ A B)` into its conjuncts — those clauses are single-premise (`lib_nal.metta:184-185`).

### Implication chaining

**Shape:** `(==> A B)` and `(==> B C)` ⊢ `(==> A C)` (`lib_nal.metta:179`), under the deduction truth function. Induction and abduction over `==>` sit next to it (`lib_nal.metta:180-181`). All three are two-premise, so `|-` reaches them — chaining is automatic and does not have to be walked by hand. Nested `-->` inside `==>` chains the same way.

### Multi-instance induction

Two instances each at `c = 0.42` revise to `c = 0.5915` (`w = 0.42 / 0.58 = 0.7241` apiece, `w2c(1.4483) = 0.5915`). Combine induction with revision to build up evidence.

### Higher-order via proxy

Use atomic labels for rules as subjects. Pattern confirmed: `birdRule --> reliable --> trustworthy` compiles and reasons.

### Negation

Via `(stv 0.0 c)`. It propagates, but watch what the formulas do with it: deduction multiplies frequencies into the confidence term (`c = f₁ × f₂ × c₁ × c₂`), so a premise at `f = 0.0` yields a conclusion at `c = 0.0`. That same collapse is what makes the contrapositive useless — see [Rules NOT to rely on](#rules-not-to-rely-on).

### Similarity (`<->`)

Reachable through the NAL-2 resemblance and comparison rules (`lib_nal.metta:118-120`), which are two-premise. **Position-sensitive** — a clause matches only when the shared term sits in the argument position that clause was written for. The clause that would make `<->` symmetric (`lib_nal.metta:117`) is single-premise, so `|-` never selects it and symmetry is not restored for you. Supply the premise in the orientation the rule expects, or state both orientations.

### Analogy

Reachable through `lib_nal.metta:121-124` (four clauses covering the argument positions), truth function `Truth_Analogy` (`lib_nal.metta:50-52`):

```
f = f₁ × f₂
c = c₁ × c₂ × f₂
```

The trailing `× f₂` is easy to overlook and it dominates whenever the similarity premise is weak: `(stv 1.0 0.9)` against `(stv 0.25 0.4)` gives `c = (0.9 × 0.4) × 0.25 = 0.09`, not 0.36. Same positional sensitivity as similarity.

---

## Rules NOT to rely on

| Pattern | Status |
|---|---|
| **Any single-premise rule** | Unreachable. `|-` always calls `|-nal` with two premises (`lib_nal.metta:201-202`), so the 20 single-premise clauses are never selected. That covers `<->` symmetry, properties and instances, set and intersection decomposition, and `¬` / `∧` elimination. |
| **NAL-3 decomposition from one premise** | Unreachable for that reason (`lib_nal.metta:135-147`). The two-premise decompositions are fine — `DecomposePNN / NPP / PNP / NNN` at `lib_nal.metta:149-160` do fire. |
| **Contrapositive** | Returns the antecedent at `c = 0.0`. `Truth_Negation` drives `f₁` to 0 and abduction's confidence is `w2c(f₁ × c₁ × c₂)` (`lib_nal.metta:12-14, 198`), so the result carries no evidence. |
| **Similarity / analogy (full symmetry)** | Argument-position-sensitive. The symmetry clause exists but is single-premise (`lib_nal.metta:117`). |
| **Premises at `c = 1.0`** | `Truth_c2w` divides by `1 - c` with a plain `/` (`lib_nal.metta:2-3`), so revision against a `c = 1.0` premise divides by zero. PLN guards the same expression with `/safe` (`lib_pln.metta:52-53`) and returns empty instead. Keep confidences strictly below 1.0. |

---

## Invocation

NAL is reached through the `(metta ...)` skill. Variables use `$1`, `$2`, …

### Deduction

```metta
(metta (|- ((--> sam human)         (stv 1.0 0.9))
           ((--> human mortal)      (stv 1.0 0.9))))
```

### Implication with variable unification

```metta
(metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))
           ((--> (× tiger elephant) eat)                            (stv 1.0 0.9))))
```

### Revision on shared term

```metta
(metta (|- ((--> wolf animal) (stv 1.0 0.45))
           ((--> wolf animal) (stv 1.0 0.45))))
```

Output: `(--> wolf animal) (stv 1.0 0.6207)`.

Two more conclusions come back with it. Identical premises also satisfy the induction and abduction clauses (`lib_nal.metta:111-112`) — they match on the shared subject and on the shared predicate and return `(--> animal animal)` and `(--> wolf wolf)`, both at `(stv 1.0 0.1684)`. Harmless, but they are in the result set; this is what "`|-` returns a set" looks like in practice.

---

## Multi-hop degradation — in numbers

Every premise at `(stv 1.0 0.9)`, chaining deduction (`c_out = f₁ × f₂ × c₁ × c₂`, `lib_nal.metta:8-10`):

| Hop | Output `c` |
|---|---|
| 1 | 0.810 |
| 2 | 0.729 |
| 3 | 0.656 |
| 4 | 0.590 |
| 5 | 0.531 |
| 6 | 0.478 |

With `f = 1.0` throughout, each hop simply multiplies confidence by the incoming premise's `c` — hence the "roughly 10% per hop" shorthand at `c = 0.9`. Frequencies below 1.0 make the decay steeper, because `f₁ × f₂` enters the confidence term as well.

Hop 6 is the first to drop under the ACT gate (`c ≥ 0.5`, see [reference-orchestration.md](./reference-orchestration.md)). This is a **feature, not a bug** — the math honestly represents diminishing certainty. Practical implication: keep chains short and insert revision to restore confidence, rather than assuming four hops are automatically safe.

---

## See also

- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — worked examples for each rule.
- [reference-lib-pln.md](./reference-lib-pln.md) — the probabilistic counterpart.
- [reference-lib-ona.md](./reference-lib-ona.md) — planned real-time / temporal engine (experimental, not installed).
- [reference-orchestration.md](./reference-orchestration.md) — when to pick NAL vs. PLN.
- [reference-failure-modes.md](./reference-failure-modes.md) — known failure rates for NAL-using chains.
