# Expert Reference KC Library: Construction Method

## What was built

A source-grounded, expert-curated reference library covering all 159 Data Mining knowledge components, curated by ONE reviewer and checked by an independent seed-blind reconstruction of 30 sampled units. It is the measurement instrument against which every frozen candidate system is evaluated. It is **not** a rival KC-generation pipeline.

## Construction protocol

```
freeze all candidate systems
        ↓
expert inspects ORIGINAL COURSE CORPUS first
        ↓
expert commits source-based judgment BEFORE seeing the machine draft
        ↓
machine draft revealed only as an editing scaffold
        ↓
expert accepts / edits / rewrites against the SOURCE CORPUS
        ↓
sentence/claim-level source provenance recorded
        ↓
explicit final human approval
        ↓
frozen expert-curated reference library
        ↓
independent seed-blind reconstruction of a 30-unit sample (separate check,
by a second person who saw no system output; NOT a review of the reviewer's
decisions and NOT a source of inter-rater agreement)
```

**One reviewer performed the curation above.** An earlier version of this document described an
"independent blind validation" and "adjudication of every disagreement" stage. That stage did not
happen; see `EXPERT_REFERENCE_ADJUDICATION_REPORT.md` for the correction and the evidence.

**Stage A (source-first).** For each KC the expert saw only the KC name and its position in the curriculum, searched the original course corpus with deterministic (non-LLM) tooling, and committed a source-support state, cited source passages, and a short memo — all before the machine draft was revealed. Stage A is hashed and timestamped at commit and is immutable thereafter; later corrections are recorded as separate, reasoned amendments that leave the original intact.

**Stage B/C (post-edit).** Only then was the frozen machine draft revealed, as an editing scaffold, with a standing instruction to write from the corpus rather than from the draft's wording and to preserve its text only where independently judged the clearest source-faithful representation. The expert chose one of `ACCEPT`, `MINOR_EDIT`, `MAJOR_EDIT`, `REPLACE`, `NO_REFERENCE_CORPUS_UNSUPPORTED`, with reason codes, and recorded source provenance for the final text.

Automated tooling assisted with file navigation, corpus search, citation bookkeeping, hashing, schema enforcement, and blind-review preparation. No automated component proposed a definition, a missing formula, a sibling concept, or an edit. Seed-hiding was enforced in code, not by convention: the seed store refused to return draft text for a KC whose Stage A was not yet committed.

## The authority

The original course corpus is the sole authority: four source PDFs decomposed into a 100,218-sentence corpus with stable per-sentence identifiers. Explicitly **not** authoritative: any system's retrieval evidence packet, or the machine seed itself.

This matters concretely. Had the expert been restricted to one system's retrieved evidence, that system's retrieval failures would have been baked into the reference and the evaluation would have been biased toward it. The union of all systems' evidence was likewise rejected as authority, because a competitor may retrieve plausible but wrong near-neighbour material.

## Outcome

| Action | n | % |
|---|---|---|
| ACCEPT | 117 | 73.58 |
| MAJOR_EDIT | 15 | 9.43 |
| MINOR_EDIT | 10 | 6.29 |
| REPLACE | 10 | 6.29 |
| NO_REFERENCE_CORPUS_UNSUPPORTED | 7 | 4.40 |

| Source support | n | % |
|---|---|---|
| SUPPORTED | 150 | 94.34 |
| PARTIALLY_SUPPORTED | 2 | 1.26 |
| UNSUPPORTED | 7 | 4.40 |

42/159 (26.42%) differ from the machine draft; 117 were accepted unchanged.

## Human review burden is a separate result

The ACCEPT rate measures **expert post-edit intervention burden for the seeded library**. It is not a cross-model accuracy score and must never be reported as one: no other system's output was ever offered to the expert for acceptance, so no other system could have earned an ACCEPT. It supports a claim of the form *"X% of machine drafts required no or only local expert intervention"* — evidence about the practical cost of turning a machine-generated library into an expert reference — and nothing stronger.

## Why this does not undermine the case for automation

Reference construction here is expensive, manual, expert-supervised, performed once for evaluation, and inspected KC-by-KC against source. Duan et al. (2026) describe traditional human KC construction and tagging as labor-intensive and rely on course instructors for KC-quality evaluation — precisely the cost the automated pipeline exists to avoid at scale. Building one 159-KC expert benchmark does not weaken the motivation for automation; it supplies the instrument needed to measure it.

The two questions stay operationally separate: reference construction answers *what does the course corpus support for this KC?*; evaluation answers *how well did each frozen automated system recover and express it?*

## Machine seeding: the validity position

Expert post-editing of machine output is an established data-construction methodology — Beemo (Artemova et al. 2025) is a benchmark of exactly that. But Beemo establishes only that the methodology is legitimate; it does not establish that seeded references are unbiased, and we do not cite it as if it did.

We therefore do **not** claim the reference is independent of the seeding model, and we do not claim seeding cannot bias it. The supportable position is:

> The reference was machine-seeded but subsequently subjected to source-grounded expert review by one reviewer, and to an independent seed-blind reconstruction of a 30-unit sample by a second person who saw no system output. There was no second review of the reviewer's own decisions, so no inter-rater agreement figure exists. The seed origin remains a potential anchoring threat, sized by the reconstruction audit and disclosed rather than ignored.

The seeding arm was identified empirically rather than assumed: exact-matching the reference's own `original_machine_draft_text` against all seven frozen candidate arms gave 159/159 matches for `intrinsic P-Q` and 17/159 for the next closest. See `THREATS_TO_VALIDITY.md` §1 for the full treatment, and `LLM_JUDGE_VALIDATION_METHOD.md` for the downstream controls that keep the seeding model from gaining a scoring advantage through wording.

## Finalization and freeze

The adjudicated artifact shipped with `human_final_approval_pending = true`. That flag was **not** flipped silently because a filename said "final". An explicit finalization step validated all 159 rows, displayed the adjudicated counts and the pre-approval SHA-256, required a typed acknowledgement, and wrote a **new** artifact — leaving the pre-approval file untouched. The transition changed metadata only; reference text, support state, review action, adjudication reason, reason codes and all source fields were copied byte-for-byte and re-verified after writing, with zero differences across all 159 rows. The approval receipt records the channel through which approval was obtained.

Freeze then hard-verified every count, confirmed no row still carried a pending flag, confirmed no unsupported row carried substantive text, confirmed every ACCEPT row exactly preserved its frozen original machine draft, and confirmed the candidate freeze manifest was unchanged. The frozen library, its manifest, the provenance resolution, and a lock recording all relevant hashes live in `reference_library/04_gold/`.

## Terminology

Use **"expert-curated reference KC library"**. Do NOT use "adjudicated" or "cross-reviewer-adjudicated": the curation was a single-reviewer task and no second review took place (see `EXPERT_REFERENCE_ADJUDICATION_REPORT.md`). The stored filename retains the older word for hash stability only. Avoid the unqualified phrase "ground truth".
