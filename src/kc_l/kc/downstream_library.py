from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from kc_l.utils.json_io import read_json, read_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]
DOWNSTREAM_LIBRARY_CONTRACT_VERSION = "step6.downstream_library_contract.v1"
DOWNSTREAM_LIBRARY_CONTRACT_PATH = Path(__file__).with_name("schemas") / "downstream_library_contract.json"


class DownstreamLibraryContractError(ValueError):
    pass


@dataclass(frozen=True)
class DownstreamKCRecord:
    library_tier: str
    review_status: str
    source_run_id: str
    kc_id: str
    title: str
    level: str
    reviewer_facing_definition: str
    evidence_spans: tuple[dict[str, Any], ...]
    source_provenance: dict[str, Any]
    risk_flags: tuple[str, ...] = ()
    review_priority: dict[str, Any] | None = None
    system_recommendation: dict[str, Any] | None = None
    content_source_mode: str = ""
    content_repair_applied: bool = False
    content_repair_reason: str = ""
    original_content_source: dict[str, Any] | None = None
    review_content_source: dict[str, Any] | None = None
    integrity_repair_notes: tuple[str, ...] = ()
    status: str = ""

    @property
    def is_human_reviewed(self) -> bool:
        return self.library_tier == "frozen_reviewed_library" and self.review_status in {"approved", "edited_approved"}


@dataclass(frozen=True)
class FullProvisionalLibraryPackage:
    manifest_path: Path
    manifest: dict[str, Any]
    provisional_library_path: Path
    sandbox_path: Path
    entries: tuple[DownstreamKCRecord, ...]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise DownstreamLibraryContractError(message)


def load_downstream_library_contract() -> dict[str, Any]:
    contract = read_json(DOWNSTREAM_LIBRARY_CONTRACT_PATH)
    if not isinstance(contract, dict):
        raise RuntimeError(f"Expected JSON object contract at {DOWNSTREAM_LIBRARY_CONTRACT_PATH}")
    version = _as_text(contract.get("schema_version"))
    if version != DOWNSTREAM_LIBRARY_CONTRACT_VERSION:
        raise RuntimeError(
            f"Unexpected downstream library contract version: {version or '<missing>'} != {DOWNSTREAM_LIBRARY_CONTRACT_VERSION}"
        )
    return contract


def _tier_policy(contract: Mapping[str, Any], tier: str) -> dict[str, Any]:
    policies = contract.get("tier_policies")
    if not isinstance(policies, Mapping):
        raise RuntimeError("Downstream library contract missing tier_policies.")
    policy = policies.get(tier)
    if not isinstance(policy, Mapping):
        raise DownstreamLibraryContractError(f"Unknown library_tier: {tier}")
    return dict(policy)


def _require_nonempty_string(entry: Mapping[str, Any], field: str) -> None:
    _ensure(_as_text(entry.get(field)), f"Missing or empty required field: {field}")


def _require_list(entry: Mapping[str, Any], field: str) -> None:
    _ensure(isinstance(entry.get(field), list), f"Field must be a list: {field}")


def _require_mapping(entry: Mapping[str, Any], field: str) -> None:
    _ensure(isinstance(entry.get(field), Mapping), f"Field must be an object: {field}")


def _validate_required_fields(entry: Mapping[str, Any], required_fields: list[str]) -> None:
    for field in required_fields:
        _ensure(field in entry, f"Missing required field: {field}")


def validate_downstream_library_manifest(manifest: Mapping[str, Any]) -> None:
    _ensure(isinstance(manifest, Mapping), "Manifest must be an object.")
    _ensure(
        _as_text(manifest.get("assembly_mode")) == "full_provisional_library_assembly",
        "Manifest is not a full provisional library assembly manifest.",
    )
    _ensure(
        _as_text(manifest.get("source_scope")) == "full_current_machine_generated_corpus",
        "Manifest does not describe the full current machine-generated corpus.",
    )
    frozen_ref = manifest.get("frozen_reviewed_library_reference")
    _ensure(isinstance(frozen_ref, Mapping), "Manifest missing frozen_reviewed_library_reference.")
    _ensure(
        frozen_ref.get("modified_by_this_assembly") is False,
        "Frozen reviewed library must remain untouched for downstream provisional loading.",
    )
    outputs = manifest.get("outputs")
    _ensure(isinstance(outputs, Mapping), "Manifest missing outputs object.")
    for field in (
        "provisional_machine_pass_library_jsonl",
        "kc_review_sandbox_jsonl",
        "provisional_library_manifest_json",
    ):
        _ensure(_as_text(outputs.get(field)), f"Manifest missing outputs.{field}.")


