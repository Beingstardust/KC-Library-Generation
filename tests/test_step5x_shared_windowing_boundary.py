from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            out.append((node.module or "", node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, node.lineno))
    return out


def test_step5x_v3_uses_shared_windowing_for_generic_surface_utilities():
    candidate_bank = REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "evidence_stage_v3_candidate_bank.py"
    scored = REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "evidence_stage_v3_scored_candidates.py"

    candidate_imports = _imports(candidate_bank)
    scored_imports = _imports(scored)

    candidate_modules = {module for module, _ in candidate_imports}
    scored_modules = {module for module, _ in scored_imports}

    assert "kc_l.retrieval_windowing.semantic" in candidate_modules
    assert "kc_l.retrieval_windowing.source_surface_fallback" in candidate_modules
    assert "kc_l.retrieval_windowing.semantic" in scored_modules

    forbidden = {
        "kc_l.retrieval_gate.semantic",
        "kc_l.retrieval_gate.source_surface_fallback",
    }

    assert not (candidate_modules & forbidden), candidate_modules & forbidden
    assert not (scored_modules & forbidden), scored_modules & forbidden


def test_retrieval_gate_generic_modules_are_compatibility_wrappers():
    wrapper_files = [
        REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "semantic.py",
        REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "text_normalize.py",
        REPO_ROOT / "src" / "kc_l" / "retrieval_gate" / "source_surface_fallback.py",
    ]

    for path in wrapper_files:
        text = path.read_text(encoding="utf-8")
        assert "Compatibility wrapper" in text
        assert "kc_l.retrieval_windowing" in text

        tree = ast.parse(text, filename=str(path))
        function_defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        class_defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]

        assert function_defs == [], (path, function_defs)
        assert class_defs == [], (path, class_defs)


def test_retrieval_windowing_does_not_import_retrieval_gate():
    windowing_dir = REPO_ROOT / "src" / "kc_l" / "retrieval_windowing"
    offenders = []

    for path in sorted(windowing_dir.glob("*.py")):
        for module, line_no in _imports(path):
            if module == "kc_l.retrieval_gate" or module.startswith("kc_l.retrieval_gate."):
                offenders.append((str(path.relative_to(REPO_ROOT)), line_no, module))

    assert offenders == [], offenders


def test_compatibility_imports_still_resolve():
    from kc_l.retrieval_gate.semantic import match_normalize, tokenize
    from kc_l.retrieval_gate.source_surface_fallback import (
        SOURCE_SURFACE_FALLBACK,
        build_source_surface_fallback_candidates,
    )
    from kc_l.retrieval_gate.text_normalize import normalize_ws

    assert match_normalize(" Bayes Theorem ") == "bayes theorem"
    assert tokenize("Naive Bayes Classifier")
    assert normalize_ws("a   b") == "a b"
    assert SOURCE_SURFACE_FALLBACK == "source_surface_fallback"
    assert callable(build_source_surface_fallback_candidates)


def main():
    test_step5x_v3_uses_shared_windowing_for_generic_surface_utilities()
    test_retrieval_gate_generic_modules_are_compatibility_wrappers()
    test_retrieval_windowing_does_not_import_retrieval_gate()
    test_compatibility_imports_still_resolve()
    print("TEST_STEP5X_SHARED_WINDOWING_BOUNDARY_OK")


if __name__ == "__main__":
    main()
