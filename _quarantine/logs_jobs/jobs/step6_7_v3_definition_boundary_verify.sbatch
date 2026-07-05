#!/bin/bash
#SBATCH --job-name=s67v3fix
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:45:00
#SBATCH --output=logs/s67v3fix-%j.out
#SBATCH --error=logs/s67v3fix-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "==== job context ===="
date -u
hostname
echo "PWD=$PWD"
"$PY" --version

STEP66_SET="data/processed/kc_drafting_input_overlay/_sets/2026-04-28_002730_step6_6_kc_drafting_input_overlay_set.json"
test -f "$STEP66_SET" || { echo "MISSING STEP66_SET=$STEP66_SET"; exit 1; }

echo
echo "==== protect current aliases before run ===="
for rel in \
  data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json \
  data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json \
  data/work/cache/current_step_artifacts/step6_75_set_manifest.current.json \
  data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json
do
  if [ -f "$rel" ]; then
    sha256sum "$rel"
  else
    echo "MISSING_ALIAS $rel"
  fi
done > data/work/cache/diagnostics/s67v3fix_alias_hashes_before_${SLURM_JOB_ID}.txt
cat data/work/cache/diagnostics/s67v3fix_alias_hashes_before_${SLURM_JOB_ID}.txt

echo
echo "==== create generated Step 6.7 config pinned to accepted v3 Step 6.6 ===="
STAMP="$(date -u +%Y%m%d_%H%M%S)"
BASE_CONFIG="steps/step_06_7_kc_draft_generation/resources/step6_7.sofja.actual_corpus.yaml"
GENERATED_CONFIG="data/work/cache/generated_configs/step6_7.sofja.actual_corpus.with_stage3_v3_step66_full144_definition_boundary_${STAMP}.yaml"

BASE_CONFIG="$BASE_CONFIG" GENERATED_CONFIG="$GENERATED_CONFIG" STEP66_SET="$STEP66_SET" "$PY" - <<'PY'
import json
import os
from pathlib import Path
import yaml

base = Path(os.environ["BASE_CONFIG"])
out = Path(os.environ["GENERATED_CONFIG"])
step66 = os.environ["STEP66_SET"]

cfg = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
cfg.setdefault("inputs", {})["step6_6_set_manifest"] = step66
cfg.setdefault("slice", {})["limit_kcs"] = 144
cfg.setdefault("metadata", {})["test"] = "stage3_v3_definition_boundary_fix_full144"
cfg["metadata"]["accepted_step6_6_set_manifest"] = step66
cfg["metadata"]["active_pointer_policy"] = "do_not_update_current_alias_or_active_pointer"

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print("GENERATED_CONFIG =", out.as_posix())
print(json.dumps(cfg, indent=2, ensure_ascii=False)[:3000])
PY

echo
echo "==== py_compile ===="
"$PY" -m py_compile \
  src/kc_l/kc_drafting/heuristic_core.py \
  src/kc_l/kc_drafting/orchestration.py \
  src/kc_l/kc_drafting/packetization.py \
  steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py

echo
echo "==== run Step 6.7 full144 after definition-boundary fix ===="
"$PY" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config "$GENERATED_CONFIG"

STEP67_SET="$(ls -1t data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json | head -n 1)"
test -f "$STEP67_SET" || { echo "MISSING latest STEP67_SET"; exit 1; }
echo "STEP67_SET=$STEP67_SET"

echo
echo "==== post-run semantic assessment ===="
STEP66_SET="$STEP66_SET" STEP67_SET="$STEP67_SET" "$PY" - <<'PY'
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

root = Path(".")
step66_set = os.environ["STEP66_SET"]
step67_set = Path(os.environ["STEP67_SET"])

set_obj = json.loads(step67_set.read_text(encoding="utf-8"))
set_text = json.dumps(set_obj, ensure_ascii=False)

