# CODEX Step 6.8 Reviewer Usefulness Keep And Edit 2026-04-14

Date: 2026-04-14
Repo: `R:\Thesis Project\kc_l_v2_clean_sofja_authoritative_sync`

## Recovered State Summary

- Active Step 6.7 path: `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py` -> `src/kc_l/kc_drafting/orchestration.py` -> `src/kc_l/kc_drafting/backend.py` -> `src/kc_l/utils/kc_step67_model_drafting.py`.
- Active Step 6.8 path: `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py` -> `src/kc_l/kc_drafting/orchestration.py` -> `src/kc_l/kc_drafting/packetization.py`.
- Latest synced full-run truth boundary inspected directly: Step 6.7 set `2026-04-14_151912_step6_7_kc_drafts_set` and Step 6.8 set `2026-04-14_160917_step6_8_kc_review_packets_restarted_set`.
- Historical compatibility seams were not touched.

## Diagnosis

- The full 144-KC Step 6.8 summary already proves that coverage, survival, hierarchy-aware packetization, and trust-state propagation are working.
- The remaining reviewer-usefulness bottleneck was the live recommendation surface: `121` low-trust seed-floor survivors were still labeled `reject_recommended`, even though those packets were explicitly preserved for human review and already carried the seed-floor support needed for keep-and-edit decisions.
- The harsh recommendation was coming from the active Step 6.8 recommendation bridge, not from a missing packet field or missing Step 6.7 survival output.

## Patch

- `src/kc_l/kc_drafting/packetization.py` now softens `system_recommendation` from `reject_recommended` to `review_needed` only when all of the following are true:
  - the packet is an explicit `seed_floor_fallback` survivor
  - `review_readiness.label` is `low_trust` and review-lane survival stays true
  - the rejection reason codes are only fallback-weakness reasons (`support_contract_downgraded`, `definition_short_contract_fail`, or low-support priority)
  - no hard contamination/salvage flags such as mixed foreign decisive support or held-salvage unverification are present
- The same packetization seam now adds an explicit reviewer note that fallback status alone is not a reject signal and the packet should support keep-and-edit review when the concept itself remains valid.
- Mixed-foreign cases continue to surface as `reject_recommended`.

## Validation

- `python -m py_compile src/kc_l/kc_drafting/packetization.py tests/test_kc_drafting_packetization.py`
- Direct synthetic assertions over the active packet builder for:
  - low-trust seed-floor keep-and-edit recommendation
  - mixed-foreign guard staying `reject_recommended`
- Full local Step 6.8 replay over the synced 144-KC Step 6.7 set using `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml`.

## Expected Full-Run Impact

- Packet count remains `144`.
- No KC is excluded or quarantined by this patch.
- Low-trust seed-floor survivors remain low-support packets, but their reviewer-facing recommendation surface shifts from pseudo-rejection to explicit review-needed keep-and-edit guidance unless contamination signals are present.
