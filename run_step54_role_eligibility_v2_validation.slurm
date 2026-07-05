#!/bin/bash
#SBATCH --job-name=step54_v2_val
#SBATCH --partition=gpu46GB
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --gres=gpu:a40:1
#SBATCH --output=logs/step54_role_eligibility_v2_validation_%j.out
#SBATCH --error=logs/step54_role_eligibility_v2_validation_%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

PY=/home/aryp26yc/venvs/kc_l_v2/bin/python

export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

echo "===== host ====="
hostname

echo
echo "===== slurm allocation ====="
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"
echo "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"

echo
echo "===== python sanity ====="
$PY -c "import sys; print(sys.executable); print(sys.version)"

echo
echo "===== working tree marker ====="
pwd
ls -lh src/kc_l/retrieval_gate/evidence_pack_composition.py
ls -lh tests/test_step54_evidence_pack_composition.py

echo
echo "===== compile check ====="
$PY -m py_compile \
  src/kc_l/retrieval_gate/evidence_pack_composition.py \
  tests/test_step54_evidence_pack_composition.py

echo
echo "===== direct tests ====="
$PY - <<'PY'
import tests.test_step54_evidence_pack_composition as mod

for name, obj in sorted(vars(mod).items()):
    if name.startswith("test_") and callable(obj):
        obj()
        print(name, "OK")

print("STEP54_DIRECT_TESTS_OK")
PY

echo
echo "===== run Step 5.4 regression slice ====="
RUN_ID="step54_role_eligibility_v2_r10_$(date +%Y%m%d_%H%M%S)"

$PY steps/step_05_4_evidence_pack_composition/scripts/run_step5_4_evidence_pack_composition.py \
  --config steps/step_05_4_evidence_pack_composition/resources/step5_4.regression_gemma_slice10.yaml \
  --run-id "$RUN_ID"

