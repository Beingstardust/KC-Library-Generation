# Pipeline defect audit — top-down, phases 1 to 6

Every entry is measured against real artifacts, not inferred. Fixed items name their commit;
declined items give the number that made declining correct.

---

## Phase 1–2: parsing and retrieval-substrate construction

### F1. Typographic ligatures destroyed tokens in the lexical channel — FIXED `399e3c0`
The BM25 tokenizer keeps `[a-z0-9]`, and a ligature is neither, so it acted as a word separator
*inside* a word:

    define -> ['define']            deﬁne         -> []                     (word vanishes)
    classification -> [...]         classiﬁcation -> ['classi','cation']
    filter -> ['filter']            ﬁlter         -> ['lter']

Queries are built from cleanly-typed hierarchy labels, so ligature-bearing evidence was
**unreachable**, not merely down-ranked. 357 corpus rows affected. Measured recovery: 91 real
content tokens gained, 72 junk tokens removed, `classification` 0 -> 33 reachable rows,
`classifier(s)` 32, `coefficient(s)` 19.

Explicit ligature map rather than NFKD, because NFKD also rewrites superscripts (`x²` -> `x2`)
and would silently alter mathematics. Guarded by LIG-4.

### F2. Dense channel disagreed with the lexical channel — FIXED (this session)
`tokenize()` expanded ligatures; `DenseIndex` embedded raw text. The two channels disagreed about
the same sentence.

The dangerous half was the **cache**: its key is derived by the caller from the corpus file's
path/size/mtime/row-count — entirely content-independent — so changing preprocessing does *not*
change the key and a pre-existing cache would be silently reused. The fix would have looked
present while every vector still came from unnormalised text.

Guard therefore lives *inside* `DenseIndex`: the preprocessing identity is written into the cache
and verified on load. Proven by real execution — a legacy-style cache is rejected
(`cache_status=written`, not `hit`), a valid one is reused, and `cosine(clean, ligature) = 1.000000`.

### F3. Severed display-fraction numerators — FIXED `54d4649`
The extractor stacks a display fraction into separate rows, so the numerator becomes a standalone
"equation" that parses perfectly and is **mathematically false**:

    row N     'P(Xi = c | y) = nc + 1'     <- reads as complete. It is false.
    row N+1   'n + v ,'

No integrity check caught it: `math_rendering_damaged("P(Xi = c | y) = nc + 1")` is **False**,
while the joined form `"P(Xi=c|y)=nc+1n+v,"` is correctly caught. The damage gate protects against
*mangled* renderings, not *truncated-but-tidy* ones.

**5 KCs per data-mining run were already handed one as evidence** and instructed to reproduce it
exactly — `Precision` received F1's numerator, `AUC` received its numerator, plus `Cohesion`,
`Overfitting`, `MAX (Complete Linkage)`. Rejection, not repair: guessing the bar position
fabricates mathematics; dropping leaves the drafter to report the formula missing.

### F4. Split citations hid formula lead-ins — FIXED `6c6325d`
A formula's naming pointer is the only route to an equation whose own tokens are LaTeX. The
pointer failed whenever the source's citation was itself split across rows:

    'The textbook gives the Laplace estimate:[1, p. 308]'

The promise and colon are intact; `[1, p.` trails after. 6 genuine formulas recovered, including
the intact MinerU renderings of the Laplace estimator, conditional probability
`\frac{P(X,Y)}{P(X)}`, the evidence/marginalisation term, and the Gaussian class-conditional
density — precisely the formulas drafts had reported as missing.

**Order dependency:** an earlier attempt at this same fix was written, tested end-to-end, found to
admit the *false* stranded numerator, and reverted. It is safe only alongside F3. Guard LI-4 pins
that dependency so the two cannot be separated later.

