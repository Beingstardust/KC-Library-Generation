# Reference Construction Method

This document describes how the expert-curated reference KC library for the 159 Data Mining KCs was built, and the research basis for that design. It is a methods document, not a status report — see `08_audits/curation_progress.json` for live progress and `04_gold/EXPERT_REFERENCE_REPORT.md` for the completed result.

## 1. What this artifact is, and is not

The reference is **not** simply "Qwen draft → light proofreading → gold." The Qwen seed (frozen `extrinsic P-Q`, see `00_freeze/CANDIDATE_FREEZE_MANIFEST.json`) is used only as an editing scaffold, revealed to the expert only after the expert has already committed a source-based judgment. The protocol is:

```
freeze all candidate systems
        ↓
expert inspects ORIGINAL COURSE CORPUS first
        ↓
expert commits source-based judgment BEFORE seeing Qwen
        ↓
Qwen seed revealed only as an editing scaffold
        ↓
expert accepts / edits / rewrites against SOURCE CORPUS
        ↓
sentence/claim-level source provenance recorded
        ↓
independent blind validation pathway
        ↓
adjudication if necessary
        ↓
frozen expert-curated reference library
        ↓
later claim-level RAG evaluation
```

The original course corpus (`corpus_support/sentence_corpus.jsonl`, extracted from the 4 PDFs in `corpus_support/source_pdfs/`) is the sole authority. The Proposed evidence packet, the Base Dense evidence packet, DOS-RAG evidence, and the Qwen seed text itself are explicitly **not** authoritative — the console's source-search tooling (`02_curation/corpus_search.py`) is built exclusively against the sentence corpus, never against any candidate's retrieval evidence, precisely so that a retrieval failure in any one candidate system cannot get baked into the reference and bias the evaluation toward or against that system.

No automatic KES and no second automatic KC-generation pipeline was built for reference creation. Automated code in this directory does file navigation, corpus search, citation bookkeeping, hashing, schema enforcement, version control, and blind-review preparation — it never tells the expert what a KC definition should be.

## 2. The hard scientific rule

We do **not** claim: *"the reference is unbiased because a human edited it."* That claim is not supportable.

The correct claim is: *the reference was seeded from a frozen machine draft, so a potential anchoring effect was treated as an explicit validity threat. The reference-construction protocol therefore required source-first expert judgment before seed exposure, full source provenance, independent blind validation, and a separate seed-bias audit.* This distinction is preserved in every methods document in this directory and must be preserved in the thesis text.

## 3. Research basis

### 3a. Expert editing of machine-generated output is a legitimate methodology

Artemova et al. (2025), *Beemo: Benchmark of Expert-edited Machine-generated Outputs*, NAACL 2025 (`10.18653/v1/2025.naacl-long.357`). Beemo contains thousands of machine-generated texts subsequently edited by experts, establishing precedent for expert-edited machine output as a research artifact / benchmark resource. We use this as precedent for the general shape of our pipeline — machine scaffold → expert correction → curated reference artifact — **not** as evidence that seeded references are unbiased; Beemo establishes only that expert editing of machine output is a legitimate data-construction methodology.

### 3b. Explicit anchoring-risk evidence

Schroeder, Roy, and Kabbara (2025), *Just Put a Human in the Loop? Investigating LLM-Assisted Annotation for Subjective Tasks*, Findings of ACL 2025 (`10.18653/v1/2025.findings-acl.1323`). Their preregistered study found annotators exposed to LLM suggestions strongly adopted those suggestions, shifting label distributions, and that using such LLM-assisted labels for evaluation could inflate reported model performance. This is the primary justification for the anti-anchoring controls in this protocol (see `ANTI_ANCHORING_PROTOCOL.md`): source-first review before seed exposure, frozen candidates before reference construction, a full edit audit trail, no lexical similarity evaluation, blind independent reference validation, and an explicit seed-bias sensitivity analysis.

### 3c. Post-edited reference contamination

Kloudová, Bojar, and Popel (2021), *Detecting Post-Edited References and Their Effect on Human Evaluation*, HumEval 2021. The study demonstrates that post-edited machine-generated references can retain characteristics and errors from the system used to seed them. We use this as justification for: never assuming an accepted Qwen sentence is correct merely because the expert did not immediately notice an error (Stage C still requires corpus provenance even for `ACCEPT`); requiring corpus verification even for `ACCEPT`; running independent blind validation (`03_validation/`); and not using BLEU/ROUGE/edit-distance-to-reference as the primary comparison among Qwen/Gemma/DeepSeek.

### 3d. Human gold/reference evaluation

Thomson and Reiter (2020), *A Gold Standard Methodology for Evaluating Accuracy in Data-To-Text Systems*, INLG 2020 (`10.18653/v1/2020.inlg-1.22`). Precedent for a carefully designed human reference/accuracy evaluation serving as the benchmark against which automated metrics/judges are subsequently validated — the role this reference library plays for the later Selene/RootSignals judge calibration.

### 3e. RAG component separation

