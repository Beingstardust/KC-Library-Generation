Step 6.7 generic lane policy V2 patch.

Source Repo A:
R:\Thesis Project\kc_l_v2_seedless_rework_sync\20260423_214049_kc_l_v2_seedless_rework_sync\unpacked\repo_source

Created:
2026-04-28 22:33:31

Purpose:
Sync only the repaired generic, domain-agnostic, model-agnostic Step 6.7 sidecar lane policy to Sofja for bounded replay and validation.

Included files:
src/kc_l/kc_drafting/evidence_lane_policy.py
scripts/experimental/step67a_build_field_lane_packets_generic.py
tests/test_evidence_lane_policy.py
tests/test_step67_sidecar_domain_agnosticity.py
docs/operator_notes/STEP67_GENERIC_LANE_POLICY_2026-04-28.md
CHANGELOG.md

Not included:
- local replay outputs
- _reference_artifacts
- production Step 6.7 orchestration
- Step 6.8 files
- model runner changes
- CODEX_ACTIVE_STEP6_REFACTOR_STATE.md
