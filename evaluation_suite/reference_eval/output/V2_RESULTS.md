# v2 evaluation results (final)

Generated 2026-08-31T23:14:52Z · **single instrument**: Cluster A ant2, 4xH100, TP4, CUDA 13 - single instrument, zero deviation

> Metrics are grounded in published constructs: per-claim faithfulness is the RAGAS supported/total ratio [R-01]; vital-nugget recall follows TREC RAG nugget evaluation [R-03,R-04]; context recall/precision are the RAGAS retrieval constructs [R-01].

> **F-45 — read the context-recall column with care.** The judge recovers only **0.5905** of nuggets that are *provably present* when the evidence set holds 123 passages, against **1.0000** at 17 (serial-position failure, not truncation). Context recall is therefore **not comparable across arms with different retrieval budgets**, and comparisons against BaseDense (123.1 passages) are flagged as confounded below. Nugget recall is judged against the **draft** and is immune.

## Summary by arm

| arm | evidence items | context recall | nugget recall | faithfulness | abstention | mean claims |
|---|---|---|---|---|---|---|
| intrinsic_P-Q | 17.2 | 0.7083 | 0.8532 | 0.952 | 0.0464 | 8.92 |
| extrinsic_P-Q | 17.2 | 0.7083 | 0.8193 | 0.9533 | 0.053 | 8.87 |
| intrinsic_P-G | 17.2 | 0.7083 | 0.7472 | 0.968 | 0.0265 | 7.72 |
| extrinsic_DOS-Q | 33.7 | 0.6978 | 0.7369 | 0.9801 | 0.0199 | 8.53 |
| intrinsic_P-D | 17.2 | 0.7083 | 0.6726 | 0.8249 | 0.0265 | 5.85 |
| sensitivity_DOS-Q_matched | 11.6 | 0.4657 | 0.5671 | 0.9289 | 0.0795 | 6.87 |
| extrinsic_B-Q | 123.1 | 0.4664 | 0.5654 | 0.936 | 0.0464 | 7.21 |

*Scored on 151/159 KCs. 7 KCs have no expert reference and 1 fails decomposition; all 8 drop identically for every arm, so paired comparisons stay balanced.*


## Abstention behaviour (all 1113 rows, no exclusions)

**Forced** = retrieval returned nothing, so declining to draft is the only correct move. **Chosen** = evidence was available and the drafter still declined. The last column is the failure mode that would matter most: asserting a description with no evidence behind it.

| arm | rows | forced abstention | chosen abstention | drafted with ZERO evidence |
|---|---|---|---|---|
| extrinsic_B-Q | 159 | 0 | 12 | **0** |
| extrinsic_DOS-Q | 159 | 0 | 5 | **0** |
| extrinsic_P-Q | 159 | 4 | 11 | **0** |
| intrinsic_P-D | 159 | 4 | 6 | **0** |
| intrinsic_P-G | 159 | 4 | 6 | **0** |
| intrinsic_P-Q | 159 | 4 | 10 | **0** |
| sensitivity_DOS-Q_matched | 159 | 7 | 10 | **0** |

Across every arm and all 1113 rows, **no draft was ever produced from an empty evidence set**: every zero-evidence row abstained. Evidence-grounded abstention is a property of the harness rather than of any single pipeline.


## Failure attribution

Context recall is measured on retrieved evidence with **no generator in the loop**, so it localises failure to a pipeline stage. The two prompts were calibrated against each other and sit on a **common scale**: shown the same content both recover 100% of nuggets, offset B = 0.0000 (F-40, resolved), so the gap is readable. The live caveat is F-45 instead - where the evidence set is large the context term is depressed by set size, and that arm's gap is not interpretable at all.

| arm | context recall | nugget recall | gap | reading |
|---|---|---|---|---|
| intrinsic_P-Q | 0.7083 | 0.8532 | +0.1449 | uses available content |
| extrinsic_P-Q | 0.7083 | 0.8193 | +0.1110 | uses available content |
| intrinsic_P-G | 0.7083 | 0.7472 | +0.0389 | uses available content |
| extrinsic_DOS-Q | 0.6978 | 0.7369 | +0.0391 | uses available content |
| intrinsic_P-D | 0.7083 | 0.6726 | -0.0357 | **content retrieved but not used** |
| sensitivity_DOS-Q_matched | 0.4657 | 0.5671 | +0.1014 | uses available content |
| extrinsic_B-Q | 0.4664 | 0.5654 | +0.0990 | **gap not interpretable — F-45 dilution** |

