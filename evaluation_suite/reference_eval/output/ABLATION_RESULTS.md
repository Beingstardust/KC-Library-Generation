# Ablation results (paired, within-KC)

Generated 2026-08-31T10:34:22Z · unit of analysis: **KC** · 159 KCs × 7 arms · 1112 rows

> **Scope of claim.** The judge failed absolute qualification (`JUDGE_QUALIFIED=false`; M3 `NOT_QUALIFIED`). These are *relative* comparisons only, licensed by pre-registered arm-independence at LOW POWER. No absolute quality claim follows.

> **Two verdict columns.** *as-specified* applies the guard exactly as pre-registered; it flags every comparison as within-noise because it compares a paired difference against an absolute judge-human disagreement rate (see locks/AMENDMENT_01_noise_guard.md). *amended* uses the controls the protocol already registered for a paired difference: Holm-adjusted exact McNemar plus a KC-clustered bootstrap CI excluding zero. Both are reported, neither hidden.

## Instrument provenance

- `ants_tp4_h100_frozen`: 553 rows
- `cluster_b_BI_a100_tp2`: 559 rows

## Abstention rate (a primary outcome)

| arm | abstained / KCs | rate |
|---|---|---|
| extrinsic_DOS-Q | 5 / 159 | 0.0314 |
| intrinsic_P-D | 10 / 159 | 0.0629 |
| intrinsic_P-G | 10 / 159 | 0.0629 |
| extrinsic_B-Q | 12 / 159 | 0.0755 |
| intrinsic_P-Q | 14 / 159 | 0.0881 |
| extrinsic_P-Q | 15 / 159 | 0.0943 |
| sensitivity_DOS-Q_matched | 17 / 158 | 0.1076 |

## Per-arm pass rates

| task | extrinsic_B-Q | extrinsic_DOS-Q | extrinsic_P-Q | intrinsic_P-D | intrinsic_P-G | intrinsic_P-Q | sensitivity_DOS-Q_matched |
|---|---|---|---|---|---|---|---|
| M1_faithfulness_per_claim | 0.7347 (n=147) | 0.8442 (n=154) | 0.6944 (n=144) | 0.4527 (n=148) | 0.8195 (n=133) | 0.6853 (n=143) | 0.7163 (n=141) |
| M2_correctness_per_claim | 0.9653 (n=144) | 0.973 (n=148) | 0.9718 (n=142) | 0.9116 (n=147) | 0.9769 (n=130) | 0.972 (n=143) | 0.9565 (n=138) |
| M3_core_completeness | 0.3947 (n=152) | 0.6645 (n=152) | 0.8158 (n=152) | 0.5724 (n=152) | 0.62 (n=150) | 0.8158 (n=152) | 0.4106 (n=151) |
| TARGET_ALIGNMENT | 0.9931 (n=145) | 0.9866 (n=149) | 1.0 (n=144) | 0.9797 (n=148) | 0.973 (n=148) | 1.0 (n=145) | 0.9928 (n=139) |

## Family: intrinsic (Holm-corrected within family)


### M1_faithfulness_per_claim

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | -0.1575 | [-0.252, -0.063] | 11/31 | 0.002887 | 0.002887 | WITHIN NOISE | **significant** |
| intrinsic_P-Q vs intrinsic_P-D | +0.2199 | [+0.1135, +0.3191] | 46/15 | 8.8e-05 | 0.000176 | WITHIN NOISE | **significant** |
| intrinsic_P-G vs intrinsic_P-D | +0.3636 | [+0.2576, +0.4697] | 59/11 | 0.0 | 0.0 | WITHIN NOISE | **significant** |

### M2_correctness_per_claim

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | -0.016 | [-0.056, +0.024] | 2/4 | 0.6875 | 0.6875 | WITHIN NOISE | not significant |
| intrinsic_P-Q vs intrinsic_P-D | +0.0426 | [-0.0071, +0.0922] | 9/3 | 0.145996 | 0.291992 | WITHIN NOISE | not significant |
| intrinsic_P-G vs intrinsic_P-D | +0.0543 | [+0.0078, +0.1085] | 9/2 | 0.06543 | 0.19629 | WITHIN NOISE | not significant |

### M3_core_completeness

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | +0.1933 | [+0.1333, +0.26] | 29/0 | 0.0 | 0.0 | WITHIN NOISE | **significant** |
| intrinsic_P-Q vs intrinsic_P-D | +0.2434 | [+0.1711, +0.3224] | 40/3 | 0.0 | 0.0 | WITHIN NOISE | **significant** |
| intrinsic_P-G vs intrinsic_P-D | +0.0533 | [-0.0467, +0.1533] | 34/26 | 0.366294 | 0.366294 | WITHIN NOISE | not significant |

