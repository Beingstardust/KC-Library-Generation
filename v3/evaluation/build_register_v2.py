"""Cross-reference the second human review against the first, by canonical_name (row numbers
differ between runs since packet content changed). Classifies each problem as:

    PERSISTING  - flagged defective in BOTH reviews
    NEW         - flagged only in the second review (introduced or newly exposed)
    RESOLVED    - flagged in the first review, absent from the second (genuinely fixed)

For persisting/new problems, records whether a shipped fix (v24-v32) targets the underlying
mechanism, based on the root-cause diagnosis already on file for persisting cases and fresh
diagnosis (done directly against the real corpus) for the two new ones.
"""
import io
import json
import os

MIR = '/path/to/kc_l'
REG1_PATH = os.path.join(MIR, 'v3/evaluation/failure_register.jsonl')

# ---- run 2 findings, transcribed from the second human review ----
# (row, canonical_name, mechanism_tag, fix_status, note)
RUN2_PROBLEMS = [
    (1, 'Learning Phase', 'wrong_sense', 'OPEN_NO_RIVAL', 'still collapses into NB-specific P(y)/P(x|y) framing'),
    (2, 'Querying Phase', 'wrong_neighbourhood', 'OPEN_NO_RIVAL', 'still search-strategy language, not deduction/prediction'),
    (5, 'Mutually Exclusive Classes', 'wrong_sense', 'OPEN_NO_RIVAL', 'mutually exclusive RULES is not itself a library unit to lose evidence to'),
    (9, 'Node Impurity', 'overgeneralisation', 'OPEN_DRAFTING', 'recursive-to-purity stated as universal; drafting-completeness issue, not evidence'),
    (10, 'Misclassification Rate', 'binary_assumption+math', 'OPEN_DRAFTING', 'binary-only framing persists AND a new arithmetic error (1/10=0) appeared'),
    (15, 'Gain Ratio', 'math_composition', 'OPEN_CORPUS_LIMIT', 'Split Information rendering has no intact form anywhere in corpus (confirmed v24 cycle)'),
    (16, 'ID3 Algorithm', 'incomplete_mechanism', 'OPEN_DRAFTING', 'still names ingredients, not the greedy top-down mechanism'),
    (17, 'Bushy Decision Tree (Multi-split)', 'wrong_sense', 'OPEN_NO_RIVAL', 'oblique/multivariate split still substituted for multiway split'),
    (19, 'Splitting Continuous Attributes', 'wrong_sense', 'OPEN_NO_RIVAL', 'generic discretization still dominates over A<v mechanism'),
    (25, "Bayes' Theorem", 'missing_formula', 'OPEN_DRAFTING', 'theorem itself still never written out'),
    (30, 'NB Classification Phase', 'incomplete_mechanism', 'OPEN_DRAFTING', 'argmax decision step still missing'),
    (33, 'NB for Numerical Attributes (Gaussian NB)', 'incomplete_mechanism', 'OPEN_DRAFTING', 'class-conditional mean/variance parameterisation still missing'),
    (34, 'Sample Mean and Variance', 'formula_payload', 'FIXED_v25', 'formula payload was being admitted then silently stripped by verify_scorer - now exempted'),
    (42, 'F-Measure', 'sibling_leak', 'PARTIAL_v26', 'has a library rival (External Index: F-Measure) but did not lose the wrong-context passages at current margin'),
    (45, 'Multi-class Confusion Matrix', 'incomplete_mechanism+leak', 'OPEN_DRAFTING', 'row/column structure still unstated; cluster-language leak persists'),
    (59, 'Cost Matrix', 'incomplete_mechanism', 'OPEN_RETRIEVAL', 'evidence itself reported as unusually thin'),
    (61, 'RIPPER Rule Induction', 'under_retrieval', 'OPEN_RETRIEVAL', 'reviewer confirms corpus HAS the sequential-covering mechanism; drafter failed to synthesize it despite it being retrievable'),
    (64, 'Comparing Two Models on Independent Test Sets', 'incomplete_mechanism', 'OPEN_DRAFTING', 'setup stated, comparison (d=e1-e2, CI) still missing'),
    (69, 'Role of Test Sample Size', 'incomplete_mechanism', 'OPEN_DRAFTING', 'representativeness stated, standard-error/CI mechanism still missing'),
    (74, 'Threshold Effect on Precision, Recall, F1', 'missing_formula', 'OPEN_DRAFTING', 'F1 still never defined'),
    (75, 'Cost-Based Model Selection via ROC', 'incomplete_mechanism', 'OPEN_DRAFTING', 'reduced to "pick lowest cost", TPR/FPR/prior relationship still missing'),
    (79, 'Classification vs. Clustering (Distinction)', 'incomplete_mechanism', 'OPEN_DRAFTING', 'the actual distinguishing criterion still unstated'),
    (80, 'Properties of a Distance Function', 'incomplete_mechanism', 'OPEN_DRAFTING', 'only identity property present; symmetry/triangle-inequality/non-negativity still missing'),
    (84, 'Cosine Similarity', 'sibling_leak', 'OPEN_NO_RIVAL', 'Bregman-divergence misclassification persists; Bregman is not a library unit'),
    (88, 'K-Means Algorithm', 'incomplete_mechanism', 'OPEN_DRAFTING', 'assign/recompute/repeat cycle still missing'),
    (91, 'Centroid Initialization Sensitivity', 'wrong_sense', 'OPEN_NO_RIVAL', 'still framed via SOM/outliers rather than initialization-dependent local optima'),
    (95, 'Agglomerative (Bottom-Up) Clustering', 'bibliography_contamination', 'FIXED_v30', 'BIRCH reference-title fragment shattered across pymupdf line-blocks, now rejected as a whole via block-level bibliography check + _VENUE_RE bugfix'),
    (98, 'MAX (Complete Linkage)', 'false_alias', 'OPEN_NO_RIVAL', 'CLIQUE is not a library unit; v27 (foreign-method guard) was built for exactly this and rejected for collateral damage elsewhere'),
    (101, 'Hierarchical Clustering Complexity', 'sibling_leak', 'OPEN_NO_RIVAL', 'Jarvis-Patrick is not a library unit'),
    (102, 'Core Point', 'sibling_leak', 'OPEN_MARGIN', 'has library rivals (Border Point, Noise Point) but SNN-similarity wording not dropped at current margin - see margin sweep'),
    (108, 'Density-Connected', 'sibling_leak', 'OPEN_NO_RIVAL', 'local-density-attractor model is not a library unit'),
    (112, 'SSE (Cluster Quality)', 'math_composition', 'OPEN_DRAFTING', 'squared-distance identity still described as plain distance'),
    (113, 'Cohesion', 'math_composition', 'OPEN_DRAFTING', 'appended algebra still does not preserve the real normalisation'),
    (114, 'Separation', 'math_composition', 'PARTIAL_v24_v29', 'formula variant selection + truncation detection should reduce garbling; unverified against this exact case'),
    (117, 'Models of Randomness (Approach 2)', 'under_retrieval', 'OPEN_RETRIEVAL', 'randomize/recompute/null-distribution mechanism not surfacing'),
    (118, 'External Index: Entropy', 'sibling_leak', 'OPEN_MARGIN', 'has library rivals but binary classification entropy not dropped at current margin - see margin sweep'),
    (119, 'External Index: Purity', 'incomplete_mechanism', 'OPEN_RETRIEVAL', 'majority-fraction-per-cluster calculation not surfacing'),
    (122, 'External Index: Recall', 'incomplete_mechanism', 'OPEN_RETRIEVAL', 'm_ij/m_j calculation not surfacing'),
    (135, 'Feature Selection Definition', 'clause_reversal', 'FIXED_v31', 'pymupdf severs a subordinate clause from its main clause, flipping "bias arises when X" into "X should be done" - now rejected via cross-extractor fragment detection'),
    (141, 'Bidirectional Generation (BG)', 'context_stripped', 'KNOWN_TRADEOFF_v22', 'relational-definition cost of per-member verification, documented in the original v22/v23 commit'),
    (143, 'Exhaustive Search', 'source_contradiction', 'OPEN_DRAFTING', 'the added "combine with random search" claim persists'),
    (145, 'Non-Deterministic Search', 'wrong_sense', 'OPEN_DRAFTING', 'search-direction/generation-strategy/randomness dimensions still conflated'),
    (147, 'Pearson Product-Moment Correlation', 'formula_payload', 'LIKELY_FIXED_v25', 'same lead-in/payload-block shape as Sample Mean and Variance; not individually re-verified post-fix'),
    (149, 'Spearman Rank Correlation', 'incomplete_mechanism', 'OPEN_DRAFTING', 'rank-then-Pearson construction still missing'),
    (152, 'Filter Approach', 'wrong_sense', 'OPEN_DRAFTING', 'generic preprocessing still dominates over independence-from-learner distinction'),
    (153, 'Ranker (Filter Subcategory)', 'incomplete_mechanism', 'OPEN_DRAFTING', 'score/order/select mechanism still missing'),
    # unjustified abstentions
    (29, 'NB Learning Phase', 'abstention_unjustified', 'OPEN_RETRIEVAL', 'persists across both reviews'),
    (36, 'Evaluation Workflow', 'abstention_unjustified', 'OPEN_RETRIEVAL', 'persists across both reviews'),
    (116, 'Models of Randomness (Approach 1)', 'abstention_unjustified', 'OPEN_RETRIEVAL', 'persists across both reviews'),
    (121, 'External Index: Precision', 'abstention_unjustified', 'IMPROVED_v26', 'was confidently-wrong content in run 1; v26 correctly stripped the wrong TP/FP content, converting the failure from contamination to abstention - real progress, not yet a full fix'),
]

