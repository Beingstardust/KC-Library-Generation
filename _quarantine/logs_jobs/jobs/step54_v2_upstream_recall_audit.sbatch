#!/bin/bash
#SBATCH --job-name=s54v2_audit
#SBATCH --partition=gpu46GB
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:30:00
#SBATCH --output=logs/s54v2_audit-%j.out
#SBATCH --error=logs/s54v2_audit-%j.err

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

echo
echo "==== Step 5.4 v2 upstream recall audit ===="

"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import json
import re
from collections import defaultdict

root = Path(".")

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def read_jsonl(path):
    rows = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def text_of(row):
    for key in [
        "text",
        "snippet",
        "candidate_text",
        "sentence_text",
        "quote",
        "source_text",
        "source_block_text",
        "raw_text",
    ]:
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return " ".join(v.split())
    return " ".join(json.dumps(row, ensure_ascii=False)[:800].split())

def score_of(row):
    for key in ["final_score", "score", "rerank_score", "calibrated_score", "similarity", "combined_score"]:
        if key in row:
            return row.get(key)
    return None

def row_ref(row):
    refs = {}
    for key in [
        "kc_id",
        "canonical_name",
        "doc_id",
        "page",
        "page_num",
        "patch_id",
        "sentence_id",
        "candidate_id",
        "source_ref",
        "source_refs",
        "safe_role_hint",
        "preferred_support_role",
    ]:
        if key in row:
            refs[key] = row.get(key)
    return refs

def contains_any(text, terms):
    low = text.lower()
    return any(t.lower() in low for t in terms)

def compact_hits(rows, terms, limit=12):
    hits = []
    for row in rows:
        txt = text_of(row)
        if contains_any(txt, terms):
            hits.append(row)
    hits = sorted(
        hits,
        key=lambda r: (
            score_of(r) is None,
            -(float(score_of(r)) if isinstance(score_of(r), (int, float)) else 0.0),
        ),
    )
    return hits[:limit], len(hits)

targets = {
    "KC_CLF_NB_011": {
        "name": "Handling Missing Values in NB",
        "terms": ["handling missing values", "missing values", "naive bayes", "bayes", "nb"],
        "expected": ["naive bayes", "bayes", "probability", "missing"],
    },
    "KC_CLU_DBS_001": {
        "name": "Core Point",
        "terms": ["core point", "core points", "minpts", "eps", "epsilon", "neighborhood"],
        "expected": ["core point", "minpts", "eps", "neighborhood"],
    },
    "KC_CLU_DBS_003": {
        "name": "Noise Point",
        "terms": ["noise point", "noise points", "neither a core point", "neither core", "discarded"],
        "expected": ["noise point", "neither", "core", "border", "discarded"],
    },
    "KC_EVAL_BASIC_005": {
        "name": "Specificity",
        "terms": ["specificity", "true negative", "false positive", "tn", "fp"],
        "expected": ["specificity", "true negative", "false positive"],
    },
    "KC_CLU_EVAL_012": {
        "name": "External Index: Recall",
        "terms": ["recall", "true positive", "false negative", "external index"],
        "expected": ["recall", "true positive", "false negative"],
    },
    "KC_EVAL_SAMP_003": {
        "name": "k-Fold Cross Validation",
        "terms": ["cross-validation", "cross validation", "fold", "hyper-parameter", "hyperparameter"],
        "expected": ["cross-validation", "fold", "training", "testing"],
    },
}

step54_sets = sorted(
    root.glob("data/processed/kc_evidence_packs/_sets/step54_role_eligibility_v2_r10_*_step5_4_kc_evidence_packs_set.json")
)
if not step54_sets:
    raise SystemExit("No Step 5.4 v2 regression set found.")

step54_set = step54_sets[-1]
step54_obj = load_json(step54_set)
packs_path = root / step54_obj["artifacts"]["kc_evidence_packs_jsonl"]
stats_path = root / step54_obj["artifacts"]["evidence_pack_stats_json"]
packs = read_jsonl(packs_path)
packs_by_kc = {row.get("kc_id"): row for row in packs}

step53_ptr = root / "data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt"
raw = step53_ptr.read_text(encoding="utf-8").strip()
raw_path = Path(raw)
if raw_path.is_absolute():
    step53_set = raw_path
else:
    direct = root / raw_path
    sibling = root / "data/processed/kc_evidence_recalibrated/_sets" / raw_path.name
    step53_set = direct if direct.exists() else sibling

if not step53_set.exists():
    candidates = sorted((root / "data/processed/kc_evidence_recalibrated/_sets").glob("*_step5_3_kc_evidence_recalibrated_set.json"))
    if not candidates:
        raise SystemExit("No Step 5.3 set manifest found.")
    step53_set = candidates[-1]

step53_obj = load_json(step53_set)
step53_candidates_path = root / step53_obj["artifacts"]["kc_evidence_candidates_recalibrated_jsonl"]
step53_rows = read_jsonl(step53_candidates_path)

print("STEP54_SET =", step54_set.as_posix())
print("STEP54_PACKS =", packs_path.as_posix())
print("STEP54_STATS =", stats_path.as_posix())
print("STEP53_SET =", step53_set.as_posix())
print("STEP53_CANDIDATES =", step53_candidates_path.as_posix())
print("STEP53_TOTAL_ROWS =", len(step53_rows))

