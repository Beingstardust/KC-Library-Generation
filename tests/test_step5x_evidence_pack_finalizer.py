from kc_l.retrieval_gate.evidence_pack_finalizer import SourceWindowIndex, finalize_packs


def test_source_window_prefers_source_row_index_over_duplicate_sentence_id() -> None:
    rows = [
        {"sentence_id": "DUP", "doc_id": "D", "block_id": "A", "sent_idx": 0, "sentence_text": "Correct anchor sentence.", "patch_heading": "Correct Section"},
        {"sentence_id": "DUP", "doc_id": "D", "block_id": "B", "sent_idx": 0, "sentence_text": "Wrong duplicate sentence.", "patch_heading": "Wrong Section"},
    ]
    idx = SourceWindowIndex(rows)
    win = idx.window({"sentence_id": "DUP", "source_row_index": 0}, before=0, after=0)
    assert win["resolved"] is True
    assert "Correct anchor sentence" in win["source_window_text"]
    assert "Wrong duplicate" not in win["source_window_text"]


def test_finalize_minimal_pack_keeps_source_bound_core() -> None:
    packs = [{
        "kc_id": "KC_X", "knowledge_unit_id": "KC_X", "knowledge_unit_type": "kc", "canonical_name": "Querying Phase",
        "topic_path_labels": ["Classification"],
        "ordered_pack_for_drafting": [{"role": "definition_kernel", "text": "This process is known as deduction.", "source_row_index": 1, "doc_id": "D", "sentence_id": "s1"}],
    }]
    profiles = [{"kc_id": "KC_X", "accepted_source_cues": [{"term": "deduction"}], "topic_path_labels": ["Classification"]}]
    registry = [{"kc_id": "KC_X", "canonical_name": "Querying Phase"}]
    overlay = [
        {"sentence_id": "s0", "doc_id": "D", "sentence_text": "Classification uses a learned model.", "patch_heading": "Framework"},
        {"sentence_id": "s1", "doc_id": "D", "sentence_text": "This process is known as deduction.", "patch_heading": "Framework"},
        {"sentence_id": "s2", "doc_id": "D", "sentence_text": "The model assigns labels to unlabeled instances.", "patch_heading": "Framework"},
    ]
    finalized, stats, review = finalize_packs(packs=packs, profiles=profiles, registry_rows=registry, scored_rows=[], sentence_overlay_rows=overlay)
    assert stats["pack_count"] == 1
    assert finalized[0]["ordered_pack_for_drafting"]
    text = finalized[0]["ordered_pack_for_drafting"][0]["text"]
    assert "Framework" in text
    assert "deduction" in text


if __name__ == "__main__":
    test_source_window_prefers_source_row_index_over_duplicate_sentence_id()
    test_finalize_minimal_pack_keeps_source_bound_core()
    print("test_step5x_evidence_pack_finalizer: OK")

