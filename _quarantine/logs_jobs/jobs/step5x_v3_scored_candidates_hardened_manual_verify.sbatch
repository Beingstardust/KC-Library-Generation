#!/bin/bash
#SBATCH --job-name=s5xv3_sc
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=logs/s5xv3_sc-%j.out
#SBATCH --error=logs/s5xv3_sc-%j.err

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
echo "==== required Stage 2 files ===="
for rel in \
  "src/kc_l/retrieval_gate/evidence_stage_v3_scored_candidates.py" \
  "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py" \
  "steps/step_05_x_evidence_stage_v3/resources/step5x_v3_scored_candidates.default.yaml" \
  "steps/step_05_x_evidence_stage_v3/resources/step5x_v3_scored_candidates.regression_gemma_slice10.yaml" \
  "tests/test_step5x_v3_scored_candidates.py" \
  "docs/operator_notes/EVIDENCE_STAGE_V3_STATE.md"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== Stage 1 regression set guard ===="
STAGE1_SET="data/processed/evidence_stage_v3_candidate_bank/_sets/step5x_v3_regression10_sofja_20260427_195700_step5x_v3_candidate_bank_set.json"
test -f "$STAGE1_SET" || { echo "MISSING Stage 1 set: $STAGE1_SET"; exit 1; }
echo "STAGE1_SET=$STAGE1_SET"

echo
echo "==== py_compile ===="
"$PY" -m py_compile \
  src/kc_l/retrieval_gate/evidence_stage_v3_scored_candidates.py \
  steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py \
  tests/test_step5x_v3_scored_candidates.py

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

path = repo / "tests" / "test_step5x_v3_scored_candidates.py"
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

print("STEP5X_V3_SCORED_CANDIDATES_TESTS_OK", passed)
PY

echo
echo "==== run hardened Stage 2 regression on Sofja ===="
RUN_ID="step5x_v3_scored_candidates_regression10_hardened_sofja_$(date -u +%Y%m%d_%H%M%S)"
echo "RUN_ID=$RUN_ID"

"$PY" steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py \
  --config steps/step_05_x_evidence_stage_v3/resources/step5x_v3_scored_candidates.regression_gemma_slice10.yaml \
  --step5x-v3-set-manifest "$STAGE1_SET" \
  --run-id "$RUN_ID"

SET_PATH="data/processed/evidence_stage_v3_scored_candidates/_sets/${RUN_ID}_step5x_v3_scored_candidates_set.json"
test -f "$SET_PATH"

echo
echo "==== build semantic assessment from exact Sofja output ===="
SET_PATH="$SET_PATH" "$PY" - <<'PY'
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import os

root = Path(".")
set_path = Path(os.environ["SET_PATH"])
set_obj = json.loads(set_path.read_text(encoding="utf-8"))

rows_path = root / set_obj["artifacts"]["scored_candidates_jsonl"]
stats_path = root / set_obj["artifacts"]["scored_candidate_stats_json"]

rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))

def norm(text):
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()

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

forbidden_fields = {
    "seed_definition",
    "seed_keywords",
    "pack_quality",
    "ordered_pack_for_drafting",
    "slots",
    "eligibility",
}

candidate_ids = [row.get("candidate_id") for row in rows]
dupes = sorted([cid for cid, n in Counter(candidate_ids).items() if n > 1])

forbidden_hits = []
for row in rows:
    present = sorted(field for field in forbidden_fields if field in row)
    if present:
        forbidden_hits.append({"candidate_id": row.get("candidate_id"), "fields": present})

by_kc = defaultdict(lambda: {"positive": [], "auxiliary": [], "guardrail": [], "manual": [], "drop": []})
known_bad_positive_hits = defaultdict(list)

