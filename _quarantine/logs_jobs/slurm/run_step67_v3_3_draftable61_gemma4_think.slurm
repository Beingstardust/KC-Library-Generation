#!/bin/bash
#SBATCH --job-name=s67v33_g4_d61
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=logs/s67v33_g4_d61_%j.out
#SBATCH --error=logs/s67v33_g4_d61_%j.err

set -uo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

CREATED_UTC="$(date -u +%Y%m%dT%H%M%SZ)"
JOB_ID="${SLURM_JOB_ID:-manual}"
PORT=$((33000 + JOB_ID % 10000))

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN="/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama"
export OLLAMA_MODELS="/beegfs2/scratch/aryp26yc/kc_l/ollama/models"
export OLLAMA_HOST="127.0.0.1:${PORT}"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"

MODEL="gemma4:31b"

SPLIT_DIR="data/work/cache/diagnostics/step67_v3_3_full144_lane_split/20260429T150636Z"
LANES="$SPLIT_DIR/draftable_strongish_61_lane_packets.jsonl"

DIAG="data/work/cache/diagnostics/step67_v3_3_draftable61_gemma4_think_${CREATED_UTC}"
RUNROOT="/beegfs2/scratch/aryp26yc/kc_l/step67_v3_3_draftable61_gemma4_think_${JOB_ID}_${CREATED_UTC}"
RETURN="/beegfs2/scratch/aryp26yc/kc_l/sync_bundles/step67_v3_3_draftable61_gemma4_think_${JOB_ID}_${CREATED_UTC}.tar.gz"

mkdir -p "$DIAG" "$RUNROOT" "$(dirname "$RETURN")"

echo "===== job context ====="
date -u
hostname
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
echo "PY=$PY"
"$PY" --version
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
echo "MODEL=$MODEL"
echo "LANES=$LANES"
echo "DIAG=$DIAG"
echo "RUNROOT=$RUNROOT"
echo "RETURN=$RETURN"

echo
echo "===== guards ====="
if [ ! -x "$PY" ]; then
  echo "ERROR: PY is not executable: $PY"
  exit 10
fi

if [ ! -x "$OLLAMA_BIN" ]; then
  echo "ERROR: OLLAMA_BIN is not executable: $OLLAMA_BIN"
  exit 11
fi

if [ ! -f "$LANES" ]; then
  echo "ERROR: lane packet file not found: $LANES"
  exit 12
fi

LANE_COUNT="$("$PY" - "$LANES" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
n = 0
for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
    if line.strip():
        json.loads(line)
        n += 1
print(n)
PY
)"
echo "LANE_COUNT=$LANE_COUNT"

if [ "$LANE_COUNT" -ne 61 ]; then
  echo "ERROR: expected 61 draftable lane packets, got $LANE_COUNT"
  exit 13
fi

echo
echo "===== gpu ====="
nvidia-smi || true

echo
echo "===== compile B/C and policy ====="
"$PY" -m py_compile \
  scripts/experimental/step67b_lane_aware_onepass_generic.py \
  scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
  src/kc_l/kc_drafting/evidence_lane_policy.py \
  scripts/experimental/step67a_build_field_lane_packets_generic.py

RC_COMPILE=$?
echo "RC_COMPILE=$RC_COMPILE"
if [ "$RC_COMPILE" -ne 0 ]; then
  exit "$RC_COMPILE"
fi

echo
echo "===== start Ollama server ====="
"$OLLAMA_BIN" serve > "$DIAG/ollama_server.log" 2>&1 &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

