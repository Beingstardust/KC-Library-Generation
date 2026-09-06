# Anti-Anchoring Protocol

The reference is seeded from a frozen Qwen draft that is itself one of the candidate outputs later evaluated against this same reference (`extrinsic P-Q` — see `00_freeze/CANDIDATE_FREEZE_MANIFEST.json`, `seed_source_designation`). This is the specific, named validity threat this protocol exists to control. It is not assumed away; it is controlled for, documented, and where possible measured.

## The risk, evidenced

Schroeder, Roy, and Kabbara (2025), *Just Put a Human in the Loop? Investigating LLM-Assisted Annotation for Subjective Tasks*, Findings of ACL 2025, ran a preregistered study and found that annotators exposed to LLM suggestions strongly adopted those suggestions, shifting label distributions, and that using such LLM-assisted labels for evaluation could inflate reported model performance. Kloudová, Bojar, and Popel (2021), *Detecting Post-Edited References and Their Effect on Human Evaluation*, HumEval 2021, separately show that post-edited machine-generated references can retain characteristics and errors from the system that seeded them, even when a human ostensibly reviewed and approved the text. Neither result is about this project's models specifically — they are general findings about human+LLM annotation pipelines, and we take them as the reason to build controls rather than trust editing alone.

## The six controls, and where each is implemented

1. **Source-first review before seed exposure.** `02_curation/reference_console.py`'s Stage A requires the expert to commit `source_support_state`, `authoritative_source_refs`, and a `pre_seed_source_memo` before the seed can be revealed at all. This is enforced in code (`SeedStore.reveal()` refuses unless the work-state for that KC already shows `stage_a` committed), not just by console UI convention — see `02_curation/test_console_dry_run.py` for the automated regression test that verifies no seed text is ever accessible or persisted anywhere before that commit.

2. **Frozen candidates before reference construction.** All 7 candidate arms were hashed and locked in `00_freeze/` before any expert edit began; `candidates_frozen.lock.json` records a hash of that freeze manifest itself so any later tampering is detectable. `freeze_reference_library.py` re-checks this lock at final reference freeze time.

3. **Full edit audit trail.** Every Stage-A commit and every Stage-B/C commit is hashed and timestamped (`reference_schema.py`'s `to_committed_dict()` methods); nothing is silently overwritten — corrections after commit go through `amend`, which preserves the original committed record byte-for-byte and writes a separate, reasoned amendment record instead (`02_curation/amendments/`).

4. **No lexical similarity evaluation.** The later evaluation scaffold (`06_evaluation_scaffold/`, see `EVALUATION_METHOD_PLAN.md`) explicitly excludes BLEU, ROUGE, exact sentence overlap, edit distance, chrF, and token overlap as primary quality comparisons. Because the reference was seeded from Qwen, surface similarity would structurally favor Qwen; all cross-model content-quality comparisons are semantic, claim-level, and source-aware instead, so the reference's textual origin cannot directly give Qwen a scoring advantage merely through wording.

5. **Blind independent reference validation.** `03_validation/` implements a second-reviewer pathway (Reviewer B) who never sees the Qwen seed, the expert's action/reason codes, the pre-seed memo, candidate identities, any candidate's evidence packet, or prior machine judgments — only the target KC, hierarchy, the final expert reference, and independent corpus access. Anything other than `VALID` routes to `adjudication_console.py`, which records both reviewers' positions and the adjudicated decision without letting Reviewer A silently overwrite the reference.

6. **Explicit seed-bias sensitivity analysis.** `05_seed_bias_audit/` implements the optional-but-strongly-recommended `BLIND_REFERENCE_RECONSTRUCTION_SAMPLE`: an independent, seed-blind reviewer reconstructs a ~30-KC stratified sample directly from the source corpus with zero exposure to the Qwen seed, the post-edited reference, or any candidate output, and the two are compared only on substantive content relationship (`SUBSTANTIVELY_EQUIVALENT` / `BOTH_VALID_DIFFERENT_FORMULATION` / `SEEDED_REFERENCE_MISSING_CONTENT` / `SEEDED_REFERENCE_EXTRA_UNSUPPORTED_CONTENT` / `MATERIAL_SEMANTIC_DIFFERENCE`) — never BLEU/ROUGE/edit distance. **If this audit is not completed, the thesis must not claim seed bias was empirically ruled out** — state instead that it remains a limitation mitigated by controls 1-5.

## What we do not claim

We do not claim the reference is unbiased because a human edited it (see `REFERENCE_CONSTRUCTION_METHOD.md` section 2 for the exact wording to use instead). We do not equate edit distance from the seed with correctness, and we do not compare Qwen/Gemma/DeepSeek by distance from this reference, precisely because the reference was seeded from Qwen — a low-edit-distance result for Qwen would be structurally expected regardless of true quality, not evidence of it.

## Anti-leakage

Once curation begins, reference content is not fed back into retrieval tuning, target-binding logic, drafting prompts, aliases, heuristics, evidence admission, or comparator configuration. If a later development cycle uses this reference to improve the pipeline, that must be documented as making this Data Mining set development data for that new version — it can no longer be claimed as a pristine held-out evaluation set for that later system.
