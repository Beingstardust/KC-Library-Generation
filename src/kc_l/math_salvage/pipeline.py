from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from kc_l.math_salvage.io import read_jsonl, write_json, write_jsonl
from kc_l.math_salvage.qc import qc_pages
from kc_l.math_salvage.mineru_salvage import (
    run_mineru_for_page_range,
    find_mineru_outputs,
    parse_equations_from_content_list,
    dedupe_against_existing_equations,
)

def run_step3_6_for_doc(
    doc_id: str,
    enriched_out_dir: Path,
    step2_out_dir: Path,
    pdf_path: Path,
    out_dir: Path,
    audit_logs_dir: Path,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    pages = read_jsonl(enriched_out_dir / "pages.jsonl")
    blocks = read_jsonl(enriched_out_dir / "blocks_enriched.jsonl")

    qc_cfg = cfg["qc"]
    qc_rows = qc_pages(doc_id, pages, blocks, enriched_out_dir, step2_out_dir, qc_cfg)
    write_jsonl(out_dir / "math_qc.page.jsonl", qc_rows)

    suspect_pages = [r for r in qc_rows if r["suspect"]]
    suspect_idxs = [int(r["page_index"]) for r in suspect_pages]

    salvage_cfg = cfg["salvage"]
    mineru_cfg = salvage_cfg["mineru"]
    dedupe_cfg = cfg.get("dedupe", {})

    salvage_blocks: List[Dict[str, Any]] = []
    salvage_attempts: List[Dict[str, Any]] = []

    if bool(salvage_cfg.get("enabled", True)) and bool(mineru_cfg.get("enabled", True)) and suspect_idxs:
        raw_root = out_dir / "mineru_salvage" / "raw_output"
        raw_root.mkdir(parents=True, exist_ok=True)

        window = int(mineru_cfg.get("page_window", 0))

        for pi in suspect_idxs:
            s = max(0, pi - window)
            e = pi + window

            job_dir = raw_root / f"p_{s:04d}_{e:04d}"
            job_dir.mkdir(parents=True, exist_ok=True)

            rc = run_mineru_for_page_range(
                pdf_path=pdf_path,
                out_dir=job_dir,
                cfg=mineru_cfg,
                page_start=s,
                page_end=e,
                audit_logs_dir=audit_logs_dir,
            )
            salvage_attempts.append({"page_index": pi, "range": [s, e], **rc})

            if rc["returncode"] != 0:
                continue

            content_list, middle = find_mineru_outputs(job_dir)
            if not content_list:
                continue

            eqs = parse_equations_from_content_list(doc_id, content_list)
            salvage_blocks.extend(eqs)

        if bool(dedupe_cfg.get("enabled", True)):
            salvage_blocks = dedupe_against_existing_equations(
                salvage_eqs=salvage_blocks,
                existing_blocks=blocks,
                iou_threshold=float(dedupe_cfg.get("iou_threshold", 0.65)),
            )

    failed_attempts = [a for a in salvage_attempts if int(a.get("returncode", 1)) != 0]
    if suspect_idxs and failed_attempts:
        raise RuntimeError(
            f"Step3.6 salvage failed for {doc_id}: "
            f"{len(failed_attempts)}/{len(salvage_attempts)} attempt(s) returned non-zero."
        )

    # Write per-doc outputs
    write_jsonl(out_dir / "blocks_salvage.jsonl", salvage_blocks)
    write_jsonl(out_dir / "blocks_enriched.jsonl", blocks)  # copy-through for convenience
    write_jsonl(out_dir / "pages.jsonl", pages)

    merged = list(blocks) + list(salvage_blocks)
    write_jsonl(out_dir / "blocks_merged.jsonl", merged)

    summary = {
        "doc_id": doc_id,
        "n_pages": len(pages),
        "n_blocks_enriched": len(blocks),
        "qc": {
            "n_suspect_pages": len(suspect_idxs),
        },
        "salvage": {
            "enabled": bool(salvage_cfg.get("enabled", True)),
            "mineru_backend": mineru_cfg.get("backend"),
            "mineru_device": mineru_cfg.get("device"),
            "attempts": len(salvage_attempts),
            "salvage_blocks_added": len(salvage_blocks),
        }
    }
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "salvage_attempts.json", salvage_attempts)

    return summary