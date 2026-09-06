"""Calls a running vLLM OpenAI-compatible Selene server for F1-F5 judgments (FINAL R9 KC CONTENT
QUALITY EVALUATION spec, sections 7/16-20/28), 2026-08-24 hardening pass.

Structured JSON output via the OpenAI-standard `response_format: {type: json_schema, ...}` field
at the TOP LEVEL of the request body - NOT nested under an `extra_body` key. `extra_body` is an
openai-python-SDK convention for merging extra fields into the request; it is meaningless when
building the raw HTTP JSON body by hand, as this module does. Confirmed empirically: the first
real run of this harness nested guided_json under extra_body and every one of 61 calls silently
ignored the schema, returning free-form markdown-fenced JSON instead.

Every response is validated with rubric_v3's own validators before being trusted. Two distinct
validity tiers are recorded per case (see build_result docstring) so a caller can tell a bare
JSON-Schema/grammar failure apart from a contract violation the grammar cannot express (identity
leaks, evidence-id namespace, F1/F4/F5 nested-item shape).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Literal

from build_rubric_sentinels_v3 import RubricSentinel, load_sentinels
from rubric_v3 import (
    CRITERIA,
    RubricSchemaError,
    SYSTEM_MESSAGE,
    build_f1_prompt,
    build_f2_prompt,
    build_f3_prompt,
    build_f4_prompt,
    build_f5_prompt,
    criterion_json_schema,
    derive_f1_verdict,
    derive_f4_outcome,
    derive_f5_outcome,
    validate_criterion_response,
    validate_f1_response,
    validate_f4_response,
    validate_f5_response,
)

_PROMPT_BUILDERS = {
    "F1": build_f1_prompt, "F2": build_f2_prompt, "F3": build_f3_prompt,
    "F4": build_f4_prompt, "F5": build_f5_prompt,
}


def evidence_block(items: tuple[dict[str, Any], ...]) -> str:
    if not items:
        return "(no evidence items)"
    return "\n\n".join(
        f"[{it['auth_id']}] (doc={it['doc_id']}, page={it['page_index']}) {it['text']}"
        for it in items
    )


def build_prompt(sentinel: RubricSentinel, criterion: str) -> str:
    sys_block = evidence_block(sentinel.system_evidence)
    auth_block = evidence_block(sentinel.authority_evidence)
    if criterion == "F1":
        return build_f1_prompt(sentinel.canonical_name, sentinel.kc_id, sentinel.draft_body, sys_block)
    if criterion == "F2":
        return build_f2_prompt(sentinel.canonical_name, sentinel.kc_id, sentinel.draft_body, auth_block)
    if criterion in ("F3", "F4"):
        return _PROMPT_BUILDERS[criterion](sentinel.canonical_name, sentinel.kc_id, sentinel.draft_body, auth_block)
    if criterion == "F5":
        return build_f5_prompt(sentinel.canonical_name, sentinel.kc_id, sys_block, auth_block)
    raise ValueError(f"unknown criterion {criterion!r}")


def applicable_criteria(sentinel: RubricSentinel) -> list[str]:
    """Section 31: an empty/abstained draft never gets F1-F4 called - only F5 (which judges the
    evidence, not the draft) is applicable."""
    if not sentinel.draft_body.strip():
        return ["F5"]
    return list(CRITERIA)


def call_selene(base_url: str, model: str, system_message: str, user_prompt: str,
                 schema: dict[str, Any], timeout_s: int = 300) -> dict[str, Any]:
    import urllib.request

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "top_p": 1.0,
        "seed": 20260812,
        "max_tokens": 3000,
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


def _validate_and_derive(criterion: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Returns (actual_verdict, contract_tier_note). Raises RubricSchemaError on contract
    violation - caller distinguishes this from a structural (json-parse/schema) failure."""
    if criterion == "F1":
        validate_f1_response(payload)
        return derive_f1_verdict(payload), "OK"
    if criterion in ("F2", "F3"):
        validate_criterion_response(payload, criterion)
        return payload["verdict"], "OK"
    if criterion == "F4":
        validate_f4_response(payload)
        verdict, _reason = derive_f4_outcome(payload)
        return verdict, "OK"
    if criterion == "F5":
        validate_f5_response(payload)
        verdict, _reason = derive_f5_outcome(payload)
        return verdict, "OK"
    raise ValueError(f"unknown criterion {criterion!r}")


def run_one(base_url: str, model: str, sentinel: RubricSentinel, criterion: str) -> dict[str, Any]:
    case_id = f"{sentinel.sentinel_id}:{criterion}"
    prompt = build_prompt(sentinel, criterion)
    schema = criterion_json_schema(criterion)
    result: dict[str, Any] = {
        "sentinel_id": sentinel.sentinel_id, "kc_id": sentinel.kc_id, "criterion": criterion,
        "case_id": case_id,
        # structural_valid: did it parse as JSON at all (the grammar/JSON-Schema layer's job).
        # contract_valid: did it additionally pass rubric_v3's own semantic contract checks
        # (identity leaks, evidence-id namespace, nested-item shape) - things no JSON Schema
        # keyword expresses. A response can be structural_valid=True, contract_valid=False.
        "structural_valid": False, "contract_valid": False,
    }
    try:
        call = call_selene(base_url, model, SYSTEM_MESSAGE, prompt, schema)
    except Exception as exc:  # network/timeout/server error - recorded, not silently dropped
        result["status"] = "CALL_FAILED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["elapsed_s"] = call["elapsed_s"]
    result["usage"] = call["usage"]
    try:
        payload = json.loads(call["raw_response"])
    except json.JSONDecodeError as exc:
        result["status"] = "STRUCTURAL_INVALID"
        result["error"] = str(exc)
        result["raw_response"] = call["raw_response"]
        return result

    result["structural_valid"] = True

    try:
        actual_verdict, _ = _validate_and_derive(criterion, payload)
    except RubricSchemaError as exc:
        result["status"] = "CONTRACT_INVALID"
        result["error"] = str(exc)
        result["raw_response"] = payload
        return result

    expected_verdict = getattr(sentinel, f"expected_{criterion.lower()}")
    result["contract_valid"] = True
    result["status"] = "OK"
    result["actual_verdict"] = actual_verdict
    result["expected_verdict"] = expected_verdict
    result["match"] = actual_verdict == expected_verdict
    result["response"] = payload
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", default="selene-1-llama-3.3-70b")
    ap.add_argument("--sentinels", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    sentinels = load_sentinels(args.sentinels)
    print(f"loaded {len(sentinels)} sentinels")

    results: list[dict[str, Any]] = []
    for s in sentinels:
        for criterion in applicable_criteria(s):
            print(f"  {s.sentinel_id} {criterion} ...", end=" ", flush=True)
            r = run_one(args.base_url, args.model, s, criterion)
            print(r.get("status"), r.get("actual_verdict"), "expected:", r.get("expected_verdict"),
                  "match:", r.get("match"))
            results.append(r)

    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")

    n_structural = sum(1 for r in results if r["structural_valid"])
    n_contract = sum(1 for r in results if r["contract_valid"])
    n_match = sum(1 for r in results if r.get("match"))
    print(f"\n{len(results)} calls: {n_structural} structurally valid, {n_contract} contract-valid, "
          f"{n_match} matched expected")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
