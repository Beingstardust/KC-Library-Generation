"""JSON schemas for the reference-based judge tasks (M1-M4 + target alignment + decomposition).

Carries forward three empirically-established constraints from the Selene v3 development work
(see evaluation_suite/final_pipeline/output/r9_final/source_artifact_manifest.json):

 1. `oneOf` discriminated unions ARE enforced by vLLM 0.27.1 + XGrammar; `if/then/else` is
    SILENTLY IGNORED. Anywhere a label must bind to other fields, use oneOf.
 2. `minItems == maxItems == N` compiles to an exact repetition operator and IS enforced, so
    per-claim verdict arrays can be pinned to exactly the number of claims sent.
 3. Never ask the model for an aggregate it can be derived from - every per-KC metric in this
    evaluation is computed in Python from per-claim labels (reference_metrics.py).

Every judged unit is POINTWISE: one claim (or one KC) against one target, never a ranking and
never a side-by-side of two systems. This is what makes blinding meaningful - the judge cannot
know which arm produced what, because it never sees two arms at once.
"""
from __future__ import annotations

# ---- label domains (spec sections 8-9) ------------------------------------
M1_FAITHFULNESS_LABELS = ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED")
M2_CORRECTNESS_LABELS = ("CORRECT", "CONTRADICTED", "NOT_SUPPORTED_BY_AUTHORITY", "REFERENCE_SILENT_BUT_SOURCE_SUPPORTED")
M3_CLAIM_COVERAGE_LABELS = ("PRESENT", "ABSENT", "PARTIALLY_PRESENT")
M3_HOLISTIC_LABELS = ("CORE_COMPLETE", "MATERIAL_OMISSION", "NOT_JUDGEABLE")
M4_RETRIEVAL_LABELS = ("SUPPORTED_BY_RETRIEVAL", "NOT_SUPPORTED_BY_RETRIEVAL")
M4_HOLISTIC_LABELS = ("EVIDENCE_ADEQUATE", "MATERIAL_EVIDENCE_GAP", "NOT_JUDGEABLE")
TARGET_LABELS = ("TARGET_ALIGNED", "WRONG_TARGET", "NOT_JUDGEABLE")

# Labels counted as materially correct for M2 (spec section 8/M2). The
# REFERENCE_SILENT_BUT_SOURCE_SUPPORTED escape path is mandatory: it is what stops the
# Qwen-seeded reference's content boundary from becoming the sole definition of correctness.
M2_MATERIALLY_CORRECT = ("CORRECT", "REFERENCE_SILENT_BUT_SOURCE_SUPPORTED")

EVIDENCE_ID_PATTERN = r"^(SRC|REF)_[0-9]{3,4}$"

# Cap on how many missing defining components a holistic MATERIAL_* verdict may enumerate.
MAX_MISSING_ITEMS = 8

# Every free-text field is length-bounded. This is not cosmetic: an UNBOUNDED trailing string is
# the mechanism behind the truncation failures observed on this stack. In the holistic and target
# schemas `rationale` is the final field, so after it only "}" remains - nothing forces the model
# to stop, and it wrote until it exhausted the token budget on roughly a third of those calls,
# while the per-claim array tasks (where each rationale is followed by more required structure)
# were unaffected.
# maxLength is genuinely enforced here: it compiles to a bounded repetition, and the emitted
# character class excludes carriage-return and newline, so a bounded string also cannot be
# padded with newlines.
MAX_RATIONALE_CHARS = 600
MAX_SHORT_TEXT_CHARS = 240


class JudgeSchemaError(ValueError):
    pass

