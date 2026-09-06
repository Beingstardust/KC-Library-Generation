"""Write EVALUATION_SCOPE_AMENDMENT_v2.json and calibration_scope_v2.json.

These are ADDITIVE. No existing lock is destroyed or rewritten - the amendment records a scope
change alongside the existing locks so the prior scope remains auditable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
REFEVAL = BASE.parent
FINAL = REFEVAL.parent
REFLIB = FINAL / "reference_library"


def sha(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

amendment = {
    "amendment_id": "EVALUATION_SCOPE_AMENDMENT_v2",
    "timestamp_utc": now,
    "supersedes": "the original M4 design recorded in paper_methods/CLAIM_EVALUATION_METHOD.md and "
                   "reference_eval/reference_judge_schema.py prior to this date",
    "change_summary": "M4 is split into a retained decomposed retrieval-coverage metric (M4A) and a "
                       "demoted exploratory holistic evidence-adequacy classifier (M4B).",

    "prior_m4_design": {
        "task": "M4_EVIDENCE_ADEQUACY",
        "labels": ["EVIDENCE_ADEQUATE", "MATERIAL_EVIDENCE_GAP", "NOT_JUDGEABLE"],
        "inputs": "target KC, hierarchy, the COMPLETE expert reference, and the candidate system evidence",
        "intended_construct": "whether the supplied evidence collectively contained enough material for "
                               "someone to write an adequate, correct description of the KC",
        "intended_use": "holistic binary reported alongside the continuous retrieval recall",
    },

    "observed_sentinel_failure_pattern": {
        "measurement": "18 of 25 judgeable cases whose gold was EVIDENCE_ADEQUATE were returned as "
                        "MATERIAL_EVIDENCE_GAP (agreement 28.0%). FAIL-recall was 100% and false-PASS "
                        "was 0 - the classifier is not permissive, it is systematically over-strict.",
        "mechanism_established_by_direct_inspection": "The enumerated 'missing' items are phrases drawn "
            "from the EXPERT REFERENCE itself rather than genuinely defining content. For a K-Means "
            "case the judge listed 'the algorithm is simple and is guaranteed to converge' and 'random "
            "initialization is often used' as missing evidence - reference enrichment that is not "
            "required to draft an adequate K-Means KC. The judge treats the full reference as an "
            "exhaustive checklist despite the prompt explicitly instructing that the evidence need not "
            "contain everything in the reference.",
        "prior_occurrence": "Structurally identical to the v3 F4/F5 all-requirements aggregation failure "
            "recorded in output/r9_final/source_artifact_manifest.json, where handing the judge a full "
            "requirement ledger plus a holistic sufficiency question produced zero false-passes while "
            "wrongly failing 14/34 and 16/36 correct cases - and where the same pattern reproduced "
            "across two independently trained 70B judges.",
    },

    "reason_for_demotion": "This is a construct-validity failure, not a prompting defect. The holistic "
        "question is a counterfactual - 'would this evidence have been enough?' - and supplying the "
        "reference as the standard reliably collapses it into 'does the evidence contain everything in "
        "the reference?'. Two independent lines of evidence (the v3 F4/F5 history and this run) show the "
        "failure survives rewording and model substitution, so it is not addressable by tuning. It was "
        "therefore demoted rather than iterated on.",

    "explicitly_not_done": [
        "No prompt tuning was applied to rescue the holistic task.",
        "No alternative holistic evidence-sufficiency wording was created.",
        "No further model substitution was attempted for this construct.",
        "No prior development output was deleted; run 3 is preserved as "
        "selene_reference_sentinel_raw.PRE_FIELDORDER_FIX.json for the audit trail.",
    ],

    "current_primary_metrics": {
        "M1_EVIDENCE_FAITHFULNESS": "candidate claims vs the evidence supplied to that drafter",
        "M2_REFERENCE_SOURCE_CORRECTNESS": "candidate claims vs expert reference + source authority, "
                                            "with the mandatory REFERENCE_SILENT_BUT_SOURCE_SUPPORTED escape path",
        "M3_CORE_COMPLETENESS": "holistic CORE_COMPLETE / MATERIAL_OMISSION - remains the primary M3 binary",
        "M3_REFERENCE_CLAIM_COVERAGE": "descriptive continuous coverage; never converted into an "
                                        "all-or-nothing completeness verdict",
        "TARGET_ALIGNMENT": "does the candidate's central defining content describe the same KC as the reference",
        "M4A_RETRIEVAL_REFERENCE_COVERAGE": "retrieval_reference_recall = reference claims supported by "
                                             "candidate evidence / total substantive reference claims",
    },

    "current_exploratory_metrics": {
        "EXPLORATORY_HOLISTIC_EVIDENCE_ADEQUACY": {
            "former_name": "M4_EVIDENCE_ADEQUACY",
            "primary_use": False,
            "qualification_gate": False,
            "derived_metric_dependency": False,
            "permitted": ["exploratory diagnostic", "optional human-calibration research output"],
            "forbidden": ["primary metric", "materially_sound", "judge qualification gating",
                           "intrinsic comparison", "extrinsic comparison",
                           "system success/failure classification", "automatic abstention validity"],
        }
    },

    "materially_sound_unchanged": {
        "definition": "draft_exists AND target_aligned AND faithfulness_precision == 1.0 AND "
                       "authority_correctness_precision == 1.0 AND core_complete",
        "verified": "Neither retrieval_reference_recall nor holistic adequacy appears in the derivation; "
                     "verified programmatically against the source of reference_metrics.derive_per_kc.",
        "rationale": "materially_sound measures the final KC draft. Retrieval coverage is an upstream "
                      "explanatory metric and must not become a condition of draft quality.",
    },

    "terminology_rule": "M4A is to be called reference-claim retrieval recall / retrieval coverage / "
                         "reference-content coverage by retrieval. It must NOT be labelled 'evidence "
                         "sufficiency' except when discussing it descriptively, because claim recall "
                         "below 1.0 does not imply the evidence was insufficient.",

    "timing_statement": {
        "made_before_human_calibration": True,
        "made_before_any_final_system_ranking_was_inspected": True,
        "statement": "This change was made during development-stage sentinel testing, before the locked "
                      "human qualification stage and before any intrinsic or extrinsic system comparison "
                      "was run or inspected. No candidate ranking, no arm unblinding, and no final "
                      "campaign result informed it. It is a methodological correction to the measurement "
                      "instrument, NOT a post-hoc correction to system results.",
    },

    "hashes_affected_prompt_and_schema_files": {
        "reference_judge_schema.py": sha(REFEVAL / "reference_judge_schema.py"),
        "reference_judge_prompts.py": sha(REFEVAL / "reference_judge_prompts.py"),
        "reference_metrics.py": sha(REFEVAL / "reference_metrics.py"),
        "reference_claim_schema.py": sha(REFEVAL / "reference_claim_schema.py"),
        "run_reference_judge.py": sha(REFEVAL / "run_reference_judge.py"),
        "analyze_reference_sentinels.py": sha(REFEVAL / "analyze_reference_sentinels.py"),
    },

    "hashes_unchanged_artifacts": {
        "expert_adjudicated_reference_kc_library.jsonl": sha(REFLIB / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"),
        "expert_adjudicated_reference_manifest.json": sha(REFLIB / "04_gold" / "expert_adjudicated_reference_manifest.json"),
        "reference_provenance_resolution.jsonl": sha(REFLIB / "04_gold" / "reference_provenance_resolution.jsonl"),
        "CANDIDATE_FREEZE_MANIFEST.json": sha(REFLIB / "00_freeze" / "CANDIDATE_FREEZE_MANIFEST.json"),
        "candidates_frozen.lock.json": sha(REFLIB / "00_freeze" / "candidates_frozen.lock.json"),
        "note": "No candidate artifact and no reference content was changed by this amendment. The "
                 "expert reference and all 7 candidate arms are untouched.",
    },

    "serialization_fix_recorded_separately": {
        "what": "rationale moved BEFORE the decision fields in the holistic and target schemas; free-text "
                 "fields length-bounded; the empty-list branch dropped from clean holistic verdicts.",
        "why": "Responses stalled after committing a verdict because inter-token whitespace was the only "
                "legal continuation, producing near-empty bodies and truncation (one target response: 145 "
                "characters of content in a 98.4% whitespace body).",
        "classification": "INFRASTRUCTURE / SERIALIZATION FIX - not semantic rubric tuning. Prompt text "
                           "and label semantics are unchanged.",
    },
}

p1 = BASE / "EVALUATION_SCOPE_AMENDMENT_v2.json"
p1.write_text(json.dumps(amendment, indent=2, ensure_ascii=False), encoding="utf-8")

CAL = REFEVAL / "output" / "human_calibration"
calibration = {
    "scope_id": "calibration_scope_v2",
    "timestamp_utc": now,
    "sample_status": "UNCHANGED - the frozen 180 rows are preserved exactly",
    "why_unchanged": "Resampling after a metric-scope change would introduce an additional researcher "
                      "degree of freedom. The sample was drawn before the M4 decision and is retained "
                      "verbatim; only its metadata is versioned.",
    "preserved": {
        "sampled_kc_identities": True, "arm_assignments": True, "random_seed": 20260825,
        "stratification": True, "row_order_and_blinding_mapping": True,
    },
    "n_kc": 30, "n_arms": 6, "n_rows": 180,
    "workbook": str((CAL / "reference_human_calibration_workbook.jsonl").relative_to(FINAL)),
    "workbook_sha256": sha(CAL / "reference_human_calibration_workbook.jsonl"),
    "blinded_mapping": str((CAL / "reference_human_calibration_blinded_mapping.jsonl").relative_to(FINAL)),
    "blinded_mapping_sha256": sha(CAL / "reference_human_calibration_blinded_mapping.jsonl"),

    "task_scope": {
        "M1_claim_faithfulness": "PRIMARY - qualification gating",
        "M2_claim_source_correctness": "PRIMARY - qualification gating",
        "M3_holistic_core_completeness": "PRIMARY - qualification gating",
        "TARGET_alignment": "PRIMARY - qualification gating",
        "M4A_reference_claim_retrieval_support": "PRIMARY retrieval diagnostic - must also be "
            "human-validated on a bounded subset to confirm the per-claim support classification is "
            "reliable, but it is a decomposed per-claim task rather than a holistic verdict",
        "M4B_holistic_evidence_adequacy": "EXPLORATORY_NON_PRIMARY - may optionally be collected for "
            "research purposes. Must NOT be used for judge qualification, system ranking, "
            "materially_sound, or primary statistical testing.",
    },

    "seed_bias_diagnostics_retained": [
        "VALID_SOURCE_SUPPORTED_ALTERNATIVE_BEYOND_REFERENCE",
        "POSSIBLE_REFERENCE_DEFECT",
    ],
    "blinding": "The human evaluator remains blind to model identity, system identity, retrieval "
                 "architecture, the machine-seed origin of the reference, machine draft status, previous "
                 "judge output, and previous sentinel outcomes.",
    "note_on_workbook_fields": "If the workbook carries a holistic adequacy field it is retained for "
                                "audit/exploratory annotation and is marked EXPLORATORY_NON_PRIMARY; it "
                                "is not consumed by any qualification or ranking computation.",
}
p2 = CAL / "calibration_scope_v2.json"
p2.write_text(json.dumps(calibration, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"wrote {p1.name}")
print(f"wrote {p2.relative_to(FINAL)}")
