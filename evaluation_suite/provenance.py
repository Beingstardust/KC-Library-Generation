"""Deterministic provenance validator (section 5.2). No LLM call - pure structural/referential
integrity checking against the CURRENT verified pipeline's real schema (PIPELINE_ARCHITECTURE.md
section 1.3), confirmed by direct inspection of real packet/draft JSONL, not assumed.

A citation is any evidence_id appearing in a draft's contextual_kc_draft.supporting_evidence_ids
or evidence_map[].supporting_evidence_ids. It resolves if and only if that evidence_id appears in
the SAME unit's own packet.evidence_for_synthesis list, and the referenced entry's doc_id and
text fields are both present and non-empty (a resolvable-but-empty entry is still a defect, not a
pass).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ProvenanceLink:
    kc_id: str
    evidence_id: str
    source: str  # "contextual_kc_draft" | "evidence_map"
    resolved: bool
    failure_reason: str | None = None


def _known_evidence_ids(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Maps evidence_id -> its full record from the packet's own evidence_for_synthesis list."""
    return {
        ev["evidence_id"]: ev
        for ev in packet.get("evidence_for_synthesis", []) or []
        if isinstance(ev, dict) and ev.get("evidence_id")
    }


def validate_draft_provenance(kc_id: str, draft_record: dict[str, Any], packet: dict[str, Any]) -> list[ProvenanceLink]:
    """Returns one ProvenanceLink per citation found in the draft (both citation sources),
    never silently drops a citation - every cited evidence_id gets exactly one link, resolved
    or not.
    """
    known = _known_evidence_ids(packet)
    links: list[ProvenanceLink] = []

    draft = draft_record.get("draft", draft_record)  # tolerate either the wrapper or inner shape
    contextual = draft.get("contextual_kc_draft", {}) or {}
    for evidence_id in contextual.get("supporting_evidence_ids", []) or []:
        links.append(_build_link(kc_id, evidence_id, "contextual_kc_draft", known))

    for claim in draft.get("evidence_map", []) or []:
        if not isinstance(claim, dict):
            continue
        for evidence_id in claim.get("supporting_evidence_ids", []) or []:
            links.append(_build_link(kc_id, evidence_id, "evidence_map", known))

    return links


def _build_link(kc_id: str, evidence_id: str, source: str, known: dict[str, dict[str, Any]]) -> ProvenanceLink:
    record = known.get(evidence_id)
    if record is None:
        return ProvenanceLink(kc_id=kc_id, evidence_id=evidence_id, source=source,
                               resolved=False, failure_reason="evidence_id not present in this unit's own packet")
    missing = [f for f in ("doc_id", "text") if not record.get(f)]
    if missing:
        return ProvenanceLink(kc_id=kc_id, evidence_id=evidence_id, source=source, resolved=False,
                               failure_reason=f"resolved but missing required field(s): {missing}")
    return ProvenanceLink(kc_id=kc_id, evidence_id=evidence_id, source=source, resolved=True)


@dataclass(frozen=True)
class ProvenanceReport:
    total_links: int
    resolved_links: int
    invalid_links: list[ProvenanceLink]
    provenance_resolution_rate: float | None

    def as_dict(self) -> dict:
        return {
            "total_links": self.total_links,
            "resolved_links": self.resolved_links,
            "invalid_link_count": len(self.invalid_links),
            "provenance_resolution_rate": self.provenance_resolution_rate,
            "invalid_links": [
                {"kc_id": l.kc_id, "evidence_id": l.evidence_id, "source": l.source,
                 "failure_reason": l.failure_reason}
                for l in self.invalid_links
            ],
        }


def summarize_provenance(links: Iterable[ProvenanceLink]) -> ProvenanceReport:
    links = list(links)
    total = len(links)
    resolved = sum(1 for l in links if l.resolved)
    invalid = [l for l in links if not l.resolved]
    rate = round(resolved / total, 6) if total else None
    return ProvenanceReport(total_links=total, resolved_links=resolved,
                             invalid_links=invalid, provenance_resolution_rate=rate)
