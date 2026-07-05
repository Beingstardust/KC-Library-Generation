from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

NEW_FILE_PATHS = [
    REPO_ROOT / "src" / "kc_l" / "kc_drafting" / "evidence_lane_policy.py",
    REPO_ROOT / "scripts" / "experimental" / "step67a_build_field_lane_packets_generic.py",
    REPO_ROOT / "tests" / "test_evidence_lane_policy.py",
    REPO_ROOT / "tests" / "test_step67_sidecar_domain_agnosticity.py",
    REPO_ROOT / "docs" / "operator_notes" / "STEP67_GENERIC_LANE_POLICY_2026-04-28.md",
]


def _join(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN_TERMS = [
    _join("k", "means"),
    _join("k", "-", "means"),
    _join("j", "ac", "card"),
    _join("g", "ini"),
    _join("h", "unt"),
    _join("co", "re ", "po", "int"),
    _join("bo", "rder ", "po", "int"),
    _join("no", "ise ", "po", "int"),
    _join("eu", "clid", "ean"),
    _join("ma", "hal", "an", "obis"),
    _join("db", "scan"),
    _join("ep", "s"),
    _join("min", "pt", "s"),
    _join("info", "rmation ", "ga", "in"),
    _join("confu", "sion ", "mat", "rix"),
    _join("na", "ive ", "ba", "yes"),
    _join("ba", "yes"),
    _join("lap", "lace"),
    _join("gem", "ma4"),
    _join("gem", "ma3"),
    _join("q", "wen3"),
]


def _term_pattern(term: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in term.split(" ")]
    body = r"\s+".join(parts)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def test_new_files_avoid_forbidden_domain_and_model_terms() -> None:
    for path in NEW_FILE_PATHS:
        text = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_TERMS:
            assert _term_pattern(term).search(text) is None, f"{path} contains forbidden term {term!r}"


def test_new_code_files_avoid_hardcoded_reference_artifact_paths() -> None:
    code_paths = [
        REPO_ROOT / "src" / "kc_l" / "kc_drafting" / "evidence_lane_policy.py",
        REPO_ROOT / "scripts" / "experimental" / "step67a_build_field_lane_packets_generic.py",
    ]
    forbidden_path_fragments = [
        "_reference_artifacts",
        "step67_sidecar_packets_40",
        "candidate_sentence_overlay.jsonl",
        "2026-04-28_161958",
        "2026-04-28_002730",
    ]

    for path in code_paths:
        text = path.read_text(encoding="utf-8").lower()
        for fragment in forbidden_path_fragments:
            assert fragment not in text, f"{path} contains hardcoded artifact fragment {fragment!r}"


def test_new_files_do_not_hardcode_literal_uppercase_kc_identifiers() -> None:
    pattern = re.compile(r"\b" + "K" + "C_" + r"[A-Z0-9_]+\b")
    for path in NEW_FILE_PATHS:
        text = path.read_text(encoding="utf-8")
        assert pattern.search(text) is None, f"{path} contains a literal uppercase kc identifier"


def _run_direct() -> None:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("TEST_STEP67_SIDECAR_DOMAIN_AGNOSTICITY_OK")


if __name__ == "__main__":
    _run_direct()
