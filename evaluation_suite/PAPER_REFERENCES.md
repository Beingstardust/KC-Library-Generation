# Paper references, citations and paper-ready findings — living document

Persistent record of every external source consulted and every finding of ours that is
paper-worthy. **Updated over time**: new entries appended, existing entries revised when our
understanding changes. Version-controlled, so `git log -p` on this file is the history of what we
cited and when.

Companion to `EVALUATION_FINDINGS.md` (which records *what we measured*). This file records
*what the literature says*, *what we adopted or rejected and why*, and *what we can claim*.

Last updated: **2026-08-31**

---

## How to maintain this document

- Every source gets a stable key (`[R-nn]`), never reused, with a URL a reader can open.
- Record **what it says**, then **what we did about it** — adopted, rejected, or diverged, with the
  reason. A citation with no stated consequence for our design is not yet useful.
- When a source changes our design, add a line to the changelog and cross-reference the
  corresponding `F-nn` finding in `EVALUATION_FINDINGS.md`.
- Findings of ours that are publishable live in section C. Mark each as `NOVEL`, `CONFIRMS` (an
  existing result), or `CONTRADICTS`.

---

## A. Sources consulted

### [R-01] RAGAS — RAG evaluation framework and metric definitions
<https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/>
**Says:** Faithfulness is defined as the **ratio of supported claims to total claims** — extract
claims from the answer, check each against retrieved context, score = supported/total. Separately
defines **context precision** (retrieval efficiency: is the limited context window wasted?) and
**context recall** (retrieval completeness: did retrieval find everything needed?).
**What we did:** Two consequences. (1) Our v1 `M1` used an **all-or-nothing** aggregation (PASS only
if every claim is supported), which is *not* the standard and produced a length artifact — see
`F-34`. v2 adopts the RAGAS ratio as the primary faithfulness measure. (2) We had **no**
retrieval-side metric at all; v2 added context recall for the extrinsic family. *(Superseded
2026-09-02: context recall has no rank cutoff and is confounded by serial-position sensitivity;
the primary retrieval metrics are now pooled Recall@k / Precision@k / nDCG@k.)*

### [R-02] ARES — automated RAG evaluation with prediction-powered inference
Referenced alongside [R-01] in framework comparisons.
**Says:** Automates multi-dimensional RAG scoring but requires roughly **150 human-annotated
samples** for calibration.
**What we did:** Relevant to our weakest point. Our human calibration is **36 rows from a single
annotator** — roughly a quarter of what ARES treats as a calibration minimum, and without a second
annotator. This is a concrete, citable benchmark for why our judge-validation status and LOW_POWER
caveats are not excessive modesty (see `F-19`, `F-21`).

### [R-03] The Great Nugget Recall — automating fact extraction and RAG evaluation
<https://arxiv.org/html/2504.15068> · SIGIR 2025 · <https://dl.acm.org/doi/10.1145/3726302.3730090>
**Says:** Decompose reference material into atomic **nuggets**, label each **vital** or **okay**,
then assign support labels (`support` / `partial_support` / `not_support`) to each nugget against a
system response. Score by recall over vital nuggets. Automated nugget evaluation correlates with
manual judgment at run level around **Kendall's τ ≈ 0.78–0.90**, though per-topic agreement is
substantially lower.
**What we did:** Adopted wholesale for v2 completeness, replacing our holistic
`CORE_COMPLETE`/`MATERIAL_OMISSION` verdict. This directly addresses `F-17`: under a holistic
verdict, one disputed item (whether the exact Wilson interval formula is "defining") flipped an
entire KC; under nuggets it becomes an explicit `VITAL`/`OKAY` label on one nugget costing 1/N.
The τ figure also sets a realistic ceiling — we should not claim better agreement than the method
achieves in its own evaluation.

### [R-04] TREC 2025 RAG Track overview
<https://arxiv.org/pdf/2603.09891>
**Says:** Response evaluation proceeds in two steps — identify/classify nuggets from relevant
documents, then determine their presence in responses. Uses **strict vital recall**: recall over
vital nuggets that are *fully* supported.
**What we did:** Adopted the strict variant as our primary v2 score (`PARTIAL` counts as 0), with a
lenient variant (`PARTIAL` = 0.5) pre-registered as secondary so the choice is declared rather than
selected after seeing results.

