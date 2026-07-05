# CHANGELOG

This is the durable running repo changelog going forward.

Historical one-off reports such as `STEP6_CHANGELOG_REPORT.txt` remain useful background, but new repo changes should be logged here.

## 2026-04-08

- Repaired the actual-corpus Step 6.8 review boundary so coherent held Step 6.7 bundles with persisted local-only LLM definition proposals can re-enter the reviewer lane without auto-filling `kc_specific_criteria`: updated `src/kc_l/kc/restarted_review_packets.py` to revive held-definition salvage, keep sibling-mismatch exclusions, preserve fragmentary/mixed-foreign quarantine, and audit held-salvage counts explicitly; generalized the ready-session wording in `src/kc_l/kc/restarted_human_review_capture.py`; and validated the boundary change on the live `2026-04-08_131447` draft bundle under `data/runs/_audit/2026-04-08_codex_step68_salvage_validation/`, expanding the audit-only ready packet surface from `49` to `105` while leaving `14` cases excluded.

## 2026-04-05

- Repaired bootstrap continuity so `requirements.txt` again means full retained-pipeline bootstrap rather than operator-only convenience: restored `orjson` and `rich` to the editable package baseline in `pyproject.toml`, rewired `requirements-runtime.txt` and `requirements-runtime-notorch.txt` to install `kc_l` editably for the preserved step tree, clarified `requirements-operator.txt` as a secondary operator-shell-only surface, updated `README.md`, and recorded the scoped repair under `audit/repo_equivalence_audit/20260404_001657/repair_bootstrap_continuity.md`.
- Added honest current-artifact discovery conventions for the Step 5 and Step 6 clean-start templates: introduced `src/kc_l/runtime/current_step_artifacts.py` plus `scripts/maintenance/refresh_current_step_artifacts.py`, repointed the live Step 5 / 6 templates to stable alias files under `data/work/cache/current_step_artifacts/`, updated `steps/README.md`, and recorded the scoped repair under `audit/repo_equivalence_audit/20260404_001657/repair_current_step_artifact_discovery.md`.
- Removed historically pinned Step 5 and Step 6 shipped current/default resource defaults as live surfaces: repointed the Step 5 `*.default.yaml` files and the Step 6 `slice10` / `full128` templates to explicit clean-start placeholders, preserved the old pinned values under explicit `historical_*` YAML names, marked the remaining bounded `slice24` / `slice48` Step 6 configs as historical in comments, updated `steps/README.md`, and recorded the scoped repair under `audit/repo_equivalence_audit/20260404_001657/repair_step5_step6_resource_default_depins.md`.

## 2026-04-04

- Aligned the main-quest config renderer and validator with the same operator-shell-only truth boundary as the public status shell: updated `src/kc_l/runtime/main_quest_config.py`, `scripts/hpc/render_main_quest_config.py`, and `tests/test_main_quest_config.py` so example overlays now report operator-shell config validity plus explicit non-readiness warnings instead of presenting `ok: true` as unqualified retained-pipeline runtime readiness; recorded the scoped repair under `audit/repo_equivalence_audit/20260404_001657/repair_config_render_truth_boundary.md`.
- Aligned the public operator/docs surface with the restored legacy execution authority: rewrote `README.md`, `docs/architecture/operator_repo.md`, `docs/workflows/offline_generation_lifecycle.md`, `docs/workflows/hpc_first_run_preparation.md`, and `steps/README.md` so the public shell is described as readiness/discoverability rather than a replacement for the retained execution ladder; updated `src/kc_l/runtime/operator_stages.py`, `scripts/local/run_stage.py`, and `scripts/maintenance/check_operator_repo.py` to expose an explicit operator-shell truth boundary plus the restored legacy execution surfaces; recorded the scoped repair under `audit/repo_equivalence_audit/20260404_001657/repair_operator_shell_truthfulness_alignment.md`.
- Restored the exact old durable execution-authority surfaces into the clean repo without touching the preserved low-level step runners: added PROJECT_STATE/MAIN_QUEST_EXECUTION_AUTHORIZATION.md, PROJECT_STATE/MAIN_QUEST_ENTRY_CONTRACT.md, PROJECT_STATE/MAIN_QUEST_PREFLIGHT_RECIPE.md, PROJECT_STATE/KC_SEMANTIC_GATING_POLICY_FROM_SIDEQUEST.md, PROJECT_STATE/REPO_GROUNDED_MASTER_DOSSIER.md, the root run_step6_7_model_draft_generation.py launcher, and the old root step6_6_*.yaml, step6_7_*.yaml, and step6_8_*.yaml family; recorded the scoped repair under audit/repo_equivalence_audit/20260404_001657/repair_execution_authority_surface_restore.md.
- Added the cross-platform corpus intake launcher `scripts/local/run_corpus_intake.py`, made it the primary truthful Step 2 intake surface for local and Sofja/Linux use, updated the intake-facing docs/control plane to point to it, and recorded the repair under `audit/repo_equivalence_audit/20260404_001657/repair_step1b_cross_platform_intake.md`.
- Repaired the retained Step 2 corpus-intake bridge so `steps/step_02_pdf_ingest_blockstore/scripts/run_step2_all.ps1` now scans `data/input/course_materials`, derives deterministic per-file `doc_id` values, and keeps the existing Step 2 active-set handoff intact for `steps/step_03_doctree_index/scripts/run_step3.py`; also updated the intake-facing docs/help and added the scoped repair note under `audit/repo_equivalence_audit/20260404_001657/repair_step1_corpus_intake.md`.
- Added the repo-grounded forensic equivalence audit bundle under `audit/repo_equivalence_audit/20260404_001657/`, including the recovered-state summary, old-vs-clean scoped inventory CSV, execution-surface comparison, stage-contract matrix, config/docs/package mismatch reports, and the final verdict on semantic parity between the old and cleaned KC_L v2 repos.

## 2026-04-03

- Resolved the remaining Sofja operator-runtime placeholders in `configs/pipeline/main_quest.local_gpu.example.yaml` and `configs/pipeline/main_quest.hpc_gpu.example.yaml`, pinning the proven Sofja interpreter, `cuda`, the local Ollama endpoint, the scratch-backed HPC roots, and `slurm.account: null` because the repo accepts an omitted account and no concrete cluster account was provided.

## 2026-04-02

- Reconstructed the clean repo dependency model from current code, configs, docs, tests, and preserved internal step surfaces; split packaging into `requirements-operator.txt`, `requirements-runtime.txt`, and `requirements-dev.txt`, repointed `requirements.txt` to the operator shell, and realigned `pyproject.toml` so base dependencies stay operator-light while heavy preserved pipeline dependencies move into the new `runtime` extra.
- Replatformed the repo into a clean operator-facing layout: added `configs/`, `docs/architecture/`, `docs/workflows/`, `docs/supervisor_overview/`, `scripts/local/`, `scripts/hpc/`, `scripts/maintenance/`, and the clean runtime roots under `data/input/`, `data/work/`, `data/runs/`, `data/library/`, and `data/exports/`.
- Rewrote `README.md` and added operator docs for the new runtime topology, the offline lifecycle, the locked-core versus extension-schema model, and the future HPC-first-run preparation boundary.
- Added the new runtime control plane under `src/kc_l/runtime/`, including clean operator-path resolution, the JSON active-library pointer, schema-profile validation, the main-quest config renderer, and operator-stage status/preflight helpers.
- Added the public operator entrypoints `scripts/local/run_stage.py`, `scripts/hpc/render_main_quest_config.py`, and `scripts/maintenance/check_operator_repo.py`, and marked the research-era `steps/` tree as internal-only through `steps/README.md`.
- Retargeted `src/kc_l/knowledge_library/access.py` and `src/kc_l/knowledge_library/grounding_bridge.py` away from the old markdown pilot pointer and onto the new clean active-library pointer at `data/library/active/knowledge_library_release_pointer.json`.
- Removed the live historical runtime and archaeology surfaces from this repo copy, including old `data/raw/`, `data/processed/`, `data/review_inputs/`, `data/runs/`, `data/work/`, local caches/model stores, archive/state folders, root-level run artifacts, and the old historical smoke tests; replaced them with clean empty-state placeholders and a new operator-focused test suite.
- Ran a bounded operator smoke-test pass, tightened `src/kc_l/runtime/operator_stages.py` so input-root guidance files do not count as real course materials or hierarchy inputs, and verified the public stage preflights still block for the correct empty-state reasons.
- Added first-use guidance files in `data/input/course_materials/README.md` and `data/input/hierarchy/README.md` plus `docs/examples/minimal_hierarchy.template.yaml` so a first run can be staged without reintroducing live-input clutter.
- Expanded the operator smoke tests in `tests/test_operator_layout.py` and `tests/test_cli_surfaces.py` to cover empty-state input counts and the expected review/freeze preflight blocking behavior.
## 2026-04-01

