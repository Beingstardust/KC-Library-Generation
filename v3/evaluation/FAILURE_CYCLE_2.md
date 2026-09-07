# Failure Cycle 2 — Persisting, New, and Resolved

Internal working record. Covers the second human review of the KC v3 pipeline's output and
everything done in response to it: two new failure mechanisms diagnosed and fixed, a cross-check
against the first review's 51-item register, a real bug found in the previously-shipped v25 fix,
one previously-shipped-but-broken regex found and fixed, one parameter tested and deliberately
left unchanged, and the grounded/partial/abstained status contract rewritten.

Companion to `v3/evaluation/failure_register.jsonl` (run 1, 51 problems) and
`docs/v3/KC_V3_FAILURE_ANATOMY.html` (the published run-1 report). This document does not
duplicate run 1's content — only what changed.

---

## 0. Where the numbers came from

Two independent human reviews of two different draft generations, same 159 units, same
source-only standard (style/length/verbosity never penalized; only content-wrong, mismapped,
contaminated, or too-incomplete-to-function counted as failure):

| Run | Draft generation | Attempted-acceptable | Overall successful |
|---|---|---|---|
| Original (pre-v22) | pre-block-splicing-fix baseline | 114/149 = **76.5%** | 120/159 = **75.5%** |
| Run 1 (post-v22/v23) | member-verification shipped, later found regressed | 102/150 = **68.0%** | 108/159 = **67.9%** |
| Run 2 (post-v24-v28, pre-v25-bugfix) | this cycle's starting point | 103/149 = **69.1%** | 109/159 = **68.6%** |

Run 2 is the draft this whole cycle diagnoses. It was built from packets carrying v24 (math
variant selection), v26 (competitive assignment against library rivals), v27 (built, rejected,
deleted before this draft was cut), and v28 (no-fabrication contract) — but **not** a working v25
(promised-formula admission was live in code but silently defeated by a separate re-verification
pass, discovered mid-cycle; see §3) and **not** v29/v30/v31/v32 (didn't exist yet).

So run 2's 68.6% is a lower bound on what v24-v28 alone deliver, understating v25's intended
contribution specifically. That gap is closed by the fixes in this document; the real number comes
from the next draft, built with all of v24-v32 live.

---

## 1. Cross-reference: run 1 (51 problems) vs run 2 (50 problems)

By `canonical_name` (row numbers differ between runs; packet content changed). Full data in
`v3/evaluation/build_register_v2.py` / `failure_register_run2.jsonl` / `resolved_since_run1.jsonl`.

### Resolved (flagged in run 1, absent from run 2): 3

| Unit | What changed |
|---|---|
| Cost-Sensitive Classification | Reviewer: "now clearly states... the objective is to identify the lowest expected-cost choice... crossed the line from too thin to sufficient." |
| DBSCAN Parameters (eps, minPts) | v26 competitive assignment stripped the SNN-similarity contamination; reviewer confirms "the SNN contamination is gone." |
| Euclidean Distance | Formula and the Bregman-divergence misattribution both gone. |

All three land exactly on units this session's own fix-tracking predicted would improve (v26 for
DBSCAN Parameters; some combination of v24's variant selection and the general precision gains for
Euclidean Distance, ahead of v29's dedicated truncation fix). Independent confirmation that the
mechanism-level diagnosis this project has been doing tracks real reviewer judgement, not just
internal metrics.

### Persisting (flagged in both): 48

The overwhelming majority. See §5 for the open-issue taxonomy — most of these are diagnosed and
deliberately not chased this cycle, for stated reasons.

### New (run 2 only): 2

Both diagnosed against the real corpus and fixed this cycle (§2).

---

## 2. The two new failures, diagnosed and fixed

### 2a. Agglomerative Clustering — bibliography-title contamination

Evidence asserted *"clustering method for very large databases."* as if it described the KC. Real
source: the tail of a reference-list title, **"BIRCH: an efficient data clustering method for very
large databases."** pymupdf's line-based PDF chunking shattered this citation across five
separate one-line blocks:

```
1036:17  "[620] T."  "Zhang, R." "Ramakrishnan, and M." "Livny." "BIRCH:" "an efficient data"
1036:18  "clustering method for very large databases." "In Proc." "of 1996 ACM-"
```

No individual fragment carries enough of the year/venue/page markers for the existing per-sentence
`is_bibliography_entry()` check to catch — the year (1996) and venue marker ("In Proc.") are split
across blocks from the identifying content (author names, "BIRCH:", "[620]").

**Fix (v30):** before relevance filtering decides what to keep, join a candidate block's RAW,
UNFILTERED membership and test the WHOLE thing for bibliography/citation shape. A citation
shattered across a block boundary is still a citation regardless of which single fragment happens
to score well against the query.

**Bonus find while debugging it:** even the joined text didn't trigger the check at first. Root
cause was a **pre-existing bug**, not something introduced this session: `_VENUE_RE` wrapped its
whole alternation in `\b...\b`, and the `proc(?:\.|eedings)` branch's trailing `\b` can never
succeed when it matches on the period in "Proc." — a period isn't a word character, and neither is
the whitespace that follows it in every real citation, so the boundary check fails against the
single most common venue phrasing in the corpus. Confirmed directly:
`_VENUE_RE.search("In Proc. of 1996 ACM-")` returned `None` before the fix. Fixed by moving the
trailing `\b` to only the branches that end on an actual word character.

Verified end-to-end against the real corpus block: 0 passages admitted, vs 1 before the fix.
Regression guard: ordinary content with a bracket citation (`"...within a node of the tree [3]."`)
still admits normally.

### 2b. Feature Selection Definition — clause-truncation reversal

Evidence asserted *"feature selection is performed outside cross-validation"* as though it were a
recommendation. Real source (Ambroise et al., cited in the textbook): the opposite — a warning
about the **selection bias that arises when** this is done. pymupdf splits the full sentence across
three one-line blocks; the final subordinate clause survives alone as its own "sentence." mineru
and docling both keep the complete sentence intact.

The reviewer flagged this as the most diagnostically important failure in the run: not an ordinary
hallucination, but a source-valid STRING given a source-INVALID interpretation purely by losing the
clause that supplied its meaning.

**Fix (v31):** `build_document_long_sentences()` indexes, once per corpus load, every sentence per
document long enough (60+ chars) and capital-starting enough to be a genuine, complete sentence.
`is_severed_fragment()` flags a candidate only when (a) it starts with a lowercase letter — close
to unambiguous evidence of a PDF line-break artifact, independent of content — AND (b) it is a
literal substring of one of those longer sentences in the SAME document. A lowercase-starting
sentence with no fuller counterpart anywhere is left alone; a normal capital-starting sentence is
never flagged regardless of what it says.

Checked against the block's SEED sentence specifically, not the joined block text — the real
failing block also carries an unrelated trailing member (the start of the *next* sentence), which
broke a joined-text substring match on the first implementation attempt even though the seed alone
is unambiguously the fragment. Caught by testing against the real block before shipping, not
assumed.

Measured cost on the real 100k-sentence corpus: 0.1s to build the per-document index, 4ms to check
the real failing case. Cheap enough that it runs unconditionally, not as an opt-in.

---

## 3. A real bug found in an already-shipped, already-"verified" fix

Prompted by the instruction to evaluate packet quality against the historical runs, not just trust
that a mechanism verified in isolation was doing its job in the real pipeline.

**Symptom:** Sample Mean and Variance's real evidence still contained the bare lead-in sentences
("...then the sample mean is", "and the sample variance is") with no formula following either —
exactly the v25 bug pattern, despite v25 being shipped and its isolated test passing.

**Trace:** built the real corpus's full block-successor index and confirmed the lookup was correct
— `mineru:38:705` ("...then the sample mean is") resolves to `mineru:38:706`
(`$$\mu_j=\bar z=\frac{1}{n}\sum z_r$$`), and `is_formula_payload` returns `True`. Instrumented the
real single-unit packet build with temporary debug prints and confirmed **both** formulas
(mean and variance) were being admitted into `best` — "ADMITTING PAYLOAD" fired for both. So the
mechanism worked, and the formula still didn't survive to the final packet.

**Root cause:** a *second*, separate mechanism inside `assemble_passages()` — the original v13
splice-detection pass (`verify_scorer`) — re-scores every passage's ASSEMBLED TEXT against the
query after block assembly and drops anything below the floor. A bare formula scores low against a
name-shaped query when judged alone (the exact problem the defining-equation floor exists to
correct for *ordinary* admission), but v25's payload passages never went through ordinary
admission and so never inherited that floor's exemption. `verify_scorer` re-scored the formula,
found it low, and silently reversed the admission `assemble_passages` had just made deliberately —
defeating the entire point of v25 the first time it ran for real.

**Why my own verification missed it:** the original v25 test called `assemble_passages()` with
only `member_verifier` set, never `verify_scorer` — the real caller in `02_build_kc_packets.py`
always supplies both. I verified the mechanism I built without exercising the mechanism it
collides with. This is precisely the failure mode this project's fix-liveness discipline exists to
catch, and would have caught it immediately had the original test exercised both re-checks.

**Fix:** `lead_in_payload` passages are now exempt from `verify_scorer` re-checking entirely, the
same way they were already exempt from `member_verifier`. Their admission is already justified by
their pointer, which was independently verified when *it* was admitted — the payload doesn't
re-litigate that judgement, it fulfils it.

**Harness strengthened accordingly:** the v25 check now supplies a hostile `verify_scorer` alongside
the existing hostile `member_verifier`, so a regression of this specific shape fails loudly instead
of passing silently the way the original, narrower test did.

Confirmed against the real corpus post-fix: both formulas present, `admission_basis` correctly
recorded as `lead_in_payload` (nested under `support_profile_summary`, not top-level — a second,
much smaller confusion during debugging that turned out to be my own inspection script reading the
wrong field path, not a code defect).

---

## 4. Status rubric: grounded / partial / abstained, standardized

**The problem, in the reviewer's own numbers:**

| | Run 1 | Run 2 |
|---|---|---|
| Grounded precision | 84.1% | 84.5% |
| Partial → actually needs revision | 81.1% | 65.2% |
| Abstention precision | 66.7% | 60.0% |

Grounded calibration barely moved. Partial calibration moved substantially — not because drafts
got better, but because the model grew more cautious about labelling complete output "grounded"
without any change in what completeness meant. A reviewer using `partial` as a triage signal would
have caught 81% of what needed fixing in run 1 and only 65% in run 2, for no real quality reason.

**Root cause:** the entire prior specification of the field was one circular line —
*"If evidence is partial, mark status as partial and explain the uncertainty."* No fixed criterion
existed for the model to calibrate against.

**Fix (v32):** replaced with a three-step, ordered decision procedure tied to the completeness
checklist the drafting contract already enforces elsewhere (shape_tags: a `formula` tag means the
formula must be written out, a `procedure` tag means the steps must be stated):

1. Evidence supports nothing for THIS unit specifically → `abstained` (already covered above in
   the prompt; this step just confirms the ordering).
2. Draft states EVERY element the evidence itself supports, every claim evidence-linked →
   `grounded`, **regardless of length**. A two-sentence draft from two sentences of evidence is
   grounded if it omits nothing those two sentences offered. Explicitly: *"Thin evidence,
   faithfully and completely used, is grounded, not partial."*
3. `partial` ONLY when a specific, nameable gap exists — a formula that couldn't be cleanly
   reconstructed, steps given incompletely, a genuine source ambiguity — and `uncertainty_notes`
   must name it exactly. *"The evidence is thin" is never by itself a reason for partial.*

Applied to `v3/pipeline/04_draft_runner.py` only (the live v3 driver) — the frozen legacy copy
(`scripts/experimental/run_step67_v2_tiny_smoke.py`) is deliberately left untouched per this
session's own earlier reorganization decision to keep the old chain working unmodified.

---

## 5. Tested and deliberately NOT changed: v26's CLAIM_MARGIN

Two persisting failures (Core Point / SNN, External Index: Entropy) have real library rivals
(Border Point, Noise Point; five entropy-adjacent units respectively) but don't lose their
wrong-sense passages at the current margin (0.08). Before touching the constant, swept it against
the real reranker on the real packets:

| Margin | Core Point dropped | External Entropy dropped | Accepted units damaged |
|---|---|---|---|
| 0.08 (shipped) | 0 | 0 | 0 |
| 0.05 | 0 | 3 | **4** (Noise Point, K-Means Algorithm, Information Gain, DBSCAN Cluster Definition) |
| 0.03 | 3 | 4 | 4+, worse |

**Decisive: collateral damage on accepted units appears before Core Point gets any help at all.**
At 0.05, four good units are already losing evidence while Core Point is still at zero. There is no
margin value where this trade favours making the change. `CLAIM_MARGIN` stays at 0.08 — a tested
and rejected tuning, not an unexamined default. Documented here so a future session doesn't
re-discover the same dead end.

---

## 6. Cluster 3 / cluster 4 re-measured against their ACTUAL original membership

The run-1 report deferred two clusters explicitly: "re-measure after 1 & 2" (cluster 3, drafting
omission, 16 units) and "probe first" (cluster 4, under-retrieval, 12 units), on the hypothesis
that fixing the input-side clusters (wrong-sense admission, formula-payload loss) would indirectly
shrink these by giving the drafter cleaner material to work from.

Direct re-measurement (`v3/evaluation/remeasure_clusters_3_4.py`), matching run 2's findings back
against the ORIGINAL cluster membership by `canonical_name` — not a fresh loose re-bucketing under
similarly-named tags, which would beg the question:

| Cluster | Original size | Still failing in run 2 | Resolved |
|---|---|---|---|
| 3 (drafting omission) | 16 | **15** | 1 (Cost-Sensitive Classification) |
| 4 (under-retrieval) | 12 | **12** | 0 |

The hypothesis was wrong. Cluster 4 did not move at all, because nothing input-side touches it —
its failures are retrieval-recall problems in a completely different part of the mechanism space
from what v24-v28 fixed. Cluster 3 barely moved, and its one resolution is better attributed to
v28's drafting-contract tightening than to cleaner input. Both clusters needed their own dedicated
work, which is §7-§10 below.

## 6a. Investigated: does competitive assignment (v26) wrongly strip evidence legitimately shared
## between two KCs?

Raised directly: a passage could genuinely support two different units (the example given was
"Recall" appearing under both a classifier-evaluation sense and an external-cluster-index sense).
If v26 treats admission as exclusive-assignment, it could be stripping evidence a "losing" unit
still legitimately needs.

Checked directly against every drop v26 has actually made on the real packets
(`evidence_dropped_to_rival_units`, recorded on every packet): 38 drops across 23 units. Sorted by
the LOSING unit's own score, the maximum was 0.642, and every single drop sat within 0.02–0.15 of
the 0.55 admission floor — v26 has never, in practice, stripped a passage that scored confidently
for its own unit. The two library units that instantiate the exact hypothetical raised (External
Index: Recall and Recall (Sensitivity), both real, separate KCs) appear in zero drop records
between them — v26 hasn't touched either. The mechanism is sound as specified; External Index:
Recall's real problem, confirmed in §7 below, is that its correct formula is never admitted with
enough score to reach v26 at all, which is a different failure entirely.

---

## 7. Cluster 4, diagnosed unit by unit against the real retrieval pipeline

`v3/evaluation/diagnose_cluster4.py` replicates the real BM25 + dense + reranker pipeline for every
cluster-4 unit and reports, per unit: is the correct content in the candidate pool at all
(`NEVER_CANDIDATE`), is it pooled but ranked low (`BELOW_FLOOR`), or does it already clear
admission (`ADMITTED`, meaning the failure is downstream — drafting or a still-present precision
problem, not recall).

| Unit | Result | What was found |
|---|---|---|
| External Index: Precision | BELOW_FLOOR, rank 116/405, **0.515** | `precision(i,j)=pij.` — exact correct formula |
| External Index: Recall | BELOW_FLOOR, rank 55/404, **0.521** | `recall(i,j)=mij/mj, mj` — exact correct formula |
| External Index: Purity | ADMITTED, rank 21/386, 0.584 | `m purity(i).` — right concept, garbled rendering |
| RIPPER Rule Induction | **ADMITTED**, rank 33/408, 0.589 | `RIPPER uses the sequential covering algorithm to extract rules directly from data.` |
| Cosine Similarity | ADMITTED, rank 13/400, 0.730 | correct dot-product/norm content DOES get admitted (the Bregman misattribution is separate, co-existing evidence — a precision problem, not recall) |
| Centroid Initialization Sensitivity | ADMITTED, rank 3/431, 0.650 | `of initial centroids.` — lowercase-starting fragment, candidate for v31 automatically |
| Evaluation Workflow | ADMITTED, rank 13/410, 0.558 | `Evaluation protocols hold-out, cross-validation, bootstrap` |
| NB Learning Phase | BELOW_FLOOR (alt form), rank 35/405, 0.534 | adjacent content close to floor |
| Querying Phase | BELOW_FLOOR, rank 16/88, 0.515 | best candidate is a rhetorical question, not a definition — looks like genuine corpus scarcity for this framing |
| Splitting Continuous Attributes | ~~NEVER_CANDIDATE~~ **ADMITTED**, rank 0/408, **0.731** | corrected below — `"Splitting continuous attributes."`, the section heading itself |
| Cost Matrix | ~~NEVER_CANDIDATE~~ **ADMITTED**, rank 0/406, **0.729** | corrected below — `"and the cost matrix:"` |

Five findings changed the diagnosis, two of them corrections to this very diagnostic:

- **RIPPER is not primarily a retrieval problem.** The reviewer's exact ask — the sequential-
  covering mechanism — IS admitted, at rank 33/408. The failure is either a `max_passages` budget
  problem (competing against 32 higher-ranked candidates) or the drafter had it and didn't
  synthesize it. Reclassified; not a cluster-4 retrieval fix candidate after all.
- **Cosine Similarity's problem is precision, not recall** — confirmed, matches the existing
  OPEN_NO_RIVAL diagnosis (Bregman divergence is not a library unit; v26 has nothing to strip it
  to). No new information, just direct confirmation.
- **Centroid Initialization Sensitivity's fragment will be checked by v31 automatically** once the
  corrected packets build — `"of initial centroids."` starts lowercase, which is exactly what v31
  tests for a fuller counterpart elsewhere in the document. No new code needed; whether it actually
  gets rescued depends on whether such a sentence exists, which the rebuild will answer for free.
- **Evaluation Workflow is the same shape as RIPPER, missed the first time round.** Its own row in
  the table above already read ADMITTED at 0.558 — above the 0.55 floor — but it was left inside
  the OPEN_RETRIEVAL bucket in §18's first draft anyway, an oversight caught on a second pass, not
  a new finding. Reclassified alongside RIPPER: not a retrieval failure.
- **Splitting Continuous Attributes and Cost Matrix were both misdiagnosed by `diagnose_cluster4.py`
  itself**, not by the real pipeline. The script's `NEVER_CANDIDATE` verdict came from a fixed list
  of marker substrings per unit (`'< v'`, `'threshold'`, `'split point'`, `'sorted values'` for the
  former; `'cost of predicting'`, `'actual class'`, `'predicted class'` for the latter) used to spot
  the target sentence inside the retrieved pool — and neither marker set matched how the corpus
  actually phrases either concept. Re-run without relying on hand-picked markers — reading the
  reranker's own top-5 results directly instead — both resolve immediately: the query `"Splitting
  Continuous Attributes"` retrieves `"Splitting continuous attributes."` (a section heading, exact
  match) at rank 0/408 with probability 0.731; the query `"Cost Matrix"` retrieves `"and the cost
  matrix:"` at rank 0/406 with probability 0.729. Both comfortably clear the 0.55 floor. The lesson
  generalizes: a diagnostic tool that filters candidates through hand-written keyword lists inherits
  every gap in the keywords its author happened to think of, and can misreport a real ADMITTED
  result as a false NEVER_CANDIDATE. Every remaining "genuinely open" cluster-4 verdict below has
  now been re-checked the same corrected way (direct top-ranked read, not marker matching) — see the
  revised open-issues count in §18.