### TARGET_ALIGNMENT

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| intrinsic_P-Q vs intrinsic_P-G | +0.0069 | [+0.0, +0.0207] | 1/0 | 1.0 | 1.0 | WITHIN NOISE | not significant |
| intrinsic_P-Q vs intrinsic_P-D | +0.0069 | [+0.0, +0.0208] | 1/0 | 1.0 | 1.0 | WITHIN NOISE | not significant |
| intrinsic_P-G vs intrinsic_P-D | -0.0068 | [-0.034, +0.0136] | 1/2 | 1.0 | 1.0 | WITHIN NOISE | not significant |

## Family: extrinsic (Holm-corrected within family)


### M1_faithfulness_per_claim

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | -0.0647 | [-0.1655, +0.036] | 21/30 | 0.262438 | 0.262438 | WITHIN NOISE | not significant |
| extrinsic_P-Q vs extrinsic_DOS-Q | -0.1901 | [-0.2817, -0.0986] | 10/37 | 9.8e-05 | 0.000294 | WITHIN NOISE | **significant** |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.1438 | [-0.226, -0.0616] | 11/32 | 0.001914 | 0.003828 | WITHIN NOISE | **significant** |

### M2_correctness_per_claim

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.0074 | [-0.0294, +0.0441] | 4/3 | 1.0 | 1.0 | WITHIN NOISE | not significant |
| extrinsic_P-Q vs extrinsic_DOS-Q | -0.0072 | [-0.0432, +0.0288] | 3/4 | 1.0 | 1.0 | WITHIN NOISE | not significant |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.007 | [-0.0423, +0.0282] | 3/4 | 1.0 | 1.0 | WITHIN NOISE | not significant |

### M3_core_completeness

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.4211 | [+0.3224, +0.5132] | 73/9 | 0.0 | 0.0 | WITHIN NOISE | **significant** |
| extrinsic_P-Q vs extrinsic_DOS-Q | +0.1513 | [+0.0658, +0.2368] | 36/13 | 0.001403 | 0.001403 | WITHIN NOISE | **significant** |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.2697 | [-0.3618, -0.1776] | 10/51 | 0.0 | 0.0 | WITHIN NOISE | **significant** |

### TARGET_ALIGNMENT

| comparison | Δ (a1−a2) | 95% CI (KC bootstrap) | discordant | exact p | Holm p | as-specified | amended |
|---|---|---|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.0072 | [+0.0, +0.0216] | 1/0 | 1.0 | 1.0 | WITHIN NOISE | not significant |
| extrinsic_P-Q vs extrinsic_DOS-Q | +0.0 | [+0.0, +0.0] | 0/0 | 1.0 | 1.0 | WITHIN NOISE | not significant |
| extrinsic_B-Q vs extrinsic_DOS-Q | +0.0 | [-0.0208, +0.0208] | 1/1 | 1.0 | 1.0 | WITHIN NOISE | not significant |

## Exploratory (no ranking claim)


### extrinsic_DOS-Q vs sensitivity_DOS-Q_matched

| task | Δ | 95% CI | exact p |
|---|---|---|---|
| M1_faithfulness_per_claim | +0.15 | [+0.0571, +0.2429] | 0.002459 |
| M2_correctness_per_claim | +0.0147 | [-0.0221, +0.0588] | 0.726562 |
| M3_core_completeness | +0.2517 | [+0.1656, +0.3377] | 0.0 |
| TARGET_ALIGNMENT | +0.0 | [-0.0217, +0.0217] | 1.0 |

## Caveats

- The judge is NOT qualified in absolute terms. Only relative, within-KC comparisons are licensed; no absolute quality claim follows from these numbers.
- Arm-independence was established at LOW POWER (4-6 calibration rows per arm). Non-significance there is weak evidence, not proof.
- M3 additionally failed absolute qualification (NOT_QUALIFIED) and is reported paired-only.
- Abstentions are excluded from M1/M2/TARGET pairs (no claims exist to judge) and are reported separately as a primary outcome; they are never imputed.

## Excluded rows (1)

- `KC_EVAL_ENS_004|sensitivity_DOS-Q_matched`: BlindingViolation: prompt contains blinding-violating text 'variant proposed' (pattern '\\b(system|arm|pipeline|architecture|retrieval|evidence\\s+pack\\w*|pack
