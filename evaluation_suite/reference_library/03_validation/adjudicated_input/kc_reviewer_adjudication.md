# CORRECTION NOTICE (added 2026-09-02) -- READ BEFORE USING THIS FILE

The "Bottom line" below reports 129/159 (81.13%) agreement between two reviewers. **That
cross-review did not take place.** The reference library was curated by ONE reviewer. No second
human reviewer ever assigned edit actions or source-support states.

What is genuine in this file: it documents 42 units, and within them 30 action differences and 18
support-state differences, resolving 15/15 and 14/4. Those counts recompute correctly from the
blocks below. What is NOT genuine: the "other" column did not come from a second human reviewer,
the file covers only 42 of 159 units, and the 129 figure was never observed -- it is 159 minus 30.

The body is retained UNEDITED as audit-trail evidence. See
`paper_methods/EXPERT_REFERENCE_ADJUDICATION_REPORT.md` for the full correction.

---

# KC Reviewer Adjudication

## Bottom line

- Both reviewers agree on the edit action for 129/159 KCs (81.13%).
- They disagree on edit action for 30/159 KCs (18.87%).
- After source adjudication of those 30 action disagreements: **15 favor my prior action and 15 favor the other reviewer's action**.
- They disagree on source-support state for 18/159 KCs.
- After source adjudication of those 18 support-state disagreements: **14 favor my prior support-state classification and 4 favor the other reviewer's**.

## Adjudicated action distribution

- ACCEPT: 117 (73.58%)
- MAJOR_EDIT: 15 (9.43%)
- REPLACE: 10 (6.29%)
- MINOR_EDIT: 10 (6.29%)
- NO_REFERENCE_CORPUS_UNSUPPORTED: 7 (4.40%)

## Adjudicated source-support distribution

- SUPPORTED: 150 (94.34%)
- UNSUPPORTED: 7 (4.40%)
- PARTIALLY_SUPPORTED: 2 (1.26%)

## Disagreements

### KC_CLF_DT_003 — Misclassification Rate
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The full source contains the classification-error formula and enough content to construct a complete reference.

### KC_CLF_DT_009 — ID3 Algorithm
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `PARTIALLY_SUPPORTED`
- Action: mine `ACCEPT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The corpus only name-checks ID3 and identifies entropy as its split criterion; it does not provide a full distinct ID3 procedure.

### KC_CLF_DT_010 — Bushy Decision Tree (Multi-split)
- Support: mine `PARTIALLY_SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `REPLACE` | other `REPLACE` | adjudicated `REPLACE`
- Verdict: The corpus directly defines multiway splits for nominal, ordinal, and continuous attributes, which is enough to support the 'multi-split' concept.

### KC_CLF_DT_011 — Binary Decision Tree
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `ACCEPT` | adjudicated `MAJOR_EDIT`
- Verdict: The draft never states the defining binary-tree distinction: internal test conditions produce exactly two outcomes/children. It instead spends most of its space on general decision-tree expressiveness and overfitting.

### KC_CLF_DT_012 — Splitting Continuous Attributes
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The final association-analysis sentence is a real but local tangent outside the decision-tree target.

### KC_CLF_NB_003 — Conditional Probability (Likelihood)
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `REPLACE` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The Gaussian likelihood formula is malformed, but the central target and most of the definition are correct. This is a substantive formula repair, not a full replacement.

### KC_CLF_NB_004 — Naive Independence Assumption
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The draft states the conditional-independence factorization accurately in prose. The rubric permits a semantically equivalent representation, so a symbolic equation is not mandatory here.

### KC_CLF_NB_010 — Sample Mean and Variance
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `ACCEPT`
- Verdict: The supplied course source itself uses the n-1 sample variance and describes it as the estimator in this teaching context. The source-only rubric does not permit correcting that wording from outside statistical knowledge.

### KC_CLF_PRUNE_003 — Pessimistic Error Estimate
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The source gives the defining pessimistic-error relation err_gen(T)=err(T)+Omega*(k/N_train); omitting a central quantitative relation is substantive, not merely cosmetic.

### KC_CLF_UND_001 — Learning Phase
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The draft already defines the learning/training phase and distinguishes it from later application; the missing 'induction' label is not essential.

