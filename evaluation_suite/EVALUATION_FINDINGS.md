# Evaluation findings — living document

Single running record of everything established while building and validating the reference-based
LLM-judge evaluation for the KC_L pipeline. **This file is updated over time**: findings get added,
corrected, or superseded as evidence changes. It is version-controlled, so `git log -p` on this file
is the authoritative history of what we believed and when.

Last updated: **2026-09-02** (documentation consolidation. Model-agnosticism DOWNGRADED to an ordering claim by F-57; seed audit sized rather than settled; abstention PROVISIONAL pending the support-boundary audit. See `paper_consolidation/PAPER_CLAIM_LEDGER.md`.)

---

## How to maintain this document

**Never delete a finding.** If it turns out to be wrong or incomplete, change its status and append
a correction underneath it. The wrong belief and the reason it changed are both part of the record —
several findings here were only reachable *because* an earlier one was wrong in an instructive way.

**Status values**

| status | meaning |
|---|---|
| `ACTIVE` | current best understanding, still relied on |
| `SUPERSEDED` | replaced by a later finding; the operational conclusion changed |
| `CORRECTED` | the claim was too broad or too narrow; scope amended in place |
| `OPEN` | known unknown; not yet settled |

**Each finding carries:** an ID (`F-nn`, never reused), a date, a status, the claim, the evidence
(file path or commit), and the operational consequence. Cite evidence that a reader can re-check —
a path, a commit hash, a measured number. Not "we observed that…".

**When adding:** append to the relevant section, take the next free ID, and add a changelog line.

---

## A. Structured output and grammar enforcement

### F-01 · `oneOf` is enforced; `if/then/else` is silently dropped · ACTIVE
JSON-Schema `if/then/else` compiles without error under XGrammar but is **not** present in the
emitted grammar, so a conditional binding that looks enforced is not. `oneOf` branches do
materialise and genuinely bind each label to its permitted evidence family.
**Evidence:** `reference_eval/tests/test_grammar_enforcement.py` (18 checks, verified by reading the
emitted EBNF, not by trusting compilation).
**Consequence:** every conditional binding in the reference schemas uses `oneOf`. The test is re-run
whenever the serving stack changes — it passed unchanged on the Cluster-B CUDA-12 rebuild.

### F-02 · Field order determines branch reachability · ACTIVE
In a `oneOf`-branched schema the model selects its branch by emitting the next **key**. With the
verdict field last, the model commits to a branch before articulating a verdict, and the
`MATERIAL_*` branch became effectively unreachable — measured **0/36** `MATERIAL_OMISSION` under
label-last versus a 19/14 split under label-first.
**Consequence:** the verdict is the **first** field in all branched schemas.

### F-03 · A required trailing free-text field causes truncation stalls · ACTIVE
With `rationale` required and last, the model — having committed its verdict — must open a string it
has nothing to put in, and inter-token whitespace is a legal continuation. Responses ran to the
1500-token cap. Making `rationale` optional (still present in `properties`) fixed it: 18/18 preflight
pass, responses 47–114 tokens.
**Consequence:** `rationale` is optional in every branched schema; all strings are length-bounded with
a character class excluding CR/LF.

### F-04 · Exact-repetition and bounded-length compile as intended · ACTIVE
`minItems == maxItems == N` compiles to an exact repetition operator; `maxLength` compiles to bounded
repetition over a class excluding newlines. Verified for N ∈ {2,3,7,12}.

---

## B. Decoding determinism and reproducibility

### F-05 · `frequency_penalty` is a semantic confound, even at temperature 0 · ACTIVE
vLLM applies frequency penalty directly to generation logits, so a nonzero value is **not** a
formatting control. Two penalty-free runs produced an identical M1 distribution (20 FAIL / 14 PASS)
while `penalty=0.2` shifted it to 22/12 — under greedy decoding.
**Consequence:** frozen at `0.0`. Recorded in `FINAL_JUDGE_DECODING_MANIFEST.json` with the rationale
that it was chosen to remove a confound, **not** because it maximised sentinel accuracy.

### F-06 · Request concurrency changes verdicts under default kernels · SUPERSEDED by F-07
Re-running the 36 calibration rows at concurrency 6 and diffing against the sequential predictions
found **1 differing verdict in 144** (`HC-fe4c7df687de961fe9ef`, M1: PASS → FAIL). Cause isolated:
the divergent row was re-run on the *same node* sequentially three times, returning PASS with 9/9
`SUPPORTED` each time, matching the original run from a different GPU. Concurrency was the only
varying factor.
**Evidence:** `reference_eval/output/gate_equivalence_concurrency.json`, commit `f85e21c`.
**Original consequence (now superseded):** production runs must be sequential.

### F-07 · `VLLM_BATCH_INVARIANT=1` makes concurrency verdict-neutral · ACTIVE
F-06 was correct for vLLM's **default** kernels but incomplete — it was reasoned from first
principles without checking whether the problem was already solved upstream. It is. vLLM ships a
batch-invariance mode using a fixed reduction order independent of batch size and request order, and
it is present in our pinned vLLM 0.27.1 (`envs.py`, `model_executor/layers/batch_invariant.py`).

| configuration | verdicts differing from frozen sequential baseline |
|---|---|
| default kernels, concurrency 6 | 1 / 144 (DIVERGENT) |
| **batch-invariant, concurrency 6** | **0 / 144 (EQUIVALENT)** |

**Evidence:** `reference_eval/output/gate_equivalence_batch_invariant.json`, commit `ed296b2`.
**Cost, measured:** disables custom all-reduce under tensor parallelism; KV cache 59,200 → 54,000
tokens; longer startup; ~63 s/row at concurrency 6 versus ~120 s/row sequential — a **~1.9×** gain,
not the ~9× that unsafe concurrency appeared to offer.
**Consequence:** concurrency is permitted **only** with `VLLM_BATCH_INVARIANT=1` and only after the
equivalence gate passes for that configuration. With default kernels, F-06 still stands.

### F-08 · Sequential decoding is exactly reproducible across GPUs · ACTIVE
Three sequential runs of the same row on one node returned byte-identical per-claim verdicts, and
reproduced a run from a *different* GPU. Combined with F-09, the instrument is stable across
hardware provided batching is controlled.

### F-09 · Reportable: "temperature 0 + fixed seed" is not a reproducibility guarantee · ACTIVE
Determinism holds per-request; it does not survive arbitrary batch composition. A judge study that
reports greedy decoding as a reproducibility guarantee, without stating whether serving was
batch-invariant, has an undisclosed source of variance. Ours can now be stated precisely.
**Consequence:** worth stating explicitly in the paper's reproducibility section.

---

## C. Infrastructure and portability

### F-10 · Cluster-B cannot run an Cluster A-built GPU stack · CORRECTED (scope narrowed)
Copying the Cluster A venv to Cluster-B fails on two independent grounds: the NVIDIA driver is `550.54.14`
(CUDA 12.4 max) while the Cluster A stack is `torch 2.13.0+cu130` (CUDA 13, needs driver 580+), and Cluster-B
is Rocky 8.4 (glibc 2.28) versus Cluster A Rocky 9.8 (glibc 2.34).
**Correction (2026-08-30):** the original claim "Cluster-B cannot run Selene" was **too broad**. A peer
runs Selene-70B on Cluster-B routinely. What fails is the *Cluster A-built CUDA-13 stack*, not the model.
**Consequence:** a Cluster-B-native CUDA-12 build is required; see F-11.

### F-11 · PyPI vLLM wheels are CUDA-13-only; a CUDA-12.4 source build works · ACTIVE
`vllm/_C_stable_libtorch` requires `libcudart.so.13` regardless of which torch is paired with it, and
`wheels.vllm.ai/cu126` does not exist. Building vLLM **0.27.1 from source** against the CUDA 12.4
toolkit on Cluster-B succeeded (`vllm-0.27.1+cu124-cp311-cp311-linux_x86_64.whl`, 283 MB), keeping the
manifest-pinned version and changing only the CUDA build target.
**Required to make it build offline** (compute nodes have neither git nor network): CUTLASS v4.4.2,
triton_kernels v3.5.1, and 7 external projects staged at their exact pinned revisions via `*_SRC_DIR`
overrides, plus 6 git submodules populated at their pinned commits.
**Also needed:** an import-only `llguidance` stub (its build needs GLIBC_2.34; the backend is unused
since XGrammar is pinned, and the stub raises loudly if ever invoked), a `pysqlite3` bridge for the
missing `_sqlite3`, and removal of `flashinfer_python` (an extra that is not in the frozen Cluster A stack
and whose `fd_exchange.py` uses a Python 3.12-only annotation).

### F-12 · A100/TP2 is verdict-identical to the frozen H100/TP4 instrument · ACTIVE
Despite different GPU architecture, different tensor parallelism, and a CUDA-12 rather than CUDA-13
build, the rebuilt instrument produced **zero** primary-verdict differences across all 36 sentinels
and all 5 tasks. Distributions matched exactly: M1 14/20, M2 18/15, M3 19/14, TARGET 24/9, M4B 33/1.
**Evidence:** `reference_eval/output/cluster_b_equivalence_comparison.csv` (0 changed rows).
**Consequence:** the two instruments may share a campaign; every output row is tagged with its
`instrument` so provenance stays recoverable.

### F-13 · `gpu_memory_utilization` had to rise 0.90 → 0.95 on A100 · ACTIVE
2×A100 80GB leaves only 3.32 GiB for KV cache after ~132 GB of weights, short of the 6.25 GiB needed
for `max_model_len=40960`. Raising utilisation to 0.95 yielded 9.04 GiB (59,200 tokens).
**Why this and not a smaller context:** `gpu_memory_utilization` is a memory-allocation knob and does
not affect greedy decoding; reducing `max_model_len` to the suggested 21760 **would** have changed
what the judge sees, and some M2/TARGET prompts embed 150–260 authority items. User-approved,
disclosed as a deviation.

---

## D. Judge qualification (absolute)

### F-14 · `JUDGE_QUALIFIED = false` · CORRECTED by F-55 (blanket status too broad; see the note under F-55)
Formal qualification against the pre-registered protocol returned: M3_CORE_COMPLETENESS
**NOT_QUALIFIED**; M1, M2, TARGET, M4A **INSUFFICIENT_VALIDATION_SUPPORT**.
**Evidence:** `reference_eval/output/qualification/qualification_decision.json`.
M3 was the only properly-powered task (n=36, 20 PASS / 16 FAIL): raw agreement 0.556 (gate 0.80),
Gwet AC1 0.392 (gate 0.65), PASS recall 0.40 (gate 0.75); FAIL recall 1.00 (gate 0.75, met).
**Consequence:** the judge is **not** licensed for absolute quality claims. The final campaign was
not run on this basis; see section E.

### F-15 · The M3 failure is one-directional over-flagging · ACTIVE
Confusion: `PASS→FAIL 12`, `PASS→PASS 8`, `FAIL→FAIL 12`, `FAIL→NOT_JUDGEABLE 4`. False-pass rate
**0.00**, false-fail rate **0.60**. The judge catches every material omission the annotator found and
misses none; it also flags 12 of 20 drafts the annotator judged complete.

### F-16 · The calibration sample is clustered, not 36 independent rows · ACTIVE
The 36 rows are (KC × arm) pairs drawn from only **17 distinct KCs**. The 12 M3 false-fails come from
7 KCs, and **`KC_EVAL_COMP_002` alone contributes 6 of 12 — all six of its rows**. That is one
KC-level judgement replicated across arms, not six independent errors.
**Consequence:** disclose as a limitation. Recomputing the gate at KC level *after* seeing it fail
would forfeit the pre-registration; a clustered analysis must be pre-registered before any re-run.
All ablation statistics use **KC as the unit of analysis**.

