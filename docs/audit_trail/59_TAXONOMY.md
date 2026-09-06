# 59. Detecting a hierarchy parent that groups children the source keeps apart

Some content errors are not pipeline errors. This is the detector for the ones that are not, so
that a taxonomy defect gets reported as one instead of surfacing later as a mysterious drafting
failure.

## The case that motivated it

An external review of r3 found that Sequential Forward Generation and Sequential Backward
Generation are drafted as heuristic search **strategies**, when the chapter treats them as search
**directions**, a different dimension; and that Non-Deterministic Search is partly defined through
random choice of direction, which belongs to Random Generation.

The hierarchy explains all three at once. Every one of these is a child of a single parent:

```
Data Mining > Data Engineering > Feature Selection > Feature Set Generation Algorithms
    Bidirectional Generation (BG)          direction
    Random Generation (RG)                 direction
    Sequential Backward Generation (SBG)   direction
    Sequential Forward Generation (SFG)    direction
    Exhaustive Search                      strategy
    Heuristic Search                       strategy
    Non-Deterministic Search               strategy
```

The source does not present them that way. `7.2.1.1 Search Directions` carries SFG, SBG and BG;
`7.2.2 Selection Criteria` and `7.4 Description of the Most Representative Feature Selection
Methods` carry Exhaustive and Heuristic Search. Two dimensions, two sections.

Presented as peers, seven concepts read as seven alternatives of one kind. A drafter that calls
SFG "a heuristic method" is being faithful to the hierarchy it was handed. No retrieval change and
no drafting change can fix this: the units are siblings by construction, and the pipeline is being
asked to distinguish things the taxonomy says are the same kind of thing.

That makes it worth **detecting** rather than repairing.

## The rule

`_taxonomy/diag_taxonomy_conflation.py`. For each hierarchy parent, take its children's admitted
evidence, keep the section headings that account for at least a quarter of a child's passages,
and link two children when they share such a heading. Report parents whose children fall into two
or more disjoint groups of at least two.

It uses the hierarchy and the documents' own section numbering, nothing else. No subject matter,
no unit list, no thresholds tuned to an outcome.

Headings have to be filtered first: the `patch_heading` field also carries bibliography entries
("[535] A. K. Jain. Data clustering: 50 years beyond K-means") and mid-sentence fragments, so only
a numbered heading of at most 90 characters counts.

## What it reports, and how well

Two parents flagged out of 23.

```
Data Mining > Data Engineering > Feature Selection > Feature Set Generation Algorithms
  group 1  Bidirectional Generation (BG)         7.2.1.1 Search Directions
           Sequential Forward Generation (SFG)   7.2.1.1 Search Directions
  group 2  Random Generation (RG)                5.3 SBG: ...; 7.2 Perspectives
           Sequential Backward Generation (SBG)  5.3 SBG: Sequential Backward Generation
  group 3  Heuristic Search                      7.4 Description of the Most Representative ...
           Non-Deterministic Search              7.4 Description of the Most Representative ...
```

The real split is groups 1+2 (directions) against group 3 (strategies), which is exactly the
finding. The over-split of the directions into two groups is a limitation: SBG's evidence comes
mostly from the guide document and SFG's from the textbook, so they share no heading string even
though they share a dimension. The detector separates by section, and a section is per document.

The second flag is a false positive:

```
Data Mining > Clustering > Similarity and Distance Functions
  group 1  Euclidean Distance, Properties of a Distance Function
           dominated by "10.2 Modeling Null and Alternative Distributions"
  group 2  Cosine Similarity, Manhattan Distance
           dominated by "3 Question 3: Manhattan Distance, Euclidean ... and Cosine Similarity"
```

Group 1's heading is simply wrong for those units; it is a heading-assignment defect, not a
dimension split.

So: **2 flags, 1 real, 1 false, on 23 parents.** That is a screening report for a human to read,
not a gate, and it should be described as one. Its value is that the real flag is the case an
expert reviewer found by reading 159 drafts against three textbooks, and the detector found it
from the hierarchy and the section numbers alone.

## Known limitations

- Only 49 of 158 units have any dominant numbered section heading, so most of the hierarchy is
  invisible to it. Coverage is bounded by extraction quality, not by the rule.
- Splitting by heading string means the same dimension described in two documents splits into two
  groups. Grouping by document first, then comparing across documents, would fix that and is the
  obvious next version.
- It cannot say which group is the "right" one, only that the parent mixes two.

## What to do with the finding

The recommendation for this corpus is concrete and checkable against the source: split
`Feature Set Generation Algorithms` into a directions parent (SFG, SBG, BG, RG) and a strategies
parent (Exhaustive, Heuristic, Non-Deterministic), matching `7.2.1.1 Search Directions` and
`7.2.2 Selection Criteria`. That is a taxonomy edit, made by whoever owns the hierarchy. It is not
a pipeline change and should not be attempted as one.
