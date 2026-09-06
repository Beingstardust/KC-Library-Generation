#!/usr/bin/env python3
"""Verify the resurrected step 6.7 v2 chain actually imports and wires itself together
correctly at its new stable location - not just that the 3 files were copied.

This exercises exactly what happens at MODULE IMPORT TIME in the real SLURM invocation
(env vars -> importlib.util.spec_from_file_location -> exec_module -> monkeypatch chain),
which requires no live Ollama server: the network call (ollama_generate_schema) only
happens inside run(), never during import. What's verified here is everything that
happens before run() is ever called - the exact place a stale/wrong path would fail.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAIN_DIR = REPO_ROOT / "steps/step_06_7_kc_draft_generation/scripts/v2_chain"

POLICY_RUNNER = CHAIN_DIR / "run_step67_v2_policy_segmentable_abstention_marker_fix.py"
FINAL_SCHEMA_RUNNER = CHAIN_DIR / "run_step67_v2_topic_schema_dict_aligned.py"
SOURCE_SCHEMA_RUNNER = CHAIN_DIR / "run_step67_v2_schema_contract_probe.py"
BASE_RUNNER = REPO_ROOT / "scripts/experimental/run_step67_v2_tiny_smoke.py"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def main() -> int:
    for label, path in [
        ("POLICY_RUNNER", POLICY_RUNNER),
        ("FINAL_SCHEMA_RUNNER", FINAL_SCHEMA_RUNNER),
        ("SOURCE_SCHEMA_RUNNER", SOURCE_SCHEMA_RUNNER),
        ("BASE_RUNNER (live, not resurrected)", BASE_RUNNER),
    ]:
        check(f"{label} exists at expected path: {path}", path.exists())

    # Exactly what the real SLURM script sets, pointed at the NEW stable location instead
    # of the old _archive/ paths.
    os.environ["KC_L_FINAL_SCHEMA_RUNNER"] = str(FINAL_SCHEMA_RUNNER)
    os.environ["KC_L_SOURCE_SCHEMA_RUNNER"] = str(SOURCE_SCHEMA_RUNNER)

    spec = importlib.util.spec_from_file_location("policy_runner_resurrection_test", POLICY_RUNNER)
    assert spec is not None and spec.loader is not None
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)  # this is where a stale env var path would raise/fail

    check("policy module loaded without raising", True)
    check("policy.final module loaded (the topic_schema_dict_aligned layer)", hasattr(policy, "final"))
    check("policy.final.source module loaded (the schema_contract_probe layer)", hasattr(policy.final, "source"))
    check(
        "policy.final.source resolved from the NEW SOURCE_SCHEMA_RUNNER location, not a stale path",
        Path(policy.final.source.__file__).resolve() == SOURCE_SCHEMA_RUNNER.resolve(),
    )
    check(
        "policy.final resolved from the NEW FINAL_SCHEMA_RUNNER location, not a stale path",
        Path(policy.final.__file__).resolve() == FINAL_SCHEMA_RUNNER.resolve(),
    )

    # Confirm the monkeypatch chain actually replaced the hooks it's supposed to replace.
    check(
        "policy.final.source.load_base_runner was monkeypatched by the policy layer",
        policy.final.source.load_base_runner is policy.load_base_runner_policy,
    )
    check(
        "topic_schema_dict layer's output_schema was wired onto source (schema alignment applied)",
        policy.final.source.output_schema is policy.final.output_schema_dict_aligned,
    )

    # Exercise load_base_runner_policy for real against the live (non-archived) base runner -
    # this is the one part of the import-time wiring that touches a file outside the
    # resurrected chain, and is also network-free (no Ollama call happens here).
    loaded_base = policy.load_base_runner_policy(BASE_RUNNER)
    check("load_base_runner_policy loads the live base runner without error", loaded_base is not None)
    check(
        "base runner's normalize_draft_from_packet was monkeypatched to the policy version",
        loaded_base.normalize_draft_from_packet is policy.normalize_draft_from_packet_policy,
    )
    check(
        "base runner's validate_output was monkeypatched to the policy version",
        loaded_base.validate_output is policy.validate_output_policy,
    )
    check(
        "base runner has build_prompt (needed by the schema-probe layer's make_prompt)",
        hasattr(loaded_base, "build_prompt"),
    )

    # Confirm ollama_generate_schema (the actual model-call function) exists and still
    # hardcodes temperature=0 with no top_p key, matching the confirmed production contract
    # investigated earlier this session - a resurrection that silently changed this would be
    # a correctness regression, not just a path issue.
    import inspect

    src = inspect.getsource(policy.final.source.ollama_generate_schema)
    check('ollama_generate_schema still hardcodes "temperature": 0', '"temperature": 0' in src)
    check("ollama_generate_schema still has no top_p key", "top_p" not in src)

    print("\nALL STEP 6.7 V2 CHAIN RESURRECTION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
