# Handoff: KC Library v3 drafting-quality investigation — continuation brief

You are picking up an in-progress investigation from another agent (Claude) whose context ran out.
This file is the full context. Read it completely before doing anything. Do not ask the user to
re-explain what's below — it's all here. The user will separately hand you a fresh draft-output
analysis and a historical-run comparison; your job starts for real once you have that, using the
protocol in §7.

## 0. Non-negotiable constraints (violating any of these invalidates the work)

1. **Mirror-only.** All work happens in `/path/to/kc_l`
   on the Cluster B HPC cluster. The production copy, `/path/to/shared`,
   must **never** be written to. Read-only reference at most (e.g. the sentence corpus it hosts).
2. **Full authority within the mirror.** You have standing permission to rewrite, delete, or
   redesign anything inside the mirror without asking first.
3. **Domain agnosticity.** Every pipeline logic component (retrieval, admission, drafting,
   validation) must stay domain-agnostic — no hardcoding to this particular course's subject
   matter. Fixes should key off structural/syntactic signals (passage shape, citation patterns,
   sentence structure), not topic content.
4. **No false evidence — the top standing principle.** The whole multi-week effort behind this
   codebase is reducing hallucination/contamination in generated Knowledge Component descriptions
   **without collapsing legitimate recall or coverage**. Every fix must be checked against both
   failure directions: does it stop a bad thing, and does it also avoid quietly deleting a good
   thing. A fix that "fixes" contamination by being overly aggressive and starving legitimate
   evidence is not a fix.
5. **Commit discipline.** Every meaningful change gets its own commit with a detailed,
   evidence-based commit message (what was found, how it was found, what changed, what was
   verified) — not just "fix bug". See §6 for the exact mechanical pattern; heredocs mangle these
   messages through nested ssh/bash layers, so don't use them.

## 1. Access

- SSH alias: `cluster-b` (already configured, passwordless).
- Mirror repo root: `/path/to/kc_l` — this is a real git
  repo, work in a clean tree, commit as you go.
- Python: use `/path/to/venv/bin/python`, and **always** set
  `LD_LIBRARY_PATH=/path/to/python/lib` first, or the interpreter fails
  with `libpython3.11.so.1.0: cannot open shared object file`. System `python3` on login/compute
  nodes is a different, unusable build — don't use it.
- For any real module-level verification, set `PYTHONPATH=$MIR/src` too.
- SLURM: `sbatch`, `squeue -u clusteruser`, `sacct -j <id> --format=...`, `scancel <id>`.

## 2. What this pipeline is

A 5-stage pipeline that turns a hierarchy of "Knowledge Components" (KCs) and "topics" (KC groups)
plus a sentence-level source corpus into LLM-drafted descriptive text per unit, validated and
packaged for expert review:

1. **Packets** (`01_packets.sbatch` → `steps/step_05x_kc_evidence_stage_v3` and
   `step_06_7_hierarchy_aware_synthesis_packets`, core logic in
   `src/kc_l/retrieval_gate/evidence_pack.py`) — retrieves and admits evidence passages per unit
   from the sentence corpus, builds a "packet" (canonical_name, aliases, hierarchy,
   sibling_kc_names, rival_units_considered, admitted evidence passages) per KC/topic. This is
   where essentially all of the v3–v43 fix cycle happened — passage admission, rival-stripping,
   dedup, truncation-budget handling.
2. **Draft generation** (`02_draft_kc_<model>.sbatch` / `03_draft_topics.sbatch`, driver
   `v3/pipeline/04_draft_runner.py`) — calls an LLM (via local Ollama) per packet to produce a
   `contextual_kc_draft` (or `contextual_topic_draft`): status (`grounded`/`partial`/`abstained`),
   descriptive text, `evidence_map`, plus `segmentation_support` and `evaluation_support` (cues
   for downstream dialogue-segmentation and tutoring use — see §8 for why these exist and their
   current state). Validated by `validate_output()`; some structural-only issues are eligible for
   an automatic follow-up repair call, gated by `should_attempt_schema_repair()`.
3. **Review packaging** (`04_review_packets.sbatch`) — postprocesses drafts into review packets
   (`review_packets.jsonl`), flags evidence-reference issues, assigns a reviewer action.
4. **Register** (`05_register.sbatch`) — records run completion in `RUN_STATE.json`.

Three drafting models are run in parallel/independent SLURM jobs against the same packets, as an
ablation: `gemma4:31b` (primary/baseline — this is what feeds review+register), `qwen3.6:27b`, and
`command-r:35b` (slowest, `--time=24:00:00` vs 12h for the others).

Unit types: `kc` (leaf Knowledge Components) and `topic` (groups of KCs). They have similar but
not identical schemas — topic units use `contextual_topic_draft` instead of `contextual_kc_draft`,
and `segmentation_support` uses different field names
(`topic_matching_cues`/`child_kc_boundary_cues`/`do_not_confuse_with_topics` vs KC's
`matching_cues`/`likely_dialogue_surface_forms`/`sibling_contrast_notes`/`do_not_confuse_with`).
**Getting unit-type branching right matters more for topics than for KCs**, because
`should_attempt_schema_repair()` unconditionally returns `False` for any non-`kc` unit on its
first line — there is no repair safety net for topics, so first-pass prompt correctness is the
only thing that matters for them.

## 3. Full fix history (v3–v43) — what's already been done

The authoritative record is `v3/evaluation/FAILURE_CYCLE_2.md` (currently ~1105 lines, sections
0–20) in the mirror repo. **Read it in full before forming any hypothesis about a new failure** —
it is entirely possible a failure you're looking at is a known, already-reasoned-about residual
(§18 documents several explicitly, e.g. the topic-level region-resort question), not a new bug.

Condensed timeline (commit hash → what it fixed):