With these corrections (a third one, Purity's, came later — see §18), cluster 4's actual
composition is very different from the original diagnosis: of its 12 units, 2 are FIXED (v34), 4 are
reclassified out of retrieval entirely (RIPPER, Evaluation Workflow, Cost Matrix, Splitting
Continuous Attributes — all genuinely ADMITTED, several at rank 0), 1 has a real but different
problem (Cosine Similarity's precision contamination), 1 is an automatic v31 candidate (Centroid
Initialization), 1 is a retrieval-ranking gap initially misdiagnosed as unfixable corpus corruption
(External Index: Purity — its clean formula exists elsewhere in the same document and simply isn't
retrieved; §18), and only 2 remain genuine, unresolved retrieval-recall gaps (Querying Phase, NB
Learning Phase — though see §10 on how v35 interacts with NB Learning Phase specifically).

---

## 8. Fixed this extension: v33, a narrower foreign-method rejection than v27

v27 (rejected, §6 of the run-1 report) fired on any short passage naming both the unit and a
method with no library entry (CLIQUE, SNN, Jarvis-Patrick), and was rejected because that signal is
identical for a real misattribution and an ordinary sibling-method aside.

Reading the real failing text beside the real text that broke v27 side by side shows a sharper
distinction. The failures are **equivalence constructs** — the foreign name sits directly behind a
marker asserting identity:

```
"Complete Link or MAX or CLIQUE"                                    (or-list, unit's own name in it)
"as determined by SNN similarity"                                   (definitional marker)
```

The sentences that broke v27 are **additive or contrastive**, never equivalential:

```
"The methods presented are SFG, SBG, BG, and RG."                   (enumeration, no equivalence)
"Unlike Jarvis-Patrick, which performs a simple thresholding..."    (explicit CONTRAST marker)
"Other techniques, such as DBSCAN and SNN..., have the notion of core points"   ("such as", not "is")
```

`attributes_via_definitional_marker()` fires only on the first shape: a foreign method name within
a short window of "as determined by / measured by / also called / known as", or inside an "X or Y"
list where the unit's OWN name is itself one of the listed items (not merely co-occurring with a
mention of the unit elsewhere in the sentence — see the false positive below).

**Caught and fixed during its own development, before shipping:** the first version's or-list check
required only that the passage mention the unit somewhere, and flagged `"only in the case of MCAR
or MAR missingness mechanisms"` as equating MAR with Missingness Mechanism. MCAR/MAR enumerate two
*kinds* of missingness mechanism; neither claims to *be* the unit. Fixed by requiring a token match
between the or-list's own items and the unit's head terms — `"MAX"` is literally one of the listed
items in the real MAX/CLIQUE case; `"MAR"` is not literally `"Missingness Mechanism"`.

