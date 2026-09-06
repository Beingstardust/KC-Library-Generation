"""Deterministic status-integrity gate for Step 6.7 KC drafts.

Confirmed corpus-wide (research_notes/step5p_5x_audits/status_integrity_reconciliation_20260805.md,
re-verified 2026-08-05 against live current HPC cluster data): 20.3% of non-abstained KC drafts (138/679)
across all 5 configs have zero real admitted evidence (evidence_lane == "ordered_pack_for_drafting")
in their own step5x-produced evidence pack, yet the drafting model still self-reports
contextual_kc_draft.status as "grounded" or "partial" - status is entirely self-reported by the
model with no deterministic gate behind it. This module is that gate.

Design decision (2026-08-05, confirmed before implementing): force status to "abstained" when the
condition holds, rather than introduce a new status label. Reuses all existing "abstained" handling
downstream (eval_rows resolution, review packet building, human review) with zero new enum value to
thread through consumers. The override touches ONLY the status field - contextual_kc_draft.text is
left untouched, so the original model-generated text remains available in the raw drafts JSONL for
forensic/diagnostic purposes even though it's correctly excluded from the trustworthy-library surface
(eval_rows.csv, review library) via the existing draft_text = ABSTAIN_SENTINEL-if-abstained logic.

Scope: KC-type units only. Topic-type units (hier::path::* records) synthesize primarily from
child-KC coverage rather than their own flat evidence list, and whether topic-level status is
actually grounded in child-KC coverage was explicitly flagged as an unconfirmed follow-up question
in the original audit - not the same confirmed failure mode, so intentionally out of scope here.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Tuple

ORDERED_PACK_LANE = "ordered_pack_for_drafting"
POSITIVE_STATUSES = ("grounded", "partial")
STATUS_INTEGRITY_GATE_VERSION = "step67_status_integrity_gate_v1"
ABSTENTION_INTEGRITY_GATE_VERSION = "step67_abstention_integrity_gate_v1"
ABSTAINED_STATUS = "abstained"
UNJUSTIFIED_ABSTENTION_CODE = "unjustified_abstention_on_draftable_packet"


def kc_admitted_evidence_count(packet: Mapping[str, Any]) -> int:
    """Count of this packet's own admitted evidence_for_synthesis items.

    2026-08-17 correction: this used to filter on evidence_lane == ORDERED_PACK_LANE
    ("ordered_pack_for_drafting"), which was the retired evidence_stage_v3_candidate_bank.py
    pipeline's lane vocabulary. The verified pipeline (evidence_pack.py / 02_build_kc_packets.py)
    stamps every item with a single fixed constant, evidence_lane="comprehensive_relevance_ranked"
    (confirmed: 02_build_kc_packets.py) - there is no multi-lane concept in the current schema.
    evidence_pack.py already performs all admission filtering (rival adjudication, damaged-math
    removal, relevance gating) before evidence_for_synthesis is ever written, so presence in that
    list already means "admitted"; no further filtering is needed or correct here. The old filter
    silently returned 0 for every real packet in this pipeline, which would have force-abstained
    every positive draft the one time this function's caller was made reachable - caught by testing
    against real data before it shipped, not assumed from reading the code.
    """
    items = packet.get("evidence_for_synthesis")
    if not isinstance(items, (list, tuple)):
        return 0
    return sum(1 for item in items if isinstance(item, Mapping))


def status_integrity_violation(packet: Mapping[str, Any], draft: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """Returns override metadata if this KC draft's self-reported status is not backed by any
    admitted evidence, else None. Does not mutate anything - callers apply the override themselves.
    """
    if not isinstance(draft, Mapping):
        return None
    unit_type = str(packet.get("knowledge_unit_type") or "")
    if unit_type != "kc":
        return None

    contextual = draft.get("contextual_kc_draft")
    if not isinstance(contextual, Mapping):
        return None

    status = str(contextual.get("status") or "").lower()
    if status not in POSITIVE_STATUSES:
        return None

    admitted_count = kc_admitted_evidence_count(packet)
    if admitted_count > 0:
        return None

    upstream = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), Mapping) else {}
    packet_support_state = str(packet.get("packet_support_state") or upstream.get("packet_support_state") or "")

    return {
        "gate_version": STATUS_INTEGRITY_GATE_VERSION,
        "original_status": status,
        "forced_status": "abstained",
        "admitted_evidence_count": admitted_count,
        "packet_support_state": packet_support_state,
        "knowledge_unit_id": packet.get("knowledge_unit_id"),
    }


def unjustified_abstention_violation(packet: Mapping[str, Any],
                                    draft: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """The inverse of status_integrity_violation(): an abstention the packet never permitted.

    status_integrity_violation() only inspects POSITIVE_STATUSES, so an "abstained" status has
    historically been accepted without ever being compared against its own packet. That asymmetry is
    measurable: in the audited Qwen 3.8 Data Mining run, gated `grounded` reached 93.5% precision
    while ungated `abstained` sat at 43.8%, and five of the nine unjustified abstentions were on
    packets that were `draftable`, carried 3-14 admitted evidence items, and set neither
    abstention_expected nor weak_fallback_abstention_allowed. Two of those five were drafted
    successfully by a different model from the byte-identical packet.

    A packet in that state grants no permission to abstain, so an abstention against it is a claim
    the packet contradicts - exactly the kind of unbacked status the forward gate already rejects in
    the other direction.

    Reports only. The caller must NOT promote the status to grounded on the strength of this: the
    model declined to draft, and manufacturing confidence on its behalf is the failure mode this
    whole gate exists to prevent. Surface it for review instead.
    """
    if not isinstance(draft, Mapping):
        return None
    if str(packet.get("knowledge_unit_type") or "") != "kc":
        return None

    contextual = draft.get("contextual_kc_draft")
    if not isinstance(contextual, Mapping):
        return None
    if str(contextual.get("status") or "").lower() != ABSTAINED_STATUS:
        return None

    # An abstention the packet explicitly allowed is legitimate, whichever way it was granted.
    if bool(packet.get("abstention_expected")):
        return None
    if bool(packet.get("weak_fallback_abstention_allowed")):
        return None

    upstream = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), Mapping) else {}
    support_state = str(packet.get("packet_support_state") or upstream.get("packet_support_state") or "")
    if support_state != "draftable":
        return None

    admitted_count = kc_admitted_evidence_count(packet)
    if admitted_count <= 0:
        return None

    return {
        "gate_version": ABSTENTION_INTEGRITY_GATE_VERSION,
        "code": UNJUSTIFIED_ABSTENTION_CODE,
        "original_status": ABSTAINED_STATUS,
        "forced_status": None,
        "admitted_evidence_count": admitted_count,
        "packet_support_state": support_state,
        "knowledge_unit_id": packet.get("knowledge_unit_id"),
    }


def apply_status_integrity_gate(
    packet: Mapping[str, Any], draft: Optional[MutableMapping[str, Any]]
) -> Tuple[Optional[MutableMapping[str, Any]], Optional[dict]]:
    """Returns (possibly-corrected draft, override metadata or None). Never mutates the input -
    returns a shallow copy of `draft` and a fresh copy of `contextual_kc_draft` when an override
    fires, so the original object passed in is always left untouched (safe for callers that reuse
    it, e.g. for the raw_response/diagnostic fields already present on each row).
    """
    violation = status_integrity_violation(packet, draft)
    if violation is None:
        # Same gate, other direction. Reported, never applied: forced_status is None, and the draft
        # is returned untouched so no confidence is manufactured on the model's behalf.
        return draft, unjustified_abstention_violation(packet, draft)

    assert isinstance(draft, Mapping)
    corrected = dict(draft)
    contextual = dict(corrected["contextual_kc_draft"])
    contextual["status"] = "abstained"
    corrected["contextual_kc_draft"] = contextual
    return corrected, violation
