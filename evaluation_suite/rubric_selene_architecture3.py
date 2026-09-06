"""Third-generation Selene judge architecture ("v3" per explicit 2026-08-24 instruction),
evolving from rubric_v3.py's hardening pass (referred to here as "v2"). Kept as a SEPARATE
module so the exact code that produced the v1/v2 sentinel runs stays reproducible without
archaeology - this is a genuinely different pipeline shape (multi-call-per-criterion, a shared
KC-level requirement ledger, per-requirement call fan-out), not an in-place patch. Shared,
unchanged primitives (SYSTEM_MESSAGE, identity-leak check, evidence-id namespace check,
RubricSchemaError) are imported from rubric_v3.py, not duplicated.

Architecture, each element driven directly by a measured v2 failure:

1. ONE atomic claim decomposition per draft, computed once and FROZEN, reused for BOTH F1
   (verify claims against SYSTEM EVIDENCE) and F3 (verify the SAME claims against AUTHORITY
   CONTEXT) - guarantees F1 and F3 check identical claim units instead of two independently-
   derived decompositions that could disagree about what a "claim" even is.
2. F3 redesigned as per-claim SUPPORTED/CONTRADICTED/NOT_ESTABLISHED verification against
   authority (replacing v2's holistic PASS/FAIL+reason_code design, which is why F3 no longer
   needs the oneOf grammar trick - it never states a top-level verdict at all now). FAIL iff any
   claim is CONTRADICTED; NOT_ESTABLISHED (authority silent) is not itself a failure, matching
   this project's standing F1/F3 division of labor (unsourced != incorrect).
3. ONE frozen CORE_REQUIREMENTS ledger per KC, built from AUTHORITY CONTEXT ALONE - independent
   of which system/candidate is being judged - reused across every F4/F5 call for that KC. Each
   requirement is tagged with a TYPE (FORMULA/DEFINITION/PROCEDURE/CONDITION/DISTINCTION/
   AGGREGATION) at ledger-build time.
4. F4 and F5 evaluate each ledger requirement in its OWN separate inference call (never
   batched), against the draft (F4: PRESENT_CORRECT/MISSING/PRESENT_BUT_INCORRECT) or system
   evidence (F5: SUPPORTED/NOT_SUPPORTED/WRONG_TARGET_ONLY). Both aggregates are derived in
   Python only, across the list of per-requirement call results - the model is never asked for
   F4's or F5's own verdict.
5. FORMULA-type requirements get an ADDITIONAL, mandatory, generic comparison checklist
   (signs, coefficients, numerator/denominator, normalization, indices, operators, conditions,
   aggregation) appended to their F4/F5 prompt - a direct, KC-AGNOSTIC response to the measured
   SENT_013 failure (v2's judge accepted "a formula is present" without checking it was the
   RIGHT formula, and false-passed on F3/F4/F5 for exactly this reason). This checklist applies
   to every formula-type requirement in every KC; nothing in this module names entropy,
   KC_CLU_EVAL_008, or SENT_013 - per explicit instruction, no KC-specific exceptions.
6. F2 redesigned as extract-then-classify: the model first states the draft's own primary
   definitional subject in its own words, then classifies that subject as SAME/DIFFERENT/
   UNCLEAR relative to the target KC. PASS/FAIL/NOT_JUDGEABLE derived in Python.

Net effect: no criterion in this architecture ever asks the model for its own PASS/FAIL verdict
directly - every one is reduced, in Python, from an atomic per-item classification. This removes
the verdict/reason_code binding problem architecture-wide rather than patching it per criterion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from rubric_v3 import (  # noqa: F401  (SYSTEM_MESSAGE, RubricSchemaError re-exported for callers)
    RubricSchemaError,
    SYSTEM_MESSAGE,
    _check_evidence_id_shape,
    _check_no_identity_leak,
)

RequirementType = Literal["FORMULA", "DEFINITION", "PROCEDURE", "CONDITION", "DISTINCTION", "AGGREGATION"]
REQUIREMENT_TYPES: tuple[RequirementType, ...] = (
    "FORMULA", "DEFINITION", "PROCEDURE", "CONDITION", "DISTINCTION", "AGGREGATION",
)

F1_CLAIM_VERDICTS = ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED")
F3_CLAIM_VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ESTABLISHED")
F4_STATUSES = ("PRESENT_CORRECT", "MISSING", "PRESENT_BUT_INCORRECT")
F5_STATUSES = ("SUPPORTED", "NOT_SUPPORTED", "WRONG_TARGET_ONLY")
F2_CLASSIFICATIONS = ("SAME", "DIFFERENT", "UNCLEAR")

FORMULA_COMPARISON_CHECKLIST = """This requirement is FORMULA-TYPE. Do not accept the mere presence of a
formula-shaped expression as correct. Explicitly compare it, term by term, against what the
supplied source material establishes:
  - signs (positive/negative)
  - coefficients and constants
  - numerator and denominator
  - normalization (what the expression is divided or scaled by)
  - indices and summation/product ranges
  - operators (addition, subtraction, multiplication, division, exponents, logarithms)
  - conditions attached to the formula's validity
  - the aggregation method (e.g. mean vs weighted sum vs count)
