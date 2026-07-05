# CODEX Step 6.8 Invalid Page-Index Sanitation

Date: 2026-04-11
Repo: `r:\Thesis Project\kc_l_v2_clean_sofja_authoritative_2026-04-10_225640`
Scope: narrow Step 6.8 packetization hygiene only

## Recovered State

- Codex remained local-only in this pass.
- Sofja ground truth for the failing run:
  - Step 6.7 succeeded with `qwen3:30b`
  - Step 6.8 failed during review packet validation
  - failing KC: `KC_CLF_DT_006`
  - failing canonical name: `Information Gain`
  - failing error: `ValueError: Evidence span 14 page_index invalid`
  - reported bad emitted span had:
    - `page_index = -1`
    - `extraction_method = step6_8_restarted_review_packet_evidence`
    - `role = scope`
    - `provenance_quality_flags` including `ProvenanceStatus:dropped`
- Local repo evidence read before edits:
  - `AGENTS.md`
  - `CHANGELOG.md`
  - `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
  - `src/kc_l/kc_drafting/packetization.py`
  - `src/kc_l/kc/review_packets.py`
  - `data/processed/kc_drafts/2026-04-11_014712/draft_stats.json`
  - `data/processed/kc_drafts/_sets/2026-04-11_014712_step6_7_kc_drafts_set.json`
  - `data/processed/kc_drafts/2026-04-11_014712/kc_draft_bundles.jsonl`
  - `data/runs/2026-04-11_015224_step6_8/summary.json`
- Exact root cause:
  - `src/kc_l/kc/review_packets.py` already correctly rejects any evidence span whose `page_index` is not an `int >= 0`
  - `src/kc_l/kc_drafting/packetization.py` only required `page_index` to be an `int`, so negative values such as `-1` could be emitted and then fail later in `validate_review_packet`

## Exact Fix

- Changed `src/kc_l/kc_drafting/packetization.py` only.
- Added `_coerce_non_negative_page_index(...)`:
  - accepts existing non-negative `int`
  - accepts clearly int-like `str`
  - rejects negative, empty, boolean, and non-int-like values
- Refined `_build_evidence_spans(...)` so Step 6.8 now:
  - sanitizes page indexes before emitting packet evidence spans
  - drops spans whose page index remains invalid after safe coercion
  - counts dropped invalid-page-index spans
- Added packet-level signaling:
  - `invalid_page_index_dropped`
- Added Step 6.8 summary accounting:
  - `dropped_invalid_page_index_span_count`
  - `packets_with_invalid_page_index_drops`
  - explicit `excluded_candidate_count`
- Kept the global validator unchanged.
- Did not touch Step 6.9+.
- Did not invent page numbers.
- Did not widen packet semantics beyond this hygiene rule.

## Tests Added

Added to `tests/test_kc_drafting_packetization.py`:

- `test_restarted_review_packet_drops_invalid_negative_page_index_span`
  - proves `page_index = -1` is dropped before validation
  - proves the emitted packet gets `invalid_page_index_dropped`
- `test_emit_restarted_review_packets_counts_dropped_invalid_page_index_spans`
  - proves end-to-end summary accounting for dropped invalid-page-index spans

## Exact Files Changed

- `src/kc_l/kc_drafting/packetization.py`
- `tests/test_kc_drafting_packetization.py`
- `docs/operator_notes/CODEX_ACTIVE_STEP6_REFACTOR_STATE.md`
- `docs/operator_notes/CODEX_STEP68_INVALID_PAGE_INDEX_SANITATION_2026-04-11.md`
- `CHANGELOG.md`

Generated during local validation:

- `data/work/cache/generated_configs/step6_8.local_replay.2026-04-11_hpc014712.yaml`
- `data/processed/kc_review_packets_restarted/2026-04-11_193327/`
- `data/runs/2026-04-11_193327_step6_8/`

## Exact Commands Run

Read/inspection:

- `Get-Content src\kc_l\kc\review_packets.py`
- `Get-Content src\kc_l\kc_drafting\packetization.py`
- `Get-Content data\work\cache\current_step_artifacts\step6_7_set_manifest.current.json`
- `Get-Content data\processed\kc_drafts\2026-04-11_014712\draft_stats.json`
- `Get-Content data\processed\kc_drafts\_sets\2026-04-11_014712_step6_7_kc_drafts_set.json`
- `Select-String -Path data\processed\kc_drafts\2026-04-11_014712\kc_draft_bundles.jsonl -Pattern '"kc_id":"KC_CLF_DT_006"'`
- `Get-Content data\runs\2026-04-11_015224_step6_8\summary.json`

Validation:

- `.\.venv\Scripts\python.exe -m py_compile src\kc_l\kc_drafting\packetization.py tests\test_kc_drafting_packetization.py`
- `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_kc_drafting_packetization.py`
- wrote one-off replay config:
  - `data/work/cache/generated_configs/step6_8.local_replay.2026-04-11_hpc014712.yaml`
- replayed Step 6.8 against the synced Sofja Step 6.7 set:
  - `.\.venv\Scripts\python.exe steps\step_06_8_kc_review_packet_emission\scripts\run_step6_8_kc_review_packet_emission.py --config data\work\cache\generated_configs\step6_8.local_replay.2026-04-11_hpc014712.yaml`

## Validation Results

- `py_compile`: passed
- `pytest tests/test_kc_drafting_packetization.py`: `7 passed`
- local Step 6.8 replay against synced Step 6.7 set `2026-04-11_014712`:
  - run id: `2026-04-11_193327`
  - processed dir: `data/processed/kc_review_packets_restarted/2026-04-11_193327/`
  - audit dir: `data/runs/2026-04-11_193327_step6_8/`
  - `packet_count = 10`
  - `excluded_candidate_count = 0`
  - `quarantine_count = 0`
  - `dropped_invalid_page_index_span_count = 0`
  - `packets_with_invalid_page_index_drops = []`
  - `KC_CLF_DT_006` emitted successfully

Important validation caveat:

- the synced local `2026-04-11_014712` Step 6.7 artifact did not reproduce the exact bad emitted span inside its selected `evidence_bundle`
- the exact negative-page-index behavior is therefore proven by the new regression tests plus code-path inspection, while the replay proves the patched Step 6.8 path still emits the full synced slice cleanly

## Remaining Risks

- The exact Sofja-failing bad span appears to have existed in a later or different active Step 6.7 evidence surface than the synced local `2026-04-11_014712` selected `evidence_bundle`, so the full reproduction still needs a Sofja rerun after sync.
- This pass intentionally did not add a broader provenance-status dropping rule; only invalid page-index sanitation was implemented because that was the smallest coherent trust-preserving fix required by the failure.

## Exact Next Action

Sync this patch to Sofja and rerun Step 6.8 on the bounded slice so the real failing `KC_CLF_DT_006` packet is exercised under the patched sanitation layer.

Exact next Sofja command:

```bash
python steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py --config steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice10.yaml
```
