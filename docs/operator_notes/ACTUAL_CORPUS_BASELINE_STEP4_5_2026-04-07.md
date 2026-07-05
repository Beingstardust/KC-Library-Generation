# Actual Corpus Step 4.5 Accepted Baseline

Accepted on: 2026-04-07

## Active inputs
- ACTIVE_STEP4_SET:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt
- ACTIVE_STEP4_5_SET:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SET.txt

## Active manifests
- Step 4 index:
  2026-04-07_000855_step4_3_1_step4_index_set.json
- Step 4.5 sentence overlay:
  2026-04-07_104900_step4_5_sentence_set.json

## Accepted Step 4.5 processed baseline
- run_id: 2026-04-07_104900
- processed dir:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/2026-04-07_104900
- audit dir:
  /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/data/runs/2026-04-07_104900_step4_5

## Repository state
- The canonical runner file `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py` was accidentally reduced to an empty file during debugging.
- The canonical runner has now been restored from backup and must remain non-empty and compilable.
- The frozen Step 4.5 set is the accepted actual-corpus baseline for downstream stages.
- Downstream stages should consume `ACTIVE_STEP4_5_SET.txt`.
- Re-running Step 4.5 is not required for immediate continuation, but the restored canonical runner should be preserved for repo integrity and future reproducibility checks.

## Core artifacts
- sentence_corpus.jsonl
- sentence_stats.json
- frozen Step 4.5 set json:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/_sets/2026-04-07_104900_step4_5_sentence_set.json
- active pointer:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SET.txt
