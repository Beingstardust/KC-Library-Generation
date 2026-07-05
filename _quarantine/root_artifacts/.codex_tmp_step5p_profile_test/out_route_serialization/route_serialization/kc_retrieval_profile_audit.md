# KC Retrieval Profile Builder Audit

## Summary

```json
{
  "profile_contract_version": "kc_retrieval_profile_v1",
  "run_id": "route_serialization",
  "created_at": "2026-05-13T16:23:36.589419+00:00",
  "inputs": {
    "registry_jsonl": "/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/.codex_tmp_step5p_profile_test/route_serialization_kc_registry.jsonl",
    "source_overlay_jsonl": "/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/.codex_tmp_step5p_profile_test/route_serialization_sentence_overlay.jsonl",
    "exact_kc_ids": [
      "KC_ROUTE_SERIALIZE"
    ],
    "limit_kcs": null,
    "base_profile_jsonl": "",
    "feedback_gap_jsonl": "",
    "feedback_round": 0
  },
  "counts": {
    "registry_kc_rows": 1,
    "selected_kc_rows": 1,
    "source_overlay_rows": 1,
    "profiles": 1,
    "completed_profiles": 1,
    "remaining_profiles": 0
  },
  "profile_status_counter": {
    "usable": 1
  },
  "profile_mode_counter": {
    "llm_policy_always": 1
  },
  "llm_policy_counter": {
    "always": 1
  },
  "llm_gate_status_counter": {
    "semantic_ambiguous_llm_allowed": 1
  },
  "profile_input_status_counter": {
    "strict_windows_available": 1
  },
  "llm_invocation_decision_counter": {
    "invoke": 1
  },
  "llm_skipped_reason_counter": {},
  "deterministic_profile_strength_band_counter": {
    "weak": 1
  },
  "validated_guidance_bucket_totals": {
    "source_observed": 0,
    "source_supported_near_target": 0,
    "model_suggested_unverified": 0,
    "rejected": 0
  },
  "accepted_cue_count_by_kc": {
    "KC_ROUTE_SERIALIZE": 0
  },
  "collection_validation": {
    "ok": true,
    "errors": [],
    "warnings": [],
    "row_count": 1,
    "unique_kc_count": 1
  },
  "active_pointer_policy": "do_not_update_active_pointer",
  "behavior": {
    "use_model": true,
    "llm_policy": "always",
    "max_snippets_per_kc": 4,
    "min_snippet_score": 1.0,
    "dynamic_broad_token_min_df": 12,
    "resume": false,
    "checkpoint_every": 1,
    "feedback_mode": false,
    "feedback_round": 0,
    "base_profile_count": 0,
    "gap_request_count": 0
  },
  "checkpointing": {
    "enabled": false,
    "final": true,
    "completed_kc_ids": [
      "KC_ROUTE_SERIALIZE"
    ],
    "remaining_kc_ids": [],
    "profile_jsonl": "/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/.codex_tmp_step5p_profile_test/out_route_serialization/route_serialization/kc_retrieval_profiles.jsonl",
    "checkpoint_json": "/beegfs1/home/aryp26yc/projects/kc_l_v2_clean/.codex_tmp_step5p_profile_test/out_route_serialization/route_serialization/kc_retrieval_profile_checkpoint.json"
  }
}
```

## Profile rows

### KC_ROUTE_SERIALIZE | Route Anchor

- status: `usable`
- profile_mode: `llm_policy_always`
- llm_invocation_decision: `invoke`
- accepted_source_cues: `0`
- source_supported_near_target_cues: `0`
- model_suggested_unverified_terms: `0`
- query_variants: `1`
- expected_evidence_shapes: `["context_phrase", "definitional_anchor", "fallback_surface_match"]`
- profile_input_status: `strict_windows_available`
- strict_source_windows: `1`
- exploratory_profile_windows: `0`
- candidate_snippets: `1`