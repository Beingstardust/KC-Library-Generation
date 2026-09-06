from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from collections import Counter

from PIL import Image


# ----------------------------
# Basic JSONL IO
# ----------------------------

def is_truthy(v: Any) -> bool:
    if v is True:
        return True
    if v is False or v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        return s in {"true", "1", "yes", "y", "t"}
    return False

def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ----------------------------
# Image hashing (dHash 64)
# ----------------------------

def dhash64(image_path: Path) -> int:
    """
    dHash 64-bit:
    resize to 9x8 grayscale, compare adjacent pixels per row to produce 64 bits.
    """
    img = Image.open(image_path).convert("L").resize((9, 8))
    px = list(img.getdata())  # 72 pixels
    out = 0
    bit = 0
    for row in range(8):
        row_start = row * 9
        for col in range(8):
            left = px[row_start + col]
            right = px[row_start + col + 1]
            if left > right:
                out |= (1 << bit)
            bit += 1
    return out

def hamming_u64(a: int, b: int) -> int:
    return (a ^ b).bit_count()

def _try_paths(candidates: List[Path]) -> Optional[Path]:
    for p in candidates:
        if p and p.exists():
            return p
    return None

def build_page_images_basename_index(doc_id: str) -> Dict[str, Path]:
    """
    Robust, deterministic image discovery for Windows repo layout.

    We scan only likely roots, and only page_images folders, and we strongly prefer paths
    that include the doc_id in the directory path.

    Returns: basename -> resolved full path
    """
    cwd = Path.cwd()
    roots = []

    # preferred: step2 outputs typically live here
    p1 = cwd / "data" / "processed" / "blockstore"
    if p1.exists():
        roots.append(p1)

    # fallback: broader processed search
    p2 = cwd / "data" / "processed"
    if p2.exists():
        roots.append(p2)

    index: Dict[str, Path] = {}

    # scan patterns that are narrow, not whole-disk
    patterns = [
        f"**/{doc_id}/**/page_images/*.png",
        f"**/{doc_id}/**/page_images/*.jpg",
        f"**/{doc_id}/**/page_images/*.jpeg",
        f"**/{doc_id}/**/page_images/*.webp",
    ]

    for root in roots:
        for pat in patterns:
            for img in root.glob(pat):
                if not img.is_file():
                    continue
                bn = img.name
                # keep first hit deterministically
                if bn not in index:
                    index[bn] = img

    return index

def resolve_image_path(
    image_relpath: str,
    pages_jsonl: Path,
    basename_index: Dict[str, Path],
) -> Optional[Path]:
    """
    Resolve image_relpath into an existing file path.

    Resolution order:
      1) absolute path
      2) repo-relative
      3) relative to pages_jsonl folder and parents
      4) basename lookup (scanned from processed page_images folders)
    """
    if not image_relpath:
        return None

    p = Path(image_relpath)
    cwd = Path.cwd()

    # absolute
    if p.is_absolute() and p.exists():
        return p

    # repo relative
    repo_rel = cwd / p
    if repo_rel.exists():
        return repo_rel

    # relative to pages.jsonl location and a few parents
    candidates = [
        pages_jsonl.parent / p,
        pages_jsonl.parent.parent / p,
        pages_jsonl.parent.parent.parent / p,
        pages_jsonl.parent.parent.parent.parent / p,
    ]
    hit = _try_paths(candidates)
    if hit is not None:
        return hit

    # basename index fallback
    bn = p.name
    if bn in basename_index:
        return basename_index[bn]

    return None


# ----------------------------
# Tokenization (text-based reveal grouping)
# ----------------------------

_token_re = re.compile(r"[a-zA-Z]+|[0-9]+|[\u03B1-\u03C9\u0391-\u03A9]+|[^\s]")

def tokenize_for_signature(text: str) -> List[str]:
    if not text:
        return []
    return _token_re.findall(text.lower())


# ----------------------------
# Doctree traversal (schema-robust)
# ----------------------------

@dataclass
class DoctreeSpan:
    node_id: str
    title: str
    depth: int
    page_start: int
    page_end: int

def _as_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None

def _extract_title(node: Dict[str, Any]) -> str:
    for k in ["title", "name", "label", "text", "heading"]:
        v = node.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _extract_node_id(node: Dict[str, Any]) -> str:
    for k in ["node_id", "id", "uid", "key"]:
        v = node.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    base = json.dumps(
        {
            k: node.get(k)
            for k in sorted(node.keys())
            if k in ["title", "name", "label", "page_start", "page_end", "start_page", "end_page"]
        },
        sort_keys=True,
    )
    return "node_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

