from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.topic import build_topic_draft_bundle


DEFAULT_OVERLAY = Path("data/processed/hierarchy_overlay/2026-03-10_005659_hierarchy_overlay/hierarchy_overlay.jsonl")
DEFAULT_APPROVED_MANIFEST = Path(
    "data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/approved_reviewed_library_manifest.json"
)
DEFAULT_APPROVED_LIBRARY = Path(
    "data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/approved_reviewed_library_frozen.jsonl"
)
DEFAULT_ACTIVE_STEP4_POINTER = Path("data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt")
DEFAULT_BLOCKSTORE_ROOT = Path("data/processed/blockstore")
DEFAULT_OUT_ROOT = Path("data/processed/topic_library_draft_restarted")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _latest_run_dir(doc_root: Path) -> Path:
    candidates = sorted(path for path in doc_root.iterdir() if path.is_dir())
    if not candidates:
        raise FileNotFoundError(f"No blockstore runs found under {doc_root}")
    return candidates[-1]


def _clean_line(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-")
    return re.sub(r"\s+", " ", text.strip())


def _extract_doc_title(blocks: list[dict[str, Any]], doc_id: str) -> str:
    block_texts: list[str] = []
    for block in blocks:
        if int(block.get("page_index", 0)) != 0:
            continue
        text = _clean_line(str(block.get("text_raw", "")))
        if not text or "Myra Spiliopoulou" in text or re.search(r"\b\d+ / \d+\b", text):
            continue
        block_texts.append(text)
    if not block_texts:
        return doc_id
    preferred = [text for text in block_texts if "block" in text.lower() or "unit" in text.lower()]
    if preferred:
        return " | ".join(preferred[:2])
    return block_texts[0]


def _load_active_doc_ids(pointer_path: Path) -> tuple[list[str], Path]:
    manifest_name = pointer_path.read_text(encoding="utf-8").strip()
    manifest_path = pointer_path.parent / manifest_name
    manifest = read_json(manifest_path)
    doc_ids = sorted((manifest.get("docs") or {}).keys())
    preferred = "DM2_2_Clustering_withSilhouetteSlide_removed"
    obsolete = "DM2_2_Clustering_Silhouette"
    if preferred in doc_ids and obsolete in doc_ids:
        doc_ids = [doc_id for doc_id in doc_ids if doc_id != obsolete]
    return doc_ids, manifest_path


def _load_blocks(doc_ids: list[str], blockstore_root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], list[str]]:
    blocks_by_doc: dict[str, list[dict[str, Any]]] = {}
    doc_titles: dict[str, str] = {}
    exact_paths: list[str] = []
    for doc_id in doc_ids:
        run_dir = _latest_run_dir(blockstore_root / doc_id)
        blocks_path = run_dir / "blocks.jsonl"
        rows = [row for row in read_jsonl(blocks_path) if row.get("layer") == "pymupdf"]
        blocks_by_doc[doc_id] = rows
        doc_titles[doc_id] = _extract_doc_title(rows, doc_id)
        exact_paths.append(str(blocks_path).replace("\\", "/"))
    return blocks_by_doc, doc_titles, exact_paths


def _build_schema_payload(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "topic_library.minimal_schema.v1",
        "object_type": "topic_draft",
        "separate_from": "kc_library",
        "preserves_typed_distinction": True,
        **schema,
    }