## Length-adjusted metrics (direct standardisation)

This judge is Llama-family, and Llama-family judges reward verbosity on completeness-style judgements (F-35, [R-07]). An arm that writes longer drafts can score higher without conveying more. Each arm is therefore re-scored as if its drafts had the **same length distribution as the pooled corpus**, so only within-length-band differences survive. Abstentions are excluded (a zero-length draft has no band); they are reported separately above.


### nugget_recall

Bands: quintiles of pooled draft length, upper bounds [125, 160, 197, 245] words.

| arm | mean words | raw (drafted only) | length-adjusted | shift | bands |
|---|---|---|---|---|---|
| intrinsic_P-Q | 245.5 | 0.8947 | **0.8655** | -0.0292 | 5/5 |
| extrinsic_P-Q | 231.2 | 0.8651 | **0.836** | -0.0291 | 5/5 |
| intrinsic_P-D | 122.7 | 0.6909 | **0.7961** | +0.1053 | 4/5 |
| intrinsic_P-G | 187.5 | 0.7675 | **0.7731** | +0.0056 | 5/5 |
| extrinsic_DOS-Q | 218.5 | 0.7519 | **0.6751** | -0.0768 | 5/5 |
| sensitivity_DOS-Q_matched | 170.4 | 0.6161 | **0.6354** | +0.0193 | 5/5 |
| extrinsic_B-Q | 176.5 | 0.5928 | **0.605** | +0.0122 | 5/5 |

### faithfulness

Bands: quintiles of pooled draft length, upper bounds [125, 159, 195, 244] words.

| arm | mean words | raw (drafted only) | length-adjusted | shift | bands |
|---|---|---|---|---|---|
| extrinsic_DOS-Q | 218.5 | 0.9801 | **0.9703** | -0.0098 | 5/5 |
| intrinsic_P-G | 180.9 | 0.968 | **0.9701** | +0.0021 | 5/5 |
| extrinsic_P-Q | 231.2 | 0.9533 | **0.9477** | -0.0056 | 5/5 |
| sensitivity_DOS-Q_matched | 170.4 | 0.9289 | **0.9345** | +0.0057 | 5/5 |
| extrinsic_B-Q | 176.5 | 0.936 | **0.9343** | -0.0017 | 5/5 |
| intrinsic_P-Q | 230.8 | 0.952 | **0.9333** | -0.0187 | 5/5 |
| intrinsic_P-D | 122.4 | 0.8249 | **0.8081** | -0.0168 | 4/5 |

### Does the completeness ranking survive length adjustment?

Each pairwise difference in nugget recall, before and after direct standardisation. **A pair whose sign flips is not a safe ranking claim** - it is reporting draft length as much as coverage.

| comparison | raw Δ | length-adjusted Δ | 95% CI (adjusted) | robust? |
|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | +0.1112 | +0.0818 | [+0.0266, +0.1357] | yes |
| intrinsic_P-Q vs intrinsic_P-D | +0.1855 | +0.0598 | [-0.0005, +0.173] | direction holds, CI includes 0 |
| intrinsic_P-G vs intrinsic_P-D | +0.072 | -0.025 | [-0.0675, +0.0803] | **NO - sign flips** |
| extrinsic_P-Q vs extrinsic_B-Q | +0.2627 | +0.2269 | [+0.1497, +0.3011] | yes |
| extrinsic_P-Q vs extrinsic_DOS-Q | +0.0941 | +0.1265 | [+0.0335, +0.2157] | yes |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.1672 | -0.0803 | [-0.1575, -0.0008] | yes |

## Family: intrinsic (Holm-corrected within family)


### nugget_recall

| comparison | Δ | 95% CI (KC bootstrap) | better a1/a2 | exact p | Holm p | verdict |
|---|---|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | +0.106 | [+0.0741, +0.1398] | 44/2 | 0.0 | 0.0 | **significant** |
| intrinsic_P-Q vs intrinsic_P-D | +0.1806 | [+0.1345, +0.2278] | 65/7 | 0.0 | 0.0 | **significant** |
| intrinsic_P-G vs intrinsic_P-D | +0.0746 | [+0.0274, +0.1224] | 47/24 | 0.008555 | 0.008555 | **significant** |

