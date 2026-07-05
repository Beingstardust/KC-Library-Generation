#!/bin/bash
#SBATCH --job-name=s67v3heur
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=logs/s67v3heur-%j.out
#SBATCH --error=logs/s67v3heur-%j.err

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
echo "==== accepted Step 6.6 full144 v3 input guard ===="
STEP66_SET="data/processed/kc_drafting_input_overlay/_sets/2026-04-28_002730_step6_6_kc_drafting_input_overlay_set.json"
test -f "$STEP66_SET" || { echo "MISSING accepted Step 6.6 set: $STEP66_SET"; exit 1; }
echo "STEP66_SET=$STEP66_SET"

echo
echo "==== required Step 6.7 files ===="
for rel in \
  "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py" \
  "steps/step_06_7_kc_draft_generation/resources/step6_7.sofja.actual_corpus.yaml" \
  "src/kc_l/kc_drafting/config.py" \
  "src/kc_l/kc_drafting/orchestration.py" \
  "src/kc_l/kc_drafting/backend.py" \
  "src/kc_l/kc_drafting/heuristic_core.py" \
  "src/kc_l/kc_drafting/provenance.py" \
  "src/kc_l/kc_drafting/packetization.py"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== protect current aliases before run ===="
ALIAS_LIST=(
  "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"
  "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json"
  "data/work/cache/current_step_artifacts/step6_75_set_manifest.current.json"
  "data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json"
)

BEFORE_HASH_FILE="data/work/cache/diagnostics/step6_7_v3_heuristic_alias_hashes_before_${SLURM_JOB_ID}.txt"
AFTER_HASH_FILE="data/work/cache/diagnostics/step6_7_v3_heuristic_alias_hashes_after_${SLURM_JOB_ID}.txt"

: > "$BEFORE_HASH_FILE"
for rel in "${ALIAS_LIST[@]}"; do
  if [ -f "$rel" ]; then
    sha256sum "$rel" | tee -a "$BEFORE_HASH_FILE"
  else
    echo "MISSING $rel" | tee -a "$BEFORE_HASH_FILE"
  fi
done

echo
echo "==== create generated Step 6.7 heuristic config pinned to accepted Step 6.6 ===="
STAMP="$(date -u +%Y%m%d_%H%M%S)"
BASE_CONFIG="steps/step_06_7_kc_draft_generation/resources/step6_7.sofja.actual_corpus.yaml"
GENERATED_CONFIG="data/work/cache/generated_configs/step6_7.sofja.actual_corpus.with_stage3_v3_step66_full144_heuristic_${STAMP}.yaml"

export BASE_CONFIG GENERATED_CONFIG STEP66_SET

"$PY" - <<'PY'
import json
import os
from pathlib import Path
import yaml

base_path = Path(os.environ["BASE_CONFIG"])
out_path = Path(os.environ["GENERATED_CONFIG"])
step66_set = os.environ["STEP66_SET"]

cfg = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}

# This intentionally stays in the legacy simple config shape.
# No model section means Step 6.7 normalizes this to heuristic mode.
cfg.setdefault("inputs", {})["step6_6_set_manifest"] = step66_set
cfg.setdefault("outputs", {})["processed_root"] = "data/processed/kc_drafts"
cfg.setdefault("outputs", {})["sets_root"] = "data/processed/kc_drafts/_sets"
cfg.setdefault("outputs", {})["runs_root"] = "data/runs"
cfg.setdefault("slice", {})["limit_kcs"] = 144
cfg.setdefault("selection", {})["max_bundle_size"] = 4
cfg.setdefault("selection", {})["max_explanatory_candidates"] = 3

# Defensive: make sure we do not accidentally trigger the LLM path here.
cfg.pop("model", None)
cfg.pop("models", None)
cfg.pop("step6_7", None)

cfg.setdefault("metadata", {})["test"] = "full144_stage3_v3_to_step6_7_heuristic_structural_acceptance"
cfg["metadata"]["accepted_step6_6_set_manifest"] = step66_set
cfg["metadata"]["expected_execution_mode"] = "heuristic"
cfg["metadata"]["active_pointer_policy"] = "do_not_update_current_alias_or_active_pointer"

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print("GENERATED_CONFIG =", out_path.as_posix())
print("CONFIG_PREVIEW =")
print(json.dumps(cfg, indent=2, ensure_ascii=False))
PY

test -f "$GENERATED_CONFIG"

