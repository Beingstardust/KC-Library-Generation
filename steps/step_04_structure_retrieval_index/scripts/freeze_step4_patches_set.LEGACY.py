import json
from pathlib import Path
from datetime import datetime

RUN_ID = "2026-03-04_150415_step4"

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

def main():
    sets_dir = Path("data/processed/retrieval_index/_sets")
    sets_dir.mkdir(parents=True, exist_ok=True)

    docs = []
    for doc_id in DOCS:
        out_dir = Path("data/processed/retrieval_index") / doc_id / RUN_ID
        req = [
            out_dir / "page_patch_index.jsonl",
            out_dir / "page_reveal_groups.jsonl",
            out_dir / "patch_summary.json",
        ]
        missing = [str(p) for p in req if not p.exists()]
        if missing:
            raise RuntimeError(f"Missing required Step4.2 outputs for {doc_id}: {missing}")

        docs.append({
            "doc_id": doc_id,
            "patches_run_id": RUN_ID,
            "patches_out_dir": str(out_dir),
            "page_patch_index": str(out_dir / "page_patch_index.jsonl"),
            "page_reveal_groups": str(out_dir / "page_reveal_groups.jsonl"),
            "patch_summary": str(out_dir / "patch_summary.json"),
        })

    set_id = datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_step4_patches_set"
    set_path = sets_dir / f"{set_id}.json"
    payload = {
        "set_id": set_id,
        "kind": "step4_patches",
        "created_local": datetime.now().isoformat(timespec="seconds"),
        "run_id": RUN_ID,
        "docs": docs,
    }
    set_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    active = sets_dir / "ACTIVE_STEP4_PATCHES_SET.txt"
    active.write_text(set_path.name, encoding="utf-8")

    print("WROTE", set_path)
    print("UPDATED", active, "->", set_path.name)

if __name__ == "__main__":
    main()