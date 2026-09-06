from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Fine-grained, one-runner-script-per-stage table matching the data/processed/runs/<run_id>/
# <stage>/ run-folder convention exactly. This is deliberately finer-grained than
# configs/kc_l_pipeline_registry.v2.json's 17 stage_nodes, several of which bundle multiple
# distinct runner scripts under one node (e.g. its "step_02_extraction" node covers step2,
# step3, step3.5, and step3.6 together; "expert_review_resolution" covers step 6.9+6.10).
# `registry_stage_id` cross-references that coarser node for traceability - the JSON registry
# and scripts/kc_l_orchestrator.py's existing status/graph/pointers-validate commands are left
# untouched and keep reading it directly.

Invocation = Literal["cli_args", "config_yaml", "unconfirmed"]


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    registry_stage_id: str | None
    order: int
    depends_on: tuple[str, ...]
    script_path: str | None
    invocation: Invocation
    needs_ollama: bool
    output_root: str | None
    # For invocation="config_yaml": the base resource yaml this stage's config is rendered
    # from, and the specific "inputs"/"outputs" override key names confirmed by this
    # session's audit (not uniform across stages - see notes on step_06_6/6_11/6_13).
    base_config_path: str | None = None
    input_override_keys: tuple[str, ...] = ()
    output_override_keys: tuple[str, ...] = ()
    # For invocation="cli_args": the confirmed CLI flags this script accepts (informational;
    # Milestone 3 fills in actual values per run_id).
    cli_flags: tuple[str, ...] = ()
    cli_flags_confirmed: bool = True
    # ACTIVE_*/BEST_* pointer this stage reads and/or writes, resolvable via
    # kc_l.runtime.stage_pointers.resolve_pointer(). pointer_key is only set for the
    # multi-line KEY=VALUE closeout format (see stage_pointers.resolve_pointer docstring).
    active_pointer_path: str | None = None
    active_pointer_key: str | None = None
    notes: str = ""
    manifest_count: int = 1
    # Whether run-stage's upstream-input-resolution logic is actually wired for this stage
    # (as opposed to just having a confirmed script/CLI contract). Distinct from
    # is_confirmed(): a stage can have fully confirmed CLI flags/config keys yet still have
    # no known/built mechanism for resolving what its upstream dependency's output artifact
    # actually is (e.g. step_06_7_kc_draft_generation's real --plan-json/--selected-packets-
    # jsonl come from step_06_7_hierarchy_aware_synthesis_packets, which is confirmed but not
    # yet wired into run-stage). Defaults to False - run-stage must refuse rather than guess
    # for any stage not explicitly marked True here.
    run_stage_wired: bool = False
    # 2026-07-16: True for a stage whose real input requires a completed HUMAN action outside
    # this pipeline's own automation (e.g. step_06_9_review_audit_ingestion reads
    # reviewer_dry_run_verdicts.json - a human reviewer's actual verdicts, confirmed by reading
    # emit_restarted_review_audits() directly - not something that exists the instant its
    # upstream stage completes). kc_l.runtime.chain.resolve_ready_stages() excludes such stages
    # from the automatic self-chain permanently (not just "not yet ready" - "not machine-
    # resolvable at all"), so a run's self-chain naturally stops at the last stage before one of
    # these, with no --no-self-chain flag needed anywhere in the actual chain to enforce it.
    # Reported under RUN_STATE.json's "ready_pending_human_review" (see submit_ready_stages())
    # so a human/console-UI can explicitly trigger it once real review input exists.
    human_review_gate: bool = False


