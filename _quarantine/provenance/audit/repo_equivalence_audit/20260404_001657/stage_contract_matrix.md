# Stage Contract Matrix

Format:
- Expected contract: what the downstream stage needs
- Old repo: whether the old repo code and durable files show that contract
- Clean repo: whether the clean repo still produces and consumes that contract consistently
- Judgment: preserved, preserved-but-hidden, repaired, broken, or not a direct handoff

## 1 -> 1.5

- Expected contract:
  - Step 1 emits a normalized hierarchy registry and manifest under `data/processed/hierarchy/<run_id>/`
  - Step 1.5 consumes raw hierarchy plus normalized registry, and optionally normalized manifest, to build overlay artifacts
- Evidence:
  - `steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py`
  - `steps/step_01_5_hierarchy_overlay/scripts/run_step01_5_hierarchy_overlay.py`
- Old repo:
  - Preserved and executable as a direct handoff
- Clean repo:
  - Same low-level scripts are retained
  - No clean public wrapper exposes this handoff, but the internal contract is unchanged
- Judgment:
  - Preserved internally

## 1.5 -> 2

- Expected contract:
  - There is no direct file or pointer handoff from Step 1.5 into Step 2
  - Step 2 is PDF/blockstore ingest; Step 1.5 overlay re-enters later at Step 6.6
- Evidence:
  - `steps/step_02_pdf_ingest_blockstore/resources/step2.default.yaml:6`
    - Step 2 only references a PDF path
  - `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml:5`
    - Step 6.6 is where `hierarchy_overlay_manifest` is consumed
- Old repo:
  - No direct 1.5 -> 2 contract in code
- Clean repo:
  - Same: no direct 1.5 -> 2 dependency exists
- Judgment:
  - Not a direct handoff
  - Any doc that implies a single linear 1 -> 1.5 -> 2 intake lane is simplifying two parallel upstream feeds

## 2 -> 3

- Expected contract:
  - Step 3 needs `data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt`
  - The target set JSON must enumerate docs and each doc must resolve to a valid Step 2 `processed_out_dir`
- Evidence:
  - `steps/step_03_doctree_index/resources/step3.default.yaml:5-10`
  - `steps/step_03_doctree_index/scripts/run_step3.py:36-42`
  - `steps/step_03_doctree_index/scripts/run_step3.py:171-172`
  - Old practical proof:
    - `data/processed/blockstore/_sets/2026-03-02_214129_step2_set.json:7-65`
    - `data/processed/doctree/_sets/2026-03-03_120609_step3_step3_set.json:6-75`
- Old repo:
  - In practice the contract existed and Step 3 consumed it
  - The tracked old `run_step2.py` did not itself emit the Step 2 set manifest, so fresh Step 2 -> Step 3 continuity depended on preexisting or externally created Step 2 set files
- Clean repo:
  - `steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py:35-160` now explicitly writes `ACTIVE_STEP2_SET.txt` and the Step 2 set JSON
  - Step 3 still consumes the same pointer contract
  - But the public clean input layout is mismatched with the retained Step 2 wrapper/config (`data/input/...` vs `data/raw/...`)
- Judgment:
  - Internal contract preserved and actually repaired
  - Advertised clean first-run continuity is broken because the new operator surface does not feed the retained Step 2 runner honestly

## 3 -> 3.5

- Expected contract:
  - Step 3.5 consumes active Step 2 and active Step 3 sets
  - It emits `data/processed/blockstore_enriched/_sets/ACTIVE_STEP3_5_SET.txt`
- Evidence:
  - `steps/step_03_5_blockstore_cleanup/resources/step3_5.default.yaml`
  - `steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py:34-40`
  - `steps/step_03_5_blockstore_cleanup/scripts/run_step3_5.py:94`
- Old repo:
  - Same script/config path preserved
- Clean repo:
  - Same script/config path preserved
- Judgment:
  - Preserved internally

## 3.5 -> 3.6

- Expected contract:
  - Step 3.6 consumes active Step 3.5 set
  - It emits `data/processed/blockstore_math_salvaged/_sets/ACTIVE_STEP3_6_SET.txt`
