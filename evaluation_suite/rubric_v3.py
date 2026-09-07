"""F1-F5 judge rubric for the R9 final KC content quality evaluation campaign (FINAL R9 KC
CONTENT QUALITY EVALUATION spec, sections 9-22), development-hardened 2026-08-24 after the
first real Selene smoke test surfaced two structural weaknesses.

Five atomic, single-criterion Selene inference requests per candidate row - never one combined
"judge everything" prompt (GroUSE, Muller et al. 2025).

HARDENING PASS (this revision) - three changes, each driven by a real measured failure mode in
the 2026-08-23 smoke test, not a hypothetical:

1. Grammar-level verdict/reason_code binding, chosen empirically, not by documentation. Compile-
   tested against the pinned vLLM 0.27.1 + XGrammar stack before relying on it:
     - JSON-Schema if/then/else "compiles" without error but is SILENTLY IGNORED - the emitted
       grammar allows every reason_code regardless of verdict (verified directly: dumped the
       compiled grammar's `root` production and confirmed no conditional branching exists).
     - A `oneOf` of fully self-contained, non-overlapping branches (one branch per legal
       verdict+reason_code pairing) compiles to a grammar that DOES structurally enforce the
       pairing - verified the same way, dumping the grammar and confirming `root_case_0`/
       `root_case_1` each hard-code their own verdict/reason_code pair.
   F2 and F3 (the only two criteria that still ask the model for a top-level verdict) use this
   oneOf pattern. F1/F4/F5 sidestep the problem entirely by never asking the model for a verdict
   at all (see 3).
2. Rationale word-count is no longer a validity criterion. It was, and it produced a real
   invalid response in the smoke test (F4 rationale at 100+ words) for a reason unrelated to
   whether the judgment itself was correct - a judge that reasons a little verbosely is not the
   same failure mode as a judge that violates the verdict/reason_code contract.
3. F4 and F5 no longer ask the model for a holistic verdict at all - matching F1's existing
   claim-decomposition pattern, extended to these two. Both now ask the model to (a) enumerate
   the AUTHORITY-CONTEXT-established defining-core elements for the target KC, then (b) classify
   each element's status - F4 against the DRAFT (PRESENT_CORRECT / MISSING /
   PRESENT_BUT_INCORRECT), F5 against SYSTEM EVIDENCE (SUPPORTED / NOT_SUPPORTED /
   WRONG_TARGET_ONLY). PASS is derived deterministically as "every element resolves to the
   fully-correct status"; this is a strictly stronger check than the old holistic-verdict design,
   which allowed a judge to say "PASS" for F4 merely because *a* formula-shaped passage existed
   in the draft, without checking it was the RIGHT formula (measured directly: SENT_013 in the
   2026-08-23 smoke test was exactly this failure - Selene passed F4 with rationale "the formula
   for entropy is provided", citing the correct authority formula in its own evidence_ids while
   the draft actually contained a different, wrong one).

NOT_JUDGEABLE is schema-legal for F3 (unchanged) and F4 (now the derived state when zero
defining-core elements are extracted from AUTHORITY CONTEXT - i.e. authority itself establishes
no clear core, so nothing can be classified). F5 has no NOT_JUDGEABLE state (the original design
never offered one); a degenerate zero-element F5 extraction is treated as FAIL/NO_TARGET_SUPPORT
rather than a vacuous PASS - see derive_f5_outcome's docstring for why.

Every derived metric in section 22 (materially_sound, justified_abstention,
avoidable_abstention, safe_outcome, unsafe_draft) is a pure function of validated verdicts -
never a value read from the LLM's own arithmetic. Evidence-ID *existence* resolution against a
real packet is provenance.py's job (already built, reused not duplicated); this module only
checks that an evidence_id is a well-formed string in the correct SYS_*/AUTH_* namespace for its
criterion - a candidate ID shaped like a leaked system/drafter label (e.g. containing "qwen",
"gemma", "deepseek", "proposed", "dos", "baseline") fails validation outright, since Section 30
requires those never reach the judge or its output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

Criterion = Literal["F1", "F2", "F3", "F4", "F5"]
ClaimVerdict = Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
CriterionVerdict = Literal["PASS", "FAIL", "NOT_JUDGEABLE"]

CRITERIA: tuple[Criterion, ...] = ("F1", "F2", "F3", "F4", "F5")

# Which verdicts each criterion's own prompt actually offers the model directly. F1/F4/F5 are
# absent here on purpose - none of them ever ask the model for a top-level verdict; it is always
# derived (F1: from claims; F4/F5: from required_elements).
_ALLOWED_VERDICTS: dict[str, tuple[str, ...]] = {
    "F2": ("PASS", "FAIL"),
    "F3": ("PASS", "FAIL", "NOT_JUDGEABLE"),
}

# Allowed reason codes per criterion. F1's is still a flat model-supplied field (a secondary,
# non-binding descriptive tag - the real signal is claims[].verdict). F4/F5's are DERIVED, listed
# here only so downstream reporting code has one place to look up the full vocabulary.
ALLOWED_REASON_CODES: dict[str, tuple[str, ...]] = {
    "F1": ("NONE", "UNSUPPORTED_FACT", "UNSUPPORTED_FORMULA", "UNSUPPORTED_RELATION",
           "UNSUPPORTED_PROCEDURE", "CONTRADICTS_EVIDENCE"),
    "F2": ("NONE", "WRONG_SIBLING", "WRONG_PARENT", "WRONG_CHILD", "WRONG_CONCEPT"),
    "F3": ("NONE", "WRONG_DEFINITION", "WRONG_FORMULA", "WRONG_CONDITION", "WRONG_PROCEDURE",
           "WRONG_RELATION", "WRONG_TAXONOMY", "CONTRADICTORY_CLAIMS"),
    "F4": ("NONE", "MISSING_REQUIRED_ELEMENT", "INCORRECT_REQUIRED_ELEMENT",
           "MISSING_AND_INCORRECT_ELEMENTS"),
    "F5": ("NONE", "NO_TARGET_SUPPORT", "WRONG_TARGET_SUPPORT", "MISSING_DEFINING_CONTENT"),
}

# Section 30: identity tokens that must never appear in a judge-visible evidence ID or
# reach the judge's own output. Checked case-insensitively. Deliberately does NOT include the
# bare word "proposed" - found via a real false positive in the sentinel expansion
# (two organic real-KC drafts use "proposed" in its ordinary English sense, e.g. "originally
# proposed for regression problems", "interpretations have been proposed in the literature";
# neither has anything to do with the RAG system codenamed Proposed). The system-identity risk
# is caught by the more specific multi-word/underscored forms below instead.
_LEAKED_IDENTITY_TOKENS = (
    "qwen", "gemma", "deepseek", "dos-rag", "dosrag", "baseline", "base_dense",
    "basedense", "native_proposed", "controlled_comparator",
)

_SYS_ID_RE = re.compile(r"^SYS_\d{3,}$")
_AUTH_ID_RE = re.compile(r"^AUTH_\d{3,}$")

F2_FAIL_REASON_CODES = ("WRONG_SIBLING", "WRONG_PARENT", "WRONG_CHILD", "WRONG_CONCEPT")
F3_FAIL_REASON_CODES = ("WRONG_DEFINITION", "WRONG_FORMULA", "WRONG_CONDITION", "WRONG_PROCEDURE",
                         "WRONG_RELATION", "WRONG_TAXONOMY", "CONTRADICTORY_CLAIMS")

F4_ELEMENT_STATUSES = ("PRESENT_CORRECT", "MISSING", "PRESENT_BUT_INCORRECT")
F5_ELEMENT_STATUSES = ("SUPPORTED", "NOT_SUPPORTED", "WRONG_TARGET_ONLY")


class RubricSchemaError(ValueError):
    """Raised for a STRUCTURAL contract violation - malformed shape, wrong enum member, a
    leaked identity token, an evidence-id outside its namespace. Never raised for rationale
    length (see module docstring, point 2) and never reachable for a verdict/reason_code
    mismatch on F2/F3 (see point 1) - the grammar makes that combination impossible to emit in
    the first place, this function no longer needs to check for it."""


# ---------------------------------------------------------------------------------------------
# Section 15: shared system message
# ---------------------------------------------------------------------------------------------

SYSTEM_MESSAGE = """You are an evaluator of evidence-grounded educational knowledge-component drafts.

