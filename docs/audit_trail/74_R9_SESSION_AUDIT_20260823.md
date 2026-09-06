# R9 Session Audit: Latest-Pipeline Ablations and DOS Budget Matching

Created: 2026-08-23  
Local repo: `/path/to/local/checkout/kc_l_vnext_work`  
Primary original worktree (primary compute cluster): `/path/to/projects/kc_l_vnext_r8_20260822`  
Latest-pipeline worktree (primary compute cluster): `/path/to/projects/kc_l_vnext_r9_latest_20260822`  
Latest committed pipeline head used for rerun: `6ebcd7562ebaf8d2199b6a94eb7ec8836dd4300e`

This document records the Codex contributions in this session so a future agent can audit what was
changed, submitted, generated, verified, and left deliberately unresolved. Work performed before
context compaction is included from the handoff state and then cross-checked where possible.

## Principles Followed

- No hand repair of individual KC drafts.
- No domain-specific fine-tuning and no one-off per-KC fixes.
- R8/latest pipeline behavior was not edited during the experiment runs.
- Technical failures were preserved and recorded rather than patched away.
- Packet rebuilds were separated from draft-only submissions where the user explicitly requested reuse.
- DOS budget matching used same-model exact token accounting through Ollama `prompt_eval_count`; no character proxy was used.

## Local Files Added or Modified by Codex

The following files were added locally as R9 evaluation/job scaffolding. They are untracked in the
local git worktree unless committed later.

- `v3/jobs/r9_packets_domain.sbatch`
- `v3/jobs/r9_draft_kc_model.sbatch`
- `v3/jobs/r9_chain_watchdog.sbatch`
- `v3/jobs/r9_dos_budget_match.sbatch`
- `v3/jobs/r9_submit_requested_experiments.sh`
- `v3/jobs/r9_submit_latest_pipeline_experiments.sh`
- `v3/evaluation/build_dos_budget_matched_packets.py`
- `v3/evaluation/summarize_r9_experiments.py`
- `v3/evaluation/build_r9_audit_manifests.py`
- `v3/evaluation/build_r9_blind_judge_inputs.py`
- `v3/evaluation/build_r9_dos_reports.py`
- `v3/audit/74_R9_SESSION_AUDIT_20260823.md`

Validation performed locally:

- `python -m py_compile` passed for all new R9 Python helpers.
- `git diff --check` passed for the R9 Python/reporting edits checked during the session.

Validation performed on the primary compute cluster:

- `bash -n` passed for the R9 shell wrappers.
- R9 Python helpers compiled with `/path/to/venvs/kc_l_v2/bin/python` and
  `LD_LIBRARY_PATH=/path/to/software/python/python-3.11.3/lib`.

## Original R9 Chain Before Latest-Commit Rerun

Original run prefix:

`r9_20260822T040731Z`

Original worktree:

`/path/to/projects/kc_l_vnext_r8_20260822`

This chain rebuilt packets for data mining, sociology, and mathematics; drafted data mining with
Qwen 3.8, Gemma4, and DeepSeek; drafted sociology and mathematics with Qwen 3.8; and ran a DOS-RAG
Proposed-budget-matched experiment.

Original Slurm job outcomes:

