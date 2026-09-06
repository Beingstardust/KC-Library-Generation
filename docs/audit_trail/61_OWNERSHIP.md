# 61. Evidence ownership: where the failure actually happens

Doc 58 recorded that the external review's category A had no mechanism here. This is the
investigation that followed, including the parts that failed. It ends with the failure located
precisely and one intervention defined but **not yet justified**, which is stated plainly rather
than shipped on plausibility.

## The case

`External Index: Entropy` is drafted from decision-tree entropy. Its nine admitted passages are
two generic "external structure" sentences, one statistical-testing sentence, and six node-entropy
rows. `Entropy (Node)` and `Shannon Entropy (Uncertainty Measure)` are already among its
`rival_units_considered`, and the rival contest did not move anything.

## What the literature says

Cross-encoder rerankers jointly encode the query-document pair and can disambiguate entity senses
given context, and hierarchical retrieval work routinely feeds root-to-node paths as context. But
the SIGIR result on query expansion and strong cross-encoder rankers is explicit that **naive
expansion degrades strong rankers**, and that what works is "minimal-disruptive query
modification" plus retrieving per variant and fusing, rather than appending terms to one query.

That maps onto an architectural fact about this pipeline: it already retrieves **per name form**
and selects between them (`full_retrieval_per_form_core_shapes_then_mean_relevance_then_count`,
`max_relevance_by_form`, `passage_count_by_form`). So a hierarchy-qualified form can be added as
another *candidate* form that competes under the existing selection rule, rather than replacing
the query. Minimal-disruptive by construction.

## Four ground truths tried, three rejected

An ownership rule needs a label, and inventing one by hand would be the domain tuning this audit
refuses.

**Section headings** (`_int17/diag_ownership_gold.py`). The documents record the section each
passage came from. Restricting to numbered headings leaves 970 passages: 306 name their holder,
150 name only another unit. Rejected: reading the 150 shows a passage inside a section about X can
legitimately support Y (a passage under "4.4 Maximum Likelihood Imputation Methods" genuinely
discussing attribute types). Worse, in the document that matters most, five of nine External Index:
Entropy passages carry no heading at all and one "heading" is an exercise question. Usable as a
feature, not as a label.

**Lexical name-in-text** (`_int17/build_ownership_eval.py`). 545 `keep` pairs (holder named, no
rival named) and 105 `flip` pairs (rival named, holder not). The `keep` side is sound and is kept
as a **safety** set for any future rule. The `flip` side is rejected: "Handling Missing Values in
NB" holding a passage plainly about itself is labelled flip because its compound name is not fully
present. Systematically biased against long-named units.

**Hierarchy path as a discriminator between siblings.** Of the 105 flip cases, 58 have a rival
under the same parent. A path the two units share cannot separate them, so path qualification is
structurally incapable of helping in more than half the contested cases.

**Expert annotation.** The review's own list is real human annotation and is the only trustworthy
benefit set available. Small, so any claim resting on it is anecdotal and must say so.

## Where the failure actually is

`_ownership/diag_candidate_pool.py` reproduces the lexical stage exactly (same index, same pool
size, no reranker) and asks where the correct rows landed.

The whole cluster-entropy definition lives in one block, present in all three extraction layers:

```
[0] Entropy:                                                    is_structural_junk -> True
[1] The degree to which each cluster consists of objects of a single class.
[2] For each cluster, the class distribution of the data is calculated first ...
[3] Using this class distribution, the entropy of each cluster i is calculated ...
[4] The total entropy for a set of clusters is calculated as the sum of the entropies ...
[5] pij, pij=mij/mi, mi mij  ei= -SUM_j=1..L pij log2 pij  e=SUM_i=1..K (mi/m) ei
```

Everything the review said was missing is in member [5].

Ranks in the 400-row pool:

```
query                                           target rows in pool   best rank
External Index: Entropy                              1 of 5             328
Clustering Cluster Evaluation External Index: ...    2 of 5             117
```

Three things follow.

1. **It is a recall problem before it is an ownership problem.** The definitional sentence [1]
   contains no occurrence of "entropy" at all, because the label is a separate sentence. It never
   enters the pool under any query tried.
2. **The block is reachable only through member [3], and marginally**: rank 328 of 400. It was in
   the pool and still did not reach the packet, so it also failed at the 0.55 rerank floor.
3. **Hierarchy qualification measurably helps the lexical stage**: 328 -> 117, and two members
   instead of one. That is a real effect at the stage where the loss begins.

Meanwhile the contaminating passage "popular measures include entropy and the Gini index" ranks
**8th**. The reason is worth recording: the compound name contributes the token "index", which
lexically matches "the Gini index" in a completely different sense, while the words that would
identify the right block ("cluster", "class") are absent from the unit's name. They are present in
its hierarchy path.

## The intervention this defines, and why it is not shipped

Add the hierarchy-qualified form as one more candidate query form, retrieved per form and selected
by the existing rule. Do not touch admission thresholds, the rival margin, or the bare-name form.

What is measured: it moves the correct block from rank 328 to 117 in the lexical pool for one unit.

What is **not** measured: whether it changes any packet for the better. The block still has to
clear the cross-encoder floor, which needs a GPU run, and the effect over all 159 units could
easily be negative - the SIGIR result exists precisely because expansion often is. Adding a query
form also multiplies retrieval cost per unit.

So it stays defined and unbuilt until an A/B says otherwise. The evaluation is already designed:
the 545 `keep` pairs as the safety set (a qualified form must not lose passages a unit plainly
owns), and the review's list as the benefit set, reported as the anecdotal evidence it is.

## What was ruled out for good

- Path qualification cannot help the 58 of 105 contested cases whose rival shares the parent.
- Lowering `CLAIM_MARGIN` from 0.08 would move these passages and is a threshold relaxation, which
  is refused for the same reason it has been refused throughout: it buys this row and pays for it
  everywhere else, unmeasured.
- `is_structural_junk` correctly rejects the bare label "Entropy:". It is a label. The block-level
  admission that already exists is the right mechanism, and it works; the block simply never won.
