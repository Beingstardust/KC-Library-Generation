"""Strict schema + validation for one expert-curated reference KC record.

Enforces the two-stage protocol structurally: a record cannot be constructed as
"committed" without Stage-A (source-first review) having been committed first, and
Stage-A's memo is immutable once committed (the console must never call
build_stage_a with different field values for a kc_id that already has a committed
Stage-A record - see reference_console.py's commit guard).

This module does not decide anything on the expert's behalf. It only enforces that
whatever the expert decides is structurally complete and internally consistent
before it can be committed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

SUPPORT_STATES = ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "AMBIGUOUS_OR_CONFLICTING")

EXPERT_ACTIONS = ("ACCEPT", "MINOR_EDIT", "MAJOR_EDIT", "REPLACE", "NO_REFERENCE_CORPUS_UNSUPPORTED")

REASON_CODES = (
    "NONE", "WRONG_TARGET", "FACTUAL_ERROR", "WRONG_FORMULA", "WRONG_PROCEDURE",
    "WRONG_RELATION", "WRONG_TAXONOMY", "MISSING_DEFINITION", "MISSING_FORMULA",
    "MISSING_CONDITION", "MISSING_PROCEDURE", "MISSING_DISTINCTION", "OVERREACH",
    "UNSUPPORTED_CLAIM", "SOURCE_AMBIGUITY", "TERMINOLOGY_NOTATION", "OTHER",
)

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


class SchemaError(ValueError):
    pass


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_of(obj) -> str:
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class SourceRef:
    sentence_id: str  # must resolve in sentence_corpus.jsonl - checked by validate_reference_provenance.py
    doc_id: str = ""
    excerpt: str = ""  # short human-readable excerpt for the record; not authoritative, sentence_id is

    def validate(self) -> None:
        if not self.sentence_id or not self.sentence_id.strip():
            raise SchemaError("SourceRef.sentence_id must be non-empty")


@dataclass
class StageASourceFirstReview:
    support_state: str
    source_refs: list
    source_memo: str
    search_log: list = field(default_factory=list)
    committed_at: str = ""
    sha256: str = ""

    def validate(self) -> None:
        if self.support_state not in SUPPORT_STATES:
            raise SchemaError(f"support_state must be one of {SUPPORT_STATES}, got {self.support_state!r}")
        if self.support_state in ("SUPPORTED", "PARTIALLY_SUPPORTED") and not self.source_refs:
            raise SchemaError(f"{self.support_state} requires at least one source_ref")
        if self.support_state == "AMBIGUOUS_OR_CONFLICTING" and not self.source_refs:
            raise SchemaError("AMBIGUOUS_OR_CONFLICTING requires citations to the conflicting/ambiguous material")
        if self.support_state == "UNSUPPORTED" and not (self.source_memo or "").strip():
            raise SchemaError("UNSUPPORTED requires a brief search/audit note in source_memo explaining why no adequate source support was found")
        if not (self.source_memo or "").strip():
            raise SchemaError("source_memo (pre_seed_source_memo) must be non-empty")
        word_count = len(self.source_memo.split())
        if word_count > 120:
            raise SchemaError(
                f"source_memo is {word_count} words - this is meant to be a short 1-4 sentence memo, "
                "not a full reference definition. If you are trying to write the actual reference, "
                "that happens in Stage C after the seed is revealed."
            )
        for ref in self.source_refs:
            (ref if isinstance(ref, SourceRef) else SourceRef(**ref)).validate()

    def to_committed_dict(self) -> dict:
        self.validate()
        refs = [asdict(r) if isinstance(r, SourceRef) else r for r in self.source_refs]
        payload = {
            "support_state": self.support_state,
            "source_refs": refs,
            "source_memo": self.source_memo,
            "search_log": self.search_log,
        }
        committed_at = utcnow_iso()
        return {
            **payload,
            "committed_at": committed_at,
            "sha256": sha256_of({**payload, "committed_at": committed_at}),
        }


@dataclass
class ExpertEdit:
    action: str
    reason_codes: list
    reference_body: str
    reference_provenance: list  # list of {"claim": str, "source_refs": [sentence_id,...]}
    confidence: str
    review_seconds: float = None
    committed_at: str = ""
    sha256: str = ""

    def validate(self) -> None:
        if self.action not in EXPERT_ACTIONS:
            raise SchemaError(f"action must be one of {EXPERT_ACTIONS}, got {self.action!r}")
        for code in self.reason_codes:
            if code not in REASON_CODES:
                raise SchemaError(f"reason code {code!r} not in {REASON_CODES}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise SchemaError(f"confidence must be one of {CONFIDENCE_LEVELS}")

        if self.action == "NO_REFERENCE_CORPUS_UNSUPPORTED":
            if self.reference_body.strip():
                raise SchemaError("NO_REFERENCE_CORPUS_UNSUPPORTED requires an empty reference_body")
        else:
            if not self.reference_body.strip():
                raise SchemaError(f"action {self.action} requires a non-empty reference_body")
            if not self.reference_provenance:
                raise SchemaError(
                    f"action {self.action} requires at least one reference_provenance entry "
                    "(sentence/claim -> source reference)"
                )
            for entry in self.reference_provenance:
                if not entry.get("claim", "").strip():
                    raise SchemaError("every reference_provenance entry needs a non-empty 'claim'")
                if not entry.get("source_refs"):
                    raise SchemaError(f"reference_provenance claim {entry.get('claim')!r} has no source_refs")

    def to_committed_dict(self, seed_sha256: str) -> dict:
        self.validate()
        payload = {
            "seed_sha256": seed_sha256,
            "action": self.action,
            "reason_codes": self.reason_codes,
            "reference_body": self.reference_body,
            "reference_provenance": self.reference_provenance,
            "confidence": self.confidence,
            "review_seconds": self.review_seconds,
        }
        committed_at = utcnow_iso()
        return {
            **payload,
            "committed_at": committed_at,
            "sha256": sha256_of({**payload, "committed_at": committed_at}),
        }


@dataclass
class ReferenceRecord:
    kc_id: str
    canonical_name: str
    hierarchy_path: list
    source_first_review: dict = None  # committed StageASourceFirstReview dict, or None if not yet committed
    seed: dict = None  # {"seed_artifact_id": kc_id, "seed_sha256": ...}
    expert_edit: dict = None  # committed ExpertEdit dict, or None
    validation_status: str = "PENDING"
    amendments: list = field(default_factory=list)

    def validate_committable(self) -> None:
        if self.source_first_review is None:
            raise SchemaError(f"{self.kc_id}: cannot commit - Stage-A source_first_review not committed")
        if self.expert_edit is None:
            raise SchemaError(f"{self.kc_id}: cannot commit - Stage-B/C expert_edit not committed")
        if self.seed is None:
            raise SchemaError(f"{self.kc_id}: cannot commit - seed reference missing")

    def to_dict(self) -> dict:
        return {
            "kc_id": self.kc_id,
            "canonical_name": self.canonical_name,
            "hierarchy_path": self.hierarchy_path,
            "source_first_review": self.source_first_review,
            "seed": self.seed,
            "expert_edit": self.expert_edit,
            "validation_status": self.validation_status,
            "amendments": self.amendments,
        }
