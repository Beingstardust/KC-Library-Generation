# 73. R8 assessment inventory and investigation contract

This audit starts from the frozen r7 artifact at `data/v3/runs/final_vnext_r7_20260821/` and the
post-r7 assessment supplied on 2026-08-22. Every suggestion below is a hypothesis until it survives
corpus-wide diagnosis, a controlled A/B where behavior can change, and regression checks against
r7. Rejected ideas remain recorded with measurements so they are not rediscovered later.

## Non-negotiable baseline

R7 remains frozen: 159 KC packets, 116 grounded, 30 partial, 13 abstained, and 484 verification
checks passing. No experiment writes into its run directory. Pipeline changes may not lower the
main relevance floor, fill the context budget merely because room remains, add hand-written
subject vocabulary, add per-KC branches, invent missing mathematics, or use fine-tuning.

## Suggestion inventory

| assessment suggestion | initial finding | investigation required |
|---|---|---|
| target identity as a support requirement | confirmed defect; current r7 evidence shows the failure is licensed mainly by contextual admission, not the subset branch | measure every anchoring branch, test source-definitional subjects and exact source anchors, preserve ordinary supporting evidence |
| separate scoring representation from evidence payload | partly present in r7 through anchored source-block scoring and pointer payload recovery | measure which structural rows use it, identify residual context-poor rows, reject any blanket contextualization |
| set-level sufficiency completion | not present as a distinct retrieval objective; two earlier completeness proxies failed in doc 64 | measure missing expected shapes and whether bounded source-local candidates can clear unchanged integrity/ownership gates |
| adaptive evidence budget | partially achieved by relevance gating; mean packet size is far below the 14K ceiling | compare an explicit stopping/completion rule only if it adds information rather than volume |
| source-aware ordering | already present by relevance-ranked source region and source order within region; final authority tiers can separate neighboring roles | generation-only A/B on identical evidence, current order versus source-contiguous semantic regions |
| source-grounded alias completeness | hierarchy carries no alias field and r7 profiles have no registry aliases; deterministic parenthetical variants do exist | determine whether a generic source-derived equivalent can be validated without model invention or subject-specific curation |
| verification findings affect status | current sidecar is advisory; the definitional-subject check contains one clear wrong-target case plus ordinary/generic/pronominal openings | only high-precision violations may become operational; measure each candidate rule over all drafts before changing status |
| mathematical claim-to-span traceability | evidence maps claims to evidence IDs, but no normalized equation-to-source relation is checked | build a conservative diagnostic first; no theorem proving or inferred equivalence |
| layout-preserving mathematical evidence | extraction loss is confirmed for residual formula ceilings | inventory existing extraction layers and intact alternatives before proposing ingestion changes |
| target-binding stress test | one natural negative control exists and fails upstream | derive candidates generically from hierarchy/corpus relations, validate support absence, compare systems on false support |
| broader evaluation battery | r7 already records coverage, provenance, evidence volume and determinism, but cost and target-binding metrics are incomplete | report component metrics and a Pareto view without substituting proxy counts for quality |
| end-to-end cost accounting | packet and drafting wall times exist; comparator accounting is incomplete | recover logs or rerun matched instrumentation, separating offline indexing, retrieval, prompt volume and drafting |

## Prior work that constrains the search

The following are not fresh candidates: proximity-window anchoring missed Mutually Exclusive
Classes and demoted nine unrelated units (doc 69); ancestor-qualified reranker queries for External
Entropy were tried twice and rejected (docs 64 and 72); unused admitted evidence did not predict
completeness (mean unused share 0.64 across good and bad drafts); sibling shape norms covered only
one of eight reviewed completeness failures; and broader bar-loss detection would delete unique
mathematics without a replacement (docs 58 and 71).

## Literature check

The primary DOS-RAG paper confirms 100-token passage retrieval followed by restoration of original
document order, and explicitly limits its evidence to single-long-document multiple-choice and
short-answer QA with GPT-4o-family readers. It leaves open multi-document, open-ended and specialized
generation, and does not measure full preprocessing/embedding cost:
<https://aclanthology.org/2025.emnlp-main.1656/>.

