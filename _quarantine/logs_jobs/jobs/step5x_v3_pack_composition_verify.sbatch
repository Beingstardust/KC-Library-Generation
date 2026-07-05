#!/bin/bash
#SBATCH --job-name=s5xv3_pk
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=logs/s5xv3_pk-%j.out
#SBATCH --error=logs/s5xv3_pk-%j.err

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
echo "==== required Stage 3 files ===="
for rel in \
  "src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py" \
  "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py" \
  "steps/step_05_x_evidence_stage_v3/resources/step5x_v3_pack_composition.default.yaml" \
  "steps/step_05_x_evidence_stage_v3/resources/step5x_v3_pack_composition.regression_gemma_slice10.yaml" \
  "tests/test_step5x_v3_pack_composition.py" \
  "docs/operator_notes/EVIDENCE_STAGE_V3_STATE.md"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== accepted Stage 2 input guard ===="
STAGE2_SET="data/processed/evidence_stage_v3_scored_candidates/_sets/step5x_v3_scored_candidates_regression10_hardened_sofja_20260427_232222_step5x_v3_scored_candidates_set.json"
test -f "$STAGE2_SET" || { echo "MISSING Stage 2 set: $STAGE2_SET"; exit 1; }
echo "STAGE2_SET=$STAGE2_SET"

echo
echo "==== py_compile ===="
"$PY" -m py_compile \
  src/kc_l/retrieval_gate/evidence_stage_v3_pack_composition.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py \
  tests/test_step5x_v3_pack_composition.py

echo
echo "==== direct Stage 3 tests without pytest ===="
"$PY" - <<'PY'
import importlib.util
import inspect
import pathlib
import sys
import tempfile

repo = pathlib.Path(".").resolve()
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo / "src"))

path = repo / "tests" / "test_step5x_v3_pack_composition.py"
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

print("STEP5X_V3_PACK_COMPOSITION_TESTS_OK", passed)
PY

echo
echo "==== run Stage 3 pack-composition regression on Sofja ===="
RUN_ID="step5x_v3_evidence_packs_regression10_sofja_$(date -u +%Y%m%d_%H%M%S)"
echo "RUN_ID=$RUN_ID"

HELP="$("$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py --help 2>&1 || true)"
echo "$HELP" | sed -n '1,180p'

INPUT_ARG=()
if echo "$HELP" | grep -q -- '--step5x-v3-scored-set-manifest'; then
  INPUT_ARG=(--step5x-v3-scored-set-manifest "$STAGE2_SET")
elif echo "$HELP" | grep -q -- '--step5x-v3-scored-candidates-set-manifest'; then
  INPUT_ARG=(--step5x-v3-scored-candidates-set-manifest "$STAGE2_SET")
elif echo "$HELP" | grep -q -- '--scored-candidates-set-manifest'; then
  INPUT_ARG=(--scored-candidates-set-manifest "$STAGE2_SET")
else
  echo "No explicit Stage 2 set override option found. Falling back to config input."
fi

echo "INPUT_ARG=${INPUT_ARG[*]:-<none>}"

"$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py \
  --config steps/step_05_x_evidence_stage_v3/resources/step5x_v3_pack_composition.regression_gemma_slice10.yaml \
  "${INPUT_ARG[@]}" \
  --run-id "$RUN_ID"

SET_PATH="data/processed/evidence_stage_v3_evidence_packs/_sets/${RUN_ID}_step5x_v3_evidence_packs_set.json"
test -f "$SET_PATH"

echo
echo "==== build semantic assessment from exact Sofja output ===="
SET_PATH="$SET_PATH" "$PY" - <<'PY'
import json
import os
import re
from pathlib import Path

root = Path(".")
set_path = Path(os.environ["SET_PATH"])
set_obj = json.loads(set_path.read_text(encoding="utf-8"))

packs_path = root / set_obj["artifacts"]["kc_evidence_packs_jsonl"]
stats_path = root / set_obj["artifacts"]["evidence_pack_stats_json"]

