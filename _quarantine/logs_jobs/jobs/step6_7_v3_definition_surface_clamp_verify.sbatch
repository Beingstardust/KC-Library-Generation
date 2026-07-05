#!/bin/bash
#SBATCH --job-name=s67v3surf
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:45:00
#SBATCH --output=logs/s67v3surf-%j.out
#SBATCH --error=logs/s67v3surf-%j.err

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
STAGE3_PACKS="data/processed/evidence_stage_v3_evidence_packs/step5x_v3_evidence_packs_full144_sofja_20260428_002703/kc_evidence_packs.jsonl"

test -f "$STEP66_SET" || { echo "MISSING STEP66_SET=$STEP66_SET"; exit 1; }
test -f "$STAGE3_PACKS" || { echo "MISSING STAGE3_PACKS=$STAGE3_PACKS"; exit 1; }

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
done > data/work/cache/diagnostics/s67v3surf_alias_hashes_before_${SLURM_JOB_ID}.txt
cat data/work/cache/diagnostics/s67v3surf_alias_hashes_before_${SLURM_JOB_ID}.txt

echo
echo "==== create generated Step 6.7 config pinned to accepted v3 Step 6.6 ===="
STAMP="$(date -u +%Y%m%d_%H%M%S)"
BASE_CONFIG="steps/step_06_7_kc_draft_generation/resources/step6_7.sofja.actual_corpus.yaml"
GENERATED_CONFIG="data/work/cache/generated_configs/step6_7.sofja.actual_corpus.with_stage3_v3_exact_surface_full144_${STAMP}.yaml"

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
cfg.setdefault("metadata", {})["test"] = "stage3_v3_definition_surface_clamp_full144"
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
echo "==== run Step 6.7 full144 after exact-surface clamp ===="
"$PY" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config "$GENERATED_CONFIG"

STEP67_SET="$(ls -1t data/processed/kc_drafts/_sets/*_step6_7_kc_drafts_set.json | head -n 1)"
test -f "$STEP67_SET" || { echo "MISSING latest STEP67_SET"; exit 1; }
echo "STEP67_SET=$STEP67_SET"

echo
echo "==== exact Stage 3 surface assessment ===="
STEP66_SET="$STEP66_SET" STEP67_SET="$STEP67_SET" STAGE3_PACKS="$STAGE3_PACKS" "$PY" - <<'PY'
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

root = Path(".")
step66_set = os.environ["STEP66_SET"]
step67_set = Path(os.environ["STEP67_SET"])
stage3_packs_path = Path(os.environ["STAGE3_PACKS"])

def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()

def norm_lower(text: Any) -> str:
    return norm(text).lower()

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
stage3_rows = [json.loads(line) for line in stage3_packs_path.read_text(encoding="utf-8").splitlines() if line.strip()]

allowed_definition_texts_by_kc = {}
pack_route_by_kc = {}

for pack in stage3_rows:
    kc_id = str(pack.get("kc_id") or "")
    quality = dict(pack.get("pack_quality") or {})
    pack_route_by_kc[kc_id] = str(quality.get("route") or "")
    allowed = []
    slots = dict(pack.get("slots") or {})
    for role in ("definition_kernel", "explanatory_gloss"):
        for item in slots.get(role) or []:
            text = norm(item.get("text") or item.get("quote") or "")
            if text:
                allowed.append(text)
    for item in pack.get("ordered_pack_for_drafting") or []:
        if str(item.get("role") or "") in {"definition_kernel", "explanatory_gloss"}:
            text = norm(item.get("text") or item.get("quote") or "")
            if text:
                allowed.append(text)
    allowed_definition_texts_by_kc[kc_id] = sorted(set(allowed))

kc_ids = [str(row.get("kc_id") or "") for row in rows]
duplicate_kc_ids = sorted(kc for kc, n in Counter(kc_ids).items() if n > 1)

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
invalid_v3_grounded_definitions = []
insufficient_packet_definition_leaks = []
v3_grounded_definition_count = 0
v3_exact_surface_count = 0

