"""Cross-branch evidence scoping.

Root cause (confirmed investigation): candidates that end up admitted as core
drafting evidence for the wrong KC are NOT detectable by comparing a candidate's own
retrieving-KC label against the target KC - source_kc_id always equals the target kc_id
(every candidate is retrieved by and for the KC it ends up attached to; there is no
"borrowed from a different KC's query" case in this pipeline). There is also no reliable
per-candidate document-section heading (patch_heading is empty for the confirmed bad
candidates). The only data-grounded signal available is comparative: across the full run,
which hierarchy branch has OTHER KCs' confirmed core evidence anchored near this same page,
independent of the candidate under test.

CROSS_BRANCH_FLAG is the new, distinguishable risk flag this module assigns - never
reuse an existing flag name (not_admitted_to_ordered_pack_for_drafting means something
narrower and already-existing: "this exact candidate failed shapeaware/ordered-pack
alignment", which is a different check with different false-positive risk).

Branch granularity (2026-07-21 hardening, "Final Pre-Review Architecture Hardening" task):
the branch key is the KC's FULL topic_path_labels, not a fixed-depth prefix. This is already
the complete ancestor path - two KCs share a branch iff they share the same immediate parent
node in the hierarchy tree (siblings) - so it adapts automatically to however deep a given
KC's subtree happens to be (measured: 129 of 159 KCs are 3 levels deep, 30 are 4), with zero
hardcoded depth constant. A fixed 2-level prefix was measured to collapse the entire 159-KC
hierarchy into just 4 branches - so coarse it could never catch within-topic contamination
(e.g. Decision-Trees evidence bleeding into a Naive-Bayes KC, both under "Classification" -
the KC_CLF_NB_011 case that motivated this hardening). A fixed 3-level prefix does better but
is still not shape-robust: it over-groups the 30 KCs 4 levels deep (e.g. treats "Decision
Trees > Overfitting and Pruning" as indistinguishable from plain "Decision Trees").

Widening from 2-level to the full path was measured (against the 159-KC evidence set) to
raise real, human-verified contamination catches substantially, but also introduces a new
false-positive mode: on a compact, multi-topic document (the exercise/tutoring "Guides_merged"
PDF, which moves through many sub-topics in quick succession), a branch's *only* confirmed
foothold in that specific document can legitimately sit further than +-window pages from a
given genuinely-on-topic candidate, since the guide simply doesn't dwell on one sub-topic for
long. Confirmed directly against source pages: e.g. a page titled "Manhattan Distance,
Euclidean Distance, and Cosine Similarity" was flagged as cross-branch purely because no other
"Similarity and Distance Functions" KC happened to cite a page within +-15 of it in that guide,
even though "Cluster Evaluation" content nearby (Rand Index) legitimately corroborates the
super-branch's presence in the document.

_has_independent_doc_coverage is the mitigation: before trusting a windowed "no target-branch
signal nearby" absence as a demotion signal, first check whether an INDEPENDENT KC (not the
same KC's own other candidates - keyed by kc_id, not page, specifically so a KC's own repeated
mis-scoped candidates can't corroborate each other into a false pass) has confirmed evidence
for the same branch ANYWHERE ELSE in the same document, not just within the window. If so, the
absence within the window is read as sparse-but-real coverage, not a genuine mismatch, and the
candidate is not demoted. Cross-branch contamination signal itself stays window-scoped (local
page proximity is what makes it evidence of a *specific* misplaced page, not just "different
topic exists somewhere in this document").

Validated against the full 159-KC evidence set: this combination (full-path
branch key + document-scope independent-KC corroboration) suppresses the confirmed false
positives (e.g. the Similarity/Distance and DBSCAN cases above) while preserving confirmed true
positives (e.g. a "Hold-out / train-test split" evaluation-methodology passage that had been
wrongly admitted as "Classification Underpinnings" core evidence; association-rule-mining
language wrongly admitted onto Class-Imbalance/ROC-Analysis KCs).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

CROSS_BRANCH_FLAG = "cross_branch_evidence_mismatch"
DEFAULT_WINDOW = 15


def load_page_branch_map(path: Path | str) -> Dict[str, Dict[str, List[str]]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _window_branch_signal(
    page_branch_map: Mapping[str, Mapping[str, List[str]]],
    doc_id: str,
    page_index: int,
    exclude_page: Optional[int],
    window: int,
) -> Dict[str, List[str]]:
    """Aggregate confirmed-branch hits within +-window pages, excluding exclude_page (the
    candidate's own page) so a candidate can never be used as evidence for its own admission -
    without this exclusion the check is circular and never demotes anything (confirmed during
    validation: page 846 only "passed" before this exclusion was added because the candidate's
    own prior citation of itself was being read back as supporting evidence).
    """
    signal: Dict[str, set] = {}
    for p in range(page_index - window, page_index + window + 1):
        if exclude_page is not None and p == exclude_page:
            continue
        key = f"{doc_id}::{p}"
        entry = page_branch_map.get(key)
        if not entry:
            continue
        for branch_key, kc_ids in entry.items():
            signal.setdefault(branch_key, set()).update(kc_ids)
    return {k: sorted(v) for k, v in signal.items()}


def _has_independent_doc_coverage(
    page_branch_map: Mapping[str, Mapping[str, List[str]]],
    doc_id: str,
    target_branch_key: str,
    own_kc_id: str,
) -> bool:
    """Whole-document (not window-limited) check: does some OTHER KC have confirmed
    target_branch_key evidence anywhere in doc_id? See module docstring for why this
    exists and why it's keyed by kc_id rather than page.
    """
    prefix = f"{doc_id}::"
    for key, entry in page_branch_map.items():
        if not key.startswith(prefix):
            continue
        kc_ids = entry.get(target_branch_key)
        if not kc_ids:
            continue
        if any(kc_id != own_kc_id for kc_id in kc_ids):
            return True
    return False


def check_cross_branch_mismatch(
    page_branch_map: Mapping[str, Mapping[str, List[str]]],
    *,
    doc_id: str,
    page_index: Any,
    target_topic_path_labels: List[str],
    own_kc_id: str,
    window: int = DEFAULT_WINDOW,
) -> Tuple[bool, Dict[str, Any]]:
    """Returns (is_mismatch, detail). is_mismatch is True only when (a) the page's local
    neighborhood has ZERO confirmed evidence from the target's own branch AND no independent
    KC anchors that branch anywhere else in the same document, AND (b) the neighborhood has at
    least one confirmed hit from a DIFFERENT branch - deliberately conservative: pages with no
    cross-KC signal at all, or pages where both the target's own branch (locally or
    document-wide) and another branch both have confirmed nearby evidence (ambiguous /
    transition content), are never flagged. This keeps false-positive risk on the stable-correct
    units low by design, at the cost of not catching cases with no corroborating cross-KC
    evidence anywhere in the same document (a real, accepted limitation).
    """
    if not doc_id or page_index is None or not target_topic_path_labels or not own_kc_id:
        return False, {}
    try:
        page_int = int(page_index)
    except (TypeError, ValueError):
        return False, {}

    target_branch_key = "|".join(target_topic_path_labels)
    if not target_branch_key:
        return False, {}

    signal = _window_branch_signal(page_branch_map, doc_id, page_int, exclude_page=page_int, window=window)
    has_target_in_window = target_branch_key in signal
    other_branches = {k: v for k, v in signal.items() if k != target_branch_key}

    has_target = has_target_in_window or _has_independent_doc_coverage(
        page_branch_map, doc_id, target_branch_key, own_kc_id
    )

    is_mismatch = (not has_target) and bool(other_branches)
    detail = {
        "doc_id": doc_id,
        "page_index": page_int,
        "target_branch": target_branch_key,
        "window": window,
        "nearby_branch_signal": signal,
        "target_branch_has_independent_doc_coverage": has_target and not has_target_in_window,
    } if (is_mismatch or other_branches) else {}
    return is_mismatch, detail
