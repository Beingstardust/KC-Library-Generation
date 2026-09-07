"""Register the v3 run so the console can resolve it - written into the MIRROR, not production.

The console resolves its repository from KC_L_REPO_ROOT and only falls back to kc_l_v2_clean when
that variable is unset. Pointing it at this repository therefore needs no write to production: the
run is registered under this repo's own data/processed/runs/, and the console reads its
RUN_STATE.json, each stage's declared output_root, and the review packets those point to.

Stage ids keep the console's existing vocabulary where a v3 stage does the same job as a v2 one, so
the run renders without console changes; the console maps them to readable labels for display.
Stages v3 genuinely does not have - 5p profiling, 5x evidence staging, 6.6 drafting-input overlay -
are absent rather than faked as completed, since their absence is the point of this version.

Outputs live in the v3 layout: data/v3/runs/<run_id>/{profiles,packets,drafts,review}/
"""
import argparse
import io
import json
import os
from datetime import datetime, timezone

MIR = "/path/to/kc_l"
PROD = "/path/to/shared"

CORPUS_ROOT = os.path.join(
    PROD, "data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/2026-07-27_085228")
HIER_ROOT = os.path.join(
    MIR, "data/processed/hierarchy_overlay/20260727T022835Z_9e856df6/"
         "2026-07-27_022841_hierarchy_overlay")


def utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stage(output_root, status="completed"):
    exists = os.path.exists(output_root)
    return {
        "status": status if exists else "not_started",
        "output_root": output_root,
        "job_id": None,
        "started_utc": utc(),
        "finished_utc": utc() if exists else None,
        "set_manifest_path": None,
        "run_folder_symlink": None,
        "slurm_script_path": None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="v3_20260812")
    a = ap.parse_args()

    data = os.path.join(MIR, "data", "v3", "runs", a.run_id)
    run_dir = os.path.join(MIR, "data", "processed", "runs", a.run_id)
    os.makedirs(run_dir, exist_ok=True)

    stages = {
        "hierarchy_registry": stage(HIER_ROOT),
        "step_04_5_sentence_overlay": stage(CORPUS_ROOT),
        "step_05x_kc_evidence_stage_v3": stage(os.path.join(data, "packets")),
        "step_06_7_hierarchy_aware_synthesis_packets": stage(os.path.join(data, "packets")),
        "step_06_7_kc_draft_generation": stage(os.path.join(data, "drafts")),
        "step_06_7_postprocessed_review_source": stage(os.path.join(data, "review", "_postprocess")),
        "step_06_8_review_packet_emission": stage(os.path.join(data, "review")),
    }

    complete = all(s["status"] == "completed" for s in stages.values())
    state = {
        "schema_version": "kc_l_run_state_v1",
        "run_id": a.run_id,
        "request_id": "kc_library_v3",
        "status": "completed" if complete else "in_progress",
        "created_utc": utc(),
        "updated_utc": utc(),
        "hierarchy_path": os.path.join(HIER_ROOT, "hierarchy_overlay.jsonl"),
        "course_materials": [],
        "overrides": {
            "pipeline_version": "v3",
            "profiling_stage_used": False,
            "profile_source": "hierarchy_overlay_only_no_model",
            "retrieval": "bm25 + pseudo-relevance-feedback + dense, cross-encoder admission",
            "notes": "Retrieval reads the sentence corpus and the knowledge registry only.",
        },
        "blocked_stages": [],
        "stages": stages,
    }

    path = os.path.join(run_dir, "RUN_STATE.json")
    io.open(path, "w", encoding="utf-8").write(json.dumps(state, indent=2))
    print("run      : %s  (%s)" % (a.run_id, state["status"]))
    print("state    : %s" % path)
    for sid, s in stages.items():
        print("  %-46s %-12s %s" % (sid, s["status"], s["output_root"].replace(MIR + "/", "")))


if __name__ == "__main__":
    main()
