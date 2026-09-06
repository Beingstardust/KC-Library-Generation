"""Part 4 sanity check: score the fixed 17-unit Tier-2 sample with Prometheus-2, loading the
model once and scoring across the three runs relevant to the sample's known verdicts:
  - fixab_resume_20260729 (baseline) - for the "strong" grounded exemplars
  - ablation_02_step5p_gemma4_12b_AND_step6_7_qwen3_6_27b - for qwen3.6:27b's honest "partial"
    units this session's manual Tier-2 read already confirmed were fine (not lower quality)
  - ablation_03_step5p_gemma4_12b_AND_step6_7_command_r_35b - for the two confirmed-wrong,
    overconfident command-r:35b cases (Density-Reachable/border conflation, Cosine Similarity
    invented numeric range) that a working judge MUST flag low

Hard gate (per task brief): do not proceed to corpus-wide scoring unless this passes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from compute_prometheus_scores import (  # noqa: E402
    PROMETHEUS_MODEL_DIR,
    build_prompt,
    parse_feedback_and_score,
    extract_claim_and_evidence,
)

REPO_ROOT = Path("/path/to/projects/kc_l_v2_clean")
SAMPLE_PATH = REPO_ROOT / "evaluation/fixed_tier2_sample_v1.json"

RUNS = {
    "fixab_resume_20260729": REPO_ROOT
    / "data/processed/step67_v2_postprocessed_review_source/fixab_resume_20260729/step67_v2_postprocessed_review_source.jsonl",
    "ablation_02_step5p_gemma4_12b_AND_step6_7_qwen3_6_27b": REPO_ROOT
    / "data/processed/step67_v2_postprocessed_review_source/ablation_02_step5p_gemma4_12b_AND_step6_7_qwen3_6_27b/step67_v2_postprocessed_review_source.jsonl",
    "ablation_03_step5p_gemma4_12b_AND_step6_7_command_r_35b": REPO_ROOT
    / "data/processed/step67_v2_postprocessed_review_source/ablation_03_step5p_gemma4_12b_AND_step6_7_command_r_35b/step67_v2_postprocessed_review_source.jsonl",
}

KNOWN_BAD_UNITS = {"KC_CLU_DBS_006", "KC_CLU_SIM_005"}  # in ablation_03 specifically

sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
unit_ids = [u["unit_id"] for u in sample["units"]]
unit_categories = {u["unit_id"]: u["category"] for u in sample["units"]}
print(f"Sample has {len(unit_ids)} units: {unit_ids}")

print(f"Loading tokenizer+model from {PROMETHEUS_MODEL_DIR} ...")
tokenizer = AutoTokenizer.from_pretrained(PROMETHEUS_MODEL_DIR)
model = AutoModelForCausalLM.from_pretrained(PROMETHEUS_MODEL_DIR, dtype=torch.bfloat16)
model = model.to("cuda")
model.eval()
print("Model loaded.")

all_results = {}
for run_id, jsonl_path in RUNS.items():
    print(f"\n=== Scoring {run_id} ===")
    rows = [json.loads(line) for line in open(jsonl_path, encoding="utf-8")]
    by_id = {}
    for row in rows:
        uid, claim, evidence, status = extract_claim_and_evidence(row)
        by_id[uid] = (claim, evidence, status)

    run_results = []
    for uid in unit_ids:
        if uid not in by_id:
            print(f"  {uid}: NOT FOUND in {run_id}, skipping")
            continue
        claim, evidence, status = by_id[uid]
        if not claim.strip() or not evidence.strip():
            print(f"  {uid}: empty claim/evidence, skipping")
            continue
        prompt = build_prompt(evidence, claim)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs, max_new_tokens=512, do_sample=False, temperature=None, top_p=None,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        feedback, score = parse_feedback_and_score(generated)
        run_results.append({
            "unit_id": uid, "category": unit_categories[uid], "draft_status": status,
            "prometheus_score": score, "prometheus_feedback": feedback,
        })
        flag = ""
        if run_id.endswith("command_r_35b") and uid in KNOWN_BAD_UNITS:
            flag = " <== EXPECT LOW (known-bad, confirmed wrong)"
        print(f"  {uid} [{unit_categories[uid]}, status={status}] -> score={score}{flag}")

    all_results[run_id] = run_results

out_path = REPO_ROOT / "evaluation/prometheus_scores/sanity_check_17unit.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
print(f"\nWrote {out_path}")

print("\n=== SANITY CHECK SUMMARY ===")
bad_scores = []
for r in all_results.get("ablation_03_step5p_gemma4_12b_AND_step6_7_command_r_35b", []):
    if r["unit_id"] in KNOWN_BAD_UNITS:
        bad_scores.append((r["unit_id"], r["prometheus_score"]))
        ok = r["prometheus_score"] is not None and r["prometheus_score"] <= 2
        print(f"KNOWN-BAD {r['unit_id']}: score={r['prometheus_score']} -> {'CORRECTLY FLAGGED LOW' if ok else 'MISSED (FAIL)'}")

partial_scores = []
for r in all_results.get("ablation_02_step5p_gemma4_12b_AND_step6_7_qwen3_6_27b", []):
    if r["draft_status"] == "partial":
        partial_scores.append((r["unit_id"], r["prometheus_score"]))
        print(f"qwen3.6:27b HONEST-PARTIAL {r['unit_id']}: score={r['prometheus_score']}")
