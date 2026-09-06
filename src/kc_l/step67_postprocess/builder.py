from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple

# This module reproduces the step 6.7 v2 postprocessing stage
# (step67_v2_postprocessed_review_source), whose original producing script was confirmed
# genuinely lost (never committed anywhere, exhaustively searched across 4 HPC-pulled
# supplemental folders in a prior investigation). The logic below was reverse-engineered with
# high confidence from the ONE surviving real run available for validation
# (data/processed/step67_v2_postprocessed_review_source/20260520T233415Z/, baseline run
# step67_v2_full165_kc_topic_policy_marker_fix_20260520T195051Z) by:
#   1. Reading the row-level "postprocess_metadata.source_row_preserved_except_derived_text_
#      cleanup_and_evidence_map_annotations": true flag already embedded in the real output,
#      which self-documents exactly the pass-through/annotation architecture implemented here.
#   2. Deriving the review_action/provenance_quality/semantic_grade_provisional/
#      evidence_reference_status/issue_flags decision table empirically from 100% of the 165
#      real rows in postprocess_unit_audit.csv, with zero contradictions.
#   3. Confirming evidence-ID resolution happens per evidence_map claim (not against the
#      top-level draft's supporting_evidence_ids summary field) by reading each claim's
#      _postprocess_original/resolved/unresolved_supporting_evidence_ids fields already
#      present in the real output, and confirming the row-level resolved/unresolved lists are
#      exactly the union of these per-claim sets across all 165 rows.
#   4. Confirming the topic-unit evidence pool (topic_evidence_for_synthesis UNION each direct
#      child KC's top_child_evidence) against the surviving upstream packet-builder script
#      (build_step67_v2_hierarchy_aware_synthesis_packets.py) and independently against step
#      6.8's own review_packets/builder.py, which implements the identical two-source fallback.
# Two known, narrow simplifications versus the historical run (both non-load-bearing - step
# 6.8's builder.py never reads the ID list fields' exact content, only review_action et al.):
#   - The historical run's preserved data itself contains text corruption (confirmed present
#     in the raw draft's own LLM-cited evidence IDs, e.g. a stray Korean character appended to
#     an otherwise-clean, resolvable ID) inflating a handful of historical unresolved-ID
#     counts. This implementation does not attempt to reproduce that corruption.
#   - Evidence-ID rebinding ("_postprocess_rebinds") is real but had zero occurrences across
#     all 165 rows in the only run available to validate against; the surviving closeout
#     documents it only as "deterministic local text matching" with no example to
#     reverse-engineer the exact algorithm from. Implemented as a structurally-present,
#     always-empty no-op rather than guessed at.


SCHEMA_VERSION = "step67_v2_postprocessed_review_source_v1"
REVIEW_PREFLIGHT_SCHEMA_VERSION = "step67_v2_review_preflight_v1"
POSTPROCESS_SUMMARY_SCHEMA_VERSION = "step67_v2_postprocess_summary_v1"

# The single text-normalization rule confirmed by the one historical run available for
# validation - only 1/165 rows exercised any normalization rule at all, so this is very likely
# an incomplete sample of a broader terminology-cleanup rule set that could not be fully
# reverse-engineered from a single observed occurrence. Documented as such, not presented as
# exhaustive.
TEXT_NORMALIZATION_RULES: List[Tuple[str, str]] = [
    (r"\buse\s+case\s+deletion\b", "case deletion"),
]

# Structural, content-agnostic artifact-leakage detectors, applied at two points confirmed by
# direct origin tracing (2026-07-30): internal pipeline IDs are introduced by the drafting model
# itself (confirmed absent from all evidence text shown to it - they exist only as a separate,
# structured "evidence_id" metadata field the model should cite via evidence_map, not copy into
# prose), while dangling structural references and bracket citations are confirmed already
# present verbatim in the raw source PDF text (in source_block_text/quote fields), faithfully
# reproduced by the model rather than invented. Each pattern targets a shape internal to this
# pipeline's own naming/citation conventions or to generic academic-writing structure - none
# reference any specific KC, topic, domain vocabulary, or subject matter, so the same checks
# apply identically regardless of what a given unit is about.
INTERNAL_ID_LEAK_PATTERN = (
    r"(?:cand_[a-f0-9]{15,}"
    r"|[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*:(?:step5_4|overlay|cand_[a-f0-9]+):[a-f0-9]{10,}"
    r"|hier::path::[a-f0-9]{20,}(?::[A-Za-z0-9_:]+)?)"
)
DANGLING_STRUCTURAL_REFERENCE_PATTERN = (
    r"(?:Equation|Eq\.?|Figure|Fig\.?|Table|Section|Sec\.?|Chapter|Theorem|Lemma|Algorithm)"
    r"\s+\d+(?:\.\d+)*"
)
BRACKET_CITATION_FRAGMENT_PATTERN = r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]"

