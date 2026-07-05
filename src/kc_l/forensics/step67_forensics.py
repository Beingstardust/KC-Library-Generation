from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


STATUS_RANK = {
    "seed_floor_fallback": 0,
    "normalized_grounded": 1,
    "direct_grounded": 2,
}

RAW_DRAFT_RESPONSE_KEYS = (
    "preservation_draft_response",
    "draft_response",
    "rescue_draft_response",
    "definition_redraft_response",
)

RAW_VERIFY_RESPONSE_KEYS = (
    "preservation_verify_response",
    "verify_response",
    "rescue_verify_response",
    "definition_redraft_verify_response",
)

REJECTION_SUBBUCKET_FALSE_REJECT = (
    "raw_draft_clearly_good_and_verifier_likely_false_rejected_it"
)
REJECTION_SUBBUCKET_CONTROL_OVERRIDE = (
    "raw_draft_clearly_good_but_later_control_logic_or_preservation_rescue_interaction_caused_the_loss"
)
REJECTION_SUBBUCKET_WEAK_DRAFT = (
    "raw_draft_present_but_not_actually_strong_enough_to_justify_grounded_acceptance"
)
REJECTION_SUBBUCKET_BINDING_WEAK = (
    "support_provenance_binding_or_supporting_overlay_id_linkage_is_weak_or_mismatched"
)
REJECTION_SUBBUCKET_MIXED = "mixed_ambiguous"
REJECTION_SUBBUCKET_ORDER = (
    REJECTION_SUBBUCKET_FALSE_REJECT,
    REJECTION_SUBBUCKET_CONTROL_OVERRIDE,
    REJECTION_SUBBUCKET_WEAK_DRAFT,
    REJECTION_SUBBUCKET_BINDING_WEAK,
    REJECTION_SUBBUCKET_MIXED,
)

SUPPORT_BINDING_SUBTYPE_BETTER_SAME_KC_UNBOUND = (
    "better_same_kc_definition_available_but_unbound"
)
SUPPORT_BINDING_SUBTYPE_BINDING_OUTSIDE_POOL = (
    "binding_outside_definition_pool_or_selected_bundle"
)
SUPPORT_BINDING_SUBTYPE_COLLAPSED_MULTI_ROW = (
    "collapsed_multi_row_weak_composite_binding"
)
SUPPORT_BINDING_SUBTYPE_WEAK_TOPIC = "weak_topic_or_crossconcept_anchor"
SUPPORT_BINDING_SUBTYPE_PROCEDURE_EXAMPLE = "procedure_or_example_anchor"
SUPPORT_BINDING_SUBTYPE_FORMULA = "formula_or_parameter_anchor"
SUPPORT_BINDING_SUBTYPE_BROAD = "residual_scope_broad_anchor"
SUPPORT_BINDING_SUBTYPE_ORDER = (
    SUPPORT_BINDING_SUBTYPE_BETTER_SAME_KC_UNBOUND,
    SUPPORT_BINDING_SUBTYPE_COLLAPSED_MULTI_ROW,
    SUPPORT_BINDING_SUBTYPE_WEAK_TOPIC,
    SUPPORT_BINDING_SUBTYPE_PROCEDURE_EXAMPLE,
    SUPPORT_BINDING_SUBTYPE_FORMULA,
    SUPPORT_BINDING_SUBTYPE_BINDING_OUTSIDE_POOL,
    SUPPORT_BINDING_SUBTYPE_BROAD,
)

REPAIR_STATE_NO_REPAIR_NEEDED = "no_repair_needed"
REPAIR_STATE_APPLIED = "repair_attempted_and_applied"
REPAIR_STATE_REJECTED = "repair_attempted_but_rejected"
REPAIR_STATE_NO_BINDING = "no_binding_possible"

REPAIR_ACTION_REASONS = {
    "blocked_out_of_pool_definition_binding",
    "promoted_stronger_same_kc_definition_anchor",
    "promoted_bounded_multi_row_definition_binding",
    "replaced_weak_definition_anchor",
}

TOUCH_CLASS_TOUCHED_HARMED = "touched_and_harmed"
TOUCH_CLASS_TOUCHED_IMPROVED = "touched_and_improved"
TOUCH_CLASS_TOUCHED_UNCHANGED = "touched_and_unchanged"
TOUCH_CLASS_UNTOUCHED_REGRESSED = "untouched_but_regressed"
TOUCH_CLASS_UNTOUCHED_STABLE = "untouched_and_stable"
TOUCH_CLASS_UNTOUCHED_IMPROVED = "untouched_but_improved"
TOUCH_CLASS_ORDER = (
    TOUCH_CLASS_TOUCHED_HARMED,
    TOUCH_CLASS_TOUCHED_IMPROVED,
    TOUCH_CLASS_TOUCHED_UNCHANGED,
    TOUCH_CLASS_UNTOUCHED_REGRESSED,
    TOUCH_CLASS_UNTOUCHED_STABLE,
    TOUCH_CLASS_UNTOUCHED_IMPROVED,
)

DEF_NOT_GROUNDED_SUBBUCKET_VERIFY_REJECTED_WITH_FALLBACK = (
    "verify_rejected_no_binding_despite_prior_single_span_support_match"
)
DEF_NOT_GROUNDED_SUBBUCKET_VERIFY_REJECTED_WITHOUT_FALLBACK = (
    "verify_rejected_no_binding_without_prior_single_span_support_match"
)
DEF_NOT_GROUNDED_SUBBUCKET_PRES_ABSTAIN_RESCUE_GROUNDED = (
    "preservation_draft_abstained_rescue_grounded_no_binding"
)
DEF_NOT_GROUNDED_SUBBUCKET_PRES_ABSTAIN_RESCUE_ABSTAIN = (
    "preservation_draft_abstained_rescue_abstained_no_binding"
)
DEF_NOT_GROUNDED_SUBBUCKET_ORDER = (
    DEF_NOT_GROUNDED_SUBBUCKET_VERIFY_REJECTED_WITH_FALLBACK,
    DEF_NOT_GROUNDED_SUBBUCKET_VERIFY_REJECTED_WITHOUT_FALLBACK,
    DEF_NOT_GROUNDED_SUBBUCKET_PRES_ABSTAIN_RESCUE_GROUNDED,
    DEF_NOT_GROUNDED_SUBBUCKET_PRES_ABSTAIN_RESCUE_ABSTAIN,
)

