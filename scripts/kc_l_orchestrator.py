#!/usr/bin/env python3
"""KC_L v2 pipeline orchestrator v2.

Scope:
- whole-pipeline stage graph from input ingestion onward
- open-ended current endpoint: Step6.8 is not terminal
- pointer validation
- surface classification
- stage validation
- Step6.8 smoke execution
- mirror-only quarantine of stale generated surfaces
- run-stage / plan: render and submit a fresh-run_id SLURM job for one stage (or a
  dependency-chained range of stages), using the src/kc_l/runtime/ infrastructure
  (stage_registry, slurm_render, slurm_submit, stage_config, run_state)

Most of this file is deliberately stdlib-only with no src/kc_l imports. run-stage and plan
are the exception - they reuse the shared runtime infrastructure rather than re-implement it
inline, since duplicating already-built-and-verified pointer/SLURM/config logic here would be
a straightforward correctness risk for no benefit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def repo_root_from_this_file() -> Path:
    return Path(__file__).resolve().parents[1]


_REPO_SRC = repo_root_from_this_file() / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from kc_l.runtime import run_state as run_state_mod  # noqa: E402
from kc_l.runtime import slurm_render, slurm_submit  # noqa: E402
from kc_l.runtime.layout import get_operator_layout  # noqa: E402
from kc_l.runtime.stage_config import load_stage_config, render_stage_config  # noqa: E402
from kc_l.runtime.stage_registry import STAGE_SPECS, get_stage, is_confirmed, ordered_stage_ids  # noqa: E402
from kc_l.runtime.step6_6_evidence_bridge import (  # noqa: E402
    TOPIC5X_V3_OUTPUT_ROOT,
    build_step6_6_run_config,
    read_kc_evidence_packs_jsonl,
    run_scoped_pack_set_path,
)
from kc_l.runtime.step5p_hierarchy_registry_bridge import (  # noqa: E402
    build_step5p_run_config,
    resolve_hierarchy_overlay_jsonl_from_output_root,
    resolve_sentence_overlay_jsonl_from_output_root,
)
from kc_l.runtime.step5_3_evidence_recalibrated_bridge import (  # noqa: E402
    build_step5_3_run_config,
    resolve_hierarchy_manifest_from_output_root,
    resolve_hierarchy_normalize_output_root,
)
from kc_l.runtime.topic5p_hierarchy_registry_bridge import (  # noqa: E402
    extract_topic_registry_and_edges,
)
from kc_l.utils.json_io import read_json  # noqa: E402

# Confirmed HPC-cluster values, reused verbatim from the confirmed-good step 6.7 full165 run
# (_archive/.../submit_step67_v2_full165_kc_topic_policy_marker_fix_20260520T195051Z/...).
HPC_PYTHON_BIN = "/path/to/venvs/kc_l_v2/bin/python"
HPC_OLLAMA_BIN = "/home/<YOUR_USERNAME>/apps/ollama_upgrade_clean_20260425_214752/bin/ollama"
HPC_OLLAMA_MODELS_DIR = "/path/to/scratch/kc_l/ollama/models"
HPC_RUNTIME_ENV_RELPATH = "config/runtime/hpc_ollama_gemma4_31b.env"
STEP67_V2_RUNTIME_CONFIG = Path(
    "steps/step_06_7_kc_draft_generation/resources/step6_7.012531.packet_multicandidate_full.yaml"
)


def _resolve_ollama_runtime(repo_root: Path, model_name: str) -> tuple[str, str, int | None]:
    """Pick the Ollama binary + runtime env profile a given model actually needs.

    Confirmed by a real incident (jobs 245988/245989, 2026-08-16): different models on this
    cluster need different Ollama builds - qwen3.8:27b's GGUF declares a genuinely different
    hybrid attention+SSM architecture ("qwen35") that the older
    ollama_upgrade_clean_20260425_214752 build cannot load at all
    (`unknown model architecture: 'qwen35'`, confirmed directly in that job's ollama_serve.log
    on every retry), which is exactly why every real /api/generate call during drafting came
    back HTTP 500 with an empty response - the server never finished loading the model in the
    first place. This was never a num_ctx or generation-time issue.

    A single hardcoded HPC_OLLAMA_BIN cannot be correct for every model, so before falling
    back to it this looks for a matching per-model profile under
    config/runtime/hpc_ollama_*.env (the same profiles v3/jobs/02_draft_kc_*.sbatch already
    source by hand) and, if the requested model's KC_L_PROFILE_MODEL matches exactly one of
    them, uses THAT profile's own KC_L_OLLAMA_BIN instead of the global default.

    Stages whose model has no matching profile (e.g. step_04_3_embedding_index's embedding
    model, which isn't part of this drafting-model-profile system at all) fall back to the
    existing HPC_OLLAMA_BIN/HPC_RUNTIME_ENV_RELPATH default, completely unchanged from every
    stage's behavior before this function existed - this only changes anything for models
    that DO have a declared profile.

    KC_L_ABLATION_OLLAMA_BIN, if set, still wins over whichever binary would otherwise be
    picked (matched profile or default) - the existing manual one-off override, preserved.
    """
    ablation_override = os.environ.get("KC_L_ABLATION_OLLAMA_BIN")

    profile_dir = repo_root / "config" / "runtime"
    matched_paths: list[Path] = []
    matched_bin: str | None = None
    matched_context: int | None = None
    for profile_path in sorted(profile_dir.glob("hpc_ollama_*.env")):
        text = profile_path.read_text(encoding="utf-8")
        model_match = re.search(r'export\s+KC_L_PROFILE_MODEL="([^"]*)"', text)
        bin_match = re.search(r'export\s+KC_L_OLLAMA_BIN="([^"]*)"', text)
        ctx_match = re.search(r'export\s+KC_L_PROFILE_MODEL_CONTEXT="(\d+)"', text)
        if model_match and model_match.group(1) == model_name and bin_match:
            matched_paths.append(profile_path)
            matched_bin = bin_match.group(1)
            if ctx_match:
                matched_context = int(ctx_match.group(1))

    if len(matched_paths) > 1:
        raise StageNotWiredError(
            f"multiple Ollama runtime profiles declare KC_L_PROFILE_MODEL={model_name!r}: "
            f"{[str(p) for p in matched_paths]} - ambiguous, fix so exactly one profile "
            "matches this model before resubmitting."
        )

    if matched_paths:
        return (ablation_override or matched_bin), str(matched_paths[0]), matched_context

    # No dedicated profile for this model - preserve exactly what every stage did before this
    # function existed (e.g. step_04_3_embedding_index's embedding model).
    return (ablation_override or HPC_OLLAMA_BIN), str(repo_root / HPC_RUNTIME_ENV_RELPATH), None


class StageNotWiredError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"ERROR: missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def read_registry(repo_root: Path) -> dict[str, Any]:
    return load_json(repo_root / "configs" / "kc_l_pipeline_registry.v2.json")


def read_surface_state(repo_root: Path) -> dict[str, Any]:
    return load_json(repo_root / "configs" / "kc_l_surface_state.v2.json")


def write_surface_state(repo_root: Path, state: dict[str, Any]) -> None:
    write_json(repo_root / "configs" / "kc_l_surface_state.v2.json", state)


def exists_or_symlink(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def safe_lstat(path: Path):
    try:
        return os.lstat(path)
    except Exception:
        return None


def path_type(path: Path) -> str:
    st = safe_lstat(path)
    if st is None:
        return "missing"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def tree_size_no_follow(path: Path) -> int:
    st = safe_lstat(path)
    if st is None:
        return 0
    if stat.S_ISLNK(st.st_mode) or stat.S_ISREG(st.st_mode):
        return st.st_size
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size

    total = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except Exception:
            continue
        for e in entries:
            p = Path(e.path)
            try:
                st2 = os.lstat(p)
            except Exception:
                continue
            if stat.S_ISDIR(st2.st_mode) and not stat.S_ISLNK(st2.st_mode):
                stack.append(p)
            else:
                total += st2.st_size
    return total


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    val = float(n)
    for unit in units:
        if abs(val) < 1024 or unit == units[-1]:
            return f"{int(val)} {unit}" if unit == "B" else f"{val:.4f} {unit}"
        val /= 1024
    return f"{n} B"


def resolve_repo_path(repo_root: Path, rel: str) -> Path:
    if rel.startswith("/"):
        return Path(rel)
    return repo_root / rel


def status(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = read_registry(repo_root)
    state = read_surface_state(repo_root)

    surfaces = registry.get("data_surfaces", [])
    status_counter = Counter(s.get("surface_status") for s in surfaces)
    stage_counter = Counter(s.get("stage_candidate") for s in surfaces)

    print("KC_L_ORCHESTRATOR_V2_STATUS=1")
    print(f"REPO_ROOT={repo_root}")
    print(f"OPEN_ENDED_PIPELINE={int(bool(registry.get('open_ended_pipeline')))}")
    print(f"CURRENT_VALIDATION_ENDPOINT={registry.get('current_validation_endpoint')}")
    print(f"CURRENT_ENDPOINT_IS_TERMINAL={int(bool(registry.get('current_endpoint_is_terminal')))}")
    print(f"DATA_SURFACE_COUNT={len(surfaces)}")
    print(f"DATA_SURFACE_STATUS_COUNTER={dict(status_counter)}")
    print(f"DATA_SURFACE_STAGE_COUNTER={dict(stage_counter)}")
    print(f"STAGE_NODE_COUNT={len(registry.get('stage_graph', {}).get('nodes', []))}")
    print(f"STAGE_EDGE_COUNT={len(registry.get('stage_graph', {}).get('edges', []))}")
    print(f"ACTIVE_BEST_SET_FILE_COUNT={registry.get('active_pointer_graph', {}).get('active_best_set_file_count')}")
    print(f"ACTIVE_BEST_POINTER_REFERENCE_COUNT={registry.get('active_pointer_graph', {}).get('active_best_pointer_reference_count')}")
    print(f"QUARANTINED_SURFACE_COUNT={len(state.get('quarantined_surfaces', []))}")
    return 0


def graph(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = read_registry(repo_root)
    graph_obj = registry.get("stage_graph", {})
    nodes = graph_obj.get("nodes", [])
    edges = graph_obj.get("edges", [])

    print("KC_L_ORCHESTRATOR_V2_GRAPH=1")
    print(f"NODE_COUNT={len(nodes)}")
    print(f"EDGE_COUNT={len(edges)}")
    print("PIPELINE_IS_OPEN_ENDED=1")
    for n in sorted(nodes, key=lambda x: int(x.get("stage_order", "999"))):
        print(
            f"STAGE\t{n.get('stage_order')}\t{n.get('stage_id')}\t"
            f"{n.get('stage_status')}\toutputs={n.get('output_root_count')}\t"
            f"runners={n.get('runner_count')}\tdeps={n.get('depends_on')}"
        )
    return 0


def pointers_validate(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = read_registry(repo_root)
    refs = registry.get("active_pointer_graph", {}).get("references", [])
    issues: list[str] = []

    active_refs = [r for r in refs if r.get("reference_scope") == "active_best"]
    for r in active_refs:
        rel = r.get("referenced_relpath", "")
        if not rel:
            issues.append(f"empty referenced_relpath in {r.get('set_file_relpath')}")
            continue
        p = resolve_repo_path(repo_root, rel)
        if not exists_or_symlink(p):
            issues.append(f"active pointer target missing: {rel} from {r.get('set_file_relpath')}")

    active_set_files = registry.get("active_pointer_graph", {}).get("set_files", [])
    for sf in active_set_files:
        rel = sf.get("set_file_relpath", "")
        if rel and not exists_or_symlink(resolve_repo_path(repo_root, rel)):
            issues.append(f"ACTIVE/BEST set file missing: {rel}")

    print("KC_L_ORCHESTRATOR_V2_POINTERS_VALIDATE=1")
    print(f"ACTIVE_POINTER_REFERENCE_COUNT={len(active_refs)}")
    print(f"ISSUE_COUNT={len(issues)}")
    for issue in issues:
        print(f"ISSUE={issue}")
    return 1 if issues else 0


def surfaces_classify(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = read_registry(repo_root)
    state = read_surface_state(repo_root)
    quarantine_by_source = {q.get("source_relpath"): q for q in state.get("quarantined_surfaces", [])}

    print("KC_L_ORCHESTRATOR_V2_SURFACES_CLASSIFY=1")
    surfaces = registry.get("data_surfaces", [])
    counter = Counter(s.get("surface_status") for s in surfaces)
    print(f"SURFACE_COUNT={len(surfaces)}")
    print(f"STATUS_COUNTER={dict(counter)}")

    for s in sorted(surfaces, key=lambda x: (x.get("surface_status", ""), x.get("root_name", ""))):
        rel = s.get("relpath", "")
        p = resolve_repo_path(repo_root, rel)
        exists_live = exists_or_symlink(p)
        quarantined = rel in quarantine_by_source
        print(
            f"SURFACE\t{s.get('surface_status')}\t{rel}\tstage={s.get('stage_candidate')}\t"
            f"live_exists={int(exists_live)}\tquarantined={int(quarantined)}\t"
            f"size={s.get('tree_size_human')}"
        )
    return 0


def validate_to(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = read_registry(repo_root)
    state = read_surface_state(repo_root)
    target = args.stage_id

    issues: list[str] = []
    protected_statuses = {"active_current", "active_in_progress", "protected_pipeline_family", "review_required"}
    quarantine_by_source = {q.get("source_relpath"): q for q in state.get("quarantined_surfaces", [])}

    for s in registry.get("data_surfaces", []):
        rel = s.get("relpath", "")
        status = s.get("surface_status", "")
        p = resolve_repo_path(repo_root, rel)
        exists_live = exists_or_symlink(p)

        if status in protected_statuses and not exists_live:
            issues.append(f"protected surface missing from live location: {rel} status={status}")

        if status == "legacy_archive_retain_candidate":
            if not exists_live and rel not in quarantine_by_source:
                issues.append(f"legacy surface missing but not recorded as quarantined: {rel}")
            if rel in quarantine_by_source:
                qp = resolve_repo_path(repo_root, quarantine_by_source[rel].get("quarantine_relpath", ""))
                if not exists_or_symlink(qp):
                    issues.append(f"quarantined surface target missing: {rel} -> {qp}")

    # Validate active pointers for any validate-to target.
    refs = registry.get("active_pointer_graph", {}).get("references", [])
    for r in refs:
        if r.get("reference_scope") != "active_best":
            continue
        rel = r.get("referenced_relpath", "")
        if rel and not exists_or_symlink(resolve_repo_path(repo_root, rel)):
            issues.append(f"active pointer target missing: {rel}")

    print("KC_L_ORCHESTRATOR_V2_VALIDATE_TO=1")
    print(f"TARGET_STAGE={target}")
    print("OPEN_ENDED_PIPELINE=1")
    print(f"CURRENT_ENDPOINT_IS_TERMINAL={int(bool(registry.get('current_endpoint_is_terminal')))}")
    print(f"ISSUE_COUNT={len(issues)}")
    for issue in issues:
        print(f"ISSUE={issue}")
    return 1 if issues else 0


def step68_smoke(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    runner = repo_root / "steps" / "step_06_8_review_packet_emission" / "scripts" / "run_step68_v2_review_packet_emission_from_postprocessed.py"
    if not runner.exists():
        print(f"ERROR: Step6.8 runner missing: {runner}")
        return 2

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, str(runner), "--out-dir", str(out_dir), "--run-id", args.run_id]

    print("KC_L_ORCHESTRATOR_V2_STEP68_SMOKE=1")
    print(f"REPO_ROOT={repo_root}")
    print(f"RUNNER={runner}")
    print(f"OUT_DIR={out_dir}")
    print(f"RUN_ID={args.run_id}")
    print("COMMAND=" + " ".join(cmd))

    proc = subprocess.run(cmd, cwd=str(repo_root), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out_dir / "orchestrator_v2_step68_stdout.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
    (out_dir / "orchestrator_v2_step68_stderr.log").write_text(proc.stderr, encoding="utf-8", errors="replace")
    print(f"RUNNER_RC={proc.returncode}")
    if proc.returncode != 0:
        return proc.returncode

    stats_path = out_dir / "STEP68_V2_REVIEW_PACKET_STATS.json"
    packets_path = out_dir / "step68_v2_review_packets.jsonl"
    if not stats_path.exists():
        print(f"ERROR: missing stats: {stats_path}")
        return 3
    if not packets_path.exists():
        print(f"ERROR: missing packets: {packets_path}")
        return 4

    stats = load_json(stats_path)
    packets = []
    with packets_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                packets.append(json.loads(line))

    unit = Counter(str(row.get("knowledge_unit_type")) for row in packets)
    reviewer = Counter(str((row.get("reviewer_decision") or {}).get("status")) for row in packets if isinstance(row.get("reviewer_decision"), dict))
    issues: list[str] = []

    def expect(name: str, actual: Any, expected: Any) -> None:
        if actual != expected:
            issues.append(f"{name}: expected {expected!r}, got {actual!r}")

    expect("stats.decision", stats.get("decision"), "PASS_STEP68_CURRENT_REVIEW_PACKET_VALIDATION")
    expect("stats.packet_count", stats.get("packet_count"), 165)
    expect("packet_count", len(packets), 165)
    expect("unit.kc", unit.get("kc"), 144)
    expect("unit.topic", unit.get("topic"), 21)
    expect("reviewer.pending", reviewer.get("pending"), 165)

    source_postprocessed = str(stats.get("source_postprocessed_jsonl", ""))
    if not source_postprocessed.startswith(str(repo_root)):
        issues.append(f"source_postprocessed_jsonl is not repo-local: {source_postprocessed}")

    print(f"STATS_DECISION={stats.get('decision')}")
    print(f"PACKET_COUNT={len(packets)}")
    print(f"UNIT_COUNTER={dict(unit)}")
    print(f"REVIEWER_STATUS_COUNTER={dict(reviewer)}")
    print(f"SOURCE_POSTPROCESSED_IS_REPO_LOCAL={int(source_postprocessed.startswith(str(repo_root)))}")
    print(f"VALIDATION_ISSUE_COUNT={len(issues)}")
    for issue in issues:
        print(f"VALIDATION_ISSUE={issue}")

    return 10 if issues else 0


def quarantine_plan(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = read_registry(repo_root)
    state = read_surface_state(repo_root)

    candidates = []
    for s in registry.get("data_surfaces", []):
        if s.get("surface_status") == "legacy_archive_retain_candidate":
            rel = s.get("relpath")
            candidates.append({
                "source_relpath": rel,
                "status": s.get("surface_status"),
                "stage_candidate": s.get("stage_candidate"),
                "tree_size_bytes": s.get("tree_size_bytes"),
                "tree_size_human": s.get("tree_size_human"),
                "quarantine_relpath": f"_quarantine/legacy_generated/data_processed/{Path(rel).name}",
            })

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, {
        "schema_version": "kc_l_quarantine_plan_v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": args.scope,
        "repo_root": str(repo_root),
        "candidate_count": len(candidates),
        "total_bytes": sum(int(c["tree_size_bytes"] or 0) for c in candidates),
        "candidates": candidates,
        "rule": "Only legacy_archive_retain_candidate data/processed roots are included.",
    })

    print("KC_L_ORCHESTRATOR_V2_QUARANTINE_PLAN=1")
    print(f"SCOPE={args.scope}")
    print(f"CANDIDATE_COUNT={len(candidates)}")
    print(f"TOTAL_BYTES={sum(int(c['tree_size_bytes'] or 0) for c in candidates)}")
    print(f"PLAN_JSON={out}")
    for c in candidates:
        print(f"CANDIDATE\t{c['tree_size_bytes']}\t{c['source_relpath']}\t->{c['quarantine_relpath']}")
    return 0


def quarantine_apply_mirror(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    plan = load_json(Path(args.plan).resolve())
    state = read_surface_state(repo_root)

    manifest = Path(args.manifest).resolve()
    restore_script = Path(args.restore_script).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    restore_script.parent.mkdir(parents=True, exist_ok=True)

    issues: list[str] = []
    moved = []

    protected_statuses = {"active_current", "active_in_progress", "protected_pipeline_family", "review_required"}

    for c in plan.get("candidates", []):
        if c.get("status") in protected_statuses:
            issues.append(f"protected candidate incorrectly included: {c.get('source_relpath')}")
        src_rel = c.get("source_relpath", "")
        dst_rel = c.get("quarantine_relpath", "")
        if not src_rel.startswith("data/processed/"):
            issues.append(f"candidate outside data/processed: {src_rel}")
        if not dst_rel.startswith("_quarantine/legacy_generated/data_processed/"):
            issues.append(f"bad quarantine target: {dst_rel}")

    if issues:
        print("KC_L_ORCHESTRATOR_V2_QUARANTINE_APPLY_PREFLIGHT_FAILED=1")
        print(f"ISSUE_COUNT={len(issues)}")
        for issue in issues:
            print(f"ISSUE={issue}")
        return 1

    for c in plan.get("candidates", []):
        src_rel = c["source_relpath"]
        dst_rel = c["quarantine_relpath"]
        src = repo_root / src_rel
        dst = repo_root / dst_rel

        before_type = path_type(src)
        before_size = tree_size_no_follow(src)
        status = "not_attempted"
        error = ""

        if not exists_or_symlink(src):
            # If already quarantined, preserve idempotence.
            if exists_or_symlink(dst):
                status = "already_quarantined"
            else:
                status = "source_missing"
                error = "source missing and quarantine target missing"
                issues.append(f"{src_rel}: {error}")
        elif exists_or_symlink(dst):
            status = "destination_exists"
            error = "destination already exists"
            issues.append(f"{dst_rel}: destination already exists")
        else:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(src, dst)
                status = "moved"
            except Exception as exc:
                status = "move_failed"
                error = repr(exc)
                issues.append(f"{src_rel}: {error}")

        after_src_exists = exists_or_symlink(src)
        after_dst_exists = exists_or_symlink(dst)
        after_size = tree_size_no_follow(dst) if after_dst_exists else 0

        rec = {
            "source_relpath": src_rel,
            "quarantine_relpath": dst_rel,
            "before_type": before_type,
            "before_size_bytes": before_size,
            "after_quarantine_size_bytes": after_size,
            "after_source_exists": after_src_exists,
            "after_quarantine_exists": after_dst_exists,
            "status": status,
            "error": error,
        }
        moved.append(rec)

        if status == "moved":
            if after_src_exists:
                issues.append(f"source still exists after move: {src_rel}")
            if not after_dst_exists:
                issues.append(f"quarantine target missing after move: {dst_rel}")
            if before_size != after_size:
                issues.append(f"size mismatch after quarantine: {src_rel} before={before_size} after={after_size}")

    with manifest.open("w", encoding="utf-8") as f:
        for rec in moved:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    # Update surface state only if movement is internally clean.
    if not issues:
        existing = {q.get("source_relpath"): q for q in state.get("quarantined_surfaces", [])}
        for rec in moved:
            if rec["status"] in {"moved", "already_quarantined"}:
                existing[rec["source_relpath"]] = {
                    "source_relpath": rec["source_relpath"],
                    "quarantine_relpath": rec["quarantine_relpath"],
                    "quarantined_utc": datetime.now(timezone.utc).isoformat(),
                    "manifest": str(manifest),
                    "status": rec["status"],
                }
        state["quarantined_surfaces"] = list(existing.values())
        write_surface_state(repo_root, state)

    restore_script.write_text(
        "#!/usr/bin/env bash\n"
        "set +e\n"
        f"REPO={json.dumps(str(repo_root))}\n"
        f"MANIFEST={json.dumps(str(manifest))}\n"
        f"PY={json.dumps(sys.executable)}\n"
        "echo \"===== RESTORE KC_L V2 MIRROR QUARANTINE =====\"\n"
        "\"$PY\" - \"$REPO\" \"$MANIFEST\" <<'PYRESTORE'\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "repo = Path(sys.argv[1])\n"
        "manifest = Path(sys.argv[2])\n"
        "rows=[]\n"
        "if manifest.exists():\n"
        "    with manifest.open('r', encoding='utf-8', errors='replace') as f:\n"
        "        for line in f:\n"
        "            if line.strip(): rows.append(json.loads(line))\n"
        "issues=[]\n"
        "restored=0\n"
        "for rec in reversed(rows):\n"
        "    src = repo / rec['source_relpath']\n"
        "    dst = repo / rec['quarantine_relpath']\n"
        "    if not (dst.exists() or dst.is_symlink()):\n"
        "        continue\n"
        "    if src.exists() or src.is_symlink():\n"
        "        issues.append(f'source already exists during restore: {src}')\n"
        "        continue\n"
        "    src.parent.mkdir(parents=True, exist_ok=True)\n"
        "    os.rename(dst, src)\n"
        "    restored += 1\n"
        "print(f'RESTORE_ROW_COUNT={len(rows)}')\n"
        "print(f'RESTORE_MOVED_BACK_COUNT={restored}')\n"
        "print(f'RESTORE_ISSUE_COUNT={len(issues)}')\n"
        "for issue in issues[:80]: print('RESTORE_ISSUE=' + issue)\n"
        "sys.exit(1 if issues else 0)\n"
        "PYRESTORE\n"
        "RC=$?\n"
        "echo \"RESTORE_RC=$RC\"\n"
        "echo \"TERMINAL_STILL_ACTIVE=1\"\n"
        "return \"$RC\" 2>/dev/null || exit \"$RC\"\n",
        encoding="utf-8",
    )
    os.chmod(restore_script, 0o755)

    status_counter = Counter(r["status"] for r in moved)
    moved_count = status_counter.get("moved", 0)
    total_moved = sum(int(r["before_size_bytes"]) for r in moved if r["status"] == "moved")

    print("KC_L_ORCHESTRATOR_V2_QUARANTINE_APPLY_MIRROR=1")
    print(f"PLAN_CANDIDATE_COUNT={len(plan.get('candidates', []))}")
    print(f"MOVED_COUNT={moved_count}")
    print(f"STATUS_COUNTER={dict(status_counter)}")
    print(f"MOVED_TOTAL_BYTES={total_moved}")
    print(f"MOVED_TOTAL_HUMAN={human_size(total_moved)}")
    print(f"ISSUE_COUNT={len(issues)}")
    print(f"MANIFEST={manifest}")
    print(f"RESTORE_SCRIPT={restore_script}")
    for issue in issues:
        print(f"ISSUE={issue}")
    return 1 if issues else 0


def _resolve_upstream_output_root(state: dict[str, Any], dep_stage_id: str) -> str:
    entry = run_state_mod.get_stage_entry(state, dep_stage_id)
    if entry is None or entry.get("status") != "completed":
        raise StageNotWiredError(f"upstream stage {dep_stage_id!r} has not completed in this run yet")
    output_root = entry.get("output_root")
    if not output_root:
        raise StageNotWiredError(f"upstream stage {dep_stage_id!r} has no recorded output_root")
    return output_root


def _find_single_file(directory: Path, pattern: str) -> Path:
    """Several confirmed-good runner scripts (step 6.6, 6.9-6.13, ...) generate their own
    internal UTC-timestamp run_id for output/set-manifest naming, decoupled from any --run-id
    this orchestrator passes (confirmed by reading their own choose_run_paths()/utc_stamp()
    logic - none of them accept --run-id at all). Their outputs.processed_root/sets_root ARE
    deterministic from this orchestrator's run_id (via the per-run config override), but the
    exact filename inside that directory is not - glob for the single match rather than
    guessing a timestamp. Raises StageNotWiredError (not silently returning a wrong file) if
    the match count isn't exactly 1, since a wrong guess here would silently feed a stale or
    wrong artifact downstream.
    """
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise StageNotWiredError(
            f"expected exactly one file matching {pattern!r} in {directory}, found {len(matches)}: {matches}"
        )
    return matches[0]


def _make_step2_doc_id(pdf_path: Path) -> str:
    """Mirror run_step2_pair_validate.slurm's own make_doc_id() bash function exactly (same
    regex, same DOC_/DOC fallback), so orchestrator-submitted step_02 invocations produce the
    identical doc_id a manual run of the confirmed-good real launcher would have produced.
    """
    stem = pdf_path.stem
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    safe = re.sub(r"_{2,}", "_", safe).strip("_")
    return f"DOC_{safe}" if safe else "DOC"


def _prepare_step_02_invocations(
    spec: Any,
    *,
    run_id: str,
    repo_root: Path,
    run_dir: Path,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """step_02_pdf_ingest is the one confirmed genuine architectural fork in this pipeline:
    run_step2.py processes exactly one document per invocation (see stage_registry.py notes),
    so this orchestrator must submit one invocation per document rather than reuse the generic
    single-invocation _prepare_stage_invocation() contract. Documents come from this run's own
    RUN_STATE.json course_materials field (populated by the fresh-run request, see run_state.py)
    - never a hardcoded historical document list, matching every other dynamic-resolution fix
    made this session.

    Each invocation shares ONE rendered per-run config (output.processed_blockstore_dir
    overridden to a run-id-scoped directory) so all documents merge into the SAME
    _sets/ACTIVE_STEP2_SET.txt - run_step2.py's own _write_step2_active_set() does this merge
    itself via a read-existing/merge/rewrite cycle with NO file locking, confirmed by reading
    its source directly. Running multiple invocations against that pointer truly concurrently
    would race (one document's contribution silently lost, not a loud error) - callers MUST
    submit these serially (chained via --dependency=afterok), never in parallel; see run_stage()
    below, which does exactly that.
    """
    course_materials = state.get("course_materials") or []
    if not course_materials:
        raise StageNotWiredError(
            "step_02_pdf_ingest: RUN_STATE.json has no course_materials recorded for this run "
            "- seed it via the fresh-run request before submitting step_02 (never defaults to "
            "a historical document list)"
        )

    processed_blockstore_dir = repo_root / spec.output_root / run_id
    overrides = {"output": {"processed_blockstore_dir": str(processed_blockstore_dir)}}
    rendered_config_path = run_dir / f"{run_id}_step_02_config.json"
    render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)

    invocations: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for raw_pdf in course_materials:
        pdf_path = resolve_repo_path(repo_root, str(raw_pdf))
        if not pdf_path.exists():
            raise StageNotWiredError(f"step_02_pdf_ingest: course material PDF not found: {pdf_path}")
        doc_id = _make_step2_doc_id(pdf_path)
        if doc_id in seen_doc_ids:
            raise StageNotWiredError(
                f"step_02_pdf_ingest: two course materials normalize to the same doc_id {doc_id!r} "
                f"({pdf_path}) - rename one of the source PDFs"
            )
        seen_doc_ids.add(doc_id)
        invocations.append(
            {
                "doc_id": doc_id,
                "script_path": spec.script_path,
                "script_args": [
                    "--config", str(rendered_config_path),
                    "--pdf", str(pdf_path),
                    "--doc-id", doc_id,
                ],
            }
        )
    return invocations


# Fixed, non-run-scoped historical reference used by step_06_7_hierarchy_aware_synthesis_packets'
# --child-kc-drafts input - confirmed this session to be a legacy baseline snapshot used only
# for cross-referencing sibling/child draft context, not a same-run circular dependency (see
# ORCHESTRATOR_BUILD_STATE.md's build_step67_v2_hierarchy_aware_synthesis_packets.py entry).
STEP_06_7_CHILD_KC_DRAFTS_HISTORICAL_PATH = (
    "data/processed/kc_drafts_quality_overlays/"
    "step67_short_definition_repair_proposal_207434_20260520T114433Z/kc_draft_bundles.jsonl"
)


def _prepare_stage_invocation(
    spec: Any,
    *,
    run_id: str,
    repo_root: Path,
    run_dir: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Return {"script_path", "script_args", "needs_ollama", "ollama_params"} describing
    exactly how to invoke this stage for this run_id. Raises StageNotWiredError for any stage
    whose upstream-input-resolution logic isn't confirmed/built yet - refuses rather than
    guesses at what artifact should feed the stage's inputs.
    """
    stage_id = spec.stage_id

    if not spec.run_stage_wired:
        raise StageNotWiredError(
            f"{stage_id}: upstream-input resolution is not wired yet (see stage_registry.py notes)"
        )

    out_dir = repo_root / spec.output_root / run_id if spec.output_root else run_dir

    # ------------------------------------------------------------------------------------------
    # Added 2026-08-16: verified-pipeline stages (evidence_pack.py, v3-v74, 232 checks 0 failed),
    # replacing step_05p/step_05x/topic_05p/topic_05x/step_06_6/step_06_7-through-step_06_8 in
    # the automatic self-chain. See stage_registry.py's own retirement notes on those 9 stages
    # and CODEX_HANDOFF.md section 11/12 for the incident and rationale.
    # ------------------------------------------------------------------------------------------
    if stage_id == "step_05v_verified_kc_packets":
        hierarchy_output_root = Path(_resolve_upstream_output_root(state, "hierarchy_registry"))
        sentence_overlay_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))
        hierarchy_overlay_jsonl = resolve_hierarchy_overlay_jsonl_from_output_root(
            repo_root=repo_root, hierarchy_output_root=hierarchy_output_root,
        )
        source_overlay_jsonl = resolve_sentence_overlay_jsonl_from_output_root(
            repo_root=repo_root, sentence_overlay_output_root=sentence_overlay_output_root,
        )

        profiles_dir = out_dir / "profiles"
        packets_dir = out_dir / "packets"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        packets_dir.mkdir(parents=True, exist_ok=True)

        profiles_jsonl = profiles_dir / "kc_profiles.jsonl"
        kc_packets_jsonl = packets_dir / "kc_packets.jsonl"
        kc_packet_stats_json = packets_dir / "kc_packet_stats.json"
        topic_packets_jsonl = packets_dir / "topic_packets.jsonl"
        topic_packet_stats_json = packets_dir / "topic_packet_stats.json"

        build_profiles_script = repo_root / "v3/pipeline/01_build_profiles.py"
        verify_fixes_script = repo_root / "v3/verify/verify_pipeline_fixes.py"
        build_kc_packets_script = repo_root / "v3/pipeline/02_build_kc_packets.py"
        build_topic_packets_script = repo_root / "v3/pipeline/03_build_topic_packets.py"

        verify_fixes_cmd = slurm_render._build_command_line(HPC_PYTHON_BIN, str(verify_fixes_script), [])
        build_kc_packets_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN, str(build_kc_packets_script),
            [
                "--corpus-jsonl", str(source_overlay_jsonl),
                "--profile-jsonl", str(profiles_jsonl),
                "--out-jsonl", str(kc_packets_jsonl),
                "--stats-json", str(kc_packet_stats_json),
                "--bm25-pool", "400", "--max-passages", "40", "--max-chars", "14000",
                "--min-relevance", "0.55",
            ],
        )
        build_topic_packets_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN, str(build_topic_packets_script),
            [
                "--hierarchy-jsonl", str(hierarchy_overlay_jsonl),
                "--kc-packets-jsonl", str(kc_packets_jsonl),
                "--out-jsonl", str(topic_packets_jsonl),
                "--stats-json", str(topic_packet_stats_json),
            ],
        )

        extra_commands = [
            verify_fixes_cmd,
            "VERIFY_FIXES_RC=$?",
            'echo "VERIFY_FIXES_RC=$VERIFY_FIXES_RC"',
            'if [ "$VERIFY_FIXES_RC" -ne 0 ]; then exit "$VERIFY_FIXES_RC"; fi',
            "",
            build_kc_packets_cmd,
            "BUILD_KC_PACKETS_RC=$?",
            'echo "BUILD_KC_PACKETS_RC=$BUILD_KC_PACKETS_RC"',
            'if [ "$BUILD_KC_PACKETS_RC" -ne 0 ]; then exit "$BUILD_KC_PACKETS_RC"; fi',
            "",
            build_topic_packets_cmd,
            "BUILD_TOPIC_PACKETS_RC=$?",
            'echo "BUILD_TOPIC_PACKETS_RC=$BUILD_TOPIC_PACKETS_RC"',
            'if [ "$BUILD_TOPIC_PACKETS_RC" -ne 0 ]; then exit "$BUILD_TOPIC_PACKETS_RC"; fi',
        ]
        return {
            "script_path": str(build_profiles_script),
            "script_args": [
                "--overlay-jsonl", str(hierarchy_overlay_jsonl),
                "--out-jsonl", str(profiles_jsonl),
            ],
            "needs_ollama": False,
            "ollama_params": None,
            "extra_commands": extra_commands,
        }

    if stage_id in ("step_06v_kc_draft_generation", "step_06v_topic_draft_generation"):
        is_topic = stage_id == "step_06v_topic_draft_generation"
        packets_output_root = Path(_resolve_upstream_output_root(state, "step_05v_verified_kc_packets"))
        packets_dir = packets_output_root / "packets"
        selected_packets_jsonl = packets_dir / ("topic_packets.jsonl" if is_topic else "kc_packets.jsonl")
        packet_stats_json = packets_dir / ("topic_packet_stats.json" if is_topic else "kc_packet_stats.json")

        overrides = dict(state.get("overrides") or {})
        # No default model - a fallback here is exactly the kind of silent, hardcoded model
        # preference that defeats this pipeline's model-agnostic design. Every invocation must
        # say explicitly which model it wants.
        model_name = overrides.get("model")
        if not model_name:
            raise StageNotWiredError(
                f"{stage_id}: no model specified. This stage is model-agnostic by design and "
                "has no default - pass RUN_STATE.json overrides.model (or the equivalent "
                "--model at submission) explicitly, e.g. \"qwen3.8:27b\" or \"gemma4:31b\"."
            )
        model_name = str(model_name)
        context_length = int(overrides.get("num_ctx") or 32768)
        # Sanitized, filesystem-safe identifier derived from whatever model is actually
        # configured - never a hardcoded string - so drafts from any number of different models
        # can coexist under the same run_id without one silently overwriting another's real
        # output at a shared path.
        # Context length is a property of the MODEL, not of the run. Resolved from the model's own
        # runtime profile first; a per-run override only applies to a model that declares nothing.
        # Job 246037 is why: that run's RUN_STATE carried num_ctx=65536 from when it was configured
        # for gemma4, and after the drafting model was correctly switched to qwen3.8 the stale
        # sizing stayed. qwen3.8's hybrid attention+SSM architecture cannot reuse KV cache
        # ("forcing full prompt re-processing due to lack of cache data" in ollama_serve.log), so at
        # 65536 every call re-processed the whole prompt and timed out at 1200s with zero output -
        # 16 of 71 units in 5.5 hours, all failed, before the job was cancelled.
        _profile_context = _resolve_ollama_runtime(repo_root, model_name)[2]
        if _profile_context:
            context_length = int(_profile_context)
        model_slug = re.sub(r"[^a-zA-Z0-9]+", "_", model_name).strip("_")

        out_dir = out_dir / model_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        # --plan-json written directly here (Python, at render time) as the confirmed inert
        # placeholder (packet_source, row_count, unit_type_counter), populated from the real
        # packet builder's own stats.json - matches step_06_7_kc_draft_generation's own
        # (retired) notes recommending exactly this, rather than an empty {} stub.
        plan_json_path = out_dir / "plan.json"
        packet_stats: dict[str, Any] = {}
        if packet_stats_json.exists():
            try:
                packet_stats = read_json(packet_stats_json)
            except Exception:
                packet_stats = {}
        plan_obj = {
            "packet_source": str(selected_packets_jsonl),
            "row_count": packet_stats.get("units_with_evidence") or packet_stats.get("topic_units"),
            "unit_type_counter": {"topic": 1} if is_topic else {"kc": 1},
        }
        plan_json_path.write_text(json.dumps(plan_obj), encoding="utf-8")

        run_label = f"topic_{model_slug}" if is_topic else f"kc_{model_slug}"
        probe_script = repo_root / (
            "steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py"
        )
        base_runner = repo_root / "v3/pipeline/04_draft_runner.py"

        script_args = [
            "--base-runner", str(base_runner),
            "--selected-packets-jsonl", str(selected_packets_jsonl),
            "--plan-json", str(plan_json_path),
            "--out-dir", str(out_dir),
            "--run-id", run_label,
            "--model", model_name,
            "--num-ctx", str(context_length),
            "--num-predict", "16000",
            "--timeout-s", "1200",
            "--seed", "20260812",
        ]

        final_drafts_jsonl = out_dir / ("topic_drafts.jsonl" if is_topic else "kc_drafts.jsonl")
        raw_drafts_jsonl = out_dir / "step67_v2_tiny_smoke_drafts.jsonl"
        validate_script = repo_root / "v3/verify/validate_drafts.py"
        archive_dir = out_dir / "archive"

        extra_commands = [
            f'[ -f {slurm_render._shell_quote(str(raw_drafts_jsonl))} ] || {{ echo "FATAL: no drafts produced"; exit 20; }}',
            f'cp {slurm_render._shell_quote(str(raw_drafts_jsonl))} {slurm_render._shell_quote(str(final_drafts_jsonl))}',
            f'[ -s {slurm_render._shell_quote(str(final_drafts_jsonl))} ] || {{ echo "FATAL: draft copy produced an empty file"; exit 21; }}',
            f'echo "drafts -> {final_drafts_jsonl} ($(wc -l < {slurm_render._shell_quote(str(final_drafts_jsonl))}) rows)"',
            "",
            f'mkdir -p {slurm_render._shell_quote(str(archive_dir))}',
            f'ARCHIVE_BASE={slurm_render._shell_quote(str(archive_dir))}/$(basename {slurm_render._shell_quote(str(final_drafts_jsonl))} .jsonl)_job${{SLURM_JOB_ID:-unknown}}',
            f'cp {slurm_render._shell_quote(str(final_drafts_jsonl))} "${{ARCHIVE_BASE}}.jsonl"',
            f'echo "archived -> ${{ARCHIVE_BASE}}.jsonl"',
            "",
            slurm_render._build_command_line(
                HPC_PYTHON_BIN, str(validate_script),
                [
                    "--drafts-jsonl", str(final_drafts_jsonl),
                    "--packets-jsonl", str(selected_packets_jsonl),
                    "--run-id", run_label,
                ],
            ),
            "VALIDATE_RC=$?",
            'echo "VALIDATE_RC=$VALIDATE_RC"',
            'if [ "$VALIDATE_RC" -ne 0 ]; then exit "$VALIDATE_RC"; fi',
        ]

        return {
            "script_path": str(probe_script),
            "script_args": script_args,
            "needs_ollama": True,
            "ollama_params": {
                "model": model_name,
                "num_ctx": context_length,
                "num_predict": 0,
                "partition": "gpu80GB",
                "gres": "gpu:1",
                "cpus_per_task": 8,
                "mem": "96G",
                "time_limit": "12:00:00",
                # 2026-08-16 (job 245994 incident): the probe script's own exit code is
                # informational, not a real failure signal - see render_ollama_job's own
                # require_main_command_success docstring/comment. extra_commands above already
                # does the real gating (raw-drafts-file check + VALIDATE_RC from the actual
                # validate_drafts.py run), so it must run regardless of the probe's rc.
                "require_main_command_success": False,
            },
            "extra_commands": extra_commands,
        }

    if stage_id == "step_06v_assemble_library":
        overrides = dict(state.get("overrides") or {})
        model_name = overrides.get("model")
        if not model_name:
            raise StageNotWiredError(
                f"{stage_id}: no model specified - assembly reads one specific model's drafts, "
                "and which one must be explicit (RUN_STATE.json overrides.model), not assumed."
            )
        model_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(model_name)).strip("_")
        kc_draft_output_root = Path(_resolve_upstream_output_root(state, "step_06v_kc_draft_generation"))
        topic_draft_output_root = Path(_resolve_upstream_output_root(state, "step_06v_topic_draft_generation"))
        kc_drafts_jsonl = kc_draft_output_root / model_slug / "kc_drafts.jsonl"
        topic_drafts_jsonl = topic_draft_output_root / model_slug / "topic_drafts.jsonl"

        out_dir = out_dir / model_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        library_json = out_dir / "kc_library.json"

        script_args = [
            "--kc-drafts-jsonl", str(kc_drafts_jsonl),
            "--topic-drafts-jsonl", str(topic_drafts_jsonl),
            "--out-json", str(library_json),
            "--run-id", run_id,
        ]

        return {
            "script_path": str(repo_root / "v3/pipeline/05_assemble_kc_library.py"),
            "script_args": script_args,
            "needs_ollama": False,
        }

    if stage_id == "step_06v_review":
        overrides = dict(state.get("overrides") or {})
        model_name = overrides.get("model")
        if not model_name:
            raise StageNotWiredError(
                f"{stage_id}: no model specified - review reads one specific model's drafts, "
                "and which one must be explicit (RUN_STATE.json overrides.model), not assumed."
            )
        model_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(model_name)).strip("_")
        kc_draft_output_root = Path(_resolve_upstream_output_root(state, "step_06v_kc_draft_generation"))
        source_drafts_jsonl = kc_draft_output_root / model_slug / "kc_drafts.jsonl"

        out_dir.mkdir(parents=True, exist_ok=True)
        postprocess_dir = out_dir / "_postprocess"
        emit_dir = out_dir / "_emit"

        postprocess_script = repo_root / (
            "steps/step_06_7_postprocessed_review_source/scripts/run_step67_v2_postprocess_review_source.py"
        )
        emit_script = repo_root / (
            "steps/step_06_8_review_packet_emission/scripts/"
            "run_step68_v2_review_packet_emission_from_postprocessed.py"
        )

        postprocessed_jsonl = postprocess_dir / "step67_v2_postprocessed_review_source.jsonl"
        emit_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN, str(emit_script),
            [
                "--postprocessed-jsonl", str(postprocessed_jsonl),
                "--out-dir", str(emit_dir),
                "--run-id", run_id,
            ],
        )

        final_review_jsonl = out_dir / "review_packets.jsonl"
        raw_review_jsonl = emit_dir / "step68_v2_review_packets.jsonl"

        extra_commands = [
            # render_cpu_job already checked the main script_path command's (postprocess) own
            # RC before running any extra_commands at all - no redundant check needed here.
            emit_cmd,
            "EMIT_RC=$?",
            'echo "EMIT_RC=$EMIT_RC"',
            'if [ "$EMIT_RC" -ne 0 ]; then exit "$EMIT_RC"; fi',
            "",
            f'[ -f {slurm_render._shell_quote(str(raw_review_jsonl))} ] || {{ echo "FATAL: emitter produced no packets"; exit 30; }}',
            f'cp {slurm_render._shell_quote(str(raw_review_jsonl))} {slurm_render._shell_quote(str(final_review_jsonl))}',
            f'[ -s {slurm_render._shell_quote(str(final_review_jsonl))} ] || {{ echo "FATAL: review copy produced an empty file"; exit 31; }}',
            f'echo "review packets -> {final_review_jsonl} ($(wc -l < {slurm_render._shell_quote(str(final_review_jsonl))}) units)"',
        ]

        return {
            "script_path": str(postprocess_script),
            "script_args": [
                "--source-drafts-jsonl", str(source_drafts_jsonl),
                "--accepted-baseline-run-id", run_id,
                "--out-dir", str(postprocess_dir),
                "--run-id", run_id,
            ],
            "needs_ollama": False,
            "ollama_params": None,
            "extra_commands": extra_commands,
        }

    if stage_id == "hierarchy_registry":
        hierarchy_path_spec = str(state.get("hierarchy_path") or "").strip()
        if not hierarchy_path_spec:
            raise StageNotWiredError(
                "hierarchy_registry requires RUN_STATE.json hierarchy_path from the fresh-run request"
            )
        hierarchy_path = resolve_repo_path(repo_root, hierarchy_path_spec)
        if not hierarchy_path.exists():
            raise StageNotWiredError(f"hierarchy_registry input hierarchy not found: {hierarchy_path}")

        layout = get_operator_layout(repo_root)
        normalize_output_root = repo_root / "data/processed/hierarchy" / run_id
        normalize_script = repo_root / "steps/step_01_hierarchy/scripts/01_hierarchy_normalize.py"
        overlay_script = repo_root / spec.script_path

        overlay_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(overlay_script),
            [
                "--hierarchy", str(hierarchy_path),
                "--out_root", str(out_dir),
                "--runs_dir", str(layout.runs_root),
            ],
            raw_trailing_args=(
                '--normalized_registry "$STEP1_NORMALIZED_REGISTRY"',
                '--normalized_manifest "$STEP1_NORMALIZED_MANIFEST"',
            ),
        )
        extra_commands = [
            f"STEP1_NORMALIZED_ROOT={slurm_render._shell_quote(str(normalize_output_root))}",
            'STEP1_REGISTRY_MATCHES=("$STEP1_NORMALIZED_ROOT"/*/kc_registry.jsonl)',
            'if [ ! -e "${STEP1_REGISTRY_MATCHES[0]:-}" ]; then',
            '  echo "ERROR_STEP1_NORMALIZED_REGISTRY_NOT_FOUND=1"',
            "  exit 42",
            "fi",
            'if [ "${#STEP1_REGISTRY_MATCHES[@]}" -ne 1 ]; then',
            '  echo "ERROR_STEP1_NORMALIZED_REGISTRY_AMBIGUOUS=${#STEP1_REGISTRY_MATCHES[@]}"',
            "  exit 43",
            "fi",
            'STEP1_NORMALIZED_REGISTRY="${STEP1_REGISTRY_MATCHES[0]}"',
            'STEP1_NORMALIZED_DIR="$(dirname "$STEP1_NORMALIZED_REGISTRY")"',
            'STEP1_NORMALIZED_MANIFEST="$STEP1_NORMALIZED_DIR/hierarchy_manifest.json"',
            'if [ ! -f "$STEP1_NORMALIZED_MANIFEST" ]; then',
            '  echo "ERROR_STEP1_NORMALIZED_MANIFEST_NOT_FOUND=1"',
            "  exit 44",
            "fi",
            'echo "STEP1_NORMALIZED_REGISTRY=$STEP1_NORMALIZED_REGISTRY"',
            'echo "STEP1_NORMALIZED_MANIFEST=$STEP1_NORMALIZED_MANIFEST"',
            "",
            overlay_cmd,
            "OVERLAY_RC=$?",
            'echo "OVERLAY_RC=$OVERLAY_RC"',
            'if [ "$OVERLAY_RC" -ne 0 ]; then exit "$OVERLAY_RC"; fi',
        ]
        return {
            "script_path": str(normalize_script),
            "script_args": [
                "--hierarchy", str(hierarchy_path),
                "--out_root", str(normalize_output_root),
                "--runs_dir", str(layout.runs_root),
            ],
            "needs_ollama": False,
            "ollama_params": None,
            "extra_commands": extra_commands,
        }

    if stage_id == "step_05_3_evidence_recalibrated":
        # Fix (2026-07-26, confirmed real incident, run 20260725T225807Z_9e856df6):
        # resolve_hierarchy_normalize_output_root() derives Step 01's intermediate output path
        # (data/processed/hierarchy/<run_id>) from THIS run's own top-level run_id - correct
        # only when hierarchy_registry genuinely executed under that exact run_id. When a run
        # instead reuses an EARLIER run's already-completed hierarchy_registry stage (as this
        # orchestrator's own seed-a-new-run-from-an-existing-one's-upstream-artifacts pattern
        # does, and as advance_run.py's own "reused_finished_utc"/"reused_from_run_id" fields on
        # the stage entry already anticipate), that directory was never created for the new
        # run_id at all - build_step5_3_run_config crashed with FileNotFoundError, and because
        # step_06_6_drafting_input_overlay hard-depends on step_05_3_evidence_recalibrated in
        # the stage graph (not just its own config), the whole chain stayed permanently blocked
        # a level deeper than a single cascading-exception issue, even after isolating that
        # exception in chain.py's submission loop (see that fix's own comment) - this needed
        # its own real fix, not just isolation. hierarchy_registry's own recorded output_root
        # (already correctly resolved from RUN_STATE.json regardless of reuse, via
        # _resolve_upstream_output_root) always names the REAL run_id hierarchy_registry
        # executed under as the parent directory of its own "hierarchy_registry" path segment
        # (the "directory-restructuring convention" from advance_run.py's own
        # create_run_convention_symlink()) - reuse that confirmed-correct run_id here instead of
        # assuming it always equals this stage's own run_id.
        hierarchy_registry_output_root = Path(_resolve_upstream_output_root(state, "hierarchy_registry"))
        hierarchy_source_run_id = hierarchy_registry_output_root.parent.name
        if not (repo_root / "data/processed/hierarchy" / hierarchy_source_run_id).exists():
            hierarchy_source_run_id = run_id
        hierarchy_normalize_output_root = resolve_hierarchy_normalize_output_root(
            repo_root=repo_root, run_id=hierarchy_source_run_id,
        )
        sentence_overlay_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))
        # Scope to step_05x's own gap KCs when its output is already available (2026-07-26 fix -
        # see build_step5_3_run_config's own docstring): step_05_3 is not a formal graph
        # dependency of step_05x, so this stays a best-effort lookup with a graceful fallback to
        # the full registry (unchanged prior behavior) when step_05x hasn't produced output yet.
        # 2026-07-26: previously reverted after this caused a real incident (run
        # 20260725T225807Z_9e856df6, job 234940) - scoping silently poisoned the GLOBAL, non-
        # run-specific ACTIVE_STEP5_3_EVIDENCE_SET.txt pointer that step_06_6_drafting_input_
        # overlay trusts as "the full registry" (step_05_3 faithfully recorded whatever
        # kc_registry_path it was given as its own upstream.kc_registry_path provenance field,
        # which was the scoped subset). Re-enabled now that run_step5_3.py has its own fix: a
        # new full_kc_registry_path_for_provenance input lets build_step5_3_run_config supply
        # the TRUE full registry for that provenance field while kc_registry_path itself still
        # drives real (scoped) processing - see both files' own docstrings/comments.
        step5x_pack_jsonl = None
        try:
            step5x_output_root = Path(_resolve_upstream_output_root(state, "step_05x_kc_evidence_stage_v3"))
            candidate = step5x_output_root / "kc_evidence_packs.jsonl"
            if candidate.exists():
                step5x_pack_jsonl = candidate
        except StageNotWiredError:
            pass
        # 2026-07-30 ablation studies: KC_L_ABLATION_STEP5_3_BASE_CONFIG lets an ablation run
        # render its per-run config from a different base YAML (e.g. a standalone
        # ablation_studies/.../step5_3.ablation_*.yaml with reranker weights/thresholds
        # neutralized) - unset means build_step5_3_run_config() falls back to BASE_CONFIG_PATH
        # (the production config), byte-identical to every run before this override existed.
        ablation_step5_3_base_config_env = os.environ.get("KC_L_ABLATION_STEP5_3_BASE_CONFIG")
        rendered_config_path = build_step5_3_run_config(
            run_id=run_id,
            repo_root=repo_root,
            run_dir=run_dir,
            hierarchy_normalize_output_root=hierarchy_normalize_output_root,
            sentence_overlay_output_root=sentence_overlay_output_root,
            step5x_pack_jsonl=step5x_pack_jsonl,
            base_config_path=Path(ablation_step5_3_base_config_env) if ablation_step5_3_base_config_env else None,
        )
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
            # Local reranker model (Qwen3-Reranker-8B-seq-cls, CUDA) - no Ollama call, but a
            # real GPU is required. No dedicated step5_3 SLURM template exists to copy from, so
            # this reuses the same gpu80GB/gpu:a100:1 combination already confirmed-good for
            # step_02's MinerU GPU routing (see that stage's own notes for why).
            "partition": "gpu80GB",
            "gres": "gpu:a100:1",
            "time_limit": "12:00:00",
        }

    if stage_id == "step_06_6_drafting_input_overlay":
        # 2026-07-26: step_05_3_evidence_recalibrated dismantled as a dependency of this stage -
        # it caused four distinct incidents in one night, each a layer deeper than the last (see
        # drafting_input_overlay.py's SOURCE_STEP_KIND comment for the full account). Evidence
        # now comes solely from step_05x_kc_evidence_stage_v3/topic_05x_evidence_stage_v3's own
        # per-run pack via the assembly-bridge mechanism already wired below - no step_05_3
        # pointer resolution needed here anymore.
        #
        # SEPARATE BUG, EXPOSED (not caused) by the above removal, FIXED same pass: step_06_6's
        # own base yaml hardcodes step4_active_set_pointer/step4_5_active_set_pointer to GLOBAL,
        # non-run-scoped pointers under /path/to/scratch/scratch/.../_sets/ACTIVE_STEP4[_5]_SET.txt -
        # confirmed stale (resolves to a 2026-04-07 snapshot, 3 docs, vs this run's real 4+ docs)
        # via direct verification, contradicting stage_registry.py's own prior note that these
        # "are at least never literally stale". This was silently masked for months by step_05_3
        # providing the real, run-scoped sentence_corpus_path as an accidental fallback in
        # run_step6_6's own kc_registry/sentence_corpus resolution - removing step_05_3 surfaced
        # it as a hard crash (FileNotFoundError on a stale corpus path) rather than a silent
        # quality gap. Resolve both real per-run pointers directly, same pattern already proven
        # for step_05_3's own bridge (Path(_resolve_upstream_output_root(...)) / "_sets" / ...).
        step4_output_root = Path(_resolve_upstream_output_root(state, "step_04_3_embedding_index"))
        step4_5_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))
        # THIRD bug in this same pass, exposed the same way as the step4/step4_5 one above:
        # without step_05_3's own upstream manifest as an accidental fallback, run_step6_6's
        # kc_registry_path defaulted to a "current_step_artifacts" cache confirmed stale (frozen
        # 2026-04-24, 144 rows) - reconstructing registry rows from evidence-pack topic_path_
        # labels instead (this run-stage's other existing fallback) silently dropped 2 of 20 real
        # topics from the KC-level hierarchy paths, failing step_06_7's own topic_pack_rows_
        # missing_from_overlay_hierarchy check. Resolve THIS run's own real hierarchy_registry
        # output directly - same hierarchy_source_run_id-aware pattern already proven for
        # step_05_3's own config above (reused run_ids need the REAL run_id hierarchy_registry
        # executed under, not necessarily this stage's own run_id).
        hierarchy_registry_output_root = Path(_resolve_upstream_output_root(state, "hierarchy_registry"))
        hierarchy_source_run_id = hierarchy_registry_output_root.parent.name
        if not (repo_root / "data/processed/hierarchy" / hierarchy_source_run_id).exists():
            hierarchy_source_run_id = run_id
        hierarchy_normalize_output_root = resolve_hierarchy_normalize_output_root(
            repo_root=repo_root, run_id=hierarchy_source_run_id,
        )
        hierarchy_manifest = resolve_hierarchy_manifest_from_output_root(
            hierarchy_normalize_output_root=hierarchy_normalize_output_root
        )
        rendered_config_path, extra_cli_args = build_step6_6_run_config(
            run_id=run_id,
            repo_root=repo_root,
            run_dir=run_dir,
            step4_active_set_pointer=step4_output_root / "_sets" / "ACTIVE_STEP4_SET.txt",
            step4_5_active_set_pointer=step4_5_output_root / "_sets" / "ACTIVE_STEP4_5_SET.txt",
            kc_registry_path=Path(hierarchy_manifest["registry_path"]),
        )
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path), *extra_cli_args],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_05p_kc_retrieval_profiles":
        sentence_overlay_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))
        hierarchy_output_root = Path(_resolve_upstream_output_root(state, "hierarchy_registry"))
        step4_3_output_root = Path(_resolve_upstream_output_root(state, "step_04_3_embedding_index"))
        # 2026-07-30 ablation studies: KC_L_ABLATION_STEP5P_BASE_CONFIG lets an ablation run
        # render its per-run config from a different base YAML (e.g. a standalone
        # ablation_studies/.../step5p.ablation_*.yaml with a different model) - unset means
        # build_step5p_run_config() falls back to BASE_CONFIG_PATH (the production config),
        # byte-identical to every run before this override existed.
        ablation_base_config_env = os.environ.get("KC_L_ABLATION_STEP5P_BASE_CONFIG")
        rendered_config_path = build_step5p_run_config(
            run_id=run_id,
            repo_root=repo_root,
            run_dir=run_dir,
            hierarchy_output_root=hierarchy_output_root,
            sentence_overlay_output_root=sentence_overlay_output_root,
            base_config_path=Path(ablation_base_config_env) if ablation_base_config_env else None,
        )
        rendered_config = read_json(rendered_config_path)
        behavior = dict(rendered_config.get("behavior") or {})
        model_cfg = dict(rendered_config.get("model") or {})
        use_model = bool(behavior.get("use_model", False))
        llm_policy = str(behavior.get("llm_policy") or ("always" if use_model else "never")).strip().lower()
        checkpoint_every = int(behavior.get("checkpoint_every", 1) or 1)
        context_length = int(model_cfg.get("context_length", 32768) or 32768)
        model_name = str(model_cfg.get("model") or "").strip()
        if use_model and llm_policy != "never" and not model_name:
            raise StageNotWiredError("step_05p_kc_retrieval_profiles missing model.model in rendered config")

        # Always resume (2026-07-26): confirmed real incident (run 20260724T122826Z_9e856df6,
        # job 232893) - a step_05p job cancelled mid-run for anomalous node slowdown ("only 5
        # KCs in 6+ hours on gpu02") left a partial kc_retrieval_profiles.jsonl on disk for its
        # run_id; the resubmission (this same run-stage path, without --resume) hit
        # build_profiles()'s "Requested run_id already exists" guard and died in 14 seconds,
        # before ever reaching the self-chain trailer - the run sat at status="running" forever
        # with nothing to notice. Confirmed safe by reading build_profiles()'s own resume
        # handling: resume=True with no existing profile_jsonl behaves identically to a fresh
        # run (existing_by_kc stays empty, every KC gets processed); with a partial file, it
        # skips only the already-completed KC rows and continues from there (with its own
        # duplicate-row safety check). Always passing --resume costs nothing on a genuinely
        # fresh run_id and makes every retry (manual or via the reconcile_stalled_stages.py
        # watchdog) actually succeed instead of repeating this exact failure.
        script_args = ["--config", str(rendered_config_path), "--run-id", run_id, "--resume"]
        if use_model and llm_policy != "never":
            script_args += [
                "--use-model",
                "--llm-policy", llm_policy,
                "--model", model_name,
                "--checkpoint-every", str(checkpoint_every),
                # Embedding-assisted tie-breaking (2026-07-25): reuses the SAME Ollama server
                # this stage already starts for its use_model LLM call - just an additional
                # model (qwen3-embedding:8b) served from it, not new GPU/infra. Only passed
                # when use_model is true, since without a running Ollama server there is
                # nothing to embed against.
                "--embedding-index-root", str(step4_3_output_root),
            ]
        return {
            "script_path": spec.script_path,
            "script_args": script_args,
            "needs_ollama": bool(use_model and llm_policy != "never"),
            "ollama_params": (
                {
                    "model": model_name,
                    "num_ctx": context_length,
                    "num_predict": 0,
                    "partition": "gpu80GB",
                    "gres": "gpu:1",
                    "cpus_per_task": 8,
                    "mem": "64G",
                    # 2026-08-02 ablation studies: KC_L_ABLATION_STEP5P_TIME_LIMIT lets a slow
                    # model (e.g. qwen3.5:9b under think=true, confirmed this session to run
                    # roughly 6x slower per-KC than non-thinking models at this stage - a real
                    # job hit 85/159 KCs at 6h35m, on track to be killed by the 8h wall time
                    # before finishing) get a longer wall-clock budget - unset means the
                    # original hardcoded 08:00:00, byte-identical to every run before this
                    # override existed.
                    "time_limit": os.environ.get("KC_L_ABLATION_STEP5P_TIME_LIMIT") or "08:00:00",
                    # render_ollama_job() hardcodes OLLAMA_MAX_LOADED_MODELS="1" - fine when
                    # only the generation model is ever loaded, but this stage now also loads
                    # qwen3-embedding:8b (4.7GB) alongside the generation model (gemma4:31b,
                    # 19GB) on the SAME Ollama server. Without this override, every KC would
                    # force-unload/reload one model to load the other - a swap-thrashing cycle
                    # for all 144 KCs. gpu80GB's A100 has ample headroom (~24GB of 80GB) for
                    # both to stay resident at once, so raise the cap to 2 for this stage only
                    # (extra_env values apply after render_ollama_job()'s own hardcoded exports,
                    # so this cleanly overrides without touching the shared function).
                    "extra_env": {"OLLAMA_MAX_LOADED_MODELS": "2"},
                }
                if use_model and llm_policy != "never"
                else None
            ),
        }

    if stage_id == "topic_05p_retrieval_profiles":
        # Confirmed this session (see ORCHESTRATOR_BUILD_STATE.md's "topic_05p rewired to
        # hierarchy_registry" entry): there is no separate topic registry - the KC hierarchy IS
        # the topic hierarchy. hierarchy_registry's own hierarchy_overlay.jsonl already carries
        # every "topic unit" topic_05p needs (its node_type=="topic" rows whose children are all
        # KC leaves directly) - the one-off reconstructed-registry workaround
        # (data/processed/topic_reconstructed_registry/..., self-documented as "not the missing
        # human-reviewed topic final-resolution artifact") is no longer needed. Verified exact
        # 1:1 match (same labels/KC-counts/hier_node_id hashes) against that reconstruction's 21
        # topic rows / 144 edges on a real hierarchy_overlay.jsonl before wiring this.
        hierarchy_output_root = Path(_resolve_upstream_output_root(state, "hierarchy_registry"))
        sentence_overlay_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))

        hierarchy_overlay_jsonl = resolve_hierarchy_overlay_jsonl_from_output_root(
            repo_root=repo_root,
            hierarchy_output_root=hierarchy_output_root,
        )
        source_overlay_jsonl = resolve_sentence_overlay_jsonl_from_output_root(
            repo_root=repo_root,
            sentence_overlay_output_root=sentence_overlay_output_root,
        )

        topic_bridge_dir = run_dir / "topic_registry_bridge_inputs"
        topic_registry_jsonl, topic_edges_jsonl = extract_topic_registry_and_edges(
            hierarchy_overlay_jsonl=hierarchy_overlay_jsonl,
            out_dir=topic_bridge_dir,
        )

        # topic_05p has no base_config_path (its real historical runs were config-less CLI-only
        # invocations, confirmed via stage_registry.py's notes - the shipped default YAMLs are
        # inert stubs for this track), so model selection has no config file to read from. Honor
        # the current run's own declared override when the fresh-run request supplied one
        # (RUN_STATE.json's overrides.model/num_ctx - not currently read by any other branch in
        # this file, but exactly what that field exists for), falling back to the historical
        # confirmed-good values (gemma4:31b, matching this stage's own gap-analysis notes) and
        # step_05p's own config-default context length otherwise.
        overrides = dict(state.get("overrides") or {})
        model_name = str(overrides.get("model") or "gemma4:31b")
        context_length = int(overrides.get("num_ctx") or 32768)
        think_override = overrides.get("think")

        topic_output_root = "data/processed/topic_retrieval_profiles"
        topic_set_manifest_root = "data/processed/topic_retrieval_profiles/_sets"

        script_args = [
            "--topic-registry-jsonl", str(topic_registry_jsonl),
            "--topic-to-kc-edges-jsonl", str(topic_edges_jsonl),
            "--source-overlay-jsonl", str(source_overlay_jsonl),
            "--output-root", topic_output_root,
            "--set-manifest-root", topic_set_manifest_root,
            "--run-id", run_id,
            "--use-model",
            "--llm-policy", "always",
            "--model", model_name,
        ]
        if think_override is not None:
            # 2026-08-02 ablation studies (Ablation 4, qwen3.5:9b @ Step 5p): topic_05p never
            # had a --config passed (confirmed via parse_profile_args - --config exists but was
            # always omitted here), so model_config["think"] always defaulted to None/False in
            # build_profiles()/builder.py (the SAME call path step_05p itself uses) - confirmed
            # this session via a controlled diagnostic that qwen3.5:9b hangs indefinitely under
            # think=False and needs it explicitly True. Only rendered when overrides.think is
            # explicitly set, so every run without this key (baseline, Ablations 1-3) stays
            # byte-identical to before this change. main_topic_profile() applies --model/
            # --base-url AFTER loading --config, so this doesn't disturb the existing
            # overrides.model/num_ctx convention.
            think_config_path = run_dir / f"{run_id}_topic_05p_model_config.json"
            think_config_path.write_text(
                json.dumps({"model": {"think": bool(think_override)}}), encoding="utf-8"
            )
            script_args += ["--config", str(think_config_path)]
        return {
            "script_path": spec.script_path,
            "script_args": script_args,
            "needs_ollama": True,
            "ollama_params": {
                "model": model_name,
                "num_ctx": context_length,
                "num_predict": 0,
                "partition": "gpu80GB",
                "gres": "gpu:1",
                "cpus_per_task": 8,
                "mem": "64G",
                "time_limit": "08:00:00",
                # Confirmed via job 228292's crash: this script's own argparse (topic_5p5x/
                # pipeline.py's parse_profile_args()) has --base-url, not --ollama-host -
                # render_ollama_job()'s default auto-appended flag doesn't exist here. --base-url
                # is also used RAW (no scheme normalization, unlike step_05p's own --ollama-host
                # handling), and downstream code requires a full scheme-included URL
                # (base_url.rstrip("/") + "/api/chat"), so the bare "$OLLAMA_HOST" host:port
                # value can't be passed as-is either - it must carry the http:// scheme.
                "ollama_host_cli_arg": '--base-url "http://$OLLAMA_HOST"',
            },
        }

    if stage_id == "topic_05x_evidence_stage_v3":
        # Real chain (4 scripts, confirmed via each one's own argparse in topic_5p5x/pipeline.py):
        # run_step5tx_topic_candidate_bank.py -> run_step5tx_topic_scored_candidates.py ->
        # run_step5tx_topic_scored_trace_rehydration.py -> run_step5tx_topic_pack_composition.py.
        # The rehydration step is the fix for the confirmed-still-live field-dropping defect
        # (see ORCHESTRATOR_BUILD_STATE.md's topic_05x sections): run_topic_scored_candidates_
        # stage() in pipeline.py still just calls build_scored_candidate_artifacts() and copies
        # its output verbatim, silently dropping bridge_loader_knowledge_unit_type/
        # topic5p_weak_profile_carry_forward and never populating content/soft risk_flags.
        # scored_trace_rehydration.py's rehydrate_topic5x_scored_trace_fields() (now with a real,
        # reimplemented risk_tags() detector, verified byte-for-byte against the historical
        # 608-row fixture - see scripts/maintenance/verify_topic5x_scored_trace_rehydration_
        # reconstruction.py) restores both. pack_composition is pointed at the REHYDRATED output,
        # not scored_candidates' raw one.
        #
        # Reuses topic_05p's own bridge registry/edges output (written under topic_05p's own
        # run_dir, not regenerated here) so both stages operate against the exact same topic-unit
        # definitions for this run - mirrors the dependency this stage already declares on
        # topic_05p_retrieval_profiles.
        topic05p_output_root = Path(_resolve_upstream_output_root(state, "topic_05p_retrieval_profiles"))
        sentence_overlay_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))

        topic05p_run_dir = run_dir.parent / "topic_05p_retrieval_profiles"
        topic_bridge_dir = topic05p_run_dir / "topic_registry_bridge_inputs"
        topic_registry_jsonl = topic_bridge_dir / "topic_registry_from_hierarchy_registry.jsonl"
        topic_edges_jsonl = topic_bridge_dir / "topic_to_kc_edges_from_hierarchy_registry.jsonl"
        if not topic_registry_jsonl.exists() or not topic_edges_jsonl.exists():
            raise StageNotWiredError(
                f"topic_05p's bridge registry/edges not found under {topic_bridge_dir} - "
                "topic_05p_retrieval_profiles must actually have run (not just be marked "
                "completed) for this run_id before topic_05x_evidence_stage_v3 can be prepared"
            )

        topic_profile_jsonl = topic05p_output_root / "topic_retrieval_profiles.jsonl"
        if not topic_profile_jsonl.exists():
            raise StageNotWiredError(f"topic_05p profile output not found: {topic_profile_jsonl}")

        source_overlay_jsonl = resolve_sentence_overlay_jsonl_from_output_root(
            repo_root=repo_root,
            sentence_overlay_output_root=sentence_overlay_output_root,
        )

        candidate_bank_output_root = "data/processed/topic_evidence_stage_v3_candidate_bank"
        candidate_bank_set_manifest_root = "data/processed/topic_evidence_stage_v3_candidate_bank/_sets"
        scored_candidates_output_root = "data/processed/topic_evidence_stage_v3_scored_candidates"
        scored_candidates_set_manifest_root = "data/processed/topic_evidence_stage_v3_scored_candidates/_sets"
        pack_composition_output_root = "data/processed/topic_evidence_stage_v3_evidence_packs"
        pack_composition_set_manifest_root = "data/processed/topic_evidence_stage_v3_evidence_packs/_sets"

        topic_candidate_bank_jsonl = repo_root / candidate_bank_output_root / run_id / "topic_candidate_bank.jsonl"
        topic_scored_candidates_jsonl = repo_root / scored_candidates_output_root / run_id / "topic_scored_candidates.jsonl"
        rehydration_out_dir = run_dir / "trace_rehydration"
        rehydrated_topic_scored_jsonl = rehydration_out_dir / "topic_scored_candidates.jsonl"

        scored_candidates_script = repo_root / (
            "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_scored_candidates.py"
        )
        rehydration_script = repo_root / (
            "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_scored_trace_rehydration.py"
        )
        pack_composition_script = repo_root / (
            "steps/step_05_tx_topic_evidence_stage/scripts/run_step5tx_topic_pack_composition.py"
        )

        scored_candidates_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(scored_candidates_script),
            [
                "--topic-candidate-bank-jsonl", str(topic_candidate_bank_jsonl),
                "--output-root", scored_candidates_output_root,
                "--set-manifest-root", scored_candidates_set_manifest_root,
                "--run-id", run_id,
            ],
        )
        rehydration_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(rehydration_script),
            [
                "--source-scored-jsonl", str(topic_scored_candidates_jsonl),
                "--typed-candidate-bank-jsonl", str(topic_candidate_bank_jsonl),
                "--out-dir", str(rehydration_out_dir),
                "--run-id", run_id,
            ],
        )
        pack_composition_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(pack_composition_script),
            [
                "--topic-scored-candidates-jsonl", str(rehydrated_topic_scored_jsonl),
                "--output-root", pack_composition_output_root,
                "--set-manifest-root", pack_composition_set_manifest_root,
                "--run-id", run_id,
            ],
        )

        extra_commands = [
            scored_candidates_cmd,
            "SCORED_CANDIDATES_RC=$?",
            'echo "SCORED_CANDIDATES_RC=$SCORED_CANDIDATES_RC"',
            'if [ "$SCORED_CANDIDATES_RC" -ne 0 ]; then exit "$SCORED_CANDIDATES_RC"; fi',
            "",
            rehydration_cmd,
            "TRACE_REHYDRATION_RC=$?",
            'echo "TRACE_REHYDRATION_RC=$TRACE_REHYDRATION_RC"',
            'if [ "$TRACE_REHYDRATION_RC" -ne 0 ]; then exit "$TRACE_REHYDRATION_RC"; fi',
            "",
            pack_composition_cmd,
            "PACK_COMPOSITION_RC=$?",
            'echo "PACK_COMPOSITION_RC=$PACK_COMPOSITION_RC"',
            'if [ "$PACK_COMPOSITION_RC" -ne 0 ]; then exit "$PACK_COMPOSITION_RC"; fi',
        ]

        return {
            "script_path": spec.script_path,
            "script_args": [
                "--topic-registry-jsonl", str(topic_registry_jsonl),
                "--topic-to-kc-edges-jsonl", str(topic_edges_jsonl),
                "--source-overlay-jsonl", str(source_overlay_jsonl),
                "--topic-profile-jsonl", str(topic_profile_jsonl),
                "--output-root", candidate_bank_output_root,
                "--set-manifest-root", candidate_bank_set_manifest_root,
                "--run-id", run_id,
            ],
            "needs_ollama": False,
            "ollama_params": None,
            "extra_commands": extra_commands,
        }

    if stage_id == "step_05x_kc_evidence_stage_v3":
        # Genuine 3-real-script chain (run_step5x_v3_candidate_bank.py ->
        # run_step5x_v3_scored_candidates.py -> run_step5x_v3_pack_composition.py), confirmed via
        # each script's own argparse + its call into its library module's real function
        # signature - not assumed from script names. All 3 honor a passed --run-id directly
        # (chosen_run_id = str(run_id or utc_stamp()), confirmed by reading each module's own
        # _materialize_run_paths()/build_evidence_pack_artifacts()), so every artifact path in
        # this chain is knowable at Python render time - unlike step_04_patches, no bash-level
        # glob-discovery of an internal timestamp is needed. Chained within ONE SLURM job via
        # render_cpu_job's extra_commands, the same multi-command pattern already used for
        # step_04_patches/step_04_3 - not registered as 3 separate StageSpec entries, matching
        # this stage's single coarse node in the JSON registry (explicit decision, see
        # ORCHESTRATOR_BUILD_STATE.md).
        sentence_overlay_output_root = Path(_resolve_upstream_output_root(state, "step_04_5_sentence_overlay"))
        hierarchy_output_root = Path(_resolve_upstream_output_root(state, "hierarchy_registry"))
        step5p_output_root = Path(_resolve_upstream_output_root(state, "step_05p_kc_retrieval_profiles"))

        registry_jsonl = resolve_hierarchy_overlay_jsonl_from_output_root(
            repo_root=repo_root,
            hierarchy_output_root=hierarchy_output_root,
        )
        source_overlay_jsonl = resolve_sentence_overlay_jsonl_from_output_root(
            repo_root=repo_root,
            sentence_overlay_output_root=sentence_overlay_output_root,
        )
        # run_step5p_kc_retrieval_profile.py honors a passed --run-id directly (confirmed:
        # run_id = args.run_id or f"step5p_{utc_stamp()}"), and step_05p's own
        # build_step5p_run_config() never overrides --output-root, so step_05p's real
        # output_root is step5p.default.yaml's own outputs.output_root
        # ("data/processed/kc_retrieval_profiles"), which is identical to this StageSpec's
        # registered output_root for step_05p - a flat join is correct here, no double-nesting
        # like step_04_5 (confirmed by reading build_profiles() in
        # src/kc_l/retrieval_profile/builder.py directly: processed_dir = output_root / run_id,
        # profile_jsonl = processed_dir / "kc_retrieval_profiles.jsonl").
        profile_jsonl = step5p_output_root / "kc_retrieval_profiles.jsonl"
        if not profile_jsonl.exists():
            raise StageNotWiredError(f"step_05p profile output not found: {profile_jsonl}")

        candidate_bank_output_root = "data/processed/evidence_stage_v3_candidate_bank"
        candidate_bank_set_manifest_root = "data/processed/evidence_stage_v3_candidate_bank/_sets"
        scored_candidates_output_root = "data/processed/evidence_stage_v3_scored_candidates"
        scored_candidates_set_manifest_root = "data/processed/evidence_stage_v3_scored_candidates/_sets"
        pack_composition_output_root = "data/processed/evidence_stage_v3_evidence_packs"
        pack_composition_set_manifest_root = "data/processed/evidence_stage_v3_evidence_packs/_sets"

        candidate_bank_jsonl = repo_root / candidate_bank_output_root / run_id / "candidate_bank.jsonl"
        scored_candidates_jsonl = repo_root / scored_candidates_output_root / run_id / "scored_candidates.jsonl"

        scored_candidates_script = repo_root / (
            "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_scored_candidates.py"
        )
        pack_composition_script = repo_root / (
            "steps/step_05_x_evidence_stage_v3/scripts/run_step5x_v3_pack_composition.py"
        )

        scored_candidates_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(scored_candidates_script),
            [
                "--candidate-bank-jsonl", str(candidate_bank_jsonl),
                "--output-root", scored_candidates_output_root,
                "--set-manifest-root", scored_candidates_set_manifest_root,
                "--run-id", run_id,
            ],
        )
        pack_composition_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(pack_composition_script),
            [
                "--scored-candidates-jsonl", str(scored_candidates_jsonl),
                "--registry-jsonl", str(registry_jsonl),
                "--output-root", pack_composition_output_root,
                "--set-manifest-root", pack_composition_set_manifest_root,
                "--run-id", run_id,
            ],
        )

        extra_commands = [
            scored_candidates_cmd,
            "SCORED_CANDIDATES_RC=$?",
            'echo "SCORED_CANDIDATES_RC=$SCORED_CANDIDATES_RC"',
            'if [ "$SCORED_CANDIDATES_RC" -ne 0 ]; then exit "$SCORED_CANDIDATES_RC"; fi',
            "",
            pack_composition_cmd,
            "PACK_COMPOSITION_RC=$?",
            'echo "PACK_COMPOSITION_RC=$PACK_COMPOSITION_RC"',
            'if [ "$PACK_COMPOSITION_RC" -ne 0 ]; then exit "$PACK_COMPOSITION_RC"; fi',
        ]

        return {
            "script_path": spec.script_path,
            "script_args": [
                "--registry-jsonl", str(registry_jsonl),
                "--source-overlay-jsonl", str(source_overlay_jsonl),
                "--profile-jsonl", str(profile_jsonl),
                "--output-root", candidate_bank_output_root,
                "--set-manifest-root", candidate_bank_set_manifest_root,
                "--run-id", run_id,
            ],
            "needs_ollama": False,
            "ollama_params": None,
            "extra_commands": extra_commands,
        }

    if stage_id == "step_06_7_hierarchy_aware_synthesis_packets":
        step6_6_output_root = Path(_resolve_upstream_output_root(state, "step_06_6_drafting_input_overlay"))
        step6_6_sets_root = step6_6_output_root / "_sets"
        step66_set_path = _find_single_file(step6_6_sets_root, "*_step6_6_kc_drafting_input_overlay_set.json")

        # 2026-07-15 fix: previously resolved via BEST_TOPIC5X_FINAL_PACK_FOR_STEP6_SET.txt, a
        # 2026-05-19 one-time snapshot nothing ever updates (same confirmed staleness bug as
        # step6_6_evidence_bridge's step5x/topic5x resolution - see its module-level note).
        # topic_05x_evidence_stage_v3 is run_stage_wired and produces genuine fresh per-run
        # output, so resolve THIS run's own real output instead, matching every other
        # stage-to-stage dependency in this file.
        topic5x_pack_set_path = repo_root / run_scoped_pack_set_path(TOPIC5X_V3_OUTPUT_ROOT, run_id)
        topic5x_pack_set_obj = read_json(topic5x_pack_set_path)
        topic5x_pack_jsonl = read_kc_evidence_packs_jsonl(topic5x_pack_set_obj)

        child_kc_drafts_path = repo_root / STEP_06_7_CHILD_KC_DRAFTS_HISTORICAL_PATH

        return {
            "script_path": spec.script_path,
            "script_args": [
                "--step66-set", str(step66_set_path),
                "--topic5x-pack", str(topic5x_pack_jsonl),
                "--child-kc-drafts", str(child_kc_drafts_path),
                "--out-dir", str(out_dir),
            ],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_06_7_kc_draft_generation":
        packets_output_root = Path(_resolve_upstream_output_root(state, "step_06_7_hierarchy_aware_synthesis_packets"))
        selected_packets_jsonl = packets_output_root / "step67_v2_hierarchy_aware_synthesis_packets.jsonl"
        packet_stats_json = packets_output_root / "step67_v2_hierarchy_aware_synthesis_packet_stats.json"
        if not packet_stats_json.exists():
            raise StageNotWiredError(f"expected packet-builder stats file missing: {packet_stats_json}")
        packet_stats = json.loads(packet_stats_json.read_text(encoding="utf-8"))
        metrics = packet_stats.get("metrics", {})
        step67_runtime_cfg = load_stage_config(repo_root / STEP67_V2_RUNTIME_CONFIG)
        step67_models_cfg = dict(step67_runtime_cfg.get("models") or {})
        step67_generation_cfg = dict(step67_models_cfg.get("generation") or {})
        step67_num_ctx = int(step67_generation_cfg.get("num_ctx", 65536) or 65536)
        step67_seed = step67_generation_cfg.get("seed")
        # 2026-07-30/31 ablation studies: honor this run's own declared step_06_7-specific
        # model/num_ctx override (RUN_STATE.json's overrides.step_06_7_model/step_06_7_num_ctx)
        # - falls back to the existing hardcoded "gemma4:31b" / config-derived step67_num_ctx
        # when no override is set, so every run before this existed (and every run that doesn't
        # set an override) stays byte-identical.
        #
        # 2026-07-31 fix (confirmed real incident, Ablation 1 job 236965): this originally read
        # the SAME overrides.model/overrides.num_ctx keys topic_05p_retrieval_profiles's own
        # invocation-prep branch already uses - correct for a run where only one of the two
        # stages is being overridden, but silently wrong for a single-variable ablation that
        # needs topic_05p on one model (e.g. gemma4:12b) while step_06_7 stays on the
        # production default (gemma4:31b): both branches read the one shared field, so
        # step_06_7 silently inherited topic_05p's override too. Ablation 1's real drafting run
        # used gemma4:12b instead of gemma4:31b as a direct result (12/181 units failed with
        # malformed JSON - gemma4:12b was never verified against step_06_7's much larger,
        # deeply-nested drafting schema, only step_05p's simpler one). Using distinctly-named
        # step_06_7_model/step_06_7_num_ctx keys decouples the two stages' overrides completely
        # - topic_05p's own overrides.model/num_ctx convention is untouched.
        step67_overrides = dict(state.get("overrides") or {})
        step67_model_name = str(step67_overrides.get("step_06_7_model") or "gemma4:31b")
        if step67_overrides.get("step_06_7_num_ctx"):
            step67_num_ctx = int(step67_overrides["step_06_7_num_ctx"])

        # Minimal inert --plan-json placeholder (confirmed never read downstream - see
        # ORCHESTRATOR_BUILD_STATE.md), populated from the real packet builder's own stats
        # rather than left as a stub with made-up numbers.
        plan_json_path = run_dir / f"{run_id}_step67_v2_plan.json"
        plan_json_path.write_text(
            json.dumps(
                {
                    "packet_source": str(selected_packets_jsonl),
                    "row_count": metrics.get("all_packet_count"),
                    "unit_type_counter": {
                        "kc": metrics.get("kc_packet_count"),
                        "topic": metrics.get("topic_packet_count"),
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        base_runner_path = repo_root / "scripts/experimental/run_step67_v2_tiny_smoke.py"

        # Confirmed via job 228481's crash (KeyError: 'KC_L_FINAL_SCHEMA_RUNNER'): this stage's
        # own script_path (run_step67_v2_policy_segmentable_abstention_marker_fix.py) reads BOTH
        # KC_L_FINAL_SCHEMA_RUNNER and KC_L_SOURCE_SCHEMA_RUNNER as required env vars at module
        # import time (pathlib.Path(os.environ[...]), then importlib-loads each as a real script
        # module) - this was never wired here even at initial wiring time (commit 8f879d6 only
        # covered --base-runner/--timeout-s/--plan-json/--selected-packets-jsonl; that stage's own
        # verify script only ever dry-ran the render, never executed the real script through it,
        # so the gap was never caught until this real live job). Real, confirmed-correct values
        # (same ones scripts/maintenance/verify_step67_v2_chain_resurrection.py already exercises
        # against the resurrected v2_chain/ files at their new stable location):
        final_schema_runner_path = repo_root / (
            "steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_topic_schema_dict_aligned.py"
        )
        source_schema_runner_path = repo_root / (
            "steps/step_06_7_kc_draft_generation/scripts/v2_chain/run_step67_v2_schema_contract_probe.py"
        )

        step67_script_args = [
            "--base-runner", str(base_runner_path),
            "--plan-json", str(plan_json_path),
            "--selected-packets-jsonl", str(selected_packets_jsonl),
            "--out-dir", str(out_dir),
            "--run-id", run_id,
            "--model", step67_model_name,
            "--num-ctx", str(step67_num_ctx),
            "--num-predict", "16000",
            "--timeout-s", "1200",
        ]
        # 2026-07-28 fix: thread the seed through if the runtime config sets one (see
        # run_step67_v2_schema_contract_probe.py's own ollama_generate_schema() comment) -
        # same reasoning/pattern as step_05p's earlier seed fix.
        if step67_seed is not None:
            step67_script_args += ["--seed", str(int(step67_seed))]

        return {
            "script_path": spec.script_path,
            "script_args": step67_script_args,
            "needs_ollama": True,
            "ollama_params": {
                "model": step67_model_name,
                "num_ctx": step67_num_ctx,
                "num_predict": 16000,
                "extra_env": {
                    "KC_L_FINAL_SCHEMA_RUNNER": str(final_schema_runner_path),
                    "KC_L_SOURCE_SCHEMA_RUNNER": str(source_schema_runner_path),
                },
            },
        }

    if stage_id == "step_06_9_review_audit_ingestion":
        step6_8_output_root = Path(_resolve_upstream_output_root(state, "step_06_8_review_packet_emission"))
        review_packet_set_manifest = step6_8_output_root / "STEP68_V2_REVIEW_PACKET_MANIFEST.json"

        overrides = {
            "inputs": {"review_packet_set_manifest": str(review_packet_set_manifest)},
            "outputs": {
                "processed_root": f"data/processed/kc_review_audits_restarted/{run_id}",
                "sets_root": f"data/processed/kc_review_audits_restarted/{run_id}/_sets",
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_06_9_config.json"
        render_stage_config(
            repo_root / "steps/step_06_9_kc_review_audit_ingestion/resources/step6_9.slice8.yaml",
            overrides,
            rendered_config_path,
        )
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_06_10_review_audit_resolution":
        # RESOLVED (Priority 1, live-run reconnection follow-up): run_step6_10_kc_review_audit_
        # resolution.py's own manifest-chase bug (legacy-only artifacts.review_packet_jsonl
        # read against step_06_8's real v2 run_id/outputs manifest) is now fixed in that script
        # directly - mirrors step_06_9's own resolve_review_packet_manifest() dual-schema
        # helper (duplicated, not imported - no step-to-step imports exist anywhere in this
        # repo). This orchestrator branch was previously entirely missing; step_06_9's own
        # output is self-generated-internal-timestamp-named (never accepts --run-id), same
        # class of problem as step_06_6/6_7 - glob-discover its real set-manifest filename via
        # _find_single_file() within THIS run's own run-scoped _sets/ dir (step_06_9's own
        # branch above already overrides outputs.processed_root/sets_root to be run-scoped, so
        # exactly one match is expected here, never a historical leftover).
        step6_9_output_root = Path(_resolve_upstream_output_root(state, "step_06_9_review_audit_ingestion"))
        step6_9_set_path = _find_single_file(
            step6_9_output_root / "_sets", "*_step6_9_kc_review_audits_restarted_set.json"
        )

        overrides = {
            "inputs": {"step6_9_set_manifest": str(step6_9_set_path)},
            "outputs": {
                "processed_root": f"data/processed/kc_review_audits_restarted_resolved/{run_id}",
                "sets_root": f"data/processed/kc_review_audits_restarted_resolved/{run_id}/_sets",
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_06_10_config.json"
        render_stage_config(
            repo_root / spec.base_config_path,
            overrides,
            rendered_config_path,
        )
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_06_7_postprocessed_review_source":
        drafts_output_root = _resolve_upstream_output_root(state, "step_06_7_kc_draft_generation")
        source_drafts_jsonl = str(Path(drafts_output_root) / "step67_v2_tiny_smoke_drafts.jsonl")
        return {
            "script_path": spec.script_path,
            "script_args": [
                "--source-drafts-jsonl", source_drafts_jsonl,
                "--accepted-baseline-run-id", run_id,
                "--out-dir", str(out_dir),
                "--run-id", run_id,
                "--update-best-pointer",
            ],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_06_8_review_packet_emission":
        postprocess_output_root = _resolve_upstream_output_root(state, "step_06_7_postprocessed_review_source")
        postprocessed_jsonl = str(Path(postprocess_output_root) / "step67_v2_postprocessed_review_source.jsonl")
        return {
            "script_path": spec.script_path,
            "script_args": [
                "--postprocessed-jsonl", postprocessed_jsonl,
                "--out-dir", str(out_dir),
                "--run-id", run_id,
                "--update-best-pointer",
            ],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_03_doctree_index":
        step2_output_root = Path(_resolve_upstream_output_root(state, "step_02_pdf_ingest"))
        overrides = {
            "input": {
                "step2_sets_dir": str(step2_output_root / "_sets"),
                "step2_active_set_file": str(step2_output_root / "_sets" / "ACTIVE_STEP2_SET.txt"),
            },
            "output": {
                "processed_doctree_dir": str(out_dir),
                "doctree_sets_dir": str(out_dir / "_sets"),
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_03_config.json"
        render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_03_5_blockstore_cleanup":
        step2_output_root = Path(_resolve_upstream_output_root(state, "step_02_pdf_ingest"))
        step3_output_root = Path(_resolve_upstream_output_root(state, "step_03_doctree_index"))
        overrides = {
            "input": {
                "step2_sets_dir": str(step2_output_root / "_sets"),
                "step2_active_set_file": str(step2_output_root / "_sets" / "ACTIVE_STEP2_SET.txt"),
                "step3_sets_dir": str(step3_output_root / "_sets"),
                "step3_active_set_file": str(step3_output_root / "_sets" / "ACTIVE_STEP3_SET.txt"),
            },
            "output": {
                "processed_enriched_dir": str(out_dir),
                "enriched_sets_dir": str(out_dir / "_sets"),
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_03_5_config.json"
        render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
        }

    if stage_id == "step_03_6_math_salvage":
        step3_5_output_root = Path(_resolve_upstream_output_root(state, "step_03_5_blockstore_cleanup"))
        overrides = {
            "input": {
                "step3_5_sets_dir": str(step3_5_output_root / "_sets"),
                "step3_5_active_set_file": str(step3_5_output_root / "_sets" / "ACTIVE_STEP3_5_SET.txt"),
            },
            "output": {
                "processed_dir": str(out_dir),
                "sets_dir": str(out_dir / "_sets"),
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_03_6_config.json"
        render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
            # Confirmed real (not stale) GPU requirement: this stage's own config comments say
            # so explicitly ("Choose a higher-accuracy backend than pipeline for salvage" /
            # device: "cuda"), and a real HPC run (job 228035, plain `big`-partition CPU node)
            # crashed with "RuntimeError: Found no NVIDIA driver on your system" while loading
            # the hybrid-auto-engine backend's VLM model - unlike Step 2's `pipeline` backend,
            # where --device is confirmed inert, this backend's extra CLI args ARE forwarded
            # into the model-loading call (mineru/cli/client.py's main() passes
            # extra_cli_args=tuple(ctx.args) straight through to the server). The confirmed-good
            # historical launcher (run_step3_6_actual_corpus_gpu.slurm) used gpu80GB/A100. This
            # stage was moved to gpu46GB/A40 on 2026-04-XX purely because gpu80GB was scarce that
            # particular night, with an explicit "revisit if VRAM proves insufficient" note that
            # was never revisited. Reverted back to gpu80GB/A100 on 2026-07-21: gpu46GB (job
            # 231833) hit a ~16h backfill estimate (both its nodes fully occupied by other users'
            # jobs) while gpu80GB sat completely idle, and a sibling GPU stage's own comments
            # elsewhere in this file already call gpu80GB/A100 the "CONFIRMED-GOOD" combination
            # after gpu46GB caused unexplained stalls on a related MinerU GPU workload (jobs
            # 227591, 227869). A100 has more VRAM than A40, so this is not a downgrade.
            "partition": "gpu80GB",
            "gres": "gpu:a100:1",
            "time_limit": "12:00:00",
        }

    if stage_id == "step_04_patches":
        step3_output_root = Path(_resolve_upstream_output_root(state, "step_03_doctree_index"))
        step3_6_output_root = Path(_resolve_upstream_output_root(state, "step_03_6_math_salvage"))
        active_step3 = step3_output_root / "_sets" / "ACTIVE_STEP3_SET.txt"
        active_step3_6 = step3_6_output_root / "_sets" / "ACTIVE_STEP3_6_SET.txt"

        processed_root = out_dir
        sets_dir = out_dir / "_sets"
        overrides = {
            "inputs": {
                "active_step3_set": str(active_step3),
                "active_step3_6_set": str(active_step3_6),
            },
            "outputs": {
                "processed_root": str(processed_root),
                "sets_dir": str(sets_dir),
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_04_patches_config.json"
        render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)

        # run_step4.py has no --run-id override (confirmed by reading it directly) - it always
        # generates its own internal timestamp run_id (now_run_id("step4")), decoupled from this
        # orchestrator's run_id, same class of problem as step 6.6/6.9-6.13 above. Its own freeze
        # script (freeze_step4_patches_set.py - confirmed this is the real one, co-located with
        # run_step4.py itself, not the differently-conventioned steps/step_04_2_patches/ copy or
        # the LEGACY variant) needs that EXACT internal run_id to locate the per-doc patch output
        # (processed_root/doc_id/run_id_step4/...), and that value only exists after run_step4.py
        # has actually finished - discover it via a bash-level glob in the same SLURM job (the
        # main command's own RUNNER_RC check, added by render_cpu_job whenever extra_commands is
        # non-empty, already guarantees the freeze step never runs if run_step4.py failed),
        # refusing loudly (not guessing) if the match count for the first document isn't exactly
        # 1 - the same "exactly one match or refuse" contract as _find_single_file, just
        # necessarily implemented in bash since the value isn't knowable at Python config-render
        # time.
        course_materials = state.get("course_materials") or []
        if not course_materials:
            raise StageNotWiredError(
                "step_04_patches: RUN_STATE.json has no course_materials recorded for this run "
                "- needed to know at least one doc_id to glob-discover step_04_patches' own "
                "internal run_id after it completes"
            )
        first_doc_id = _make_step2_doc_id(resolve_repo_path(repo_root, str(course_materials[0])))
        doc_dir = processed_root / first_doc_id

        freeze_script = repo_root / "steps/step_04_structure_retrieval_index/scripts/freeze_step4_patches_set.py"
        freeze_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(freeze_script),
            [
                "--repo-root", str(repo_root),
                "--processed-root", str(processed_root),
                "--sets-dir", str(sets_dir),
                "--active-step3", str(active_step3),
                "--active-step3-6", str(active_step3_6),
            ],
            raw_trailing_args=('--run-id "$STEP4_PATCHES_RUN_ID"',),
        )

        extra_commands = [
            f"STEP4_PATCHES_DOC_DIR={slurm_render._shell_quote(str(doc_dir))}",
            'STEP4_PATCHES_MATCHES=("$STEP4_PATCHES_DOC_DIR"/*/patch_summary.json)',
            'if [ ! -e "${STEP4_PATCHES_MATCHES[0]:-}" ]; then',
            '  echo "ERROR_STEP4_PATCHES_RUN_ID_NOT_FOUND=1"',
            "  exit 40",
            "fi",
            'if [ "${#STEP4_PATCHES_MATCHES[@]}" -ne 1 ]; then',
            '  echo "ERROR_STEP4_PATCHES_RUN_ID_AMBIGUOUS=${#STEP4_PATCHES_MATCHES[@]}"',
            "  exit 41",
            "fi",
            'STEP4_PATCHES_RUN_ID=$(basename "$(dirname "${STEP4_PATCHES_MATCHES[0]}")")',
            'echo "STEP4_PATCHES_DISCOVERED_RUN_ID=$STEP4_PATCHES_RUN_ID"',
            "",
            freeze_cmd,
            "FREEZE_RC=$?",
            'echo "FREEZE_RC=$FREEZE_RC"',
            'if [ "$FREEZE_RC" -ne 0 ]; then exit "$FREEZE_RC"; fi',
        ]

        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
            "extra_commands": extra_commands,
        }

    if stage_id == "step_04_3_embedding_index":
        layout = get_operator_layout(repo_root)
        step3_output_root = Path(_resolve_upstream_output_root(state, "step_03_doctree_index"))
        step3_6_output_root = Path(_resolve_upstream_output_root(state, "step_03_6_math_salvage"))
        step4_patches_output_root = Path(_resolve_upstream_output_root(state, "step_04_patches"))
        active_step3 = step3_output_root / "_sets" / "ACTIVE_STEP3_SET.txt"
        active_step3_6 = step3_6_output_root / "_sets" / "ACTIVE_STEP3_6_SET.txt"
        active_step4_patches = step4_patches_output_root / "_sets" / "ACTIVE_STEP4_PATCHES_SET.txt"

        processed_root = out_dir
        sets_dir = out_dir / "_sets"
        overrides = {
            "inputs": {
                "step3_set_active": str(active_step3),
                "step3_6_set_active": str(active_step3_6),
                "step4_patches_set_active": str(active_step4_patches),
            },
            "outputs": {
                "retrieval_root": str(processed_root),
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_04_3_config.json"
        render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)
        rendered_config = read_json(rendered_config_path)
        embedding_model = str((rendered_config.get("embedding") or {}).get("model") or "qwen3-embedding:8b")

        # Unlike step_04_patches, run_step4_3.py accepts --run-id directly, so its freeze step
        # can run in the same SLURM job without any bash-level glob-discovery of an internal
        # timestamped run_id. The main script writes its own audit dir to data/runs/<run_id>/;
        # freeze_step4_index_set_actual_corpus.py needs that exact path for summary.json.
        freeze_script = repo_root / "steps/step_04_structure_retrieval_index/scripts/freeze_step4_index_set_actual_corpus.py"
        step4_3_runner_dir = layout.runs_root / run_id
        freeze_cmd = slurm_render._build_command_line(
            HPC_PYTHON_BIN,
            str(freeze_script),
            [
                "--run-id", run_id,
                "--processed-root", str(processed_root),
                "--sets-dir", str(sets_dir),
                "--active-step3", str(active_step3),
                "--active-step3-6", str(active_step3_6),
                "--active-step4-patches", str(active_step4_patches),
                "--run-dir-step4-3", str(step4_3_runner_dir),
            ],
        )
        extra_commands = [
            freeze_cmd,
            "FREEZE_RC=$?",
            'echo "FREEZE_RC=$FREEZE_RC"',
            'if [ "$FREEZE_RC" -ne 0 ]; then exit "$FREEZE_RC"; fi',
        ]

        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path), "--run-id", run_id],
            "needs_ollama": True,
            "ollama_params": {
                "model": embedding_model,
                # run_step4_3.py itself only needs the dynamic --ollama-host endpoint; these
                # render-time knobs are for the shared Ollama wrapper and are not read by the
                # runner script.
                "num_ctx": 65536,
                "num_predict": 0,
                # Rerouted 2026-07-21 (same reasoning as step_03_6_math_salvage, see that
                # stage's comment): gpu46GB (job 231840) hit the exact same multi-hour backfill
                # stall (both its nodes fully occupied by other users) while gpu80GB sat
                # completely idle. This stage runs a single Ollama embedding model (qwen3-
                # embedding:8b), a lighter workload than the A40 was ever load-bearing for -
                # A100's 80GB has strictly more headroom, not less.
                "partition": "gpu80GB",
                "gres": "gpu:a100:1",
                "cpus_per_task": 12,
                "mem": "96G",
                "time_limit": "24:00:00",
            },
            "extra_commands": extra_commands,
        }

    if stage_id == "step_04_5_sentence_overlay":
        step4_3_output_root = Path(_resolve_upstream_output_root(state, "step_04_3_embedding_index"))
        active_step4_set = step4_3_output_root / "_sets" / "ACTIVE_STEP4_SET.txt"

        overrides = {
            "inputs": {
                # step4_5.default.yaml sets inputs.step4_active_set_pointer, while the
                # actual_corpus.yaml base this stage renders from sets a DIFFERENTLY-named
                # inputs.active_step4_set - main()'s own lookup checks step4_active_set_pointer
                # FIRST (cfg["inputs"].get("step4_active_set_pointer") or .get(
                # "active_step4_set")), confirmed the hard way while functionally verifying the
                # step_04_5 bug fix (an override of only active_step4_set was silently shadowed
                # by the default's step4_active_set_pointer surviving the merge). Both keys must
                # be overridden together.
                "step4_active_set_pointer": str(active_step4_set),
                "active_step4_set": str(active_step4_set),
                "active_step4_5_set_pointer": str(out_dir / "_sets" / "ACTIVE_STEP4_5_SET.txt"),
            },
            "outputs": {
                "processed_root": str(out_dir),
                "sets_dir": str(out_dir / "_sets"),
            },
        }
        rendered_config_path = run_dir / f"{run_id}_step_04_5_config.json"
        render_stage_config(repo_root / spec.base_config_path, overrides, rendered_config_path)
        return {
            "script_path": spec.script_path,
            "script_args": ["--config", str(rendered_config_path)],
            "needs_ollama": False,
            "ollama_params": None,
        }

    raise StageNotWiredError(f"{stage_id}: marked run_stage_wired=True but no invocation builder implemented")


def _chain_advance_extra_commands(*, run_id: str, stage_id: str) -> list[str]:
    """Raw bash lines that call advance_run.py as a trailer, only run once the main command
    (and any stage-specific extra_commands before this) have already succeeded - see
    render_cpu_job/render_ollama_job's own extra_commands contract. advance_run.py resolves
    its own --repo-root default from its own file location under $REPO/scripts/, so no
    --repo-root needs to be passed here; $REPO is already the cwd by the time this runs.
    """
    advance_cmd = slurm_render._build_command_line(
        HPC_PYTHON_BIN, "scripts/advance_run.py", [run_id, stage_id]
    )
    return [
        advance_cmd,
        "ADVANCE_RC=$?",
        'echo "ADVANCE_RC=$ADVANCE_RC"',
        'if [ "$ADVANCE_RC" -ne 0 ]; then exit "$ADVANCE_RC"; fi',
    ]


def _run_step_02_stage(
    args: argparse.Namespace,
    spec: Any,
    *,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    state: dict[str, Any],
    state_path: Path,
) -> int:
    """step_02_pdf_ingest submits one SLURM job per document, chained serially via
    --dependency=afterok (never in parallel - see _prepare_step_02_invocations' docstring for
    the confirmed unsynchronized-pointer-write race this avoids). job_id recorded in
    RUN_STATE.json is the LAST job in the chain; SLURM's own afterok semantics mean polling just
    that job_id is sufficient to know the whole stage succeeded (see run_state.set_stage_submitted).
    """
    if not spec.run_stage_wired:
        print(f"ERROR_STAGE_NOT_WIRED={spec.stage_id}")
        print(f"ERROR={spec.stage_id}: upstream-input resolution is not wired yet (see stage_registry.py notes)")
        return 3

    try:
        invocations = _prepare_step_02_invocations(spec, run_id=run_id, repo_root=repo_root, run_dir=run_dir, state=state)
    except StageNotWiredError as exc:
        print(f"ERROR_STAGE_NOT_WIRED={spec.stage_id}")
        print(f"ERROR={exc}")
        return 3

    print("KC_L_ORCHESTRATOR_V2_RUN_STAGE=1")
    print(f"STAGE_ID={spec.stage_id}")
    print(f"RUN_ID={run_id}")
    print(f"STEP_02_DOC_COUNT={len(invocations)}")

    no_self_chain = getattr(args, "no_self_chain", False)
    if no_self_chain:
        # --no-self-chain is a deliberate per-invocation override (see its argparse help text) -
        # loud on purpose: this run WILL stay stuck at status="running" in RUN_STATE.json until
        # a human runs `python scripts/advance_run.py <run_id> <stage_id>` by hand. Confirmed
        # (2026-07-15 investigation) that a stalled step_02_pdf_ingest run is caused by exactly
        # this flag, never by a document-count-dependent bug in the is_last check below.
        print(
            f"SELF_CHAIN_SUPPRESSED=1 stage_id={spec.stage_id} run_id={run_id} - no document's "
            f"job (including the last) will carry the advance_run.py trailer; manually run "
            f"'python scripts/advance_run.py {run_id} {spec.stage_id}' once all {len(invocations)} "
            f"jobs finish, or this run stays stuck."
        )

    slurm_script_paths: list[str] = []
    for i, inv in enumerate(invocations):
        # Only the LAST document's job should trigger the chain-advance trailer: step_02 as a
        # WHOLE stage isn't done until every document has merged into ACTIVE_STEP2_SET.txt (see
        # _prepare_step_02_invocations' docstring) - triggering advance_run.py after an
        # intermediate document's job would prematurely treat step_02 as complete and submit
        # step_03 before the later documents even exist yet.
        is_last = i == len(invocations) - 1
        extra_commands = (
            _chain_advance_extra_commands(run_id=run_id, stage_id=spec.stage_id)
            if (is_last and not no_self_chain)
            else ()
        )
        slurm_text = slurm_render.render_cpu_job(
            job_name=f"kc_{spec.stage_id}_{inv['doc_id']}",
            run_id=run_id,
            repo_root=str(repo_root),
            python_bin=HPC_PYTHON_BIN,
            script_path=inv["script_path"],
            script_args=inv["script_args"],
            log_dir=str(run_dir),
            # Routes Step 2 to GPU for MinerU specifically (Docling reverted to explicit CPU -
            # docling_cli's venv is torch 2.11.0+cu130, but this cluster's driver only supports
            # CUDA 12.4, so torch.cuda.is_available() is False there; Docling's own
            # decide_device() silently falls back to cpu on unavailable CUDA, so device: "cuda"
            # was never actually routing to GPU - see step2.hpc.actual_corpus.yaml).
            #
            # partition/gres match the CONFIRMED-GOOD historical GPU launcher
            # (run_step3_6_actual_corpus_gpu.slurm: gpu80GB/gpu:a100:1, real GPU MinerU output,
            # returncode 0 across 18 attempts) rather than gpu46GB/gpu:a40:1, which stalled
            # MinerU twice under the orchestrator's own sbatch path (jobs 227591, 227869 - both
            # stuck at 0% GPU util at the exact point where the confirmed-working step_03_6
            # config and a direct interactive srun invocation both sailed through in ~1 second).
            # No code-level cause was found for that stall; matching the one combination proven
            # to work end-to-end in this repo is the next cheapest experiment before assuming
            # it's unfixable. time_limit extended to 12:00:00 (from 04:00:00) to match
            # run_step3_6_actual_corpus_gpu.slurm - chunked MinerU processing of a 1120-page
            # document needs more wall time than a single whole-document call.
            partition="gpu80GB",
            gres="gpu:a100:1",
            time_limit="12:00:00",
            extra_env={"MINERU_DEVICE_MODE": "cuda"},
            # nvidia-smi diagnostic before the main command, matching
            # run_step3_6_actual_corpus_gpu.slurm's own `nvidia-smi || true` placement.
            pre_commands=["nvidia-smi || true", ""],
            extra_commands=extra_commands,
        )
        slurm_script_path = run_dir / f"{spec.stage_id}_{inv['doc_id']}.slurm"
        slurm_script_path.write_text(slurm_text, encoding="utf-8", newline="\n")
        slurm_script_paths.append(str(slurm_script_path))
        print(f"SLURM_SCRIPT\t{inv['doc_id']}\t{slurm_script_path}")
        if args.dry_run:
            print(f"----- rendered SLURM script ({inv['doc_id']}) -----")
            print(slurm_text)

    if args.dry_run:
        print("DRY_RUN=1")
        return 0

    job_ids: list[str] = []
    prev_job_id = args.dependency_job_id
    for script_path in slurm_script_paths:
        job_id = slurm_submit.sbatch_submit(script_path, dependency_job_id=prev_job_id)
        job_ids.append(job_id)
        prev_job_id = job_id

    run_state_mod.set_stage_submitted(
        state,
        spec.stage_id,
        job_id=job_ids[-1],
        slurm_script_path=slurm_script_paths[-1],
        job_ids=job_ids,
        slurm_script_paths=slurm_script_paths,
    )
    run_state_mod.write_run_state(state_path, state)

    print(f"JOB_IDS={','.join(job_ids)}")
    print(f"JOB_ID={job_ids[-1]}")
    return 0


def run_stage(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    stage_id = args.stage_id
    run_id = args.run_id

    try:
        spec = get_stage(stage_id)
    except KeyError as exc:
        print(f"ERROR_UNKNOWN_STAGE_ID={stage_id}")
        print(f"ERROR={exc}")
        return 2

    if not is_confirmed(stage_id):
        print(f"ERROR_STAGE_NOT_CONFIRMED={stage_id}")
        print(f"NOTES={spec.notes}")
        return 2

    layout = get_operator_layout(repo_root)
    run_dir = layout.pipeline_runs_root / run_id / stage_id
    run_dir.mkdir(parents=True, exist_ok=True)

    state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, run_id)
    state = run_state_mod.load_run_state(state_path) if state_path.exists() else run_state_mod.new_run_state(run_id)

    if stage_id == "step_02_pdf_ingest":
        return _run_step_02_stage(
            args, spec, repo_root=repo_root, run_id=run_id, run_dir=run_dir, state=state, state_path=state_path
        )

    try:
        invocation = _prepare_stage_invocation(spec, run_id=run_id, repo_root=repo_root, run_dir=run_dir, state=state)
    except StageNotWiredError as exc:
        print(f"ERROR_STAGE_NOT_WIRED={stage_id}")
        print(f"ERROR={exc}")
        return 3

    no_self_chain = getattr(args, "no_self_chain", False)
    if no_self_chain:
        # See the matching SELF_CHAIN_SUPPRESSED note in _run_step_02_stage() above - same
        # deliberate-override, loud-by-design reasoning applies here for every other stage.
        print(
            f"SELF_CHAIN_SUPPRESSED=1 stage_id={stage_id} run_id={run_id} - this job will not "
            f"carry the advance_run.py trailer; manually run 'python scripts/advance_run.py "
            f"{run_id} {stage_id}' once it finishes, or this run stays stuck."
        )
    extra_commands = list(invocation.get("extra_commands", ()))
    if not no_self_chain:
        extra_commands += _chain_advance_extra_commands(run_id=run_id, stage_id=stage_id)

    log_dir = str(run_dir)
    if invocation["needs_ollama"]:
        ollama_model_name = str((invocation.get("ollama_params") or {}).get("model") or "")
        if not ollama_model_name:
            print(f"ERROR_STAGE_NOT_WIRED={stage_id}")
            print(f"ERROR={stage_id}: needs_ollama=True but no model in ollama_params - "
                  "cannot select an Ollama runtime profile without knowing which model this "
                  "stage will run.")
            return 3
        resolved_ollama_bin, resolved_runtime_env_path, _resolved_ctx = _resolve_ollama_runtime(
            repo_root, ollama_model_name
        )
        slurm_text = slurm_render.render_ollama_job(
            job_name=f"kc_{stage_id}",
            run_id=run_id,
            repo_root=str(repo_root),
            python_bin=HPC_PYTHON_BIN,
            script_path=invocation["script_path"],
            script_args=invocation["script_args"],
            log_dir=log_dir,
            # Resolved per-model (see _resolve_ollama_runtime docstring for the 245988/245989
            # incident this fixes) - no longer an unconditional HPC_OLLAMA_BIN regardless of
            # which model this stage actually runs. KC_L_ABLATION_OLLAMA_BIN, if set, still
            # wins, same as before.
            ollama_bin=resolved_ollama_bin,
            ollama_models_dir=HPC_OLLAMA_MODELS_DIR,
            runtime_env_path=resolved_runtime_env_path,
            extra_commands=extra_commands,
            **(invocation["ollama_params"] or {}),
        )
    else:
        # partition/gres/time_limit are optional per-invocation overrides (currently only
        # step_03_6_math_salvage returns them, for its confirmed real GPU requirement - see
        # that branch's own comment above) - absent for every other stage, so render_cpu_job()
        # falls back to its own existing defaults ("big"/None/"04:00:00") and every other
        # rendered script stays byte-identical to before.
        cpu_job_kwargs: dict[str, Any] = {}
        if "partition" in invocation:
            cpu_job_kwargs["partition"] = invocation["partition"]
        if "gres" in invocation:
            cpu_job_kwargs["gres"] = invocation["gres"]
        if "time_limit" in invocation:
            cpu_job_kwargs["time_limit"] = invocation["time_limit"]

        slurm_text = slurm_render.render_cpu_job(
            job_name=f"kc_{stage_id}",
            run_id=run_id,
            repo_root=str(repo_root),
            python_bin=HPC_PYTHON_BIN,
            script_path=invocation["script_path"],
            script_args=invocation["script_args"],
            log_dir=log_dir,
            extra_commands=extra_commands,
            **cpu_job_kwargs,
        )

    slurm_script_path = run_dir / f"{stage_id}.slurm"
    slurm_script_path.write_text(slurm_text, encoding="utf-8", newline="\n")

    print("KC_L_ORCHESTRATOR_V2_RUN_STAGE=1")
    print(f"STAGE_ID={stage_id}")
    print(f"RUN_ID={run_id}")
    print(f"SLURM_SCRIPT={slurm_script_path}")

    if args.dry_run:
        print("DRY_RUN=1")
        print("----- rendered SLURM script -----")
        print(slurm_text)
        return 0

    job_id = slurm_submit.sbatch_submit(slurm_script_path, dependency_job_id=args.dependency_job_id)
    run_state_mod.set_stage_submitted(state, stage_id, job_id=job_id, slurm_script_path=str(slurm_script_path))
    run_state_mod.write_run_state(state_path, state)

    print(f"JOB_ID={job_id}")
    return 0


def plan(args: argparse.Namespace) -> int:
    from_id = args.from_stage
    to_id = args.to_stage

    ordered = ordered_stage_ids()
    if from_id not in ordered or to_id not in ordered:
        print(f"ERROR_UNKNOWN_STAGE_ID={from_id if from_id not in ordered else to_id}")
        return 2
    from_order = STAGE_SPECS[from_id].order
    to_order = STAGE_SPECS[to_id].order
    if from_order > to_order:
        print("ERROR_FROM_AFTER_TO=1")
        return 2

    chain = [sid for sid in ordered if from_order <= STAGE_SPECS[sid].order <= to_order]

    print("KC_L_ORCHESTRATOR_V2_PLAN=1")
    print(f"RUN_ID={args.run_id}")
    print(f"FROM={from_id}")
    print(f"TO={to_id}")
    print(f"STAGE_COUNT={len(chain)}")
    for sid in chain:
        wired = STAGE_SPECS[sid].run_stage_wired
        confirmed = is_confirmed(sid)
        print(f"STAGE\t{STAGE_SPECS[sid].order}\t{sid}\tconfirmed={int(confirmed)}\twired={int(wired)}")

    if args.dry_run:
        print("DRY_RUN=1")
        return 0

    prev_job_id: str | None = None
    for sid in chain:
        if not STAGE_SPECS[sid].run_stage_wired:
            print(f"ERROR_STAGE_NOT_WIRED={sid}")
            print("STOPPING_CHAIN_HERE=1")
            return 3
        stage_args = argparse.Namespace(
            repo_root=args.repo_root,
            stage_id=sid,
            run_id=args.run_id,
            dry_run=False,
            dependency_job_id=prev_job_id,
            # plan() already explicitly sequences this exact stage range via --dependency=
            # afterok chaining - the automatic self-chaining trailer (run_stage()'s default,
            # meant for the request-queue/advance_run.py flow) would otherwise try to ALSO
            # submit each next-ready stage once its predecessor's job finishes, double-
            # submitting stages plan() is already explicitly managing.
            no_self_chain=True,
        )
        rc = run_stage(stage_args)
        if rc != 0:
            print(f"ERROR_SUBMITTING_STAGE={sid}")
            return rc
        layout = get_operator_layout(Path(args.repo_root).resolve())
        state_path = run_state_mod.run_state_path(layout.pipeline_runs_root, args.run_id)
        state = run_state_mod.load_run_state(state_path)
        prev_job_id = run_state_mod.get_stage_entry(state, sid)["job_id"]

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KC_L v2 orchestrator v2")
    parser.add_argument("--repo-root", default=str(repo_root_from_this_file()))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.set_defaults(func=status)

    p = sub.add_parser("graph")
    p.set_defaults(func=graph)

    p = sub.add_parser("pointers-validate")
    p.set_defaults(func=pointers_validate)

    p = sub.add_parser("surfaces-classify")
    p.set_defaults(func=surfaces_classify)

    p = sub.add_parser("validate-to")
    p.add_argument("stage_id")
    p.set_defaults(func=validate_to)

    p = sub.add_parser("step68-smoke")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=step68_smoke)

    p = sub.add_parser("quarantine-plan")
    p.add_argument("--scope", default="legacy-processed")
    p.add_argument("--out", required=True)
    p.set_defaults(func=quarantine_plan)

    p = sub.add_parser("quarantine-apply-mirror")
    p.add_argument("--plan", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--restore-script", required=True)
    p.set_defaults(func=quarantine_apply_mirror)

    p = sub.add_parser("run-stage")
    p.add_argument("stage_id")
    p.add_argument("--run-id", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dependency-job-id", default=None)
    p.add_argument(
        "--no-self-chain",
        action="store_true",
        help="Do not append the advance_run.py trailer to the rendered SLURM script - run "
        "only this one stage, matching run-stage's pre-Milestone-4 behavior. Self-chaining is "
        "on by default (Milestone 4): a successful stage automatically resolves and submits "
        "whatever's next-ready in the dependency graph.",
    )
    p.set_defaults(func=run_stage)

    p = sub.add_parser("plan")
    p.add_argument("--from", dest="from_stage", required=True)
    p.add_argument("--to", dest="to_stage", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
