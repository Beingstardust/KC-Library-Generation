# Step5x Lane Semantics Reset

Date: 2026-05-09  
Status: patch prepared from uploaded Sofja bundle  
Scope: Step5x evidence-pack lane semantics and Step6.6/Step6.7 lane-aware consumption guards

## Decision

This patch makes the Step5x evidence-pack lane contract explicit and machine-checkable.

Automatic drafting support is defined only as:

```text
len(drafting_core_evidence) > 0
```

The following fields are not automatic drafting support:

```text
review_needed_evidence
rejected_false_positive_evidence
expected_evidence_needs
pack_quality.insufficient_reasons
```

## Why this patch exists

Recent audits showed that bare "nonempty pack" counts are misleading because packs can contain review, rejected, expected-need, or insufficiency lists without any drafting-core support. The V18/direct-overlay branch therefore looked superficially nonempty but was operationally mostly insufficient. Old 204794 remains the reset base candidate, but it must be consumed through explicit lane semantics.

## Files changed

```text
src/kc_l/retrieval_gate/evidence_stage_v3_lane_semantics.py
src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py
src/kc_l/kc/drafting_input_overlay.py
src/kc_l/kc_drafting/heuristic_core.py
src/kc_l/utils/kc_step67_model_drafting.py
tests/test_step5x_v3_lane_semantics.py
```

## Contract impact

Step5x pack composition now emits an `evidence_lane_semantics` sidecar for every pack row and stats now report evidence-lane breakdowns plus automatic drafting support counts.

Step6.6 overlay payloads now expose:

```text
drafting_core_evidence
auxiliary_evidence
review_needed_evidence
rejected_false_positive_evidence
evidence_lane_semantics
evidence_pack_membership.selected_for_drafting_core
evidence_pack_membership.drafting_core_positions
evidence_pack_membership.review_needed_positions
evidence_pack_membership.rejected_false_positive_positions
```

Step6.7 heuristic consumption now fails closed when a Step5x v3 pack is available but has no automatic drafting support. Ordered pack items are ignored in that case even if legacy route or slot metadata is present.

## Validation performed on the uploaded package mirror

```text
python3 -m py_compile \
  src/kc_l/retrieval_gate/evidence_stage_v3_lane_semantics.py \
  src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py \
  src/kc_l/kc/drafting_input_overlay.py \
  src/kc_l/kc_drafting/heuristic_core.py \
  src/kc_l/utils/kc_step67_model_drafting.py \
  tests/test_step5x_v3_lane_semantics.py

PYTHONPATH=src python3 tests/test_step5x_v3_lane_semantics.py
```

Both commands passed in the extracted uploaded bundle.

## Remaining unproven

Full repo tests must still run on Sofja after applying the patch because the uploaded bundle is not a complete runnable repo mirror. It omits modules such as `kc_l.audit`, so existing Step5x tests cannot all be executed locally inside the uploaded package.

This patch does not approve old 204794 as final evidence and does not unblock Step6.6. It only makes the lane contract explicit and safer.

## Next validation on Sofja

After applying the patch on Sofja, run targeted py_compile and the focused tests before any replay or Step6.6 run.
