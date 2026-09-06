# Paper claim ledger

**This is the source of truth for what the paper may assert.** Every paper-facing claim has a row.
If a sentence in the thesis is not traceable to a row here, it is not yet supported.

Machine-readable twin: `PAPER_CLAIM_LEDGER.json`.

## Status vocabulary

| status | meaning |
|---|---|
| `SUPPORTED` | Holds as stated, within the population given. |
| `SUPPORTED_WITH_SCOPE` | Holds only with the stated scope attached. The scope is not optional. |
| `SECONDARY` | Reportable, but not load-bearing for the thesis argument. |
| `PROVISIONAL` | Numerically computed, but a known dependency is unresolved. Do not headline. |
| `NEGATIVE_RESULT` | A measurement that failed. Reported as a finding, not hidden. |
| `SUPERSEDED` | Replaced by a better measurement. Retained in history. |
| `WITHDRAWN` | Was asserted, then refuted or found unsupportable. Retained in history. |

---

## A. Retrieval (extrinsic)

### `RET_PROP_VS_BASE` — Proposed retrieves better than BaseDense
**Status:** `SUPPORTED_WITH_SCOPE`
**Population:** 159 data-mining KCs · **Metric:** P/R/nDCG @5,10,20 on pooled judgements
**Result:** Proposed exceeds BaseDense on **all nine** metric/cutoff combinations, every 95%
concept-clustered bootstrap CI excluding zero. P@10 +0.2545 [+0.2058, +0.3045]; nDCG@10 +0.2799
[+0.2363, +0.3229].
**Allowed:** "Proposed outperformed the dense baseline at every measured cutoff under automated
pooled relevance judgements."
**Prohibited:** any phrasing implying human-validated relevance labels.
**Limitation:** qrels are automated (see `QREL_AUTOMATED`).

### `RET_DOS_NDCG` — Proposed ranks definitional evidence earlier than DOS-RAG
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** nDCG@10 paired difference **+0.1141 [+0.0659, +0.1604]**, CI excludes zero.
Also nDCG@5 +0.2049 [+0.1470, +0.2618] and P@5 +0.1117 [+0.0519, +0.1714].
**Allowed:** "Proposed placed relevant and definitional passages earlier in the ranking than DOS-RAG
at k=5 and k=10, under automated pooled relevance judgements."
**Prohibited:** "Proposed retrieves more relevant evidence than DOS-RAG overall." It does not — see
`RET_DOS_DEEP`.

### `RET_DOS_TOP10` — Proposed and DOS-RAG at k=10
**Status:** `SUPPORTED_WITH_SCOPE` (descriptive similarity only)
**Result:** P@10 paired difference **−0.0006 [−0.0500, +0.0481]**; R@10 **+0.0019 [−0.0245, +0.0280]**.
Both intervals contain zero.
**Allowed:** "P@10 and R@10 showed no material separation between Proposed and DOS-RAG; the paired
intervals contain zero."
**Prohibited:** "statistically equivalent", "equivalent". **No retrieval equivalence margin was
pre-registered**, and inventing one after seeing a 0.0006 difference would be post hoc.

### `RET_DOS_DEEP` — DOS-RAG recovers more material deeper in the ranking
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** R@20 paired difference **−0.1332 [−0.1848, −0.0823]** and P@20 **−0.1321 [−0.1789,
−0.0857]** — both favour DOS-RAG, CIs exclude zero.
**Allowed:** "DOS-RAG recovered more relevant material by rank 20, in the configuration with the
larger native retrieval budget."
**Prohibited:** "this is caused by budget". See `RET_BUDGET`.

### `RET_BUDGET` — the deep-rank advantage co-occurs with the larger budget
**Status:** `SECONDARY`
**Result:** Against its own budget-matched sensitivity arm, DOS-RAG's advantage at depth is
R@20 +0.2147 [+0.1771, +0.2564] and P@20 +0.2155 [+0.1793, +0.2516]; at k=5 the budget-matched arm is
*better* (nDCG@5 −0.1178 [−0.1642, −0.0714] against native DOS-RAG).
**Allowed:** "DOS-RAG's deeper-rank advantage is attenuated in the budget-matched condition, which is
consistent with a retrieval-budget effect."
**Prohibited:** "caused by budget" — no analysis isolates the mechanism.

### `RET_COMPACT` — Proposed operates on a smaller evidence set
**Status:** `SUPPORTED`
**Result:** 17.2 passages/KC vs DOS-RAG 33.7 and BaseDense 123.1 (descriptive, from frozen artifacts).
**Allowed:** as stated. This is a property of the artifacts, not a judged measurement.

