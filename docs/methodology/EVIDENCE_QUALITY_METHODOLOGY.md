# Evidence Quality Methodology

This document captures, precisely enough to reuse or defend in the thesis, the methodology
developed across the 2026-07-20/22 investigation into KC draft regression, cross-branch evidence
contamination, and evidence-quality signaling. It covers four things: how correctness was
verified, what contamination mechanisms were found and fixed, how the branch-scoping granularity
decision was made, and what limitations remain honestly unresolved.

See also: `kc_l_v2_streamlit_console/ARCHITECTURE_REPORT.md` for the console's own data-path
audit, and `kc_l_v2_streamlit_console/review_priority.py` for the reviewer-facing implementation
of the evidence-quality signals this document motivates.

## 1. The content-verified census method

Every correctness judgment in this investigation — which KC drafts regressed, which improved,
which stayed wrong — was made by directly reading the generated draft text and its cited
evidence, then checking that evidence against the real corpus text at its stated page, not by
trusting pipeline status labels (`draft_status`, `packet_support_state`, risk flags) or by
diffing draft text between runs.

This distinction matters because status labels answer "did the pipeline think this was
grounded," not "is this actually correct" — and diffing catches *that* something changed, not
*whether* the change was for the better. Both are necessary inputs but neither is sufficient on
its own. Two concrete failures this session that a status/diff-only method would have missed:

- A unit's `packet_support_state` can be `draftable` (normal confidence) while the draft is still
  topically wrong — see §5, `KC_EVAL_BASIC_006`. The pipeline's own confidence signal was never
  designed to catch term-polysemy contamination (same word, two unrelated concepts), so it
  doesn't flag it, and it wouldn't show up as a diff-only "regression" against a baseline that
  was also wrong.
- Draft text can change between two runs of *structurally identical code* due to retrieval
  non-determinism (confirmed independently in the Phase A alias-fix rerun and again in the
  Phase 2 branch-scoping rerun) — a raw diff would report these as regressions or improvements
  with no way to distinguish real fix effects from noise.

**The method, concretely:**

1. Take the full draft text for a knowledge component (`draft.contextual_kc_draft.text`) and its
   supporting evidence citations (`evidence_map` / `evidence_for_synthesis`, with `doc_id` +
   `page_index` + quoted text).
2. Fetch the actual corpus text at that `(doc_id, page_index)` from the blockstore
   (`data/processed/blockstore/<run_id>/<doc_id>/.../blocks.jsonl`) — not the pipeline's own
   extracted quote, the underlying PDF-derived block text directly.
3. Read both side by side and classify: does the draft's stated definition/procedure/relationship
   match what the source page actually says, on the specific KC's own topic (not an adjacent or
   superficially similar one)?
4. For every unit flagged as changed (regression, improvement, or new drift), repeat this for
   *both* the old and new state, not just one side — a unit that "looks the same" under a status
   check can still have swapped which specific evidence backs it.
5. Full-corpus passes (not sampling) were used whenever the claim was "N regressions, zero new
   ones elsewhere" — a sampled census cannot support a zero-new-regressions claim, only a
   probabilistic one.

