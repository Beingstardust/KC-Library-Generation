from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.kc.downstream_library import load_operational_kc_library
from kc_l.utils.json_io import read_jsonl, write_json, write_jsonl


RESTARTED_RUNTIME_PACKAGING_STAGE = "step6_12_reviewed_library_runtime_packaging"
RESTARTED_RUNTIME_PACKAGING_RULE_VERSION = "step6.12.reviewed_runtime_packaging.v1"
RUNTIME_ENTRY_SCHEMA_VERSION = "step6.runtime.restarted.v1"
FROZEN_LIBRARY_TIER = "frozen_reviewed_library"


@dataclass(frozen=True)
class RestartedRuntimePackagingResult:
    output_dir: Path
    runtime_library_path: Path
    runtime_summary_path: Path
    runtime_preview_path: Path
    runtime_manifest_path: Path
    runtime_entry_count: int


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _matching_text(title: str, aliases: Sequence[str], definition: str, scope: str) -> str:
    parts = [title, *aliases, definition, scope]
    return " ".join(part for part in (item.strip() for item in parts if item is not None) if part)


def _display_text(title: str, definition: str, scope: str) -> str:
    parts = [title, definition]
    if scope:
        parts.append(scope)
    return "\n".join(part for part in parts if part)


def _search_terms(title: str, aliases: Sequence[str], canonical_name: str) -> list[str]:
    return _normalize_string_list([title, canonical_name, *aliases])


def validate_runtime_entry(entry: Mapping[str, Any]) -> None:
    _ensure(_as_text(entry.get("runtime_entry_id")), "runtime_entry_id is required")
    _ensure(_as_text(entry.get("schema_version")) == RUNTIME_ENTRY_SCHEMA_VERSION, "runtime schema_version mismatch")
    _ensure(_as_text(entry.get("kc_id")), "kc_id is required")
    _ensure(_as_text(entry.get("title")), "title is required")
    _ensure(_as_text(entry.get("level")), "level is required")
    _ensure(_as_text(entry.get("source_library_tier")) == FROZEN_LIBRARY_TIER, "source_library_tier must be frozen_reviewed_library")
    _ensure(_as_text(entry.get("source_review_status")) in {"approved", "edited_approved"}, "source_review_status invalid")
    _ensure(_as_text(entry.get("reviewer_facing_definition")), "reviewer_facing_definition is required")
    _ensure(_as_text(entry.get("matching_text")), "matching_text is required")
    _ensure(_as_text(entry.get("segmentation_text")), "segmentation_text is required")
    _ensure(_as_text(entry.get("display_text")), "display_text is required")
    _ensure(isinstance(entry.get("search_terms"), list) and bool(entry.get("search_terms")), "search_terms must be a non-empty list")
    _ensure(isinstance(entry.get("source_provenance"), Mapping), "source_provenance must be an object")
    _ensure(isinstance(entry.get("evidence_spans"), list) and bool(entry.get("evidence_spans")), "evidence_spans must be a non-empty list")
    _ensure(isinstance(entry.get("linked_evidence_ids"), list) and bool(entry.get("linked_evidence_ids")), "linked_evidence_ids must be a non-empty list")


def build_runtime_entry(
    *,
    source_entry: Mapping[str, Any],
    assembly_run_id: str,
    source_reviewed_set_id: str,
) -> dict[str, Any]:
    kc_id = _as_text(source_entry.get("kc_id"))
    title = _as_text(source_entry.get("title"))
    canonical_name = _as_text(source_entry.get("canonical_name")) or title
    aliases = _normalize_string_list(source_entry.get("aliases"))
    definition = _as_text(source_entry.get("reviewer_facing_definition"))
    scope_value = source_entry.get("reviewer_facing_scope")
    scope = _as_text(scope_value)
    matching_text = _matching_text(title, aliases, definition, scope)
    display_text = _display_text(title, definition, scope)

    source_provenance = {
        "assembly_stage": RESTARTED_RUNTIME_PACKAGING_STAGE,
        "assembly_run_id": assembly_run_id,
        "source_reviewed_library_set_id": source_reviewed_set_id,
        "source_reviewed_library_run_id": _as_text(source_entry.get("assembly_run_id")),
        "source_resolution_run_id": _as_text(source_entry.get("source_run_id")),
        "source_stage_lineage": dict((source_entry.get("source_provenance") or {}).get("source_stage_lineage") or {}),
        "source_document_ids": list((source_entry.get("source_provenance") or {}).get("source_document_ids") or []),
    }

    entry = {
        "schema_version": RUNTIME_ENTRY_SCHEMA_VERSION,
        "runtime_entry_id": f"step6_12:{assembly_run_id}:{kc_id}",
        "kc_id": kc_id,
        "title": title,
        "canonical_name": canonical_name,
        "aliases": aliases,
        "level": _as_text(source_entry.get("level")) or "atomic",
        "source_library_tier": _as_text(source_entry.get("library_tier")),
        "source_review_status": _as_text(source_entry.get("review_status")),
        "source_review_packet_id": _as_text(source_entry.get("review_packet_id")),
        "source_review_event_id": _as_text(source_entry.get("review_event_id")),
        "reviewer_facing_definition": definition,
        "reviewer_facing_scope": scope_value,
        "scope_status": _as_text(source_entry.get("scope_status")),
        "matching_text": matching_text,
        "segmentation_text": display_text,
        "display_text": display_text,
        "search_terms": _search_terms(title, aliases, canonical_name),
        "risk_flags": list(source_entry.get("risk_flags") or []),
        "review_priority": dict(source_entry.get("review_priority") or {}),
        "system_recommendation": dict(source_entry.get("system_recommendation") or {}),
        "field_linked_evidence_ids": dict(source_entry.get("field_linked_evidence_ids") or {}),
        "linked_evidence_ids": list(source_entry.get("linked_evidence_ids") or []),
        "evidence_spans": list(source_entry.get("evidence_spans") or []),
        "source_provenance": source_provenance,
    }
    validate_runtime_entry(entry)
    return entry

