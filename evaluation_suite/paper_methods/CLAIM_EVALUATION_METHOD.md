# Claim-Level Reference-Based Evaluation Method

## Overview

Each frozen candidate KC draft is evaluated against the frozen expert-adjudicated reference and the original course corpus through four semantic relations plus a target-alignment judgment. The design follows RAGChecker's fine-grained claim-level diagnosis (Ru et al. 2024) and RAGAS's separation of retrieval quality from generation quality (Es et al. 2024), with FActScore's atomic-fact decomposition (Min et al. 2023) as precedent for decomposing long-form text into individually checkable units.

Notation: for KC *i* and arm *j* — `G_i` expert reference, `A_i` source authority for that reference, `D_ij` candidate draft, `E_ij` evidence supplied to that drafter.

## The four relations

| | Relation | Question | Diagnoses |
|---|---|---|---|
| **M1** | `D_ij` claims → `E_ij` | Is each substantive candidate claim supported by the evidence that drafter actually received? | generation grounding |
| **M2** | `D_ij` claims → `G_i` + `A_i` | Is each claim semantically correct for this KC per the reference and source? | content correctness |
| **M3** | `G_i` content → `D_ij` | Does the candidate recover the important reference content? | completeness |
| **M4A** | `G_i` claims → `E_ij` | Was this reference claim available in the retrieved evidence? | retrieval coverage (primary) |
| ~~M4B~~ | `G_i` + `E_ij` → adequacy | *Was the evidence collectively enough?* | **demoted — exploratory only** |

M1 and M2 are deliberately orthogonal: a claim can be faithful to evidence that is itself wrong, and a claim can be correct while ungrounded in the supplied evidence. M3 and M4 separate *the draft failed to use available evidence* from *the evidence never contained it* — the failure decomposition the extrinsic experiment depends on.

### M1 — evidence faithfulness
Labels per claim: `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`.
`faithfulness_precision = supported / material claims`. Abstentions produce no claims; precision is `None`, never 0.0, so a safe abstention is not scored as maximally unfaithful.

### M2 — reference and source correctness
Labels per claim: `CORRECT`, `CONTRADICTED`, `NOT_SUPPORTED_BY_AUTHORITY`, `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED`. `CORRECT` and `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` count as materially correct.

The `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` path is **mandatory**, not a convenience. The reference was seeded from one specific system; without this label, any correct statement that system happened not to make would be scored wrong for every other system. A claim is never marked incorrect merely because its wording, level of detail, or optional content is absent from the reference. `CONTRADICTED` is reserved for genuine incompatibility.

This binding is enforced at the grammar level rather than by instruction: the JSON schema uses a `oneOf` discriminated union so `CORRECT`/`CONTRADICTED` can only cite reference ids, `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` can only cite source-authority ids, and `NOT_SUPPORTED_BY_AUTHORITY` can only emit an empty citation array. The judge cannot assert "the source backs it" without pointing at the source passage. Enforcement was verified by compiling the schema and reading the emitted grammar (`tests/test_grammar_enforcement.py`); `if/then/else` was confirmed to be silently ignored by the pinned toolchain and is used nowhere.

### M3 — reference completeness (two separate outputs)
1. `reference_claim_coverage` — per reference claim, `PRESENT` / `PARTIALLY_PRESENT` / `ABSENT`, aggregated with partial credit. A **descriptive** measure.
2. Holistic `CORE_COMPLETE` / `MATERIAL_OMISSION` / `NOT_JUDGEABLE` — the judgment that decides whether an omission matters.

These are separate inference calls because `CORE_COMPLETE` must not require full claim coverage. Missing examples, optional applications, extra detail, different organization, different wording, and greater concision are explicitly **not** material omissions.

### M4A — reference-claim retrieval recall (primary retrieval diagnostic)

Per reference claim, `SUPPORTED_BY_RETRIEVAL` / `NOT_SUPPORTED_BY_RETRIEVAL`:

```
retrieval_reference_recall = reference claims supported by candidate evidence
                             --------------------------------------------------
                                    total substantive reference claims
```

This is the RAGChecker-style claim-recall formulation (Ru et al. 2024): a concrete, decomposed question asked one proposition at a time - *is there source support for this claim in the evidence the drafter received?*

**Retrieval coverage is deliberately not called "evidence sufficiency."** A value below 1.0 does **not** mean the evidence was inadequate: a concise evidence set can omit reference detail and still support an adequate draft. Preferred terms are *reference-claim retrieval recall*, *retrieval coverage*, or *reference-content coverage by retrieval*.

M4A is an **upstream explanatory** metric and is **not** a condition of `materially_sound`.

### M4B - holistic evidence adequacy (EXPLORATORY ONLY, demoted 2026-08-25)

