# Step 6.7 V8 lane-positive 20 selection

## Summary

```json
{
  "stage": "step67_make_lane_positive20_from_v8_40",
  "source_lanes_path": "data/processed/step67_sidecar_lane_packets_v8_40/2026-04-28_171241/lane_packets.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_packets_v8_40_lanepositive20/2026-04-28_171714",
  "lane_packets_path": "data/processed/step67_sidecar_lane_packets_v8_40_lanepositive20/2026-04-28_171714/lane_packets.jsonl",
  "source_row_count": 40,
  "lane_positive_available_count": 20,
  "selected_count": 20,
  "pattern_counter": {
    "d1_s1_c1": 4,
    "d1_s0_c1": 3,
    "d1_s1_c0": 1,
    "d0_s1_c1": 3,
    "d1_s0_c0": 3,
    "d0_s1_c0": 1,
    "d0_s0_c1": 5
  },
  "selection_policy": "prefer usable non-quarantine lane coverage, then definition/scope/context density, then fewer quarantine items",
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Selected KCs

- 01. `KC_EVAL_BASIC_001` | Confusion Matrix | d=2 s=3 c=1 q=2
- 02. `KC_CLU_EVAL_002` | SSE (Cluster Quality) | d=2 s=1 c=1 q=4
- 03. `KC_EVAL_SAMP_003` | k-Fold Cross Validation | d=1 s=2 c=3 q=2
- 04. `KC_CLU_SIM_007` | Jaccard Coefficient | d=1 s=1 c=3 q=1
- 05. `KC_CLF_DT_006` | Information Gain | d=2 s=0 c=3 q=0
- 06. `KC_CLU_DBS_003` | Noise Point | d=2 s=0 c=2 q=3
- 07. `KC_CLF_UND_005` | Mutually Exclusive Classes | d=1 s=2 c=0 q=5
- 08. `KC_CLU_HIER_005` | MAX (Complete Linkage) | d=1 s=0 c=2 q=5
- 09. `KC_CLF_NB_002` | Prior Probability | d=0 s=2 c=3 q=3
- 10. `KC_CLU_SIM_003` | Euclidean Distance | d=0 s=1 c=3 q=0
- 11. `KC_CLF_DT_001` | Hunt's Algorithm | d=0 s=1 c=3 q=3
- 12. `KC_CLU_CORE_002` | Intra-cluster Distance | d=2 s=0 c=0 q=5
- 13. `KC_CLF_NB_003` | Conditional Probability (Likelihood) | d=1 s=0 c=0 q=7
- 14. `KC_CLU_EVAL_001` | Internal Indices Overview | d=1 s=0 c=0 q=7
- 15. `KC_CLU_EVAL_009` | External Index: Purity | d=0 s=1 c=0 q=7
- 16. `KC_CLF_DT_004` | Gini Index | d=0 s=0 c=3 q=0
- 17. `KC_CLU_KM_001` | K-Means Algorithm | d=0 s=0 c=3 q=1
- 18. `KC_CLU_DBS_001` | Core Point | d=0 s=0 c=3 q=5
- 19. `KC_CLF_DT_010` | Bushy Decision Tree (Multi-split) | d=0 s=0 c=1 q=7
- 20. `KC_CLF_NB_001` | Bayes' Theorem | d=0 s=0 c=1 q=7