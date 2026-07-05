#!/bin/bash
#SBATCH --job-name=s67g4s10
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=6
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --output=logs/s67g4s10-%j.out
#SBATCH --error=logs/s67g4s10-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

export OLLAMA_BIN=/beegfs1/home/aryp26yc/apps/ollama_upgrade_clean_20260425_214752/bin/ollama
export OLLAMA_MODELS=/beegfs2/scratch/aryp26yc/kc_l/ollama/models
export OLLAMA_HOST="127.0.0.1:$((24000 + SLURM_JOB_ID % 20000))"
export OLLAMA_BASE_URL="http://${OLLAMA_HOST}"
export GEMMA_MODEL="gemma4:31b"
export OLLAMA_LOGS="logs/s67g4s10-ollama-${SLURM_JOB_ID}.log"

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
test -x "$OLLAMA_BIN" || { echo "FAIL: OLLAMA_BIN not executable"; exit 1; }
test -d "$OLLAMA_MODELS" || { echo "FAIL: OLLAMA_MODELS missing"; exit 1; }
test -f "$STEP66_SET" || { echo "FAIL: missing accepted Step 6.6 set: $STEP66_SET"; exit 1; }

for rel in \
  "src/kc_l/kc_drafting/model_profile.py" \
  "src/kc_l/kc_drafting/config.py" \
  "src/kc_l/kc_drafting/orchestration.py" \
  "src/kc_l/kc_drafting/backend.py" \
  "src/kc_l/kc_drafting/heuristic_core.py" \
  "src/kc_l/kc_drafting/provenance.py" \
  "src/kc_l/kc_drafting/packetization.py" \
  "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py"
do
  test -f "$rel" && echo "OK $rel" || { echo "MISSING $rel"; exit 1; }
done

echo
echo "==== protect current aliases before run ===="
ALIAS_HASH_FILE="data/work/cache/diagnostics/step6_7_gemma4_smoke10_alias_hashes_before_${SLURM_JOB_ID}.txt"
: > "$ALIAS_HASH_FILE"

for rel in \
  "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json" \
  "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json" \
  "data/work/cache/current_step_artifacts/step6_75_set_manifest.current.json" \
  "data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json"
do
  if [ -f "$rel" ]; then
    sha256sum "$rel" | tee -a "$ALIAS_HASH_FILE"
  else
    echo "MISSING $rel" | tee -a "$ALIAS_HASH_FILE"
  fi
done

echo
echo "==== start Ollama server ===="
"$OLLAMA_BIN" serve > "$OLLAMA_LOGS" 2>&1 &
OLLAMA_PID=$!

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "OLLAMA_PID=$OLLAMA_PID"

echo
echo "==== wait for Ollama API ===="
for i in $(seq 1 90); do
  if curl -fsS "${OLLAMA_BASE_URL}/api/version" >/tmp/s67g4s10_version_${SLURM_JOB_ID}.json 2>/dev/null; then
    echo "OLLAMA_READY_AFTER=${i}s"
    cat /tmp/s67g4s10_version_${SLURM_JOB_ID}.json
    echo
    break
  fi
  sleep 1
done

if ! curl -fsS "${OLLAMA_BASE_URL}/api/version" >/dev/null 2>&1; then
  echo "FAIL: Ollama API did not become ready"
  tail -n 200 "$OLLAMA_LOGS" || true
  exit 1
fi

echo
echo "==== model availability guard ===="
"$OLLAMA_BIN" list | tee "data/work/cache/diagnostics/step6_7_gemma4_smoke10_ollama_list_${SLURM_JOB_ID}.txt"

if ! "$OLLAMA_BIN" list | awk 'NR>1 {print $1}' | grep -Fx "$GEMMA_MODEL" >/dev/null; then
  echo "FAIL: required model not listed: $GEMMA_MODEL"
  "$OLLAMA_BIN" list | awk 'NR==1 || tolower($0) ~ /gemma/ {print}'
  exit 1
fi

echo "RESOLVED_GEMMA_MODEL=$GEMMA_MODEL"

echo
echo "==== patch Step 6.7 model_profile to honor generic system_prefix ===="
"$PY" - <<'PY'
from pathlib import Path

path = Path("src/kc_l/kc_drafting/model_profile.py")
text = path.read_text(encoding="utf-8")

marker = "PATCH_STEP67_GENERIC_SYSTEM_PREFIX_GEMMA4_20260428"

