from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


KC_TYPES = {
    "concept",
    "procedure",
    "metric",
    "theorem_or_claim",
    "misconception_cluster",
}
RECOVERY_STATES = {"none", "needs_recovery", "manual_required"}
EVIDENCE_ROLES = {"definition", "scope", "procedure", "equation", "example", "warning", "other"}
TIER1_RETRIEVAL_ROLES = {"definition", "equation", "procedure", "other"}


def load_schema(schema_path: Path) -> dict[str, Any]:
    obj = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected JSON object schema at {schema_path}")
    return obj


def schema_version(schema: Mapping[str, Any]) -> str:
    value = schema.get("schema_version")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("Schema is missing schema_version.")
    return value


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_nonempty_string_list(value: Any) -> bool:
    return _is_string_list(value) and len(value) > 0


def _append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _validate_evidence_span(prefix: str, evidence: Any) -> list[str]:
    errors: list[str] = []
    _append(errors, isinstance(evidence, dict), f"{prefix}: expected object")
    if not isinstance(evidence, dict):
        return errors

    required = [
        "doc_id",
        "block_id",
        "page_index",
        "layer",
        "role",
        "quote",
        "extraction_method",
        "quote_verified",
    ]
    for key in required:
        _append(errors, key in evidence, f"{prefix}.{key}: missing")

    if "doc_id" in evidence:
        _append(errors, _is_nonempty_string(evidence["doc_id"]), f"{prefix}.doc_id: expected non-empty string")
    if "block_id" in evidence:
        _append(errors, _is_nonempty_string(evidence["block_id"]), f"{prefix}.block_id: expected non-empty string")
    if "page_index" in evidence:
        _append(
            errors,
            isinstance(evidence["page_index"], int) and evidence["page_index"] >= 0,
            f"{prefix}.page_index: expected integer >= 0",
        )
    if "layer" in evidence:
        _append(errors, _is_nonempty_string(evidence["layer"]), f"{prefix}.layer: expected non-empty string")
    if "role" in evidence:
        _append(errors, evidence["role"] in EVIDENCE_ROLES, f"{prefix}.role: invalid value")
    if "quote" in evidence:
        _append(errors, _is_nonempty_string(evidence["quote"]), f"{prefix}.quote: expected non-empty string")
    if "extraction_method" in evidence:
        _append(
            errors,
            _is_nonempty_string(evidence["extraction_method"]),
            f"{prefix}.extraction_method: expected non-empty string",
        )
    if "quote_verified" in evidence:
        _append(errors, isinstance(evidence["quote_verified"], bool), f"{prefix}.quote_verified: expected boolean")
    if "bbox" in evidence and evidence["bbox"] is not None:
        bbox = evidence["bbox"]
        _append(
            errors,
            isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox),
            f"{prefix}.bbox: expected [x0, y0, x1, y1] or null",
        )
    if "provenance_quality_flags" in evidence:
        _append(
            errors,
            _is_string_list(evidence["provenance_quality_flags"]),
            f"{prefix}.provenance_quality_flags: expected string array",
        )
    return errors


def _validate_text_with_evidence(prefix: str, value: Any) -> list[str]:
    errors: list[str] = []
    _append(errors, isinstance(value, dict), f"{prefix}: expected object")
    if not isinstance(value, dict):
        return errors
    _append(errors, _is_nonempty_string(value.get("text")), f"{prefix}.text: expected non-empty string")
    evidence = value.get("evidence")
    _append(errors, isinstance(evidence, list), f"{prefix}.evidence: expected list")
    if isinstance(evidence, list):
        for idx, item in enumerate(evidence):
            errors.extend(_validate_evidence_span(f"{prefix}.evidence[{idx}]", item))
    return errors


def _validate_parameters(prefix: str, value: Any) -> list[str]:
    errors: list[str] = []
    _append(errors, isinstance(value, list), f"{prefix}: expected list")
    if not isinstance(value, list):
        return errors
    for idx, item in enumerate(value):
        item_prefix = f"{prefix}[{idx}]"
        _append(errors, isinstance(item, dict), f"{item_prefix}: expected object")
        if not isinstance(item, dict):
            continue
        _append(errors, _is_nonempty_string(item.get("name")), f"{item_prefix}.name: expected non-empty string")
        if "meaning" in item:
            _append(errors, isinstance(item["meaning"], str), f"{item_prefix}.meaning: expected string")
        if "constraints" in item:
            _append(errors, isinstance(item["constraints"], str), f"{item_prefix}.constraints: expected string")
        evidence = item.get("evidence")
        _append(errors, isinstance(evidence, list), f"{item_prefix}.evidence: expected list")
        if isinstance(evidence, list):
            for eidx, ev in enumerate(evidence):
                errors.extend(_validate_evidence_span(f"{item_prefix}.evidence[{eidx}]", ev))
    return errors


def _validate_text_with_evidence_list(prefix: str, value: Any) -> list[str]:
    errors: list[str] = []
    _append(errors, isinstance(value, list), f"{prefix}: expected list")
    if not isinstance(value, list):
        return errors
    for idx, item in enumerate(value):
        errors.extend(_validate_text_with_evidence(f"{prefix}[{idx}]", item))
    return errors


