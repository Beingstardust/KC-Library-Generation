# Threats to Validity

This document states the known threats to the validity of the reference-based KC evaluation, what is done about each, and — where a threat is not eliminated — says so plainly. Nothing here is hidden or softened; several of these threats are not fully resolvable within this study's design, and the correct scientific move is to disclose them rather than to claim they were handled.

## 1. Qwen seed anchoring (the principal threat)

**The threat.** The expert reference library was constructed by post-editing a frozen machine-generated draft, and that draft is one of the systems the reference is later used to evaluate. The seeding arm was empirically identified as `intrinsic P-Q` (Proposed + Qwen3.8 27B) by exact-matching the reference's own `original_machine_draft_text` field against all seven frozen candidate arms: 159/159 exact text and status matches, against 17/159 for the next closest arm. Post-edited references are known to retain characteristics of the system that produced them (Kloudová, Bojar and Popel 2021), and annotators exposed to model suggestions demonstrably adopt them, shifting label distributions in ways that can inflate reported model performance (Schroeder, Roy and Kabbara 2025).

**Scale of the exposure.** 117 of 159 references (73.58%) were accepted unchanged from the machine draft. Only 42 (26.42%) differ from it. The reference therefore substantially *is* the Qwen draft, on three quarters of the curriculum.

**What is done.**
- Source-first review: the expert recorded a corpus support state, source passages and a written memo *before* the machine draft was revealed for each KC.
- An independent seed-blind reconstruction of a stratified 30-unit sample by a second person who saw no system output and no part of the existing library (see `05_seed_bias_audit/`). This is the only independent human check on the reference; it is **not** a second review of the reviewer's decisions and yields no inter-rater agreement figure.
- No lexical-overlap metric is used anywhere in the comparison. BLEU, ROUGE, chrF, exact match, token overlap, edit distance, n-gram similarity, and embedding similarity to the reference are all excluded as primary or supporting ranking evidence. Surface similarity to a Qwen-seeded reference would structurally advantage Qwen irrespective of quality.
- A mandatory source-aware escape path in the correctness judgment: a candidate claim absent from the reference but supported by the source corpus is labeled `REFERENCE_SILENT_BUT_SOURCE_SUPPORTED` and counted as materially correct. Without this, the Qwen-seeded reference's content boundary would silently become the definition of correctness, penalizing every other system for saying correct things Qwen happened not to say.
- Pointwise, blinded evaluation: each judgment sees one draft against one target, never two systems side by side, and never a model, system, or retrieval-architecture name.
- Per-arm seed-bias diagnostics in human calibration: every calibration row carries `VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE` and `POSSIBLE_REFERENCE_DEFECT`, reported by arm after unblinding.

**What is NOT claimed.** We do not claim the reference is independent of Qwen, and we do not claim seeding cannot bias it. The defensible claim is narrower: the reference was machine-seeded and then subjected to source-grounded expert review by one reviewer, plus an independent seed-blind reconstruction of a 30-unit sample, so the anchoring threat is **controlled and disclosed, not eliminated**. If the per-arm seed-bias diagnostics show that legitimate non-Qwen formulations are disproportionately flagged, that is a finding to report, not a defect to patch away.

**Residual risk.** The seed-blind reconstruction has now been performed twice. Round 1 is not usable: its entries averaged 22 words against the reference's 186, so only the distortion direction was interpretable, and the reviewer wrote definitions on the three sampled corpus-unsupported units against instruction. Round 2 is protocol-compliant — 30 fresh units disjoint from round 1, 27 written entries of 144-186 words against a reference median of 186, and the three unsupported units correctly declined with recorded reasons. The magnitude of any anchoring effect is therefore measurable for the first time from round 2, and must not be described as ruled out until that comparison is reported.

## 2. Human expert subjectivity

A single expert made the primary source-support and edit-action determinations for all 159 KCs, and **no second reviewer repeated that task**. Judgments such as "is this omission material?" and "is this a MAJOR_EDIT or a REPLACE?" are irreducibly interpretive, and nothing in this design bounds that interpretive latitude. This is the most significant unmitigated threat to the reference, and it is unmitigated by construction rather than by oversight.

## 3. No inter-rater agreement is available

Because the curation was a single-reviewer task, there is no inter-rater agreement statistic for it and none is reported. An earlier version of this document reported 81.13% raw action agreement over two reviewers, with 30 action and 18 support-state disagreements adjudicated 15/15 and 14/4. **That cross-review did not take place**; see `EXPERT_REFERENCE_ADJUDICATION_REPORT.md` for the correction and the artifact evidence. No individual KC's edit action should be treated as beyond question, and the absence of a second opinion is the reason.

## 4. Reference incompleteness

The expert reference is *an adequate description* of each KC, not an exhaustive account of everything true about it. Two consequences are handled explicitly: completeness is judged holistically (`CORE_COMPLETE` / `MATERIAL_OMISSION`) rather than by requiring full reference-claim coverage, and `materially_sound` deliberately does **not** require `reference_claim_coverage == 1.0`. A candidate that omits reference enrichment while retaining the defining content is not penalized. Conversely, a defining component the expert failed to include would be invisible to the completeness measure for every system equally.

## 5. Claim decomposition error

