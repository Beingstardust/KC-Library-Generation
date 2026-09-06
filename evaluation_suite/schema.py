"""Judge output schema and deterministic derived-score computation for the final-pipeline
evaluation suite (section 11.1 of the evaluation brief).

Targets the CURRENT, verified KC generation pipeline (see PIPELINE_ARCHITECTURE.md section 1) -
NOT the retired strong/weak-evidence authority structure authority_schema.py (this package's
sibling in evaluation_suite/) was built against. Do not reuse that module's row-building logic;
its evidence partitioning assumes a schema the current pipeline doesn't produce.

Everything the LLM judge is asked to return is validated here BEFORE any derived score is
trusted. Every derived score (evidence_relevance_precision, faithfulness ratio, draft_adequate,
categorical faithfulness) is computed in this module, deterministically, from the validated raw
judgments - never taken from the LLM's own arithmetic, per the brief's explicit requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


class JudgeSchemaError(ValueError):
    """Raised for any judge response that doesn't validate against the contract - never
    silently coerced or partially trusted."""


# ---------------------------------------------------------------------------------------------
# Raw judge response validation
# ---------------------------------------------------------------------------------------------

_REQUIRED_TOP_KEYS = {
    "kc_id", "evidence_relevance", "evidence_sufficiency", "draft_groundedness", "draft_adequacy",
}


def validate_judge_response(payload: dict[str, Any]) -> None:
    """Raises JudgeSchemaError on any structural violation. Does not mutate payload."""
    if not isinstance(payload, dict):
        raise JudgeSchemaError(f"judge response is not a JSON object: {type(payload)!r}")

    missing = _REQUIRED_TOP_KEYS - payload.keys()
    if missing:
        raise JudgeSchemaError(f"judge response missing required top-level keys: {sorted(missing)}")

    if not isinstance(payload["kc_id"], str) or not payload["kc_id"]:
        raise JudgeSchemaError("kc_id must be a non-empty string")

    _validate_evidence_relevance(payload["evidence_relevance"])
    _validate_evidence_sufficiency(payload["evidence_sufficiency"])
    _validate_draft_groundedness(payload["draft_groundedness"])
    _validate_draft_adequacy(payload["draft_adequacy"])


def _validate_evidence_relevance(block: Any) -> None:
    if not isinstance(block, dict) or "passages" not in block:
        raise JudgeSchemaError("evidence_relevance must be an object with a 'passages' list")
    passages = block["passages"]
    if not isinstance(passages, list):
        raise JudgeSchemaError("evidence_relevance.passages must be a list")
    for i, p in enumerate(passages):
        if not isinstance(p, dict):
            raise JudgeSchemaError(f"evidence_relevance.passages[{i}] is not an object")
        if "passage_id" not in p or not isinstance(p["passage_id"], str) or not p["passage_id"]:
            raise JudgeSchemaError(f"evidence_relevance.passages[{i}].passage_id missing/invalid")
        if "relevant" not in p or not isinstance(p["relevant"], bool):
            raise JudgeSchemaError(f"evidence_relevance.passages[{i}].relevant must be a bool")
        if p["relevant"] is False and not p.get("reason_if_irrelevant"):
            raise JudgeSchemaError(
                f"evidence_relevance.passages[{i}] marked irrelevant but reason_if_irrelevant is empty"
            )


def _validate_evidence_sufficiency(block: Any) -> None:
    if not isinstance(block, dict) or "sufficient" not in block:
        raise JudgeSchemaError("evidence_sufficiency must be an object with 'sufficient'")
    if not isinstance(block["sufficient"], bool):
        raise JudgeSchemaError("evidence_sufficiency.sufficient must be a bool")
    if block["sufficient"] is False and not block.get("missing_information"):
        raise JudgeSchemaError(
            "evidence_sufficiency.sufficient is False but missing_information is empty"
        )


def _validate_draft_groundedness(block: Any) -> None:
    if not isinstance(block, dict) or "claims" not in block:
        raise JudgeSchemaError("draft_groundedness must be an object with a 'claims' list")
    claims = block["claims"]
    if not isinstance(claims, list):
        raise JudgeSchemaError("draft_groundedness.claims must be a list")
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            raise JudgeSchemaError(f"draft_groundedness.claims[{i}] is not an object")
        if "claim" not in c or not isinstance(c["claim"], str) or not c["claim"].strip():
            raise JudgeSchemaError(f"draft_groundedness.claims[{i}].claim missing/empty")
        if "supported" not in c or not isinstance(c["supported"], bool):
            raise JudgeSchemaError(f"draft_groundedness.claims[{i}].supported must be a bool")
        ids = c.get("supporting_passage_ids", [])
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise JudgeSchemaError(
                f"draft_groundedness.claims[{i}].supporting_passage_ids must be a list of strings"
            )
        if c["supported"] is True and not ids:
            raise JudgeSchemaError(
                f"draft_groundedness.claims[{i}] marked supported but supporting_passage_ids is empty"
            )
    # empty_or_non_substantive_draft is an explicit escape hatch (section 4.3: "If the draft
    # contains no meaningful material claim, return NA and flag empty_or_non_substantive_draft")
    # - zero claims is only valid when that flag is set, otherwise it's a schema violation, not a
    # silently-accepted empty faithfulness computation.
    if not claims and not block.get("empty_or_non_substantive_draft"):
        raise JudgeSchemaError(
            "draft_groundedness.claims is empty but empty_or_non_substantive_draft was not set"
        )


def _validate_draft_adequacy(block: Any) -> None:
    if not isinstance(block, dict):
        raise JudgeSchemaError("draft_adequacy must be an object")
    for key in ("interpretable_definition", "captures_core_supported_content"):
        if key not in block or not isinstance(block[key], bool):
            raise JudgeSchemaError(f"draft_adequacy.{key} must be a bool")
    adequate = block["interpretable_definition"] and block["captures_core_supported_content"]
    if not adequate and not block.get("failure_reason"):
        raise JudgeSchemaError(
            "draft_adequacy is not adequate (at least one check is False) but failure_reason is empty"
        )


# ---------------------------------------------------------------------------------------------
# Deterministic derived scores - computed here in Python, never trusted from the LLM
# ---------------------------------------------------------------------------------------------

CategoricalFaithfulness = Literal["faithful", "partially_faithful", "unfaithful", "not_applicable"]


@dataclass(frozen=True)
class DerivedScores:
    kc_id: str
    evidence_relevance_precision: float | None  # None (NA) if no passages were selected
    relevant_passage_count: int
    selected_passage_count: int
    evidence_sufficient: bool
    faithfulness_ratio: float | None  # None (NA) if empty_or_non_substantive_draft
    supported_claim_count: int
    total_claim_count: int
    categorical_faithfulness: CategoricalFaithfulness
    draft_adequate: bool | None  # None if adequacy wasn't evaluated (e.g. no draft to judge)
    interpretable_definition: bool
    captures_core_supported_content: bool


def compute_derived_scores(validated_payload: dict[str, Any]) -> DerivedScores:
    """Call only after validate_judge_response() has passed. Pure function of the validated
    payload - no LLM-reported ratio/percentage field is ever read or trusted, matching the
    brief's explicit "Derived scores MUST be computed in deterministic Python" requirement.
    """
    kc_id = validated_payload["kc_id"]

    passages = validated_payload["evidence_relevance"]["passages"]
    selected_count = len(passages)
    relevant_count = sum(1 for p in passages if p["relevant"] is True)
    relevance_precision = (relevant_count / selected_count) if selected_count > 0 else None

    sufficient = validated_payload["evidence_sufficiency"]["sufficient"]

    groundedness = validated_payload["draft_groundedness"]
    claims = groundedness["claims"]
    empty_draft = bool(groundedness.get("empty_or_non_substantive_draft"))
    total_claims = len(claims)
    supported_claims = sum(1 for c in claims if c["supported"] is True)

    if empty_draft or total_claims == 0:
        faithfulness_ratio = None
        categorical = "not_applicable"
    else:
        faithfulness_ratio = supported_claims / total_claims
        if supported_claims == total_claims:
            categorical = "faithful"
        elif supported_claims == 0:
            categorical = "unfaithful"
        else:
            categorical = "partially_faithful"

    adequacy = validated_payload["draft_adequacy"]
    interpretable = adequacy["interpretable_definition"]
    captures_core = adequacy["captures_core_supported_content"]
    draft_adequate = interpretable and captures_core

    return DerivedScores(
        kc_id=kc_id,
        evidence_relevance_precision=(
            round(relevance_precision, 6) if relevance_precision is not None else None
        ),
        relevant_passage_count=relevant_count,
        selected_passage_count=selected_count,
        evidence_sufficient=sufficient,
        faithfulness_ratio=round(faithfulness_ratio, 6) if faithfulness_ratio is not None else None,
        supported_claim_count=supported_claims,
        total_claim_count=total_claims,
        categorical_faithfulness=categorical,  # type: ignore[arg-type]
        draft_adequate=draft_adequate,
        interpretable_definition=interpretable,
        captures_core_supported_content=captures_core,
    )


# ---------------------------------------------------------------------------------------------
# Judge payload construction - what the judge is allowed to SEE (identity-blinding contract)
# ---------------------------------------------------------------------------------------------

_FORBIDDEN_IDENTITY_SUBSTRINGS = (
    "qwen", "gemma", "deepseek", "command-r", "command r", "baseline", "ours", "our system",
    "proposed system", "the proposed", "control condition", "treatment condition",
)


def build_judge_payload(
    *,
    kc_id: str,
    kc_name: str,
    hierarchy_context: str,
    passages: list[dict[str, Any]],
    draft_text: str | None,
    system_behavior: Literal["drafted", "abstained"] | None = None,
) -> dict[str, Any]:
    """Builds exactly what the judge is allowed to see. Never includes drafter model, run label,
    provider, or condition identity (section 7's explicit blinding contract) - system_behavior
    is passed through only when the rubric genuinely needs to distinguish drafted-vs-abstained
    (evidence_sufficiency judging still applies to an abstained unit; draft_groundedness/adequacy
    do not, since there is no draft text to judge).
    """
    payload = {
        "kc_id": kc_id,
        "kc_name": kc_name,
        "hierarchy_context": hierarchy_context,
        "passages": [
            {"passage_id": p["passage_id"], "text": p["text"]} for p in passages
        ],
        "draft_text": draft_text,
    }
    if system_behavior is not None:
        payload["system_behavior"] = system_behavior
    _assert_no_identity_leak(payload)
    return payload


def _assert_no_identity_leak(payload: dict[str, Any]) -> None:
    """Defense in depth: even though build_judge_payload() only ever sets known-safe fields,
    scan the fully serialized payload text for forbidden identity substrings before it's ever
    sent anywhere - catches an accidental future field addition that leaks identity through
    passage text or a draft that happens to quote a model name, not just a code-review mistake.
    """
    import json

    text = json.dumps(payload).lower()
    hits = [s for s in _FORBIDDEN_IDENTITY_SUBSTRINGS if s in text]
    if hits:
        raise JudgeSchemaError(
            f"judge payload for kc_id={payload.get('kc_id')!r} contains forbidden identity "
            f"substrings {hits} - system/model identity must never reach the judge"
        )
