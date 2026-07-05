#!/bin/bash
#SBATCH --job-name=s67v33_g4_f40
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=03:30:00
#SBATCH --output=logs/s67v33_g4_f40_%j.out
#SBATCH --error=logs/s67v33_g4_f40_%j.err

set -uo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

CREATED_UTC="$(date -u +%Y%m%dT%H%M%SZ)"
JOB_ID="${SLURM_JOB_ID:-manual}"

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST="127.0.0.1:$((34000 + JOB_ID % 1000))"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"
export MODEL="gemma4:31b"

FULL_LANES="data/work/cache/diagnostics/step67_generic_lane_policy_v3_3_source_sense_replay/2026-04-29_123523/lane_packets.jsonl"

DIAG="data/work/cache/diagnostics/step67_v3_3_full40_gemma4_think_${CREATED_UTC}"
RUNROOT="/beegfs2/scratch/aryp26yc/kc_l/step67_v3_3_full40_gemma4_think_${JOB_ID}_${CREATED_UTC}"
RETURN="/beegfs2/scratch/aryp26yc/kc_l/sync_bundles/step67_v3_3_full40_gemma4_think_${JOB_ID}_${CREATED_UTC}.tar.gz"

mkdir -p "$DIAG" "$RUNROOT" /beegfs2/scratch/aryp26yc/kc_l/sync_bundles

echo "===== job context ====="
date -u
hostname
echo "SLURM_JOB_ID=${SLURM_JOB_ID:-NA}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-NA}"
echo "PY=$PY"
"$PY" --version
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
echo "MODEL=$MODEL"
echo "FULL_LANES=$FULL_LANES"
echo "DIAG=$DIAG"
echo "RUNROOT=$RUNROOT"
echo "RETURN=$RETURN"

echo
echo "===== guards ====="
if [ ! -x "$PY" ]; then
  echo "Missing python executable: $PY"
  exit 10
fi

if [ ! -x "$OLLAMA_BIN" ]; then
  echo "Missing Ollama binary: $OLLAMA_BIN"
  exit 11
fi

if [ ! -f "$FULL_LANES" ]; then
  echo "Missing full lane packet file: $FULL_LANES"
  exit 12
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

echo
echo "===== start Ollama server ====="
"$OLLAMA_BIN" serve > "$RUNROOT/ollama_server.log" 2>&1 &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

cleanup() {
  status=$?
  echo
  echo "===== cleanup ====="
  echo "status=$status"
  if kill -0 "$OLLAMA_PID" 2>/dev/null; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    sleep 2
  fi
}
trap cleanup EXIT

echo
echo "===== wait for Ollama API ====="
READY=0
for i in $(seq 1 90); do
  if curl -sS "$OLLAMA_BASE_URL/api/version" > "$RUNROOT/ollama_version.json" 2>/dev/null; then
    READY=1
    echo "OLLAMA_READY_AFTER=${i}s"
    cat "$RUNROOT/ollama_version.json"
    break
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "Ollama did not become ready."
  tail -n 120 "$RUNROOT/ollama_server.log" || true
  exit 13
fi

echo
echo "===== model availability ====="
"$OLLAMA_BIN" list || true

echo
echo "===== run generic B, full40, think ====="
"$PY" scripts/experimental/step67b_lane_aware_onepass_generic.py \
  --lanes "$FULL_LANES" \
  --out-root data/processed/step67_sidecar_lane_drafts_generic_full40_v3_3/think \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode think \
  --num-ctx 8192 \
  --num-predict 8192 \
  --temperature 0.0 \
  --timeout 360 \
  2>&1 | tee "$DIAG/01_full40_think_draft.log"

B_RC=${PIPESTATUS[0]}
echo "B_RC=$B_RC"

DRAFT_DIR="$(grep 'STEP67B_GENERIC_ONEPASS_DIR =' "$DIAG/01_full40_think_draft.log" | tail -n 1 | sed 's/^.*= //')"
DRAFTS="$(grep 'STEP67B_GENERIC_ONEPASS_JSONL =' "$DIAG/01_full40_think_draft.log" | tail -n 1 | sed 's/^.*= //')"

echo "DRAFT_DIR=$DRAFT_DIR"
echo "DRAFTS=$DRAFTS"

echo
echo "===== validate generic C, full40, think ====="
if [ -f "$DRAFTS" ]; then
  "$PY" scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
    --lanes "$FULL_LANES" \
    --drafts "$DRAFTS" \
    --out-root data/processed/step67_sidecar_lane_validated_generic_full40_v3_3/think \
    2>&1 | tee "$DIAG/02_full40_think_validate.log"
  C_RC=${PIPESTATUS[0]}
else
  echo "Missing drafts file, skipping validation."
  C_RC=99
fi

echo "C_RC=$C_RC"

VALID_DIR="$(grep 'STEP67C_GENERIC_VALIDATION_DIR =' "$DIAG/02_full40_think_validate.log" 2>/dev/null | tail -n 1 | sed 's/^.*= //')"
echo "VALID_DIR=$VALID_DIR"

echo
echo "===== compact validation analysis ====="
"$PY" - "$FULL_LANES" "$DRAFTS" "$VALID_DIR" "$DIAG" <<'PY'
import json
import sys
from pathlib import Path
from collections import Counter

lanes = Path(sys.argv[1])
drafts = Path(sys.argv[2])
valid_dir = Path(sys.argv[3]) if sys.argv[3] else Path("")
diag = Path(sys.argv[4])

