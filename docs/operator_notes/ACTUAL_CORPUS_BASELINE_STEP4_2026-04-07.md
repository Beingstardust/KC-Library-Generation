# Actual Corpus Step 4 Accepted Baseline

Accepted on: 2026-04-07

## Active inputs
- ACTIVE_STEP3_SET:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/doctree/_sets/ACTIVE_STEP3_SET.txt
- ACTIVE_STEP3_6_SET:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/blockstore_math_salvaged/_sets/ACTIVE_STEP3_6_SET.txt
- ACTIVE_STEP4_PATCHES_SET:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index/_sets/ACTIVE_STEP4_PATCHES_SET.txt
- ACTIVE_STEP4_SET:
  /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt

## Active manifests
- Step 3:
  2026-04-06_191410_step3_step3_set.json
- Step 3.6:
  2026-04-06_211652_step3_6_step3_6_set.json
- Step 4 patches:
  2026-04-06_220031_step4_step4_patches_set.json
- Step 4 index:
  2026-04-07_000855_step4_3_1_step4_index_set.json

## Accepted Step 4.3 run
- run_id: 2026-04-07_000855_step4_3_1
- run_dir:
  /beegfs1/home/aryp26yc/projects/kc_l_v2_clean/data/runs/2026-04-07_000855_step4_3_1

## Processed output root
- /beegfs2/scratch/aryp26yc/kc_l/data/processed/retrieval_index

## Embedding/runtime facts
- embedding model used: qwen3-embedding:8b
- vector backend used: matrix_exact_ip
- faiss unavailable in this successful run
- Ollama ran locally on GPU node and completed successfully

## Notes
- Actual-corpus Step 4 patches and Step 4.3 index are frozen and validated.
- Custom actual-corpus freeze/validate scripts were used because legacy freeze scripts assumed the old manifest structure.
- Heavy processed artifacts live on scratch. Audit and code live in the repo/home side.