### `QREL_AUTOMATED` — the relevance labels are automated
**Status:** `SUPPORTED` (a limitation, stated as a claim so it cannot be dropped)
**Result:** 8,246 passage judgements produced by the frozen Selene judge; 1,751 DEFINITIONAL /
2,505 RELATED / 3,990 NOT_RELEVANT. **No human validation of these labels exists.**
**Required wording wherever retrieval results appear:** "under automated pooled relevance judgements".
**Prohibited:** "human gold qrels", "gold-standard relevance labels".

### `POOL_DEPTH` — pool construction and its incompleteness
**Status:** `SUPPORTED`
**Result:** Union of **top-20** from seven evaluated arms corresponding to **four distinct retrieval
configurations** (the four Proposed-lineage arms share one evidence configuration).
**Prohibited:** "seven diverse retrieval runs"; "BaseDense contributed 123 passages to the pool" —
only its top 20 entered.
**Limitation:** relevant passages ranked below 20 by *every* configuration are unjudged and counted
non-relevant.

---

## B. Groundedness and drafters (intrinsic)

### `GND_INSTRUMENT` — groundedness ranking is instrument-sensitive
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Two instruments over 7,747 matched ablation claims: raw agreement 0.7176, Gwet AC1
0.6076, arm-ordering Spearman ρ **+0.4286**. Only the endpoints agree.
**Allowed:** "The full seven-arm groundedness ordering was instrument-sensitive; only the endpoints
reproduced across instruments."
**Prohibited:** any headline seven-arm groundedness ranking presented as objective.

### `GND_ENDPOINTS` — the endpoints reproduce
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** DOS-RAG highest and DeepSeek-R1 lowest under both instruments.
**Allowed:** as stated, with both instruments named.

### `DRAFT_ORDER` — drafter ordering
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Gemma ≥ Qwen > DeepSeek in mathematics and data-mining under both instruments;
**sociology is instrument-sensitive** (MiniCheck finds DeepSeek equivalent to both others there).
**Allowed:** "Both instruments place DeepSeek below Gemma and Qwen in mathematics and data-mining,
while the sociology result is instrument-sensitive."
**Prohibited:** "DeepSeek is a definitively weaker drafter."

> **Definitional correction (2026-09-02).** Model- and domain-agnosticism are **architectural**
> properties, not performance-equivalence claims. An earlier pass conflated them and withdrew the
> architectural claim when statistical equivalence failed to reproduce. Each is now split into three
> claims: architecture, portability, and performance. See
> `MODEL_AGNOSTICISM_CONSISTENCY_AUDIT.md` and `DOMAIN_AGNOSTICISM_IMPLEMENTATION_AUDIT.md`.

### `DRAFTER_ARCHITECTURE_AGNOSTIC` — the drafter is structurally replaceable
**Status:** `SUPPORTED`
**Basis:** implementation audit. All generation flows through one `ollama_generate(host, model, …)`
call; a grep for conditionals on model identity across `v3/pipeline/*.py` returns **nothing**; the
model arrives as a CLI argument with an environment default; the single capability accommodation
(`"think": False`) is applied unconditionally with the code comment recording that it is general
rather than model-specific. All three drafters emit the same output contract.
**Allowed:** "The drafting layer is model-agnostic by architecture: the drafter is replaceable behind
a common input/output contract, and no model-family-specific logic is required by the surrounding
KC-generation pipeline."
**Prohibited:** "any LLM will work" — only the named models were exercised.

### `DRAFTER_PORTABILITY_TESTED` — three model families ran the same contract
**Status:** `SUPPORTED_WITH_SCOPE`
**Scope:** Qwen3.8-27B, Gemma4-31B, DeepSeek-R1-32B.
**Result:** nine drafter × domain cells, 1,137 drafts, all parsed under one extraction contract with
no per-model handling.
**Allowed:** "The common drafting interface was exercised without architectural modification using
Qwen3.8-27B, Gemma4-31B, and DeepSeek-R1-32B."
**Limitation:** a model unable to honour the JSON output contract would fail; one did, historically,
until the uniform `think: False` accommodation was added.

