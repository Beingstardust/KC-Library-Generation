# Domain-agnosticism implementation audit

**Purpose.** The architectural claim *"the pipeline is domain-agnostic"* is conditional on there being
no subject-specific semantic logic in the production path. This audit establishes whether that holds,
so the claim can be made on evidence rather than on design intent.

**Scope note.** This is a code-and-artifact audit. It does not re-run experiments and does not touch
any frozen artifact.

---

## 1. The definition being tested

Domain-agnostic means **subject knowledge enters through the corpus and curriculum, not through
hardcoded pipeline semantics**. It does not mean equal performance across domains — that is
cross-domain performance sensitivity, measured separately.

The audit therefore looks for *semantic branches keyed on subject matter*, and distinguishes them
from *domain configuration and input data*, which are legitimate.

| legitimate | violation |
|---|---|
| a data-mining curriculum supplied as input | `if KC == "Spearman": include next equation` |
| a generic formula-damage detector | 41 regexes naming specific metrics |
| KC identities derived from the supplied hierarchy | a hardcoded roster of benchmark KC ids |
| a selectable corpus path | a filename-specific branch |

## 2. Prior state: the claim was once false, and this was found and fixed

An audit on **2026-08-16** found the claim unsupported by the code. The verified evidence path
contained roughly **66 active data-mining-specific decisions per run**. Measured from real packets:

| domain | units | total drops | generic rival adjudication | **domain-specific rules** |
|---|---|---|---|---|
| data-mining | 159 | 175 | 109 | **66** |
| sociology | 149 | 108 | 106 | **0** |
| mathematics | 71 | 29 | 23 | **0** |

This carried a second problem beyond the false claim: because every hardcoded rule keyed on a
data-mining KC name, **data-mining received help the other two domains never got**, which would
confound any cross-domain comparison.

A remediation tracked seven defects (D-1 … D-7) to closure, recorded in
`DOMAIN_AGNOSTICITY_REMEDIATION.md`, and declared **COMPLETE on 2026-08-17**, verified by AST audit
across the whole verified evidence path: exactly one subject-vocabulary string constant remains in
executable code, and it is a docstring example illustrating acronym derivation, not behaviour.

| id | resolution |
|---|---|
| D-1 | 18 per-KC misbinding rules removed; `semantic_misbinding_owner()` reduced to a no-op seam |
| D-2 | compound ownership derived from `all_unit_names` plus the compound name's own qualifier |
| D-3 | `_STANDARD_DBSCAN_UNITS` emptied |
| D-5 | eponym roster replaced by a hyphenated proper-noun shape rule |
| D-6 | 41 metric-named damage regexes replaced by 4 structural patterns |
| D-7 | curated per-KC query vocabulary emptied |

Notably, damage detection went **up** after removing the hardcodes (1008 → 1027 on the real corpus),
because structural patterns catch damage in metrics nobody had hardcoded.

## 3. The question this audit had to answer

The remediation was explicitly applied **without regenerating existing artifacts** — the standing
instruction was that results and ablations were not to be re-run. So the fix being in the code does
not by itself establish that the **evaluated candidates** were produced by the fixed code.

If they were not, the cross-domain comparison would carry exactly the confound the remediation
identified.

## 4. Verification against the frozen artifacts

Tested directly on the evaluated packets (`r9_latest_20260822T202514Z`, built 2026-08-22, after the
2026-08-17 remediation). Drop reasons recorded per unit:

| domain | units | generic rival drops | named domain-mechanism drops |
|---|---|---|---|
| data-mining | 159 | 132 | `compound_sibling_ownership` 8 · `stranded_numerator_denominator_severed` 4 · `stranded_numerator_substituted_intact` 2 · `assembled_passage_math_rendering_damaged` 1 |
| sociology | 149 | 108 | `assembled_passage_math_rendering_damaged` 2 |
| mathematics | 71 | 33 | `assembled_passage_math_rendering_damaged` 7 |

