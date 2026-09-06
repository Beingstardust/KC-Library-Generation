"""Proves the reference-based judge schemas are ENFORCED by vLLM 0.27.1 + XGrammar, by compiling
them and inspecting the emitted EBNF - not by assuming that 'compiles without error' means
'constrains output'.

Must be run on a host with xgrammar installed (Cluster A: ~/projects/selene_judge/.venv). No GPU needed.

    ssh Cluster A "cd ~/projects/selene_judge && source .venv/bin/activate && python eval_code/test_grammar_enforcement.py"

Why this test exists: during the Selene v3 development work, JSON-Schema if/then/else was found to
compile cleanly while being silently dropped from the grammar, so a verdict/reason binding that
looked enforced was not. Every conditional binding in the reference-based schemas therefore uses
oneOf, and this test re-verifies that choice against the pinned toolchain rather than trusting the
earlier finding to still hold.
"""
import json
import re
import sys

import xgrammar as xgr

sys.path.insert(0, "/path/to/pipeline/projects/selene_judge/eval_code")
import reference_judge_schema as S

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def grammar_of(schema) -> str:
    return str(xgr.Grammar.from_json_schema(json.dumps(schema)))


def root_rules(g: str) -> str:
    return "\n".join(l for l in g.splitlines() if l.startswith("root"))


# ---------------------------------------------------------------------------
print("=" * 72)
print("CONTROL: if/then/else must be shown to be IGNORED (justifies using oneOf)")
print("=" * 72)
ifthen = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": ["A", "B"]},
                    "note": {"type": "string", "enum": ["x", "y"]}},
    "required": ["label", "note"], "additionalProperties": False,
    "if": {"properties": {"label": {"const": "A"}}},
    "then": {"properties": {"note": {"const": "x"}}},
}
g = root_rules(grammar_of(ifthen))
print(g)
# if if/then were enforced there would be two alternative root cases; instead both enums stay open
both_labels_one_rule = bool(re.search(r'root_prop_0 ::= \(\("\\"A\\""\) \| \("\\"B\\""\)\)', g))
both_notes_one_rule = bool(re.search(r'root_prop_1 ::= \(\("\\"x\\""\) \| \("\\"y\\""\)\)', g))
check("if/then produces NO case split (i.e. it is ignored, as expected)",
      both_labels_one_rule and both_notes_one_rule,
      "expected a single open enum for each property")
check("if/then control has no root_case_* alternatives", "root_case_" not in g)

# ---------------------------------------------------------------------------
print()
print("=" * 72)
print("M2: oneOf must hard-bind each label to the evidence-id family it may cite")
print("=" * 72)
g2 = root_rules(grammar_of(S.m2_correctness_schema(1)))
print(g2)

check("M2 emits three separate oneOf cases",
      all(f"root_prop_1_additional_case_{i} ::=" in g2 for i in (0, 1, 2)))
check("M2 case_0 (CORRECT/CONTRADICTED) is bound to REF_ ids",
      '"R" "E" "F" "_"' in g2 and 'case_0_prop_1 ::= (("\\"CORRECT\\"") | ("\\"CONTRADICTED\\""))' in g2)
check("M2 case_1 (REFERENCE_SILENT_BUT_SOURCE_SUPPORTED) is bound to SRC_ ids",
      '"S" "R" "C" "_"' in g2 and 'case_1_prop_1 ::= (("\\"REFERENCE_SILENT_BUT_SOURCE_SUPPORTED\\""))' in g2)
check("M2 case_2 (NOT_SUPPORTED_BY_AUTHORITY) can only emit an EMPTY evidence array",
      bool(re.search(r'case_2_prop_2 ::= \(\("\[" \[ \\n\\t\]\* "\]"\)\)', g2)))
check("M2 root alternates over exactly the three cases",
      "root_prop_1_additional ::= ((root_prop_1_additional_case_0) | (root_prop_1_additional_case_1) | (root_prop_1_additional_case_2))" in g2)

# ---------------------------------------------------------------------------
print()
print("=" * 72)
print("Exact-length arrays: minItems == maxItems == N must compile to exact repetition")
print("=" * 72)
_REP_RE = re.compile(r"\{\d+, \d+\}")
for n in (2, 3, 7, 12):
    g3 = grammar_of(S.m1_faithfulness_schema(n))
    # the array is one item followed by exactly (n-1) repetitions of ", item"
    expected = "{%d, %d}" % (n - 1, n - 1)
    found = _REP_RE.findall(g3)
    check(f"n_claims={n} compiles to exact repetition {expected}", expected in g3,
          "repetitions found: %s" % found)

# ---------------------------------------------------------------------------
print()
print("=" * 72)
print("All remaining schemas compile")
print("=" * 72)
for name, sch in [
    ("m1_faithfulness_schema(3)", S.m1_faithfulness_schema(3)),
    ("m3_claim_coverage_schema(3)", S.m3_claim_coverage_schema(3)),
    ("m3_holistic_schema", S.m3_holistic_schema()),
    ("m4_retrieval_coverage_schema(4)", S.m4_retrieval_coverage_schema(4)),
    ("m4_holistic_schema", S.m4_holistic_schema()),
    ("target_alignment_schema", S.target_alignment_schema()),
    ("decomposition_schema", S.decomposition_schema()),
]:
    try:
        grammar_of(sch)
        check(f"{name} compiles", True)
    except Exception as e:
        check(f"{name} compiles", False, f"{type(e).__name__}: {e}")

print()
print(f"{len(FAILURES)} failure(s): {FAILURES}" if FAILURES else "ALL GRAMMAR ENFORCEMENT CHECKS PASSED")
sys.exit(1 if FAILURES else 0)
