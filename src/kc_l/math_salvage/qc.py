from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np


def compile_token_regex(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p) for p in patterns]


def count_math_tokens(text: str, regs: List[re.Pattern]) -> int:
    if not text:
        return 0
    hits = 0
    for rx in regs:
        hits += len(rx.findall(text))
    return hits



def page_image_path(enriched_out_dir: Path, step2_out_dir: Path, image_relpath: str | None) -> Path | None:
    """
    Try both:
      - step3_5 enriched output dir (if it copied images)
      - step2 output dir (canonical page_images)
    """
    if not image_relpath:
        return None
    p1 = enriched_out_dir / image_relpath
    if p1.exists():
        return p1
    p2 = step2_out_dir / image_relpath
    if p2.exists():
        return p2
    return None


def _bbox_norm_to_px(
    b: Tuple[float, float, float, float], img_w: int, img_h: int
) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = b
    # MinerU bbox is 0-1000 normalized for both axes.
    px0 = int(round((x0 / 1000.0) * img_w))
    py0 = int(round((y0 / 1000.0) * img_h))
    px1 = int(round((x1 / 1000.0) * img_w))
    py1 = int(round((y1 / 1000.0) * img_h))
    return px0, py0, px1, py1


def compute_edge_outside_ratio(
    img_path: Path,
    mineru_blocks_on_page: List[Dict[str, Any]],
    min_total_edges: int,
) -> Tuple[float, int]:
    """
    Returns (outside_ratio, total_edge_pixels).
    Uses bbox mask built from MinerU bboxes in mineru_0_1000_norm coord system.
    If bboxes are missing, returns (0.0, 0.0) or (0.0,total) if edges exist but no boxes.
    """
    import cv2

    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0, 0

    h, w = img.shape[:2]
    edges = cv2.Canny(img, 50, 150)

    total = int(np.count_nonzero(edges))
    if total < min_total_edges:
        return 0.0, total

    mask = np.zeros((h, w), dtype=np.uint8)

    n_boxes = 0
    for b in mineru_blocks_on_page:
        bbox = b.get("bbox_pt")
        cs = b.get("bbox_coord_system")
        if not bbox or not cs:
            continue
        if cs != "mineru_0_1000_norm":
            continue
        try:
            x0, y0, x1, y1 = map(float, bbox)
        except Exception:
            continue

        px0, py0, px1, py1 = _bbox_norm_to_px((x0, y0, x1, y1), w, h)
        px0 = max(0, min(w - 1, px0))
        px1 = max(0, min(w - 1, px1))
        py0 = max(0, min(h - 1, py0))
        py1 = max(0, min(h - 1, py1))
        if px1 <= px0 or py1 <= py0:
            continue

        mask[py0:py1, px0:px1] = 1
        n_boxes += 1

    # If MinerU produced no boxes at all on a page with lots of ink,
    # we can't compute outside_ratio meaningfully; return 0.0 but keep total.
    if n_boxes == 0:
        return 0.0, total

    outside = int(np.count_nonzero(edges[mask == 0]))
    return outside / max(1, total), total


# Inline math detection inside MinerU text blocks.
# This prevents false "missing equation" flags when the page only has inline LaTeX,
# which is common in LaTeX slide decks.
_INLINE_LATEX_PATTERNS = [
    r"\$[^$]+\$",                  # inline $...$
    r"\$\$[\s\S]+?\$\$",           # display $$...$$ inside text
    r"\\(frac|sum|prod|int|sqrt|log|ln|exp)\b",
    r"\\(alpha|beta|gamma|delta|mu|sigma|theta|rho|lambda|pi)\b",
    r"\\(ldots|dots|cdot|cdots)\b",
    r"\\(mathbf|mathbb|mathcal)\b",
    r"[_^]\s*\{",                  # _{  or ^{
    r"\\left\b|\\right\b",
    r"\\(times|leq|geq|neq|approx)\b",
]
_INLINE_RX = [re.compile(p) for p in _INLINE_LATEX_PATTERNS]


def mineru_inline_math_hits(page_blocks: List[Dict[str, Any]]) -> int:
    hits = 0
    for b in page_blocks:
        if b.get("layer") != "mineru":
            continue
        if b.get("content_type") not in ("text", "unknown", "title", "header", "footer"):
            continue
        tx = b.get("text_raw") or ""
        if not tx:
            continue
        for rx in _INLINE_RX:
            hits += len(rx.findall(tx))
    return hits


