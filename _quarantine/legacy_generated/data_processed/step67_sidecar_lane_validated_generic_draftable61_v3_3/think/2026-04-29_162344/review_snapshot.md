# Step 6.7C generic lane-aware validation snapshot

- Lanes: `data/work/cache/diagnostics/step67_v3_3_full144_lane_split/20260429T150636Z/draftable_strongish_61_lane_packets.jsonl`
- Drafts: `data/processed/step67_sidecar_lane_drafts_generic_draftable61_v3_3/think/2026-04-29_151712/onepass_drafts.jsonl`
- Draft rows: `61`
- Valid rows: `61`
- Error rows: `0`
- Warning rows: `21`

## Summary

```json
{
  "stage": "step67c_validate_lane_aware_drafts_generic",
  "run_id": "2026-04-29_162344",
  "created_utc": "2026-04-29T16:23:44.082165+00:00",
  "lanes_path": "data/work/cache/diagnostics/step67_v3_3_full144_lane_split/20260429T150636Z/draftable_strongish_61_lane_packets.jsonl",
  "drafts_path": "data/processed/step67_sidecar_lane_drafts_generic_draftable61_v3_3/think/2026-04-29_151712/onepass_drafts.jsonl",
  "out_dir": "data/processed/step67_sidecar_lane_validated_generic_draftable61_v3_3/think/2026-04-29_162344",
  "packet_count": 61,
  "draft_row_count": 61,
  "valid_row_count": 61,
  "error_row_count": 0,
  "warning_row_count": 21,
  "status_counter": {
    "definition::grounded": 33,
    "scope::grounded": 43,
    "definition::abstained": 28,
    "scope::abstained": 18
  },
  "mode_counter": {
    "definition::contextual_synthesis": 17,
    "scope::contextual_synthesis": 24,
    "definition::abstained": 28,
    "definition::single_strong_context": 8,
    "scope::direct_scope": 13,
    "scope::abstained": 18,
    "scope::single_strong_context": 6,
    "definition::direct_definition": 8
  },
  "issue_counter": {
    "WARNING::definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis": 8,
    "WARNING::scope: grounded only from context_lane": 10,
    "WARNING::scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis": 6,
    "WARNING::definition: contextual_synthesis also cites definition_lane support": 1
  },
  "validation_policy": {
    "definition_direct": "direct_definition must cite at least one definition_lane id",
    "definition_contextual": "contextual_synthesis may cite definition, scope, or context ids, must cite at least two positive evidence ids, and must include scope/context support",
    "definition_single_strong_context": "single_strong_context may cite exactly one strong scope or context id and should be human-reviewed",
    "scope": "scope may cite definition, scope, or context ids; quarantine/sibling ids are errors",
    "scope_single_strong_context": "single_strong_context may cite exactly one strong definition, scope, or context id and should be human-reviewed",
    "abstained": "text, support ids, and supporting_lanes must be empty"
  },
  "active_pointer_policy": "do_not_update_current_alias_or_active_pointer"
}
```

## Rows

