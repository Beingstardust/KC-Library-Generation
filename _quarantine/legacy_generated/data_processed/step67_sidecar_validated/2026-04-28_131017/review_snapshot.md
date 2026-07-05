# Step 6.7C one-pass validation snapshot

- Packets: `data/processed/step67_sidecar_packets/2026-04-28_130527/evidence_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_onepass_drafts/2026-04-28_130620/onepass_drafts.jsonl`
- Draft rows: `10`
- Valid rows: `3`
- Error rows: `7`
- Warning rows: `0`

## Status counter

```json
{
  "definition::": 7,
  "scope::": 7,
  "definition::abstained": 3,
  "scope::abstained": 3
}
```

## Issue counter

```json
{
  "ERROR::model_call_failed: empty visible model content": 7,
  "ERROR::parsed_output_missing_or_not_object": 7,
  "ERROR::kc_id_mismatch parsed=None expected='KC_CLU_EVAL_001'": 1,
  "ERROR::definition: field is not an object": 7,
  "ERROR::scope: field is not an object": 7,
  "ERROR::kc_id_mismatch parsed=None expected='KC_CLU_EVAL_002'": 1,
  "ERROR::kc_id_mismatch parsed=None expected='KC_DE_PREP_003'": 1,
  "ERROR::kc_id_mismatch parsed=None expected='KC_EVAL_SAMP_003'": 1,
  "ERROR::kc_id_mismatch parsed=None expected='KC_CLU_DBS_003'": 1,
  "ERROR::kc_id_mismatch parsed=None expected='KC_CLU_CORE_002'": 1,
  "ERROR::kc_id_mismatch parsed=None expected='KC_CLU_DBS_001'": 1
}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_CLU_EVAL_001'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_CLU_EVAL_002'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_DE_PREP_003 | Duplicate Tuples

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_DE_PREP_003'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_EVAL_SAMP_003'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_CLU_DBS_003'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_CLU_CORE_002 | Intra-cluster Distance

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_CLU_CORE_002'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `False`
- thinking_present: `False`
- thinking_char_count: `0`
- definition_status: ``
- definition_text: 
- scope_status: ``
- scope_text: 
- errors: `['model_call_failed: empty visible model content', 'parsed_output_missing_or_not_object', "kc_id_mismatch parsed=None expected='KC_CLU_DBS_001'", 'definition: field is not an object', 'scope: field is not an object']`
- warnings: `[]`

### KC_CLF_NB_011 | Handling Missing Values in NB

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `1486`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_012 | External Index: Recall

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `1140`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_005 | Specificity

- model_call_ok: `True`
- thinking_present: `True`
- thinking_char_count: `698`
- definition_status: `abstained`
- definition_text: 
- scope_status: `abstained`
- scope_text: 
- errors: `[]`
- warnings: `[]`
