# M4 Scope Decision: Retain Decomposed Retrieval Recall, Demote Holistic Evidence Adequacy

**Date:** 2026-08-25
**Status:** Methodological correction to the measurement instrument, made **before** locked human qualification and **before** any system ranking was run or inspected.
**Machine-readable record:** `reference_eval/locks/EVALUATION_SCOPE_AMENDMENT_v2.json`

## The decision

M4 previously bundled two different questions into one construct. They are now separated, and only one survives as a primary metric.

| | Question | Status |
|---|---|---|
| **M4A** reference-claim retrieval recall | *Was this specific reference claim available in the retrieved evidence?* | **RETAINED — primary retrieval diagnostic** |
| **M4B** holistic evidence adequacy | *Was the evidence collectively enough to construct an adequate KC?* | **DEMOTED — exploratory only** |

## Why M4B was demoted

### What was measured

On the development sentinel suite, the holistic classifier marked **18 of 25 judgeable `EVIDENCE_ADEQUATE` cases as `MATERIAL_EVIDENCE_GAP`** — 28.0% agreement. Critically, FAIL-recall was 100% and false-PASS was 0. The classifier is not permissive or noisy; it is **systematically over-strict in one direction**.

### The mechanism, established by reading the outputs

The items the judge enumerated as "missing evidence" are phrases drawn from the **expert reference itself**, not genuinely defining content. For a K-Means case it listed as missing:

- *"the algorithm is simple and is guaranteed to converge"*
- *"random initialization is often used"*

Neither is required to draft an adequate K-Means KC. They are reference enrichment. The judge was treating the full expert reference as a mandatory checklist — despite the prompt explicitly instructing that *"the evidence does NOT need to contain everything in the reference description"* and listing missing examples and optional detail as non-qualifying.

### Why this is a construct problem, not a prompting problem

This is the **third** independent observation of the same failure shape in this project:

1. **v3 F4** (core completeness against an authority-derived requirements ledger): all-requirements-must-be-correct aggregation drove false-passes to zero while wrongly failing 14 of 34 correct cases.
2. **v3 F5** (evidence sufficiency, same design): wrongly failed 16 of 36.
3. **M4B here**: wrongly failed 18 of 25.

The v3 pattern reproduced across **two independently trained 70B judges** (Selene and RootSignals), with every single F4/F5 mismatch on both models in the same over-strict direction. The failure survives rewording and model substitution.

The common structure is: *hand a judge a complete reference or requirement list, then ask a holistic sufficiency question.* The holistic question is a counterfactual — "would this have been enough?" — and supplying the reference as the standard reliably collapses it into "does this contain everything in the reference?".

That is a **construct-validity failure**: the task does not measure what it was designed to measure. It is not addressable by tuning, and per the campaign protocol it was not tuned.

### What was deliberately not done

- No prompt tuning to rescue the task.
- No alternative holistic evidence-sufficiency wording.
- No further model substitution for this construct.
- No deletion of prior development output — run 3 is preserved as `selene_reference_sentinel_raw.PRE_FIELDORDER_FIX.json`.

## Why M4A is retained

M4A asks a **concrete, decomposed, checkable** question, one reference claim at a time: *is there source support for this claim in the evidence the drafter received?* There is no counterfactual and no implicit standard of sufficiency — only presence or absence of support for a specific proposition. This is the RAGChecker-style claim-recall formulation (Ru et al. 2024), and it is continuous and interpretable.

```
retrieval_reference_recall = reference claims supported by candidate evidence
                             ────────────────────────────────────────────────
                                    total substantive reference claims
```

**A value below 1.0 must not be read as "insufficient evidence."** A concise evidence set can omit reference detail and still support an adequate draft. That inference — from incomplete coverage to inadequacy — is exactly the error that sank M4B, and it must not be reintroduced at the interpretation stage after being removed at the measurement stage.

## Terminology

Use: **reference-claim retrieval recall**, **retrieval coverage**, **reference-content coverage by retrieval**.

Do **not** call it *evidence sufficiency* except when discussing the concept descriptively.

## Enforcement in code

`reference_judge_schema.METRIC_SCOPE` carries the scope of every task, and `assert_primary()` raises if a demoted task is consumed on a production path:

```
EXPLORATORY_HOLISTIC_EVIDENCE_ADEQUACY:
    primary_use               = False
    qualification_gate        = False
    derived_metric_dependency = False
```

`materially_sound` was verified programmatically to reference **neither** M4 output:

```
materially_sound = draft_exists
                   AND target_aligned
                   AND faithfulness_precision == 1.0
                   AND authority_correctness_precision == 1.0
                   AND core_complete
```

Retrieval coverage is an **upstream explanatory** metric. `materially_sound` measures the final KC draft; retrieval coverage helps explain that outcome rather than defining it. Keeping them separate is what makes the extrinsic failure decomposition possible:

- low retrieval recall + incomplete draft → retrieval-side failure
- high retrieval recall + incomplete draft → drafting/utilization failure
- high retrieval recall + unsupported claims → generation faithfulness failure
- evidence supports a related concept + wrong-target draft → target-binding failure

Collapsing these into one weighted score would destroy exactly the diagnostic this design exists to provide.

## Scientific note

M4B is retained in the record as **useful negative-method evidence**, not hidden. That a plausible, carefully worded holistic sufficiency classifier reproducibly fails this way — across two model families and three task designs — is a finding about LLM-as-judge evaluation design worth reporting.

The decision was not made because M4B made any system look worse. No system ranking has been computed or inspected. It was made because the development sentinels exist precisely to detect whether the evaluator measures the intended construct, and here they showed it does not.
