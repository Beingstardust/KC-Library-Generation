"""Build retrieval profiles from a flat hierarchy_overlay.jsonl - no profiling model in the path.

The data-mining runs have been reading their profile rows out of
data/processed/kc_retrieval_profiles/ablation_01_step5p_gemma4_12b/kc_retrieval_profiles.jsonl.
Only registry-derived fields are consumed from it, but that file is Step 5p OUTPUT, so as long as
it is the input the claim "this pipeline does not depend on the profiling stage" is not literally
true for this domain. Sociology is already clean because its profiles are built straight from its
hierarchy; this does the same for the flat overlay format the data-mining registry uses.

Retrieval reads exactly six fields. Five are copied from the overlay and the sixth is a pure string
function:

    knowledge_unit_id / kc_id     the leaf node's kc_id
    knowledge_unit_type           "kc"
    canonical_name                the leaf node's label
    parent_topic_label            the parent node's label
    topic_path_labels             the node's own source_hierarchy_path
    deterministic_label_variants  deterministic_label_variants(canonical_name)

--verify-against compares the result field-by-field with an existing profile file, so switching
inputs can be shown to be a provenance change and not a behaviour change.
"""
import argparse
import collections
import io
import json
import sys

sys.path.insert(0, '/path/to/projects/kc_l_v2_mirror_20260810/src')
from kc_l.retrieval_profile.deterministic import deterministic_label_variants  # noqa: E402

FIELDS_RETRIEVAL_READS = (
    "knowledge_unit_id", "knowledge_unit_type", "canonical_name",
    "parent_topic_label", "topic_path_labels", "deterministic_label_variants",
)


def load_jsonl(path):
    return [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]


def norm_variants(value):
    out = []
    for v in value or []:
        term = v.get("term") if isinstance(v, dict) else v
        if term:
            out.append(str(term))
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay-jsonl", required=True)
    ap.add_argument("--out-jsonl", required=True)
    ap.add_argument("--verify-against", default=None)
    a = ap.parse_args()

    nodes = load_jsonl(a.overlay_jsonl)
    by_id = {n.get("hier_node_id"): n for n in nodes}

    rows = []
    for n in nodes:
        kc_id = n.get("kc_id")
        if not kc_id:
            continue
        parent = by_id.get(n.get("parent_hier_node_id")) or {}
        label = n.get("label") or ""
        rows.append({
            "knowledge_unit_id": kc_id,
            "kc_id": kc_id,
            "knowledge_unit_type": "kc",
            "canonical_name": label,
            "parent_topic_label": parent.get("label") or "",
            "topic_path_labels": list(n.get("source_hierarchy_path") or []),
            "aliases": [],
            "deterministic_label_variants": deterministic_label_variants(label, []),
            "profile_source": "hierarchy_overlay_only_no_model",
        })

    with io.open(a.out_jsonl, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("knowledge units written : %d" % len(rows))

    if not a.verify_against:
        return 0

    old = {r.get("knowledge_unit_id"): r for r in load_jsonl(a.verify_against)}
    new = {r["knowledge_unit_id"]: r for r in rows}
    print()
    print("FIELD-EQUIVALENCE vs %s" % a.verify_against.split("/")[-2])
    print("  units old=%d new=%d shared=%d" % (len(old), len(new), len(set(old) & set(new))))
    diffs = collections.Counter()
    examples = collections.defaultdict(list)
    for uid in sorted(set(old) & set(new)):
        o, n = old[uid], new[uid]
        for f in FIELDS_RETRIEVAL_READS:
            ov, nv = o.get(f), n.get(f)
            if f == "deterministic_label_variants":
                ov, nv = norm_variants(ov), norm_variants(nv)
            if f == "knowledge_unit_type":
                ov, nv = (ov or "kc"), (nv or "kc")
            if ov != nv:
                diffs[f] += 1
                if len(examples[f]) < 4:
                    examples[f].append((uid, ov, nv))
    for f in FIELDS_RETRIEVAL_READS:
        print("  %-30s differs on %d unit(s)" % (f, diffs.get(f, 0)))
    for f, items in examples.items():
        print()
        print("  --- %s ---" % f)
        for uid, ov, nv in items:
            print("    %-20s 5p=%r" % (uid, ov))
            print("    %-20s new=%r" % ("", nv))
    total = sum(diffs.values())
    print()
    print("RESULT: %s" % ("IDENTICAL on every field retrieval reads"
                          if total == 0 else "%d field differences - inspect above" % total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
