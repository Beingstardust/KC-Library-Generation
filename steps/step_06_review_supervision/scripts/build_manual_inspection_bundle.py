from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc.review_packets import (
    TRACE_DEFINITION_REFINEMENT_EXTRACTION_METHOD,
    TRACE_FALLBACK_EXTRACTION_METHOD,
    TRACE_SELECTED_REPAIR_EXTRACTION_METHOD,
)
from kc_l.utils.json_io import read_json, read_jsonl, write_json


REVIEWER_CHECKLIST = [
    "Is the title appropriately scoped?",
    "Is the definition sufficiently clear and specific?",
    "Do the evidence spans genuinely support the KC?",
    "Is the recommendation sensible?",
    "Would an expert be able to Approve, Edit, or Reject from this packet without digging through raw internals?",
    "Is any important evidence missing from the packet?",
    "Is trace-fallback evidence acceptable here?",
]


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _load_lookup(path: Path, key: str = "kc_id") -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        row_key = str(row.get(key) or "").strip()
        if row_key:
            out[row_key] = row
    return out


def _load_trace_lookup(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in sorted(path.glob("*.json")):
        payload = read_json(item)
        kc_id = str(payload.get("kc_id") or item.stem).strip()
        if kc_id:
            out[kc_id] = payload
    return out


def _excerpt(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys if key in source}


def _packet_has_provenance_adjustment(packet: dict[str, Any], trace: dict[str, Any]) -> bool:
    for span in packet.get("evidence_spans") or []:
        flags = {str(item) for item in span.get("provenance_quality_flags") or []}
        if "PageIndexSubstituted" in flags or "PageIndexDropped" in flags:
            return True
    provenance = dict(trace.get("provenance_normalization") or trace.get("provenance_normalization_excerpt") or {})
    return any(int(provenance.get(key) or 0) > 0 for key in ("page_index_substituted_count", "page_index_dropped_count"))


def _select_packets(packets: list[dict[str, Any]], trace_lookup: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    selections: list[dict[str, str]] = []
    selected_ids: set[str] = set()

    non_approve = [packet for packet in packets if packet["system_recommendation"]["label"] != "approve_ready"]
    for packet in non_approve:
        label = packet["system_recommendation"]["label"]
        if label == "reject_recommended":
            reason = "All reject_recommended packets must be included."
        else:
            reason = "All review_needed packets must be included."
        selections.append(
            {
                "kc_candidate_id": packet["kc_candidate_id"],
                "selection_role": "non_approve_required",
                "selection_reason": reason,
            }
        )
        selected_ids.add(packet["kc_candidate_id"])

    approve_packets = [packet for packet in packets if packet["system_recommendation"]["label"] == "approve_ready"]

    strongest = sorted(
        approve_packets,
        key=lambda packet: (
            packet["evidence_coverage_summary"].get("operational_support_present") is True,
            not packet.get("risk_flags"),
            packet["review_priority"]["rank_score"],
            packet["evidence_coverage_summary"]["evidence_span_count"],
            packet["kc_candidate_id"],
        ),
        reverse=True,
    )
    for packet in strongest:
        kc_id = packet["kc_candidate_id"]
        if kc_id in selected_ids:
            continue
        selections.append(
            {
                "kc_candidate_id": kc_id,
                "selection_role": "approve_ready_control",
                "selection_reason": "Strongest-looking remaining approve-ready packet after integrity gating: highest surviving support footprint with the cleanest packet surface.",
            }
        )
        selected_ids.add(kc_id)
        break

    borderline = sorted(
        approve_packets,
        key=lambda packet: (
            packet["evidence_coverage_summary"]["evidence_span_count"],
            packet["evidence_coverage_summary"].get("operational_support_present") is True,
            packet["review_priority"]["rank_score"],
            packet["kc_candidate_id"],
        ),
    )
    for packet in borderline:
        kc_id = packet["kc_candidate_id"]
        if kc_id in selected_ids:
            continue
        selections.append(
            {
                "kc_candidate_id": kc_id,
                "selection_role": "approve_ready_control",
                "selection_reason": "Borderline remaining approve-ready control after integrity gating: smallest surviving evidence footprint among approve-ready packets.",
            }
        )
        selected_ids.add(kc_id)
        break

    varied = sorted(
        approve_packets,
        key=lambda packet: (
            _packet_has_provenance_adjustment(packet, trace_lookup.get(packet["kc_candidate_id"], {})),
            len({span.get("role") for span in packet.get("evidence_spans") or []}),
            len(packet["source_provenance"].get("source_document_ids") or []),
            packet["evidence_coverage_summary"]["evidence_span_count"],
            packet["kc_candidate_id"],
        ),
        reverse=True,
    )
    for packet in varied:
        kc_id = packet["kc_candidate_id"]
        if kc_id in selected_ids:
            continue
        selections.append(
            {
                "kc_candidate_id": kc_id,
                "selection_role": "approve_ready_control",
                "selection_reason": "Different evidence-characteristics control after integrity gating: chosen to broaden the approve-ready sample beyond the strongest and thinnest cases.",
            }
        )
        selected_ids.add(kc_id)
        break

    return selections


def _json_block(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_manual_inspection_bundle(review_packet_dir: Path) -> tuple[Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    packet_path = review_packet_dir / "review_packet.jsonl"
    summary_path = review_packet_dir / "review_packet_summary.json"
    if not packet_path.exists() or not summary_path.exists():
        raise FileNotFoundError(f"Review packet artifacts missing under {review_packet_dir}")

    packets = read_jsonl(packet_path)
    summary = read_json(summary_path)
    source_dir = Path(summary["source_processed_dir"]).resolve()

    kc_lookup = _load_lookup(source_dir / "kc_library.jsonl")
    short_audit_lookup = _load_lookup(source_dir / "definition_short_contract_audit.jsonl")
    tier2_lookup = _load_lookup(source_dir / "tier2_recovery_queue.jsonl")
    trace_lookup = _load_trace_lookup(source_dir / "enrichment_traces")

    selections = _select_packets(packets, trace_lookup)
    selection_lookup = {item["kc_candidate_id"]: item for item in selections}

    selection_json_path = review_packet_dir / "inspection_packet_selection.json"
    write_json(
        selection_json_path,
        {
            "review_packet_dir": str(review_packet_dir),
            "source_processed_dir": str(source_dir),
            "selected_packets": selections,
        },
    )

    ordered_packets = [
        packet
        for packet in packets
        if packet["kc_candidate_id"] in selection_lookup
    ]
    ordered_packets.sort(key=lambda packet: list(selection_lookup).index(packet["kc_candidate_id"]))

    lines = [
        "# Manual Inspection Bundle",
        "",
        f"- Proof-run packet directory: `{review_packet_dir.relative_to(REPO_ROOT)}`",
        f"- Source processed directory: `{source_dir.relative_to(REPO_ROOT)}`",
        "- Bundle purpose: manual packet-sufficiency inspection before any expert-action or audit-write flow.",
        "- Included packets: all current non-approve packets plus up to 3 deliberate approve-ready controls after integrity gating.",
        f"- Proof-run aggregate counts: `{ {'packet_count': summary['packet_count'], 'priority_bucket_counts': summary['priority_bucket_counts'], 'system_recommendation_counts': summary['system_recommendation_counts'], 'integrity_capped_packet_count': summary.get('integrity_capped_packet_count', 0), 'content_repaired_packet_count': summary.get('content_repaired_packet_count', 0), 'remaining_incoherent_packet_count': summary.get('remaining_incoherent_packet_count', 0), 'skipped_candidate_count': summary.get('skipped_candidate_count', 0)} }`",
        "",
        "## Selection Set",
        "",
    ]

    for item in selections:
        packet = next(packet for packet in packets if packet["kc_candidate_id"] == item["kc_candidate_id"])
        lines.append(
            f"- `{item['kc_candidate_id']}`: `{packet['review_priority']['bucket']}` / `{packet['system_recommendation']['label']}`. {item['selection_reason']}"
        )

    for packet in ordered_packets:
        kc_id = packet["kc_candidate_id"]
        selection = selection_lookup[kc_id]
        kc_row = kc_lookup.get(kc_id, {})
        short_audit = short_audit_lookup.get(kc_id, {})
        tier2_row = tier2_lookup.get(kc_id, {})
        trace = trace_lookup.get(kc_id, {})
        coverage = packet["evidence_coverage_summary"]

        lines.extend(
            [
                "",
                f"## {kc_id}",
                "",
                f"- Selection role: `{selection['selection_role']}`",
                f"- Selection reason: {selection['selection_reason']}",
                "",
                "### Packet Header",
                "",
                f"- Review packet id: `{packet['review_packet_id']}`",
                f"- Title draft: `{packet['title_draft']}`",
                f"- Definition draft: `{packet['definition_draft']}`",
                f"- Review priority: `{packet['review_priority']['bucket']}` / `{packet['review_priority']['display_label']}` / rank `{packet['review_priority']['rank_score']}`",
                f"- System recommendation: `{packet['system_recommendation']['label']}`",
                f"- Content source mode: `{packet.get('content_source_mode', '')}`",
                f"- Content repair applied: `{packet.get('content_repair_applied', False)}`",
                f"- Content repair reason: `{packet.get('content_repair_reason', '')}`",
                f"- Original content source: `{packet.get('original_content_source', {})}`",
                f"- Review content source: `{packet.get('review_content_source', {})}`",
                f"- Integrity repair notes: `{packet.get('integrity_repair_notes', [])}`",
                f"- Priority reason codes: `{packet['review_priority']['reason_codes']}`",
                f"- Recommendation reason codes: `{packet['system_recommendation']['reason_codes']}`",
                f"- Risk flags: `{packet['risk_flags']}`",
                f"- Coverage summary: `{coverage}`",
                "",
                "### Evidence View",
                "",
            ]
        )

        if packet.get("debug_original_content"):
            debug_original = packet["debug_original_content"]
            debug_excerpt = {
                "definition_draft": debug_original.get("definition_draft"),
                "evidence_span_count": len(debug_original.get("evidence_spans") or []),
                "evidence_doc_ids": sorted({span.get("doc_id") for span in debug_original.get("evidence_spans") or [] if span.get("doc_id")}),
                "first_evidence_quotes": [span.get("quote") for span in (debug_original.get("evidence_spans") or [])[:2]],
            }
            lines.extend(["### Repair Debug Metadata", "", f"```json\n{_json_block(debug_excerpt)}\n```", ""])

        for index, span in enumerate(packet.get("evidence_spans") or [], start=1):
            if span.get("extraction_method") == TRACE_SELECTED_REPAIR_EXTRACTION_METHOD:
                origin = "trace-selected repair"
            elif span.get("extraction_method") == TRACE_DEFINITION_REFINEMENT_EXTRACTION_METHOD:
                origin = "trace definition refinement"
            elif span.get("extraction_method") == TRACE_FALLBACK_EXTRACTION_METHOD:
                origin = "trace fallback"
            else:
                origin = "primary evidence"
            lines.extend(
                [
                    f"#### Span {index}",
                    "",
                    f"- Origin: `{origin}`",
                    f"- Evidence id: `{span['evidence_id']}`",
                    f"- Provenance: doc `{span['doc_id']}`, block `{span['block_id']}`, page `{span['page_index']}`, layer `{span['layer']}`",
                    f"- Role: `{span['role']}`",
                    f"- Quote verified: `{span['quote_verified']}`",
                    f"- Extraction method: `{span.get('extraction_method', '')}`",
                    f"- Provenance quality flags: `{span.get('provenance_quality_flags', [])}`",
                    f"- Quote: `{span['quote']}`",
                    "",
                ]
            )

        kc_excerpt = {
            "kc_id": kc_row.get("kc_id"),
            "canonical_name": kc_row.get("canonical_name"),
            "definition_short": kc_row.get("definition_short"),
            "definition_full": kc_row.get("definition_full"),
            "procedure_steps": kc_row.get("procedure_steps"),
            "worked_examples": kc_row.get("worked_examples"),
            "evidence_minimal_count": len(kc_row.get("evidence_minimal") or []),
            "quality_flags_excerpt": list(kc_row.get("quality_flags") or [])[:12],
        }
        short_excerpt = _excerpt(
            short_audit,
            [
                "semantic_tier",
                "definition_status",
                "definition_short_source_type",
                "definition_short_contract_ok",
                "tier1",
                "usable_curriculum",
            ],
        )
        tier2_excerpt = _excerpt(
            tier2_row,
            [
                "semantic_tier",
                "definition_status",
                "accepted_quote_count",
                "support_contract_downgraded",
                "support_contract_downgrade_reason",
                "contamination_category",
                "sibling_ambiguity",
                "reasons",
            ],
        )
        trace_excerpt = {
            "semantic_tier": trace.get("semantic_tier"),
            "definition_status": trace.get("definition_status"),
            "semantic_tier_reasons": trace.get("semantic_tier_reasons", []),
            "support_contract_excerpt": _excerpt(
                trace.get("support_contract") or {},
                [
                    "target_support_state",
                    "bundle_strict_leaf_support",
                    "bundle_family_topic_support",
                    "bundle_parent_topic_overlap",
                    "generic_selected_support",
                    "permissive_rescue_lineage",
                    "preserved_from_step63",
                    "support_contract_downgraded",
                    "support_contract_downgrade_reason",
                ],
            ),
            "contamination_excerpt": _excerpt(
                trace.get("contamination_summary") or {},
                [
                    "category",
                    "target_support_state",
                    "sibling_ambiguous_support",
                    "competitor_kc_ids",
                    "support_contract_downgraded",
                    "support_contract_downgrade_reason",
                ],
            ),
            "provenance_normalization_excerpt": _excerpt(
                trace.get("provenance_normalization") or trace.get("provenance_normalization_excerpt") or {},
                [
                    "page_index_recovered_count",
                    "page_index_substituted_count",
                    "page_index_dropped_count",
                    "quote_rebound_count",
                    "quote_rebind_failed_count",
                    "dropped_candidate_ids",
                ],
            ),
        }

        lines.extend(
            [
                "### Source Cross-Check",
                "",
                "`kc_library.jsonl` excerpt",
                "```json",
                _json_block(kc_excerpt),
                "```",
                "",
                "`definition_short_contract_audit.jsonl` excerpt",
                "```json",
                _json_block(short_excerpt),
                "```",
                "",
                "`tier2_recovery_queue.jsonl` excerpt",
            ]
        )
        if tier2_excerpt:
            lines.extend(["```json", _json_block(tier2_excerpt), "```", ""])
        else:
            lines.extend(["No tier2 recovery entry for this packet.", ""])

        lines.extend(
            [
                f"`enrichment_traces/{kc_id}.json` excerpt",
                "```json",
                _json_block(trace_excerpt),
                "```",
                "",
                "### Reviewer Checklist",
                "",
            ]
        )
        for item in REVIEWER_CHECKLIST:
            lines.append(f"- [ ] {item}")
        lines.extend(
            [
                "",
                "### Reviewer Placeholder",
                "",
                "- Reviewer decision: `_____` (`approve` / `edit` / `reject`)",
                "- Reviewer note: `_____`",
            ]
        )

    bundle_path = review_packet_dir / "manual_inspection_bundle.md"
    bundle_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return bundle_path, selection_json_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a manual inspection bundle for one emitted review-packet proof run.")
    parser.add_argument("--review-packet-dir", required=True, help="Repo-relative or absolute emitted review-packet directory.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_packet_dir = _resolve_repo_path(args.review_packet_dir)
    bundle_path, selection_path = build_manual_inspection_bundle(review_packet_dir)
    print(f"Manual inspection bundle: {bundle_path}")
    print(f"Inspection selection JSON: {selection_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