### faithfulness

| comparison | Δ | 95% CI (KC bootstrap) | better a1/a2 | exact p | Holm p | verdict |
|---|---|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | -0.0247 | [-0.0457, -0.0042] | 15/35 | 0.0066 | 0.0066 | **significant** |
| intrinsic_P-Q vs intrinsic_P-D | +0.1103 | [+0.0834, +0.1377] | 75/15 | 0.0 | 0.0 | **significant** |
| intrinsic_P-G vs intrinsic_P-D | +0.1403 | [+0.1054, +0.1772] | 69/13 | 0.0 | 0.0 | **significant** |

## Family: extrinsic (Holm-corrected within family)


### context_recall

| comparison | Δ | 95% CI (KC bootstrap) | better a1/a2 | exact p | Holm p | verdict |
|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.2419 | [+0.1584, +0.3243] | 84/24 | 0.0 | 0.0 | **CONFOUNDED (F-45)** — judge ceilings 0.9999 vs 0.5905; no claim |
| extrinsic_P-Q vs extrinsic_DOS-Q | +0.0104 | [-0.0627, +0.0817] | 42/39 | 0.824313 | 0.824313 | not significant |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.2314 | [-0.3, -0.1626] | 20/76 | 0.0 | 0.0 | **CONFOUNDED (F-45)** — judge ceilings 0.5905 vs 0.9903; no claim |

### nugget_recall

| comparison | Δ | 95% CI (KC bootstrap) | better a1/a2 | exact p | Holm p | verdict |
|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.2539 | [+0.189, +0.3186] | 87/17 | 0.0 | 0.0 | **significant** |
| extrinsic_P-Q vs extrinsic_DOS-Q | +0.0823 | [+0.0273, +0.1368] | 51/20 | 0.000303 | 0.000303 | **significant** |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.1716 | [-0.2295, -0.1118] | 15/64 | 0.0 | 0.0 | **significant** |

### faithfulness

| comparison | Δ | 95% CI (KC bootstrap) | better a1/a2 | exact p | Holm p | verdict |
|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.0066 | [-0.0158, +0.0296] | 31/29 | 0.897422 | 0.897422 | not significant |
| extrinsic_P-Q vs extrinsic_DOS-Q | -0.0302 | [-0.0471, -0.0135] | 12/39 | 0.000198 | 0.000594 | **significant** |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.0468 | [-0.0705, -0.0249] | 11/37 | 0.000222 | 0.000594 | **significant** |

## Exploratory (no ranking claim)


### extrinsic_DOS-Q vs sensitivity_DOS-Q_matched

| metric | Δ | 95% CI | exact p |
|---|---|---|---|
| context_recall | +0.2321 | [+0.1791, +0.2883] | 0.0 |
| nugget_recall | +0.1698 | [+0.1175, +0.2229] | 0.0 |
| faithfulness | +0.0556 | [+0.0309, +0.0826] | 0.002088 |

## Caveats

- Absolute JUDGE_QUALIFIED=false. Only relative within-KC claims are licensed.
- Arm-independence established at LOW POWER (4-6 calibration rows per arm); weak evidence, not proof.
- Human gold is 36 rows from a SINGLE annotator, against a literature calibration benchmark of roughly 150 [R-02].
- F-45: context recall is depressed by evidence-set size (judge recovers 0.5905 of provably-present nuggets at 123 passages vs 1.0000 at 17). Comparisons against BaseDense are confounded and carry no claim; nugget recall, judged on drafts, is unaffected.
- Nugget and context metrics cover 151 of 159 KCs: 7 KCs have NO expert reference (the library covers 152/159) and KC_CLF_NB_009 fails decomposition structurally (F-36). All 8 drop identically for every arm, so paired comparisons stay balanced, but the excluded set is NOT random - 4 of the 7 reference-less KCs are exactly those where Proposed retrieved zero evidence, so the exclusion plausibly flatters Proposed ABSOLUTE retrieval recall (F-42).
- F-40 RESOLVED: the two recall prompts carry no constant offset (B = 0.0000; both recover 100% shown the same content), so the attribution gap is NOT prompt-asymmetry confounded. It remains uninterpretable for large-evidence arms under F-45.
- Completeness is verbosity-confounded under this Llama-family judge; length-adjusted figures are reported alongside (F-35, R-07).