def _build_schema_rationale() -> str:
    return """# Topic Schema Rationale

## Kept fields
- `topic_id`: required so topic drafts remain a separate addressable object family from KC ids.
- `topic_title`: required because slide headings and hierarchy labels reliably support a topic name.
- `topic_level`: kept because the hierarchy overlay already supplies a stable topic depth.
- `parent_topic_id`: kept to preserve hierarchy without flattening topics into the KC library.
- `draft_definition`: kept but optional-in-content because some slides contain definition-grade statements while many only provide headings.
- `draft_scope_role`: kept because agenda lines and section headings often ground what the topic covers even when no definition is present.
- `outline_children`: kept because parent topics already expose topic children in the overlay and leaf topics sometimes expose agenda/section breakdowns.
- `source_refs`: kept for page/block-level provenance and auditability.
- `source_units`: kept as a lightweight doc/unit rollup so cross-unit topics can stay honest without copying large evidence dumps.
- `draft_flags`: kept to mark weak support, alias bridging, cross-unit aggregation, and branch/source ambiguities explicitly.

## Rejected fields
- `aliases`: rejected for now because the slide corpus does not justify stable human-facing alternate names for every topic.
- `prerequisites`: rejected because the slides do not support a trustworthy prerequisite graph.
- `misconceptions`: rejected because the current corpus is not a misconception-oriented teaching source.
- `assessment_cues`: rejected because the slides do not reliably expose assessment intent.
- `confidence_score`: rejected because a numeric score would imply precision the current evidence does not support.
- `typed_links`: rejected from the core schema because topic-to-KC links remain a separate optional artifact.
- `kc_specific_criteria`: rejected and untouched by design.
"""


def _build_naming_note() -> str:
    return """# Knowledge Library Naming Note

`Knowledge Library` should remain the umbrella term only.

Within that umbrella, keep two separate typed collections:
- `Topic Library`: broader contextual or hierarchical topic nodes.
- `KC Library`: fine-grained approved knowledge components.

This pass does not rename or rewrite any existing KC artifacts. The new topic outputs stay in a separate topic-library path, with a separate schema and separate ids, so later typed links can be added without collapsing topics and KCs into one flat library.
"""


