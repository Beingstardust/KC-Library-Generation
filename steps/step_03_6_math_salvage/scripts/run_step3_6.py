from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

from kc_l.audit.run_audit import RunAudit
from kc_l.math_salvage.pipeline import run_step3_6_for_doc
from kc_l.utils.fs import ensure_dir

def load_yaml(p: Path) -> Dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def load_active_set(sets_dir: Path, active_file: Path) -> Dict[str, Any]:
    name = active_file.read_text(encoding="utf-8").strip()
    return json.loads((sets_dir / name).read_text(encoding="utf-8"))

def resolve_pdf_path(step2_out_dir: Path, fallback_raw_pdfs_dir: Path) -> Path:
    """
    Prefer doc_manifest.json if available, else match by sanitized name in raw_pdfs_dir.
    """
    m = step2_out_dir / "doc_manifest.json"
    if m.exists():
        obj = json.loads(m.read_text(encoding="utf-8"))
        for k in ["pdf_abs_path", "pdf_path", "source_pdf"]:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                p = Path(v)
                if p.exists():
                    return p

        rel = obj.get("pdf_relpath")
        if isinstance(rel, str) and rel.strip():
            p = (Path(obj.get("repo_root", "")) / rel) if obj.get("repo_root") else (fallback_raw_pdfs_dir / Path(rel).name)
            if p.exists():
                return p

    # fallback: scan raw_pdfs_dir and match by filename stem presence
    pdfs = sorted(fallback_raw_pdfs_dir.glob("*.pdf"))
    if len(pdfs) == 1:
        return pdfs[0]
    raise RuntimeError(f"Cannot resolve pdf path from {step2_out_dir}. Add pdf_abs_path to doc_manifest.json.")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--doc-id", default=None)
    ap.add_argument("--raw-pdfs-dir", default="data/raw/pdfs")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_yaml(cfg_path)

    audit = RunAudit.from_config(cfg=cfg, step_name="step3_6", config_path=cfg_path)
    with audit:
        step3_5_set = load_active_set(
            Path(cfg["input"]["step3_5_sets_dir"]),
            Path(cfg["input"]["step3_5_active_set_file"]),
        )

        run_id = audit.run_dir.name
        out_root = Path(cfg["output"]["processed_dir"])
        sets_root = Path(cfg["output"]["sets_dir"])
        ensure_dir(out_root)
        ensure_dir(sets_root)

        raw_pdfs_dir = Path(args.raw_pdfs_dir)

        docs = step3_5_set["docs"]
        if args.doc_id:
            docs = [d for d in docs if d["doc_id"] == args.doc_id]
            if not docs:
                raise RuntimeError(f"doc_id not found in step3_5 set: {args.doc_id}")

        per_doc = []
        for d in docs:
            doc_id = d["doc_id"]
            enriched_out_dir = Path(d["enriched_out_dir"])
            step2_out_dir = Path(d["step2_out_dir"])

            pdf_path = resolve_pdf_path(step2_out_dir, raw_pdfs_dir)

            out_dir = out_root / doc_id / run_id
            ensure_dir(out_dir)

            summary = run_step3_6_for_doc(
                doc_id=doc_id,
                enriched_out_dir=enriched_out_dir,
                step2_out_dir=step2_out_dir,
                pdf_path=pdf_path,
                out_dir=out_dir,
                audit_logs_dir=audit.logs_dir,
                cfg=cfg,
            )

            per_doc.append({
                "doc_id": doc_id,
                "run_id_step3_6": run_id,
                "math_out_dir": str(out_dir).replace("\\", "/"),
                "enriched_out_dir": d["enriched_out_dir"],
                "step2_out_dir": d["step2_out_dir"],
                "summary": summary,
            })

        set_id = f"{run_id}_step3_6_set"
        set_path = sets_root / f"{set_id}.json"
        set_obj = {
            "set_id": set_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "timezone": cfg.get("project", {}).get("timezone", "Europe/Amsterdam"),
            "step": "step3_6",
            "input_step3_5_set": Path(cfg["input"]["step3_5_active_set_file"]).read_text(encoding="utf-8").strip(),
            "docs": per_doc,
        }
        set_path.write_text(json.dumps(set_obj, indent=2, ensure_ascii=False), encoding="utf-8")
        (sets_root / "ACTIVE_STEP3_6_SET.txt").write_text(set_path.name, encoding="utf-8")

        print("\nSTEP3.6 COMPLETE")
        print(json.dumps({"run_id": run_id, "set_path": str(set_path).replace("\\", "/"), "n_docs": len(per_doc)}, indent=2))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())