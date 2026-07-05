# Step 6.7 stratified 40-KC sidecar packet selection

## Summary

```json
{
  "stage": "step67_make_stratified_sidecar_packets40",
  "run_id": "2026-04-28_161958",
  "created_utc": "2026-04-28T16:19:58.995846+00:00",
  "overlay_path": "data/processed/kc_drafting_input_overlay/2026-04-28_002730/candidate_sentence_overlay.jsonl",
  "out_dir": "data/processed/step67_sidecar_packets_40/2026-04-28_161958",
  "packets_path": "data/processed/step67_sidecar_packets_40/2026-04-28_161958/evidence_packets.jsonl",
  "selection_rows_path": "data/processed/step67_sidecar_packets_40/2026-04-28_161958/selection_rows.jsonl",
  "overlay_row_count": 2592,
  "available_kc_count": 144,
  "selected_kc_count": 40,
  "evidence_per_kc": 8,
  "category_counter": {
    "smoke_seed": 10,
    "review_queue": 11,
    "contamination_risk": 39,
    "abbreviation": 9,
    "strong_clean": 9,
    "sparse_or_weak_definition_support": 4
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Selected KCs

- 01. `KC_CLU_EVAL_001` | Internal Indices Overview | topic=`Clustering` | review=True | strong_def=6 | high_contam=5 | abbrev=False
- 02. `KC_CLU_EVAL_002` | SSE (Cluster Quality) | topic=`Clustering` | review=False | strong_def=9 | high_contam=1 | abbrev=True
- 03. `KC_DE_PREP_003` | Duplicate Tuples | topic=`Data Engineering` | review=False | strong_def=3 | high_contam=3 | abbrev=False
- 04. `KC_EVAL_SAMP_003` | k-Fold Cross Validation | topic=`Model Evaluation and Model Comparison` | review=False | strong_def=3 | high_contam=2 | abbrev=False
- 05. `KC_CLU_DBS_003` | Noise Point | topic=`Clustering` | review=False | strong_def=8 | high_contam=1 | abbrev=True
- 06. `KC_CLU_CORE_002` | Intra-cluster Distance | topic=`Clustering` | review=False | strong_def=12 | high_contam=0 | abbrev=False
- 07. `KC_CLU_DBS_001` | Core Point | topic=`Clustering` | review=False | strong_def=1 | high_contam=2 | abbrev=True
- 08. `KC_CLF_NB_011` | Handling Missing Values in NB | topic=`Classification` | review=False | strong_def=12 | high_contam=1 | abbrev=True
- 09. `KC_CLU_EVAL_012` | External Index: Recall | topic=`Clustering` | review=True | strong_def=3 | high_contam=10 | abbrev=False
- 10. `KC_EVAL_BASIC_005` | Specificity | topic=`Model Evaluation and Model Comparison` | review=False | strong_def=8 | high_contam=2 | abbrev=False
- 11. `KC_CLF_UND_001` | Learning Phase | topic=`Classification` | review=True | strong_def=3 | high_contam=10 | abbrev=False
- 12. `KC_CLF_NB_008` | Laplace Estimator | topic=`Classification` | review=True | strong_def=2 | high_contam=9 | abbrev=False
- 13. `KC_CLF_DT_007` | Intrinsic Information | topic=`Classification` | review=True | strong_def=3 | high_contam=7 | abbrev=False
- 14. `KC_CLF_NB_004` | Naive Independence Assumption | topic=`Classification` | review=True | strong_def=6 | high_contam=3 | abbrev=False
- 15. `KC_CLU_EVAL_011` | External Index: Precision | topic=`Clustering` | review=True | strong_def=3 | high_contam=11 | abbrev=False
- 16. `KC_CLU_EVAL_006` | Models of Randomness (Approach 1) | topic=`Clustering` | review=True | strong_def=7 | high_contam=9 | abbrev=False
- 17. `KC_CLU_EVAL_007` | Models of Randomness (Approach 2) | topic=`Clustering` | review=True | strong_def=7 | high_contam=9 | abbrev=False
- 18. `KC_CLU_EVAL_009` | External Index: Purity | topic=`Clustering` | review=True | strong_def=5 | high_contam=9 | abbrev=False
- 19. `KC_CLF_UND_002` | Querying Phase | topic=`Classification` | review=False | strong_def=4 | high_contam=7 | abbrev=False
- 20. `KC_CLF_NB_007` | Zero-Frequency Problem | topic=`Classification` | review=False | strong_def=7 | high_contam=6 | abbrev=False
- 21. `KC_CLF_DT_001` | Hunt's Algorithm | topic=`Classification` | review=False | strong_def=4 | high_contam=6 | abbrev=False
- 22. `KC_CLF_DT_010` | Bushy Decision Tree (Multi-split) | topic=`Classification` | review=False | strong_def=3 | high_contam=6 | abbrev=False
- 23. `KC_CLF_UND_005` | Mutually Exclusive Classes | topic=`Classification` | review=False | strong_def=7 | high_contam=5 | abbrev=False
- 24. `KC_CLF_DT_009` | ID3 Algorithm | topic=`Classification` | review=False | strong_def=6 | high_contam=5 | abbrev=False
- 25. `KC_CLF_UND_004` | Representative Training Sample | topic=`Classification` | review=False | strong_def=8 | high_contam=4 | abbrev=False
- 26. `KC_CLF_NB_001` | Bayes' Theorem | topic=`Classification` | review=False | strong_def=5 | high_contam=4 | abbrev=False
- 27. `KC_CLF_NB_006` | NB Classification Phase | topic=`Classification` | review=False | strong_def=10 | high_contam=1 | abbrev=True
- 28. `KC_CLF_NB_009` | NB for Numerical Attributes (Gaussian NB) | topic=`Classification` | review=False | strong_def=14 | high_contam=0 | abbrev=True
- 29. `KC_CLF_NB_005` | NB Learning Phase | topic=`Classification` | review=False | strong_def=7 | high_contam=0 | abbrev=True
- 30. `KC_CLU_DBS_009` | DBSCAN Advantages and Limitations | topic=`Clustering` | review=True | strong_def=14 | high_contam=3 | abbrev=True
- 31. `KC_CLU_HIER_005` | MAX (Complete Linkage) | topic=`Clustering` | review=False | strong_def=8 | high_contam=5 | abbrev=True
- 32. `KC_CLF_DT_006` | Information Gain | topic=`Classification` | review=False | strong_def=0 | high_contam=2 | abbrev=False
- 33. `KC_CLU_SIM_007` | Jaccard Coefficient | topic=`Clustering` | review=False | strong_def=0 | high_contam=1 | abbrev=False
- 34. `KC_EVAL_BASIC_001` | Confusion Matrix | topic=`Model Evaluation and Model Comparison` | review=False | strong_def=1 | high_contam=0 | abbrev=False
- 35. `KC_CLF_UND_003` | Training Set vs. Test Set Split | topic=`Classification` | review=False | strong_def=15 | high_contam=0 | abbrev=False
- 36. `KC_CLF_DT_004` | Gini Index | topic=`Classification` | review=False | strong_def=12 | high_contam=0 | abbrev=False
- 37. `KC_CLF_NB_003` | Conditional Probability (Likelihood) | topic=`Classification` | review=False | strong_def=12 | high_contam=0 | abbrev=False
- 38. `KC_CLF_NB_002` | Prior Probability | topic=`Classification` | review=False | strong_def=10 | high_contam=0 | abbrev=False
- 39. `KC_CLU_KM_001` | K-Means Algorithm | topic=`Clustering` | review=False | strong_def=15 | high_contam=0 | abbrev=False
- 40. `KC_CLU_SIM_003` | Euclidean Distance | topic=`Clustering` | review=False | strong_def=13 | high_contam=0 | abbrev=False