echo
echo "==== py_compile Step 6.7 active surface ===="
"$PY" -m py_compile \
  steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  src/kc_l/kc_drafting/config.py \
  src/kc_l/kc_drafting/orchestration.py \
  src/kc_l/kc_drafting/backend.py \
  src/kc_l/kc_drafting/heuristic_core.py \
  src/kc_l/kc_drafting/provenance.py \
  src/kc_l/kc_drafting/packetization.py

echo
echo "==== run Step 6.7 heuristic full144 with accepted v3 Step 6.6 ===="
RUN_STDOUT="data/work/cache/diagnostics/step6_7_v3_heuristic_runner_stdout_${SLURM_JOB_ID}.json"
"$PY" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config "$GENERATED_CONFIG" | tee "$RUN_STDOUT"

RUN_ID="$("$PY" - <<'PY'
import json
from pathlib import Path

path = Path("data/work/cache/diagnostics/step6_7_v3_heuristic_runner_stdout_${SLURM_JOB_ID}.json")
text = path.read_text(encoding="utf-8")
obj = json.loads(text)
print(obj["run_id"])
PY
)"

SET_PATH="data/processed/kc_drafts/_sets/${RUN_ID}_step6_7_kc_drafts_set.json"
test -f "$SET_PATH" || { echo "MISSING Step 6.7 set: $SET_PATH"; exit 1; }

echo "RUN_ID=$RUN_ID"
echo "SET_PATH=$SET_PATH"

echo
echo "==== assess Step 6.7 output contract, lineage, and quality counters ===="
STEP66_SET="$STEP66_SET" SET_PATH="$SET_PATH" GENERATED_CONFIG="$GENERATED_CONFIG" "$PY" - <<'PY'
import json
import os
from pathlib import Path
from collections import Counter, defaultdict

root = Path(".")
step66_set = Path(os.environ["STEP66_SET"])
set_path = Path(os.environ["SET_PATH"])
generated_config = Path(os.environ["GENERATED_CONFIG"])

step66_obj = json.loads(step66_set.read_text(encoding="utf-8"))
step67_obj = json.loads(set_path.read_text(encoding="utf-8"))

step66_overlay_path = root / step66_obj["artifacts"]["candidate_sentence_overlay_jsonl"]
step67_bundles_path = root / step67_obj["artifacts"]["kc_draft_bundles_jsonl"]
step67_stats_path = root / step67_obj["artifacts"]["draft_stats_json"]

