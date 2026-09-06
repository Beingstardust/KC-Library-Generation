# Threats to validity — master

Consolidates every threat identified across the campaign. Supersedes the scattered threat sections in
`paper_methods/THREATS_TO_VALIDITY.md`, `EVALUATION_FINDINGS.md`, and the individual protocol
documents, which remain as history.

Each threat records what was **observed**, what **mitigation** was applied, what **residual** risk
remains, and — the operative column — **which claims it constrains**.

---

## A. Construct validity

### A1. Pooled relevance labels are automated
**Observed.** All 8,246 passage-level relevance judgements were produced by the frozen Selene judge.
No human has validated any of them.
**Mitigation.** Per-passage judging (so the serial-position failure cannot occur); graded 3-level
scale; pooling across four distinct retrieval configurations so no single system defines the labels.
**Residual.** The entire retrieval comparison inherits evaluator-validity risk. Bootstrapping
quantifies sampling variability, not label correctness.
**Constrains.** `RET_PROP_VS_BASE`, `RET_DOS_NDCG`, `RET_DOS_TOP10`, `RET_DOS_DEEP`. Every retrieval
sentence must carry "under automated pooled relevance judgements". **Unblocked by P2.**

### A2. Nugget decomposition and VITAL assignment are unaudited
**Observed.** 1,185 nuggets, 475 VITAL, produced automatically from the reference. No human audit
exists.
**Mitigation.** Decomposition is arm-independent and shared across all arms, so it cannot advantage
one arm; the downstream coverage step was validated against 36 human labels.
**Residual.** An error in the yardstick itself is invisible to any downstream agreement statistic.
Formula-bearing references are the known weak point — the one structural failure was formula-driven,
and mathematics is the weakest measured domain.
**Constrains.** All completeness figures. **Unblocked by P3.**

### A3. Two instruments operationalise "grounded" differently
**Observed.** Selene applies the project's support rubric; MiniCheck applies strict document-claim
entailment. Support rates 0.9428 vs 0.7200 on identical claims; arm-ordering ρ = +0.4286.
**Mitigation.** Both scored byte-identical claims and evidence, with zero length mismatches, so the
difference is not a claim-set artifact. A same-instrument rerun control (A-E5) bounds the noise.
**Residual.** Neither is ground truth. The disagreement is a genuine construct difference and cannot
be resolved by either instrument.
**Constrains.** `GND_INSTRUMENT`, `MODEL_AGNOSTIC`. Report orderings and endpoints, not magnitudes.

### A4. Completeness inherits the seed's content selection
**Observed.** Nuggets are extracted from a reference seeded from Qwen; 117/159 accepted unchanged.
Within-arm overlap–recall correlation is +0.80 for the seed arm against +0.11/+0.21 for others.
**Mitigation.** Semantic rather than lexical evaluation (established empirically: DeepSeek scores
0.69 recall at 1.5% lexical overlap); seed-blind reconstruction audit; explicit provenance.
**Residual.** The audit tested distortion and unsupported assertion. It did **not** test whether the
seed shaped *which* content counts as essential. That asymmetry attaches specifically to the two
Qwen-lineage arms' completeness figures.
**Constrains.** Completeness comparisons involving `intrinsic_P-Q` and `extrinsic_P-Q`. Gemma-vs-
DeepSeek completeness carries no seed asymmetry.

### A5. Editorial triage does not measure what it names
**Observed.** 97.2–99.3% of every arm placed in the top two categories; `UNUSABLE` never used;
exact agreement with expert codes 0.462.
**Mitigation.** Validated against real human codes, which is how the failure was detected.
**Residual.** None — the metric is withdrawn from use.
**Constrains.** `TRIAGE_FAILED` is reported as a negative result only.

---

## B. Internal validity

### B1. The reference is machine-seeded
**Observed.** Seed arm identified by exact string comparison as `intrinsic_P-Q`, 159/159 match; next
closest arm 17/159. 8-gram overlap 0.807 for the seed arm against ≤0.089 for non-Qwen arms.
**Mitigation.** Six anti-anchoring controls, of which the decisive one — seed-blind reconstruction —
was executed: 0 distortion, 0 unsupported assertion across 27 comparable KCs, and no stratum effect
in the direction seed bias predicts.
**Residual.** Content-selection shaping and support-boundary correctness remain live. Accepted
references were deliberately **not** paraphrased; see the methodological note in the reference
construction document.
**Constrains.** `SEED_AUDIT` may not be phrased as elimination or proof.

