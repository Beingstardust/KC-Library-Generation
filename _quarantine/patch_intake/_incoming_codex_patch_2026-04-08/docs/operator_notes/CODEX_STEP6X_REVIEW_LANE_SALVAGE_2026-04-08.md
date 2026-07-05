# Codex Step6.x Review-Lane Salvage Repair
Date: 2026-04-08
Repo: `r:\Thesis Project\kc_l_v2_clean_codeplusstate`

## Objective
Determine the highest-value next architecture move from the current actual-corpus Step 6.x baseline, make the smallest generic fix that materially improves curriculum representation, and document enough durable state to port the work back to Sofja later without chat memory.

## Recovered state summary
- Live actual-corpus ready review surface before this patch:
  - `data/processed/kc_review_packets_restarted/2026-04-08_204029/`
  - `49` ready packets
  - `14` quarantined packets
  - `81` excluded held packets
- Mandatory notes confirmed:
  - `docs/operator_notes/ACTUAL_CORPUS_STEP6X_REPRO_STATE_2026-04-08.md`
  - `docs/operator_notes/STEP6X_ALIAS_REFRESH_RULE_2026-04-08.md`
- Current review scaffolding exists and already honors the `review_packets.jsonl` filename contract:
  - `src/kc_l/kc/restarted_reviewer_session.py`
  - `src/kc_l/kc/restarted_human_review_capture.py`
- `kc_specific_criteria` remained present-and-empty in the current live ready packets and stayed a hard constraint in this repair.

## Diagnosis
- The current ready lane was not sufficiently representative for downstream thesis use.
- Repo-grounded evidence showed the dominant loss was upstream of the ready queue:
  - Step 6.7 statuses on `data/processed/kc_drafts/2026-04-08_131447/kc_draft_bundles.jsonl`: `20 draft_ready`, `43 draft_ready_with_holds`, `81 held`.
  - Step 6.8 was only removing `14` additional packets by quarantine; the main coverage failure was the `81` held bundles never reaching review.
- Family-level underrepresentation in the pre-patch ready lane included:
  - `KC_CLF_UND`: `0 / 5` ready
  - `KC_EVAL_COMP`: `0 / 8` ready
  - `KC_FSEL_GOOD`: `0 / 6` ready
  - `KC_FSEL_GEN`: `1 / 7` ready
  - `KC_EVAL_IMBAL`: `1 / 6` ready
- Live code inspection found a dormant generic salvage seam already present in `src/kc_l/kc/restarted_review_packets.py`:
  - `_held_review_salvage_definition(...)`
  - `HELD_REVIEW_SALVAGE_FLAG`
  - `DEFINITION_REVIEW_SALVAGE_UNVERIFIED_FLAG`
- The seam was defined but not wired into the active emitter. The active emitter excluded every `held` row before packet construction.

## Decision
- The best next move was not a Step 6.7 rerun.
- The smallest generic architecture fix was to reopen Step 6.8 for review-salvageable held bundles that already expose a coherent local-only LLM definition proposal, while keeping hard safety boundaries:
  - keep sibling-boundary-mismatch held bundles excluded
  - keep fragmentary reviewer-facing definition surfaces quarantined
  - keep mixed-foreign decisive definition support quarantined
  - keep scope gaps explicit and reviewer-editable
  - keep `kc_specific_criteria` present-and-empty

## Files changed
- `src/kc_l/kc/restarted_review_packets.py`
- `src/kc_l/kc/restarted_human_review_capture.py`
- `CHANGELOG.md`
- `docs/operator_notes/CODEX_STEP6X_REVIEW_LANE_SALVAGE_2026-04-08.md`

## Behavior change
- `src/kc_l/kc/restarted_review_packets.py`
  - Restored the held-bundle salvage route during packet emission.
  - A `held` Step 6.7 bundle can now become a Step 6.8 review packet only if:
    - it exposes a persisted LLM definition proposal
    - the proposal is local-only to the target KC
    - the surfaced text is coherent enough for review
    - the held reasons do not include `sibling_boundary_mismatch`
  - Salvaged packets are explicitly marked with:
    - `held_bundle_review_salvage`
    - `definition_review_salvage_unverified`
  - The quarantine boundary was narrowed so coherent held-salvage definitions are not auto-quarantined just because they still have a reviewer-editable scope gap plus inherited weak-support flags from the extractive lane.
  - Summary output now records:
    - `held_salvage_ready_count`
    - `held_salvage_ready_kcs`
    - `held_salvage_quarantine_count`
    - `held_salvage_quarantined_kcs`
    - `risk_flags` on quarantined entries
- `src/kc_l/kc/restarted_human_review_capture.py`
  - Removed stale March-27-specific wording from the capture surface.
  - The capture templates now describe the current restarted Step 6.8 surface generically.

## Validation
Validation was performed against the live actual-corpus draft bundle:
- source bundle:
  - `data/processed/kc_drafts/2026-04-08_131447/kc_draft_bundles.jsonl`
- audit validation bundle:
  - `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/`
- key audit artifacts:
  - `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/validation_summary.json`
  - `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/review_packets_surface/review_packets.jsonl`
  - `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/review_packets_surface/review_packet_summary.json`
  - `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/review_packets_surface/real_reviewer_session.md`
  - `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/review_packets_surface/human_review_capture_manifest.json`

### Validation results
- syntax compilation succeeded for:
  - `src/kc_l/kc/restarted_review_packets.py`
  - `src/kc_l/kc/restarted_human_review_capture.py`
- patched Step 6.8 logic on the live Step 6.7 bundle produced:
  - `105` ready packets
  - `25` quarantined packets
  - `14` excluded packets
  - `56` held-salvage packets promoted into the ready reviewer lane
  - `11` held-salvage packets still quarantined for fragmentary reviewer-facing definition surfaces
