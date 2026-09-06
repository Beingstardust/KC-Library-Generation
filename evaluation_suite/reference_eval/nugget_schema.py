"""Schemas and prompts for the v2 metrics (OVERHAUL_PROTOCOL_v2.md).

Every structural constraint learned in v1 is applied here, because they were learned the hard way:
  * verdict field FIRST in each branched object - with it last, the model picks its oneOf branch by
    choosing the next key and one branch becomes unreachable (F-02, measured 0/36).
  * rationale OPTIONAL - a required trailing free-text field makes the model open a string it has
    nothing to put in, and whitespace is a legal continuation, so responses run to the token cap
    (F-03).
  * `oneOf` for any conditional binding, never `if/then/else` - the latter compiles cleanly and is
    then silently dropped from the grammar (F-01).
  * every string length-bounded with a character class excluding CR/LF (F-03/F-04).
  * minItems == maxItems for exact-length arrays, which compiles to exact repetition (F-04).

Blinding: these prompts carry no arm, system, drafter or retrieval identity, and are passed through
`assert_blinded()` by the runner exactly as the v1 prompts are.
"""
from __future__ import annotations

MAX_NUGGET_CHARS = 300
MAX_RATIONALE_CHARS = 400
MAX_NUGGETS = 20

NUGGET_IMPORTANCE = ["VITAL", "OKAY"]
NUGGET_SUPPORT = ["SUPPORTED", "PARTIAL", "NOT_SUPPORTED"]
CONTEXT_PRESENCE = ["PRESENT", "PARTIAL", "ABSENT"]


def _bounded_str(n: int) -> dict:
    return {"type": "string", "maxLength": n, "pattern": r"^[^\r\n]*$"}


def nugget_decomposition_schema() -> dict:
    """Decompose a reference into atomic nuggets, each labelled VITAL or OKAY.

    Importance is FIRST in each item so the model commits to it before writing the text, matching
    the field-order lesson from F-02.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["task", "nuggets"],
        "properties": {
            "task": {"type": "string", "enum": ["NUGGET_DECOMPOSITION"]},
            "nuggets": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_NUGGETS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["importance", "text"],
                    "properties": {
                        "importance": {"type": "string", "enum": NUGGET_IMPORTANCE},
                        "text": _bounded_str(MAX_NUGGET_CHARS),
                    },
                },
            },
        },
    }


def _assignment_schema(task_name: str, labels: list[str], n: int) -> dict:
    """Per-nugget verdicts, exactly n of them, verdict first, rationale optional."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["task", "verdicts"],
        "properties": {
            "task": {"type": "string", "enum": [task_name]},
            "verdicts": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["nugget_index", "label"],
                    "properties": {
                        "nugget_index": {"type": "integer", "minimum": 1, "maximum": n},
                        "label": {"type": "string", "enum": labels},
                        "rationale": _bounded_str(MAX_RATIONALE_CHARS),
                    },
                },
            },
        },
    }


def nugget_assignment_schema(n: int) -> dict:
    return _assignment_schema("NUGGET_ASSIGNMENT", NUGGET_SUPPORT, n)


def context_recall_schema(n: int) -> dict:
    return _assignment_schema("CONTEXT_RECALL", CONTEXT_PRESENCE, n)


# ---------------------------------------------------------------- prompts

def build_nugget_decomposition_prompt(canonical: str, hierarchy: str, reference_block: str) -> str:
    return f"""You are decomposing an expert reference description of a knowledge component into atomic factual nuggets.

KNOWLEDGE COMPONENT: {canonical}
LOCATION IN SYLLABUS: {hierarchy}

EXPERT REFERENCE:
{reference_block}

TASK
Break the reference into atomic, self-contained nuggets. Each nugget must state ONE fact and be
understandable without reading the others.

Label each nugget:
  VITAL - a defining component of this knowledge component. A description that omits it is
          materially incomplete: a learner reading only the remaining nuggets would misunderstand
          or be unable to apply the concept.
  OKAY  - accurate and useful, but elaboration, example, or detail rather than definitional. A
          description omitting it is still a correct and usable account of the concept.

Be strict about VITAL. Reserve it for what makes this concept what it is and distinguishes it from
neighbouring concepts. Specific formulae, thresholds or named procedures are VITAL only when the
concept cannot be correctly applied without them.

Do not invent content absent from the reference. Do not merge distinct facts into one nugget.

Return JSON with "task": "NUGGET_DECOMPOSITION" and a "nuggets" array; each item has "importance"
(VITAL or OKAY) then "text"."""


