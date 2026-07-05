from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Tuple


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clip_text(value: Any, max_chars: int) -> str:
    text = normalize_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: pathlib.Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    invalid = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    invalid += 1
            except Exception:
                invalid += 1
    return rows, invalid


def write_jsonl(path: pathlib.Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def row_id(row: Mapping[str, Any]) -> str:
    for key in ("knowledge_unit_id", "kc_id", "topic_id", "node_id", "unit_id", "id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def unit_type(row: Mapping[str, Any]) -> str:
    value = row.get("knowledge_unit_type") or row.get("unit_type") or ""
    if value:
        return str(value)
    rid = row_id(row)
    return "kc" if rid.startswith("KC_") else ""


def canonical_name(row: Mapping[str, Any]) -> str:
    return normalize_text(row.get("canonical_name") or row.get("label") or row.get("name") or "")


def source_hierarchy_path(row: Mapping[str, Any]) -> List[str]:
    value = row.get("source_hierarchy_path") or row.get("ancestor_labels") or row.get("topic_path_labels") or []
    return [normalize_text(x) for x in value if normalize_text(x)]


def parent_topic_label_from_overlay(row: Mapping[str, Any]) -> str:
    path = source_hierarchy_path(row)
    if len(path) >= 2:
        return path[-2]
    return normalize_text(row.get("parent_topic_label") or "")


def hierarchy_context_from_overlay(row: Mapping[str, Any]) -> Dict[str, Any]:
    path = source_hierarchy_path(row)
    return {
        "source_hierarchy_path": path,
        "topic_labels": path[:-1] if path else [],
        "parent_topic_label": path[-2] if len(path) >= 2 else normalize_text(row.get("parent_topic_label") or ""),
        "leaf_label": path[-1] if path else canonical_name(row),
        "ancestor_hier_node_ids": [str(x) for x in row.get("ancestor_hier_node_ids") or [] if str(x)],
        "parent_hier_node_id": str(row.get("parent_hier_node_id") or ""),
        "leaf_hier_node_id": str(row.get("leaf_hier_node_id") or ""),
    }


def evidence_text_from_overlay(row: Mapping[str, Any], max_chars: int) -> str:
    for key in ("quote_surface", "original_quote_surface", "source_block_text", "original_source_block_text"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return clip_text(value, max_chars)
    return ""


def evidence_text_from_pack_item(item: Mapping[str, Any], max_chars: int) -> str:
    for key in ("text", "quote", "candidate_sentence_text", "source_block_text", "preview"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return clip_text(value, max_chars)
    return ""


def draft_field_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, dict):
        return normalize_text(value.get("text") or "")
    return normalize_text(value)


def draft_field_status(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if isinstance(value, dict):
        return str(value.get("status") or "")
    return ""


def score_overlay_evidence(row: Mapping[str, Any]) -> float:
    score = 0.0
    try:
        score += float(row.get("alignment_score") or 0.0)
    except Exception:
        pass
    support = row.get("support_profile") if isinstance(row.get("support_profile"), dict) else {}
    role_hint = row.get("role_hint") if isinstance(row.get("role_hint"), dict) else {}
    text = normalize_text(row.get("quote_surface") or row.get("source_block_text") or "")
    low = text.lower()

    if support.get("definition_candidate") or support.get("definition_signal"):
        score += 12.0
    if support.get("scope_signal") or support.get("context_candidate"):
        score += 8.0
    if support.get("equation_support") or support.get("formula_candidate"):
        score += 5.0
    if "definition" in str(role_hint).lower():
        score += 8.0
    if "scope" in str(role_hint).lower() or "context" in str(role_hint).lower():
        score += 5.0
    if len(text) >= 80:
        score += 3.0
    if len(text) < 50:
        score -= 6.0
    if any(low.endswith(x) for x in ("can easily", "is that", "such as", "and", "or", "to", "of")):
        score -= 12.0
    if bool(row.get("is_heading_like")):
        score -= 8.0
    if str(row.get("contamination_risk") or "").lower() == "high":
        score -= 8.0
    return score


def compact_overlay_evidence(row: Mapping[str, Any], max_chars: int) -> Dict[str, Any]:
    support = row.get("support_profile") if isinstance(row.get("support_profile"), dict) else {}
    return {
        "evidence_id": str(row.get("overlay_candidate_id") or ""),
        "text": evidence_text_from_overlay(row, max_chars),
        "source_block_text": clip_text(row.get("source_block_text") or "", max_chars),
        "role_hint": row.get("role_hint") if isinstance(row.get("role_hint"), dict) else {},
        "support_profile": {
            "classification": support.get("classification"),
            "definition_candidate": bool(support.get("definition_candidate") or support.get("definition_signal")),
            "scope_signal": bool(support.get("scope_signal")),
            "context_candidate": bool(support.get("context_candidate")),
            "equation_support": bool(support.get("equation_support")),
        },
        "doc_id": str(row.get("doc_id") or ""),
        "page_index": row.get("page_index"),
        "patch_heading": normalize_text(row.get("patch_heading") or row.get("original_patch_heading") or ""),
        "quote_verification_status": str(row.get("quote_verification_status") or ""),
        "contamination_risk": str(row.get("contamination_risk") or ""),
        "score_for_packet": round(score_overlay_evidence(row), 4),
    }


def compact_topic_evidence(item: Mapping[str, Any], max_chars: int) -> Dict[str, Any]:
    source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {}
    return {
        "evidence_id": str(item.get("candidate_id") or item.get("source_candidate_id") or item.get("scored_candidate_id") or ""),
        "text": evidence_text_from_pack_item(item, max_chars),
        "source_block_text": clip_text(item.get("source_block_text") or "", max_chars),
        "role": str(item.get("role") or item.get("slot_role") or ""),
        "roles": [str(x) for x in item.get("roles") or [] if str(x)],
        "doc_id": str(item.get("doc_id") or source_refs.get("doc_id") or ""),
        "page_index": item.get("page_index", source_refs.get("page_index")),
        "patch_heading": normalize_text(item.get("patch_heading") or source_refs.get("patch_heading") or ""),
        "selected_text_mode": str(item.get("selected_text_mode") or ""),
        "risk_flags": [str(x) for x in item.get("risk_flags") or [] if str(x)],
    }


def build_kc_packet(
    kc_id: str,
    rows: List[Dict[str, Any]],
    sibling_names: List[str],
    child_draft: Mapping[str, Any] | None,
    *,
    evidence_limit: int,
    text_max_chars: int,
) -> Dict[str, Any]:
    exemplar = sorted(rows, key=lambda r: str(r.get("overlay_candidate_id") or ""))[0]
    ordered_rows = sorted(rows, key=score_overlay_evidence, reverse=True)
    selected = ordered_rows[:evidence_limit]
    draft = dict(child_draft or {})

    return {
        "packet_version": "step67_v2_synthesis_packet_v1",
        "knowledge_unit_type": "kc",
        "knowledge_unit_id": kc_id,
        "kc_id": kc_id,
        "canonical_name": canonical_name(exemplar),
        "aliases": [normalize_text(x) for x in exemplar.get("aliases") or [] if normalize_text(x)],
        "hierarchy": hierarchy_context_from_overlay(exemplar),
        "sibling_kc_names": sibling_names,
        "upstream_summary": {
            "total_overlay_candidates": len(rows),
            "definition_like_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("definition_candidate") or (r.get("support_profile") or {}).get("definition_signal")),
            "scope_like_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("scope_signal")),
            "context_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("context_candidate")),
            "formula_or_equation_candidates": sum(1 for r in rows if (r.get("support_profile") or {}).get("equation_support") or (r.get("support_profile") or {}).get("formula_candidate")),
        },
        "evidence_for_synthesis": [
            compact_overlay_evidence(row, text_max_chars)
            for row in selected
        ],
        "previous_step67_draft_summary": {
            "available": bool(draft),
            "draft_status": draft.get("draft_status"),
            "review_readiness": draft.get("review_readiness"),
            "definition_status": draft_field_status(draft, "definition_full_candidate"),
            "definition_text": draft_field_text(draft, "definition_full_candidate"),
            "scope_status": draft_field_status(draft, "scope_candidate"),
            "scope_text": draft_field_text(draft, "scope_candidate"),
            "hold_reasons": draft.get("hold_reasons"),
            "risk_flags": draft.get("risk_flags"),
        },
        "drafting_instruction": {
            "goal": "Create one integrated contextual KC draft useful for segmentation, tutor evaluation, and expert review.",
            "must_use": [
                "Use all relevant evidence_for_synthesis items, not only the first definitional-looking span.",
                "Connect compatible evidence into a coherent supported context object.",
                "Do not invent facts not supported by evidence.",
                "Every substantive claim must be linked to evidence_id values in evidence_map.",
                "If evidence is partial, produce partial status and explicit uncertainty notes rather than a fake complete definition.",
            ],
        },
        "expected_output_fields": [
            "contextual_kc_draft",
            "segmentation_support",
            "evaluation_support",
            "evidence_map",
            "kc_specific_criteria",
            "kc_specific_criteria_status",
            "kc_specific_criteria_source",
        ],
    }


def topic_child_match(topic_label: str, kc_path: List[str]) -> bool:
    label = normalize_text(topic_label).lower()
    if not label or len(kc_path) < 2:
        return False
    return any(normalize_text(x).lower() == label for x in kc_path[:-1])


def build_topic_packet(
    topic: Mapping[str, Any],
    child_kc_ids: List[str],
    kc_packets_by_id: Mapping[str, Mapping[str, Any]],
    child_drafts_by_id: Mapping[str, Mapping[str, Any]],
    *,
    topic_evidence_limit: int,
    child_limit: int,
    text_max_chars: int,
) -> Dict[str, Any]:
    topic_id = row_id(topic)
    topic_name = canonical_name(topic)
    ordered = [x for x in topic.get("ordered_pack_for_drafting") or [] if isinstance(x, dict)]
    near_miss = [x for x in topic.get("topic_near_miss_review_items") or topic.get("near_miss_review_items") or [] if isinstance(x, dict)]

    child_summaries = []
    for kc_id in child_kc_ids[:child_limit]:
        packet = kc_packets_by_id.get(kc_id) or {}
        draft = child_drafts_by_id.get(kc_id) or {}
        child_summaries.append(
            {
                "kc_id": kc_id,
                "canonical_name": packet.get("canonical_name") or canonical_name(draft),
                "hierarchy": packet.get("hierarchy"),
                "previous_definition_status": draft_field_status(draft, "definition_full_candidate"),
                "previous_definition_text": draft_field_text(draft, "definition_full_candidate"),
                "previous_scope_status": draft_field_status(draft, "scope_candidate"),
                "previous_scope_text": draft_field_text(draft, "scope_candidate"),
                "draft_status": draft.get("draft_status"),
                "review_readiness": draft.get("review_readiness"),
                "top_child_evidence": list((packet.get("evidence_for_synthesis") or [])[:3]),
            }
        )

    return {
        "packet_version": "step67_v2_topic_synthesis_packet_v1",
        "knowledge_unit_type": "topic",
        "knowledge_unit_id": topic_id,
        "topic_id": topic_id,
        "canonical_name": topic_name,
        "aliases": [normalize_text(x) for x in topic.get("aliases") or [] if normalize_text(x)],
        "topic_evidence_for_synthesis": [
            compact_topic_evidence(item, text_max_chars)
            for item in ordered[:topic_evidence_limit]
        ],
        "topic_near_miss_or_gap_context": [
            {
                "candidate_id": str(item.get("candidate_id") or item.get("scored_candidate_id") or ""),
                "preview": clip_text(item.get("preview") or item.get("text") or "", text_max_chars),
                "near_miss_reason": str(item.get("near_miss_reason") or ""),
                "risk_flags": [str(x) for x in item.get("risk_flags") or [] if str(x)],
                "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {},
            }
            for item in near_miss[:8]
        ],
        "child_kc_summary": {
            "child_kc_count": len(child_kc_ids),
            "included_child_kc_count": len(child_summaries),
            "child_kcs": child_summaries,
        },
        "drafting_instruction": {
            "goal": "Create one integrated topic draft that summarizes the conceptual area represented by its child KCs plus topic-level evidence.",
            "must_use": [
                "Use child_kc_summary as the backbone of the topic draft.",
                "Use topic_evidence_for_synthesis to ground the topic-level overview.",
                "Do not draft a topic from one clipped topic evidence sentence alone.",
                "Do not invent new child concepts that are not present in child_kc_summary or topic evidence.",
                "If topic-level evidence is thin, synthesize only what child KCs support and mark topic evidence gaps explicitly.",
                "Every substantive topic claim must be linked to evidence IDs or child KC IDs in evidence_map.",
            ],
        },
        "expected_output_fields": [
            "contextual_topic_draft",
            "child_kc_coverage_summary",
            "segmentation_support",
            "evaluation_support",
            "evidence_map",
            "topic_gap_notes",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step66-set", required=True, type=pathlib.Path)
    ap.add_argument("--topic5x-pack", required=True, type=pathlib.Path)
    ap.add_argument("--child-kc-drafts", required=True, type=pathlib.Path)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--kc-evidence-limit", type=int, default=18)
    ap.add_argument("--topic-evidence-limit", type=int, default=8)
    ap.add_argument("--topic-child-limit", type=int, default=24)
    ap.add_argument("--text-max-chars", type=int, default=2200)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    step66_set = read_json(args.step66_set)
    overlay_path = pathlib.Path(step66_set.get("artifacts", {}).get("candidate_sentence_overlay_jsonl") or "")
    if not overlay_path.is_absolute():
        overlay_path = pathlib.Path.cwd() / overlay_path
    overlay_rows, overlay_invalid = read_jsonl(overlay_path)

    topic_rows, topic_invalid = read_jsonl(args.topic5x_pack)
    child_drafts, child_drafts_invalid = read_jsonl(args.child_kc_drafts)

    child_drafts_by_id = {row_id(r): r for r in child_drafts if row_id(r)}

    rows_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in overlay_rows:
        kid = str(row.get("kc_id") or "")
        if kid:
            rows_by_kc[kid].append(row)

    parent_label_by_kc = {
        kid: parent_topic_label_from_overlay(rows[0])
        for kid, rows in rows_by_kc.items()
        if rows
    }

    sibling_names_by_parent: Dict[str, List[str]] = defaultdict(list)
    for kid, rows in rows_by_kc.items():
        parent = parent_label_by_kc.get(kid, "")
        if parent and rows:
            sibling_names_by_parent[parent].append(canonical_name(rows[0]))

    kc_packets = []
    kc_packets_by_id: Dict[str, Dict[str, Any]] = {}
    for kid in sorted(rows_by_kc):
        rows = rows_by_kc[kid]
        parent = parent_label_by_kc.get(kid, "")
        siblings = [x for x in sorted(set(sibling_names_by_parent.get(parent, []))) if x != canonical_name(rows[0])]
        packet = build_kc_packet(
            kid,
            rows,
            siblings,
            child_drafts_by_id.get(kid),
            evidence_limit=args.kc_evidence_limit,
            text_max_chars=args.text_max_chars,
        )
        kc_packets.append(packet)
        kc_packets_by_id[kid] = packet

    child_ids_by_topic_label: Dict[str, List[str]] = defaultdict(list)
    for kid, rows in rows_by_kc.items():
        if not rows:
            continue
        path = source_hierarchy_path(rows[0])
        for label in path[:-1]:
            child_ids_by_topic_label[normalize_text(label).lower()].append(kid)

    topic_packets = []
    for topic in topic_rows:
        tname = canonical_name(topic)
        child_ids = sorted(set(child_ids_by_topic_label.get(tname.lower(), [])))
        topic_packets.append(
            build_topic_packet(
                topic,
                child_ids,
                kc_packets_by_id,
                child_drafts_by_id,
                topic_evidence_limit=args.topic_evidence_limit,
                child_limit=args.topic_child_limit,
                text_max_chars=args.text_max_chars,
            )
        )

    all_packets = [*kc_packets, *topic_packets]

    packets_jsonl = args.out_dir / "step67_v2_synthesis_packets.jsonl"
    kc_packets_jsonl = args.out_dir / "step67_v2_kc_synthesis_packets.jsonl"
    topic_packets_jsonl = args.out_dir / "step67_v2_topic_synthesis_packets.jsonl"
    stats_json = args.out_dir / "step67_v2_synthesis_packet_stats.json"
    report_md = args.out_dir / "step67_v2_synthesis_packet_report.md"

    write_jsonl(packets_jsonl, all_packets)
    write_jsonl(kc_packets_jsonl, kc_packets)
    write_jsonl(topic_packets_jsonl, topic_packets)

    topic_child_counts = {
        p["canonical_name"]: p["child_kc_summary"]["child_kc_count"]
        for p in topic_packets
    }

    zero_child_topics = [
        p["canonical_name"]
        for p in topic_packets
        if p["child_kc_summary"]["child_kc_count"] == 0
    ]

    zero_topic_evidence = [
        p["canonical_name"]
        for p in topic_packets
        if len(p["topic_evidence_for_synthesis"]) == 0
    ]

    kc_evidence_counts = Counter(len(p["evidence_for_synthesis"]) for p in kc_packets)
    topic_evidence_counts = Counter(len(p["topic_evidence_for_synthesis"]) for p in topic_packets)
    topic_child_count_counter = Counter(p["child_kc_summary"]["child_kc_count"] for p in topic_packets)

    failures = []
    warnings = []

    if overlay_invalid:
        failures.append({"code": "overlay_invalid_json_rows", "count": overlay_invalid})
    if topic_invalid:
        failures.append({"code": "topic_pack_invalid_json_rows", "count": topic_invalid})
    if child_drafts_invalid:
        failures.append({"code": "child_drafts_invalid_json_rows", "count": child_drafts_invalid})
    if not kc_packets:
        failures.append({"code": "no_kc_packets_built"})
    if not topic_packets:
        failures.append({"code": "no_topic_packets_built"})
    if zero_child_topics:
        failures.append({"code": "topics_without_child_kc_context", "topics": zero_child_topics})
    if zero_topic_evidence:
        warnings.append({"code": "topics_without_topic_level_evidence", "topics": zero_topic_evidence})

    decision = "PASS_STEP67_V2_SYNTHESIS_PACKETS_READY_FOR_MANUAL_PACKET_REVIEW" if not failures else "FAIL_STEP67_V2_SYNTHESIS_PACKET_BUILD"

    stats = {
        "schema_version": "step67_v2_synthesis_packet_stats_v1",
        "created_utc": now_utc(),
        "decision": decision,
        "ready_for_manual_packet_review": not failures,
        "ready_for_model_smoke": False,
        "inputs": {
            "step66_set": str(args.step66_set),
            "step66_overlay": str(overlay_path),
            "topic5x_pack": str(args.topic5x_pack),
            "child_kc_drafts": str(args.child_kc_drafts),
        },
        "outputs": {
            "all_packets_jsonl": str(packets_jsonl),
            "kc_packets_jsonl": str(kc_packets_jsonl),
            "topic_packets_jsonl": str(topic_packets_jsonl),
            "stats_json": str(stats_json),
            "report_md": str(report_md),
        },
        "metrics": {
            "overlay_rows": len(overlay_rows),
            "overlay_invalid_json_rows": overlay_invalid,
            "kc_packet_count": len(kc_packets),
            "topic_packet_count": len(topic_packets),
            "all_packet_count": len(all_packets),
            "child_draft_rows": len(child_drafts),
            "child_draft_invalid_json_rows": child_drafts_invalid,
            "topic_child_counts": topic_child_counts,
            "topic_child_count_counter": dict(topic_child_count_counter),
            "zero_child_topic_count": len(zero_child_topics),
            "zero_child_topics": zero_child_topics,
            "zero_topic_evidence_count": len(zero_topic_evidence),
            "zero_topic_evidence": zero_topic_evidence,
            "kc_evidence_count_distribution": dict(kc_evidence_counts),
            "topic_evidence_count_distribution": dict(topic_evidence_counts),
        },
        "hashes": {
            "packets_sha256": sha256_file(packets_jsonl),
            "kc_packets_sha256": sha256_file(kc_packets_jsonl),
            "topic_packets_sha256": sha256_file(topic_packets_jsonl),
        },
        "failures": failures,
        "warnings": warnings,
        "policy": {
            "no_model_calls": True,
            "no_gpu_required": True,
            "no_pointer_mutation": True,
            "domain_agnostic_code": True,
            "topic_packets_use_child_kc_context": True,
            "kc_packets_include_full_upstream_overlay_evidence": True,
        },
    }

    write_json(stats_json, stats)

    md = []
    md.append("# Step6.7 v2 synthesis packet report")
    md.append("")
    md.append(f"- decision: `{decision}`")
    md.append(f"- ready_for_manual_packet_review: `{not failures}`")
    md.append(f"- ready_for_model_smoke: `False`")
    md.append(f"- kc_packet_count: `{len(kc_packets)}`")
    md.append(f"- topic_packet_count: `{len(topic_packets)}`")
    md.append(f"- overlay_rows: `{len(overlay_rows)}`")
    md.append(f"- child_draft_rows: `{len(child_drafts)}`")
    md.append("")
    md.append("## Topic child counts")
    for name, count in sorted(topic_child_counts.items()):
        md.append(f"- `{name}`: `{count}`")
    md.append("")
    md.append("## Failures")
    if failures:
        for item in failures:
            md.append(f"- `{item['code']}`: {json.dumps(item, ensure_ascii=False)}")
    else:
        md.append("- none")
    md.append("")
    md.append("## Warnings")
    if warnings:
        for item in warnings:
            md.append(f"- `{item['code']}`: {json.dumps(item, ensure_ascii=False)}")
    else:
        md.append("- none")
    md.append("")
    md.append("## Sample topic packet previews")
    for packet in topic_packets[:5]:
        md.append("")
        md.append(f"### {packet['canonical_name']}")
        md.append(f"- topic_evidence_count: `{len(packet['topic_evidence_for_synthesis'])}`")
        md.append(f"- child_kc_count: `{packet['child_kc_summary']['child_kc_count']}`")
        md.append("- child KCs:")
        for child in packet["child_kc_summary"]["child_kcs"][:12]:
            md.append(f"  - `{child.get('kc_id')}` | {child.get('canonical_name')} | def={child.get('previous_definition_status')} scope={child.get('previous_scope_status')}")
    report_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "decision": decision,
        "ready_for_manual_packet_review": not failures,
        "ready_for_model_smoke": False,
        "kc_packet_count": len(kc_packets),
        "topic_packet_count": len(topic_packets),
        "zero_child_topic_count": len(zero_child_topics),
        "zero_topic_evidence_count": len(zero_topic_evidence),
        "topic_child_count_counter": dict(topic_child_count_counter),
        "packets_jsonl": str(packets_jsonl),
        "kc_packets_jsonl": str(kc_packets_jsonl),
        "topic_packets_jsonl": str(topic_packets_jsonl),
        "stats_json": str(stats_json),
        "report_md": str(report_md),
        "failure_count": len(failures),
        "warning_count": len(warnings),
    }, indent=2, ensure_ascii=False))

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
