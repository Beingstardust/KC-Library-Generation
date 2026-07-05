from __future__ import annotations

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    _direct_overlay_signal_hits,
    _direct_overlay_target_signals,
)
from kc_l.retrieval_gate.evidence_stage_v3_scored_candidates import (
    _direct_overlay_supplement_signal_hits,
)


def test_candidate_bank_direct_overlay_accepts_uppercase_acronym_signal() -> None:
    raw_row = {"target_signals": ["ABC"], "sentence_text": "ABC is stated locally."}
    signals = _direct_overlay_target_signals(raw_row)
    assert "ABC" in signals

    matched_terms, matched_tokens, surface = _direct_overlay_signal_hits(
        {"text_norm": "abc is stated locally", "source_block_norm": "", "heading_norm": ""},
        signals,
    )

    assert matched_terms == ["ABC"]
    assert "abc" in matched_tokens
    assert surface == "text"


def test_candidate_bank_direct_overlay_rejects_lowercase_single_token_signal() -> None:
    raw_row = {"target_signals": ["shared"], "sentence_text": "shared appears locally."}
    signals = _direct_overlay_target_signals(raw_row)
    assert "shared" not in {signal.lower() for signal in signals}


def test_scored_direct_overlay_accepts_uppercase_acronym_signal() -> None:
    candidate_row = {
        "candidate_source": "direct_overlay_supplement",
        "support_profile": {
            "direct_overlay_supplement": True,
            "target_signals": ["ABC"],
        },
    }
    hits = _direct_overlay_supplement_signal_hits(
        candidate_row,
        context={"text_norm": "abc is stated locally", "source_block_norm": "", "heading_norm": ""},
    )

    assert hits["matched_terms"] == ["ABC"]
    assert "abc" in hits["matched_tokens"]
    assert hits["text_term_count"] == 1
    assert hits["best_surface"] == "text"


def test_scored_direct_overlay_rejects_lowercase_single_token_signal() -> None:
    candidate_row = {
        "candidate_source": "direct_overlay_supplement",
        "support_profile": {
            "direct_overlay_supplement": True,
            "target_signals": ["shared"],
        },
    }
    hits = _direct_overlay_supplement_signal_hits(
        candidate_row,
        context={"text_norm": "shared appears locally", "source_block_norm": "", "heading_norm": ""},
    )

    assert hits["matched_terms"] == []
    assert hits["matched_tokens"] == []
    assert hits["text_term_count"] == 0


if __name__ == "__main__":
    test_candidate_bank_direct_overlay_accepts_uppercase_acronym_signal()
    test_candidate_bank_direct_overlay_rejects_lowercase_single_token_signal()
    test_scored_direct_overlay_accepts_uppercase_acronym_signal()
    test_scored_direct_overlay_rejects_lowercase_single_token_signal()
    print("TEST_STEP5X_DIRECT_OVERLAY_ACRONYM_SIGNAL_OK")
