#!/usr/bin/env bash
#SBATCH --job-name=s67g4s10v3
#SBATCH --partition=gpu46GB
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:30:00
#SBATCH --output=logs/s67g4s10v3-%j.out
#SBATCH --error=logs/s67g4s10v3-%j.err

set -u

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST=127.0.0.1:$((26000 + SLURM_JOB_ID % 10000))
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"
export GEMMA_MODEL="gemma4:31b"

STEP66_SET="data/processed/kc_drafting_input_overlay/_sets/2026-04-28_002730_step6_6_kc_drafting_input_overlay_set.json"

echo "==== job context ===="
date -u
hostname
echo "PWD=$PWD"
echo "PY=$PY"
"$PY" --version
echo "OLLAMA_BIN=$OLLAMA_BIN"
echo "OLLAMA_MODELS=$OLLAMA_MODELS"
echo "OLLAMA_HOST=$OLLAMA_HOST"
echo "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
echo "GEMMA_MODEL=$GEMMA_MODEL"

echo
echo "==== guards ===="
test -x "$OLLAMA_BIN" || { echo "FAIL missing executable OLLAMA_BIN=$OLLAMA_BIN"; exit 1; }
test -f "$STEP66_SET" || { echo "FAIL missing STEP66_SET=$STEP66_SET"; exit 1; }
test -f src/kc_l/kc_drafting/model_profile.py || exit 1
test -f src/kc_l/utils/ollama_json.py || exit 1
test -f src/kc_l/utils/kc_step67_model_drafting.py || exit 1
test -f steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py || exit 1

echo
echo "==== start Ollama server ===="
"$OLLAMA_BIN" serve > "logs/ollama-s67g4s10v3-${SLURM_JOB_ID}.out" 2> "logs/ollama-s67g4s10v3-${SLURM_JOB_ID}.err" &
OLLAMA_PID=$!
echo "OLLAMA_PID=$OLLAMA_PID"

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo
echo "==== wait for Ollama API ===="
for i in $(seq 1 90); do
  if curl -fsS "${OLLAMA_BASE_URL}/api/version" >/dev/null 2>&1; then
    echo "OLLAMA_READY_AFTER=${i}s"
    curl -fsS "${OLLAMA_BASE_URL}/api/version" || true
    break
  fi
  sleep 1
  if [ "$i" -eq 90 ]; then
    echo "FAIL Ollama API not ready"
    exit 1
  fi
done

echo
echo "==== model availability guard ===="
"$OLLAMA_BIN" list
if ! "$OLLAMA_BIN" list | awk '{print $1}' | grep -Fxq "$GEMMA_MODEL"; then
  echo "FAIL Gemma model not installed: $GEMMA_MODEL"
  exit 1
fi
echo "RESOLVED_GEMMA_MODEL=$GEMMA_MODEL"

echo
echo "==== py_compile active files ===="
"$PY" -m py_compile \
  src/kc_l/kc_drafting/model_profile.py \
  src/kc_l/utils/ollama_json.py \
  src/kc_l/utils/kc_step67_model_drafting.py \
  steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py

STAMP="$(date -u +%Y%m%d_%H%M%S)"
CONFIG="data/work/cache/generated_configs/step6_7.gemma4_31b.stage3_v3_smoke10_v3_clean_${STAMP}.yaml"
mkdir -p "$(dirname "$CONFIG")"

cat > "$CONFIG" <<EOF
project:
  timezone: Europe/Berlin
  run_purpose: step6_7_gemma4_31b_model_backed_smoke10_v3_clean

inputs:
  step6_6_set_manifest: "$STEP66_SET"

outputs:
  processed_root: data/processed/kc_drafts
  sets_root: data/processed/kc_drafts/_sets
  runs_root: data/runs

slice:
  limit_kcs: 10
  exact_kc_ids:
    - KC_CLU_EVAL_001
    - KC_CLU_EVAL_002
    - KC_DE_PREP_003
    - KC_EVAL_SAMP_003
    - KC_CLU_DBS_003
    - KC_CLU_CORE_002
    - KC_CLU_DBS_001
    - KC_CLF_NB_011
    - KC_CLU_EVAL_012
    - KC_EVAL_BASIC_005

selection:
  max_bundle_size: 6
  max_explanatory_candidates: 5

execution:
  execution_mode: llm
  llm_required: true
  fail_closed_when_llm_unavailable: true
  provider: ollama
  generation_model_alias: "$GEMMA_MODEL"
  generation_base_url: "$OLLAMA_BASE_URL"
  generation_base_url_field: generated_config.models.generation.base_url
  domain_policy_name: none
  domain_policy_field: generated_config.step6_7.drafting_policy.domain_policy

