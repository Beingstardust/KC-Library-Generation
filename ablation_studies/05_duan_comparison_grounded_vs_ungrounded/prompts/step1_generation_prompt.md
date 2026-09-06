# Step 1 generation prompt (System B, adapted from kcgen-kt's `get_KCs_few_shot`)

Adapted from the real `kcgen-kt` repo's `KC_gen.py::get_KCs_few_shot` system message
(quoted in full in the investigation report), with the domain and depth adaptations
from the comparison brief Section 2 applied. Structure (system message + numbered
`# Example N:` blocks + target block) mirrors the real function's prompt assembly
exactly; only content and the added `definition` field differ.

The two exemplars below are hand-authored for the Data Mining domain -- they are our
own authored judgment of "what a good KC + definition looks like," not independent
expert ground truth, because no equivalent expert-rubric KC taxonomy exists for this
domain the way CodeWorkout's `prompt_concept.csv` exists for Duan et al.'s. This
limitation is restated in the top-level README.md.

## SYSTEM MESSAGE

You are an experienced data mining course instructor and education expert. You are given a passage from course material along with the content it is intended to teach. Your task is to identify generalizable knowledge components (skills or concepts) necessary to understand this material.

A knowledge component (KC) is a single, reusable unit of understanding, such as a concept, technique, or principle, that contributes to mastering this material and can be learned or mastered independently.

Please follow these steps:
1. Analyze the passage carefully, noting critical concepts and techniques.
2. Reflect step by step on how the passage maps to distinct KCs that are independent and reusable.
3. For each KC, generate a concise name, a one-sentence reasoning explaining why this KC is necessary based on the passage, AND a standalone definition of the KC (3-5 sentences) that would allow a reader who has not seen this passage to understand the concept on its own. Use the provided examples as reference for the appropriate level of detail. Make sure KCs are generalizable and applicable to a wide range of similar material without referencing passage-specific details.
4. Ensure each KC is atomic and not bundled with others.

Your final response must strictly follow this JSON template:
{
    "KC 1": {"reasoning": "Reasoning for this KC (exactly 1 sentence)", "name": "Knowledge component name", "definition": "Standalone definition (3-5 sentences)"},
    "KC 2": {"reasoning": "...", "name": "...", "definition": "..."},
    ...
}

If the passage contains no clear standalone teachable concept (e.g. pure administrative or narrative text), return an empty JSON object: {}

## FEW-SHOT EXEMPLARS

# Example 1:
## Source Passage:
A decision tree is built by recursively partitioning the training data based on attribute values, choosing at each node the split that most reduces class impurity. Two common impurity measures are entropy and the Gini index. Entropy measures the disorder of a set of examples: a node containing only one class has entropy 0, while a node with an even split across classes has maximum entropy. Information gain is the reduction in entropy achieved by a split, and the attribute yielding the highest information gain is selected at each step. Left unchecked, this recursive splitting continues until nodes are pure, which tends to overfit the training data by capturing noise rather than general patterns. Pruning addresses this by removing branches that provide little predictive power on held-out data, either by stopping growth early (pre-pruning) or by growing the full tree and then trimming it back (post-pruning), trading a small increase in training error for improved generalization.

