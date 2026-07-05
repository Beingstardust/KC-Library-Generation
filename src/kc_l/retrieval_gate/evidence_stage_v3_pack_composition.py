from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    read_json_from_spec,
    read_jsonl_from_spec,
    resolve_related_input_spec,
    resolve_repo_path,
    parse_input_spec,
)
from kc_l.utils.json_io import write_json, write_jsonl
from kc_l.retrieval_gate.feedback_loop import write_retrieval_gap_artifacts
from kc_l.retrieval_gate.shapeaware_shadow import compose_shapeaware_shadow_pack
from kc_l.retrieval_gate.evidence_admission import normalize_evidence_admission


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_CONTRACT_VERSION = "step5x_v3_evidence_packs_v1"
V4C_ORDERED_PACK_QUALITY_GUARD_VERSION = "v4c_recovered_204794_overlay_ordered_pack_quality_guard_20260515"
DEFAULT_OUTPUT_ROOT = "data/processed/evidence_stage_v3_evidence_packs"
DEFAULT_SET_MANIFEST_ROOT = "data/processed/evidence_stage_v3_evidence_packs/_sets"

POSITIVE_ROLES: Tuple[str, ...] = (
    "definition_kernel",
    "explanatory_gloss",
    "scope_condition",
    "formula_notation",
    "example_or_procedure",
)
AUXILIARY_ROLES: Tuple[str, ...] = ("context_completion",)
GUARDRAIL_ROLES: Tuple[str, ...] = ("sibling_contrast",)
ALL_SLOT_ROLES: Tuple[str, ...] = POSITIVE_ROLES + AUXILIARY_ROLES + GUARDRAIL_ROLES
ORDERED_ALLOWED_ROLES: Tuple[str, ...] = POSITIVE_ROLES + AUXILIARY_ROLES
FORBIDDEN_OUTPUT_FIELDS: Tuple[str, ...] = (
    "seed_definition",
    "seed_keywords",
    "seed_floor",
    "seed_floor_fallback",
    "seed_definition_text",
    "seed_scope",
    "legacy_eligibility",
)
STAGE2_FORBIDDEN_PACK_FIELDS: Tuple[str, ...] = (
    "pack_quality",
    "ordered_pack_for_drafting",
    "slots",
    "eligibility",
)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _rel_path(path: Path, *, repo_root: Path = REPO_ROOT) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _as_int(value: Any, default: int = -1) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (Mapping, bytes)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def unique_preserve_order(values: Iterable[Any]) -> List[Any]:
    seen = set()
    out: List[Any] = []
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _binding_rank(row: Mapping[str, Any]) -> int:
    binding = dict(row.get("lexical_target_binding") or {})
    strength = str(binding.get("binding_strength") or "none")
    return {"none": 0, "weak": 1, "usable": 2, "strong": 3}.get(strength, 0)


def _role_score(row: Mapping[str, Any], role: str) -> float:
    role_scores = dict(row.get("role_scores") or {})
    return _as_float(role_scores.get(role), 0.0)


def _overall_score(row: Mapping[str, Any]) -> float:
    quality = dict(row.get("candidate_quality") or {})
    return _as_float(quality.get("overall_score"), 0.0)


def _source_order(row: Mapping[str, Any]) -> Tuple[int, int, int, str, str]:
    return (
        _as_int(row.get("page_index"), 10**9),
        _as_int(row.get("sent_idx"), 10**9),
        _as_int(row.get("char_start"), 10**9),
        str(row.get("block_id") or ""),
        str(row.get("candidate_id") or ""),
    )


def _ranking_key(row: Mapping[str, Any], role: str) -> Tuple[float, float, int, Tuple[int, int, int, str, str]]:
    return (
        -_role_score(row, role),
        -_overall_score(row),
        -_binding_rank(row),
        _source_order(row),
    )


def _evidence_admission(row: Mapping[str, Any]) -> Dict[str, Any]:
    return normalize_evidence_admission(row)


def _admission_decision(row: Mapping[str, Any]) -> str:
    return str(_evidence_admission(row).get("decision") or "")


def _admission_role(row: Mapping[str, Any]) -> str:
    return str(_evidence_admission(row).get("role") or "")


def _compatible_step54_candidate_id(kc_id: str, row: Mapping[str, Any]) -> str:
    source_candidate_index = _as_int(row.get("source_evidence_index"), default=0)
    text = _as_text(row.get("text") or row.get("candidate_text"))
    payload = {
        "kc_id": str(kc_id),
        "source_candidate_index": int(source_candidate_index),
        "doc_id": str(row.get("doc_id") or ""),
        "block_id": str(row.get("block_id") or ""),
        "page_index": row.get("page_index"),
        "sentence_id": str(row.get("sentence_id") or ""),
        "snippet": text,
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{kc_id}:step5_4:{digest}"


def _primary_positive_role(row: Mapping[str, Any]) -> str:
    admission = _evidence_admission(row)
    admission_role = str(admission.get("role") or "")
    if str(admission.get("decision") or "") == "ordered_evidence" and admission_role in POSITIVE_ROLES:
        return admission_role
    eligibility = dict(row.get("role_eligibility") or {})
    for role in POSITIVE_ROLES:
        if bool(eligibility.get(role)):
            return role
    return ""



_CONTEXT_DEPENDENT_START_RE = re.compile(
    r"^\s*(?:instead|however|therefore|thus|hence|consequently|moreover|furthermore|then|this|that|these|those|it|they)\b[\s,;:.-]*",
    re.IGNORECASE,
)

_DANGLING_CONTEXT_COMPLETION_END_RE = re.compile(
    r"\b(?:because|because of|due to|as a result of|with|without|by|of|for|to|from|than|that|which|whose|where|when|while|although|if|and|or|but|their|its|the)\s*[.,;:]?\s*$",
    re.IGNORECASE,
)

_EXPLICIT_EXERCISE_PROMPT_CONTEXT_RE = re.compile(
    r"(?:^|\b)(?:"
    r"this\s+exercise\b|"
    r"exercise\s*,\s*inspired\b|"
    r"determine\s+the\s+error\s+rate\b|"
    r"using\s+the\s+following\s+methods\b"
    r")",
    re.IGNORECASE,
)


def _normalized_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]


