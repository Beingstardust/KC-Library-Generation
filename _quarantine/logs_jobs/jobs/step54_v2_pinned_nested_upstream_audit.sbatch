#!/bin/bash
#SBATCH --job-name=s54v2_pin_audit
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:30:00
#SBATCH --output=logs/s54v2_pin_audit-%j.out
#SBATCH --error=logs/s54v2_pin_audit-%j.err

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean

export PYTHON_BIN=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH=/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "==== job context ===="
date -u
hostname
echo "PWD=$PWD"
"$PYTHON_BIN" --version

"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json
from collections import defaultdict

root = Path(".")

STEP54_SET = root / "data/processed/kc_evidence_packs/_sets/step54_role_eligibility_v2_r10_20260427_182346_step5_4_kc_evidence_packs_set.json"
STEP66_SET = root / "data/processed/kc_drafting_input_overlay/_sets/2026-04-27_182358_step6_6_kc_drafting_input_overlay_set.json"
STEP53_SET = root / "data/processed/kc_evidence_recalibrated/_sets/2026-04-26_195746_step5_3_kc_evidence_recalibrated_set.json"

for p in [STEP54_SET, STEP66_SET, STEP53_SET]:
    if not p.exists():
        raise SystemExit(f"Missing required pinned artifact: {p}")

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def text_of(obj):
    for key in [
        "text",
        "snippet",
        "candidate_text",
        "sentence_text",
        "quote",
        "source_text",
        "source_block_text",
        "block_text",
        "patch_text",
        "raw_text",
    ]:
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return " ".join(v.split())
    return ""

def score_of(obj):
    for key in [
        "final_score",
        "score",
        "rerank_score",
        "calibrated_score",
        "similarity",
        "combined_score",
        "sharp_score",
    ]:
        if key in obj:
            return obj.get(key)
    return None

def refs_of(obj):
    keys = [
        "kc_id",
        "canonical_name",
        "doc_id",
        "block_id",
        "page_index",
        "page",
        "layer",
        "patch_id",
        "patch_heading",
        "sentence_id",
        "candidate_id",
        "preferred_support_role",
        "safe_role_hint",
        "support_role",
    ]
    return {k: obj.get(k) for k in keys if k in obj}

def contains_any(text, terms):
    low = text.lower()
    return any(t.lower() in low for t in terms)

targets = {
    "KC_CLF_NB_011": {
        "name": "Handling Missing Values in NB",
        "terms": ["handling missing values", "missing values", "naive bayes", "bayes", "nb"],
        "bad": ["decision tree classifier", "knn instances", "mar missing data mechanism", "patients have missing values"],
    },
    "KC_CLU_DBS_001": {
        "name": "Core Point",
        "terms": ["core point", "core points", "minpts", "eps", "epsilon", "neighborhood"],
        "bad": ["a border point is a point that is not a core point", "a border point is not a core point"],
    },
    "KC_CLU_DBS_003": {
        "name": "Noise Point",
        "terms": ["noise point", "noise points", "neither a core point", "neither core", "discarded"],
        "bad": ["random component of a measurement error", "notice that some of the noise points are"],
    },
    "KC_EVAL_BASIC_005": {
        "name": "Specificity",
        "terms": ["specificity", "true negative", "false positive", "tn", "fp"],
        "bad": [],
    },
    "KC_CLU_EVAL_012": {
        "name": "External Index: Recall",
        "terms": ["recall", "true positive", "false negative", "external index"],
        "bad": [],
    },
    "KC_EVAL_SAMP_003": {
        "name": "k-Fold Cross Validation",
        "terms": ["cross-validation", "cross validation", "fold", "hyper-parameter", "hyperparameter"],
        "bad": ["best choice of the hyper-parameter value"],
    },
}

step54_obj = load_json(STEP54_SET)
step66_obj = load_json(STEP66_SET)
step53_obj = load_json(STEP53_SET)

packs_path = root / step54_obj["artifacts"]["kc_evidence_packs_jsonl"]
stats_path = root / step54_obj["artifacts"]["evidence_pack_stats_json"]
overlay_path = root / step66_obj["artifacts"]["candidate_sentence_overlay_jsonl"]
overlay_stats_path = root / step66_obj["artifacts"]["overlay_stats_json"]
step53_path = root / step53_obj["artifacts"]["kc_evidence_candidates_recalibrated_jsonl"]

packs = read_jsonl(packs_path)
packs_by_kc = {r.get("kc_id"): r for r in packs}

step53_rows = read_jsonl(step53_path)
step53_by_kc = {r.get("kc_id"): r for r in step53_rows}

expanded = []
for row in step53_rows:
    kc_id = row.get("kc_id")
    canonical_name = row.get("canonical_name")
    evidence_items = row.get("evidence") or []
    for idx, ev in enumerate(evidence_items):
        item = dict(ev)
        item["_parent_kc_id"] = kc_id
        item["_parent_canonical_name"] = canonical_name
        item["_evidence_index"] = idx
        expanded.append(item)