- Added a processed-artifact registry layer under `data/processed/README.md` and `data/processed/_registry/`, documenting the 42 top-level processed families, their classifications, the hard lineage split between older `_sets`-driven step surfaces and the newer manifest-based April 1 library surfaces, and the current canonical entry bundles.
- Added `data/processed/_registry/canonical_processed_surfaces.json` as a machine-readable pointer index for the active April 1 library surfaces, the current March 30 KC review boundary source, preserved March 26 baselines, and the legacy active `_sets` pointers that still anchor older steps.
- Kept the consolidation registry-only in this pass: no processed family directories were moved, renamed, deleted, or rewritten, because many scripts, manifests, configs, and historical notes still resolve the existing family paths directly.

- Rewrote `README.md` to document the repo's current thesis stage, the frozen April 1 Knowledge Library pilot boundary, the Topic Library / KC Library / Knowledge Library split, the conservative graph semantics, and the read-only access and grounding entrypoints.
- Added `docs/knowledge_library_pilot.md` as a compact boundary and entrypoint note for the active pilot release, including the exact frozen source files, approved-only retrieval pointer, and durable pointer map for future UI work.
- Clarified the durable state pointers in `CURRENT_ACTIVE_STATE.md` and `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md` without changing frozen artifacts or library semantics.

- Added the downstream grounding bridge under `src/kc_l/knowledge_library/grounding_bridge.py` plus the bounded runner `steps/step_01_9_knowledge_library_grounding_bridge/scripts/run_step01_9_knowledge_library_grounding_bridge.py`, exposing release-backed topic/KC grounding bundles, conservative graph neighborhood summaries, and a read-only retrieval pointer without rebuilding any upstream assets.
- Emitted the derived grounding-bridge bundle under `data/processed/knowledge_library_grounding_bridge_restarted/2026-04-01_184151/`, including `grounding_bridge_manifest.json`, `grounding_bridge_report.md`, `grounding_bridge_validation_results.json`, `grounding_bridge_validation_summary.md`, and `grounding_bridge_examples.json` after validating the bridge against the active pilot release and the frozen access-layer bundle.
- Kept the pass interface-only: no topic or KC content changes, no graph regeneration, no semantic widening, no segmentation/evaluator implementation, and no `kc_specific_criteria` changes.
- Added the pilot Knowledge Library access layer under `src/kc_l/knowledge_library/access.py` plus the bounded runner `steps/step_01_8_knowledge_library_access_layer/scripts/run_step01_8_knowledge_library_access_layer.py`, providing read-only release resolution, typed topic/KC/graph loaders, conservative graph access helpers, and optional approved-only retrieval pointer exposure without rebuilding retrieval assets.
- Emitted the derived access-layer validation bundle under `data/processed/knowledge_library_access_layer_restarted/2026-04-01_182416/`, including `access_layer_manifest.json`, `access_layer_report.md`, `access_validation_results.json`, `access_validation_summary.md`, and `access_inventory_preview.csv` after validating the active pilot release boundary end to end.
- Kept the pass integration-only: no topic or KC content changes, no graph regeneration, no semantic widening, no downstream evaluator work, and no kc_specific_criteria changes.
- Added the pilot Knowledge Library release packaging bundle under `data/processed/knowledge_library_pilot_release_restarted/2026-04-01_181217/`, freezing one explicit release boundary over the active reviewed Topic Library subset, approved KC Library subset, conservative typed graph bundle, and clean schema-validation bundle.
- Emitted `knowledge_library_pilot_release_manifest.json`, `knowledge_library_pilot_release_report.md`, `knowledge_library_boundary_note.md`, and `knowledge_library_component_inventory.csv`, explicitly preserving the two excluded topics and the conservative `topic_contains_kc` membership caveat.
- Added `CURRENT_KNOWLEDGE_LIBRARY_PILOT_RELEASE.md` as the lightweight active pointer for the pilot release boundary, without rewriting older state files or reopening any drafting/review/graph-generation work.

- Added the Knowledge Library schema and validation hardening surface under `src/kc_l/knowledge_library/` plus the bounded runner `steps/step_01_7_knowledge_library_schema_validation/scripts/run_step01_7_knowledge_library_schema_validation.py`, formalizing canonical typed contracts for topic nodes, KC nodes, and the current pilot graph edge set without changing upstream topic, KC, or graph artifacts.
- Emitted the derived validation bundle under `data/processed/knowledge_library_schema_validation_restarted/2026-04-01_180256/`, including `schema_manifest.json`, `schema_report.md`, `validation_results.json`, `validation_summary.md`, and normalized graph node/edge previews after validating the April 1 pilot boundaries and conservative graph bundle cleanly against the new contract layer.
- Kept the pass boundary-only: no topic or KC drafting, no review reruns, no graph regeneration, no UI or downstream work, and no `kc_specific_criteria` changes.

- Added the first typed knowledge-graph preparation bundle under `data/processed/knowledge_graph_preparation_restarted/2026-04-01_173727/`, emitting separate typed `topic` and `kc` node layers plus conservative `topic_contains_topic` and `topic_contains_kc` edge layers from the resolved reviewed topic boundary and the approved frozen KC boundary.
- Emitted `graph_nodes.jsonl`, `graph_edges.jsonl`, `graph_manifest.json`, `graph_validation_report.md`, `graph_summary.md`, `graph_adjacency_summary.csv`, and `graph_edge_counts.csv`, validating a clean 89-node / 160-edge pilot graph surface with the two excluded topics kept outside the graph and no `kc_to_kc` edges introduced.
- Kept the pass boundary-only: no Step 6.7 / 6.8 reruns, no topic or KC drafting work, no source-boundary rewrites, no UI or analytics work, and no `kc_specific_criteria` changes.

- Added the final six-topic manual-resolution bundle under `data/processed/topic_final_resolution_restarted/2026-04-01_172430/`, ingesting the user-supplied final approved wording for the six remaining model-evaluation topics into `reviewed_topic_library_resolved_final.jsonl`, `reviewed_topic_library_resolution_pending_final.csv`, `topic_review_boundary_consolidated_final.json`, `final_topic_resolution_manifest.json`, and `final_topic_resolution_report.md`.
- Closed the reviewed topic boundary from `16 resolved / 6 pending / 2 excluded` to `22 resolved / 0 pending / 2 excluded`, preserving `Clustering Concepts` and `Density-Based Clustering (DBSCAN)` as excluded rescue-heavy topics and keeping all KC artifacts, topic drafting code, Step 6.7 / 6.8 logic, and graph/downstream stages untouched.
- Left the pass boundary-only: no topic redrafting, no runtime candidate emission, and no widening beyond the six pending topics plus boundary recomputation.

- Added the narrow pending-topic resolution bundle under `data/processed/topic_pending_resolution_restarted/2026-04-01_170538/`, reopening only the 10 prior text-pending reviewed topics from `data/processed/topic_review_ingestion_reviewed_library_assembly_restarted/2026-04-01_162232/` against the repo-local filled reviewer sheet `data/review_inputs/topic_reviewer_sheet_filled.csv`.
- Emitted `reviewed_topic_library_resolved_updated.jsonl`, `reviewed_topic_library_resolution_pending_updated.csv`, `topic_review_boundary_consolidated_updated.json`, `topic_pending_resolution_analysis.csv`, `topic_pending_resolution_manifest.json`, and `topic_pending_resolution_report.md`, reducing the reviewed-topic boundary from `12 resolved / 10 pending / 2 excluded` to `16 resolved / 6 pending / 2 excluded`.
- Newly resolved `Classification Underpinnings`, `Decision Trees`, `Clustering`, and `Cluster Evaluation` from durable reviewer wording, while preserving the six model-evaluation-family truncation-limited topics as pending and keeping the two rescue-heavy clustering topics excluded; no KC artifacts, topic drafting outputs, Step 6.7 / 6.8 logic, or graph/downstream stages were touched.

- Added the approved-only KC library pilot packaging bundle under `data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/`, freezing the March 30 resolved reviewed subset into `approved_reviewed_library_frozen.jsonl`, packaging the pending/quarantined/hold boundary into compact manifests, and emitting the concise pilot packaging report.
- Added the approved-only retrieval package in the same bundle, creating a single `retrieval_index/` folder with the 67-record approved-only retrieval source, lexical index, query contract, and smoke-validation outputs while keeping `KC_FSEL_GEN_007`, the 15 quarantined/pre-screen cases, and the 45 holds outside the retrievable set.
- Left March 26 accepted baselines, March 28 to March 30 historical review artifacts, reviewer input CSVs, and all Step 6.7 through Step 6.14 logic untouched in this packaging-only pass.

