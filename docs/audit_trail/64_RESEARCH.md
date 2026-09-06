# 64. Categories A and C: what the literature offers, and what survives the constraints

Doc 58 recorded that the external review's category A (semantic ownership) and category C
(completeness) had no mechanism here. This is the literature search for both, done deliberately
rather than as background reading, with each candidate tested against three constraints that are
not negotiable in this project:

1. **No fine-tuning.** Anything whose method is "train the retriever/reranker on better negatives"
   is out, however good the reported gains.
2. **No threshold relaxation.** Anything that works by lowering a floor or a margin is out.
3. **Generic.** No rule may reference a KC, a document, or subject-matter vocabulary.

---

# Category A: which concept owns this evidence

## What the literature says

**Hard-negative mining** is the dominant answer, and the field agrees on the shape of it: negatives
drawn from a concept's own taxonomic neighbourhood are the informative ones. The clearest analogue
to this problem is medical entity linking, where the question is literally "which ontology concept
owns this mention": ancestors and depth-1 descendants are used as negatives, with gains of 5.5 to
5.9 points on unseen mentions and concepts.

**Rejected by constraint 1.** Every one of these methods fine-tunes the encoder. The insight
transfers, the method does not.

**CERA** (contrastive evidence retrieval with attention alignment) does operate at query time with
no retriever fine-tuning, and addresses exactly the stated problem: passages that are topically
similar but belong to a different concept. It scores passages by whether the retriever's attention
actually supports selecting them, and deprioritises those that match only on surface topic.
Plausible, but it needs the reranker's internal attention, and its own reported limitation is
ranking-phase cost across the candidate set. A large lift for an unmeasured gain.

**The finding that actually matters** is about ranking *form* rather than ranking *model*. LLM and
cross-encoder ranking is done pointwise, pairwise, listwise or setwise, and the literature is
consistent that **pointwise scores each passage independently and is the weakest at capturing
relative relevance**; setwise presents the competing candidates together in one prompt and gets
the comparative signal at a fraction of listwise's cost. Zero-shot, no training.

## Why that is the finding

`drop_passages_claimed_by_rivals` is **pointwise**:

```python
own_scored   = scorer(unit_name, texts)          # one score per passage
rival_scored = scorer(rival, texts)              # one score per passage, per rival
...  if best_rival[i] > own[i] + CLAIM_MARGIN:   # compare two independent numbers
```

Each score is produced without the model ever seeing the competitor. The margin (0.08) then tries
to recover a comparative decision from two numbers that were never compared. For External Index:
Entropy versus Entropy (Node) it does not clear, and the node-entropy passages stay.

That is the weak configuration the literature names, and the fix is a change of form, not a change
of threshold: **ask one question about the contested passage and the competing units together.**

## What is proposed, and what still has to be measured

Setwise ownership arbitration, restricted to contested passages: those where a rival's score is
within some band of the holder's. The units are named with their hierarchy paths, so the model
sees "Clustering > Cluster Evaluation > External Index: Entropy" against "Classification >
Decision Trees > Entropy (Node)" rather than two bare labels that share a word.

In its favour: no fine-tuning, no threshold moved (the band selects what to arbitrate, it does not
decide anything), the pipeline already runs an LLM and already has a verifier bakeoff, and the
cost is bounded by the contested set rather than by the corpus.

Against it, and this is why it is not built here: it puts a generative model inside retrieval,
which is a real architectural commitment; the contested set has not been counted (the reranker was
busy); and it is a *second* mechanism for a decision that already has one, which is exactly the
kind of accretion this audit has otherwise refused.

## And a finding that partly undercuts all of it

For the case that motivated category A, ownership is not where the loss happens. Measured in
`_ownership/diag_candidate_pool.py`: the block holding the entire cluster-entropy definition
reaches rank **328 of 400** in the lexical pool under the unit's own name, and its definitional
sentence never enters at all, because the label "Entropy:" is a separate sentence and the
definition itself contains no occurrence of the word. Meanwhile "popular measures include entropy
and the Gini index" ranks **8th**, because the compound name contributes the token "index" and it
matches "the Gini index" in an unrelated sense.