- downstream reviewer scaffolding rebuilt successfully over that expanded audit-only lane:
  - `105` packets in `real_reviewer_session_manifest.json`
  - `105` packets in `human_review_capture_manifest.json`
  - `14` excluded held cases preserved in capture output
- emitted packets still preserved `kc_specific_criteria == ""`

## Coverage delta evidence
Selected family-level ready-lane changes from the audit validation:

| Family | Total | Old ready | New ready | Delta |
| --- | ---: | ---: | ---: | ---: |
| `KC_CLF_UND` | 5 | 0 | 5 | +5 |
| `KC_EVAL_COMP` | 8 | 0 | 5 | +5 |
| `KC_FSEL_GEN` | 7 | 1 | 6 | +5 |
| `KC_EVAL_IMBAL` | 6 | 1 | 5 | +4 |
| `KC_CLU_DBS` | 9 | 5 | 9 | +4 |
| `KC_CLU_HIER` | 8 | 3 | 7 | +4 |
| `KC_FSEL_GOOD` | 6 | 0 | 3 | +3 |
| `KC_CLU_KM` | 6 | 2 | 5 | +3 |

Repo-grounded conclusion after the patch:
- A. The original `49`-packet ready lane was not representative enough.
- B. The highest-value smallest fix was a Step 6.8 review-boundary repair, not a Step 6.7 rerun.
- C. The next move should be: improve the packet boundary and reviewability first, then proceed to expert review from the expanded lane.

## Commands run
- `Get-Content AGENTS.md`
- `Get-Content CHANGELOG.md`
- `Get-Content docs/operator_notes/ACTUAL_CORPUS_STEP6X_REPRO_STATE_2026-04-08.md`
- `Get-Content docs/operator_notes/STEP6X_ALIAS_REFRESH_RULE_2026-04-08.md`
- `Get-ChildItem data/processed/kc_review_packets_restarted/2026-04-08_204029 -Force`
- `Get-ChildItem data/runs/_audit/2026-04-08_204029_review_boundary -Recurse -Depth 2`
- `Get-Content data/runs/_audit/2026-04-08_204029_review_boundary/operator_note.md`
- `Get-Content data/runs/_audit/2026-04-08_204029_review_boundary/decision_summary.json`
- `Get-Content data/processed/kc_review_packets_restarted/2026-04-08_204029/review_packet_summary.json`
- `Get-Content src/kc_l/kc/restarted_review_packets.py`
- `Get-Content src/kc_l/kc/restarted_reviewer_session.py`
- `Get-Content src/kc_l/kc/restarted_human_review_capture.py`
- `Get-Content src/kc_l/kc/restarted_human_review_pass.py`
- `Get-Content src/kc_l/utils/kc_step67_model_drafting.py`
- `Get-Content steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py`
- `Get-Content steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`
- `python -c "...draft-status and family-count analysis over data/processed/kc_drafts/2026-04-08_131447/kc_draft_bundles.jsonl..."`
- `python -c "...held hold-reason analysis over data/processed/kc_drafts/2026-04-08_131447/kc_draft_bundles.jsonl..."`
- `python -c "...salvageability analysis over held bundles via persisted local-only LLM definition proposals..."`
- `python -c "...family coverage comparison between the live 2026-04-08_204029 Step 6.8 surface and the Codex validation surface..."`
- `python -c "compile(path.read_text(...), str(path), 'exec')"` for the two touched source files
- inline Python validation harness executed inside the repo with a serialization-only `orjson` stub to:
  - emit patched Step 6.8 review packets into `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/review_packets_surface/`
  - rebuild `real_reviewer_session.md`
  - rebuild `human_review_capture_manifest.json`
  - write `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/validation_summary.json`

## Validation caveats
- The local runtime in this workspace could not import `orjson` directly, so the validation harness used a serialization-only stub for `orjson`.
- No semantic packet logic was stubbed or bypassed; the emitted Step 6.8/reviewer/capture behavior came from the live repo code.
- The validation bundle is audit-only and not yet an accepted production rerun under `data/processed/kc_review_packets_restarted/`.

## Remaining risks / open questions
- The newly surfaced held-salvage packets remain heavily machine-labeled as `reject_recommended` because the current supervision logic still treats missing Step 6.7 short-definition contract satisfaction as a low-support signal.
- That recommendation is advisory only, but it may still bias the future expert-review experience and may deserve a later generic calibration pass.
- `14` held cases remain excluded even after the salvage repair because they still fail the held-salvage gate or remain sibling-mismatch risky.
- `25` packets remain quarantined; `11` of those are held-salvage packets whose reviewer-facing definitions are still fragmentary.

## Sync-to-Sofja note
- Must later sync to Sofja: `yes`
- Why:
  - `src/kc_l/kc/restarted_review_packets.py` changes the real Step 6.8 actual-corpus architecture boundary.
  - `src/kc_l/kc/restarted_human_review_capture.py` changes the live reviewer/capture wording on that boundary.
- Audit-only validation artifacts and this note do not themselves need code-sync, but they should travel as documentation/evidence for the Sofja port.

## Exact next action
1. On the real Sofja/runtime environment, rerun Step 6.8 only against `data/processed/kc_drafts/2026-04-08_131447/` using the patched code.
2. Rebuild reviewer-session and human-capture artifacts from that authoritative rerun.
3. Proceed to expert review from the expanded ready lane; do not rerun Step 6.7 first.
4. Treat the newly surfaced held-salvage packets as explicit review-salvage cases, with special attention to the machine-`reject_recommended` bias noted above.
