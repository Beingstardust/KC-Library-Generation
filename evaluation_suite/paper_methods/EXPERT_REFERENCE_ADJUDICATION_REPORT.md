# Expert Reference Review Report

> **CORRECTION, 2026-09-02.** This document previously reported a two-reviewer cross-review with
> 81.13% inter-rater agreement (129/159), 30 action disagreements adjudicated 15/15, and 18
> support-state disagreements adjudicated 14/4. **That cross-review did not take place.** The
> reference library was curated by **one** reviewer. No second reviewer ever assigned edit actions
> or support states, so no inter-rater agreement statistic exists for this task and none is
> reported here or in the manuscript.
>
> The superseded text is retained verbatim at
> `EXPERT_REFERENCE_ADJUDICATION_REPORT.SUPERSEDED_20260902.md` rather than deleted, so the
> correction is auditable.

## What actually happened

One expert reviewer assessed all 159 Data Mining curriculum units from the Proposed-Qwen
reference-seeding run, working against the course corpus. For each unit the reviewer recorded an
edit action, a source-support state, the final reference text, and the source passages supporting
it.

A second person contributed later, in a different role: they wrote **independent reference
descriptions for a sample of 30 units** from the corpus alone, without sight of any system output
or of the existing library. That is the seed-blind reconstruction audit (`05_seed_bias_audit/`),
not a review of the reviewer's decisions.

## Review outcome (single reviewer, verified against the frozen library)

| Action | n | % |
|---|---:|---:|
| ACCEPT | 117 | 73.58 |
| MAJOR_EDIT | 15 | 9.43 |
| MINOR_EDIT | 10 | 6.29 |
| REPLACE | 10 | 6.29 |
| NO_REFERENCE_CORPUS_UNSUPPORTED | 7 | 4.40 |

| Source support | n | % |
|---|---:|---:|
| SUPPORTED | 150 | 94.34 |
| PARTIALLY_SUPPORTED | 2 | 1.26 |
| UNSUPPORTED | 7 | 4.40 |

117 entries are byte-identical to their machine seed; 42 differ. These counts were recomputed
directly from `04_gold/expert_adjudicated_reference_kc_library.jsonl` and match.

## How the error arose, and how it was found

The frozen library carries an `adjudication_reason` field on all 159 rows. On the 42 rows whose
text differs from the machine seed it holds a substantive rationale; on the other 117 it holds a
single identical generated string, `"Both reviewers agreed; no adjudication change required."`
That boilerplate was **generated**, not recorded from a second reviewer.

`kc_reviewer_adjudication.md` records paired `mine | other | adjudicated` positions for 42 units.
Recomputed from it, the 30/18 split and the 15/15 and 14/4 outcomes are arithmetically correct —
but they describe only those 42 units, and the "other" column did not come from a second human
reviewer. The 129/159 figure was never observed; it is `159 − 30`.

The discrepancy surfaced when the author's own recollection (one reviewer for all 159; a second
person who wrote 30 definitions near the end) was checked against the artifacts:
`03_validation/reviewer_b/` is empty, as are `03_validation/adjudications/` and
`02_curation/{committed,amendments,logs,work}/`.

## Terminology consequence

"Adjudicated" presupposes two parties and is no longer used for this artifact. The library is an
**expert-curated, seed-blind-audited reference KC library**. The stored filename
`expert_adjudicated_reference_kc_library.jsonl` is retained unchanged so that hashes and the freeze
lock stay valid; the name is historical and does not license the claim.

## What the reference still supports

- A single-reviewer, source-grounded curation of all 159 units, with per-unit provenance: 980
  source citations, every one resolving to a document, page and sentence.
- 117/159 machine drafts requiring no edit and 127/159 requiring at most minor editing — an
  editing-burden result, not a model-accuracy result, and not a cross-model comparison.
- An independent seed-blind reconstruction of 30 sampled units as the one external human check on
  the reference. See `05_seed_bias_audit/SEED_ANCHORING_AUDIT.md`.

## What it does not support

- Any inter-rater agreement or reliability figure for the curation task.
- Any claim of independent validation of the reviewer's individual edit actions or support states.
- Treating the corpus-support boundary (the 7 UNSUPPORTED units) as independently confirmed. Three
  of those seven were re-checked directly against the corpus and the original label held; the other
  four rest on the single reviewer's judgement.