def build_runtime_summary(
    *,
    runtime_entries: Sequence[Mapping[str, Any]],
    source_reviewed_set_id: str,
    validation_failures: Sequence[str],
    source_frozen_load_passed: bool,
) -> dict[str, Any]:
    status_counts = Counter(_as_text(entry.get("source_review_status")) for entry in runtime_entries)
    scope_blank_kcs = [entry["kc_id"] for entry in runtime_entries if not _as_text(entry.get("reviewer_facing_scope"))]
    intentionally_blank_fields_preserved = [
        f"{entry['kc_id']}.scope"
        for entry in runtime_entries
        if _as_text(entry.get("scope_status")) == "intentionally_blank"
    ]
    validation = {
        "source_frozen_load_passed": source_frozen_load_passed,
        "runtime_entry_validation_failures": list(validation_failures),
        "sandbox_excluded_by_construction": True,
    }
    return {
        "schema_version": "1.0",
        "stage": RESTARTED_RUNTIME_PACKAGING_STAGE,
        "rule_version": RESTARTED_RUNTIME_PACKAGING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "runtime_entry_count": len(runtime_entries),
        "source_frozen_load_success": source_frozen_load_passed,
        "source_review_status_counts": dict(status_counts),
        "included_kcs": [entry["kc_id"] for entry in runtime_entries],
        "scope_blank_kcs": scope_blank_kcs,
        "intentionally_blank_fields_preserved": intentionally_blank_fields_preserved,
        "sandbox_excluded_by_construction": True,
        "runtime_validation_failures": list(validation_failures),
        "contract_validation_failures": list(validation_failures),
        "validation": validation,
    }


def build_runtime_preview(*, summary: Mapping[str, Any], runtime_entries: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Restarted Runtime Package Preview",
        "",
        f"- Runtime entries: `{summary['runtime_entry_count']}`",
        f"- Source frozen load success: `{summary['source_frozen_load_success']}`",
        f"- Source review statuses: `{summary['source_review_status_counts']}`",
        f"- Scope-blank KCs: `{summary['scope_blank_kcs']}`",
        f"- Intentionally blank fields preserved: `{summary['intentionally_blank_fields_preserved']}`",
        f"- Sandbox excluded by construction: `{summary['sandbox_excluded_by_construction']}`",
        f"- Runtime validation failures: `{summary['runtime_validation_failures']}`",
        "",
        "## Sample Runtime Entries",
        "",
    ]
    for entry in runtime_entries[:5]:
        lines.extend(
            [
                f"### {entry['kc_id']} - {entry['source_review_status']}",
                "",
                f"- Title: `{entry['title']}`",
                f"- Search terms: `{entry['search_terms']}`",
                f"- Matching text: `{entry['matching_text']}`",
                f"- Scope: `{entry.get('reviewer_facing_scope')}`",
                f"- Linked evidence ids: `{entry['linked_evidence_ids']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def assemble_restarted_runtime_package(
    *,
    source_reviewed_library_path: Path,
    output_dir: Path,
    assembly_run_id: str,
    source_reviewed_set_id: str,
) -> RestartedRuntimePackagingResult:
    source_reviewed_library_path = source_reviewed_library_path.resolve()
    output_dir = output_dir.resolve()

    load_operational_kc_library(source_reviewed_library_path, expected_tier=FROZEN_LIBRARY_TIER)
    source_rows = read_jsonl(source_reviewed_library_path)

    validation_failures: list[str] = []
    runtime_entries: list[dict[str, Any]] = []
    for row in source_rows:
        kc_id = _as_text(row.get("kc_id"))
        try:
            runtime_entries.append(
                build_runtime_entry(
                    source_entry=row,
                    assembly_run_id=assembly_run_id,
                    source_reviewed_set_id=source_reviewed_set_id,
                )
            )
        except Exception as exc:
            validation_failures.append(f"{kc_id}: {exc}")
            raise

    summary = build_runtime_summary(
        runtime_entries=runtime_entries,
        source_reviewed_set_id=source_reviewed_set_id,
        validation_failures=validation_failures,
        source_frozen_load_passed=True,
    )
    preview = build_runtime_preview(summary=summary, runtime_entries=runtime_entries)
    manifest = {
        "schema_version": "1.0",
        "stage": RESTARTED_RUNTIME_PACKAGING_STAGE,
        "rule_version": RESTARTED_RUNTIME_PACKAGING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_reviewed_library_jsonl": str(source_reviewed_library_path),
        "runtime_entry_count": len(runtime_entries),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_library_path = output_dir / "runtime_kc_library.jsonl"
    runtime_summary_path = output_dir / "runtime_package_summary.json"
    runtime_preview_path = output_dir / "runtime_package_preview.md"
    runtime_manifest_path = output_dir / "runtime_package_manifest.json"
    write_jsonl(runtime_library_path, runtime_entries)
    write_json(runtime_summary_path, summary)
    runtime_preview_path.write_text(preview, encoding="utf-8")
    write_json(runtime_manifest_path, manifest)

    return RestartedRuntimePackagingResult(
        output_dir=output_dir,
        runtime_library_path=runtime_library_path,
        runtime_summary_path=runtime_summary_path,
        runtime_preview_path=runtime_preview_path,
        runtime_manifest_path=runtime_manifest_path,
        runtime_entry_count=len(runtime_entries),
    )
