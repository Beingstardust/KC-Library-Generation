from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .role_target_contract import validate_role_target_contract_fields

PROFILE_CONTRACT_VERSION = "kc_retrieval_profile_v1"

ACTIVE_CUE_TYPES = {
    "source_observed_equivalent",
    "mechanism_description",
    "formula_relation",
    "process_phrase",
    "definition_phrase",
    "metric_relation",
    "context_phrase",
}

PROFILE_STATUSES = {"usable", "weak", "reject", "anchor_only", "likely_corpus_insufficient", "needs_rescue"}

FORBIDDEN_SEED_KEYS = {
    "seed_definition",
    "seed_floor",
    "seed_floor_fallback",
    "seed_definition_text",
    "seed_scope",
}

UNSAFE_FIELD_MARKERS = {
    "reference",
    "references",
    "bibliography",
    "metadata",
    "query_text",
    "canonical_name",
    "alias",
    "registry",
    "prompt",
    "synthetic",
}


class ProfileValidationError(ValueError):
    pass


def _walk_keys(obj: Any, path: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            current = f"{path}.{key}" if path else str(key)
            yield current, value
            yield from _walk_keys(value, current)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            current = f"{path}[{i}]"
            yield from _walk_keys(value, current)


def contains_forbidden_seed_field(obj: Any) -> List[str]:
    hits: List[str] = []
    for path, _ in _walk_keys(obj):
        leaf = path.split(".")[-1].split("[")[0].lower()
        if leaf in FORBIDDEN_SEED_KEYS:
            hits.append(path)
    return hits


def field_path_is_allowed(field_path: str) -> bool:
    low = str(field_path or "").lower()
    if not low:
        return False
    return not any(marker in low for marker in UNSAFE_FIELD_MARKERS)


def validate_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if profile.get("profile_contract_version") != PROFILE_CONTRACT_VERSION:
        errors.append("bad_or_missing_profile_contract_version")

    kc_id = str(profile.get("kc_id") or "").strip()
    if not kc_id:
        errors.append("missing_kc_id")

    canonical_name = str(profile.get("canonical_name") or "").strip()
    if not canonical_name:
        errors.append("missing_canonical_name")

    status = str(profile.get("profile_status") or "").strip()
    if status not in PROFILE_STATUSES:
        errors.append("bad_profile_status")

    seed_hits = contains_forbidden_seed_field(profile)
    if seed_hits:
        errors.append("forbidden_seed_fields_present:" + ",".join(seed_hits[:10]))

    accepted = profile.get("accepted_source_cues") or []
    if not isinstance(accepted, list):
        errors.append("accepted_source_cues_not_list")
        accepted = []

    active_terms = Counter()
    for i, cue in enumerate(accepted):
        if not isinstance(cue, Mapping):
            errors.append(f"accepted_source_cues[{i}]_not_object")
            continue

        term = str(cue.get("term") or "").strip()
        cue_type = str(cue.get("cue_type") or "").strip()
        active = cue.get("active")

        if not term:
            errors.append(f"accepted_source_cues[{i}]_missing_term")
        else:
            active_terms[term.lower()] += 1

        if cue_type not in ACTIVE_CUE_TYPES:
            errors.append(f"accepted_source_cues[{i}]_bad_cue_type:{cue_type}")

        if active is not True:
            errors.append(f"accepted_source_cues[{i}]_active_not_true")

        provenance = cue.get("provenance") or []
        if not isinstance(provenance, list) or not provenance:
            errors.append(f"accepted_source_cues[{i}]_missing_provenance")
            continue

        for j, prov in enumerate(provenance):
            if not isinstance(prov, Mapping):
                errors.append(f"accepted_source_cues[{i}].provenance[{j}]_not_object")
                continue

            snippet_id = str(prov.get("snippet_id") or prov.get("sentence_id") or prov.get("source_id") or "").strip()
            field_path = str(prov.get("field_path") or "").strip()

            if not snippet_id:
                errors.append(f"accepted_source_cues[{i}].provenance[{j}]_missing_snippet_id")

            if not field_path:
                errors.append(f"accepted_source_cues[{i}].provenance[{j}]_missing_field_path")
            elif not field_path_is_allowed(field_path):
                errors.append(f"accepted_source_cues[{i}].provenance[{j}]_unsafe_field_path:{field_path}")

    duplicate_active_terms = [term for term, count in active_terms.items() if count > 1]
    if duplicate_active_terms:
        warnings.append("duplicate_active_source_cues:" + ",".join(duplicate_active_terms[:10]))

    quarantined = profile.get("quarantined_terms") or []
    if not isinstance(quarantined, list):
        errors.append("quarantined_terms_not_list")
        quarantined = []

    for i, term in enumerate(quarantined):
        if not isinstance(term, Mapping):
            errors.append(f"quarantined_terms[{i}]_not_object")
            continue
        if term.get("active") is True:
            errors.append(f"quarantined_terms[{i}]_active_true")

    query_variants = profile.get("query_variants") or []
    if not isinstance(query_variants, list):
        errors.append("query_variants_not_list")
        query_variants = []

    for i, query in enumerate(query_variants):
        if not isinstance(query, Mapping):
            errors.append(f"query_variants[{i}]_not_object")
            continue
        if query.get("active") is not True:
            errors.append(f"query_variants[{i}]_active_not_true")
        source = str(query.get("source") or "")
        if source == "model_suggested_unconfirmed":
            errors.append(f"query_variants[{i}]_uses_unconfirmed_model_suggestion")

    active_query_terms = profile.get("active_query_terms") or []
    if not isinstance(active_query_terms, list):
        errors.append("active_query_terms_not_list")
        active_query_terms = []

    for i, term in enumerate(active_query_terms):
        if not isinstance(term, Mapping):
            errors.append(f"active_query_terms[{i}]_not_object")
            continue
        if not str(term.get("term") or "").strip():
            errors.append(f"active_query_terms[{i}]_missing_term")
        if str(term.get("source") or "") in {"model_suggested_unverified", "model_suggested_unconfirmed"}:
            errors.append(f"active_query_terms[{i}]_uses_unconfirmed_model_suggestion")
        if term.get("step5x_verification_required") is not True:
            errors.append(f"active_query_terms[{i}]_missing_step5x_verification_required")

    source_equivalent_terms = profile.get("source_equivalent_terms") or []
    if not isinstance(source_equivalent_terms, list):
        errors.append("source_equivalent_terms_not_list")
        source_equivalent_terms = []

    for i, term in enumerate(source_equivalent_terms):
        if not isinstance(term, Mapping):
            errors.append(f"source_equivalent_terms[{i}]_not_object")
            continue
        if not str(term.get("term") or "").strip():
            errors.append(f"source_equivalent_terms[{i}]_missing_term")
        provenance = term.get("provenance") or []
        if not isinstance(provenance, list) or not provenance:
            errors.append(f"source_equivalent_terms[{i}]_missing_provenance")
        if term.get("step5x_verification_required") is not True:
            errors.append(f"source_equivalent_terms[{i}]_missing_step5x_verification_required")

    expected_evidence_shape = profile.get("expected_evidence_shape") or []
    if not isinstance(expected_evidence_shape, list):
        errors.append("expected_evidence_shape_not_list")

    source_windows = profile.get("source_windows") or []
    if not isinstance(source_windows, list):
        errors.append("source_windows_not_list")
        source_windows = []

    for i, window in enumerate(source_windows):
        if not isinstance(window, Mapping):
            errors.append(f"source_windows[{i}]_not_object")
            continue
        if window.get("step5x_verification_required") is not True:
            errors.append(f"source_windows[{i}]_missing_step5x_verification_required")
        for unsafe_text_key in ("text", "sentence_text", "source_block_text", "context_text", "quoted_text"):
            if unsafe_text_key in window:
                errors.append(f"source_windows[{i}]_contains_text_field:{unsafe_text_key}")

    if "rescue_eligible" in profile and not isinstance(profile.get("rescue_eligible"), bool):
        errors.append("rescue_eligible_not_bool")

    role_target_validation = validate_role_target_contract_fields(profile)
    errors.extend(role_target_validation.get("errors") or [])
    warnings.extend(role_target_validation.get("warnings") or [])

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def validate_profile_collection(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    kc_counter = Counter(str(row.get("kc_id") or "") for row in rows)

    for kc_id, count in kc_counter.items():
        if not kc_id:
            errors.append("blank_kc_id_present")
        elif count != 1:
            errors.append(f"kc_id_not_unique:{kc_id}:{count}")

    for row in rows:
        result = validate_profile(row)
        if not result["ok"]:
            errors.append(f"{row.get('kc_id')}: " + ";".join(result["errors"]))
        warnings.extend([f"{row.get('kc_id')}: {w}" for w in result["warnings"]])

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "row_count": len(rows),
        "unique_kc_count": len([k for k in kc_counter if k]),
    }