def validate_downstream_kc_entry(
    entry: Mapping[str, Any],
    *,
    expected_tier: str | None = None,
    operational_use: bool = False,
) -> None:
    contract = load_downstream_library_contract()
    _ensure(isinstance(entry, Mapping), "Downstream KC entry must be an object.")

    required_common_fields = contract.get("required_common_fields")
    _ensure(isinstance(required_common_fields, list), "Contract missing required_common_fields.")
    _validate_required_fields(entry, [str(field) for field in required_common_fields])
    for field in ("library_tier", "review_status", "source_run_id", "kc_id"):
        _require_nonempty_string(entry, field)

    tier = _as_text(entry.get("library_tier"))
    allowed_tiers = contract.get("allowed_source_tiers")
    _ensure(isinstance(allowed_tiers, list), "Contract missing allowed_source_tiers.")
    _ensure(tier in {str(item) for item in allowed_tiers}, f"Unknown library_tier: {tier or '<missing>'}")

    if expected_tier and tier != expected_tier:
        raise DownstreamLibraryContractError(
            f"Expected library_tier={expected_tier}, but entry has library_tier={tier}."
        )

    policy = _tier_policy(contract, tier)
    required_fields = [str(field) for field in policy.get("required_fields") or []]
    _validate_required_fields(entry, required_fields)

    allowed_statuses = {str(item) for item in policy.get("allowed_review_statuses") or []}
    review_status = _as_text(entry.get("review_status"))
    _ensure(review_status in allowed_statuses, f"Invalid review_status={review_status} for library_tier={tier}.")

    if operational_use and policy.get("operational_load_allowed") is not True:
        raise DownstreamLibraryContractError(
            f"library_tier={tier} is not allowed for operational downstream loading."
        )

    if tier == "kc_review_sandbox" and operational_use:
        raise DownstreamLibraryContractError("Sandbox entries cannot be loaded as operational KC entries.")

    if tier == "provisional_machine_pass_library" and review_status in {"approved", "edited_approved"}:
        raise DownstreamLibraryContractError(
            "Provisional machine-pass entries must not claim a human-reviewed approval status."
        )

    if tier == "provisional_machine_pass_library":
        _ensure(
            _as_text(entry.get("status")) == "provisional_machine_pass",
            "Provisional machine-pass entries must carry status=provisional_machine_pass.",
        )
        for field in ("title", "level", "reviewer_facing_definition", "content_source_mode"):
            _require_nonempty_string(entry, field)
        _ensure(isinstance(entry.get("content_repair_reason"), str), "content_repair_reason must be a string.")
        for field in ("evidence_spans", "risk_flags", "integrity_repair_notes"):
            _require_list(entry, field)
        for field in (
            "source_provenance",
            "review_priority",
            "system_recommendation",
            "original_content_source",
            "review_content_source",
        ):
            _require_mapping(entry, field)
        _ensure(isinstance(entry.get("content_repair_applied"), bool), "content_repair_applied must be boolean.")

    if tier == "frozen_reviewed_library":
        for field in ("title", "level", "reviewer_facing_definition"):
            _require_nonempty_string(entry, field)
        _require_list(entry, "evidence_spans")
        _require_mapping(entry, "source_provenance")

    if tier == "kc_review_sandbox":
        _ensure(_as_text(entry.get("status")), "Sandbox entries must carry a non-empty status.")
        _require_mapping(entry, "reason")
        _require_mapping(entry, "source_provenance")


def _record_from_entry(entry: Mapping[str, Any]) -> DownstreamKCRecord:
    return DownstreamKCRecord(
        library_tier=_as_text(entry.get("library_tier")),
        review_status=_as_text(entry.get("review_status")),
        source_run_id=_as_text(entry.get("source_run_id")),
        kc_id=_as_text(entry.get("kc_id")),
        title=_as_text(entry.get("title")),
        level=_as_text(entry.get("level")),
        reviewer_facing_definition=_as_text(entry.get("reviewer_facing_definition")),
        evidence_spans=tuple(dict(span) for span in entry.get("evidence_spans") or []),
        source_provenance=dict(entry.get("source_provenance") or {}),
        risk_flags=tuple(str(flag) for flag in entry.get("risk_flags") or []),
        review_priority=dict(entry.get("review_priority") or {}) or None,
        system_recommendation=dict(entry.get("system_recommendation") or {}) or None,
        content_source_mode=_as_text(entry.get("content_source_mode")),
        content_repair_applied=bool(entry.get("content_repair_applied")),
        content_repair_reason=_as_text(entry.get("content_repair_reason")),
        original_content_source=dict(entry.get("original_content_source") or {}) or None,
        review_content_source=dict(entry.get("review_content_source") or {}) or None,
        integrity_repair_notes=tuple(str(note) for note in entry.get("integrity_repair_notes") or []),
        status=_as_text(entry.get("status")),
    )


def load_operational_kc_library(path: str | Path, *, expected_tier: str) -> list[DownstreamKCRecord]:
    resolved_path = _resolve_repo_path(path)
    rows = read_jsonl(resolved_path)
    records: list[DownstreamKCRecord] = []
    for index, row in enumerate(rows):
        try:
            validate_downstream_kc_entry(row, expected_tier=expected_tier, operational_use=True)
        except DownstreamLibraryContractError as exc:
            raise DownstreamLibraryContractError(f"Invalid downstream KC entry at {resolved_path} row {index + 1}: {exc}") from exc
        records.append(_record_from_entry(row))
    return records


def load_provisional_machine_pass_library(path: str | Path) -> list[DownstreamKCRecord]:
    return load_operational_kc_library(path, expected_tier="provisional_machine_pass_library")


def load_full_provisional_machine_pass_library_from_manifest(manifest_path: str | Path) -> FullProvisionalLibraryPackage:
    resolved_manifest_path = _resolve_repo_path(manifest_path)
    manifest = read_json(resolved_manifest_path)
    validate_downstream_library_manifest(manifest)

    outputs = dict(manifest.get("outputs") or {})
    provisional_library_path = _resolve_repo_path(outputs["provisional_machine_pass_library_jsonl"])
    sandbox_path = _resolve_repo_path(outputs["kc_review_sandbox_jsonl"])

    entries = tuple(load_provisional_machine_pass_library(provisional_library_path))
    return FullProvisionalLibraryPackage(
        manifest_path=resolved_manifest_path,
        manifest=dict(manifest),
        provisional_library_path=provisional_library_path,
        sandbox_path=sandbox_path,
        entries=entries,
    )


