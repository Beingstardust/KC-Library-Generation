from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def exists_info(path_str: str) -> dict:
    p = Path(path_str)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return {
        "path": str(p),
        "exists": p.exists(),
        "is_file": p.is_file() if p.exists() else False,
    }

def read_json(path_str: str) -> dict:
    p = Path(path_str)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return json.loads(p.read_text(encoding="utf-8"))

report = {
    "repo_root": str(REPO_ROOT),
    "checks": {},
    "notes": [
        "This script is read-only.",
        "It reports selector surfaces and known runner splits relevant to the Step 6.x actual-corpus branch.",
        "It does not certify semantic suitability or end-to-end runtime readiness.",
    ],
}

# Core runner surfaces
report["checks"]["step67_root_runner"] = exists_info("run_step6_7_model_draft_generation.py")
report["checks"]["step67_step_local_runner"] = exists_info(
    "steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py"
)

# Alias surfaces
alias_paths = {
    "active_seedless_registry_pointer": "data/work/cache/current_step_artifacts/ACTIVE_SEEDLESS_KC_REGISTRY.txt",
    "step1_registry_alias": "data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl",
    "step1_5_overlay_alias": "data/work/cache/current_step_artifacts/step1_5_overlay_manifest.current.json",
    "step6_6_alias": "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json",
    "step6_7_alias": "data/work/cache/current_step_artifacts/step6_7_set_manifest.current.json",
}
for k, v in alias_paths.items():
    report["checks"][k] = exists_info(v)

# Local upstream selector surfaces
local_selector_paths = {
    "local_step4_active": "data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt",
    "local_step4_patches_active": "data/processed/retrieval_index/_sets/ACTIVE_STEP4_PATCHES_SET.txt",
    "local_step4_5_active": "data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SET.txt",
    "local_step4_5_sentence_active": "data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SENTENCE_SET.txt",
    "local_step5_active": "data/processed/kc_evidence/_sets/ACTIVE_STEP5_EVIDENCE_SET.txt",
    "local_step5_2_active": "data/processed/kc_evidence_sharp/_sets/ACTIVE_STEP5_2_EVIDENCE_SHARP_SET.txt",
    "local_step5_3_active": "data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt",
}
for k, v in local_selector_paths.items():
    report["checks"][k] = exists_info(v)

# Accepted Step 6.6 upstream scratch-backed surfaces if alias exists
step66_alias = REPO_ROOT / "data/work/cache/current_step_artifacts/step6_6_set_manifest.current.json"
if step66_alias.exists():
    obj = json.loads(step66_alias.read_text(encoding="utf-8"))
    up = obj.get("upstream", {})
    for key in [
        "step4_active_set_pointer",
        "step4_active_set_target",
        "step4_5_active_set_pointer",
        "step4_5_active_set_target",
    ]:
        if up.get(key):
            report["checks"][f"accepted_branch_{key}"] = exists_info(up[key])

# Step 6.x default config surfaces
config_paths = {
    "step6_6_default": "steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml",
    "step6_7_default": "steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml",
    "step6_8_default": "steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml",
}
for k, v in config_paths.items():
    report["checks"][k] = exists_info(v)

print(json.dumps(report, indent=2))