### [R-05] Component-wise vs end-to-end RAG evaluation — the generator confound
Synthesised from RAG evaluation methodology literature; see also [R-09].
**Says:** End-to-end RAG accuracy has **three determinants**: retrieval quality, the generator's
ability to exploit retrieved context, and the generator's parametric knowledge. Changes in retrieval
may appear to help or hurt end-to-end performance depending on the generator. Best practice is to
evaluate components **separately and together**.
**What we did:** This is the formal statement of the project owner's objection — that fixing
Qwen3.8 as the drafter makes the extrinsic retrieval comparison unfair, and that Gemma4 might have
produced a different picture. v1 measured retrieval **only** through downstream drafts. v2 adds
drafter-independent context recall. Enabling detail we verified: the 7 arms use only **4 distinct
evidence configurations**, so retrieval can be scored with **no generator in the loop**.

### [R-06] Pairwise or Pointwise? Evaluating feedback protocols for bias in LLM-based evaluation
<https://arxiv.org/abs/2504.14716>
**Says:** Pairwise preferences **flip in ~35% of repeated trials versus ~9% for pointwise scores**.
Pairwise aligns better with human preference overall but is less stable and carries position bias,
mitigable by randomised swapping. Analytic pointwise rubrics suit debugging and longitudinal
monitoring; pairwise suits model selection.
**What we did:** Validated our existing design and we did **not** switch. We apply a pointwise
rubric per arm and only then compare **paired within KC** — retaining pointwise stability, gaining
the comparative benefit, and making position bias structurally impossible because the judge never
sees two drafts together.

### [R-07] LLM-as-judge bias: verbosity/length bias is heterogeneous by judge family
<https://arxiv.org/html/2510.12462v2> · survey: <https://arxiv.org/pdf/2411.15594>
**Says:** Longer answers score higher at matched quality. Critically, the direction is
**model-family dependent**: Llama-family judges exhibit classical verbosity bias (**+0.24 to +0.44**
on expansion pairs), Claude prefers shorter (−0.12), GPT-4o is near-neutral (−0.04). Practitioners
are advised to **test their own judge rather than assume**. Mitigations: penalise unnecessary
length, separate correctness from style, normalise for length.
**What we did:** Directly implicates our instrument. Our judge is **Selene-1-Llama-3.3-70B**, i.e.
the family the literature identifies as verbosity-biased — and we measured exactly that:
completeness rises monotonically with claim count (0.14 → 0.82 across buckets). We adopted the
recommended mitigation by reporting **length-adjusted completeness** via direct standardisation to
the pooled claim-count distribution (see `C-04`).

### [R-08] JudgeBench / systematic evaluations of LLM judges
<https://arxiv.org/pdf/2410.12784> · <https://arxiv.org/pdf/2606.19544>
**Says:** Judges can show high *reliability* (self-consistency) without *validity* (agreement with
ground truth); agreement, consistency and bias must be reported separately.
**What we did:** Supports our reporting structure. We report determinism (`F-08`, exact
reproducibility), agreement (`F-14`, which **failed**), and arm-independence (`F-21`) as three
separate claims, and we explicitly refuse to let reproducibility stand in for validity.

### [R-09] vLLM batch invariance (documentation)
<https://docs.vllm.ai/en/latest/features/batch_invariance/>
**Says:** `VLLM_BATCH_INVARIANT=1` makes output independent of batch size and request order via
fixed-reduction-order kernels. Requires compute capability ≥ 8.0; disables custom all-reduce under
tensor parallelism; may reduce throughput; documented as beta.
**What we did:** Adopted, and it resolved a real defect. Default-kernel concurrency changed 1 verdict
in 144; batch-invariant concurrency changed **0 of 144** (`F-06`→`F-07`). Measured cost: KV cache
59,200 → 54,000 tokens, ~1.9× throughput gain rather than the ~9× unsafe concurrency appeared to
offer.

### [R-10] Defeating Nondeterminism in LLM Inference
<https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/> ·
code: <https://github.com/thinking-machines-lab/batch_invariant_ops>
**Says:** Nondeterminism in LLM serving arises from batch-size-dependent reduction order in kernels,
not from sampling alone. Batch-invariant kernels fix a single reduction strategy regardless of
batching.
**What we did:** The mechanism behind `F-06`/`F-07` and the theoretical basis for our reproducibility
claim `C-01`.

---

## B. Metric provenance — every metric traced to a reference

Each metric must be interpretable and grounded, not an arbitrary number.