def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

lane_rows = load_jsonl(lanes)
draft_rows = load_jsonl(drafts)
validation_rows = load_jsonl(valid_dir / "validation_rows.jsonl") if valid_dir.exists() else []

lane_summary = {
    "lane_packet_count": len(lane_rows),
    "lane_patterns": Counter((r.get("summary") or {}).get("lane_pattern") for r in lane_rows),
    "selected_lane_totals": Counter(),
    "flag_totals": Counter(),
}

for row in lane_rows:
    summary = row.get("summary") or {}
    for k, v in (summary.get("selected_lane_counts") or {}).items():
        lane_summary["selected_lane_totals"][k] += int(v)
    for k, v in (summary.get("flag_counter") or {}).items():
        lane_summary["flag_totals"][k] += int(v)

draft_summary = {
    "draft_row_count": len(draft_rows),
    "ok_count": sum(1 for r in draft_rows if r.get("ok")),
    "fail_count": sum(1 for r in draft_rows if not r.get("ok")),
    "failed_rows": [
        {
            "kc_id": r.get("kc_id"),
            "canonical_name": r.get("canonical_name"),
            "error": r.get("error"),
            "visible_content_len": r.get("visible_content_len"),
            "thinking_char_count": r.get("thinking_char_count"),
            "response_summary": r.get("response_summary"),
        }
        for r in draft_rows
        if not r.get("ok")
    ],
}

validation_summary_path = valid_dir / "summary.json"
validation_summary = {}
if validation_summary_path.exists():
    validation_summary = json.loads(validation_summary_path.read_text(encoding="utf-8"))

problem_rows = []
for row in validation_rows:
    if row.get("errors") or row.get("warnings"):
        problem_rows.append({
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

out = {
    "lane_summary": {
        **lane_summary,
        "lane_patterns": dict(lane_summary["lane_patterns"]),
        "selected_lane_totals": dict(lane_summary["selected_lane_totals"]),
        "flag_totals_top30": dict(lane_summary["flag_totals"].most_common(30)),
    },
    "draft_summary": draft_summary,
    "validation_summary": validation_summary,
    "problem_rows": problem_rows,
}

(diag / "03_full40_compact_analysis.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

md = []
md.append("# Step 6.7 v3.3 full40 Gemma4 think compact analysis")
md.append("")
md.append("## Draft summary")
md.append("")
md.append("```json")
md.append(json.dumps(draft_summary, indent=2, ensure_ascii=False))
md.append("```")
md.append("")
md.append("## Validation summary")
md.append("")
md.append("```json")
md.append(json.dumps(validation_summary, indent=2, ensure_ascii=False))
md.append("```")
md.append("")
md.append("## Problem rows")
md.append("")
for row in problem_rows:
    md.append(f"### {row['kc_id']} | {row['canonical_name']}")
    md.append("")
    md.append("```json")
    md.append(json.dumps(row, indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")

(diag / "03_full40_compact_analysis.md").write_text(
    "\n".join(md),
    encoding="utf-8",
)

print("COMPACT_ANALYSIS_JSON =", (diag / "03_full40_compact_analysis.json").as_posix())
print("COMPACT_ANALYSIS_MD =", (diag / "03_full40_compact_analysis.md").as_posix())
print("draft_ok_count =", draft_summary["ok_count"])
print("draft_fail_count =", draft_summary["fail_count"])
print("validation_error_row_count =", validation_summary.get("error_row_count"))
print("validation_warning_row_count =", validation_summary.get("warning_row_count"))
print("problem_row_count =", len(problem_rows))
PY

RC_ANALYSIS=$?
echo "RC_ANALYSIS=$RC_ANALYSIS"

echo
echo "===== package outputs ====="
tar -czf "$RETURN" \
  scripts/experimental/step67b_lane_aware_onepass_generic.py \
  scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
  src/kc_l/kc_drafting/evidence_lane_policy.py \
  scripts/experimental/step67a_build_field_lane_packets_generic.py \
  tests/test_evidence_lane_policy.py \
  tests/test_step67_sidecar_domain_agnosticity.py \
  "$DIAG" \
  "$FULL_LANES" \
  ${DRAFT_DIR:+"$DRAFT_DIR"} \
  ${VALID_DIR:+"$VALID_DIR"} \
  "$RUNROOT/ollama_server.log" \
  2>&1 | tee "$DIAG/04_package.log"

RC_PACKAGE=${PIPESTATUS[0]}
ls -lh "$RETURN" || true
echo "RETURN=$RETURN"
echo "RC_PACKAGE=$RC_PACKAGE"

echo
echo "===== final rc summary ====="
cat > "$DIAG/final_rc_summary.txt" <<EOF
created_utc=$CREATED_UTC
job_id=$JOB_ID
host=$(hostname)
model=$MODEL
ollama_host=$OLLAMA_HOST
full_lanes=$FULL_LANES
draft_dir=$DRAFT_DIR
valid_dir=$VALID_DIR
diag=$DIAG
return_bundle=$RETURN
RC_COMPILE=$RC_COMPILE
B_RC=$B_RC
C_RC=$C_RC
RC_ANALYSIS=$RC_ANALYSIS
RC_PACKAGE=$RC_PACKAGE
active_pointer_policy=do_not_update_current_alias_or_active_pointer
EOF

cat "$DIAG/final_rc_summary.txt"

echo
echo "STEP67_V3_3_FULL40_GEMMA4_THINK_DONE"
