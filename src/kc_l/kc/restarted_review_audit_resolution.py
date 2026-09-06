from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kc_l.kc.restarted_review_audits import validate_scope_aware_review_audit_event
from kc_l.utils.json_io import read_jsonl, write_json, write_jsonl


RESTARTED_REVIEW_AUDIT_RESOLUTION_STAGE = "step6_10_restarted_review_audit_resolution"
RESTARTED_REVIEW_AUDIT_RESOLUTION_RULE_VERSION = "step6.10.restarted_review_audit_resolution.v1"
RESTARTED_FINAL_TEXT_CAPTURE_MODE = "bounded_restarted_final_text_capture"
EDIT_PENDING_STATUS = "edit_pending"
EDITED_APPROVED_STATUS = "edited_approved"
FINALIZED_RESOLUTION_STATUS = "finalized"
APPROVED_STATUS = "approved"

FINAL_TEXT_CAPTURE_PLAN: dict[str, dict[str, Any]] = {
    "KC_CLF_DT_001": {
        "definition": "A very old, simple tree induction algorithm.",
        "scope": "Used for learning bushy and binary classifiers.",
        "definition_evidence_ids": [
            "KC_CLF_DT_001:overlay:0feb01769302c3a4",
            "KC_CLF_DT_001:overlay:78365f14ddef0783",
        ],
        "scope_evidence_ids": [
            "KC_CLF_DT_001:overlay:0feb01769302c3a4",
            "KC_CLF_DT_001:overlay:78365f14ddef0783",
        ],
        "resolution_note": "Normalized the slide-bullet cluster into a concise definition and use-context sentence from the existing packet evidence.",
    },
    "KC_CLF_DT_003": {
        "scope": "Used to minimize impurity with respect to the target variable.",
        "scope_evidence_ids": [
            "KC_CLF_DT_003:overlay:1ad6165beb9315a0",
            "KC_CLF_DT_003:overlay:d5e053ed5ffbce55",
        ],
        "resolution_note": "Filled the previously blank scope from the packet's impurity-minimization support rather than inventing a new surface.",
    },
    "KC_CLF_DT_004": {
        "definition": "The Gini index at a node is 1 minus the sum of squared class probabilities.",
        "scope": None,
        "definition_evidence_ids": ["KC_CLF_DT_004:overlay:f3ec44ae27b28843"],
        "scope_evidence_ids": [],
        "resolution_note": "Converted the formula-first definition into a readable sentence, but kept scope blank because the bounded packet surface still does not provide a clean scope quote beyond the preserved weak-coverage caution.",
    },
    "KC_CLF_DT_006": {
        "definition": "Information gain is the difference between the prior uncertainty and the expected posterior uncertainty using a feature.",
        "definition_evidence_ids": [
            "KC_CLF_DT_006:overlay:762aa51a388e6994",
            "KC_CLF_DT_006:overlay:946f825fbf3c0793",
        ],
        "resolution_note": "Replaced the formula lead-in with the packet's explanatory uncertainty-difference sentence.",
    },
    "KC_CLF_DT_008": {
        "definition": "Gain ratio is information gain divided by intrinsic information.",
        "scope": "Used to evaluate a candidate split of a node into children.",
        "definition_evidence_ids": ["KC_CLF_DT_008:overlay:e9c8bd4deb1d1443"],
        "scope_evidence_ids": ["KC_CLF_DT_008:overlay:9b50f9a41c43e0f5"],
        "resolution_note": "Normalized both the formula surface and the split-context line into short reviewer-final text while staying inside the packet evidence.",
    },
    "KC_CLF_NB_004": {
        "definition": "It is assumed that p(E|H) equals the product of p(E_i|H) over the attributes.",
        "scope": "All attributes contribute equally to the class prediction.",
        "definition_evidence_ids": [
            "KC_CLF_NB_004:overlay:9519aa1ed5b279d3",
            "KC_CLF_NB_004:overlay:068cdaf56ab951a4",
        ],
        "scope_evidence_ids": [
            "KC_CLF_NB_004:overlay:4dffd324dc686fcd",
            "KC_CLF_NB_004:overlay:94fd1de5a740bce6",
        ],
        "resolution_note": "Separated the packet's predictive-scope sentence from the probability-factorization statement so the final surface is cleaner and field-specific.",
    },
    "KC_CLF_UND_001": {
        "definition": "The set D is used for learning, that is, for training.",
        "definition_evidence_ids": [
            "KC_CLF_UND_001:overlay:c7887669f76e2221",
            "KC_CLF_UND_001:overlay:7b160206a6219354",
        ],
        "resolution_note": "Shortened the definition to the grounded training-phase statement and left the broader classifier-build note in scope/context.",
    },
    "KC_CLF_UND_003": {
        "definition": "We split D into a training set D_train and a test set D_test.",
        "scope": "Used to separate model induction from testing and evaluation.",
        "definition_evidence_ids": [
            "KC_CLF_UND_003:overlay:246e951cf78be296",
        ],
        "scope_evidence_ids": [
            "KC_CLF_UND_003:overlay:f07dbd8d4c8562f3",
            "KC_CLF_UND_003:overlay:ccdfdbe11ad2a404",
        ],
        "resolution_note": "Replaced the noisy induction/deduction wording with a concise train/test split statement grounded in the packet evidence.",
    },
    "KC_CLF_UND_004": {
        "definition": "The training set D must be representative of the population under study.",
        "definition_evidence_ids": [
            "KC_CLF_UND_004:overlay:f28af3ae1b7aef93",
            "KC_CLF_UND_004:overlay:513bebd0e894bf37",
        ],
        "resolution_note": "Tightened the over-extended packet definition to the representative-sample requirement already present in the packet evidence.",
    },
    "KC_CLF_UND_005": {
        "definition": "Classification takes as input a set of mutually exclusive classes, each with a set of instances belonging to it.",
        "scope": None,
        "definition_evidence_ids": [
            "KC_CLF_UND_005:overlay:7f601cec5e889043",
            "KC_CLF_UND_005:overlay:1c52f8fb6c3e9d2e",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Trimmed away the appended training-phase text and kept scope blank because the packet never surfaced a clean use-context line beyond the core mutually-exclusive-classes statement.",
    },
    "KC_CLF_NB_006": {
        "definition": "For each label y in L, assign x the label with the highest probability.",
        "scope": None,
        "definition_evidence_ids": [
            "KC_CLF_NB_006:overlay:e6ee918e6e8b3b2f",
            "KC_CLF_NB_006:overlay:a318ea1f6157848d",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Reduced the bullet-heavy packet surface to the grounded highest-probability assignment clause and dropped the noisy duplicated scope line.",
    },
    "KC_EVAL_ENS_004": {
        "definition": "In boosting, the weights of the records misclassified by classifier zeta_i are increased to train classifier zeta_{i+1}.",
        "scope": None,
        "definition_evidence_ids": [
            "KC_EVAL_ENS_004:overlay:e07d90770014d714",
            "KC_EVAL_ENS_004:overlay:e821610f6f857f99",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Dropped the Random Forest contamination and kept the grounded boosting update rule, while preserving the missing scope as intentionally blank because the packet did not expose a clean separate use-context line.",
    },
    "KC_EVAL_SAMP_004": {
        "definition": "Leave-one-out cross validation is k-fold cross validation over the learning set D with k = |D|.",
        "scope": None,
        "definition_evidence_ids": [
            "KC_EVAL_SAMP_004:overlay:01410bd46df97972",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Replaced the stray error-rate fragment with the grounded leave-one-out clue and kept scope intentionally blank because the packet never surfaced a separate scope line beyond that definition cue.",
    },
    "KC_EVAL_SAMP_002": {
        "definition": "Random subsampling invokes the holdout method k times.",
        "scope": "The overall performance is the average of the performance values over the k invocations.",
        "definition_evidence_ids": [
            "KC_EVAL_SAMP_002:overlay:889d99d6fca7ac39",
        ],
        "scope_evidence_ids": [
            "KC_EVAL_SAMP_002:overlay:889d99d6fca7ac39",
        ],
        "resolution_note": "Replaced the unrelated test-statistic surface with the repeated-holdout statement already present in the packet evidence.",
    },
    "KC_CLF_NB_008": {
        "definition": "The Laplace estimator uses a small weight w > 0, where n_a is the number of distinct values that attribute a can take.",
        "scope": "This is a generalization of the original Laplace estimator, where w = n_a.",
        "definition_evidence_ids": [
            "KC_CLF_NB_008:overlay:0d6ae3be720fa947",
        ],
        "scope_evidence_ids": [
            "KC_CLF_NB_008:overlay:7ccace30c9861dca",
            "KC_CLF_NB_008:overlay:94c1ea4ddc96f371",
        ],
        "resolution_note": "Turned the trailing where-clause into a readable Laplace-estimator statement and separated the generalization note into scope/context.",
    },
    "KC_CLF_NB_011": {
        "definition": "Handling missing values in NB considers an instance x of unknown label for which the value of x for some attribute a is missing.",
        "definition_evidence_ids": [
            "KC_CLF_NB_011:overlay:dc114eb8db323d8a",
        ],
        "resolution_note": "Kept only the grounded missing-attribute statement and left the already-grounded packet scope intact.",
    },
    "KC_EVAL_BASIC_002": {
        "definition": "Accuracy is the fraction of correctly classified instances.",
        "scope": "For binary classification, accuracy = (f11 + f00) / (f11 + f10 + f01 + f00).",
        "definition_evidence_ids": [
            "KC_EVAL_BASIC_002:overlay:977aeb2fdb1d1931",
            "KC_EVAL_BASIC_002:overlay:484ca8b17157ccac",
        ],
        "scope_evidence_ids": [
            "KC_EVAL_BASIC_002:overlay:977aeb2fdb1d1931",
            "KC_EVAL_BASIC_002:overlay:484ca8b17157ccac",
        ],
        "resolution_note": "Discarded the unrelated F-measure caveat and rewrote the packet's accuracy formulas into a short definition plus binary-case scope line.",
    },
    "KC_EVAL_BASIC_004": {
        "definition": "Recall, or sensitivity, is f11 / (f11 + f10).",
        "scope": None,
        "definition_evidence_ids": [
            "KC_EVAL_BASIC_004:overlay:9804b604bc48a8c7",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Converted the paired metric row into a target-only Recall/Sensitivity formula and kept scope intentionally blank because the remaining packet scope spans were unrelated background.",
    },
    "KC_EVAL_BASIC_005": {
        "definition": "Specificity is f00 / (f00 + f01).",
        "scope": None,
        "definition_evidence_ids": [
            "KC_EVAL_BASIC_005:overlay:f1edf44798b04603",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Converted the paired metric row into a target-only Specificity formula and kept scope intentionally blank because the packet did not surface a clean target-specific scope line.",
    },
    "KC_EVAL_ENS_001": {
        "definition": "There are many ways of building a single or ensemble classifier.",
        "definition_evidence_ids": [
            "KC_EVAL_ENS_001:overlay:a32ade9ce49a78f3",
        ],
        "resolution_note": "Tightened the packet to the only ensemble-specific sentence it actually exposed and left the grounded classifier-building scope unchanged.",
    },
    "KC_EVAL_ENS_002": {
        "definition": "Majority voting bases the ensemble decision on the votes of the ensemble members.",
        "scope": "The quality of the ensemble is computed on the basis of the collective decisions for the records of the test set.",
        "definition_evidence_ids": [
            "KC_EVAL_ENS_002:overlay:5241298e1c4a5c2d",
        ],
        "scope_evidence_ids": [
            "KC_EVAL_ENS_002:overlay:5241298e1c4a5c2d",
        ],
        "resolution_note": "Normalized the duplicated majority-voting packet sentence into a concise ensemble-decision definition plus the grounded test-set evaluation scope line.",
    },
    "KC_EVAL_ENS_003": {
        "definition": "Random forest is an ensemble composed of m decision trees.",
        "scope": None,
        "definition_evidence_ids": [
            "KC_EVAL_ENS_003:overlay:c6840f981605d842",
            "KC_EVAL_ENS_003:overlay:fa0ee36d3244e19f",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Kept the recovered target-only Random Forest clause and preserved scope as intentionally blank because the packet still does not expose a clean separate use-context line.",
    },
    "KC_EVAL_IMBAL_001": {
        "definition": "The class imbalance problem concerns classes that are more rare than others and may have different costs of class misattribution.",
        "definition_evidence_ids": [
            "KC_EVAL_IMBAL_001:overlay:5abc924a5efd2639",
            "KC_EVAL_IMBAL_001:overlay:0ef4da00fcaf6ba4",
            "KC_EVAL_IMBAL_001:overlay:50baa1594bcdc438",
        ],
        "resolution_note": "Replaced the course-outline fragment with the packet's actual rare-class and misattribution-cost content while keeping the existing grounded scope sentence.",
    },
    "KC_EVAL_SAMP_001": {
        "definition": "The holdout method splits D into a training set D_train for model induction and a test set D_test for evaluation.",
        "scope": "Used to separate training from testing and evaluation.",
        "definition_evidence_ids": [
            "KC_EVAL_SAMP_001:overlay:cdc1b93d89011ace",
        ],
        "scope_evidence_ids": [
            "KC_EVAL_SAMP_001:overlay:cdc1b93d89011ace",
        ],
        "resolution_note": "Normalized the noisy holdout train/test split sentence into a concise definition and scope statement while staying inside the packet evidence.",
    },
    "KC_EVAL_SAMP_003": {
        "definition": "In k-fold cross validation, use the k-1 folds union_{j!=i} D_j for training and the fold D_i for testing.",
        "scope": "Aggregate the error values or performance values over all k tests.",
        "definition_evidence_ids": [
            "KC_EVAL_SAMP_003:overlay:c03dedad9c6b677c",
            "KC_EVAL_SAMP_003:overlay:6e7514fd6061004f",
        ],
        "scope_evidence_ids": [
            "KC_EVAL_SAMP_003:overlay:c03dedad9c6b677c",
            "KC_EVAL_SAMP_003:overlay:6e7514fd6061004f",
        ],
        "resolution_note": "Split the packet's bullet cluster into the grounded train/test procedure and the grounded aggregation scope line.",
    },
    "KC_EVAL_BASIC_006": {
        "definition": "F-measure combines precision and recall.",
        "scope": "A generalization is F_beta = ((1 + beta^2) f11) / ((1 + beta^2) f11 + beta^2 f10 + f01).",
        "definition_evidence_ids": [
            "KC_EVAL_BASIC_006:overlay:0f2f0de43daad8de",
        ],
        "scope_evidence_ids": [
            "KC_EVAL_BASIC_006:overlay:0f2f0de43daad8de",
        ],
        "resolution_note": "Replaced the worked numeric example and slide-note debris with the packet's explicit precision/recall and F_beta formula support.",
    },
    "KC_EVAL_SAMP_005": {
        "definition": "Bootstrap sampling builds training and test samples by sampling with replacement.",
        "scope": None,
        "definition_evidence_ids": [
            "KC_EVAL_SAMP_005:overlay:2446f0f0c261d8b5",
            "KC_EVAL_SAMP_005:overlay:e38ea2ca3ee7c301",
        ],
        "scope_evidence_ids": [],
        "resolution_note": "Recovered the sampling-with-replacement idea from the packet evidence and kept scope intentionally blank because the remaining scope surface stayed as a broad course-outline fragment.",
    },
}


@dataclass(frozen=True)
class RestartedReviewAuditResolutionResult:
    output_dir: Path
    resolved_audit_jsonl_path: Path
    summary_path: Path
    preview_path: Path
    event_count: int


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _union_ids(*groups: Sequence[Any]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for value in group or []:
            text = _as_text(value)
            if text and text not in out:
                out.append(text)
    return out


def _packet_lookup(source_review_packet_jsonl: Path) -> dict[str, dict[str, Any]]:
    packets = read_jsonl(source_review_packet_jsonl)
    return {_as_text(packet.get("kc_candidate_id")): dict(packet) for packet in packets}


def _resolved_note(existing_note: str, resolution_note: str) -> str:
    base = existing_note.strip()
    extra = f" Final text captured from restarted packet surface via {RESTARTED_FINAL_TEXT_CAPTURE_MODE}. {resolution_note}".strip()
    if not base:
        return extra
    return f"{base} {extra}".strip()


def resolve_edit_pending_event(*, event: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]:
    kc_id = _as_text(event.get("kc_candidate_id"))
    plan = FINAL_TEXT_CAPTURE_PLAN.get(kc_id)
    _ensure(_as_text(event.get("action_taken")) == "edit", f"Resolution expected edit action for {kc_id}")
    _ensure(_as_text(event.get("final_status")) == EDIT_PENDING_STATUS, f"Resolution expected edit_pending status for {kc_id}")

    edited_fields = _normalize_string_list(event.get("edited_fields"))
    current_packet_text = dict(event.get("current_packet_text") or {})
    final_text = dict(event.get("final_text") or {})
    field_linked = {
        "definition": _normalize_string_list((event.get("field_linked_evidence_ids") or {}).get("definition")),
        "scope": _normalize_string_list((event.get("field_linked_evidence_ids") or {}).get("scope")),
    }
    if plan is None:
        plan = {
            "definition": current_packet_text.get("definition"),
            "scope": current_packet_text.get("scope"),
            "definition_evidence_ids": list(field_linked["definition"]),
            "scope_evidence_ids": list(field_linked["scope"]),
            "resolution_note": "No dedicated final-text capture plan was configured; finalized from the existing restarted packet surface without inventing new text.",
        }

    if "definition" in edited_fields:
        final_text["definition"] = plan.get("definition")
        field_linked["definition"] = _normalize_string_list(plan.get("definition_evidence_ids"))
    if "scope" in edited_fields:
        final_text["scope"] = plan.get("scope")
        field_linked["scope"] = _normalize_string_list(plan.get("scope_evidence_ids"))

    for field in ("title", "level", "definition", "scope"):
        if field not in final_text:
            final_text[field] = current_packet_text.get(field)

    packet_span_ids = [
        _as_text(span.get("evidence_id"))
        for span in packet.get("evidence_spans") or []
        if _as_text(span.get("evidence_id"))
    ]
    linked_evidence_ids = _union_ids(
        field_linked["definition"],
        field_linked["scope"],
        packet_span_ids,
        event.get("linked_evidence_ids") or [],
    )

    resolved = dict(event)
    resolved["final_status"] = EDITED_APPROVED_STATUS
    resolved["edit_resolution_status"] = FINALIZED_RESOLUTION_STATUS
    resolved["final_text"] = final_text
    resolved["field_linked_evidence_ids"] = field_linked
    resolved["linked_evidence_ids"] = linked_evidence_ids
    resolved["review_notes"] = _resolved_note(_as_text(event.get("review_notes")), _as_text(plan.get("resolution_note")))
    validate_scope_aware_review_audit_event(resolved)
    return resolved


def resolve_restarted_review_audits(
    *,
    source_review_audit_dir: Path,
    source_review_packet_dir: Path,
    source_review_packet_jsonl: Path,
    output_dir: Path,
) -> RestartedReviewAuditResolutionResult:
    """source_review_packet_dir is used only for display/audit-trail purposes (build_summary());
    source_review_packet_jsonl is the actual file read - callers must resolve the real filename
    themselves (it differs between the legacy and v2 Step 6.8 manifest schemas, confirmed via
    run_step6_10_kc_review_audit_resolution.py's own resolve_review_packet_manifest()) rather
    than this function guessing a fixed name within a directory, which was the confirmed bug.
    """
    source_review_audit_dir = source_review_audit_dir.resolve()
    source_review_packet_dir = source_review_packet_dir.resolve()
    source_review_packet_jsonl = source_review_packet_jsonl.resolve()
    output_dir = output_dir.resolve()

    events = read_jsonl(source_review_audit_dir / "review_audit.jsonl")
    packet_lookup = _packet_lookup(source_review_packet_jsonl)

    resolved_events: list[dict[str, Any]] = []
    for event in events:
        kc_id = _as_text(event.get("kc_candidate_id"))
        packet = packet_lookup.get(kc_id)
        _ensure(packet is not None, f"Missing source review packet for {kc_id}")
        if _as_text(event.get("action_taken")) == "edit" and _as_text(event.get("final_status")) == EDIT_PENDING_STATUS:
            resolved_events.append(resolve_edit_pending_event(event=event, packet=packet))
        else:
            validate_scope_aware_review_audit_event(event)
            resolved_events.append(dict(event))

    summary = build_summary(
        source_review_audit_dir=source_review_audit_dir,
        source_review_packet_dir=source_review_packet_dir,
        events=resolved_events,
    )
    preview = build_preview_markdown(summary=summary, events=resolved_events)

    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_audit_jsonl_path = output_dir / "review_audit_resolved.jsonl"
    summary_path = output_dir / "review_audit_resolution_summary.json"
    preview_path = output_dir / "review_audit_resolution_preview.md"
    write_jsonl(resolved_audit_jsonl_path, resolved_events)
    write_json(summary_path, summary)
    preview_path.write_text(preview, encoding="utf-8")

    return RestartedReviewAuditResolutionResult(
        output_dir=output_dir,
        resolved_audit_jsonl_path=resolved_audit_jsonl_path,
        summary_path=summary_path,
        preview_path=preview_path,
        event_count=len(resolved_events),
    )


def build_summary(
    *,
    source_review_audit_dir: Path,
    source_review_packet_dir: Path,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    action_counts = Counter(_as_text(event.get("action_taken")) for event in events)
    final_status_counts = Counter(_as_text(event.get("final_status")) for event in events)
    resolution_counts = Counter(_as_text(event.get("edit_resolution_status")) for event in events)
    approved_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == APPROVED_STATUS]
    edited_approved_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == EDITED_APPROVED_STATUS]
    rejected_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == "rejected"]
    unresolved_edit_kcs = [event["kc_candidate_id"] for event in events if _as_text(event.get("final_status")) == EDIT_PENDING_STATUS]
    intentionally_blank_final_fields: list[str] = []
    for event in events:
        final_text = dict(event.get("final_text") or {})
        if _as_text(event.get("final_status")) != EDITED_APPROVED_STATUS:
            continue
        for field in _normalize_string_list(event.get("edited_fields")):
            if field in {"definition", "scope"} and final_text.get(field) is None:
                intentionally_blank_final_fields.append(f"{event['kc_candidate_id']}.{field}")
    return {
        "schema_version": "1.0",
        "stage": RESTARTED_REVIEW_AUDIT_RESOLUTION_STAGE,
        "rule_version": RESTARTED_REVIEW_AUDIT_RESOLUTION_RULE_VERSION,
        "final_text_capture_mode": RESTARTED_FINAL_TEXT_CAPTURE_MODE,
        "source_review_audit_dir": str(source_review_audit_dir),
        "source_review_packet_dir": str(source_review_packet_dir),
        "event_count": len(events),
        "action_counts": dict(action_counts),
        "final_status_counts": dict(final_status_counts),
        "edit_resolution_status_counts": dict(resolution_counts),
        "approved_count": len(approved_kcs),
        "edited_approved_count": len(edited_approved_kcs),
        "rejected_count": len(rejected_kcs),
        "approved_kcs": approved_kcs,
        "edited_approved_kcs": edited_approved_kcs,
        "rejected_kcs": rejected_kcs,
        "unresolved_edit_kcs": unresolved_edit_kcs,
        "intentionally_blank_final_fields": intentionally_blank_final_fields,
        "no_frozen_library_assembly": True,
    }


def build_preview_markdown(*, summary: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Restarted Review Audit Resolution Preview",
        "",
        f"- Source review-audit dir: `{summary['source_review_audit_dir']}`",
        f"- Source review-packet dir: `{summary['source_review_packet_dir']}`",
        f"- Event count: `{summary['event_count']}`",
        f"- Action counts: `{summary['action_counts']}`",
        f"- Final status counts: `{summary['final_status_counts']}`",
        f"- Edit-resolution counts: `{summary['edit_resolution_status_counts']}`",
        f"- Approved count: `{summary['approved_count']}`",
        f"- Edited-approved count: `{summary['edited_approved_count']}`",
        f"- Rejected count: `{summary['rejected_count']}`",
        f"- Approved KCs: `{summary['approved_kcs']}`",
        f"- Edited-approved KCs: `{summary['edited_approved_kcs']}`",
        f"- Rejected KCs: `{summary['rejected_kcs']}`",
        f"- Unresolved edit KCs: `{summary['unresolved_edit_kcs']}`",
        f"- Intentionally blank final fields: `{summary['intentionally_blank_final_fields']}`",
        "",
        "## Resolved Events",
        "",
    ]
    for event in events:
        lines.extend(
            [
                f"### {event['kc_candidate_id']} - {event['final_status']}",
                "",
                f"- Edited fields: `{event['edited_fields']}`",
                f"- Current packet text: `{event['current_packet_text']}`",
                f"- Final text: `{event['final_text']}`",
                f"- Field-linked evidence ids: `{event['field_linked_evidence_ids']}`",
                f"- Review note: {event.get('review_notes', '')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"

