# Actual Corpus Step 5.3 Accepted Baseline

Accepted on: 2026-04-07

## Accepted active pointer
- /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt

## Accepted manifest
- 2026-04-07_203250_step5_3_kc_evidence_recalibrated_set.json

## Accepted processed baseline
- run_id: 2026-04-07_203250
- processed dir: data/processed/kc_evidence_recalibrated/2026-04-07_203250
- audit dir: data/runs/2026-04-07_203250_step5_3

## Reranker
- model: /beegfs2/scratch/aryp26yc/kc_l/models/rerankers/tomaarsen__Qwen3-Reranker-4B-seq-cls
- device: cuda
- used_fallback: false

## Summary
- n_kcs_total: 144
- median_same_topic_fraction: 0.4444
- baseline_median_same_topic_fraction: 0.1111
- median_same_topic_fraction_lift: 0.3333
- median_same_topic_fraction_relative_lift: 3.0000
- kcs_with_at_least_2_strong_candidates: 125
- kcs_with_at_least_2_structured_candidates: 124
- high_risk_audit_candidates: 2
- review_queue_count: 20
- acceptance_passed: true

## Comparison note
- Earlier fallback run 2026-04-07_195513_step5_3 used BAAI/bge-reranker-v2-m3 on cuda.
- The Qwen run dominated the BGE run on summary metrics and is the accepted Step 5.3 actual-corpus baseline.

## Scope note
- This acceptance is for the Step 5.3 recalibrated evidence baseline.
- It does not by itself certify downstream Step 6 readiness.
