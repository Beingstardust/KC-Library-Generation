# Step 6.7C lane-aware validation snapshot

- Lanes: `data/processed/step67_sidecar_lane_packets_v4/2026-04-28_155759/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts/2026-04-28_160209/onepass_drafts.jsonl`
- Draft rows: `10`
- Valid rows: `10`
- Error rows: `0`
- Warning rows: `0`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts",
  "run_id": "2026-04-28_160703",
  "created_utc": "2026-04-28T16:07:03.229896+00:00",
  "lanes_path": "data/processed/step67_sidecar_lane_packets_v4/2026-04-28_155759/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts/2026-04-28_160209/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated/2026-04-28_160703",
  "packet_count": 10,
  "draft_row_count": 10,
  "valid_row_count": 10,
  "error_row_count": 0,
  "warning_row_count": 0,
  "status_counter": {
    "definition::grounded": 5,
    "scope::abstained": 7,
    "scope::grounded": 3,
    "definition::abstained": 5
  },
  "issue_counter": {},
  "validation_policy": {
    "definition": "grounded definition must cite at least one definition_lane id and no quarantine/sibling id",
    "scope": "grounded scope may cite scope, definition, or context lane ids; missing scope_lane support is warning",
    "abstained": "text and support ids must be empty"
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: Internal indices are unsupervised measures that use only information present in the data set.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: Sum of the squared error (SSE), also known as scatter, is an objective function used to measure the quality of a clustering; it is calculated by computing the error of each data point (its Euclidean distance to the closest centroid) and then computing the total sum of the squared errors.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `grounded`
- scope_text: Lower SSE translates into noticeably better clustering results, and a smaller squared error indicates that the prototypes (centroids) of a clustering are a better representation of the points in their cluster.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- errors: `[]`
- warnings: `[]`

### KC_DE_PREP_003 | Duplicate Tuples

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `grounded`
- scope_text: Duplicate tuples can waste space and computing time for the DM algorithm and can be a source of inconsistency.
- scope_supporting_evidence_ids: `['E4']`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: A model evaluation method that aims to make effective use of all labeled instances in a dataset for both training and testing by randomly partitioning the set into equal-sized subsets; for each run, one subset is used for testing while the remaining subsets are used for training, with the overall test error rate calculated by summing errors across all runs and dividing by the total number of instances.
- definition_supporting_evidence_ids: `['E3']`
- scope_status: `grounded`
- scope_text: Cross-validation is used for model assessment (evaluation) and model selection, such as hyper-parameter selection, where it allows for the determination of the best hyper-parameter value and the final classification model by making effective use of every data instance in the training set.
- scope_supporting_evidence_ids: `['E2', 'E4']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: Noise points are points that are not in a cluster.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_CORE_002 | Intra-cluster Distance

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: In K-means clustering, intra-cluster dissimilarity is measured by the summation of distances between the objects and the centroid of the cluster they are assigned to.
- definition_supporting_evidence_ids: `['E3', 'E4']`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_011 | Handling Missing Values in NB

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_012 | External Index: Recall

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_005 | Specificity

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`
