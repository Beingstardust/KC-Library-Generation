"""Self-test for discover_r9_evaluation_artifacts.py and verify_r9_experimental_matrix.py.
Zero API key, zero network calls, zero cost - synthetic fixtures only, written to a temp dir.

Run: python test_discover_and_verify_r9.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from discover_r9_evaluation_artifacts import artifact_stats, build_manifest
from verify_r9_experimental_matrix import (
    ExperimentalInvariantError,
    assert_no_stop_conditions,
    check_decoding_config_parity,
    check_extrinsic_commit_parity,
    check_intrinsic_evidence_hash_equality,
    check_kc_identity_equality,
)

CHECKS_PASSED: list[str] = []
CHECKS_FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        CHECKS_PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        CHECKS_FAILED.append((name, detail))
        print(f"  [FAIL] {name}  -- {detail}")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


TMP = Path(tempfile.mkdtemp(prefix="r9_eval_selftest_"))


def _packet_row(kc_id: str, evidence_text: str) -> dict:
    return {"kc_id": kc_id, "evidence_for_synthesis": [{"evidence_id": "SYS_001", "text": evidence_text}]}


def test_artifact_stats_and_missing_file():
    p = TMP / "a.jsonl"
    _write_jsonl(p, [_packet_row("KC_1", "x"), _packet_row("KC_2", "y")])
    stats = artifact_stats(p)
    check("artifact_stats reports correct row count", stats["row_count"] == 2)
    check("artifact_stats reports correct KC-ID count", stats["unique_kc_id_count"] == 2)
    check("artifact_stats includes a sha256 hex digest", len(stats["sha256"]) == 64)

    try:
        artifact_stats(TMP / "does_not_exist.jsonl")
        ok = False
    except FileNotFoundError:
        ok = True
    check("artifact_stats raises (not silently skips) on a missing artifact", ok)


def test_build_manifest_preserves_structure():
    p1 = TMP / "b1.jsonl"
    p2 = TMP / "b2.jsonl"
    _write_jsonl(p1, [_packet_row("KC_1", "x")])
    _write_jsonl(p2, [_packet_row("KC_1", "x")])
    config = {
        "intrinsic": {"P-Q": str(p1), "P-G": str(p2)},
        "commit": "abc123",
        "n": 2,
    }
    manifest = build_manifest(config)
    check("build_manifest resolves nested .jsonl paths to stats records",
          manifest["intrinsic"]["P-Q"]["row_count"] == 1)
    check("build_manifest carries non-path scalars through unchanged",
          manifest["commit"] == "abc123" and manifest["n"] == 2)


def test_kc_identity_equality():
    same = {"A": {"KC_1", "KC_2"}, "B": {"KC_1", "KC_2"}}
    result = check_kc_identity_equality(same, expected_count=2)
    check("identical 2-KC sets pass with expected_count=2", result.passed)

    mismatched = {"A": {"KC_1", "KC_2"}, "B": {"KC_1", "KC_3"}}
    result = check_kc_identity_equality(mismatched, expected_count=2)
    check("a genuinely different KC set fails, not just a count mismatch", not result.passed)

    wrong_count = {"A": {"KC_1"}, "B": {"KC_1"}}
    result = check_kc_identity_equality(wrong_count, expected_count=159)
    check("equal-but-wrong-sized sets still fail against the expected count", not result.passed)


def test_intrinsic_evidence_hash_equality():
    shared = TMP / "shared.jsonl"
    _write_jsonl(shared, [_packet_row("KC_1", "same evidence")])
    result = check_intrinsic_evidence_hash_equality({"P-Q": shared, "P-G": shared, "P-D": shared})
    check("three conditions pointing at the literal same file pass trivially", result.passed)

    identical_content_diff_files = TMP / "copy.jsonl"
    _write_jsonl(identical_content_diff_files, [_packet_row("KC_1", "same evidence")])
    result = check_intrinsic_evidence_hash_equality({"P-Q": shared, "P-G": identical_content_diff_files})
    check("two different files with byte-identical per-KC evidence still pass", result.passed)

    drifted = TMP / "drifted.jsonl"
    _write_jsonl(drifted, [_packet_row("KC_1", "DIFFERENT evidence")])
    result = check_intrinsic_evidence_hash_equality({"P-Q": shared, "P-G": drifted})
    check("a condition with drifted evidence for the same KC is caught, not waved through",
          not result.passed)


def test_extrinsic_commit_and_decoding_parity():
    same_commit = {"B-Q": "450c88c", "DOS-Q": "450c88c", "P-Q": "450c88c"}
    check("three conditions at the same commit pass", check_extrinsic_commit_parity(same_commit).passed)

    stale_commit = {"B-Q": "e3944aa", "DOS-Q": "e3944aa", "P-Q": "450c88c"}
    result = check_extrinsic_commit_parity(stale_commit)
    check("a stale comparator commit is caught", not result.passed)

    cfg = {"num_ctx": 32768, "seed": 20260812, "temperature": 0}
    same_decoding = {"B-Q": dict(cfg), "DOS-Q": dict(cfg), "P-Q": dict(cfg)}
    check("identical decoding configs pass", check_decoding_config_parity(same_decoding).passed)

    drifted_cfg = dict(cfg)
    drifted_cfg["num_ctx"] = 40960
    mismatched_decoding = {"B-Q": dict(cfg), "DOS-Q": drifted_cfg, "P-Q": dict(cfg)}
    check("a single differing decoding field is caught",
          not check_decoding_config_parity(mismatched_decoding).passed)


def test_assert_no_stop_conditions_raises():
    from verify_r9_experimental_matrix import VerificationResult
    all_pass = [VerificationResult("x", True), VerificationResult("y", True)]
    try:
        assert_no_stop_conditions(all_pass)
        raised = False
    except ExperimentalInvariantError:
        raised = True
    check("all-passing results do not raise", not raised)

    one_fail = [VerificationResult("x", True), VerificationResult("y", False, "boom")]
    try:
        assert_no_stop_conditions(one_fail)
        raised = False
    except ExperimentalInvariantError as exc:
        raised = "boom" in str(exc)
    check("a single failed invariant raises ExperimentalInvariantError with the failure detail", raised)


def main() -> None:
    print("=" * 70)
    print("discover_r9_evaluation_artifacts / verify_r9_experimental_matrix — self-test")
    print("No API key required. No network calls. No cost.")
    print("=" * 70)
    tests = [
        test_artifact_stats_and_missing_file, test_build_manifest_preserves_structure,
        test_kc_identity_equality, test_intrinsic_evidence_hash_equality,
        test_extrinsic_commit_and_decoding_parity, test_assert_no_stop_conditions_raises,
    ]
    for t in tests:
        print(f"\n-- {t.__name__} --")
        t()

    print("\n" + "=" * 70)
    print(f"{len(CHECKS_PASSED)} passed, {len(CHECKS_FAILED)} failed")
    if CHECKS_FAILED:
        print("\nFAILURES:")
        for name, detail in CHECKS_FAILED:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
