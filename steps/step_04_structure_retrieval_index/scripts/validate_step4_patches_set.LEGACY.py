# save as: steps/step_04_structure_retrieval_index/scripts/validate_step4_patches_set.py
import json
from pathlib import Path

ACTIVE = Path("data/processed/retrieval_index/_sets/ACTIVE_STEP4_PATCHES_SET.txt")

def pick(d: dict, keys):
    for k in keys:
        if k in d and d[k]:
            return d[k]
    return None

def main() -> int:
    if not ACTIVE.exists():
        print(f"FAIL: missing {ACTIVE}")
        return 2

    rel = ACTIVE.read_text(encoding="utf-8").strip()
    set_path = (ACTIVE.parent / rel).resolve()
    print(f"ACTIVE -> {rel}")
    if not set_path.exists():
        print(f"FAIL: set json not found: {set_path}")
        return 2

    data = json.loads(set_path.read_text(encoding="utf-8"))

    docs = data.get("docs") or data.get("documents") or data.get("by_doc") or data.get("items")
    if docs is None:
        print("FAIL: cannot find docs container in set json (expected one of: docs/documents/by_doc/items)")
        print(f"Top-level keys: {sorted(list(data.keys()))}")
        return 2

    # Normalize to iterable of (doc_id, entry)
    entries = []
    if isinstance(docs, dict):
        for doc_id, entry in docs.items():
            entries.append((doc_id, entry))
    elif isinstance(docs, list):
        for entry in docs:
            doc_id = entry.get("doc_id") or entry.get("id") or entry.get("name")
            if not doc_id:
                print("FAIL: doc entry missing doc_id/id/name")
                return 2
            entries.append((doc_id, entry))
    else:
        print(f"FAIL: docs container has unexpected type: {type(docs)}")
        return 2

    expected_docs = 8
    print(f"Docs in set: {len(entries)} (expected {expected_docs})")

    required_names = ["page_patch_index.jsonl", "page_reveal_groups.jsonl", "patch_summary.json"]

    failures = 0
    for doc_id, entry in entries:
        out_dir = pick(entry, ["patches_out_dir", "out_dir", "dir", "path"])
        if out_dir:
            out_dir = Path(out_dir)
        # Try explicit paths first
        p_patch = pick(entry, ["page_patch_index", "page_patch_index_path", "page_patch_index_jsonl"])
        p_groups = pick(entry, ["page_reveal_groups", "page_reveal_groups_path", "page_reveal_groups_jsonl"])
        p_sum = pick(entry, ["patch_summary", "patch_summary_path"])

        paths = []
        for p in [p_patch, p_groups, p_sum]:
            if p:
                paths.append(Path(p))
            else:
                paths.append(None)

        # If explicit paths missing, derive from out_dir
        derived = []
        if out_dir:
            derived = [out_dir / n for n in required_names]

        # Build final candidates per file
        candidates = []
        for i, name in enumerate(required_names):
            cands = []
            if paths[i] is not None:
                cands.append(paths[i])
            if derived:
                cands.append(derived[i])
            candidates.append((name, cands))

        missing = []
        found = []
        for name, cands in candidates:
            ok = False
            for c in cands:
                if c.exists():
                    ok = True
                    found.append(str(c))
                    break
            if not ok:
                missing.append(name)

        if missing:
            failures += 1
            print(f"FAIL [{doc_id}]: missing {missing}")
            if out_dir:
                print(f"  out_dir={out_dir}")
        else:
            print(f"OK   [{doc_id}]")

    if failures:
        print(f"\nFAIL: {failures} doc(s) missing required artifacts.")
        return 2

    print("\nPASS: set json lists docs and all required artifacts exist.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())