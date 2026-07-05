#!/bin/bash
#SBATCH --job-name=s66_v3p2
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=logs/s66_v3p2-%j.out
#SBATCH --error=logs/s66_v3p2-%j.err

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
echo "==== accepted v3 Stage 3 set guard ===="
STAGE3_SET="data/processed/evidence_stage_v3_evidence_packs/_sets/step5x_v3_evidence_packs_regression10_sofja_20260428_000418_step5x_v3_evidence_packs_set.json"
test -f "$STAGE3_SET" || { echo "MISSING Stage 3 set: $STAGE3_SET"; exit 1; }
echo "STAGE3_SET=$STAGE3_SET"

echo
echo "==== required Step 6.6 files ===="
for rel in \
  "src/kc_l/kc/drafting_input_overlay.py" \
  "steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py" \
  "steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.regression_gemma_slice10.yaml" \
  "src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== protect current Step 6.6 alias before run ===="
CURRENT_ALIAS="data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"
if [ -f "$CURRENT_ALIAS" ]; then
  BEFORE_ALIAS_HASH="$(sha256sum "$CURRENT_ALIAS")"
else
  BEFORE_ALIAS_HASH="MISSING"
fi
echo "BEFORE_ALIAS_HASH=$BEFORE_ALIAS_HASH"

echo
echo "==== create generated Step 6.6 config pinned to v3 Stage 3 packs ===="
STAMP="$(date -u +%Y%m%d_%H%M%S)"
BASE_CONFIG="steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.regression_gemma_slice10.yaml"
GENERATED_CONFIG="data/work/cache/generated_configs/step6_6.regression_gemma_slice10.with_stage3_v3_packs_v2_${STAMP}.yaml"

export BASE_CONFIG GENERATED_CONFIG STAGE3_SET

"$PY" - <<'PY'
import json
import os
from pathlib import Path

import yaml

base_path = Path(os.environ["BASE_CONFIG"])
out_path = Path(os.environ["GENERATED_CONFIG"])
stage3_set = os.environ["STAGE3_SET"]

cfg = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}

inputs = cfg.setdefault("inputs", {})
inputs["step5_4_set_manifest"] = stage3_set

if isinstance(cfg.get("input"), dict):
    cfg["input"]["step5_4_set_manifest"] = stage3_set

metadata = cfg.setdefault("metadata", {})
metadata["compatibility_test"] = "step6_6_with_step5x_v3_stage3_evidence_packs_v2"
metadata["stage3_v3_set_manifest"] = stage3_set
metadata["active_pointer_policy"] = "do_not_update_current_alias_or_active_pointer"
metadata["expected_overlay_row_unit"] = "candidate_sentence_overlay_rows_not_kc_rows"

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print("GENERATED_CONFIG =", out_path.as_posix())
print("CONFIG_JSON_PREVIEW =")
print(json.dumps(cfg, indent=2, ensure_ascii=False)[:4000])
PY

test -f "$GENERATED_CONFIG"

echo
echo "==== py_compile Step 6.6 compatibility surface ===="
"$PY" -m py_compile \
  src/kc_l/kc/drafting_input_overlay.py \
  steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py

echo
echo "==== run Step 6.6 with v3 Stage 3 pack set ===="
"$PY" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config "$GENERATED_CONFIG"

SET_PATH="$(ls -1t data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json | head -n 1)"
test -f "$SET_PATH" || { echo "MISSING Step 6.6 set after run"; exit 1; }
echo "SET_PATH=$SET_PATH"

echo
echo "==== build corrected compatibility assessment from exact Step 6.6 output ===="
SET_PATH="$SET_PATH" STAGE3_SET="$STAGE3_SET" "$PY" - <<'PY'
import json
import os
import re
from pathlib import Path
from collections import Counter

root = Path(".")
set_path = Path(os.environ["SET_PATH"])
stage3_set = os.environ["STAGE3_SET"]

set_obj = json.loads(set_path.read_text(encoding="utf-8"))
set_text = json.dumps(set_obj, ensure_ascii=False)

if stage3_set not in set_text and Path(stage3_set).name not in set_text:
    raise SystemExit("FAIL: Step 6.6 set manifest does not reference accepted v3 Stage 3 set")

artifacts = set_obj.get("artifacts") or {}

def pick_artifact(*names):
    for name in names:
        value = artifacts.get(name)
        if value:
            return root / value
    return None

overlay_path = pick_artifact(
    "candidate_sentence_overlay_jsonl",
    "kc_drafting_input_overlay_jsonl",
    "overlay_jsonl",
)

stats_path = pick_artifact(
    "overlay_stats_json",
    "candidate_sentence_overlay_stats_json",
    "stats_json",
)

manifest_path = pick_artifact(
    "overlay_manifest_json",
    "kc_drafting_input_overlay_manifest_json",
    "manifest_json",
)

if overlay_path is None:
    for key, value in artifacts.items():
        if isinstance(value, str) and value.endswith(".jsonl") and "overlay" in value:
            overlay_path = root / value
            break

if stats_path is None:
    for key, value in artifacts.items():
        if isinstance(value, str) and value.endswith(".json") and "stats" in value:
            stats_path = root / value
            break

if overlay_path is None or not overlay_path.exists():
    raise SystemExit(f"FAIL: could not locate overlay jsonl from artifacts: {artifacts}")

