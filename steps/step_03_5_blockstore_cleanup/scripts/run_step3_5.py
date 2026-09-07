from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

from kc_l.audit.run_audit import RunAudit
from kc_l.cleaning.enrich import enrich_doc
from kc_l.utils.fs import ensure_dir

def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))

def _load_active_set(sets_dir: Path, active_file: Path) -> tuple[Path, Dict[str, Any]]:
    name = active_file.read_text(encoding="utf-8").strip()
    p = sets_dir / name
    return p, json.loads(p.read_text(encoding="utf-8"))

def main() -> int:
    ap = argparse.ArgumentParser(description="STEP 3.5: MinerU-first non-destructive boilerplate tagging + QA reports.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--doc-id", default=None)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load_yaml(cfg_path)

    audit = RunAudit.from_config(cfg=cfg, step_name="step3_5", config_path=cfg_path)
    with audit:
        step2_manifest_path, step2_set = _load_active_set(
            Path(cfg["input"]["step2_sets_dir"]),
            Path(cfg["input"]["step2_active_set_file"]),
        )
        step3_manifest_path, step3_set = _load_active_set(
            Path(cfg["input"]["step3_sets_dir"]),
            Path(cfg["input"]["step3_active_set_file"]),
        )

        step2_docs = {d["doc_id"]: Path(d["processed_out_dir"]) for d in step2_set["docs"]}
        step3_docs = {d["doc_id"]: Path(d["doctree_out_dir"]) for d in step3_set["docs"]}

        if set(step2_docs.keys()) != set(step3_docs.keys()):
            raise RuntimeError(f"Step2 doc_ids != Step3 doc_ids: {set(step2_docs) ^ set(step3_docs)}")

        doc_ids = sorted(step2_docs.keys())
        if args.doc_id:
            if args.doc_id not in step2_docs:
                raise RuntimeError(f"Unknown doc_id: {args.doc_id}")
            doc_ids = [args.doc_id]

        run_id = audit.run_dir.name
        out_root = Path(cfg["output"]["processed_enriched_dir"])
        sets_root = Path(cfg["output"]["enriched_sets_dir"])
        ensure_dir(out_root)
        ensure_dir(sets_root)

        per_doc = []
        for doc_id in doc_ids:
            out_dir = out_root / doc_id / run_id
            ensure_dir(out_dir)
            summary = enrich_doc(
                doc_id=doc_id,
                step2_out_dir=step2_docs[doc_id],
                step3_out_dir=step3_docs[doc_id],
                out_dir=out_dir,
                cfg=cfg,
            )
            per_doc.append({
                "doc_id": doc_id,
                "run_id_step3_5": run_id,
                "enriched_out_dir": str(out_dir).replace("\\", "/"),
                "step2_out_dir": str(step2_docs[doc_id]).replace("\\", "/"),
                "step3_out_dir": str(step3_docs[doc_id]).replace("\\", "/"),
                "summary": summary,
            })

        # Step 3.5 set manifest
        set_id = f"{run_id}_step3_5_set"
        set_path = sets_root / f"{set_id}.json"
        set_obj = {
            "set_id": set_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "timezone": cfg.get("project", {}).get("timezone", "Europe/Amsterdam"),
            "step": "step3_5",
            "input_step2_set": step2_manifest_path.name,
            "input_step3_set": step3_manifest_path.name,
            "docs": per_doc,
        }
        set_path.write_text(json.dumps(set_obj, indent=2, ensure_ascii=False), encoding="utf-8")
        (sets_root / "ACTIVE_STEP3_5_SET.txt").write_text(set_path.name, encoding="utf-8")

        print("\nSTEP3.5 COMPLETE")
        print(json.dumps({
            "run_id": run_id,
            "set_path": str(set_path).replace("\\", "/"),
            "n_docs": len(per_doc),
        }, indent=2))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())