def _context_target_tokens(row: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()

    canonical = _as_text(
        row.get("canonical_name")
        or row.get("target_label")
        or row.get("kc_label")
        or row.get("source_canonical_name")
        or ""
    )
    canonical_head = canonical.split("(", 1)[0]
    for raw in re.findall(r"[A-Za-z0-9]+", canonical_head):
        low = raw.lower()
        if len(low) >= 4:
            tokens.add(low)

    support = row.get("support_profile")
    support_map = dict(support) if isinstance(support, Mapping) else {}
    for key in ("matched_surface_terms", "matched_target_tokens"):
        for value in _string_values(support_map.get(key)):
            for raw in re.findall(r"[A-Za-z0-9]+", value):
                low = raw.lower()
                if len(low) >= 4:
                    tokens.add(low)

    return tokens


def _selected_item_text(row: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
    candidate_text = _as_text(row.get("candidate_text") or row.get("text"))
    support = row.get("support_profile")
    support_map = dict(support) if isinstance(support, Mapping) else {}
    source_block_text = _as_text(row.get("source_block_text") or support_map.get("source_block_text"))

    candidate = _normalized_space(candidate_text)
    source_block = _normalized_space(source_block_text)

    use_source_block = False
    reject_dangling_context_completion = False
    if candidate and source_block:
        candidate_low = candidate.lower()
        source_block_low = source_block.lower()
        starts_context_dependent = bool(_CONTEXT_DEPENDENT_START_RE.match(candidate))
        source_block_ends_dangling = bool(_DANGLING_CONTEXT_COMPLETION_END_RE.search(source_block))
        source_block_is_explicit_exercise_prompt = bool(_EXPLICIT_EXERCISE_PROMPT_CONTEXT_RE.search(source_block))
        target_tokens = _context_target_tokens(row)
        target_hit = (not target_tokens) or any(token in source_block_low for token in target_tokens)

        context_completion_candidate = (
            starts_context_dependent
            and len(source_block) > len(candidate) + 40
            and len(source_block) <= 1200
            and candidate_low in source_block_low
            and target_hit
        )
        use_source_block = (
            context_completion_candidate
            and not source_block_ends_dangling
            and not source_block_is_explicit_exercise_prompt
        )
        reject_dangling_context_completion = context_completion_candidate and source_block_ends_dangling
        reject_exercise_prompt_context_completion = (
            context_completion_candidate
            and source_block_is_explicit_exercise_prompt
        )

    if reject_dangling_context_completion:
        return candidate_text, {
            "candidate_sentence_text": candidate_text,
            "selected_text_mode": "context_completion_rejected_dangling_source_block",
            "source_block_text_used": False,
            "source_block_context_reason": "rejected_context_completion_ends_dangling",
            "source_block_text": source_block_text,
            "selected_text_blocker": "context_completion_ends_dangling",
            "_drop_from_ordered": True,
        }

    if reject_exercise_prompt_context_completion:
        return candidate_text, {
            "candidate_sentence_text": candidate_text,
            "selected_text_mode": "context_completion_rejected_explicit_exercise_prompt",
            "source_block_text_used": False,
            "source_block_context_reason": "rejected_context_completion_explicit_exercise_prompt",
            "source_block_text": source_block_text,
            "selected_text_blocker": "context_completion_explicit_exercise_prompt",
            "_drop_from_ordered": True,
        }

    if use_source_block:
        return source_block_text, {
            "candidate_sentence_text": candidate_text,
            "selected_text_mode": "source_block_context_completion",
            "source_block_text_used": True,
            "source_block_context_reason": "context_dependent_candidate_sentence_completed_from_source_block",
            "source_block_text": source_block_text,
            "selected_text_blocker": "",
            "_drop_from_ordered": False,
        }

    return candidate_text, {
        "candidate_sentence_text": candidate_text,
        "selected_text_mode": "candidate_text",
        "source_block_text_used": False,
        "source_block_context_reason": "",
        "source_block_text": source_block_text,
        "selected_text_blocker": "",
        "_drop_from_ordered": False,
    }


def _selected_item(row: Mapping[str, Any], *, role: str, reason_selected: str) -> Dict[str, Any]:
    kc_id = str(row.get("kc_id") or "")
    compatible_id = _compatible_step54_candidate_id(kc_id, row)
    text, selected_text_meta = _selected_item_text(row)
    role_scores = dict(row.get("role_scores") or {})
    eligibility = dict(row.get("role_eligibility") or {})
    quality = dict(row.get("candidate_quality") or {})
    binding = dict(row.get("lexical_target_binding") or {})
    admission = _evidence_admission(row)
    refs = {
        "doc_id": str(row.get("doc_id") or ""),
        "block_id": str(row.get("block_id") or ""),
        "page_index": row.get("page_index"),
        "sentence_id": str(row.get("sentence_id") or ""),
        "patch_id": str(row.get("patch_id") or ""),
        "reveal_group_id": row.get("reveal_group_id"),
        "layer": str(row.get("layer") or ""),
    }
    return {
        "candidate_id": compatible_id,
        "source_candidate_id": compatible_id,
        "stage2_candidate_id": str(row.get("candidate_id") or ""),
        "scored_candidate_id": str(row.get("scored_candidate_id") or row.get("candidate_id") or ""),
        "source_row_id": str(row.get("candidate_id") or ""),
        "source_candidate_index": _as_int(row.get("source_evidence_index"), default=-1),
        "source_row_index": _as_int(row.get("source_row_index"), default=-1),
        "source_evidence_index": _as_int(row.get("source_evidence_index"), default=-1),
        "role": role,
        "roles": [role],
        "reason_selected": reason_selected,
        "text": text,
        "quote": text,
        "candidate_sentence_text": selected_text_meta["candidate_sentence_text"],
        "selected_text_mode": selected_text_meta["selected_text_mode"],
        "source_block_text_used": selected_text_meta["source_block_text_used"],
        "source_block_context_reason": selected_text_meta["source_block_context_reason"],
        "source_block_text": selected_text_meta["source_block_text"],
        "selected_text_blocker": selected_text_meta["selected_text_blocker"],
        "_drop_from_ordered": selected_text_meta["_drop_from_ordered"],
        "doc_id": refs["doc_id"],
        "block_id": refs["block_id"],
        "page_index": row.get("page_index"),
        "layer": refs["layer"],
        "bbox": row.get("bbox"),
        "sentence_id": refs["sentence_id"],
        "sent_idx": _as_int(row.get("sent_idx"), default=-1),
        "char_start": _as_int(row.get("char_start"), default=-1),
        "char_end": _as_int(row.get("char_end"), default=-1),
        "reveal_group_id": row.get("reveal_group_id"),
        "patch_id": refs["patch_id"],
        "patch_heading": str(row.get("patch_heading") or ""),
        "alignment_score": _as_float(row.get("alignment_score"), 0.0),
        "retrieval_scores": dict(row.get("retrieval_scores") or {}),
        "support_profile": dict(row.get("support_profile") or {}),
        "risk_flags": _string_list(row.get("risk_flags")),
        "review_risk_flags": _string_list(row.get("review_risk_flags")),
        "shapeaware_bucket": str(row.get("shapeaware_bucket") or ""),
        "debug_reasons": dict(row.get("debug_reasons") or {}),
        "role_scores": role_scores,
        "role_eligibility": eligibility,
        "candidate_quality": quality,
        "positive_support_guard": _positive_support_guard(row),
        "evidence_admission": admission,
        "lexical_target_binding": binding,
        "definition_framing_score": dict(row.get("definition_framing_score") or {}),
        "formula_signal": dict(row.get("formula_signal") or {}),
        "fragment_or_caption_signal": dict(row.get("fragment_or_caption_signal") or {}),
        "contamination_signals": dict(row.get("contamination_signals") or {}),
        "sibling_or_competitor_signals": dict(row.get("sibling_or_competitor_signals") or {}),
        "provenance": dict(row.get("provenance") or {}),
        "source_refs": refs,
    }


def _dedupe_items(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate selected pack items by final evidence identity.

    The 204794 family can surface the same evidence through multiple rows,
    extraction layers, or bridge paths. For drafting-facing packs, compatible
    candidate identities, source sentence identity, and normalized text identity
    are stronger than transient source-row IDs.
    """
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []

    for item in items:
        if isinstance(item, Mapping) and item.get("_drop_from_ordered"):
            continue
        item_dict = dict(item)

        candidate_id = str(item_dict.get("candidate_id") or "")
        source_candidate_id = str(item_dict.get("source_candidate_id") or "")
        doc_id = str(item_dict.get("doc_id") or "")
        sentence_id = str(item_dict.get("sentence_id") or "")
        patch_id = str(item_dict.get("patch_id") or "")
        text = _as_text(item_dict.get("text") or item_dict.get("quote"))
        text_key = " ".join(text.lower().split())

        aliases: List[str] = []
        if candidate_id:
            aliases.append(f"candidate_id::{candidate_id}")
        if source_candidate_id:
            aliases.append(f"source_candidate_id::{source_candidate_id}")
        if doc_id and sentence_id:
            aliases.append(f"doc_sentence::{doc_id}::{sentence_id}")
        if doc_id and patch_id and len(text_key) >= 32:
            aliases.append(f"doc_patch_text::{doc_id}::{patch_id}::{text_key[:240]}")
        if len(text_key) >= 80:
            aliases.append(f"text::{text_key[:240]}")

        if not aliases:
            stage2_candidate_id = str(item_dict.get("stage2_candidate_id") or "")
            scored_candidate_id = str(item_dict.get("scored_candidate_id") or "")
            source_row_id = str(item_dict.get("source_row_id") or "")
            if stage2_candidate_id:
                aliases.append(f"stage2_candidate_id::{stage2_candidate_id}")
            if scored_candidate_id:
                aliases.append(f"scored_candidate_id::{scored_candidate_id}")
            if source_row_id:
                aliases.append(f"source_row_id::{source_row_id}")

        if not aliases:
            aliases.append("json::" + json.dumps(item_dict, sort_keys=True, ensure_ascii=False, default=str))

        if any(alias in seen for alias in aliases):
            continue

        seen.update(aliases)
        out.append(item_dict)

    return out

def _limit_role_items(items: Sequence[Mapping[str, Any]], limit: int, max_chars: int) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    out: List[Dict[str, Any]] = []
    total_chars = 0
    for item in items:
        text = _as_text(item.get("text") or item.get("quote"))
        if out and max_chars > 0 and total_chars + len(text) > max_chars:
            continue
        out.append(dict(item))
        total_chars += len(text)
        if len(out) >= limit:
            break
    return out


def _unit_id_from_row(row: Mapping[str, Any]) -> str:
    return str(row.get("knowledge_unit_id") or row.get("kc_id") or row.get("node_id") or "")


def _unit_type_from_row(row: Mapping[str, Any]) -> str:
    value = str(row.get("knowledge_unit_type") or row.get("node_type") or "kc").strip().lower()
    return value if value in {"kc", "topic"} else "kc"



def _positive_support_guard(row: Mapping[str, Any]) -> Dict[str, Any]:
    guard = row.get("positive_support_guard")
    return dict(guard) if isinstance(guard, Mapping) else {}


def _positive_support_guard_blocked(row: Mapping[str, Any]) -> bool:
    guard = _positive_support_guard(row)
    return bool(guard.get("blocked_from_positive_support"))


def _positive_support_guard_flags(row: Mapping[str, Any]) -> List[str]:
    guard = _positive_support_guard(row)
    return _string_list(guard.get("blocker_flags"))

def _source_ref_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": str(row.get("doc_id") or ""),
        "page_index": row.get("page_index"),
        "block_id": str(row.get("block_id") or ""),
        "sentence_id": str(row.get("sentence_id") or ""),
        "patch_id": str(row.get("patch_id") or ""),
        "patch_heading": str(row.get("patch_heading") or ""),
    }


def _near_miss_review_items(kc_rows: Sequence[Mapping[str, Any]], *, limit: int = 6) -> List[Dict[str, Any]]:
    ranked = sorted(kc_rows, key=lambda row: (-_overall_score(row), _source_order(row)))
    items: List[Dict[str, Any]] = []
    for row in ranked:
        route = str(row.get("routing_recommendation") or "")
        admission = _evidence_admission(row)
        decision = str(admission.get("decision") or "")
        if decision in {"ordered_evidence", "guardrail"}:
            continue
        flags = unique_preserve_order([
            *_string_list(row.get("risk_flags")),
            *_positive_support_guard_flags(row),
            *_string_list(admission.get("warnings")),
        ])
        if (
            not flags
            and decision not in {"review", "reject", "auxiliary_context"}
            and route not in {
                "manual_review_candidate",
                "review_only_candidate",
                "drop_from_positive_roles",
                "auxiliary_only_candidate",
            }
        ):
            continue
        text = _as_text(row.get("candidate_text") or row.get("text"))
        items.append({
            "candidate_id": str(row.get("candidate_id") or ""),
            "scored_candidate_id": str(row.get("scored_candidate_id") or row.get("candidate_id") or ""),
            "routing_recommendation": route,
            "evidence_admission": admission,
            "risk_flags": flags,
            "near_miss_reason": str(row.get("near_miss_reason") or (flags[0] if flags else decision or route)),
            "retrieval_intent": str(row.get("retrieval_intent") or row.get("candidate_origin") or ""),
            "candidate_origin": str(row.get("candidate_origin") or row.get("retrieval_intent") or ""),
            "target_binding_basis": str(row.get("target_binding_basis") or ""),
            "evidence_shape_match": str(row.get("evidence_shape_match") or ""),
            "authority_contract": str(row.get("authority_contract") or "step5x_must_verify_against_source_rows"),
            "source_refs": _source_ref_from_row(row),
            "preview": text[:500],
        })
        if len(items) >= limit:
            break
    return items


def _admission_sidecar_items(
    kc_rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[str],
    *,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    wanted = {str(item) for item in decisions}
    ranked = sorted(kc_rows, key=lambda row: (-_overall_score(row), _source_order(row)))
    items: List[Dict[str, Any]] = []
    for row in ranked:
        admission = _evidence_admission(row)
        decision = str(admission.get("decision") or "")
        if decision not in wanted:
            continue
        role = str(admission.get("role") or "none")
        if role == "none":
            role = "review_only"
        item = _selected_item(
            row,
            role=role,
            reason_selected=f"preserved_for_{decision}_from_evidence_admission",
        )
        item["evidence_admission"] = admission
        items.append(item)
        if len(items) >= limit:
            break
    return _dedupe_items(items)



def _section_anchor_summary(kc_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    headings = Counter(str(row.get("patch_heading") or row.get("source_heading_text") or "") for row in kc_rows)
    headings.pop("", None)
    pages = Counter(str(row.get("page_index")) for row in kc_rows if row.get("page_index") is not None)
    origins = Counter(str(row.get("candidate_origin") or row.get("retrieval_intent") or "") for row in kc_rows)
    origins.pop("", None)
    return {
        "top_headings": [{"heading": key, "count": count} for key, count in headings.most_common(5)],
        "top_pages": [{"page_index": key, "count": count} for key, count in pages.most_common(5)],
        "candidate_origin_breakdown": dict(origins),
    }


def _retrieval_failure_diagnosis(
    *,
    unit_type: str,
    kc_rows: Sequence[Mapping[str, Any]],
    positive_count: int,
    ordered_count: int,
) -> Dict[str, Any]:
    flags = Counter(flag for row in kc_rows for flag in _string_list(row.get("risk_flags")))
    routes = Counter(str(row.get("routing_recommendation") or "") for row in kc_rows)
    labels: List[str] = []
    if not kc_rows:
        labels.append("retrieval_failure")
    if flags.get("retrieval_failure"):
        labels.append("retrieval_failure")
    if flags.get("reference_like") or flags.get("bibliography_like"):
        labels.append("bibliography_or_reference_only")
    if flags.get("fragmentary"):
        labels.append("evidence_fragmentation")
    if flags.get("context_only_support") or routes.get("review_only_candidate"):
        labels.append("context_only_support")
    if flags.get("sibling_competitor_dominant") or flags.get("source_kc_mismatch"):
        labels.append("sibling_or_wrong_branch_contamination")
    if positive_count == 0 and kc_rows:
        labels.append("pack_composition_conservatism")
    if flags.get("no_target_binding") or flags.get("candidate_pool_membership_only"):
        labels.append("label_mismatch")
    if not labels and positive_count == 0:
        labels.append("source_sparsity")
    if unit_type == "topic" and positive_count == 0 and kc_rows:
        labels = [label for label in labels if label not in {"pack_composition_conservatism"}]
        labels.append("topic_context_only_support")
    return {
        "diagnosis_labels": [str(item) for item in unique_preserve_order(labels)],
        "primary_diagnosis": str(labels[0]) if labels else "",
        "risk_flag_breakdown": dict(flags),
        "routing_recommendation_breakdown": dict(routes),
        "positive_support_count": int(positive_count),
        "ordered_pack_for_drafting_count": int(ordered_count),
    }


def _feedback_sidecar(
    *,
    cfg: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    kc_rows: Sequence[Mapping[str, Any]],
    near_miss_items: Sequence[Mapping[str, Any]],
) -> tuple[bool, Dict[str, Any]]:
    feedback_cfg = dict((cfg or {}).get("feedback") or {})
    enabled = bool(feedback_cfg.get("enabled", False))
    severe = bool(
        "retrieval_failure" in _string_list(diagnosis.get("diagnosis_labels"))
        or (
            diagnosis.get("positive_support_count") == 0
            and not near_miss_items
            and len(kc_rows) == 0
        )
    )
    eligible = bool(enabled and severe)
    payload: Dict[str, Any] = {}
    if eligible:
        payload = {
            "feedback_policy": "disabled_by_default_bounded_one_pass_when_enabled",
            "max_feedback_rounds": int(feedback_cfg.get("max_feedback_rounds", 1) or 1),
            "diagnosis": dict(diagnosis),
        }
    return eligible, payload


def _topic_sidecars(unit_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    topic_scope: List[Dict[str, Any]] = []
    representative_regions: List[Dict[str, Any]] = []
    child_summary: Dict[str, Any] = {}
    section_map: List[Dict[str, Any]] = []
    boundary_notes: List[str] = []
    for row in unit_rows:
        support = dict(row.get("support_profile") or {})
        if support.get("topic_scope_evidence") or row.get("topic_scope_evidence"):
            topic_scope.append({"source_refs": _source_ref_from_row(row), "preview": _as_text(row.get("text"))[:500]})
        region = support.get("representative_source_region") or row.get("representative_source_region")
        if isinstance(region, Mapping):
            representative_regions.append(dict(region))
        elif support.get("representative_source_regions") or row.get("representative_source_regions"):
            for item in _string_list(support.get("representative_source_regions") or row.get("representative_source_regions")):
                representative_regions.append({"region": item})
        if isinstance(support.get("child_kc_coverage_summary"), Mapping):
            child_summary.update(dict(support.get("child_kc_coverage_summary")))
        if isinstance(row.get("child_kc_coverage_summary"), Mapping):
            child_summary.update(dict(row.get("child_kc_coverage_summary")))
        if support.get("source_section_map"):
            for item in _as_list(support.get("source_section_map")):
                if isinstance(item, Mapping):
                    section_map.append(dict(item))
        boundary_notes.extend(_string_list(support.get("sibling_topic_boundary_notes") or row.get("sibling_topic_boundary_notes")))
    if not representative_regions:
        representative_regions = [_source_ref_from_row(row) for row in unit_rows[:4]]
    return {
        "topic_scope_evidence": topic_scope,
        "representative_source_regions": representative_regions,
        "child_kc_coverage_summary": child_summary,
        "source_section_map": section_map,
        "sibling_topic_boundary_notes": unique_preserve_order(boundary_notes),
    }


def _default_composition_cfg(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    comp = dict(cfg.get("composition") or {})
    return {
        "max_definition_kernel": int(comp.get("max_definition_kernel", 2)),
        "max_explanatory_gloss": int(comp.get("max_explanatory_gloss", 3)),
        "max_scope_condition": int(comp.get("max_scope_condition", 2)),
        "max_formula_notation": int(comp.get("max_formula_notation", 2)),
        "max_example_or_procedure": int(comp.get("max_example_or_procedure", 2)),
        "max_context_completion": int(comp.get("max_context_completion", 2)),
        "max_sibling_contrast": int(comp.get("max_sibling_contrast", 4)),
        "max_ordered_pack_items": int(comp.get("max_ordered_pack_items", 8)),
        "max_ordered_pack_chars": int(comp.get("max_ordered_pack_chars", 1800)),
        "allow_context_completion_in_ordered_pack": bool(comp.get("allow_context_completion_in_ordered_pack", True)),
        "min_positive_items_for_standard": int(comp.get("min_positive_items_for_standard", 1)),
    }


def _ordered_pack_item_hard_blockers(row: Mapping[str, Any], *, role: str) -> List[str]:
    """Narrow hard blocker for final ordered-pack admission.

    The purpose of this helper is not to re-score evidence and not to impose a
    second broad precision gate. Earlier false-positive audits showed the
    required hard block is to prevent known false-positive and review-only rows
    from leaking into ordered_pack_for_drafting. Softer risks such as
    needs_stronger_anchor_context must remain available to the existing pack
    quality lanes, otherwise almost all 204794-family drafting evidence is
    strangled before drafting.
    """
    blockers: List[str] = []

    shapeaware_bucket = str(
        row.get("shapeaware_bucket")
        or row.get("evidence_bucket")
        or row.get("bucket")
        or ""
    ).strip()

    routing = str(row.get("routing_recommendation") or "").strip()

    if shapeaware_bucket == "rejected_false_positive":
        blockers.append("shapeaware_rejected_false_positive")

    if bool(row.get("review_only_candidate")):
        blockers.append("review_only_candidate")

    if routing in {"rejected_false_positive", "review_only_candidate"}:
        blockers.append(f"routing_{routing}")

    flags: List[str] = []
    for key in ("risk_flags", "review_risk_flags"):
        value = row.get(key) or []
        if isinstance(value, list):
            flags.extend(str(x or "").strip() for x in value if str(x or "").strip())
        elif value:
            flags.append(str(value).strip())

    flag_set = {flag for flag in flags if flag}

    for hard_flag in (
        "suspected_false_positive",
        "reference_like",
        "bibliography_like",
        "meta_guidance",
        "caption_like",
    ):
        if hard_flag in flag_set:
            blockers.append(hard_flag)

    return unique_preserve_order(blockers)

def _positive_item_candidates(kc_rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {role: [] for role in POSITIVE_ROLES}
    for row in kc_rows:
        admission = _evidence_admission(row)
        if str(admission.get("decision") or "") != "ordered_evidence":
            continue
        role = str(admission.get("role") or _primary_positive_role(row))
        if role not in POSITIVE_ROLES:
            continue
        buckets[role].append(
            _selected_item(
                row,
                role=role,
                reason_selected=f"selected_as_{role}_from_evidence_admission_ordered_evidence",
            )
        )
    for role in POSITIVE_ROLES:
        buckets[role].sort(key=lambda item, r=role: _ranking_key(item, r))
    return buckets



def _auxiliary_item_candidates(kc_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in kc_rows:
        admission = _evidence_admission(row)
        if str(admission.get("decision") or "") != "auxiliary_context":
            continue
        items.append(
            _selected_item(
                row,
                role="context_completion",
                reason_selected="selected_as_context_completion_from_evidence_admission_auxiliary_context",
            )
        )
    items.sort(key=lambda item: _ranking_key(item, "context_completion_candidate"))
    return items



def _guardrail_item_candidates(kc_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in kc_rows:
        admission = _evidence_admission(row)
        if str(admission.get("decision") or "") != "guardrail":
            continue
        items.append(
            _selected_item(
                row,
                role="sibling_contrast",
                reason_selected="selected_as_sibling_contrast_from_evidence_admission_guardrail",
            )
        )
    items.sort(key=lambda item: _ranking_key(item, "sibling_contrast"))
    return items



def _build_ordered_pack(slots: Mapping[str, Sequence[Mapping[str, Any]]], cfg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    ordered: List[Dict[str, Any]] = []
    comp = _default_composition_cfg(cfg)
    for role in POSITIVE_ROLES:
        ordered.extend(dict(item) for item in slots.get(role) or [])
    ordered = _dedupe_items(ordered)
    ordered = [
        dict(item)
        for item in ordered
        if _admission_decision(item) == "ordered_evidence"
    ]
    ordered.sort(key=_source_order)
    return _limit_role_items(
        ordered,
        limit=int(comp["max_ordered_pack_items"]),
        max_chars=int(comp["max_ordered_pack_chars"]),
    )



def _pack_quality(slots: Mapping[str, Sequence[Mapping[str, Any]]], kc_rows: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> Dict[str, Any]:
    unit_type = _unit_type_from_row(kc_rows[0]) if kc_rows else "kc"
    positive_count = sum(len(slots.get(role) or []) for role in POSITIVE_ROLES)
    auxiliary_count = len(slots.get("context_completion") or [])
    guardrail_count = len(slots.get("sibling_contrast") or [])
    definition_count = len(slots.get("definition_kernel") or [])
    ordered_count = sum(len(slots.get(role) or []) for role in ORDERED_ALLOWED_ROLES)
    total_candidates = max(1, len(kc_rows))
    insufficient_reasons: List[str] = []
    if unit_type == "kc" and definition_count == 0:
        insufficient_reasons.extend(["definition_anchor_missing", "natural_language_anchor_missing"])
    if positive_count == 0:
        insufficient_reasons.append("weak_coverage")
    if auxiliary_count and positive_count == 0:
        insufficient_reasons.append("auxiliary_without_positive_anchor")
    if guardrail_count and positive_count == 0:
        insufficient_reasons.append("guardrail_only_support")
    if guardrail_count >= 3:
        insufficient_reasons.append("sibling_contamination_risk")
    insufficient_reasons = [str(item) for item in unique_preserve_order(insufficient_reasons)]

    comp = _default_composition_cfg(cfg)
    min_positive = int(comp["min_positive_items_for_standard"])
    if unit_type == "topic":
        topic_sidecars = _topic_sidecars(kc_rows)
        if topic_sidecars["topic_scope_evidence"]:
            route = "topic_scope_support_packet"
        elif topic_sidecars["representative_source_regions"]:
            route = "topic_representative_coverage_packet"
        elif kc_rows:
            route = "topic_context_only_review_packet"
        else:
            route = "topic_insufficient_support_packet"
    elif definition_count > 0 and positive_count >= min_positive:
        route = "standard_drafting"
    elif positive_count > 0:
        route = "partial_grounded_packet"
    else:
        route = "insufficient_support_packet"

    return {
        "route": route,
        "knowledge_unit_type": unit_type,
        "definition_anchor_present": bool(definition_count),
        "definition_anchor_natural_language": bool(definition_count),
        "positive_support_count": int(positive_count),
        "auxiliary_support_count": int(auxiliary_count),
        "guardrail_support_count": int(guardrail_count),
        "context_completion_used": bool(auxiliary_count and positive_count),
        "sibling_contrast_present": bool(guardrail_count),
        "sibling_contamination_risk": "high" if guardrail_count >= 3 else ("medium" if guardrail_count else "low"),
        "formula_dominance_risk": "low",
        "formula_primary": False,
        "coverage_score": round(float(positive_count) / float(total_candidates), 6),
        "density_score": round(float(ordered_count) / float(total_candidates), 6),
        "source_order_preserved": True,
        "insufficient_reasons": insufficient_reasons,
    }


def _provenance_sidecar(kc_rows: Sequence[Mapping[str, Any]], slots: Mapping[str, Sequence[Mapping[str, Any]]], ordered_pack: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    selected_stage2_ids: List[str] = []
    selected_candidate_ids: List[str] = []
    selected_source_refs: List[Dict[str, Any]] = []
    for role in ALL_SLOT_ROLES:
        for item in slots.get(role) or []:
            selected_stage2_ids.append(str(item.get("stage2_candidate_id") or ""))
            selected_candidate_ids.append(str(item.get("candidate_id") or ""))
            selected_source_refs.append(dict(item.get("source_refs") or {}))
    selected_stage2_set = {cid for cid in selected_stage2_ids if cid}
    dropped: List[str] = []
    drop_reasons: Dict[str, str] = {}
    for row in kc_rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in selected_stage2_set:
            continue
        dropped.append(candidate_id)
        route = str(row.get("routing_recommendation") or "")
        flags = _string_list(row.get("risk_flags"))
        if route == "drop_from_positive_roles":
            drop_reasons[candidate_id] = "stage2_drop_from_positive_roles"
        elif route == "manual_review_candidate":
            drop_reasons[candidate_id] = "stage2_manual_review_candidate"
        elif flags:
            drop_reasons[candidate_id] = ",".join(flags[:3])
        else:
            drop_reasons[candidate_id] = "not_selected_by_stage3_limits"
    return {
        "selected_candidate_ids": [cid for cid in unique_preserve_order(selected_candidate_ids) if cid],
        "selected_stage2_candidate_ids": [cid for cid in unique_preserve_order(selected_stage2_ids) if cid],
        "ordered_candidate_ids": [str(item.get("candidate_id") or "") for item in ordered_pack if str(item.get("candidate_id") or "")],
        "ordered_stage2_candidate_ids": [str(item.get("stage2_candidate_id") or "") for item in ordered_pack if str(item.get("stage2_candidate_id") or "")],
        "dropped_candidate_ids": dropped,
        "drop_reasons": drop_reasons,
        "all_source_refs": unique_preserve_order(selected_source_refs),
    }


def _empty_slots() -> Dict[str, List[Dict[str, Any]]]:
    return {role: [] for role in ALL_SLOT_ROLES}


def _candidate_identity_values(item: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ("candidate_id", "source_candidate_id", "stage2_candidate_id", "scored_candidate_id", "source_row_id"):
        value = str(item.get(key) or "").strip()
        if value:
            values.append(f"{key}::{value}")
    return values


def _candidate_identity_set(items: Sequence[Mapping[str, Any]]) -> set[str]:
    identities: set[str] = set()
    for item in items:
        identities.update(_candidate_identity_values(item))
    return identities


def _shapeaware_core_aligned_to_ordered_pack(
    shapeaware_core: Sequence[Mapping[str, Any]],
    ordered_pack: Sequence[Mapping[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Only expose shape-aware core evidence to drafting if it passed ordered admission."""
    ordered_ids = _candidate_identity_set(ordered_pack)
    aligned: List[Dict[str, Any]] = []
    demoted: List[Dict[str, Any]] = []
    for raw in shapeaware_core:
        item = dict(raw)
        item_ids = set(_candidate_identity_values(item))
        if item_ids & ordered_ids:
            aligned.append(item)
        else:
            item["lane_demotion_reason"] = "shapeaware_core_not_admitted_to_ordered_pack_for_drafting"
            flags = _string_list(item.get("review_risk_flags"))
            flags.append("not_admitted_to_ordered_pack_for_drafting")
            item["review_risk_flags"] = unique_preserve_order(flags)
            demoted.append(item)
    return _dedupe_items(aligned), _dedupe_items(demoted)


def compose_pack_for_kc(kc_id: str, kc_rows: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> Dict[str, Any]:
    if not kc_rows:
        raise ValueError("compose_pack_for_kc requires at least one row")
    first = dict(kc_rows[0])
    comp = _default_composition_cfg(cfg)
    slots = _empty_slots()

    positive_candidates = _positive_item_candidates(kc_rows)
    for role in POSITIVE_ROLES:
        slots[role] = _limit_role_items(
            positive_candidates.get(role) or [],
            limit=int(comp[f"max_{role}"]),
            max_chars=int(comp["max_ordered_pack_chars"]),
        )

    positive_count = sum(len(slots.get(role) or []) for role in POSITIVE_ROLES)
    aux_candidates = _auxiliary_item_candidates(kc_rows)
    guard_candidates = _guardrail_item_candidates(kc_rows)
    slots["context_completion"] = _limit_role_items(
        aux_candidates,
        limit=int(comp["max_context_completion"]),
        max_chars=int(comp["max_ordered_pack_chars"]),
    )
    slots["sibling_contrast"] = _limit_role_items(
        guard_candidates,
        limit=int(comp["max_sibling_contrast"]),
        max_chars=int(comp["max_ordered_pack_chars"]),
    )

    ordered_pack = _build_ordered_pack(slots, cfg)
    quality = _pack_quality(slots, kc_rows, cfg)
    shapeaware_shadow = compose_shapeaware_shadow_pack(
        kc_id,
        kc_rows,
        expected_evidence_needs=_as_list(first.get("expected_evidence_needs")),
    )
    raw_shapeaware_core = _as_list(shapeaware_shadow.get("drafting_core_evidence"))
    drafting_core_evidence, demoted_shapeaware_core = _shapeaware_core_aligned_to_ordered_pack(
        raw_shapeaware_core,
        ordered_pack,
    )
    review_needed_evidence = _dedupe_items([
        *_as_list(shapeaware_shadow.get("review_needed_evidence")),
        *demoted_shapeaware_core,
        *_admission_sidecar_items(kc_rows, ["review"], limit=12),
    ])
    rejected_false_positive_evidence = _dedupe_items([
        *_as_list(shapeaware_shadow.get("rejected_false_positive_evidence")),
        *_admission_sidecar_items(kc_rows, ["reject"], limit=12),
    ])
    sidecar = _provenance_sidecar(kc_rows, slots, ordered_pack)
    unit_id = _unit_id_from_row(first) or kc_id
    unit_type = _unit_type_from_row(first)
    near_miss_items = _near_miss_review_items(kc_rows)
    diagnosis = _retrieval_failure_diagnosis(
        unit_type=unit_type,
        kc_rows=kc_rows,
        positive_count=int(quality.get("positive_support_count") or 0),
        ordered_count=len(ordered_pack),
    )
    feedback_eligible, feedback_payload = _feedback_sidecar(
        cfg=cfg,
        diagnosis=diagnosis,
        kc_rows=kc_rows,
        near_miss_items=near_miss_items,
    )
    topic_sidecars = _topic_sidecars(kc_rows) if unit_type == "topic" else {
        "topic_scope_evidence": [],
        "representative_source_regions": [],
        "child_kc_coverage_summary": {},
        "source_section_map": [],
        "sibling_topic_boundary_notes": [],
    }

    return {
        "pack_version": PACK_CONTRACT_VERSION,
        "kc_id": kc_id,
        "knowledge_unit_id": unit_id,
        "knowledge_unit_type": unit_type,
        "canonical_name": str(first.get("canonical_name") or ""),
        "aliases": _string_list(first.get("aliases")),
        "topic_path_ids": _string_list(first.get("topic_path_ids")),
        "topic_path_labels": _string_list(first.get("topic_path_labels")),
        "parent_topic_id": str(first.get("parent_topic_id") or ""),
        "parent_topic_label": str(first.get("parent_topic_label") or ""),
        "slots": slots,
        "ordered_pack_for_drafting": ordered_pack,
        "pack_quality": quality,
        "expected_evidence_needs": shapeaware_shadow["expected_evidence_needs"],
        "shapeaware_route": shapeaware_shadow["shapeaware_route"],
        "evidence_need_satisfaction": shapeaware_shadow["evidence_need_satisfaction"],
        "review_risk_flags": shapeaware_shadow["review_risk_flags"],
        "drafting_core_evidence": drafting_core_evidence,
        "auxiliary_evidence": shapeaware_shadow["auxiliary_evidence"],
        "review_needed_evidence": review_needed_evidence,
        "rejected_false_positive_evidence": rejected_false_positive_evidence,
        "provenance_sidecar": sidecar,
        "near_miss_review_items": near_miss_items,
        "retrieval_failure_diagnosis": diagnosis,
        "retrieval_gap_requests": [],
        "missing_positive_support_reason": str(diagnosis.get("primary_diagnosis") or "") if not ordered_pack else "",
        "feedback_eligible": feedback_eligible,
        "feedback_payload": feedback_payload,
        "section_anchor_summary": _section_anchor_summary(kc_rows),
        "topic_scope_evidence": topic_sidecars["topic_scope_evidence"],
        "representative_source_regions": topic_sidecars["representative_source_regions"],
        "child_kc_coverage_summary": topic_sidecars["child_kc_coverage_summary"],
        "source_section_map": topic_sidecars["source_section_map"],
        "sibling_topic_boundary_notes": topic_sidecars["sibling_topic_boundary_notes"],
        "topic_near_miss_review_items": near_miss_items if unit_type == "topic" else [],
        "source_manifests": {
            "stage2_scored_candidates": str(first.get("source_manifest") or ""),
            "stage1_candidate_bank": str(first.get("stage1_source_manifest") or ""),
        },
        "stage2_summary": {
            "candidate_count": len(kc_rows),
            "routing_recommendation_breakdown": dict(Counter(str(row.get("routing_recommendation") or "") for row in kc_rows)),
            "risk_flag_breakdown": dict(Counter(flag for row in kc_rows for flag in _string_list(row.get("risk_flags")))),
            "evidence_admission_breakdown": dict(Counter(_admission_decision(row) for row in kc_rows)),
            "ordered_pack_quality_guard_version": V4C_ORDERED_PACK_QUALITY_GUARD_VERSION,
        },
    }


def compose_evidence_packs_from_scored_candidates(rows: Sequence[Mapping[str, Any]], cfg: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = dict(cfg or {})
    by_kc: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        kc_id = _unit_id_from_row(row)
        if kc_id:
            by_kc[kc_id].append(row)
    packs: List[Dict[str, Any]] = []
    for kc_id in sorted(by_kc.keys()):
        packs.append(compose_pack_for_kc(kc_id, by_kc[kc_id], cfg))
    return packs


def _read_gap_requests_from_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    requests: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            requests.append(obj)
    return requests


def _attach_retrieval_gap_requests_to_packs(
    packs: Sequence[Dict[str, Any]],
    requests: Sequence[Mapping[str, Any]],
) -> None:
    requests_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for request in requests:
        kc_id = str(request.get("kc_id") or request.get("knowledge_unit_id") or "")
        if kc_id:
            requests_by_kc[kc_id].append(dict(request))
    for pack in packs:
        kc_id = str(pack.get("kc_id") or pack.get("knowledge_unit_id") or "")
        pack["retrieval_gap_requests"] = requests_by_kc.get(kc_id, [])


def _split_exact_kc_ids(values: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _filter_rows(rows: Sequence[Mapping[str, Any]], *, exact_kc_ids: Optional[Sequence[str]], limit_kcs: Optional[int]) -> List[Dict[str, Any]]:
    exact = _split_exact_kc_ids(exact_kc_ids)
    if exact:
        allowed = set(exact)
        filtered = [dict(row) for row in rows if str(row.get("kc_id") or "") in allowed]
        seen = {str(row.get("kc_id") or "") for row in filtered}
        missing = [kc_id for kc_id in exact if kc_id not in seen]
        if missing:
            # Zero-candidate KCs are valid after Stage 2.
            # A requested KC may be absent from scored rows because Stage 1 found no candidates.
            # Do not crash here. Keep available scored rows and let pack composition
            # expose whether missing KCs are still dropped or represented downstream.
            pass
        order = {kc_id: index for index, kc_id in enumerate(exact)}
        filtered.sort(key=lambda row: (order.get(str(row.get("kc_id") or ""), 999999), _source_order(row)))
        return filtered
    ordered_kcs = sorted({str(row.get("kc_id") or "") for row in rows if str(row.get("kc_id") or "")})
    if limit_kcs is not None:
        ordered_kcs = ordered_kcs[: int(limit_kcs)]
    allowed = set(ordered_kcs)
    return [dict(row) for row in rows if str(row.get("kc_id") or "") in allowed]


def load_scored_candidate_rows(
    *,
    stage2_set_manifest: Optional[str],
    scored_candidates_jsonl: Optional[str],
    exact_kc_ids: Optional[Sequence[str]] = None,
    limit_kcs: Optional[int] = None,
    repo_root: Path = REPO_ROOT,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not stage2_set_manifest and not scored_candidates_jsonl:
        raise RuntimeError("Provide either stage2_set_manifest or scored_candidates_jsonl")
    source_manifest = ""
    base_spec = None
    if stage2_set_manifest:
        manifest_spec = parse_input_spec(stage2_set_manifest, repo_root=repo_root)
        manifest = read_json_from_spec(manifest_spec)
        base_spec = manifest_spec
        source_manifest = manifest_spec.display()
        raw = (manifest.get("artifacts") or {}).get("scored_candidates_jsonl")
        if not raw:
            raise RuntimeError("Stage 2 set manifest missing artifacts.scored_candidates_jsonl")
        row_spec = resolve_related_input_spec(raw, repo_root=repo_root, base_spec=base_spec)
    else:
        row_spec = parse_input_spec(scored_candidates_jsonl, repo_root=repo_root)
    rows = read_jsonl_from_spec(row_spec)
    filtered = _filter_rows(rows, exact_kc_ids=exact_kc_ids, limit_kcs=limit_kcs)
    return filtered, {
        "source_manifest": source_manifest,
        "scored_candidates_jsonl": row_spec.display(),
    }


def _schema_snapshot(packs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    pack_keys = sorted({key for pack in packs for key in pack.keys()})
    slot_item_keys = sorted({key for pack in packs for items in (pack.get("slots") or {}).values() for item in items for key in item.keys()})
    return {
        "pack_contract_version": PACK_CONTRACT_VERSION,
        "pack_top_level_keys": pack_keys,
        "slot_roles": list(ALL_SLOT_ROLES),
        "ordered_allowed_roles": list(ORDERED_ALLOWED_ROLES),
        "slot_item_keys": slot_item_keys,
    }


def _stats(packs: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]], run_id: str, source_manifest: str) -> Dict[str, Any]:
    route_counter = Counter(str((pack.get("pack_quality") or {}).get("route") or "") for pack in packs)
    slot_counter: Counter[str] = Counter()
    ordered_role_counter: Counter[str] = Counter()
    evidence_admission_counter: Counter[str] = Counter(
        str(_evidence_admission(row).get("decision") or "")
        for row in rows
    )
    ordered_admission_violations: List[str] = []
    forbidden_hits = 0
    ordered_sibling_violations: List[str] = []
    pack_candidate_ids: List[str] = []
    for pack in packs:
        slots = dict(pack.get("slots") or {})
        for role in ALL_SLOT_ROLES:
            slot_counter[role] += len(slots.get(role) or [])
        for item in pack.get("ordered_pack_for_drafting") or []:
            role = str(item.get("role") or "")
            ordered_role_counter[role] += 1
            admission = _evidence_admission(item)
            if str(admission.get("decision") or "") != "ordered_evidence":
                ordered_admission_violations.append(str(pack.get("kc_id") or ""))
            if role == "sibling_contrast":
                ordered_sibling_violations.append(str(pack.get("kc_id") or ""))
        pack_json = json.dumps(pack, ensure_ascii=False)
        for forbidden in FORBIDDEN_OUTPUT_FIELDS:
            if forbidden in pack_json:
                forbidden_hits += 1
        for item in pack.get("ordered_pack_for_drafting") or []:
            cid = str(item.get("candidate_id") or "")
            if cid:
                pack_candidate_ids.append(cid)
    duplicate_pack_candidate_ids = [cid for cid, count in Counter(pack_candidate_ids).items() if count > 1]
    return {
        "run_id": run_id,
        "pack_contract_version": PACK_CONTRACT_VERSION,
        "source_manifest": source_manifest,
        "total_input_scored_candidates_seen": len(rows),
        "total_packs_emitted": len(packs),
        "pack_count_by_kc": {str(pack.get("kc_id") or ""): 1 for pack in packs},
        "route_breakdown": dict(route_counter),
        "slot_item_count_breakdown": dict(slot_counter),
        "ordered_role_breakdown": dict(ordered_role_counter),
        "evidence_admission_decision_breakdown": dict(evidence_admission_counter),
        "ordered_evidence_admission_violation_count": len(ordered_admission_violations),
        "ordered_evidence_admission_violations": sorted(set(ordered_admission_violations)),
        "ordered_sibling_violation_count": len(ordered_sibling_violations),
        "ordered_sibling_violations": sorted(set(ordered_sibling_violations)),
        "duplicate_ordered_candidate_id_count": len(duplicate_pack_candidate_ids),
        "forbidden_seed_field_hits": int(forbidden_hits),
    }



def _build_zero_candidate_insufficient_pack(
    *,
    kc_id,
    exact_kc_ids=None,
    source_manifests=None,
):
    """Build a minimal pack row for a requested KC with zero scored candidates.

    This preserves KC survival without fabricating evidence or claiming source
    corpus insufficiency.
    """
    return {
        "pack_version": PACK_CONTRACT_VERSION,
        "kc_id": str(kc_id),
        "knowledge_unit_id": str(kc_id),
        "knowledge_unit_type": "kc",
        "canonical_name": "",
        "aliases": [],
        "parent_topic_id": "",
        "parent_topic_label": "",
        "topic_path_ids": [],
        "topic_path_labels": [],
        "ordered_pack_for_drafting": [],
        "slots": {
            "definition_kernel": [],
            "explanatory_gloss": [],
            "formula_notation": [],
            "example_or_procedure": [],
            "scope_condition": [],
            "sibling_contrast": [],
            "context_completion": [],
        },
        "pack_quality": {
            "status": "insufficient_support",
            "insufficient_reasons": [
                "zero_scored_candidates_for_requested_kc",
                "preserved_for_review_not_source_insufficiency_claim",
            ],
            "selected_candidate_count": 0,
            "ordered_pack_for_drafting_count": 0,
        },
        "expected_evidence_needs": [],
        "shapeaware_route": "insufficient_source_support_packet",
        "evidence_need_satisfaction": {},
        "review_risk_flags": [],
        "drafting_core_evidence": [],
        "auxiliary_evidence": [],
        "review_needed_evidence": [],
        "rejected_false_positive_evidence": [],
        "provenance_sidecar": {
            "selected_candidate_ids": [],
            "selected_stage2_candidate_ids": [],
            "ordered_candidate_ids": [],
            "ordered_stage2_candidate_ids": [],
            "dropped_candidate_ids": [],
            "all_source_refs": [],
            "zero_candidate_contract": True,
            "exact_kc_ids_requested": list(exact_kc_ids or []),
        },
        "source_manifests": list(source_manifests or []),
        "stage2_summary": {
            "scored_candidate_count": 0,
            "zero_candidate_contract": True,
            "interpretation": (
                "No scored candidates were available for this requested KC. "
                "This is a retrieval/profile gap unless separately proven to be corpus insufficiency."
            ),
        },
        "near_miss_review_items": [],
        "retrieval_failure_diagnosis": {
            "diagnosis_labels": ["retrieval_failure"],
            "primary_diagnosis": "retrieval_failure",
            "risk_flag_breakdown": {},
            "routing_recommendation_breakdown": {},
            "positive_support_count": 0,
            "ordered_pack_for_drafting_count": 0,
        },
        "retrieval_gap_requests": [],
        "missing_positive_support_reason": "retrieval_failure",
        "feedback_eligible": False,
        "feedback_payload": {},
        "section_anchor_summary": {"top_headings": [], "top_pages": [], "candidate_origin_breakdown": {}},
        "topic_scope_evidence": [],
        "representative_source_regions": [],
        "child_kc_coverage_summary": {},
        "source_section_map": [],
        "sibling_topic_boundary_notes": [],
        "topic_near_miss_review_items": [],
    }

def build_evidence_pack_artifacts(
    scored_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_manifest: str,
    scored_candidates_jsonl_path: str,
    config_path: str,
    exact_kc_ids: Optional[Sequence[str]] = None,
    limit_kcs: Optional[int] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    set_manifest_root: Path | str = DEFAULT_SET_MANIFEST_ROOT,
    repo_root: Path = REPO_ROOT,
    **_ignored_step5x_runner_compat_kwargs: Any,
) -> Dict[str, Any]:
    cfg = dict(cfg or {})
    run_id = str(run_id or f"step5x_v3_evidence_packs_{utc_stamp()}")
    output_root = resolve_repo_path(output_root, repo_root=repo_root)
    set_manifest_root = resolve_repo_path(set_manifest_root, repo_root=repo_root)
    processed_dir = output_root / run_id
    set_manifest_path = set_manifest_root / f"{run_id}_step5x_v3_evidence_packs_set.json"
    if processed_dir.exists() or set_manifest_path.exists():
        raise RuntimeError(f"Stage 3 run_id already exists: {run_id}")
    processed_dir.mkdir(parents=True, exist_ok=False)
    set_manifest_root.mkdir(parents=True, exist_ok=True)

    packs = compose_evidence_packs_from_scored_candidates(scored_rows, cfg)
    packs_path = processed_dir / "kc_evidence_packs.jsonl"
    stats_path = processed_dir / "evidence_pack_stats.json"
    schema_path = processed_dir / "evidence_pack_schema_snapshot.json"
    manifest_path = processed_dir / "evidence_pack_manifest.json"
    output_manifest_path = processed_dir / "output_manifest.json"
    retrieval_gap_requests_jsonl = processed_dir / "retrieval_gap_requests.jsonl"
    retrieval_gap_stats_json = processed_dir / "retrieval_gap_request_stats.json"

    stats = _stats(packs, scored_rows, run_id, source_manifest)
    schema = _schema_snapshot(packs)
    manifest = {
        "run_id": run_id,
        "stage": "step5x_v3_evidence_packs",
        "created_at": now_utc_iso(),
        "source_manifest": source_manifest,
        "scored_candidates_jsonl": scored_candidates_jsonl_path,
        "config_path": config_path,
        "artifacts": {
            "kc_evidence_packs_jsonl": _rel_path(packs_path, repo_root=repo_root),
            "evidence_pack_stats_json": _rel_path(stats_path, repo_root=repo_root),
            "evidence_pack_schema_snapshot_json": _rel_path(schema_path, repo_root=repo_root),
            "evidence_pack_manifest_json": _rel_path(manifest_path, repo_root=repo_root),
        },
        "inputs": {
            "stage2_scored_candidates_set_manifest": source_manifest,
            "scored_candidates_jsonl": scored_candidates_jsonl_path,
            "exact_kc_ids": list(exact_kc_ids or []),
            "limit_kcs": limit_kcs,
        },
        "compatibility": {
            "step6_6_ready": True,
            "step6_6_artifact_key": "kc_evidence_packs_jsonl",
            "step6_7_contract_changed": False,
            "active_pointer_created": False,
        },
    }
    set_manifest = {
        "run_id": run_id,
        "set_id": f"{run_id}_step5x_v3_evidence_packs_set",
        "stage": "step5x_v3_evidence_packs",
        "created_at": now_utc_iso(),
        "artifacts": {
            "kc_evidence_packs_jsonl": _rel_path(packs_path, repo_root=repo_root),
            "evidence_pack_stats_json": _rel_path(stats_path, repo_root=repo_root),
            "evidence_pack_schema_snapshot_json": _rel_path(schema_path, repo_root=repo_root),
            "evidence_pack_manifest_json": _rel_path(manifest_path, repo_root=repo_root),
        },
        "inputs": manifest["inputs"],
        "compatibility": manifest["compatibility"],
    }
    output_manifest = {
        "run_id": run_id,
        "stage": "step5x_v3_evidence_packs",
        "created_at": now_utc_iso(),
        "processed_dir": _rel_path(processed_dir, repo_root=repo_root),
        "set_manifest": _rel_path(set_manifest_path, repo_root=repo_root),
        "artifacts": manifest["artifacts"],
    }


    # Preserve requested zero-candidate KCs as explicit insufficient-support packs.
    # This is a KC survival contract only. It does not fabricate evidence and
    # does not claim source corpus insufficiency.
    try:
        _requested_exact_kc_ids = [str(kc_id) for kc_id in (exact_kc_ids or [])]
    except NameError:
        _requested_exact_kc_ids = []
    
    if _requested_exact_kc_ids:
        _existing_pack_kc_ids = set()
        for _pack_row in packs:
            if isinstance(_pack_row, dict):
                _existing_pack_kc_ids.add(str(_pack_row.get("kc_id")))
        _missing_pack_kc_ids = [
            _kc_id for _kc_id in _requested_exact_kc_ids
            if _kc_id not in _existing_pack_kc_ids
        ]
        for _missing_kc_id in _missing_pack_kc_ids:
            packs.append(
                _build_zero_candidate_insufficient_pack(
                    kc_id=_missing_kc_id,
                    exact_kc_ids=_requested_exact_kc_ids,
                    source_manifests=[],
                )
            )
    gap_stats = write_retrieval_gap_artifacts(
        scored_rows=scored_rows,
        packs=packs,
        output_jsonl=retrieval_gap_requests_jsonl,
        output_stats_json=retrieval_gap_stats_json,
        exact_kc_ids=exact_kc_ids,
        source_paths={
            "source_manifest": source_manifest,
            "scored_candidates_jsonl": scored_candidates_jsonl_path,
            "kc_evidence_packs_jsonl": _rel_path(packs_path, repo_root=repo_root),
        },
    )
    _attach_retrieval_gap_requests_to_packs(
        packs,
        _read_gap_requests_from_jsonl(retrieval_gap_requests_jsonl),
    )
    stats["retrieval_gap_requests"] = gap_stats
    manifest["artifacts"]["retrieval_gap_requests_jsonl"] = _rel_path(retrieval_gap_requests_jsonl, repo_root=repo_root)
    manifest["artifacts"]["retrieval_gap_request_stats_json"] = _rel_path(retrieval_gap_stats_json, repo_root=repo_root)
    set_manifest["artifacts"]["retrieval_gap_requests_jsonl"] = _rel_path(retrieval_gap_requests_jsonl, repo_root=repo_root)
    set_manifest["artifacts"]["retrieval_gap_request_stats_json"] = _rel_path(retrieval_gap_stats_json, repo_root=repo_root)

    write_jsonl(packs_path, packs)
    write_json(stats_path, stats)
    write_json(schema_path, schema)
    write_json(manifest_path, manifest)
    write_json(output_manifest_path, output_manifest)
    write_json(set_manifest_path, set_manifest)

    return {
        "run_id": run_id,
        "processed_dir": _rel_path(processed_dir, repo_root=repo_root),
        "set_manifest": _rel_path(set_manifest_path, repo_root=repo_root),
        "kc_evidence_packs_jsonl": _rel_path(packs_path, repo_root=repo_root),
        "evidence_pack_stats_json": _rel_path(stats_path, repo_root=repo_root),
        "evidence_pack_schema_snapshot_json": _rel_path(schema_path, repo_root=repo_root),
        "evidence_pack_manifest_json": _rel_path(manifest_path, repo_root=repo_root),
        "retrieval_gap_requests_jsonl": _rel_path(retrieval_gap_requests_jsonl, repo_root=repo_root),
        "retrieval_gap_request_stats_json": _rel_path(retrieval_gap_stats_json, repo_root=repo_root),
        "total_packs_emitted": len(packs),
        "retrieval_gap_request_count": int(gap_stats.get("gap_request_count") or 0),
    }


# ---------------------------------------------------------------------------
# Compatibility shim for recovered 204794-family Step 5x pack runner overlays.
# Some recovered runner versions import load_expected_kc_rows from this module,
# while the overlaid production pack module did not define it. This helper is
# deliberately conservative: it only builds expected KC row skeletons from
# explicit KC ids, registry-like rows, profile rows, or scored rows. It does
# not create evidence, does not alter scoring, and does not admit any item into
# ordered_pack_for_drafting.
# ---------------------------------------------------------------------------
def load_expected_kc_rows(*args, **kwargs):
    """Compatibility helper for recovered Step 5x pack runner overlays.

    Return shape intentionally matches the recovered runner contract:
        (expected_kc_rows, resolved_registry_jsonl)

    This function only reconstructs KC row skeletons from explicit ids and
    registry/profile/scored rows. It does not create evidence, does not alter
    scored rows, and does not admit any item into ordered_pack_for_drafting.
    """
    def _norm_id(value):
        text = str(value or "").strip()
        return text if text.startswith("KC_") else ""

    def _as_id_list(value):
        if value is None:
            return []
        if isinstance(value, str):
            return [_norm_id(x) for x in value.replace(",", " ").split() if _norm_id(x)]
        if isinstance(value, (list, tuple, set)):
            out = []
            for item in value:
                if isinstance(item, dict):
                    out.append(_norm_id(item.get("kc_id") or item.get("node_id") or item.get("id")))
                else:
                    out.append(_norm_id(item))
            return [x for x in out if x]
        return []

    def _read_jsonl_rows(path_value):
        if not path_value:
            return []
        try:
            path = Path(path_value)
        except TypeError:
            return []
        if not path.exists() or not path.is_file():
            return []
        rows = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    exact_ids = []
    row_sources = []

    resolved_registry_jsonl = ""
    for key in ("registry_jsonl", "registry_path", "expected_kc_rows_jsonl"):
        value = kwargs.get(key)
        if value:
            try:
                path = Path(value)
                if path.exists() and path.is_file():
                    resolved_registry_jsonl = path.as_posix()
                    break
            except TypeError:
                pass

    for key in (
        "exact_kc_ids",
        "expected_kc_ids",
        "kc_ids",
        "selected_kc_ids",
        "allowed_kc_ids",
    ):
        exact_ids.extend(_as_id_list(kwargs.get(key)))

    for key in (
        "expected_kc_rows",
        "kc_rows",
        "registry_rows",
        "profile_rows",
        "scored_rows",
        "scored_candidates",
    ):
        value = kwargs.get(key)
        if isinstance(value, (list, tuple)):
            row_sources.extend([x for x in value if isinstance(x, dict)])

    for key in (
        "registry_jsonl",
        "registry_path",
        "expected_kc_rows_jsonl",
        "profile_jsonl",
        "scored_candidates_jsonl",
    ):
        row_sources.extend(_read_jsonl_rows(kwargs.get(key)))

    for arg in args:
        if isinstance(arg, (list, tuple, set)):
            if all(isinstance(x, dict) for x in arg):
                row_sources.extend(list(arg))
            else:
                exact_ids.extend(_as_id_list(arg))
        elif isinstance(arg, dict):
            row_sources.append(arg)
        elif isinstance(arg, (str, Path)):
            rows = _read_jsonl_rows(arg)
            if rows:
                row_sources.extend(rows)
                if not resolved_registry_jsonl:
                    try:
                        path = Path(arg)
                        if path.exists() and path.is_file():
                            resolved_registry_jsonl = path.as_posix()
                    except TypeError:
                        pass
            else:
                exact_ids.extend(_as_id_list(arg))

    by_id = {}
    for row in row_sources:
        kc_id = _norm_id(row.get("kc_id") or row.get("node_id") or row.get("id"))
        if not kc_id:
            continue

        current = dict(by_id.get(kc_id) or {})
        current.update({k: v for k, v in row.items() if v not in (None, "", [], {})})
        current["kc_id"] = kc_id

        if "canonical_name" not in current:
            for alt in ("label", "name", "title", "kc_label"):
                if row.get(alt):
                    current["canonical_name"] = row.get(alt)
                    break

        by_id[kc_id] = current

    exact_ids = list(dict.fromkeys([x for x in exact_ids if x]))

    if exact_ids:
        rows = [dict(by_id.get(kc_id) or {"kc_id": kc_id}) for kc_id in exact_ids]
    else:
        rows = [by_id[kc_id] for kc_id in sorted(by_id)]

    limit_kcs = kwargs.get("limit_kcs")
    if limit_kcs is not None:
        try:
            limit = int(limit_kcs)
            if limit >= 0:
                rows = rows[:limit]
        except Exception:
            pass

    return rows, resolved_registry_jsonl

