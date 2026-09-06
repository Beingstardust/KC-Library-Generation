# KC_L evaluation record — v3, internal final

**Documentation-consolidation date:** 2026-09-02
**Predecessor record:** `KCL_EVALUATION_RECORD.html` (published state, closed 2026-09-01), retained
unchanged.
**Findings log:** `EVALUATION_FINDINGS.md`, F-01 … F-58, retained with statuses.

> **Nature of the changes in this version.** Interpretive, statistical-documentation, and scope
> corrections only, plus one new analysis computed from **existing** data (paired retrieval intervals).
>
> - Raw experimental artifacts: **unchanged**
> - Expert reference text: **unchanged**
> - Candidate drafts and evidence: **unchanged**
> - Judge outputs: **unchanged**
> - Completed statistical results: **unchanged** (added to, not altered)
>
> Superseded and withdrawn findings are retained with explicit status. Nothing was deleted.

**Companion documents.** This record is the narrative; the operative documents for writing are
`PAPER_CLAIM_LEDGER.md` (what may be asserted), `PAPER_NONCLAIMS.md` (what may not),
`RESULTS_EVIDENCE_MATRIX.md` (what each result rests on), `PAPER_NUMBERS_SOURCE_OF_TRUTH.md` (every
figure), and `RQ_EVIDENCE_MAPPING_FINAL.md` (what the thesis actually asks).

---

## I. Evaluation design

Seven frozen candidate arms over 159 data-mining knowledge components (1,113 rows), in two
pre-registered families, plus a crossed 3-drafter × 3-domain design (1,137 rows).

| family | varies | holds fixed | property claimed |
|---|---|---|---|
| extrinsic | retrieval (Proposed / DOS-RAG / BaseDense) | drafter (Qwen) | retrieval performance |
| intrinsic | drafter (Qwen / Gemma / DeepSeek) | retrieval | drafter performance **sensitivity** |
| domain | subject (data-mining / mathematics / sociology) | — | cross-domain performance **sensitivity** |

The seven arms correspond to **four distinct retrieval configurations**; the four Proposed-lineage
arms share one evidence configuration. `extrinsic P-Q` and `intrinsic P-Q` are different artifacts
(different commit and prompt mode, 17/159 identical drafts) and are not interchangeable.

**Terminology, fixed.** The intrinsic and domain families measure *performance sensitivity*. They are
**not** tests of model- or domain-agnosticism, which are **architectural** properties evidenced by
implementation audit and by multi-family / multi-domain execution (§V(a), §VI(a)). Portability does
not imply performance invariance, and failure of a performance-equivalence test says nothing about
whether the architecture is agnostic.

The two sensitivity families make **equivalence** claims, which require equivalence statistics. v2
tested them with difference tests and read non-significance as equivalence; that error is corrected
in v3.

## II. Reference construction and validity

The reference library is **machine-seeded**: 117 of 159 references are accepted Qwen drafts unchanged,
and the seed arm is identified by exact string match (159/159; next closest arm 17/159).

Six anti-anchoring controls were specified. The decisive one — seed-blind reconstruction — was
executed: 30 KCs stratified on the expert's own edit codes, compared blinded and order-randomised.

**Result.** Across 27 comparable KCs: **0** material semantic differences, **0** cases of the seeded
reference asserting unsupported content, 18/27 equivalent or both-valid. No stratum effect in the
direction seed bias predicts (ACCEPT 13/18, CHANGED 5/9).

**What the audit tested, and what it did not.** It tested semantic distortion and unsupported
assertion. It did **not** test omission of source-supported content, seed-shaped content selection, or
provenance error. It *did* test corpus-support correctness, and **disagreed**: all three sampled
corpus-unsupported KCs were classified as supported by the independent reviewer.

The correct summary is therefore: *the seed-blind audit found no semantic distortion or unsupported
assertions among comparable substantive references, but exposed residual disagreement over the
corpus-support boundary.* The threat was **sized**, not eliminated.

**Methodological decision — accepted references were not paraphrased.** Seed-derived references
accepted by expert review were deliberately not rewritten to reduce lexical similarity to Qwen.
Evaluation is semantic rather than lexical, so cosmetic paraphrasing would not address the anchoring
threat that matters — which concerns *content selection* — and rewriting only the Qwen-identical
references after results were known would itself be a post-hoc intervention. Rewriting would also
perturb nugget decomposition, VITAL labelling, and every reference-based metric value. The protection
applied instead was source-grounded expert review, explicit seed provenance, semantic evaluation, and
the seed-blind audit.