if step66_set not in set_text and Path(step66_set).name not in set_text:
    raise SystemExit("FAIL: Step 6.7 set does not reference accepted Step 6.6 set")

artifacts = set_obj.get("artifacts") or {}
drafts_rel = (
    artifacts.get("kc_draft_bundles_jsonl")
    or artifacts.get("draft_bundles_jsonl")
    or artifacts.get("kc_drafts_jsonl")
)
stats_rel = artifacts.get("draft_stats_json") or artifacts.get("kc_draft_stats_json")

if not drafts_rel:
    raise SystemExit(f"FAIL: no draft JSONL artifact in {artifacts}")

drafts_path = Path(drafts_rel)
if not drafts_path.is_absolute():
    drafts_path = root / drafts_path

stats_path = Path(stats_rel) if stats_rel else None
if stats_path is not None and not stats_path.is_absolute():
    stats_path = root / stats_path

rows = [json.loads(line) for line in drafts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path and stats_path.exists() else {}

kc_ids = [str(row.get("kc_id") or "") for row in rows]
duplicate_kc_ids = sorted(kc for kc, n in Counter(kc_ids).items() if n > 1)

def norm(text: Any) -> str:
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
        "snn density-based clustering",
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

def collect_definition_like_strings(obj: Any, path: str = "") -> list[tuple[str, str]]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{path}.{k}" if path else str(k)
            out.extend(collect_definition_like_strings(v, kp))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(collect_definition_like_strings(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        low_path = path.lower()
        if (
            ("definition" in low_path or "scope" in low_path or "draft" in low_path)
            and "seed_definition" not in low_path
            and "evidence" not in low_path
            and "quote" not in low_path
        ):
            out.append((path, obj))
    return out

known_bad_definition_hits = {}
for row in rows:
    kc_id = str(row.get("kc_id") or "")
    for path, text in collect_definition_like_strings(row):
        text_norm = norm(text)
        for marker in known_bad.get(kc_id, []):
            marker_norm = norm(marker)
            if marker_norm and marker_norm in text_norm:
                known_bad_definition_hits.setdefault(kc_id, []).append({
                    "path": path,
                    "marker": marker,
                    "text": text,
                })

by_kc = {str(row.get("kc_id") or ""): row for row in rows}

core = by_kc.get("KC_CLU_DBS_001") or {}
cv = by_kc.get("KC_EVAL_SAMP_003") or {}

core_def = core.get("definition_full_candidate") or {}
core_short = core.get("definition_short_candidate") or {}
cv_def = cv.get("definition_full_candidate") or {}

assessment = {
    "assessment_scope": "step6_7_stage3_v3_definition_boundary_fix_full144",
    "step6_6_set_manifest": step66_set,
    "step6_7_set_manifest": step67_set.as_posix(),
    "drafts_path": drafts_path.as_posix(),
    "stats_path": stats_path.as_posix() if stats_path else "",
    "row_count": len(rows),
    "unique_kc_count": len(set(kc_ids)),
    "duplicate_kc_ids": duplicate_kc_ids,
    "known_bad_definition_hits": known_bad_definition_hits,
    "draft_status_breakdown": Counter(str(row.get("draft_status") or "") for row in rows),
    "authoritative_definition_status_breakdown": Counter(str(row.get("authoritative_definition_status") or "") for row in rows),
    "KC_CLU_DBS_001": {
        "draft_status": core.get("draft_status"),
        "authoritative_definition_status": core.get("authoritative_definition_status"),
        "definition_full_candidate": core_def,
        "definition_short_candidate": core_short,
        "selection_diagnostics_evidence_pack": (core.get("selection_diagnostics") or {}).get("evidence_pack"),
    },
    "KC_EVAL_SAMP_003": {
        "draft_status": cv.get("draft_status"),
        "authoritative_definition_status": cv.get("authoritative_definition_status"),
        "definition_full_candidate": cv_def,
        "selection_diagnostics_evidence_pack": (cv.get("selection_diagnostics") or {}).get("evidence_pack"),
    },
    "stats": stats,
}

out = root / "data/work/cache/diagnostics" / f"{step67_set.stem}_stage3_v3_definition_boundary_assessment.json"
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False, default=lambda x: dict(x)), encoding="utf-8")

print("ASSESSMENT_JSON =", out.as_posix())
print("STEP67_SET =", step67_set.as_posix())
print("DRAFTS_PATH =", drafts_path.as_posix())
print("row_count =", len(rows))
print("unique_kc_count =", len(set(kc_ids)))
print("duplicate_kc_ids =", duplicate_kc_ids)
print("known_bad_definition_hits =", json.dumps(known_bad_definition_hits, indent=2, ensure_ascii=False))
print("KC_CLU_DBS_001_status =", core.get("draft_status"), core.get("authoritative_definition_status"))
print("KC_CLU_DBS_001_definition_full =", json.dumps(core_def, indent=2, ensure_ascii=False))
print("KC_EVAL_SAMP_003_definition_full =", json.dumps(cv_def, indent=2, ensure_ascii=False))
print("draft_status_breakdown =", json.dumps(dict(assessment["draft_status_breakdown"]), indent=2, ensure_ascii=False))
print("authoritative_definition_status_breakdown =", json.dumps(dict(assessment["authoritative_definition_status_breakdown"]), indent=2, ensure_ascii=False))

if len(rows) != 144:
    raise SystemExit(f"FAIL: expected 144 draft rows, got {len(rows)}")
if len(set(kc_ids)) != 144:
    raise SystemExit(f"FAIL: expected 144 unique KC ids, got {len(set(kc_ids))}")
if duplicate_kc_ids:
    raise SystemExit("FAIL: duplicate KC ids")
if known_bad_definition_hits:
    raise SystemExit("FAIL: known bad markers still leaked into definition-like fields")

if str(core.get("authoritative_definition_status") or "") != "insufficient_support":
    raise SystemExit("FAIL: KC_CLU_DBS_001 should be insufficient_support after v3 boundary enforcement")
if str(core_def.get("status") or "") != "abstained":
    raise SystemExit("FAIL: KC_CLU_DBS_001 definition_full_candidate should be abstained")
if str(core_short.get("status") or "") != "abstained":
    raise SystemExit("FAIL: KC_CLU_DBS_001 definition_short_candidate should be abstained")

cv_text = norm(cv_def.get("text") or "")
if "cross-validation is a widely-used model evaluation method" not in cv_text:
    raise SystemExit("FAIL: KC_EVAL_SAMP_003 did not use the Stage 3 definition kernel")
if "hyper-parameter" in cv_text:
    raise SystemExit("FAIL: KC_EVAL_SAMP_003 still uses hyperparameter-selection text")

print("STEP6_7_STAGE3_V3_DEFINITION_BOUNDARY_FIX_ASSESSMENT_OK")
PY

echo
echo "==== protect current aliases after run ===="
for rel in \
  data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json \
  data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json \
  data/work/cache/current_step_artifacts/step6_75_set_manifest.current.json \
  data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json
do
  if [ -f "$rel" ]; then
    sha256sum "$rel"
  else
    echo "MISSING_ALIAS $rel"
  fi
done > data/work/cache/diagnostics/s67v3fix_alias_hashes_after_${SLURM_JOB_ID}.txt
cat data/work/cache/diagnostics/s67v3fix_alias_hashes_after_${SLURM_JOB_ID}.txt

diff -u \
  data/work/cache/diagnostics/s67v3fix_alias_hashes_before_${SLURM_JOB_ID}.txt \
  data/work/cache/diagnostics/s67v3fix_alias_hashes_after_${SLURM_JOB_ID}.txt

echo
echo "STEP6_7_STAGE3_V3_DEFINITION_BOUNDARY_FIX_PIPELINE_OK"