| our metric | construct | grounded in | status |
|---|---|---|---|
| per-claim faithfulness | groundedness of claims in retrieved evidence | [R-01] RAGAS faithfulness | **v2 primary** |
| all-or-nothing M1 | (non-standard aggregation of the above) | none — our own | v1 only, retained with `F-34` caveat |
| vital-nugget recall | knowledge coverage of the reference | [R-03], [R-04] TREC nuggets | **v2 primary** — adoption test PASSED, AUC 0.858 vs 0.700 (`F-39`) |
| holistic M3 | completeness | none — our own | v1 only; failed qualification `F-14` |
| ~~context recall~~ | did retrieval surface what was needed | [R-01] context recall | **WITHDRAWN 2026-09-02** — no rank cutoff, and confounded by serial-position sensitivity (F-45). Superseded by pooled Recall@k / Precision@k / nDCG@k. |
| context precision | was the context window wasted | [R-01] context precision | v2 secondary |
| length-adjusted completeness | completeness net of verbosity bias | [R-07] mitigation | **v2 reporting requirement** — computed by direct standardisation (`F-44`) |
| abstention rate | system declines to answer | our own; reported as behaviour, not quality | primary outcome |
| M2 correctness | factual correctness vs reference + authority | partially [R-01] answer correctness | at ceiling, `F-32` |
| TARGET alignment | is the response about the right thing | [R-01] answer relevance (loosely) | at ceiling, `F-32` |

**Metrics with no reference grounding are flagged above and are being replaced.** That was the
substance of the project owner's critique and it is accepted rather than argued.

### Instrument validation specific to v2

The v2 metrics are new prompts, so they are a new instrument and were validated as one rather than
assumed. Each check is pre-registered with a git-verifiable timestamp preceding its result.

| check | question it answers | pre-registration | outcome |
|---|---|---|---|
| adoption test | does nugget recall separate the human labels better than holistic M3? | `OVERHAUL_PROTOCOL_v2.md` | **PASSED**, AUC 0.858 vs 0.700 (`F-39`) |
| prompt-offset calibration | are the two recall prompts on a common scale? | `locks/PREREG_F40_calibration.md` (`50562e5`) | **B = 0.0000** — no constant offset (`F-40`) |
| evidence-dilution test | does a larger passage set depress the judge independently of content? | `locks/PREREG_F45_dilution.md` (`f7261a1`) | see `F-45` |
| length adjustment | is completeness measuring coverage or verbosity? | `F-35` mandate | 3/3 extrinsic robust; 1 intrinsic ranking withdrawn (`F-44`) |
| cross-instrument agreement | does the result depend on which cluster ran it? | `F-12` | max abs delta 0.0034 over 7 arms, mean 0.0013 |

---

## C. Our findings that are paper-ready

### [C-01] Batch-invariant serving is required for reproducible LLM-judge evaluation · NOVEL
"temperature 0 + fixed seed" does **not** imply reproducibility for a judge served with request
batching. We measured 1 verdict flip in 144 under default kernels, isolated it to concurrency by
re-running the divergent row sequentially three times on the same node (3/3 identical, matching a
different GPU), and eliminated it with `VLLM_BATCH_INVARIANT=1` (0/144).
**Why publishable:** judge studies routinely report greedy decoding as a reproducibility guarantee
without stating whether serving was batch-invariant. Supported by [R-09], [R-10]; evidence `F-06`,
`F-07`, `F-08`.

### [C-02] All-or-nothing claim aggregation manufactures spurious system rankings · NOVEL
Deriving faithfulness as "PASS only if every claim is supported" makes the score a function of draft
length: observed ≈ p^n, predicted within 0.1–1.0 points for the arms tested. A **1.45-point**
per-claim difference was reported as **13.42 points** (~9× amplification), and the ordering of two
retrieval arms **inverts** between the two aggregations.
**Why publishable:** a concrete demonstration that a plausible-looking aggregation choice can
reverse a published ranking. Contrasts with the RAGAS ratio [R-01]. Evidence `F-34`.

### [C-03] A pre-registered guard can be non-commensurable with its own statistic · NOVEL
Our registered noise guard compared a **paired within-KC difference** against an **absolute**
judge–human disagreement rate. Pairing already cancels the systematic offset that produces that
rate, so the guard double-counted a removed bias and nullified **24 of 24** comparisons — including
a 73-vs-9 discordant split at p = 0.0.
**Why publishable:** pre-registration is necessary but not sufficient; a registered rule can be
internally invalid. Our audit trail (defect recorded before results; unmodified run committed before
amendment) is a worked example of correcting one without forfeiting the guarantee. Evidence `F-28`,
`F-29`, `AMENDMENT_01`.

### [C-04] Verbosity bias is measurable and separable in a knowledge-coverage metric · CONFIRMS [R-07]
Completeness rises monotonically with claim count (0.14 / 0.42 / 0.64 / 0.79 / 0.82 across buckets)
under a Llama-family judge — the family [R-07] identifies as verbosity-biased. Direct
standardisation to the pooled claim-count distribution separates verbosity from content:

