# KC Library Generation Pipeline v3

Drafts knowledge-component and topic definitions from a source corpus. Retrieval reads the corpus
and the knowledge registry, and nothing else - no profiling model runs at any point.

## Layout

    v3/
      pipeline/   the stages, numbered in execution order
      lib/        (modules live in ../src/kc_l/retrieval_gate: retrieval.py, evidence_pack.py)
      jobs/       sbatch scripts
      verify/     fix-liveness harness and draft validator
      logs/       job output
      docs/       architecture and methods write-ups

    data/v3/runs/<run_id>/
      profiles/kc_profiles.jsonl
      packets/kc_packets.jsonl        packets/topic_packets.jsonl
      drafts/kc_drafts.jsonl          drafts/topic_drafts.jsonl
      review/review_packets.jsonl

## Stages

| # | script | what it does |
|---|--------|--------------|
| 01 | `01_build_profiles.py` | Derives one profile row per unit from the registry. Five fields copied verbatim, one a pure string function. No model. |
| 02 | `02_build_kc_packets.py` | Retrieval and evidence assembly: BM25 + pseudo-relevance feedback + dense recall, cross-encoder admission, structural filtering, passage assembly. |
| 03 | `03_build_topic_packets.py` | Topic packets built from the evidence grounding their child units - not from the children's drafts, so errors cannot propagate upward. |
| 04 | `04_draft_runner.py` | Prompt construction and generation. Source-document pointers are neutralised before the packet is shown to the model. |
| 05 | postprocess | Normalises drafts into the review source and audits artifact leakage. |
| 06 | emit review packets | Produces the reviewable packets the console consumes. |

## Running

    sbatch v3/jobs/01_packets.sbatch                       # profiles + KC packets + topic packets
    sbatch --dependency=afterok:<id> v3/jobs/02_draft_kc_gemma4.sbatch
    sbatch --dependency=afterok:<id> v3/jobs/03_draft_topics.sbatch

`01_packets.sbatch` runs `verify/verify_pipeline_fixes.py` before building. That harness asserts
on observed behaviour, so a fix that is present but doing nothing fails the build rather than
passing silently - which has happened five times in this project's history.

## Naming note

Two inherited v2-lineage scripts hardcode their own output filenames
(`step67_v2_tiny_smoke_drafts.jsonl`, `step68_v2_review_packets.jsonl`). They carry repair loops
and validation worth keeping, so rather than fork them the jobs rename their output to the v3 name
immediately afterwards, and assert the rename happened.

## Console

    kcui      KC Library v3 console  (port 8503, reads this repository)
    kcuiold   the previous console   (port 8501, reads kc_l_v2_clean)
