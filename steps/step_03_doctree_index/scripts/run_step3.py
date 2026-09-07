from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime, timezone
import platform
import subprocess
import sys

import yaml

from kc_l.audit.run_audit import RunAudit
from kc_l.audit.manifests import build_input_manifest, build_output_manifest
from kc_l.doctree.build import load_active_step2_set, build_doctree_for_doc
from kc_l.doctree.writers import write_json, write_jsonl
from kc_l.utils.fs import ensure_dir


def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="STEP 3: Build DocTree + PageIndex from Step2 BlockStore set.")
    ap.add_argument("--config", required=True, type=str)
    ap.add_argument("--doc-id", default=None, type=str, help="Optional: process only one doc_id.")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = _load_yaml(cfg_path)

    audit = RunAudit.from_config(cfg=cfg, step_name="step3", config_path=cfg_path)
    with audit:
        step2_sets_dir = Path(cfg["input"]["step2_sets_dir"])
        active_file = Path(cfg["input"]["step2_active_set_file"])

        step2_manifest_path, step2_set = load_active_step2_set(step2_sets_dir, active_file)
        step2_set_id = Path(step2_manifest_path).name

        audit.log_kv("step2_set_manifest", str(step2_manifest_path).replace("\\", "/"))
        audit.log_kv("step2_set_id", step2_set_id)

        docs = list(step2_set.get("docs", []))
        if args.doc_id:
            docs = [d for d in docs if d.get("doc_id") == args.doc_id]

        if not docs:
            raise RuntimeError("No docs to process. Check ACTIVE_STEP2_SET.txt or --doc-id filter.")

        run_id = audit.run_dir.name
        out_root = Path(cfg["output"]["processed_doctree_dir"])
        set_root = Path(cfg["output"]["doctree_sets_dir"])
        ensure_dir(out_root)
        ensure_dir(set_root)

        # Input manifest: step2 manifest + each doc blocks/pages
        input_paths: List[Path] = [Path(step2_manifest_path)]
        for d in docs:
            step2_out = Path(d["processed_out_dir"])
            input_paths.append(step2_out / "pages.jsonl")
            input_paths.append(step2_out / "blocks.jsonl")
            input_paths.append(step2_out / "doc_manifest.json")
        (audit.run_dir / "input_manifest.step3.json").write_text(
            json.dumps(build_input_manifest(input_paths), indent=2),
            encoding="utf-8",
        )

        per_doc_rows = []
        produced_dirs: List[Path] = []

        for d in docs:
            doc_id = d["doc_id"]
            step2_out = Path(d["processed_out_dir"])

            doc_out = out_root / doc_id / run_id
            ensure_dir(doc_out)

            built = build_doctree_for_doc(doc_id=doc_id, step2_out_dir=step2_out, run_id=run_id, cfg=cfg)

            write_json(doc_out / "doctree.json", {"doc_id": doc_id, "run_id": run_id, **built["stats"], "nodes": built["nodes"], "edges": built["edges"]})
            write_jsonl(doc_out / "page_index.jsonl", built["page_index_rows"])
            write_json(doc_out / "summary.json", built["stats"])

            produced_dirs.append(doc_out)
            per_doc_rows.append(
                {
                    "doc_id": doc_id,
                    "run_id_step3": run_id,
                    "doctree_out_dir": str(doc_out).replace("\\", "/"),
                    "step2_out_dir": str(step2_out).replace("\\", "/"),
                    "n_pages": built["stats"]["n_pages"],
                    "n_nodes": built["stats"]["n_nodes"],
                    "title_coverage": built["stats"]["title_coverage"],
                }
            )

            # -------------------------
            # Run-level summary.json (root)
            # -------------------------
            run_summary = {
                "run_id": run_id,
                "step": "step3",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "input_step2_set": step2_set_id,
                "n_docs": len(per_doc_rows),
                "docs": per_doc_rows,
            }
            (audit.run_dir / "summary.json").write_text(
                json.dumps(run_summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # -------------------------
            # Environment snapshot (env/)
            # -------------------------
            env_dir = audit.run_dir / "env"
            ensure_dir(env_dir)

            env_snapshot = {
                "platform": platform.platform(),
                "python_executable": sys.executable,
                "python_version": sys.version,
            }

            # git state is optional but valuable
            try:
                head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
                dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True)
                env_snapshot["git_head"] = head
                env_snapshot["git_dirty"] = bool(dirty.strip())
                if env_snapshot["git_dirty"]:
                    env_snapshot["git_status_porcelain"] = dirty
            except Exception as e:
                env_snapshot["git_error"] = repr(e)

            (env_dir / "env_snapshot.json").write_text(
                json.dumps(env_snapshot, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            try:
                pip_freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
                (env_dir / "pip_freeze.txt").write_text(pip_freeze, encoding="utf-8")
            except Exception as e:
                (env_dir / "pip_freeze.txt").write_text(f"pip_freeze_failed: {repr(e)}", encoding="utf-8")

        # Validation: title coverage warning gate, not a hard failure unless require_all_pages fails
        min_cov = float(cfg["validation"].get("min_title_coverage", 0.0))
        allow_no_titles = bool(cfg["validation"].get("allow_pages_without_titles", True))

        low = [r for r in per_doc_rows if (r["title_coverage"] < min_cov)]
        if low and (not allow_no_titles):
            raise RuntimeError(f"Title coverage below threshold for docs: {low}")

        # Step3 set manifest
        set_id = f"{run_id}_step3_set"
        set_path = set_root / f"{set_id}.json"
        step3_set = {
            "set_id": set_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "timezone": cfg.get("project", {}).get("timezone", "Europe/Amsterdam"),
            "step": "step3",
            "input_step2_set": step2_set_id,
            "docs": per_doc_rows,
        }
        write_json(set_path, step3_set)

        # Active pointer
        active_step3 = set_root / "ACTIVE_STEP3_SET.txt"
        active_step3.write_text(set_path.name, encoding="utf-8")

        # Output manifest over all produced doctree dirs and the set file
        (audit.run_dir / "output_manifest.step3.json").write_text(
            json.dumps({"set_path": str(set_path), "produced": [str(p) for p in produced_dirs]}, indent=2),
            encoding="utf-8",
        )

        # Hash manifests for doctree outputs
        # This is heavy, but Step3 output size is small and worth hashing.
        for p in produced_dirs:
            (audit.run_dir / f"output_manifest.processed.{p.parent.name}.json").write_text(
                json.dumps(build_output_manifest(p), indent=2),
                encoding="utf-8",
            )

        print("\nSTEP3 COMPLETE")
        print(json.dumps({"run_id": run_id, "step3_set": str(set_path), "n_docs": len(per_doc_rows)}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())