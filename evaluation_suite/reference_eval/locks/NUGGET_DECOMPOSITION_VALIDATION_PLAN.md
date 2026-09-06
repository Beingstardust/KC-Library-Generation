# Nugget decomposition and VITAL-assignment validation plan (P3)

**Status: PLAN. Not executed. Do not run without explicit authorization.**

## The problem

Completeness is a four-step construct:

    expert reference -> nuggets -> VITAL / OKAY -> semantic coverage by the candidate

Steps two and three are automated and **have never been audited**. The campaign has validated the
fourth step (against 36 human labels) and frozen the first. An error in decomposition or importance
labelling propagates into every completeness number and is invisible to any agreement statistic
computed downstream, because the nuggets are the yardstick rather than the thing measured.

Scale of the unaudited artifact: **1,185 nuggets across 151 KCs, of which 475 are labelled VITAL.**

## Sample design

Stratify so that the known failure mode is represented rather than averaged away:

| facet | levels |
|---|---|
| reference length | short · medium · long tercile |
| content type | definitional prose · formula-bearing · procedure-bearing |
| nugget count | low · high |
| hierarchy branch | at least four distinct branches |

Suggested **25 KCs**, giving roughly 200 nuggets — enough to detect a systematic decomposition
pathology, not enough to estimate a precise per-nugget error rate. State that limit.

Formula-bearing references must be over-sampled: the one known decomposition failure
(`KC_CLF_NB_009`) was formula-driven, and mathematics is the weakest domain, so this is where a
defect is most likely.

## Checks, per KC

**Decomposition fidelity**
1. Is any substantive reference content missing from the nugget set?
2. Does any nugget assert something the reference does not?
3. Are formulae preserved exactly, including symbols and subscripts?
4. Are multi-step procedures preserved as usable steps rather than flattened?
5. Is the decomposition over-fragmented — one fact split across nuggets such that a correct
   description could miss one and be penalised?

**Importance labelling**
6. Is each `VITAL` label defensible: would a description omitting it be materially incomplete?
7. Is each `OKAY` label defensible: is it genuinely elaboration rather than definition?
8. Is the VITAL share plausible for this KC? Corpus-wide it is 40.1%; sharp per-KC departures
   deserve a look.

## Reporting

Per-check error counts with examples, and a judgement on whether any observed error is *systematic*
(affecting a content type) or *idiosyncratic*. A systematic error is far more damaging: it would bias
whole strata of the completeness results in one direction.

## Consequences

- **Few errors, none systematic.** Completeness results keep their current status; the residual
  limitation is downgraded to a measured error rate.
- **Systematic error found.** Completeness figures must be recomputed or withdrawn for the affected
  content type. Note this would touch the adoption test and, indirectly, the completeness calibration
  in `JUDGE_COMPLETENESS_CAL`.

## Explicit non-goal

This audit does **not** revisit the reference text. The reference is frozen. The question is only
whether the automated decomposition faithfully represents it.
