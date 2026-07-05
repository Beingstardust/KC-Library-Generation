#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(".")

DEFAULT_SMOKE10 = [
    "KC_CLU_EVAL_001",
    "KC_CLU_EVAL_002",
    "KC_DE_PREP_003",
    "KC_EVAL_SAMP_003",
    "KC_CLU_DBS_003",
    "KC_CLU_CORE_002",
    "KC_CLU_DBS_001",
    "KC_CLF_NB_011",
    "KC_CLU_EVAL_012",
    "KC_EVAL_BASIC_005",
]

TEXT_KEYS = {
    "quote_surface",
    "source_block_text",
    "original_quote_surface",
    "query_text",
    "query_used",
}

RISK_WORDS = [
    "contamination",
    "high_contamination",
    "sibling",
    "background_drift",
    "formula_only",
    "heading_only",
    "weak",
    "fragment",
]

DEFINITION_CUES = [
    " is ",
    " are ",
    " refers to ",
    " defined as ",
    " known as ",
    " called ",
    " measures ",
    " method ",
    " algorithm ",
    " procedure ",
    " criterion ",
    " index ",
]

SCOPE_CUES = [
    " used ",
    " use ",
    " applied ",
    " objective ",
    " purpose ",
    " role ",
    " helps ",
    " allows ",
    " computes ",
    " evaluates ",
    " selects ",
    " assigns ",
]


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def resolve_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def compact_text(text: Any, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(" ", 1)[0].strip()
    return cut + " ..."


def collect_scalar_signals(obj: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            low = key.lower()

            if any(token in low for token in ["text", "quote", "bbox", "char", "block_text"]):
                continue

            if isinstance(v, (str, int, float, bool)) or v is None:
                if any(token in low for token in ["role", "class", "score", "rank", "risk", "support", "definition", "scope", "candidate", "verified", "rebound", "reason"]):
                    out[key] = v
            elif isinstance(v, list):
                if len(v) <= 8 and all(isinstance(x, (str, int, float, bool)) or x is None for x in v):
                    if any(token in low for token in ["role", "class", "risk", "support", "reason", "path", "label"]):
                        out[key] = v
                else:
                    for item in v[:3]:
                        collect_scalar_signals(item, key + "[]", out)
            else:
                collect_scalar_signals(v, key, out)
    return out


def signal_blob(row: dict[str, Any]) -> str:
    signals = collect_scalar_signals(row)
    return norm(json.dumps(signals, ensure_ascii=False))


def text_blob(row: dict[str, Any]) -> str:
    parts = []
    for key in ["quote_surface", "source_block_text", "original_quote_surface", "patch_heading", "page_heading_norm"]:
        value = row.get(key)
        if value:
            parts.append(str(value))
    return norm(" ".join(parts))


def candidate_text(row: dict[str, Any], max_chars: int) -> tuple[str, str]:
    quote = str(row.get("quote_surface") or "").strip()
    source = str(row.get("source_block_text") or "").strip()
    original = str(row.get("original_quote_surface") or "").strip()

    if len(quote) >= 40:
        return compact_text(quote, max_chars), "quote_surface"
    if len(source) >= 40:
        return compact_text(source, max_chars), "source_block_text"
    if original:
        return compact_text(original, max_chars), "original_quote_surface"
    return compact_text(quote or source or original, max_chars), "fallback_empty_or_short"


def role_hints(row: dict[str, Any]) -> list[str]:
    blob = signal_blob(row)
    hints = []
    for token in [
        "definitional_anchor",
        "definition_anchor",
        "strong_definition_anchor",
        "explanatory_anchor",
        "definition_support",
        "scope",
        "procedure",
        "example",
        "formula",
        "contamination",
        "high_contamination",
        "context_completion",
    ]:
        if token in blob:
            hints.append(token)
    return sorted(set(hints))


def risk_hints(row: dict[str, Any]) -> list[str]:
    blob = signal_blob(row)
    hints = []
    for token in RISK_WORDS:
        if token in blob:
            hints.append(token)
    return sorted(set(hints))


def score_candidate(row: dict[str, Any], canonical_name: str, aliases: list[str], purpose: str) -> float:
    blob = signal_blob(row)
    text = text_blob(row)
    name_terms = [canonical_name, *aliases]
    name_hit = any(norm(name) and norm(name) in text for name in name_terms)

    score = 0.0
    idx = row.get("source_candidate_index")
    if isinstance(idx, int):
        score += max(0.0, 4.0 - min(idx, 12) * 0.2)

    if name_hit:
        score += 2.0

    if "quote_verified" in row and row.get("quote_verified") is True:
        score += 1.0

    if purpose == "definition":
        if "definitional_anchor" in blob:
            score += 5.0
        if "definition_anchor" in blob:
            score += 4.0
        if "strong_definition_anchor" in blob:
            score += 4.0
        if any(cue in text for cue in DEFINITION_CUES):
            score += 2.0
    elif purpose == "scope":
        if "explanatory_anchor" in blob:
            score += 4.0
        if any(cue in text for cue in SCOPE_CUES):
            score += 2.0
        if "procedure" in blob:
            score += 1.0

    if "high_contamination" in blob:
        score -= 6.0
    elif "contamination" in blob:
        score -= 3.0
    if "formula_only" in blob:
        score -= 2.0
    if "heading_only" in blob:
        score -= 2.0

    if len(text) < 40:
        score -= 3.0

    return score


def find_candidate_jsonl(step66_set: Path) -> Path:
    set_obj = read_json(step66_set)
    artifacts = set_obj.get("artifacts") or {}

    candidates = []
    for key, value in artifacts.items():
        p = resolve_path(value)
        if p and p.exists() and p.suffix == ".jsonl" and "candidate_sentence_overlay" in p.name:
            candidates.append(p)

    if candidates:
        return candidates[0]

    processed_dir = Path("data/processed/kc_drafting_input_overlay/2026-04-28_002730")
    fallback = processed_dir / "candidate_sentence_overlay.jsonl"
    if fallback.exists():
        return fallback

    raise SystemExit(f"FAIL: could not locate candidate_sentence_overlay.jsonl from {step66_set}")


def build_packet(
    kc_id: str,
    rows: list[dict[str, Any]],
    step66_set: Path,
    max_candidates: int,
    max_text_chars: int,
) -> dict[str, Any]:
    first = rows[0]
    canonical_name = str(first.get("canonical_name") or "")
    aliases = first.get("aliases") if isinstance(first.get("aliases"), list) else []
    aliases = [str(x) for x in aliases if str(x).strip()]

    ranked_def = sorted(
        rows,
        key=lambda r: score_candidate(r, canonical_name, aliases, "definition"),
        reverse=True,
    )
    ranked_scope = sorted(
        rows,
        key=lambda r: score_candidate(r, canonical_name, aliases, "scope"),
        reverse=True,
    )
    ranked_index = sorted(
        rows,
        key=lambda r: r.get("source_candidate_index") if isinstance(r.get("source_candidate_index"), int) else 9999,
    )

    selected = []
    seen = set()

    def add(row: dict[str, Any]) -> None:
        oid = str(row.get("overlay_candidate_id") or "")
        if not oid or oid in seen:
            return
        selected.append(row)
        seen.add(oid)

    for bucket in [ranked_def[:4], ranked_scope[:3], ranked_index[:3]]:
        for row in bucket:
            add(row)

    selected = selected[:max_candidates]

    evidence = []
    for i, row in enumerate(selected, start=1):
        text, text_source = candidate_text(row, max_text_chars)
        evidence.append({
            "evidence_id": f"E{i}",
            "overlay_candidate_id": row.get("overlay_candidate_id"),
            "source_candidate_index": row.get("source_candidate_index"),
            "text": text,
            "text_source": text_source,
            "role_hints": role_hints(row),
            "risk_hints": risk_hints(row),
            "definition_score": round(score_candidate(row, canonical_name, aliases, "definition"), 4),
            "scope_score": round(score_candidate(row, canonical_name, aliases, "scope"), 4),
            "provenance": {
                "doc_id": row.get("doc_id"),
                "page_index": row.get("page_index"),
                "block_id": row.get("block_id"),
                "sentence_id": row.get("sentence_id"),
                "patch_id": row.get("patch_id"),
                "patch_heading": row.get("patch_heading"),
                "patch_type": row.get("patch_type"),
                "layer": row.get("layer"),
            },
        })

    source_hash = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return {
        "packet_contract_version": "step67a_evidence_packet_v1",
        "source_step6_6_set_manifest": step66_set.as_posix(),
        "source_candidate_row_count_for_kc": len(rows),
        "source_rows_sha256": source_hash,
        "kc_id": kc_id,
        "canonical_name": canonical_name,
        "aliases": aliases,
        "topic_path_labels": first.get("source_hierarchy_path") or first.get("ancestor_labels") or [],
        "query_text": first.get("query_text") or "",
        "seed_definition": first.get("seed_definition") or "",
        "seed_definition_is_not_evidence": True,
        "support_pack_summary": first.get("step5_3_support_pack_summary") or {},
        "review_queue_aux": first.get("step5_3_review_queue_aux") or {},
        "evidence": evidence,
        "packet_notes": [
            "Evidence ids are local to this packet.",
            "Use seed_definition only as a label/context guardrail, not as evidence.",
            "If direct evidence is insufficient, abstain rather than inventing a complete KC.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step66-set", required=True)
    parser.add_argument("--out-root", default="data/processed/step67_sidecar_packets")
    parser.add_argument("--exact-kc-ids", nargs="*", default=[])
    parser.add_argument("--limit-kcs", type=int, default=0)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--max-text-chars", type=int, default=520)
    args = parser.parse_args()

    step66_set = Path(args.step66_set)
    if not step66_set.exists():
        raise SystemExit(f"FAIL: missing Step 6.6 set manifest: {step66_set}")

    run_id = utc_run_id()
    out_dir = Path(args.out_root) / run_id
    packets_path = out_dir / "evidence_packets.jsonl"
    manifest_path = out_dir / "manifest.json"
    snapshot_path = out_dir / "packet_snapshot.md"

    candidate_path = find_candidate_jsonl(step66_set)
    rows = read_jsonl(candidate_path)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        kc_id = str(row.get("kc_id") or "")
        if kc_id:
            grouped[kc_id].append(row)

    if args.exact_kc_ids:
        selected_ids = [kc for kc in args.exact_kc_ids if kc in grouped]
    else:
        selected_ids = sorted(grouped)

    if args.limit_kcs and args.limit_kcs > 0:
        selected_ids = selected_ids[: args.limit_kcs]

    missing_requested = [kc for kc in args.exact_kc_ids if kc not in grouped]

    packets = [
        build_packet(
            kc_id=kc_id,
            rows=grouped[kc_id],
            step66_set=step66_set,
            max_candidates=args.max_candidates,
            max_text_chars=args.max_text_chars,
        )
        for kc_id in selected_ids
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    for packet in packets:
        append_jsonl(packets_path, packet)

    manifest = {
        "stage": "step67a_evidence_packet_build",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "step66_set": step66_set.as_posix(),
        "candidate_sentence_overlay_jsonl": candidate_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "packets_path": packets_path.as_posix(),
        "packet_count": len(packets),
        "selected_kc_ids": selected_ids,
        "missing_requested_kc_ids": missing_requested,
        "source_total_rows": len(rows),
        "source_unique_kc_count": len(grouped),
        "candidate_count_distribution": dict(sorted(Counter(len(v) for v in grouped.values()).items())),
        "max_candidates_per_packet": args.max_candidates,
        "max_text_chars": args.max_text_chars,
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }
    write_json(manifest_path, manifest)

    lines = []
    lines.append("# Step 6.7A evidence packet snapshot")
    lines.append("")
    lines.append(f"- Run id: `{run_id}`")
    lines.append(f"- Packet count: `{len(packets)}`")
    lines.append(f"- Source candidate rows: `{len(rows)}`")
    lines.append(f"- Source unique KCs: `{len(grouped)}`")
    lines.append(f"- Packets: `{packets_path.as_posix()}`")
    lines.append("")
    for packet in packets:
        lines.append(f"## {packet['kc_id']} | {packet['canonical_name']}")
        lines.append("")
        lines.append(f"- Topic: `{packet.get('topic_path_labels')}`")
        lines.append(f"- Source rows for KC: `{packet.get('source_candidate_row_count_for_kc')}`")
        lines.append(f"- Evidence candidates selected: `{len(packet.get('evidence') or [])}`")
        for ev in packet.get("evidence") or []:
            text = ev.get("text") or ""
            if len(text) > 280:
                text = text[:280] + " ..."
            lines.append(f"  - `{ev['evidence_id']}` idx=`{ev.get('source_candidate_index')}` def_score=`{ev.get('definition_score')}` scope_score=`{ev.get('scope_score')}` roles=`{ev.get('role_hints')}` risks=`{ev.get('risk_hints')}`")
            lines.append(f"    - {text}")
        lines.append("")
    snapshot_path.write_text("\n".join(lines), encoding="utf-8")

    print("STEP67A_PACKETS_RUN_ID =", run_id)
    print("STEP67A_PACKETS_DIR =", out_dir.as_posix())
    print("STEP67A_PACKETS_JSONL =", packets_path.as_posix())
    print("STEP67A_PACKETS_MANIFEST =", manifest_path.as_posix())
    print("STEP67A_PACKET_SNAPSHOT_MD =", snapshot_path.as_posix())
    print("packet_count =", len(packets))
    print("selected_kc_ids =", json.dumps(selected_ids, ensure_ascii=False))
    print("missing_requested_kc_ids =", json.dumps(missing_requested, ensure_ascii=False))
    print("source_total_rows =", len(rows))
    print("source_unique_kc_count =", len(grouped))
    print("candidate_count_distribution =", json.dumps(manifest["candidate_count_distribution"], ensure_ascii=False))
    print("STEP67A_EVIDENCE_PACKETS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