- Added `CURRENT_ACTIVE_STATE.md` as the single compact repo-grounded pointer for the March 30 review boundary, the preserved March 26 accepted baseline, the major March 28 to March 30 evidence lineages, and the next stop point for `KC_FSEL_GEN_007`.
- Created `archive/repo_hygiene_2026-04-01/` and moved a very small set of non-authoritative root scratch/cache items there (`__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `_tmp_mineru_test/`, `tmp_test_add.txt`, `step6_7_hardening_stdout.log`, `step6_7_hardening_stderr.log`) without touching historical run artifacts.
- Left `Current.md` unchanged but explicitly superseded for post-2026-03-26 operational truth by `CURRENT_ACTIVE_STATE.md` plus the March 30 review-ingestion/assembly artifacts.

- Created `archive/repo_hygiene_2026-04-01_phase2/` and `archive/root_historical_reports_2026-04-01/`; archived the movable model cache and temp runtime trees (`data/hf_home_step6_4_2`, `test_runtime`) plus the listed root historical reports, while `.pytest_tmp` and `test_tmp_pytest` remained in place after access-denied move attempts. No pipeline logic changed and no reruns were executed.


## 2026-03-30

- Hardened Step 6.7 field stability in `src/kc_l/utils/kc_step67_model_drafting.py` and `run_step6_7_model_draft_generation.py` by allowing field-specific reference bundles, so definition protection can stay anchored to the corrected `2026-03-29_201853` draft set while scope protection can selectively preserve compatible grounded scope from the stronger `2026-03-29_135819` rerun.
- Tightened restarted Step 6.8 packet trust logic in `src/kc_l/kc/restarted_review_packets.py` so mixed foreign decisive definition provenance is explicitly flagged and capped out of `approve_ready` without blocking `review_needed` packets that still need human inspection.
- Extended regression coverage in `tests/test_step6_7_model_draft_generation_smoke.py` and `tests/test_step6_8_kc_review_packet_emission_smoke.py` for field-specific scope preservation, mixed-foreign decisive support downgrading, and local-only approve preservation.
- Added one-off configs `step6_7_full128_field_stability_approve_provenance_repair_2026-03-30.yaml` and `step6_8_full128_field_stability_approve_provenance_repair_2026-03-30.yaml`, reusing the existing Step 6.6 overlay `data/processed/kc_drafting_input_overlay/2026-03-28_195428/`.
- Emitted the fresh narrow reruns under `data/processed/kc_drafts/2026-03-29_231634/` and `data/processed/kc_review_packets_restarted/2026-03-30_004316/`, with matching audit trails under `data/runs/2026-03-29_231634_step6_7/` and `data/runs/2026-03-30_004316_step6_8/`.
- Tightened Step 6.7 definition-surface admissibility in `src/kc_l/utils/kc_step67_model_drafting.py` so metric-output rows, procedural headers, and contextual scaffold fragments are treated as unsafe definition surfaces during sibling-risk checks and single-span fallback selection instead of surviving as target definitions.
- Extended `tests/test_step6_7_model_draft_generation_smoke.py` with generic regression coverage for metric-output rejection, procedural-header rejection, contextual-scaffold rejection, unsafe reference-definition blocking, and safe local-definition preservation.
- Added one-off configs `step6_7_full128_definition_admissibility_repair_2026-03-30.yaml` and `step6_8_full128_definition_admissibility_repair_2026-03-30.yaml`, reusing the existing Step 6.6 overlay `data/processed/kc_drafting_input_overlay/2026-03-28_195428/`.
- Emitted the final narrow admissibility reruns under `data/processed/kc_drafts/2026-03-30_110313/` and `data/processed/kc_review_packets_restarted/2026-03-30_123558/`, with matching audit trails under `data/runs/2026-03-30_110313_step6_7/` and `data/runs/2026-03-30_123558_step6_8/`.

## 2026-03-29

- Hardened the Step 6.7 target-discriminative clause path in `src/kc_l/utils/kc_step67_model_drafting.py` so page-local completion can materialize the exact support rows it assembles, keep those rows visible to sibling-risk checks, and carry them forward into downstream evidence support instead of falling back to a weaker sibling-clause completion.
- Extended `tests/test_step6_7_model_draft_generation_smoke.py` with a focused completion-support visibility regression smoke test covering same-target clause completion when the confirming continuation row is initially outside the local candidate map.
- Added the one-off Step 6.8 config `step6_8_full128_target_discriminative_clause_repair_2026-03-29.yaml` and emitted the fresh narrow reruns under `data/processed/kc_drafts/2026-03-29_201853/` and `data/processed/kc_review_packets_restarted/2026-03-29_214643/`, with matching audit trails under `data/runs/2026-03-29_201853_step6_7/` and `data/runs/2026-03-29_214643_step6_8/`.
- Narrowed the model-backed Step 6.7 source-faithfulness hardening in `src/kc_l/utils/kc_step67_model_drafting.py` by preferring local duplicate definition evidence over foreign family-context copies, adding generic clause-completion recovery from adjacent local context, and tightening sibling-risk checks for unsafe foreign composite definitions.
- Extended `tests/test_step6_7_model_draft_generation_smoke.py` with generic regression coverage for local-over-foreign duplicate preference, deterministic clause-completion recovery, and fragment-only definition fallback protection.
- Added one-off configs `step6_7_full128_narrow_source_faithfulness_hardening_2026-03-29.yaml` and `step6_8_full128_narrow_source_faithfulness_hardening_2026-03-29.yaml`, reusing the fresh Step 6.6 overlay `data/processed/kc_drafting_input_overlay/2026-03-28_195428/` as the narrow rerun base.
- Emitted the narrow hardening evaluation artifacts under `data/processed/kc_drafts/2026-03-29_135819/` and `data/processed/kc_review_packets_restarted/2026-03-29_152348/`, with matching audit trails under `data/runs/2026-03-29_135819_step6_7/` and `data/runs/2026-03-29_152348_step6_8/`.

## 2026-03-26

- Added a bounded exchange-level KC matching pilot under `src/kc_l/kc/exchange_matching_pilot.py` and `steps/step_06_exchange_matching_pilot/`, wired to the accepted reviewed/runtime slice48 baseline plus the fixed `2026-03-26_174937` reviewed retrieval source/index.
- Added a narrow runner/config to emit synthetic pilot exchange units, top-k retrieval traces with retained evidence/provenance, assignment labels (`confident_single`, `confident_multi`, `ambiguous`, `no_match`), and a concise bounded-readiness assessment.

## 2026-03-27

- Added broader full-128 restarted scale-up configs at `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml`, `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml`, and `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml`, reusing the accepted March 26 repaired drafting path without changing Step 6.9+ logic.
- Emitted the broader restarted Step 6.6-6.8 outputs under `data/processed/kc_drafting_input_overlay/2026-03-27_112701/`, `data/processed/kc_drafts/2026-03-27_112751/`, and `data/processed/kc_review_packets_restarted/2026-03-27_112830/`, producing a full-128 overlay, 87 non-held draft bundles with 41 held cases, and an 87-packet broader review surface with 41 held exclusions.
- Added a broader human-review capture preparation bundle for data/processed/kc_review_packets_restarted/2026-03-27_112830/, creating neutral reviewer-session artifacts plus blank reviewer_dry_run_verdicts.json and human_supervised_draft_actions.json templates for all 87 ready packets while preserving 41 held exclusions and the human approval boundary.

- Hardened `src/kc_l/kc/draft_generation.py` for a quality-first full-128 redraft by adding all-assessed field selection, stricter generic rejection of OCR/citation/formula-garble definition surfaces, and reviewer-bundle blocking for evidence rows the definition verifier already classifies as noisy.
- Added focused regression coverage in `tests/test_step6_7_kc_draft_generation_full128_regression_smoke.py` and updated `tests/test_step6_7_kc_draft_generation_smoke.py` to match the new abstention-first Step 6.7 quality contract.
- Added one-off full-128 quality-redraft configs at `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128_quality_redraft_2026-03-27.yaml`, `steps/step_06_7_kc_draft_generation/resources/step6_7.full128_quality_redraft_2026-03-27.yaml`, and `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128_quality_redraft_2026-03-27.yaml`.
- Emitted the fresh full-128 quality-redraft artifacts under `data/processed/kc_drafting_input_overlay/2026-03-27_180547/`, `data/processed/kc_drafts/2026-03-27_180606/`, `data/processed/kc_review_packets_restarted/2026-03-27_180632/`, and the corresponding audit trails under `data/runs/2026-03-27_180547_step6_6/`, `data/runs/2026-03-27_180606_step6_7/`, and `data/runs/2026-03-27_180632_step6_8/`.

## 2026-03-28

- Added a real local-model Step 6.7 drafting path under `src/kc_l/utils/ollama_json.py`, `src/kc_l/utils/kc_step67_model_drafting.py`, and `run_step6_7_model_draft_generation.py`, introducing field-specific candidate harvesting, Ollama-backed multi-span definition/scope drafting, claim-level verification, and a Step 6.8-compatible evidence-bundle contract.
- Added full-128 rewrite configs at `step6_6_full128_model_rewrite_2026-03-27.yaml`, `step6_7_full128_model_rewrite_2026-03-27.yaml`, and `step6_8_full128_model_rewrite_2026-03-27.yaml`.
- Added model-rewrite smoke coverage in `tests/test_step6_7_model_draft_generation_smoke.py`, including watchlist candidate-harvest checks and a regression ensuring multi-span verified support ids are preserved in the emitted evidence bundle.
- Emitted the fresh rewrite-run artifacts under `data/processed/kc_drafting_input_overlay/2026-03-28_002110/`, `data/processed/kc_drafts/2026-03-28_002127/`, and `data/processed/kc_review_packets_restarted/2026-03-28_010335/`, with matching audit trails under `data/runs/2026-03-28_002110_step6_6/`, `data/runs/2026-03-28_002127_step6_7/`, and `data/runs/2026-03-28_010335_step6_8/`.
- Extended `src/kc_l/utils/kc_step67_model_drafting.py` for a scope/explanation redesign by adding stronger scope-side ranking, a dedicated scope redraft/verify path that drafts from verified definition context, and a conservative definition-redraft safeguard to preserve grounded definitions while scope improves.
- Updated `tests/test_step6_7_model_draft_generation_smoke.py` to cover the new scope-redraft recovery behavior and added the one-off scope-pass configs `step6_7_full128_scope_redesign_2026-03-28.yaml` and `step6_8_full128_scope_redesign_2026-03-28.yaml`.
- Emitted the fresh scope-pass Step 6.6 overlay under `data/processed/kc_drafting_input_overlay/2026-03-28_112853/` plus the first scope-redesign Step 6.7 audit run under `data/processed/kc_drafts/2026-03-28_112915/`, which improved scope recovery but exposed an unacceptable definition-regression tail.
- Emitted the corrected scope-pass artifacts under `data/processed/kc_drafts/2026-03-28_121329/` and `data/processed/kc_review_packets_restarted/2026-03-28_131326/`, with matching audit trails under `data/runs/2026-03-28_121329_step6_7/` and `data/runs/2026-03-28_131326_step6_8/`.
- Narrowed the Step 6.7 balance-repair path in `src/kc_l/utils/kc_step67_model_drafting.py` by adding definition-rescue ordering, a conservative single-span definition fallback, and tighter scope drafting/verification instructions for formula-based explanations without reopening the overall architecture.
- Hardened local Ollama JSON parsing in `src/kc_l/utils/ollama_json.py` so Step 6.7 can salvage otherwise-valid JSON objects that contain raw LaTeX-style backslashes, and extended `tests/test_step6_7_model_draft_generation_smoke.py` with fallback and parser-salvage coverage.
- Added one-off balance-pass configs `step6_7_full128_balance_repair_2026-03-28.yaml`, `step6_7_full128_balance_repair_retry_2026-03-28.yaml`, and `step6_8_full128_balance_repair_retry_2026-03-28.yaml`.
- Emitted the first balance-pass attempt under `data/processed/kc_drafting_input_overlay/2026-03-28_135409/`, `data/processed/kc_drafts/2026-03-28_135430/`, and its audit trail under `data/runs/2026-03-28_135409_step6_6/` and `data/runs/2026-03-28_135430_step6_7/`, then reran cleanly after the JSON-salvage hardening.
- Emitted the clean balance-pass artifacts under `data/processed/kc_drafting_input_overlay/2026-03-28_151048/`, `data/processed/kc_drafts/2026-03-28_151108/`, and `data/processed/kc_review_packets_restarted/2026-03-28_162024/`, with matching audit trails under `data/runs/2026-03-28_151048_step6_6/`, `data/runs/2026-03-28_151108_step6_7/`, and `data/runs/2026-03-28_162024_step6_8/`.
- Repaired the model-backed Step 6.7 path for source-faithfulness and sibling-boundary stability in `src/kc_l/utils/kc_step67_model_drafting.py` by adding generic same-family candidate harvesting, contrastive sibling-aware ranking/verification, and reference-field preservation against a prior grounded Step 6.7 set.
- Updated `run_step6_7_model_draft_generation.py` to accept an optional reference Step 6.7 set manifest and the new `family_context_limit` drafting knob, and extended `tests/test_step6_7_model_draft_generation_smoke.py` with family-context, sibling-boundary, and reference-scope-protection smoke coverage.
- Added one-off source-faithfulness repair configs `step6_6_full128_source_faithfulness_repair_2026-03-28.yaml`, `step6_7_full128_source_faithfulness_repair_2026-03-28.yaml`, and `step6_8_full128_source_faithfulness_repair_2026-03-28.yaml`.
- Emitted the fresh source-faithfulness repair artifacts under `data/processed/kc_drafting_input_overlay/2026-03-28_173232/`, `data/processed/kc_drafts/2026-03-28_173303/`, and `data/processed/kc_review_packets_restarted/2026-03-28_185648/`, with matching audit trails under `data/runs/2026-03-28_173232_step6_6/`, `data/runs/2026-03-28_173303_step6_7/`, and `data/runs/2026-03-28_185648_step6_8/`.
- Hardened the model-backed Step 6.7 source-faithfulness guard in `src/kc_l/utils/kc_step67_model_drafting.py` with generic heading/bibliography admissibility rejection, adjacent-block completion-context harvesting, stricter foreign-provenance fallback checks, and stronger sibling-boundary verification so nearby family concepts are less able to steal each other’s definitions.
- Updated `run_step6_7_model_draft_generation.py` to pass the new `completion_context_limit` policy knob, extended `tests/test_step6_7_model_draft_generation_smoke.py` with completion-context and foreign-fallback guard coverage, and added one-off configs `step6_6_full128_step67_hardening_2026-03-28.yaml`, `step6_7_full128_step67_hardening_2026-03-28.yaml`, `step6_8_full128_step67_hardening_2026-03-28.yaml`, `step6_7_full128_step67_hardening_source_guard_retry_2026-03-28.yaml`, and `step6_8_full128_step67_hardening_source_guard_retry_2026-03-28.yaml`.
- Emitted the fresh hardening/evaluation families under `data/processed/kc_drafting_input_overlay/2026-03-28_195428/`, `data/processed/kc_drafts/2026-03-28_213831/`, `data/processed/kc_review_packets_restarted/2026-03-28_234148/`, `data/processed/kc_drafts/2026-03-28_235151/`, and `data/processed/kc_review_packets_restarted/2026-03-29_013548/`, with matching audit trails under `data/runs/2026-03-28_195428_step6_6/`, `data/runs/2026-03-28_213831_step6_7/`, `data/runs/2026-03-28_235151_step6_7/`, `data/runs/2026-03-28_234148_step6_8/`, and `data/runs/2026-03-29_013548_step6_8/`.

## 2026-03-23

- Established the repo-wide changelog at `CHANGELOG.md`.
- Updated `AGENTS.md` so future repo edits must also update this changelog.
- Added restarted Step 6.8 bounded review-packet emission for Step 6.7 draft bundles, with a new clean packet adapter and runner under `steps/step_06_8_kc_review_packet_emission/`.
- Extended the review-packet schema additively for restarted packets to preserve `scope_draft`, explicit draft-gap metadata, and field-level provenance.
- Emitted the first bounded restarted packet set for the 10-KC slice, including 8 non-held packets and excluding the 2 legitimate held KCs.

## 2026-03-23
- Added restarted reviewer-session preparation support for the bounded Step 6.8 packet run.
- Created `src/kc_l/kc/restarted_reviewer_session.py` and `steps/step_06_8_kc_review_packet_emission/scripts/build_restarted_reviewer_session_artifacts.py` to build restarted-only reviewer-session artifacts from `data/processed/kc_review_packets_restarted/2026-03-23_003321/review_packet.jsonl`.
- Added `tests/test_restarted_reviewer_session_smoke.py`.
- Generated restarted `manual_inspection_bundle.md`, `real_reviewer_session.md`, and `real_reviewer_session_manifest.json` under `data/processed/kc_review_packets_restarted/2026-03-23_003321/`.

## 2026-03-23
- Added a restarted bounded human reviewer-pass builder under `src/kc_l/kc/restarted_human_review_pass.py` and `steps/step_06_review_supervision/scripts/build_restarted_human_reviewer_pass.py`.
- Added `tests/test_restarted_human_review_pass_smoke.py`.
- Generated restarted `reviewer_dry_run_verdicts.json`, `human_supervised_draft_actions.json`, and `human_supervised_workflow_validation.md` for the 8-packet restarted review slice under `data/processed/kc_review_packets_restarted/2026-03-23_003321/`.

## 2026-03-23
- Upgraded the review-audit contract to `step6.review_audit.v2` so restarted review events can preserve `scope`, packet text snapshots, field-linked evidence ids, scope status at review, and pending edit resolution state.
- Added restarted Step 6.9 review-audit ingestion under `src/kc_l/kc/restarted_review_audits.py` and `steps/step_06_9_kc_review_audit_ingestion/`.
- Added `tests/test_step6_9_restarted_review_audit_ingestion_smoke.py`.
- Emitted the first bounded restarted review-audit set for the 8-packet reviewer pass under `data/processed/kc_review_audits_restarted/2026-03-23_011446/`, with 1 approved audit event and 7 scope-aware `edit_pending` events, and no frozen-library assembly.

## 2026-03-23
- Broadened the scope-aware review-audit validator so `step6.review_audit.v2` can validate both pending edit events and finalized `edited_approved` edit resolutions.
- Added bounded restarted Step 6.10 review-audit resolution under `src/kc_l/kc/restarted_review_audit_resolution.py` and `steps/step_06_10_kc_review_audit_resolution/`.
- Added `tests/test_step6_10_restarted_review_audit_resolution_smoke.py`.
- Emitted the first bounded restarted resolved-review-audit set under `data/processed/kc_review_audits_restarted_resolved/2026-03-23_130601/`, finalizing the 7 `edit_pending` cases into `edited_approved` events while keeping `KC_CLF_DT_004.scope` intentionally blank and still avoiding any frozen-library assembly.

## 2026-03-23
- Added bounded restarted Step 6.11 reviewed-library assembly under `src/kc_l/kc/restarted_reviewed_library_assembly.py` and `steps/step_06_11_reviewed_library_assembly/`.
- Added `tests/test_step6_11_reviewed_library_assembly_smoke.py`.
- Emitted the first bounded restarted reviewed-library slice and sandbox slice from resolved restarted review outcomes only, preserving `KC_CLF_DT_004.scope` as intentionally blank and keeping the held exclusions out of the frozen reviewed library.

## 2026-03-23
- Added bounded restarted Step 6.12 reviewed-only runtime packaging under `src/kc_l/kc/restarted_runtime_packaging.py` and `steps/step_06_12_reviewed_library_runtime_packaging/`.
- Added `tests/test_step6_12_reviewed_library_runtime_packaging_smoke.py`.
- Emitted the first bounded restarted runtime package from the Step 6.11 frozen reviewed slice under `data/processed/kc_library_runtime_restarted/2026-03-23_134210/`.
- Added deterministic slice24 configs for restarted scaling under `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice24.yaml`, `steps/step_06_7_kc_draft_generation/resources/step6_7.slice24.yaml`, and `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice24.yaml`.
- Ran the restarted 24-KC automated scale-up through Step 6.8, producing overlay outputs in `data/processed/kc_drafting_input_overlay/2026-03-23_134259/`, draft outputs in `data/processed/kc_drafts/2026-03-23_134318/`, and restarted review packets in `data/processed/kc_review_packets_restarted/2026-03-23_134334/`.

## 2026-03-23
- Generalized restarted reviewer-session and restarted human-review pass wording so they no longer hardcode the original 8-packet / 2-held slice.
- Extended `src/kc_l/kc/restarted_human_review_pass.py` with a bounded 24-slice reviewer verdict plan covering 18 included restarted packets and 6 excluded held KCs.
- Added `tests/test_restarted_human_review_pass_slice24_smoke.py` for the restarted 24-packet human-review path.
- Generated restarted `manual_inspection_bundle.md`, `real_reviewer_session.md`, `real_reviewer_session_manifest.json`, `reviewer_dry_run_verdicts.json`, `human_supervised_draft_actions.json`, and `human_supervised_workflow_validation.md` for the 18-packet 24-KC restarted slice under `data/processed/kc_review_packets_restarted/2026-03-23_134334/`.

## 2026-03-23
- Extended restarted Step 6.9 review-audit ingestion so audit events preserve packet sufficiency, raw-internals usage, current risk flags, and source lineage back to Step 6.7 drafts and Step 6.8 restarted packets.
- Added `steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice24.yaml`.
- Added `tests/test_step6_9_restarted_review_audit_ingestion_slice24_smoke.py` and expanded the existing Step 6.9 smoke test for the new lineage fields and counts.
- Emitted the restarted 24-slice review-audit set under `data/processed/kc_review_audits_restarted/2026-03-23_142755/` with 18 ingested events, 2 approved, 11 edit-pending, 5 rejected, and 6 explicit excluded held cases preserved in summary/preview outputs.

## 2026-03-23
- Extended restarted Step 6.10 resolution reporting so resolved summaries and set manifests keep rejected KCs explicit alongside approved and edited-approved outcomes.
- Added `steps/step_06_10_kc_review_audit_resolution/resources/step6_10.slice24.yaml`.
- Added `tests/test_step6_10_restarted_review_audit_resolution_slice24_smoke.py`.
- Emitted the restarted 24-slice resolved review-audit set under `data/processed/kc_review_audits_restarted_resolved/2026-03-23_143932/` with 2 approved, 11 edited-approved, 5 rejected, no unresolved edits, and 3 intentionally blank final fields preserved.

## 2026-03-23
- Extended restarted Step 6.11 assembly so the sandbox now preserves both rejected review outcomes and excluded-held KCs, while the frozen reviewed slice still includes only `approved` and `edited_approved`.
- Added `steps/step_06_11_reviewed_library_assembly/resources/step6_11.slice24.yaml`.
- Added `tests/test_step6_11_reviewed_library_assembly_slice24_smoke.py` and expanded the existing Step 6.11 smoke assertions for the new sandbox breakdown fields.
- Emitted the restarted 24-slice reviewed-library and sandbox slices under `data/processed/kc_library_reviewed_restarted/2026-03-23_145442/` and `data/processed/kc_review_sandbox_restarted/2026-03-23_145442/`, with 13 frozen reviewed entries, 5 rejected sandbox entries, and 6 excluded-held sandbox entries.

## 2026-03-23
- Added restarted Step 6.12 slice24 config at `steps/step_06_12_reviewed_library_runtime_packaging/resources/step6_12.slice24.yaml`.
- Extended restarted runtime-package summaries and manifests to make preserved intentional blanks and sandbox exclusion explicit.
- Added `tests/test_step6_12_reviewed_library_runtime_packaging_slice24_smoke.py` and expanded the existing Step 6.12 smoke assertions for the new summary fields.
- Emitted the restarted 24-slice runtime package under `data/processed/kc_library_runtime_restarted/2026-03-23_150120/`, with 13 runtime entries, sandbox excluded by construction, and 3 intentionally blank scope fields preserved.
- Added deterministic slice48 configs at `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.slice48.yaml`, `steps/step_06_7_kc_draft_generation/resources/step6_7.slice48.yaml`, and `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice48.yaml`, extending the validated 24-KC restarted slice with the next 24 registry-order KCs.
- Emitted the restarted 48-slice automated outputs under `data/processed/kc_drafting_input_overlay/2026-03-23_150909/`, `data/processed/kc_drafts/2026-03-23_150927/`, and `data/processed/kc_review_packets_restarted/2026-03-23_150950/`, with 48 overlayed KCs, 37 non-held draft packets, and 11 explicit held exclusions.
- Extended `src/kc_l/kc/restarted_human_review_pass.py` for the restarted 48-slice reviewer plan, added `tests/test_restarted_human_review_pass_slice48_smoke.py`, and emitted restarted `manual_inspection_bundle.md`, `real_reviewer_session.md`, `real_reviewer_session_manifest.json`, `reviewer_dry_run_verdicts.json`, `human_supervised_draft_actions.json`, and `human_supervised_workflow_validation.md` under `data/processed/kc_review_packets_restarted/2026-03-23_150950/`, preserving all 11 held KCs as exclusions.

## 2026-03-23
- Extended restarted Step 6.9 edit-field planning and Step 6.10 final-text capture planning for the new 48-slice edit cases across evaluation and Naive Bayes KCs.
- Added `steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice48.yaml`, `steps/step_06_10_kc_review_audit_resolution/resources/step6_10.slice48.yaml`, `steps/step_06_11_reviewed_library_assembly/resources/step6_11.slice48.yaml`, and `steps/step_06_12_reviewed_library_runtime_packaging/resources/step6_12.slice48.yaml`.
- Emitted the restarted 48-slice Step 6.9 review-audit set under `data/processed/kc_review_audits_restarted/2026-03-23_154431/` with 37 audit events, 2 approved, 22 edit-pending, 13 rejected, and 11 held exclusions preserved explicitly.
- Emitted the restarted 48-slice Step 6.10 resolved review-audit set under `data/processed/kc_review_audits_restarted_resolved/2026-03-23_154457/` with 2 approved, 22 edited-approved, 13 rejected, no unresolved edits, and 6 intentionally blank final scope fields preserved.
- Emitted the restarted 48-slice Step 6.11 reviewed-library and sandbox slices under `data/processed/kc_library_reviewed_restarted/2026-03-23_154525/` and `data/processed/kc_review_sandbox_restarted/2026-03-23_154525/`, with 24 frozen reviewed entries and a 24-entry sandbox split into 13 rejected plus 11 excluded-held cases.
- Emitted the restarted 48-slice Step 6.12 runtime package under `data/processed/kc_library_runtime_restarted/2026-03-23_154556/`, with 24 reviewed-only runtime entries, 6 intentionally blank scope fields preserved, and sandbox excluded by construction.
- Added slice48 smoke tests for restarted Steps 6.9, 6.10, 6.11, and 6.12 in `tests/test_step6_9_restarted_review_audit_ingestion_slice48_smoke.py`, `tests/test_step6_10_restarted_review_audit_resolution_slice48_smoke.py`, `tests/test_step6_11_reviewed_library_assembly_slice48_smoke.py`, and `tests/test_step6_12_reviewed_library_runtime_packaging_slice48_smoke.py`.

## 2026-03-23
- Added a bounded Step 6.7 evaluation-family guard in src/kc_l/kc/draft_generation.py so Model Evaluation and Model Comparison KCs no longer treat unanchored DM2_Evaluation_Unit_2_Bestmodel significance-test or error-rate background text as ready drafting support.
- Added focused smoke coverage in 	ests/test_step6_7_kc_draft_generation_eval_family_smoke.py and the bounded rerun config steps/step_06_7_kc_draft_generation/resources/step6_7.eval_model_comparison_sandbox10.yaml.
- Emitted the bounded 10-KC Step 6.7 rerun under data/processed/kc_drafts/2026-03-23_170231/, shifting the evaluation subset to 3 draft-ready, 2 draft-ready-with-holds, and 5 held cases.
- Added steps/step_06_8_kc_review_packet_emission/resources/step6_8.eval_model_comparison_sandbox10.yaml and emitted the matched Step 6.8 rerun under data/processed/kc_review_packets_restarted/2026-03-23_170249/, reducing the affected ready packet set from 6 packets to 5 and pushing one previously bad packet surface back to held/excluded.

## 2026-03-24


- Extended `src/kc_l/kc/restarted_review_audits.py` and `src/kc_l/kc/restarted_review_audit_resolution.py` so the restarted 48-slice downstream closure can carry the new 32-packet surface from `data/processed/kc_review_packets_restarted/2026-03-24_150915/`, including the newly recovered evaluation-family edit cases.
- Repointed the restarted slice48 downstream configs `steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice48.yaml`, `steps/step_06_10_kc_review_audit_resolution/resources/step6_10.slice48.yaml`, `steps/step_06_11_reviewed_library_assembly/resources/step6_11.slice48.yaml`, and `steps/step_06_12_reviewed_library_runtime_packaging/resources/step6_12.slice48.yaml` to the new 32-packet review and reviewed-library manifests.
- Emitted the restarted 48-slice Step 6.9 review-audit set under `data/processed/kc_review_audits_restarted/2026-03-24_164536/` with 32 audit events, 2 approved, 22 edit-pending, 8 rejected, and 16 held exclusions preserved explicitly.
- Emitted the restarted 48-slice Step 6.10 resolved review-audit set under `data/processed/kc_review_audits_restarted_resolved/2026-03-24_164616/` with 2 approved, 22 edited-approved, 8 rejected, no unresolved edits, and 7 intentionally blank final scope fields preserved.
- Emitted the restarted 48-slice Step 6.11 reviewed-library and sandbox slices under `data/processed/kc_library_reviewed_restarted/2026-03-24_164654/` and `data/processed/kc_review_sandbox_restarted/2026-03-24_164654/`, with 24 frozen reviewed entries and a 24-entry sandbox split into 8 rejected plus 16 excluded-held cases.
- Emitted the restarted 48-slice Step 6.12 runtime package under `data/processed/kc_library_runtime_restarted/2026-03-24_165020/`, with 24 reviewed-only runtime entries, 7 intentionally blank scope fields preserved, sandbox excluded by construction, and `KC_CLF_DT_011` absent from both frozen reviewed and runtime outputs.

- Repaired the restarted 48-slice human-review plan in `src/kc_l/kc/restarted_human_review_pass.py` for the new 32-packet packet set `data/processed/kc_review_packets_restarted/2026-03-24_150915/`, including the explicit `KC_CLF_DT_011` spot-check and the newly recovered evaluation-family packets.
- Emitted fresh restarted reviewer-session artifacts and human-review outputs under `data/processed/kc_review_packets_restarted/2026-03-24_150915/`, with 32 packet-only reviewer decisions (`2` approve / `22` edit / `8` reject) and no raw-internals reopen required.
- Calibrated the generic Step 6.7 drafting policy in `src/kc_l/kc/draft_generation.py` so strong concept anchors can survive moderate background drift only through generic positive surfaces, with a soft drift penalty instead of a source-name-specific hard block.
- Broadened the generic `anchored_descriptive_clause` handling for strong anchored descriptive rows and expanded `tests/test_step6_7_kc_draft_generation_eval_family_smoke.py` to assert the generic Majority Voting and Holdout outcomes without relying on DM2 unit-name logic.
- Repointed `steps/step_06_8_kc_review_packet_emission/resources/step6_8.eval_model_comparison_sandbox10.yaml` to the new bounded Step 6.7 set `2026-03-24_140345_step6_7_kc_drafts_set.json`.
- Emitted the calibrated affected-subset reruns under `data/processed/kc_drafts/2026-03-24_140345/` and `data/processed/kc_review_packets_restarted/2026-03-24_140405/`, moving the evaluation subset to 2 `draft_ready_with_holds` packets (`KC_EVAL_ENS_002`, `KC_EVAL_SAMP_001`) and 8 held/excluded cases without reintroducing DM2-specific unit-name guards.
- Replaced the three DM2/unit-name-specific Step 6.7 evaluation-family drift guards in `src/kc_l/kc/draft_generation.py` with one generic drafting-policy helper built from row-level `anchor_strength`, `background_drift_class`, and `concept_mix_risk` features.
- Expanded `tests/test_step6_7_kc_draft_generation_eval_family_smoke.py` so the bounded evaluation-family regression now asserts generic policy behavior even when the source `doc_id` is changed, and added coverage for the symmetric-distribution theorem/statistics drift row.
- Repointed `steps/step_06_8_kc_review_packet_emission/resources/step6_8.eval_model_comparison_sandbox10.yaml` to the new bounded Step 6.7 set `2026-03-24_131521_step6_7_kc_drafts_set.json`.
- Emitted the generic-policy bounded reruns under `data/processed/kc_drafts/2026-03-24_131521/` and `data/processed/kc_review_packets_restarted/2026-03-24_131542/`, tightening the affected 10-KC evaluation subset to 1 `draft_ready_with_holds` packet (`KC_EVAL_SAMP_001`) and 9 held/excluded cases without relying on DM2 unit-name logic.
- Added one more bounded Step 6.7 evaluation-family guard in `src/kc_l/kc/draft_generation.py` so `DM2_Evaluation_Unit_1_Basics` generic recap rows and mixed concept-heading rows no longer qualify as drafting support for Model Evaluation and Model Comparison KCs unless they stay tightly anchored to the target concept.
- Expanded `tests/test_step6_7_kc_draft_generation_eval_family_smoke.py` to cover the new basics-doc drift cases while preserving the good Holdout surface.
- Repointed `steps/step_06_8_kc_review_packet_emission/resources/step6_8.eval_model_comparison_sandbox10.yaml` to the new bounded Step 6.7 rerun set `2026-03-24_121529_step6_7_kc_drafts_set.json`.
- Emitted the new bounded 10-KC reruns under `data/processed/kc_drafts/2026-03-24_121529/` and `data/processed/kc_review_packets_restarted/2026-03-24_121557/`, shifting the evaluation subset to 3 draft-ready, 1 draft-ready-with-holds, 6 held, and 4 ready packets after blocking additional basics-doc drift.

- Added one more bounded Step 6.7 evaluation-family guard in `src/kc_l/kc/draft_generation.py` so `DM2_Evaluation_Unit_2_Bestmodel` theorem/statistics and classifier-comparison background rows no longer qualify as drafting support for Model Evaluation and Model Comparison KCs unless they contain a real concept-name anchor in the surface text.
- Expanded `tests/test_step6_7_kc_draft_generation_eval_family_smoke.py` to cover the new `Bestmodel` drift cases.
- Repointed `steps/step_06_8_kc_review_packet_emission/resources/step6_8.eval_model_comparison_sandbox10.yaml` to the new bounded Step 6.7 rerun set `2026-03-24_123919_step6_7_kc_drafts_set.json`.
- Emitted the new bounded 10-KC reruns under `data/processed/kc_drafts/2026-03-24_123919/` and `data/processed/kc_review_packets_restarted/2026-03-24_123946/`, shifting the evaluation subset to 1 draft-ready, 1 draft-ready-with-holds, 8 held, and 2 ready packets after blocking the remaining `Bestmodel` theorem/statistics drift.
- Added a generic row-internal target-segment extraction path in `src/kc_l/kc/draft_generation.py` so strongly anchored paired-metric rows and mixed concept-list rows can yield target-only support segments before Step 6.7 surface classification, without any Data Mining/source-unit-specific guards.
- Expanded `tests/test_step6_7_kc_draft_generation_eval_family_smoke.py` to cover the new generic paired-metric and mixed-clause recoveries for Recall/Sensitivity, Specificity, and Random Forest while keeping the bad evaluation-background rows blocked.
- Repointed `steps/step_06_8_kc_review_packet_emission/resources/step6_8.eval_model_comparison_sandbox10.yaml` to the new bounded Step 6.7 set `2026-03-24_150107_step6_7_kc_drafts_set.json`.
- Emitted the final bounded subset reruns under `data/processed/kc_drafts/2026-03-24_150107/` and `data/processed/kc_review_packets_restarted/2026-03-24_150124/`, moving the evaluation-family sandbox10 subset to 5 `draft_ready_with_holds` packets (`KC_EVAL_BASIC_004`, `KC_EVAL_BASIC_005`, `KC_EVAL_ENS_002`, `KC_EVAL_ENS_003`, `KC_EVAL_SAMP_001`) and 5 held/excluded cases.
- Repointed the full-48 restarted slice configs `steps/step_06_7_kc_draft_generation/resources/step6_7.slice48.yaml` and `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice48.yaml` to the new full-48 rerun manifests `2026-03-24_150835_step6_6_kc_drafting_input_overlay_set.json` and `2026-03-24_150855_step6_7_kc_drafts_set.json`.
- Emitted the full restarted 48-slice automated validation reruns under `data/processed/kc_drafting_input_overlay/2026-03-24_150835/`, `data/processed/kc_drafts/2026-03-24_150855/`, and `data/processed/kc_review_packets_restarted/2026-03-24_150915/`, with 849 overlay records, 32 non-held packets, and 16 held exclusions after the generic Step 6.7 policy calibration.
- Added the bounded reviewed-only retrieval pilot module `src/kc_l/kc/restarted_retrieval_pilot.py` and the new stage wrapper/config `steps/step_06_13_reviewed_library_retrieval_pilot/scripts/run_step6_13_reviewed_library_retrieval_pilot.py` plus `steps/step_06_13_reviewed_library_retrieval_pilot/resources/step6_13.slice48.yaml`, reusing only the repaired Step 6.11 frozen reviewed slice and Step 6.12 runtime lineage.
- Emitted the reviewed-only retrieval pilot artifacts under `data/processed/kc_library_retrieval_pilot_restarted/2026-03-24_183415/`, including a 24-record normalized retrieval source, a lexical reviewed-only retrieval index, the explicit query contract, the 10-query tiny validation set/results, and the pilot assessment report.
- Emitted the Step 6.13 audit trail under `data/runs/2026-03-24_183415_step6_13/` and the three set manifests under `data/processed/kc_library_retrieval_pilot_restarted/_sets/`, with sandbox excluded by construction, `KC_CLF_DT_011` absent from the pilot source/index, and validation landing at 7 top-1 hits and 9 top-3 hits.
- Added the bounded repaired-slice48 packet-failure audit extractor `src/kc_l/kc/restarted_packet_failure_audit.py` and the new stage wrapper/config `steps/step_06_14_kc_packet_failure_audit/scripts/run_step6_14_kc_packet_failure_audit.py` plus `steps/step_06_14_kc_packet_failure_audit/resources/step6_14.slice48.yaml`.
- Emitted the repaired-slice48 packet-failure audit bundle under `data/processed/kc_packet_failure_audit_restarted/2026-03-25_220053/`, including a 48-row packet cohort registry, a 46-row non-clean packet failure matrix, 10 representative dossiers, and a concise aggregate audit report.
- Emitted the Step 6.14 audit trail under `data/runs/2026-03-25_220053_step6_14/` and the four set manifests under `data/processed/kc_packet_failure_audit_restarted/_sets/`, preserving the repaired slice48 outcome counts exactly (`2` approved, `22` edited-approved, `8` rejected, `16` excluded-held) with explicit `KC_CLF_DT_011` tracing across registry, matrix, and dossier outputs.

## 2026-03-26
- Added deterministic reviewed-source alias and lexical expansion in `src/kc_l/kc/restarted_retrieval_pilot.py` plus the one-off replay config `steps/step_06_13_reviewed_library_retrieval_pilot/resources/step6_13.slice48_alias_improvement_2026-03-26_154319.yaml`, using only accepted title, structure-path, and reviewed-text fields.
- Emitted the alias-improved Step 6.13 replay under `data/processed/kc_retrieval_alias_improvement_restarted/2026-03-26_174937/` and `data/runs/2026-03-26_174937_step6_13/`, producing a 24-record alias-enriched reviewed retrieval source, a refreshed lexical index, and same-slice validation at `9` top-1 hits and `9` top-3 hits.
- Emitted the comparison and assessment bundle under `data/processed/kc_retrieval_alias_improvement_restarted/2026-03-26_174937/` plus two new set manifests under `data/processed/kc_retrieval_alias_improvement_restarted/_sets/`, showing `Q08` and `Q09` improved to top-1 hits with no top-3 regression and `Q10` remaining the only miss.
- Tightened Step 6.7 drafting generically in `src/kc_l/kc/draft_generation.py` so reviewer-facing definitions now use a second-stage surfaced-definition chooser, block fragment/background/heading-like non-definitions, and stop auto-copying weak definition text into scope.
- Added one-off Step 6.8 rerun configs at `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice48_patchrun_2026-03-26_103441.yaml` and `steps/step_06_8_kc_review_packet_emission/resources/step6_8.slice48_patchrun_2026-03-26_103746.yaml` for bounded repaired-slice48 reruns.
- Emitted the final bounded repaired-slice48 reruns under `data/processed/kc_drafts/2026-03-26_103746/` and `data/processed/kc_review_packets_restarted/2026-03-26_103801/`, plus the sentinel comparison bundle under `data/processed/kc_step6_7_patch_comparison_restarted/2026-03-26_104018/`.
- Added a bounded review-refresh bundle under `data/processed/kc_review_packets_restarted/2026-03-26_114721/` for the new 29-packet repaired slice48 surface, including `packet_delta_registry.json`, refreshed `human_supervised_draft_actions.json`, refreshed `reviewer_dry_run_verdicts.json`, `manual_review_shortlist.md`, `human_supervised_workflow_validation.md`, `real_reviewer_session.md`, `real_reviewer_session_manifest.json`, and `review_refresh_summary.json`.
- Carried forward 21 materially stable prior human decisions from `2026-03-24_150915`, flagged 8 current packets for manual re-review, and kept 3 newly held former packets outside the ready review session pending manual confirmation.
- Added one-off replay config `steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice48_replay_2026-03-26_114721.yaml` for downstream replay from the finalized 29-packet Step 6.8 surface `2026-03-26_114721`.
- Attempted the mechanical Step 6.9 replay from the finalized review bundle, but the run stopped immediately because `src/kc_l/kc/restarted_review_audits.py` is missing `EDIT_FIELD_PLAN` entries for the newly editable replay cases `KC_CLF_DT_005` and `KC_CLF_DT_011`.
- Added bounded generic replay fallbacks in `src/kc_l/kc/restarted_review_audits.py` and `src/kc_l/kc/restarted_review_audit_resolution.py` so missing KC-specific edit plans now finalize from the existing restarted packet surface instead of blocking the mechanical 29-packet replay.
- Added one-off downstream replay configs `steps/step_06_10_kc_review_audit_resolution/resources/step6_10.slice48_replay_2026-03-26_114721.yaml`, `steps/step_06_11_reviewed_library_assembly/resources/step6_11.slice48_replay_2026-03-26_114721.yaml`, `steps/step_06_12_reviewed_library_runtime_packaging/resources/step6_12.slice48_replay_2026-03-26_114721.yaml`, `steps/step_06_13_reviewed_library_retrieval_pilot/resources/step6_13.slice48_replay_2026-03-26_114721.yaml`, and `steps/step_06_14_kc_packet_failure_audit/resources/step6_14.slice48_replay_2026-03-26_114721.yaml`.
- Emitted the finalized replayed downstream artifacts under `data/processed/kc_review_audits_restarted/2026-03-26_153809/`, `data/processed/kc_review_audits_restarted_resolved/2026-03-26_153957/`, `data/processed/kc_library_reviewed_restarted/2026-03-26_154021/`, `data/processed/kc_review_sandbox_restarted/2026-03-26_154021/`, `data/processed/kc_library_runtime_restarted/2026-03-26_154046/`, `data/processed/kc_library_retrieval_pilot_restarted/2026-03-26_154319/`, and `data/processed/kc_packet_failure_audit_restarted/2026-03-26_154357/`.
- Completed the repaired slice48 downstream closure mechanically with counts preserved at `2` approved, `22` edited-approved, `5` rejected, `19` excluded-held, `24` frozen reviewed entries, `24` sandbox entries, `24` runtime entries, and `24` reviewed-only retrieval records while keeping sandbox excluded by construction.
- Added a bounded retrieval ambiguity diagnosis bundle under `data/processed/kc_retrieval_ambiguity_diagnosis_restarted/2026-03-26_171102/` from the accepted reviewed/runtime slice48 baseline (`2026-03-26_154021` / `2026-03-26_154046` / `2026-03-26_154319` / `2026-03-26_154357`).
- Emitted `retrieval_ambiguity_registry.jsonl`, `query_to_document_trace_bundle.md/json`, `reviewed_record_sparsity_alias_audit.jsonl`, `retrieval_ambiguity_diagnosis_report.md`, and the four corresponding set manifests under `data/processed/kc_retrieval_ambiguity_diagnosis_restarted/_sets/`.
- The diagnosis found sibling/family lexical collision to be the dominant ambiguity source on the accepted reviewed-only slice, with zero alias expansion across all 24 reviewed retrieval records and no extra diagnostic queries required.


## 2026-03-30
- Added a bounded pilot review-preparation bundle under `data/processed/kc_review_pilot_preparation_restarted/2026-03-30_163443/`, derived from the quarantined latest Step 6.8 surface `data/processed/kc_review_packets_restarted/2026-03-30_123558/` and its paired draft/overlay artifacts without modifying any historical run outputs.
- Emitted `pilot_packet_dossier.md`, `pilot_reviewer_sheet.csv`, `pilot_summary_note.md`, and `pilot_review_manifest.json` for a 20-packet stratified expert-review pilot consisting of 8 Tier 1 packets, 10 Tier 2 packets, and 2 explicit borderline Tier 2 burden probes.
- Added blinded reviewer-facing copies in the same pilot-prep folder: `pilot_packet_dossier_blinded.md`, `pilot_reviewer_sheet_blinded.csv`, and `pilot_summary_note_blinded.md`, preserving the keyed/internal pilot artifacts unchanged while removing tiering and machine-recommendation fields from the reviewer-facing versions.
- Added the pilot review ingestion and next-batch preparation bundle under `data/processed/kc_review_pilot_ingestion_next_batch_restarted/2026-03-30_172157/`, ingesting the filled reviewer input `data/review_inputs/pilot_reviewer_sheet_filled_2026-03-30.csv` into normalized/joined analysis artifacts plus a concise pilot results report and burden summary.
- Emitted the next bounded safe-surface review batch in the same folder with keyed and blinded dossiers, keyed and blinded reviewer sheets, a next-batch manifest, and keyed/blinded summary notes for a 20-packet post-pilot review batch drawn from the remaining non-quarantined surface without modifying any historical Step 6.7/6.8 artifacts.
- Added the lean batch 2 ingestion and remaining-review-preparation bundle under `data/processed/kc_review_batch2_ingestion_remaining_review_restarted/2026-03-30_174915/`, ingesting `data/review_inputs/second_batch_reviewer_sheet_filled.csv` into normalized and joined batch 2 review outputs plus a concise batch 2 results report.
- Added `operational_quarantine_update.md` and `operational_quarantine_update.json` in the same folder, recording `KC_CLF_DT_007` as newly quarantined for future normal review batching and `KC_EVAL_IMBAL_004` as manual pre-screen only, then emitted the blinded consolidated remaining safe-review wave pack (`remaining_review_manifest.json`, blinded dossier, blinded reviewer sheet, blinded reviewer note) for the 31 unreviewed safe packets.
- Added the final review ingestion and reviewed-library assembly bundle under `data/processed/kc_review_final_ingestion_reviewed_library_assembly_restarted/2026-03-30_184413/`, ingesting the completed remaining-wave reviewer input `data/review_inputs/remaining_review_reviewer_sheet_filled.csv` into normalized/joined remaining-wave review outputs plus consolidated 71-case review results across the pilot, batch 2, and remaining waves.
- Emitted the reviewed-library boundary artifacts in the same folder: `reviewed_library_resolved.jsonl` for 67 fully resolved reviewed entries, `reviewed_library_resolution_pending.csv` for the single edit-approved text-pending case `KC_FSEL_GEN_007`, `review_boundary_consolidated.json` for the full 128-KC boundary split, `reviewed_library_assembly_report.md`, and a `reviewed_runtime_candidate.jsonl` over the resolved reviewed subset only.




- Ran a bounded operator smoke-test pass, tightened `src/kc_l/runtime/operator_stages.py` so input-root guidance files do not count as real course materials or hierarchy inputs, and verified the public stage preflights still block for the correct empty-state reasons.
- Added first-use guidance files in `data/input/course_materials/README.md` and `data/input/hierarchy/README.md` plus `docs/examples/minimal_hierarchy.template.yaml` so a first run can be staged without reintroducing live-input clutter.
- Expanded the operator smoke tests in `tests/test_operator_layout.py` and `tests/test_cli_surfaces.py` to cover empty-state input counts and the expected review/freeze preflight blocking behavior.
## 2026-04-01
- Added a bounded topic-library drafting path in `src/kc_l/topic/__init__.py`, `src/kc_l/topic/minimal_draft.py`, and `steps/step_01_6_topic_library_draft/scripts/run_step01_6_topic_library_draft.py`, keeping topic objects separate from the approved KC library and leaving all March 30 / April 1 KC artifacts read-only.
- Emitted the slide-grounded topic draft bundle under `data/processed/topic_library_draft_restarted/2026-04-01_143108/`, including `topic_schema_minimal.json`, `topic_schema_rationale.md`, `topic_drafts.jsonl`, `topic_draft_manifest.json`, `topic_draft_report.md`, `topic_to_kc_link_candidates.jsonl`, and `knowledge_library_naming_note.md`.
- Drafted all 24 hierarchy topic nodes from the active seven-document slide corpus with 5 grounded definitions, 19 scope-only topic drafts, one explicit hierarchy/source ambiguity (`Statistical Testing`), and no changes to the approved reviewed KC boundary or Step 6.7 / 6.8 outputs.
- Added the quality-first topic redraft runner at `steps/step_01_6_topic_library_draft/scripts/run_step01_6_topic_library_quality_redraft.py`, using local Ollama-backed drafting for topic definitions and scope/role while keeping hierarchy fields deterministic and all KC artifacts read-only.
- Emitted the quality-first topic draft bundle under `data/processed/topic_library_draft_restarted/2026-04-01_152415/`, producing 24 topic drafts with 11 grounded definitions, 13 scope-only drafts, 0 title-only weak drafts, explicit `Statistical Testing` mismatch flagging, and a comparison report against `2026-04-01_143108`.
- Added the lean topic-review preparation bundle under `data/processed/topic_review_preparation_restarted/2026-04-01_155429/`, packaging the active `2026-04-01_152415` Topic Library draft candidate into keyed and blinded dossiers, keyed and blinded reviewer sheets, keyed and blinded summary notes, and a review-pack manifest for 24 topic sanity-review cases.
- Kept the topic draft bundle and the approved KC package read-only during this packaging pass, preserved Topic/KC separation, and avoided any Step 6.7 / 6.8 reruns, topic redrafting, graph work, or downstream pipeline changes.
- Added the topic review ingestion and reviewed-topic-library assembly bundle under `data/processed/topic_review_ingestion_reviewed_library_assembly_restarted/2026-04-01_162232/`, ingesting the filled external reviewer sheet `r:\Downloads\topic_reviewer_sheet_filled.csv` plus the pasted full expert topic review into normalized/joined analysis artifacts, a conservative reviewed-topic boundary split, a 12-topic resolved reviewed subset, and a 10-pending / 2-excluded assembly report without modifying any KC artifacts or topic drafting outputs.




