### F-17 · The dominant M3 failure is a construct-boundary dispute, and the judge is factually right · ACTIVE
`KC_EVAL_COMP_002` (Confidence Interval for Accuracy) has a reference centred on the **Wilson score
interval**. All six drafts omit that exact formula (three substitute a Wald approximation, three give
none). The judge's `missing_defining_components` cite the formula in all six rows, plus the binomial
model, the role of *z*, and the effect of *N* — every item verifiably present in the reference and
absent from the draft. The annotator called the same omission "not a material defect".
**Evidence:** `reference_eval/output/qualification/M3_DISAGREEMENT_DIAGNOSTIC.md`.
**Consequence:** the open question is definitional, not a model deficiency — *is a reference's exact
closed-form formula a defining component?* No change of judge model resolves it. This KC also yields
**zero** between-arm discrimination while consuming 6 of 36 calibration rows.

### F-18 · Correctness appears to leak into the completeness construct · OPEN
Annotator notes repeatedly separate the two — "M2 fails … **however** it adequately explains" — while
the judge returns `MATERIAL_OMISSION` on those same rows. If confirmed at scale this is a
prompt/rubric separation defect, and would be inherited by any substitute judge.
**Not yet quantified across the full campaign.**

### F-19 · Human gold is single-annotator and partly unstable · ACTIVE
`human_human` agreement is `{}` — not computable. Two contested rows carry explicit
"REVISED on recheck" flips, and `KC_DE_MISS_004` is labelled `CORE_COMPLETE` while its own note says
it "materially underdefines the KC".
**Consequence:** low judge–human agreement cannot be cleanly attributed to judge error rather than
annotation error. The protocol's own instruction — flag the construct first when human–human
agreement is poor — cannot be executed. This caveat must travel with every qualification number.

---

## E. Comparative (ablation) qualification

### F-20 · Ablation ranking needs arm-independence, not absolute accuracy · ACTIVE
Every arm drafts the same KCs, so the comparison is **paired within KC**, and a constant judge
threshold offset cancels. F-17 is exactly that shape: the dominant failure KC returned
`MATERIAL_OMISSION` on all six arms, carrying zero between-arm signal.
**Consequence:** a separate, weaker, testable criterion was **pre-registered before being computed**
(`reference_eval/locks/COMPARATIVE_USE_PROTOCOL.md`, committed at `246c040` with the analysis script
and no results).

### F-21 · No arm-dependent disagreement detected · ACTIVE
Fisher–Freeman–Halton exact test on arm × {agree, disagree}: M1 p=0.418, M2 p=0.247, M3 p=0.721,
TARGET p=0.855. All ≥ α=0.05 → **COMPARATIVE_QUALIFIED** for those four. M4A returns
`INSUFFICIENT_COMPARATIVE_SUPPORT` (no labels — it is skipped during calibration because no
reference-claim decomposition exists for calibration KCs).
Supporting detail: on M3 the signed bias (over-flag − under-flag) is positive on five of six arms and
zero on the sixth — uniform over-flagging, which is what cancels under pairing.
**Evidence:** `reference_eval/output/qualification/comparative_qualification.json`, commit `b24e721`.
**Limitation, flagged on every task:** 4–6 rows per arm, so the test has **low power**.
Non-significance is weak evidence of arm-independence, **not proof**, and must be reported as such.

### F-22 · Pointwise-plus-paired-analysis is the right protocol; pairwise judging is not · ACTIVE
Literature check: pairwise preferences flip in ~35% of repeated trials versus ~9% for pointwise
scores, and pairwise carries position bias. Our design applies a pointwise rubric to each arm
independently and only then compares paired within KC — keeping pointwise stability, gaining the
comparative benefit, and making position bias structurally impossible since the judge never sees two
drafts together.
**Source:** *Pairwise or Pointwise? Evaluating Feedback Protocols for Bias in LLM-Based Evaluation*
(arXiv:2504.14716).

---

## F. Ablation dataset

### F-23 · Full paired coverage · ACTIVE
7 frozen arms × 159 KCs = **1113 rows**, with **159/159 KCs present in all 7 arms** (protocol
condition C4 satisfied). Extraction deliberately reuses the calibration contract
(`draft.contextual_kc_draft.text` + packets `evidence_for_synthesis`) so ablation rows and
human-calibrated rows are built identically.
**Evidence:** `reference_eval/build_ablation_rows.py`, `data/ablation_rows_meta.json`.

### F-24 · Abstention rates differ markedly by arm · ACTIVE
Empty drafts are genuine abstentions and are retained, not filtered:

| arm | abstentions / 159 |
|---|---|
| extrinsic_DOS-Q | 5 |
| intrinsic_P-G | 10 |
| intrinsic_P-D | 10 |
| extrinsic_B-Q | 12 |
| intrinsic_P-Q | 14 |
| extrinsic_P-Q | 15 |
| sensitivity_DOS-Q_matched | 17 |

**Consequence:** this is an evaluation outcome in its own right — how a system behaves when it
declines to draft is part of what is being measured — and is reported alongside the rubric metrics,
not hidden inside them.

### F-25 · Six unique primary arms, not five · ACTIVE
`intrinsic.P-Q` and `extrinsic.P-Q` are genuinely different artifacts (different sha256, different
build commits), so the specification's "five unique primary arms because Proposed/Qwen is shared" does
not hold. Also corrected at freeze time: `seed_source_designation` is `intrinsic_P-Q` (159/159 exact
match), superseding an earlier `extrinsic_P-Q` designation that matched only 17/159.
**Evidence:** `reference_library/00_freeze/CANDIDATE_FREEZE_MANIFEST.json`.

---

## G. Open questions

- **F-18** — is correctness leaking into the completeness construct at scale? Quantifiable once the
  campaign completes.
- **Definitional (from F-17)** — is a reference's exact closed-form formula a "defining component"?
  Owner decision. Either add an explicit rubric rule (breaks the freeze, mandates re-derivation and
  re-run) or report M3 as construct-limited, as was already done for M4B.
- **F-19** — a second independent annotator remains the single highest-value unblock: without it,
  judge error and annotation error cannot be separated.
- **M4A** — never validated; no reference-claim decomposition exists for the calibration KCs.

---

## H. Ablation results (campaign complete, 2026-08-31)

### F-26 · Campaign completed: 1112/1113 rows across two verified-equivalent instruments · ACTIVE
7 arms x 159 KCs. 553 rows on the ZERO-DEVIATION frozen instrument (Cluster A ant2, 4xH100, TP4,
CUDA 13, sequential) and 559 on the Cluster-B CUDA-12.4 rebuild (A100 TP2, `VLLM_BATCH_INVARIANT=1`,
concurrency 6). Combinable because F-12 (36/36 sentinels identical across instruments) and F-07
(batch-invariant concurrency identical to sequential). Every row carries an `instrument` tag.
158 of 159 KCs are complete across all 7 arms.
**Evidence:** `reference_eval/output/ablation_predictions_{ants_halfA,cluster_b_halfB}.jsonl`, commit `f8865e1`.

### F-27 · One row lost to a blinding-guard false positive · ACTIVE
`KC_EVAL_ENS_004|sensitivity_DOS-Q_matched` raised `BlindingViolation`: the DRAFT text contains the
phrase "variant proposed", which matches a forbidden-pattern regex. No arm identity was leaked - the
guard is over-broad here - but `assert_blinded()` raises rather than warns by design.
**Consequence:** excluded and disclosed rather than re-run with a bespoke allow-list. Suppressing a
blinding check to recover one exploratory-arm row would be a bad trade. Affects the exploratory
sensitivity arm only.

### F-28 · The pre-registered noise guard nullified all 24 comparisons · SUPERSEDED by F-29
Applied as written, the guard flagged **24 of 24** comparisons `WITHIN_INSTRUMENT_NOISE`, including
extrinsic M3 Proposed vs BaseDense (delta +0.421, CI [+0.322,+0.513], p=0.0, 73 vs 9 discordant) and
intrinsic M3 Qwen3.8 vs Gemma4 (29 discordant pairs, **all** one-directional, p=0.0).
**Evidence:** commit `63fc707` (the unmodified as-specified run).

### F-29 · The guard compares non-commensurable quantities; amended · ACTIVE
The guard subtracted an **absolute** judge-human disagreement rate from a **paired** within-KC
difference. Pairing already cancels the systematic offset that produces that rate - F-15 measured it
directly (false-fail 0.60, false-pass 0.00, one-directional) and F-21 confirmed it is
arm-independent - so the subtraction double-counts a bias already removed. At M3's threshold of
0.444 no achievable effect could clear it.
**Timing matters and is verifiable:** the defect was recorded in commit `5dbdf54` **before** results
existed, and the as-specified run was committed unmodified at `63fc707` before any amendment.
**Amendment:** for a paired difference, inference rests on controls the protocol already registered -
Holm-adjusted exact McNemar **and** a KC-clustered bootstrap CI excluding zero. Both verdicts are
reported side by side; the original is never hidden.
**Evidence:** `reference_eval/locks/AMENDMENT_01_noise_guard.md`.

### F-30 · Intrinsic ablation: drafters differ, and differently by construct · ACTIVE
Evidence held fixed (Proposed); drafter varies. Significant under the amended rule:

| task | ordering | key effect |
|---|---|---|
| M1 faithfulness | **Gemma4 .820 > Qwen3.8 .685 > DeepSeek-R1 .453** | all 3 pairs significant; G vs D delta +0.364 |
| M3 completeness | **Qwen3.8 .816 > Gemma4 .620 ~ DeepSeek-R1 .572** | Q > G (+0.193) and Q > D (+0.243); G vs D not significant |

**The ordering inverts across constructs**: Gemma4 is the most faithful drafter, Qwen3.8 the most
complete. DeepSeek-R1 is worst on faithfulness by a wide margin.

### F-31 · Extrinsic ablation: retrieval architecture, same inversion · ACTIVE
Drafter held fixed (Qwen3.8); retrieval varies.

| task | ordering | key effect |
|---|---|---|
| M1 faithfulness | **DOS-RAG .844 > BaseDense .735 ~ Proposed .694** | DOS > P (+0.190) and DOS > B (+0.144); P vs B not significant |
| M3 completeness | **Proposed .816 > DOS-RAG .664 > BaseDense .395** | all 3 pairs significant; P > B delta +0.421 |

Again a faithfulness/completeness inversion: **DOS-RAG yields more faithful drafts, Proposed yields
more complete ones.** Proposed beats BaseDense on completeness by 42 points (73 vs 9 discordant KCs).

### F-32 · M2 and TARGET are at ceiling and discriminate between no arms · ACTIVE
M2 correctness .912-.977 and TARGET alignment .973-1.000 across all seven arms; **zero** significant
pairwise differences on either, under either verdict rule.
**Consequence:** report as a construct finding, not a null. These two metrics lack discriminative
power at this quality level and should not be presented as evidence of arm equivalence.

### F-33 · Abstention rate varies threefold and is a primary outcome · ACTIVE
DOS-RAG 3.1% < DeepSeek-R1 6.3% = Gemma4 6.3% < BaseDense 7.5% < Qwen3.8(intrinsic) 8.8% <
Proposed(extrinsic) 9.4% < budget-matched DOS-RAG 10.8%.
Note DOS-RAG abstains least while scoring highest on faithfulness, and the budget-matched
sensitivity arm abstains most - constraining DOS-RAG's evidence allowance raises abstention.

### F-34 · The M1 faithfulness ranking is largely an artifact of all-or-nothing aggregation · ACTIVE
`M1_faithfulness_per_claim` is derived as **PASS only if EVERY claim is SUPPORTED**. That makes it a
function of draft length: a longer draft has more claims and therefore more exposure. Since more
complete drafts contain more claims, M1 and M3 are structurally coupled and the apparent
"faithfulness vs completeness inversion" is mostly mechanical.

Tested directly against p^n (p = per-claim support rate, n = mean claims per draft):