rows = [json.loads(line) for line in overlay_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = {}
if stats_path is not None and stats_path.exists():
    stats = json.loads(stats_path.read_text(encoding="utf-8"))

accepted_kcs = {
    "KC_CLF_NB_011",
    "KC_CLU_CORE_002",
    "KC_CLU_DBS_001",
    "KC_CLU_DBS_003",
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_CLU_EVAL_012",
    "KC_DE_PREP_003",
    "KC_EVAL_BASIC_005",
    "KC_EVAL_SAMP_003",
}

seen_kcs = {str(row.get("kc_id") or "") for row in rows}
missing_kcs = sorted(accepted_kcs - seen_kcs)
extra_kcs = sorted(seen_kcs - accepted_kcs)

kc_counts = dict(sorted(Counter(str(row.get("kc_id") or "") for row in rows).items()))

available_rows = [row for row in rows if row.get("evidence_pack_available") is True]
available_kcs = {str(row.get("kc_id") or "") for row in available_rows}
missing_pack_available_kcs = sorted(accepted_kcs - available_kcs)

positive_roles = [
    "definition_kernel",
    "explanatory_gloss",
    "scope_condition",
    "formula_notation",
    "example_or_procedure",
]

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

def norm(text):
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()

known_bad_positive_hits = {}
known_bad_ordered_hits = {}
positive_slots_by_kc = {}
ordered_roles_by_kc = {}

for row in rows:
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

    if positive_summary and kc_id not in positive_slots_by_kc:
        positive_slots_by_kc[kc_id] = positive_summary

    if kc_id not in ordered_roles_by_kc:
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

assessment = {
    "step6_6_set_manifest": set_path.as_posix(),
    "stage3_v3_set_manifest": stage3_set,
    "overlay_path": overlay_path.as_posix(),
    "stats_path": stats_path.as_posix() if stats_path else "",
    "manifest_path": manifest_path.as_posix() if manifest_path else "",
    "expected_row_unit": "candidate_sentence_overlay_rows",
    "expected_pack_unit": "kc_evidence_pack_rows",
    "row_count": len(rows),
    "expected_row_count_for_regression10": 180,
    "kc_counts": kc_counts,
    "seen_kcs": sorted(seen_kcs),
    "missing_kcs": missing_kcs,
    "extra_kcs": extra_kcs,
    "evidence_pack_available_count_from_rows": len(available_rows),
    "evidence_pack_available_kcs": sorted(available_kcs),
    "missing_pack_available_kcs": missing_pack_available_kcs,
    "stats": stats,
    "positive_slots_by_kc": positive_slots_by_kc,
    "ordered_roles_by_kc": ordered_roles_by_kc,
    "known_bad_positive_hits": known_bad_positive_hits,
    "known_bad_ordered_hits": known_bad_ordered_hits,
}

out = root / "data/work/cache/diagnostics" / f"{set_path.stem}_stage3_v3_compat_assessment_v2.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("SET_PATH =", set_path.as_posix())
print("OVERLAY_PATH =", overlay_path.as_posix())
print("STATS_PATH =", stats_path.as_posix() if stats_path else "")
print("ASSESSMENT_JSON =", out.as_posix())
print("row_count =", len(rows))
print("kc_counts =", json.dumps(kc_counts, indent=2, ensure_ascii=False))
print("missing_kcs =", missing_kcs)
print("extra_kcs =", extra_kcs)
print("evidence_pack_available_count_from_rows =", len(available_rows))
print("evidence_pack_available_kc_count =", len(available_kcs))
print("missing_pack_available_kcs =", missing_pack_available_kcs)
print("stats_evidence_pack_available_count =", stats.get("evidence_pack_available_count"))
print("known_bad_positive_hits =", json.dumps(known_bad_positive_hits, indent=2, ensure_ascii=False))
print("known_bad_ordered_hits =", json.dumps(known_bad_ordered_hits, indent=2, ensure_ascii=False))
print("positive_slots_by_kc =", json.dumps(positive_slots_by_kc, indent=2, ensure_ascii=False))

if len(rows) != 180:
    raise SystemExit(f"FAIL: expected 180 Step 6.6 overlay rows for this regression slice, got {len(rows)}")
if missing_kcs or extra_kcs:
    raise SystemExit("FAIL: Step 6.6 KC set mismatch")
if any(count != 18 for count in kc_counts.values()):
    raise SystemExit("FAIL: expected 18 overlay rows per KC in this regression slice")
if len(available_kcs) != 10:
    raise SystemExit("FAIL: expected evidence packs attached for all 10 KCs")
if stats.get("evidence_pack_available_count") != 10:
    raise SystemExit("FAIL: Step 6.6 stats did not report 10 evidence packs available")
if missing_pack_available_kcs:
    raise SystemExit("FAIL: some v3 Stage 3 packs were not attached in Step 6.6")
if known_bad_positive_hits:
    raise SystemExit("FAIL: known bad markers leaked into Step 6.6 positive evidence slots")
if known_bad_ordered_hits:
    raise SystemExit("FAIL: known bad markers leaked into Step 6.6 ordered drafting pack")

print("STEP6_6_WITH_STAGE3_V3_PACKS_COMPAT_ASSESSMENT_V2_OK")
PY

echo
echo "==== protect current Step 6.6 alias after run ===="
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
find data/processed/kc_drafting_input_overlay/_sets -maxdepth 1 -type f -name 'ACTIVE*STEP6*' -print 2>/dev/null || true

echo
echo "PIPELINE_STEP6_6_WITH_STAGE3_V3_PACKS_COMPAT_V2_OK"
