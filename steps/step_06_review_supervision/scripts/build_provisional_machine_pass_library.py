from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


BOUNDARY_NOTE = (
    "The frozen Step 6 library reference remains unchanged. "
    "This assembly creates a provisional machine-pass library and a sandbox only from current review-packet outputs."
)
PROVISIONAL_WARNING = (
    "The provisional machine-pass library is machine-pass only for operational progress and downstream experimentation. "
    "It is not a reviewed final library and does not prove human approval."
)
SANDBOX_WARNING = (
    "The sandbox contains reject-recommended and skipped-before-review cases so they remain separated from the provisional machine-pass tier."
)
REDUCED_SUPERVISION_WARNING = (
    "This source run does not carry the richer main-quest supervision sidecars, so review packets were emitted in reduced-supervision mode with conservative missing-feature handling."
)


ACTIVE_STEP6_POINTER = Path("data/processed/kc_library/_sets/ACTIVE_STEP6_KC_LIBRARY_SET.txt")

PROOF_RUN_OUTPUTS = {
    "provisional": "provisional_machine_pass_library.jsonl",
    "sandbox": "kc_review_sandbox.jsonl",
    "manifest": "provisional_library_manifest.json",
}
FULL_CORPUS_OUTPUTS = {
    "provisional": "full_provisional_machine_pass_library.jsonl",
    "sandbox": "full_kc_review_sandbox.jsonl",
    "manifest": "full_provisional_library_manifest.json",
}


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _relative_repo_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def _read_active_pointer_target(pointer_path: Path) -> str:
    return pointer_path.read_text(encoding="utf-8").strip()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _load_source_record_lookup(source_processed_dir: Path) -> dict[str, dict[str, Any]]:
    source_path = source_processed_dir / "kc_library.jsonl"
    if not source_path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(source_path):
        kc_id = _as_text(row.get("kc_id"))
        if kc_id:
            out[kc_id] = row
    return out


def _source_run_id(packet: dict[str, Any], summary: dict[str, Any]) -> str:
    provenance = packet.get("source_provenance") or {}
    run_id = _as_text(provenance.get("generation_run_id"))
    if run_id:
        return run_id
    return _as_text(summary.get("source_run_id"))


def _packet_review_status(packet: dict[str, Any]) -> str:
    packet_state = _as_text(packet.get("packet_state"))
    return packet_state or "review_ready"


def _build_provisional_entry(packet: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "status": "provisional_machine_pass",
        "library_tier": "provisional_machine_pass_library",
        "review_status": _packet_review_status(packet),
        "source_run_id": _source_run_id(packet, summary),
        "source_kind": "review_packet",
        "review_packet_id": packet["review_packet_id"],
        "kc_id": packet["kc_candidate_id"],
        "title": packet["title_draft"],
        "level": packet["level_draft"],
        "reviewer_facing_definition": packet["definition_draft"],
        "evidence_spans": packet["evidence_spans"],
        "evidence_coverage_summary": packet["evidence_coverage_summary"],
        "source_provenance": packet["source_provenance"],
        "risk_flags": list(packet.get("risk_flags") or []),
        "review_priority": dict(packet["review_priority"]),
        "system_recommendation": dict(packet["system_recommendation"]),
        "content_source_mode": packet["content_source_mode"],
        "content_repair_applied": bool(packet.get("content_repair_applied")),
        "content_repair_reason": packet.get("content_repair_reason", ""),
        "original_content_source": dict(packet.get("original_content_source") or {}),
        "review_content_source": dict(packet.get("review_content_source") or {}),
        "integrity_repair_notes": list(packet.get("integrity_repair_notes") or []),
    }
    if "debug_original_content" in packet:
        entry["debug_original_content"] = dict(packet["debug_original_content"])
    return entry


def _build_reject_sandbox_entry(packet: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "reject_recommended",
        "library_tier": "kc_review_sandbox",
        "review_status": _packet_review_status(packet),
        "source_run_id": _source_run_id(packet, summary),
        "source_kind": "review_packet",
        "review_packet_id": packet["review_packet_id"],
        "kc_id": packet["kc_candidate_id"],
        "title": packet["title_draft"],
        "reason": {
            "system_recommendation_label": packet["system_recommendation"]["label"],
            "system_recommendation_reason_codes": list(packet["system_recommendation"].get("reason_codes") or []),
            "review_priority_bucket": packet["review_priority"]["bucket"],
            "review_priority_reason_codes": list(packet["review_priority"].get("reason_codes") or []),
        },
        "evidence_spans": packet["evidence_spans"],
        "source_provenance": packet["source_provenance"],
        "risk_flags": list(packet.get("risk_flags") or []),
        "content_source_mode": packet["content_source_mode"],
        "content_repair_applied": bool(packet.get("content_repair_applied")),
        "content_repair_reason": packet.get("content_repair_reason", ""),
        "integrity_repair_notes": list(packet.get("integrity_repair_notes") or []),
        "review_priority": dict(packet["review_priority"]),
        "system_recommendation": dict(packet["system_recommendation"]),
    }


