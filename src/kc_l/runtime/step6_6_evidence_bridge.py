from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from kc_l.runtime.stage_config import render_stage_config
from kc_l.runtime.stage_pointers import resolve_pointer
from kc_l.utils.json_io import read_json, write_json

BASE_CONFIG_PATH = Path("steps/step_06_6_kc_drafting_input_overlay/resources/step6_6.hpc.actual_corpus.yaml")

# Step 6.6's *only* code path that accepts genuinely separate KC and topic evidence sources is
# the --step6-input-assembly-manifest CLI flag (see build_step6_assembly_bridge_manifest() in
# run_step6_6_kc_drafting_input_overlay.py), which reads a step6_authorized_inputs block with
# distinct kc_evidence_pack_jsonl / topic_evidence_pack_jsonl keys. The plain YAML `inputs:`
# path only has a single step5_4_set_manifest slot and cannot represent two separate sources
# without inventing new merge logic - so this module builds a fresh assembly-manifest JSON per
# run, pointing at each source's ACTUAL evidence-pack artifact, rather than trying to force
# both pointers through the single config key.
DEFAULT_BEST_STEP5X_POINTER = Path(
    "data/processed/evidence_stage_v3_evidence_packs/_sets/BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt"
)
DEFAULT_BEST_TOPIC5X_POINTER = Path(
    "data/processed/topic_evidence_stage_v3_evidence_packs/_sets/BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt"
)

# 2026-07-15: both BEST_* pointer files above are one-time snapshots from 2026-05-19/20 that
# nothing in this codebase ever writes to (confirmed by grepping for write_best_pointer / any
# writer targeting either filename - zero matches). step_05x_kc_evidence_stage_v3 and
# topic_05x_evidence_stage_v3 are now both run_stage_wired and produce genuine fresh per-run
# output, so every run since those stages were wired has silently been built on the SAME frozen
# ~144-KC evidence pack regardless of run_id - masked until a run's real KC hierarchy (this run:
# 159 KCs, confirmed via kc_registry.jsonl) diverged from that frozen snapshot's fixed coverage.
# These two roots + the deterministic run_step5x_v3_pack_composition.py-family set-manifest name
# are used to resolve each run's OWN real output by default now; the BEST_* pointers remain
# available as an explicit opt-in override (below) for deliberately pinning to one historical
# snapshot, not as the default path every run takes.
STEP5X_V3_OUTPUT_ROOT = Path("data/processed/evidence_stage_v3_evidence_packs")
TOPIC5X_V3_OUTPUT_ROOT = Path("data/processed/topic_evidence_stage_v3_evidence_packs")


def run_scoped_pack_set_path(output_root: Path, run_id: str) -> Path:
    """Deterministic per-run set-manifest path shared by step_05x_kc_evidence_stage_v3 and
    topic_05x_evidence_stage_v3 (both end in run_step5x_v3_pack_composition.py, which writes
    <run_id>_step5x_v3_evidence_packs_set.json under <output_root>/_sets/) - confirmed
    2026-07-15 against real on-disk output for both tracks, identical schema
    (artifacts.kc_evidence_packs_jsonl), so read_kc_evidence_packs_jsonl() works unchanged for
    either track's real per-run set-manifest.
    """
    return output_root / "_sets" / f"{run_id}_step5x_v3_evidence_packs_set.json"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_kc_evidence_packs_jsonl(pack_set_obj: Mapping[str, Any]) -> str:
    """Read the kc_evidence_packs_jsonl artifact path from a step5x/topic5x pack-set JSON.

    The field NAME (kc_evidence_packs_jsonl) is the stable cross-era contract in this repo -
    every pack-set variant found uses this exact key, for both KC-level and topic-level packs
    (topic packs are packaged in the same KC-compatible shape for step 6 consumption). Its
    POSITION in the JSON is not stable: some pack-set schemas put it at the top level, others
    nest it under "artifacts". Check both rather than hardcode either shape, since which one
    a given pointer resolves to on any future run is not something this code should assume.
    """
    if "kc_evidence_packs_jsonl" in pack_set_obj:
        return str(pack_set_obj["kc_evidence_packs_jsonl"])
    artifacts = pack_set_obj.get("artifacts")
    if isinstance(artifacts, Mapping) and "kc_evidence_packs_jsonl" in artifacts:
        return str(artifacts["kc_evidence_packs_jsonl"])
    raise KeyError(
        "kc_evidence_packs_jsonl not found in pack-set JSON at either the top level or "
        "artifacts.kc_evidence_packs_jsonl"
    )


