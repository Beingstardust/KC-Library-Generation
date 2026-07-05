# Step 6.7C lane-aware validation snapshot

- Lanes: `data/processed/step67_sidecar_lane_packets_v8_40_lanepositive20/2026-04-28_171714/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts/2026-04-28_171815/onepass_drafts.jsonl`
- Draft rows: `20`
- Valid rows: `20`
- Error rows: `0`
- Warning rows: `0`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts",
  "run_id": "2026-04-28_172133",
  "created_utc": "2026-04-28T17:21:33.492109+00:00",
  "lanes_path": "data/processed/step67_sidecar_lane_packets_v8_40_lanepositive20/2026-04-28_171714/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts/2026-04-28_171815/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated/2026-04-28_172133",
  "packet_count": 20,
  "draft_row_count": 20,
  "valid_row_count": 20,
  "error_row_count": 0,
  "warning_row_count": 0,
  "status_counter": {
    "definition::grounded": 7,
    "scope::grounded": 8,
    "definition::abstained": 13,
    "scope::abstained": 12
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

### KC_EVAL_BASIC_001 | Confusion Matrix

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: A confusion matrix is a table that summarizes the performance of a classifier by comparing predicted labels against the true labels of instances, where each entry denotes the number of instances from class i predicted to be of class j.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `grounded`
- scope_text: A confusion matrix can be used to record how often characters are classified as themselves or others, to define a similarity measure between characters based on misclassification counts, and to estimate evaluation measures on a test set when combined with an estimate of test data skew and validation set TPR and TNR.
- scope_supporting_evidence_ids: `['E3', 'E4', 'E7']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: Also known as scatter, the sum of the squared error (SSE) is an objective function used to measure the quality of a clustering; it is calculated by computing the error of each data point (its Euclidean distance to the closest centroid) and then computing the total sum of the squared errors.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `grounded`
- scope_text: In the context of K-means, a smaller SSE indicates that the prototypes (centroids) are a better representation of the points in their cluster; additionally, initialization procedures like K-means++ can lead to better clustering results in terms of lower SSE.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `grounded`
- scope_text: k-fold cross-validation can be used for model evaluation and model selection, including the selection of the best hyper-parameter value and the final classification model by making effective use of every data instance in the training set. Pre-processing operations, such as feature selection or hyper-parameter tuning, should be performed within the training fold of every run rather than using the entire data set to avoid selection bias.
- scope_supporting_evidence_ids: `['E2', 'E4']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_SIM_007 | Jaccard Coefficient

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `grounded`
- scope_text: The Jaccard coefficient is frequently used to handle objects consisting of asymmetric binary attributes.
- scope_supporting_evidence_ids: `['E5']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_006 | Information Gain

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: The information gain from a feature A, IG(A), is defined as the difference between the prior uncertainty and the expected posterior uncertainty using A.
- definition_supporting_evidence_ids: `['E2']`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
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

### KC_CLF_UND_005 | Mutually Exclusive Classes

- model_call_ok: `True`
- definition_status: `grounded`
- definition_text: A property of a rule set where an instance is not covered by more than one rule, preventing the prediction of conflicting classes.
- definition_supporting_evidence_ids: `['E3']`
- scope_status: `grounded`
- scope_text: A decision tree can be represented by a set of mutually exclusive and exhaustive rules; if a rule set is not mutually exclusive, multiple classification rules may predict conflicting classes for a single instance.
- scope_supporting_evidence_ids: `['E1', 'E2']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_HIER_005 | MAX (Complete Linkage)

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
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

### KC_CLU_SIM_003 | Euclidean Distance

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `grounded`
- scope_text: Euclidean distance can be used to measure the distance between entities based on attributes, such as measuring the distance between people based on age and income.
- scope_supporting_evidence_ids: `['E4']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_001 | Hunt's Algorithm

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `grounded`
- scope_text: In Hunt's algorithm, child nodes may be empty if no training instances possess the specific attribute values.
- scope_supporting_evidence_ids: `['E3']`
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

### KC_CLF_DT_004 | Gini Index

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- scope_status: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_KM_001 | K-Means Algorithm

- model_call_ok: `True`
- definition_status: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
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