def validate_kc_record(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "kc_id",
        "kc_path",
        "canonical_name",
        "aliases",
        "seed_definition",
        "kc_type",
        "definition_short",
        "definition_full",
        "scope_includes",
        "scope_excludes",
        "evidence_minimal",
        "field_evidence_map",
        "kc_specific_criteria",
        "source_set_ids",
        "record_meta",
        "quality_flags",
        "recovery_state",
        "recovery_reasons",
    ]
    for key in required:
        _append(errors, key in record, f"{key}: missing")

    _append(errors, _is_nonempty_string(record.get("kc_id")), "kc_id: expected non-empty string")
    _append(errors, _is_nonempty_string(record.get("canonical_name")), "canonical_name: expected non-empty string")
    _append(errors, isinstance(record.get("seed_definition"), str), "seed_definition: expected string")
    _append(errors, _is_string_list(record.get("aliases")), "aliases: expected string array")
    _append(errors, _is_string_list(record.get("quality_flags")), "quality_flags: expected string array")
    _append(errors, _is_string_list(record.get("recovery_reasons")), "recovery_reasons: expected string array")
    _append(errors, isinstance(record.get("kc_specific_criteria"), str), "kc_specific_criteria: expected string")
    _append(errors, isinstance(record.get("definition_short"), str), "definition_short: expected string")
    _append(errors, isinstance(record.get("definition_full"), str), "definition_full: expected string")
    _append(errors, record.get("kc_type") in KC_TYPES, "kc_type: invalid value")
    _append(errors, record.get("recovery_state") in RECOVERY_STATES, "recovery_state: invalid value")
    _append(errors, _is_string_list(record.get("scope_includes")), "scope_includes: expected string array")
    _append(errors, _is_string_list(record.get("scope_excludes")), "scope_excludes: expected string array")

    kc_path = record.get("kc_path")
    _append(errors, isinstance(kc_path, list) and len(kc_path) > 0, "kc_path: expected non-empty array")
    if isinstance(kc_path, list):
        for idx, item in enumerate(kc_path):
            _append(errors, _is_nonempty_string(item), f"kc_path[{idx}]: expected non-empty string")

    source_set_ids = record.get("source_set_ids")
    _append(errors, isinstance(source_set_ids, dict), "source_set_ids: expected object")
    if isinstance(source_set_ids, dict):
        _append(errors, _is_nonempty_string(source_set_ids.get("step4_set_id")), "source_set_ids.step4_set_id: required")
        _append(errors, _is_nonempty_string(source_set_ids.get("step5_set_id")), "source_set_ids.step5_set_id: required")

    record_meta = record.get("record_meta")
    _append(errors, isinstance(record_meta, dict), "record_meta: expected object")
    if isinstance(record_meta, dict):
        _append(errors, _is_nonempty_string(record_meta.get("created_utc")), "record_meta.created_utc: required")
        _append(errors, _is_nonempty_string(record_meta.get("run_id_step6")), "record_meta.run_id_step6: required")
        _append(errors, _is_nonempty_string(record_meta.get("schema_version")), "record_meta.schema_version: required")

    evidence_minimal = record.get("evidence_minimal")
    _append(errors, isinstance(evidence_minimal, list), "evidence_minimal: expected list")
    if isinstance(evidence_minimal, list):
        for idx, evidence in enumerate(evidence_minimal):
            errors.extend(_validate_evidence_span(f"evidence_minimal[{idx}]", evidence))

    field_map = record.get("field_evidence_map")
    _append(errors, isinstance(field_map, dict), "field_evidence_map: expected object")
    if isinstance(field_map, dict):
        for key, value in field_map.items():
            _append(errors, isinstance(key, str) and bool(key), f"field_evidence_map key {key!r}: invalid")
            _append(errors, isinstance(value, list), f"field_evidence_map.{key}: expected list")
            if isinstance(value, list):
                for idx, evidence in enumerate(value):
                    errors.extend(_validate_evidence_span(f"field_evidence_map.{key}[{idx}]", evidence))

    optional_string_fields = [
        "inputs_outputs",
        "termination_condition",
        "formal_definition",
        "interpretation",
        "when_to_use",
        "when_not_to_use",
        "claim_statement",
        "misconception_statement",
        "canonical_correction",
    ]
    for key in optional_string_fields:
        if key in record:
            _append(errors, isinstance(record[key], str), f"{key}: expected string")

    optional_string_list_fields = [
        "procedure_steps",
        "diagnostic_cues",
        "remediation_suggestions",
    ]
    for key in optional_string_list_fields:
        if key in record:
            _append(errors, _is_string_list(record[key]), f"{key}: expected string array")

    if "parameters" in record:
        errors.extend(_validate_parameters("parameters", record["parameters"]))
    if "assumptions" in record:
        errors.extend(_validate_text_with_evidence_list("assumptions", record["assumptions"]))
    if "worked_examples" in record:
        errors.extend(_validate_text_with_evidence_list("worked_examples", record["worked_examples"]))
    if "references" in record:
        errors.extend(_validate_text_with_evidence_list("references", record["references"]))

    kc_type = record.get("kc_type")
    if kc_type == "procedure":
        for key in ["inputs_outputs", "procedure_steps", "parameters"]:
            _append(errors, key in record, f"{key}: required for kc_type=procedure")
    if kc_type == "metric":
        for key in ["formal_definition", "interpretation"]:
            _append(errors, key in record, f"{key}: required for kc_type=metric")
    if kc_type == "theorem_or_claim":
        for key in ["claim_statement", "assumptions"]:
            _append(errors, key in record, f"{key}: required for kc_type=theorem_or_claim")
    if kc_type == "misconception_cluster":
        for key in [
            "misconception_statement",
            "canonical_correction",
            "diagnostic_cues",
            "remediation_suggestions",
        ]:
            _append(errors, key in record, f"{key}: required for kc_type=misconception_cluster")

    return errors