**Empirically, the judge matches meaning rather than wording.** DeepSeek scores 0.69 vital-nugget
recall at 1.5% 8-gram overlap with the reference; 32 of 66 Gemma drafts with under 5% overlap score
1.0. The overlap–recall correlation is +0.80 for the seed arm but +0.11/+0.21 for the others — the
same judge, which excludes judge-side lexical bias and localises the residual asymmetry to the two
Qwen-lineage arms' completeness figures.

## III. Judge and instrument validation

**Status is criterion-specific. There is no single blanket judge status.**

| task | status |
|---|---|
| binary completeness (v1) | **FAILED** — raw 0.556, AC1 0.392, PASS recall 0.400 |
| graded completeness (v2) | met the pre-registered thresholds under leave-one-out calibration: raw 0.8611, AC1 0.7224, PASS recall 0.8000, FAIL recall 0.9375 |
| M1, M2, TARGET, M4A | `INSUFFICIENT_VALIDATION_SUPPORT` — inadequate minority-class support (6, 8, 5, and 0 respectively) |

**The graded result is development calibration, not external qualification.** The 36 human labels
also contributed to development and adoption of the replacement metric, so they are not an
independent held-out set. Leave-one-out thresholding avoids fitting and testing on the same row, but
does not make the label set independent. `INSUFFICIENT_VALIDATION_SUPPORT` is neither PASS nor FAIL
and must not be collapsed into either.

**Instrument-sensitivity analysis.** An independent entailment verifier — MiniCheck-Flan-T5-Large,
an encoder-decoder sharing no lineage with the primary judge or any drafter — scored the identical
stored claims: 7,747 matched ablation and 7,914 matched crossed claims, zero length mismatches.
Per-claim raw agreement 0.7176, **Gwet AC1 0.6076**, arm-ordering Spearman **ρ = +0.4286**.

Read AC1, not κ: at 94% prevalence κ = 0.074 through the kappa paradox, and the pre-registered
protocol already records κ as secondary.

This measures **reliability and construct sensitivity, not human validity**. Neither instrument is
ground truth. Their disagreement traces to a measured cause — strict entailment correlates with
document words at r = +0.261 where the support rubric does not — and is a construct difference, not
one instrument being wrong.

**Instrument properties established.** Serial-position sensitivity (recovery of provably-present
content 1.0000 → 0.9934 → 0.5905 at 17/33/123 passages, truncation excluded); a task-dependent sign
reversal under the same padding (context recall −0.4095, faithfulness +0.0175); serving-configuration
effects on reproducibility (1/144 verdict changes under concurrency, 0/144 with batch-invariant
kernels).

## IV. Retrieval evaluation

Rebuilt as a **pooled test collection**: the union of top-20 from seven evaluated arms across four
distinct retrieval configurations, each passage judged individually. 8,246 judgements.

**These labels are automated.** They were produced by the frozen Selene judge and **no human has
validated any of them.** Every retrieval statement must carry "under automated pooled relevance
judgements". They are not gold qrels.

Paired differences, concept-clustered bootstrap, B = 10,000:

| comparison | metric | paired Δ | 95% CI | reading |
|---|---|---|---|---|
| Proposed vs DOS-RAG | P@10 | −0.0006 | [−0.0500, +0.0481] | no separation |
| | R@10 | +0.0019 | [−0.0245, +0.0280] | no separation |
| | **nDCG@10** | **+0.1141** | [+0.0659, +0.1604] | Proposed ranks earlier |
| | nDCG@5 | +0.2049 | [+0.1470, +0.2618] | larger at k=5 |
| | **R@20** | **−0.1332** | [−0.1848, −0.0823] | DOS-RAG deeper |
| Proposed vs BaseDense | all 9 | all favour Proposed | all exclude zero | — |
| DOS-RAG vs budget-matched | R@20 | +0.2147 | [+0.1771, +0.2564] | attenuates when matched |

**No equivalence test is reported for retrieval.** No equivalence margin was pre-registered, and
choosing one after observing a 0.0006 difference would be post hoc. "No material separation" is the
supportable phrasing; "equivalent" is not.

**Pool incompleteness** remains: relevant passages ranked below 20 by every configuration are
unjudged and counted non-relevant. Note the pool takes each arm's top 20 — BaseDense's 123 native
passages did not all enter it.

## V. Drafting-model evaluation

**Two distinct claims, kept apart.**

