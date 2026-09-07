"""Assemble KC-level and topic-level machine drafts into one nested KC Library document.

WHY THIS STEP WAS MISSING
--------------------------
Drafting produces two flat, independent files - kc_drafts_<model>.jsonl and
topic_drafts_<model>.jsonl - joined only by ID convention. Nothing in the pipeline combined them
into the structure the paper actually describes: "a KC Library is more than a list of KC names...
each entry has a stable curriculum identity and hierarchy position." Analysts had to manually
cross-reference two files by knowledge_unit_id. This closes that gap with one dedicated, real step
rather than a bridging script bolted onto something else.

Explicitly NOT review resolution (in the paper, not reliably operational): this assembles
MACHINE drafts as they exist right now, with no reviewer verdict involved. It is the artifact that
would feed review, not a replacement for it.

STRUCTURE, DERIVED ENTIRELY FROM THE PACKET'S OWN HIERARCHY FIELDS
--------------------------------------------------------------------
Each topic draft's source_packet already carries direct_child_kcs (a real, existing field - see
03_build_topic_packets.py), which is the only fact needed to nest KC entries under their topic. No
new hierarchy logic, no domain assumption: whatever the curriculum's own topic set is, that is what
gets built.

ORPHAN KCs ARE NOT A BUG AND MUST NOT BE DROPPED
--------------------------------------------------
03_build_topic_packets.py's own documented rule: the topic set is "the hierarchy nodes whose
children are ALL knowledge units" - a node with MIXED children (some KC, some child-topic) is
excluded from topic packet generation. Its direct KC children then belong to no topic draft.
Measured on the real data-mining rebuild: 12 of 159 KCs (the Decision Trees case) are orphans this
way. They are reported under their own top-level key, never silently absorbed or discarded.

assemble_library is importable directly (v3/pipeline/06_sync_console_registry.py calls it as
part of the automatic console-sync chain, not just this file's own CLI) - kept separate from
argv/file-I/O handling in main so both call sites share the identical assembly logic.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def draft_status(row: Dict[str, Any]) -> str:
    d = row.get("draft") or {}
    inner = d.get("contextual_kc_draft") or d.get("contextual_topic_draft") or {}
    return str(inner.get("status") or "unknown").lower()


def compact_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    """The fields a library reader actually needs from one draft row - not the full row, which
    also carries raw_response, ollama_metadata, prompt_chars and other run-diagnostic fields that
    belong in the drafting log, not in the assembled library."""
    packet = row.get("source_packet") or {}
    return {
        "knowledge_unit_id": row.get("knowledge_unit_id"),
        "knowledge_unit_type": row.get("knowledge_unit_type"),
        "canonical_name": row.get("canonical_name"),
        "hierarchy": packet.get("hierarchy"),
        "model": row.get("model"),
        "run_id": row.get("run_id"),
        "packet_support_state": packet.get("packet_support_state"),
        "status": draft_status(row),
        "draft": row.get("draft"),
        "validation_issues": row.get("validation_issues") or [],
        "hard_failure": bool(row.get("runtime_error") or row.get("parse_error")),
    }


def single_model(rows: List[Dict[str, Any]], label: str) -> str:
    models = sorted({str(r.get("model") or "") for r in rows})
    if len(models) > 1:
        raise SystemExit(
            "FATAL: %s draft file mixes more than one model (%s) - pass a single "
            "per-model drafts file, matching this project's own one-model-per-file "
            "convention." % (label, models))
    return models[0] if models else ""


def assemble_library(kc_drafts_jsonl: str, topic_drafts_jsonl: str, run_id: str) -> Dict[str, Any]:
    kc_rows = load_jsonl(kc_drafts_jsonl)
    topic_rows = load_jsonl(topic_drafts_jsonl)

    kc_ids = [r.get("knowledge_unit_id") for r in kc_rows]
    dup_kc = [k for k, c in collections.Counter(kc_ids).items() if c > 1]
    if dup_kc:
        raise SystemExit("FATAL: duplicate knowledge_unit_id in KC drafts: %s" % dup_kc[:5])
    topic_ids = [r.get("knowledge_unit_id") for r in topic_rows]
    dup_topic = [k for k, c in collections.Counter(topic_ids).items() if c > 1]
    if dup_topic:
        raise SystemExit("FATAL: duplicate knowledge_unit_id in topic drafts: %s" % dup_topic[:5])

    kc_by_id = {r["knowledge_unit_id"]: r for r in kc_rows}
    claimed: set = set()
    warnings: List[str] = []

    topics_out = []
    for trow in topic_rows:
        tpacket = trow.get("source_packet") or {}
        children_out = []
        for child in (tpacket.get("direct_child_kcs") or []):
            child_id = child.get("child_kc_id")
            kc_row = kc_by_id.get(child_id)
            if kc_row is None:
                warnings.append(
                    "topic %s references child KC %s, which has no row in the KC drafts file "
                    "(different run, or a partial/--limit-units invocation)"
                    % (trow.get("knowledge_unit_id"), child_id))
                continue
            children_out.append(compact_entry(kc_row))
            claimed.add(child_id)
        topics_out.append({
            **compact_entry(trow),
            "child_kc_count_expected": tpacket.get("child_kc_count"),
            "children": children_out,
        })

    ungrouped = [compact_entry(r) for kid, r in kc_by_id.items() if kid not in claimed]

    def status_counts(entries):
        c = collections.Counter(e["status"] for e in entries)
        return dict(sorted(c.items()))

    all_kc_entries = [c for t in topics_out for c in t["children"]] + ungrouped

    return {
        "library_version": "kc_library_draft_v1",
        "run_id": run_id,
        "created_utc": now_utc(),
        "kc_model": single_model(kc_rows, "KC"),
        "topic_model": single_model(topic_rows, "topic"),
        "counts": {
            "topics": len(topics_out),
            "total_kcs": len(kc_rows),
            "grouped_kcs": len(claimed),
            "ungrouped_kcs": len(ungrouped),
        },
        "status_counts": {
            "topics": status_counts(topics_out),
            "kcs": status_counts(all_kc_entries),
        },
        "topics": topics_out,
        "ungrouped_kcs": ungrouped,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kc-drafts-jsonl", required=True)
    ap.add_argument("--topic-drafts-jsonl", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    library = assemble_library(args.kc_drafts_jsonl, args.topic_drafts_jsonl, args.run_id)

    with io.open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(library, fh, indent=2, ensure_ascii=False)

    print("KC_LIBRARY_ASSEMBLED=1")
    print("topics=%d  grouped_kcs=%d  ungrouped_kcs=%d  total_kcs=%d"
          % (len(library["topics"]), library["counts"]["grouped_kcs"],
             library["counts"]["ungrouped_kcs"], library["counts"]["total_kcs"]))
    if library["warnings"]:
        print("WARNINGS=%d" % len(library["warnings"]))
        for w in library["warnings"][:10]:
            print("  -", w)
    print("library -> %s" % args.out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
