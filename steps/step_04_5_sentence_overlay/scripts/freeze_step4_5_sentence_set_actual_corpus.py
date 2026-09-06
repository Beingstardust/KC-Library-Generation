from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


REQUIRED_TOP_LEVEL = [
    "sentence_corpus.jsonl",
    "sentence_stats.json",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_active_manifest(pointer_path: Path) -> Path:
    pointer_path = pointer_path.resolve()
    target_name = read_text(pointer_path)
    if not target_name:
        raise RuntimeError(f"ACTIVE pointer is empty: {pointer_path}")
    target = Path(target_name)
    if target.is_absolute():
        return target.resolve()
    return (pointer_path.parent / target).resolve()


def normalize_docs_map(docs_obj: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(docs_obj, dict):
        return {str(k): v for k, v in docs_obj.items() if isinstance(v, dict)}
    if isinstance(docs_obj, list):
        out: Dict[str, Dict[str, Any]] = {}
        for row in docs_obj:
            if not isinstance(row, dict):
                raise TypeError(f"docs entry is not a dict: {type(row).__name__}")
            doc_id = row.get("doc_id")
            if not doc_id:
                raise KeyError("docs entry missing doc_id")
            doc_id = str(doc_id)
            if doc_id in out:
                raise ValueError(f"duplicate doc_id in docs: {doc_id}")
            out[doc_id] = row
        return out
    raise TypeError(f"Unsupported docs container: {type(docs_obj).__name__}")


def artifact_entry(path: Path) -> Dict[str, Any]:
    return {"path": str(path.resolve())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Freeze actual-corpus Step 4.5 sentence overlay set.")
    ap.add_argument("--run-id", required=True, type=str)
    ap.add_argument("--processed-root", required=True, type=str)
    ap.add_argument("--sets-dir", required=True, type=str)
    ap.add_argument("--active-step4", required=True, type=str)
    ap.add_argument("--run-dir-step4-5", required=True, type=str)
    ap.add_argument("--timezone", default="Europe/Berlin", type=str)
    args = ap.parse_args()

    run_id = args.run_id.strip()
    processed_root = Path(args.processed_root).resolve()
    sets_dir = Path(args.sets_dir).resolve()
    active_step4 = Path(args.active_step4).resolve()
    run_dir_step4_5 = Path(args.run_dir_step4_5).resolve()

    ensure_dir(sets_dir)

    overlay_dir = processed_root / run_id
    if not overlay_dir.exists():
        raise FileNotFoundError(f"Missing Step 4.5 processed dir: {overlay_dir}")

    missing_top = [str(overlay_dir / rel) for rel in REQUIRED_TOP_LEVEL if not (overlay_dir / rel).exists()]
    if missing_top:
        raise RuntimeError(json.dumps({"missing_top_level_files": missing_top}, indent=2))

    sentence_corpus_path = overlay_dir / "sentence_corpus.jsonl"
    sentence_stats_path = overlay_dir / "sentence_stats.json"
    sentence_stats = read_json(sentence_stats_path)

    step4_manifest_path = resolve_active_manifest(active_step4)
    if not step4_manifest_path.exists():
        raise FileNotFoundError(f"Resolved Step 4 set missing: {step4_manifest_path}")

    step4_manifest = read_json(step4_manifest_path)
    step4_docs = normalize_docs_map(step4_manifest.get("docs"))

    stats_docs_obj = sentence_stats.get("docs")
    if not isinstance(stats_docs_obj, dict):
        raise RuntimeError("sentence_stats.json does not expose docs as a mapping.")

    stats_docs = {str(k): v for k, v in stats_docs_obj.items() if isinstance(v, dict)}
    doc_ids = sorted(set(step4_docs.keys()) & set(stats_docs.keys()))
    if not doc_ids:
        raise RuntimeError("No overlapping doc_ids between Step 4 set and sentence_stats.json docs.")

    docs_out: Dict[str, Dict[str, Any]] = {}
    for doc_id in doc_ids:
        step4_row = step4_docs[doc_id]
        stats_row = stats_docs[doc_id]

        docs_out[doc_id] = {
            "doc_id": doc_id,
            "run_id_step4_5": run_id,
            "run_id": run_id,
            "sentence_overlay_out_dir": str(overlay_dir),
            "processed_out_dir": str(overlay_dir),
            "sentence_corpus_path": str(sentence_corpus_path),
            "sentence_stats_path": str(sentence_stats_path),
            "step4_index_out_dir": str(step4_row.get("index_out_dir", step4_row.get("processed_out_dir", ""))),
            "step4_patch_out_dir": str(step4_row.get("step4_patch_out_dir", step4_row.get("patch_out_dir", ""))),
            "step3_out_dir": str(step4_row.get("step3_out_dir", "")),
            "step3_6_out_dir": str(step4_row.get("step3_6_out_dir", "")),
            "n_blocks_total": int(stats_row.get("n_blocks_total", 0)),
            "n_blocks_with_text": int(stats_row.get("n_blocks_with_text", 0)),
            "n_sentences": int(stats_row.get("n_sentences", 0)),
            "n_sentences_without_page_index": int(stats_row.get("n_sentences_without_page_index", 0)),
            "block_corpus_path": str(stats_row.get("block_corpus_path", "")),
            "page_patch_index_path": str(stats_row.get("page_patch_index_path", "")),
            "page_reveal_groups_path": str(stats_row.get("page_reveal_groups_path", "")),
            "flag_counts": stats_row.get("flag_counts", {}),
            "artifacts": {
                "sentence_overlay_out_dir": artifact_entry(overlay_dir),
                "sentence_corpus.jsonl": artifact_entry(sentence_corpus_path),
                "sentence_stats.json": artifact_entry(sentence_stats_path),
            },
            "stats": stats_row,
        }

    set_id = f"{run_id}_step4_5_sentence_set"
    set_path = sets_dir / f"{set_id}.json"
    active_pointer = sets_dir / "ACTIVE_STEP4_5_SET.txt"

    set_obj = {
        "set_id": set_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timezone": args.timezone,
        "step": "step4_5_sentence_overlay",
        "run_id_step4_5": run_id,
        "run_id": run_id,
        "run_dir_step4_5": str(run_dir_step4_5),
        "input_step4_set": step4_manifest_path.name,
        "doc_count": len(docs_out),
        "sentence_corpus_path": str(sentence_corpus_path),
        "sentence_stats_path": str(sentence_stats_path),
        "summary": {
            "step4_set_id": step4_manifest.get("set_id"),
            "n_docs_total": int(sentence_stats.get("n_docs_total", 0)),
            "docs_with_sentences": int(sentence_stats.get("docs_with_sentences", 0)),
            "n_blocks_total": int(sentence_stats.get("n_blocks_total", 0)),
            "n_blocks_with_text": int(sentence_stats.get("n_blocks_with_text", 0)),
            "n_sentences_total": int(sentence_stats.get("n_sentences_total", 0)),
            "invalid_sentence_rows": int(sentence_stats.get("invalid_sentence_rows", 0)),
            "sentences_with_patch_id": int(sentence_stats.get("sentences_with_patch_id", 0)),
            "sentences_with_reveal_group_id": int(sentence_stats.get("sentences_with_reveal_group_id", 0)),
            "flag_counts": sentence_stats.get("flag_counts", {}),
            "layer_counts": sentence_stats.get("layer_counts", {}),
        },
        "docs": docs_out,
    }

    set_path.write_text(json.dumps(set_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    active_pointer.write_text(set_path.name + "\n", encoding="utf-8")

    print(json.dumps(
        {
            "status": "ok",
            "set_path": str(set_path),
            "active_pointer": str(active_pointer),
            "doc_count": len(docs_out),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
