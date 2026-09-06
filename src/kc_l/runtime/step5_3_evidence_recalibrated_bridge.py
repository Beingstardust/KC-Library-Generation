from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from kc_l.runtime.stage_config import load_stage_config, render_stage_config
from kc_l.utils.json_io import read_json

BASE_CONFIG_PATH = Path("steps/step_05_3_evidence_recalibrated/resources/step5_3.hpc.actual_corpus.yaml")


def _find_single_file(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one file matching {pattern!r} in {directory}, found {len(matches)}: {matches}"
        )
    return matches[0]


def resolve_hierarchy_normalize_output_root(*, repo_root: Path, run_id: str) -> Path:
    """Step 01's own normalized-registry output root - repo_root/data/processed/hierarchy/
    <run_id> - NOT the same as the hierarchy_registry StageSpec's own recorded output_root
    (data/processed/hierarchy_overlay/<run_id>, Step 01.5's overlay output). Both scripts run
    within the same hierarchy_registry SLURM job (see kc_l_orchestrator.py's own
    normalize_output_root computation in that stage's _prepare_stage_invocation branch - this
    mirrors that exact literal path construction, confirmed 2026-07-16), but Step 01's
    intermediate kc_registry.jsonl/hierarchy_manifest.json only exist under this separate root.
    """
    return repo_root / "data/processed/hierarchy" / run_id


def resolve_hierarchy_manifest_from_output_root(*, hierarchy_normalize_output_root: Path) -> dict[str, Any]:
    """Step 01 nests its real output one level deeper under its own internally generated
    timestamp run_id (same pattern already documented for step_04_5/step_06_6/etc.) - glob for
    the single hierarchy_manifest.json rather than assuming it's flat.

    hierarchy_manifest.json's own "registry_path"/"num_kcs" fields are the authoritative source
    for this run's real KC registry JSONL path and real KC count - confirmed by direct read
    against real on-disk output, 2026-07-15/16 investigation.
    """
    manifest_path = hierarchy_normalize_output_root / "hierarchy_manifest.json"
    if not manifest_path.exists():
        manifest_path = _find_single_file(hierarchy_normalize_output_root, "*/hierarchy_manifest.json")
    return read_json(manifest_path)


def compute_step5x_gap_kc_ids(*, step5x_pack_jsonl: Path, repo_root: Path) -> list[str]:
    """The KC_IDs for which step_05x_kc_evidence_stage_v3's own embedded pack (ordered_pack_for_
    drafting, else the same filtered review_needed_evidence step_06_7's real packet builder
    trusts) produces zero usable synthesis evidence - i.e. the only KCs step_05_3's deterministic
    fallback can possibly matter for, since step_06_7's build_kc_packet() always tries the
    embedded step_05x pack FIRST and only ever consults step_05_3-sourced overlay candidates
    when that comes back empty (see build_step67_v2_hierarchy_aware_synthesis_packets.py's
    build_kc_packet - a hard if/else, not a scoring comparison, so step_05_3 can never override
    step_05x's own evidence when step_05x has any).

    Reuses the real selection function directly (rather than re-deriving an equivalent check
    here, which would silently drift out of sync the next time that function's admission logic
    changes) - imported via sys.path since it lives under steps/, not src/kc_l/.

    Confirmed (2026-07-26, run 20260725T225807Z_9e856df6): of 159 real KC rows, only 39 came
    back with zero usable evidence from step_05x alone - step_05_3 was previously being run
    unconditionally over the full registry every time, discarding ~75% of its own compute on
    KCs whose output could structurally never be looked at.
    """
    v2_chain_dir = repo_root / "steps/step_06_7_kc_draft_generation/scripts/v2_chain"
    if str(v2_chain_dir) not in sys.path:
        sys.path.insert(0, str(v2_chain_dir))
    import build_step67_v2_hierarchy_aware_synthesis_packets as packet_builder  # noqa: PLC0415

    gap_kc_ids: list[str] = []
    with step5x_pack_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kc_id = row.get("kc_id")
            if not kc_id:
                continue
            selected = packet_builder.select_kc_synthesis_evidence_from_embedded_pack(
                [row], evidence_limit=18, text_max_chars=2200,
            )
            if not selected:
                gap_kc_ids.append(str(kc_id))
    return gap_kc_ids


def write_scoped_kc_registry(
    *, full_registry_path: Path, gap_kc_ids: list[str], out_path: Path,
) -> int:
    """Write only the gap_kc_ids' own rows from the full KC registry to out_path - never
    modifies or deletes the full registry. Returns the row count actually written (may be less
    than len(gap_kc_ids) if a gap KC is somehow absent from the registry - callers should treat
    that mismatch as worth investigating, not silently ignore it)."""
    gap_set = set(gap_kc_ids)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with full_registry_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("kc_id") in gap_set:
                fout.write(line + "\n")
                written += 1
    return written


