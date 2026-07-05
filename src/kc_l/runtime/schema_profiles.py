from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kc_l.runtime.layout import get_operator_layout


LOCKED_CORE_SCHEMA_VERSION = "kc_library.locked_core.v1"
EXTENSION_SCHEMA_VERSION = "kc_library.extension_schema.v1"
ALLOWED_EXTENSION_TYPES = {
    "boolean",
    "enum",
    "json",
    "markdown",
    "string",
    "string_list",
    "string_or_null",
}


def default_locked_core_path() -> Path:
    return get_operator_layout().configs_root / "schemas" / "default" / "core_schema.locked.json"


def default_extension_template_path() -> Path:
    return get_operator_layout().configs_root / "schemas" / "examples" / "extension_schema.template.json"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Schema profile must be a JSON object: {path}")
    return payload


def load_locked_core_schema(path: str | Path | None = None) -> dict[str, Any]:
    schema_path = Path(path) if path is not None else default_locked_core_path()
    return _load_json(schema_path)


def load_extension_schema(path: str | Path) -> dict[str, Any]:
    return _load_json(Path(path))


def _locked_field_ids(locked_core_schema: dict[str, Any]) -> set[str]:
    field_ids: set[str] = set()
    for section in ("topic_library_locked_core", "kc_library_locked_core"):
        for row in locked_core_schema.get(section) or []:
            if isinstance(row, dict) and row.get("field_id"):
                field_ids.add(str(row["field_id"]))
    return field_ids


def validate_extension_schema(
    extension_schema: dict[str, Any],
    locked_core_schema: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    core_schema = locked_core_schema or load_locked_core_schema()
    locked_fields = _locked_field_ids(core_schema)

    if extension_schema.get("schema_profile_version") != EXTENSION_SCHEMA_VERSION:
        errors.append("Extension schema version must be kc_library.extension_schema.v1.")
    if extension_schema.get("locked_core_version") != LOCKED_CORE_SCHEMA_VERSION:
        errors.append("Extension schema must declare the matching locked core version.")

    extension_fields = extension_schema.get("extension_fields")
    if not isinstance(extension_fields, list):
        errors.append("Extension schema must define extension_fields as a list.")
        return errors

    seen_ids: set[str] = set()
    for row in extension_fields:
        if not isinstance(row, dict):
            errors.append("Each extension field must be a JSON object.")
            continue
        field_id = str(row.get("field_id") or "").strip()
        field_type = str(row.get("type") or "").strip()
        if not field_id:
            errors.append("Each extension field must include a non-empty field_id.")
            continue
        if field_id in seen_ids:
            errors.append(f"Duplicate extension field_id: {field_id}")
        seen_ids.add(field_id)
        if field_id in locked_fields:
            errors.append(f"Extension field_id collides with locked core field: {field_id}")
        if field_id == "kc_specific_criteria":
            errors.append("kc_specific_criteria must remain in the locked core and empty in this phase.")
        if field_type not in ALLOWED_EXTENSION_TYPES:
            errors.append(f"Unsupported extension field type for {field_id}: {field_type}")

    return errors


def build_merged_schema_profile(
    extension_schema_path: str | Path | None = None,
    locked_core_path: str | Path | None = None,
) -> dict[str, Any]:
    locked_core = load_locked_core_schema(locked_core_path)
    extension_path = Path(extension_schema_path) if extension_schema_path is not None else default_extension_template_path()
    extension = load_extension_schema(extension_path)
    errors = validate_extension_schema(extension, locked_core)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "locked_core": locked_core,
        "extension": extension,
        "merged_field_ids": sorted(_locked_field_ids(locked_core) | {row["field_id"] for row in extension["extension_fields"]}),
    }
