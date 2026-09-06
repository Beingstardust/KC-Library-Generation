from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping


REVIEW_PACKET_SCHEMA_VERSION = "step6.review_packet.v1"
REVIEW_AUDIT_SCHEMA_VERSION = "step6.review_audit.v2"
REVIEW_PRIORITY_RULE_VERSION = "step6.review_priority.v1"

REVIEW_PACKET_SCHEMA_PATH = Path(__file__).with_name("schemas") / "review_packet.schema.json"
REVIEW_AUDIT_SCHEMA_PATH = Path(__file__).with_name("schemas") / "review_audit.schema.json"

REVIEW_PRIORITY_BUCKET_LABELS = {
    "high_support": "High support",
    "moderate_support": "Moderate support",
    "needs_review": "Needs review",
    "low_support": "Low support",
}
SYSTEM_RECOMMENDATION_LABELS = ("approve_ready", "review_needed", "reject_recommended")

CURRENT_REQUIRED_PRIORITY_FEATURES = (
    "semantic_tier",
    "definition_status",
    "accepted_quote_count",
    "evidence_span_count",
    "definition_short_contract_ok",
    "support_contract_downgraded",
    "contamination_category",
    "sibling_ambiguity",
)
FUTURE_CAPABLE_PRIORITY_FEATURES = (
    "operational_support_present",
    "proposal_route_agreement",
    "overlap_risk",
    "underspecified_wording_risk",
    "overbroadness_risk",
    "novelty_against_frozen_library",
)

DEFINITION_STATUS_VALUES = {"coherent_supported", "fragmentary_supported", "unsupported_in_source", "unknown"}
CONTAMINATION_CATEGORY_VALUES = {"clean", "hard_contamination", "unknown"}
PROPOSAL_ROUTE_AGREEMENT_VALUES = {"strong", "mixed", "conflicting"}
RISK_LEVEL_VALUES = {"low", "medium", "high"}
NOVELTY_VALUES = {"novel", "adjacent", "near_duplicate"}


def _load_json_schema(path: Path) -> Dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected JSON object schema at {path}")
    return obj


def load_review_packet_schema() -> Dict[str, Any]:
    return _load_json_schema(REVIEW_PACKET_SCHEMA_PATH)


def load_review_audit_schema() -> Dict[str, Any]:
    return _load_json_schema(REVIEW_AUDIT_SCHEMA_PATH)


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _normalized_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _normalized_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
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