A formula that differs from the correct one in any of these respects is INCORRECT, not merely
imprecise, even if it is fluently written and superficially formula-shaped."""


def evidence_block(items: tuple[dict[str, Any], ...]) -> str:
    if not items:
        return "(no evidence items)"
    return "\n\n".join(
        f"[{it['auth_id']}] (doc={it['doc_id']}, page={it['page_index']}) {it['text']}"
        for it in items
    )


# ---------------------------------------------------------------------------------------------
# 1. Claim decomposition - shared by F1 and F3
# ---------------------------------------------------------------------------------------------

def build_decompose_claims_prompt(canonical_name: str, hierarchy_path: str, draft_body: str) -> str:
    return f"""CLAIM DECOMPOSITION

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

DRAFT TO DECOMPOSE:
{draft_body}

TASK:

Decompose the draft into its minimal atomic material claims. A material claim is a factual,
mathematical, conceptual, procedural, causal, comparative, taxonomic, or definitional statement
whose falsity would change what a learner understands about the KC.

Do not evaluate the claims. Do not compare them to any evidence. Only extract them.

Each claim must be a short, self-contained, minimal atomic statement, closely paraphrasing the
draft's own wording - do not merge multiple distinct claims into one, and do not split a single
claim into redundant fragments.

If the draft asserts zero material claims, return an empty list.