| Commit | Fix |
|---|---|
| `c73e9fc` | v3: coherent tree and honest names (early baseline) |
| `87667dd` | v22+v23: per-block-member evidence verification, block-splicing contamination |
| `0edf99d` | v24 math variant selection, v26 competitive assignment, v27 built |
| `e6cfb4b` | v28: reject corrupted math + no-fabrication drafting contract |
| `7a30077` | v25 bugfix: payload admission was being reversed by whole-passage re-verification |
| `08fdf89` | v29: truncated-mid-formula detection |
| `148b0eb` | v30 shattered-citation rejection, v31 severed-clause rejection, v32 status rubric |
| `6f829a0` | v33 narrower foreign-method rejection, v34 compound-name equation recovery, control-byte fixes |
| `119f3d7` | v35: forward-truncated ("front-severed") fragment rejection — largest single finding, 133/159 units affected |
| `852e7b1` | v36: bare trailing colon recognised as a lead-in |
| `32f3736` | v37: name-anchored defining equations exempt from v26 rival-stripping (v34 was silently self-defeating) |
| `f2a8c1c` | v38+v39: close rest of rescue-exemption gap + a separate silent-drop bug |
| `ad8dbd1` | v40: exempt formula-shaped candidates from v31's severed-fragment check |
| `e3ccfb2` | v41: rescue admission_basis survives deduplicate_passages(), not just the merge-winner's own basis |
| `279254a` | v42: protect rescue-basis passages from max_passages budget truncation (found via structural inventory, not hypothesis-testing — see §16) |
| `1bb86de` | v43: segmentation_support/evaluation_support populated for every unit including abstained ones (draft-runner prompt + repair-gating change, not a packets/evidence change) |
| `7dcf6db` | infra (not a numbered "v" fix): archive each draft run's output job-ID-stamped so resubmissions stop overwriting history (see §6.7 below) |

`FAILURE_CYCLE_2.md` §19 has the same table with fuller descriptions and reasoning pointers. §20
is a 23-item checklist titled "what the next draft needs to confirm" — **this is very likely
exactly what the user's incoming draft-analysis will be validating against.** Start there.

## 4. The established protocol — how this project does fixes

This is the actual "how we did it before" the user is asking you to continue. Follow it exactly;
it is not incidental style, it's load-bearing for the project's credibility (this feeds a thesis).

**A. Diagnose against real evidence, never assumption.** Every fix in the history above traces to
either a specific real unit's real packet content, read directly, or a mechanical/structural
inventory of the code (see §16 in the report for what that looks like: instead of hypothesizing
"maybe X is the bug", enumerate every function that touches the relevant code path and check each
one's actual behavior against real data). Do not theorize about what might be wrong — open the
actual packet/draft JSONL and look.

**B. Cluster, don't fix one-off.** When multiple units show a similar-shaped failure, name the
cluster (the report uses "cluster 3", "cluster 4" for two recurring evidence-shape failure
families) and diagnose unit-by-unit within it before writing one fix that's supposed to cover the
whole cluster. Then verify the fix against every member of the cluster, not just the first one you
saw.

**C. A fix needs either a demonstrated case or an explicit checked reason it doesn't apply.**
Per §19's closing paragraph: nothing ships without one of those two. If you find a theoretical risk
that isn't actually manifesting in real data, say so explicitly and record why (the report does
this for the topic-level region-resort question in §16 — checked, reasoned about, left open, not
silently dropped).

**D. Regression-guard everything.** Before shipping a fix, re-check every previously-fixed case
it could plausibly interact with. v37 exists because v34's fix was being silently defeated by v26;
that class of self-defeating-fix bug is exactly what you're being asked to hunt for now ("how many
fixes didn't work last time").

**E. Verify via real execution, never `ast.parse` alone.** `ast.parse` only checks syntax; it will
not catch a `NameError` from a missing import (this happened once already — see §17/commit
`052746b`, a harness gate that passed on `ast.parse` while the real job crashed 9 seconds in).
Always verify a patched function by actually importing and calling it:
```python
import importlib.util
spec = importlib.util.spec_from_file_location("mod", "/path/to/file.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)   # this is what actually catches NameErrors etc.
# then call the specific function(s) you changed with real or realistic inputs
```
Also scan any file you touch for stray control bytes (`[\x00-\x08\x0b\x0c\x0e-\x1f]` regex) — this
project has hit silent control-byte corruption more than once.

**F. Patch mechanically, not via inline heredoc edits over ssh.** The reliable pattern, used for
every fix in this history:
1. Write a local `.py` patch script containing `OLD`/`NEW` string constants and
   `assert t.count(OLD) == 1, ("anchor", t.count(OLD))` before every `.replace()` — this fails
   loudly instead of silently no-op'ing or double-patching if the anchor text doesn't match
   exactly once.
2. `scp` it to the remote host.
3. Run it via plain `ssh cluster-b "python3 /tmp/patch_x.py"` (or the venv python + LD_LIBRARY_PATH
   per §1 if plain `python3` fails).
4. Verify per §4E.

**G. Commit messages via file, never inline heredoc.** A `"` or backtick inside a commit message
reliably gets mangled through nested ssh/bash/heredoc layers (happened twice in this project).
Pattern: Write the full message to a local `.txt` file → `scp` it to the remote → `git commit -F
that_file.txt`. If a truncated message somehow lands anyway, fix with
`git commit --amend -F <fixed_file>` rather than re-doing the diff.

**H. Document every fix in `FAILURE_CYCLE_2.md` as you go**, not in a batch at the end. New
fixes get a new `## N.` section (continue the existing numbering — don't renumber existing
sections unless you're inserting; if you do insert, fix every internal `§N` cross-reference and
verify with `grep -n "^## "` before committing). Each entry should read like the existing ones:
what was found, how (unit-by-unit or structural-audit), the fix, and what was verified.

