# vNext audit trail

One document per investigation, numbered in reading order. Each records what was measured, what
was changed, and - as often - what was rejected and why. A rejected intervention is kept here
deliberately: without the measurement that killed it, the same idea comes back.

The code changes themselves are in git, and every `INT-nn` commit message carries its own A/B
numbers, sabotage results and suite delta. These documents carry the reasoning around them.

## Reading order

```
48  Why grounded appeared to fall and partial to rise        a status shift that was an artefact
49  Semantic correctness of the final drafts, read against source
50  Semantic assessment of all 159 KC drafts
51  INT-11  repair a damaged formula from an intact twin
52  INT-12  draft hygiene checks
53  D2 symbol binding                                        REJECTED on measurement
54  Final state after INT-11 and INT-12
55  INT-13  two content repairs existed and had never once executed
56  INT-14  a well-formed repair can be worse than the abstention it replaced
57  INT-15  one payload branch of three did nothing when the reranker got there first
58  Reconciling an external content review of r3 against this audit
59  Detecting a hierarchy parent that groups children the source keeps apart
60  INT-16  a formula is admitted with the sentence that says what its symbols mean
61  Evidence ownership: where the failure actually happens
62  INT-17  "grounded" answers a different question than the reader thinks
63  INT-18/19  provenance, and whether the draft is about the unit
64  Categories A and C: what the literature offers, and what survives the constraints
65  Running the verify suite on Cluster A when Cluster B is saturated
66  The taxonomy split, applied
67  INT-20  the defining-equation rescue could not read its own corpus
68  Reproducibility of the packet build, and a noise floor I had been quoting wrongly
69  Mutually Exclusive Classes as a negative control the pipeline fails
70  INT-21  the defining-equation rescue reads through LaTeX formatting commands
71  INT-22/22b  prose with another sentence's mathematics spliced through it
72  Final state: r7
73  R8 assessment inventory, independent measurements, accepted/rejected hypotheses
```

## Where to start

For the shipped r7 result and its remaining ceilings, read **72**. For the post-r7 assessment and
the independently verified r8 decisions, read **73**.
For how a claim in this audit is allowed to be made, read **68** - it establishes that the build's
noise floor is zero, which is what makes every A/B delta elsewhere readable.
For the methodology, read **56** and **70**: a guard whose fixture does not need the mechanism it
names will pass without it, and only sabotage finds that.

## Standing rules this trail established

- A fix is not shippable because it is precise. It is shippable because the thing it does with what
  it finds is better than doing nothing (58, 71).
- A substitution is a deletion of whatever only the original carried; check that before shipping,
  not after (71).
- Measure a corpus-level change on whole packets, not on admitted text - the BM25 index moves
  globally (71, 72).
- Break every guard and require the TARGETING guard to fail. Restore byte-exact, and never cancel a
  sabotage run without verifying the tree.