# ---------------------------------------------------------------------------
# METRIC SCOPE REGISTRY (EVALUATION_SCOPE_AMENDMENT_v2)
# M4 was split after development sentinels showed the holistic evidence-adequacy
# classifier systematically treating the full expert reference as a mandatory checklist -
# the same construct-validity failure previously seen in the v3 F4/F5 design. The decomposed
# retrieval question survives; the holistic counterfactual does not.
# This registry is consumed by the analysis and metric layers so a demoted task cannot be
# silently picked up as a production metric.
# ---------------------------------------------------------------------------
METRIC_SCOPE = {
    "M1_EVIDENCE_FAITHFULNESS": {
        "primary_use": True, "qualification_gate": True, "derived_metric_dependency": True,
    },
    "M2_REFERENCE_SOURCE_CORRECTNESS": {
        "primary_use": True, "qualification_gate": True, "derived_metric_dependency": True,
    },
    "M3_CORE_COMPLETENESS": {
        "primary_use": True, "qualification_gate": True, "derived_metric_dependency": True,
    },
    "M3_REFERENCE_CLAIM_COVERAGE": {
        "primary_use": True, "qualification_gate": False, "derived_metric_dependency": False,
        "note": "descriptive continuous coverage measure; deliberately NOT converted into an "
                "all-or-nothing completeness verdict.",
    },
    "TARGET_ALIGNMENT": {
        "primary_use": True, "qualification_gate": True, "derived_metric_dependency": True,
    },
    # M4A - retained as THE retrieval coverage metric
    "M4_RETRIEVAL_REFERENCE_COVERAGE": {
        "primary_use": True, "qualification_gate": True, "derived_metric_dependency": False,
        "metric": "retrieval_reference_recall",
        "note": "Upstream retrieval diagnostic. NOT a condition of materially_sound - that flag "
                "measures the final KC draft, and retrieval coverage explains it rather than "
                "defining it. Must not be relabelled 'evidence sufficiency' except descriptively: "
                "a system may retrieve well under 100% of reference content and still hold enough "
                "to draft a correct KC.",
    },
    # M4B - DEMOTED
    "EXPLORATORY_HOLISTIC_EVIDENCE_ADEQUACY": {
        "primary_use": False, "qualification_gate": False, "derived_metric_dependency": False,
        "deprecated_as_primary_utc": "2026-08-25",
        "former_name": "M4_EVIDENCE_ADEQUACY",
        "reason": "Development sentinels showed the judge treating the full expert reference as an "
                  "exhaustive checklist, returning MATERIAL_EVIDENCE_GAP whenever any reference "
                  "detail was absent even when the evidence was already sufficient to draft an "
                  "adequate KC. Same construct-validity failure as the earlier F5 design.",
        "permitted_uses": ["exploratory diagnostic", "optional human-calibration research output"],
        "forbidden_uses": ["primary metric", "materially_sound", "judge qualification gating",
                            "intrinsic comparison", "extrinsic comparison",
                            "system success/failure classification", "automatic abstention validity"],
    },
}

EXPLORATORY_TASKS = frozenset(
    k for k, v in METRIC_SCOPE.items() if not v["primary_use"]
)


def assert_primary(task: str) -> None:
    """Guard for any code path that would consume a task as a production metric."""
    scope = METRIC_SCOPE.get(task)
    if scope is None:
        raise JudgeSchemaError(f"unknown task {task!r} - not in METRIC_SCOPE")
    if not scope["primary_use"]:
        raise JudgeSchemaError(
            f"{task} is EXPLORATORY ONLY (demoted {scope.get('deprecated_as_primary_utc')}): "
            f"{scope.get('reason', '')} Forbidden uses: {scope.get('forbidden_uses')}"
        )



def _per_claim_array(item_schema: dict, n_claims: int) -> dict:
    """Exact-length array. minItems==maxItems is verified-enforced by XGrammar."""
    return {
        "type": "array",
        "items": item_schema,
        "minItems": n_claims,
        "maxItems": n_claims,
    }


