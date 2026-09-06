"""Stratified sampler for the later human judge-calibration set: 30 KCs x the 5 unique primary
candidate arms (Proposed/Qwen, Proposed/Gemma, Proposed/DeepSeek, Base/Qwen, DOS/Qwen) = 150 rows.
See 07_methods/EVALUATION_METHOD_PLAN.md "Human judge calibration". NOT executed against real
candidate content anywhere - this only produces the blinded sampling plan (which KC x which arm,
in which blind order), following the existing blinding convention already used for the authority
evaluation (evaluation_suite/data/authority_human_review_blinded_mapping.jsonl: opaque
review_case_id, variant_label, unit_id, with the true arm identity kept only in the mapping file).

Stratification is by top-level topic (second path element of hierarchy_path, e.g. "Classification",
"Evaluation", "Feature Selection", "Clustering") so the 30-KC sample isn't accidentally concentrated
in one topic area. hierarchy_path/canonical_name are identity fields, not seed content (see
02_curation/reference_console.py's KCRoster - the same distinction applies here), so reading them
from 01_seed/qwen_seed.jsonl for sampling purposes does not touch anything that needs to stay hidden.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

SEED_PATH = Path(__file__).parent.parent / "01_seed" / "qwen_seed.jsonl"

PRIMARY_ARMS = ("P-Q", "P-G", "P-D", "B-Q", "DOS-Q")  # Proposed/Qwen, Proposed/Gemma, Proposed/DeepSeek, Base/Qwen, DOS/Qwen

N_KC_TARGET = 30


def load_roster_with_topic() -> list[dict]:
    rows = []
    with open(SEED_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            hp = d.get("hierarchy_path") or []
            topic = hp[1] if len(hp) > 1 else (hp[0] if hp else "UNKNOWN")
            rows.append({"kc_id": d["kc_id"], "canonical_name": d["canonical_name"], "topic": topic})
    return rows


def stratified_kc_sample(roster: list[dict], n_target: int = N_KC_TARGET, seed: int = 20260824) -> list[str]:
    by_topic: dict[str, list[str]] = defaultdict(list)
    for r in roster:
        by_topic[r["topic"]].append(r["kc_id"])
    rng = random.Random(seed)
    for ids in by_topic.values():
        rng.shuffle(ids)

    topics = sorted(by_topic.keys())
    total = sum(len(v) for v in by_topic.values())
    # proportional allocation with largest-remainder rounding so every topic with >=1 KC gets >=1 slot where possible
    raw_alloc = {t: len(by_topic[t]) / total * n_target for t in topics}
    alloc = {t: int(raw_alloc[t]) for t in topics}
    remaining = n_target - sum(alloc.values())
    remainders = sorted(topics, key=lambda t: raw_alloc[t] - alloc[t], reverse=True)
    for t in remainders[:remaining]:
        alloc[t] += 1

    sample = []
    for t in topics:
        sample.extend(by_topic[t][: alloc[t]])
    return sorted(sample)


def build_blinded_rows(kc_ids: list[str], seed: int = 20260824) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for kc_id in kc_ids:
        arm_order = list(PRIMARY_ARMS)
        rng.shuffle(arm_order)  # per-KC randomized presentation order, blocks positional anchoring
        for variant_idx, arm_id in enumerate(arm_order):
            variant_label = "ABCDE"[variant_idx]
            case_id = "HC-" + hashlib.sha256(f"{kc_id}:{arm_id}:{seed}".encode()).hexdigest()[:20]
            rows.append({
                "review_case_id": case_id,
                "variant_label": variant_label,
                "unit_id": kc_id,
                "arm_id": arm_id,  # kept ONLY in this mapping file, never shown to the blinded human reviewer
            })
    return rows


def build_sample(n_target: int = N_KC_TARGET, seed: int = 20260824) -> dict:
    roster = load_roster_with_topic()
    kc_ids = stratified_kc_sample(roster, n_target=n_target, seed=seed)
    rows = build_blinded_rows(kc_ids, seed=seed)
    return {
        "n_kc": len(kc_ids), "n_arms": len(PRIMARY_ARMS), "n_rows": len(rows),
        "kc_ids": kc_ids, "blinded_mapping": rows,
    }


if __name__ == "__main__":
    plan = build_sample()
    assert plan["n_kc"] == N_KC_TARGET, plan["n_kc"]
    assert plan["n_rows"] == N_KC_TARGET * len(PRIMARY_ARMS), plan["n_rows"]
    seen_case_ids = {r["review_case_id"] for r in plan["blinded_mapping"]}
    assert len(seen_case_ids) == plan["n_rows"], "review_case_id collision"
    print(f"OK - {plan['n_kc']} KCs x {plan['n_arms']} arms = {plan['n_rows']} blinded calibration rows")
    print("sample topics covered:", sorted({r["topic"] for r in load_roster_with_topic() if r["kc_id"] in plan["kc_ids"]}))
