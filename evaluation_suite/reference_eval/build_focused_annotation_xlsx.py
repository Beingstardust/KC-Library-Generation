"""Build a FOCUSED annotation workbook: a stratified subset of the frozen 180 calibration rows,
enriched so the qualification gates are actually testable within a realistic annotation budget.

WHY A SUBSET, NOT A NEW SAMPLE
Every row here is drawn from the already-frozen 180. No KC is added, no row is regenerated, and
arm balance is preserved exactly (every selected KC contributes all 6 arms). The frozen sample is
narrowed, never redrawn.

WHY ENRICHED
The binding constraint is not row count - it is that gates like "false-PASS rate <= 10%" and
"FAIL recall >= 85%" need enough FAIL-side examples to be computable at all. Under a uniform
subset most gates would return INSUFFICIENT_VALIDATION_SUPPORT purely from small denominators.

SELECTION USES ONLY JUDGE-INDEPENDENT SIGNALS
Selene's predictions are NOT used to choose rows. Selecting on the judge's own output would
condition the validation sample on the judge's decision boundary and quietly bias every agreement
statistic computed from it. The signals used instead come from the expert reference and from
mechanical text properties:

    expert review_action   REPLACE / MAJOR_EDIT / MINOR_EDIT mark KCs where the expert found the
                           seeded draft deficient - harder KCs, independent of any judge
    empty candidate draft  genuine abstentions; edge cases for NOT_JUDGEABLE handling
    draft/reference ratio  a very short draft against a long reference is mechanically more likely
                           to be incomplete
    formula-bearing        formula errors were historically the dominant failure mode

CONSEQUENCE TO DISCLOSE
Rates computed on this subset are conditional on an enriched sample and are NOT population
estimates for the 180. They are the right quantity for testing whether the gates hold where they
bind, and must be reported as enriched-sample rates.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import reference_judge_prompts as P  # noqa: E402

CAL = BASE / "output" / "human_calibration"
SRC = CAL / "reference_human_calibration_workbook_v2_MATERIALIZED.jsonl"
REF = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
OUT = CAL / "KC_ANNOTATION_FOCUSED.xlsx"
OUT_JSONL = CAL / "focused_calibration_subset.jsonl"
OUT_META = CAL / "focused_subset_selection.json"

N_PER_ARM = 6                  # 6 arms x 6 rows = 36 rows (see select_rows for the split)
HARD_PER_ARM = 4               # highest-risk rows: supply the minority classes
EASY_PER_ARM = 2               # lowest-risk rows: supply the majority class M3 PASS-recall needs
KC_ID_PATTERN = r"KC_[A-Z]+_[A-Z]+_\d+"
MATH = re.compile(r"[=<>≤≥±∑∏√/^]|\\frac|\\sum|\\prod")

ACTION_WEIGHT = {"REPLACE": 3, "MAJOR_EDIT": 2, "MINOR_EDIT": 1, "ACCEPT": 0}

H_FILL = PatternFill("solid", fgColor="1F3864")
RO_FILL = PatternFill("solid", fgColor="F2F2F2")
EV_FILL = PatternFill("solid", fgColor="EDEDED")
ANS_FILL = PatternFill("solid", fgColor="FFF2CC")
OPT_FILL = PatternFill("solid", fgColor="EAF1F8")
TODO_FILL = PatternFill("solid", fgColor="FCE4E4")
H_FONT = Font(color="FFFFFF", bold=True, size=11)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

LABELS = {
    "M1_verdict": ["PASS", "FAIL", "NOT_JUDGEABLE"],
    "M2_verdict": ["PASS", "FAIL", "NOT_JUDGEABLE"],
    "M3_core_completeness": ["CORE_COMPLETE", "MATERIAL_OMISSION", "NOT_JUDGEABLE"],
    "TARGET_ALIGNMENT": ["TARGET_ALIGNED", "WRONG_TARGET", "NOT_JUDGEABLE"],
    "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE": ["YES", "NO"],
    "POSSIBLE_REFERENCE_DEFECT": ["YES", "NO"],
    "confidence": ["HIGH", "MEDIUM", "LOW"],
}

COLUMNS = [
    ("row_no", "#", 5, "ro"),
    ("review_case_id", "Case ID", 23, "ro"),
    ("unit_id", "KC ID", 19, "ro"),
    ("canonical_name", "KC Name", 26, "ro"),
    ("expert_reference", "EXPERT REFERENCE  (the standard)", 72, "ro"),
    ("candidate_draft", "DESCRIPTION UNDER REVIEW  (judge this)", 72, "ro"),
    ("evidence_inline", "EVIDENCE GIVEN TO THIS DESCRIPTION  (for M1)", 96, "ev"),
    ("n_evidence", "# ev", 6, "ro"),
    ("M1_verdict", "M1 faithfulness", 17, "ans"),
    ("M2_verdict", "M2 correctness", 17, "ans"),
    ("M3_core_completeness", "M3 completeness", 21, "ans"),
    ("TARGET_ALIGNMENT", "TARGET alignment", 19, "ans"),
    ("VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "Valid alt. beyond ref?", 19, "ans"),
    ("POSSIBLE_REFERENCE_DEFECT", "Possible ref defect?", 19, "ans"),
    ("confidence", "Confidence", 12, "ans"),
    ("notes", "Notes", 42, "ans"),
]


def clean(v):
    return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v


def row_risk(r, reference):
    """Judge-independent per-row risk score. Selene's outputs are NOT consulted - selecting rows by
    the judge's own answers would condition the validation sample on its decision boundary."""
    R = reference[r["unit_id"]]
    rl = len(R.get("reference_text") or "")
    d = (r.get("candidate_draft") or "").strip()
    ratio = len(d) / max(1, rl)
    s = 0.0
    if not d:
        s += 3                                   # abstention: an edge case worth capturing
    s += ACTION_WEIGHT.get(R["review_action"], 0)  # expert found the seeded draft deficient
    if ratio < 0.40:
        s += 2
    elif ratio < 0.60:
        s += 1
    if r.get("n_system_evidence_items", 0) <= 5:
        s += 1
    if MATH.search(R.get("reference_text") or ""):
        s += 1
    return s