Your task is not to improve or rewrite the draft.

Your task is not to reward fluency, style, verbosity, confidence, or sophistication.

Judge only the single evaluation criterion supplied in this request.

Use only the evidence explicitly supplied in this request.
Do not use outside knowledge to add facts or repair missing source information.

A fluent response can fail.
A short response can pass.
A source-faithful response can still fail a target-alignment or correctness criterion.
An incomplete response can remain faithful.

Follow the criterion exactly.

Your response must conform exactly to the provided JSON schema."""


# ---------------------------------------------------------------------------------------------
# Per-criterion user prompt builders
# ---------------------------------------------------------------------------------------------

def build_f1_prompt(canonical_name: str, hierarchy_path: str, draft_body: str,
                     system_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F1 EVIDENCE FAITHFULNESS

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

DRAFT TO EVALUATE:
{draft_body}

SYSTEM EVIDENCE:
{system_evidence_block}

TASK:

Determine whether every material claim in the draft is supported by SYSTEM EVIDENCE.

A material claim is a factual, mathematical, conceptual, procedural, causal,
comparative, taxonomic, or definitional statement whose falsity would change
what a learner understands about the KC.

First decompose the draft into minimal material claims.

For each claim assign exactly one:
SUPPORTED
UNSUPPORTED
CONTRADICTED

Use only SYSTEM EVIDENCE.
Do not use external knowledge.

Paraphrasing is allowed if meaning is preserved.

Missing information does not make this criterion fail.

Return structured JSON only."""