for row in rows:
    kc_id = str(row.get("kc_id") or "")
    full = dict(row.get("definition_full_candidate") or {})
    full_status = str(full.get("status") or "")
    full_text = norm(full.get("text") or "")
    auth_status = str(row.get("authoritative_definition_status") or "")
    route = pack_route_by_kc.get(kc_id, "")

    for path, text in collect_definition_like_strings(row):
        text_norm = norm_lower(text)
        for marker in known_bad.get(kc_id, []):
            marker_norm = norm_lower(marker)
            if marker_norm and marker_norm in text_norm:
                known_bad_definition_hits.setdefault(kc_id, []).append({
                    "path": path,
                    "marker": marker,
                    "text": text,
                })

    if route == "insufficient_support_packet":
        if full_status == "grounded" or auth_status != "insufficient_support":
            insufficient_packet_definition_leaks.append({
                "kc_id": kc_id,
                "authoritative_definition_status": auth_status,
                "definition_full_status": full_status,
                "definition_full_text": full_text,
            })

    if full_status == "grounded":
        allowed = allowed_definition_texts_by_kc.get(kc_id) or []
        v3_grounded_definition_count += 1
        if full_text in allowed:
            v3_exact_surface_count += 1
        else:
            invalid_v3_grounded_definitions.append({
                "kc_id": kc_id,
                "definition_full_text": full_text,
                "source_text_field": full.get("source_text_field"),
                "selection_reason": full.get("selection_reason"),
                "allowed_stage3_definition_texts": allowed,
            })

by_kc = {str(row.get("kc_id") or ""): row for row in rows}
core = by_kc.get("KC_CLU_DBS_001") or {}
cv = by_kc.get("KC_EVAL_SAMP_003") or {}
core_def = dict(core.get("definition_full_candidate") or {})
core_short = dict(core.get("definition_short_candidate") or {})
cv_def = dict(cv.get("definition_full_candidate") or {})
cv_short = dict(cv.get("definition_short_candidate") or {})

assessment = {
    "assessment_scope": "step6_7_stage3_v3_definition_surface_clamp_full144",
    "step6_6_set_manifest": step66_set,
    "step6_7_set_manifest": step67_set.as_posix(),
    "drafts_path": drafts_path.as_posix(),
    "stats_path": stats_path.as_posix() if stats_path else "",
    "stage3_packs_path": stage3_packs_path.as_posix(),
    "row_count": len(rows),
    "unique_kc_count": len(set(kc_ids)),
    "duplicate_kc_ids": duplicate_kc_ids,
    "v3_grounded_definition_count": v3_grounded_definition_count,
    "v3_exact_surface_count": v3_exact_surface_count,
    "invalid_v3_grounded_definitions": invalid_v3_grounded_definitions,
    "insufficient_packet_definition_leaks": insufficient_packet_definition_leaks,
    "known_bad_definition_hits": known_bad_definition_hits,
    "draft_status_breakdown": dict(Counter(str(row.get("draft_status") or "") for row in rows)),
    "authoritative_definition_status_breakdown": dict(Counter(str(row.get("authoritative_definition_status") or "") for row in rows)),
    "KC_CLU_DBS_001": {
        "draft_status": core.get("draft_status"),
        "authoritative_definition_status": core.get("authoritative_definition_status"),
        "definition_full_candidate": core_def,
        "definition_short_candidate": core_short,
    },
    "KC_EVAL_SAMP_003": {
        "draft_status": cv.get("draft_status"),
        "authoritative_definition_status": cv.get("authoritative_definition_status"),
        "definition_full_candidate": cv_def,
        "definition_short_candidate": cv_short,
        "allowed_stage3_definition_texts": allowed_definition_texts_by_kc.get("KC_EVAL_SAMP_003") or [],
    },
    "stats": stats,
}