STEP54_SET=$(ls -1t data/processed/kc_evidence_packs/_sets/*_step5_4_kc_evidence_packs_set.json | head -n 1)
echo "STEP54_SET=$STEP54_SET"

echo
echo "===== create Step 6.6 override config ====="
STEP66_CFG="/tmp/step6_6.regression_gemma_slice10.with_step54_role_eligibility_v2.${SLURM_JOB_ID}.yaml"

STEP54_SET="$STEP54_SET" STEP66_CFG="$STEP66_CFG" $PY - <<'PY'
import os
from pathlib import Path
import yaml

base = Path("steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.regression_gemma_slice10.yaml")
cfg = yaml.safe_load(base.read_text(encoding="utf-8"))

cfg.setdefault("inputs", {})["step5_4_set_manifest"] = os.environ["STEP54_SET"]

out = Path(os.environ["STEP66_CFG"])
out.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
print(out)
PY

echo
echo "===== run Step 6.6 regression overlay ====="
$PY steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config "$STEP66_CFG"

STEP66_SET=$(ls -1t data/processed/kc_drafting_input_overlay/_sets/*_step6_6_kc_drafting_input_overlay_set.json | head -n 1)
echo "STEP66_SET=$STEP66_SET"

echo
echo "===== inspect Step 5.4 and Step 6.6 outputs ====="
STEP54_SET="$STEP54_SET" STEP66_SET="$STEP66_SET" $PY - <<'PY'
import json
import os
from pathlib import Path

root = Path(".")
step54_set = Path(os.environ["STEP54_SET"])
step66_set = Path(os.environ["STEP66_SET"])

step54_obj = json.loads(step54_set.read_text(encoding="utf-8"))
step66_obj = json.loads(step66_set.read_text(encoding="utf-8"))

packs_path = root / step54_obj["artifacts"]["kc_evidence_packs_jsonl"]
stats_path = root / step54_obj["artifacts"]["evidence_pack_stats_json"]

overlay_path = root / step66_obj["artifacts"]["candidate_sentence_overlay_jsonl"]
overlay_stats_path = root / step66_obj["artifacts"]["overlay_stats_json"]

stats = json.loads(stats_path.read_text(encoding="utf-8"))

print("step54_set_manifest =", step54_set.as_posix())
print("step54_stats_path =", stats_path.as_posix())
print("step66_set_manifest =", step66_set.as_posix())
print("step66_overlay_path =", overlay_path.as_posix())
print("step66_overlay_stats_path =", overlay_stats_path.as_posix())

print()
print("route_breakdown =", stats.get("route_breakdown", {}))
print("formula_dominance_risk_breakdown =", stats.get("formula_dominance_risk_breakdown", {}))
print("sibling_contamination_risk_breakdown =", stats.get("sibling_contamination_risk_breakdown", {}))
print("definition_anchor_present_count =", stats.get("definition_anchor_present_count"))
print("definition_anchor_natural_language_count =", stats.get("definition_anchor_natural_language_count"))
print("context_completion_used_count =", stats.get("context_completion_used_count"))
print("insufficient_reason_breakdown =", stats.get("insufficient_reason_breakdown", {}))

packs = [
    json.loads(line)
    for line in packs_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

bad_markers = {
    "KC_CLF_NB_011": [
        "decision tree classifier",
        "knn instances",
        "mar missing data mechanism",
        "patients have missing values",
    ],
    "KC_CLU_DBS_001": [
        "a border point is a point that is not a core point",
        "a border point is not a core point",
    ],
    "KC_CLU_DBS_003": [
        "random component of a measurement error",
        "notice that some of the noise points are",
    ],
    "KC_EVAL_SAMP_003": [
        "best choice of the hyper-parameter value",
    ],
    "KC_CLU_CORE_002": [
        "precision is only 0.167",
    ],
    "KC_CLU_EVAL_001": [
        "covariance of the random variable",
    ],
}

positive_roles = [
    "definition_kernel",
    "explanatory_gloss",
    "formula_notation",
    "scope_condition",
    "context_completion",
    "example_or_procedure",
]

watch_markers = {
    "KC_CLU_CORE_002": [
        "nearestneighbour distance",
        "nearest-neighbour distance",
        "nearest neighbour distance",
    ],
    "KC_CLU_EVAL_002": [
        "high-dimensional data leading to reduced classification accuracy",
    ],
}

violations = []
marker_failures = []
watch_hits = []

for row in sorted(packs, key=lambda r: r["kc_id"]):
    kc_id = row["kc_id"]
    name = row.get("canonical_name")
    route = row.get("pack_quality", {}).get("route")
    reasons = row.get("pack_quality", {}).get("insufficient_reasons", [])

    print()
    print("KC =", kc_id, "|", name)
    print("route =", route)
    print("insufficient_reasons =", reasons)

    ordered = row.get("ordered_pack_for_drafting", [])
    ordered_roles = [item.get("role") for item in ordered]
    print("ordered_roles =", ordered_roles)

    if "sibling_contrast" in ordered_roles:
        violations.append(kc_id)

    positive_texts = []
    for role in positive_roles:
        items = row.get("slots", {}).get(role, [])
        texts = [item.get("text", "") for item in items]
        if texts:
            print(role, "=", texts)
            positive_texts.extend(texts)

    merged = " ".join(t.lower() for t in positive_texts)

    matches = [
        marker
        for marker in bad_markers.get(kc_id, [])
        if marker.lower() in merged
    ]
    print("known_bad_marker_matches =", matches)

    if matches:
        marker_failures.append((kc_id, matches))

    watches = [
        marker
        for marker in watch_markers.get(kc_id, [])
        if marker.lower() in merged
    ]
    print("watch_marker_matches =", watches)

    if watches:
        watch_hits.append((kc_id, watches))

print()
print("sibling_contrast_ordered_pack_violations =", violations)
print("known_bad_marker_failures =", marker_failures)
print("watch_marker_hits =", watch_hits)

if violations:
    raise SystemExit("FAIL: sibling_contrast leaked into ordered_pack_for_drafting")

if marker_failures:
    raise SystemExit("FAIL: known bad markers remain in positive support")

print("PASS: hard Step 5.4 role eligibility checks passed on authoritative Sofja rerun")

if watch_hits:
    print("WATCH: suspicious but non-blocking positive support rows remain. Inspect before broader replay.")
else:
    print("WATCH: no extra watch markers found.")
PY
