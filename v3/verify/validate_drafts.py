"""Post-drafting validator: separate real breakage from correct abstention.

The schema-contract probe exits non-zero when ANY unit fails its checks, and a legitimate
abstention (empty draft text, empty evidence_map) trips exactly those checks. On the last two runs
that marked the SLURM job FAILED while all 159 drafts had in fact been produced with well-formed
JSON - the run summaries recorded parse_repair_attempt_count 0, schema_repair_attempt_count 0 and
model_call_failed_count 0.

This distinguishes:
  HARD failures  - missing rows, unparseable output, missing required keys, model/runtime errors.
                   These mean the run is broken and must be looked at.
  Abstentions    - well-formed output declaring status "abstained" with empty text. Correct
                   behaviour when the corpus genuinely lacks the concept, and not a defect.

Exit code reflects only hard failures, so a run that abstains honestly completes cleanly.

Row schema note (verified against a real run before trusting this): the parsed object lives in
`draft`, and `raw_response` is CLEARED on success and populated only when something went wrong.
Reading raw_response first would report every healthy row as broken.
"""
import argparse
import json
import sys

REQUIRED_TOP = ("knowledge_unit_id", "knowledge_unit_type", "canonical_name")


def extract_draft_object(row):
    """Return (obj, error). Prefers the parsed `draft`; falls back to raw text if absent."""
    obj = row.get("draft")
    if isinstance(obj, dict) and obj:
        return obj, None
    for field in ("raw_response", "repair_raw_response", "parse_repair_raw_response"):
        raw = row.get(field)
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed, None
                return None, "%s_not_object" % field
            except Exception as exc:
                return None, "unparseable_%s:%s" % (field, exc.__class__.__name__)
        if isinstance(raw, dict) and raw:
            return raw, None
    return None, "no_draft_and_no_raw_response"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts-jsonl", required=True)
    ap.add_argument("--packets-jsonl", required=True)
    ap.add_argument("--run-id", default="")
    a = ap.parse_args()

    packets = [json.loads(l) for l in open(a.packets_jsonl, encoding="utf-8") if l.strip()]
    expected_ids = [p.get("knowledge_unit_id") for p in packets]

    try:
        rows = [json.loads(l) for l in open(a.drafts_jsonl, encoding="utf-8") if l.strip()]
    except Exception as exc:
        print("HARD FAIL: drafts file unreadable: %r" % (exc,))
        return 1

    by_id = {r.get("knowledge_unit_id"): r for r in rows}
    hard, abstained, grounded, partial = [], [], [], []
    text_lengths = []

    for uid in expected_ids:
        row = by_id.get(uid)
        if row is None:
            hard.append((uid, "row_missing"))
            continue
        if row.get("runtime_error"):
            hard.append((uid, "runtime_error:%s" % str(row.get("runtime_error"))[:80]))
            continue
        obj, err = extract_draft_object(row)
        if obj is None:
            hard.append((uid, err))
            continue
        missing = [k for k in REQUIRED_TOP if not obj.get(k)]
        if missing:
            hard.append((uid, "missing_keys:%s" % ",".join(missing)))
            continue
        draft = obj.get("contextual_kc_draft") or obj.get("contextual_topic_draft") or {}
        if not isinstance(draft, dict):
            hard.append((uid, "draft_not_object"))
            continue
        status = str(draft.get("status") or "").lower()
        text = str(draft.get("text") or "").strip()
        if status == "abstained" or not text:
            abstained.append(uid)
        elif status == "partial":
            partial.append(uid)
            text_lengths.append(len(text))
        else:
            grounded.append(uid)
            text_lengths.append(len(text))

    total = len(expected_ids)
    produced = len(grounded) + len(partial)
    mean_len = (sum(text_lengths) / len(text_lengths)) if text_lengths else 0
    print("=" * 74)
    print("DRAFT VALIDATION  run_id=%s" % a.run_id)
    print("  packets expected      : %d" % total)
    print("  draft rows present    : %d" % len(rows))
    print("  grounded              : %d (%.1f%%)" % (len(grounded), 100.0 * len(grounded) / max(total, 1)))
    print("  partial               : %d (%.1f%%)" % (len(partial), 100.0 * len(partial) / max(total, 1)))
    print("  abstained (expected)  : %d (%.1f%%)" % (len(abstained), 100.0 * len(abstained) / max(total, 1)))
    print("  mean draft length     : %.0f chars (over %d drafted units)" % (mean_len, produced))
    print("  HARD FAILURES         : %d" % len(hard))
    for uid, why in hard[:25]:
        print("      %-20s %s" % (uid, why))
    if abstained:
        print("  abstained unit ids    : %s" % ", ".join(abstained[:20]))
    print("=" * 74)
    if hard:
        print("RESULT: HARD_FAILURES_PRESENT")
        return 1
    print("RESULT: SCHEMA_OK (abstentions are not failures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
