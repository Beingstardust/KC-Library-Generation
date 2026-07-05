# Step 6.7A evidence packet snapshot

- Run id: `2026-04-28_130527`
- Packet count: `10`
- Source candidate rows: `2592`
- Source unique KCs: `144`
- Packets: `data/processed/step67_sidecar_packets/2026-04-28_130527/evidence_packets.jsonl`

## KC_CLU_EVAL_001 | Internal Indices Overview

- Topic: `['Data Mining', 'Clustering', 'Cluster Evaluation', 'Internal Indices Overview']`
- Source rows for KC: `18`
- Evidence candidates selected: `5`
  - `E1` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - A transaction data set containing three items, p, q, and r, where $p$ is a high support item and q and r are low support items.
  - `E2` idx=`1` def_score=`13.8` scope_score=`5.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Unsupervised measures are often called internal indices because they use only information present in the data set.
  - `E3` idx=`2` def_score=`13.6` scope_score=`5.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - In this case, Ic is the set of indices of the training examples belonging to class c, and Σ is the covariance of the random variable (z −zi).
  - `E4` idx=`3` def_score=`13.4` scope_score=`3.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Each internal node of the tree uses the following hash function, h(p)=(p−1) mod 3,, where mode refers to the modulo (remainder) operator, to determine which branch of the current node should be followed next.
  - `E5` idx=`5` def_score=`13.0` scope_score=`5.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Alternatively, and this is the focus of measures of clustering tendency, we can try to evaluate whether a data set has clusters without clustering.

## KC_CLU_EVAL_002 | SSE (Cluster Quality)

- Topic: `['Data Mining', 'Clustering', 'Cluster Evaluation', 'SSE (Cluster Quality)']`
- Source rows for KC: `18`
- Evidence candidates selected: `5`
  - `E1` idx=`0` def_score=`14.0` scope_score=`6.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - (This is discussed further in Sections 8.1.2, 8.4.6, and 8.4.8.) As a result, many clustering and classification algorithms (and other data analysis algorithms) have trouble with high-dimensional data leading to reduced classification accuracy and poor quality clusters.
  - `E2` idx=`1` def_score=`13.8` scope_score=`5.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Given two different sets of clusters that are produced by two different runs of Kmeans, we prefer the one with the smallest squared error since this means that the prototypes (centroids) of this clustering are a better representation of the points in their cluster.
  - `E3` idx=`2` def_score=`13.6` scope_score=`3.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - This procedure is guaranteed to find a K-means clustering solution that is optimal to within a factor of , which inO log(k) practice translates into noticeably better clustering results in terms of lower SSE.
  - `E4` idx=`3` def_score=`13.4` scope_score=`3.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Because we are using the K-means algorithm “locally,” i.e., to bisect individual clusters, the final set of clusters does not represent a clustering that is a local minimum with respect to the total SSE.
  - `E5` idx=`5` def_score=`13.0` scope_score=`5.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - While there are many types of fuzzy clustering—indeed, many data analysis algorithms can be “fuzzified”—we only consider the fuzzy version of K-means, which is called fuzzy c-means.

## KC_DE_PREP_003 | Duplicate Tuples

- Topic: `['Data Mining', 'Data Engineering', 'Preparing the Data for Learning', 'Duplicate Tuples']`
- Source rows for KC: `18`
- Evidence candidates selected: `6`
  - `E1` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Describe the potential problems with this algorithm if there are duplicate objects in the data set.
  - `E2` idx=`1` def_score=`13.8` scope_score=`3.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - where $m \ > \ 1$ is the fuzzifier, and $\begin{array} { r c l } { \sum _ { j = 1 } ^ { K } U ( \nu _ { j } , x _ { i } ) } & { = } & { 1 } \end{array}$ for any data object $x _ { i } ( 1 \leq i \leq N )$ .
  - `E3` idx=`2` def_score=`13.6` scope_score=`5.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - where ${ \sf w } ( { \sf k } )$ is the weight parameter associated with the $\bar { I } ^ { \mathrm { t h } }$ input link after the ${ \boldsymbol { k } } ^ { \mathrm { { t h } } }$ iteration, is a parameter known as the learning rate, and is the value λ xij of the j attribute of ...
  - `E4` idx=`17` def_score=`13.6` scope_score=`3.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Having duplicate tuples can be troublesome, not only wasting space and computing time for the DM algorithm, but they can also be a source of inconsistency.
  - `E5` idx=`3` def_score=`13.4` scope_score=`5.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - In the case of itemsets, generation of duplicate candidates is avoided by the use of lexicographic ordering, such that two frequent k-itemsets are merged only if their first items, arranged in lexicographic order, arek−1 identical.
  - `E6` idx=`4` def_score=`13.2` scope_score=`5.2` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Fellegi and Sunter [10] formulated the duplicate instance detection problem as Bayesian inference problem, and thus the Fellegi-Sunter model is the most widely used in probabilistic approaches.

## KC_EVAL_SAMP_003 | k-Fold Cross Validation

- Topic: `['Data Mining', 'Model Evaluation and Model Comparison', 'Sampling for Testing', 'k-Fold Cross Validation']`
- Source rows for KC: `18`
- Evidence candidates selected: `4`
  - `E1` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - , where p(n) is the number(p−n)/(p+n) of positive (negative) examples in the validation set covered by the rule.
  - `E2` idx=`1` def_score=`13.8` scope_score=`5.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Hence, at m\* the end of this algorithm, we obtain the best choice of the hyper-parameter value as well as the final classification model (Step 14), both of which are obtained by making an effective use of every data instance in D.train.
  - `E3` idx=`2` def_score=`13.6` scope_score=`5.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - This approach is called three-fold cross-validation.
  - `E4` idx=`3` def_score=`13.4` scope_score=`5.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - One of the common mistakes while using cross-validation is to perform pre-processing operations (e.g., hyper-parameter tuning or feature selection) using the entire data set and not “within” the training fold of every cross-validation run.

