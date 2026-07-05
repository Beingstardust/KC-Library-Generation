# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_v3_3_gemma_smoke8_20260429T123859Z/target_smoke8_lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_smoke_v3_3/nothink/2026-04-29_123913/onepass_drafts.jsonl`
- Draft rows: `8`
- Valid rows: `8`
- Error rows: `0`
- Warning rows: `5`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-29_124101",
  "created_utc": "2026-04-29T12:41:01.770221+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_v3_3_gemma_smoke8_20260429T123859Z/target_smoke8_lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_smoke_v3_3/nothink/2026-04-29_123913/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_smoke_v3_3/nothink/2026-04-29_124101",
  "packet_count": 8,
  "draft_row_count": 8,
  "valid_row_count": 8,
  "error_row_count": 0,
  "warning_row_count": 5,
  "status_counter": {
    "definition::grounded": 6,
    "scope::abstained": 3,
    "scope::grounded": 5,
    "definition::abstained": 2
  },
  "mode_counter": {
    "definition::direct_definition": 1,
    "scope::abstained": 3,
    "definition::single_strong_context": 3,
    "scope::single_strong_context": 2,
    "definition::abstained": 2,
    "scope::contextual_synthesis": 2,
    "definition::contextual_synthesis": 2,
    "scope::direct_scope": 1
  },
  "issue_counter": {
    "WARNING::definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis": 3,
    "WARNING::scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis": 2,
    "WARNING::scope: grounded only from context_lane": 1,
    "WARNING::definition: contextual_synthesis also cites definition_lane support": 1
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

### KC_CLU_HIER_005 | MAX (Complete Linkage)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: In the MAX or complete link version of hierarchical clustering, the proximity between two clusters is the maximum distance (or minimum similarity) between any two points from the different clusters.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
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
- scope_text: Noise points are characterized by having a relatively large k-dist compared to points belonging to a cluster.
- scope_supporting_evidence_ids: `['E4']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: In the DBSCAN algorithm, core points that are within a distance Eps of each other are placed in the same cluster; additionally, any border point located within the neighborhood of a core point is also assigned to that core point's cluster.
- scope_supporting_evidence_ids: `['E5', 'E7']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Sum of the squared error (SSE), also known as scatter, is an objective function used to measure clustering quality. It is calculated by computing the total sum of the squared Euclidean distances from each data point to its closest centroid.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used to compare different K-means clustering results, where a lower SSE indicates that the centroids are a better representation of the points in their cluster and generally reflects better clustering results.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_EVAL_BASIC_001 | Confusion Matrix

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A confusion matrix is a table used to summarize the performance of a classifier by comparing predicted labels against the true labels of instances, recording the number of instances predicted correctly or incorrectly.
- definition_supporting_evidence_ids: `['E2', 'E8']`
- definition_supporting_lanes: `['definition_lane', 'context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: A confusion matrix can be used as a basic approach for representing a classifier's performance on a test set.
- scope_supporting_evidence_ids: `['E8']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: contextual_synthesis also cites definition_lane support', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_SIM_003 | Euclidean Distance

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Euclidean distance is the distance between the grid locations of two centroids, calculated as $( \mathsf { x j - x k } ) 2 \mathsf { + } ( \mathsf { y j - y k } ) 2$.
- definition_supporting_evidence_ids: `['E3']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_CLF_NB_003 | Conditional Probability (Likelihood)

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

### KC_CLF_DT_001 | Hunt's Algorithm

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Hunt's algorithm is a recursive process used to fit training data into a tree structure, where nodes are expanded and the algorithm is applied to each resulting child.
- definition_supporting_evidence_ids: `['E4', 'E5']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: In Hunt's algorithm, child nodes may be empty if no training instances possess the specific attribute values.
- scope_supporting_evidence_ids: `['E3']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`