**I. Rebuilds are expensive — justify each one individually.** Six full packet rebuilds happened
across the v35–v42 cycle, each justified separately at the time rather than batched "to be safe".
Don't cancel/resubmit a running job speculatively; if you change something in
`evidence_pack.py`, you need a fresh packets rebuild before any draft run reflects it — plan fix
batches with that cost in mind, similar to the shape of what already happened (a few
close-together numbered fixes landing before one rebuild, not one rebuild per line changed).

## 5. SLURM / cluster-specific gotchas (learned the hard way this cycle)

- **Progress-tracking JSON files are unreliable across resubmissions.**
  `STEP67_V2_TINY_SMOKE_PROGRESS.json` inside each model's work dir (`kc_work_<model>/`) is keyed
  by a fixed `run_id` string, not the SLURM job ID, and gets **overwritten in place** by every
  resubmission. Before trusting one, check its `created_utc` / mtime against wall-clock `date -u`
  — a stale file from an earlier attempt looks present-but-wrong, not absent.
- **GPU offload can silently fail per-node.** `ollama_serve.log` inside a model's work dir is
  ground truth: `grep -i offloaded ollama_serve.log` should show e.g. `"offloaded 61/61 layers to
  GPU"` and `device=CUDA0`. If it shows `"offloaded 0/N layers to GPU"` and `device=CPU`, that job
  is running 100% on CPU — SLURM state will still say `RUNNING` and give no other signal. This
  happened for real on node `gpu03` this cycle (cost ~2h47m before caught; projected ~18 days to
  finish 159 units if left running). Fix was `--exclude=gpu03` on resubmission. **Check this
  proactively ~90s after any drafting job transitions to RUNNING**, don't wait for it to surface
  on its own.
- **"Priority" ≠ hard dependency.** If asked to run jobs "in priority order" opportunistically
  across free GPUs (not "wait for the previous one to fully finish"), use `--nice=<N>` (lower =
  higher priority) on independent job submissions, not `--dependency=afterok:<id>`. A hard
  dependency chain means job 2 cannot even *start* until job 1 fully completes — that's a
  meaningfully different scheduling behavior and was an actual miscommunication caught and
  corrected once already this cycle. If genuinely unsure which the user means, ask.
- **Final draft output files get overwritten by every resubmission of the same stage** (the
  `$FINAL` path is keyed by the fixed `$RUN`, e.g. `kc_drafts.jsonl`, not by job ID) — as of commit
  `7dcf6db` all four draft sbatch scripts now also write a permanent, job-ID-stamped copy to
  `$DATA/drafts/archive/<final-basename>_job<jobid>.jsonl` (+`_summary.json`) right after `$FINAL`
  is confirmed non-empty. This is new as of this handoff — any draft job submitted *before*
  `7dcf6db` landed does **not** have this (SLURM snapshots the script at submission time), so if
  you find a completed run without a matching archive entry, back it up manually the same way
  before it can get overwritten by a future resubmission.
- **Local monitoring infrastructure (if you use anything analogous) can crash independently of
  the real remote jobs.** Always verify via a direct one-off `sacct`/`squeue` call before treating
  monitor silence as a job problem.

## 6. State as of this handoff (2026-08-14)

Current/most recent run: `v3_20260812` (run_id — note the name is the date the run was first
created, not a per-attempt identifier; see the archive-overwrite gotcha above).

| Model/stage | Job ID | State at handoff | Final output path |
|---|---|---|---|
| gemma4 (kc) | 245232 | COMPLETED | `data/v3/runs/v3_20260812/drafts/kc_drafts.jsonl` (159 rows) |
| gemma4 (topics) | 245233 | COMPLETED | `data/v3/runs/v3_20260812/drafts/topic_drafts.jsonl` (22 rows) |
| qwen | 245182 | COMPLETED | `data/v3/runs/v3_20260812/drafts/kc_drafts_qwen36_27b.jsonl` (159 rows) |
| command-r | 245183 | **check `sacct -j 245183` — was still RUNNING (~76%+ done) as of handoff** | `data/v3/runs/v3_20260812/drafts/kc_drafts_command_r_35b.jsonl` (stale until it completes — see below) |
| review | 245234 | COMPLETED | `data/v3/runs/v3_20260812/review/review_packets.jsonl` (159 rows) |
| register | 245235 | COMPLETED | `data/processed/runs/v3_20260812/RUN_STATE.json` |

**If command-r (245183) has finished by the time you read this**: (1) confirm
`data/v3/runs/v3_20260812/drafts/kc_drafts_command_r_35b.jsonl` mtime is recent (post-handoff), not
the stale Aug-13 16:37 copy from a prior attempt (job 244582); (2) if it doesn't already have a
matching entry in `data/v3/runs/v3_20260812/drafts/archive/`, copy it there manually (job ID
suffix), since 245183 predates the archive-fix and won't have self-archived.

**gemma4 final numbers (245232, the primary/baseline model, all fixes through v43):** grounded 118
(74.2%), partial 27 (17.0%), abstained 14 (8.8%), 0 hard failures.
**qwen final (245182):** grounded 114 (71.7%), partial 32 (20.1%), abstained 13 (8.2%), 0 hard
failures.
Both are already-completed final data you can start clustering against immediately, independent of
whatever the user hands you.