- Evidence:
  - `steps/step_03_6_math_salvage/resources/step3_6.default.yaml`
  - `steps/step_03_6_math_salvage/scripts/run_step3_6.py:61-63`
  - `steps/step_03_6_math_salvage/scripts/run_step3_6.py:121`
- Old repo:
  - Same low-level contract
- Clean repo:
  - Same low-level contract
- Judgment:
  - Preserved internally

## 3.6 -> 4

- Expected contract:
  - Step 4 consumes active Step 3 and active Step 3.6 sets
  - It writes retrieval-index outputs and a Step 4 set under `data/processed/retrieval_index/_sets`
- Evidence:
  - `steps/step_04_structure_retrieval_index/resources/step4.default.yaml:4-24`
  - `steps/step_04_structure_retrieval_index/scripts/run_step4.py:227-255`
- Old repo:
  - Same low-level contract
- Clean repo:
  - Same low-level contract
  - But the shipped default Step 4 config is not a real writing launch because `step4.default.yaml:21-22` sets `dry_run: true`
- Judgment:
  - Preserved internally
  - Default shipped config is not first-run executable without modification

## 4 -> 4.3

- Expected contract:
  - Step 4.3 is not a separate folder; it is the accepted retrieval-patch trace/replay lane
  - It consumes:
    - active Step 3 set
    - active Step 3.6 set
    - active Step 4 patches set
- Evidence:
  - `steps/step_04_2_patches/scripts/freeze_step4_patches_set.py`
    - writes `ACTIVE_STEP4_PATCHES_SET.txt`
  - `steps/step_04_structure_retrieval_index/scripts/run_step4_3.py:607-609`
    - resolves active Step 3, Step 3.6, and Step 4 patches sets
- Old repo:
  - Same low-level 4.x contract
- Clean repo:
  - Same low-level 4.x contract
  - The public clean operator surface does not mention this subladder
- Judgment:
  - Preserved internally but hidden

## 4.3 -> 4.5

- Expected contract:
  - Step 4.5 consumes Step 4 active set plus the frozen Step 4 patches set
  - It writes `data/processed/retrieval_sentence_overlay/_sets/ACTIVE_STEP4_5_SENTENCE_SET.txt`
- Evidence:
  - `steps/step_04_5_sentence_overlay/resources/step4_5.default.yaml`
  - `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py:548-577`
  - `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py:809-836`
  - `steps/step_04_5_sentence_overlay/scripts/run_step4_5.py:871`
- Old repo:
  - Same low-level contract
- Clean repo:
  - Same low-level contract
- Judgment:
  - Preserved internally

## 4.5 -> 5

- Expected contract:
  - Step 5 consumes active Step 4 retrieval set and a KC registry
  - It emits `data/processed/kc_evidence/_sets/ACTIVE_STEP5_EVIDENCE_SET.txt`
- Evidence:
  - `steps/step_05_kc_evidence_mining/resources/step5.default.yaml:5-22`
  - `steps/step_05_kc_evidence_mining/scripts/run_step5.py:775-776`
  - `steps/step_05_kc_evidence_mining/scripts/run_step5.py:1031`
- Old repo:
  - Same contract and historical artifact path
- Clean repo:
  - Same contract is retained
  - But the default config still hardcodes `kc_registry_path: data/processed/hierarchy/20260228T211719Z/kc_registry.jsonl`
- Judgment:
  - Preserved internally
  - Not clean-first-run equivalent because the shipped config is historically pinned

## 5 -> 5.2

- Expected contract:
  - Step 5.2 consumes active Step 4 and active Step 5 baseline
  - It emits `data/processed/kc_evidence_sharp/_sets/ACTIVE_STEP5_2_EVIDENCE_SHARP_SET.txt`
- Evidence:
  - `steps/step_05_2_evidence_sharpen/resources/step5_2.default.yaml:5-7`
  - `steps/step_05_2_evidence_sharpen/scripts/run_step5_2.py:772-781`
  - `steps/step_05_2_evidence_sharpen/scripts/run_step5_2.py:1116`
