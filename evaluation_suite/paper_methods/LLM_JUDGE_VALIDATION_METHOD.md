# LLM Judge Validation Method

## Position

The automated judge is an instrument to be validated, not an oracle. Following ARES (Saad-Falcon et al. 2024), which uses a bounded human-annotated set to correct for automated-judge error rather than trusting the judge outright, and GroUSE (Muller et al. 2025), which shows that evaluators of grounded answers themselves need benchmarking, no automated judgment is treated as gold merely because the underlying model is large or well-regarded.

## The prior qualification does not transfer

Selene-1-Llama-3.3-70B is retained as the primary operational candidate, and RootSignals-Judge-Llama-70B as the documented challenger. Neither is qualified for this evaluation.

The earlier qualification tested a **holistic F1–F5 rubric** against an authority-derived core-requirements ledger. The present tasks are different in kind: per-claim support against supplied evidence, per-claim correctness against an expert reference plus source, semantic completeness, retrieval-reference coverage, and reference-based target alignment. A qualification obtained on the old rubric says nothing reliable about the new one, and the development record shows concretely why assuming transfer would be unsafe:

- Two independently trained 70B judges missed the **same** two failure cases (`SENT_013` wrong-formula, `SENT_034` wrong-target) under that rubric — evidence the limitation was structural to the task design, not a property of one model.
- The F4/F5 all-requirements-must-be-correct aggregation drove false-passes to zero while wrongly failing 14 of 34 and 16 of 36 correct cases. Every single F4/F5 mismatch on both models was in the same direction (correct case wrongly failed), which is what identified the aggregation rule rather than the models as the cause.
- Selene and RootSignals differed sharply in structured-output discipline (100% vs 64.7% contract validity on one task under an identical prompt and token budget), so judge choice is not interchangeable even between models of the same size and licence.

Qualification therefore restarts from scratch.

## Structural enforcement before semantic evaluation

Every judge task is constrained by a JSON schema whose enforcement is **verified, not assumed**. The schemas are compiled with the pinned vLLM 0.27.1 + XGrammar toolchain and the emitted grammar is read directly (`reference_eval/tests/test_grammar_enforcement.py`). Two findings govern the design:

- `oneOf` discriminated unions **are** materialized into separate grammar branches, so a label can be hard-bound to the evidence family it is permitted to cite.
- `if/then/else` compiles cleanly but is **silently dropped** from the grammar. It is used nowhere.

Exact-length arrays (`minItems == maxItems == N`) compile to an exact repetition operator, so per-claim verdict arrays are pinned to the number of claims sent and a judge cannot silently skip or duplicate a claim.

No aggregate is ever requested from the model. Every per-KC metric is derived in Python from per-claim labels.

## Blinding

Judgments are **pointwise**: one text against one target, never two systems side by side. Model names, system names, retrieval-architecture names, machine draft-status labels, and any indication that a machine seeded the reference are excluded. Evidence is renumbered into opaque identifiers at prompt-build time so native ids cannot leak the KC or the retrieval lane.

Blinding is enforced in code (`assert_blinded()` raises at prompt-build time), not left to convention. The pattern set is two-tiered because several system names in this project are also ordinary domain vocabulary — "sensitivity" is a synonym for recall, "baseline assumption" is standard hypothesis-testing language, "seeded by a positive example" describes RIPPER's rule-growing strategy, and "a previously proposed model" is ordinary academic prose. Tier 1 patterns are unambiguous tokens; Tier 2 patterns require an adjacent wiring-level noun. The pattern set was validated against all 159 frozen reference texts and all 36 sentinels: zero false positives, all known leak forms caught.

## Development-stage sentinel testing

The frozen 36-case sentinel suite is translated into the reference-based tasks without changing any case's substantive truth. The translation is rule-driven, never per-case, and any case the rules cannot classify is emitted with an explicit review flag instead of an invented label.

Three re-typings follow from the reference itself rather than from convenience:
- Cases whose KC the expert adjudicated **UNSUPPORTED** have no gold text, so correctness and completeness have nothing to judge against; they become source-boundary cases asking whether the system respected the corpus gap. This makes the previously hard-to-catch `SENT_034` failure directly checkable.
- A case whose KC is **PARTIALLY_SUPPORTED** receives no completeness expectation.
- A case with an empty draft has no claims, so only the evidence-side question applies.

