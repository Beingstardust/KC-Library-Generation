# Full144 evidence packet build audit

```json
{
  "stage": "step67_build_full144_evidence_packets_from_overlay",
  "created_utc": "2026-04-29T15:02:50.793169+00:00",
  "overlay_path": "data/processed/kc_drafting_input_overlay/2026-04-28_002730/candidate_sentence_overlay.jsonl",
  "out_dir": "data/processed/step67_sidecar_packets_full144/2026-04-29_150247",
  "evidence_packets_path": "data/processed/step67_sidecar_packets_full144/2026-04-29_150247/evidence_packets.jsonl",
  "overlay_row_count": 2592,
  "packet_count": 144,
  "row_count_distribution_per_kc": {
    "18": 144
  },
  "evidence_count_distribution": {
    "8": 144
  },
  "max_evidence_per_kc": 8,
  "missing_text_items": 0,
  "contract_policy": "deterministic_full144_overlay_to_evidence_packets_no_model_no_active_pointer",
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## First 20 packets

- `KC_CLF_DT_001` | Hunt's Algorithm | evidence=8 | source_rows=18
- `KC_CLF_DT_002` | Node Impurity | evidence=8 | source_rows=18
- `KC_CLF_DT_003` | Misclassification Rate | evidence=8 | source_rows=18
- `KC_CLF_DT_004` | Gini Index | evidence=8 | source_rows=18
- `KC_CLF_DT_005` | Entropy (Node) | evidence=8 | source_rows=18
- `KC_CLF_DT_006` | Information Gain | evidence=8 | source_rows=18
- `KC_CLF_DT_007` | Intrinsic Information | evidence=8 | source_rows=18
- `KC_CLF_DT_008` | Gain Ratio | evidence=8 | source_rows=18
- `KC_CLF_DT_009` | ID3 Algorithm | evidence=8 | source_rows=18
- `KC_CLF_DT_010` | Bushy Decision Tree (Multi-split) | evidence=8 | source_rows=18
- `KC_CLF_DT_011` | Binary Decision Tree | evidence=8 | source_rows=18
- `KC_CLF_DT_012` | Splitting Continuous Attributes | evidence=8 | source_rows=18
- `KC_CLF_NB_001` | Bayes' Theorem | evidence=8 | source_rows=18
- `KC_CLF_NB_002` | Prior Probability | evidence=8 | source_rows=18
- `KC_CLF_NB_003` | Conditional Probability (Likelihood) | evidence=8 | source_rows=18
- `KC_CLF_NB_004` | Naive Independence Assumption | evidence=8 | source_rows=18
- `KC_CLF_NB_005` | NB Learning Phase | evidence=8 | source_rows=18
- `KC_CLF_NB_006` | NB Classification Phase | evidence=8 | source_rows=18
- `KC_CLF_NB_007` | Zero-Frequency Problem | evidence=8 | source_rows=18
- `KC_CLF_NB_008` | Laplace Estimator | evidence=8 | source_rows=18