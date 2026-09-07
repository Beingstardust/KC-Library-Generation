"""Build a BLANK seed-blind reconstruction worksheet (round 2).

Round 1 (`reviewer_c_worksheet.jsonl`) is unusable as a worksheet for two reasons, both
recorded rather than quietly fixed:

  1. It shipped PRE-FILLED. Every one of its 30 entries carried reference_text,
     support_state and source_passages, which the protocol's own section 2 forbids
     ("You are not given a pre-selected passage set... Finding the relevant material is
     part of your task"). It is in fact the completed OUTPUT, misfiled under the
     worksheet name; its texts match the comparison file's blind_words exactly.
  2. None of its 30 reconstructions met the 100-250 word spec (median 22, max 45).

This builder emits a genuinely blank worksheet over a FRESH stratified sample drawn from
the units the round-1 reviewer never saw, so the same person can serve again without the
audit losing blindness.

Reads only the frozen gold library. Writes a worksheet plus a separate stratum key that
must never be shown to the reviewer.
"""
from __future__ import annotations
import json, pathlib, random, collections

HERE = pathlib.Path(__file__).resolve().parent
GOLD = HERE.parent / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
ROUND1 = HERE / "reviewer_c_worksheet.jsonl"
OUT_WORKSHEET = HERE / "reviewer_d_worksheet.jsonl"
OUT_KEY = HERE / "reviewer_d_stratum_key_DO_NOT_SHOW_REVIEWER.json"

SEED = 20260819
QUOTA = {"ACCEPT": 18, "CHANGED": 9, "UNSUPPORTED": 3}

CHANGED_ACTIONS = {"MINOR_EDIT", "MAJOR_EDIT", "REPLACE"}


def stratum_of(row: dict) -> str:
    action = row.get("review_action")
    if action == "NO_REFERENCE_CORPUS_UNSUPPORTED":
        return "UNSUPPORTED"
    if action in CHANGED_ACTIONS:
        return "CHANGED"
    if action == "ACCEPT":
        return "ACCEPT"
    raise ValueError("unrecognised review_action: %r" % (action,))


def main() -> int:
    gold = [json.loads(l) for l in GOLD.open(encoding="utf-8") if l.strip()]
    seen_round1 = {e["knowledge_unit_id"]
                   for e in json.loads(ROUND1.read_text(encoding="utf-8"))}

    pool = collections.defaultdict(list)
    for row in gold:
        if row["knowledge_unit_id"] in seen_round1:
            continue                      # reviewer already wrote this one; not blind
        pool[stratum_of(row)].append(row)

    print("round-1 units excluded : %d" % len(seen_round1))
    for s in ("ACCEPT", "CHANGED", "UNSUPPORTED"):
        print("  pool[%-11s] = %3d   (need %d)" % (s, len(pool[s]), QUOTA[s]))

    short = {s: QUOTA[s] - len(pool[s]) for s in QUOTA if len(pool[s]) < QUOTA[s]}
    if short:
        print("\nFATAL: insufficient unseen units for strata %r" % short)
        return 2

    rng = random.Random(SEED)
    selected = []
    for s in ("ACCEPT", "CHANGED", "UNSUPPORTED"):
        picked = rng.sample(sorted(pool[s], key=lambda r: r["knowledge_unit_id"]), QUOTA[s])
        for row in picked:
            selected.append((s, row))
    rng.shuffle(selected)                 # strata must not be inferable from order

    worksheet = []
    key = {}
    for i, (stratum, row) in enumerate(selected, 1):
        kc = row["knowledge_unit_id"]
        h = row.get("hierarchy") or {}
        path = h.get("source_hierarchy_path") or h.get("topic_path") or []
        # the stored path can repeat the leaf label; collapse consecutive duplicates
        path = [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]
        worksheet.append({
            "order": i,
            "knowledge_unit_id": kc,
            "canonical_name": row.get("canonical_name"),
            "hierarchy": " > ".join(str(x) for x in path),
            # --- everything below is YOURS to fill in. Left deliberately empty. ---
            "reviewer": "D",
            "support_state": "",          # SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED
            "source_passages": [],        # {document, locator, quote, supports:[...]}
            "reference_text": "",         # 100-250 words, prose, corpus-only
            "unsupported_reason": None,
            "time_minutes": None,
            "notes": "",
        })
        key[kc] = stratum

    OUT_WORKSHEET.write_text(json.dumps(worksheet, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    OUT_KEY.write_text(json.dumps({
        "seed": SEED,
        "quota": QUOTA,
        "round": 2,
        "excluded_round1_units": sorted(seen_round1),
        "note": "Stratum assignment for analysis only. Reviewer D must never see this file.",
        "strata": key,
    }, indent=2) + "\n", encoding="utf-8")

    print("\nwrote %s (%d blank entries)" % (OUT_WORKSHEET.name, len(worksheet)))
    print("wrote %s" % OUT_KEY.name)
    print("blank-check: any entry carrying prefilled content? %s"
          % ("YES - ABORT" if any(e["reference_text"] or e["support_state"] or e["source_passages"]
                                 for e in worksheet) else "no"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
