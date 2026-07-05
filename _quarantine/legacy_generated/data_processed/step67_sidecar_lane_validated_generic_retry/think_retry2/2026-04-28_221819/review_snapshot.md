# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67bc_think_retry2_input_20260428T221349Z/retry2_lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_retry/think_retry2/2026-04-28_221418/onepass_drafts.jsonl`
- Draft rows: `2`
- Valid rows: `2`
- Error rows: `0`
- Warning rows: `1`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-28_221819",
  "created_utc": "2026-04-28T22:18:19.133731+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67bc_think_retry2_input_20260428T221349Z/retry2_lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_retry/think_retry2/2026-04-28_221418/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_retry/think_retry2/2026-04-28_221819",
  "packet_count": 2,
  "draft_row_count": 2,
  "valid_row_count": 2,
  "error_row_count": 0,
  "warning_row_count": 1,
  "status_counter": {
    "definition::grounded": 2,
    "scope::grounded": 2
  },
  "mode_counter": {
    "definition::contextual_synthesis": 2,
    "scope::contextual_synthesis": 1,
    "scope::single_strong_context": 1
  },
  "issue_counter": {
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

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: SSE (Sum of Squared Error), also known as scatter, is a measure of clustering quality calculated as the total sum of the squared Euclidean distances from each data point to its closest centroid.
- definition_supporting_evidence_ids: `['E2', 'E7']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used as an objective function to evaluate clustering quality, where a lower SSE indicates that the centroids are a better representation of the points in their cluster.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Noise points are points that do not belong to a cluster, and may result from the random component of a measurement error, such as the addition of spurious objects or the distortion of a value.
- definition_supporting_evidence_ids: `['E3', 'E4']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: Noise points are characterized by having a relatively large k-dist.
- scope_supporting_evidence_ids: `['E4']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`
