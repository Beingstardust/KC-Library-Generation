# 66. The taxonomy split, applied

Doc 59 built the detector and recommended the edit. This is the edit, made before the final freeze
because the alternative was freezing a library with a known taxonomy defect in it.

## What changed

```
before   Feature Selection
         └── Feature Set Generation Algorithms
             ├── Sequential Forward Generation (SFG)      direction
             ├── Sequential Backward Generation (SBG)     direction
             ├── Bidirectional Generation (BG)            direction
             ├── Random Generation (RG)                   direction
             ├── Exhaustive Search                        strategy
             ├── Heuristic Search                         strategy
             └── Non-Deterministic Search                 strategy

after    Feature Selection
         ├── Search Directions
         │   ├── Sequential Forward Generation (SFG)
         │   ├── Sequential Backward Generation (SBG)
         │   ├── Bidirectional Generation (BG)
         │   └── Random Generation (RG)
         └── Search Strategies
             ├── Exhaustive Search
             ├── Heuristic Search
             └── Non-Deterministic Search
```

188 nodes to 189: one conflating parent removed, two added. No leaf changes depth, so nothing
downstream that keys on depth sees a new shape.

## Three decisions inside that edit

**Replace the parent rather than nest under it.** Nesting would have kept the old node and added a
level, putting these leaves at depth 6 when every other unit in the library is at 4 or 5. Replacing
keeps the depth and matches the source, which has no section corresponding to "Feature Set
Generation Algorithms" but does have sections for the two groups.

**"Search Strategies", not the source's "Selection Criteria".** 7.2.2 in the source is called
Selection Criteria and carries Exhaustive and Heuristic Search. But this taxonomy already uses
"Goodness Criteria" for the evaluation measures (Chi-Squared, Covariance, Information Gain,
Pearson, Shannon Entropy, Spearman). Reusing "Criteria" would have removed one conflation by
introducing another. "Search Strategies" is the standard term for the dimension and collides with
nothing.

**Node ids from the builder's own scheme, not invented.** `hier_node_id` is
`hier::path::sha256(source_set_id + \x1f + \x1f.join(path))`, found in
`src/kc_l/hierarchy_overlay/builder.py::_make_fallback_hier_node_id` and verified by regenerating
two existing ids before generating any new one. Guessing at the hash would have produced nodes
that look right and are unreachable by anything that recomputes the id.

## The input file is not modified

The edit reads
`kc_l_v2_clean/.../hierarchy_overlay.jsonl` and writes
`data/v3/hierarchy/hierarchy_overlay_taxonomy_split.jsonl`. The original overlay is shared with
other projects and is left byte-identical; the r5 job points at the new file explicitly and refuses
to run if it is missing, and refuses to run if the conflating parent is still present in it.

## Validation

`_taxonomy/split_taxonomy.py` validates its own output before writing: no duplicate node ids, every
`parent_hier_node_id` resolves, every `child_hier_node_ids` entry resolves, and all seven leaves
carry the new parent label in their `source_hierarchy_path`. It also refuses to run if the node's
descendants are not exactly the seven expected units, so it cannot silently do the wrong thing to a
hierarchy that has moved on.

## What this is expected to change, and what it is not

Changed: `sibling_kc_names` and therefore `rival_units_considered` for those seven units, and the
topic packet set (one topic node becomes two, so 22 topic units becomes 23).

Not changed: retrieval for the other 152 units, except where INT-15 and INT-16 act. The r5-vs-r4
comparison reports the two separately for that reason, since one combined total would be
uninterpretable.

**This is not a claim that the drafts will improve.** The review's finding was that SFG is drafted
as a heuristic strategy; whether a corrected sibling set actually changes that depends on the
drafter, and the evidence for those units may be unchanged. The honest prediction is that the
rival sets change, which is checkable directly, and the drafts may or may not follow.