print("PINNED_STEP54_SET =", STEP54_SET.as_posix())
print("PINNED_STEP66_SET =", STEP66_SET.as_posix())
print("PINNED_STEP53_SET =", STEP53_SET.as_posix())
print("STEP54_PACKS =", packs_path.as_posix())
print("STEP54_STATS =", stats_path.as_posix())
print("STEP66_OVERLAY =", overlay_path.as_posix())
print("STEP66_OVERLAY_STATS =", overlay_stats_path.as_posix())
print("STEP53_CANDIDATES =", step53_path.as_posix())
print("STEP53_KC_ROWS =", len(step53_rows))
print("STEP53_EXPANDED_EVIDENCE_ITEMS =", len(expanded))

stats = load_json(stats_path)
print()
print("PINNED_STEP54_ROUTE_BREAKDOWN =", stats.get("route_breakdown"))
print("PINNED_STEP54_INSUFFICIENT_REASON_BREAKDOWN =", stats.get("insufficient_reason_breakdown"))
print("PINNED_STEP54_DEFINITION_NL_COUNT =", stats.get("definition_anchor_natural_language_count"))
print("PINNED_STEP54_CONTEXT_COMPLETION_USED =", stats.get("context_completion_used_count"))

positive_roles = [
    "definition_kernel",
    "explanatory_gloss",
    "formula_notation",
    "scope_condition",
    "context_completion",
    "example_or_procedure",
]

audit = {
    "pinned_step54_set": STEP54_SET.as_posix(),
    "pinned_step66_set": STEP66_SET.as_posix(),
    "pinned_step53_set": STEP53_SET.as_posix(),
    "stats": stats,
    "targets": {},
}

print()
print("==== pinned Step 5.4 support and nested Step 5.3 evidence audit ====")

for kc_id, spec in targets.items():
    pack = packs_by_kc.get(kc_id) or {}
    q = pack.get("pack_quality") or {}
    slots = pack.get("slots") or {}

    print()
    print("=" * 120)
    print("KC =", kc_id, "|", spec["name"])
    print("STEP54_ROUTE =", q.get("route"))
    print("STEP54_INSUFFICIENT_REASONS =", q.get("insufficient_reasons"))
    print("STEP54_DEFINITION_NL =", q.get("definition_anchor_natural_language"))

    positive_texts = []
    positive_payload = {}
    for role in positive_roles:
        items = slots.get(role) or []
        positive_payload[role] = []
        if items:
            print("ROLE =", role)
        for item in items:
            txt = " ".join(str(item.get("text") or item.get("quote") or item.get("candidate_text") or "").split())
            positive_texts.append(txt)
            positive_payload[role].append(txt)
            print("  -", txt[:900])

    merged_positive = " ".join(t.lower() for t in positive_texts)
    bad_matches = [m for m in spec["bad"] if m.lower() in merged_positive]
    print("STEP54_BAD_MARKER_MATCHES =", bad_matches)

    parent = step53_by_kc.get(kc_id) or {}
    same_evidence = list(parent.get("evidence") or [])
    print("STEP53_NESTED_SAME_KC_EVIDENCE_COUNT =", len(same_evidence))

    same_payload = []
    for i, ev in enumerate(same_evidence[:18], start=1):
        txt = text_of(ev)
        refs = refs_of(ev)
        print()
        print("SAME_KC_EVIDENCE", i)
        print("score =", score_of(ev))
        print("refs =", refs)
        print("text =", txt[:900])
        same_payload.append({
            "rank": i,
            "score": score_of(ev),
            "refs": refs,
            "text": txt,
        })

    phrase_hits = []
    for ev in expanded:
        txt = text_of(ev)
        if contains_any(txt, spec["terms"]):
            phrase_hits.append(ev)

    print()
    print("STEP53_EXPANDED_PHRASE_HIT_COUNT =", len(phrase_hits))
    phrase_payload = []
    for i, ev in enumerate(phrase_hits[:20], start=1):
        txt = text_of(ev)
        refs = refs_of(ev)
        print()
        print("PHRASE_HIT", i)
        print("parent_kc =", ev.get("_parent_kc_id"), "|", ev.get("_parent_canonical_name"))
        print("score =", score_of(ev))
        print("refs =", refs)
        print("text =", txt[:900])
        phrase_payload.append({
            "rank": i,
            "parent_kc_id": ev.get("_parent_kc_id"),
            "parent_canonical_name": ev.get("_parent_canonical_name"),
            "score": score_of(ev),
            "refs": refs,
            "text": txt,
        })

    audit["targets"][kc_id] = {
        "canonical_name": spec["name"],
        "step54_route": q.get("route"),
        "step54_insufficient_reasons": q.get("insufficient_reasons"),
        "step54_definition_anchor_natural_language": q.get("definition_anchor_natural_language"),
        "step54_bad_marker_matches": bad_matches,
        "step54_positive_slots": positive_payload,
        "step53_same_kc_evidence_count": len(same_evidence),
        "step53_same_kc_top_evidence": same_payload,
        "step53_expanded_phrase_hit_count": len(phrase_hits),
        "step53_expanded_phrase_top_hits": phrase_payload,
    }

out = root / "data/work/cache/diagnostics" / "step54_v2_pinned_nested_upstream_audit_203817.json"
out.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

print()
print("AUDIT_JSON =", out.as_posix())
print("STEP54_V2_PINNED_NESTED_UPSTREAM_AUDIT_OK")
PY
