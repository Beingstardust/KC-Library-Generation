#!/usr/bin/env bash
#SBATCH --job-name=s54tb_r10
#SBATCH --partition=gpu46GB
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:30:00
#SBATCH --output=logs/s54tb_r10-%j.out
#SBATCH --error=logs/s54tb_r10-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "==== job context ===="
date -u
hostname
echo "PYTHON_BIN=$PYTHON_BIN"
"$PYTHON_BIN" --version

echo
echo "==== content guard ===="
grep -nE 'def _candidate_target_binding\(|"is_target_bound"|binding_strength|offtarget_reasons|def _critical_offtarget|def _build_global_candidate_usage' \
  src/kc_l/retrieval_gate/evidence_pack_composition.py
if grep -n "def _candidate_target_binding_score(candidate_row" src/kc_l/retrieval_gate/evidence_pack_composition.py; then
  echo "CRITICAL: wrong old Step 5.4 file version."
  exit 1
fi

echo
echo "==== active Step 5.3 pointer ===="
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json

ptr = Path("data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt")
print("ACTIVE_STEP5_3_POINTER", ptr)
print("EXISTS", ptr.exists())
if not ptr.exists():
    raise SystemExit("Missing ACTIVE_STEP5_3_EVIDENCE_SET.txt")

target = Path(ptr.read_text(encoding="utf-8").strip())
if not target.is_absolute():
    target = Path(".") / target
print("ACTIVE_STEP5_3_TARGET", target.resolve())
print("TARGET_EXISTS", target.exists())
if not target.exists():
    raise SystemExit("Missing active Step 5.3 target manifest")

m = json.loads(target.read_text(encoding="utf-8"))
print("STEP5_3_SET_ID", m.get("set_id"))
print("STEP5_3_RUN_ID", m.get("run_id_step5_3") or m.get("run_id"))
print("STEP5_3_ARTIFACTS", m.get("artifacts"))
PY

echo
echo "==== Step 5.4 target-binding regression slice ===="
RUN_ID="step54_target_binding_regression10_$(date -u +%Y%m%d_%H%M%S)"
"$PYTHON_BIN" steps/step_05_4_evidence_pack_composition/scripts/run_step5_4_evidence_pack_composition.py \
  --config steps/step_05_4_evidence_pack_composition/resources/step5_4.regression_gemma_slice10.yaml \
  --run-id "$RUN_ID"

echo
echo "==== Step 5.4 stats ===="
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json

sets = sorted(Path("data/processed/kc_evidence_packs/_sets").glob("*_step5_4_kc_evidence_packs_set.json"))
if not sets:
    raise SystemExit("No Step 5.4 set manifests found")

latest = sets[-1]
m = json.loads(latest.read_text(encoding="utf-8"))
stats_path = Path(m["artifacts"]["evidence_pack_stats_json"])
packs_path = Path(m["artifacts"]["kc_evidence_packs_jsonl"])
stats = json.loads(stats_path.read_text(encoding="utf-8"))

print("STEP54_SET", latest)
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

rows = [json.loads(line) for line in packs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
print()
print("==== per-KC pack routes ====")
for row in sorted(rows, key=lambda r: r.get("kc_id", "")):
    q = row.get("pack_quality", {})
    print(
        row.get("kc_id"),
        "route=", q.get("route"),
        "definition_anchor_natural_language=", q.get("definition_anchor_natural_language"),
        "formula_risk=", q.get("formula_dominance_risk"),
        "sibling_risk=", q.get("sibling_contamination_risk"),
        "context_completion_used=", q.get("context_completion_used"),
        "insufficient_reasons=", q.get("insufficient_reasons", []),
    )
PY

echo
echo "==== build explicit Step 6.6 config from regression_gemma_slice10 + latest Step 5.4 ===="
STEP54_SET=$(ls -1t data/processed/kc_evidence_packs/_sets/*_step5_4_kc_evidence_packs_set.json | head -n 1)
STEP66_CFG="data/work/cache/generated_configs/step6_6.regression_gemma_slice10.with_target_binding_step54.yaml"

STEP54_SET="$STEP54_SET" STEP66_CFG="$STEP66_CFG" "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path
import yaml

base = Path("steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.regression_gemma_slice10.yaml")
if not base.exists():
    raise SystemExit(f"Missing regression Step 6.6 config: {base}")

cfg = yaml.safe_load(base.read_text(encoding="utf-8"))
cfg.setdefault("inputs", {})["step5_4_set_manifest"] = os.environ["STEP54_SET"]

out = Path(os.environ["STEP66_CFG"])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print("WROTE", out)
print("STEP5_4_SET_MANIFEST", os.environ["STEP54_SET"])
PY

echo
echo "==== Step 6.6 regression slice with target-binding Step 5.4 pack ===="
"$PYTHON_BIN" steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py \
  --config "$STEP66_CFG"

echo
echo "==== inspect Step 6.6 integration ===="
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json
from collections import defaultdict

sets = sorted(Path("data/processed/kc_drafting_input_overlay/_sets").glob("*_step6_6_kc_drafting_input_overlay_set.json"))
latest = sets[-1]
m = json.loads(latest.read_text(encoding="utf-8"))
overlay_path = Path(m["artifacts"]["candidate_sentence_overlay_jsonl"])
stats_path = Path(m["artifacts"]["overlay_stats_json"])
stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

rows = [json.loads(line) for line in overlay_path.read_text(encoding="utf-8").splitlines() if line.strip()]
by_kc = defaultdict(list)
for row in rows:
    by_kc[row.get("kc_id")].append(row)

pack_kcs = sorted(kc for kc, vals in by_kc.items() if any(v.get("evidence_pack_available") for v in vals))
routes = {}
for kc, vals in by_kc.items():
    q = vals[0].get("evidence_pack_quality") or {}
    if q:
        routes[kc] = q.get("route")

print("STEP66_SET", latest)
print("OVERLAY_PATH", overlay_path)
print("STATS_PATH", stats_path)
print("TOTAL_OVERLAY_ROWS", len(rows))
print("PACK_AVAILABLE_KC_COUNT", len(pack_kcs))
print("PACK_AVAILABLE_KCS", pack_kcs)
print("ROUTE_BY_KC", dict(sorted(routes.items())))
print("OVERLAY_STATS_KEYS", sorted(stats.keys()))
print("PIPELINE_STEP54_66_TARGET_BINDING_OK")
PY