### KC_CLF_DT_001 | Hunt's Algorithm

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Hunt's algorithm is used to fit training data by starting with a single leaf node and recursively splitting training instances based on attribute test conditions to create a tree.
- definition_supporting_evidence_ids: `['E4', 'E5']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Leaf nodes are expanded if they contain training instances from more than one class, though child nodes may be empty if no training instances possess the required attribute values.
- scope_supporting_evidence_ids: `['E3', 'E4']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_004 | Gini Index

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The Gini index is used to evaluate candidate split positions when choosing a splitting attribute, where the best split position is the one that produces the lowest Gini index value.
- scope_supporting_evidence_ids: `['E3', 'E6', 'E8']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_005 | Entropy (Node)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Entropy of an interval is a measure of its purity; it is 0 if the interval is perfectly pure (containing only values of one class) and reaches a maximum if the classes of values in the interval occur equally often.
- definition_supporting_evidence_ids: `['E3']`
- definition_supporting_lanes: `['scope_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Entropy-based approaches are used for discretization, whether bottom-up or top-down. The total entropy of a partition is the weighted average of the individual interval entropies.
- scope_supporting_evidence_ids: `['E3']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_CLF_DT_006 | Information Gain

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: In FOIL, information gain is used to evaluate candidate conjuncts, and the conjunct with the highest information gain is selected to extend the rule.
- scope_supporting_evidence_ids: `['E1', 'E3']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_CLF_DT_008 | Gain Ratio

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_DT_011 | Binary Decision Tree

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A decision tree used for binary classification problems that can be represented as a set of mutually exclusive and exhaustive rules.
- definition_supporting_evidence_ids: `['E5', 'E8']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: It partitions the attribute space into disjoint, rectilinear regions and assigns a class to each partition.
- scope_supporting_evidence_ids: `['E5', 'E8']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_CLF_NB_002 | Prior Probability

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Prior probability is used as an estimate of the posterior probability in cases where no attributes are observed, and is the sole content of a table if the variable has no parents.
- scope_supporting_evidence_ids: `['E3', 'E6']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_010 | Sample Mean and Variance

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_NB_011 | Handling Missing Values in NB

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLF_UND_005 | Mutually Exclusive Classes

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_001 | Core Point

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: In the DBSCAN algorithm, core points within a distance Eps of each other are placed in the same cluster, and any border point close enough to a core point is also assigned to that cluster.
- scope_supporting_evidence_ids: `['E7']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_DBS_002 | Border Point

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: In the DBSCAN algorithm, a border point is placed in the same cluster as a core point if it is close enough to it, though ties must be resolved if the border point is close to core points from different clusters.
- scope_supporting_evidence_ids: `['E7']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_004 | DBSCAN Parameters (eps, minPts)

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_006 | Density-Reachable

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_DBS_007 | Density-Connected

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: In the DENCLUE clustering approach, clusters associated with local peaks are merged if the peaks are connected by a path of data points where the density at each point on the path is above the minimum density threshold.
- scope_supporting_evidence_ids: `['E6']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_002 | SSE (Cluster Quality)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: The sum of the squared error (SSE), also known as scatter, is calculated by computing the Euclidean distance from each data point to its closest centroid and then summing the squares of these errors.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: SSE is used as an objective function to measure clustering quality; a lower SSE indicates that the centroids are a better representation of the points in their cluster and translates to better clustering results.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_CLU_EVAL_003 | Cohesion

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Cohesion, also referred to as compactness, is a cluster evaluation measure that can be quantified via SSE, centroid-based measures, or a graph-based view as the sum of the weights of the links in the proximity graph that connect points within a cluster.
- definition_supporting_evidence_ids: `['E6', 'E4', 'E7', 'E2']`
- definition_supporting_lanes: `['scope_lane', 'context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: When used with partitional clustering algorithms such as K-means, cohesion is typically incorporated with separation to provide a way to determine the number of clusters.
- scope_supporting_evidence_ids: `['E6']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_004 | Separation

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Separation is a component of unsupervised cluster evaluation measures used to help determine the number of clusters in partitional clustering algorithms such as K-means; it is associated with maximizing SSB and suffers when clusters are split too finely.
- scope_supporting_evidence_ids: `['E4', 'E8']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_EVAL_005 | Silhouette Coefficient

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: An internal clustering validity index computed for unlabeled data that serves as a measure of the goodness of a clustering.
- definition_supporting_evidence_ids: `['E6', 'E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The coefficient ranges from -1 to 1, with a maximum value of 1, and can be used to identify the number of clusters by observing a distinct peak.
- scope_supporting_evidence_ids: `['E5', 'E1']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_HIER_001 | Dendrogram

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A dendrogram is a diagram that displays cluster-subcluster relationships, where the height at which two clusters are merged reflects the distance between them.
- definition_supporting_evidence_ids: `['E3', 'E2']`
- definition_supporting_lanes: `['definition_lane', 'context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: In hierarchical clustering, a dendrogram can be used to generate K clusters by taking the clusters at a specific level of the diagram.
- scope_supporting_evidence_ids: `['E6']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `['definition: contextual_synthesis also cites definition_lane support']`

### KC_CLU_HIER_004 | MIN (Single Linkage)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: In the MIN (Single Linkage) version of hierarchical clustering, the proximity of two clusters is defined as the minimum distance (or maximum similarity) between any two points in the two different clusters.
- definition_supporting_evidence_ids: `['E5']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_HIER_005 | MAX (Complete Linkage)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: In hierarchical clustering, the MAX (complete link) method defines the proximity between two clusters as the maximum distance (or minimum similarity) between any two points in the two different clusters.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The complete link method favors globular shapes and is less susceptible to noise and outliers, although it can break large clusters. It is applied by calculating the maximum distance between any two points in the clusters, and in graph terms, a group of points is not a cluster until all points in it form a clique.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['definition_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_HIER_006 | Group Average Linkage

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: In the group average version of hierarchical clustering, the proximity of two clusters is defined as the average pairwise proximity among all pairs of points in the different clusters.
- definition_supporting_evidence_ids: `['E5']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: This is an intermediate approach between the single and complete link approaches.
- scope_supporting_evidence_ids: `['E5']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_HIER_007 | Ward's Method

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Ward's method is a clustering technique that assumes clusters are represented by centroids and defines the proximity between two clusters as the increase in the sum of squared errors (SSE) that results from merging them, aiming to minimize the sum of squared distances of points from their cluster centroids.
- definition_supporting_evidence_ids: `['E2', 'E7']`
- definition_supporting_lanes: `['scope_lane', 'context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Ward's method is often used as a robust method for initializing K-means clustering. It is sensitive to outliers, which increase SSE and distort centroids. Additionally, it is mathematically similar to the group average method when the proximity between two points is the square of the distance between them.
- scope_supporting_evidence_ids: `['E1', 'E4', 'E5']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_HIER_008 | Hierarchical Clustering Complexity

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: The computational complexity of hierarchical clustering, which can be O(m^3) or O(m^2 log m) depending on the implementation (such as the use of sorted lists or heaps), making the process computationally expensive.
- definition_supporting_evidence_ids: `['E1', 'E3']`
- definition_supporting_lanes: `['scope_lane', 'context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Hierarchical clustering is practical only if the sample size is relatively small (e.g., a few hundred to a few thousand) and K is relatively small compared to the sample size.
- scope_supporting_evidence_ids: `['E1']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_KM_001 | K-Means Algorithm

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: The K-means algorithm is a clustering approach equivalent to a statistical mixture model and, for Euclidean data, a special case of the EM algorithm; it assumes clusters are spherical Gaussian distributions with different means and equal covariance matrices.
- definition_supporting_evidence_ids: `['E1', 'E2']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The algorithm is used to find clusters in sample data, including Euclidean data.
- scope_supporting_evidence_ids: `['E8', 'E2']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_KM_006 | Bisecting K-Means

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_SIM_001 | Properties of a Distance Function

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_SIM_002 | Properties of a Similarity Function

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_CLU_SIM_004 | Manhattan Distance

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Manhattan distance (L1) is a distance measure that, for one-dimensional data, is calculated as |ci - x| and is used to minimize the sum of absolute errors (SAE).
- definition_supporting_evidence_ids: `['E3', 'E4']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: In K-means clustering, Manhattan distance is used to partition data into K clusters to minimize the sum of distances from the cluster centers, where the median of the points in a cluster is the appropriate centroid.
- scope_supporting_evidence_ids: `['E1', 'E3', 'E4']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_CLU_SIM_005 | Cosine Similarity

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Cosine similarity does not take the length of the two data objects into account when computing similarity.
- scope_supporting_evidence_ids: `['E1']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_CLU_SIM_007 | Jaccard Coefficient

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: The Jaccard coefficient is frequently used to handle objects consisting of asymmetric binary attributes.
- scope_supporting_evidence_ids: `['E5']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_CLU_SIM_008 | Similarity Matrix

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: A similarity matrix can be used to illustrate the separation of clusters or to evaluate the quality of clustering by correlating it with an ideal similarity matrix. Additionally, some clustering algorithms, such as JP clustering, avoid storing the entire similarity matrix to optimize storage and time complexity.
- scope_supporting_evidence_ids: `['E1', 'E6', 'E7', 'E8']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_DE_MISS_001 | Missing Value

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Missing values cause information loss in data mining and can be addressed through preprocessing schemes like imputation. In the context of decision tree training, they can be handled by excluding instances with missing values from child node counts, propagating them to child nodes, or treating the missing value as a separate categorical value distinct from other attribute values.
- scope_supporting_evidence_ids: `['E1', 'E7', 'E8']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_DE_MISS_004 | Imputation

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Imputation is the process of predicting missing values (MVs) in a data set, which can be achieved by modeling hidden distribution probabilities or by using machine learning models such as regression, classification, or KNN.
- definition_supporting_evidence_ids: `['E3', 'E7']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Imputation may be performed using the EM algorithm, which requires assuming a probability distribution such as multivariate Gaussian, or via machine learning methods, which are subject to the MAR assumption.
- scope_supporting_evidence_ids: `['E3', 'E7']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_DE_PREP_001 | Data Integration

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: Data integration is the process of integrating data from different databases.
- definition_supporting_evidence_ids: `['E7']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_DE_PREP_002 | Redundant Attributes

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: In logistic regression, redundant attributes that are duplicates of each other can be assigned equal weights without degrading classification performance, although a large number of redundant attributes in high-dimensional settings can make the model susceptible to overfitting.
- scope_supporting_evidence_ids: `['E1']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_DE_PREP_005 | Data Cleaning

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: Data cleaning is the detection and correction of data quality problems.
- definition_supporting_evidence_ids: `['E4']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_001 | Confusion Matrix

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: A confusion matrix is a table that summarizes the comparison of predicted labels against the true labels of instances to evaluate the performance of a classifier.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: It is a basic approach for representing a classifier's performance on a test set and can be used to estimate evaluation measures on a test set when combined with an estimate of the test data skew and the TPR and TNR on a validation set.
- scope_supporting_evidence_ids: `['E4', 'E8']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_002 | Accuracy

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_BASIC_003 | Precision

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: Precision, also known as positive predicted value (PPV), is a measure where a classifier with high precision is likely to have most of its positive predictions correct; near the leftmost point on a PR curve, it is equal to the fraction of positives in the top ranked instances of the algorithm.
- definition_supporting_evidence_ids: `['E2', 'E4']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Precision is a useful measure for highly skewed test sets where positive predictions must be mostly correct, and it is more strongly impacted by false positives in top ranked test instances than the false positive rate (FPR).
- scope_supporting_evidence_ids: `['E2', 'E5']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_EVAL_BASIC_006 | F-Measure

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: In supervised clustering, the F-measure is used to evaluate the match between a set of clusters and classes, including assessing whether a hierarchical clustering contains clusters for each class that are relatively pure and include most of the objects of that class.
- scope_supporting_evidence_ids: `['E4', 'E6']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_EVAL_BASIC_009 | Multi-class Confusion Matrix

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_COMP_003 | Comparing Two Models on Independent Test Sets

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: The process of evaluating two models on independent test sets to determine if the difference between their observed error rates is statistically significant.
- definition_supporting_evidence_ids: `['E2', 'E3']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: This involves using the number of instances and the error rates of two models evaluated on independent test sets to test for statistical significance.
- scope_supporting_evidence_ids: `['E2', 'E3']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_EVAL_COMP_005 | Nemenyi Test

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_ENS_001 | Ensemble Classifier

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: An ensemble classifier is a classifier that combines the output of a collection of models.
- definition_supporting_evidence_ids: `['E6']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`

### KC_EVAL_ENS_003 | Random Forest

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A random forest is a classifier and ensemble learning method that constructs ensembles of decision trees by building independent base classifiers using bootstrap samples of the training set.
- definition_supporting_evidence_ids: `['E2', 'E8']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: Random forests utilize a hyper-parameter $p$ to determine the number of attributes selected at every node and can employ out-of-bag (oob) error estimates to estimate the generalization error rate during training without the need for a separate validation set.
- scope_supporting_evidence_ids: `['E2']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_EVAL_ENS_004 | Boosting

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: Boosting is a technique that focuses on training examples that are difficult to classify by base classifiers to reduce the bias and variance of final predictions.
- definition_supporting_evidence_ids: `['E1']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: Boosting can be susceptible to overfitting and poor generalization performance due to its tendency to focus on wrongly classified training examples, and it has limitations in rare class modeling.
- scope_supporting_evidence_ids: `['E1', 'E8']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: grounded only from context_lane']`

### KC_EVAL_IMBAL_003 | Undersampling

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A sampling methodology used to ensure a training set has adequate representation of both majority and minority classes by reducing the frequency of the majority class to match the frequency of the minority class.
- definition_supporting_evidence_ids: `['E2', 'E7']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: A limitation of undersampling is that it may result in an inferior classification model if useful negative examples, such as those near the decision boundary, are not selected for training; additionally, the smaller resulting sample may exhibit higher variance.
- scope_supporting_evidence_ids: `['E1']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_IMBAL_006 | RIPPER Rule Induction

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: RIPPER is a widely-used rule induction algorithm that scales almost linearly with the number of training instances, is particularly suited for building models from data sets with imbalanced class distributions, and uses a validation set to prevent model overfitting when working with noisy data.
- definition_supporting_evidence_ids: `['E4']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_SAMP_001 | Holdout Method

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `abstained`
- scope_grounding_mode: `abstained`
- scope_text: 
- scope_supporting_evidence_ids: `[]`
- scope_supporting_lanes: `[]`
- errors: `[]`
- warnings: `[]`

### KC_EVAL_SAMP_003 | k-Fold Cross Validation

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A model evaluation method that aims to make effective use of all labeled instances for both training and testing by partitioning the data into equal-sized subsets.
- definition_supporting_evidence_ids: `['E5', 'E3']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The process involves randomly partitioning a labeled set into equal-sized subsets, iteratively training the model on some subsets and testing it on the remaining subset, and calculating the overall test error rate by dividing the total errors across all runs by the total number of instances.
- scope_supporting_evidence_ids: `['E5', 'E3']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_EVAL_SAMP_004 | Leave-One-Out Cross Validation

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A special case of k-fold cross-validation in which the procedure is repeated N times and each run uses one data instance for testing.
- definition_supporting_evidence_ids: `['E4', 'E5']`
- definition_supporting_lanes: `['scope_lane', 'context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: This approach maximizes the data used for training, but it can be computationally expensive for large data sets and may produce misleading results in some special scenarios.
- scope_supporting_evidence_ids: `['E5']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_FSEL_FUND_002 | Redundant Features

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Ensembles of predictive models can be used to generate a compact subset of non-redundant features when data is wide, dirty, mixed with numerical and categorical predictors, and may contain interactive effects requiring complex models.
- scope_supporting_evidence_ids: `['E2']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_FSEL_FUND_004 | Curse of Dimensionality

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: The phenomenon where many types of data analysis become significantly harder as the dimensionality of the data increases.
- definition_supporting_evidence_ids: `['E8']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: The curse of dimensionality can be encountered when computing similarity in high-dimensional spaces, though the use of kernel functions can avoid these problems when representing nonlinear decision boundaries.
- scope_supporting_evidence_ids: `['E6', 'E7']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `[]`

### KC_FSEL_FW_003 | Wrapper Approach

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: The wrapper approach selects the best feature subset by using a learning algorithm as a black box and statistical validation to avoid overfitting, based on a predictive measure.
- definition_supporting_evidence_ids: `['E4']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: This approach utilizes statistical validation, such as cross-validation, to prevent overfitting during the selection of the optimal feature subset.
- scope_supporting_evidence_ids: `['E4']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_FSEL_GEN_005 | Exhaustive Search

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: A search method that explores all possible subsets to find the optimal ones.
- definition_supporting_evidence_ids: `['E5']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `single_strong_context`
- scope_text: Exhaustive search is the only method that can guarantee optimality, but it is impractical for real data sets with a high number of features (M) due to a space complexity of O(2M).
- scope_supporting_evidence_ids: `['E5']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis', 'scope: single_strong_context should be human-reviewed as weaker than direct_scope or contextual_synthesis']`

### KC_FSEL_GOOD_003 | Covariance

- model_call_ok: `True`
- definition_status: `abstained`
- definition_grounding_mode: `abstained`
- definition_text: 
- definition_supporting_evidence_ids: `[]`
- definition_supporting_lanes: `[]`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: Covariance is positive if two attributes vary similarly, such that when one attribute is above its mean, the other is likely to be above its mean as well.
- scope_supporting_evidence_ids: `['E7']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_FSEL_STAT_001 | Null Hypothesis (H0)

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `direct_definition`
- definition_text: The null hypothesis is a general statement that a desired pattern or phenomenon of interest is not true and that the observed outcome can be explained by natural variability, such as random chance.
- definition_supporting_evidence_ids: `['E2']`
- definition_supporting_lanes: `['definition_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `direct_scope`
- scope_text: The null hypothesis is used for statistical testing, and experimental design provides guidelines for collecting data pertaining to it.
- scope_supporting_evidence_ids: `['E4']`
- scope_supporting_lanes: `['scope_lane']`
- errors: `[]`
- warnings: `[]`

### KC_FSEL_STAT_002 | Test Statistic

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `contextual_synthesis`
- definition_text: A test statistic is a value computed from an observed result or measure that provides the evidence used in hypothesis testing to decide whether to reject or not reject a null hypothesis.
- definition_supporting_evidence_ids: `['E1', 'E2', 'E3']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: It is used to evaluate the significance of results, such as using cluster validity indices (e.g., SSE, silhouette coefficient, entropy, or purity) for clustering or classification accuracy for classification models, by comparing the observed statistic to a null distribution or a critical region.
- scope_supporting_evidence_ids: `['E1', 'E2', 'E3']`
- scope_supporting_lanes: `['context_lane']`
- errors: `[]`
- warnings: `['scope: grounded only from context_lane']`

### KC_FSEL_STAT_003 | Significance Level and p-value

- model_call_ok: `True`
- definition_status: `grounded`
- definition_grounding_mode: `single_strong_context`
- definition_text: The level of significance is a threshold for p-values; an observed p-value is described as statistically significant if it is lower than this threshold.
- definition_supporting_evidence_ids: `['E1']`
- definition_supporting_lanes: `['context_lane']`
- scope_status: `grounded`
- scope_grounding_mode: `contextual_synthesis`
- scope_text: These are used to determine statistical significance and are employed in False Discovery Rate (FDR) controlling procedures. For example, the Benjamini-Hochberg (BH) procedure sorts results by p-values and applies a different significance level to each result, where the significance level (α) represents the desired false discovery rate and is often set to a value greater than 0.05.
- scope_supporting_evidence_ids: `['E1', 'E4', 'E6']`
- scope_supporting_lanes: `['scope_lane', 'context_lane']`
- errors: `[]`
- warnings: `['definition: single_strong_context should be human-reviewed as weaker than direct_definition or contextual_synthesis']`