### B2. The corpus-support boundary is contested
**Observed.** Seven KCs adjudicated corpus-unsupported. The seed-blind reviewer classified all three
sampled as *supported*.
**Mitigation.** None yet.
**Residual.** The abstention comparison measures a boundary that two reviewers disagree about.
**Constrains.** `ABSTAIN_UNSUPPORTED` is `PROVISIONAL`. **Unblocked by P1.**

### B3. Pool incompleteness
**Observed.** The pool is the union of **top-20** from seven arms spanning four distinct retrieval
configurations. Relevant passages ranked below 20 by every configuration are unjudged.
**Mitigation.** Four diverse configurations contribute, including one that natively returns 123
passages per KC. The four Proposed-lineage arms contribute zero passages unique to them, so the pool
cannot be characterised as Proposed's own output.
**Residual.** Standard pool bias. Unjudged passages count as non-relevant.
**Constrains.** All retrieval recall figures are recall-at-pool, not absolute recall. Note the pool
uses BaseDense's **top 20**, not its 123 — an earlier framing that overstated pool coverage.

### B4. Frozen candidates and paired design
**Observed.** Drafts and evidence generated once and frozen; every comparison paired within KC.
**Mitigation.** Pairing removes KC difficulty and any constant judge offset. All seven arms score an
identical 151-KC set (verified, not assumed).
**Residual.** Run-to-run variance of the *generation* pipeline is not captured at all. A single
frozen sample per configuration.
**Constrains.** No claim about generation stability may be made.

### B5. Non-random reference coverage
**Observed.** 151 of 159 KCs scored. Seven lack a reference entirely; four of those seven are exactly
the KCs where Proposed retrieved zero evidence.
**Mitigation.** All eight drop identically for every arm, so paired comparisons stay balanced.
**Residual.** Absolute reference-based figures are plausibly flattered for Proposed.
**Constrains.** Absolute completeness values; relative paired comparisons are unaffected.

---

## C. Measurement validity

### C1. Judge validation is criterion-specific and incomplete
**Observed.** Binary completeness FAILED. Graded completeness met the gates under leave-one-out
calibration (0.8611 / 0.7224 / 0.8000 / 0.9375). M1, M2, TARGET, M4A returned
`INSUFFICIENT_VALIDATION_SUPPORT` — a sample-size verdict, not a disagreement verdict.
**Mitigation.** Pre-registered gates; Gwet AC1 as primary with kappa recorded secondary (the label
distribution is skewed enough to trigger the kappa paradox — κ = 0.074 at 94% prevalence).
**Residual.** The 36 labels also informed adoption of the graded metric, so this is **development
calibration, not independent external qualification**. M1/M2/TARGET need roughly 4, 2 and 5 more
minority-class rows; M4A has zero labels.
**Constrains.** `JUDGE_COMPLETENESS_CAL`, `JUDGE_STATUS`. Never use a single blanket judge status.

### C2. Small, single-annotator calibration set
**Observed.** 36 labels from one annotator, clustered in 17 KCs; the annotator cross-checked their
own work against other tools. Human–human agreement is not computable.
**Mitigation.** Disclosed; the provenance record is preserved.
**Residual.** Roughly a quarter of the ~150 samples treated as a calibration minimum in comparable
frameworks.
**Constrains.** Everything resting on those labels, including `JUDGE_COMPLETENESS_CAL`.

### C3. Serial-position sensitivity
**Observed.** Recovery of provably-present content falls 1.0000 → 0.9934 → 0.5905 at 17 / 33 / 123
passages; within the 123 condition, 1.0000 for positions 0–33 against 0.20–0.40 beyond 59.
Truncation excluded on two independent grounds.
**Mitigation.** Retrieval re-built on per-passage pooled judging, where the failure cannot occur.
**Residual.** Any metric read off a long passage set remains affected. This is what invalidated the
original context-recall metric.
**Constrains.** `SERIAL_POSITION` is scoped to this model and configuration.

