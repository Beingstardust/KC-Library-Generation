"""Batch re-verification that every source citation in every committed reference record still
resolves in the corpus. The console already refuses unresolvable sentence_ids at commit time
(cmd_cite/cmd_provenance call corpus.resolve before accepting anything), so this exists as an
independent after-the-fact audit - e.g. to catch a citation that resolved against a corpus file
that has since been (incorrectly) replaced. Any unresolved citation found here is a hard failure,
per the reference-construction spec (section 7).

Run: python validate_reference_provenance.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus_search import CorpusIndex

BASE = Path(__file__).parent
COMMITTED_DIR = BASE / "committed"
CORPUS_PATH = BASE.parent / "corpus_support" / "sentence_corpus.jsonl"


def validate_all() -> dict:
    corpus = CorpusIndex(str(CORPUS_PATH))
    failures = []
    n_records = 0
    n_citations = 0
    for p in sorted(COMMITTED_DIR.glob("*.json")):
        n_records += 1
        rec = json.loads(p.read_text(encoding="utf-8"))
        kc_id = rec["kc_id"]

        for ref in rec.get("source_first_review", {}).get("source_refs", []):
            n_citations += 1
            sid = ref["sentence_id"]
            if not corpus.resolve(sid):
                failures.append({"kc_id": kc_id, "stage": "source_first_review", "sentence_id": sid})

        for entry in rec.get("expert_edit", {}).get("reference_provenance", []):
            for sid in entry.get("source_refs", []):
                n_citations += 1
                if not corpus.resolve(sid):
                    failures.append({"kc_id": kc_id, "stage": "expert_edit.reference_provenance",
                                      "sentence_id": sid, "claim": entry.get("claim")})

    return {
        "n_committed_records": n_records,
        "n_citations_checked": n_citations,
        "n_unresolved": len(failures),
        "failures": failures,
        "result": "PASS" if not failures else "FAIL",
    }


if __name__ == "__main__":
    result = validate_all()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["result"] == "PASS" else 1)
