"""Diagnose contextual scoring, set sufficiency, budget use, and source ordering on frozen packets.

This script is read-only. Expected-shape measurements call the existing deterministic profile
heuristic; they are an evaluation of that signal, not a new completion policy.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import pathlib
import re
import statistics
import sys
from typing import Any, Iterable, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from kc_l.retrieval_profile.deterministic import infer_expected_evidence_shapes


SHAPE_PRIOR_TO_PACKET_SHAPE = {
    "definition_phrase": "definition",
    "formula_relation": "formula",
    "metric_relation": "formula",
    "process_phrase": "procedure",
}
CONTEXT_BASES = {"context_anchored_relevance", "heading_anchored_context_relevance"}
PAYLOAD_BASES = {
    "lead_in_payload",
    "structured_list_payload",
    "procedure_list_payload",
    "formula_qualifier_payload",
}


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("kc_id") or row.get("knowledge_unit_id") or "")


def quantiles(values: Iterable[int | float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {}

    def percentile(fraction: float) -> float:
        index = fraction * (len(ordered) - 1)
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        weight = index - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
    }


def admission_basis(item: Mapping[str, Any]) -> str:
    summary = item.get("support_profile_summary") or {}
    return str(summary.get("admission_basis") or "cross_encoder_relevance")


def source_region(item: Mapping[str, Any]) -> tuple[str, int]:
    page = item.get("page_index")
    return str(item.get("doc_id") or ""), int(page) if page is not None else -1


def source_position(item: Mapping[str, Any]) -> str:
    sentence_id = str(item.get("sentence_id") or "")
    return sentence_id.rsplit("::", 1)[0]


def source_contiguous_order(evidence: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Reconstruct the packet builder's documented region-utility/source-position order."""
    region_utility: dict[tuple[str, int], float] = {}
    for item in evidence:
        region = source_region(item)
        region_utility[region] = max(region_utility.get(region, 0.0),
                                     float(item.get("relevance") or 0.0))
    return sorted(evidence, key=lambda item: (
        -region_utility[source_region(item)],
        source_region(item),
        source_position(item),
    ))


def lexical_terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()))


