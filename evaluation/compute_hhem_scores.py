"""HHEM-2.1-Open groundedness scoring, uniform across runs.

For every unit in a run's postprocessed_review_source.jsonl, pairs the drafted claim text
with the evidence actually available to that draft - resolved via the row's own embedded
source_packet.evidence_for_synthesis (frozen at generation time), NOT the external
evidence-pack file, which is known to drift out of sync with what a given historical draft
actually saw. Premise = concatenated evidence text, hypothesis = drafted claim text
(contextual_kc_draft.text / contextual_topic_draft.text). Abstained units (empty text) are
recorded but not scored - there is no claim to check.

Usage: python3 compute_hhem_scores.py --run-id <run_id> --postprocessed-jsonl <path> --out <path>
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification  # noqa: E402

HHEM_MODEL_DIR = "/path/to/scratch/kc_l/hf_models/hhem_2_1_open"


def draft_key_for_unit_type(unit_type: str) -> str:
    return "contextual_topic_draft" if unit_type == "topic" else "contextual_kc_draft"


def extract_claim_and_evidence(row: dict) -> tuple[str, str, str]:
    """Returns (unit_id, claim_text, evidence_text). evidence_text is '' if none available."""
    unit_id = row.get("knowledge_unit_id") or (row.get("draft") or {}).get("knowledge_unit_id")
    unit_type = row.get("knowledge_unit_type") or (row.get("draft") or {}).get("knowledge_unit_type") or "kc"
    draft = row.get("draft") or {}
    ck = draft.get(draft_key_for_unit_type(unit_type)) or {}
    claim_text = str(ck.get("text") or "")

    source_packet = row.get("source_packet") or {}
    evidence_items = source_packet.get("evidence_for_synthesis") or []
    evidence_texts = [str(item.get("text") or "").strip() for item in evidence_items if isinstance(item, dict)]
    evidence_texts = [t for t in evidence_texts if t]
    evidence_text = "\n".join(evidence_texts)

    return str(unit_id), claim_text, evidence_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--postprocessed-jsonl", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    print(f"Loading HHEM model from {HHEM_MODEL_DIR} ...")
    model = AutoModelForSequenceClassification.from_pretrained(HHEM_MODEL_DIR, trust_remote_code=True)
    model.eval()

    rows = [json.loads(line) for line in open(args.postprocessed_jsonl, encoding="utf-8")]
    print(f"Loaded {len(rows)} rows for run_id={args.run_id}")

    pairs = []
    meta = []
    skipped_empty = []
    for row in rows:
        unit_id, claim_text, evidence_text = extract_claim_and_evidence(row)
        if not claim_text.strip():
            skipped_empty.append(unit_id)
            continue
        if not evidence_text.strip():
            # No evidence at all to check against - record but don't score (undefined premise).
            skipped_empty.append(unit_id)
            continue
        pairs.append((evidence_text, claim_text))
        meta.append({
            "unit_id": unit_id,
            "canonical_name": row.get("canonical_name"),
            "knowledge_unit_type": row.get("knowledge_unit_type"),
            "draft_status": (row.get("draft") or {}).get(
                draft_key_for_unit_type(row.get("knowledge_unit_type") or "kc"), {}
            ).get("status"),
            "claim_chars": len(claim_text),
            "evidence_chars": len(evidence_text),
        })

    print(f"Scoring {len(pairs)} claim/evidence pairs ({len(skipped_empty)} skipped - empty claim or no evidence)")

    scores = []
    batch_size = 16
    with torch.no_grad():
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            batch_scores = model.predict(batch)
            scores.extend(float(x) for x in batch_scores.detach().cpu().tolist())
            print(f"  scored {min(i + batch_size, len(pairs))}/{len(pairs)}")

    results = []
    for m, s in zip(meta, scores):
        results.append({**m, "hhem_score": s})

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_id": args.run_id,
            "total_rows": len(rows),
            "scored_count": len(results),
            "skipped_count": len(skipped_empty),
            "skipped_unit_ids": skipped_empty,
            "mean_hhem_score": sum(scores) / len(scores) if scores else None,
            "results": results,
        }, f, indent=2)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
