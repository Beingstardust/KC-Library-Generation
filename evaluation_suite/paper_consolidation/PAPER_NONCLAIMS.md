# What we do not claim

A guard against accidental overclaiming while writing. Every line here is a sentence that must **not**
appear in the thesis, followed by what may be said instead.

| We do NOT claim | Say instead |
|---|---|
| Proposed universally outperforms DOS-RAG. | Proposed ranks relevant material earlier and operates on a smaller evidence set; DOS-RAG recovers more by rank 20 under its larger budget. |
| DOS-RAG cannot construct KC drafts. | DOS-RAG is a strong high-recall comparator that produces usable drafts; the question is what KC-specific evidence construction adds. |
| The Qwen-seeded references are unbiased. | The seed-blind audit found no distortion or unsupported assertion in the audited sample; residual content-selection and support-boundary risks remain. |
| The reference is lexically independent of Qwen. | The reference is machine-seeded and explicitly not independent of Qwen; evaluation is semantic, and the residual asymmetry is localised to the Qwen-lineage arms' completeness figures. |
| All seven corpus-gap labels are independently confirmed. | Seven KCs are labelled corpus-unsupported under the adjudicated standard; a seed-blind reviewer disagreed on all three sampled, and revalidation is pending. |
| The groundedness arm ordering is judge-independent. | Only the endpoints reproduce across instruments; the middle ordering is instrument-sensitive. |
| Drafter choice does not affect quality. | The architecture is model-agnostic — the drafter is replaceable behind a common contract — but substituting it **does** change output quality. Portability is not performance invariance. |
| Any LLM will work as the drafter. | Three model families were exercised through the common interface: Qwen3.8-27B, Gemma4-31B, DeepSeek-R1-32B. |
| Domain choice does not affect quality. | The architecture is domain-agnostic — subject matter enters through corpus and curriculum, not pipeline semantics — but performance remains domain-sensitive, with mathematics measurably harder. |
| The pipeline works equally well in every domain. | It transferred to all three tested domains without domain-specific variants; performance differed. |
| 99.83% end-to-end KC-generation reproducibility. | A rerun of the claim-decomposition and judging stages reproduced 99.83% of matched per-claim decisions. Retrieval and drafting were not re-run. |
| MiniCheck establishes human truth. | MiniCheck is an independent entailment verifier used for instrument-sensitivity analysis; neither instrument is ground truth. |
| The pooled relevance labels are human gold. | Automated pooled relevance judgements produced by the frozen judge; no human validation exists. |
| Similar P@10/R@10 proves statistical equivalence. | The paired intervals contain zero; no retrieval equivalence margin was pre-registered, so no equivalence test is reported. |
| Batch-invariant serving is required for reproducible LLM judging. | In our configuration, concurrent serving changed a judgment at temperature zero; batch-invariant kernels removed the observed discrepancy. |
| LLM judges are serial-position sensitive. | Our judge, in our configuration, showed severe serial-position sensitivity as the passage set grew. |
| A judge failing a binary rubric can always be fixed by grading. | For completeness in this evaluation, retaining graded information substantially improved agreement with the available human labels. |
| The automated editorial triage measures quality. | The triage failed: it did not discriminate between arms and agreed with expert codes only 0.462 exactly. |
| Four in five drafts are accurate. | Approximately four in five **seed-arm** drafts required no more than local human editing under the adjudicated construction workflow. This is a review-burden figure, not an accuracy figure, and not a cross-model comparison. |
