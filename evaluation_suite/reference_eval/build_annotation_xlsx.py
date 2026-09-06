"""Build the human annotation workbook (.xlsx) from the frozen materialized calibration JSONL.

Design constraints carried over from the frozen protocol:

  * BLINDING. Nothing identifying a system, drafter, retrieval architecture, or the reference's
    seed origin may appear. The source JSONL was already swept clean; this builder re-sweeps the
    assembled cell values before saving and refuses to write on any hit.
  * SAMPLE UNCHANGED. Row identities and order come straight from the JSONL. Nothing is resampled,
    reordered or filtered - including the 4 rows whose candidate draft is empty, which are genuine
    abstentions and part of what is being evaluated.
  * CLOSED LABEL SETS. Every judgment column is a dropdown with an error alert, so a free-typed or
    misspelled label cannot enter the data.
  * READ-ONLY MATERIALS. Reference/draft/evidence columns are locked so the evidence being judged
    cannot be edited mid-annotation; only the answer columns are unlocked.

M4A is deliberately NOT given a row-level column. The protocol gates it on ATOMIC per-reference-claim
support decisions, and no frozen reference-claim decomposition exists yet for these 30 KCs. A
row-level proxy would not be the quantity the protocol qualifies, so it is deferred rather than
approximated.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.worksheet.datavalidation import DataValidation

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import reference_judge_prompts as P  # noqa: E402

CAL = BASE / "output" / "human_calibration"
SRC = CAL / "reference_human_calibration_workbook_v2_MATERIALIZED.jsonl"
OUT = CAL / "KC_ANNOTATION_WORKBOOK.xlsx"

KC_ID_PATTERN = r"KC_[A-Z]+_[A-Z]+_\d+"  # legitimate for a human annotator


def clean(v):
    """Strip XML-illegal control characters that PDF extraction leaves in the corpus text.

    Excel cannot store them and openpyxl refuses the write. They are extraction noise carrying no
    content, so removing them loses nothing an annotator would read - but the substitution is done
    with an explicit marker-free strip rather than a lossy re-encode, so the surrounding wording
    stays exactly as the source has it.
    """
    if isinstance(v, str):
        return ILLEGAL_CHARACTERS_RE.sub("", v)
    return v

# ---- palette -------------------------------------------------------------
H_FILL = PatternFill("solid", fgColor="1F3864")      # header navy
RO_FILL = PatternFill("solid", fgColor="F2F2F2")     # read-only grey
ANS_FILL = PatternFill("solid", fgColor="FFF2CC")    # answer amber
OPT_FILL = PatternFill("solid", fgColor="EAF1F8")    # optional blue
TODO_FILL = PatternFill("solid", fgColor="FCE4E4")   # unfilled pink
H_FONT = Font(color="FFFFFF", bold=True, size=11)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# ---- label sets ----------------------------------------------------------
LABELS = {
    "M1_verdict": ["PASS", "FAIL", "NOT_JUDGEABLE"],
    "M2_verdict": ["PASS", "FAIL", "NOT_JUDGEABLE"],
    "M3_core_completeness": ["CORE_COMPLETE", "MATERIAL_OMISSION", "NOT_JUDGEABLE"],
    "TARGET_ALIGNMENT": ["TARGET_ALIGNED", "WRONG_TARGET", "NOT_JUDGEABLE"],
    "M4B_evidence_adequacy_OPTIONAL": ["EVIDENCE_ADEQUATE", "MATERIAL_EVIDENCE_GAP", "NOT_JUDGEABLE"],
    "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE": ["YES", "NO"],
    "POSSIBLE_REFERENCE_DEFECT": ["YES", "NO"],
    "confidence": ["HIGH", "MEDIUM", "LOW"],
}

COLUMNS = [
    # (key, header, width, kind)
    ("row_no", "#", 5, "ro"),
    ("review_case_id", "Case ID", 24, "ro"),
    ("unit_id", "KC ID", 20, "ro"),
    ("canonical_name", "KC Name", 28, "ro"),
    ("hierarchy", "Curriculum location", 34, "ro"),
    ("expert_reference", "EXPERT REFERENCE (the standard)", 78, "ro"),
    ("candidate_draft", "DESCRIPTION UNDER REVIEW", 78, "ro"),
    ("n_evidence", "# evidence items", 11, "ro"),
    ("source_citations", "Reference source citations", 40, "ro"),
    ("M1_verdict", "M1 faithfulness", 18, "ans"),
    ("M2_verdict", "M2 correctness", 18, "ans"),
    ("M3_core_completeness", "M3 completeness", 22, "ans"),
    ("TARGET_ALIGNMENT", "TARGET alignment", 20, "ans"),
    ("VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "Valid alt. beyond reference?", 20, "ans"),
    ("POSSIBLE_REFERENCE_DEFECT", "Possible reference defect?", 20, "ans"),
    ("confidence", "Confidence", 13, "ans"),
    ("notes", "Notes", 46, "ans"),
    ("M4B_evidence_adequacy_OPTIONAL", "M4B adequacy (OPTIONAL)", 24, "opt"),
    ("review_seconds", "Seconds (optional)", 14, "opt"),
]


def build_instructions(ws):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 116

    def w(text, size=11, bold=False, color="000000", gap_after=0):
        ws.cell(row=w.r, column=2, value=text)
        c = ws.cell(row=w.r, column=2)
        c.font = Font(size=size, bold=bold, color=color)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        w.r += 1 + gap_after
    w.r = 2

    w("KC Annotation Workbook", 20, True, "1F3864")
    w("Blinded human calibration for the reference-based KC evaluator", 12, False, "595959", 1)

    w("What you are doing", 14, True, "1F3864")
    w("For each of 180 rows you compare a DESCRIPTION UNDER REVIEW against an EXPERT REFERENCE for the "
      "same knowledge component, and answer four questions. Your labels become the validation standard "
      "used to decide whether an automated judge is reliable enough to use. They are not compared to "
      "the automated judge until after all annotation is finished and frozen.", gap_after=1)

    w("Read this before you start", 14, True, "C00000")
    w("• You are BLIND by design. The workbook contains no system, model or retrieval-method names, and "
      "no indication of which system wrote which description. This is deliberate — please do not try to "
      "infer it, and do not open 'reference_human_calibration_blinded_mapping.jsonl', which would unblind you.")
    w("• Judge MEANING, not wording. Different vocabulary, ordering, structure, or length are not "
      "differences in content. A shorter description is not worse for being shorter.")
    w("• The reference is ONE adequate description, not an exhaustive list of everything true about the "
      "component. A description is not wrong merely for saying something the reference omits.")
    w("• Some descriptions are EMPTY. That is a real abstention by that system, not a data error. Judge "
      "it as an abstention — usually NOT_JUDGEABLE for M1/M2/TARGET, and MATERIAL_OMISSION for M3.")
    w("• Only the amber and blue columns are editable. The evidence you are judging is locked so it "
      "cannot be changed by accident.", gap_after=1)

    w("The four required judgments", 14, True, "1F3864")

    def task(title, question, opts):
        w(title, 12, True, "1F3864")
        w(question)
        for o in opts:
            w("      " + o)
        w("", gap_after=0)

    task("M1 — Faithfulness  (against the EVIDENCE, not the reference)",
         "Is every substantive claim in the description supported by the evidence supplied for it? "
         "Open the 'Evidence' sheet and filter by Case ID to read it.",
         ["PASS — every substantive claim is supported by the evidence.",
          "FAIL — at least one claim is not in the evidence, or contradicts it. A claim that is TRUE "
          "but absent from the evidence still fails: this measures grounding, not truth.",
          "NOT_JUDGEABLE — no description, or too fragmentary to assess."])

    task("M2 — Correctness  (against the REFERENCE and its SOURCE)",
         "Is every substantive claim correct for this knowledge component?",
         ["PASS — every claim is correct: stated by the reference, OR not mentioned by the reference "
          "but supported by the cited source material.",
          "FAIL — at least one claim contradicts the reference/source, or is supported by neither.",
          "NOT_JUDGEABLE — no description, or too fragmentary to assess.",
          "IMPORTANT: do NOT mark a claim wrong just because the reference is silent about it. If it is "
          "correct and the source supports it, that still counts as correct."])

    task("M3 — Core completeness",
         "Does the description contain enough of the DEFINING content to adequately explain the component?",
         ["CORE_COMPLETE — a reader would come away with an adequate, correct understanding.",
          "MATERIAL_OMISSION — a defining component is missing, leaving it underdefined.",
          "NOT_JUDGEABLE — empty or too fragmentary.",
          "Do NOT call it a material omission for: missing examples, missing optional detail, different "
          "organisation or wording, or simply being more concise than the reference."])

    task("TARGET — Alignment",
         "Is the description centrally about the SAME knowledge component as the reference?",
         ["TARGET_ALIGNED — yes, it is about this component.",
          "WRONG_TARGET — it is centrally about a different (often neighbouring) concept. Being entirely "
          "accurate about the wrong concept is still WRONG_TARGET.",
          "NOT_JUDGEABLE — empty or too fragmentary to identify a subject."])

    w("The two audit questions (every row)", 14, True, "1F3864")
    w("These test whether the reference itself is skewing the evaluation. Answer from the source "
      "material, never from any guess about who wrote the description.")
    w("      Valid alt. beyond reference? — YES if the description contains substantively valid, "
      "source-supported content or phrasing that someone marking mechanically against the reference "
      "could wrongly penalise.")
    w("      Possible reference defect? — YES if you think the EXPERT REFERENCE itself may be wrong or "
      "misleading here. Flag it; do not edit it.", gap_after=1)

    w("Optional columns", 14, True, "1F3864")
    w("M4B adequacy — exploratory only. It does not affect any decision; leave blank if short of time.")
    w("Seconds — rough time on the row, if you are tracking it.")
    w("Notes — anything ambiguous. Especially valuable where you nearly chose a different label.", gap_after=1)

    w("Practical guidance", 14, True, "1F3864")
    w("• Work top to bottom. Rows are deliberately ordered so the same component appears several times "
      "from different sources; judge each row on its own without trying to remember earlier rows.")
    w("• Unfilled required cells stay pink, so remaining work is visible at a glance.")
    w("• The four required judgments are INDEPENDENT. A description can be faithful to its evidence yet "
      "incorrect (the evidence was wrong), or correct yet incomplete, or complete yet about the wrong "
      "component. Do not let one answer pull the others.")
    w("• If genuinely torn, pick the label you would defend to a colleague, mark confidence LOW, and say "
      "why in Notes. Low-confidence rows are informative, not failures.", gap_after=1)

    w("When you are finished", 14, True, "1F3864")
    w("Save the file and hand it back. Do not rename the sheets or columns — an importer reads them by "
      "name. If a second annotator is working independently, do not compare answers first: disagreements "
      "are measured, then adjudicated by someone who has not seen the automated judge's output.")


def main() -> int:
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    wb = Workbook()

    build_instructions(wb.active)
    wb.active.title = "Instructions"

    ws = wb.create_sheet("Annotate")
    ev = wb.create_sheet("Evidence")
    lists = wb.create_sheet("_lists")
    lists.sheet_state = "hidden"

    # ---- hidden validation lists ----
    for ci, (key, opts) in enumerate(LABELS.items(), start=1):
        lists.cell(row=1, column=ci, value=key)
        for ri, o in enumerate(opts, start=2):
            lists.cell(row=ri, column=ci, value=o)

    # ---- header ----
    for ci, (key, header, width, kind) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=1, column=ci, value=header)
        c.fill = H_FILL
        c.font = H_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        c.border = BORDER
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"

    key_to_ci = {key: i for i, (key, *_rest) in enumerate(COLUMNS, start=1)}

    for ri, r in enumerate(rows, start=2):
        vals = {
            "row_no": ri - 1,
            "review_case_id": r["review_case_id"],
            "unit_id": r["unit_id"],
            "canonical_name": r["canonical_name"],
            "hierarchy": " > ".join(r.get("hierarchy_path") or []),
            "expert_reference": r.get("expert_reference") or "",
            "candidate_draft": (r.get("candidate_draft") or "").strip()
                                or "(EMPTY — this system produced no description. This is a genuine "
                                   "abstention, not a data error.)",
            "n_evidence": r.get("n_system_evidence_items", 0),
            "source_citations": "; ".join(
                f"{c.get('document')} p.{c.get('page')}"
                for c in (r.get("expert_source_citations") or []) if isinstance(c, dict) and c.get("document")
            ),
        }
        for key, header, width, kind in COLUMNS:
            c = ws.cell(row=ri, column=key_to_ci[key])
            c.border = BORDER
            if kind == "ro":
                c.value = clean(vals.get(key))
                c.fill = RO_FILL
                c.protection = Protection(locked=True)
                c.alignment = Alignment(wrap_text=key in ("expert_reference", "candidate_draft",
                                                          "source_citations", "hierarchy"),
                                        vertical="top")
            else:
                c.fill = ANS_FILL if kind == "ans" else OPT_FILL
                c.protection = Protection(locked=False)
                c.alignment = Alignment(vertical="top", wrap_text=(key == "notes"))
        ws.row_dimensions[ri].height = 96

    # ---- dropdowns ----
    for li, (key, opts) in enumerate(LABELS.items(), start=1):
        if key not in key_to_ci:
            continue
        col = get_column_letter(key_to_ci[key])
        src = f"_lists!${get_column_letter(li)}$2:${get_column_letter(li)}${len(opts) + 1}"
        dv = DataValidation(type="list", formula1=src, allow_blank=True, showDropDown=False)
        dv.error = f"Choose one of: {', '.join(opts)}"
        dv.errorTitle = "Not a valid label"
        dv.prompt = f"Select: {', '.join(opts)}"
        dv.promptTitle = key
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{len(rows) + 1}")

    # highlight unfilled required cells
    for key in ("M1_verdict", "M2_verdict", "M3_core_completeness", "TARGET_ALIGNMENT",
                "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE", "POSSIBLE_REFERENCE_DEFECT"):
        col = get_column_letter(key_to_ci[key])
        ws.conditional_formatting.add(
            f"{col}2:{col}{len(rows) + 1}",
            FormulaRule(formula=[f'ISBLANK({col}2)'], fill=TODO_FILL, stopIfTrue=False))

    # Protection without a password: it prevents accidental edits to the material being judged,
    # while staying trivially removable if an annotator genuinely needs to. Setting .password = None
    # raises in openpyxl, so it is simply never assigned.
    ws.protection.sheet = True
    ws.protection.enable()
    ws.protection.selectLockedCells = False
    ws.protection.formatColumns = False
    ws.protection.formatRows = False
    ws.protection.autoFilter = False

    # ---- evidence sheet ----
    ev_cols = [("Case ID", 24), ("KC ID", 20), ("Evidence ID", 12), ("Document", 34),
               ("Page", 7), ("Section", 40), ("Evidence text", 120)]
    for ci, (h, wdt) in enumerate(ev_cols, start=1):
        c = ev.cell(row=1, column=ci, value=h)
        c.fill = H_FILL
        c.font = H_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ev.column_dimensions[get_column_letter(ci)].width = wdt
    er = 2
    for r in rows:
        for e in r.get("candidate_system_evidence") or []:
            for ci, v in enumerate([r["review_case_id"], r["unit_id"], e.get("id"),
                                     e.get("document"), e.get("page"), e.get("section"),
                                     e.get("text")], start=1):
                c = ev.cell(row=er, column=ci, value=clean(v))
                c.alignment = Alignment(wrap_text=(ci == 7), vertical="top")
                c.border = BORDER
            er += 1
    ev.freeze_panes = "A2"
    ev.auto_filter.ref = f"A1:G{er - 1}"

    # ---- blinding re-sweep over every assembled cell before saving ----
    violations = []
    for sheet in (ws, ev):
        for row in sheet.iter_rows():
            for c in row:
                if not isinstance(c.value, str):
                    continue
                for pat in P._FORBIDDEN:
                    if pat.pattern == KC_ID_PATTERN:
                        continue
                    hit = pat.search(c.value)
                    if hit:
                        violations.append((sheet.title, c.coordinate, pat.pattern, hit.group(0)))
    if violations:
        print(f"REFUSED: {len(violations)} blinding violation(s); workbook NOT written")
        for v in violations[:10]:
            print(f"  - {v}")
        return 1

    wb.save(OUT)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"wrote {OUT.name}")
    print(f"  rows       : {len(rows)}  (KCs {len({r['unit_id'] for r in rows})})")
    print(f"  evidence   : {er - 2} rows")
    print(f"  dropdowns  : {sum(1 for k in LABELS if k in key_to_ci)} validated columns")
    print(f"  blinding   : zero violations across {ws.max_row + ev.max_row} scanned rows")
    print(f"  sha256     : {digest}")
    print(f"\n  {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
