from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from kc_l.kc.supervision import (
    CURRENT_REQUIRED_PRIORITY_FEATURES,
    REVIEW_PACKET_SCHEMA_VERSION,
    REVIEW_PRIORITY_BUCKET_LABELS,
    compute_review_priority,
    derive_system_recommendation,
    load_review_packet_schema,
)
from kc_l.utils.json_io import read_json, read_jsonl, write_json, write_jsonl


GENERATION_STAGE_BY_LANE = {
    "main_quest": "main_quest_step6_processed_output",
    "default": "step6_processed_output",
}
REVIEW_PACKET_STATE = "review_ready"
TRACE_FALLBACK_EXTRACTION_METHOD = "review_packet_adapter:trace_top_candidate_fallback"
TRACE_SELECTED_REPAIR_EXTRACTION_METHOD = "review_packet_adapter:trace_selected_repair"
TRACE_DEFINITION_REFINEMENT_EXTRACTION_METHOD = "review_packet_adapter:trace_definition_refinement"
TRACE_FALLBACK_RISK_FLAG = "trace_candidate_fallback_evidence"
INTEGRITY_RULE_VERSION = "step6.review_packet_integrity.v1"
CONTENT_SOURCE_MODE_PRIMARY = "kc_library_primary"
CONTENT_SOURCE_MODE_TRACE_REPAIR = "trace_selected_repair"
CONTENT_SOURCE_MODE_DRAFT_PRIMARY = "step6_7_draft_primary"
CONTENT_REPAIR_REASON_INCOHERENT = "integrity_packet_incoherent:trace_selected_content_preferred"
CONTENT_REPAIR_REASON_WEAK_DEFINITION_SURFACE = "weak_definition_surface:grounded_evidence_definition_preferred"
CONTENT_REPAIR_RISK_FLAG = "integrity_content_repair_applied"
TRACE_SELECTED_CONTENT_REPAIR_RISK_FLAG = "integrity_content_repaired_from_trace_selected"
DEFINITION_SURFACE_REFINED_RISK_FLAG = "integrity_definition_surface_refined"
TITLE_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
GENERIC_TITLE_TOKENS = {
    "algorithm",
    "algorithms",
    "coefficient",
    "function",
    "functions",
    "index",
    "measure",
    "measures",
    "method",
    "methods",
    "model",
    "models",
    "node",
    "nodes",
    "system",
    "systems",
    "topic",
    "topics",
    "tree",
    "trees",
}
HEADING_PREFIXES = (
    "basics on ",
    "classification with ",
    "evaluation of ",
    "example",
    "internal indices",
    "questions on ",
    "recall",
    "tree induction algorithms",
)
PRIORITY_BUCKET_MAX_SCORE = {
    "low_support": 0,
    "needs_review": 3,
    "moderate_support": 5,
    "high_support": 999,
}
PRIORITY_BUCKET_ORDER = {
    "low_support": 0,
    "needs_review": 1,
    "moderate_support": 2,
    "high_support": 3,
}
INTEGRITY_FLAG_PREFIX = "integrity_"


@dataclass(frozen=True)
class PacketSkip:
    kc_candidate_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReviewPacketEmissionResult:
    output_dir: Path
    packet_path: Path
    summary_path: Path
    preview_path: Path
    packet_count: int
    skipped_candidate_count: int


@dataclass(frozen=True)
class PacketContent:
    definition_draft: str
    definition_source: str
    evidence_spans: list[dict[str, Any]]
    evidence_source: str
    used_trace_fallback: bool


@dataclass(frozen=True)
class DefinitionSurfaceRefinement:
    definition_draft: str
    definition_source: str
    replacement_evidence_id: str
    surface_issues: tuple[str, ...]
    repair_source: str
    anchor_evidence_id: str = ""
    appended_evidence_spans: tuple[dict[str, Any], ...] = ()
    appended_evidence_source: str = ""


def detect_lane(source_processed_dir: Path) -> str:
    parts = {part.lower() for part in source_processed_dir.parts}
    if "main_quest" in parts:
        return "main_quest"
    return "default"


