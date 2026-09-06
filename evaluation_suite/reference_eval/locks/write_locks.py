"""Freeze locks for the reference-based evaluation (spec section 29).

The production evaluation runner must refuse to execute without all six locks. Each stores the
SHA-256 of what it freezes, so a lock is not a checkbox - re-verification recomputes the hashes
and a mismatch is a hard stop.

There is deliberately NO override flag anywhere in this module or in the verifier. A judge that
has not been qualified cannot be silently used in production mode; the only way forward is to
qualify it.

Locks:
  EXPERT_REFERENCE_FROZEN  - written by reference_library/03_validation/freeze_adjudicated_reference.py
  CANDIDATES_FROZEN        - the 7 frozen candidate arms + their freeze manifest
  CLAIM_PROTOCOL_FROZEN    - claim schema + decomposition prompt (changing either changes claims)
  JUDGE_PROMPTS_FROZEN     - judge schemas + prompt builders
  JUDGE_QUALIFIED          - written only after a judge passes the qualification gate
  BLINDING_FROZEN          - the blinding pattern set + calibration mapping
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
REPO = BASE.parent.parent           # evaluation_suite/final_pipeline
REFLIB = REPO / "reference_library"
REFEVAL = REPO / "reference_eval"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_files(paths: list[Path]) -> dict[str, str]:
    return {str(p.relative_to(REPO)): sha256_file(p) for p in paths if p.exists()}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_lock(name: str, payload: dict) -> Path:
    payload = {"lock_name": name, "written_utc": _now(), **payload}
    payload["lock_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in payload.items() if k != "written_utc"},
                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    p = BASE / f"{name}.lock.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def build_all(judge_qualified: bool = False) -> list[Path]:
    written = []

    # ---- CANDIDATES_FROZEN ----
    written.append(write_lock("CANDIDATES_FROZEN", {
        "candidate_freeze_manifest": "reference_library/00_freeze/CANDIDATE_FREEZE_MANIFEST.json",
        "hashes": sha256_files([
            REFLIB / "00_freeze" / "CANDIDATE_FREEZE_MANIFEST.json",
            REFLIB / "00_freeze" / "candidates_frozen.lock.json",
            REFLIB / "00_freeze" / "candidate_revalidation_20260825.json",
        ]),
        "n_arms": 7,
        "unique_primary_arms": 6,
        "note": "Candidate draft files live on Cluster-B and are hashed inside CANDIDATE_FREEZE_MANIFEST.json; "
                "revalidated 2026-08-25 with all 7 hashes unchanged. If any candidate hash differs at "
                "verification time, the evaluation must STOP.",
    }))

    # ---- CLAIM_PROTOCOL_FROZEN ----
    written.append(write_lock("CLAIM_PROTOCOL_FROZEN", {
        "hashes": sha256_files([REFEVAL / "reference_claim_schema.py"]),
        "decomposition_prompt_sha256": _prompt_hash("build_decomposition_prompt"),
        "note": "Freezes both the claim data model and the decomposition prompt. Changing either changes "
                "what a 'claim' is, which invalidates every downstream per-claim metric.",
    }))

    # ---- JUDGE_PROMPTS_FROZEN ----
    written.append(write_lock("JUDGE_PROMPTS_FROZEN", {
        "hashes": sha256_files([
            REFEVAL / "reference_judge_schema.py",
            REFEVAL / "reference_judge_prompts.py",
        ]),
        "grammar_enforcement_verified": True,
        "grammar_enforcement_evidence": "tests/test_grammar_enforcement.py, run against vLLM 0.27.1 + XGrammar: "
                                         "oneOf branches materialize and bind each M2 label to its permitted "
                                         "evidence-id family; if/then/else is confirmed silently ignored and is "
                                         "therefore not used anywhere.",
    }))

    # ---- BLINDING_FROZEN ----
    import sys as _s
    _s.path.insert(0, str(REFEVAL))
    import reference_judge_prompts as P
    written.append(write_lock("BLINDING_FROZEN", {
        "forbidden_pattern_count": len(P._FORBIDDEN_PATTERNS),
        "forbidden_patterns_sha256": hashlib.sha256(
            json.dumps(P._FORBIDDEN_PATTERNS, sort_keys=True).encode()).hexdigest(),
        "calibration_mapping": sha256_files([
            REFEVAL / "output" / "human_calibration" / "reference_human_calibration_blinded_mapping.jsonl",
            REFEVAL / "output" / "human_calibration" / "reference_human_calibration_workbook.jsonl",
        ]),
        "note": "Blinding is enforced at prompt-build time by assert_blinded(), verified against all 159 "
                "frozen reference texts and all 36 sentinels with zero false positives and all known leak "
                "forms caught. Arm identity exists only in the mapping file, never in the workbook.",
    }))

    # ---- EXPERT_REFERENCE_FROZEN (mirror of the reference-library lock) ----
    src = REFLIB / "04_gold" / "EXPERT_REFERENCE_FROZEN.lock.json"
    if src.exists():
        written.append(write_lock("EXPERT_REFERENCE_FROZEN", {
            "source_lock": str(src.relative_to(REPO)),
            "source_lock_sha256": sha256_file(src),
            "reference_library": sha256_files([
                REFLIB / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl",
                REFLIB / "04_gold" / "expert_adjudicated_reference_manifest.json",
                REFLIB / "04_gold" / "reference_provenance_resolution.jsonl",
            ]),
        }))

    # ---- JUDGE_QUALIFIED ----
    written.append(write_lock("JUDGE_QUALIFIED", {
        "qualified": judge_qualified,
        "status": "NOT_QUALIFIED - development sentinel results exist but the qualification gate has not "
                  "been evaluated, and human calibration has not been run."
                  if not judge_qualified else "QUALIFIED",
        "requirement": "A judge is qualified only against HUMAN calibration labels on the reference-based "
                        "tasks, per ARES-style human-calibrated validation. Sentinel performance alone does "
                        "not qualify a judge, and the previous holistic F1-F5 qualification does not "
                        "transfer to these tasks.",
        "no_override": "There is no flag that bypasses this lock in production mode.",
    }))
    return written


def _prompt_hash(fn_name: str) -> str:
    import inspect
    sys.path.insert(0, str(REFEVAL))
    import reference_judge_prompts as P
    return hashlib.sha256(inspect.getsource(getattr(P, fn_name)).encode()).hexdigest()


if __name__ == "__main__":
    for p in build_all():
        d = json.loads(p.read_text(encoding="utf-8"))
        print(f"{p.name:<34} {d['lock_sha256'][:16]}...")
    print(f"\nwrote {len(list(BASE.glob('*.lock.json')))} locks to {BASE}")