Late Chunking supports the representation-boundary diagnosis, especially for short chunks, but is
an embedding-architecture change rather than evidence that every fragment should inherit context:
<https://arxiv.org/abs/2409.04701>. Adaptive-k selects retrieval depth from score-distribution gaps
without fine-tuning, but its evidence is QA rather than curriculum artifact construction:
<https://aclanthology.org/2025.emnlp-main.1017/>. RAGChecker supports component-level diagnostic
reporting rather than treating one fluent answer score as the whole system:
<https://proceedings.neurips.cc/paper_files/paper/2024/hash/27245589131d17368cccdfa990cbf16e-Abstract-Datasets_and_Benchmarks_Track.html>.

## Target-binding measurement

`v3/evaluation/investigate_r8_assessment.py` calls the live packet builder's target-anchor predicate
over all frozen packets. It reports evidence-level branch use, packets that depend only on the weak
subset branch, profile/alias coverage, source-order inversions after final ordering, and current
definitional-subject/status contradictions. This is diagnosis only and cannot rewrite an artifact.

The assessment's localization to the subset branch was not correct for the current r7 artifact.
The negative control's passages are mostly admitted through `context_anchored_relevance`, which is
one of the bases the support gate treats as a strong target anchor. Corpus-wide branch counts are:

| live anchor branch | evidence items |
|---|---:|
| licensed admission basis | 1,889 |
| exact source phrase | 308 |
| term subset only | 124 |
| none | 307 |

No packet depends only on the subset branch. Eight packets have no strong anchor and are already
weak or insufficient. A strict requirement for a positive source identity would demote 31 currently
draftable KCs, including legitimate source paraphrases. A generic veto for any foreign definitional
subject would demote 16 and includes ordinary pronouns and peripheral subjects. Both are rejected.

The accepted candidate is narrower. For a label shaped `modifier modifier HEAD`, it detects an
assertable copular statement where all target modifiers occur in the predicate, the target head is
absent, and another head occurs in both subject and predicate. It acts only when no assertable
passage provides an exact target surface, target-named defining equation, or compatible
definitional subject. Over all 159 frozen packets it changes exactly one support state:

```
Mutually Exclusive Classes
draftable -> insufficient_support
reason: modifier_matched_foreign_head_without_positive_target_identity
```

The three matching source statements all identify rule/rule-set objects, including the explicit
definition "rules in a rule set R are mutually exclusive if ...". No curriculum term, KC ID,
document ID, or per-unit branch occurs in the mechanism. INT-23 contributes seven live guards.
The complete verifier reports 491 checks and zero failures. Deliberately replacing the live veto
with `return False` produces exactly one failure, INT23-2; restoring it returns both edited files to
their pre-sabotage SHA-256 values and the suite to zero failures.

The whole-pipeline packet A/B ran both arms sequentially in one primary-cluster GPU allocation against the
same 159 frozen profiles, 100,218-row corpus and dense cache (job 249460, 00:41:47). Both arms have
155 units with evidence, four empty units, 16.53 mean passages, 4,957.4 mean characters, and the
same definition/formula/procedure/example coverage. Evidence identity, multiplicity, text and order
are unchanged for the target. The only functional transition is:

```
KC_CLF_UND_005  draftable -> insufficient_support
abstention_expected: false -> true
evidence items: 9 -> 9
```

One additional packet was reported as changed between the sequential arms, but a field-level diff
isolates it to a BM25 score serialized as 12.5250 versus 12.5249; the regenerated baseline versus
frozen r7 similarly has two 0.0001 BM25 rounding deltas. No evidence was added, lost, reordered or
rewritten, and no support state changed in those packets. The comparison tool reports these full
object differences rather than silently rounding them away; they are measured runtime score noise,
not an INT-23 side effect.

