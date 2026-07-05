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

No third-party dependencies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
