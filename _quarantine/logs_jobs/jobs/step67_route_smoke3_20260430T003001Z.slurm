#!/bin/bash
#SBATCH --job-name=step67_smoke3
#SBATCH --partition=gpu80GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=logs/step67_smoke3_%j.out
#SBATCH --error=logs/step67_smoke3_%j.err

set +e

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || {
  echo "ERROR: repo cd failed"
  exit 1
}

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export OLLAMA_MODELS="/beegfs2/scratch/aryp26yc/kc_l/ollama/models"
export OLLAMA_HOST="127.0.0.1:$((25000 + RANDOM % 20000))"
export OLLAMA_FLASH_ATTENTION=1

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DIAG_DIR="data/work/cache/diagnostics/step67_route_smoke3_runtime_${STAMP}"
mkdir -p "$DIAG_DIR"

SMOKE_CONFIG="steps/step_06_7_kc_draft_generation/resources/step6_7.sofja.actual_corpus.step66_001631_route_smoke3.yaml"
RUNNER="steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py"

echo "HOST=$(hostname)"
echo "PWD=$PWD"
echo "DIAG_DIR=$DIAG_DIR"
echo "SMOKE_CONFIG=$SMOKE_CONFIG"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "PY=$PY"
"$PY" --version

echo
echo "===== COMPILE CHECK ====="
"$PY" -m py_compile "$RUNNER" $(find src/kc_l -type f \( -name '*draft*.py' -o -name '*step67*.py' -o -name '*6_7*.py' \) ! -name '*.bak*' 2>/dev/null | sort) \
  > "$DIAG_DIR/py_compile_stdout.txt" 2> "$DIAG_DIR/py_compile_stderr.txt"
RC_COMPILE=$?
cat "$DIAG_DIR/py_compile_stdout.txt"
cat "$DIAG_DIR/py_compile_stderr.txt"
echo "RC_COMPILE=$RC_COMPILE"

echo
echo "===== SMOKE CONFIG CHECK ====="
"$PY" - "$SMOKE_CONFIG" <<'PY' 2>&1 | tee "$DIAG_DIR/config_check.txt"
import json
import sys
from pathlib import Path
import yaml

p = Path(sys.argv[1])
obj = yaml.safe_load(p.read_text(encoding="utf-8"))
inputs = obj.get("inputs") or {}
slice_cfg = obj.get("slice") or {}

print(json.dumps({
    "config": str(p),
    "step6_6_set_manifest": inputs.get("step6_6_set_manifest"),
    "limit_kcs": slice_cfg.get("limit_kcs"),
    "exact_kc_ids": slice_cfg.get("exact_kc_ids"),
    "exact_kc_count": len(slice_cfg.get("exact_kc_ids") or []),
    "bridge_notes": obj.get("bridge_notes"),
}, indent=2, ensure_ascii=False))

if len(slice_cfg.get("exact_kc_ids") or []) != 3:
    raise SystemExit("ERROR: smoke config must contain exactly 3 exact_kc_ids")
PY
RC_CONFIG_CHECK=${PIPESTATUS[0]}
echo "RC_CONFIG_CHECK=$RC_CONFIG_CHECK"

echo
echo "===== START OLLAMA SERVER IF AVAILABLE ====="
if command -v ollama >/dev/null 2>&1; then
  nohup ollama serve > "$DIAG_DIR/ollama_server.log" 2>&1 &
  OLLAMA_PID=$!
  echo "OLLAMA_PID=$OLLAMA_PID"
  sleep 15
  ollama list > "$DIAG_DIR/ollama_list.txt" 2>&1 || true
  cat "$DIAG_DIR/ollama_list.txt"
else
  echo "WARNING: ollama command not found in PATH. Runner may still use a different backend if configured."
  OLLAMA_PID=""
fi

echo
echo "===== RUN STEP6.7 ROUTE-AWARE SMOKE3 ====="
"$PY" "$RUNNER" --config "$SMOKE_CONFIG" \
  > "$DIAG_DIR/step67_run_stdout.txt" \
  2> "$DIAG_DIR/step67_run_stderr.txt"
