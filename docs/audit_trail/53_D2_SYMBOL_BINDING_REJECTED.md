# 53. D2 symbol binding: rejected on measurement

Doc 50 recorded three verified cases where a unit's own defining formula sits in a sibling's
packet and nowhere else:

| unit missing it | where it actually is |
|---|---|
| `Euclidean Distance` | `Cosine Similarity`, boxed and complete |
| `Chi-Squared Test` | `Redundant Attributes`, with every symbol defined |
| `External Index: Precision` | `External Index: Purity`, which defines `p_ij` |

## The hypothesis

`defining_equation_patterns()` matches `<unit name> =` - the words of the label, spelled out. The
corpus routinely writes the same definition with a SYMBOL built from those words instead:
`d_Euclidean(x, y) =`, `GainRatio(A) =`, `SplitInfo(A) =`. Those never match, which would explain
why such an equation can be admitted to a sibling and never to the unit it names.

The proposed rule: a defining equation whose left-hand side contains a distinctive content word of
a unit's label belongs to that unit. Stated without reference to any corpus or unit, and it uses
the equation's own function symbol rather than prose proximity - a stronger signal than any of the
four target-binding attempts that came before it.

## The measurement

Over the 100,218-row corpus and all 159 units, with label words filtered against a structural
generic-word list (`index`, `measure`, `rate`, `distance`, ... - words that appear in many labels
at once and therefore identify nothing):

```
variant                                    scanned  claimed  contested        unique  missing
broad (any row containing "=")                3889     1164   777  (67%)         387      345
+ overlay says is_formula_like                3889     1164   777  (67%)         387      345
+ short symbolic head                         3322      688   377  (55%)         311      269
+ symbolic right-hand side (narrowest)        2601      513   267  (52%)         246      213
```

"Contested" means the same equation is claimed by more than one unit, so any rule acting on this
signal would have to pick one and would be wrong for the others.

## Why this is a rejection

**Even at its narrowest, the signal is ambiguous for more than half the equations it fires on.**
267 of 513. That is a coin flip, and it is not the kind of ambiguity a tie-break resolves: it is
inherent, because sibling units in this taxonomy share label words by construction
(`External Index: Precision` / `External Index: Purity`, `MIN (Single Linkage)` /
`MAX (Complete Linkage)`, `Density-Reachable` / `Directly Density-Reachable`).

Two further findings make the unambiguous remainder unattractive:

1. **The `is_formula_like` filter changes nothing** - 3889 rows before and after. Every row
   carrying an `=` is already flagged, so the overlay's own formula signal cannot separate a
   definition from a sentence containing an equals sign.
2. **The "unique" set is dominated by worked-example steps, not definitions.** 63 of the 213
   remaining rows are claimed by a single unit, `Area Under the ROC Curve (AUC)`, and the ones
   read are intermediate arithmetic:
   ```
   AUC(M1) = (4 - 1) + (7 - 2) + (8 - 3) + (9 - 4) + (10 - 5)
   AUC(M1) = 3 + 5 + 5 + 5 + 5
   AUC(M2) = 0 + 2 + 2 + 3 + 3
   ```
   Admitting these would fill a unit's evidence budget with the steps of one worked calculation.
   The `symbolic right-hand side` filter was added specifically to exclude them and still leaves
   most of them, because `AUC(M1) = 0.920 > AUC(M2) = 0.400` contains letters.

## Status

**Rejected.** This is the fifth distinct failure mode recorded for target binding, and the most
precisely quantified:

1. lexical/n-gram rival revival - revived the wrong rival
2. Hearst-pattern binding - patterns too rare in this corpus
3. generic target-binding heuristics - forbidden by the authorization as untestable
4. anchor preference - shorter rival names structurally win
5. **symbol binding - the signal is 52% ambiguous even at its narrowest**

The three defects in doc 50 remain real and remain unrepaired. What they need is a binding signal
that can distinguish sibling units sharing label words, which neither the equation's symbol nor
its surrounding prose provides. Recorded as a ceiling for this architecture, with the measurement
attached so a future attempt starts from the number rather than the hypothesis.

Reproduction: `_d2/d2_symbol_binding.py` (job 248853) and `_d2/d2_narrow.py` (job 248856), both
via SLURM on partition `short`.

## One correction made during this measurement

The first run of the narrowed variants scanned **zero** rows, because the filter tested
`row.get('shape_tags')` - a PACKET-item field that does not exist on a corpus row, where the
overlay's flag is `is_formula_like`. A filter that silently matches nothing reports a clean
result, so the zero was investigated rather than accepted.