def qc_pages(
    doc_id: str,
    pages: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    enriched_out_dir: Path,
    step2_out_dir: Path,
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    regs = compile_token_regex(cfg["tokens_regex"])
    min_hits = int(cfg["min_math_token_hits"])

    edge_cfg = cfg.get("edge_qc", {})
    edge_on = bool(edge_cfg.get("enabled", True))
    min_edges = int(edge_cfg.get("min_total_edge_pixels", 800))
    outside_thr = float(edge_cfg.get("outside_edge_ratio_ge", 0.55))

    by_page: Dict[int, List[Dict[str, Any]]] = {}
    for b in blocks:
        pi = int(b.get("page_index", -1))
        by_page.setdefault(pi, []).append(b)

    out = []
    for p in pages:
        pi = int(p["page_index"])
        page_blocks = by_page.get(pi, [])

        eq_mineru = sum(
            1 for b in page_blocks
            if b.get("layer") == "mineru" and b.get("content_type") == "equation"
        )
        eq_any = sum(1 for b in page_blocks if b.get("content_type") == "equation")

        # Stronger than PyMuPDF alone: check inline LaTeX in MinerU blocks too.
        inline_hits = mineru_inline_math_hits(page_blocks)

        pym_text = "\n".join(
            (b.get("text_raw") or "")
            for b in page_blocks
            if b.get("layer") == "pymupdf" and b.get("content_type") == "text"
        )
        token_hits = count_math_tokens(pym_text, regs)
        pym_struct_hits = pymupdf_math_structure_hits(pym_text)

        outside_ratio = 0.0
        total_edges = 0
        img_path = page_image_path(enriched_out_dir, step2_out_dir, p.get("image_relpath"))
        if edge_on and img_path and img_path.exists():
            mineru_boxes = [b for b in page_blocks if b.get("layer") == "mineru"]
            outside_ratio, total_edges = compute_edge_outside_ratio(img_path, mineru_boxes, min_edges)

        reasons: List[str] = []
        suspect = False

        # We classify pages into 3 buckets:
        #   A) has interline equations (eq_mineru > 0) -> not suspect
        #   B) has math present in text form (inline LaTeX OR PyMuPDF math-structure) -> not suspect
        #   C) math keywords/symbols hit but no evidence of math structure -> suspect (likely missing extraction or QC noise)

        if eq_mineru > 0:
            reasons.append("mineru_equation_present")
        else:
            if inline_hits > 0:
                reasons.append("inline_math_present_no_interline_equation")
            elif pym_struct_hits > 0:
                reasons.append("pymupdf_math_structure_present_no_mineru_equation")
            else:
                if token_hits >= min_hits:
                    suspect = True
                    reasons.append("keywords_or_symbols_hit_but_no_inline_latex_no_equation_no_math_structure")

        # Edge rule: only escalate to suspect if we do NOT already have math evidence
        # and the page has lots of unaccounted ink outside MinerU boxes.
        if (not suspect) and eq_mineru == 0 and inline_hits == 0 and pym_struct_hits == 0:
            if eq_mineru <= 1 and outside_ratio >= outside_thr and total_edges >= min_edges:
                suspect = True
                reasons.append("high_unaccounted_ink_outside_mineru_boxes")

        out.append({
            "doc_id": doc_id,
            "page_index": pi,
            "eq_mineru": eq_mineru,
            "eq_any": eq_any,
            "mineru_inline_math_hits": inline_hits,
            "math_token_hits_pymupdf": token_hits,
            "pymupdf_math_structure_hits": pym_struct_hits,
            "edge_total": total_edges,
            "edge_outside_ratio": outside_ratio,
            "suspect": suspect,
            "reasons": reasons,
        })

    return out

_PYM_MATH_STRUCT_PATTERNS = [
    r"[=±×÷≤≥≠≈]",           # operators
    r"\b(log|ln|exp)\s*\(",   # log(
    r"\bH\s*\(",              # H(
    r"\bIG\s*\(",             # IG(
    r"\bGini\b.*[=≤≥]",       # gini with operator somewhere
    r"\bP\s*\(",              # P(
    r"\bPr\s*\(",             # Pr(
    r"[_^]\s*\{",             # _{ or ^{
    r"\d+\s*/\s*\d+",         # simple fractions like 1/2
]
_PYM_STRUCT_RX = [re.compile(p, re.IGNORECASE) for p in _PYM_MATH_STRUCT_PATTERNS]

def pymupdf_math_structure_hits(text: str) -> int:
    if not text:
        return 0
    hits = 0
    for rx in _PYM_STRUCT_RX:
        hits += len(rx.findall(text))
    return hits

    