### D1. Split-fraction rejoining — DECLINED, measured
955 candidates. Best gate reaching acceptable precision recovers **7 of 522** true denominators
(1.3%). Loose gates fabricate: `'Precision = 0.750'` + `'12'` (a page number). Root cause is that
bboxes are **block**-level — one numerator block spans 296pt — so "directly below" is not
decidable. Full numbers in `local_audits/SPLIT_FRACTIONS_FINDING.md` with the labelled sample.
Moves only with line-level extraction at parse time.

### D2. Within-line bar loss — UNFIXABLE
13 rows (`'Precision = 3 3 + 1'`). The bar's position is unrecoverable by any means.

### D3. Unreachable intact formulas — LOW VALUE
4,110 intact formula rows; 679 reachable by no route. Inspection shows these are worked-example
arithmetic (`M2 = (0.12, 0.60)`, `C(M1) = 1 −1.1(0.50)...`), not defining formulas. The drafting
contract already warns against restating worked-example values as general properties.

### D4. Ligature/encoding, word fusion, boilerplate — LOW VALUE
357 ligature rows (fixed above), 70 word-fusion, 62 lost-space, 94 repeated-boilerplate. Sampling
shows the fusion/space detectors mostly match legitimate camelCase identifiers and control-char
formula rows; boilerplate is already deduplicated at admission.

---

## Phase 3: hierarchy integration

### F5. Duplicate canonical name overwrote its twin's branch context — FIXED (this session)
`unit_branch_terms` keys on canonical_name (the ownership rule receives names, not ids). One name
denotes two unrelated branches:

    KC_EVAL_COMP_007  Model Evaluation / Finding the Best Model
    KC_FSEL_STAT_004  Data Engineering / Feature Selection / Statistical Testing

Whichever built last won; the other silently carried its twin's ancestry. A name denoting two
branches has no well-defined branch, so it is now given **none** — ownership falls back to the
compound's own qualifier words, the conservative direction — and the duplicate is printed to the
build log rather than absorbed.

### Clean
0 units without ancestry, 0 self-siblings, 0 self-rivals, 0 self-referential branches.

### Documentation correction
`_RETRIEVAL_DISAMBIGUATION_BY_KC_ID` is **empty** and **0 units** carry curated disambiguation
terms. The paper's Limitations section still states that three data-mining units carry them —
that is now stale and should be updated.

---

## Phase 4: retrieval and admission

### F6. Compound-sibling ownership was hardcoded to one curriculum — FIXED `18cfc78`
Ownership was decided by a typed-in word list plus a named-metric special case:

    r"\b(?:clusters?|clustering|external\s+index|cluster\s+labels?)\b"
    if own_base == "f" and re.search(r"\bhierarchical\s+F\s*-?\s*measure\b", ...)

Two defects, not one: it named a subject vocabulary and a specific metric, and — naming only that
subject's words — **could never fire on any other corpus**, so the rule was silently inert outside
data mining.

Replaced with a curriculum-derived discriminator:
`discriminating(rival) = branch_terms(rival) − branch_terms(base)`. On the real hierarchy that
computes to exactly `{cluster, clustering, external}` — the same discriminating power, now derived
rather than invented, and available in any subject. Shared ancestry cancels, so it cannot carry a
transfer alone.

Also fixed an over-claim it exposed: a passage **stating** the base unit's own defining equation
is no longer transferred by context alone. Measured: of 11 compound-dropped passages, 6 correctly
stay with the sibling and **5 return to their base unit**, including the F-beta definition and
formula that had left classification `F-Measure` holding only `'F = F \ {f}.'` (a set-difference
from *feature selection*) and `'Select an evaluation measure.'`

### Validated as correct behaviour, not a defect
**9 of 10** weak/insufficient KCs are genuine corpus gaps — Friedman, Nemenyi, MAE/RMSE Ordinal,
McNemar, Querying Phase, Evaluation Workflow, Cost-Based ROC, Informative Missingness. The
abstention mechanism is working. The 1 real miss was F-Measure, addressed by F6.

