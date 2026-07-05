# Actual Corpus Baseline State After Step 4.5

## Accepted active pointers
- Step 4:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt
- Step 4.5:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SET.txt

## Accepted manifests
- Step 4:
  2026-04-07_000855_step4_3_1_step4_index_set.json
- Step 4.5:
  2026-04-07_104900_step4_5_sentence_set.json

## Accepted processed roots
- Step 4:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index
- Step 4.5:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_sentence_overlay

## Important note
- The accepted Step 4.5 baseline is frozen from verified existing processed output.
- The canonical Step 4.5 runner must remain restored and compilable for repo integrity.
- Downstream stages should consume the frozen active Step 4.5 set rather than rely on a fresh rerun.