| Job | Purpose | State | Elapsed | Node |
| --- | --- | --- | --- | --- |
| `249843` | data-mining packets | `COMPLETED` | `00:21:20` | `gpu01` |
| `249844` | sociology packets | `COMPLETED` | `00:30:01` | `gpu03` |
| `249845` | mathematics packets | `COMPLETED` | `00:06:37` | `gpu03` |
| `249846` | data-mining Qwen | `COMPLETED` | `01:57:51` | `gpu01` |
| `249847` | data-mining Gemma4 | `COMPLETED` | `02:43:59` | `gpu03` |
| `249848` | data-mining DeepSeek | `FAILED` | `06:14:19` | `gpu03` |
| `249849` | sociology Qwen | `COMPLETED` | `01:47:39` | `gpu01` |
| `249850` | mathematics Qwen | `FAILED` | `00:53:49` | `gpu03` |
| `249851` | original DOS matched gate | `FAILED` | `00:00:01` | `gpu03` |
| `249852` | original DOS matched draft dependency | `CANCELLED` | `00:00:00` | none |
| `249853` | original watchdog | `COMPLETED` | `07:13:56` | `cn189` |
| `249855` | DOS rerun1 gate | `FAILED` | `00:03:32` | `gpu01` |
| `249856` | DOS rerun1 draft dependency | `CANCELLED` | `00:00:00` | none |
| `249857` | DOS rerun1 watchdog | `COMPLETED` | `00:16:04` | `cn189` |
| `249941` | mathematics Qwen rerun1 | `FAILED` | `00:52:56` | `gpu01` |
| `249942` | DOS rerun2 gate | `FAILED` | `00:03:20` | `gpu03` |
| `249944` | DOS rerun2 draft dependency | `CANCELLED` | `00:00:00` | none |
| `249945` | DOS rerun2 watchdog | `COMPLETED` | `00:26:06` | `cn189` |
| `249952` | DOS rerun3 gate | `FAILED` | `00:06:43` | `gpu03` |
| `249953` | DOS rerun3 draft dependency | `CANCELLED` | `00:00:00` | none |
| `249954` | DOS rerun3 watchdog | `COMPLETED` | `00:01:03` | `cn189` |
| `249955` | DOS rerun4 gate | `COMPLETED` | `08:45:58` | `gpu03` |
| `249956` | DOS matched Qwen | `COMPLETED` | `01:36:48` | `gpu01` |
| `249957` | DOS rerun4 watchdog | `COMPLETED` | `10:10:53` | `cn189` |

Original output roots:

- Data mining:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/runs/r9_20260822T040731Z_datamining_r8`
- Sociology:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/runs/r9_20260822T040731Z_sociology_r8`
- Mathematics:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/runs/r9_20260822T040731Z_mathematics_r8`
- DOS matched experiment:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z_dos_budget_matched_rerun4`
- DOS matched run:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/runs/r9_20260822T040731Z_dos_budget_matched_rerun4_run`

Original descriptive summary:

`/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z/descriptive_metrics/summary.md`

Original descriptive outcomes:

| Arm | Packets | Draft rows | Grounded | Partial | Abstained | Hard failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `r9_datamining_qwen38` | 159 | 159 | 115 | 30 | 14 | 0 |
| `r9_datamining_gemma4` | 159 | 159 | 135 | 14 | 10 | 0 |
| `r9_datamining_deepseek` | 159 | 159 | 149 | 0 | 9 | 1 |
| `r9_sociology_qwen38` | 149 | 149 | 131 | 17 | 1 | 0 |
| `r9_mathematics_qwen38_rerun1` | 71 | 71 | 45 | 20 | 5 | 1 |
| `frozen_proposed_qwen38` | 159 | 159 | 120 | 25 | 14 | 0 |
| `frozen_dos_full_qwen38` | 159 | 159 | 124 | 19 | 14 | 2 |
| `dos_matched_qwen38` | 159 | 159 | 107 | 35 | 17 | 0 |

Preserved original technical failures:

- Data-mining DeepSeek: `KC_FSEL_STAT_002`, `runtime_error:TimeoutError`.
- Mathematics Qwen original and rerun: `KC_C00_007`, `unparseable_raw_response:JSONDecodeError`.
- Frozen DOS full: `KC_CLF_PRUNE_003` and `KC_CLF_NB_004`, both JSON parse failures.

Original DOS budget matching:

- Matched packets:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z_dos_budget_matched_rerun4/dos_matched_packets/kc_packets.jsonl`
- Budget manifest:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z_dos_budget_matched_rerun4/dos_budget_matching_manifest.csv`
- Technical summary:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z_dos_budget_matched_rerun4/technical_run_summary.json`
- Token counter: `ollama:qwen3.8:27b:generate_prompt_eval_count`.
- Mean matched/proposed token ratio: `0.8915295890696876`.
- Median matched/proposed token ratio: `0.9564102564102565`.
- Within 5 percent: 87 KCs.
- Within 10 percent: 111 KCs.
- Within 20 percent: 135 KCs.
- Integrity checks were clean: no frozen chunk mismatches, no non-subset violations, no ranked-prefix violations.