### Verified, correcting an earlier sloppy claim
6,631 corpus rows start lowercase and never terminate. `is_severed_fragment()` classifies **5,253**
as real fragments — far more than "mostly legitimate", as I had loosely described them. What
matters is the outcome: **0 reached evidence** in either run. The guard works.

---

## Phase 5: drafting and validation

### F7. Damaged-math validator flagged correct mathematics — FIXED `86ecd65`
**All 10** flags on the real run were false positives, from two causes.

6× a genuine regex bug: `_ONE_OVER_PRODUCT_BAR_LOST_RE` matched `"=1 to"` inside `∑(i=1 to C)` and
`∏(i=1 to m)`, and `"= 1 on"` inside `s(x,y) = 1 only if x = y`. It required only `= 1` followed by
two letters with no constraint that they are standalone variables.

4× the wrong unit of analysis: `math_rendering_damaged()` is tuned for short extracted evidence
sentences and was applied to generated prose (874–6,994 chars). A normal paragraph after a display
equation read as a "stray tail"; a quantity discussed across three paragraphs read as a "repeated
named equation"; one unclosed paren at char 5,614 of 5,624 read as damaged delimiters.

Span granularity is **sentence-level** and that is load-bearing: line-level missed a damaged
formula appended inline to prose (defeating the existing v46 guard), and token-level shredded
formulas containing English connectives (`chi-squared = sum from j=1 to r of ...` cut at
`from`/`of`), manufacturing 16 fresh false positives.

### F8. Topic contract was a three-way mismatch — FIXED `0c0176e`
The enforced schema (`additionalProperties: False`) declares `child_kc_summaries` and
`contextual_topic_draft.supporting_evidence_ids`. It does **not** declare
`child_kc_coverage_summary` or `supporting_child_kc_ids` — the model is physically forbidden from
emitting them. The prompt asked for them anyway and the validator required them, so **22/22 topic
drafts failed by construction**. Measured: 0/22 for both forbidden fields, 22/22 for both real
ones, and all 22 topics already accounted for every direct child.

Aligned on the schema. The coverage intent is preserved and strengthened — now derived by
comparing `child_kc_summaries` against the packet's own `direct_child_kcs`, naming the unaccounted
ids. That derived check immediately found **2 genuine coverage gaps** the broken check had masked.

### F9. Abstentions faulted for their own required shape — FIXED `0c0176e`
The prompt instructs an abstention to keep text and `evidence_map` empty; the validator then
reported exactly that as two schema errors. All 8 remaining KC issues were this. The real signal —
a model declining a draftable packet — is already reported by the status-integrity gate, so this
double-counted one disagreement in the wrong vocabulary.

**Net effect on the promptfix run: KC issues 8 -> 0 across 159 drafts; topic issues 44 -> 0 across
22; mathematics topics 38 -> 0.** No regeneration needed.

---

## Phase 6: review resolution
Not audited. The paper already documents this phase as not reliably operational end to end.

---

## Verification discipline

Suite grew 305 -> 328 checks, 0 failed. A full sabotage audit breaks each fix in its real source
file and requires the suite to fail.

**The audit found two of my own guards to be defeatable, which is the point of running it:**
- `DL-1` checked `expand_ligatures` anywhere in the file; `tokenize()` also calls it, so removing
  it from `DenseIndex` went undetected. Now checks the call inside `DenseIndex.__init__` and
  `top_k` specifically.
- `SN-5` matched substrings that remain present when the condition is wrapped in `if False and …`.
  The drop was refactored into a real function so it can be tested behaviourally, and `SN-6` now
  requires the call to be the **direct right-hand side of an assignment**, which also rejects
  short-circuit disabling (`x = (a, []) or f(...)` keeps the Call node while `f` never runs).

## Outstanding
- Existing draft artifacts still carry validation flags computed under the old validators;
  re-deriving is cheap and needs no GPU.
- Paper Limitations section: the disambiguation-terms claim is stale (now 0).
