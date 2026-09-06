from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SET_MANIFEST_ROOT,
    resolve_repo_path,
    run_candidate_bank_stage,
)


DEFAULT_CONFIG = Path("steps/step_05_x_evidence_stage_v3/resources/step5x_v3_candidate_bank.default.yaml")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml_or_json(path: Path) -> Dict[str, Any]:
    text = read_text(path)
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping at config root: {path}")
    return obj


def _split_exact_kc_ids(values: Optional[List[str]]) -> List[str]:
    output: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                output.append(part)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Step 5x v3 candidate bank from either legacy Step 5.3 inputs "
            "or clean-slate registry + sentence-overlay inputs."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--step5-3-set-manifest", dest="step5_3_set_manifest", type=str, default=None)
    parser.add_argument("--step5-3-candidates-jsonl", dest="step5_3_candidates_jsonl", type=str, default=None)
    parser.add_argument("--registry-jsonl", dest="registry_jsonl", type=str, default=None)
    parser.add_argument("--source-overlay-jsonl", dest="source_overlay_jsonl", type=str, default=None)
    parser.add_argument("--profile-jsonl", dest="profile_jsonl", type=str, default=None)
    parser.add_argument("--exact-kc-ids", nargs="*", default=None)
    parser.add_argument("--limit-kcs", type=int, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--set-manifest-root", type=Path, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--allow-seed-bearing-input-for-diagnostic", action="store_true")
    parser.add_argument("--enable-source-surface-fallback", action="store_true")
    parser.add_argument("--disable-source-surface-fallback", action="store_true")
    parser.add_argument("--max-fallback-per-kc", type=int, default=None)
    parser.add_argument("--fallback-min-score", type=float, default=None)
    parser.add_argument("--direct-overlay-supplement-jsonl", dest="direct_overlay_supplement_jsonl", type=str, default=None)
    parser.add_argument("--enable-direct-overlay-supplement", action="store_true")
    parser.add_argument("--disable-direct-overlay-supplement", action="store_true")
    parser.add_argument("--max-direct-overlay-per-kc", type=int, default=None)
    parser.add_argument("--direct-overlay-min-score", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config, repo_root=REPO_ROOT)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    behavior_cfg = dict(cfg.get("behavior") or {})
    fallback_cfg = dict(cfg.get("source_surface_fallback") or {})
    direct_overlay_cfg = dict(cfg.get("direct_overlay_supplement") or {})

    if args.enable_source_surface_fallback:
        fallback_cfg["enabled"] = True
    if args.disable_source_surface_fallback:
        fallback_cfg["enabled"] = False
    if args.max_fallback_per_kc is not None:
        fallback_cfg["max_fallback_per_kc"] = args.max_fallback_per_kc
    if args.fallback_min_score is not None:
        fallback_cfg["min_score"] = args.fallback_min_score
    if args.enable_direct_overlay_supplement:
        direct_overlay_cfg["enabled"] = True
    if args.disable_direct_overlay_supplement:
        direct_overlay_cfg["enabled"] = False
    if args.direct_overlay_supplement_jsonl:
        direct_overlay_cfg["supplement_jsonl"] = args.direct_overlay_supplement_jsonl
        direct_overlay_cfg["enabled"] = True
    if args.max_direct_overlay_per_kc is not None:
        direct_overlay_cfg["max_candidates_per_kc"] = args.max_direct_overlay_per_kc
    if args.direct_overlay_min_score is not None:
        direct_overlay_cfg["min_score"] = args.direct_overlay_min_score

    exact_kc_ids = _split_exact_kc_ids(args.exact_kc_ids)
    if not exact_kc_ids:
        exact_kc_ids = _split_exact_kc_ids(input_cfg.get("exact_kc_ids"))

    result = run_candidate_bank_stage(
        run_id=args.run_id,
        step5_3_set_manifest_spec=args.step5_3_set_manifest or input_cfg.get("step5_3_set_manifest") or None,
        step5_3_candidates_jsonl_spec=args.step5_3_candidates_jsonl or input_cfg.get("step5_3_candidates_jsonl") or None,
        registry_jsonl_spec=args.registry_jsonl or input_cfg.get("registry_jsonl") or None,
        source_overlay_jsonl_spec=args.source_overlay_jsonl or input_cfg.get("source_overlay_jsonl") or None,
        config_path=config_path.as_posix(),
        exact_kc_ids=exact_kc_ids,
        limit_kcs=args.limit_kcs if args.limit_kcs is not None else input_cfg.get("limit_kcs"),
        output_root=resolve_repo_path(args.output_root or output_cfg.get("output_root") or DEFAULT_OUTPUT_ROOT, repo_root=REPO_ROOT),
        set_manifest_root=resolve_repo_path(args.set_manifest_root or output_cfg.get("set_manifest_root") or DEFAULT_SET_MANIFEST_ROOT, repo_root=REPO_ROOT),
        allow_reference_artifact_inputs=bool(behavior_cfg.get("allow_reference_artifact_inputs", True)),
        fail_if_no_candidate_source=bool(behavior_cfg.get("fail_if_no_candidate_source", True)),
        allow_seed_bearing_input_for_diagnostic=bool(
            args.allow_seed_bearing_input_for_diagnostic
            or behavior_cfg.get("allow_seed_bearing_input_for_diagnostic", False)
        ),
        exclude_seed_fields=bool(behavior_cfg.get("exclude_seed_fields", True)),
        preserve_raw_support_profile=bool(behavior_cfg.get("preserve_raw_support_profile", True)),
        preserve_raw_alignment_breakdown=bool(behavior_cfg.get("preserve_raw_alignment_breakdown", True)),
        profile_jsonl_spec=args.profile_jsonl or input_cfg.get("profile_jsonl") or None,
        source_surface_fallback_cfg=fallback_cfg,
        direct_overlay_supplement_cfg=direct_overlay_cfg,
        repo_root=REPO_ROOT,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
