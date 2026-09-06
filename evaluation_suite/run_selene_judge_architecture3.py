"""Orchestrates the v3 judge architecture (rubric_selene_architecture3.py) against the frozen
36-sentinel suite: shared claim decomposition -> F1/F3 verification, a cached per-KC
CORE_REQUIREMENTS ledger -> F4/F5 per-requirement fan-out, and extract-then-classify F2.

Call shape per sentinel (draft_exists=True): 1 decompose + 1 F1-verify + 1 F3-verify + 1 F2 +
N F4-per-requirement + N F5-per-requirement, where N is the ledger size for that sentinel's KC
(built once per unique kc_id and reused - "independent of candidates and systems" per the
explicit architecture requirement). draft_exists=False sentinels only need the ledger's F5 calls
(F1-F4 are NOT_APPLICABLE by construction, matching every prior architecture generation).

response_format uses the OpenAI-standard json_schema (see run_selene_judge_v3.py's docstring for
why - extra_body does not work against this vLLM version).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import rubric_selene_architecture3 as r3
from build_rubric_sentinels_v3 import RubricSentinel, load_sentinels


def call_selene(base_url: str, model: str, user_prompt: str, schema: dict[str, Any],
                 timeout_s: int = 300) -> dict[str, Any]:
    import urllib.request

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": r3.SYSTEM_MESSAGE},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "top_p": 1.0,
        "seed": 20260812,
        "max_tokens": 2000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "judge_response", "schema": schema, "strict": True},
        },
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0
    content = body["choices"][0]["message"]["content"]
    return {"raw_response": content, "elapsed_s": elapsed, "usage": body.get("usage", {})}


def call_and_validate(base_url: str, model: str, case_id: str, prompt: str, schema: dict[str, Any],
                       validator) -> dict[str, Any]:
    """Returns a record with structural_valid/contract_valid flags set, never raising - every
    call outcome (including failures) must be recorded, per this project's own standing
    "never silently drop a row" convention."""
    record: dict[str, Any] = {"case_id": case_id, "structural_valid": False, "contract_valid": False}
    try:
        call = call_selene(base_url, model, prompt, schema)
    except Exception as exc:
        record["status"] = "CALL_FAILED"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    record["elapsed_s"] = call["elapsed_s"]
    record["usage"] = call["usage"]
    try:
        payload = json.loads(call["raw_response"])
    except json.JSONDecodeError as exc:
        record["status"] = "STRUCTURAL_INVALID"
        record["error"] = str(exc)
        record["raw_response"] = call["raw_response"]
        return record
    record["structural_valid"] = True
    try:
        validator(payload)
    except r3.RubricSchemaError as exc:
        record["status"] = "CONTRACT_INVALID"
        record["error"] = str(exc)
        record["raw_response"] = payload
        return record
    record["contract_valid"] = True
    record["status"] = "OK"
    record["response"] = payload
    return record


class LedgerCache:
    """One CORE_REQUIREMENTS ledger per kc_id, built once, reused across every sentinel sharing
    that kc_id - "independent of candidates and systems" per the architecture requirement. Keyed
    on kc_id alone because within this frozen sentinel suite authority_evidence is verified
    constant per kc_id (no CONSTRUCTED sentinel ever perturbs authority_evidence, only
    draft_body and occasionally system_evidence)."""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model
        self._cache: dict[str, tuple[tuple[r3.CoreRequirement, ...], dict[str, Any]]] = {}
        self.build_records: list[dict[str, Any]] = []

    def get(self, sentinel: RubricSentinel) -> tuple[r3.CoreRequirement, ...]:
        if sentinel.kc_id in self._cache:
            return self._cache[sentinel.kc_id][0]
        auth_block = r3.evidence_block(sentinel.authority_evidence)
        prompt = r3.build_core_requirements_prompt(sentinel.canonical_name, sentinel.kc_id, auth_block)
        case_id = f"LEDGER:{sentinel.kc_id}"
        record = call_and_validate(self.base_url, self.model, case_id, prompt,
                                    r3.core_requirements_json_schema(),
                                    r3.validate_core_requirements_response)
        record["kc_id"] = sentinel.kc_id
        self.build_records.append(record)
        if record["contract_valid"]:
            reqs = r3.frozen_requirements(record["response"])
        else:
            reqs = ()  # a failed ledger build degrades to "zero requirements" for this KC,
            # recorded explicitly in build_records rather than silently retried or invented.
        self._cache[sentinel.kc_id] = (reqs, record)
        return reqs


def run_f1_f3(base_url: str, model: str, sentinel: RubricSentinel) -> dict[str, Any]:
    out: dict[str, Any] = {"sentinel_id": sentinel.sentinel_id, "kc_id": sentinel.kc_id}

    decompose_prompt = r3.build_decompose_claims_prompt(sentinel.canonical_name, sentinel.kc_id, sentinel.draft_body)
    decompose_rec = call_and_validate(base_url, model, f"{sentinel.sentinel_id}:DECOMPOSE",
                                       decompose_prompt, r3.decompose_claims_json_schema(),
                                       r3.validate_decompose_response)
    out["decompose"] = decompose_rec
    if not decompose_rec["contract_valid"]:
        out["f1"] = {"status": "SKIPPED_DECOMPOSE_FAILED"}
        out["f3"] = {"status": "SKIPPED_DECOMPOSE_FAILED"}
        return out

    claims = r3.frozen_claim_texts(decompose_rec["response"])
    sys_block = r3.evidence_block(sentinel.system_evidence)
    auth_block = r3.evidence_block(sentinel.authority_evidence)

    f1_prompt = r3.build_f1_verify_prompt(sentinel.canonical_name, sentinel.kc_id, claims, sys_block)
    f1_rec = call_and_validate(base_url, model, f"{sentinel.sentinel_id}:F1", f1_prompt,
                                r3.f1_verify_json_schema(len(claims)),
                                lambda p: r3.validate_f1_verify_response(p, len(claims)))
    if f1_rec["contract_valid"]:
        f1_rec["actual_verdict"] = r3.derive_f1_v3_verdict(f1_rec["response"])
        f1_rec["expected_verdict"] = sentinel.expected_f1
        f1_rec["match"] = f1_rec["actual_verdict"] == sentinel.expected_f1
    out["f1"] = f1_rec

    f3_prompt = r3.build_f3_verify_prompt(sentinel.canonical_name, sentinel.kc_id, claims, auth_block)
    f3_rec = call_and_validate(base_url, model, f"{sentinel.sentinel_id}:F3", f3_prompt,
                                r3.f3_verify_json_schema(len(claims)),
                                lambda p: r3.validate_f3_verify_response(p, len(claims)))
    if f3_rec["contract_valid"]:
        f3_rec["actual_verdict"] = r3.derive_f3_v3_verdict(f3_rec["response"])
        f3_rec["expected_verdict"] = sentinel.expected_f3
        f3_rec["match"] = f3_rec["actual_verdict"] == sentinel.expected_f3
    out["f3"] = f3_rec
    return out


def run_f2(base_url: str, model: str, sentinel: RubricSentinel) -> dict[str, Any]:
    auth_block = r3.evidence_block(sentinel.authority_evidence)
    prompt = r3.build_f2_v3_prompt(sentinel.canonical_name, sentinel.kc_id, sentinel.draft_body, auth_block)
    rec = call_and_validate(base_url, model, f"{sentinel.sentinel_id}:F2", prompt,
                             r3.f2_v3_json_schema(), r3.validate_f2_v3_response)
    if rec["contract_valid"]:
        rec["actual_verdict"] = r3.derive_f2_v3_verdict(rec["response"])
        rec["expected_verdict"] = sentinel.expected_f2
        rec["match"] = rec["actual_verdict"] == sentinel.expected_f2
    return rec


def run_f4_f5(base_url: str, model: str, sentinel: RubricSentinel,
              requirements: tuple[r3.CoreRequirement, ...]) -> dict[str, Any]:
    f4_per_req: list[dict[str, Any]] = []
    f5_per_req: list[dict[str, Any]] = []

    auth_block = r3.evidence_block(sentinel.authority_evidence)
    if sentinel.draft_body.strip():
        for i, req in enumerate(requirements):
            prompt = r3.build_f4_requirement_prompt(sentinel.canonical_name, req, sentinel.draft_body, auth_block)
            rec = call_and_validate(base_url, model, f"{sentinel.sentinel_id}:F4:{i}", prompt,
                                     r3.f4_requirement_json_schema(), r3.validate_f4_requirement_response)
            rec["requirement"] = req.requirement
            rec["requirement_type"] = req.type
            f4_per_req.append(rec)

    sys_block = r3.evidence_block(sentinel.system_evidence)
    for i, req in enumerate(requirements):
        prompt = r3.build_f5_requirement_prompt(sentinel.canonical_name, req, sys_block)
        rec = call_and_validate(base_url, model, f"{sentinel.sentinel_id}:F5:{i}", prompt,
                                 r3.f5_requirement_json_schema(), r3.validate_f5_requirement_response)
        rec["requirement"] = req.requirement
        rec["requirement_type"] = req.type
        f5_per_req.append(rec)

    result: dict[str, Any] = {"f4_per_requirement": f4_per_req, "f5_per_requirement": f5_per_req}

    if sentinel.draft_body.strip():
        valid_f4 = [r for r in f4_per_req if r["contract_valid"]]
        if len(valid_f4) == len(f4_per_req):
            statuses = [r["response"]["status"] for r in valid_f4]
            verdict, _reason = r3.derive_f4_v3_outcome(statuses)
            result["f4_actual_verdict"] = verdict
        else:
            result["f4_actual_verdict"] = None  # cannot derive - at least one requirement call failed
        result["f4_expected_verdict"] = sentinel.expected_f4
        result["f4_match"] = result["f4_actual_verdict"] == sentinel.expected_f4
        result["f4_all_calls_valid"] = len(valid_f4) == len(f4_per_req)

    valid_f5 = [r for r in f5_per_req if r["contract_valid"]]
    if len(valid_f5) == len(f5_per_req):
        statuses = [r["response"]["status"] for r in valid_f5]
        verdict, _reason = r3.derive_f5_v3_outcome(statuses)
        result["f5_actual_verdict"] = verdict
    else:
        result["f5_actual_verdict"] = None
    result["f5_expected_verdict"] = sentinel.expected_f5
    result["f5_match"] = result["f5_actual_verdict"] == sentinel.expected_f5
    result["f5_all_calls_valid"] = len(valid_f5) == len(f5_per_req)

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", default="selene-1-llama-3.3-70b")
    ap.add_argument("--sentinels", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None, help="only process the first N sentinels (smoke use)")
    args = ap.parse_args()

    sentinels = load_sentinels(args.sentinels)
    if args.limit:
        sentinels = sentinels[: args.limit]
    print(f"loaded {len(sentinels)} sentinels")

    ledger = LedgerCache(args.base_url, args.model)
    results: list[dict[str, Any]] = []

    for s in sentinels:
        print(f"{s.sentinel_id} ({s.kc_id}) ...")
        row: dict[str, Any] = {"sentinel_id": s.sentinel_id, "kc_id": s.kc_id, "category": s.category}

        requirements = ledger.get(s)
        row["n_requirements"] = len(requirements)

        if s.draft_body.strip():
            f1f3 = run_f1_f3(args.base_url, args.model, s)
            row["decompose"] = f1f3["decompose"]
            row["f1"] = f1f3["f1"]
            row["f3"] = f1f3["f3"]
            print(f"  F1: {f1f3['f1'].get('status')} {f1f3['f1'].get('actual_verdict')} "
                  f"expected {s.expected_f1} match {f1f3['f1'].get('match')}")
            print(f"  F3: {f1f3['f3'].get('status')} {f1f3['f3'].get('actual_verdict')} "
                  f"expected {s.expected_f3} match {f1f3['f3'].get('match')}")

            f2_rec = run_f2(args.base_url, args.model, s)
            row["f2"] = f2_rec
            print(f"  F2: {f2_rec.get('status')} {f2_rec.get('actual_verdict')} "
                  f"expected {s.expected_f2} match {f2_rec.get('match')}")
        else:
            row["f1"] = {"status": "NOT_APPLICABLE"}
            row["f2"] = {"status": "NOT_APPLICABLE"}
            row["f3"] = {"status": "NOT_APPLICABLE"}

        f4f5 = run_f4_f5(args.base_url, args.model, s, requirements)
        row["f4_f5"] = f4f5
        print(f"  F4: {f4f5.get('f4_actual_verdict')} expected {s.expected_f4} match {f4f5.get('f4_match')}")
        print(f"  F5: {f4f5.get('f5_actual_verdict')} expected {s.expected_f5} match {f4f5.get('f5_match')}")

        results.append(row)

    out_obj = {"ledger_builds": ledger.build_records, "sentinel_results": results}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2, sort_keys=True, ensure_ascii=False)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