def _labeled_item(label_field: str, labels: tuple, extra_required: dict | None = None) -> dict:
    props = {
        "claim_index": {"type": "integer"},
        label_field: {"type": "string", "enum": list(labels)},
        "evidence_ids": {"type": "array", "items": {"type": "string", "pattern": EVIDENCE_ID_PATTERN}},
        "rationale": {"type": "string", "maxLength": MAX_RATIONALE_CHARS},
    }
    if extra_required:
        props.update(extra_required)
    return {
        "type": "object",
        "properties": props,
        "required": ["claim_index", label_field, "evidence_ids", "rationale"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# M1 - evidence faithfulness: candidate claims -> candidate system evidence
# ---------------------------------------------------------------------------
def m1_faithfulness_schema(n_claims: int) -> dict:
    if n_claims < 1:
        raise JudgeSchemaError("m1 schema requires at least one claim")
    return {
        "type": "object",
        "properties": {
            "task": {"type": "string", "enum": ["M1_EVIDENCE_FAITHFULNESS"]},
            "verdicts": _per_claim_array(_labeled_item("label", M1_FAITHFULNESS_LABELS), n_claims),
        },
        "required": ["task", "verdicts"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# M2 - reference/source correctness: candidate claims -> reference + source authority
# oneOf binds the label to what the judge must cite:
#   CORRECT / CONTRADICTED            -> must cite the REFERENCE (REF_*)
#   REFERENCE_SILENT_BUT_SOURCE_SUPPORTED -> must cite SOURCE authority (SRC_*)
#   NOT_SUPPORTED_BY_AUTHORITY        -> cites nothing (that IS the finding)
# This makes "the reference is silent but the source backs it" impossible to assert without
# pointing at the actual source passage that backs it.
# ---------------------------------------------------------------------------
def _m2_item() -> dict:
    def branch(labels: list, id_pattern: str | None, allow_empty: bool) -> dict:
        ev = ({"type": "array", "items": {"type": "string", "pattern": id_pattern}, "minItems": 1}
              if id_pattern else {"type": "array", "items": {"type": "string"}, "maxItems": 0})
        return {
            "type": "object",
            "properties": {
                "claim_index": {"type": "integer"},
                "label": {"type": "string", "enum": labels},
                "evidence_ids": ev,
                "rationale": {"type": "string", "maxLength": MAX_RATIONALE_CHARS},
            },
            "required": ["claim_index", "label", "evidence_ids", "rationale"],
            "additionalProperties": False,
        }

    return {
        "oneOf": [
            branch(["CORRECT", "CONTRADICTED"], r"^REF_[0-9]{3,4}$", False),
            branch(["REFERENCE_SILENT_BUT_SOURCE_SUPPORTED"], r"^SRC_[0-9]{3,4}$", False),
            branch(["NOT_SUPPORTED_BY_AUTHORITY"], None, True),
        ]
    }


def m2_correctness_schema(n_claims: int) -> dict:
    if n_claims < 1:
        raise JudgeSchemaError("m2 schema requires at least one claim")
    return {
        "type": "object",
        "properties": {
            "task": {"type": "string", "enum": ["M2_REFERENCE_SOURCE_CORRECTNESS"]},
            "verdicts": _per_claim_array(_m2_item(), n_claims),
        },
        "required": ["task", "verdicts"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# M3 - reference completeness. Two SEPARATE calls, never one:
#   (a) per-reference-claim coverage  -> continuous descriptive measure
#   (b) holistic core-completeness    -> the judgment that decides material omission
# They are separate because the spec requires that CORE_COMPLETE must NOT require 100% claim
# coverage; deriving one from the other would collapse that distinction.
# ---------------------------------------------------------------------------
def m3_claim_coverage_schema(n_claims: int) -> dict:
    if n_claims < 1:
        raise JudgeSchemaError("m3 coverage schema requires at least one reference claim")
    return {
        "type": "object",
        "properties": {
            "task": {"type": "string", "enum": ["M3_REFERENCE_CLAIM_COVERAGE"]},
            "verdicts": _per_claim_array(_labeled_item("label", M3_CLAIM_COVERAGE_LABELS), n_claims),
        },
        "required": ["task", "verdicts"],
        "additionalProperties": False,
    }


def _holistic_schema(task: str, material_label: str, clean_label: str, list_field: str) -> dict:
    """oneOf-bound holistic judgment.

    Two properties of this shape matter and were both established empirically:

    0. FIELD ORDER: `label` comes FIRST, and this is load-bearing for SEMANTICS, not just for
       serialization. A rationale-first / label-last variant was tried and had to be reverted: with
       the verdict last, the model must select the oneOf branch by choosing the NEXT KEY after the
       rationale, i.e. it has to commit to the material branch by emitting the list key BEFORE it
       has articulated a verdict. It essentially always took the shorter clean-branch path instead.
       Measured on the full 36-case suite: label-last produced ZERO MATERIAL_OMISSION verdicts
       (21 CORE_COMPLETE, 12 NOT_JUDGEABLE) where label-first produced a sane 19/14 split, and
       likewise zero MATERIAL_EVIDENCE_GAP where label-first produced 24. Putting the label first
       makes the branch selectable by the verdict token itself. Trailing-rationale stalls are
       handled by bounding every free-text field with maxLength instead.

    0b. `rationale` is OPTIONAL, not required. It is the last field, and a REQUIRED trailing
       free-text field is precisely where the model stalls: having already committed its verdict it
       has nothing further to say, but the grammar forces it to open a rationale string, and
       whitespace is a legal continuation. Making it optional lets the model close the object
       instead. Every string in these schemas is length-bounded and its character class excludes
       newlines, so all remaining whitespace is inter-token and semantically empty - nothing is
       lost by allowing an early close. Labels are what the metrics consume; the rationale is for
       auditability and is still emitted whenever the model has something to record.

    1. The LIST must not come first either. With the list first, the model reliably fell into a
       whitespace-padding loop - the compiled grammar permits unlimited `[ \\n\\t]*` between tokens,
       and with nothing contentful yet committed the model emitted 3000 tokens of indentation and
       hit the length limit. Putting a decision first ends the loop; verified against the live
       server (142 tokens, clean stop, vs 3000-token truncation).

    2. oneOf binds the label to the list's cardinality at the GRAMMAR level rather than leaving it
       to post-hoc validation: a MATERIAL_* verdict cannot be emitted without naming what is
       missing, and a clean verdict cannot be emitted with a non-empty list.

    The MATERIAL_* branch is also capped at MAX_MISSING_ITEMS. Left uncapped, the model ran the
    list on indefinitely - one observed M4 response enumerated missing items until it hit the token
    limit mid-string at 8.8k characters. The cap is semantic as well as practical: the question is
    which DEFINING components are absent, and past a handful the verdict is not in doubt.
    """
    def material_branch(labels: list) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "enum": [task]},
                "label": {"type": "string", "enum": labels},
                list_field: {
                    "type": "array",
                    "items": {"type": "string", "maxLength": MAX_SHORT_TEXT_CHARS},
                    "minItems": 1, "maxItems": MAX_MISSING_ITEMS,
                },
                "rationale": {"type": "string", "maxLength": MAX_RATIONALE_CHARS},
            },
            "required": ["task", "label", list_field],
            "additionalProperties": False,
        }

    def clean_branch(labels: list) -> dict:
        # The list field is OMITTED here rather than required-and-empty. An empty array was a
        # reliable stall point: the model would emit a complete, correct answer up to
        # `"...": []` and then pad whitespace until it exhausted the token budget - 99% of an
        # 8.9k-character response was indentation, with only 87 characters of content. Dropping
        # the field removes that dead end, and it is also the more honest shape: a clean verdict
        # has no missing components, rather than an empty list of them.
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "enum": [task]},
                "label": {"type": "string", "enum": labels},
                "rationale": {"type": "string", "maxLength": MAX_RATIONALE_CHARS},
            },
            "required": ["task", "label"],
            "additionalProperties": False,
        }

    return {"oneOf": [
        material_branch([material_label]),                # must name what is missing, bounded
        clean_branch([clean_label, "NOT_JUDGEABLE"]),     # carries no list at all
    ]}


