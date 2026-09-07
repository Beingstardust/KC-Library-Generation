"""PHASE 8: run the reference-based judge tasks over the translated sentinel suite.

One decomposition per draft and one per reference, each frozen and reused across the tasks that
share it (candidate claims -> M1 + M2; reference claims -> M3 coverage + M4 coverage), exactly as
the spec requires and as the Selene v3 work established is necessary for the relations to be
comparable to one another.

Every call is pointwise and blinded: the judge sees one text against one target, with evidence
renumbered into opaque SRC_/REF_ ids, and never sees a model, system, or retrieval-architecture
name. reference_judge_prompts.assert_blinded enforces this at build time.

Aggregates are NEVER requested from the model. Per-KC metrics are derived in Python by
reference_metrics.derive_per_kc from the per-claim label lists collected here.

Usage:
  python run_reference_judge.py --base-url http://ant2:8000/v1 --model <served-name> \
      --sentinels output/reference_sentinel_gold.jsonl --out output/sentinel_judge_raw.json [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import reference_claim_schema as C           # noqa: E402
import reference_judge_prompts as P          # noqa: E402
import reference_judge_schema as S           # noqa: E402

LEGACY_SENTINELS = BASE.parent / "output" / "r9_final" / "rubric_sentinel_gold.jsonl"
REFERENCE = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
EVIDENCE_STORE = BASE.parent / "reference_library" / "corpus_support" / "evidence_store" / "proposed_evidence_store.jsonl"


# ---------------------------------------------------------------------------
# FROZEN FINAL JUDGE DECODING CONFIGURATION
# frequency_penalty is 0.0. It was briefly set to 0.2 while diagnosing structured-output stalls,
# and must not return. vLLM applies a frequency penalty directly to generation logits as a function
# of how often a token has already appeared, so a nonzero value is NOT a formatting control - it
# can alter semantic decisions even under greedy decoding. This project measured exactly that: two
# penalty-free runs produced an IDENTICAL M1 verdict distribution (20 FAIL / 14 PASS) despite
# differing in holistic schema, while the penalty=0.2 run shifted to 22 FAIL / 12 PASS.
# The decisive structural remedy was making `rationale` optional; the penalty only moved preflight
# failures from 5 to 4 and was never the fix. Removing it restores default decoding rather than
# tuning anything - prompts, label semantics and sentinel gold are untouched.
# ---------------------------------------------------------------------------
DECODING = {
    "temperature": 0.0,
    "top_p": 1.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
    "seed": 20260825,
}


def call_judge(base_url: str, model: str, prompt: str, schema: dict, max_tokens: int = 3000) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": P.SYSTEM_MESSAGE},
                      {"role": "user", "content": prompt}],
        "temperature": DECODING["temperature"],
        "top_p": DECODING["top_p"],
        "frequency_penalty": DECODING["frequency_penalty"],
        "presence_penalty": DECODING["presence_penalty"],
        "repetition_penalty": DECODING["repetition_penalty"],
        "seed": DECODING["seed"],
        "max_tokens": max_tokens,
        # OpenAI-standard structured output. NOTE: extra_body/guided_json is an openai-python SDK
        # convention and is SILENTLY IGNORED when POSTing raw JSON, which cost a whole smoke run
        # during the Selene v3 work - do not "simplify" this back to extra_body.
        "response_format": {"type": "json_schema",
                             "json_schema": {"name": "judge_response", "schema": schema, "strict": True}},
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return {
        "content": body["choices"][0]["message"]["content"],
        "finish_reason": body["choices"][0].get("finish_reason"),
        "usage": body.get("usage"),
        "elapsed_s": time.time() - t0,
    }


def call_and_validate(base_url, model, case_id, prompt, schema, validator, max_tokens=3000,
                       max_attempts: int = 2) -> dict:
    """Never raises. Classifies every outcome so structural vs contract vs call failures can be
    reported separately, as the qualification statistics require.

    A single retry is allowed for TRUNCATED / STRUCTURAL_INVALID / CALL_FAILED outcomes, because
    this stack exhibits a sporadic decoding pathology: under the permissive whitespace in the
    compiled grammar the model occasionally falls into emitting indentation until it exhausts the
    token budget. The same prompt re-issued usually completes normally in ~150 tokens. It is
    genuinely intermittent rather than input-specific - vLLM's continuous batching is not
    bit-deterministic even at temperature 0 with a fixed seed, so batch composition changes the
    outcome.

    The retry NEVER changes the prompt or the schema, so it is not prompt tuning. Every attempt is
    recorded in `attempts` and `n_attempts`, so retried calls stay visible in the validity
    statistics instead of being quietly laundered into clean ones.
    """
    attempts = []
    rec: dict = {}
    for attempt in range(1, max_attempts + 1):
        rec = _attempt_once(base_url, model, case_id, prompt, schema, validator, max_tokens)
        attempts.append({"attempt": attempt, "status": rec["status"], "error": rec["error"][:200]})
        if rec["status"] in ("OK", "CONTRACT_INVALID"):
            break  # a contract failure is a real semantic finding - never retry it away
    rec["attempts"] = attempts
    rec["n_attempts"] = len(attempts)
    rec["retried"] = len(attempts) > 1
    return rec


def _attempt_once(base_url, model, case_id, prompt, schema, validator, max_tokens) -> dict:
    rec = {"case_id": case_id, "status": None, "structural_valid": False, "contract_valid": False,
           "response": None, "error": "", "elapsed_s": None, "usage": None}
    try:
        out = call_judge(base_url, model, prompt, schema, max_tokens=max_tokens)
    except Exception as e:
        rec["status"] = "CALL_FAILED"
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    rec["elapsed_s"] = out["elapsed_s"]
    rec["usage"] = out["usage"]
    rec["finish_reason"] = out["finish_reason"]
    try:
        parsed = json.loads(out["content"])
    except Exception as e:
        # Truncation is reported separately from malformed output: it is a budget/decoding problem,
        # not the model failing to follow the schema, and conflating them would misstate structural
        # validity. Runaway whitespace padding under a permissive grammar shows up here.
        rec["status"] = "TRUNCATED" if out["finish_reason"] == "length" else "STRUCTURAL_INVALID"
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["raw"] = out["content"][:2000]
        rec["whitespace_ratio"] = (
            sum(1 for ch in out["content"] if ch.isspace()) / len(out["content"])
            if out["content"] else None
        )
        return rec
    rec["structural_valid"] = True
    rec["response"] = parsed
    try:
        validator(parsed)
    except Exception as e:
        rec["status"] = "CONTRACT_INVALID"
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    rec["contract_valid"] = True
    rec["status"] = "OK"
    return rec


def decompose(base_url, model, case_id, text, origin, subject_id, kc_id) -> tuple[dict, list]:
    """Returns (call_record, claims). Claims are structurally validated against the source text -
    a decomposer that invents a parent_span is caught here, not silently trusted."""
    prompt = P.build_decomposition_prompt(text, origin)
    rec = call_and_validate(
        base_url, model, case_id, prompt, S.decomposition_schema(),
        lambda r: r.get("task") == "CLAIM_DECOMPOSITION" or (_ for _ in ()).throw(
            S.JudgeSchemaError(f"expected CLAIM_DECOMPOSITION, got {r.get('task')!r}")),
        max_tokens=4000,
    )
    if not rec["contract_valid"]:
        return rec, []
    raw_claims = rec["response"]["claims"]
    claims = [C.Claim(claim_id=C.stable_claim_id(subject_id, i), text=c["text"],
                      claim_type=c["claim_type"], parent_span=c["parent_span"],
                      subject_id=subject_id, origin=origin)
              for i, c in enumerate(raw_claims)]
    decomp = C.ClaimDecomposition(subject_id=subject_id, kc_id=kc_id, origin=origin,
                                   source_text=text, claims=claims, decomposer_model=model,
                                   source_text_sha256=C.content_sha256(text))
    problems = C.all_structural_problems(decomp)
    rec["decomposition_problems"] = problems
    rec["frozen"] = decomp.freeze()
    return rec, claims


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--sentinels", type=Path, default=BASE / "output" / "reference_sentinel_gold.jsonl")
    ap.add_argument("--legacy-sentinels", type=Path, default=LEGACY_SENTINELS,
                    help="frozen rubric_sentinel_gold.jsonl (source of draft_body and evidence)")
    ap.add_argument("--reference", type=Path, default=REFERENCE,
                    help="frozen expert_adjudicated_reference_kc_library.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    translated = {json.loads(l)["sentinel_id"]: json.loads(l)
                  for l in open(args.sentinels, encoding="utf-8") if l.strip()}
    legacy = {json.loads(l)["sentinel_id"]: json.loads(l)
              for l in open(args.legacy_sentinels, encoding="utf-8") if l.strip()}
    reference = {json.loads(l)["knowledge_unit_id"]: json.loads(l)
                 for l in open(args.reference, encoding="utf-8") if l.strip()}

    ids = sorted(translated)
    if args.limit:
        ids = ids[: args.limit]
    print(f"running {len(ids)} sentinels")

    results = []
    for sid in ids:
        t = translated[sid]
        s = legacy[sid]
        ref = reference[t["kc_id"]]
        print(f"{sid} ({t['kc_id']}) [{t['case_type']}] ...")

        row = {"sentinel_id": sid, "kc_id": t["kc_id"], "case_type": t["case_type"],
               "expected": t["expected"], "calls": {}}

        draft = (s.get("draft_body") or "").strip()
        ref_text = (ref.get("reference_text") or "").strip()
        hierarchy = " > ".join(ref.get("hierarchy", {}).get("topic_path") or [])
        canonical = ref["canonical_name"]

        sys_items = [{"native_id": e["auth_id"], "text": e["text"]} for e in s.get("system_evidence") or []]
        auth_items = [{"native_id": e["auth_id"], "text": e["text"]} for e in s.get("authority_evidence") or []]
        sys_block, _ = P.render_evidence(sys_items, "SRC")
        auth_block, _ = P.render_evidence(auth_items, "SRC")
        ref_block, _ = P.render_evidence([{"native_id": "ref", "text": ref_text}] if ref_text else [], "REF")

        # ---- candidate decomposition (frozen, reused by M1 and M2) ----
        cand_claims = []
        if draft:
            rec, cand_claims = decompose(args.base_url, args.model, f"{sid}:DECOMPOSE_CANDIDATE",
                                          draft, "candidate_draft", f"{t['kc_id']}::sentinel", t["kc_id"])
            row["calls"]["decompose_candidate"] = rec
            print(f"   candidate claims: {len(cand_claims)} ({rec['status']})")

        # ---- reference decomposition (frozen, reused by M3 coverage and M4) ----
        ref_claims = []
        if ref_text:
            rec, ref_claims = decompose(args.base_url, args.model, f"{sid}:DECOMPOSE_REFERENCE",
                                         ref_text, "reference", f"{t['kc_id']}::reference", t["kc_id"])
            row["calls"]["decompose_reference"] = rec
            print(f"   reference claims: {len(ref_claims)} ({rec['status']})")

        cd = [{"text": c.text} for c in cand_claims]
        rd = [{"text": c.text} for c in ref_claims]

        # ---- M1 faithfulness ----
        if cd:
            row["calls"]["m1"] = call_and_validate(
                args.base_url, args.model, f"{sid}:M1", P.build_m1_prompt(cd, sys_block),
                S.m1_faithfulness_schema(len(cd)),
                lambda r: S.validate_per_claim_response(r, "M1_EVIDENCE_FAITHFULNESS",
                                                         S.M1_FAITHFULNESS_LABELS, len(cd)))
            print(f"   M1: {row['calls']['m1']['status']}")

        # ---- M2 correctness (needs a reference to judge against) ----
        if cd and ref_text:
            row["calls"]["m2"] = call_and_validate(
                args.base_url, args.model, f"{sid}:M2",
                P.build_m2_prompt(cd, ref_block, auth_block), S.m2_correctness_schema(len(cd)),
                lambda r: S.validate_m2_response(r, len(cd)))
            print(f"   M2: {row['calls']['m2']['status']}")

        # ---- M3 coverage + holistic ----
        if rd and draft:
            row["calls"]["m3_coverage"] = call_and_validate(
                args.base_url, args.model, f"{sid}:M3_COV",
                P.build_m3_coverage_prompt(rd, draft), S.m3_claim_coverage_schema(len(rd)),
                lambda r: S.validate_per_claim_response(r, "M3_REFERENCE_CLAIM_COVERAGE",
                                                         S.M3_CLAIM_COVERAGE_LABELS, len(rd)))
            row["calls"]["m3_holistic"] = call_and_validate(
                args.base_url, args.model, f"{sid}:M3_HOL",
                P.build_m3_holistic_prompt(canonical, hierarchy, ref_block, draft),
                S.m3_holistic_schema(),
                lambda r: S.validate_holistic_response(r, "M3_CORE_COMPLETENESS",
                                                        S.M3_HOLISTIC_LABELS, "missing_defining_components"))
            print(f"   M3: cov={row['calls']['m3_coverage']['status']} hol={row['calls']['m3_holistic']['status']}")

        # ---- M4 retrieval coverage + holistic ----
        if rd:
            row["calls"]["m4_coverage"] = call_and_validate(
                args.base_url, args.model, f"{sid}:M4_COV",
                P.build_m4_prompt(rd, sys_block), S.m4_retrieval_coverage_schema(len(rd)),
                lambda r: S.validate_per_claim_response(r, "M4_RETRIEVAL_REFERENCE_COVERAGE",
                                                         S.M4_RETRIEVAL_LABELS, len(rd)))
            print(f"   M4 cov: {row['calls']['m4_coverage']['status']}")
        if ref_text:
            row["calls"]["m4_holistic"] = call_and_validate(
                args.base_url, args.model, f"{sid}:M4_HOL",
                P.build_m4_holistic_prompt(canonical, hierarchy, ref_block, sys_block),
                S.m4_holistic_schema(),
                lambda r: S.validate_holistic_response(r, "M4_EVIDENCE_ADEQUACY",
                                                        S.M4_HOLISTIC_LABELS, "missing_evidence_for"))
            print(f"   M4 hol: {row['calls']['m4_holistic']['status']}")

        # ---- target alignment ----
        if draft and ref_text:
            row["calls"]["target"] = call_and_validate(
                args.base_url, args.model, f"{sid}:TARGET",
                P.build_target_alignment_prompt(canonical, hierarchy, ref_block, draft, auth_block),
                S.target_alignment_schema(), S.validate_target_alignment_response)
            print(f"   TARGET: {row['calls']['target']['status']}")

        results.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "n_sentinels": len(results), "results": results},
                  f, indent=2, ensure_ascii=False)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