models:
  generation:
    provider: ollama
    resolved_model_alias: "$GEMMA_MODEL"
    generation_model: "$GEMMA_MODEL"
    base_url: "$OLLAMA_BASE_URL"
    temperature: 0.0
    top_p: 1.0
    repeat_penalty: 1.0
    num_ctx: 8192
    think: true
    thinking_enabled: true
    thinking_activation_mode: request_flag
    response_parse_mode: message_content_only
    strip_thought_block_before_parse: false
    system_prefix: |
      You are drafting machine-generated knowledge-component records for expert review.

      Rules:
      1. Use only the supplied evidence.
      2. Write a concise paraphrase when the evidence clearly supports the target KC.
      3. Do not copy a full evidence sentence unless it is a formula, notation, or fixed technical phrase.
      4. Do not infer a definition from sibling evidence unless the evidence explicitly explains the target KC.
      5. Abstain when support is only background, example, procedure, fragment, or sibling contrast.
      6. Return only the required JSON object in the visible response.
      7. Keep kc_specific_criteria empty.

model_profile:
  backend_kind: ollama
  transport_mode: ollama_chat
  response_parse_mode: message_content_only
  generation_model: "$GEMMA_MODEL"
  resolved_model_alias: "$GEMMA_MODEL"
  generation_base_url: "$OLLAMA_BASE_URL"
  temperature: 0.0
  top_p: 1.0
  repeat_penalty: 1.0
  num_ctx: 8192
  thinking_enabled: true
  thinking_activation_mode: request_flag
  strip_thought_block_before_parse: false
  system_prefix: |
    You are drafting machine-generated knowledge-component records for expert review.

    Rules:
    1. Use only the supplied evidence.
    2. Write a concise paraphrase when the evidence clearly supports the target KC.
    3. Do not copy a full evidence sentence unless it is a formula, notation, or fixed technical phrase.
    4. Do not infer a definition from sibling evidence unless the evidence explicitly explains the target KC.
    5. Abstain when support is only background, example, procedure, fragment, or sibling contrast.
    6. Return only the required JSON object in the visible response.
    7. Keep kc_specific_criteria empty.

step6_7:
  contract_version: step6_7_gemma4_31b_model_backed_smoke10_v3_clean
  execution_mode: llm
  llm_required: true
  fail_closed_when_llm_unavailable: true
  active_runner: steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py
  inputs:
    step6_6_set_manifest: "$STEP66_SET"
  outputs:
    processed_root: data/processed/kc_drafts
    sets_root: data/processed/kc_drafts/_sets
    runs_root: data/runs
  drafting_policy:
    domain_policy: none
EOF

echo
echo "==== generated config ===="
echo "GENERATED_CONFIG=$CONFIG"
sed -n '1,220p' "$CONFIG"

echo
echo "==== run Step 6.7 Gemma4 smoke10 v3 clean ===="
RUN_JSON="$("$PY" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py --config "$CONFIG")"
echo "$RUN_JSON"

RUN_ID="$(printf '%s\n' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"
STEP67_SET="data/processed/kc_drafts/_sets/${RUN_ID}_step6_7_kc_drafts_set.json"
echo "RUN_ID=$RUN_ID"
echo "STEP67_SET=$STEP67_SET"

echo
echo "==== final-field-only audit ===="
AUDIT_DIR="data/work/cache/diagnostics/step67_gemma4_smoke10_v3_clean_${RUN_ID}"
mkdir -p "$AUDIT_DIR"

STEP67_SET="$STEP67_SET" AUDIT_DIR="$AUDIT_DIR" "$PY" - <<'PY'
import json
import os
import re
from collections import Counter
from pathlib import Path

root = Path(".")
step67_set = Path(os.environ["STEP67_SET"])
audit_dir = Path(os.environ["AUDIT_DIR"])
audit_dir.mkdir(parents=True, exist_ok=True)

def norm(x):
    return re.sub(r"\s+", " ", str(x or "").lower()).strip()

def resolve(v):
    if not isinstance(v, str) or not v.strip():
        return None
    p = Path(v)
    return p if p.is_absolute() else root / p

set_obj = json.loads(step67_set.read_text(encoding="utf-8"))
artifacts = set_obj.get("artifacts") or {}
drafts_path = None
for key in ("kc_draft_bundles_jsonl", "draft_bundles_jsonl", "kc_drafts_jsonl", "drafts_jsonl"):
    p = resolve(artifacts.get(key))
    if p and p.exists():
        drafts_path = p
        break
if drafts_path is None:
    raise SystemExit(f"FAIL could not resolve draft JSONL from artifacts={artifacts}")