An earlier attempt at semi-automated screening (heuristic keyword/sibling-name matching) was
explicitly tried and rejected mid-investigation: verified against a known contamination case
(`KC_EVAL_BASIC_006`'s F-measure conflation, §5) and confirmed it would have produced a false
negative — the wrong-branch evidence doesn't always share a distinctive keyword with the correct
topic, so keyword-based screening under-catches exactly the subtle cases that matter most.

## 2. Classification taxonomy

Every knowledge unit, per comparison, was placed into one of nine cells crossing
`{correct, wrong, abstained} × {correct, wrong, abstained}` (old state × new state):

| | new: correct | new: wrong | new: abstained |
|---|---|---|---|
| **old: correct** | Stable | **Regression** | **Regression** (lost coverage) |
| **old: wrong** | Genuine improvement | Stable (unresolved) | Arguable improvement |
| **old: abstained** | Genuine improvement | **Regression** (worse) | Stable |

`correct` / `wrong` are content judgments from §1, never taken from a pipeline field.
`abstained` means the draft is empty (`contextual_kc_draft.text == ""`) or, more subtly, drafts a
paragraph of hedge language without asserting a specific answer (see the hedge-pattern detector
in `review_priority.py` — e.g. "the provided evidence does not provide a formal definition of
what it means for two points to be density-connected" is textually non-empty but functionally an
abstention).

**Why `wrong → abstained` is classified as an improvement, not a lateral move:** a wrong-but-
confident draft actively misleads a downstream reader (student, tutor-evaluation harness, human
reviewer skimming quickly) with no signal that anything is amiss. An abstention is self-flagging
— it visibly asks for the evidence gap to be filled, either by better retrieval or a human
reviewer, rather than presenting fabricated content as settled. This is the same principle behind
`packet_support_state: weak_fallback`/`insufficient_support` existing as pipeline states at all,
and the same principle behind treating "inadequate evidence → abstain" as correct system
behavior (§4/§5) rather than a defect to be papered over with a lower admission bar. It does not
mean abstention is a *good* outcome in absolute terms — a `wrong → abstained` unit still needs
better evidence recall to reach `correct`, and is exactly the kind of unit the review-priority
signal (§5, `review_priority.py`) is built to surface.

## 3. Three contamination mechanisms and how branch-scoping addresses each

All three were found by tracing specific regression cases through the real evidence-composition
code (`src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py`,
`steps/step_06_7_kc_draft_generation/scripts/v2_chain/build_step67_v2_hierarchy_aware_synthesis_packets.py`)
rather than inferred from symptoms alone — each has a concrete before/after code diff and a
concrete confirmed test case.

**Mechanism A — risk-flag bypass.** `_review_needed_item_is_useful_for_synthesis()`'s
`hard_exclusion_risks` set didn't include `not_admitted_to_ordered_pack_for_drafting`, so an item
the upstream pack-composition stage had *already* decided not to use could still be pulled back
into a draft whenever `routing_recommendation == "positive_role_candidate"` — a short-circuit
that ignored the earlier, more specific rejection. Fix: added that flag (and, later,
`cross_branch_evidence_mismatch`) to the hard-exclusion set.

**Mechanism B — fragment mis-scoring.** `compose_pack_for_kc()`'s pack-composition step could
admit mis-scored fragments or headings as core evidence with zero risk flags at the point
`positive_candidates`/`ordered_pack` are constructed — earlier in the pipeline than the
`drafting_core_evidence`/`auxiliary_evidence` buckets, meaning a later-stage filter on those
buckets alone would be a no-op (confirmed by tracing a real candidate ID through
`ordered_pack_for_drafting`, which step6_7 reads *before* the later buckets). Fix: the
cross-branch check (§4) was placed at this earlier point, not just on the later buckets.

**Mechanism C — generic-token overlay binding.** `_overlay_row_has_target_binding()`'s fallback
lane matched candidates on generic 2-word token overlap (e.g. "handling"/"missing") whenever a
target KC's own aliases were empty, so its binding tokens fell back to a maximally generic
canonical-name fragment — with no branch-scoping at all. A real case: decision-tree missing-value
content bound to a Naive Bayes KC purely because both mention "missing values." Fix: the
cross-branch check runs as an independent rejection step inside
`select_target_bound_overlay_fallback_evidence()`, between the target-binding check and the
source-shape check.

**How branch-scoping (`src/kc_l/retrieval_gate/branch_scoping.py`) addresses all three:** rather
than patching each admission path with mechanism-specific logic, one shared check
(`check_cross_branch_mismatch()`) was wired into all three call sites. It works from an empirical
`(doc_id, page_index) → branch` map built from every KC's own confirmed core+auxiliary evidence
across the whole run (not any single candidate's own retrieving-KC label, which was confirmed to
always equal the target KC — zero independent signal). A candidate is flagged only when its local
page neighborhood (±15 pages, excluding its own page) has zero confirmed evidence from its own
target branch *and* at least one confirmed hit from a different branch — deliberately
conservative, so pages with no signal at all, or with legitimately mixed/transitional content,
are never flagged.

**Correction (2026-07-22):** the two call sites in `build_step67_v2_hierarchy_aware_synthesis_packets.py`
(the review-needed-promotion and overlay-fallback lanes) derived their branch key via
`row.get("topic_path_labels")` against a row schema (`candidate_sentence_overlay.jsonl`) that
never carries that field — confirmed 0/2862 rows. This silently no-opped the check at both sites
for every run since deployment, for any KC relying on those two lanes (`packet_evidence_source`
in `{weak_fallback, insufficient_support}`, ~25% of a run's units) — the step5x-level check
(described above) was and remains unaffected, since its own candidate schema genuinely has the
field. Fixed by reading `ancestor_labels` (present on 2592/2862 rows) with a
`source_hierarchy_path[:-1]` fallback (present on all rows). Verified via direct function calls
against real data before any rerun (22/46 previously-unprotected units showed real new
rejections, 109 candidates total) and again via a full pipeline rerun and 144-unit census after.

## 4. The granularity decision — methodology and result

The branch key that "same branch" is computed at started as a fixed 2-level hierarchy prefix
(e.g. `Data Mining > Clustering`). This was measured — not assumed — to be too coarse: across the
real 159-KC hierarchy, 2-level keys collapse into just **4 distinct branches total**, meaning the
check could catch contamination *between* e.g. Clustering and Classification but was structurally
blind to contamination *within* one of those 4 (the motivating case: Decision-Trees evidence
bleeding into a Naive-Bayes KC, both under "Classification").

**The empirical measurement.** Every KC's own evidence pool was re-scored under three candidate
branch-key definitions — the existing 2-level prefix, a 3-level prefix, and the KC's complete
`topic_path_labels` (its full ancestor path, untruncated) — and the resulting newly-flagged
candidates were hand-verified against the real corpus text (§1's method), not just counted:

| Granularity | Distinct branches | New flags (2-level → X) | Hand-verified in core/aux (changes real output) |
|---|---|---|---|
| 2-level (baseline) | 4 | — | — |
| 3-level | 18 | +250 | 39 (roughly half true positives, half false positives) |
| Full path (untruncated) | 23 | +356 | 47 |

**Why full path over a fixed integer depth.** The real hierarchy is not uniform: 129 of 159 KCs
are 3 levels deep, 30 are 4 levels deep (e.g. `Decision Trees > Overfitting and Pruning` is a
genuine sub-branch of `Decision Trees`). A KC's complete `topic_path_labels` (everything above
the KC's own leaf name) is *already* present in the data and is, by construction, exactly "share
the same immediate parent node" — the literal definition of tree siblinghood, with no depth
constant to choose or get wrong for a future hierarchy of a different shape. A fixed integer
(whether 2 or 3) is a **hardcoded assumption about hierarchy depth uniformity that this project's
own domain-agnostic principle already prohibits** — 3-level was measured to under-split the
30 KCs at depth 4 (grouping "Decision Trees" and "Decision Trees > Overfitting and Pruning"
together) while gaining nothing over full-path for the 129 KCs at depth 3 (where 3-level and
full-path are numerically identical). Full path was adopted specifically because it is the
correct general definition, not merely the empirically-best-scoring option among a set of
arbitrary integers.

**Why full path alone was not sufficient, and the guard that was added.** Hand-verification of
the 47 core/aux-affecting candidates found a real, non-hypothetical false-positive mode:
finer branch keys shrink each branch's within-document evidence footprint, so a genuinely
on-topic candidate can be flagged purely because *no other* KC in its exact sub-branch happens to
cite a page within the ±15-page window of *this specific document* — even though the branch does
have confirmed evidence elsewhere in that same document, just further away (concentrated
examples: a page titled "Manhattan Distance, Euclidean Distance, and Cosine Similarity" flagged
because no other Similarity-and-Distance KC cited a page within 15 of it in one particular
compact exercise-guide PDF; DBSCAN-specific evidence flagged on the same pattern in the primary
900-page textbook).

The fix is **document-scope corroboration**: before trusting a windowed "no same-branch signal
nearby" absence as a demotion signal, first check whether an *independent* KC (not the same KC's
own other candidates — keyed by `kc_id`, specifically so a KC's own repeated mis-scored
candidates can't corroborate each other into a false pass) has confirmed evidence for the same
branch *anywhere else* in the same document, not just within the window. Cross-branch
contamination signal itself stays window-scoped (local page proximity is what makes it evidence
of a *specific* misplaced page, not just "a different topic exists somewhere in this document").
This was validated against the same 47 hand-verified cases before shipping: it suppressed the
confirmed false positives (Similarity/Distance, DBSCAN) while preserving the confirmed true
positives (a "Hold-out / train-test split" evaluation-methodology passage wrongly admitted as
"Classification Underpinnings" core evidence; association-rule-mining language wrongly admitted
onto Class-Imbalance/ROC-Analysis KCs).

**The citable design contribution**, stated generally: for a check that reasons about "is this
piece of evidence from the right part of a hierarchy," the correct branch granularity is *the
hierarchy's own sibling structure*, not a chosen traversal depth — and a locality-based
corroboration signal (page windows, document proximity, or any similar proxy) needs a
document-scope fallback precisely because locality and topical correctness are correlated but not
identical, and the gap between them widens as the branch key gets more specific.

## 5. Known, honestly-stated limitations

**`KC_CLU_EVAL_012`, `KC_CLF_UND_002` — retrieval gaps, not resolver defects.** Both regressed
from correct to abstained and remain abstained after this session's fixes. Neither is caused by
cross-branch contamination or the docling page-index bug — direct evidence tracing found no
related candidates in either unit's evidence pool at all; the retrieval stage simply isn't
surfacing content for them under the current run. Out of scope for the branch-scoping/docling
work; would need separate retrieval-recall investigation.

**`KC_DE_PREP_004` — a real, confirmed false-positive from the branch-scoping guard.** "Data can
contain inconsistent values" is legitimate, on-topic evidence for "Preparing the Data for
Learning," demoted only because no other confirmed KC in that exact branch happens to cite
anything within the window of the specific (large, single-book) document it came from, and the
document-scope guard (§4) — checked and confirmed via the real `cross_branch_evidence_detail`
payload — didn't have independent corroboration to fall back on for this specific branch/document
pair either. This is the residual edge of the same false-positive mode the guard was built to
reduce, not eliminate: a branch whose *entire* evidence footprint in a given document is thin
enough that even document-scope corroboration finds nothing to lean on. A future hardening could
widen corroboration to the whole corpus (not just the same document) at the cost of a weaker
locality signal — not attempted this session because it changes the check's fundamental
selectivity and deserves its own empirical validation pass, not a reactive patch.

**`KC_EVAL_BASIC_006` ("F-Measure") — confirmed still wrong.** Direct verification (2026-07-22):
its core evidence is a single MinerU-sourced sentence, correctly page-indexed (no docling bug
involved), with a real, non-tied score — "The F-measure and hierarchical F-measure discussed
earlier, are examples of how to evaluate such a match," which is actually about *clustering*
F-measure, not the *classifier* F-measure this KC is about. The branch-scoping guard does not
catch it, and the reason is structural rather than a bug: within ±15 pages of this candidate's
own page, another confirmed "Classifier Evaluation Basics" KC (`KC_EVAL_BASIC_002`) genuinely
does have evidence nearby, so the target branch's own presence is correctly confirmed locally —
the check has no way to know that *this one sentence*, despite sitting in a page neighborhood
that is legitimately about classifier evaluation, is itself referencing the *other* sense of a
term ("F-measure") shared between two unrelated branches. This is a term-polysemy problem, not a
page-locality problem, and no page-locality-based signal can resolve it. It is also, by design,
not flagged by the review-priority signal (`review_priority.py`) at its default threshold: the
unit's `packet_support_state` is `draftable` (normal confidence), its evidence score margin is
wide (not a near-tie), and it only picks up one minor rare-flag contribution
(`variant_only_support`, +12 of the 30-point threshold) — an honest reflection of the fact that
every *structural* evidence-quality signal available genuinely looks fine here. Contrast with
`KC_CLU_HIER_003` (a comparable prior bug, now resolved as a side effect of the docling
tie-break fix, §Part-1-of-this-session's-verification): it is *still* flagged by the
review-priority signal today (`packet_support_state:weak_fallback` +
`narrow_evidence_score_margin`), because its resolution came through a fragile, low-confidence
evidence path even though the resulting content happens to be correct — precisely the
"confidence, not correctness" signal this system is designed to surface, and precisely why
`KC_EVAL_BASIC_006` — genuinely wrong, but arrived at through a normal-confidence path — is the
clearest illustration of this methodology's ceiling: **evidence-quality signals can flag "this
was decided under uncertainty," never "this is factually wrong."** That determination remains,
irreducibly, a human reviewer's job — which is the entire reason the content-verified census
method in §1 exists, and why it cannot be fully automated away by any signal in `review_priority.py`.

**`KC_CLU_KM_004` ("Centroid Initialization Sensitivity") — a topically-correct draft built on
zero admissible grounding evidence.** Once the field-name fix above started genuinely rejecting
this unit's contaminating candidates (a Self-Organizing-Map update formula and a Fuzzy-C-Means
membership formula — real clustering content, but about different algorithms than K-Means
initialization sensitivity), the unit was left with `embedded_ordered_pack_items: 0` and no
overlay-fallback evidence either, and correctly abstained. Its *previous* draft, however — "While
standard K-Means is sensitive to these starting positions, Bisecting K-Means is less susceptible
... because it performs several trial bisections and selects the one with the lowest SSE" — was
independently verified as accurate, specific, and correct. With the contaminating candidates now
known to be off-topic and nothing else admissible, that draft could not have been genuinely
evidence-grounded synthesis. The most likely explanation is that the drafting model filled the gap
from its own pretrained knowledge of a well-known textbook concept, producing content that reads
as correct without being traceable to the corpus. **This is a real, disclosed failure mode, not
one the content-verified census method (§1) claims to eliminate**: census verification checks
whether draft content matches the *real corpus* at its cited page — a draft that is factually
correct but ungrounded still passes that check, because the check only fails content that is
*wrong*, not content that is right for the wrong reason. Catching this specific failure mode would
require a distinct, additional check (e.g. flagging drafts with substantive text but zero admitted
evidence citations) rather than an extension of either the content-verification method or the
branch-scoping guard, and is not implemented as of this writing.

## 6. Retrieval-gap investigation (2026-07-22/23): Mechanisms A and B

Beyond evidence-quality signaling, a second class of gap was investigated: units where the
*correct* corpus content was never assembled as a candidate at all, so no downstream check
(branch-scoping, review-priority, or otherwise) had anything to evaluate in the first place.

**The unified root cause.** Two symptom patterns were investigated separately (Mechanism A:
zero relevant candidates, falls back to generic branch filler; Mechanism B: some real candidates,
but from a different, wrong-subtopic passage) and found to be the same underlying failure:
`retrieval_profile/builder.py`'s primary candidate scout is a deterministic lexical/token search
seeded only from the KC's own `canonical_name` (plus any registered aliases, which were empty for
every affected unit). When the corpus's real vocabulary for that concept diverges from the
canonical name - either completely (`KC_CLF_UND_002` "Querying Phase" vs. the textbook's own
"deduction", confirmed zero occurrences of "querying" anywhere in the corpus) or partially (a
compound canonical name like `"External Index: Precision"` where the shared "External Index"
fragment pulls candidates toward a different, real subsection that never mentions "precision")
- the search fails, and for Mechanism B specifically the correct passage was confirmed to never
enter the candidate pool at all (checked directly: none of `KC_CLU_EVAL_011`'s 7 scouted
candidates were within 200+ pages of its real answer), so this was never a fair scoring contest
between real candidates - the "winning" candidate was simply the only one ever offered.

**A related, already-existing but dead diagnostic.** `_detect_source_sparse_label_mismatch()`
already computed almost exactly the needed detection signal, but `role_target_contract.py`
consumed it via `if source_sparse_label_mismatch:` - dict truthiness, not the inner boolean
field, which is always-true regardless of the actual mismatch state (the function always returns
a non-empty dict). Confirmed 159/159 KCs in a real run showed the resulting rescue_hint firing
unconditionally, and the diagnostic's actual value never reached the serialized profile output at
all. Fixed 2026-07-23 (`role_target_contract.py`): reads the inner boolean correctly, and the full
audit dict is now surfaced as its own field (`source_sparse_label_mismatch_audit`) so it is
directly inspectable rather than only inferable from whether a hint fired.

**The fix: sibling-confirmed-page anchoring, not vocabulary guessing.** A vocabulary-inference
approach (deriving alternate terms from sibling/parent hierarchy context) was considered and
rejected: it requires some similarity judgment (lexical or LLM-based), and both reintroduce a
version of the same problem one level up, or violate the deterministic-first principle. Instead,
`_sibling_confirmed_anchor_scout_windows()` (new, `retrieval_profile/builder.py`) reuses a fact
already known for certain: the empirical `page_branch_map` built for branch-scoping (§3/§4)
already records which pages *other* KCs in this exact branch (full `topic_path_labels`, same
zero-constant convention as branch-scoping) have confirmed evidence on. When the primary
label/topic search finds nothing (the same "surface retrieval starvation" branch that used to
fall through to generic `sibling_context_scout` filler alone), this scout searches near those
confirmed sibling pages instead - never guessing new vocabulary, only reusing confirmed structural
fact. Both lanes are kept (additive, not replacing): a KC that is the only member of its branch
has no sibling anchors to draw on and still needs the generic fallback.

**The window was measured, not assumed** (same discipline as the 2-level vs. full-path
granularity decision, §4). Anchoring on the *current* (broken) generic-scout candidates would have
required 68-231 pages of radius to reach the correct answer for the confirmed real cases - far too
wide to be safe. Anchoring on sibling KCs' own *confirmed* evidence pages instead required 0-2
pages for `KC_CLF_UND_002` and `KC_FSEL_FW_004`, 0 pages (for one of two real occurrences) for
`KC_CLF_DT_009`, and 25 pages for the widest confirmed case (`KC_CLU_EVAL_011`/`012`/`013`,
anchored via sibling `KC_CLU_EVAL_008`). `SIBLING_ANCHOR_WINDOW = 25` was set from that measured
ceiling, not a round number.

**A real implementation bug found and fixed during direct testing, before any pipeline rerun.**
The first version of this scout took a naive top-N by (distance, score), which let whichever
anchor page happened to sort first in file order monopolize the entire candidate budget - directly
confirmed: `KC_CLF_UND_002`'s real answer (page 144, anchored by sibling `KC_CLF_UND_001`) was
silently squeezed out entirely by two unrelated siblings' pages that simply came first in the
source-row scan, in a branch with many sibling KCs. Fixed with a per-anchor-page cap (same
diversification principle as `_topic_local_content_scout_windows`'s existing `per_patch_cap`),
re-verified directly afterward that page 144 is present in the candidate pool.

**A second, separate bug found in passing:** the `page_branch_map.json` on disk was stale (last
built 2026-07-21, before subsequent evidence-pack updates) - confirmed directly: it was missing
`KC_CLF_UND_001`'s own page-144 anchor, which does exist in the current evidence. Rebuilt from the
latest verified evidence packs before this fix could be tested meaningfully. This map should be
refreshed whenever evidence packs change; it is not automatically regenerated as part of a normal
run today.

### Confirmed genuine corpus insufficiency (closed, not pursued further)

Three units were investigated and confirmed to have **no real corresponding content anywhere in
the corpus** - not a retrieval defect, a vocabulary gap, or a scoring artifact. No radius, no
vocabulary-matching improvement, and no scoring change can fix these; they would need new source
material, which is out of scope for this pipeline.

- **`KC_EVAL_COMP_001` ("McNemar Test")** - zero occurrences of "McNemar" anywhere in the corpus.
  The general statistical machinery it depends on (contingency tables) is present (34 occurrences)
  but clustered entirely around Association Rule Mining and the External-Index statistical-testing
  section - never in the Model Comparison chapter, and never applied to paired classifier
  comparison anywhere.
- **`KC_EVAL_COMP_004` ("Friedman Test")** - every occurrence of "Friedman" in the corpus is a
  bibliography citation (Jerome H. Friedman, co-author of a cited textbook on statistical
  learning), not a topical reference to the Friedman statistical test.
- **`KC_EVAL_COMP_005` ("Nemenyi Test")** - zero occurrences anywhere, and no post-hoc pairwise
  comparison procedure is discussed under any name near the Friedman-test-adjacent content that
  does not itself exist either.

These three should be treated as confirmed, permanent gaps unless and until the source corpus
itself is expanded - a documentation/scoping decision, not a pipeline defect.

## 7. Widen-fallback investigation (2026-07-28): attempted, reverted, four confirmed failure modes

A follow-on to §6's retrieval-gap work was attempted for the 33 KCs whose canonical name
contributes ≤1 real corpus content token and carry no aliases (the same generic-name/empty-alias
population as §6): drop the topic/label/branch anchor requirement in
`_topic_local_content_scout_windows()` for exactly this narrow trigger condition
(`label_anchored_window_count <= 1`), replacing it with a domain-agnostic structural bar (a
recognized evidence shape - definition/mechanism/formula/process - from the same
`evidence_shape_for_text()` used elsewhere), while keeping every existing safety filter
(heading-only/unsafe/bibliographic/prompt-like exclusion). The intent was to let the LLM
cue-acceptance step judge genuinely unconstrained candidate content only in the narrow case where
anchor-based filtering had nothing real left to filter *for*. A full corpus-wide A/B run (all 159
KCs, `--use-model` on, real LLM classification) was executed to verify it before shipping. It did
not pass, and was reverted in full (confirmed zero trace against the pre-attempt backup). Four
independent failure modes were found, each real, each worth recording:

**Failure mode 1 - the alias field never reaches the retrieval stage at all, regardless of what
the hierarchy source file says.** Investigating why a hand-restored alias
(`KC_CLF_DT_009`'s "information gain"/"difference in entropy", historically real per §6's own
sibling-anchor work) still showed as `aliases: []` in step_05p's output traced to a structural gap
independent of tonight's changes: `aliases` survives the first normalization pass
(`01_hierarchy_normalize.py` → `kc_registry.jsonl`, confirmed present there) but is silently
dropped by `run_step01_5_hierarchy_overlay.py` when building `hierarchy_overlay.jsonl` - the file
`step_05p`'s `registry_jsonl` and `step_05x`'s `registry_jsonl` both actually read. Checked
directly against the *baseline* production run (`20260727T022835Z_9e856df6`, unrelated to
tonight's code): `KC_CLU_EVAL_004`'s own SSB alias, applied and reported as "verified end-to-end"
in an earlier session, shows the same `aliases: []` there too - it was working via
`_sibling_confirmed_anchor_scout_windows()` (§6) independently finding real "SSB"/separation
content through branch proximity, not through the alias, which never reached the pipeline. This
means every alias-based fix attempted across multiple sessions - not just tonight's - has had zero
effect on the real production pipeline. It is a pre-existing, previously-undiagnosed schema gap,
not something this session's changes caused, but this session is what surfaced it. Not fixed as of
this writing; out of scope for the widen-fallback attempt itself.

**Failure mode 2 - the new fallback's own candidate windows never reached the LLM in any tested
case.** The widened windows were appended after `_sibling_confirmed_anchor_scout_windows()`'s
output in the combined candidate list (`sibling_anchor + widened + narrow_topic_local`), and that
function - existing, unmodified, documented in §6 - fills its own full 20-window budget whenever
it activates. Confirmed directly from the real run's `source_window_supplier` audit: all 5 KCs
where the new fallback's activation condition fired
(`KC_CLF_UND_002`, `KC_CLF_DT_009`, `KC_EVAL_COMP_001`, `KC_EVAL_COMP_004`, `KC_EVAL_COMP_005`)
also showed `sibling_confirmed_branch_anchor_scout: 20` windows, which `_enforce_profile_window_budget`'s
list-order truncation admits first, leaving zero of the budget for the widened pass. The mechanism
was implemented, deployed, and exercised by a real 159-KC LLM run, but never actually tested on its
own merits - the observed outcomes below are attributable to a different, pre-existing mechanism.

**Failure mode 3 - a real, confirmed new false positive, caused by a necessary side fix, not by
the widen mechanism itself.** Computing `label_anchored_window_count` correctly required aligning
`_TOPIC_LOCAL_GENERIC_TOKENS` with `deterministic.py`'s `GENERIC_SUFFIX_TOKENS` (it was missing
`test`/`index`/`score`/etc., letting e.g. "McNemar **Test**" register a false anchor on the word
"test" alone in ~20/20 candidate windows, masking the real zero-anchor signature this whole
investigation depends on). That fix is correct and needed. Its side effect: it newly activates
`sibling_confirmed_branch_anchor_scout` for `KC_EVAL_COMP_001`/`004`/`005`, which never triggered
it before (the old, buggy anchor count was always >1 for them). For Friedman and Nemenyi the newly
surfaced sibling content was correctly rejected by the LLM (0 accepted cues, matching §6's
confirmed corpus-insufficiency finding for both - no fix can invent content that was never
written). For McNemar it was not: the LLM accepted 2 cues, including the formula
`Z = (p_A - p_B) / sqrt(2*p̄*(1-p̄)/N)`, sourced from a real passage (`DOC_Guides_merged`, page 78,
"Question 3: Wins, draws, losses, and significance comparison") that never uses the word
"McNemar." This is the two-proportion Z-test, not McNemar's test (which uses the discordant-pair
form `Z = (b-c)/sqrt(b+c)`) - a genuine, confirmed semantic misattribution: a draft built from this
would state the wrong formula under the McNemar name. Matches this project's own standing bar
exactly ("topically wrong, not just topically thin") and was the proximate trigger for reverting.

**Failure mode 4 - the blast radius extended well beyond the 5 directly-affected KCs.** A full
`step_05x` evidence-admission diff (candidate_bank → scored_candidates, all 159 KCs, both runs)
found 33 additional KCs - none targeted by tonight's change, none sharing the generic-name/
empty-alias signature - with real `risk_flags` or `admission` differences. Root cause: flags like
`recurring_global_candidate` and `sibling_competitor_dominant` are computed from *global,
cross-KC* candidate bookkeeping, so changing the candidate set for 5 KCs shifted which KC "owns" a
shared recurring text block corpus-wide. Most were flag-only churn, but at least two moved in the
risky direction on KCs never intended to be touched: `KC_CLU_EVAL_009` (`review → ordered_evidence`
on one candidate) and `KC_EVAL_COMP_008` (`reject → review` on two). Confirms that this pipeline's
evidence-admission layer is more globally coupled across KCs than a locally-scoped fix's own
verification plan accounted for - any future retrieval-cascade change needs a full-corpus A/B
pass as a baseline requirement, not an targeted-subset one, which is exactly what caught this
before it shipped.

**Disposition.** Reverted in full (`src/kc_l/retrieval_profile/builder.py` restored from its
pre-attempt backup, confirmed byte-identical and zero remaining references anywhere in the
codebase). `KC_CLF_DT_009`'s alias restoration was kept in the hierarchy source file - harmless
per failure mode 1 above, and historically justified independent of this attempt - but is not
expected to have any effect on retrieval until the overlay schema gap is separately fixed. The
WARN-flagged validator limitation from §6 (generic canonical name, no real corpus anchor) stands
undisturbed as the honest, correct current state for `KC_CLF_UND_002`/`004`/`005` and the rest of
the 33-KC population: real, but currently unresolved without either (a) fixing the alias-overlay
gap so hand-authored aliases can actually reach retrieval, or (b) a redesigned widen mechanism
that does not compete with `_sibling_confirmed_anchor_scout_windows()` for candidate-pool budget
and is re-verified with the same full-corpus discipline that caught this attempt's problems.
