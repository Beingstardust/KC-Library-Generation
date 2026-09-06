# Improving absolute qualification, and selecting a second judge

**Status: one result already established (§1), the rest is a costed plan. Nothing in §2–§4 has run.**

---

## 1. The qualification failure was largely a metric artifact — RESULT, already computed

`JUDGE_QUALIFIED=false` came from the v1 gate. Re-reading the per-task decisions shows only **one**
task actually failed; the other three returned `INSUFFICIENT_VALIDATION_SUPPORT`, which is a
**sample-size** verdict, not a disagreement verdict:

| task | n | raw | AC1 | decision | why |
|---|---|---|---|---|---|
| M3_CORE_COMPLETENESS | 36 | 0.556 | 0.392 | **NOT_QUALIFIED** | genuine disagreement |
| M1_EVIDENCE_FAITHFULNESS | 30 | 0.633 | 0.354 | INSUFFICIENT | only 6 minority-class rows |
| M2_REFERENCE_SOURCE_CORRECTNESS | 30 | 0.667 | 0.538 | INSUFFICIENT | only 8 minority-class rows |
| TARGET_ALIGNMENT | 32 | **0.906** | **0.884** | INSUFFICIENT | only 5 minority-class rows |
| M4A_RETRIEVAL_CLAIM_SUPPORT | 0 | — | — | INSUFFICIENT | no labels at all |

TARGET already agrees at 0.906 / AC1 0.884 — it is blocked purely by minority-class count.

### The finding: M3 fails as a *binary holistic verdict* and passes as a *graded score*

M3 was a binary `CORE_COMPLETE` / `MATERIAL_OMISSION` judgement. v2 replaced it with graded
vital-nugget recall, which scores AUC **0.8578** against the same human labels (v1 holistic: 0.700).
**The qualification gate was never re-run on the replacement metric.** Doing so, with the decision
threshold chosen **leave-one-out** so it never sees the row it predicts:

| gate | threshold | v1 holistic M3 | **v2 nugget recall (LOO)** |
|---|---|---|---|
| raw agreement | ≥ 0.80 | 0.556 ✗ | **0.8611 ✓** |
| Gwet AC1 | ≥ 0.65 | 0.392 ✗ | **0.7224 ✓** |
| PASS recall | ≥ 0.75 | 0.400 ✗ | **0.8000 ✓** |
| FAIL recall | ≥ 0.75 | 1.000 ✓ | **0.9375 ✓** |

Confusion under LOO: TP 16, TN 15, FP 1, FN 4.

**All four gates pass.** The completeness judge is not miscalibrated; the *binary rubric* was
discarding the information. This costs nothing to claim — no new annotation, no new inference.

**What it does and does not establish.** It establishes agreement with *this annotator's* labels on
36 rows at a cross-validated threshold. It does **not** establish absolute validity: same single
annotator, same 36 rows, and the threshold family was chosen after nugget recall was known to work
(though the AUC comparison itself was pre-registered as the adoption test). The honest statement is
**"qualified on completeness against the available human labels"**, not "qualified".

---

## 2. What would move the other three tasks — costed

M1, M2 and TARGET need **≥10 minority-class examples** each. Current counts: M1 has 6 FAIL, M2 has 8,
TARGET has 5. So the shortfall is **4, 2 and 5** rows respectively — small.

The 180-row calibration workbook exists and 144 rows are unannotated, but **judge predictions exist
only for the same 36 rows**, so stratified sampling is not yet possible.

**Procedure, in order:**

1. **Predict the remaining 144 rows** with the frozen judge. ~1–2 h GPU, no human time.
2. **Stratified sample** for annotation, oversampling rows the judge predicts FAIL. The judge
   over-flags (false-fail 0.375–0.60), so its FAIL predictions are *enriched* for true minority
   cases — this is what makes the sample efficient rather than needing ~20 random rows per task.
3. **Annotate ~25–35 targeted rows.** At the observed rates this should clear the ≥10 threshold on
   all three tasks simultaneously, since one row carries labels for every task.
4. **Reweight by the sampling probability** when computing agreement. Stratified sampling without
   reweighting would bias the estimate — this step is not optional.

M4A cannot be rescued cheaply: it has zero labels because reference-claim decomposition does not
exist for the calibration KCs. Recommend reporting it as unvalidated rather than annotating it.

---

## 3. Second judge — selection, with the reasoning

### The constraint that rules out most candidates

The point of a second judge is to test whether conclusions are **judge-dependent**. Two judges that
share a base family also share failure modes, so their agreement is inflated and the check is
uninformative. Two exclusion rules follow:

- **Not Llama-family.** Selene-1 is Llama-3.3-70B, and Llama-family judges carry a documented
  verbosity bias (+0.24 to +0.44 on expansion pairs, `R-07`) which we measured in our own instrument
  (`F-35`). A second Llama judge would reproduce that bias, not test it.
  → rules out **Skywork-Critic**, **Self-taught-evaluator**, **RootSignals-Judge-Llama-70B**
  (the one the protocol addendum named — and which, checked today, is **not actually present on
  Cluster A**; only Selene is).
- **Not a drafter family.** LLM judges favour their own generations, driven by self-recognition
  ([Panickssery et al., NeurIPS 2024]; bias spans −38% to +90% on ArenaHard). Our drafters are
  Qwen3.8, Gemma4 and DeepSeek-R1.
  → rules out **CompassJudger** and **M-Prometheus** (Qwen-based).

Note this also retrospectively validates the *current* choice: Selene is Llama-family and no drafter
is, so there is no self-preference conflict in the primary instrument.

### Task shape rules out the generic rubric judges

**Prometheus-2** (Mistral-7B / 8x7B) clears both family rules and would fit the hardware comfortably
(~94 GB for the 8x7B MoE on 4×H100). But it is trained for **rubric-based direct assessment** —
"score 1–5 with feedback" — not per-claim entailment. Our surviving conclusions rest on
**groundedness**, which is a claim-vs-evidence support decision. Forcing Prometheus into our JSON
schema would run it off-distribution, and a disagreement would then be uninterpretable: instrument
difference or task mismatch?

### Recommendation: MiniCheck-Flan-T5-Large

A **purpose-built grounded-factuality verifier**, not a generic judge.

| property | value | why it matters |
|---|---|---|
| base | **Flan-T5-Large, 770M** | Encoder–decoder. Architecturally independent of *every* model in this study — no shared lineage with Llama, Qwen, Gemma or DeepSeek |
| task | `(document, claim) → supported ∈ {0,1}` + probability | **Exactly** our groundedness task; no schema coercion needed |
| benchmark | 74.7% balanced accuracy on LLM-AggreFact | Matches Claude-3 Opus (74.1%), approaches GPT-4 (75.3%) |
| hardware | runs on a single A40 | ant7/ant8 have A40s — leaves the H100 node free |
| licence | permissive (Flan-T5 line) | no restriction for thesis use |

The README explicitly recommends splitting multi-sentence claims into sentences — which our pipeline
already does, since claim decomposition is stage one of groundedness.

**Optional stronger variant: Bespoke-MiniCheck-7B**, currently SOTA on LLM-AggreFact at 77.4%,
beating Claude-3.5-Sonnet. Two cautions: its base model is **not stated** in the public README, so
family independence cannot be asserted without checking, and it is **CC BY-NC 4.0** — fine for a
thesis, but it must not be described as a reusable component of a deployable system. Use it as a
secondary confirmation only if the base is verified independent.

### Why a 770M model is a legitimate second judge

For a **reliability** check what matters is independence and task validity, not parameter count. This
model is independent in architecture, training objective and data, and is benchmarked at
Claude-3-Opus level *on this exact task*. A 70B Llama judge would be larger and less informative.

---

## 4. Costed plan

| step | cost | blocks |
|---|---|---|
| Re-run claim decomposition **storing claim texts** (they were not stored) | ~2 h GPU, 2250 calls | second-judge check |
| Download MiniCheck-Flan-T5-Large | minutes, <5 GB | — |
| Run MiniCheck over ~20k claim–evidence pairs | ~40 min on one A40 | — |
| Agreement analysis: Selene vs MiniCheck per claim, and arm-ranking stability | none | — |
| Judge predictions on 144 workbook rows | ~1–2 h GPU | stratified annotation |
| Targeted annotation of ~25–35 rows | **human time** | M1/M2/TARGET qualification |

### What each buys

- **MiniCheck agreement** tests whether the groundedness conclusions — which are what currently
  survive — depend on the judge. If the arm ordering reproduces under an independent verifier, that
  is the strongest reliability evidence available to this project.
- **Targeted annotation** converts three `INSUFFICIENT` verdicts into real decisions, and TARGET is
  already at 0.906 agreement so it would likely qualify outright.

### Stated in advance

Inter-judge agreement measures **reliability, not validity** — two judges can agree and both be
wrong (`R-08`). It is reported alongside, never instead of, the human-anchored qualification. And it
cannot rehabilitate an absolute claim: the §1 result is the one that speaks to validity, and it is
bounded by 36 single-annotator labels.