The candidate packet was then sent alone through the exact r7 Cluster A H100 drafting mirror (job
1683022, 00:00:24). It produced one expected `abstained` row with an empty body, zero cited evidence,
zero hard failures and zero hygiene findings. This repairs the natural control end to end rather
than merely changing metadata. Finally, the exact normalized files ran on the primary compute cluster (Linux) with 491/491
checks passing. Their normalized-LF SHA-256 values are
`cb54bc74ae1e521f43c25676ebc4b5c822bb5fa30949efd0c4dbf851932a2e57` for the packet builder and
`74d998b9c5d632270d0382d9171f882829f898ca91c9fcb6d2d943d102fc3f08` for the verifier.

## Alias audit

R7 profiles contain zero registry aliases and zero retrieval-disambiguation terms; 77 carry more
than one deterministic parenthetical/label variant. `investigate_r8_profile_surfaces.py` scans all
100,218 corpus rows using only source-observed, head-preserving n-grams and hierarchy-derived branch
context. Canonical core wording is observed for 103 profiles; 48 draftable profiles lack it, showing
that exact phrase absence is not concept absence.

Classification Threshold's source gap is real: `cutoff` occurs 14 times, `score threshold` 60
times, and 25 of the 31 branch-context `score threshold` occurrences co-occur with an already
licensed target surface. `cutoff threshold` has six occurrences and all six satisfy both checks.
But the same generic candidate rule emits hundreds of false sibling and same-head alternatives for
other profiles, especially families of indices, distances and entropies. Automatic alias mutation
is therefore rejected. The source-surface report is retained for registry review; no Data Mining
alias is written into pipeline code or a generated profile.

## Context, selection and budget

The proposed scoring/payload separation is already present and heavily exercised. Of 2,628 r7
evidence items, 1,696 use an anchored contextual scoring view. Separately, source-linked payload
recovery admits 124 lead-in payloads, 20 structured-list payloads, six procedure-list payloads and
seven formula qualifiers; 36 more are target-named defining equations. Evidence payload text and
fine provenance remain unchanged. This directly implements the conservative principle supported by
Late Chunking without replacing the embedding architecture or contextualizing every row.

The budget is adaptive in practice because only admitted passages consume it:

| statistic | characters | passages |
|---|---:|---:|
| mean | 4,957 | 16.53 |
| median | 4,170 | 13 |
| p90 | 11,159 | 36.2 |
| maximum | 13,997 | 40 |

Only ten packets exceed 90% of the character ceiling and nine reach the passage ceiling. The
reviewed residual failures are mostly far below both: Classification Threshold has 256 characters,
F-Measure 571, Spearman 656, External Purity 1,902, External Entropy 2,264, and the threshold-effect
KC 4,691. A larger or score-gap-selected `k` cannot recover candidates that failed the unchanged
relevance/ownership gates. An additional adaptive-budget policy is rejected as redundant.

The existing deterministic expected-shape heuristic is also not fit to drive a completion stage.
It predicts a structural requirement for only 31 profiles and reports four missing formulas. All
four are lexical false positives: substring matching reads `ratio` or `rate` inside `generation`,
`integration`, and `strategy`. It misses most externally reviewed completeness cases. Earlier
sibling-shape norms covered only one of eight cases, and unused evidence averaged 0.64 in good and
bad drafts alike (doc 64). A bounded role-completion search still needs a trustworthy, source-bound
slot specification; inventing one from the named failures would be domain/evaluation fitting.

Exact/near duplicate diagnostics find 12 exact duplicate pairs and 194 pairs with token Jaccard at
least 0.90. Inspection shows extractor twins, repeated worked-example values, repeated list labels,
and genuinely distinct formulas sharing most terms. Cross-document duplicates can provide source
corroboration. The possible safe reduction (same document/page, byte-equivalent extractor twins)
is too small to justify another selection intervention in this cycle; near-duplicate removal is not
safe.

## Source ordering experiment

`assemble_passages` already ranks source regions by utility and restores document/page order inside
each region. `order_by_definitional_authority` then stably places definitions and formulas before
procedures, examples and questions. Reconstructing the pre-authority region order changes 145
packets and reverses 9,619 item pairs, so this is a real hypothesis rather than a cosmetic sort.