out = root / "data/work/cache/diagnostics" / f"{step67_set.stem}_stage3_v3_definition_surface_clamp_assessment.json"
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("ASSESSMENT_JSON =", out.as_posix())
print("STEP67_SET =", step67_set.as_posix())
print("DRAFTS_PATH =", drafts_path.as_posix())
print("row_count =", len(rows))
print("unique_kc_count =", len(set(kc_ids)))
print("duplicate_kc_ids =", duplicate_kc_ids)
print("v3_grounded_definition_count =", v3_grounded_definition_count)
print("v3_exact_surface_count =", v3_exact_surface_count)
print("invalid_v3_grounded_definitions_count =", len(invalid_v3_grounded_definitions))
print("insufficient_packet_definition_leaks_count =", len(insufficient_packet_definition_leaks))
print("known_bad_definition_hits =", json.dumps(known_bad_definition_hits, indent=2, ensure_ascii=False))
print("KC_CLU_DBS_001_status =", core.get("draft_status"), core.get("authoritative_definition_status"))
print("KC_CLU_DBS_001_definition_full =", json.dumps(core_def, indent=2, ensure_ascii=False))
print("KC_EVAL_SAMP_003_definition_full =", json.dumps(cv_def, indent=2, ensure_ascii=False))
print("KC_EVAL_SAMP_003_definition_short =", json.dumps(cv_short, indent=2, ensure_ascii=False))
print("draft_status_breakdown =", json.dumps(assessment["draft_status_breakdown"], indent=2, ensure_ascii=False))
print("authoritative_definition_status_breakdown =", json.dumps(assessment["authoritative_definition_status_breakdown"], indent=2, ensure_ascii=False))

if len(rows) != 144:
    raise SystemExit(f"FAIL: expected 144 draft rows, got {len(rows)}")
if len(set(kc_ids)) != 144:
    raise SystemExit(f"FAIL: expected 144 unique KC ids, got {len(set(kc_ids))}")
if duplicate_kc_ids:
    raise SystemExit("FAIL: duplicate KC ids")
if known_bad_definition_hits:
    raise SystemExit("FAIL: known bad markers leaked into definition-like fields")
if insufficient_packet_definition_leaks:
    raise SystemExit("FAIL: insufficient_support_packet KCs emitted grounded definitions")
if invalid_v3_grounded_definitions:
    raise SystemExit("FAIL: grounded v3 definitions do not exactly match Stage 3 definition slot text")

if str(core.get("authoritative_definition_status") or "") != "insufficient_support":
    raise SystemExit("FAIL: KC_CLU_DBS_001 should be insufficient_support")
if str(core_def.get("status") or "") != "abstained":
    raise SystemExit("FAIL: KC_CLU_DBS_001 definition_full_candidate should be abstained")
if str(core_short.get("status") or "") != "abstained":
    raise SystemExit("FAIL: KC_CLU_DBS_001 definition_short_candidate should be abstained")

expected_cv = "Cross-validation is a widely-used model evaluation method that aims to make effective use of all labeled instances in D for both training and testing."
if norm(cv_def.get("text") or "") != expected_cv:
    raise SystemExit("FAIL: KC_EVAL_SAMP_003 full definition is not the exact Stage 3 definition kernel")
if "To illustrate this method" in str(cv_def.get("text") or ""):
    raise SystemExit("FAIL: KC_EVAL_SAMP_003 still contains expanded source_block_text")
if "three-fold cross-validation" in str(cv_def.get("text") or ""):
    raise SystemExit("FAIL: KC_EVAL_SAMP_003 still contains example tail text")

print("STEP6_7_STAGE3_V3_DEFINITION_SURFACE_CLAMP_ASSESSMENT_OK")
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
done > data/work/cache/diagnostics/s67v3surf_alias_hashes_after_${SLURM_JOB_ID}.txt
cat data/work/cache/diagnostics/s67v3surf_alias_hashes_after_${SLURM_JOB_ID}.txt

diff -u \
  data/work/cache/diagnostics/s67v3surf_alias_hashes_before_${SLURM_JOB_ID}.txt \
  data/work/cache/diagnostics/s67v3surf_alias_hashes_after_${SLURM_JOB_ID}.txt

echo
echo "STEP6_7_STAGE3_V3_DEFINITION_SURFACE_CLAMP_PIPELINE_OK"