def duplicate_pairs(evidence: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    terms = [lexical_terms(str(item.get("text") or "")) for item in evidence]
    normalized = [" ".join(str(item.get("text") or "").lower().split()) for item in evidence]
    exact = []
    near = []
    for left_index, left in enumerate(terms):
        for right_index, right in enumerate(terms[left_index + 1:], left_index + 1):
            if normalized[left_index] and normalized[left_index] == normalized[right_index]:
                exact.append({
                    "text": str(evidence[left_index].get("text") or ""),
                    "left_doc": evidence[left_index].get("doc_id"),
                    "left_sentence": evidence[left_index].get("sentence_id"),
                    "right_doc": evidence[right_index].get("doc_id"),
                    "right_sentence": evidence[right_index].get("sentence_id"),
                })
                continue
            if len(left) < 8:
                continue
            if len(right) < 8:
                continue
            union = left | right
            if union and len(left & right) / len(union) >= 0.90:
                near.append({
                    "jaccard": round(len(left & right) / len(union), 4),
                    "left_text": str(evidence[left_index].get("text") or ""),
                    "right_text": str(evidence[right_index].get("text") or ""),
                })
    return exact, near


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True, type=pathlib.Path)
    parser.add_argument("--packets", required=True, type=pathlib.Path)
    parser.add_argument("--out-json", type=pathlib.Path)
    parser.add_argument("--max-chars", type=int, default=14000)
    parser.add_argument("--max-passages", type=int, default=40)
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    packets = load_jsonl(args.packets)
    profile_by_id = {unit_id(row): row for row in profiles}
    chars_per_packet = []
    items_per_packet = []
    near_duplicate_total = 0
    exact_duplicate_total = 0
    duplicate_packets = []
    basis_counts: collections.Counter[str] = collections.Counter()
    basis_shapes: collections.Counter[str] = collections.Counter()
    missing_shape_counts: collections.Counter[str] = collections.Counter()
    expected_shape_counts: collections.Counter[str] = collections.Counter()
    missing_expected_shapes = []
    reordered_packets = []
    source_inversions_total = 0

    for packet in packets:
        evidence = list(packet.get("evidence_for_synthesis") or [])
        item_count = len(evidence)
        char_count = sum(len(str(item.get("text") or "")) for item in evidence)
        items_per_packet.append(item_count)
        chars_per_packet.append(char_count)
        exact_pairs, near_pairs = duplicate_pairs(evidence)
        exact_duplicate_total += len(exact_pairs)
        near_duplicate_total += len(near_pairs)
        if exact_pairs or near_pairs:
            duplicate_packets.append({
                "kc_id": unit_id(packet),
                "canonical_name": packet.get("canonical_name"),
                "exact_pair_count": len(exact_pairs),
                "near_pair_count": len(near_pairs),
                "exact_examples": exact_pairs[:3],
                "near_examples": near_pairs[:3],
            })

        for item in evidence:
            basis = admission_basis(item)
            basis_counts[basis] += 1
            shapes = set(item.get("shape_tags") or item.get("roles") or [])
            if basis in CONTEXT_BASES or basis in PAYLOAD_BASES:
                for shape in shapes or {"unshaped"}:
                    basis_shapes["%s:%s" % (basis, shape)] += 1

        profile = profile_by_id.get(unit_id(packet)) or {}
        variants = list(profile.get("deterministic_label_variants") or [])
        priors = infer_expected_evidence_shapes(
            str(profile.get("canonical_name") or packet.get("canonical_name") or ""), variants)
        required = sorted({SHAPE_PRIOR_TO_PACKET_SHAPE[prior] for prior in priors
                           if prior in SHAPE_PRIOR_TO_PACKET_SHAPE})
        actual = set((packet.get("evidence_coverage") or {}).get("shape_coverage") or {})
        missing = sorted(set(required) - actual)
        for shape in required:
            expected_shape_counts[shape] += 1
        for shape in missing:
            missing_shape_counts[shape] += 1
        if missing:
            missing_expected_shapes.append({
                "kc_id": unit_id(packet),
                "canonical_name": packet.get("canonical_name"),
                "packet_support_state": packet.get("packet_support_state"),
                "expected_from_label": required,
                "actual_shapes": sorted(actual),
                "missing": missing,
                "evidence_count": item_count,
            })

        reordered = source_contiguous_order(evidence)
        current_ids = [str(item.get("evidence_id") or "") for item in evidence]
        source_ids = [str(item.get("evidence_id") or "") for item in reordered]
        if current_ids != source_ids:
            source_rank = {evidence_id: rank for rank, evidence_id in enumerate(source_ids)}
            inversions = 0
            for left_index, left_id in enumerate(current_ids):
                for right_id in current_ids[left_index + 1:]:
                    if source_rank.get(left_id, 0) > source_rank.get(right_id, 0):
                        inversions += 1
            source_inversions_total += inversions
            displacement = sum(abs(index - source_rank.get(evidence_id, index))
                               for index, evidence_id in enumerate(current_ids))
            reordered_packets.append({
                "kc_id": unit_id(packet),
                "canonical_name": packet.get("canonical_name"),
                "evidence_count": item_count,
                "source_order_inversions": inversions,
                "total_rank_displacement": displacement,
            })

    reordered_packets.sort(
        key=lambda row: (-row["source_order_inversions"], -row["total_rank_displacement"],
                         str(row["canonical_name"])))
    missing_expected_shapes.sort(
        key=lambda row: (str(row["packet_support_state"]), str(row["canonical_name"])))
    result = {
        "counts": {"profiles": len(profiles), "packets": len(packets)},
        "budget": {
            "configured_max_chars": args.max_chars,
            "configured_max_passages": args.max_passages,
            "characters": quantiles(chars_per_packet),
            "passages": quantiles(items_per_packet),
            "packets_at_character_ceiling": sum(value >= args.max_chars for value in chars_per_packet),
            "packets_above_90_percent_character_ceiling": sum(
                value >= args.max_chars * 0.90 for value in chars_per_packet),
            "packets_at_passage_ceiling": sum(value >= args.max_passages for value in items_per_packet),
        },
        "selection_redundancy": {
            "exact_duplicate_pairs": exact_duplicate_total,
            "near_duplicate_pairs_jaccard_gte_0_90": near_duplicate_total,
            "packets": duplicate_packets,
        },
        "admission_basis_counts": dict(sorted(basis_counts.items())),
        "context_and_payload_shape_counts": dict(sorted(basis_shapes.items())),
        "expected_shapes_from_existing_label_heuristic": {
            "expected_counts": dict(sorted(expected_shape_counts.items())),
            "missing_counts": dict(sorted(missing_shape_counts.items())),
            "packets_missing_at_least_one_expected_shape": len(missing_expected_shapes),
            "packets": missing_expected_shapes,
        },
        "source_order": {
            "packets_changed_by_source_contiguous_reorder": len(reordered_packets),
            "pair_inversions_total": source_inversions_total,
            "ranked_packets": reordered_packets,
        },
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
