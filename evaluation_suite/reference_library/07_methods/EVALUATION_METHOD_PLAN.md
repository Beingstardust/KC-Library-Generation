# Evaluation Method Plan (infrastructure only — NOT executed)

This describes the reference-based evaluation that will run **after** the expert reference library is frozen (`04_gold/expert_reference_kc_library.jsonl`). Nothing in this document has been run. `06_evaluation_scaffold/` contains the supporting code, built now so it is ready the moment the reference freezes, but none of it has been invoked against real candidate drafts or a real reference — there is no reference yet to run it against.

## Four claim-level relations, after RAGChecker/RAGAS

For candidate draft $D_i$, candidate system evidence $E_i$, and expert reference $G_i$:

**A. Faithfulness** — $D_i$ claims → $E_i$. Are the candidate's claims supported by the evidence actually supplied to that drafter? This measures generation grounding, independent of the reference.

**B. Reference correctness** — $D_i$ claims → $G_i$ / reference authority. Are the candidate's claims semantically compatible with the expert-adjudicated reference and its source authority? An alternative formulation is not wrong merely because its wording doesn't appear in $G_i$ — semantic equivalence is allowed. If a candidate adds a claim not explicitly in $G_i$ but supported by the cited original corpus, it must not be automatically penalized for being absent from the Qwen-seeded reference wording; such cases escalate to a `REFERENCE_SILENT_SOURCE_CHECK_REQUIRED` state rather than being scored FAIL outright (`06_evaluation_scaffold/claim_schema.py`).

**C. Reference completeness** — $G_i$ substantive content → $D_i$. Does the candidate recover the important content represented in the expert reference? Semantic equivalence, not lexical overlap.

**D. Retrieval coverage** — $G_i$ substantive content → $E_i$. Was the source-supported reference content available in the system's retrieval evidence at all? This is the retrieval-side diagnostic the old rubric's F5 was trying to measure, now anchored to an actual expert reference instead of an authority-derived requirements ledger.

RAGAS (Es et al. 2024) motivates separating retrieval/context quality from generation faithfulness/quality; RAGChecker (Ru et al. 2024) is the direct precedent for this four-relation, claim-level diagnostic shape and reports stronger correlation with human judgment than several alternatives.

## No lexical reference metrics as primary quality evaluation

BLEU, ROUGE, exact sentence overlap, edit distance, chrF, and token overlap are not used as primary quality comparisons anywhere in this evaluation. The reference was seeded from Qwen, so surface similarity would structurally favor Qwen. All cross-model content-quality comparisons must be semantic, claim-level, and source-aware (see `ANTI_ANCHORING_PROTOCOL.md`).

## Claim decomposition discipline

Following the lesson from the Selene v3 development work (`evaluation_suite/final_pipeline/rubric_selene_architecture3.py`, and its documented finding that a shared, frozen decomposition avoids re-deriving inconsistent claim sets per criterion): one frozen claim decomposition per reference KC, one frozen decomposition per candidate draft, the same candidate decomposition reused for both faithfulness (A) and correctness (B). Provenance is retained at every step. The claim extractor never redefines the reference — it only decomposes already-frozen text. Formulas/procedures must not be split in a way that destroys their mathematical meaning. Because claim decomposition itself introduces measurement error, a bounded human validation workflow for the decomposition is required before any LLM-generated claim list is trusted as gold (`06_evaluation_scaffold/build_claim_evaluation_rows.py` docstring records this requirement; the validation workflow itself is not yet built, since it is only needed once claim decomposition actually runs).

## Judge model status

No new judge search starts now. Selene 1 Llama-3.3 70B is retained as the leading operational candidate — in the completed development-stage hardening (`evaluation_suite/final_pipeline/output/r9_final/source_artifact_manifest.json`, `v3_architecture_2026-08-24` and `rootsignals_challenger_run_2026-08-24`), it was significantly cleaner than RootSignals-Judge-Llama-70B on structured output (100% F1/F2/F3/F5 contract validity vs. RootSignals' 64.7%-100%, with RootSignals showing systematic JSON truncation from unselective evidence citation under an identical token budget). RootSignals is retained as a documented challenger, not discarded.

Once the expert reference is complete and the claim-level task above is frozen, judge qualification **starts again** on this simplified reference-based task. The old holistic F1-F5 qualification outcome (development-stage sentinel suite results) does not automatically validate the new task — it was built for a different rubric (authority-derived requirement ledgers, not an expert reference) and does not transfer. The new judge must be calibrated against human judgments, per ARES's (Saad-Falcon et al. 2024) precedent for human-calibrated automated RAG evaluation: a bounded human-annotated set, not blind trust in judge output.

## Human judge calibration (later; not run yet)

Planned design for the five unique primary candidate arms (Proposed/Qwen, Proposed/Gemma, Proposed/DeepSeek, Base/Qwen, DOS/Qwen): 30 KCs × 5 arms = 150 human candidate rows (`06_evaluation_scaffold/build_human_calibration_sample.py`). The human evaluator must be blind to system identity, drafter identity, and whether Qwen seeded the reference. Human and automated judge apply the same semantic evaluation protocol. Measured: raw agreement, Gwet AC1, confusion matrices, false-PASS rate, false-FAIL rate, failure recall (`06_evaluation_scaffold/derived_metrics.py`) — the same statistical toolkit already used for the Selene/RootSignals development-stage sentinel qualification, reused here rather than reinvented. Automated judgments are never declared gold merely because the underlying model is strong.

## Intrinsic evaluation (later; not run yet)

Hold Proposed evidence fixed; compare Qwen / Gemma / DeepSeek. Because retrieval is identical across the three, differences primarily reflect drafting-model behavior. Primary content outcomes: faithfulness, reference correctness, reference completeness, strict materially-sound draft rate, abstention behavior. Edit distance to the Qwen-seeded reference is explicitly excluded (see anti-anchoring rationale above).

## Extrinsic evaluation (later; not run yet)

Hold Qwen fixed; compare Base Dense / native DOS-RAG / Proposed. Evaluated separately: retrieval coverage, draft faithfulness, reference correctness, reference completeness, safe abstention, usable KC coverage, evidence volume, technical completion. Matched-budget DOS-RAG remains a separate sensitivity analysis, not folded into the primary extrinsic comparison.

## What is deliberately not built yet

The actual claim-decomposition validation workflow, the judge-prompt schemas for the four claim-level relations, and any code that reads `04_gold/expert_reference_kc_library.jsonl` are not built, because that file does not exist yet. `06_evaluation_scaffold/` contains the row-building and metrics infrastructure that is model/reference-agnostic; the judge-facing prompts/schemas are the next piece of work once the reference freezes and judge qualification restarts.
