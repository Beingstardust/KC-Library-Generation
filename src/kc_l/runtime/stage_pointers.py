from __future__ import annotations

from pathlib import Path

from kc_l.runtime.layout import REPO_ROOT


def _resolve_repo_path(raw_path: str | Path, *, repo_root: Path | None = None) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    root = (repo_root or REPO_ROOT).resolve()
    return (root / path).resolve()


def _looks_absolute(text: str) -> bool:
    # POSIX absolute (the real Cluster B target) or Windows drive-letter absolute (a dev checkout).
    # Path.is_absolute alone is not enough: Windows treats a POSIX path like "/path/to/shared"
    # as root-relative-but-driveless (not absolute), which is exactly the join bug found
    # earlier in resolve_repo_path - detect it explicitly here instead of repeating that bug.
    if text.startswith("/"):
        return True
    if len(text) >= 2 and text[1] == ":":
        return True
    return False


def write_pointer(pointer_path: str | Path, target_path: str | Path, *, repo_root: Path | None = None) -> Path:
    """Write an ACTIVE_*/BEST_* pointer as a single-line absolute path - the convention this
    orchestrator uses for anything it writes itself (matching the step5x v3 BEST-pointer
    format, the most recently-established convention among the several found in this repo).
    """
    path = _resolve_repo_path(pointer_path, repo_root=repo_root)
    target = _resolve_repo_path(target_path, repo_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(target) + "\n", encoding="utf-8")
    return path


def resolve_pointer(
    pointer_path: str | Path,
    *,
    key: str | None = None,
    repo_root: Path | None = None,
    require_exists: bool = True,
) -> Path:
    """Resolve any of the three ACTIVE_*/BEST_* pointer conventions found in this repo:

    1. Legacy filename-only (e.g. data/processed/blockstore/_sets/ACTIVE_STEP2_SET.txt):
       a single line naming a file in the pointer's own directory.
    2. Absolute-path single-line (e.g. BEST_STEP5X_FINAL_SANITIZED_GAPAWARE_SET.txt): a single
       line that is already a fully-resolved path - used verbatim, never joined with the
       pointer's directory.
    3. Multi-line KEY=VALUE closeout (e.g. BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt,
       BEST_STEP68_V2_REVIEW_PACKETS_FROM_POSTPROCESSED_SOURCE.txt): a closeout receipt with
       several named artifact paths. Requires `key` (e.g. key="REVIEW_PACKETS_JSONL") to say
       which value to extract.
    """
    path = _resolve_repo_path(pointer_path, repo_root=repo_root)
    if not path.exists():
        raise FileNotFoundError(f"Pointer file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Pointer file is empty: {path}")

    lines = text.splitlines()
    is_multiline_kv = len(lines) > 1 and any("=" in line for line in lines)

    if is_multiline_kv:
        if key is None:
            raise ValueError(f"Pointer file is a multi-line KEY=VALUE closeout, key= is required: {path}")
        kv = dict(line.split("=", 1) for line in lines if "=" in line)
        if key not in kv:
            raise KeyError(f"Key {key!r} not found in pointer file {path} (available: {sorted(kv)})")
        raw_value = kv[key].strip()
    else:
        raw_value = lines[0].strip()

    target_path = Path(raw_value) if _looks_absolute(raw_value) else (path.parent / raw_value).resolve()

    if require_exists and not target_path.exists():
        raise FileNotFoundError(f"Pointer target does not exist: {path} -> {target_path}")
    return target_path
