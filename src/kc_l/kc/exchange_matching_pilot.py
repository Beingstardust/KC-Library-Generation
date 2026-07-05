from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from kc_l.kc.restarted_retrieval_pilot import run_query, tokenize
from kc_l.retrieval_gate.text_normalize import match_normalize
from kc_l.utils.json_io import read_json, read_jsonl, write_json


EXCHANGE_MATCHING_STAGE = "kc_exchange_matching_pilot_restarted"
EXCHANGE_MATCHING_RULE_VERSION = "exchange_matching_pilot.v1"
EXCHANGE_INPUT_SCHEMA_VERSION = "kc.exchange_matching_pilot.input.v1"
EXCHANGE_RETRIEVAL_SCHEMA_VERSION = "kc.exchange_matching_pilot.retrieval_results.v1"
EXCHANGE_ASSIGNMENT_SCHEMA_VERSION = "kc.exchange_matching_pilot.assignment_results.v1"
EXCHANGE_ASSESSMENT_SCHEMA_VERSION = "kc.exchange_matching_pilot.assessment.v1"

TOP_K_DEFAULT = 5

_TITLE_PAREN_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")
_MULTI_COORDINATION_MARKERS = (" both ", " and ", " plus ", " together ", " also ")
_GENERIC_LABEL_TOKENS = {
    "algorithm",
    "algorithms",
    "class",
    "classes",
    "classification",
    "classifier",
    "classifiers",
    "criterion",
    "criteria",
    "decision",
    "ensemble",
    "evaluation",
    "index",
    "indices",
    "measure",
    "measures",
    "method",
    "methods",
    "metric",
    "metrics",
    "model",
    "models",
    "node",
    "nodes",
    "phase",
    "phases",
    "query",
    "rate",
    "rates",
    "sampling",
    "set",
    "sets",
    "split",
    "splits",
    "test",
    "testing",
    "training",
    "tree",
    "trees",
}

_DEFAULT_SOURCE_NOTE = (
    "Synthetic bounded pilot exchange authored for exchange-level KC matching validation because no durable "
    "dialogue/exchange artifact was found in the repo. This input is testing-only and leaves the reviewed/runtime "
    "baseline untouched."
)