The holistic classifier (`EVIDENCE_ADEQUATE` / `MATERIAL_EVIDENCE_GAP`) was investigated during development and **excluded from primary evaluation**. On the development sentinels it marked 18 of 25 adequate cases as having a material gap (28.0% agreement), and inspection showed it enumerating phrases taken from the expert reference itself as "missing evidence" - treating the reference as a mandatory checklist despite explicit instruction to the contrary. This reproduced the construct-validity failure previously seen in the v3 F4/F5 design, across two independently trained judge models.

It may not be used as a primary metric, in `materially_sound`, in judge qualification gating, in the intrinsic or extrinsic comparison, to classify a system as successful or failed, or to derive abstention validity. It is retained as an exploratory diagnostic and optional human-calibration research output. See `../reference_eval/output/m4_scope_decision.md`.

This is reported rather than hidden: it is useful negative-method evidence about holistic sufficiency judgments in LLM-as-judge evaluation.

### Target alignment
`TARGET_ALIGNED` / `WRONG_TARGET` / `NOT_JUDGEABLE`, decided against the reference's description of the intended KC. The v3 extract-subject-then-compare mechanism is retired. A draft that is entirely accurate about a neighbouring concept is `WRONG_TARGET`: being correct about the wrong thing is still wrong. Word overlap is explicitly not the basis.

## Claim decomposition

One frozen decomposition per candidate draft, reused for M1 and M2. One frozen decomposition per reference, reused for M3 coverage and M4. Never decomposed separately per relation — independently re-derived claim sets cannot be compared to one another, a lesson taken directly from the earlier v3 development work.

Requirements: mathematical relations stay intact as single claims together with the variable meanings needed to interpret them; procedure steps are not split where splitting destroys the procedure; headings and stylistic phrases do not become claims; nothing implicit is invented. Every claim retains its parent text span, a stable id, its source text, and a descriptive type (definition, formula, condition, procedure, relationship, taxonomy, factual, other).

These types are descriptive labels only. This is **not** a second KES or core-requirements ledger — the reference is the authority, and the decomposer may never redefine it.

Structural validation runs on every decomposition: each `parent_span` must be a literal substring of the decomposed text (catching invented provenance), formula-bearing source text must have at least one claim preserving a mathematical relation, and gross under-coverage is flagged. Decomposition is additionally human-validated on a stratified subset before results are opened, with the error rate reported.

## Derived per-KC metrics

For each fully supported KC and candidate: `faithfulness_precision`, `authority_correctness_precision`, `reference_claim_coverage`, `retrieval_reference_recall`, `target_aligned`, `core_complete`, `draft_exists`. (`exploratory_holistic_evidence_adequacy` is recorded for the audit trail but is not a production metric.)

Primary aggregation is **KC-macro**, so a KC with 30 claims does not outweigh one with 4. Micro claim totals are secondary diagnostics only.

### Strict binaries (deterministic, fixed before results)

```
materially_sound = draft_exists
                   AND target_aligned
                   AND faithfulness_precision == 1.0
                   AND authority_correctness_precision == 1.0
                   AND core_complete

unsafe_draft     = draft_exists
                   AND (NOT target_aligned
                        OR authority_correctness_precision < 1.0
                        OR faithfulness_precision < 1.0)
```

`materially_sound` deliberately does **not** require `reference_claim_coverage == 1.0`, because the reference can contain valid enrichment beyond the minimum needed for an adequate description; the holistic completeness judgment decides materiality. It also excludes **both** M4 outputs - `materially_sound` measures the final KC draft, while retrieval coverage explains that outcome rather than defining it. This was verified programmatically against the derivation source. A material omission breaks `materially_sound` without making a draft `unsafe` — incompleteness is not incorrectness.

Continuous metrics are always reported alongside the binaries. No weighted composite quality score is constructed.

## Source-boundary outcomes

- **7 UNSUPPORTED KCs** (adjudicated corpus gaps): `safe_gap_handling` = no substantive definition produced. Clean abstention is safe; a confident definition is unsafe unless a later blinded source adjudication shows the reference itself was wrong. Ordinary reference-completeness metrics are not computed.
- **2 PARTIALLY_SUPPORTED KCs**: evaluated on faithfulness, overreach, and coverage of the supported portion only. No completeness requirement. Reported separately from the 150.
- **`safe_curriculum_outcome`** (all 159, secondary): `materially_sound` on supported KCs, safe partial behavior on partial KCs, safe gap handling on unsupported KCs. Derivation fixed and documented before results; kept separate from the primary 150-KC content measure.

## What is excluded

BLEU, ROUGE, chrF, exact-match percentage, token overlap, edit distance, n-gram similarity, and embedding similarity to the reference are excluded as primary or supporting ranking evidence. The reference was machine-seeded from one arm; surface comparison would hand that arm a structural advantage unrelated to quality. All content-quality comparison is semantic, claim-level, and source-aware.
