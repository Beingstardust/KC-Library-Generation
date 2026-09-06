# 49. Semantic correctness of the final drafts, read against source

Method: no classifier, no scoring script. Fifteen KC drafts were read in full alongside every
evidence item in their packets and judged by reading. Extraction was used only to lay draft and
source side by side (`_semantic_read/dump_for_reading.py`, SLURM job 248814).

Sampling is deliberately adversarial, not random: formula-bearing units, units the interventions
touched, units whose own uncertainty notes named a defect, and four abstentions. Defect density
here is therefore an upper bound on the library and must not be read as a library-wide rate.

## A methodological correction, stated first

My first pass extracted only each evidence item's `text` field. Evidence items also carry
`source_block_text` and `patch_heading`, and `patch_heading` can hold real assertive content.

That caused one false finding. I judged the Spearman draft's sentence "if there are no ties in the
data, a shortcut formula may be used" to be an unsupported insertion, because no `text` field
mentioned ties. It is in fact supported by item 0007's `patch_heading`:

> "Rule. No ties: the shortcut formula is okay. Ties: use average ranks and compute Pearson
> correlation on the ranks."

The Spearman draft is fully grounded. Every "unsupported" verdict below was subsequently re-checked
against all three text fields of every evidence item in the packet.

## Confirmed defects

### 1. Euclidean Distance states a formula that is not the definition, while the real one sits in a sibling's packet

The draft asserts:

> "The measure is defined by the formula d_E(x, y) = sqrt((x_1 - y_1)^2 + (x_2 - y_2)^2)"

This is two-dimensional only, so it is not the definition of Euclidean distance. It was abstracted
from item 0017, which is a worked example between two specific points and is labelled `d_max`:

```
d_max = d_E(p_2, p_6) = sqrt((2 - 4)^2 + (5 - 1)^2) = sqrt(20)
```

The draft's own uncertainty note concedes the general form "is not explicitly written out in the
evidence, but is inferred from the 2D worked example".

**The general formula is in the corpus.** It is present, complete and boxed, as evidence item 02
of the **Cosine Similarity** packet:

```
d_Euclidean(x, y) = sqrt( sum_{i=1}^{m} (x_i - y_i)^2 )
```

Checked across `text`, `source_block_text` and `patch_heading` of every item in both packets: zero
occurrences in the Euclidean Distance packet, present in Cosine Similarity's. Both are siblings
under "Similarity and Distance Functions", and the Euclidean packet does draw three other items
from the same source page (110 of the merged guides) - including the **Manhattan** worked example -
but not the boxed Euclidean formula on that page.

This is evidence misrouting between siblings that share a source page, and it produced a
definitional error in a different unit. Stated generically:

> Where a defining equation names its own unit in its function symbol, and that equation is
> admitted to a sibling unit's packet but not to the unit it names, the unit is left to infer its
> definition from a worked example.

The codebase already has a `name_anchored_defining_equation` rescue basis, so the mechanism for
this exists; it did not fire here.

### 2. Group Average Linkage is factually wrong and self-contradictory

> "a weighted version known as WPGMA, where the coefficients ... are **constants independent of
> cluster sizes**, specifically defined by **αA = mA/(mA+mB), αB = mB/(mA+mB)**, β = 0, γ = 0. In
> contrast to the unweighted UPGMA version, which involves the sizes of the clusters being merged..."

The sentence says the coefficients are independent of cluster sizes and then writes coefficients
made of cluster sizes. Those are UPGMA's coefficients; WPGMA's are αA = αB = 1/2.

The cause is upstream. Evidence item 0015 has the formula interleaved into the wrong sentence:

> "the coefficients for UPGMA involve the size, and of each of the clusters, A and B that were
> **m A m B** merged: For the weighted **αA=mA/(mA+mB), αB=mB/(mA+mB), β=0, γ=0** version of group
> average - known as WPGMA - the coefficients are constants that are independent of the cluster
> sizes:"

The trailing colon is a lead-in whose payload never arrived. INT-6 flags this contradiction, which
is the intervention working exactly as specified - but INT-6 is flag-only, so the wrong text ships.

### 3. Bayes' Theorem has no Bayes' theorem, and a foreign formula stands in its place

The packet points at the theorem six times and never delivers it:

```
0025  "Bayes theorem can be briefly described as follows."
0026  "...leads to Equation 4.11, which is known as Bayes theorem:"
0027  "4.11, which is known as Bayes theorem:"
0029  "Using the Bayes Theorem, we can"
0034  "By Bayes' theorem, we have"
0010  "...we can represent the posterior probability as P(y|x)"        (formula severed)
0028  "Bayes theorem provides a relationship between the conditional probabilities and ."
```

The only equation in the packet is items 0013/0014, from a different book (data preprocessing,
Chapter 3-4) and a different subject - Bayesian estimation for PPCA:

```
p(θ, X|Y) ∝ p(Y, X|θ) p(θ)
```

The draft presents it, hedged as "a specific formulation provided in the evidence for this
estimation context", and its notes concede the general algebraic form is absent. That is about as
honest as the drafter could be with what it was given, but the resulting unit for one of the most
fundamental concepts in the library carries a PPCA proportionality as its only mathematics.