def build_step5_3_run_config(
    *,
    run_id: str,
    repo_root: Path,
    run_dir: Path,
    hierarchy_normalize_output_root: Path,
    sentence_overlay_output_root: Path,
    step5x_pack_jsonl: Path | None = None,
    base_config_path: Path | None = None,
) -> Path:
    """Render a per-run Step 5.3 (kc_evidence_recalibrated) config from current-run upstream
    artifacts.

    base_config_path (2026-07-30, ablation studies): optional override for the base YAML this
    run's config is rendered from - defaults to BASE_CONFIG_PATH (the production config) when
    omitted, so every existing caller and the production baseline stay byte-identical. Lets a
    diagnostic/ablation run (e.g. reranker weights/thresholds neutralized) supply its own
    standalone base YAML without touching BASE_CONFIG_PATH or any shared production file.

    2026-07-15/16 fix: step_05_3_evidence_recalibrated was never wired into run-stage at all -
    step_06_6_drafting_input_overlay's step5_3_active_set_pointer input always fell through to
    the base YAML's own default, a single shared ACTIVE_STEP5_3_EVIDENCE_SET.txt pointer last
    written 2026-04-26 (this stage was never re-run since). Its acceptance.n_kcs_total was also
    hardcoded to 144, hard-matching only that historical run's KC count - any run whose real
    hierarchy has a different KC count (this run: 159) hard-fails immediately
    (RuntimeError: "Expected N registry rows, found M"). Both kc_registry_path and
    acceptance.n_kcs_total are re-derived here from THIS run's own real hierarchy_registry
    output; step4_5_active_set_pointer is re-derived from THIS run's own real
    step_04_5_sentence_overlay output. Everything else (models.reranker, scoring/selection/
    runtime blocks, baseline_step5_2_active_set_pointer - a comparison-only input, not
    load-bearing for output correctness) is left as the base YAML's own default.

    2026-07-26 fix: step_05_3's output can structurally only ever be looked at for a KC whose
    step_05x embedded pack came back empty (see compute_step5x_gap_kc_ids' own docstring) -
    running it unconditionally over the full registry wastes the large majority of its own
    compute on KCs whose output is guaranteed to be discarded. When step5x_pack_jsonl is
    provided (the caller has step_05x_kc_evidence_stage_v3's own completed output available -
    it is step_05_3's own sibling dependency in the stage graph, always available by the time
    step_05_3 becomes ready), scope kc_registry_path/acceptance.n_kcs_total down to just the
    real gap KCs instead of the full registry. Falls back to the full, unscoped registry
    (previous behavior, unchanged) whenever step5x_pack_jsonl is not provided, so this stays
    backward compatible for any caller that hasn't been updated to pass it yet.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    resolved_base_config_path = (
        repo_root / base_config_path if base_config_path is not None else repo_root / BASE_CONFIG_PATH
    )

    hierarchy_manifest = resolve_hierarchy_manifest_from_output_root(
        hierarchy_normalize_output_root=hierarchy_normalize_output_root
    )
    kc_registry_path = Path(hierarchy_manifest["registry_path"])
    full_kc_registry_path_for_provenance: Path | None = None
    n_kcs_total = int(hierarchy_manifest["num_kcs"])
    acceptance_overrides: dict[str, Any] = {"n_kcs_total": n_kcs_total}

    if step5x_pack_jsonl is not None and step5x_pack_jsonl.exists():
        gap_kc_ids = compute_step5x_gap_kc_ids(step5x_pack_jsonl=step5x_pack_jsonl, repo_root=repo_root)
        if gap_kc_ids:
            scoped_registry_path = run_dir / f"{run_id}_step_05_3_scoped_kc_registry.jsonl"
            written = write_scoped_kc_registry(
                full_registry_path=kc_registry_path, gap_kc_ids=gap_kc_ids, out_path=scoped_registry_path,
            )
            # 2026-07-26 fix: keep the ORIGINAL full registry path (before this reassignment)
            # so it can still be recorded as this stage's own upstream.kc_registry_path
            # provenance - see run_step5_3.py's full_kc_registry_path_for_provenance for why
            # (downstream consumers trust that field as "the real, full registry").
            full_kc_registry_path_for_provenance = kc_registry_path
            kc_registry_path = scoped_registry_path
            n_kcs_total = written
            acceptance_overrides["n_kcs_total"] = n_kcs_total
            # 2026-07-26 fix, confirmed real incident (run 20260725T225807Z_9e856df6, job
            # 234787): the base config's acceptance.min_kcs_with_2_strong_candidates (100) is an
            # ABSOLUTE count calibrated against the FULL, unscoped registry (144 in that config)
            # - scoping kc_registry_path down to just the gap KCs without also scaling this
            # threshold makes acceptance mathematically impossible to pass for any scoped subset
            # smaller than the threshold itself (e.g. 31 strong candidates out of 39 scoped KCs
            # - a genuinely GOOD 79% rate, well above the base config's own ~69% (100/144) ratio
            # - still hard-failed against the unscaled absolute 100). Re-derive the threshold as
            # the base config's own ratio applied to the real scoped count, not a fixed number,
            # so this stays meaningful (and still genuinely protective) regardless of how many
            # KCs end up in the scoped registry for any future run.
            base_config = load_stage_config(resolved_base_config_path)
            base_acceptance = dict(base_config.get("acceptance") or {})
            base_n_kcs_total = int(base_acceptance.get("n_kcs_total") or 0)
            base_min_strong = int(base_acceptance.get("min_kcs_with_2_strong_candidates") or 0)
            if base_n_kcs_total > 0 and base_min_strong > 0:
                ratio = base_min_strong / base_n_kcs_total
                acceptance_overrides["min_kcs_with_2_strong_candidates"] = max(1, round(ratio * n_kcs_total))

    step4_5_pointer = sentence_overlay_output_root / "_sets" / "ACTIVE_STEP4_5_SET.txt"

    inputs_overrides: dict[str, Any] = {
        "kc_registry_path": str(kc_registry_path),
        "step4_5_active_set_pointer": str(step4_5_pointer),
    }
    if full_kc_registry_path_for_provenance is not None:
        inputs_overrides["full_kc_registry_path_for_provenance"] = str(full_kc_registry_path_for_provenance)

    overrides = {
        "inputs": inputs_overrides,
        "acceptance": acceptance_overrides,
    }
    rendered_config_path = run_dir / f"{run_id}_step_05_3_config.json"
    render_stage_config(resolved_base_config_path, overrides, rendered_config_path)
    return rendered_config_path
