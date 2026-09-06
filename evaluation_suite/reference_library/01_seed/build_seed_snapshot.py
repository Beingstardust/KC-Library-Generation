"""One-shot: freeze the designated Qwen seed (extrinsic P-Q, see 00_freeze/CANDIDATE_FREEZE_MANIFEST.json
seed_source_designation) into the immutable per-KC seed store the curation console reads from.

Run once. Output files (qwen_seed.jsonl, qwen_seed_manifest.json) are never overwritten by the
console - the console only reads them. Re-running this script after curation has started would
violate the freeze; it is intentionally not wired into any other tool's import path.
"""
import hashlib
import json

SRC = "_source_qwen_draft_raw.jsonl"
OUT_JSONL = "qwen_seed.jsonl"
OUT_MANIFEST = "qwen_seed_manifest.json"

EXPECTED_SOURCE_SHA256 = "42e15cd17885ea1416eedfaeff3769cfec9fbd4a0ba36d2fd5bc6a32b61b88c1"


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main() -> None:
    with open(SRC, "rb") as fb:
        src_hash = hashlib.sha256(fb.read()).hexdigest()
    if src_hash != EXPECTED_SOURCE_SHA256:
        raise SystemExit(
            f"REFUSING TO BUILD SEED: {SRC} sha256={src_hash} does not match the frozen "
            f"extrinsic P-Q hash recorded in CANDIDATE_FREEZE_MANIFEST.json ({EXPECTED_SOURCE_SHA256}). "
            "The seed must be built from the exact frozen candidate artifact."
        )

    seed_rows = []
    status_counts = {"grounded": 0, "partial": 0, "abstained": 0, "technical_failure": 0}

    with open(SRC, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kc_id = row["knowledge_unit_id"]
            canonical_name = row["canonical_name"]
            source_packet = row.get("source_packet") or {}
            hierarchy = source_packet.get("hierarchy") or {}
            hierarchy_path = hierarchy.get("topic_path") or hierarchy.get("source_hierarchy_path") or []

            draft = row.get("draft")
            if draft is None:
                # preserved hard failure (KC_CLF_UND_006: unparseable_raw_response) - not hand-repaired,
                # not silently skipped either. seed_status makes the technical failure visible in-console.
                seed_status = "TECHNICAL_FAILURE_NO_DRAFT"
                seed_body = ""
                evidence_ids = []
                status_counts["technical_failure"] += 1
            else:
                ckd = draft["contextual_kc_draft"]
                seed_status = ckd.get("status", "")
                seed_body = ckd.get("text") or ""
                evidence_ids = ckd.get("supporting_evidence_ids") or []
                status_counts[seed_status] = status_counts.get(seed_status, 0) + 1

            seed_rows.append({
                "kc_id": kc_id,
                "canonical_name": canonical_name,
                "hierarchy_path": hierarchy_path,
                "seed_status": seed_status,
                "seed_body": seed_body,
                "seed_evidence_ids_audit_only": evidence_ids,
                "seed_sha256": sha256_text(seed_body),
            })

    seed_rows.sort(key=lambda r: r["kc_id"])
    kc_ids = [r["kc_id"] for r in seed_rows]
    if len(kc_ids) != 159 or len(set(kc_ids)) != 159:
        raise SystemExit(f"REFUSING TO BUILD SEED: expected exactly 159 unique kc_id, got {len(kc_ids)} rows / {len(set(kc_ids))} unique")

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in seed_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(OUT_JSONL, "rb") as fb:
        out_hash = hashlib.sha256(fb.read()).hexdigest()

    manifest = {
        "generated_utc": "2026-08-24T11:15:00Z",
        "source_file": SRC,
        "source_sha256_verified_against_freeze_manifest": src_hash,
        "source_seed_arm": "extrinsic P-Q (r9final_ext_proposed_ctrl_20260823T140000Z, commit 450c88c, controlled_comparator) - see 00_freeze/CANDIDATE_FREEZE_MANIFEST.json seed_source_designation",
        "output_file": OUT_JSONL,
        "output_sha256": out_hash,
        "n_kc": len(seed_rows),
        "status_counts": status_counts,
        "immutability_note": "This file is never edited in place after generation. The curation console (02_curation/reference_console.py) opens it read-only. If build_seed_snapshot.py is ever re-run, the resulting qwen_seed.jsonl sha256 must be compared against this manifest's output_sha256 before any console session trusts it - a mismatch means the seed changed after curation may have started, which must be treated as a protocol violation and investigated, not silently accepted.",
    }
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"wrote {OUT_JSONL} ({len(seed_rows)} KCs, sha256={out_hash})")
    print(f"wrote {OUT_MANIFEST}")
    print("status_counts:", status_counts)


if __name__ == "__main__":
    main()