for row in rows:
    kc_id = str(row.get("kc_id") or "")
    route = str(row.get("routing_recommendation") or "")
    item = {
        "candidate_id": row.get("candidate_id"),
        "text": row.get("candidate_text") or row.get("text"),
        "roles": sorted([k for k, v in (row.get("role_eligibility") or {}).items() if v]),
        "risk_flags": row.get("risk_flags") or [],
    }

    if route == "positive_role_candidate":
        by_kc[kc_id]["positive"].append(item)
    elif route == "auxiliary_only_candidate":
        by_kc[kc_id]["auxiliary"].append(item)
    elif route == "guardrail_only_candidate":
        by_kc[kc_id]["guardrail"].append(item)
    elif route == "manual_review_candidate":
        by_kc[kc_id]["manual"].append(item)
    else:
        by_kc[kc_id]["drop"].append(item)

    if route == "positive_role_candidate":
        txt = norm(row.get("candidate_text") or row.get("text"))
        for marker in known_bad.get(kc_id, []):
            if norm(marker) in txt:
                known_bad_positive_hits[kc_id].append(
                    {
                        "marker": marker,
                        "candidate_id": row.get("candidate_id"),
                        "text": row.get("candidate_text") or row.get("text"),
                    }
                )

role_breakdown = stats.get("role_eligibility_breakdown", {})
routing_breakdown = stats.get("routing_recommendation_breakdown", {})

summary = {
    "set_manifest": set_path.as_posix(),
    "rows_path": rows_path.as_posix(),
    "stats_path": stats_path.as_posix(),
    "row_count": len(rows),
    "per_kc_candidate_counts": stats.get("per_kc_candidate_counts"),
    "routing_breakdown": routing_breakdown,
    "role_eligibility_breakdown": role_breakdown,
    "risk_flag_breakdown": stats.get("risk_flag_breakdown"),
    "duplicate_candidate_id_count": len(dupes),
    "duplicate_candidate_ids": dupes,
    "forbidden_field_hit_count": len(forbidden_hits),
    "forbidden_field_hits": forbidden_hits[:20],
    "known_bad_positive_hits": dict(known_bad_positive_hits),
    "positive_candidate_count": sum(len(v["positive"]) for v in by_kc.values()),
    "positive_candidates_by_kc": {kc: v["positive"] for kc, v in sorted(by_kc.items()) if v["positive"]},
    "auxiliary_candidates_by_kc": {kc: v["auxiliary"][:10] for kc, v in sorted(by_kc.items()) if v["auxiliary"]},
    "guardrail_candidates_by_kc": {kc: v["guardrail"][:10] for kc, v in sorted(by_kc.items()) if v["guardrail"]},
}

out = root / "data/work/cache/diagnostics" / f"{set_path.stem}_sofja_hardened_assessment.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

print("SET_PATH =", set_path.as_posix())
print("ROWS_PATH =", rows_path.as_posix())
print("STATS_PATH =", stats_path.as_posix())
print("ASSESSMENT_JSON =", out.as_posix())
print("row_count =", len(rows))
print("duplicate_candidate_id_count =", len(dupes))
print("forbidden_field_hit_count =", len(forbidden_hits))
print("routing_breakdown =", routing_breakdown)
print("role_eligibility_breakdown =", role_breakdown)
print("known_bad_positive_hits =", json.dumps(dict(known_bad_positive_hits), indent=2, ensure_ascii=False))
print("positive_candidates_by_kc =", json.dumps(summary["positive_candidates_by_kc"], indent=2, ensure_ascii=False))

if len(rows) != 180:
    raise SystemExit(f"FAIL: expected 180 rows, got {len(rows)}")
if dupes:
    raise SystemExit("FAIL: duplicate candidate IDs found")
if forbidden_hits:
    raise SystemExit("FAIL: forbidden fields found")
if known_bad_positive_hits:
    raise SystemExit("FAIL: known-bad markers still appear in standalone positive candidates")
if role_breakdown.get("definition_kernel", 0) <= 0:
    raise SystemExit("FAIL: definition_kernel stayed at zero")
if any((root / "data/processed/evidence_stage_v3_scored_candidates/_sets").glob("ACTIVE_STEP5X_V3*")):
    raise SystemExit("FAIL: ACTIVE pointer was created unexpectedly")

print("STAGE2_V3_HARDENED_SOFJA_ASSESSMENT_OK")
PY

echo
echo "==== active pointer guard ===="
find data/processed/evidence_stage_v3_scored_candidates/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' -print

if find data/processed/evidence_stage_v3_scored_candidates/_sets -maxdepth 1 -type f -name 'ACTIVE_STEP5X_V3*' | grep -q .; then
  echo "FAIL: ACTIVE pointer was created unexpectedly"
  exit 1
fi

echo
echo "PIPELINE_STAGE2_V3_HARDENED_SOFJA_OK"