if marker not in text:
    backup = Path("_backups") / f"{path.name}.bak_{marker}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(text, encoding="utf-8")

    append = r'''
# PATCH_STEP67_GENERIC_SYSTEM_PREFIX_GEMMA4_20260428
# Domain-agnostic Step 6.7 prompt injection support.
# This intentionally does not add course-specific examples.
def _step67_prepend_system_message_for_profile(prepared, prefix):
    prefix = as_text(prefix).strip()
    if not prefix:
        return prepared

    out = [dict(message) for message in prepared]
    for message in out:
        if as_text(message.get("role")).lower() == "system":
            current = as_text(message.get("content")).strip()
            if prefix and prefix not in current:
                message["content"] = f"{prefix}\n\n{current}" if current else prefix
            return out

    return [{"role": "system", "content": prefix}, *out]


def apply_step67_model_profile_to_messages(messages, profile):
    prepared = [dict(message) for message in messages]

    prepared = _step67_prepend_system_message_for_profile(
        prepared,
        profile.get("system_prefix"),
    )

    if (
        as_bool(profile.get("thinking_enabled"))
        and as_text(profile.get("thinking_activation_mode")).lower() == "system_prefix"
    ):
        prepared = _step67_prepend_system_message_for_profile(
            prepared,
            profile.get("thinking_system_prefix"),
        )

    return prepared
'''
    path.write_text(text.rstrip() + "\n\n" + append + "\n", encoding="utf-8")
    print("PATCH_APPLIED", path.as_posix())
    print("BACKUP", backup.as_posix())
else:
    print("PATCH_ALREADY_PRESENT", path.as_posix())
PY

echo
echo "==== py_compile after patch ===="
"$PY" -m py_compile \
  src/kc_l/kc_drafting/model_profile.py \
  src/kc_l/kc_drafting/config.py \
  src/kc_l/kc_drafting/orchestration.py \
  src/kc_l/kc_drafting/backend.py \
  src/kc_l/kc_drafting/heuristic_core.py \
  src/kc_l/kc_drafting/provenance.py \
  src/kc_l/kc_drafting/packetization.py \
  steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py

echo
echo "==== create Gemma4 31B Step 6.7 smoke10 config ===="
STAMP="$(date -u +%Y%m%d_%H%M%S)"
GENERATED_CONFIG="data/work/cache/generated_configs/step6_7.gemma4_31b.stage3_v3_smoke10_${STAMP}.yaml"

export GENERATED_CONFIG STEP66_SET OLLAMA_BASE_URL GEMMA_MODEL

"$PY" - <<'PY'
import os
from pathlib import Path
import yaml
import json

out_path = Path(os.environ["GENERATED_CONFIG"])
step66_set = os.environ["STEP66_SET"]
base_url = os.environ["OLLAMA_BASE_URL"]
model = os.environ["GEMMA_MODEL"]

smoke_kcs = [
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_DE_PREP_003",
    "KC_EVAL_SAMP_003",
    "KC_CLU_DBS_003",
    "KC_CLU_CORE_002",
    "KC_CLU_DBS_001",
    "KC_CLF_NB_011",
    "KC_CLU_EVAL_012",
    "KC_EVAL_BASIC_005",
]

generic_system_prefix = """
You are drafting machine-generated knowledge-component records for a human reviewer.

You must follow these rules.

1. Use only the supplied evidence. Do not invent facts, definitions, examples, formulas, prerequisites, or scope.
2. Do not copy a textbook sentence word for word unless the text is a formula, symbol, or fixed technical term. Prefer a concise paraphrase that preserves the exact meaning.
3. A strong definition should state what the KC means and what role it plays. It should not merely repeat a heading, page fragment, example, or isolated formula.
4. If the evidence is only sibling contrast, background context, examples without a definition, or weak procedural context, abstain instead of pretending the KC is grounded.
5. If the evidence supports a partial draft, produce the supported part and clearly preserve holds for unsupported fields.
6. Keep kc_specific_criteria empty. Criteria are expert-authored later.
7. Return only the JSON object required by the caller. Do not include reasoning, analysis text, markdown, or commentary in the visible answer.

Domain-agnostic examples of desired behavior:

Example A:
KC name: Target concept
Evidence: "A target concept is the label or outcome that a learner must predict."
Good draft: "A target concept is the outcome variable that a model or learner is intended to predict."
Bad draft: "A target concept is important." Reason: too vague.

Example B:
KC name: Sibling concept Y
Evidence: "Unlike concept X, concept Y applies only after the grouping step."
Good draft: Abstain or mark partial support if no direct definition of Y is present.
Bad draft: Define concept X as if it were concept Y.

Example C:
KC name: Procedure Z
Evidence: "First compute the candidate score, then retain candidates above the threshold."
Good draft: "Procedure Z retains candidates whose computed score exceeds a threshold."
Bad draft: Invent a mathematical formula not present in the evidence.
""".strip()