### `DRAFTER_PERFORMANCE_EQUIVALENCE` — quality is invariant to drafter choice
**Status:** `NOT_ROBUST` / `SECONDARY` — **and not required by model-agnosticism**
**Result:** TOST at pre-registered δ=0.05 gives Qwen≡Gemma in all three domains under the primary
instrument but **1 of 3** under an independent entailment verifier; 5 of 9 comparisons agree.
**Allowed:** "Substituting the drafter can change output quality; architectural portability should
not be interpreted as performance invariance." And: "The ablation shows that model choice remains
consequential even in a model-agnostic architecture."
**Prohibited:** treating this result as evidence against the architectural claim.
**Note:** the analysis is retained and renamed **drafter performance-equivalence analysis**. Its
question is how sensitive KC draft quality is to drafter choice under fixed evidence — not whether
the pipeline is model-agnostic.

### `DOMAIN_ARCHITECTURE_AGNOSTIC` — subject matter enters through data, not code
**Status:** `SUPPORTED`
**Basis:** implementation audit plus artifact verification. A 2026-08-16 audit found ~66
data-mining-specific decisions per run; remediation D-1…D-7 completed 2026-08-17, AST-verified, with
exactly one subject-vocabulary string left in executable code (a docstring example). Verified against
the **evaluated** packets: zero semantic-misbinding drops, data-mining domain-specific drops down
from ~66 to 15, and the generic math-damage detector now firing in all three domains (1/2/7) with
mathematics highest.
**Allowed:** "The KC-generation architecture is domain-agnostic: the pipeline consumes a domain
corpus and curriculum representation as inputs, while retrieval, evidence construction, support
determination, drafting, provenance, and review operate through domain-independent contracts."
Key sentence: "Domain knowledge enters through the corpus and curriculum rather than through
domain-specific implementation logic."
**Prohibited:** "proven to work equally well in every domain".
**Residual:** `compound_sibling_ownership` fires 8× in data-mining and 0× elsewhere — a data-driven
asymmetry from curriculum shape, not hardcoding, but disclose it.

### `CROSS_DOMAIN_PORTABILITY_TESTED` — one architecture, three subjects
**Status:** `SUPPORTED_WITH_SCOPE`
**Scope:** Data Mining, Mathematics, Sociology; those corpora and curriculum structures.
**Allowed:** "The same architecture was exercised on Data Mining, Mathematics, and Sociology without
introducing domain-specific pipeline variants."
**Requires (not a contradiction):** a sufficiently informative corpus, a curriculum or hierarchy, a
convertible source representation, and a compatible drafting model.

### `CROSS_DOMAIN_PERFORMANCE_EQUIVALENCE` — quality is invariant to domain
**Status:** `NOT_SUPPORTED` / `SECONDARY` — **and not required by domain-agnosticism**
**Result:** data-mining and sociology fall within δ=0.05 for in-scope drafters under the primary
instrument; mathematics is consistently harder.
**Allowed:** "Performance varied by domain, with Mathematics more difficult under the measured
groundedness criterion." And: "The architecture transferred across all three tested domains, while
performance remained domain-sensitive."
**Prohibited:** treating the mathematics result as refuting architectural domain-agnosticism.
**Note:** renamed **cross-domain performance sensitivity analysis**.

### `VARIANCE_DECOMP` — drafter variance share
**Status:** `SECONDARY`
**Result:** Drafter facet explains 0.0–6.4% of groundedness variance across the two in-scope
drafters, 15.5–39.5% including DeepSeek. One observation per cell, so drafter × KC interaction is
confounded with error; G-coefficients 0.0–0.42.
**Allowed:** as a descriptive decomposition with the design limitation attached.

---

## C. Abstention and source boundaries

### `ABSTAIN_UNSUPPORTED` — refusal on corpus-unsupported KCs
**Status:** `PROVISIONAL_PENDING_SUPPORT_BOUNDARY_AUDIT`
**Result:** Under the adjudicated reference standard, Proposed abstained on **7/7** KCs labelled
corpus-unsupported; DOS-RAG drafted on **5/7**.
**Blocking dependency:** the seed-blind audit classified **all three** sampled unsupported KCs as
*supported*, so the support-boundary labels themselves are contested.
**Allowed:** "Under the adjudicated reference standard, Proposed abstained on all seven KCs
classified as corpus-unsupported, whereas DOS-RAG drafted on five. A subsequent seed-blind audit
classified all three unsupported KCs in its sample as supported, so the corpus-support boundary
requires further independent adjudication before this is treated as a robust safety result."
**Prohibited:** headlining as a settled safety advantage.
**Unblocked by:** `SUPPORT_BOUNDARY_REVALIDATION_PLAN.md`.

### `ABSTAIN_NO_EVIDENCE` — no drafting from empty evidence
**Status:** `SUPPORTED`
**Result:** 0 of 1113 rows produced a description from an empty evidence set, across all seven arms.
**Note:** a property of the harness contract, not of any single pipeline. Attribute it that way.