For the `complete_but_unsupported` cases the old and new semantics genuinely differ: legacy F3 asked whether content was *correct* (a true-but-unsourced claim passed), whereas M2 asks whether it is supported by the reference **or the source authority** (a true-but-unsourced claim is `NOT_SUPPORTED_BY_AUTHORITY`, which does not count as materially correct). These were resolved from what each sentinel's own frozen record verified — cases documenting an explicit authority-context search establishing absence were set to FAIL; cases verifying only system-evidence absence were left undetermined for expert resolution rather than guessed.

Sentinel results are development evidence. **They do not qualify a judge.**

## Task scope at qualification

Qualification gates on the primary tasks only: **M1** faithfulness, **M2** correctness, **M3** holistic core completeness, **TARGET** alignment, and **M4A** reference-claim retrieval support (which is additionally human-validated on a bounded subset to confirm the per-claim support classification is reliable).

**M4B holistic evidence adequacy is excluded from qualification gating** - even if a later run happens to score better. It was demoted during development for construct-validity failure; a favourable number would not restore construct validity, and re-promoting a metric because it later looked good is precisely the researcher degree of freedom this protocol exists to close.

## Human calibration

Design: 30 stratified KCs × 6 unique primary arms = 180 blinded human rows. (Six, not five: intrinsic and extrinsic Proposed/Qwen are different artifacts — different commit, different prompt mode, different hash, only 17/159 identical drafts — and neither can substitute for the other without breaking the within-experiment control it was built to satisfy.)

All arms for a KC stay in the same stratum, so the comparison is paired. Stratification covers hierarchy branch, reference edit action, formula/non-formula, and procedure/non-procedure, with guaranteed representation of every level of every factor — proportional allocation alone had silently dropped the REPLACE and MINOR_EDIT categories, which are the most informative about anchoring. Known failures are not oversampled.

The human sees KC, hierarchy, expert reference, expert source authority, candidate draft, and candidate system evidence — and is blind to model, system, retrieval architecture, machine status, and which arm seeded the reference. Humans label the **same constructs** as the automated judge.

### Mandatory seed-bias diagnostic

Because the reference is machine-seeded, every calibration row carries two additional blinded fields:

- `VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE` — YES only when the candidate contains substantively valid, source-supported content or formulation that an evaluator relying mechanically on the reference could wrongly penalize.
- `POSSIBLE_REFERENCE_DEFECT` — YES when the reference itself may be wrong.

Both are answered against the original source authority, never against candidate identity, and are reported **per arm** after unblinding. This does not prove absence of seed bias. It tests empirically whether the reference representation disproportionately penalizes legitimate non-seed formulations.

The reference is never modified because a candidate uses different wording. If a genuine factual defect in the reference is discovered, the process stops, the defect is adjudicated through an explicit blinded correction protocol, the reference is versioned, and all affected evaluations are rerun. The reference is never silently patched.

## Qualification statistics

Per judgment type: raw human/judge agreement, Gwet's AC1, confusion matrix, PASS precision and recall, FAIL precision and recall, false-PASS rate, false-FAIL rate, and invalid-output rate. All are additionally reported **per candidate arm**, to detect a judge that is accurate in aggregate but differentially biased toward one model family.

Gwet's AC1 is the primary chance-corrected statistic rather than Cohen's κ because these label distributions are heavily imbalanced, and κ behaves paradoxically under high prevalence — a documented property with a hand-verified demonstration in this project's statistics module (90% raw agreement giving κ = 0.0 while AC1 ≈ 0.89).

The dominant concern is **dangerous false PASS**: incorrect content, wrong target, or unsupported claims accepted as sound.

## Qualification gate

Thresholds are set as a project criterion — not inherited from any literature universal, and not carried over from the prior rubric where they would no longer make sense — and are **fixed before locked validation results are opened**. Strong performance is required specifically on claim correctness, claim faithfulness, wrong-target detection, and material-omission detection.

Once locked validation begins: no threshold changes, no prompt changes, no reason-code changes.

Judge selection happens while candidate identities are blinded, and never on the basis of which system a judge makes win. If Selene fails, the failure is reported rather than tuned away; RootSignals is then tested under the identical frozen contracts as the pre-designated fallback.

## Locks

Production execution is refused without all six: `EXPERT_REFERENCE_FROZEN`, `CANDIDATES_FROZEN`, `CLAIM_PROTOCOL_FROZEN`, `JUDGE_PROMPTS_FROZEN`, `JUDGE_QUALIFIED`, `BLINDING_FROZEN`. Each stores the SHA-256 of what it freezes, so verification recomputes rather than trusts. There is no override flag: an unqualified judge cannot be used in production mode by any switch, only by qualifying it.
