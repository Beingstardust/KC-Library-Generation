# Research question → evidence mapping

Source of the questions: `KC_L v2 - Copy/Thesis_Proposal.pdf`, §5, quoted verbatim.

**Read this first.** The thesis is a framework for **evaluating multi-turn tutoring dialogues**. It
has two phases: an offline *curriculum grounding* phase that builds the KC Library from course
materials, and an online *dialogue evaluation* phase that segments a dialogue, retrieves KCs, and
scores each segment.

**Everything in this evaluation campaign belongs to the offline phase.** It answers RQ2.1 and
contributes to RQ3. It does not, by itself, answer RQ1, RQ2.2 or RQ2.3.

---

## RQ1 — How can we evaluate multi-turn dialogues beyond final-response scoring in a way that is pedagogically meaningful and supports failure localisation?

**Status: `NOT ADDRESSED BY THIS CAMPAIGN`.** This is the dialogue-evaluation phase.
**Paper section:** framework design and the dialogue-evaluation chapters.

| sub-RQ | question | status | note |
|---|---|---|---|
| RQ1.1 | segmenting dialogue into curriculum-grounded KC-relevant units | `NOT ADDRESSED HERE` | separate segmentation work |
| RQ1.2 | scoring each KC-aligned segment on micro dimensions alongside macro dimensions | `NOT ADDRESSED HERE` | — |
| RQ1.3 | aggregating micro and macro scores without masking critical errors | `PARTIALLY INFORMED` | the aggregation findings below transfer directly — see note |

**RQ1.3 note.** Two campaign findings bear directly on this sub-question even though it was not its
target, and they should be cited there:

- **All-or-nothing aggregation masks and manufactures.** Observed all-or-nothing rates track p^n, so a
  conjunctive rule reports draft length as if it were quality, and it *inverted* a system ranking
  relative to the per-claim rate. Any micro→macro aggregation that uses "all dimensions must pass"
  will behave the same way. (`AGGREGATION_ARTIFACT`)
- **Graded information survives aggregation where binary does not.** The same judge on the same
  labels scored 0.556 as a binary verdict and 0.8611 graded. (`GRADED_VS_BINARY`)

---

## RQ2 — How valid and reliable is a KC-grounded evaluation pipeline?

### RQ2.1 — What is the quality of the generated KCs, in terms of coverage, grounding, and usefulness for evaluation?

**This is the question the campaign was built to answer.** It has three named constructs, and they
are in materially different states.

#### (a) Coverage — `PARTIALLY ANSWERED`

| element | evidence | status |
|---|---|---|
| Retrieval coverage of required evidence | pooled test collection: P/R/nDCG @5,10,20 over 8,246 judged passages | `SUPPORTED_WITH_SCOPE` — automated qrels |
| Draft coverage of reference content | vital-nugget recall over 1,185 nuggets | `SUPPORTED_WITH_SCOPE` — but the decomposition is unaudited (**P3**) and the seed asymmetry attaches to Qwen-lineage arms |
| Curriculum coverage | 152/159 KCs have a reference body; 151 scored | `SUPPORTED` |

**Caveat that must travel with any coverage claim:** the completeness yardstick is derived from a
machine-seeded reference, and the decomposition step producing it has never been human-audited.

#### (b) Grounding — `ANSWERED, WITH A MATERIAL QUALIFICATION`

| element | evidence | status |
|---|---|---|
| Claims supported by retrieved evidence | per-claim groundedness, two independent instruments, 7,747 matched claims | `INSTRUMENT_SENSITIVE` |
| Behaviour when the corpus cannot support a KC | abstention: 0/1113 drafts from empty evidence; 7/7 vs 5/7 on unsupported KCs | `SUPPORTED` / `PROVISIONAL` (**P1**) |
| Provenance | 980 source citations, 980 resolved to document/page/sentence | `SUPPORTED` |

**The qualification:** absolute groundedness values and the middle of the arm ordering are
evaluator-dependent. Only the endpoints reproduce across instruments. Grounding is *demonstrated*;
its precise magnitude is not.

#### (c) Architectural portability — `SUPPORTED`

Distinct from performance, and evidenced by architecture rather than statistics:

| element | evidence | status |
|---|---|---|
| Drafter is structurally replaceable | single generic call path; zero conditionals on model identity; uniform capability accommodation; common output contract | `SUPPORTED` |
| Three model families ran the same contract | Qwen3.8-27B, Gemma4-31B, DeepSeek-R1-32B across 9 cells | `SUPPORTED_WITH_SCOPE` |
| Subject matter enters via corpus and curriculum | D-1…D-7 remediation AST-verified; evaluated packets confirm post-remediation code | `SUPPORTED` |
| Three subject domains ran the same architecture | Data Mining, Mathematics, Sociology | `SUPPORTED_WITH_SCOPE` |