cleanup() {
  status=$?
  echo
  echo "===== cleanup ====="
  echo "status=$status"
  if [ -n "${OLLAMA_PID:-}" ]; then
    kill "$OLLAMA_PID" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

echo
echo "===== wait for Ollama API ====="
READY=0
for i in $(seq 1 90); do
  if curl -fsS "$OLLAMA_BASE_URL/api/version" > "$DIAG/ollama_version.json" 2>/dev/null; then
    READY=1
    echo "OLLAMA_READY_AFTER=${i}s"
    cat "$DIAG/ollama_version.json"
    break
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: Ollama API did not become ready"
  tail -n 120 "$DIAG/ollama_server.log" || true
  exit 20
fi

echo
echo "===== model availability ====="
"$OLLAMA_BIN" list || true

echo
echo "===== run generic B, draftable61, think ====="
"$PY" scripts/experimental/step67b_lane_aware_onepass_generic.py \
  --lanes "$LANES" \
  --out-root data/processed/step67_sidecar_lane_drafts_generic_draftable61_v3_3/think \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode think \
  --num-ctx 8192 \
  --num-predict 8192 \
  --temperature 0.0 \
  --timeout 300 \
  2>&1 | tee "$DIAG/01_step67b_draftable61.log"

B_RC=${PIPESTATUS[0]}
echo "B_RC=$B_RC"

DRAFT_DIR="$(grep 'STEP67B_GENERIC_ONEPASS_DIR =' "$DIAG/01_step67b_draftable61.log" | tail -n 1 | sed 's/^.*= //')"
DRAFTS="$(grep 'STEP67B_GENERIC_ONEPASS_JSONL =' "$DIAG/01_step67b_draftable61.log" | tail -n 1 | sed 's/^.*= //')"

echo "DRAFT_DIR=$DRAFT_DIR"
echo "DRAFTS=$DRAFTS"

if [ "$B_RC" -ne 0 ]; then
  echo "ERROR: Step 6.7B failed"
fi

echo
echo "===== validate generic C, draftable61, think ====="
if [ -n "${DRAFTS:-}" ] && [ -f "$DRAFTS" ]; then
  "$PY" scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
    --lanes "$LANES" \
    --drafts "$DRAFTS" \
    --out-root data/processed/step67_sidecar_lane_validated_generic_draftable61_v3_3/think \
    2>&1 | tee "$DIAG/02_step67c_validate_draftable61.log"

  C_RC=${PIPESTATUS[0]}
else
  echo "ERROR: Draft file missing, cannot validate"
  C_RC=30
fi

echo "C_RC=$C_RC"

VALID_DIR="$(grep 'STEP67C_GENERIC_VALIDATION_DIR =' "$DIAG/02_step67c_validate_draftable61.log" 2>/dev/null | tail -n 1 | sed 's/^.*= //')"
echo "VALID_DIR=$VALID_DIR"

echo
echo "===== compact validation analysis ====="
"$PY" - "$LANES" "$DRAFTS" "$VALID_DIR" "$DIAG" <<'PY'
import json
import sys
from pathlib import Path
from collections import Counter

lanes = Path(sys.argv[1])
drafts = Path(sys.argv[2]) if sys.argv[2] else None
valid_dir = Path(sys.argv[3]) if sys.argv[3] else None
diag = Path(sys.argv[4])
diag.mkdir(parents=True, exist_ok=True)

analysis = {
    "lanes": lanes.as_posix(),
    "drafts": drafts.as_posix() if drafts else "",
    "valid_dir": valid_dir.as_posix() if valid_dir else "",
    "lane_count": 0,
    "draft_row_count": 0,
    "draft_ok_count": 0,
    "draft_fail_count": 0,
    "validation_summary": {},
    "problem_rows": [],
}

for line in lanes.read_text(encoding="utf-8", errors="replace").splitlines():
    if line.strip():
        analysis["lane_count"] += 1

if drafts and drafts.exists():
    for line in drafts.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        analysis["draft_row_count"] += 1
        if row.get("ok"):
            analysis["draft_ok_count"] += 1
        else:
            analysis["draft_fail_count"] += 1

if valid_dir and valid_dir.exists():
    summary_path = valid_dir / "summary.json"
    rows_path = valid_dir / "validation_rows.jsonl"

    if summary_path.exists():
        analysis["validation_summary"] = json.loads(summary_path.read_text(encoding="utf-8"))

    if rows_path.exists():
        for line in rows_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("errors") or row.get("warnings"):
                analysis["problem_rows"].append({
                    "kc_id": row.get("kc_id"),
                    "canonical_name": row.get("canonical_name"),
                    "definition_status": row.get("definition_status"),
                    "definition_grounding_mode": row.get("definition_grounding_mode"),
                    "definition_supporting_lanes": row.get("definition_supporting_lanes"),
                    "scope_status": row.get("scope_status"),
                    "scope_grounding_mode": row.get("scope_grounding_mode"),
                    "scope_supporting_lanes": row.get("scope_supporting_lanes"),
                    "errors": row.get("errors"),
                    "warnings": row.get("warnings"),
                })

(diag / "03_draftable61_compact_analysis.json").write_text(
    json.dumps(analysis, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

md = []
md.append("# Step 6.7 v3.3 draftable61 Gemma4 think compact analysis")
md.append("")
md.append("```json")
md.append(json.dumps(analysis, indent=2, ensure_ascii=False))
md.append("```")
(diag / "03_draftable61_compact_analysis.md").write_text("\n".join(md), encoding="utf-8")

print("COMPACT_ANALYSIS_JSON =", (diag / "03_draftable61_compact_analysis.json").as_posix())
print("draft_ok_count =", analysis["draft_ok_count"])
print("draft_fail_count =", analysis["draft_fail_count"])
print("validation_error_row_count =", analysis["validation_summary"].get("error_row_count"))
print("validation_warning_row_count =", analysis["validation_summary"].get("warning_row_count"))
print("problem_row_count =", len(analysis["problem_rows"]))
PY

RC_ANALYSIS=$?
echo "RC_ANALYSIS=$RC_ANALYSIS"

echo
echo "===== package outputs ====="
tar -czf "$RETURN" \
  "$DIAG" \
  "$LANES" \
  "$DRAFT_DIR" \
  "$VALID_DIR" \
  "$SPLIT_DIR/split_summary.json" \
  "$SPLIT_DIR/split_audit.md" \
  scripts/experimental/step67b_lane_aware_onepass_generic.py \
  scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
  src/kc_l/kc_drafting/evidence_lane_policy.py \
  2>&1 | tee "$DIAG/04_package.log"

RC_PACKAGE=${PIPESTATUS[0]}
ls -lh "$RETURN" || true
echo "RETURN=$RETURN"
echo "RC_PACKAGE=$RC_PACKAGE"

echo
echo "===== final rc summary ====="
{
  echo "created_utc=$CREATED_UTC"
  echo "job_id=$JOB_ID"
  echo "host=$(hostname)"
  echo "model=$MODEL"
  echo "ollama_host=$OLLAMA_HOST"
  echo "lanes=$LANES"
  echo "draft_dir=$DRAFT_DIR"
  echo "valid_dir=$VALID_DIR"
  echo "diag=$DIAG"
  echo "return_bundle=$RETURN"
  echo "RC_COMPILE=$RC_COMPILE"
  echo "B_RC=$B_RC"
  echo "C_RC=$C_RC"
  echo "RC_ANALYSIS=$RC_ANALYSIS"
  echo "RC_PACKAGE=$RC_PACKAGE"
  echo "active_pointer_policy=do_not_update_current_alias_or_active_pointer"
} | tee "$DIAG/final_rc_summary.txt"

echo
echo "STEP67_V3_3_DRAFTABLE61_GEMMA4_THINK_DONE"

if [ "$B_RC" -ne 0 ]; then
  exit "$B_RC"
fi

if [ "$C_RC" -ne 0 ]; then
  exit "$C_RC"
fi

if [ "$RC_ANALYSIS" -ne 0 ]; then
  exit "$RC_ANALYSIS"
fi

if [ "$RC_PACKAGE" -ne 0 ]; then
  exit "$RC_PACKAGE"
fi

exit 0
