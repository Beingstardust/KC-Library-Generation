from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from kc_l.cleaning.boilerplate import build_line_stats, is_boilerplate_line, clean_block_text, math_symbol_ratio

def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            rows.append(json.loads(ln))
    return rows

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def enrich_doc(
    doc_id: str,
    step2_out_dir: Path,
    step3_out_dir: Path,
    out_dir: Path,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    pages = _read_jsonl(step2_out_dir / "pages.jsonl")
    blocks = _read_jsonl(step2_out_dir / "blocks.jsonl")
    page_index = _read_jsonl(step3_out_dir / "page_index.jsonl")

    page_heights = {int(p["page_index"]): float(p["height_pt"]) for p in pages}
    n_pages_total = len(pages)

    bp_cfg = cfg["boilerplate"]
    apply_layers = set(bp_cfg.get("apply_layers", ["mineru"]))
    apply_types = set(bp_cfg.get("apply_content_types", ["text"]))

    # protect Step3 titles (never removed)
    protect_lines_norm: set[str] = set()
    if bool(bp_cfg.get("protect_step3_titles", True)):
        for r in page_index:
            t = (r.get("title") or "").strip()
            if t:
                protect_lines_norm.add(" ".join(t.lower().split()))

    # build stats on MinerU text blocks only
    mineru_text_blocks = [
        b for b in blocks
        if b.get("layer") == "mineru" and b.get("content_type") == "text" and (b.get("text_raw") or "").strip()
    ]

    line_stats = build_line_stats(
        mineru_text_blocks=mineru_text_blocks,
        page_heights=page_heights,
        bottom_y_frac=float(bp_cfg["bottom_y_frac"]),
        max_line_len=int(bp_cfg["max_line_len"]),
    )

    # precompute boilerplate decision per norm line
    is_bp: Dict[str, Tuple[bool, List[str]]] = {}
    for n, st in line_stats.items():
        ok, reasons = is_boilerplate_line(
            stat=st,
            cfg=bp_cfg,
            n_pages_total=n_pages_total,
        )
        is_bp[n] = (ok, reasons)

    enriched_blocks: List[Dict[str, Any]] = []
    removed_total = 0
    cleaned_total = 0
    boiler_blocks = 0

    for b in blocks:
        nb = dict(b)
        layer = str(nb.get("layer"))
        ctype = str(nb.get("content_type"))

        nb["text_clean"] = (nb.get("text_raw") or "")

        nb["boilerplate"] = {
            "enabled": bool(bp_cfg.get("enabled", True)),
            "applied": False,
            "is_boilerplate_block": False,
            "removed_lines_n": 0,
            "removed_lines": [],
            "cleaning_version": "3.5.0",
        }

        if bool(bp_cfg.get("enabled", True)) and (layer in apply_layers) and (ctype in apply_types):
            txt = (nb.get("text_raw") or "")
            res = clean_block_text(
                text_raw=txt,
                line_stats=line_stats,
                is_bp=is_bp,
                protect_lines_norm=protect_lines_norm,
            )
            nb["text_clean"] = res["text_clean"]
            nb["boilerplate"]["applied"] = True
            nb["boilerplate"]["is_boilerplate_block"] = bool(res["is_boilerplate_block"])
            nb["boilerplate"]["removed_lines_n"] = int(res["removed_lines_n"])
            nb["boilerplate"]["removed_lines"] = res["removed_lines"]

            removed_total += int(res["removed_lines_n"])
            cleaned_total += 1
            if res["is_boilerplate_block"]:
                boiler_blocks += 1

        enriched_blocks.append(nb)

    # boilerplate catalog (top lines)
    top = sorted(
        [st for st in line_stats.values() if is_bp.get(st.norm, (False, []))[0]],
        key=lambda s: (s.n_pages, s.n_occurrences),
        reverse=True,
    )[:200]

    catalog = []
    for st in top:
        ok, reasons = is_bp.get(st.norm, (False, []))
        catalog.append({
            "norm": st.norm,
            "examples": st.raw_examples,
            "n_pages": st.n_pages,
            "n_occurrences": st.n_occurrences,
            "bottom_frac": st.bottom_frac,
            "reasons": reasons,
        })

    _write_json(out_dir / "boilerplate_catalog.json", {
        "doc_id": doc_id,
        "n_pages": n_pages_total,
        "n_candidates": len(line_stats),
        "n_flagged": len([1 for v in is_bp.values() if v[0]]),
        "top_flagged": catalog,
    })

    _write_jsonl(out_dir / "blocks_enriched.jsonl", enriched_blocks)
    _write_jsonl(out_dir / "pages.jsonl", pages)  # pass-through

    # Formula coverage QA report (see explanation below)
    formula_cfg = cfg.get("formula_qa", {})
    formula_report = build_formula_coverage_report(
        doc_id=doc_id,
        pages=pages,
        blocks=enriched_blocks,
        formula_cfg=formula_cfg,
    )
    _write_json(out_dir / "formula_coverage.json", formula_report)

    summary = {
        "doc_id": doc_id,
        "n_pages": n_pages_total,
        "n_blocks_total": len(blocks),
        "n_blocks_enriched": len(enriched_blocks),
        "boilerplate": {
            "enabled": bool(bp_cfg.get("enabled", True)),
            "cleaned_blocks": cleaned_total,
            "boilerplate_blocks": boiler_blocks,
            "removed_lines_total": removed_total,
            "protected_titles_count": len(protect_lines_norm),
        },
        "formula_qa": {
            "enabled": bool(formula_cfg.get("enabled", True)),
            "suspect_pages": len(formula_report.get("suspect_pages", [])),
        }
    }
    _write_json(out_dir / "summary.json", summary)
    return summary

def build_formula_coverage_report(
    doc_id: str,
    pages: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    formula_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    enabled = bool(formula_cfg.get("enabled", True))
    if not enabled:
        return {"doc_id": doc_id, "enabled": False}

    # Count MinerU equation blocks per page
    eq_counts: Dict[int, int] = {}
    for b in blocks:
        if b.get("layer") == "mineru" and b.get("content_type") == "equation":
            pi = int(b.get("page_index", -1))
            eq_counts[pi] = eq_counts.get(pi, 0) + 1

    # Compute "mathness" from PyMuPDF text on each page
    pymupdf_text_by_page: Dict[int, str] = {}
    for b in blocks:
        if b.get("layer") == "pymupdf" and b.get("content_type") == "text":
            pi = int(b.get("page_index", -1))
            pymupdf_text_by_page.setdefault(pi, "")
            pymupdf_text_by_page[pi] += "\n" + (b.get("text_raw") or "")

    suspect = []
    for p in pages:
        pi = int(p["page_index"])
        eq = eq_counts.get(pi, 0)

        txt = (pymupdf_text_by_page.get(pi) or "").strip()
        if len(txt) < int(formula_cfg.get("suspicious_if", {}).get("min_chars_for_math_check", 200)):
            continue

        ratio = math_symbol_ratio(txt)
        if bool(formula_cfg.get("suspicious_if", {}).get("eq_count_mineru_is_zero", True)):
            if eq == 0 and ratio >= float(formula_cfg.get("suspicious_if", {}).get("math_symbol_ratio_ge", 0.08)):
                suspect.append({
                    "page_index": pi,
                    "eq_count_mineru": eq,
                    "math_symbol_ratio_pymupdf": ratio,
                    "reason": "math_symbols_high_but_no_mineru_equations",
                })

    return {
        "doc_id": doc_id,
        "enabled": True,
        "eq_counts_mineru": eq_counts,
        "suspect_pages": suspect,
        "notes": [
            "This is a QA heuristic. It does not prove formulas are missing.",
            "It flags pages where PyMuPDF text contains many math symbols but MinerU found zero equation blocks."
        ],
    }