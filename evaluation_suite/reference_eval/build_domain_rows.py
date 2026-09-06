"""Build reference-free evaluation rows for the mathematics and sociology domains.

WHY THESE DOMAINS ARE EVALUATED DIFFERENTLY
The frozen reference library covers 159 data-mining KCs and nothing else; KC-id overlap with
mathematics (71 KCs) and sociology (149 KCs) is exactly ZERO. M2 (correctness vs reference),
M3 (completeness vs reference) and TARGET (alignment to the reference KC) are therefore not
merely unmeasured here - they are undefined, because each needs a gold reference that does not
exist. Building one would require domain expertise the project owner does not claim, and a
badly-authored reference is worse than none.

WHAT REMAINS MEASURABLE, AND WHY IT IS THE RIGHT THING TO MEASURE
Per-claim faithfulness needs no reference: it asks whether each claim in the draft is supported by
the evidence THAT DRAFTER RECEIVED. Finding F-34 showed this per-claim rate is also the better
faithfulness measure in-domain - the frozen all-or-nothing M1 scalar mostly tracks draft length
(observed = p^n almost exactly), so a 1.45-point per-claim gap was being reported as 13.42 points.
The reference-free metric and the statistically sound metric are the same metric.

Abstention rate is likewise reference-free and is reported as a primary outcome.

SCOPE: Qwen3.8 27B only, per the project owner's decision. This is a domain-generalisation probe
for one drafter, not a cross-domain ablation.

Extraction contract is identical to build_ablation_rows.py / extract_calibration_content.py so the
rows stay comparable with the data-mining campaign.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

R9 = "/path/to/pipeline/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs"

DOMAINS = {
    "mathematics": f"{R9}/r9_latest_20260822T202514Z_mathematics_latest",
    "sociology": f"{R9}/r9_latest_20260822T202514Z_sociology_latest",
}
DRAFTER = "kc_drafts_qwen38_27b.jsonl"
ARM = "intrinsic_P-Q"  # same arm identity as the data-mining intrinsic Qwen arm


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--meta-out", type=Path, required=True)
    args = ap.parse_args()

    rows, stats = [], {}
    for domain, root in DOMAINS.items():
        dpath = Path(root) / "drafts" / DRAFTER
        ppath = Path(root) / "packets" / "kc_packets.jsonl"
        if not dpath.exists() or not ppath.exists():
            print(f"SKIP {domain}: missing {dpath if not dpath.exists() else ppath}", file=sys.stderr)
            continue

        evidence = {}
        for line in open(ppath, encoding="utf-8"):
            if not line.strip():
                continue
            pkt = json.loads(line)
            kid = pkt.get("kc_id") or pkt.get("knowledge_unit_id")
            evidence[kid] = [
                {"text": e.get("text") or "", "doc_id": e.get("doc_id"),
                 "page_index": e.get("page_index"), "section": e.get("patch_heading") or ""}
                for e in (pkt.get("evidence_for_synthesis") or [])
            ]

        n_empty = 0
        for line in open(dpath, encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            kid = rec["knowledge_unit_id"]
            d = rec.get("draft")
            if d is None:
                text, status = "", "TECHNICAL_FAILURE_NO_DRAFT"
                canonical = rec.get("canonical_name") or kid
                hier = []
            else:
                ckd = d.get("contextual_kc_draft") or {}
                text = ckd.get("text") or ""
                status = ckd.get("status", "")
                canonical = d.get("canonical_name") or rec.get("canonical_name") or kid
                hier = ((rec.get("source_packet") or {}).get("hierarchy") or {}).get("topic_path") or []
            if not text.strip():
                n_empty += 1
            rows.append({
                "eval_row_id": f"{kid}|{domain}|{ARM}",
                "unit_id": kid,
                "domain": domain,
                "arm": ARM,
                "family": "domain_generalisation",
                "drafter": "qwen3.8:27b",
                "canonical_name": canonical,
                "hierarchy_path": hier,
                # deliberately empty: no gold reference exists for these domains, so the runner
                # skips M2/M3/TARGET and evaluates decomposition + per-claim faithfulness only
                "expert_reference": "",
                "candidate_draft": text,
                "draft_status_INTERNAL_DO_NOT_SHOW": status,
                "candidate_system_evidence": [
                    {"id": f"SRC_{i+1:03d}", "text": e["text"]}
                    for i, e in enumerate(evidence.get(kid, []))
                ],
            })
        stats[domain] = {
            "n_kcs": sum(1 for r in rows if r["domain"] == domain),
            "n_empty_drafts": n_empty,
            "drafts_sha256": sha(dpath),
            "packets_sha256": sha(ppath),
        }
        print(f"{domain}: {stats[domain]['n_kcs']} KCs, {n_empty} abstentions", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {
        "n_rows": len(rows),
        "arm": ARM,
        "drafter": "qwen3.8:27b",
        "per_domain": stats,
        "evaluable_metrics": ["per_claim_faithfulness", "abstention_rate"],
        "not_evaluable": {
            "M2_REFERENCE_SOURCE_CORRECTNESS": "no expert reference exists for these domains",
            "M3_CORE_COMPLETENESS": "no expert reference exists for these domains",
            "TARGET_ALIGNMENT": "no expert reference exists for these domains",
        },
        "reason": "The frozen reference library is 159 data-mining KCs; KC-id overlap with these "
                  "domains is zero. Reference-based metrics are undefined here, not merely "
                  "unmeasured. Authoring references would require domain expertise the project "
                  "owner does not claim.",
        "output_sha256": sha(args.out),
    }
    args.meta_out.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out} ({len(rows)} rows)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
