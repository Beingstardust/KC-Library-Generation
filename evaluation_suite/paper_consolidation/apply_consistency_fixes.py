"""Correct stale statements in paper-facing documents, recording every change.

Corrections only. No finding is deleted, no status is upgraded, and no unresolved question is
converted into a settled one. Where a finding's headline overstated, the heading is marked and a
correction note is appended beneath it rather than the original text being rewritten away.
"""
from pathlib import Path

BASE = Path(__file__).parent.parent
LOG = []


def fix(rel, old, new, rationale, must=True):
    p = BASE / rel
    if not p.exists():
        LOG.append((rel, "-", "-", "FILE NOT FOUND", rationale))
        return
    s = p.read_text(encoding="utf-8")
    n = s.count(old)
    if n != 1:
        LOG.append((rel, old[:70], f"({n} matches)",
                    "SKIPPED - anchor not unique" if must else "not present", rationale))
        return
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    LOG.append((rel, old[:110], new[:110], "CORRECTED", rationale))


# ---------------- EVALUATION_FINDINGS.md ----------------
fix("EVALUATION_FINDINGS.md",
    "Last updated: **2026-09-01** (v3 complete: reference library cleared by control 6, "
    "model-agnosticism established by equivalence testing, retrieval claim restored by pooled IR)",
    "Last updated: **2026-09-02** (documentation consolidation. Model-agnosticism DOWNGRADED to an "
    "ordering claim by F-57; seed audit sized rather than settled; abstention PROVISIONAL pending "
    "the support-boundary audit. See `paper_consolidation/PAPER_CLAIM_LEDGER.md`.)",
    "Header asserted model-agnosticism as established; F-57 contradicts it.")

fix("EVALUATION_FINDINGS.md",
    "### F-50 · Model-agnostic within a competence band, established by equivalence testing rather than a null result · ACTIVE",
    "### F-50 · Model-agnostic within a competence band · DOWNGRADED by F-57 (equivalence is evaluator-dependent; ordering retained)",
    "Title asserted an equivalence result that does not reproduce under a second instrument.")

fix("EVALUATION_FINDINGS.md",
    "### F-58 · The pipeline reproduces itself to 0.17% - so the second-judge disagreement is real, not noise · ACTIVE",
    "### F-58 · The EVALUATION STAGES reproduce to 0.17% - so the second-instrument disagreement is real, not noise · ACTIVE (scope corrected 2026-09-02)",
    "'Pipeline' implied end-to-end KC generation. The rerun covers claim decomposition and judging "
    "only - not retrieval, not drafting.")

fix("EVALUATION_FINDINGS.md",
    "### F-14 · `JUDGE_QUALIFIED = false` · ACTIVE",
    "### F-14 · `JUDGE_QUALIFIED = false` · CORRECTED by F-55 (blanket status too broad; see the note under F-55)",
    "Only one task genuinely failed; three returned INSUFFICIENT for sample size, which is not a "
    "disagreement verdict.")

fix("EVALUATION_FINDINGS.md",
    "Mitigated by pooling seven diverse runs, one of which returns 123 passages per KC. Notably the four",
    "Mitigated by pooling seven evaluated arms corresponding to **four distinct retrieval "
    "configurations**; note the pool takes each arm's **top 20**, so BaseDense's 123 passages did "
    "not all enter it. Notably the four",
    "Two errors: seven arms are only four configurations, and only the top 20 entered the pool.")

fix("EVALUATION_FINDINGS.md",
    "**The two failure modes that would invalidate a machine-seeded reference did not occur once.** The\n"
    "seeded library never disagreed with an independently written reference about what a concept is, and\n"
    "never asserted content the corpus does not support.",
    "**The two failure modes TESTED did not occur.** The seeded library never disagreed with an "
    "independently written reference about what a concept is, and never asserted content the corpus "
    "does not support.\n\n"
    "**Correction (2026-09-02):** an earlier phrasing called these \"the two ways a machine-seeded "
    "reference could be invalid\". That is wrong. At least six failure modes are possible: semantic "
    "distortion; unsupported content; **omission of source-supported content**; **incorrect "
    "corpus-support state**; **seed-shaped content selection or emphasis**; and provenance error. "
    "This audit tested the first two. The support-boundary mode was tested and **disagreed** (below). "
    "Omission and content-selection shaping were not tested.",
    "Claimed exhaustiveness over failure modes that the audit did not test.")

