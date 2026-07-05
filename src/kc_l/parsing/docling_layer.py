from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kc_l.blockstore.schema import BlockRecord
from kc_l.utils.fs import ensure_dir
from kc_l.utils.subprocess_run import run_cmd


def _list_rel_files(root: Path, limit: int = 200) -> List[str]:
    """
    Debug helper for audit. Returns up to `limit` relative file paths under root.
    """
    files: List[str] = []
    if not root.exists():
        return files

    for p in sorted(root.rglob("*")):
        if p.is_file():
            files.append(str(p.relative_to(root)).replace("\\", "/"))
            if len(files) >= limit:
                break
    return files


def _find_single_json(out_dir: Path) -> Path:
    """
    Picks the newest JSON file under out_dir (recursive).
    If Docling writes multiple JSONs, this picks the newest one by mtime.
    """
    cands = sorted(out_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        raise FileNotFoundError(f"No JSON produced under {out_dir}")
    return cands[0]


def _guess_text_field(item: Dict[str, Any]) -> str:
    for k in ["text", "content", "raw_text", "value"]:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _guess_bbox(item: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """
    Conservative bbox extractor. Returns None if not confidently found.
    We avoid fragile alignment assumptions at this stage.
    """
    for k in ["bbox", "bounding_box", "rect"]:
        v = item.get(k)
        if isinstance(v, list) and len(v) == 4:
            try:
                return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
            except Exception:
                pass

    prov = item.get("prov") or item.get("provenance")
    if isinstance(prov, dict):
        v = prov.get("bbox") or prov.get("rect")
        if isinstance(v, list) and len(v) == 4:
            try:
                return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
            except Exception:
                pass

    return None


def _guess_page_index(item: Dict[str, Any]) -> Optional[int]:
    for k in ["page_idx", "page_index", "page_no", "page"]:
        v = item.get(k)
        if isinstance(v, int):
            return v

    prov = item.get("prov") or item.get("provenance")
    if isinstance(prov, dict):
        for k in ["page_idx", "page_index", "page_no", "page"]:
            v = prov.get(k)
            if isinstance(v, int):
                return v

    return None


def _require_positive_int(raw: Any, field_name: str) -> int:
    try:
        value = int(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _raw_relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _pdf_page_count(pdf_path: Path) -> int:
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def _write_pdf_chunk(source_pdf: Path, chunk_pdf_path: Path, start_page: int, end_page_exclusive: int) -> None:
    import fitz  # PyMuPDF

    if end_page_exclusive <= start_page:
        raise ValueError(
            f"Invalid PDF chunk range for {source_pdf}: start_page={start_page}, end_page_exclusive={end_page_exclusive}"
        )

    ensure_dir(chunk_pdf_path.parent)

    src = fitz.open(str(source_pdf))
    dst = fitz.open()
    try:
        dst.insert_pdf(src, from_page=start_page, to_page=end_page_exclusive - 1)
        dst.save(str(chunk_pdf_path))
    finally:
        dst.close()
        src.close()


def _plan_docling_pdf_chunks(
    pdf_path: Path,
    working_root: Path,
    threshold_pages: int,
    pages_per_chunk: int,
) -> tuple[int, List[Dict[str, Any]]]:
    total_pages = _pdf_page_count(pdf_path)
    if total_pages <= threshold_pages:
        return total_pages, []

    ensure_dir(working_root)
    plans: List[Dict[str, Any]] = []
    for chunk_index, start_page in enumerate(range(0, total_pages, pages_per_chunk)):
        end_page_exclusive = min(start_page + pages_per_chunk, total_pages)
        chunk_label = f"chunk_{chunk_index:03d}_pages_{start_page + 1:05d}_{end_page_exclusive:05d}"
        plan_root = working_root / chunk_label
        chunk_pdf_path = plan_root / "input.pdf"
        chunk_output_dir = plan_root / "output"
        _write_pdf_chunk(pdf_path, chunk_pdf_path, start_page, end_page_exclusive)
        plans.append(
            {
                "chunk_index": chunk_index,
                "chunk_label": chunk_label,
                "page_start": start_page,
                "page_end_exclusive": end_page_exclusive,
                "page_count": end_page_exclusive - start_page,
                "plan_root": plan_root,
                "chunk_pdf_path": chunk_pdf_path,
                "chunk_output_dir": chunk_output_dir,
            }
        )
    return total_pages, plans


def run_docling_cli(
    pdf_path: Path,
    out_dir: Path,
    cli: str,
    to_format: str,
    pipeline: str,
    pdf_backend: str,
    ocr: bool,
    tables: bool,
    abort_on_error: bool,
    show_layout: bool,
    extra_args: List[str],
    audit_logs_dir: Path,
    log_stem: str = "docling",
) -> Dict[str, Any]:
    ensure_dir(out_dir)

    cmd = [cli, "--to", to_format, "--output", str(out_dir)]
    cmd += ["--pipeline", pipeline]
    cmd += ["--pdf-backend", pdf_backend]
    cmd += ["--artifacts-path", artifacts_path]
    cmd += ["--ocr" if ocr else "--no-ocr"]
    cmd += ["--tables" if tables else "--no-tables"]
    cmd += ["--abort-on-error" if abort_on_error else "--no-abort-on-error"]
    cmd += ["--show-layout" if show_layout else "--no-show-layout"]
    cmd += extra_args
    cmd += [str(pdf_path)]

    rc, _, _ = run_cmd(
        cmd=cmd,
        cwd=None,
        stdout_path=audit_logs_dir / f"{log_stem}.stdout.txt",
        stderr_path=audit_logs_dir / f"{log_stem}.stderr.txt",
        timeout_s=None,
    )
    return {"returncode": rc, "cmd": cmd}


def _docling_items_to_blocks(
    doc_id: str,
    raw_relpath: str,
    top_key: str,
    items: List[Dict[str, Any]],
    *,
    page_offset: int = 0,
    chunk_meta: Optional[Dict[str, Any]] = None,
) -> List[BlockRecord]:
    blocks: List[BlockRecord] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        page_index = _guess_page_index(item)
        if page_index is None:
            page_index = -1
        elif page_index >= 0:
            page_index += page_offset

        text = _guess_text_field(item)
        bbox = _guess_bbox(item)

        block_id = f"{doc_id}:docling:{top_key}:{i}"

        if top_key == "tables":
            ctype = "table"
        elif top_key == "pictures":
            ctype = "figure"
        else:
            ctype = "text"

        raw_ref: Dict[str, Any] = {
            "layer": "docling",
            "raw_relpath": raw_relpath,
            "top_key": top_key,
            "index": i,
        }
        if chunk_meta is not None:
            raw_ref.update(chunk_meta)

        blocks.append(
            BlockRecord(
                doc_id=doc_id,
                block_id=block_id,
                layer="docling",
                page_index=int(page_index),
                content_type=ctype,  # type: ignore[arg-type]
                text_raw=text,
                bbox_pt=bbox,
                bbox_coord_system="docling_native_or_points",
                raw_ref=raw_ref,
            )
        )
    return blocks


def parse_docling_json_to_blocks(
    doc_id: str,
    raw_json_path: Path,
    *,
    raw_relpath: Optional[str] = None,
    page_offset: int = 0,
    chunk_meta: Optional[Dict[str, Any]] = None,
) -> List[BlockRecord]:
    data = json.loads(raw_json_path.read_text(encoding="utf-8"))
    resolved_raw_relpath = raw_relpath or raw_json_path.name

    blocks: List[BlockRecord] = []
    for top_key in ["texts", "tables", "pictures", "key_value_items"]:
        items = data.get(top_key)
        if not isinstance(items, list):
            continue
        blocks.extend(
            _docling_items_to_blocks(
                doc_id=doc_id,
                raw_relpath=resolved_raw_relpath,
                top_key=top_key,
                items=items,
                page_offset=page_offset,
                chunk_meta=chunk_meta,
            )
        )

    return blocks


def _copy_tree_merge(src: Path, dst: Path) -> None:
    """
    Merge-copy src into dst.
    Uses copytree(dirs_exist_ok=True) on Python 3.8+.
    """
    ensure_dir(dst)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def extract_docling(
    doc_id: str,
    pdf_path: Path,
    out_dir: Path,
    cfg: Dict[str, Any],
    audit_logs_dir: Path,
    cli_output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Writes canonical raw output to: out_dir/raw_output/
    Optionally runs Docling in a separate cli_output_dir (short path), then copies results into raw_output.
    When configured and the PDF is large enough, the Docling layer chunks the source PDF
    into smaller PDFs first, runs Docling per chunk, and merges the parsed blocks back
    to document-level page indices.
    """
    raw_dir = out_dir / "raw_output"
    ensure_dir(raw_dir)

    cli_dir = cli_output_dir if cli_output_dir is not None else raw_dir
    ensure_dir(cli_dir)

    chunking_cfg = dict(cfg.get("chunking") or {})
    try:
        threshold_pages = _require_positive_int(
            chunking_cfg.get("threshold_pages", 300),
            "layers.docling.chunking.threshold_pages",
        )
        pages_per_chunk = _require_positive_int(
            chunking_cfg.get("pages_per_chunk", 100),
            "layers.docling.chunking.pages_per_chunk",
        )
    except ValueError as exc:
        return {
            "blocks": [],
            "layer_status": {
                "enabled": True,
                "ok": False,
                "reason": "invalid_docling_chunking_config",
                "error": str(exc),
            },
        }

    status: Dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "n_blocks": 0,
        "raw_dir": str(raw_dir).replace("\\", "/"),
        "cli_dir": str(cli_dir).replace("\\", "/"),
        "chunking": {
            "enabled": bool(chunking_cfg.get("enabled", False)),
            "threshold_pages": threshold_pages,
            "pages_per_chunk": pages_per_chunk,
            "used": False,
        },
    }

    if not cfg.get("enabled", True):
        return {"blocks": [], "layer_status": {"enabled": False, "ok": False, "reason": "disabled"}}

    common_cli_kwargs = {
        "cli": cfg.get("cli", "docling"),
        "to_format": cfg.get("to_format", "json"),
        "pipeline": cfg.get("pipeline", "standard"),
        "pdf_backend": cfg.get("pdf_backend", "docling_parse"),
        "ocr": bool(cfg.get("ocr", True)),
        "tables": bool(cfg.get("tables", True)),
        "abort_on_error": bool(cfg.get("abort_on_error", False)),
        "show_layout": bool(cfg.get("show_layout", False)),
        "extra_args": list(cfg.get("extra_args", [])),
        "audit_logs_dir": audit_logs_dir,
    }

    if bool(chunking_cfg.get("enabled", False)):
        try:
            total_pages, chunk_plans = _plan_docling_pdf_chunks(
                pdf_path=pdf_path,
                working_root=cli_dir / "pdf_chunking",
                threshold_pages=threshold_pages,
                pages_per_chunk=pages_per_chunk,
            )
        except Exception as exc:
            status["reason"] = "docling_pdf_chunk_plan_failed"
            status["error"] = repr(exc)
            return {"blocks": [], "layer_status": status}

        status["chunking"]["source_pdf_pages"] = total_pages
        if chunk_plans:
            status["chunking"]["used"] = True
            status["chunking"]["chunk_count"] = len(chunk_plans)

            blocks: List[BlockRecord] = []
            chunk_status_rows: List[Dict[str, Any]] = []
            raw_chunk_root = raw_dir / "pdf_chunking"
            ensure_dir(raw_chunk_root)

            for plan in chunk_plans:
                log_stem = f"docling.chunk_{int(plan['chunk_index']):03d}"
                rc = run_docling_cli(
                    pdf_path=plan["chunk_pdf_path"],
                    out_dir=plan["chunk_output_dir"],
                    log_stem=log_stem,
                    **common_cli_kwargs,
                )

                chunk_row = {
                    "chunk_index": int(plan["chunk_index"]),
                    "chunk_label": str(plan["chunk_label"]),
                    "page_start": int(plan["page_start"]),
                    "page_end_exclusive": int(plan["page_end_exclusive"]),
                    "page_count": int(plan["page_count"]),
                    "returncode": int(rc["returncode"]),
                    "cmd": rc["cmd"],
                }

                if rc["returncode"] != 0:
                    chunk_row["cli_dir_listing"] = _list_rel_files(plan["plan_root"], limit=200)
                    chunk_status_rows.append(chunk_row)
                    status["reason"] = "docling_chunk_cli_failed"
                    status["chunks"] = chunk_status_rows
                    status["failed_chunk"] = chunk_row
                    return {"blocks": [], "layer_status": status}

                canonical_plan_root = plan["plan_root"]
                if cli_dir.resolve() != raw_dir.resolve():
                    canonical_plan_root = raw_chunk_root / str(plan["chunk_label"])
                    try:
                        _copy_tree_merge(plan["plan_root"], canonical_plan_root)
                    except Exception as exc:
                        chunk_row["cli_dir_listing"] = _list_rel_files(plan["plan_root"], limit=200)
                        chunk_row["raw_dir_listing"] = _list_rel_files(raw_dir, limit=200)
                        chunk_status_rows.append(chunk_row)
                        status["reason"] = "docling_chunk_copy_to_raw_failed"
                        status["error"] = repr(exc)
                        status["chunks"] = chunk_status_rows
                        status["failed_chunk"] = chunk_row
                        return {"blocks": [], "layer_status": status}

                try:
                    raw_json = _find_single_json(canonical_plan_root / "output")
                except FileNotFoundError:
                    chunk_row["raw_dir_listing"] = _list_rel_files(canonical_plan_root, limit=200)
                    chunk_status_rows.append(chunk_row)
                    status["reason"] = "docling_chunk_no_json_output"
                    status["chunks"] = chunk_status_rows
                    status["failed_chunk"] = chunk_row
                    return {"blocks": [], "layer_status": status}

                raw_relpath = _raw_relpath(raw_json, raw_dir)
                chunk_pdf_relpath = _raw_relpath(canonical_plan_root / "input.pdf", raw_dir)
                chunk_row["raw_json"] = raw_relpath
                chunk_row["chunk_pdf"] = chunk_pdf_relpath

                try:
                    chunk_blocks = parse_docling_json_to_blocks(
                        doc_id=doc_id,
                        raw_json_path=raw_json,
                        raw_relpath=raw_relpath,
                        page_offset=int(plan["page_start"]),
                        chunk_meta={
                            "chunk_index": int(plan["chunk_index"]),
                            "chunk_page_offset": int(plan["page_start"]),
                            "chunk_page_count": int(plan["page_count"]),
                            "chunk_pdf_relpath": chunk_pdf_relpath,
                        },
                    )
                except Exception as exc:
                    chunk_status_rows.append(chunk_row)
                    status["reason"] = "docling_chunk_parse_failed"
                    status["error"] = repr(exc)
                    status["chunks"] = chunk_status_rows
                    status["failed_chunk"] = chunk_row
                    return {"blocks": [], "layer_status": status}

                blocks.extend(chunk_blocks)
                chunk_row["n_blocks"] = len(chunk_blocks)
                chunk_status_rows.append(chunk_row)

            status["ok"] = True
            status["n_blocks"] = len(blocks)
            status["chunks"] = chunk_status_rows
            return {"blocks": blocks, "layer_status": status}

    rc = run_docling_cli(
        pdf_path=pdf_path,
        out_dir=cli_dir,
        **common_cli_kwargs,
    )

    status["cmd"] = rc["cmd"]
    status["returncode"] = rc["returncode"]

    if rc["returncode"] != 0:
        status["reason"] = "docling_cli_failed"
        status["cli_dir_listing"] = _list_rel_files(cli_dir, limit=200)
        return {"blocks": [], "layer_status": status}

    if cli_dir.resolve() != raw_dir.resolve():
        try:
            _copy_tree_merge(cli_dir, raw_dir)
        except Exception as exc:
            status["reason"] = "docling_copy_to_raw_failed"
            status["error"] = repr(exc)
            status["cli_dir_listing"] = _list_rel_files(cli_dir, limit=200)
            status["raw_dir_listing"] = _list_rel_files(raw_dir, limit=200)
            return {"blocks": [], "layer_status": status}

    try:
        raw_json = _find_single_json(raw_dir)
    except FileNotFoundError:
        status["reason"] = "docling_no_json_output"
        status["cli_dir_listing"] = _list_rel_files(cli_dir, limit=200)
        status["raw_dir_listing"] = _list_rel_files(raw_dir, limit=200)
        return {"blocks": [], "layer_status": status}

    blocks = parse_docling_json_to_blocks(
        doc_id=doc_id,
        raw_json_path=raw_json,
        raw_relpath=_raw_relpath(raw_json, raw_dir),
    )
    status["ok"] = True
    status["n_blocks"] = len(blocks)
    status["raw_json"] = _raw_relpath(raw_json, raw_dir)

    if "source_pdf_pages" not in status["chunking"] and bool(chunking_cfg.get("enabled", False)):
        try:
            status["chunking"]["source_pdf_pages"] = _pdf_page_count(pdf_path)
        except Exception:
            pass

    return {"blocks": blocks, "layer_status": status}
