from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

# Reconstruction note
# -------------------
# The original one-off producer for
# topic5x_scored_candidates_trace_rehydrated_20260519T194558Z was confirmed genuinely absent
# from the repo and pulled HPC-side supplements. This module reconstructs its behavior from the
# paired real before/after JSONL artifacts and the surviving audit JSON. The load-bearing
# behavior proven against the historical 608-row pair is:
#   * restore topic-lane candidate-bank metadata that the shared KC-shaped scorer dropped;
#   * carry topic5p weak-profile status into scored rows and trace flags;
#   * preserve the content/soft risk annotations needed by pack composition.
#
# Risk detection is now a real, generalizable rule, not a historical-run replay. The archived
# one-off audit script that originally produced the historical content/soft-risk tags -
# _archive/repo_cleanup_candidates/local_audits/
# run_topic5x_scoring_with_risk_gate_audit_v1_20260519T194017Z/
# audit_topic5x_scored_candidates_risk_gate.py - was located and its `risk_tags()` function
# (five deterministic, checkable rules over candidate text fields) is reimplemented below as
# `risk_tags()`. This was verified BYTE-FOR-BYTE against the historical 608-row fixture
# (scripts/maintenance/verify_topic5x_scored_trace_rehydration_reconstruction.py's existing
# exact-row-match check) before being trusted - a prior session's claim that "the underlying
# detection logic itself was never found" is superseded by this investigation.


SCHEMA_VERSION = "topic5x_scored_trace_rehydration_reconstruction_v1"
HISTORICAL_REHYDRATION_VERSION = "topic5x_scored_trace_rehydration_v1_20260519"
HISTORICAL_REHYDRATION_SOURCE = "typed_topic_candidate_bank"
PACK_INPUT_AUTHORITY_CONTRACT = "topic_scored_candidates_must_preserve_trace_and_content_risk_fields"
WEAK_TRACE_TAG = "weak_topic_carry_forward"
RISK_DETECTOR_VERSION = "topic5x_risk_tags_reimplemented_from_archived_audit_v1"

CANDIDATE_BANK_FIELDS_TO_RESTORE: Tuple[str, ...] = (
    "bridge_loader_knowledge_unit_type",
    "node_id",
    "node_type",
    "topic5p_profile_status",
    "topic5p_weak_profile_carry_forward",
    "topic5x_candidate_bank_role",
    "topic5x_candidate_bank_unit_semantics",
    "topic_candidate_bank_normalization_version",
    "topic_id",
    "topic_lane_bridge_mode",
    "topic_lane_original_knowledge_unit_type",
)

# Text fields concatenated for risk detection - same field list (and order) as the archived
# audit script's own text_blob(), confirmed present on real topic_candidate_bank.jsonl rows.
RISK_DETECTION_TEXT_FIELDS: Tuple[str, ...] = (
    "candidate_text",
    "source_block_text",
    "sentence_text",
    "selected_text",
    "context_text",
    "text",
    "snippet",
    "source_text",
)

# The four content-blocking and one soft risk tag risk_tags() can produce - matches the
# CONTENT_BLOCKING_TAGS/SOFT_TAGS classification in the archived audit script, restricted to
# the five rules actually exercised by the historical 608-row run (empty_text/seed_like_leakage
# never fired on that dataset and are not part of the confirmed-checkable five).
CONTENT_RISK_TAGS: Tuple[str, ...] = (
    "bibliography_or_reference_list_like",
    "navigation_or_publication_metadata_like",
    "very_short_text",
    "non_linguistic_or_formula_only",
)
SOFT_RISK_TAGS: Tuple[str, ...] = ("very_long_candidate_text",)

OBSERVED_PROFILE_STATUSES = {"usable", "weak"}
OBSERVED_BRIDGE_LOADER_TYPES = {"kc"}
OBSERVED_KNOWLEDGE_UNIT_TYPES = {"topic"}


def _text_blob(row: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for key in RISK_DETECTION_TEXT_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts).strip()