def _build_report(bundle: dict[str, Any], branch_mismatches: list[dict[str, Any]]) -> str:
    stats = bundle["stats"]
    coverage = bundle["coverage"]
    overlap_lines = [
        f"- `{row['topic_title']}` vs `{row['kc_title']}` (`{row['kc_id']}`)"
        for row in coverage["overlap_examples"]
    ]
    mismatch_lines = [f"- `{row['topic_title']}` uses source units outside its hierarchy branch label." for row in branch_mismatches]
    if not overlap_lines:
        overlap_lines = ["- No direct wording-overlap examples were surfaced automatically."]
    if not mismatch_lines:
        mismatch_lines = ["- No branch/source mismatches were detected."]
    paths = "\n".join(f"- `{path}`" for path in coverage["topic_paths"])
    return f"""# Topic Draft Report

## Chosen schema
The topic layer uses a separate minimal topic schema with only ten retained fields: `topic_id`, `topic_title`, `topic_level`, `parent_topic_id`, `draft_definition`, `draft_scope_role`, `outline_children`, `source_refs`, `source_units`, and `draft_flags`.

## Field survival and rejection
See `topic_schema_rationale.md` for the per-field keep/reject justification. The short version is that hierarchy, light drafting, and provenance survived; heavier pedagogical or inferential fields did not.

## Output counts
- Topic drafts produced: `{stats['topic_draft_count']}`
- Topic drafts with grounded definitions: `{stats['grounded_definition_count']}`
- Topic drafts with scope/role only and no grounded definition: `{stats['scope_only_count']}`
- Topic drafts marked title-only / weakly supported: `{stats['weak_title_only_count']}`

## Hierarchy coverage
All overlay topic nodes were drafted from the current slide corpus:
{paths}

## Topic/KC overlap or ambiguity
These topic drafts stay separate from the KC library. Wording overlap exists in several branches because broad topics sit above finer-grained approved KCs:
{chr(10).join(overlap_lines)}

Hierarchy/source ambiguities detected:
{chr(10).join(mismatch_lines)}

## Practical judgment
The current slides are enough for a useful lightweight topic layer, especially for hierarchy, unit coverage, and scoped navigation. They are not enough for uniformly strong topic definitions. A richer textbook rerun would mainly improve `draft_definition` coverage, reduce title-only topics, and support more stable topic-to-KC linking.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--approved_manifest", type=Path, default=DEFAULT_APPROVED_MANIFEST)
    parser.add_argument("--approved_library", type=Path, default=DEFAULT_APPROVED_LIBRARY)
    parser.add_argument("--active_step4_pointer", type=Path, default=DEFAULT_ACTIVE_STEP4_POINTER)
    parser.add_argument("--blockstore_root", type=Path, default=DEFAULT_BLOCKSTORE_ROOT)
    parser.add_argument("--out_root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    created_utc = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = args.out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    overlay_rows = read_jsonl(args.overlay)
    approved_manifest = read_json(args.approved_manifest)
    approved_rows = read_jsonl(args.approved_library)
    approved_kc_titles = {
        row["kc_id"]: row.get("title") or row.get("final_text", {}).get("title") or row.get("canonical_name", "")
        for row in approved_rows
    }

    active_doc_ids, active_set_manifest_path = _load_active_doc_ids(args.active_step4_pointer)
    blocks_by_doc, doc_titles, blockstore_paths = _load_blocks(active_doc_ids, args.blockstore_root)
    bundle = build_topic_draft_bundle(
        overlay_rows=overlay_rows,
        blocks_by_doc=blocks_by_doc,
        doc_titles=doc_titles,
        approved_kc_titles=approved_kc_titles,
    )

    schema_path = out_dir / "topic_schema_minimal.json"
    rationale_path = out_dir / "topic_schema_rationale.md"
    drafts_path = out_dir / "topic_drafts.jsonl"
    manifest_path = out_dir / "topic_draft_manifest.json"
    report_path = out_dir / "topic_draft_report.md"
    links_path = out_dir / "topic_to_kc_link_candidates.jsonl"
    naming_note_path = out_dir / "knowledge_library_naming_note.md"

    write_json(schema_path, _build_schema_payload(bundle["schema"]))
    rationale_path.write_text(_build_schema_rationale(), encoding="utf-8")
    write_jsonl(drafts_path, bundle["drafts"])
    write_jsonl(links_path, bundle["link_candidates"])
    naming_note_path.write_text(_build_naming_note(), encoding="utf-8")

    branch_mismatches = [row for row in bundle["drafts"] if "source_branch_label_mismatch" in row["draft_flags"]]
    report_path.write_text(_build_report(bundle, branch_mismatches), encoding="utf-8")

    manifest = {
        "schema_version": "topic_library.draft_manifest.v1",
        "run_id": run_id,
        "created_utc": created_utc,
        "package_status": "topic_draft_layer_emitted",
        "object_type": "topic_library_draft_bundle",
        "approved_kc_count": approved_manifest["counts"]["approved_reviewed_entries_frozen"],
        "separation_invariants": {
            "separate_topic_and_kc_layers": True,
            "kc_library_artifacts_read_only": True,
            "approved_kc_boundary_unmodified": True,
            "no_step6_7_or_6_8_rerun": True,
        },
        "inputs": {
            "current_state_files": [
                "AGENTS.md",
                "CHANGELOG.md",
                "CURRENT_ACTIVE_STATE.md",
                "Current.md",
                "Target design.md",
            ],
            "overlay_jsonl": str(args.overlay).replace("\\", "/"),
            "approved_kc_manifest": str(args.approved_manifest).replace("\\", "/"),
            "approved_kc_library": str(args.approved_library).replace("\\", "/"),
            "active_step4_pointer": str(args.active_step4_pointer).replace("\\", "/"),
            "active_step4_manifest": str(active_set_manifest_path).replace("\\", "/"),
            "active_doc_ids": active_doc_ids,
            "blockstore_jsonl_paths": blockstore_paths,
        },
        "counts": bundle["stats"],
        "outputs": {
            "topic_schema_minimal_json": str(schema_path).replace("\\", "/"),
            "topic_schema_rationale_md": str(rationale_path).replace("\\", "/"),
            "topic_drafts_jsonl": str(drafts_path).replace("\\", "/"),
            "topic_draft_manifest_json": str(manifest_path).replace("\\", "/"),
            "topic_draft_report_md": str(report_path).replace("\\", "/"),
            "topic_to_kc_link_candidates_jsonl": str(links_path).replace("\\", "/"),
            "knowledge_library_naming_note_md": str(naming_note_path).replace("\\", "/"),
        },
    }
    write_json(manifest_path, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

