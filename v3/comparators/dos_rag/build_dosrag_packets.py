#!/usr/bin/env python3
"""DOS-RAG comparator packet builder. Mirrors v3/pipeline/build_baseline_rag_packets.py's exact
packet-shape contract (same field-inclusion rationale: real KC identity copied verbatim from the
proposed system's own real packets; every proposed-system-COMPUTED field - drafting_instruction,
query_formulation, evidence_coverage, evidence_dropped_to_rival_units, packet_support_state,
support_state_reason, insufficient_support_reasons, weak_fallback_abstention_allowed - omitted;
abstention_expected/insufficient_synthesis_support explicitly False, not omitted, since
build_prompt() checks them by name).

Retrieval itself is entirely DOS-RAG's own, unmodified code (dosrag_retrieve.py, vendor/). This
script's only job is mapping that retrieval output into the shared packet shape
04_draft_runner.py already knows how to consume.

DOS-RAG evidence items are structurally poorer than the proposed system's, by design, per the
feasibility audit's explicit instruction: no shape_tags, no assertability, no authority_tier, no
relevance score (RAG.retrieve() does not return one), no role/roles. What IS included and is
genuinely DOS-RAG's own native output: the chunk's pre-reorder similarity rank
(dos_rag_pre_reorder_rank) and its source-position index in the combined corpus
(dos_rag_chunk_index) - both directly read off RAG.retrieve()'s real return values, not
recomputed or invented.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dosrag_retrieve import DosRagCorpusIndex, dosrag_query_text  # noqa: E402


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_dosrag_packet(real_packet: dict, evidence: list[dict]) -> dict:
    """Same field set as build_baseline_rag_packets.py:build_baseline_packet(), only
    packet_version differs - real KC identity only, never proposed-system-computed guidance."""
    return {
        "knowledge_unit_id": real_packet.get("knowledge_unit_id"),
        "kc_id": real_packet.get("kc_id"),
        "knowledge_unit_type": real_packet.get("knowledge_unit_type"),
        "canonical_name": real_packet.get("canonical_name"),
        "aliases": real_packet.get("aliases") or [],
        "hierarchy": real_packet.get("hierarchy") or {},
        "sibling_kc_names": real_packet.get("sibling_kc_names") or [],
        "rival_units_considered": real_packet.get("rival_units_considered") or [],
        "packet_version": "dos_rag_v1",
        "evidence_for_synthesis": evidence,
        "abstention_expected": False,
        "insufficient_synthesis_support": False,
    }


def evidence_items_from_result(kc_id: str, result) -> list[dict]:
    items = []
    for rank_pos, node_idx in enumerate(result.final_order_node_indices):
        prov = next(p for p in result.chunk_provenance if p["chunk_index"] == node_idx)
        # Recover this node's own text from the combined context is unreliable once multiple
        # chunks are joined; re-read it directly off the index instead (single source of truth).
        items.append({
            "evidence_id": f"{kc_id}:dos_rag:{rank_pos:04d}",
            "text": prov["_chunk_text"],
            "source_block_text": prov["_chunk_text"],
            "doc_id": prov.get("doc_id"),
            "page_index": prov.get("page_index_min"),
            "page_index_max": prov.get("page_index_max"),
            "patch_heading": "",
            "source_sentence_ids": prov.get("sentence_ids") or [],
            "provenance_status": prov.get("provenance", "unresolved"),
            "evidence_lane": "dos_rag_native_retrieval",
            "dos_rag_chunk_index": node_idx,
            "dos_rag_pre_reorder_rank": result.pre_reorder_node_indices.index(node_idx),
        })
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--real-packets-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--corpus-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--embedding-model-dir", required=True, type=pathlib.Path,
                     help="local directory holding the Snowflake Arctic sentence-transformers files")
    ap.add_argument("--out-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--stats-json", required=True, type=pathlib.Path)
    ap.add_argument("--index-cache", type=pathlib.Path, default=None,
                     help="pickle path to cache the built DOS-RAG node index across runs")
    ap.add_argument("--chunk-size", type=int, default=100)
    ap.add_argument("--top-k", type=int, default=200, help="DOS-RAG's own over-fetch parameter")
    ap.add_argument("--max-tokens", type=int, default=3500,
                     help="DOS-RAG's own token budget (tiktoken cl100k_base); see "
                          "08_TOKEN_BUDGET_ANALYSIS.md for calibration to the shared char ceiling")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N units (smoke use)")
    args = ap.parse_args()

    real_packets = load_jsonl(args.real_packets_jsonl)
    if args.limit:
        real_packets = real_packets[: args.limit]
    print(f"real proposed-system packets to process: {len(real_packets)}", flush=True)

    t0 = time.time()
    index = DosRagCorpusIndex(
        corpus_jsonl_path=str(args.corpus_jsonl),
        embedding_model_dir=str(args.embedding_model_dir),
        chunk_size=args.chunk_size,
        cache_path=str(args.index_cache) if args.index_cache else None,
    )
    print(f"DOS-RAG index built: {index.n_chunks} chunks ({time.time() - t0:.0f}s)", flush=True)

    out_packets = []
    per_unit_stats = []
    for i, packet in enumerate(real_packets):
        kc_id = packet.get("knowledge_unit_id") or packet.get("kc_id")
        name = str(packet.get("canonical_name") or "")
        hierarchy = packet.get("hierarchy") or {}
        path_labels = hierarchy.get("source_hierarchy_path") or hierarchy.get("topic_path") or []
        query = dosrag_query_text(name, [str(p) for p in path_labels if p])

        result = index.retrieve(query=query, top_k=args.top_k, max_tokens=args.max_tokens)
        # attach raw chunk text into provenance dicts for evidence_items_from_result to read
        for p in result.chunk_provenance:
            p["_chunk_text"] = index.rag.nodes[p["chunk_index"]].text

        evidence = evidence_items_from_result(kc_id, result)
        out_packets.append(build_dosrag_packet(packet, evidence))
        per_unit_stats.append({
            "knowledge_unit_id": kc_id, "query": query,
            "selected_chunk_count": result.selected_chunk_count,
            "selected_source_chars": result.selected_source_chars,
            "estimated_source_tokens": result.estimated_source_tokens,
            "pre_reorder_node_indices": result.pre_reorder_node_indices,
            "final_order_node_indices": result.final_order_node_indices,
        })
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(real_packets)} units", flush=True)

    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.out_jsonl.open("w", encoding="utf-8") as f:
        for p in out_packets:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    args.stats_json.parent.mkdir(parents=True, exist_ok=True)
    stats = {
        "n_units": len(out_packets),
        "n_corpus_chunks": index.n_chunks,
        "chunk_size": args.chunk_size,
        "top_k": args.top_k,
        "max_tokens": args.max_tokens,
        "per_unit": per_unit_stats,
    }
    args.stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"dos-rag packets -> {args.out_jsonl}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