DEFAULT_EXCHANGE_UNITS: list[dict[str, Any]] = [
    {
        "exchange_id": "EX01",
        "pilot_case_type": "straightforward_single",
        "student_text": "Is Bayes theorem what lets naive Bayes compute the most likely class from conditional probabilities?",
        "tutor_text": "Yes. Naive Bayes uses Bayes theorem to infer the posterior class probability.",
        "combined_exchange_text": "Student: Is Bayes theorem what lets naive Bayes compute the most likely class from conditional probabilities?\nTutor: Yes. Naive Bayes uses Bayes theorem to infer the posterior class probability.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Straightforward single-KC exchange about Bayes theorem.",
        "reference_kc_ids": ["KC_CLF_NB_001"],
    },
    {
        "exchange_id": "EX02",
        "pilot_case_type": "straightforward_single",
        "student_text": "In an ensemble, if each classifier votes and the label with the most votes wins, is that majority voting?",
        "tutor_text": "Yes, the ensemble prediction is based on majority voting across members.",
        "combined_exchange_text": "Student: In an ensemble, if each classifier votes and the label with the most votes wins, is that majority voting?\nTutor: Yes, the ensemble prediction is based on majority voting across members.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Straightforward single-KC exchange about majority voting.",
        "reference_kc_ids": ["KC_EVAL_ENS_002"],
    },
    {
        "exchange_id": "EX03",
        "pilot_case_type": "straightforward_single",
        "student_text": "Is F-measure the harmonic mean of precision and recall?",
        "tutor_text": "Exactly. It combines precision and recall into a single measure.",
        "combined_exchange_text": "Student: Is F-measure the harmonic mean of precision and recall?\nTutor: Exactly. It combines precision and recall into a single measure.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Straightforward single-KC exchange about F-measure.",
        "reference_kc_ids": ["KC_EVAL_BASIC_006"],
    },
    {
        "exchange_id": "EX04",
        "pilot_case_type": "straightforward_single",
        "student_text": "Is random forest just an ensemble of many decision trees?",
        "tutor_text": "Yes. Random forest combines many decision trees in an ensemble.",
        "combined_exchange_text": "Student: Is random forest just an ensemble of many decision trees?\nTutor: Yes. Random forest combines many decision trees in an ensemble.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Straightforward single-KC exchange about random forest.",
        "reference_kc_ids": ["KC_EVAL_ENS_003"],
    },
    {
        "exchange_id": "EX05",
        "pilot_case_type": "confident_multi",
        "student_text": "Should I report both recall and specificity, since recall is the true positive rate and specificity is the true negative rate?",
        "tutor_text": "Yes, both metrics can matter depending on the error profile.",
        "combined_exchange_text": "Student: Should I report both recall and specificity, since recall is the true positive rate and specificity is the true negative rate?\nTutor: Yes, both metrics can matter depending on the error profile.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Explicit two-KC exchange spanning recall and specificity.",
        "reference_kc_ids": ["KC_EVAL_BASIC_004", "KC_EVAL_BASIC_005"],
    },
    {
        "exchange_id": "EX06",
        "pilot_case_type": "ambiguous_family",
        "student_text": "I know decision trees need a split criterion at each node, but which impurity criterion is it?",
        "tutor_text": "Think about the common node impurity criteria for decision trees.",
        "combined_exchange_text": "Student: I know decision trees need a split criterion at each node, but which impurity criterion is it?\nTutor: Think about the common node impurity criteria for decision trees.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Family-confusion exchange that should surface decision-tree sibling ambiguity.",
        "reference_kc_ids": ["KC_CLF_DT_003", "KC_CLF_DT_004", "KC_CLF_DT_005", "KC_CLF_DT_008"],
    },
    {
        "exchange_id": "EX07",
        "pilot_case_type": "ambiguous_generic",
        "student_text": "I forgot the formula for that classification metric.",
        "tutor_text": "Think about the common classifier evaluation metrics and their formulas.",
        "combined_exchange_text": "Student: I forgot the formula for that classification metric.\nTutor: Think about the common classifier evaluation metrics and their formulas.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Generic under-specified exchange that should stay ambiguous.",
        "reference_kc_ids": ["KC_EVAL_BASIC_002", "KC_EVAL_BASIC_004", "KC_EVAL_BASIC_005", "KC_EVAL_BASIC_006"],
    },
    {
        "exchange_id": "EX08",
        "pilot_case_type": "no_match",
        "student_text": "How does k-means update centroids after assigning points to clusters?",
        "tutor_text": "It recomputes each centroid from the assigned points.",
        "combined_exchange_text": "Student: How does k-means update centroids after assigning points to clusters?\nTutor: It recomputes each centroid from the assigned points.",
        "source_note": _DEFAULT_SOURCE_NOTE,
        "pilot_design_intent": "Out-of-library exchange that should remain no-match on the reviewed slice48 baseline.",
        "reference_kc_ids": [],
    },
]


@dataclass(frozen=True)
class ExchangeMatchingPilotResult:
    output_dir: Path
    input_path: Path
    retrieval_results_path: Path
    retrieval_summary_path: Path
    assignment_results_path: Path
    assignment_summary_path: Path
    preview_path: Path
    assessment_summary_path: Path
    assessment_path: Path
    exchange_count: int


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


