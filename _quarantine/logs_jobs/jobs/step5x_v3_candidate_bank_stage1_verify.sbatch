#!/bin/bash
#SBATCH --job-name=s5xv3_cb
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=logs/s5xv3_cb-%j.out
#SBATCH --error=logs/s5xv3_cb-%j.err

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
echo "==== required files ===="
for rel in \
  "src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py" \
  "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py" \
  "steps/step_05_x_evidence_stage_v3/resources/step5x_v3_candidate_bank.default.yaml" \
  "steps/step_05_x_evidence_stage_v3/resources/step5x_v3_candidate_bank.regression_gemma_slice10.yaml" \
  "tests/test_step5x_v3_candidate_bank.py" \
  "docs/operator_notes/EVIDENCE_STAGE_V3_STATE.md" \
  "_reference_artifacts/evidence_stage_v3_audit_inputs_20260427_184622.tar.gz"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== seed residue guard in new v3 code ===="
if grep -R -nE 'seed_definition|seed_keywords|SEED_DEFINITION_FLOOR_ACTIVE_FLAG|hierarchy\.seed_definition|seed_floor_active_count' \
  src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py \
  tests/test_step5x_v3_candidate_bank.py
then
  echo "NOTE: seed terms appear in tests or exclusion guards. Checking no seed propagation is handled by tests."
else
  echo "NO_SEED_TERMS_FOUND"
fi

echo
echo "==== py_compile ===="
"$PY" -m py_compile \
  src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py \
  tests/test_step5x_v3_candidate_bank.py

echo
echo "==== direct tests without pytest ===="
"$PY" - <<'PY'
import importlib.util
import inspect
import pathlib
import sys
import tempfile

repo = pathlib.Path(".").resolve()
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo / "src"))

path = repo / "tests" / "test_step5x_v3_candidate_bank.py"
spec = importlib.util.spec_from_file_location(path.stem, path)
mod = importlib.util.module_from_spec(spec)
sys.modules[path.stem] = mod
spec.loader.exec_module(mod)

passed = 0
for name, fn in sorted(vars(mod).items()):
    if not name.startswith("test_") or not callable(fn):
        continue
    sig = inspect.signature(fn)
    kwargs = {}
    with tempfile.TemporaryDirectory() as td:
        if "tmp_path" in sig.parameters:
            kwargs["tmp_path"] = pathlib.Path(td)
        fn(**kwargs)
    print("PASS", name)
    passed += 1

print("STEP5X_V3_CANDIDATE_BANK_TESTS_OK", passed)
PY

echo
echo "==== run Stage 1 regression candidate bank on Sofja ===="
RUN_ID="step5x_v3_regression10_sofja_$(date -u +%Y%m%d_%H%M%S)"
echo "RUN_ID=$RUN_ID"

"$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py \
  --config steps/step_05_x_evidence_stage_v3/resources/step5x_v3_candidate_bank.regression_gemma_slice10.yaml \
  --run-id "$RUN_ID"

SET_PATH="data/processed/evidence_stage_v3_candidate_bank/_sets/${RUN_ID}_step5x_v3_candidate_bank_set.json"
test -f "$SET_PATH"

echo
echo "==== inspect Stage 1 outputs ===="
SET_PATH="$SET_PATH" "$PY" - <<'PY'
import json
import os
from pathlib import Path
from collections import Counter

root = Path(".")
set_path = Path(os.environ["SET_PATH"])
set_obj = json.loads(set_path.read_text(encoding="utf-8"))

stats_path = root / set_obj["artifacts"]["candidate_bank_stats_json"]
bank_path = root / set_obj["artifacts"]["candidate_bank_jsonl"]
schema_path = root / set_obj["artifacts"]["candidate_bank_schema_snapshot_json"]
manifest_path = root / set_obj["artifacts"]["candidate_bank_manifest_json"]

