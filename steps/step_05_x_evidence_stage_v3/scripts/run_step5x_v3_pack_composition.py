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

from kc_l.retrieval_gate.evidence_stage_v3_candidate_bank import resolve_repo_path
from kc_l.runtime.current_step_artifacts import resolve_seedless_kc_registry_path
from kc_l.retrieval_gate.evidence_stage_v3_pack_composition import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SET_MANIFEST_ROOT,
    build_evidence_pack_artifacts,
    load_expected_kc_rows,
    load_scored_candidate_rows,
)

DEFAULT_CONFIG = Path("steps/step_05_x_evidence_stage_v3/resources/step5x_v3_pack_composition.default.yaml")


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
    parser = argparse.ArgumentParser(description="Compose Stage 3 v3 KC evidence packs from Stage 2 scored candidates.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--step5x-v3-scored-set-manifest", dest="stage2_set_manifest", type=str, default=None)
    parser.add_argument("--scored-candidates-jsonl", dest="scored_candidates_jsonl", type=str, default=None)
    parser.add_argument("--registry-jsonl", dest="registry_jsonl", type=str, default=None)
    parser.add_argument("--exact-kc-ids", nargs="*", default=None)
    parser.add_argument("--limit-kcs", type=int, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--set-manifest-root", type=Path, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config, repo_root=REPO_ROOT)
    cfg = load_yaml_or_json(config_path)

    input_cfg = dict(cfg.get("inputs") or {})
    output_cfg = dict(cfg.get("outputs") or {})
    exact_kc_ids = _split_exact_kc_ids(args.exact_kc_ids)
    if not exact_kc_ids:
        exact_kc_ids = _split_exact_kc_ids(input_cfg.get("exact_kc_ids"))
    limit_kcs = args.limit_kcs if args.limit_kcs is not None else input_cfg.get("limit_kcs")

    rows, input_info = load_scored_candidate_rows(
        stage2_set_manifest=args.stage2_set_manifest or input_cfg.get("step5x_v3_scored_set_manifest") or None,
        scored_candidates_jsonl=args.scored_candidates_jsonl or input_cfg.get("scored_candidates_jsonl") or None,
        exact_kc_ids=exact_kc_ids or None,
        limit_kcs=limit_kcs,
        repo_root=REPO_ROOT,
    )
    registry_jsonl_path = resolve_seedless_kc_registry_path(args.registry_jsonl or input_cfg.get("registry_jsonl") or None, repo_root=REPO_ROOT)
    expected_kc_rows, resolved_registry_jsonl = load_expected_kc_rows(
        registry_jsonl=registry_jsonl_path.as_posix(),
        exact_kc_ids=exact_kc_ids or None,
        limit_kcs=limit_kcs,
        repo_root=REPO_ROOT,
    )
    result = build_evidence_pack_artifacts(
        rows,
        run_id=str(args.run_id or ""),
        source_manifest=str(input_info.get("source_manifest") or ""),
        scored_candidates_jsonl_path=str(input_info.get("scored_candidates_jsonl") or ""),
        config_path=config_path.as_posix(),
        exact_kc_ids=exact_kc_ids or None,
        limit_kcs=limit_kcs,
        expected_kc_rows=expected_kc_rows,
        registry_jsonl_path=resolved_registry_jsonl,
        cfg=cfg,
        output_root=resolve_repo_path(args.output_root or output_cfg.get("output_root") or DEFAULT_OUTPUT_ROOT, repo_root=REPO_ROOT),
        set_manifest_root=resolve_repo_path(args.set_manifest_root or output_cfg.get("set_manifest_root") or DEFAULT_SET_MANIFEST_ROOT, repo_root=REPO_ROOT),
        repo_root=REPO_ROOT,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