Original report artifacts generated/refreshed by Codex after compaction:

- DOS full-vs-matched CSV:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z/dos_reports/dos_full_vs_matched_manifest.csv`
- DOS known-case Markdown:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z/dos_reports/known_advantage_case_analysis.md`
- Blind judge inputs:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z/blind_judge_inputs_primary`
- Original audit manifests:
  `/path/to/projects/kc_l_vnext_r8_20260822/data/v3/experiments/r9_20260822T040731Z/audit`

The original DOS known-case report resolved all 11 requested known cases and added 5 automatic
grounded controls. No formal blind judge run was executed; only judge input manifests were built.

## Latest-Pipeline Correction

The user reminded Codex that all ablations must be run against the latest pipeline version. Codex
then compared the local and remote pipeline revisions.

Findings:

- Local latest branch HEAD:
  `6ebcd7562ebaf8d2199b6a94eb7ec8836dd4300e`.
- The original primary-cluster worktree HEAD was:
  `c3dd68552b840502d8b1f617332273de3fb4976c`.
- The original primary-cluster worktree also had an uncommitted INT-23 overlay in
  `v3/pipeline/02_build_kc_packets.py`, but it was not the latest committed branch state.

Because the user required latest-pipeline ablations, Codex created a separate clean latest worktree:

`/path/to/projects/kc_l_vnext_r9_latest_20260822`

The worktree was created at:

`6ebcd7562ebaf8d2199b6a94eb7ec8836dd4300e`

The latest submit wrapper:

`v3/jobs/r9_submit_latest_pipeline_experiments.sh`

Important wrapper behavior:

- Refuses to submit unless `git rev-parse HEAD` equals
  `6ebcd7562ebaf8d2199b6a94eb7ec8836dd4300e`.
- Rebuilds data-mining, sociology, and mathematics packets.
- Drafts data-mining Qwen/Gemma4/DeepSeek, sociology Qwen, and mathematics Qwen.
- Runs DOS budget matching only after the new data-mining packet rebuild completes.
- Passes the latest rebuilt Proposed packet file to DOS explicitly:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_datamining_latest/packets/kc_packets.jsonl`.

Latest packet job logs show `git` was unavailable on compute nodes, so `repo_head=` printed empty
inside Slurm logs. Provenance is still anchored by the submission manifest and code hashes. The
packet jobs logged:

- `packet_builder_sha256=cb54bc74ae1e521f43c25676ebc4b5c822bb5fa30949efd0c4dbf851932a2e57`
- `verifier_sha256=74d998b9c5d632270d0382d9171f882829f898ca91c9fcb6d2d943d102fc3f08`

The latest packet logs also show all INT-23 liveness checks passed, including:

- `INT23-1 an explicit modifier-matched foreign head is detected`
- `INT23-2 the decoy makes an otherwise substantive packet unsupported`
- `INT23-6 the packet builder calls the identity veto`
- `INT23-7 the mechanism contains no fixture or curriculum vocabulary`

## Latest-Pipeline Run

Run prefix:

`r9_latest_20260822T202514Z`

Submission manifest:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z/submission_manifest.json`

Final watchdog:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z/chain_status.txt`

Final chain status:

`RESULT: CHAIN FINISHED WITH FAILURES.`

This is expected because the user asked not to hide technical failures. The failed jobs still
produced draft rows and are represented in descriptive summaries.

