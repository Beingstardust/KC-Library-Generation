# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_generic_lane_policy_v3_3_source_sense_replay/2026-04-29_123523/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_full40_v3_3/think/2026-04-29_142701/onepass_drafts.jsonl`
- Draft rows: `40`
- Valid rows: `40`
- Error rows: `0`
- Warning rows: `9`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-29_145350",
  "created_utc": "2026-04-29T14:53:50.860493+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_generic_lane_policy_v3_3_source_sense_replay/2026-04-29_123523/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_full40_v3_3/think/2026-04-29_142701/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_full40_v3_3/think/2026-04-29_145350",
  "packet_count": 40,
  "draft_row_count": 40,
  "valid_row_count": 40,
  "error_row_count": 0,
  "warning_row_count": 9,
  "status_counter": {
    "definition::grounded": 8,
    "scope::grounded": 12,
    "definition::abstained": 32,
    "scope::abstained": 28
  },
  "mode_counter": {
    "definition::single_strong_context": 3,
    "scope::single_strong_context": 4,
    "scope::contextual_synthesis": 7,
    "definition::abstained": 32,
    "scope::abstained": 28,
    "definition::contextual_synthesis": 3,
    "scope::direct_scope": 1,
    "definition::direct_definition": 2
  },
  "issue_counter": {
    "WARNING::definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis": 3,
    "WARNING::scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis": 4,
    "WARNING::scope: grounded only from context_lane": 3,
    "WARNING::scope: single_strong_context uses one definition_lane id; human review required because scope is inferred from definition-support evidence": 1
  },
  "validation_policy": {
    "definition_direct": "direct_definition must cite at least one definition_lane id",
    "definition_contextual": "contextual_synthesis may cite definition, scope, or context ids, must cite at least two positive evidence ids, and must include scope/context support",
    "definition_single_strong_context": "single_strong_context may cite exactly one strong scope or context id and should be human-reviewed",
    "scope": "scope may cite definition, scope, or context ids; quarantine/sibling ids are errors",
    "scope_single_strong_context": "single_strong_context may cite exactly one strong definition, scope, or context id and should be human-reviewed",
    "abstained": "text, support ids, and supporting_lanes must be empty"
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Internal indices are unsupervised measures that rely exclusively on information present within the data set.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: These indices evaluate the quality of a clustering structure without external information and are categorized into measures of cluster cohesion (compactness, tightness) and cluster separation (isolation).
- scope_supporting_evidence_ids: `['E2']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: The sum of the squared error (SSE), also known as scatter, is a measure of clustering quality calculated by summing the squared Euclidean distances from each data point to its closest centroid.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used as an objective function to measure clustering quality; a lower SSE indicates that the centroids are a better representation of the points in their cluster and translates to better clustering results.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

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
- definition_text: A model evaluation method that partitions a labeled set into equal-sized subsets to effectively use all labeled instances for both training and testing.
- definition_supporting_evidence_ids: `['E5', 'E3']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: This method evaluates models by calculating an overall test error rate, which is determined by summing the errors committed in each test subset across all runs and dividing by the total number of instances.
- scope_supporting_evidence_ids: `['E5', 'E3']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

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

### KC_CLU_CORE_002 | Intra-cluster Distance

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
- scope_grounding_mode: `single_strong_context`
- scope_text: In the DBSCAN algorithm, core points are placed in the same cluster if they are within a distance Eps of one another, and any border point close enough to a core point is also included in that core point's cluster.
- scope_supporting_evidence_ids: `['E7']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLF_NB_011 | Handling Missing Values in NB

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

### KC_CLU_EVAL_012 | External Index: Recall

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

### KC_EVAL_BASIC_005 | Specificity

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

### KC_CLF_UND_001 | Learning Phase

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

### KC_CLF_NB_008 | Laplace Estimator

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

### KC_CLF_DT_007 | Intrinsic Information

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

### KC_CLF_NB_004 | Naive Independence Assumption

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

### KC_CLU_EVAL_011 | External Index: Precision

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

### KC_CLU_EVAL_006 | Models of Randomness (Approach 1)

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

### KC_CLU_EVAL_007 | Models of Randomness (Approach 2)

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

### KC_CLU_EVAL_009 | External Index: Purity

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: A measure of the extent to which a cluster contains objects of a single class.
- definition_supporting_evidence_ids: `['E1']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_CLF_UND_002 | Querying Phase

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

### KC_CLF_NB_007 | Zero-Frequency Problem

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
- definition_text: Hunt's algorithm is used to fit training data by recursively splitting training instances based on attribute test conditions to create child nodes.
- definition_supporting_evidence_ids: `['E4', 'E5']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Child nodes created in Hunt's algorithm can be empty if no training instances have the particular attribute values.
- scope_supporting_evidence_ids: `['E3']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_010 | Bushy Decision Tree (Multi-split)

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

### KC_CLF_UND_005 | Mutually Exclusive Classes

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

### KC_CLF_DT_009 | ID3 Algorithm

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

### KC_CLF_UND_004 | Representative Training Sample

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

### KC_CLF_NB_001 | Bayes' Theorem

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

### KC_CLF_NB_006 | NB Classification Phase

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

### KC_CLF_NB_009 | NB for Numerical Attributes (Gaussian NB)

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

### KC_CLF_NB_005 | NB Learning Phase

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

### KC_CLU_DBS_009 | DBSCAN Advantages and Limitations

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

### KC_CLU_HIER_005 | MAX (Complete Linkage)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: In the MAX (complete linkage) version of hierarchical clustering, the proximity of two clusters is defined as the maximum distance (or minimum similarity) between any two points in the two different clusters.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: Complete linkage favors globular shapes and is less susceptible to noise and outliers, though it can break large clusters.
- scope_supporting_evidence_ids: `['E2']`
- scope_supporting_lanes: `['definition_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context uses one definition_lane id; human review required because scope is inferred from definition-support evidence', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLF_DT_006 | Information Gain

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: In the context of FOIL, information gain is used to determine which candidate conjunct is chosen to extend a rule.
- scope_supporting_evidence_ids: `['E1', 'E3']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_CLU_SIM_007 | Jaccard Coefficient

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: The Jaccard coefficient is frequently used to handle objects consisting of asymmetric binary attributes.
- scope_supporting_evidence_ids: `['E5']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

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

### KC_CLF_UND_003 | Training Set vs. Test Set Split

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

### KC_CLF_DT_004 | Gini Index

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The Gini index is computed at candidate split positions to identify the best split position, which is the one that produces the lowest Gini index value.
- scope_supporting_evidence_ids: `['E6', 'E8']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

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

### KC_CLF_NB_002 | Prior Probability

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Prior probability can be used as an estimate of the posterior probability when no attributes are observed and is combined with observed outcomes via Bayes theorem to make predictions. Additionally, if there are no parents, the table contains only the prior probability.
- scope_supporting_evidence_ids: `['E3', 'E4', 'E6']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_KM_001 | K-Means Algorithm

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: The K-means algorithm is a clustering approach equivalent to a statistical mixture model and, for Euclidean data, a special case of the EM algorithm; it assumes clusters are spherical Gaussian distributions with different means and equal covariance matrices.
- definition_supporting_evidence_ids: `['E1', 'E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The algorithm is used to find clusters in sample data, including Euclidean data.
- scope_supporting_evidence_ids: `['E8', 'E2']`
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
