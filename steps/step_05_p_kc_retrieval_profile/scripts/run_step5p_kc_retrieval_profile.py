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


def _normalize_ollama_base_url(host_or_url: str) -> str:
    text = str(host_or_url or "").strip()
    if not text:
        raise RuntimeError("Empty Ollama host/base URL.")
    if text.startswith(("http://", "https://")):
        return text.rstrip("/")
    return f"http://{text}"


def validate_config(cfg: Dict[str, Any], *, config_path: Path) -> None:
    """Minimal runtime schema validation for Step 5p configs.

    This stage historically accepted any mapping-shaped YAML. Keep the validator intentionally
    narrow: assert the expected top-level sections exist and that the new model.context_length
    field, when present, is a positive integer.
    """
    for key in ("inputs", "outputs", "behavior", "model"):
        value = cfg.get(key)
        if not isinstance(value, dict):
            raise RuntimeError(f"Step 5p config {config_path} must define a mapping at {key!r}.")

    model_cfg = dict(cfg.get("model") or {})
    context_length = model_cfg.get("context_length")
    if context_length is not None and int(context_length) <= 0:
        raise RuntimeError(
            f"Step 5p config {config_path} has invalid model.context_length={context_length!r}; "
            "expected a positive integer."
        )


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
    p.add_argument("--ollama-host", type=str, default=None)
    p.add_argument("--max-snippets-per-kc", type=int, default=None)
    p.add_argument("--min-snippet-score", type=float, default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--checkpoint-every", type=int, default=None)
    p.add_argument("--base-profile-jsonl", type=str, default=None)
    p.add_argument("--feedback-gap-jsonl", type=str, default=None)
    p.add_argument("--feedback-round", type=int, default=0)
    p.add_argument("--embedding-index-root", type=str, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg_path = repo_path(args.config)
    assert cfg_path is not None
    cfg = load_config(cfg_path)
    validate_config(cfg, config_path=cfg_path)

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
    if args.ollama_host:
        model_cfg["base_url"] = _normalize_ollama_base_url(args.ollama_host)

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
        # Phase 3.5 rank #15 / audit codebase-audit-20260805 item 16. Of the three code-level
        # fallback defaults below (only used if a config omits the key - real run configs always
        # set these explicitly, so these are not "silent" in production, just undocumented as
        # fallbacks):
        # - max_snippets_per_kc=12: this specific number is stale/pre-calibration. The real
        #   production config (steps/step_05_p_kc_retrieval_profile/resources/
        #   step5p.hpc.production_gemma4_31b.yaml) sets 20, empirically grounded in commit
        #   672b0ae (2026-07-27, "Add embedding-assisted evidence reranking, raise candidate
        #   ceiling, calibrate truncation length"): "grounded in measured near-miss counts (8-23
        #   per KC) after tie-breaking alone proved insufficient to relieve ceiling pressure."
        #   Investigated as part of this audit: unlike the six role-score thresholds fallback
        #   staleness fixed in scored_candidates.py (item 6), this fallback's staleness is lower
        #   risk since it only relaxes a ceiling (never causes new admission of bad evidence) if
        #   ever exercised - documented here rather than silently left, but not changed, since the
        #   real production config already carries the calibrated value and there is no
        #   evidence-corruption risk from the code-level fallback lagging.
        # - min_snippet_score=4.0 and dynamic_broad_token_min_df=12: match the real production
        #   config's values exactly (no drift), but neither has a dedicated calibration record
        #   the way max_snippets_per_kc does. Documented as accepted, reasoned defaults per the
        #   audit's own explicit fallback - no confirmed bug tied to either.
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
        embedding_index_root=repo_path(args.embedding_index_root or inputs.get("embedding_index_root")),
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