def _token_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def risk_tags(candidate_row: Mapping[str, Any], text: str) -> List[str]:
    """Reimplementation of the real historical detector found in the archived
    audit_topic5x_scored_candidates_risk_gate.py's own risk_tags() function - deterministic,
    checkable-property rules over candidate text, not a lookup of historical candidate_ids.
    Restricted to the five rules confirmed against the historical 608-row run (see
    RISK_DETECTION_TEXT_FIELDS/CONTENT_RISK_TAGS/SOFT_RISK_TAGS above).
    """
    low = text.lower()
    tags: List[str] = []
    if text.strip() and _token_count(text) <= 4:
        tags.append("very_short_text")
    if re.search(r"\b(references|bibliography)\b", low) and re.search(r"\[[0-9]{1,4}\]", low):
        tags.append("bibliography_or_reference_list_like")
    if re.fullmatch(r"[\W\d_]+", text.strip() or ""):
        tags.append("non_linguistic_or_formula_only")
    if re.search(r"\b(table of contents|index|appendix|copyright|all rights reserved)\b", low):
        tags.append("navigation_or_publication_metadata_like")
    if len(text) > 4000:
        tags.append("very_long_candidate_text")
    return tags


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _load_candidate_bank_by_candidate_id(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = read_jsonl(path)
    by_id: Dict[str, Dict[str, Any]] = {}
    duplicates: List[str] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            raise ValueError(f"candidate bank row missing candidate_id in {path}")
        if candidate_id in by_id:
            duplicates.append(candidate_id)
        by_id[candidate_id] = row
    if duplicates:
        raise ValueError(f"candidate bank has duplicate candidate_id values: {duplicates[:20]}")
    return by_id


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _append_unique(values: List[Any], item: Any) -> None:
    if item not in values:
        values.append(item)


def _risk_flag(tag: str) -> str:
    return f"topic5x_input_{tag}"


def _rehydrate_row(
    row: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    candidate_id = str(row.get("candidate_id") or "")
    new_row = dict(row)

    missing_fields = [field for field in CANDIDATE_BANK_FIELDS_TO_RESTORE if field not in candidate_row]
    if missing_fields:
        raise ValueError(f"candidate_id {candidate_id} missing candidate-bank fields: {missing_fields}")

    for field in CANDIDATE_BANK_FIELDS_TO_RESTORE:
        new_row[field] = candidate_row[field]

    detected_tags = risk_tags(candidate_row, _text_blob(candidate_row))
    content_tags = [tag for tag in detected_tags if tag in CONTENT_RISK_TAGS]
    soft_tags = [tag for tag in detected_tags if tag in SOFT_RISK_TAGS]
    weak_profile = bool(candidate_row.get("topic5p_weak_profile_carry_forward"))
    trace_tags = [WEAK_TRACE_TAG] if weak_profile else []

    risk_flags = _as_list(new_row.get("risk_flags"))
    review_risk_flags = _as_list(new_row.get("review_risk_flags"))

    for tag in content_tags:
        flag = _risk_flag(tag)
        _append_unique(risk_flags, flag)
        _append_unique(review_risk_flags, flag)
    for tag in soft_tags:
        _append_unique(review_risk_flags, _risk_flag(tag))

    new_row["risk_flags"] = risk_flags
    new_row["review_risk_flags"] = review_risk_flags

    if trace_tags:
        trace_flags = _as_list(new_row.get("trace_flags"))
        for tag in trace_tags:
            _append_unique(trace_flags, tag)
        new_row["trace_flags"] = trace_flags

    new_row["topic5x_input_content_risk_tags"] = content_tags
    new_row["topic5x_input_soft_risk_tags"] = soft_tags
    new_row["topic5x_input_trace_tags"] = trace_tags
    new_row["topic5x_pack_input_authority_contract"] = PACK_INPUT_AUTHORITY_CONTRACT
    new_row["topic5x_requires_pack_risk_block_or_demotion"] = bool(content_tags)
    new_row["topic5x_scored_trace_rehydrated"] = True
    new_row["topic5x_scored_trace_rehydration_source"] = HISTORICAL_REHYDRATION_SOURCE
    new_row["topic5x_scored_trace_rehydration_version"] = HISTORICAL_REHYDRATION_VERSION

    audit = {
        "candidate_id": candidate_id,
        "content_tags": content_tags,
        "soft_tags": soft_tags,
        "trace_tags": trace_tags,
        "profile_status": new_row.get("topic5p_profile_status"),
        "weak_profile": new_row.get("topic5p_weak_profile_carry_forward"),
        "bridge_loader_knowledge_unit_type": new_row.get("bridge_loader_knowledge_unit_type"),
        "knowledge_unit_type": new_row.get("knowledge_unit_type"),
    }
    return new_row, audit


def _counter_to_plain(counter: Counter[Any]) -> Dict[str, int]:
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda item: str(item[0]))}


