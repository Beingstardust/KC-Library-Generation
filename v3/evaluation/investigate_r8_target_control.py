"""Compare one independently validated target-binding control across frozen system arms."""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any, Mapping


def find_row(path: pathlib.Path, target: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if target not in line:
                continue
            row = json.loads(line)
            if str(row.get("canonical_name") or "") == target:
                return row
    raise ValueError("target %r not found in %s" % (target, path))


def contextual(row: Mapping[str, Any]) -> Mapping[str, Any]:
    draft = row.get("draft") or {}
    value = draft.get("contextual_kc_draft") or {} if isinstance(draft, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--system", action="append", nargs=3, metavar=("NAME", "PACKETS", "DRAFTS"),
        required=True, help="repeat for each matched frozen system arm")
    parser.add_argument("--out-json", type=pathlib.Path)
    args = parser.parse_args()

    systems = []
    for name, packet_path, draft_path in args.system:
        packet = find_row(pathlib.Path(packet_path), args.target)
        draft = find_row(pathlib.Path(draft_path), args.target)
        evidence = list(packet.get("evidence_for_synthesis") or [])
        body = str(contextual(draft).get("text") or "")
        systems.append({
            "system": name,
            "evidence_count": len(evidence),
            "evidence_characters": sum(len(str(item.get("text") or "")) for item in evidence),
            "packet_support_state": packet.get("packet_support_state"),
            "abstention_expected": packet.get("abstention_expected"),
            "draft_status": contextual(draft).get("status"),
            "draft_body": body,
            "produced_nonempty_supported_draft": bool(body.strip()),
            "runtime_error": draft.get("runtime_error"),
            "validation_issues": draft.get("validation_issues") or [],
        })
    result = {
        "target": args.target,
        "label_basis": "independently expert-validated corpus-unsupported natural near-neighbor",
        "systems": systems,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
