"""PHASE 4: freeze the approved expert-adjudicated reference into 04_gold/.

Runs only after PHASE 2 (explicit human approval) and PHASE 3 (provenance resolution) have both
succeeded, and re-checks both rather than trusting that they were run. Hard-verifies every count
the specification pins down, then writes the immutable gold artifacts and the freeze lock.

Content is NEVER edited during freeze - the approved artifact is copied byte-for-byte and the
copy is re-hashed to prove it.

Run: python freeze_adjudicated_reference.py
Exit 0 = frozen, 1 = refused (nothing written).
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
APPROVED = BASE / "03_validation" / "approved" / "kc_library_expert_adjudicated_reference_APPROVED.jsonl"
RECEIPT = BASE / "03_validation" / "approved" / "human_final_approval_receipt.json"
PREAPPROVAL = BASE / "03_validation" / "adjudicated_input" / "kc_library_expert_curated_adjudicated_final.jsonl"
ADJUDICATION_MD = BASE / "03_validation" / "adjudicated_input" / "kc_reviewer_adjudication.md"
SUMMARY_JSON = BASE / "03_validation" / "adjudicated_input" / "kc_library_expert_curated_adjudicated_final_summary.json"
PROV_SUMMARY = BASE / "04_gold" / "reference_provenance_resolution_summary.json"
PROV_JSONL = BASE / "04_gold" / "reference_provenance_resolution.jsonl"
CORPUS = BASE / "corpus_support" / "sentence_corpus.jsonl"
EVIDENCE_STORE = BASE / "corpus_support" / "evidence_store" / "proposed_evidence_store.jsonl"
CANDIDATE_MANIFEST = BASE / "00_freeze" / "CANDIDATE_FREEZE_MANIFEST.json"
CANDIDATE_LOCK = BASE / "00_freeze" / "candidates_frozen.lock.json"

GOLD = BASE / "04_gold"
OUT_JSONL = GOLD / "expert_adjudicated_reference_kc_library.jsonl"
OUT_MANIFEST = GOLD / "expert_adjudicated_reference_manifest.json"
OUT_LOCK = GOLD / "EXPERT_REFERENCE_FROZEN.lock.json"

EXPECTED_ACTIONS = {"ACCEPT": 117, "MINOR_EDIT": 10, "MAJOR_EDIT": 15, "REPLACE": 10, "NO_REFERENCE_CORPUS_UNSUPPORTED": 7}
EXPECTED_SUPPORT = {"SUPPORTED": 150, "PARTIALLY_SUPPORTED": 2, "UNSUPPORTED": 7}
EXPECTED_N = 159
EXPECTED_CHANGED = 42


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           cwd=str(BASE), timeout=10)
        return r.stdout.strip() or "NOT_A_GIT_REPO"
    except Exception:
        return "NOT_A_GIT_REPO"


def main() -> int:
    refusals: list[str] = []

    if not APPROVED.exists():
        print(f"REFUSED: approved artifact missing ({APPROVED}). Run finalize_adjudicated_reference.py first (PHASE 2).")
        return 1
    if not PROV_SUMMARY.exists():
        print(f"REFUSED: provenance summary missing ({PROV_SUMMARY}). Run validate_reference_provenance_final.py first (PHASE 3).")
        return 1

    prov = json.loads(PROV_SUMMARY.read_text(encoding="utf-8"))
    if prov.get("result") != "PASS":
        refusals.append(f"provenance audit result is {prov.get('result')}, not PASS ({prov.get('n_failures')} failures)")
    if prov.get("n_unresolved", 1) != 0:
        refusals.append(f"provenance audit has {prov.get('n_unresolved')} unresolved source ids")

    receipt = json.loads(RECEIPT.read_text(encoding="utf-8")) if RECEIPT.exists() else {}
    if sha256_file(PREAPPROVAL) != receipt.get("preapproval_sha256"):
        refusals.append("preapproval artifact hash no longer matches the approval receipt - it changed after approval")

    rows = [json.loads(l) for l in open(APPROVED, encoding="utf-8") if l.strip()]

    if len(rows) != EXPECTED_N:
        refusals.append(f"row count {len(rows)} != {EXPECTED_N}")
    ids = [r["knowledge_unit_id"] for r in rows]
    if len(set(ids)) != EXPECTED_N:
        refusals.append(f"unique id count {len(set(ids))} != {EXPECTED_N}")

    actions = dict(Counter(r["review_action"] for r in rows))
    if actions != EXPECTED_ACTIONS:
        refusals.append(f"action counts {actions} != {EXPECTED_ACTIONS}")
    support = dict(Counter(r["support_state"] for r in rows))
    if support != EXPECTED_SUPPORT:
        refusals.append(f"support counts {support} != {EXPECTED_SUPPORT}")

    changed = sum(1 for r in rows if r.get("changed_from_machine_draft"))
    if changed != EXPECTED_CHANGED:
        refusals.append(f"changed_from_machine_draft count {changed} != {EXPECTED_CHANGED}")

    pending = [r["knowledge_unit_id"] for r in rows if r.get("human_final_approval_pending")]
    if pending:
        refusals.append(f"{len(pending)} rows still have human_final_approval_pending=true")
    bad_status = [r["knowledge_unit_id"] for r in rows if r.get("curation_status") != "EXPERT_ADJUDICATED_REFERENCE_FINAL"]
    if bad_status:
        refusals.append(f"{len(bad_status)} rows lack curation_status=EXPERT_ADJUDICATED_REFERENCE_FINAL")

    for r in rows:
        kc = r["knowledge_unit_id"]
        text = (r.get("reference_text") or "").strip()
        if r["support_state"] == "UNSUPPORTED" and text:
            refusals.append(f"{kc}: UNSUPPORTED row carries substantive reference text")
        if r["support_state"] in ("SUPPORTED", "PARTIALLY_SUPPORTED") and not text:
            refusals.append(f"{kc}: {r['support_state']} row has empty reference text")
        if r["review_action"] == "ACCEPT" and (r.get("reference_text") or "") != (r.get("original_machine_draft_text") or ""):
            refusals.append(f"{kc}: ACCEPT row does not exactly preserve its frozen original machine draft")

    # candidate freeze must be intact
    if CANDIDATE_LOCK.exists():
        lock = json.loads(CANDIDATE_LOCK.read_text(encoding="utf-8"))
        actual = sha256_file(CANDIDATE_MANIFEST)
        if actual != lock.get("manifest_sha256"):
            refusals.append(f"candidate freeze manifest hash {actual} != lock {lock.get('manifest_sha256')}")
    else:
        refusals.append("candidate freeze lock missing")

    if refusals:
        print(f"FREEZE REFUSED - {len(refusals)} problem(s), nothing written:")
        for x in refusals:
            print(f"  - {x}")
        return 1

    # ---- write gold artifacts: byte-for-byte copy, then prove it ----
    GOLD.mkdir(parents=True, exist_ok=True)
    approved_bytes = APPROVED.read_bytes()
    OUT_JSONL.write_bytes(approved_bytes)
    if sha256_file(OUT_JSONL) != sha256_file(APPROVED):
        OUT_JSONL.unlink()
        print("FATAL: frozen copy does not match the approved artifact. Output deleted.")
        return 1

    ordered_ids = [r["knowledge_unit_id"] for r in rows]
    ordered_kc_id_hash = hashlib.sha256("\n".join(ordered_ids).encode("utf-8")).hexdigest()
    frozen_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = {
        "schema_version": "expert_adjudicated_reference_manifest_v1",
        "frozen_utc": frozen_utc,
        "kc_count": len(rows),
        "unique_kc_count": len(set(ids)),
        "ordered_kc_id_sha256": ordered_kc_id_hash,
        "reference_jsonl_sha256": sha256_file(OUT_JSONL),
        "approved_artifact_sha256": sha256_file(APPROVED),
        "preapproval_artifact_sha256": sha256_file(PREAPPROVAL),
        "adjudication_document_sha256": sha256_file(ADJUDICATION_MD),
        "adjudication_summary_sha256": sha256_file(SUMMARY_JSON),
        "corpus_snapshot_sha256": sha256_file(CORPUS),
        "source_evidence_store_sha256": sha256_file(EVIDENCE_STORE),
        "candidate_freeze_manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
        "support_state_counts": support,
        "action_counts": actions,
        "changed_from_machine_draft_count": changed,
        "unchanged_accept_count": len(rows) - changed,
        "human_approval": {
            "approved_by": receipt.get("approved_by"),
            "approved_utc": receipt.get("approved_utc"),
            "approval_channel": receipt.get("approval_channel"),
            "approval_channel_meaning": receipt.get("approval_channel_meaning"),
            "approval_note": receipt.get("approval_note"),
        },
        "provenance_validation": {
            "result": prov.get("result"),
            "n_source_citation_instances": prov.get("n_source_citation_instances"),
            "n_distinct_source_ids": prov.get("n_distinct_source_ids"),
            "n_resolved": prov.get("n_resolved"),
            "n_unresolved": prov.get("n_unresolved"),
            "resolution_rate": prov.get("resolution_rate"),
            "resolution_file": PROV_JSONL.name,
        },
        "seed_provenance": {
            "seed_arm": "intrinsic_P-Q",
            "seed_arm_sha256": "6f17d205294a785f488e12b539dc53b68e203e3aa8c86914cb3c7c0c086ab242",
            "identification_method": "exact string comparison of the reference's own original_machine_draft_text against all 7 frozen candidate arms: intrinsic_P-Q matched 159/159 text and 159/159 status; next closest was extrinsic_P-Q at 17/159.",
            "validity_note": "The reference is machine-seeded. It must never be described as independent of Qwen. See 07_methods/THREATS_TO_VALIDITY.md.",
        },
        "git_commit": git_commit(),
        "software_environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    lock = {
        "lock_name": "EXPERT_REFERENCE_FROZEN",
        "frozen_utc": frozen_utc,
        "reference_jsonl": OUT_JSONL.name,
        "reference_jsonl_sha256": manifest["reference_jsonl_sha256"],
        "manifest_sha256": sha256_file(OUT_MANIFEST),
        "ordered_kc_id_sha256": ordered_kc_id_hash,
        "corpus_snapshot_sha256": manifest["corpus_snapshot_sha256"],
        "source_evidence_store_sha256": manifest["source_evidence_store_sha256"],
        "candidate_freeze_manifest_sha256": manifest["candidate_freeze_manifest_sha256"],
        "note": "The production evaluation runner must verify this lock before executing. Reference content is frozen: any change to expert_adjudicated_reference_kc_library.jsonl invalidates this lock and every downstream result.",
    }
    OUT_LOCK.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")

    print("REFERENCE FROZEN")
    print(f"  {OUT_JSONL.name}")
    print(f"     sha256 : {manifest['reference_jsonl_sha256']}")
    print(f"     rows   : {len(rows)} ({len(set(ids))} unique)")
    print(f"  ordered_kc_id_sha256 : {ordered_kc_id_hash}")
    print(f"  corpus_snapshot      : {manifest['corpus_snapshot_sha256']}")
    print(f"  evidence_store       : {manifest['source_evidence_store_sha256']}")
    print(f"  actions : {actions}")
    print(f"  support : {support}")
    print(f"  provenance: {prov.get('n_resolved')}/{prov.get('n_source_citation_instances')} resolved ({prov.get('result')})")
    print(f"  wrote {OUT_MANIFEST.name} and {OUT_LOCK.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
