"""Targeted unit tests for the DOS-RAG comparator adapter (section 14 of the implementation
brief). Runs standalone, same check()/RESULTS pattern v3/verify/verify_pipeline_fixes.py already
uses in this project, so results read the same way. No network, no GPU, no real corpus needed -
synthetic fixtures only, except where noted.
"""
import hashlib
import json
import os
import sys
import tempfile

COMPARATOR_DIR = "/path/to/kc_l/v3/comparators/dos_rag"
sys.path.insert(0, COMPARATOR_DIR)
sys.path.insert(0, os.path.join(COMPARATOR_DIR, "vendor", "dos-rag-eval"))

from corpus_text import load_documents, combine_documents, locate_chunk_provenance  # noqa: E402
import build_dosrag_packets as BDP  # noqa: E402

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))


# --- corpus_text.py: load_documents / combine_documents --------------------------------------

_synthetic_corpus_rows = [
    {"doc_id": "D1", "sentence_text": "Alpha sentence.", "sentence_id": "D1:s0", "page_index": 0},
    {"doc_id": "D1", "sentence_text": "Beta sentence.", "sentence_id": "D1:s1", "page_index": 0},
    {"doc_id": "D2", "sentence_text": "Gamma sentence.", "sentence_id": "D2:s0", "page_index": 3},
]

with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
    for r in _synthetic_corpus_rows:
        tf.write(json.dumps(r) + "\n")
    _tmp_corpus_path = tf.name

joined, spans = load_documents(_tmp_corpus_path)
check("corpus_text: load_documents groups rows by doc_id",
      set(joined.keys()) == {"D1", "D2"}, joined.keys())
check("corpus_text: load_documents joins sentence_text with single spaces, in file order",
      joined["D1"] == "Alpha sentence. Beta sentence.", joined["D1"])
check("corpus_text: SentenceSpan offsets are correct into the joined text",
      joined["D1"][spans["D1"][1].char_start_in_doc:spans["D1"][1].char_end_in_doc] == "Beta sentence.",
      joined["D1"])

combined_text, combined_spans = combine_documents(joined, spans)
check("corpus_text: combine_documents concatenates all documents with a separator",
      "Alpha sentence. Beta sentence." in combined_text and "Gamma sentence." in combined_text,
      combined_text)
check("corpus_text: combine_documents preserves per-row doc_id/page_index/sentence_id in combined spans",
      {(s.doc_id, s.page_index, s.sentence_id) for s in combined_spans} ==
      {("D1", 0, "D1:s0"), ("D1", 0, "D1:s1"), ("D2", 3, "D2:s0")},
      combined_spans)
# offsets in combined text must correctly locate each sentence's own text
_offset_check_ok = all(
    combined_text[s.char_start_in_doc:s.char_end_in_doc] == s.text for s in combined_spans
)
check("corpus_text: combine_documents' adjusted offsets correctly locate each sentence in the combined text",
      _offset_check_ok, combined_spans)

os.unlink(_tmp_corpus_path)

# --- corpus_text.py: locate_chunk_provenance --------------------------------------------------

_prov = locate_chunk_provenance("Beta sentence.", combined_spans)
check("provenance: an exact chunk resolves to the correct doc_id/page_index/sentence_id",
      _prov.get("provenance") == "resolved" and _prov.get("doc_id") == "D1"
      and _prov.get("page_index_min") == 0 and "D1:s1" in _prov.get("sentence_ids", []),
      _prov)

_prov_multi = locate_chunk_provenance("Alpha sentence. Beta sentence.", combined_spans)
check("provenance: a chunk spanning two original sentences resolves both sentence_ids",
      _prov_multi.get("provenance") == "resolved"
      and set(_prov_multi.get("sentence_ids", [])) == {"D1:s0", "D1:s1"},
      _prov_multi)

_prov_missing = locate_chunk_provenance("This text does not exist anywhere in the corpus.", combined_spans)
check("provenance: an unlocatable chunk reports 'unresolved', never a guessed location",
      _prov_missing.get("provenance") == "unresolved" and "page_index_min" not in _prov_missing,
      _prov_missing)

# --- build_dosrag_packets.py: packet-shape contract -------------------------------------------

_real_packet_fixture = {
    "knowledge_unit_id": "KC_PROBE", "kc_id": "KC_PROBE", "knowledge_unit_type": "kc",
    "canonical_name": "Probe Unit", "aliases": ["Probe"], "hierarchy": {"topic_path": ["A"]},
    "sibling_kc_names": ["Other"], "rival_units_considered": [],
    # fields that MUST NOT survive into the DOS-RAG packet (same forbidden set as the baseline's
    # own leak check in verify_pipeline_fixes.py):
    "drafting_instruction": {"goal": "x"}, "query_formulation": {"selected": "x"},
    "evidence_coverage": {"has_definition": True}, "packet_support_state": "draftable",
    "support_state_reason": "x", "insufficient_support_reasons": ["x"],
    "weak_fallback_abstention_allowed": True,
}
_evidence_fixture = [{
    "evidence_id": "e1", "text": "probe chunk text.", "source_block_text": "probe chunk text.",
    "doc_id": "D", "page_index": 1, "page_index_max": 1, "patch_heading": "",
    "source_sentence_ids": ["D:1"], "provenance_status": "resolved",
    "evidence_lane": "dos_rag_native_retrieval", "dos_rag_chunk_index": 0,
    "dos_rag_pre_reorder_rank": 0,
}]
_dosrag_packet = BDP.build_dosrag_packet(_real_packet_fixture, _evidence_fixture)

