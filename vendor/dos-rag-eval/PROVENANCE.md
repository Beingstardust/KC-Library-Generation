# Vendored subset of dos-rag-eval

- Source repository: https://github.com/alex-laitenberger/dos-rag-eval
- Cloned commit: `781944cddaf8382e75f76772fdb364eca98afccf` (2026-05-04 10:05:27 +0200)
- Branch: `main`
- License: MIT (`LICENSE`, this directory, copied unmodified)
- Files vendored, byte-identical to the clone (verified by `diff -q` against the original clone
  before this copy was made): `source/method/__init__.py`, `source/method/RAG.py`,
  `source/method/EmbeddingModels.py`, `source/method/QAModels.py`, `source/method/utils.py`.
- Real source-file commit history for the vendored files: `3cbca8f` (2025-04-10, "initial
  commit") is the only commit touching any of them.

## Why only these five files

`RAG.py` imports `.EmbeddingModels` and `.QAModels` (both required transitively for the module
to import at all, even though this comparator never instantiates a `QAModels` class); `utils.py`
provides `split_text()`. Nothing under `source/experiments/`, `source/data/`, or `test/` is
needed for this comparator (those are the authors' own dataset-specific experiment scripts and
QA-metric evaluation code, not part of the retrieval method itself - see
`02_DOS_RAG_REPO_AUDIT.md`'s "incidental scaffolding" analysis).

## Not modified

No line in any vendored file has been changed. All comparator-specific logic (corpus-text
reconstruction, query construction, provenance mapping, packet-shape adaptation) lives in the
sibling `v3/comparators/dos_rag/` scripts, which import these files unmodified and call only
`RAG.chunk_and_embed_document()` and `RAG.retrieve()` - never `RAG.answer_question()` or anything
in `QAModels.py`.