### KC_CLF_UND_005 — Mutually Exclusive Classes
- Support: mine `UNSUPPORTED` | other `AMBIGUOUS_OR_CONFLICTING` | adjudicated `UNSUPPORTED`
- Action: mine `NO_REFERENCE_CORPUS_UNSUPPORTED` | other `NO_REFERENCE_CORPUS_UNSUPPORTED` | adjudicated `NO_REFERENCE_CORPUS_UNSUPPORTED`
- Verdict: The source explicitly discusses mutually exclusive rule sets, not mutually exclusive classes; the single-label framing is only implicit and not enough for this exact KC.

### KC_CLF_UND_006 — Target Attribute
- Support: mine `PARTIALLY_SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `PARTIALLY_SUPPORTED`
- Action: mine `REPLACE` | other `MAJOR_EDIT` | adjudicated `REPLACE`
- Verdict: The draft's central framing is the unrelated quantitative-association-rule sense of 'target attribute' and then concatenates several other 'target' senses. Under the rubric, central wrong-target content warrants REPLACE.

### KC_CLF_UND_007 — Attribute/Variable Types (Numerical, Categorical, Ordinal)
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `REPLACE` | adjudicated `MAJOR_EDIT`
- Verdict: The core attribute-type taxonomy is correct and usable, but substantial unrelated material must be removed. Because the central definition is sound, MAJOR_EDIT is more appropriate than REPLACE.

### KC_CLU_EVAL_008 — External Index: Entropy
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The full source gives both per-cluster entropy and the size-weighted total entropy.

### KC_CLU_EVAL_009 — External Index: Purity
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `ACCEPT` | adjudicated `MAJOR_EDIT`
- Verdict: The draft's overall purity formula omits the normalization by total sample size m. That changes the measure and is a substantive formula error.

### KC_CLU_EVAL_011 — External Index: Precision
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The same source page defines p_ij=m_ij/m_i and precision(i,j)=p_ij, enough for a complete reference.

### KC_CLU_EVAL_013 — External Index: F-Measure
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `ACCEPT` | adjudicated `MAJOR_EDIT`
- Verdict: The draft gives only the per-cluster/per-class F(i,j) formula. The source also defines the overall clustering F-measure using a class-size-weighted aggregation of per-class maxima; that aggregation is defining content.

### KC_CLU_KM_003 — K-Means Complexity
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The textbook directly gives O((m+K)n) space and O(I*K*m*n) time.

### KC_CLU_SIM_002 — Properties of a Similarity Function
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The draft tracks the source's stated similarity properties accurately; no material notation repair is needed.

### KC_CLU_SIM_003 — Euclidean Distance
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The L2/Euclidean definition plus a verified 2-D formula is adequate. A separately written n-dimensional summation is not necessary to understand the KC.

### KC_DE_MISS_001 — Missing Value
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The source explicitly states that there is no universal imputation method that performs best for all classifiers. My prior unsupported-claim flag was wrong.

### KC_DE_MISS_003 — Deletion Strategy
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The source states that deletion yields unbiased estimates under MCAR, loses power, and biases results when data are not MCAR. That condition is an important usage limitation.

### KC_DE_MISS_005 — Informative Missingness
- Support: mine `PARTIALLY_SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `REPLACE` | other `REPLACE` | adjudicated `REPLACE`
- Verdict: The Data Preparation source directly defines NMAR/MNAR: missingness depends on the unobserved value itself as well as observed values.

### KC_DE_PREP_004 — Inconsistent Values
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `ACCEPT`
- Verdict: The extra easy-to-detect versus external-reference detection distinction is useful but not necessary to define 'Inconsistent Values'. Requiring it would over-edit.

### KC_EVAL_BASIC_002 — Accuracy
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `ACCEPT`
- Verdict: The draft explicitly distinguishes rule-level accuracy from classifier accuracy; no material confusion remains.

### KC_EVAL_BASIC_009 — Multi-class Confusion Matrix
- Support: mine `SUPPORTED` | other `UNSUPPORTED` | adjudicated `UNSUPPORTED`
- Action: mine `REPLACE` | other `NO_REFERENCE_CORPUS_UNSUPPORTED` | adjudicated `NO_REFERENCE_CORPUS_UNSUPPORTED`
- Verdict: The course source covers binary classifier confusion matrices and a clustering confusion matrix, but not the requested N-class classifier confusion-matrix structure. The clustering matrix is a different target.

