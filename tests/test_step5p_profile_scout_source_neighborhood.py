from __future__ import annotations

from kc_l.retrieval_profile.builder import _topic_local_content_scout_windows
from kc_l.retrieval_profile.deterministic import deterministic_label_variants


def _row(text: str, *, page: int, patch: str, heading: str = "") -> dict:
    return {
        "sentence_text": text,
        "doc_id": "DOC_X",
        "page_index": page,
        "patch_id": patch,
        "patch_heading": heading,
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_heading_like": False,
    }


def test_short_target_anchor_expands_to_neighbor_content() -> None:
    kc = {
        "kc_id": "KC_RANDOM",
        "canonical_name": "Models of Randomness",
        "aliases": [],
        "topic_path_labels": ["Cluster Evaluation"],
        "parent_topic_label": "Cluster Evaluation",
        "sibling_labels": [],
    }
    variants = deterministic_label_variants(kc["canonical_name"], [])
    rows = [
        _row("statistical tests for spatial randomness.", page=10, patch="p1", heading="Clustering Tendency"),
        _row(
            "For this approach, generated reference points are compared with actual points in the data space, "
            "and the resulting statistic is used to judge whether the structure is non-random.",
            page=10,
            patch="p1",
            heading="Clustering Tendency",
        ),
        _row("A broad cluster evaluation sentence from another section.", page=11, patch="p2", heading="Cluster Evaluation"),
    ]
    windows = _topic_local_content_scout_windows(
        kc_row=kc,
        source_rows=rows,
        variants=variants,
        max_snippets_per_kc=8,
        dynamic_broad_tokens=set(),
    )
    assert any("generated reference points" in w["text"] for w in windows)
    expanded = [w for w in windows if "generated reference points" in w["text"]][0]
    assert "source_neighborhood_anchor_expansion" in expanded["score_reasons"]
    assert "randomness" in expanded["branch_overlap"]


def test_sibling_context_anchor_can_supply_label_mismatch_neighbor() -> None:
    kc = {
        "kc_id": "KC_INTRINSIC",
        "canonical_name": "Intrinsic Information",
        "aliases": [],
        "topic_path_labels": ["Decision Tree"],
        "parent_topic_label": "Decision Tree",
        "sibling_labels": ["Gain Ratio"],
    }
    variants = deterministic_label_variants(kc["canonical_name"], [])
    rows = [
        _row("Gain Ratio", page=20, patch="p_gain", heading="Gain Ratio"),
        _row(
            "The split information measures the entropy of splitting a node into its child nodes and "
            "penalizes attributes that produce a large number of equally-sized child nodes.",
            page=20,
            patch="p_gain",
            heading="Gain Ratio",
        ),
        _row("Information appears in a broad unrelated sentence.", page=21, patch="p_bad", heading="Other Material"),
    ]
    windows = _topic_local_content_scout_windows(
        kc_row=kc,
        source_rows=rows,
        variants=variants,
        max_snippets_per_kc=8,
        dynamic_broad_tokens={"information"},
    )
    assert any("split information" in w["text"].lower() for w in windows)
    selected = [w for w in windows if "split information" in w["text"].lower()][0]
    assert selected["source_neighborhood_anchor_count"] >= 1
    assert "gain" in selected["branch_overlap"] or "ratio" in selected["branch_overlap"]


def main() -> None:
    test_short_target_anchor_expands_to_neighbor_content()
    test_sibling_context_anchor_can_supply_label_mismatch_neighbor()
    print("TEST_STEP5P_PROFILE_SCOUT_SOURCE_NEIGHBORHOOD_OK")


if __name__ == "__main__":
    main()