rows = [json.loads(line) for line in drafts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
kc_ids = [str(r.get("kc_id") or "") for r in rows]

final_fields = ["definition_full_candidate", "definition_short_candidate", "scope_candidate"]

strict_bad_markers = {
    "KC_CLF_NB_011": ["decision tree classifier", "knn instances", "mar missing data mechanism", "patients have missing values"],
    "KC_CLU_DBS_001": ["a border point is a point that is not a core point", "a border point is not a core point"],
    "KC_CLU_DBS_003": ["random component of a measurement error", "notice that some of the noise points are"],
    "KC_EVAL_SAMP_003": ["best choice of the hyper-parameter value", "common mistakes while using cross-validation"],
    "KC_CLU_EVAL_001": ["covariance"],
}

final_bad_hits = {}
exact_copy_hits = {}
selection_reason_counts = Counter()
field_status_counts = Counter()
persisted_thinking_chars = 0

def iter_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)
    elif isinstance(obj, str):
        yield obj

for row in rows:
    kc_id = str(row.get("kc_id") or "")
    evidence_strings = []
    for obj in (row.get("evidence_bundle"), row.get("selection_diagnostics")):
        for s in iter_strings(obj):
            if len(norm(s)) >= 50:
                evidence_strings.append(s)

    for obj in (row.get("selection_diagnostics"),):
        # Count thinking for diagnostics only. Do not inspect it for final quality.
        text_blob = json.dumps(obj, ensure_ascii=False)
        persisted_thinking_chars += text_blob.count('"thinking"')

    for field in final_fields:
        value = row.get(field) or {}
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "")
        text = str(value.get("text") or "")
        reason = str(value.get("selection_reason") or "")
        selection_reason_counts[reason] += 1
        field_status_counts[f"{field}:{status}"] += 1

        low = norm(text)
        for marker in strict_bad_markers.get(kc_id, []):
            if norm(marker) and norm(marker) in low:
                final_bad_hits.setdefault(kc_id, []).append({
                    "field": field,
                    "marker": marker,
                    "text": text,
                    "selection_reason": reason,
                })

        if len(low) >= 50:
            for ev in evidence_strings:
                if low in norm(ev):
                    exact_copy_hits.setdefault(kc_id, []).append({
                        "field": field,
                        "text": text,
                        "selection_reason": reason,
                    })
                    break

assessment = {
    "scope": "step67_gemma4_smoke10_v3_clean_final_field_only",
    "step67_set": step67_set.as_posix(),
    "drafts_path": drafts_path.as_posix(),
    "row_count": len(rows),
    "unique_kc_count": len(set(kc_ids)),
    "duplicate_kc_ids": sorted(k for k, n in Counter(kc_ids).items() if n > 1),
    "draft_status_breakdown": dict(Counter(str(r.get("draft_status") or "") for r in rows)),
    "authoritative_definition_status_breakdown": dict(Counter(str(r.get("authoritative_definition_status") or "") for r in rows)),
    "field_status_counts": dict(field_status_counts),
    "selection_reason_counts": dict(selection_reason_counts),
    "final_bad_hits": final_bad_hits,
    "exact_copy_hits": exact_copy_hits,
    "exact_copy_kc_count": len(exact_copy_hits),
}

out_json = audit_dir / "final_field_only_audit.json"
out_json.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("FINAL_FIELD_ONLY_AUDIT_JSON=", out_json.as_posix())
print("row_count=", assessment["row_count"])
print("unique_kc_count=", assessment["unique_kc_count"])
print("draft_status_breakdown=", json.dumps(assessment["draft_status_breakdown"], indent=2))
print("authoritative_definition_status_breakdown=", json.dumps(assessment["authoritative_definition_status_breakdown"], indent=2))
print("field_status_counts=", json.dumps(assessment["field_status_counts"], indent=2))
print("selection_reason_counts=", json.dumps(assessment["selection_reason_counts"], indent=2))
print("final_bad_hits_count=", len(final_bad_hits))
print("exact_copy_kc_count=", len(exact_copy_hits))
print("final_bad_hits=", json.dumps(final_bad_hits, indent=2, ensure_ascii=False))
print("exact_copy_hits=", json.dumps(exact_copy_hits, indent=2, ensure_ascii=False))

if len(rows) != 10:
    raise SystemExit(f"FAIL expected 10 rows, got {len(rows)}")
if len(set(kc_ids)) != 10:
    raise SystemExit(f"FAIL expected 10 unique KCs, got {len(set(kc_ids))}")
if final_bad_hits:
    raise SystemExit("FAIL final fields contain known bad markers")

print("STEP67_GEMMA4_SMOKE10_V3_CLEAN_FINAL_FIELD_AUDIT_OK")
PY

echo
echo "STEP67_GEMMA4_SMOKE10_V3_CLEAN_PIPELINE_DONE"