### C4. Evidence-length and verbosity effects
**Observed.** MiniCheck score correlates +0.261 with document words (only +0.053 with passage count);
DOS-RAG retrieves 2,212 words/KC against Proposed's 914. Separately, the Llama-family judge rewards
verbosity, and length adjustment shifts completeness by up to +0.105.
**Mitigation.** Direct standardisation reported alongside raw completeness; the length driver
identified by measurement rather than assumed.
**Residual.** Cross-arm groundedness comparisons remain sensitive to evidence length under strict
entailment.
**Constrains.** `GND_INSTRUMENT`, `DRAFT_ORDER`.

### C5. Constrained-decoding failure history
**Observed.** Verdict-field ordering made one branch unreachable (0/36); a required trailing
free-text field caused token-cap stalls; `if/then/else` compiled and was silently dropped.
**Mitigation.** All three fixed and verified at the EBNF level; schema and prompt hashes frozen.
**Residual.** Historical results produced before the fixes are superseded, not merged.
**Constrains.** Nothing current, but explains why v1 results are not comparable.

---

## D. External validity

### D1. Single reference domain
**Observed.** The expert reference library exists only for data-mining, covering 152/159 KCs.
**Residual.** Reference-based metrics are **undefined**, not merely unmeasured, in mathematics and
sociology.
**Constrains.** Cross-domain claims rest on groundedness alone, which needs no reference.

### D2. Mathematics is measurably harder
**Observed.** Consistently the weakest domain under groundedness; falls outside δ=0.05 for every
drafter; the one structural decomposition failure was formula-bearing.
**Residual.** Formula-heavy content is plausibly a systematic weak point for both the pipeline and
the measurement apparatus.
**Constrains.** `DOMAIN_TRANSFER` — partial transfer only.

### D3. Single course corpus
**Observed.** Four source documents, 100,218 sentences, one curriculum.
**Residual.** Corpus characteristics — density, redundancy, formula load — are not varied.
**Constrains.** No claim of generality beyond curriculum-style corpora.

---

## E. Reproducibility

### E1. Batch invariance is off
**Observed.** Concurrent serving changed 1 verdict in 144 at temperature 0; batch-invariant kernels
changed 0 of 144. The production server ran **without** batch invariance.
**Mitigation.** All stages ran strictly sequentially.
**Residual.** 1.5% of drafts re-decompose to a different claim count across runs.
**Constrains.** `BATCH_INVARIANCE` is scoped to this configuration.

### E2. Claim decomposition is not bit-reproducible
**Observed.** 15 of 1,011 drafts (1.5%) produced a different claim count on re-extraction.
**Mitigation.** Claim texts are now stored, so future comparisons need not re-derive them; affected
drafts are excluded and counted rather than silently misaligned.
**Residual.** The 99.83% agreement figure has a denominator of 7,610 matched claims from 996 drafts,
excluding those 15.
**Constrains.** `RERUN_CONTROL` must state its denominator.

### E3. Rerun drift is small at aggregate level
**Observed.** 0.9983 per-claim agreement; support-rate drift −0.0001; max arm drift 0.0027; ordering
ρ +0.9643.
**Residual.** Covers claim decomposition and judging **only** — not retrieval, not drafting, not
regeneration of the library.
**Constrains.** `RERUN_CONTROL`. Never describe as end-to-end pipeline reproducibility.

---

## Threat-to-claim index

| Threat | Claims constrained | Unblocked by |
|---|---|---|
| A1 automated qrels | all four retrieval claims | **P2** |
| A2 unaudited nuggets | all completeness figures | **P3** |
| B2 contested boundary | `ABSTAIN_UNSUPPORTED` | **P1** |
| A3 construct difference | `GND_INSTRUMENT`, `MODEL_AGNOSTIC` | not resolvable by more judging |
| A4 / B1 seed provenance | Qwen-lineage completeness | partially addressed by the executed audit |
| C1 / C2 judge validation | `JUDGE_COMPLETENESS_CAL` | more labelled minority-class rows |
| E3 rerun scope | `RERUN_CONTROL` | n/a — scope statement only |