Per-claim metrics inherit any error in the decomposition step. The decomposer is an LLM and is explicitly **not** treated as ground truth. Mitigations: one frozen decomposition per draft and per reference, reused across the relations that share it (so faithfulness and correctness cannot disagree because they were given different claim sets); structural validation that every `parent_span` is a literal substring of the source text, catching invented provenance; formula-integrity checks that flag mathematical relations no single claim preserves intact; and a bounded human validation pass over a stratified subset before results are opened. Decomposition error rate is reported. If it is poor, the generic decomposition protocol is fixed before results are inspected — and the fix must be generic, never Data-Mining-specific.

## 5b. Construct validity of holistic sufficiency judgments

A holistic "was this evidence enough?" classifier was built, tested, and **demoted** during development. Given the full expert reference as its standard, it reliably reinterpreted the question as "does the evidence contain everything in the reference", marking 18 of 25 adequate cases as materially gapped and citing reference enrichment (for K-Means: *"guaranteed to converge"*, *"random initialization is often used"*) as missing evidence.

This is the third instance of the same failure shape in this project, after v3 F4 and F5, and it reproduced across two independently trained 70B judges. It is reported as negative-method evidence: plausible holistic sufficiency prompts appear to be an unreliable construct for LLM judges when a complete reference is supplied as the standard. Retrieval coverage is therefore measured only in decomposed per-claim form. See `../reference_eval/output/m4_scope_decision.md`.

The residual threat is that the decomposed measure answers a narrower question than "was the evidence sufficient", and we do not claim otherwise.

## 6. LLM judge error

The automated judge is not gold. It is qualified against human labels on the same constructs (following ARES's human-calibrated approach), not assumed correct because the underlying model is strong. The prior holistic F1–F5 qualification does **not** transfer: those were different tasks against an authority-derived requirements ledger, and the development record shows why transfer would be unsafe — under that rubric the same two failure cases (`SENT_013`, `SENT_034`) were missed by two independently trained 70B judges, and the F4/F5 aggregation rule produced zero false-passes while wrongly failing 14–21 of ~35 correct cases. Judge qualification therefore restarts from scratch on the reference-based tasks, with thresholds fixed before locked validation results are opened, and no prompt, threshold, or reason-code changes once validation begins.

## 7. Differential judge bias across model families

A judge may systematically favor text that resembles its own family's output. This is a live risk here because the reference itself came from one specific model. Judge qualification statistics are therefore reported **per candidate arm**, not only in aggregate, so a judge that is accurate overall but differentially lenient toward one family is detectable. Judge selection happens while candidate identities are blinded, and explicitly not on the basis of which system the judge makes win.

## 8. Single-domain internal validity

All 159 KCs come from one Data Mining course corpus of four documents. Findings about which drafter or which retrieval architecture performs best are internally valid for this corpus and curriculum, and should not be presented as general properties of the systems. Corpus characteristics — document count, notation density, the prevalence of formulas and procedures, how thoroughly each concept is covered — plausibly interact with retrieval and drafting behavior.

## 9. Generalization to other domains

Mathematics and Sociology KC libraries exist in this project but are **not** covered by this reference or this evaluation. No claim from this study transfers to them without a separate reference construction and evaluation. They must be reported separately, and a result here must not be described as a result about the pipeline in general.

## 10. Source-corpus boundaries

The corpus is the sole authority, which makes its edges consequential.
- Seven KCs (4.40%) were labelled by the reviewer as genuine corpus gaps with no reference text. For these the only meaningful question is whether a system respected the boundary; a clean abstention is the safe outcome and a confident definition is an unsafe attempt. They are excluded from reference-content metrics rather than scored against an invented gold.
- Two KCs are `PARTIALLY_SUPPORTED`: the corpus establishes part of the concept. Completeness is not assessed for these, and they are reported separately from the 150 fully supported KCs.
- A KC the corpus covers poorly may produce a thin reference that is easy for every system to match, and a KC it covers richly may produce a demanding one. This affects difficulty per KC, which is why the primary aggregation is KC-macro rather than pooled over claims — otherwise KCs with long references would dominate.
- The corpus reflects one instructor's course materials. "Correct" throughout means "established by this corpus", not "true in the field". One adjudication makes this concrete: a sample-variance convention was retained because the course source itself uses it, explicitly declining to correct it from outside statistical knowledge.

## 11. Statistical conclusion validity

All systems are paired by KC. Three-way comparisons use Cochran's Q before pairwise exact McNemar tests with Holm correction inside each comparison family (intrinsic; extrinsic). Proportions carry Wilson 95% intervals; paired continuous differences use a deterministic paired bootstrap (5,000 replicates) reported with mean difference, 95% interval, and win/tie/loss counts. Superiority is not inferred from raw percentages. Two limits remain: n = 150 fully supported KCs bounds the detectable effect size, and the ~30-KC × 6-arm calibration sample bounds the precision of the judge-agreement estimates that everything downstream depends on.

## 12. Human review burden is not a quality comparison

The 117/159 (73.58%) ACCEPT rate measures **expert post-edit intervention burden for the seeded library**. It is not Qwen's accuracy score and must never be reported as a cross-model quality result — no other system's output was ever offered to the expert for acceptance, so no other system could have earned an ACCEPT. The action distribution supports a claim of the form "X% of machine drafts required no or only local expert intervention"; it cannot support "Qwen is better than Gemma".
