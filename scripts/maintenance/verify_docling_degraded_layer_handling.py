#!/usr/bin/env python3
"""Verify blockstore_builder.py's degraded-layer handling (see ORCHESTRATOR_BUILD_STATE.md's
Docling degraded-layer-handling entry): when validation.require_each_enabled_layer_nonempty is
True and exactly one enabled layer produces zero blocks while at least one other enabled layer
succeeds, the document is tolerated (document_level_status="degraded", a specific warning naming
the layer and reason) rather than hard-failing with RuntimeError. Only genuinely catastrophic
input - ALL enabled layers empty - still raises.

Uses a REAL small PDF (built with PyMuPDF, the same library the real pymupdf layer uses) and the
REAL extract_pymupdf() function - only docling/mineru are mocked (via unittest.mock.patch), so
this exercises the real merge/validation logic in build_blockstore() directly, not a
reimplementation of it.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

import fitz  # noqa: E402

from kc_l.audit.run_audit import RunAudit  # noqa: E402
from kc_l.blockstore.schema import BlockRecord  # noqa: E402
from kc_l.parsing.blockstore_builder import build_blockstore  # noqa: E402


def _fake_block(*, doc_id: str, layer: str, block_id: str) -> BlockRecord:
    return BlockRecord(
        doc_id=doc_id, block_id=block_id, layer=layer, page_index=0,
        content_type="paragraph", text_raw="fake test content",
        bbox_pt=None, bbox_coord_system=None, raw_ref={"source": "test_fixture"},
    )


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Verification failed: {label}")


def _make_real_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Real test content for degraded-layer-handling verification.")
    doc.save(str(path))
    doc.close()


def _base_cfg(work_root: Path, pdf_path: Path, *, require_each_layer_nonempty: bool) -> dict:
    return {
        "project": {"timezone": "UTC"},
        "doc": {"doc_id": "DOC_degraded_layer_test", "pdf_path": str(pdf_path), "freeze_inputs": False},
        "output": {
            "processed_blockstore_dir": str(work_root / "blockstore"),
            "runs_dir": str(work_root / "runs"),
            "render_page_images": False,
            "use_work_dir_for_external_tools": False,
            "keep_work_dir": False,
        },
        "layers": {
            "pymupdf": {"enabled": True, "sort_text": True, "write_raw_dump": False},
            "docling": {"enabled": True},
            "mineru": {"enabled": True},
        },
        "validation": {
            "min_pages": 1,
            "min_total_blocks": 1,
            "require_each_enabled_layer_nonempty": require_each_layer_nonempty,
        },
        "logging": {},
    }


def _fake_layer(*, blocks: list, ok: bool, reason: str | None = None) -> dict:
    status = {"enabled": True, "ok": ok, "n_blocks": len(blocks)}
    if reason:
        status["reason"] = reason
    # "pages" is only read from the pymupdf layer's result (build_blockstore() does
    # py_res["pages"] unconditionally), but Case 2 mocks extract_pymupdf too, so this
    # fake must always carry the key regardless of which layer it's standing in for.
    return {"pages": [], "blocks": blocks, "layer_status": status}


def _run_build(cfg: dict, run_dir_name: str, work_root: Path) -> dict:
    cfg_snapshot_path = work_root / f"{run_dir_name}_config_snapshot.yaml"
    cfg_snapshot_path.write_text("snapshot", encoding="utf-8")
    audit = RunAudit.from_config(cfg=cfg, step_name="step2", config_path=cfg_snapshot_path)
    with audit:
        return build_blockstore(cfg=cfg, audit=audit)


def main() -> int:
    work_root = Path(__file__).resolve().parent / "_tmp_degraded_layer_test"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True)
    pdf_path = work_root / "test.pdf"
    _make_real_pdf(pdf_path)
    config_snapshot_path = work_root / "config_snapshot.txt"
    config_snapshot_path.write_text("test config snapshot placeholder", encoding="utf-8")

    try:
        print("=== Case 1: docling degraded (zero blocks), pymupdf+mineru succeed - must NOT hard-fail ===")
        cfg1 = _base_cfg(work_root, pdf_path, require_each_layer_nonempty=True)
        cfg1["doc"]["doc_id"] = "DOC_case1"
        with patch(
            "kc_l.parsing.blockstore_builder.extract_docling",
            return_value=_fake_layer(blocks=[], ok=False, reason="docling_no_json_output"),
        ), patch(
            "kc_l.parsing.blockstore_builder.extract_mineru",
            return_value=_fake_layer(blocks=[_fake_block(doc_id="DOC_case1", layer="mineru", block_id="b1")], ok=True),
        ):
            result1 = build_blockstore(cfg=cfg1, audit=RunAudit.from_config(
                cfg=cfg1, step_name="step2", config_path=config_snapshot_path,
            ))
        check("case 1 did not raise (degraded, not hard-failed)", True)
        check(
            "case 1 document_level_status is 'degraded'",
            result1["summary"]["document_level_status"] == "degraded",
        )
        warnings1 = result1["summary"]["document_level_warnings"]
        check(f"case 1 has exactly one warning (found {len(warnings1)})", len(warnings1) == 1)
        check(
            "case 1 warning names the docling layer and its real reason",
            "docling" in warnings1[0] and "docling_no_json_output" in warnings1[0],
        )
        doc_manifest_path1 = Path(result1["summary"]["paths"]["processed_out_dir"]) / "doc_manifest.json"
        doc_manifest1 = json.loads(doc_manifest_path1.read_text(encoding="utf-8"))
        check(
            "doc_manifest.json on disk also records document_level_status='degraded'",
            doc_manifest1["document_level_status"] == "degraded",
        )
        check(
            "doc_manifest.json's warnings match the summary's",
            doc_manifest1["document_level_warnings"] == warnings1,
        )
        check(
            "real pymupdf layer (not mocked) contributed real, non-empty blocks",
            result1["summary"]["blocks_by_layer"].get("pymupdf", 0) > 0,
        )

        print("\n=== Case 2: ALL enabled layers empty - must still hard-fail (nothing to salvage) ===")
        cfg2 = _base_cfg(work_root, pdf_path, require_each_layer_nonempty=True)
        cfg2["doc"]["doc_id"] = "DOC_case2"
        cfg2["validation"]["min_total_blocks"] = 0  # isolate the all-empty-layers check specifically
        cfg2["validation"]["min_pages"] = 0  # pymupdf is mocked empty too, so pages=0 as well
        with patch(
            "kc_l.parsing.blockstore_builder.extract_pymupdf",
            return_value=_fake_layer(blocks=[], ok=False, reason="pymupdf_test_forced_empty"),
        ), patch(
            "kc_l.parsing.blockstore_builder.extract_docling",
            return_value=_fake_layer(blocks=[], ok=False, reason="docling_no_json_output"),
        ), patch(
            "kc_l.parsing.blockstore_builder.extract_mineru",
            return_value=_fake_layer(blocks=[], ok=False, reason="mineru_test_forced_empty"),
        ):
            try:
                build_blockstore(cfg=cfg2, audit=RunAudit.from_config(
                    cfg=cfg2, step_name="step2", config_path=config_snapshot_path,
                ))
                check("case 2 raised RuntimeError (all layers empty, nothing to salvage)", False)
            except RuntimeError as exc:
                check(f"case 2 raised RuntimeError as expected ({exc})", "ALL enabled layers produced zero blocks" in str(exc))

        print("\n=== Case 3: baseline, all layers succeed - status must be 'ok', no warnings ===")
        cfg3 = _base_cfg(work_root, pdf_path, require_each_layer_nonempty=True)
        cfg3["doc"]["doc_id"] = "DOC_case3"
        with patch(
            "kc_l.parsing.blockstore_builder.extract_docling",
            return_value=_fake_layer(blocks=[_fake_block(doc_id="DOC_case3", layer="docling", block_id="b2")], ok=True),
        ), patch(
            "kc_l.parsing.blockstore_builder.extract_mineru",
            return_value=_fake_layer(blocks=[_fake_block(doc_id="DOC_case3", layer="mineru", block_id="b3")], ok=True),
        ):
            result3 = build_blockstore(cfg=cfg3, audit=RunAudit.from_config(
                cfg=cfg3, step_name="step2", config_path=config_snapshot_path,
            ))
        check("case 3 document_level_status is 'ok'", result3["summary"]["document_level_status"] == "ok")
        check("case 3 has zero warnings", len(result3["summary"]["document_level_warnings"]) == 0)

        print("\n=== Case 4: flag disabled (require_each_enabled_layer_nonempty=False) - old behavior preserved ===")
        cfg4 = _base_cfg(work_root, pdf_path, require_each_layer_nonempty=False)
        cfg4["doc"]["doc_id"] = "DOC_case4"
        with patch(
            "kc_l.parsing.blockstore_builder.extract_docling",
            return_value=_fake_layer(blocks=[], ok=False, reason="docling_no_json_output"),
        ), patch(
            "kc_l.parsing.blockstore_builder.extract_mineru",
            return_value=_fake_layer(blocks=[_fake_block(doc_id="DOC_case4", layer="mineru", block_id="b4")], ok=True),
        ):
            result4 = build_blockstore(cfg=cfg4, audit=RunAudit.from_config(
                cfg=cfg4, step_name="step2", config_path=config_snapshot_path,
            ))
        check(
            "case 4 (flag off) document_level_status stays 'ok' - flag genuinely gates this",
            result4["summary"]["document_level_status"] == "ok",
        )

    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    print("\nALL DOCLING DEGRADED-LAYER HANDLING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
