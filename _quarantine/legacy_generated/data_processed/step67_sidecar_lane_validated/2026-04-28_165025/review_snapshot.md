# Step 6.7C lane-aware validation snapshot

- Lanes: `data/processed/step67_sidecar_lane_packets_v4_40_lanepositive20/2026-04-28_163139/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts/2026-04-28_163234/onepass_drafts.jsonl`
- Draft rows: `20`
- Valid rows: `9`
- Error rows: `11`
- Warning rows: `0`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts",
  "run_id": "2026-04-28_165025",
  "created_utc": "2026-04-28T16:50:25.519518+00:00",
  "lanes_path": "data/processed/step67_sidecar_lane_packets_v4_40_lanepositive20/2026-04-28_163139/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts/2026-04-28_163234/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated/2026-04-28_165025",
  "packet_count": 20,
  "draft_row_count": 20,
  "valid_row_count": 9,
  "error_row_count": 11,
  "warning_row_count": 0,
  "status_counter": {
    "definition::None": 11,
    "scope::None": 11,
    "definition::grounded": 4,
    "scope::grounded": 2,
    "scope::abstained": 7,
    "definition::abstained": 5
  },
  "issue_counter": {
    "ERROR::model call not ok: parsed output missing or not object": 9,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_EVAL_SAMP_003'": 1,
    "ERROR::definition: invalid status ''": 11,
    "ERROR::scope: invalid status ''": 11,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLF_DT_006'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_SIM_003'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_SIM_007'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLF_DT_001'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_KM_001'": 1,
    "ERROR::model call not ok: empty visible model content": 2,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLF_UND_005'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_HIER_005'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLF_DT_004'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_EVAL_BASIC_001'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_001'": 1
  },
  "validation_policy": {
    "definition": "grounded definition must cite at least one definition_lane id and no quarantine/sibling id",
    "scope": "grounded scope may cite scope, definition, or context lane ids; missing scope_lane support is warning",
    "abstained": "text and support ids must be empty"
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Rows

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_EVAL_SAMP_003'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLF_DT_006 | Information Gain

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLF_DT_006'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLU_SIM_003 | Euclidean Distance

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLU_SIM_003'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLU_SIM_007 | Jaccard Coefficient

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLU_SIM_007'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: SSE (sum of the squared error), also known as scatter, is calculated by computing the total sum of the squared errors, where the error of each data point is its Euclidean distance to the closest centroid.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `grounded`
- scope_text: The centroid that minimizes the SSE of a cluster is the mean, and certain procedures like K-means++ can result in lower SSE.
- scope_supporting_evidence_ids: `['E3', 'E7']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_001 | Hunt's Algorithm

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLF_DT_001'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLU_KM_001 | K-Means Algorithm

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLU_KM_001'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLF_UND_005 | Mutually Exclusive Classes

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: empty visible model content', "parsed kc_id mismatch parsed='' expected='KC_CLF_UND_005'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: Noise points are points that are not in a cluster.
- definition_supporting_evidence_ids: `['E4']`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_HIER_005 | MAX (Complete Linkage)

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLU_HIER_005'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLF_DT_004 | Gini Index

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLF_DT_004'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_EVAL_BASIC_001 | Confusion Matrix

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: empty visible model content', "parsed kc_id mismatch parsed='' expected='KC_EVAL_BASIC_001'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

### KC_CLF_NB_002 | Prior Probability

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `grounded`
- scope_text: In the extreme case where no attributes are observed, the prior probability P(y) can be used as an estimate of the posterior probability.
- scope_supporting_evidence_ids: `['E3', 'E5']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `False`
- definition_status: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_001'", "definition: invalid status ''", "scope: invalid status ''"]`
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

### KC_CLU_EVAL_009 | External Index: Purity

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_010 | Bushy Decision Tree (Multi-split)

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_001 | Bayes' Theorem

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_003 | Conditional Probability (Likelihood)

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`