STRICT_VERIFY_REASON_RE = re.compile(
    r"not explicitly|not directly supported|broader claim|broader than|only mentions",
    re.IGNORECASE,
)
SUBSTANTIVE_VERIFY_REASON_RE = re.compile(
    r"formula|does not match|incorrect|contradict|unrelated|different concept|"
    r"binary classifier|linear|numerical attributes|specific labels|notation|"
    r"none of the evidence|physics definition|activation function|"
    r"not to form clusters|not define|not supported by cited evidence",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Step67RunArtifacts:
    run_id: str
    set_path: Path
    bundle_path: Path
    summary_path: Path
    input_manifest_path: Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def relative_to_repo(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_jsonl_by_kc(path: Path, kc_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    rows_by_kc: dict[str, list[dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kc_id = row.get("kc_id")
            if kc_id in kc_ids:
                rows_by_kc.setdefault(kc_id, []).append(row)
    return rows_by_kc


def read_jsonl_index(path: Path, key_field: str) -> dict[str, dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = row.get(key_field)
            if key:
                rows_by_key[key] = row
    return rows_by_key


def _normalize_ws(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _candidate_alignment_breakdown(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("alignment_breakdown") or {}


def _candidate_flags(candidate: dict[str, Any]) -> dict[str, Any]:
    return (
        _candidate_alignment_breakdown(candidate).get("flags")
        or candidate.get("sentence_flags")
        or {}
    )


def _candidate_contamination_risk(candidate: dict[str, Any]) -> str:
    return (
        candidate.get("contamination_risk")
        or _candidate_alignment_breakdown(candidate).get("contamination_risk")
        or ""
    )


def _is_definition_like_candidate(candidate: dict[str, Any]) -> bool:
    if "is_definition_like" in candidate:
        return bool(candidate.get("is_definition_like"))
    return bool(_candidate_flags(candidate).get("is_definition_like"))


def resolve_step67_run_artifacts(root: Path, run_id: str) -> Step67RunArtifacts:
    return Step67RunArtifacts(
        run_id=run_id,
        set_path=root / "data" / "processed" / "kc_drafts" / "_sets" / f"{run_id}_step6_7_kc_drafts_set.json",
        bundle_path=root / "data" / "processed" / "kc_drafts" / run_id / "kc_draft_bundles.jsonl",
        summary_path=root / "data" / "runs" / f"{run_id}_step6_7" / "summary.json",
        input_manifest_path=root / "data" / "runs" / f"{run_id}_step6_7" / "input_manifest.json",
    )


def load_run_snapshot(artifacts: Step67RunArtifacts, root: Path) -> dict[str, Any]:
    bundles = read_jsonl(artifacts.bundle_path)
    summary = read_json(artifacts.summary_path)
    set_payload = read_json(artifacts.set_path)
    input_manifest = read_json(artifacts.input_manifest_path) if artifacts.input_manifest_path.exists() else []
    status_counts = Counter(row["authoritative_definition_status"] for row in bundles)
    llm_calls = (
        (summary.get("drafting_runtime") or {}).get("llm_calls")
        or ((summary.get("stats") or {}).get("drafting_runtime") or {}).get("llm_calls")
        or ((summary.get("stats") or {}).get("llm_runtime") or {}).get("llm_calls")
    )
    return {
        "run_id": artifacts.run_id,
        "artifacts": {
            "set_path": relative_to_repo(artifacts.set_path, root),
            "bundle_path": relative_to_repo(artifacts.bundle_path, root),
            "summary_path": relative_to_repo(artifacts.summary_path, root),
            "input_manifest_path": relative_to_repo(artifacts.input_manifest_path, root),
        },
        "set_payload": set_payload,
        "summary": summary,
        "input_manifest": input_manifest,
        "rows_by_kc": {row["kc_id"]: row for row in bundles},
        "status_counts": dict(status_counts),
        "total_kcs": len(bundles),
        "llm_calls": llm_calls,
        "grounded_total": status_counts.get("direct_grounded", 0) + status_counts.get("normalized_grounded", 0),
    }


def normalize_definition_support_binding_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    diagnostics = (
        ((row.get("selection_diagnostics") or {}).get("definition_support_binding") or {})
        if isinstance(row, dict)
        else {}
    )
    repair_applied = bool(diagnostics.get("repair_applied"))
    repair_state = str(diagnostics.get("repair_state") or "").strip()
    repair_reason = str(diagnostics.get("repair_reason") or "").strip()
    repair_attempt_reason = str(diagnostics.get("repair_attempt_reason") or "").strip()
    basis = "native_binding_diagnostics" if repair_state else "legacy_binding_diagnostics_inference"

    if not repair_state:
        if repair_applied:
            repair_state = REPAIR_STATE_APPLIED
            if not repair_attempt_reason and repair_reason in REPAIR_ACTION_REASONS:
                repair_attempt_reason = repair_reason
        elif repair_reason in {
            "definition_not_grounded",
            "no_grounded_definition_candidate",
            "no_active_definition_anchor_pool",
            "no_valid_definition_anchor_after_repair",
        }:
            repair_state = REPAIR_STATE_NO_BINDING
        elif repair_reason in REPAIR_ACTION_REASONS:
            repair_state = REPAIR_STATE_REJECTED
            repair_attempt_reason = repair_reason
            repair_reason = "legacy_action_reason_without_applied_flag"
        else:
            repair_state = REPAIR_STATE_NO_REPAIR_NEEDED

    if repair_applied and not repair_attempt_reason and repair_reason in REPAIR_ACTION_REASONS:
        repair_attempt_reason = repair_reason

    return {
        "repair_state": repair_state,
        "repair_applied": repair_applied,
        "repair_reason": repair_reason,
        "repair_attempt_reason": repair_attempt_reason,
        "basis": basis,
        "current_support_ids": list(diagnostics.get("current_support_ids") or []),
        "chosen_support_ids": list(diagnostics.get("chosen_support_ids") or []),
        "current_binding_mode": str(diagnostics.get("current_binding_mode") or ""),
        "final_binding_mode": str(diagnostics.get("final_binding_mode") or ""),
        "stronger_same_kc_candidate_existed": bool(diagnostics.get("stronger_same_kc_candidate_existed")),
        "raw_repair_reason": str(diagnostics.get("repair_reason") or ""),
    }


def _touch_classification(*, delta: int, repair_applied: bool) -> str:
    if repair_applied and delta < 0:
        return TOUCH_CLASS_TOUCHED_HARMED
    if repair_applied and delta > 0:
        return TOUCH_CLASS_TOUCHED_IMPROVED
    if repair_applied and delta == 0:
        return TOUCH_CLASS_TOUCHED_UNCHANGED
    if delta < 0:
        return TOUCH_CLASS_UNTOUCHED_REGRESSED
    if delta > 0:
        return TOUCH_CLASS_UNTOUCHED_IMPROVED
    return TOUCH_CLASS_UNTOUCHED_STABLE


def compare_step67_runs(
    baseline_snapshot: dict[str, Any],
    candidate_snapshot: dict[str, Any],
) -> dict[str, Any]:
    transition_counts: Counter[str] = Counter()
    touch_class_counts: Counter[str] = Counter()
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    per_kc: list[dict[str, Any]] = []

    baseline_rows = baseline_snapshot["rows_by_kc"]
    candidate_rows = candidate_snapshot["rows_by_kc"]

    for kc_id in sorted(baseline_rows):
        baseline_row = baseline_rows[kc_id]
        candidate_row = candidate_rows[kc_id]
        baseline_status = baseline_row["authoritative_definition_status"]
        candidate_status = candidate_row["authoritative_definition_status"]
        baseline_rank = STATUS_RANK[baseline_status]
        candidate_rank = STATUS_RANK[candidate_status]
        delta = candidate_rank - baseline_rank
        binding_diag = normalize_definition_support_binding_diagnostics(candidate_row)
        touch_class = _touch_classification(delta=delta, repair_applied=bool(binding_diag.get("repair_applied")))
        transition = f"{baseline_status}->{candidate_status}"
        transition_counts[transition] += 1
        touch_class_counts[touch_class] += 1

        record = {
            "kc_id": kc_id,
            "baseline_status": baseline_status,
            "candidate_status": candidate_status,
            "baseline_trust_state": (baseline_row.get("trust_state") or {}).get("label"),
            "candidate_trust_state": (candidate_row.get("trust_state") or {}).get("label"),
            "delta": delta,
            "binding_touch_classification": touch_class,
            "binding_repair_diagnostics": binding_diag,
        }
        per_kc.append(record)
        if delta < 0:
            regressions.append(record)
        elif delta > 0:
            improvements.append(record)
        else:
            unchanged.append(record)

    gate = evaluate_no_regression_gate(baseline_snapshot, candidate_snapshot)
    return {
        "baseline_run_id": baseline_snapshot["run_id"],
        "candidate_run_id": candidate_snapshot["run_id"],
        "baseline_status_counts": baseline_snapshot["status_counts"],
        "candidate_status_counts": candidate_snapshot["status_counts"],
        "baseline_llm_calls": baseline_snapshot["llm_calls"],
        "candidate_llm_calls": candidate_snapshot["llm_calls"],
        "transition_counts": dict(sorted(transition_counts.items())),
        "binding_touch_summary": {key: int(touch_class_counts.get(key, 0)) for key in TOUCH_CLASS_ORDER},
        "regression_count": len(regressions),
        "improvement_count": len(improvements),
        "unchanged_count": len(unchanged),
        "regressions": regressions,
        "improvements": improvements,
        "per_kc": per_kc,
        "no_regression_gate": gate,
    }


def evaluate_no_regression_gate(
    baseline_snapshot: dict[str, Any],
    candidate_snapshot: dict[str, Any],
) -> dict[str, Any]:
    baseline_rows = baseline_snapshot["rows_by_kc"]
    candidate_rows = candidate_snapshot["rows_by_kc"]

    previously_direct_ids = {
        kc_id
        for kc_id, row in baseline_rows.items()
        if row["authoritative_definition_status"] == "direct_grounded"
    }
    direct_to_fallback = sorted(
        kc_id
        for kc_id in previously_direct_ids
        if candidate_rows[kc_id]["authoritative_definition_status"] == "seed_floor_fallback"
    )

    baseline_fallback = baseline_snapshot["status_counts"].get("seed_floor_fallback", 0)
    candidate_fallback = candidate_snapshot["status_counts"].get("seed_floor_fallback", 0)
    baseline_llm_calls = baseline_snapshot.get("llm_calls")
    candidate_llm_calls = candidate_snapshot.get("llm_calls")
    grounded_gain = candidate_snapshot["grounded_total"] - baseline_snapshot["grounded_total"]

    reasons: list[str] = []
    if direct_to_fallback:
        reasons.append(
            "previously direct-grounded KCs fell to seed-floor fallback: " + ", ".join(direct_to_fallback)
        )
    if candidate_fallback > baseline_fallback:
        reasons.append(
            f"seed-floor fallback increased from {baseline_fallback} to {candidate_fallback}"
        )

    llm_call_delta = None
    material_increase_threshold = None
    if isinstance(baseline_llm_calls, int) and isinstance(candidate_llm_calls, int):
        llm_call_delta = candidate_llm_calls - baseline_llm_calls
        material_increase_threshold = max(50, math.ceil(baseline_llm_calls * 0.10))
        if llm_call_delta > material_increase_threshold and grounded_gain <= 0:
            reasons.append(
                "llm_calls rose materially without enough grounded gain "
                f"(delta={llm_call_delta}, grounded_gain={grounded_gain})"
            )

    return {
        "pass": not reasons,
        "baseline_run_id": baseline_snapshot["run_id"],
        "candidate_run_id": candidate_snapshot["run_id"],
        "direct_to_fallback_kcs": direct_to_fallback,
        "baseline_seed_floor_fallback": baseline_fallback,
        "candidate_seed_floor_fallback": candidate_fallback,
        "baseline_grounded_total": baseline_snapshot["grounded_total"],
        "candidate_grounded_total": candidate_snapshot["grounded_total"],
        "grounded_gain": grounded_gain,
        "baseline_llm_calls": baseline_llm_calls,
        "candidate_llm_calls": candidate_llm_calls,
        "llm_call_delta": llm_call_delta,
        "material_llm_call_increase_threshold": material_increase_threshold,
        "reasons": reasons,
    }


def _definition_candidates(row: dict[str, Any]) -> list[dict[str, Any]]:
    field_sets = (row.get("selection_diagnostics") or {}).get("field_candidate_sets") or {}
    return list(field_sets.get("definition") or [])


def _definition_support_pack(row: dict[str, Any]) -> list[dict[str, Any]]:
    field_sets = (row.get("selection_diagnostics") or {}).get("field_candidate_sets") or {}
    return list(field_sets.get("definition_support_pack") or [])


def _preservation_definition_candidates(row: dict[str, Any]) -> list[dict[str, Any]]:
    field_sets = (row.get("selection_diagnostics") or {}).get("field_candidate_sets") or {}
    return list(field_sets.get("definition_preservation") or [])


def _selected_bundle_ids(row: dict[str, Any]) -> set[str]:
    diagnostics = row.get("selection_diagnostics") or {}
    return set(diagnostics.get("selected_bundle_candidate_ids") or [])


def _same_kc_overlay_ids(items: list[dict[str, Any]], kc_id: str) -> set[str]:
    overlay_ids: set[str] = set()
    for item in items:
        overlay_id = item.get("overlay_candidate_id")
        source_kc_id = item.get("source_kc_id")
        if not overlay_id:
            continue
        if source_kc_id == kc_id or overlay_id.startswith(f"{kc_id}:overlay:"):
            overlay_ids.add(overlay_id)
    return overlay_ids


def _definition_bundle_overlay_ids(row: dict[str, Any]) -> set[str]:
    overlay_ids: set[str] = set()
    for item in row.get("evidence_bundle") or []:
        assessment = item.get("assessment") or {}
        overlay_id = item.get("overlay_candidate_id")
        if not overlay_id:
            continue
        if item.get("bundle_role") == "definition_support" or assessment.get("definition_signal"):
            overlay_ids.add(overlay_id)
    return overlay_ids


def _grounded_definition_response_keys(row: dict[str, Any]) -> list[str]:
    llm = (row.get("selection_diagnostics") or {}).get("llm_drafting") or {}
    grounded_keys: list[str] = []
    for key in RAW_DRAFT_RESPONSE_KEYS:
        definition = ((llm.get(key) or {}).get("definition") or {})
        if definition.get("status") == "grounded" and (definition.get("text") or "").strip():
            grounded_keys.append(key)
    return grounded_keys


def _verify_abstention_keys(row: dict[str, Any]) -> list[str]:
    llm = (row.get("selection_diagnostics") or {}).get("llm_drafting") or {}
    abstained_keys: list[str] = []
    for key in RAW_VERIFY_RESPONSE_KEYS:
        definition = ((llm.get(key) or {}).get("definition") or {})
        if definition.get("status") == "abstained":
            abstained_keys.append(key)
    return abstained_keys


def _verify_grounded_keys(row: dict[str, Any]) -> list[str]:
    llm = (row.get("selection_diagnostics") or {}).get("llm_drafting") or {}
    grounded_keys: list[str] = []
    for key in RAW_VERIFY_RESPONSE_KEYS:
        definition = ((llm.get(key) or {}).get("definition") or {})
        if definition.get("status") == "grounded" and (definition.get("text") or "").strip():
            grounded_keys.append(key)
    return grounded_keys


def _step53_evidence_items(step53_rows_by_kc: dict[str, list[dict[str, Any]]], kc_id: str) -> list[dict[str, Any]]:
    row_list = step53_rows_by_kc.get(kc_id) or []
    if not row_list:
        return []
    return list((row_list[0].get("evidence") or []))


def _overlay_alignment(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("alignment_breakdown") or {}


def _overlay_flags(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("sentence_flags") or _overlay_alignment(item).get("flags") or {}


def _overlay_contamination(item: dict[str, Any]) -> str:
    return item.get("contamination_risk") or _overlay_alignment(item).get("contamination_risk") or ""


def _overlay_strong_same_topic(item: dict[str, Any]) -> bool:
    return bool(item.get("strong_same_topic") or _overlay_alignment(item).get("strong_same_topic"))


def _overlay_is_definition_like(item: dict[str, Any]) -> bool:
    return bool(item.get("is_definition_like") or _overlay_flags(item).get("is_definition_like"))


def _overlay_is_clean_definition_support(item: dict[str, Any]) -> bool:
    flags = _overlay_flags(item)
    return (
        _overlay_strong_same_topic(item)
        and _overlay_is_definition_like(item)
        and not bool(flags.get("is_procedure_like"))
        and not bool(flags.get("is_example_like"))
        and _overlay_contamination(item) in {"", "low"}
    )


def _llm_definition_payload(row: dict[str, Any], key: str) -> dict[str, Any]:
    llm = (row.get("selection_diagnostics") or {}).get("llm_drafting") or {}
    return ((llm.get(key) or {}).get("definition") or {})


def _definition_grounding_diagnostics(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    selection = row.get("selection_diagnostics") or {}
    native = dict(selection.get("definition_grounding_diagnostics") or {})
    if native:
        native.setdefault(
            "draft_supported_single_span_fallback_candidate_present",
            bool(native.get("control_fallback_candidate_present")),
        )
        native.setdefault(
            "draft_supported_single_span_fallback_source_phase",
            str(native.get("control_fallback_source_phase") or ""),
        )
        native.setdefault(
            "draft_supported_single_span_fallback_support_ids",
            [str(item) for item in native.get("control_fallback_support_ids") or [] if str(item)],
        )
        native.setdefault(
            "draft_supported_single_span_fallback_applied",
            bool(native.get("control_fallback_applied")),
        )
        return native, "native_definition_grounding_diagnostics"

    definition_candidates = _definition_candidates(row)
    preservation_definition_candidates = _preservation_definition_candidates(row)
    support_pack = _definition_support_pack(row)
    preservation_draft = _llm_definition_payload(row, "preservation_draft_response")
    preservation_verify = _llm_definition_payload(row, "preservation_verify_response")
    rescue_draft = _llm_definition_payload(row, "rescue_draft_response")
    rescue_verify = _llm_definition_payload(row, "rescue_verify_response")
    definition_redraft = _llm_definition_payload(row, "definition_redraft_response")
    definition_redraft_verify = _llm_definition_payload(row, "definition_redraft_verify_response")
    llm = (selection.get("llm_drafting") or {})
    final_definition = row.get("definition_full_candidate") or {}

    single_span_local_ids = {
        str(candidate.get("overlay_candidate_id") or "")
        for candidate in definition_candidates
        if candidate.get("single_span_accepted") and candidate.get("candidate_source_relation") == "local"
    }
    control_fallback_source_phase = ""
    control_fallback_support_ids: list[str] = []
    for key in ("preservation_draft_response", "rescue_draft_response", "definition_redraft_response"):
        payload = _llm_definition_payload(row, key)
        support_ids = [str(item) for item in payload.get("supporting_overlay_candidate_ids") or [] if str(item)]
        if payload.get("status") == "grounded" and len(support_ids) == 1 and support_ids[0] in single_span_local_ids:
            control_fallback_source_phase = key
            control_fallback_support_ids = support_ids
            break

    if final_definition.get("status") == "grounded":
        if final_definition.get("selection_reason") == "definition_full_candidate_draft_supported_single_span_fallback":
            collapse_stage = "control_fallback_applied"
        else:
            collapse_stage = "grounded_before_control_fallback"
    elif not definition_candidates:
        collapse_stage = "no_usable_candidate_pool"
    elif preservation_draft.get("status") != "grounded":
        collapse_stage = "no_binding_after_preservation_draft_abstention"
    elif preservation_verify.get("status") == "abstained":
        collapse_stage = "no_binding_after_preservation_verify_rejection"
    elif bool(llm.get("rescue_used")) and rescue_draft.get("status") != "grounded":
        collapse_stage = "no_binding_after_rescue_draft_abstention"
    elif bool(llm.get("rescue_used")) and rescue_verify.get("status") == "abstained":
        collapse_stage = "no_binding_after_rescue_verify_rejection"
    elif definition_redraft_verify.get("status") == "abstained":
        collapse_stage = "no_binding_after_definition_redraft_verify_rejection"
    else:
        collapse_stage = "no_binding_after_control_path_gating"

    return {
        "candidate_pool_size": len(definition_candidates),
        "preservation_candidate_pool_size": len(preservation_definition_candidates),
        "support_pack_size": len(support_pack),
        "preservation_draft_status": str(preservation_draft.get("status") or ""),
        "preservation_verify_status": str(preservation_verify.get("status") or ""),
        "preservation_verify_reason": str(preservation_verify.get("abstention_reason") or ""),
        "rescue_used": bool(llm.get("rescue_used")),
        "rescue_draft_status": str(rescue_draft.get("status") or ""),
        "rescue_verify_status": str(rescue_verify.get("status") or ""),
        "rescue_verify_reason": str(rescue_verify.get("abstention_reason") or ""),
        "definition_redraft_status": str(definition_redraft.get("status") or ""),
        "definition_redraft_verify_status": str(definition_redraft_verify.get("status") or ""),
        "definition_redraft_verify_reason": str(definition_redraft_verify.get("abstention_reason") or ""),
        "control_fallback_candidate_present": bool(control_fallback_support_ids),
        "control_fallback_source_phase": control_fallback_source_phase,
        "control_fallback_support_ids": control_fallback_support_ids,
        "control_fallback_applied": (
            str(final_definition.get("selection_reason") or "") == "definition_full_candidate_draft_supported_single_span_fallback"
        ),
        "draft_supported_single_span_fallback_candidate_present": bool(control_fallback_support_ids),
        "draft_supported_single_span_fallback_source_phase": control_fallback_source_phase,
        "draft_supported_single_span_fallback_support_ids": control_fallback_support_ids,
        "draft_supported_single_span_fallback_applied": (
            str(final_definition.get("selection_reason") or "") == "definition_full_candidate_draft_supported_single_span_fallback"
        ),
        "final_selection_reason": str(final_definition.get("selection_reason") or ""),
        "collapse_stage": collapse_stage,
    }, "inferred_from_saved_step67_payloads"


def _verify_reason_tags(reason: str) -> list[str]:
    tags: list[str] = []
    if not reason.strip():
        tags.append("missing_reason")
        return tags
    if STRICT_VERIFY_REASON_RE.search(reason):
        tags.append("strict_paraphrase_or_scope")
    if SUBSTANTIVE_VERIFY_REASON_RE.search(reason):
        tags.append("substantive_unsupported_detail")
    if "insufficient_evidence" in reason.lower():
        tags.append("insufficient_evidence")
    return tags


def _support_binding_assessment(
    row: dict[str, Any],
    overlay_rows_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    kc_id = row["kc_id"]
    draft_definition = _llm_definition_payload(row, "draft_response")
    support_ids = list(draft_definition.get("supporting_overlay_candidate_ids") or [])
    selected_bundle_ids = _selected_bundle_ids(row)
    same_kc_definition_ids = _same_kc_overlay_ids(_definition_candidates(row), kc_id)
    support_rows = [overlay_rows_by_id[overlay_id] for overlay_id in support_ids if overlay_id in overlay_rows_by_id]
    clean_support_ids = [
        item["overlay_candidate_id"]
        for item in support_rows
        if _overlay_is_clean_definition_support(item)
    ]
    issue_signals: list[str] = []
    if not support_ids:
        issue_signals.append("no_supporting_overlay_ids")
    if len(support_rows) != len(support_ids):
        issue_signals.append("supporting_overlay_ids_missing_from_overlay_payload")
    missing_from_selected = sorted(overlay_id for overlay_id in support_ids if overlay_id not in selected_bundle_ids)
    if missing_from_selected:
        issue_signals.append("supporting_overlay_ids_not_in_selected_bundle")
    missing_from_definition_candidates = sorted(
        overlay_id for overlay_id in support_ids if overlay_id not in same_kc_definition_ids
    )
    if missing_from_definition_candidates:
        issue_signals.append("supporting_overlay_ids_not_in_same_kc_definition_candidates")
    if not clean_support_ids:
        issue_signals.append("no_clean_same_kc_definition_support")

    risk_flags = list(row.get("risk_flags") or [])
    for flag in risk_flags:
        if flag in {
            "review_queue_weak_coverage",
            "not_selected_for_bundle",
            "high_contamination_candidates_present",
            "definition_verification_runtime_failed",
        }:
            issue_signals.append(flag)
        elif flag.startswith("background_drift_") or flag == "neighboring_concept_bleed":
            issue_signals.append("background_drift_or_neighboring_concept_bleed")

    return {
        "supporting_overlay_candidate_ids": support_ids,
        "support_row_count": len(support_rows),
        "support_row_definition_like_count": sum(1 for item in support_rows if _overlay_is_definition_like(item)),
        "support_row_strong_same_topic_count": sum(1 for item in support_rows if _overlay_strong_same_topic(item)),
        "support_row_clean_definition_support_count": len(clean_support_ids),
        "clean_definition_support_overlay_ids": clean_support_ids,
        "issue_signals": sorted(set(issue_signals)),
        "missing_from_selected_bundle": missing_from_selected,
        "missing_from_same_kc_definition_candidates": missing_from_definition_candidates,
        "support_rows": [
            {
                "overlay_candidate_id": item.get("overlay_candidate_id"),
                "quote_surface": item.get("quote_surface") or "",
                "source_candidate_index": item.get("source_candidate_index"),
                "is_definition_like": _overlay_is_definition_like(item),
                "strong_same_topic": _overlay_strong_same_topic(item),
                "contamination_risk": _overlay_contamination(item),
                "sentence_flags": _overlay_flags(item),
            }
            for item in support_rows
        ],
    }


def audit_baseline_step67_rejection_subbuckets(
    baseline_snapshot: dict[str, Any],
    step6_6_manifest_path: Path,
) -> dict[str, Any]:
    root = repo_root()
    step6_6_manifest = read_json(step6_6_manifest_path)
    step6_6_overlay_path = root / step6_6_manifest["artifacts"]["candidate_sentence_overlay_jsonl"]
    overlay_rows_by_id = (
        read_jsonl_index(step6_6_overlay_path, "overlay_candidate_id")
        if step6_6_overlay_path.exists()
        else {}
    )

    records: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter({bucket: 0 for bucket in REJECTION_SUBBUCKET_ORDER})
    bucket_basis_counts: Counter[str] = Counter()

    for row in sorted(
        (
            item
            for item in baseline_snapshot["rows_by_kc"].values()
            if item["authoritative_definition_status"] == "seed_floor_fallback"
        ),
        key=lambda item: item["kc_id"],
    ):
        draft_definition = _llm_definition_payload(row, "draft_response")
        verify_definition = _llm_definition_payload(row, "verify_response")
        redraft_definition = _llm_definition_payload(row, "definition_redraft_response")
        redraft_verify_definition = _llm_definition_payload(row, "definition_redraft_verify_response")
        support_binding = _support_binding_assessment(row, overlay_rows_by_id)
        verify_grounded_keys = _verify_grounded_keys(row)
        direct_control_override_keys = verify_grounded_keys
        verify_reason = (verify_definition.get("abstention_reason") or "").strip()
        verify_reason_tags = _verify_reason_tags(verify_reason)
        raw_draft_grounded = draft_definition.get("status") == "grounded" and bool(
            (draft_definition.get("text") or "").strip()
        )

        if not raw_draft_grounded:
            bucket = REJECTION_SUBBUCKET_MIXED
            bucket_basis = "direct_step67_payload_inspection"
            classification_notes = (
                "No grounded raw draft is present in the accepted-baseline bundle, so the failure cannot be refined "
                "beyond an ambiguous early Step 6.7 loss from the existing payload."
            )
        elif direct_control_override_keys:
            bucket = REJECTION_SUBBUCKET_CONTROL_OVERRIDE
            bucket_basis = "direct_step67_payload_inspection"
            classification_notes = (
                "A grounded verify-stage definition exists in the payload, but the final definition candidate still "
                "lands in fallback, so the loss appears to happen after verification."
            )
        elif support_binding["issue_signals"]:
            bucket = REJECTION_SUBBUCKET_BINDING_WEAK
            bucket_basis = "direct_step67_payload_inspection"
            classification_notes = (
                "The supporting overlay linkage is directly weak, misaligned, or insufficiently definition-shaped in "
                "the accepted-baseline Step 6.7 payload."
            )
        elif "strict_paraphrase_or_scope" in verify_reason_tags and "substantive_unsupported_detail" not in verify_reason_tags:
            bucket = REJECTION_SUBBUCKET_FALSE_REJECT
            bucket_basis = "inferred_from_step67_payload_and_verify_reason"
            classification_notes = (
                "The raw draft has clean same-KC definition support and no direct binding issue, while the verifier "
                "appears to object to wording scope rather than a clearly wrong concept claim."
            )
        elif verify_reason:
            bucket = REJECTION_SUBBUCKET_WEAK_DRAFT
            bucket_basis = "inferred_from_step67_payload_and_verify_reason"
            classification_notes = (
                "The raw draft exists, but the verifier reason indicates substantive unsupported detail or mismatch, "
                "so the draft is not strong enough for grounded acceptance from the available payload."
            )
        else:
            bucket = REJECTION_SUBBUCKET_MIXED
            bucket_basis = "mixed_or_insufficient"
            classification_notes = (
                "The available Step 6.7 payload does not cleanly distinguish verifier overreach from weak drafting."
            )

        bucket_counts[bucket] += 1
        bucket_basis_counts[bucket_basis] += 1

        records.append(
            {
                "kc_id": row["kc_id"],
                "canonical_name": row["canonical_name"],
                "seed_definition": row.get("seed_definition") or "",
                "authoritative_definition_status": row["authoritative_definition_status"],
                "trust_state_label": (row.get("trust_state") or {}).get("label"),
                "effective_definition_phase": row.get("effective_definition_phase"),
                "risk_flags": list(row.get("risk_flags") or []),
                "rejection_subbucket": bucket,
                "rejection_subbucket_basis": bucket_basis,
                "classification_notes": classification_notes,
                "raw_draft_present": "yes" if raw_draft_grounded else "no",
                "draft_response": draft_definition,
                "verify_response": verify_definition,
                "definition_redraft_response": redraft_definition,
                "definition_redraft_verify_response": redraft_verify_definition,
                "verify_reason_tags": verify_reason_tags,
                "verify_grounded_keys": verify_grounded_keys,
                "direct_control_override_keys": direct_control_override_keys,
                "support_binding_assessment": support_binding,
                "selected_bundle_candidate_ids": sorted(_selected_bundle_ids(row)),
                "definition_candidate_overlay_ids": sorted(_same_kc_overlay_ids(_definition_candidates(row), row["kc_id"])),
                "supporting_artifact_refs": {
                    "baseline_bundle_path": baseline_snapshot["artifacts"]["bundle_path"],
                    "baseline_summary_path": baseline_snapshot["artifacts"]["summary_path"],
                    "baseline_input_manifest_path": baseline_snapshot["artifacts"]["input_manifest_path"],
                    "step6_6_manifest_path": relative_to_repo(step6_6_manifest_path, root),
                    "step6_6_overlay_path": relative_to_repo(step6_6_overlay_path, root),
                },
            }
        )

    return {
        "generated_at_utc": now_utc_iso(),
        "accepted_baseline_run_id": baseline_snapshot["run_id"],
        "accepted_baseline_artifacts": baseline_snapshot["artifacts"],
        "accepted_baseline_status_counts": baseline_snapshot["status_counts"],
        "proof_boundary": {
            "direct_step67_payload_inspection": [
                "draft_response",
                "verify_response",
                "definition_redraft_response",
                "definition_redraft_verify_response",
                "effective_definition_phase",
                "risk_flags",
                "final_authoritative_definition_status",
                "final_trust_state",
                "selection_diagnostics.field_candidate_sets",
                "supporting_overlay_candidate_ids",
                "selected_bundle_candidate_ids",
                "step6_6_overlay_support_rows",
            ],
            "inferred_from_step67_payload_and_verify_reason": [
                REJECTION_SUBBUCKET_FALSE_REJECT,
                REJECTION_SUBBUCKET_WEAK_DRAFT,
            ],
        },
        "rejection_subbucket_definitions": {
            "1": REJECTION_SUBBUCKET_FALSE_REJECT,
            "2": REJECTION_SUBBUCKET_CONTROL_OVERRIDE,
            "3": REJECTION_SUBBUCKET_WEAK_DRAFT,
            "4": REJECTION_SUBBUCKET_BINDING_WEAK,
            "5": REJECTION_SUBBUCKET_MIXED,
        },
        "rejection_subbucket_summary": dict(bucket_counts),
        "rejection_subbucket_basis_summary": dict(bucket_basis_counts),
        "records": records,
    }


def render_rejection_subbucket_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 Rejection Subbucket Audit")
    lines.append("")
    lines.append(f"- Generated: `{payload['generated_at_utc']}`")
    lines.append(f"- Accepted baseline run: `{payload['accepted_baseline_run_id']}`")
    lines.append(f"- Accepted baseline status counts: `{payload['accepted_baseline_status_counts']}`")
    lines.append("")
    lines.append("## Proof Boundary")
    for key, values in payload["proof_boundary"].items():
        lines.append(f"- `{key}`: `{values}`")
    lines.append("")
    lines.append("## Rejection Subbucket Summary")
    for bucket_id, bucket_name in payload["rejection_subbucket_definitions"].items():
        count = payload["rejection_subbucket_summary"].get(bucket_name, 0)
        lines.append(f"- `{bucket_id}. {bucket_name}`: `{count}`")
    lines.append("")
    lines.append("## Basis Summary")
    for key, value in payload["rejection_subbucket_basis_summary"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## High-Signal Notes")
    lines.append(
        "- Category 2 is directly absent in the accepted-baseline payload: no fallback KC shows a grounded verify-stage definition that is later overridden."
    )
    lines.append(
        "- Category 4 is directly evidenced from Step 6.7 plus Step 6.6 overlay inspection: many raw grounded drafts are attached to weak, procedure-like, or mismatched support rows rather than clean same-KC definitional spans."
    )
    lines.append(
        "- Categories 1 and 3 remain inferred classifications because the payload shows the verifier rejection reason, but not an external adjudication of whether that rejection was substantively correct."
    )
    lines.append(
        "- Category 1 is intentionally conservative: any fallback KC with a direct support-linkage weakness stays in Category 4 even if the verifier reason also looks overly strict."
    )
    return "\n".join(lines) + "\n"


def _support_row_flags(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("sentence_flags") or {}


def _support_row_flag_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in rows:
        flags = _support_row_flags(item)
        for key in (
            "is_definition_like",
            "is_procedure_like",
            "is_example_like",
            "is_formula_like",
            "is_heading_like",
        ):
            if item.get("is_definition_like") if key == "is_definition_like" else flags.get(key):
                counts[key.removeprefix("is_").removesuffix("_like")] += 1
    return dict(counts)


def _support_row_is_weak_shape(item: dict[str, Any]) -> bool:
    flags = _support_row_flags(item)
    return bool(
        item.get("is_definition_like")
        or flags.get("is_procedure_like")
        or flags.get("is_example_like")
        or flags.get("is_formula_like")
        or flags.get("is_heading_like")
    )


def _overlay_row_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "overlay_candidate_id": item.get("overlay_candidate_id"),
        "quote_surface": item.get("quote_surface") or "",
        "source_candidate_index": item.get("source_candidate_index"),
        "is_definition_like": _overlay_is_definition_like(item),
        "strong_same_topic": _overlay_strong_same_topic(item),
        "contamination_risk": _overlay_contamination(item),
        "sentence_flags": _overlay_flags(item),
    }


def _same_kc_clean_definition_alternative_rows(
    definition_candidate_overlay_ids: list[str],
    bound_support_ids: list[str],
    overlay_rows_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for overlay_id in definition_candidate_overlay_ids:
        if overlay_id in bound_support_ids:
            continue
        item = overlay_rows_by_id.get(overlay_id)
        if not item or not _overlay_is_clean_definition_support(item):
            continue
        rows.append(_overlay_row_summary(item))
    return rows


def _classify_support_binding_subtype(
    binding_record: dict[str, Any],
    overlay_rows_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    assessment = binding_record["support_binding_assessment"]
    support_rows = list(assessment.get("support_rows") or [])
    support_ids = list(assessment.get("supporting_overlay_candidate_ids") or [])
    issue_signals = set(assessment.get("issue_signals") or [])
    support_row_flag_counts = _support_row_flag_counts(support_rows)
    definition_candidate_overlay_ids = list(binding_record.get("definition_candidate_overlay_ids") or [])
    clean_alternative_rows = _same_kc_clean_definition_alternative_rows(
        definition_candidate_overlay_ids=definition_candidate_overlay_ids,
        bound_support_ids=support_ids,
        overlay_rows_by_id=overlay_rows_by_id,
    )
    clean_alternative_ids = [
        item["overlay_candidate_id"] for item in clean_alternative_rows if item.get("overlay_candidate_id")
    ]
    binding_outside_pool = bool(
        assessment.get("missing_from_selected_bundle")
        or assessment.get("missing_from_same_kc_definition_candidates")
        or "supporting_overlay_ids_missing_from_overlay_payload" in issue_signals
    )
    weak_topic_or_crossconcept = bool(
        assessment.get("support_row_strong_same_topic_count", 0) == 0
        or {
            "review_queue_weak_coverage",
            "background_drift_or_neighboring_concept_bleed",
            "high_contamination_candidates_present",
        }
        & issue_signals
    )
    collapsed_multi_row = bool(
        assessment.get("support_row_count", 0) >= 2
        and not binding_outside_pool
        and not clean_alternative_ids
        and support_rows
        and (
            (
                assessment.get("support_row_clean_definition_support_count", 0) == 0
                and all(_support_row_is_weak_shape(item) for item in support_rows)
            )
            or "definition_verification_runtime_failed" in issue_signals
        )
    )

    if clean_alternative_ids:
        subtype = SUPPORT_BINDING_SUBTYPE_BETTER_SAME_KC_UNBOUND
        subtype_basis = "direct_artifact_inspection"
        subtype_notes = (
            "A cleaner same-KC definition row exists in the saved Step 6.7 definition candidate pool, but the raw "
            "draft bound itself to a weaker row instead."
        )
    elif binding_outside_pool:
        subtype = SUPPORT_BINDING_SUBTYPE_BINDING_OUTSIDE_POOL
        subtype_basis = "direct_artifact_inspection"
        subtype_notes = (
            "The raw draft cites support ids that do not stay inside the saved same-KC definition pool or selected "
            "bundle, so the provenance binding is directly unstable."
        )
    elif collapsed_multi_row:
        subtype = SUPPORT_BINDING_SUBTYPE_COLLAPSED_MULTI_ROW
        subtype_basis = "inferred_from_support_shape"
        subtype_notes = (
            "The draft appears to rely on multiple weak same-KC rows together, but the saved binding collapses that "
            "composite support into individually weak rows with no cleaner same-KC definition row selected."
        )
    elif weak_topic_or_crossconcept:
        subtype = SUPPORT_BINDING_SUBTYPE_WEAK_TOPIC
        subtype_basis = "direct_artifact_inspection"
        subtype_notes = (
            "The saved bound row is weakly anchored to the target KC or shows cross-concept/background drift signals, "
            "so the support is too loose to justify the drafted definition precisely."
        )
    elif support_row_flag_counts.get("procedure", 0) or support_row_flag_counts.get("example", 0):
        subtype = SUPPORT_BINDING_SUBTYPE_PROCEDURE_EXAMPLE
        subtype_basis = "direct_artifact_inspection"
        subtype_notes = (
            "The bound support is operational, procedural, or example-shaped rather than a clean definitional row."
        )
    elif support_row_flag_counts.get("formula", 0):
        subtype = SUPPORT_BINDING_SUBTYPE_FORMULA
        subtype_basis = "direct_artifact_inspection"
        subtype_notes = (
            "The bound support is primarily formula- or parameter-shaped without enough plain-language definition "
            "support in the saved binding."
        )
    else:
        subtype = SUPPORT_BINDING_SUBTYPE_BROAD
        subtype_basis = "direct_artifact_inspection"
        subtype_notes = (
            "The bound support stays on-topic but is still too broad, section-level, or multi-proposition to justify "
            "the drafted definition precisely."
        )

    return {
        "support_binding_subtype": subtype,
        "support_binding_subtype_basis": subtype_basis,
        "support_binding_subtype_notes": subtype_notes,
        "support_row_flag_counts": support_row_flag_counts,
        "same_kc_clean_definition_alternative_overlay_ids": clean_alternative_ids,
        "same_kc_clean_definition_alternative_rows": clean_alternative_rows,
    }


def audit_baseline_step67_support_binding_subtypes(
    baseline_snapshot: dict[str, Any],
    step6_6_manifest_path: Path,
) -> dict[str, Any]:
    root = repo_root()
    step6_6_manifest = read_json(step6_6_manifest_path)
    step6_6_overlay_path = root / step6_6_manifest["artifacts"]["candidate_sentence_overlay_jsonl"]
    overlay_rows_by_id = (
        read_jsonl_index(step6_6_overlay_path, "overlay_candidate_id")
        if step6_6_overlay_path.exists()
        else {}
    )
    rejection_payload = audit_baseline_step67_rejection_subbuckets(
        baseline_snapshot=baseline_snapshot,
        step6_6_manifest_path=step6_6_manifest_path,
    )

    binding_records = [
        record
        for record in rejection_payload["records"]
        if record["rejection_subbucket"] == REJECTION_SUBBUCKET_BINDING_WEAK
    ]
    subtype_counts: Counter[str] = Counter(
        {subtype: 0 for subtype in SUPPORT_BINDING_SUBTYPE_ORDER}
    )
    subtype_basis_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []

    for record in binding_records:
        subtype_details = _classify_support_binding_subtype(record, overlay_rows_by_id)
        subtype = subtype_details["support_binding_subtype"]
        subtype_basis = subtype_details["support_binding_subtype_basis"]
        subtype_counts[subtype] += 1
        subtype_basis_counts[subtype_basis] += 1
        records.append(
            {
                "kc_id": record["kc_id"],
                "canonical_name": record["canonical_name"],
                "seed_definition": record["seed_definition"],
                "authoritative_definition_status": record["authoritative_definition_status"],
                "trust_state_label": record["trust_state_label"],
                "effective_definition_phase": record.get("effective_definition_phase"),
                "risk_flags": list(record.get("risk_flags") or []),
                "support_binding_subtype": subtype,
                "support_binding_subtype_basis": subtype_basis,
                "support_binding_subtype_notes": subtype_details["support_binding_subtype_notes"],
                "issue_signals": list((record.get("support_binding_assessment") or {}).get("issue_signals") or []),
                "support_row_count": (record.get("support_binding_assessment") or {}).get("support_row_count", 0),
                "support_row_flag_counts": subtype_details["support_row_flag_counts"],
                "supporting_overlay_candidate_ids": list(
                    (record.get("support_binding_assessment") or {}).get("supporting_overlay_candidate_ids") or []
                ),
                "selected_bundle_candidate_ids": list(record.get("selected_bundle_candidate_ids") or []),
                "definition_candidate_overlay_ids": list(record.get("definition_candidate_overlay_ids") or []),
                "same_kc_clean_definition_alternative_overlay_ids": subtype_details[
                    "same_kc_clean_definition_alternative_overlay_ids"
                ],
                "same_kc_clean_definition_alternative_rows": subtype_details[
                    "same_kc_clean_definition_alternative_rows"
                ],
                "support_rows": list((record.get("support_binding_assessment") or {}).get("support_rows") or []),
                "support_binding_assessment": record["support_binding_assessment"],
                "draft_response": record["draft_response"],
                "verify_response": record["verify_response"],
                "definition_redraft_response": record["definition_redraft_response"],
                "definition_redraft_verify_response": record["definition_redraft_verify_response"],
                "supporting_artifact_refs": record["supporting_artifact_refs"],
            }
        )

    subtype_examples = {
        subtype: [record["kc_id"] for record in records if record["support_binding_subtype"] == subtype][:5]
        for subtype in SUPPORT_BINDING_SUBTYPE_ORDER
    }

    return {
        "generated_at_utc": now_utc_iso(),
        "accepted_baseline_run_id": baseline_snapshot["run_id"],
        "accepted_baseline_artifacts": baseline_snapshot["artifacts"],
        "accepted_baseline_status_counts": baseline_snapshot["status_counts"],
        "target_rejection_bucket": REJECTION_SUBBUCKET_BINDING_WEAK,
        "target_record_count": len(binding_records),
        "proof_boundary": {
            "direct_artifact_inspection": [
                "support_binding_assessment.issue_signals",
                "support_binding_assessment.support_rows",
                "supporting_overlay_candidate_ids",
                "selected_bundle_candidate_ids",
                "definition_candidate_overlay_ids",
                "step6_6_overlay_row_lookup",
            ],
            "inferred_from_support_shape": [
                SUPPORT_BINDING_SUBTYPE_COLLAPSED_MULTI_ROW,
            ],
        },
        "support_binding_subtype_definitions": {
            "1": SUPPORT_BINDING_SUBTYPE_BETTER_SAME_KC_UNBOUND,
            "2": SUPPORT_BINDING_SUBTYPE_BINDING_OUTSIDE_POOL,
            "3": SUPPORT_BINDING_SUBTYPE_COLLAPSED_MULTI_ROW,
            "4": SUPPORT_BINDING_SUBTYPE_WEAK_TOPIC,
            "5": SUPPORT_BINDING_SUBTYPE_PROCEDURE_EXAMPLE,
            "6": SUPPORT_BINDING_SUBTYPE_FORMULA,
            "7": SUPPORT_BINDING_SUBTYPE_BROAD,
        },
        "support_binding_subtype_summary": dict(subtype_counts),
        "support_binding_subtype_basis_summary": dict(subtype_basis_counts),
        "support_binding_subtype_examples": subtype_examples,
        "records": records,
    }


def render_support_binding_subtypes_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 Support-Binding Subtype Audit")
    lines.append("")
    lines.append(f"- Generated: `{payload['generated_at_utc']}`")
    lines.append(f"- Accepted baseline run: `{payload['accepted_baseline_run_id']}`")
    lines.append(f"- Accepted baseline status counts: `{payload['accepted_baseline_status_counts']}`")
    lines.append(f"- Target rejection bucket: `{payload['target_rejection_bucket']}`")
    lines.append(f"- Target record count: `{payload['target_record_count']}`")
    lines.append("")
    lines.append("## Proof Boundary")
    for key, values in payload["proof_boundary"].items():
        lines.append(f"- `{key}`: `{values}`")
    lines.append("")
    lines.append("## Support-Binding Subtype Summary")
    for subtype_id, subtype_name in payload["support_binding_subtype_definitions"].items():
        count = payload["support_binding_subtype_summary"].get(subtype_name, 0)
        examples = payload["support_binding_subtype_examples"].get(subtype_name, [])
        lines.append(f"- `{subtype_id}. {subtype_name}`: `{count}`")
        if examples:
            lines.append(f"  examples: `{examples}`")
    lines.append("")
    lines.append("## Basis Summary")
    for key, value in payload["support_binding_subtype_basis_summary"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## High-Signal Notes")
    lines.append(
        "- The accepted-baseline support-binding problem is not a single failure mode: it splits into wrong-row binding, off-pool provenance instability, multi-row weak composites, weak topic anchors, and weak support-shape anchors."
    )
    lines.append(
        "- Only the collapsed-multi-row bucket is explicitly marked as inferred; the other subtype families come directly from saved support ids, saved definition-candidate ids, saved bundle membership, and the real Step 6.6 overlay rows."
    )
    lines.append(
        "- The subtype audit is accepted-baseline only and does not treat the current alias or later diagnostic runs as the reference surface."
    )
    return "\n".join(lines) + "\n"


def audit_baseline_fallbacks(
    baseline_snapshot: dict[str, Any],
    step6_6_manifest_path: Path,
    step6_7_manifest_path: Path,
    diagnostic_snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = repo_root()
    step6_6_manifest = read_json(step6_6_manifest_path)
    step6_7_manifest = read_json(step6_7_manifest_path)
    step5_3_set_path = root / step6_6_manifest["upstream"]["step5_3_active_set_target"]
    step5_3_review_queue_path = root / step6_6_manifest["upstream"]["review_queue_jsonl"]
    step6_6_overlay_path = root / step6_6_manifest["artifacts"]["candidate_sentence_overlay_jsonl"]
    step6_6_overlay_stats_path = root / step6_6_manifest["artifacts"]["overlay_stats_json"]
    step5_3_set_payload = read_json(step5_3_set_path) if step5_3_set_path.exists() else {}
    step5_3_candidates_path = None
    if step5_3_set_payload:
        candidate_rel = (
            (step5_3_set_payload.get("artifacts") or {}).get("kc_evidence_candidates_recalibrated_jsonl")
        )
        if candidate_rel:
            step5_3_candidates_path = root / candidate_rel

    artifact_availability = {
        "step5_3_set_present": step5_3_set_path.exists(),
        "step5_3_candidates_present": bool(step5_3_candidates_path and step5_3_candidates_path.exists()),
        "step5_3_review_queue_present": step5_3_review_queue_path.exists(),
        "step6_6_overlay_present": step6_6_overlay_path.exists(),
        "step6_6_overlay_stats_present": step6_6_overlay_stats_path.exists(),
        "step6_6_manifest_present": step6_6_manifest_path.exists(),
        "step6_7_manifest_present": step6_7_manifest_path.exists(),
    }

    records: list[dict[str, Any]] = []
    counters = {
        "step5_3_definition_evidence_visible": Counter(),
        "step5_3_definition_evidence_visible_basis": Counter(),
        "step6_6_preserved_in_overlay": Counter(),
        "step6_6_preserved_in_overlay_basis": Counter(),
        "step6_7_definition_candidate_set": Counter(),
        "step6_7_prellm_definition_surface": Counter(),
        "raw_draft_candidate_present": Counter(),
        "likely_failure_locus": Counter(),
        "confidence": Counter(),
    }

    fallback_rows = [
        row
        for row in baseline_snapshot["rows_by_kc"].values()
        if row["authoritative_definition_status"] == "seed_floor_fallback"
    ]
    fallback_kc_ids = {row["kc_id"] for row in fallback_rows}

    step53_rows_by_kc: dict[str, list[dict[str, Any]]] = {}
    if step5_3_candidates_path and step5_3_candidates_path.exists():
        step53_rows_by_kc = read_jsonl_by_kc(step5_3_candidates_path, fallback_kc_ids)

    overlay_rows_by_kc: dict[str, list[dict[str, Any]]] = {}
    if step6_6_overlay_path.exists():
        overlay_rows_by_kc = read_jsonl_by_kc(step6_6_overlay_path, fallback_kc_ids)

    review_queue_kc_ids: set[str] = set()
    if step5_3_review_queue_path.exists():
        with step5_3_review_queue_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                kc_id = record.get("kc_id")
                if kc_id in fallback_kc_ids:
                    review_queue_kc_ids.add(kc_id)

    for row in sorted(fallback_rows, key=lambda item: item["kc_id"]):
        kc_id = row["kc_id"]
        definition_candidates = _definition_candidates(row)
        same_kc_definition_ids = _same_kc_overlay_ids(definition_candidates, kc_id)
        support_pack_ids = _same_kc_overlay_ids(_definition_support_pack(row), kc_id)
        selected_bundle_ids = _selected_bundle_ids(row)
        definition_bundle_ids = {
            overlay_id
            for overlay_id in _definition_bundle_overlay_ids(row)
            if overlay_id.startswith(f"{kc_id}:overlay:")
        }
        prellm_surface_ids = sorted(
            (same_kc_definition_ids & selected_bundle_ids) | support_pack_ids | definition_bundle_ids
        )
        grounded_draft_keys = _grounded_definition_response_keys(row)
        verify_abstention_keys = _verify_abstention_keys(row)
        step53_evidence = _step53_evidence_items(step53_rows_by_kc, kc_id)
        overlay_rows = list(overlay_rows_by_kc.get(kc_id) or [])
        step53_definition_like_indices = {
            index
            for index, candidate in enumerate(step53_evidence)
            if _is_definition_like_candidate(candidate)
        }
        overlay_all_indices = {
            candidate.get("source_candidate_index")
            for candidate in overlay_rows
            if candidate.get("source_candidate_index") is not None
        }
        overlay_definition_like_indices = {
            candidate.get("source_candidate_index")
            for candidate in overlay_rows
            if candidate.get("source_candidate_index") is not None
            and _is_definition_like_candidate(candidate)
        }

        if step53_evidence:
            step5_3_visible = "yes" if step53_definition_like_indices else "no"
            step5_3_visible_basis = "direct_upstream_payload_inspection"
        else:
            step5_3_visible = "uncertain"
            step5_3_visible_basis = "step6_7_lineage_only"

        if step53_evidence and overlay_rows:
            if (
                set(range(len(step53_evidence))).issubset(overlay_all_indices)
                and step53_definition_like_indices.issubset(overlay_definition_like_indices)
            ):
                step6_6_preserved = "full"
            else:
                step6_6_preserved = "partial"
            step6_6_preserved_basis = "direct_upstream_payload_inspection"
        elif step53_evidence and not overlay_rows:
            step6_6_preserved = "no"
            step6_6_preserved_basis = "direct_upstream_payload_inspection"
        else:
            step6_6_preserved = "uncertain"
            step6_6_preserved_basis = "step6_7_lineage_only"

        step6_7_candidate_set = "yes" if same_kc_definition_ids else "no"
        step6_7_prellm_surface = "yes" if prellm_surface_ids else "no"
        raw_draft_present = "yes" if grounded_draft_keys else "no"

        if step5_3_visible == "no":
            likely_failure_locus = "step5_3_evidence_not_actually_definitional"
            confidence = "high"
        elif step6_6_preserved in {"partial", "no"}:
            likely_failure_locus = "step6_6_losing_definitional_evidence"
            confidence = "high"
        elif grounded_draft_keys and verify_abstention_keys:
            likely_failure_locus = "step6_7_verification_or_control_rejection_after_good_raw_drafting"
            confidence = "high"
        elif prellm_surface_ids and not grounded_draft_keys:
            likely_failure_locus = "step6_7_support_pack_or_candidate_construction_failure"
            confidence = "medium"
        else:
            likely_failure_locus = "mixed_or_other"
            confidence = "low"

        counters["step5_3_definition_evidence_visible"][step5_3_visible] += 1
        counters["step6_6_preserved_in_overlay"][step6_6_preserved] += 1
        counters["step6_7_definition_candidate_set"][step6_7_candidate_set] += 1
        counters["step6_7_prellm_definition_surface"][step6_7_prellm_surface] += 1
        counters["raw_draft_candidate_present"][raw_draft_present] += 1
        counters["likely_failure_locus"][likely_failure_locus] += 1
        counters["confidence"][confidence] += 1
        counters["step5_3_definition_evidence_visible_basis"][step5_3_visible_basis] += 1
        counters["step6_6_preserved_in_overlay_basis"][step6_6_preserved_basis] += 1

        records.append(
            {
                "kc_id": kc_id,
                "canonical_name": row["canonical_name"],
                "seed_definition": row["seed_definition"],
                "baseline_status": row["authoritative_definition_status"],
                "step5_3_definition_evidence_visible": step5_3_visible,
                "step5_3_definition_evidence_visible_basis": step5_3_visible_basis,
                "step5_3_row_present": "yes" if step53_evidence else "no",
                "step5_3_evidence_count": len(step53_evidence),
                "step5_3_definition_like_evidence_count": len(step53_definition_like_indices),
                "step5_3_review_queue_hit": "yes" if kc_id in review_queue_kc_ids else "no",
                "step6_6_preserved_in_overlay": step6_6_preserved,
                "step6_6_preserved_in_overlay_basis": step6_6_preserved_basis,
                "step6_6_overlay_row_count": len(overlay_rows),
                "step6_6_overlay_preserved_all_step5_3_indices": "yes"
                if step53_evidence and set(range(len(step53_evidence))).issubset(overlay_all_indices)
                else "no"
                if step53_evidence
                else "uncertain",
                "step6_6_overlay_preserved_all_step5_3_definition_like_indices": "yes"
                if step53_evidence and step53_definition_like_indices.issubset(overlay_definition_like_indices)
                else "no"
                if step53_evidence
                else "uncertain",
                "step6_7_definition_candidate_set": step6_7_candidate_set,
                "step6_7_prellm_definition_surface": step6_7_prellm_surface,
                "raw_draft_candidate_present": raw_draft_present,
                "verify_abstention_after_raw_draft": "yes" if grounded_draft_keys and verify_abstention_keys else "no",
                "likely_failure_locus": likely_failure_locus,
                "confidence": confidence,
                "supporting_overlay_candidate_ids": sorted(
                    same_kc_definition_ids | set(prellm_surface_ids)
                )[:12],
                "grounded_draft_response_keys": grounded_draft_keys,
                "verify_abstention_keys": verify_abstention_keys,
                "supporting_artifact_refs": {
                    "baseline_bundle_path": baseline_snapshot["artifacts"]["bundle_path"],
                    "baseline_summary_path": baseline_snapshot["artifacts"]["summary_path"],
                    "baseline_input_manifest_path": baseline_snapshot["artifacts"]["input_manifest_path"],
                    "step6_6_manifest_path": relative_to_repo(step6_6_manifest_path, root),
                    "step6_7_manifest_path": relative_to_repo(step6_7_manifest_path, root),
                    "step5_3_set_path": relative_to_repo(step5_3_set_path, root),
                    "step5_3_candidates_path": relative_to_repo(step5_3_candidates_path, root)
                    if step5_3_candidates_path
                    else "",
                    "step5_3_review_queue_path": relative_to_repo(step5_3_review_queue_path, root),
                    "step6_6_overlay_path": relative_to_repo(step6_6_overlay_path, root),
                    "step6_6_overlay_stats_path": relative_to_repo(step6_6_overlay_stats_path, root),
                },
            }
        )

    comparisons: list[dict[str, Any]] = []
    if diagnostic_snapshots:
        for snapshot in diagnostic_snapshots:
            comparisons.append(compare_step67_runs(baseline_snapshot, snapshot))

    dominant_failure_locus = max(
        counters["likely_failure_locus"].items(),
        key=lambda item: item[1],
    )[0]

    return {
        "generated_at_utc": now_utc_iso(),
        "accepted_baseline_run_id": baseline_snapshot["run_id"],
        "accepted_baseline_artifacts": baseline_snapshot["artifacts"],
        "accepted_baseline_status_counts": baseline_snapshot["status_counts"],
        "artifact_availability": artifact_availability,
        "dominant_failure_locus": dominant_failure_locus,
        "proof_boundary": {
            "direct_upstream_payload_inspection": [
                "step5_3_definition_evidence_visible",
                "step6_6_preserved_in_overlay",
                "step5_3_row_present",
                "step5_3_evidence_count",
                "step5_3_definition_like_evidence_count",
                "step5_3_review_queue_hit",
                "step6_6_overlay_row_count",
                "step6_6_overlay_preserved_all_step5_3_indices",
                "step6_6_overlay_preserved_all_step5_3_definition_like_indices",
            ],
            "step6_7_lineage_only": [
                "step6_7_definition_candidate_set",
                "step6_7_prellm_definition_surface",
                "raw_draft_candidate_present",
                "verify_abstention_after_raw_draft",
                "grounded_draft_response_keys",
                "verify_abstention_keys",
            ],
        },
        "step6_6_manifest": {
            "path": relative_to_repo(step6_6_manifest_path, root),
            "set_id": step6_6_manifest.get("set_id"),
            "artifacts": step6_6_manifest.get("artifacts"),
            "upstream": step6_6_manifest.get("upstream"),
        },
        "step5_3_set": {
            "path": relative_to_repo(step5_3_set_path, root),
            "set_id": step5_3_set_payload.get("set_id"),
            "artifacts": step5_3_set_payload.get("artifacts"),
        },
        "step6_7_manifest": {
            "path": relative_to_repo(step6_7_manifest_path, root),
            "set_id": step6_7_manifest.get("set_id"),
        },
        "run_comparisons": comparisons,
        "fallback_audit_summary": {key: dict(counter) for key, counter in counters.items()},
        "fallback_records": records,
    }


def render_audit_markdown(audit_payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 5.3 -> Step 6.6 -> Step 6.7 Forensic Audit")
    lines.append("")
    lines.append(f"- Generated: `{audit_payload['generated_at_utc']}`")
    lines.append(f"- Accepted baseline run: `{audit_payload['accepted_baseline_run_id']}`")
    lines.append(f"- Accepted baseline status counts: `{audit_payload['accepted_baseline_status_counts']}`")
    lines.append(f"- Dominant failure locus: `{audit_payload['dominant_failure_locus']}`")
    lines.append("")
    lines.append("## Local Artifact Availability")
    for key, value in sorted(audit_payload["artifact_availability"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Proof Boundary")
    for key, values in audit_payload["proof_boundary"].items():
        lines.append(f"- `{key}`: `{values}`")
    lines.append("")
    lines.append("## Direct Upstream Findings")
    summary = audit_payload["fallback_audit_summary"]
    for key in (
        "step5_3_definition_evidence_visible",
        "step5_3_definition_evidence_visible_basis",
        "step6_6_preserved_in_overlay",
        "step6_6_preserved_in_overlay_basis",
    ):
        lines.append(f"- `{key}`: `{summary.get(key, {})}`")
    lines.append("")
    lines.append("## Step 6.7 Lineage Findings")
    for key in (
        "step6_7_definition_candidate_set",
        "step6_7_prellm_definition_surface",
        "raw_draft_candidate_present",
        "likely_failure_locus",
        "confidence",
    ):
        lines.append(f"- `{key}`: `{summary.get(key, {})}`")
    if audit_payload["run_comparisons"]:
        lines.append("")
        lines.append("## Run Comparison Summary")
        for comparison in audit_payload["run_comparisons"]:
            gate = comparison["no_regression_gate"]
            lines.append(
                f"- `{comparison['candidate_run_id']}`: "
                f"transitions=`{comparison['transition_counts']}`, "
                f"regressions=`{comparison['regression_count']}`, "
                f"improvements=`{comparison['improvement_count']}`, "
                f"gate_pass=`{gate['pass']}`"
            )
            if gate["reasons"]:
                lines.append(f"  reasons: `{gate['reasons']}`")
    lines.append("")
    lines.append("## High-Signal Findings")
    lines.append(
        "- The accepted baseline now has real local Step 5.3 and Step 6.6 payloads, so upstream evidence preservation is directly auditable instead of inferred from Step 6.7 lineage."
    )
    lines.append(
        "- Keep the accepted baseline fixed at `2026-04-16_194203`; the current Step 6.7 alias is a separate diagnostic pointer and must not be treated as the accepted baseline."
    )
    return "\n".join(lines) + "\n"


def audit_step67_touch_comparison(
    baseline_snapshot: dict[str, Any],
    candidate_snapshot: dict[str, Any],
) -> dict[str, Any]:
    comparison = compare_step67_runs(baseline_snapshot, candidate_snapshot)
    return {
        "generated_at_utc": now_utc_iso(),
        "baseline_run_id": baseline_snapshot["run_id"],
        "candidate_run_id": candidate_snapshot["run_id"],
        "baseline_status_counts": baseline_snapshot["status_counts"],
        "candidate_status_counts": candidate_snapshot["status_counts"],
        "baseline_llm_calls": baseline_snapshot.get("llm_calls"),
        "candidate_llm_calls": candidate_snapshot.get("llm_calls"),
        "transition_counts": comparison["transition_counts"],
        "binding_touch_summary": comparison["binding_touch_summary"],
        "regressions": comparison["regressions"],
        "improvements": comparison["improvements"],
        "no_regression_gate": comparison["no_regression_gate"],
        "artifacts": {
            "baseline": baseline_snapshot["artifacts"],
            "candidate": candidate_snapshot["artifacts"],
        },
    }


def render_touch_comparison_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 Binding Touch Comparison")
    lines.append("")
    lines.append(f"- Generated: `{payload['generated_at_utc']}`")
    lines.append(f"- Baseline run: `{payload['baseline_run_id']}`")
    lines.append(f"- Candidate run: `{payload['candidate_run_id']}`")
    lines.append(f"- Transition counts: `{payload['transition_counts']}`")
    lines.append(f"- Binding touch summary: `{payload['binding_touch_summary']}`")
    lines.append(f"- No-regression gate pass: `{payload['no_regression_gate']['pass']}`")
    if payload["no_regression_gate"]["reasons"]:
        lines.append(f"- No-regression gate reasons: `{payload['no_regression_gate']['reasons']}`")
    lines.append("")
    lines.append("## Regressions")
    for record in payload["regressions"]:
        binding_diag = record["binding_repair_diagnostics"]
        lines.append(
            f"- `{record['kc_id']}`: `{record['baseline_status']} -> {record['candidate_status']}`; "
            f"`{record['binding_touch_classification']}`; "
            f"`repair_state={binding_diag['repair_state']}`; "
            f"`repair_applied={binding_diag['repair_applied']}`; "
            f"`repair_reason={binding_diag['repair_reason']}`; "
            f"`repair_attempt_reason={binding_diag['repair_attempt_reason']}`"
        )
    lines.append("")
    lines.append("## Improvements")
    for record in payload["improvements"]:
        binding_diag = record["binding_repair_diagnostics"]
        lines.append(
            f"- `{record['kc_id']}`: `{record['baseline_status']} -> {record['candidate_status']}`; "
            f"`{record['binding_touch_classification']}`; "
            f"`repair_state={binding_diag['repair_state']}`; "
            f"`repair_reason={binding_diag['repair_reason']}`"
        )
    lines.append("")
    lines.append("## High-Signal Notes")
    lines.append(
        "- `untouched_but_improved` is emitted explicitly when a candidate improves without any applied binding repair. This keeps the touched/untouched accounting honest for the real 2026-04-17_194932 artifact surface."
    )
    lines.append(
        "- Legacy candidate artifacts can carry an action-like `repair_reason` even when `repair_applied=false`; the comparison normalizes those rows into a durable `repair_state` plus `repair_attempt_reason` for attribution."
    )
    return "\n".join(lines) + "\n"


def audit_step67_untouched_definition_not_grounded_regressions(
    baseline_snapshot: dict[str, Any],
    candidate_snapshot: dict[str, Any],
    *,
    kc_ids: Sequence[str],
) -> dict[str, Any]:
    baseline_rows = baseline_snapshot["rows_by_kc"]
    candidate_rows = candidate_snapshot["rows_by_kc"]
    records: list[dict[str, Any]] = []

    for kc_id in kc_ids:
        baseline_row = baseline_rows[kc_id]
        candidate_row = candidate_rows[kc_id]
        candidate_binding_diag = normalize_definition_support_binding_diagnostics(candidate_row)
        baseline_llm = (baseline_row.get("selection_diagnostics") or {}).get("llm_drafting") or {}
        candidate_llm = (candidate_row.get("selection_diagnostics") or {}).get("llm_drafting") or {}
        baseline_definition = baseline_row.get("definition_full_candidate") or {}
        candidate_definition = candidate_row.get("definition_full_candidate") or {}

        baseline_candidate_ids = [str(item.get("overlay_candidate_id") or "") for item in _definition_candidates(baseline_row) if str(item.get("overlay_candidate_id") or "")]
        candidate_candidate_ids = [str(item.get("overlay_candidate_id") or "") for item in _definition_candidates(candidate_row) if str(item.get("overlay_candidate_id") or "")]
        baseline_candidate_set = set(baseline_candidate_ids)
        candidate_candidate_set = set(candidate_candidate_ids)
        candidate_pool_changed = baseline_candidate_set != candidate_candidate_set
        candidate_pool_added_ids = sorted(candidate_candidate_set - baseline_candidate_set)
        candidate_pool_removed_ids = sorted(baseline_candidate_set - candidate_candidate_set)

        baseline_draft_definition = _llm_definition_payload(baseline_row, "draft_response")
        baseline_verify_definition = _llm_definition_payload(baseline_row, "verify_response")
        candidate_preservation_draft = _llm_definition_payload(candidate_row, "preservation_draft_response")
        candidate_preservation_verify = _llm_definition_payload(candidate_row, "preservation_verify_response")
        candidate_rescue_draft = _llm_definition_payload(candidate_row, "rescue_draft_response")
        candidate_rescue_verify = _llm_definition_payload(candidate_row, "rescue_verify_response")
        candidate_redraft = _llm_definition_payload(candidate_row, "definition_redraft_response")
        candidate_redraft_verify = _llm_definition_payload(candidate_row, "definition_redraft_verify_response")

        preservation_result_changed = bool(
            str(baseline_draft_definition.get("status") or "") != str(candidate_preservation_draft.get("status") or "")
            or _normalize_ws(baseline_draft_definition.get("text") or "") != _normalize_ws(candidate_preservation_draft.get("text") or "")
        )

        baseline_verify_grounded = str(baseline_verify_definition.get("status") or "") == "grounded"
        candidate_verify_grounded = any(
            str(payload.get("status") or "") == "grounded"
            for payload in (
                candidate_preservation_verify,
                _llm_definition_payload(candidate_row, "verify_response"),
                candidate_rescue_verify,
                candidate_redraft_verify,
            )
        )
        verification_result_changed = bool(
            baseline_verify_grounded != candidate_verify_grounded
            or (
                str(candidate_preservation_verify.get("status") or "") != str(baseline_verify_definition.get("status") or "")
                and str(baseline_definition.get("selection_reason") or "") != "definition_full_candidate_single_span_fallback"
            )
        )

        baseline_used_control_fallback = str(baseline_definition.get("selection_reason") or "") == "definition_full_candidate_single_span_fallback"
        candidate_later_control_override = bool(candidate_verify_grounded and str(candidate_definition.get("status") or "") != "grounded")
        later_control_logic_changed = bool(baseline_used_control_fallback or candidate_later_control_override)

        diagnostics_masking_real_step = not any(
            [
                candidate_pool_changed,
                preservation_result_changed,
                verification_result_changed,
                later_control_logic_changed,
            ]
        )

        if later_control_logic_changed and baseline_used_control_fallback:
            dominant_collapse_path = "later_control_logic_changed"
            dominant_basis = (
                "baseline final definition came from definition_full_candidate_single_span_fallback, "
                "so the accepted baseline did not depend on a grounded verify response"
            )
        elif verification_result_changed:
            dominant_collapse_path = "verification_result_changed"
            dominant_basis = "baseline verify path stayed grounded or accepted while candidate verify paths abstained"
        elif candidate_pool_changed:
            dominant_collapse_path = "candidate_pool_changed"
            dominant_basis = "definition candidate ids changed between baseline and candidate"
        elif preservation_result_changed:
            dominant_collapse_path = "preservation_result_changed"
            dominant_basis = "candidate preservation draft output materially changed relative to the baseline draft"
        else:
            dominant_collapse_path = "diagnostics_masking_real_step"
            dominant_basis = "saved payloads do not isolate one dominant collapse step"

        records.append(
            {
                "kc_id": kc_id,
                "baseline_status": baseline_row["authoritative_definition_status"],
                "candidate_status": candidate_row["authoritative_definition_status"],
                "binding_touch_classification": _touch_classification(
                    delta=STATUS_RANK[candidate_row["authoritative_definition_status"]] - STATUS_RANK[baseline_row["authoritative_definition_status"]],
                    repair_applied=bool(candidate_binding_diag.get("repair_applied")),
                ),
                "candidate_binding_repair_state": candidate_binding_diag["repair_state"],
                "candidate_binding_repair_reason": candidate_binding_diag["repair_reason"],
                "candidate_binding_repair_attempt_reason": candidate_binding_diag["repair_attempt_reason"],
                "candidate_pool_changed": candidate_pool_changed,
                "candidate_pool_added_ids": candidate_pool_added_ids,
                "candidate_pool_removed_ids": candidate_pool_removed_ids,
                "preservation_result_changed": preservation_result_changed,
                "verification_result_changed": verification_result_changed,
                "later_control_logic_changed": later_control_logic_changed,
                "diagnostics_masking_real_step": diagnostics_masking_real_step,
                "dominant_collapse_path": dominant_collapse_path,
                "dominant_collapse_basis": dominant_basis,
                "baseline_selection_reason": str(baseline_definition.get("selection_reason") or ""),
                "candidate_selection_reason": str(candidate_definition.get("selection_reason") or ""),
                "baseline_verify_status": str(baseline_verify_definition.get("status") or ""),
                "candidate_preservation_verify_status": str(candidate_preservation_verify.get("status") or ""),
                "candidate_rescue_verify_status": str(candidate_rescue_verify.get("status") or ""),
                "candidate_definition_redraft_verify_status": str(candidate_redraft_verify.get("status") or ""),
                "baseline_verify_reason": str(baseline_verify_definition.get("abstention_reason") or ""),
                "candidate_preservation_verify_reason": str(candidate_preservation_verify.get("abstention_reason") or ""),
                "candidate_definition_redraft_verify_reason": str(candidate_redraft_verify.get("abstention_reason") or ""),
                "baseline_errors": {
                    "verify_error": str(baseline_llm.get("verify_error") or ""),
                    "definition_redraft_verify_error": str(baseline_llm.get("definition_redraft_verify_error") or ""),
                },
                "candidate_errors": {
                    "verify_error": str(candidate_llm.get("verify_error") or ""),
                    "preservation_verify_error": str(candidate_llm.get("preservation_verify_error") or ""),
                    "rescue_verify_error": str(candidate_llm.get("rescue_verify_error") or ""),
                    "definition_redraft_verify_error": str(candidate_llm.get("definition_redraft_verify_error") or ""),
                },
                "supporting_artifact_refs": {
                    "baseline_bundle_path": baseline_snapshot["artifacts"]["bundle_path"],
                    "candidate_bundle_path": candidate_snapshot["artifacts"]["bundle_path"],
                    "baseline_summary_path": baseline_snapshot["artifacts"]["summary_path"],
                    "candidate_summary_path": candidate_snapshot["artifacts"]["summary_path"],
                },
            }
        )

    path_summary = Counter(record["dominant_collapse_path"] for record in records)
    return {
        "generated_at_utc": now_utc_iso(),
        "baseline_run_id": baseline_snapshot["run_id"],
        "candidate_run_id": candidate_snapshot["run_id"],
        "target_kc_ids": list(kc_ids),
        "dominant_collapse_path_summary": dict(path_summary),
        "records": records,
    }


def audit_step67_definition_not_grounded_cases(snapshot: dict[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    direct_stage_counts: Counter[str] = Counter()
    subbucket_counts: Counter[str] = Counter()
    direct_basis_counts: Counter[str] = Counter()

    for kc_id, row in snapshot["rows_by_kc"].items():
        binding_diag = normalize_definition_support_binding_diagnostics(row)
        if binding_diag.get("repair_reason") != "definition_not_grounded":
            continue
        grounding_diag, grounding_basis = _definition_grounding_diagnostics(row)
        direct_basis_counts[grounding_basis] += 1
        direct_stage_counts[f"candidate_pool_size_{grounding_diag['candidate_pool_size']}"] += 1
        direct_stage_counts[f"preservation_draft_{grounding_diag['preservation_draft_status'] or 'missing'}"] += 1
        direct_stage_counts[f"preservation_verify_{grounding_diag['preservation_verify_status'] or 'missing'}"] += 1
        direct_stage_counts[f"rescue_used_{grounding_diag['rescue_used']}"] += 1
        direct_stage_counts[f"rescue_draft_{grounding_diag['rescue_draft_status'] or 'missing'}"] += 1
        direct_stage_counts[f"rescue_verify_{grounding_diag['rescue_verify_status'] or 'missing'}"] += 1
        direct_stage_counts[f"definition_redraft_{grounding_diag['definition_redraft_status'] or 'missing'}"] += 1
        direct_stage_counts[f"definition_redraft_verify_{grounding_diag['definition_redraft_verify_status'] or 'missing'}"] += 1
        direct_stage_counts[f"control_fallback_candidate_present_{grounding_diag['control_fallback_candidate_present']}"] += 1
        direct_stage_counts[f"collapse_stage_{grounding_diag['collapse_stage']}"] += 1

        if grounding_diag["preservation_draft_status"] != "grounded":
            if grounding_diag["rescue_draft_status"] == "grounded":
                subbucket = DEF_NOT_GROUNDED_SUBBUCKET_PRES_ABSTAIN_RESCUE_GROUNDED
            else:
                subbucket = DEF_NOT_GROUNDED_SUBBUCKET_PRES_ABSTAIN_RESCUE_ABSTAIN
        elif grounding_diag["control_fallback_candidate_present"]:
            subbucket = DEF_NOT_GROUNDED_SUBBUCKET_VERIFY_REJECTED_WITH_FALLBACK
        else:
            subbucket = DEF_NOT_GROUNDED_SUBBUCKET_VERIFY_REJECTED_WITHOUT_FALLBACK
        subbucket_counts[subbucket] += 1

        records.append(
            {
                "kc_id": kc_id,
                "authoritative_definition_status": row["authoritative_definition_status"],
                "trust_state_label": str((row.get("trust_state") or {}).get("label") or ""),
                "repair_state": binding_diag["repair_state"],
                "repair_reason": binding_diag["repair_reason"],
                "repair_attempt_reason": binding_diag["repair_attempt_reason"],
                "definition_not_grounded_subbucket": subbucket,
                "subbucket_basis": "direct_step67_payload_evidence",
                "grounding_diagnostics": grounding_diag,
                "grounding_diagnostics_basis": grounding_basis,
                "supporting_artifact_refs": {
                    "bundle_path": snapshot["artifacts"]["bundle_path"],
                    "summary_path": snapshot["artifacts"]["summary_path"],
                },
            }
        )

    records.sort(key=lambda item: item["kc_id"])
    return {
        "generated_at_utc": now_utc_iso(),
        "candidate_run_id": snapshot["run_id"],
        "definition_not_grounded_case_count": len(records),
        "definition_not_grounded_subbucket_summary": {
            key: int(subbucket_counts.get(key, 0))
            for key in DEF_NOT_GROUNDED_SUBBUCKET_ORDER
        },
        "direct_stage_counts": dict(direct_stage_counts),
        "direct_basis_counts": dict(direct_basis_counts),
        "records": records,
    }


def audit_step67_persistent_regressions(
    baseline_snapshot: dict[str, Any],
    candidate_snapshots: Sequence[dict[str, Any]],
    *,
    kc_ids: Sequence[str],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    candidate_run_ids = [snapshot["run_id"] for snapshot in candidate_snapshots]

    for kc_id in kc_ids:
        baseline_row = baseline_snapshot["rows_by_kc"][kc_id]
        candidate_records: list[dict[str, Any]] = []
        regressed_in_all = True
        for snapshot in candidate_snapshots:
            candidate_row = snapshot["rows_by_kc"][kc_id]
            baseline_status = str(baseline_row.get("authoritative_definition_status") or "")
            candidate_status = str(candidate_row.get("authoritative_definition_status") or "")
            regressed = STATUS_RANK.get(candidate_status, -1) < STATUS_RANK.get(baseline_status, -1)
            regressed_in_all = regressed_in_all and regressed
            binding_diag = normalize_definition_support_binding_diagnostics(candidate_row)
            grounding_diag, grounding_basis = _definition_grounding_diagnostics(candidate_row)
            if binding_diag.get("repair_reason") == "definition_not_grounded":
                collapse_stage = grounding_diag.get("collapse_stage") or ""
            elif binding_diag.get("repair_state") == REPAIR_STATE_REJECTED and candidate_status == "normalized_grounded":
                collapse_stage = "binding_repair_rejected_then_normalization_only"
            elif binding_diag.get("repair_state") == REPAIR_STATE_APPLIED and candidate_status == "normalized_grounded":
                collapse_stage = "binding_repair_applied_then_normalization_only"
            else:
                collapse_stage = "non_definition_not_grounded_regression"
            candidate_records.append(
                {
                    "candidate_run_id": snapshot["run_id"],
                    "candidate_status": candidate_status,
                    "regressed_vs_baseline": regressed,
                    "collapse_stage": collapse_stage,
                    "collapse_stage_basis": (
                        "direct_step67_payload_evidence"
                        if binding_diag.get("repair_reason") == "definition_not_grounded"
                        else "direct_binding_and_selection_diagnostics"
                    ),
                    "binding_repair_state": binding_diag["repair_state"],
                    "binding_repair_reason": binding_diag["repair_reason"],
                    "binding_repair_attempt_reason": binding_diag["repair_attempt_reason"],
                    "final_selection_reason": str((candidate_row.get("definition_full_candidate") or {}).get("selection_reason") or ""),
                    "grounding_diagnostics": grounding_diag,
                    "grounding_diagnostics_basis": grounding_basis,
                }
            )
        records.append(
            {
                "kc_id": kc_id,
                "baseline_status": str(baseline_row.get("authoritative_definition_status") or ""),
                "regressed_in_all_candidates": regressed_in_all,
                "candidate_records": candidate_records,
            }
        )

    persistent_regressions = [record for record in records if record["regressed_in_all_candidates"]]
    return {
        "generated_at_utc": now_utc_iso(),
        "baseline_run_id": baseline_snapshot["run_id"],
        "candidate_run_ids": candidate_run_ids,
        "target_kc_ids": list(kc_ids),
        "persistent_regression_count": len(persistent_regressions),
        "records": records,
    }


def render_untouched_definition_not_grounded_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 Untouched `definition_not_grounded` Regression Audit")
    lines.append("")
    lines.append(f"- Generated: `{payload['generated_at_utc']}`")
    lines.append(f"- Baseline run: `{payload['baseline_run_id']}`")
    lines.append(f"- Candidate run: `{payload['candidate_run_id']}`")
    lines.append(f"- Target KCs: `{payload['target_kc_ids']}`")
    lines.append(f"- Dominant collapse path summary: `{payload['dominant_collapse_path_summary']}`")
    lines.append("")
    for record in payload["records"]:
        lines.append(f"## {record['kc_id']}")
        lines.append(f"- Binding touch class: `{record['binding_touch_classification']}`")
        lines.append(f"- Binding repair state: `{record['candidate_binding_repair_state']}`")
        lines.append(f"- Candidate pool changed: `{record['candidate_pool_changed']}`")
        lines.append(f"- Preservation result changed: `{record['preservation_result_changed']}`")
        lines.append(f"- Verification result changed: `{record['verification_result_changed']}`")
        lines.append(f"- Later control logic changed: `{record['later_control_logic_changed']}`")
        lines.append(f"- Diagnostics masking real step: `{record['diagnostics_masking_real_step']}`")
        lines.append(f"- Dominant collapse path: `{record['dominant_collapse_path']}`")
        lines.append(f"- Dominant basis: `{record['dominant_collapse_basis']}`")
        lines.append(f"- Baseline selection reason: `{record['baseline_selection_reason']}`")
        lines.append(f"- Candidate selection reason: `{record['candidate_selection_reason']}`")
        lines.append(f"- Baseline verify status/reason: `{record['baseline_verify_status']}` / `{record['baseline_verify_reason']}`")
        lines.append(
            f"- Candidate preservation verify status/reason: `{record['candidate_preservation_verify_status']}` / `{record['candidate_preservation_verify_reason']}`"
        )
        lines.append(
            f"- Candidate definition redraft verify status/reason: `{record['candidate_definition_redraft_verify_status']}` / `{record['candidate_definition_redraft_verify_reason']}`"
        )
        lines.append(
            f"- Candidate pool added ids: `{record['candidate_pool_added_ids']}`; removed ids: `{record['candidate_pool_removed_ids']}`"
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def render_definition_not_grounded_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 `definition_not_grounded` Audit")
    lines.append("")
    lines.append(f"- Generated: `{payload['generated_at_utc']}`")
    lines.append(f"- Candidate run: `{payload['candidate_run_id']}`")
    lines.append(f"- Definition-not-grounded cases: `{payload['definition_not_grounded_case_count']}`")
    lines.append(f"- Subbucket summary: `{payload['definition_not_grounded_subbucket_summary']}`")
    lines.append(f"- Direct basis counts: `{payload['direct_basis_counts']}`")
    lines.append("")
    lines.append("## Direct Stage Counts")
    for key in sorted(payload["direct_stage_counts"]):
        lines.append(f"- `{key}` = `{payload['direct_stage_counts'][key]}`")
    lines.append("")
    lines.append("## Example Records")
    for record in payload["records"][:10]:
        grounding = record["grounding_diagnostics"]
        lines.append(f"### {record['kc_id']}")
        lines.append(f"- Subbucket: `{record['definition_not_grounded_subbucket']}`")
        lines.append(f"- Collapse stage: `{grounding['collapse_stage']}`")
        lines.append(
            f"- Preservation draft/verify: `{grounding['preservation_draft_status']}` / `{grounding['preservation_verify_status']}`"
        )
        lines.append(f"- Rescue used: `{grounding['rescue_used']}`")
        lines.append(
            f"- Rescue draft/verify: `{grounding['rescue_draft_status']}` / `{grounding['rescue_verify_status']}`"
        )
        lines.append(
            f"- Redraft/verify: `{grounding['definition_redraft_status']}` / `{grounding['definition_redraft_verify_status']}`"
        )
        lines.append(
            f"- Control fallback candidate present/applied: `{grounding['control_fallback_candidate_present']}` / `{grounding['control_fallback_applied']}`"
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def render_persistent_regressions_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Step 6.7 Persistent Regression Audit")
    lines.append("")
    lines.append(f"- Generated: `{payload['generated_at_utc']}`")
    lines.append(f"- Baseline run: `{payload['baseline_run_id']}`")
    lines.append(f"- Candidate runs: `{payload['candidate_run_ids']}`")
    lines.append(f"- Persistent regression count: `{payload['persistent_regression_count']}`")
    lines.append("")
    for record in payload["records"]:
        lines.append(f"## {record['kc_id']}")
        lines.append(f"- Baseline status: `{record['baseline_status']}`")
        lines.append(f"- Regressed in all candidates: `{record['regressed_in_all_candidates']}`")
        for candidate in record["candidate_records"]:
            lines.append(f"- `{candidate['candidate_run_id']}` -> `{candidate['candidate_status']}`")
            lines.append(f"  collapse_stage=`{candidate['collapse_stage']}`")
            lines.append(f"  binding=`{candidate['binding_repair_state']}` / `{candidate['binding_repair_reason']}`")
            lines.append(f"  selection_reason=`{candidate['final_selection_reason']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