Return structured JSON only."""


def decompose_claims_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "claims"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "DECOMPOSE"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["claim"],
                    "additionalProperties": False,
                    "properties": {"claim": {"type": "string", "minLength": 1}},
                },
            },
        },
    }


def validate_decompose_response(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"DECOMPOSE response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "claims"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"DECOMPOSE response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "DECOMPOSE":
        raise RubricSchemaError(f"DECOMPOSE response has wrong criterion field: {payload.get('criterion')!r}")
    claims = payload["claims"]
    if not isinstance(claims, list):
        raise RubricSchemaError("DECOMPOSE claims must be a list")
    for i, c in enumerate(claims):
        if not isinstance(c, dict) or "claim" not in c:
            raise RubricSchemaError(f"DECOMPOSE claims[{i}] missing 'claim'")
        if not isinstance(c["claim"], str) or not c["claim"].strip():
            raise RubricSchemaError(f"DECOMPOSE claims[{i}].claim must be a non-empty string")
        _check_no_identity_leak(c["claim"], f"DECOMPOSE claims[{i}].claim")


def frozen_claim_texts(decompose_payload: dict[str, Any]) -> tuple[str, ...]:
    """The frozen claim list - call validate_decompose_response first. Both F1 and F3 verify
    calls are built from this exact tuple; neither may re-decompose."""
    return tuple(c["claim"] for c in decompose_payload["claims"])


def _numbered_claims_block(claims: tuple[str, ...]) -> str:
    if not claims:
        return "(no claims - the draft asserted no material claims)"
    return "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))


# ---------------------------------------------------------------------------------------------
# 2. F1 verification - claims (frozen, from decomposition) vs SYSTEM EVIDENCE
# ---------------------------------------------------------------------------------------------

def build_f1_verify_prompt(canonical_name: str, hierarchy_path: str, claims: tuple[str, ...],
                            system_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F1 EVIDENCE FAITHFULNESS (VERIFICATION STAGE)

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

CLAIMS TO VERIFY (already decomposed from the draft - do not re-decompose, do not add, remove,
merge, or split claims):
{_numbered_claims_block(claims)}

SYSTEM EVIDENCE:
{system_evidence_block}

TASK:

For each claim listed above, in order, determine whether SYSTEM EVIDENCE supports it. Assign
exactly one:
SUPPORTED
UNSUPPORTED
CONTRADICTED

Use only SYSTEM EVIDENCE. Do not use external knowledge. Paraphrasing is allowed if meaning is
preserved.

Return exactly one verdict per claim, in the same order as listed, with the correct claim_index
(1-based, matching the numbering above).

Return structured JSON only."""