STAGE_SPECS: dict[str, StageSpec] = {
    "step_02_pdf_ingest": StageSpec(
        stage_id="step_02_pdf_ingest",
        registry_stage_id="step_02_extraction",
        order=1,
        depends_on=(),
        script_path="steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/blockstore",
        base_config_path="steps/step_02_pdf_ingest_blockstore/resources/step2.hpc.actual_corpus.yaml",
        active_pointer_path="data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt",
        run_stage_wired=True,
        notes="RESOLVED AND WIRED (Milestone 4 session): the confirmed architectural fork - "
        "run_step2.py processes exactly ONE document per invocation, no list/loop in either its "
        "config schema (doc.doc_id/doc.pdf_path, both singular) or main() - is real, but the "
        "orchestrator itself now owns the per-document looping rather than modifying "
        "run_step2.py (which is validated, working, single-document-per-invocation code that "
        "should not be changed to add multiplicity it wasn't designed for). "
        "_prepare_step_02_invocations() (scripts/kc_l_orchestrator.py) renders ONE shared "
        "per-run config (output.processed_blockstore_dir overridden to a run-id-scoped "
        "directory) and returns one invocation per RUN_STATE.json course_materials entry (never "
        "a hardcoded historical document list - refuses if course_materials is empty). "
        "CONFIRMED LOAD-BEARING DETAIL found while wiring this: run_step2.py's own "
        "_write_step2_active_set() self-merges each invocation's doc entry into the SAME "
        "_sets/ACTIVE_STEP2_SET.txt via an unsynchronized read-existing/merge/rewrite cycle - "
        "no file locking of any kind. Running N of these truly in parallel would race (one "
        "document's contribution silently overwritten, not a loud crash). "
        "run_stage()/_run_step_02_stage() therefore submits one SLURM job per document, "
        "chained SERIALLY via --dependency=afterok (never in parallel) - this also composes "
        "directly with the same afterok chaining Milestone 4's self-chaining uses between "
        "stages, so no new 'wait for N parallel jobs, then fan in' primitive was needed. "
        "RUN_STATE.json's job_id for this stage is the LAST job in the chain; SLURM's own "
        "afterok semantics guarantee that job only reaches COMPLETED if every job before it "
        "also succeeded, so polling just that one job_id is sufficient. Steps 3 through 4.5 do "
        "NOT have the one-doc-per-invocation problem (each processes ALL docs from a single "
        "invocation, looping over an upstream ACTIVE_*.txt set's docs list, confirmed by "
        "reading run_step3.py through run_step4_5.py directly) - see their own notes for what "
        "DOES still block step_04_3_embedding_index/step_04_5_sentence_overlay (a separate, "
        "newly-confirmed Ollama CLI-contract mismatch, unrelated to this fork).",
    ),
    "step_03_doctree_index": StageSpec(
        stage_id="step_03_doctree_index",
        registry_stage_id="step_02_extraction",
        order=2,
        depends_on=("step_02_pdf_ingest",),
        script_path="steps/step_03_doctree_index/scripts/run_step3.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/doctree",
        base_config_path="steps/step_03_doctree_index/resources/step3.hpc.actual_corpus.yaml",
        active_pointer_path="data/processed/doctree/_sets/ACTIVE_STEP3_SET.txt",
        run_stage_wired=True,
        notes="WIRED (Milestone 4 session): self-writes its own ACTIVE_STEP3_SET.txt "
        "(confirmed by reading run_step3.py directly - no separate freeze step needed, unlike "
        "step_04_patches/step_04_3_embedding_index below), reads ALL docs from a single "
        "invocation via input.step2_sets_dir/step2_active_set_file, resolved from step_02's "
        "current-run output_root - never a hardcoded historical pointer.",
    ),
    "step_03_5_blockstore_cleanup": StageSpec(
        stage_id="step_03_5_blockstore_cleanup",
        registry_stage_id="step_02_extraction",
        order=3,
        depends_on=("step_03_doctree_index",),
        script_path="steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/blockstore_enriched",
        base_config_path="steps/step_03_5_blockstore_cleanup/resources/step3_5.hpc.actual_corpus.yaml",
        active_pointer_path="data/processed/blockstore_enriched/_sets/ACTIVE_STEP3_5_SET.txt",
        run_stage_wired=True,
        notes="WIRED (Milestone 4 session): same self-contained single-invocation pattern as "
        "step_03_doctree_index; reads both step_02's and step_03's current-run ACTIVE_*.txt "
        "pointers (input.step2_sets_dir/step2_active_set_file/step3_sets_dir/"
        "step3_active_set_file).",
    ),
    "step_03_6_math_salvage": StageSpec(
        stage_id="step_03_6_math_salvage",
        registry_stage_id="step_02_extraction",
        order=4,
        depends_on=("step_03_5_blockstore_cleanup",),
        script_path="steps/step_03_6_math_salvage/scripts/run_step3_6.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/blockstore_math_salvaged",
        base_config_path="steps/step_03_6_math_salvage/resources/step3_6.hpc.actual_corpus.yaml",
        active_pointer_path="data/processed/blockstore_math_salvaged/_sets/ACTIVE_STEP3_6_SET.txt",
        run_stage_wired=True,
        notes="A GPU-partition launcher variant exists (run_step3_6_actual_corpus_gpu.slurm) "
        "for throughput - not Ollama-based, needs_ollama=False is still correct. "
        "WIRED (Milestone 4 session): same self-contained single-invocation pattern as "
        "step_03_doctree_index/step_03_5_blockstore_cleanup; reads step_03_5's current-run "
        "ACTIVE_STEP3_5_SET.txt.",
    ),
    "step_04_patches": StageSpec(
        stage_id="step_04_patches",
        registry_stage_id="step_04_retrieval_index",
        order=5,
        depends_on=("step_03_6_math_salvage",),
        script_path="steps/step_04_structure_retrieval_index/scripts/run_step4.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/retrieval_index",
        base_config_path="steps/step_04_structure_retrieval_index/resources/step4.patches.hpc.actual_corpus.yaml",
        active_pointer_path="data/processed/retrieval_index/_sets/ACTIVE_STEP4_PATCHES_SET.txt",
        run_stage_wired=True,
        notes="WIRED (Milestone 4 session), with a genuinely new wrinkle beyond the "
        "multi-document question: run_step4.py does NOT self-write ACTIVE_STEP4_PATCHES_SET.txt "
        "(confirmed by reading it directly - no set-manifest/pointer-writing code at all) - a "
        "SEPARATE script, freeze_step4_patches_set.py (co-located with run_step4.py; NOT the "
        "differently-conventioned steps/step_04_2_patches/ copy or the .LEGACY.py variant, "
        "confirmed by matching its explicit-CLI-args style to the other 'actual_corpus' "
        "scripts), must run afterward to produce it. That freeze script needs run_step4.py's "
        "own internally-generated timestamp run_id (now_run_id('step4') - confirmed no --run-id "
        "CLI override exists), which is only knowable after run_step4.py finishes. Solved via a "
        "new render_cpu_job(extra_commands=...) parameter (src/kc_l/runtime/slurm_render.py, "
        "backward-compatible - byte-identical output when unused): the rendered SLURM script "
        "runs run_step4.py, then (only if it exits 0) glob-discovers the internal run_id from "
        "the first document's processed_root subdirectory in bash, refusing loudly (exit "
        "40/41) if that glob doesn't match exactly one run, then runs "
        "freeze_step4_patches_set.py with the discovered value - all in the SAME SLURM job, no "
        "second sbatch submission needed.",
    ),
    "step_04_3_embedding_index": StageSpec(
        stage_id="step_04_3_embedding_index",
        registry_stage_id="step_04_retrieval_index",
        order=6,
        depends_on=("step_04_patches",),
        script_path="steps/step_04_structure_retrieval_index/scripts/run_step4_3.py",
        invocation="config_yaml",
        needs_ollama=True,
        output_root="data/processed/retrieval_index",
        base_config_path="steps/step_04_structure_retrieval_index/resources/step4.index.hpc.actual_corpus.yaml",
        active_pointer_path="data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt",
        run_stage_wired=True,
        notes="WIRED after the Milestone 4 follow-up static-port fix. Confirmed by reading "
        "run_step4_3.py directly: the original blocker was real - it read a hardcoded STATIC "
        "embedding.base_url (http://127.0.0.1:11434) from config and had no --ollama-host CLI "
        "flag, which meant render_ollama_job()'s dynamic per-job OLLAMA_HOST design could not "
        "reach the script. Fixed surgically by adding --ollama-host (defaulting to "
        "os.environ['OLLAMA_HOST'] when present) and normalizing host:port -> "
        "http://host:port inside run_step4_3.py, so the shared render_ollama_job() contract now "
        "applies here exactly the same way it already does for the confirmed-good step 6.7 "
        "chain. The second Milestone 4 issue remains load-bearing and is handled in the same "
        "SLURM job via extra_commands: run_step4_3.py still does NOT self-write "
        "ACTIVE_STEP4_SET.txt, so freeze_step4_index_set_actual_corpus.py runs afterward with "
        "the orchestrator-provided current-run paths. Unlike step_04_patches, no bash-level "
        "glob-discovery is needed here because run_step4_3.py accepts --run-id directly; the "
        "freeze script can use data/runs/<run_id>/summary.json deterministically.",
    ),
    "step_04_5_sentence_overlay": StageSpec(
        stage_id="step_04_5_sentence_overlay",
        registry_stage_id="step_04_5_sentence_overlay",
        order=7,
        depends_on=("step_04_3_embedding_index",),
        script_path="steps/step_04_5_sentence_overlay/scripts/run_step4_5.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/retrieval_sentence_overlay",
        base_config_path="steps/step_04_5_sentence_overlay/resources/step4_5.hpc.actual_corpus.yaml",
        input_override_keys=("active_step4_set", "step4_active_set_pointer"),
        active_pointer_path="data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SET.txt",
        run_stage_wired=True,
        notes="WIRED. The two runner bugs from the earlier follow-up investigation are FIXED "
        "and functionally verified against real historical data (not just import/signature-"
        "level): (1) resolve_step4_block_corpus_path(step4_doc, repo_root) was called but never "
        "defined anywhere in the module - added it, mirroring the sibling "
        "resolve_step4_patch_paths()'s own real-manifest-field-checking style (checks "
        "block_text_corpus_path, then artifacts['block_text_corpus.jsonl']['path'], then falls "
        "back to index_out_dir/processed_out_dir + the known filename - confirmed both real key "
        "shapes exist in a real historical Step 4.3 manifest). (2) resolve_step4_patch_paths(..., "
        "repo_root=repo_root) passed a keyword the real signature (step4_doc, "
        "step4_patch_doc=None) doesn't accept - removed the stray keyword; the function's own "
        "internals never needed repo_root, since real manifest paths are already absolute. "
        "scripts/maintenance/verify_step4_5_bugfix_functional.py runs the real, unmodified "
        "run_step4_5.py end to end against a real historical Step 4.3 manifest (found fully "
        "mirrored locally for all 3 real course-material documents): 77470 real sentence rows "
        "across all 3 docs, 0 invalid rows, acceptance gate passed. CONFIRMED CONFIG-KEY "
        "PRECEDENCE DETAIL (load-bearing for the wiring below, found while building that "
        "verification): step4_5.default.yaml sets inputs.step4_active_set_pointer, while this "
        "stage's own actual_corpus.yaml base sets a DIFFERENTLY-named inputs.active_step4_set - "
        "main()'s lookup checks step4_active_set_pointer FIRST, so overriding only "
        "active_step4_set is silently shadowed by the default's value surviving the merge. "
        "WIRED into run-stage overriding BOTH keys together to the current run's step_04_3 "
        "output ({step_04_3 output_root}/_sets/ACTIVE_STEP4_SET.txt, resolved dynamically via "
        "_resolve_upstream_output_root - never a hardcoded historical pointer, same pattern as "
        "step_06_6/step_05p).",
    ),
    "step_05_3_evidence_recalibrated": StageSpec(
        stage_id="step_05_3_evidence_recalibrated",
        registry_stage_id=None,
        order=9,
        depends_on=("step_04_5_sentence_overlay", "hierarchy_registry"),
        script_path="steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/kc_evidence_recalibrated",
        base_config_path="steps/step_05_3_evidence_recalibrated/resources/step5_3.hpc.actual_corpus.yaml",
        input_override_keys=("kc_registry_path", "step4_5_active_set_pointer"),
        active_pointer_path="data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt",
        run_stage_wired=False,
        notes="DISABLED 2026-07-31 (real, permanent-for-now fix, not a one-off skip): confirmed "
        "this stage's output has ZERO effect on drafting_input_overlay.py's real evidence "
        "assembly (that module's own SOURCE_STEP_KIND comment: step_05x/topic_05x's embedded "
        "pack is its sole evidence source, and step_06_6's own invocation-prep code in "
        "kc_l_orchestrator.py passes no step_05_3 pointer at all) - this stage has been running "
        "to completion on every real run (baseline fixab_resume_20260729 job 236575, ablation "
        "runs job 236954/236958) purely as wasted GPU compute, never read downstream. Also "
        "confirmed a live race condition: since this stage's only depends_on "
        "(step_04_5_sentence_overlay, hierarchy_registry) are satisfied well before "
        "step_05x_kc_evidence_stage_v3 finishes, its own gap-KC scoping (see "
        "step5_3_evidence_recalibrated_bridge.build_step5_3_run_config's step5x_pack_jsonl "
        "handling) silently falls back to the FULL unscoped registry (159 KCs, ~2 hours) rather "
        "than the intended ~35-KC gap subset (~30 minutes) almost every time. No stage in this "
        "registry lists step_05_3_evidence_recalibrated in its own depends_on (confirmed via "
        "direct grep), so disabling it cannot strand or block any other stage's self-chaining -"
        " it simply stops being submitted. One accepted side effect: resolve_ready_stages() "
        "will still evaluate it as 'ready' (its own dependencies are still real graph edges) "
        "every run, find run_stage_wired=False, and record it under RUN_STATE.json's "
        "blocked_stages with the run's top-level status permanently set to "
        "'blocked_unwired_stage' - cosmetic only (submit_ready_stages() still submits every "
        "other ready-and-wired stage normally in the same pass; this doesn't halt or delay "
        "anything), but expect every future run's top-level status field to read this way "
        "rather than 'awaiting_human_review' going forward. "
        "NEWLY WIRED 2026-07-16 (not one of the JSON registry's 17 canonical stage_nodes - "
        "registry_stage_id=None reflects that gap honestly rather than inventing a mapping). "
        "CONFIRMED this session: step_06_6_drafting_input_overlay's own code "
        "(run_step6_6_kc_drafting_input_overlay.py) hard-requires this stage's "
        "kc_evidence_candidates_recalibrated_jsonl as the PRIMARY per-KC candidate source - "
        "build_overlay_records() raises RuntimeError for any real kc_id absent from it, with no "
        "fallback. This stage was never migrated into the modern orchestrator and its shared "
        "ACTIVE_STEP5_3_EVIDENCE_SET.txt pointer had not been updated since 2026-04-26 - "
        "silently capping every subsequent run's real KC coverage at that date's 144-KC "
        "hierarchy (see step_06_6_drafting_input_overlay's own notes below for the full chain: "
        "this is what actually produced the kc_packet_count 144-vs-159 discrepancy investigated "
        "2026-07-15/16, NOT the topic5x_pack/step5x_pack BEST-pointer staleness fixed earlier "
        "the same investigation). acceptance.n_kcs_total was also hardcoded to 144 in the base "
        "YAML, hard-asserted against the real registry row count - any run whose hierarchy "
        "differs immediately raises RuntimeError. kc_l.runtime.step5_3_evidence_recalibrated_"
        "bridge.build_step5_3_run_config() re-derives both kc_registry_path (from Step 01's own "
        "hierarchy_manifest.json - NOT hierarchy_registry's own output_root, which is Step "
        "01.5's separate overlay output; see that module's own docstring) and step4_5's ACTIVE "
        "pointer, plus acceptance.n_kcs_total, fresh per run_id. Runs a local reranker model "
        "(Qwen3-Reranker-8B-seq-cls, BGE-reranker-v2-m3 fallback) on CUDA - needs a real GPU "
        "partition/gres override, same gpu80GB/gpu:a100:1 combination already confirmed-good "
        "for step_02's MinerU GPU routing, since no dedicated step5_3 SLURM template exists to "
        "copy from. No Ollama/chat-LLM call anywhere in this script.",
    ),
    "hierarchy_registry": StageSpec(
        stage_id="hierarchy_registry",
        registry_stage_id="seedless_hierarchy_registry",
        order=8,
        depends_on=(),
        script_path="steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/hierarchy_overlay",
        cli_flags=(
            "--hierarchy",
            "--normalized_registry",
            "--normalized_manifest",
            "--out_root",
            "--runs_dir",
            "--print_summary",
        ),
        cli_flags_confirmed=True,
        run_stage_wired=True,
        notes="NEW StageSpec name intentionally drops the historical 'seedless' terminology; "
        "registry_stage_id preserves the JSON registry's seedless_hierarchy_registry node only "
        "for cross-traceability. CONFIRMED this session by reading both real producer scripts "
        "directly: steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py writes the "
        "intermediate normalized registry/manifest under data/processed/hierarchy/<run_id>/, "
        "and steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py then "
        "consumes those exact step 01 outputs and writes the final consumer-facing "
        "hierarchy_overlay.jsonl recorded in overlay_manifest.json under "
        "data/processed/hierarchy_overlay/<run_id>/. step_05p consumes that final overlay "
        "artifact, so this StageSpec anchors the actual producer script for the artifact "
        "Step 5p reads while documenting the upstream step 01 prerequisite. Dynamic Step 5p "
        "resolution must read this stage's per-run overlay_manifest.json / "
        "artifacts.hierarchy_overlay_jsonl, never default to any fixed historical overlay path.",
    ),
    "step_05p_kc_retrieval_profiles": StageSpec(
        stage_id="step_05p_kc_retrieval_profiles",
        registry_stage_id="step_05p_kc_retrieval_profiles",
        order=10,
        depends_on=("step_04_5_sentence_overlay", "hierarchy_registry"),
        script_path="steps/step_05_p_kc_retrieval_profile/scripts/run_step5p_kc_retrieval_profile.py",
        invocation="cli_args",
        needs_ollama=True,
        output_root="data/processed/kc_retrieval_profiles",
        base_config_path="steps/step_05_p_kc_retrieval_profile/resources/step5p.hpc.production_gemma4_31b.yaml",
        cli_flags=(
            "--config", "--registry-jsonl", "--source-overlay-jsonl", "--exact-kc-ids",
            "--limit-kcs", "--run-id", "--output-root", "--set-manifest-root", "--use-model",
            "--no-model", "--llm-policy", "--model", "--base-url", "--ollama-host", "--max-snippets-per-kc",
            "--min-snippet-score", "--resume", "--checkpoint-every", "--base-profile-jsonl",
            "--feedback-gap-jsonl", "--feedback-round",
        ),
        cli_flags_confirmed=True,
        run_stage_wired=False,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. WIRED. CONFIRMED via real manifests plus direct script read. Flags read directly "
        "from add_argument() in the real script. Historical Step 5p runs used MORE THAN ONE real "
        "registry lineage (confirmed this session): some runs consumed canonical in-repo "
        "hierarchy_overlay outputs, some consumed the current_step_artifacts seedless alias, and "
        "some late runs consumed the scratch/codex_sync rehydrated registry artifact. The "
        "canonical producer lineage inside this repo is now explicitly modeled as "
        "hierarchy_registry above. Dynamic Step 5p config rendering is implemented via "
        "kc_l.runtime.step5p_hierarchy_registry_bridge.build_step5p_run_config(), which resolves "
        "inputs.registry_jsonl from the CURRENT run chain's hierarchy_registry output "
        "(overlay_manifest.json -> artifacts.hierarchy_overlay_jsonl) and source_overlay_jsonl "
        "from the CURRENT run chain's step_04_5_sentence_overlay output - never a hardcoded "
        "historical default. The scratch build_step5p_context_rehydrated_registry_20260505T214429Z "
        "artifact remains a real historical alternate input lineage, but verification-only: not "
        "the runtime default for fresh runs. CONFIRMED BUG FIXED (final flip-and-verify pass): "
        "resolve_sentence_overlay_jsonl_from_output_root() in step5p_hierarchy_registry_bridge.py "
        "used to assume step_04_5's output was a flat sentence_corpus.jsonl file; the real "
        "run_step4_5.py nests it under its own internal-timestamp run_id (same pattern as step "
        "6.6/6.9-6.13/step_04_patches/step_04_3), confirmed by actually running the real runner "
        "against a real chain state and hitting an uncaught FileNotFoundError. Fixed by reading "
        "step_04_5's own self-written ACTIVE_STEP4_5_SET.txt pointer (<output_root>/_sets/"
        "ACTIVE_STEP4_5_SET.txt) via stage_pointers.resolve_pointer(), then that set manifest's "
        "own artifacts.sentence_corpus_jsonl field (both confirmed the real real path/field name "
        "by reading run_step4_5.py's own pointer-writing/manifest-writing code directly) - the "
        "stage's own declared output location, not an inferred one. Re-verified end to end "
        "(scripts/maintenance/verify_step05p_step05x_full_chain_dry_run.py): real step_04_3 "
        "output -> real run_step4_5.py execution producing genuine nested output -> step_05p "
        "dry-run now succeeds and resolves the real nested file, not the old flat guess.",
    ),
    "step_05x_kc_evidence_stage_v3": StageSpec(
        stage_id="step_05x_kc_evidence_stage_v3",
        registry_stage_id="step_05x_kc_evidence_stage_v3",
        order=11,
        depends_on=(
            "step_05p_kc_retrieval_profiles", "step_04_5_sentence_overlay", "hierarchy_registry",
        ),
        script_path="steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_candidate_bank.py",
        invocation="cli_args",
        needs_ollama=False,
        run_stage_wired=False,
        output_root="data/processed/evidence_stage_v3_evidence_packs",
        cli_flags=(
            "--config", "--step5-3-set-manifest", "--step5-3-candidates-jsonl",
            "--registry-jsonl", "--source-overlay-jsonl", "--profile-jsonl", "--exact-kc-ids",
            "--limit-kcs", "--output-root", "--set-manifest-root", "--run-id",
            "--allow-seed-bearing-input-for-diagnostic", "--enable-source-surface-fallback",
            "--disable-source-surface-fallback", "--max-fallback-per-kc",
            "--fallback-min-score", "--direct-overlay-supplement-jsonl",
            "--enable-direct-overlay-supplement", "--disable-direct-overlay-supplement",
            "--max-direct-overlay-per-kc", "--direct-overlay-min-score",
        ),
        cli_flags_confirmed=True,
        active_pointer_path="data/processed/evidence_stage_v3_evidence_packs/_sets/"
        "BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt",
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. CONFIRMED this session via backward provenance trace: real chain is 3 canonical "
        "scripts under steps/step_05_x_evidence_stage_v3/scripts/ - "
        "run_step5x_v3_candidate_bank.py (config step5x_v3_candidate_bank.default.yaml) -> "
        "run_step5x_v3_scored_candidates.py (step5x_v3_scored_candidates.default.yaml) -> "
        "run_step5x_v3_pack_composition.py (step5x_v3_pack_composition.default.yaml, cli_flags "
        "above are this final script's). All 3 flag lists confirmed via add_argument() grep. "
        "GAP MEASURED AND CLOSED (see ORCHESTRATOR_BUILD_STATE.md's 'KC-track gate-chain "
        "quality investigation' entry): the BEST pointer's actual target "
        "(best_step5x_final_sanitized_gapaware_20260519T160140Z_pack) was NOT this 3-script "
        "chain's raw output, but a direct A/B comparison found the real, measured gap was small "
        "(5/189 ordered items across 5/144 KCs - 4 exact-duplicate drops + 1 exercise-prompt "
        "filter, plus 23 items flagged-not-removed) and NOT the large 'reproduces "
        "pre-sanitization, not best quality' divergence previously assumed here. Everything else "
        "in the >20-script local_audits/ gate chain (bounded31_dangling_guard_gate_*, "
        "full_exercise_guard_gate_*, the parenthetical/route-respect/domain-residue patches, "
        "etc.) turned out to be iterative development of src/kc_l/retrieval_gate/"
        "evidence_admission.py, already permanently live in current source - confirmed via its "
        "own rule-marker strings. Only the FINAL script in that chain "
        "(finalize_best_step5x_pack_gapaware_v2.py, created_by="
        "'kc_l_finalize_best_step5x_pack_v2_precision_gap_aware', distinct from the canonical "
        "run_step5x_v3_finalize_evidence_pack.py) had logic missing from the canonical tree. "
        "That logic (dedup by normalized text, remove exercise/task-prompt items, flag-not-"
        "remove noisy items, create a retrieval_gap_request for any KC emptied by the removal) "
        "is now folded into run_step5x_v3_pack_composition.py's own main() as a post-processing "
        "step (src/kc_l/retrieval_gate/step5x_pack_sanitizer.py::finalize_step5x_pack_in_place, "
        "called after build_evidence_pack_artifacts()). Verified: running the now-updated "
        "canonical script against the real historical scored-candidates input reproduces the "
        "real BEST_STEP5X pack exactly - 0/144 KCs differing (scripts/maintenance/"
        "verify_step5x_pack_sanitizer_fold_in.py). The other ~18 gate-chain scripts were "
        "deliberately NOT resurrected - their work is already live in evidence_admission.py. "
        "RESOLVED (3-script chain wiring pass): decision made was (b) - chain all 3 real "
        "scripts within this stage's own SLURM job via render_cpu_job's extra_commands (the "
        "same multi-command pattern already used for step_04_patches/step_04_3's freeze "
        "steps), not (a) separate StageSpec entries - this stage stays one registry entry, "
        "matching its single coarse node in the JSON registry. script_path/cli_flags above are "
        "now run_step5x_v3_candidate_bank.py's own (the FIRST script in the chain, invoked as "
        "the main SLURM command); run_step5x_v3_scored_candidates.py and "
        "run_step5x_v3_pack_composition.py run after it via extra_commands, each gated on the "
        "previous command's exit code. All 3 scripts confirmed (via their own argparse plus "
        "their library module's real function signature, not assumed from names) to honor a "
        "passed --run-id directly (chosen_run_id = str(run_id or utc_stamp())) - every "
        "artifact path in the chain is knowable at Python render time, no bash-level glob "
        "discovery needed unlike step_04_patches. candidate_bank is invoked in its confirmed "
        "clean-slate mode (registry_jsonl_spec + source_overlay_jsonl_spec both set => "
        "clean_slate_requested=True per evidence_stage_v3_candidate_bank.py's own "
        "run_candidate_bank_stage(), confirmed by reading that branch directly) - legacy "
        "--step5-3-set-manifest/--step5-3-candidates-jsonl are NOT needed/passed. registry_jsonl "
        "and source_overlay_jsonl are resolved via the same "
        "step5p_hierarchy_registry_bridge.resolve_hierarchy_overlay_jsonl_from_output_root()/"
        "resolve_sentence_overlay_jsonl_from_output_root() helpers step_05p already uses "
        "(hierarchy_registry added to this stage's own depends_on for that reason); "
        "--profile-jsonl is step_05p's own real current-run output "
        "(<step_05p_output_root>/kc_retrieval_profiles.jsonl - confirmed flat, no double-"
        "nesting, since run_step5p_kc_retrieval_profile.py honors a passed --run-id directly "
        "and step_05p's own output_root override matches this StageSpec's registered "
        "output_root exactly). Verified end to end via scripts/maintenance/"
        "verify_step05x_v3_chain_dry_run.py. run_stage_wired flipped True.",
    ),
    "topic_05p_retrieval_profiles": StageSpec(
        stage_id="topic_05p_retrieval_profiles",
        registry_stage_id="topic_05p_retrieval_profiles",
        order=12,
        depends_on=("step_04_5_sentence_overlay", "hierarchy_registry"),
        script_path="steps/step_05_tp_topic_retrieval_profile/scripts/run_step5tp_topic_retrieval_profile.py",
        invocation="cli_args",
        needs_ollama=True,
        run_stage_wired=False,
        output_root="data/processed/topic_retrieval_profiles",
        cli_flags=(
            "--config", "--topic-registry-jsonl", "--topic-to-kc-edges-jsonl",
            "--exact-topic-ids", "--limit-topics", "--run-id", "--source-overlay-jsonl",
            "--output-root", "--set-manifest-root", "--max-snippets-per-topic",
            "--min-snippet-score", "--use-model", "--no-model", "--llm-policy", "--model",
            "--base-url", "--dynamic-broad-token-min-df",
        ),
        cli_flags_confirmed=True,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. CONFIRMED this session (background research agent, same backward-trace "
        "methodology) via src/kc_l/topic_5p5x/pipeline.py's parse_profile_args - the actual "
        "script is a thin wrapper (main_topic_profile) around this shared module, which also "
        "backs all 3 topic_05x scripts. needs_ollama=True because the confirmed-good historical "
        "run used --use-model --llm-policy always --model gemma4:31b (the default yaml config "
        "has use_model=false/llm_policy=never - a fresh run must pass these CLI overrides "
        "explicitly, they are NOT the script's own defaults). "
        "WIRED (later same-night follow-up session): the old CONFIRMED GAP here - "
        "--topic-registry-jsonl/--topic-to-kc-edges-jsonl pointing at a one-off "
        "local_audits reconstruction (build_reconstructed_topic_registry_20260519T165224Z/), "
        "self-documented as 'not the missing human-reviewed topic final-resolution artifact' - "
        "is resolved, not worked around: there is no separate topic registry. The KC hierarchy "
        "IS the topic hierarchy (confirmed directly: the reconstruction's own topic_id values "
        "are literally hierarchy_overlay.jsonl's hier_node_id hashes, traced back through the "
        "final KC pack's parent_topic_id field). A 'topic unit' is precisely a "
        "hierarchy_overlay.jsonl row with node_type=='topic' whose child_hier_node_ids are all "
        "KC leaves directly - verified an exact 1:1 match (same 21 topics, same labels, same "
        "KC-id sets) against the historical reconstruction on a real 171-row hierarchy_overlay "
        "output. New src/kc_l/runtime/topic5p_hierarchy_registry_bridge.py "
        "(extract_topic_registry_and_edges()) derives both required inputs directly from the "
        "CURRENT run's hierarchy_registry output, replacing the reconstruction entirely - see "
        "ORCHESTRATOR_BUILD_STATE.md's 'topic_05p rewired to hierarchy_registry' entry for the "
        "full investigation. depends_on gained hierarchy_registry for this reason (mirrors "
        "step_05p/step_05x's own dependency). topic_05x_evidence_stage_v3 is untouched by this "
        "- its own blocker (the field-dropping defect in the shared KC-scorer, and the "
        "deliberately-unwired risk-detection blind spot in its reconstructed rehydration fix) is "
        "unrelated to registry sourcing and remains open, still requiring a human decision.",
    ),
    "topic_05x_evidence_stage_v3": StageSpec(
        stage_id="topic_05x_evidence_stage_v3",
        registry_stage_id="topic_05x_evidence_stage_v3",
        order=13,
        depends_on=("topic_05p_retrieval_profiles", "step_04_5_sentence_overlay"),
        script_path="steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_candidate_bank.py",
        invocation="cli_args",
        needs_ollama=False,
        run_stage_wired=False,
        output_root="data/processed/topic_evidence_stage_v3_evidence_packs",
        cli_flags=(
            "--config", "--topic-scored-candidates-jsonl", "--exact-topic-ids",
            "--limit-topics", "--output-root", "--set-manifest-root", "--run-id",
        ),
        cli_flags_confirmed=True,
        active_pointer_path="data/processed/topic_evidence_stage_v3_evidence_packs/_sets/"
        "BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt",
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. Parallel topic-level track to step_05x - feeds the ~21/165 topic-type KCs. "
        "Pointer name is explicitly '...FOR_STEP6_SET' - confirms it's consumed by step 6.6. "
        "WIRED: real chain is 4 scripts (run_step5tx_topic_candidate_bank.py -> "
        "run_step5tx_topic_scored_candidates.py -> run_step5tx_topic_scored_trace_rehydration.py "
        "-> run_step5tx_topic_pack_composition.py; script_path is the first script, matching the "
        "step_05x_kc_evidence_stage_v3 convention - cli_flags above are still the LAST script's, "
        "kept for is_confirmed()/gap-tracking purposes), all thin wrappers around "
        "src/kc_l/topic_5p5x/pipeline.py, which itself imports the shared KC-track scoring/pack "
        "code (kc_l.retrieval_gate.evidence_stage_v3_*) rather than reimplementing it. "
        "BOTH confirmed gaps closed: (1) the field-dropping defect (bridge_loader_knowledge_"
        "unit_type/topic5p_weak_profile_carry_forward dropped by the shared KC-shaped scorer, "
        "still present in current live pipeline.py) is fixed by inserting the rehydration script "
        "as a real chain step, pointing pack_composition at its rehydrated output rather than "
        "scored_candidates' raw one; (2) the risk-detection blind spot (the rehydration module's "
        "content/soft risk tags used to be a hardcoded lookup of 20+3 historical candidate_ids, "
        "silently tagging every NEW candidate as risk-free) is fixed by reimplementing the real "
        "historical detector - found in the archived audit_topic5x_scored_candidates_risk_gate.py "
        "- as a live risk_tags() function in scored_trace_rehydration.py, verified byte-for-byte "
        "(sha256-identical, 608/608 exact row match) against the historical fixture before being "
        "trusted (scripts/maintenance/verify_topic5x_scored_trace_rehydration_reconstruction.py). "
        "A separate candidate-bank type-mistagging bug from the same era was already fixed in "
        "current source (normalize_topic_candidate_bank_rows in pipeline.py). run_stage_wired "
        "flipped True only after the byte-for-byte verification passed.",
    ),
    "step_06_6_drafting_input_overlay": StageSpec(
        stage_id="step_06_6_drafting_input_overlay",
        registry_stage_id="step_06_6_drafting_input_overlay",
        order=14,
        # 2026-07-26: step_05_3_evidence_recalibrated dismantled as a dependency - it caused four
        # distinct incidents in one night, each fix revealing the next (hierarchy-path
        # resolution, acceptance-threshold scaling, provenance-pointer poisoning, then the hard
        # "every KC needs a Step5.3 candidate" requirement in drafting_input_overlay.py's
        # build_overlay_records()) - a strong signal the retrofit conflicted with more of the
        # existing contract than originally scoped. step_05x/topic_05x's own embedded pack is
        # now this stage's sole evidence source (see build_overlay_records' own comment). The
        # step_05_3_evidence_recalibrated StageSpec itself is left intact/orphaned, not deleted -
        # still manually runnable via run-stage, just no longer self-chained into anything.
        depends_on=("step_05x_kc_evidence_stage_v3", "topic_05x_evidence_stage_v3"),
        script_path="steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/kc_drafting_input_overlay",
        base_config_path="steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.hpc.actual_corpus.yaml",
        input_override_keys=(
            "step4_active_set_pointer",
            "step4_5_active_set_pointer",
            "step5_3_active_set_pointer",
            "step5_4_set_manifest",
            "hierarchy_overlay_manifest",
        ),
        run_stage_wired=False,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. CONFIRMED LIVE INTEGRITY BUG, FIXED (original): step6_6.hpc.actual_corpus."
        "step5x_bridge.yaml hardcoded one specific timestamped step5x pack (manual_bridge_config) "
        "instead of resolving BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt / "
        "BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt dynamically. run-stage now calls "
        "kc_l.runtime.step6_6_evidence_bridge.build_step6_6_run_config(), which resolves both "
        "via the --step6-input-assembly-manifest mechanism (the only code path that keeps KC "
        "and topic evidence genuinely separate) - never the bridge yaml's hardcoded path. "
        "SECOND CONFIRMED BUG, FIXED 2026-07-15: those same BEST_STEP5X/BEST_TOPIC5X pointer "
        "FILES (not just the bridge yaml's hardcoded path) were themselves one-time snapshots "
        "from 2026-05-19/20 that nothing in this codebase ever wrote to again - build_step6_6_"
        "run_config() now defaults to resolving step_05x_kc_evidence_stage_v3/"
        "topic_05x_evidence_stage_v3's OWN fresh per-run output (run_scoped_pack_set_path()) "
        "instead, since both are now run_stage_wired and produce genuine per-run evidence; the "
        "BEST_* pointers remain available as an explicit opt-in override only. THIRD CONFIRMED "
        "BUG, FIXED 2026-07-16: step5_3_active_set_pointer was still coming from the base yaml "
        "unconditionally (this key's real producer, step_05_3_evidence_recalibrated, was never "
        "migrated into the modern orchestrator at all - see that stage's own notes for the full "
        "chain). This was the ACTUAL cause of a kc_packet_count 144-vs-159 discrepancy "
        "investigated over both 2026-07-15 fixes above - step_06_6's own build_overlay_records() "
        "hard-requires every real kc_id to have a Step 5.3 candidate entry, with no fallback, so "
        "a stale Step 5.3 pack silently capped real KC coverage even after both BEST-pointer "
        "fixes. step5_3_active_set_pointer is now overridden per-run to point at THIS run's own "
        "freshly-produced step_05_3_evidence_recalibrated output. step4_active_set_pointer/"
        "step4_5_active_set_pointer still come from the base yaml as configured - both are "
        "self-updating SHARED ACTIVE_* pointers (unlike the three fixed above, both are written "
        "fresh by their own producer stage every run, confirmed via step_03_doctree_index/"
        "step_04_5_sentence_overlay's own notes elsewhere in this file) - not yet independently "
        "re-derived per run_id here, a smaller remaining gap than the three above since those "
        "pointers are at least never literally stale.",
    ),
    "step_06_7_hierarchy_aware_synthesis_packets": StageSpec(
        stage_id="step_06_7_hierarchy_aware_synthesis_packets",
        registry_stage_id="step_06_7_drafting_or_synthesis",
        order=15,
        depends_on=("step_06_6_drafting_input_overlay",),
        script_path="steps/step_06_7_kc_draft_generation/scripts/v2_chain/"
        "build_step67_v2_hierarchy_aware_synthesis_packets.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/step67_v2_hierarchy_aware_synthesis_packets",
        cli_flags=(
            "--step66-set",
            "--topic5x-pack",
            "--child-kc-drafts",
            "--out-dir",
            "--kc-evidence-limit",
            "--topic-evidence-limit",
            "--direct-child-kc-limit",
            "--descendant-kc-limit",
            "--child-topic-kc-preview-limit",
            "--text-max-chars",
        ),
        run_stage_wired=False,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. Resurrected into the same v2_chain/ directory as the 3 confirmed-good step 6.7 "
        "v2 chain scripts. Verified against the historical 20260520T151731Z_policy_repair_replay "
        "artifact: raw Windows SHA256 differs only because local Python writes CRLF line endings, "
        "but LF-normalized bytes are exact "
        "(188af8e9b68ac7d0937ab0df824382512b756ae77b77c60846fb2be20aee5443), with 165/165 "
        "parsed rows and 0 substantive content differences. WIRED into run-stage: "
        "--step66-set is resolved by globbing step 6.6's own per-run _sets/ directory for "
        "*_step6_6_kc_drafting_input_overlay_set.json (step 6.6's own script generates an "
        "internal UTC-timestamp run_id decoupled from this orchestrator's --run-id, confirmed "
        "via its own choose_run_paths(), so the exact filename can't be predicted - exactly one "
        "match is expected since sets_root is scoped per orchestrator run_id); --topic5x-pack "
        "resolves BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt directly (same mechanism step 6.6 "
        "itself uses, confirmed real historical run used the identical topic5x pack); "
        "--child-kc-drafts uses the fixed historical baseline path (confirmed not a same-run "
        "dependency). Future wiring should feed this output to step_06_7_kc_draft_generation as "
        "--selected-packets-jsonl and generate the downstream --plan-json as an inert minimal "
        "placeholder containing only packet_source, row_count, and unit_type_counter.",
    ),
    "step_06_7_kc_draft_generation": StageSpec(
        stage_id="step_06_7_kc_draft_generation",
        registry_stage_id="step_06_7_drafting_or_synthesis",
        order=16,
        depends_on=("step_06_7_hierarchy_aware_synthesis_packets",),
        script_path="steps/step_06_7_kc_draft_generation/scripts/v2_chain/"
        "run_step67_v2_policy_segmentable_abstention_marker_fix.py",
        invocation="cli_args",
        needs_ollama=True,
        output_root="data/processed/step67_v2_tiny_smoke_drafts",
        cli_flags=(
            "--base-runner",
            "--plan-json",
            "--selected-packets-jsonl",
            "--out-dir",
            "--run-id",
            "--model",
            "--num-ctx",
            "--num-predict",
            "--timeout-s",
            "--seed",
        ),
        run_stage_wired=False,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. Resurrected from _archive/ into this stable location (Milestone 2) and "
        "verified: the KC_L_FINAL_SCHEMA_RUNNER/KC_L_SOURCE_SCHEMA_RUNNER importlib wiring "
        "was tested end-to-end at the new path (scripts/maintenance/"
        "verify_step67_v2_chain_resurrection.py), pointing at the other 2 files in this same "
        "v2_chain/ directory. WIRED into run-stage: --selected-packets-jsonl and the packet "
        "stats needed to populate --plan-json both come from "
        "step_06_7_hierarchy_aware_synthesis_packets's fixed (non-timestamped) output filenames "
        "- depends_on corrected to name that stage directly instead of skipping straight to "
        "step_06_6 (depends_on is informational only, not consumed by plan()/run_stage()'s "
        "own order-based sequencing, but was misleading). --plan-json is generated per-run as "
        "the confirmed inert minimal placeholder (packet_source, row_count, unit_type_counter), "
        "populated from the real packet builder's own stats.json rather than left as a stub. "
        "--base-runner is the confirmed real fixed path scripts/experimental/"
        "run_step67_v2_tiny_smoke.py. --ollama-host is appended automatically by "
        "slurm_render.render_ollama_job(), not part of cli_flags here. model=gemma4:31b, "
        "num_ctx=65536, num_predict=16000, temperature=0 (hardcoded in the script itself, "
        "not a flag) are the confirmed production values.",
    ),
    "step_06_7_postprocessed_review_source": StageSpec(
        stage_id="step_06_7_postprocessed_review_source",
        registry_stage_id="step_06_7_postprocessed_review_source",
        order=17,
        depends_on=("step_06_7_kc_draft_generation",),
        script_path="steps/step_06_7_postprocessed_review_source/scripts/"
        "run_step67_v2_postprocess_review_source.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/step67_v2_postprocessed_review_source",
        cli_flags=(
            "--source-drafts-jsonl",
            "--accepted-baseline-run-id",
            "--step67-drafts-best-pointer",
            "--out-dir",
            "--run-id",
            "--update-best-pointer",
            "--step67-postprocess-best-pointer",
        ),
        active_pointer_path="data/processed/step67_v2_postprocessed_review_source/_sets/"
        "BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt",
        active_pointer_key="POSTPROCESSED_JSONL",
        run_stage_wired=False,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. NEW SCRIPT WRITTEN (Milestone 2) - the original producer script was confirmed "
        "lost/never committed anywhere; this is a from-scratch reconstruction "
        "(src/kc_l/step67_postprocess/builder.py), empirically reverse-engineered from the one "
        "surviving real run and validated to reproduce it exactly: 0 classification mismatches "
        "and 0 unresolved-count mismatches across all 165 rows, all 5 summary counters byte-"
        "exact (scripts/maintenance/verify_step67_v2_postprocess_reconstruction.py). Evidence-ID "
        "rebinding is a documented no-op (0 real occurrences to validate against).",
    ),
    "step_06_8_review_packet_emission": StageSpec(
        stage_id="step_06_8_review_packet_emission",
        registry_stage_id="step_06_8_review_packet_emission",
        order=18,
        depends_on=("step_06_7_postprocessed_review_source",),
        script_path="steps/step_06_8_review_packet_emission/scripts/"
        "run_step68_v2_review_packet_emission_from_postprocessed.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/step68_v2_review_packets_from_postprocessed_source",
        cli_flags=(
            "--postprocessed-jsonl",
            "--step67-best-pointer",
            "--out-dir",
            "--run-id",
            "--update-best-pointer",
            "--step68-best-pointer",
            "--pointer-backup-dir",
        ),
        active_pointer_path="data/processed/step68_v2_review_packets_from_postprocessed_source/"
        "_sets/BEST_STEP68_V2_REVIEW_PACKETS_FROM_POSTPROCESSED_SOURCE.txt",
        active_pointer_key="REVIEW_PACKETS_JSONL",
        run_stage_wired=False,
        notes="RETIRED from the automatic self-chain 2026-08-16 (run_stage_wired flipped False): this stage's real evidence-building logic (evidence_stage_v3_candidate_bank.py and its downstream consumers) has never been audited to the standard evidence_pack.py has (v3-v74, 232 checks, 0 failed, documented unit-by-unit and via real Slurm verification in FAILURE_CYCLE_2.md) - see CODEX_HANDOFF.md section 11 for the real incident this caused (mathematics domain output bridged from this stage directly into a real drafting job before being caught). step_05v_verified_kc_packets/step_06v_kc_draft_generation/step_06v_topic_draft_generation/step_06v_review now cover this same ground using the verified pipeline instead. The code and this StageSpec entry are left in place, not deleted, in case a future audit brings evidence_stage_v3_candidate_bank.py up to the same standard and this path is worth reviving - matches the existing step_05_3_evidence_recalibrated precedent for a deliberately-disabled-but-kept stage. Already fully parameterized for fresh runs - no changes needed to this script "
        "itself, only a new SLURM launcher (it has none yet). Mirrored by "
        "scripts/kc_l_orchestrator.py's existing step68-smoke command, a good reference for "
        "how the orchestrator's run-stage command should invoke and validate it.",
    ),
    "step_06_9_review_audit_ingestion": StageSpec(
        stage_id="step_06_9_review_audit_ingestion",
        registry_stage_id="expert_review_resolution",
        order=19,
        depends_on=("step_06_8_review_packet_emission",),
        script_path="steps/step_06_9_kc_review_audit_ingestion/scripts/run_step6_9_kc_review_audit_ingestion.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/kc_review_audits_restarted",
        base_config_path="steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice8.yaml",
        input_override_keys=("review_packet_set_manifest",),
        run_stage_wired=True,
        human_review_gate=True,
        notes="2026-07-16: human_review_gate=True - confirmed by reading "
        "emit_restarted_review_audits() (src/kc_l/kc/restarted_review_audits.py) directly: it "
        "reads reviewer_dry_run_verdicts.json from the review packet dir, a real human "
        "reviewer's completed verdicts, not something step_06_8_review_packet_emission alone "
        "ever produces. This is the correct, final automated boundary for a fresh run's "
        "self-chain - step_06_8 emits packets for a human to review in the console UI; this "
        "stage ingests that human's completed verdicts afterward, on demand, not automatically. "
        "Default path + v2/legacy schema detection already fixed this session "
        "(resolve_review_packet_manifest()). This stage's per-run config must set "
        "inputs.review_packet_set_manifest to point at the v2 manifest from the just-completed "
        "step_06_8_review_packet_emission run, not rely on any hardcoded default. WIRED into "
        "run-stage: review_packet_set_manifest = step 6.8's fixed (non-timestamped) "
        "STEP68_V2_REVIEW_PACKET_MANIFEST.json. CONFIRMED-SAFE for this stage specifically "
        "because it reads that manifest via its own dual-schema-aware "
        "resolve_review_packet_manifest() helper - CONTRAST with step_06_10/step_06_11 below, "
        "which do NOT use that helper and were found to be genuinely broken against the v2 "
        "schema (see ORCHESTRATOR_BUILD_STATE.md's run-stage wiring expansion entry) - do not "
        "assume the same safety carries downstream.",
    ),
    "step_06_10_review_audit_resolution": StageSpec(
        stage_id="step_06_10_review_audit_resolution",
        registry_stage_id="expert_review_resolution",
        order=20,
        depends_on=("step_06_9_review_audit_ingestion",),
        script_path="steps/step_06_10_kc_review_audit_resolution/scripts/run_step6_10_kc_review_audit_resolution.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/kc_review_audits_restarted_resolved",
        base_config_path="steps/step_06_10_kc_review_audit_resolution/resources/step6_10.slice8.yaml",
        input_override_keys=("step6_9_set_manifest",),
        notes="PARTIALLY FIXED, STILL NOT WIRED (live-run reconnection follow-up session). "
        "Bug #1 (the manifest-path-resolution bug documented in the prior note below) is now "
        "FIXED: run_step6_10_kc_review_audit_resolution.py gained its own "
        "resolve_review_packet_manifest() (byte-mirrors step_06_9's own helper - duplicated, "
        "not imported, matching this repo's no-step-imports-another-step's-script convention), "
        "and src/kc_l/kc/restarted_review_audit_resolution.py's _packet_lookup()/"
        "resolve_restarted_review_audits() were fixed to accept the real resolved jsonl path "
        "directly instead of guessing a fixed filename inside a directory (the same class of "
        "bug, one level deeper, in a function with exactly one live caller - confirmed via "
        "repo-wide grep). A new _prepare_stage_invocation() branch was added, glob-discovering "
        "step_06_9's own internal-timestamp set-manifest filename via _find_single_file() "
        "within a run-scoped _sets/ dir, mirroring step_06_9's own branch. Verified via real "
        "execution of emit_review_packets_from_postprocessed_source() (genuine v2 Step 6.8 "
        "manifest+packets) feeding resolve_review_packet_manifest(), plus a real historical "
        "schema-valid audit event (data/processed/kc_review_audits_restarted/2026-04-09_193800/"
        "review_audit.jsonl) round-tripped through the fixed resolve_restarted_review_audits(). "
        "Legacy-schema regression-checked too. "
        "Bug #2, NEWLY DISCOVERED while building that verification, NOT FIXED: real v2 "
        "review packets (built by kc_l.review_packets.builder.build_review_packets()) use "
        "'knowledge_unit_id' as their ID field; resolve_restarted_review_audits()'s own "
        "_packet_lookup()/event-matching logic (restarted_review_audit_resolution.py lines "
        "~332/344/422/464-467/475/524) reads 'kc_candidate_id' throughout, a field that does "
        "not exist anywhere in real v2 packets. Confirmed reproducible, not guessed: running "
        "the fixed function against a real v2 packets file raises 'Missing source review "
        "packet for <kc_id>' for every row. "
        "SEPARATE AND MORE FUNDAMENTAL, blocks step_06_9 itself (upstream of this stage, "
        "so encountered first): step_06_9_review_audit_ingestion (marked run_stage_wired=True, "
        "but never actually functionally exercised against real v2 data before this "
        "investigation) hard-requires a 'reviewer_dry_run_verdicts.json' file "
        "(src/kc_l/kc/restarted_review_audits.py's emit_restarted_review_audits(), line 471, "
        "no try/except, no fallback) that no stage in the current dependency graph produces - "
        "the real producers (build_restarted_human_reviewer_pass.py / "
        "build_restarted_human_review_capture_template.py under "
        "steps/step_06_review_supervision/) are not registered as StageSpec entries or listed "
        "as step_06_9's depends_on at all. This is very likely an intentional human-in-the-loop "
        "gate (matching this project's real 'expert-driven review' design intent) rather than a "
        "bug - it should NOT be patched around unilaterally. emit_restarted_review_audits() "
        "also derives its own event-level kc_candidate_id from packet.get('kc_candidate_id') "
        "(same field-name gap as bug #2 above, one stage earlier), and its own packet read "
        "hardcodes the legacy 'review_packet.jsonl' filename (same class as bug #1, unfixed "
        "in step_06_9's module - out of scope here, not touched). "
        "NOTE: at the time of this investigation, the live orchestrator-driven run was actually "
        "many stages further back (topic_05p_retrieval_profiles/topic_05x_evidence_stage_v3 "
        "are both still run_stage_wired=False, and step_06_6_drafting_input_overlay depends on "
        "topic_05x_evidence_stage_v3 - so any fresh run reaches a clean blocked_unwired_stage "
        "stop there, well before step_06_6 through step_06_9 are ever reached). "
        "run_stage_wired stays False - flipping it now would replace a safe clean stop with an "
        "actual crash once the stage is genuinely reached, given bug #2 above.",
    ),
    "step_06_11_library_assembly": StageSpec(
        stage_id="step_06_11_library_assembly",
        registry_stage_id="frozen_reviewed_library",
        order=21,
        depends_on=("step_06_10_review_audit_resolution",),
        script_path="steps/step_06_11_reviewed_library_assembly/scripts/run_step6_11_reviewed_library_assembly.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/kc_library_reviewed_restarted",
        base_config_path="steps/step_06_11_reviewed_library_assembly/resources/step6_11.slice8.yaml",
        input_override_keys=("step6_10_set_manifest",),
        output_override_keys=("reviewed_root", "reviewed_sets_root", "sandbox_root", "sandbox_sets_root"),
        manifest_count=2,
        notes="STRUCTURAL OUTLIER: output key names (reviewed_root/sandbox_root) differ from "
        "every other stage's processed_root/sets_root convention, and it writes TWO set "
        "manifests per run into two separate _sets/ roots. Symlink-discovery logic in "
        "Milestone 3 must special-case this stage rather than assuming one new sets_root file. "
        "ALSO HAS THE SAME CONFIRMED BUG as step_06_10 (see that stage's notes) - its own "
        "chase-back through step6_8_set_obj.get('artifacts', {}).get('review_packet_jsonl') "
        "is legacy-schema-only, resolves to the repo root for the real v2 step_06_8 output. "
        "It additionally chases further upstream to a step6_7_set_manifest_json - which the "
        "confirmed-good v2 step 6.7 chain (step_06_7_kc_draft_generation) does not even "
        "produce (that script writes step67_v2_tiny_smoke_drafts.jsonl directly, no "
        "set-manifest concept at all) - so this stage is written against an entirely "
        "different, older stage-chaining schema convention than the currently-confirmed v2 "
        "chain uses. Blocked on the same step_06_10 fix/bridge decision, likely a larger one.",
    ),
    "step_06_12_library_packaging": StageSpec(
        stage_id="step_06_12_library_packaging",
        registry_stage_id="runtime_library",
        order=22,
        depends_on=("step_06_11_library_assembly",),
        script_path="steps/step_06_12_reviewed_library_runtime_packaging/scripts/"
        "run_step6_12_reviewed_library_runtime_packaging.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root="data/processed/kc_library_runtime_restarted",
        base_config_path="steps/step_06_12_reviewed_library_runtime_packaging/resources/step6_12.slice8.yaml",
        input_override_keys=("step6_11_set_manifest",),
    ),
    "step_06_13_retrieval_pilot": StageSpec(
        stage_id="step_06_13_retrieval_pilot",
        registry_stage_id=None,
        order=23,
        depends_on=("step_06_11_library_assembly", "step_06_12_library_packaging"),
        script_path="steps/step_06_13_reviewed_library_retrieval_pilot/scripts/"
        "run_step6_13_reviewed_library_retrieval_pilot.py",
        invocation="config_yaml",
        needs_ollama=False,
        output_root=None,
        base_config_path="steps/step_06_13_reviewed_library_retrieval_pilot/resources/step6_13.slice48.yaml",
        input_override_keys=("step6_11_set_manifest", "step6_12_set_manifest"),
        manifest_count=3,
        notes="No registry_stage_id: could not confirm this stage corresponds to the JSON "
        "registry's 'downstream_segmentation_evaluation' node (see that stage's own entry "
        "below) - treating as a separate, unconfirmed-output-root stage rather than assuming "
        "the relationship. STRUCTURAL OUTLIER: writes THREE set manifests per run "
        "(source/index/validation) into the same sets_root.",
    ),
    "downstream_segmentation_evaluation": StageSpec(
        stage_id="downstream_segmentation_evaluation",
        registry_stage_id="downstream_segmentation_evaluation",
        order=24,
        depends_on=("step_06_12_library_packaging",),
        script_path=None,
        invocation="unconfirmed",
        needs_ollama=False,
        output_root="data/processed/kc_segmentation_matching_catalog",
        notes="UNCONFIRMED MAPPING - do not wire into run-stage/plan yet. The JSON registry "
        "attributes output root data/processed/kc_segmentation_matching_catalog to this node, "
        "but its relationship to step_06_13_reviewed_library_retrieval_pilot (or some other, "
        "entirely separate script) was not verified this session. Needs a dedicated "
        "investigation before a real StageSpec can be written.",
    ),
    # ------------------------------------------------------------------------------------------
    # Added 2026-08-16: the VERIFIED pipeline (evidence_pack.py, v3-v74, 232 checks 0 failed),
    # replacing step_05p/step_05x/topic_05p/topic_05x/step_06_6/step_06_7-through-step_06_8
    # (all retired above, run_stage_wired=False, kept not deleted) in the automatic self-chain.
    # See CODEX_HANDOFF.md section 11/12 for the incident and rationale.
    # ------------------------------------------------------------------------------------------
    "step_05v_verified_kc_packets": StageSpec(
        stage_id="step_05v_verified_kc_packets",
        registry_stage_id=None,
        order=100,
        depends_on=("step_04_5_sentence_overlay", "hierarchy_registry"),
        script_path="v3/pipeline/01_build_profiles.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/verified_v3_packets",
        cli_flags=("--overlay-jsonl", "--out-jsonl"),
        run_stage_wired=True,
        notes="Chains v3/pipeline/01_build_profiles.py -> v3/verify/verify_pipeline_fixes.py -> "
        "v3/pipeline/02_build_kc_packets.py -> v3/pipeline/03_build_topic_packets.py in one job, "
        "exactly matching v3/jobs/01_packets*.sbatch's own structure/CLI flags/params "
        "(bm25-pool 400, max-passages 40, max-chars 14000, min-relevance 0.55) - this run's own "
        "resolved corpus/hierarchy paths substituted for a hardcoded domain-specific CORPUS/HIER. "
        "verify_pipeline_fixes.py is a hard gate (nonzero exit aborts before any packet is "
        "built), same as every other real packet build in this project. Replaces "
        "step_05p_kc_retrieval_profiles/step_05x_kc_evidence_stage_v3/"
        "topic_05p_retrieval_profiles/topic_05x_evidence_stage_v3/"
        "step_06_6_drafting_input_overlay/step_06_7_hierarchy_aware_synthesis_packets - one "
        "stage instead of six, because the verified pipeline builds KC and topic packets "
        "together in one pass, with no separate 'drafting input overlay'/'synthesis' step "
        "needed (02_build_kc_packets.py's own output is already the final packet format).",
    ),
    "step_06v_kc_draft_generation": StageSpec(
        stage_id="step_06v_kc_draft_generation",
        registry_stage_id=None,
        order=101,
        depends_on=("step_05v_verified_kc_packets",),
        script_path="steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py",
        invocation="cli_args",
        needs_ollama=True,
        output_root="data/processed/verified_v3_drafts",
        cli_flags=("--base-runner", "--selected-packets-jsonl", "--plan-json", "--out-dir",
                   "--run-id", "--model", "--num-ctx", "--num-predict", "--timeout-s", "--seed"),
        run_stage_wired=True,
        notes="gemma4:31b by default, matching this project's established default model for the "
        "auto-chained path (qwen/command-r/deepseek remain available as manual ablation "
        "submissions via v3/jobs/02_draft_kc_*.sbatch, exactly as they always have been - this "
        "stage does not replace that workflow, only the packets it consumes). --plan-json is "
        "written directly by _prepare_stage_invocation (Python, not a bash pre-command) as the "
        "confirmed inert placeholder (packet_source, row_count, unit_type_counter) populated "
        "from the real packet builder's own kc_packet_stats.json, matching the exact "
        "recommendation left in step_06_7_kc_draft_generation's own retirement note. Replaces "
        "step_06_7_kc_draft_generation.",
    ),
    "step_06v_topic_draft_generation": StageSpec(
        stage_id="step_06v_topic_draft_generation",
        registry_stage_id=None,
        order=102,
        depends_on=("step_05v_verified_kc_packets",),
        script_path="steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py",
        invocation="cli_args",
        needs_ollama=True,
        output_root="data/processed/verified_v3_topic_drafts",
        cli_flags=("--base-runner", "--selected-packets-jsonl", "--plan-json", "--out-dir",
                   "--run-id", "--model", "--num-ctx", "--num-predict", "--timeout-s", "--seed"),
        run_stage_wired=True,
        notes="gemma4:31b by default, matching v3/jobs/03_draft_topics.sbatch (topics has always "
        "been gemma4-only in the auto-chained path in this project; qwen-topics remains "
        "available as a manual submission via v3/jobs/03_draft_topics_qwen36.sbatch). Independent "
        "leaf off step_05v_verified_kc_packets, not a dependency of step_06v_review - the "
        "verified review stage's own script only ever consumed KC-level drafts (confirmed by "
        "reading v3/jobs/04_review_packets.sbatch directly), matching how this project's real "
        "review pipeline has always worked.",
    ),
    "step_06v_assemble_library": StageSpec(
        stage_id="step_06v_assemble_library",
        registry_stage_id=None,
        order=102,
        depends_on=("step_06v_kc_draft_generation", "step_06v_topic_draft_generation"),
        script_path="v3/pipeline/05_assemble_kc_library.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/verified_v3_library",
        cli_flags=("--kc-drafts-jsonl", "--topic-drafts-jsonl", "--out-json", "--run-id"),
        run_stage_wired=True,
        notes="2026-08-17: combines the KC-level and topic-level machine drafts (previously two "
        "flat files joined only by ID convention) into one nested KC Library document, structured "
        "entirely from the topic packet's own direct_child_kcs field - no new hierarchy logic, no "
        "domain assumption. Orphan KCs (a topic with mixed KC/child-topic children is excluded from "
        "topic packet generation per 03_build_topic_packets.py's own documented rule, so its direct "
        "KC children belong to no topic draft - 12 of 159 on the real data-mining rebuild) are "
        "reported under their own top-level key, never silently dropped. This is NOT review "
        "resolution (Phase 6, not reliably operational): it assembles machine drafts as they exist, "
        "with no reviewer verdict - the artifact that would feed review, not a replacement for it.",
    ),
    "step_06v_review": StageSpec(
        stage_id="step_06v_review",
        registry_stage_id=None,
        order=103,
        depends_on=("step_06v_kc_draft_generation",),
        script_path="steps/step_06_7_postprocessed_review_source/scripts/run_step67_v2_postprocess_review_source.py",
        invocation="cli_args",
        needs_ollama=False,
        output_root="data/processed/verified_v3_review",
        cli_flags=("--source-drafts-jsonl", "--accepted-baseline-run-id", "--out-dir", "--run-id"),
        run_stage_wired=True,
        notes="Chains run_step67_v2_postprocess_review_source.py -> "
        "run_step68_v2_review_packet_emission_from_postprocessed.py, exactly matching "
        "v3/jobs/04_review_packets.sbatch's own two-stage structure. This is the correct, final "
        "automated boundary for the verified-pipeline self-chain, matching "
        "step_06_9_review_audit_ingestion's own human_review_gate=True boundary in the old "
        "chain - review packets are for a human to review next, not something this pipeline "
        "auto-ingests verdicts for. Replaces step_06_7_postprocessed_review_source + "
        "step_06_8_review_packet_emission.",
    ),
}


def get_stage(stage_id: str) -> StageSpec:
    if stage_id not in STAGE_SPECS:
        raise KeyError(f"Unknown stage_id: {stage_id!r} (known: {sorted(STAGE_SPECS)})")
    return STAGE_SPECS[stage_id]


def ordered_stage_ids() -> list[str]:
    return [s.stage_id for s in sorted(STAGE_SPECS.values(), key=lambda s: s.order)]


def dependents_of(stage_id: str) -> list[str]:
    return [s.stage_id for s in STAGE_SPECS.values() if stage_id in s.depends_on]


def is_confirmed(stage_id: str) -> bool:
    """False for stages this session could not fully verify (unconfirmed CLI flags, missing
    script, or an unconfirmed registry mapping) - callers should refuse to run-stage these
    without explicit human confirmation first.
    """
    spec = get_stage(stage_id)
    return spec.invocation != "unconfirmed" and spec.cli_flags_confirmed