def build_step6_6_assembly_manifest(
    *,
    run_id: str,
    repo_root: Path,
    output_path: Path,
    step5x_pointer: Path | None = None,
    topic5x_pointer: Path | None = None,
) -> Path:
    """Resolve step5x_v3/topic5x_v3 evidence packs and write a fresh step6.6 assembly manifest
    for this run_id - never a hardcoded one-off pack path.

    Defaults to THIS run_id's own real, fresh per-run output (run_scoped_pack_set_path()) since
    2026-07-15 - see the module-level note above. Passing step5x_pointer/topic5x_pointer
    explicitly opts into the older BEST_STEP5X/BEST_TOPIC5X pointer-file resolution instead (for
    deliberately pinning to one historical/blessed snapshot, or for this module's own
    verification fixtures) - never the default for a real run.
    """
    if step5x_pointer is not None:
        step5x_pointer_path = repo_root / step5x_pointer
        kc_pack_set_path = resolve_pointer(step5x_pointer_path)
        step5x_best_pointer_field = str(step5x_pointer_path)
    else:
        kc_pack_set_path = repo_root / run_scoped_pack_set_path(STEP5X_V3_OUTPUT_ROOT, run_id)
        step5x_best_pointer_field = None

    if topic5x_pointer is not None:
        topic5x_pointer_path = repo_root / topic5x_pointer
        topic_pack_set_path = resolve_pointer(topic5x_pointer_path)
        topic5x_best_pointer_field = str(topic5x_pointer_path)
    else:
        topic_pack_set_path = repo_root / run_scoped_pack_set_path(TOPIC5X_V3_OUTPUT_ROOT, run_id)
        topic5x_best_pointer_field = None

    kc_pack_set_obj = read_json(kc_pack_set_path)
    topic_pack_set_obj = read_json(topic_pack_set_path)

    kc_evidence_pack_jsonl = read_kc_evidence_packs_jsonl(kc_pack_set_obj)
    topic_evidence_pack_jsonl = read_kc_evidence_packs_jsonl(topic_pack_set_obj)

    manifest = {
        "schema_version": "1.0",
        "kind": "step6_6_assembly_manifest",
        "created_utc": _now_utc_iso(),
        "run_id": run_id,
        "ready_for_step6": True,
        "step6_authorized_inputs": {
            "kc_evidence_pack_jsonl": kc_evidence_pack_jsonl,
            "topic_evidence_pack_jsonl": topic_evidence_pack_jsonl,
            "topic_gap_jsonl": "",
        },
        "provenance": {
            "step5x_best_pointer": step5x_best_pointer_field,
            "step5x_pack_set_path": str(kc_pack_set_path),
            "topic5x_best_pointer": topic5x_best_pointer_field,
            "topic5x_pack_set_path": str(topic_pack_set_path),
        },
    }
    write_json(output_path, manifest)
    return output_path


def build_step6_6_run_config(
    *,
    run_id: str,
    repo_root: Path,
    run_dir: Path,
    step5x_pointer: Path | None = None,
    topic5x_pointer: Path | None = None,
    step5_3_active_set_pointer: Path | None = None,
    step4_active_set_pointer: Path | None = None,
    step4_5_active_set_pointer: Path | None = None,
    kc_registry_path: Path | None = None,
) -> tuple[Path, list[str]]:
    """Build everything needed to invoke step 6.6 for a fresh run: a per-run assembly
    manifest with both BEST pointers resolved dynamically, and a per-run rendered config
    with per-run output paths. Returns (rendered_config_path, extra_cli_args) - the extra
    CLI args must be appended to the stage's invocation alongside --config.

    step5x_pointer/topic5x_pointer default to the real BEST pointers when omitted; the
    override parameters exist for verification against local test fixtures.

    step5_3_active_set_pointer: retained for backward compatibility only - step_05_3_evidence_
    recalibrated was dismantled as a dependency of this stage 2026-07-26 (see stage_registry.py's
    step_06_6 notes); the live orchestrator call site no longer passes this.

    step4_active_set_pointer/step4_5_active_set_pointer (2026-07-26 fix): both were previously
    resolved unconditionally from the base yaml's own GLOBAL, non-run-scoped pointers - confirmed
    stale (a 2026-04-07 snapshot, 3 docs, vs a real run's 4+ docs) via direct verification. Same
    override mechanism as step5_3_active_set_pointer above; pass THIS run's own real per-run
    pointers (Path(_resolve_upstream_output_root(state, "step_04_3_embedding_index")) / "_sets" /
    "ACTIVE_STEP4_SET.txt", same pattern for step_04_5) to fix.

    kc_registry_path (2026-07-26 fix, same investigation): without step_05_3's own upstream
    manifest to fall back on, run_step6_6's kc_registry_path defaulted to a "current_step_
    artifacts" cache confirmed stale (a frozen 2026-04-24 144-row registry). Pass THIS run's own
    real hierarchy_registry output (resolve_hierarchy_manifest_from_output_root(...)["registry_
    path"], same resolution already proven for step_05_3's own config) - richer/authoritative
    hierarchy_path data than reconstructing registry rows from evidence-pack topic_path_labels
    alone, which was silently dropping 2 of 20 real topics from the KC-level hierarchy paths.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    assembly_manifest_path = run_dir / f"{run_id}_step6_6_assembly_manifest.json"
    build_step6_6_assembly_manifest(
        run_id=run_id,
        repo_root=repo_root,
        output_path=assembly_manifest_path,
        step5x_pointer=step5x_pointer,
        topic5x_pointer=topic5x_pointer,
    )

    overrides: dict[str, Any] = {
        "outputs": {
            "processed_root": f"data/processed/kc_drafting_input_overlay/{run_id}",
            "sets_root": f"data/processed/kc_drafting_input_overlay/{run_id}/_sets",
        },
    }
    input_overrides: dict[str, Any] = {}
    if step5_3_active_set_pointer is not None:
        input_overrides["step5_3_active_set_pointer"] = str(step5_3_active_set_pointer)
    if step4_active_set_pointer is not None:
        input_overrides["step4_active_set_pointer"] = str(step4_active_set_pointer)
    if step4_5_active_set_pointer is not None:
        input_overrides["step4_5_active_set_pointer"] = str(step4_5_active_set_pointer)
    if kc_registry_path is not None:
        input_overrides["kc_registry_path"] = str(kc_registry_path)
    if input_overrides:
        overrides["inputs"] = input_overrides
    rendered_config_path = run_dir / f"{run_id}_step6_6_config.json"
    render_stage_config(repo_root / BASE_CONFIG_PATH, overrides, rendered_config_path)

    extra_cli_args = ["--step6-input-assembly-manifest", str(assembly_manifest_path)]
    return rendered_config_path, extra_cli_args