RC_STEP67=$?

echo "RC_STEP67=$RC_STEP67"
echo
echo "===== STEP6.7 STDOUT ====="
cat "$DIAG_DIR/step67_run_stdout.txt"
echo
echo "===== STEP6.7 STDERR ====="
cat "$DIAG_DIR/step67_run_stderr.txt"

echo
echo "===== POSTRUN ARTIFACT VALIDATION ====="
"$PY" - "$DIAG_DIR" "$SMOKE_CONFIG" <<'PY' 2>&1 | tee "$DIAG_DIR/postrun_validation_stdout.txt"
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

diag_dir = Path(sys.argv[1])
smoke_config = Path(sys.argv[2])

stdout_path = diag_dir / "step67_run_stdout.txt"
stderr_path = diag_dir / "step67_run_stderr.txt"

stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""

def load_json_from_stdout(text):
    candidates = re.findall(r"\{[\s\S]*?\}", text)
    parsed = []
    for cand in candidates:
        try:
            parsed.append(json.loads(cand))
        except Exception:
            pass
    return parsed

parsed_stdout_json = load_json_from_stdout(stdout)

run_info = {}
for obj in parsed_stdout_json:
    if isinstance(obj, dict) and ("processed_dir" in obj or "audit_dir" in obj or "run_id" in obj):
        run_info = obj

run_id = str(run_info.get("run_id") or "")
processed_dir = Path(str(run_info.get("processed_dir") or "")) if run_info.get("processed_dir") else None
audit_dir = Path(str(run_info.get("audit_dir") or "")) if run_info.get("audit_dir") else None

jsonl_reports = []
draft_like_files = []

search_roots = []
if processed_dir:
    search_roots.append(processed_dir)
if audit_dir:
    search_roots.append(audit_dir)

for root in search_roots:
    if not root.exists():
        continue
    for path in sorted(root.rglob("*.jsonl")):
        rows = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rows.append(json.loads(line))
        except Exception as exc:
            jsonl_reports.append({
                "path": str(path),
                "read_error": str(exc),
            })
            continue

        keys = set()
        for row in rows[:5]:
            if isinstance(row, dict):
                keys.update(row.keys())

        unique_kcs = sorted({
            str(row.get("kc_id") or "")
            for row in rows
            if isinstance(row, dict) and row.get("kc_id")
        })

        draft_status_counts = Counter(
            str(row.get("draft_status") or "")
            for row in rows
            if isinstance(row, dict) and "draft_status" in row
        )

        route_counts = Counter(
            str(((row.get("evidence_pack_quality") or {}).get("route")) or "")
            for row in rows
            if isinstance(row, dict) and "evidence_pack_quality" in row
        )

        looks_draft_like = bool(
            "kc_id" in keys and (
                "draft_status" in keys
                or "definition" in keys
                or "machine_draft" in keys
                or "draft" in keys
            )
        )

        report = {
            "path": str(path),
            "row_count": len(rows),
            "keys_sample": sorted(keys),
            "unique_kc_count": len(unique_kcs),
            "unique_kcs": unique_kcs,
            "draft_status_counts": dict(draft_status_counts),
            "route_counts": dict(route_counts),
            "looks_draft_like": looks_draft_like,
        }

        jsonl_reports.append(report)

        if looks_draft_like:
            draft_like_files.append(report)

set_manifest_candidates = []
for root in [
    Path("data/processed/kc_drafts/_sets"),
    Path("data/processed/kc_draft_generation/_sets"),
    Path("data/processed/kc_drafting/_sets"),
]:
    if root.exists():
        if run_id:
            set_manifest_candidates.extend(sorted(root.glob(f"*{run_id}*.json")))
        set_manifest_candidates.extend(sorted(root.glob("*step6_7*.json"))[-10:])

