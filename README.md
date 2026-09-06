# KC Library: Source-Grounded Knowledge Component Construction

This repository accompanies the paper *"Constructing a Source-Grounded Knowledge Component Library from Course Materials"*, submitted to the 42nd ACM/SIGAPP Symposium on Applied Computing (SAC 2027), AIED track.

> **Review status.** This paper is currently under double-blind review. Author identity is withheld from this repository until the review process concludes; the license and citation files below will be updated with full author information at that point.

## What this is

Knowledge Components (KCs) describe the skills and concepts a course expects learners to acquire. Building a well-specified, course-wide KC inventory is normally slow and expert-heavy: relevant content is scattered across textbooks, slides, and problem sets, and the terms a curriculum uses rarely match the language of the source material.

This pipeline takes two inputs — a set of course PDFs, and a curriculum hierarchy that names the KCs and how they relate to each other — and produces a **KC Library**: for every curriculum target, a source-grounded definition, the passages that support it, provenance back to the original material, a support state (draftable / weak fallback / insufficient evidence), and a slot for expert review. The curriculum decides *which concepts must be considered and where they belong*; the corpus decides *what can be said about them and what evidence backs it up*. Machine-drafted entries are never treated as final — they carry their supporting evidence forward so a human reviewer can accept, edit, replace, or reject them.

The pipeline is deliberately model-agnostic and domain-agnostic in an architectural sense: the same code was run with three different open-weight drafting models (in the 27B–32B parameter range, served locally via Ollama) across three different course domains, without any model- or subject-specific branching in the pipeline itself. It does not assume access to a proprietary hosted LLM.

## Repository structure

```
src/kc_l/            Core pipeline package (retrieval, evidence selection, evidence pack
                      assembly, drafting interface, review-packet emission)
steps/                Numbered pipeline stages as run on the evaluation HPC deployment,
                      each with its own scripts/, config resources, and output slot
scripts/              Orchestration entry points (scripts/kc_l_orchestrator.py) and
                      maintenance/verification utilities
configs/              Pipeline configuration, templated for a generic HPC/GPU deployment
tests/                Unit and integration tests
evaluation/           Auxiliary intrinsic metric scripts (entailment/factuality checks)
ablation_studies/     Controlled ablations referenced in the paper's analysis
vendor/dos-rag-eval/  The DOS RAG comparator baseline (third-party, MIT-licensed —
                      see vendor/dos-rag-eval/LICENSE)
docs/
  architecture/       System design notes
  audit_trail/        A dated log of reliability interventions made to the drafting and
                      evidence-repair stages after the paper's primary evaluation, each
                      entry paired with the measurement that motivated it (A/B deltas,
                      sabotage-style adversarial checks). Kept for transparency about how
                      the shipped pipeline reached its current behaviour.
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

The pipeline is organized as a sequence of numbered stages under `steps/`, each independently runnable and orchestrated end-to-end by `scripts/kc_l_orchestrator.py`. `configs/` holds the pipeline configuration, templated for a generic SLURM/GPU deployment — replace the placeholder paths and partition/account values with your own cluster's before running at scale. `docs/architecture/` and `docs/workflows/` describe the stage sequence and configuration surface in more depth.

**On full reproducibility:** the evaluation reported in the paper was run on an institutional HPC cluster against course PDFs the authors do not have redistribution rights to (see Data Availability below). A single-command, fully automated rerun of the entire pipeline against the exact original data is therefore not possible from this repository alone. What *is* reproducible: the code itself, against your own course materials and compute; and the paper's reported statistics, against the frozen intermediate evaluation data released in `evaluation_suite/` (see that directory's README for exactly how each reported number is derived and how to recompute it).

## Data availability

The course materials used as source corpora in the paper's evaluation are third-party textbooks and educational resources, subject to their original licensing and copyright conditions. The source PDFs — and any derived full-text extraction of them — are therefore not included in this repository. This matches the Data Availability statement in the paper itself.

What *is* included under `evaluation_suite/`: the frozen, claim-level judge verdicts, retrieval relevance labels, coverage/nugget-recall data, and the human-adjudicated reference KC definitions used to compute the paper's reported statistics — none of which reproduce bulk source text from the underlying textbooks.

## License

Released under the MIT License (see `LICENSE`). The vendored DOS RAG comparator under `vendor/dos-rag-eval/` retains its own MIT license and attribution — see `NOTICE.md`.

## Citation

See `CITATION.cff`. A full citation with author information will be added once the double-blind review process concludes.
