# Seed Anchoring Audit -- Round 2 (authoritative)

Round 1 is superseded and retained at `SEED_ANCHORING_AUDIT.SUPERSEDED_ROUND1_20260902.md`.

## Why round 1 was redone

Two protocol failures, both found by inspection of the artifacts rather than reported at the time:

1. **The worksheet was issued pre-filled.** `reviewer_c_worksheet.jsonl` carried `reference_text`,
   `support_state` and `source_passages` for all 30 units, which section 2 of the protocol forbids.
   That file is in fact the completed OUTPUT, misfiled under the worksheet name -- its texts match
   the comparison file's `blind_words` exactly, and `independent_references/` was left empty.
2. **Every entry was far below the length floor.** The spec required 100-250 words; the 30
   submitted entries had a median of 22 and a maximum of 45. The comparison was therefore between
   a one-line gloss and a full paragraph, which makes the omission direction uninterpretable. The
   comparison script's own docstring recorded this limitation honestly at the time.

The reviewer also wrote definitions on the three sampled corpus-unsupported units against an
explicit instruction to decline, and the passages cited for them do not occur in the corpus.

## Round 2 design

- **Fresh sample.** 30 units drawn from the 129 the round-1 reviewer never saw, so the same person
  could serve again without loss of blindness. Stratified 18 ACCEPT / 9 CHANGED / 3 UNSUPPORTED,
  seed 20260819, order randomised.
- **Genuinely blank worksheet**, verified programmatically before issue.
- **Machine-checked submission.** `validate_reviewer_d_submission.py` enforces coverage, the word
  floor, support-state validity, provenance completeness, correct shape for declined units, and an
  8-gram overlap contamination check against the existing library. Round 1's data fails it (90
  problems, 0/30 within the word range); round 2 passes with no blocking problems.

## Round 2 submission

30 units: 25 SUPPORTED, 2 PARTIALLY_SUPPORTED, 3 UNSUPPORTED. 27 written entries, all within
100-250 words (median 164, range 144-186), each with recorded source passages. The three declined
units carry reasons and no text, as the protocol requires. Median length against the reference's
186 words gives a ratio of 0.86, against round 1's ~0.15.

## Round 2 comparison (blinded, order-randomised, Selene-1-Llama-3.3-70B)

26 substantive comparisons; 4 skipped because one side wrote no text.

| relationship | n | % of 26 |
|---|---:|---:|
| BOTH_VALID_DIFFERENT_FORMULATION | 13 | 50.0 |
| SUBSTANTIVELY_EQUIVALENT | 12 | 46.2 |
| SEEDED_MISSING_CONTENT | 1 | 3.8 |
| MATERIAL_SEMANTIC_DIFFERENCE | 0 | 0.0 |
| SEEDED_REFERENCE_EXTRA_UNSUPPORTED_CONTENT | 0 | 0.0 |

**25 of 26 (96.2%) show no content deficit in the seeded reference**, and no case of semantic
distortion or unsupported assertion. Because the two sides are now comparable in length, the
omission direction is interpretable in this round -- so the single `SEEDED_MISSING_CONTENT` result
is a measured outcome rather than an artifact of effort asymmetry.

## Corpus-support boundary (the four skipped units)

| unit | independent reviewer | reference | agreement |
|---|---|---|---|
| `KC_EVAL_COMP_005` Nemenyi Test | UNSUPPORTED | NO_REFERENCE_CORPUS_UNSUPPORTED | **confirms** |
| `KC_EVAL_BASIC_008` MAE for Ordinal Targets | UNSUPPORTED | NO_REFERENCE_CORPUS_UNSUPPORTED | **confirms** |
| `KC_EVAL_BASIC_009` Multi-class Confusion Matrix | PARTIALLY_SUPPORTED | NO_REFERENCE_CORPUS_UNSUPPORTED | contests |
| `KC_FSEL_GOOD_004` Spearman Rank Correlation | UNSUPPORTED | ACCEPT (reference written) | contests |

Two of the seven corpus-unsupported labels are now independently corroborated by someone who never
saw the reference, one of the seven is contested (`KC_EVAL_BASIC_009`), and **four remain untested**.
`KC_FSEL_GOOD_004` contests the boundary in the opposite direction but is an ACCEPT unit, not one
of the seven, so it must not be counted against that denominator. This is the first
independent evidence on that boundary: round 1 contradicted all three units it sampled, but its
judgements are not usable for the reasons above.

## What this audit still does not test

Whether the seed shaped *which* content is treated as essential, and provenance accuracy. Neither
is addressed by comparing written descriptions.

## Artifacts

```
reviewer_d_worksheet.jsonl                      blank worksheet as issued (regenerated post-submission)
reviewer_d_submission_as_delivered.jsonl        submission exactly as returned
independent_references/reviewer_d.jsonl         submission at the protocol path
comparison/seed_audit_round2.jsonl              blinded comparison output
REVIEWER_D_INSTRUCTIONS.md                      round-2 protocol
validate_reviewer_d_submission.py               submission validator
```
