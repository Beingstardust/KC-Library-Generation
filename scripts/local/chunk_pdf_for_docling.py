from __future__ import annotations

import argparse
import json
from pathlib import Path
from pypdf import PdfReader, PdfWriter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-pdf", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--pages-per-chunk", type=int, default=100)
    args = ap.parse_args()

    input_pdf = Path(args.input_pdf).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.pages_per_chunk <= 0:
        raise ValueError("--pages-per-chunk must be > 0")

    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)

    stem = input_pdf.stem
    manifest = {
        "source_pdf": str(input_pdf),
        "source_stem": stem,
        "total_pages": total_pages,
        "pages_per_chunk": args.pages_per_chunk,
        "chunks": [],
    }

    chunk_idx = 0
    for start0 in range(0, total_pages, args.pages_per_chunk):
        end0 = min(start0 + args.pages_per_chunk, total_pages)
        start1 = start0 + 1
        end1 = end0

        writer = PdfWriter()
        for p in range(start0, end0):
            writer.add_page(reader.pages[p])

        chunk_name = f"{stem}_p{start1:04d}-{end1:04d}.pdf"
        chunk_path = output_dir / chunk_name
        with chunk_path.open("wb") as f:
            writer.write(f)

        manifest["chunks"].append(
            {
                "chunk_index": chunk_idx,
                "page_start_1based": start1,
                "page_end_1based": end1,
                "page_count": end0 - start0,
                "chunk_pdf": str(chunk_path),
                "chunk_pdf_name": chunk_name,
                "expected_docling_json": f"{chunk_path.stem}.json",
            }
        )
        chunk_idx += 1

    manifest_path = output_dir / "chunk_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"INPUT_PDF={input_pdf}")
    print(f"TOTAL_PAGES={total_pages}")
    print(f"PAGES_PER_CHUNK={args.pages_per_chunk}")
    print(f"CHUNK_COUNT={len(manifest['chunks'])}")
    print(f"MANIFEST={manifest_path}")


if __name__ == "__main__":
    main()