Latest Slurm outcomes:

| Job | Purpose | State | Elapsed | Node |
| --- | --- | --- | --- | --- |
| `250260` | data-mining packets latest | `COMPLETED` | `00:21:19` | `gpu01` |
| `250261` | sociology packets latest | `COMPLETED` | `00:29:40` | `gpu02` |
| `250262` | mathematics packets latest | `COMPLETED` | `00:06:23` | `gpu02` |
| `250263` | data-mining Qwen latest | `COMPLETED` | `01:57:23` | `gpu01` |
| `250264` | data-mining Gemma4 latest | `COMPLETED` | `02:43:48` | `gpu03` |
| `250265` | data-mining DeepSeek latest | `FAILED` | `06:13:06` | `gpu03` |
| `250266` | sociology Qwen latest | `COMPLETED` | `01:52:59` | `gpu02` |
| `250267` | mathematics Qwen latest | `FAILED` | `00:54:36` | `gpu02` |
| `250268` | DOS matched-budget latest packet gate | `COMPLETED` | `08:48:32` | `gpu02` |
| `250269` | DOS matched-budget latest Qwen | `COMPLETED` | `01:36:27` | `gpu02` |
| `250270` | latest watchdog | `COMPLETED` | `10:48:39` | `cn092` |

Latest output roots:

- Data mining:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_datamining_latest`
- Sociology:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_sociology_latest`
- Mathematics:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_mathematics_latest`
- DOS matched latest:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_dos_budget_matched_latest_run`
- DOS experiment latest:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z_dos_budget_matched_latest`

Latest descriptive summary:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z/descriptive_metrics/summary.md`

Latest descriptive outcomes:

| Arm | Packets | Draft rows | Grounded | Partial | Abstained | Hard failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `latest_datamining_qwen38` | 159 | 159 | 115 | 30 | 14 | 0 |
| `latest_datamining_gemma4` | 159 | 159 | 135 | 14 | 10 | 0 |
| `latest_datamining_deepseek` | 159 | 159 | 149 | 0 | 9 | 1 |
| `latest_sociology_qwen38` | 149 | 149 | 131 | 17 | 1 | 0 |
| `latest_sociology_gemma4` | 149 | 149 | 138 | 10 | 1 | 0 |
| `latest_sociology_deepseek` | 149 | 149 | 148 | 0 | 1 | 0 |
| `latest_mathematics_qwen38` | 71 | 71 | 45 | 20 | 5 | 1 |
| `latest_mathematics_gemma4` | 71 | 71 | 57 | 11 | 3 | 0 |
| `latest_mathematics_deepseek` | 71 | 71 | 69 | 0 | 2 | 0 |
| `latest_dos_matched_qwen38` | 159 | 159 | 107 | 35 | 17 | 0 |

Latest preserved technical failures:

- Data-mining DeepSeek: one hard failure. This matches the earlier data-mining DeepSeek pattern.
- Mathematics Qwen: `KC_C00_007`, `unparseable_raw_response:JSONDecodeError`. This matches the
  earlier mathematics Qwen failure and was not hand-repaired.

## Extra Draft-Only Jobs Requested After Latest Chain Submission

The user then asked for additional draft-only ablations without rebuilding packets:

- Mathematics Gemma4.
- Mathematics DeepSeek.
- Sociology Gemma4.
- Sociology DeepSeek.

Codex verified that the latest-built packet files existed and that target draft outputs did not
already exist.

Packet files reused:

- Mathematics packets:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_mathematics_latest/packets/kc_packets.jsonl`
- Sociology packets:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_sociology_latest/packets/kc_packets.jsonl`

Extra job outcomes:

| Job | Purpose | State | Elapsed | Node |
| --- | --- | --- | --- | --- |
| `250456` | mathematics Gemma4 | `COMPLETED` | `01:06:20` | `gpu01` |
| `250458` | mathematics DeepSeek | `COMPLETED` | `02:42:42` | `gpu02` |
| `250459` | sociology Gemma4 | `COMPLETED` | `02:27:50` | `gpu03` |
| `250460` | sociology DeepSeek | `COMPLETED` | `04:51:18` | `gpu01` |