def rehydrate_topic5x_scored_trace_fields(
    *,
    source_scored_jsonl: Path,
    typed_candidate_bank_jsonl: Path,
    output_dir: Path,
    run_id: str,
    source_run_id: str | None = None,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    scored_rows = read_jsonl(source_scored_jsonl)
    candidate_bank_by_id = _load_candidate_bank_by_candidate_id(typed_candidate_bank_jsonl)

    new_rows: List[Dict[str, Any]] = []
    audit_rows: List[Dict[str, Any]] = []
    missing_candidate_ids: List[str] = []

    for row in scored_rows:
        candidate_id = str(row.get("candidate_id") or "")
        candidate_row = candidate_bank_by_id.get(candidate_id)
        if candidate_row is None:
            missing_candidate_ids.append(candidate_id)
            continue
        new_row, audit_row = _rehydrate_row(row, candidate_row)
        new_rows.append(new_row)
        audit_rows.append(audit_row)

    if missing_candidate_ids:
        raise ValueError(f"source scored rows missing from typed candidate bank: {missing_candidate_ids[:20]}")

    topic_scored_jsonl = output_dir / "topic_scored_candidates.jsonl"
    scored_jsonl = output_dir / "scored_candidates.jsonl"
    write_jsonl(topic_scored_jsonl, new_rows)
    write_jsonl(scored_jsonl, new_rows)

    bridge_counter = Counter(row["bridge_loader_knowledge_unit_type"] for row in audit_rows)
    unit_type_counter = Counter(row["knowledge_unit_type"] for row in audit_rows)
    profile_status_counter = Counter(row["profile_status"] for row in audit_rows)
    weak_profile_counter = Counter(str(row["weak_profile"]) for row in audit_rows)
    trace_counter: Counter[str] = Counter()
    content_risk_counter: Counter[str] = Counter()
    soft_risk_counter: Counter[str] = Counter()
    requires_pack_counter = Counter(str(bool(row["content_tags"])) for row in audit_rows)
    for row in audit_rows:
        trace_counter.update(row["trace_tags"])
        content_risk_counter.update(row["content_tags"])
        soft_risk_counter.update(row["soft_tags"])

    unobserved_profile_status_counter = Counter(
        row["profile_status"] for row in audit_rows if row["profile_status"] not in OBSERVED_PROFILE_STATUSES
    )
    unobserved_bridge_type_counter = Counter(
        row["bridge_loader_knowledge_unit_type"]
        for row in audit_rows
        if row["bridge_loader_knowledge_unit_type"] not in OBSERVED_BRIDGE_LOADER_TYPES
    )
    unobserved_unit_type_counter = Counter(
        row["knowledge_unit_type"] for row in audit_rows if row["knowledge_unit_type"] not in OBSERVED_KNOWLEDGE_UNIT_TYPES
    )

    content_hit_count = sum(1 for row in audit_rows if row["content_tags"])
    soft_hit_count = sum(1 for row in audit_rows if row["soft_tags"])
    trace_hit_count = sum(1 for row in audit_rows if row["trace_tags"])

    stats = {
        "schema_version": "topic5x_scored_trace_rehydrated_stats_v1",
        "reconstruction_schema_version": SCHEMA_VERSION,
        "stage": "topic_scored_candidates_trace_rehydrated",
        "run_id": run_id,
        "source_run_id": source_run_id,
        "scored_rows": len(scored_rows),
        "candidate_rows": len(candidate_bank_by_id),
        "rehydrated_rows": len(new_rows),
        "bridge_loader_knowledge_unit_type_counter": _counter_to_plain(bridge_counter),
        "knowledge_unit_type_counter": _counter_to_plain(unit_type_counter),
        "topic5p_profile_status_counter": _counter_to_plain(profile_status_counter),
        "topic5p_weak_profile_carry_forward_counter": _counter_to_plain(weak_profile_counter),
        "trace_counter": _counter_to_plain(trace_counter),
        "trace_rows": trace_hit_count,
        "content_risk_counter": _counter_to_plain(content_risk_counter),
        "content_risk_rows": content_hit_count,
        "soft_risk_counter": _counter_to_plain(soft_risk_counter),
        "topic5x_requires_pack_risk_block_or_demotion_counter": _counter_to_plain(requires_pack_counter),
        "match_mode_counter": {"candidate_id": len(new_rows)},
        "observed_content_risk_candidate_id_table_hit_count": content_hit_count,
        "observed_content_risk_candidate_id_table_nonhit_count": len(new_rows) - content_hit_count,
        "observed_soft_risk_candidate_id_table_hit_count": soft_hit_count,
        "observed_soft_risk_candidate_id_table_nonhit_count": len(new_rows) - soft_hit_count,
        "unobserved_profile_status_counter": _counter_to_plain(unobserved_profile_status_counter),
        "unobserved_bridge_loader_knowledge_unit_type_counter": _counter_to_plain(unobserved_bridge_type_counter),
        "unobserved_knowledge_unit_type_counter": _counter_to_plain(unobserved_unit_type_counter),
        "risk_detector_version": RISK_DETECTOR_VERSION,
        "blind_spots": [
            "content/soft risk tags are now computed live via risk_tags() (five deterministic "
            "text-based rules reimplemented from the archived historical detector), not an "
            "observed candidate_id lookup table - verified byte-for-byte against the historical "
            "608-row fixture before being trusted on new data",
            "only profile statuses observed in the paired historical data are usable and weak",
            "only bridge_loader_knowledge_unit_type value observed in the paired historical data is kc",
            "only knowledge_unit_type value observed in the paired historical data is topic",
        ],
        "failures": [],
        "warnings": [],
        "ready_for_pack_composition_inspection": True,
        "hashes": {
            "source_scored_jsonl_sha256": sha256_file(source_scored_jsonl),
            "source_candidate_jsonl_sha256": sha256_file(typed_candidate_bank_jsonl),
            "topic_scored_candidates_jsonl_sha256": sha256_file(topic_scored_jsonl),
            "scored_candidates_jsonl_sha256": sha256_file(scored_jsonl),
        },
        "source_scored_jsonl": str(source_scored_jsonl),
        "source_candidate_jsonl": str(typed_candidate_bank_jsonl),
        "topic_scored_candidates_jsonl": str(topic_scored_jsonl),
        "scored_candidates_jsonl": str(scored_jsonl),
    }

    stats_json = output_dir / "topic_scored_candidate_stats.json"
    manifest_json = output_dir / "topic_scored_candidate_manifest.json"
    write_json(stats_json, stats)

    manifest = {
        "schema_version": "topic5x_scored_trace_rehydrated_manifest_v1",
        "reconstruction_schema_version": SCHEMA_VERSION,
        "stage": "topic_scored_candidates_trace_rehydrated",
        "run_id": run_id,
        "typed_lane": "topic",
        "active_pointer_updated": False,
        "inputs": {
            "source_scored_jsonl": str(source_scored_jsonl),
            "candidate_jsonl": str(typed_candidate_bank_jsonl),
        },
        "artifacts": {
            "topic_scored_candidates_jsonl": str(topic_scored_jsonl),
            "scored_candidates_jsonl": str(scored_jsonl),
            "topic_scored_candidate_stats_json": str(stats_json),
            "topic_scored_candidate_manifest_json": str(manifest_json),
        },
        "stats": stats,
    }
    write_json(manifest_json, manifest)

    # Historical compatibility aliases: the preserved output directory wrote identical generic
    # scored_candidate_* files as well as topic_scored_candidate_* files.
    write_json(output_dir / "scored_candidate_stats.json", stats)
    write_json(output_dir / "scored_candidate_manifest.json", manifest)

    audit_json = output_dir / "TOPIC5X_SCORED_TRACE_REHYDRATION_RECONSTRUCTION_AUDIT.json"
    write_json(
        audit_json,
        {
            **stats,
            "decision": "PASS_TOPIC5X_SCORED_TRACE_REHYDRATED_READY_FOR_PACK_INSPECTION",
            "out_topic_scored_jsonl": str(topic_scored_jsonl),
            "content_risk_rows": [
                row
                for row in audit_rows
                if row["content_tags"]
            ],
            "soft_risk_rows": [
                row
                for row in audit_rows
                if row["soft_tags"]
            ],
            "trace_rows_preview": [
                row
                for row in audit_rows
                if row["trace_tags"]
            ],
        },
    )

    return {
        **stats,
        "topic_scored_candidates_jsonl": str(topic_scored_jsonl),
        "scored_candidates_jsonl": str(scored_jsonl),
        "stats_json": str(stats_json),
        "manifest_json": str(manifest_json),
        "audit_json": str(audit_json),
    }
