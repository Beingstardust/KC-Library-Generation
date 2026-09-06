"""Materialize the calibration workbook: fill candidate_draft and candidate_system_evidence from
the frozen arms so annotators actually have something to judge.

The SAMPLE is not touched. Row identities, arm assignment, presentation order, seed and
stratification all come from the existing workbook; this only replaces the two placeholder fields.
Verified row-for-row before writing.

BLINDING: content is joined via the blinded mapping, and the arm's true identity is never written
into the workbook. Every materialized row is scanned for identity-revealing tokens before the file
is written, and the draft's self-reported status (grounded/partial/abstained) is deliberately
dropped - it is a machine-status signal annotators must not see.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import reference_judge_prompts as P  # noqa: E402

CAL = BASE / "output" / "human_calibration"
WB_IN = CAL / "reference_human_calibration_workbook_v2.jsonl"
MAP = CAL / "reference_human_calibration_blinded_mapping.jsonl"
WB_OUT = CAL / "reference_human_calibration_workbook_v2_MATERIALIZED.jsonl"
META = CAL / "calibration_workbook_materialization_metadata.json"

CONTENT = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "output" / "cal_content.json"

SAMPLE_FIELDS = ("review_case_id", "unit_id", "presentation_position", "canonical_name",
                 "hierarchy_path", "expert_reference", "expert_source_citations")

# KC identity is legitimate in a human workbook - the annotator must know which component they are
# assessing. Every other blinding pattern applies.
KC_ID_PATTERN = r"KC_[A-Z]+_[A-Z]+_\d+"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    rows = [json.loads(l) for l in open(WB_IN, encoding="utf-8") if l.strip()]
    mapping = {json.loads(l)["review_case_id"]: json.loads(l)
               for l in open(MAP, encoding="utf-8") if l.strip()}
    content = json.loads(CONTENT.read_text(encoding="utf-8"))["content"]

    out_rows = []
    missing = []
    empty_drafts = 0

    for r in rows:
        m = mapping.get(r["review_case_id"])
        if m is None:
            missing.append(r["review_case_id"])
            continue
        key = f"{r['unit_id']}|{m['arm_true_identity']}"
        c = content.get(key)
        if c is None:
            missing.append(key)
            continue

        n = dict(r)
        draft = (c["draft_text"] or "").strip()
        if not draft:
            empty_drafts += 1
        n["candidate_draft"] = draft
        n["candidate_draft_is_empty"] = not bool(draft)
        n["candidate_system_evidence"] = [
            # opaque ids only; no native evidence id, no retrieval-lane name
            {"id": f"SRC_{i:03d}", "text": e["text"], "document": e.get("doc_id"),
             "page": e.get("page_index"), "section": e.get("section") or ""}
            for i, e in enumerate(c["evidence"])
        ]
        n["n_system_evidence_items"] = len(c["evidence"])
        # deliberately NOT carried over: draft_status_INTERNAL_DO_NOT_SHOW
        out_rows.append(n)

    if missing:
        print(f"REFUSED: {len(missing)} rows could not be matched to content: {missing[:5]}")
        return 1

    # --- sample must be untouched ---
    problems = []
    if len(out_rows) != len(rows):
        problems.append(f"row count changed {len(rows)} -> {len(out_rows)}")
    for a, b in zip(rows, out_rows):
        for f in SAMPLE_FIELDS:
            if json.dumps(a.get(f), sort_keys=True) != json.dumps(b.get(f), sort_keys=True):
                problems.append(f"{a.get('review_case_id')}: sample field {f} changed")
    if problems:
        print(f"REFUSED: the sample would have changed ({len(problems)} problems)")
        for p in problems[:10]:
            print(f"  - {p}")
        return 1

    # --- blinding sweep over the assembled rows, before writing ---
    violations = []
    for n in out_rows:
        blob = json.dumps(n, ensure_ascii=False)
        for pat in P._FORBIDDEN:
            if pat.pattern == KC_ID_PATTERN:
                continue
            hit = pat.search(blob)
            if hit:
                violations.append((n["review_case_id"], pat.pattern, hit.group(0)))
    if violations:
        print(f"REFUSED: {len(violations)} blinding violation(s) in materialized rows")
        for v in violations[:10]:
            print(f"  - {v}")
        return 1

    with open(WB_OUT, "w", encoding="utf-8") as f:
        for n in out_rows:
            f.write(json.dumps(n, ensure_ascii=False) + "\n")

    # arm distribution is computed from the MAPPING, never stored in the workbook
    arm_counts = Counter(mapping[r["review_case_id"]]["arm_true_identity"] for r in out_rows)

    meta = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_workbook": WB_IN.name,
        "source_workbook_sha256": sha(WB_IN),
        "materialized_workbook": WB_OUT.name,
        "materialized_sha256": sha(WB_OUT),
        "n_rows": len(out_rows),
        "n_unique_kc": len({r["unit_id"] for r in out_rows}),
        "n_arms": len(arm_counts),
        "rows_per_arm": dict(arm_counts),
        "n_empty_candidate_drafts": empty_drafts,
        "empty_draft_note": "An empty candidate draft is a real abstention by that system and is "
                             "presented as such. It is not an error and must not be filtered out - "
                             "how a system behaves when it declines to draft is part of what is "
                             "being evaluated.",
        "sample_unchanged": True,
        "sample_verification": "All rows verified field-for-field on review_case_id, unit_id, "
                                "presentation_position, canonical_name, hierarchy_path, "
                                "expert_reference and expert_source_citations.",
        "blinding_verified": "Every materialized row scanned against the full forbidden-pattern set "
                              "(excluding the KC-identity pattern, which is legitimate in a human "
                              "workbook). Zero violations. Native evidence ids replaced with opaque "
                              "SRC_* ids; the draft's self-reported grounded/partial/abstained status "
                              "was deliberately dropped as a machine-status signal.",
        "arm_identity_location": "reference_human_calibration_blinded_mapping.jsonl ONLY",
    }
    META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {WB_OUT.name}")
    print(f"  rows={len(out_rows)} KCs={meta['n_unique_kc']} arms={meta['n_arms']} {dict(arm_counts)}")
    print(f"  empty candidate drafts (genuine abstentions): {empty_drafts}")
    print(f"  sha256: {meta['materialized_sha256'][:16]}...")
    print("  sample unchanged: verified | blinding: zero violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
