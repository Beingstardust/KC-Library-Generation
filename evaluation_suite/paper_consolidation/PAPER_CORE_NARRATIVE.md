# Paper core narrative

The spine of the thesis argument, written so that every sentence traces to a ledger row. If a
paragraph here cannot be matched to `PAPER_CLAIM_LEDGER.md`, it is not yet supported.

---

## 0. Where this work sits in the thesis

**The thesis is a framework for evaluating multi-turn tutoring dialogues.** It has two phases: an
offline *curriculum-grounding* phase that builds a Knowledge Component library from course materials,
and an online *dialogue-evaluation* phase that segments a dialogue, retrieves KCs, and scores each
segment against micro and macro rubrics.

**Everything in this evaluation campaign belongs to the offline phase.** It answers **RQ2.1** — the
quality of the generated KCs — and contributes substantially to **RQ3**, the comparison of scores
across evaluators. It does not address RQ1, RQ2.2 or RQ2.3.

This matters for framing: the KC library is *instrumentation* for dialogue evaluation, not the end
product. A KC library is good insofar as it makes downstream dialogue evaluation curriculum-grounded
and diagnostic. See `RQ_EVIDENCE_MAPPING_FINAL.md`.

## 1. What the KC library is for

KC_L addresses **evidence-grounded construction of a persistent, curriculum-indexed knowledge-component
library**. That is not ordinary single-query RAG: the output is a durable artifact, indexed against a
syllabus, that a human will review and maintain, and where every statement must be traceable to
course material — because it will later serve as the reference against which tutoring dialogues are
scored.

The consequences for evaluation are immediate. Answer quality on a single query is not the target;
what matters is whether the library is complete against the curriculum, grounded in the corpus,
reviewable, and honest about what the corpus does not support.

## 2. Why DOS-RAG is the comparator

DOS-RAG is chosen deliberately as a **strong contemporary comparator**, not a straw baseline. It
tests the question that actually threatens the contribution: *can simpler high-recall retrieval make
KC-specific evidence construction unnecessary?*

BaseDense plays the different role of a simple dense floor. Both are needed: without DOS-RAG the
comparison would be uninformative; without BaseDense there would be no reference point for what
naive retrieval achieves.

The thesis is **not** that DOS-RAG cannot produce KC drafts. It can. The question is what the
proposed evidence machinery buys on top.

## 3. What the retrieval evaluation found

Under automated pooled relevance judgements, across 159 KCs:

| | Proposed | DOS-RAG |
|---|---|---|
| passages per KC | 17.2 | 33.7 |
| P@10 | 0.6279 | 0.6286 | 
| R@10 | 0.2379 | 0.2361 |
| nDCG@10 | **0.5229** | 0.4074 |
| R@20 | 0.3304 | **0.4705** |

Read as paired differences with concept-clustered intervals:

- **At k=10 there is no material separation on precision or recall.** P@10 −0.0006 [−0.0500,
  +0.0481]; R@10 +0.0019 [−0.0245, +0.0280]. Both contain zero. This is *not* an equivalence result —
  no equivalence margin was pre-registered for retrieval — it is an absence of detected separation.
- **Proposed ranks relevant material earlier.** nDCG@10 +0.1141 [+0.0659, +0.1604], and the effect is
  larger at k=5 (nDCG@5 +0.2049).
- **DOS-RAG recovers more by rank 20.** R@20 −0.1332 [−0.1848, −0.0823], in the configuration with
  roughly twice the native retrieval budget. Against its own budget-matched arm, DOS-RAG's depth
  advantage attenuates — consistent with a budget effect, though no analysis isolates the mechanism.
- **Against BaseDense, Proposed wins on all nine metric/cutoff combinations**, every interval
  excluding zero.

## 4. The claim this supports: an operating point, not superiority

The defensible reading is that the proposed architecture's contribution is its **operating point**:

- **compactness** — comparable top-10 retrieval quality on roughly half the evidence;
- **concentration** — definitional material placed earlier in the ranking;
- **target specificity** — evidence organised per knowledge component rather than per query;
- **provenance and reviewability** — every KC carries resolvable source citations;
- **source-boundary handling** — the pipeline declines rather than drafting from nothing.

It is explicitly **not** a claim of universal retrieval superiority. DOS-RAG retrieves more relevant
material overall when allowed its larger budget, and the paper should say so.