Extra output files:

- Mathematics Gemma4:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_mathematics_latest/drafts/kc_drafts_gemma4_31b.jsonl`
- Mathematics DeepSeek:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_mathematics_latest/drafts/kc_drafts_deepseek_r1_32b.jsonl`
- Sociology Gemma4:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_sociology_latest/drafts/kc_drafts_gemma4_31b.jsonl`
- Sociology DeepSeek:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_sociology_latest/drafts/kc_drafts_deepseek_r1_32b.jsonl`

These four extra jobs are included in the latest descriptive summary and latest audit manifests.

## Latest DOS Budget-Matched Experiment

Latest DOS experiment directory:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z_dos_budget_matched_latest`

Latest DOS run directory:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_dos_budget_matched_latest_run`

Key files:

- Technical summary:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z_dos_budget_matched_latest/technical_run_summary.json`
- Budget matching manifest:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z_dos_budget_matched_latest/dos_budget_matching_manifest.csv`
- Full-vs-matched manifest:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z_dos_budget_matched_latest/dos_full_vs_matched_manifest.jsonl`
- DOS matched packets:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_dos_budget_matched_latest_run/packets/kc_packets.jsonl`
- DOS matched Qwen drafts:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/runs/r9_latest_20260822T202514Z_dos_budget_matched_latest_run/drafts/kc_drafts_qwen38_27b.jsonl`

Latest DOS metrics:

- Units: 159.
- Token counter: `ollama:qwen3.8:27b:generate_prompt_eval_count`.
- Exact for Qwen 3.8 27B: true.
- Prompt handling: plain prompt string, no chat wrapper.
- Proposed tokens mean: `6985.987421383647`.
- DOS full tokens mean: `20178.075471698114`.
- DOS matched tokens mean: `6602.314465408805`.
- Matched/proposed token ratio mean: `0.892034911413631`.
- Matched/proposed token ratio median: `0.9569295708590636`.
- Within 5 percent: 88 KCs.
- Within 10 percent: 111 KCs.
- Within 20 percent: 135 KCs.
- Zero-chunk matched packets: 7.
- Full DOS smaller than Proposed budget: 0.
- Draft allowed by granularity gate: true.
- Integrity clean: no frozen full chunk text mismatches, no matched non-subset violations, no selected-prefix violations.

Latest DOS reports:

- CSV:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z/dos_reports/dos_full_vs_matched_manifest.csv`
- Markdown:
  `/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z/dos_reports/known_advantage_case_analysis.md`

## Latest Audit Manifests

Latest audit directory:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z/audit`

Files:

- `hash_manifest.json`
- `code_manifest.json`
- `environment_manifest.json`

Codex checked that `hash_manifest.json` contained no `"exists": false` entries after the latest
refresh.

## What Was Not Done

- No model fine-tuning was performed.
- No KC-specific repair or manual draft edit was performed.
- No old outputs were overwritten.
- No formal blind-judge scoring was run; only blind judge inputs were prepared for the original R9 primary comparison.
- No commit was made in the local repo.

## Current Final Status

As of the final check on 2026-08-23:

- `squeue` returned no rows for jobs
  `250260,250261,250262,250263,250264,250265,250266,250267,250268,250269,250270,250456,250458,250459,250460`.
- All packet rebuilds completed.
- All requested non-Qwen extra draft-only jobs completed.
- Latest chain completed with two preserved technical failures:
  data-mining DeepSeek and mathematics Qwen.

Future agents should start from the latest worktree and latest audit directory when comparing or
judging these ablations:

`/path/to/projects/kc_l_vnext_r9_latest_20260822/data/v3/experiments/r9_latest_20260822T202514Z`
