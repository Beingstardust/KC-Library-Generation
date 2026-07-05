#!/bin/bash
#SBATCH --job-name=g4probe
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:20:00
#SBATCH --output=logs/g4probe-%j.out
#SBATCH --error=logs/g4probe-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST="127.0.0.1:$((23000 + SLURM_JOB_ID % 20000))"
export OLLAMA_LOGS="logs/g4probe-ollama-${SLURM_JOB_ID}.log"

echo "==== job context ===="
date -u
hostname
echo "PWD=$PWD"
echo "PY=$PY"
"$PY" --version
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"

test -x "$OLLAMA_BIN" || { echo "FAIL: OLLAMA_BIN is not executable"; exit 1; }
test -d "$OLLAMA_MODELS" || { echo "FAIL: OLLAMA_MODELS directory missing"; exit 1; }

echo
echo "==== offline manifest scan ===="
find "$OLLAMA_MODELS/manifests" -type f 2>/dev/null | sed "s#^$OLLAMA_MODELS/manifests/##" | sort | sed -n '1,220p' || true

echo
echo "==== start ollama server ===="
"$OLLAMA_BIN" serve > "$OLLAMA_LOGS" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "OLLAMA_PID=$OLLAMA_PID"

echo
echo "==== wait for ollama API ===="
for i in $(seq 1 60); do
  if curl -fsS "http://${OLLAMA_HOST}/api/version" >/tmp/g4probe_version_${SLURM_JOB_ID}.json 2>/dev/null; then
    echo "OLLAMA_READY_AFTER=${i}s"
    cat /tmp/g4probe_version_${SLURM_JOB_ID}.json
    echo
    break
  fi
  sleep 1
done

if ! curl -fsS "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
  echo "FAIL: Ollama API did not become ready"
  echo "===== ollama log tail ====="
  tail -n 160 "$OLLAMA_LOGS" || true
  exit 1
fi

echo
echo "==== ollama list ===="
"$OLLAMA_BIN" list | tee "data/work/cache/diagnostics/gemma4_31b_ollama_list_${SLURM_JOB_ID}.txt"

echo
echo "==== select Gemma4 31B model tag ===="
MODEL="$(
  "$OLLAMA_BIN" list |
  awk 'NR>1 {print $1}' |
  grep -Ei '(^|/)gemma4:31b$|(^|/)gemma4:31b-|(^|/)gemma4.*31b' |
  head -n 1
)"

if [ -z "${MODEL:-}" ]; then
  echo "No exact Gemma4 31B match found using strict pattern. Showing all gemma-like tags:"
  "$OLLAMA_BIN" list | awk 'NR==1 || tolower($0) ~ /gemma/ {print}'
  echo "FAIL: could not resolve Gemma4 31B model tag"
  exit 1
fi

echo "RESOLVED_GEMMA_MODEL=$MODEL"

echo
echo "==== ollama show selected model ===="
"$OLLAMA_BIN" show "$MODEL" | sed -n '1,180p' || true

echo
echo "==== test /api/chat with think=true, suppress reasoning content ===="
MODEL="$MODEL" "$PY" - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

host = os.environ["OLLAMA_HOST"]
model = os.environ["MODEL"]

payload = {
    "model": model,
    "messages": [
        {
            "role": "system",
            "content": (
                "You are a strict JSON generator. Return only JSON. "
                "Do not include chain-of-thought text in the answer."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return this exact JSON object and nothing else: "
                "{\"ok\": true, \"model_runtime_probe\": \"gemma4_31b\"}"
            ),
        },
    ],
    "stream": False,
    "think": True,
    "options": {
        "temperature": 0,
        "top_p": 1,
        "num_ctx": 4096,
        "repeat_penalty": 1.0,
    },
}

req = urllib.request.Request(
    f"http://{host}/api/chat",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=180) as resp:
    outer = json.loads(resp.read().decode("utf-8"))

msg = outer.get("message") or {}
content = msg.get("content") or ""
thinking = msg.get("thinking") or outer.get("thinking") or ""

probe = {
    "model": model,
    "outer_keys": sorted(outer.keys()),
    "message_keys": sorted(msg.keys()) if isinstance(msg, dict) else [],
    "content_preview": content[:220],
    "content_len": len(content),
    "thinking_field_present": bool(thinking),
    "thinking_len_suppressed": len(thinking) if isinstance(thinking, str) else 0,
    "done": outer.get("done"),
    "done_reason": outer.get("done_reason"),
}

out = Path("data/work/cache/diagnostics") / f"gemma4_31b_think_true_runtime_probe_{os.environ.get('SLURM_JOB_ID', 'manual')}.json"
out.write_text(json.dumps(probe, indent=2, ensure_ascii=False), encoding="utf-8")

print("GEMMA4_RUNTIME_PROBE_JSON =", out.as_posix())
print(json.dumps(probe, indent=2, ensure_ascii=False))

if not content.strip():
    raise SystemExit("FAIL: Gemma probe returned empty content")
PY

echo
echo "==== inspect Step 6.7 LLM config/backend fields, no run ===="
grep -R -nE 'execution_mode|llm_required|fail_closed|resolved_model_alias|generation_model_alias|base_url|think|thinking|ollama|api/chat|temperature|num_ctx|messages|system|few_shot|few-shot|domain_policy|definition_generation_mode' \
  src/kc_l/kc_drafting steps/step_06_7_kc_draft_generation \
  2>/dev/null | sed -n '1,260p'

echo
echo "==== accepted Step 6.6 input guard ===="
STEP66_SET="data/processed/kc_drafting_input_overlay/_sets/2026-04-28_002730_step6_6_kc_drafting_input_overlay_set.json"
test -f "$STEP66_SET" && echo "OK $STEP66_SET" || { echo "MISSING $STEP66_SET"; exit 1; }

echo
echo "PRE_STEP6_7_GEMMA4_31B_RUNTIME_PROBE_OK"