def _extract_page_range(node: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    ps = _as_int(node.get("page_start"))
    pe = _as_int(node.get("page_end"))
    if ps is not None and pe is not None:
        return ps, pe

    ps = _as_int(node.get("start_page"))
    pe = _as_int(node.get("end_page"))
    if ps is not None and pe is not None:
        return ps, pe

    pages = node.get("pages")
    if isinstance(pages, list) and pages:
        ints = [p for p in (_as_int(x) for x in pages) if p is not None]
        if ints:
            return min(ints), max(ints)

    pr = node.get("page_range")
    if isinstance(pr, dict):
        ps = _as_int(pr.get("start"))
        pe = _as_int(pr.get("end"))
        if ps is not None and pe is not None:
            return ps, pe

    if isinstance(pr, list) and len(pr) == 2:
        ps = _as_int(pr[0])
        pe = _as_int(pr[1])
        if ps is not None and pe is not None:
            return ps, pe

    return None

def collect_doctree_spans(doctree: Dict[str, Any], include_depths: List[int]) -> List[DoctreeSpan]:
    spans: List[DoctreeSpan] = []

    def walk(node: Dict[str, Any], depth: int) -> None:
        rng = _extract_page_range(node)
        if rng and depth in include_depths:
            spans.append(
                DoctreeSpan(
                    node_id=_extract_node_id(node),
                    title=_extract_title(node),
                    depth=depth,
                    page_start=rng[0],
                    page_end=rng[1],
                )
            )

        for ck in ["children", "nodes", "items", "subsections", "sections"]:
            ch = node.get(ck)
            if isinstance(ch, list):
                for c in ch:
                    if isinstance(c, dict):
                        walk(c, depth + 1)

    root = doctree.get("root")
    if isinstance(root, dict):
        walk(root, 0)
    elif isinstance(doctree, dict):
        walk(doctree, 0)

    norm: List[DoctreeSpan] = []
    for s in spans:
        ps, pe = s.page_start, s.page_end
        if pe < ps:
            ps, pe = pe, ps
        norm.append(DoctreeSpan(s.node_id, s.title, s.depth, ps, pe))
    return norm


# ----------------------------
# PageIndex cues and fallback spans
# ----------------------------

def extract_page_cues(page_rec: Dict[str, Any]) -> List[str]:
    cues: List[str] = []
    candidate_keys = [
        "title", "heading", "headings", "section", "subsection", "toc_path",
        "labels", "slide_title", "page_title",
    ]
    for k in candidate_keys:
        v = page_rec.get(k)
        if isinstance(v, str) and v.strip():
            cues.append(v.strip())
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x.strip():
                    cues.append(x.strip())
        elif isinstance(v, dict):
            for x in v.values():
                if isinstance(x, str) and x.strip():
                    cues.append(x.strip())

    seen = set()
    out = []
    for c in cues:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out

def normalize_heading(h: str) -> str:
    h = (h or "").strip()
    h = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", h)
    h = re.sub(r"\s+\d+\s*$", "", h)
    return h.strip()

def collect_spans_from_page_index(page_index_jsonl: Path, n_pages: int, min_span_pages: int, max_span_pages: int) -> List[DoctreeSpan]:
    heading_by_page: Dict[int, str] = {}
    for rec in iter_jsonl(page_index_jsonl):
        pi = rec.get("page_index")
        if pi is None:
            continue
        try:
            pi = int(pi)
        except Exception:
            continue
        cues = extract_page_cues(rec)
        primary = normalize_heading(cues[0]) if cues else ""
        if primary:
            heading_by_page[pi] = primary

    spans: List[DoctreeSpan] = []
    start = 0
    cur = heading_by_page.get(0, "")

    def flush(s: int, e: int, title: str) -> None:
        L = e - s + 1
        if L < min_span_pages or L > max_span_pages:
            return
        if not title:
            return
        node_id = "pi_" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
        spans.append(DoctreeSpan(node_id=node_id, title=title, depth=0, page_start=s, page_end=e))

    for p in range(1, n_pages):
        h = heading_by_page.get(p, "")
        if h == cur:
            continue
        flush(start, p - 1, cur)
        start = p
        cur = h

    flush(start, n_pages - 1, cur)
    return spans


# ----------------------------
# Build page text per page from blocks
# ----------------------------

def build_page_texts(
    blocks_jsonl: Path,
    use_field_order: List[str],
    drop_boilerplate_if_true: bool,
) -> Dict[int, str]:
    """
    Groups blocks by page_index and concatenates selected text fields.

    Determinism + auditability:
    - We probe the first N blocks (in file order) to discover which string fields are actually populated.
    - We then extend use_field_order with the most common populated fields (without removing user config).
    - We do NOT silently change the configured priority, we only append fallbacks.
    """
    PROBE_N = 500
    MIN_CHARS = 5

    # 1) probe which fields contain text
    probe_counts = Counter()
    probed = 0
    for b in iter_jsonl(blocks_jsonl):
        if drop_boilerplate_if_true and is_truthy(b.get("boilerplate")):
            continue
        for k, v in b.items():
            if isinstance(v, str) and len(v.strip()) >= MIN_CHARS:
                probe_counts[k] += 1
        probed += 1
        if probed >= PROBE_N:
            break

    # 2) extend field order with discovered candidates (deterministic)
    discovered = [k for k, _ in probe_counts.most_common(30)]
    field_order = list(use_field_order)
    for k in discovered:
        if k not in field_order:
            field_order.append(k)

    # 3) build page texts
    buf: Dict[int, List[str]] = {}
    for b in iter_jsonl(blocks_jsonl):
        pi = b.get("page_index")
        if pi is None:
            continue
        try:
            pi = int(pi)
        except Exception:
            continue

        if drop_boilerplate_if_true and is_truthy(b.get("boilerplate")):
            continue

        text = ""
        for f in field_order:
            v = b.get(f)
            if isinstance(v, str) and v.strip():
                text = v.strip()
                break

        if not text:
            continue

        buf.setdefault(pi, []).append(text)

    out: Dict[int, str] = {}
    for pi, parts in buf.items():
        out[pi] = "\n".join(parts)
    return out


# ----------------------------
# Reveal grouping (adjacency-only, text-first, image-fallback)
# ----------------------------

def build_reveal_groups(
    n_pages: int,
    page_texts: Dict[int, str],
    page_heading_norm: Dict[int, str],
    page_image_hash: Dict[int, int],
    page_image_ok: Dict[int, bool],
    rd: Dict[str, Any],
) -> Tuple[Dict[int, int], Dict[int, int], Dict[str, Any], Dict[int, int]]:
    enabled = bool(rd.get("enabled", True))
    if not enabled:
        page_to_group = {i: i for i in range(n_pages)}
        group_to_canonical = {i: i for i in range(n_pages)}
        token_counts = {i: 0 for i in range(n_pages)}
        stats = {"enabled": False}
        return page_to_group, group_to_canonical, stats, token_counts

    min_tokens = int(rd.get("min_tokens", 10))
    min_overlap_ratio = float(rd.get("min_overlap_ratio", 0.80))
    min_intersection_tokens = int(rd.get("min_intersection_tokens", 20))
    use_heading_gate = bool(rd.get("use_heading_gate", True))
    heading_mismatch_min_overlap = float(rd.get("heading_mismatch_min_overlap", 0.95))
    require_non_decreasing_tokens = bool(rd.get("require_non_decreasing_tokens", True))
    epsilon_token_growth = float(rd.get("epsilon_token_growth", 0.02))

    image_enabled = bool(rd.get("image_hash_enabled", False))
    image_max_hamming = int(rd.get("image_hash_max_hamming", 5))
    image_require_heading_match = bool(rd.get("image_hash_require_heading_match", True))
    image_heading_mismatch_max_hamming = int(rd.get("image_hash_heading_mismatch_max_hamming", 2))

    token_sets: List[set] = []
    token_counts_list: List[int] = []
    token_counts: Dict[int, int] = {}

    for i in range(n_pages):
        toks = tokenize_for_signature(page_texts.get(i, ""))
        token_sets.append(set(toks))
        token_counts_list.append(len(toks))
        token_counts[i] = len(toks)

    parent = list(range(n_pages))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    stats: Dict[str, Any] = {
        "enabled": True,
        "adj_pairs_total": max(0, n_pages - 1),

        "pages_with_any_text_tokens": sum(1 for i in range(n_pages) if token_counts_list[i] > 0),
        "pages_with_imagehash": sum(1 for i in range(n_pages) if page_image_ok.get(i, False)),

        "adj_pairs_attempt_text": 0,
        "adj_pairs_merged_text": 0,
        "adj_pairs_attempt_imagehash": 0,
        "adj_pairs_merged_imagehash": 0,

        "adj_pairs_skipped_text_min_tokens": 0,
        "adj_pairs_skipped_text_low_intersection": 0,
        "adj_pairs_skipped_text_low_overlap": 0,
        "adj_pairs_skipped_text_heading_gate": 0,
        "adj_pairs_skipped_text_token_decrease": 0,

        "adj_pairs_skipped_image_missing": 0,
        "adj_pairs_skipped_image_hamming": 0,
        "adj_pairs_skipped_image_heading_gate": 0,
    }

    for i in range(n_pages - 1):
        a, b = i, i + 1
        ca, cb = token_counts_list[a], token_counts_list[b]

        # Text attempt
        if min(ca, cb) >= min_tokens:
            stats["adj_pairs_attempt_text"] += 1
            A, B = token_sets[a], token_sets[b]
            if not A or not B:
                stats["adj_pairs_skipped_text_min_tokens"] += 1
            else:
                inter = len(A.intersection(B))
                if inter < min_intersection_tokens:
                    stats["adj_pairs_skipped_text_low_intersection"] += 1
                else:
                    overlap = inter / float(min(len(A), len(B)))
                    ha = page_heading_norm.get(a, "")
                    hb = page_heading_norm.get(b, "")
                    if use_heading_gate and ha and hb and ha != hb and overlap < heading_mismatch_min_overlap:
                        stats["adj_pairs_skipped_text_heading_gate"] += 1
                    elif overlap < min_overlap_ratio:
                        stats["adj_pairs_skipped_text_low_overlap"] += 1
                    elif require_non_decreasing_tokens and cb < int((1.0 - epsilon_token_growth) * ca):
                        stats["adj_pairs_skipped_text_token_decrease"] += 1
                    else:
                        union(a, b)
                        stats["adj_pairs_merged_text"] += 1
                        continue
        else:
            stats["adj_pairs_skipped_text_min_tokens"] += 1

        # Image fallback attempt
        if image_enabled:
            stats["adj_pairs_attempt_imagehash"] += 1
            ok_a = bool(page_image_ok.get(a, False))
            ok_b = bool(page_image_ok.get(b, False))
            if not (ok_a and ok_b):
                stats["adj_pairs_skipped_image_missing"] += 1
                continue

            ha_img = page_image_hash.get(a)
            hb_img = page_image_hash.get(b)
            if ha_img is None or hb_img is None:
                stats["adj_pairs_skipped_image_missing"] += 1
                continue

            ham = hamming_u64(ha_img, hb_img)

            ha = page_heading_norm.get(a, "")
            hb = page_heading_norm.get(b, "")
            headings_match = (ha == hb) if (ha and hb) else True

            if image_require_heading_match and not headings_match:
                if ham <= image_heading_mismatch_max_hamming:
                    union(a, b)
                    stats["adj_pairs_merged_imagehash"] += 1
                else:
                    stats["adj_pairs_skipped_image_heading_gate"] += 1
                continue

            if ham <= image_max_hamming:
                union(a, b)
                stats["adj_pairs_merged_imagehash"] += 1
            else:
                stats["adj_pairs_skipped_image_hamming"] += 1

    root_to_pages: Dict[int, List[int]] = {}
    for i in range(n_pages):
        r = find(i)
        root_to_pages.setdefault(r, []).append(i)

    groups = sorted((min(pages), pages) for pages in root_to_pages.values())
    page_to_group: Dict[int, int] = {}
    group_to_canonical: Dict[int, int] = {}

    for gid, (_, pages) in enumerate(groups):
        pages_sorted = sorted(pages)
        for p in pages_sorted:
            page_to_group[p] = gid
        group_to_canonical[gid] = pages_sorted[-1]

    return page_to_group, group_to_canonical, stats, token_counts


# ----------------------------
# Patch building
# ----------------------------

def make_patch_id(doc_id: str, patch_type: str, page_start: int, page_end: int, extra: str) -> str:
    s = f"{doc_id}|{patch_type}|{page_start}|{page_end}|{extra}"
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def build_page_patches(
    doc_id: str,
    doctree_json: Path,
    page_index_jsonl: Path,
    pages_jsonl: Path,
    blocks_jsonl: Path,
    cfg: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    pages = list(iter_jsonl(pages_jsonl))
    n_pages = len(pages)

    patches_cfg = cfg.get("patches")
    if not isinstance(patches_cfg, dict):
        raise RuntimeError("Config missing top-level 'patches' mapping. Expected patches.window_sizes and patches.window_stride.")

    if "window_sizes" not in patches_cfg:
        raise RuntimeError("Config missing patches.window_sizes. Add: patches: { window_sizes: [1,2,3], window_stride: 1 }")

    if "window_stride" not in patches_cfg:
        raise RuntimeError("Config missing patches.window_stride. Add: patches: { window_sizes: [1,2,3], window_stride: 1 }")

    # build basename index once per doc
    basename_index = build_page_images_basename_index(doc_id)

    # image hashes
    rd = cfg["reveal_dedupe"]
    image_hash_enabled = bool(rd.get("image_hash_enabled", False))
    page_image_hash: Dict[int, int] = {}
    page_image_ok: Dict[int, bool] = {}
    unresolved_relpaths: List[str] = []

    if image_hash_enabled:
        for rec in pages:
            pi = rec.get("page_index")
            if pi is None:
                continue
            try:
                pi = int(pi)
            except Exception:
                continue

            rel = rec.get("image_relpath") if isinstance(rec.get("image_relpath"), str) else ""
            p_img = resolve_image_path(rel, pages_jsonl, basename_index)
            if p_img is None:
                page_image_ok[pi] = False
                if rel and len(unresolved_relpaths) < 10:
                    unresolved_relpaths.append(rel)
                continue

            try:
                page_image_hash[pi] = dhash64(p_img)
                page_image_ok[pi] = True
            except Exception:
                page_image_ok[pi] = False

    # spans from doctree, fallback to page index heading spans
    doctree = json.loads(doctree_json.read_text(encoding="utf-8"))
    spans = collect_doctree_spans(doctree, include_depths=cfg["patches"]["doctree_spans"]["include_node_depths"])
    span_source = "doctree"
    if not spans:
        ds = cfg["patches"]["doctree_spans"]
        spans = collect_spans_from_page_index(
            page_index_jsonl=page_index_jsonl,
            n_pages=n_pages,
            min_span_pages=int(ds["min_span_pages"]),
            max_span_pages=int(ds["max_span_pages"]),
        )
        span_source = "page_index_heading_fallback"

    raw_span_lengths: List[int] = []
    raw_span_depth_hist: Dict[int, int] = {}
    for sp in spans:
        ps, pe = sp.page_start, sp.page_end
        if ps < 0 or pe < 0 or ps >= n_pages or pe >= n_pages:
            continue
        L = pe - ps + 1
        raw_span_lengths.append(L)
        raw_span_depth_hist[sp.depth] = raw_span_depth_hist.get(sp.depth, 0) + 1

    # page cues
    page_cues: Dict[int, List[str]] = {}
    for rec in iter_jsonl(page_index_jsonl):
        pi = rec.get("page_index")
        if pi is None:
            continue
        try:
            pi = int(pi)
        except Exception:
            continue
        page_cues[pi] = extract_page_cues(rec)

    page_heading_norm: Dict[int, str] = {}
    for pi in range(n_pages):
        cues = page_cues.get(pi, [])
        page_heading_norm[pi] = normalize_heading(cues[0]) if cues else ""

    # page texts
    page_texts = build_page_texts(
        blocks_jsonl=blocks_jsonl,
        use_field_order=cfg["text_build"]["use_field_order"],
        drop_boilerplate_if_true=cfg["text_build"]["drop_boilerplate_if_true"],
    )

    # reveal grouping
    page_to_group, group_to_canonical, reveal_stats, token_counts = build_reveal_groups(
        n_pages=n_pages,
        page_texts=page_texts,
        page_heading_norm=page_heading_norm,
        page_image_hash=page_image_hash,
        page_image_ok=page_image_ok,
        rd=rd,
    )

    reveal_rows: List[Dict[str, Any]] = []
    for pi in range(n_pages):
        gid = page_to_group[pi]
        dh = page_image_hash.get(pi)
        reveal_rows.append(
            {
                "doc_id": doc_id,
                "page_index": pi,
                "reveal_group_id": gid,
                "reveal_canonical_page_index": group_to_canonical[gid],
                "is_reveal_canonical": (pi == group_to_canonical[gid]),
                "token_count": int(token_counts.get(pi, 0)),
                "heading_norm": page_heading_norm.get(pi, ""),
                "image_hash_ok": bool(page_image_ok.get(pi, False)),
                "image_dhash64_hex": (hex(dh) if dh is not None else None),
            }
        )

    def patch_record(patch_type: str, ps: int, pe: int, doctree_nodes: List[DoctreeSpan]) -> Dict[str, Any]:
        nodes_ids = [n.node_id for n in doctree_nodes]
        nodes_titles = [n.title for n in doctree_nodes if n.title]

        cues: List[str] = []
        for p in range(ps, pe + 1):
            cues.extend(page_cues.get(p, []))

        seen = set()
        cues_dedup: List[str] = []
        for c in nodes_titles + cues:
            if not c or c in seen:
                continue
            seen.add(c)
            cues_dedup.append(c)

        gids = sorted({page_to_group[p] for p in range(ps, pe + 1)})
        noncanon = [p for p in range(ps, pe + 1) if p != group_to_canonical[page_to_group[p]]]

        pid = make_patch_id(doc_id, patch_type, ps, pe, extra=";".join(nodes_ids))

        return {
            "patch_id": pid,
            "doc_id": doc_id,
            "patch_type": patch_type,
            "page_start": ps,
            "page_end": pe,
            "n_pages": (pe - ps + 1),
            "doctree_node_ids": nodes_ids,
            "title_cues": cues_dedup,
            "reveal_group_ids": gids,
            "noncanonical_reveal_pages": noncanon,
            "span_source": span_source,
        }

    patches: List[Dict[str, Any]] = []

    # windows
    window_sizes = cfg["patches"]["window_sizes"]
    stride = int(cfg["patches"]["window_stride"])
    for w in window_sizes:
        w = int(w)
        if w <= 0:
            continue
        for ps in range(0, n_pages - w + 1, stride):
            pe = ps + w - 1
            patches.append(patch_record(f"window_{w}", ps, pe, doctree_nodes=[]))

    # doctree spans
    doctree_span_used = 0
    ds = cfg["patches"]["doctree_spans"]
    if bool(ds["enabled"]):
        min_span = int(ds["min_span_pages"])
        max_span = int(ds["max_span_pages"])
        for sp in spans:
            ps, pe = sp.page_start, sp.page_end
            if ps < 0 or pe < 0 or ps >= n_pages or pe >= n_pages:
                continue
            span_len = pe - ps + 1
            if span_len < min_span or span_len > max_span:
                continue
            patches.append(patch_record("structure_span", ps, pe, doctree_nodes=[sp]))
        doctree_span_used = sum(1 for p in patches if p["patch_type"] == "doctree_span")

    patches.sort(key=lambda r: (r["page_start"], r["page_end"], r["patch_type"], r["patch_id"]))

    type_counts: Dict[str, int] = {}
    for p in patches:
        type_counts[p["patch_type"]] = type_counts.get(p["patch_type"], 0) + 1

    reveal_group_sizes: Dict[int, int] = {}
    for pi in range(n_pages):
        gid = page_to_group[pi]
        reveal_group_sizes[gid] = reveal_group_sizes.get(gid, 0) + 1

    summary = {
        "doc_id": doc_id,
        "n_pages": n_pages,
        "n_patches": len(patches),
        "patch_type_counts": dict(sorted(type_counts.items())),
        "span_source": span_source,

        "n_reveal_groups": len(reveal_group_sizes),
        "reveal_group_size_hist": dict(sorted(reveal_group_sizes.items())),
        "canonical_pages": sum(1 for r in reveal_rows if r["is_reveal_canonical"]),
        "noncanonical_pages": sum(1 for r in reveal_rows if not r["is_reveal_canonical"]),

        "doctree_spans_raw_count": len(raw_span_lengths),
        "doctree_spans_raw_len_min": min(raw_span_lengths) if raw_span_lengths else None,
        "doctree_spans_raw_len_max": max(raw_span_lengths) if raw_span_lengths else None,
        "doctree_spans_raw_depth_hist": dict(sorted(raw_span_depth_hist.items())),
        "doctree_spans_used_count": doctree_span_used,

        "reveal_stats": reveal_stats,
        "image_debug": {
            "basename_index_size": len(basename_index),
            "unresolved_relpaths_head": unresolved_relpaths,
        },
    }

    return patches, summary, reveal_rows