The generation-only A/B uses 11 externally reviewed problem/DOS-advantage cases plus eight grounded
controls selected by a fixed SHA-256 rule. All non-evidence packet fields and the evidence
multisets are identical; only `evidence_for_synthesis` order differs. Two reviewed packets have
one/two evidence items and therefore form no-op determinism controls. Both arms ran sequentially
through the exact r7 Cluster A
drafting mirror on one H100, one Ollama server, one prompt and one seed (job 1683021, 00:15:07).
Both no-op bodies were byte-identical, so the 17 reordered comparisons are readable rather than
generation noise. There were no technical failures or status changes: both arms produced 13
grounded and six partial drafts.

Source order reduced aggregate hygiene findings from 71 to 35, but the aggregate hides a highly
mixed result. The externally reviewed stratum's body-ledger gaps fell from 45 to 18, dominated by
turning one runaway Confidence Interval draft from 7,979 to 2,533 characters. Across the eight
healthy controls, however, source order reduced body text from 14,280 to 12,145 characters,
evidence-map entries from 79 to 70, and distinct citations from 89 to 78, while body-ledger gaps
rose from 12 to 14. Manual paired review likewise found trade-offs: the source-order arm made the
damaged F-Measure formula more cautious and the Confidence Interval draft much cleaner, but lost
the chi-squared relation and other supported detail from Test Statistic, shortened valid handling
detail from Missing Value, and removed useful qualifications from Spearman and SFG. A global
source-order rewrite is therefore rejected: it can control a runaway draft, but it does not improve
completeness without regressions. A special ordering rule for the named failures would be exactly
the case-specific optimization this investigation forbids.

## Verification and mathematics

The r7 hygiene sidecar has 323 findings. The six definitional-subject findings are not one uniform
status error: one is the clear wrong-target negative control; the remainder include pronoun,
generic, example and threshold openings, with at least one borderline case. Applying INT-19
wholesale to status would create false demotions. INT-23 instead prevents the single verified case
upstream, where `insufficient_synthesis_support` and `abstention_expected` already force the normal
drafting contract to abstain.

`investigate_r8_math_traceability.py` audits every explicit top-level relational operator in the
159 r7 draft bodies. It normalizes wrappers, whitespace, Unicode comparison signs and common LaTeX
fraction spelling, then requires operator-centered literal agreement on both sides in one admitted
source item. It is explicitly a lower bound, not symbolic equivalence:

| math trace diagnostic | count |
|---|---:|
| drafts containing relations | 60 |
| top-level relation occurrences | 186 |
| literal admitted-source matches | 119 |
| relations represented literally in an evidence-map claim | 138 |
| source match cited by that matching claim | 85 |
| drafts with at least one unresolved literal relation | 34 |

The unresolved set mixes genuine ledger gaps with variable renaming, equivalent re-rendering,
fraction-bar extraction loss, and multi-expression normalization differences. A literal-only status
gate would therefore reject valid mathematics; algebraic equivalence would require a much larger,
riskier theorem/normalization subsystem. The diagnostic is retained as review evidence and no
automatic status change is made.

## Ingestion boundary

The corpus already combines multiple extraction layers and the repair path uses an independent
extractor only when it supplies a clean twin. INT-22 measured 109 splice candidates before safety
checks; INT-22b makes 80 repairs over 86 rows and refuses substitutions that would orphan unique
mathematics. Twenty of the original 83 substitutions would have deleted a unique formula. The
remaining External Purity and Chi-Squared failures have no intact machine-readable twin. A second,
layout-preserving evidence representation would require returning to source PDF/table/equation
coordinates and changing the ingestion contract. It is correctly located as future ingestion work,
not disguised as a retrieval fix or reconstructed from model knowledge in r8.

## Stress-test boundary

The corpus supplies one expert-validated natural unsupported near-neighbor: Mutually Exclusive
Classes. The strict identity audit finds 31 more packets without a conservative positive identity,
but manual inspection shows many are valid paraphrastic support; the source-surface audit similarly
finds 48 draftable labels without canonical wording. Neither set can be relabeled as negative
controls. Hierarchy head swaps or nonce labels can create synthetic unsupported queries, but they
do not establish that a plausible real curriculum concept is absent and would reward this one
grammar rule. R8 therefore reports one natural control plus generic synthetic liveness fixtures,
not a misleadingly large automatically labeled benchmark. A broader target-binding benchmark needs
independent expert annotation before it can support false-support-rate claims.

