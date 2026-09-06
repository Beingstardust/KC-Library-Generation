# Human Annotation Summary

**Date:** 2026-08-25
**Annotation status: NOT STARTED — 0 of 180 rows annotated.**

---

## State

| | |
|---|---|
| Calibration rows | 180 (30 KCs × 6 arms) |
| Rows with any human label | **0** |
| Total human labels across all tasks | **0** |
| Annotators assigned | none recorded |
| Human–human agreement | **cannot be computed** |
| Selene–human qualification | **cannot be computed** |
| `JUDGE_QUALIFIED` | **false** |

No human has annotated any row. This is a statement of fact, not a processing delay: the label fields are empty across all 180 rows and all eight annotation fields.

**No labels were imputed, defaulted, simulated, or inferred**, and none will be. A qualification decision computed from fabricated labels would be worse than no decision, because it would look like validation while being none.

## What was blocking annotation, and is now fixed

The workbook could not have been annotated before today regardless of annotator availability: `candidate_draft` and `candidate_system_evidence` were still `<<POPULATED_AT_MATERIALIZATION_FROM_FROZEN_ARM>>` placeholders. There was nothing for a human to judge.

The workbook has now been **materialized** from the frozen candidate arms and is annotation-ready.

## Annotation target

```
evaluation_suite/final_pipeline/reference_eval/output/human_calibration/
    reference_human_calibration_workbook_v2_MATERIALIZED.jsonl
```

- 180 rows · 30 KCs · 6 arms · 30 rows per arm · seed 20260825
- sha256 `dae62772e96d36b2…`
- Sample verified **unchanged**: row identities, KC set, arm assignment, presentation order, seed and stratification are byte-identical to the pre-materialization workbook on every sample field.
- The unmaterialized workbook is retained unmodified.

Each row now carries: KC id and canonical name, hierarchy path, the expert reference, resolved source citations (document / page / section / sentence id), the candidate draft, and the candidate's system evidence under opaque `SRC_*` ids.

**4 of 180 rows have an empty candidate draft.** These are genuine abstentions by those systems and are presented as such — how a system behaves when it declines to draft is part of what is being evaluated, so they are not filtered out.

## Blinding verified

A full sweep over all 180 materialized rows found **zero** violations of the forbidden-pattern set. Specifically absent from the workbook:

- system, drafter and retrieval-architecture names (Proposed / Base / DOS, Qwen / Gemma / DeepSeek)
- the reference's Qwen seed origin
- native evidence ids (which encode the retrieval lane) — replaced with opaque `SRC_*`
- the draft's self-reported `grounded` / `partial` / `abstained` status — deliberately dropped as a machine-status signal
- any Selene judgment or sentinel result

Arm identity exists **only** in `reference_human_calibration_blinded_mapping.jsonl`, and is restored only after human labels and judge predictions are frozen, for the post-hoc bias audit.

KC identity is intentionally visible: the annotator must know which knowledge component they are assessing.

## Tasks to annotate

**Primary (qualification-gating):**

| Task | Question |
|---|---|
| M1 faithfulness | is each candidate claim supported by the evidence that drafter received? |
| M2 correctness | is each claim correct per the expert reference **or** the source authority? |
| M3 core completeness | does the draft retain the defining content? (`CORE_COMPLETE` / `MATERIAL_OMISSION`) |
| TARGET alignment | is the draft centrally about the same KC as the reference? |
| M4A retrieval claim support | per reference claim: is it supported in the candidate's evidence? |

**Exploratory, non-gating:** M4B holistic evidence adequacy — optional, marked `EXPLORATORY_NON_PRIMARY`, and excluded from qualification.

**Seed-bias audit fields (every row):** `VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE` and `POSSIBLE_REFERENCE_DEFECT`, answered against the source authority and never against candidate identity.

## Required annotation design

- **Two independent annotators** are needed on at least a subset, otherwise human–human agreement cannot be computed at all and every construct's reproducibility is unknown.
- Disagreements must be **adjudicated before** judge qualification, by an adjudicator blind to Selene's prediction. Record annotator A, annotator B, adjudicated label, and rationale.
- Human–human agreement is computed **first**. If it is poor on a task, that construct is flagged as insufficiently reproducible — Selene is not blamed first.

## What happens after annotation

1. Human–human agreement computed and reported.
2. Human gold frozen (agreed labels; adjudicated labels where they disagreed).
3. Frozen Selene run on the same 180 rows; predictions completed and **hashed before** any agreement statistic is computed.
4. Qualification evaluated against the already-frozen thresholds.
5. Arm identities restored for the seed-bias and differential-error audits only.

`run_judge_qualification.py` implements this order and **refuses to run** without real labels — verified: it rejects a missing annotation file and rejects a file whose label fields are all empty, rather than reporting a vacuous pass.

## Small-denominator warning, stated in advance

With 180 rows and heavily imbalanced label distributions, some gates may rest on very few examples of one class. The protocol requires flagging `SMALL_DENOMINATOR` below 10 examples in a class and reporting exact numerators, denominators and Wilson intervals; where prevalence is too extreme to test a gate meaningfully, the task is reported `INSUFFICIENT_VALIDATION_SUPPORT` rather than manufacturing confidence. Resampling is **not** automatic — that decision is the project owner's.

---

## Deliverables that cannot yet be produced

`HUMAN_HUMAN_AGREEMENT.md`, `SELENE_HUMAN_QUALIFICATION.md`, `REFERENCE_SEED_BIAS_CALIBRATION_AUDIT.md`, `judge_human_confusions.csv`, `judge_human_metrics.csv`, and `qualification_decision.json` all require human labels that do not exist. They are **deliberately not created as empty or placeholder files**, so that their absence is unambiguous and no downstream reader mistakes a stub for a result.

The tooling that produces all of them is written, syntax-checked, and gated to refuse fabricated input.