def build_default_output_dir(repo_root: Path, source_processed_dir: Path) -> Path:
    lane = detect_lane(source_processed_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    name = f"{stamp}_from_{source_processed_dir.name}"
    return repo_root / "data" / "processed" / "kc_review_packets" / lane / name


def _load_lookup(path: Path, key: str = "kc_id") -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = read_jsonl(path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_key = str(row.get(key) or "").strip()
        if row_key:
            out[row_key] = row
    return out


def _load_trace_lookup(trace_dir: Path) -> dict[str, dict[str, Any]]:
    if not trace_dir.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(trace_dir.glob("*.json")):
        payload = read_json(path)
        kc_id = str(payload.get("kc_id") or path.stem).strip()
        if kc_id:
            out[kc_id] = payload
    return out


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalized_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _salient_title_tokens(title: str) -> list[str]:
    tokens = [token for token in _normalized_tokens(title) if len(token) >= 3 and token not in TITLE_TOKEN_STOPWORDS]
    preferred = [token for token in tokens if token not in GENERIC_TITLE_TOKENS]
    if preferred:
        return preferred
    fallback = [token for token in tokens if len(token) >= 4]
    if fallback:
        return fallback
    return tokens


def _candidate_kc_ids(values: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _default_evidence_id(kc_id: str, span: Mapping[str, Any], index: int, prefix: str) -> str:
    doc_id = _as_text(span.get("doc_id")) or "unknown_doc"
    block_id = _as_text(span.get("block_id")) or f"unknown_block_{index}"
    return f"{kc_id}:{prefix}:{index:03d}:{doc_id}:{block_id}"


def _normalize_bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        return None
    out: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            return None
        out.append(float(item))
    return out


def _normalize_role(raw: Mapping[str, Any]) -> str:
    role = _as_text(raw.get("role") or raw.get("final_role")).lower()
    if role in {"definition", "scope", "procedure", "equation", "example", "warning", "other"}:
        return role
    return "other"


def _normalize_evidence_span(
    *,
    kc_id: str,
    raw: Mapping[str, Any],
    index: int,
    extraction_method: str | None = None,
    provenance_quality_flags: Sequence[Any] | None = None,
    prefix: str,
) -> dict[str, Any] | None:
    doc_id = _as_text(raw.get("doc_id"))
    block_id = _as_text(raw.get("block_id"))
    quote = _as_text(raw.get("quote"))
    page_index = _as_int(raw.get("page_index"))
    layer = _as_text(raw.get("layer"))
    quote_verified = _as_bool(raw.get("quote_verified"))

    if not doc_id or not block_id or not quote or page_index is None or page_index < 0 or not layer:
        return None
    if quote_verified is None:
        quote_verified = False

    flags: list[str] = []
    for item in provenance_quality_flags or raw.get("provenance_quality_flags") or []:
        text = _as_text(item)
        if text:
            _append_unique(flags, text)

    span = {
        "evidence_id": _default_evidence_id(kc_id, raw, index, prefix),
        "doc_id": doc_id,
        "block_id": block_id,
        "page_index": page_index,
        "layer": layer,
        "bbox": _normalize_bbox(raw.get("bbox")),
        "quote": quote,
        "role": _normalize_role(raw),
        "extraction_method": extraction_method or _as_text(raw.get("extraction_method")) or prefix,
        "quote_verified": quote_verified,
        "provenance_quality_flags": flags,
    }
    return span


def build_packet_evidence_spans(record: Mapping[str, Any], trace: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    kc_id = _as_text(record.get("kc_id")) or _as_text(trace.get("kc_id"))
    spans: list[dict[str, Any]] = []
    for index, raw in enumerate(record.get("evidence_minimal") or []):
        if not isinstance(raw, Mapping):
            continue
        span = _normalize_evidence_span(kc_id=kc_id, raw=raw, index=index, prefix="minimal")
        if span is not None:
            spans.append(span)
    if spans:
        return spans, False

    fallback_spans: list[dict[str, Any]] = []
    for index, raw in enumerate(trace.get("top_candidates_before_gating") or []):
        if not isinstance(raw, Mapping):
            continue
        span = _normalize_evidence_span(
            kc_id=kc_id,
            raw=raw,
            index=index,
            prefix="trace_candidate",
            extraction_method=TRACE_FALLBACK_EXTRACTION_METHOD,
            provenance_quality_flags=["TraceFallbackEvidence"],
        )
        if span is not None:
            fallback_spans.append(span)
        if len(fallback_spans) >= 3:
            break
    return fallback_spans, bool(fallback_spans)


def _derive_definition_with_source(record: Mapping[str, Any], trace: Mapping[str, Any]) -> tuple[str, str]:
    for key, source in (
        ("definition_short", "kc_library.jsonl.definition_short"),
        ("definition_full", "kc_library.jsonl.definition_full"),
    ):
        text = _as_text(record.get(key))
        if text:
            return text, source
    for key, source in (
        ("definition_short_text", "enrichment_traces.definition_short_text"),
        ("definition_full_text", "enrichment_traces.definition_full_text"),
    ):
        text = _as_text(trace.get(key))
        if text:
            return text, source
    return "", "source_artifacts.empty"


def derive_definition_draft(record: Mapping[str, Any], trace: Mapping[str, Any]) -> str:
    definition_draft, _ = _derive_definition_with_source(record, trace)
    return definition_draft


def _build_primary_packet_content(record: Mapping[str, Any], trace: Mapping[str, Any]) -> PacketContent:
    evidence_spans, used_trace_fallback = build_packet_evidence_spans(record, trace)
    definition_draft, definition_source = _derive_definition_with_source(record, trace)
    evidence_source = "kc_library.jsonl.evidence_minimal"
    if used_trace_fallback:
        evidence_source = "enrichment_traces.top_candidates_before_gating"
    return PacketContent(
        definition_draft=definition_draft,
        definition_source=definition_source,
        evidence_spans=evidence_spans,
        evidence_source=evidence_source,
        used_trace_fallback=used_trace_fallback,
    )


def _coverage_labels(record: Mapping[str, Any], evidence_spans: Sequence[Mapping[str, Any]]) -> list[str]:
    labels: list[str] = []
    roles = {_normalize_role(span) for span in evidence_spans}

    if "definition" in roles or "equation" in roles:
        _append_unique(labels, "definition")
    if "example" in roles or bool(record.get("worked_examples")):
        _append_unique(labels, "worked_example")
        _append_unique(labels, "exercise_or_application")
    if "warning" in roles or _as_text(record.get("misconception_statement")):
        _append_unique(labels, "misconception_or_correction")
    if "procedure" in roles or bool(record.get("procedure_steps")):
        _append_unique(labels, "procedural_step")
    return labels


def _operational_support_present(record: Mapping[str, Any], evidence_spans: Sequence[Mapping[str, Any]]) -> bool | None:
    roles = {_normalize_role(span) for span in evidence_spans}
    if "procedure" in roles or "example" in roles:
        return True
    if record.get("procedure_steps") or record.get("worked_examples"):
        return True
    return None


def _definition_support_state(short_audit: Mapping[str, Any], tier2_row: Mapping[str, Any], trace: Mapping[str, Any]) -> str:
    for source in (tier2_row, trace, short_audit):
        value = _as_text(source.get("definition_status"))
        if value in {"coherent_supported", "fragmentary_supported", "unsupported_in_source"}:
            return value
    return "unknown"


def _definition_short_contract_ok(short_audit: Mapping[str, Any], trace: Mapping[str, Any]) -> bool | None:
    direct_value = _as_bool(short_audit.get("definition_short_contract_ok"))
    if direct_value is not None:
        return direct_value
    return _as_bool((trace.get("definition_short_audit") or {}).get("definition_short_contract_ok"))


def _provenance_complete(evidence_spans: Sequence[Mapping[str, Any]]) -> bool:
    for span in evidence_spans:
        if (
            not _as_text(span.get("doc_id"))
            or not _as_text(span.get("block_id"))
            or _as_int(span.get("page_index")) is None
            or not _as_text(span.get("layer"))
        ):
            return False
    return bool(evidence_spans)


def _source_document_ids(evidence_spans: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for span in evidence_spans:
        doc_id = _as_text(span.get("doc_id"))
        if doc_id:
            _append_unique(out, doc_id)
    return out


def _joined_evidence_quotes(evidence_spans: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(_as_text(span.get("quote")) for span in evidence_spans if _as_text(span.get("quote")))


def _all_trace_fallback_evidence(evidence_spans: Sequence[Mapping[str, Any]]) -> bool:
    return bool(evidence_spans) and all(
        _as_text(span.get("extraction_method")) == TRACE_FALLBACK_EXTRACTION_METHOD for span in evidence_spans
    )


def _has_title_anchor(title: str, text: str) -> bool:
    title_tokens = _salient_title_tokens(title)
    if not title_tokens:
        return True
    observed = set(_normalized_tokens(text))
    return any(token in observed for token in title_tokens)


def _packet_coherence_state(title: str, definition_draft: str, evidence_spans: Sequence[Mapping[str, Any]]) -> tuple[bool, bool, bool]:
    evidence_text = _joined_evidence_quotes(evidence_spans)
    definition_has_title_anchor = _has_title_anchor(title, definition_draft)
    evidence_has_title_anchor = _has_title_anchor(title, evidence_text)
    title_definition_mismatch = bool(definition_draft) and not definition_has_title_anchor
    title_evidence_mismatch = not evidence_has_title_anchor
    return title_definition_mismatch, title_evidence_mismatch, title_definition_mismatch and title_evidence_mismatch


def _normalized_surface_phrase(text: str) -> str:
    return " ".join(_normalized_tokens(text))


def _strip_title_citation_tail(text: str) -> str:
    stripped = re.sub(r"\([^)]*\)", " ", text)
    stripped = re.sub(r"\bfrom\b.*$", " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\b\d+\b", " ", stripped)
    return _normalized_surface_phrase(stripped)


def _definition_surface_issue_codes(title: str, definition_draft: str) -> list[str]:
    definition_text = _as_text(definition_draft)
    if not definition_text:
        return []

    issues: list[str] = []
    normalized_title = _normalized_surface_phrase(title)
    stripped_definition = _strip_title_citation_tail(definition_text)
    if normalized_title and stripped_definition == normalized_title:
        _append_unique(issues, "title_like")

    title_tokens = set(_normalized_tokens(title))
    definition_tokens = _normalized_tokens(definition_text)
    extra_tokens = [token for token in definition_tokens if token not in title_tokens]
    contains_heading_separator = any(separator in definition_text for separator in (" - ", " – ", ":"))
    if (
        contains_heading_separator
        and title_tokens
        and title_tokens.issubset(set(definition_tokens))
        and len(extra_tokens) <= 4
        and not definition_text.endswith(".")
    ):
        _append_unique(issues, "heading_like")
    if title_tokens and any(definition_text.lower().startswith(prefix) for prefix in HEADING_PREFIXES):
        _append_unique(issues, "heading_like")

    lowered = definition_text.lower()
    if (
        definition_text.endswith(":")
        or lowered.startswith("for a node ")
        or lowered.startswith("where ")
        or "means that:" in lowered
        or "the gain of this split is" in lowered
    ):
        _append_unique(issues, "formula_lead_in")
    return issues


def _definition_surface_quality_score(title: str, definition_draft: str) -> int:
    definition_text = _as_text(definition_draft)
    if not definition_text:
        return -999

    issues = _definition_surface_issue_codes(title, definition_text)
    score = len(_normalized_tokens(definition_text))
    score -= 20 * len(issues)
    if len(definition_text) >= 30:
        score += 8
    if len(definition_text) >= 60:
        score += 4
    if definition_text.endswith("."):
        score += 6
    if "=" in definition_text:
        score += 3
    return score


def _span_identity_key(span: Mapping[str, Any]) -> tuple[str, str, int | None, str, str]:
    return (
        _as_text(span.get("doc_id")),
        _as_text(span.get("block_id")),
        _as_int(span.get("page_index")),
        _as_text(span.get("layer")),
        _as_text(span.get("quote")),
    )


def _merge_unique_evidence_spans(
    existing_spans: Sequence[Mapping[str, Any]],
    appended_spans: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged = [dict(span) for span in existing_spans]
    seen = {_span_identity_key(span) for span in merged}
    for span in appended_spans:
        key = _span_identity_key(span)
        if key in seen:
            continue
        merged.append(dict(span))
        seen.add(key)
    return merged


def _normalize_trace_definition_refinement_span(
    *,
    kc_id: str,
    raw: Mapping[str, Any],
    index: int,
) -> dict[str, Any] | None:
    augmented_raw = dict(raw)
    quote = _as_text(raw.get("quote")) or _as_text(raw.get("source_text"))
    if not quote:
        return None
    augmented_raw["quote"] = quote
    return _normalize_evidence_span(
        kc_id=kc_id,
        raw=augmented_raw,
        index=index,
        prefix="trace_definition_refinement",
        extraction_method=TRACE_DEFINITION_REFINEMENT_EXTRACTION_METHOD,
        provenance_quality_flags=[*(raw.get("provenance_quality_flags") or []), "TraceDefinitionRefinement"],
    )


def _trace_definition_anchor(
    *,
    title_draft: str,
    definition_draft: str,
    evidence_spans: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    current_definition = _as_text(definition_draft)
    if _has_title_anchor(title_draft, current_definition):
        return current_definition, ""

    best_anchor = ""
    best_anchor_id = ""
    best_score = -999
    for span in evidence_spans:
        text = _as_text(span.get("quote"))
        if not text or not _has_title_anchor(title_draft, text):
            continue
        score = _definition_surface_quality_score(title_draft, text)
        if text.endswith(":"):
            score += 6
        if _as_text(span.get("role")) in {"definition", "procedure", "equation"}:
            score += 4
        if _as_bool(span.get("quote_verified")) is True:
            score += 2
        if score <= best_score:
            continue
        best_anchor = text
        best_anchor_id = _as_text(span.get("evidence_id"))
        best_score = score
    return best_anchor, best_anchor_id


def _trace_definition_composite_text(anchor_text: str, candidate_text: str) -> str:
    anchor = anchor_text.strip()
    candidate = candidate_text.strip().lstrip("▶").strip()
    if not anchor:
        return candidate
    if not candidate:
        return anchor
    separator = " "
    if not anchor.endswith((".", ":", ";")):
        separator = ". "
    return f"{anchor}{separator}{candidate}"


def _build_trace_definition_surface_refinement(
    *,
    kc_id: str,
    title_draft: str,
    definition_draft: str,
    evidence_spans: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any],
) -> DefinitionSurfaceRefinement | None:
    current_definition = _as_text(definition_draft)
    current_issues = _definition_surface_issue_codes(title_draft, current_definition)
    if not current_definition or not current_issues:
        return None

    anchor_text, anchor_evidence_id = _trace_definition_anchor(
        title_draft=title_draft,
        definition_draft=current_definition,
        evidence_spans=evidence_spans,
    )
    if not anchor_text:
        return None

    best_refinement: DefinitionSurfaceRefinement | None = None
    best_score = _definition_surface_quality_score(title_draft, current_definition)
    existing_doc_ids = {
        _as_text(span.get("doc_id"))
        for span in evidence_spans
        if _as_text(span.get("doc_id"))
    }

    for source_key in ("accepted_candidates_post_provenance", "selected_candidates", "top_candidates_before_gating"):
        for index, raw in enumerate(trace.get(source_key) or []):
            if not isinstance(raw, Mapping):
                continue
            candidate_text = _as_text(raw.get("source_text")) or _as_text(raw.get("quote"))
            if not candidate_text or candidate_text == current_definition or candidate_text == anchor_text:
                continue

            page_index = _as_int(raw.get("page_index"))
            if page_index is None or page_index < 0:
                continue
            if _as_bool(raw.get("quote_verified")) is not True:
                continue

            lowered_candidate = candidate_text.lower()
            if "=" not in candidate_text and " where " not in lowered_candidate:
                continue
            if any(marker in lowered_candidate for marker in ("justify your answers", "if you answered", "can we then say that")):
                continue

            context_text = _trace_candidate_context_text(raw)
            if not (_has_title_anchor(title_draft, candidate_text) or _has_title_anchor(title_draft, context_text)):
                continue
            if existing_doc_ids and _as_text(raw.get("doc_id")) not in existing_doc_ids:
                continue

            appended_span = _normalize_trace_definition_refinement_span(kc_id=kc_id, raw=raw, index=index)
            if appended_span is None:
                continue

            composed_definition = _trace_definition_composite_text(anchor_text, candidate_text)
            candidate_score = _definition_surface_quality_score(title_draft, composed_definition)
            if "=" in candidate_text:
                candidate_score += 8
            if source_key != "top_candidates_before_gating":
                candidate_score += 4
            if _as_text(raw.get("doc_id")) in existing_doc_ids:
                candidate_score += 6
            if len(_normalized_tokens(candidate_text)) > 40:
                candidate_score -= 12
            if _as_text(raw.get("final_role") or raw.get("role")) in {"definition", "equation", "procedure"}:
                candidate_score += 4

            if candidate_score <= best_score:
                continue

            best_score = candidate_score
            best_refinement = DefinitionSurfaceRefinement(
                definition_draft=composed_definition,
                definition_source=f"review_packet.composed_definition:{source_key}",
                replacement_evidence_id=_as_text(appended_span.get("evidence_id")),
                surface_issues=tuple(current_issues),
                repair_source="grounded_trace_candidate_compose",
                anchor_evidence_id=anchor_evidence_id,
                appended_evidence_spans=(appended_span,),
                appended_evidence_source=f"enrichment_traces.{source_key}",
            )

    return best_refinement


def _build_definition_surface_refinement(
    *,
    title_draft: str,
    definition_draft: str,
    evidence_spans: Sequence[Mapping[str, Any]],
) -> DefinitionSurfaceRefinement | None:
    current_definition = _as_text(definition_draft)
    current_issues = _definition_surface_issue_codes(title_draft, current_definition)
    if not current_definition or not current_issues:
        return None

    best_refinement: DefinitionSurfaceRefinement | None = None
    best_score = _definition_surface_quality_score(title_draft, current_definition)

    for span in evidence_spans:
        candidate_text = _as_text(span.get("quote"))
        if not candidate_text or candidate_text == current_definition:
            continue

        candidate_issues = _definition_surface_issue_codes(title_draft, candidate_text)
        if len(candidate_issues) >= len(current_issues):
            continue

        candidate_score = _definition_surface_quality_score(title_draft, candidate_text)
        if _as_text(span.get("role")) in {"definition", "procedure"}:
            candidate_score += 4
        if _as_bool(span.get("quote_verified")) is True:
            candidate_score += 2

        if candidate_score <= best_score:
            continue

        evidence_id = _as_text(span.get("evidence_id"))
        if not evidence_id:
            continue

        best_score = candidate_score
        best_refinement = DefinitionSurfaceRefinement(
            definition_draft=candidate_text,
            definition_source=f"review_packet.evidence_spans.quote:{evidence_id}",
            replacement_evidence_id=evidence_id,
            surface_issues=tuple(current_issues),
            repair_source="packet_evidence_quote",
        )

    return best_refinement


def _trace_selected_candidates(trace: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], str]:
    for key in ("accepted_candidates_post_provenance", "selected_candidates"):
        rows = [row for row in trace.get(key) or [] if isinstance(row, Mapping)]
        if rows:
            return rows, f"enrichment_traces.{key}"
    return [], "enrichment_traces.selected_candidates"


def _trace_candidate_context_text(raw: Mapping[str, Any]) -> str:
    parts = [
        _as_text(raw.get("quote")),
        _as_text(raw.get("source_text")),
        _as_text(raw.get("patch_heading")),
        _as_text(raw.get("page_heading_norm")),
        _as_text(raw.get("source_block_text")),
        _as_text(raw.get("doc_id")),
    ]
    return " ".join(part for part in parts if part)


def _normalize_trace_selected_candidate_span(*, kc_id: str, raw: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    return _normalize_evidence_span(
        kc_id=kc_id,
        raw=raw,
        index=index,
        prefix="trace_selected_repair",
        extraction_method=TRACE_SELECTED_REPAIR_EXTRACTION_METHOD,
        provenance_quality_flags=[*(raw.get("provenance_quality_flags") or []), "TraceSelectedRepair"],
    )


def _build_trace_selected_repair_content(*, kc_id: str, title_draft: str, trace: Mapping[str, Any]) -> PacketContent | None:
    candidates, source_label = _trace_selected_candidates(trace)
    anchored_candidates: list[Mapping[str, Any]] = []
    for raw in candidates:
        candidate_text = _as_text(raw.get("source_text")) or _as_text(raw.get("quote"))
        if not candidate_text:
            continue
        if _has_title_anchor(title_draft, candidate_text) and _has_title_anchor(title_draft, _trace_candidate_context_text(raw)):
            anchored_candidates.append(raw)

    if not anchored_candidates:
        return None

    evidence_spans: list[dict[str, Any]] = []
    for index, raw in enumerate(anchored_candidates):
        span = _normalize_trace_selected_candidate_span(kc_id=kc_id, raw=raw, index=index)
        if span is not None:
            evidence_spans.append(span)
        if len(evidence_spans) >= 3:
            break

    if not evidence_spans:
        return None

    definition_draft = _as_text(anchored_candidates[0].get("source_text")) or _as_text(anchored_candidates[0].get("quote"))
    if not definition_draft:
        return None

    title_definition_mismatch, title_evidence_mismatch, packet_incoherent = _packet_coherence_state(
        title_draft,
        definition_draft,
        evidence_spans,
    )
    if title_definition_mismatch or title_evidence_mismatch or packet_incoherent:
        return None

    return PacketContent(
        definition_draft=definition_draft,
        definition_source=f"{source_label}.source_text_or_quote",
        evidence_spans=evidence_spans,
        evidence_source=source_label,
        used_trace_fallback=False,
    )


def _trace_provenance_adjusted(trace: Mapping[str, Any], evidence_spans: Sequence[Mapping[str, Any]]) -> bool:
    for span in evidence_spans:
        flags = {_as_text(item) for item in span.get("provenance_quality_flags") or []}
        if "PageIndexSubstituted" in flags or "PageIndexDropped" in flags:
            return True

    provenance = dict(trace.get("provenance_normalization") or trace.get("provenance_normalization_excerpt") or {})
    return any(
        (_as_int(provenance.get(key)) or 0) > 0
        for key in ("page_index_substituted_count", "page_index_dropped_count")
    )


def _build_evidence_coverage_summary(
    *,
    record: Mapping[str, Any],
    short_audit: Mapping[str, Any],
    tier2_row: Mapping[str, Any],
    trace: Mapping[str, Any],
    evidence_spans: Sequence[Mapping[str, Any]],
    used_trace_fallback: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "evidence_span_count": len(evidence_spans),
        "definition_support_state": _definition_support_state(short_audit, tier2_row, trace),
        "operational_support_present": _operational_support_present(record, evidence_spans),
        "coverage_labels": _coverage_labels(record, evidence_spans),
        "provenance_complete": _provenance_complete(evidence_spans),
    }
    if used_trace_fallback:
        summary["coverage_note"] = (
            "Packet evidence falls back to grounded trace candidates because kc_library.jsonl lacked minimal evidence spans."
        )
    return summary


def _build_source_provenance(
    *,
    source_processed_dir: Path,
    record: Mapping[str, Any],
    evidence_spans: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    lane = detect_lane(source_processed_dir)
    source_set_ids = dict(record.get("source_set_ids") or {})
    allowed_set_ids = {
        key: value
        for key, value in source_set_ids.items()
        if key in {"step4_set_id", "step5_set_id", "step6_set_id"} and _as_text(value)
    }
    return {
        "generation_stage": GENERATION_STAGE_BY_LANE.get(lane, GENERATION_STAGE_BY_LANE["default"]),
        "generation_run_id": source_processed_dir.name,
        "source_set_ids": allowed_set_ids,
        "source_document_ids": _source_document_ids(evidence_spans),
    }


def _build_risk_flags(
    *,
    definition_draft: str,
    short_audit: Mapping[str, Any],
    tier2_row: Mapping[str, Any],
    trace: Mapping[str, Any],
    used_trace_fallback: bool,
) -> list[str]:
    risk_flags: list[str] = []
    definition_status = _definition_support_state(short_audit, tier2_row, trace)
    if definition_status == "unsupported_in_source":
        _append_unique(risk_flags, "unsupported_in_source")
    elif definition_status == "fragmentary_supported":
        _append_unique(risk_flags, "fragmentary_supported")

    support_contract = dict(trace.get("support_contract") or {})
    support_contract_downgraded = _as_bool(
        tier2_row.get("support_contract_downgraded")
        if "support_contract_downgraded" in tier2_row
        else support_contract.get("support_contract_downgraded")
    )
    if support_contract_downgraded is True:
        _append_unique(risk_flags, "support_contract_downgraded")

    contamination_summary = dict(trace.get("contamination_summary") or {})
    contamination_category = _as_text(
        tier2_row.get("contamination_category")
        if "contamination_category" in tier2_row
        else contamination_summary.get("category")
    )
    if contamination_category == "hard_contamination":
        _append_unique(risk_flags, "hard_contamination")

    sibling_ambiguity = _as_bool(
        tier2_row.get("sibling_ambiguity")
        if "sibling_ambiguity" in tier2_row
        else contamination_summary.get("sibling_ambiguous_support")
    )
    if sibling_ambiguity is True:
        _append_unique(risk_flags, "sibling_ambiguity")

    if _definition_short_contract_ok(short_audit, trace) is False:
        _append_unique(risk_flags, "definition_short_contract_fail")

    competitor_ids = _candidate_kc_ids(
        tier2_row.get("competitor_kc_ids")
        or contamination_summary.get("competitor_kc_ids")
        or []
    )
    if competitor_ids:
        _append_unique(risk_flags, "nearby_competitor_present")

    if not definition_draft:
        _append_unique(risk_flags, "definition_text_missing")
    if used_trace_fallback:
        _append_unique(risk_flags, TRACE_FALLBACK_RISK_FLAG)
    return risk_flags


def build_priority_features(
    *,
    record: Mapping[str, Any],
    short_audit: Mapping[str, Any],
    tier2_row: Mapping[str, Any],
    trace: Mapping[str, Any],
    evidence_spans: Sequence[Mapping[str, Any]],
    definition_draft: str,
) -> dict[str, Any]:
    support_contract = dict(trace.get("support_contract") or {})
    contamination_summary = dict(trace.get("contamination_summary") or {})
    competitor_ids = _candidate_kc_ids(
        tier2_row.get("competitor_kc_ids")
        or contamination_summary.get("competitor_kc_ids")
        or []
    )

    accepted_quote_count = _as_int(tier2_row.get("accepted_quote_count"))
    if accepted_quote_count is None:
        accepted_quote_count = sum(1 for span in evidence_spans if _as_bool(span.get("quote_verified")) is True)

    semantic_tier = _as_int(tier2_row.get("semantic_tier"))
    if semantic_tier is None:
        semantic_tier = _as_int(trace.get("semantic_tier"))
    if semantic_tier is None:
        semantic_tier = _as_int(short_audit.get("semantic_tier"))

    return {
        "semantic_tier": semantic_tier,
        "definition_status": _definition_support_state(short_audit, tier2_row, trace),
        "accepted_quote_count": accepted_quote_count,
        "evidence_span_count": len(evidence_spans),
        "definition_short_contract_ok": _definition_short_contract_ok(short_audit, trace),
        "support_contract_downgraded": _as_bool(
            tier2_row.get("support_contract_downgraded")
            if "support_contract_downgraded" in tier2_row
            else support_contract.get("support_contract_downgraded")
        ),
        "contamination_category": _as_text(
            tier2_row.get("contamination_category")
            if "contamination_category" in tier2_row
            else contamination_summary.get("category")
        )
        or None,
        "sibling_ambiguity": _as_bool(
            tier2_row.get("sibling_ambiguity")
            if "sibling_ambiguity" in tier2_row
            else contamination_summary.get("sibling_ambiguous_support")
        ),
        "operational_support_present": _operational_support_present(record, evidence_spans),
        "proposal_route_agreement": None,
        "overlap_risk": "high" if competitor_ids else None,
        "underspecified_wording_risk": "high" if not definition_draft else None,
        "overbroadness_risk": "high" if support_contract.get("bundle_parent_topic_overlap") is True else None,
        "novelty_against_frozen_library": None,
    }


def _cap_review_priority(review_priority: dict[str, Any], target_bucket: str, reason_code: str) -> None:
    current_bucket = _as_text(review_priority.get("bucket"))
    if current_bucket not in PRIORITY_BUCKET_ORDER or target_bucket not in PRIORITY_BUCKET_ORDER:
        return
    if PRIORITY_BUCKET_ORDER[current_bucket] <= PRIORITY_BUCKET_ORDER[target_bucket]:
        return

    reason_codes = [
        str(code)
        for code in review_priority.get("reason_codes") or []
        if not str(code).startswith("priority_bucket:")
    ]
    review_priority["reason_codes"] = reason_codes
    review_priority["bucket"] = target_bucket
    review_priority["display_label"] = REVIEW_PRIORITY_BUCKET_LABELS[target_bucket]
    review_priority["rank_score"] = min(_as_int(review_priority.get("rank_score")) or 0, PRIORITY_BUCKET_MAX_SCORE[target_bucket])
    _append_unique(review_priority["reason_codes"], f"priority_bucket:{target_bucket}")
    _append_unique(review_priority["reason_codes"], f"integrity_bucket_cap:{target_bucket}")
    _append_unique(review_priority["reason_codes"], reason_code)


def _apply_packet_integrity_gate(
    *,
    packet: dict[str, Any],
    trace: Mapping[str, Any],
) -> None:
    title_draft = _as_text(packet.get("title_draft"))
    definition_draft = _as_text(packet.get("definition_draft"))
    evidence_spans = list(packet.get("evidence_spans") or [])
    coverage = dict(packet.get("evidence_coverage_summary") or {})
    risk_flags = list(packet.get("risk_flags") or [])
    review_priority = dict(packet.get("review_priority") or {})
    review_priority["reason_codes"] = list(review_priority.get("reason_codes") or [])
    review_priority["missing_feature_keys"] = list(review_priority.get("missing_feature_keys") or [])
    review_priority["blocking_reason_codes"] = list(review_priority.get("blocking_reason_codes") or [])

    title_definition_mismatch, title_evidence_mismatch, packet_incoherent = _packet_coherence_state(
        title_draft,
        definition_draft,
        evidence_spans,
    )
    definition_surface_issues = _definition_surface_issue_codes(title_draft, definition_draft)
    fallback_only_evidence = _all_trace_fallback_evidence(evidence_spans)
    provenance_adjusted = _trace_provenance_adjusted(trace, evidence_spans)
    content_repair_applied = _as_bool(packet.get("content_repair_applied")) is True
    content_repair_reason = _as_text(packet.get("content_repair_reason"))
    thin_support = (
        _as_text(review_priority.get("bucket")) == "high_support"
        and len(evidence_spans) <= 2
        and coverage.get("operational_support_present") is not True
    )

    integrity_reason_codes: list[str] = []

    if title_definition_mismatch:
        _append_unique(risk_flags, "integrity_title_definition_mismatch")
        _append_unique(integrity_reason_codes, "integrity:title_definition_mismatch")
    if title_evidence_mismatch:
        _append_unique(risk_flags, "integrity_title_evidence_mismatch")
        _append_unique(integrity_reason_codes, "integrity:title_evidence_mismatch")
    if packet_incoherent:
        _append_unique(risk_flags, "integrity_packet_incoherent")
        _append_unique(integrity_reason_codes, "integrity:packet_incoherent")
    if not content_repair_applied:
        for issue in definition_surface_issues:
            _append_unique(risk_flags, f"integrity_definition_surface_{issue}")
            _append_unique(integrity_reason_codes, f"integrity:definition_surface_{issue}")
    if not definition_draft:
        _append_unique(risk_flags, "integrity_definition_missing_no_approve")
        _append_unique(integrity_reason_codes, "integrity:definition_missing_no_approve")
    if fallback_only_evidence:
        _append_unique(risk_flags, "integrity_fallback_only_evidence")
        _append_unique(integrity_reason_codes, "integrity:fallback_only_evidence")
    if provenance_adjusted:
        _append_unique(risk_flags, "integrity_provenance_adjusted")
        _append_unique(integrity_reason_codes, "integrity:provenance_adjusted")
    if thin_support:
        _append_unique(risk_flags, "integrity_thin_support")
        _append_unique(integrity_reason_codes, "integrity:thin_support")
    if content_repair_applied:
        _append_unique(risk_flags, CONTENT_REPAIR_RISK_FLAG)
        _append_unique(integrity_reason_codes, "integrity:content_repair_applied")
        if content_repair_reason == CONTENT_REPAIR_REASON_WEAK_DEFINITION_SURFACE:
            _append_unique(risk_flags, DEFINITION_SURFACE_REFINED_RISK_FLAG)
            _append_unique(integrity_reason_codes, "integrity:definition_surface_refined")
        if _as_text(packet.get("content_source_mode")) == CONTENT_SOURCE_MODE_TRACE_REPAIR:
            _append_unique(risk_flags, TRACE_SELECTED_CONTENT_REPAIR_RISK_FLAG)
            _append_unique(integrity_reason_codes, "integrity:content_repaired_from_trace_selected")

    if not definition_draft:
        _cap_review_priority(review_priority, "needs_review", "integrity:definition_missing_no_approve")
    if fallback_only_evidence:
        _cap_review_priority(review_priority, "needs_review", "integrity:fallback_only_evidence")
    if title_evidence_mismatch:
        _cap_review_priority(review_priority, "needs_review", "integrity:title_evidence_mismatch")
    if definition_surface_issues and not content_repair_applied:
        _cap_review_priority(review_priority, "moderate_support", "integrity:weak_definition_surface")
    if provenance_adjusted:
        _cap_review_priority(review_priority, "moderate_support", "integrity:provenance_adjusted")
    if thin_support:
        _cap_review_priority(review_priority, "moderate_support", "integrity:thin_support")
    if content_repair_applied:
        _cap_review_priority(review_priority, "needs_review", "integrity:content_repair_applied")

    recommendation = derive_system_recommendation({}, review_priority)
    for reason_code in integrity_reason_codes:
        _append_unique(review_priority["reason_codes"], reason_code)
        _append_unique(recommendation["reason_codes"], reason_code)
    _append_unique(review_priority["reason_codes"], f"integrity_rule_version:{INTEGRITY_RULE_VERSION}")
    _append_unique(recommendation["reason_codes"], f"integrity_rule_version:{INTEGRITY_RULE_VERSION}")

    packet["risk_flags"] = risk_flags
    packet["review_priority"] = review_priority
    packet["system_recommendation"] = recommendation


def _content_source_metadata(*, definition_source: str, evidence_source: str) -> dict[str, str]:
    return {
        "definition_source": definition_source,
        "evidence_source": evidence_source,
    }


def _apply_definition_surface_refinement(
    *,
    source_processed_dir: Path,
    record: Mapping[str, Any],
    short_audit: Mapping[str, Any],
    tier2_row: Mapping[str, Any],
    trace: Mapping[str, Any],
    packet: dict[str, Any],
) -> None:
    if _as_bool(packet.get("content_repair_applied")) is True:
        return

    evidence_spans = [span for span in packet.get("evidence_spans") or [] if isinstance(span, Mapping)]
    refinement = _build_definition_surface_refinement(
        title_draft=_as_text(packet.get("title_draft")),
        definition_draft=_as_text(packet.get("definition_draft")),
        evidence_spans=evidence_spans,
    )
    if refinement is None:
        refinement = _build_trace_definition_surface_refinement(
            kc_id=_as_text(record.get("kc_id")),
            title_draft=_as_text(packet.get("title_draft")),
            definition_draft=_as_text(packet.get("definition_draft")),
            evidence_spans=evidence_spans,
            trace=trace,
        )
    if refinement is None:
        return

    packet["debug_original_content"] = {
        "definition_draft": _as_text(packet.get("definition_draft")),
        "evidence_spans": [dict(span) for span in packet.get("evidence_spans") or []],
    }
    packet["definition_draft"] = refinement.definition_draft
    if refinement.appended_evidence_spans:
        packet["evidence_spans"] = _merge_unique_evidence_spans(evidence_spans, refinement.appended_evidence_spans)
    packet["evidence_coverage_summary"] = _build_evidence_coverage_summary(
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        evidence_spans=[span for span in packet.get("evidence_spans") or [] if isinstance(span, Mapping)],
        used_trace_fallback=False,
    )
    packet["source_provenance"] = _build_source_provenance(
        source_processed_dir=source_processed_dir,
        record=record,
        evidence_spans=[span for span in packet.get("evidence_spans") or [] if isinstance(span, Mapping)],
    )
    packet["risk_flags"] = _build_risk_flags(
        definition_draft=refinement.definition_draft,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        used_trace_fallback=False,
    )
    priority_features = build_priority_features(
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        evidence_spans=[span for span in packet.get("evidence_spans") or [] if isinstance(span, Mapping)],
        definition_draft=refinement.definition_draft,
    )
    review_priority = compute_review_priority(priority_features)
    system_recommendation = derive_system_recommendation(priority_features, review_priority)
    packet["review_priority"] = review_priority
    packet["system_recommendation"] = system_recommendation
    packet["content_repair_applied"] = True
    packet["content_repair_reason"] = CONTENT_REPAIR_REASON_WEAK_DEFINITION_SURFACE
    current_evidence_source = _as_text((packet.get("review_content_source") or {}).get("evidence_source")) or _as_text(
        (packet.get("original_content_source") or {}).get("evidence_source")
    )
    if refinement.appended_evidence_source:
        current_evidence_source = f"{current_evidence_source}+{refinement.appended_evidence_source}"
    packet["review_content_source"] = _content_source_metadata(
        definition_source=refinement.definition_source,
        evidence_source=current_evidence_source,
    )
    packet["integrity_repair_notes"] = [
        "repair_applied:weak_definition_surface",
        f"repair_source:{refinement.repair_source}",
        "replaced:definition_draft",
        *([f"anchor_evidence_id:{refinement.anchor_evidence_id}"] if refinement.anchor_evidence_id else []),
        f"replacement_evidence_id:{refinement.replacement_evidence_id}",
        *[f"original_surface:{issue}" for issue in refinement.surface_issues],
    ]


def _apply_source_precedence_repair(
    *,
    source_processed_dir: Path,
    record: Mapping[str, Any],
    short_audit: Mapping[str, Any],
    tier2_row: Mapping[str, Any],
    trace: Mapping[str, Any],
    packet: dict[str, Any],
) -> None:
    title_draft = _as_text(packet.get("title_draft"))
    _, _, packet_incoherent = _packet_coherence_state(
        title_draft,
        _as_text(packet.get("definition_draft")),
        list(packet.get("evidence_spans") or []),
    )
    if not packet_incoherent:
        return

    kc_id = _as_text(record.get("kc_id"))
    repair_content = _build_trace_selected_repair_content(kc_id=kc_id, title_draft=title_draft, trace=trace)
    if repair_content is None:
        raise ValueError(f"{kc_id}: integrity_packet_incoherent and no coherent trace-selected repair content")

    packet["debug_original_content"] = {
        "definition_draft": _as_text(packet.get("definition_draft")),
        "evidence_spans": [dict(span) for span in packet.get("evidence_spans") or []],
    }
    packet["definition_draft"] = repair_content.definition_draft
    packet["evidence_spans"] = repair_content.evidence_spans
    packet["evidence_coverage_summary"] = _build_evidence_coverage_summary(
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        evidence_spans=repair_content.evidence_spans,
        used_trace_fallback=False,
    )
    packet["evidence_coverage_summary"]["coverage_note"] = (
        "Packet reviewer-facing content was repaired from grounded trace-selected candidates because the original packet content was incoherent to the KC title."
    )
    packet["source_provenance"] = _build_source_provenance(
        source_processed_dir=source_processed_dir,
        record=record,
        evidence_spans=repair_content.evidence_spans,
    )
    packet["risk_flags"] = _build_risk_flags(
        definition_draft=repair_content.definition_draft,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        used_trace_fallback=False,
    )

    priority_features = build_priority_features(
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        evidence_spans=repair_content.evidence_spans,
        definition_draft=repair_content.definition_draft,
    )
    review_priority = compute_review_priority(priority_features)
    system_recommendation = derive_system_recommendation(priority_features, review_priority)
    packet["review_priority"] = review_priority
    packet["system_recommendation"] = system_recommendation

    packet["content_source_mode"] = CONTENT_SOURCE_MODE_TRACE_REPAIR
    packet["content_repair_applied"] = True
    packet["content_repair_reason"] = CONTENT_REPAIR_REASON_INCOHERENT
    packet["review_content_source"] = _content_source_metadata(
        definition_source=repair_content.definition_source,
        evidence_source=repair_content.evidence_source,
    )
    packet["integrity_repair_notes"] = [
        "repair_applied:integrity_packet_incoherent",
        "repair_source:trace_selected_candidates",
        "replaced:definition_draft",
        "replaced:evidence_spans",
    ]


def build_review_packet(
    *,
    source_processed_dir: Path,
    record: Mapping[str, Any],
    short_audit: Mapping[str, Any],
    tier2_row: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> dict[str, Any]:
    kc_id = _as_text(record.get("kc_id"))
    primary_content = _build_primary_packet_content(record, trace)
    if not primary_content.evidence_spans:
        raise ValueError(f"{kc_id}: no grounded evidence spans available for review packet emission")

    priority_features = build_priority_features(
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        evidence_spans=primary_content.evidence_spans,
        definition_draft=primary_content.definition_draft,
    )
    review_priority = compute_review_priority(priority_features)
    system_recommendation = derive_system_recommendation(priority_features, review_priority)

    original_content_source = _content_source_metadata(
        definition_source=primary_content.definition_source,
        evidence_source=primary_content.evidence_source,
    )
    packet = {
        "review_packet_id": f"{source_processed_dir.name}:{kc_id}:review_packet",
        "packet_state": REVIEW_PACKET_STATE,
        "kc_candidate_id": kc_id,
        "title_draft": _as_text(record.get("canonical_name")),
        "level_draft": "atomic",
        "definition_draft": primary_content.definition_draft,
        "evidence_spans": primary_content.evidence_spans,
        "evidence_coverage_summary": _build_evidence_coverage_summary(
            record=record,
            short_audit=short_audit,
            tier2_row=tier2_row,
            trace=trace,
            evidence_spans=primary_content.evidence_spans,
            used_trace_fallback=primary_content.used_trace_fallback,
        ),
        "source_provenance": _build_source_provenance(
            source_processed_dir=source_processed_dir,
            record=record,
            evidence_spans=primary_content.evidence_spans,
        ),
        "content_source_mode": CONTENT_SOURCE_MODE_PRIMARY,
        "content_repair_applied": False,
        "content_repair_reason": "",
        "original_content_source": original_content_source,
        "review_content_source": dict(original_content_source),
        "integrity_repair_notes": [],
        "risk_flags": _build_risk_flags(
            definition_draft=primary_content.definition_draft,
            short_audit=short_audit,
            tier2_row=tier2_row,
            trace=trace,
            used_trace_fallback=primary_content.used_trace_fallback,
        ),
        "review_priority": review_priority,
        "system_recommendation": system_recommendation,
    }
    _apply_source_precedence_repair(
        source_processed_dir=source_processed_dir,
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        packet=packet,
    )
    _apply_definition_surface_refinement(
        source_processed_dir=source_processed_dir,
        record=record,
        short_audit=short_audit,
        tier2_row=tier2_row,
        trace=trace,
        packet=packet,
    )
    _apply_packet_integrity_gate(packet=packet, trace=trace)
    return packet


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_review_packet(packet: Mapping[str, Any]) -> None:
    schema = load_review_packet_schema()
    _expect(schema.get("schema_version") == REVIEW_PACKET_SCHEMA_VERSION, "Review packet schema version mismatch")

    required = schema.get("required") or []
    for key in required:
        _expect(key in packet, f"Missing required packet field: {key}")

    _expect(packet.get("packet_state") == REVIEW_PACKET_STATE, "Packet state must be review_ready at emission")
    _expect(packet.get("level_draft") in {"atomic", "topic"}, "level_draft must be atomic or topic")
    _expect(isinstance(packet.get("kc_candidate_id"), str) and packet["kc_candidate_id"], "kc_candidate_id is required")
    _expect(isinstance(packet.get("review_packet_id"), str) and packet["review_packet_id"], "review_packet_id is required")
    _expect(isinstance(packet.get("risk_flags"), list), "risk_flags must be a list")

    evidence_spans = packet.get("evidence_spans")
    _expect(isinstance(evidence_spans, list) and evidence_spans, "evidence_spans must be a non-empty list")
    for index, span in enumerate(evidence_spans):
        _expect(isinstance(span, Mapping), f"Evidence span {index} must be an object")
        for key in ("evidence_id", "doc_id", "block_id", "page_index", "layer", "quote", "role", "quote_verified"):
            _expect(key in span, f"Evidence span {index} missing required field: {key}")
        _expect(isinstance(span["page_index"], int) and span["page_index"] >= 0, f"Evidence span {index} page_index invalid")
        _expect(
            span["role"] in {"definition", "scope", "procedure", "equation", "example", "warning", "other"},
            f"Evidence span {index} role invalid",
        )
        _expect(isinstance(span["quote_verified"], bool), f"Evidence span {index} quote_verified invalid")

    coverage = packet.get("evidence_coverage_summary")
    _expect(isinstance(coverage, Mapping), "evidence_coverage_summary must be an object")
    _expect(coverage.get("evidence_span_count") == len(evidence_spans), "evidence_span_count must match evidence_spans length")
    _expect(
        coverage.get("definition_support_state") in {"coherent_supported", "fragmentary_supported", "unsupported_in_source", "unknown"},
        "definition_support_state invalid",
    )
    _expect(isinstance(coverage.get("coverage_labels"), list), "coverage_labels must be a list")
    _expect(isinstance(coverage.get("provenance_complete"), bool), "provenance_complete must be boolean")

    provenance = packet.get("source_provenance")
    _expect(isinstance(provenance, Mapping), "source_provenance must be an object")
    _expect(_as_text(provenance.get("generation_stage")), "generation_stage is required")
    _expect(_as_text(provenance.get("generation_run_id")), "generation_run_id is required")
    _expect(isinstance(provenance.get("source_set_ids"), Mapping), "source_set_ids must be an object")
    _expect(
        isinstance(provenance.get("source_document_ids"), list) and provenance.get("source_document_ids"),
        "source_document_ids must be a non-empty list",
    )

    _expect(
        packet.get("content_source_mode") in {
            CONTENT_SOURCE_MODE_PRIMARY,
            CONTENT_SOURCE_MODE_TRACE_REPAIR,
            CONTENT_SOURCE_MODE_DRAFT_PRIMARY,
        },
        "content_source_mode invalid",
    )
    _expect(isinstance(packet.get("content_repair_applied"), bool), "content_repair_applied must be boolean")
    _expect(isinstance(packet.get("content_repair_reason"), str), "content_repair_reason must be a string")
    for key in ("original_content_source", "review_content_source"):
        content_source = packet.get(key)
        _expect(isinstance(content_source, Mapping), f"{key} must be an object")
        _expect(_as_text(content_source.get("definition_source")), f"{key}.definition_source is required")
        _expect(_as_text(content_source.get("evidence_source")), f"{key}.evidence_source is required")
    _expect(isinstance(packet.get("integrity_repair_notes"), list), "integrity_repair_notes must be a list")
    if packet.get("content_repair_applied") is True:
        if packet.get("content_repair_reason") == CONTENT_REPAIR_REASON_INCOHERENT:
            _expect(packet.get("content_source_mode") == CONTENT_SOURCE_MODE_TRACE_REPAIR, "incoherent repaired packet must use trace_selected_repair mode")
        debug_original = packet.get("debug_original_content")
        _expect(isinstance(debug_original, Mapping), "repaired packet must preserve debug_original_content")
        _expect(isinstance(debug_original.get("definition_draft"), str), "debug_original_content.definition_draft must be a string")
        _expect(isinstance(debug_original.get("evidence_spans"), list), "debug_original_content.evidence_spans must be a list")

    review_priority = packet.get("review_priority")
    _expect(isinstance(review_priority, Mapping), "review_priority must be an object")
    _expect(
        review_priority.get("bucket") in {"high_support", "moderate_support", "needs_review", "low_support"},
        "review_priority.bucket invalid",
    )
    _expect(isinstance(review_priority.get("rank_score"), int), "review_priority.rank_score must be an int")
    _expect(isinstance(review_priority.get("reason_codes"), list), "review_priority.reason_codes must be a list")
    _expect(isinstance(review_priority.get("missing_feature_keys"), list), "review_priority.missing_feature_keys must be a list")
    _expect(_as_text(review_priority.get("rule_version")), "review_priority.rule_version is required")

    recommendation = packet.get("system_recommendation")
    _expect(isinstance(recommendation, Mapping), "system_recommendation must be an object")
    _expect(
        recommendation.get("label") in {"approve_ready", "review_needed", "reject_recommended"},
        "system_recommendation.label invalid",
    )
    _expect(isinstance(recommendation.get("reason_codes"), list), "system_recommendation.reason_codes must be a list")
    _expect(_as_text(recommendation.get("rule_version")), "system_recommendation.rule_version is required")


def _field_source_map() -> dict[str, str]:
    return {
        "review_packet_id": "adapter-derived from source run id plus kc_id",
        "packet_state": "adapter constant: review_ready",
        "kc_candidate_id": "kc_library.jsonl.kc_id",
        "title_draft": "kc_library.jsonl.canonical_name",
        "level_draft": "adapter constant for current leaf-only Step 6 outputs: atomic",
        "definition_draft": "kc_library.jsonl.definition_short/full or enrichment trace definition text; for incoherent packets the reviewer-facing definition may be repaired from grounded trace-selected content, and for weak definition surfaces it may be replaced by a better grounded packet-evidence quote or a grounded packet-plus-trace composite surface",
        "evidence_spans": "kc_library.jsonl.evidence_minimal, else grounded fallback from enrichment_traces.top_candidates_before_gating; for incoherent packets only, reviewer-facing evidence may be replaced by grounded trace-selected candidates",
        "evidence_coverage_summary": "adapter-derived from packet evidence spans plus definition_short_contract_audit.jsonl, tier2_recovery_queue.jsonl, and enrichment trace signals",
        "source_provenance": "adapter-derived from source run id, kc_library.jsonl.source_set_ids, and packet evidence provenance",
        "content_source_mode": "adapter marker for default kc_library precedence vs reviewer-facing repair mode",
        "content_repair_applied": "adapter boolean set when reviewer-facing packet content is repaired for incoherence or weak definition surfaces",
        "content_repair_reason": "adapter machine-readable reason for any reviewer-facing content repair",
        "original_content_source": "adapter record of the source paths used before any repair",
        "review_content_source": "adapter record of the source paths used for the final reviewer-facing packet content",
        "integrity_repair_notes": "adapter machine-readable notes describing which packet fields were repaired",
        "risk_flags": "adapter-normalized from definition status, support downgrade, contamination, sibling ambiguity, contract checks, fallback-evidence use, packet-integrity checks, and any content repair flag",
        "review_priority": "src/kc_l/kc/supervision.py computed from adapter-built priority features, then conservatively capped by the packet-integrity gate when packet coherence, provenance, or repair signals make approve_ready unsafe",
        "system_recommendation": "src/kc_l/kc/supervision.py derived from review_priority, then re-derived after any packet-integrity downgrade",
    }


def _grounding_rules() -> dict[str, str]:
    return {
        "required_evidence_rule": "Emit a packet only when at least one evidence span can be grounded from kc_library.jsonl.evidence_minimal, trace top_candidates_before_gating, or a coherent trace-selected repair path.",
        "definition_rule": "Prefer machine draft definition_short, then definition_full, then trace text; leave empty only when source artifacts are empty.",
        "missing_current_feature_rule": "Missing required-now supervision features are recorded and may cap review priority to needs_review; they are never imputed positively.",
        "accepted_quote_count_rule": "Use tier2_recovery_queue accepted_quote_count when present; otherwise derive from quote_verified packet evidence spans.",
        "fallback_evidence_rule": "Trace fallback evidence is marked in risk_flags and coverage_note so unsupported or downgraded cases remain auditable.",
        "integrity_gate_rule": "Schema-valid packets are conservatively downgraded when title-definition coherence, title-evidence coherence, definition presence, fallback-only evidence, thin support, provenance adjustment, or content-repair signals indicate that approve_ready would be unsafe.",
        "content_repair_rule": "For integrity_packet_incoherent cases only, prefer coherent trace-selected content over stale kc_library reviewer-facing content, preserve the original content in debug metadata, and keep the repaired packet at least review_needed.",
        "definition_surface_refinement_rule": "When a reviewer-facing definition is title-like, heading-like, or a formula lead-in, replace it only if an already-grounded packet evidence quote is clearly better or if a grounded trace candidate can be conservatively composed with anchored packet content; otherwise keep the packet conservative and do not allow approve_ready to survive on weak wording alone.",
        "incoherent_skip_rule": "If neither the original packet content nor the grounded trace-selected repair path yields coherent reviewer-facing content, skip the packet and record the reason in summary output.",
    }


def build_summary(
    *,
    source_processed_dir: Path,
    output_dir: Path,
    packets: Sequence[Mapping[str, Any]],
    skips: Sequence[PacketSkip],
) -> dict[str, Any]:
    priority_counts = Counter(packet["review_priority"]["bucket"] for packet in packets)
    recommendation_counts = Counter(packet["system_recommendation"]["label"] for packet in packets)
    risk_flag_counts = Counter(flag for packet in packets for flag in packet.get("risk_flags") or [])
    integrity_flag_counts = Counter(
        flag for packet in packets for flag in packet.get("risk_flags") or [] if str(flag).startswith(INTEGRITY_FLAG_PREFIX)
    )
    missing_current_feature_counts = Counter(
        key
        for packet in packets
        for key in packet["review_priority"].get("missing_feature_keys") or []
        if key in CURRENT_REQUIRED_PRIORITY_FEATURES
    )
    integrity_capped_packets = [
        {
            "kc_candidate_id": packet["kc_candidate_id"],
            "bucket": packet["review_priority"]["bucket"],
            "recommendation": packet["system_recommendation"]["label"],
            "reason_codes": [
                str(code)
                for code in packet["review_priority"].get("reason_codes") or []
                if str(code).startswith("integrity:")
                or str(code).startswith("integrity_bucket_cap:")
                or str(code).startswith("integrity_rule_version:")
            ],
        }
        for packet in packets
        if any(str(code).startswith("integrity_bucket_cap:") for code in packet["review_priority"].get("reason_codes") or [])
    ]
    content_repaired_packets = [
        {
            "kc_candidate_id": packet["kc_candidate_id"],
            "content_repair_reason": packet.get("content_repair_reason", ""),
            "original_content_source": dict(packet.get("original_content_source") or {}),
            "review_content_source": dict(packet.get("review_content_source") or {}),
            "integrity_repair_notes": list(packet.get("integrity_repair_notes") or []),
        }
        for packet in packets
        if packet.get("content_repair_applied") is True
    ]
    definition_surface_refined_packets = [
        {
            "kc_candidate_id": packet["kc_candidate_id"],
            "original_definition_draft": _as_text((packet.get("debug_original_content") or {}).get("definition_draft")),
            "refined_definition_draft": _as_text(packet.get("definition_draft")),
            "review_definition_source": _as_text((packet.get("review_content_source") or {}).get("definition_source")),
        }
        for packet in packets
        if packet.get("content_repair_reason") == CONTENT_REPAIR_REASON_WEAK_DEFINITION_SURFACE
    ]
    remaining_incoherent_packets = [
        packet["kc_candidate_id"]
        for packet in packets
        if "integrity_packet_incoherent" in (packet.get("risk_flags") or [])
    ]

    return {
        "source_processed_dir": str(source_processed_dir),
        "output_dir": str(output_dir),
        "source_run_id": source_processed_dir.name,
        "lane": detect_lane(source_processed_dir),
        "packet_count": len(packets),
        "skipped_candidate_count": len(skips),
        "priority_bucket_counts": dict(priority_counts),
        "system_recommendation_counts": dict(recommendation_counts),
        "risk_flag_counts": dict(risk_flag_counts),
        "integrity_rule_version": INTEGRITY_RULE_VERSION,
        "integrity_flag_counts": dict(integrity_flag_counts),
        "integrity_capped_packet_count": len(integrity_capped_packets),
        "integrity_capped_packets": integrity_capped_packets,
        "content_repaired_packet_count": len(content_repaired_packets),
        "content_repaired_packets": content_repaired_packets,
        "definition_surface_refined_packet_count": len(definition_surface_refined_packets),
        "definition_surface_refined_packets": definition_surface_refined_packets,
        "remaining_incoherent_packet_count": len(remaining_incoherent_packets),
        "remaining_incoherent_packets": remaining_incoherent_packets,
        "missing_current_feature_counts": dict(missing_current_feature_counts),
        "skipped_candidates": [
            {"kc_candidate_id": skip.kc_candidate_id, "reasons": list(skip.reasons)}
            for skip in skips
        ],
        "field_source_map": _field_source_map(),
        "grounding_rules": _grounding_rules(),
    }


def build_preview_markdown(
    *,
    source_processed_dir: Path,
    packets: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    max_preview_items: int = 5,
) -> str:
    lines = [
        "# Review Packet Preview",
        "",
        f"- Source processed dir: `{source_processed_dir}`",
        f"- Packet count: `{summary['packet_count']}`",
        f"- Skipped candidates: `{summary['skipped_candidate_count']}`",
        f"- Priority buckets: `{summary['priority_bucket_counts']}`",
        f"- System recommendations: `{summary['system_recommendation_counts']}`",
        f"- Integrity caps: `{summary.get('integrity_capped_packet_count', 0)}`",
        f"- Content repaired packets: `{summary.get('content_repaired_packet_count', 0)}`",
        f"- Definition-surface refined packets: `{summary.get('definition_surface_refined_packet_count', 0)}`",
        f"- Remaining incoherent packets: `{summary.get('remaining_incoherent_packet_count', 0)}`",
        "",
        "## Sample Packets",
        "",
    ]

    urgency_order = {
        "low_support": 0,
        "needs_review": 1,
        "moderate_support": 2,
        "high_support": 3,
    }
    ordered_packets = sorted(
        packets,
        key=lambda packet: (
            urgency_order.get(packet["review_priority"]["bucket"], 99),
            packet["review_priority"]["rank_score"],
            packet["kc_candidate_id"],
        ),
    )
    for packet in ordered_packets[:max_preview_items]:
        coverage = packet["evidence_coverage_summary"]
        lines.extend(
            [
                f"### {packet['kc_candidate_id']} - {packet['title_draft']}",
                "",
                f"- Priority: `{packet['review_priority']['bucket']}`",
                f"- Recommendation: `{packet['system_recommendation']['label']}`",
                f"- Content source mode: `{packet['content_source_mode']}`",
                f"- Content repair applied: `{packet['content_repair_applied']}`",
                f"- Priority reasons: `{packet['review_priority']['reason_codes']}`",
                f"- Recommendation reasons: `{packet['system_recommendation']['reason_codes']}`",
                f"- Definition support: `{coverage['definition_support_state']}`",
                f"- Evidence spans: `{coverage['evidence_span_count']}`",
                f"- Coverage labels: `{coverage['coverage_labels']}`",
                f"- Risk flags: `{packet['risk_flags']}`",
                f"- Definition draft: `{packet['definition_draft']}`",
                "",
            ]
        )
    if summary["content_repaired_packet_count"]:
        lines.extend(["## Repaired Packets", ""])
        for item in summary["content_repaired_packets"]:
            lines.append(
                f"- `{item['kc_candidate_id']}`: `{item['content_repair_reason']}` via `{item['review_content_source'].get('evidence_source', '')}`"
            )
    if summary["skipped_candidate_count"]:
        lines.extend(["", "## Skipped Candidates", ""])
        for item in summary["skipped_candidates"]:
            lines.append(f"- `{item['kc_candidate_id']}`: {', '.join(item['reasons'])}")
    return "\n".join(lines).rstrip() + "\n"


def emit_review_packets_from_processed_dir(
    *,
    source_processed_dir: Path,
    output_dir: Path,
) -> ReviewPacketEmissionResult:
    source_processed_dir = source_processed_dir.resolve()
    output_dir = output_dir.resolve()

    records = read_jsonl(source_processed_dir / "kc_library.jsonl")
    short_audit_lookup = _load_lookup(source_processed_dir / "definition_short_contract_audit.jsonl")
    tier2_lookup = _load_lookup(source_processed_dir / "tier2_recovery_queue.jsonl")
    trace_lookup = _load_trace_lookup(source_processed_dir / "enrichment_traces")

    packets: list[dict[str, Any]] = []
    skips: list[PacketSkip] = []
    for record in records:
        kc_id = _as_text(record.get("kc_id"))
        short_audit = short_audit_lookup.get(kc_id, {})
        tier2_row = tier2_lookup.get(kc_id, {})
        trace = trace_lookup.get(kc_id, {})
        try:
            packet = build_review_packet(
                source_processed_dir=source_processed_dir,
                record=record,
                short_audit=short_audit,
                tier2_row=tier2_row,
                trace=trace,
            )
            validate_review_packet(packet)
            packets.append(packet)
        except ValueError as exc:
            skips.append(PacketSkip(kc_candidate_id=kc_id, reasons=(str(exc),)))

    summary = build_summary(
        source_processed_dir=source_processed_dir,
        output_dir=output_dir,
        packets=packets,
        skips=skips,
    )
    preview = build_preview_markdown(
        source_processed_dir=source_processed_dir,
        packets=packets,
        summary=summary,
    )

    packet_path = output_dir / "review_packet.jsonl"
    summary_path = output_dir / "review_packet_summary.json"
    preview_path = output_dir / "review_packet_preview.md"
    write_jsonl(packet_path, packets)
    write_json(summary_path, summary)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(preview, encoding="utf-8")

    return ReviewPacketEmissionResult(
        output_dir=output_dir,
        packet_path=packet_path,
        summary_path=summary_path,
        preview_path=preview_path,
        packet_count=len(packets),
        skipped_candidate_count=len(skips),
    )
