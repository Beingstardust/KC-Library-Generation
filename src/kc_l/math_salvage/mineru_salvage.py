from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kc_l.utils.fs import ensure_dir
from kc_l.utils.subprocess_run import run_cmd

def _hash_short(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

def run_mineru_for_page_range(
    pdf_path: Path,
    out_dir: Path,
    cfg: Dict[str, Any],
    page_start: int,
    page_end: int,
    audit_logs_dir: Path,
) -> Dict[str, Any]:
    ensure_dir(out_dir)

    cli = cfg.get("cli", "mineru")
    backend = cfg.get("backend", "hybrid-auto-engine")
    device = cfg.get("device", "cuda")
    method = cfg.get("method", "auto")
    lang = cfg.get("lang", "en")
    source = cfg.get("source", "local")

    formula = bool(cfg.get("formula", True))
    table = bool(cfg.get("table", True))

    cmd = [
        cli,
        "-p", str(pdf_path),
        "-o", str(out_dir),
        "-b", str(backend),
        "--source", str(source),
        "--device", str(device),
        "--lang", str(lang),
        "--method", str(method),
        "-s", str(page_start),
        "-e", str(page_end),
        "-f", "True" if formula else "False",
        "-t", "True" if table else "False",
    ]

    rc, _, _ = run_cmd(
        cmd=cmd,
        cwd=None,
        stdout_path=audit_logs_dir / f"mineru_salvage_p{page_start}_{page_end}.stdout.txt",
        stderr_path=audit_logs_dir / f"mineru_salvage_p{page_start}_{page_end}.stderr.txt",
        timeout_s=None,
    )

    return {"returncode": rc, "cmd": cmd}

def find_mineru_outputs(raw_out_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """
    MinerU output folder structure is not stable across versions.
    We locate content_list.json and middle.json recursively.
    """
    if not raw_out_dir.exists():
        return None, None

    content_list = None
    middle = None

    for p in sorted(raw_out_dir.rglob("*")):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name.endswith("_content_list.json") or name.endswith("content_list.json"):
            content_list = p
        if name.endswith("_middle.json") or name.endswith("middle.json"):
            middle = p

    return content_list, middle

def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk(x)

def parse_equations_from_content_list(
    doc_id: str,
    content_list_path: Path,
) -> List[Dict[str, Any]]:
    """
    Minimal, robust parser:
    - MinerU content blocks include page_idx and bbox in 0-1000 normalization. :contentReference[oaicite:6]{index=6}
    - Equation content may be stored under fields like: "type", "category", "text", "latex".
    """
    data = json.loads(content_list_path.read_text(encoding="utf-8"))
    eq_blocks: List[Dict[str, Any]] = []
    i = 0

    for d in _walk(data):
        t = (d.get("type") or d.get("category") or d.get("label") or "").lower()
        if t not in ("equation", "formula", "math"):
            continue

        page_idx = d.get("page_idx")
        if page_idx is None:
            page_idx = d.get("page_index")
        if page_idx is None:
            continue

        bbox = d.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue

        latex = d.get("latex") or d.get("text") or d.get("content") or ""
        if not isinstance(latex, str):
            latex = ""

        block_id = f"{doc_id}:mineru_salvage:eq:{int(page_idx)}:{i}"
        i += 1

        eq_blocks.append({
            "doc_id": doc_id,
            "block_id": block_id,
            "layer": "mineru_salvage",
            "page_index": int(page_idx),
            "content_type": "equation",
            "text_raw": latex.strip(),
            "bbox_pt": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
            "bbox_coord_system": "mineru_0_1000_norm",
            "raw_ref": {
                "source": "mineru_salvage",
                "raw_relpath": str(content_list_path.name),
                "type": t,
            },
        })

    return eq_blocks

def iou_norm_0_1000(a: List[float], b: List[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

def dedupe_against_existing_equations(
    salvage_eqs: List[Dict[str, Any]],
    existing_blocks: List[Dict[str, Any]],
    iou_threshold: float,
) -> List[Dict[str, Any]]:
    existing_eqs = [
        b for b in existing_blocks
        if b.get("content_type") == "equation"
        and b.get("bbox_coord_system") == "mineru_0_1000_norm"
        and isinstance(b.get("bbox_pt"), list)
        and len(b.get("bbox_pt")) == 4
    ]

    kept: List[Dict[str, Any]] = []
    for s in salvage_eqs:
        sb = s.get("bbox_pt")
        if not (isinstance(sb, list) and len(sb) == 4):
            kept.append(s)
            continue
        dup = False
        for e in existing_eqs:
            eb = e.get("bbox_pt")
            if not (isinstance(eb, list) and len(eb) == 4):
                continue
            if iou_norm_0_1000(list(map(float, sb)), list(map(float, eb))) >= iou_threshold:
                dup = True
                break
        if not dup:
            kept.append(s)
    return kept