def f1_verify_json_schema(n_claims: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "verdicts"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F1"},
            "verdicts": {
                "type": "array",
                "minItems": n_claims,
                "maxItems": n_claims,
                "items": {
                    "type": "object",
                    "required": ["claim_index", "verdict", "evidence_ids"],
                    "additionalProperties": False,
                    "properties": {
                        "claim_index": {"type": "integer"},
                        "verdict": {"enum": list(F1_CLAIM_VERDICTS)},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def validate_f1_verify_response(payload: dict[str, Any], n_claims: int) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"F1 verify response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "verdicts"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"F1 verify response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "F1":
        raise RubricSchemaError(f"F1 verify response has wrong criterion field: {payload.get('criterion')!r}")
    verdicts = payload["verdicts"]
    if not isinstance(verdicts, list) or len(verdicts) != n_claims:
        raise RubricSchemaError(f"F1 verify verdicts must have exactly {n_claims} entries, got {len(verdicts) if isinstance(verdicts, list) else type(verdicts)}")
    for i, v in enumerate(verdicts):
        if not isinstance(v, dict):
            raise RubricSchemaError(f"F1 verify verdicts[{i}] is not an object")
        if v.get("verdict") not in F1_CLAIM_VERDICTS:
            raise RubricSchemaError(f"F1 verify verdicts[{i}].verdict invalid: {v.get('verdict')!r}")
        _check_evidence_id_shape(v.get("evidence_ids"), "F1", f"F1 verify verdicts[{i}]")


def derive_f1_v3_verdict(payload: dict[str, Any]) -> Literal["PASS", "FAIL"]:
    """PASS iff every claim is SUPPORTED (vacuously PASS for zero claims). Call
    validate_f1_verify_response first."""
    verdicts = payload["verdicts"]
    return "PASS" if all(v["verdict"] == "SUPPORTED" for v in verdicts) else "FAIL"


# ---------------------------------------------------------------------------------------------
# 3. F3 verification - the SAME frozen claims vs AUTHORITY CONTEXT
# ---------------------------------------------------------------------------------------------

def build_f3_verify_prompt(canonical_name: str, hierarchy_path: str, claims: tuple[str, ...],
                            authority_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F3 MATERIAL CORRECTNESS (VERIFICATION STAGE)

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

CLAIMS TO VERIFY (the SAME claims already decomposed from the draft for F1 - do not
re-decompose, do not add, remove, merge, or split claims):
{_numbered_claims_block(claims)}

AUTHORITY CONTEXT:
{authority_evidence_block}

TASK:

For each claim listed above, in order, determine AUTHORITY CONTEXT's position on it. Assign
exactly one:
SUPPORTED - AUTHORITY CONTEXT confirms this claim
CONTRADICTED - AUTHORITY CONTEXT states something that conflicts with this claim (a
  meaning-changing factual, mathematical, conceptual, procedural, relational, or taxonomic
  difference)
NOT_ESTABLISHED - AUTHORITY CONTEXT neither confirms nor conflicts with this claim

Do not mark a claim CONTRADICTED merely because it is unaddressed - only an actual conflict is
CONTRADICTED; silence is NOT_ESTABLISHED. Do not use outside knowledge to override authority
context.

If a claim is formula-shaped or numeric, compare explicitly: signs, coefficients, numerator and
denominator, normalization, indices, operators, conditions, and aggregation - not merely whether
a formula is present.

Return exactly one verdict per claim, in the same order as listed, with the correct claim_index
(1-based, matching the numbering above).

Return structured JSON only."""


def f3_verify_json_schema(n_claims: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "verdicts"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F3"},
            "verdicts": {
                "type": "array",
                "minItems": n_claims,
                "maxItems": n_claims,
                "items": {
                    "type": "object",
                    "required": ["claim_index", "verdict", "evidence_ids"],
                    "additionalProperties": False,
                    "properties": {
                        "claim_index": {"type": "integer"},
                        "verdict": {"enum": list(F3_CLAIM_VERDICTS)},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def validate_f3_verify_response(payload: dict[str, Any], n_claims: int) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"F3 verify response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "verdicts"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"F3 verify response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "F3":
        raise RubricSchemaError(f"F3 verify response has wrong criterion field: {payload.get('criterion')!r}")
    verdicts = payload["verdicts"]
    if not isinstance(verdicts, list) or len(verdicts) != n_claims:
        raise RubricSchemaError(f"F3 verify verdicts must have exactly {n_claims} entries, got {len(verdicts) if isinstance(verdicts, list) else type(verdicts)}")
    for i, v in enumerate(verdicts):
        if not isinstance(v, dict):
            raise RubricSchemaError(f"F3 verify verdicts[{i}] is not an object")
        if v.get("verdict") not in F3_CLAIM_VERDICTS:
            raise RubricSchemaError(f"F3 verify verdicts[{i}].verdict invalid: {v.get('verdict')!r}")
        _check_evidence_id_shape(v.get("evidence_ids"), "F3", f"F3 verify verdicts[{i}]")


def derive_f3_v3_verdict(payload: dict[str, Any]) -> Literal["PASS", "FAIL"]:
    """FAIL iff any claim is CONTRADICTED; NOT_ESTABLISHED does not fail the criterion (silence
    is not an error - see module docstring point 2). Vacuously PASS for zero claims. Call
    validate_f3_verify_response first."""
    verdicts = payload["verdicts"]
    return "FAIL" if any(v["verdict"] == "CONTRADICTED" for v in verdicts) else "PASS"


# ---------------------------------------------------------------------------------------------
# 4. CORE_REQUIREMENTS ledger - one per KC, authority-only, candidate/system-independent
# ---------------------------------------------------------------------------------------------

def build_core_requirements_prompt(canonical_name: str, hierarchy_path: str,
                                    authority_evidence_block: str) -> str:
    return f"""CORE REQUIREMENTS EXTRACTION

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

AUTHORITY CONTEXT:
{authority_evidence_block}

TASK:

From AUTHORITY CONTEXT ALONE, list the specific elements (definitions, formulas, conditions,
procedures, distinctions, aggregations) that AUTHORITY CONTEXT itself establishes as part of the
defining core needed to identify or operationally define the target KC. List only elements
AUTHORITY CONTEXT actually establishes - do not invent elements it does not support, and do not
list optional examples, applications, or historical commentary as required elements.

For each element, classify its TYPE as exactly one of:
FORMULA
DEFINITION
PROCEDURE
CONDITION
DISTINCTION
AGGREGATION

If AUTHORITY CONTEXT does not establish any clear defining-core element for this KC, return an
empty list.

This step does not evaluate any draft or system evidence - it characterizes only what AUTHORITY
CONTEXT itself establishes, independent of any candidate output.

Return structured JSON only."""


def core_requirements_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "requirements"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "CORE_REQUIREMENTS"},
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["requirement", "type", "evidence_ids"],
                    "additionalProperties": False,
                    "properties": {
                        "requirement": {"type": "string", "minLength": 1},
                        "type": {"enum": list(REQUIREMENT_TYPES)},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def validate_core_requirements_response(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"CORE_REQUIREMENTS response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "requirements"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"CORE_REQUIREMENTS response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "CORE_REQUIREMENTS":
        raise RubricSchemaError(f"CORE_REQUIREMENTS response has wrong criterion field: {payload.get('criterion')!r}")
    reqs = payload["requirements"]
    if not isinstance(reqs, list):
        raise RubricSchemaError("CORE_REQUIREMENTS requirements must be a list")
    for i, r in enumerate(reqs):
        if not isinstance(r, dict):
            raise RubricSchemaError(f"CORE_REQUIREMENTS requirements[{i}] is not an object")
        if not isinstance(r.get("requirement"), str) or not r["requirement"].strip():
            raise RubricSchemaError(f"CORE_REQUIREMENTS requirements[{i}].requirement must be a non-empty string")
        if r.get("type") not in REQUIREMENT_TYPES:
            raise RubricSchemaError(f"CORE_REQUIREMENTS requirements[{i}].type invalid: {r.get('type')!r}")
        _check_evidence_id_shape(r.get("evidence_ids"), "F4", f"CORE_REQUIREMENTS requirements[{i}]")
        _check_no_identity_leak(r["requirement"], f"CORE_REQUIREMENTS requirements[{i}].requirement")


@dataclass(frozen=True)
class CoreRequirement:
    requirement: str
    type: RequirementType


def frozen_requirements(ledger_payload: dict[str, Any]) -> tuple[CoreRequirement, ...]:
    """Call validate_core_requirements_response first. This exact tuple is reused for every
    F4/F5 call against every candidate/system for this KC - built once, never re-derived."""
    return tuple(CoreRequirement(r["requirement"], r["type"]) for r in ledger_payload["requirements"])


# ---------------------------------------------------------------------------------------------
# 5. F4 - one separate inference call per requirement, against the DRAFT
# ---------------------------------------------------------------------------------------------

def build_f4_requirement_prompt(canonical_name: str, requirement: CoreRequirement, draft_body: str,
                                 authority_evidence_block: str) -> str:
    checklist = f"\n\n{FORMULA_COMPARISON_CHECKLIST}\n" if requirement.type == "FORMULA" else ""
    return f"""EVALUATION CRITERION: F4 CORE COMPLETENESS (SINGLE REQUIREMENT)

TARGET KC:
{canonical_name}

REQUIREMENT TO CHECK:
{requirement.requirement}

REQUIREMENT TYPE: {requirement.type}
{checklist}
DRAFT TO EVALUATE:
{draft_body}

AUTHORITY CONTEXT (cite the id(s) here that establish the correct form of this requirement -
evidence_ids must be real ids from this list, never free text):
{authority_evidence_block}

TASK:

Determine the DRAFT's treatment of this ONE requirement only - ignore whether other
requirements are met. Assign exactly one:
PRESENT_CORRECT - the draft addresses this requirement and represents it correctly (paraphrase
  allowed if meaning is preserved)
MISSING - the draft does not address this requirement at all
PRESENT_BUT_INCORRECT - the draft addresses this requirement but represents it incorrectly

Return structured JSON only."""


def f4_requirement_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "status", "evidence_ids", "rationale"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F4"},
            "status": {"enum": list(F4_STATUSES)},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def validate_f4_requirement_response(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"F4 requirement response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "status", "evidence_ids", "rationale"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"F4 requirement response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "F4":
        raise RubricSchemaError(f"F4 requirement response has wrong criterion field: {payload.get('criterion')!r}")
    if payload.get("status") not in F4_STATUSES:
        raise RubricSchemaError(f"F4 requirement status invalid: {payload.get('status')!r}")
    _check_evidence_id_shape(payload.get("evidence_ids"), "F4", "F4 requirement")
    if not isinstance(payload.get("rationale"), str):
        raise RubricSchemaError("F4 requirement rationale must be a string")
    _check_no_identity_leak(payload["rationale"], "F4 requirement rationale")


def derive_f4_v3_outcome(per_requirement_statuses: list[str]) -> tuple[Literal["PASS", "FAIL", "NOT_JUDGEABLE"], str]:
    """Aggregates across the LIST of per-requirement call results (one call per requirement,
    unlike v2's single batched call) - PASS iff every requirement is PRESENT_CORRECT. Zero
    requirements (empty ledger) -> NOT_JUDGEABLE."""
    if not per_requirement_statuses:
        return "NOT_JUDGEABLE", "NONE"
    if all(s == "PRESENT_CORRECT" for s in per_requirement_statuses):
        return "PASS", "NONE"
    has_missing = "MISSING" in per_requirement_statuses
    has_incorrect = "PRESENT_BUT_INCORRECT" in per_requirement_statuses
    if has_missing and has_incorrect:
        return "FAIL", "MISSING_AND_INCORRECT_ELEMENTS"
    if has_missing:
        return "FAIL", "MISSING_REQUIRED_ELEMENT"
    return "FAIL", "INCORRECT_REQUIRED_ELEMENT"


# ---------------------------------------------------------------------------------------------
# 6. F5 - one separate inference call per requirement (the SAME ledger as F4), against SYSTEM
#    EVIDENCE
# ---------------------------------------------------------------------------------------------

def build_f5_requirement_prompt(canonical_name: str, requirement: CoreRequirement,
                                 system_evidence_block: str) -> str:
    checklist = f"\n\n{FORMULA_COMPARISON_CHECKLIST}\n" if requirement.type == "FORMULA" else ""
    return f"""EVALUATION CRITERION: F5 EVIDENCE SUFFICIENCY (SINGLE REQUIREMENT)

TARGET KC:
{canonical_name}

REQUIREMENT TO CHECK:
{requirement.requirement}

REQUIREMENT TYPE: {requirement.type}
{checklist}
SYSTEM EVIDENCE:
{system_evidence_block}

TASK:

Determine SYSTEM EVIDENCE's support for this ONE requirement only. Assign exactly one:
SUPPORTED - SYSTEM EVIDENCE contains source material establishing this requirement for the
  target KC
NOT_SUPPORTED - SYSTEM EVIDENCE contains no source material establishing this requirement at
  all
WRONG_TARGET_ONLY - SYSTEM EVIDENCE contains source material for this requirement, but only for
  a different concept, not the target KC

Do not judge any generated draft in this criterion - judge only whether SYSTEM EVIDENCE itself
could support this requirement.

Return structured JSON only."""


def f5_requirement_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "status", "evidence_ids", "rationale"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F5"},
            "status": {"enum": list(F5_STATUSES)},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def validate_f5_requirement_response(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"F5 requirement response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "status", "evidence_ids", "rationale"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"F5 requirement response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "F5":
        raise RubricSchemaError(f"F5 requirement response has wrong criterion field: {payload.get('criterion')!r}")
    if payload.get("status") not in F5_STATUSES:
        raise RubricSchemaError(f"F5 requirement status invalid: {payload.get('status')!r}")
    _check_evidence_id_shape(payload.get("evidence_ids"), "F5", "F5 requirement")
    if not isinstance(payload.get("rationale"), str):
        raise RubricSchemaError("F5 requirement rationale must be a string")
    _check_no_identity_leak(payload["rationale"], "F5 requirement rationale")


def derive_f5_v3_outcome(per_requirement_statuses: list[str]) -> tuple[Literal["PASS", "FAIL"], str]:
    """PASS iff every requirement is SUPPORTED. Zero requirements -> FAIL/NO_TARGET_SUPPORT
    (never a vacuous PASS - same reasoning as v2's derive_f5_outcome: a sufficiency judgment
    that defaults to 'yes' on a degenerate empty extraction is the dangerous direction)."""
    if not per_requirement_statuses:
        return "FAIL", "NO_TARGET_SUPPORT"
    if all(s == "SUPPORTED" for s in per_requirement_statuses):
        return "PASS", "NONE"
    if "WRONG_TARGET_ONLY" in per_requirement_statuses:
        return "FAIL", "WRONG_TARGET_SUPPORT"
    return "FAIL", "MISSING_DEFINING_CONTENT"


# ---------------------------------------------------------------------------------------------
# 7. F2 - extract the draft's own primary subject, then classify SAME/DIFFERENT/UNCLEAR
# ---------------------------------------------------------------------------------------------

def build_f2_v3_prompt(canonical_name: str, hierarchy_path: str, draft_body: str,
                        authority_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F2 EXACT KC ALIGNMENT

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

DRAFT TO EVALUATE:
{draft_body}

AUTHORITY CONTEXT:
{authority_evidence_block}

TASK:

Step 1. State the draft's own primary definitional subject: what specific concept, mechanism,
or entity is the draft actually defining or explaining as its central subject? Answer in your
own words, independent of what the target KC's name is.

Step 2. Compare that primary subject to the target KC and classify the relationship as exactly
one of:
SAME - the draft's primary subject IS the target KC (the same concept, not merely related to
  it)
DIFFERENT - the draft's primary subject is a sibling, parent, child, or otherwise distinct
  concept from the target KC
UNCLEAR - the draft's primary subject cannot be confidently identified as the same as or
  different from the target KC given what is present

Related concepts appearing only as supporting context, without becoming the draft's own central
subject, do not make the classification DIFFERENT.

Return structured JSON only."""


def f2_v3_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "primary_subject", "classification", "evidence_ids", "rationale"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F2"},
            "primary_subject": {"type": "string", "minLength": 1},
            "classification": {"enum": list(F2_CLASSIFICATIONS)},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def validate_f2_v3_response(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"F2 response is not a JSON object: {type(payload)!r}")
    missing = {"case_id", "criterion", "primary_subject", "classification", "evidence_ids", "rationale"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"F2 response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "F2":
        raise RubricSchemaError(f"F2 response has wrong criterion field: {payload.get('criterion')!r}")
    if not isinstance(payload.get("primary_subject"), str) or not payload["primary_subject"].strip():
        raise RubricSchemaError("F2 primary_subject must be a non-empty string")
    if payload.get("classification") not in F2_CLASSIFICATIONS:
        raise RubricSchemaError(f"F2 classification invalid: {payload.get('classification')!r}")
    _check_evidence_id_shape(payload.get("evidence_ids"), "F2", "F2")
    if not isinstance(payload.get("rationale"), str):
        raise RubricSchemaError("F2 rationale must be a string")
    _check_no_identity_leak(payload["primary_subject"], "F2 primary_subject")
    _check_no_identity_leak(payload["rationale"], "F2 rationale")


def derive_f2_v3_verdict(payload: dict[str, Any]) -> Literal["PASS", "FAIL", "NOT_JUDGEABLE"]:
    """SAME->PASS, DIFFERENT->FAIL, UNCLEAR->NOT_JUDGEABLE. Call validate_f2_v3_response first."""
    return {"SAME": "PASS", "DIFFERENT": "FAIL", "UNCLEAR": "NOT_JUDGEABLE"}[payload["classification"]]
