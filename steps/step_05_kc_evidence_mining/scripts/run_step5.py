from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

from kc_l.audit.manifests import build_input_manifest, env_snapshot, try_cmd_version


EXPECTED_EMBED_MODELS = {"qwen3-embedding:8b-q4_K_M", "qwen3-embedding:8b"}
EXPECTED_EMBED_DIM = 4096
ACTIVE_STEP5_EVIDENCE_SET = Path("data/processed/kc_evidence/_sets/ACTIVE_STEP5_EVIDENCE_SET.txt")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def jsonl_iter(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stat_payload(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {
        "size_bytes": int(st.st_size),
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def rel_path(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    repo_resolved = repo_root.resolve()
    try:
        return resolved.relative_to(repo_resolved).as_posix()
    except ValueError:
        return resolved.as_posix()


def describe_path(path: Path, repo_root: Path) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "path": rel_path(path, repo_root),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        payload["sha256"] = sha256_file(path)
        payload["stat"] = stat_payload(path)
    return payload


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required for Step 5.")
    obj = yaml.safe_load(read_text(path))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping at config root: {path}")
    return obj


def load_json(path: Path) -> Dict[str, Any]:
    obj = json.loads(read_text(path))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return obj


def import_step4_helpers(repo_root: Path):
    helper_path = (repo_root / "steps/step_04_structure_retrieval_index/scripts/run_step4_3.py").resolve()
    spec = importlib.util.spec_from_file_location("kc_l_step4_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import Step 4 helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class AuditLog:
    path: Path

    def info(self, message: str) -> None:
        line = f"[{now_utc_iso()}] {message}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line)


@dataclass
class DocContext:
    doc_id: str
    index_rows: List[Dict[str, Any]]
    indexed_corpus_rows: List[Dict[str, Any]]
    emb_mat: np.ndarray
    lex: Any
    lex_cfg: Dict[str, Any]
    stopwords: Optional[set[str]]
    patch_pages_map: Dict[str, List[int]]
    patch_heading_map: Dict[str, str]
    patch_type_map: Dict[str, str]
    patch_span_src_map: Dict[str, str]
    page_to_noncanon: Dict[int, bool]
    page_to_gid: Dict[int, str]
    page_to_rowids: Dict[int, List[int]]
    patch_docs: List[Tuple[str, str, List[str]]]
    patch_doc_df: Dict[str, int]


def choose_run_paths(repo_root: Path, processed_root_rel: str, runs_dir_rel: str, sets_dir_rel: str) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id_step5 = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (repo_root / processed_root_rel / run_id_step5).resolve()
        audit_dir = (repo_root / runs_dir_rel / f"{run_id_step5}_step5").resolve()
        set_path = (repo_root / sets_dir_rel / f"{run_id_step5}_step5_kc_evidence_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step5": Path(run_id_step5),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def build_reveal_maps(rows: List[Dict[str, Any]], s4: Any) -> Tuple[Dict[int, str], Dict[int, bool], Dict[str, int], Dict[int, str]]:
    page_to_gid: Dict[int, str] = {}
    page_to_noncanon: Dict[int, bool] = {}
    gid_to_canon: Dict[str, int] = {}
    page_heading: Dict[int, str] = {}
    for row in rows:
        page_index = row.get("page_index")
        if page_index is None:
            continue
        pi = int(page_index)
        gid_raw = row.get("reveal_group_id")
        if gid_raw is not None and gid_raw != "":
            gid = str(gid_raw)
            page_to_gid[pi] = gid
            page_to_noncanon[pi] = not bool(row.get("is_reveal_canonical", False))
            canon = row.get("reveal_canonical_page_index")
            if canon is not None:
                gid_to_canon[gid] = int(canon)
        heading = s4.norm_ws(str(row.get("heading_norm") or row.get("heading") or ""))
        if heading:
            page_heading[pi] = heading
    return page_to_gid, page_to_noncanon, gid_to_canon, page_heading


def extract_keywords(title: str, seed_definition: str, s4: Any, max_terms: int) -> List[str]:
    title_tokens = set(
        s4.tokenize(
            title,
            max_token_len=40,
            lowercase=True,
            stopwords=s4._MIN_STOP,
        )
    )
    tokens = s4.tokenize(
        seed_definition,
        max_token_len=40,
        lowercase=True,
        stopwords=s4._MIN_STOP,
    )
    counts: Counter[str] = Counter()
    first_pos: Dict[str, int] = {}
    for idx, token in enumerate(tokens):
        if len(token) < 3 or token.isdigit():
            continue
        if token in title_tokens:
            continue
        counts[token] += 1
        first_pos.setdefault(token, idx)
    ranked = sorted(counts, key=lambda tok: (-counts[tok], first_pos[tok], tok))
    return ranked[:max_terms]


def build_queries(kc_row: Dict[str, Any], cfg: Dict[str, Any], s4: Any) -> List[str]:
    runtime_cfg = cfg.get("runtime", {})
    max_queries = int(cfg["retrieval"]["per_kc"]["max_queries_per_kc"])
    def_max_chars = int(runtime_cfg.get("seed_definition_max_chars", 240))
    keyword_max_terms = int(runtime_cfg.get("keyword_query_max_terms", 8))

    title = str(kc_row.get("canonical_name") or "").strip()
    seed_definition = str(kc_row.get("seed_definition") or "").strip()

    queries: List[str] = []
    seen: set[str] = set()

    def add_query(text: str) -> None:
        normalized = s4.norm_ws(text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append(normalized)

    add_query(title)
    if seed_definition:
        add_query(f"{title} {s4.pretruncate(seed_definition, def_max_chars)}")
        keywords = extract_keywords(title, seed_definition, s4, max_terms=keyword_max_terms)
        if keywords:
            add_query(" ".join(keywords))
    return queries[:max_queries]


def load_step4_runtime_cfg(step4_cfg_path: Path) -> Dict[str, Any]:
    cfg = load_yaml(step4_cfg_path)
    model = str(cfg["embedding"]["model"])
    dims = int(cfg["embedding"]["dimensions"])
    if model not in EXPECTED_EMBED_MODELS:
        raise RuntimeError(f"Step 4 embedding model mismatch: {model}; expected one of {sorted(EXPECTED_EMBED_MODELS)}")
    if dims != EXPECTED_EMBED_DIM:
        raise RuntimeError(f"Step 4 embedding dimensions mismatch: {dims}")
    return cfg


def load_doc_context(repo_root: Path, doc_id: str, step4_set: Dict[str, Any], patch_set: Dict[str, Any], step4_cfg: Dict[str, Any], s4: Any) -> Tuple[DocContext, List[Path]]:
    doc_entry = step4_set["docs"][doc_id]

    raw_patch_docs = patch_set.get("docs", {})
    if isinstance(raw_patch_docs, list):
        patch_docs_by_id = {
            str(row["doc_id"]): row
            for row in raw_patch_docs
            if isinstance(row, dict) and "doc_id" in row
        }
    elif isinstance(raw_patch_docs, dict):
        patch_docs_by_id = {str(k): v for k, v in raw_patch_docs.items()}
    else:
        raise RuntimeError(
            f"Unsupported Step 4 patches set docs shape: {type(raw_patch_docs).__name__}"
        )

    if doc_id not in patch_docs_by_id:
        raise KeyError(f"Missing patch entry for doc_id={doc_id}")

    patch_entry = patch_docs_by_id[doc_id]

    index_rows_path = s4.resolve_doc_file(repo_root, doc_entry, "index_rows.jsonl", ["index_rows.jsonl", "index_rows"])
    corpus_path = s4.resolve_doc_file(repo_root, doc_entry, "block_text_corpus.jsonl", ["block_text_corpus.jsonl", "block_text_corpus"])
    emb_meta_path = s4.resolve_doc_file(repo_root, doc_entry, "meta.json", ["embeddings/meta.json", "embeddings_meta", "meta"])
    emb_rows_path = s4.resolve_doc_file(repo_root, doc_entry, "rows.jsonl", ["embeddings/rows.jsonl", "embeddings_rows"])
    emb_matrix_path = s4.resolve_doc_file(repo_root, doc_entry, "embeddings.f32.npy", ["embeddings/embeddings.f32.npy", "embeddings_matrix"])
    vector_meta_path = s4.resolve_doc_file(repo_root, doc_entry, "meta.json", ["vector_index/meta.json", "vector_meta"])
    vector_index_path = s4.resolve_doc_file(repo_root, doc_entry, "faiss.index", ["vector_index/faiss.index", "faiss.index"])
    lex_meta_path = s4.resolve_doc_file(repo_root, doc_entry, "meta.json", ["lexical/meta.json", "lexical_meta"])
    vocab_path = s4.resolve_doc_file(repo_root, doc_entry, "vocab.json", ["lexical/vocab.json", "lexical_vocab"])
    df_path = s4.resolve_doc_file(repo_root, doc_entry, "df.i32.npy", ["lexical/df.i32.npy", "lexical_df"])
    idf_path = s4.resolve_doc_file(repo_root, doc_entry, "idf.f32.npy", ["lexical/idf.f32.npy", "lexical_idf"])
    doclens_path = s4.resolve_doc_file(repo_root, doc_entry, "doclens.i32.npy", ["lexical/doclens.i32.npy", "lexical_doclens"])
    postings_offsets_path = s4.resolve_doc_file(repo_root, doc_entry, "postings_offsets.i64.npy", ["lexical/postings_offsets.i64.npy", "lexical_postings_offsets"])
    postings_docids_path = s4.resolve_doc_file(repo_root, doc_entry, "postings_docids.i32.npy", ["lexical/postings_docids.i32.npy", "lexical_postings_docids"])
    postings_tfs_path = s4.resolve_doc_file(repo_root, doc_entry, "postings_tfs.i16.npy", ["lexical/postings_tfs.i16.npy", "lexical_postings_tfs"])
    patch_index_path = s4.resolve_doc_file(repo_root, patch_entry, "page_patch_index.jsonl", ["page_patch_index.jsonl", "page_patch_index"])
    reveal_groups_path = s4.resolve_doc_file(repo_root, patch_entry, "page_reveal_groups.jsonl", ["page_reveal_groups.jsonl", "page_reveal_groups"])

    emb_rows_path = emb_rows_path if emb_rows_path.exists() else (emb_meta_path.parent / "rows.jsonl")
    emb_matrix_path = emb_matrix_path if emb_matrix_path.exists() else (emb_meta_path.parent / "embeddings.f32.npy")
    vector_index_path = vector_index_path if vector_index_path.exists() else (vector_meta_path.parent / "faiss.index")
    vocab_path = vocab_path if vocab_path.exists() else (lex_meta_path.parent / "vocab.json")
    df_path = df_path if df_path.exists() else (lex_meta_path.parent / "df.i32.npy")
    idf_path = idf_path if idf_path.exists() else (lex_meta_path.parent / "idf.f32.npy")
    doclens_path = doclens_path if doclens_path.exists() else (lex_meta_path.parent / "doclens.i32.npy")
    postings_offsets_path = postings_offsets_path if postings_offsets_path.exists() else (lex_meta_path.parent / "postings_offsets.i64.npy")
    postings_docids_path = postings_docids_path if postings_docids_path.exists() else (lex_meta_path.parent / "postings_docids.i32.npy")
    postings_tfs_path = postings_tfs_path if postings_tfs_path.exists() else (lex_meta_path.parent / "postings_tfs.i16.npy")

    input_paths = [
        index_rows_path,
        corpus_path,
        emb_meta_path,
        emb_rows_path,
        emb_matrix_path,
        vector_meta_path,
        vector_index_path,
        lex_meta_path,
        vocab_path,
        df_path,
        idf_path,
        doclens_path,
        postings_offsets_path,
        postings_docids_path,
        postings_tfs_path,
        patch_index_path,
        reveal_groups_path,
    ]

    index_rows = sorted(list(jsonl_iter(index_rows_path)), key=lambda row: int(row["row_id"]))
    indexed_corpus_rows = [row for row in jsonl_iter(corpus_path) if bool(row.get("is_indexed"))]
    if len(index_rows) != len(indexed_corpus_rows):
        raise RuntimeError(f"{doc_id}: index_rows/corpus indexed length mismatch")
    for expected_row_id, (index_row, corpus_row) in enumerate(zip(index_rows, indexed_corpus_rows)):
        if int(index_row["row_id"]) != expected_row_id:
            raise RuntimeError(f"{doc_id}: non-contiguous row_id at {expected_row_id}")
        if str(index_row["block_id"]) != str(corpus_row["block_id"]):
            raise RuntimeError(f"{doc_id}: block alignment mismatch at row {expected_row_id}")

    emb_meta = load_json(emb_meta_path)
    if str(emb_meta.get("model")) not in EXPECTED_EMBED_MODELS:
        raise RuntimeError(f"{doc_id}: embedding model mismatch in embeddings/meta.json")
    if int(emb_meta.get("dimensions")) != EXPECTED_EMBED_DIM:
        raise RuntimeError(f"{doc_id}: embedding dimension mismatch in embeddings/meta.json")
    emb_mat = np.load(emb_matrix_path)
    if emb_mat.ndim != 2 or emb_mat.shape[1] != EXPECTED_EMBED_DIM:
        raise RuntimeError(f"{doc_id}: unexpected embedding matrix shape {emb_mat.shape}")
    if emb_mat.shape[0] != len(index_rows):
        raise RuntimeError(f"{doc_id}: embeddings/index_rows length mismatch")

    vector_meta = load_json(vector_meta_path)
    if int(vector_meta.get("dimensions", EXPECTED_EMBED_DIM)) != EXPECTED_EMBED_DIM:
        raise RuntimeError(f"{doc_id}: vector dimensions mismatch in vector_index/meta.json")

    lex_meta = load_json(lex_meta_path)
    stopwords = s4._MIN_STOP if str(lex_meta.get("stopwords")) == "minimal_v1" else None
    lex = s4.LexicalIndex(
        vocab=load_json(vocab_path),
        df=np.load(df_path),
        idf=np.load(idf_path),
        doclens=np.load(doclens_path),
        offsets=np.load(postings_offsets_path),
        post_docids=np.load(postings_docids_path),
        post_tfs=np.load(postings_tfs_path),
        avgdl=float(lex_meta["avgdl"]),
        k1=float(lex_meta["k1"]),
        b=float(lex_meta["b"]),
    )
    if int(lex_meta["n_docs"]) != len(index_rows):
        raise RuntimeError(f"{doc_id}: lexical n_docs mismatch")

    reveal_rows = list(jsonl_iter(reveal_groups_path))
    page_to_gid, page_to_noncanon, _, page_heading = build_reveal_maps(reveal_rows, s4)
    patch_rows = list(jsonl_iter(patch_index_path))

    patch_pages_map: Dict[str, List[int]] = {}
    patch_heading_map: Dict[str, str] = {}
    patch_type_map: Dict[str, str] = {}
    patch_span_src_map: Dict[str, str] = {}

    page_sample_texts: Dict[int, List[str]] = {}
    page_to_rowids: Dict[int, List[int]] = {}
    for row_id, (index_row, corpus_row) in enumerate(zip(index_rows, indexed_corpus_rows)):
        page_index = int(index_row["page_index"])
        page_to_rowids.setdefault(page_index, []).append(row_id)
        samples = page_sample_texts.setdefault(page_index, [])
        if len(samples) < 2:
            sample = s4.stable_phrase(str(corpus_row.get("text") or ""), max_words=20, max_chars=180)
            if sample:
                samples.append(sample)

    for idx, patch_row in enumerate(patch_rows):
        patch_id = s4.patch_id(patch_row, idx)
        pages = s4.patch_pages(patch_row)
        patch_pages_map[patch_id] = pages
        patch_type_map[patch_id] = s4.patch_type(patch_row)
        patch_span_src_map[patch_id] = s4.patch_span_source(patch_row)
        heading = s4.patch_heading(patch_row)
        if not heading and pages:
            heading = page_heading.get(pages[0], "")
        if not heading:
            for page_index in pages:
                candidates = page_sample_texts.get(page_index, [])
                if candidates:
                    heading = candidates[0]
                    break
        patch_heading_map[patch_id] = s4.norm_ws(heading)

    patch_docs: List[Tuple[str, str, List[str]]] = []
    patch_doc_df: Dict[str, int] = {}
    for idx, patch_row in enumerate(patch_rows):
        patch_id = s4.patch_id(patch_row, idx)
        sample_parts: List[str] = []
        for page_index in patch_pages_map.get(patch_id, []):
            sample_parts.extend(page_sample_texts.get(page_index, [])[:2])
        sample_text = " ".join(sample_parts[:6])
        text = s4.norm_ws(
            f"{patch_heading_map.get(patch_id, '')} {patch_type_map.get(patch_id, 'unknown')} "
            f"{patch_span_src_map.get(patch_id, 'unknown')} {sample_text}"
        )
        tokens = s4.tokenize(
            text,
            max_token_len=int(lex_meta["max_token_len"]),
            lowercase=bool(lex_meta["lowercase"]),
            stopwords=stopwords,
        )
        patch_docs.append((patch_id, text, tokens))
        for token in set(tokens):
            patch_doc_df[token] = patch_doc_df.get(token, 0) + 1

    return (
        DocContext(
            doc_id=doc_id,
            index_rows=index_rows,
            indexed_corpus_rows=indexed_corpus_rows,
            emb_mat=emb_mat,
            lex=lex,
            lex_cfg=lex_meta,
            stopwords=stopwords,
            patch_pages_map=patch_pages_map,
            patch_heading_map=patch_heading_map,
            patch_type_map=patch_type_map,
            patch_span_src_map=patch_span_src_map,
            page_to_noncanon=page_to_noncanon,
            page_to_gid=page_to_gid,
            page_to_rowids=page_to_rowids,
            patch_docs=patch_docs,
            patch_doc_df=patch_doc_df,
        ),
        input_paths,
    )


def navigate_rank(doc_ctx: DocContext, query: str, top_patches: int, s4: Any) -> List[Tuple[str, float]]:
    query_tokens = s4.tokenize(
        query,
        max_token_len=int(doc_ctx.lex_cfg["max_token_len"]),
        lowercase=bool(doc_ctx.lex_cfg["lowercase"]),
        stopwords=doc_ctx.stopwords,
    )
    n_patches = len(doc_ctx.patch_docs)
    scores: List[Tuple[str, float]] = []
    for patch_id, _, tokens in doc_ctx.patch_docs:
        tf: Dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        score = 0.0
        for token in query_tokens:
            df = doc_ctx.patch_doc_df.get(token)
            if df is None:
                continue
            score += s4.bm25_idf(n_patches, df) * float(tf.get(token, 0))
        scores.append((patch_id, score))
    scores.sort(key=lambda item: (-item[1], item[0]))
    return scores[:top_patches]


def fetch_rank(
    doc_ctx: DocContext,
    query: str,
    query_vector: np.ndarray,
    selected_nav: List[Tuple[str, float]],
    top_blocks: int,
    scoring_cfg: Dict[str, Any],
    s4: Any,
) -> List[Dict[str, Any]]:
    selected_patch_ids = [patch_id for patch_id, _ in selected_nav]
    candidate_rowids: set[int] = set()
    page_best_patch: Dict[int, Tuple[str, float]] = {}
    for patch_id, nav_score in selected_nav:
        for page_index in doc_ctx.patch_pages_map.get(patch_id, []):
            candidate_rowids.update(doc_ctx.page_to_rowids.get(page_index, []))
            current = page_best_patch.get(page_index)
            if current is None or float(nav_score) > float(current[1]) or (
                float(nav_score) == float(current[1]) and patch_id < current[0]
            ):
                page_best_patch[page_index] = (patch_id, float(nav_score))
    if not candidate_rowids:
        return []

    query_tokens = s4.tokenize(
        query,
        max_token_len=int(doc_ctx.lex_cfg["max_token_len"]),
        lowercase=bool(doc_ctx.lex_cfg["lowercase"]),
        stopwords=doc_ctx.stopwords,
    )
    lex_scores = dict(doc_ctx.lex.score(query_tokens, topk=max(200, top_blocks * 20)))
    sims = doc_ctx.emb_mat @ query_vector if doc_ctx.emb_mat.shape[0] > 0 else np.zeros((0,), dtype=np.float32)
    max_lex = max(lex_scores.values()) if lex_scores else 0.0
    layer_prior = {str(key).lower(): float(value) for key, value in scoring_cfg["layer_prior"].items()}

    ranked: List[Tuple[int, float, float, float]] = []
    for row_id in sorted(candidate_rowids):
        index_row = doc_ctx.index_rows[row_id]
        lex_score = float(lex_scores.get(row_id, 0.0))
        lex_norm = lex_score / (max_lex + 1e-12) if max_lex > 0.0 else 0.0
        emb_raw = float(sims[row_id])
        emb01 = (emb_raw + 1.0) / 2.0
        combined = float(scoring_cfg["w_lex"]) * lex_norm + float(scoring_cfg["w_emb"]) * emb01
        combined *= float(layer_prior.get(str(index_row["layer"]).lower(), 1.0))
        if bool(index_row.get("is_noncanonical_reveal_page")):
            combined *= float(scoring_cfg["noncanonical_page_penalty"])
        ranked.append((row_id, combined, lex_norm, emb01))

    ranked.sort(key=lambda item: (-item[1], doc_ctx.index_rows[item[0]]["block_id"]))
    results: List[Dict[str, Any]] = []
    query_token_set = set(query_tokens)
    for row_id, combined, lex_norm, emb01 in ranked[:top_blocks]:
        index_row = doc_ctx.index_rows[row_id]
        corpus_row = doc_ctx.indexed_corpus_rows[row_id]
        page_index = int(index_row["page_index"])
        boosted = False
        for patch_id in selected_patch_ids:
            if doc_ctx.patch_type_map.get(patch_id) != "structure_span":
                continue
            heading = doc_ctx.patch_heading_map.get(patch_id, "")
            if not heading:
                continue
            heading_tokens = set(
                s4.tokenize(
                    heading,
                    max_token_len=int(doc_ctx.lex_cfg["max_token_len"]),
                    lowercase=bool(doc_ctx.lex_cfg["lowercase"]),
                    stopwords=doc_ctx.stopwords,
                )
            )
            if heading_tokens and query_token_set and (len(heading_tokens & query_token_set) / max(1, len(query_token_set))) >= 0.2:
                combined = combined * float(scoring_cfg["structure_span_boost"])
                boosted = True
                break

        patch_id, nav_score = page_best_patch.get(page_index, ("", 0.0))
        results.append(
            {
                "doc_id": doc_ctx.doc_id,
                "block_id": str(index_row["block_id"]),
                "page_index": page_index,
                "bbox": index_row.get("bbox"),
                "layer": str(index_row["layer"]),
                "reveal_group_id": index_row.get("reveal_group_id"),
                "patch_id": patch_id or None,
                "patch_heading": doc_ctx.patch_heading_map.get(patch_id, "") or None,
                "query_used": query,
                "scores": {
                    "combined": float(combined),
                    "lex_norm": float(lex_norm),
                    "emb01": float(emb01),
                    "navigate_score": float(nav_score),
                    "boosted_structure_span": bool(boosted),
                },
                "snippet": s4.safe_snip(str(corpus_row.get("text") or ""), 260),
                "_source_text": str(corpus_row.get("text") or ""),
            }
        )
    return results


def candidate_sort_key(candidate: Dict[str, Any]) -> Tuple[Any, ...]:
    scores = candidate["scores"]
    return (
        float(scores["combined"]),
        float(scores.get("navigate_score") or 0.0),
        -int(candidate.get("_query_ordinal", 0)),
        -int(candidate.get("page_index", -1)),
        str(candidate["doc_id"]),
        str(candidate["block_id"]),
    )


def better_candidate(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
    return candidate_sort_key(candidate) > candidate_sort_key(current)


def dedupe_candidates(candidates: List[Dict[str, Any]], enable_reveal_fp_dedupe: bool, s4: Any) -> List[Dict[str, Any]]:
    by_block: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for candidate in candidates:
        key = (str(candidate["doc_id"]), str(candidate["block_id"]))
        current = by_block.get(key)
        if current is None or better_candidate(candidate, current):
            by_block[key] = candidate

    deduped = list(by_block.values())
    if not enable_reveal_fp_dedupe:
        return deduped

    by_fp: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    passthrough: List[Dict[str, Any]] = []
    for candidate in deduped:
        reveal_group_id = candidate.get("reveal_group_id")
        source_text = str(candidate.get("_source_text") or "")
        if reveal_group_id in (None, "") or not source_text:
            passthrough.append(candidate)
            continue
        fp = s4.fingerprint_text(source_text)
        key = (str(candidate["doc_id"]), str(reveal_group_id), fp)
        current = by_fp.get(key)
        if current is None or better_candidate(candidate, current):
            by_fp[key] = candidate

    merged = passthrough + list(by_fp.values())
    merged.sort(key=lambda candidate: (-float(candidate["scores"]["combined"]), candidate["doc_id"], int(candidate["page_index"]), candidate["block_id"]))
    return merged


def apply_diversity(candidates: List[Dict[str, Any]], max_blocks: int, score_tolerance: float) -> List[Dict[str, Any]]:
    remaining = sorted(
        candidates,
        key=lambda candidate: (-float(candidate["scores"]["combined"]), candidate["doc_id"], int(candidate["page_index"]), candidate["block_id"]),
    )
    selected: List[Dict[str, Any]] = []
    page_counts: Counter[Tuple[str, int]] = Counter()
    patch_counts: Counter[Tuple[str, str]] = Counter()

    while remaining and len(selected) < max_blocks:
        best_score = float(remaining[0]["scores"]["combined"])
        pool: List[Dict[str, Any]] = []
        for candidate in remaining:
            if best_score - float(candidate["scores"]["combined"]) > score_tolerance:
                break
            pool.append(candidate)

        chosen = min(
            pool,
            key=lambda candidate: (
                page_counts[(str(candidate["doc_id"]), int(candidate["page_index"]))],
                patch_counts[(str(candidate["doc_id"]), str(candidate.get("patch_id") or ""))],
                -float(candidate["scores"]["combined"]),
                str(candidate["doc_id"]),
                int(candidate["page_index"]),
                str(candidate["block_id"]),
            ),
        )
        selected.append(chosen)
        page_counts[(str(chosen["doc_id"]), int(chosen["page_index"]))] += 1
        patch_counts[(str(chosen["doc_id"]), str(chosen.get("patch_id") or ""))] += 1
        remaining.remove(chosen)

    selected.sort(key=lambda candidate: (-float(candidate["scores"]["combined"]), candidate["doc_id"], int(candidate["page_index"]), candidate["block_id"]))
    return selected


def strip_internal_fields(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": candidate["doc_id"],
        "block_id": candidate["block_id"],
        "page_index": candidate["page_index"],
        "bbox": candidate.get("bbox"),
        "layer": candidate["layer"],
        "reveal_group_id": candidate.get("reveal_group_id"),
        "patch_id": candidate.get("patch_id"),
        "patch_heading": candidate.get("patch_heading"),
        "query_used": candidate["query_used"],
        "scores": candidate["scores"],
        "snippet": candidate["snippet"],
    }


def percentile_p90(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(0.9 * len(ordered)) - 1)
    return int(ordered[index])


def select_sample_rows(rows: List[Dict[str, Any]], sample_kcs: int) -> List[Dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: str(row["kc_id"]))
    with_evidence = [row for row in ordered if row["evidence"]]
    without_evidence = [row for row in ordered if not row["evidence"]]
    sample = with_evidence[:sample_kcs]
    if len(sample) < sample_kcs:
        sample.extend(without_evidence[: sample_kcs - len(sample)])
    return sample


def build_output_manifest(repo_root: Path, processed_dir: Path, set_path: Path, active_pointer_path: Path) -> Dict[str, Any]:
    outputs: Dict[str, Any] = {
        "processed_outputs": [],
        "set_manifest": describe_path(set_path, repo_root),
        "active_pointer": describe_path(active_pointer_path, repo_root),
    }
    for path in sorted(processed_dir.rglob("*")):
        if not path.is_file():
            continue
        outputs["processed_outputs"].append(describe_path(path, repo_root))
    return outputs


def tool_versions(base_url: str, s4: Any) -> Dict[str, Any]:
    faiss_available = False
    try:
        import faiss  # type: ignore

        faiss_available = bool(getattr(faiss, "__version__", True))
    except Exception:
        faiss_available = False

    versions: Dict[str, Any] = {
        "python": sys.version,
        "numpy": np.__version__,
        "pyyaml_available": yaml is not None,
        "faiss_available": faiss_available,
        "ollama_cli": try_cmd_version(["ollama", "--version"]),
    }
    try:
        versions["ollama_http_version"] = s4.ollama_version(base_url)
    except Exception as exc:
        versions["ollama_http_version_error"] = repr(exc)
    return versions


def run() -> int:
    parser = argparse.ArgumentParser(description="STEP 5: KC evidence mining.")
    parser.add_argument("--config", required=True, help="Repo-relative YAML config path.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    cfg = load_yaml(config_path)
    s4 = import_step4_helpers(repo_root)

    inputs_cfg = cfg["inputs"]
    outputs_cfg = cfg["outputs"]
    runtime_cfg = cfg.get("runtime", {})
    per_kc_cfg = cfg["retrieval"]["per_kc"]
    dedupe_cfg = cfg["retrieval"]["dedupe"]

    run_paths = choose_run_paths(
        repo_root=repo_root,
        processed_root_rel=str(outputs_cfg["processed_root"]),
        runs_dir_rel=str(cfg["audit"]["runs_dir"]),
        sets_dir_rel=str(outputs_cfg["sets_dir"]),
    )
    run_id_step5 = run_paths["run_id_step5"].name
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    active_pointer_path = (repo_root / ACTIVE_STEP5_EVIDENCE_SET).resolve()

    audit_dir.mkdir(parents=True, exist_ok=False)
    processed_dir.mkdir(parents=True, exist_ok=False)
    logger = AuditLog(audit_dir / "logs" / "run.log")
    started = time.perf_counter()
    timings: Dict[str, Any] = {"started_utc": now_utc_iso()}

    write_text(audit_dir / "config.snapshot.yaml", read_text(config_path))
    write_json(
        audit_dir / "invocation.json",
        {
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "repo_root": str(repo_root),
            "config_path": rel_path(config_path, repo_root),
        },
    )

    try:
        kc_registry_path = (repo_root / str(inputs_cfg["kc_registry_path"])).resolve()
        if not kc_registry_path.exists():
            raise FileNotFoundError(f"Missing KC registry: {kc_registry_path}")

        step4_pointer_path = (repo_root / str(inputs_cfg["step4_active_set_pointer"])).resolve()
        step4_set_path = s4.resolve_active_pointer(step4_pointer_path)
        step4_set = load_json(step4_set_path)

        if "provenance" in step4_set:
            patch_target_raw = step4_set["provenance"]["step4_patches_set"]["target_path"]
            step4_run_audit_raw = step4_set["provenance"]["retrieval_run_audit_dir"]
        else:
            patch_target_raw = step4_set.get("input_step4_patches_set")
            step4_run_audit_raw = step4_set.get("run_dir_step4_3")

        if not patch_target_raw:
            raise KeyError("Missing linked Step 4 patches set path in Step 4 manifest.")
        patch_set_path = Path(str(patch_target_raw))
        if not patch_set_path.is_absolute():
            patch_set_path = (step4_set_path.parent / patch_set_path).resolve()
        if not patch_set_path.exists():
            raise FileNotFoundError(f"Missing linked Step 4 patches set: {patch_set_path}")
        patch_set = load_json(patch_set_path)

        if not step4_run_audit_raw:
            raise KeyError("Missing Step 4 run audit dir in Step 4 manifest.")
        step4_run_audit_dir = Path(str(step4_run_audit_raw))
        if not step4_run_audit_dir.is_absolute():
            step4_run_audit_dir = (repo_root / step4_run_audit_dir).resolve()
        step4_cfg_path = (step4_run_audit_dir / "config_snapshot.yaml").resolve()
        if not step4_cfg_path.exists():
            raise FileNotFoundError(f"Missing Step 4 config snapshot: {step4_cfg_path}")
        step4_cfg = load_step4_runtime_cfg(step4_cfg_path)

        logger.info(
            "Using active Step 4 index set plus linked Step 4 patches set: "
            f"{step4_set_path} -> {patch_set_path}"
        )

        write_json(audit_dir / "environment_snapshot.json", env_snapshot())
        write_json(audit_dir / "tool_versions.json", tool_versions(str(step4_cfg["embedding"]["base_url"]), s4))

        registry_rows = [json.loads(line) for line in read_text(kc_registry_path).splitlines() if line.strip()]
        registry_rows = sorted(registry_rows, key=lambda row: str(row["kc_id"]))
        logger.info(f"Loaded KC registry rows: {len(registry_rows)}")

        docs_sorted = sorted(step4_set["docs"].keys())
        doc_contexts: Dict[str, DocContext] = {}
        input_paths: List[Path] = [config_path, kc_registry_path, step4_pointer_path, step4_set_path, patch_set_path, step4_cfg_path]

        load_started = time.perf_counter()
        for doc_id in docs_sorted:
            doc_ctx, doc_inputs = load_doc_context(repo_root, doc_id, step4_set, patch_set, step4_cfg, s4)
            doc_contexts[doc_id] = doc_ctx
            input_paths.extend(doc_inputs)
            logger.info(f"Loaded doc context: {doc_id} rows={len(doc_ctx.index_rows)} patches={len(doc_ctx.patch_docs)}")
        timings["load_seconds"] = round(time.perf_counter() - load_started, 3)

        write_json(audit_dir / "input_manifest.json", build_input_manifest(input_paths))

        queries_by_kc: Dict[str, List[str]] = {}
        all_queries: List[str] = []
        for row in registry_rows:
            queries = build_queries(row, cfg, s4)
            queries_by_kc[str(row["kc_id"])] = queries
            all_queries.extend(queries)
        unique_queries = sorted(set(all_queries))
        logger.info(f"Prepared KC queries: kcs={len(registry_rows)} unique_queries={len(unique_queries)}")

        embed_started = time.perf_counter()
        embedding_cfg = step4_cfg["embedding"]
        query_embed_batch_size = int(runtime_cfg.get("query_embed_batch_size", 32))
        query_vectors: Dict[str, np.ndarray] = {}
        for start_idx in range(0, len(unique_queries), query_embed_batch_size):
            batch = unique_queries[start_idx : start_idx + query_embed_batch_size]
            truncated_batch = [s4.pretruncate(query, int(embedding_cfg["max_chars"])) for query in batch]
            embeddings = s4.ollama_embed(
                base_url=str(embedding_cfg["base_url"]),
                model=str(embedding_cfg["model"]),
                inputs=truncated_batch,
                truncate=bool(embedding_cfg["truncate"]),
                dimensions=int(embedding_cfg["dimensions"]),
                keep_alive=str(embedding_cfg["keep_alive"]),
                options=dict(embedding_cfg.get("options", {})),
                timeout_s=240.0,
            )
            arr = np.asarray(embeddings, dtype=np.float32)
            if arr.shape != (len(batch), EXPECTED_EMBED_DIM):
                raise RuntimeError(f"Unexpected query embedding batch shape: {arr.shape}")
            if bool(step4_cfg["vector_index"].get("l2_normalize", True)):
                arr = s4.l2_normalize(arr)
            for query, vector in zip(batch, arr):
                query_vectors[query] = vector
        timings["query_embedding_seconds"] = round(time.perf_counter() - embed_started, 3)

        retrieval_started = time.perf_counter()
        candidates_rows: List[Dict[str, Any]] = []
        review_rows: List[Dict[str, Any]] = []
        per_doc_contrib: Counter[str] = Counter()
        empty_snippet_candidates = 0
        min_review_blocks = int(runtime_cfg.get("review_queue_min_unique_blocks", 2))
        diversity_tolerance = float(runtime_cfg.get("diversity_score_tolerance", 0.05))

        for row in registry_rows:
            kc_id = str(row["kc_id"])
            kc_title = str(row.get("canonical_name") or "")
            seed_definition = str(row.get("seed_definition") or "")
            queries = queries_by_kc[kc_id]
            raw_candidates: List[Dict[str, Any]] = []
            best_patch_headings: Dict[str, float] = {}

            for query_ordinal, query in enumerate(queries):
                query_vector = query_vectors[query]
                for doc_id in docs_sorted:
                    doc_ctx = doc_contexts[doc_id]
                    nav = navigate_rank(doc_ctx, query, int(per_kc_cfg["top_patches_per_doc"]), s4)
                    for patch_id, nav_score in nav:
                        heading = doc_ctx.patch_heading_map.get(patch_id, "")
                        if heading:
                            current = best_patch_headings.get(heading)
                            if current is None or float(nav_score) > current:
                                best_patch_headings[heading] = float(nav_score)
                    fetched = fetch_rank(
                        doc_ctx=doc_ctx,
                        query=query,
                        query_vector=query_vector,
                        selected_nav=nav,
                        top_blocks=int(per_kc_cfg["top_blocks_per_doc"]),
                        scoring_cfg=step4_cfg["scoring"],
                        s4=s4,
                    )
                    for candidate in fetched:
                        candidate["_query_ordinal"] = query_ordinal
                        raw_candidates.append(candidate)

            filtered_candidates = []
            for candidate in raw_candidates:
                if str(candidate.get("snippet") or "").strip():
                    filtered_candidates.append(candidate)
                else:
                    empty_snippet_candidates += 1

            deduped = dedupe_candidates(
                filtered_candidates,
                enable_reveal_fp_dedupe=bool(dedupe_cfg.get("dedupe_by_text_fingerprint_within_reveal_group", False)),
                s4=s4,
            )
            selected = apply_diversity(
                deduped,
                max_blocks=int(per_kc_cfg["max_blocks_per_kc"]),
                score_tolerance=diversity_tolerance,
            )
            selected_public = [strip_internal_fields(candidate) for candidate in selected]

            for evidence in selected_public:
                per_doc_contrib[str(evidence["doc_id"])] += 1

            if len(selected_public) == 0:
                review_rows.append(
                    {
                        "kc_id": kc_id,
                        "reason": "no_evidence",
                        "queries_tried": queries,
                        "debug_hints": {
                            "best_patch_headings_seen": [
                                heading
                                for heading, _ in sorted(best_patch_headings.items(), key=lambda item: (-item[1], item[0]))[:5]
                            ]
                        },
                    }
                )
            elif len(selected_public) < min_review_blocks:
                review_rows.append(
                    {
                        "kc_id": kc_id,
                        "reason": f"low_evidence_lt_{min_review_blocks}",
                        "queries_tried": queries,
                        "debug_hints": {
                            "best_patch_headings_seen": [
                                heading
                                for heading, _ in sorted(best_patch_headings.items(), key=lambda item: (-item[1], item[0]))[:5]
                            ]
                        },
                    }
                )

            candidates_rows.append(
                {
                    "kc_id": kc_id,
                    "kc_title": kc_title,
                    "kc_label": kc_title,
                    "seed_definition": seed_definition,
                    "evidence": selected_public,
                }
            )

        timings["retrieval_seconds"] = round(time.perf_counter() - retrieval_started, 3)

        candidates_rows = sorted(candidates_rows, key=lambda row: str(row["kc_id"]))
        review_rows = sorted(review_rows, key=lambda row: (str(row["reason"]), str(row["kc_id"])))

        candidates_path = (processed_dir / "kc_evidence_candidates.jsonl").resolve()
        stats_path = (processed_dir / "kc_evidence_stats.json").resolve()
        review_path = (processed_dir / "review_queue.jsonl").resolve()

        write_jsonl(candidates_path, candidates_rows)
        write_jsonl(review_path, review_rows)

        evidence_counts = [len(row["evidence"]) for row in candidates_rows]
        n_kcs_total = len(candidates_rows)
        n_kcs_with_any_evidence = sum(1 for count in evidence_counts if count > 0)
        coverage_pct = (100.0 * n_kcs_with_any_evidence / n_kcs_total) if n_kcs_total else 0.0

        stats_payload = {
            "n_kcs_total": n_kcs_total,
            "n_kcs_with_any_evidence": n_kcs_with_any_evidence,
            "coverage_pct": coverage_pct,
            "distribution_evidence_blocks_per_kc": {
                "min": int(min(evidence_counts) if evidence_counts else 0),
                "median": float(np.median(evidence_counts)) if evidence_counts else 0.0,
                "p90": int(percentile_p90(evidence_counts)),
                "max": int(max(evidence_counts) if evidence_counts else 0),
            },
            "top_20_kcs_zero_evidence": [row["kc_id"] for row in candidates_rows if not row["evidence"]][:20],
            "per_doc_contribution_counts": dict(sorted(per_doc_contrib.items())),
            "empty_snippet_candidates_skipped": int(empty_snippet_candidates),
        }
        write_json(stats_path, stats_payload)

        sample_rows = select_sample_rows(candidates_rows, int(runtime_cfg.get("sample_kcs", 10)))
        sample_table: List[Dict[str, Any]] = []
        for row in sample_rows:
            top = row["evidence"][0] if row["evidence"] else None
            sample_table.append(
                {
                    "kc_id": row["kc_id"],
                    "n_evidence": len(row["evidence"]),
                    "top_doc_id": top["doc_id"] if top else "",
                    "top_page": top["page_index"] if top else "",
                    "top_layer": top["layer"] if top else "",
                    "top_snippet_nonempty": bool(top and str(top.get("snippet") or "").strip()),
                }
            )

        if any(row["evidence"] and not str(row["evidence"][0].get("snippet") or "").strip() for row in candidates_rows):
            raise RuntimeError("Validation failed: at least one top evidence snippet is empty.")
        if any(not evidence["snippet"] for row in candidates_rows for evidence in row["evidence"]):
            raise RuntimeError("Validation failed: empty snippet found in selected evidence.")

        set_payload = {
            "schema_version": "1.0",
            "kind": "step5_kc_evidence_set",
            "set_id": set_path.stem,
            "created_utc": now_utc_iso(),
            "run_id_step5": run_id_step5,
            "artifacts": {
                "kc_evidence_candidates_jsonl": rel_path(candidates_path, repo_root),
                "kc_evidence_stats_json": rel_path(stats_path, repo_root),
                "review_queue_jsonl": rel_path(review_path, repo_root),
            },
            "upstream": {
                "kc_registry_path": rel_path(kc_registry_path, repo_root),
                "step4_active_set_pointer": rel_path(step4_pointer_path, repo_root),
                "step4_active_set_target": rel_path(step4_set_path, repo_root),
                "step4_linked_patches_set_target": rel_path(patch_set_path, repo_root),
                "step4_retrieval_run_audit_dir": rel_path(step4_run_audit_dir, repo_root),
                "step4_retrieval_config_snapshot": rel_path(step4_cfg_path, repo_root),
            },
            "audit": {
                "run_dir": rel_path(audit_dir, repo_root),
                "input_manifest": rel_path((audit_dir / "input_manifest.json").resolve(), repo_root),
                "output_manifest": rel_path((audit_dir / "output_manifest.json").resolve(), repo_root),
                "summary": rel_path((audit_dir / "summary.json").resolve(), repo_root),
            },
        }
        write_json(set_path, set_payload)
        write_text(active_pointer_path, set_path.name + "\n")

        output_manifest = build_output_manifest(repo_root, processed_dir, set_path, active_pointer_path)
        write_json(audit_dir / "output_manifest.json", output_manifest)

        timings["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        timings["n_kcs_total"] = n_kcs_total
        timings["n_docs"] = len(docs_sorted)
        timings["n_unique_queries"] = len(unique_queries)
        write_json(audit_dir / "timings.json", timings)

        summary_payload = {
            "run_id_step5": run_id_step5,
            "status": "success",
            "created_utc": now_utc_iso(),
            "n_kcs_total": n_kcs_total,
            "n_kcs_with_any_evidence": n_kcs_with_any_evidence,
            "coverage_pct": coverage_pct,
            "median_evidence_blocks_per_kc": float(np.median(evidence_counts)) if evidence_counts else 0.0,
            "review_queue_count": len(review_rows),
            "sample_rows": sample_table,
            "set_manifest": rel_path(set_path, repo_root),
            "active_pointer": rel_path(active_pointer_path, repo_root),
            "patch_set_source": rel_path(patch_set_path, repo_root),
        }
        write_json(audit_dir / "summary.json", summary_payload)

        print(f"n_kcs_total={n_kcs_total}")
        print(f"n_kcs_with_any_evidence={n_kcs_with_any_evidence}")
        print(f"coverage_pct={coverage_pct:.2f}")
        print(f"median_evidence_blocks_per_kc={summary_payload['median_evidence_blocks_per_kc']:.2f}")
        print(f"review_queue_count={len(review_rows)}")
        print("kc_id | n_evidence | top_doc_id | top_page | top_layer | top_snippet_nonempty")
        for row in sample_table:
            print(
                f"{row['kc_id']} | {row['n_evidence']} | {row['top_doc_id']} | "
                f"{row['top_page']} | {row['top_layer']} | {row['top_snippet_nonempty']}"
            )
        logger.info(f"Wrote Step 5 evidence set: {rel_path(set_path, repo_root)}")
        logger.info(f"Updated ACTIVE pointer: {rel_path(active_pointer_path, repo_root)} -> {set_path.name}")
        return 0
    except Exception as exc:
        write_json(
            audit_dir / "summary.json",
            {
                "run_id_step5": run_id_step5,
                "status": "failed",
                "created_utc": now_utc_iso(),
                "error": repr(exc),
            },
        )
        write_json(
            audit_dir / "timings.json",
            {
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "status": "failed",
            },
        )
        logger.info(f"FAILED: {repr(exc)}")
        raise


if __name__ == "__main__":
    raise SystemExit(run())