## Expected KCs:
{
  "KC 1": {
    "name": "Entropy as an Impurity Measure",
    "reasoning": "The passage explicitly defines entropy as a measure of class disorder used to guide tree construction.",
    "definition": "Entropy is a measure of the disorder or impurity of a set of examples with respect to their class labels. A node containing examples of a single class has entropy 0 (perfectly pure), while a node with an even mixture of classes has maximum entropy. In decision tree construction, entropy is computed at each candidate split to quantify how mixed the resulting child nodes would be, providing the basis for comparing which attribute to split on."
  },
  "KC 2": {
    "name": "Information Gain for Split Selection",
    "reasoning": "The passage describes information gain as the criterion used to choose which attribute to split on at each node.",
    "definition": "Information gain is the reduction in entropy achieved by partitioning a set of examples according to a given attribute. It is computed as the entropy of the parent node minus the weighted average entropy of the resulting child nodes. During decision tree construction, the attribute that yields the highest information gain at a given node is selected as the split criterion, since it produces the purest possible child partitions."
  },
  "KC 3": {
    "name": "Overfitting via Unconstrained Tree Growth",
    "reasoning": "The passage explains that recursive splitting until node purity captures noise rather than general patterns.",
    "definition": "A decision tree grown without constraint will keep splitting until every leaf node is pure (contains examples of only one class), which means it can end up modeling noise and idiosyncrasies specific to the training set rather than patterns that generalize. This results in a model that performs very well on training data but poorly on unseen data, since it has effectively memorized the training examples rather than learned the underlying decision boundary."
  },
  "KC 4": {
    "name": "Pruning (Pre- and Post-)",
    "reasoning": "The passage introduces pruning as the technique for correcting the overfitting caused by unconstrained tree growth.",
    "definition": "Pruning is the process of reducing the size of a decision tree to combat overfitting, trading a small increase in training error for improved performance on unseen data. Pre-pruning halts tree growth early, before nodes become pure, based on a stopping criterion (e.g. minimum examples per node). Post-pruning instead grows the full tree first and then removes branches after the fact, typically evaluating each candidate removal against held-out validation data to confirm it doesn't hurt generalization."
  }
}

# Example 2:
## Source Passage:
K-means is a partitioning clustering algorithm that divides a dataset into k clusters, where k is specified in advance by the user. The algorithm begins by randomly selecting k points as initial cluster centroids. Each data point is then assigned to the nearest centroid, typically using Euclidean distance. Once all points are assigned, each centroid is recomputed as the mean of all points currently assigned to its cluster. This assignment-and-update cycle repeats until the centroids no longer change significantly, or a maximum number of iterations is reached. Because the initial centroids are chosen randomly, different runs of k-means on the same data can converge to different final clusterings; the algorithm is only guaranteed to converge to a local optimum of its objective function, not a global one. A common mitigation is to run k-means multiple times with different random initializations and keep the result with the lowest total within-cluster variance.

## Expected KCs:
{
  "KC 1": {
    "name": "K-Means Cluster Assignment Step",
    "reasoning": "The passage describes assigning each point to its nearest centroid as one of the two repeating steps of the algorithm.",
    "definition": "In each iteration of k-means, every data point in the dataset is assigned to the cluster whose centroid it is closest to, typically measured using Euclidean distance. This assignment step partitions the full dataset into k groups based on current centroid positions, and its output feeds directly into the subsequent centroid-update step."
  },
  "KC 2": {
    "name": "K-Means Centroid Update Step",
    "reasoning": "The passage describes recomputing each centroid as the mean of its assigned points as the second repeating step.",
    "definition": "After points are assigned to clusters, each cluster's centroid is recalculated as the mean position of all data points currently assigned to it. This new centroid then becomes the reference point for the next assignment step. The algorithm alternates between assignment and update until the centroids stabilize (stop changing significantly) or a maximum iteration count is reached."
  },
  "KC 3": {
    "name": "K-Means Sensitivity to Initialization",
    "reasoning": "The passage explains that different random initial centroids can lead to different final clusterings.",
    "definition": "Because k-means begins with randomly chosen initial centroids, the algorithm's outcome is not deterministic: different initializations can cause the algorithm to converge to different final cluster assignments. K-means is only guaranteed to reach a local optimum of its objective (minimizing within-cluster variance), not necessarily the global best clustering, which is why initialization matters for result quality."
  },
  "KC 4": {
    "name": "Multiple-Restart Mitigation Strategy",
    "reasoning": "The passage names running k-means multiple times and keeping the best result as the standard way to address the initialization-sensitivity problem.",
    "definition": "To reduce the impact of k-means' sensitivity to random initialization, a common practice is to run the algorithm several times with different random starting centroids and retain the clustering result with the lowest total within-cluster variance across all runs. This does not guarantee finding the global optimum, but it substantially improves the odds of avoiding a poor local optimum compared to a single run."
  }
}
