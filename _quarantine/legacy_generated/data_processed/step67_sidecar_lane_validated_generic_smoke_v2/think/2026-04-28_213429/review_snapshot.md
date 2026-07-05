# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_smoke_v2/think/2026-04-28_212845/onepass_drafts.jsonl`
- Draft rows: `5`
- Valid rows: `4`
- Error rows: `1`
- Warning rows: `0`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-28_213429",
  "created_utc": "2026-04-28T21:34:29.732798+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_smoke_v2/think/2026-04-28_212845/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_smoke_v2/think/2026-04-28_213429",
  "packet_count": 40,
  "draft_row_count": 5,
  "valid_row_count": 4,
  "error_row_count": 1,
  "warning_row_count": 0,
  "status_counter": {
    "definition::abstained": 2,
    "scope::abstained": 2,
    "definition::grounded": 2,
    "scope::grounded": 2,
    "definition::None": 1,
    "scope::None": 1
  },
  "mode_counter": {
    "definition::abstained": 2,
    "scope::abstained": 2,
    "definition::contextual_synthesis": 2,
    "scope::contextual_synthesis": 2,
    "definition::None": 1,
    "scope::None": 1
  },
  "issue_counter": {
    "ERROR::model call not ok: empty visible model content": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_003'": 1,
    "ERROR::definition: invalid status ''": 1,
    "ERROR::scope: invalid status ''": 1
  },
  "validation_policy": {
    "definition_direct": "direct_definition must cite at least one definition_lane id",
    "definition_contextual": "contextual_synthesis may cite definition, scope, or context ids, must cite at least two positive evidence ids, and must include scope/context support",
    "scope": "scope may cite definition, scope, or context ids; quarantine/sibling ids are errors",
    "abstained": "text, support ids, and supporting_lanes must be empty"
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: SSE (Sum of Squared Error), also known as scatter, is a measure of clustering quality calculated by summing the squared Euclidean distances from each data point to its closest centroid.
- definition_supporting_evidence_ids: `['E2', 'E7']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used as an objective function to evaluate clustering quality, where a lower SSE indicates that the centroids are a better representation of the points in their cluster and that the clustering results are improved.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['context_lane', 'scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_DE_PREP_003 | Duplicate Tuples

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A widely-used model evaluation method in supervised classification that aims to make effective use of all labeled instances for both training and testing.
- definition_supporting_evidence_ids: `['E5', 'E6']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Used for model evaluation and model selection; in nested frameworks, an inner cross-validation framework is used for selection and an outer framework is used for evaluation. Pre-processing operations, such as feature selection or hyper-parameter tuning, should be performed within the training fold of every run rather than on the entire data set.
- scope_supporting_evidence_ids: `['E4', 'E7']`
- scope_supporting_lanes: `['context_lane', 'scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `False`
- definition_status: `None`
- definition_grounding_mode: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `None`
- scope_grounding_mode: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `['model call not ok: empty visible model content', "parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_003'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`