stats = json.loads(stats_path.read_text(encoding="utf-8"))
rows = [json.loads(line) for line in bank_path.read_text(encoding="utf-8").splitlines() if line.strip()]

print("SET_PATH =", set_path.as_posix())
print("BANK_PATH =", bank_path.as_posix())
print("STATS_PATH =", stats_path.as_posix())
print("SCHEMA_PATH =", schema_path.as_posix())
print("MANIFEST_PATH =", manifest_path.as_posix())

print()
print("total_kc_rows_seen =", stats.get("total_kc_rows_seen"))
print("total_candidate_rows_emitted =", stats.get("total_candidate_rows_emitted"))
print("kcs_with_candidates =", stats.get("kcs_with_candidates"))
print("kcs_without_candidates =", stats.get("kcs_without_candidates"))
print("candidate_count_by_kc =", stats.get("candidate_count_by_kc"))
print("granularity_breakdown =", stats.get("granularity_breakdown"))
print("seed_fields_detected_in_input =", stats.get("seed_fields_detected_in_input"))
print("seed_fields_propagated_to_output =", stats.get("seed_fields_propagated_to_output"))

candidate_ids = [row.get("candidate_id") for row in rows]
dupes = [cid for cid, n in Counter(candidate_ids).items() if n > 1]
print("duplicate_candidate_ids =", dupes[:20])
print("duplicate_candidate_id_count =", len(dupes))

forbidden = {
    "role_scores",
    "eligibility",
    "pack_quality",
    "ordered_pack_for_drafting",
    "slots",
    "seed_definition",
    "seed_keywords",
}

forbidden_hits = {}
for row in rows:
    hits = sorted(k for k in forbidden if k in row)
    if hits:
        forbidden_hits[row.get("candidate_id", "")] = hits

print("forbidden_top_level_hits_count =", len(forbidden_hits))
if forbidden_hits:
    print("forbidden_top_level_hits_sample =", dict(list(forbidden_hits.items())[:5]))

required_kcs = {
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
seen_kcs = {row.get("kc_id") for row in rows}
missing_kcs = sorted(required_kcs - seen_kcs)
extra_kcs = sorted(seen_kcs - required_kcs)

print("missing_required_kcs =", missing_kcs)
print("extra_kcs =", extra_kcs)

summary = {
    "set_path": set_path.as_posix(),
    "bank_path": bank_path.as_posix(),
    "stats_path": stats_path.as_posix(),
    "schema_path": schema_path.as_posix(),
    "manifest_path": manifest_path.as_posix(),
    "stats": stats,
    "candidate_row_count": len(rows),
    "duplicate_candidate_id_count": len(dupes),
    "forbidden_top_level_hits_count": len(forbidden_hits),
    "missing_required_kcs": missing_kcs,
    "extra_kcs": extra_kcs,
}

out = root / "data/work/cache/diagnostics" / f"{set_path.stem}_sofja_validation_summary.json"
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print("SOFJA_VALIDATION_SUMMARY =", out.as_posix())

if len(rows) != 180:
    raise SystemExit(f"Expected 180 regression candidate rows, got {len(rows)}")
if dupes:
    raise SystemExit("Duplicate candidate IDs found")
if forbidden_hits:
    raise SystemExit("Forbidden semantic or seed fields found in candidate rows")
if missing_kcs or extra_kcs:
    raise SystemExit("KC set mismatch in regression extraction")
if stats.get("seed_fields_propagated_to_output") != 0:
    raise SystemExit("Seed fields propagated to output")
PY

echo
echo "==== active pointer guard ===="
find data/processed/evidence_stage_v3_candidate_bank/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' -print

if find data/processed/evidence_stage_v3_candidate_bank/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' | grep -q .; then
  echo "FAIL: ACTIVE pointer was created unexpectedly"
  exit 1
fi

echo
echo "PIPELINE_STEP5X_V3_CANDIDATE_BANK_STAGE1_SOFJA_OK"