| arm | per-claim p | mean claims | p^n predicted | observed M1 | diff |
|---|---|---|---|---|---|
| extrinsic_DOS-Q | 0.9760 | 8.40 | 0.8157 | 0.8442 | +0.029 |
| intrinsic_P-G (Gemma4) | 0.9744 | 7.64 | 0.8203 | **0.8195** | **-0.001** |
| intrinsic_P-Q (Qwen3.8) | 0.9599 | 8.89 | 0.6949 | **0.6853** | **-0.010** |
| extrinsic_P-Q | 0.9569 | 8.86 | 0.6768 | 0.6944 | +0.018 |
| extrinsic_B-Q | 0.9459 | 7.17 | 0.6712 | 0.7347 | +0.064 |
| intrinsic_P-D (DeepSeek-R1) | 0.8191 | 5.86 | 0.3103 | 0.4527 | +0.142 |

For the two arms in question the prediction is essentially exact (errors of 0.1 and 1.0 points).

**Gemma4 vs Qwen3.8 is a 1.45-point difference reported as 13.42 points** — a ~9x amplification
caused entirely by Qwen writing 8.89 claims per draft against Gemma4's 7.64:

| | per-claim support | all-or-nothing M1 |
|---|---|---|
| Gemma4 | 0.9744 | 0.8195 |
| Qwen3.8 | 0.9599 | 0.6853 |
| gap | **1.45 pp** | **13.42 pp** |

**DeepSeek-R1 is the exception and its deficit is real.** Per-claim support 0.8191 versus 0.94-0.98
for every other arm is a genuine, large model-level weakness, not an aggregation effect. (Its
observed M1 exceeds p^n by +0.14, meaning its unsupported claims concentrate in fewer drafts rather
than spreading uniformly - but the per-claim rate is the substantive finding.)

**Consequence:** report **per-claim support rate as the primary faithfulness measure**, with
all-or-nothing M1 shown alongside as the frozen-instrument derivation. This is not a metric change
after the fact - the per-claim verdicts were always the underlying data and M1 is a scalar derived
from them; reporting the underlying rate adds information rather than substituting a different
measure. The F-30/F-31 orderings stand as stated for M1-as-defined, but the *interpretation* changes:
only the DeepSeek-R1 gap survives as a model-level faithfulness claim.

### F-35 · Completeness is verbosity-confounded, but the arm ordering is not purely length · ACTIVE
Completeness rises monotonically with draft length (claim-count buckets: 0.143 / 0.424 / 0.642 /
0.793 / 0.821 / 0.795). Our judge is Selene-1-**Llama**-3.3-70B, and the family the literature
identifies as classically verbosity-biased ([R-07], +0.24 to +0.44 on expansion pairs). The
recommended mitigation - length normalisation - was applied via direct standardisation to the pooled
claim-count distribution:

| arm | raw M3 | length-adjusted | delta |
|---|---|---|---|
| extrinsic_P-Q | 0.861 | 0.848 | -0.013 |
| intrinsic_P-Q (Qwen3.8) | 0.860 | **0.845** | -0.015 |
| intrinsic_P-D (DeepSeek-R1) | 0.585 | **0.671** | **+0.086** |
| extrinsic_DOS-Q | 0.678 | 0.635 | -0.043 |
| intrinsic_P-G (Gemma4) | 0.615 | 0.620 | +0.004 |
| sensitivity_DOS-Q_matched | 0.446 | 0.504 | +0.058 |
| extrinsic_B-Q (BaseDense) | 0.414 | 0.426 | +0.012 |

**Mechanistic reading, which is what the metric should deliver:**
- **Qwen3.8's completeness advantage is real** - it survives adjustment (0.845 vs Gemma4 0.620), so
  it covers more reference content *per claim*, not merely by writing more.
- **DeepSeek-R1's apparent completeness deficit is largely a verbosity artifact.** It writes the
  shortest drafts (5.86 claims) and gains most from adjustment (+0.086), overtaking Gemma4. Its
  genuine weakness is faithfulness (per-claim 0.819 vs 0.94-0.98), not coverage.
- **BaseDense stays worst under adjustment**, so its deficit is a genuine *retrieval* failure, not a
  writing-style effect - which is precisely what a retrieval-side metric should confirm (v2 context
  recall will test this directly).

**Consequence:** length-adjusted completeness is a required reporting column, not an optional
robustness check. Raw completeness under a verbosity-biased judge conflates "wrote more" with
"covered more".

### F-36 · Nugget decomposition has a character-bound failure mode on formula-heavy references · ACTIVE
`KC_CLF_NB_009` ("NB for Numerical Attributes (Gaussian NB)") fails nugget decomposition with
`STRUCTURAL_INVALID`, and fails **identically on retry** - consistent with F-08, since greedy
decoding reproduces the same output for the same prompt. A retry can never fix it.

**Cause:** the reference embeds a full LaTeX Gaussian density formula. Reproducing it inside a single
nugget exceeds the schema's `MAX_NUGGET_CHARS = 300` bound, so no valid nugget can be emitted.

**Decision: excluded and disclosed, not repaired.** Raising the bound would change the schema, and
for provenance all 152 KCs must share one decomposition schema - so the fix would invalidate every
nugget produced so far plus the assignment run in flight. That is not a proportionate trade for
1 KC of 152 (0.66%), i.e. 7 rows of 1113.

**The honest caveat, because this exclusion is NOT random:** the failure mode selects for
**formula-heavy** KCs, and those are precisely the KCs where completeness disputes concentrated in
v1 (F-17 was the Wilson interval formula). Two consequences to report rather than bury:
1. one formula-heavy KC is missing from v2 completeness entirely;
2. other formula-bearing references may have had formulas **silently truncated to fit** 300
   characters rather than failing outright, which would understate their nugget content.
A future revision should raise the bound and re-decompose uniformly.

### F-37 · Context recall inverts the v1 retrieval ranking, and exposes a severe efficiency gap · CORRECTED
Vital-nugget context recall, judged against the **retrieved evidence** with **no drafter in the
loop** (604/604 judgements, zero errors, single instrument Cluster A ant2):

| arm | mean evidence items | strict recall | lenient |
|---|---|---|---|
| **Proposed** | **17.2** | **0.7347** | 0.7779 |
| DOS-RAG | 33.7 | 0.6926 | 0.7411 |
| DOS-RAG budget-matched | 11.6 | 0.4800 | 0.5453 |
| **BaseDense** | **123.1** | **0.4716** | 0.5547 |

**1. The v1 ranking inverts.** v1 reported DOS-RAG as the most faithful extrinsic arm (per-claim
0.976 vs Proposed 0.957) and Proposed as worse. Measured at the retrieval layer, **Proposed wins**.
v1 was measuring the drafter's behaviour on retrieved context, not the retrieval itself - exactly the
confound [R-05] describes and the project owner objected to.

**2. BaseDense is catastrophically inefficient.** It retrieves **7.2x more evidence than Proposed**
(123.1 vs 17.2 items) and recovers **less** of the required content (0.472 vs 0.735). More context is
not more information; this is the concrete case for reporting context precision alongside recall
[R-01].

**3. Constraining DOS-RAG's budget collapses its recall** (0.693 -> 0.480 at 11.6 items), so its
advantage over BaseDense depends on being allowed a large evidence allowance.

**CORRECTION 2026-08-31 — aggregation, and a significance claim that was never tested.**

*(a) The table above is micro-averaged; the protocol requires macro.* The figures pool every nugget
across KCs, which weights a KC by how many nuggets its reference happens to contain. The
pre-registered analysis plan fixes **KC as the unit of analysis** (KC-clustered bootstrap, exact
McNemar), so the correct aggregation is the mean of per-KC ratios. Restated:

| arm | evidence items | macro (protocol) | micro (as first reported) |
|---|---|---|---|
| Proposed | 17.2 | **0.7083** | 0.7347 |
| DOS-RAG | 33.7 | **0.6978** | 0.6926 |
| DOS-RAG budget-matched | 11.6 | **0.4657** | 0.4800 |
| BaseDense | 123.1 | **0.4664** | 0.4716 |

**The ranking is identical under both**, so the substantive conclusion is robust to the aggregation
choice — unlike all-or-nothing M1, whose ranking flipped (F-34). Only the decimals move. Verified by
independent recomputation over all 604/604 context judgements.

*(b) "Proposed wins" over DOS-RAG is NOT statistically supported.* Point 1 above asserts Proposed
beats DOS-RAG at the retrieval layer. The paired test was run afterwards and does not support it:
Δ = +0.0104, 95% CI [-0.0613, +0.0814], exact p = 0.824. On **context recall the two are
statistically indistinguishable.** What survives:

- **Proposed > BaseDense**: Δ = +0.2419, CI [+0.1598, +0.3227], Holm p < 0.001. Significant.
- **DOS-RAG > BaseDense**: Δ = +0.2314, CI [+0.1623, +0.3009], Holm p < 0.001. Significant.
- **Proposed vs DOS-RAG**: not significant on context recall — but Proposed **is** significantly
  better on *nugget recall* (Δ = +0.0823, Holm p = 0.0003), and that survives length adjustment
  (Δ = +0.1265, CI [+0.0335, +0.2157]).

*(c) The defensible claim is efficiency, not superiority.* Proposed matches DOS-RAG's retrieval
quality using **half the evidence** (17.2 vs 33.7 passages) and beats BaseDense decisively using
**one seventh** (17.2 vs 123.1). The inversion-of-v1 finding (point 1) and the efficiency finding
(point 2) both stand; the unqualified "Proposed wins on retrieval" does not.

**4. Design validation:** the three intrinsic arms and extrinsic_P-Q return **identical** recall
(0.7347), confirming empirically that the intrinsic family holds evidence fixed and varies only the
drafter.

**Consequence (SUPERSEDED 2026-09-02 — context recall was later withdrawn as a cross-arm metric; see F-45 and F-52):** context recall becomes the primary metric for the extrinsic family, as
pre-registered. It cannot be confounded by drafter choice, so the "would Gemma4 change the answer?"
objection does not apply to it.

### F-38 · Vital-nugget recall (v2 completeness), all arms · ACTIVE
1057/1057 assignments, zero errors, single instrument (Cluster A ant2).

| arm | strict | lenient |
|---|---|---|
| intrinsic_P-Q (Qwen3.8) | **0.8674** | 0.8800 |
| extrinsic_P-Q | 0.8295 | 0.8537 |
| intrinsic_P-G (Gemma4) | 0.7537 | 0.7853 |
| extrinsic_DOS-Q | 0.7305 | 0.7832 |
| intrinsic_P-D (DeepSeek-R1) | 0.6589 | 0.7295 |
| sensitivity_DOS-Q_matched | 0.5663 | 0.6232 |
| extrinsic_B-Q (BaseDense) | 0.5495 | 0.6126 |

### F-39 · v2 PASSES its pre-registered adoption test · ACTIVE
Registered in advance: vital-nugget recall must separate the 36 human
`CORE_COMPLETE`/`MATERIAL_OMISSION` rows better than holistic M3 did, else v2 is not adopted.

| predictor | AUC vs human label |
|---|---|
| **v2 vital-nugget recall** | **0.8578** |
| v1 holistic M3 (binary) | 0.7000 |

Separation is clean: human `CORE_COMPLETE` rows average **0.650** nugget recall, `MATERIAL_OMISSION`
rows average **0.094** — a ~7x gap. The graded metric tracks human judgement where the binary one
failed qualification (F-14).
**Honest limit:** the test uses the same 36 single-annotator rows, so passing establishes that v2 is
**better than v1**, not that it is validated in absolute terms. `JUDGE_QUALIFIED=false` still stands.

### F-40 · The context-vs-nugget gap is NOT safely readable as parametric leakage · OPEN
The attribution table shows several arms with nugget recall **above** context recall — the drafter
conveying reference content the retrieval judge scored as absent from the evidence:

| arm | ctx recall | nugget recall | gap |
|---|---|---|---|
| intrinsic_P-Q | 0.7347 | 0.8674 | **+0.133** |
| extrinsic_P-Q | 0.7347 | 0.8295 | +0.095 |
| extrinsic_B-Q | 0.4716 | 0.5495 | +0.078 |
| **intrinsic_P-D** | 0.7347 | 0.6589 | **−0.076** |

The tempting reading is parametric leakage — the drafter supplying content from its weights rather
than retrieval. **That reading is not supported and should not be made.** Per-claim faithfulness is
~0.96 for these arms, i.e. almost every claim IS evidence-supported; substantial parametric content
would depress it.

The likelier cause is **prompt asymmetry between the two judgements**: nugget assignment asks
whether a *description conveys* a fact, while context recall asks whether *passages contain what is
needed to state* it. The second is a stricter bar, so the same content scores PRESENT-in-draft more
readily than PRESENT-in-evidence. The two scores are therefore **not on a common scale**, and their
absolute difference is not a quantity.

**What remains safely claimable:** the asymmetry applies identically to all arms, so *relative*
gaps are informative. The standout is **DeepSeek-R1 as the only arm with a negative gap** — content
was retrieved and not used, consistent with it writing the shortest drafts (5.86 claims) and with
its faithfulness deficit (F-34).
**To close this properly** a calibration pass would judge the same nugget/evidence pairs under both
prompts to measure the offset directly. Not done; recorded as an open limitation rather than
silently interpreted.

**RESOLVED 2026-08-31 — no constant offset exists.** The calibration was run
(`locks/PREREG_F40_calibration.md`, pre-registered in `50562e5` before any result; 302 calls, 0
failures, `output/v2_f40_calib.jsonl`). Both prompts were shown the same clean expert reference,
from which the nuggets were extracted, so ground truth is 1.0 for both by construction.

| prompt | vital-nugget recall on the reference |
|---|---|
| assignment ("does this DESCRIPTION convey it") | **1.0000** |
| context ("do these PASSAGES contain it") | **1.0000** |

`B = 0.0000`, bootstrap CI `[0.0000, 0.0000]` over 151 KCs. The registered hypothesis — that the
context prompt is inherently stricter in wording — is **disconfirmed**.

Not degenerate: the judge still emitted PARTIALs (1 assign, 2 context) and the same scoring path on
real data produces wide spread (context: 2480 PRESENT / 1094 PARTIAL / 1166 ABSENT). The prompts
genuinely agree when the content is plainly present.

**What this does NOT settle.** The test saturates at the ceiling, so it has no power against a
confound that scales with evidence-set *size* — which the pre-registration anticipated by recording
`B` as a lower bound. That residual threat is now tracked separately as **F-45**, and it matters
more than F-40 did, because BaseDense has both the largest evidence set and the lowest score.

### F-41 · A dead server looks like fast progress; the runner now aborts on repeated call failures · ACTIVE
The Cluster A serve script carried `--time=06:00:00`, not the 24h assumed. SLURM killed the server at
exactly 06:00:04, mid-`faithfulness`. The runner kept issuing requests against a dead endpoint,
recorded `DECOMPOSE_CALL_FAILED` for **538 rows**, finished the queue quickly, and printed
**"ALL STAGES COMPLETE"**.

**Why this failure mode is dangerous rather than merely annoying:** a dead server does not look like
an error, it looks like *work completing unusually fast*. Three arms (`extrinsic_B-Q`,
`extrinsic_DOS-Q`, `sensitivity_DOS-Q_matched`) had **zero** judged rows while the stage reported
success. It was caught only because computing per-arm faithfulness produced `n/a` for those arms. A
completion message was, in this instance, actively misleading.

**Fixes applied:**
1. server time limit raised 6h -> 24h (the `gpu-stud` partition maximum);
2. `run_v2_metrics.py` now **aborts after 15 consecutive call failures**, cancels pending futures,
   and prints how many rows were processed. The reason is recorded in a code comment so the guard is
   not "tidied away" later.

**Recovery:** the 541 affected rows were dropped from the output and re-run; the 572 rows completed
before the server died were retained (resumability made this a re-run of the failed subset, not the
whole stage).

**Generalisable lesson for the writeup:** long unattended LLM-judge campaigns need a liveness check
that distinguishes "no work left" from "no server left". Row counts and exit status do not.

### F-42 · Reference coverage is 152/159, and the 7 uncovered KCs are not a random sample · ACTIVE
The v2 nugget and context metrics score **151 of 159 KCs**, not 158 as the earlier single-KC caveat
implied. The exclusions are:

- **7 KCs have no expert reference at all** — `KC_CLF_UND_005`, `KC_EVAL_BASIC_007/008/009`,
  `KC_EVAL_COMP_001/004/005`. The reference library covers 152/159. No reference means no nuggets,
  so every reference-based metric is undefined, not merely low.
- **1 KC fails decomposition structurally** — `KC_CLF_NB_009` (F-36, LaTeX formula exceeds
  `MAX_NUGGET_CHARS = 300`).

**Why the paired comparisons are still fair:** a reference and its decomposition are properties of
the *KC*, not of any arm, so all 7 arms lose the **same** 8 KCs. Every within-KC paired test remains
balanced and none of the reported comparisons is affected.

**Why the absolute figures need a caveat anyway:** the excluded set is not random. **4 of the 7
reference-less KCs are exactly the KCs where the Proposed retriever returned zero evidence.** Had
they been scorable, Proposed would have scored 0 context recall on them, while BaseDense — which
always returns passages — might have scored above 0. Excluding them therefore plausibly **flatters
Proposed's absolute retrieval recall**. Evidence: `output/v2_report.json` → `coverage`.

**Consequence:** absolute context-recall values are reported with this stated; relative rankings,
which are what the paper claims, are unaffected.

### F-43 · No arm ever drafted from an empty evidence set · ACTIVE
Splitting abstentions into **forced** (retrieval returned nothing) and **chosen** (evidence was
available, the drafter declined anyway) across all 1113 rows:

| arm | forced | chosen | drafted with ZERO evidence |
|---|---|---|---|
| extrinsic_B-Q | 0 | 12 | **0** |
| extrinsic_DOS-Q | 0 | 5 | **0** |
| extrinsic_P-Q | 4 | 11 | **0** |
| intrinsic_P-D | 4 | 6 | **0** |
| intrinsic_P-G | 4 | 6 | **0** |
| intrinsic_P-Q | 4 | 10 | **0** |
| sensitivity_DOS-Q_matched | 7 | 10 | **0** |

All 23 zero-evidence rows abstained; **none** produced a description with nothing to ground it. The
worst available failure mode — asserting content with no retrieved support — never occurred in the
campaign.

Reported over **all** rows rather than the 151-KC scored subset, because the zero-evidence KCs are
precisely the ones the reference-coverage exclusion removes (F-42); computing this on the scored
subset would hide the entire phenomenon. This is a property of the harness's abstention contract,
not of any single pipeline, and should be attributed that way.

### F-44 · Two of three intrinsic completeness rankings do not survive length adjustment · ACTIVE
F-35 established verbosity confounding on v1's holistic completeness. The same check now applies to
v2 vital-nugget recall, by direct standardisation onto the pooled draft-length distribution (each
arm re-scored as if its drafts had the same length profile as the corpus; abstentions excluded).

**Internal validity check passes:** the adjustment moves completeness (shifts to +0.105) and leaves
faithfulness essentially untouched (all shifts < 0.01) — the predicted pattern, since faithfulness is
already a ratio and should not be length-driven. The adjustment is doing what it claims, not adding
noise.

| comparison | raw Δ | length-adjusted Δ | 95% CI | robust? |
|---|---|---|---|---|
| extrinsic_P-Q vs extrinsic_B-Q | +0.2627 | +0.2269 | [+0.1497, +0.3011] | yes |
| extrinsic_P-Q vs extrinsic_DOS-Q | +0.0941 | +0.1265 | [+0.0335, +0.2157] | yes |
| extrinsic_B-Q vs extrinsic_DOS-Q | -0.1672 | -0.0803 | [-0.1575, -0.0008] | yes |
| intrinsic_P-Q vs intrinsic_P-G | +0.1112 | +0.0818 | [+0.0266, +0.1357] | yes |
| intrinsic_P-Q vs intrinsic_P-D | +0.1855 | +0.0598 | [-0.0005, +0.1730] | direction holds, CI touches 0 |
| **intrinsic_P-G vs intrinsic_P-D** | **+0.0720** | **-0.0250** | [-0.0675, +0.0803] | **NO — sign flips** |

**All three extrinsic (retrieval architecture) comparisons survive.** The paper's central claim —
Proposed > DOS-RAG > BaseDense on retrieval — is not a verbosity artifact.

**The Gemma-over-DeepSeek completeness ranking does not survive** and is withdrawn as a claim.
DeepSeek-R1 averages 122.7 words against Gemma4's 187.5; its apparent completeness deficit is
largely **brevity**, not worse coverage per unit length. This independently reproduces F-35's v1
conclusion on a different metric, which is meaningful corroboration rather than a restatement — the
two metrics fail differently.

Note DeepSeek covers only 4 of 5 length bands (it never writes a long draft), so its adjusted figure
is renormalised over covered bands and is the least reliable of the seven.

**Consequence:** the same standard the protocol applied to all-or-nothing M1 applies here — a ranking
that flips under a defensible adjustment cannot support a claim. Evidence:
`output/v2_report.json` → `length_adjusted`, `length_robustness_nugget_recall`.

### F-45 · The judge loses evidence placed late in a large passage set; context recall is NOT comparable across arms with different retrieval budgets · ACTIVE

**This is the most consequential finding in the v2 campaign and it forces a retraction.**

Pre-registered in `locks/PREREG_F45_dilution.md` (commit `f7261a1`, before any result). Each KC's own
expert reference — which provably contains **every** nugget — was embedded among topically separated
distractors at three set sizes. **Ground truth is 1.0 at every level by construction.** 453 calls,
zero failures (`output/v2_f45_dilution.jsonl`).

