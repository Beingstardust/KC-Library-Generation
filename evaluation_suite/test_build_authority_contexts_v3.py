"""Self-test for build_authority_contexts_v3.py. Zero API key, zero network calls, zero cost."""
from __future__ import annotations

import sys

from build_authority_contexts_v3 import (
    AuthorityContextError,
    authority_manifest_row,
    combine_authority_passages,
    source_identity_key,
    strip_system_identity,
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


def expect_raises(fn, exc_type=AuthorityContextError) -> bool:
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def test_source_identity_key():
    p = {"doc_id": "D1", "page_index": 3, "block_id": "b7", "text": "x"}
    check("source_identity_key uses (doc_id, page_index, block_id)",
          source_identity_key(p) == ("D1", 3, "b7"))

    p2 = {"doc_id": "D1", "page_index": 3, "sentence_id": "s2", "text": "x"}
    check("falls back to sentence_id when block_id is absent",
          source_identity_key(p2) == ("D1", 3, "s2"))

    check("a passage with no source coordinate raises rather than silently keying on text",
          expect_raises(lambda: source_identity_key({"text": "orphan"})))


def test_strip_system_identity_whitelist():
    dirty = {
        "doc_id": "D1", "page_index": 1, "block_id": "b1", "text": "content",
        "retrieval_score": 0.91, "system": "proposed", "method": "bm25_dense_hybrid",
        "packet_support_state": "draftable",
    }
    clean = strip_system_identity(dirty)
    check("only whitelisted fields survive", set(clean) == {"doc_id", "page_index", "block_id", "text"})
    check("retrieval_score is stripped", "retrieval_score" not in clean)
    check("system label is stripped", "system" not in clean)
    check("method/support-state fields are stripped", "method" not in clean and "packet_support_state" not in clean)


def _p(doc, page, block, text):
    return {"doc_id": doc, "page_index": page, "block_id": block, "text": text}


def test_combine_dedup_by_source_identity_not_text():
    same_location_two_extractors = {
        "proposed": [_p("D1", 1, "b1", "clean rendering")],
        "base_dense": [_p("D1", 1, "b1", "damaged r3nd3ring")],  # same location, different text
        "dos_rag": [_p("D2", 5, "b9", "a different passage entirely")],
    }
    items = combine_authority_passages(same_location_two_extractors)
    check("same source location from two systems collapses to ONE authority item",
          len(items) == 2, f"got {len(items)} items")
    check("the FIRST system in iteration order wins the text for a shared location "
          "(deterministic tie-break, not arbitrary)",
          items[0]["text"] == "clean rendering")


def test_combine_strips_and_assigns_ids_in_source_order():
    system_passages = {
        "proposed": [_p("D2", 1, "b1", "second doc first block")],
        "base_dense": [_p("D1", 3, "b2", "first doc, later page")],
        "dos_rag": [_p("D1", 1, "b1", "first doc, first page")],
    }
    items = combine_authority_passages(system_passages)
    check("three distinct source locations produce three items", len(items) == 3)
    check("items are ordered by (doc_id, page_index, block_id), not by which system found them",
          [i["doc_id"] for i in items] == ["D1", "D1", "D2"])
    check("AUTH ids are assigned 001.. in that source order",
          [i["auth_id"] for i in items] == ["AUTH_001", "AUTH_002", "AUTH_003"])
    check("no item carries any field outside the neutral whitelist",
          all(set(i) <= {"doc_id", "page_index", "block_id", "sentence_id", "text", "auth_id"} for i in items))


def test_augmentation_passages_are_lowest_priority():
    system_passages = {"proposed": [_p("D1", 1, "b1", "system-found text")]}
    augmentation = [_p("D1", 1, "b1", "augmentation-found text (should lose)")]
    items = combine_authority_passages(system_passages, augmentation_passages=augmentation)
    check("a system's own passage at a location beats an augmentation copy of the same location",
          len(items) == 1 and items[0]["text"] == "system-found text")

    augmentation_only = [_p("D3", 9, "b3", "only found via augmentation")]
    items2 = combine_authority_passages({"proposed": []}, augmentation_passages=augmentation_only)
    check("an augmentation-only location is still included when no system found it",
          len(items2) == 1 and items2[0]["text"] == "only found via augmentation")


def test_authority_manifest_row_and_reproducibility():
    items = combine_authority_passages({
        "proposed": [_p("D1", 1, "b1", "alpha beta gamma"), _p("D1", 2, "b2", "delta")],
    })
    row = authority_manifest_row("KC_TEST", "Test KC", items)
    check("authority_item_count matches", row.authority_item_count == 2)
    check("authority_chars sums item text lengths", row.authority_chars == len("alpha beta gamma") + len("delta"))
    check("approximate_token_count is a whitespace word count, not a real tokenizer claim",
          row.authority_approximate_token_count == 3 + 1)
    check("source_documents is a sorted, deduplicated doc_id tuple", row.source_documents == ("D1",))

    items_again = combine_authority_passages({
        "proposed": [_p("D1", 1, "b1", "alpha beta gamma"), _p("D1", 2, "b2", "delta")],
    })
    row_again = authority_manifest_row("KC_TEST", "Test KC", items_again)
    check("the same input passages produce a byte-reproducible sha256 (freezable, not run-dependent)",
          row.sha256 == row_again.sha256)


def main() -> None:
    print("=" * 70)
    print("build_authority_contexts_v3 — self-test")
    print("No API key required. No network calls. No cost.")
    print("=" * 70)
    tests = [
        test_source_identity_key, test_strip_system_identity_whitelist,
        test_combine_dedup_by_source_identity_not_text,
        test_combine_strips_and_assigns_ids_in_source_order,
        test_augmentation_passages_are_lowest_priority,
        test_authority_manifest_row_and_reproducibility,
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