**v43 already verified against real gemma4 output**: `segmentation_support` is 159/159 (100%,
including all 14 abstained units — this was the point of v43). `evaluation_support` is present
(never `None`) on all 159, populated with real content on all 145 non-abstained units, and **is an
empty-but-present dict (all four sub-lists `[]`) on all 14/14 abstained units** — assessed as
likely correct (genuine abstentions plausibly have nothing defensible to say pedagogically either),
matching every `repair_attempted=False` and no `evaluation_support_missing` validation issue on any
of them. But 14/14 uniform emptiness was flagged as "worth scrutiny" and not independently
re-confirmed unit-by-unit — worth a second look with fresh eyes once you have the fuller draft
analysis, per protocol §4A (real evidence, not assumption).

**Historical gemma4 run-to-run trend** (reconstructed from job `.log` files, which persist by job
ID even though data files don't — see §5's archive-overwrite gotcha):

| Job | Started | Packets fix-level | grounded | partial | abstained | mean draft len |
|---|---|---|---|---|---|---|
| 244437 | Aug 12 16:58 | v3 only | 78.0% | 15.7% | 6.3% | 1284 ch |
| 244524 | Aug 12 22:42 | +v22–v23 | 71.1% | 23.3% | 5.7% | 942 ch |
| 244581 | Aug 13 04:53 | +v24–v28 | 64.8% | 28.9% | 6.3% | 864 ch |
| 245232 (current) | Aug 14 01:37 | full v3–v43 | 74.2% | 17.0% | 8.8% | 838 ch |

Two cancelled/discarded gemma4 attempts in between (244963 — cancelled, no output; 245095 — the
gpu03 CPU-only incident from §5, cancelled once diagnosed) are not comparable, no valid output.

## 7. The task now

The user will hand you (a) a fresh analysis of the current draft output and (b) a comparison
against historical runs (likely similar in shape to §6 above, possibly deeper). Once you have it:

1. **Read `FAILURE_CYCLE_2.md` in full first** if you haven't. Cross-reference every failure you
   see in the new analysis against it — many things that look like new bugs may be documented,
   reasoned-about, already-known residuals (§18 especially).
2. **Work through the §20 checklist (23 items) systematically** — this is literally titled "what
   the next draft needs to confirm" and was written for exactly this moment. For each item,
   determine: confirmed fixed / still broken / can't tell from available data.
3. **For every item that's still broken**: that's a fix that "didn't work last time" — this is
   the user's explicit ask ("see how many of the fixes didn't work last time and fix them all").
   Diagnose it the same way every prior fix was diagnosed (§4A/§4B: real evidence, unit-by-unit
   or structural audit, not hypothesis-guessing), and check specifically whether it's:
   - the original fix logic being wrong (rare — most were tested at the time), or
   - a **self-defeating-fix** interaction, i.e. a later or sibling piece of code silently
     undoing an earlier, already-verified fix's effect (this is the single most common root
     cause found across this whole cycle — v37, v38, v39, v40, v41 are ALL instances of exactly
     this pattern: an earlier fix (v26, v31, v34...) working correctly in isolation but being
     defeated by a different function elsewhere in the same pipeline). Actively hunt for this
     pattern first, not last.
4. **Cluster new failures** the same way §7 and §11 do for clusters 3/4 — name the cluster,
   diagnose each member, fix once per cluster, verify against every member.
5. **Ship fixes following §4's protocol exactly**: real-execution verification, patch pattern,
   commit-message pattern, regression guards, `FAILURE_CYCLE_2.md` documentation as you go
   (continue the numbering from `## 20.` → add `## 21.` etc., or follow whatever the current tip
   of the report looks like when you start — check `grep -n "^## " FAILURE_CYCLE_2.md` first).
6. **Note v43 and the archive-infra change (`7dcf6db`) are not yet written up in
   `FAILURE_CYCLE_2.md` at all** — §19's commit table and the section list stop before them. Add
   the missing documentation for both as part of your first commit batch, before or alongside new
   fixes, so the report stays a complete record. v43's rationale/verification detail (for writing
   this section) is in §3 of this handoff file if you don't have it elsewhere.
7. Once new fixes are shipped and a packets rebuild is justified (§4I), resubmit the draft
   chain(s) needed to validate them, using the SLURM patterns in §5, and confirm the specific
   units/clusters that were failing are now fixed, without regressing anything in §20's
   already-confirmed items.

## 8. Other loose ends, not blocking, worth knowing about

- **Frozen-library bundling** (a direct user directive from earlier this cycle): "all KCs should
  have `segmentation_support`/`evaluation_support` regardless of abstention" is done (v43).
  "Bundle it with the frozen library instead of a separate file" is *structurally* already true —
  these fields live inside the same per-unit `draft` object that flows through into
  `review_packets.jsonl`, not a separate file. But there is no distinct "frozen library" export
  stage in this pipeline at all yet (`review_packets.jsonl` is the current terminal artifact) — if
  a consolidation/export stage gets built later, these fields are already embedded per-unit and
  will carry through automatically. This is an open design question the user hasn't been asked to
  resolve yet, not a bug.
- **Known, not-yet-fixed inconsistency, out of scope so far**: `build_required_output_schema()` in
  `04_draft_runner.py` (used only by the KC-only repair path, a different function from the real
  first-pass schema inside `build_prompt()`) has a topic branch that's missing
  `segmentation_support` entirely, out of sync with the real schema. Discovered incidentally while
  fixing v43, not yet fixed since it's the repair path (KC-only anyway, so it doesn't affect topic
  drafting) rather than first-pass generation. Worth fixing for consistency but wasn't blocking
  anything real.

## 9. Key absolute paths

