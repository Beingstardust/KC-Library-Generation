# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_smoke/think/2026-04-28_211218/onepass_drafts.jsonl`
- Draft rows: `5`
- Valid rows: `2`
- Error rows: `3`
- Warning rows: `0`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-28_211512",
  "created_utc": "2026-04-28T21:15:12.390746+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-04-28_204204/lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_smoke/think/2026-04-28_211218/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_smoke/think/2026-04-28_211512",
  "packet_count": 40,
  "draft_row_count": 5,
  "valid_row_count": 2,
  "error_row_count": 3,
  "warning_row_count": 0,
  "status_counter": {
    "definition::abstained": 2,
    "scope::abstained": 2,
    "definition::None": 3,
    "scope::None": 3
  },
  "mode_counter": {
    "definition::abstained": 2,
    "scope::abstained": 2,
    "definition::None": 3,
    "scope::None": 3
  },
  "issue_counter": {
    "ERROR::model call not ok: empty visible model content": 3,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_EVAL_002'": 1,
    "ERROR::definition: invalid status ''": 3,
    "ERROR::scope: invalid status ''": 3,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_EVAL_SAMP_003'": 1,
    "ERROR::parsed kc_id mismatch parsed='' expected='KC_CLU_DBS_003'": 1
  },
  "validation_policy": {
    "definition_direct": "direct_definition must cite at least one definition_lane id",
    "definition_contextual": "contextual_synthesis may cite definition, scope, or context ids, must cite at least two positive evidence ids, and must include scope/context support",
    "scope": "scope may cite definition, scope, or context ids; quarantine/sibling ids are errors",
    "abstained": "text, support ids, and supporting_lanes must be empty"
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Rows

### KC_CLU_EVAL_001 | Internal Indices Overview

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
- errors: `['model call not ok: empty visible model content', "parsed kc_id mismatch parsed='' expected='KC_CLU_EVAL_002'", "definition: invalid status ''", "scope: invalid status ''"]`
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
- errors: `['model call not ok: empty visible model content', "parsed kc_id mismatch parsed='' expected='KC_EVAL_SAMP_003'", "definition: invalid status ''", "scope: invalid status ''"]`
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