**(a) Architectural — the drafting layer is model-agnostic. SUPPORTED.** All generation flows through
one `ollama_generate(host, model, …)` call; a search for conditionals on model identity across the
pipeline returns nothing; the model arrives as a CLI argument with an environment default; and the
single capability accommodation (`"think": False`) is applied unconditionally, with the code comment
recording that it is general rather than model-specific. All three drafters emit the same output
contract, and all nine drafter × domain cells parsed under one extraction contract with no per-model
handling. Scope: three model families were exercised — this is not a claim that any LLM will work.

**(b) Performance — quality is not invariant to drafter choice. NOT ROBUST, and not required by (a).**
Groundedness across the crossed design, under two instruments.

**Supportable:** Gemma ≥ Qwen > DeepSeek in mathematics and data-mining under both instruments.

**Not supportable:** that drafters perform equivalently. The **drafter performance-equivalence
analysis** (TOST) at the pre-registered δ = 0.05 gives
Qwen ≡ Gemma in all three domains under the primary instrument but **1 of 3** under the verifier; only
5 of 9 comparisons agree, and in sociology the verifier finds DeepSeek equivalent to both others. The
equivalence conclusion is evaluator-dependent and margin-dependent. The TOST analysis is retained; its
interpretation carries the dependence.

Variance decomposition (drafter facet: 0.0–6.4% across in-scope drafters, 15.5–39.5% including
DeepSeek) is `SECONDARY`: one observation per cell confounds the drafter × KC interaction with error,
and G-coefficients are 0.0–0.42.

DeepSeek's compliance characteristics — 118/114/123 words across three domains against Qwen's
208/234/245, and self-reported `grounded` on ~99% of KCs — are **descriptive**. They support treating
it as behaving differently, not as a demonstrated quality deficiency.

## VI. Cross-domain evaluation

**(a) Architectural — the pipeline is domain-agnostic. SUPPORTED.** Domain knowledge enters through
the corpus and curriculum rather than through domain-specific implementation logic. This was once
false: a 2026-08-16 audit found ~66 data-mining-specific decisions per run, which would also have
confounded cross-domain comparison. Remediation D-1…D-7 completed 2026-08-17 and was AST-verified,
leaving exactly one subject-vocabulary string in executable code — a docstring example, not
behaviour. Confirmed against the **evaluated** artifacts: zero semantic-misbinding drops, data-mining
domain-specific drops down from ~66 to 15, and the generic math-damage detector now firing in all
three domains (1/2/7) with mathematics highest. Residual, disclosed: `compound_sibling_ownership`
fires 8× in data-mining and 0× elsewhere — a data-driven asymmetry from curriculum shape, not
hardcoding. See `DOMAIN_AGNOSTICISM_IMPLEMENTATION_AUDIT.md`.

**(b) Performance — quality is not invariant across domains. NOT SUPPORTED, and not required by (a).**
The **cross-domain performance sensitivity analysis**: data-mining and sociology fall within δ = 0.05
for in-scope drafters under the primary instrument; **mathematics is consistently harder** and falls
outside the margin for every drafter, though the absolute gaps are 0.032–0.065.

Reference-based metrics are **undefined**, not merely unmeasured, outside data-mining: no reference
library exists there. Cross-domain evidence rests on groundedness alone.

## VII. Abstention and source boundaries

Under the adjudicated reference standard, Proposed abstained on all seven KCs classified as
corpus-unsupported, whereas DOS-RAG drafted on five.

**This is `PROVISIONAL_PENDING_SUPPORT_BOUNDARY_AUDIT`.** The seed-blind audit classified all three
unsupported KCs in its sample as *supported*, so the labels this comparison depends on are contested.
It must not be headlined as a settled safety result. See `SUPPORT_BOUNDARY_REVALIDATION_PLAN.md`.

Separately and unaffected: **no arm produced a description from an empty evidence set** across all
1,113 rows. This is a property of the harness abstention contract and should be attributed as such.

## VIII. Reproducibility

**Evaluation-stage reproducibility** — a rerun of claim decomposition and judging over the same
drafts reproduced **99.83%** of matched per-claim decisions (7,610 claims from 996 drafts;
15 drafts excluded where re-decomposition changed the claim count). Support-rate drift −0.0001;
maximum arm-level drift 0.0027; ordering ρ = +0.9643.

**Scope, mandatory.** This covers claim decomposition and judging **only**. Retrieval was not re-run,
drafting was not re-run, and the KC library was not regenerated. It is not end-to-end pipeline
reproducibility and must not be described as such.

Its function is as the baseline that makes §III's cross-instrument disagreement interpretable:
0.9983 within instrument against 0.7176 across instruments.

## IX. Negative results

Retained deliberately.

