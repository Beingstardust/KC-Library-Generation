from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


REQUIRED_FILE_ARTIFACTS = [
    "block_text_corpus.jsonl",
    "index_rows.jsonl",
    "index_summary.json",
    "retrieval_eval.json",
    "embeddings/embeddings.f32.npy",
    "embeddings/meta.json",
    "vector_index/meta.json",
    "lexical/meta.json",
    "lexical/vocab.json",
    "lexical/idf.f32.npy",
    "lexical/postings_docids.i32.npy",
    "lexical/postings_tfs.i16.npy",
    "lexical/postings_offsets.i64.npy",
]

OPTIONAL_FILE_ARTIFACTS = [
    "retrieval_diagnostics.json",
    "retrieval_eval_diagnostics.json",
    "vector_index/faiss.index",
    "lexical/df.i32.npy",
    "lexical/doclens.i32.npy",
    "lexical/rows.jsonl",
    "embeddings/rows.jsonl",
]

REQUIRED_DIR_ARTIFACTS = [
    "retrieval_traces",
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


def load_active_docs(pointer_path: Path) -> tuple[Path, Dict[str, Dict[str, Any]], Dict[str, Any]]:
    manifest_path = resolve_active_manifest(pointer_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"ACTIVE pointer target missing: {manifest_path}")
    obj = read_json(manifest_path)
    docs_map = normalize_docs_map(obj.get("docs"))
    return manifest_path, docs_map, obj


def artifact_entry(path: Path) -> Dict[str, Any]:
    return {"path": str(path.resolve())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Freeze actual-corpus Step4 index set.")
    ap.add_argument("--run-id", required=True, type=str)
    ap.add_argument("--processed-root", required=True, type=str)
    ap.add_argument("--sets-dir", required=True, type=str)
    ap.add_argument("--active-step3", required=True, type=str)
    ap.add_argument("--active-step3-6", required=True, type=str)
    ap.add_argument("--active-step4-patches", required=True, type=str)
    ap.add_argument("--run-dir-step4-3", required=True, type=str)
    ap.add_argument("--timezone", default="Europe/Amsterdam", type=str)
    args = ap.parse_args()

    run_id = args.run_id.strip()
    processed_root = Path(args.processed_root).resolve()
    sets_dir = Path(args.sets_dir).resolve()
    active_step3 = Path(args.active_step3).resolve()
    active_step3_6 = Path(args.active_step3_6).resolve()
    active_step4_patches = Path(args.active_step4_patches).resolve()
    run_dir_step4_3 = Path(args.run_dir_step4_3).resolve()

    ensure_dir(sets_dir)

    step3_manifest_path, step3_docs, _ = load_active_docs(active_step3)
    step3_6_manifest_path, step3_6_docs, _ = load_active_docs(active_step3_6)
    step4_patches_manifest_path, step4_patch_docs, _ = load_active_docs(active_step4_patches)

    doc_ids = sorted(set(step3_docs.keys()) & set(step3_6_docs.keys()) & set(step4_patch_docs.keys()))
    if not doc_ids:
        raise RuntimeError("No overlapping doc_ids across Step3, Step3.6, and Step4 patches sets.")

    run_summary_path = run_dir_step4_3 / "summary.json"
    if not run_summary_path.exists():
        raise FileNotFoundError(f"Missing Step4.3 run summary: {run_summary_path}")
    run_summary = read_json(run_summary_path)
    rows_summary = run_summary.get("rows_summary", [])
    rows_summary_map = {}
    if isinstance(rows_summary, list):
        for row in rows_summary:
            if isinstance(row, dict) and row.get("doc_id"):
                rows_summary_map[str(row["doc_id"])] = row

    docs_out: Dict[str, Dict[str, Any]] = {}
    failures = []

    for doc_id in doc_ids:
        index_dir = processed_root / doc_id / run_id
        missing_files = [str(index_dir / rel) for rel in REQUIRED_FILE_ARTIFACTS if not (index_dir / rel).exists()]
        missing_dirs = [str(index_dir / rel) for rel in REQUIRED_DIR_ARTIFACTS if not (index_dir / rel).is_dir()]

        if missing_files or missing_dirs:
            failures.append(
                {
                    "doc_id": doc_id,
                    "missing_files": missing_files,
                    "missing_dirs": missing_dirs,
                }
            )
            continue

        step3_row = step3_docs[doc_id]
        step3_6_row = step3_6_docs[doc_id]
        step4_patch_row = step4_patch_docs[doc_id]

        index_summary = read_json(index_dir / "index_summary.json")
        retrieval_eval = read_json(index_dir / "retrieval_eval.json")
        row_summary = rows_summary_map.get(doc_id, {})

        artifacts: Dict[str, Dict[str, Any]] = {
            "index_out_dir": artifact_entry(index_dir),
            "block_text_corpus.jsonl": artifact_entry(index_dir / "block_text_corpus.jsonl"),
            "index_rows.jsonl": artifact_entry(index_dir / "index_rows.jsonl"),
            "index_summary.json": artifact_entry(index_dir / "index_summary.json"),
            "retrieval_eval.json": artifact_entry(index_dir / "retrieval_eval.json"),
            "embeddings/embeddings.f32.npy": artifact_entry(index_dir / "embeddings/embeddings.f32.npy"),
            "embeddings/meta.json": artifact_entry(index_dir / "embeddings/meta.json"),
            "vector_index/meta.json": artifact_entry(index_dir / "vector_index/meta.json"),
            "lexical/meta.json": artifact_entry(index_dir / "lexical/meta.json"),
            "lexical/vocab.json": artifact_entry(index_dir / "lexical/vocab.json"),
            "lexical/idf.f32.npy": artifact_entry(index_dir / "lexical/idf.f32.npy"),
            "lexical/postings_docids.i32.npy": artifact_entry(index_dir / "lexical/postings_docids.i32.npy"),
            "lexical/postings_tfs.i16.npy": artifact_entry(index_dir / "lexical/postings_tfs.i16.npy"),
            "lexical/postings_offsets.i64.npy": artifact_entry(index_dir / "lexical/postings_offsets.i64.npy"),
            "retrieval_traces": artifact_entry(index_dir / "retrieval_traces"),
        }

        for rel in OPTIONAL_FILE_ARTIFACTS:
            p = index_dir / rel
            if p.exists():
                artifacts[rel] = artifact_entry(p)

        docs_out[doc_id] = {
            "doc_id": doc_id,
            "run_id_step4_3": run_id,
            "run_id": run_id,
            "index_out_dir": str(index_dir),
            "processed_out_dir": str(index_dir),
            "step3_out_dir": str(Path(step3_row.get("doctree_out_dir", ""))),
            "step3_6_out_dir": str(Path(step3_6_row.get("math_out_dir", ""))),
            "step4_patch_out_dir": str(Path(step4_patch_row.get("patch_out_dir", step4_patch_row.get("processed_out_dir", "")))),
            "block_text_corpus_path": str(index_dir / "block_text_corpus.jsonl"),
            "index_rows_path": str(index_dir / "index_rows.jsonl"),
            "index_summary_path": str(index_dir / "index_summary.json"),
            "retrieval_eval_path": str(index_dir / "retrieval_eval.json"),
            "embeddings_path": str(index_dir / "embeddings/embeddings.f32.npy"),
            "vector_index_meta_path": str(index_dir / "vector_index/meta.json"),
            "lexical_meta_path": str(index_dir / "lexical/meta.json"),
            "retrieval_traces_dir": str(index_dir / "retrieval_traces"),
            "artifacts": artifacts,
            "summary": index_summary,
            "retrieval_eval": retrieval_eval,
            "row_summary": row_summary,
        }

    if failures:
        raise RuntimeError(json.dumps({"freeze_failures": failures}, indent=2))

    set_id = f"{run_id}_step4_index_set"
    set_path = sets_dir / f"{set_id}.json"
    active_pointer = sets_dir / "ACTIVE_STEP4_SET.txt"

    set_obj = {
        "set_id": set_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timezone": args.timezone,
        "step": "step4_index",
        "run_id_step4_3": run_id,
        "run_id": run_id,
        "run_dir_step4_3": str(run_dir_step4_3),
        "run_summary_path_step4_3": str(run_summary_path),
        "input_step3_set": step3_manifest_path.name,
        "input_step3_6_set": step3_6_manifest_path.name,
        "input_step4_patches_set": step4_patches_manifest_path.name,
        "doc_count": len(docs_out),
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