model_profile = {
    "backend_kind": "ollama",
    "transport_mode": "ollama_chat",
    "response_parse_mode": "message_content_or_response_or_thinking",
    "generation_model": model,
    "resolved_model_alias": model,
    "generation_base_url": base_url,
    "temperature": 0.0,
    "top_p": 1.0,
    "repeat_penalty": 1.0,
    "num_ctx": 8192,
    "thinking_enabled": True,
    "thinking_activation_mode": "ollama_param",
    "thinking_system_prefix": "",
    "system_prefix": generic_system_prefix,
}

execution = {
    "execution_mode": "llm",
    "llm_required": True,
    "fail_closed_when_llm_unavailable": True,
    "provider": "ollama",
    "generation_model_alias": model,
    "generation_base_url": base_url,
    "generation_base_url_field": "generated_config.models.generation.base_url",
    "domain_policy_name": "none",
    "domain_policy_field": "generated_config.step6_7.drafting_policy.domain_policy",
}

cfg = {
    "project": {
        "timezone": "Europe/Berlin",
        "run_purpose": "step6_7_gemma4_31b_model_backed_smoke10",
    },
    "inputs": {
        "step6_6_set_manifest": step66_set,
    },
    "outputs": {
        "processed_root": "data/processed/kc_drafts",
        "sets_root": "data/processed/kc_drafts/_sets",
        "runs_root": "data/runs",
    },
    "slice": {
        "limit_kcs": 10,
        "exact_kc_ids": smoke_kcs,
    },
    "selection": {
        "max_bundle_size": 6,
        "max_explanatory_candidates": 5,
    },
    "execution": execution,
    "models": {
        "generation": {
            "provider": "ollama",
            "resolved_model_alias": model,
            "generation_model": model,
            "base_url": base_url,
            "temperature": 0.0,
            "top_p": 1.0,
            "repeat_penalty": 1.0,
            "num_ctx": 8192,
            "think": True,
            "thinking_enabled": True,
            "thinking_activation_mode": "ollama_param",
            "system_prefix": generic_system_prefix,
        },
        "gate_llm": {
            "provider": "ollama",
            "resolved_model_alias": model,
            "generation_model": model,
            "base_url": base_url,
            "think": True,
            "thinking_enabled": True,
        },
    },
    "model_profile": model_profile,
    "step6_7": {
        "contract_version": "step6_7_gemma4_31b_model_backed_smoke10_v1",
        "execution_mode": "llm",
        "llm_required": True,
        "fail_closed_when_llm_unavailable": True,
        "active_runner": "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py",
        "inputs": {
            "step6_6_set_manifest": step66_set,
        },
        "outputs": {
            "processed_root": "data/processed/kc_drafts",
            "sets_root": "data/processed/kc_drafts/_sets",
            "runs_root": "data/runs",
        },
        "slice": {
            "limit_kcs": 10,
            "exact_kc_ids": smoke_kcs,
        },
        "selection": {
            "max_bundle_size": 6,
            "max_explanatory_candidates": 5,
        },
        "drafting_policy": {
            "domain_policy": "none",
            "definition_generation_mode": "llm_evidence_grounded_paraphrase_v1",
            "evidence_text_max_chars": 900,
            "short_definition_max_chars": 260,
            "short_definition_max_tokens": 48,
            "max_llm_calls_per_kc": 8,
            "generic_few_shot_prompt_version": "domain_agnostic_evidence_behavior_v1",
            "forbid_verbatim_textbook_copy_except_formula_or_fixed_term": True,
            "abstain_when_only_auxiliary_or_sibling_support": True,
            "keep_kc_specific_criteria_empty": True,
        },
        "model_profile": model_profile,
    },
    "metadata": {
        "test": "gemma4_31b_step6_7_model_backed_smoke10_after_stage3_v3",
        "accepted_step6_6_set_manifest": step66_set,
        "model": model,
        "base_url": base_url,
        "thinking_enabled": True,
        "generic_few_shot_prompt": "enabled_domain_agnostic",
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    },
}

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