ARTIFACT_LEAKAGE_PATTERNS: List[Tuple[str, str]] = [
    ("internal_id_leak", r"\b" + INTERNAL_ID_LEAK_PATTERN + r"\b"),
    ("dangling_structural_reference", r"\b" + DANGLING_STRUCTURAL_REFERENCE_PATTERN + r"\b"),
    ("bracket_citation_fragment", BRACKET_CITATION_FRAGMENT_PATTERN),
]

# Internal-ID leaks confirmed (against all 3 real K-Means-Family instances) to always appear as
# their own self-contained parenthetical aside - safely removable without damaging grammar
# ("...time complexity (cand_XXX) and its sensitivity..." -> "...time complexity and its
# sensitivity..."). IDs appearing bare (not parenthetical) are deliberately NOT matched here -
# too risky to strip without a grammar model, left to the flag-only path instead.
_PARENTHETICAL_INTERNAL_ID_RE = re.compile(r"\s*\([^()]*?" + INTERNAL_ID_LEAK_PATTERN + r"[^()]*?\)")


def _tidy_whitespace_after_strip(text: str) -> str:
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def strip_safely_parenthetical_id_leaks(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Deterministically strip internal-ID leaks from final draft text where safely separable
    from surrounding grammar (self-contained parenthetical asides), returning (new_text,
    stripped_matches). Confirmed this is how the mechanism actually manifests in real drafts -
    see module-level comment. Does not touch dangling_structural_reference/bracket_citation_
    fragment here - those are handled upstream instead (see strip_upstream_evidence_leakage),
    since removing a mid-sentence reference from already-generated draft prose risks damaging
    grammar in a way a parenthetical aside does not.
    """
    if not text:
        return text, []
    stripped: List[Dict[str, str]] = []

    def _repl(m: "re.Match[str]") -> str:
        stripped.append({"category": "internal_id_leak", "match": m.group(0).strip(), "stripped": True})
        return ""

    new_text = _PARENTHETICAL_INTERNAL_ID_RE.sub(_repl, text)
    if stripped:
        new_text = _tidy_whitespace_after_strip(new_text)
    return new_text, stripped


def strip_upstream_evidence_leakage(text: str) -> str:
    """Strip dangling structural references (Equation/Figure/Table/... + number) and bare
    bracket-citations from raw evidence text BEFORE it is shown to the drafting model, so the
    model never has the opportunity to reproduce a reference it cannot resolve for a reader.
    Confirmed these are present verbatim in the source PDF text itself, not model-invented (see
    module-level comment) - fixing at this upstream point prevents the leak at its actual
    origin. Evidence text is background synthesis material, not final human-facing prose, so
    accepting minor grammatical looseness here is a safer trade-off than trying to preserve
    perfect grammar while stripping the same pattern out of an already-generated sentence a
    human will actually read.
    """
    if not text:
        return text
    new_text = re.sub(r"\b" + DANGLING_STRUCTURAL_REFERENCE_PATTERN + r"\b", "", text)
    new_text = re.sub(BRACKET_CITATION_FRAGMENT_PATTERN, "", new_text)
    return _tidy_whitespace_after_strip(new_text)


def detect_artifact_leakage(text: str) -> List[Dict[str, str]]:
    """Scan final draft text for any remaining internal-ID leaks, dangling Equation/Figure/
    Table/Section/Theorem/Lemma/Algorithm-number references, and bracket-citation fragments -
    used as the flag-only safety net for whatever the strip passes above do not (or cannot)
    remove. Returns a list of {"category", "match"} dicts, one per match found (duplicates
    preserved so a reviewer sees every occurrence, not just distinct patterns). Purely
    structural/regex-based - no vocabulary list, no per-unit special-casing.
    """
    if not text:
        return []
    matches: List[Dict[str, str]] = []
    for category, pattern in ARTIFACT_LEAKAGE_PATTERNS:
        for m in re.finditer(pattern, text):
            matches.append({"category": category, "match": m.group(0), "stripped": False})
    return matches

PACKET_EVIDENCE_SOURCE_BY_SUPPORT_STATE = {
    "draftable": "embedded_step5x_pack",
    "insufficient_support": "insufficient_support_no_target_bound_fallback",
    "weak_fallback": "step66_overlay_target_bound_fallback",
}

PROVENANCE_QUALITY_BY_SUPPORT_STATE = {
    "draftable": "ordered_step5x_or_embedded_pack",
    "insufficient_support": "fallback_source_lane",
    "weak_fallback": "fallback_source_lane",
}

SEMANTIC_GRADE_BY_DRAFT_STATUS = {
    "grounded": "usable_or_good_grounded",
    "partial": "usable_partial_needs_review",
    "abstained": "not_applicable_segmentable_abstention",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _unit_type(row: Mapping[str, Any]) -> str:
    return _text(row.get("knowledge_unit_type"))


def _draft_key_for_unit_type(utype: str) -> str:
    return "contextual_topic_draft" if utype == "topic" else "contextual_kc_draft"


def _draft_status(draft: Mapping[str, Any], utype: str) -> str:
    return _text(_as_dict(draft.get(_draft_key_for_unit_type(utype))).get("status"))


def evidence_pool_for_row(row: Mapping[str, Any], utype: str) -> Set[str]:
    """The set of evidence_ids a drafted claim's supporting_evidence_ids can validly cite.

    KC packets: source_packet.evidence_for_synthesis.
    Topic packets: source_packet.topic_evidence_for_synthesis UNION each direct child KC's
    source_packet.direct_child_kc_summary.child_kcs[].top_child_evidence (already capped to
    each child's own top 3 evidence items upstream, at packet-build time).
    """
    source_packet = _as_dict(row.get("source_packet"))
    pool: Set[str] = set()

    if utype == "topic":
        for item in _as_list(source_packet.get("topic_evidence_for_synthesis")):
            if isinstance(item, Mapping) and item.get("evidence_id"):
                pool.add(str(item["evidence_id"]))
        child_summary = _as_dict(source_packet.get("direct_child_kc_summary"))
        for child in _as_list(child_summary.get("child_kcs")):
            if not isinstance(child, Mapping):
                continue
            for item in _as_list(child.get("top_child_evidence")):
                if isinstance(item, Mapping) and item.get("evidence_id"):
                    pool.add(str(item["evidence_id"]))
    else:
        for item in _as_list(source_packet.get("evidence_for_synthesis")):
            if isinstance(item, Mapping) and item.get("evidence_id"):
                pool.add(str(item["evidence_id"]))

    return pool


def _postprocess_evidence_map(draft: Mapping[str, Any], pool: Set[str]) -> Tuple[List[Any], Set[str], Set[str]]:
    """Resolve each evidence_map claim's cited evidence_ids against pool.

    Returns (new_evidence_map, all_resolved_ids, all_unresolved_ids). The row-level resolved/
    unresolved sets are the union across every claim - confirmed empirically to match the real
    row-level review_preflight lists exactly, for every row in the one historical run
    available for validation.
    """
    evidence_map = _as_list(draft.get("evidence_map"))
    all_resolved: Set[str] = set()
    all_unresolved: Set[str] = set()
    new_claims: List[Any] = []

    for claim in evidence_map:
        if not isinstance(claim, Mapping):
            new_claims.append(claim)
            continue
        cited = [str(x) for x in _as_list(claim.get("supporting_evidence_ids"))]
        resolved = [x for x in cited if x in pool]
        unresolved = [x for x in cited if x not in pool]
        all_resolved.update(resolved)
        all_unresolved.update(unresolved)

        new_claim = dict(claim)
        new_claim["_postprocess_original_supporting_evidence_ids"] = cited
        new_claim["_postprocess_resolved_supporting_evidence_ids"] = resolved
        new_claim["_postprocess_unresolved_supporting_evidence_ids"] = unresolved
        new_claim["_postprocess_rebinds"] = []
        new_claims.append(new_claim)

    return new_claims, all_resolved, all_unresolved


def _apply_text_normalization(text: str) -> Tuple[str, int]:
    changed = 0
    for pattern, replacement in TEXT_NORMALIZATION_RULES:
        text, count = re.subn(pattern, replacement, text)
        changed += count
    return text, changed


def _classify(
    utype: str,
    draft_status: str,
    packet_support_state: str,
    unresolved_count: int,
    artifact_leakage_count: int = 0,
) -> Dict[str, Any]:
    """The review_action/provenance_quality/semantic_grade_provisional/evidence_reference_status/
    issue_flags decision table, empirically derived from 100% of the 165 rows in the one
    historical postprocess run available for validation - every combination below was
    directly observed with zero contradiction.
    """
    if utype == "topic":
        provenance_quality = "topic_evidence_or_child_kc_flow"
        packet_evidence_source = ""
    else:
        provenance_quality = PROVENANCE_QUALITY_BY_SUPPORT_STATE.get(packet_support_state, "fallback_source_lane")
        packet_evidence_source = PACKET_EVIDENCE_SOURCE_BY_SUPPORT_STATE.get(packet_support_state, "")

    semantic_grade_provisional = SEMANTIC_GRADE_BY_DRAFT_STATUS.get(draft_status, "usable_partial_needs_review")

    has_artifact_leakage = artifact_leakage_count > 0

    if draft_status == "abstained":
        review_action = "emit_segmentable_gap_packet"
        evidence_reference_status = "no_evidence_expected_for_segmentable_abstention"
        issue_flags = ["fallback_source_lane_not_bad_by_itself", "segmentable_non_grounding_abstention"]
        if has_artifact_leakage:
            issue_flags.append("artifact_leakage_detected")
        return {
            "review_action": review_action,
            "provenance_quality": provenance_quality,
            "packet_evidence_source": packet_evidence_source,
            "semantic_grade_provisional": semantic_grade_provisional,
            "evidence_reference_status": evidence_reference_status,
            "issue_flags": issue_flags,
        }

    evidence_reference_status = "has_unresolved_evidence_refs" if unresolved_count > 0 else "resolved_or_no_refs"
    is_weak_fallback = packet_support_state == "weak_fallback"

    # Precedence: unresolved evidence references remain the top review-action tier (existing,
    # unchanged behavior). Artifact leakage is a distinct, independently severe defect - a raw
    # internal ID or bracket citation reaching a human-facing definition - so it gets its own
    # tier, ranked above provenance/content caution but never silently dropped when it
    # co-occurs with unresolved refs (still recorded in issue_flags either way).
    if unresolved_count > 0:
        review_action = "review_with_evidence_reference_warning"
    elif has_artifact_leakage:
        review_action = "review_with_artifact_leakage_warning"
    elif is_weak_fallback:
        review_action = "review_with_provenance_caution"
    elif draft_status == "partial":
        review_action = "review_with_content_caution"
    else:
        review_action = "review_ready"

    issue_flags = []
    if is_weak_fallback:
        issue_flags.append("fallback_source_lane_not_bad_by_itself")
    if draft_status == "partial":
        issue_flags.append("partial_draft_needs_review")
    if unresolved_count > 0:
        issue_flags.append("unresolved_evidence_refs")
    if has_artifact_leakage:
        issue_flags.append("artifact_leakage_detected")

    return {
        "review_action": review_action,
        "provenance_quality": provenance_quality,
        "packet_evidence_source": packet_evidence_source,
        "semantic_grade_provisional": semantic_grade_provisional,
        "evidence_reference_status": evidence_reference_status,
        "issue_flags": issue_flags,
    }


def postprocess_row(
    row: Mapping[str, Any],
    *,
    accepted_baseline_run_id: str,
    postprocess_root: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Postprocess one drafts.jsonl row into its step67_v2_postprocessed_review_source form.

    Returns (new_row, audit_row) - audit_row is the flat dict written to
    postprocess_unit_audit.csv/.jsonl.
    """
    utype = _unit_type(row)
    draft = _as_dict(row.get("draft"))
    draft_key = _draft_key_for_unit_type(utype)
    draft_status = _draft_status(draft, utype)
    source_packet = _as_dict(row.get("source_packet"))
    packet_support_state = _text(source_packet.get("packet_support_state"))
    support_state_reason = _text(source_packet.get("support_state_reason"))

    pool = evidence_pool_for_row(row, utype)
    new_evidence_map, resolved_ids, unresolved_ids = _postprocess_evidence_map(draft, pool)

    unit_text = _text(_as_dict(draft.get(draft_key)).get("text"))
    _normalized_text, text_normalization_change_count = _apply_text_normalization(unit_text)

    # Strip internal-ID leaks that are safely separable from surrounding grammar (parenthetical
    # asides), then flag whatever remains (bare/non-parenthetical IDs, and any dangling
    # structural reference or bracket citation that slipped through despite upstream evidence
    # sanitization) rather than attempting a risky in-place removal on already-generated prose.
    _stripped_text, id_leak_strip_matches = strip_safely_parenthetical_id_leaks(_normalized_text)
    text_changed = bool(id_leak_strip_matches) or text_normalization_change_count > 0
    if text_changed:
        new_unit_draft = dict(_as_dict(draft.get(draft_key)))
        new_unit_draft["text"] = _stripped_text
    else:
        new_unit_draft = None

    artifact_leakage_matches = id_leak_strip_matches + detect_artifact_leakage(_stripped_text)

    classification = _classify(
        utype, draft_status, packet_support_state, len(unresolved_ids), len(artifact_leakage_matches)
    )

    knowledge_unit_id = _text(row.get("knowledge_unit_id"))
    canonical_name = _text(row.get("canonical_name"))

    review_preflight = {
        "schema_version": REVIEW_PREFLIGHT_SCHEMA_VERSION,
        "accepted_baseline_run_id": accepted_baseline_run_id,
        "knowledge_unit_id": knowledge_unit_id,
        "knowledge_unit_type": utype,
        "canonical_name": canonical_name,
        "draft_status": draft_status,
        "do_not_treat_as_expert_approved": True,
        "kc_specific_criteria_status": "expert_pending",
        "packet_support_state": packet_support_state,
        "packet_evidence_source": classification["packet_evidence_source"],
        "support_state_reason": support_state_reason,
        "provenance_quality": classification["provenance_quality"],
        "semantic_grade_provisional": classification["semantic_grade_provisional"],
        "evidence_reference_status": classification["evidence_reference_status"],
        "review_action": classification["review_action"],
        "issue_flags": classification["issue_flags"],
        "exact_resolved_supporting_evidence_ids": sorted(resolved_ids),
        "unresolved_supporting_evidence_ids": sorted(unresolved_ids),
        "rebound_supporting_evidence_ids": [],
        "text_normalization_change_count": text_normalization_change_count,
        "artifact_leakage_detected": bool(artifact_leakage_matches),
        "artifact_leakage_matches": artifact_leakage_matches,
    }

    new_draft = dict(draft)
    new_draft["evidence_map"] = new_evidence_map
    if new_unit_draft is not None:
        new_draft[draft_key] = new_unit_draft
    new_draft["review_preflight"] = review_preflight

    new_row = dict(row)
    new_row["draft"] = new_draft
    new_row["postprocess_metadata"] = {
        "schema_version": SCHEMA_VERSION,
        "original_run_id": accepted_baseline_run_id,
        "postprocess_root": postprocess_root,
        "source_row_preserved_except_derived_text_cleanup_and_evidence_map_annotations": True,
    }

    audit_row = {
        "knowledge_unit_id": knowledge_unit_id,
        "knowledge_unit_type": utype,
        "canonical_name": canonical_name,
        "draft_status": draft_status,
        "semantic_grade_provisional": classification["semantic_grade_provisional"],
        "provenance_quality": classification["provenance_quality"],
        "packet_evidence_source": classification["packet_evidence_source"],
        "packet_support_state": packet_support_state,
        "evidence_reference_status": classification["evidence_reference_status"],
        "exact_resolved_supporting_evidence_id_count": len(resolved_ids),
        "rebound_supporting_evidence_id_count": 0,
        "unresolved_supporting_evidence_id_count": len(unresolved_ids),
        "review_action": classification["review_action"],
        "issue_flags": "|".join(classification["issue_flags"]),
        "text_normalization_change_count": text_normalization_change_count,
        "unresolved_supporting_evidence_ids": ",".join(sorted(unresolved_ids)),
        "rebound_supporting_evidence_ids": "",
        "artifact_leakage_match_count": len(artifact_leakage_matches),
        "artifact_leakage_stripped_count": sum(1 for m in artifact_leakage_matches if m.get("stripped")),
        "artifact_leakage_matches": "|".join(
            f"{m['category']}:{'stripped' if m.get('stripped') else 'flagged'}:{m['match']}"
            for m in artifact_leakage_matches
        ),
    }

    return new_row, audit_row


def postprocess_review_source(
    *,
    source_drafts_jsonl: Path,
    output_dir: Path,
    run_id: str,
    accepted_baseline_run_id: str,
    postprocess_root: str,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_jsonl(source_drafts_jsonl)
    new_rows: List[Dict[str, Any]] = []
    audit_rows: List[Dict[str, Any]] = []

    for row in rows:
        new_row, audit_row = postprocess_row(
            row,
            accepted_baseline_run_id=accepted_baseline_run_id,
            postprocess_root=postprocess_root,
        )
        new_rows.append(new_row)
        audit_rows.append(audit_row)

    postprocessed_jsonl = output_dir / "step67_v2_postprocessed_review_source.jsonl"
    write_jsonl(postprocessed_jsonl, new_rows)

    unit_type_counter = Counter(a["knowledge_unit_type"] for a in audit_rows)
    draft_status_counter = Counter(a["draft_status"] for a in audit_rows)
    review_action_counter = Counter(a["review_action"] for a in audit_rows)
    provenance_quality_counter = Counter(a["provenance_quality"] for a in audit_rows)
    evidence_reference_status_counter = Counter(a["evidence_reference_status"] for a in audit_rows)
    semantic_grade_counter = Counter(a["semantic_grade_provisional"] for a in audit_rows)
    rebind_count = sum(a["rebound_supporting_evidence_id_count"] for a in audit_rows)
    unresolved_reference_count = sum(a["unresolved_supporting_evidence_id_count"] for a in audit_rows)
    rows_with_unresolved_refs = sum(1 for a in audit_rows if a["unresolved_supporting_evidence_id_count"] > 0)
    text_normalization_change_count = sum(a["text_normalization_change_count"] for a in audit_rows)
    # Rebinding (fuzzy-recovery of near-miss/typo'd evidence ids) is a real mechanism in the
    # original algorithm that this reconstruction cannot implement with confidence - it had
    # zero occurrences in the only historical run available to reverse-engineer it from (see
    # builder.py module docstring). A row with exactly 1 unresolved reference is exactly one
    # recoverable rebind away from a different evidence_reference_status/review_action
    # classification, so this count makes that exposure visible on every future run instead of
    # letting it silently accumulate.
    rebind_gap_exposure_count = sum(1 for a in audit_rows if a["unresolved_supporting_evidence_id_count"] == 1)
    artifact_leakage_total_match_count = sum(a["artifact_leakage_match_count"] for a in audit_rows)
    artifact_leakage_unit_count = sum(1 for a in audit_rows if a["artifact_leakage_match_count"] > 0)

    audit_csv_path = output_dir / "postprocess_unit_audit.csv"
    audit_jsonl_path = output_dir / "postprocess_unit_audit.jsonl"
    _write_audit_csv(audit_csv_path, audit_rows)
    write_jsonl(audit_jsonl_path, audit_rows)

    unresolved_refs_csv = output_dir / "unresolved_evidence_references.csv"
    _write_unresolved_refs_csv(unresolved_refs_csv, new_rows)

    artifact_leakage_csv = output_dir / "artifact_leakage_instances.csv"
    _write_artifact_leakage_csv(artifact_leakage_csv, new_rows)

    evidence_rebinds_csv = output_dir / "evidence_id_rebinds.csv"
    _write_rebinds_csv(evidence_rebinds_csv)

    text_changes_csv = output_dir / "text_normalization_changes.csv"
    _write_text_changes_csv(text_changes_csv, rows, new_rows)

    postprocessed_sha256 = sha256_file(postprocessed_jsonl)

    summary = {
        "schema_version": POSTPROCESS_SUMMARY_SCHEMA_VERSION,
        "accepted_baseline_run_id": accepted_baseline_run_id,
        "row_count": len(new_rows),
        "unit_type_counter": dict(unit_type_counter),
        "draft_status_counter": dict(draft_status_counter),
        "review_action_counter": dict(review_action_counter),
        "provenance_quality_counter": dict(provenance_quality_counter),
        "evidence_reference_status_counter": dict(evidence_reference_status_counter),
        "semantic_grade_counter": dict(semantic_grade_counter),
        "rebind_count": rebind_count,
        "unresolved_reference_count": unresolved_reference_count,
        "rows_with_unresolved_refs": rows_with_unresolved_refs,
        "rebind_gap_exposure_count": rebind_gap_exposure_count,
        "text_normalization_change_count": text_normalization_change_count,
        "artifact_leakage_total_match_count": artifact_leakage_total_match_count,
        "artifact_leakage_unit_count": artifact_leakage_unit_count,
        "postprocessed_jsonl": str(postprocessed_jsonl),
        "postprocessed_sha256": postprocessed_sha256,
        "postprocess_audit_csv": str(audit_csv_path),
        "postprocess_audit_jsonl": str(audit_jsonl_path),
        "unresolved_refs_csv": str(unresolved_refs_csv),
        "evidence_rebinds_csv": str(evidence_rebinds_csv),
        "artifact_leakage_csv": str(artifact_leakage_csv),
        "text_changes_csv": str(text_changes_csv),
        "source_drafts_jsonl": str(source_drafts_jsonl),
        "decision": "POSTPROCESSED_REVIEW_SOURCE_READY",
        "issues": [],
    }

    summary_json = output_dir / "STEP67_V2_POSTPROCESS_SUMMARY.json"
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    closeout_txt = output_dir / "CLOSEOUT_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt"
    closeout_txt.write_text(
        "\n".join(
            [
                "STEP67_V2_POSTPROCESSED_REVIEW_SOURCE_CLOSEOUT",
                "DECISION=POSTPROCESSED_REVIEW_SOURCE_READY",
                f"ACCEPTED_BASELINE_RUN_ID={accepted_baseline_run_id}",
                f"ROW_COUNT={summary['row_count']}",
                f"UNIT_TYPE_COUNTER={summary['unit_type_counter']}",
                f"DRAFT_STATUS_COUNTER={summary['draft_status_counter']}",
                f"REVIEW_ACTION_COUNTER={summary['review_action_counter']}",
                f"PROVENANCE_QUALITY_COUNTER={summary['provenance_quality_counter']}",
                f"EVIDENCE_REFERENCE_STATUS_COUNTER={summary['evidence_reference_status_counter']}",
                f"REBIND_COUNT={summary['rebind_count']}",
                f"UNRESOLVED_REFERENCE_COUNT={summary['unresolved_reference_count']}",
                f"ROWS_WITH_UNRESOLVED_REFS={summary['rows_with_unresolved_refs']}",
                f"REBIND_GAP_EXPOSURE_COUNT={summary['rebind_gap_exposure_count']}",
                f"TEXT_NORMALIZATION_CHANGE_COUNT={summary['text_normalization_change_count']}",
                f"ARTIFACT_LEAKAGE_TOTAL_MATCH_COUNT={summary['artifact_leakage_total_match_count']}",
                f"ARTIFACT_LEAKAGE_UNIT_COUNT={summary['artifact_leakage_unit_count']}",
                f"POSTPROCESSED_JSONL={postprocessed_jsonl}",
                f"POSTPROCESSED_SHA256={postprocessed_sha256}",
                f"SUMMARY_JSON={summary_json}",
                f"AUDIT_CSV={audit_csv_path}",
                f"UNRESOLVED_REFS_CSV={unresolved_refs_csv}",
                f"EVIDENCE_REBINDS_CSV={evidence_rebinds_csv}",
                f"ARTIFACT_LEAKAGE_CSV={artifact_leakage_csv}",
                "ISSUES=[]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        **summary,
        "closeout_txt": str(closeout_txt),
    }


def _write_audit_csv(path: Path, audit_rows: List[Dict[str, Any]]) -> None:
    import csv

    fields = [
        "knowledge_unit_id",
        "knowledge_unit_type",
        "canonical_name",
        "draft_status",
        "semantic_grade_provisional",
        "provenance_quality",
        "packet_evidence_source",
        "packet_support_state",
        "evidence_reference_status",
        "exact_resolved_supporting_evidence_id_count",
        "rebound_supporting_evidence_id_count",
        "unresolved_supporting_evidence_id_count",
        "review_action",
        "issue_flags",
        "text_normalization_change_count",
        "unresolved_supporting_evidence_ids",
        "rebound_supporting_evidence_ids",
        "artifact_leakage_match_count",
        "artifact_leakage_stripped_count",
        "artifact_leakage_matches",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in audit_rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _write_unresolved_refs_csv(path: Path, new_rows: List[Dict[str, Any]]) -> None:
    import csv

    fields = ["knowledge_unit_id", "knowledge_unit_type", "canonical_name", "evidence_map_index", "unresolved_id", "claim_text"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in new_rows:
            draft = _as_dict(row.get("draft"))
            for idx, claim in enumerate(_as_list(draft.get("evidence_map"))):
                if not isinstance(claim, Mapping):
                    continue
                for unresolved_id in _as_list(claim.get("_postprocess_unresolved_supporting_evidence_ids")):
                    writer.writerow(
                        {
                            "knowledge_unit_id": row.get("knowledge_unit_id"),
                            "knowledge_unit_type": row.get("knowledge_unit_type"),
                            "canonical_name": row.get("canonical_name"),
                            "evidence_map_index": idx,
                            "unresolved_id": unresolved_id,
                            "claim_text": claim.get("claim"),
                        }
                    )


def _write_artifact_leakage_csv(path: Path, new_rows: List[Dict[str, Any]]) -> None:
    import csv

    fields = ["knowledge_unit_id", "knowledge_unit_type", "canonical_name", "category", "stripped", "match"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in new_rows:
            draft = _as_dict(row.get("draft"))
            preflight = _as_dict(draft.get("review_preflight"))
            for m in _as_list(preflight.get("artifact_leakage_matches")):
                if not isinstance(m, Mapping):
                    continue
                writer.writerow(
                    {
                        "knowledge_unit_id": row.get("knowledge_unit_id"),
                        "knowledge_unit_type": row.get("knowledge_unit_type"),
                        "canonical_name": row.get("canonical_name"),
                        "category": m.get("category"),
                        "stripped": bool(m.get("stripped")),
                        "match": m.get("match"),
                    }
                )


def _write_rebinds_csv(path: Path) -> None:
    import csv

    fields = ["knowledge_unit_id", "knowledge_unit_type", "canonical_name", "evidence_map_index", "original_id", "rebound_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        # No rebinds are ever produced (see module docstring) - header-only file, matching the
        # historical run's own rebind_count=0 shape.


def _write_text_changes_csv(path: Path, original_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> None:
    import csv

    fields = ["knowledge_unit_id", "knowledge_unit_type", "canonical_name", "pattern", "replacement"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for original_row, new_row in zip(original_rows, new_rows):
            utype = _unit_type(new_row)
            draft_key = _draft_key_for_unit_type(utype)
            original_text = _text(_as_dict(_as_dict(original_row.get("draft")).get(draft_key)).get("text"))
            if not original_text:
                continue
            for pattern, replacement in TEXT_NORMALIZATION_RULES:
                if re.search(pattern, original_text):
                    writer.writerow(
                        {
                            "knowledge_unit_id": new_row.get("knowledge_unit_id"),
                            "knowledge_unit_type": utype,
                            "canonical_name": new_row.get("canonical_name"),
                            "pattern": pattern,
                            "replacement": replacement,
                        }
                    )