def _normalized_enum(value: Any, allowed: set[str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if text in allowed else None


def normalize_priority_features(features: Mapping[str, Any]) -> Dict[str, Any]:
    semantic_tier = _normalized_int(features.get("semantic_tier"))
    if semantic_tier is not None and semantic_tier not in {0, 1, 2}:
        semantic_tier = None

    accepted_quote_count = _normalized_int(features.get("accepted_quote_count"))
    if accepted_quote_count is not None and accepted_quote_count < 0:
        accepted_quote_count = None

    evidence_span_count = _normalized_int(features.get("evidence_span_count"))
    if evidence_span_count is not None and evidence_span_count < 0:
        evidence_span_count = None

    return {
        "semantic_tier": semantic_tier,
        "definition_status": _normalized_enum(features.get("definition_status"), DEFINITION_STATUS_VALUES),
        "accepted_quote_count": accepted_quote_count,
        "evidence_span_count": evidence_span_count,
        "definition_short_contract_ok": _normalized_bool(features.get("definition_short_contract_ok")),
        "support_contract_downgraded": _normalized_bool(features.get("support_contract_downgraded")),
        "contamination_category": _normalized_enum(features.get("contamination_category"), CONTAMINATION_CATEGORY_VALUES),
        "sibling_ambiguity": _normalized_bool(features.get("sibling_ambiguity")),
        "operational_support_present": _normalized_bool(features.get("operational_support_present")),
        "proposal_route_agreement": _normalized_enum(
            features.get("proposal_route_agreement"), PROPOSAL_ROUTE_AGREEMENT_VALUES
        ),
        "overlap_risk": _normalized_enum(features.get("overlap_risk"), RISK_LEVEL_VALUES),
        "underspecified_wording_risk": _normalized_enum(
            features.get("underspecified_wording_risk"), RISK_LEVEL_VALUES
        ),
        "overbroadness_risk": _normalized_enum(features.get("overbroadness_risk"), RISK_LEVEL_VALUES),
        "novelty_against_frozen_library": _normalized_enum(
            features.get("novelty_against_frozen_library"), NOVELTY_VALUES
        ),
    }


def compute_review_priority(features: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = normalize_priority_features(features)
    reason_codes: list[str] = []
    missing_feature_keys: list[str] = []
    blocking_reason_codes: list[str] = []
    score = 0

    for key in CURRENT_REQUIRED_PRIORITY_FEATURES:
        if normalized.get(key) is None:
            missing_feature_keys.append(key)
            _append_unique(reason_codes, f"missing_current_feature:{key}")
    for key in FUTURE_CAPABLE_PRIORITY_FEATURES:
        if normalized.get(key) is None:
            missing_feature_keys.append(key)

    semantic_tier = normalized["semantic_tier"]
    if semantic_tier == 2:
        score += 2
        _append_unique(reason_codes, "semantic_tier:2")
    elif semantic_tier == 1:
        score += 1
        _append_unique(reason_codes, "semantic_tier:1")
    elif semantic_tier == 0:
        _append_unique(reason_codes, "semantic_tier:0")

    definition_status = normalized["definition_status"]
    if definition_status == "coherent_supported":
        score += 2
        _append_unique(reason_codes, "definition_status:coherent_supported")
    elif definition_status == "fragmentary_supported":
        score += 1
        _append_unique(reason_codes, "definition_status:fragmentary_supported")
    elif definition_status == "unsupported_in_source":
        score -= 2
        _append_unique(reason_codes, "definition_status:unsupported_in_source")
    elif definition_status == "unknown":
        _append_unique(reason_codes, "definition_status:unknown")

    accepted_quote_count = normalized["accepted_quote_count"]
    if accepted_quote_count is not None:
        if accepted_quote_count >= 2:
            score += 1
            _append_unique(reason_codes, "accepted_quotes:2_plus")
        elif accepted_quote_count == 0:
            score -= 2
            _append_unique(reason_codes, "accepted_quotes:0")
        else:
            _append_unique(reason_codes, "accepted_quotes:1")

    evidence_span_count = normalized["evidence_span_count"]
    if evidence_span_count is not None:
        if evidence_span_count >= 2:
            score += 1
            _append_unique(reason_codes, "evidence_spans:2_plus")
        elif evidence_span_count == 0:
            score -= 2
            _append_unique(reason_codes, "evidence_spans:0")
        else:
            _append_unique(reason_codes, "evidence_spans:1")

    if normalized["definition_short_contract_ok"] is False:
        _append_unique(blocking_reason_codes, "definition_short_contract_fail")
    if normalized["support_contract_downgraded"] is True:
        _append_unique(blocking_reason_codes, "support_contract_downgraded")
    if normalized["contamination_category"] == "hard_contamination":
        _append_unique(blocking_reason_codes, "hard_contamination")
    elif normalized["contamination_category"] == "clean":
        _append_unique(reason_codes, "contamination_category:clean")

    if normalized["sibling_ambiguity"] is True:
        score -= 1
        _append_unique(reason_codes, "sibling_ambiguity:true")

    if normalized["operational_support_present"] is True:
        score += 1
        _append_unique(reason_codes, "operational_support:true")

    proposal_route_agreement = normalized["proposal_route_agreement"]
    if proposal_route_agreement == "strong":
        score += 1
        _append_unique(reason_codes, "proposal_route_agreement:strong")
    elif proposal_route_agreement == "conflicting":
        score -= 1
        _append_unique(reason_codes, "proposal_route_agreement:conflicting")

    overlap_risk = normalized["overlap_risk"]
    if overlap_risk == "high":
        score -= 2
        _append_unique(reason_codes, "overlap_risk:high")
    elif overlap_risk == "medium":
        score -= 1
        _append_unique(reason_codes, "overlap_risk:medium")

    if normalized["underspecified_wording_risk"] == "high":
        score -= 1
        _append_unique(reason_codes, "underspecified_wording_risk:high")

    if normalized["overbroadness_risk"] == "high":
        score -= 1
        _append_unique(reason_codes, "overbroadness_risk:high")

    if normalized["novelty_against_frozen_library"] == "near_duplicate":
        score -= 2
        _append_unique(reason_codes, "novelty_against_frozen_library:near_duplicate")

    if blocking_reason_codes:
        bucket = "low_support"
    elif score >= 6:
        bucket = "high_support"
    elif score >= 4:
        bucket = "moderate_support"
    elif score >= 1:
        bucket = "needs_review"
    else:
        bucket = "low_support"

    if any(key in missing_feature_keys for key in CURRENT_REQUIRED_PRIORITY_FEATURES) and bucket in {
        "high_support",
        "moderate_support",
    }:
        bucket = "needs_review"
        _append_unique(reason_codes, "missing_current_features_caps_priority")

    _append_unique(reason_codes, f"priority_bucket:{bucket}")
    return {
        "bucket": bucket,
        "display_label": REVIEW_PRIORITY_BUCKET_LABELS[bucket],
        "rank_score": score,
        "reason_codes": reason_codes,
        "missing_feature_keys": missing_feature_keys,
        "blocking_reason_codes": blocking_reason_codes,
        "rule_version": REVIEW_PRIORITY_RULE_VERSION,
    }


def derive_system_recommendation(
    features: Mapping[str, Any],
    review_priority: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    priority = compute_review_priority(features) if review_priority is None else dict(review_priority)
    reason_codes: list[str] = []
    for item in priority.get("blocking_reason_codes") or []:
        _append_unique(reason_codes, str(item))

    bucket = str(priority.get("bucket") or "needs_review")
    missing_feature_keys = {str(item) for item in priority.get("missing_feature_keys") or []}
    missing_current = any(item in missing_feature_keys for item in CURRENT_REQUIRED_PRIORITY_FEATURES)

    if reason_codes or bucket == "low_support":
        if not reason_codes:
            _append_unique(reason_codes, "priority_bucket:low_support")
        label = "reject_recommended"
    elif bucket == "high_support" and not missing_current:
        label = "approve_ready"
        _append_unique(reason_codes, "priority_bucket:high_support")
    else:
        label = "review_needed"
        _append_unique(reason_codes, f"priority_bucket:{bucket}")
        if missing_current:
            _append_unique(reason_codes, "missing_current_priority_features")

    return {
        "label": label,
        "reason_codes": reason_codes,
        "rule_version": REVIEW_PRIORITY_RULE_VERSION,
    }