---

## D. Reference construction

### `SEED_AUDIT` — seed-blind reconstruction audit
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** n=27 comparable KCs; **0** material semantic differences, **0** cases of the seeded
reference asserting unsupported content; 18/27 equivalent-or-both-valid. No stratum effect in the
direction seed bias predicts (ACCEPT 13/18, CHANGED 5/9).
**Allowed:** "The seed-blind audit found no semantic distortion or unsupported assertions among
comparable substantive references, but exposed residual disagreement over the corpus-support
boundary."
**Prohibited:** "the seed issue was eliminated"; "the reference was proven unbiased"; "settled".
**Tested failure modes:** semantic distortion; unsupported assertion.
**NOT tested:** omission of source-supported content; content-selection/emphasis shaping;
provenance error. Support-boundary correctness was tested and **disagreed**.

### `SEED_NO_PARAPHRASE` — accepted references were not cosmetically rewritten
**Status:** `SUPPORTED` (methodological decision, documented)
**Statement:** Accepted seed-derived references were not paraphrased to manufacture surface
independence. Evaluation is semantic rather than lexical, so such rewriting would not address the
anchoring threat that matters — content selection — and post-hoc rewriting of only the
Qwen-identical references would itself be an intervention after results were known.

### `SEED_LEXICAL` — the judge matches meaning, not wording
**Status:** `SUPPORTED`
**Result:** DeepSeek scores 0.69 vital-nugget recall at 1.5% 8-gram overlap with the reference; 32 of
66 Gemma drafts with <5% overlap score 1.0. Within-arm overlap–recall correlation is +0.80 for the
seed arm but +0.11/+0.21 for the others — same judge, so judge-side lexical bias is excluded.
**Allowed:** as stated. This localises the residual seed asymmetry to the two Qwen-lineage arms'
completeness figures.

---

## E. Instrument and evaluation methodology

### `JUDGE_COMPLETENESS_CAL` — graded completeness calibration
**Status:** `SUPPORTED_WITH_SCOPE` — **development calibration, not external qualification**
**Result:** Under leave-one-out thresholding on the 36 available human-labelled development cases:
raw 0.8611, Gwet AC1 0.7224, PASS recall 0.8000, FAIL recall 0.9375; v1 binary equivalent 0.556.
**Allowed:** "The graded completeness score met the pre-registered agreement thresholds under
leave-one-out calibration on the available 36 human-labelled development cases. Because those labels
also contributed to development and adoption of the replacement metric, this is cross-validated
development calibration rather than independent external qualification."
**Prohibited:** "the judge is qualified"; "the qualification gate passes" without the scope sentence.

### `JUDGE_STATUS` — per-task validation status
**Status:** `SUPPORTED` (status record)
| task | status |
|---|---|
| binary completeness (v1) | `FAILED` |
| graded completeness (v2) | development-calibration thresholds met under LOO |
| M1 / M2 / TARGET / M4A | `INSUFFICIENT_VALIDATION_SUPPORT` — inadequate minority-class support |
**Prohibited:** collapsing `INSUFFICIENT_VALIDATION_SUPPORT` into either PASSED or FAILED; using a
single blanket judge status.

### `SECOND_INSTRUMENT` — independent entailment verifier was run
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** MiniCheck-Flan-T5-Large over 7,747 matched ablation and 7,914 matched crossed claims.
**Required framing:** "an independent entailment verifier run as an instrument-sensitivity analysis";
it measures reliability and construct sensitivity, **not** human validity.
**Prohibited:** "MiniCheck proves Selene wrong" (or the reverse); "second judge not run" (stale).

### `RERUN_CONTROL` — evaluation-stage rerun baseline
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** 0.9983 per-claim agreement over **7,610 matched claims from 996 drafts**; 15 drafts
excluded where re-decomposition produced a different claim count; support-rate drift −0.0001; max
arm drift 0.0027; ordering ρ +0.9643.
**Scope, mandatory:** covers **claim decomposition and judging only** — not retrieval, not drafting,
not regeneration of the KC library.
**Allowed:** "A full rerun of the claim-decomposition and judging stages reproduced 99.83% of matched
per-claim decisions."
**Prohibited:** "the pipeline reproduces itself at 99.83%"; any end-to-end reproducibility reading.