def _numbered(nuggets: list[dict]) -> str:
    return "\n".join(f"{i+1}. [{x['importance']}] {x['text']}" for i, x in enumerate(nuggets))


def build_nugget_assignment_prompt(nuggets: list[dict], draft: str) -> str:
    return f"""You are checking which reference nuggets are conveyed by a candidate description.

NUGGETS (numbered):
{_numbered(nuggets)}

CANDIDATE DESCRIPTION:
{draft}

TASK
For EACH numbered nugget, decide whether the CANDIDATE DESCRIPTION conveys it:
  SUPPORTED     - the description states this fact, or states something that entails it. Wording
                  may differ; meaning must match.
  PARTIAL       - the description gestures at the fact but omits what makes it substantive (for
                  example names a quantity without defining it, or alludes without asserting).
  NOT_SUPPORTED - the description does not convey this fact.

Judge ONLY whether the fact is conveyed. Do NOT judge whether the description is well written, and
do NOT penalise it for containing additional material beyond the nuggets.

Return one verdict per nugget, {len(nuggets)} in total, each with "nugget_index" then "label"."""


def build_context_recall_prompt(nuggets: list[dict], evidence_block: str) -> str:
    return f"""You are checking which reference nuggets are recoverable from a set of retrieved source passages.

NUGGETS (numbered):
{_numbered(nuggets)}

RETRIEVED PASSAGES:
{evidence_block}

TASK
For EACH numbered nugget, decide whether the RETRIEVED PASSAGES contain the information needed to
state it:
  PRESENT - the passages state this fact, or state enough that it follows directly.
  PARTIAL - the passages touch the topic but lack what is needed to assert the fact.
  ABSENT  - the passages do not contain this information.

You are assessing the PASSAGES only. There is no candidate description here and none is implied.
Do not reward or penalise passages for length, ordering, or redundancy - only for whether the
information is present.

Return one verdict per nugget, {len(nuggets)} in total, each with "nugget_index" then "label"."""


# ---------------------------------------------------------------- validation

class NuggetSchemaError(ValueError):
    pass


def validate_decomposition(r: dict) -> bool:
    if r.get("task") != "NUGGET_DECOMPOSITION":
        raise NuggetSchemaError(f"expected NUGGET_DECOMPOSITION, got {r.get('task')!r}")
    ns = r.get("nuggets") or []
    if not ns:
        raise NuggetSchemaError("no nuggets returned")
    for x in ns:
        if x.get("importance") not in NUGGET_IMPORTANCE:
            raise NuggetSchemaError(f"bad importance {x.get('importance')!r}")
    return True


def validate_assignment(r: dict, task_name: str, labels: list[str], n: int) -> bool:
    if r.get("task") != task_name:
        raise NuggetSchemaError(f"expected {task_name}, got {r.get('task')!r}")
    vs = r.get("verdicts") or []
    if len(vs) != n:
        raise NuggetSchemaError(f"expected {n} verdicts, got {len(vs)}")
    seen = set()
    for v in vs:
        if v.get("label") not in labels:
            raise NuggetSchemaError(f"bad label {v.get('label')!r}")
        idx = v.get("nugget_index")
        if not isinstance(idx, int) or not (1 <= idx <= n):
            raise NuggetSchemaError(f"nugget_index out of range: {idx!r}")
        if idx in seen:
            raise NuggetSchemaError(f"duplicate nugget_index {idx}")
        seen.add(idx)
    return True
