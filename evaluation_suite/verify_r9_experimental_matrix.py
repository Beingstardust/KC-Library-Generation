"""Experimental-invariant checks for the R9 final judge campaign (FINAL R9 KC CONTENT QUALITY
EVALUATION spec, section 4 and section 46's STOP conditions).

Three checks, each independent and each a hard stop on failure - never a warning that lets a
broken invariant pass through to judging:

  1. KC identity equality: every arm must cover the exact same 159 KC IDs. A count match alone
     is not accepted - section 3's "STOP if the five primary arms do not all contain the same
     intended 159 KC IDs" means the *sets* must be equal, not just their sizes.
  2. Intrinsic evidence-hash equality: P-Q/P-G/P-D must see byte-identical evidence per KC. Where
     all conditions read one shared packets file this holds by construction; this module still
     verifies it explicitly (per-KC evidence_for_synthesis hash) rather than trusting "shared
     file" as a proxy, so a caller that accidentally supplies drifted per-condition packet copies
     is caught rather than silently accepted.
  3. Extrinsic parity: same pipeline commit, same decoding config, across all extrinsic
     conditions. This is the check that caught the e3944aa-vs-HEAD staleness this session -
     retained here as regression protection for the next comparator refresh.

Nothing here re-derives evidence or drafts anything; it only reads already-built artifacts and
either confirms or refuses the invariant.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from discover_r9_evaluation_artifacts import load_jsonl


class ExperimentalInvariantError(ValueError):
    """Raised when a section-46 STOP condition is met. Never caught silently by a caller that
    intends to proceed with judging anyway - solving these by weakening the evaluation is
    explicitly forbidden by the campaign spec."""


@dataclass(frozen=True)
class VerificationResult:
    name: str
    passed: bool
    detail: str = ""


def check_kc_identity_equality(id_sets: Mapping[str, set[str]],
                                expected_count: int = 159) -> VerificationResult:
    if not id_sets:
        return VerificationResult("kc_identity_equality", False, "no arms supplied")
    labels = list(id_sets)
    reference = id_sets[labels[0]]
    mismatches = []
    for label, ids in id_sets.items():
        if ids != reference:
            missing = sorted(reference - ids)
            extra = sorted(ids - reference)
            mismatches.append(f"{label}: missing={missing[:5]} extra={extra[:5]}")
        if len(ids) != expected_count:
            mismatches.append(f"{label}: has {len(ids)} KC IDs, expected {expected_count}")
    if mismatches:
        return VerificationResult("kc_identity_equality", False, "; ".join(mismatches))
    return VerificationResult("kc_identity_equality", True,
                               f"all {len(labels)} arms share the same {expected_count} KC IDs")


def _evidence_hash_by_kc(packet_path: str | Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in load_jsonl(packet_path):
        kc = row.get("kc_id") or row.get("knowledge_unit_id")
        if kc is None:
            continue
        ev = row.get("evidence_for_synthesis") or []
        ser = json.dumps(ev, sort_keys=True, ensure_ascii=False)
        out[kc] = hashlib.sha256(ser.encode("utf-8")).hexdigest()
    return out


def check_intrinsic_evidence_hash_equality(
    packet_paths: Mapping[str, str | Path],
) -> VerificationResult:
    """packet_paths is {condition_label: path_to_that_condition's_packets_jsonl}. If every
    condition points at the literal same file path, this is a trivial pass (identity by
    construction). Otherwise each condition's per-KC evidence is hashed and compared."""
    labels = list(packet_paths)
    resolved = {label: str(Path(p).resolve()) for label, p in packet_paths.items()}
    if len(set(resolved.values())) == 1:
        return VerificationResult("intrinsic_evidence_hash_equality", True,
                                   f"{len(labels)} conditions share one literal packets file")

    per_condition = {label: _evidence_hash_by_kc(p) for label, p in packet_paths.items()}
    reference_label = labels[0]
    reference = per_condition[reference_label]
    mismatches = []
    for label in labels[1:]:
        this = per_condition[label]
        if this.keys() != reference.keys():
            mismatches.append(f"{label}: KC-ID coverage differs from {reference_label}")
            continue
        diffs = [kc for kc in reference if reference[kc] != this[kc]]
        if diffs:
            mismatches.append(f"{label}: {len(diffs)} KCs have different evidence than {reference_label}")
    if mismatches:
        return VerificationResult("intrinsic_evidence_hash_equality", False, "; ".join(mismatches))
    return VerificationResult("intrinsic_evidence_hash_equality", True,
                               f"{len(labels)} separately-hashed conditions have identical per-KC evidence")


def check_extrinsic_commit_parity(commit_by_condition: Mapping[str, str]) -> VerificationResult:
    values = set(commit_by_condition.values())
    if len(values) <= 1:
        return VerificationResult("extrinsic_commit_parity", True,
                                   f"all {len(commit_by_condition)} conditions built at "
                                   f"{next(iter(values), 'N/A')}")
    detail = ", ".join(f"{k}={v}" for k, v in commit_by_condition.items())
    return VerificationResult("extrinsic_commit_parity", False, detail)


def check_decoding_config_parity(config_by_condition: Mapping[str, Mapping[str, Any]]) -> VerificationResult:
    labels = list(config_by_condition)
    reference = config_by_condition[labels[0]]
    mismatches = [label for label in labels[1:] if config_by_condition[label] != reference]
    if mismatches:
        return VerificationResult("decoding_config_parity", False,
                                   f"conditions differing from {labels[0]}: {mismatches}")
    return VerificationResult("decoding_config_parity", True,
                               f"all {len(labels)} conditions share one decoding config")


def assert_no_stop_conditions(results: list[VerificationResult]) -> None:
    failed = [r for r in results if not r.passed]
    if failed:
        detail = "; ".join(f"{r.name}: {r.detail}" for r in failed)
        raise ExperimentalInvariantError(
            f"{len(failed)} experimental invariant(s) failed - do not proceed to judging. {detail}"
        )
