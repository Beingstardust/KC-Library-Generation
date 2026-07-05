# Shapeaware target-named measurement-gloss repair, 2026-05-09

Scope: Step 5x shapeaware shadow classification only.

This patch adds a narrow target-named measurement-gloss rescue for cases where a scored candidate is already target-bound, uses a measurement-gloss sentence such as `X, which measures ...` or `X can be measured by ...`, and was otherwise demoted only because the generic definition subject parser marked the grammatical subject as mismatched.

The repair is intentionally not a global normalization or broad threshold weakening. It does not promote exercise prompts, reference/metadata/caption-like candidates, no-target-binding candidates, sibling-overlap candidates, formula fragments without target binding, or variant-only metric evidence.

Validated locally against the packaged 7 shapeaware probe KCs:

- recovered as drafting core: `KC_CLU_EVAL_004` Separation, `KC_CLU_EVAL_008` External Index: Entropy, `KC_FSEL_GOOD_002` Pearson Product-Moment Correlation
- deliberately not recovered: `KC_CLF_DT_003` Misclassification Rate, `KC_CLU_EVAL_006` Models of Randomness Approach 1, `KC_CLU_EVAL_007` Models of Randomness Approach 2, `KC_FSEL_GEN_007` Non-Deterministic Search

The new focused test file is `tests/test_shapeaware_target_named_measure_gloss.py`.