def _has_verified_definition_evidence(evidence_items: Iterable[Mapping[str, Any]]) -> bool:
    return any(
        bool(item.get("quote_verified")) and item.get("role") == "definition"
        for item in evidence_items
        if isinstance(item, Mapping)
    )


def _verified_evidence_items(evidence_items: Any) -> list[Mapping[str, Any]]:
    if not isinstance(evidence_items, list):
        return []
    return [
        item
        for item in evidence_items
        if isinstance(item, Mapping) and item.get("quote_verified") is True
    ]


def _has_verified_retrieval_role(evidence_items: Iterable[Mapping[str, Any]]) -> bool:
    return any(str(item.get("role")) in TIER1_RETRIEVAL_ROLES for item in evidence_items)


def _has_tier2_boundary_signal(record: Mapping[str, Any]) -> bool:
    return (
        _is_nonempty_string_list(record.get("scope_includes"))
        or _is_nonempty_string_list(record.get("scope_excludes"))
        or _is_nonempty_string_list(record.get("discriminators"))
    )


def _type_incomplete_flags(record: Mapping[str, Any]) -> list[str]:
    kc_type = record.get("kc_type")
    if kc_type == "procedure":
        if not _is_nonempty_string(record.get("inputs_outputs")) and not _is_nonempty_string_list(
            record.get("procedure_steps")
        ):
            return ["TypeIncomplete:procedure"]
    if kc_type == "metric":
        if not _is_nonempty_string(record.get("formal_definition")):
            return ["TypeIncomplete:metric"]
    if kc_type == "theorem_or_claim":
        if not _is_nonempty_string(record.get("claim_statement")):
            return ["TypeIncomplete:theorem_or_claim"]
    if kc_type == "misconception_cluster":
        if not _is_nonempty_string(record.get("misconception_statement")):
            return ["TypeIncomplete:misconception_cluster"]
    return []


def _tier2_reasons(record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not _has_tier2_boundary_signal(record):
        reasons.append("Tier2MissingBoundaryOrDiscriminator")

    kc_type = record.get("kc_type")
    if kc_type == "procedure":
        if not _is_nonempty_string(record.get("inputs_outputs")) and not _is_nonempty_string_list(
            record.get("procedure_steps")
        ):
            reasons.append("Tier2MissingProcedureDetail")
    if kc_type == "metric":
        if not _is_nonempty_string(record.get("formal_definition")):
            reasons.append("Tier2MissingFormalDefinition")
    if kc_type == "theorem_or_claim":
        if not _is_nonempty_string(record.get("claim_statement")):
            reasons.append("Tier2MissingClaimStatement")
    if kc_type == "misconception_cluster":
        if not _is_nonempty_string(record.get("misconception_statement")):
            reasons.append("Tier2MissingMisconceptionStatement")
    return reasons


def classify_tier(record: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    evidence_minimal = record.get("evidence_minimal")
    evidence_count = len(evidence_minimal) if isinstance(evidence_minimal, list) else 0
    verified_items = _verified_evidence_items(evidence_minimal)

    if evidence_count < 2:
        reasons.append("Tier1MissingEvidenceMinimalCount")
    if len(verified_items) < 2:
        reasons.append("Tier1MissingVerifiedQuotes")
    if not (_is_nonempty_string(record.get("definition_short")) or _is_nonempty_string(record.get("definition_full"))):
        reasons.append("Tier1MissingDefinition")
    if not _has_verified_retrieval_role(verified_items):
        reasons.append("Tier1MissingVerifiedRetrievalRole")

    flags = _type_incomplete_flags(record)
    if reasons:
        return {"tier": 0, "reasons": reasons, "flags": flags}

    tier2_reasons = _tier2_reasons(record)
    if tier2_reasons:
        return {"tier": 1, "reasons": tier2_reasons, "flags": flags}
    return {"tier": 2, "reasons": [], "flags": flags}


def compute_missing_usability_fields(record: Mapping[str, Any]) -> list[str]:
    tier_info = classify_tier(record)
    if int(tier_info["tier"]) >= 1:
        return []
    return [str(reason) for reason in tier_info["reasons"]]


def is_record_usable(record: Mapping[str, Any]) -> bool:
    return int(classify_tier(record)["tier"]) >= 1
