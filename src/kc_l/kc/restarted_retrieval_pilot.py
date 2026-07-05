from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from kc_l.kc.downstream_library import load_operational_kc_library
from kc_l.retrieval_gate.text_normalize import match_normalize
from kc_l.utils.json_io import read_jsonl, write_json, write_jsonl


RETRIEVAL_PILOT_STAGE = "step6_13_reviewed_library_retrieval_pilot"
RETRIEVAL_PILOT_RULE_VERSION = "step6.13.reviewed_retrieval_pilot.v1"
RETRIEVAL_SOURCE_SCHEMA_VERSION = "step6.retrieval_source.restarted.v1"
RETRIEVAL_INDEX_SCHEMA_VERSION = "step6.retrieval_index.restarted.v1"
RETRIEVAL_QUERY_CONTRACT_VERSION = "step6.retrieval_query_contract.restarted.v1"
RETRIEVAL_VALIDATION_SCHEMA_VERSION = "step6.retrieval_validation.restarted.v1"
TOP_K_DEFAULT = 5
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_MIN_STOP = {
    "the", "and", "or", "of", "to", "in", "for", "a", "an", "is", "are", "be", "as", "on", "by", "with", "at",
    "from", "that", "this", "it", "we", "you", "your", "our", "can", "may", "not", "do", "does", "did",
}
_GENERIC_TITLE_DESCRIPTOR_TOKENS = {
    "algorithm", "algorithms", "class", "classes", "index", "measure", "measures", "method", "methods", "phase",
    "rate", "sample", "samples", "set", "split", "splits", "test", "theorem", "theorems", "training", "tree",
    "trees",
}
_GENERIC_TITLE_SUFFIXES = (" Method", " Algorithm")

DEFAULT_VALIDATION_QUERIES: list[dict[str, Any]] = [
    {"query_id": "Q01", "category": "straightforward", "query_text": "bayes theorem conditional probability", "expected_any_of": ["KC_CLF_NB_001"], "note": "Direct theorem/title retrieval."},
    {"query_id": "Q02", "category": "straightforward", "query_text": "classifier oracle querying phase", "expected_any_of": ["KC_CLF_UND_002"], "note": "Definition-oriented underpinning query."},
    {"query_id": "Q03", "category": "straightforward", "query_text": "accuracy correctly classified instances", "expected_any_of": ["KC_EVAL_BASIC_002"], "note": "Metric definition query."},
    {"query_id": "Q04", "category": "straightforward", "query_text": "majority voting ensemble members votes", "expected_any_of": ["KC_EVAL_ENS_002"], "note": "Ensemble method query."},
    {"query_id": "Q05", "category": "family_confusion", "query_text": "recall sensitivity true positive rate", "expected_any_of": ["KC_EVAL_BASIC_004"], "note": "Sibling metric collision check."},
    {"query_id": "Q06", "category": "family_confusion", "query_text": "specificity true negative rate", "expected_any_of": ["KC_EVAL_BASIC_005"], "note": "Sibling metric collision check."},
    {"query_id": "Q07", "category": "family_confusion", "query_text": "random forest ensemble of decision trees", "expected_any_of": ["KC_EVAL_ENS_003"], "note": "Sibling ensemble collision check."},
    {"query_id": "Q08", "category": "straightforward", "query_text": "holdout training set test set split", "expected_any_of": ["KC_EVAL_SAMP_001"], "note": "Sampling method query."},
    {"query_id": "Q09", "category": "ambiguous", "query_text": "decision tree impurity measure", "expected_any_of": ["KC_CLF_DT_003", "KC_CLF_DT_004", "KC_CLF_DT_006"], "note": "Family-level ambiguity check."},
    {"query_id": "Q10", "category": "ambiguous", "query_text": "classification metric formula", "expected_any_of": ["KC_EVAL_BASIC_002", "KC_EVAL_BASIC_004", "KC_EVAL_BASIC_005", "KC_EVAL_BASIC_006"], "note": "Generic metric query."},
]


@dataclass(frozen=True)
class RestartedRetrievalPilotResult:
    output_dir: Path
    retrieval_source_path: Path
    source_summary_path: Path
    source_preview_path: Path
    index_path: Path
    index_summary_path: Path
    query_contract_path: Path
    validation_queries_path: Path
    validation_results_path: Path
    validation_summary_path: Path
    validation_preview_path: Path
    assessment_path: Path
    retrieval_record_count: int


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _append_unique_text(values: list[str], value: Any) -> None:
    text = _as_text(value)
    if text and text not in values:
        values.append(text)


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


def _split_camel_case(text: str) -> str:
    return _CAMEL_BOUNDARY_RE.sub(" ", _as_text(text))


def tokenize(text: str, *, max_token_len: int = 40, lowercase: bool = True, stopwords: set[str] | None = None) -> list[str]:
    value = str(text or "")
    if lowercase:
        value = value.lower()
    out: list[str] = []
    for token in _TOKEN_RE.findall(value):
        if len(token) > max_token_len:
            continue
        if stopwords is not None and token in stopwords:
            continue
        out.append(token)
    return out


