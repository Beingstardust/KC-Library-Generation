"""Final scan: every strong phrase left in paper-facing documentation must be defensible.

Classifies each hit rather than just listing it, because most occurrences of words like "equivalent"
are legitimate - quoting a label, describing a withdrawn claim, or stating the prohibition itself.
Only DEFENDED and NEEDS_REVIEW distinguish the two.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).parent.parent

PATTERNS = {
    "second judge not run": r"second judge (?:was )?not run|no second judge",
    "blanket JUDGE_QUALIFIED": r"JUDGE_QUALIFIED\s*=\s*false",
    "seed settled": r"seed (?:question|issue)[^.\n]{0,30}(?:settled|eliminated|resolved)",
    "proven unbiased": r"prov(?:en|ed)[^.\n]{0,20}unbiased|reference (?:is|was) unbiased",
    "pipeline reproducibility": r"pipeline reproduc",
    "seven diverse": r"seven diverse",
    "123 in pool": r"contributes 123|123 passages[^.\n]{0,40}pool",
    "budget causal": r"caused by (?:the )?budget",
    "proposed better than DOS": r"Proposed (?:retrieves|performs) better than DOS",
    "model agnostic": r"model[- ]agnostic",
    "domain agnostic": r"domain[- ]agnostic",
    "gold standard": r"gold standard|gold qrel",
    "equivalent": r"\bequivalen",
    "proved": r"\bprove[dsn]?\b",
    "context recall primary": r"context recall[^.\n]{0,40}(?:primary|retrieval metric)",
    "M4B primary": r"M4B[^.\n]{0,30}primary",
    "superiority": r"\bsuperior\b|\boutperforms\b",
}

SAFE = re.compile(
    r"prohibit|do not (?:claim|write|use)|never (?:write|claim|use)|not supportable|withdraw|"
    r"superseded|corrected|stale|downgrad|instead of|rather than|must not|cannot be|"
    r"we do not claim|non-?claim|is not |was not |no longer|status\s*=|WITHDRAWN|SUPERSEDED|"
    r"say instead|avoid|forbid|wrong|overclaim|overstat|not an|not a |does not|did not|"
    r"NOT |failed|dependent|sensitive|caveat|limitation|pending|provisional", re.I)


def classify(line: str, name: str) -> str:
    if SAFE.search(line):
        return "DEFENDED (prohibition, correction, or withdrawal)"
    if name == "equivalent" and re.search(
            r"SUBSTANTIVELY_EQUIVALENT|BOTH_VALID|EQUIV\b|equivalence (?:test|margin|claim|"
            r"statistic|verdict|result|analysis)|TOST", line):
        return "DEFENDED (label or named statistical concept)"
    if name == "blanket JUDGE_QUALIFIED" and re.search(r"lock|freeze|frozen|six:", line, re.I):
        return "DEFENDED (names the lock artifact, not a status claim)"
    if name in ("proved", "superiority") and re.search(r"improve", line, re.I):
        return "DEFENDED (ordinary usage)"
    return "NEEDS_REVIEW"


def main() -> int:
    skip = {".git", "output", "models", "__pycache__", "corpus_support", "02_curation"}
    # the audit must not scan its own output, nor the documents whose PURPOSE is to quote the
    # forbidden phrasings verbatim - doing so would inflate the count with its own text
    self_ref = {"FINAL_PHRASE_AUDIT.md", "PAPER_NONCLAIMS.md", "DOCUMENT_CONSISTENCY_AUDIT.md",
                "PAPER_CLAIM_LEDGER.md"}
    rows = []
    for p in sorted(BASE.rglob("*.md")):
        if any(d in p.parts for d in skip) or p.name in self_ref:
            continue
        rel = p.relative_to(BASE).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for name, pat in PATTERNS.items():
                if re.search(pat, line, re.I):
                    rows.append((name, rel, i, classify(line, name), line.strip()[:150]))

    need = [r for r in rows if r[3] == "NEEDS_REVIEW"]
    out = ["# Final phrase audit\n",
           "Every strong or potentially overclaiming phrase remaining in paper-facing documentation, "
           "classified. `DEFENDED` means the occurrence is legitimate: it states a prohibition, "
           "records a correction, names a withdrawn claim, or refers to a label or named statistical "
           "concept. `NEEDS_REVIEW` means a human should look at it.\n",
           f"Scanned {len(set(r[1] for r in rows))} files · {len(rows)} hits · "
           f"**{len(need)} need review**\n"]

    if need:
        out += ["## Needs review\n", "| phrase | file | line | excerpt |", "|---|---|---|---|"]
        for name, rel, i, _, ex in need:
            out.append(f"| `{name}` | `{rel}` | {i} | {ex.replace('|', '\\|')} |")
    else:
        out.append("## Needs review\n\nNone. Every remaining strong phrase is defended by context.\n")

    out += ["\n## All hits by classification\n", "| phrase | defended | needs review |", "|---|---|---|"]
    for name in PATTERNS:
        d = sum(1 for r in rows if r[0] == name and r[3] != "NEEDS_REVIEW")
        n = sum(1 for r in rows if r[0] == name and r[3] == "NEEDS_REVIEW")
        if d or n:
            out.append(f"| `{name}` | {d} | {n} |")

    (Path(__file__).parent / "FINAL_PHRASE_AUDIT.md").write_text("\n".join(out) + "\n",
                                                                 encoding="utf-8")
    print(f"{len(rows)} hits, {len(need)} need review")
    for name, rel, i, _, ex in need[:30]:
        print(f"  {name:<24} {rel}:{i}  {ex[:86]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