| arm | raw | length-adjusted | Δ |
|---|---|---|---|
| Qwen3.8 (Proposed) | 0.860 | **0.845** | −0.015 |
| DeepSeek-R1 | 0.585 | **0.671** | **+0.086** |
| Gemma4 | 0.615 | 0.620 | +0.004 |
| BaseDense | 0.414 | 0.426 | +0.012 |

**Substantive result:** Qwen3.8's completeness advantage **survives** adjustment (genuine content
coverage, not verbosity), DeepSeek-R1's apparent deficit is **largely a verbosity artifact** — once
adjusted it overtakes Gemma4 — and BaseDense remains worst, i.e. a genuine *retrieval* deficit
rather than a writing-style effect.

### [C-05] Reference-based metrics are undefined, not merely unmeasured, outside the reference domain · NOVEL (methodological)
KC-id overlap between our reference library and two further domains (mathematics, sociology) is
**exactly zero**, so correctness/completeness/alignment cannot be computed there at all. Only
reference-free metrics (per-claim faithfulness, abstention) transfer.
**Why publishable:** a clean statement of the scope limit of reference-based evaluation, and an
argument for reporting reference-free metrics alongside so that cross-domain claims remain possible.

### [C-06] Draft-mediated evaluation can invert a retrieval ranking · NOVEL
Measuring retrieval architectures through downstream generation reversed the ordering relative to
measuring retrieval directly. Through drafts, DOS-RAG appeared the strongest extrinsic arm
(per-claim faithfulness 0.980 vs Proposed 0.953); judged on the retrieved evidence itself with no
generator in the loop, that advantage disappears — **the two become statistically
indistinguishable** (vital context recall 0.698 vs 0.708; Δ = +0.0104, 95% CI [-0.0613, +0.0814],
p = 0.824).

State the claim as *the draft-mediated ordering is not reproduced at the retrieval layer*, **not**
as "Proposed wins on retrieval" — the latter is unsupported (F-37 correction (b)).

**RETRACTED 2026-08-31 — the efficiency claim.** An earlier version of this entry read
"BaseDense retrieves 7.2x more evidence than Proposed yet recovers less required content (0.466 vs
0.708)". **That is withdrawn.** F-45 shows the context-recall judge recovers only 0.5905 of nuggets
that are *provably present* when the set holds 123 passages, against 1.0000 at 17. BaseDense's
0.4664 sits **below the ceiling a perfect retriever would score at its set size**, so the number is
not a measurement of retrieval quality and the comparison carries no claim. The underlying claim may
well be true; we have not measured it, and say so.

**What survives, stated end-to-end rather than at the retrieval layer:** Proposed produces
substantially more complete drafts than BaseDense — vital-nugget recall Δ = **+0.2539** raw,
**+0.2269** length-adjusted, 95% CI [+0.1497, +0.3011]. Nugget recall is judged against the **draft**
and never against a passage set, so it is immune to F-45. Against DOS-RAG (33.7 passages, ceiling
0.9903) the context-recall comparison remains valid and is **not** significant (p = 0.824), while
Proposed does lead on nugget recall (Holm p = 0.0003, surviving length adjustment).

Robustness: the ranking is unchanged under both micro- and macro-averaging (F-37 correction (a)),
and all three extrinsic nugget-recall comparisons survive length adjustment (F-44). Absolute values
are flattered for Proposed by non-random reference coverage (F-42).

**Why publishable:** a concrete, measured instance of the component-vs-end-to-end confound [R-05],
strong enough to overturn a published-style conclusion rather than merely add noise. Evidence
`F-37`, `F-42`, `F-44`, `F-45`.

### [C-07] Evidence-grounded abstention held across an entire campaign · NOVEL
Across all 1113 judged rows and all seven arms, **no system ever produced a description from an
empty evidence set**. Every one of the 23 rows where retrieval returned nothing resulted in
abstention rather than an ungrounded draft.

Separating abstentions into **forced** (nothing retrieved, so declining is correct) and **chosen**
(evidence available, drafter declined anyway) makes the distinction reportable: chosen abstention
ranges 5-12 rows per arm, forced 0-7, and the ungrounded-draft cell is **0 for every arm**.

**Why publishable:** the failure mode most often attributed to RAG systems — asserting content with
no retrieved support — was measured directly and did not occur once. It is a property of the
harness's abstention contract rather than of any single pipeline, and should be attributed that way.
Reported over all rows rather than the scored subset, because the reference-coverage exclusion
(`F-42`) removes precisely the zero-evidence KCs and would have hidden the phenomenon entirely.
Evidence `F-43`.

