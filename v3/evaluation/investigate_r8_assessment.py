"""Corpus-wide diagnostics for the post-r7 improvement assessment.

This script changes no artifacts. It deliberately imports the live packet builder so target-anchor
measurements exercise the production mechanism rather than a local reimplementation.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import pathlib
import re
from typing import Any, Iterable, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKET_BUILDER = ROOT / "v3" / "pipeline" / "02_build_kc_packets.py"


def load_packet_builder():
    spec = importlib.util.spec_from_file_location("r8_packet_builder", PACKET_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load %s" % PACKET_BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_jsonl(path: str | pathlib.Path) -> list[dict[str, Any]]:
    with pathlib.Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def nested_body(row: Mapping[str, Any]) -> str:
    candidates = [row]
    for key in ("draft", "output", "parsed", "result", "bundle"):
        value = row.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
            contextual = value.get("contextual_kc_draft")
            if isinstance(contextual, Mapping):
                candidates.append(contextual)
    for item in candidates:
        for key in ("body", "text", "draft_text", "definition"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def nested_status(row: Mapping[str, Any]) -> str:
    candidates = [row]
    for key in ("draft", "output", "parsed", "result", "bundle"):
        value = row.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
            contextual = value.get("contextual_kc_draft")
            if isinstance(contextual, Mapping):
                candidates.append(contextual)
    for item in candidates:
        value = item.get("status")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def passage_view(evidence: Mapping[str, Any]) -> dict[str, Any]:
    support = evidence.get("support_profile_summary") or {}
    return {
        "text": evidence.get("text") or "",
        "patch_heading": evidence.get("patch_heading") or "",
        "shapes": evidence.get("shape_tags") or evidence.get("roles") or [],
        "admission_basis": support.get("admission_basis") or "cross_encoder_relevance",
    }


def anchor_branch(packet_builder, passage: Mapping[str, Any], labels: Iterable[str]) -> str:
    """Classify the branch used by the live anchor predicate and assert exact agreement."""
    labels = [str(label) for label in labels if str(label).strip()]
    production = packet_builder.passage_has_strong_target_anchor(passage, labels)
    basis = passage.get("admission_basis")
    branch = "none"
    if basis in packet_builder.STRONG_TARGET_ADMISSION_BASES:
        branch = "licensed_admission_basis"
    else:
        text = str(passage.get("text") or "").strip()
        heading = str(passage.get("patch_heading") or "")
        normalized = packet_builder.normalized_label_phrase("%s %s" % (heading, text))
        terms = packet_builder.context_content_terms("%s %s" % (heading, text))
        for label in labels:
            core = re.sub(r"\([^)]*\)", "", label).strip()
            phrase = packet_builder.normalized_label_phrase(core)
            if phrase and re.search(r"(?:^|\s)" + re.escape(phrase) + r"(?:\s|$)", normalized):
                branch = "exact_phrase"
                break
            label_terms = packet_builder.context_content_terms(core)
            if label_terms and label_terms.issubset(terms):
                branch = "subset_only"
                break
    if production != (branch != "none"):
        raise AssertionError("diagnostic diverged from live anchor predicate")
    return branch


_DEFINITIONAL_SUBJECT_PATTERNS = (
    re.compile(
        r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
        r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,80}?)\s+"
        r"(?:is|are)\s+(?:defined\s+as|called|known\s+as|referred\s+to\s+as|"
        r"classified\s+as|used\s+to|a\b|an\b|the\b)", re.I),
    re.compile(
        r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
        r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,80}?)\s+"
        r"(?:is|are)\s+[^.!?]{1,80}\b(?:if|when)\b", re.I),
    re.compile(
        r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
        r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,80}?)\s+"
        r"(?:refers\s+to|means|denotes|measures|consists\s+of)\b", re.I),
)


def incompatible_definitional_subjects(packet_builder, text: str,
                                       labels: Iterable[str]) -> list[str]:
    target_terms = set()
    for label in labels:
        target_terms |= packet_builder.context_content_terms(
            re.sub(r"\([^)]*\)", "", str(label or "")))
    subjects = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        for pattern in _DEFINITIONAL_SUBJECT_PATTERNS:
            match = pattern.match(sentence)
            if not match:
                continue
            subject = match.group("subject").strip()
            subject_terms = packet_builder.context_content_terms(subject)
            if subject_terms and not (subject_terms & target_terms):
                subjects.append(subject)
            break
    return subjects


def identity_anchor_reason(packet_builder, passage: Mapping[str, Any],
                           labels: Iterable[str]) -> str:
    """A conservative positive identity signal, independent of retrieval relevance."""
    labels = [str(label) for label in labels if str(label).strip()]
    text = str(passage.get("text") or "").strip()
    heading = str(passage.get("patch_heading") or "").strip()
    normalized = packet_builder.normalized_label_phrase("%s %s" % (heading, text))
    for label in labels:
        core = re.sub(r"\([^)]*\)", "", label).strip()
        phrase = packet_builder.normalized_label_phrase(core)
        if phrase and re.search(r"(?:^|\s)" + re.escape(phrase) + r"(?:\s|$)", normalized):
            return "exact_source_surface"
    if passage.get("admission_basis") == "name_anchored_defining_equation":
        return "target_named_equation"
    subject = packet_builder._compatible_definitional_subject(text, labels)
    reason = "compatible_definitional_subject" if subject else ""
    if packet_builder.passage_has_positive_target_identity(passage, labels) != bool(reason):
        raise AssertionError("diagnostic diverged from live positive-identity predicate")
    return reason


def source_region_key(evidence: Mapping[str, Any]) -> tuple[str, Any]:
    return str(evidence.get("doc_id") or ""), evidence.get("page_index")


def source_order_key(evidence: Mapping[str, Any]) -> tuple[str, int, str]:
    page = evidence.get("page_index")
    return (str(evidence.get("doc_id") or ""), int(page) if page is not None else -1,
            str(evidence.get("sentence_id") or ""))


def ordering_diagnostics(packet: Mapping[str, Any]) -> dict[str, Any]:
    evidence = list(packet.get("evidence_for_synthesis") or [])
    if len(evidence) < 2:
        return {"authority_transitions": 0, "source_inversions_within_region": 0}
    transitions = sum(
        int(evidence[index - 1].get("authority_tier") != evidence[index].get("authority_tier"))
        for index in range(1, len(evidence))
    )
    inversions = 0
    for left_index, left in enumerate(evidence):
        for right in evidence[left_index + 1:]:
            if source_region_key(left) == source_region_key(right) and source_order_key(left) > source_order_key(right):
                inversions += 1
    return {"authority_transitions": transitions, "source_inversions_within_region": inversions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--packets", required=True)
    parser.add_argument("--drafts", required=True)
    parser.add_argument("--hygiene", required=True)
    parser.add_argument("--out-json")
    args = parser.parse_args()

    packet_builder = load_packet_builder()
    profiles = load_jsonl(args.profiles)
    packets = load_jsonl(args.packets)
    drafts = load_jsonl(args.drafts)
    hygiene = load_jsonl(args.hygiene)

    profiles_by_id = {row.get("kc_id") or row.get("knowledge_unit_id"): row for row in profiles}
    drafts_by_id = {row.get("kc_id") or row.get("knowledge_unit_id"): row for row in drafts}
    anchor_counts: collections.Counter[str] = collections.Counter()
    packet_anchor_profiles: collections.Counter[tuple[str, ...]] = collections.Counter()
    subset_only_packets = []
    no_anchor_packets = []
    identity_anchor_counts: collections.Counter[str] = collections.Counter()
    would_demote_without_identity = []
    would_demote_on_foreign_subject = []
    would_demote_on_modifier_foreign_head = []
    candidate_support_state_changes = []
    ordering = collections.Counter()
    status_counts: collections.Counter[str] = collections.Counter()

    for packet in packets:
        unit_id = packet.get("kc_id") or packet.get("knowledge_unit_id")
        profile = profiles_by_id.get(unit_id) or {}
        labels = [profile.get("canonical_name") or packet.get("canonical_name") or ""]
        labels.extend(
            item.get("term") if isinstance(item, Mapping) else item
            for item in profile.get("deterministic_label_variants") or []
        )
        branches = []
        identity_reasons = []
        foreign_subjects = []
        modifier_decoys = []
        passage_views = []
        for item in packet.get("evidence_for_synthesis") or []:
            passage = passage_view(item)
            passage_views.append(passage)
            branch = anchor_branch(packet_builder, passage, labels)
            anchor_counts[branch] += 1
            if branch != "none":
                branches.append(branch)
            identity_reason = identity_anchor_reason(packet_builder, passage, labels)
            identity_anchor_counts[identity_reason or "none"] += 1
            if identity_reason:
                identity_reasons.append(identity_reason)
            foreign_subjects.extend(
                incompatible_definitional_subjects(packet_builder, passage.get("text") or "", labels))
            modifier_decoys.extend(packet_builder.modifier_foreign_head_decoys(
                passage.get("text") or "", labels[0]))
        profile_key = tuple(sorted(set(branches))) or ("none",)
        packet_anchor_profiles[profile_key] += 1
        if branches and set(branches) == {"subset_only"}:
            subset_only_packets.append({
                "kc_id": unit_id,
                "canonical_name": packet.get("canonical_name"),
                "support_state": packet.get("packet_support_state"),
                "evidence_count": len(packet.get("evidence_for_synthesis") or []),
            })
        if not branches:
            no_anchor_packets.append({
                "kc_id": unit_id,
                "canonical_name": packet.get("canonical_name"),
                "support_state": packet.get("packet_support_state"),
            })
        if packet.get("packet_support_state") == "draftable" and not identity_reasons:
            would_demote_without_identity.append({
                "kc_id": unit_id,
                "canonical_name": packet.get("canonical_name"),
                "evidence_count": len(packet.get("evidence_for_synthesis") or []),
                "current_anchor_branches": sorted(set(branches)),
            })
            if foreign_subjects:
                would_demote_on_foreign_subject.append({
                    "kc_id": unit_id,
                    "canonical_name": packet.get("canonical_name"),
                    "foreign_subjects": sorted(set(foreign_subjects)),
                })
            if modifier_decoys:
                would_demote_on_modifier_foreign_head.append({
                    "kc_id": unit_id,
                    "canonical_name": packet.get("canonical_name"),
                    "decoys": modifier_decoys,
                })
        selected_query = str((packet.get("query_formulation") or {}).get("selected") or "")
        live_labels = labels + ([selected_query] if selected_query else [])
        candidate_state, candidate_reason = packet_builder.assess_support_state(
            passage_views, live_labels)
        if (candidate_state != packet.get("packet_support_state")
                or candidate_reason != packet.get("support_state_reason")):
            candidate_support_state_changes.append({
                "kc_id": unit_id,
                "canonical_name": packet.get("canonical_name"),
                "state_before": packet.get("packet_support_state"),
                "state_after": candidate_state,
                "reason_before": packet.get("support_state_reason"),
                "reason_after": candidate_reason,
            })
        order = ordering_diagnostics(packet)
        ordering["authority_transitions"] += order["authority_transitions"]
        ordering["source_inversions_within_region"] += order["source_inversions_within_region"]

        draft = drafts_by_id.get(unit_id) or {}
        status_counts[nested_status(draft)] += 1

    hygiene_counts = collections.Counter(str(row.get("check") or "") for row in hygiene)
    hard_status_conflicts = []
    for row in hygiene:
        if row.get("check") != "DEFINITIONAL_SUBJECT_IS_NOT_THE_UNIT":
            continue
        unit_id = row.get("kc_id") or row.get("knowledge_unit_id")
        draft = drafts_by_id.get(unit_id) or {}
        hard_status_conflicts.append({
            "kc_id": unit_id,
            "canonical_name": row.get("canonical_name"),
            "defined_subject": row.get("defined_subject"),
            "draft_status": nested_status(draft),
            "sentence": row.get("sentence"),
        })

    result = {
        "counts": {
            "profiles": len(profiles),
            "packets": len(packets),
            "drafts": len(drafts),
            "hygiene_findings": len(hygiene),
        },
        "draft_status": dict(sorted(status_counts.items())),
        "profile_aliases": {
            "profiles_with_registry_aliases": sum(bool(row.get("aliases")) for row in profiles),
            "profiles_with_multiple_deterministic_variants": sum(
                len(row.get("deterministic_label_variants") or []) > 1 for row in profiles),
            "profiles_with_retrieval_disambiguation": sum(
                bool(row.get("retrieval_disambiguation_terms")) for row in profiles),
        },
        "anchor_evidence_branches": dict(sorted(anchor_counts.items())),
        "identity_anchor_evidence_branches": dict(sorted(identity_anchor_counts.items())),
        "packet_anchor_profiles": {
            "+".join(key): value for key, value in sorted(packet_anchor_profiles.items())
        },
        "subset_only_packets": subset_only_packets,
        "no_anchor_packets": no_anchor_packets,
        "would_demote_without_positive_identity": would_demote_without_identity,
        "would_demote_on_positive_foreign_subject_without_identity": would_demote_on_foreign_subject,
        "would_demote_on_modifier_foreign_head_without_identity": would_demote_on_modifier_foreign_head,
        "live_candidate_support_state_changes": candidate_support_state_changes,
        "ordering": dict(ordering),
        "hygiene_counts": dict(sorted(hygiene_counts.items())),
        "definitional_subject_status_conflicts": hard_status_conflicts,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out_json:
        pathlib.Path(args.out_json).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
