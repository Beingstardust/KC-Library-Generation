# Candidate Freeze Report

Generated 2026-08-24. Full machine-readable detail is in `CANDIDATE_FREEZE_MANIFEST.json`; this is the human-readable summary.

## What is frozen

7 candidate draft arms, all sharing the identical 159 Data Mining KC ids (cross-checked pairwise, zero mismatches):

| Arm | System | Drafter | Commit | Rows |
|---|---|---|---|---|
| intrinsic P-Q | Proposed | Qwen3.8 27B | 6ebcd75 | 159 |
| intrinsic P-G | Proposed | Gemma4 31B | 6ebcd75 | 159 |
| intrinsic P-D | Proposed | DeepSeek R1 32B | 6ebcd75 | 159 |
| extrinsic P-Q | Proposed (controlled_comparator) | Qwen3.8 27B | 450c88c | 159 |
| extrinsic B-Q | Base Dense | Qwen3.8 27B | 450c88c | 159 |
| extrinsic DOS-Q | native full DOS-RAG | Qwen3.8 27B | 450c88c | 159 |
| sensitivity DOS-Q (matched budget) | budget-matched DOS-RAG | Qwen3.8 27B | 6ebcd75 | 159 |

Plus the original course corpus (`sentence_corpus.jsonl`, 100,218 sentences) and the 4 source PDFs it was extracted from, and the hierarchy overlay (188 lines / 160 node identities).

## How this was verified (not inferred from filenames)

Every sha256 above was computed fresh against the live files on Cluster-B on 2026-08-24 (`verify_candidate_freeze.py`, raw output in `_verification_run_raw.json`), then cross-checked against the hashes already on record in `evaluation_suite/final_pipeline/output/r9_final/source_artifact_manifest.json` from the earlier evaluation-campaign session. All 7 candidate hashes matched exactly — no drift. All 7 files independently confirmed at 159/159 rows and 159/159 unique KC ids, and the 159-id sets are identical across every arm.

The corpus hash was flagged in the prior manifest as "carried forward, recommend re-verification before final freeze" — that re-verification is exactly what this freeze performed, and it also matched exactly.

The 4 original PDFs were located by cross-referencing the shared provenance hash (`9e856df6`) embedded in the corpus/hierarchy build paths against `data/input/9e856df6-ed73-4e33-9536-82aa7bdeec30/course_materials/` on Cluster-B, then confirming their 4 filenames' derived `doc_id`s exactly account for all 4 distinct `doc_id` values that actually appear in the sentence corpus (no missing or extra document).

## The seed-source decision

The editing scaffold for reference construction is **extrinsic P-Q** (`r9final_ext_proposed_ctrl_20260823T140000Z`, commit 450c88c, controlled_comparator mode) — the most current, most rigorously-built Proposed+Qwen draft, not the older intrinsic P-Q file. This decision and its rationale are recorded in the manifest's `seed_source_designation` block, together with an explicit note that this creates the exact seed/candidate overlap the anti-anchoring protocol exists to control for (`extrinsic P-Q` is both the seed source and one of the 7 frozen evaluation arms).

## Local mirrors

`sentence_corpus.jsonl`, the 4 source PDFs, and the hierarchy overlay were copied locally into `evaluation_suite/final_pipeline/reference_library/corpus_support/` so the curation console can run without a live Cluster-B connection. Every local copy's hash was independently re-verified byte-for-byte against the remote hash after transfer (all matched). The 7 candidate draft files themselves remain on Cluster-B only (too large to be useful locally beyond the one designated as the seed, which is separately snapshotted into `01_seed/`).

## Effective as of this freeze

None of the 7 candidate files, the corpus, the PDFs, or the hierarchy overlay may be regenerated, repaired, or modified using anything learned during reference construction. `candidates_frozen.lock.json` records a hash of this freeze manifest itself; `freeze_reference_library.py` re-checks that hash at final reference freeze time to prove this freeze was never edited mid-curation.
