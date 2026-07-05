#!/bin/bash
#SBATCH --job-name=s67v33_g4_sm8
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=logs/s67v33_g4_sm8_%j.out
#SBATCH --error=logs/s67v33_g4_sm8_%j.err

set -uo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models

PORT="$((33000 + SLURM_JOB_ID % 1000))"
export OLLAMA_HOST="127.0.0.1:${PORT}"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"

MODEL="gemma4:31b"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

REPLAY_ROOT="data/work/cache/diagnostics/step67_generic_lane_policy_v3_3_source_sense_replay"
REPLAY_DIR="$(ls -1td "$REPLAY_ROOT"/2026-* 2>/dev/null | head -n 1)"
FULL_LANES="$REPLAY_DIR/lane_packets.jsonl"

DIAG="data/work/cache/diagnostics/step67_v3_3_gemma_smoke8_${STAMP}"
RUNROOT="/beegfs2/scratch/aryp26yc/kc_l/step67_v3_3_gemma_smoke8_${SLURM_JOB_ID}_${STAMP}"
RETURN="/beegfs2/scratch/aryp26yc/kc_l/sync_bundles/step67_v3_3_gemma_smoke8_${SLURM_JOB_ID}_${STAMP}.tar.gz"

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
echo "REPLAY_DIR=$REPLAY_DIR"
echo "FULL_LANES=$FULL_LANES"
echo "DIAG=$DIAG"
echo "RUNROOT=$RUNROOT"
echo "RETURN=$RETURN"

echo
echo "===== guards ====="
if [ -z "$REPLAY_DIR" ] || [ ! -f "$FULL_LANES" ]; then
  echo "ERROR: v3.3 replay lane_packets.jsonl not found."
  exit 2
fi

if [ ! -x "$OLLAMA_BIN" ]; then
  echo "ERROR: Ollama binary not executable: $OLLAMA_BIN"
  exit 2
fi

if [ ! -x "$PY" ]; then
  echo "ERROR: Python venv not executable: $PY"
  exit 2
fi

echo
echo "===== gpu ====="
nvidia-smi || true

echo
echo "===== compile generic B/C ====="
"$PY" -m py_compile \
  scripts/experimental/step67b_lane_aware_onepass_generic.py \
  scripts/experimental/step67c_validate_lane_aware_drafts_generic.py
RC_COMPILE=$?
echo "RC_COMPILE=$RC_COMPILE"

echo
echo "===== create target lane subset ====="
TARGET_LANES="$DIAG/target_smoke8_lane_packets.jsonl"

"$PY" - "$FULL_LANES" "$TARGET_LANES" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

target_ids = [
    "KC_CLU_HIER_005",   # MAX Complete Linkage, restored definition
    "KC_CLU_DBS_003",    # Noise Point, hierarchy-sense risk
    "KC_CLU_DBS_001",    # Core Point, sibling contrast risk
    "KC_CLU_EVAL_002",   # SSE, contextual synthesis
    "KC_EVAL_BASIC_001", # Confusion Matrix, direct definition
    "KC_CLU_SIM_003",    # Euclidean Distance, thin evidence case
    "KC_CLF_NB_003",     # Conditional Probability/Likelihood, prior off-target risk
    "KC_CLF_DT_001",     # Hunt-style fragment risk
]

wanted = set(target_ids)
rows = []

for line in src.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("kc_id") in wanted:
        rows.append(row)

found = [row.get("kc_id") for row in rows]
missing = [x for x in target_ids if x not in found]

if missing:
    raise SystemExit(f"Missing target lane packets: {missing}")

ordered = []
by_id = {row.get("kc_id"): row for row in rows}
for kc_id in target_ids:
    ordered.append(by_id[kc_id])

dst.write_text(
    "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in ordered) + "\n",
    encoding="utf-8",
)

print("TARGET_LANE_COUNT =", len(ordered))
print("TARGET_IDS =", ",".join(target_ids))
PY

RC_SUBSET=$?
echo "RC_SUBSET=$RC_SUBSET"

echo
echo "===== start Ollama server ====="
"$OLLAMA_BIN" serve > "$RUNROOT/ollama_server.log" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  status=$?
  echo
  echo "===== cleanup ====="
  echo "status=$status"
  if [ -n "${OLLAMA_PID:-}" ]; then
    kill "$OLLAMA_PID" >/dev/null 2>&1 || true
    wait "$OLLAMA_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo
echo "===== wait for Ollama API ====="
READY=0
for i in $(seq 1 60); do
  "$PY" - <<PY >/dev/null 2>&1
