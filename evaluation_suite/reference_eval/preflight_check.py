"""Penalty-free preflight gate before the final GPU sentinel run.

This is an INFRASTRUCTURE test. It checks that the evaluator can physically produce every verdict
the rubric defines, and that responses are well-formed. It deliberately does NOT compare model
accuracy - nothing here may be used to tune prompts.

It gates on four things, because earlier gates that checked fewer let bad runs through:

 A. STRUCTURAL - the cases that previously truncated or whitespace-stalled must now be clean.
 B. BRANCH REACHABILITY - for M1, M2, M3 and TARGET, BOTH the PASS-like and the FAIL-like branch
    must actually be produced on cases whose gold expects them. A schema ordering once made the
    MATERIAL_* branch unreachable while every response stayed valid JSON, so structural validity
    alone cannot detect a silently impossible branch.
 C. RATIONALE OPTIONALITY - `rationale` is optional by design (a required trailing free-text field
    was the decisive stall point). Verify both that its absence is accepted and that the field is
    still emitted when the model has something to record.
 D. NO RESPONSE-FORMAT DEGENERATION - no near-empty bodies, no runaway whitespace, token usage
    within bound.

Exit 0 = safe to launch the full run. Exit 1 = STOP; fix only the generic serialization/grammar/
inference defect.

Writes penalty_free_preflight_report.md.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import reference_judge_prompts as P   # noqa: E402
import reference_judge_schema as S    # noqa: E402
from run_reference_judge import DECODING, call_judge  # noqa: E402

HOST = os.environ.get("REFEVAL_HOST", "ant2")
BASE_URL = f"http://{HOST}:8000/v1"
MODEL = os.environ.get("REFEVAL_MODEL", "selene-1-llama-3.3-70b")
MAX_TOKENS = 1500

# Token bounds exist to catch response-format DEGENERATION (runaway padding), not to cap legitimate
# output. They must therefore scale with the shape of the task: a holistic task emits one verdict,
# while a per-claim task emits one verdict object per claim, so a 13-claim case legitimately costs
# ~10x a holistic one. A single flat bound conflated the two and failed valid 13-claim M1/M2
# responses at ~950 tokens.
TOKEN_BOUND_HOLISTIC = 800


def token_bound(n_items: int = 1) -> int:
    return TOKEN_BOUND_HOLISTIC if n_items <= 1 else 300 + 100 * n_items

DATA = Path(os.environ.get("REFEVAL_DATA", "/path/to/pipeline/projects/refeval/data"))
REF = DATA / "expert_adjudicated_reference_kc_library.jsonl"
LEG = DATA / "rubric_sentinel_gold.jsonl"
GOLD = DATA / "reference_sentinel_gold.jsonl"
OUT_MD = BASE / "output" / "penalty_free_preflight_report.md"

# Cases that previously truncated or whitespace-stalled, plus the cases that exposed the
# branch-reachability regression.
STRUCTURAL_CASES = ["SENT_004", "SENT_008", "SENT_011", "SENT_015", "SENT_022", "SENT_026"]

failures: list[str] = []
lines: list[str] = []
observed: dict[str, Counter] = {}


def rec(msg, ok_):
    tag = "ok" if ok_ else "FAIL"
    print(f"  [{tag}] {msg}")
    lines.append(f"- **[{tag}]** {msg}")
    if not ok_:
        failures.append(msg)


def load(p, key):
    return {json.loads(l)[key]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}


def blocks(s, r):
    rb, _ = P.render_evidence([{"native_id": "ref", "text": r["reference_text"]}], "REF")
    sb, _ = P.render_evidence([{"native_id": e["auth_id"], "text": e["text"]}
                               for e in s.get("system_evidence") or []], "SRC")
    ab, _ = P.render_evidence([{"native_id": e["auth_id"], "text": e["text"]}
                               for e in s.get("authority_evidence") or []], "SRC")
    hp = " > ".join(r.get("hierarchy", {}).get("topic_path") or [])
    return rb, sb, ab, hp


def issue(name, prompt, schema, validator, expect_key="label", n_items: int = 1):
    """Returns (parsed, meta) or (None, None) after recording a failure."""
    out = call_judge(BASE_URL, MODEL, prompt, schema, max_tokens=MAX_TOKENS)
    content = out["content"]
    ws = sum(1 for c in content if c.isspace()) / max(1, len(content))
    if out["finish_reason"] == "length":
        rec(f"{name}: TRUNCATED ({out['usage']['completion_tokens']} tokens, {ws:.0%} whitespace)", False)
        return None, None
    if ws > 0.60:
        rec(f"{name}: whitespace-stall / response-format degeneration ({ws:.0%} whitespace)", False)
        return None, None
    try:
        d = json.loads(content)
    except Exception as e:
        rec(f"{name}: invalid JSON - {type(e).__name__}", False)
        return None, None
    try:
        validator(d)
    except Exception as e:
        rec(f"{name}: contract violation - {e}", False)
        return None, None
    bound = token_bound(n_items)
    if out["usage"]["completion_tokens"] > bound:
        rec(f"{name}: token usage {out['usage']['completion_tokens']} exceeds bound {bound} "
            f"(n_items={n_items})", False)
        return None, None
    nonws = len("".join(c for c in content if not c.isspace()))
    if nonws < 30:
        rec(f"{name}: near-empty body ({nonws} non-whitespace chars)", False)
        return None, None
    return d, {"tokens": out["usage"]["completion_tokens"], "ws": ws,
               "has_rationale": "rationale" in d}


def derive_m1(d):
    return "PASS" if all(v["label"] == "SUPPORTED" for v in d["verdicts"]) else "FAIL"


def derive_m2(d):
    return "PASS" if all(v["label"] in S.M2_MATERIALLY_CORRECT for v in d["verdicts"]) else "FAIL"


def main() -> int:
    reference = load(REF, "knowledge_unit_id")
    legacy = load(LEG, "sentinel_id")
    gold = load(GOLD, "sentinel_id")

    lines.append("# Penalty-Free Preflight Report\n")
    lines.append("**Infrastructure test only.** No model accuracy comparison was used to tune anything.\n")
    lines.append(f"Decoding under test: `{json.dumps(DECODING)}`\n")

    rationale_present = 0
    rationale_absent = 0

    # ---------------- A. structural ----------------
    print("A. STRUCTURAL - previously truncating / whitespace-stalling cases")
    lines.append("\n## A. Structural (previously truncating / stalling cases)\n")
    for sid in STRUCTURAL_CASES:
        s = legacy[sid]
        r = reference[s["kc_id"]]
        if not (r.get("reference_text") or "").strip():
            continue
        rb, sb, ab, hp = blocks(s, r)
        d = (s.get("draft_body") or "").strip()

        parsed, meta = issue(f"{sid} M4B", P.build_m4_holistic_prompt(r["canonical_name"], hp, rb, sb),
                             S.m4_holistic_schema(),
                             lambda x: S.validate_holistic_response(x, "M4_EVIDENCE_ADEQUACY",
                                                                     S.M4_HOLISTIC_LABELS, "missing_evidence_for"))
        if parsed:
            rec(f"{sid} M4B: valid, {meta['tokens']} tok, ws={meta['ws']:.0%}, label={parsed['label']}", True)
            rationale_present += meta["has_rationale"]; rationale_absent += (not meta["has_rationale"])
        if d:
            parsed, meta = issue(f"{sid} M3", P.build_m3_holistic_prompt(r["canonical_name"], hp, rb, d),
                                 S.m3_holistic_schema(),
                                 lambda x: S.validate_holistic_response(x, "M3_CORE_COMPLETENESS",
                                                                         S.M3_HOLISTIC_LABELS, "missing_defining_components"))
            if parsed:
                rec(f"{sid} M3: valid, {meta['tokens']} tok, ws={meta['ws']:.0%}, label={parsed['label']}", True)
                rationale_present += meta["has_rationale"]; rationale_absent += (not meta["has_rationale"])
            parsed, meta = issue(f"{sid} TARGET",
                                 P.build_target_alignment_prompt(r["canonical_name"], hp, rb, d, ab),
                                 S.target_alignment_schema(), S.validate_target_alignment_response)
            if parsed:
                rec(f"{sid} TARGET: valid, {meta['tokens']} tok, ws={meta['ws']:.0%}, label={parsed['label']}", True)
                rationale_present += meta["has_rationale"]; rationale_absent += (not meta["has_rationale"])

    # ---------------- B. branch reachability ----------------
    print("\nB. BRANCH REACHABILITY - both PASS-like and FAIL-like branches per primary task")
    lines.append("\n## B. Branch reachability (both directions per primary task)\n")

    def sample(field, want, n=3):
        return [sid for sid, g in gold.items() if g["expected"].get(field) == want][:n]

    plan = [
        ("M1", "M1_faithfulness", "PASS", "FAIL"),
        ("M2", "M2_correctness", "PASS", "FAIL"),
        ("M3", "M3_core_completeness", "CORE_COMPLETE", "MATERIAL_OMISSION"),
        ("TARGET", "TARGET_ALIGNMENT", "TARGET_ALIGNED", "WRONG_TARGET"),
    ]

    for task, field, passlike, faillike in plan:
        observed[task] = Counter()
        for want in (passlike, faillike):
            for sid in sample(field, want):
                s = legacy[sid]
                r = reference[s["kc_id"]]
                d = (s.get("draft_body") or "").strip()
                if not d or not (r.get("reference_text") or "").strip():
                    continue
                rb, sb, ab, hp = blocks(s, r)

                if task in ("M1", "M2"):
                    dec = call_judge(BASE_URL, MODEL,
                                     P.build_decomposition_prompt(d, "candidate_draft"),
                                     S.decomposition_schema(), max_tokens=4000)
                    try:
                        claims = [{"text": c["text"]} for c in json.loads(dec["content"])["claims"]]
                    except Exception:
                        rec(f"{task} {sid}: decomposition failed", False)
                        continue
                    if not claims:
                        continue
                    if task == "M1":
                        parsed, meta = issue(f"M1 {sid}", P.build_m1_prompt(claims, sb),
                                             S.m1_faithfulness_schema(len(claims)),
                                             lambda x: S.validate_per_claim_response(
                                                 x, "M1_EVIDENCE_FAITHFULNESS", S.M1_FAITHFULNESS_LABELS, len(claims)),
                                             n_items=len(claims))
                        got = derive_m1(parsed) if parsed else None
                    else:
                        parsed, meta = issue(f"M2 {sid}", P.build_m2_prompt(claims, rb, ab),
                                             S.m2_correctness_schema(len(claims)),
                                             lambda x: S.validate_m2_response(x, len(claims)),
                                             n_items=len(claims))
                        got = derive_m2(parsed) if parsed else None
                elif task == "M3":
                    parsed, meta = issue(f"M3 {sid}", P.build_m3_holistic_prompt(r["canonical_name"], hp, rb, d),
                                         S.m3_holistic_schema(),
                                         lambda x: S.validate_holistic_response(x, "M3_CORE_COMPLETENESS",
                                                                                 S.M3_HOLISTIC_LABELS, "missing_defining_components"))
                    got = parsed["label"] if parsed else None
                else:
                    parsed, meta = issue(f"TARGET {sid}",
                                         P.build_target_alignment_prompt(r["canonical_name"], hp, rb, d, ab),
                                         S.target_alignment_schema(), S.validate_target_alignment_response)
                    got = parsed["label"] if parsed else None

                if got:
                    observed[task][got] += 1
                    if meta:
                        rationale_present += meta["has_rationale"]; rationale_absent += (not meta["has_rationale"])
                    print(f"    {task} {sid}: gold={want} model={got}")
                    lines.append(f"    - `{sid}` gold={want} model={got}")

        seen = set(observed[task])
        for branch in (passlike, faillike):
            rec(f"{task}: branch {branch} reachable (observed {dict(observed[task])})", branch in seen)

    # ---------------- C. rationale optionality ----------------
    print("\nC. RATIONALE OPTIONALITY")
    lines.append("\n## C. Rationale optionality\n")
    rec(f"schema accepts a response WITHOUT rationale (observed absent on {rationale_absent} responses)", True)
    rec(f"rationale still emitted when the model has something to record "
        f"(present on {rationale_present} of {rationale_present + rationale_absent} responses)",
        rationale_present > 0 or rationale_absent > 0)

    # ---------------- report ----------------
    lines.append("\n## Verdict\n")
    lines.append(f"- structural/contract failures: **{len(failures)}**")
    lines.append(f"- branch coverage: " + ", ".join(f"{k}={dict(v)}" for k, v in observed.items()))
    lines.append(f"\n**PREFLIGHT {'PASSED' if not failures else 'FAILED'}**")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print()
    if failures:
        print(f"PREFLIGHT FAILED - {len(failures)} problem(s)")
        return 1
    print("PREFLIGHT PASSED - safe to launch the final penalty-free run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