- **Automated editorial triage failed.** 97.2–99.3% of every arm in the top two categories,
  `UNUSABLE` never used across 1,113 drafts, exact agreement with expert codes 0.462. Not usable as a
  quality metric. Third metric in the campaign to sit at ceiling, with M2 correctness and TARGET
  alignment.
- **Context recall was withdrawn** as a cross-arm retrieval metric: no rank cutoff, and confounded by
  serial-position sensitivity.
- **All-or-nothing faithfulness and holistic completeness were superseded**, both retained in history
  with the artifacts that disqualified them.
- **No human–human agreement exists** anywhere in the project; only one annotation pass was made.

## X. Threats to validity

See `THREATS_TO_VALIDITY_MASTER.md`. The three that currently constrain claims most:

1. **Automated relevance labels** — the entire retrieval argument rests on unvalidated judge labels
   (**P2**).
2. **Unaudited nugget decomposition** — completeness is measured against a yardstick nobody has
   checked (**P3**).
3. **Contested support boundary** — the abstention result measures a boundary two reviewers disagree
   about (**P1**).

## XI. Supported claims

See `PAPER_CLAIM_LEDGER.md` for the full set with allowed and prohibited wording. Summary:

- Proposed outperforms BaseDense at every measured cutoff (automated qrels).
- Proposed ranks definitional material earlier than DOS-RAG at k=5 and k=10.
- DOS-RAG recovers more by rank 20, under its larger native budget.
- Proposed operates on roughly half DOS-RAG's evidence.
- Gemma ≥ Qwen > DeepSeek in mathematics and data-mining, under both instruments.
- The drafting layer is model-agnostic by architecture; three model families ran the same contract.
- The pipeline is domain-agnostic by architecture; three subject domains ran the same architecture.
- No arm drafted from an empty evidence set.
- The seed-blind audit found no distortion or unsupported assertion among comparable references.
- Evaluation-stage reruns reproduce at 99.83%.
- Graded completeness met its gates under development calibration.

## XII. Unsupported, provisional, and withdrawn claims

- **Withdrawn:** "drafters perform equivalently"; "Proposed retrieves better than DOS-RAG"; the
  original context-recall efficiency claim; "the seed question is settled".
  *(Note: the architectural model- and domain-agnosticism claims were never withdrawn. An earlier
  consolidation pass withdrew them in error by treating them as performance claims; see
  `MODEL_AGNOSTICISM_CONSISTENCY_AUDIT.md`.)*
- **Provisional:** the abstention safety result (**P1**).
- **Not answered at all:** the *usefulness for evaluation* component of RQ2.1 — this campaign measures
  coverage and grounding, and nothing about downstream utility in dialogue evaluation.
- **Never claim:** equivalence at k=10; human-gold qrels; end-to-end pipeline reproducibility;
  universal statements about LLM judges, serial position, or batch invariance.

## XIII. Reproducibility manifest

| artifact | rows | content |
|---|---|---|
| `ablation_rows.jsonl` | 1,113 | frozen drafts and evidence, 159 KC × 7 arms |
| `crossed_rows.jsonl` | 1,137 | 3 drafters × 3 domains |
| `v2_nuggets.jsonl` | 152 | decompositions; 151 usable, 1,185 nuggets, 475 vital |
| `v2_assign.jsonl` | 1,057 | nugget assignment, 151 scored KCs × 7 arms |
| `v2_context.jsonl` | 604 | context judgements, 4 configs × 151 KCs |
| `v2_faith.jsonl` | 1,114 | groundedness; 1,113 unique keys, one superseded record retained |
| `v3_pooled_relevance.jsonl` | 8,246 | pooled relevance labels (**automated**) |
| `v3_claims_ablation/crossed.jsonl` | 1,113 / 1,137 | stored claim texts |
| `v3_selene_stored_*.jsonl` | 1,012 / 1,071 | primary instrument over stored claims |
| `v3_minicheck_*.jsonl` | 1,012 / 1,071 | independent verifier over the same claims |
| `v2_f45_dilution.jsonl` | 453 | serial-position experiment |
| `v2_f46_faith_dilution.jsonl` | 145 | padding sign-reversal experiment |
| `seed_audit_comparison.jsonl` | 30 | seed-blind reconstruction comparison |

Gates: `audit_v2_outputs.py` (21/21 checks) and `audit_campaign_accounting.py` (38/38 quantities).
Regenerators: `build_v2_report.py`, `analyse_v3.py`, `analyse_retrieval_paired.py`,
`build_paper_numbers.py`.