# ---------------- AMENDMENT_01 ----------------
fix("reference_eval/locks/AMENDMENT_01_noise_guard.md",
    "- The judge remains **absolutely unqualified** (`JUDGE_QUALIFIED=false`; M3 `NOT_QUALIFIED`). Only",
    "- The judge remains unqualified for absolute claims on M1/M2/TARGET/M4A. *(Updated 2026-09-02: "
    "the blanket phrasing is superseded by F-55 - graded completeness met its gates under "
    "leave-one-out development calibration; the binary v1 verdict is what failed.)* Only",
    "Blanket 'absolutely unqualified' is no longer accurate for completeness.")

# ---------------- OVERHAUL_PROTOCOL_v2 ----------------
fix("reference_eval/locks/OVERHAUL_PROTOCOL_v2.md",
    "### Reliability evidence: second judge",
    "### Reliability evidence: second judge *(superseded 2026-09-02 - see note)*\n\n"
    "> **Superseded.** This section planned `RootSignals-Judge-Llama-70B`. That model was never "
    "present on the cluster, and it would in any case have shared Selene's Llama family and so its "
    "verbosity bias. The executed check used **MiniCheck-Flan-T5-Large**, an encoder-decoder chosen "
    "for architectural independence. See F-56/F-57 and `PLAN_judge_qualification_and_second_judge.md`.",
    "Named a model that was never available and would have been family-confounded.")

# ---------------- EXTRINSIC_EVALUATION_METHOD ----------------
fix("paper_methods/EXTRINSIC_EVALUATION_METHOD.md",
    "| `retrieval_reference_recall` (M4A) | was each reference claim present in retrieved evidence - **primary** retrieval diagnostic |",
    "| ~~`retrieval_reference_recall` (M4A)~~ | **SUPERSEDED 2026-09-02.** Never validated - M4A has "
    "zero human labels (`INSUFFICIENT_VALIDATION_SUPPORT`). The primary retrieval diagnostic is now "
    "the pooled test collection: Recall@k / Precision@k / nDCG@k over per-passage relevance "
    "judgements. See `PAPER_CLAIM_LEDGER.md` sections A. |",
    "Named as PRIMARY a measure with zero human labels, superseded by the pooled IR metrics.")

# ---------------- PAPER_REFERENCES ----------------
fix("PAPER_REFERENCES.md",
    "annotator. This is a concrete, citable benchmark for why our `JUDGE_QUALIFIED=false` and LOW_POWER",
    "annotator. This is a concrete, citable benchmark for why our judge-validation status and LOW_POWER",
    "Blanket JUDGE_QUALIFIED=false is superseded by the criterion-specific status.")

if __name__ == "__main__":
    out = ["# Document consistency audit\n",
           "Stale, overstated, or imprecise statements found in paper-facing documentation and what "
           "was done about each. Corrections only: no finding was deleted, no status upgraded, and "
           "no unresolved question converted into a settled one.\n",
           f"Entries: {len(LOG)}\n",
           "| file | before | after | action | rationale |",
           "|---|---|---|---|---|"]
    for rel, old, new, action, why in LOG:
        o = old.replace("|", "\\|").replace("\n", " ")
        n = new.replace("|", "\\|").replace("\n", " ")
        out.append(f"| `{rel}` | {o} | {n} | **{action}** | {why} |")
        print(f"{action:<12} {rel}")
    (Path(__file__).parent / "DOCUMENT_CONSISTENCY_AUDIT.md").write_text(
        "\n".join(out) + "\n", encoding="utf-8")
    print(f"\nwrote DOCUMENT_CONSISTENCY_AUDIT.md ({len(LOG)} entries)")