audit = {
    "step54_set": step54_set.as_posix(),
    "step54_packs": packs_path.as_posix(),
    "step54_stats": stats_path.as_posix(),
    "step53_set": step53_set.as_posix(),
    "step53_candidates": step53_candidates_path.as_posix(),
    "targets": {},
}

positive_roles = [
    "definition_kernel",
    "explanatory_gloss",
    "formula_notation",
    "scope_condition",
    "context_completion",
    "example_or_procedure",
]

print()
print("==== exact Step 5.4 positive support by target ====")

for kc_id, spec in targets.items():
    pack = packs_by_kc.get(kc_id) or {}
    q = pack.get("pack_quality") or {}
    slots = pack.get("slots") or {}

    print()
    print("=" * 120)
    print("KC =", kc_id, "|", spec["name"])
    print("route =", q.get("route"))
    print("insufficient_reasons =", q.get("insufficient_reasons"))
    print("definition_anchor_natural_language =", q.get("definition_anchor_natural_language"))

    positive = {}
    for role in positive_roles:
        items = slots.get(role) or []
        positive[role] = []
        if items:
            print()
            print("ROLE =", role)
        for item in items:
            txt = " ".join(str(item.get("text") or item.get("quote") or item.get("candidate_text") or "").split())
            positive[role].append(txt)
            print("  -", txt[:700])

    audit["targets"].setdefault(kc_id, {})["step54"] = {
        "canonical_name": spec["name"],
        "route": q.get("route"),
        "insufficient_reasons": q.get("insufficient_reasons"),
        "definition_anchor_natural_language": q.get("definition_anchor_natural_language"),
        "positive_slots": positive,
    }

print()
print("==== Step 5.3 same-KC candidate inspection ====")

for kc_id, spec in targets.items():
    same = [r for r in step53_rows if str(r.get("kc_id")) == kc_id]
    print()
    print("=" * 120)
    print("KC =", kc_id, "|", spec["name"])
    print("SAME_KC_CANDIDATE_COUNT =", len(same))

    same_sorted = sorted(
        same,
        key=lambda r: (
            score_of(r) is None,
            -(float(score_of(r)) if isinstance(score_of(r), (int, float)) else 0.0),
        ),
    )

    same_payload = []
    for i, row in enumerate(same_sorted[:18], start=1):
        txt = text_of(row)
        print()
        print("SAME_KC_ROW", i)
        print("score =", score_of(row))
        print("refs =", row_ref(row))
        print("text =", txt[:900])
        same_payload.append({
            "rank": i,
            "score": score_of(row),
            "refs": row_ref(row),
            "text": txt,
        })

    audit["targets"].setdefault(kc_id, {})["step53_same_kc_top"] = same_payload

print()
print("==== Step 5.3 cross-KC phrase recall inspection ====")

for kc_id, spec in targets.items():
    hits, total = compact_hits(step53_rows, spec["terms"], limit=15)

    print()
    print("=" * 120)
    print("KC =", kc_id, "|", spec["name"])
    print("PHRASE_TERMS =", spec["terms"])
    print("CROSS_KC_HIT_COUNT =", total)

    hit_payload = []
    for i, row in enumerate(hits, start=1):
        txt = text_of(row)
        print()
        print("PHRASE_HIT", i)
        print("score =", score_of(row))
        print("refs =", row_ref(row))
        print("text =", txt[:900])
        hit_payload.append({
            "rank": i,
            "score": score_of(row),
            "refs": row_ref(row),
            "text": txt,
        })

    audit["targets"].setdefault(kc_id, {})["step53_cross_kc_phrase_hits"] = {
        "terms": spec["terms"],
        "total": total,
        "top_hits": hit_payload,
    }

print()
print("==== try broader sentence-overlay search if local sentence overlay exists ====")

sentence_files = []
for base in [
    root / "data/processed/retrieval_sentence_overlay",
    root / "data/processed/sentence_overlay",
    root / "data/processed/retrieval_index",
]:
    if base.exists():
        sentence_files.extend(base.glob("**/*.jsonl"))

sentence_files = [p for p in sentence_files if p.is_file()]
print("SENTENCE_JSONL_FILE_COUNT =", len(sentence_files))

sentence_audit = {}
max_rows_to_scan_per_file = 250000

for kc_id, spec in targets.items():
    collected = []
    total_hits = 0

    for path in sentence_files[:20]:
        scanned = 0
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    scanned += 1
                    if scanned > max_rows_to_scan_per_file:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    txt = text_of(row)
                    if contains_any(txt, spec["terms"]):
                        total_hits += 1
                        if len(collected) < 12:
                            collected.append({
                                "file": path.as_posix(),
                                "refs": row_ref(row),
                                "text": txt,
                            })
        except Exception as e:
            continue

    sentence_audit[kc_id] = {
        "terms": spec["terms"],
        "total_hits_seen": total_hits,
        "top_hits": collected,
    }

    print()
    print("=" * 120)
    print("KC =", kc_id, "|", spec["name"])
    print("SENTENCE_OVERLAY_HITS_SEEN =", total_hits)
    for i, hit in enumerate(collected, start=1):
        print()
        print("SENTENCE_HIT", i)
        print("file =", hit["file"])
        print("refs =", hit["refs"])
        print("text =", hit["text"][:900])

audit["sentence_overlay_search"] = sentence_audit

out = root / "data/work/cache/diagnostics" / f"step54_v2_upstream_recall_audit_{step54_set.stem}.json"
out.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

print()
print("AUDIT_JSON =", out.as_posix())
print("STEP54_V2_UPSTREAM_RECALL_AUDIT_OK")
PY
