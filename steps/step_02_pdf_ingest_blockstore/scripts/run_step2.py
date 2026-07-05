from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml  # pip install pyyaml

from kc_l.audit.run_audit import RunAudit
from kc_l.parsing.blockstore_builder import build_blockstore


REQUIRED_STEP2_DOC_FILES = ("pages.jsonl", "blocks.jsonl", "doc_manifest.json")


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)



def _normalize_path_text(raw: str) -> str:
    return str(raw).replace("\\", "/")



def _step2_sets_root(cfg: Dict[str, Any]) -> Path:
    return Path(cfg["output"]["processed_blockstore_dir"]) / "_sets"



def _step2_active_pointer_path(cfg: Dict[str, Any]) -> Path:
    return _step2_sets_root(cfg) / "ACTIVE_STEP2_SET.txt"



def _doc_entry_has_required_outputs(doc_entry: Dict[str, Any]) -> bool:
    processed_out_dir_raw = doc_entry.get("processed_out_dir")
    if not isinstance(processed_out_dir_raw, str) or not processed_out_dir_raw.strip():
        return False
    processed_out_dir = Path(processed_out_dir_raw)
    return processed_out_dir.exists() and all((processed_out_dir / name).exists() for name in REQUIRED_STEP2_DOC_FILES)



def _load_existing_step2_docs(active_pointer_path: Path) -> tuple[list[Dict[str, Any]], int]:
    if not active_pointer_path.exists():
        return [], 0

    target_name = active_pointer_path.read_text(encoding="utf-8").strip()
    if not target_name:
        raise RuntimeError(f"Existing Step 2 active pointer is empty: {active_pointer_path}")

    set_path = active_pointer_path.parent / target_name
    if not set_path.exists():
        raise FileNotFoundError(f"Existing Step 2 set manifest is missing: {set_path}")

    data = json.loads(set_path.read_text(encoding="utf-8"))
    docs_raw = data.get("docs")
    if not isinstance(docs_raw, list):
        raise RuntimeError(f"Existing Step 2 set manifest has invalid docs payload: {set_path}")

    kept_docs: list[Dict[str, Any]] = []
    pruned_count = 0
    for item in docs_raw:
        if isinstance(item, dict) and isinstance(item.get("doc_id"), str) and _doc_entry_has_required_outputs(item):
            kept_docs.append(item)
        else:
            pruned_count += 1
    return kept_docs, pruned_count



def _build_step2_doc_entry(result: Dict[str, Any], pdf_path: Path) -> Dict[str, Any]:
    summary = dict(result["summary"])
    paths = dict(summary.get("paths") or {})
    return {
        "doc_id": str(summary["doc_id"]),
        "run_id_step2": str(summary["run_id"]),
        "processed_out_dir": _normalize_path_text(str(paths["processed_out_dir"])),
        "audit_run_dir": _normalize_path_text(str(paths["audit_run_dir"])),
        "source_pdf": _normalize_path_text(str(pdf_path)),
        "summary": summary,
    }



def _write_step2_active_set(cfg: Dict[str, Any], *, run_id: str, doc_entry: Dict[str, Any]) -> tuple[Path, Path, int]:
    if not _doc_entry_has_required_outputs(doc_entry):
        raise RuntimeError(f"Step 2 doc entry is missing required outputs for doc_id={doc_entry.get('doc_id')}")

    sets_root = _step2_sets_root(cfg)
    sets_root.mkdir(parents=True, exist_ok=True)
    active_pointer_path = _step2_active_pointer_path(cfg)

    existing_docs, pruned_count = _load_existing_step2_docs(active_pointer_path)
    docs_by_id = {str(item["doc_id"]): item for item in existing_docs}
    docs_by_id[str(doc_entry["doc_id"])] = doc_entry
    merged_docs = [docs_by_id[doc_id] for doc_id in sorted(docs_by_id)]

    set_id = f"{run_id}_step2_set"
    set_path = sets_root / f"{set_id}.json"
    set_obj = {
        "set_id": set_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timezone": cfg.get("project", {}).get("timezone", "Europe/Amsterdam"),
        "step": "step2",
        "doc_count": len(merged_docs),
        "docs": merged_docs,
    }
    set_path.write_text(json.dumps(set_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    active_pointer_path.write_text(set_path.name, encoding="utf-8")
    return set_path, active_pointer_path, pruned_count



def main() -> int:
    ap = argparse.ArgumentParser(description="STEP 2: PDF ingest into multi-layer BlockStore with full run audit trail.")
    ap.add_argument("--config", type=str, required=True, help="Path to YAML config.")
    ap.add_argument("--pdf", type=str, default=None, help="Override doc.pdf_path from config.")
    ap.add_argument("--doc-id", type=str, default=None, help="Override doc.doc_id from config.")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load_yaml(cfg_path)

    if args.pdf:
        cfg.setdefault("doc", {})["pdf_path"] = args.pdf
    if args.doc_id:
        cfg.setdefault("doc", {})["doc_id"] = args.doc_id

    # Basic config sanity
    pdf_path = Path(cfg["doc"]["pdf_path"])
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc_id = cfg["doc"]["doc_id"]
    if not doc_id or not isinstance(doc_id, str):
        raise ValueError("doc.doc_id must be a non-empty string.")

    audit = RunAudit.from_config(cfg=cfg, step_name="step2", config_path=cfg_path)
    with audit:
        audit.log_kv("doc_id", doc_id)
        audit.log_kv("pdf_path", str(pdf_path))

        result = build_blockstore(cfg=cfg, audit=audit)
        doc_entry = _build_step2_doc_entry(result, pdf_path)
        set_path, active_pointer_path, pruned_count = _write_step2_active_set(
            cfg,
            run_id=str(result["summary"]["run_id"]),
            doc_entry=doc_entry,
        )
        audit.log_kv("step2_set_manifest", _normalize_path_text(str(set_path)))
        audit.log_kv("step2_active_set_pointer", _normalize_path_text(str(active_pointer_path)))
        if pruned_count:
            audit.log_kv("step2_docs_pruned_from_active_set", pruned_count)
        result["summary"].setdefault("paths", {})
        result["summary"]["paths"]["step2_set_manifest"] = _normalize_path_text(str(set_path))
        result["summary"]["paths"]["active_step2_pointer"] = _normalize_path_text(str(active_pointer_path))

        # Write a short top-level summary into the audit folder too
        summary_path = audit.run_dir / "summary.json"
        summary_path.write_text(json.dumps(result["summary"], indent=2), encoding="utf-8")

    print("\nSTEP2 COMPLETE")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