checks = {
    "runner_stdout_present": bool(stdout.strip()),
    "runner_no_traceback": "Traceback" not in stdout and "Traceback" not in stderr,
    "run_id_detected": bool(run_id),
    "processed_dir_detected": processed_dir is not None,
    "processed_dir_exists": bool(processed_dir and processed_dir.exists()),
    "audit_dir_exists_if_reported": bool((audit_dir is None) or audit_dir.exists()),
    "found_jsonl_outputs": bool(jsonl_reports),
    "found_draft_like_jsonl": bool(draft_like_files),
}

summary = {
    "smoke_config": str(smoke_config),
    "run_info": run_info,
    "run_id": run_id,
    "processed_dir": str(processed_dir) if processed_dir else "",
    "audit_dir": str(audit_dir) if audit_dir else "",
    "set_manifest_candidates": [str(p) for p in set_manifest_candidates],
    "jsonl_reports": jsonl_reports,
    "draft_like_files": draft_like_files,
    "checks": checks,
    "stdout_tail": stdout[-5000:],
    "stderr_tail": stderr[-5000:],
    "all_postrun_checks_passed": all(checks.values()),
}

summary_path = diag_dir / "step67_route_smoke3_postrun_summary.json"
md_path = diag_dir / "step67_route_smoke3_postrun.md"

summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

lines = []
lines.append("# Step6.7 route-aware smoke3 postrun validation\n")
lines.append("## Checks\n")
lines.append("```json\n" + json.dumps(checks, indent=2, ensure_ascii=False) + "\n```")
lines.append("")
lines.append("## Run info\n")
lines.append("```json\n" + json.dumps(run_info, indent=2, ensure_ascii=False) + "\n```")
lines.append("")
lines.append("## Draft-like files\n")
lines.append("```json\n" + json.dumps(draft_like_files, indent=2, ensure_ascii=False) + "\n```")
lines.append("")
lines.append("## JSONL reports\n")
lines.append("```json\n" + json.dumps(jsonl_reports, indent=2, ensure_ascii=False) + "\n```")
md_path.write_text("\n".join(lines), encoding="utf-8")

print("POSTRUN_CHECKS =", json.dumps(checks, sort_keys=True))
print("POSTRUN_ALL_CHECKS_PASSED =", summary["all_postrun_checks_passed"])
print("RUN_INFO =", json.dumps(run_info, sort_keys=True))
print("DRAFT_LIKE_FILE_COUNT =", len(draft_like_files))
print("STEP67_ROUTE_SMOKE3_POSTRUN_VALIDATION_OK")
print("SUMMARY_PATH =", summary_path)
print("MD_PATH =", md_path)
PY
RC_POST=${PIPESTATUS[0]}

echo "RC_POST=$RC_POST"

if [ -n "${OLLAMA_PID:-}" ]; then
  echo
  echo "===== STOP OLLAMA SERVER ====="
  kill "$OLLAMA_PID" >/dev/null 2>&1 || true
fi

echo
echo "===== RESULT ====="
echo "DIAG_DIR=$DIAG_DIR"
echo "SMOKE_CONFIG=$SMOKE_CONFIG"
echo "RUN_STDOUT=$DIAG_DIR/step67_run_stdout.txt"
echo "RUN_STDERR=$DIAG_DIR/step67_run_stderr.txt"
echo "POST_SUMMARY=$DIAG_DIR/step67_route_smoke3_postrun_summary.json"
echo "POST_MD=$DIAG_DIR/step67_route_smoke3_postrun.md"
echo "RC_COMPILE=$RC_COMPILE"
echo "RC_CONFIG_CHECK=$RC_CONFIG_CHECK"
echo "RC_STEP67=$RC_STEP67"
echo "RC_POST=$RC_POST"

if [ "$RC_COMPILE" -eq 0 ] && [ "$RC_CONFIG_CHECK" -eq 0 ] && [ "$RC_STEP67" -eq 0 ] && [ "$RC_POST" -eq 0 ]; then
  echo "STEP67_ROUTE_SMOKE3_RUN_DONE"
else
  echo "STEP67_ROUTE_SMOKE3_RUN_FAILED"
fi