**Three independent signals confirm the evaluated artifacts came from post-remediation code:**

1. **No semantic-misbinding drops appear in any domain.** D-1 reduced that mechanism to a no-op, and
   the artifacts show it firing zero times. Pre-remediation it was 18 per-KC rules.
2. **Data-mining's domain-specific decisions fell from ~66 to 15.** The remaining ones are the
   generic replacements, not the removed hardcodes.
3. **The math-damage detector now fires in all three domains** (1 / 2 / 7), and **mathematics gets the
   most** — which is what a *generic* formula-damage detector should do. The pre-remediation version
   was 41 metric-named regexes that could only ever fire for data-mining.

**Conclusion: the evaluated candidates were produced by domain-agnostic code, and the cross-domain
comparison is not confounded by the asymmetry the remediation identified.**

## 5. Residual asymmetry, stated

`compound_sibling_ownership` fires 8 times in data-mining and zero times in sociology and
mathematics. This is **not** hardcoding — after D-2 the mechanism derives ownership from
`all_unit_names` and the compound name's own qualifier, with no subject vocabulary involved. It fires
more in data-mining because that curriculum contains more compound KC names of the triggering shape.

That is a **data-driven** asymmetry, not a logic-driven one, and it is exactly the distinction the
architectural claim rests on: subject matter enters through the curriculum, not through the code.
It should nonetheless be disclosed, because the *effect* is still domain-unequal.

## 6. Accepted costs, recorded rather than hidden

The remediation traded capability for genericity, and the tracker records the price:

- ~66 contamination drops in data-mining lost (2.6% evidence increase across 20 of 159 units);
- ~35 metric-specific damage detections lost — silhouette numeric forms, purity weight bar, extended
  Jaccard denominator — each of which needs the formula's identity to recognise;
- three data-mining units lose label disambiguation their registry names alone cannot supply.

These are real losses in data-mining performance accepted in exchange for a claim that is true.

## 7. Stages covered

Verified execution path, confirmed by reading call sites rather than import lists
(`v3/pipeline/02_build_kc_packets.py`, lines 367-378): rival identification, math-damage dropping,
compound-sibling ownership, semantic misbinding (no-op), and rival adjudication.
`03_build_topic_packets.py` imports no `evidence_pack` functions and inherits the KC packets, so the
KC path governs both.

Modules confirmed **not** in the execution path, whose KC-id mentions are comments only:
`branch_scoping.py`, `evidence_pack_composition.py`, and the `evidence_stage_v3_*` modules.

## 8. What domain portability still requires

Domain-agnostic does not mean input-free. Portability requires:

- a sufficiently informative source corpus;
- a curriculum or hierarchy from which target KCs can be defined;
- source material convertible into the pipeline's corpus representation;
- a compatible drafting model.

These are **inputs**, not hardcoded semantics, and they do not contradict the architectural claim.

## 9. Audit verdict

| claim | verdict |
|---|---|
| `DOMAIN_ARCHITECTURE_AGNOSTIC` | **SUPPORTED.** No subject-specific semantic logic remains in the verified execution path; one docstring example is the sole subject-vocabulary string, and it is not behaviour. |
| Evaluated artifacts produced by agnostic code | **SUPPORTED.** Confirmed by three independent signals in the frozen packets. |
| `CROSS_DOMAIN_PORTABILITY_TESTED` | **SUPPORTED_WITH_SCOPE.** Data Mining, Mathematics, Sociology; those corpora and curriculum structures. |
| `CROSS_DOMAIN_PERFORMANCE_INVARIANCE` | **NOT SUPPORTED, AND NOT REQUIRED.** Mathematics is measurably harder. |

**Limit of this audit.** It covers the verified evidence path and the drafting stage. It is a
static and artifact-based audit, not a proof: a semantic dependency expressed without subject
vocabulary — through thresholds tuned on data-mining, for instance — would not be caught by a string
audit. The accepted-costs section above is the honest indication that such tuning existed and was
removed.
