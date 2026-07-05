from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Tuple


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def norm_key(value: Any) -> str:
    return normalize_text(value).lower()


def clip_text(value: Any, max_chars: int) -> str:
    text = normalize_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: pathlib.Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    invalid = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    invalid += 1
            except Exception:
                invalid += 1
    return rows, invalid


def write_jsonl(path: pathlib.Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def row_id(row: Mapping[str, Any]) -> str:
    for key in ("knowledge_unit_id", "kc_id", "topic_id", "node_id", "unit_id", "id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def unit_type(row: Mapping[str, Any]) -> str:
    value = row.get("knowledge_unit_type") or row.get("unit_type") or ""
    if value:
        return str(value)
    rid = row_id(row)
    return "kc" if rid.startswith("KC_") else ""


def canonical_name(row: Mapping[str, Any]) -> str:
    return normalize_text(row.get("canonical_name") or row.get("label") or row.get("name") or "")


def source_hierarchy_path(row: Mapping[str, Any]) -> List[str]:
    value = row.get("source_hierarchy_path") or row.get("ancestor_labels") or row.get("topic_path_labels") or []
    return [normalize_text(x) for x in value if normalize_text(x)]


def hierarchy_prefixes_for_kc_path(path: Tuple[str, ...]) -> List[Tuple[str, ...]]:
    if len(path) <= 1:
        return []
    return [path[:i] for i in range(1, len(path))]


def field_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, dict):
        return normalize_text(value.get("text") or "")
    return normalize_text(value)


def field_status(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, dict):
        return str(value.get("status") or "")
    return ""


def evidence_text_from_overlay(row: Mapping[str, Any], max_chars: int) -> str:
    for key in ("quote_surface", "original_quote_surface", "source_block_text", "original_source_block_text"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return clip_text(value, max_chars)
    return ""


def evidence_text_from_pack_item(item: Mapping[str, Any], max_chars: int) -> str:
    for key in ("text", "quote", "candidate_sentence_text", "source_block_text", "preview"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return clip_text(value, max_chars)
    return ""


def score_overlay_evidence(row: Mapping[str, Any]) -> float:
    score = 0.0
    try:
        score += float(row.get("alignment_score") or 0.0)
    except Exception:
        pass

    support = row.get("support_profile") if isinstance(row.get("support_profile"), dict) else {}
    role_hint = row.get("role_hint") if isinstance(row.get("role_hint"), dict) else {}
    text = normalize_text(row.get("quote_surface") or row.get("source_block_text") or "")
    low = text.lower()

    if support.get("definition_candidate") or support.get("definition_signal"):
        score += 12.0
    if support.get("scope_signal") or support.get("context_candidate"):
        score += 8.0
    if support.get("equation_support") or support.get("formula_candidate"):
        score += 5.0
    if "definition" in str(role_hint).lower():
        score += 8.0
    if "scope" in str(role_hint).lower() or "context" in str(role_hint).lower():
        score += 5.0
    if len(text) >= 80:
        score += 3.0
    if len(text) < 50:
        score -= 6.0
    if any(low.endswith(x) for x in ("can easily", "is that", "such as", "and", "or", "to", "of")):
        score -= 12.0
    if bool(row.get("is_heading_like")):
        score -= 8.0
    if str(row.get("contamination_risk") or "").lower() == "high":
        score -= 8.0
    return score


def compact_overlay_evidence(row: Mapping[str, Any], max_chars: int) -> Dict[str, Any]:
    support = row.get("support_profile") if isinstance(row.get("support_profile"), dict) else {}
    return {
        "evidence_id": str(row.get("overlay_candidate_id") or ""),
        "text": evidence_text_from_overlay(row, max_chars),
        "source_block_text": clip_text(row.get("source_block_text") or "", max_chars),
        "role_hint": row.get("role_hint") if isinstance(row.get("role_hint"), dict) else {},
        "support_profile": {
            "classification": support.get("classification"),
            "definition_candidate": bool(support.get("definition_candidate") or support.get("definition_signal")),
            "scope_signal": bool(support.get("scope_signal")),
            "context_candidate": bool(support.get("context_candidate")),
            "equation_support": bool(support.get("equation_support")),
        },
        "doc_id": str(row.get("doc_id") or ""),
        "page_index": row.get("page_index"),
        "patch_heading": normalize_text(row.get("patch_heading") or row.get("original_patch_heading") or ""),
        "quote_verification_status": str(row.get("quote_verification_status") or ""),
        "contamination_risk": str(row.get("contamination_risk") or ""),
        "score_for_packet": round(score_overlay_evidence(row), 4),
    }


def compact_topic_evidence(item: Mapping[str, Any], max_chars: int) -> Dict[str, Any]:
    source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {}
    return {
        "evidence_id": str(item.get("candidate_id") or item.get("source_candidate_id") or item.get("scored_candidate_id") or ""),
        "text": evidence_text_from_pack_item(item, max_chars),
        "source_block_text": clip_text(item.get("source_block_text") or "", max_chars),
        "role": str(item.get("role") or item.get("slot_role") or ""),
        "roles": [str(x) for x in item.get("roles") or [] if str(x)],
        "doc_id": str(item.get("doc_id") or source_refs.get("doc_id") or ""),
        "page_index": item.get("page_index", source_refs.get("page_index")),
        "patch_heading": normalize_text(item.get("patch_heading") or source_refs.get("patch_heading") or ""),
        "selected_text_mode": str(item.get("selected_text_mode") or ""),
        "risk_flags": [str(x) for x in item.get("risk_flags") or [] if str(x)],
    }


def _pack_item_identity(item: Mapping[str, Any]) -> str:
    for key in ("candidate_id", "source_candidate_id", "scored_candidate_id", "source_row_id", "sentence_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    text = normalize_text(evidence_text_from_pack_item(item, 1000)).lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _unique_pack_items(items: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    seen: set[str] = set()
    out: List[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        text = evidence_text_from_pack_item(item, 1000)
        if not text:
            continue
        key = _pack_item_identity(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _first_nonempty_pack_lane(rows: Iterable[Mapping[str, Any]], key: str) -> List[Mapping[str, Any]]:
    for row in rows:
        value = row.get(key)
        if isinstance(value, list):
            items = [x for x in value if isinstance(x, Mapping)]
            if items:
                return items
    return []


def _pack_item_score(item: Mapping[str, Any]) -> float:
    for key in ("overall_score", "score", "alignment_score", "definition_anchor_score", "explanatory_anchor_score"):
        try:
            value = item.get(key)
            if value not in (None, ""):
                return float(value)
        except Exception:
            pass
    support = item.get("support_profile") if isinstance(item.get("support_profile"), Mapping) else {}
    try:
        return float(support.get("definition_anchor_score") or support.get("fallback_score") or 0.0)
    except Exception:
        return 0.0


def _review_needed_item_is_useful_for_synthesis(item: Mapping[str, Any]) -> bool:
    text = evidence_text_from_pack_item(item, 1000).lower()
    if len(text) < 40:
        return False

    roles = " ".join(str(x).lower() for x in (item.get("shapeaware_support_roles") or item.get("roles") or []))
    routing = str(item.get("routing_recommendation") or "").lower()
    risks = [str(x).lower() for x in (item.get("review_risk_flags") or item.get("risk_flags") or [])]

    hard_exclusion_risks = {
        "no_target_binding",
        "suspected_false_positive",
        "definition_subject_mismatch",
        "metadata_only",
        "bibliography_only",
    }
    if any(r in hard_exclusion_risks for r in risks):
        return False

    if routing == "positive_role_candidate":
        return True

    if any(x in roles for x in ("definition_anchor", "metric_formula_anchor", "formal_relation_anchor", "objective_function_anchor")):
        return True

    return False


def compact_kc_pack_evidence(item: Mapping[str, Any], max_chars: int, lane: str) -> Dict[str, Any]:
    source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), Mapping) else {}
    support_profile = item.get("support_profile") if isinstance(item.get("support_profile"), Mapping) else {}
    evidence_id = str(
        item.get("candidate_id")
        or item.get("source_candidate_id")
        or item.get("scored_candidate_id")
        or item.get("source_row_id")
        or item.get("sentence_id")
        or ""
    )

    return {
        "evidence_id": evidence_id,
        "text": evidence_text_from_pack_item(item, max_chars),
        "source_block_text": clip_text(item.get("source_block_text") or "", max_chars),
        "evidence_lane": lane,
        "role": str(item.get("role") or item.get("slot_role") or support_profile.get("preferred_support_role") or ""),
        "roles": [str(x) for x in (item.get("shapeaware_support_roles") or item.get("roles") or item.get("support_roles") or []) if str(x)],
        "routing_recommendation": str(item.get("routing_recommendation") or ""),
        "selected_text_mode": str(item.get("selected_text_mode") or ""),
        "review_risk_flags": [str(x) for x in (item.get("review_risk_flags") or item.get("risk_flags") or []) if str(x)],
        "doc_id": str(item.get("doc_id") or source_refs.get("doc_id") or ""),
        "page_index": item.get("page_index", source_refs.get("page_index")),
        "patch_heading": normalize_text(item.get("patch_heading") or source_refs.get("patch_heading") or ""),
        "sentence_id": str(item.get("sentence_id") or source_refs.get("sentence_id") or ""),
        "support_profile_summary": {
            "anchor_quality": support_profile.get("anchor_quality"),
            "candidate_source": support_profile.get("candidate_source"),
            "fallback_reason": support_profile.get("fallback_reason"),
            "evidence_shape_match": support_profile.get("evidence_shape_match"),
            "matched_surface_terms": support_profile.get("matched_surface_terms"),
        },
        "score_for_packet": round(_pack_item_score(item), 4),
    }


def select_kc_synthesis_evidence_from_embedded_pack(
    rows: List[Dict[str, Any]],
    *,
    evidence_limit: int,
    text_max_chars: int,
) -> List[Dict[str, Any]]:
    ordered_items = _unique_pack_items(_first_nonempty_pack_lane(rows, "ordered_pack_for_drafting"))

    review_items = _unique_pack_items(
        item
        for item in _first_nonempty_pack_lane(rows, "review_needed_evidence")
        if _review_needed_item_is_useful_for_synthesis(item)
    )
    review_items = sorted(review_items, key=_pack_item_score, reverse=True)

    selected: List[Dict[str, Any]] = []
    selected_ids: set[str] = set()

    for item in ordered_items:
        if len(selected) >= evidence_limit:
            break
        compact = compact_kc_pack_evidence(item, text_max_chars, "ordered_pack_for_drafting")
        key = compact.get("evidence_id") or compact.get("text")
        if key and key not in selected_ids:
            selected_ids.add(str(key))
            selected.append(compact)

    for item in review_items:
        if len(selected) >= evidence_limit:
            break
        compact = compact_kc_pack_evidence(item, text_max_chars, "review_needed_evidence_caution")
        key = compact.get("evidence_id") or compact.get("text")
        if key and key not in selected_ids:
            selected_ids.add(str(key))
            selected.append(compact)

    return selected


GENERIC_TARGET_BINDING_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "onto", "that", "this", "these", "those",
    "unit", "topic", "concept", "method", "approach", "model", "models", "data", "value",
    "values", "index", "indices", "measure", "measures", "metric", "metrics", "external",
    "internal", "basic", "core", "phase", "process", "problem", "definition", "algorithm",
}


def _match_normalize(value: Any) -> str:
    text = normalize_text(value).lower()
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _label_segments_for_binding(label: str) -> List[str]:
    raw = normalize_text(label)
    if not raw:
        return []
    pieces = [raw]

    # If a hierarchy label has an explicit delimiter, the rightmost segment is
    # often the more specific target. This is generic delimiter logic, not
    # domain-specific logic.
    for delimiter in (":", ";", "|", " / "):
        if delimiter in raw:
            right = raw.split(delimiter)[-1].strip()
            if right:
                pieces.insert(0, right)

    for match in re.findall(r"\(([^)]+)\)", raw):
        if match.strip():
            pieces.insert(0, match.strip())

    out: List[str] = []
    seen: set[str] = set()
    for piece in pieces:
        norm = _match_normalize(piece)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _target_binding_profile_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    exemplar = rows[0] if rows else {}
    labels: List[str] = []
    for key in ("canonical_name", "kc_name", "knowledge_unit_name", "title"):
        value = exemplar.get(key)
        if isinstance(value, str) and normalize_text(value):
            labels.append(value)

    for key in ("aliases", "alias_labels"):
        vals = exemplar.get(key)
        if isinstance(vals, list):
            labels.extend(str(v) for v in vals if normalize_text(v))

    phrases: List[str] = []
    for label in labels:
        phrases.extend(_label_segments_for_binding(label))

    phrase_seen: set[str] = set()
    phrase_out: List[str] = []
    for phrase in phrases:
        if phrase and phrase not in phrase_seen:
            phrase_seen.add(phrase)
            phrase_out.append(phrase)

    tokens = sorted({
        tok
        for phrase in phrase_out
        for tok in phrase.split()
        if len(tok) >= 3 and tok not in GENERIC_TARGET_BINDING_STOPWORDS
    })

    return {
        "phrases": phrase_out,
        "distinctive_tokens": tokens,
    }


def _overlay_candidate_text_for_binding(row: Mapping[str, Any]) -> str:
    return _match_normalize(" ".join([
        evidence_text_from_overlay(row, 2000),
        str(row.get("source_block_text") or ""),
        str(row.get("patch_heading") or row.get("original_patch_heading") or ""),
    ]))


def _overlay_row_has_target_binding(row: Mapping[str, Any], binding: Mapping[str, Any]) -> bool:
    text = _overlay_candidate_text_for_binding(row)
    if not text:
        return False

    phrases = [str(x) for x in binding.get("phrases") or [] if str(x)]
    tokens = [str(x) for x in binding.get("distinctive_tokens") or [] if str(x)]

    # Prefer phrase-level binding. For labels with delimiter-derived specific
    # segments, this prevents generic head terms from admitting broad fallback.
    for phrase in phrases:
        if len(phrase) >= 3 and phrase in text:
            return True

    # Token fallback is intentionally strict. It requires multiple distinctive
    # target tokens when phrase binding is unavailable.
    if len(tokens) >= 2 and sum(1 for tok in tokens if re.search(r"\b" + re.escape(tok) + r"\b", text)) >= 2:
        return True

    return False


def _overlay_row_has_admissible_source_shape(row: Mapping[str, Any]) -> bool:
    support = row.get("support_profile") if isinstance(row.get("support_profile"), Mapping) else {}
    role_hint = row.get("role_hint") if isinstance(row.get("role_hint"), Mapping) else {}

    if str(row.get("contamination_risk") or "").lower() == "high":
        return False

    quote_status = str(row.get("quote_verification_status") or "").lower()
    if quote_status and quote_status not in {"verified_original", "verified", "ok"}:
        return False

    if bool(support.get("definition_candidate") or support.get("definition_signal")):
        return True
    if bool(support.get("scope_signal") or support.get("context_candidate")):
        return True
    if bool(support.get("equation_support") or support.get("formula_candidate")):
        return True

    safe_role = str(role_hint.get("safe_role_hint") or "").lower()
    if safe_role in {"definition", "scope", "context", "equation", "formula", "procedure"}:
        return True

    return False


def select_target_bound_overlay_fallback_evidence(
    rows: List[Dict[str, Any]],
    *,
    evidence_limit: int,
    text_max_chars: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    binding = _target_binding_profile_from_rows(rows)
    considered = 0
    rejected_not_target_bound = 0
    rejected_bad_source_shape = 0
    selected: List[Dict[str, Any]] = []
    selected_ids: set[str] = set()

    for row in sorted(rows, key=score_overlay_evidence, reverse=True):
        considered += 1
        if not _overlay_row_has_target_binding(row, binding):
            rejected_not_target_bound += 1
            continue
        if not _overlay_row_has_admissible_source_shape(row):
            rejected_bad_source_shape += 1
            continue

        compact = compact_overlay_evidence(row, text_max_chars)
        compact["evidence_lane"] = "step66_overlay_target_bound_fallback"
        key = compact.get("evidence_id") or compact.get("text")
        if key and key not in selected_ids:
            selected_ids.add(str(key))
            selected.append(compact)
        if len(selected) >= evidence_limit:
            break

    report = {
        "binding_phrases": binding.get("phrases") or [],
        "binding_distinctive_tokens": binding.get("distinctive_tokens") or [],
        "overlay_fallback_considered": considered,
        "overlay_fallback_admitted": len(selected),
        "overlay_fallback_rejected_not_target_bound": rejected_not_target_bound,
        "overlay_fallback_rejected_bad_source_shape": rejected_bad_source_shape,
    }
    return selected, report


def build_kc_packet(
    kc_id: str,
    rows: List[Dict[str, Any]],
    sibling_names: List[str],
    child_draft: Mapping[str, Any] | None,
    *,
    evidence_limit: int,
    text_max_chars: int,
) -> Dict[str, Any]:
    exemplar = sorted(rows, key=lambda r: str(r.get("overlay_candidate_id") or ""))[0]
    selected_evidence = select_kc_synthesis_evidence_from_embedded_pack(
        rows,
        evidence_limit=evidence_limit,
        text_max_chars=text_max_chars,
    )
    overlay_fallback_report: Dict[str, Any] = {}
    insufficient_synthesis_support = False
    abstention_expected = False
    insufficient_support_reasons: List[str] = []

    packet_support_state = "draftable"
    support_state_reason = "embedded_step5x_pack_selected"
    weak_fallback_abstention_allowed = False

    if selected_evidence:
        packet_evidence_source = "embedded_step5x_pack"
    else:
        selected_evidence, overlay_fallback_report = select_target_bound_overlay_fallback_evidence(
            rows,
            evidence_limit=evidence_limit,
            text_max_chars=text_max_chars,
        )
        if selected_evidence:
            packet_evidence_source = "step66_overlay_target_bound_fallback"
            packet_support_state = "weak_fallback"
            support_state_reason = "target_bound_overlay_fallback_selected_without_embedded_ordered_evidence"
            weak_fallback_abstention_allowed = True
        else:
            packet_evidence_source = "insufficient_support_no_target_bound_fallback"
            packet_support_state = "insufficient_support"
            support_state_reason = "no_embedded_or_target_bound_synthesis_evidence"
            insufficient_synthesis_support = True
            abstention_expected = True
            insufficient_support_reasons.append("no_embedded_ordered_or_admissible_review_needed_evidence")
            insufficient_support_reasons.append("no_target_bound_overlay_fallback_evidence")
    draft = dict(child_draft or {})
    path = tuple(source_hierarchy_path(exemplar))

    return {
        "packet_version": "step67_v2_hierarchy_aware_synthesis_packet_v1",
        "knowledge_unit_type": "kc",
        "knowledge_unit_id": kc_id,
        "kc_id": kc_id,
        "canonical_name": canonical_name(exemplar),
        "aliases": [normalize_text(x) for x in exemplar.get("aliases") or [] if normalize_text(x)],
        "hierarchy": {
            "source_hierarchy_path": list(path),
            "topic_path": list(path[:-1]),
            "parent_topic_label": path[-2] if len(path) >= 2 else "",
            "leaf_label": path[-1] if path else canonical_name(exemplar),
            "ancestor_hier_node_ids": [str(x) for x in exemplar.get("ancestor_hier_node_ids") or [] if str(x)],
            "parent_hier_node_id": str(exemplar.get("parent_hier_node_id") or ""),
            "leaf_hier_node_id": str(exemplar.get("leaf_hier_node_id") or ""),
        },
        "sibling_kc_names": sibling_names,
        "upstream_summary": {
            "total_overlay_candidates": len(rows),
            "packet_evidence_source": packet_evidence_source,
            "embedded_ordered_pack_items": len(_first_nonempty_pack_lane(rows, "ordered_pack_for_drafting")),
            "embedded_review_needed_items": len(_first_nonempty_pack_lane(rows, "review_needed_evidence")),
            "selected_evidence_items": len(selected_evidence),
            "packet_support_state": packet_support_state,
            "support_state_reason": support_state_reason,
            "weak_fallback_abstention_allowed": weak_fallback_abstention_allowed,
            "insufficient_synthesis_support": insufficient_synthesis_support,
            "abstention_expected": abstention_expected,
            "insufficient_support_reasons": insufficient_support_reasons,
            "overlay_fallback_report": overlay_fallback_report,
            "definition_like_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("definition_candidate") or (r.get("support_profile") or {}).get("definition_signal")),
            "scope_like_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("scope_signal")),
            "context_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("context_candidate")),
            "formula_or_equation_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("equation_support") or (r.get("support_profile") or {}).get("formula_candidate")),
        },
        "packet_support_state": packet_support_state,
        "support_state_reason": support_state_reason,
        "weak_fallback_abstention_allowed": weak_fallback_abstention_allowed,
        "insufficient_synthesis_support": insufficient_synthesis_support,
        "abstention_expected": abstention_expected,
        "insufficient_support_reasons": insufficient_support_reasons,
        "evidence_for_synthesis": selected_evidence,
        "previous_step67_draft_summary": {
            "available": bool(draft),
            "draft_status": draft.get("draft_status"),
            "review_readiness": draft.get("review_readiness"),
            "definition_status": field_status(draft, "definition_full_candidate"),
            "definition_text": field_text(draft, "definition_full_candidate"),
            "scope_status": field_status(draft, "scope_candidate"),
            "scope_text": field_text(draft, "scope_candidate"),
            "hold_reasons": draft.get("hold_reasons"),
            "risk_flags": draft.get("risk_flags"),
        },
        "drafting_instruction": {
            "goal": "Create one integrated contextual KC draft useful for segmentation, tutor evaluation, and expert review.",
            "must_use": [
                "Use all relevant evidence_for_synthesis items, not only the first definitional-looking span.",
                "Treat evidence_lane=review_needed_evidence_caution as weaker reviewer-visible support: use it only when the quoted text directly supports the claim and mark uncertainty if needed.",
                "Connect compatible evidence into a coherent supported context object.",
                "Do not invent facts not supported by evidence.",
                "Every substantive claim must be linked to evidence_id values in evidence_map.",
                "If evidence is partial, produce partial status and explicit uncertainty notes rather than a fake complete definition.",
            ],
        },
    }


def build_topic_packet(
    topic: Mapping[str, Any],
    topic_prefix: Tuple[str, ...],
    direct_child_topic_prefixes: List[Tuple[str, ...]],
    descendant_topic_prefixes: List[Tuple[str, ...]],
    direct_child_kc_ids: List[str],
    descendant_kc_ids: List[str],
    kc_packets_by_id: Mapping[str, Mapping[str, Any]],
    child_drafts_by_id: Mapping[str, Mapping[str, Any]],
    topic_row_by_prefix: Mapping[Tuple[str, ...], Mapping[str, Any]],
    *,
    topic_evidence_limit: int,
    direct_child_kc_limit: int,
    descendant_kc_limit: int,
    child_topic_kc_preview_limit: int,
    text_max_chars: int,
) -> Dict[str, Any]:
    topic_id = row_id(topic)
    topic_name = canonical_name(topic)
    ordered = [x for x in topic.get("ordered_pack_for_drafting") or [] if isinstance(x, dict)]
    near_miss = [
        x
        for x in topic.get("topic_near_miss_review_items") or topic.get("near_miss_review_items") or []
        if isinstance(x, dict)
    ]

    direct_child_topic_summaries: List[Dict[str, Any]] = []
    for cp in direct_child_topic_prefixes:
        child_row = topic_row_by_prefix.get(cp, {})
        child_topic_label = cp[-1] if cp else canonical_name(child_row)

        child_desc_kcs = [
            kid
            for kid in descendant_kc_ids
            if tuple(kc_packets_by_id.get(kid, {}).get("hierarchy", {}).get("source_hierarchy_path") or [])[: len(cp)] == cp
        ]
        child_direct_kcs = [
            kid
            for kid in child_desc_kcs
            if len(kc_packets_by_id.get(kid, {}).get("hierarchy", {}).get("source_hierarchy_path") or []) == len(cp) + 1
        ]

        direct_child_topic_summaries.append(
            {
                "topic_id": row_id(child_row),
                "canonical_name": canonical_name(child_row) or child_topic_label,
                "topic_path": list(cp),
                "topic_evidence_count": len(child_row.get("ordered_pack_for_drafting") or []) if isinstance(child_row, dict) else 0,
                "direct_child_kc_count": len(child_direct_kcs),
                "descendant_kc_count": len(child_desc_kcs),
                "preview_child_kcs": [
                    {
                        "kc_id": kid,
                        "canonical_name": kc_packets_by_id.get(kid, {}).get("canonical_name"),
                        "previous_definition_status": field_status(child_drafts_by_id.get(kid, {}), "definition_full_candidate"),
                        "previous_scope_status": field_status(child_drafts_by_id.get(kid, {}), "scope_candidate"),
                    }
                    for kid in child_desc_kcs[:child_topic_kc_preview_limit]
                ],
            }
        )

    direct_child_kc_summaries: List[Dict[str, Any]] = []
    for kc_id in direct_child_kc_ids[:direct_child_kc_limit]:
        packet = kc_packets_by_id.get(kc_id) or {}
        draft = child_drafts_by_id.get(kc_id) or {}
        direct_child_kc_summaries.append(
            {
                "kc_id": kc_id,
                "canonical_name": packet.get("canonical_name") or canonical_name(draft),
                "hierarchy": packet.get("hierarchy"),
                "previous_definition_status": field_status(draft, "definition_full_candidate"),
                "previous_definition_text": field_text(draft, "definition_full_candidate"),
                "previous_scope_status": field_status(draft, "scope_candidate"),
                "previous_scope_text": field_text(draft, "scope_candidate"),
                "draft_status": draft.get("draft_status"),
                "review_readiness": draft.get("review_readiness"),
                "top_child_evidence": list((packet.get("evidence_for_synthesis") or [])[:3]),
            }
        )

    descendant_preview_ids = [
        kid
        for kid in descendant_kc_ids
        if kid not in set(direct_child_kc_ids)
    ][:descendant_kc_limit]

    descendant_kc_summaries: List[Dict[str, Any]] = []
    for kc_id in descendant_preview_ids:
        packet = kc_packets_by_id.get(kc_id) or {}
        draft = child_drafts_by_id.get(kc_id) or {}
        descendant_kc_summaries.append(
            {
                "kc_id": kc_id,
                "canonical_name": packet.get("canonical_name") or canonical_name(draft),
                "topic_path": (packet.get("hierarchy") or {}).get("topic_path"),
                "previous_definition_status": field_status(draft, "definition_full_candidate"),
                "previous_scope_status": field_status(draft, "scope_candidate"),
                "draft_status": draft.get("draft_status"),
            }
        )

    return {
        "packet_version": "step67_v2_hierarchy_aware_topic_synthesis_packet_v1",
        "knowledge_unit_type": "topic",
        "knowledge_unit_id": topic_id,
        "topic_id": topic_id,
        "canonical_name": topic_name,
        "topic_hierarchy": {
            "topic_path": list(topic_prefix),
            "parent_topic_path": list(topic_prefix[:-1]),
            "parent_topic_label": topic_prefix[-2] if len(topic_prefix) >= 2 else "",
            "direct_child_topic_count": len(direct_child_topic_prefixes),
            "direct_child_topic_labels": [p[-1] for p in direct_child_topic_prefixes],
            "descendant_topic_count": len(descendant_topic_prefixes),
            "descendant_topic_labels": [p[-1] for p in descendant_topic_prefixes],
            "direct_child_kc_count": len(direct_child_kc_ids),
            "descendant_kc_count": len(descendant_kc_ids),
        },
        "aliases": [normalize_text(x) for x in topic.get("aliases") or [] if normalize_text(x)],
        "topic_evidence_for_synthesis": [
            compact_topic_evidence(item, text_max_chars)
            for item in ordered[:topic_evidence_limit]
        ],
        "direct_child_topic_summary": {
            "count": len(direct_child_topic_summaries),
            "child_topics": direct_child_topic_summaries,
        },
        "direct_child_kc_summary": {
            "count": len(direct_child_kc_ids),
            "included_count": len(direct_child_kc_summaries),
            "child_kcs": direct_child_kc_summaries,
        },
        "descendant_kc_summary": {
            "count": len(descendant_kc_ids),
            "included_preview_count": len(descendant_kc_summaries),
            "descendant_kcs_preview": descendant_kc_summaries,
        },
        "topic_near_miss_or_gap_context": [
            {
                "candidate_id": str(item.get("candidate_id") or item.get("scored_candidate_id") or ""),
                "preview": clip_text(item.get("preview") or item.get("text") or "", text_max_chars),
                "near_miss_reason": str(item.get("near_miss_reason") or ""),
                "risk_flags": [str(x) for x in item.get("risk_flags") or [] if str(x)],
                "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {},
            }
            for item in near_miss[:8]
        ],
        "drafting_instruction": {
            "goal": "Create one integrated topic draft that respects the topic hierarchy.",
            "must_use": [
                "If direct_child_topic_summary is nonempty, synthesize the topic primarily from direct child topics, then use direct child KCs and descendant KCs as support.",
                "If direct_child_topic_summary is empty, synthesize from direct child KCs plus topic-level evidence.",
                "Use topic_evidence_for_synthesis to ground topic-level framing.",
                "Do not draft a topic from one clipped topic evidence sentence alone.",
                "Do not flatten a parent topic into an unstructured list of all descendant KCs.",
                "Every substantive topic claim must be linked to topic evidence IDs, child topic IDs, or child KC IDs in evidence_map.",
            ],
        },
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step66-set", required=True, type=pathlib.Path)
    ap.add_argument("--topic5x-pack", required=True, type=pathlib.Path)
    ap.add_argument("--child-kc-drafts", required=True, type=pathlib.Path)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--kc-evidence-limit", type=int, default=18)
    ap.add_argument("--topic-evidence-limit", type=int, default=8)
    ap.add_argument("--direct-child-kc-limit", type=int, default=24)
    ap.add_argument("--descendant-kc-limit", type=int, default=24)
    ap.add_argument("--child-topic-kc-preview-limit", type=int, default=8)
    ap.add_argument("--text-max-chars", type=int, default=2200)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    step66_set = read_json(args.step66_set)
    overlay_path = pathlib.Path(step66_set.get("artifacts", {}).get("candidate_sentence_overlay_jsonl") or "")
    if not overlay_path.is_absolute():
        overlay_path = pathlib.Path.cwd() / overlay_path

    overlay_rows, overlay_invalid = read_jsonl(overlay_path)
    topic_rows, topic_invalid = read_jsonl(args.topic5x_pack)
    child_drafts, child_drafts_invalid = read_jsonl(args.child_kc_drafts)

    child_drafts_by_id = {row_id(r): r for r in child_drafts if row_id(r)}

    rows_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    kc_path_by_id: Dict[str, Tuple[str, ...]] = {}
    for row in overlay_rows:
        kid = str(row.get("kc_id") or "")
        path = tuple(source_hierarchy_path(row))
        if kid and path:
            rows_by_kc[kid].append(row)
            kc_path_by_id.setdefault(kid, path)

    topic_rows_by_name = {norm_key(canonical_name(r)): r for r in topic_rows if canonical_name(r)}
    topic_names = set(topic_rows_by_name.keys())

    topic_prefixes_by_name: Dict[str, List[Tuple[str, ...]]] = defaultdict(list)
    all_topic_prefixes_in_overlay: set[Tuple[str, ...]] = set()
    for path in set(kc_path_by_id.values()):
        for prefix in hierarchy_prefixes_for_kc_path(path):
            all_topic_prefixes_in_overlay.add(prefix)
            label = norm_key(prefix[-1])
            if label in topic_names and prefix not in topic_prefixes_by_name[label]:
                topic_prefixes_by_name[label].append(prefix)

    ambiguous_topics = {
        topic_rows_by_name[name].get("canonical_name") or name: [list(p) for p in prefixes]
        for name, prefixes in topic_prefixes_by_name.items()
        if len(prefixes) > 1
    }

    missing_topic_prefixes = [
        canonical_name(row)
        for name, row in topic_rows_by_name.items()
        if not topic_prefixes_by_name.get(name)
    ]

    topic_row_by_prefix: Dict[Tuple[str, ...], Mapping[str, Any]] = {}
    for name, prefixes in topic_prefixes_by_name.items():
        if len(prefixes) == 1:
            topic_row_by_prefix[prefixes[0]] = topic_rows_by_name[name]

    parent_label_by_kc = {
        kid: path[-2] if len(path) >= 2 else ""
        for kid, path in kc_path_by_id.items()
    }

    sibling_names_by_parent: Dict[str, List[str]] = defaultdict(list)
    for kid, rows in rows_by_kc.items():
        parent = parent_label_by_kc.get(kid, "")
        if parent and rows:
            sibling_names_by_parent[parent].append(canonical_name(rows[0]))

    kc_packets = []
    kc_packets_by_id: Dict[str, Dict[str, Any]] = {}
    for kid in sorted(rows_by_kc):
        rows = rows_by_kc[kid]
        parent = parent_label_by_kc.get(kid, "")
        siblings = [x for x in sorted(set(sibling_names_by_parent.get(parent, []))) if x != canonical_name(rows[0])]
        packet = build_kc_packet(
            kid,
            rows,
            siblings,
            child_drafts_by_id.get(kid),
            evidence_limit=args.kc_evidence_limit,
            text_max_chars=args.text_max_chars,
        )
        kc_packets.append(packet)
        kc_packets_by_id[kid] = packet

    topic_packets = []
    topic_topology_reports = []
    for prefix, topic_row in sorted(topic_row_by_prefix.items(), key=lambda x: x[0]):
        direct_child_topic_prefixes = sorted(
            p for p in topic_row_by_prefix
            if len(p) == len(prefix) + 1 and p[: len(prefix)] == prefix
        )
        descendant_topic_prefixes = sorted(
            p for p in topic_row_by_prefix
            if len(p) > len(prefix) and p[: len(prefix)] == prefix
        )
        direct_child_kc_ids = sorted(
            kid for kid, path in kc_path_by_id.items()
            if len(path) == len(prefix) + 1 and path[: len(prefix)] == prefix
        )
        descendant_kc_ids = sorted(
            kid for kid, path in kc_path_by_id.items()
            if len(path) > len(prefix) and path[: len(prefix)] == prefix
        )

        packet = build_topic_packet(
            topic_row,
            prefix,
            direct_child_topic_prefixes,
            descendant_topic_prefixes,
            direct_child_kc_ids,
            descendant_kc_ids,
            kc_packets_by_id,
            child_drafts_by_id,
            topic_row_by_prefix,
            topic_evidence_limit=args.topic_evidence_limit,
            direct_child_kc_limit=args.direct_child_kc_limit,
            descendant_kc_limit=args.descendant_kc_limit,
            child_topic_kc_preview_limit=args.child_topic_kc_preview_limit,
            text_max_chars=args.text_max_chars,
        )
        topic_packets.append(packet)
        topic_topology_reports.append(
            {
                "topic_id": row_id(topic_row),
                "canonical_name": canonical_name(topic_row),
                "topic_path": list(prefix),
                "direct_child_topic_count": len(direct_child_topic_prefixes),
                "direct_child_topic_labels": [p[-1] for p in direct_child_topic_prefixes],
                "descendant_topic_count": len(descendant_topic_prefixes),
                "direct_child_kc_count": len(direct_child_kc_ids),
                "descendant_kc_count": len(descendant_kc_ids),
                "topic_evidence_count": len(topic_row.get("ordered_pack_for_drafting") or []),
            }
        )

    all_packets = [*kc_packets, *topic_packets]

    packets_jsonl = args.out_dir / "step67_v2_hierarchy_aware_synthesis_packets.jsonl"
    kc_packets_jsonl = args.out_dir / "step67_v2_hierarchy_aware_kc_synthesis_packets.jsonl"
    topic_packets_jsonl = args.out_dir / "step67_v2_hierarchy_aware_topic_synthesis_packets.jsonl"
    topology_json = args.out_dir / "step67_v2_topic_topology_report.json"
    stats_json = args.out_dir / "step67_v2_hierarchy_aware_synthesis_packet_stats.json"
    report_md = args.out_dir / "step67_v2_hierarchy_aware_synthesis_packet_report.md"

    write_jsonl(packets_jsonl, all_packets)
    write_jsonl(kc_packets_jsonl, kc_packets)
    write_jsonl(topic_packets_jsonl, topic_packets)
    write_json(topology_json, topic_topology_reports)

    topic_child_topic_counter = Counter(r["direct_child_topic_count"] for r in topic_topology_reports)
    topic_direct_kc_counter = Counter(r["direct_child_kc_count"] for r in topic_topology_reports)
    topic_desc_kc_counter = Counter(r["descendant_kc_count"] for r in topic_topology_reports)

    orphan_topics = [
        r["canonical_name"]
        for r in topic_topology_reports
        if r["direct_child_topic_count"] == 0 and r["direct_child_kc_count"] == 0
    ]

    zero_topic_evidence = [
        r["canonical_name"]
        for r in topic_topology_reports
        if r["topic_evidence_count"] == 0
    ]

    failures = []
    warnings = []

    if overlay_invalid:
        failures.append({"code": "overlay_invalid_json_rows", "count": overlay_invalid})
    if topic_invalid:
        failures.append({"code": "topic_pack_invalid_json_rows", "count": topic_invalid})
    if child_drafts_invalid:
        failures.append({"code": "child_drafts_invalid_json_rows", "count": child_drafts_invalid})
    if ambiguous_topics:
        failures.append({"code": "ambiguous_topic_label_to_hierarchy_prefix_mapping", "topics": ambiguous_topics})
    if missing_topic_prefixes:
        failures.append({"code": "topic_pack_rows_missing_from_overlay_hierarchy", "topics": missing_topic_prefixes})
    if orphan_topics:
        failures.append({"code": "topic_nodes_with_no_direct_child_topics_or_direct_child_kcs", "topics": orphan_topics})
    if zero_topic_evidence:
        warnings.append({"code": "topics_without_topic_level_evidence", "topics": zero_topic_evidence})

    decision = "PASS_STEP67_V2_HIERARCHY_AWARE_SYNTHESIS_PACKETS_READY_FOR_MANUAL_PACKET_REVIEW" if not failures else "FAIL_STEP67_V2_HIERARCHY_AWARE_SYNTHESIS_PACKET_BUILD"

    stats = {
        "schema_version": "step67_v2_hierarchy_aware_synthesis_packet_stats_v1",
        "created_utc": now_utc(),
        "decision": decision,
        "ready_for_manual_packet_review": not failures,
        "ready_for_model_smoke": False,
        "inputs": {
            "step66_set": str(args.step66_set),
            "step66_overlay": str(overlay_path),
            "topic5x_pack": str(args.topic5x_pack),
            "child_kc_drafts": str(args.child_kc_drafts),
        },
        "outputs": {
            "all_packets_jsonl": str(packets_jsonl),
            "kc_packets_jsonl": str(kc_packets_jsonl),
            "topic_packets_jsonl": str(topic_packets_jsonl),
            "topic_topology_json": str(topology_json),
            "stats_json": str(stats_json),
            "report_md": str(report_md),
        },
        "metrics": {
            "overlay_rows": len(overlay_rows),
            "overlay_invalid_json_rows": overlay_invalid,
            "kc_packet_count": len(kc_packets),
            "topic_packet_count": len(topic_packets),
            "all_packet_count": len(all_packets),
            "topic_pack_rows": len(topic_rows),
            "child_draft_rows": len(child_drafts),
            "child_draft_invalid_json_rows": child_drafts_invalid,
            "topic_direct_child_topic_count_counter": dict(topic_child_topic_counter),
            "topic_direct_child_kc_count_counter": dict(topic_direct_kc_counter),
            "topic_descendant_kc_count_counter": dict(topic_desc_kc_counter),
            "ambiguous_topic_count": len(ambiguous_topics),
            "missing_topic_prefix_count": len(missing_topic_prefixes),
            "orphan_topic_count": len(orphan_topics),
            "zero_topic_evidence_count": len(zero_topic_evidence),
            "zero_topic_evidence": zero_topic_evidence,
        },
        "failures": failures,
        "warnings": warnings,
        "hashes": {
            "packets_sha256": sha256_file(packets_jsonl),
            "kc_packets_sha256": sha256_file(kc_packets_jsonl),
            "topic_packets_sha256": sha256_file(topic_packets_jsonl),
            "topology_sha256": sha256_file(topology_json),
        },
        "policy": {
            "no_model_calls": True,
            "no_gpu_required": True,
            "no_pointer_mutation": True,
            "domain_agnostic_code": True,
            "topic_packets_preserve_direct_child_topic_structure": True,
            "topic_packets_separate_direct_child_kcs_from_descendant_kcs": True,
            "parent_topic_drafting_must_not_flatten_all_descendant_kcs": True,
        },
    }

    write_json(stats_json, stats)

    md = []
    md.append("# Step6.7 v2 hierarchy-aware synthesis packet report")
    md.append("")
    md.append(f"- decision: `{decision}`")
    md.append(f"- ready_for_manual_packet_review: `{not failures}`")
    md.append(f"- ready_for_model_smoke: `False`")
    md.append(f"- kc_packet_count: `{len(kc_packets)}`")
    md.append(f"- topic_packet_count: `{len(topic_packets)}`")
    md.append(f"- overlay_rows: `{len(overlay_rows)}`")
    md.append("")
    md.append("## Topic topology")
    for r in topic_topology_reports:
        md.append(
            f"- `{r['canonical_name']}` path={r['topic_path']} "
            f"direct_child_topics={r['direct_child_topic_count']} "
            f"direct_child_kcs={r['direct_child_kc_count']} "
            f"descendant_kcs={r['descendant_kc_count']} "
            f"topic_evidence={r['topic_evidence_count']}"
        )
    md.append("")
    md.append("## Failures")
    if failures:
        for item in failures:
            md.append(f"- `{item['code']}`: {json.dumps(item, ensure_ascii=False)}")
    else:
        md.append("- none")
    md.append("")
    md.append("## Warnings")
    if warnings:
        for item in warnings:
            md.append(f"- `{item['code']}`: {json.dumps(item, ensure_ascii=False)}")
    else:
        md.append("- none")

    report_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "decision": decision,
        "ready_for_manual_packet_review": not failures,
        "ready_for_model_smoke": False,
        "kc_packet_count": len(kc_packets),
        "topic_packet_count": len(topic_packets),
        "topic_direct_child_topic_count_counter": dict(topic_child_topic_counter),
        "topic_direct_child_kc_count_counter": dict(topic_direct_kc_counter),
        "topic_descendant_kc_count_counter": dict(topic_desc_kc_counter),
        "ambiguous_topic_count": len(ambiguous_topics),
        "missing_topic_prefix_count": len(missing_topic_prefixes),
        "orphan_topic_count": len(orphan_topics),
        "zero_topic_evidence_count": len(zero_topic_evidence),
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "packets_jsonl": str(packets_jsonl),
        "kc_packets_jsonl": str(kc_packets_jsonl),
        "topic_packets_jsonl": str(topic_packets_jsonl),
        "topology_json": str(topology_json),
        "stats_json": str(stats_json),
        "report_md": str(report_md),
    }, indent=2, ensure_ascii=False))

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
