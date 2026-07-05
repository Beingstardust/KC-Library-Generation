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


def run_mineru_cli(
    pdf_path: Path,
    out_dir: Path,
    cli: str,
    backend: str,
    extra_args: List[str],
    audit_logs_dir: Path,
) -> Dict[str, Any]:
    ensure_dir(out_dir)

    # MinerU CLI requires: -p/--path, -o/--output, -b/--backend. :contentReference[oaicite:1]{index=1}
    cmd = [cli, "-p", str(pdf_path), "-o", str(out_dir), "-b", backend] + extra_args
    rc, _, _ = run_cmd(
        cmd=cmd,
        cwd=None,
        stdout_path=audit_logs_dir / "mineru.stdout.txt",
        stderr_path=audit_logs_dir / "mineru.stderr.txt",
        timeout_s=None,
    )
    return {"returncode": rc, "cmd": cmd}


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
    """
    raw_dir = out_dir / "raw_output"
    ensure_dir(raw_dir)

    cli_dir = cli_output_dir if cli_output_dir is not None else raw_dir
    ensure_dir(cli_dir)

    status: Dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "n_blocks": 0,
        "raw_dir": str(raw_dir).replace("\\", "/"),
        "cli_dir": str(cli_dir).replace("\\", "/"),
    }

    if not cfg.get("enabled", True):
        return {"blocks": [], "layer_status": {"enabled": False, "ok": False, "reason": "disabled"}}

    cli = cfg.get("cli", "mineru")
    backend = cfg.get("backend", "pipeline")
    extra_args = list(cfg.get("extra_args", []))

    rc = run_mineru_cli(
        pdf_path=pdf_path,
        out_dir=cli_dir,
        cli=cli,
        backend=backend,
        extra_args=extra_args,
        audit_logs_dir=audit_logs_dir,
    )

    # After rc = run_mineru_cli(...)
    stderr_path = audit_logs_dir / "mineru.stderr.txt"
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