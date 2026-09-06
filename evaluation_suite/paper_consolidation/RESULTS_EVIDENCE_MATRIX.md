# Results evidence matrix

One row per result the paper might use. The purpose of the layout is to make unsupported leaps
visually obvious: a row with `no` in **human validated** and `no` in **second instrument** cannot
carry a strong claim, whatever its p-value.

Legend — **Robust?** `yes` = holds under every check applied · `scoped` = holds with the stated scope
· `no` = does not survive a check · `pending` = a blocking dependency is unresolved.

| # | Result | Population | Metric | Value | Uncertainty | Human validated? | 2nd instrument? | Robust? | Paper status | Caveat |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Retrieval compactness | 159 KCs | passages/KC | Proposed 17.2 · DOS 33.7 · Base 123.1 | n/a (artifact property) | n/a | n/a | yes | `SUPPORTED` | descriptive only |
| 2 | P@10, Proposed vs DOS-RAG | 159 KCs | P@10 | −0.0006 | [−0.0500, +0.0481] | **no** | no | scoped | `SUPPORTED_WITH_SCOPE` | contains zero; **no equivalence test** |
| 3 | R@10, Proposed vs DOS-RAG | 159 KCs | R@10 | +0.0019 | [−0.0245, +0.0280] | **no** | no | scoped | `SUPPORTED_WITH_SCOPE` | contains zero |
| 4 | nDCG@10, Proposed vs DOS-RAG | 159 KCs | nDCG@10 | **+0.1141** | [+0.0659, +0.1604] | **no** | no | scoped | `SUPPORTED_WITH_SCOPE` | automated qrels |
| 5 | nDCG@5 / P@5, Proposed vs DOS-RAG | 159 KCs | nDCG@5 · P@5 | +0.2049 · +0.1117 | [+0.147,+0.262] · [+0.052,+0.171] | **no** | no | scoped | `SUPPORTED_WITH_SCOPE` | automated qrels |
| 6 | R@20, Proposed vs DOS-RAG | 159 KCs | R@20 | **−0.1332** | [−0.1848, −0.0823] | **no** | no | scoped | `SUPPORTED_WITH_SCOPE` | favours DOS-RAG; larger budget |
| 7 | Proposed vs BaseDense | 159 KCs | all 9 metric/cutoffs | all favour Proposed | all CIs exclude zero | **no** | no | scoped | `SUPPORTED_WITH_SCOPE` | automated qrels |
| 8 | Budget sensitivity | 159 KCs | R@20 DOS vs matched | +0.2147 | [+0.1771, +0.2564] | **no** | no | scoped | `SECONDARY` | consistent with, not proof of, a budget effect |
| 9 | Pooled qrel provenance | 8,246 passages | label source | Selene, automated | n/a | **no** | n/a | — | limitation | **blocks P2** |
| 10 | Groundedness, Selene | 1,011 drafts | per-claim rate | 0.813–0.969 by arm | — | no | yes | **no** | `INSTRUMENT_SENSITIVE` | see row 12 |
| 11 | Groundedness, MiniCheck | 1,011 drafts | per-claim rate | 0.587–0.922 by arm | — | no | yes | **no** | `INSTRUMENT_SENSITIVE` | strict entailment |
| 12 | Cross-instrument agreement | 7,747 claims | AC1 · ρ | 0.6076 · **+0.4286** | — | no | yes | **no** | `SUPPORTED_WITH_SCOPE` | only endpoints reproduce |
| 13 | Groundedness endpoints | 1,011 drafts | ordering | DOS-RAG top, DeepSeek bottom | — | no | yes | scoped | `SUPPORTED_WITH_SCOPE` | endpoints only |
| 14 | Drafter ordering | crossed 3×3 | groundedness | Gemma ≥ Qwen > DeepSeek | — | no | yes | scoped | `SUPPORTED_WITH_SCOPE` | maths + data-mining only |
| 15 | **Drafter performance** equivalence (TOST) | crossed 3×3 | δ=0.05 | 3/3 under Selene, 1/3 under MiniCheck | 90% CI vs margin | no | yes | **no** | `NOT_ROBUST` | evaluator- and margin-dependent. **Not** a test of model-agnosticism |
| 15a | **Drafter architecture agnostic** | pipeline code | implementation audit | zero model-name conditionals; one generic call path | n/a | n/a | n/a | yes | `SUPPORTED` | static audit; only 3 families exercised |
| 15b | **Domain architecture agnostic** | verified evidence path | AST audit + artifact check | 1 docstring string remains; evaluated packets post-remediation | n/a | n/a | n/a | yes | `SUPPORTED` | residual data-driven asymmetry disclosed |
| 16 | **Cross-domain performance** sensitivity | crossed 3×3 | δ=0.05 | DM≡Soc; maths outside | 90% CI vs margin | no | **no** | scoped | `NOT_SUPPORTED` as invariance | one instrument. **Not** a test of domain-agnosticism |
| 17 | Variance decomposition | crossed 3×3 | drafter variance share | 0.0–6.4% (in-scope) | G-coef 0.0–0.42 | no | no | scoped | `SECONDARY` | 1 obs/cell; interaction confounded |
| 18 | Abstention on unsupported KCs | 7 KCs | refusal count | Proposed 7/7 · DOS 5/7 drafted | n=7 | labels human, **contested** | no | **pending** | `PROVISIONAL` | **blocked by P1** |
| 19 | No drafting from empty evidence | 1,113 rows | count | 0 | n/a | n/a | n/a | yes | `SUPPORTED` | harness property |
| 20 | Seed-blind audit | 27 KCs | relationship labels | 0 distortion · 0 unsupported | n=27, 1 reviewer | reviewer human | no | scoped | `SUPPORTED_WITH_SCOPE` | 3 failure modes untested; boundary disagreed |
| 21 | Seed lexical independence | 1,011 drafts | 8-gram overlap vs recall | r=+0.80 seed vs +0.11/+0.21 | — | no | no | yes | `SUPPORTED` | localises asymmetry to Qwen-lineage arms |
| 22 | Editorial triage | 1,113 drafts | level distribution | 97.2–99.3% top two | agreement 0.462 | yes (145 codes) | no | **no** | `NEGATIVE_RESULT` | do not use as quality metric |
| 23 | Human review burden | 159 drafts | review_action | 127/159 = 79.9% | n/a | yes | n/a | scoped | `SUPPORTED_WITH_SCOPE` | seed arm; not accuracy |
| 24 | Completeness calibration | 36 labels | raw · AC1 | 0.8611 · 0.7224 | n=36 | yes | no | scoped | `SUPPORTED_WITH_SCOPE` | **development** calibration |
| 25 | v1 binary completeness | 36 labels | raw | 0.556 | n=36 | yes | no | — | `FAILED` | superseded |
| 26 | M1/M2/TARGET/M4A | ≤32 labels | — | undecided | minority class < 10 | partial | no | — | `INSUFFICIENT` | not PASS, not FAIL |
| 27 | Serial-position experiment | 151 KCs × 3 | recovery of known content | 1.0000 → 0.5905 | +0.4095 [+0.332,+0.487] | ground truth by construction | no | scoped | `SUPPORTED_WITH_SCOPE` | this model/config |
| 28 | Faithfulness padding | 143 KCs | paired change | +0.0175 | McNemar p=0.00082 | no | no | scoped | `SUPPORTED_WITH_SCOPE` | opposite sign to row 27 |
| 29 | Evaluation-stage rerun | 7,610 claims | agreement · ρ | **0.9983** · +0.9643 | max arm drift 0.0027 | no | n/a | yes | `SUPPORTED_WITH_SCOPE` | decomposition + judging only |
| 30 | Batch invariance | 144 sentinels | verdict changes | 1/144 → 0/144 | n=144 | no | no | scoped | `SUPPORTED_WITH_SCOPE` | one configuration |
| 31 | Aggregation artifact | 2 domains | p^n vs observed | err +0.021 / +0.088 | — | no | no | scoped | `SUPPORTED_WITH_SCOPE` | positive errors = correlated claims |
| 32 | Nugget decomposition | 1,185 nuggets | — | unaudited | — | **no** | no | **pending** | limitation | **blocked by P3** |

## Reading the matrix

Three structural observations follow directly from the columns.

**Every retrieval row has `no` under human validation.** That is one dependency (P2) sitting under
the entire extrinsic argument. It does not make the results wrong; it means each retrieval sentence
must carry the automated-qrel qualifier until P2 is done.

**Every row that was checked on a second instrument came back `no` or `scoped`** — rows 10–15. The
only results that survived a second instrument unchanged are the endpoints. This is the strongest
single argument for reporting orderings rather than magnitudes.

**Row 29 is what makes rows 10–15 interpretable.** Without a rerun baseline showing 0.9983, the
cross-instrument disagreement could have been dismissed as noise.