```
Mirror repo root:      /path/to/kc_l
Production (READ ONLY, never write): /path/to/shared
Report:                 v3/evaluation/FAILURE_CYCLE_2.md
Draft-runner (drafting prompt/validation logic): v3/pipeline/04_draft_runner.py
Evidence/admission logic:  src/kc_l/retrieval_gate/evidence_pack.py
Draft sbatch jobs:      v3/jobs/02_draft_kc_gemma4.sbatch, 02_draft_kc_qwen36.sbatch,
                         02_draft_kc_commandr.sbatch, 03_draft_topics.sbatch
Review/register jobs:   v3/jobs/04_review_packets.sbatch, 05_register.sbatch
Current run data root:  data/v3/runs/v3_20260812/
  packets:               data/v3/runs/v3_20260812/packets/kc_packets.jsonl
  gemma4 kc drafts:       data/v3/runs/v3_20260812/drafts/kc_drafts.jsonl
  gemma4 topic drafts:    data/v3/runs/v3_20260812/drafts/topic_drafts.jsonl
  qwen drafts:            data/v3/runs/v3_20260812/drafts/kc_drafts_qwen36_27b.jsonl
  command-r drafts:       data/v3/runs/v3_20260812/drafts/kc_drafts_command_r_35b.jsonl
  archive (new):          data/v3/runs/v3_20260812/drafts/archive/
  review packets:         data/v3/runs/v3_20260812/review/review_packets.jsonl
Job logs (persist by job ID, useful for historical reconstruction):
                         v3/logs/0N_<stage>_<jobid>.log
Python venv:             /path/to/venv/bin/python
Required env:            LD_LIBRARY_PATH=/path/to/python/lib
                         PYTHONPATH=<mirror>/src  (for module-level verification)
```
## 10. Run/folder naming convention — non-destructive, learned from production

**Standing rule, as of 2026-08-15: nothing under `data/v3/runs/` (or any pipeline output tree)
gets overwritten or deleted by an automated process, ever.** Every new run, every new model added
to an existing run, every redo of a stage gets its own directory or its own file. Deletion only
happens when the user does it manually or explicitly asks for it. This applies to *you* (whoever
is reading this) as much as it did to the agent that wrote it.

This isn't a new invention — it's how the production repo (`kc_l_v2_clean`) has always worked.
Its `data/processed/` directory has dozens of stage-output directories going back to July,
none deleted, following two patterns worth copying exactly:

1. **A stage that gets meaningfully redone gets a new sibling directory with a descriptive
   qualifier**, not a rebuild in place: `kc_evidence` → `kc_evidence_sharp` →
   `kc_evidence_recalibrated`, `kc_review_packets_restarted`, etc. The qualifier describes *what's
   different about this attempt* (sharper thresholds, recalibrated scoring, restarted from a
   checkpoint) — not just a counter.
2. **Anything tied to a specific input snapshot is named `<ISO8601Z-timestamp>_<short-content-hash>`**
   (e.g. `20260809T140541Z_01d6072f`), with a trailing `_v2` etc. if that exact snapshot needs a
   second pass. This is exactly where the sociology run's own folder name
   (`v3_20260815_sociology_20260809T140541Z_01d6072f_004108`) got its suffix from — it's already
   following this convention, correctly.

**Apply this pattern to every new `data/v3/runs/<name>` you create.** Minimum bar: the name must
encode (a) which domain/corpus it's for — never a bare date with no domain, that's how the
original `v3_20260812` name became ambiguous once a second domain existed — and (b) enough to
tell it apart from every other run touching the same domain. Prefer carrying the actual source
corpus's timestamp+hash through when one exists, the way the sociology run does.

