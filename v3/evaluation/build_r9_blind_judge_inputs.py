#!/usr/bin/env python3
"""Create blinded, randomized judge inputs for R9 arm comparisons.

The output JSONL is meant for a later formal judge runner. Condition identity is stored only in
the private key file; public cases strip packet-version/lane metadata and remap evidence IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
from typing import Any, Mapping


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: pathlib.Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def unit_id(row: Mapping[str, Any]) -> str:
    return str(row.get("knowledge_unit_id") or row.get("kc_id") or row.get("topic_id") or "")


def canonical_name(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get("canonical_name") or "").split())


def extract_draft_object(row: Mapping[str, Any]) -> dict:
    obj = row.get("draft")
    if isinstance(obj, dict) and obj:
        return obj
    for field in ("raw_response", "repair_raw_response", "parse_repair_raw_response"):
        raw = row.get(field)
        if isinstance(raw, dict) and raw:
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def draft_payload(obj: Mapping[str, Any]) -> dict:
    payload = obj.get("contextual_kc_draft") or obj.get("contextual_topic_draft") or {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def replace_exact_ids(obj: Any, id_map: Mapping[str, str]) -> Any:
    if isinstance(obj, str):
        return id_map.get(obj, obj)
    if isinstance(obj, list):
        return [replace_exact_ids(x, id_map) for x in obj]
    if isinstance(obj, dict):
        return {k: replace_exact_ids(v, id_map) for k, v in obj.items()}
    return obj


def public_evidence(packet: Mapping[str, Any]) -> tuple[list[dict], dict[str, str]]:
    raw = [e for e in (packet.get("evidence_for_synthesis") or []) if isinstance(e, Mapping)]
    id_map: dict[str, str] = {}
    public: list[dict] = []
    for idx, ev in enumerate(raw):
        old_id = str(ev.get("evidence_id") or f"missing:{idx}")
        new_id = f"E{idx + 1:03d}"
        id_map[old_id] = new_id
        item = {
            "evidence_id": new_id,
            "text": str(ev.get("text") or ev.get("source_block_text") or ""),
            "doc_id": ev.get("doc_id"),
            "page_index": ev.get("page_index"),
            "page_index_max": ev.get("page_index_max"),
        }
        if ev.get("patch_heading"):
            item["local_heading"] = ev.get("patch_heading")
        if ev.get("assertability"):
            item["assertability"] = ev.get("assertability")
        if ev.get("shape_tags") or ev.get("shapes"):
            item["shape_tags"] = list(ev.get("shape_tags") or ev.get("shapes") or [])
        public.append(item)
    return public, id_map


def public_draft(row: Mapping[str, Any], id_map: Mapping[str, str]) -> dict:
    obj = extract_draft_object(row)
    payload = replace_exact_ids(draft_payload(obj), id_map)
    keep = {
        "status",
        "text",
        "evidence_map",
        "coverage_notes",
        "uncertainty_notes",
        "sibling_contrast_notes",
        "do_not_confuse_with",
    }
    return {k: payload.get(k) for k in sorted(keep) if k in payload}


def parse_arm_arg(value: str) -> tuple[str, pathlib.Path, pathlib.Path]:
    parts = value.split("|")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--arm must be label|packets_jsonl|drafts_jsonl")
    return parts[0], pathlib.Path(parts[1]), pathlib.Path(parts[2])


def case_id(seed: int, unit: str, label: str) -> str:
    raw = f"{seed}|{unit}|{label}".encode("utf-8")
    return "J" + hashlib.sha256(raw).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", action="append", required=True, type=parse_arm_arg,
                    help="label|packets_jsonl|drafts_jsonl; repeat for every arm")
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--seed", type=int, default=20260822)
    args = ap.parse_args()

    public_rows: list[dict] = []
    key_rows: list[dict] = []
    for label, packet_path, draft_path in args.arm:
        packets = {unit_id(p): p for p in load_jsonl(packet_path)}
        drafts = {unit_id(d): d for d in load_jsonl(draft_path)}
        for uid in sorted(packets):
            packet = packets[uid]
            draft = drafts.get(uid) or {}
            jid = case_id(args.seed, uid, label)
            evidence, id_map = public_evidence(packet)
            public_rows.append({
                "judge_case_id": jid,
                "unit_id": uid,
                "canonical_name": canonical_name(packet),
                "hierarchy": packet.get("hierarchy") or {},
                "sibling_kc_names": packet.get("sibling_kc_names") or [],
                "rival_units_considered": packet.get("rival_units_considered") or [],
                "evidence_for_judge": evidence,
                "draft_for_judge": public_draft(draft, id_map),
            })
            key_rows.append({
                "judge_case_id": jid,
                "arm_label": label,
                "unit_id": uid,
                "packet_path": str(packet_path),
                "draft_path": str(draft_path),
                "evidence_id_map": id_map,
            })

    rng = random.Random(args.seed)
    rng.shuffle(public_rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "judge_input_manifest.jsonl", public_rows)
    write_jsonl(args.out_dir / "judge_blind_key.jsonl", key_rows)
    (args.out_dir / "judge_input_README.md").write_text(
        "# R9 Blind Judge Inputs\n\n"
        "The JSONL manifest is randomized deterministically and hides arm labels. "
        "Evidence IDs are remapped per case. The separate key file must not be shown to judges.\n",
        encoding="utf-8",
    )
    print(f"judge inputs -> {args.out_dir / 'judge_input_manifest.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