def build_f2_prompt(canonical_name: str, hierarchy_path: str, draft_body: str,
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

Determine whether the draft's central definition or explanation is actually
about the exact TARGET KC.

PASS if the target KC is the main definitional subject and mechanism.

FAIL if the draft primarily defines or explains a sibling, parent, child,
near-neighbour, or different concept.

Related concepts may appear as supporting context without causing failure.

Do not use fluency, length, or writing quality as evidence.

Use only the supplied authority context.

Return structured JSON only."""


def build_f3_prompt(canonical_name: str, hierarchy_path: str, draft_body: str,
                     authority_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F3 MATERIAL CORRECTNESS

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

DRAFT TO EVALUATE:
{draft_body}

AUTHORITY CONTEXT:
{authority_evidence_block}

TASK:

Determine whether the draft contains a meaning-changing factual,
mathematical, conceptual, procedural, relational, or taxonomic error
relative to AUTHORITY CONTEXT.

PASS if there is no material error.

FAIL if at least one error would teach a materially incorrect definition,
formula, condition, procedure, relationship, taxonomy, or interpretation.

Do not fail for style, grammar, verbosity, concision, optional missing
examples, or harmless notation differences.

Do not use outside knowledge to override the authority context.

If the authority context itself is genuinely insufficient or conflicting
such that correctness cannot be determined, return NOT_JUDGEABLE.

Return structured JSON only."""


def build_f4_prompt(canonical_name: str, hierarchy_path: str, draft_body: str,
                     authority_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F4 CORE COMPLETENESS

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

DRAFT TO EVALUATE:
{draft_body}

AUTHORITY CONTEXT:
{authority_evidence_block}

TASK:

Step 1. From AUTHORITY CONTEXT alone, list the specific elements (definitions,
formulas, conditions, procedures, distinctions, aggregations) that AUTHORITY
CONTEXT itself establishes as part of the defining core needed to identify or
operationally define the target KC. List only elements AUTHORITY CONTEXT
actually establishes - do not invent elements it does not support. Do not
list optional examples, applications, or historical commentary as required
elements.

If AUTHORITY CONTEXT does not establish any clear defining-core element for
this KC, return an empty list of required elements.

Step 2. For each required element you listed, classify the DRAFT's treatment
of it as exactly one of:
PRESENT_CORRECT - the element appears in the draft and is correctly represented (paraphrase allowed if meaning is preserved)
MISSING - the element does not appear in the draft at all
PRESENT_BUT_INCORRECT - the draft addresses the element but represents it incorrectly

Cite the AUTHORITY CONTEXT id(s) that establish each element as part of the
defining core.

Return structured JSON only."""


def build_f5_prompt(canonical_name: str, hierarchy_path: str, system_evidence_block: str,
                     authority_evidence_block: str) -> str:
    return f"""EVALUATION CRITERION: F5 EVIDENCE SUFFICIENCY

TARGET KC:
{canonical_name}

HIERARCHY PATH:
{hierarchy_path}

SYSTEM EVIDENCE:
{system_evidence_block}

AUTHORITY CONTEXT:
{authority_evidence_block}

TASK:

Step 1. From AUTHORITY CONTEXT alone, list the specific elements (definitions,
formulas, conditions, procedures, distinctions, aggregations) that AUTHORITY
CONTEXT itself establishes as part of the defining core needed to identify or
operationally define the target KC. List only elements AUTHORITY CONTEXT
actually establishes. Do not list optional examples or applications.

Step 2. For each required element you listed, classify SYSTEM EVIDENCE's
support for it as exactly one of:
SUPPORTED - SYSTEM EVIDENCE contains source material establishing this element for the target KC
NOT_SUPPORTED - SYSTEM EVIDENCE contains no source material establishing this element at all
WRONG_TARGET_ONLY - SYSTEM EVIDENCE contains source material for this element, but only for a different concept, not the target KC

Do not judge the generated draft in this criterion - judge only whether
SYSTEM EVIDENCE itself could support a materially correct, exact-target,
core-complete definition.

Cite the SYSTEM EVIDENCE id(s) relevant to each element.

Return structured JSON only."""


_PROMPT_BUILDERS = {
    "F1": build_f1_prompt,
    "F2": build_f2_prompt,
    "F3": build_f3_prompt,
    "F4": build_f4_prompt,
    "F5": build_f5_prompt,
}


# ---------------------------------------------------------------------------------------------
# Structured-output JSON schemas
# F2/F3 use a `oneOf` of fully self-contained branches, one per legal (verdict, reason_code)
# pairing - the ONLY construct in this module's own compile-testing that XGrammar actually
# enforces at the grammar level (see module docstring point 1). Branches deliberately repeat
# their shared properties rather than composing via allOf/$ref, since only the flat, repeated-
# property form has been verified to compile to a correctly-restrictive grammar; allOf/$ref
# composition has not been tested and is not assumed to work.
# ---------------------------------------------------------------------------------------------

def _base_props(criterion: str) -> dict[str, Any]:
    return {
        "case_id": {"type": "string", "minLength": 1},
        "criterion": {"const": criterion},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    }


def f1_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "claims", "reason_code", "rationale"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F1"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["claim", "verdict", "evidence_ids"],
                    "additionalProperties": False,
                    "properties": {
                        "claim": {"type": "string", "minLength": 1},
                        "verdict": {"enum": ["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "reason_code": {"enum": list(ALLOWED_REASON_CODES["F1"])},
            "rationale": {"type": "string"},
        },
    }


def _pass_fail_oneof_schema(criterion: str, fail_reason_codes: tuple[str, ...],
                             include_not_judgeable: bool) -> dict[str, Any]:
    required = ["case_id", "criterion", "verdict", "reason_code", "evidence_ids", "rationale"]

    def branch(verdict: str, reason_code_schema: dict[str, Any]) -> dict[str, Any]:
        props = dict(_base_props(criterion))
        props["verdict"] = {"const": verdict}
        props["reason_code"] = reason_code_schema
        return {"type": "object", "required": required, "additionalProperties": False, "properties": props}

    branches = [
        branch("PASS", {"const": "NONE"}),
        branch("FAIL", {"enum": list(fail_reason_codes)}),
    ]
    if include_not_judgeable:
        branches.append(branch("NOT_JUDGEABLE", {"const": "NONE"}))
    return {"oneOf": branches}


def f2_json_schema() -> dict[str, Any]:
    return _pass_fail_oneof_schema("F2", F2_FAIL_REASON_CODES, include_not_judgeable=False)


def f3_json_schema() -> dict[str, Any]:
    return _pass_fail_oneof_schema("F3", F3_FAIL_REASON_CODES, include_not_judgeable=True)


def _required_element_schema(status_enum: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["element", "status", "evidence_ids", "rationale"],
        "additionalProperties": False,
        "properties": {
            "element": {"type": "string", "minLength": 1},
            "status": {"enum": list(status_enum)},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
    }


def f4_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "required_elements", "overall_rationale"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F4"},
            "required_elements": {"type": "array", "items": _required_element_schema(F4_ELEMENT_STATUSES)},
            "overall_rationale": {"type": "string"},
        },
    }


def f5_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["case_id", "criterion", "required_elements", "overall_rationale"],
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "criterion": {"const": "F5"},
            "required_elements": {"type": "array", "items": _required_element_schema(F5_ELEMENT_STATUSES)},
            "overall_rationale": {"type": "string"},
        },
    }


def criterion_json_schema(criterion: Criterion) -> dict[str, Any]:
    return {
        "F1": f1_json_schema, "F2": f2_json_schema, "F3": f3_json_schema,
        "F4": f4_json_schema, "F5": f5_json_schema,
    }[criterion]()


# ---------------------------------------------------------------------------------------------
# Response validation - BEFORE any derived score is trusted.
# Two-tier, reported separately by callers that want the distinction (see
# validate_selene_qualification_v3.py): STRUCTURAL validity is "does this parse as JSON and
# match the JSON Schema" (mechanically guaranteed by the grammar for F2/F3's verdict/reason_code
# pairing, but the harness still re-checks it independently rather than trusting the server not
# to have a bug). CONTRACT validity is everything this module checks beyond bare JSON-Schema
# conformance: no identity leak, evidence-id namespace, F1 claim shape, F4/F5 element shape.
# ---------------------------------------------------------------------------------------------

def _check_no_identity_leak(text: str, where: str) -> None:
    lowered = text.lower()
    for token in _LEAKED_IDENTITY_TOKENS:
        if token in lowered:
            raise RubricSchemaError(f"{where} leaks a system/drafter identity token: {token!r}")


def _check_evidence_id_shape(evidence_ids: Any, criterion: Criterion, where: str) -> list[str]:
    if not isinstance(evidence_ids, list) or not all(isinstance(x, str) for x in evidence_ids):
        raise RubricSchemaError(f"{where} evidence_ids must be a list of strings")
    pattern = _SYS_ID_RE if criterion in ("F1", "F5") else _AUTH_ID_RE
    # F5 also legitimately cites AUTH_* (it compares SYSTEM EVIDENCE against AUTHORITY CONTEXT).
    alt_pattern = _AUTH_ID_RE if criterion == "F5" else None
    for eid in evidence_ids:
        if pattern.match(eid):
            continue
        if alt_pattern is not None and alt_pattern.match(eid):
            continue
        raise RubricSchemaError(f"{where} evidence_id {eid!r} is not a well-formed SYS_*/AUTH_* id")
    return evidence_ids


def validate_f1_response(payload: dict[str, Any]) -> None:
    """Raises RubricSchemaError on any structural violation. Does not mutate payload."""
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"F1 response is not a JSON object: {type(payload)!r}")

    missing = {"case_id", "criterion", "claims", "reason_code", "rationale"} - payload.keys()
    if missing:
        raise RubricSchemaError(f"F1 response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != "F1":
        raise RubricSchemaError(f"F1 response has wrong criterion field: {payload.get('criterion')!r}")
    if not isinstance(payload["case_id"], str) or not payload["case_id"]:
        raise RubricSchemaError("F1 case_id must be a non-empty string")

    claims = payload["claims"]
    if not isinstance(claims, list):
        raise RubricSchemaError("F1 claims must be a list")
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            raise RubricSchemaError(f"F1 claims[{i}] is not an object")
        cmissing = {"claim", "verdict", "evidence_ids"} - c.keys()
        if cmissing:
            raise RubricSchemaError(f"F1 claims[{i}] missing keys: {sorted(cmissing)}")
        if not isinstance(c["claim"], str) or not c["claim"].strip():
            raise RubricSchemaError(f"F1 claims[{i}].claim must be a non-empty string")
        if c["verdict"] not in ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED"):
            raise RubricSchemaError(f"F1 claims[{i}].verdict invalid: {c['verdict']!r}")
        _check_evidence_id_shape(c["evidence_ids"], "F1", f"F1 claims[{i}]")
        _check_no_identity_leak(c["claim"], f"F1 claims[{i}].claim")

    reason = payload["reason_code"]
    if reason not in ALLOWED_REASON_CODES["F1"]:
        raise RubricSchemaError(f"F1 reason_code invalid: {reason!r}")

    rationale = payload["rationale"]
    if not isinstance(rationale, str):
        raise RubricSchemaError("F1 rationale must be a string")
    _check_no_identity_leak(rationale, "F1 rationale")


def validate_criterion_response(payload: dict[str, Any], criterion: Literal["F2", "F3"]) -> None:
    """Validates an F2/F3 response. Raises RubricSchemaError on any violation. Verdict/reason_code
    pairing is NOT re-derived or checked here as a separate rule - the grammar makes an illegal
    pairing structurally unreachable, so if one somehow appeared it would be caught generically
    by the reason-not-in-allowed-set check below, not by a bespoke pairing rule."""
    if criterion not in ("F2", "F3"):
        raise RubricSchemaError(f"use validate_f4_response/validate_f5_response for {criterion}")
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"{criterion} response is not a JSON object: {type(payload)!r}")

    required = {"case_id", "criterion", "verdict", "reason_code", "evidence_ids", "rationale"}
    missing = required - payload.keys()
    if missing:
        raise RubricSchemaError(f"{criterion} response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != criterion:
        raise RubricSchemaError(f"{criterion} response has wrong criterion field: {payload.get('criterion')!r}")
    if not isinstance(payload["case_id"], str) or not payload["case_id"]:
        raise RubricSchemaError(f"{criterion} case_id must be a non-empty string")

    allowed_verdicts = _ALLOWED_VERDICTS[criterion]
    verdict = payload["verdict"]
    if verdict not in allowed_verdicts:
        raise RubricSchemaError(
            f"{criterion} verdict {verdict!r} not allowed - this criterion's prompt only offers {allowed_verdicts}"
        )

    reason = payload["reason_code"]
    if reason not in ALLOWED_REASON_CODES[criterion]:
        raise RubricSchemaError(f"{criterion} reason_code invalid: {reason!r}")
    if verdict in ("PASS", "NOT_JUDGEABLE") and reason != "NONE":
        raise RubricSchemaError(f"{criterion} verdict {verdict} must carry reason_code NONE, got {reason!r}")
    if verdict == "FAIL" and reason == "NONE":
        raise RubricSchemaError(f"{criterion} verdict FAIL must carry a specific reason_code, not NONE")

    _check_evidence_id_shape(payload["evidence_ids"], criterion, criterion)

    rationale = payload["rationale"]
    if not isinstance(rationale, str):
        raise RubricSchemaError(f"{criterion} rationale must be a string")
    _check_no_identity_leak(rationale, f"{criterion} rationale")


def _validate_required_elements_response(payload: dict[str, Any], criterion: Literal["F4", "F5"],
                                          status_enum: tuple[str, ...],
                                          evidence_criterion_for_ids: Criterion) -> None:
    if not isinstance(payload, dict):
        raise RubricSchemaError(f"{criterion} response is not a JSON object: {type(payload)!r}")

    required = {"case_id", "criterion", "required_elements", "overall_rationale"}
    missing = required - payload.keys()
    if missing:
        raise RubricSchemaError(f"{criterion} response missing required keys: {sorted(missing)}")
    if payload.get("criterion") != criterion:
        raise RubricSchemaError(f"{criterion} response has wrong criterion field: {payload.get('criterion')!r}")
    if not isinstance(payload["case_id"], str) or not payload["case_id"]:
        raise RubricSchemaError(f"{criterion} case_id must be a non-empty string")

    elements = payload["required_elements"]
    if not isinstance(elements, list):
        raise RubricSchemaError(f"{criterion} required_elements must be a list")
    for i, e in enumerate(elements):
        if not isinstance(e, dict):
            raise RubricSchemaError(f"{criterion} required_elements[{i}] is not an object")
        emissing = {"element", "status", "evidence_ids", "rationale"} - e.keys()
        if emissing:
            raise RubricSchemaError(f"{criterion} required_elements[{i}] missing keys: {sorted(emissing)}")
        if not isinstance(e["element"], str) or not e["element"].strip():
            raise RubricSchemaError(f"{criterion} required_elements[{i}].element must be a non-empty string")
        if e["status"] not in status_enum:
            raise RubricSchemaError(f"{criterion} required_elements[{i}].status invalid: {e['status']!r}")
        _check_evidence_id_shape(e["evidence_ids"], evidence_criterion_for_ids,
                                  f"{criterion} required_elements[{i}]")
        _check_no_identity_leak(e["element"], f"{criterion} required_elements[{i}].element")
        _check_no_identity_leak(e["rationale"], f"{criterion} required_elements[{i}].rationale")

    overall = payload["overall_rationale"]
    if not isinstance(overall, str):
        raise RubricSchemaError(f"{criterion} overall_rationale must be a string")
    _check_no_identity_leak(overall, f"{criterion} overall_rationale")


def validate_f4_response(payload: dict[str, Any]) -> None:
    _validate_required_elements_response(payload, "F4", F4_ELEMENT_STATUSES, evidence_criterion_for_ids="F2")


def validate_f5_response(payload: dict[str, Any]) -> None:
    # F5 elements may cite SYS_* (system evidence supports it) - reuse the F5 alt-pattern path
    # in _check_evidence_id_shape by passing criterion="F5" itself (its own SYS_*-or-AUTH_* rule).
    _validate_required_elements_response(payload, "F5", F5_ELEMENT_STATUSES, evidence_criterion_for_ids="F5")


# ---------------------------------------------------------------------------------------------
# Section 22: deterministic derived metrics - never taken from the model's own arithmetic
# ---------------------------------------------------------------------------------------------

def derive_f1_verdict(payload: dict[str, Any]) -> Literal["PASS", "FAIL"]:
    """F1 PASS iff every claim is SUPPORTED (vacuously PASS if the draft asserts zero material
    claims). Call validate_f1_response(payload) first - this trusts claim shape, not content."""
    claims = payload["claims"]
    return "PASS" if all(c["verdict"] == "SUPPORTED" for c in claims) else "FAIL"


def derive_f4_outcome(payload: dict[str, Any]) -> tuple[Literal["PASS", "FAIL", "NOT_JUDGEABLE"], str]:
    """PASS iff every required element is PRESENT_CORRECT. Zero elements (authority establishes
    no clear defining core) -> NOT_JUDGEABLE, matching the original holistic prompt's own
    "if AUTHORITY CONTEXT does not establish a clear defining core, return NOT_JUDGEABLE" rule,
    now derived from the element list's emptiness instead of asked for directly.
    Call validate_f4_response(payload) first."""
    elements = payload["required_elements"]
    if not elements:
        return "NOT_JUDGEABLE", "NONE"
    statuses = [e["status"] for e in elements]
    if all(s == "PRESENT_CORRECT" for s in statuses):
        return "PASS", "NONE"
    has_missing = "MISSING" in statuses
    has_incorrect = "PRESENT_BUT_INCORRECT" in statuses
    if has_missing and has_incorrect:
        return "FAIL", "MISSING_AND_INCORRECT_ELEMENTS"
    if has_missing:
        return "FAIL", "MISSING_REQUIRED_ELEMENT"
    return "FAIL", "INCORRECT_REQUIRED_ELEMENT"


def derive_f5_outcome(payload: dict[str, Any]) -> tuple[Literal["PASS", "FAIL"], str]:
    """PASS iff every required element is SUPPORTED. A zero-element extraction is treated as
    FAIL/NO_TARGET_SUPPORT rather than a vacuous PASS: F5 has no NOT_JUDGEABLE state in this
    design (unlike F4), and a sufficiency judgment that defaults to "yes, sufficient" on a
    degenerate empty extraction would be the dangerous direction of error for a criterion whose
    entire purpose is deciding whether evidence backs the KC - silence about what's required
    must never read as confirmation that what exists is enough.
    Call validate_f5_response(payload) first."""
    elements = payload["required_elements"]
    if not elements:
        return "FAIL", "NO_TARGET_SUPPORT"
    statuses = [e["status"] for e in elements]
    if all(s == "SUPPORTED" for s in statuses):
        return "PASS", "NONE"
    if "WRONG_TARGET_ONLY" in statuses:
        return "FAIL", "WRONG_TARGET_SUPPORT"
    return "FAIL", "MISSING_DEFINING_CONTENT"


@dataclass(frozen=True)
class CriterionOutcomes:
    """One row's F1-F5 outcomes, already reduced to PASS/FAIL/NOT_JUDGEABLE/NOT_APPLICABLE."""

    draft_exists: bool
    f1: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    f2: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    f3: Literal["PASS", "FAIL", "NOT_JUDGEABLE", "NOT_APPLICABLE"]
    f4: Literal["PASS", "FAIL", "NOT_JUDGEABLE", "NOT_APPLICABLE"]
    f5: Literal["PASS", "FAIL"]


def not_applicable_outcomes(f5: Literal["PASS", "FAIL"]) -> CriterionOutcomes:
    """Section 31: an empty/abstained draft gets F1-F4 = NOT_APPLICABLE deterministically,
    without ever calling the judge model for those four criteria. F5 is independent of whether
    a draft exists (it judges the evidence, not the draft) and must still be supplied."""
    return CriterionOutcomes(
        draft_exists=False, f1="NOT_APPLICABLE", f2="NOT_APPLICABLE",
        f3="NOT_APPLICABLE", f4="NOT_APPLICABLE", f5=f5,
    )


def materially_sound(outcomes: CriterionOutcomes) -> bool:
    return (
        outcomes.draft_exists
        and outcomes.f1 == "PASS"
        and outcomes.f2 == "PASS"
        and outcomes.f3 == "PASS"
        and outcomes.f4 == "PASS"
    )


def justified_abstention(outcomes: CriterionOutcomes) -> bool:
    return (not outcomes.draft_exists) and outcomes.f5 == "FAIL"


def avoidable_abstention(outcomes: CriterionOutcomes) -> bool:
    return (not outcomes.draft_exists) and outcomes.f5 == "PASS"


def safe_outcome(outcomes: CriterionOutcomes) -> bool:
    return materially_sound(outcomes) or justified_abstention(outcomes)


def unsafe_draft(outcomes: CriterionOutcomes) -> bool:
    return outcomes.draft_exists and (
        outcomes.f1 == "FAIL" or outcomes.f2 == "FAIL" or outcomes.f3 == "FAIL"
    )
