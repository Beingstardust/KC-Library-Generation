"""PHASE 2: explicit final human-approval transition for the adjudicated expert reference.

This tool exists because the adjudicated artifact ships with
    human_final_approval_pending = true
    curation_status = ADJUDICATED_REFERENCE_READY_FOR_HUMAN_APPROVAL
and those fields must NOT be flipped silently just because the filename says "final".

It validates all 159 rows, shows the operator exactly what they are approving (counts + the
sha256 of the preapproval artifact), demands an explicit typed acknowledgement, and then writes
a NEW artifact - the preapproval file is never overwritten.

METADATA ONLY. The following fields are copied byte-for-byte and a post-write verification pass
re-reads the output and re-compares every one of them against the input, aborting if any differs:
    reference_text, reference_display_text, support_state, review_action, adjudication_reason,
    reason_codes, source_evidence_ids, full_source_refs, source_limitations,
    original_machine_draft_text, original_machine_draft_status, changed_from_machine_draft,
    canonical_name, hierarchy, knowledge_unit_id, knowledge_unit_type

Only these change:
    human_final_approval_pending : true -> false
    curation_status              : ADJUDICATED_REFERENCE_READY_FOR_HUMAN_APPROVAL
                                   -> EXPERT_ADJUDICATED_REFERENCE_FINAL
    + added: human_final_approval  {approved_by, approved_utc, preapproval_sha256, tool}

Usage (interactive - the operator types the acknowledgement themselves):
    python finalize_adjudicated_reference.py --operator "Name <email>" \
        --approval-channel INTERACTIVE_TERMINAL

Nothing is written unless the exact acknowledgement phrase is supplied on stdin. There is
deliberately no --yes/--force flag that would let the phrase be skipped.

--approval-channel is REQUIRED and is recorded verbatim in the receipt, so the artifact always
carries an honest record of HOW the human approval was captured. Use INTERACTIVE_TERMINAL when a
human typed the phrase at a live prompt. Use AGENT_SESSION_RELAY only when a human gave an
explicit, recorded approval decision in an agent session and the agent relayed the phrase on
their behalf - that is a weaker provenance than a live terminal and the receipt says so, so that
anyone auditing the freeze can see the difference rather than having to infer it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
IN_PATH = BASE / "03_validation" / "adjudicated_input" / "kc_library_expert_curated_adjudicated_final.jsonl"
OUT_PATH = BASE / "03_validation" / "approved" / "kc_library_expert_adjudicated_reference_APPROVED.jsonl"
RECEIPT_PATH = BASE / "03_validation" / "approved" / "human_final_approval_receipt.json"

ACK_PHRASE = "I APPROVE THIS EXPERT REFERENCE AS FINAL"

EXPECTED_ACTIONS = {"ACCEPT": 117, "MINOR_EDIT": 10, "MAJOR_EDIT": 15, "REPLACE": 10, "NO_REFERENCE_CORPUS_UNSUPPORTED": 7}
EXPECTED_SUPPORT = {"SUPPORTED": 150, "PARTIALLY_SUPPORTED": 2, "UNSUPPORTED": 7}
EXPECTED_N = 159

IMMUTABLE_FIELDS = (
    "knowledge_unit_id", "knowledge_unit_type", "canonical_name", "hierarchy",
    "support_state", "review_action", "reference_text", "reference_display_text",
    "source_evidence_ids", "full_source_refs", "reason_codes", "source_limitations",
    "original_machine_draft_status", "original_machine_draft_text",
    "changed_from_machine_draft", "adjudication_reason", "cross_reviewer_adjudicated",
)


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(rows: list[dict]) -> list[str]:
    problems = []
    if len(rows) != EXPECTED_N:
        problems.append(f"expected {EXPECTED_N} rows, got {len(rows)}")
    ids = [r["knowledge_unit_id"] for r in rows]
    if len(set(ids)) != len(ids):
        dupes = [k for k, c in Counter(ids).items() if c > 1]
        problems.append(f"duplicate knowledge_unit_id: {dupes}")

    actions = Counter(r["review_action"] for r in rows)
    if dict(actions) != EXPECTED_ACTIONS:
        problems.append(f"action counts {dict(actions)} != expected {EXPECTED_ACTIONS}")
    support = Counter(r["support_state"] for r in rows)
    if dict(support) != EXPECTED_SUPPORT:
        problems.append(f"support counts {dict(support)} != expected {EXPECTED_SUPPORT}")

    for r in rows:
        kc = r["knowledge_unit_id"]
        text = (r.get("reference_text") or "").strip()
        if r["support_state"] == "UNSUPPORTED" and text:
            problems.append(f"{kc}: UNSUPPORTED but has reference_text")
        if r["support_state"] in ("SUPPORTED", "PARTIALLY_SUPPORTED") and not text:
            problems.append(f"{kc}: {r['support_state']} but reference_text is empty")
        if r["review_action"] == "ACCEPT" and (r.get("reference_text") or "") != (r.get("original_machine_draft_text") or ""):
            problems.append(f"{kc}: ACCEPT but reference_text != original_machine_draft_text")
        if not r.get("cross_reviewer_adjudicated"):
            problems.append(f"{kc}: cross_reviewer_adjudicated is not true")
        if not r.get("human_final_approval_pending"):
            problems.append(f"{kc}: human_final_approval_pending is already false - already approved?")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--operator", required=True, help='approving operator identity, e.g. "Name <email>"')
    ap.add_argument("--approval-channel", required=True,
                    choices=("INTERACTIVE_TERMINAL", "AGENT_SESSION_RELAY"),
                    help="how the human approval was captured; recorded verbatim in the receipt")
    ap.add_argument("--approval-note", default="",
                    help="free-text detail about the approval channel, recorded verbatim in the receipt")
    args = ap.parse_args()

    if not IN_PATH.exists():
        print(f"ERROR: preapproval artifact not found: {IN_PATH}")
        return 1
    if OUT_PATH.exists():
        print(f"ERROR: approved artifact already exists: {OUT_PATH}\nRefusing to re-approve. Delete it deliberately if a re-approval is genuinely intended.")
        return 1

    rows = [json.loads(l) for l in open(IN_PATH, encoding="utf-8") if l.strip()]
    problems = validate(rows)
    pre_sha = file_sha256(IN_PATH)

    print("=" * 72)
    print("FINAL HUMAN APPROVAL OF THE EXPERT-ADJUDICATED REFERENCE KC LIBRARY")
    print("=" * 72)
    print(f"\npreapproval artifact : {IN_PATH}")
    print(f"sha256               : {pre_sha}")
    print(f"rows                 : {len(rows)} ({len({r['knowledge_unit_id'] for r in rows})} unique KC ids)")
    print("\nadjudicated ACTION counts:")
    for k, v in sorted(Counter(r["review_action"] for r in rows).items()):
        print(f"    {k:<32} {v:>4}   ({100*v/len(rows):.2f}%)")
    print("\nadjudicated SOURCE-SUPPORT counts:")
    for k, v in sorted(Counter(r["support_state"] for r in rows).items()):
        print(f"    {k:<32} {v:>4}   ({100*v/len(rows):.2f}%)")
    changed = sum(1 for r in rows if r.get("changed_from_machine_draft"))
    print(f"\nchanged from machine draft: {changed}/{len(rows)} ({100*changed/len(rows):.2f}%)")
    print(f"unchanged (ACCEPT)        : {len(rows)-changed}/{len(rows)}")

    if problems:
        print(f"\nVALIDATION FAILED - {len(problems)} problem(s). NOT proceeding:")
        for p in problems[:30]:
            print(f"  - {p}")
        return 1
    print("\nvalidation: all 159 rows PASS structural + count + consistency checks")

    print("\nThis transition changes METADATA ONLY. reference_text, support_state, review_action,")
    print("adjudication_reason, reason_codes and all source fields are copied byte-for-byte and")
    print("re-verified after writing.")
    print(f"\nApproving operator: {args.operator}")
    print(f"\nTo approve, type exactly:\n    {ACK_PHRASE}")
    try:
        typed = input("\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nno acknowledgement received - ABORTED, nothing written")
        return 1

    if typed != ACK_PHRASE:
        print("acknowledgement did not match - ABORTED, nothing written")
        return 1

    approved_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_rows = []
    for r in rows:
        new = dict(r)
        new["human_final_approval_pending"] = False
        new["curation_status"] = "EXPERT_ADJUDICATED_REFERENCE_FINAL"
        new["human_final_approval"] = {
            "approved_by": args.operator,
            "approved_utc": approved_utc,
            "approval_channel": args.approval_channel,
            "preapproval_sha256": pre_sha,
            "tool": "finalize_adjudicated_reference.py",
        }
        out_rows.append(new)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # post-write verification: re-read and confirm every immutable field is byte-identical
    reread = [json.loads(l) for l in open(OUT_PATH, encoding="utf-8") if l.strip()]
    drift = []
    by_id_in = {r["knowledge_unit_id"]: r for r in rows}
    for r in reread:
        src = by_id_in[r["knowledge_unit_id"]]
        for fld in IMMUTABLE_FIELDS:
            if json.dumps(src.get(fld), sort_keys=True, ensure_ascii=False) != json.dumps(r.get(fld), sort_keys=True, ensure_ascii=False):
                drift.append((r["knowledge_unit_id"], fld))
    if drift:
        OUT_PATH.unlink()
        print(f"\nFATAL: post-write verification found {len(drift)} immutable-field difference(s). Output deleted.")
        for d in drift[:20]:
            print(f"  {d}")
        return 1

    if file_sha256(IN_PATH) != pre_sha:
        print("\nFATAL: preapproval artifact changed during this run.")
        return 1

    receipt = {
        "approved_by": args.operator,
        "approved_utc": approved_utc,
        "approval_channel": args.approval_channel,
        "approval_channel_meaning": {
            "INTERACTIVE_TERMINAL": "a human typed the acknowledgement phrase at a live prompt",
            "AGENT_SESSION_RELAY": "a human gave an explicit recorded approval decision inside an agent session and the agent relayed the acknowledgement phrase on their behalf - weaker provenance than a live terminal",
        }[args.approval_channel],
        "approval_note": args.approval_note,
        "acknowledgement_phrase": ACK_PHRASE,
        "preapproval_artifact": str(IN_PATH.name),
        "preapproval_sha256": pre_sha,
        "approved_artifact": str(OUT_PATH.name),
        "approved_sha256": file_sha256(OUT_PATH),
        "n_rows": len(out_rows),
        "action_counts": dict(Counter(r["review_action"] for r in out_rows)),
        "support_counts": dict(Counter(r["support_state"] for r in out_rows)),
        "immutable_fields_verified": list(IMMUTABLE_FIELDS),
        "post_write_verification": "PASS - all immutable fields byte-identical to preapproval artifact",
    }
    with open(RECEIPT_PATH, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)

    print(f"\nAPPROVED at {approved_utc}")
    print(f"  wrote  : {OUT_PATH}")
    print(f"  sha256 : {receipt['approved_sha256']}")
    print(f"  receipt: {RECEIPT_PATH}")
    print(f"  preapproval artifact left untouched at {IN_PATH}")
    print("\npost-write verification: PASS (all immutable fields byte-identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
