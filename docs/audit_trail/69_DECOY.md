# 69. Mutually Exclusive Classes as a negative control the pipeline fails

Raised in review: if a unit's concept genuinely is not in the source, while a near-homonym IS,
then that unit is a natural negative control. It tests whether the pipeline abstains on a concept
the corpus does not carry, or reaches for the almost-identically-named one instead. That is a
better use for it than treating it as one more content bug.

The framing is right, and the pipeline fails the control.

## The source insufficiency is genuine

`_decoy/diag_decoy_unit.py` over the corpus:

```
rows mentioning "mutually exclusive" at all : 22
  paired with "class" :  1
  paired with "rule"  : 19
```

The single "class" row is:

> This avoids the problem of having conflicting classes predicted by multiple classification rules
> if the rule set is not mutually exclusive.

which is about rule sets. So the corpus defines mutually exclusive RULE SETS thoroughly - it has a
numbered "Definition 4.1 (Mutually Exclusive Rule ...)" and a worked example table - and defines
mutually exclusive CLASSES nowhere. The correct output for this unit is an abstention.

## What the pipeline does instead

```
packet_support_state          : draftable
abstention_expected           : False
insufficient_synthesis_support: False
support_state_reason          : target_anchored_substantive_passages_available_no_completeness_claim
thin_evidence                 : False   (7 substantive rows)
admitted rows                 : 9, of which 9 mention "rule" and 5 mention "class"
```

and the drafter, given nine substantive rule-set passages and no abstention signal, writes:

> status: **grounded**
> In the context of rule-based classification, a rule set is defined as mutually exclusive if no
> two rules within the set are triggered by the same instance.

True, well-evidenced, and about the wrong concept. This is the case an external content review
called the single most serious remaining error.

## The mechanism

`passage_has_strong_target_anchor` decides whether a packet may be called draftable. Its second
branch:

```python
label_terms = context_content_terms(core)
if label_terms and label_terms.issubset(text_terms):
    return True
```

A passage anchors when the unit's content terms are a SUBSET of its terms, in any positions. The
decoy row carries "classes", "classification", "rules" and "mutually exclusive" across three
clauses, so {mutually, exclusive, class} is a subset and the passage anchors a unit about classes.
Subset membership says nothing about whether the words are syntactically related.

## A fix that was tried and does not work

Requiring the unit's terms to sit within a window of each other. Measured with the real function
(`_decoy/diag_anchor_real.py`, loading the packet builder as a module rather than reimplementing
it - a first attempt that reimplemented it produced a 16-unit blast radius that was an artefact of
normalising only one side before phrase-matching):

```
window +/-8 tokens:  support state unchanged 144, MOVED 11
```

**Mutually Exclusive Classes is not among the 11.** The fix fails on its own motivating case, for a
reason underneath the first: "classification" and "classes" both reduce to the same stem, so the
decoy row satisfies proximity as well - "classification"(5), "mutually"(13), "exclusive"(14) all
fall inside one window.

The 11 that do move are not a good trade either: two gains (Naive Independence Assumption, Laplace
Estimator) against nine losses including Properties of a Distance Function, K-Means Complexity and
External Index: Purity and Recall. A change that misses its target and demotes nine unrelated
units is not worth shipping.

## What does catch it

**INT-19**, at the verification stage:

```
INT-19 flags it: True   defines: "rule set"
```

The draft's definitional subject is "rule set", which shares no term with "Mutually Exclusive
Classes". So the library ships this unit flagged, not silently.

That is the honest status: **the control is failed at the abstention stage and caught at the
verification stage.** A reviewer reading the sidecar sees it; a consumer reading only the status
field sees `grounded` and is misled.

## Why this is worth keeping as a control rather than special-casing

Nothing here should be fixed by teaching the pipeline about classes and rules. The value of the
case is that it is a real instance of a general hazard - a unit whose name differs from a
well-covered neighbour by one word - and it now has a measured answer:

- retrieval finds the neighbour's evidence, correctly, because it is genuinely about
  "mutually exclusive" things
- the support gate accepts it, because subset anchoring cannot tell a phrase from a bag of words
- the drafter uses it, because it was handed nine substantive passages and told the packet is
  draftable
- only a check on the drafted text notices the subject is wrong

Any future work on target binding has this as its test case, with the failure localised to one
branch of one function and a measurement harness that calls the real code.
