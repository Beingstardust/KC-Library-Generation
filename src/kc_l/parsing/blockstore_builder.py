from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from kc_l.audit.manifests import build_input_manifest, build_output_manifest
from kc_l.audit.run_audit import RunAudit
from kc_l.blockstore.writers import write_jsonl, page_to_dict, block_to_dict
from kc_l.parsing.page_render import render_pages
from kc_l.parsing.pymupdf_layer import extract_pymupdf
from kc_l.parsing.docling_layer import extract_docling
from kc_l.parsing.mineru_layer import extract_mineru
from kc_l.utils.fs import ensure_dir, copy_file
from kc_l.utils.hash import sha256_file


def _freeze_input(pdf_path: Path, frozen_root: Path) -> Dict[str, Any]:
    sha = sha256_file(pdf_path)
    target_dir = frozen_root / sha
    ensure_dir(target_dir)
    dst = target_dir / pdf_path.name
    if not dst.exists():
        copy_file(pdf_path, dst)
    return {"sha256": sha, "frozen_path": str(dst)}


def _counts_by(items: List[dict], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        v = str(it.get(key))
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))


def build_blockstore(cfg: Dict[str, Any], audit: RunAudit) -> Dict[str, Any]:
    doc_id = cfg["doc"]["doc_id"]
    pdf_path = Path(cfg["doc"]["pdf_path"]).resolve()

    processed_root = Path(cfg["output"]["processed_blockstore_dir"])
    ensure_dir(processed_root)

    # Run id is the audit folder name
    run_id = audit.run_dir.name

    out_dir = processed_root / doc_id / run_id
    ensure_dir(out_dir)

    work_root = Path(cfg["output"].get("work_dir", "data/work"))
    use_work = bool(cfg["output"].get("use_work_dir_for_external_tools", False))
    keep_work = bool(cfg["output"].get("keep_work_dir", False))

    tool_work_base = None
    if use_work:
        ensure_dir(work_root)
        short_key = sha256_file(pdf_path)[:12]
        tool_work_base = work_root / run_id / short_key
        ensure_dir(tool_work_base)

    # Input manifest and optional freezing
    input_paths = [pdf_path]
    (audit.run_dir / "input_manifest.json").write_text(json.dumps(build_input_manifest(input_paths), indent=2), encoding="utf-8")

    freeze_info = None
    if bool(cfg["doc"].get("freeze_inputs", False)):
        frozen_root = Path(cfg["doc"].get("frozen_store_dir", "data/raw/frozen"))
        ensure_dir(frozen_root)
        freeze_info = _freeze_input(pdf_path, frozen_root)
        (audit.run_dir / "frozen_input.json").write_text(json.dumps(freeze_info, indent=2), encoding="utf-8")

    # Render page images first (audit-critical)
    pages_img_map = {}
    if bool(cfg["output"].get("render_page_images", True)):
        img_dir = out_dir / "page_images"
        pages_img_map = render_pages(
            pdf_path=pdf_path,
            out_dir=img_dir,
            dpi=int(cfg["output"].get("render_dpi", 144)),
            fmt=str(cfg["output"].get("render_format", "png")),
        )

    # PyMuPDF layer
    pym_cfg = cfg.get("layers", {}).get("pymupdf", {})
    py_res = extract_pymupdf(
        doc_id=doc_id,
        pdf_path=pdf_path,
        out_dir=out_dir / "pymupdf",
        sort_text=bool(pym_cfg.get("sort_text", True)),
        write_raw_dump=bool(pym_cfg.get("write_raw_dump", True)),
    )
    pages = py_res["pages"]
    # attach image info to pages (kept separate in schema)
    pages2 = []
    for p in pages:
        m = pages_img_map.get(p.page_index)
        pages2.append(
            {
                "doc_id": p.doc_id,
                "page_index": p.page_index,
                "width_pt": p.width_pt,
                "height_pt": p.height_pt,
                "rotation": p.rotation,
                "image_relpath": m["relpath"] if m else None,
                "image_sha256": m["sha256"] if m else None,
            }
        )

    # Docling layer
    doc_cfg = cfg.get("layers", {}).get("docling", {})
    doc_cli_dir = (tool_work_base / "docling") if tool_work_base else None
    doc_res = extract_docling(
        doc_id=doc_id,
        pdf_path=pdf_path,
        out_dir=out_dir / "docling",
        cfg=doc_cfg,
        audit_logs_dir=audit.logs_dir,
        cli_output_dir=doc_cli_dir,
    )

    # MinerU layer
    min_cfg = cfg.get("layers", {}).get("mineru", {})
    min_cli_dir = (tool_work_base / "mineru") if tool_work_base else None
    min_res = extract_mineru(
        doc_id=doc_id,
        pdf_path=pdf_path,
        out_dir=out_dir / "mineru",
        cfg=min_cfg,
        audit_logs_dir=audit.logs_dir,
        cli_output_dir=min_cli_dir,
    )
    if tool_work_base and (not keep_work):
        shutil.rmtree(tool_work_base, ignore_errors=True)
    # Merge blocks
    blocks_all = []
    for b in py_res["blocks"]:
        blocks_all.append(block_to_dict(b))
    for b in doc_res["blocks"]:
        blocks_all.append(block_to_dict(b))
    for b in min_res["blocks"]:
        blocks_all.append(block_to_dict(b))

    # Write pages.jsonl + blocks.jsonl
    pages_path = out_dir / "pages.jsonl"
    blocks_path = out_dir / "blocks.jsonl"
    write_jsonl(pages_path, pages2)
    write_jsonl(blocks_path, blocks_all)

    # Layer-level degradation handling (see ORCHESTRATOR_BUILD_STATE.md's Docling
    # degraded-layer-handling entry): a single enabled layer producing zero blocks while at
    # least one other enabled layer succeeds is tolerated - the document-level manifest records
    # which layer(s) degraded and why (from that layer's own layer_status.reason), rather than
    # hard-failing the whole document over one layer's failure. Only genuinely catastrophic
    # input - ALL enabled layers empty, nothing to salvage - still raises (below, after this
    # manifest is written, matching the existing min_pages/min_blocks ordering).
    validation_cfg = cfg.get("validation", {})
    layer_status_by_name = {
        "pymupdf": py_res["layer_status"],
        "docling": doc_res["layer_status"],
        "mineru": min_res["layer_status"],
    }
    layer_block_counts = {
        "pymupdf": len(py_res["blocks"]),
        "docling": len(doc_res["blocks"]),
        "mineru": len(min_res["blocks"]),
    }
    enabled_layers = {
        "pymupdf": bool(pym_cfg.get("enabled", True)),
        "docling": bool(doc_cfg.get("enabled", True)),
        "mineru": bool(min_cfg.get("enabled", True)),
    }
    empty_enabled_layers = [
        layer_name
        for layer_name, enabled in enabled_layers.items()
        if enabled and layer_block_counts.get(layer_name, 0) <= 0
    ]
    non_empty_enabled_layers = [
        layer_name
        for layer_name, enabled in enabled_layers.items()
        if enabled and layer_block_counts.get(layer_name, 0) > 0
    ]
    require_each_layer_nonempty = bool(validation_cfg.get("require_each_enabled_layer_nonempty", False))

    document_level_status = "ok"
    document_level_warnings: List[str] = []
    if require_each_layer_nonempty and empty_enabled_layers and non_empty_enabled_layers:
        document_level_status = "degraded"
        for layer_name in sorted(empty_enabled_layers):
            reason = layer_status_by_name[layer_name].get("reason", "unknown_reason")
            document_level_warnings.append(
                f"Layer '{layer_name}' produced zero blocks (reason: {reason}) - continuing "
                f"with {', '.join(sorted(non_empty_enabled_layers))}."
            )

    # Per-run doc manifest
    doc_manifest = {
        "doc_id": doc_id,
        "run_id": run_id,
        "source_pdf": str(pdf_path),
        "frozen_input": freeze_info,
        "outputs": {
            "pages_jsonl": "pages.jsonl",
            "blocks_jsonl": "blocks.jsonl",
            "page_images_dir": "page_images/" if bool(cfg["output"].get("render_page_images", True)) else None,
            "raw_layers": {
                "pymupdf": "pymupdf/raw_output/",
                "docling": "docling/raw_output/",
                "mineru": "mineru/raw_output/",
            },
        },
        "layer_status": layer_status_by_name,
        "document_level_status": document_level_status,
        "document_level_warnings": document_level_warnings,
    }
    (out_dir / "doc_manifest.json").write_text(json.dumps(doc_manifest, indent=2), encoding="utf-8")

    # Output manifest for the processed outputs
    (audit.run_dir / "output_manifest.processed.json").write_text(
        json.dumps(build_output_manifest(out_dir), indent=2),
        encoding="utf-8",
    )

    # Validation checks (do not pretend this is optional)
    min_pages = int(validation_cfg.get("min_pages", 1))
    min_blocks = int(validation_cfg.get("min_total_blocks", 1))
    if len(pages2) < min_pages:
        raise RuntimeError(f"Validation failed: pages={len(pages2)} < min_pages={min_pages}")
    if len(blocks_all) < min_blocks:
        raise RuntimeError(f"Validation failed: blocks={len(blocks_all)} < min_total_blocks={min_blocks}")
    if require_each_layer_nonempty and empty_enabled_layers and not non_empty_enabled_layers:
        # ALL enabled layers empty - nothing to salvage, unlike the tolerated partial-failure
        # case above (document_level_status="degraded"), which already logged and continued.
        raise RuntimeError(
            "Validation failed: ALL enabled layers produced zero blocks (nothing to salvage): "
            + ", ".join(sorted(empty_enabled_layers))
        )

    # Summary for console and audit
    summary = {
        "doc_id": doc_id,
        "run_id": run_id,
        "n_pages": len(pages2),
        "n_blocks_total": len(blocks_all),
        "blocks_by_layer": _counts_by(blocks_all, "layer"),
        "blocks_by_type": _counts_by(blocks_all, "content_type"),
        "layer_status": doc_manifest["layer_status"],
        "document_level_status": document_level_status,
        "document_level_warnings": document_level_warnings,
        "paths": {
            "processed_out_dir": str(out_dir),
            "audit_run_dir": str(audit.run_dir),
        },
    }

    return {"summary": summary}