Es et al. (2024), *RAGAs: Automated Evaluation of Retrieval Augmented Generation*, EACL 2024 (`10.18653/v1/2024.eacl-demo.16`). RAGAS explicitly distinguishes retrieval/context quality, generation faithfulness, and generation quality — used here to justify evaluating retrieval and drafting separately in the later evaluation scaffold (`EVALUATION_METHOD_PLAN.md`).

### 3f. Fine-grained reference-based RAG diagnosis

Ru et al. (2024), *RAGChecker: A Fine-Grained Framework for Diagnosing Retrieval-Augmented Generation*, NeurIPS 2024 (arXiv:2408.08067). RAGChecker evaluates retrieval and generation using fine-grained claim-level diagnostics and reports stronger correlation with human judgment than several alternatives. This is the main precedent for the later evaluation architecture (claim-level faithfulness/correctness/completeness/retrieval-coverage) — see `EVALUATION_METHOD_PLAN.md`. That evaluation is **not** run yet; only compatible infrastructure is being prepared.

### 3g. Human-calibrated automatic RAG evaluation

Saad-Falcon et al. (2024), *ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems*, NAACL 2024 (`10.18653/v1/2024.naacl-long.20`). ARES evaluates context relevance, answer faithfulness, and answer relevance, using a bounded human-annotated set with prediction-powered inference to mitigate automated-judge errors. Precedent for validating any LLM judge against human annotations rather than treating the LLM as gold — the same principle that governs how Selene/RootSignals will be recalibrated on the new reference-based task (section 17-18 of the original task spec; see `EVALUATION_METHOD_PLAN.md`).

### 3h. KC-specific human expertise

Duan et al. (2026), *Automated Knowledge Component Generation and Interpretable Knowledge Tracing in Coding Problems*, Findings of ACL 2026 (`10.18653/v1/2026.findings-acl.1670`). The paper emphasizes that traditional KC construction/tagging relies on human domain expertise and is labor-intensive, and uses course instructors for human evaluation of KC quality/tagging. We use this to motivate expert validation as a legitimate reference authority, while also explaining (section 5 below) why the cost of manually building this one benchmark does not undermine the motivation for the scalable automated KC-construction pipeline that this reference will evaluate.

Full BibTeX entries are in `REFERENCES.bib`.

## 4. Freeze discipline

Before any expert edit, all 7 candidate arms (3 intrinsic, 3 extrinsic, 1 sensitivity), the corpus, the 4 source PDFs, and the hierarchy overlay were located via current audit records (not inferred from filenames), freshly re-hashed, and locked in `00_freeze/`. See `00_freeze/CANDIDATE_FREEZE_REPORT.md` for the full verification record, including the explicit reasoning for which Proposed/Qwen build was designated the seed source (`extrinsic P-Q`, not the older `intrinsic P-Q`). Once frozen, none of these artifacts may be regenerated, repaired, or modified using anything learned during reference construction (`21. ANTI-LEAKAGE RULE` in the original task spec; also stated in `ANTI_ANCHORING_PROTOCOL.md`).

## 5. Why this does not become a rival KC pipeline

Reference construction here is expensive, manual, expert-supervised, performed once for evaluation, inspected KC-by-KC against source, and explicitly not intended as a scalable production system. Duan et al. (2026) describe traditional human KC construction/tagging as labor-intensive — that is precisely the cost the automated pipeline under evaluation exists to avoid at scale. An expensive 159-KC expert reference benchmark does not undermine the motivation for automation; it supplies the measurement instrument required to evaluate the scalable method. Reference construction answers "what does the course corpus support for this KC?"; evaluation later answers "how well did each frozen automated system recover and express it?" These two questions are kept operationally separated throughout this directory.

## 6. Wording to preserve in the thesis

> "The reference KC library was created by expert post-editing of the frozen Qwen-generated library, but the machine draft was deliberately withheld during the first stage of each review. The expert first inspected the original course corpus, recorded the corpus support state and relevant source passages, and committed a short source-based memo. Only then was the frozen machine draft revealed as an editing scaffold. The expert could accept, modify, replace, or reject the draft, and all final reference content retained source provenance."
>
> "Because machine-assisted annotation can anchor human judgments, we treated the use of a machine seed as an explicit validity threat rather than assuming human post-editing removed the bias." (cite Schroeder et al. 2025; Kloudová et al. 2021)
>
> "To reduce the possibility that machine-specific phrasing influenced later system comparisons, evaluation was based on semantic, source-aware, claim-level judgments rather than lexical overlap with the reference." (cite RAGChecker 2024; RAGAS 2024)

If secondary blind validation is completed (`03_validation/`):

> "The final reference was independently validated against the original course corpus by a reviewer who did not see the machine seed or the identity of any evaluated system."

If blind reconstruction is completed (`05_seed_bias_audit/`):

> "A stratified subset was additionally reconstructed from the source corpus by a seed-blind reviewer to quantify whether the post-editing procedure changed the substantive reference content."

Neither of the last two claims may be made unless the corresponding workflow was actually run — see `05_seed_bias_audit/SEED_ANCHORING_AUDIT.md` for whether it was.
