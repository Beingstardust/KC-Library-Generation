"""Make every v3 pipeline run with real drafts reviewable in the Streamlit console.

The console (kc_l_v2_streamlit_console/app.py) never scans data/v3/runs/ itself. It only shows
a run if data/processed/runs/<console_run_id>/RUN_STATE.json exists AND that state's
step_06_8_review_packet_emission stage is "completed" with a real review_packets.jsonl at its
recorded output_root (confirmed by reading list_available_runs/resolve_run_review_packet_path
in app.py directly). Two separate things were missing for every run built: (1) no
run-state registration, (2) no review-packet emission had ever been run against these drafts at
all - that is a distinct downstream stage from drafting itself, not a byproduct of it.

One console run_id can only point at ONE review_packets.jsonl (resolve_run_review_packet_path
reads a single output_root), but several of these run directories hold more than one drafting
model's output under the same run_id (e.g. v3_20260814_draft_3models_232029 has 4). This script
therefore mints one console run_id per (physical run, model) pair - "<run_id>" for the run's
FIRST/only model, "<run_id>__<model_slug>" for every additional one - rather than making models
beyond the first silently invisible.

The postprocess/emit builders are genuinely knowledge_unit_type-aware (confirmed by reading
step67_postprocess/builder.py directly: _unit_type, _draft_key_for_unit_type,
evidence_pool_for_row and _classify all branch on "topic" vs "kc"), so KC and topic drafts
for the same model are concatenated into one input before postprocessing, producing one unified
review_packets.jsonl per (run, model) covering both unit types - not two separate, harder-to-find
packet sets. No run built through this pipeline has ever had its topic drafts reviewed before;
this is a genuine addition, not a like-for-like port of prior behaviour.

Idempotent and safe to re-run, WITH one deliberate exception: KC and topic drafting run as
independent SLURM jobs and can finish in either order, so a console run_id already registered
from KC drafts alone is automatically upgraded (recomputed, re-registered) the next time this
script runs after the matching topic drafts appear - never silently stuck as KC-only forever.
Once a registration already includes topic drafts, or --force is not passed and nothing new is
available, it's left untouched. This protects data/processed/runs/v3_20260812, the one
pre-existing, already-working registration, from being altered by a policy this script did not
create it under (that one specific id is always skipped outright, upgrade or not).

Nested KC-library assembly (05_assemble_kc_library.py: kc_drafts + topic_drafts -> one hierarchy-
nested JSON) rides the SAME trigger as the review-packet bundling above - both need KC and topic
drafts both present, and both only need recomputing when that just became true. Written to
data/v3/runs/<run_id>/library/<model_slug>/kc_library.json. Nothing is ever overwritten in place:
an existing kc_library.json is moved to library/<model_slug>/archive/kc_library_<UTC
timestamp>.json before a fresh one is written, matching the archive-before-replace convention
already used for drafts (drafts/archive/<file>_job<ID>.jsonl). A run/model with no topic drafts
at all (the baseline condition, by design) never gets a library file - assembly needs both inputs.

v3_20260816_baseline_rag_datamining is excluded deliberately: it is the confirmed-superseded
first baseline build (evidence-budget bug - see v3/jobs/build_baseline_rag_datamining_v2.sbatch's
own header comment), and registering it would put known-broken drafts in front of a reviewer with
nothing to mark them as such.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repo-relative: a hardcoded absolute path at sys.path position 0 overrides PYTHONPATH,
# so any worktree/clone silently imports the ORIGINAL mirror's kc_l package instead of
# its own. That already invalidated one A/B experiment silently.
MIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MIR / "src"))

from kc_l.step67_postprocess import postprocess_review_source  # noqa: E402
from kc_l.review_packets import emit_review_packets_from_postprocessed_source  # noqa: E402

_ASSEMBLE_SPEC = importlib.util.spec_from_file_location(
    "assemble_kc_library", str(MIR / "v3" / "pipeline" / "05_assemble_kc_library.py"))
assert _ASSEMBLE_SPEC is not None and _ASSEMBLE_SPEC.loader is not None
ASSEMBLE = importlib.util.module_from_spec(_ASSEMBLE_SPEC)
_ASSEMBLE_SPEC.loader.exec_module(ASSEMBLE)

RUNS_ROOT = MIR / "data" / "v3" / "runs"
REGISTRY_ROOT = MIR / "data" / "processed" / "runs"

EXCLUDED_RUNS = {
    "v3_20260816_baseline_rag_datamining":
        "superseded by v3_20260816_baseline_rag_datamining_budgetfix - confirmed evidence-budget "
        "bug (source_block_text was unbudgeted), truncated 42/159 units mid-JSON",
}

_KC_RE = re.compile(r"^kc_drafts(?:_(?P<model>.+))?\.jsonl$")
DEFAULT_MODEL_SLUG = "gemma4_31b"  # the unsuffixed kc_drafts.jsonl convention - confirmed
# distinct (not a duplicate) from every model-suffixed sibling file by md5sum in every run that
# has one, and matches v3/jobs/04_review_packets.sbatch's own MODEL=${MODEL:-gemma4_31b} default.


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def discover_groups():
    """Yields (run_id, model_slug, kc_drafts_path, topic_drafts_path_or_None)."""
    for run_dir in sorted(RUNS_ROOT.iterdir()):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        if run_id in EXCLUDED_RUNS:
            continue
        drafts_dir = run_dir / "drafts"
        if not drafts_dir.is_dir():
            continue
        for kc_path in sorted(drafts_dir.glob("kc_drafts*.jsonl")):
            m = _KC_RE.match(kc_path.name)
            if not m:
                continue
            model_slug = m.group("model") or DEFAULT_MODEL_SLUG
            topic_name = f"topic_drafts_{m.group('model')}.jsonl" if m.group("model") else "topic_drafts.jsonl"
            topic_path = drafts_dir / topic_name
            yield run_id, model_slug, kc_path, (topic_path if topic_path.exists() else None)


def console_run_id_for(run_id: str, model_slug: str, seen_models_for_run: set) -> str:
    if len(seen_models_for_run) <= 1:
        return run_id
    return f"{run_id}__{model_slug}"


def stage_entry(output_root: Path | None, status: str) -> dict:
    return {
        "status": status,
        "output_root": str(output_root) if output_root else None,
        "job_id": None,
        "started_utc": utc(),
        "finished_utc": utc() if status == "completed" else None,
        "set_manifest_path": None,
        "run_folder_symlink": None,
        "slurm_script_path": None,
    }


def write_run_state(console_run_id: str, review_output_root: Path, kc_drafts_root: Path,
                    model_slug: str, source_run_id: str, has_topic: bool) -> Path:
    run_dir = REGISTRY_ROOT / console_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stages = {
        "step_06_7_kc_draft_generation": stage_entry(kc_drafts_root, "completed"),
        "step_06_7_postprocessed_review_source": stage_entry(review_output_root / "_postprocess", "completed"),
        "step_06_8_review_packet_emission": stage_entry(review_output_root, "completed"),
    }
    state = {
        "schema_version": "kc_l_run_state_v1",
        "run_id": console_run_id,
        "request_id": "kc_library_v3_console_sync",
        "status": "completed",
        "created_utc": utc(),
        "updated_utc": utc(),
        "hierarchy_path": None,
        "course_materials": [],
        "overrides": {
            "pipeline_version": "v3",
            "model": model_slug,
            "source_run_id": source_run_id,
            "includes_topic_drafts": has_topic,
            "notes": "Registered retroactively by v3/pipeline/06_sync_console_registry.py, not "
                     "produced by a live self-chaining orchestrator run.",
        },
        "blocked_stages": [],
        "stages": stages,
    }
    path = run_dir / "RUN_STATE.json"
    io.open(path, "w", encoding="utf-8").write(json.dumps(state, indent=2))
    return path


def registered_includes_topic(console_run_id: str) -> bool | None:
    """None if not registered yet; else whether the CURRENT registration already bundled topic
    drafts. KC and topic drafting run as independent SLURM jobs and finish in whichever order the
    queue allows, so a KC-only registration written before topic drafts existed must not be
    mistaken for a permanent state - it needs to be recomputed once topic drafts show up, or a
    reviewer would be stuck looking at a KC-only set forever even though a fuller one is now
    available under the exact same console_run_id.
    """
    state_path = REGISTRY_ROOT / console_run_id / "RUN_STATE.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return bool((state.get("overrides") or {}).get("includes_topic_drafts"))


def assemble_and_archive_library(run_id: str, model_slug: str, kc_path: Path,
                                 topic_path: Path) -> Path:
    """Writes data/v3/runs/<run_id>/library/<model_slug>/kc_library.json. If one already exists
    there, it is moved (never deleted, never silently overwritten) to
    library/<model_slug>/archive/kc_library_<UTC timestamp>.json first."""
    lib_dir = RUNS_ROOT / run_id / "library" / model_slug
    lib_dir.mkdir(parents=True, exist_ok=True)
    out_path = lib_dir / "kc_library.json"
    if out_path.exists():
        archive_dir = lib_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path.replace(archive_dir / f"kc_library_{stamp}.json")

    library = ASSEMBLE.assemble_library(str(kc_path), str(topic_path), f"{run_id}:{model_slug}")
    io.open(out_path, "w", encoding="utf-8").write(
        json.dumps(library, indent=2, ensure_ascii=False))
    return out_path


def process_group(run_id: str, model_slug: str, kc_path: Path, topic_path: Path | None,
                  console_run_id: str, force: bool) -> dict:
    review_root = RUNS_ROOT / run_id / "review" / model_slug
    packets_path = review_root / "review_packets.jsonl"
    registry_state_path = REGISTRY_ROOT / console_run_id / "RUN_STATE.json"

    already_has_topic = registered_includes_topic(console_run_id)
    topic_now_available = topic_path is not None
    needs_topic_upgrade = topic_now_available and not already_has_topic
    if registry_state_path.exists() and not force and not needs_topic_upgrade:
        return {"run_id": run_id, "model": model_slug, "console_run_id": console_run_id,
                "action": "skipped_already_registered", "packets": str(packets_path)}

    recompute = force or needs_topic_upgrade or not packets_path.exists()
    if not recompute:
        rows = read_jsonl_count(packets_path)
    else:
        review_root.mkdir(parents=True, exist_ok=True)
        combined_path = review_root / "_combined_source_drafts.jsonl"
        if topic_path is not None:
            with io.open(combined_path, "w", encoding="utf-8") as out:
                for src in (kc_path, topic_path):
                    with io.open(src, encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                out.write(line if line.endswith("\n") else line + "\n")
            source_for_postprocess = combined_path
        else:
            source_for_postprocess = kc_path

        postprocess_dir = review_root / "_postprocess"
        result67 = postprocess_review_source(
            source_drafts_jsonl=source_for_postprocess,
            output_dir=postprocess_dir,
            run_id=console_run_id,
            accepted_baseline_run_id=run_id,
            postprocess_root=str(postprocess_dir),
        )
        postprocessed_jsonl = Path(result67["postprocessed_jsonl"])

        emit_dir = review_root / "_emit"
        emit_review_packets_from_postprocessed_source(
            postprocessed_jsonl=postprocessed_jsonl,
            output_dir=emit_dir,
            run_id=console_run_id,
        )
        raw = emit_dir / "step68_v2_review_packets.jsonl"
        if not raw.exists():
            return {"run_id": run_id, "model": model_slug, "console_run_id": console_run_id,
                    "action": "FAILED_no_packets_emitted", "packets": None}
        packets_path.parent.mkdir(parents=True, exist_ok=True)
        packets_path.write_bytes(raw.read_bytes())
        rows = read_jsonl_count(packets_path)

    if rows == 0:
        return {"run_id": run_id, "model": model_slug, "console_run_id": console_run_id,
                "action": "FAILED_zero_rows", "packets": str(packets_path)}

    library_path = None
    if recompute and topic_path is not None:
        library_path = assemble_and_archive_library(run_id, model_slug, kc_path, topic_path)

    write_run_state(console_run_id, review_root, kc_path.parent, model_slug, run_id,
                    topic_path is not None)
    action = "upgraded_with_topic" if needs_topic_upgrade and not force else "registered"
    return {"run_id": run_id, "model": model_slug, "console_run_id": console_run_id,
            "action": action, "packets": str(packets_path), "rows": rows,
            "library": str(library_path) if library_path else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                     help="Recompute review packets and overwrite RUN_STATE.json even if already "
                          "present. Never touches a console_run_id this script did not create "
                          "unless that exact id is targeted (v3_20260812's bare registration is "
                          "never a possible console_run_id output of this script, since it always "
                          "keeps the bare id reserved for the run's own already-registered entry).")
    args = ap.parse_args()

    groups = list(discover_groups())
    by_run: dict[str, set] = {}
    for run_id, model_slug, _, _ in groups:
        by_run.setdefault(run_id, set()).add(model_slug)

    results = []
    for run_id, model_slug, kc_path, topic_path in groups:
        n = read_jsonl_count(kc_path)
        if n == 0:
            results.append({"run_id": run_id, "model": model_slug, "console_run_id": None,
                            "action": "skipped_empty_drafts", "packets": None})
            continue
        console_run_id = console_run_id_for(run_id, model_slug, by_run[run_id])
        if console_run_id == "v3_20260812":
            # the one pre-existing, already-working registration - never overwritten by this
            # script's own (different, KC+topic-combined) policy.
            results.append({"run_id": run_id, "model": model_slug, "console_run_id": console_run_id,
                            "action": "skipped_preexisting_reference_registration", "packets": None})
            continue
        results.append(process_group(run_id, model_slug, kc_path, topic_path, console_run_id,
                                     args.force))

    print(f"{'run_id':<45} {'model':<16} {'console_run_id':<50} {'action':<38} {'rows':<6} library")
    for r in results:
        print(f"{r['run_id']:<45} {r['model']:<16} {str(r['console_run_id']):<50} "
              f"{r['action']:<38} {str(r.get('rows', '-')):<6} {r.get('library') or '-'}")

    failed = [r for r in results if str(r["action"]).startswith("FAILED")]
    print()
    print(f"TOTAL={len(results)} "
          f"REGISTERED={sum(1 for r in results if r['action'] == 'registered')} "
          f"UPGRADED_WITH_TOPIC={sum(1 for r in results if r['action'] == 'upgraded_with_topic')} "
          f"FAILED={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
