#!/usr/bin/env python3
"""Conventional RAG baseline packet builder (section 8 of the evaluation brief).

Tests: does the proposed multi-stage evidence-grounding pipeline materially improve KC
authoring over ordinary RAG when model, corpus, KC targets, and evidence budget are held
constant? (RQ2)

Design, and why each choice matches section 8's controls:

- Query = canonical_name + this unit's own hierarchy path labels ONLY (section 8, "Recommended
  baseline retrieval query"). No PRF expansion, no acronym expansion, no sibling/rival-aware
  query formulation - those live in src/kc_l/retrieval_gate/{retrieval,evidence_pack}.py's
  build_query()/expand_query_tokens()/candidate_query_texts() and are exactly the "model-generated
  retrieval guidance" section 8.2 says the baseline must not use.
- Retrieval = pure dense (DenseIndex.top_k), no BM25, no cross-encoder reranking. The brief's own
  conceptual baseline pipeline (section 8) lists "conventional dense retrieval" only, with no
  reranking stage - reranking is part of the proposed system's "extra retrieval/evidence
  engineering" this baseline exists to isolate (section 8.3), not something the baseline should
  borrow. Reuses src/kc_l/retrieval_gate/retrieval.py's DenseIndex class directly (the repo's own
  standard dense-retrieval primitive - section 8's explicit instruction to reuse rather than
  introduce a new library), same embedder (sentence-transformers/all-mpnet-base-v2), and even the
  SAME on-disk embedding cache the proposed system's own packet builder writes (identical cache-key
  derivation, confirmed by reading v3/pipeline/02_build_kc_packets.py directly) - bit-identical
  embeddings, not just "the same model name".
- Evidence budget = 14000 chars per unit of PROMPT-CONSUMED text (see the source_block_text note
  in retrieve_baseline_evidence: both fields reach the prompt, so both are bounded by this cap),
  taken in descending similarity order until the cap is
  hit. This is not an arbitrary new number: it is the EXACT --max-chars ceiling
  v3/pipeline/02_build_kc_packets.py already enforces for the proposed system (confirmed: the real
  data-mining packets' evidence chars/unit distribution tops out at 13997, one below this same
  cap). Same shared ceiling, both conditions - section 8.1 control #12.
- KC identity (IDs, canonical names, aliases, hierarchy, sibling_kc_names, rival_units_considered)
  is copied VERBATIM from the real, already-built proposed-system packets for this run - same
  intended KC set, same names, same hierarchy context (controls #1-3), with zero risk of drift
  from rebuilding it independently.
- Explicitly OMITTED from the baseline packet (confirmed present in a real packet, confirmed to be
  proposed-system-COMPUTED guidance, not raw identity): drafting_instruction, query_formulation,
  evidence_coverage, evidence_dropped_to_rival_units, packet_support_state, support_state_reason,
  insufficient_support_reasons. Each of these is the proposed pipeline's own generated analysis of
  the evidence it selected - including any of them would leak the proposed system's engineering
  into the condition meant to be free of it (section 8.2). abstention_expected and
  insufficient_synthesis_support are explicitly set to False (not omitted, since build_prompt()
  checks them by name) - the baseline drafter gets no pre-computed sufficiency signal either way
  and must judge abstention purely from the retrieved text, exactly like the proposed condition's
  own drafter does from ITS evidence.
- evidence_for_synthesis items carry no shape_tags/role classification - a plain retrieved
  passage, not a proposed-system-classified one. The drafter can still notice a formula or
  procedure by reading the text (build_prompt()'s instructions ask for that regardless of tags);
  it simply does not get the proposed system's extra shape-aware completeness nudge. That
  asymmetry is real and intended - it is exactly what "isolate the extra evidence engineering" is
  supposed to expose (section 8.3), not something to erase for parity.
- Output packets pass through v3/pipeline/04_draft_runner.py's build_prompt()/ollama_generate()
  completely UNCHANGED (same checkpoint, quantization, system prompt, max tokens, decoding
  params/seed, output JSON schema, abstention permission - controls #7-14) by construction: the
  output of this script is a real v3/jobs/02_draft_kc_gemma4.sbatch-shaped kc_packets.jsonl, run
  through the IDENTICAL, unmodified drafting sbatch script used for the proposed condition, just
  pointed at a different RUN directory. Same code path end to end past the evidence-selection
  boundary - the only intentional difference between conditions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.retrieval_gate.retrieval import DenseIndex, DEFAULT_EMBEDDER  # noqa: E402

MAX_CHARS_BUDGET = 14000  # same ceiling v3/pipeline/02_build_kc_packets.py enforces for the
                          # proposed system - not a new number, reused deliberately (see module
                          # docstring)
DENSE_TOPK = 200  # generous over-fetch; the char budget is what actually bounds what's kept


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def hierarchy_query_text(packet: dict) -> str:
    """canonical_name + this unit's own hierarchy path labels - nothing else. No PRF, no
    acronym expansion, no sibling/rival awareness."""
    name = str(packet.get("canonical_name") or "").strip()
    hierarchy = packet.get("hierarchy") or {}
    path_labels = hierarchy.get("source_hierarchy_path") or hierarchy.get("topic_path") or []
    path_text = " ".join(str(p) for p in path_labels if p)
    return f"{name} {path_text}".strip()


def dense_cache_path(corpus_jsonl: pathlib.Path, corpus_rows: list[dict], real_packets_jsonl: pathlib.Path) -> str:
    """Identical derivation to v3/pipeline/02_build_kc_packets.py's own cache-key logic, so an
    identical corpus file produces an identical key and this script gets a real cache HIT against
    the proposed system's own already-computed embeddings, not a fresh (and much slower) re-embed.

    Points at the cache directory ALONGSIDE the real proposed-system packets this run is copying
    KC identity from (real_packets_jsonl.parent.parent / "_dense_cache") - that is where the
    proposed system's own DenseIndex call already wrote it, confirmed by inspecting
    data/v3/runs/v3_20260812/_dense_cache/ directly. NOT derived from this script's own --out-jsonl
    location: an earlier version did that, which put the baseline's own (necessarily different,
    non-destructive-convention) run directory in the key derivation and caused a real, confirmed
    27-minute cache MISS on the first real run of this script - fixed here, not still using that
    derivation.
    """
    st = corpus_jsonl.stat()
    key = hashlib.sha1(
        ("%s|%d|%d|%d" % (str(corpus_jsonl), st.st_size, int(st.st_mtime), len(corpus_rows))).encode("utf-8")
    ).hexdigest()[:16]
    return str(real_packets_jsonl.parent.parent / "_dense_cache" / f"emb_{key}.npz")


def retrieve_baseline_evidence(
    kc_id: str, query_text: str, dense: DenseIndex, corpus: list[dict], max_chars: int,
) -> list[dict]:
    if not query_text:
        return []
    hits = dense.top_k(query_text, DENSE_TOPK)
    evidence: list[dict] = []
    used_chars = 0
    seen_text: set[str] = set()  # exact-duplicate skip only - basic RAG hygiene (the corpus has
    # real duplicate/near-duplicate sentences, e.g. repeated chapter-intro lines), not a quality
    # judgment. Confirmed necessary by direct smoke-test inspection: without this, the top-4
    # dense hits for two different real KCs were literally the same sentence retrieved twice
    # each, silently halving the usable evidence budget. This is NOT the same as filtering out
    # low-quality-but-distinct text (e.g. a citation/bibliography fragment) - those are kept,
    # since a real "ordinary RAG" baseline is expected to be noisier than the proposed system's
    # filtered evidence, and section 8.2 explicitly forbids giving the baseline any
    # relevance/quality classification the proposed system itself uses.
    for rank, (idx, score) in enumerate(hits):
        row = corpus[idx]
        text = str(row.get("sentence_text") or "").strip()
        if not text or text in seen_text:
            continue
        if used_chars + len(text) > max_chars and evidence:
            break  # budget cap - stop adding once the shared ceiling would be exceeded
        seen_text.add(text)
        evidence.append({
            "evidence_id": f"{kc_id}:baseline_rag:{rank:04d}",
            "text": text,
            # Mirrors `text` deliberately. 04_draft_runner.py's _PROMPT_TEXT_FIELDS puts BOTH
            # "text" and "source_block_text" into the drafting prompt, so writing the full
            # containing block here would put an unbudgeted payload into the prompt while the
            # max-chars control below counted only `text` - which is exactly what happened on the
            # first two baseline runs (jobs 245933, 246018): a median 38,322 chars of block text
            # per unit against a 14,000-char budget, driving the median prompt to 29,028 tokens
            # (gemma4: 32,691) of a 32,768 context and truncating 42/159 qwen3.8 units mid-JSON
            # with done_reason=length. The proposed system's own packets have text ==
            # source_block_text (its `text` is already the expanded block), so mirroring is what
            # makes the shared evidence budget genuinely shared and the two conditions
            # structurally comparable. This grants the baseline no proposed-system machinery: it
            # still gets no reranking, no relevance classification, and no sentence-to-block
            # expansion.
            "source_block_text": text,
            "doc_id": row.get("doc_id"),
            "page_index": row.get("page_index"),
            "patch_heading": row.get("patch_heading") or "",
            "sentence_id": row.get("sentence_id"),
            "evidence_lane": "baseline_dense_retrieval",
            "retrieval_score": round(float(score), 6),
        })
        used_chars += len(text)
        if used_chars >= max_chars:
            break
    return evidence


def build_baseline_packet(real_packet: dict, evidence: list[dict]) -> dict:
    """Copies only real KC identity fields from the proposed system's own packet - never its
    computed evidence, guidance, or support-state judgments. See module docstring for the exact
    field-inclusion rationale."""
    return {
        "knowledge_unit_id": real_packet.get("knowledge_unit_id"),
        "kc_id": real_packet.get("kc_id"),
        "knowledge_unit_type": real_packet.get("knowledge_unit_type"),
        "canonical_name": real_packet.get("canonical_name"),
        "aliases": real_packet.get("aliases") or [],
        "hierarchy": real_packet.get("hierarchy") or {},
        "sibling_kc_names": real_packet.get("sibling_kc_names") or [],
        "rival_units_considered": real_packet.get("rival_units_considered") or [],
        "packet_version": "sentence_level_base_dense_rag_v1",
        "evidence_for_synthesis": evidence,
        # Explicitly neutral, not omitted - build_prompt() checks these two by name. No
        # pre-computed sufficiency signal in either direction; the drafter judges purely from the
        # retrieved text, same as the proposed condition judges from its own evidence.
        "abstention_expected": False,
        "insufficient_synthesis_support": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--real-packets-jsonl", required=True, type=pathlib.Path,
                     help="proposed-system kc_packets.jsonl to copy KC identity fields from")
    ap.add_argument("--corpus-jsonl", required=True, type=pathlib.Path,
                     help="same immutable sentence corpus the proposed system's packets were built from")
    ap.add_argument("--out-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--stats-json", required=True, type=pathlib.Path)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS_BUDGET)
    ap.add_argument("--dense-cache-path", type=str, default=None,
                     help="explicit override for the embedding cache file - use this when "
                          "--real-packets-jsonl doesn't live next to the proposed system's own "
                          "_dense_cache/ directory (e.g. a copy, a differently-organized rebuild). "
                          "Auto-derivation from --real-packets-jsonl's own location is only a "
                          "convenience default, not guaranteed correct - verify the target file "
                          "actually exists before relying on it for a real (non-smoke-test) run.")
    args = ap.parse_args()

    real_packets = load_jsonl(args.real_packets_jsonl)
    print(f"real proposed-system packets: {len(real_packets)}", flush=True)

    corpus = load_jsonl(args.corpus_jsonl)
    print(f"corpus rows: {len(corpus)}", flush=True)

    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if args.dense_cache_path:
        cache_path = args.dense_cache_path
        print(f"using explicit --dense-cache-path override: {cache_path} "
              f"(exists={pathlib.Path(cache_path).exists()})", flush=True)
    else:
        cache_path = dense_cache_path(args.corpus_jsonl, corpus, args.real_packets_jsonl)
        print(f"auto-derived cache path: {cache_path} (exists={pathlib.Path(cache_path).exists()})",
              flush=True)
    t0 = time.time()
    dense = DenseIndex([r.get("sentence_text") or "" for r in corpus], cache_path=cache_path)
    print(f"dense_index available={dense.available} device={getattr(dense, 'device', '-')} "
          f"cache={getattr(dense, 'cache_status', '-')} ({time.time() - t0:.0f}s)", flush=True)
    if not dense.available:
        print("ABORT: dense index unavailable", file=sys.stderr)
        return 3

    baseline_packets = []
    empty_query = 0
    empty_evidence = 0
    evidence_chars = []
    evidence_counts = []
    for i, packet in enumerate(real_packets):
        kc_id = packet.get("knowledge_unit_id") or packet.get("kc_id")
        query_text = hierarchy_query_text(packet)
        if not query_text:
            empty_query += 1
        evidence = retrieve_baseline_evidence(kc_id, query_text, dense, corpus, args.max_chars)
        if not evidence:
            empty_evidence += 1
        chars = sum(len(e["text"]) for e in evidence)
        evidence_chars.append(chars)
        evidence_counts.append(len(evidence))
        baseline_packets.append(build_baseline_packet(packet, evidence))
        if (i + 1) % 40 == 0:
            print(f"  {i + 1}/{len(real_packets)} units", flush=True)

    with args.out_jsonl.open("w", encoding="utf-8") as f:
        for p in baseline_packets:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    stats = {
        "n_units": len(baseline_packets),
        "empty_query_count": empty_query,
        "empty_evidence_count": empty_evidence,
        "mean_evidence_chars": round(sum(evidence_chars) / len(evidence_chars), 1) if evidence_chars else None,
        "median_evidence_chars": sorted(evidence_chars)[len(evidence_chars) // 2] if evidence_chars else None,
        "max_evidence_chars": max(evidence_chars) if evidence_chars else None,
        "mean_evidence_item_count": round(sum(evidence_counts) / len(evidence_counts), 1) if evidence_counts else None,
        "max_chars_budget": args.max_chars,
        "embedder": DEFAULT_EMBEDDER,
        "dense_cache_path": cache_path,
        "corpus_jsonl": str(args.corpus_jsonl),
        "real_packets_jsonl": str(args.real_packets_jsonl),
    }
    args.stats_json.parent.mkdir(parents=True, exist_ok=True)
    args.stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))
    print(f"baseline packets -> {args.out_jsonl}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
