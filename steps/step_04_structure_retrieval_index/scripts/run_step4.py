from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from kc_l.retrieval.build.page_patches import build_page_patches, write_jsonl


# -----------------------------
# Small IO helpers (stdlib)
# -----------------------------

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()

def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def read_jsonl_head(path: Path, n: int = 3) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for _ in range(n):
            line = f.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def now_run_id(step_tag: str) -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S") + f"_{step_tag}"

def resolve_active_set(active_txt: Path) -> Path:
    name = read_text(active_txt)
    if not name:
        raise RuntimeError(f"ACTIVE set pointer is empty: {active_txt}")
    p = Path(name)
    return p if p.is_absolute() else (active_txt.parent / p)

def iter_string_values(d: Dict[str, Any]) -> Iterable[str]:
    for v in d.values():
        if isinstance(v, str) and v.strip():
            yield v.strip()

def find_dir_containing(required_files: List[str], candidates: List[Path]) -> Optional[Path]:
    for c in candidates:
        if not c.exists() or not c.is_dir():
            continue
        if all((c / fn).exists() for fn in required_files):
            return c
    return None

def iter_files_recursive(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


# -----------------------------
# Audit writer (stdlib)
# -----------------------------

class Audit:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.logs_dir = run_dir / "logs"
        self.cfg_dir = run_dir / "config"
        self.env_dir = run_dir / "env"
        self.manifests_dir = run_dir / "manifests"
        self.timings_dir = run_dir / "timings"
        ensure_dir(self.logs_dir)
        ensure_dir(self.cfg_dir)
        ensure_dir(self.env_dir)
        ensure_dir(self.manifests_dir)
        ensure_dir(self.timings_dir)
        self.log_path = self.logs_dir / "run.log"
        self._log_f = self.log_path.open("w", encoding="utf-8")
        self.t0 = time.time()

    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        self._log_f.write(line + "\n")
        self._log_f.flush()

    def close(self) -> None:
        self._log_f.close()

    def write_invocation(self) -> None:
        inv = {
            "argv": sys.argv,
            "cwd": str(Path.cwd()),
            "python_executable": sys.executable,
            "timestamp_local": datetime.now().isoformat(timespec="seconds"),
        }
        (self.run_dir / "invocation.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")

    def write_env(self) -> None:
        sysinfo = {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        }
        (self.env_dir / "system.json").write_text(json.dumps(sysinfo, indent=2), encoding="utf-8")

        pyinfo = {
            "python_version": sys.version,
            "python_version_info": list(sys.version_info),
        }
        (self.env_dir / "python.json").write_text(json.dumps(pyinfo, indent=2), encoding="utf-8")

        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                check=False,
            )
            (self.env_dir / "pip_freeze.txt").write_text(r.stdout, encoding="utf-8")
            if r.stderr.strip():
                (self.env_dir / "pip_freeze.stderr.txt").write_text(r.stderr, encoding="utf-8")
        except Exception as e:
            (self.env_dir / "pip_freeze.error.txt").write_text(repr(e), encoding="utf-8")

    def write_config_snapshot(self, config_path: Path) -> None:
        snap = self.cfg_dir / config_path.name
        snap.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        meta = {
            "config_path": str(config_path),
            "snapshot_path": str(snap),
            "sha256": sha256_file(snap),
        }
        (self.cfg_dir / "config_snapshot.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def write_input_manifest(self, paths: List[Path]) -> None:
        items = []
        for p in paths:
            exists = p.exists()
            item: Dict[str, Any] = {
                "path": str(p),
                "exists": exists,
                "is_file": p.is_file() if exists else False,
                "size_bytes": None,
                "mtime": None,
                "sha256": None,
            }
            if exists and p.is_file():
                st = p.stat()
                item["size_bytes"] = st.st_size
                item["mtime"] = st.st_mtime
                item["sha256"] = sha256_file(p)
            items.append(item)
        (self.manifests_dir / "input_manifest.json").write_text(json.dumps(items, indent=2), encoding="utf-8")

    def write_output_manifest(self, roots: List[Path]) -> None:
        files: List[Path] = []
        for r in roots:
            if r.exists():
                files.extend(list(iter_files_recursive(r)))
        files_sorted = sorted({str(p): p for p in files}.values(), key=lambda p: str(p))

        items = []
        for p in files_sorted:
            st = p.stat()
            items.append({
                "path": str(p),
                "size_bytes": st.st_size,
                "mtime": st.st_mtime,
                "sha256": sha256_file(p),
            })
        (self.manifests_dir / "output_manifest.json").write_text(json.dumps(items, indent=2), encoding="utf-8")

    def write_timing(self) -> None:
        elapsed = time.time() - self.t0
        (self.timings_dir / "elapsed_seconds.json").write_text(json.dumps({"elapsed_seconds": elapsed}, indent=2), encoding="utf-8")


# -----------------------------
# Step4 runner
# -----------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    return ap.parse_args()

def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(str(config_path))

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    stage = str(cfg.get("stage", "preflight")).strip().lower()

    active_step3 = Path(cfg["inputs"]["active_step3_set"])
    active_step3_6 = Path(cfg["inputs"]["active_step3_6_set"])
    canonical_blocks_filename = str(cfg["inputs"]["canonical_blocks_filename"])

    dry_run = bool(cfg.get("run", {}).get("dry_run", True))
    strict = bool(cfg.get("run", {}).get("strict", True))
    allow = set(cfg.get("run", {}).get("doc_id_allowlist") or [])

    if stage != "preflight" and dry_run:
        raise RuntimeError(f"Config has dry_run=true but stage={stage}. Set run.dry_run=false for non-preflight stages.")

    run_id = now_run_id("step4")
    run_dir = Path("data") / "runs" / run_id
    ensure_dir(run_dir)

    audit = Audit(run_dir)
    processed_outputs_written: List[Path] = []

    try:
        audit.log(f"STEP4 starting | stage={stage}")
        audit.write_invocation()
        audit.write_env()
        audit.write_config_snapshot(config_path)

        step3_set_path = resolve_active_set(active_step3)
        step3_6_set_path = resolve_active_set(active_step3_6)

        audit.log(f"ACTIVE_STEP3_SET -> {step3_set_path}")
        audit.log(f"ACTIVE_STEP3_6_SET -> {step3_6_set_path}")

        step3_set = read_json(step3_set_path)
        step3_6_set = read_json(step3_6_set_path)

        docs3 = step3_set.get("docs")
        docs36 = step3_6_set.get("docs")
        if not isinstance(docs3, list) or not isinstance(docs36, list):
            raise RuntimeError("Set manifest missing docs[] list (expected key: 'docs')")

        map3 = {d["doc_id"]: d for d in docs3 if isinstance(d, dict) and "doc_id" in d}
        map36 = {d["doc_id"]: d for d in docs36 if isinstance(d, dict) and "doc_id" in d}

        doc_ids = sorted(set(map3.keys()) & set(map36.keys()))
        if allow:
            doc_ids = [d for d in doc_ids if d in allow]
        if not doc_ids:
            raise RuntimeError("No overlapping doc_ids between Step3 and Step3.6 sets")

        req_step3 = ["doctree.json", "page_index.jsonl"]
        req_step36 = [canonical_blocks_filename, "pages.jsonl"]

        resolved_rows: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        input_paths: List[Path] = [config_path, active_step3, active_step3_6, step3_set_path, step3_6_set_path]

        for doc_id in doc_ids:
            try:
                e3 = map3[doc_id]
                e36 = map36[doc_id]

                cand3 = [Path(p) for p in iter_string_values(e3)]
                cand36 = [Path(p) for p in iter_string_values(e36)]

                step3_dir = find_dir_containing(req_step3, cand3)
                step36_dir = find_dir_containing(req_step36, cand36)

                if step3_dir is None:
                    raise FileNotFoundError(f"Could not find Step3 dir containing {req_step3} in set entry values")
                if step36_dir is None:
                    raise FileNotFoundError(f"Could not find Step3.6 dir containing {req_step36} in set entry values")

                doctree_json = step3_dir / "doctree.json"
                page_index_jsonl = step3_dir / "page_index.jsonl"
                blocks_jsonl = step36_dir / canonical_blocks_filename
                pages_jsonl = step36_dir / "pages.jsonl"

                blocks_head = read_jsonl_head(blocks_jsonl, n=3)
                pages_head = read_jsonl_head(pages_jsonl, n=3)

                resolved_rows.append({
                    "doc_id": doc_id,
                    "step3_dir": str(step3_dir),
                    "step3_6_dir": str(step36_dir),
                    "blocks_keys": sorted(list(blocks_head[0].keys())) if blocks_head else [],
                    "pages_keys": sorted(list(pages_head[0].keys())) if pages_head else [],
                })

                input_paths.extend([doctree_json, page_index_jsonl, blocks_jsonl, pages_jsonl])

            except Exception as e:
                failures.append({"doc_id": doc_id, "error": repr(e)})

        seen = set()
        uniq_inputs: List[Path] = []
        for p in input_paths:
            sp = str(p)
            if sp in seen:
                continue
            seen.add(sp)
            uniq_inputs.append(p)

        audit.write_input_manifest(uniq_inputs)

        audit.log(f"strict={strict} docs_ok={len(resolved_rows)} docs_fail={len(failures)}")
        for r in resolved_rows:
            audit.log(f"OK {r['doc_id']} | step3={r['step3_dir']} | step3_6={r['step3_6_dir']}")
        for f in failures[:10]:
            audit.log(f"FAIL {f['doc_id']} | {f['error']}")

        if failures and strict:
            raise RuntimeError(f"Preflight failed for {len(failures)} docs (strict=true). See logs/run.log")

        if stage == "patches":
            processed_root = Path(cfg["outputs"]["processed_root"])
            ensure_dir(processed_root)

            for r in resolved_rows:
                doc_id = r["doc_id"]
                step3_dir = Path(r["step3_dir"])
                step3_6_dir = Path(r["step3_6_dir"])

                doctree_json = step3_dir / "doctree.json"
                page_index_jsonl = step3_dir / "page_index.jsonl"
                pages_jsonl = step3_6_dir / "pages.jsonl"
                blocks_jsonl = step3_6_dir / canonical_blocks_filename

                out_dir = processed_root / doc_id / run_id
                ensure_dir(out_dir)

                patches, patch_summary, reveal_rows = build_page_patches(
                    doc_id=doc_id,
                    doctree_json=doctree_json,
                    page_index_jsonl=page_index_jsonl,
                    pages_jsonl=pages_jsonl,
                    blocks_jsonl=blocks_jsonl,
                    cfg=cfg,
                )

                write_jsonl(out_dir / "page_patch_index.jsonl", patches)
                write_jsonl(out_dir / "page_reveal_groups.jsonl", reveal_rows)
                (out_dir / "patch_summary.json").write_text(json.dumps(patch_summary, indent=2), encoding="utf-8")

                processed_outputs_written.append(out_dir)
                audit.log(f"WROTE patches for {doc_id} -> {out_dir}")

        elif stage == "preflight":
            pass
        else:
            raise RuntimeError(f"Unknown stage: {stage}")

        step_label = "4.1_preflight" if stage == "preflight" else "4.2_patches"
        summary = {
            "run_id": run_id,
            "step": step_label,
            "stage": stage,
            "dry_run": dry_run,
            "strict": strict,
            "canonical_blocks_filename": canonical_blocks_filename,
            "active_step3_set": str(active_step3),
            "active_step3_6_set": str(active_step3_6),
            "step3_set_path": str(step3_set_path),
            "step3_6_set_path": str(step3_6_set_path),
            "n_docs_ok": len(resolved_rows),
            "n_docs_fail": len(failures),
            "resolved": resolved_rows,
            "failures": failures,
            "processed_outputs": [str(p) for p in processed_outputs_written],
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        audit.write_output_manifest(processed_outputs_written)
        audit.log("STEP4 complete")
        audit.write_timing()

    finally:
        audit.close()

if __name__ == "__main__":
    main()