overlay_rows = [json.loads(line) for line in step66_overlay_path.read_text(encoding="utf-8").splitlines() if line.strip()]
bundle_rows = [json.loads(line) for line in step67_bundles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(step67_stats_path.read_text(encoding="utf-8"))

overlay_kcs = sorted({str(row.get("kc_id") or "") for row in overlay_rows if str(row.get("kc_id") or "")})
bundle_kcs = sorted({str(row.get("kc_id") or "") for row in bundle_rows if str(row.get("kc_id") or "")})

bundle_counts = Counter(str(row.get("kc_id") or "") for row in bundle_rows)
duplicate_bundle_kcs = sorted([kc for kc, n in bundle_counts.items() if n > 1])
missing_bundle_kcs = sorted(set(overlay_kcs) - set(bundle_kcs))
extra_bundle_kcs = sorted(set(bundle_kcs) - set(overlay_kcs))

upstream_step66 = str((step67_obj.get("upstream") or {}).get("step6_6_set_manifest_json") or "")
runtime = dict(step67_obj.get("drafting_runtime") or stats.get("drafting_runtime") or {})

def nested_get_status(value):
    if isinstance(value, dict):
        return str(value.get("status") or value.get("state") or "")
    return str(value or "")

draft_status_counter = Counter()
definition_status_counter = Counter()
trust_state_counter = Counter()
review_readiness_counter = Counter()
coverage_status_counter = Counter()
definition_text_present = 0
scope_text_present = 0

for row in bundle_rows:
    draft_status_counter[nested_get_status(row.get("draft_status"))] += 1
    definition_status_counter[nested_get_status(row.get("authoritative_definition_status"))] += 1
    trust_state_counter[nested_get_status(row.get("trust_state"))] += 1
    review_readiness_counter[nested_get_status(row.get("review_readiness"))] += 1
    coverage_status_counter[nested_get_status(row.get("coverage_state"))] += 1

    definition = row.get("definition") or row.get("definition_full") or {}
    scope = row.get("scope") or {}

    if isinstance(definition, dict):
        if str(definition.get("text") or "").strip():
            definition_text_present += 1
    elif str(definition or "").strip():
        definition_text_present += 1

    if isinstance(scope, dict):
        if str(scope.get("text") or "").strip():
            scope_text_present += 1
    elif str(scope or "").strip():
        scope_text_present += 1

assessment = {
    "generated_config": generated_config.as_posix(),
    "step6_6_set_manifest": step66_set.as_posix(),
    "step6_7_set_manifest": set_path.as_posix(),
    "step6_6_overlay_path": step66_overlay_path.as_posix(),
    "step6_7_bundles_path": step67_bundles_path.as_posix(),
    "step6_7_stats_path": step67_stats_path.as_posix(),
    "overlay_row_count": len(overlay_rows),
    "overlay_unique_kc_count": len(overlay_kcs),
    "bundle_count": len(bundle_rows),
    "bundle_unique_kc_count": len(bundle_kcs),
    "missing_bundle_kcs": missing_bundle_kcs,
    "extra_bundle_kcs": extra_bundle_kcs,
    "duplicate_bundle_kcs": duplicate_bundle_kcs,
    "upstream_step6_6_set_manifest_json": upstream_step66,
    "drafting_runtime": runtime,
    "draft_status_counter": dict(draft_status_counter),
    "authoritative_definition_status_counter": dict(definition_status_counter),
    "trust_state_counter": dict(trust_state_counter),
    "review_readiness_counter": dict(review_readiness_counter),
    "coverage_status_counter": dict(coverage_status_counter),
    "definition_text_present_count": definition_text_present,
    "scope_text_present_count": scope_text_present,
    "draft_stats_keys": sorted(stats.keys()),
    "draft_stats": stats,
}

out = root / "data/work/cache/diagnostics" / f"{set_path.stem}_full144_v3_heuristic_assessment.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("ASSESSMENT_JSON =", out.as_posix())
print("overlay_row_count =", len(overlay_rows))
print("overlay_unique_kc_count =", len(overlay_kcs))
print("bundle_count =", len(bundle_rows))
print("bundle_unique_kc_count =", len(bundle_kcs))
print("missing_bundle_kcs =", missing_bundle_kcs)
print("extra_bundle_kcs =", extra_bundle_kcs)
print("duplicate_bundle_kcs =", duplicate_bundle_kcs)
print("upstream_step6_6_set_manifest_json =", upstream_step66)
print("drafting_runtime =", json.dumps(runtime, indent=2, ensure_ascii=False))
print("draft_status_counter =", dict(draft_status_counter))
print("authoritative_definition_status_counter =", dict(definition_status_counter))
print("trust_state_counter =", dict(trust_state_counter))
print("review_readiness_counter =", dict(review_readiness_counter))
print("coverage_status_counter =", dict(coverage_status_counter))
print("definition_text_present_count =", definition_text_present)
print("scope_text_present_count =", scope_text_present)

if len(overlay_kcs) != 144:
    raise SystemExit(f"FAIL: expected 144 overlay KCs, got {len(overlay_kcs)}")
if len(bundle_rows) != 144:
    raise SystemExit(f"FAIL: expected 144 Step 6.7 draft bundles, got {len(bundle_rows)}")
if len(bundle_kcs) != 144:
    raise SystemExit(f"FAIL: expected 144 unique Step 6.7 KCs, got {len(bundle_kcs)}")
if missing_bundle_kcs or extra_bundle_kcs or duplicate_bundle_kcs:
    raise SystemExit("FAIL: Step 6.7 bundle KC identity mismatch")
if Path(upstream_step66).name != step66_set.name:
    raise SystemExit("FAIL: Step 6.7 set does not point to accepted Step 6.6 v3 set")
if str(runtime.get("execution_mode") or "").lower() != "heuristic":
    raise SystemExit("FAIL: expected heuristic execution mode for this structural run")
if int(runtime.get("llm_calls") or 0) != 0:
    raise SystemExit("FAIL: heuristic structural run unexpectedly made LLM calls")

print("STEP6_7_FULL144_V3_HEURISTIC_ASSESSMENT_OK")
PY

echo
echo "==== protect current aliases after run ===="
: > "$AFTER_HASH_FILE"
for rel in "${ALIAS_LIST[@]}"; do
  if [ -f "$rel" ]; then
    sha256sum "$rel" | tee -a "$AFTER_HASH_FILE"
  else
    echo "MISSING $rel" | tee -a "$AFTER_HASH_FILE"
  fi
done

if ! diff -u "$BEFORE_HASH_FILE" "$AFTER_HASH_FILE"; then
  echo "FAIL: one or more current aliases changed unexpectedly"
  exit 1
fi

echo
echo "STEP6_7_FULL144_V3_HEURISTIC_PIPELINE_OK"
