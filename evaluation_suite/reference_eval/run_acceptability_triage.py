"""Editorial acceptability triage: how much work would each draft need before it could be used?

A post-editing effort scale, as used in MT evaluation (MQM / post-editing levels). This answers the
practical question directly - of N generated descriptions, how many are usable as-is, how many need
a light pass, how many need real work, how many are unusable.

Crucially this is HUMAN-ANCHORED. The expert's own adjudication codes on the 159 seed-arm drafts
(ACCEPT 117 / MINOR_EDIT 10 / MAJOR_EDIT 15 / REPLACE 10) are exactly this scale, assigned by a
person against the corpus. Judge agreement with those codes is measurable, so the metric is
validated rather than asserted.

Judged against the draft's own retrieved evidence, never against the expert reference, so the
seed-provenance question does not arise.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import reference_judge_prompts as P   # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

_lock = threading.Lock()
LEVELS = ["USABLE_AS_IS", "MINOR_EDIT", "MAJOR_EDIT", "UNUSABLE"]


def schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["task", "level"],
        "properties": {
            "task": {"type": "string", "enum": ["ACCEPTABILITY_TRIAGE"]},
            "level": {"type": "string", "enum": LEVELS},
            "rationale": {"type": "string", "maxLength": 300, "pattern": r"^[^\r\n]*$"},
        },
    }


def build_prompt(canonical: str, hierarchy: str, evidence: str, draft: str) -> str:
    p = f"""You are triaging a machine-written description of a course concept, deciding how much editing it would need before a lecturer could use it.

CONCEPT: {canonical}
LOCATION IN SYLLABUS: {hierarchy}

SOURCE PASSAGES AVAILABLE:
{evidence}

DESCRIPTION:
{draft.strip}

TASK
Judge how much work this description needs before it could be published to students:

  USABLE_AS_IS - correct and adequately complete. A reviewer would accept it unchanged.
  MINOR_EDIT   - substantively right, but needs small fixes: a clumsy phrase, a missing minor
                 detail, an imprecise wording. Under a couple of minutes of work.
  MAJOR_EDIT   - the description is on the right topic but a reviewer would have to rewrite or add
                 substantial content: a defining element is missing, or something is stated wrongly.
  UNUSABLE     - it would be faster to write from scratch: wrong concept, or not supported by the
                 source passages at all.

Judge against the SOURCE PASSAGES, not against your own knowledge of the subject. Do not reward
length - a short description that says the right things is USABLE_AS_IS.

Return JSON with "task": "ACCEPTABILITY_TRIAGE" and a "level"."""
    P.assert_blinded(p)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]
    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass
    todo = [r for r in rows if r["eval_row_id"] not in done]
    print(f"triage: {len(todo)} todo", flush=True)

    def work(row):
        rid = row["eval_row_id"]
        rec = {"key": rid, "unit_id": row["unit_id"], "arm": row["arm"]}
        draft = (row.get("candidate_draft") or "").strip()
        if not draft:
            # an abstention is not an editing level - it is a different behaviour entirely
            rec["status"] = "ABSTENTION_NO_DRAFT"
            rec["level"] = None
            return rec
        items = [{"native_id": e["id"], "text": e["text"]}
                 for e in row.get("candidate_system_evidence") or []]
        blk, _ = P.render_evidence(items, "SRC")
        out = call_and_validate(
            args.base_url, args.model, f"{rid}:TRIAGE",
            build_prompt(row.get("canonical_name") or "",
                         " > ".join(row.get("hierarchy_path") or []), blk, draft),
            schema(), lambda r: r.get("level") in LEVELS, max_tokens=500)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["level"] = out["response"]["level"]
        return rec

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n, fails = 0, 0
    with open(args.out, "a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(work, t): t for t in todo}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as e:
                rec = {"key": futs[fut]["eval_row_id"], "error": f"{type(e).__name__}: {e}"}
            with _lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            n += 1
            fails = fails + 1 if ("CALL_FAILED" in str(rec.get("status", "")) or "error" in rec) else 0
            if fails >= 15:
                print(f"ABORTING: {fails} consecutive failures. {n}/{len(todo)} done.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 100 == 0:
                print(f"[{n}/{len(todo)}]", flush=True)
    print(f"\ntriage complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
