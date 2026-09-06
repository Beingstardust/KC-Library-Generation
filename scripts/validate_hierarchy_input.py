#!/usr/bin/env python3
"""Validate a candidate hierarchy JSON before submitting it through the console.

Reuses the exact real contract 01_hierarchy_normalize.py itself applies (kc_l.hierarchy.loader/
validators) - not a reimplementation - so a "PASS" here means the real pipeline stage will also
accept the file, and a "FAIL" names precisely which node(s) and which missing field(s) are the
problem, not a downstream symptom.

Contract (see ORCHESTRATOR_BUILD_STATE.md's hierarchy-ingestion-robustness entry): a node with
no "children" is a KC leaf, structurally - no "kc": true marker needed. Each leaf must carry a
KC identifier under one of: kc_id, id. A canonical/display name is satisfied either by the
node's own key in its parent's "children" object, or explicitly via one of: canonical_name,
name, label (only needed if the tree key itself isn't a good display name). seed_definition
("definition" field) and aliases are optional.

Usage: python scripts/validate_hierarchy_input.py --hierarchy path/to/hierarchy.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_SRC = _SCRIPTS_DIR.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from kc_l.hierarchy.loader import load_hierarchy_kcs  # noqa: E402
from kc_l.hierarchy.validators import has_errors, validate_kc_leaves  # noqa: E402
from kc_l.hierarchy.stats import compute_stats  # noqa: E402
from kc_l.utils.json_io import read_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hierarchy", required=True, type=Path, help="Path to the candidate hierarchy JSON.")
    args = ap.parse_args()

    hierarchy_path: Path = args.hierarchy
    if not hierarchy_path.exists():
        print(f"FAIL: hierarchy file not found: {hierarchy_path}")
        return 2

    try:
        tree = read_json(hierarchy_path)
    except Exception as exc:
        print(f"FAIL: could not parse {hierarchy_path} as JSON: {exc}")
        return 2

    try:
        kcs = load_hierarchy_kcs(tree)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2

    issues = validate_kc_leaves(kcs)
    stats = compute_stats(kcs, issues, source_set_id="validate_hierarchy_input_cli")

    print(f"Hierarchy: {hierarchy_path}")
    print(f"KC leaves found: {len(kcs)}")
    print(f"Issues: {len(issues)} ({sum(1 for i in issues if i.level == 'ERROR')} error, "
          f"{sum(1 for i in issues if i.level == 'WARN')} warning)")

    if len(kcs) == 0:
        print(
            "\nFAIL: zero KC leaves found. Every node with no \"children\" is treated as a KC "
            "leaf - if this hierarchy has real leaf nodes, check they are structured as a "
            "no-children object (not, for example, a list, or a further-nested empty "
            "\"children\": {} placeholder)."
        )
        return 1

    errors = [i for i in issues if i.level == "ERROR"]
    warnings = [i for i in issues if i.level == "WARN"]

    if errors:
        print("\nERRORS (must fix before this hierarchy will be accepted):")
        for issue in errors:
            path = " > ".join(issue.kc_path or [])
            kc_id_part = f" (kc_id={issue.kc_id})" if issue.kc_id else ""
            print(f"  - [{issue.code}] {issue.message}{kc_id_part}\n    at: {path}")

    if warnings:
        print("\nWarnings (won't block submission, but worth reviewing):")
        for issue in warnings:
            path = " > ".join(issue.kc_path or [])
            print(f"  - [{issue.code}] {issue.message}\n    at: {path}")

    if has_errors(issues):
        print(f"\nFAIL: {len(errors)} error(s) found above - fix these specific nodes/fields and re-run.")
        return 1

    print(f"\nPASS: {len(kcs)} KC leaves, {stats.get('num_issues', len(issues))} warning(s), no errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
