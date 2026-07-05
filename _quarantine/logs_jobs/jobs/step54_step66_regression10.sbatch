#!/usr/bin/env bash
#SBATCH --job-name=s54_66_r10
#SBATCH --partition=gpu46GB
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --output=logs/s54_66_r10-%j.out
#SBATCH --error=logs/s54_66_r10-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "==== job context ===="
date -u
hostname
echo "PYTHON_BIN=$PYTHON_BIN"
"$PYTHON_BIN" --version

echo
echo "==== preflight active Step 5.3 pointer ===="
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json

pointer = Path("data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt")
print("ACTIVE_STEP5_3_POINTER", pointer)
print("EXISTS", pointer.exists())

if not pointer.exists():
    raise SystemExit("FAIL: ACTIVE_STEP5_3_EVIDENCE_SET.txt is missing")

target = Path(pointer.read_text(encoding="utf-8").strip())
if not target.is_absolute():
    target = (pointer.parent / target).resolve()

print("ACTIVE_STEP5_3_TARGET", target)
print("TARGET_EXISTS", target.exists())

if not target.exists():
    raise SystemExit("FAIL: active Step 5.3 set manifest target is missing")

obj = json.loads(target.read_text(encoding="utf-8"))
print("STEP5_3_SET_ID", obj.get("set_id"))
print("STEP5_3_RUN_ID", obj.get("run_id") or obj.get("run_id_step5_3"))
print("STEP5_3_ARTIFACTS", obj.get("artifacts", {}))
PY

RUN_ID="step54_regression_slice10_$(date -u +%Y%m%d_%H%M%S)"

echo
echo "==== Step 5.4 regression slice ===="
"$PYTHON_BIN" steps/step_05_4_evidence_pack_composition/scripts/run_step5_4_evidence_pack_composition.py \
  --config steps/step_05_4_evidence_pack_composition/resources/step5_4.regression_gemma_slice10.yaml \
  --run-id "$RUN_ID"

STEP54_SET="data/processed/kc_evidence_packs/_sets/${RUN_ID}_step5_4_kc_evidence_packs_set.json"
test -f "$STEP54_SET" || { echo "Missing Step 5.4 set manifest: $STEP54_SET"; exit 1; }

echo
echo "==== Step 5.4 stats ===="
"$PYTHON_BIN" - <<PY
import json
from pathlib import Path

set_path = Path("$STEP54_SET")
set_obj = json.loads(set_path.read_text(encoding="utf-8"))
stats_path = Path(set_obj["artifacts"]["evidence_pack_stats_json"])
packs_path = Path(set_obj["artifacts"]["kc_evidence_packs_jsonl"])

stats = json.loads(stats_path.read_text(encoding="utf-8"))
rows = [json.loads(line) for line in packs_path.read_text(encoding="utf-8").splitlines() if line.strip()]

print("STEP54_SET", set_path)
print("STATS_PATH", stats_path)
print("PACKS_PATH", packs_path)

for key in [
    "total_kcs",
    "route_breakdown",
    "formula_dominance_risk_breakdown",
    "sibling_contamination_risk_breakdown",
    "definition_anchor_present_count",
    "definition_anchor_natural_language_count",
    "context_completion_used_count",
    "insufficient_reason_breakdown",
    "average_coverage_score",
    "average_density_score",
]:
    print(key, "=", stats.get(key))

print()
print("==== per-KC Step 5.4 routes ====")
for row in rows:
    q = row.get("pack_quality") or {}
    print(
        row.get("kc_id"),
        "route=", q.get("route"),
        "definition_anchor_present=", q.get("definition_anchor_present"),
        "natural_language_anchor_present=", q.get("natural_language_anchor_present"),
        "formula_dominance_risk=", q.get("formula_dominance_risk"),
        "sibling_contamination_risk=", q.get("sibling_contamination_risk"),
        "context_completion_used=", q.get("context_completion_used"),
        "insufficient_reasons=", q.get("insufficient_reasons", []),
    )

if stats.get("total_kcs") != 10:
    raise SystemExit("FAIL: Step 5.4 did not emit exactly 10 packs")
PY

echo
echo "==== build explicit Step 6.6 config using this Step 5.4 set ===="
STEP66_CFG="data/work/cache/generated_configs/step6_6.regression_gemma_slice10.with_${RUN_ID}.yaml"

"$PYTHON_BIN" - <<PY
from pathlib import Path
import yaml

base = Path("steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.regression_gemma_slice10.yaml")
out = Path("$STEP66_CFG")
step54 = "$STEP54_SET"

cfg = yaml.safe_load(base.read_text(encoding="utf-8"))
cfg.setdefault("inputs", {})["step5_4_set_manifest"] = step54

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print("WROTE", out)
print("STEP5_4_SET_MANIFEST", step54)
PY

echo
echo "==== Step 6.6 regression slice with explicit Step 5.4 pack ===="
"$PYTHON_BIN" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config "$STEP66_CFG"

echo
echo "==== latest Step 6.6 inspection ===="
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
from collections import Counter

sets = sorted(Path("data/processed/kc_drafting_input_overlay/_sets").glob("*_step6_6_kc_drafting_input_overlay_set.json"))
if not sets:
    raise SystemExit("No Step 6.6 set manifests found")

set_path = sets[-1]
set_obj = json.loads(set_path.read_text(encoding="utf-8"))

stats_path = Path(set_obj["artifacts"]["overlay_stats_json"])
overlay_path = Path(set_obj["artifacts"]["candidate_sentence_overlay_jsonl"])
summary_path = Path(set_obj["audit"]["summary"])

stats = json.loads(stats_path.read_text(encoding="utf-8"))
summary = json.loads(summary_path.read_text(encoding="utf-8"))

rows = []
with overlay_path.open("r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))

target_kcs = sorted({row.get("kc_id") for row in rows})
pack_available_kcs = sorted({row.get("kc_id") for row in rows if row.get("evidence_pack_available")})
route_by_kc = {}
availability_by_kc = Counter()

for row in rows:
    kc_id = row.get("kc_id")
    if row.get("evidence_pack_available"):
        availability_by_kc[kc_id] += 1
    q = row.get("evidence_pack_quality") or {}
    if q:
        route_by_kc[kc_id] = q.get("route")

print("STEP66_SET", set_path)
print("STATS_PATH", stats_path)
print("OVERLAY_PATH", overlay_path)
print("SUMMARY_PATH", summary_path)
print("STEP5_4_INTEGRATION", summary.get("step5_4_integration"))
print("TOTAL_OVERLAY_RECORDS", stats.get("total_overlay_records"))
print("EVIDENCE_PACK_AVAILABLE_COUNT", stats.get("evidence_pack_available_count"))
print("TARGET_KC_COUNT", len(target_kcs))
print("PACK_AVAILABLE_KC_COUNT", len(pack_available_kcs))
print("PACK_AVAILABLE_KCS", pack_available_kcs)
print("PACK_AVAILABLE_ROWS_BY_KC", dict(sorted(availability_by_kc.items())))
print("ROUTE_BY_KC", dict(sorted(route_by_kc.items())))

if len(target_kcs) != 10:
    raise SystemExit("FAIL: Step 6.6 did not emit exactly 10 target KCs")
if len(pack_available_kcs) != 10:
    raise SystemExit("FAIL: not every target KC carried Step 5.4 evidence-pack metadata")
if not rows:
    raise SystemExit("FAIL: Step 6.6 emitted no overlay rows")
PY

echo
echo "PIPELINE_SLICE_OK"