## KC_CLU_DBS_003 | Noise Point

- Topic: `['Data Mining', 'Clustering', 'Density-Based Clustering (DBSCAN)', 'Noise Point']`
- Source rows for KC: `18`
- Evidence candidates selected: `6`
  - `E1` idx=`2` def_score=`15.6` scope_score=`5.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Notice that some of the noise points are‘+’s intermixed with the non-noise points.
  - `E2` idx=`3` def_score=`15.4` scope_score=`5.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - However, for points that are not in a cluster, such as noise points, the k-dist will be relatively large.
  - `E3` idx=`4` def_score=`15.2` scope_score=`5.2` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Notice that some of the noise points are
  - `E4` idx=`5` def_score=`15.0` scope_score=`5.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Naïve Bayes classifiers are robust to isolated noise points because
  - `E5` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - The generalization error of a model is then described in terms of its bias (the error of the average prediction obtained using different training sets), its variance (how different are the predictions obtained using different training sets), and noise (the irreducible error inher ...
  - `E6` idx=`1` def_score=`13.8` scope_score=`3.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Using calculus terminology, $L ( { \bf x } )$ is the linearization of around the point y,ϕ and the Bregman divergence is just the difference between a function and a linear approximation to that function.

## KC_CLU_CORE_002 | Intra-cluster Distance

- Topic: `['Data Mining', 'Clustering', 'Clustering Concepts', 'Intra-cluster Distance']`
- Source rows for KC: `18`
- Evidence candidates selected: `4`
  - `E1` idx=`0` def_score=`17.0` scope_score=`9.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'sibling', 'weak']`
    - We could, however, use a divisive clustering technique, such as the minimum spanning tree (MST) algorithm, which is the divisive analog to single link, but this would only work if the data set is not too large.
  - `E2` idx=`1` def_score=`16.8` scope_score=`8.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'sibling', 'weak']`
    - Given a set of objects, the overall objective of clustering is to divide the data set into groups based on the similarity of objects, and to minimize the intra-cluster dissimilarity.
  - `E3` idx=`2` def_score=`16.6` scope_score=`8.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'sibling', 'weak']`
    - In K-means clustering [53], the intra-cluster dissimilarity is measured by the summation of distances between the objects and the centroid of the cluster they are assigned to.
  - `E4` idx=`3` def_score=`16.4` scope_score=`8.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'sibling', 'weak']`
    - In K-means clustering [53], the intra-cluster dissimilarity is measured by the summa- tion of distances between the objects and the centroid of the cluster they are assigned to.

## KC_CLU_DBS_001 | Core Point

