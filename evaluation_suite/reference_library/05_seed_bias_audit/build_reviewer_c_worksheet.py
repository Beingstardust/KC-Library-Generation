"""Build the seed-blind reconstruction worksheet for Reviewer C (control 6).

Stratifies on Reviewer A's action codes so the audit can separate "the seed shaped the content"
from "the expert simply edited the weaker drafts" - but the reviewer is never told the stratum, and
the worksheet carries NOTHING except the KC identity and its place in the hierarchy.

The leak check at the end is not decoration. A worksheet that accidentally carries reference text or
a machine draft would void the audit, and the failure would be invisible afterwards.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

BASE = Path(__file__).parent
LIB = BASE.parent / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
OUT = BASE / "reviewer_c_worksheet.jsonl"
KEY = BASE / "reviewer_c_stratum_key_DO_NOT_SHOW_REVIEWER.json"
SEED = 20260901
QUOTA = {"ACCEPT": 18, "CHANGED": 9, "UNSUPPORTED": 3}

# fields that must never reach the reviewer
FORBIDDEN_FIELDS = {
    "reference_text", "reference_display_text", "original_machine_draft_text",
    "original_machine_draft_status", "review_action", "reason_codes",
    "adjudication_reason", "support_state", "source_evidence_ids", "full_source_refs",
    "source_limitations", "curation_status",
}


def stratum(rec: dict) -> str | None:
    if rec.get("support_state") == "UNSUPPORTED":
        return "UNSUPPORTED"
    act = rec.get("review_action")
    if act == "ACCEPT":
        return "ACCEPT"
    if act in ("MINOR_EDIT", "MAJOR_EDIT", "REPLACE"):
        return "CHANGED"
    return None


def main() -> int:
    lib = [json.loads(l) for l in open(LIB, encoding="utf-8") if l.strip()]
    buckets: dict[str, list] = {"ACCEPT": [], "CHANGED": [], "UNSUPPORTED": []}
    for r in lib:
        s = stratum(r)
        if s:
            buckets[s].append(r)

    rng = random.Random(SEED)
    picked = []
    for s, n in QUOTA.items():
        pool = sorted(buckets[s], key=lambda r: r["knowledge_unit_id"])
        if len(pool) < n:
            sys.exit(f"REFUSED: stratum {s} has {len(pool)} KCs, need {n}")
        picked += [(s, r) for r in rng.sample(pool, n)]

    # randomise presentation order so the stratum is not inferable from position
    rng.shuffle(picked)

    rows = []
    for i, (_s, r) in enumerate(picked, 1):
        h = r.get("hierarchy")
        if isinstance(h, dict):
            path = h.get("topic_path") or h.get("source_hierarchy_path") or []
        elif isinstance(h, list):
            path = h
        else:
            path = [str(h)] if h else []
        rows.append({
            "order": i,
            "knowledge_unit_id": r["knowledge_unit_id"],
            "canonical_name": r["canonical_name"],
            "hierarchy": " > ".join(str(x) for x in path),
            # everything the reviewer fills in, left empty on purpose
            "support_state": None,
            "source_passages": [],
            "reference_text": "",
            "unsupported_reason": None,
            "time_minutes": None,
            "notes": "",
        })

    # ---- leak check: no worksheet row may carry any content-bearing field ----
    lib_by_id = {r["knowledge_unit_id"]: r for r in lib}
    leaked = []
    for row in rows:
        src = lib_by_id[row["knowledge_unit_id"]]
        blob = json.dumps(row, ensure_ascii=False).lower()
        for f in FORBIDDEN_FIELDS:
            v = src.get(f)
            if isinstance(v, str) and len(v.strip()) > 40 and v.strip()[:40].lower() in blob:
                leaked.append((row["knowledge_unit_id"], f))
    if leaked:
        sys.exit(f"REFUSED: worksheet would leak {leaked[:5]}")

    empty_answer_fields = all(
        not r["reference_text"] and r["support_state"] is None and not r["source_passages"]
        for r in rows)
    if not empty_answer_fields:
        sys.exit("REFUSED: answer fields are not empty")

    with open(OUT, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # the stratum key is written SEPARATELY and must not be given to the reviewer
    KEY.write_text(json.dumps({
        "seed": SEED,
        "quota": QUOTA,
        "note": "Stratum assignment for analysis only. Reviewer C must never see this file.",
        "strata": {r["knowledge_unit_id"]: s for s, r in picked},
    }, indent=2), encoding="utf-8")

    print(f"worksheet: {len(rows)} KCs -> {OUT.name}")
    print(f"strata (key withheld from reviewer): "
          f"{ {s: sum(1 for x, _ in picked if x == s) for s in QUOTA} }")
    print("leak check: PASSED - worksheet carries only id, name, hierarchy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
