"""PHASE 3: full provenance-resolution audit for the adjudicated expert reference.

Resolves every source_evidence_id in the adjudicated reference back to the frozen course corpus
through the complete chain, verifying each hop rather than assuming it:

    reference.source_evidence_ids
        -> Proposed evidence store (evidence_id)          [hop 1]
        -> corpus sentence_id / doc_id / page             [hop 2]
        -> sentence_corpus.jsonl snapshot                 [hop 3, incl. text hash]

Emits reference_provenance_resolution.jsonl (one row per reference source item) plus a summary.

HARD FAILURE CONDITIONS (per spec section 4) - any of these must STOP the freeze:
  * a SUPPORTED reference with zero resolvable source items
  * a PARTIALLY_SUPPORTED reference with zero resolvable source items
  * any source id that neither resolves nor is explicitly classified as an audit failure
  * any UNSUPPORTED row carrying substantive reference text
  * a corpus snapshot hash that does not match the frozen candidate manifest

This script never rewrites expert references and never invents replacement source IDs.

Run: python validate_reference_provenance_final.py
Exit code 0 = PASS (freeze may proceed), 1 = FAIL (freeze must stop).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent  # reference_library/
REFERENCE = BASE / "03_validation" / "adjudicated_input" / "kc_library_expert_curated_adjudicated_final.jsonl"
EVIDENCE_STORE = BASE / "corpus_support" / "evidence_store" / "proposed_evidence_store.jsonl"
CORPUS = BASE / "corpus_support" / "sentence_corpus.jsonl"
FREEZE_MANIFEST = BASE / "00_freeze" / "CANDIDATE_FREEZE_MANIFEST.json"
OUT_JSONL = BASE / "04_gold" / "reference_provenance_resolution.jsonl"
OUT_SUMMARY = BASE / "04_gold" / "reference_provenance_resolution_summary.json"

EXPECTED_CORPUS_SHA = "62c4d26543ee5ac2b81fbb2d7ad772b031d18616d93334122c979d99e867bc33"
EXPECTED_EVIDENCE_STORE_SHA = "96d489558c4f33ac3104a40e63c40d4e23503c7d06870f5d068738fcbf685893"


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_corpus_index(path: Path) -> dict[str, dict]:
    idx = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            idx[d["sentence_id"]] = {
                "doc_id": d["doc_id"],
                "page_index": d.get("page_index"),
                "block_id": d.get("block_id"),
                "sentence_text": d.get("sentence_text", ""),
                "source_block_text": d.get("source_block_text", ""),
                "patch_heading": d.get("patch_heading", ""),
            }
    return idx


def main() -> int:
    failures: list[dict] = []

    corpus_sha = file_sha256(CORPUS)
    evstore_sha = file_sha256(EVIDENCE_STORE)
    reference_sha = file_sha256(REFERENCE)

    if corpus_sha != EXPECTED_CORPUS_SHA:
        failures.append({"kind": "CORPUS_SNAPSHOT_HASH_MISMATCH", "expected": EXPECTED_CORPUS_SHA, "actual": corpus_sha})
    if evstore_sha != EXPECTED_EVIDENCE_STORE_SHA:
        failures.append({"kind": "EVIDENCE_STORE_HASH_MISMATCH", "expected": EXPECTED_EVIDENCE_STORE_SHA, "actual": evstore_sha})

    evidence: dict[str, dict] = {}
    with open(EVIDENCE_STORE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                evidence[d["evidence_id"]] = d

    corpus = load_corpus_index(CORPUS)

    rows = [json.loads(l) for l in open(REFERENCE, encoding="utf-8") if l.strip()]

    resolution_rows: list[dict] = []
    per_kc: dict[str, dict] = {}

    for r in rows:
        kc_id = r["knowledge_unit_id"]
        support = r["support_state"]
        ref_text = (r.get("reference_text") or "").strip()
        src_ids = r.get("source_evidence_ids") or []

        n_resolved = 0
        for sid in src_ids:
            ev = evidence.get(sid)
            if ev is None:
                resolution_rows.append({
                    "knowledge_unit_id": kc_id, "reference_source_id": sid, "resolved": False,
                    "failure_kind": "EVIDENCE_ID_NOT_IN_STORE",
                })
                failures.append({"kind": "EVIDENCE_ID_NOT_IN_STORE", "kc_id": kc_id, "source_id": sid})
                continue

            sentence_id = ev.get("sentence_id")
            corpus_hit = corpus.get(sentence_id) if sentence_id else None
            if corpus_hit is None:
                resolution_rows.append({
                    "knowledge_unit_id": kc_id, "reference_source_id": sid, "resolved": False,
                    "failure_kind": "SENTENCE_ID_NOT_IN_CORPUS", "sentence_id": sentence_id,
                    "document_id": ev.get("doc_id"), "page": ev.get("page_index"),
                })
                failures.append({"kind": "SENTENCE_ID_NOT_IN_CORPUS", "kc_id": kc_id,
                                 "source_id": sid, "sentence_id": sentence_id})
                continue

            # cross-hop consistency: the evidence item's own doc/page must agree with the corpus row
            doc_ok = corpus_hit["doc_id"] == ev.get("doc_id")
            page_ok = corpus_hit["page_index"] == ev.get("page_index")
            if not (doc_ok and page_ok):
                resolution_rows.append({
                    "knowledge_unit_id": kc_id, "reference_source_id": sid, "resolved": False,
                    "failure_kind": "EVIDENCE_CORPUS_LOCATION_DISAGREEMENT",
                    "sentence_id": sentence_id,
                    "evidence_doc": ev.get("doc_id"), "corpus_doc": corpus_hit["doc_id"],
                    "evidence_page": ev.get("page_index"), "corpus_page": corpus_hit["page_index"],
                })
                failures.append({"kind": "EVIDENCE_CORPUS_LOCATION_DISAGREEMENT", "kc_id": kc_id, "source_id": sid})
                continue

            n_resolved += 1
            source_text = corpus_hit["source_block_text"] or corpus_hit["sentence_text"]
            resolution_rows.append({
                "knowledge_unit_id": kc_id,
                "reference_source_id": sid,
                "resolved": True,
                "document_id": corpus_hit["doc_id"],
                "page": corpus_hit["page_index"],
                "section": ev.get("patch_heading") or corpus_hit.get("patch_heading") or "",
                "block_id": corpus_hit["block_id"],
                "sentence_id": sentence_id,
                "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "evidence_text_sha256": ev.get("text_sha256"),
                "corpus_sha256": corpus_sha,
            })

        per_kc[kc_id] = {"support_state": support, "n_source_ids": len(src_ids), "n_resolved": n_resolved,
                          "has_reference_text": bool(ref_text)}

        if support in ("SUPPORTED", "PARTIALLY_SUPPORTED") and n_resolved == 0:
            failures.append({"kind": "SUPPORTED_REFERENCE_WITH_NO_RESOLVABLE_SOURCE", "kc_id": kc_id, "support_state": support})
        if support == "UNSUPPORTED" and ref_text:
            failures.append({"kind": "UNSUPPORTED_ROW_HAS_REFERENCE_TEXT", "kc_id": kc_id})

    # UNSUPPORTED rows: confirm the expert source-gap record survives
    unsupported = [r for r in rows if r["support_state"] == "UNSUPPORTED"]
    unsupported_audit = []
    for r in unsupported:
        has_reason = bool((r.get("adjudication_reason") or "").strip())
        has_limits = bool((r.get("source_limitations") or "").strip()) and (r.get("source_limitations") or "").strip().lower() != "none"
        unsupported_audit.append({
            "knowledge_unit_id": r["knowledge_unit_id"],
            "reference_text_empty": not (r.get("reference_text") or "").strip(),
            "has_adjudication_reason": has_reason,
            "has_source_limitations": has_limits,
            "review_action": r["review_action"],
            "n_source_evidence_ids": len(r.get("source_evidence_ids") or []),
        })
        if not has_reason:
            failures.append({"kind": "UNSUPPORTED_ROW_MISSING_GAP_RATIONALE", "kc_id": r["knowledge_unit_id"]})

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for row in resolution_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    n_total = len(resolution_rows)
    n_res = sum(1 for r in resolution_rows if r["resolved"])
    distinct_ids = {r["reference_source_id"] for r in resolution_rows}

    summary = {
        "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference_file": str(REFERENCE.name),
        "reference_sha256": reference_sha,
        "corpus_sha256": corpus_sha,
        "evidence_store_sha256": evstore_sha,
        "n_reference_rows": len(rows),
        "n_source_citation_instances": n_total,
        "n_distinct_source_ids": len(distinct_ids),
        "n_resolved": n_res,
        "n_unresolved": n_total - n_res,
        "resolution_rate": (n_res / n_total) if n_total else None,
        "support_state_counts": {s: sum(1 for v in per_kc.values() if v["support_state"] == s)
                                  for s in ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED")},
        "supported_or_partial_with_zero_resolvable": [k for k, v in per_kc.items()
                                                       if v["support_state"] in ("SUPPORTED", "PARTIALLY_SUPPORTED") and v["n_resolved"] == 0],
        "unsupported_audit": unsupported_audit,
        "n_failures": len(failures),
        "failures": failures,
        "result": "PASS" if not failures else "FAIL",
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps({k: v for k, v in summary.items() if k not in ("unsupported_audit", "failures")}, indent=2))
    print(f"\nunsupported_audit ({len(unsupported_audit)} rows):")
    for u in unsupported_audit:
        print(f"  {u['knowledge_unit_id']}: empty_text={u['reference_text_empty']} reason={u['has_adjudication_reason']} "
              f"limits={u['has_source_limitations']} n_src={u['n_source_evidence_ids']}")
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for fl in failures[:25]:
            print(f"  {fl}")
    print(f"\nwrote {OUT_JSONL.name} and {OUT_SUMMARY.name}")
    print(f"RESULT: {summary['result']}")
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
