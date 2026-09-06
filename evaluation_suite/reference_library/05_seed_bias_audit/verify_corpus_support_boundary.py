"""Verify the three disputed corpus-support units directly against the course corpus.

Reviewer C recorded all three UNSUPPORTED-stratum units as `supported` and wrote a definition for
each, contrary to step 2 of SEED_BLIND_RECONSTRUCTION_INSTRUCTIONS.md. This script re-derives the
evidence used to resolve that disagreement in SEED_ANCHORING_AUDIT.md §4.

Read-only. Touches no artifact. Run from anywhere:

    python verify_corpus_support_boundary.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CORPUS = BASE.parent / "corpus_support" / "sentence_corpus.jsonl"
WORKSHEET = BASE / "reviewer_c_worksheet.jsonl"

# The three units the adjudicated reference labels NO_REFERENCE_CORPUS_UNSUPPORTED
# and that the seed-blind reviewer recorded as supported.
DISPUTED = {
    "KC_EVAL_COMP_001": ("McNemar Test",
                         ["mcnemar", "paired nominal", "significantly different error rate"]),
    "KC_EVAL_BASIC_007": ("RMSE for Ordinal Targets",
                          ["rmse", "root mean square error", "root mean squared error"]),
    "KC_CLF_UND_005": ("Mutually Exclusive Classes",
                       ["mutually exclusive", "one and only one", "exactly one class",
                        "single label", "single-label"]),
}

norm = lambda s: re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
squash = lambda s: re.sub(r"\s+", " ", norm(s)).strip()


def load_corpus() -> list[tuple[str, object, str, str]]:
    rows = []
    with open(CORPUS, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                d = json.loads(line)
                rows.append((d.get("doc_id", ""), d.get("page_index"),
                             d.get("sentence_text") or "", d.get("source_block_text") or ""))
    return rows


def main() -> int:
    if not CORPUS.exists():
        sys.exit(f"corpus not found: {CORPUS}")
    rows = load_corpus()
    print(f"corpus sentences: {len(rows)}\n")

    print("=" * 78)
    print("1. Term presence for each disputed unit")
    print("=" * 78)
    for kc, (name, terms) in DISPUTED.items():
        print(f"\n{kc}  {name}")
        for t in terms:
            n = sum(1 for _, _, s, b in rows if t in (s + " " + b).lower())
            print(f"    {t!r:42s} {n:5d} sentence(s)")

    print("\n" + "=" * 78)
    print("2. Does RMSE ever co-occur with an ordinal/ranked target?")
    print("=" * 78)
    co = [(d, p, b or s) for d, p, s, b in rows
          if re.search(r"rmse|root mean square", s + " " + b, re.I)
          and re.search(r"ordinal|ranked|rank-order", s + " " + b, re.I)]
    print(f"co-occurring sentences: {len(co)}")
    docs = {d for d, _, s, b in rows if re.search(r"rmse|root mean square", s + " " + b, re.I)}
    print(f"documents mentioning RMSE at all: {sorted(docs)}")

    print("\n" + "=" * 78)
    print("3. Is any 'mutually exclusive' occurrence about CLASSES rather than RULES?")
    print("=" * 78)
    seen, uniq = set(), []
    for d, p, s, b in rows:
        if "mutually exclusive" in (s + " " + b).lower():
            k = re.sub(r"[\s.]{3,}", " ", re.sub(r"\s+", " ", b or s)).strip()[:160]
            if k not in seen:
                seen.add(k)
                uniq.append((p, k))
    print(f"unique contexts: {len(uniq)}")
    for p, k in uniq:
        tag = ("RULE" if re.search(r"rule", k, re.I)
               else "CLASS" if re.search(r"\bclass|label|categor", k, re.I) else "-")
        print(f"  [{tag:5s}] p{p} {k[:150]}")

    print("\n" + "=" * 78)
    print("4. Do the reviewer's recorded passages occur in the corpus?")
    print("=" * 78)
    if WORKSHEET.exists():
        raw = WORKSHEET.read_text(encoding="utf-8").strip()
        ws = json.loads(raw) if raw.startswith("[") else [
            json.loads(l) for l in raw.splitlines() if l.strip()]
        joined = " ".join(squash(s) for _, _, s, _ in rows)
        for r in ws:
            if r["knowledge_unit_id"] in DISPUTED:
                for p in (r.get("source_passages") or []):
                    q = squash(p if isinstance(p, str) else (p.get("quote") or ""))
                    print(f"  {'FOUND ' if q and q in joined else 'ABSENT'}  "
                          f"{r['knowledge_unit_id']}: {(p if isinstance(p, str) else '')[:96]}")
    else:
        print(f"  worksheet not found: {WORKSHEET}")

    print("\nExpected outcome (SEED_ANCHORING_AUDIT.md §4): all three adjudications upheld.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