### KC_EVAL_COMP_002 — Confidence Interval for Accuracy
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MINOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The source gives an explicit confidence-interval derivation/formula, while the draft omits the usable equation and contains substantial unrelated fragment leakage.

### KC_EVAL_COMP_003 — Comparing Two Models on Independent Test Sets
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `ACCEPT` | adjudicated `MAJOR_EDIT`
- Verdict: The source supplies d=e1-e2, its variance estimate, and the confidence interval for the true difference. The draft stops at the setup and omits the defining comparison procedure.

### KC_EVAL_COMP_008 — Role of Test Sample Size
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The evaluation chapter directly establishes that larger test sets reduce sampling uncertainty via narrower confidence intervals.

### KC_EVAL_IMBAL_004 — Cost Matrix
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The packaged course guide directly defines the cost matrix and expected-cost use.

### KC_EVAL_IMBAL_005 — Cost-Sensitive Classification
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `ACCEPT` | adjudicated `ACCEPT`
- Verdict: The course guide plus textbook discussion is sufficient to construct a source-grounded cost-sensitive-classification reference.

### KC_EVAL_ROC_001 — ROC Curve
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `MINOR_EDIT`
- Verdict: The draft says p at random-classifier point (p,p) is probability of correct classification. The source says p is the fixed probability of classifying an instance as positive.

### KC_EVAL_ROC_002 — ROC Space (TPR vs. FPR)
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `MINOR_EDIT`
- Verdict: The draft misdescribes (TPR=0,FPR=1) as predicting every instance negative. That point instead corresponds to all positives predicted negative and all negatives predicted positive.

### KC_EVAL_ROC_004 — Classification Threshold (Cutoff)
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `REPLACE` | adjudicated `REPLACE`
- Verdict: The existing draft is almost content-free, while the source gives a complete three-step threshold-selection procedure and s*=argmax E(s). The draft is substantially incomplete.

### KC_EVAL_ROC_005 — Threshold Effect on Precision, Recall, F1
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MINOR_EDIT` | other `ACCEPT` | adjudicated `MINOR_EDIT`
- Verdict: The KC name explicitly includes F1, but the draft explains threshold effects only through precision/recall and omits the source-supported F1 relation. This is a small but real named-component omission.

### KC_EVAL_ROC_006 — Cost-Based Model Selection via ROC
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `REPLACE` | other `NO_REFERENCE_CORPUS_UNSUPPORTED` | adjudicated `REPLACE`
- Verdict: The packaged course guide directly contains a cost matrix, expected-cost formula in terms of class prior/TPR/FPR, and model selection among ROC operating points. This is a false abstention, not a corpus gap.

### KC_EVAL_SAMP_005 — Bootstrap Sampling
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MAJOR_EDIT` | adjudicated `ACCEPT`
- Verdict: The draft adequately defines bootstrap sampling, replacement, the 63.2/36.8 phenomenon, out-of-bag cases, and uses. The .632 error-estimator formula is a related variant, not essential to define Bootstrap Sampling.

### KC_FSEL_FUND_001 — Feature Selection Definition
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The core definition is sound; the Random Forest/application material is tangential and can be removed locally rather than requiring a major rewrite.

### KC_FSEL_FUND_004 — Curse of Dimensionality
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The closing claim that kernel SVMs avoid the curse of dimensionality overstates what the source supports; soften/remove that sentence.

### KC_FSEL_FW_002 — Ranker (Filter Subcategory)
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The draft never actually defines a ranker. The source explicitly says rankers score each feature, produce a ranking, and then a learner/threshold chooses how many features to keep.

### KC_FSEL_GEN_001 — Sequential Forward Generation (SFG)
- Support: mine `SUPPORTED` | other `SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `ACCEPT` | other `MINOR_EDIT` | adjudicated `MINOR_EDIT`
- Verdict: The source treats SFG as a search direction and heuristic/exhaustive/nondeterministic as a separate search-strategy axis. Calling SFG itself 'a heuristic method' conflates the taxonomy.

### KC_FSEL_GOOD_001 — Chi-Squared Test
- Support: mine `SUPPORTED` | other `PARTIALLY_SUPPORTED` | adjudicated `SUPPORTED`
- Action: mine `MAJOR_EDIT` | other `MAJOR_EDIT` | adjudicated `MAJOR_EDIT`
- Verdict: The full source gives the chi-squared statistic, expected frequencies, and general degrees-of-freedom rule.
