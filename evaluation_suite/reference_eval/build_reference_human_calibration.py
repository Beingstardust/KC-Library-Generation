"""PHASE 9: build the blinded human calibration sample and workbook.

30 stratified KCs x the unique primary arms. Note the arm count is SIX, not the five the
specification anticipated: intrinsic Proposed/Qwen and extrinsic Proposed/Qwen are different
artifacts (different commit, different prompt mode, different sha256, only 17/159 identical
drafts) and neither can substitute for the other without breaking the within-experiment control
each was built to satisfy. See reference_library/00_freeze/CANDIDATE_FREEZE_MANIFEST.json,
"unique_primary_arm_count_decision_2026-08-25". That gives 30 x 6 = 180 human rows.

All arms for the same KC stay in the same stratum, so the human sees every system's attempt at a
KC together as one block (order randomized), which is what makes the per-arm calibration
comparison paired.

STRATIFICATION (spec section 15) over the 150 fully-supported KCs:
    hierarchy branch, reference edit action, formula/non-formula, procedure/non-procedure.
Deliberately NOT sampling only known failures.

BLINDING: the workbook carries no model, system, retrieval-architecture, or machine-status field.
The arm identity lives only in the separate mapping file, exactly as the earlier authority
evaluation did (evaluation_suite/data/authority_human_review_blinded_mapping.jsonl).

SEED-BIAS DIAGNOSTIC (spec section 16, mandatory because the reference was machine-seeded):
every row carries VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE and
POSSIBLE_REFERENCE_DEFECT. These are answered blind and reported per arm after unblinding. They do
not prove absence of seed bias; they test whether the reference representation disproportionately
penalizes legitimate non-seed formulations.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).parent
REFERENCE = BASE.parent / "reference_library" / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
OUT_DIR = BASE / "output" / "human_calibration"

PRIMARY_ARMS = ("A1", "A2", "A3", "A4", "A5", "A6")  # opaque; true identity only in the mapping file
ARM_TRUE_IDENTITY = {
    "A1": "intrinsic_P-Q", "A2": "intrinsic_P-G", "A3": "intrinsic_P-D",
    "A4": "extrinsic_P-Q", "A5": "extrinsic_B-Q", "A6": "extrinsic_DOS-Q",
}

N_KC = 30
SEED = 20260825

_MATH = re.compile(r"[=<>≤≥±∑∏√/^]|\\frac|\\sum|\\prod|\\sqrt")
_PROC = re.compile(r"\b(step|first|then|repeat|iterat|procedure|algorithm|until|loop|recursiv)\w*\b", re.I)

PROVENANCE = BASE.parent / "reference_library" / "04_gold" / "reference_provenance_resolution.jsonl"

_PROV_CACHE: dict[str, dict] | None = None


def _provenance() -> dict[str, dict]:
    global _PROV_CACHE
    if _PROV_CACHE is None:
        idx = {}
        if PROVENANCE.exists():
            for line in open(PROVENANCE, encoding="utf-8"):
                if line.strip():
                    d = json.loads(line)
                    if d.get("resolved"):
                        idx[d["reference_source_id"]] = d
        _PROV_CACHE = idx
    return _PROV_CACHE


def resolve_citations(source_evidence_ids: list[str]) -> list[dict]:
    """Turn native evidence ids into human-checkable document/page/section citations.

    The native ids embed the retrieval lane (":comprehensive:"), so passing them through to a
    blinded reviewer would leak information about how the evidence was produced. Resolving them
    also gives the human something they can actually look up in the source PDFs.
    """
    prov = _provenance()
    out, unresolved = [], 0
    for sid in source_evidence_ids or []:
        p = prov.get(sid)
        if p is None:
            unresolved += 1
            continue
        out.append({
            "document": p.get("document_id"),
            "page": p.get("page"),
            "section": p.get("section") or "",
            "sentence_id": p.get("sentence_id"),
        })
    if unresolved:
        out.append({"unresolved_count": unresolved,
                     "note": "these source ids did not resolve in the provenance audit"})
    return out


def stratum_of(row: dict) -> tuple:
    hp = row.get("hierarchy", {}).get("topic_path") or []
    branch = hp[1] if len(hp) > 1 else (hp[0] if hp else "UNKNOWN")
    text = row.get("reference_text") or ""
    return (branch, row["review_action"], bool(_MATH.search(text)), bool(_PROC.search(text)))


def stratified_sample(rows: list[dict], n_target: int = N_KC, seed: int = SEED) -> list[str]:
    """Guaranteed-coverage stratification.

    Pure proportional allocation over the full 4-way stratum cross-product concentrates the sample
    in the largest cells and silently drops whole levels of a factor: a first version of this
    sampler returned 25 ACCEPT + 5 MAJOR_EDIT and zero REPLACE / MINOR_EDIT KCs, which would have
    left the two most heavily edited reference categories - exactly the ones most informative about
    seed anchoring - unrepresented in calibration.

    So: first guarantee at least one KC per level of each individual stratification factor, then
    fill the remainder proportionally over the full cross-product.
    """
    rng = random.Random(seed)
    by_cell: dict[tuple, list[str]] = defaultdict(list)
    for r in rows:
        by_cell[stratum_of(r)].append(r["knowledge_unit_id"])
    for ids in by_cell.values():
        ids.sort()
        rng.shuffle(ids)

    id_to_stratum = {r["knowledge_unit_id"]: stratum_of(r) for r in rows}
    picked: list[str] = []

    # pass 1 - guarantee every level of every factor appears at least once
    for factor_idx in range(4):
        levels = defaultdict(list)
        for r in rows:
            levels[stratum_of(r)[factor_idx]].append(r["knowledge_unit_id"])
        for level in sorted(levels, key=str):
            if any(id_to_stratum[k][factor_idx] == level for k in picked):
                continue
            candidates = sorted(levels[level])
            rng.shuffle(candidates)
            for k in candidates:
                if k not in picked:
                    picked.append(k)
                    break

    # pass 2 - fill the rest proportionally over the full cross-product
    remaining_pool = [(cell, [k for k in ids if k not in picked]) for cell, ids in by_cell.items()]
    total_remaining = sum(len(v) for _, v in remaining_pool)
    slots = max(0, n_target - len(picked))
    if slots and total_remaining:
        raw = {cell: len(v) / total_remaining * slots for cell, v in remaining_pool}
        alloc = {cell: min(int(raw[cell]), len(v)) for cell, v in remaining_pool}
        leftover = slots - sum(alloc.values())
        for cell, v in sorted(remaining_pool, key=lambda cv: raw[cv[0]] - alloc[cv[0]], reverse=True):
            if leftover <= 0:
                break
            if alloc[cell] < len(v):
                alloc[cell] += 1
                leftover -= 1
        for cell, v in remaining_pool:
            picked.extend(v[: alloc[cell]])

    return sorted(picked[:n_target])


def build(reference_path: Path = REFERENCE, n_kc: int = N_KC, seed: int = SEED) -> dict:
    rows = [json.loads(l) for l in open(reference_path, encoding="utf-8") if l.strip()]
    supported = [r for r in rows if r["support_state"] == "SUPPORTED"]

    kc_ids = stratified_sample(supported, n_kc, seed)
    by_id = {r["knowledge_unit_id"]: r for r in rows}

    rng = random.Random(seed + 1)
    workbook, mapping = [], []
    for kc_id in kc_ids:
        ref = by_id[kc_id]
        arms = list(PRIMARY_ARMS)
        rng.shuffle(arms)  # per-KC presentation order, blocks positional anchoring
        for pos, arm in enumerate(arms):
            case_id = "HC-" + hashlib.sha256(f"{kc_id}:{arm}:{seed}".encode()).hexdigest()[:20]
            workbook.append({
                "review_case_id": case_id,
                "unit_id": kc_id,
                "presentation_position": pos,
                "canonical_name": ref["canonical_name"],
                "hierarchy_path": ref.get("hierarchy", {}).get("topic_path") or [],
                # materials the human receives
                "expert_reference": ref["reference_text"],
                # Human-readable citations resolved through the provenance audit. The raw
                # source_evidence_ids are deliberately NOT carried here: they embed the retrieval
                # lane name, which would tell a blinded reviewer something about how evidence was
                # produced. Document/page/section is what a human actually needs to check a source.
                "expert_source_citations": resolve_citations(ref["source_evidence_ids"]),
                "candidate_draft": "<<POPULATED_AT_MATERIALIZATION_FROM_FROZEN_ARM>>",
                "candidate_system_evidence": "<<POPULATED_AT_MATERIALIZATION_FROM_FROZEN_ARM>>",
                # labels the human assigns - identical constructs to the automated judge
                "M1_faithfulness_per_claim": None,
                "M2_correctness_per_claim": None,
                "M3_core_completeness": None,      # CORE_COMPLETE | MATERIAL_OMISSION | NOT_JUDGEABLE
                "M4_evidence_adequacy": None,      # EVIDENCE_ADEQUATE | MATERIAL_EVIDENCE_GAP | NOT_JUDGEABLE
                "TARGET_ALIGNMENT": None,          # TARGET_ALIGNED | WRONG_TARGET | NOT_JUDGEABLE
                # mandatory seed-bias diagnostics (spec section 16)
                "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE": None,  # YES | NO
                "POSSIBLE_REFERENCE_DEFECT": None,                            # YES | NO
                "seed_bias_note": "",
                "review_seconds": None,
            })
            mapping.append({
                "review_case_id": case_id, "unit_id": kc_id,
                "arm_code": arm, "arm_true_identity": ARM_TRUE_IDENTITY[arm],
                "presentation_position": pos,
            })

    sampled = [by_id[k] for k in kc_ids]
    return {
        "kc_ids": kc_ids,
        "workbook": workbook,
        "mapping": mapping,
        "summary": {
            "n_kc": len(kc_ids), "n_arms": len(PRIMARY_ARMS), "n_rows": len(workbook),
            "seed": seed,
            "sampled_from": "the 150 SUPPORTED KCs only (PARTIALLY_SUPPORTED and UNSUPPORTED are "
                            "evaluated by different questions - spec section 7B/7C)",
            "stratum_coverage": {
                "hierarchy_branch": dict(Counter(stratum_of(r)[0] for r in sampled)),
                "reference_edit_action": dict(Counter(stratum_of(r)[1] for r in sampled)),
                "formula_bearing": dict(Counter(str(stratum_of(r)[2]) for r in sampled)),
                "procedure_bearing": dict(Counter(str(stratum_of(r)[3]) for r in sampled)),
            },
            "population_for_comparison": {
                "hierarchy_branch": dict(Counter(stratum_of(r)[0] for r in supported)),
                "reference_edit_action": dict(Counter(stratum_of(r)[1] for r in supported)),
                "formula_bearing": dict(Counter(str(stratum_of(r)[2]) for r in supported)),
                "procedure_bearing": dict(Counter(str(stratum_of(r)[3]) for r in supported)),
            },
            "blinding": "workbook rows carry NO model, system, retrieval-architecture, or machine-status "
                        "field. Arm identity exists only in the separate mapping file.",
        },
    }


def main() -> int:
    out = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wb = OUT_DIR / "reference_human_calibration_workbook.jsonl"
    with open(wb, "w", encoding="utf-8") as f:
        for r in out["workbook"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    mp = OUT_DIR / "reference_human_calibration_blinded_mapping.jsonl"
    with open(mp, "w", encoding="utf-8") as f:
        for r in out["mapping"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    sm = OUT_DIR / "reference_human_calibration_summary.json"
    with open(sm, "w", encoding="utf-8") as f:
        json.dump(out["summary"] | {"kc_ids": out["kc_ids"]}, f, indent=2, ensure_ascii=False)

    # Blinding self-check. The workbook is blinded against SYSTEM/MODEL identity, not against KC
    # identity - the reviewer must know which knowledge component they are assessing, so the
    # native-KC-id pattern (which exists to keep KC ids out of JUDGE prompts) does not apply here.
    # Every other forbidden pattern, including the retrieval-lane evidence-id form, does apply.
    import sys
    sys.path.insert(0, str(BASE))
    import reference_judge_prompts as P
    blob = wb.read_text(encoding="utf-8")
    kc_identity_pattern = r"KC_[A-Z]+_[A-Z]+_\d+"
    violations = []
    for pat in P._FORBIDDEN:
        if pat.pattern == kc_identity_pattern:
            continue  # legitimate and required in a human workbook
        m = pat.search(blob)
        if m:
            violations.append((pat.pattern, m.group(0)))
    print(json.dumps(out["summary"], indent=2))
    print(f"\nwrote {wb.name} ({len(out['workbook'])} rows)")
    print(f"wrote {mp.name} (arm identities, kept OUT of the workbook)")
    print(f"wrote {sm.name}")
    if violations:
        print(f"\nBLINDING VIOLATIONS IN WORKBOOK ({len(violations)}): {violations[:5]}")
        return 1
    print("\nblinding self-check: PASS - no identity-revealing token in the workbook file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
