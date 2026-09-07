# KC Library: Source-Grounded Knowledge Component Construction

This repository accompanies the paper *"Constructing a Source-Grounded Knowledge Component Library from Course Materials"*, submitted to the 42nd ACM/SIGAPP Symposium on Applied Computing (SAC 2027), AIED track.

> **Review status.** This paper is currently under double-blind review. Author identity is withheld from this repository until the review process concludes; the license and citation files below will be updated with full author information at that point.

## What this is

Knowledge Components (KCs) describe the skills and concepts a course expects learners to acquire. Building a well-specified, course-wide KC inventory is normally slow and expert-heavy: relevant content is scattered across textbooks, slides, and problem sets, and the terms a curriculum uses rarely match the language of the source material.

This pipeline takes two inputs — a set of course PDFs, and a curriculum hierarchy that names the KCs and how they relate to each other — and produces a **KC Library**: for every curriculum target, a source-grounded definition, the passages that support it, provenance back to the original material, a support state (draftable / weak fallback / insufficient evidence), and a slot for expert review. The curriculum decides *which concepts must be considered and where they belong*; the corpus decides *what can be said about them and what evidence backs it up*. Machine-drafted entries are never treated as final — they carry their supporting evidence forward so a human reviewer can accept, edit, replace, or reject them.

The pipeline is deliberately model-agnostic and domain-agnostic in an architectural sense: the same code was run with three different open-weight drafting models (in the 27B–32B parameter range, served locally via Ollama) across three different course domains, without any model- or subject-specific branching in the pipeline itself. It does not assume access to a proprietary hosted LLM.

## Repository structure

```
v3/                   The generation pipeline. This is the system that produced the
  pipeline/           results reported in the paper.
                      Stages in execution order: 01 build profiles, 02 build KC packets
                      (retrieval + evidence assembly), 03 build topic packets, 04 draft
                      runner, 05 assemble/register, 06 sync registry
  jobs/               SLURM launchers, one per stage and drafting model
  verify/             Fix-liveness harness: asserts each reliability fix is not merely
                      present but actually firing, so a silently-inert fix fails the
                      build instead of passing
  evaluation/         Run comparison and audit tooling, including the budget-matched
                      DOS RAG packet builder used for the paper's sensitivity analysis
  comparators/        Comparator configurations

src/kc_l/             Library modules the pipeline imports — retrieval, evidence-pack
                      assembly, drafting hygiene and status integrity, review packets

steps/                The corpus-build chain that feeds v3: PDF ingest and block store,
                      doctree indexing, block-store cleanup, math salvage, structural
                      retrieval index, and the sentence overlay that produces the
                      sentence-level passage store. Also holds the retrieval-profile
                      stage and the three v2-lineage scripts v3 still calls directly
                      (the drafting schema probe, review postprocessing, and review
                      packet emission)

run_*.slurm           Launchers for the corpus-build chain above
configs/              Pipeline configuration, templated for a generic HPC/GPU deployment
tests/                Unit and integration tests for the retained modules
evaluation/           Auxiliary intrinsic metric scripts (entailment/factuality checks)
ablation_studies/     Controlled ablations referenced in the paper's analysis
vendor/dos-rag-eval/  The DOS RAG comparator baseline (third-party, MIT-licensed —
                      see vendor/dos-rag-eval/LICENSE)
docs/
  architecture/       System design notes
  audit_trail/        A dated log of reliability interventions made to the drafting and
                      evidence-repair stages, each entry paired with the measurement
                      that motivated it (A/B deltas, sabotage-style adversarial checks).
                      Kept for transparency about how the pipeline reached its current
                      behaviour, including the interventions that were tried and rejected.
  methodology/        Evidence-quality judging method and a defect log from development
  workflows/, examples/
evaluation_suite/     Statistical evaluation harness, frozen reference data, and the exact
                      files each number in the paper is sourced from — see its own README
```

## Setup

The package targets Python 3.12.

```bash
pip install -r requirements.txt
pip install -e .[runtime]      # pulls in torch/transformers/sentence-transformers for
                                # the retrieval and reranking models
```

For a lighter install without GPU-model dependencies (useful for reading/orchestration-only work), use `requirements-runtime-notorch.txt` in place of the `[runtime]` extra. `requirements-dev.txt` adds `pytest` and `ruff` for development.

Retrieval uses a `BM25` + pseudo-relevance-feedback lexical channel, a dense channel over `sentence-transformers`-served embeddings, and structural search; the final candidate pool is reranked with `BAAI/bge-reranker-v2-m3`. Drafting models are served locally through [Ollama](https://ollama.com/); no proprietary API-hosted model is used anywhere in the pipeline.

## Running the pipeline

There are two phases. First the corpus is built from source PDFs, using the `run_*.slurm` launchers at the repository root in numeric order (ingest → doctree index → block-store cleanup → math salvage → structural index → sentence overlay). That produces the sentence-level passage store the retrieval stage reads.

Then the generation pipeline runs from `v3/jobs/`:

```bash
sbatch v3/jobs/01_packets.sbatch                          # profiles + KC and topic packets
sbatch --dependency=afterok:<id> v3/jobs/02_draft_kc_qwen38.sbatch
sbatch --dependency=afterok:<id> v3/jobs/03_draft_topics.sbatch
sbatch --dependency=afterok:<id> v3/jobs/04_review_packets.sbatch
```

`01_packets.sbatch` runs `v3/verify/verify_pipeline_fixes.py` before building. That harness asserts on observed behaviour rather than on the presence of code, so a fix that exists but is doing nothing fails the build instead of passing silently.

`configs/` holds the pipeline configuration, templated for a generic SLURM/GPU deployment — replace the placeholder paths and partition/account values with your own cluster's before running at scale. `docs/architecture/` and `docs/workflows/` describe the stage sequence and configuration surface in more depth.

**On full reproducibility:** the evaluation reported in the paper was run on an institutional HPC cluster against course PDFs the authors do not have redistribution rights to (see Data Availability below). A single-command, fully automated rerun of the entire pipeline against the exact original data is therefore not possible from this repository alone. What *is* reproducible: the code itself, against your own course materials and compute; and the paper's reported statistics, against the frozen intermediate evaluation data released in `evaluation_suite/` (see that directory's README for exactly how each reported number is derived and how to recompute it).

## Data availability

The course materials used as source corpora in the paper's evaluation are third-party textbooks and educational resources, subject to their original licensing and copyright conditions. The source PDFs — and any derived full-text extraction of them — are therefore not included in this repository. This matches the Data Availability statement in the paper itself.

What *is* included under `evaluation_suite/`: the frozen, claim-level judge verdicts, retrieval relevance labels, coverage/nugget-recall data, and the human-adjudicated reference KC definitions used to compute the paper's reported statistics — none of which reproduce bulk source text from the underlying textbooks.

## License

Released under the MIT License (see `LICENSE`). The vendored DOS RAG comparator under `vendor/dos-rag-eval/` retains its own MIT license and attribution — see `NOTICE.md`.

## Citation

See `CITATION.cff`. A full citation with author information will be added once the double-blind review process concludes.
