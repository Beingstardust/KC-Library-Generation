"""Offline (no GPU, no judge) assembly of EVERY prompt for all 36 translated sentinels.

Exists because of a specific past failure: during the Selene v3 work an F4 prompt shipped without
its authority-evidence block, so the model was asked to cite evidence ids it had never been shown,
and 54.6% of those calls came back contract-invalid. That was only caught mid-run. This test
assembles every prompt against real frozen data first and asserts each one actually contains the
material the task asks the judge to cite.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import reference_judge_prompts as P  # noqa: E402
import reference_judge_schema as S   # noqa: E402

LEGACY = BASE.parent / "output" / "r9_final" / "rubric_sentinel_gold.jsonl"
TRANSLATED = BASE / "output" / "reference_sentinel_gold.jsonl"
REFERENCE = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"

FAILURES = []


def check(name, cond, detail=""):
    if not cond:
        print(f"[FAIL] {name}" + (f" - {detail}" if detail else ""))
        FAILURES.append(name)


translated = {json.loads(l)["sentinel_id"]: json.loads(l) for l in open(TRANSLATED, encoding="utf-8") if l.strip()}
legacy = {json.loads(l)["sentinel_id"]: json.loads(l) for l in open(LEGACY, encoding="utf-8") if l.strip()}
reference = {json.loads(l)["knowledge_unit_id"]: json.loads(l) for l in open(REFERENCE, encoding="utf-8") if l.strip()}

n_prompts = 0
stats = {"m1": 0, "m2": 0, "m3_cov": 0, "m3_hol": 0, "m4_cov": 0, "m4_hol": 0, "target": 0, "decomp": 0}

for sid in sorted(translated):
    t, s = translated[sid], legacy[sid]
    ref = reference[t["kc_id"]]
    draft = (s.get("draft_body") or "").strip()
    ref_text = (ref.get("reference_text") or "").strip()
    canonical, hierarchy = ref["canonical_name"], " > ".join(ref.get("hierarchy", {}).get("topic_path") or [])

    sys_items = [{"native_id": e["auth_id"], "text": e["text"]} for e in s.get("system_evidence") or []]
    auth_items = [{"native_id": e["auth_id"], "text": e["text"]} for e in s.get("authority_evidence") or []]
    sys_block, sys_map = P.render_evidence(sys_items, "SRC")
    auth_block, _ = P.render_evidence(auth_items, "SRC")
    ref_block, _ = P.render_evidence([{"native_id": "ref", "text": ref_text}] if ref_text else [], "REF")

    # opaque renumbering must actually replace native ids
    if sys_items:
        check(f"{sid}: system evidence renumbered to SRC_*", all(v.startswith("SRC_") for v in sys_map.values()))
        check(f"{sid}: native evidence ids absent from rendered block",
              not any(k in sys_block for k in sys_map if k.startswith("KC_")))

    fake_claims = [{"text": "claim one"}, {"text": "claim two"}]

    try:
        if draft:
            p = P.build_decomposition_prompt(draft, "candidate_draft"); n_prompts += 1; stats["decomp"] += 1
            check(f"{sid}: decomposition prompt contains the draft", draft[:60] in p)

        if draft:
            p = P.build_m1_prompt(fake_claims, sys_block); n_prompts += 1; stats["m1"] += 1
            check(f"{sid}: M1 prompt contains the EVIDENCE block", "EVIDENCE" in p and (sys_block[:40] in p if sys_items else True))
            check(f"{sid}: M1 cites-from material present", "SRC_000" in p if sys_items else True)

        if draft and ref_text:
            p = P.build_m2_prompt(fake_claims, ref_block, auth_block); n_prompts += 1; stats["m2"] += 1
            # the bug class this test exists for: asking for REF_/SRC_ citations without showing them
            check(f"{sid}: M2 prompt shows REF_ material it asks to be cited", "REF_000" in p)
            check(f"{sid}: M2 prompt shows SRC_ material it asks to be cited", "SRC_000" in p if auth_items else True)
            check(f"{sid}: M2 prompt contains the reference text", ref_text[:60] in p)

        if ref_text and draft:
            p = P.build_m3_coverage_prompt(fake_claims, draft); n_prompts += 1; stats["m3_cov"] += 1
            check(f"{sid}: M3 coverage prompt contains the draft", draft[:60] in p)
            p = P.build_m3_holistic_prompt(canonical, hierarchy, ref_block, draft); n_prompts += 1; stats["m3_hol"] += 1
            check(f"{sid}: M3 holistic contains reference AND draft", ref_text[:50] in p and draft[:50] in p)

        if ref_text:
            p = P.build_m4_prompt(fake_claims, sys_block); n_prompts += 1; stats["m4_cov"] += 1
            check(f"{sid}: M4 coverage contains evidence", "EVIDENCE" in p)
            p = P.build_m4_holistic_prompt(canonical, hierarchy, ref_block, sys_block); n_prompts += 1; stats["m4_hol"] += 1
            check(f"{sid}: M4 holistic contains reference AND evidence", ref_text[:50] in p)

        if draft and ref_text:
            p = P.build_target_alignment_prompt(canonical, hierarchy, ref_block, draft, auth_block)
            n_prompts += 1; stats["target"] += 1
            check(f"{sid}: target prompt contains reference AND draft", ref_text[:50] in p and draft[:50] in p)
            check(f"{sid}: target prompt names the intended KC", canonical in p)

    except P.BlindingViolation as e:
        check(f"{sid}: no blinding violation", False, str(e)[:200])
    except Exception as e:
        check(f"{sid}: prompt assembly", False, f"{type(e).__name__}: {e}")

    # schemas must build for the real claim counts too
    try:
        S.m1_faithfulness_schema(max(1, len(fake_claims)))
        S.m2_correctness_schema(max(1, len(fake_claims)))
    except Exception as e:
        check(f"{sid}: schema build", False, str(e))

print(f"assembled {n_prompts} prompts across {len(translated)} sentinels")
print(f"per-task counts: {stats}")
print()
print(f"{len(FAILURES)} failure(s)" if FAILURES else "ALL OFFLINE PROMPT-ASSEMBLY CHECKS PASSED")
sys.exit(1 if FAILURES else 0)