This is the same lead-in-without-payload class as defect 2, at its most extreme.

### 4. Pessimistic Error Estimate reproduces a mathematically impossible fragment as a result

> "In a worked example, the pessimistic error estimate for a specific tree TL is calculated as
> 0.3 + 2 · 5."

That evaluates to 10.3. An error estimate cannot exceed 1. The expression is a damaged rendering
with a lost denominator, and it reached the draft as a completed calculation rather than being
rejected. The coverage notes repeat it as if valid: "only a worked example (errp(TL) = 0.3 + 2 · 5)".

Damaged math passed the math-damage guards here.

### 5. Density-Connected asserts two things its packet does not contain, and is marked grounded

Status `grounded`, `uncertainty_notes` empty. The draft states:

> "The relationship is symmetric in the sense that if p and q are density-connected, they belong to
> the same cluster..."

Whole-packet search: `symmetric` occurs 0 times, `same cluster` occurs 0 times. Neither statement
appears in the evidence ledger either. Both happen to be true of DBSCAN, and "belongs to the same
cluster" is the business of the sibling unit "DBSCAN Cluster Definition" - but neither is supported
by what this unit was given.

### 6. Evidence meta-commentary leaks into unit text

The K-Means Complexity draft ends with statements about the document rather than about K-means, and
two of its seven ledger claims are of this kind:

- "The K-means algorithm has a time complexity, though the specific value is not fully rendered in
  the provided text."
- "The analysis of the algorithm's space and time complexity follows a detailed consideration of the
  steps in the basic K-means algorithm."

The Misclassification Rate draft does the same ("The source provides a formula ... but the rendering
is incomplete and partially unreadable"). This belongs in `uncertainty_notes`, where it also already
appears. A Knowledge Library unit consumed downstream for dialogue segmentation should describe the
concept, not narrate the condition of its sources.

## The structural finding: the ledger does not cover the body, and INT-2 only sees the ledger

STEP 3 tells the model to fill `evidence_map` first and STEP 4 says to write "using only claims that
appear in evidence_map". Nothing enforces the second instruction, and the drafts show body prose
exceeding the ledger in both directions:

- Silhouette Coefficient: the sentence about subclusters giving "only a coarse view of the cluster
  structure" has no ledger entry. It is source-supported (the packet does contain the subcluster
  passage), so this is an accounting gap, not a fabrication.
- Density-Connected: the two unsupported statements in defect 5 are likewise unledgered.

INT-2 verifies entailment per ledger entry, against that entry's `evidence_ids`. **A body sentence
that never entered the ledger is therefore invisible to INT-2.** The verifier's coverage is bounded
by the model's own honesty about what it claimed, which is the one thing a verifier should not
depend on.

This is generic, domain-agnostic, and directly measurable: segment the draft body into sentences and
check how many are covered by a ledger entry. It is the highest-value remaining reliability gap I
found, and it is orthogonal to retrieval quality.

## What is working, evidenced

- **Refusal of damaged math where the guards did fire.** AUC declined to state
  `AUC = number of correctly ranked positive-negative pairs` because the denominator was severed,
  and said so. Ensemble Classifier declined two garbled formulas. This is the intended behaviour and
  it is the direct cause of those units being `partial`.
- **INT-1 is visibly reaching the drafter.** The Misclassification Rate notes reason explicitly
  about the flag: "evidence items 0012, 0013, and 0014 are marked as not_assertable_interrogative,
  posing questions about calculating the rate rather than stating the method as fact."
- **INT-7's recovered formulas landed in the text.** Spearman carries `r_s = ρ(R(X), R(Y))`; Recall
  carries `Sensitivity = TP/(TP+FN)`.
- **Difficult renderings reconstructed correctly.** Shannon Entropy recovered
  `Entropy = −Σ_{i=0}^{c−1} p_i(t) log_2 p_i(t)` and read the mangled "1020" as 10/20 to get
  entropy 1 for a 50-50 node. Silhouette transcribed all five of its formulas faithfully.
- **Misconception discrimination.** The Naive Independence Assumption packet contains both a
  student misconception in quotes ("Naive Bayes assumes the features are independent.") and its
  correction. The draft used the correction.
- **Rival discrimination.** Recall ignored the cluster-external `recall(i,j)=mij/mj`.
  Density-Connected ignored the bisecting-K-means centroids and SSE values sharing its source page -
  the cross-branch admission flagged during the INT-7 audit did not contaminate the draft.
- **Abstentions are correct.** Friedman, Nemenyi, RMSE and MAE for Ordinal Targets each have zero
  evidence passages, `insufficient_support`, empty text, and notes correctly scoped to the packet
  rather than claiming the corpus lacks the concept.

## Ranking for repair

1. Lead-in admitted without its payload (defects 2 and 3) - already identified in doc 48 as the
   top candidate; these two cases raise its severity considerably.
2. Body-not-covered-by-ledger, which bounds INT-2's reach (structural finding).
3. Defining equation routed to a sibling that shares a source page (defect 1).
4. Damaged math surviving the guards (defect 4).
5. Meta-commentary in unit text (defect 6) - cosmetic by comparison, but it degrades every
   downstream consumer of the unit.

None of these requires domain knowledge, KC-specific rules, or comparator imitation to state.