**Within a run directory, every model/variant gets its own path, never a shared one.** This project
already does this at the KC-draft level (`kc_work_gemma4_31b/` vs `kc_work_qwen36_27b/` vs
`kc_work_deepseek_r1_32b/`, `kc_drafts.jsonl` vs `kc_drafts_qwen36_27b.jsonl` etc.) — when adding a
new model/stage anywhere in the pipeline (this project just did it for topics: added
`v3/jobs/03_draft_topics_qwen36.sbatch`, writing to `topic_work_qwen36_27b/` and
`topic_drafts_qwen36_27b.jsonl`, deliberately never touching the existing `topic_work/` /
`topic_drafts.jsonl` gemma4 paths under the same run), keep that pattern: a distinct, model-named
path, plus the job-ID-stamped archive copy under `drafts/archive/` that every draft sbatch script
now writes automatically (§5 already covers the archive mechanism itself — this section is about
never colliding with a sibling model's paths in the first place, which the archive mechanism alone
doesn't protect against).

**Multiple domains are now active in parallel — don't assume `v3_20260812` is the only run.** As of
this addendum there are at least three: the original ML/"data mining" domain (`v3_20260812`, plus
an isolated 3-model re-run at `v3_20260814_draft_3models_232029` after v47 required a packet
rebuild), a "sociology" domain (`v3_20260815_sociology_20260809T140541Z_01d6072f_004108`, built
from a pre-existing prepared corpus, not a fresh ingestion), and a "mathematics" domain (full fresh
pipeline from raw PDF ingestion, steps 02→03→03.5→03.6→04→04.3→04.5→05p, still in progress as of
this writing — do not submit its drafting stage until its packets stage has actually completed and
you can point a real `--dependency=afterok:<packets_job_id>` at it; a bug where its draft job had
no dependency at all and could have started against nonexistent/partial packets was caught and
cancelled on 2026-08-15). If you're not sure which domain a job or run directory belongs to, check
`data/v3/runs/<name>/packets/kc_packet_stats.json` or the job's own log for unit counts and names
before assuming.

## 11. CRITICAL: two separate evidence-building pipelines exist — do not confuse them

Discovered 2026-08-15 after mistakenly bridging output from the wrong one into a real drafting
job (caught by the user, not self-caught — read this section so it doesn't happen again).

**There are two independent, non-interchangeable evidence/packet-building implementations in this
codebase:**

1. **`src/kc_l/retrieval_gate/evidence_pack.py`** — 18 commits, the full v3–v74 fix cycle this
   entire project (`FAILURE_CYCLE_2.md`) is about (§29–§36 cover v48–v74 specifically: a much
   deeper second-pass semantic audit against a real 159-packet rebuild, found via real reranker
   jobs and a corpus-wide identity audit, not synthetic tests — read those sections, they're some
   of the most rigorous work in the whole cycle, correcting an earlier wrong assumption in an
   earlier draft of this handoff that the commit landing this work — `a0ee7e1`, 906 lines, an
   empty commit message — was undocumented; it isn't, the write-up is 364 lines in the very next
   commit, `e5bf2d3`, just under section titles that don't contain the words "comprehensive" or
   "harden"). Invoked by `v3/pipeline/02_build_kc_packets.py` (called from
   `v3/jobs/01_packets*.sbatch`), gated by `v3/verify/verify_pipeline_fixes.py` (232 checks, 0
   failed as of v74) before every packet build. **This is the verified, trusted path.** It's what
   built sociology's, data-mining's, and (after a correction, see below) mathematics' packets.
2. **`src/kc_l/retrieval_gate/evidence_stage_v3_candidate_bank.py`** — a separate module, only 5
   commits of its own (independent) contamination-fix history, invoked by the *orchestrator's*
   `step_05x_kc_evidence_stage_v3` stage (`steps/step_05_x_evidence_stage_v3/scripts/
   run_step5x_v3_candidate_bank.py`) and consumed downstream by `step_06_6_drafting_input_overlay`
   → `step_06_7_hierarchy_aware_synthesis_packets`. **This has never been audited against the
   v3–v74 fix cycle and must not be assumed equivalent to it**, even though both produce
   JSONL records that superficially look like the same packet schema (`canonical_name`,
   `knowledge_unit_id`, `packet_support_state`, etc. all present in both). This finding still
   stands — it's a real, separate module, genuinely less audited — only the "a0ee7e1 is
   undocumented" tangent above was wrong.

**Separately worth knowing, found later on a direct read of the real packets**: even the verified
`evidence_pack.py` path isn't perfect on a brand-new corpus. Mathematics' rebuild turned up 17
evidence items (out of 1,332, ~1.3%) that end literally at the text `"(LATEX code:"` with nothing
after — a PDF-extraction defect specific to that corpus that none of v28–v74's detectors catch,
found by manually reading a random sample of formula-shaped evidence rather than trusting an
automated 0-damaged-items result alone. Not yet fixed as of this writing — a concrete, scoped,
well-diagnosed candidate for a v75-class fix, but the decision to fix it now vs. later is the
user's, not made unilaterally.

**The mistake that happened**: the mathematics domain's first real end-to-end orchestrator run
went through `step_05x`/`step_06_6`/`step_06_7` (the *second*, unaudited pipeline) simply because
that's the orchestrator's own wired sequence for going from a fresh corpus to drafting. Its output
was bridged directly into `v3/jobs/02_draft_kc_qwen36.sbatch` on the assumption that "same field
names = same trust level." **Caught and reverted before any drafting ran on it** — the bridged
file was renamed to `kc_packets_FROM_ORCHESTRATOR_EVIDENCE_STAGE_V3_DO_NOT_USE_unverified.jsonl`
(kept, not deleted, per §10's non-destructive rule) rather than used.

**The fix, and the correct pattern going forward**: when a domain needs fresh PDF ingestion (which
sociology and data-mining didn't — they already had a prebuilt corpus), let the orchestrator run
*only* through corpus + hierarchy-overlay construction (`step_02_pdf_ingest` through
`step_04_5_sentence_overlay`, plus `hierarchy_registry`) — stop there. Then hand off to the
**verified** path exactly the way sociology/data-mining did: a `v3/jobs/01_packets*.sbatch`-style
script calling `01_build_profiles.py` → `verify_pipeline_fixes.py` → `02_build_kc_packets.py` →
`03_build_topic_packets.py`, pointed at that corpus/hierarchy output instead of hardcoded
production paths. See `v3/jobs/01_packets_mathematics.sbatch` for the worked example (mathematics'
own `CORPUS`/`HIER` paths substituted in, otherwise identical to `01_packets.sbatch`).

**Do not use `step_05x_kc_evidence_stage_v3` / `step_06_6_drafting_input_overlay` /
`step_06_7_hierarchy_aware_synthesis_packets` output for real drafting** until someone actually
audits `evidence_stage_v3_candidate_bank.py` against the same standard `evidence_pack.py` has been
held to (structural fix-liveness harness, unit-by-unit diagnosis, the works) and either confirms it
independently meets the bar or ports/reconciles the two. That audit has not happened as of this
writing — this section exists to stop it from being silently assumed rather than to report it as
already resolved.

## 12. The §11 rewiring is now built, real-execution-verified, and confirmed working end to end

As of 2026-08-16, `step_05v_verified_kc_packets` / `step_06v_kc_draft_generation` /
`step_06v_topic_draft_generation` / `step_06v_review` (the replacement stages §11 describes) exist
in `stage_registry.py` and `kc_l_orchestrator.py`'s `_prepare_stage_invocation`, `run_stage_wired
=True`, and have been proven against a real run, not just a dry-run render: mathematics domain
(`run_id 20260815T010743Z_ea40e85c`) went `hierarchy_registry` → ... → `step_05v_verified_kc_packets`
→ self-chained automatically into both `step_06v_kc_draft_generation` and
`step_06v_topic_draft_generation` with zero manual intervention beyond the one verification pause
described below. The 9 old stages remain in the registry with `run_stage_wired=False` and an
inline retirement note each, not deleted.

**A second real bug was found and fixed during that first real run — read this before trusting any
`step_05v_verified_kc_packets` output that predates 2026-08-16.** The stage completed successfully
(`rc=0`, real packets written, 70/71 KC units with evidence) but silently ran with the dense-
retrieval recall channel disabled (`dense_index=False` in the log, with a
`No sentence-transformers model found... Creating a new one with mean pooling` warning in stderr —
BM25+PRF still worked, dense semantic recall did not). Root cause: the shared
`~/kc_l_v2_env.sh` (sourced by every orchestrator-rendered job, not something this rewiring
introduced) sets `TRANSFORMERS_CACHE=$KC_ROOT/cache/transformers` and `HF_HOME=$KC_ROOT/cache/hf`,
redirecting HuggingFace/sentence-transformers cache lookups to `/path/to/scratch/kc_l/
cache/`. That scratch cache already had `all-MiniLM-L6-v2` cached (some other stage's dependency)
but never had `all-mpnet-base-v2` (`DEFAULT_EMBEDDER` in `retrieval.py`, what `DenseIndex` actually
needs) — a real population gap, not a broken mechanism. Every prior orchestrator-driven stage
happened to never call `DenseIndex` at all, so this was invisible until `step_05v` became the
first one to. Manually-written sbatch scripts (`v3/jobs/01_packets*.sbatch` and everything this
project has run through them) never hit this, because they don't source `kc_l_v2_env.sh` and rely
on the default `~/.cache/huggingface` location instead, where the mpnet model was already present.

**Fix**: `ln -s ~/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2
/path/to/scratch/kc_l/cache/hf/hub/models--sentence-transformers--all-mpnet-base-v2` — one
symlink, no changes to `kc_l_v2_env.sh` itself (shared by every stage, out of caution) and no
duplication of the ~420MB model weights. Verified by literally re-running the same stage after the
symlink: `dense_index=True device=cpu cache=written` this time. The first (broken) attempt's output
was archived, not deleted — `data/processed/verified_v3_packets/20260815T010743Z_ea40e85c/
packets_BM25_ONLY_DENSE_INDEX_FAILED_DO_NOT_USE/`. **If you run `step_05v_verified_kc_packets` for
a fresh domain and see `dense_index=False` in its log, this symlink may not exist on whatever
machine/session you're running from — check for it before assuming a new bug.**

**Practical takeaway for verifying any future `step_05v` run**: always grep the job's own stdout
for the literal line `dense_index=` and confirm it says `True`, not just that the job exited 0 —
exactly the same "a clean exit code doesn't mean clean output" lesson §4E already states for
`ast.parse`, just for a different failure shape (a silently-degraded external dependency, not a
code bug).


## 13. A third real bug found in the §11/§12 rewiring: every orchestrator-driven Ollama stage
used ONE hardcoded Ollama binary regardless of which model it was actually told to run —
fixed 2026-08-16, read this before assuming any orchestrator-submitted drafting job's failure
is a data/prompt/config problem

**Symptom**: mathematics domain KC + topic drafting via `qwen3.8:27b`, submitted through the
(already model-agnosticity-fixed, §12) `step_06v_kc_draft_generation` /
`step_06v_topic_draft_generation` stages — jobs `245988` and `245989` — both failed with
`RUNNER_RC=2`, 100% of records (`71/71` and equivalent for topics) showing
`parse_error: "HTTPError: <HTTPError 500: 'Internal Server Error'>"` and an **empty**
`raw_response`. This looked like a generation-time crash (the working hypothesis at the time
was `num_ctx=65536`, inherited from `RUN_STATE.json` for gemma4, being too large for
qwen3.8's hybrid SSM architecture) — **that hypothesis was wrong**, refuted by direct log
evidence below. Do not reach for "shrink num_ctx" as the fix for an HTTP-500-with-empty-body
pattern before checking `ollama_serve.log` first.

**Root cause, confirmed via `ollama_serve.log`** (see §-general practical takeaway: the real
Ollama server log for an orchestrator-rendered job lives at
`data/processed/runs/<run_id>/<stage_id>/ollama_serve.log` — same `$LOG_DIR` the job's own
`.slurm`/`.out`/`.err` live in, NOT the `$OUT/ollama_serve.log` path the manually-written
`v3/jobs/*.sbatch` scripts use; the two rendering paths log to different locations. It is
**not job-ID-suffixed**, so a second job reusing the same `stage_id` under the same `run_id`
silently overwrites the previous one's log — check the job's own start timestamp against the
log's first `time=` line before trusting it belongs to the job you're investigating):

```
llama_model_loader: - kv  23: qwen35.ssm.conv_kernel u32 = 4
llama_model_loader: - kv  24: qwen35.ssm.state_size u32 = 128
llama_model_load: error loading model: error loading model architecture: unknown model architecture: 'qwen35'
msg="failed to create server" model=qwen3.8:27b error="unable to load model: .../blobs/sha256-f5f1..."
```

repeated on every single retry for the whole job. **The Ollama server never finished loading
the model in the first place** — every `/api/generate` call downstream during real drafting
therefore got HTTP 500 with nothing behind it. Confirmed by the `OLLAMA_LIBRARY_PATH` in the
same log's `server config` line: it pointed at
`ollama_upgrade_clean_20260425_214752` — the OLD build, the same one §-qwen3.8-incompatibility
(the original model-pull investigation) already established cannot load the `qwen35` hybrid
attention+SSM architecture at all. The already-validated `ollama_v0.32.13_extracted_
20260816T113634Z` fix from that investigation was never actually reaching this job.

**Why**: `kc_l_orchestrator.py` had exactly one call site for `slurm_render.render_ollama_job`,
shared by every `needs_ollama=True` stage, and it resolved the binary as:
```python
ollama_bin=os.environ.get("KC_L_ABLATION_OLLAMA_BIN", HPC_OLLAMA_BIN)
```
— a single hardcoded module-level `HPC_OLLAMA_BIN` (the old build) for every model, with an
escape hatch (`KC_L_ABLATION_OLLAMA_BIN`) that must be set manually, by the human, at
submission time, completely disconnected from `RUN_STATE.json overrides.model` (the mechanism
§12's own fix made the actual source of truth for which model runs). It was simply not set
when `245988`/`245989` were submitted. `HPC_RUNTIME_ENV_RELPATH` was separately hardcoded to
`clusterb_ollama_gemma4_31b.env` too, though sourcing it turned out to be functionally inert for
binary selection anyway — `render_ollama_job` sources `RUNTIME_ENV` (which sets
`KC_L_OLLAMA_BIN`) and then immediately does `export OLLAMA_BIN=<the Python-resolved value>`
right after, a different variable name, so the sourced profile's own binary choice was never
actually consulted even when the "right" profile happened to be sourced.

**Fix**: added `_resolve_ollama_runtime(repo_root, model_name)` to `kc_l_orchestrator.py`. Before
falling back to `HPC_OLLAMA_BIN`, it scans `config/runtime/clusterb_ollama_*.env` (the same
profile files `v3/jobs/02_draft_kc_qwen38.sbatch` etc. already source by hand) for whichever
profile's `KC_L_PROFILE_MODEL` matches the model this stage was actually told to run, and uses
that profile's own `KC_L_OLLAMA_BIN` instead. `KC_L_ABLATION_OLLAMA_BIN`, if set, still wins
over either — the manual override is preserved, just no longer the only way to get this right.
Models with no matching profile (confirmed: `step_04_3_embedding_index`'s
`qwen3-embedding:8b`, which isn't part of this drafting-model-profile system) fall back to
exactly the prior behavior — verified via dry-run that gemma4 (which does have a profile, but
one whose `KC_L_OLLAMA_BIN` happens to equal the old default anyway) renders a byte-identical
`OLLAMA_BIN=` line before and after this change, and that qwen3.8 now renders the v0.32.13
path. Both didn't need to be assumed — checked directly in the rendered `.slurm` file's
`OLLAMA_BIN=`/`RUNTIME_ENV=` lines for both models on the real mathematics run before trusting
either.

**Practical takeaway**: any future model added to this pipeline needs its own
`config/runtime/clusterb_ollama_<model>.env` profile (matching the existing 4 examples) BEFORE
being run through the orchestrator, or it silently gets whatever `HPC_OLLAMA_BIN` currently
points at — which may or may not be able to load it. This is a real, cluster-specific fact
about Ollama/llama.cpp builds (different model architectures need different engine versions),
not a workaround for a design flaw — there is no single "right" binary for every model.


### 13b. Addendum (same day): a second, distinct bug behind the same "245994 FAILED" symptom
— the schema-contract probe's exit code is informational, not a success signal, and one
orchestrator gate was treating it as one

After §13's Ollama-binary fix, resubmitting mathematics KC drafting via qwen3.8 (job 245994)
proved the real fix worked: the model loaded correctly, and **real generation succeeded** -
`DRAFT_ROW_COUNT=71`, `FAILURE_COUNT=7` (a normal, healthy rate - directly comparable to
sociology's own clean qwen3.8 runs the same day: 5/149 and a 30/30-touched-but-0-hard-failures
topic run). Yet SLURM still reported the job `FAILED`, and no `kc_drafts.jsonl`/archive/
`validate_drafts.py` run appeared - the good data was stuck in
`.../verified_v3_drafts/<run_id>/qwen3_8_27b/step67_v2_tiny_smoke_drafts.jsonl` with nothing
downstream able to see it, and no self-chain into `step_06v_review`.

**Root cause**: `render_ollama_job`'s shared "extra_commands only run if the main command
exits 0" gate (`RUNNER_RC=$?; if [ "$RUNNER_RC" -ne 0 ]; then exit "$RUNNER_RC"; fi`) - correct
and desired for most stages using it - was being applied to
`run_step67_v2_schema_contract_probe.py`. That script's own exit code (`return 0 if not
failures else 2`) is **not a real failure signal**: `failures` accumulates any record that
ever had `parse_error` or `validation_issues` set, *including ones that repair cleanly* - the
standalone `v3/jobs/02_draft_kc_*.sbatch` scripts already treat this as purely informational
(`echo "probe rc=$? (informational: a correct abstention makes this non-zero)"`, no gating).
`step_06v_kc_draft_generation`/`step_06v_topic_draft_generation`'s own `extra_commands`
*already* implement the real gating correctly - a `[ -f ... ]` check that the raw drafts file
genuinely exists, and a `VALIDATE_RC` check from the actual `validate_drafts.py` run - they
just never got a chance to execute, because the generic gate fired first.

**Fix**: `render_ollama_job` gained an opt-in `require_main_command_success: bool = True`
parameter. Default `True` keeps every other stage's rendered script byte-identical (verified
via dry-run diff against `step_04_3_embedding_index`, which still has the gate). Set `False`
specifically in `step_06v_kc_draft_generation`/`step_06v_topic_draft_generation`'s
`ollama_params`, whose own `extra_commands` already do the correct, stricter real check.

**Practical takeaway**: a SLURM job reporting `FAILED` for a `step_06v_kc_draft_generation`/
`step_06v_topic_draft_generation` run does **not**, by itself, mean drafting failed - check
`.../verified_v3_drafts/<run_id>/<model_slug>/step67_v2_tiny_smoke_drafts.jsonl` (or the topic
equivalent) directly for real row counts before assuming a wasted GPU-hour. This addendum was
only needed for jobs submitted before this fix landed (2026-08-16); anything resubmitted after
should fail SLURM-visibly only on a genuine hard failure (no drafts file, or a real
`validate_drafts.py` failure), matching the standalone scripts' behavior.
