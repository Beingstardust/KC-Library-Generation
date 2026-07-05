# Step 6.7C one-pass validation snapshot

- Packets: `data/processed/step67_sidecar_lane_packets_v4/2026-04-28_155759/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts/2026-04-28_160209/onepass_drafts.jsonl`
- Draft rows: `10`
- Valid rows: `4`
- Error rows: `6`
- Warning rows: `0`

## Status counter

```json
{
  "definition::grounded": 5,
  "scope::abstained": 7,
  "scope::grounded": 3,
  "definition::abstained": 5
}
```

## Issue counter

```json
{
  "ERROR::definition: invalid supporting evidence ids ['E2']": 3,
  "ERROR::scope: invalid supporting evidence ids ['E2', 'E3']": 1,
  "ERROR::scope: invalid supporting evidence ids ['E4']": 1,
  "ERROR::definition: invalid supporting evidence ids ['E3']": 1,
  "ERROR::scope: invalid supporting evidence ids ['E2', 'E4']": 1,
  "ERROR::definition: invalid supporting evidence ids ['E3', 'E4']": 1
}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `grounded`
- definition_text: Internal indices are unsupervised measures that use only information present in the data set.
- scope_status: `abstained`
- scope_text: 
- errors: `["definition: invalid supporting evidence ids ['E2']"]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `grounded`
- definition_text: Sum of the squared error (SSE), also known as scatter, is an objective function used to measure the quality of a clustering; it is calculated by computing the error of each data point (its Euclidean distance to the closest centroid) and then computing the total sum of the squared errors.
- scope_status: `grounded`
- scope_text: Lower SSE translates into noticeably better clustering results, and a smaller squared error indicates that the prototypes (centroids) of a clustering are a better representation of the points in their cluster.
- errors: `["definition: invalid supporting evidence ids ['E2']", "scope: invalid supporting evidence ids ['E2', 'E3']"]`
- warnings: `[]`

### KC_DE_PREP_003 | Duplicate Tuples

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `grounded`
- scope_text: Duplicate tuples can waste space and computing time for the DM algorithm and can be a source of inconsistency.
- errors: `["scope: invalid supporting evidence ids ['E4']"]`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `grounded`
- definition_text: A model evaluation method that aims to make effective use of all labeled instances in a dataset for both training and testing by randomly partitioning the set into equal-sized subsets; for each run, one subset is used for testing while the remaining subsets are used for training, with the overall test error rate calculated by summing errors across all runs and dividing by the total number of instances.
- scope_status: `grounded`
- scope_text: Cross-validation is used for model assessment (evaluation) and model selection, such as hyper-parameter selection, where it allows for the determination of the best hyper-parameter value and the final classification model by making effective use of every data instance in the training set.
- errors: `["definition: invalid supporting evidence ids ['E3']", "scope: invalid supporting evidence ids ['E2', 'E4']"]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `grounded`
- definition_text: Noise points are points that are not in a cluster.
- scope_status: `abstained`
- scope_text: 
- errors: `["definition: invalid supporting evidence ids ['E2']"]`
- warnings: `[]`

### KC_CLU_CORE_002 | Intra-cluster Distance

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `grounded`
- definition_text: In K-means clustering, intra-cluster dissimilarity is measured by the summation of distances between the objects and the centroid of the cluster they are assigned to.
- scope_status: `abstained`
- scope_text: 
- errors: `["definition: invalid supporting evidence ids ['E3', 'E4']"]`
- warnings: `[]`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_011 | Handling Missing Values in NB

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_012 | External Index: Recall

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_005 | Specificity

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`
