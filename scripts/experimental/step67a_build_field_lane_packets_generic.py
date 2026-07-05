from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.kc_drafting.evidence_lane_policy import (  # noqa: E402
    EvidenceLanePolicy,
    build_lane_packet,
    summarize_lane_packet,
    summarize_lane_packets,
)


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _overlay_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        overlay_candidate_id = str(row.get("overlay_candidate_id") or "")
        if overlay_candidate_id:
            indexed[overlay_candidate_id] = row
    return indexed


def _filter_packets(
    packets: list[dict[str, Any]],
    *,
    limit_kcs: int | None,
    exact_kc_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if exact_kc_ids:
        wanted = [str(item) for item in exact_kc_ids]
        packet_by_id = {str(packet.get("kc_id") or ""): packet for packet in packets}
        missing = [kc_id for kc_id in wanted if kc_id not in packet_by_id]
        if missing:
            raise RuntimeError(f"Unknown kc_id values requested: {missing}")
        selected = [packet_by_id[kc_id] for kc_id in wanted]
    else:
        selected = list(packets)

    if limit_kcs is None:
        return selected
    return selected[: max(0, int(limit_kcs))]


def _lane_audit_markdown(
    lane_packets: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    packets_path: Path,
    overlay_path: Path | None,
    output_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 Generic Lane Policy Audit")
    lines.append("")
    lines.append(f"- packets: `{packets_path.as_posix()}`")
    lines.append(f"- overlay: `{overlay_path.as_posix() if overlay_path else ''}`")
    lines.append(f"- output_dir: `{output_dir.as_posix()}`")
    lines.append(f"- packet_count: `{summary.get('packet_count')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(summary, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    lines.append("## Packets")
    lines.append("")

    for lane_packet in lane_packets:
        packet_summary = summarize_lane_packet(lane_packet)
        lines.append(
            f"### {lane_packet.get('kc_id') or ''} | {lane_packet.get('canonical_name') or ''}"
        )
        lines.append("")
        lines.append(f"- lane_pattern: `{packet_summary.get('lane_pattern')}`")
        lines.append(
            f"- selected_counts: `{json.dumps(packet_summary.get('selected_lane_counts') or {}, ensure_ascii=False, sort_keys=True)}`"
        )
        lines.append(
            f"- all_item_lane_counts: `{json.dumps(packet_summary.get('all_item_lane_counts') or {}, ensure_ascii=False, sort_keys=True)}`"
        )
        lines.append("")

        for lane_name in ("definition_lane", "scope_lane", "context_lane", "sibling_contrast_lane", "quarantine_lane"):
            lane_items = [item for item in (lane_packet.get(lane_name) or []) if isinstance(item, dict)]
            if not lane_items:
                continue
            lines.append(f"- {lane_name}:")
            for item in lane_items:
                lines.append(
                    "  "
                    + json.dumps(
                        {
                            "evidence_id": item.get("evidence_id"),
                            "reason": item.get("reason"),
                            "flags": item.get("flags") or [],
                            "target_binding_strength": item.get("target_binding_strength"),
                            "decisive_surface": item.get("decisive_surface"),
                            "source_sense_status": item.get("source_sense_status"),
                            "source_sense_reason": item.get("source_sense_reason"),
                            "source_sense_surface_overlap": item.get("source_sense_surface_overlap") or [],
                            "source_sense_branch_overlap": item.get("source_sense_branch_overlap") or [],
                            "source_heading_text": item.get("source_heading_text") or "",
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True, help="Input evidence-packets JSONL path.")
    parser.add_argument("--overlay", default="", help="Optional overlay JSONL path.")
    parser.add_argument(
        "--out-root",
        default="data/work/cache/diagnostics/step67_generic_lane_policy",
        help="Output root for replay artifacts.",
    )
    parser.add_argument("--run-id", default="", help="Optional explicit output run id.")
    parser.add_argument("--limit-kcs", type=int, default=None)
    parser.add_argument("--exact-kc-ids", nargs="*", default=None)
    args = parser.parse_args()

    packets_path = Path(args.packets)
    overlay_path = Path(args.overlay) if str(args.overlay or "").strip() else None
    out_root = Path(args.out_root)
    run_id = str(args.run_id or "").strip() or _utc_run_id()

    packets = _load_jsonl(packets_path)
    overlay_rows = _load_jsonl(overlay_path) if overlay_path else []
    overlay_by_id = _overlay_index(overlay_rows)
    selected_packets = _filter_packets(
        packets,
        limit_kcs=args.limit_kcs,
        exact_kc_ids=list(args.exact_kc_ids) if args.exact_kc_ids else None,
    )

    output_dir = out_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    policy = EvidenceLanePolicy()
    lane_packets = [
        build_lane_packet(packet, overlay_rows=overlay_by_id, policy=policy)
        for packet in selected_packets
    ]

    summary = summarize_lane_packets(lane_packets)
    summary.update(
        {
            "stage": "step67a_build_field_lane_packets_generic",
            "run_id": run_id,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "policy_version": policy.version,
            "packets_path": packets_path.as_posix(),
            "overlay_path": overlay_path.as_posix() if overlay_path else "",
            "out_dir": output_dir.as_posix(),
            "lane_packets_path": (output_dir / "lane_packets.jsonl").as_posix(),
            "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
        }
    )

    lane_counter = Counter(summary.get("lane_counter_all_items") or {})
    summary["lane_counter_all_items"] = dict(lane_counter)

    lane_packets_path = output_dir / "lane_packets.jsonl"
    summary_path = output_dir / "summary.json"
    audit_path = output_dir / "lane_audit.md"

    _write_jsonl(lane_packets_path, lane_packets)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    audit_path.write_text(
        _lane_audit_markdown(
            lane_packets,
            summary,
            packets_path=packets_path,
            overlay_path=overlay_path,
            output_dir=output_dir,
        ),
        encoding="utf-8",
    )

    print("STEP67A_GENERIC_LANE_RUN_ID =", run_id)
    print("STEP67A_GENERIC_LANE_DIR =", output_dir.as_posix())
    print("STEP67A_GENERIC_LANE_JSONL =", lane_packets_path.as_posix())
    print("STEP67A_GENERIC_LANE_SUMMARY =", summary_path.as_posix())
    print("STEP67A_GENERIC_LANE_AUDIT =", audit_path.as_posix())
    print("packet_count =", len(lane_packets))
    print("lane_counter_all_items =", json.dumps(summary.get("lane_counter_all_items") or {}, ensure_ascii=False))
    print("selected_counter =", json.dumps(summary.get("selected_counter") or {}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