import json, urllib.request
urllib.request.urlopen("http://${OLLAMA_HOST}/api/version", timeout=2).read()
PY
  if [ "$?" -eq 0 ]; then
    READY=1
    echo "OLLAMA_READY_AFTER=${i}s"
    break
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: Ollama API did not become ready."
  tail -n 120 "$RUNROOT/ollama_server.log" || true
  exit 2
fi

"$PY" - <<PY
import json, urllib.request
print(urllib.request.urlopen("http://${OLLAMA_HOST}/api/version", timeout=5).read().decode())
PY

echo
echo "===== model availability ====="
"$OLLAMA_BIN" list || true

echo
echo "===== direct chat sanity, nothink ====="
"$PY" - <<PY
import json, urllib.request
body = {
    "model": "${MODEL}",
    "messages": [{"role": "user", "content": "Return only this JSON object: {\\\"ok\\\": true}"}],
    "stream": False,
    "think": False,
    "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 64},
}
req = urllib.request.Request(
    "http://${OLLAMA_HOST}/api/chat",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
msg = resp.get("message") or {}
print(json.dumps({
    "done": resp.get("done"),
    "done_reason": resp.get("done_reason"),
    "content": msg.get("content"),
    "thinking_len": len(msg.get("thinking") or ""),
}, ensure_ascii=False))
PY
RC_SANITY_NOTHINK=$?
echo "RC_SANITY_NOTHINK=$RC_SANITY_NOTHINK"

echo
echo "===== direct chat sanity, think ====="
"$PY" - <<PY
import json, urllib.request
body = {
    "model": "${MODEL}",
    "messages": [{"role": "user", "content": "Return only this JSON object: {\\\"ok\\\": true}"}],
    "stream": False,
    "think": True,
    "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 512},
}
req = urllib.request.Request(
    "http://${OLLAMA_HOST}/api/chat",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = json.loads(urllib.request.urlopen(req, timeout=180).read().decode())
msg = resp.get("message") or {}
print(json.dumps({
    "done": resp.get("done"),
    "done_reason": resp.get("done_reason"),
    "content": msg.get("content"),
    "content_len": len(msg.get("content") or ""),
    "thinking_len": len(msg.get("thinking") or ""),
}, ensure_ascii=False))
PY
RC_SANITY_THINK=$?
echo "RC_SANITY_THINK=$RC_SANITY_THINK"

echo
echo "===== run generic B, nothink, smoke8 ====="
NOTHINK_OUT="data/processed/step67_sidecar_lane_drafts_generic_smoke_v3_3/nothink"

"$PY" scripts/experimental/step67b_lane_aware_onepass_generic.py \
  --lanes "$TARGET_LANES" \
  --out-root "$NOTHINK_OUT" \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode nothink \
  --num-ctx 8192 \
  --num-predict 1000 \
  --temperature 0.0 \
  --timeout 240 \
  2>&1 | tee "$DIAG/01_nothink_draft.log"

B_NOTHINK_RC=${PIPESTATUS[0]}
echo "B_NOTHINK_RC=$B_NOTHINK_RC"

NOTHINK_DRAFT_DIR="$(ls -1td "$NOTHINK_OUT"/2026-* 2>/dev/null | head -n 1)"
NOTHINK_DRAFTS="$NOTHINK_DRAFT_DIR/onepass_drafts.jsonl"

echo "NOTHINK_DRAFT_DIR=$NOTHINK_DRAFT_DIR"
echo "NOTHINK_DRAFTS=$NOTHINK_DRAFTS"

echo
echo "===== validate generic C, nothink ====="
NOTHINK_VALID_OUT="data/processed/step67_sidecar_lane_validated_generic_smoke_v3_3/nothink"

"$PY" scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
  --lanes "$TARGET_LANES" \
  --drafts "$NOTHINK_DRAFTS" \
  --out-root "$NOTHINK_VALID_OUT" \
  2>&1 | tee "$DIAG/02_nothink_validate.log"

C_NOTHINK_RC=${PIPESTATUS[0]}
echo "C_NOTHINK_RC=$C_NOTHINK_RC"

NOTHINK_VALID_DIR="$(ls -1td "$NOTHINK_VALID_OUT"/2026-* 2>/dev/null | head -n 1)"
echo "NOTHINK_VALID_DIR=$NOTHINK_VALID_DIR"

echo
echo "===== run generic B, think, smoke8 ====="
THINK_OUT="data/processed/step67_sidecar_lane_drafts_generic_smoke_v3_3/think"

"$PY" scripts/experimental/step67b_lane_aware_onepass_generic.py \
  --lanes "$TARGET_LANES" \
  --out-root "$THINK_OUT" \
  --model "$MODEL" \
  --base-url "$OLLAMA_BASE_URL" \
  --reasoning-mode think \
  --num-ctx 8192 \
  --num-predict 8192 \
  --temperature 0.0 \
  --timeout 420 \
  2>&1 | tee "$DIAG/03_think_draft.log"

B_THINK_RC=${PIPESTATUS[0]}
echo "B_THINK_RC=$B_THINK_RC"

THINK_DRAFT_DIR="$(ls -1td "$THINK_OUT"/2026-* 2>/dev/null | head -n 1)"
THINK_DRAFTS="$THINK_DRAFT_DIR/onepass_drafts.jsonl"

echo "THINK_DRAFT_DIR=$THINK_DRAFT_DIR"
echo "THINK_DRAFTS=$THINK_DRAFTS"

echo
echo "===== validate generic C, think ====="
THINK_VALID_OUT="data/processed/step67_sidecar_lane_validated_generic_smoke_v3_3/think"

"$PY" scripts/experimental/step67c_validate_lane_aware_drafts_generic.py \
  --lanes "$TARGET_LANES" \
  --drafts "$THINK_DRAFTS" \
  --out-root "$THINK_VALID_OUT" \
  2>&1 | tee "$DIAG/04_think_validate.log"

C_THINK_RC=${PIPESTATUS[0]}
echo "C_THINK_RC=$C_THINK_RC"

THINK_VALID_DIR="$(ls -1td "$THINK_VALID_OUT"/2026-* 2>/dev/null | head -n 1)"
echo "THINK_VALID_DIR=$THINK_VALID_DIR"

echo
echo "===== create compact comparison ====="
"$PY" - "$TARGET_LANES" "$NOTHINK_DRAFTS" "$NOTHINK_VALID_DIR/validation_rows.jsonl" "$THINK_DRAFTS" "$THINK_VALID_DIR/validation_rows.jsonl" "$DIAG" <<'PY'
import json
import sys
from pathlib import Path

lanes_path = Path(sys.argv[1])
nothink_drafts_path = Path(sys.argv[2])
nothink_rows_path = Path(sys.argv[3])
think_drafts_path = Path(sys.argv[4])
think_rows_path = Path(sys.argv[5])
out_dir = Path(sys.argv[6])

def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

def by_kc(rows):
    return {str(r.get("kc_id") or ""): r for r in rows}

def parsed_field(draft, field):
    parsed = draft.get("parsed") if isinstance(draft.get("parsed"), dict) else {}
    value = parsed.get(field) if isinstance(parsed.get(field), dict) else {}
    return value

lane_packets = by_kc(load_jsonl(lanes_path))
nd = by_kc(load_jsonl(nothink_drafts_path))
nr = by_kc(load_jsonl(nothink_rows_path))
td = by_kc(load_jsonl(think_drafts_path))
tr = by_kc(load_jsonl(think_rows_path))

summary_rows = []

for kc_id, packet in lane_packets.items():
    n_draft = nd.get(kc_id, {})
    t_draft = td.get(kc_id, {})
    n_val = nr.get(kc_id, {})
    t_val = tr.get(kc_id, {})

    row = {
        "kc_id": kc_id,
        "canonical_name": packet.get("canonical_name"),
        "lane_summary": packet.get("summary"),
        "nothink": {
            "ok": n_draft.get("ok"),
            "error": n_draft.get("error"),
            "visible_content_len": n_draft.get("visible_content_len"),
            "thinking_char_count": n_draft.get("thinking_char_count"),
            "definition": parsed_field(n_draft, "definition"),
            "scope": parsed_field(n_draft, "scope"),
            "validation_errors": n_val.get("errors"),
            "validation_warnings": n_val.get("warnings"),
        },
        "think": {
            "ok": t_draft.get("ok"),
            "error": t_draft.get("error"),
            "visible_content_len": t_draft.get("visible_content_len"),
            "thinking_char_count": t_draft.get("thinking_char_count"),
            "definition": parsed_field(t_draft, "definition"),
            "scope": parsed_field(t_draft, "scope"),
            "validation_errors": t_val.get("errors"),
            "validation_warnings": t_val.get("warnings"),
        },
    }
    summary_rows.append(row)

(out_dir / "05_smoke8_comparison.json").write_text(
    json.dumps(summary_rows, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

md = []
md.append("# Step 6.7 v3.3 Gemma smoke8 comparison")
md.append("")

for row in summary_rows:
    md.append(f"## {row['kc_id']} | {row['canonical_name']}")
    md.append("")
    md.append("### Lane summary")
    md.append("```json")
    md.append(json.dumps(row["lane_summary"], indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")
    for mode in ["nothink", "think"]:
        data = row[mode]
        md.append(f"### {mode}")
        md.append(f"- ok: `{data['ok']}`")
        md.append(f"- error: `{data['error']}`")
        md.append(f"- visible_content_len: `{data['visible_content_len']}`")
        md.append(f"- thinking_char_count: `{data['thinking_char_count']}`")
        md.append(f"- validation_errors: `{data['validation_errors']}`")
        md.append(f"- validation_warnings: `{data['validation_warnings']}`")
        md.append("")
        md.append("definition:")
        md.append("```json")
        md.append(json.dumps(data["definition"], indent=2, ensure_ascii=False))
        md.append("```")
        md.append("")
        md.append("scope:")
        md.append("```json")
        md.append(json.dumps(data["scope"], indent=2, ensure_ascii=False))
        md.append("```")
        md.append("")

(out_dir / "05_smoke8_comparison.md").write_text("\n".join(md), encoding="utf-8")

print("COMPARISON_WRITTEN =", (out_dir / "05_smoke8_comparison.json").as_posix())
PY

RC_COMPARE=$?
echo "RC_COMPARE=$RC_COMPARE"

echo
echo "===== package outputs ====="
STAGE="$RUNROOT/return_package"
mkdir -p "$STAGE"

cp -a "$DIAG" "$STAGE/diagnostics"

mkdir -p "$STAGE/lane_input"
cp -a "$TARGET_LANES" "$STAGE/lane_input/target_smoke8_lane_packets.jsonl"
cp -a "$FULL_LANES" "$STAGE/lane_input/full_v3_3_lane_packets.jsonl" || true
cp -a "$REPLAY_DIR/summary.json" "$STAGE/lane_input/v3_3_replay_summary.json" || true

mkdir -p "$STAGE/nothink"
cp -a "$NOTHINK_DRAFT_DIR" "$STAGE/nothink/drafts" || true
cp -a "$NOTHINK_VALID_DIR" "$STAGE/nothink/validated" || true

mkdir -p "$STAGE/think"
cp -a "$THINK_DRAFT_DIR" "$STAGE/think/drafts" || true
cp -a "$THINK_VALID_DIR" "$STAGE/think/validated" || true

{
  echo "created_utc=$STAMP"
  echo "job_id=${SLURM_JOB_ID:-NA}"
  echo "host=$(hostname)"
  echo "model=$MODEL"
  echo "ollama_host=$OLLAMA_HOST"
  echo "replay_dir=$REPLAY_DIR"
  echo "target_lanes=$TARGET_LANES"
  echo "nothink_draft_dir=$NOTHINK_DRAFT_DIR"
  echo "nothink_valid_dir=$NOTHINK_VALID_DIR"
  echo "think_draft_dir=$THINK_DRAFT_DIR"
  echo "think_valid_dir=$THINK_VALID_DIR"
  echo "RC_COMPILE=$RC_COMPILE"
  echo "RC_SUBSET=$RC_SUBSET"
  echo "RC_SANITY_NOTHINK=$RC_SANITY_NOTHINK"
  echo "RC_SANITY_THINK=$RC_SANITY_THINK"
  echo "B_NOTHINK_RC=$B_NOTHINK_RC"
  echo "C_NOTHINK_RC=$C_NOTHINK_RC"
  echo "B_THINK_RC=$B_THINK_RC"
  echo "C_THINK_RC=$C_THINK_RC"
  echo "RC_COMPARE=$RC_COMPARE"
  echo "active_pointer_policy=do_not_update_current_alias_or_active_pointer"
} > "$STAGE/README_SMOKE8.txt"

find "$STAGE" -type f | sort > "$STAGE/FILES.txt"

if command -v sha256sum >/dev/null 2>&1; then
  (
    cd "$STAGE" || exit 1
    find . -type f ! -name MANIFEST_SHA256.txt -print0 | sort -z | xargs -0 sha256sum > MANIFEST_SHA256.txt
  )
fi

tar -czf "$RETURN" -C "$STAGE" .

ls -lh "$RETURN"
echo "RETURN=$RETURN"

echo
echo "===== final rc summary ====="
cat "$STAGE/README_SMOKE8.txt"

echo
echo "STEP67_V3_3_GEMMA_SMOKE8_DONE"
