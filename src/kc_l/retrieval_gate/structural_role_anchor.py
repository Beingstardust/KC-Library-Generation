"""Structural role anchoring for formula and procedure evidence.

THE PROBLEM (measured on the audited baseline run, 3027 candidates / 159 units):

    role                  clears score threshold   role eligible   ADMITTED
    formula_notation                        1759       149 (8.5%)        18
    example_or_procedure                    1183        94 (7.9%)         0

Pack composition reserves two slots each for these roles and both are STANDALONE_POSITIVE_ROLES,
yet the shipped library contains zero procedure evidence and almost no formula evidence. Drafts
therefore never state an algorithm's steps or a measure's formula, which is the single largest
content gap against human-authored reference drafts.

THE CAUSE

Positive support requires the candidate text to be lexically target-bound, i.e. to restate the
unit's own name. Two rules enforce it:

    evidence_stage_v3_scored_candidates.py:1552
        a genuine formula that is not lexically target-bound is flagged
        "formula_without_target_binding", which is a HARD blocker in
        evidence_admission.ORDERED_EVIDENCE_BLOCKER_FLAGS

    evidence_stage_v3_scored_candidates.py:2278-2284
        when target binding fails, EVERY standalone positive role is zeroed,
        formula_notation and example_or_procedure included

That contract is correct for definitional prose. It is category-wrong for formulas and procedure
steps, because those are exactly the parts of a source document that do NOT restate the concept
name: a display equation carries notation, and a procedure step carries imperative verbs. The
pipeline is asking this evidence to look like a definition before it will accept it as a formula.

THE FIX

Bind these two roles STRUCTURALLY instead of lexically. A formula or procedure step that sits in
the same source patch as a candidate that IS target-bound and positively admitted for the same
unit is, by co-location, about that unit. The anchor is another candidate the pipeline has already
validated - not a heuristic about the text itself.

Precision is preserved by construction:
  * the anchor must be a genuine target-bound positive candidate FOR THE SAME UNIT
  * anchoring is granted only inside the same (doc_id, patch_id) as that anchor
  * only formula_notation and example_or_procedure are granted; definition_kernel and
    explanatory_gloss still require lexical binding, so definitions cannot drift
  * candidates carrying a hard-reject flag are never anchored
  * the role score threshold still applies

This reads only unit id, doc id, patch id, role scores and existing flags. It contains no
subject-matter vocabulary and is inert for a corpus whose formulas already bind lexically.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Set, Tuple

# Roles whose evidence characteristically does not restate the concept name.
STRUCTURALLY_ANCHORABLE_ROLES = ("formula_notation", "example_or_procedure")

# Never anchor a candidate carrying one of these - they are wrong regardless of location.
ANCHOR_DISQUALIFYING_FLAGS = frozenset({
    "reference_like",
    "bibliography_like",
    "meta_guidance",
    "caption_like",
    "source_kc_mismatch",
    "suspected_false_positive",
    "prompt_like",
    "no_target_binding",
})

DEFAULT_ROLE_THRESHOLDS = {
    "formula_notation": 3.6,
    "example_or_procedure": 4.5,
}


def _string_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if isinstance(x, (str, int, float))]
    return []

def _unit_of(row: Mapping[str, Any]) -> str:
    return str(row.get("kc_id") or row.get("knowledge_unit_id") or "")


def _patch_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    return (str(row.get("doc_id") or ""), str(row.get("patch_id") or ""))


def _is_anchor(row: Mapping[str, Any]) -> bool:
    """A candidate already accepted as target-bound positive support for its unit."""
    quality = row.get("candidate_quality") or {}
    admission = row.get("evidence_admission") or {}
    return bool(quality.get("target_bound_positive_support")) and \
        str(admission.get("decision") or "") in {"ordered_evidence", "auxiliary_context"}


def build_anchor_index(rows: List[Mapping[str, Any]]) -> Set[Tuple[str, str, str]]:
    """(unit, doc_id, patch_id) triples that contain a validated target-bound positive."""
    index: Set[Tuple[str, str, str]] = set()
    for row in rows:
        if _is_anchor(row):
            doc, patch = _patch_key(row)
            if patch:
                index.add((_unit_of(row), doc, patch))
    return index


def apply_structural_role_anchoring(
    rows: List[Dict[str, Any]],
    *,
    thresholds: Mapping[str, float] | None = None,
    readmit,
) -> Dict[str, Any]:
    """Grant formula/procedure roles a structural target binding. Mutates rows in place.

    `readmit` is the admission function to recompute a row's decision, injected so this module
    stays free of import cycles.
    """
    role_thresholds = dict(DEFAULT_ROLE_THRESHOLDS)
    if thresholds:
        for role in STRUCTURALLY_ANCHORABLE_ROLES:
            if role in thresholds:
                role_thresholds[role] = float(thresholds[role])

    anchors = build_anchor_index(rows)
    stats: Dict[str, Any] = {
        "anchor_patches": len(anchors),
        "rows_examined": 0,
        "rows_anchored": 0,
        "anchored_by_role": {},
        "promoted_to_ordered_evidence": 0,
        "units_gaining": set(),
    }

    for row in rows:
        quality = row.get("candidate_quality") or {}
        if quality.get("target_bound_positive_support"):
            continue  # already bound; nothing to grant

        flags = set(row.get("review_risk_flags") or []) | set(row.get("risk_flags") or [])
        if flags & ANCHOR_DISQUALIFYING_FLAGS:
            continue

        doc, patch = _patch_key(row)
        if not patch or (_unit_of(row), doc, patch) not in anchors:
            continue

        role_scores = row.get("role_scores") or {}
        # Grant only the BEST-FITTING role, by margin over that role's own threshold.
        # _primary_positive_role (evidence_admission.py:430) walks POSITIVE_ROLES in a fixed order
        # in which formula_notation always precedes example_or_procedure, so granting both would
        # label every procedure step a formula and make it compete for the formula pack slot.
        # Pack composition caps the two roles separately (2 each), so correct labelling is what
        # lets procedural and formula evidence occupy a unit's pack side by side.
        eligible_roles = [
            (float(role_scores.get(role) or 0.0) / max(role_thresholds[role], 1e-9), role)
            for role in STRUCTURALLY_ANCHORABLE_ROLES
            if float(role_scores.get(role) or 0.0) >= role_thresholds[role]
        ]
        granted = [max(eligible_roles)[1]] if eligible_roles else []
        stats["rows_examined"] += 1
        if not granted:
            continue

        before = str((row.get("evidence_admission") or {}).get("decision") or "")

        eligibility = dict(row.get("role_eligibility") or {})
        for role in granted:
            eligibility[role] = True
        eligibility["positive_support_eligible"] = True
        eligibility["structural_role_anchor_support"] = True
        eligibility["structural_role_anchor_roles"] = list(granted)
        # The route contract cannot veto a structurally anchored role: the anchor is an
        # independent, already-validated positive for this same unit in this same patch.
        eligibility["profile_route_positive_support_blocked"] = False
        row["role_eligibility"] = eligibility

        new_quality = dict(quality)
        new_quality["target_bound_positive_support"] = True
        basis = dict(new_quality.get("target_bound_positive_support_basis") or {})
        basis["structural_role_anchor"] = True
        basis["structural_role_anchor_patch"] = {"doc_id": doc, "patch_id": patch}
        new_quality["target_bound_positive_support_basis"] = basis
        row["candidate_quality"] = new_quality

        # These flags all exist only because the text did not read like a definition sentence:
        # formula_without_target_binding fires when a real formula does not restate the unit name,
        # and definition_subject_mismatch comes from _definition_subject_alignment, which asks
        # whether a sentence's DEFINITIONAL SUBJECT matches the target. A display equation has no
        # definitional subject and neither does an imperative procedure step, so for these two
        # roles the tests are category errors. The structural anchor supplies a stronger binding
        # than either, so they must not keep hard-blocking the row.
        waived = {
            "formula_without_target_binding",
            "definition_subject_mismatch",
            "definition_subject_mismatch_single_token_match",
        }
        for key in ("review_risk_flags", "risk_flags"):
            current = row.get(key)
            if isinstance(current, list) and (set(current) & waived):
                row[key + "_pre_structural_anchor"] = list(current)
                row[key] = [f for f in current if f not in waived]

        if str(row.get("routing_recommendation") or "") != "positive_role_candidate":
            row["structural_role_anchor_prior_routing"] = row.get("routing_recommendation")
            row["routing_recommendation"] = "positive_role_candidate"

        # shapeaware bucketed this row during scoring, before the anchor existed. Where its
        # reason was the missing target binding (shapeaware_shadow.py:1130,1134), the anchor has
        # now supplied it, so the review_needed verdict no longer applies. rejected_false_positive
        # is never touched, and neither is a row its own review flags call a suspected false
        # positive - that detector remains authoritative.
        shapeaware = row.get("shapeaware_shadow")
        bucket_key = None
        holder = None
        if isinstance(shapeaware, dict) and "shapeaware_bucket" in shapeaware:
            holder, bucket_key = shapeaware, "shapeaware_bucket"
        elif "shapeaware_bucket" in row:
            holder, bucket_key = row, "shapeaware_bucket"
        if holder is not None and str(holder.get(bucket_key) or "") == "review_needed":
            review_flags = set(_string_list(holder.get("review_risk_flags")))
            if "suspected_false_positive" not in review_flags:
                row["structural_role_anchor_prior_shapeaware_bucket"] = holder.get(bucket_key)
                holder[bucket_key] = "drafting_core"

        row["evidence_admission"] = readmit(row)
        row["structural_role_anchor"] = {
            "granted_roles": granted,
            "anchor_patch": {"doc_id": doc, "patch_id": patch},
            "decision_before": before,
            "decision_after": str((row.get("evidence_admission") or {}).get("decision") or ""),
        }

        stats["rows_anchored"] += 1
        for role in granted:
            stats["anchored_by_role"][role] = stats["anchored_by_role"].get(role, 0) + 1
        if str((row.get("evidence_admission") or {}).get("decision") or "") == "ordered_evidence":
            stats["promoted_to_ordered_evidence"] += 1
            stats["units_gaining"].add(_unit_of(row))

    stats["units_gaining"] = sorted(stats["units_gaining"])
    return stats