def _build_skipped_sandbox_entry_from_workflow(
    *,
    skipped_case: dict[str, Any],
    skipped_reason_lookup: dict[str, list[str]],
    source_processed_dir: Path,
    review_packet_dir: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    kc_id = _as_text(skipped_case.get("kc_candidate_id"))
    risk_flags = ["skipped_before_review"]
    if bool(skipped_case.get("requires_raw_internals")):
        risk_flags.append("requires_raw_internals")
    return {
        "status": "skipped",
        "library_tier": "kc_review_sandbox",
        "review_status": "skipped_before_review",
        "source_run_id": _as_text(summary.get("source_run_id")),
        "source_kind": "skipped_case_assessment",
        "kc_id": kc_id,
        "title": _as_text(skipped_case.get("title_draft")),
        "reason": {
            "pre_review_disposition": _as_text(skipped_case.get("pre_review_disposition")),
            "skip_assessment": _as_text(skipped_case.get("skip_assessment")),
            "verdict_rationale": _as_text(skipped_case.get("verdict_rationale")),
            "summary_skip_reasons": list(skipped_reason_lookup.get(kc_id) or []),
            "key_findings": list(skipped_case.get("key_findings") or []),
        },
        "evidence_spans": [],
        "source_provenance": {
            "source_review_packet_dir": _relative_repo_path(review_packet_dir),
            "source_processed_dir": _relative_repo_path(source_processed_dir),
        },
        "risk_flags": risk_flags,
        "content_source_mode": "",
        "content_repair_applied": False,
        "content_repair_reason": "",
        "integrity_repair_notes": [],
    }


def _build_skipped_sandbox_entry_from_summary(
    *,
    skipped_item: dict[str, Any],
    source_record_lookup: dict[str, dict[str, Any]],
    source_processed_dir: Path,
    review_packet_dir: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    kc_id = _as_text(skipped_item.get("kc_candidate_id"))
    source_record = source_record_lookup.get(kc_id, {})
    evidence_spans = list(source_record.get("evidence_minimal") or [])
    source_document_ids: list[str] = []
    for span in evidence_spans:
        doc_id = _as_text((span or {}).get("doc_id"))
        if doc_id and doc_id not in source_document_ids:
            source_document_ids.append(doc_id)
    return {
        "status": "skipped",
        "library_tier": "kc_review_sandbox",
        "review_status": "skipped_before_review",
        "source_run_id": _as_text(summary.get("source_run_id")),
        "source_kind": "review_packet_skip_summary",
        "kc_id": kc_id,
        "title": _as_text(source_record.get("canonical_name")),
        "reason": {
            "summary_skip_reasons": [str(reason) for reason in skipped_item.get("reasons") or []],
            "skip_category": "skipped_before_review",
        },
        "evidence_spans": evidence_spans,
        "source_provenance": {
            "source_review_packet_dir": _relative_repo_path(review_packet_dir),
            "source_processed_dir": _relative_repo_path(source_processed_dir),
            "source_set_ids": dict(source_record.get("source_set_ids") or {}),
            "source_document_ids": source_document_ids,
        },
        "risk_flags": ["skipped_before_review"],
        "content_source_mode": "",
        "content_repair_applied": False,
        "content_repair_reason": "",
        "integrity_repair_notes": [],
    }


def _skipped_reason_lookup(summary: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in summary.get("skipped_candidates") or []:
        kc_id = _as_text(item.get("kc_candidate_id"))
        if not kc_id:
            continue
        out[kc_id] = [str(reason) for reason in item.get("reasons") or []]
    return out


def _source_supervision_surface(source_processed_dir: Path) -> dict[str, Any]:
    trace_dir = source_processed_dir / "enrichment_traces"
    extraction_trace_dir = source_processed_dir / "extraction_traces"
    return {
        "has_definition_short_contract_audit": (source_processed_dir / "definition_short_contract_audit.jsonl").exists(),
        "has_tier2_recovery_queue": (source_processed_dir / "tier2_recovery_queue.jsonl").exists(),
        "has_enrichment_traces": trace_dir.exists(),
        "enrichment_trace_count": len(list(trace_dir.glob("*.json"))) if trace_dir.exists() else 0,
        "has_extraction_traces": extraction_trace_dir.exists(),
        "extraction_trace_count": len(list(extraction_trace_dir.glob("*.json"))) if extraction_trace_dir.exists() else 0,
    }


def _assemble_library_package(
    *,
    review_packet_dir: Path,
    output_names: dict[str, str],
    source_scope: str,
    require_human_session_context: bool,
) -> tuple[Path, Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    review_packet_path = review_packet_dir / "review_packet.jsonl"
    summary_path = review_packet_dir / "review_packet_summary.json"
    workflow_path = review_packet_dir / "human_supervised_draft_actions.json"
    session_manifest_path = review_packet_dir / "real_reviewer_session_manifest.json"

    required = [review_packet_path, summary_path]
    if require_human_session_context:
        required.extend([workflow_path, session_manifest_path])
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required review-packet artifacts missing: {missing}")

    packets = read_jsonl(review_packet_path)
    summary = read_json(summary_path)
    source_processed_dir = Path(summary["source_processed_dir"]).resolve()
    source_record_lookup = _load_source_record_lookup(source_processed_dir)
    skipped_reason_lookup = _skipped_reason_lookup(summary)

    workflow = read_json(workflow_path) if workflow_path.exists() else {}
    session_manifest = read_json(session_manifest_path) if session_manifest_path.exists() else {}
    skipped_case = dict(workflow.get("skipped_case") or {})

    provisional_entries: list[dict[str, Any]] = []
    sandbox_entries: list[dict[str, Any]] = []
    unresolved_or_unusable_count = 0

    for packet in packets:
        recommendation = _as_text(((packet.get("system_recommendation") or {}).get("label")))
        packet_state = _as_text(packet.get("packet_state"))
        risk_flags = [str(flag) for flag in packet.get("risk_flags") or []]
        explicit_unresolved = packet_state in {"rejected"} or any(
            ("unresolved" in flag.lower()) or ("unusable" in flag.lower()) for flag in risk_flags
        )

        if recommendation == "reject_recommended":
            sandbox_entries.append(_build_reject_sandbox_entry(packet, summary))
            continue
        if explicit_unresolved:
            unresolved_or_unusable_count += 1
            sandbox_entries.append(_build_reject_sandbox_entry(packet, summary))
            continue
        provisional_entries.append(_build_provisional_entry(packet, summary))

    if skipped_case:
        sandbox_entries.append(
            _build_skipped_sandbox_entry_from_workflow(
                skipped_case=skipped_case,
                skipped_reason_lookup=skipped_reason_lookup,
                source_processed_dir=source_processed_dir,
                review_packet_dir=review_packet_dir,
                summary=summary,
            )
        )
    else:
        for skipped_item in summary.get("skipped_candidates") or []:
            sandbox_entries.append(
                _build_skipped_sandbox_entry_from_summary(
                    skipped_item=dict(skipped_item),
                    source_record_lookup=source_record_lookup,
                    source_processed_dir=source_processed_dir,
                    review_packet_dir=review_packet_dir,
                    summary=summary,
                )
            )

    provisional_path = review_packet_dir / output_names["provisional"]
    sandbox_path = review_packet_dir / output_names["sandbox"]
    manifest_path = review_packet_dir / output_names["manifest"]

    write_jsonl(provisional_path, provisional_entries)
    write_jsonl(sandbox_path, sandbox_entries)

    active_pointer_target = _read_active_pointer_target(REPO_ROOT / ACTIVE_STEP6_POINTER)
    active_pointer_target_path = (REPO_ROOT / ACTIVE_STEP6_POINTER.parent / active_pointer_target).resolve()
    supervision_surface = _source_supervision_surface(source_processed_dir)
    warnings = [
        PROVISIONAL_WARNING,
        SANDBOX_WARNING,
        "This assembly does not change ACTIVE pointers and does not promote any machine-pass entry into the frozen Step 6 baseline.",
    ]
    if source_scope == "full_current_machine_generated_corpus" and not supervision_surface["has_definition_short_contract_audit"]:
        warnings.append(REDUCED_SUPERVISION_WARNING)

    manifest = {
        "assembly_mode": (
            "full_provisional_library_assembly"
            if source_scope == "full_current_machine_generated_corpus"
            else "provisional_machine_pass_library_assembly"
        ),
        "source_scope": source_scope,
        "boundary_note": BOUNDARY_NOTE,
        "warnings": warnings,
        "frozen_reviewed_library_reference": {
            "active_step6_pointer": _relative_repo_path(REPO_ROOT / ACTIVE_STEP6_POINTER),
            "resolved_active_step6_target": _relative_repo_path(active_pointer_target_path),
            "unchanged": True,
            "modified_by_this_assembly": False,
        },
        "tier_semantics": {
            "frozen_reviewed_library": "Unchanged reference tier. This assembly does not modify or promote it.",
            "provisional_machine_pass_library": "All emitted review packets except reject-recommended packets and skipped-before-review cases. Machine-pass only, not human-approved.",
            "kc_review_sandbox": "Reject-recommended packets, skipped-before-review cases, and any explicit unresolved or unusable outputs if such status appears.",
        },
        "source_review_packet_dir": _relative_repo_path(review_packet_dir),
        "source_processed_dir": _relative_repo_path(source_processed_dir),
        "source_run_id": _as_text(summary.get("source_run_id")),
        "source_packet_summary": {
            "packet_count": int(summary.get("packet_count") or 0),
            "skipped_candidate_count": int(summary.get("skipped_candidate_count") or 0),
            "system_recommendation_counts": dict(summary.get("system_recommendation_counts") or {}),
            "priority_bucket_counts": dict(summary.get("priority_bucket_counts") or {}),
            "missing_current_feature_counts": dict(summary.get("missing_current_feature_counts") or {}),
        },
        "source_supervision_surface": supervision_surface,
        "source_artifacts": {
            "review_packet_jsonl": _relative_repo_path(review_packet_path),
            "review_packet_summary_json": _relative_repo_path(summary_path),
            "review_packet_preview_md": _relative_repo_path(review_packet_dir / "review_packet_preview.md"),
        },
        "outputs": {
            "provisional_machine_pass_library_jsonl": _relative_repo_path(provisional_path),
            "kc_review_sandbox_jsonl": _relative_repo_path(sandbox_path),
            "provisional_library_manifest_json": _relative_repo_path(manifest_path),
        },
        "counts": {
            "source_review_packet_count": len(packets),
            "provisional_machine_pass_library_count": len(provisional_entries),
            "sandbox_total_count": len(sandbox_entries),
            "sandbox_reject_recommended_count": sum(
                1 for entry in sandbox_entries if entry.get("status") == "reject_recommended"
            ),
            "sandbox_skipped_count": sum(1 for entry in sandbox_entries if entry.get("status") == "skipped"),
            "sandbox_unresolved_or_unusable_count": unresolved_or_unusable_count,
        },
    }
    if session_manifest:
        manifest["source_artifacts"].update(
            {
                "manual_inspection_bundle_md": _relative_repo_path(review_packet_dir / "manual_inspection_bundle.md"),
                "real_reviewer_session_md": _relative_repo_path(review_packet_dir / "real_reviewer_session.md"),
                "real_reviewer_session_manifest_json": _relative_repo_path(session_manifest_path),
                "human_supervised_draft_actions_json": _relative_repo_path(workflow_path),
            }
        )
        manifest["session_context"] = {
            "reviewer_session_mode": _as_text(session_manifest.get("session_mode")),
            "success_threshold": _as_text(session_manifest.get("success_threshold")),
            "approve_path_required": bool(session_manifest.get("approve_path_required")),
        }

    write_json(manifest_path, manifest)
    return provisional_path, sandbox_path, manifest_path


def build_provisional_machine_pass_library(review_packet_dir: Path) -> tuple[Path, Path, Path]:
    return _assemble_library_package(
        review_packet_dir=review_packet_dir,
        output_names=PROOF_RUN_OUTPUTS,
        source_scope="proof_run_review_packet_slice",
        require_human_session_context=True,
    )


def build_full_provisional_machine_pass_library(review_packet_dir: Path) -> tuple[Path, Path, Path]:
    return _assemble_library_package(
        review_packet_dir=review_packet_dir,
        output_names=FULL_CORPUS_OUTPUTS,
        source_scope="full_current_machine_generated_corpus",
        require_human_session_context=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble provisional machine-pass and sandbox tiers from one review-packet directory."
    )
    parser.add_argument("--review-packet-dir", required=True, help="Repo-relative or absolute review-packet directory.")
    parser.add_argument(
        "--assembly-scope",
        choices=("proof_run", "full_corpus"),
        default="proof_run",
        help="Use proof_run for the existing reviewed proof slice or full_corpus for generic full-source assembly.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)
    if args.assembly_scope == "full_corpus":
        provisional_path, sandbox_path, manifest_path = build_full_provisional_machine_pass_library(review_packet_dir)
    else:
        provisional_path, sandbox_path, manifest_path = build_provisional_machine_pass_library(review_packet_dir)
    print(f"Provisional machine-pass library: {provisional_path}")
    print(f"KC review sandbox: {sandbox_path}")
    print(f"Provisional library manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