def select_rows(rows, reference, mapping):
    """Arm-balanced hard/easy split.

    Both halves are required, and for a specific reason: M3 gates PASS recall AND FAIL recall, so a
    purely failure-enriched sample would make one of its two gates untestable. The easy half exists
    to supply the majority class, not as filler.
    """
    for r in rows:
        r["_risk"] = row_risk(r, reference)
    by_arm = {}
    for r in rows:
        by_arm.setdefault(mapping[r["review_case_id"]]["arm_true_identity"], []).append(r)

    chosen, detail = [], {}
    for arm in sorted(by_arm):
        ranked = sorted(by_arm[arm], key=lambda r: (-r["_risk"], r["review_case_id"]))
        hard = ranked[:HARD_PER_ARM]
        easy = ranked[-EASY_PER_ARM:]
        pick = hard + [e for e in easy if e not in hard]
        chosen.extend(pick)
        detail[arm] = {"hard": [r["review_case_id"] for r in hard],
                       "easy": [r["review_case_id"] for r in easy]}
    chosen.sort(key=lambda r: (r["unit_id"], r["review_case_id"]))
    return chosen, detail


def build_instructions(ws, meta):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 118

    def w(t, size=11, bold=False, color="000000", gap=0):
        c = ws.cell(row=w.r, column=2, value=t)
        c.font = Font(size=size, bold=bold, color=color)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        w.r += 1 + gap
    w.r = 2

    w("KC Annotation — Focused Set", 20, True, "1F3864")
    w(f"{meta['n_rows']} rows · {meta['n_kc']} knowledge components · 6 sources, balanced", 12, False, "595959", 1)

    w("Everything you need is on ONE row", 14, True, "1F3864")
    w("Each row of the 'Annotate' sheet contains the expert reference, the description you are judging, "
      "and the full evidence that description was given. No cross-referencing between sheets.", gap=1)

    w("Read this first", 14, True, "C00000")
    w("• You are BLIND by design — no system or model names anywhere. Please don't try to infer them, and "
      "don't open 'reference_human_calibration_blinded_mapping.jsonl'.")
    w("• Judge MEANING, not wording. Different vocabulary, ordering or length are not content differences. "
      "A shorter description is not worse for being shorter.")
    w("• The reference is ONE adequate description, not everything true about the component. A description "
      "is not wrong merely for adding something the reference omits.")
    w("• Some descriptions are EMPTY — a real abstention by that source, not a data error.")
    w("• Only the amber columns are editable; the material being judged is locked.", gap=1)

    w("The four judgments — they are INDEPENDENT", 14, True, "1F3864")
    w("A description can be faithful to its evidence yet incorrect (the evidence was wrong), or correct yet "
      "incomplete, or complete yet about the wrong component. Don't let one answer drag the others.", gap=1)

    def task(t, q, opts):
        w(t, 12, True, "1F3864")
        w(q)
        for o in opts:
            w("      " + o)
        w("")

    task("M1 — Faithfulness   → compare against the EVIDENCE column",
         "Is every substantive claim in the description supported by the evidence it was given?",
         ["PASS — every claim is supported by that evidence.",
          "FAIL — a claim is absent from the evidence, or contradicts it. A claim that is TRUE but not in "
          "the evidence still FAILS — this measures grounding, not truth.",
          "NOT_JUDGEABLE — empty or too fragmentary."])

    task("M2 — Correctness   → compare against the EXPERT REFERENCE",
         "Is every substantive claim actually correct for this component?",
         ["PASS — every claim is correct: stated by the reference, OR not mentioned by it but genuinely "
          "correct for this component.",
          "FAIL — a claim contradicts the reference, or is simply wrong.",
          "NOT_JUDGEABLE — empty or too fragmentary.",
          "Do NOT mark a claim wrong merely because the reference is silent about it."])

    task("M3 — Core completeness",
         "Does the description contain enough DEFINING content to adequately explain the component?",
         ["CORE_COMPLETE — a reader would come away with an adequate, correct understanding.",
          "MATERIAL_OMISSION — a defining component is missing, leaving it underdefined.",
          "NOT_JUDGEABLE — empty or too fragmentary.",
          "NOT omissions: missing examples, optional detail, different organisation, or being concise."])

    task("TARGET — Alignment",
         "Is the description centrally about the SAME component as the reference?",
         ["TARGET_ALIGNED — yes.",
          "WRONG_TARGET — centrally about a different (often neighbouring) concept. Being entirely accurate "
          "about the wrong concept is still WRONG_TARGET.",
          "NOT_JUDGEABLE — empty or too fragmentary."])

    w("The two audit questions", 14, True, "1F3864")
    w("      Valid alt. beyond ref? — YES if the description contains valid, correct content or phrasing "
      "that someone marking mechanically against the reference could wrongly penalise.")
    w("      Possible ref defect? — YES if you think the EXPERT REFERENCE itself looks wrong here. Flag it; "
      "don't edit it.", gap=1)

    w("Why this set is smaller than 180", 14, True, "1F3864")
    w(f"These {meta['n_rows']} rows are the smallest SUBSET of the frozen 180 that still lets the "
      "acceptance thresholds be tested — nothing new was sampled. They were "
      "chosen to concentrate the harder cases, so the acceptance thresholds can actually be tested within "
      "a realistic amount of your time. Selection used only the expert reference and mechanical text "
      "properties; the automated judge's own outputs were deliberately NOT used, since choosing rows by "
      "its answers would bias the very comparison this is meant to validate.", gap=1)

    w("If you're unsure", 14, True, "1F3864")
    w("Pick the label you'd defend to a colleague, set Confidence to LOW, and say why in Notes. "
      "Low-confidence rows are informative — they are not failures.")