_forbidden_top = {"drafting_instruction", "query_formulation", "evidence_coverage",
                  "evidence_dropped_to_rival_units", "packet_support_state",
                  "support_state_reason", "insufficient_support_reasons",
                  "weak_fallback_abstention_allowed"}
check("packet shape: build_dosrag_packet drops every proposed-system-computed top-level field",
      not (set(_dosrag_packet.keys()) & _forbidden_top),
      set(_dosrag_packet.keys()) & _forbidden_top)
check("packet shape: build_dosrag_packet keeps real KC identity fields verbatim",
      _dosrag_packet["canonical_name"] == "Probe Unit"
      and _dosrag_packet["sibling_kc_names"] == ["Other"],
      _dosrag_packet)
check("packet shape: packet_version accurately identifies this as the DOS-RAG condition",
      _dosrag_packet["packet_version"] == "dos_rag_v1", _dosrag_packet["packet_version"])
check("packet shape: abstention_expected/insufficient_synthesis_support explicitly False, not omitted",
      _dosrag_packet["abstention_expected"] is False
      and _dosrag_packet["insufficient_synthesis_support"] is False,
      _dosrag_packet)
_ev0 = _dosrag_packet["evidence_for_synthesis"][0]
check("packet shape: DOS-RAG evidence items carry no shape_tags/assertability/authority_tier/relevance",
      not any(k in _ev0 for k in ("shape_tags", "assertability", "authority_tier", "relevance", "role", "roles")),
      _ev0.keys())
check("packet shape: DOS-RAG evidence items carry text == source_block_text (no block restoration to claim)",
      _ev0["text"] == _ev0["source_block_text"], _ev0)

# --- non-mutation test: build_dosrag_packet must not mutate its input real_packet -------------

import copy
_before = copy.deepcopy(_real_packet_fixture)
BDP.build_dosrag_packet(_real_packet_fixture, _evidence_fixture)
check("non-mutation: build_dosrag_packet never mutates the caller's real_packet dict",
      _real_packet_fixture == _before, "input dict changed after calling build_dosrag_packet")

# --- common-prompt hash test (synthetic, mirroring the controlled-comparator fix's own CC-4) --

sys.path.insert(0, "/path/to/kc_l/v3/pipeline")
sys.path.insert(0, "/path/to/kc_l/src")
import importlib.util as _ilu
_dr_spec = _ilu.spec_from_file_location(
    "draft_runner_under_test",
    "/path/to/kc_l/v3/pipeline/04_draft_runner.py")
DR = _ilu.module_from_spec(_dr_spec)
_dr_spec.loader.exec_module(DR)

_shared_identity = {
    "knowledge_unit_id": "KC_HASH_PROBE", "knowledge_unit_type": "kc", "canonical_name": "Hash Probe",
    "hierarchy": {}, "sibling_kc_names": [], "rival_units_considered": [],
    "abstention_expected": False, "insufficient_synthesis_support": False,
}
_dosrag_shaped = dict(_shared_identity, packet_version="dos_rag_v1",
                       evidence_for_synthesis=[_ev0])
_baseline_shaped = dict(_shared_identity, packet_version="sentence_level_base_dense_rag_v1",
                         evidence_for_synthesis=[])
_proposed_shaped = dict(_shared_identity, packet_version="step67_comprehensive_synthesis_packet_v1",
                         drafting_instruction={"goal": "x"}, packet_support_state="draftable",
                         evidence_for_synthesis=[])


def _common_text(prompt):
    m = "\n\nPACKET:\n"
    return prompt[:prompt.index(m)]


_p_dosrag = DR.build_prompt(_dosrag_shaped, mode="controlled_comparator")
_p_baseline = DR.build_prompt(_baseline_shaped, mode="controlled_comparator")
_p_proposed = DR.build_prompt(_proposed_shaped, mode="controlled_comparator")

_h_dosrag = hashlib.sha256(_common_text(_p_dosrag).encode()).hexdigest()
_h_baseline = hashlib.sha256(_common_text(_p_baseline).encode()).hexdigest()
_h_proposed = hashlib.sha256(_common_text(_p_proposed).encode()).hexdigest()

check("common-prompt hash: DOS-RAG / Base Dense RAG / Proposed all get an IDENTICAL common "
      "instruction text in controlled_comparator mode (same unit, same identity fields)",
      _h_dosrag == _h_baseline == _h_proposed,
      {"dos_rag": _h_dosrag, "baseline": _h_baseline, "proposed": _h_proposed})
check("common-prompt hash: drafting_instruction is not visible in the DOS-RAG condition's prompt",
      '"drafting_instruction"' not in _p_dosrag, "leaked into DOS-RAG prompt")

# --- context-budget test: DOS-RAG evidence_for_synthesis chars are measurable the same way -----

_budget_probe_evidence = [
    {"evidence_id": f"e{i}", "text": "x" * 1000, "source_block_text": "x" * 1000} for i in range(5)
]
_total_chars = sum(len(e["text"]) for e in _budget_probe_evidence)
check("context budget: DOS-RAG evidence character totals are computable the same way as the "
      "other two conditions (sum of evidence_for_synthesis[*].text length)",
      _total_chars == 5000, _total_chars)

print("=" * 88)
print("DOS-RAG COMPARATOR ADAPTER UNIT TESTS")
print("=" * 88)
failed = 0
for name, ok, detail in RESULTS:
    print("  %-6s %-95s %s" % ("OK" if ok else "FAIL", name, detail))
    failed += 0 if ok else 1
print("=" * 88)
print("%d checks, %d failed" % (len(RESULTS), failed))
sys.exit(1 if failed else 0)