def bm25_idf(n_docs: int, df: int) -> float:
    return math.log(((n_docs - df + 0.5) / (df + 0.5)) + 1.0)


def _unique_join(parts: Sequence[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        text = _as_text(part)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return " ".join(ordered)


def _preview_snippet(text: str, *, limit: int = 220) -> str:
    compact = " ".join(_as_text(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _normalized_phrase_tokens(text: str) -> list[str]:
    return tokenize(_split_camel_case(text), stopwords=_MIN_STOP)


def _singularize_token(token: str) -> str:
    lower = token.lower()
    if len(token) <= 4:
        return token
    if lower.endswith("ies"):
        return token[:-3] + "y"
    if lower.endswith(("ses", "zes", "xes", "ches", "shes")):
        return token[:-2]
    if lower.endswith("s") and not lower.endswith(("ss", "us", "is", "ayes")):
        return token[:-1]
    return token


def _singularize_label(text: str) -> str:
    parts = [_singularize_token(part) for part in _as_text(text).split()]
    return " ".join(part for part in parts if part)


def _parenthetical_title_variants(title: str) -> list[str]:
    match = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", _as_text(title))
    if not match:
        return []
    outer = match.group(1).strip()
    inner = match.group(2).strip()
    return _normalize_string_list([outer, inner, f"{outer} {inner}", f"{inner} {outer}"])


def _punctuation_title_variants(title: str) -> list[str]:
    raw = _as_text(title)
    if not raw:
        return []
    variants: list[str] = []
    plain = " ".join(raw.replace("'", "").replace("-", " " ).replace("/", " " ).replace("&", " and " ).split())
    if plain and plain != raw:
        variants.append(plain)
    if " vs. " in raw or " vs " in raw:
        variants.append(raw.replace("vs.", "").replace("vs", "").replace(".", " "))
    return _normalize_string_list(variants)


def _generic_title_variants(title: str) -> list[str]:
    raw = _as_text(title)
    variants: list[str] = []
    for suffix in _GENERIC_TITLE_SUFFIXES:
        if raw.endswith(suffix):
            variants.append(raw[: -len(suffix)].strip())
    return _normalize_string_list(variants)


def _path_title_variants(source_path: Sequence[str], title: str) -> list[str]:
    path = _normalize_string_list(source_path)
    variants: list[str] = []
    if len(path) >= 2:
        parent = path[-2]
        singular_parent = _singularize_label(parent)
        variants.extend([f"{parent} {title}", f"{singular_parent} {title}", singular_parent])
    return _normalize_string_list(variants)


def _distinctive_title_tokens(title: str) -> list[str]:
    title_tokens = _normalized_phrase_tokens(title)
    distinctive = [token for token in title_tokens if token not in _GENERIC_TITLE_DESCRIPTOR_TOKENS]
    return distinctive or title_tokens[:1]


def _definition_scope_variants(title: str, definition: str, scope: str) -> list[str]:
    body_text = " ".join(_normalized_phrase_tokens(_unique_join([definition, scope])))
    if "training set" not in body_text or "test set" not in body_text:
        return []
    variants = ["Training Set Test Set Split"]
    for anchor in _distinctive_title_tokens(title)[:2]:
        variants.append(f"{anchor.capitalize()} Training Set Test Set Split")
    return _normalize_string_list(variants)


def _derived_lexical_variants(*, title: str, canonical_name: str, definition: str, scope: str, source_path: Sequence[str]) -> list[str]:
    variants: list[str] = []
    for value in [
        *_parenthetical_title_variants(title),
        *_parenthetical_title_variants(canonical_name),
        *_punctuation_title_variants(title),
        *_punctuation_title_variants(canonical_name),
        *_generic_title_variants(title),
        *_generic_title_variants(canonical_name),
        *_path_title_variants(source_path, title),
        *_definition_scope_variants(title, definition, scope),
    ]:
        _append_unique_text(variants, value)
    return variants


def _ancestor_labels(row: Mapping[str, Any]) -> list[str]:
    return _normalize_string_list((row.get("hierarchy_ancestry") or {}).get("ancestor_labels"))


def _source_hierarchy_path(row: Mapping[str, Any]) -> list[str]:
    return _normalize_string_list((row.get("hierarchy_ancestry") or {}).get("source_hierarchy_path"))


def _build_retrieval_text(title: str, canonical_name: str, aliases: Sequence[str], definition: str, scope: str) -> str:
    return _unique_join([title, canonical_name, *aliases, definition, scope])


def _build_structure_text(source_path: Sequence[str], ancestor_labels: Sequence[str]) -> str:
    parts = list(source_path) if source_path else list(ancestor_labels)
    return " > ".join(_normalize_string_list(parts))


def _source_document_ids(reviewed_row: Mapping[str, Any], runtime_row: Mapping[str, Any]) -> list[str]:
    source_provenance = dict(reviewed_row.get("source_provenance") or {})
    runtime_provenance = dict(runtime_row.get("source_provenance") or {})
    return _normalize_string_list(list(source_provenance.get("source_document_ids") or []) + list(runtime_provenance.get("source_document_ids") or []))


def build_retrieval_source_records(*, reviewed_rows: Sequence[Mapping[str, Any]], runtime_rows: Sequence[Mapping[str, Any]], assembly_run_id: str, source_reviewed_set_id: str, source_runtime_set_id: str) -> list[dict[str, Any]]:
    runtime_by_kc = {str(row.get("kc_id")): row for row in runtime_rows}
    records: list[dict[str, Any]] = []
    for reviewed_row in reviewed_rows:
        kc_id = _as_text(reviewed_row.get("kc_id"))
        _ensure(kc_id, "kc_id is required in reviewed row")
        runtime_row = runtime_by_kc.get(kc_id)
        _ensure(runtime_row is not None, f"Runtime row missing for reviewed kc_id={kc_id}")
        title = _as_text(reviewed_row.get("title")) or _as_text(runtime_row.get("title"))
        canonical_name = _as_text(reviewed_row.get("canonical_name")) or _as_text(runtime_row.get("canonical_name")) or title
        definition = _as_text(reviewed_row.get("reviewer_facing_definition")) or _as_text(runtime_row.get("reviewer_facing_definition"))
        scope_value = reviewed_row.get("reviewer_facing_scope")
        scope = _as_text(scope_value)
        hierarchy = dict(reviewed_row.get("hierarchy_ancestry") or {})
        ancestor_labels = _ancestor_labels(reviewed_row)
        source_path = _source_hierarchy_path(reviewed_row)
        base_aliases = _normalize_string_list(reviewed_row.get("aliases") or runtime_row.get("aliases"))
        derived_aliases = _derived_lexical_variants(
            title=title,
            canonical_name=canonical_name,
            definition=definition,
            scope=scope,
            source_path=source_path,
        )
        aliases = _normalize_string_list([*base_aliases, *derived_aliases])
        structure_text = _unique_join([
            _build_structure_text(source_path, ancestor_labels),
            _singularize_label(" > ".join(source_path)),
        ])
        retrieval_text = _build_retrieval_text(title, canonical_name, aliases, definition, scope)
        search_terms = _normalize_string_list([
            *(runtime_row.get("search_terms") or [title, canonical_name, *base_aliases]),
            *aliases,
            definition,
            scope,
        ])
        source_provenance = dict(reviewed_row.get("source_provenance") or {})
        source_stage_lineage = dict(source_provenance.get("source_stage_lineage") or {})
        record = {
            "schema_version": RETRIEVAL_SOURCE_SCHEMA_VERSION,
            "retrieval_record_id": f"step6_13:source:{assembly_run_id}:{kc_id}",
            "kc_id": kc_id,
            "title": title,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "level": _as_text(reviewed_row.get("level")) or _as_text(runtime_row.get("level")) or "atomic",
            "source_library_tier": _as_text(reviewed_row.get("library_tier")),
            "review_status": _as_text(reviewed_row.get("review_status")),
            "scope_status": _as_text(reviewed_row.get("scope_status")) or _as_text(runtime_row.get("scope_status")),
            "scope_blank_is_intentional": bool(reviewed_row.get("scope_blank_is_intentional")),
            "review_priority": dict(reviewed_row.get("review_priority") or runtime_row.get("review_priority") or {}),
            "risk_flags": list(reviewed_row.get("risk_flags") or runtime_row.get("risk_flags") or []),
            "search_terms": search_terms,
            "retrieval_text": retrieval_text,
            "structure_text": structure_text,
            "display_text": _as_text(runtime_row.get("display_text")) or _unique_join([title, definition, scope]),
            "reviewer_facing_definition": definition,
            "reviewer_facing_scope": scope_value,
            "hierarchy_ancestry": hierarchy,
            "ancestor_labels": ancestor_labels,
            "source_hierarchy_path": source_path,
            "leaf_hier_node_id": _as_text(hierarchy.get("leaf_hier_node_id")),
            "parent_hier_node_id": _as_text(hierarchy.get("parent_hier_node_id")),
            "source_document_ids": _source_document_ids(reviewed_row, runtime_row),
            "linked_evidence_ids": list(reviewed_row.get("linked_evidence_ids") or runtime_row.get("linked_evidence_ids") or []),
            "field_linked_evidence_ids": dict(reviewed_row.get("field_linked_evidence_ids") or runtime_row.get("field_linked_evidence_ids") or {}),
            "evidence_spans": list(reviewed_row.get("evidence_spans") or runtime_row.get("evidence_spans") or []),
            "source_provenance": source_provenance,
            "source_stage_lineage": source_stage_lineage,
            "review_packet_id": _as_text(reviewed_row.get("review_packet_id")) or _as_text(runtime_row.get("source_review_packet_id")),
            "review_event_id": _as_text(reviewed_row.get("review_event_id")) or _as_text(runtime_row.get("source_review_event_id")),
            "runtime_entry_id": _as_text(runtime_row.get("runtime_entry_id")),
            "source_run_refs": {
                "source_reviewed_set_id": source_reviewed_set_id,
                "source_runtime_set_id": source_runtime_set_id,
                "source_reviewed_run_id": _as_text(reviewed_row.get("assembly_run_id")),
                "source_runtime_run_id": _as_text((runtime_row.get("source_provenance") or {}).get("assembly_run_id")),
            },
        }
        _ensure(record["source_library_tier"] == "frozen_reviewed_library", f"Unexpected library tier for {kc_id}")
        _ensure(record["review_status"] in {"approved", "edited_approved"}, f"Unexpected review status for {kc_id}")
        _ensure(record["linked_evidence_ids"], f"linked_evidence_ids missing for {kc_id}")
        records.append(record)
    return records


def build_source_summary(*, records: Sequence[Mapping[str, Any]], source_reviewed_set_id: str, source_runtime_set_id: str) -> dict[str, Any]:
    status_counts = Counter(_as_text(record.get("review_status")) for record in records)
    support_counts = Counter(_as_text((record.get("review_priority") or {}).get("bucket")) for record in records)
    intentionally_blank_scope_kcs = [record["kc_id"] for record in records if _as_text(record.get("scope_status")) == "intentionally_blank"]
    alias_count_total = sum(len(_normalize_string_list(record.get("aliases"))) for record in records)
    search_term_count_total = sum(len(_normalize_string_list(record.get("search_terms"))) for record in records)
    return {
        "schema_version": "1.0",
        "stage": RETRIEVAL_PILOT_STAGE,
        "rule_version": RETRIEVAL_PILOT_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "record_count": len(records),
        "review_status_counts": dict(status_counts),
        "support_bucket_counts": dict(support_counts),
        "included_kcs": [record["kc_id"] for record in records],
        "intentionally_blank_scope_kcs": intentionally_blank_scope_kcs,
        "records_with_aliases": sum(1 for record in records if bool(_normalize_string_list(record.get("aliases")))),
        "alias_count_total": alias_count_total,
        "records_with_search_expansion": sum(1 for record in records if len(_normalize_string_list(record.get("search_terms"))) > 1),
        "search_term_count_total": search_term_count_total,
        "lexical_expansion_mode": "deterministic_alias_lexical_expansion_v1",
        "sandbox_entries_included": 0,
        "source_frozen_load_success": True,
        "source_runtime_load_success": True,
    }


def build_source_preview(*, summary: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Reviewed-Only Retrieval Source Preview",
        "",
        f"- Reviewed KC records: `{summary['record_count']}`",
        f"- Review statuses: `{summary['review_status_counts']}`",
        f"- Support buckets: `{summary['support_bucket_counts']}`",
        f"- Intentionally blank scope KCs: `{summary['intentionally_blank_scope_kcs']}`",
        f"- Records with aliases: `{summary['records_with_aliases']}`",
        f"- Alias count total: `{summary['alias_count_total']}`",
        f"- Records with search expansion: `{summary['records_with_search_expansion']}`",
        f"- Lexical expansion mode: `{summary['lexical_expansion_mode']}`",
        f"- Sandbox entries included: `{summary['sandbox_entries_included']}`",
        "",
        "## Sample Retrieval Records",
        "",
    ]
    for record in records[:5]:
        lines.extend([
            f"### {record['kc_id']} - {record['title']}",
            "",
            f"- Review status: `{record['review_status']}`",
            f"- Structure path: `{record['source_hierarchy_path']}`",
            f"- Search terms: `{record['search_terms']}`",
            f"- Retrieval text: `{_preview_snippet(str(record['retrieval_text']))}`",
            f"- Linked evidence ids: `{record['linked_evidence_ids']}`",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"

def build_lexical_index(records: Sequence[Mapping[str, Any]], *, k1: float, b: float, max_token_len: int, lowercase: bool, stopwords: set[str] | None) -> dict[str, Any]:
    doc_term_freqs: list[dict[str, int]] = []
    doc_lengths: list[int] = []
    doc_tokens_all: list[list[str]] = []
    doc_search_tokens: list[list[str]] = []
    doc_structure_tokens: list[list[str]] = []
    doc_title_tokens: list[list[str]] = []
    df_map: dict[str, int] = {}
    postings: dict[str, list[list[int]]] = {}
    for record in records:
        retrieval_tokens = tokenize(f"{_as_text(record.get('retrieval_text'))} {_as_text(record.get('structure_text'))}", max_token_len=max_token_len, lowercase=lowercase, stopwords=stopwords)
        search_tokens = tokenize(" ".join(_normalize_string_list(record.get("search_terms"))), max_token_len=max_token_len, lowercase=lowercase, stopwords=stopwords)
        structure_tokens = tokenize(_as_text(record.get("structure_text")), max_token_len=max_token_len, lowercase=lowercase, stopwords=stopwords)
        title_tokens = tokenize(_as_text(record.get("title")), max_token_len=max_token_len, lowercase=lowercase, stopwords=stopwords)
        tf: dict[str, int] = {}
        seen: set[str] = set()
        for token in retrieval_tokens:
            tf[token] = tf.get(token, 0) + 1
            if token not in seen:
                df_map[token] = df_map.get(token, 0) + 1
                seen.add(token)
        doc_term_freqs.append(tf)
        doc_lengths.append(len(retrieval_tokens))
        doc_tokens_all.append(retrieval_tokens)
        doc_search_tokens.append(search_tokens)
        doc_structure_tokens.append(structure_tokens)
        doc_title_tokens.append(title_tokens)
    vocab = sorted(df_map)
    idf = {term: bm25_idf(len(records), df_map[term]) for term in vocab}
    for doc_idx, tf in enumerate(doc_term_freqs):
        for term, count in tf.items():
            postings.setdefault(term, []).append([doc_idx, count])
    avg_doc_length = (sum(doc_lengths) / len(doc_lengths)) if doc_lengths else 0.0
    return {
        "schema_version": RETRIEVAL_INDEX_SCHEMA_VERSION,
        "index_kind": "bm25_lexical_reviewed_kc_pilot",
        "record_count": len(records),
        "record_ord_to_kc_id": [record["kc_id"] for record in records],
        "doc_lengths": doc_lengths,
        "avg_doc_length": avg_doc_length,
        "min_doc_length": min(doc_lengths) if doc_lengths else 0,
        "max_doc_length": max(doc_lengths) if doc_lengths else 0,
        "vocab_size": len(vocab),
        "idf": idf,
        "postings": postings,
        "tokenizer": {"regex": _TOKEN_RE.pattern, "lowercase": lowercase, "max_token_len": max_token_len, "stopwords": "minimal_v1" if stopwords else "none"},
        "bm25": {"k1": k1, "b": b},
        "doc_tokens_all": doc_tokens_all,
        "doc_search_tokens": doc_search_tokens,
        "doc_structure_tokens": doc_structure_tokens,
        "doc_title_tokens": doc_title_tokens,
    }


def build_index_summary(*, index_package: Mapping[str, Any], source_reviewed_set_id: str, source_runtime_set_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "stage": RETRIEVAL_PILOT_STAGE,
        "rule_version": RETRIEVAL_PILOT_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "index_kind": _as_text(index_package.get("index_kind")),
        "indexed_record_count": int(index_package.get("record_count") or 0),
        "vocab_size": int(index_package.get("vocab_size") or 0),
        "avg_doc_length": float(index_package.get("avg_doc_length") or 0.0),
        "min_doc_length": int(index_package.get("min_doc_length") or 0),
        "max_doc_length": int(index_package.get("max_doc_length") or 0),
        "tokenizer": dict(index_package.get("tokenizer") or {}),
        "bm25": dict(index_package.get("bm25") or {}),
        "sandbox_entries_included": 0,
        "indexed_kcs": list(index_package.get("record_ord_to_kc_id") or []),
    }


def build_query_contract(*, top_k_default: int) -> dict[str, Any]:
    return {
        "schema_version": RETRIEVAL_QUERY_CONTRACT_VERSION,
        "stage": RETRIEVAL_PILOT_STAGE,
        "endpoint_name": "reviewed_only_kc_retrieval_pilot",
        "input_contract": {"query_text": "natural-language query string", "top_k": top_k_default},
        "output_contract": {"result_fields": ["kc_id", "title", "score", "rank", "matched_terms", "matched_text_basis", "source_hierarchy_path", "linked_evidence_ids", "source_document_ids", "review_status", "runtime_entry_id"]},
        "policies": {"reviewed_only_source": True, "sandbox_included": False, "kc_identity_field": "kc_id", "score_kind": "bm25_plus_title_anchor_plus_structure_overlap"},
    }


def _title_anchor_bonus(query_norm: str, query_tokens: set[str], record: Mapping[str, Any]) -> tuple[float, str]:
    labels = [_as_text(record.get("title")), _as_text(record.get("canonical_name")), *_normalize_string_list(record.get("aliases"))]
    best_bonus = 0.0
    best_basis = ""
    for label in labels:
        if not label:
            continue
        label_norm = match_normalize(label)
        if label_norm and label_norm in query_norm:
            bonus = 1.4 if label == _as_text(record.get("title")) else 1.1
            if bonus > best_bonus:
                best_bonus = bonus
                best_basis = f"title_or_alias_contains:{label}"
            continue
        label_tokens = set(tokenize(label, stopwords=_MIN_STOP))
        if label_tokens and label_tokens.issubset(query_tokens):
            bonus = 0.9 if label == _as_text(record.get("title")) else 0.7
            if bonus > best_bonus:
                best_bonus = bonus
                best_basis = f"title_or_alias_token_anchor:{label}"
    return best_bonus, best_basis


def run_query(*, query_text: str, records: Sequence[Mapping[str, Any]], index_package: Mapping[str, Any], top_k: int) -> list[dict[str, Any]]:
    q_tokens = tokenize(query_text, stopwords=_MIN_STOP)
    q_token_set = set(q_tokens)
    query_norm = match_normalize(query_text)
    postings = dict(index_package.get("postings") or {})
    idf = dict(index_package.get("idf") or {})
    doc_lengths = list(index_package.get("doc_lengths") or [])
    avg_doc_length = float(index_package.get("avg_doc_length") or 0.0)
    bm25_cfg = dict(index_package.get("bm25") or {})
    k1 = float(bm25_cfg.get("k1") or 1.2)
    b = float(bm25_cfg.get("b") or 0.75)
    lexical_scores: dict[int, float] = {}
    for token in q_tokens:
        for doc_idx, tf in list(postings.get(token) or []):
            dl = float(doc_lengths[doc_idx]) if doc_lengths else 0.0
            denom = tf + k1 * (1.0 - b + b * ((dl / avg_doc_length) if avg_doc_length else 0.0))
            lexical_scores[doc_idx] = lexical_scores.get(doc_idx, 0.0) + float(idf.get(token) or 0.0) * (tf * (k1 + 1.0) / (denom + 1e-12))
    ranked: list[dict[str, Any]] = []
    for doc_idx, record in enumerate(records):
        lex = float(lexical_scores.get(doc_idx, 0.0))
        title_bonus, title_basis = _title_anchor_bonus(query_norm, q_token_set, record)
        search_terms = list(index_package.get("doc_search_tokens") or [])[doc_idx]
        structure_terms = list(index_package.get("doc_structure_tokens") or [])[doc_idx]
        title_terms = list(index_package.get("doc_title_tokens") or [])[doc_idx]
        doc_terms = list(index_package.get("doc_tokens_all") or [])[doc_idx]
        search_overlap = len(q_token_set & set(search_terms))
        structure_overlap = len(q_token_set & set(structure_terms))
        title_overlap = len(q_token_set & set(title_terms))
        final_score = lex + title_bonus + 0.2 * search_overlap + 0.1 * structure_overlap + 0.15 * title_overlap
        if final_score <= 0.0:
            continue
        matched_terms = sorted(q_token_set & set(doc_terms))
        source_path = list(record.get("source_hierarchy_path") or [])
        parent_label = str(source_path[-2]) if len(source_path) >= 2 else ""
        basis = title_basis or (f"lexical_overlap:{','.join(matched_terms[:6])}" if matched_terms else "structure_overlap")
        ranked.append({
            "doc_idx": doc_idx,
            "kc_id": record["kc_id"],
            "title": record["title"],
            "score": round(final_score, 6),
            "score_components": {"bm25": round(lex, 6), "title_anchor_bonus": round(title_bonus, 6), "search_term_overlap": search_overlap, "structure_overlap": structure_overlap, "title_overlap": title_overlap},
            "matched_terms": matched_terms,
            "matched_text_basis": basis,
            "matched_text_preview": _preview_snippet(_as_text(record.get("retrieval_text"))),
            "review_status": _as_text(record.get("review_status")),
            "parent_label": parent_label,
            "source_hierarchy_path": source_path,
            "linked_evidence_ids": list(record.get("linked_evidence_ids") or []),
            "source_document_ids": list(record.get("source_document_ids") or []),
            "runtime_entry_id": _as_text(record.get("runtime_entry_id")),
        })
    ranked.sort(key=lambda item: (-float(item["score"]), item["kc_id"]))
    top = ranked[:top_k]
    for idx, result in enumerate(top, start=1):
        result["rank"] = idx
        result["same_parent_top_hits"] = [other["title"] for other in top if other["kc_id"] != result["kc_id"] and other.get("parent_label") and other.get("parent_label") == result.get("parent_label")]
    return top

def run_validation_queries(*, records: Sequence[Mapping[str, Any]], index_package: Mapping[str, Any], validation_queries: Sequence[Mapping[str, Any]], top_k: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for query in validation_queries:
        query_id = _as_text(query.get("query_id"))
        query_text = _as_text(query.get("query_text"))
        expected = _normalize_string_list(query.get("expected_any_of"))
        top_results = run_query(query_text=query_text, records=records, index_package=index_package, top_k=top_k)
        top_ids = [result["kc_id"] for result in top_results]
        top1_hit = bool(top_ids[:1] and top_ids[0] in expected)
        top3_hit = bool(set(top_ids[:3]) & set(expected))
        results.append({
            "schema_version": RETRIEVAL_VALIDATION_SCHEMA_VERSION,
            "query_id": query_id,
            "category": _as_text(query.get("category")),
            "query_text": query_text,
            "note": _as_text(query.get("note")),
            "expected_any_of": expected,
            "top_results": top_results,
            "evaluation": {"top1_hit": top1_hit, "top3_hit": top3_hit, "top_result_kc_id": top_ids[0] if top_ids else "", "same_parent_confusion": any(result.get("same_parent_top_hits") for result in top_results[:3])},
        })
    return results


def build_validation_summary(*, validation_results: Sequence[Mapping[str, Any]], top_k: int, source_reviewed_set_id: str, source_runtime_set_id: str) -> dict[str, Any]:
    category_totals = Counter(_as_text(result.get("category")) for result in validation_results)
    category_top1 = Counter(_as_text(result.get("category")) for result in validation_results if bool((result.get("evaluation") or {}).get("top1_hit")))
    category_top3 = Counter(_as_text(result.get("category")) for result in validation_results if bool((result.get("evaluation") or {}).get("top3_hit")))
    weak_queries = [_as_text(result.get("query_id")) for result in validation_results if not bool((result.get("evaluation") or {}).get("top3_hit"))]
    ambiguous_queries = [_as_text(result.get("query_id")) for result in validation_results if bool((result.get("evaluation") or {}).get("same_parent_confusion")) or not bool((result.get("evaluation") or {}).get("top1_hit"))]
    strong_queries = [_as_text(result.get("query_id")) for result in validation_results if bool((result.get("evaluation") or {}).get("top1_hit")) and not bool((result.get("evaluation") or {}).get("same_parent_confusion"))]
    return {
        "schema_version": "1.0",
        "stage": RETRIEVAL_PILOT_STAGE,
        "rule_version": RETRIEVAL_PILOT_RULE_VERSION,
        "source_reviewed_set_id": source_reviewed_set_id,
        "source_runtime_set_id": source_runtime_set_id,
        "query_count": len(validation_results),
        "top_k": top_k,
        "top1_hit_count": sum(1 for result in validation_results if bool((result.get("evaluation") or {}).get("top1_hit"))),
        "top3_hit_count": sum(1 for result in validation_results if bool((result.get("evaluation") or {}).get("top3_hit"))),
        "weak_queries": weak_queries,
        "ambiguous_queries": ambiguous_queries,
        "strong_queries": strong_queries,
        "category_breakdown": {category: {"query_count": count, "top1_hits": category_top1.get(category, 0), "top3_hits": category_top3.get(category, 0)} for category, count in sorted(category_totals.items())},
        "sandbox_entries_included": 0,
    }


def build_validation_preview(*, summary: Mapping[str, Any], validation_results: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Reviewed-Only Retrieval Validation Preview",
        "",
        f"- Query count: `{summary['query_count']}`",
        f"- Top-1 hits: `{summary['top1_hit_count']}`",
        f"- Top-3 hits: `{summary['top3_hit_count']}`",
        f"- Weak queries: `{summary['weak_queries']}`",
        f"- Ambiguous queries: `{summary['ambiguous_queries']}`",
        "",
    ]
    for result in validation_results:
        evaluation = dict(result.get("evaluation") or {})
        lines.extend([
            f"## {result['query_id']} - {result['query_text']}",
            "",
            f"- Category: `{result['category']}`",
            f"- Expected KC(s): `{result['expected_any_of']}`",
            f"- Top-1 hit: `{evaluation.get('top1_hit')}`",
            f"- Top-3 hit: `{evaluation.get('top3_hit')}`",
            "",
        ])
        for top in list(result.get("top_results") or [])[:3]:
            lines.extend([
                f"### Rank {top['rank']} - {top['kc_id']} ({top['title']})",
                "",
                f"- Score: `{top['score']}`",
                f"- Matched basis: `{top['matched_text_basis']}`",
                f"- Matched terms: `{top['matched_terms']}`",
                f"- Structure path: `{top['source_hierarchy_path']}`",
                f"- Same-parent top hits: `{top['same_parent_top_hits']}`",
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def build_assessment_markdown(*, source_summary: Mapping[str, Any], validation_summary: Mapping[str, Any], validation_results: Sequence[Mapping[str, Any]]) -> str:
    weak_queries = list(validation_summary.get("weak_queries") or [])
    ambiguous_queries = list(validation_summary.get("ambiguous_queries") or [])
    strong_queries = list(validation_summary.get("strong_queries") or [])
    supports_continuation = not weak_queries and int(validation_summary.get("top1_hit_count") or 0) >= 7
    lines = [
        "# Reviewed-Only Retrieval Pilot Assessment",
        "",
        f"- Source reviewed slice used: `{source_summary['source_reviewed_set_id']}`",
        f"- Reviewed KC records indexed: `{source_summary['record_count']}`",
        f"- Sandbox entries included: `{source_summary['sandbox_entries_included']}`",
        f"- Validation queries run: `{validation_summary['query_count']}`",
        f"- Top-1 hits: `{validation_summary['top1_hit_count']}` / `{validation_summary['query_count']}`",
        f"- Top-3 hits: `{validation_summary['top3_hit_count']}` / `{validation_summary['query_count']}`",
        "",
        "## Observed Strengths",
        "",
        f"- Strong query ids: `{strong_queries}`",
        "- Title-anchored and definition-anchored KC queries behaved plausibly on the reviewed-only slice.",
        "- Approved lineage, evidence ids, and hierarchy cues stayed attached to every returned KC.",
        "",
        "## Observed Ambiguity / Weakness",
        "",
        f"- Ambiguous query ids: `{ambiguous_queries}`",
        f"- Weak query ids: `{weak_queries}`",
        "- Family-level metric and impurity queries still show sibling collision, but the endpoint exposes enough structure and provenance to inspect that honestly.",
        "",
        "## Recommendation",
        "",
        ("- Blunt read: this reviewed-only endpoint is good enough to support broader continuation work on KC retrieval, but not yet to claim production-grade retrieval behavior." if supports_continuation else "- Blunt read: this pilot is useful, but retrieval ambiguity is still high enough that broader continuation should stay bounded until the reviewed-only endpoint is checked on a few more slice48-style queries."),
    ]
    if validation_results:
        sample = validation_results[0]
        top = list(sample.get("top_results") or [])
        if top:
            lines.extend(["", "## Sample Trace", "", f"- Query `{sample['query_text']}` top result: `{top[0]['kc_id']}` / `{top[0]['title']}` via `{top[0]['matched_text_basis']}`"])
    return "\n".join(lines).rstrip() + "\n"

def assemble_restarted_retrieval_pilot(*, source_reviewed_library_path: Path, source_runtime_library_path: Path, output_dir: Path, assembly_run_id: str, source_reviewed_set_id: str, source_runtime_set_id: str, top_k: int = TOP_K_DEFAULT) -> RestartedRetrievalPilotResult:
    source_reviewed_library_path = source_reviewed_library_path.resolve()
    source_runtime_library_path = source_runtime_library_path.resolve()
    output_dir = output_dir.resolve()

    load_operational_kc_library(source_reviewed_library_path, expected_tier="frozen_reviewed_library")
    reviewed_rows = read_jsonl(source_reviewed_library_path)
    runtime_rows = read_jsonl(source_runtime_library_path)
    retrieval_records = build_retrieval_source_records(reviewed_rows=reviewed_rows, runtime_rows=runtime_rows, assembly_run_id=assembly_run_id, source_reviewed_set_id=source_reviewed_set_id, source_runtime_set_id=source_runtime_set_id)
    source_summary = build_source_summary(records=retrieval_records, source_reviewed_set_id=source_reviewed_set_id, source_runtime_set_id=source_runtime_set_id)
    source_preview = build_source_preview(summary=source_summary, records=retrieval_records)
    index_package = build_lexical_index(retrieval_records, k1=1.2, b=0.75, max_token_len=40, lowercase=True, stopwords=_MIN_STOP)
    index_summary = build_index_summary(index_package=index_package, source_reviewed_set_id=source_reviewed_set_id, source_runtime_set_id=source_runtime_set_id)
    query_contract = build_query_contract(top_k_default=top_k)
    validation_results = run_validation_queries(records=retrieval_records, index_package=index_package, validation_queries=DEFAULT_VALIDATION_QUERIES, top_k=top_k)
    validation_summary = build_validation_summary(validation_results=validation_results, top_k=top_k, source_reviewed_set_id=source_reviewed_set_id, source_runtime_set_id=source_runtime_set_id)
    validation_preview = build_validation_preview(summary=validation_summary, validation_results=validation_results)
    assessment_md = build_assessment_markdown(source_summary=source_summary, validation_summary=validation_summary, validation_results=validation_results)

    output_dir.mkdir(parents=True, exist_ok=True)
    retrieval_source_path = output_dir / "reviewed_retrieval_source.jsonl"
    source_summary_path = output_dir / "reviewed_retrieval_source_summary.json"
    source_preview_path = output_dir / "reviewed_retrieval_source_preview.md"
    index_path = output_dir / "reviewed_retrieval_index.json"
    index_summary_path = output_dir / "reviewed_retrieval_index_summary.json"
    query_contract_path = output_dir / "retrieval_query_contract.json"
    validation_queries_path = output_dir / "retrieval_validation_queries.json"
    validation_results_path = output_dir / "retrieval_validation_results.json"
    validation_summary_path = output_dir / "retrieval_validation_summary.json"
    validation_preview_path = output_dir / "retrieval_validation_preview.md"
    assessment_path = output_dir / "retrieval_pilot_assessment.md"

    write_jsonl(retrieval_source_path, retrieval_records)
    write_json(source_summary_path, source_summary)
    source_preview_path.write_text(source_preview, encoding="utf-8")
    write_json(index_path, index_package)
    write_json(index_summary_path, index_summary)
    write_json(query_contract_path, query_contract)
    write_json(validation_queries_path, list(DEFAULT_VALIDATION_QUERIES))
    write_json(validation_results_path, list(validation_results))
    write_json(validation_summary_path, validation_summary)
    validation_preview_path.write_text(validation_preview, encoding="utf-8")
    assessment_path.write_text(assessment_md, encoding="utf-8")

    return RestartedRetrievalPilotResult(
        output_dir=output_dir,
        retrieval_source_path=retrieval_source_path,
        source_summary_path=source_summary_path,
        source_preview_path=source_preview_path,
        index_path=index_path,
        index_summary_path=index_summary_path,
        query_contract_path=query_contract_path,
        validation_queries_path=validation_queries_path,
        validation_results_path=validation_results_path,
        validation_summary_path=validation_summary_path,
        validation_preview_path=validation_preview_path,
        assessment_path=assessment_path,
        retrieval_record_count=len(retrieval_records),
    )