**These are architectural claims and are not evidenced by the TOST analyses.** The TOST results
answer a different question — how much quality changes when the drafter or domain changes — and are
mapped under (b) and to RQ3 as *sensitivity*, not agnosticism.

#### (d) Usefulness for evaluation — `NOT ANSWERED`

**This is the gap.** "Usefulness for evaluation" means whether the KC library actually works as
instrumentation for the downstream dialogue-evaluation phase. Nothing in this campaign measures that.
Everything measured is intrinsic to the library — coverage against a reference, grounding in a
corpus — not its downstream utility.

Answering it requires evidence from the online phase: whether KC-aligned segmentation and scoring
behave better with this library than with an alternative, or than without curriculum grounding at
all. That is RQ2.2/RQ2.3 territory and, as far as this campaign is concerned, is **unresolved**.

**Do not let coverage and grounding results stand in for usefulness.** They are necessary conditions,
not the thing RQ2.1 finally asks for.

### RQ2.2 — How reliably can the KC inspector match dialogue segments to the correct KCs?
**Status: `NOT ADDRESSED BY THIS CAMPAIGN`.** No dialogue segments were evaluated here.

### RQ2.3 — How well does KC-aligned segmentation work under realistic student–tutor dialogue noise?
**Status: `NOT ADDRESSED BY THIS CAMPAIGN`.**

---

## RQ3 — How do the calculated scores and identified flaws compare across evaluators, human or otherwise?

**Status: `SUBSTANTIALLY INFORMED` — this campaign contributes directly, though on KC-quality scoring
rather than dialogue scoring.**

| comparison | evidence | status |
|---|---|---|
| LLM evaluator vs LLM evaluator | Selene vs MiniCheck, 7,747 matched claims: raw 0.7176, Gwet AC1 0.6076, arm-ordering ρ +0.4286 | `SUPPORTED_WITH_SCOPE` |
| Same evaluator, repeated | 0.9983 per-claim, ordering ρ +0.9643 — the baseline that makes the above interpretable | `SUPPORTED_WITH_SCOPE` |
| LLM evaluator vs human | graded completeness 0.8611 raw / 0.7224 AC1 on 36 development labels; binary predecessor 0.556 | `SUPPORTED_WITH_SCOPE` — development calibration |
| LLM evaluator vs human, editorial judgement | triage agreed with expert codes 0.462 exactly; never used the bottom category | `NEGATIVE_RESULT` |
| Human vs human | **not computable** — single annotation pass | `UNRESOLVED` |

**Directly transferable findings for RQ3:**

- Evaluator disagreement can be an order of magnitude larger than evaluator *noise*, and the two are
  distinguishable only if a rerun baseline is measured. Report both.
- Evaluator disagreement was traced to a measurable cause — strict entailment rewards longer evidence
  (r = +0.261 with document words) where a support rubric does not. Disagreement between evaluators
  is often a construct difference, not one of them being wrong.
- Prevalence wrecks κ. At 94% agreement-category prevalence, κ = 0.074 while AC1 = 0.61. Report AC1
  for skewed evaluator comparisons.
- Serving configuration, not just sampling temperature, affects evaluator reproducibility.

**Gap for RQ3:** no human–human agreement exists anywhere in the project, so "compared across
evaluators, human or otherwise" is currently answerable only for the *otherwise*.

---

## Summary

| RQ | status | blocking gap |
|---|---|---|
| RQ1, RQ1.1, RQ1.2 | not addressed here | dialogue-phase work |
| RQ1.3 | partially informed | aggregation findings transfer |
| **RQ2.1 coverage** | partially answered | P3 (nugget audit); seed asymmetry |
| **RQ2.1 portability** | answered (architectural) | static audit cannot catch non-vocabulary semantics |
| **RQ2.1 grounding** | answered with qualification | instrument sensitivity; P1 |
| **RQ2.1 usefulness** | **not answered** | requires downstream evidence |
| RQ2.2, RQ2.3 | not addressed here | dialogue-phase work |
| RQ3 | substantially informed | no human–human agreement |

**The single most important line for the writeup:** RQ2.1 asks for *coverage, grounding, and
usefulness for evaluation*. This campaign delivers strong evidence on the first two and **none on the
third**. Any sentence claiming RQ2.1 is answered must be qualified accordingly.
