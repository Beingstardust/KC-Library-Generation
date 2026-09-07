"""Build the persistent failure register from the human review of the v23 gemma4 run.

One row per defective output, carrying the reviewer's finding verbatim-in-substance, what the
source actually supports, and probe terms that decide mechanically whether the needed content was
in the evidence pack at all. That last field is the important one: it separates a retrieval failure
(right content never retrieved) from a drafting failure (right content retrieved, composed wrong),
and those need completely different fixes.

Row numbers are the reviewer's, 1-indexed into kc_drafts.jsonl; kc_id/canonical_name/status are
resolved from the actual file rather than transcribed, so a mis-transcription cannot silently
misattribute a finding. Verified on 8 spot-checked rows before writing this.

    probes_expected : text that SHOULD be in evidence if retrieval served this KC correctly
    probes_wrong    : text whose presence indicates wrong-sense/sibling contamination
"""
import io
import json
import os

MIR = '/path/to/kc_l'
DATA = os.path.join(MIR, 'data/v3/runs/v3_20260812')
OUT_DIR = os.path.join(MIR, 'v3', 'evaluation')

# (row, reviewer_finding, source_expects, probes_expected, probes_wrong, first_pass_category)
FINDINGS = [
    # ---- A. Classification foundations ----
    (1, "Centred on a narrow feature-selection/probabilistic-training reading rather than the general classification learning phase.",
     "The inductive stage in which a classification model is constructed from training data.",
     ["inductive", "model is constructed", "learning phase"], ["P(x|y)", "feature selection"], "wrong_sense"),
    (2, "Describes repeatedly selecting a search strategy until convergence; not the classification-side counterpart of the learning phase.",
     "The deductive/prediction stage in which the learned classifier is applied to new instances.",
     ["deductive", "applied to", "predict"], ["search strategy", "converges"], "wrong_neighbourhood"),
    (5, "Defines mutually exclusive RULES (no two rules fire for one instance); the KC is mutually exclusive CLASSES.",
     "Classes are mutually exclusive when an instance belongs to exactly one class.",
     ["class", "exactly one class", "belong"], ["rule set", "mutually exclusive rules"], "wrong_sense"),

    # ---- B. Decision trees ----
    (9, "Presents recursive expansion until all leaves are pure as a universal property of decision-tree learning.",
     "Impurity measures class mixedness at a node; unrestricted growth-to-purity is one regime, not universal (pruning/prepruning).",
     ["impurity", "node"], ["until every leaf is pure", "all leaves are pure"], "overgeneralisation"),
    (10, "Defines node misclassification rate via the MINORITY class count over node total - assumes binary.",
     "Error is the fraction not in the majority class, i.e. 1 - max_i p_i, general over classes.",
     ["majority", "1 -", "max"], ["minority class"], "binary_assumption"),
    (15, "MATH ERROR: defines Split Information as Entropy(Parent) - sum p log p. Split Information is -sum p log p.",
     "GainRatio = InformationGain / SplitInfo, where SplitInfo = -sum_i p_i log2 p_i over branch fractions.",
     ["split information", "-\\sum", "branch"], ["entropy(parent) -"], "math_composition"),
    (16, "Connects ID3 to Hunt + entropy but never gives the operational algorithm.",
     "Greedy top-down recursive partitioning selecting splits by an information-based criterion.",
     ["greedy", "recursive", "top-down", "information gain"], [], "incomplete_mechanism"),
    (17, "Defines a multivariate/oblique split (several attributes in one condition); the KC is multiway splitting.",
     "A multiway split produces more than two branches from one attribute test.",
     ["multiway", "more than two", "number of partitions"], ["oblique", "multivariate"], "wrong_sense"),
    (19, "Dominated by generic discretisation/binning rather than the decision-tree continuous-split mechanism.",
     "Binary split A < v, or several mutually exclusive value ranges for a multiway split.",
     ["A < v", "split point", "test condition"], ["discretization", "binning"], "wrong_sense"),

    # ---- C. Bayes ----
    (25, "Describes prior/likelihood/posterior in prose but never states the theorem.",
     "P(Y|X) = P(X|Y)P(Y) / P(X).",
     ["P(Y|X)", "P(X|Y)P(Y)", "bayes theorem"], [], "missing_formula"),
    (30, "Explains probability computation but stops short of the classification decision.",
     "Assign the instance to the class maximising the posterior / NB score.",
     ["argmax", "largest", "maximum posterior", "assign"], [], "incomplete_mechanism"),
    (33, "Names the Gaussian density without the class-conditioned parameterisation.",
     "Per-class, per-attribute Gaussian with mean and variance estimated from training data.",
     ["mean", "variance", "class-conditional", "estimated"], [], "incomplete_mechanism"),
    (34, "Discusses sample mean/variance as Gaussian estimates but never defines either quantity.",
     "Sample mean = sum x_i / n; sample variance = sum (x_i - xbar)^2 / (n-1).",
     ["sample mean", "sample variance", "x_i", "n-1"], [], "missing_formula"),

    # ---- D. Evaluation, cost, statistical comparison ----
    (42, "CROSS-KC: defines the cluster-class external F-measure under a Classifier Evaluation Basics KC (row 123 is the external one).",
     "Harmonic mean of precision and recall for classifier evaluation.",
     ["harmonic mean", "2PR", "F1"], ["cluster", "hierarchical clustering", "external"], "sibling_leak"),
    (45, "Generic confusion-matrix material; uses clustering language ('clusters'); no multiclass row/column structure.",
     "Rows/columns over multiple actual vs predicted classes, generalising the binary matrix.",
     ["multiclass", "rows", "columns", "actual", "predicted"], ["cluster"], "incomplete_mechanism"),
    (59, "Says a cost matrix represents costs but never defines what an entry means.",
     "Entry C(i,j) = cost of predicting class j when the true class is i.",
     ["cost of predicting", "actual class", "C(i,j)"], [], "incomplete_mechanism"),
    (60, "Descriptive about unequal costs; missing the decision principle.",
     "Choose predictions minimising expected cost rather than maximising accuracy.",
     ["minimiz", "expected cost"], [], "incomplete_mechanism"),
    (61, "Z-test contamination gone (real improvement) but the RIPPER mechanism is still absent.",
     "Sequential covering: grow rule, prune, one class at a time, remove covered instances.",
     ["sequential covering", "grow", "prune", "remove"], ["hypothesis test", "critical value"], "under_retrieval"),
    (64, "Establishes the setup but never performs the comparison.",
     "Compare via d = e1 - e2 with a confidence interval / uncertainty on d.",
     ["d =", "difference", "confidence interval"], [], "incomplete_mechanism"),
    (69, "Improved from abstention to attempt, but misses the statistical consequence.",
     "Larger test set reduces sampling uncertainty / standard error, narrowing confidence intervals.",
     ["standard error", "confidence interval", "variance", "uncertainty"], [], "incomplete_mechanism"),
    (74, "F1 is in the KC name but never defined; threshold/tradeoff effect not explained.",
     "F1 = harmonic mean of precision and recall; raising the threshold trades recall for precision.",
     ["harmonic mean", "F1", "threshold"], [], "missing_formula"),
    (75, "Reduces to 'pick the lowest expected cost'; omits the ROC relationship.",
     "Expected cost of an operating point from TPR, FPR, class priors and the cost matrix.",
     ["true positive rate", "false positive rate", "prior", "cost matrix"], [], "incomplete_mechanism"),

    # ---- E. Classification vs clustering, proximity ----
    (79, "Never states the fundamental distinction.",
     "Classification uses predefined class labels; clustering finds structure without supplied labels.",
     ["predefined", "class label", "without", "unsupervised"], [], "incomplete_mechanism"),
    (80, "Mentions zero-distance-iff-identical but omits the metric properties.",
     "Non-negativity, identity of indiscernibles, symmetry, triangle inequality.",
     ["symmetry", "triangle inequality", "non-negativ"], [], "incomplete_mechanism"),
    (82, "MATH: displays sum of squares as the distance (sqrt only in prose). ALSO calls Euclidean an instance of a Bregman-divergence clustering algorithm.",
     "d(x,y) = sqrt(sum_i (x_i - y_i)^2).",
     ["square root", "sqrt", "\\sqrt"], ["bregman"], "math_composition"),
    (84, "Says cosine similarity belongs to the Bregman-divergence class.",
     "cos(x,y) = x.y / (||x|| ||y||); a similarity, unrelated to Bregman divergences here.",
     ["dot product", "magnitude", "norm"], ["bregman"], "sibling_leak"),
    (88, "Identifies K-means and its objective but omits the algorithmic cycle.",
     "Assign points to nearest centroid, recompute centroids, repeat to convergence.",
     ["assign", "nearest", "recompute", "repeat", "until"], [], "incomplete_mechanism"),
    (91, "Discusses initialisation mainly via SOM, then outliers/SSE.",
     "Different initial centroids give different local optima / SSE; hence multiple restarts.",
     ["local", "different initial", "multiple runs", "restart"], ["SOM", "self-organizing"], "wrong_sense"),
    (98, "Identifies Complete Link as CLIQUE - a false alias.",
     "Complete linkage: inter-cluster distance = maximum pairwise distance.",
     ["maximum", "farthest", "complete link"], ["CLIQUE"], "false_alias"),
    (101, "Inserts Jarvis-Patrick complexity into hierarchical-clustering complexity.",
     "Hierarchical clustering is O(m^2 log m) time, O(m^2) space.",
     ["O(m", "m2", "space"], ["jarvis", "patrick"], "sibling_leak"),
    (102, "Standard DBSCAN core point mixed with SNN density.",
     "Core point: at least MinPts points within its Eps-neighbourhood.",
     ["MinPts", "Eps", "neighborhood"], ["SNN", "shared nearest neighbor"], "sibling_leak"),
    (105, "Says the core decision can involve SNN similarity; conflates DBSCAN with an SNN variant.",
     "Eps = neighbourhood radius; MinPts = minimum count for core status.",
     ["Eps", "MinPts", "radius"], ["SNN", "shared nearest neighbor"], "sibling_leak"),
    (108, "Correct core definition then imports other local-density/attractor machinery.",
     "Two points are density-connected if both are density-reachable from a common core point.",
     ["density-connected", "density-reachable", "core point"], ["attractor", "DENCLUE"], "sibling_leak"),

    # ---- F. Cluster quality and validation ----
    (112, "Says SSE equals average pairwise DISTANCE; the identity uses squared distances.",
     "SSE relates to pairwise SQUARED distances, normalised by cluster size.",
     ["squared", "pairwise"], [], "math_composition"),
    (113, "Long m_i^2 derivation does not preserve the source's size normalisation between centroid SSE and pairwise squared distances.",
     "Cohesion via within-cluster proximities or centroid distance, with correct 1/m_i normalisation.",
     ["cohesion", "within cluster", "proximity"], [], "math_composition"),
    (114, "separation(Y) and angular-separation formulas are garbled with unexplained notation.",
     "Separation via prototype-to-prototype distance or cross-cluster proximity.",
     ["separation", "between cluster", "prototype"], [], "math_composition"),
    (117, "Calling it an alternative randomisation approach does not explain the mechanism.",
     "Randomise labels, recompute the external index, build a null distribution, compare the observed value.",
     ["randomiz", "null distribution", "labels"], [], "under_retrieval"),
    (118, "Gives binary class entropy -p+log p+ -p-log p-; the KC is the clustering external index.",
     "Per-cluster entropy over the class distribution, aggregated weighted by cluster size.",
     ["cluster", "weighted", "m_i", "size"], ["p+", "p-"], "wrong_sense"),
    (119, "Identifies purity as an external measure but never gives the calculation.",
     "Majority-class fraction per cluster, aggregated across clusters.",
     ["majority", "max", "fraction"], [], "incomplete_mechanism"),
    (121, "Gives binary-classification TP/(TP+FP); the KC is the cluster-class external index.",
     "precision(i,j) = m_ij / m_i - overlap of cluster i with class j over cluster i size.",
     ["m_ij", "cluster i", "overlap"], ["TP", "FP"], "wrong_sense"),
    (122, "Never cleanly defines external cluster/class recall.",
     "recall(i,j) = m_ij / m_j - overlap over class j size.",
     ["m_ij", "class j", "overlap"], ["TP", "FN"], "wrong_sense"),

    # ---- G. Feature selection and statistics ----
    (141, "Does not adequately explain the parallel forward/backward mechanism.",
     "SFG and SBG run in parallel, stopping when either finds a satisfactory subset or they meet.",
     ["parallel", "SFG", "SBG", "stops"], [], "context_stripped"),
    (143, "Says exhaustive search can combine with 'random search'; the source separates these.",
     "Exhaustive covers the complete subset space and alone guarantees the optimum.",
     ["complete", "guarantee", "optimal"], ["random search", "non-deterministic"], "source_contradiction"),
    (145, "Says the search starts 'in a random direction' with heuristics; alters the definition.",
     "The next subset is generated RANDOMLY rather than by a deterministic direction.",
     ["randomly", "next subset"], ["direction", "heuristic"], "wrong_sense"),
    (147, "Identifies linear association but never defines the coefficient or its range.",
     "Normalised covariance / centred products, ranging over [-1, 1].",
     ["covariance", "standard deviation", "-1", "+1"], [], "missing_formula"),
    (149, "Identifies ranked data/monotonic association but omits the construction.",
     "Convert observations to ranks, then compute Pearson correlation on the ranks.",
     ["rank", "pearson"], [], "incomplete_mechanism"),
    (152, "Mixes generic filtering/preprocessing with efficiency; misses the defining property.",
     "Features evaluated independently of the downstream learning algorithm (vs wrapper).",
     ["independent", "learning algorithm", "wrapper"], ["preprocessing", "noise"], "wrong_sense"),
    (153, "Says Ranker is a filter subcategory; omits the mechanism.",
     "Score each feature, order by score, retain by threshold or count.",
     ["score", "rank", "order", "threshold"], [], "incomplete_mechanism"),

    # ---- Unjustified abstentions ----
    (29, "UNJUSTIFIED ABSTENTION: the corpus supports the NB learning phase directly.",
     "Estimate class priors and class-conditional probabilities from training data.",
     ["prior", "conditional probability", "estimate", "training"], [], "abstention_unjustified"),
    (36, "UNJUSTIFIED ABSTENTION: corpus covers training, validation/model selection and final evaluation.",
     "Train, select/validate, then evaluate once on held-out data.",
     ["training set", "validation", "test set"], [], "abstention_unjustified"),
    (116, "UNJUSTIFIED ABSTENTION: the source gives a concrete randomisation procedure.",
     "Generate random datasets, cluster with K-means, build an SSE null distribution, compare.",
     ["random", "SSE", "distribution", "compare"], [], "abstention_unjustified"),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    drafts = []
    with io.open(os.path.join(DATA, 'drafts/kc_drafts.jsonl'), encoding='utf-8') as f:
        for line in f:
            drafts.append(json.loads(line))

    rows = []
    for row_no, finding, expects, p_exp, p_wrong, cat in FINDINGS:
        d = drafts[row_no - 1]
        draft = d.get('draft')
        if isinstance(draft, str):
            try:
                draft = json.loads(draft)
            except Exception:
                draft = {}
        inner = (draft or {}).get('contextual_kc_draft', draft) or {}
        rows.append({
            'row': row_no,
            'kc_id': d.get('kc_id') or d.get('knowledge_unit_id'),
            'canonical_name': d.get('canonical_name'),
            'machine_status': inner.get('status'),
            'reviewer_finding': finding,
            'source_expects': expects,
            'probes_expected': p_exp,
            'probes_wrong': p_wrong,
            'first_pass_category': cat,
            'evidence_diagnosis': None,
            'root_cause': None,
            'cluster': None,
        })

    out = os.path.join(OUT_DIR, 'failure_register.jsonl')
    with io.open(out, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print('wrote %s (%d failures)' % (out, len(rows)))
    from collections import Counter
    for cat, n in Counter(r['first_pass_category'] for r in rows).most_common():
        print('  %-24s %d' % (cat, n))
    print()
    print('machine status of failures:')
    for st, n in Counter(r['machine_status'] for r in rows).most_common():
        print('  %-12s %d' % (st, n))


if __name__ == '__main__':
    main()