### [C-08] LLM-judge context recall is serial-position sensitive, so it cannot compare retrieval systems with different top-k · NOVEL (methodological)
Embedding a passage that **provably contains every required nugget** among topically separated
distractors, and varying only the set size, the judge's recall of that provably-present content
collapses:

| passages in set | vital-nugget recall (ground truth = 1.0) |
|---|---|
| 17 | **1.0000** |
| 33 | **0.9934** |
| 123 | **0.5905** |

Paired drop 17→123 = **0.4095**, 95% CI [+0.3322, +0.4868], n = 151, 453 calls, zero failures.

The mechanism is **serial position**, isolated cleanly: within the 123-passage condition every
prompt has identical length and only the target's position varies, and recall falls from 1.0000
(positions 0–33) to 0.20–0.40 (positions 59+). **Truncation is excluded** on two independent grounds
— a truncated prompt would collapse to exactly 0.0 past a fixed cut point, yet the last decile still
scores 0.3125, and the server ran `--max-model-len 40960` against ~25k-token prompts with every call
returning `OK`.

**Consequence for the field:** any RAG evaluation that compares a top-k=10 system against a
top-k=100 system on judge-scored context recall is measuring **set size as much as retrieval
quality**, and the bias runs *against* the system that retrieves more. We found no contemporary
RAG-evaluation work controlling for this, and the standard frameworks [R-01] do not raise it; the
nugget-based TREC line [R-03], [R-04] uses human assessors over pooled passages and does not
characterise the automated-judge case.

**Why this is the strongest methodological contribution here:** it was found by testing the
instrument against a case where the correct answer was known **in advance**, it was pre-registered
before the result existed (`locks/PREREG_F45_dilution.md`, commit `f7261a1`), and it **forced us to
retract our own favourable result** ([C-06]) rather than being used to explain away an unfavourable
one. Evidence `F-45`.

**The bias is task-dependent and changes sign, which is the subtler half of the result.** The same
padding manipulation was applied to per-claim faithfulness (n = 143, controlled paired design:
identical claims, only the padding differs):

| metric | what the judge must do | change when padded 18 → 123 passages |
|---|---|---|
| context recall | locate a **specific** nugget | **-0.4095** [-0.4868, -0.3322] |
| per-claim faithfulness | find support for a claim **anywhere** | **+0.0175** [+0.0024, +0.0325] |

Padding *depresses* one and *inflates* the other. The unifying account is that an overloaded judge
falls back on the task's **default label** — ABSENT when asked to find a specific item, SUPPORTED
when asked whether anything supports a claim. So "large contexts degrade LLM judges" is too coarse a
statement to act on: the direction depends on which way the task's default points, and a correction
applied with the wrong sign would make matters worse.

**Practical mitigation for others:** report the judge's ceiling at each system's own top-k, measured
on known-present content, and treat a metric as comparable only across systems whose ceilings match
— **and establish the sign empirically per metric rather than assuming degradation.** Metrics read
off the **generated answer** rather than the passage set (nugget recall here) are unaffected and
remain comparable. Evidence `F-45`, `F-46`.

---

## Changelog

| date | change |
|---|---|
| 2026-09-01 | [C-08] extended with F-46: the same padding INFLATES faithfulness (+0.0175) while DEPRESSING context recall (-0.4095). An overloaded judge falls back on each task's default label, so the bias changes sign by task. |
| 2026-08-31 | **[C-06] efficiency claim RETRACTED** per F-45 (the instrument cannot see content late in a 123-passage set); restated end-to-end on nugget recall, which is immune. **[C-08] added**: LLM-judge context recall is serial-position sensitive and cannot compare systems with different top-k. |
| 2026-08-31 | [C-07] added (abstention discipline: 0/1113 ungrounded drafts). Provenance table refreshed; v2 instrument-validation table added with pre-registration commits. |
| 2026-08-31 | [C-06] corrected: "Proposed leads" withdrawn (p=0.824 vs DOS-RAG); restated as the draft-mediated ordering failing to reproduce at the retrieval layer, plus the efficiency result. Figures moved to macro-averaging per F-37. |
| 2026-08-31 | [C-06] added: draft-mediated evaluation inverted the retrieval ranking; BaseDense shown 7.2x less evidence-efficient. |
| 2026-08-31 | Document created. [R-01]…[R-10] recorded; metric provenance table added; [C-01]…[C-05] drafted. Prompted by the requirement that every metric be interpretable through references rather than an arbitrary number. |
