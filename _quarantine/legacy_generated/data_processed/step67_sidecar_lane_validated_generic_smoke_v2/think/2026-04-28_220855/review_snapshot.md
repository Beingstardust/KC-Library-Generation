# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_smoke_v2/think/2026-04-28_220233/onepass_drafts.jsonl`
- Draft rows: `5`
- Valid rows: `3`
- Error rows: `2`
- Warning rows: `1`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-28_220855",
  "created_utc": "2026-04-28T22:08:55.666264+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_smoke_v2/think/2026-04-28_220233/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_smoke_v2/think/2026-04-28_220855",
  "packet_count": 40,
  "draft_row_count": 5,
  "valid_row_count": 3,
  "error_row_count": 2,
  "warning_row_count": 1,
  "status_counter": {
    "definition::grounded": 2,
    "scope::grounded": 2,
    "definition::None": 2,
    "scope::None": 2,
    "definition::abstained": 1,
    "scope::abstained": 1
  },
  "mode_counter": {
    "definition::single_strong_context": 1,
    "scope::single_strong_context": 1,
    "definition::None": 2,
    "scope::None": 2,
    "definition::abstained": 1,
    "scope::abstained": 1,
    "definition::contextual_synthesis": 1,
    "scope::contextual_synthesis": 1
  },
  "issue_counter": {
    "WARNING::definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis": 1,
    "WARNING::scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis": 1,
    "ERROR::model call not ok: parsed output missing or not object": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_EVAL_002'": 1,
    "ERROR::definition: invalid status ''": 2,
    "ERROR::scope: invalid status ''": 2,
    "ERROR::model call not ok: empty visible model content": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_003'": 1
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

### KC_CLU_EVAL_001 | Internal Indices Overview

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Internal indices are unsupervised measures that rely exclusively on information present within the data set.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: These indices evaluate the quality of a clustering structure without external information and are categorized into measures of cluster cohesion (compactness and tightness) and cluster separation (isolation).
- scope_supporting_evidence_ids: `['E2']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `False`
- definition_status: `None`
- definition_grounding_mode: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `None`
- scope_grounding_mode: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `['model call not ok: parsed output missing or not object', "parsed kc_id mismatch parsed='' expected='KC_CLU_EVAL_002'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`

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
- definition_text: A model evaluation method used in supervised classification that aims to make effective use of all labeled instances for both training and testing.
- definition_supporting_evidence_ids: `['E5', 'E6']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Used for model assessment (evaluation) and model selection. Pre-processing operations, such as feature selection or hyper-parameter tuning, should be performed within the training fold of each run rather than on the entire dataset. In some configurations, an inner cross-validation framework is used for model selection while an outer framework is used for model evaluation.
- scope_supporting_evidence_ids: `['E4', 'E7']`
- scope_supporting_lanes: `['context_lane', 'scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_003 | Noise Point

- model_call_ok: `False`
- definition_status: `None`
- definition_grounding_mode: `None`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `None`
- scope_grounding_mode: `None`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `['model call not ok: empty visible model content', "parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_003'", "definition: invalid status ''", "scope: invalid status ''"]`
- warnings: `[]`
