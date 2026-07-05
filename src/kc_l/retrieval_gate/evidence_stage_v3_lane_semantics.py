from __future__ import annotations

"""Minimal lane semantics helpers for Step 5x v3 evidence packs.

These helpers deliberately separate evidence discovery/review bookkeeping from
automatic drafting support. A pack is automatic-drafting-supported only when it
has at least one item in ``ordered_pack_for_drafting``. Review, rejected,
expected-need, raw shadow-core, and insufficient-reason lists are useful
diagnostics, but they must never be counted as drafting support unless the item
also passed the ordered-pack admission contract.
"""

from typing import Any, Dict, List, Mapping

DRAFTING_CORE_EVIDENCE = "drafting_core_evidence"
AUXILIARY_EVIDENCE = "auxiliary_evidence"
REVIEW_NEEDED_EVIDENCE = "review_needed_evidence"
REJECTED_FALSE_POSITIVE_EVIDENCE = "rejected_false_positive_evidence"
EXPECTED_EVIDENCE_NEEDS = "expected_evidence_needs"
ORDERED_PACK_FOR_DRAFTING = "ordered_pack_for_drafting"
PACK_QUALITY = "pack_quality"
INSUFFICIENT_REASONS = "insufficient_reasons"
PACK_QUALITY_INSUFFICIENT_REASONS = "pack_quality.insufficient_reasons"

LANE_CORE_READY = "core_ready"
LANE_MIXED_CORE_WITH_REVIEW_OR_REJECTED = "mixed_core_with_review_or_rejected"
LANE_REVIEW_ONLY = "review_only"
LANE_MIXED_REVIEW_AND_REJECTED = "mixed_review_and_rejected"
LANE_REJECTED_ONLY = "rejected_only"
LANE_INSUFFICIENT_ONLY = "insufficient_only"
LANE_EXPECTED_NEEDS_ONLY = "expected_needs_only"
LANE_TRUE_EMPTY_OR_UNKNOWN_SCHEMA = "true_empty_or_unknown_schema"

