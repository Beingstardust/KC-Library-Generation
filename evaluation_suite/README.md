# Evaluation Suite

This directory holds the statistical evaluation harness, the frozen reference data, and the exact provenance trail for every number reported in the paper — retrieval precision/recall/nDCG, claim-level groundedness, vital-nugget coverage, and the pairwise significance tests between drafting models.

## Where to start

**`paper_consolidation/PAPER_NUMBERS_SOURCE_OF_TRUTH.md`** (and its machine-readable twin, `PAPER_NUMBERS_SOURCE_OF_TRUTH.csv`) is the entry point: it maps every number that appears in the paper to the exact file and field it was computed from. If you're trying to trace a specific reported figure back to its source data, start there rather than searching the tree by hand.

## Layout

```
reference_eval/
  *.py            Builders, runners, and analyzers for the evaluation campaigns
  locks/          Frozen protocol documents — judge qualification thresholds,
                  pre-registered checks, and the amendments made to them, each
                  dated and reasoned
  output/         Frozen evaluation artifacts: per-claim judge verdicts (including
                  v3_crossed_groundedness.jsonl, the file behind the paper's
                  per-model / per-domain groundedness table and its pairwise
                  significance appendix), pooled retrieval relevance labels,
                  nugget/coverage scoring, and paired bootstrap confidence
                  intervals for every retrieval metric reported
  tests/          Tests for the evaluation code itself

reference_library/
  00_freeze/ .. 08_audits/   The reference-construction pipeline in order: freezing
                             the seed run, drafting a seed reference, human curation,
                             validation, the frozen gold KC library (04_gold/), the
                             independent seed-blind reconstruction audit
                             (05_seed_bias_audit/), the evaluation scaffold that turns
                             the gold library into scorable claims/nuggets, and the
                             methodology + audit documentation for the whole process

paper_consolidation/   Claim ledger, the paper-numbers source-of-truth table, the
                       research-question-to-evidence mapping, and threats-to-validity
                       documentation
paper_methods/         Standalone methodology writeups: how claims are evaluated,
                       how the LLM judge was validated against human labels, how
                       the extrinsic/intrinsic evaluation split works

statistics.py, schema.py, provenance.py, system_accounting.py, rubric_v3.py
                       Shared library code: the paired bootstrap / exact sign test
                       implementation, claim and evaluation-row schemas, provenance
                       tracking, and the grounding rubric used by the primary judge

EVALUATION_FINDINGS.md, KCL_EVALUATION_RECORD.html, PAPER_REFERENCES.md
                       Narrative findings log, a self-contained HTML evaluation
                       record, and the literature/methods adopted for evaluation
```

## Reproducing the paper's statistics

The frozen JSONL files under `reference_eval/output/` and the gold reference library under `reference_library/04_gold/` are the released intermediate data: they let you recompute every reported statistic (paired bootstrap confidence intervals, the Holm-corrected exact sign tests, vital-nugget recall) without needing to rerun the drafting pipeline or the LLM judges. `statistics.py` implements the bootstrap-CI and sign-test methodology used throughout the paper (10,000 resamples, unit-level pairing, Holm correction within each comparison family) and can be pointed at these files directly.

What is **not** included, and why: `reference_library/corpus_support/` originally held the source course PDFs and their full sentence-level extraction. Both are excluded here — the course materials are third-party copyrighted textbooks not licensed for redistribution (see the root `README.md`'s Data Availability section). The `evidence_store/` subdirectory *is* included, since it stores only content hashes and structural metadata (document, page, heading) rather than the underlying text.

The `human_final_approval.approved_by` field in the frozen gold reference library has been redacted to a generic placeholder; the original reviewer identity is not needed to interpret or reproduce any reported statistic.