| passages in set | vital-nugget recall | shortfall from truth |
|---|---|---|
| 17 (≈ Proposed's 17.2) | **1.0000** | 0.0000 |
| 33 (≈ DOS-RAG's 33.7) | **0.9934** | 0.0066 |
| 123 (≈ BaseDense's 123.1) | **0.5905** | **0.4095** |

Paired drop 17→123: **+0.4095**, 95% CI [+0.3322, +0.4868] over 151 KCs. **Registered Prediction 2
(CONFOUNDED) is realised.**

**The mechanism is serial position, not truncation.** Within `K=122` every prompt is the same length
and only the reference's position varies, so the effect is purely positional:

| reference position | vital recall |
|---|---|
| 0–33 | 1.0000 |
| 33–59 | 0.72–0.87 |
| 59–121 | 0.20–0.40 |

**Truncation is ruled out** on two independent grounds: a truncated prompt would collapse to exactly
0.0 beyond a fixed cut point, yet positions 113–121 still score 0.3125; and the server runs
`--max-model-len 40960` against ~25k-token prompts, with all 453 calls returning `OK` and none
rejected. The judge is *reading* the late passages and *failing to use* them.

#### What this invalidates, and what it leaves standing

The confound scales with evidence-set size, so it cancels exactly where sets are equal and bites only
where they differ:

| comparison | set sizes | ceilings | status |
|---|---|---|---|
| intrinsic P-Q / P-G / P-D | 17.2 vs 17.2 (**identical evidence**) | 1.0000 both | **VALID** — dilution is identical and cancels exactly in the paired test |
| Proposed vs DOS-RAG | 17.2 vs 33.7 | 1.0000 vs 0.9934 | **VALID** — differential 0.0066, negligible |
| DOS-RAG vs budget-matched | 33.7 vs 11.6 | 0.9934 vs ~1.0 | **VALID** |
| anything **vs BaseDense** | vs 123.1 | vs **0.5905** | **INVALID** for any metric judged against the evidence set |

And it depends on *what the metric reads*:

- **Vital-nugget recall is UNAFFECTED.** It is judged against the **draft** (122–245 words), never
  against a passage set. Every nugget-recall comparison — including those against BaseDense —
  stands, and they survive length adjustment (F-44).
- **Context recall against BaseDense is INVALID.** BaseDense's 0.4664 sits *below* the 0.5905 ceiling
  a perfect retriever would score at that set size. The number cannot be read as retrieval quality.
- **Per-claim faithfulness is judged against the evidence set and is therefore SUSPECT** for
  BaseDense. Tested separately as F-46.

#### Retraction required

**F-37 point 2 and [C-06]'s efficiency claim are withdrawn as measured.** "BaseDense retrieves 7.2x
more evidence yet recovers less required content" is not supportable: the instrument cannot see
content late in a 123-passage set, so a low score there is not evidence of poor retrieval. The
underlying claim may still be true — this finding does not show BaseDense is *good* — but **we have
not measured it**, and the honest position is that we cannot, with this instrument, at that set size.

**No numeric correction is applied**, deliberately. The measured 0.5905 ceiling is neither a clean
upper nor lower bound: the test placed all required content in **one** passage, whereas real
retrieval may spread it across several (which would help the judge), while the distractors were
topically *separated*, whereas real retrieved sets are topically adjacent and harder (which would
hurt). The two biases oppose and cannot be netted out, so the comparison is **downgraded rather than
adjusted**.

#### The finding that replaces it

The surviving, and stronger, claim is end-to-end rather than retrieval-layer: **Proposed produces
substantially more complete drafts than BaseDense** (vital-nugget recall Δ = +0.2539 raw,
+0.2269 length-adjusted, CI [+0.1497, +0.3011]) — measured on drafts, immune to this confound.

**Generalisable methodological result, and arguably the most publishable thing here:** LLM-judge
context-recall metrics are **serial-position sensitive**, so they are **not comparable across
retrieval systems that return different numbers of passages**. Any RAG evaluation comparing a
top-k=10 system against a top-k=100 system on judge-scored context recall is measuring set size as
much as retrieval quality. We found no contemporary RAG-evaluation work that controls for this, and
the standard frameworks [R-01] do not mention it. A reviewer would have found this; we found it
first, by testing our own instrument against a case where the right answer was known in advance.

### F-47 · Domain runs are v2-compatible after all; faithfulness generalises, and F-34's artifact reproduces out-of-domain · ACTIVE
The v2 protocol assumed the domain runs already stored per-claim verdicts and could be upgraded at
zero inference cost. That was checked rather than trusted: the top-level field
`M1_faithfulness_per_claim` is misleadingly named and holds a **scalar `"PASS"`**, not per-claim
data. The verdicts do survive in `responses.m1.verdicts`, so the assumption holds — but only because
the raw responses were retained. **220 rows, instrument `ants_tp4_h100_frozen`, single instrument,
no new inference.**

**Aggregation restated (same defect as F-37).** The domain figures previously reported —
mathematics 0.9274, sociology 0.9739 — are **micro**-averaged. The protocol fixes KC as the unit, so
macro governs:

| domain | KCs | per-claim macro (protocol) | per-claim micro (as reported) | all-or-nothing |
|---|---|---|---|---|
| mathematics | 71 | **0.9199** | 0.9274 | 0.5231 |
| sociology | 149 | **0.9666** | 0.9739 | 0.8176 |
| data-mining (main corpus) | 151 | **0.9591** | 0.9523 | — |

**Domain generalisation holds.** Per-claim faithfulness sits in 0.92–0.97 across three unrelated
subject areas, with mathematics weakest — consistent with F-36, where the one reference that broke
decomposition was formula-heavy. Formulaic content is plausibly harder both to ground and to
decompose. This remains a **single-drafter probe** (Qwen3.8 only, the project owner's scoping
decision) and reference-based metrics stay undefined here (F-27/C-05); only faithfulness, which
needs no reference, transfers.

**F-34's all-or-nothing artifact reproduces out-of-domain, quantitatively.** F-34 modelled the
all-or-nothing rate as ≈ p^n for per-claim rate p over n claims. Tested on data F-34 never saw:

| domain | p | n | p^n predicted | all-or-nothing observed | error |
|---|---|---|---|---|---|
| mathematics | 0.9199 | 8.26 | 0.5017 | 0.5231 | +0.0214 |
| sociology | 0.9666 | 9.30 | 0.7292 | 0.8176 | +0.0883 |

Mathematics lands within 0.021 of prediction. Both errors are **positive**, exactly as they should
be: p^n assumes claims fail independently, whereas claims within one draft are positively
correlated, which lifts the observed rate above the independent-failure floor. The model is
conservative in the predicted direction rather than merely fitting.

This is why the all-or-nothing scalar cannot carry a domain claim: it reads 0.5231 for mathematics,
implying near-coin-flip reliability, when the underlying per-claim rate is 0.9199. The difference is
draft length, not quality.

**F-45 exposure is negligible here.** Domain evidence sets reach at most ~38 passages (max `SRC_038`
in mathematics, `SRC_026` in sociology), where the measured dilution ceiling is ≈0.99. Unlike the
BaseDense comparison, these figures are not materially depressed by set size.

### F-46 · Faithfulness is NOT depressed by evidence-set size; it is mildly INFLATED · ACTIVE (final, n=143)
F-45 showed the context-recall judge loses content placed late in a 123-passage set. Faithfulness is
judged against the same evidence sets, so the obvious worry was that the reported
"DOS-RAG more faithful than BaseDense" result (Holm p = 0.0006) is the same artifact — BaseDense
having 123.1 passages and the lowest faithfulness.

Controlled paired design: each `intrinsic_P-Q` draft's claims are decomposed **once**, then judged
twice — against the arm's own evidence (~19 passages) and against that same evidence **padded to 123**
with topically separated distractors inserted at seeded random positions. Only the padding differs.

| condition | per-claim faithfulness |
|---|---|
| own evidence (~18 passages) | 0.9537 |
| padded to 123 passages | **0.9712** |

Mean paired change **-0.0175**, 95% CI [-0.0325, -0.0024] — **excludes zero**. Padding **lowered**
faithfulness in 7 of 143 KCs, **raised** it in 27, left 109 unchanged; exact McNemar
**p = 0.00082**. 145 records, 0 call failures; 2 rows unusable because claim decomposition hit the
token cap in **both** conditions, so the loss is symmetric and cannot bias the contrast.

**The direction is opposite to F-45 and the mechanism explains why.** Context recall asks the judge
to locate a *specific* nugget; burying it among 122 distractors makes it findable only if attended
to, and the judge defaults to ABSENT when it is not. Faithfulness asks whether a claim *is supported
by anything present*; adding passages can only **add** potential support, and never removes the
original evidence, which is still in the set. The two tasks fail in opposite directions under the
same manipulation — one toward its negative default, one toward its positive one.

**Consequence: the faithfulness comparisons against BaseDense STAND.** BaseDense's 0.9440 is not
depressed by its set size. If anything the bias runs the other way, so the measured
DOS-RAG-over-BaseDense gap is **conservative** — the true gap is plausibly larger, not smaller. This
is the opposite of the context-recall situation (F-45), where the comparison had to be withdrawn.

**How large is the inflation relative to the result it might threaten?** The measured
DOS-RAG-over-BaseDense faithfulness gap is +0.0468 (paired within-KC, n=143; the
difference of arm means is +0.0441). The full 18→123 inflation is
0.0175, and the *differential* between DOS-RAG (33.7 passages) and BaseDense (123.1) is necessarily
**smaller** than that, since DOS-RAG's own set is already padded relative to the 18-passage
baseline. The inflation therefore cannot manufacture the gap; it can only **understate** it.

**Scope note.** Measured on `intrinsic_P-Q` drafts only, and the padding uses topically separated
distractors. Real BaseDense passages are topically adjacent, which plausibly offers *more* spurious
support and would push the inflation higher — again in the conservative direction for the reported
result.

### F-48 · The expert reference is seeded from Qwen · CORRECTED (over-claimed; see the correction and F-49)

**CORRECTION 2026-09-01 — this finding over-claimed and its headline is withdrawn.**

Two errors. First, the reference library was *designed* as expert-edited machine output with
source-first review before seed exposure, so `ACCEPT` means **corpus-verified complete**, not
unexamined — a seed-arm score of 1.0 on that stratum is a true positive, not a tautology. Second,
and more seriously, the `CHANGED` stratum is **selected on Qwen having failed**: the expert edited
precisely the drafts that were deficient. A low Qwen score there is therefore expected by
construction. F-48 presented a selection effect as evidence of circularity, and buried the
alternative explanation as a caveat instead of leading with it.

**F-49 settles it empirically** — the seed-blind audit found zero distortion and zero unsupported
assertion in the seeded library, and the ACCEPT stratum agreed with independent references *no
worse* than the CHANGED stratum, which is the opposite of what seed bias predicts.

The residual, narrower issue that does stand: the nugget set inherits Qwen's **content selection**,
so nugget-recall comparisons carry an asymmetry. That is a disclosure, and completeness is reported
as secondary — not a withdrawal of the library.

*Original text retained below for the record.*

#### What the reference actually is

The expert reference library was **seeded from the frozen Qwen drafts** and then human-adjudicated.
This is documented in the library's own manifest, not inferred:

```
seed_provenance/seed_arm:              intrinsic_P-Q
seed_provenance/identification_method: exact string comparison of the reference's own
                                       original_machine_draft_text against all 7 frozen arms;
                                       intrinsic_P-Q matched 159/159 text and 159/159 status;
                                       next closest was extrinsic_P-Q at 17/159
seed_provenance/validity_note:         The reference is machine-seeded. It must never be
                                       described as independent of Qwen.
```

Adjudication outcome: **ACCEPT 117** (machine draft kept unchanged), MAJOR_EDIT 15, REPLACE 10,
MINOR_EDIT 10, NO_REFERENCE_CORPUS_UNSUPPORTED 7. So **117 of 159 references are verbatim Qwen
output.**

Independently confirmed here by 8-gram overlap between each arm's drafts and the reference:

| arm | 8-gram overlap with reference |
|---|---|
| **intrinsic_P-Q** (the seed arm) | **0.8074** |
| extrinsic_P-Q | 0.3151 |
| intrinsic_P-G | 0.0889 |
| sensitivity_DOS-Q_matched | 0.0540 |
| extrinsic_DOS-Q | 0.0514 |
| extrinsic_B-Q | 0.0428 |
| intrinsic_P-D | 0.0147 |

#### Why the existing controls do not cover this

`ANTI_ANCHORING_PROTOCOL.md` anticipated the risk and implements six controls. Two matter here:

- **Control 4 — no lexical similarity evaluation.** BLEU/ROUGE/edit distance are excluded precisely
  because "surface similarity would structurally favor Qwen". Vital-nugget recall is *semantic and
  claim-level*, so it complies with the letter of this control. **But the nuggets are extracted from
  the reference**, and the reference is Qwen's content. The advantage Qwen inherits is not in
  *wording* — it is in **which facts were selected**. Control 4 does not cover that.
- **Control 6 — seed-bias sensitivity audit. NOT RUN.** `05_seed_bias_audit/` is empty. The protocol
  states: *"If this audit is not completed, the thesis must not claim seed bias was empirically ruled
  out."*

#### Stratified sensitivity analysis (partial substitute for control 6)

The expert's own adjudication stratifies the references by how much they still owe to the seed:
**ACCEPT** (116 scored KCs, reference = verbatim Qwen) versus **CHANGED** (35 scored KCs, expert
edited or replaced it). Vital-nugget recall by stratum:

| arm | ACCEPT | CHANGED | drop |
|---|---|---|---|
| **intrinsic_P-Q** (seed) | **1.0000** | 0.3667 | +0.6333 |
| **extrinsic_P-Q** (seed lineage) | **0.9558** | 0.3667 | +0.5891 |
| intrinsic_P-G | 0.8742 | 0.3262 | +0.5480 |
| intrinsic_P-D | 0.7584 | 0.3881 | +0.3703 |
| extrinsic_DOS-Q | 0.8035 | 0.5163 | +0.2871 |
| extrinsic_B-Q | 0.6038 | 0.4381 | +0.1657 |

**The seed arm scores exactly 1.0000 on all 116 accepted references.** That is not a quality result,
it is a tautology: the nuggets were extracted from Qwen's own text, so Qwen's draft contains all of
them by construction. Since 116/151 = 77% of the scored sample sits in this stratum, the seed arm's
headline 0.8532 is arithmetically ≈ (116×1.0000 + 35×0.3667)/151 = 0.853 — i.e. **it is
substantially a measurement of the metric's own circularity.**

Every paired ranking reverses across the strata:

| comparison | ACCEPT | CHANGED |
|---|---|---|
| intrinsic_P-Q vs P-G | +0.1258 [+0.092,+0.163] | +0.0405 [−0.029,+0.117] |
| intrinsic_P-Q vs P-D | +0.2416 [+0.192,+0.292] | **−0.0214** [−0.117,+0.069] |
| extrinsic_P-Q vs B-Q | +0.3521 [+0.291,+0.412] | **−0.0714** [−0.217,+0.079] |
| extrinsic_P-Q vs DOS-Q | +0.1523 [+0.102,+0.205] | **−0.1497** [−0.292,−0.005] |

On expert-rewritten references the seed-lineage arms **lose** to their comparators, and against
DOS-RAG the reversal's CI excludes zero.

#### The falsification test — and what survives

Per-claim faithfulness is judged against **retrieved evidence** and never touches the reference, so
if seed provenance is what drives the reversal, faithfulness should be stratum-**stable**. It is:

| comparison | ACCEPT | CHANGED | |
|---|---|---|---|
| extrinsic_DOS-Q vs B-Q | +0.0392 [+0.016,+0.064] | +0.0730 [+0.021,+0.138] | STABLE |
| extrinsic_DOS-Q vs P-Q | +0.0218 [+0.005,+0.039] | +0.0659 [+0.022,+0.117] | STABLE |
| intrinsic_P-G vs P-D | +0.1252 [+0.089,+0.163] | +0.1906 [+0.102,+0.287] | STABLE |
| intrinsic_P-Q vs P-D | +0.1095 [+0.081,+0.140] | +0.1136 [+0.053,+0.184] | STABLE |

Same sign, comparable magnitude, and an identical arm ordering in both strata. This is a clean
dissociation: the metric that reads the reference is contaminated, the metric that reads the
evidence is not.

#### Consequences

**WITHDRAWN — every reference-based ranking:**
- All vital-nugget recall comparisons, both families (F-44's length-adjusted versions included —
  length adjustment does not touch this confound).
- All context-recall comparisons. The nuggets derive from the reference, so a retrieval
  configuration that surfaced the passages Qwen drafted from is advantaged independently of the
  F-45 dilution problem.
- The extrinsic conclusion "Proposed produces more complete drafts than BaseDense", which was the
  claim left standing after F-45. It does not survive this.

**STANDS:**
- **Per-claim faithfulness** — reference-independent by construction and stratum-stable by
  measurement. DOS-RAG is the most faithful extrinsic arm; Gemma4 the most faithful drafter;
  DeepSeek-R1 clearly the least.
- **Abstention behaviour** (F-43) — no reference involved.
- **All instrument findings** (F-34, F-45, F-46, C-01, C-02, C-08) — properties of the judge, not
  arm rankings.

#### Limits of this analysis, stated

The strata are **not randomly assigned**. The expert chose which drafts to edit and plausibly edited
the weaker ones, which would depress the seed arm's CHANGED score for reasons unrelated to seeding.
So the CHANGED stratum is not a clean estimate of Qwen's true quality either. What the analysis does
establish is narrower and sufficient: **the ACCEPT stratum carries no information about the seed
arm's quality**, and it is 77% of the sample. A metric that is degenerate on three quarters of its
sample cannot rank the arm it is degenerate for.

This is a partial substitute for control 6, not a replacement. The seed-blind reconstruction audit
remains the correct fix, and remains un-run. **Evidence:** `run_seed_bias_sensitivity.py`,
`output/seed_bias_sensitivity.json`.

### F-49 · Control 6: the seeded reference library is cleared on both failure modes that would invalidate it · ACTIVE
The seed-blind reconstruction audit (`ANTI_ANCHORING_PROTOCOL` control 6) was run. An independent
reviewer, with no exposure to any system output or to the existing library, wrote references for a
stratified 30-KC sample directly from the corpus. Comparison was **blinded and order-randomised** —
the judge saw two descriptions as A and B with no indication which was which — and verdicts were
re-expressed against the seeded reference afterwards using the recorded mapping.

| relationship | n |
|---|---|
| BOTH_VALID_DIFFERENT_FORMULATION | 14 |
| BLIND_MISSING_CONTENT | 9 |
| SUBSTANTIVELY_EQUIVALENT | 4 |
| **MATERIAL_SEMANTIC_DIFFERENCE** | **0** |
| **SEEDED_EXTRA_UNSUPPORTED** | **0** |

n = 27 comparable; the 3 corpus-unsupported KCs have no reference text to compare against.

**The two failure modes TESTED did not occur.** The seeded library never disagreed with an independently written reference about what a concept is, and never asserted content the corpus does not support.

**Correction (2026-09-02):** an earlier phrasing called these "the two ways a machine-seeded reference could be invalid". That is wrong. At least six failure modes are possible: semantic distortion; unsupported content; **omission of source-supported content**; **incorrect corpus-support state**; **seed-shaped content selection or emphasis**; and provenance error. This audit tested the first two. The support-boundary mode was tested and **disagreed** (below). Omission and content-selection shaping were not tested.

**Stratum check — the discriminating test.** If the seed had shaped the content, agreement should be
*worse* where the expert accepted the draft unchanged. It is not: `ACCEPT` agrees 13/18, `CHANGED`
agrees 5/9. No stratum effect in the direction seed bias predicts.

**Limits, stated.** The blind references average 24 words against the seeded library's ~150 and cite
~1 passage each, so the MISSING_CONTENT direction is an effort artifact and was declared
uninterpretable *before* the run — the 9 BLIND_MISSING_CONTENT verdicts carry no information about
bias. The reviewer also marked all 3 corpus-unsupported KCs as supported, suggesting a less strict
support threshold than the original expert. Single reviewer, n=27.

**A bug caught by reading the output rather than trusting it:** the A/B de-blinding map was inverted,
which reported `BLIND_MISSING_CONTENT` as `SEEDED_MISSING_CONTENT` — the exact opposite conclusion.
Both the raw label and the `blind_is_A` flag were stored, so the corrected reading was recoverable
without re-running. Fixed in `run_seed_audit_comparison.py`.

### F-50 · Drafter performance-equivalence analysis · DOWNGRADED by F-57 (equivalence is evaluator-dependent; ordering retained). **Definitional note 2026-09-02: this finding concerns drafter PERFORMANCE, not architectural model-agnosticism, which is separately SUPPORTED**
v2 tested the intrinsic family with *difference* tests and reported non-significance. That is not
evidence of equivalence. v3 uses **TOST** against a margin registered in advance (δ = 0.05 absolute
on groundedness), across the full crossed 3-drafter × 3-domain design (1137 rows, 0 failures).

| comparison | maths | data-mining | sociology |
|---|---|---|---|
| **Gemma vs Qwen** | +0.0063 **EQUIV** | +0.0245 **EQUIV** | +0.0276 **EQUIV** |
| DeepSeek vs Qwen | −0.2142 not equiv | −0.1129 not equiv | −0.0758 not equiv |
| DeepSeek vs Gemma | −0.2402 not equiv | −0.1474 not equiv | −0.1034 not equiv |

**Qwen and Gemma are statistically equivalent in all three domains.** DeepSeek-R1 is not equivalent
to either, anywhere — and its deficit is **consistent across three unrelated subjects**, which makes
it a stable model property rather than a pipeline–domain interaction. Supporting evidence
independent of quality: DeepSeek writes 118 / 114 / 123 words across the three domains against
Qwen's 208 / 234 / 245, and self-reports `grounded` on ~99% of KCs while the others use `partial`
10–20% of the time.

**Variance decomposition puts a number on it** — the share of groundedness variance attributable to
the drafter facet:

| domain | all three drafters | Qwen + Gemma only |
|---|---|---|
| data-mining | 23.3% | **3.3%** |
| mathematics | 39.5% | **0.0%** |
| sociology | 15.5% | **6.4%** |

**The defensible claim is "model-agnostic across drafters of comparable capability, with graceful
degradation"** — which the decomposition supports and a difference test never could.

> **DOWNGRADED 2026-09-01 by F-57, marked here 2026-09-02.** The equivalence result above holds under
> the primary instrument only. Under an independent entailment verifier scoring identical claims it
> reproduces in **1 of 3** domains, and only 5 of 9 comparisons agree. The supportable claim is the
> **ordering** (Gemma >= Qwen > DeepSeek in mathematics and data-mining), not equivalence. The
> paragraph above is retained as the record of what the primary instrument showed.

**Limits.** One observation per cell, so the drafter × KC interaction is confounded with error; the
residual term is large (49–97%) and the G-coefficients are correspondingly low (0.0–0.42), meaning
item-level measurement is noisy even where the drafter effect is small. Excluding DeepSeek is
defensible only because the exclusion criterion is a compliance characteristic measurable without
looking at quality — but it is still an exclusion, so both figures are reported.

### F-51 · Cross-domain performance sensitivity: mathematics is the outlier · ACTIVE. **Definitional note 2026-09-02: this concerns domain PERFORMANCE, not architectural domain-agnosticism, which is separately SUPPORTED**
Same TOST machinery across domains, within each drafter:

| drafter | data-mining vs sociology | data-mining vs maths | maths vs sociology |
|---|---|---|---|
| Qwen | −0.0147 **EQUIV** | +0.0320 not equiv | −0.0467 not equiv |
| Gemma | −0.0282 **EQUIV** | +0.0366 not equiv | −0.0648 not equiv |
| DeepSeek | −0.0739 not equiv | +0.1353 not equiv | −0.2092 not equiv |

Data-mining and sociology fall within the pre-registered margin for both in-scope drafters **under
the primary instrument** (the domain pairs were not re-tested on the second instrument).
**Mathematics is consistently
the hardest domain** and falls outside δ = 0.05, though the gaps are small in absolute terms
(0.032–0.065) and would pass at δ = 0.10. This is consistent with F-36 and F-47: formulaic content
is harder both to ground and to decompose.

### F-52 · Pooled retrieval judgements restore the efficiency claim F-45 forced us to retract · ACTIVE
The extrinsic comparison was rebuilt as a **pooled test collection** (TREC methodology): the union of
the top-20 passages from every arm, with each passage judged **individually** for whether it supports
describing the KC. 8246 judgements, 0 failures. Individual judging means the serial-position failure
of F-45 — which made context recall uninterpretable across different retrieval budgets — cannot
arise, and `@k` metrics are *designed* for systems returning different numbers of results.

| retrieval | passages/KC | P@10 | R@10 | nDCG@10 | R@20 |
|---|---|---|---|---|---|
| **Proposed** | 17.2 | **0.6279** | 0.2379 | **0.5229** | 0.3304 |
| DOS-RAG | 33.7 | 0.6244 | 0.2401 | 0.4074 | **0.4705** |
| DOS-RAG budget-matched | 11.6 | 0.5421 | 0.1853 | 0.4274 | 0.2484 |
| BaseDense | 123.1 | 0.3686 | 0.1374 | 0.2399 | 0.2333 |

**The retracted efficiency claim is restored, now properly measured.** BaseDense returns 7.2× more
passages than Proposed and its top-10 precision is **0.3686 against 0.6279** — it retrieves far more
and ranks far worse. F-45 was right that the *old* measurement could not support this; the pooled
measurement can.

**Proposed vs DOS-RAG is a ranking difference, not a recall difference.** They are near-identical on
P@10 (0.6279 vs 0.6244) and R@10 (0.2379 vs 0.2401), but Proposed's nDCG@10 is markedly higher
(0.5229 vs 0.4074) — it puts the definitional material at the top. DOS-RAG leads at R@20 (0.4705)
because it returns twice as many passages, which is the expected budget effect and not a quality
difference.

Disclosed limitation: **pool bias** — relevant passages outside the pool count as non-relevant.
Mitigated by pooling seven evaluated arms corresponding to **four distinct retrieval configurations**; note the pool takes each arm's **top 20**, so BaseDense's 123 passages did not all enter it. Notably the four
Proposed-lineage arms contribute **zero** passages unique to them, so the ground truth cannot be
characterised as Proposed's own output.

### F-53 · Editorial acceptability triage does not discriminate and is not validated · ACTIVE
An LLM-judged post-editing effort scale (usable as-is / minor / major / unusable) was run on all 1113
ablation rows. It fails on both counts.

**Non-discriminating:** every arm lands at 97.2–99.3% "usable or minor", and the judge never once
used `UNUSABLE` across 1113 drafts.

**Not validated:** against the expert's own adjudication codes on the 159 seed-arm drafts, exact
agreement is **0.462** (within one level, 0.952). The judge systematically compresses toward the
middle — it downgraded 59 of 117 expert-`ACCEPT` drafts to `MINOR_EDIT`, and used `MAJOR_EDIT` 4
times where the expert used it 15.

**Consequence:** the automated triage is reported as a construct failure, not as a result. The
trustworthy answer to "how much work do these drafts need" is the **human** one, on the seed arm:

| expert verdict | n | % |
|---|---|---|
| usable as-is | 117 | 73.6% |
| minor edit | 10 | 6.3% |
| major edit | 15 | 9.4% |
| replace | 10 | 6.3% |
| no corpus support | 7 | 4.4% |

This is the third metric in the campaign to sit at ceiling and fail to separate arms (with M2 and
TARGET, F-32) — a pattern worth reporting in its own right: **LLM judges asked for holistic
editorial verdicts compress toward the middle and do not resolve differences that a human resolves.**

### F-54 · The judge matches meaning, not wording - and the seed asymmetry is isolated to one arm · ACTIVE
Direct test of whether vital-nugget recall is secretly rewarding lexical overlap with the reference,
which the reference-construction protocol's control 4 explicitly forbids. All three intrinsic arms
read the SAME retrieved passages, so any recall difference must come either from genuine content
selection or from the judge favouring drafts that echo the reference's wording.

| arm | 8-gram overlap with reference | vital recall | ratio |
|---|---|---|---|
| intrinsic_P-Q | 0.8061 | 0.8947 | 1.1x |
| intrinsic_P-G | 0.0879 | 0.7675 | **8.7x** |
| intrinsic_P-D | 0.0148 | 0.6909 | **46.6x** |

**String matching is ruled out arithmetically.** DeepSeek-R1 shares 1.5% of its 8-word sequences with
the reference and scores 69% vital recall. Gemma4 shares 8.8% and scores 76.8%. More directly: of
147 Gemma drafts, **66 share under 5% of their 8-grams with the reference, and 32 of those score a
perfect 1.0**. A draft with essentially no verbatim overlap achieving full nugget recall is only
possible if the judge is assessing meaning.

**The seed asymmetry is isolated, and this localises it precisely.** Within-arm correlation between
lexical overlap and vital recall across KCs:

| arm | r | n |
|---|---|---|
| intrinsic_P-Q | **+0.800** | 144 |
| intrinsic_P-G | +0.206 | 147 |
| intrinsic_P-D | +0.112 | 147 |

The same judge produces r = +0.11 to +0.21 for the non-seed arms and +0.80 for the seed arm. That
rules out judge-side lexical bias as the explanation - a judge rewarding wording would do so for
every arm. The correlation is a property of the **seed relationship**: where the expert accepted
Qwen's draft unchanged the reference *is* that draft, so it trivially contains every nugget; where
the expert edited, Qwen's draft lacks exactly what was added.

**Consequence, and it is narrower than F-48 claimed.** The residual seed asymmetry attaches to
`intrinsic_P-Q`'s and `extrinsic_P-Q`'s completeness figures specifically, not to the metric in
general and not to the judge. Gemma-vs-DeepSeek completeness comparisons carry no seed asymmetry at
all, since neither is seed lineage. Together with F-49 (no content distortion in the library) this
closes the seed question: the library is sound, the judge is semantic, and the one affected quantity
is identified.

### F-55 · The judge QUALIFIES on completeness once scored with the v2 graded metric · ACTIVE
`JUDGE_QUALIFIED=false` has been carried as an absolute caveat on every result in this project. Its
scope was narrower than we treated it, and one part of it is now overturned.

**Only one task actually failed.** M1, M2 and TARGET returned `INSUFFICIENT_VALIDATION_SUPPORT`,
which is a **sample-size** verdict, not a disagreement verdict - each has fewer than the required 10
minority-class rows (6, 8 and 5). TARGET in fact agrees at raw **0.906**, Gwet AC1 **0.884**.

**M3 failed as a binary verdict and passes as a graded score.** v1's M3 was binary
`CORE_COMPLETE`/`MATERIAL_OMISSION`. v2 replaced it with graded vital-nugget recall, which scores
AUC 0.8578 against the same labels versus holistic M3's 0.700 (F-39) - but **the qualification gate
was never re-run on the replacement metric**. Re-running it, with the decision threshold selected
**leave-one-out** so it never sees the row it predicts:

| gate | threshold | v1 holistic M3 | v2 nugget recall (LOO) |
|---|---|---|---|
| raw agreement | >= 0.80 | 0.556 FAIL | **0.8611 PASS** |
| Gwet AC1 | >= 0.65 | 0.392 FAIL | **0.7224 PASS** |
| PASS recall | >= 0.75 | 0.400 FAIL | **0.8000 PASS** |
| FAIL recall | >= 0.75 | 1.000 pass | **0.9375 PASS** |

Confusion under LOO: TP 16, TN 15, FP 1, FN 4, n=36.

**All four gates pass.** The completeness judge was not miscalibrated - the binary rubric was
discarding the information that the graded score retains. This is consistent with F-15's diagnosis
that the failure was one-directional over-flagging: a uniformly strict judge with a graded output can
be thresholded, whereas a binary one cannot.

**What this does and does not license.** It establishes agreement with **this annotator's** labels on
36 rows at a cross-validated threshold. It does not establish absolute validity: same single
annotator, same rows, and while the AUC comparison was pre-registered as the adoption test, the
threshold *family* was chosen after nugget recall was known to separate the labels. The supportable
statement is **"qualified on completeness against the available human labels"**. The three
`INSUFFICIENT` tasks remain unresolved and need roughly 4, 2 and 5 more minority-class annotations
respectively - see `locks/PLAN_judge_qualification_and_second_judge.md`.

**Consequence for the record:** the blanket claim "no absolute quality statement is licensed" should
be narrowed. It remains true for M1/M2/TARGET/M4A, and for anything outside the calibrated
completeness decision. It is no longer accurate as a blanket statement about completeness.

### F-56 · A second, independent judge does NOT reproduce the groundedness arm ranking · ACTIVE

MiniCheck-Flan-T5-Large was run as the second judge, chosen by elimination rather than availability.
It is an encoder-decoder T5, so it shares no lineage with Selene (Llama-3.3) or with any drafter
under test (Qwen, Gemma, DeepSeek) - which matters, because judges favour their own generations and
two judges from one family would agree for the wrong reason. Its native task,
(document, claim) -> supported, IS groundedness, so nothing was coerced into a foreign schema.
Published benchmark: 74.7% balanced accuracy on LLM-AggreFact, matching Claude-3 Opus.

**Clean by construction.** v2 discarded its claim texts, so claims were re-extracted and STORED, then
BOTH judges ran over the identical stored claims with identical evidence: 7747 claims across 1011
drafts, **zero length mismatches**. Any disagreement is instrument difference and nothing else. This
mattered: re-extraction alone matches the v2 verdict counts only 98.52% of the time, because
`VLLM_BATCH_INVARIANT` is off and decomposition is not bit-reproducible, so the naive comparison
would have rested on an assumption nobody could check.

#### Per-claim agreement

| | |
|---|---|
| both SUPPORTED | 5347 |
| both NOT_SUPPORTED | 212 |
| Selene only | 1957 |
| MiniCheck only | 231 |
| raw agreement | 0.7176 |
| **Gwet AC1** | **0.6076** |
| Cohen kappa | 0.0744 |
| Selene support rate | 0.9428 |
| MiniCheck support rate | 0.7200 |

Read AC1, not kappa. This is the **kappa paradox**: with one category at 94% prevalence kappa
collapses toward zero even at high agreement. The pre-registered protocol already treats AC1 as
primary and stores kappa as `cohens_kappa_SECONDARY_ONLY` for exactly this reason. AC1 = 0.61 is
substantial agreement, but below our own 0.65 gate.

#### The ranking does not reproduce

| arm | Selene | MiniCheck | delta |
|---|---|---|---|
| extrinsic_DOS-Q | 0.9691 | 0.9218 | **-0.047** |
| intrinsic_P-G | 0.9634 | 0.6966 | -0.267 |
| intrinsic_P-Q | 0.9518 | 0.6406 | -0.311 |
| extrinsic_P-Q | 0.9517 | 0.6275 | -0.324 |
| extrinsic_B-Q | 0.9354 | 0.7073 | -0.228 |
| sensitivity_DOS-Q_matched | 0.9274 | 0.7133 | -0.214 |
| intrinsic_P-D | 0.8130 | 0.5865 | -0.227 |

**Spearman rho = +0.4286.** Only the two endpoints survive - DOS-RAG best, DeepSeek-R1 worst, under
both judges. The middle five positions scramble.

#### The mechanism, measured rather than guessed

Per-arm deltas differ sevenfold (DOS-RAG loses 0.047, extrinsic_P-Q loses 0.324). The driver is
**document length, not passage count**:

| | correlation with MiniCheck score |
|---|---|
| number of passages | +0.053 |
| **document words** | **+0.261** |

DOS-RAG retrieves 2212 words per KC against Proposed's ~914. MiniCheck is ANLI-trained strict
entailment and needs the supporting text present; Selene's rubric accepts partial support. So
DOS-RAG's longer passages make its claims more often *fully entailed*, which MiniCheck rewards and
Selene does not. Selene rated the DOS-RAG-over-Proposed gap at +0.016; MiniCheck rates it +0.294, an
eighteenfold amplification.

This is a genuine construct difference, not a defect in either judge - and arguably MiniCheck
measures something stricter and more externally checkable.

#### Consequence

**The groundedness arm ranking is judge-dependent and must not be reported as robust.** What survives
two independent judges is only: DOS-RAG is the most grounded retrieval arm, DeepSeek-R1 the least
grounded drafter. The intermediate ordering is an artifact of judge choice.

This is what a second judge is for, and it found something real. It rehabilitates nothing:
inter-judge agreement is **reliability, not validity** (`R-08`), and F-55 remains the only result
speaking to validity.

### F-57 · Model-agnosticism is judge-dependent; F-50 downgraded to an ordering claim · ACTIVE
Re-running the pre-registered TOST (delta = 0.05) on the crossed 3x3 design, with **both judges
scoring the identical stored claims** - 7914 claims, **zero length mismatches**, so nothing here is
attributable to claim-set difference:

| comparison | Selene | MiniCheck | |
|---|---|---|---|
| maths: Gemma vs Qwen | +0.0161 **EQUIV** | +0.0346 not | **disagree** |
| maths: DeepSeek vs Qwen | -0.2207 not | -0.0598 not | agree |
| maths: DeepSeek vs Gemma | -0.2558 not | -0.1123 not | agree |
| data-mining: Gemma vs Qwen | +0.0213 **EQUIV** | +0.0476 not | **disagree** |
| data-mining: DeepSeek vs Qwen | -0.1173 not | -0.0419 not | agree |
| data-mining: DeepSeek vs Gemma | -0.1478 not | -0.0996 not | agree |
| sociology: Gemma vs Qwen | +0.0250 EQUIV | +0.0261 EQUIV | agree |
| **sociology: DeepSeek vs Qwen** | -0.0806 not | **-0.0002 EQUIV** | **disagree** |
| **sociology: DeepSeek vs Gemma** | -0.1056 not | **-0.0262 EQUIV** | **disagree** |

Per-claim agreement on this set: raw 0.6884, Gwet AC1 0.5457 (Selene support rate 0.9272 vs
MiniCheck 0.6826) - lower than the ablation set's AC1 0.6076, so the disagreement is if anything
wider out of domain.

**Only 5 of 9 comparisons agree.** F-50's headline - Qwen and Gemma equivalent in all three domains -
reproduces in **1 of 3** under the second judge. In sociology MiniCheck finds DeepSeek equivalent to
both others, contradicting the outlier account entirely.

The **ordering** does reproduce: Gemma >= Qwen > DeepSeek in mathematics and data-mining under both
judges. It is the equivalence *verdicts* that fail, because MiniCheck widens the Gemma-Qwen gap and
compresses the DeepSeek gap.

**A caveat that cuts both ways:** delta = 0.05 is an *absolute* margin applied to two metrics with
different spreads (MiniCheck 0.44-0.78, Selene 0.68-0.99). A reviewer could reasonably argue the
margin should be standardised to each metric's variance. That does not rescue F-50 - it means the
equivalence verdict is sensitive to *both* the judge and the margin, which is itself the finding.

**Consequence:** F-50 is downgraded. The supportable claim is the ordering
(Gemma >= Qwen > DeepSeek, stable across judges and domains), not statistical equivalence.

### F-58 · The EVALUATION STAGES reproduce to 0.17% - so the second-instrument disagreement is real, not noise · ACTIVE (scope corrected 2026-09-02)

F-56 reports that Selene and MiniCheck disagree substantially (Gwet AC1 0.6076, arm-ordering
Spearman rho +0.4286). That finding is only interpretable against a control: **how much would the
numbers move if we simply ran the same pipeline twice?** Re-judging with Selene over re-extracted
claims supplies exactly that comparison - a full end-to-end re-run of decomposition *and* judging.

| | |
|---|---|
| comparable drafts | 996 (15 skipped for claim-count mismatch) |
| claims compared | 7610 |
| **per-claim agreement** | **0.9983** - 13 of 7610 flipped |
| support rate | 0.9432 -> 0.9431 (drift -0.0001) |
| **max arm-level drift** | **0.0027** |
| **arm-ordering Spearman rho** | **+0.9643** |

Per-arm drift: DOS-RAG +0.0008, Gemma -0.0019, extrinsic_P-Q -0.0010, Qwen 0.0000, BaseDense +0.0008,
budget-matched +0.0027, DeepSeek -0.0025. The single ordering change is an adjacent swap between two
arms separated by 0.0001, which is not a ranking change in any meaningful sense.

#### Why this matters for F-56

| comparison | per-claim agreement | arm-ordering rho |
|---|---|---|
| **Selene vs itself** (re-run) | **0.9983** | **+0.9643** |
| Selene vs MiniCheck | 0.7176 (AC1 0.6076) | +0.4286 |

The instrument is essentially deterministic at the aggregate level, so the second-judge disagreement
**cannot be attributed to run-to-run noise**. It is a genuine construct difference between a
partial-support rubric and strict entailment. This strengthens F-56 rather than weakening it.

#### A reproducibility result in its own right

This is the first direct measurement of end-to-end reproducibility for this pipeline, and it is
better than expected given `VLLM_BATCH_INVARIANT` is **off** on this server. Nondeterminism does
exist and is visible where you would expect it - **1.5% of drafts re-decompose to a different claim
count** - but it barely propagates: claim-level agreement is 99.83% and no arm moves by more than
0.003.

Practical reading for the writeup: batch invariance remains the correct configuration (F-07), but its
absence perturbs *aggregate* conclusions here far less than it perturbs individual judgements. A
campaign of this size absorbs the noise; a 36-row calibration set would not.

---

## Changelog

| date | change |
|---|---|
| 2026-09-01 | F-58 added: full pipeline re-run agrees with itself on **99.83%** of claims, max arm drift 0.0027, ordering rho +0.9643. This is the control that makes F-56 interpretable - the second-judge disagreement (AC1 0.61, rho 0.43) cannot be run-to-run noise. Also the first direct reproducibility measurement: batch invariance is off and 1.5% of drafts re-decompose differently, but it barely propagates to aggregates. |
| 2026-09-01 | **F-56/F-57: the second judge does NOT reproduce the rankings.** MiniCheck-Flan-T5, chosen for architectural independence, judged the IDENTICAL stored claims (7747 claims, 0 length mismatches). Per-claim Gwet AC1 0.6076 - read AC1 not kappa, 94% prevalence triggers the kappa paradox. Arm ordering Spearman rho +0.43: only DOS-RAG best and DeepSeek worst survive. Driver is document length (r=+0.26); DOS-RAG retrieves 2212 words vs Proposed's 914. F-50's model-agnosticism reproduces in 1 of 3 domains and is downgraded to an ordering claim. |
| 2026-09-01 | **F-55: the judge QUALIFIES on completeness** when scored with the v2 graded metric at a leave-one-out threshold - all four gates pass (0.8611 / 0.7224 / 0.800 / 0.9375) against v1 holistic M3's 0.556 / 0.392 / 0.400. The failure was the binary rubric, not the judge. M1/M2/TARGET were never disagreement failures - they lack minority-class rows, and TARGET already agrees at 0.906. |
| 2026-09-01 | F-54 added: the judge matches MEANING, proven arithmetically - DeepSeek scores 69% vital recall on 1.5% lexical overlap, and 32 Gemma drafts score a perfect 1.0 with under 5% overlap. Within-arm overlap-recall correlation is +0.80 for the seed arm but only +0.11 to +0.21 for the others, which rules out judge-side lexical bias and localises the seed asymmetry to the two Qwen-lineage arms. |
| 2026-09-01 | **v3 complete.** F-49 control 6 CLEARS the seeded library (0 distortion, 0 unsupported assertion, no stratum effect) and **F-48 is CORRECTED as over-claimed**. F-50 model-agnosticism established by TOST: Qwen=Gemma equivalent in all 3 domains, drafter variance 0-6.4% excluding the outlier. F-51 domain-agnostic except mathematics. F-52 pooled IR judgements RESTORE the efficiency claim (BaseDense P@10 0.369 vs Proposed 0.628). F-53 acceptability triage fails - non-discriminating and only 0.462 agreement with the expert. |
| 2026-09-01 | **F-48 added — withdraws both completeness rankings.** The expert reference is seeded from Qwen (117/159 verbatim; manifest-documented, 8-gram overlap 0.807 confirms). The seed arm scores exactly 1.0000 on all 116 accepted references - a tautology, since the nuggets come from its own text - and every nugget-recall ranking REVERSES on the 35 expert-rewritten ones. Faithfulness, judged against evidence, is stratum-stable and STANDS. |
| 2026-09-01 | **F-46 FINAL (n=143)**: padding to 123 passages RAISES faithfulness by 0.0175 (CI [-0.0325,-0.0024], McNemar p=0.00082) - opposite in sign to F-45. Faithfulness comparisons against BaseDense STAND and are conservative. One blinding-exempt row re-judged; audit now 21/21. |
| 2026-08-31 | F-46 added (INTERIM, n=26/145): padding evidence to 123 passages does NOT lower faithfulness (0/26 KCs; mean -0.0199, CI [-0.0494, 0.0000]) - opposite to F-45's +0.4095 drop in context recall. The faithfulness comparisons against BaseDense STAND and are conservative. |
| 2026-08-31 | F-47 added: domain per-claim faithfulness recovered from stored verdicts (the `_per_claim` field is a scalar; the real data is in `responses.m1`). Restated macro: maths 0.9199 / sociology 0.9666 / data-mining 0.9591. F-34's p^n artifact reproduces out-of-domain to within 0.021 on maths. Domain sets are <=38 passages so F-45 barely applies. |
| 2026-08-31 | **F-45 added — forces a retraction.** The judge recovers only 0.5905 of nuggets that are provably present when the set holds 123 passages (1.0000 at 17). Serial-position effect, truncation ruled out. Context recall is NOT comparable across arms with different retrieval budgets; the BaseDense efficiency claim in F-37/C-06 is withdrawn. Nugget recall is unaffected (judged on drafts). |
| 2026-08-31 | **F-37 CORRECTED**: micro- vs macro-averaging reconciled (protocol fixes KC as the unit, so macro governs; ranking identical under both), and the untested "Proposed wins on retrieval" claim withdrawn - Proposed vs DOS-RAG is p=0.824 on context recall. |
| 2026-08-31 | F-44 added: v2 completeness length-adjusted. All 3 extrinsic comparisons survive; intrinsic Gemma-over-DeepSeek SIGN FLIPS and is withdrawn, reproducing F-35 on a new metric. |
| 2026-08-31 | F-43 added: forced vs chosen abstention separated; no arm ever drafted from an empty evidence set (0/1113). |
| 2026-08-31 | F-42 added: reference coverage is 152/159 and the uncovered KCs are non-random - 4 of 7 are exactly where Proposed retrieved nothing, so absolute retrieval recall is flattered. |
| 2026-08-31 | **F-40 RESOLVED**: calibration returns B = 0.0000: no constant prompt offset. Residual set-size threat split out as F-45. |
| 2026-08-31 | v2 faithfulness completed on a SINGLE instrument (Cluster A). Reproduces the v1 mixed-instrument figures to max |delta| 0.0034, mean 0.0013 - independent corroboration of F-12. |
| 2026-08-31 | F-41 added: server hit a 6h SLURM limit mid-stage; runner recorded 538 silent CALL_FAILED rows and reported success. Time limit raised to 24h and a consecutive-failure abort added. |
| 2026-08-31 | F-38/F-39/F-40 added: v2 nugget recall computed, PASSES its adoption test (AUC .858 vs .700), and the context-vs-nugget gap flagged as prompt-asymmetry confounded rather than parametric leakage. |
| 2026-08-31 | F-37 added: context recall (generator-free) INVERTS the v1 retrieval ranking - Proposed best at 17 evidence items, BaseDense worst at 123. |
| 2026-08-31 | F-36 added: nugget decomposition fails deterministically on formula-heavy references (character bound); exclusion is non-random and disclosed. |
| 2026-08-31 | F-35 added: completeness is verbosity-confounded; length-adjusted reporting made mandatory. Qwen3.8's advantage survives adjustment, DeepSeek-R1's deficit does not. |
| 2026-08-31 | F-34 added: M1 ranking shown to be largely an all-or-nothing aggregation artifact; per-claim support becomes the primary faithfulness measure. |
| 2026-08-31 | Ablation campaign COMPLETE. F-26..F-33 added (results, guard defect, F-28 SUPERSEDED by F-29 via AMENDMENT_01). |
| 2026-08-31 | F-07 added; **F-06 marked SUPERSEDED** — batch invariance makes concurrency verdict-neutral. F-22 added from literature check. Document created, consolidating F-01…F-25. |
| 2026-08-30 | F-10 **CORRECTED** (scope narrowed: Cluster-B runs Selene fine; the Cluster A-built CUDA-13 stack does not). F-11, F-12, F-13 added. F-20, F-21 added. F-23, F-24 added. |
| 2026-08-29 | F-14…F-19 added: qualification result and M3 diagnostic. |