Hierarchy-qualifying the query moves the block to rank **117**. So the first loss is recall, not
ownership, and an ownership mechanism placed after it would arbitrate over a candidate set that
never contained the right answer. Any work here should start at the pool, not at the contest.

---

# Category C: completeness

## What the literature says

**Nugget-based coverage** is the established reference-free method: enumerate the atomic units of
information a complete answer must contain, then measure how many the answer has. The nuggets are
normally human-authored, which is the whole difficulty.

**Context sufficiency** is the other half, and the framing is useful: whether the retrieved
context contains the facts needed at all is a *different* question from whether the answer used
them. The literature names the failure mode precisely - retrieval succeeds, the context still does
not support a complete answer, and the model produces a plausible one anyway.

**Genus and differentia** is the classical account of what a definition owes: what kind of thing
it is, and what separates it from its neighbours.

## What that yielded here

The differentia half turned out to be **already solved**. All 159 r4 drafts fill
`sibling_contrast_notes` and `do_not_confuse_with`, and they are good:

```
Learning Phase
  "Distinguish from 'Querying Phase', which involves applying the learned model to new data."
  "Distinguish from 'Training Set vs. Test Set Split', which is a data preparation step."
```

The context-sufficiency framing produced **INT-17**, which is the one that worked: the drafting
rubric answers "did the draft use what it was given" and nothing answered "was that enough". Six
of the review's eight category-C units are thin packets that no existing signal flagged. See
doc 62.

## Two attempts that failed, with numbers

**Unused admitted evidence** as a nugget-coverage proxy, with the packet as the nugget source.
Lexical overlap between an evidence row and any body sentence, threshold 0.5. Mean unused share is
**0.64 across all 150 drafted units**, good and bad alike. It does not discriminate;
`_completeness/diag_unused_evidence.py`.

**Sibling shape norms**, the genus half derived from the hierarchy rather than hand-written: a
unit's siblings are the same kind of thing, so if 11 of 12 children of a parent have
definition-shaped evidence and one does not, the one is missing something its own taxonomy says it
should have. This is a nice idea and it is not the category-C mechanism: it flags 17 units, of
which only **1 of the review's 8** (ID3 Algorithm, which it flags twice, for definition and
formula). What it actually correlates with is abstention - 4 of its 17 are already abstained and 4
more are the Models of Randomness / Bushy Decision Tree group that r4 now abstains.
`_completeness/diag_sibling_shape_norm.py`. Kept as a taxonomy-coverage report, not as a
completeness check.

## The residual, honestly

Two of the review's eight - Comparing Two Models on Independent Test Sets, Threshold Effect on
Precision/Recall/F1 - have 6 and 9 substantive evidence rows. They are not thin. The draft sets up
the question and stops before the method: it names `M1` and `M2` and independent test sets and
never gives `d = e1 - e2`.

The literature's answer is an LLM judge scoring answer completeness against the retrieved context,
reference-free. That is available - the pipeline runs an LLM and has a verifier - and it is not
fine-tuning. It is also a model-based judgement replacing a rule, which is a different kind of
component from everything else in this audit, and it would need its own validation against the
same expert list it is meant to reproduce, on a sample of two.

Recorded as understood but unbuilt. Two units is not enough evidence to justify putting a judge
inside the pipeline, and the honest statement is that this residual is real and unaddressed.

---

# Summary

| category | mechanism found | status |
|---|---|---|
| A | pointwise ownership contest is the weak form; setwise arbitration is the literature's answer | designed, not built: the prior loss is recall, not ownership |
| A | hierarchy-qualified query form | measured at the pool (rank 328 -> 117), effect on packets unmeasured |
| C | context sufficiency reported apart from status | **built** as INT-17, covers 6 of 8 |
| C | nugget coverage via unused evidence | rejected, 0.64 mean everywhere |
| C | genus from sibling shape norms | rejected as a completeness check, 1 of 8 |
| C | LLM judge for answer completeness | understood, unbuilt, 2 units of evidence |