- Old repo:
  - Same low-level contract
- Clean repo:
  - Same low-level contract
  - Same hardcoded historical `kc_registry_path`
- Judgment:
  - Preserved internally
  - Historically pinned, not clean-first-run equivalent

## 5.2 -> 5.3

- Expected contract:
  - Step 5.3 consumes active Step 4.5 and active Step 5.2
  - It emits `data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt`
- Evidence:
  - `steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml:5-8`
  - `steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py:984-1007`
  - `steps/step_05_3_evidence_recalibrated/scripts/run_step5_3.py:1346`
- Old repo:
  - Same low-level contract
- Clean repo:
  - Same low-level contract
  - Same hardcoded historical `kc_registry_path`
- Judgment:
  - Preserved internally
  - Historically pinned, not clean-first-run equivalent

## 5.3 -> 6.6

- Expected contract:
  - Step 6.6 consumes active Step 4, active Step 4.5, active Step 5.3, and hierarchy overlay artifacts
  - It emits a Step 6.6 set manifest under `data/processed/kc_drafting_input_overlay/_sets`
- Evidence:
  - `steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.full128.yaml:2-12`
  - `steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py:126-147`
  - `steps/step_06_6_kc_drafting_input_overlay/scripts/run_step6_6_kc_drafting_input_overlay.py:249-285`
- Old repo:
  - Same low-level contract
- Clean repo:
  - Same low-level contract
  - But the shipped config is historically pinned to:
    - active Step 4 pointer
    - active Step 4.5 pointer
    - active Step 5.3 pointer
    - dated `hierarchy_overlay_manifest`
    - a fixed 128-KC exact slice
- Judgment:
  - Preserved internally
  - Not clean-first-run equivalent because the shipped config is historically pinned

## 6.6 -> 6.7

- Expected contract:
  - Step 6.7 consumes a Step 6.6 set manifest and emits a Step 6.7 set manifest under `data/processed/kc_drafts/_sets`
- Evidence:
  - `steps/step_06_7_kc_draft_generation/resources/step6_7.full128.yaml:2-5`
  - `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py:111-112`
  - `steps/step_06_7_kc_draft_generation/scripts/run_step6_7_kc_draft_generation.py:178-205`
  - Old removed surface:
    - `run_step6_7_model_draft_generation.py:28-110`
- Old repo:
  - Same internal non-model wrapper existed
  - Plus an additional root model-backed wrapper and root YAML family
- Clean repo:
  - Same internal non-model wrapper survives
  - Root model-backed launcher and root YAML family are gone
  - The shipped `step6_7.full128.yaml` is pinned to a dated Step 6.6 set manifest
- Judgment:
  - Partially preserved
  - Contract survives internally, but the calibrated root launch surface was lost and the default resource is historically pinned

## 6.7 -> 6.8

- Expected contract:
  - Step 6.8 consumes a Step 6.7 set manifest plus active Step 4 and Step 4.5 pointers
  - It emits a Step 6.8 review-packet set manifest
- Evidence:
  - `steps/step_06_8_kc_review_packet_emission/resources/step6_8.full128.yaml:2-5`
  - `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py:115-129`
  - `steps/step_06_8_kc_review_packet_emission/scripts/run_step6_8_kc_review_packet_emission.py:192-220`
- Old repo:
  - Same internal contract
  - Root Step 6.7 model-backed launcher and root YAML family were still present nearby
- Clean repo:
  - Same internal Step 6.8 runner survives
  - The shipped `step6_8.full128.yaml` is pinned to a dated Step 6.7 set manifest
- Judgment:
  - Partially preserved
  - Internal contract survives, but the late-stage chain remains historically pinned and no longer has its old root wrapper ecosystem

## Bottom line

- The internal step ladder from Step 3 onward is mostly preserved.
- The clean repo's real contract break is not wholesale code deletion; it is the mismatch between:
  - the new public operator/control-plane story
  - the retained legacy execution contracts
  - the historically pinned resource YAMLs that still assume old processed artifacts
