# Actual Corpus Step 5.3 Qwen 8B Rejection Note

Date: 2026-04-08

## Tested run
- run_id: 2026-04-08_090332
- model: /beegfs2/scratch/aryp26yc/kc_l/models/rerankers/tomaarsen__Qwen3-Reranker-8B-seq-cls
- device: cuda
- partition: gpu80GB

## Decision
- Rejected as accepted Step 5.3 baseline.

## Reason
Compared against accepted Qwen 4B run 2026-04-07_203250, the 8B run did not improve the outcome and regressed on key summary metrics.

## Keep as accepted baseline
- run_id: 2026-04-07_203250
- manifest: 2026-04-07_203250_step5_3_kc_evidence_recalibrated_set.json
