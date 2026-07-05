# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_smoke_v2/nothink/2026-04-28_220135/onepass_drafts.jsonl`
- Draft rows: `5`
- Valid rows: `4`
- Error rows: `1`
- Warning rows: `1`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-28_220232",
  "created_utc": "2026-04-28T22:02:32.395701+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_smoke_v2/nothink/2026-04-28_220135/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_smoke_v2/nothink/2026-04-28_220232",
  "packet_count": 40,
  "draft_row_count": 5,
  "valid_row_count": 4,
  "error_row_count": 1,
  "warning_row_count": 1,
  "status_counter": {
    "definition::abstained": 2,
    "scope::abstained": 2,
    "definition::grounded": 3,
    "scope::grounded": 3
  },
  "mode_counter": {
    "definition::abstained": 2,
    "scope::abstained": 2,
    "definition::contextual_synthesis": 2,
    "scope::contextual_synthesis": 2,
    "definition::single_strong_context": 1,
    "scope::single_strong_context": 1
  },
  "issue_counter": {
    "ERROR::definition: contextual_synthesis requires at least two supporting evidence ids": 1,
    "WARNING::definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis": 1,
    "WARNING::scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis": 1
  },
  "validation_policy": {
    "definition_direct": "direct_definition must cite at least one definition_lane id",
    "definition_contextual": "contextual_synthesis may cite definition, scope, or context ids, must cite at least two positive evidence ids, and must include scope/context support",
    "definition_single_strong_context": "single_strong_context may cite exactly one strong scope or context id and should be human-reviewed",
    "scope": "scope may cite definition, scope, or context ids; quarantine/sibling ids are errors",
    "scope_single_strong_context": "single_strong_context may cite exactly one strong scope or context id and should be human-reviewed",
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
- definition_text: Sum of the squared error (SSE), also known as scatter, is a measure of clustering quality calculated by summing the squared Euclidean distances from each data point to its closest centroid.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used to compare different K-means clustering results, where a smaller squared error indicates that centroids better represent the points in their cluster; lower SSE is associated with better clustering results.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['context_lane', 'scope_lane']`
- errors: `['definition: contextual_synthesis requires at least two supporting evidence ids']`
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
- definition_text: Cross-validation is a model evaluation method used in supervised classification that aims to effectively utilize all labeled instances in a dataset for both training and testing.
- definition_supporting_evidence_ids: `['E5', 'E6']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Cross-validation is used for model evaluation and model selection. When used for model selection, it can be employed as an inner framework to select the best hyper-parameter value and resulting classification model, while an outer framework is used for model evaluation.
- scope_supporting_evidence_ids: `['E4', 'E7']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Noise points are data points that are not in a cluster.
- definition_supporting_evidence_ids: `['E4']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: In the context of determining DBSCAN parameters, noise points are characterized by having a relatively large k-dist.
- scope_supporting_evidence_ids: `['E4']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`
