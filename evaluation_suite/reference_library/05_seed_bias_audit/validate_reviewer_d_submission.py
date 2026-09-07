"""Validate a Reviewer D seed-blind reconstruction submission before it is accepted.

Round 1 failed on things a script would have caught in a second: output written into the
worksheet file, and 30/30 entries below the word floor. This checks all of it mechanically.

Usage:
    python validate_reviewer_d_submission.py [path/to/reviewer_d.jsonl]

Exits 0 if the submission is acceptable, non-zero otherwise.
"""
from __future__ import annotations
import json, pathlib, re, sys, collections

HERE = pathlib.Path(__file__).resolve().parent
WORKSHEET = HERE / "reviewer_d_worksheet.jsonl"
DEFAULT_SUBMISSION = HERE / "independent_references" / "reviewer_d.jsonl"
GOLD = HERE.parent / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"

MIN_WORDS, MAX_WORDS = 100, 250
VALID_STATES = {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED"}
OVERLAP_ALERT = 0.35          # 8-gram Jaccard against the existing library

problems: list[str] = []
warnings: list[str] = []


def fail(unit: str, msg: str) -> None:
    problems.append("%-22s %s" % (unit, msg))


def warn(unit: str, msg: str) -> None:
    warnings.append("%-22s %s" % (unit, msg))


def words(text: str) -> int:
    return len((text or "").split())


def shingles(text: str, n: int = 8) -> set:
    w = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def load_jsonl(path: pathlib.Path) -> list:
    rows, raw = [], path.read_text(encoding="utf-8").strip()
    if raw.startswith("["):
        raise SystemExit(
            "FATAL: %s is a JSON array. The submission must be JSONL — one object per line.\n"
            "       (This is exactly how round 1 went wrong.)" % path.name)
    for i, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit("FATAL: %s line %d is not valid JSON: %s" % (path.name, i, e))
    return rows


def main() -> int:
    sub_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SUBMISSION
    if not sub_path.exists():
        raise SystemExit("FATAL: submission not found: %s\n"
                         "       Create it; do NOT edit the worksheet." % sub_path)

    expected = {e["knowledge_unit_id"] for e in
                json.loads(WORKSHEET.read_text(encoding="utf-8"))}
    rows = load_jsonl(sub_path)

    # --- worksheet must be untouched --------------------------------------------------
    ws = json.loads(WORKSHEET.read_text(encoding="utf-8"))
    if any(e.get("reference_text") or e.get("support_state") or e.get("source_passages")
           for e in ws):
        problems.append("%-22s %s" % ("(worksheet)",
                        "worksheet has been filled in — it is INPUT ONLY and must stay blank"))

    # --- coverage ---------------------------------------------------------------------
    got = [r.get("knowledge_unit_id") for r in rows]
    dupes = [k for k, n in collections.Counter(got).items() if n > 1]
    missing = sorted(expected - set(got))
    extra = sorted(set(got) - expected)
    if len(rows) != len(expected):
        problems.append("%-22s submitted %d entries, expected %d"
                        % ("(coverage)", len(rows), len(expected)))
    for k in missing:
        fail(k, "MISSING from submission")
    for k in extra:
        fail(k, "not in the assigned worksheet")
    for k in dupes:
        fail(k, "appears more than once")

    # --- contamination check ----------------------------------------------------------
    gold = {}
    if GOLD.exists():
        for line in GOLD.open(encoding="utf-8"):
            if line.strip():
                g = json.loads(line)
                gold[g["knowledge_unit_id"]] = g.get("reference_text") or ""

    # --- per-entry --------------------------------------------------------------------
    for r in rows:
        kc = r.get("knowledge_unit_id", "(no id)")
        state = (r.get("support_state") or "").strip()
        text = (r.get("reference_text") or "").strip()
        reason = (r.get("unsupported_reason") or "")
        notes = (r.get("notes") or "").strip()
        passages = r.get("source_passages") or []
        n = words(text)

        if state not in VALID_STATES:
            fail(kc, "support_state %r not one of %s" % (state, sorted(VALID_STATES)))
            continue

        if state == "UNSUPPORTED":
            if text:
                fail(kc, "UNSUPPORTED but reference_text is non-empty (%d words) — "
                         "do not write from own knowledge" % n)
            if not str(reason).strip():
                fail(kc, "UNSUPPORTED requires unsupported_reason")
        else:
            if not text:
                fail(kc, "%s but reference_text is empty" % state)
                continue
            if re.search(r"^\s*[-*•]\s+", text, re.M):
                fail(kc, "reference_text contains bullet list formatting; prose required")
            if n > MAX_WORDS:
                fail(kc, "reference_text %d words, over the %d limit" % (n, MAX_WORDS))
            elif n < MIN_WORDS:
                if state == "PARTIALLY_SUPPORTED" and notes:
                    warn(kc, "%d words (under %d) — allowed for PARTIALLY_SUPPORTED "
                             "because notes explain the shortfall" % (n, MIN_WORDS))
                else:
                    fail(kc, "reference_text %d words, under the %d minimum%s"
                         % (n, MIN_WORDS,
                            " (PARTIALLY_SUPPORTED needs notes explaining why)"
                            if state == "PARTIALLY_SUPPORTED" else ""))
            if not passages:
                fail(kc, "no source_passages recorded")
            for j, p in enumerate(passages):
                if not isinstance(p, dict):
                    fail(kc, "source_passages[%d] is not an object" % j)
                    continue
                for field in ("document", "locator", "quote"):
                    if not str(p.get(field) or "").strip():
                        fail(kc, "source_passages[%d] missing %s" % (j, field))

            g = gold.get(kc, "")
            if g and text:
                a, b = shingles(text), shingles(g)
                if a and b:
                    jac = len(a & b) / len(a | b)
                    if jac >= OVERLAP_ALERT:
                        fail(kc, "8-gram overlap with the existing library is %.2f "
                                 "(>= %.2f) — possible contamination, investigate before "
                                 "accepting" % (jac, OVERLAP_ALERT))

        if r.get("time_minutes") in (None, ""):
            warn(kc, "time_minutes not recorded")
        if (r.get("reviewer") or "").strip().upper() != "D":
            warn(kc, "reviewer field is %r, expected 'D'" % r.get("reviewer"))

    # --- report -----------------------------------------------------------------------
    dist = collections.Counter((r.get("support_state") or "?") for r in rows)
    wc = [words(r.get("reference_text") or "") for r in rows
          if (r.get("support_state") or "") != "UNSUPPORTED"]
    print("submission        : %s" % sub_path)
    print("entries           : %d (expected %d)" % (len(rows), len(expected)))
    print("support states    : %s" % dict(dist))
    if wc:
        wc_sorted = sorted(wc)
        print("word counts       : min=%d median=%d max=%d"
              % (min(wc), wc_sorted[len(wc_sorted) // 2], max(wc)))
        print("within %d-%d words : %d/%d"
              % (MIN_WORDS, MAX_WORDS, sum(1 for x in wc if MIN_WORDS <= x <= MAX_WORDS), len(wc)))
    print()
    if warnings:
        print("WARNINGS (%d) — not blocking:" % len(warnings))
        for w in warnings:
            print("  " + w)
        print()
    if problems:
        print("PROBLEMS (%d) — must be fixed before this submission is accepted:" % len(problems))
        for p in problems:
            print("  " + p)
        print()
        print("RESULT: REJECTED")
        return 1
    print("RESULT: ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
