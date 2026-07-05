from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.retrieval_profile.builder import build_profiles, utc_stamp


DEFAULT_CONFIG = Path("steps/step_05_p_kc_retrieval_profile/resources/step5p.default.yaml")


def load_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping config root: {path}")
    return obj


def repo_path(spec: str | Path | None) -> Path | None:
    if spec is None:
        return None
    text = str(spec)
    if not text:
        return None
    p = Path(text)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def split_ids(values: List[str] | None) -> List[str]:
    out: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build source-grounded KC retrieval profiles.")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--registry-jsonl", type=str, default=None)
    p.add_argument("--source-overlay-jsonl", type=str, default=None)
    p.add_argument("--exact-kc-ids", nargs="*", default=None)
    p.add_argument("--limit-kcs", type=int, default=None)
    p.add_argument("--run-id", type=str, default=None)
    p.add_argument("--output-root", type=str, default=None)
    p.add_argument("--set-manifest-root", type=str, default=None)
    p.add_argument("--use-model", action="store_true")
    p.add_argument("--no-model", action="store_true")
    p.add_argument("--llm-policy", choices=["always", "edge", "never"], default=None)
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--base-url", type=str, default=None)
    p.add_argument("--max-snippets-per-kc", type=int, default=None)
    p.add_argument("--min-snippet-score", type=float, default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--checkpoint-every", type=int, default=None)
    p.add_argument("--base-profile-jsonl", type=str, default=None)
    p.add_argument("--feedback-gap-jsonl", type=str, default=None)
    p.add_argument("--feedback-round", type=int, default=0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg_path = repo_path(args.config)
    assert cfg_path is not None
    cfg = load_config(cfg_path)

    inputs = dict(cfg.get("inputs") or {})
    outputs = dict(cfg.get("outputs") or {})
    behavior = dict(cfg.get("behavior") or {})
    model_cfg = dict(cfg.get("model") or {})

    registry_jsonl = repo_path(args.registry_jsonl or inputs.get("registry_jsonl"))
    source_overlay_jsonl = repo_path(args.source_overlay_jsonl or inputs.get("source_overlay_jsonl"))

    if registry_jsonl is None:
        raise RuntimeError("Missing registry_jsonl. Pass --registry-jsonl or set inputs.registry_jsonl.")
    if source_overlay_jsonl is None:
        raise RuntimeError("Missing source_overlay_jsonl. Pass --source-overlay-jsonl or set inputs.source_overlay_jsonl.")

    exact_kc_ids = split_ids(args.exact_kc_ids)
    if not exact_kc_ids:
        exact_kc_ids = split_ids(inputs.get("exact_kc_ids") or [])

    use_model = bool(behavior.get("use_model", False))
    llm_policy = behavior.get("llm_policy")
    if args.use_model:
        use_model = True
        llm_policy = "always"
    if args.no_model:
        use_model = False
        llm_policy = "never"
    if args.llm_policy:
        llm_policy = args.llm_policy

    if args.model:
        model_cfg["model"] = args.model
    if args.base_url:
        model_cfg["base_url"] = args.base_url

    output_root = repo_path(args.output_root or outputs.get("output_root") or "data/processed/kc_retrieval_profiles")
    set_manifest_root = repo_path(args.set_manifest_root or outputs.get("set_manifest_root") or "data/processed/kc_retrieval_profiles/_sets")
    assert output_root is not None
    assert set_manifest_root is not None

    result = build_profiles(
        registry_jsonl=registry_jsonl,
        source_overlay_jsonl=source_overlay_jsonl,
        output_root=output_root,
        set_manifest_root=set_manifest_root,
        run_id=args.run_id or f"step5p_{utc_stamp()}",
        exact_kc_ids=exact_kc_ids,
        limit_kcs=args.limit_kcs if args.limit_kcs is not None else inputs.get("limit_kcs"),
        max_snippets_per_kc=args.max_snippets_per_kc if args.max_snippets_per_kc is not None else int(behavior.get("max_snippets_per_kc", 12)),
        min_snippet_score=args.min_snippet_score if args.min_snippet_score is not None else float(behavior.get("min_snippet_score", 4.0)),
        use_model=use_model,
        llm_policy=llm_policy,
        model_config=model_cfg,
        dynamic_broad_token_min_df=int(behavior.get("dynamic_broad_token_min_df", 12)),
        resume=bool(args.resume or behavior.get("resume", False)),
        checkpoint_every=args.checkpoint_every if args.checkpoint_every is not None else int(behavior.get("checkpoint_every", 1)),
        base_profile_jsonl=repo_path(args.base_profile_jsonl or inputs.get("base_profile_jsonl")),
        feedback_gap_jsonl=repo_path(args.feedback_gap_jsonl or inputs.get("feedback_gap_jsonl")),
        feedback_round=int(args.feedback_round or behavior.get("feedback_round", 0) or 0),
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