- Topic: `['Data Mining', 'Clustering', 'Density-Based Clustering (DBSCAN)', 'Core Point']`
- Source rows for KC: `18`
- Evidence candidates selected: `5`
  - `E1` idx=`1` def_score=`15.8` scope_score=`7.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - However, the use of core points and SNN density adds considerable power and flexibility to this approach.
  - `E2` idx=`2` def_score=`15.6` scope_score=`5.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - A border point is a point that is not a core point, i.e., there are not enough points in its neighborhood for it to be a core point, but it falls within the neighborhood of a core point.
  - `E3` idx=`3` def_score=`15.4` scope_score=`5.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - neighborhood of a core point. In Figure 7.21 , point B is a border point. A
  - `E4` idx=`4` def_score=`15.2` scope_score=`5.2` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - A border point can fall within the neighborhoods of several core points.
  - `E5` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Assume that we have a set of data points , where each point, ,X={x1,…,xm} xi is an n-dimensional point, i.e., .

## KC_CLF_NB_011 | Handling Missing Values in NB

- Topic: `['Data Mining', 'Classification', 'Naive Bayes', 'Handling Missing Values in NB']`
- Source rows for KC: `18`
- Evidence candidates selected: `6`
  - `E1` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Following Schafer’s example based on [79], let suppose that we dispose an $n \times p$ matrix called B of variables whose values are 1 or 0 when X elements are observed and missing respectively.
  - `E2` idx=`1` def_score=`13.8` scope_score=`3.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - If we call $X _ { o b s }$ the observed part of X and we denote the missing part as $X _ { m i s }$ so that $X = ( X _ { o b s } , X _ { m i s } )$ , we can provide a first intuitive definition of what missing at random (MAR) means.
  - `E3` idx=`2` def_score=`13.6` scope_score=`3.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - where $I _ { K i h }$ is the index set of KNN examples of the ith example, and if $y _ { j h }$ is missing the jth attribute is excluded from $I _ { K i h }$ .
  - `E4` idx=`3` def_score=`13.4` scope_score=`5.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Since LLSI was proposed for microarrays, it is assumed that $m \gg n$ In the data set $X ,$ , a row $x _ { i } ^ { T } \in \bar { \mathbb { R } } ^ { 1 \times i }$ represents expressions of the ith instance in n examples:
  - `E5` idx=`4` def_score=`13.2` scope_score=`5.2` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - One simple way is to exclude instances with missing values of v in the counting of instances associated with every child node, generated for every possible outcome of v.Further, if v is chosen as the attribute test condition at a node, training instances with missing values of v  ...
  - `E6` idx=`5` def_score=`13.0` scope_score=`5.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Indeed, mutual information is a measure of how much information one set of values provides about another, given that the values come in pairs, e.g., height and weight.

## KC_CLU_EVAL_012 | External Index: Recall

- Topic: `['Data Mining', 'Clustering', 'Cluster Evaluation', 'External Index: Recall']`
- Source rows for KC: `18`
- Evidence candidates selected: `4`
  - `E1` idx=`0` def_score=`14.0` scope_score=`6.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - where X is the set of input attributes, $M u i _ { \alpha } ( i )$ represents the Mui value of the ith attribute in the imputed data set and $M u i ( i )$ is the Mui value of the ith input attribute in the not imputed data set.
  - `E2` idx=`1` def_score=`13.8` scope_score=`5.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Alternatively, and this is the focus of measures of clustering tendency, we can try to evaluate whether a data set has clusters without clustering.
  - `E3` idx=`2` def_score=`13.6` scope_score=`5.6` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - But, as suggested by the last few paragraphs, K-means is a general clustering algorithm and can be used with a wide variety of data types, such as documents and time series.
  - `E4` idx=`3` def_score=`13.4` scope_score=`3.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'scope', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Besides market basket data, association analysis is also applicable to data from other application domains such as bioinformatics, medical diagnosis, web mining, and scientific data analysis.

## KC_EVAL_BASIC_005 | Specificity

- Topic: `['Data Mining', 'Model Evaluation and Model Comparison', 'Classifier Evaluation Basics', 'Specificity']`
- Source rows for KC: `18`
- Evidence candidates selected: `5`
  - `E1` idx=`0` def_score=`14.0` scope_score=`4.0` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - The association rule mining formulation described in the previous chapter assumes that the input data consists of binary attributes called items.
  - `E2` idx=`1` def_score=`13.8` scope_score=`5.8` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - While there are many types of fuzzy clustering—indeed, many data analysis algorithms can be “fuzzified”—we only consider the fuzzy version of K-means, which is called fuzzy c-means.
  - `E3` idx=`2` def_score=`13.6` scope_score=`3.6` roles=`['contamination', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - the data to a model is a good way to do that if the model is a good match for
  - `E4` idx=`3` def_score=`13.4` scope_score=`5.4` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Hence, at m\* the end of this algorithm, we obtain the best choice of the hyper-parameter value as well as the final classification model (Step 14), both of which are obtained by making an effective use of every data instance in D.train.
  - `E5` idx=`4` def_score=`13.2` scope_score=`5.2` roles=`['contamination', 'context_completion', 'definition_anchor', 'definitional_anchor', 'example', 'explanatory_anchor', 'formula', 'high_contamination', 'procedure', 'strong_definition_anchor']` risks=`['contamination', 'fragment', 'high_contamination', 'sibling', 'weak']`
    - Although the choice of kernel function depends on the characteristics of the input data, a commonly used kernel function is the radial basis function (RBF) kernel, which involves a single hyper-parameter ,σ known as the standard deviation of the RBF kernel.