config_text = out_path.read_text(encoding="utf-8").lower()
if "qwen" in config_text:
    raise SystemExit("FAIL: generated Gemma config still contains qwen")

print("GENERATED_CONFIG =", out_path.as_posix())
print("CONFIG_PREVIEW =")
print(json.dumps(cfg, indent=2, ensure_ascii=False)[:7000])
PY

test -f "$GENERATED_CONFIG" || { echo "FAIL: generated config missing"; exit 1; }

echo
echo "==== run Step 6.7 Gemma4 31B smoke10 model-backed ===="
RUNNER_STDOUT="data/work/cache/diagnostics/step6_7_gemma4_31b_smoke10_runner_stdout_${SLURM_JOB_ID}.json"

"$PY" steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py \
  --config "$GENERATED_CONFIG" \
  | tee "$RUNNER_STDOUT"

RUN_ID="$(
  RUNNER_STDOUT="$RUNNER_STDOUT" "$PY" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["RUNNER_STDOUT"])
text = path.read_text(encoding="utf-8").strip()
start = text.rfind("{")
if start < 0:
    raise SystemExit("FAIL: no JSON object found in runner stdout")
obj = json.loads(text[start:])
run_id = obj.get("run_id")
if not run_id:
    raise SystemExit("FAIL: runner stdout JSON has no run_id")
print(run_id)
PY
)"

STEP67_SET="data/processed/kc_drafts/_sets/${RUN_ID}_step6_7_kc_drafts_set.json"
test -f "$STEP67_SET" || { echo "FAIL: missing Step 6.7 set: $STEP67_SET"; exit 1; }

echo "RUN_ID=$RUN_ID"
echo "STEP67_SET=$STEP67_SET"

echo
echo "==== assess Gemma4 31B smoke10 output ===="
STEP66_SET="$STEP66_SET" STEP67_SET="$STEP67_SET" GENERATED_CONFIG="$GENERATED_CONFIG" GEMMA_MODEL="$GEMMA_MODEL" "$PY" - <<'PY'
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

root = Path(".")
step66_set = os.environ["STEP66_SET"]
step67_set = Path(os.environ["STEP67_SET"])
generated_config = Path(os.environ["GENERATED_CONFIG"])
model = os.environ["GEMMA_MODEL"]

set_obj = json.loads(step67_set.read_text(encoding="utf-8"))
set_text = json.dumps(set_obj, ensure_ascii=False)
config_text = generated_config.read_text(encoding="utf-8")

if step66_set not in set_text and Path(step66_set).name not in set_text:
    raise SystemExit("FAIL: Step 6.7 set does not reference accepted Step 6.6 input")

if model not in config_text:
    raise SystemExit("FAIL: generated config does not contain Gemma model")

if "qwen" in config_text.lower():
    raise SystemExit("FAIL: generated config contains qwen")

artifacts = set_obj.get("artifacts") or {}

