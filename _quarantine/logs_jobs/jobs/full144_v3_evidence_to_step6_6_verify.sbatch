#!/bin/bash
#SBATCH --job-name=v3full66
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/v3full66-%j.out
#SBATCH --error=logs/v3full66-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "==== job context ===="
date -u
hostname
echo "PWD=$PWD"
echo "PY=$PY"
"$PY" --version

echo
echo "==== required source files ===="
for rel in \
  "src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py" \
  "src/kc_l/retrieval_gate/evidence_stage_v3_scored_candidates.py" \
  "src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py" \
  "src/kc_l/kc/drafting_input_overlay.py" \
  "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py" \
  "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py" \
  "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py" \
  "steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py" \
  "steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.sofja.actual_corpus.yaml"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== fixed full Step 5.3 source set ===="
STEP53_SET="data/processed/kc_evidence_recalibrated/_sets/2026-04-26_195746_step5_3_kc_evidence_recalibrated_set.json"

if [ ! -f "$STEP53_SET" ]; then
  echo "MISSING fixed Step 5.3 set: $STEP53_SET"
  echo "Available Step 5.3 sets:"
  ls -1 data/processed/kc_evidence_recalibrated/_sets/*step5_3*json 2>/dev/null || true
  exit 1
fi

echo "STEP53_SET=$STEP53_SET"

echo
echo "==== protect current Step 6.6 alias before full run ===="
CURRENT_ALIAS="data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"

if [ -f "$CURRENT_ALIAS" ]; then
  BEFORE_ALIAS_HASH="$(sha256sum "$CURRENT_ALIAS")"
else
  BEFORE_ALIAS_HASH="MISSING"
fi

echo "BEFORE_ALIAS_HASH=$BEFORE_ALIAS_HASH"

echo
echo "==== py_compile full v3 surface ===="
"$PY" -m py_compile \
  src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py \
  src/kc_l/retrieval_gate/evidence_stage_v3_scored_candidates.py \
  src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py \
  src/kc_l/kc/drafting_input_overlay.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py \
  steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py

echo
echo "==== run Stage 1 full candidate bank ===="
STAMP="$(date -u +%Y%m%d_%H%M%S)"
RUN1="step5x_v3_candidate_bank_full144_sofja_${STAMP}"

"$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py \
  --step5-3-set-manifest "$STEP53_SET" \
  --run-id "$RUN1"

STAGE1_SET="data/processed/evidence_stage_v3_candidate_bank/_sets/${RUN1}_step5x_v3_candidate_bank_set.json"
test -f "$STAGE1_SET" || { echo "MISSING Stage 1 full set: $STAGE1_SET"; exit 1; }

echo "STAGE1_SET=$STAGE1_SET"

echo
echo "==== run Stage 2 full scored candidates ===="
RUN2="step5x_v3_scored_candidates_full144_sofja_${STAMP}"

"$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py \
  --step5x-v3-set-manifest "$STAGE1_SET" \
  --run-id "$RUN2"

STAGE2_SET="data/processed/evidence_stage_v3_scored_candidates/_sets/${RUN2}_step5x_v3_scored_candidates_set.json"
test -f "$STAGE2_SET" || { echo "MISSING Stage 2 full set: $STAGE2_SET"; exit 1; }

echo "STAGE2_SET=$STAGE2_SET"

echo
echo "==== run Stage 3 full evidence packs ===="
RUN3="step5x_v3_evidence_packs_full144_sofja_${STAMP}"

"$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py \
  --step5x-v3-scored-set-manifest "$STAGE2_SET" \
  --run-id "$RUN3"

STAGE3_SET="data/processed/evidence_stage_v3_evidence_packs/_sets/${RUN3}_step5x_v3_evidence_packs_set.json"
test -f "$STAGE3_SET" || { echo "MISSING Stage 3 full set: $STAGE3_SET"; exit 1; }

echo "STAGE3_SET=$STAGE3_SET"

echo
echo "==== create Step 6.6 full config pinned to Stage 3 v3 full packs ===="
BASE66="steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.sofja.actual_corpus.yaml"
GEN66="data/work/cache/generated_configs/step6_6.sofja.actual_corpus.with_stage3_v3_full144_${STAMP}.yaml"

export BASE66 GEN66 STAGE3_SET

"$PY" - <<'PY'
import json
import os
from pathlib import Path

import yaml

base = Path(os.environ["BASE66"])
out = Path(os.environ["GEN66"])
stage3_set = os.environ["STAGE3_SET"]

cfg = yaml.safe_load(base.read_text(encoding="utf-8")) or {}

inputs = cfg.setdefault("inputs", {})
inputs["step5_4_set_manifest"] = stage3_set

if isinstance(cfg.get("input"), dict):
    cfg["input"]["step5_4_set_manifest"] = stage3_set

cfg.pop("slice", None)

metadata = cfg.setdefault("metadata", {})
metadata["compatibility_test"] = "full144_step6_6_with_step5x_v3_stage3_evidence_packs"
metadata["stage3_v3_set_manifest"] = stage3_set
metadata["active_pointer_policy"] = "do_not_update_current_alias_or_active_pointer"
metadata["expected_scope"] = "full_144_kc_actual_corpus"

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print("GEN66 =", out.as_posix())
print("CONFIG_PREVIEW =")
print(json.dumps(cfg, indent=2, ensure_ascii=False)[:5000])
PY

test -f "$GEN66"

echo
echo "==== run Step 6.6 full compatibility overlay ===="
"$PY" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config "$GEN66"

STEP66_SET="$(ls -1t data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json | head -n 1)"
test -f "$STEP66_SET" || { echo "MISSING latest Step 6.6 set"; exit 1; }

echo "STEP66_SET=$STEP66_SET"

echo
echo "==== full144 semantic and contract assessment ===="
STEP53_SET="$STEP53_SET" \
STAGE1_SET="$STAGE1_SET" \
STAGE2_SET="$STAGE2_SET" \
STAGE3_SET="$STAGE3_SET" \
STEP66_SET="$STEP66_SET" \
GEN66="$GEN66" \
STAMP="$STAMP" \
"$PY" - <<'PY'
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

root = Path(".")

stage1_set = Path(os.environ["STAGE1_SET"])
stage2_set = Path(os.environ["STAGE2_SET"])
stage3_set = Path(os.environ["STAGE3_SET"])
step66_set = Path(os.environ["STEP66_SET"])
gen66 = Path(os.environ["GEN66"])
stamp = os.environ["STAMP"]

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def norm(text):
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()

def artifact_path(set_obj, *keys):
    artifacts = set_obj.get("artifacts") or {}
    for key in keys:
        value = artifacts.get(key)
        if value:
            return root / value
    return None

stage1_obj = read_json(stage1_set)
stage2_obj = read_json(stage2_set)
stage3_obj = read_json(stage3_set)
step66_obj = read_json(step66_set)

stage1_stats_path = artifact_path(stage1_obj, "candidate_bank_stats_json")
stage2_stats_path = artifact_path(stage2_obj, "scored_candidate_stats_json")
stage3_stats_path = artifact_path(stage3_obj, "evidence_pack_stats_json")
stage3_packs_path = artifact_path(stage3_obj, "kc_evidence_packs_jsonl")

step66_overlay_path = artifact_path(
    step66_obj,
    "candidate_sentence_overlay_jsonl",
    "kc_drafting_input_overlay_jsonl",
    "overlay_jsonl",
)
step66_stats_path = artifact_path(
    step66_obj,
    "overlay_stats_json",
    "candidate_sentence_overlay_stats_json",
    "stats_json",
)

if step66_overlay_path is None:
    for key, value in (step66_obj.get("artifacts") or {}).items():
        if isinstance(value, str) and value.endswith(".jsonl") and "overlay" in value:
            step66_overlay_path = root / value
            break

if step66_stats_path is None:
    for key, value in (step66_obj.get("artifacts") or {}).items():
        if isinstance(value, str) and value.endswith(".json") and "stats" in value:
            step66_stats_path = root / value
            break

required_paths = [
    stage1_stats_path,
    stage2_stats_path,
    stage3_stats_path,
    stage3_packs_path,
    step66_overlay_path,
    step66_stats_path,
]

missing_artifacts = [str(p) for p in required_paths if p is None or not p.exists()]
if missing_artifacts:
    raise SystemExit(f"FAIL: missing assessment artifacts: {missing_artifacts}")

stage1_stats = read_json(stage1_stats_path)
stage2_stats = read_json(stage2_stats_path)
stage3_stats = read_json(stage3_stats_path)
stage3_packs = read_jsonl(stage3_packs_path)
step66_rows = read_jsonl(step66_overlay_path)
step66_stats = read_json(step66_stats_path)

stage3_kcs = {str(pack.get("kc_id") or "") for pack in stage3_packs}
step66_kcs = {str(row.get("kc_id") or "") for row in step66_rows}

missing_step66_kcs = sorted(stage3_kcs - step66_kcs)
extra_step66_kcs = sorted(step66_kcs - stage3_kcs)

stage3_pack_count = len(stage3_packs)
stage3_duplicate_kcs = sorted([kc for kc, n in Counter([pack.get("kc_id") for pack in stage3_packs]).items() if n > 1])

step66_kc_counts = dict(sorted(Counter([row.get("kc_id") for row in step66_rows]).items()))

known_bad = {
    "KC_CLF_NB_011": [
        "decision tree classifier",
        "knn instances",
        "mar missing data mechanism",
        "patients have missing values",
    ],
    "KC_CLU_DBS_001": [
        "neighborhood of a core point.",
        "a border point is a point that is not a core point",
        "a border point is not a core point",
        "given the previous definitions of core points, border points, and noise points",
    ],
    "KC_CLU_DBS_003": [
        "random component of a measurement error",
        "notice that some of the noise points are",
    ],
    "KC_EVAL_SAMP_003": [
        "best choice of the hyper-parameter value",
        "hyper-parameter",
        "common mistakes while using cross-validation",
    ],
    "KC_CLU_EVAL_001": [
        "covariance",
    ],
}

positive_roles = [
    "definition_kernel",
    "explanatory_gloss",
    "scope_condition",
    "formula_notation",
    "example_or_procedure",
]

known_bad_positive_hits = {}
known_bad_ordered_hits = {}
positive_slots_by_kc = {}
ordered_roles_by_kc = {}

for row in step66_rows:
    kc_id = str(row.get("kc_id") or "")
    slots = row.get("evidence_pack_slots") or {}
    ordered = row.get("ordered_pack_for_drafting") or []

    positive_summary = {}
    positive_texts = []

    for role in positive_roles:
        items = slots.get(role) or []
        if items:
            positive_summary[role] = [item.get("text") or item.get("quote") for item in items]
        for item in items:
            positive_texts.append(str(item.get("text") or item.get("quote") or ""))

    if positive_summary:
        positive_slots_by_kc[kc_id] = positive_summary

    ordered_roles_by_kc[kc_id] = [str(item.get("role") or "") for item in ordered]

    for marker in known_bad.get(kc_id, []):
        marker_norm = norm(marker)

        for text in positive_texts:
            if marker_norm and marker_norm in norm(text):
                known_bad_positive_hits.setdefault(kc_id, []).append({
                    "marker": marker,
                    "text": text,
                })

        for item in ordered:
            text = str(item.get("text") or item.get("quote") or "")
            if marker_norm and marker_norm in norm(text):
                known_bad_ordered_hits.setdefault(kc_id, []).append({
                    "marker": marker,
                    "role": item.get("role"),
                    "text": text,
                })

ordered_sibling_leaks = []
for pack in stage3_packs:
    kc_id = str(pack.get("kc_id") or "")
    for item in pack.get("ordered_pack_for_drafting") or []:
        if str(item.get("role") or "") == "sibling_contrast":
            ordered_sibling_leaks.append(kc_id)

assessment = {
    "stamp": stamp,
    "stage1_set": stage1_set.as_posix(),
    "stage2_set": stage2_set.as_posix(),
    "stage3_set": stage3_set.as_posix(),
    "step66_set": step66_set.as_posix(),
    "generated_step66_config": gen66.as_posix(),
    "stage1_stats_path": stage1_stats_path.as_posix(),
    "stage2_stats_path": stage2_stats_path.as_posix(),
    "stage3_stats_path": stage3_stats_path.as_posix(),
    "stage3_packs_path": stage3_packs_path.as_posix(),
    "step66_overlay_path": step66_overlay_path.as_posix(),
    "step66_stats_path": step66_stats_path.as_posix(),
    "stage1_stats": stage1_stats,
    "stage2_stats": stage2_stats,
    "stage3_stats": stage3_stats,
    "step66_stats": step66_stats,
    "stage3_pack_count": stage3_pack_count,
    "stage3_unique_kc_count": len(stage3_kcs),
    "stage3_duplicate_kcs": stage3_duplicate_kcs,
    "step66_row_count": len(step66_rows),
    "step66_unique_kc_count": len(step66_kcs),
    "step66_kc_counts": step66_kc_counts,
    "missing_step66_kcs": missing_step66_kcs,
    "extra_step66_kcs": extra_step66_kcs,
    "ordered_sibling_leaks": ordered_sibling_leaks,
    "known_bad_positive_hits": known_bad_positive_hits,
    "known_bad_ordered_hits": known_bad_ordered_hits,
    "positive_slots_by_kc": positive_slots_by_kc,
    "ordered_roles_by_kc": ordered_roles_by_kc,
}

out = root / "data/work/cache/diagnostics" / f"full144_v3_evidence_to_step6_6_assessment_{stamp}.json"
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("ASSESSMENT_JSON =", out.as_posix())
print("stage1_total_kc_rows_seen =", stage1_stats.get("total_kc_rows_seen"))
print("stage1_total_candidate_rows_emitted =", stage1_stats.get("total_candidate_rows_emitted"))
print("stage1_kcs_with_candidates =", stage1_stats.get("kcs_with_candidates"))
print("stage1_kcs_without_candidates =", stage1_stats.get("kcs_without_candidates"))
print("stage2_total_scored_candidates_emitted =", stage2_stats.get("total_scored_candidates_emitted"))
print("stage3_pack_count =", stage3_pack_count)
print("stage3_unique_kc_count =", len(stage3_kcs))
print("stage3_duplicate_kcs =", stage3_duplicate_kcs)
print("stage3_route_breakdown =", stage3_stats.get("route_breakdown"))
print("stage3_slot_item_count_breakdown =", stage3_stats.get("slot_item_count_breakdown"))
print("stage3_ordered_role_breakdown =", stage3_stats.get("ordered_role_breakdown"))
print("step66_row_count =", len(step66_rows))
print("step66_unique_kc_count =", len(step66_kcs))
print("step66_stats_evidence_pack_available_count =", step66_stats.get("evidence_pack_available_count"))
print("missing_step66_kcs =", missing_step66_kcs)
print("extra_step66_kcs =", extra_step66_kcs)
print("ordered_sibling_leaks =", ordered_sibling_leaks)
print("known_bad_positive_hits =", json.dumps(known_bad_positive_hits, indent=2, ensure_ascii=False))
print("known_bad_ordered_hits =", json.dumps(known_bad_ordered_hits, indent=2, ensure_ascii=False))

if stage1_stats.get("total_kc_rows_seen") != 144:
    raise SystemExit("FAIL: Stage 1 did not see 144 KC rows")

if stage3_pack_count != 144:
    raise SystemExit(f"FAIL: Stage 3 did not emit 144 packs, got {stage3_pack_count}")

if len(stage3_kcs) != 144:
    raise SystemExit(f"FAIL: Stage 3 unique KC count is not 144, got {len(stage3_kcs)}")

if stage3_duplicate_kcs:
    raise SystemExit("FAIL: Stage 3 emitted duplicate KC packs")

if missing_step66_kcs or extra_step66_kcs:
    raise SystemExit("FAIL: Step 6.6 KC set does not match Stage 3 KC set")

if len(step66_kcs) != 144:
    raise SystemExit(f"FAIL: Step 6.6 unique KC count is not 144, got {len(step66_kcs)}")

if ordered_sibling_leaks:
    raise SystemExit("FAIL: sibling_contrast leaked into ordered drafting pack")

if known_bad_positive_hits:
    raise SystemExit("FAIL: known bad markers leaked into Step 6.6 positive evidence slots")

if known_bad_ordered_hits:
    raise SystemExit("FAIL: known bad markers leaked into Step 6.6 ordered drafting pack")

print("FULL144_V3_EVIDENCE_TO_STEP6_6_ASSESSMENT_OK")
PY

echo
echo "==== protect current Step 6.6 alias after full run ===="
if [ -f "$CURRENT_ALIAS" ]; then
  AFTER_ALIAS_HASH="$(sha256sum "$CURRENT_ALIAS")"
else
  AFTER_ALIAS_HASH="MISSING"
fi

echo "AFTER_ALIAS_HASH=$AFTER_ALIAS_HASH"

if [ "$BEFORE_ALIAS_HASH" != "$AFTER_ALIAS_HASH" ]; then
  echo "FAIL: current Step 6.6 alias changed unexpectedly"
  exit 1
fi

echo
echo "==== active/current pointer guard ===="
find data/work/cache/current_step_artifacts -maxdepth 1 -type f -name 'step6_6_set_manifest.current.json' -print
find data/processed/evidence_stage_v3_candidate_bank/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' -print 2>/dev/null || true
find data/processed/evidence_stage_v3_scored_candidates/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' -print 2>/dev/null || true
find data/processed/evidence_stage_v3_evidence_packs/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' -print 2>/dev/null || true

echo
echo "FULL144_V3_EVIDENCE_TO_STEP6_6_PIPELINE_OK"