## 5. Evaluation findings that qualify the above

Three results constrain how strongly anything can be stated, and they belong in the paper rather than
in a footnote.

**Groundedness rankings are instrument-sensitive.** Two independent instruments scoring byte-identical
claims agree at Gwet AC1 0.6076 with arm-ordering ρ = +0.4286. Only the endpoints reproduce — DOS-RAG
highest, DeepSeek-R1 lowest. The mechanism was measured: strict entailment rewards longer retrieved
evidence (r = +0.261 with document words), where a partial-support rubric does not.

**That disagreement is real, not noise.** A rerun of the same instrument over the same claims agrees
at 0.9983 with ordering ρ = +0.9643. Cross-instrument disagreement is an order of magnitude larger
than rerun drift.

**The equivalence result for drafters does not survive an instrument change.** Qwen ≡ Gemma in all
three domains under the primary instrument, in one of three under the verifier. The supportable claim
is the ordering — Gemma ≥ Qwen > DeepSeek in mathematics and data-mining — not equivalence.

**This is a statement about performance, not architecture.** The pipeline *is* model-agnostic and
domain-agnostic in the architectural sense: the drafter is replaceable behind a common contract with
no model-name conditionals anywhere in the pipeline, and subject matter enters through the corpus and
curriculum rather than through hardcoded semantics — the latter established by an AST-verified
remediation and confirmed against the evaluated artifacts. Three model families and three subject
domains were exercised through unchanged contracts. **Portability does not imply performance
invariance**, and the ablations exist to measure the difference.

## 6. Human supervision remains part of the method

Under the adjudicated construction workflow, **127 of 159 seed drafts (79.9%) required no more than
local editing** — 117 accepted unchanged, 10 minor edits. Fifteen needed major editing, ten were
replaced, and seven were judged to have no corpus support at all.

This is a **review-burden** figure for the seed arm under a specific workflow. It is not an accuracy
measure, not a cross-model comparison, and the corpus-gap count is pending revalidation. The honest
framing is that the pipeline substantially reduces, but does not remove, expert effort — and the
reference library is explicitly human-supervised.

## 7. Methodological contributions

The evaluation produced findings that stand independently of which pipeline wins, and they are what
make the pipeline conclusions credible:

- **Aggregation artifacts.** All-or-nothing claim aggregation tracks p^n and manufactures rankings
  that reflect draft length; the pattern reproduces out-of-domain.
- **Serial-position sensitivity.** Recovery of provably-present content collapses from 1.0000 at 17
  passages to 0.5905 at 123 — with truncation excluded — which invalidated an entire metric and
  forced the move to pooled per-passage judging.
- **Task-dependent sign reversal.** The same padding manipulation depresses one metric and inflates
  another, because an overloaded judge falls back on each task's default label.
- **Serving reproducibility.** Concurrent serving changed a verdict at temperature zero;
  batch-invariant kernels removed the discrepancy.
- **Rubric design.** The same judge on the same labels scored 0.556 as a binary verdict and 0.8611
  graded — the rubric, not the judge, was discarding the information.
- **Seed-audit methodology.** A stratified seed-blind reconstruction, comparing on substantive
  relationship rather than lexical overlap and using the expert's own edit codes as strata, separates
  "the seed shaped the content" from "the expert edited the weaker drafts".

## 8. Framing guidance

This is a **dialogue-evaluation thesis**. The KC pipeline is the offline grounding phase, and this
campaign establishes how far its output can be trusted as instrumentation. Present the
evaluation-method findings in that role — not as the contribution, but as the reason the
curriculum-grounding component is credible enough to build dialogue evaluation on.

**The gap to state plainly.** RQ2.1 asks for KC quality in terms of *coverage, grounding, and
usefulness for evaluation*. This campaign delivers strong evidence on coverage and grounding and
**none on usefulness** — that requires downstream evidence from the dialogue-evaluation phase.
Coverage and grounding are necessary conditions for usefulness, not demonstrations of it, and the
writeup must not let one stand in for the other.

## 9. What the paper must not say

See `PAPER_NONCLAIMS.md`. The three most tempting overclaims, given how close the numbers look:

1. that Proposed and DOS-RAG are *equivalent* at k=10 — no equivalence test was pre-registered;
2. that the pipeline is model-agnostic — it does not survive an instrument change;
3. that the abstention result is a settled safety advantage — the support boundary is contested.