def resolve_artifact(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else root / p

def pick_artifact(*names: str) -> Path | None:
    for name in names:
        p = resolve_artifact(artifacts.get(name))
        if p is not None and p.exists():
            return p
    return None

drafts_path = pick_artifact(
    "kc_draft_bundles_jsonl",
    "draft_bundles_jsonl",
    "kc_drafts_jsonl",
    "drafts_jsonl",
)

stats_path = pick_artifact(
    "draft_stats_json",
    "kc_draft_stats_json",
    "stats_json",
)

if drafts_path is None:
    for value in artifacts.values():
        p = resolve_artifact(value)
        if p is not None and p.exists() and p.suffix == ".jsonl":
            drafts_path = p
            break

if stats_path is None:
    for value in artifacts.values():
        p = resolve_artifact(value)
        if p is not None and p.exists() and p.suffix == ".json" and "stat" in p.name:
            stats_path = p
            break

if drafts_path is None or not drafts_path.exists():
    raise SystemExit(f"FAIL: could not locate draft JSONL from artifacts: {artifacts}")

rows = [json.loads(line) for line in drafts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path and stats_path.exists() else {}

all_text = json.dumps({"set": set_obj, "stats": stats, "rows": rows}, ensure_ascii=False)

runtime_model_hit = model in all_text or model in config_text
llm_hit = (
    '"execution_mode": "llm"' in all_text
    or '"execution_mode":"llm"' in all_text
    or '"llm_mode_selected": true' in all_text
    or '"llm_required": true' in all_text
)

kc_ids = [str(row.get("kc_id") or "") for row in rows]
kc_counts = Counter(kc_ids)
duplicate_kc_ids = sorted(kc for kc, n in kc_counts.items() if n > 1)
missing_kc_id_rows = [i for i, kc in enumerate(kc_ids) if not kc]

expected_kcs = {
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_DE_PREP_003",
    "KC_EVAL_SAMP_003",
    "KC_CLU_DBS_003",
    "KC_CLU_CORE_002",
    "KC_CLU_DBS_001",
    "KC_CLF_NB_011",
    "KC_CLU_EVAL_012",
    "KC_EVAL_BASIC_005",
}
seen_kcs = set(kc_ids)
missing_kcs = sorted(expected_kcs - seen_kcs)
extra_kcs = sorted(seen_kcs - expected_kcs)

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

def collect_strings(obj: Any) -> list[str]:
    out = []
    if isinstance(obj, dict):
        for value in obj.values():
            out.extend(collect_strings(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(collect_strings(value))
    elif isinstance(obj, str):
        if obj.strip():
            out.append(obj)
    return out

known_bad_definition_hits = {}
extractive_definition_hits = []
grounded_definition_count = 0

for row in rows:
    kc_id = str(row.get("kc_id") or "")

    for candidate_key in ("definition_full_candidate", "definition_short_candidate"):
        candidate = row.get(candidate_key) or {}
        if isinstance(candidate, dict) and candidate.get("status") == "grounded" and norm(candidate.get("text")):
            grounded_definition_count += 1

    definition_strings = collect_definition_like_strings(row)
    evidence_strings = collect_strings(row.get("evidence_bundle"))
    evidence_norms = [norm(s) for s in evidence_strings if len(norm(s)) >= 40]

    for path, text in definition_strings:
        text_norm = norm(text)

        for marker in known_bad.get(kc_id, []):
            marker_norm = norm(marker)
            if marker_norm and marker_norm in text_norm:
                known_bad_definition_hits.setdefault(kc_id, []).append({
                    "path": path,
                    "marker": marker,
                    "text": text,
                })

        if len(text_norm) >= 80 and any(text_norm in ev for ev in evidence_norms):
            extractive_definition_hits.append({
                "kc_id": kc_id,
                "path": path,
                "text": text,
            })

nonempty_kc_specific_criteria = []
for row in rows:
    value = row.get("kc_specific_criteria")
    if value not in (None, [], {}, ""):
        nonempty_kc_specific_criteria.append(str(row.get("kc_id") or ""))

def breakdown(field_name: str) -> dict[str, int]:
    c = Counter()
    for row in rows:
        value = row.get(field_name)
        if isinstance(value, str) and value:
            c[value] += 1
    return dict(sorted(c.items()))

assessment = {
    "assessment_scope": "step6_7_gemma4_31b_model_backed_smoke10",
    "step6_6_set_manifest": step66_set,
    "step6_7_set_manifest": step67_set.as_posix(),
    "generated_config": generated_config.as_posix(),
    "drafts_path": drafts_path.as_posix(),
    "stats_path": stats_path.as_posix() if stats_path else "",
    "row_count": len(rows),
    "unique_kc_count": len(seen_kcs),
    "missing_kcs": missing_kcs,
    "extra_kcs": extra_kcs,
    "duplicate_kc_ids": duplicate_kc_ids,
    "missing_kc_id_rows": missing_kc_id_rows,
    "runtime_model_hit": runtime_model_hit,
    "llm_hit": llm_hit,
    "grounded_definition_count": grounded_definition_count,
    "extractive_definition_hits_count": len(extractive_definition_hits),
    "extractive_definition_hits_sample": extractive_definition_hits[:10],
    "known_bad_definition_hits": known_bad_definition_hits,
    "nonempty_kc_specific_criteria": sorted(set(nonempty_kc_specific_criteria)),
    "draft_status_breakdown": breakdown("draft_status"),
    "authoritative_definition_status_breakdown": breakdown("authoritative_definition_status"),
    "interesting_stats": {
        k: stats.get(k)
        for k in sorted(stats.keys())
        if k in {
            "total_kcs",
            "draft_status_breakdown",
            "authoritative_definition_status_breakdown",
            "drafting_mode",
            "execution_mode",
            "resolved_generation_model_alias",
            "domain_policy_name",
            "llm_calls",
            "thinking_used_frac",
        }
    },
    "sample_row_keys": sorted(rows[0].keys()) if rows else [],
}

out = root / "data/work/cache/diagnostics" / f"{step67_set.stem}_gemma4_31b_smoke10_assessment.json"
out.write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")

print("ASSESSMENT_JSON =", out.as_posix())
print("STEP67_SET =", step67_set.as_posix())
print("DRAFTS_PATH =", drafts_path.as_posix())
print("STATS_PATH =", stats_path.as_posix() if stats_path else "")
print("row_count =", len(rows))
print("unique_kc_count =", len(seen_kcs))
print("missing_kcs =", missing_kcs)
print("extra_kcs =", extra_kcs)
print("duplicate_kc_ids =", duplicate_kc_ids)
print("runtime_model_hit =", runtime_model_hit)
print("llm_hit =", llm_hit)
print("grounded_definition_count =", grounded_definition_count)
print("extractive_definition_hits_count =", len(extractive_definition_hits))
print("known_bad_definition_hits =", json.dumps(known_bad_definition_hits, indent=2, ensure_ascii=False))
print("nonempty_kc_specific_criteria_count =", len(set(nonempty_kc_specific_criteria)))
print("draft_status_breakdown =", json.dumps(assessment["draft_status_breakdown"], indent=2, ensure_ascii=False))
print("authoritative_definition_status_breakdown =", json.dumps(assessment["authoritative_definition_status_breakdown"], indent=2, ensure_ascii=False))
print("interesting_stats =", json.dumps(assessment["interesting_stats"], indent=2, ensure_ascii=False))

if len(rows) != 10:
    raise SystemExit(f"FAIL: expected 10 Step 6.7 smoke rows, got {len(rows)}")
if len(seen_kcs) != 10:
    raise SystemExit(f"FAIL: expected 10 unique KC ids, got {len(seen_kcs)}")
if missing_kcs or extra_kcs:
    raise SystemExit("FAIL: smoke KC set mismatch")
if duplicate_kc_ids:
    raise SystemExit("FAIL: duplicate KC ids in smoke output")
if missing_kc_id_rows:
    raise SystemExit("FAIL: Step 6.7 smoke rows missing kc_id")
if not runtime_model_hit:
    raise SystemExit("FAIL: Gemma model not visible in Step 6.7 output/config evidence")
if not llm_hit:
    raise SystemExit("FAIL: Step 6.7 output/config does not prove LLM mode")
if grounded_definition_count < 3:
    raise SystemExit("FAIL: too few grounded definitions in smoke output")
if known_bad_definition_hits:
    raise SystemExit("FAIL: known bad markers leaked into definition-like draft fields")
if nonempty_kc_specific_criteria:
    raise SystemExit("FAIL: kc_specific_criteria is non-empty before expert review")
if grounded_definition_count > 0 and len(extractive_definition_hits) >= grounded_definition_count:
    raise SystemExit("FAIL: all grounded definitions appear extractive, not model-drafted")

print("STEP6_7_GEMMA4_31B_SMOKE10_MODEL_BACKED_ASSESSMENT_OK")
PY

echo
echo "==== protect current aliases after run ===="
ALIAS_HASH_AFTER="data/work/cache/diagnostics/step6_7_gemma4_smoke10_alias_hashes_after_${SLURM_JOB_ID}.txt"
: > "$ALIAS_HASH_AFTER"

for rel in \
  "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json" \
  "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json" \
  "data/work/cache/current_step_artifacts/step6_75_set_manifest.current.json" \
  "data/work/cache/current_step_artifacts/step6_7b_set_manifest.current.json"
do
  if [ -f "$rel" ]; then
    sha256sum "$rel" | tee -a "$ALIAS_HASH_AFTER"
  else
    echo "MISSING $rel" | tee -a "$ALIAS_HASH_AFTER"
  fi
done

if ! diff -u "$ALIAS_HASH_FILE" "$ALIAS_HASH_AFTER"; then
  echo "FAIL: current alias hashes changed unexpectedly"
  exit 1
fi

echo
echo "STEP6_7_GEMMA4_31B_SMOKE10_MODEL_BACKED_PIPELINE_OK"