packs = [json.loads(line) for line in packs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))

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
ordered_sibling_violations = []
positive_slots_by_kc = {}
ordered_roles_by_kc = {}

for pack in packs:
    kc_id = str(pack.get("kc_id") or "")
    slots = pack.get("slots") or {}
    ordered = pack.get("ordered_pack_for_drafting") or []

    positive_texts = []
    positive_summary = {}

    for role in positive_roles:
        items = slots.get(role) or []
        if items:
            positive_summary[role] = [item.get("text") for item in items]
        for item in items:
            positive_texts.append(str(item.get("text") or item.get("quote") or ""))

    if positive_summary:
        positive_slots_by_kc[kc_id] = positive_summary

    ordered_roles = [str(item.get("role") or "") for item in ordered]
    ordered_roles_by_kc[kc_id] = ordered_roles

    if "sibling_contrast" in ordered_roles:
        ordered_sibling_violations.append(kc_id)

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
    "set_manifest": set_path.as_posix(),
    "packs_path": packs_path.as_posix(),
    "stats_path": stats_path.as_posix(),
    "pack_count": len(packs),
    "route_breakdown": stats.get("route_breakdown"),
    "slot_item_count_breakdown": stats.get("slot_item_count_breakdown"),
    "ordered_role_breakdown": stats.get("ordered_role_breakdown"),
    "ordered_sibling_violations": ordered_sibling_violations,
    "known_bad_positive_hits": known_bad_positive_hits,
    "known_bad_ordered_hits": known_bad_ordered_hits,
    "positive_slots_by_kc": positive_slots_by_kc,
    "ordered_roles_by_kc": ordered_roles_by_kc,
}

out = root / "data/work/cache/diagnostics" / f"{set_path.stem}_sofja_stage3_assessment.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("SET_PATH =", set_path.as_posix())
print("PACKS_PATH =", packs_path.as_posix())
print("STATS_PATH =", stats_path.as_posix())
print("ASSESSMENT_JSON =", out.as_posix())
print("pack_count =", len(packs))
print("route_breakdown =", stats.get("route_breakdown"))
print("slot_item_count_breakdown =", stats.get("slot_item_count_breakdown"))
print("ordered_role_breakdown =", stats.get("ordered_role_breakdown"))
print("ordered_sibling_violations =", ordered_sibling_violations)
print("known_bad_positive_hits =", json.dumps(known_bad_positive_hits, indent=2, ensure_ascii=False))
print("known_bad_ordered_hits =", json.dumps(known_bad_ordered_hits, indent=2, ensure_ascii=False))
print("positive_slots_by_kc =", json.dumps(positive_slots_by_kc, indent=2, ensure_ascii=False))

if len(packs) != 10:
    raise SystemExit(f"FAIL: expected 10 packs, got {len(packs)}")
if ordered_sibling_violations:
    raise SystemExit("FAIL: sibling_contrast leaked into ordered_pack_for_drafting")
if known_bad_positive_hits:
    raise SystemExit("FAIL: known bad markers leaked into positive support slots")
if known_bad_ordered_hits:
    raise SystemExit("FAIL: known bad markers leaked into ordered drafting pack")
if stats.get("ordered_sibling_violation_count") not in (0, None):
    raise SystemExit("FAIL: stats reported ordered sibling violation")
if stats.get("duplicate_ordered_candidate_id_count") not in (0, None):
    raise SystemExit("FAIL: duplicate ordered candidate ids")
if stats.get("forbidden_seed_field_hits") not in (0, None):
    raise SystemExit("FAIL: forbidden seed field hit")

print("STAGE3_V3_PACK_COMPOSITION_SOFJA_ASSESSMENT_OK")
PY

echo
echo "==== active pointer guard ===="
find data/processed/evidence_stage_v3_evidence_packs/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' -print

if find data/processed/evidence_stage_v3_evidence_packs/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' | grep -q .; then
  echo "FAIL: ACTIVE pointer was created unexpectedly"
  exit 1
fi

echo
echo "PIPELINE_STAGE3_V3_SOFJA_OK"
