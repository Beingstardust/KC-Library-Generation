"""Self-test for build_rubric_sentinels_v3.py. Zero API key, zero network calls, zero cost."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from build_rubric_sentinels_v3 import (
    RubricSentinel,
    check_sentinel_coverage,
    freeze_hash,
    load_sentinels,
    missing_required_categories,
    write_sentinels,
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


def _sentinel(sid="S1", category="correct_definition"):
    return RubricSentinel(
        sentinel_id=sid, kc_id="KC_TEST", canonical_name="Test KC", category=category,
        provenance="synthetic fixture", draft_body="a faithful draft",
        system_evidence=({"auth_id": "SYS_001", "doc_id": "D1", "page_index": 1, "text": "x"},),
        authority_evidence=({"auth_id": "AUTH_001", "doc_id": "D1", "page_index": 1, "text": "x"},),
        expected_f1="PASS", expected_f2="PASS", expected_f3="PASS", expected_f4="PASS",
        expected_f5="PASS", rationale="test rationale",
    )


def test_roundtrip():
    s = _sentinel()
    tmp = Path(tempfile.mkdtemp()) / "sentinels.jsonl"
    write_sentinels(tmp, [s])
    loaded = load_sentinels(tmp)
    check("roundtrip preserves sentinel_id", loaded[0].sentinel_id == s.sentinel_id)
    check("roundtrip preserves expected labels",
          (loaded[0].expected_f1, loaded[0].expected_f2, loaded[0].expected_f3,
           loaded[0].expected_f4, loaded[0].expected_f5) == ("PASS", "PASS", "PASS", "PASS", "PASS"))
    check("roundtrip preserves system_evidence as a tuple of dicts",
          loaded[0].system_evidence == s.system_evidence)


def test_freeze_hash_detects_label_change():
    s1 = _sentinel()
    s2 = RubricSentinel(**{**s1.__dict__, "expected_f3": "FAIL"})
    h1 = freeze_hash([s1])
    h2 = freeze_hash([s2])
    check("changing one expected label changes the freeze hash", h1 != h2)
    check("re-hashing the same suite is stable", freeze_hash([s1]) == h1)


def test_coverage_and_missing_categories():
    only_one = [_sentinel("S1", "correct_definition")]
    missing = missing_required_categories(only_one)
    check("a suite with only 1 of 13 required categories reports 12 missing", len(missing) == 12)
    check("correct_definition itself is not reported missing", "correct_definition" not in missing)

    counts = check_sentinel_coverage(only_one)
    check("coverage counts reflect the single category", counts == {"correct_definition": 1})


def main() -> None:
    print("=" * 70)
    print("build_rubric_sentinels_v3 — self-test")
    print("No API key required. No network calls. No cost.")
    print("=" * 70)
    tests = [test_roundtrip, test_freeze_hash_detects_label_change, test_coverage_and_missing_categories]
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
