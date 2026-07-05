# Final Verdict

## 1. Executive Verdict

Classification: `not honestly equivalent`

The clean repo preserved a large amount of the old low-level code and step ladder, but it did not preserve honest operational equivalence as delivered.

What is true:
- most retained `src/` and `steps/` execution logic is still there
- the old multi-PDF Step 2 wrapper still exists
- many stage handoff contracts from Step 3 onward are still present inside the legacy `steps/` tree

What is not true:
- the new public operator surface is not an executable replacement for the old operational surface
- the clean status / preflight / config-render surfaces overclaim readiness
- the default package/bootstrap path no longer prepares the full retained pipeline
- several late-stage configs still depend on historical processed artifacts that the clean repo intentionally removed

Direct answers required by the audit brief:
- The clean repo did lose corpus-level orchestration as an honestly exposed surface.
  - The old multi-PDF path still exists internally, but the clean public/operator surface does not replace it and the cleaned layout no longer satisfies it.
- Step 2 to Step 3 continuity was not destroyed inside the legacy step tree.
  - In fact `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py` was improved to emit the Step 2 set pointer.
  - But the advertised clean first-run path is broken because the retained Step 2 wrapper/config still use `data/raw/...`, not the new `data/input/...` roots.
- Docs and status surfaces currently overclaim readiness.

## 2. Exact Preserved Surfaces

- The retained low-level step ladder is mostly intact:
  - Step 3, Step 3.5, Step 3.6, Step 4, Step 4.3, Step 4.5, Step 5, Step 5.2, Step 5.3, Step 6.6, Step 6.7, and Step 6.8 runners are preserved in place.
- The old multi-PDF wrapper still exists:
  - `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1`
- The internal main-quest step files under `steps/step_06_main_quest_execution/` still exist.
- The knowledge-library package surface was mostly kept:
  - `kc_l.knowledge_library` still exports the same conceptual access and grounding APIs.
- The 2 -> 3 internal contract was strengthened:
  - the clean `run_step2.py` now writes `ACTIVE_STEP2_SET.txt` and a merged Step 2 set manifest

## 3. Exact Lost Surfaces

- Old durable main-quest state / recovery docs:
  - `PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md`
  - `PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md`
  - `PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md`
  - `PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md`
  - the rest of `PROJECT_STATE/`
- Old frozen-release state pointers and lineage docs:
  - `CURRENT_ACTIVE_STATE.md`
  - `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md`
  - `docs/knowledge_library_pilot.md`
  - `STEP6_SCHEMA_LINEAGE.md`
  - `Target design.md`
  - `Current.md`
- Old root Step 6.7 model-backed launcher surface:
  - `run_step6_7_model_draft_generation.py`
  - root `step6_6_*.yaml`
  - root `step6_7_*.yaml`
  - root `step6_8_*.yaml`

## 4. Exact Misleading Surfaces

- `README.md`
  - claims the clean entry surfaces should replace the research-era `steps/` tree
  - claims the repo is ready for first use
- `docs/workflows/offline_generation_lifecycle.md`
  - claims the new commands point to the same underlying logic
- `src/kc_l/runtime/operator_stages.py`
  - reports `ready_for_first_run = true` when clean layout checks pass and inputs exist
  - omits several retained stages that `configs/pipeline/main_quest.base.yaml` itself says are part of the internal flow
- `scripts/maintenance/check_operator_repo.py`
  - reduces the same overpermissive status surface and returned `ok: true`
- `scripts/hpc/render_main_quest_config.py` plus `src/kc_l/runtime/main_quest_config.py`
  - render `ok: true` for Linux- and Beegfs-specific example overlays on this Windows repo

## 5. Multi-PDF Corpus Capability, Old vs Clean

Old:
- Exact old path that handled multi-PDF corpus execution:
  - `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1`
- It scans `data/raw/pdfs` and shells into `run_step2.py`.
- Old tracked set manifests prove the path worked in practice:
  - `data/processed/blockstore/_sets/2026-03-02_214129_step2_set.json`
  - `data/processed/doctree/_sets/2026-03-03_120609_step3_step3_set.json`

Clean:
- The same internal wrapper is still present.
- But CLEAN_REPO no longer provides `data/raw/pdfs`.
- A smoke run of the wrapper failed immediately with `ERROR: Folder not found: ...data/raw/pdfs`.
- The new public operator surface does not provide any equivalent multi-PDF corpus runner.

Verdict:
- Old repo: yes, multi-PDF corpus intake existed in practice.
- Clean repo: only internally and misleadingly. The path is retained, but the cleaned layout and new operator story do not preserve it honestly.

## 6. Stage Contract Breakages

- `1.5 -> 2` is not a real direct handoff in either repo.
  - The overlay lane and the PDF lane only converge later.
  - Any clean narrative that flattens them into one linear "operator stage 1" story loses architectural precision.
- `2 -> 3` is internally preserved and repaired, but publicly broken.
  - Internal fix: clean `run_step2.py` now emits the Step 2 set contract.
  - Public break: clean entry docs point to `data/input/...`, while retained Step 2 still needs `data/raw/...`.
