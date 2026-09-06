"""Second-judge check: score every extracted claim with MiniCheck-Flan-T5-Large.

MiniCheck is chosen for INDEPENDENCE, not size. It is an encoder-decoder Flan-T5 model, so it shares
no lineage with Selene (Llama-3.3) or with any drafter under test (Qwen, Gemma, DeepSeek) - which
matters because judges favour their own generations, and two judges from one family share failure
modes and would agree for the wrong reason. Its native task, (document, claim) -> supported, IS our
groundedness task, so nothing is coerced into a foreign schema.

Uses the model's own inference code from the downloaded repo rather than a reimplementation: input is
'predict: ' + doc + eos + claim, decoded one step, with logits at positions [3, 209] read as
[no-support, support], and the maximum support probability taken over ~500-word document chunks.

Reliability, not validity: two judges can agree and both be wrong. This tests whether the
groundedness conclusions depend on the choice of judge, nothing more.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minicheck-dir", required=True)
    ap.add_argument("--claims", type=Path, required=True)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    sys.path.insert(0, args.minicheck_dir)
    import nltk
    for pkg in ("punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{pkg}")
        except LookupError:
            nltk.download(pkg, quiet=True)
    from minicheck_web.inference import Inferencer

    rows = {r["eval_row_id"]: r for r in
            (json.loads(l) for l in open(args.rows, encoding="utf-8") if l.strip())}
    claims = [json.loads(l) for l in open(args.claims, encoding="utf-8") if l.strip()]

    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                try:
                    done.add(json.loads(l)["key"])
                except Exception:
                    pass

    todo = [c for c in claims if c.get("claims") and c["key"] not in done]
    total_claims = sum(len(c["claims"]) for c in todo)
    print(f"minicheck: {len(todo)} drafts, {total_claims} claims to score", flush=True)

    inf = Inferencer(path=args.minicheck_dir, max_input_length=512, batch_size=args.batch_size)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(args.out, "a", encoding="utf-8") as fh:
        for c in todo:
            row = rows.get(c["key"])
            if not row:
                continue
            # the same evidence Selene saw, concatenated into one grounding document
            doc = "\n".join((e.get("text") or "").strip()
                            for e in (row.get("candidate_system_evidence") or []))
            rec = {"key": c["key"], "unit_id": c["unit_id"], "arm": c["arm"],
                   "n_claims": len(c["claims"]), "n_evidence": len(row.get("candidate_system_evidence") or [])}
            if not doc.strip():
                # no evidence at all: nothing can be supported, and this is a real state, not an error
                rec["probs"] = [0.0] * len(c["claims"])
                rec["status"] = "NO_EVIDENCE"
            else:
                probs = []
                for cl in c["claims"]:
                    try:
                        o = inf.inference_per_example(doc, cl)
                        probs.append(round(float(o["max_support_prob"]), 6))
                    except Exception as e:
                        probs.append(None)
                        rec.setdefault("errors", []).append(f"{type(e).__name__}: {e}")
                rec["probs"] = probs
                rec["status"] = "OK"
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 50 == 0:
                print(f"[{n}/{len(todo)}]", flush=True)
    print(f"\nminicheck complete: {n} drafts -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
