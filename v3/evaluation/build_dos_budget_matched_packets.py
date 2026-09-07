#!/usr/bin/env python3
"""Build DOS-RAG packets restricted to Proposed's per-KC evidence-token budget.

This is evaluation scaffolding only. It never changes Proposed/R8 retrieval and never changes the
vendored DOS-RAG chunking, ranking, or source-order restoration. The matched condition is built as
a strict ranked-prefix subset of the frozen DOS full-budget selected chunks for the same KC.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import pathlib
import pickle
import statistics
import sys
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

THIS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
DOS_DIR = REPO_ROOT / "v3" / "comparators" / "dos_rag"
if str(DOS_DIR) not in sys.path:
    sys.path.insert(0, str(DOS_DIR))

from corpus_text import combine_documents, load_documents, locate_chunk_provenance  # noqa: E402


def build_dosrag_packet(real_packet: Mapping[str, Any], evidence: list[dict]) -> dict:
    """Local copy of the DOS packet-shape adapter, without importing live DOS retrieval code."""
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


class FrozenDosNode:
    def __init__(self, text: str = "", index: int = 0, embedding: Any = None) -> None:
        self.text = text
        self.index = index
        self.embedding = embedding


class FrozenDosNodeUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if module == "source.method.RAG" and name == "Node":
            return FrozenDosNode
        return super().find_class(module, name)


class FrozenDosIndex:
    """Frozen DOS-RAG node cache plus provenance spans, without live retrieval.

    The budget-matched condition is a subset of already-selected frozen DOS chunks. It does not
    run new query embeddings, ranking, or retrieval, so instantiating the Snowflake embedder would
    add an unnecessary environment dependency and a misleading moving part.
    """

    def __init__(self, corpus_jsonl_path: pathlib.Path, index_cache: pathlib.Path):
        joined, spans = load_documents(str(corpus_jsonl_path))
        self.combined_text, self.combined_spans = combine_documents(joined, spans)
        with index_cache.open("rb") as f:
            nodes = FrozenDosNodeUnpickler(f).load()
        if not isinstance(nodes, dict):
            raise TypeError(f"DOS index cache did not contain a node dictionary: {index_cache}")
        bad = [k for k, v in nodes.items() if not hasattr(v, "text") or not hasattr(v, "index")]
        if bad:
            raise TypeError(f"DOS index cache has non-node-like entries, first bad keys: {bad[:5]}")
        self.rag = SimpleNamespace(nodes=nodes)
        self.n_chunks = len(nodes)


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: pathlib.Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("knowledge_unit_id") or row.get("kc_id") or row.get("topic_id") or "")


def canonical_name(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get("canonical_name") or "").split())


def import_file(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def load_draft_modules(repo_root: pathlib.Path):
    draft_runner = import_file(repo_root / "v3" / "pipeline" / "04_draft_runner.py", "r9_draft_runner")
    schema_runner = import_file(
        repo_root / "steps" / "step_06_7_kc_draft_generation" / "scripts" / "v2_chain"
        / "run_step67_v2_schema_contract_probe.py",
        "r9_schema_runner",
    )
    return draft_runner, schema_runner


class TokenCounter:
    label = "abstract"

    def count(self, text: str) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def metadata(self) -> dict:
        return {"label": self.label}


class TiktokenCounter(TokenCounter):
    def __init__(self, encoding_name: str = "cl100k_base"):
        import tiktoken

        self.encoding_name = encoding_name
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.label = f"tiktoken:{encoding_name}"

    def count(self, text: str) -> int:
        return len(self.encoding.encode(str(text or "")))

    def metadata(self) -> dict:
        return {
            "label": self.label,
            "implementation": "tiktoken",
            "encoding": self.encoding_name,
            "special_token_handling": "ordinary encode(); no chat wrapper; special tokens disallowed by default",
            "exact_for_qwen38_27b": False,
        }


class OllamaTokenCounter(TokenCounter):
    def __init__(
        self,
        host: str,
        model: str,
        timeout_s: int = 120,
        allow_generate_fallback: bool = False,
    ):
        self.host = host
        self.model = model
        self.timeout_s = timeout_s
        self.allow_generate_fallback = allow_generate_fallback
        self.cache: dict[str, int] = {}
        self.mode = self._detect_mode()
        self.label = f"ollama:{model}:{self.mode}"

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict:
        data = json.dumps(dict(payload)).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.host}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def _tokenize_count(self, text: str) -> int:
        # Ollama API versions have used both "prompt" and "content" in experimental tokenize
        # endpoints. Try the normal prompt form first; reject unknown shapes loudly.
        obj = self._post("/api/tokenize", {"model": self.model, "prompt": text})
        if isinstance(obj.get("tokens"), list):
            return len(obj["tokens"])
        if isinstance(obj.get("count"), int):
            return int(obj["count"])
        raise RuntimeError(f"unrecognized /api/tokenize response keys: {sorted(obj)}")

    def _generate_prompt_eval_count(self, text: str) -> int:
        obj = self._post(
            "/api/generate",
            {
                "model": self.model,
                "prompt": text,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0,
                    "top_p": 1.0,
                    "num_predict": 1,
                },
            },
        )
        count = obj.get("prompt_eval_count")
        if not isinstance(count, int):
            raise RuntimeError(f"generate response had no integer prompt_eval_count: {sorted(obj)}")
        return int(count)

    def _detect_mode(self) -> str:
        probe = "tokenizer probe"
        try:
            counted = self._tokenize_count(probe)
            if counted >= 1:
                return "api_tokenize"
        except urllib.error.HTTPError as exc:
            tokenize_error = f"HTTP {exc.code}"
        except Exception as exc:  # endpoint may not exist on older Ollama
            tokenize_error = f"{exc.__class__.__name__}: {exc}"
        if not self.allow_generate_fallback:
            raise RuntimeError(
                "/api/tokenize is not available for exact fast token counting "
                f"({tokenize_error}); refusing to fall back to generation-count mode without "
                "--allow-ollama-generate-token-count"
            )
        counted = self._generate_prompt_eval_count(probe)
        if counted < 1:
            raise RuntimeError("Ollama prompt_eval_count probe returned an impossible count")
        return "generate_prompt_eval_count"

    def count(self, text: str) -> int:
        text = str(text or "")
        if text == "":
            return 0
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.mode == "api_tokenize":
            value = self._tokenize_count(text)
        else:
            value = self._generate_prompt_eval_count(text)
        self.cache[key] = int(value)
        return int(value)

    def metadata(self) -> dict:
        return {
            "label": self.label,
            "implementation": "Ollama HTTP API",
            "host": self.host,
            "model": self.model,
            "mode": self.mode,
            "special_token_handling": "plain prompt string sent to Ollama model tokenizer; no chat wrapper",
            "exact_for_qwen38_27b": True,
            "allow_generate_fallback": self.allow_generate_fallback,
        }


def evidence_raw_text(evidence: list[Mapping[str, Any]]) -> str:
    return "\n\n".join(str(e.get("text") or e.get("source_block_text") or "") for e in evidence)


def visible_evidence(packet: Mapping[str, Any], draft_runner: Any, prompt_mode: str) -> list[dict]:
    visible = draft_runner.visible_packet_for_prompt(packet, prompt_mode)
    evidence = visible.get("evidence_for_synthesis") or []
    return [dict(e) for e in evidence if isinstance(e, Mapping)]


def serialized_visible_evidence_tokens(
    packet: Mapping[str, Any],
    counter: TokenCounter,
    draft_runner: Any,
    prompt_mode: str,
) -> int:
    return counter.count(compact_json(visible_evidence(packet, draft_runner, prompt_mode)))


def evidence_metrics(
    packet: Mapping[str, Any],
    counter: TokenCounter,
    draft_runner: Any,
    schema_runner: Any,
    prompt_mode: str,
) -> dict:
    evidence = visible_evidence(packet, draft_runner, prompt_mode)
    raw = evidence_raw_text(evidence)
    serialized = compact_json(evidence)
    prompt = schema_runner.make_prompt(
        draft_runner,
        packet,
        schema_runner.output_schema(packet),
        mode=prompt_mode,
    )
    return {
        "evidence_items": len(evidence),
        "raw_chars": len(raw),
        "serialized_chars": len(serialized),
        "raw_tokens": counter.count(raw),
        "serialized_tokens": counter.count(serialized),
        "complete_prompt_chars": len(prompt),
        "complete_prompt_tokens": counter.count(prompt),
    }


def normalized_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())


def evidence_items_from_selected(
    kc_id: str,
    selected_ranked: list[tuple[int, int]],
    index: Any,
) -> list[dict]:
    # selected_ranked is [(pre_reorder_rank, node_index)] in similarity-rank order. DOS restores
    # selected chunks to original source order before prompting.
    final_ids = [node_idx for _rank, node_idx in sorted(selected_ranked, key=lambda x: x[1])]
    rank_by_node = {node_idx: rank for rank, node_idx in selected_ranked}
    items: list[dict] = []
    for rank_pos, node_idx in enumerate(final_ids):
        node = index.rag.nodes[node_idx]
        prov = locate_chunk_provenance(node.text, index.combined_spans)
        items.append({
            "evidence_id": f"{kc_id}:dos_rag_matched:{rank_pos:04d}",
            "text": node.text,
            "source_block_text": node.text,
            "doc_id": prov.get("doc_id"),
            "page_index": prov.get("page_index_min"),
            "page_index_max": prov.get("page_index_max"),
            "patch_heading": "",
            "source_sentence_ids": prov.get("sentence_ids") or [],
            "provenance_status": prov.get("provenance", "unresolved"),
            "evidence_lane": "dos_rag_native_retrieval",
            "dos_rag_chunk_index": node_idx,
            "dos_rag_pre_reorder_rank": rank_by_node[node_idx],
        })
    return items


def lost_content_flags(texts: list[str]) -> dict:
    joined = "\n".join(texts)
    formula_re = any(ch in joined for ch in "=∑Σ∫√≤≥±≈≠→") or "$" in joined or "\\" in joined
    proc_re = any(word in joined.lower() for word in (
        "step", "algorithm", "procedure", "first", "second", "then", "repeat", "initialize",
        "compute", "for each", "until",
    ))
    definition_re = any(word in joined.lower() for word in (
        " is defined as ", " are defined as ", " is called ", " are called ",
        " refers to ", " is a ", " are a ", " consists of ",
    ))
    return {
        "whether_defining_formula_was_lost": bool(formula_re),
        "whether_procedure_block_was_lost": bool(proc_re),
        "whether_definition_passage_was_lost": bool(definition_re),
    }


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * pct
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return float(ordered[lo] * (1 - frac) + ordered[hi] * frac)


def stats(values: list[float]) -> dict:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {k: None for k in ("mean", "median", "p10", "p25", "p75", "p90", "minimum", "maximum")}
    return {
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "p10": percentile(clean, 0.10),
        "p25": percentile(clean, 0.25),
        "p75": percentile(clean, 0.75),
        "p90": percentile(clean, 0.90),
        "minimum": min(clean),
        "maximum": max(clean),
    }


def make_counter(args: argparse.Namespace) -> TokenCounter:
    if args.tokenizer == "ollama":
        return OllamaTokenCounter(
            host=args.ollama_host,
            model=args.ollama_model,
            timeout_s=args.ollama_timeout_s,
            allow_generate_fallback=args.allow_ollama_generate_token_count,
        )
    if args.tokenizer == "tiktoken-cl100k":
        return TiktokenCounter("cl100k_base")
    raise ValueError(args.tokenizer)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proposed-packets-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--dos-full-packets-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--corpus-jsonl", required=True, type=pathlib.Path)
    ap.add_argument(
        "--embedding-model-dir",
        type=pathlib.Path,
        default=None,
        help="Accepted for compatibility with normal DOS-RAG jobs; unused for frozen-cache matching.",
    )
    ap.add_argument("--index-cache", required=True, type=pathlib.Path)
    ap.add_argument("--out-root", required=True, type=pathlib.Path)
    ap.add_argument("--matched-run-dir", required=True, type=pathlib.Path)
    ap.add_argument("--chunk-size", type=int, default=100)
    ap.add_argument("--top-k", type=int, default=200)
    ap.add_argument("--prompt-mode", default="controlled_comparator",
                    choices=("native_proposed", "controlled_comparator"))
    ap.add_argument("--tokenizer", default="ollama", choices=("ollama", "tiktoken-cl100k"))
    ap.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
    ap.add_argument("--ollama-model", default="qwen3.8:27b")
    ap.add_argument("--ollama-timeout-s", type=int, default=120)
    ap.add_argument("--allow-ollama-generate-token-count", action="store_true")
    ap.add_argument("--max-mean-underfill-pct", type=float, default=35.0)
    args = ap.parse_args()

    start = time.time()
    args.out_root.mkdir(parents=True, exist_ok=False)
    (args.out_root / "dos_matched_packets").mkdir(parents=True, exist_ok=True)
    (args.matched_run_dir / "packets").mkdir(parents=True, exist_ok=False)

    draft_runner, schema_runner = load_draft_modules(REPO_ROOT)
    counter = make_counter(args)

    proposed_packets = load_jsonl(args.proposed_packets_jsonl)
    dos_full_packets = load_jsonl(args.dos_full_packets_jsonl)
    proposed_by_id = {unit_id(p): p for p in proposed_packets}
    dos_by_id = {unit_id(p): p for p in dos_full_packets}
    ids = [unit_id(p) for p in proposed_packets]
    missing = [kc_id for kc_id in ids if kc_id not in dos_by_id]
    if missing:
        raise SystemExit(f"DOS full packets missing {len(missing)} proposed ids: {missing[:5]}")

    index = FrozenDosIndex(args.corpus_jsonl, args.index_cache)

    matched_packets: list[dict] = []
    budget_rows: list[dict] = []
    full_vs_matched_rows: list[dict] = []
    integrity: dict[str, Any] = {
        "frozen_full_chunk_text_mismatches": [],
        "matched_non_subset_violations": [],
        "selected_prefix_violations": [],
    }

    for ordinal, kc_id in enumerate(ids, 1):
        proposed = proposed_by_id[kc_id]
        dos_full = dos_by_id[kc_id]

        proposed_m = evidence_metrics(proposed, counter, draft_runner, schema_runner, args.prompt_mode)
        dos_full_m = evidence_metrics(dos_full, counter, draft_runner, schema_runner, args.prompt_mode)
        target = int(proposed_m["serialized_tokens"])

        full_evidence = [dict(e) for e in (dos_full.get("evidence_for_synthesis") or [])
                         if isinstance(e, Mapping)]
        full_ranked: list[tuple[int, int]] = []
        for ev in full_evidence:
            if "dos_rag_chunk_index" not in ev:
                continue
            node_idx = int(ev["dos_rag_chunk_index"])
            rank = int(ev.get("dos_rag_pre_reorder_rank", len(full_ranked)))
            full_ranked.append((rank, node_idx))
            node_text = normalized_text(index.rag.nodes[node_idx].text)
            ev_text = normalized_text(str(ev.get("text") or ev.get("source_block_text") or ""))
            if node_text != ev_text:
                integrity["frozen_full_chunk_text_mismatches"].append({
                    "kc_id": kc_id,
                    "node_index": node_idx,
                    "frozen_prefix": ev_text[:160],
                    "index_prefix": node_text[:160],
                })
        full_ranked.sort()

        selected: list[tuple[int, int]] = []
        next_chunk_tokens = None
        nearest_exceed_by = None
        for rank, node_idx in full_ranked:
            candidate = selected + [(rank, node_idx)]
            candidate_packet = build_dosrag_packet(
                proposed,
                evidence_items_from_selected(kc_id, candidate, index),
            )
            cand_tokens = serialized_visible_evidence_tokens(
                candidate_packet, counter, draft_runner, args.prompt_mode
            )
            raw_next_tokens = counter.count(index.rag.nodes[node_idx].text)
            if cand_tokens > target:
                next_chunk_tokens = raw_next_tokens
                nearest_exceed_by = cand_tokens - target
                break
            selected = candidate

        selected_node_set = {idx for _rank, idx in selected}
        full_node_set = {idx for _rank, idx in full_ranked}
        if not selected_node_set <= full_node_set:
            integrity["matched_non_subset_violations"].append(kc_id)
        if selected != full_ranked[:len(selected)]:
            integrity["selected_prefix_violations"].append(kc_id)

        matched_packet = build_dosrag_packet(
            proposed,
            evidence_items_from_selected(kc_id, selected, index),
        )
        matched_packet["packet_version"] = "dos_rag_v1_proposed_budget_matched_strict_under"
        matched_m = evidence_metrics(matched_packet, counter, draft_runner, schema_runner, args.prompt_mode)
        matched_packets.append(matched_packet)

        lost = [(rank, idx) for rank, idx in full_ranked if idx not in selected_node_set]
        lost_texts = [index.rag.nodes[idx].text for _rank, idx in lost]
        lost_flags = lost_content_flags(lost_texts)
        diff = int(matched_m["serialized_tokens"]) - target
        pct = (100.0 * diff / target) if target else (0.0 if matched_m["serialized_tokens"] == 0 else None)
        ratio = (matched_m["serialized_tokens"] / target) if target else None

        budget_rows.append({
            "kc_id": kc_id,
            "canonical_name": canonical_name(proposed),
            "proposed_evidence_items": proposed_m["evidence_items"],
            "proposed_raw_chars": proposed_m["raw_chars"],
            "proposed_evidence_tokens": proposed_m["serialized_tokens"],
            "proposed_raw_evidence_tokens": proposed_m["raw_tokens"],
            "proposed_complete_prompt_tokens": proposed_m["complete_prompt_tokens"],
            "dos_full_chunks": dos_full_m["evidence_items"],
            "dos_full_chars": dos_full_m["raw_chars"],
            "dos_full_tokens": dos_full_m["serialized_tokens"],
            "dos_full_complete_prompt_tokens": dos_full_m["complete_prompt_tokens"],
            "dos_matched_chunks": matched_m["evidence_items"],
            "dos_matched_chars": matched_m["raw_chars"],
            "dos_matched_tokens": matched_m["serialized_tokens"],
            "dos_matched_complete_prompt_tokens": matched_m["complete_prompt_tokens"],
            "token_difference_vs_proposed": diff,
            "pct_difference_vs_proposed": pct,
            "dos_matched_to_proposed_token_ratio": ratio,
            "next_chunk_tokens": next_chunk_tokens,
            "nearest_chunk_would_exceed_by": nearest_exceed_by,
        })

        full_vs_matched_rows.append({
            "kc_id": kc_id,
            "canonical_name": canonical_name(proposed),
            "proposed_budget_tokens": proposed_m["serialized_tokens"],
            "dos_full_evidence_tokens": dos_full_m["serialized_tokens"],
            "dos_matched_evidence_tokens": matched_m["serialized_tokens"],
            "evidence_chunks_lost_due_to_matching": [
                {
                    "dos_rag_pre_reorder_rank": rank,
                    "dos_rag_chunk_index": idx,
                    "text": index.rag.nodes[idx].text,
                }
                for rank, idx in lost
            ],
            **lost_flags,
        })

        if ordinal % 20 == 0:
            print(f"processed {ordinal}/{len(ids)}", flush=True)

    if integrity["frozen_full_chunk_text_mismatches"]:
        write_json(args.out_root / "integrity_failure.json", integrity)
        raise SystemExit("frozen DOS chunk text no longer matches the DOS index")
    if integrity["matched_non_subset_violations"] or integrity["selected_prefix_violations"]:
        write_json(args.out_root / "integrity_failure.json", integrity)
        raise SystemExit("matched condition violated DOS ranked-prefix subset invariant")

    write_jsonl(args.out_root / "dos_matched_packets" / "kc_packets.jsonl", matched_packets)
    write_jsonl(args.matched_run_dir / "packets" / "kc_packets.jsonl", matched_packets)

    csv_path = args.out_root / "dos_budget_matching_manifest.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(budget_rows[0].keys()))
        writer.writeheader()
        writer.writerows(budget_rows)

    proposed_budget_csv = args.out_root / "proposed_budget_by_kc.csv"
    with proposed_budget_csv.open("w", encoding="utf-8", newline="") as f:
        fields = [
            "kc_id", "canonical_name", "proposed_evidence_items", "proposed_raw_chars",
            "proposed_raw_evidence_tokens", "proposed_evidence_tokens",
            "proposed_complete_prompt_tokens",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in budget_rows:
            writer.writerow({k: row[k] for k in fields})

    write_jsonl(args.out_root / "dos_full_vs_matched_manifest.jsonl", full_vs_matched_rows)

    targets = [r["proposed_evidence_tokens"] for r in budget_rows]
    fulls = [r["dos_full_tokens"] for r in budget_rows]
    matched = [r["dos_matched_tokens"] for r in budget_rows]
    ratios = [r["dos_matched_to_proposed_token_ratio"] for r in budget_rows
              if r["dos_matched_to_proposed_token_ratio"] is not None]
    errors = [abs(r["token_difference_vs_proposed"]) for r in budget_rows]
    pct_errors = [abs(r["pct_difference_vs_proposed"]) for r in budget_rows
                  if r["pct_difference_vs_proposed"] is not None]

    within = {}
    for band in (5, 10, 20):
        within[f"within_{band}_pct"] = sum(
            1 for r in budget_rows
            if r["pct_difference_vs_proposed"] is not None
            and abs(float(r["pct_difference_vs_proposed"])) <= band
        )
    mean_underfill_pct = statistics.fmean(pct_errors) if pct_errors else None
    draft_allowed = bool(mean_underfill_pct is not None and mean_underfill_pct <= args.max_mean_underfill_pct)

    summary = {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - start, 3),
        "n_units": len(budget_rows),
        "token_counter": counter.metadata(),
        "prompt_mode": args.prompt_mode,
        "matching_rule": "strict under Proposed serialized evidence-section tokens; ranked prefix of frozen DOS full chunks",
        "budget_target": "serialized evidence_for_synthesis section after draft_runner.visible_packet_for_prompt()",
        "diagnostic_raw_evidence_tokens": "sum-equivalent raw evidence text counted separately in proposed_budget_by_kc.csv",
        "proposed_tokens": stats(targets),
        "dos_full_tokens": stats(fulls),
        "dos_matched_tokens": stats(matched),
        "dos_matched_to_proposed_token_ratio": stats(ratios),
        "absolute_matching_error_tokens": stats(errors),
        "absolute_matching_error_pct": stats(pct_errors),
        "within_bands": within,
        "zero_chunk_matched_packets": sum(1 for r in budget_rows if r["dos_matched_chunks"] == 0),
        "full_dos_smaller_than_proposed_budget": sum(
            1 for r in budget_rows if r["dos_full_tokens"] <= r["proposed_evidence_tokens"]
        ),
        "draft_allowed_by_granularity_gate": draft_allowed,
        "max_mean_underfill_pct_gate": args.max_mean_underfill_pct,
        "inputs": {
            "proposed_packets_jsonl": str(args.proposed_packets_jsonl),
            "proposed_packets_sha256": sha256_file(args.proposed_packets_jsonl),
            "dos_full_packets_jsonl": str(args.dos_full_packets_jsonl),
            "dos_full_packets_sha256": sha256_file(args.dos_full_packets_jsonl),
            "corpus_jsonl": str(args.corpus_jsonl),
            "corpus_sha256": sha256_file(args.corpus_jsonl),
            "index_cache": str(args.index_cache),
        },
        "outputs": {
            "matched_packets_jsonl": str(args.out_root / "dos_matched_packets" / "kc_packets.jsonl"),
            "matched_run_packets_jsonl": str(args.matched_run_dir / "packets" / "kc_packets.jsonl"),
            "dos_budget_matching_manifest_csv": str(csv_path),
            "proposed_budget_by_kc_csv": str(proposed_budget_csv),
        },
        "integrity": integrity,
    }
    write_json(args.out_root / "technical_run_summary.json", summary)

    readme = args.out_root / "README.md"
    readme.write_text(
        "# DOS-RAG Proposed-Budget-Matched Experiment\n\n"
        f"Created: {summary['created_utc']}\n\n"
        "This directory contains the strict-under-budget DOS-RAG packet condition. The matched "
        "condition is a ranked-prefix subset of the frozen DOS full-budget chunks for each KC; "
        "chunk text, chunk IDs, and source locations are inherited from the unchanged DOS index.\n\n"
        f"Token counter: `{summary['token_counter']['label']}`.\n\n"
        f"Draft allowed by granularity gate: `{draft_allowed}`.\n",
        encoding="utf-8",
    )

    if not draft_allowed:
        print("BUDGET_MATCH_GATE_FAILED: matched DOS underfills Proposed too strongly", flush=True)
        return 20
    print(f"matched packets -> {args.out_root / 'dos_matched_packets' / 'kc_packets.jsonl'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
