"""
Build System B's "source units" (the passage-level input to Duan et al.'s per-unit
KC generation step) from this project's own retrieval-index block corpus.

A source unit = a non-overlapping 3-page window of one source document, built from
the SAME 4 documents ablation_1's evidence stage actually cited (confirmed by
extracting doc_id values from its kc_evidence_packs.jsonl). Only blocks already
marked is_indexed=true are used -- this project's own step 4 retrieval-index build
already resolved cross-layer (pymupdf/docling/mineru) duplication per page via that
flag, so re-deriving a layer-preference here would just re-implement logic that
already exists upstream.

No domain-specific content: doc IDs and the corpus root are passed as arguments,
nothing about Data Mining is hardcoded in the grouping/windowing logic itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PAGES_PER_WINDOW = 3
MIN_UNIT_CHARS = 200  # windows with less real text than this are skipped, not force-included


def load_indexed_blocks(block_corpus_path: Path) -> list[dict]:
    blocks = []
    with block_corpus_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("is_indexed"):
                blocks.append(row)
    return blocks


def build_units_for_doc(doc_id: str, block_corpus_path: Path) -> list[dict]:
    blocks = load_indexed_blocks(block_corpus_path)
    # Stable order: file order already reflects reading order within a page;
    # group by page first, then by window.
    windows: dict[int, list[dict]] = {}
    for b in blocks:
        page_index = b["page_index"]
        window_id = page_index // PAGES_PER_WINDOW
        windows.setdefault(window_id, []).append(b)

    units = []
    skipped = 0
    for window_id in sorted(windows.keys()):
        window_blocks = windows[window_id]
        page_start = min(b["page_index"] for b in window_blocks)
        page_end = max(b["page_index"] for b in window_blocks)
        text = " ".join(b["text"].strip() for b in window_blocks if b.get("text", "").strip())
        if len(text) < MIN_UNIT_CHARS:
            skipped += 1
            continue
        units.append(
            {
                "doc_id": doc_id,
                "page_start": page_start,
                "page_end": page_end,
                "block_count": len(window_blocks),
                "char_count": len(text),
                "text": text,
            }
        )

    print(f"[{doc_id}] windows built: {len(units)}, skipped (below {MIN_UNIT_CHARS} chars): {skipped}")
    return units


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-index-root", required=True, help="e.g. data/processed/retrieval_index/20260727T022835Z_9e856df6")
    ap.add_argument("--index-run-id", required=True, help="e.g. 20260727T022835Z_9e856df6 (the subdir under each doc)")
    ap.add_argument("--doc-ids", required=True, nargs="+", help="doc_id values, same set ablation_1's evidence stage cited")
    ap.add_argument("--out", required=True, help="output source_units.jsonl path")
    args = ap.parse_args()

    root = Path(args.retrieval_index_root)
    all_units = []
    for doc_id in args.doc_ids:
        block_corpus_path = root / doc_id / args.index_run_id / "block_text_corpus.jsonl"
        if not block_corpus_path.exists():
            raise FileNotFoundError(f"block_text_corpus.jsonl not found for {doc_id}: {block_corpus_path}")
        all_units.extend(build_units_for_doc(doc_id, block_corpus_path))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, unit in enumerate(all_units, start=1):
            unit_id = f"SU_{i:04d}"
            row = {"unit_id": unit_id, **unit}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"TOTAL_SOURCE_UNITS={len(all_units)}")
    print(f"OUT_PATH={out_path}")


if __name__ == "__main__":
    main()
