from __future__ import annotations

from typing import Any


DRAFT_CONTRACT_VERSION = "1.0"
HEURISTIC_DRAFTING_MODE = "heuristic_extract_grounded_v1"
STEP67_RUNTIME_CONTRACT_VERSION = "step6_7_authoritative_runtime_v1"
STEP67_SEMANTIC_CONTRACT_VERSION = "step6_7_survival_semantics_v1"

EXECUTION_MODE_LLM = "llm"
EXECUTION_MODE_HEURISTIC = "heuristic"

SURVIVAL_FLOOR_STATUS_SEED = "seed_definition_floor"
SURVIVAL_FLOOR_STATUS_NAME_ONLY = "canonical_name_floor"

ENRICHMENT_LAYER_STATUS_GROUNDED = "grounded"
ENRICHMENT_LAYER_STATUS_MISSING = "missing"

CONTEXT_LAYER_STATUS_GROUNDED = "grounded"
CONTEXT_LAYER_STATUS_FALLBACK = "fallback_context"
CONTEXT_LAYER_STATUS_MISSING = "missing"

SCOPE_LAYER_STATUS_GROUNDED = "grounded"
SCOPE_LAYER_STATUS_ABSTAINED = "abstained"

TRUST_STATE_GROUNDED = "grounded"
TRUST_STATE_GROUNDED_WITH_GAPS = "grounded_with_gaps"
TRUST_STATE_FALLBACK_SEED = "fallback_seed_floor"
TRUST_STATE_FALLBACK_SEED_WITH_RISKS = "fallback_seed_floor_with_risks"

REVIEW_READINESS_READY = "ready"
REVIEW_READINESS_NEEDS_ATTENTION = "needs_attention"
REVIEW_READINESS_LOW_TRUST = "low_trust"

AUTHORITATIVE_DEFINITION_STATUS_DIRECT_GROUNDED = "direct_grounded"
AUTHORITATIVE_DEFINITION_STATUS_NORMALIZED_GROUNDED = "normalized_grounded"
AUTHORITATIVE_DEFINITION_STATUS_SEED_FLOOR_FALLBACK = "seed_floor_fallback"


def as_text(value: Any) -> str:
    return str(value or "").strip()


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = as_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def looks_unresolved(value: Any) -> bool:
    return as_text(value).startswith("UNRESOLVED_")


def builder_function_name(execution_mode: Any) -> str:
    if as_text(execution_mode).lower() == EXECUTION_MODE_LLM:
        return "build_kc_draft_bundles_llm"
    return "build_kc_draft_bundles"


def compatibility_draft_status(review_readiness_label: Any) -> str:
    if as_text(review_readiness_label) == REVIEW_READINESS_READY:
        return "draft_ready"
    return "draft_ready_with_holds"
