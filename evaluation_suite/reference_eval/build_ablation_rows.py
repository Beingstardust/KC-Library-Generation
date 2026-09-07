"""Build the full ablation evaluation set: every frozen candidate arm x every KC.

Runs on Cluster-B, where the frozen candidate artifacts live. Emits one JSONL row per (KC, arm).

EXTRACTION CONTRACT — deliberately identical to the calibration extraction
(`extract_calibration_content.py`), so ablation rows and the human-calibrated rows are built the
same way and remain comparable:
  - draft text   = draft.contextual_kc_draft.text
  - draft status = draft.contextual_kc_draft.status  (INTERNAL; never shown to the judge)
  - evidence     = packets/kc_packets.jsonl -> evidence_for_synthesis
  - a missing draft object becomes text="" with status TECHNICAL_FAILURE_NO_DRAFT

An EMPTY draft is a genuine abstention by that system, not missing data. It is emitted and scored
as such — how a system behaves when it declines to draft is part of what is being evaluated.

Arm identity IS written here. That is safe and necessary: this file is the evaluation input, and
the judge never receives it directly — prompts are assembled by the runner, which passes only
draft text and opaque SRC_* evidence ids, with `assert_blinded` raising on any leak.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

R9 = "/path/to/pipeline/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs"
EXT = "/path/to/pipeline/wt_450c88c_extrinsic/data/v3/runs"

# The 7 frozen candidate arms, exactly as recorded in CANDIDATE_FREEZE_MANIFEST.json.
# family: which pre-registered comparison this arm belongs to (see COMPARATIVE_USE_PROTOCOL.md).
ARMS = {
    "intrinsic_P-Q": {
        "family": "intrinsic", "drafter": "qwen3.8:27b", "retrieval": "Proposed",
        "drafts": f"{R9}/r9_latest_20260822T202514Z_datamining_latest/drafts/kc_drafts_qwen38_27b.jsonl",
        "packets": f"{R9}/r9_latest_20260822T202514Z_datamining_latest/packets/kc_packets.jsonl",
    },
    "intrinsic_P-G": {
        "family": "intrinsic", "drafter": "gemma4:31b", "retrieval": "Proposed",
        "drafts": f"{R9}/r9_latest_20260822T202514Z_datamining_latest/drafts/kc_drafts_gemma4_31b.jsonl",
        "packets": f"{R9}/r9_latest_20260822T202514Z_datamining_latest/packets/kc_packets.jsonl",
    },
    "intrinsic_P-D": {
        "family": "intrinsic", "drafter": "deepseek-r1:32b", "retrieval": "Proposed",
        "drafts": f"{R9}/r9_latest_20260822T202514Z_datamining_latest/drafts/kc_drafts_deepseek_r1_32b.jsonl",
        "packets": f"{R9}/r9_latest_20260822T202514Z_datamining_latest/packets/kc_packets.jsonl",
    },
    "extrinsic_P-Q": {
        "family": "extrinsic", "drafter": "qwen3.8:27b", "retrieval": "Proposed",
        "drafts": f"{EXT}/r9final_ext_proposed_ctrl_20260823T140000Z/drafts/kc_drafts_qwen38_27b.jsonl",
        "packets": f"{EXT}/r9final_ext_proposed_ctrl_20260823T140000Z/packets/kc_packets.jsonl",
    },
    "extrinsic_B-Q": {
        "family": "extrinsic", "drafter": "qwen3.8:27b", "retrieval": "BaseDense",
        "drafts": f"{EXT}/r9final_ext_basedense_20260823T140000Z/drafts/kc_drafts_qwen38_27b.jsonl",
        "packets": f"{EXT}/r9final_ext_basedense_20260823T140000Z/packets/kc_packets.jsonl",
    },
    "extrinsic_DOS-Q": {
        "family": "extrinsic", "drafter": "qwen3.8:27b", "retrieval": "DOS-RAG",
        "drafts": f"{EXT}/r9final_ext_dosrag_20260823T140000Z/drafts/kc_drafts_qwen38_27b.jsonl",
        "packets": f"{EXT}/r9final_ext_dosrag_20260823T140000Z/packets/kc_packets.jsonl",
    },
    "sensitivity_DOS-Q_matched": {
        "family": "sensitivity", "drafter": "qwen3.8:27b", "retrieval": "DOS-RAG (budget-matched)",
        "drafts": f"{R9}/r9_latest_20260822T202514Z_dos_budget_matched_latest_run/drafts/kc_drafts_qwen38_27b.jsonl",
        "packets": f"{R9}/r9_latest_20260822T202514Z_dos_budget_matched_latest_run/packets/kc_packets.jsonl",
    },
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_arm(paths):
    drafts, evidence = {}, {}
    with open(paths["drafts"], encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            kid = row["knowledge_unit_id"]
            d = row.get("draft")
            if d is None:
                drafts[kid] = {"text": "", "status": "TECHNICAL_FAILURE_NO_DRAFT"}
            else:
                ckd = d.get("contextual_kc_draft") or {}
                drafts[kid] = {"text": ckd.get("text") or "", "status": ckd.get("status", "")}
    with open(paths["packets"], encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            pkt = json.loads(line)
            kid = pkt.get("kc_id") or pkt.get("knowledge_unit_id")
            evidence[kid] = [
                {"text": e.get("text") or "", "doc_id": e.get("doc_id"),
                 "page_index": e.get("page_index"), "section": e.get("patch_heading") or ""}
                for e in (pkt.get("evidence_for_synthesis") or [])
            ]
    return drafts, evidence


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", type=Path, required=True,
                    help="expert_adjudicated_reference_kc_library.jsonl (frozen gold)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--meta-out", type=Path, required=True)
    args = ap.parse_args()

    reference = {}
    for l in open(args.reference, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            reference[r["knowledge_unit_id"]] = r
    print(f"reference KCs: {len(reference)}", file=sys.stderr)

    rows, stats = [], {}
    for arm, paths in ARMS.items():
        drafts, evidence = load_arm(paths)
        kc_ids = sorted(drafts)
        n_empty = sum(1 for v in drafts.values() if not v["text"].strip())
        n_no_ref = 0
        for kid in kc_ids:
            ref = reference.get(kid)
            if ref is None:
                n_no_ref += 1
                continue
            hier = ref.get("hierarchy", {}).get("topic_path") or []
            rows.append({
                "eval_row_id": f"{kid}|{arm}",
                "unit_id": kid,
                "arm": arm,
                "family": paths["family"],
                "drafter": paths["drafter"],
                "retrieval": paths["retrieval"],
                "canonical_name": ref.get("canonical_name"),
                "hierarchy_path": hier,
                "expert_reference": ref.get("reference_text") or "",
                "candidate_draft": drafts[kid]["text"],
                "draft_status_INTERNAL_DO_NOT_SHOW": drafts[kid]["status"],
                "candidate_system_evidence": [
                    {"id": f"SRC_{i+1:03d}", "text": e["text"]}
                    for i, e in enumerate(evidence.get(kid, []))
                ],
            })
        stats[arm] = {
            "n_kcs": len(kc_ids), "n_empty_drafts": n_empty,
            "n_dropped_no_reference": n_no_ref,
            "drafts_sha256": sha(Path(paths["drafts"])),
        }
        print(f"{arm}: kcs={len(kc_ids)} empty={n_empty} no_ref={n_no_ref}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # paired-coverage check (protocol condition C4)
    by_kc = {}
    for r in rows:
        by_kc.setdefault(r["unit_id"], set()).add(r["arm"])
    complete = [k for k, a in by_kc.items() if len(a) == len(ARMS)]
    meta = {
        "n_rows": len(rows),
        "n_arms": len(ARMS),
        "n_kcs_total": len(by_kc),
        "n_kcs_with_all_arms": len(complete),
        "kcs_missing_some_arm": sorted(k for k, a in by_kc.items() if len(a) != len(ARMS)),
        "per_arm": stats,
        "output_sha256": sha(args.out),
        "extraction_contract": "identical to extract_calibration_content.py (draft.contextual_kc_draft.text "
                               "+ packets evidence_for_synthesis); empty draft = genuine abstention, retained",
    }
    args.meta_out.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {args.out} ({len(rows)} rows)", file=sys.stderr)
    print(f"KCs with all {len(ARMS)} arms present: {len(complete)}/{len(by_kc)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
