from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kc_l.doctree.schema import DocNode
from kc_l.doctree.heuristics import clean_title, score_title_candidate
from kc_l.utils.fs import ensure_dir


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def load_active_step2_set(step2_sets_dir: Path, active_file: Path) -> Tuple[Path, Dict[str, Any]]:
    """
    Reads ACTIVE_STEP2_SET.txt to find the manifest filename, then loads it.
    """
    name = active_file.read_text(encoding="utf-8").strip()
    manifest_path = step2_sets_dir / name
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_path, data


def _group_blocks_by_layer_and_page(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[int, List[Dict[str, Any]]]]:
    out: Dict[str, Dict[int, List[Dict[str, Any]]]] = {}
    for b in blocks:
        layer = str(b.get("layer"))
        page = int(b.get("page_index", -1))
        out.setdefault(layer, {}).setdefault(page, []).append(b)

    # Deterministic ordering within each layer and page
    for layer, by_page in out.items():
        for page, lst in by_page.items():
            # Prefer raw_ref.index if present (preserves MinerU content_list order). :contentReference[oaicite:2]{index=2}
            lst.sort(key=lambda x: (int(x.get("page_index", -1)), int((x.get("raw_ref") or {}).get("index", 10**9))))
    return out


def _pick_page_title(
    doc_id: str,
    page_index: int,
    page_h: Optional[float],
    blocks_mineru: List[Dict[str, Any]],
    title_cfg: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    best = (0.0, None, None)  # score, text, block_id

    for b in blocks_mineru:
        if b.get("content_type") != "text":
            continue
        text = (b.get("text_raw") or "").strip()
        bbox = b.get("bbox_pt")
        y0 = None
        if isinstance(bbox, list) and len(bbox) == 4:
            y0 = float(bbox[1])

        s = score_title_candidate(
            text=text,
            y0=y0,
            page_h=page_h,
            cfg={
                "min_len": float(title_cfg["min_len"]),
                "max_len": float(title_cfg["max_len"]),
                "top_y_frac": float(title_cfg["top_y_frac"]),
                "min_alnum_ratio": float(title_cfg["min_alnum_ratio"]),
            },
        )
        if s > best[0]:
            best = (s, clean_title(text, int(title_cfg["max_title_chars"])), str(b.get("block_id")))

    if best[1] is None:
        return None, None, None
    return best[1], best[2], float(best[0])


def build_doctree_for_doc(
    doc_id: str,
    step2_out_dir: Path,
    run_id: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reads Step2 pages.jsonl and blocks.jsonl and builds a doc tree without cross-layer alignment.
    """
    pages_path = step2_out_dir / "pages.jsonl"
    blocks_path = step2_out_dir / "blocks.jsonl"
    doc_manifest_path = step2_out_dir / "doc_manifest.json"

    pages = _read_jsonl(pages_path)
    blocks = _read_jsonl(blocks_path)
    blocks_by = _group_blocks_by_layer_and_page(blocks)

    n_pages = len(pages)
    page_h_map = {int(p["page_index"]): float(p["height_pt"]) for p in pages}

    root_id = f"{doc_id}:doc"
    nodes: Dict[str, DocNode] = {}
    edges: List[Dict[str, str]] = []
    page_index_rows: List[Dict[str, Any]] = []

    nodes[root_id] = DocNode(
        node_id=root_id,
        doc_id=doc_id,
        node_type="doc",
        label=doc_id,
        page_index=None,
        parent_id=None,
        child_ids=[],
        block_ids_by_layer={},
        title=None,
        title_block_id=None,
        title_confidence=None,
        meta={
            "step2_out_dir": str(step2_out_dir).replace("\\", "/"),
            "run_id_step3": run_id,
        },
    )

    title_cfg = cfg["builder"]["title_detection"]
    preview_cfg = cfg["builder"]["page_preview"]
    leaf_cfg = cfg["builder"]["leaf_nodes"]
    prefer_layers = list(cfg["builder"]["prefer_layers"])

    title_found = 0

    for p in pages:
        pi = int(p["page_index"])
        page_node_id = f"{doc_id}:page:{pi}"

        by_layer_ids: Dict[str, List[str]] = {}
        by_layer_counts: Dict[str, int] = {}

        for layer in prefer_layers:
            page_blocks = blocks_by.get(layer, {}).get(pi, [])
            by_layer_ids[layer] = [str(b["block_id"]) for b in page_blocks]
            by_layer_counts[layer] = len(page_blocks)

        # Title from MinerU only (primary structured layer)
        mineru_page_blocks = blocks_by.get("mineru", {}).get(pi, [])
        title, title_block_id, title_conf = _pick_page_title(
            doc_id=doc_id,
            page_index=pi,
            page_h=page_h_map.get(pi),
            blocks_mineru=mineru_page_blocks,
            title_cfg=title_cfg,
        )
        if title:
            title_found += 1

        # Page preview: use first text blocks in MinerU order, excluding title block
        preview_parts: List[str] = []
        max_blocks = int(preview_cfg["max_blocks"])
        max_chars = int(preview_cfg["max_chars_per_block"])

        for b in mineru_page_blocks:
            if len(preview_parts) >= max_blocks:
                break
            if b.get("content_type") != "text":
                continue
            bid = str(b.get("block_id"))
            if title_block_id and bid == title_block_id:
                continue
            t = (b.get("text_raw") or "").strip()
            if not t:
                continue
            if len(t) > max_chars:
                t = t[:max_chars].rstrip()
            preview_parts.append(t)

        page_preview = "\n".join(preview_parts).strip()

        # Create page node
        nodes[page_node_id] = DocNode(
            node_id=page_node_id,
            doc_id=doc_id,
            node_type="page",
            label=f"page_{pi}",
            page_index=pi,
            parent_id=root_id,
            child_ids=[],
            block_ids_by_layer=by_layer_ids,
            title=title,
            title_block_id=title_block_id,
            title_confidence=title_conf,
            meta={
                "page_image_relpath": p.get("image_relpath"),
                "page_image_sha256": p.get("image_sha256"),
                "page_preview": page_preview,
                "block_counts_by_layer": by_layer_counts,
            },
        )
        nodes[root_id].child_ids.append(page_node_id)
        edges.append({"parent": root_id, "child": page_node_id})

        # Leaf nodes for tables, figures, equations (from MinerU only)
        if bool(leaf_cfg.get("enabled", True)):
            include_types = set(leaf_cfg.get("include_types", []))
            leaf_blocks = [b for b in mineru_page_blocks if str(b.get("content_type")) in include_types]

            for b in leaf_blocks:
                ctype = str(b.get("content_type"))
                bid = str(b.get("block_id"))
                leaf_id = f"{doc_id}:leaf:{pi}:{ctype}:{(b.get('raw_ref') or {}).get('index', 'x')}"
                nodes[leaf_id] = DocNode(
                    node_id=leaf_id,
                    doc_id=doc_id,
                    node_type="leaf",
                    label=f"{ctype}:{pi}",
                    page_index=pi,
                    parent_id=page_node_id,
                    child_ids=[],
                    block_ids_by_layer={"mineru": [bid]},
                    title=None,
                    title_block_id=None,
                    title_confidence=None,
                    meta={
                        "content_type": ctype,
                        "source_block_id": bid,
                    },
                )
                nodes[page_node_id].child_ids.append(leaf_id)
                edges.append({"parent": page_node_id, "child": leaf_id})

        page_index_rows.append(
            {
                "doc_id": doc_id,
                "page_index": pi,
                "page_node_id": page_node_id,
                "title": title,
                "title_block_id": title_block_id,
                "title_confidence": title_conf,
                "page_preview": page_preview,
                "block_ids_by_layer": by_layer_ids,
                "block_counts_by_layer": by_layer_counts,
            }
        )

    title_coverage = title_found / max(1, n_pages)

    stats = {
        "doc_id": doc_id,
        "run_id_step3": run_id,
        "n_pages": n_pages,
        "n_nodes": len(nodes),
        "title_found_pages": title_found,
        "title_coverage": title_coverage,
        "step2_out_dir": str(step2_out_dir).replace("\\", "/"),
        "step2_doc_manifest_exists": doc_manifest_path.exists(),
    }

    return {
        "nodes": [n.__dict__ for n in nodes.values()],
        "edges": edges,
        "page_index_rows": page_index_rows,
        "stats": stats,
    }