NON_DRAFTING_LANES = {
    LANE_REVIEW_ONLY,
    LANE_MIXED_REVIEW_AND_REJECTED,
    LANE_REJECTED_ONLY,
    LANE_INSUFFICIENT_ONLY,
    LANE_EXPECTED_NEEDS_ONLY,
    LANE_TRUE_EMPTY_OR_UNKNOWN_SCHEMA,
}


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _nested_get(obj: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = obj
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _list_len(pack: Mapping[str, Any], key: str) -> int:
    if "." in key:
        value = _nested_get(pack, key)
    else:
        value = pack.get(key)
    return len(value) if isinstance(value, list) else 0


def evidence_lane_lengths(pack: Mapping[str, Any]) -> Dict[str, int]:
    """Return canonical Step 5x v3 evidence lane lengths.

    Only ``ordered_pack_for_drafting`` is automatic drafting support. The other
    lengths are included so audit code and downstream stages cannot accidentally
    infer support from a generic nonempty list.
    """
    return {
        DRAFTING_CORE_EVIDENCE: _list_len(pack, DRAFTING_CORE_EVIDENCE),
        AUXILIARY_EVIDENCE: _list_len(pack, AUXILIARY_EVIDENCE),
        REVIEW_NEEDED_EVIDENCE: _list_len(pack, REVIEW_NEEDED_EVIDENCE),
        REJECTED_FALSE_POSITIVE_EVIDENCE: _list_len(pack, REJECTED_FALSE_POSITIVE_EVIDENCE),
        EXPECTED_EVIDENCE_NEEDS: _list_len(pack, EXPECTED_EVIDENCE_NEEDS),
        ORDERED_PACK_FOR_DRAFTING: _list_len(pack, ORDERED_PACK_FOR_DRAFTING),
        PACK_QUALITY_INSUFFICIENT_REASONS: _list_len(pack, PACK_QUALITY_INSUFFICIENT_REASONS),
    }


def classify_evidence_pack_lane(pack: Mapping[str, Any]) -> str:
    lengths = evidence_lane_lengths(pack)
    core = lengths[ORDERED_PACK_FOR_DRAFTING]
    review = lengths[REVIEW_NEEDED_EVIDENCE]
    rejected = lengths[REJECTED_FALSE_POSITIVE_EVIDENCE]
    needs = lengths[EXPECTED_EVIDENCE_NEEDS]
    insuff = lengths[PACK_QUALITY_INSUFFICIENT_REASONS]

    if core > 0 and review == 0 and rejected == 0:
        return LANE_CORE_READY
    if core > 0 and (review > 0 or rejected > 0):
        return LANE_MIXED_CORE_WITH_REVIEW_OR_REJECTED
    if core == 0 and review > 0 and rejected == 0:
        return LANE_REVIEW_ONLY
    if core == 0 and review > 0 and rejected > 0:
        return LANE_MIXED_REVIEW_AND_REJECTED
    if core == 0 and review == 0 and rejected > 0:
        return LANE_REJECTED_ONLY
    if core == 0 and review == 0 and rejected == 0 and insuff > 0:
        return LANE_INSUFFICIENT_ONLY
    if core == 0 and review == 0 and rejected == 0 and needs > 0:
        return LANE_EXPECTED_NEEDS_ONLY
    return LANE_TRUE_EMPTY_OR_UNKNOWN_SCHEMA


def has_automatic_drafting_support(pack: Mapping[str, Any]) -> bool:
    """True only when the pack has admitted ordered drafting evidence.

    ``drafting_core_evidence`` can be a shadow/audit lane during pack
    construction. The final contract for downstream drafting is stricter:
    automatic support exists only after evidence has passed
    ``ordered_pack_for_drafting`` admission.
    """
    return evidence_lane_lengths(pack)[ORDERED_PACK_FOR_DRAFTING] > 0


def evidence_lane_semantics(pack: Mapping[str, Any]) -> Dict[str, Any]:
    lengths = evidence_lane_lengths(pack)
    lane = classify_evidence_pack_lane(pack)
    return {
        "lane_contract_version": "step5x_v3_lane_semantics_v2",
        "lane": lane,
        "automatic_drafting_supported": has_automatic_drafting_support(pack),
        "automatic_drafting_support_source": ORDERED_PACK_FOR_DRAFTING,
        "drafting_core_evidence_len": lengths[DRAFTING_CORE_EVIDENCE],
        "auxiliary_evidence_len": lengths[AUXILIARY_EVIDENCE],
        "review_needed_evidence_len": lengths[REVIEW_NEEDED_EVIDENCE],
        "rejected_false_positive_evidence_len": lengths[REJECTED_FALSE_POSITIVE_EVIDENCE],
        "expected_evidence_needs_len": lengths[EXPECTED_EVIDENCE_NEEDS],
        "ordered_pack_for_drafting_len": lengths[ORDERED_PACK_FOR_DRAFTING],
        "insufficient_reasons_len": lengths[PACK_QUALITY_INSUFFICIENT_REASONS],
        "non_drafting_lanes_are_not_success": True,
    }


def _candidate_aliases(item: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    for key in (
        "candidate_id",
        "source_candidate_id",
        "scored_candidate_id",
        "stage2_candidate_id",
        "source_row_id",
        "overlay_candidate_id",
    ):
        value = str(item.get(key) or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    return aliases


def evidence_lane_membership_index(pack: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index candidate ids by semantic evidence lane.

    This is separate from slot membership. Slot membership is useful provenance,
    but it is not the same thing as automatic drafting support.
    """
    index: Dict[str, Dict[str, Any]] = {}
    lanes = (
        (DRAFTING_CORE_EVIDENCE, "drafting_core_positions"),
        (AUXILIARY_EVIDENCE, "auxiliary_positions"),
        (REVIEW_NEEDED_EVIDENCE, "review_needed_positions"),
        (REJECTED_FALSE_POSITIVE_EVIDENCE, "rejected_false_positive_positions"),
    )
    for lane_name, position_key in lanes:
        items = pack.get(lane_name)
        if not isinstance(items, list):
            continue
        for index_position, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            for alias in _candidate_aliases(item):
                payload = index.setdefault(
                    alias,
                    {
                        "lanes": [],
                        "drafting_core_positions": [],
                        "auxiliary_positions": [],
                        "review_needed_positions": [],
                        "rejected_false_positive_positions": [],
                        "selected_for_drafting_core": False,
                    },
                )
                if lane_name not in payload["lanes"]:
                    payload["lanes"].append(lane_name)
                if index_position not in payload[position_key]:
                    payload[position_key].append(index_position)
                if lane_name == DRAFTING_CORE_EVIDENCE:
                    payload["selected_for_drafting_core"] = True
    return index