### `SERIAL_POSITION` — position sensitivity under long passage sets
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Recovery of provably-present reference content: 1.0000 at 17 passages, 0.9934 at 33,
**0.5905** at 123; within the 123-passage condition recall falls from 1.0000 (positions 0–33) to
0.20–0.40 beyond position 59. Truncation excluded (last decile 0.3125; 40,960-token limit against
~25k-token prompts).
**Allowed:** "Selene-based reference-content recovery in our evaluation configuration exhibited
severe serial-position sensitivity as the passage set grew."
**Prohibited:** "LLM judges are serial-position sensitive" as a universal.

### `PADDING_SIGN_FLIP` — the same manipulation moves two metrics oppositely
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Padding to 123 passages depresses context recall (−0.4095) but *inflates* per-claim
faithfulness (+0.0175, n=143, McNemar p=0.00082).
**Allowed:** as an empirical property of this instrument and configuration.

### `BATCH_INVARIANCE` — serving configuration affects judge reproducibility
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Default concurrent serving changed 1 verdict in 144 at temperature 0; batch-invariant
kernels changed 0 of 144.
**Allowed:** "In our Selene/vLLM configuration, concurrent serving changed a judgment despite
temperature-zero decoding, while batch-invariant kernels eliminated the observed discrepancy."
**Prohibited:** "batch-invariant serving is required for reproducible LLM judging" as a universal.

### `AGGREGATION_ARTIFACT` — all-or-nothing aggregation
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Observed all-or-nothing rates track p^n closely (mathematics: predicted 0.5017, observed
0.5231; sociology 0.7292 vs 0.8176), reproducing out-of-domain.
**Allowed:** "the observed all-or-nothing rate closely tracked an independent-claim p^n pattern".
**Prohibited:** asserting claim independence as a model of the data — errors are positive in both
domains, which is what correlated claims predict.

### `GRADED_VS_BINARY` — graded rubrics can rescue a failing judge
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** Same judge, same 36 labels: 0.556 as a binary verdict, 0.8611 graded with LOO threshold.
**Allowed:** "For completeness in this evaluation, retaining graded information substantially
improved agreement with available human judgments compared with an all-or-nothing binary verdict."
**Prohibited:** universalising to all judges and rubrics.

### `TRIAGE_FAILED` — automated editorial triage
**Status:** `NEGATIVE_RESULT`
**Result:** 97.2–99.3% of every arm placed in the top two categories; `UNUSABLE` never used across
1113 drafts; exact agreement with expert codes 0.462 (0.952 within one level).
**Allowed:** report as a construct failure. **Do not use as a quality metric.**

### `REVIEW_BURDEN` — human editing burden
**Status:** `SUPPORTED_WITH_SCOPE`
**Result:** ACCEPT 117, MINOR_EDIT 10, MAJOR_EDIT 15, REPLACE 10, corpus-gap 7 → 127/159 = 79.9%.
**Allowed:** "Approximately four in five seed drafts required no more than local human editing under
the adjudicated reference-construction process."
**Prohibited:** presenting this as cross-model accuracy or as an evaluation result — it is a property
of the seed arm under the construction workflow. Corpus-gap count inherits
`ABSTAIN_UNSUPPORTED`'s pending status.

---

## F. Superseded and withdrawn (retained in history)

| id | claim | status | replaced by |
|---|---|---|---|
| `CTX_RECALL` | context recall as a cross-arm retrieval metric | `SUPERSEDED` | pooled IR metrics — no rank cutoff, and confounded by `SERIAL_POSITION` |
| `M4A_PRIMARY` | M4A retrieval-reference-recall as primary retrieval diagnostic | `SUPERSEDED` | pooled IR metrics; M4A has zero human labels |
| `M1_BINARY` | all-or-nothing faithfulness as a quality ranking | `SUPERSEDED` | per-claim groundedness |
| `M3_HOLISTIC` | holistic completeness verdict | `SUPERSEDED` | graded vital-nugget recall |
| `RET_EFFICIENCY_OLD` | "BaseDense retrieves 7.2× more yet recovers less" (context-recall version) | `WITHDRAWN` | restated as `RET_PROP_VS_BASE` on pooled metrics |
| `PROP_BEATS_DOS` | "Proposed retrieves better than DOS-RAG" | `WITHDRAWN` | split into `RET_DOS_NDCG`, `RET_DOS_TOP10`, `RET_DOS_DEEP` |
| `SEED_SETTLED` | "the seed question is settled" | `WITHDRAWN` | `SEED_AUDIT` with residual boundary risk |
| `MODEL_AGNOSTIC` (as a performance claim) | "drafters perform equivalently" | `WITHDRAWN` | `DRAFTER_PERFORMANCE_EQUIVALENCE`. **The architectural claim was never withdrawn and is now `DRAFTER_ARCHITECTURE_AGNOSTIC`.** |