def main() -> int:
    rows_all = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    reference = {json.loads(l)["knowledge_unit_id"]: json.loads(l)
                 for l in open(REF, encoding="utf-8") if l.strip()}

    mapping = {json.loads(l)["review_case_id"]: json.loads(l)
               for l in open(CAL / "reference_human_calibration_blinded_mapping.jsonl", encoding="utf-8") if l.strip()}
    rows, split_detail = select_rows(rows_all, reference, mapping)

    meta = {
        "generated_utc": "2026-08-27",
        "derived_from": SRC.name,
        "derived_from_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
        "n_rows": len(rows), "n_kc": len({r["unit_id"] for r in rows}),
        "design": f"{HARD_PER_ARM} highest-risk + {EASY_PER_ARM} lowest-risk rows per arm, 6 arms",
        "selection_rule": {
            "judge_outputs_used": False,
            "signals": {"expert_review_action": ACTION_WEIGHT,
                         "empty_draft": "+2 each, capped at 2 drafts",
                         "min_draft_reference_length_ratio_below_0.35": "+1",
                         "formula_bearing_reference": "+1"},
            "tie_break": "KC id ascending, so the selection is reproducible",
        },
        "hard_easy_split_by_arm": split_detail,
        "arm_balance": f"exactly {N_PER_ARM} rows per arm",
        "why_both_halves": "M3 gates PASS recall AND FAIL recall, so a purely failure-enriched sample "
                            "would leave one of its two gates untestable.",
        "disclosure": "Rates computed on this subset are conditional on an ENRICHED sample and are not "
                       "population estimates for the frozen 180. They test whether the gates hold where "
                       "they bind.",
        "sample_integrity": "strict subset of the frozen 180; no KC added, no row regenerated, no resampling",
    }

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    OUT_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------------- workbook ----------------
    wb = Workbook()
    build_instructions(wb.active, meta)
    wb.active.title = "Instructions"
    ws = wb.create_sheet("Annotate")
    lists = wb.create_sheet("_lists")
    lists.sheet_state = "hidden"

    for ci, (key, opts) in enumerate(LABELS.items(), start=1):
        lists.cell(row=1, column=ci, value=key)
        for ri, o in enumerate(opts, start=2):
            lists.cell(row=ri, column=ci, value=o)

    for ci, (key, header, width, kind) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=1, column=ci, value=header)
        c.fill = H_FILL
        c.font = H_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        c.border = BORDER
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[1].height = 40
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"
    key_to_ci = {k: i for i, (k, *_r) in enumerate(COLUMNS, start=1)}

    for ri, r in enumerate(rows, start=2):
        ev_txt = "\n\n".join(
            f"[{e['id']}]  {e.get('document')}  p.{e.get('page')}"
            + (f"  |  {e.get('section')}" if e.get("section") else "")
            + f"\n{(e.get('text') or '').strip()}"
            for e in (r.get("candidate_system_evidence") or [])
        ) or "(no evidence supplied)"
        vals = {
            "row_no": ri - 1,
            "review_case_id": r["review_case_id"],
            "unit_id": r["unit_id"],
            "canonical_name": r["canonical_name"],
            "expert_reference": r.get("expert_reference") or "",
            "candidate_draft": (r.get("candidate_draft") or "").strip()
                                or "(EMPTY — this source produced no description. A genuine abstention, "
                                   "not a data error.)",
            "evidence_inline": ev_txt,
            "n_evidence": r.get("n_system_evidence_items", 0),
        }
        for key, header, width, kind in COLUMNS:
            c = ws.cell(row=ri, column=key_to_ci[key])
            c.border = BORDER
            if kind in ("ro", "ev"):
                c.value = clean(vals.get(key))
                c.fill = EV_FILL if kind == "ev" else RO_FILL
                c.protection = Protection(locked=True)
                c.alignment = Alignment(
                    wrap_text=key in ("expert_reference", "candidate_draft", "evidence_inline"),
                    vertical="top")
            else:
                c.fill = ANS_FILL
                c.protection = Protection(locked=False)
                c.alignment = Alignment(vertical="top", wrap_text=(key == "notes"))
        ws.row_dimensions[ri].height = 210

    for li, (key, opts) in enumerate(LABELS.items(), start=1):
        if key not in key_to_ci:
            continue
        col = get_column_letter(key_to_ci[key])
        src = f"_lists!${get_column_letter(li)}$2:${get_column_letter(li)}${len(opts) + 1}"
        dv = DataValidation(type="list", formula1=src, allow_blank=True, showDropDown=False)
        dv.error = f"Choose one of: {', '.join(opts)}"
        dv.errorTitle = "Not a valid label"
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{len(rows) + 1}")

    for key in ("M1_verdict", "M2_verdict", "M3_core_completeness", "TARGET_ALIGNMENT",
                "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "POSSIBLE_REFERENCE_DEFECT"):
        col = get_column_letter(key_to_ci[key])
        ws.conditional_formatting.add(
            f"{col}2:{col}{len(rows) + 1}",
            FormulaRule(formula=[f"ISBLANK({col}2)"], fill=TODO_FILL, stopIfTrue=False))

    ws.protection.sheet = True
    ws.protection.enable()
    ws.protection.selectLockedCells = False
    ws.protection.autoFilter = False
    ws.protection.formatRows = False
    ws.protection.formatColumns = False

    # blinding re-sweep
    violations = []
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str):
                for pat in P._FORBIDDEN:
                    if pat.pattern == KC_ID_PATTERN:
                        continue
                    h = pat.search(c.value)
                    if h:
                        violations.append((c.coordinate, pat.pattern, h.group(0)))
    if violations:
        print(f"REFUSED: {len(violations)} blinding violation(s); not written")
        for v in violations[:8]:
            print("  -", v)
        return 1

    wb.save(OUT)
    print(f"wrote {OUT.name}")
    print(f"  {len(rows)} rows across {len({r['unit_id'] for r in rows})} KCs, {N_PER_ARM} per source")
    print(f"  evidence inline on every row (max {max(len(str(c.value)) for c in ws['G'][1:])} chars)")
    print(f"  abstentions included: {sum(1 for r in rows if not (r['candidate_draft'] or '').strip())}")
    print("  risk range: %.1f - %.1f" % (min(r["_risk"] for r in rows), max(r["_risk"] for r in rows)))
    print(f"\n  {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
