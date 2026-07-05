from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.retrieval_gate.shapeaware_shadow import build_shapeaware_guidance, compose_shapeaware_shadow_pack


EXPECTED_LOCAL_ARTIFACTS = {
    "profiles": REPO_ROOT / "data/processed/kc_retrieval_profiles/full144_diagnostic_rehydrated_ctx32768_204794_profile/kc_retrieval_profiles.jsonl",
    "scored": REPO_ROOT / "data/processed/evidence_stage_v3_scored_candidates/full144_diagnostic_rehydrated_ctx32768_204794_scored/scored_candidates.jsonl",
    "packs": REPO_ROOT / "data/processed/evidence_stage_v3_evidence_packs/full144_diagnostic_rehydrated_ctx32768_204794_pack/kc_evidence_packs.jsonl",
}

KNOWN_TARGET_LABELS = [
    "NB Learning Phase",
    "Rand Index",
    "K-Means Algorithm",
    "DBSCAN Parameters",
    "Directly Density-Reachable",
    "Density-Reachable",
    "External Index: F-Measure",
    "Basic F-Measure",
]

KNOWN_TARGET_PATTERNS = {
    "NB Learning Phase": ["NB Learning Phase"],
    "Rand Index": ["Rand Index"],
    "K-Means Algorithm": ["K-Means Algorithm"],
    "DBSCAN Parameters": ["DBSCAN Parameters (eps, minPts)", "DBSCAN Parameters"],
    "Directly Density-Reachable": ["Directly Density-Reachable"],
    "Density-Reachable": ["Density-Reachable"],
    "External Index: F-Measure": ["External Index: F-Measure"],
    "Basic F-Measure": ["F-Measure"],
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        out: List[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def _mapping_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray, str)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _latest_extracted_root(inbound_root: Path) -> Path | None:
    candidates = sorted(
        path for path in inbound_root.glob("shapeaware_surgery_*/extracted") if path.is_dir()
    )
    return candidates[-1] if candidates else None


def _resolve_artifacts(extracted_root: Path | None) -> Dict[str, Path]:
    resolved: Dict[str, Path] = {}
    for key, local_path in EXPECTED_LOCAL_ARTIFACTS.items():
        if local_path.exists():
            resolved[key] = local_path
            continue
        if extracted_root is None:
            raise FileNotFoundError(f"Missing local artifact and no extracted fallback available: {local_path}")
        extracted_path = extracted_root / local_path.relative_to(REPO_ROOT)
        if not extracted_path.exists():
            raise FileNotFoundError(f"Missing local and extracted artifact for {key}: {local_path}")
        resolved[key] = extracted_path
    return resolved


def _route_from_pack(pack: Mapping[str, Any]) -> str:
    quality = pack.get("pack_quality") or {}
    route = str(quality.get("route") or "").strip()
    if route:
        return route
    status = str(quality.get("status") or "").strip()
    return status or "unknown"


def _ordered_len(pack: Mapping[str, Any]) -> int:
    return len(pack.get("ordered_pack_for_drafting") or [])


def _profile_negative_terms(profile: Mapping[str, Any]) -> List[str]:
    negatives: List[str] = []
    negatives.extend(_string_list(profile.get("negative_terms")))
    for route in _mapping_list(profile.get("retrieval_routes")):
        negatives.extend(_string_list(route.get("negative_terms_any")))
    return _string_list(negatives)


def _shapeaware_guidance_for_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return build_shapeaware_guidance(
        profile,
        query_variants=_mapping_list(profile.get("query_variants")),
        retrieval_routes=_mapping_list(profile.get("retrieval_routes")),
        expected_evidence_shape_hints=_mapping_list(profile.get("expected_evidence_shape_hints")),
        negative_terms=_profile_negative_terms(profile),
    )


def _enrich_row(row: Mapping[str, Any], profile: Mapping[str, Any], guidance: Mapping[str, Any]) -> Dict[str, Any]:
    enriched = dict(row)
    for field_name in (
        "aliases",
        "topic_path_labels",
        "topic_path_ids",
        "parent_topic_label",
        "parent_topic_id",
        "sibling_labels",
    ):
        if field_name not in enriched or not enriched.get(field_name):
            enriched[field_name] = profile.get(field_name)
    for field_name in (
        "concept_head",
        "qualifiers",
        "expanded_aliases",
        "normalized_surface_variants",
        "expected_evidence_needs",
        "route_specific_query_variants",
        "route_specific_required_terms",
        "route_specific_optional_terms",
        "negative_sibling_terms",
        "risk_hints",
    ):
        enriched[field_name] = guidance.get(field_name)
    return enriched


def _transition_matrix(records: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in records:
        matrix[str(record["baseline_route"])][str(record["shapeaware_route"])] += 1
    return {
        old_route: dict(sorted(new_counts.items()))
        for old_route, new_counts in sorted(matrix.items())
    }


def _top_role_breakdown(items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        for role in _string_list(item.get("shapeaware_support_roles")):
            counts[role] += 1
    return dict(sorted(counts.items()))


def _record_for_kc(
    kc_id: str,
    profile: Mapping[str, Any],
    baseline_pack: Mapping[str, Any],
    scored_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    guidance = _shapeaware_guidance_for_profile(profile)
    enriched_rows = [_enrich_row(row, profile, guidance) for row in scored_rows]
    shadow_pack = compose_shapeaware_shadow_pack(
        kc_id,
        enriched_rows,
        expected_evidence_needs=guidance.get("expected_evidence_needs"),
    )
    baseline_route = _route_from_pack(baseline_pack)
    new_route = str(shadow_pack.get("shapeaware_route") or "")
    baseline_ordered_len = _ordered_len(baseline_pack)
    new_drafting_core_len = len(shadow_pack.get("drafting_core_evidence") or [])
    new_auxiliary_len = len(shadow_pack.get("auxiliary_evidence") or [])
    new_review_needed_len = len(shadow_pack.get("review_needed_evidence") or [])
    new_rejected_len = len(shadow_pack.get("rejected_false_positive_evidence") or [])
    drafting_core_risk_flags = _string_list(shadow_pack.get("drafting_core_risk_flags"))
    auxiliary_risk_flags = _string_list(shadow_pack.get("auxiliary_risk_flags"))
    review_needed_risk_flags = _string_list(shadow_pack.get("review_needed_risk_flags"))
    rejected_false_positive_risk_flags = _string_list(shadow_pack.get("rejected_false_positive_risk_flags"))
    pack_level_risk_flags = _string_list(shadow_pack.get("pack_level_risk_flags") or shadow_pack.get("review_risk_flags"))
    return {
        "kc_id": kc_id,
        "canonical_name": str(profile.get("canonical_name") or baseline_pack.get("canonical_name") or ""),
        "baseline_route": baseline_route,
        "shapeaware_route": new_route,
        "baseline_ordered_pack_len": baseline_ordered_len,
        "shapeaware_drafting_core_len": new_drafting_core_len,
        "shapeaware_auxiliary_len": new_auxiliary_len,
        "shapeaware_review_needed_len": new_review_needed_len,
        "shapeaware_rejected_false_positive_len": new_rejected_len,
        "drafting_core_risk_flags": drafting_core_risk_flags,
        "auxiliary_risk_flags": auxiliary_risk_flags,
        "review_needed_risk_flags": review_needed_risk_flags,
        "rejected_false_positive_risk_flags": rejected_false_positive_risk_flags,
        "pack_level_risk_flags": pack_level_risk_flags,
        "expected_evidence_needs": shadow_pack.get("expected_evidence_needs") or [],
        "evidence_need_satisfaction": shadow_pack.get("evidence_need_satisfaction") or {},
        "drafting_core_role_breakdown": _top_role_breakdown(shadow_pack.get("drafting_core_evidence") or []),
        "review_needed_role_breakdown": _top_role_breakdown(shadow_pack.get("review_needed_evidence") or []),
    }


def _match_score(canonical_name: str, requested_label: str) -> int:
    patterns = KNOWN_TARGET_PATTERNS.get(requested_label, [requested_label])
    canonical_low = canonical_name.lower().strip()
    best = 0
    for pattern in patterns:
        pattern_low = pattern.lower().strip()
        if pattern_low == canonical_low:
            best = max(best, 2)
        elif pattern_low in canonical_low:
            best = max(best, 1)
    return best


def _compact_entry(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kc_id": record["kc_id"],
        "canonical_name": record["canonical_name"],
        "baseline_route": record["baseline_route"],
        "shapeaware_route": record["shapeaware_route"],
        "baseline_ordered_pack_len": record["baseline_ordered_pack_len"],
        "shapeaware_drafting_core_len": record["shapeaware_drafting_core_len"],
        "shapeaware_auxiliary_len": record["shapeaware_auxiliary_len"],
        "shapeaware_review_needed_len": record["shapeaware_review_needed_len"],
        "drafting_core_risk_flags": record["drafting_core_risk_flags"],
        "review_needed_risk_flags": record["review_needed_risk_flags"],
        "pack_level_risk_flags": record["pack_level_risk_flags"],
    }


def build_report(artifact_paths: Mapping[str, Path]) -> Dict[str, Any]:
    profiles = _read_jsonl(artifact_paths["profiles"])
    baseline_packs = _read_jsonl(artifact_paths["packs"])
    scored_rows = _read_jsonl(artifact_paths["scored"])

    profiles_by_kc = {str(row.get("kc_id") or ""): row for row in profiles if str(row.get("kc_id") or "")}
    packs_by_kc = {str(row.get("kc_id") or ""): row for row in baseline_packs if str(row.get("kc_id") or "")}
    scored_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in scored_rows:
        kc_id = str(row.get("kc_id") or row.get("knowledge_unit_id") or "")
        if kc_id:
            scored_by_kc[kc_id].append(dict(row))

    ordered_kcs = sorted(set(profiles_by_kc) | set(packs_by_kc))
    records: List[Dict[str, Any]] = []
    for kc_id in ordered_kcs:
        profile = profiles_by_kc.get(kc_id, packs_by_kc.get(kc_id, {}))
        baseline_pack = packs_by_kc.get(
            kc_id,
            {
                "kc_id": kc_id,
                "canonical_name": profile.get("canonical_name", ""),
                "ordered_pack_for_drafting": [],
                "pack_quality": {"route": "missing_baseline_pack"},
            },
        )
        records.append(_record_for_kc(kc_id, profile, baseline_pack, scored_by_kc.get(kc_id, [])))

    baseline_routes = Counter(record["baseline_route"] for record in records)
    shapeaware_routes = Counter(record["shapeaware_route"] for record in records)
    transition_matrix = _transition_matrix(records)

    rescued_insufficient = [
        _compact_entry(record)
        for record in records
        if record["baseline_route"] == "insufficient_support_packet"
        and record["shapeaware_route"] != "insufficient_source_support_packet"
    ]
    demoted_risky_standard = [
        _compact_entry(record)
        for record in records
        if record["baseline_route"] == "standard_drafting"
        and not str(record["shapeaware_route"]).startswith("standard_")
    ]
    unchanged_clean = [
        _compact_entry(record)
        for record in records
        if record["baseline_route"] == "standard_drafting"
        and str(record["shapeaware_route"]).startswith("standard_")
        and not record["drafting_core_risk_flags"]
    ]
    suspected_false_positive_drafting_packs = [
        _compact_entry(record)
        for record in records
        if record["baseline_ordered_pack_len"] > 0
        and (
            record["shapeaware_route"] == "suspected_false_positive_review_packet"
            or "suspected_false_positive" in record["drafting_core_risk_flags"]
        )
    ]
    known_target_diagnostics: List[Dict[str, Any]] = []
    for requested_label in KNOWN_TARGET_LABELS:
        matched_records = [
            (record, _match_score(str(record["canonical_name"]), requested_label))
            for record in records
        ]
        matched_records = [item for item in matched_records if item[1] > 0]
        if matched_records:
            matched_records.sort(
                key=lambda item: (
                    -item[1],
                    str(item[0]["canonical_name"]),
                    str(item[0]["kc_id"]),
                )
            )
            record = matched_records[0][0]
            known_target_diagnostics.append(
                _compact_entry(record)
                | {
                    "requested_label": requested_label,
                    "drafting_core_risk_flags": record["drafting_core_risk_flags"],
                    "auxiliary_risk_flags": record["auxiliary_risk_flags"],
                    "review_needed_risk_flags": record["review_needed_risk_flags"],
                    "rejected_false_positive_risk_flags": record["rejected_false_positive_risk_flags"],
                    "pack_level_risk_flags": record["pack_level_risk_flags"],
                    "expected_evidence_needs": record["expected_evidence_needs"],
                    "evidence_need_satisfaction": record["evidence_need_satisfaction"],
                    "drafting_core_role_breakdown": record["drafting_core_role_breakdown"],
                    "review_needed_role_breakdown": record["review_needed_role_breakdown"],
                }
            )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifact_sources": {key: str(path) for key, path in artifact_paths.items()},
        "kc_count": len(records),
        "baseline_route_distribution": dict(sorted(baseline_routes.items())),
        "shapeaware_route_distribution": dict(sorted(shapeaware_routes.items())),
        "transition_matrix": transition_matrix,
        "ordered_pack_vs_shapeaware_summary": {
            "baseline_total_ordered_pack_items": sum(record["baseline_ordered_pack_len"] for record in records),
            "shapeaware_total_drafting_core_items": sum(record["shapeaware_drafting_core_len"] for record in records),
            "shapeaware_total_auxiliary_items": sum(record["shapeaware_auxiliary_len"] for record in records),
            "shapeaware_total_review_needed_items": sum(record["shapeaware_review_needed_len"] for record in records),
            "shapeaware_total_rejected_false_positive_items": sum(
                record["shapeaware_rejected_false_positive_len"] for record in records
            ),
        },
        "rescued_insufficient_support_kcs": rescued_insufficient,
        "demoted_risky_standard_kcs": demoted_risky_standard,
        "unchanged_clean_kcs": unchanged_clean,
        "suspected_false_positive_drafting_packs": suspected_false_positive_drafting_packs,
        "known_target_diagnostics": known_target_diagnostics,
        "per_kc": records,
    }


def render_text_report(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Shape-Aware Shadow Pack Comparison")
    lines.append(f"Generated: {report['generated_at_utc']}")
    lines.append(f"KC count: {report['kc_count']}")
    lines.append("")
    lines.append("Artifact Sources")
    for key, path in (report.get("artifact_sources") or {}).items():
        lines.append(f"- {key}: {path}")
    lines.append("")
    lines.append("Baseline Route Distribution")
    for route, count in (report.get("baseline_route_distribution") or {}).items():
        lines.append(f"- {route}: {count}")
    lines.append("")
    lines.append("Shape-Aware Route Distribution")
    for route, count in (report.get("shapeaware_route_distribution") or {}).items():
        lines.append(f"- {route}: {count}")
    lines.append("")
    lines.append("Transition Matrix")
    for old_route, new_counts in (report.get("transition_matrix") or {}).items():
        rendered = ", ".join(f"{new_route}={count}" for new_route, count in new_counts.items())
        lines.append(f"- {old_route} -> {rendered}")
    lines.append("")
    ordered_summary = report.get("ordered_pack_vs_shapeaware_summary") or {}
    lines.append("Ordered Pack vs Shape-Aware Evidence Totals")
    for key, value in ordered_summary.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    for title, key in (
        ("Rescued Insufficient-Support KCs", "rescued_insufficient_support_kcs"),
        ("Demoted Risky Standard KCs", "demoted_risky_standard_kcs"),
        ("Unchanged Clean KCs", "unchanged_clean_kcs"),
        ("Suspected False-Positive Drafting Packs", "suspected_false_positive_drafting_packs"),
    ):
        lines.append(title)
        items = report.get(key) or []
        if not items:
            lines.append("- none")
        else:
            for item in items:
                lines.append(
                    "- "
                    f"{item['canonical_name']} ({item['kc_id']}): "
                    f"{item['baseline_route']} -> {item['shapeaware_route']}, "
                    f"ordered={item['baseline_ordered_pack_len']}, "
                    f"core={item['shapeaware_drafting_core_len']}, "
                    f"aux={item['shapeaware_auxiliary_len']}, "
                    f"review={item['shapeaware_review_needed_len']}, "
                    f"core_flags={','.join(item['drafting_core_risk_flags']) or 'none'}, "
                    f"review_flags={','.join(item['review_needed_risk_flags']) or 'none'}"
                )
        lines.append("")
    lines.append("Known Target Diagnostics")
    known_target_items = report.get("known_target_diagnostics") or []
    if not known_target_items:
        lines.append("- none")
    else:
        for item in known_target_items:
            needs = ", ".join(
                f"{spec.get('priority')}:{spec.get('need')}"
                for spec in item.get("expected_evidence_needs") or []
            ) or "none"
            satisfied = ", ".join(
                f"{need}={status.get('status')}"
                for need, status in (item.get("evidence_need_satisfaction") or {}).items()
            ) or "none"
            lines.append(
                "- "
                f"{item['canonical_name']} ({item['kc_id']}): "
                f"{item['baseline_route']} -> {item['shapeaware_route']}, "
                f"ordered={item['baseline_ordered_pack_len']}, "
                f"core={item['shapeaware_drafting_core_len']}, "
                f"aux={item['shapeaware_auxiliary_len']}, "
                f"review={item['shapeaware_review_needed_len']}, "
                f"core_flags={','.join(item['drafting_core_risk_flags']) or 'none'}, "
                f"review_flags={','.join(item['review_needed_risk_flags']) or 'none'}"
            )
            lines.append(f"  needs: {needs}")
            lines.append(f"  satisfaction: {satisfied}")
            lines.append(
                "  bucket_flags: "
                f"core={json.dumps(item.get('drafting_core_risk_flags') or [])}, "
                f"aux={json.dumps(item.get('auxiliary_risk_flags') or [])}, "
                f"review={json.dumps(item.get('review_needed_risk_flags') or [])}, "
                f"rejected={json.dumps(item.get('rejected_false_positive_risk_flags') or [])}"
            )
            lines.append(
                "  role_breakdown: "
                f"core={json.dumps(item.get('drafting_core_role_breakdown') or {}, sort_keys=True)}, "
                f"review={json.dumps(item.get('review_needed_role_breakdown') or {}, sort_keys=True)}"
            )
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare baseline Step 5x packs against shape-aware shadow routing.")
    parser.add_argument(
        "--inbound-root",
        default=str(REPO_ROOT / "_sofja_inbound"),
        help="Root directory that may contain shapeaware_surgery_<STAMP>/extracted fallbacks.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Optional explicit output directory. Defaults to local_audits/shapeaware_shadow_pack_comparison_<STAMP>.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inbound_root = Path(args.inbound_root)
    extracted_root = _latest_extracted_root(inbound_root) if inbound_root.exists() else None
    artifact_paths = _resolve_artifacts(extracted_root)

    output_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "local_audits" / f"shapeaware_shadow_pack_comparison_{utc_stamp()}"
    output_dir.mkdir(parents=True, exist_ok=False)

    report = build_report(artifact_paths)
    json_path = output_dir / "shapeaware_shadow_pack_comparison.json"
    text_path = output_dir / "shapeaware_shadow_pack_comparison.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    text_path.write_text(render_text_report(report), encoding="utf-8")

    print(f"ARTIFACT_SOURCE profiles={artifact_paths['profiles']}")
    print(f"ARTIFACT_SOURCE scored={artifact_paths['scored']}")
    print(f"ARTIFACT_SOURCE packs={artifact_paths['packs']}")
    print(f"SUMMARY baseline_routes={json.dumps(report['baseline_route_distribution'], sort_keys=True)}")
    print(f"SUMMARY shapeaware_routes={json.dumps(report['shapeaware_route_distribution'], sort_keys=True)}")
    print(
        "SUMMARY totals="
        + json.dumps(report["ordered_pack_vs_shapeaware_summary"], sort_keys=True)
    )
    print(f"OUTPUT_DIR {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
