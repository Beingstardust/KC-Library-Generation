# Model-agnosticism consistency audit

**Why this document exists.** The previous consolidation pass treated "model-agnostic" as a claim
about *performance equivalence across drafters*, found that equivalence did not reproduce under a
second evaluator, and marked the claim `WITHDRAWN`. That was a category error. Model-agnosticism is
an **architectural** property; performance equivalence is a separate empirical question that the
intrinsic ablation exists to answer. This document records the correction and the evidence.

---

## 1. The three concepts, kept apart

| term | means | status |
|---|---|---|
| **Drafter-model-agnostic architecture** | No particular LLM is structurally required by the drafting pipeline. | **SUPPORTED** — §3 |
| **Drafter portability** | Multiple model families execute the same frozen drafting contract without rebuilding the surrounding pipeline. | **SUPPORTED_WITH_SCOPE** — §4 |
| **Drafter performance equivalence** | Substituting a model does not materially change output quality. | **NOT ROBUST** — §5. *Not the definition of model-agnosticism.* |

The corresponding pair on the domain side is kept in
`DOMAIN_AGNOSTICISM_IMPLEMENTATION_AUDIT.md`: domain-agnostic architecture and cross-domain
portability are architectural; cross-domain performance is separate.

## 2. What was wrong before

| previous treatment | why it was wrong |
|---|---|
| `MODEL_AGNOSTIC` → `WITHDRAWN` because TOST equivalence did not reproduce | Conflates architecture with performance. Failure of performance equivalence says nothing about whether the drafter is structurally replaceable. |
| The TOST analysis labelled a "model-agnosticism test" | It is a drafter *sensitivity* analysis. Its question is how much quality changes when the drafter changes under fixed evidence. |
| Domain TOST labelled a "domain-agnosticism" result | Same error on the domain axis. |

The experiments themselves are untouched and remain valid. Only their names and interpretation
change.

## 3. Architectural evidence — implementation audit

Audited `v3/pipeline/04_draft_runner.py` (1,508 lines) and the surrounding pipeline stages.

**Single generic call path.** All generation goes through one function whose model is a parameter:

```python
def ollama_generate(host, model, prompt, num_ctx, timeout_s, num_predict=None):
    payload = {"model": model, "prompt": prompt, "stream": False,
               "format": "json", "think": False, "options": options}
```

**No conditional branch on model identity anywhere in the pipeline.** A grep for conditionals testing
a model name (`if ... model ... in/==/startswith/lower`) across `v3/pipeline/*.py`, excluding
argument plumbing, returns **nothing**.

**Model selection is configuration, not logic.** The model arrives as a CLI argument with an
environment default:

```python
ap.add_argument("--model", default=os.environ.get("KC_L_PROFILE_MODEL", "gemma4:31b"))
```

A selectable model identifier does not violate architectural agnosticism.

**The one capability accommodation is applied unconditionally.** `"think": False` is set for every
model, and the code comment records the reasoning explicitly — that reasoning-capable models spend
their token budget on internal reasoning and return empty structured answers, that this is *general
rather than model-specific*, and that the parameter is a no-op for models lacking the capability.
This is precisely the shape a model-agnostic accommodation should take: uniform, not branched.

**Common contract on the output side.** All three drafters emit the same structure —
`draft.contextual_kc_draft.{text, status, supporting_evidence_ids, coverage_notes}` — and all nine
drafter × domain cells were parsed by one extraction contract without per-model handling. That is
independent confirmation from the artifacts, not just from the code.

## 4. Portability evidence — empirical

The same frozen drafting contract was exercised, without architectural modification, by three
distinct model families across three domains — nine cells, 1,137 drafts:

| | mathematics | data-mining | sociology |
|---|---|---|---|
| Qwen3.8-27B | 71 | 159 | 149 |
| Gemma4-31B | 71 | 159 | 149 |
| DeepSeek-R1-32B | 71 | 159 | 149 |

All nine cells produced parseable drafts under the same schema, with abstentions recorded through the
same status field.

**Scope limit.** Three model families were tested. The supportable claim is that these three worked
through a common interface — **not** that any LLM will work. A model that cannot honour the JSON
output contract would fail, and one did fail historically until `think: False` was added.

## 5. Performance sensitivity — the separate question

Holding retrieved evidence fixed and substituting the drafter changes output quality:

- Under the primary evaluator, Qwen and Gemma are close (differences +0.016 to +0.028) while
  DeepSeek-R1 shows larger deficits (−0.076 to −0.256).
- Under an independent entailment verifier scoring identical claims, the Qwen/Gemma closeness
  reproduces in **1 of 3** domains, and only 5 of 9 comparisons agree.
- Drafter behaviour differs structurally too: DeepSeek writes 118/114/123 words across the three
  domains against Qwen's 208/234/245, and self-reports `grounded` on ~99% of KCs.

**Correct conclusion: portability does not imply performance equivalence.** Model choice remains
consequential *within* a model-agnostic architecture, and the ablation exists precisely to measure
that.

## 6. Renamings applied

| was called | now called |
|---|---|
| model-agnosticism test / proof of model agnosticism | **drafter performance-equivalence analysis** (equivalently, cross-model drafter sensitivity analysis) |
| domain-agnosticism test / failure of domain agnosticism | **cross-domain performance sensitivity analysis** |
| `MODEL_AGNOSTIC` (withdrawn) | split into `DRAFTER_ARCHITECTURE_AGNOSTIC`, `DRAFTER_PORTABILITY_TESTED`, `DRAFTER_PERFORMANCE_EQUIVALENCE` |
| `DOMAIN_TRANSFER` (partial) | split into `DOMAIN_ARCHITECTURE_AGNOSTIC`, `CROSS_DOMAIN_PORTABILITY_TESTED`, `CROSS_DOMAIN_PERFORMANCE_EQUIVALENCE` |

## 7. Locations corrected

| file | correction |
|---|---|
| `PAPER_CLAIM_LEDGER.md` / `.json` | `MODEL_AGNOSTIC`/`DOMAIN_TRANSFER` replaced by the six-claim split; the withdrawal no longer touches the architectural claims |
| `RQ_EVIDENCE_MAPPING_FINAL.md` | architectural agnosticism mapped to interface analysis and multi-family execution; performance sensitivity mapped separately to the ablation |
| `PAPER_CORE_NARRATIVE.md` | terminology corrected; portability/equivalence distinction made explicit |
| `PAPER_NONCLAIMS.md` | "we do not claim the pipeline is model-agnostic" replaced with the accurate non-claims: no claim of performance invariance, and no claim that any LLM will work |
| `RESULTS_EVIDENCE_MATRIX.md` | equivalence rows relabelled as sensitivity; architectural rows added |
| `THREATS_TO_VALIDITY_MASTER.md` | architectural-audit limits recorded (static audit cannot catch semantics expressed without subject vocabulary) |
| `KC_L_EVALUATION_RECORD_v3_INTERNAL_FINAL.md` | §V and §VI rewritten around the corrected definitions |
| `EVALUATION_FINDINGS.md` | F-50/F-51 titles and bodies marked with the definitional correction; findings retained |

## 8. Terminology rule, for all future writing

| use | to mean | never to mean |
|---|---|---|
| model-agnostic | the drafter is structurally replaceable | drafter performance is invariant |
| domain-agnostic | subject matter enters via corpus and curriculum, not pipeline semantics | domain performance is invariant |
| model sensitivity | quality changes when the drafter changes | — |
| domain sensitivity | quality changes when the subject changes | — |

These are architecturally and statistically different claims and must not be substituted for one
another.
