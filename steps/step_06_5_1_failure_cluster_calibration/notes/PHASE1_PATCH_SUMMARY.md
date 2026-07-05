Step 6.5.1 Phase 1 patch summary

- Dominant cluster treated as local support-quote rescue failure, not upstream retrieval failure.
- Added a narrow post-gating local bundle rescue in `run_step6_4_2.py`.
- Rescue scope is limited to verified, same-topic, non-doc-mismatch candidates that already passed semantic gating and `rerank_min`, but failed only on narrow `rerank_margin` or `D2Error`.
- Rescue requires a tightly local bundle, at least one provisional definition/equation/procedure-style support quote, and a bundle-level reranker win over competitors.
- Added a same-parent sibling fallback in contamination adjudication so the `KC_CLF_UND_001` vs `KC_CLF_UND_005` pattern is adjudicated as sibling ambiguity when the selected bundle still clearly supports the target KC.
- No upstream retrieval, quote verification, provenance rebinding, definition_short contract, or deterministic slice logic was changed.