reg1 = [json.loads(l) for l in io.open(REG1_PATH, encoding='utf-8') if l.strip()]
run1_names = {r['canonical_name'] for r in reg1}
run2_names = {name for _, name, *_ in RUN2_PROBLEMS}

persisting = sorted(run1_names & run2_names)
resolved = sorted(run1_names - run2_names)
new = sorted(run2_names - run1_names)

print('=' * 100)
print('CROSS-REFERENCE: run 1 (51 problems) vs run 2 (50 problems), by canonical_name')
print('=' * 100)
print('PERSISTING (in both): %d' % len(persisting))
for n in persisting:
    print('   ', n)
print()
print('RESOLVED (run 1 only - genuinely fixed): %d' % len(resolved))
for n in resolved:
    print('   ', n)
print()
print('NEW (run 2 only): %d' % len(new))
for n in new:
    print('   ', n)

print()
print('=' * 100)
print('FIX STATUS BREAKDOWN (run 2 problems)')
print('=' * 100)
from collections import Counter
status_counts = Counter(status for _, _, _, status, _ in RUN2_PROBLEMS)
for status, n in status_counts.most_common():
    print('  %-22s %d' % (status, n))

# write the merged register for the report
out = []
for row, name, mech, status, note in RUN2_PROBLEMS:
    persisted = name in run1_names
    out.append({
        'run2_row': row, 'canonical_name': name, 'mechanism': mech,
        'fix_status': status, 'note': note, 'persisting_from_run1': persisted,
    })
with io.open(os.path.join(MIR, 'v3/evaluation/failure_register_run2.jsonl'), 'w', encoding='utf-8') as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print()
print('wrote v3/evaluation/failure_register_run2.jsonl (%d rows)' % len(out))

# also record resolved units explicitly with their run1 row for the report
resolved_rows = [r for r in reg1 if r['canonical_name'] in resolved]
with io.open(os.path.join(MIR, 'v3/evaluation/resolved_since_run1.jsonl'), 'w', encoding='utf-8') as f:
    for r in resolved_rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print('wrote v3/evaluation/resolved_since_run1.jsonl (%d rows)' % len(resolved_rows))
