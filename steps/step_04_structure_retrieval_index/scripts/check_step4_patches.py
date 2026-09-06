import json
from pathlib import Path

RUN_ID = "2026-03-04_132157_step4"
DOCS = [
    "DM2_1_Classification_Unit_DTs",
    "DM2_1_Classification_Unit_NB",
    "DM2_1_Classification_Unit_Underpinnings",
    "DM2_2_Clustering_Silhouette",
    "DM2_2_Clustering_withSilhouetteSlide_removed",
    "DM2_DataEng_3_FeatureSelection_HANDOUT",
    "DM2_Evaluation_Unit_1_Basics",
    "DM2_Evaluation_Unit_2_Bestmodel",
]

def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def main():
    rows = []
    any_fail = False

    for doc_id in DOCS:
        base = Path("data/processed/retrieval_index") / doc_id / RUN_ID
        summ_p = base / "patch_summary.json"
        idx_p = base / "page_patch_index.jsonl"

        if not summ_p.exists():
            rows.append((doc_id, "MISSING patch_summary.json"))
            any_fail = True
            continue
        if not idx_p.exists():
            rows.append((doc_id, "MISSING page_patch_index.jsonl"))
            any_fail = True
            continue

        s = load_json(summ_p)
        n_pages = int(s["n_pages"])
        counts = s.get("patch_type_counts", {}) or {}

        w1 = int(counts.get("window_1", -1))
        w2 = int(counts.get("window_2", -1))
        w3 = int(counts.get("window_3", -1))

        exp_w1 = n_pages
        exp_w2 = n_pages - 1 if n_pages >= 2 else 0
        exp_w3 = n_pages - 2 if n_pages >= 3 else 0

        ok_w = (w1 == exp_w1) and (w2 == exp_w2) and (w3 == exp_w3)

        # cue coverage sample: percent patches with non-empty title_cues
        total = 0
        nonempty = 0
        with idx_p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                rec = json.loads(line)
                cues = rec.get("title_cues") or []
                if isinstance(cues, list) and len(cues) > 0:
                    nonempty += 1
        cue_ratio = (nonempty / total) if total else 0.0

        # reveal sanity
        canon = int(s.get("canonical_pages", -1))
        noncanon = int(s.get("noncanonical_pages", -1))
        rg = int(s.get("n_reveal_groups", -1))
        ok_r = (canon + noncanon == n_pages) and (rg <= n_pages)

        status = []
        if not ok_w:
            status.append(f"WINDOW_FAIL got({w1},{w2},{w3}) exp({exp_w1},{exp_w2},{exp_w3})")
        if not ok_r:
            status.append(f"REVEAL_FAIL canon={canon} noncanon={noncanon} groups={rg} n_pages={n_pages}")

        if status:
            any_fail = True
            rows.append((doc_id, " | ".join(status), n_pages, total, cue_ratio))
        else:
            rows.append((doc_id, "OK", n_pages, total, cue_ratio))

    print("\nDOC_ID\tSTATUS\tn_pages\tn_patches\tcue_nonempty_ratio")
    for r in rows:
        if len(r) == 2:
            print(f"{r[0]}\t{r[1]}")
        else:
            print(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t{r[4]:.3f}")

    if any_fail:
        raise SystemExit(2)

if __name__ == "__main__":
    main()