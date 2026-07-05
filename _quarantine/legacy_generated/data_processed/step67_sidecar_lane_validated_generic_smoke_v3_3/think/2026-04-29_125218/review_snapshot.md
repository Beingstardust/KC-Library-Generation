# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_v3_3_gemma_smoke8_20260429T123859Z/target_smoke8_lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_smoke_v3_3/think/2026-04-29_124102/onepass_drafts.jsonl`
- Draft rows: `8`
- Valid rows: `7`
- Error rows: `1`
- Warning rows: `2`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-29_125218",
  "created_utc": "2026-04-29T12:52:18.745290+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_v3_3_gemma_smoke8_20260429T123859Z/target_smoke8_lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_smoke_v3_3/think/2026-04-29_124102/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_smoke_v3_3/think/2026-04-29_125218",
  "packet_count": 8,
  "draft_row_count": 8,
  "valid_row_count": 7,
  "error_row_count": 1,
  "warning_row_count": 2,
  "status_counter": {
    "definition::grounded": 4,
    "scope::grounded": 5,
    "definition::abstained": 4,
    "scope::abstained": 3
  },
  "mode_counter": {
    "definition::direct_definition": 2,
    "scope::direct_scope": 2,
    "definition::abstained": 4,
    "scope::abstained": 3,
    "scope::contextual_synthesis": 3,
    "definition::single_strong_context": 1,
    "definition::contextual_synthesis": 1
  },
  "issue_counter": {
    "ERROR::scope: direct_scope lacks scope_lane support": 1,
    "WARNING::scope: grounded only from context_lane": 1,
    "WARNING::definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis": 1
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
- definition_text: In the MAX (complete linkage) version of hierarchical clustering, the proximity between two clusters is defined as the maximum distance (or minimum similarity) between any two points in the two different clusters.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: This method favors globular shapes and is less susceptible to noise and outliers, although it can break large clusters. In graph terminology, a group of points is not considered a cluster until all points within it are completely linked, forming a clique.
- scope_supporting_evidence_ids: `['E2']`
- scope_supporting_lanes: `['definition_lane']`
- errors: `['scope: direct_scope lacks scope_lane support']`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

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

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: In the DBSCAN algorithm, core points within a distance Eps of each other are assigned to the same cluster, and border points that are close enough to a core point are also included in that cluster, though a border point may fall within the neighborhoods of several core points.
- scope_supporting_evidence_ids: `['E7', 'E5']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: SSE, also known as scatter, is an objective function used to measure clustering quality, calculated as the total sum of the squared Euclidean distances from each data point to its closest centroid.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used to compare clustering results, where a lower SSE indicates better clustering and that the centroids are a better representation of the points in their clusters.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_EVAL_BASIC_001 | Confusion Matrix

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: A confusion matrix is a table that summarizes the comparison of predicted labels against the true labels of instances to evaluate the performance of a classifier.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: It is a basic approach for representing a classifier's performance on a test set and can be used to estimate evaluation measures on a test set when combined with an estimate of the test data skew and the TPR and TNR on a validation set.
- scope_supporting_evidence_ids: `['E4', 'E8']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_SIM_003 | Euclidean Distance

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
- definition_text: Hunt's algorithm is used to fit training data by recursively splitting instances based on attribute test conditions; nodes are expanded if they contain instances from more than one class and become leaf nodes when all associated instances have the same class label.
- definition_supporting_evidence_ids: `['E4', 'E5']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Child nodes created by the algorithm may be empty if no training instances possess the specific attribute values.
- scope_supporting_evidence_ids: `['E3']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`
