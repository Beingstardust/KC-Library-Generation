"""Package the sentinel cases whose gold label is disputed into a single self-contained file the
project owner can adjudicate from, without needing to open the pipeline.

These cases are NOT guessed, NOT excluded from the suite, and NOT modified to improve agreement.
Their disputed criterion is carried as GOLD_PENDING and excluded from agreement while being
counted and reported.

Run: python build_pending_adjudication.py
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).parent
GOLD = BASE / "output" / "reference_sentinel_gold.jsonl"
LEGACY = BASE.parent / "output" / "r9_final" / "rubric_sentinel_gold.jsonl"
REFERENCE = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
RAW_CANDIDATES = [
    BASE / "output" / "selene_reference_sentinel_raw.json",
    BASE / "output" / "selene_reference_sentinel_raw.PRE_FIELDORDER_FIX.json",
]
OUT = BASE / "output" / "pending_sentinel_adjudication.json"

GOLD_PENDING = "GOLD_PENDING"

WHY_DISPUTED = (
    "Legacy F3 (Material Correctness) asked whether the content was CORRECT, so a true-but-unsourced "
    "injected claim passed. New M2 asks whether each claim is supported by the expert reference OR by "
    "the source authority; a true-but-unsourced claim is NOT_SUPPORTED_BY_AUTHORITY, which the "
    "specification does not count as materially correct. The M2 gold label therefore turns on a "
    "question the frozen sentinel record never settled: is this specific injected claim present in the "
    "AUTHORITY corpus, or only absent from the system evidence?\n\n"
    "For SENT_029/030/031 the frozen record contains an explicit statement that the claim is absent "
    "from the authority context, so those were set to FAIL on that documented basis. For the cases "
    "below the record verifies only SYSTEM-EVIDENCE absence. A keyword probe of the authority text was "
    "run and was inconclusive (some related terms present, the specific assertion not clearly located), "
    "and a keyword probe is not a substitute for an expert source judgment. The label is therefore left "
    "pending rather than guessed."
)


def main() -> int:
    gold = {json.loads(l)["sentinel_id"]: json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()}
    legacy = {json.loads(l)["sentinel_id"]: json.loads(l) for l in open(LEGACY, encoding="utf-8") if l.strip()}
    reference = {json.loads(l)["knowledge_unit_id"]: json.loads(l)
                 for l in open(REFERENCE, encoding="utf-8") if l.strip()}

    raw = None
    raw_name = None
    for p in RAW_CANDIDATES:
        if p.exists():
            raw = {r["sentinel_id"]: r for r in json.loads(p.read_text(encoding="utf-8"))["results"]}
            raw_name = p.name
            break

    pending_ids = sorted(
        sid for sid, g in gold.items()
        if any(v == GOLD_PENDING for v in g["expected"].values())
    )

    cases = []
    for sid in pending_ids:
        g, s = gold[sid], legacy[sid]
        ref = reference[g["kc_id"]]
        disputed = [k for k, v in g["expected"].items() if v == GOLD_PENDING]

        model_out = {}
        if raw and sid in raw:
            for task_key, label in (("m1", "M1_faithfulness"), ("m2", "M2_correctness"),
                                     ("m3_holistic", "M3_core_completeness"),
                                     ("m4_holistic", "M4_evidence_adequacy_EXPLORATORY"),
                                     ("target", "TARGET_ALIGNMENT")):
                c = raw[sid]["calls"].get(task_key)
                if not c:
                    continue
                entry = {"status": c["status"]}
                if c.get("contract_valid"):
                    resp = c["response"]
                    if "verdicts" in resp:
                        entry["per_claim_labels"] = [v["label"] for v in resp["verdicts"]]
                        entry["per_claim_rationales"] = [v.get("rationale", "")[:400] for v in resp["verdicts"]]
                    else:
                        entry["label"] = resp.get("label")
                        entry["rationale"] = (resp.get("rationale") or "")[:600]
                model_out[label] = entry

        cases.append({
            "sentinel_id": sid,
            "kc_id": g["kc_id"],
            "canonical_name": g["canonical_name"],
            "hierarchy_path": ref.get("hierarchy", {}).get("topic_path") or [],
            "category": g["category"],
            "case_type": g["case_type"],
            "disputed_criteria": disputed,
            "expected_labels_currently_stored": g["expected"],
            "legacy_expected_labels": g["legacy_expected"],
            "expert_reference_text": ref.get("reference_text") or "",
            "expert_reference_support_state": ref["support_state"],
            "expert_reference_review_action": ref["review_action"],
            "candidate_draft": s.get("draft_body") or "",
            "candidate_system_evidence": [
                {"id": e["auth_id"], "doc_id": e.get("doc_id"), "page_index": e.get("page_index"),
                 "text": e["text"]}
                for e in (s.get("system_evidence") or [])
            ],
            "n_authority_evidence_items": len(s.get("authority_evidence") or []),
            "authority_evidence_note": "Full authority context is large and is NOT inlined here; it is "
                                        "available in the frozen sentinel record at "
                                        "output/r9_final/rubric_sentinel_gold.jsonl under this sentinel's "
                                        "authority_evidence field.",
            "frozen_sentinel_rationale": s.get("rationale", ""),
            "frozen_sentinel_provenance": s.get("provenance", ""),
            "model_outputs_for_information_only": model_out,
            "model_outputs_source": raw_name,
            "why_disputed": WHY_DISPUTED,
            "question_for_adjudicator": (
                f"For {sid}: is the injected claim in the candidate draft supported anywhere in the "
                f"ORIGINAL COURSE CORPUS (not merely in the system evidence shown to the drafter)?\n"
                f"  - If YES -> the claim is REFERENCE_SILENT_BUT_SOURCE_SUPPORTED, which counts as "
                f"materially correct, so M2_correctness gold = PASS.\n"
                f"  - If NO  -> the claim is NOT_SUPPORTED_BY_AUTHORITY, which does not count as "
                f"materially correct, so M2_correctness gold = FAIL.\n"
                f"Note the M1 (faithfulness) gold for this case is already settled as FAIL and is not "
                f"in dispute - the claim is definitely absent from the system evidence."
            ),
            "adjudication_decision": None,
            "adjudication_rationale": None,
            "adjudicated_by": None,
            "adjudicated_utc": None,
        })

    out = {
        "schema_version": "pending_sentinel_adjudication_v1",
        "generated_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_pending": len(cases),
        "pending_sentinel_ids": pending_ids,
        "status": "AWAITING_PROJECT_OWNER_ADJUDICATION",
        "handling_rules": [
            "The disputed criterion is stored as GOLD_PENDING in reference_sentinel_gold.jsonl.",
            "GOLD_PENDING labels are excluded from agreement but counted and reported; no aggregate "
            "is computed from a guessed label.",
            "These cases are NOT removed from the 36-case suite and their other criteria still score "
            "normally - only the disputed criterion is held.",
            "Judge prompts must NOT be tuned against these cases while their gold status is unresolved.",
            "Once adjudicated: version the gold file, record timestamp and rationale, preserve the old "
            "version, and recompute ONLY the affected aggregates. Do NOT rerun model inference - the "
            "analyzer reads gold and predictions from separate files precisely so a gold revision "
            "never requires new inference.",
        ],
        "cases": cases,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(cases)} pending case(s): {pending_ids}")
    for c in cases:
        print(f"\n  {c['sentinel_id']}  {c['kc_id']} ({c['canonical_name']})")
        print(f"    disputed: {c['disputed_criteria']}")
        print(f"    category: {c['category']}   legacy F3: {c['legacy_expected_labels']['f3']}")
        print(f"    n_system_evidence: {len(c['candidate_system_evidence'])}  n_authority: {c['n_authority_evidence_items']}")
    print(f"\nwrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
