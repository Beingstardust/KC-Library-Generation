# Step 6.7C one-pass validation snapshot

- Packets: `data/processed/step67_sidecar_packets/2026-04-28_130527/evidence_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_rescued_drafts/2026-04-28_152034/onepass_drafts.jsonl`
- Draft rows: `10`
- Valid rows: `10`
- Error rows: `0`
- Warning rows: `0`

## Status counter

```json
{
  "definition::grounded": 2,
  "scope::abstained": 5,
  "definition::abstained": 8,
  "scope::grounded": 5
}
```

## Issue counter

```json
{}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `3039`
- definition_status: `grounded`
- definition_text: Internal indices are unsupervised measures that rely exclusively on information contained within the data set.
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `grounded`
- scope_text: In K-means clustering, a smaller squared error indicates that cluster prototypes (centroids) better represent the points within their respective clusters.
- errors: `[]`
- warnings: `[]`

### KC_DE_PREP_003 | Duplicate Tuples

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `2014`
- definition_status: `abstained`
- definition_text: 
- scope_status: `grounded`
- scope_text: Duplicate tuples can cause inconsistency and waste computing time and space for data mining algorithms.
- errors: `[]`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `grounded`
- scope_text: Cross-validation is used for tasks such as hyper-parameter tuning and feature selection, which should be performed within the training fold of every run.
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `grounded`
- definition_text: Noise points are data points that are not part of a cluster.
- scope_status: `grounded`
- scope_text: Noise points are characterized by having a relatively large k-dist.
- errors: `[]`
- warnings: `[]`

### KC_CLU_CORE_002 | Intra-cluster Distance

- model_call_ok: `True`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: `abstained`
- definition_text: 
- scope_status: `grounded`
- scope_text: In K-means clustering, intra-cluster dissimilarity is calculated as the sum of distances between objects and their assigned cluster centroid.
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `2689`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_011 | Handling Missing Values in NB

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `1499`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_012 | External Index: Recall

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `1117`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_005 | Specificity

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `699`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`
