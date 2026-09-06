from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - matches the fallback already used by step 6.9's runner
    yaml = None

from kc_l.utils.json_io import write_json


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        import json

        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected a mapping at config root: {path}")
    return obj


def load_stage_config(path: Path) -> dict[str, Any]:
    """Public loader for stage resource configs used outside this module."""
    return _load_yaml_or_json(path)


def _deep_merge(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def render_stage_config(
    base_config_path: Path,
    overrides: Mapping[str, Any],
    output_path: Path,
) -> Path:
    """Render a per-run stage config: load base_config_path, deep-merge overrides into it
    (e.g. {"inputs": {"step5_4_set_manifest": "..."}, "outputs": {"processed_root": "..."}}),
    write the result to output_path.

    Every generated config is written as JSON, not YAML - both step 6.9's load_yaml_or_json
    and this module's own loader accept JSON as valid YAML (a superset), and this avoids
    taking a hard dependency on PyYAML being importable for the *write* path (only the read
    path already tolerates its absence, matching the existing step 6.9 runner convention).
    """
    base = _load_yaml_or_json(base_config_path)
    merged = _deep_merge(base, overrides)
    write_json(output_path, merged)
    return output_path