def m3_holistic_schema() -> dict:
    return _holistic_schema("M3_CORE_COMPLETENESS", "MATERIAL_OMISSION", "CORE_COMPLETE",
                             "missing_defining_components")


# ---------------------------------------------------------------------------
# M4 - retrieval reference coverage: reference claims -> candidate system evidence
# ---------------------------------------------------------------------------
def m4_retrieval_coverage_schema(n_claims: int) -> dict:
    if n_claims < 1:
        raise JudgeSchemaError("m4 schema requires at least one reference claim")
    return {
        "type": "object",
        "properties": {
            "task": {"type": "string", "enum": ["M4_RETRIEVAL_REFERENCE_COVERAGE"]},
            "verdicts": _per_claim_array(_labeled_item("label", M4_RETRIEVAL_LABELS), n_claims),
        },
        "required": ["task", "verdicts"],
        "additionalProperties": False,
    }


def m4_holistic_schema() -> dict:
    return _holistic_schema("M4_EVIDENCE_ADEQUACY", "MATERIAL_EVIDENCE_GAP", "EVIDENCE_ADEQUATE",
                             "missing_evidence_for")


# ---------------------------------------------------------------------------
# Target alignment - reference-based, replacing the retired v3 extract-subject mechanism
# ---------------------------------------------------------------------------
def target_alignment_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "task": {"type": "string", "enum": ["TARGET_ALIGNMENT"]},
            "candidate_central_subject": {"type": "string", "maxLength": MAX_SHORT_TEXT_CHARS},
            "reference_central_subject": {"type": "string", "maxLength": MAX_SHORT_TEXT_CHARS},
            "label": {"type": "string", "enum": list(TARGET_LABELS)},
            "rationale": {"type": "string", "maxLength": MAX_RATIONALE_CHARS},
        },
        # Same label-first rule as the holistic schemas. TARGET is a flat object with no oneOf
        # branch, so it is not exposed to the branch-selection bias that forced the revert there -
        # but one consistent ordering rule across every decision task removes a confound rather
        # than leaving a mixed convention to be explained later. The two subject fields still come
        # first, so the model states what each text is about before it judges whether they match.
        "required": ["task", "candidate_central_subject", "reference_central_subject", "label"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Claim decomposition
# ---------------------------------------------------------------------------
def decomposition_schema() -> dict:
    from reference_claim_schema import CLAIM_TYPES
    return {
        "type": "object",
        "properties": {
            "task": {"type": "string", "enum": ["CLAIM_DECOMPOSITION"]},
            "claims": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "maxLength": 500},
                        "claim_type": {"type": "string", "enum": list(CLAIM_TYPES)},
                        "parent_span": {"type": "string", "maxLength": 1200},
                    },
                    "required": ["text", "claim_type", "parent_span"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["task", "claims"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Response validation - structural (schema-shaped) vs contract (semantic rules)
# ---------------------------------------------------------------------------
def validate_per_claim_response(resp: dict, task: str, labels: tuple, n_claims: int) -> None:
    if resp.get("task") != task:
        raise JudgeSchemaError(f"expected task {task}, got {resp.get('task')!r}")
    verdicts = resp.get("verdicts")
    if not isinstance(verdicts, list):
        raise JudgeSchemaError("verdicts is not a list")
    if len(verdicts) != n_claims:
        raise JudgeSchemaError(f"expected {n_claims} verdicts, got {len(verdicts)}")
    seen = set()
    for v in verdicts:
        idx = v.get("claim_index")
        if not isinstance(idx, int) or not (0 <= idx < n_claims):
            raise JudgeSchemaError(f"claim_index {idx!r} out of range 0..{n_claims-1}")
        if idx in seen:
            raise JudgeSchemaError(f"duplicate claim_index {idx}")
        seen.add(idx)
        if v.get("label") not in labels:
            raise JudgeSchemaError(f"label {v.get('label')!r} not in {labels}")
    if seen != set(range(n_claims)):
        raise JudgeSchemaError(f"verdicts do not cover every claim index exactly once")


def validate_m2_response(resp: dict, n_claims: int) -> None:
    validate_per_claim_response(resp, "M2_REFERENCE_SOURCE_CORRECTNESS", M2_CORRECTNESS_LABELS, n_claims)
    for v in resp["verdicts"]:
        label, ev = v["label"], v.get("evidence_ids") or []
        if label in ("CORRECT", "CONTRADICTED"):
            if not ev or not all(e.startswith("REF_") for e in ev):
                raise JudgeSchemaError(f"{label} must cite at least one REF_* id, got {ev}")
        elif label == "REFERENCE_SILENT_BUT_SOURCE_SUPPORTED":
            if not ev or not all(e.startswith("SRC_") for e in ev):
                raise JudgeSchemaError(f"{label} must cite at least one SRC_* source id, got {ev}")
        elif label == "NOT_SUPPORTED_BY_AUTHORITY":
            if ev:
                raise JudgeSchemaError(f"{label} must cite nothing, got {ev}")


def validate_holistic_response(resp: dict, task: str, labels: tuple, list_field: str) -> None:
    if resp.get("task") != task:
        raise JudgeSchemaError(f"expected task {task}, got {resp.get('task')!r}")
    if resp.get("label") not in labels:
        raise JudgeSchemaError(f"label {resp.get('label')!r} not in {labels}")
    if resp["label"].startswith("MATERIAL_"):
        # a MATERIAL_* finding has to say what is missing, or it is neither actionable nor auditable
        if not isinstance(resp.get(list_field), list):
            raise JudgeSchemaError(f"{resp['label']} requires {list_field} as a list")
        if not resp[list_field]:
            raise JudgeSchemaError(f"{resp['label']} requires a non-empty {list_field}")
    else:
        # clean verdicts carry no list at all (see clean_branch); an empty list is tolerated for
        # backward compatibility with responses produced before the field was dropped, but a
        # NON-empty list contradicts the verdict and is rejected.
        if resp.get(list_field):
            raise JudgeSchemaError(f"{resp['label']} must not name any {list_field}")


def validate_target_alignment_response(resp: dict) -> None:
    if resp.get("task") != "TARGET_ALIGNMENT":
        raise JudgeSchemaError(f"expected TARGET_ALIGNMENT, got {resp.get('task')!r}")
    if resp.get("label") not in TARGET_LABELS:
        raise JudgeSchemaError(f"label {resp.get('label')!r} not in {TARGET_LABELS}")
    for f in ("candidate_central_subject", "reference_central_subject"):
        if not (resp.get(f) or "").strip():
            raise JudgeSchemaError(f"{f} must be non-empty")