- `3.6 -> 4` ships with `dry_run: true` in the default Step 4 config.
- `4 -> 4.3 -> 4.5` is preserved internally but hidden from the clean public stage mapping.
- `4.5 -> 5 -> 5.2 -> 5.3` still depends on a dated historical `kc_registry_path`.
- `5.3 -> 6.6` still depends on a dated hierarchy overlay manifest and a hardcoded 128-KC slice.
- `6.6 -> 6.7 -> 6.8` still depends on dated set-manifest paths, and the old root model-backed Step 6.7 wrapper was removed.

## 7. Smallest Repair Set To Restore True Equivalence

- Make the public operator surface either truthful or actually executable.
  - Files:
    - `README.md`
    - `docs/workflows/offline_generation_lifecycle.md`
    - `docs/architecture/operator_repo.md`
    - `docs/workflows/hpc_first_run_preparation.md`
    - `src/kc_l/runtime/operator_stages.py`
    - `scripts/local/run_stage.py`
- Bridge the clean input layout to the retained Step 2 intake code, or explicitly restore/expose the old raw-input contract.
  - Files:
    - `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1`
    - `steps/step_02_pdf_ingest_blockstore/resources/step2.default.yaml`
- Make the new config renderer honest about runtime readiness.
  - Files:
    - `src/kc_l/runtime/main_quest_config.py`
    - `scripts/hpc/render_main_quest_config.py`
    - `configs/pipeline/main_quest.base.yaml`
    - `configs/pipeline/main_quest.local_gpu.example.yaml`
    - `configs/pipeline/main_quest.hpc_gpu.example.yaml`
- Remove or regenerate historically pinned late-stage defaults.
  - Files:
    - `steps/step_05_kc_evidence_mining/resources/step5.default.yaml`
    - `steps/step_05_2_evidence_sharpen/resources/step5_2.default.yaml`
    - `steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml`
    - `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml`
    - `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml`
    - `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml`
- Restore or re-document the removed durable execution authority.
  - Smallest truthful options:
    - restore the critical `PROJECT_STATE/` execution docs into CLEAN_REPO
    - or rewrite the clean docs/configs so they no longer imply that the new surface fully replaces them
- Decide whether the clean repo should preserve the old model-backed Step 6.7 launcher.
  - If yes, restore or relocate:
    - `run_step6_7_model_draft_generation.py`
    - the root Step 6.6 / 6.7 / 6.8 YAML family

## 8. Nice-to-Have Repairs

- Add an automated parity test that fails if `operator_stages.py` omits steps still listed in `configs/pipeline/main_quest.base.yaml`.
- Add a smoke test that fails if `run_stage.py intake` or `draft-preflight` reports ready while the retained Step 2 wrapper cannot locate its input root.
- Mark the example runtime overlays as platform-specific examples rather than `ok` configs unless strict validation passes.
- Clarify in docs whether CLEAN_REPO is meant to be:
  - a clean operator shell
  - or a truly equivalent execution repo

## 9. Files That Must Not Be Touched

Until the wrapper/docs/control-plane repairs are decided, do not rewrite the preserved low-level lineage surfaces that still carry the old behavior:
- `steps/step_03_doctree_index/scripts/run_step3.py`
- `steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py`
- `steps/step_03_6_math_salvage/scripts/run_step3_6.py`
- `steps/step_04_structure_retrieval_index/scripts/run_step4.py`
- `steps/step_04_structure_retrieval_index/scripts/run_step4_3.py`
- `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py`
- `steps/step_05_kc_evidence_mining/scripts/run_step5.py`
- `steps/step_05_2_evidence_sharpen/scripts/run_step5_2.py`
- `steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py`
- `steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py`
- `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py`
- `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.base.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.local_gpu.yaml`
- `steps/step_06_main_quest_execution/resources/step6_main_quest_v1.hpc_gpu.yaml`

These are the parity-bearing files. The safer repair strategy is to fix docs, wrappers, config defaults, and bootstrap around them first.

## 10. Confidence and Remaining Uncertainties

Confidence: high

Why high:
- The inventory CSV cleanly separates same, changed, old-only, and clean-only semantic surfaces.
- The most important misleading claims were verified behaviorally, not just read from docs.
  - clean intake/draft preflight reported ready
  - clean Step 2 corpus wrapper failed on the cleaned layout
  - old `load_release()` succeeded while clean `load_release()` failed by default

Remaining uncertainties:
- The old tracked `run_step2.py` did not itself emit the Step 2 set manifest, so some old Step 2 set creation may have involved an earlier script version or manual/operator action that is not fully reconstructable from the remaining files alone.
- I did not execute the heavy mid/late stages; conclusions there are code- and config-grounded rather than based on a fresh rerun.
- I intentionally did not use historical output contents as semantic mismatch evidence except where a tracked set manifest or pointer was itself the contract.
