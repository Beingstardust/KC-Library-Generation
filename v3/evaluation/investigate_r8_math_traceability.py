"""Conservative draft-equation to admitted-source traceability diagnostic.

This is deliberately a lower-bound audit, not a status gate. It recognizes literal normalized
relations and reports re-rendered or algebraically equivalent formulas as unresolved rather than
pretending to perform symbolic proof.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import pathlib
import re
import sys
from typing import Any, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from kc_l.retrieval_gate.evidence_pack import compact_formula_signature  # noqa: E402


RELATION_RE = re.compile(r"(?:<=|>=|!=|=|\u2248)")
EDGE_PUNCTUATION_RE = re.compile(r"^[,;:.]+|[,;:.]+$")


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("kc_id") or row.get("knowledge_unit_id") or "")


def draft_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    draft = row.get("draft") or {}
    return draft if isinstance(draft, Mapping) else {}


def draft_body(row: Mapping[str, Any]) -> str:
    contextual = draft_payload(row).get("contextual_kc_draft") or {}
    return str(contextual.get("text") or "") if isinstance(contextual, Mapping) else ""


def normalized_relation(text: str) -> str:
    raw = str(text or "").replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    raw = raw.replace("\u2264", "<=").replace("\u2265", ">=").replace("\u2260", "!=")
    return EDGE_PUNCTUATION_RE.sub("", compact_formula_signature(raw)).strip()


def relation_occurrences(text: str) -> list[dict[str, Any]]:
    normalized = normalized_relation(text)
    occurrences = []
    for match in RELATION_RE.finditer(normalized):
        prefix = normalized[max(0, match.start() - 24):match.start()]
        # A lower bound such as i=1 inside a summation is part of its enclosing formula, not a
        # second mathematical claim. Sigma is included because upper-case Sigma lowercases to it.
        if re.search(r"(?:sum|prod|[\u2211\u220f\u03c3])_?[a-z][a-z0-9]*$", prefix):
            continue
        occurrences.append({"normalized_text": normalized, "operator": match.group(0),
                            "start": match.start(), "end": match.end()})
    return occurrences


def common_suffix_length(left: str, right: str, limit: int = 80) -> int:
    matched = 0
    while (matched < min(len(left), len(right), limit)
           and left[-matched - 1] == right[-matched - 1]):
        matched += 1
    return matched


def common_prefix_length(left: str, right: str, limit: int = 160) -> int:
    matched = 0
    while (matched < min(len(left), len(right), limit)
           and left[matched] == right[matched]):
        matched += 1
    return matched


def best_centered_source_match(occurrence: Mapping[str, Any], evidence_text: str) -> dict[str, Any]:
    draft_text = str(occurrence["normalized_text"])
    draft_start, draft_end = int(occurrence["start"]), int(occurrence["end"])
    operator = str(occurrence["operator"])
    evidence = normalized_relation(evidence_text)
    best = {"matched": False, "matched_fragment": "", "match_chars": 0,
            "left_chars": 0, "right_chars": 0}
    for match in RELATION_RE.finditer(evidence):
        if match.group(0) != operator:
            continue
        left_count = common_suffix_length(draft_text[:draft_start], evidence[:match.start()])
        right_count = common_prefix_length(draft_text[draft_end:], evidence[match.end():])
        total = left_count + len(operator) + right_count
        if total <= int(best["match_chars"]):
            continue
        fragment = draft_text[draft_start - left_count:draft_end + right_count]
        # Short coincidences such as "p=1" are too common to prove source traceability. A valid
        # literal trace must preserve material on both sides and at least six non-operator chars.
        valid = (left_count >= 1 and right_count >= 1
                 and left_count + right_count >= 6
                 and any(char.isalpha() for char in fragment))
        best = {"matched": valid, "matched_fragment": fragment, "match_chars": total,
                "left_chars": left_count, "right_chars": right_count}
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True, type=pathlib.Path)
    parser.add_argument("--drafts", required=True, type=pathlib.Path)
    parser.add_argument("--out-json", type=pathlib.Path)
    args = parser.parse_args()

    packets = load_jsonl(args.packets)
    drafts = load_jsonl(args.drafts)
    packet_by_id = {unit_id(row): row for row in packets}
    status_counts: collections.Counter[str] = collections.Counter()
    equation_count = 0
    literal_trace_count = 0
    body_relations_in_ledger = 0
    relation_specific_ledger_trace_count = 0
    drafts_with_equations = 0
    drafts_with_unresolved = 0
    draft_results = []

    for draft_row in drafts:
        body = draft_body(draft_row)
        occurrences = relation_occurrences(body)
        if not occurrences:
            continue
        drafts_with_equations += 1
        draft = draft_payload(draft_row)
        contextual = draft.get("contextual_kc_draft") or {}
        status = str(contextual.get("status") or "") if isinstance(contextual, Mapping) else ""
        status_counts[status] += 1
        packet = packet_by_id.get(unit_id(draft_row)) or {}
        evidence = list(packet.get("evidence_for_synthesis") or [])
        ledger_entries = [entry for entry in draft.get("evidence_map") or []
                          if isinstance(entry, Mapping)]
        relation_results = []
        unresolved = 0
        for occurrence in occurrences:
            equation_count += 1
            matches = []
            for item in evidence:
                match = best_centered_source_match(
                    occurrence, str(item.get("text") or ""))
                if match["matched"]:
                    matches.append({"evidence_id": str(item.get("evidence_id") or ""), **match})
            matching_ids = [match["evidence_id"] for match in matches]
            literal = bool(matching_ids)
            matching_ledger_entries = []
            relation_ledger_ids = set()
            for entry in ledger_entries:
                claim_match = best_centered_source_match(
                    occurrence, str(entry.get("claim") or ""))
                if not claim_match["matched"]:
                    continue
                ids = [str(value) for value in entry.get("supporting_evidence_ids") or []]
                relation_ledger_ids.update(ids)
                matching_ledger_entries.append({"claim": entry.get("claim"),
                                                "supporting_evidence_ids": ids})
            in_ledger = bool(matching_ledger_entries)
            ledger = bool(set(matching_ids) & relation_ledger_ids)
            literal_trace_count += int(literal)
            body_relations_in_ledger += int(in_ledger)
            relation_specific_ledger_trace_count += int(ledger)
            unresolved += int(not literal)
            normalized = str(occurrence["normalized_text"])
            start, end = int(occurrence["start"]), int(occurrence["end"])
            relation_results.append({
                "normalized_relation_context": normalized[max(0, start - 80):min(len(normalized), end + 160)],
                "operator": occurrence["operator"],
                "literal_source_match": literal,
                "matching_evidence_ids": matching_ids,
                "match_details": matches,
                "represented_by_literal_relation_in_evidence_map": in_ledger,
                "matching_evidence_map_entries": matching_ledger_entries,
                "source_match_cited_by_matching_evidence_map_entry": ledger,
            })
        drafts_with_unresolved += int(unresolved > 0)
        draft_results.append({
            "kc_id": unit_id(draft_row),
            "canonical_name": draft_row.get("canonical_name") or packet.get("canonical_name"),
            "status": status,
            "relation_count": len(occurrences),
            "unresolved_literal_relations": unresolved,
            "relations": relation_results,
        })

    draft_results.sort(key=lambda row: (-row["unresolved_literal_relations"],
                                        str(row["canonical_name"])))
    result = {
        "method": {
            "scope": "every explicit relation operator in the contextual draft text",
            "match": "operator-centered normalized literal agreement on both sides in admitted evidence",
            "interpretation": "lower bound only; unresolved includes equivalent re-renderings",
            "status_effect": "none",
        },
        "counts": {
            "packets": len(packets),
            "drafts": len(drafts),
            "drafts_with_substantive_relations": drafts_with_equations,
            "substantive_draft_relations": equation_count,
            "literal_source_traces": literal_trace_count,
            "relations_represented_literally_in_evidence_map": body_relations_in_ledger,
            "literal_source_traces_cited_by_matching_evidence_map_entry": relation_specific_ledger_trace_count,
            "drafts_with_at_least_one_unresolved_literal_relation": drafts_with_unresolved,
        },
        "draft_statuses_with_relations": dict(sorted(status_counts.items())),
        "drafts": draft_results,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
