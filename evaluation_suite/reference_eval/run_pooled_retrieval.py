"""Pooled relevance judgements for the extrinsic retrieval comparison (TREC methodology).

Each pooled passage is judged INDIVIDUALLY against the KC. That is the whole point: the judge never
sees a long passage list, so the serial-position failure measured in F-45 - which made context recall
uninterpretable for large-budget systems - cannot occur here.

The pool is the union of the top-k passages from every arm, so no single system defines the ground
truth. Measured: the four Proposed-lineage arms contribute ZERO passages unique to them, so the pool
cannot be accused of being Proposed's own output.

Unjudged passages count as non-relevant, per standard practice. Pool bias is the known limitation
(Buckley et al. 2007) and is disclosed rather than corrected.
"""
from __future__ import annotations

import argparse
import hashlib
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

GRADES = ["NOT_RELEVANT", "RELATED", "DEFINITIONAL"]


def passage_id(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def schema() -> dict:
    """Verdict first, rationale optional, oneOf-free - the F-02/F-03 lessons apply here too."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["task", "grade"],
        "properties": {
            "task": {"type": "string", "enum": ["PASSAGE_RELEVANCE"]},
            "grade": {"type": "string", "enum": GRADES},
            "rationale": {"type": "string", "maxLength": 300, "pattern": r"^[^\r\n]*$"},
        },
    }


def build_prompt(canonical: str, hierarchy: str, passage: str) -> str:
    p = f"""You are judging whether a single source passage is useful for writing an explanatory description of one course concept.

CONCEPT: {canonical}
LOCATION IN SYLLABUS: {hierarchy}

PASSAGE:
{passage.strip}

TASK
Judge THIS PASSAGE ALONE. Decide how useful it is for writing a description of the concept above:

  DEFINITIONAL - the passage states what the concept IS, or gives a mechanism, formula, property or
                 contrast that a correct description would need. Someone writing the description
                 would draw on this passage directly.
  RELATED      - the passage is about the right topic area and provides useful context, but does not
                 carry defining content for this specific concept.
  NOT_RELEVANT - the passage does not help describe this concept.

Judge only this passage's usefulness for this concept. Do not speculate about what other passages
might contain, and do not reward a passage for being well written.

Return JSON with "task": "PASSAGE_RELEVANCE" and a "grade"."""
    P.assert_blinded(p)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--depth", type=int, default=20, help="pool depth per arm")
    ap.add_argument("--concurrency", type=int, default=1)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip()]

    # pool: union of each arm's top-`depth` passages, per KC
    pool: dict[str, dict[str, str]] = {}
    meta: dict[str, dict] = {}
    for r in rows:
        kc = r["unit_id"]
        pool.setdefault(kc, {})
        meta.setdefault(kc, {"canonical_name": r.get("canonical_name") or "",
                             "hierarchy": " > ".join(r.get("hierarchy_path") or [])})
        for e in (r.get("candidate_system_evidence") or [])[: args.depth]:
            t = (e.get("text") or "").strip()
            if t:
                pool[kc][passage_id(t)] = t

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass

    todo = [(f"{kc}|{pid}", kc, pid, txt)
            for kc, ps in sorted(pool.items())
            for pid, txt in sorted(ps.items())
            if f"{kc}|{pid}" not in done]
    print(f"pool: {len(pool)} KCs, {sum(len(v) for v in pool.values())} passages "
          f"(depth {args.depth}); {len(todo)} todo", flush=True)

    def work(item):
        key, kc, pid, txt = item
        m = meta[kc]
        rec = {"key": key, "unit_id": kc, "passage_id": pid, "n_words": len(txt.split())}
        out = call_and_validate(
            args.base_url, args.model, f"{key}:POOL",
            build_prompt(m["canonical_name"], m["hierarchy"], txt), schema(),
            lambda r: r.get("grade") in GRADES, max_tokens=400)
        rec["status"] = out["status"]
        if out.get("contract_valid"):
            rec["grade"] = out["response"]["grade"]
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
                rec = {"key": futs[fut][0], "error": f"{type(e).__name__}: {e}"}
            with _lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            n += 1
            fails = fails + 1 if ("CALL_FAILED" in str(rec.get("status", "")) or "error" in rec) else 0
            if fails >= 15:
                print(f"ABORTING: {fails} consecutive failures - server likely gone. "
                      f"{n}/{len(todo)} done; re-run to resume.", flush=True)
                for f in futs:
                    f.cancel()
                break
            if n % 200 == 0:
                print(f"[{n}/{len(todo)}]", flush=True)
    print(f"\npooled judgements complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
