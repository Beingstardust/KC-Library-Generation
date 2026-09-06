# Intrinsic Evaluation Method (drafter comparison)

## Question

Given the **same** retrieved evidence, which drafting model produces the most materially sound KC content?

## Design

Three arms, retrieval held fixed at the Proposed architecture:

| Arm | Drafter |
|---|---|
| `intrinsic P-Q` | Qwen3.8 27B |
| `intrinsic P-G` | Gemma4 31B |
| `intrinsic P-D` | DeepSeek R1 32B |

All three were built at the same pipeline commit (`6ebcd75`), under the same prompt mode, and read the **single shared packets file** — evidence identity holds by construction, not by post-hoc hash comparison of three separate files. Evidence equality and KC-set identity (159/159) are re-verified before scoring rather than assumed.

Because retrieval is identical across the three, differences are attributable primarily to drafting-model behavior.

## Primary outcome

`materially_sound` over the **150 fully supported KCs**:

```
materially_sound = draft_exists AND target_aligned
                   AND faithfulness_precision == 1.0
                   AND authority_correctness_precision == 1.0
                   AND core_complete
```

Aggregated KC-macro. Reported with Wilson 95% intervals, a Cochran Q omnibus, then pairwise exact McNemar with Holm correction inside the intrinsic family.

## Also reported

Faithfulness precision, authority-correctness precision, core completeness, target alignment, abstention rate, unsafe-draft rate, and `reference_claim_coverage` (descriptive). Continuous per-KC metrics are compared with a deterministic paired bootstrap (5,000 replicates), reporting mean difference, 95% interval, and win/tie/loss counts.

The 2 PARTIALLY_SUPPORTED and 7 UNSUPPORTED KCs are handled by their own questions and reported separately; they are not folded into the primary content measure.

## Seed-anchoring handling — specific to this experiment

**This is the experiment most exposed to the seed threat.** The expert reference was seeded from `intrinsic P-Q` — one of the three arms compared here — established empirically (159/159 exact draft matches, against 17/159 for the next closest arm).

Required treatment:

1. **Report the threat prominently**, in the results section itself and not only in limitations.
2. **No lexical similarity of any kind.** No BLEU, ROUGE, chrF, exact match, token overlap, edit distance, n-gram similarity, or embedding similarity to the reference — as primary or supporting ranking evidence. Surface comparison would hand the seeding arm a structural advantage unrelated to quality.
3. **Report per-arm seed-bias calibration diagnostics** (`VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE`, `POSSIBLE_REFERENCE_DEFECT`). If Gemma or DeepSeek is disproportionately flagged as containing valid source-supported content the reference happens not to mention, that materially qualifies any Qwen advantage and must be stated alongside the result.
4. **Never present the 117/159 ACCEPT count as the intrinsic result.** It is expert post-edit intervention burden for the seeded library. Gemma and DeepSeek were never offered to the expert for acceptance and could not have earned an ACCEPT. Reporting it as a drafter comparison would be a category error.

The `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` label carries much of the defensive weight here: it lets a Gemma or DeepSeek claim that is correct and corpus-supported, but absent from the seeded reference, count as materially correct instead of being scored wrong for not resembling the seed.

## The result this design must remain able to produce

Gemma or DeepSeek beating Qwen. The reference exists to measure the systems, not to justify one of them. If the blinded evidence shows a non-seeding drafter is stronger, that is the finding — and the seed threat makes such a finding *more* credible, not less, since the seeding arm had every structural advantage the design tried to remove.