The assessment's implied comparator result also required correction. In the frozen controlled run,
Base Dense receives 133 items/12,956 characters and DOS-RAG 32 chunks/13,304 characters for this
target; neither packet has a precomputed insufficiency flag. Nevertheless, the shared Qwen prompt
abstains correctly in both arms. Proposed receives only nine items/3,256 characters but marks the
packet draftable and produces the wrong rule-set definition as `grounded`. On the one natural
control the observed false-support draft count is therefore Base Dense 0, DOS-RAG 0, r7 Proposed 1.
INT-23 repairs a real proposed-system regression and restores expected abstention; it does not by
itself establish superior target binding over DOS-RAG.

## Cost accounting

The controlled three-way run `final_e3944aa_20260818T140248Z` and SLURM accounting independently
confirm the evidence figures used in the assessment: Proposed averaged 4,931.8 evidence characters
and 16.57 items/KC; Base Dense 10,730.8 characters and 123.8 items; DOS-RAG averaged 13,919.2
characters and 33.71 chunks. On matched primary-cluster A100-class drafting jobs,
Proposed took 01:43:31, Base Dense 02:25:39, and DOS-RAG 02:32:16. The shorter proposed prompts
therefore reduced generation wall time by about 32% versus DOS-RAG in that run.

Retrieval cost cuts the other way in the original comparator: CPU `big` jobs took 06:33:01 for
Proposed, 00:35:53 for DOS-RAG and 00:00:47 for Base Dense with a reusable dense cache. That result
documents substantial extra retrieval engineering, but is not a current-hardware comparison: the
proposed cross-encoder ran on CPU. The optimized r7 packet job on the primary cluster's GPU took 00:21:24 and the
r7 H100 drafting job 01:17:06. A fair Pareto report must keep both views and label hardware/cache
state rather than claiming one total-runtime winner. Shared upstream PDF extraction time and a cold
DOS embedding/index build were not separately instrumented; this remains a measurement gap, also
acknowledged by the DOS-RAG paper for its own preprocessing cost.

## Final disposition

| hypothesis | r8 disposition | reason |
|---|---|---|
| target identity as support | **accepted as INT-23** | one natural false-support regression repaired; 1/159 functional packet change; sabotage, packet A/B and generation check pass |
| contextual scoring versus payload | **retain r7** | already active for 1,696 items plus bounded structural payload rescues; no verified missing generic mechanism |
| set-level sufficiency completion | **rejected for now** | existing shape predictor is sparse and has substring false positives; prior proxies do not predict reviewed gaps |
| adaptive evidence budget | **rejected** | reviewed gaps are mostly far below the ceilings and concern admission, not available budget |
| source-aware ordering | **rejected globally** | improves one runaway draft and aggregate hygiene but removes supported detail and citations from healthy controls |
| automatic source aliases | **rejected** | real source gaps exist, but the generic candidate emits hundreds of false sibling/same-head aliases |
| hygiene findings change status | **rejected globally** | five of six definitional-subject flags are not high-precision status errors; the one clear case is prevented upstream |
| equation-to-span status gate | **diagnostic only** | literal matching leaves valid re-renderings/equivalences unresolved in 34 drafts |
| layout-preserving mathematics | **future ingestion work** | remaining failures have no intact machine-readable twin and cannot be reconstructed safely in retrieval |
| target-binding benchmark | **one natural control only** | automatically generated negatives are not independently validated and would reward one grammar |
| broader metrics and cost | **reported, no gate change** | component quality, evidence volume and hardware/cache-specific timing must remain separate claims |

R8 therefore ships one generic behavioral change, not a bundle of plausible tweaks. It does not
fine-tune a model, lower a relevance or ownership gate, add curriculum vocabulary, add a per-KC
branch, alter evidence payloads, or overwrite the frozen r7 artifact. The rejected experiments and
their scripts remain in the audit so a later cycle can start from measurements rather than repeat
the same attractive failures.
