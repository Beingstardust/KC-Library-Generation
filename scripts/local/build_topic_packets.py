"""Build topic-unit packets from the SAME evidence that produced the child KC packets.

WHY THIS SHAPE
--------------
The original pipeline drafted a topic from its child KCs' finished DRAFTS ("use child KC summaries
as the backbone"). Checked against the original run's own output: all 22 topics used zero
topic-evidence ids, so a topic was in practice a model summarising other model output. That has
two costs - a topic cannot be drafted until every child KC is drafted (strictly sequential), and
any error in a child draft propagates upward with nothing to check it against.

This builds the topic packet from the children's evidence passages instead, so a topic draft is
grounded in source text exactly like a KC draft is, and topic drafting can run at the same time as
KC drafting rather than after it.

Measured before choosing: the full union of a topic's children's evidence peaks at 70,737 chars
(~17.7k tokens) for the largest topic, which fits the 32k context alongside the prompt. A per-child
cap is still applied so one verbose child cannot crowd out its siblings, and the packet keeps an
overall character budget the way KC packets do.

TOPIC SET
---------
The 22 topics are the hierarchy nodes whose children are ALL knowledge units. That rule is not
invented here - it is what the original library contains, verified by diffing this hierarchy
against the original run's 22 topic packets: the only node with mixed children ("Decision Trees",
12 KCs plus the child topic "Overfitting and Pruning") is the single node the original omitted.
Matching the rule keeps the two libraries comparable. Parent topics remain out of scope, as the
original drafting prompt itself states.

Each evidence item records which child KC it came from, so a topic claim can be traced to both a
source passage and the unit it belongs to.
"""
import argparse
import collections
import io
import json


def load_jsonl(path):
    return [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hierarchy-jsonl", required=True)
    ap.add_argument("--kc-packets-jsonl", required=True)
    ap.add_argument("--out-jsonl", required=True)
    ap.add_argument("--stats-json", default=None)
    ap.add_argument("--max-chars", type=int, default=24000)
    ap.add_argument("--per-child-max", type=int, default=6)
    a = ap.parse_args()

    nodes = load_jsonl(a.hierarchy_jsonl)
    kc_packets = {r.get("knowledge_unit_id"): r for r in load_jsonl(a.kc_packets_jsonl)}

    by_parent = collections.defaultdict(list)
    for n in nodes:
        by_parent[n.get("parent_hier_node_id")].append(n)

    packets = []
    for node in nodes:
        if node.get("node_type") == "leaf":
            continue
        kids = by_parent.get(node.get("hier_node_id")) or []
        kc_kids = [k for k in kids if k.get("kc_id")]
        topic_kids = [k for k in kids if not k.get("kc_id")]
        # terminal topics only: every child is a knowledge unit (matches the original library)
        if not kc_kids or topic_kids:
            continue

        children = [{"child_kc_id": k["kc_id"], "child_kc_name": k.get("label") or ""}
                    for k in kc_kids]

        # Round-robin across children so a verbose child cannot crowd out its siblings, taking
        # each child's passages in its own relevance order.
        ranked = {}
        for c in children:
            pkt = kc_packets.get(c["child_kc_id"]) or {}
            ev = list(pkt.get("evidence_for_synthesis") or [])[: a.per_child_max]
            ranked[c["child_kc_id"]] = ev

        evidence = []
        used = 0
        for depth in range(a.per_child_max):
            for c in children:
                items = ranked.get(c["child_kc_id"]) or []
                if depth >= len(items):
                    continue
                e = items[depth]
                text = str(e.get("text") or "")
                if used + len(text) > a.max_chars:
                    continue
                used += len(text)
                evidence.append({
                    "evidence_id": e.get("evidence_id"),
                    "text": text,
                    "source_block_text": text,
                    "doc_id": e.get("doc_id"),
                    "page_index": e.get("page_index"),
                    "patch_heading": e.get("patch_heading") or "",
                    "shape_tags": list(e.get("shape_tags") or []),
                    "relevance": e.get("relevance"),
                    "source_child_kc_id": c["child_kc_id"],
                    "source_child_kc_name": c["child_kc_name"],
                    "evidence_lane": "topic_from_child_kc_evidence",
                })

        shapes = collections.Counter(s for e in evidence for s in (e.get("shape_tags") or []))
        covered = sorted({e["source_child_kc_id"] for e in evidence})
        packets.append({
            "knowledge_unit_id": node.get("hier_node_id"),
            "kc_id": None,
            "knowledge_unit_type": "topic",
            "canonical_name": node.get("label"),
            "packet_version": "step67_comprehensive_topic_packet_v1",
            "hierarchy": {
                "topic_path": list(node.get("source_hierarchy_path") or []),
                "source_hierarchy_path": list(node.get("source_hierarchy_path") or []),
                "parent_topic_label": "",
                "leaf_label": node.get("label"),
            },
            "direct_child_kcs": children,
            "child_kc_count": len(children),
            "evidence_for_synthesis": evidence,
            "evidence_coverage": {
                "passage_count": len(evidence),
                "total_chars": used,
                "shape_coverage": dict(shapes),
                "has_definition": "definition" in shapes,
                "has_formula": "formula" in shapes,
                "has_procedure": "procedure" in shapes,
                "has_example": "example" in shapes,
                "child_kcs_represented": len(covered),
                "child_kcs_total": len(children),
                "child_kcs_without_evidence": sorted(
                    c["child_kc_id"] for c in children if c["child_kc_id"] not in covered),
            },
            "drafting_instruction": {
                "goal": ("Write a cohesive account of this topic: what it covers, how its child "
                         "knowledge units relate to one another, and the boundary of the topic."),
                "must_use": [
                    "Draft from the supplied source passages, which are the same passages that "
                    "ground this topic's child knowledge units.",
                    "Every child knowledge unit named in direct_child_kcs must be accounted for - "
                    "covered if the passages support it, or named as a gap if they do not.",
                    "Relate the children to each other; do not emit an unstructured list.",
                    "Do not invent anything the passages do not support.",
                ],
            },
            "insufficient_synthesis_support": not evidence,
            "abstention_expected": not evidence,
            "packet_support_state": "comprehensive" if evidence else "insufficient_support",
        })

    with io.open(a.out_jsonl, "w", encoding="utf-8") as fh:
        for p in packets:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    n = len(packets)
    stats = {
        "topic_units": n,
        "mean_child_kcs": round(sum(p["child_kc_count"] for p in packets) / max(n, 1), 2),
        "mean_passages": round(sum(p["evidence_coverage"]["passage_count"] for p in packets) / max(n, 1), 2),
        "mean_chars": round(sum(p["evidence_coverage"]["total_chars"] for p in packets) / max(n, 1), 1),
        "topics_with_definition": sum(1 for p in packets if p["evidence_coverage"]["has_definition"]),
        "topics_with_formula": sum(1 for p in packets if p["evidence_coverage"]["has_formula"]),
        "topics_with_procedure": sum(1 for p in packets if p["evidence_coverage"]["has_procedure"]),
        "topics_all_children_represented": sum(
            1 for p in packets
            if p["evidence_coverage"]["child_kcs_represented"] == p["evidence_coverage"]["child_kcs_total"]),
        "topics_empty": sum(1 for p in packets if not p["evidence_for_synthesis"]),
    }
    if a.stats_json:
        io.open(a.stats_json, "w", encoding="utf-8").write(json.dumps(stats, indent=2))
    for k, v in stats.items():
        print("  %-34s %s" % (k, v))


if __name__ == "__main__":
    main()