def _preview_snippet(text: str, *, limit: int = 160) -> str:
    compact = " ".join(_as_text(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _title_variants(text: str) -> list[str]:
    raw = _as_text(text)
    if not raw:
        return []
    variants = [raw]
    match = _TITLE_PAREN_RE.match(raw)
    if match:
        outer = match.group(1).strip()
        inner = match.group(2).strip()
        for value in [outer, inner, f"{outer} {inner}"]:
            if value and value not in variants:
                variants.append(value)
    return variants


def _distinctive_tokens(text: str) -> list[str]:
    tokens = tokenize(text, stopwords=None)
    return [token for token in tokens if token not in _GENERIC_LABEL_TOKENS]


def _title_mentioned_in_query(*, query_norm: str, query_tokens: set[str], record: Mapping[str, Any]) -> tuple[bool, str]:
    for label in [*_title_variants(_as_text(record.get("title"))), *_title_variants(_as_text(record.get("canonical_name")))]:
        label_norm = match_normalize(label)
        label_tokens = set(_distinctive_tokens(label))
        if not label_norm or not label_tokens:
            continue
        if label_norm in query_norm:
            return True, label
        if label_tokens.issubset(query_tokens):
            return True, label
    return False, ""


def _anchor_label(result: Mapping[str, Any]) -> str:
    basis = _as_text(result.get("matched_text_basis"))
    if ":" not in basis:
        return ""
    prefix, remainder = basis.split(":", 1)
    if prefix not in {"title_or_alias_contains", "title_or_alias_token_anchor"}:
        return ""
    return remainder.strip()


def _generic_anchor_from_ancestors(*, anchor_label: str, record: Mapping[str, Any]) -> bool:
    if not anchor_label:
        return False
    anchor_norm = match_normalize(anchor_label)
    if not anchor_norm:
        return False
    if not _distinctive_tokens(anchor_label):
        return True
    for label in _normalize_string_list(record.get("ancestor_labels")):
        if match_normalize(label) == anchor_norm:
            return True
    for label in _normalize_string_list(record.get("source_hierarchy_path"))[:-1]:
        if match_normalize(label) == anchor_norm:
            return True
    return False


def _evidence_refs(record: Mapping[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for span in list(record.get("evidence_spans") or [])[:limit]:
        refs.append(
            {
                "evidence_id": _as_text(span.get("evidence_id")),
                "doc_id": _as_text(span.get("doc_id")),
                "page_index": span.get("page_index"),
                "role": _as_text(span.get("role")),
                "block_id": _as_text(span.get("block_id")),
                "quote_preview": _preview_snippet(_as_text(span.get("quote"))),
            }
        )
    return refs


def _same_parent_close_results(results: Sequence[Mapping[str, Any]], *, parent_label: str, top_score: float) -> list[dict[str, Any]]:
    close_min = max(top_score * 0.82, top_score - 3.0)
    out: list[dict[str, Any]] = []
    for result in results:
        if _as_text(result.get("parent_label")) != parent_label:
            continue
        if float(result.get("score") or 0.0) < close_min:
            continue
        out.append(dict(result))
    return out


def _close_cluster_results(results: Sequence[Mapping[str, Any]], *, top_score: float, margin: float = 1.5) -> list[dict[str, Any]]:
    return [dict(result) for result in results if float(result.get("score") or 0.0) >= top_score - margin]


def _has_multi_coordination(query_norm: str) -> bool:
    query_text = f" {query_norm} "
    return any(marker in query_text for marker in _MULTI_COORDINATION_MARKERS)


def build_exchange_input_artifact(
    *,
    exchange_units: Sequence[Mapping[str, Any]],
    source_reviewed_set_id: str,
    source_runtime_set_id: str,
    retrieval_source_set_id: str,
    retrieval_index_set_id: str,
    top_k: int,
) -> dict[str, Any]:
    return {
        "schema_version": EXCHANGE_INPUT_SCHEMA_VERSION,
        "stage": EXCHANGE_MATCHING_STAGE,
        "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "top_k": top_k,
        "input_origin": "synthetic_bounded_pilot_input",
        "input_note": _DEFAULT_SOURCE_NOTE,
        "exchange_units": list(exchange_units),
    }


def build_exchange_retrieval_results(
    *,
    exchange_units: Sequence[Mapping[str, Any]],
    retrieval_records: Sequence[Mapping[str, Any]],
    index_package: Mapping[str, Any],
    top_k: int,
) -> list[dict[str, Any]]:
    record_by_kc = {_as_text(record.get("kc_id")): record for record in retrieval_records}
    rows: list[dict[str, Any]] = []
    for exchange in exchange_units:
        query_text = _as_text(exchange.get("combined_exchange_text"))
        query_norm = match_normalize(query_text)
        query_tokens = set(tokenize(query_text, stopwords=None))
        raw_results = run_query(query_text=query_text, records=retrieval_records, index_package=index_package, top_k=top_k)
        top_results: list[dict[str, Any]] = []
        for result in raw_results:
            record = record_by_kc.get(_as_text(result.get("kc_id")))
            _ensure(record is not None, f"Missing retrieval record for kc_id={result.get('kc_id')}")
            title_mentioned, matched_title_variant = _title_mentioned_in_query(query_norm=query_norm, query_tokens=query_tokens, record=record)
            anchor_label = _anchor_label(result)
            top_results.append(
                {
                    "kc_id": _as_text(result.get("kc_id")),
                    "title": _as_text(result.get("title")),
                    "canonical_name": _as_text(record.get("canonical_name")),
                    "rank": int(result.get("rank") or 0),
                    "score": float(result.get("score") or 0.0),
                    "score_components": dict(result.get("score_components") or {}),
                    "matched_terms": list(result.get("matched_terms") or []),
                    "matched_text_basis": _as_text(result.get("matched_text_basis")),
                    "matched_text_preview": _as_text(result.get("matched_text_preview")),
                    "title_mentioned_in_exchange": title_mentioned,
                    "matched_title_variant": matched_title_variant,
                    "anchor_label": anchor_label,
                    "anchor_is_generic_ancestor": _generic_anchor_from_ancestors(anchor_label=anchor_label, record=record),
                    "review_status": _as_text(result.get("review_status")),
                    "parent_label": _as_text(result.get("parent_label")),
                    "ancestor_labels": _normalize_string_list(record.get("ancestor_labels")),
                    "source_hierarchy_path": _normalize_string_list(result.get("source_hierarchy_path")),
                    "linked_evidence_ids": _normalize_string_list(result.get("linked_evidence_ids")),
                    "field_linked_evidence_ids": dict(record.get("field_linked_evidence_ids") or {}),
                    "source_document_ids": _normalize_string_list(result.get("source_document_ids")),
                    "runtime_entry_id": _as_text(result.get("runtime_entry_id")),
                    "source_run_refs": dict(record.get("source_run_refs") or {}),
                    "evidence_refs": _evidence_refs(record),
                }
            )
        rows.append(
            {
                "exchange_id": _as_text(exchange.get("exchange_id")),
                "pilot_case_type": _as_text(exchange.get("pilot_case_type")),
                "student_text": _as_text(exchange.get("student_text")),
                "tutor_text": _as_text(exchange.get("tutor_text")),
                "combined_exchange_text": query_text,
                "source_note": _as_text(exchange.get("source_note")),
                "pilot_design_intent": _as_text(exchange.get("pilot_design_intent")),
                "reference_kc_ids": _normalize_string_list(exchange.get("reference_kc_ids")),
                "top_results": top_results,
            }
        )
    return rows


def build_retrieval_summary(
    *,
    retrieval_rows: Sequence[Mapping[str, Any]],
    source_reviewed_set_id: str,
    source_runtime_set_id: str,
    retrieval_source_set_id: str,
    retrieval_index_set_id: str,
    top_k: int,
) -> dict[str, Any]:
    zero_hit_ids = [_as_text(row.get("exchange_id")) for row in retrieval_rows if not list(row.get("top_results") or [])]
    same_parent_collision_ids: list[str] = []
    for row in retrieval_rows:
        top_results = list(row.get("top_results") or [])
        if not top_results:
            continue
        top1 = top_results[0]
        parent_label = _as_text(top1.get("parent_label"))
        if not parent_label:
            continue
        close_results = _same_parent_close_results(top_results[:5], parent_label=parent_label, top_score=float(top1.get("score") or 0.0))
        if len(close_results) >= 2:
            same_parent_collision_ids.append(_as_text(row.get("exchange_id")))
    return {
        "schema_version": "1.0",
        "stage": EXCHANGE_MATCHING_STAGE,
        "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "top_k": top_k,
        "exchange_count": len(retrieval_rows),
        "exchange_ids_with_zero_hits": zero_hit_ids,
        "same_parent_collision_exchange_ids": same_parent_collision_ids,
        "max_results_per_exchange": max((len(list(row.get("top_results") or [])) for row in retrieval_rows), default=0),
        "exchanges_with_any_hits": sum(1 for row in retrieval_rows if list(row.get("top_results") or [])),
    }


def _dominant_kc(top_results: Sequence[Mapping[str, Any]]) -> str:
    if not top_results:
        return ""
    if len(top_results) == 1:
        return _as_text(top_results[0].get("kc_id"))
    top1 = float(top_results[0].get("score") or 0.0)
    top2 = float(top_results[1].get("score") or 0.0)
    return _as_text(top_results[0].get("kc_id")) if (top1 - top2) >= 1.5 else ""


def assign_exchange_matches(
    *,
    retrieval_rows: Sequence[Mapping[str, Any]],
    source_reviewed_set_id: str,
    source_runtime_set_id: str,
    retrieval_source_set_id: str,
    retrieval_index_set_id: str,
    top_k: int,
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for row in retrieval_rows:
        exchange_id = _as_text(row.get("exchange_id"))
        top_results = [dict(result) for result in list(row.get("top_results") or [])]
        combined_text = _as_text(row.get("combined_exchange_text"))
        query_norm = match_normalize(combined_text)
        label = "confident_single"
        assigned_kcs: list[str] = []
        plausible_kcs: list[str] = []
        dominant_kc = ""
        rationale = ""
        if not top_results:
            label = "no_match"
            rationale = "No reviewed-library retrieval hits were returned for this exchange."
        else:
            top1 = top_results[0]
            top_score = float(top1.get("score") or 0.0)
            explicit_results = [result for result in top_results if bool(result.get("title_mentioned_in_exchange")) and float(result.get("score") or 0.0) >= 8.0]
            explicit_multi_results = []
            if _has_multi_coordination(query_norm) and len(explicit_results) >= 2:
                multi_close_min = float(explicit_results[0].get("score") or 0.0) * 0.75
                explicit_multi_results = [
                    result for result in explicit_results if float(result.get("score") or 0.0) >= multi_close_min
                ]
            same_parent_close = _same_parent_close_results(top_results[:5], parent_label=_as_text(top1.get("parent_label")), top_score=top_score)
            close_cluster = _close_cluster_results(top_results[:5], top_score=top_score, margin=1.5)
            generic_top = bool(top1.get("anchor_is_generic_ancestor")) or (
                not bool(top1.get("title_mentioned_in_exchange")) and _as_text(top1.get("matched_text_basis")).startswith("lexical_overlap:")
            )
            weak_top = top_score < 6.5
            if len(explicit_multi_results) >= 2:
                label = "confident_multi"
                assigned_kcs = [_as_text(result.get("kc_id")) for result in explicit_multi_results]
                plausible_kcs = list(assigned_kcs)
                dominant_kc = _dominant_kc(explicit_multi_results)
                rationale = "Multiple KC titles are explicitly present in the exchange and each was retrieved with strong evidence."
            elif top_score < 4.25 and not bool(top1.get("title_mentioned_in_exchange")):
                label = "no_match"
                rationale = "Top retrieval support stayed too weak and no KC title was explicitly grounded in the exchange."
            elif (len(same_parent_close) >= 2 and (generic_top or not bool(top1.get("title_mentioned_in_exchange")))) or (weak_top and len(close_cluster) >= 3):
                label = "ambiguous"
                if len(same_parent_close) >= 2:
                    plausible_kcs = [_as_text(result.get("kc_id")) for result in same_parent_close[:4]]
                    rationale = "Top retrieval stayed inside a sibling/family cluster without enough leaf-specific separation."
                else:
                    plausible_kcs = [_as_text(result.get("kc_id")) for result in close_cluster[:5]]
                    rationale = "Top retrieval scores remained weak and clustered across generic alternatives."
            else:
                label = "confident_single"
                assigned_kcs = [_as_text(top1.get("kc_id"))]
                plausible_kcs = list(assigned_kcs)
                dominant_kc = _as_text(top1.get("kc_id"))
                rationale = "One KC is explicitly supported by the exchange surface and remains the strongest retrieved match."
        assignments.append(
            {
                "schema_version": EXCHANGE_ASSIGNMENT_SCHEMA_VERSION,
                "stage": EXCHANGE_MATCHING_STAGE,
                "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
                "source_reviewed_set_id": source_reviewed_set_id,
                "source_runtime_set_id": source_runtime_set_id,
                "retrieval_source_set_id": retrieval_source_set_id,
                "retrieval_index_set_id": retrieval_index_set_id,
                "top_k": top_k,
                "exchange_id": exchange_id,
                "pilot_case_type": _as_text(row.get("pilot_case_type")),
                "reference_kc_ids": _normalize_string_list(row.get("reference_kc_ids")),
                "assignment_label": label,
                "assigned_kc_ids": assigned_kcs,
                "plausible_kc_ids": plausible_kcs,
                "dominant_kc": dominant_kc,
                "rationale": rationale,
                "top_result_kc_id": _as_text(top_results[0].get("kc_id")) if top_results else "",
                "top_result_title": _as_text(top_results[0].get("title")) if top_results else "",
                "top_result_score": float(top_results[0].get("score") or 0.0) if top_results else 0.0,
                "top_result_basis": _as_text(top_results[0].get("matched_text_basis")) if top_results else "",
                "same_parent_top_kc_ids": [
                    _as_text(result.get("kc_id"))
                    for result in _same_parent_close_results(
                        top_results[:5],
                        parent_label=_as_text(top_results[0].get("parent_label")) if top_results else "",
                        top_score=float(top_results[0].get("score") or 0.0) if top_results else 0.0,
                    )
                ],
            }
        )
    return assignments


def build_assignment_summary(
    *,
    assignments: Sequence[Mapping[str, Any]],
    source_reviewed_set_id: str,
    source_runtime_set_id: str,
    retrieval_source_set_id: str,
    retrieval_index_set_id: str,
    top_k: int,
) -> dict[str, Any]:
    label_counts = {
        "confident_single": 0,
        "confident_multi": 0,
        "ambiguous": 0,
        "no_match": 0,
    }
    for row in assignments:
        label = _as_text(row.get("assignment_label"))
        if label in label_counts:
            label_counts[label] += 1
    return {
        "schema_version": "1.0",
        "stage": EXCHANGE_MATCHING_STAGE,
        "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "top_k": top_k,
        "exchange_count": len(assignments),
        "label_counts": label_counts,
        "confident_single_exchange_ids": [_as_text(row.get("exchange_id")) for row in assignments if _as_text(row.get("assignment_label")) == "confident_single"],
        "confident_multi_exchange_ids": [_as_text(row.get("exchange_id")) for row in assignments if _as_text(row.get("assignment_label")) == "confident_multi"],
        "ambiguous_exchange_ids": [_as_text(row.get("exchange_id")) for row in assignments if _as_text(row.get("assignment_label")) == "ambiguous"],
        "no_match_exchange_ids": [_as_text(row.get("exchange_id")) for row in assignments if _as_text(row.get("assignment_label")) == "no_match"],
    }


def build_assessment_summary(
    *,
    retrieval_rows: Sequence[Mapping[str, Any]],
    assignments: Sequence[Mapping[str, Any]],
    assignment_summary: Mapping[str, Any],
    source_reviewed_set_id: str,
    source_runtime_set_id: str,
    retrieval_source_set_id: str,
    retrieval_index_set_id: str,
) -> dict[str, Any]:
    assignment_by_exchange = {_as_text(row.get("exchange_id")): row for row in assignments}
    straightforward_exchange_ids = [
        _as_text(row.get("exchange_id"))
        for row in retrieval_rows
        if _as_text(row.get("pilot_case_type")) == "straightforward_single"
    ]
    straightforward_confident_ids = [
        exchange_id
        for exchange_id in straightforward_exchange_ids
        if _as_text((assignment_by_exchange.get(exchange_id) or {}).get("assignment_label")) == "confident_single"
    ]
    collision_rows = [
        row
        for row in assignments
        if list(row.get("same_parent_top_kc_ids") or []) and _as_text(row.get("assignment_label")) in {"ambiguous", "confident_multi"}
    ]
    bounded_ready = (
        len(straightforward_confident_ids) == len(straightforward_exchange_ids)
        and int((assignment_summary.get("label_counts") or {}).get("ambiguous") or 0) >= 1
        and int((assignment_summary.get("label_counts") or {}).get("no_match") or 0) >= 1
    )
    return {
        "schema_version": EXCHANGE_ASSESSMENT_SCHEMA_VERSION,
        "stage": EXCHANGE_MATCHING_STAGE,
        "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "q1_straightforward_matchable": {
            "answer": "yes" if len(straightforward_confident_ids) == len(straightforward_exchange_ids) else "mixed",
            "matched_exchange_ids": straightforward_confident_ids,
            "total_straightforward_exchanges": len(straightforward_exchange_ids),
        },
        "q2_sibling_family_collisions": {
            "exchange_ids": [_as_text(row.get("exchange_id")) for row in collision_rows],
            "details": [
                {
                    "exchange_id": _as_text(row.get("exchange_id")),
                    "assignment_label": _as_text(row.get("assignment_label")),
                    "same_parent_top_kc_ids": list(row.get("same_parent_top_kc_ids") or []),
                }
                for row in collision_rows
            ],
        },
        "q3_ambiguous_cases_exposed_honestly": {
            "answer": "yes" if int((assignment_summary.get("label_counts") or {}).get("ambiguous") or 0) >= 1 else "partial",
            "ambiguous_exchange_ids": list(assignment_summary.get("ambiguous_exchange_ids") or []),
            "no_match_exchange_ids": list(assignment_summary.get("no_match_exchange_ids") or []),
        },
        "q4_good_enough_for_bounded_next_segmentation": {
            "answer": "yes_bounded" if bounded_ready else "not_yet",
            "reason": (
                "Straightforward exchanges were matched cleanly while ambiguous and no-match cases remained visible instead of being forced."
                if bounded_ready
                else "The pilot still needs tighter bounded validation before it can justify the next segmentation layer."
            ),
        },
    }


def build_preview_markdown(
    *,
    retrieval_rows: Sequence[Mapping[str, Any]],
    assignments: Sequence[Mapping[str, Any]],
    assignment_summary: Mapping[str, Any],
) -> str:
    assignment_by_exchange = {_as_text(row.get("exchange_id")): row for row in assignments}
    label_counts = dict(assignment_summary.get("label_counts") or {})
    lines = [
        "# KC Exchange Matching Pilot Preview",
        "",
        f"- Exchange count: `{assignment_summary.get('exchange_count')}`",
        f"- Label counts: `{label_counts}`",
        "",
    ]
    for row in retrieval_rows:
        exchange_id = _as_text(row.get("exchange_id"))
        assignment = assignment_by_exchange.get(exchange_id) or {}
        lines.extend(
            [
                f"## {exchange_id} - {_as_text(row.get('pilot_case_type'))}",
                "",
                f"- Assignment label: `{_as_text(assignment.get('assignment_label'))}`",
                f"- Dominant KC: `{_as_text(assignment.get('dominant_kc')) or 'none'}`",
                f"- Rationale: {_as_text(assignment.get('rationale'))}",
                f"- Exchange text: `{_preview_snippet(_as_text(row.get('combined_exchange_text')), limit=220)}`",
                "",
            ]
        )
        for result in list(row.get("top_results") or [])[:3]:
            evidence_refs = list(result.get("evidence_refs") or [])
            evidence_note = ", ".join(
                f"{_as_text(ref.get('doc_id'))}:p{ref.get('page_index')}:{_as_text(ref.get('role'))}"
                for ref in evidence_refs[:2]
            )
            lines.extend(
                [
                    f"### Rank {result.get('rank')} - {_as_text(result.get('kc_id'))} ({_as_text(result.get('title'))})",
                    "",
                    f"- Score: `{result.get('score')}`",
                    f"- Matched basis: `{_as_text(result.get('matched_text_basis'))}`",
                    f"- Matched terms: `{list(result.get('matched_terms') or [])}`",
                    f"- Title mentioned in exchange: `{bool(result.get('title_mentioned_in_exchange'))}`",
                    f"- Evidence refs: `{evidence_note or 'none'}`",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def build_assessment_markdown(
    *,
    assignment_summary: Mapping[str, Any],
    assessment_summary: Mapping[str, Any],
) -> str:
    q1 = dict(assessment_summary.get("q1_straightforward_matchable") or {})
    q2 = dict(assessment_summary.get("q2_sibling_family_collisions") or {})
    q3 = dict(assessment_summary.get("q3_ambiguous_cases_exposed_honestly") or {})
    q4 = dict(assessment_summary.get("q4_good_enough_for_bounded_next_segmentation") or {})
    lines = [
        "# KC Exchange Matching Pilot Assessment",
        "",
        f"- Label counts: `{dict(assignment_summary.get('label_counts') or {})}`",
        "",
        "## 1. Straightforward exchanges matchable?",
        "",
        f"- Answer: `{_as_text(q1.get('answer'))}`",
        f"- Confident straightforward exchange ids: `{list(q1.get('matched_exchange_ids') or [])}` / `{q1.get('total_straightforward_exchanges')}`",
        "",
        "## 2. Where do sibling/family collisions still surface?",
        "",
        f"- Exchange ids: `{list(q2.get('exchange_ids') or [])}`",
        "",
        "## 3. Are ambiguous cases being exposed honestly?",
        "",
        f"- Answer: `{_as_text(q3.get('answer'))}`",
        f"- Ambiguous exchange ids: `{list(q3.get('ambiguous_exchange_ids') or [])}`",
        f"- No-match exchange ids: `{list(q3.get('no_match_exchange_ids') or [])}`",
        "",
        "## 4. Good enough for the next segmentation step on a bounded basis?",
        "",
        f"- Answer: `{_as_text(q4.get('answer'))}`",
        f"- Reason: {_as_text(q4.get('reason'))}",
        "",
        "## Blunt Read",
        "",
        (
            "- The accepted reviewed-only retrieval stack looks good enough for bounded exchange-to-KC continuation work because easy cases land cleanly and harder cases stay visible as ambiguous/no-match instead of being silently overclaimed."
            if _as_text(q4.get("answer")) == "yes_bounded"
            else "- The pilot surfaced too much uncertainty to justify even bounded downstream continuation without another narrow check."
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


def assemble_exchange_matching_pilot(
    *,
    retrieval_source_path: Path,
    retrieval_index_path: Path,
    output_dir: Path,
    source_reviewed_set_id: str,
    source_runtime_set_id: str,
    retrieval_source_set_id: str,
    retrieval_index_set_id: str,
    top_k: int = TOP_K_DEFAULT,
) -> ExchangeMatchingPilotResult:
    retrieval_source_path = retrieval_source_path.resolve()
    retrieval_index_path = retrieval_index_path.resolve()
    output_dir = output_dir.resolve()

    retrieval_records = read_jsonl(retrieval_source_path)
    index_package = read_json(retrieval_index_path)
    exchange_units = list(DEFAULT_EXCHANGE_UNITS)

    input_artifact = build_exchange_input_artifact(
        exchange_units=exchange_units,
        source_reviewed_set_id=source_reviewed_set_id,
        source_runtime_set_id=source_runtime_set_id,
        retrieval_source_set_id=retrieval_source_set_id,
        retrieval_index_set_id=retrieval_index_set_id,
        top_k=top_k,
    )
    retrieval_rows = build_exchange_retrieval_results(
        exchange_units=exchange_units,
        retrieval_records=retrieval_records,
        index_package=index_package,
        top_k=top_k,
    )
    retrieval_results_artifact = {
        "schema_version": EXCHANGE_RETRIEVAL_SCHEMA_VERSION,
        "stage": EXCHANGE_MATCHING_STAGE,
        "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "top_k": top_k,
        "retrieval_results": retrieval_rows,
    }
    retrieval_summary = build_retrieval_summary(
        retrieval_rows=retrieval_rows,
        source_reviewed_set_id=source_reviewed_set_id,
        source_runtime_set_id=source_runtime_set_id,
        retrieval_source_set_id=retrieval_source_set_id,
        retrieval_index_set_id=retrieval_index_set_id,
        top_k=top_k,
    )
    assignments = assign_exchange_matches(
        retrieval_rows=retrieval_rows,
        source_reviewed_set_id=source_reviewed_set_id,
        source_runtime_set_id=source_runtime_set_id,
        retrieval_source_set_id=retrieval_source_set_id,
        retrieval_index_set_id=retrieval_index_set_id,
        top_k=top_k,
    )
    assignment_results_artifact = {
        "schema_version": EXCHANGE_ASSIGNMENT_SCHEMA_VERSION,
        "stage": EXCHANGE_MATCHING_STAGE,
        "rule_version": EXCHANGE_MATCHING_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "retrieval_source_set_id": retrieval_source_set_id,
        "retrieval_index_set_id": retrieval_index_set_id,
        "top_k": top_k,
        "assignments": assignments,
    }
    assignment_summary = build_assignment_summary(
        assignments=assignments,
        source_reviewed_set_id=source_reviewed_set_id,
        source_runtime_set_id=source_runtime_set_id,
        retrieval_source_set_id=retrieval_source_set_id,
        retrieval_index_set_id=retrieval_index_set_id,
        top_k=top_k,
    )
    assessment_summary = build_assessment_summary(
        retrieval_rows=retrieval_rows,
        assignments=assignments,
        assignment_summary=assignment_summary,
        source_reviewed_set_id=source_reviewed_set_id,
        source_runtime_set_id=source_runtime_set_id,
        retrieval_source_set_id=retrieval_source_set_id,
        retrieval_index_set_id=retrieval_index_set_id,
    )
    preview_md = build_preview_markdown(
        retrieval_rows=retrieval_rows,
        assignments=assignments,
        assignment_summary=assignment_summary,
    )
    assessment_md = build_assessment_markdown(
        assignment_summary=assignment_summary,
        assessment_summary=assessment_summary,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "exchange_unit_pilot_input.json"
    retrieval_results_path = output_dir / "exchange_topk_retrieval_results.json"
    retrieval_summary_path = output_dir / "exchange_topk_retrieval_summary.json"
    assignment_results_path = output_dir / "exchange_assignment_results.json"
    assignment_summary_path = output_dir / "exchange_assignment_summary.json"
    preview_path = output_dir / "exchange_matching_preview.md"
    assessment_summary_path = output_dir / "pilot_assessment_summary.json"
    assessment_path = output_dir / "pilot_assessment.md"

    write_json(input_path, input_artifact)
    write_json(retrieval_results_path, retrieval_results_artifact)
    write_json(retrieval_summary_path, retrieval_summary)
    write_json(assignment_results_path, assignment_results_artifact)
    write_json(assignment_summary_path, assignment_summary)
    preview_path.write_text(preview_md, encoding="utf-8")
    write_json(assessment_summary_path, assessment_summary)
    assessment_path.write_text(assessment_md, encoding="utf-8")

    return ExchangeMatchingPilotResult(
        output_dir=output_dir,
        input_path=input_path,
        retrieval_results_path=retrieval_results_path,
        retrieval_summary_path=retrieval_summary_path,
        assignment_results_path=assignment_results_path,
        assignment_summary_path=assignment_summary_path,
        preview_path=preview_path,
        assessment_summary_path=assessment_summary_path,
        assessment_path=assessment_path,
        exchange_count=len(exchange_units),
    )