**Library-wide impact**, measured the identical way v27's rejection was measured: 3/2749 evidence
items flagged (0.11%, vs v27's 2.9%), all three the real known-bad cases, zero false positives,
zero units among those the review accepted losing anything. All 7 of the specific sentences that
broke v27 — including the exact SFG/SBG enumeration and the Jarvis-Patrick contrast — correctly
left untouched, tested explicitly as regression guards.

---

## 9. Fixed this extension: v34, a compound unit's equation without its qualifier

Table in §7 shows it directly: External Index: Precision and External Index: Recall both retrieve
their exact correct formula, already above the 0.45 defining-equation floor (0.515, 0.521) — the
only blocker was recognition. The existing defining-equation matcher (v17-v20) requires the unit's
own label text literally before the `=`, and the corpus never writes it that way: within its own
external-index section it drops the qualifier and writes `precision(i,j)=pij`, never `"external
precision(i,j)=..."`.

`compound_index_equation_patterns()` extends recognition, narrowly: for a compound "X: Y" name,
also match `Y` immediately followed by a **required** parenthetical single/double-letter index —
`(i)`, `(i,j)` — as this unit's defining equation. The parenthetical is what keeps this safe: the
plain classifier-level sibling (`"Precision = TP/(TP+FP)"`) never carries an index subscript, so
this cannot rescue the wrong sibling's formula the way an unconditional head-noun match would have
— the exact failure mode v26 was built to prevent. Verified as an explicit regression guard, both
in isolation and through the real `assemble_passages()` call at the precise measured real-world
score (0.515).

---

## 10. Fixed this extension: v35, forward-truncated ("front-severed") fragments — the largest
## single finding this cycle

Following the user's directive to keep working cluster-4 items one by one, re-checking NB Learning
Phase's real retrieval trace turned up something bigger than NB Learning Phase itself. The
reranker's top hits for `"Naive Bayes Learning Phase"`:

```
rank 14   prob 0.590   ADMITTED    "Bayes theorem can be briefly"
rank 187  prob 0.504   below floor "Bayes theorem can be briefly described as follows."
```

A PDF line-break severed the sentence; the fragment beat its own complete counterpart because a
short fragment's few tokens overlap the query more densely than the same tokens diluted across a
longer, more informative sentence. v31 (this cycle, §2b of the earlier register) already catches
the mirror case — a severed TAIL, unambiguous because it starts lowercase. A severed HEAD still
starts with a capital letter and reads as a plausible sentence on its own, so case alone cannot flag
it.

**Design.** Two signals together are safe where either alone is not: the fragment ends with NO
terminal punctuation at all (a genuine complete sentence almost always has one), AND it is a
literal, word-boundary-safe PREFIX of a longer sentence elsewhere in the SAME document that ITSELF
ends with terminal punctuation (confirming that longer sentence really is the complete counterpart,
not just another fragment that happens to be longer). A 20-character minimum on the fragment guards
against coincidental short-phrase collisions ("Recall" prefixing an unrelated sentence that happens
to also start "Recall..."). `build_document_all_sentences()` indexes every sentence 20+ chars per
document regardless of case (broader than v31's index, which additionally requires a capital start
and 60+ chars — the complete counterpart here is only 51 chars, under v31's own floor).

**Verification, in order:**

1. *Isolated* — 8 checks: the real failing case caught; the complete counterpart itself left alone;
   below-minimum-length fragments left alone; cross-document prefix matches ignored (same-document
   only); word-boundary safety (`"...can be briefer than..."` does not falsely match
   `"...can be briefly"` — different word, not a true prefix); a bare heading with no fuller
   counterpart anywhere left alone; end-to-end through the real `assemble_passages()` for both the
   reject and the no-op case.
2. *Library-wide impact*, at the correct grain — the real check runs against a block's single SEED
   sentence, so the measurement looked up each evidence item's `sentence_id` in the real corpus
   rather than scanning the assembled multi-sentence block text (an early version of this
   measurement did the latter and produced a misleadingly inflated 455/2749 — legitimate joined
   blocks contain plenty of individual lines that look truncated in isolation but are already
   correctly reassembled by existing block logic). At the correct grain: **470 of 2749 evidence
   items (17%) flagged, across 133 of the library's 159 units.** A manual read of ~90 distinct
   examples across the full unit list found **zero false positives** — every one is an unambiguous
   mid-clause cut: `"A point is a core point if the number of points within a given"` (Core Point),
   `"Hunt's algorithm is a generic procedure for growing decision trees in a greedy"` (Hunt's
   Algorithm), `"For the complete link or MAX version of hierarchical clustering, the proximity"`
   (MAX). This is a far larger, more pervasive corpus defect than anything else found this cycle —
   neither v29 (formula-specific) nor v31 (suffix-only) could see it, and nobody had checked for the
   prefix-severed half until this trace.
3. *Choking-risk check* — the standing "without choking it" principle demands checking not just
   whether a fix helps, but whether it can zero out a unit's evidence entirely. It can: **3 units**
   (RMSE for Ordinal Targets, MAE for Ordinal Targets, Friedman Test) have ALL of their current
   evidence made of exactly these fragments — `"The goal is to test whether"`, `"These measures can
   be used"`, `"A commonly used evaluation"` — none of which could support a non-fabricated draft
   regardless. Confirmed `abstention_expected` is derived directly as `not passages` in the packet
   builder, so these 3 units correctly flip to an honest abstention rather than continuing to be
   marked `"comprehensive"` support and drafted from content-free fragments. Under the project's own
   top standing principle — no false evidence, even at the cost of recall — this is the right
   outcome: an honest abstention beats a confident draft built on a clause with no verb complement.

**Open watch-item, not yet resolved:** v35 can only ever *remove* a fragment that was going to be
admitted; it cannot promote the fragment's own complete counterpart if that counterpart itself
scores below the floor on its own merits. For NB Learning Phase specifically, the complete
class-conditional-probability sentence sits at rank 35-47 with scores (0.527-0.534) that remain
below the 0.55 floor even after the fragment is gone. Whether NB Learning Phase ends up with *more*
usable evidence, *less*, or roughly the same after v35 depends on how much OTHER already-admitted
content this unit has beyond the one fragment traced here — not yet checked against the real
rebuilt packets. Added to the confirmation checklist in §20.

Folded into the currently-running rebuild rather than deferred: job 244946 was cancelled at 40/159
units (~27 minutes in) and resubmitted as 244952-244956 with v35 included. The scale of impact
(133/159 units) and the clean verification record justify the sunk cost, per the user's explicit
"if you say we should run once for better diagnose... i am willing given it is justified."

Harness: 69 → 77 checks, 0 failed. Commit `119f3d7`.

---

## 11. Cluster 3, diagnosed unit by unit against the real evidence packets

Following through on the second half of the user's "did you do that?" question, cluster 3
(drafting omission) got the same direct-evidence-inspection treatment cluster 4 got, using the
real `evidence_for_synthesis` from a complete pre-cycle packet build
(`_v24to28_prescorerfix/packets/kc_packets.jsonl`). Of the 15 units still failing (§6), 10 are true
`OPEN_DRAFTING` after subtracting the ones already reclassified elsewhere (Gain Ratio into
`OPEN_CORPUS_LIMIT`, Sample Mean and Variance into the already-fixed v25 bug, Hierarchical
Clustering Complexity into `OPEN_NO_RIVAL`, both Models of Randomness units into `OPEN_RETRIEVAL`).
Reading the real evidence for those 10 splits them into four genuinely different shapes — "the
model just omits it" is not one root cause, it is a label the reviewer applied to four different
underlying failures that all happen to look the same from the outside (a plausible narrative
missing its formula or procedure).

**Shape 1 — the formula exists, one block away, behind an unrecognised lead-in.** Bayes' Theorem
(26 evidence items, all narrative, zero formulas) and NB for Numerical Attributes / Gaussian NB (18
items, same pattern) both have their real, cleanly-rendered formula sitting in the very next block
after a sentence already in the packet:

```
"...according to the Bayes' theorem:"        -> "$$ p(theta,X|Y) propto p(Y,X|theta)p(theta). $$"
"...handled with a Gaussian density:"        -> "$$ P(Xi=xi|Y=yj) = 1/(sqrt(2*pi)*sigma_ij) * exp[...] $$"
```

This is exactly v36 (§12) — both confirmed rescued once the regex recognises a bare trailing colon
regardless of the words before it.

**Shape 2 — the evidence is genuinely rich and complete; this is a real drafting-capability gap.**
Cohesion (38 items, including `Total Cohesion=∑i=1K∑x∈Cicosine(x, ci) (7.3)` stated cleanly twice)
and SSE / Cluster Quality (15 items, including `SSE=∑i=1K∑x∈Ci(ci−x)2 (7.4)` plus four separate
fully-worked numeric examples) both have everything a draft would need, already admitted, already
clean. If the model still omits the formula for these two, no packet-side fix reaches it — this is
the honest, irreducible core of `OPEN_DRAFTING`, confirmed rather than assumed.

**Shape 3 — the right content exists in the corpus verbatim but never reaches this unit's admitted
evidence.** K-Means Algorithm (25 items, comprehensively covering history, bisecting K-means, and
objective-function derivations — but not one plain statement of the assign/recompute/repeat loop)
is a real gap, but not for lack of source material: `"Assign each point to the nearest centroid."`
and `"Recompute the centroid of each cluster."` both exist as clean, complete, standalone sentences
in the corpus (confirmed by direct grep, 5 hits each), evidently outranked and crowded out of the
25-passage budget by bisecting-K-means and historical content that shares more surface vocabulary
with the query. This is the same shape as cluster 4's RIPPER and Evaluation Workflow findings (§7)
but on the precision side rather than the floor side — not diagnosed to a fix this cycle; flagged as
a well-scoped next-cycle candidate rather than rushed into this rebuild alongside v35/v36.

**Shape 4 — corrupted or vestigial source, not a drafting problem at all.** Misclassification Rate
(14 items) and Threshold Effect on Precision/Recall/F1 (6 items) both show the SAME corruption
signature: a numeric value cut off right after the decimal point (`"the majority-class error rate
is $1/10 = 0."`, `"precision is equal to while recall is 1"` with the actual precision value
missing entirely) alongside garbled symbol rendering (`$\in \mathsf{i}$` for what should be
`ε_i`). This is the Gain Ratio pattern (`OPEN_CORPUS_LIMIT`) repeating on different units, not a
model failure to use evidence that exists — the evidence itself is damaged. Ranker (Filter
Subcategory) is the opposite problem: only 2 near-duplicate evidence items total (`"Some authors
differentiate a sub-category from filtering called rankers"`, twice, once per ligature variant of
"filtering"), genuinely thin regardless of the `"comprehensive"` label the support-state heuristic
assigned it — a real `OPEN_RETRIEVAL` case mislabeled as drafting. Filter Approach shows a v35-
shaped forward-truncated fragment (`"For the filter approach, such measures attempt to"`, no
terminal punctuation) among otherwise-adequate evidence — expected to improve automatically once
the rebuild's v35 pass runs, checked in §20.

**Headline finding:** of cluster 3's 10 true `OPEN_DRAFTING` members, only 2 (Cohesion, SSE) survive
as a genuine, irreducible drafting-capability gap after direct inspection. The other 8 have an
identifiable, evidence-side explanation — 2 fixed this cycle (v36), 1 flagged as a well-scoped
precision problem for next cycle, 2 as corpus-corruption (matching the existing Gain Ratio
precedent, not newly fixable), 2 as mislabeled retrieval/truncation issues rather than drafting
ones. The lesson generalizes the same way §7's corrections did: a coarse root-cause tag from a
first-pass review (`DRAFTING_OMITTED`) is a starting hypothesis, not a diagnosis, and direct
evidence inspection routinely reassigns most of a cluster's members once someone actually reads
what the packet contained.

---

## 12. Fixed this extension: v36, a bare trailing colon is itself a lead-in

v25 (already shipped) rescues a promised formula only when the promise ends in one of a fixed list
of trigger phrases (`is`/`are`/`given by`/`defined as`/`as follows`/`computed as`/`expressed
as`/`following`) immediately before the colon. Real textbook prose routinely names its referent
between the trigger phrase and the colon instead — `"...according to the Bayes' theorem:"`,
`"...which is known as Bayes theorem:"`, `"...handled with a Gaussian density:"` — and no fixed
word list can anticipate every possible referent noun phrase.

**Fix:** also recognise ANY sentence ending in a bare trailing colon, independent of the words
before it. Safe to broaden because `is_formula_payload()` on the successor block is the real gate,
unchanged by this — a falsely-flagged lead-in whose successor isn't formula-shaped simply fails
that check and nothing is rescued, exactly as before this change.

**Verification:** 4 isolated checks plus 2 end-to-end checks through the real `assemble_passages()`
with BOTH re-verification passes hostile (mirroring v25's own hardened test, since a collision
between this and the OTHER re-check is exactly what defeated v25 silently once already — see the
prior register). The real Bayes' theorem and Gaussian-density cases both confirmed rescued through
the real corpus block-successor graph. Library-wide: 4781 newly-recognised lead-in sentences, of
which 1153 have a genuinely formula-shaped successor (i.e. actually change what gets admitted). A
manual read of 50 randomly-sampled pairs plus the first 15 sequential ones found zero false
positives — every pair is a correct promise-and-formula relationship (`"Brown entropy:"` → the
entropy calculation; `"TPR = TP/(TP+FN) and:"` → `"FPR = FP/(FP+TN)"`; `"the following measure to
determine whether a rule should be pruned:"` → RIPPER's own pruning formula, `vRIPPER=(p−n)/(P+n)`).

No new wiring needed — `ends_with_lead_in()` is called internally by the already-imported
`assemble_passages()`; only its regex changed. Folded into the same rebuild as v35 (job 244952 was
cancelled a second time, at its first checkpoint, and resubmitted as 244962-244966) — the
verification record is equally clean and the value (touching at least 2 of cluster 3's real members,
likely more once the corrected packets are read) justified not deferring it.

Harness: 77 → 83 checks, 0 failed. Commit `852e7b1`.

---

## 13. Fixed this extension: v37, v26 was silently defeating v34's own rescue

Diagnosed while validating v34 against the REAL rebuilt packets rather than trusting the isolated
harness result — precisely because trusting an isolated verification once already let v25's own bug
through undetected this same cycle (§3). External Index: Precision's real packet, after the rebuild
that shipped v34, contained exactly 2 evidence items — both the WRONG formula
(`"Precision, p=TP/(TP+FP)."`, the plain classifier metric), not the `precision(i,j)=pij` formula
v34 was specifically built to rescue.

**Root cause:** `drop_passages_claimed_by_rivals()` (v26) re-scores every admitted passage against
the unit's own name AND against every rival's bare name, dropping anything a rival scores more than
`CLAIM_MARGIN` higher. Measured directly with the real cross-encoder: the target formula scores
**0.507** against its own compound name (`"External Index: Precision"`) but **0.663** against the
bare rival (`"Precision"`) — margin 0.156, comfortably over the 0.08 threshold — despite the formula
being unambiguously and exclusively about the external-index sense (it names `"cluster i"` and
`"class j"` explicitly). This is a cross-encoder query-length/specificity bias, not a real ownership
signal: a short, generic query scores confidently against any text containing that literal word,
regardless of which unit the text actually belongs to. `"External Index: Recall"` showed the
identical pattern against its own rival `"Recall (Sensitivity)"`.

This is the exact same root shape as the original v25 bug (§3) — a later-added rescue mechanism that
an earlier-written, independently-running re-check doesn't know to exempt — just a different pair of
mechanisms colliding (v34 and v26, instead of v25 and `verify_scorer`). The project's own
fix-liveness discipline caught it the same way it was designed to: not by trusting the isolated test
that already passed, but by validating the fix's real, measured effect against the actual rebuilt
output.

**Fix:** a `name_anchored_defining_equation` passage's ownership was already established at
admission time by anchoring the equation-recognition pattern to the unit's own label text (or, for a
compound name, to its head noun plus the parenthetical-index safety check v34 added) — a stronger,
more specific binding than a generic cross-encoder comparison against a bare rival name provides.
Exempt it from rival-stripping entirely, mirroring the exact reasoning that already justified v25's
`lead_in_payload` exemption from `verify_scorer`.

**Verification:** re-ran the exact real corpus failing case with the real cross-encoder — the target
formula now survives, while the classifier-level rival formula is still correctly demoted, confirming
the fix is narrowly scoped rather than a blanket disable of v26. 2 new harness checks encode the real
measured scores as a fixed-scorer regression guard. Re-ran v33/v34/v35's own end-to-end checks
(which exercise `assemble_passages()` directly, not `drop_passages_claimed_by_rivals()`) to confirm
no regression to mechanisms this fix doesn't touch.

Harness: 83 → 85 checks, 0 failed. Commit `32f3736`.

Folded into a third rebuild of this cycle — the most expensive cancellation so far (packets and
topics stages had already completed; the gemma4 draft stage was 54 minutes in, but still at
model-preflight with no actual drafting logged yet). Justified despite the cost: this bug directly
and completely undid v34 for its own showcase units, in a build that was headed for the human review
this whole report exists to prepare for. Shipping a known, understood, already-fixable silent defeat
of an already-verified fix would have repeated the exact mistake this project's discipline exists to
catch.

---

## 14. The systematic audit: "make triple sure everything is in place"

After v37 shipped, the user's response was direct: v25 and v34 had now both been silently defeated
once each, discovered by chance rather than by design, and each discovery cost a full rebuild
cancellation. The explicit instruction was to stop finding these one at a time — audit every
mechanism systematically, so this class of bug cannot recur unnoticed, before spending any more
compute on another rebuild.

**Method.** Every "rescue" admission path (a mechanism that admits a passage some OTHER check would
ordinarily reject or score too low) was inventoried against every post-admission process that runs
on the passages list afterward — inside `assemble_passages()` and in the packet builder's own code
after it returns — checking specifically whether the later process knows to exempt the rescue. Three
more real gaps were found this way, all before the next rebuild:

**v38 — `lead_in_payload` was not exempt from `drop_passages_claimed_by_rivals` either.** v37 fixed
this exemption for `name_anchored_defining_equation` only. `lead_in_payload` (v25) already had the
correct exemption from the OTHER two re-checks (`verify_scorer`, `member_verifier`) — added when
v25's original bug was fixed — but nobody had extended the same exemption to rival-stripping, which
runs outside `assemble_passages()` entirely and was untouched by that fix. Structurally the identical
gap v37 had just closed, for the other mechanism. Fixed by introducing `RESCUE_ADMISSION_BASES`, a
single named constant listing both mechanisms, checked everywhere a re-verification pass runs — so
the *next* mechanism added to this module inherits the exemption by being added to one set, instead
of requiring every check site to be updated by hand, which is exactly how the v37 gap (one basis
exempted, not both) was introduced in the first place. Verified with the real cross-encoder against
the three units confirmed to have a real rival sharing a content word with them (Sample Mean and
Variance, Pearson Product-Moment Correlation, NB for Numerical Attributes), plus a deterministic
regression test reproducing the exact bias shape measured for v37.

**v39 — `deduplicate_passages()` was dropping, not skipping deduplication for, short-signature
passages.** A different mechanism, found in the same pass: this function strips LaTeX markup and
non-alphanumerics to build an extractor-independent content signature, then used `continue` whenever
that signature came out under 12 characters — discarding the passage entirely, before
`verify_scorer` or rival-stripping ever saw it, with no regard for admission basis at all. Confirmed
directly against real corpus content: `"p = 0.1"` → signature `"p01"` (3 chars, dropped),
`"purity(Z1) = 3"` → `"purityz13"` (9 chars, dropped), `"So: P = 5"` → `"sop5"` (4 chars, dropped) —
real, meaningful, short worked-example values. The 12-character floor's actual defensible purpose is
narrower than what the code did: too short to trust as a *deduplication key* (unrelated short
passages could coincidentally collide), not a reason to discard the content. Fixed: a signature under
the threshold now gets a private, never-colliding key instead of being skipped, so the passage is
always kept, just never merged with anything else. Verified: two different short passages are both
kept (not collapsed into each other), while a true duplicate (long signature, identical text) still
correctly collapses to one — confirming this isn't a blanket dedup disable.

**A control-byte corruption inside the very test I was writing to catch this class of bug.** While
adding v38's harness check, the LaTeX in the test literal (`\bar z`, `\frac{1}{n}`) came out
under-escaped by exactly one layer while being written by a nested patch script — the identical
corruption class documented earlier this cycle (§11), just landing in the harness file itself this
time, which the existing guard did not scan. It happened not to change the test's pass/fail outcome
this time (the search string still matched what it needed to), but that was luck, not a property of
the fix. Corrected, and the permanent control-byte guard — previously scoped to `evidence_pack.py`
only — now also scans `verify_pipeline_fixes.py`'s own source, with one documented, deliberate
exception for `v28`'s real intentional control-byte test fixture (which simulates genuine
PDF-extraction wreckage on purpose and must not be flagged).

**v40 — a candidate that WOULD be recognised as a defining equation still had to survive v31 first,
unlike `lead_in_payload` which is exempt from all four rejection checks.** Found from a different
angle: does any rejection check (v30 bibliography, v31 severed-fragment, v33 foreign-method, v35
forward-truncation) run on a candidate *before* it gets a chance to be admitted via
`name_anchored_defining_equation`? Confirmed directly: `is_severed_fragment("precision(i,j)=pij.",
...)` returned `True` — the exact formula this entire cycle's v34/v37 work was built around, wrongly
caught as a "severed fragment." v31 assumes a lowercase-starting substring match means PDF-truncated
prose; true for prose, false for a compact formula that the corpus states BOTH standalone and folded
into an explanatory sentence — that is the corpus restating its own definition, not truncating it.

The first draft of this fix used the same broad "contains a relational operator anywhere" signal
`is_formula_payload` already uses elsewhere — and a library-wide scope scan (run specifically because
of the "triple sure" instruction, not skipped as unnecessary) caught it before it ever reached a
rebuild: 261 affected sentences included real counter-examples, genuine truncated PROSE that merely
*mentions* an attribute-value comparison mid-sentence (`"raw zero probability for Marital Status =
Married in class Y was preventing the stronger income"`, plainly cut off) that the broad signal would
have wrongly exempted, reopening the exact hole v31 exists to close for a different subset of
sentences. Corrected to a START-ANCHORED signal — the text must look like a formula from its own
first token, not merely contain one somewhere — and rescanned: 130 genuinely formula-shaped sentences
correctly exempted (every sampled one a bona fide short equation), the real prose counter-examples
correctly still protected.

**What the audit checked and found clean, not just what it found broken.** Equally important to
report: v35 (forward-truncation) was checked against the same real formulas and does not misfire on
them (it requires the ABSENCE of terminal punctuation, and every real defining-equation example here
ends in a period). v30 (bibliography) and v33 (foreign-method) were checked empirically against 2,631
real formula-start-shaped sentences from the corpus — zero false positives from either, because both
require signal (citation markers, natural-language definitional phrasing) that symbolic formula text
structurally does not contain. This ruled out a broader refactor (giving `name_anchored_defining_
equation` the same blanket four-check exemption `lead_in_payload` already has) as solving a purely
theoretical problem with no empirical counterpart — the narrower, already-shipped v40 fix is the
right scope, not an underscoped one.

**Full end-to-end confirmation, not just unit tests.** The real question the user asked — does the
fix actually work in the places it needs to — was answered by running the complete real chain
(retrieval → `assemble_passages()` with v34/v40 → `drop_passages_claimed_by_rivals()` with v37/v38)
for both External Index: Precision and External Index: Recall. Final result for Precision: the packet
now contains the correct formula in both its explanatory-sentence and bare forms (both via
`name_anchored_defining_equation`, both surviving rival-stripping), while all 7 real classifier-level
`"Precision"` formulas in the candidate pool — TP/FP-based and an unrelated record-linkage formula
that happens to share the word "Precision" — are still correctly dropped as claimed by the rival
unit. Recall showed the identical pattern.

Harness: 85 → 96 checks across v38/v39/v40, 0 failed. Commits `f2a8c1c` (v38, v39, harness guard),
`ad8dbd1` (v40).

---

## 15. "Are you sure everything is checked?" — a direct question, a direct answer

Asked directly, after §14's fixes shipped, whether everything had now been checked. The honest
answer at that moment was no — several avenues had been reasoned about but not verified with the
same rigor as v37-v40, and saying otherwise would have been exactly the kind of overclaimed
certainty that let the original v25 and v34 bugs ship unnoticed in the first place. Five specific
gaps in confidence were named and closed one at a time, in the open, rather than rounded up to "yes."

**`is_structural_junk` — checked, found one negligible case, not a code bug.** This function runs on
every hit *before* it can ever enter the candidate pool `best` — earlier than any of the checks §14
covered, meaning a legitimate formula could in principle be discarded here before v34/v37/v40 ever
get a chance to matter. Its length threshold depends on a corpus metadata flag
(`sentence.get("is_formula_like")`) completely independent of v40's own pattern-based detection — a
different signal that needed its own check. Scanned 1,151 real short formula-shaped sentences: 1,150
had the flag reliably set and passed; exactly one (`"k≠l i≠j"`, a 7-character subscript-condition
fragment) was missing the flag and got wrongly rejected. Traced to a gap in the corpus's own upstream
extraction metadata, not a logic error in this module — left as a documented, negligible residual
(0.09% of cases, and not itself anyone's actual defining equation) rather than patched, the same way
the Gain Ratio corpus limitation is documented rather than chased.

**v29 (`formula_truncated`) — checked, confirmed clean.** Same structural position as `is_structural_
junk` (called from inside it). Scanned 2,631 real formula-start-shaped sentences: 29 were flagged,
and every single one is a genuine truncation — ending bare in `=` or `√` with nothing after
(`"purity ="`, `"cos(x, y) = 10 √"`, `"b(2)=1−w⋅x2="`). Unlike v31, v29 is working exactly as
designed; no false positives, no fix needed.

**v41 — a rescue admission basis could be silently discarded by `deduplicate_passages()` itself.**
The one real gap this round found. `RESCUE_ADMISSION_BASES` (v38) is checked everywhere a
post-admission re-verification pass runs — but `deduplicate_passages()` sits *between* admission and
every one of those checks, merging two passages that share a content signature by keeping whichever
has the higher `_information_score()`, a comparison that does not consider admission basis at all.
Confirmed directly: a `name_anchored_defining_equation` passage (`"precision(i,j)=pij."`) and a
near-identical ordinary `cross_encoder_relevance` passage (`"Precision(i,j) = pij."`, a plausible
different-extractor rendering of the same formula) share the same signature; the merge kept the
ordinary one's basis, silently discarding the rescue tag — the content survives, but its protection
from the strict floor and from rival-stripping does not, reopening the same failure mode through a
third pathway. Fixed: rescue status is now sticky across a merge the same way it is already sticky
across every other check, verified order-independent and confirmed not to become a blanket
promotion (two ordinary duplicates are completely unaffected).

**Checked whether v41 is actually manifesting, not just possible.** Ran the complete real pipeline
end to end for all 5 units that have both a confirmed rescue admission *and* a real rival — the exact
precondition v41 requires — External Index: Precision, External Index: Recall, Sample Mean and
Variance, Pearson Product-Moment Correlation, and NB for Numerical Attributes (Gaussian NB). All 5
came back completely clean even *before* v41 shipped: every real formula intact, every wrong-sibling
formula correctly dropped, zero collisions. v41 closes a structurally real gap that was not
demonstrated to be actively costing anything in the current corpus — fixed on the same principle as
v38: a real gap in a safety mechanism does not wait to be found actively hurting a specific unit
before it gets closed, which is the entire point of auditing systematically rather than reactively.

**`03_build_topic_packets.py` — checked, structurally clean.** This file was not audited at all
before this round. It contains no reference to `admission_basis`, `deduplicate_passages`,
`drop_passages_claimed_by_rivals`, `verify_scorer`, or `is_structural_junk` anywhere — it purely
aggregates the *already-finalized* `evidence_for_synthesis` list from each child KC's packet,
round-robin, under a character budget. It cannot independently silently-defeat a rescue mechanism
because it does not re-implement, re-score, or re-filter anything the KC-level pipeline already
decided — it inherits whatever that pipeline gets right, which after v37-v41 is verifiably more than
it was.

Harness: 96 → 99 checks, 0 failed. Commit `e3ccfb2`.

Folded into a fifth rebuild cancellation of this cycle (packets stage, ~21 minutes in). The scale of
each individual cancellation has been shrinking as the fixes found have moved from "defeats an
already-shipped, celebrated fix" (v37, the most expensive) toward "closes a real but so-far-
non-manifesting structural gap" (v41) — a sign the audit is converging, not a reason to stop before
it does.

---

## 16. "Cleverly, not just exhaustively" — a structural audit instead of another hypothesis

Pushed again, directly: what's stopping a genuinely thorough investigation — do it cleverly, not just
exhaustively. Fair, and accurate about the method used through §14-§15: each finding came from
imagining a specific plausible failure and testing that one thing, one at a time. That finds real bugs
(five of them, so far) but leaves gaps exactly where nothing prompted a hypothesis in the first place.
The cleverer version replaces "guess and check" with a mechanical inventory of the actual code
structure, so nothing depends on remembering to think of it.

**The inventory.** Every function in `evidence_pack.py` was listed and classified by shape: does it
take a `passages`-shaped list and return a transformed one, or is it a single-item boolean check (a
building block used by the transformers, incapable of dropping anything from a list on its own)?
Exactly three list-transformer functions exist in the whole module — `deduplicate_passages`,
`assemble_passages` (the orchestrator), and `drop_passages_claimed_by_rivals`. All three were already
`RESCUE_ADMISSION_BASES`-aware after v37-v41. That is the complete set; there is no fourth
list-transforming function hiding anywhere else to independently re-discover this bug class in.

**What the inventory still missed on the first pass, and why.** `assemble_passages`'s own final step —
sort the surviving passages by raw relevance, truncate to `max_passages` — is a list transformer too,
but it isn't shaped like a "rejection check" or a "re-verification pass," so it wasn't in the mental
category v37-v41 were checking against. This is exactly the value of doing it mechanically instead of
categorically: **v42** — a rescue-basis passage's relevance is deliberately low (that under-scoring is
the entire reason it needed a rescue mechanism in the first place), so sorting by raw relevance alone
lets ordinary, lower-value content budget-truncate a name-verified formula purely because it happens
to score higher, defeating the rescue after every other check already let it through. Confirmed
actively reachable, not hypothetical: **9 real units already sit at exactly the 40-passage cap today**
(Euclidean Distance, Cosine Similarity, Conditional Probability (Likelihood), Attribute/Variable
Types, Generalization Error, Handling Missing Values in NB, Silhouette Coefficient, Inconsistent
Values, Missing Value, Test Statistic), with 34 more within a few items of it. Fixed: rescue-basis
passages sort ahead of ordinary ones unconditionally, ordinary passages still compete on relevance
among themselves for whatever budget remains. `DEFINING_EQUATION_MAX_PER_UNIT` (3) and the naturally
small number of lead-in structures per unit mean this can never meaningfully crowd out ordinary
content — verified directly: a synthetic rescue formula outscored by 45 ordinary candidates now
survives a 40-slot budget it did not survive before the fix, while ordinary-only truncation (no rescue
content at all) is byte-for-byte unchanged.

**Followed the chain one hop further, because a mechanical audit should not stop at the first place it
finds something.** `assemble_passages` re-sorts its own output a SECOND time after the budget
truncation — by region (document + page) reading order, so procedure steps stay sequential rather than
scattered by relevance rank. That re-sort does not know about rescue status either, and topic-level
packet building (`03_build_topic_packets.py`, audited in §15) slices each child KC's evidence by
*position* (`--per-child-max`, default **6** — far tighter than the KC-level 40-item budget). In
principle a rescue item could be correctly *included* by v42 and still be sorted past position 6 by
the region re-sort, missing the topic-level view even though it is safe in the KC-level packet the
user's draft review has actually been about all cycle.

Checked directly rather than left as a bare hypothetical: traced the full real pipeline output order
for the two units with the richest confirmed rescue content, External Index: Precision (3 final items,
rescue items at position 2-3) and Sample Mean and Variance (23 final items, rescue items at position
2-3) — both comfortably inside the 6-item window. There is a structural reason this is not an
accident: `region_rank[r] = max(...)` takes the HIGHEST relevance of any item sharing that page, not
the rescue item's own score — a formula's page routinely also contains the descriptive prose that
introduces it, so the rescue item inherits its region's better ranking rather than being sorted on its
own weak score. Not proven impossible for every one of the 159 units (a formula alone on an otherwise
low-relevance page could still be pushed back), but not observed in either of the two real cases with
the strongest claim to being affected, and not chased into a speculative fix for a problem that has
not been demonstrated — the same discipline v41 was held to, applied the other direction: real
structural gaps get fixed regardless of demonstrated damage (v41, v42), but a theoretical residual
without a demonstrated case and with a found structural reason it is unlikely to fire does not, so as
not to spend another rebuild cancellation chasing a shadow. Documented here as an explicit, checked,
open residual rather than either ignored or over-fixed.

Harness: 99 → 102 checks, 0 failed. Commit `279254a`.

---

## 17. A real, silent bug found in the session's own tooling — and one from three weeks ago

While building v33's or-list regex, a working isolated test kept returning `None` against text a
step-by-step trace confirmed should match. Root cause: `\b` (word boundary) had been silently
reduced to a literal backspace byte (`0x08`) by a shell/heredoc escaping layer several levels deep
in an earlier inline edit — no syntax error, because `\x08` is valid inside a Python string; it
just isn't the regex escape it was meant to be.

A full scan of the module for stray control bytes (`grep`-equivalent over `[\x00-\x08\x0b\x0c\x0e-
\x1f]`) found a **second**, unrelated instance: line 186, inside v29's own already-shipped
`_TRUNCATED_FORMULA_RE`, committed and reported "47/47 passing" several fixes ago. The `\bis\b`
branch had the identical corruption — meaning `formula_truncated()` never actually matched a
sentence ending "... is √" (only "... = √" and bare trailing operators, via the alternation's other
branches). Both of v29's own shipped harness checks happened to use inputs that also satisfy the
unaffected branch, so the corruption was invisible to the harness that was supposed to catch
exactly this class of thing.

Both fixed. A new harness check now scans the whole module source for stray control bytes on every
run — the cheapest possible check, and one that would have caught both instances immediately
instead of by chance during unrelated debugging.

---

## 18. Open issues: why each remaining cluster is still open

Not attempted further this cycle; documented so the reasoning is legible rather than silently
absent.

**OPEN_NO_RIVAL, now smaller** — the units v33 reaches (MAX/CLIQUE, Core Point/SNN) move out of
this bucket. What remains: Jarvis-Patrick complexity, Bregman-divergence misattribution (Cosine
Similarity, confirmed real in §7 — good content is admitted alongside bad, and nothing yet strips
the bad), oblique/multivariate splits, mutually-exclusive-*rules*, generic discretization,
SOM-framed initialization. None of these use the equivalence/definitional-marker construction v33
targets — they read as ordinary (if wrong-context) descriptive prose, the same shape that made v27
too blunt an instrument. No new mechanism attempted for these this cycle.

**OPEN_MARGIN (2)** — Core Point (partially addressed by v33 now — the "as determined by SNN"
sentence specifically is gone; the two milder "such as DBSCAN and SNN..." mentions were correctly
left alone since v33 doesn't touch comparative prose), External Index: Entropy. See §5 for the
margin sweep — no viable value exists for the remainder.

**OPEN_RETRIEVAL, much smaller after the §7 corrections** — External Index: Precision/Recall move
to FIXED (v34). RIPPER, Evaluation Workflow, Cost Matrix, and Splitting Continuous Attributes are
ALL reclassified out of this cluster — each is genuinely ADMITTED against the real pipeline (§7),
two of them (Cost Matrix, Splitting Continuous Attributes) only after correcting a marker-selection
bug in the diagnostic tool itself, not the pipeline. If any of these four are still missing from the
next draft, that is now confirmed to be a budget or drafting question, not a retrieval one. Purity
is corrected here too, the same way Cost Matrix and Splitting Continuous Attributes were: the
garbled `"m purity(i)."` fragment (rank 21, §7) is a stray cell from a worked numeric example's
table extraction, but it is NOT the corpus's only option — `"purity(i) = max j pij."`, a clean,
completely intact canonical definition, sits in the SAME document, two blocks earlier (`pymupdf:
163:26`), and is not admitted as evidence at all (checked directly against the real packet — 9
evidence items, none of them this sentence). This was wrongly written up as a rendering-quality
dead end (`"not addressed for the same reason"` as Gain Ratio); it is actually the same shape as
K-Means Algorithm below — correct content exists verbatim in the corpus and is being crowded out or
outranked, not a corpus limitation. Reclassified as a genuine retrieval-ranking gap and a next-cycle
candidate, not written off.
Ranker (Filter Subcategory) moves IN to this bucket from cluster 3 (§11 — genuinely thin, 2
near-duplicate items, mislabeled "comprehensive" and mislabeled drafting). Genuinely remaining:
Querying Phase (best candidate is a rhetorical question — looks like genuine corpus scarcity for
this specific framing) and NB Learning Phase (whose interaction with v35 is an open watch-item —
see §10), plus Models of Randomness Approach 1/2, not re-examined this cycle.

**OPEN_DRAFTING, much smaller after the §11 corrections** — of cluster 3's 10 true members, only 2
(Cohesion, SSE / Cluster Quality) survive as a genuine, irreducible drafting-capability gap after
direct evidence inspection — both confirmed to already have rich, clean, complete evidence
(including the exact defining formula, stated more than once for Cohesion). Bayes' Theorem and NB
for Numerical Attributes move to FIXED (v36). K-Means Algorithm is reclassified into a new,
well-scoped precision problem (§11, Shape 3 — its actual procedure sentences exist verbatim in the
corpus but are crowded out of the evidence budget, not investigated to a fix this cycle). Ranker
moves to `OPEN_RETRIEVAL` above. Misclassification Rate and Threshold Effect on Precision/Recall/F1
move to a corpus-corruption shape matching Gain Ratio below (numeric values cut off after the
decimal point, garbled symbol rendering) — not a drafting failure, the evidence itself is damaged.
Filter Approach carries a v35-shaped forward-truncated fragment, expected to improve automatically
once the rebuilt packets are read (§20). What's left in this bucket after all of that: the other 11
units from the original run-1 `OPEN_DRAFTING` count of 21 that weren't part of cluster 3's named 16
and haven't had this same direct-inspection treatment yet — a next-cycle task, and worth noting that
the cluster-3 result above (8 of 10 reclassified once someone actually read the evidence) is reason
to expect a similar fraction of those 11 to reclassify too, not to assume they're all irreducible.

**OPEN_CORPUS_LIMIT, now larger** — Gain Ratio (confirmed during the v24 cycle: the corpus's
rendering of Split Information has no intact form anywhere — summation as a bare letter, big parens
as control characters, no fraction bar — and the only readable-looking alternative has ALSO lost its
fraction bar, actively inviting the exact error the model makes), joined by Misclassification Rate
and Threshold Effect on Precision/Recall/F1 (§11 — the same decimal-truncation and symbol-garbling
signature, on different source pages). v28's no-fabrication contract means the model should now (in
principle) decline to state a formula it can't render cleanly rather than guessing — unverified
against any of these three specific cases pending the next draft.

**KNOWN_TRADEOFF (1)** — Bidirectional Generation. Documented in the original v22/v23 commit: a
relationally-defined unit (BG *is* "SFG and SBG run in parallel") loses some evidence richness
because per-member verification scores a sibling-describing sentence against BG's own query, and
sentences describing SFG/SBG don't mention "BG" by name. Accepted cost of the fix that closed the
much larger block-splicing contamination hole; not revisited this cycle.

---

## 19. Fixes shipped this cycle, in commit order

| Commit | What |
|---|---|
| `0edf99d` | v24 (math variant selection), v26 (competitive assignment), v27 built |
| `e6cfb4b` | v28 (reject corrupted math + no-fabrication drafting contract) |
| `7a30077` | v25 bugfix (payload survives verify_scorer) |
| `08fdf89` | v29 (truncated-formula detection: "= √" with nothing after) |
| `148b0eb` | v30 (shattered-citation rejection + _VENUE_RE bugfix), v31 (severed-clause rejection), v32 (status rubric) |
| `052746b` | import-wiring bugfix (build_document_long_sentences missing from packet-builder imports — caught by the harness gate passing while the real job still crashed 9s in; ast.parse alone can't catch a NameError, only actually executing the import chain can, done before resubmitting) |
| `6f829a0` | v33 (narrower foreign-method rejection, replacing rejected v27), v34 (compound-name defining-equation recovery), two control-byte bugfixes (one silent since v29), permanent control-byte harness guard |
| `119f3d7` | v35 (forward-truncated fragment rejection — the largest single finding this cycle, 133/159 units affected) |
| `852e7b1` | v36 (bare trailing colon recognised as a lead-in, independent of wording) |
| `32f3736` | v37 (name-anchored defining equations exempt from v26 rival-stripping — v34 was silently defeated for its own showcase units) |
| `f2a8c1c` | v38 (lead_in_payload also exempt from rival-stripping, via shared RESCUE_ADMISSION_BASES), v39 (deduplicate_passages no longer drops short-signature passages), harness self-scan control-byte guard |
| `ad8dbd1` | v40 (formula-shaped candidates exempt from v31's severed-fragment check, start-anchored after a scope scan caught the first draft's false positives) |
| `e3ccfb2` | v41 (rescue admission_basis survives deduplicate_passages, closing a third pathway to the same failure class) |
| `279254a` | v42 (rescue-basis passages protected from max_passages budget truncation, found via structural inventory rather than hypothesis-testing) |

Fix-liveness harness: 102 checks, 0 failed as of the last commit in this cycle.

Cluster 3 (§11) has now had the same per-unit diagnostic treatment cluster 4 got (§7) — both
clusters are diagnosed to the same standard. What remains open in each is documented in §18.

Six rebuilds were cancelled and resubmitted this cycle to fold in v35, v36, v37, v38-v40, v41, and v42
respectively, each individually justified and reasoned through at the time (§10, §12, §13, §14, §15,
§16) rather than batched. The most expensive and most necessary were the ones that reversed an
ALREADY-VERIFIED fix's real effect rather than adding new coverage — exactly the class of finding
this project's own discipline treats as non-negotiable to ship around, per the user's explicit
instruction after v37 to audit systematically rather than trust that one fix closed the whole class
of bug, the direct follow-up question ("are you sure everything is checked?") that §15 answers
honestly rather than reassuringly, and the further push ("cleverly, not just exhaustively") that
§16 answers by replacing per-instance hypothesis-testing with a mechanical inventory of the code's
own structure. No fix shipped in this cycle without either a concrete demonstrated case or an
explicit, checked reason it does not apply — and where a theoretical residual was found and NOT
fixed (the topic-level region-resort question, §16), the reasoning for leaving it open is recorded
with the same rigor as the fixes themselves, not silently dropped.

---

## 20. What the next draft needs to confirm

1. Sample Mean and Variance / Pearson Product-Moment Correlation both carry their formulas
   (v25 bugfix + same lead-in/payload shape).
2. Agglomerative Clustering's evidence no longer contains the BIRCH citation tail (v30).
3. Feature Selection Definition's evidence no longer contains the reversed-meaning fragment (v31).
4. Overall grounded/partial split moves toward the run-1 calibration (v32) — a useful secondary
   signal, though the real test is still content correctness, not label distribution.
5. The three run-1-resolved units (Cost-Sensitive Classification, DBSCAN Parameters, Euclidean
   Distance) stay resolved.
6. No accepted unit regresses — the standing "without choking it" check, run the same way as every
   prior cycle: retention ratios against the immediately-prior generation, not just the failing
   units.
7. External Index: Precision and External Index: Recall now carry their formulas, admitted via
   `name_anchored_defining_equation` (v34) rather than sitting below-floor unrecognised.
8. MAX/CLIQUE and the "as determined by SNN similarity" sentence no longer contaminate their
   real targets (v33), while the SFG/SBG enumeration and Jarvis-Patrick contrast remain intact and
   undamaged (v33's own regression guards, now to be confirmed against the real draft too).
9. Centroid Initialization Sensitivity's `"of initial centroids."` fragment — check whether a
   fuller counterpart sentence exists in the same document and, if so, whether v31 rescues it as
   predicted in §7.
10. RIPPER Rule Induction, Evaluation Workflow, Cost Matrix, and Splitting Continuous Attributes —
    now that all four are confirmed ADMITTED (§7), check directly whether the new draft states
    them. If still missing despite admission, that confirms the budget/drafting reclassification
    and rules out retrieval as the remaining cause for all four at once.
11. RMSE for Ordinal Targets, MAE for Ordinal Targets, and Friedman Test correctly show as
    abstentions rather than drafts built on the single content-free fragment each used to have as
    its only evidence (v35's confirmed choking effect on exactly these 3 units — §10).
12. NB Learning Phase's total evidence count and content, before/after v35 — the specific open
    watch-item from §10: v35 removes a fragment that was going to be admitted, but its own complete
    counterpart remains below-floor on its own merits, so this unit's net evidence change is not
    yet known and needs a direct read of the real rebuilt packet.
13. A spot-check of a random sample of the 133 units v35 touches, beyond the ones already named
    above, confirming the fragment is simply gone and not replaced by something worse.
14. Bayes' Theorem and NB for Numerical Attributes (Gaussian NB) now carry their real formulas,
    admitted via `lead_in_payload` (v36) rather than 26/18 evidence items of narrative with no
    equation anywhere among them (§11, §12).
15. Cohesion and SSE (Cluster Quality) — confirmed to already have complete, correct evidence
    (§11, Shape 2); if the next draft still omits their formulas, that is now a clean, isolated
    signal about the drafting step itself, unclouded by any possible evidence-quality excuse.
16. K-Means Algorithm — check whether the assign/recompute/repeat steps make it into the draft now
    that the rebuild includes v35 (which may free up budget by rejecting truncated competing
    fragments); if not, the crowding-out diagnosis from §11 Shape 3 stands and is a real next-cycle
    retrieval-precision task, not a drafting one.
17. External Index: Precision and External Index: Recall now carry their OWN correct formula
    (`precision(i,j)=pij`, `recall(i,j)=mij/mj`) rather than the plain classifier TP/FP formula
    v26 was wrongly substituting in (v37+v40, §13-§14) — already confirmed directly against the
    real end-to-end pipeline before this rebuild (§14), not merely predicted; the next draft
    should show the drafted text finally reflecting the formula that was in the packet all along.
18. A spot-check of the other 5 units with a real short-name rival sharing a root word with a
    compound name (§13's blast-radius scan found 7 units carrying a surviving defining-equation
    passage after v37; 2 of them, Precision and Recall, were the confirmed damage cases) —
    confirming v37 didn't only fix the two showcase units but the general class of the bug.
19. Sample Mean and Variance, Pearson Product-Moment Correlation, and NB for Numerical Attributes
    (Gaussian NB) — already confirmed via a full real end-to-end pipeline trace before this
    rebuild (§15, not just the deterministic v38 unit test): all 3 formulas intact, 0 passages
    dropped by their real rivals. The next draft should show the drafted text finally reflecting
    what the packet has carried correctly since before this rebuild started.
20. A spot-check of a random sample of the 130 sentences v40's corrected, start-anchored signal
    now exempts from v31, confirming each one really is a formula and the real draft benefits
    from it (the theoretical risk this checklist item exists for was already ruled out once by
    the pre-rebuild scope scan in §14, but a real draft is the final confirmation).
21. Any unit whose evidence includes two near-identical formula renderings from different
    extractors (the precondition v41 needs) — confirm the merged passage still carries a rescue
    admission_basis and was not silently exposed to the strict floor or to rival-stripping. Not
    demonstrated to be actively occurring for any unit checked this cycle (§15), so a clean
    result here is expected, not a surprise.
22. Any of the 9 units that already sit at the 40-passage cap (Euclidean Distance, Cosine
    Similarity, Conditional Probability (Likelihood), Attribute/Variable Types, Generalization
    Error, Handling Missing Values in NB, Silhouette Coefficient, Inconsistent Values, Missing
    Value, Test Statistic) — check whether any of them actually had rescue-basis content that
    was being truncated before v42, and whether the new draft now states it.
23. The topic-level packets specifically (not the KC-level packets everything else in this
    report is about) for Cluster Evaluation and any other topic with a rescue-bearing child KC
    — confirm a rescue item that is safe at the KC level also survived the region-based re-sort
    and the topic level's much tighter --per-child-max=6 window (§16's open, checked-but-not-
    fixed residual).

---

## 21. Late-cycle documentation catch-up: v43 and draft archive infrastructure

This report previously stopped at v42 even though two follow-up commits had already shipped before
the fresh v3_20260812 output was reviewed.

`1bb86de` is v43. It fixed a draft-runner/schema mismatch: KC outputs were expected to contain
`segmentation_support` and `evaluation_support`, but the repair path could leave abstained KCs in a
state where those structural fields were still absent. v43 made schema repair legal for legitimate
abstentions whose only defects were structural support fields. The v43 liveness check added in this
cycle confirms that policy-allowed abstentions can still receive structural schema repair after the
newer invalid-abstention work below.

`7dcf6db` is archive infrastructure. It made newer drafting scripts self-archive job-ID-specific
final outputs. That matters for this cycle because the fresh comparison depends on knowing exactly
which output came from which submitted job, rather than guessing from mutable filenames in
`data/v3/runs/v3_20260812/drafts/`. The current archive contains the completed gemma4, qwen36, and
topic outputs from jobs 245232, 245182, and 245233 respectively. Command-r job 245183 was still
running when first checked in this continuation and was confirmed to be on A100 GPU offload rather
than repeating the previous CPU-only incident.

## 22. Fresh v3_20260812 KC draft assessment

The human review of the current 159-KC `kc_drafts(2).jsonl` reported:

- 103 correct/sufficient attempted definitions.
- 42 attempted definitions needing revision.
- 6 appropriate abstentions.
- 8 unjustified abstentions.
- Attempted-definition acceptability of 103/145 = 71.0%.
- Overall success of 109/159 = 68.6%.

The headline comparison is that this is an improvement over the immediately prior generated files
but still below the original stronger run: original 76.5/75.5, then 68.0/67.9, then 69.1/68.6, now
71.0/68.6. The current failure surface is therefore not one clean retrieval miss. It is a mixed
surface:

- malformed mathematical renderings in packet evidence and drafted text;
- false or policy-disagreed abstentions;
- residual sibling/foreign-method contamination;
- content-thin drafts even when evidence is present;
- genuine retrieval/corpus gaps where the packet has only headings or fragments.

The fresh-output verifier run after `225f6cd` measured the live current output, not a synthetic
fixture: 36 damaged evidence items across 30 rows, 17 damaged contextual KC drafts, and 5
abstentions that meet the new conservative content-repair gate. It also showed why a broad
"comprehensive packet + abstained" repair would be unsafe: McNemar Test and Informative Missingness
are marked comprehensive by packet metadata but their packet evidence is fragmentary or generic,
matching the human review's decision to keep them as appropriate abstentions.

## 23. Previously shipped fixes that were not sufficient against the fresh output

The liveness harness still shows the old fixes executing: after the v44-v46 commit it reports 119
checks, 0 failed. The issue is not that v25/v36/v37/v38/v41/v42 disappeared. The continuing
failures are narrower:

1. v28 was too narrow for damaged math. It caught control-character wreckage and a few truncated
formula endings, but not lost fraction bars or display-equation block splices. This let evidence
such as `P(Y|X)=P(X|Y)P(Y)P(X).`, `GainRatio(A)=IG(A) SplitInfo(A).`, `AUC = 1 P · N`, and spliced
display math enter packets and then drafts.
2. v43 repaired structural schema fields, but an invalid abstention is a content failure, not just a
missing-field failure. A schema repair pass cannot turn an empty abstained draft into grounded text.
3. v28's prompt-side "do not reconstruct formulas" rule was not enough as a validator. The current
draft file contains 17 generated contextual KC drafts with damaged mathematical renderings, and
those previously passed validation.

The handoff's most common root-cause pattern was checked explicitly. The v44 formula filter would
have been silently defeated if only `is_structural_junk()` had changed, because v25/v36 lead-in
payload inheritance uses `is_formula_payload()` as the real gate. `225f6cd` therefore routes both
paths through `math_rendering_damaged()`.

## 24. v44: damaged formula renderings beyond control characters

Commit `225f6cd` extends `math_rendering_damaged()` with deliberately narrow signatures for the
fresh observed extractor failures:

- conditional-probability denominator loss;
- function-over-function ratio loss;
- count-fraction denominator loss;
- one-over-product denominator loss;
- pair-count denominator loss;
- display math spliced to unrelated trailing text.

It also makes `is_formula_payload()` reject the same damaged renderings. This is the important
self-defeat guard: without it, v25/v36 could still inherit a bad successor formula even after the
structural-junk path learned to reject it.

Verification:

- `verify_pipeline_fixes.py` now checks the Bayes, Laplace, GainRatio, AUC, and spliced-display
  failure shapes directly.
- It also checks that a normal explicit fraction remains admissible.
- The full liveness harness passes: 119 checks, 0 failed.

Expected rebuild effect: current packet evidence contains 36 now-damaged evidence items across 30
rows. A packet rebuild should drop or avoid those items before any model draft sees them.

## 25. v45: invalid-abstention repair without forcing fragment packets

The first tempting fix was too broad: "packet policy says non-abstain, model abstained, therefore
repair." The current output proves that would be unsafe. McNemar Test and Informative Missingness
are both metadata-labelled comprehensive, but their evidence is not draftable; forcing content there
would manufacture unsupported definitions.

Commit `225f6cd` therefore adds a gated content-repair path:

- only KC packets are eligible;
- packet-policy abstentions remain untouched;
- the packet must contain substantive prose;
- the evidence must overlap at least two target-name content-token stems;
- fragment-only packets and generic sibling-level evidence are not repaired.

On the current output this routes five abstentions to content repair: Representative Training
Sample, Bushy Decision Tree (Multi-split), Multi-class Confusion Matrix, Centroid Initialization
Sensitivity, and Models of Randomness (Approach 2). It deliberately leaves McNemar Test and
Informative Missingness alone, and it also leaves no-evidence or heading-only cases such as NB
Learning Phase, Evaluation Workflow, and Models of Randomness (Approach 1) as packet/retrieval
residuals rather than asking the model to invent.

Verification:

- The liveness harness checks a repairable Representative Training Sample fixture.
- It checks policy-allowed abstentions do not route to content repair.
- It checks fragment-only McNemar and generic Informative Missingness packets do not route to
  content repair.
- It checks v43 policy-abstention schema repair remains live.

## 26. v46: generated damaged math is now a validation failure

Packet filtering is necessary but not sufficient. The fresh draft itself contains damaged math in
17 contextual KC drafts. That means a model can copy a damaged formula, or reconstruct one despite
the prompt contract, and still pass the old validator.

Commit `225f6cd` adds draft-side damaged-math validation for KC and topic contextual text. When such
a validation issue appears, the draft runner uses a content repair prompt that forbids formula
reconstruction and tells the model to remove the broken equation unless the packet contains an
intact source formula.

Verification:

- The liveness harness checks that a generated Bayes denominator-loss formula raises
  `kc_contextual_draft_damaged_math`.
- It checks that damaged-math drafts route to content repair.
- It checks that intact prose does not raise the issue.
- It checks that the repair prompt explicitly forbids formula reconstruction.
- The current-output verifier confirms the new validator flags the same 17 damaged draft rows
  already identified by direct `math_rendering_damaged()` measurement.

## 27. Rebuild/drafting implications

The chain ordering must be packet rebuild first, then model drafting. v44 only affects packet
selection after packets are rebuilt; v45 and v46 only affect drafting after rebuilt packets are fed
to the models. Starting drafting against the old packet JSONL would preserve the old damaged
evidence surface and would not test the intended fix.

Residuals after v44-v46, to check in the next real output:

- rows whose packets remain too thin or generic despite human review marking the source as
  available, especially NB Learning Phase, Evaluation Workflow, and Models of Randomness
  (Approach 1);
- units where the packet has only a short incomplete formula such as external precision/recall;
- residual sibling/foreign-method contamination in clustering and DBSCAN/SNN areas;
- content-thin drafts where retrieval is adequate but the model omits procedure, assumptions, or
  formula detail.

---

## 28. Packet rebuild 245267 evaluation and v47

Packet rebuild job `245267` completed successfully on `cn024` in 01:27:59. It ran the liveness
harness inside the Slurm job before building and passed the then-current 119 checks, 0 failed. It
then wrote fresh artifacts at 2026-08-14 09:13 CEST:

- `data/v3/runs/v3_20260812/packets/kc_packets.jsonl`
- `data/v3/runs/v3_20260812/packets/topic_packets.jsonl`
- corresponding KC/topic stats JSON files.

Operational packet stats were healthy: 159 KC packets, 154 with evidence, 5 empty; mean 12.18
passages; 90 formula-bearing units; 133 procedure-bearing units. The 5 empty packets remained the
same policy-abstention set: NB Learning Phase, RMSE for Ordinal Targets, MAE for Ordinal Targets,
Friedman Test, and Nemenyi Test.

However, the semantic packet evaluation caught exactly why real packet checks must follow every
rebuild. v44 removed the old literal damaged signatures — the new packet file had 0 hits for the
plain-text Bayes/Laplace/GainRatio/AUC/Rand strings that motivated v44 — but the same damage class
survived through a different rendering path. Bayes' Theorem still contained the denominator-lost
formula as a LaTeX `\mathsf` rendering, and other compacted formula renderings survived for
conditional probability, gain ratio, RandIndex, and Euclidean distance.

This is the handoff's most common root-cause pattern again: the fix was active, but a different
representation path silently defeated the literal check. Gemma job `245268`, which had started only
after `245267` completed, was therefore cancelled at 01:39:35 elapsed rather than allowed to finish
on a still-contaminated packet file.

Commit `3c8ff65` is v47. It adds `compact_formula_signature()` so formula damage checks normalize
LaTeX wrapper macros, tags, spacing, and common math operators before applying structural lost-bar
patterns. The harness now includes the rebuilt-packet residuals directly:

- LaTeX-wrapped Bayes denominator loss;
- damaged LaTeX formula payload inheritance;
- conditional-probability RHS `P(...)` loss;
- gain-ratio `infoSplitInfo` denominator flattening;
- numeric RandIndex denominator loss;
- Euclidean `d(x,y)=sum squared` rendering with no square root;
- negative checks for a square-root Euclidean worked example and a correct Bayes formula with
  explicit division.

Verification after v47: liveness harness 127 checks, 0 failed. Running the compact packet evaluator
against the already-built `245267` packet file under the new code identifies 9 now-known-bad
evidence items across rows 13, 15, 25, 27, 82, and 85. None of those removals would empty a packet,
so the correct next step is a second packet rebuild, then gemma-only drafting after that rebuild
succeeds.

---

## 29. Packet rebuild 245312: full semantic audit and v48-v53

Packet rebuild `245312` completed with 159 KC packets, 154 evidence-bearing packets and 5 empty
packets. The pre-build liveness run passed 127 checks. No model-drafting job was submitted from
this artifact: the packet review below found that it was not safe to draft from.

The strict review of the preceding 159 drafts reported 42 defective attempted definitions and 8
unjustified abstentions. Every one of those 50 rows was traced back through `245312` rather than
treated as one undifferentiated model-quality problem. The packet-side findings formed six
mechanical clusters:

1. Damaged mathematics still had representations outside v44/v47's signatures. A whole-artifact
   scan under the expanded detector found 57 damaged evidence items across 23 rows. Removing them
   in simulation emptied no packet.
2. Coherent source-block members were scored in isolation and discarded. This affected NB
   Learning Phase, RIPPER, K-Means, Models of Randomness, and External Index Precision/Recall.
3. v33's SNN ownership check still had a container-size bypass: a short misattributed seed was not
   checked when another member made its raw block longer than 320 characters.
4. A single equality or Greek symbol could turn a long prose paragraph into a protected
   `lead_in_payload`; this admitted the SVM paragraph seen in Euclidean/Cosine packets.
5. The builder called every non-empty packet `comprehensive`, so a heading or unrelated fragment
   was indistinguishable from substantive target support.
6. Fragmented structured lists had no ownership mechanism. The distance-properties source is one
   admitted lead block followed by five consecutive blocks for positivity, identity, symmetry,
   and triangle inequality; only a fragment survived previously.

The corresponding fixes are:

- **v48, formula integrity and payload shape.** `math_rendering_damaged()` now checks delimiter
  balance and the exact numerator/denominator-loss and concatenation signatures observed in the
  fresh artifact. `has_explicit_fraction_notation()` prevents the prose word `fraction` from
  silently satisfying a notation check. Long non-display prose is no longer a formula payload
  merely because it contains one equality.
- **v49, SNN long-block bypass.** `assemble_passages()` applies v33 to the ranked seed and the raw
  block independently, then applies the same ownership check again to final kept members.
- **v50, licensed context scoring.** The same source-context scorer now runs at candidate
  admission, member verification and final passage verification. Context is licensed only by an
  exact canonical heading or a member coherently attached to a unit-bearing source anchor.
  Deduplication preserves this admission provenance.
- **v51, truthful support states.** Packets now report `insufficient_support`, `weak_fallback`, or
  `draftable`; they never claim measured completeness. Empty packets alone require abstention.
- **v52, compound sibling formula ownership.** Indexed cluster/class precision and F-measure
  equations belong to their explicit `External Index:` sibling rather than the same-named plain
  classifier measure.
- **v53, structured list continuation.** An explicit properties/conditions lead may own a
  consecutive numbered heading plus intact formula list on the same source page and patch. The
  rule requires a numbered first block and at least one formula, and stops at the first ordinary
  prose block. It recovers all five real distance-property blocks without becoming generic
  adjacency expansion.

Real reranker jobs `245333`, `245353`, and `245356` established the context thresholds with the
actual model, not a mock. The canonical-name run measured, among others: RIPPER's isolated
procedure member 0.501 versus 0.628 with its licensed block; the K-Means assignment step 0.502
alone versus 0.730 under its exact heading; External Precision 0.500 alone versus 0.608 in its
block; and Models of Randomness Approach 1/2 about 0.508 alone versus 0.710/0.718 with licensed
context. The SNN negative remained about 0.730 and the SVM negative remained about 0.500, proving
that context recovery must coexist with, not replace, deterministic ownership guards.

After v53, the full liveness harness passed 167 checks, 0 failed. This includes all previous
v3-v47 controls, real positive continuations, off-topic negative controls, deduplication
provenance, final re-verification, and budget truncation.

## 30. Semantic ownership audit and v54

A second pass over all 159 frozen `245312` packets found a different silent-defeat pattern in the
compound equation rescue. Its comment and design required lowercase cluster indices `(i)` or
`(i,j)`, but the entire regular expression was compiled case-insensitively. Consequently ordinary
decision-tree equations `Entropy(D)` and `Entropy(F)` were treated as protected equations for
`External Index: Entropy`. Their rescue basis then exempted them from every later rival check.

v54 makes only the measure name case-insensitive; index symbols remain genuinely lowercase. It
also carries a payload pointer's ownership context into the emitted passage, so a bare formula
cannot shed the semantic owner established by the prose that points to it. This closes the same
post-admission provenance class that caused v25/v37/v38/v41, now for semantic ownership rather
than relevance alone.

The full packet replay also established a finite set of high-confidence wrong-sense signatures:

- Naive-Bayes parameter training inside the generic Learning Phase;
- feature-selection `search strategy` text inside Querying Phase;
- mutually exclusive *rules* inside Mutually Exclusive Classes;
- MDL `Cost(tree,data)` / `Cost(model,data)` inside Cost Matrix;
- external cluster F/precision/recall content inside their plain classifier siblings;
- ordinary node/classifier entropy and confusion-matrix measures inside `External Index:` units;
- JP complexity and hierarchical F-measure evaluation inside Hierarchical Clustering Complexity;
- SNN and local-density-attractor/xi variants inside standard DBSCAN concepts;
- Bregman-family prose inside Euclidean Distance and Cosine Similarity;
- random search-direction and generic algorithm-nondeterminism statements inside the feature
  selection strategy `Non-Deterministic Search`;
- noisy-data filtering inside the feature-selection `Filter Approach`.

These are now deterministic, auditable ownership drops. Each requires both the exact target family
and the observed contradictory subject/signature. A replay against all 159 frozen packets removes
44 passages, all in those reviewed families. Direct target counterexamples for every rule remain,
and the replay produced no unrelated-unit drops.

Support-state target binding is stricter as well: one shared generic word can no longer make a
packet `draftable`. Ordinary passages must carry the complete target terms; pointer-owned,
name-anchored-equation, and licensed-context passages keep their already-proven target binding.

After v54, the full liveness harness passes 176 checks, 0 failed. A 69-unit real packet regression
build was submitted as Slurm job `245360` using the immutable production corpus and the normal
production resource envelope. Its profile subset contains every reviewed defect/abstention row,
every row hit by the expanded formula detector, and the appropriate-abstention controls. The full
rebuild remains blocked on inspection of that real diagnostic artifact; model drafting remains
blocked on the subsequent full rebuild and packet validation.

## 31. v55-v58: opaque ordinals, residual convention collisions, and executed-packet inspection

The 69-unit probe exposed one registry problem before it completed. `Models of Randomness
(Approach 1)` and `(Approach 2)` differ only by an ordinal that does not occur in source prose.
Their canonical strings therefore cannot tell a lexical, dense, or cross-encoder retriever which
source procedure each ordinal denotes. Reusing the same numbered-label query would make both
units compete for the same evidence and could silently swap them on every rebuild.

v55 adds a deterministic `retrieval_disambiguation_terms` profile field for only those two KC
IDs. Profiles are still generated directly from the hierarchy overlay. A field-by-field comparison
against the prior 159 profiles shows zero changes to every previously consumed field and exactly
two intentional values in the new field. The packet builder uses a non-empty value as the semantic
retrieval query and records `registry_disambiguation_applied`; all ordinary units retain the
established candidate-query path. Reciprocal terminal ownership guards prevent the two procedures
from crossing after admission.

While cross-walking all 50 reviewed problem rows, three additional packet hazards were found in
the frozen `245312` artifact:

- `Sample Mean and Variance` combined an unbiased `n-1` sample-variance definition with separate
  Gaussian maximum-likelihood prose. The generated draft then incorrectly called the `n-1`
  estimator the MLE.
- `SSE (Cluster Quality)` contained the source-rendering sentence "average pairwise distance"
  beside Equation 7.14, whose actual identity uses squared pairwise distance.
- `Shannon Entropy` inherited an intact mutual-information equation because a lead-in named both
  `I(X,C)` and `H(X,C)` before pointer rescue selected the following equation for `I`.

v56 adds narrow terminal guards for those exact convention/adjacent-equation collisions. A replay
removes three MLE passages, one unsquared-SSE sentence, and one mutual-information equation while
retaining the direct sample-statistic, squared-SSE, and entropy definitions. Slurm job `245375`
is the three-unit real-builder proof for these guards; its result is pending below.

The first real two-unit build, job `245364`, then demonstrated why automated signature checks must
be followed by full packet reading. The high-level v55 assertions passed, but Approach 1 contained
correct random-data/SSE sentences interleaved inside extractor blocks about Chameleon,
graph/subgraph definitions, and frequent-itemset support. It also retained generic `K=n` SSE and
"clustering is unsupervised" snippets. v57 rejects those observed stitched foreign-topic blocks
and requires an explicit random/null/statistical signal for this specifically disambiguated unit.
It removes seven passages from the executed packet and leaves twelve, including the clean docling
rendering of the complete random-data K-means/SSE procedure.

Inspection of the immutable corpus found a second issue in the initially chosen Approach 2 term.
It retrieved a valid but generic *classification* permutation test. The intended clustering source
is Section 10.5.2, which states the actual three-step external-index procedure: generate randomized
sets of labels, compute the external index for every randomization, and derive the p-value by
comparing randomized values with the original. v58 changes only that unit's disambiguation value
to the exact source-grounded concepts `randomized sets labels compute external index p-value
clustering`. It also rejects classifier-training/accuracy permutation passages unless they carry
external-index or clustering context. The obsolete v57 diagnostic job `245376` was cancelled after
82 seconds rather than consume shared resources with the superseded query. Corrected job `245378`
is pending below.

The liveness harness now executes 189 checks with 0 failures. In particular, it proves all new
terminal guards reject the real bad signatures, retain direct target counterexamples, and cannot
be bypassed by rescue admission provenance. `drop_semantically_misbound_passages()` runs after
assembly and before final rival filtering, and no later stage re-adds passages. A repeatable
50-row matrix reproduces 42 failures on the frozen `245312` packets; it will be rerun against the
new diagnostic and final full artifacts.

Executed results replaced the three pending items above:

- `245375` completed. Sample Mean and Variance and Shannon Entropy passed their target checks. SSE
  did not: a damaged error-rate formula appeared only after source-block assembly, while the clean
  Equation 7.1 row never entered the long-query BM25 pool.
- `245378` completed. The corrected Approach 2 query reached the intended external-index step, but
  full packet reading found that the MinerU block stitched the step between market-basket,
  proximity, and K-means prose. That exact executed block motivated v59 below.
- `245360` remains the long-running 69-unit v48-v54 problem/control subset. It intentionally loaded
  the v54 code present when submitted; later target jobs and the final rebuild carry v55 onward.

No model drafting has been submitted. The full packet rebuild remains blocked until the real
target artifacts and the 69-unit diagnostic are inspected and every fixable residual is resolved.

## 32. v59-v63: executed splices, terminal math, duplicate block IDs, and equation recall

Job `245380` is the real v59 Approach 2 proof. v59 rejects the exact MinerU block observed in
`245378` when the external-index sentence is inseparably stitched into market-basket, bounds-on-
proximity, triangle-inequality, or K-means/centroid prose. The clean Docling rendering remains.

The v56 SSE failure established a second post-admission self-defeat. Candidate-level math checks
ran before assembly; assembly could concatenate individually admissible fragments into one damaged
passage afterward. v60 applies `math_rendering_damaged()` to the exact assembled passage list before
semantic and rival filtering. Replaying the v56 artifact drops exactly the damaged assembled item.

The immutable corpus contains a clean SSE source paragraph and Equation 7.1, but the existing
profile query did not retrieve them reliably. v61 adds one registry correction for
`KC_CLU_EVAL_002`: `SSE sum squared error Euclidean distance closest cluster centroid formula`.
A 159-profile field audit found zero changes to old fields and exactly three intended values in the
new disambiguation field: the SSE unit and the two randomness ordinals. Job `245384` then recovered
the clean closest-centroid/squared-error prose but still missed Equation 7.1 because that exact row
never entered BM25 top 400.

The same job exposed a corpus-identity defect. Exact extractor block ID
`DOC_introduction_to_data_mining:mineru:77:426` names both the clean random-data/SSE paragraph and
an unrelated agglomerative/Chameleon paragraph. The old `(doc_id, block_id)` key merged them before
member scoring. A corpus-wide audit measured 100,218 rows, 45,596 old doc/block IDs, 804 IDs reused
across source regions, 1,101 additional source regions hidden by the old key, and 1,590 sentence IDs
reused across source regions. v62 adds a full SHA-256 `source_block_text` discriminator, falling
back to a full SHA-256 of page/bbox, while preserving the original raw block ID in output
provenance. Pointer continuation refuses adjacency across either side of an ambiguous raw ID. The
new corpus block count is exactly 46,697 = 45,596 + 1,101. Job `245385` confirmed the observed
Chameleon/itemset/proximity block splices disappeared.

v63 closes the SSE equation-recall gap. The builder maintains a bounded index of formula/equality
rows and supplements a query pool only where an exact unit-label left-hand-side equation matches.
Supplemented rows still pass ordinary reranking, math integrity, ownership, final filtering, and
budget gates. The harness proves Equation 7.1 is added for SSE while SSB is not. Job `245387`
recovered the clean squared closest-centroid definition and Equation 7.1.

## 33. v64-v69: fixes that real execution and corpus-wide scope checks caught as inert

Manual reading of job `245385` found one isolated Approach 1 contaminant:
`(A K-means++ approach could be used as well.) Another approach is to choose the replacement
centroid...`. v57's source contained the intended `K-?means\+\+` guard followed by `\b`; that word
boundary can never match after `++`. An earlier harness fixture passed only because another foreign
marker in the same text masked the inert branch. v64 removes the impossible trailing boundary and
adds the isolated real signature as its own test. Job `245388` passed the strict randomness checks
and dropped that item.

The Approach 2 packet was still procedurally incomplete: it retained only the middle instruction,
"For each randomized set of labels, compute the external index." Immutable Docling blocks 37-40
contain the complete same-page/same-patch sequence: generate M randomized label sets, compute each
external-index value, define the p-value as the fraction exceeding the original value, then the
rendered equation. A real reranker probe measured the middle step at 0.724, while the lead, first
step, p-value step, and equation scored only 0.500-0.530 against the 0.55 gate.

v65 introduced a bounded source-structure rescue around an independently admitted procedure step.
It requires backward adjacency to an explicit `as follows` lead and forward adjacency to a formula
boundary, at least two procedure-shaped blocks, at least three payload blocks, and one page/patch.
The formula is a stop marker, not inherited evidence. Synthetic end-to-end tests passed, but job
`245398` remained incomplete. The required protocol therefore did not accept v65.

A corpus-wide scope audit found why. The real p-value prose block is itself marked formula-like
because it contains `mi > m0`; v65 stopped before it. v67 replaced the raw formula flag with an
equation-dominance boundary and excluded definition lists introduced by `defined as follows`.
Another scope run showed that twelve-word p-value prose still met the first boundary heuristic and
that damaged equations could evade `is_formula_payload()`. v68 separates boundary recognition from
formula admissibility: a short formula-flagged relational block stops continuation even if damaged,
but ordinary prose does not. A third real-data trace then found one auxiliary sentence record in
the p-value source block marked heading-like. `any(is_heading_like)` silently defeated continuation;
v69 requires the entire block to be heading-like before treating it as a boundary.

After v69, the full harness passes 215 checks with 0 failures. The corpus-wide scan over all 100,218
rows and 46,697 fingerprinted blocks finds exactly one structurally licensable sequence: the three
intended Approach 2 prose steps. No unrelated procedure or definition sequence remains. Final real
job `245477` completed in 00:09:25 with exit 0. Its emitted packet contains all three steps in
source order under `procedure_list_payload`, excludes the rendered Equation 10.9 block, and passes
the strengthened completeness, damaged-math, semantic-ownership, and cross-approach checks with 0
failures. The superseded job `245398` fails exactly the first-step and p-value-comparison checks,
providing a real before/after proof rather than only a synthetic fixture.

v70 removes one adjacent future self-defeat risk. `passage_has_strong_target_anchor()` previously
duplicated the special admission-basis names in the packet builder even though passage relevance,
deduplication, and rival protection already use `RESCUE_ADMISSION_BASES` and
`CONTEXT_ADMISSION_BASES`. It now derives one `STRONG_TARGET_ADMISSION_BASES` union from those
shared registries. The harness asserts exact equality and inclusion of the new procedure payload;
after v70 it passes 216 checks with 0 failures.

## 34. v66: SSE target packet cleanup after formula recovery

Although v63 restored the central SSE evidence, manual reading of job `245387` found three residual
items that the initial evaluator did not reject: a clipped common-mistakes bullet literally saying
"Computing SSE with unsquared Euclidean distances", and two definitions of between-group sum of
squares (SSB), a separation measure rather than within-cluster SSE. This is lexical retrieval of a
different `sum of squares` objective, not formula recall.

v66 assigns standalone SSB definitions to `SSB (Cluster Separation)` while preserving passages
that explicitly compare SSB and SSE. It also rejects only the observed detached unsquared-SSE
warning; independent clean squared-distance definitions remain. The strengthened evaluator fails
job `245387` exactly on these three residues. Job `245397` then passes: direct squared closest-
centroid definition present, Equation 7.1 present, no damaged math, no SSB evidence, no detached
unsquared warning, and the source-grounded query override recorded.

No drafting job has been submitted. Packet rebuild and validation remain strict prerequisites for
any later model chain.

## 35. v71: topic packets use the same truthful support vocabulary

The Section 20 topic-packet check found one stale policy path before rebuild. v51 removed the false
`comprehensive` claim from KC packets, but `03_build_topic_packets.py` still assigned
`packet_support_state="comprehensive"` to every non-empty topic packet. v71 centralizes topic state
selection in `topic_support_state()`: source-bearing topics are `draftable` with reason
`child_source_evidence_available_no_completeness_claim`; empty topics remain
`insufficient_support` with an explicit no-child-evidence reason.

The drafting runner already normalizes and accepts `draftable`; no later chain depends on the stale
topic-only `comprehensive` value. The liveness harness now passes 219 checks with 0 failures. A real
topic composition probe against all 22 hierarchy topics produced 22 rows, all `draftable`, zero
`comprehensive`, and zero empty. The final rebuild validator also checks that every topic item
exactly matches an evidence ID/text pair in its child KC packet, carries no damaged math or known
child-semantic misbinding, and that the six-item per-child cap preserves the repaired SSE and both
randomness procedures.

## 36. Broad 69-unit audit and v72-v73 terminal findings

The delayed real problem/control build `245360` completed in 02:43:59 with exit 0. It emitted all
69 requested packets from the normal immutable corpus: 14.74 mean passages, 4,318 mean characters,
51 units with definition evidence, 45 with formula evidence, 60 with procedure evidence, and 43
with example evidence. This job loaded v54 when submitted, so its purpose is broad failure discovery;
the completed v56/v66/v69 target artifacts provide the later-code replacements for Sample Mean and
Variance, Shannon Entropy, SSE, and both Models of Randomness units.

The strengthened evaluator found the expected post-v54 residues and two previously unobserved
silent defeats. Replaying the exact broad evidence through the current v60 terminal math filter
drops all five damaged assembled passages, in K-Means, Hierarchical Clustering Complexity, DBSCAN
Parameters, Density-Connected, and the superseded SSE packet. The v66 SSE artifact replaces the
last of these and independently passes its strict content checks. The broad collision audit also
finds 73 evidence items seeded by ambiguous legacy sentence IDs, further confirming that v62's
source-text fingerprint identity is a global correction rather than a randomness-only patch.

v72 fixes the first new defect. v52 correctly recognized cluster-indexed F-measure evidence when
`External Index: F-Measure` was supplied as a rival, but the real hierarchy puts the plain and
external units under different branches. The plain F-Measure packet therefore had an empty rival
list and retained four external/hierarchical cluster-evaluation passages. v72 gives the finite set
of known external-index measure heads an implicit compound owner when explicit cluster/index
notation is present. It also treats the observed `hierarchical F-measure` phrase as external only
for the plain F-measure unit. The exact four broad passages are dropped; ordinary classifier
`F1 = 2PR/(P+R)` remains.

v73 fixes the second. Friedman Test and McNemar Test both reduced to the single context term `test`.
That generic overlap licensed unrelated decision-tree test-condition and Bonferroni passages as
`context_anchored_relevance`; the support-state function then trusted that admission provenance and
called both packets draftable. v73 adds `test` to the same context stopword set that already excludes
generic `model`, `class`, `index`, and `measure`. The executed false contexts no longer anchor either
named test, while direct McNemar/Friedman text and the distinct `statistic` anchor in Test Statistic
remain live. The full harness now passes 228 checks with 0 failures.

The strict 50-row lexical matrix still reports missing literal phrases in packets that the earlier
source audit already classified as corpus scarcity, valid abstention, or valid differently worded
support. Those are not silently reclassified as fixed: Querying Phase and Mutually Exclusive
Classes are now honest empty packets after foreign-sense removal; RIPPER carries its direct method,
sequential covering, pruning, and stopping evidence; and External Index: Precision carries the
source's own `precision(i,j)=pij` definition. The matrix remains a failure-discovery tool, while
acceptance is based on emitted source evidence, current terminal replay, targeted real builds, and
the final 159/22 rebuild validator.

Diagnostic job `245550` completed in 00:03:24 with exit 0. McNemar Test became `weak_fallback`
with one fragment rather than false draftable support; Friedman Test became `insufficient_support`
with zero evidence. Plain F-Measure contained no cluster-indexed or hierarchical-F passage, but
manual reading found one generic target-name list under source heading `8.4 Graph-Based Clustering`.
Because support assessment sees an exact target phrase, that one passage still made the packet
`draftable` even though it could not support the requested classifier definition.

v74 closes that last context-loss path. Terminal compound ownership now considers the passage's
source patch heading as well as emitted text and pointer ownership context. It also requires an
actual `F-measure`, `Fmeasure`, or indexed `F(...)` head for the normalizer's one-letter `f` base,
so arbitrary words containing that letter cannot trigger the rule. Replaying the executed v73
packet drops exactly the Graph-Based-Clustering item, retains the F1/F-beta pointer and unrelated
generic fragment, and leaves no strong target-anchored substantive passage. The harness passes
232 checks with 0 failures. One-unit real proof job `245551` completed in 00:01:34 with exit 0.
Its plain F-Measure packet is `weak_fallback` with the same two unanchored fragments, permits
abstention, and contains no cluster-indexed, hierarchical-F, or Graph-Based-Clustering evidence.

No drafting job has been submitted. All diagnostic jobs are complete; the full packet-only rebuild
is the next operation.
