from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kc_l.blockstore.schema import BlockRecord
from kc_l.utils.fs import ensure_dir
from kc_l.utils.subprocess_run import run_cmd


def _list_rel_files(root: Path, limit: int = 200) -> List[str]:
    files: List[str] = []
    if not root.exists():
        return files
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files.append(str(p.relative_to(root)).replace("\\", "/"))
            if len(files) >= limit:
                break
    return files


def _find_any(out_dir: Path, patterns: List[str]) -> Optional[Path]:
    cands: List[Path] = []
    for pat in patterns:
        cands.extend(list(out_dir.rglob(pat)))
    # newest first
    cands = sorted(set(cands), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _require_positive_int(raw: Any, field_name: str) -> int:
    try:
        value = int(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _pdf_page_count(pdf_path: Path) -> int:
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def _plan_mineru_page_chunks(
    pdf_path: Path,
    threshold_pages: int,
    pages_per_chunk: int,
) -> Tuple[int, List[Dict[str, Any]]]:
    """Sequential page-range chunk plan for MinerU's native -s/-e flags. Confirmed via
    `mineru --help`: both are 0-indexed and inclusive ("The starting/ending page for PDF
    parsing, beginning from 0"). Unlike Docling's chunking, this does NOT physically split the
    PDF - MinerU's -s/-e already restrict processing to a page range within the original file,
    and the resulting content_list.json's page_idx values are already absolute (document-level)
    page indices, confirmed by mineru_salvage.py's equivalent usage doing no offset correction
    when merging - so no page_offset math is needed here, unlike Docling's chunk merge.
    """
    total_pages = _pdf_page_count(pdf_path)
    if total_pages <= threshold_pages:
        return total_pages, []

    plans: List[Dict[str, Any]] = []
    chunk_index = 0
    start = 0
    while start < total_pages:
        end = min(start + pages_per_chunk - 1, total_pages - 1)
        plans.append(
            {
                "chunk_index": chunk_index,
                "chunk_label": f"chunk_{chunk_index:03d}_pages_{start:05d}_{end:05d}",
                "page_start": start,
                "page_end": end,
                "page_count": end - start + 1,
            }
        )
        chunk_index += 1
        start = end + 1

    return total_pages, plans


def run_mineru_cli(
    pdf_path: Path,
    out_dir: Path,
    cli: str,
    backend: str,
    device: str,
    extra_args: List[str],
    audit_logs_dir: Path,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    log_stem: str = "mineru",
    timeout_s: Optional[int] = None,
) -> Dict[str, Any]:
    ensure_dir(out_dir)

    # MinerU CLI requires: -p/--path, -o/--output, -b/--backend. :contentReference[oaicite:1]{index=1}
    cmd = [cli, "-p", str(pdf_path), "-o", str(out_dir), "-b", backend]
    # --device: confirmed inert on the currently-installed MinerU CLI (its click context is
    # ignore_unknown_options=True, so unrecognized flags are silently swallowed - the real
    # switch is the MINERU_DEVICE_MODE env var, set by the caller at the SLURM-script level).
    # Re-added anyway for defense-in-depth: the historical step_03_6 GPU run
    # (run_step3_6_actual_corpus_gpu.slurm) passed this exact flag and produced real GPU output
    # (returncode 0, real content), so the installed CLI version's flag-parsing behavior may not
    # be stable across upgrades - cheap to keep both mechanisms in place rather than relying on
    # the env var alone. (--source, also present in the historical mineru_salvage.py pattern, is
    # NOT re-added here - confirmed via `mineru --help` that no such flag exists at all in the
    # currently-installed CLI, unlike --device which is a real-but-ignored flag.)
    cmd += ["--device", str(device)]
    cmd += extra_args
    if page_start is not None and page_end is not None:
        cmd += ["-s", str(page_start), "-e", str(page_end)]

    rc, _, _ = run_cmd(
        cmd=cmd,
        cwd=None,
        stdout_path=audit_logs_dir / f"{log_stem}.stdout.txt",
        stderr_path=audit_logs_dir / f"{log_stem}.stderr.txt",
        timeout_s=timeout_s,
    )
    return {"returncode": rc, "cmd": cmd}


# Confirmed via three independent real runs on the HPC cluster (and's
# chunk 11/12) that MinerU's fast_api-based task-queue architecture occasionally hangs
# indefinitely at the exact same internal transition point (right after logging "Pipeline
# processing window batch X/Y", before any GPU-stage progress bar appears) - with zero GPU
# utilization for the entire hang. All three hangs eventually surfaced MinerU's own hardcoded
# `TASK_RESULT_TIMEOUT_SECONDS = 3600` (mineru/cli/api_client.py - not configurable via env var
# or CLI flag, confirmed by reading the source) with the identical error: "Timed out waiting for
# result of task ... ". Critically's chunks 0-10 (11 consecutive prior calls in the
# SAME SLURM job) all succeeded in ~2-5 minutes each with no degradation trend, and chunk 11 was
# the SMALLEST chunk (20 pages, vs 100 for the others) - ruling out both "resource leak across
# repeated invocations in one job" and "content/size-specific" as the cause. This is a
# probabilistic/intermittent hang inherent to the installed MinerU version's own internal
# async task handling, not something fixable from caller-side code. The practical mitigation is
# retry-with-a-shorter-external-timeout: killing a hung attempt well before MinerU's own 3600s
# deadline and relaunching a fresh subprocess (fresh CUDA context, fresh fast_api server, fresh
# asyncio event loop) escapes whatever stuck state the previous attempt was in.
MINERU_DEFAULT_MAX_ATTEMPTS = 3
MINERU_DEFAULT_ATTEMPT_TIMEOUT_SECONDS = 1200  # 20 min - ~4-10x the ~2-5 min observed for every
# real successful chunk in, generous enough to not falsely kill legitimately slower
# chunks while still cutting the cost of a hang from a guaranteed 3600s down to this bound.

MINERU_KNOWN_TIMEOUT_SIGNATURE = "Timed out waiting for result of task"


def run_mineru_cli_with_retry(
    pdf_path: Path,
    out_dir: Path,
    cli: str,
    backend: str,
    device: str,
    extra_args: List[str],
    audit_logs_dir: Path,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    log_stem: str = "mineru",
    max_attempts: int = MINERU_DEFAULT_MAX_ATTEMPTS,
    attempt_timeout_seconds: int = MINERU_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Retry wrapper around run_mineru_cli() for the confirmed intermittent hang documented
    above. Each attempt gets its own log_stem suffix so no attempt's logs are overwritten -
    useful for diagnosing whether a given failure was a fresh occurrence of the known hang or
    something new. Returns the last attempt's result dict plus an "attempts" list recording
    every attempt's returncode/cmd/timed_out for audit.
    """
    attempts: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {}

    for attempt_index in range(1, max(1, max_attempts) + 1):
        attempt_log_stem = log_stem if attempt_index == 1 else f"{log_stem}.retry{attempt_index}"

        result = run_mineru_cli(
            pdf_path=pdf_path,
            out_dir=out_dir,
            cli=cli,
            backend=backend,
            device=device,
            extra_args=extra_args,
            audit_logs_dir=audit_logs_dir,
            page_start=page_start,
            page_end=page_end,
            log_stem=attempt_log_stem,
            timeout_s=attempt_timeout_seconds,
        )

        stderr_path = audit_logs_dir / f"{attempt_log_stem}.stderr.txt"
        try:
            stderr_txt = stderr_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            stderr_txt = ""

        timed_out_externally = result["returncode"] == 124
        hit_known_mineru_timeout = MINERU_KNOWN_TIMEOUT_SIGNATURE in stderr_txt
        is_retryable_failure = timed_out_externally or hit_known_mineru_timeout

        attempts.append(
            {
                "attempt": attempt_index,
                "log_stem": attempt_log_stem,
                "returncode": result["returncode"],
                "timed_out_externally": timed_out_externally,
                "hit_known_mineru_timeout": hit_known_mineru_timeout,
            }
        )

        if result["returncode"] == 0:
            break
        if not is_retryable_failure:
            # A real (non-hang) failure - retrying won't help, fail fast.
            break

    result["attempts"] = attempts
    return result


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _page_sizes_from_middle(middle: Dict[str, Any]) -> Dict[int, Tuple[float, float]]:
    sizes: Dict[int, Tuple[float, float]] = {}
    pdf_info = middle.get("pdf_info")
    if not isinstance(pdf_info, list):
        return sizes
    for page in pdf_info:
        if not isinstance(page, dict):
            continue
        idx = page.get("page_idx")
        size = page.get("page_size")
        if isinstance(idx, int) and isinstance(size, list) and len(size) == 2:
            try:
                sizes[idx] = (float(size[0]), float(size[1]))
            except Exception:
                pass
    return sizes


def _bbox_0_1000_to_points(bbox: List[float], page_w: float, page_h: float) -> Tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (
        float(x0) / 1000.0 * page_w,
        float(y0) / 1000.0 * page_h,
        float(x1) / 1000.0 * page_w,
        float(y1) / 1000.0 * page_h,
    )


def parse_mineru_content_list(
    doc_id: str,
    content_list_path: Path,
    page_sizes: Dict[int, Tuple[float, float]],
) -> List[BlockRecord]:
    data = _load_json(content_list_path)
    if not isinstance(data, list):
        return []

    blocks: List[BlockRecord] = []

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue

        page_idx = item.get("page_idx")
        if not isinstance(page_idx, int):
            page_idx = -1

        t = item.get("type", "unknown")

        # Normalize content types roughly (MinerU content list types are documented). :contentReference[oaicite:2]{index=2}
        if t == "image":
            ctype = "figure"
        elif t in ["table", "equation", "text", "title", "header", "footer", "page_number", "list", "code"]:
            ctype = t
        else:
            ctype = "unknown"

        # Extract text payload defensively
        text = ""
        if isinstance(item.get("text"), str):
            text = item["text"]
        elif isinstance(item.get("latex"), str):
            text = item["latex"]
        elif isinstance(item.get("content"), str):
            text = item["content"]

        bbox = item.get("bbox")
        bbox_pt = None
        bbox_cs = "mineru_0_1000_norm"

        if isinstance(bbox, list) and len(bbox) == 4 and page_idx in page_sizes:
            try:
                page_w, page_h = page_sizes[page_idx]
                bbox_pt = _bbox_0_1000_to_points([float(x) for x in bbox], page_w, page_h)
                bbox_cs = "mineru_0_1000_norm_to_points"
            except Exception:
                bbox_pt = None
                bbox_cs = "mineru_0_1000_norm"

        block_id = f"{doc_id}:mineru:{page_idx}:{i}"
        blocks.append(
            BlockRecord(
                doc_id=doc_id,
                block_id=block_id,
                layer="mineru",
                page_index=int(page_idx),
                content_type=ctype,  # type: ignore[arg-type]
                text_raw=text,
                bbox_pt=bbox_pt,
                bbox_coord_system=bbox_cs,
                raw_ref={
                    "layer": "mineru",
                    "raw_relpath": content_list_path.name,
                    "index": i,
                },
            )
        )

    return blocks


def _copy_tree_merge(src: Path, dst: Path) -> None:
    ensure_dir(dst)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def extract_mineru(
    doc_id: str,
    pdf_path: Path,
    out_dir: Path,
    cfg: Dict[str, Any],
    audit_logs_dir: Path,
    cli_output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Canonical raw output lives at: out_dir/raw_output/
    Optionally run MinerU into cli_output_dir (short path), then copy into raw_output.
    When configured and the PDF is large enough, MinerU is called once per sequential page
    range (via its native -s/-e flags, on the original whole PDF - no physical file splitting
    needed, unlike the Docling layer) instead of one whole-document call.
    """
    raw_dir = out_dir / "raw_output"
    ensure_dir(raw_dir)

    cli_dir = cli_output_dir if cli_output_dir is not None else raw_dir
    ensure_dir(cli_dir)

    chunking_cfg = dict(cfg.get("chunking") or {})
    try:
        threshold_pages = _require_positive_int(
            chunking_cfg.get("threshold_pages", 300),
            "layers.mineru.chunking.threshold_pages",
        )
        pages_per_chunk = _require_positive_int(
            chunking_cfg.get("pages_per_chunk", 100),
            "layers.mineru.chunking.pages_per_chunk",
        )
    except ValueError as exc:
        return {
            "blocks": [],
            "layer_status": {
                "enabled": True,
                "ok": False,
                "reason": "invalid_mineru_chunking_config",
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

    cli = cfg.get("cli", "mineru")
    backend = cfg.get("backend", "pipeline")
    device = cfg.get("device", "auto")
    extra_args = list(cfg.get("extra_args", []))

    retry_cfg = dict(cfg.get("retry") or {})
    max_attempts = int(retry_cfg.get("max_attempts", MINERU_DEFAULT_MAX_ATTEMPTS))
    attempt_timeout_seconds = int(
        retry_cfg.get("attempt_timeout_seconds", MINERU_DEFAULT_ATTEMPT_TIMEOUT_SECONDS)
    )

    if bool(chunking_cfg.get("enabled", False)):
        try:
            total_pages, chunk_plans = _plan_mineru_page_chunks(
                pdf_path=pdf_path,
                threshold_pages=threshold_pages,
                pages_per_chunk=pages_per_chunk,
            )
        except Exception as exc:
            status["reason"] = "mineru_pdf_chunk_plan_failed"
            status["error"] = repr(exc)
            return {"blocks": [], "layer_status": status}

        status["chunking"]["source_pdf_pages"] = total_pages
        if chunk_plans:
            status["chunking"]["used"] = True
            status["chunking"]["chunk_count"] = len(chunk_plans)

            blocks: List[BlockRecord] = []
            chunk_status_rows: List[Dict[str, Any]] = []

            for plan in chunk_plans:
                chunk_label = str(plan["chunk_label"])
                log_stem = f"mineru.{chunk_label}"
                chunk_cli_dir = cli_dir / chunk_label

                rc = run_mineru_cli_with_retry(
                    pdf_path=pdf_path,
                    out_dir=chunk_cli_dir,
                    cli=cli,
                    backend=backend,
                    device=device,
                    extra_args=extra_args,
                    audit_logs_dir=audit_logs_dir,
                    page_start=int(plan["page_start"]),
                    page_end=int(plan["page_end"]),
                    log_stem=log_stem,
                    max_attempts=max_attempts,
                    attempt_timeout_seconds=attempt_timeout_seconds,
                )
                # The final attempt's own log_stem (may carry a .retryN suffix) - not
                # necessarily the same as `log_stem` above once a retry happened.
                final_log_stem = rc["attempts"][-1]["log_stem"] if rc.get("attempts") else log_stem

                chunk_row = {
                    "chunk_index": int(plan["chunk_index"]),
                    "chunk_label": chunk_label,
                    "page_start": int(plan["page_start"]),
                    "page_end": int(plan["page_end"]),
                    "page_count": int(plan["page_count"]),
                    "returncode": int(rc["returncode"]),
                    "cmd": rc["cmd"],
                    "attempts": rc.get("attempts", []),
                }

                chunk_stderr_path = audit_logs_dir / f"{final_log_stem}.stderr.txt"
                try:
                    chunk_stderr_txt = chunk_stderr_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    chunk_stderr_txt = ""

                if ("ModuleNotFoundError" in chunk_stderr_txt) or ("Traceback (most recent call last)" in chunk_stderr_txt):
                    chunk_row["stderr_tail"] = chunk_stderr_txt[-2000:]
                    chunk_status_rows.append(chunk_row)
                    status["reason"] = "mineru_chunk_exception"
                    status["chunks"] = chunk_status_rows
                    status["failed_chunk"] = chunk_row
                    return {"blocks": [], "layer_status": status}

                if rc["returncode"] != 0:
                    chunk_row["cli_dir_listing"] = _list_rel_files(chunk_cli_dir, limit=200)
                    chunk_status_rows.append(chunk_row)
                    status["reason"] = "mineru_chunk_cli_failed"
                    status["chunks"] = chunk_status_rows
                    status["failed_chunk"] = chunk_row
                    return {"blocks": [], "layer_status": status}

                canonical_chunk_dir = chunk_cli_dir
                if cli_dir.resolve() != raw_dir.resolve():
                    canonical_chunk_dir = raw_dir / chunk_label
                    try:
                        _copy_tree_merge(chunk_cli_dir, canonical_chunk_dir)
                    except Exception as exc:
                        chunk_row["cli_dir_listing"] = _list_rel_files(chunk_cli_dir, limit=200)
                        chunk_status_rows.append(chunk_row)
                        status["reason"] = "mineru_chunk_copy_to_raw_failed"
                        status["error"] = repr(exc)
                        status["chunks"] = chunk_status_rows
                        status["failed_chunk"] = chunk_row
                        return {"blocks": [], "layer_status": status}

                chunk_content_list = _find_any(canonical_chunk_dir, ["*_content_list.json", "*content_list.json"])
                chunk_middle = _find_any(canonical_chunk_dir, ["*_middle.json", "*middle.json"])

                if chunk_content_list is None or chunk_middle is None:
                    chunk_row["raw_dir_listing"] = _list_rel_files(canonical_chunk_dir, limit=400)
                    chunk_status_rows.append(chunk_row)
                    status["reason"] = "mineru_chunk_missing_expected_outputs"
                    status["chunks"] = chunk_status_rows
                    status["failed_chunk"] = chunk_row
                    return {"blocks": [], "layer_status": status}

                chunk_middle_json = _load_json(chunk_middle)
                chunk_page_sizes = _page_sizes_from_middle(chunk_middle_json)
                chunk_blocks = parse_mineru_content_list(
                    doc_id=doc_id,
                    content_list_path=chunk_content_list,
                    page_sizes=chunk_page_sizes,
                )

                blocks.extend(chunk_blocks)
                chunk_row["n_blocks"] = len(chunk_blocks)
                chunk_status_rows.append(chunk_row)

            status["ok"] = True
            status["n_blocks"] = len(blocks)
            status["chunks"] = chunk_status_rows
            return {"blocks": blocks, "layer_status": status}

    rc = run_mineru_cli_with_retry(
        pdf_path=pdf_path,
        out_dir=cli_dir,
        cli=cli,
        backend=backend,
        device=device,
        extra_args=extra_args,
        audit_logs_dir=audit_logs_dir,
        max_attempts=max_attempts,
        attempt_timeout_seconds=attempt_timeout_seconds,
    )
    status["attempts"] = rc.get("attempts", [])

    # The final attempt's own log_stem (may carry a .retryN suffix).
    final_log_stem = rc["attempts"][-1]["log_stem"] if rc.get("attempts") else "mineru"
    stderr_path = audit_logs_dir / f"{final_log_stem}.stderr.txt"
    try:
        stderr_txt = stderr_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        stderr_txt = ""

    # If MinerU printed a traceback, treat as hard failure even if returncode==0
    if ("ModuleNotFoundError" in stderr_txt) or ("Traceback (most recent call last)" in stderr_txt):
        status["ok"] = False
        status["reason"] = "mineru_exception"
        status["stderr_tail"] = stderr_txt[-2000:]
        return {"blocks": [], "layer_status": status}
    status["cmd"] = rc["cmd"]
    status["returncode"] = rc["returncode"]

    if rc["returncode"] != 0:
        status["reason"] = "mineru_cli_failed"
        status["cli_dir_listing"] = _list_rel_files(cli_dir, limit=200)
        return {"blocks": [], "layer_status": status}

    # If CLI ran in a work dir, copy everything into canonical raw_dir
    if cli_dir.resolve() != raw_dir.resolve():
        try:
            _copy_tree_merge(cli_dir, raw_dir)
        except Exception as e:
            status["reason"] = "mineru_copy_to_raw_failed"
            status["error"] = repr(e)
            status["cli_dir_listing"] = _list_rel_files(cli_dir, limit=200)
            status["raw_dir_listing"] = _list_rel_files(raw_dir, limit=200)
            return {"blocks": [], "layer_status": status}

    # MinerU docs say filenames are {original_filename}_content_list.json and {original_filename}_middle.json :contentReference[oaicite:3]{index=3}
    content_list = _find_any(raw_dir, ["*_content_list.json", "*content_list.json"])
    middle = _find_any(raw_dir, ["*_middle.json", "*middle.json"])

    status["found_content_list"] = bool(content_list)
    status["found_middle"] = bool(middle)

    if content_list is None or middle is None:
        status["reason"] = "mineru_missing_expected_outputs"
        status["raw_dir_listing"] = _list_rel_files(raw_dir, limit=400)
        return {"blocks": [], "layer_status": status}

    middle_json = _load_json(middle)
    page_sizes = _page_sizes_from_middle(middle_json)

    blocks = parse_mineru_content_list(doc_id=doc_id, content_list_path=content_list, page_sizes=page_sizes)

    status["ok"] = True
    status["n_blocks"] = len(blocks)
    status["content_list"] = content_list.name
    status["middle"] = middle.name
    status["page_sizes_found"] = len(page_sizes)

    return {"blocks": blocks, "layer_status": status}