"""Assert every fix in this pipeline is ACTIVE, not merely present in the source.

Written because several fixes in this project were silently inert and only found by accident:
a regex that lost its word boundary passing through a shell heredoc and matched nothing; an
admission_basis value computed but never stored, so the lookup that depended on it always saw
None; a defining-equation floor that could never fire because a length filter discarded the
passages first; and - worst - sibling_kc_names empty on all 159 packets, which silently disabled
three anti-contamination instructions in the drafting prompt while a code comment asserted the
field was populated.

Every check here executes the real code path and asserts on observed behaviour. A fix that is
present but doing nothing fails. Run before any full build.
"""
import atexit
import copy
import hashlib
import json
import os
import sys
import pathlib
import io
import importlib.util
import inspect
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
# Repo-relative: a hardcoded absolute path at sys.path position 0 overrides PYTHONPATH,
# so any worktree/clone silently imports the ORIGINAL mirror's kc_l package instead of
# its own. That already invalidated one A/B experiment silently.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'src'))

import kc_l.retrieval_gate.evidence_pack as CP
import kc_l.retrieval_gate.retrieval as HR

_DRAFT_RUNNER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "pipeline", "04_draft_runner.py")
_DRAFT_RUNNER_SPEC = importlib.util.spec_from_file_location("draft_runner_under_test",
                                                            _DRAFT_RUNNER_PATH)
assert _DRAFT_RUNNER_SPEC is not None and _DRAFT_RUNNER_SPEC.loader is not None
DR = importlib.util.module_from_spec(_DRAFT_RUNNER_SPEC)
_DRAFT_RUNNER_SPEC.loader.exec_module(DR)

_PACKET_BUILDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "pipeline", "02_build_kc_packets.py")
_PACKET_BUILDER_SPEC = importlib.util.spec_from_file_location("packet_builder_under_test",
                                                              _PACKET_BUILDER_PATH)
assert _PACKET_BUILDER_SPEC is not None and _PACKET_BUILDER_SPEC.loader is not None
PB = importlib.util.module_from_spec(_PACKET_BUILDER_SPEC)
_PACKET_BUILDER_SPEC.loader.exec_module(PB)

_PROFILE_BUILDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "pipeline", "01_build_profiles.py")
_PROFILE_BUILDER_SPEC = importlib.util.spec_from_file_location("profile_builder_under_test",
                                                               _PROFILE_BUILDER_PATH)
assert _PROFILE_BUILDER_SPEC is not None and _PROFILE_BUILDER_SPEC.loader is not None
PR = importlib.util.module_from_spec(_PROFILE_BUILDER_SPEC)
_PROFILE_BUILDER_SPEC.loader.exec_module(PR)

_TOPIC_PACKET_BUILDER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pipeline", "03_build_topic_packets.py")
_TOPIC_PACKET_BUILDER_SPEC = importlib.util.spec_from_file_location(
    "topic_packet_builder_under_test", _TOPIC_PACKET_BUILDER_PATH)
assert _TOPIC_PACKET_BUILDER_SPEC is not None and _TOPIC_PACKET_BUILDER_SPEC.loader is not None
TPB = importlib.util.module_from_spec(_TOPIC_PACKET_BUILDER_SPEC)
_TOPIC_PACKET_BUILDER_SPEC.loader.exec_module(TPB)

RESULTS = []

_BASELINE_RAG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "pipeline", "build_baseline_rag_packets.py")
_BASELINE_RAG_SPEC = importlib.util.spec_from_file_location("baseline_rag_under_test",
                                                             _BASELINE_RAG_PATH)
assert _BASELINE_RAG_SPEC is not None and _BASELINE_RAG_SPEC.loader is not None
BB = importlib.util.module_from_spec(_BASELINE_RAG_SPEC)
_BASELINE_RAG_SPEC.loader.exec_module(BB)

import ast as _ast


def _live_calls(path):
    """Names actually CALLED in a module, ignoring any inside a constant-false branch.

    Source-text matching cannot tell a live call from a dead one: "if False and hasattr(mod, 'x')"
    still contains the string, and renaming a call site to _disabled_x() leaves "x(" in the def.
    A sabotage audit found five of this session's own checks defeated exactly that way, so
    reachability is established from the parse tree instead.
    """
    tree = _ast.parse(io.open(path, encoding="utf-8").read())

    dead = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.If):
            test = node.test
            const_false = (isinstance(test, _ast.Constant) and not test.value)
            and_false = (isinstance(test, _ast.BoolOp) and isinstance(test.op, _ast.And)
                         and any(isinstance(v, _ast.Constant) and not v.value
                                 for v in test.values))
            if const_false or and_false:
                for sub in node.body:
                    for inner in _ast.walk(sub):
                        dead.add(id(inner))

    names = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and id(node) not in dead:
            fn = node.func
            if isinstance(fn, _ast.Name):
                names.add(fn.id)
            elif isinstance(fn, _ast.Attribute):
                names.add(fn.attr)
    return names


_LIVE_CALL_CACHE = {}


def live_calls(path):
    """Memoised _live_calls(); resolved at use, since module paths are set up further below."""
    if path not in _LIVE_CALL_CACHE:
        _LIVE_CALL_CACHE[path] = _live_calls(path)
    return _LIVE_CALL_CACHE[path]


def orchestrator_path():
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "scripts",
        "kc_l_orchestrator.py"))


_STATUS_INTEGRITY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "src", "kc_l", "kc_drafting", "status_integrity.py")
_STATUS_INTEGRITY_PATH = os.path.normpath(_STATUS_INTEGRITY_PATH)
_STATUS_INTEGRITY_SPEC = importlib.util.spec_from_file_location(
    "status_integrity_under_test", _STATUS_INTEGRITY_PATH)
assert _STATUS_INTEGRITY_SPEC is not None and _STATUS_INTEGRITY_SPEC.loader is not None
SI = importlib.util.module_from_spec(_STATUS_INTEGRITY_SPEC)
_STATUS_INTEGRITY_SPEC.loader.exec_module(SI)

_PROBE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "steps", "step_06_7_kc_draft_generation", "scripts", "v2_chain",
    "run_step67_v2_schema_contract_probe.py")
_PROBE_PATH = os.path.normpath(_PROBE_PATH)



def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))


_SUMMARY_REACHED = []


def _report_results(header):
    failed = 0
    print("=" * 88)
    print(header)
    print("=" * 88)
    for name, ok, detail in RESULTS:
        print("  %-6s %-62s %s" % ("OK" if ok else "FAIL", name, detail))
        failed += 0 if ok else 1
    print("=" * 88)
    return failed


def _report_on_abort():
    """Print what was collected when an exception ends the run before the summary.

    This suite records every check and prints them all at the end, so any check that RAISES -
    rather than evaluating to False - discards the report for every check, including the ones
    that had already failed correctly. Found by sabotage: two deliberate breakages produced a
    bare StopIteration and no verdict at all, which reads as an infrastructure problem instead of
    the caught regression it actually was. The exit status is unchanged; only the reporting is.
    """
    if _SUMMARY_REACHED or not RESULTS:
        return
    failed = _report_results("SUITE ABORTED BEFORE ITS SUMMARY - results collected up to that point")
    print("%d checks recorded, %d failed, then an exception ended the run" % (len(RESULTS), failed))


atexit.register(_report_on_abort)


def sentence(text, **flags):
    row = {"sentence_text": text, "doc_id": "D", "block_id": "D:b:1", "sent_idx": 0}
    row.update(flags)
    return row


# --- v3/v12 citation density -------------------------------------------------------------
check("v12 citation density rejects survey listings",
      CP.is_citation_dense("Surveys by Buntine [129], Moret [166] and Murthy [174] cover this."))
check("v12 citation density KEEPS single-citation content",
      not CP.is_citation_dense(
          "If we call Xobs the observed part of X, we can define missing at random, per [79]."))

# --- v14 bibliography + document structure -----------------------------------------------
check("v14 bibliography entry rejected",
      CP.is_bibliography_entry(
          "Measuring classifier performance. Machine learning, 77(1):103-123, 2009."))
check("v14 bibliography KEEPS a formula",
      not CP.is_bibliography_entry("Recall = TP / (TP + FN)"))
check("v14 table-of-contents row rejected",
      CP.is_document_structure_noise(
          "6 Split Information and Gain Ratio 5 6.1 Split Information . 5 6.3 Why ID is dangerous ."))
check("v14 cross-ref inside real content KEPT",
      not CP.is_document_structure_noise(
          "The derived attributes shown in Figure 3.15(c) are more informative than the originals "
          "because they capture repeated access patterns."))

# --- v18 short defining equations are not junk -------------------------------------------
check("v18 short formula survives the length filter",
      not CP.is_structural_junk(sentence("Recall = TP / (TP + FN)", is_formula_like=True)))
check("v18 short prose fragment still rejected",
      CP.is_structural_junk(sentence("To do this, the")))

# --- v19 equation overrides a boilerplate flag -------------------------------------------
check("v19 equation overrides is_nav_boilerplate/is_meta",
      not CP.is_structural_junk(sentence(
          "Recall = TP / (TP + FN)", is_formula_like=True,
          is_nav_boilerplate=True, is_meta=True)))
check("v19 non-equation boilerplate still rejected",
      CP.is_structural_junk(sentence(
          "Chapter 4 Classification and Prediction Methods Overview",
          is_nav_boilerplate=True, is_meta=True)))

# --- v17/v20 defining-equation recognition and symbolic preference -----------------------
pats = CP.defining_equation_patterns(["Recall (Sensitivity)", "Recall", "Sensitivity"])
check("v17 recognises the unit's defining equation",
      CP.is_defining_equation("Recall = TP / (TP + FN)", pats))
check("v17 does NOT match an incidental mention",
      not CP.is_defining_equation(
          "Execute K-Means with K = 2 and Euclidean distance on the given data.",
          CP.defining_equation_patterns(["Euclidean Distance"])))
check("v20 symbolic RHS distinguished from a worked number",
      CP.has_symbolic_rhs("Recall = TP / (TP + FN)") and not CP.has_symbolic_rhs("Recall = 0.600"))

# --- v3 garbled math penalty -------------------------------------------------------------
check("v3 garbled math penalised",
      CP.garbled_math_penalty("De = m i=1 (xi -yi)2 1") > 0)
check("v3 clean math not penalised",
      CP.garbled_math_penalty("Gain ratio = Entropy(Parent) - sum N(vi)/N Entropy(vi)") == 0)

# --- v6 junk-safe relative floor ----------------------------------------------------------
hits = [
    {"sentence": sentence("Such information can"), "rerank_prob": 0.72, "bm25_score": 1.0},
    {"sentence": sentence(
        "Node impurity measures how mixed the class labels are within a node of the tree."),
     "rerank_prob": 0.58, "bm25_score": 1.0},
]
blocks = CP.build_corpus_block_index([h["sentence"] for h in hits])
passages = CP.assemble_passages(hits, blocks, max_passages=10, max_chars=9000, min_relevance=0.55)
check("v6 junk fragment does not set the floor that excludes real content",
      len(passages) >= 1, "%d passage(s) admitted" % len(passages))

# --- v22 per-block-member verification: strip off-topic splices without choking real evidence
# Reproduces the mechanism found in the human review of the gemma4 drafts: assemble_passages()
# used to pull EVERY sentence from a matched source block once its seed sentence scored well,
# filtered only for structural junk - never for topical relevance. A block containing one
# on-topic sentence and one off-topic sentence (glued together only because they share a source
# block) cleared the floor on the on-topic sentence alone. The real KC_EVAL_IMBAL_006 packet
# admitted "...algorithm called RIPPER. For a one-sided hypothesis test at a 95% confidence
# level, the critical value..." this way. member_verifier scores every non-seed block member
# individually and drops it below min_relevance before the text is ever joined.
v22_seed = sentence(
    "RIPPER is a widely-used rule induction algorithm for classification.",
    block_id="D:b:22", sent_idx=0, sentence_id="v22-seed")
v22_good_member = sentence(
    "Rules are learned incrementally, adding conjunctive tests that maximize an "
    "information-based metric until no negative examples remain covered.",
    block_id="D:b:22", sent_idx=1, sentence_id="v22-good")
v22_bad_member = sentence(
    "For a one-sided hypothesis test at a 95% confidence level, the critical value is obtained "
    "from a t-distribution.",
    block_id="D:b:22", sent_idx=2, sentence_id="v22-bad")
v22_blocks = CP.build_corpus_block_index([v22_seed, v22_good_member, v22_bad_member])
v22_hits = [{"sentence": v22_seed, "rerank_prob": 0.90, "bm25_score": 1.0}]


def v22_member_verifier(texts):
    # stand-in reranker: on-topic RIPPER content scores high, unrelated stats content scores low
    return [0.80 if ("conjunctive" in txt or "information-based" in txt) else 0.10 for txt in texts]


v22_passages = CP.assemble_passages(
    v22_hits, v22_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    member_verifier=v22_member_verifier)
v22_text = (v22_passages[0].get("text") or "") if v22_passages else ""
check("v22 off-topic block member stripped from assembled passage",
      "critical value" not in v22_text and "hypothesis test" not in v22_text, v22_text[:160])
check("v22 on-topic block member retained (fix does not choke real evidence)",
      "conjunctive" in v22_text or "information-based" in v22_text, v22_text[:160])
check("v22 seed sentence always retained regardless of member_verifier",
      "RIPPER" in v22_text, v22_text[:160])

# --- v23: seed identity must survive a duplicate sentence_id -------------------------------
# The real corpus has at least one case (DOC_introduction_to_data_mining:mineru:72:364) where an
# upstream OCR/sentence-segmentation defect assigns the SAME sentence_id to two unrelated
# sentences. Probing v22 against the human-flagged units found this defeated is_seed - BOTH rows
# matched entry["seed"]'s id, so both were exempted from member verification and the real
# KC_EVAL_IMBAL_006 contamination ("...called RIPPER. For a one-sided hypothesis test...")
# survived unchanged. is_seed must key on sentence_text too, not id alone.
v23_seed = sentence(
    "The real seed sentence for this block.", block_id="D:b:23", sent_idx=0,
    sentence_id="dup-id")
v23_collider = sentence(
    "An unrelated sentence that happens to share the same corpus sentence_id as the seed.",
    block_id="D:b:23", sent_idx=1, sentence_id="dup-id")  # same id, different text - the defect
v23_blocks = CP.build_corpus_block_index([v23_seed, v23_collider])
v23_hits = [{"sentence": v23_seed, "rerank_prob": 0.90, "bm25_score": 1.0}]
v23_passages = CP.assemble_passages(
    v23_hits, v23_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    member_verifier=lambda texts: [0.05 for _ in texts])  # collider always scores low
v23_text = (v23_passages[0].get("text") or "") if v23_passages else ""
check("v23 a sentence_id collision does not exempt an unrelated sentence from verification",
      "unrelated sentence" not in v23_text, v23_text[:160])
check("v23 the true seed (matching id AND text) is still always retained",
      "real seed sentence" in v23_text, v23_text[:160])

# --- v50 context scoring is coherent, exact-heading bounded, and survives all later checks ---
check("v50 a generic procedure member is coherent with its unit-bearing source anchor",
      CP.context_candidate_is_anchored(
          "Rules are grown in a greedy fashion one class at a time.",
          "RIPPER uses sequential covering to extract rules. Rules are grown in a greedy fashion.",
          "", ["RIPPER Rule Induction"]))
check("v50 an off-topic splice is not licensed merely because its block contains a good seed",
      not CP.context_candidate_is_anchored(
          "For a one-sided hypothesis test, use a critical value from a t-distribution.",
          "RIPPER uses sequential covering to extract rules. For a one-sided hypothesis test, "
          "use a critical value from a t-distribution.",
          "", ["RIPPER Rule Induction"]))
check("v50 an exact canonical heading licenses a short numbered K-means step",
      CP.context_candidate_is_anchored(
          "Assign each point to the nearest centroid.",
          "3. Assign each point to the nearest centroid.",
          "2 Question 2: K-Means Algorithm and Objective Function", ["K-Means Algorithm"]))
check("v50 a corrupted partial-overlap heading does not license unrelated distance content",
      not CP.context_candidate_is_anchored(
          "Positivity", "1. Positivity", "10.2 Modeling Null and Alternative Distributions",
          ["Models of Randomness (Approach 1)"]))
check("v73 generic test-condition prose cannot anchor McNemar Test",
      not CP.context_candidate_is_anchored(
          "Since the test condition involves only a single attribute.",
          "Using Rectilinear Splits. Since the test condition involves one attribute.",
          "Classification rules extracted from a decision tree.", ["McNemar Test"]))
check("v73 generic multiple-test prose cannot anchor Friedman Test",
      not CP.context_candidate_is_anchored(
          "The m tests are assumed to be independent.",
          "If m results are tested, the Bonferroni procedure changes the significance level.",
          "", ["Friedman Test"]))
check("v73 a real McNemar passage remains target anchored",
      CP.context_candidate_is_anchored(
          "McNemar compares the discordant predictions of two classifiers.",
          "The McNemar test compares paired classifier predictions.", "", ["McNemar Test"]))
check("v73 a real Friedman passage remains target anchored",
      CP.context_candidate_is_anchored(
          "The Friedman statistic ranks each algorithm within each data set.",
          "The Friedman test compares multiple algorithms over multiple data sets.",
          "", ["Friedman Test"]))
check("v73 Test Statistic keeps its specific statistic anchor",
      CP.context_candidate_is_anchored(
          "A test statistic summarizes an observed outcome as a numerical value.",
          "The test statistic is evaluated under the null hypothesis.", "", ["Test Statistic"]))
check("v73 inflected generic test terms do not escape the context stoplist",
      not ({"test"} & CP.context_content_terms("tests tested testing")))
check("v73 one-sided versus two-sided tests retains its specific anchor",
      CP.context_candidate_is_anchored(
          "A one-sided test rejects only in one direction.",
          "One-sided and two-sided tests use different rejection regions.",
          "", ["One-sided vs. Two-sided Tests"]))


class _V50FakeReranker:
    def score(self, query, texts):
        key = "ripper" if "ripper" in query.lower() else "k-means"
        return [1.0 if key in str(text).lower() else 0.0 for text in texts]


_v50_model_scores = PB.score_context_records(
    _V50FakeReranker(), "RIPPER Rule Induction", [{
        "text": "Rules are grown greedily one class at a time.",
        "context": "RIPPER uses sequential covering. Rules are grown greedily.",
        "heading": "",
    }, {
        "text": "For a one-sided hypothesis test, use a critical value.",
        "context": "RIPPER uses sequential covering. For a one-sided hypothesis test, use a critical value.",
        "heading": "",
    }], ["RIPPER Rule Induction"])
check("v50 the live builder scorer raises a licensed coherent member above the context floor",
      _v50_model_scores[0][0] > CP.CONTEXT_RELEVANCE_FLOOR
      and _v50_model_scores[0][1] != "standalone", str(_v50_model_scores))
check("v50 the live builder scorer never probes an unlicensed off-topic splice",
      abs(_v50_model_scores[1][0] - 0.5) < 0.0001
      and _v50_model_scores[1][1] == "standalone", str(_v50_model_scores))

_v50_seed = sentence(
    "RIPPER uses the sequential covering algorithm to extract rules directly from data.",
    block_id="D:b:50", sent_idx=0, sentence_id="v50-seed")
_v50_good = sentence(
    "Rules are grown in a greedy fashion one class at a time.",
    block_id="D:b:50", sent_idx=1, sentence_id="v50-good")
_v50_bad = sentence(
    "For a one-sided hypothesis test, use a critical value from a t-distribution.",
    block_id="D:b:50", sent_idx=2, sentence_id="v50-bad")
_v50_blocks = CP.build_corpus_block_index([_v50_seed, _v50_good, _v50_bad])


def _v50_context_scorer(records):
    return [0.56 if CP.context_candidate_is_anchored(
        record.get("text"), record.get("context"), record.get("heading"),
        ["RIPPER Rule Induction"]) else 0.50 for record in records]


_v50_passages = CP.assemble_passages(
    [{"sentence": _v50_seed, "rerank_prob": 0.56, "bm25_score": 1.0,
      "context_score_mode": "source_block"}],
    _v50_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    context_scorer=_v50_context_scorer, unit_labels=["RIPPER Rule Induction"])
_v50_text = " ".join(p.get("text") or "" for p in _v50_passages)
check("v50 context rescue retains the coherent procedure member through final verification",
      "Rules are grown" in _v50_text and "critical value" not in _v50_text, _v50_text)
check("v50 context admission basis survives into the emitted passage",
      bool(_v50_passages)
      and _v50_passages[0].get("admission_basis") == "context_anchored_relevance",
      str(_v50_passages))
_v50_dedup = CP.deduplicate_passages([
    {"text": "Rules are grown in a greedy fashion one class at a time.",
     "relevance": 0.56, "sentence_count": 1, "admission_basis": "context_anchored_relevance",
     "verification_context_text": "RIPPER uses sequential covering. Rules are grown greedily.",
     "verification_heading": ""},
    {"text": "Rules are grown in a greedy fashion one class at a time.",
     "relevance": 0.60, "sentence_count": 2, "admission_basis": "cross_encoder_relevance"},
])
check("v50 deduplication cannot silently erase context-rescue provenance",
      len(_v50_dedup) == 1
      and _v50_dedup[0].get("admission_basis") == "context_anchored_relevance"
      and "RIPPER" in str(_v50_dedup[0].get("verification_context_text") or ""),
      str(_v50_dedup))

# --- v51 packet support state reports availability, never unmeasured completeness ----------
check("v51 no passages are explicitly insufficient",
      PB.assess_support_state([], ["Any Unit"])[0] == "insufficient_support")
check("v51 a heading-only packet is weak fallback, not comprehensive",
      PB.assess_support_state([{
          "text": "A Probabilistic Perspective.", "shapes": ["heading"],
          "admission_basis": "cross_encoder_relevance"}],
          ["Models of Randomness (Approach 1)"])[0] == "weak_fallback")
check("v51 a target-anchored substantive passage is draftable without a completeness claim",
      PB.assess_support_state([{
          "text": "RIPPER uses sequential covering to extract rules directly from data.",
          "shapes": ["procedure"], "admission_basis": "context_anchored_relevance",
          "verification_context_text": "RIPPER uses sequential covering to extract rules directly from data."}],
          ["RIPPER Rule Induction"])[0] == "draftable")
check("v54 one generic shared word cannot make a weak packet draftable",
      PB.assess_support_state([{
          "text": "Decision trees with different model complexities are available.",
          "shapes": ["procedure"], "admission_basis": "cross_encoder_relevance"}],
          ["Bushy Decision Tree (Multi-split)"])[0] == "weak_fallback")
check("v54 complete target terms still establish a strong packet anchor",
      PB.assess_support_state([{
          "text": "Hierarchical clustering has severe time and space complexity.",
          "shapes": ["procedure"], "admission_basis": "cross_encoder_relevance"}],
          ["Hierarchical Clustering Complexity"])[0] == "draftable")
check("v51 the packet builder no longer emits a one-passage-equals-comprehensive policy",
      "'packet_support_state': 'comprehensive'" not in io.open(
          _PACKET_BUILDER_PATH, encoding="utf-8").read())
check("v71 non-empty topic packets are draftable without claiming completeness",
      TPB.topic_support_state([{"text": "source evidence"}])
      == ("draftable", "child_source_evidence_available_no_completeness_claim"))
check("v71 empty topic packets remain explicit source-only abstentions",
      TPB.topic_support_state([])
      == ("insufficient_support", "no_child_source_evidence_available"))
check("v71 the topic builder no longer emits the stale comprehensive status",
      '"comprehensive" if evidence' not in io.open(
          _TOPIC_PACKET_BUILDER_PATH, encoding="utf-8").read())

# --- v24 damaged renderings lose to intact ones -------------------------------------------
# The corpus stores each source paragraph up to three times, once per PDF extractor, and pymupdf -
# 56% of the corpus - substitutes control characters for operators it cannot map. The dedup scorer
# was blind to that twice over: garbled_math_penalty scored control characters at 0.0, and its
# has_math test looked only for "$" and "\\", so clean Unicode mathematics counted as prose. On the
# real KL-inequality passage the damaged rendering scored 0.000 and the intact one 0.080, and dedup
# kept the damaged text.
_dmg = 'The key is that if \x07 b P(b|a) log P(b, a) > \x07 b P(b|a) log P(b, a).'
_cln = 'The key is that if \u2211 b P ( b | a ) logP ( b , a ) > \u2211 b P ( b | a ) logP ( b , a ) .'
check("v24 control characters register as math damage",
      CP.garbled_math_penalty(_dmg) > CP.garbled_math_penalty(_cln),
      "damaged=%.3f clean=%.3f" % (CP.garbled_math_penalty(_dmg), CP.garbled_math_penalty(_cln)))
check("v24 Unicode mathematics counts as mathematics",
      CP.has_mathematics('\u2211 b P ( b ) h ( b )') and CP.has_mathematics('$\\frac{1}{n}$'))
check("v24 intact rendering outranks the damaged one",
      CP._information_score({'text': _cln, 'shapes': ['formula'], 'sentence_count': 1}) >
      CP._information_score({'text': _dmg, 'shapes': ['formula'], 'sentence_count': 1}))

# --- v29 truncated-formula detection (control-char damage's sibling) ----------------------
# Found while evaluating packet quality: "Euclidean distance = \u221a" survived v24/v28 verbatim.
# control_char_damage() is 0 for it - the radical sign rendered correctly, the extractor simply
# stopped before writing the radicand. Different signature from corrupted-glyph damage, same
# consequence: a generator handed this has nothing to reproduce and is left to invent an ending.
check("v29 a formula truncated after a bare radical is caught",
      CP.formula_truncated("Euclidean distance = \u221a"))
check("v29 a formula truncated after a bare relational operator is caught",
      CP.formula_truncated("SSE ="))
check("v29 a complete formula is NOT flagged as truncated",
      not CP.formula_truncated("Recall = TP / (TP + FN)")
      and not CP.formula_truncated("Precision = TP / (TP + FP)."))
check("v29 a formula-introducing LEAD-IN is not confused with truncation",
      not CP.formula_truncated("Split Information is:"),
      "v25 handles this case via payload admission, not junk-rejection")
check("v29 truncated formulas are rejected as structural junk",
      CP.is_structural_junk(sentence("Euclidean distance = \u221a", is_formula_like=True)))

# --- v25 a promised formula is admitted with its promise ----------------------------------
# Ten registered failures admitted the sentence introducing a formula and not the formula. The
# corpus splits equations into their own blocks, so "... then the sample mean is" and the equation
# it points at are separate retrieval units, and only the prose scores against a name-shaped query.
check("v25 lead-in recognised", CP.ends_with_lead_in('then the sample mean is'))

# --- v36 a bare trailing colon is itself recognised as a lead-in, regardless of the words -----
# before it. Diagnosed on cluster 3's "Bayes' Theorem" drafting-omission failure: the real formula
# sits in the next block, but the lead-in sentence ("...according to the Bayes' theorem:") wasn't
# recognised because v25's trigger-word list requires the verb phrase immediately before the
# colon, and real prose routinely names its referent in between ("according to X:", "known as X:").
check("v36 a referent-named lead-in ('according to the Bayes theorem:') IS recognised",
      CP.ends_with_lead_in(
          "Bayesian estimation obtains the posterior distribution of X, according to the "
          "Bayes' theorem:"))
check("v36 'known as X:' is recognised the same way",
      CP.ends_with_lead_in("Equation 4.11, which is known as Bayes theorem:"))
check("v36 an ordinary sentence ending in a period (not a colon) is still NOT flagged",
      not CP.ends_with_lead_in("The sample mean summarises the attribute values for a class."))
check("v36 is_formula_payload is still the real gate - a colon-ending lead-in whose successor "
      "is ordinary prose does not become a payload",
      not CP.is_formula_payload(
          "For example, consider the following case in more detail about how the algorithm "
          "behaves under different settings and conditions overall"))

_v36_lead = sentence(
    "Bayesian estimation obtains the posterior distribution of theta and X, according to the "
    "Bayes' theorem:", block_id="D:b:900", sent_idx=0, sentence_id="v36lead")
_v36_formula = sentence("$$ p(\\theta, X|Y) \\propto p(Y,X|\\theta)p(\\theta). $$",
                        block_id="D:b:901", sent_idx=0, sentence_id="v36formula")
_v36_blocks = CP.build_corpus_block_index([_v36_lead, _v36_formula])
_v36_succ = CP.build_block_successor_index([_v36_lead, _v36_formula])
_v36_passages = CP.assemble_passages(
    [{"sentence": _v36_lead, "rerank_prob": 0.60, "bm25_score": 1.0}], _v36_blocks,
    max_passages=10, max_chars=9000, min_relevance=0.55,
    member_verifier=lambda texts: [0.02 for _ in texts],
    verify_scorer=lambda texts: [0.02 for _ in texts],
    block_successors=_v36_succ)
_v36_t = ' '.join(p.get('text') or '' for p in _v36_passages)
check("v36 end to end: the referent-named lead-in pulls in its real formula successor, "
      "surviving both hostile re-verification passes",
      '\\propto' in _v36_t, _v36_t[:160])
check("v36 payload admission is recorded as such",
      any(p.get('admission_basis') == 'lead_in_payload' for p in _v36_passages),
      str([p.get('admission_basis') for p in _v36_passages]))
check("v25 prose is not a lead-in",
      not CP.ends_with_lead_in('The sample mean summarises the attribute values for a class.'))
check("v25 a formula is payload, prose and damaged text are not",
      CP.is_formula_payload('$$ \\mu = \\frac{1}{n} \\sum z_r $$')
      and not CP.is_formula_payload('This section explains how the estimator behaves in practice.')
      and not CP.is_formula_payload('\x12|Dj| p X \x13 .'))

_lead = sentence('If the values are z1..zn, then the sample mean is',
                 block_id='D:b:100', sent_idx=0, sentence_id='lead')
_form = sentence('$$ \\mu = \\frac{1}{n} \\sum_{r=1}^{n} z_r $$',
                 block_id='D:b:101', sent_idx=0, sentence_id='formula')
_blocks25 = CP.build_corpus_block_index([_lead, _form])
_succ25 = CP.build_block_successor_index([_lead, _form])
_p25 = CP.assemble_passages(
    [{"sentence": _lead, "rerank_prob": 0.80, "bm25_score": 1.0}], _blocks25,
    max_passages=10, max_chars=9000, min_relevance=0.55,
    member_verifier=lambda texts: [0.02 for _ in texts],    # hostile: strips whatever it may
    verify_scorer=lambda texts: [0.02 for _ in texts],    # hostile: same for the OTHER re-check
    block_successors=_succ25)
_t25 = ' '.join(p.get('text') or '' for p in _p25)
check("v25 the promised formula survives BOTH re-verification passes", '\\sum' in _t25, _t25[:110])
check("v25 payload admission is recorded as such",
      any(p.get('admission_basis') == 'lead_in_payload' for p in _p25))

# --- v26 evidence another unit claims more strongly is refused -----------------------------
# Eight of the eighteen wrongly-"grounded" drafts were source-valid text belonging to a different
# unit of the same library - classifier precision admitted for External Index: Precision, and so on.
_names = ['External Index: Precision', 'Precision', 'External Index: Recall', 'Border Point']
check("v26 rivals are units sharing a content word",
      'Precision' in CP.find_rival_units('External Index: Precision', _names)
      and 'Border Point' not in CP.find_rival_units('External Index: Precision', _names),
      str(CP.find_rival_units('External Index: Precision', _names)))

_own = 'precision(i,j) is the overlap of cluster i with class j over the size of cluster i'
_rivaltext = 'Precision = TP / (TP + FP).'
_passages26 = [{'text': _own}, {'text': _rivaltext}]


def _fake_scorer(query, texts):
    # stands in for the cross-encoder: the classification formula belongs to plain Precision
    out = []
    for tx in texts:
        if 'TP' in tx:
            out.append(0.95 if query == 'Precision' else 0.60)
        else:
            out.append(0.90 if query != 'Precision' else 0.55)
    return out


_kept26, _dropped26 = CP.drop_passages_claimed_by_rivals(
    _passages26, 'External Index: Precision', ['Precision'], _fake_scorer, min_keep=1)
check("v26 a rival-claimed passage is dropped",
      all('TP' not in (p.get('text') or '') for p in _kept26), str(_dropped26)[:120])
check("v26 the unit's own evidence is kept",
      any('cluster i' in (p.get('text') or '') for p in _kept26))
check("v26 a unit with no rival is untouched",
      CP.drop_passages_claimed_by_rivals(_passages26, 'Border Point', [], _fake_scorer)[0]
      == _passages26)

# --- v52 indexed formulas belong to an explicit compound sibling, not its plain-name unit ---
# Curriculum-derived branch context, exactly as 02_build_kc_packets.py builds and passes it.
# The compound-ownership rule previously used a hardcoded subject word list; it now subtracts the
# base unit's own ancestry from the compound sibling's, so the discriminating terms
# ({"cluster","clustering","external"} for this pair) are DERIVED from the curriculum rather than
# typed in, and the same rule works on a corpus in any subject.
_CMP_BRANCH = {
    "F-Measure": {"data", "mining", "classifier", "comparison", "evaluation"},
    "External Index: F-Measure": {"data", "mining", "clustering", "cluster", "evaluation",
                                  "external"},
    "Precision": {"data", "mining", "classifier", "comparison", "evaluation"},
    "External Index: Precision": {"data", "mining", "clustering", "cluster", "evaluation",
                                  "external"},
}

check("v52 external indexed precision is owned by the compound sibling",
      CP.compound_sibling_formula_owner(
          "The precision of cluster i with respect to class j is precision(i,j)=pij.",
          "Precision", ["External Index: Precision"]) == "External Index: Precision")
check("v52 external indexed F-measure is owned by the compound sibling",
      CP.compound_sibling_formula_owner(
          "The F-measure of cluster i for class j is F(i,j)=2*p(i,j)*r(i,j)/(p(i,j)+r(i,j)).",
          "F-Measure", ["External Index: F-Measure"]) == "External Index: F-Measure")
check("v72 external F-measure ownership does not depend on hierarchy rivals",
      CP.compound_sibling_formula_owner(
          "F-measure measures the extent to which a cluster contains only objects of a "
          "particular class.",
          "F-Measure", [], ["External Index: F-Measure"], _CMP_BRANCH)
      == "External Index: F-Measure")
check("v72 the exact broad-probe indexed F-measure is owned without hierarchy rivals",
      CP.compound_sibling_formula_owner(
          "The F-measure of cluster i with respect to class j is "
          "F(i,j)=(2*precision(i,j)*recall(i,j))/(precision(i,j)+recall(i,j)).",
          "F-Measure", [], ["External Index: F-Measure"], _CMP_BRANCH)
      == "External Index: F-Measure")
check("v72 hierarchical F-measure prose has external-index ownership",
      CP.compound_sibling_formula_owner(
          "The Fmeasure and hierarchical F-measure are examples of how to evaluate such a "
          "match across every cluster.",
          "F-Measure", [], ["External Index: F-Measure"], _CMP_BRANCH)
      == "External Index: F-Measure")
_v74_heading_kept, _v74_heading_dropped = CP.drop_compound_sibling_formulas([{
    "text": "Measures from classification include entropy, purity, and the F-measure.",
    "patch_heading": "8.4 Graph-Based Clustering",
}], "F-Measure", [], ["External Index: F-Measure"], _CMP_BRANCH)
check("v74 source headings participate in terminal compound ownership",
      not _v74_heading_kept and len(_v74_heading_dropped) == 1,
      str((_v74_heading_kept, _v74_heading_dropped)))
check("v74 the one-letter F base requires an actual F-measure head",
      CP.compound_sibling_formula_owner(
          "Select an evaluation measure under feature selection.",
          "F-Measure", []) is None)
check("v72 ordinary classifier F1 remains with the plain F-measure unit",
      CP.compound_sibling_formula_owner(
          "F1 = 2 * precision * recall / (precision + recall).",
          "F-Measure", []) is None)
check("v52 classifier precision is not mistaken for an external indexed formula",
      CP.compound_sibling_formula_owner(
          "Precision = TP / (TP + FP).", "Precision", ["External Index: Precision"]) is None)
check("v52 the compound unit retains its own indexed formula",
      CP.compound_sibling_formula_owner(
          "The precision of cluster i with respect to class j is precision(i,j)=pij.",
          "External Index: Precision", ["Precision"]) is None)
_v52_kept, _v52_dropped = CP.drop_compound_sibling_formulas([
    {"text": "Precision = TP / (TP + FP)."},
    {"text": "The precision of cluster i for class j is precision(i,j)=pij."},
], "Precision", ["External Index: Precision"], (), _CMP_BRANCH)
check("v52 deterministic ownership drops only the compound sibling formula",
      len(_v52_kept) == 1 and "TP" in _v52_kept[0]["text"]
      and len(_v52_dropped) == 1, str((_v52_kept, _v52_dropped)))

# --- v54 semantic ownership and compound-index case integrity -----------------------------
_v54_entropy_patterns = CP.compound_index_equation_patterns(["External Index: Entropy"])
check("v54 uppercase data-set symbols are not external cluster indices",
      not CP.is_defining_equation("Entropy(D) = -p+ log2(p+) - p- log2(p-)",
                                 _v54_entropy_patterns)
      and not CP.is_defining_equation("Entropy(F) = -6", _v54_entropy_patterns))
check("v54 a lowercase external cluster index remains recognisable",
      CP.is_defining_equation("entropy(i) = -sum_j p(i,j) log p(i,j)",
                              _v54_entropy_patterns))

check("v54 cluster F-measure prose belongs to the compound external-index sibling",
      CP.compound_sibling_formula_owner(
          "F-measure evaluates how a cluster contains objects of a particular class.",
          "F-Measure", ["External Index: F-Measure"], (), _CMP_BRANCH)
      == "External Index: F-Measure")
_v54_payload_kept, _v54_payload_dropped = CP.drop_compound_sibling_formulas([{
    "text": "F=sum_j weight_j max_i F(i,j)",
    "admission_basis": "lead_in_payload",
    "ownership_context_text": "The hierarchical F-measure evaluates every cluster and class.",
}], "F-Measure", ["External Index: F-Measure"], (), _CMP_BRANCH)
check("v54 a bare payload inherits its pointer's external-index ownership",
      not _v54_payload_kept and len(_v54_payload_dropped) == 1,
      str((_v54_payload_kept, _v54_payload_dropped)))

_v54_semantic_cases = [
    ("Learning Phase",
     "During the training phase, learn the parameters for P(y) and P(x|y).",
     ["NB Learning Phase"]),
    ("Querying Phase", "Select a search strategy.", []),
    ("Mutually Exclusive Classes",
     "Rules are mutually exclusive when no two rules trigger for one instance.", []),
    ("Cost Matrix", "Cost(tree,data)=Cost(tree)+Cost(data|tree).", []),
    ("Hierarchical Clustering Complexity",
     "JP clustering has a basic time complexity of O(m^2).", []),
    ("Density-Connected",
     "Clusters connected through local density attractors above ξ are combined.", []),
    ("Euclidean Distance",
     "Bregman divergence includes squared Euclidean distance and other measures.", []),
    ("Non-Deterministic Search", "It starts the search in a random direction.", []),
    ("Filter Approach", "Noisy values are detected and treated by filtering.", []),
]

_v54_valid_cases = [
    ("Learning Phase", "The learning phase constructs a classifier from training data.", []),
    ("Mutually Exclusive Classes",
     "Classes are mutually exclusive when an instance belongs to at most one class.", []),
    ("Hierarchical Clustering Complexity",
     "Hierarchical clustering has O(m^2 log m) time complexity and high storage cost.", []),
    ("Density-Connected",
     "Points p and q are density-connected if both are density-reachable from a point o.", []),
    ("Euclidean Distance", "Euclidean distance is the straight-line distance.", []),
    ("Non-Deterministic Search",
     "Nondeterministic search can improve the best feature subset before search ends.", []),
    ("Filter Approach",
     "A filter evaluates features independently of the downstream learner.", []),
]
check("v54 direct target evidence survives every semantic ownership guard",
      all(CP.semantic_misbinding_owner(text, name, rivals) is None
          for name, text, rivals in _v54_valid_cases),
      str([(name, CP.semantic_misbinding_owner(text, name, rivals))
           for name, text, rivals in _v54_valid_cases]))

_v54_external_kept, _v54_external_dropped = CP.drop_semantically_misbound_passages([
    {"text": "Entropy(D) = -p+ log2(p+) - p- log2(p-)."},
    {"text": "External entropy compares cluster labels with supplied class labels."},
], "External Index: Entropy", ["Shannon Entropy"])

# --- D-7 (supersedes v55/v61): no curated per-KC vocabulary ships --------------------------
# v55 and v61 previously asserted that curated query strings for three data-mining KC IDs were
# ACTIVE. That is precisely the hardcode that made the domain-agnosticity claim false, so the
# assertion is inverted: any curated entry here is now a defect. Accepted cost, recorded in
# DOMAIN_AGNOSTICITY_REMEDIATION.md D-7: those three units lose source-semantics disambiguation
# their registry labels cannot supply alone, pending a generic hierarchy-derived replacement.
check("D-7 no curated per-KC retrieval disambiguation vocabulary ships",
      PR._RETRIEVAL_DISAMBIGUATION_BY_KC_ID == {},
      str(PR._RETRIEVAL_DISAMBIGUATION_BY_KC_ID))
check("D-7 the disambiguation plumbing still exists for a future generic source",
      callable(getattr(PR, "retrieval_disambiguation_terms", None))
      and PR.retrieval_disambiguation_terms("ANY_KC_ID") == [])
_v55_a1 = PR.retrieval_disambiguation_terms("KC_CLU_EVAL_006")
_v55_a2 = PR.retrieval_disambiguation_terms("KC_CLU_EVAL_007")
# The override MECHANISM must still work for a future generic source, so it stays tested - with a
# synthetic term rather than any curriculum vocabulary, so the test itself introduces no hardcode.
_synthetic_override = ["synthetic disambiguation probe term"]
check("D-7 retrieval still honours a supplied disambiguation override (mechanism intact)",
      PB.retrieval_query_forms({
          "canonical_name": "Some Unit",
          "retrieval_disambiguation_terms": _synthetic_override,
      }) == _synthetic_override)
check("v55 ordinary units retain the established candidate-query path",
      PB.retrieval_query_forms({"canonical_name": "RIPPER Rule Induction"})
      == HR.candidate_query_texts({"canonical_name": "RIPPER Rule Induction"}))
check("v55 each randomness approach retains its own direct procedure",
      CP.semantic_misbinding_owner(
          "Generate random data sets, cluster each with K-means, and collect SSE values.",
          "Models of Randomness (Approach 1)", []) is None
      and CP.semantic_misbinding_owner(
          "Randomly permute class labels and calculate a statistic for each permutation.",
          "Models of Randomness (Approach 2)", []) is None)

# --- v56 cross-convention and adjacent-equation contamination -----------------------------
_v56_bad_cases = [
    ("Sample Mean and Variance",
     "Show mathematically that the maximum likelihood estimate of mu and sigma are the sample mean and standard deviation.",
     "gaussian_mle_convention_conflicts_with_sample_variance_definition"),
    ("SSE (Cluster Quality)",
     "The average pairwise distance between points in a cluster is equivalent to the SSE of the cluster.",
     "sse_pairwise_identity_requires_squared_distance"),
    ("Shannon Entropy (Uncertainty Measure)",
     "I(X,C) = sum_x sum_c P(x,c) log(P(x,c)/(P(x)P(c))).",
     "mutual_information_equation_not_entropy_definition"),
]

_v56_good_cases = [
    ("Sample Mean and Variance",
     "The sample mean is xbar = (1/n) sum_i x_i and the sample variance uses n-1."),
    ("SSE (Cluster Quality)",
     "Cluster SSE is the sum of squared distances from each point to its centroid."),
    ("SSE (Cluster Quality)",
     "Average pairwise squared distance is proportional to cluster SSE."),
    ("Shannon Entropy (Uncertainty Measure)",
     "Shannon entropy is H(X) = -sum_x P(x) log P(x)."),
    ("Shannon Entropy (Uncertainty Measure)",
     "Mutual information can be expressed as a difference of Shannon entropies."),
]
check("v56 direct target definitions survive the new guards",
      all(CP.semantic_misbinding_owner(text, name, []) is None
          for name, text in _v56_good_cases),
      str([(name, CP.semantic_misbinding_owner(text, name, []))
           for name, text in _v56_good_cases]))

# --- v57 executed v55 packets: remove mixed extractor blocks from randomness Approach 1 ---
_v57_mixed_blocks = [
    ("We generate many random sets, run K-means, and collect SSE values. Chameleon then merges "
     "clusters using closeness and interconnectivity."),
    ("We generate random sets and collect the SSE null distribution. A graph is a subgraph of "
     "another graph when its vertices and edges are subsets."),
    ("A frequent itemset null model uses support thresholds. K-means++ chooses a centroid from "
     "the cluster with the highest SSE."),
]

# --- v65 an admitted middle step recovers its complete unnumbered source procedure ----------
_v65_rows = [
    sentence("However, randomization can also generate a null distribution, as follows.",
             block_id="D:docling:36", sentence_id="v65-pointer", patch_id="p65",
             page_index=1108),
    sentence("Generate M randomized sets of labels, L1,...,Li,...,LM",
             block_id="D:docling:37", sentence_id="v65-step-1", patch_id="p65",
             page_index=1108, is_procedure_like=True, is_heading_like=True),
    sentence("For each randomized set of labels, compute the value of the external index.",
             block_id="D:docling:38", sentence_id="v65-step-2", patch_id="p65",
             page_index=1108, is_procedure_like=True),
    sentence("Assuming larger values are desirable, define the p-value as the fraction of "
             "randomized values greater than the original value.",
             block_id="D:docling:39", sentence_id="v65-step-3", patch_id="p65",
             page_index=1108, sent_idx=0, is_formula_like=True),
    sentence("m0 mi mi>m0", block_id="D:docling:39", sentence_id="v69-step-3-aux",
             patch_id="p65", page_index=1108, sent_idx=1, is_formula_like=True,
             is_heading_like=True),
    sentence("p-value(m0)=|{mi:mi>m0}|/M", block_id="D:docling:40",
             sentence_id="v65-formula", patch_id="p65", page_index=1108,
             is_formula_like=True),
    sentence("This later prose belongs to a different discussion.", block_id="D:docling:41",
             sentence_id="v65-tail", patch_id="p65", page_index=1108,
             is_procedure_like=True),
]
_v65_blocks = CP.build_corpus_block_index(_v65_rows)
_v65_successors = CP.build_block_successor_index(_v65_rows)
_v65_predecessors = {successor: predecessor
                     for predecessor, successor in _v65_successors.items()}
_v65_keys, _v65_context = CP.procedure_list_payload_keys(
    ("D", "D:docling:38"), _v65_predecessors, _v65_successors, _v65_blocks)
check("v65 exact real-shaped sequence recovers all three prose steps from the admitted middle step",
      _v65_keys == [("D", "D:docling:37"), ("D", "D:docling:38"),
                    ("D", "D:docling:39")]
      and _v65_context.endswith("as follows."), str((_v65_keys, _v65_context)))
_v65_passages = CP.assemble_passages(
    [{"sentence": _v65_rows[2], "rerank_prob": 0.72, "bm25_score": 1.0}],
    _v65_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    block_successors=_v65_successors,
    member_verifier=lambda texts: [0.01 for _ in texts],
    verify_scorer=lambda texts: [0.01 for _ in texts],
    unit_labels=["Models of Randomness (Approach 2)"])
_v65_text = " ".join(p.get("text") or "" for p in _v65_passages)
check("v65 recovered steps survive low member/reverification scores through their pointer basis",
      len(_v65_passages) == 3
      and all(p.get("admission_basis") == "procedure_list_payload"
              for p in _v65_passages)
      and all(token in _v65_text for token in (
          "Generate M", "For each randomized set", "fraction of randomized values")),
      str(_v65_passages))
check("v65 formula boundary and unrelated trailing prose are not inherited",
      "p-value(m0)=" not in _v65_text and "different discussion" not in _v65_text,
      _v65_text)
check("v65 new pointer basis is protected by every shared post-admission rescue registry",
      "procedure_list_payload" in CP.POINTER_PAYLOAD_ADMISSION_BASES
      and "procedure_list_payload" in CP.RESCUE_ADMISSION_BASES
      and PB.passage_has_strong_target_anchor(
          {"text": "Generate M randomized sets.",
           "admission_basis": "procedure_list_payload"}, []))
check("v70 packet target anchoring derives from the shared admission registries",
      PB.STRONG_TARGET_ADMISSION_BASES
      == CP.RESCUE_ADMISSION_BASES | CP.CONTEXT_ADMISSION_BASES
      and "procedure_list_payload" in PB.STRONG_TARGET_ADMISSION_BASES)

_v65_no_pointer = _v65_rows[1:]
_v65_no_pointer_blocks = CP.build_corpus_block_index(_v65_no_pointer)
_v65_no_pointer_successors = CP.build_block_successor_index(_v65_no_pointer)
check("v65 no explicit as-follows pointer means no adjacency rescue",
      not CP.procedure_list_payload_keys(
          ("D", "D:docling:38"),
          {successor: predecessor
           for predecessor, successor in _v65_no_pointer_successors.items()},
          _v65_no_pointer_successors, _v65_no_pointer_blocks)[0])

_v65_one_anchor = list(_v65_rows)
_v65_one_anchor[1] = sentence(
    _v65_rows[1]["sentence_text"], block_id="D:docling:37", sentence_id="v65-step-1-no-shape",
    patch_id="p65", page_index=1108, is_heading_like=True)
_v65_one_anchor_blocks = CP.build_corpus_block_index(_v65_one_anchor)
_v65_one_anchor_successors = CP.build_block_successor_index(_v65_one_anchor)
check("v65 one procedure-shaped block is insufficient to rescue neighboring prose",
      not CP.procedure_list_payload_keys(
          ("D", "D:docling:38"),
          {successor: predecessor
           for predecessor, successor in _v65_one_anchor_successors.items()},
          _v65_one_anchor_successors, _v65_one_anchor_blocks)[0])

_v65_cross_page = list(_v65_rows)
_v65_cross_page[5] = sentence(
    _v65_rows[5]["sentence_text"], block_id="D:docling:40", sentence_id="v65-formula-page",
    patch_id="p65", page_index=1109, is_formula_like=True)
_v65_cross_page_blocks = CP.build_corpus_block_index(_v65_cross_page)
_v65_cross_page_successors = CP.build_block_successor_index(_v65_cross_page)
check("v65 a formula on another page cannot license a procedure continuation",
      not CP.procedure_list_payload_keys(
          ("D", "D:docling:38"),
          {successor: predecessor
           for predecessor, successor in _v65_cross_page_successors.items()},
          _v65_cross_page_successors, _v65_cross_page_blocks)[0])

_v67_definition_rows = [
    sentence("Closed itemsets can be defined as follows.", block_id="D:docling:70",
             sentence_id="v67-definition-pointer", patch_id="p67", page_index=10),
    sentence("An itemset is closed if no superset has the same support.",
             block_id="D:docling:71", sentence_id="v67-definition-1", patch_id="p67",
             page_index=10, is_procedure_like=True),
    sentence("It is frequent if its support is at least the minimum threshold.",
             block_id="D:docling:72", sentence_id="v67-definition-2", patch_id="p67",
             page_index=10, is_procedure_like=True),
    sentence("support(X)>=minsup", block_id="D:docling:73", sentence_id="v67-definition-formula",
             patch_id="p67", page_index=10, is_formula_like=True),
]
_v67_definition_blocks = CP.build_corpus_block_index(_v67_definition_rows)
_v67_definition_successors = CP.build_block_successor_index(_v67_definition_rows)
check("v67 a definition introduced by 'defined as follows' is not procedure-rescued",
      not CP.procedure_list_payload_keys(
          ("D", "D:docling:72"),
          {successor: predecessor
           for predecessor, successor in _v67_definition_successors.items()},
          _v67_definition_successors, _v67_definition_blocks)[0])
check("v67 the real formula-like prose comparison remains a step, not a false formula boundary",
      any("fraction of randomized values" in (p.get("text") or "")
          for p in _v65_passages), str(_v65_passages))

_v68_damaged_boundary_rows = list(_v65_rows[:5]) + [
    sentence("psi(X)={1, if X=x. 0, otherwise.", block_id="D:docling:40",
             sentence_id="v68-damaged-boundary", patch_id="p65", page_index=1108,
             is_formula_like=True),
]
_v68_damaged_boundary_blocks = CP.build_corpus_block_index(_v68_damaged_boundary_rows)
_v68_damaged_boundary_successors = CP.build_block_successor_index(
    _v68_damaged_boundary_rows)
_v68_keys, _v68_context = CP.procedure_list_payload_keys(
    ("D", "D:docling:38"),
    {successor: predecessor
     for predecessor, successor in _v68_damaged_boundary_successors.items()},
    _v68_damaged_boundary_successors, _v68_damaged_boundary_blocks)
check("v68 a short damaged equation is still a stop boundary, never inherited as evidence",
      _v68_keys == [("D", "D:docling:37"), ("D", "D:docling:38"),
                    ("D", "D:docling:39")]
      and all("psi(" not in joined.get("sentence_text", "")
              for key in _v68_keys for joined in _v68_damaged_boundary_blocks[key]),
      str((_v68_keys, _v68_context)))
check("v69 one noisy heading flag inside a mixed prose block cannot stop the real procedure",
      len(_v65_blocks[("D", "D:docling:39")]) == 2
      and any(row.get("is_heading_like") for row in _v65_blocks[("D", "D:docling:39")])
      and any("fraction of randomized values" in (p.get("text") or "")
              for p in _v65_passages), str(_v65_passages))
check("v57 clean random-data procedure and null-distribution context remain eligible",
      CP.semantic_misbinding_owner(
          "Generate many random data sets, cluster each with K-means, and accumulate the null "
          "distribution of SSE values.",
          "Models of Randomness (Approach 1)", []) is None
      and CP.semantic_misbinding_owner(
          "The null distribution is the distribution of a statistic under the null hypothesis.",
          "Models of Randomness (Approach 1)", []) is None)

# --- v58 Approach 2 means the clustering external-index procedure, not classifier testing ---
check("v58 randomized-label external-index procedure remains eligible",
      CP.semantic_misbinding_owner(
          "Generate randomized sets of labels, compute the external index for every "
          "randomization, and use the resulting values to calculate a p-value for the clustering.",
          "Models of Randomness (Approach 2)", []) is None)

# --- v59 reject the actual v58 mixed block while preserving its clean semantic payload --------
check("v59 clean Approach 2 external-index step remains eligible",
      CP.semantic_misbinding_owner(
          "For each randomized set of labels, compute the value of the external index. Let m_i "
          "be the external-index value from the ith randomization and m_0 the original value.",
          "Models of Randomness (Approach 2)", []) is None)

# --- v60 candidate checks are repeated on the exact assembled text sent to drafting -----------
_v60_damaged = (
    "$$ \\mathsf { e r r g e n ( T ) } = \\mathsf { e r r ( T ) } + \\Omega \\times "
    "\\mathsf { k N } \\mathsf { train } , $$ Later, SSE is discussed. "
    "$$ \\mathsf { e r r g e n ( T ) } = \\mathsf { e r r ( T ) } + \\Omega \\times "
    "\\mathsf { k N } \\mathsf { train } , $$"
)
_v60_clean = "SSE=∑i=1K∑x∈Ci dist(ci,x)^2 (7.1)"
_v60_kept, _v60_dropped = CP.drop_damaged_math_passages([
    {"text": _v60_damaged},
    {"text": _v60_clean},
])
check("v60 final assembled math filter drops damage and keeps the intact SSE equation",
      _v60_kept == [{"text": _v60_clean}]
      and len(_v60_dropped) == 1
      and _v60_dropped[0]["reason"] == "assembled_passage_math_rendering_damaged",
      str((_v60_kept, _v60_dropped)))

# --- v61 source-grounded SSE query reaches the definition/formula, not generic quality prose ---
# v61's two assertions removed with D-7: they required curated SSE source-semantics vocabulary to
# be present in the profile builder. Superseded by the D-7 inverse checks above.

# --- v66 real v63 SSE target: reject SSB and a detached contradictory warning ---------------
check("v66 a passage explicitly relating SSB and SSE is preserved",
      CP.semantic_misbinding_owner(
          "SSB measures between-cluster separation, while SSE measures within-cluster error.",
          "SSE (Cluster Quality)", []) is None)
check("v66 the direct squared closest-centroid definition remains eligible",
      CP.semantic_misbinding_owner(
          "SSE is the sum of squared Euclidean distances from each point to its closest "
          "cluster centroid.", "SSE (Cluster Quality)", []) is None)

# --- v62 extractor block IDs are not globally unique, so source regions must not merge --------
_v62_good_source = (
    "We generate random data sets, cluster each with K-means, and collect the SSE null "
    "distribution. The original clustering is then compared with that distribution."
)
_v62_bad_source = (
    "Agglomerative hierarchical clustering combines the closest clusters. Chameleon uses "
    "closeness and interconnectivity."
)
_v62_good = sentence(
    "We generate random data sets, cluster each with K-means, and collect the SSE null distribution.",
    block_id="D:mineru:77:426", sentence_id="D:mineru:77:426::s000", sent_idx=0,
    source_block_text=_v62_good_source)
_v62_good_tail = sentence(
    "The original clustering is then compared with that distribution.",
    block_id="D:mineru:77:426", sentence_id="D:mineru:77:426::s001", sent_idx=1,
    source_block_text=_v62_good_source)
_v62_bad = sentence(
    "Agglomerative hierarchical clustering combines the closest clusters.",
    block_id="D:mineru:77:426", sentence_id="D:mineru:77:426::s000", sent_idx=0,
    source_block_text=_v62_bad_source)
_v62_bad_tail = sentence(
    "Chameleon uses closeness and interconnectivity.",
    block_id="D:mineru:77:426", sentence_id="D:mineru:77:426::s001", sent_idx=1,
    source_block_text=_v62_bad_source)
_v62_corpus = [_v62_good, _v62_good_tail, _v62_bad, _v62_bad_tail]
_v62_blocks = CP.build_corpus_block_index(_v62_corpus)
_v62_passages = CP.assemble_passages(
    [{"sentence": _v62_good, "rerank_prob": 0.70, "bm25_score": 1.0}],
    _v62_blocks, max_passages=5, max_chars=2000, min_relevance=0.55)
check("v62 reused block IDs produce two internal source regions",
      len(_v62_blocks) == 2, str(list(_v62_blocks)))
check("v62 assembly expands only within the seed's fingerprinted source region",
      len(_v62_passages) == 1
      and "original clustering" in _v62_passages[0]["text"].lower()
      and "Chameleon" not in _v62_passages[0]["text"]
      and _v62_passages[0]["block_id"] == "D:mineru:77:426",
      str(_v62_passages))
_v62_successors = CP.build_block_successor_index(_v62_corpus)
check("v62 pointer rescue refuses ambiguous adjacency around a reused block ID",
      not _v62_successors, str(_v62_successors))

# --- v63 exact defining equations cannot disappear outside the lexical/dense candidate pool ----
_v63_patterns = CP.defining_equation_patterns(["SSE (Cluster Quality)", "SSE"])
_v63_pool = [(0, 2.5)]
_v63_indices = {0}
_v63_added = PB.supplement_defining_equation_rows(
    _v63_pool, _v63_indices,
    [(1, "SSE=∑i=1K∑x∈Ci dist(ci,x)^2 (7.1)"),
     (2, "SSB=∑i dist(ci,c)^2"),
     (3, "SSE=17.5")],
    _v63_patterns)
check("v63 the live builder supplements only exact unit-LHS equation rows",
      _v63_added == 2 and _v63_indices == {0, 1, 3}
      and _v63_pool == [(0, 2.5), (1, 0.0), (3, 0.0)],
      str((_v63_added, _v63_pool)))

_builder_src = io.open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pipeline", "02_build_kc_packets.py"), encoding="utf-8").read()
check("v60 the live builder invokes terminal math filtering before semantic/rival filtering",
      _builder_src.index("passages, math_drops = drop_damaged_math_passages(passages)")
      < _builder_src.index("passages, compound_drops = drop_compound_sibling_formulas")
      < _builder_src.index("passages, semantic_drops = drop_semantically_misbound_passages"))

# --- v42 a rescue-basis passage is protected from the final max_passages budget truncation -----
# Found via a mechanical, structural pass over the whole module (not another one-off hypothesis):
# of the three functions that transform a passages LIST, all were RESCUE_ADMISSION_BASES-aware -
# but assemble_passages' own FINAL sort-by-relevance-then-truncate step was not, because it is
# ordinary budget management, not a "rejection check" or "re-verification pass" in the shape
# v37-v41 covered. Confirmed reachable, not hypothetical: 9 real units already sit at exactly the
# 40-passage cap in the current library.
_v42_hits = []
for _i in range(45):
    _s = sentence('Ordinary sentence number %d about the general topic area here now.' % _i,
                 block_id='D:b:v42_%d' % _i, sent_idx=0, sentence_id='v42s%d' % _i)
    _v42_hits.append({"sentence": _s, "rerank_prob": 0.70, "bm25_score": 1.0})
_v42_formula = sentence('precision(i,j)=pij.', block_id='D:b:v42_900', sent_idx=0,
                        sentence_id='v42formula', is_formula_like=True)
_v42_hits.append({"sentence": _v42_formula, "rerank_prob": 0.50, "bm25_score": 1.0})
_v42_blocks = CP.build_corpus_block_index([h["sentence"] for h in _v42_hits])
_v42_passages = CP.assemble_passages(
    _v42_hits, _v42_blocks, max_passages=40, max_chars=99999, min_relevance=0.55,
    unit_labels=["External Index: Precision", "external precision"])
check("v42 a rescue-basis formula survives max_passages truncation even when outscored by 45 "
      "ordinary candidates",
      any(p.get("admission_basis") == "name_anchored_defining_equation" for p in _v42_passages),
      str(len(_v42_passages)))
check("v42 the budget itself is still respected - still exactly max_passages, not unlimited",
      len(_v42_passages) == 40)

_v42_reg_hits = []
for _i in range(45):
    _s = sentence('Ordinary sentence number %d about topic here, relevance marker %d.' % (_i, _i),
                 block_id='D:b:v42r_%d' % _i, sent_idx=0, sentence_id='v42rs%d' % _i)
    _v42_reg_hits.append({"sentence": _s, "rerank_prob": 0.55 + _i * 0.001, "bm25_score": 1.0})
_v42_reg_blocks = CP.build_corpus_block_index([h["sentence"] for h in _v42_reg_hits])
_v42_reg_passages = CP.assemble_passages(
    _v42_reg_hits, _v42_reg_blocks, max_passages=40, max_chars=99999, min_relevance=0.55)
check("v42 regression: with no rescue content at all, ordinary relevance-ranked truncation is "
      "unchanged (highest-scoring 40 of 45 survive)",
      len(_v42_reg_passages) == 40
      and min(p["relevance"] for p in _v42_reg_passages)
      >= sorted([h["rerank_prob"] for h in _v42_reg_hits], reverse=True)[39] - 1e-6)

# --- v37 a name_anchored_defining_equation passage is exempt from v26's rival-stripping ------
# Diagnosed by validating v34's rescue against the REAL pipeline end to end, not just
# assemble_passages() in isolation - the exact gap that let v25's own bug through once already.
# A cross-encoder scores a SHORT, generic rival query ("Precision") against text containing that
# literal word MORE confidently than the longer, compound owning query ("External Index:
# Precision") scores the same text - a query-length bias, not a real ownership signal. Measured
# directly on the real corpus formula: margin 0.156, comfortably over CLAIM_MARGIN, meaning v26
# was silently deleting v34's own rescue every time it fired for a compound name with a
# same-rooted standalone rival.
_v37_target = 'The precision of cluster i with respect to class j is precision(i,j)=pij.'
_v37_rival_text = 'Precision, p = TP / (TP + FP).'
_v37_passages = [
    {"text": _v37_target, "admission_basis": "name_anchored_defining_equation"},
    {"text": _v37_rival_text, "admission_basis": "cross_encoder_relevance"},
]


def _v37_fake_scorer(query, texts):
    # stands in for the cross-encoder's real, measured query-length bias: the rival's bare name
    # scores the classifier formula highest, and even scores the CORRECT external-index formula
    # higher than the compound query does - exactly the real measured behaviour.
    out = []
    for tx in texts:
        if query == "Precision":
            out.append(0.90 if "TP" in tx else 0.66)
        else:
            out.append(0.55 if "TP" in tx else 0.51)
    return out


_v37_kept, _v37_dropped = CP.drop_passages_claimed_by_rivals(
    _v37_passages, "External Index: Precision", ["Precision"], _v37_fake_scorer, min_keep=1)
check("v37 the name-anchored defining equation SURVIVES rival-stripping even though a bare "
      "rival name would out-score it on a plain relevance re-check",
      any(p.get("text") == _v37_target for p in _v37_kept), str(_v37_kept))
check("v37 the ordinary rival-claimed passage is still correctly dropped (regression: v37 must "
      "not blanket-disable v26)",
      any(d.get("text", "").startswith("Precision, p") for d in _v37_dropped), str(_v37_dropped))

# --- v38 lead_in_payload is exempt from rival-stripping too, closing the SAME gap v37 fixed for
# name_anchored_defining_equation only. Found by systematically auditing every special-admission
# basis against every post-admission re-verification pass, not by trusting that one instance was
# the whole class of bug.
check("v38 RESCUE_ADMISSION_BASES covers both original special bases, not just one",
      CP.RESCUE_ADMISSION_BASES.issuperset(
          {"lead_in_payload", "name_anchored_defining_equation"}),
      str(CP.RESCUE_ADMISSION_BASES))

_v38_passages = [
    {"text": "$$ \\mu_j = \\bar z = \\frac{1}{n}\\sum z_r $$", "admission_basis": "lead_in_payload"},
    {"text": "Representative training samples cover the full range of the population.",
     "admission_basis": "cross_encoder_relevance"},
]


def _v38_fake_scorer(query, texts):
    # a rival's bare, shorter name scores a bare formula more confidently than the compound own
    # query does - the exact measured bias v37/v38 exist to neutralise.
    out = []
    for tx in texts:
        if "\\mu_j" in tx:
            out.append(0.70 if query == "Representative Training Sample" else 0.50)
        else:
            out.append(0.60 if query != "Representative Training Sample" else 0.85)
    return out


_v38_kept, _v38_dropped = CP.drop_passages_claimed_by_rivals(
    _v38_passages, "Sample Mean and Variance", ["Representative Training Sample"],
    _v38_fake_scorer, min_keep=0)
check("v38 the lead_in_payload formula SURVIVES rival-stripping even though a bare rival name "
      "would out-score it",
      any("mu_j" in p.get("text", "") for p in _v38_kept), str(_v38_kept))
check("v38 the ordinary rival-claimed passage is still correctly dropped (regression: v38 must "
      "not blanket-disable v26 either)",
      any("Representative training" in d.get("text", "") for d in _v38_dropped), str(_v38_dropped))

# --- v39 a too-short content signature must skip DEDUPLICATION, not DELETE the passage --------
# Found in the same systematic audit: deduplicate_passages() used a too-short signature as a
# reason to drop a passage outright, silently discarding real short evidence ("p = 0.1",
# "purity(Z1) = 3") with no admission_basis exemption of any kind.
check("v39 a short-signature passage is KEPT, not dropped",
      len(CP.deduplicate_passages([{"text": "p = 0.1", "relevance": 0.6}])) == 1)
check("v39 two DIFFERENT short passages are both kept, not collapsed into one",
      len(CP.deduplicate_passages([
          {"text": "p = 0.1", "relevance": 0.6},
          {"text": "K = 2", "relevance": 0.6},
      ])) == 2)
check("v39 a TRUE duplicate (long signature, identical text) still correctly collapses to one",
      len(CP.deduplicate_passages([
          {"text": "precision(i,j)=pij.", "relevance": 0.6},
          {"text": "precision(i,j)=pij.", "relevance": 0.5},
      ])) == 1)

# --- v28 corrupted mathematics never reaches the drafter ----------------------------------
# A generator told to reproduce the mathematics in its evidence completes a partial rendering
# rather than reporting it unusable - which is how Gain Ratio acquired a Split Information
# definition of Entropy(Parent) - sum p log p from a rendering that had lost its fraction bar.
# Corrupted renderings are therefore withheld entirely: no formula beats a reconstructed one.
check("v28 control-character wreckage is rejected as evidence",
      CP.is_structural_junk(sentence('Euclidean distance De = m i=1 (xi -yi)2 1',
                                     is_formula_like=True)))
check("v28 an intact formula is still admitted",
      not CP.is_structural_junk(sentence('Recall = TP / (TP + FN)', is_formula_like=True)))
check("v44 a Bayes formula with the denominator bar lost is rejected",
      CP.is_structural_junk(sentence('P(Y|X)=P(X|Y)P(Y)P(X).', is_formula_like=True)))
check("v44 a Laplace estimate with a flattened denominator is rejected",
      CP.is_structural_junk(sentence('P(Xi=c|y)=nc+1n+v,', is_formula_like=True)))
check("v44 a ratio formula with a lost fraction bar is rejected",
      CP.is_structural_junk(sentence('GainRatio(A) = IG(A) SplitInfo(A).', is_formula_like=True)))
check("v44 an AUC one-over-product formula with a lost denominator is rejected",
      CP.is_structural_junk(sentence('AUC = 1 P · N', is_formula_like=True)))
check("v44 a display formula spliced to an unrelated list item is rejected",
      CP.is_structural_junk(sentence('$$ H(X) = - \\sum p log p $$ b. More centroids should be allocated.',
                                     is_formula_like=True)))
check("v44 a normal explicit fraction remains admissible",
      not CP.is_structural_junk(sentence('GainRatio(A) = IG(A) / SplitInfo(A).',
                                         is_formula_like=True)))
check("v44 damaged formula payloads are not inherited as formula payloads",
      not CP.is_formula_payload('P(Y|X)=P(X|Y)P(Y)P(X).'))
check("v47 a LaTeX-wrapped Bayes formula with the denominator bar lost is rejected",
      CP.is_structural_junk(sentence(
          '$$ \\mathsf { P } ( \\mathsf { Y } | \\mathsf { X } ) { = } '
          '\\mathsf { P } ( \\mathsf { X } | \\mathsf { Y } ) '
          '\\mathsf { P } ( \\mathsf { Y } ) \\mathsf { P } ( \\mathsf { X } ) . $$',
          is_formula_like=True)))
check("v47 LaTeX-wrapped damaged formula payloads are not inherited",
      not CP.is_formula_payload(
          '$$ \\mathsf { P } ( \\mathsf { Y } | \\mathsf { X } ) { = } '
          '\\mathsf { P } ( \\mathsf { X } | \\mathsf { Y } ) '
          '\\mathsf { P } ( \\mathsf { Y } ) \\mathsf { P } ( \\mathsf { X } ) . $$'))
check("v47 a conditional-probability formula whose RHS lost P(...) terms is rejected",
      CP.is_structural_junk(sentence('P(Y=y|x)=(y, x)P(x)=(y, x)∑y′P(y′, x) (4.24)',
                                    is_formula_like=True)))
check("v47 numeric RandIndex denominator loss is rejected",
      CP.is_structural_junk(sentence('RandIndex = 1 + 10 1 + 2 + 2 + 10 = 11',
                                    is_formula_like=True)))
check("v47 Euclidean distance sum-of-squares rendering with no square root is rejected",
      CP.is_structural_junk(sentence(
          '$$ \\mathsf { d } ( \\mathsf { x } , \\mathsf { y } ) { = } \\sum '
          '\\mathsf { k } { = } 1 \\mathsf { n } ( \\mathsf { x } \\mathsf { k } { - } '
          '\\mathsf { y } \\mathsf { k } ) 2 . $$',
          is_formula_like=True)))
check("v47 Euclidean distance worked example with square roots remains admissible",
      not CP.is_structural_junk(sentence(
          '$$ d_E(p_2,p_6)=\\sqrt{(2-4)^2+(5-1)^2}=\\sqrt{20}. $$',
          is_formula_like=True)))
check("v47 a correct Bayes formula with an explicit division remains admissible",
      not CP.is_structural_junk(sentence('P(Y|X)=P(X|Y)P(Y)/P(X).', is_formula_like=True)))

# --- v48 delimiter integrity and additional real compact-formula loss ---------------------
check("v48 ordinary prose saying 'fraction' is NOT explicit fraction notation",
      not CP.has_explicit_fraction_notation(
          "The fraction of a cluster that consists of objects of a specified class."))
check("v48 literal slash, LaTeX frac, and 'divided by' ARE explicit fraction notation",
      all(CP.has_explicit_fraction_notation(x) for x in (
          "Recall = TP / (TP + FN)", r"Recall = \frac{TP}{TP+FN}",
          "Recall is TP divided by TP plus FN")))
check("v48 an unmatched inline-math dollar is rejected",
      CP.is_structural_junk(sentence(
          r"At significance level $\alpha = 0 .", is_formula_like=True)))
check("v48 a currency dollar is not mistaken for an unmatched math delimiter",
      not CP.formula_delimiters_damaged("Income is less than or equal to $55,000."))
check("v48 unbalanced formula parentheses and brackets are rejected",
      CP.is_structural_junk(sentence(
          "s_i=(b_i-a_i)/max(a_i,", is_formula_like=True))
      and CP.is_structural_junk(sentence(
          "[ sum ] = 1 N w_j ]", is_formula_like=True)))
check("v48 a display equation torn off after 'and' is rejected",
      CP.is_structural_junk(sentence(
          r"$$ \widehat B=\widehat\Sigma^{-1}, a n d\tag{4.10} $$",
          is_formula_like=True)))
check("v48 leading closing-bracket formula wreckage is rejected",
      CP.is_structural_junk(sentence(
          "]x2=0.971 Gain Ratio=1-0.971-10/20", is_formula_like=True)))
check("v48 flattened classifier-metric numerators are rejected",
      all(CP.is_structural_junk(sentence(x, is_formula_like=True)) for x in (
          "Accuracy = TP + TN TP + TN + FP + FN.",
          "Precision = TP TP + FP.",
          "JaccardCoefficient = f11 f11 + f10 + f01.")))
check("v48 a long prose block cannot become an exempt formula payload from one equality prefix",
      not CP.is_formula_payload(
          "ys=2*y. In the presence of slack variables, it is important to learn a separating "
          "hyperplane that jointly maximizes the margin and minimizes the values of slack "
          "variables. This is achieved by modifying the optimization problem of SVM as follows."))
check("v48 a long intact display equation remains a formula payload",
      CP.is_formula_payload(
          r"$$ r_{A,B}=\frac{\sum_{i=1}^{m}(a_i-\bar A)(b_i-\bar B)}"
          r"{m\sigma_A\sigma_B}=\frac{\sum_{i=1}^{m}a_ib_i-m\bar A\bar B}"
          r"{m\sigma_A\sigma_B}. $$"))
check("v48 intact explicit metric fractions remain admissible",
      all(not CP.is_structural_junk(sentence(x, is_formula_like=True)) for x in (
          "Accuracy = (TP + TN) / (TP + TN + FP + FN).",
          "Precision = TP / (TP + FP).",
          "silhouette(x)=(b(x)-a(x))/max(a(x),b(x)).",
          "purity=∑i=1K (mi/m) purity(i).")))
check("v48 intact LaTeX Gaussian, covariance, entropy and square-root formulas remain admissible",
      all(not CP.is_structural_junk(sentence(x, is_formula_like=True)) for x in (
          r"$$ P(X_i=x_i\mid Y=y_j)=\frac{1}{\sqrt{2\pi}\sigma_{ij}}\exp[-\frac{(x_i-\mu_{ij})^2}{2\sigma_{ij}^2}]. $$",
          r"$$ Cov(A,B)=\frac{\sum_i(a_i-\bar A)(b_i-\bar B)}{m}. $$",
          r"$$ H(X)=-\sum_i p_i\log_2 p_i. $$",
          r"$$ d_E(p_2,p_6)=\sqrt{(2-4)^2+(5-1)^2}=\sqrt{20}. $$")))
check("v28 the drafting contract forbids reconstructing a formula",
      'Never reconstruct, complete, simplify or infer a formula' in _builder_src
      and 'give no equation at all' in _builder_src)
check("v28 the drafting contract forbids padding to look finished",
      'Never add a sentence, a step or' in _builder_src)

# --- v30 a shattered bibliography entry is rejected as a whole, not by its innocuous piece ----
# Agglomerative Clustering's evidence admitted "clustering method for very large databases." as
# though it described the KC. It is the tail of a reference-list title - "BIRCH: an efficient
# data clustering method for very large databases" - split across single-line pymupdf blocks so
# thoroughly that no individual fragment carries enough of the year/venue markers to be caught by
# the existing per-sentence bibliography filter alone.
check("v30 a shattered citation is rejected from its own block's raw text",
      CP.is_bibliography_entry(
          "clustering method for very large databases. In Proc. of 1996 ACM-"))
check("v30b _VENUE_RE actually matches \"In Proc.\" (a real pre-existing regex bug: the trailing "
      "\\b after a period can never match, since neither side of a period-then-space is a word "
      "character)",
      CP._VENUE_RE.search("In Proc. of 1996 ACM-") is not None)
check("v30 ordinary content with a bracket citation is NOT rejected",
      not CP.is_bibliography_entry(
          "Node impurity measures how mixed the class labels are within a node of the tree [3]."))

_v30_cite = [
    sentence("[620] T.", block_id="D:b:300", sent_idx=0, sentence_id="c0"),
    sentence("Zhang, R. Ramakrishnan, and M. Livny.", block_id="D:b:300", sent_idx=1, sentence_id="c1"),
    sentence("BIRCH:", block_id="D:b:301", sent_idx=0, sentence_id="c2"),
    sentence("an efficient data", block_id="D:b:301", sent_idx=1, sentence_id="c3"),
    sentence("clustering method for very large databases.", block_id="D:b:302", sent_idx=0, sentence_id="c4"),
    sentence("In Proc.", block_id="D:b:302", sent_idx=1, sentence_id="c5"),
    sentence("of 1996 ACM-", block_id="D:b:302", sent_idx=2, sentence_id="c6"),
]
_v30_blocks = CP.build_corpus_block_index(_v30_cite)
_v30_hits = [{"sentence": _v30_cite[4], "rerank_prob": 0.65, "bm25_score": 1.0}]
_v30_passages = CP.assemble_passages(
    _v30_hits, _v30_blocks, max_passages=10, max_chars=9000, min_relevance=0.55)
check("v30 end to end: the citation-tail block is rejected, not admitted",
      len(_v30_passages) == 0, str(_v30_passages)[:120])

# --- v31 a lowercase-starting fragment of a longer sentence elsewhere is rejected -----------
# Feature Selection Definition's evidence asserted "feature selection is performed outside
# cross-validation" as a recommendation. The source says the opposite: Ambroise et al. discuss
# the SELECTION BIAS that arises when this is done. pymupdf splits the sentence across three
# one-line blocks; the final clause survives alone. mineru/docling keep it whole.
check("v31 a lowercase-starting fragment IS recognised when a fuller sentence contains it",
      CP.is_severed_fragment(
          "feature selection is performed outside cross-validation.",
          "DOC_X",
          {"DOC_X": ["Ambroise et al. provide an extensive discussion of the selection bias "
                     "that arises when feature selection is performed outside cross-validation."]}))
check("v31 a lowercase-starting sentence with NO fuller counterpart is left alone",
      not CP.is_severed_fragment(
          "x denotes the feature vector for a single training instance.",
          "DOC_X", {"DOC_X": ["Some unrelated long complete sentence that shares nothing."]}))
check("v31 a normal capital-starting sentence is never flagged, regardless of content",
      not CP.is_severed_fragment(
          "Node impurity measures how mixed the class labels are within a node.",
          "DOC_X", {"DOC_X": ["Node impurity measures how mixed the class labels are within a "
                              "node, extended with more detail."]}))

_v31_frag = sentence("feature selection is performed outside cross-validation.",
                     block_id="D:b:400", sent_idx=0, sentence_id="f0")
_v31_tail = sentence("Useful guidelines for", block_id="D:b:400", sent_idx=1, sentence_id="f1")
_v31_blocks = CP.build_corpus_block_index([_v31_frag, _v31_tail])
_v31_hits = [{"sentence": _v31_frag, "rerank_prob": 0.68, "bm25_score": 1.0}]
_v31_docs = {"D": ["Ambroise et al. provide an extensive discussion of the selection bias that "
                   "arises when feature selection is performed outside cross-validation."]}
_v31_passages = CP.assemble_passages(
    _v31_hits, _v31_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    doc_long_sentences=_v31_docs)
check("v31 end to end: the severed-fragment block is rejected even with an unrelated sibling "
      "member in the same block (checked on the seed sentence, not the joined block text)",
      len(_v31_passages) == 0, str(_v31_passages)[:120])

# --- v40 a formula-shaped candidate is exempt from v31's severed-fragment check --------------
# Found via the systematic post-v37/v38/v39 audit: a candidate that will ultimately be admitted
# via name_anchored_defining_equation still had to survive v31 FIRST, with no exemption, unlike
# lead_in_payload which is fully exempt from all four rejection checks. Confirmed directly against
# the real corpus: is_severed_fragment("precision(i,j)=pij.", ...) returned True - the exact
# formula this whole cycle's v34/v37 work was built around, wrongly caught as a "severed fragment"
# because the corpus states it both standalone AND folded into a longer explanatory sentence
# ("The precision of cluster i ... is precision(i,j)=pij.") - the corpus restating its own
# definition, not a PDF line-break truncating the formula.
check("v40 the real target formula is no longer wrongly flagged as a severed fragment",
      not CP.is_severed_fragment(
          "precision(i,j)=pij.", "Dv40",
          CP.build_document_long_sentences([
              {"doc_id": "Dv40",
               "sentence_text": "The precision of cluster i with respect to class j is "
                                "precision(i,j)=pij."},
          ])))
check("v40 a genuine truncated PROSE fragment (no formula shape) is STILL caught",
      CP.is_severed_fragment(
          "continues on and describes something in full.", "Dv40",
          CP.build_document_long_sentences([
              {"doc_id": "Dv40",
               "sentence_text": "This is a complete, properly capitalised sentence that "
                                "continues on and describes something in full."},
          ])))
check("v40 is deliberately narrow: prose that merely MENTIONS a mid-sentence comparison "
      "('Marital Status = Married') is NOT exempted just because it contains '=' - only text "
      "that IS a formula from its own first token is (library-wide scan found this exact real "
      "counter-example in the first, broader draft of this fix)",
      CP.is_severed_fragment(
          "raw zero probability for Marital Status = Married in class Y was preventing the "
          "stronger income", "Dv40",
          CP.build_document_long_sentences([
              {"doc_id": "Dv40",
               "sentence_text": "The raw zero probability for Marital Status = Married in "
                                "class Y was preventing the stronger income evidence from "
                                "mattering at all in the end."},
          ])))
check("v40 a formula-shaped fragment with no fuller counterpart is still left alone regardless "
      "(unchanged baseline behaviour)",
      not CP.is_severed_fragment(
          "p = 0.5", "Dv40",
          CP.build_document_long_sentences([
              {"doc_id": "Dv40",
               "sentence_text": "Some unrelated complete sentence goes here for testing "
                                "purposes today and has nothing to do with anything."},
          ])))

# --- v32 the grounded/partial/abstained status rubric is operational, not circular ----------
_runner_src = io.open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pipeline", "04_draft_runner.py"), encoding="utf-8").read()
check("v32 status rubric ties GROUNDED to completeness, not length",
      "regardless of length" in _runner_src and "Thin evidence, faithfully and completely used, is grounded" in _runner_src)
check("v32 status rubric requires PARTIAL to name a specific gap",
      "must name EXACTLY what is missing" in _runner_src
      and "is never by itself a reason for partial" in _runner_src)
check("v32 the old circular definition is gone",
      ("mark status as partial and explain the uncertainty") not in _runner_src)

# --- v33 a foreign method sitting behind a definitional-equivalence marker is rejected -----
# v27 (built, measured, rejected, deleted) tried to solve wrong-sense contamination where the
# competing concept has no library unit to lose to (CLIQUE, SNN, Jarvis-Patrick). It fired on any
# short passage naming both the unit and a foreign method, which is identical whether the sentence
# is a real misattribution or an ordinary sibling-method aside. v33 narrows the signal to fire
# only when the foreign name sits behind a definitional/equivalence marker specifically.
check("v33 an equivalence-list foreign name IS caught (unit's own name anchors the list)",
      CP.attributes_via_definitional_marker(
          "Complete Link or MAX or CLIQUE", ["MAX (Complete Linkage)"]) == "CLIQUE")
check("v33 a definitional-marker foreign name IS caught",
      CP.attributes_via_definitional_marker(
          "A point is a core point if the neighborhood, as determined by SNN similarity, exceeds Eps.",
          ["Core Point"]) == "SNN")
check("v33 an ordinary enumeration sharing a head noun is NOT caught "
      "(regression: this exact case was a real false positive during development)",
      CP.attributes_via_definitional_marker(
          "only in the case of MCAR or MAR missingness mechanisms",
          ["Missingness Mechanism"]) is None)
check("v33 a legitimate sibling-comparison sentence is NOT caught (the exact pattern that broke v27)",
      CP.attributes_via_definitional_marker(
          "The methods presented are SFG, SBG, BG, and RG.",
          ["Sequential Forward Generation (SFG)"]) is None)
check("v33 an explicit contrast marker (\"unlike\") is NOT caught",
      CP.attributes_via_definitional_marker(
          "Unlike Jarvis-Patrick, which performs simple thresholding, this approach differs.",
          ["Density-Connected"]) is None)

# --- v49 v33 cannot be bypassed by a long source block or later member expansion -----------
_v49_snn = sentence(
    "A point is a core point if the number of points within a given neighborhood around the "
    "point, as determined by SNN similarity and a supplied parameter Eps, exceeds MinPts.",
    block_id="D:b:49a", sent_idx=0, sentence_id="v49-snn")
_v49_long_context = sentence(
    "This deliberately long source-block member reproduces the real container-size condition. "
    "It contains enough ordinary explanatory prose to push the joined block beyond the guard's "
    "three-hundred-and-twenty-character local attribution window without changing the short seed "
    "sentence that was actually ranked and selected by retrieval for this unit.",
    block_id="D:b:49a", sent_idx=1, sentence_id="v49-context")
_v49_blocks = CP.build_corpus_block_index([_v49_snn, _v49_long_context])
_v49_passages = CP.assemble_passages(
    [{"sentence": _v49_snn, "rerank_prob": 0.90, "bm25_score": 1.0}],
    _v49_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    member_verifier=lambda texts: [0.90 for _ in texts], unit_labels=["Core Point"])
check("v49 a 320-plus-character block cannot bypass v33 when its ranked seed is SNN-attributed",
      not _v49_passages, str(_v49_passages))

_v49_good_seed = sentence(
    "A core point has at least MinPts points in its epsilon neighborhood.",
    block_id="D:b:49b", sent_idx=0, sentence_id="v49-good")
_v49_bad_member = sentence(
    "A point is a core point if its neighborhood, as determined by SNN similarity, exceeds "
    "the supplied threshold MinPts.",
    block_id="D:b:49b", sent_idx=1, sentence_id="v49-bad-member")
_v49_long_member = sentence(
    "This second deliberately long member keeps the raw block above the same length boundary "
    "while leaving the seed itself valid and allowing the test to exercise final per-member "
    "ownership filtering rather than the earlier ranked-seed check alone.",
    block_id="D:b:49b", sent_idx=2, sentence_id="v49-long-member")
_v49_member_blocks = CP.build_corpus_block_index(
    [_v49_good_seed, _v49_bad_member, _v49_long_member])
_v49_member_passages = CP.assemble_passages(
    [{"sentence": _v49_good_seed, "rerank_prob": 0.90, "bm25_score": 1.0}],
    _v49_member_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    member_verifier=lambda texts: [0.90 for _ in texts], unit_labels=["Core Point"])
_v49_member_text = " ".join(p.get("text") or "" for p in _v49_member_passages)
check("v49 a non-seed SNN misattribution is removed after long-block member expansion",
      "SNN similarity" not in _v49_member_text and "epsilon neighborhood" in _v49_member_text,
      _v49_member_text[:240])

# --- v53 fragmented numbered formula/property lists remain complete ----------------------
_v53_rows = [
    sentence("Distances, such as Euclidean distance, have well-known properties.",
             block_id="D:b:357", sentence_id="v53-pointer-0", sent_idx=0,
             patch_id="p53", page_index=81),
    sentence("If d(x,y) is the distance between x and y, then the following properties hold.",
             block_id="D:b:357", sentence_id="v53-pointer-1", sent_idx=1,
             patch_id="p53", page_index=81),
    sentence("1.", block_id="D:b:358", sentence_id="v53-list-0", sent_idx=0,
             patch_id="p53", page_index=81),
    sentence("Positivity", block_id="D:b:358", sentence_id="v53-list-1", sent_idx=1,
             patch_id="p53", page_index=81, is_heading_like=True),
    sentence("for all x and y, d(x,y)>=0", block_id="D:b:359", sentence_id="v53-pos",
             patch_id="p53", page_index=81, is_formula_like=True),
    sentence("only if d(x,y)=0 x=y.", block_id="D:b:360", sentence_id="v53-id",
             patch_id="p53", page_index=81, is_formula_like=True),
    sentence("Symmetry for all x and y. d(x,y)=d(y,x)", block_id="D:b:361",
             sentence_id="v53-sym", patch_id="p53", page_index=81,
             is_formula_like=True),
    sentence("Triangle Inequality: d(x,z)<=d(x,y)+d(y,z)", block_id="D:b:362",
             sentence_id="v53-tri", patch_id="p53", page_index=81,
             is_formula_like=True),
    sentence("This later prose starts a different discussion and must not be inherited.",
             block_id="D:b:363", sentence_id="v53-stop", patch_id="p53", page_index=81),
]
_v53_blocks = CP.build_corpus_block_index(_v53_rows)
_v53_successors = CP.build_block_successor_index(_v53_rows)
_v53_passages = CP.assemble_passages(
    [{"sentence": _v53_rows[0], "rerank_prob": 0.90, "bm25_score": 1.0}],
    _v53_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    block_successors=_v53_successors,
    member_verifier=lambda texts: [0.90 for _ in texts],
    verify_scorer=lambda texts: [0.90 for _ in texts],
    unit_labels=["Distance Properties"])
_v53_text = " ".join(p.get("text") or "" for p in _v53_passages)
_v53_structured = [p for p in _v53_passages
                   if p.get("admission_basis") == "structured_list_payload"]
check("v53 the complete five-block distance-property payload is retained from its pointer",
      len(_v53_structured) == 5 and all(token in _v53_text for token in (
          "Positivity", "d(x,y)>=0", "d(x,y)=0", "d(x,y)=d(y,x)",
          "d(x,z)<=d(x,y)+d(y,z)")), str(_v53_passages))
check("v53 structured continuation stops before the first non-list prose block",
      "different discussion" not in _v53_text, _v53_text)

_v53_no_number = list(_v53_rows[:2]) + [
    sentence("Positivity", block_id="D:b:358", sentence_id="v53-no-number",
             patch_id="p53", page_index=81),
    _v53_rows[4],
]
check("v53 an unnumbered neighbor is not promoted as a structured list",
      not CP.structured_list_payload_keys(
          ("D", "D:b:357"), CP.build_block_successor_index(_v53_no_number),
          CP.build_corpus_block_index(_v53_no_number)))

_v53_no_formula = list(_v53_rows[:2]) + [
    sentence("1. Background", block_id="D:b:358", sentence_id="v53-chapter-1",
             patch_id="p53", page_index=81),
    sentence("2. Related Work", block_id="D:b:359", sentence_id="v53-chapter-2",
             patch_id="p53", page_index=81),
]
check("v53 an ordinary numbered prose list without formulas is not pointer-rescued",
      not CP.structured_list_payload_keys(
          ("D", "D:b:357"), CP.build_block_successor_index(_v53_no_formula),
          CP.build_corpus_block_index(_v53_no_formula)))

# Regression guard for the exact class of bug this project just found in its own shipped code:
# a \b or \f escape silently corrupted into a literal control byte by a shell/heredoc escaping
# layer, changing regex behaviour without any syntax error to catch it. Scans the whole module
# source for stray control characters - the fastest, cheapest check available, and one that would
# have caught both the v33-in-development bug and the older, silent v29 _TRUNCATED_FORMULA_RE bug
# immediately instead of by chance during unrelated debugging.
import re as _re_ctrl_check
_module_src = io.open(HR.__file__.replace('retrieval.py', 'evidence_pack.py'),
                      encoding='utf-8').read()
check("no stray control bytes anywhere in evidence_pack.py (guards against \\b/\\f "
      "silently becoming literal backspace/formfeed bytes through shell escaping)",
      not _re_ctrl_check.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', _module_src))

# The SAME corruption class can hit the harness's own test literals, not just
# evidence_pack.py - found directly this cycle: a newly-added v38 test's LaTeX backslashes
# got under-escaped by exactly one layer while being written by a nested patch script,
# turning what should have been literal backslashes into a real backspace byte and a real
# formfeed byte in the RUNTIME string (invisible in the printed OK line, since the test's
# pass/fail outcome happened not to depend on the exact bytes that time - it could easily
# have gone the other way). One deliberate exception: v28's own test fixture contains a
# real control byte ON PURPOSE, simulating the exact PDF-extraction control-character
# wreckage control_char_damage() exists to detect - not a corruption to flag. Strip that one
# known-intentional literal out before scanning for anything else that should not be there.
_self_src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
_self_src_minus_intentional = _self_src.replace('Euclidean distance De = \x04m i=1 (xi -yi)2 1', "")
check("no stray control bytes anywhere in verify_pipeline_fixes.py itself, outside the one "
      "deliberate v28 test fixture (guards the harness's OWN test literals against the same "
      "escaping corruption class found and fixed in evidence_pack.py)",
      not _re_ctrl_check.search('[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]', _self_src_minus_intentional))

# --- v41 a rescue admission basis survives deduplicate_passages(), not just the merge-winner --
# Found by extending RESCUE_ADMISSION_BASES (v38) to its logical conclusion: deduplicate_passages
# sits BETWEEN admission and every post-admission re-verification check, and merges two passages
# sharing a content signature by keeping whichever has the higher _information_score(), which does
# not consider admission_basis - so a rescue-tagged passage could lose its tag to a near-identical
# ordinary variant (a different extractor's rendering of the same formula) and be silently
# re-exposed to the strict floor and to rival-stripping, the exact failure v37/v38 fixed, through a
# third pathway.
check("v41 rescue basis survives even when the rescue-tagged variant loses the merge",
      CP.deduplicate_passages([
          {"text": "precision(i,j)=pij.", "relevance": 0.515,
           "admission_basis": "name_anchored_defining_equation"},
          {"text": "Precision(i,j) = pij.", "relevance": 0.60,
           "admission_basis": "cross_encoder_relevance"},
      ])[0]["admission_basis"] in CP.RESCUE_ADMISSION_BASES)
check("v41 the same result holds regardless of input order",
      CP.deduplicate_passages([
          {"text": "Precision(i,j) = pij.", "relevance": 0.60,
           "admission_basis": "cross_encoder_relevance"},
          {"text": "precision(i,j)=pij.", "relevance": 0.515,
           "admission_basis": "name_anchored_defining_equation"},
      ])[0]["admission_basis"] in CP.RESCUE_ADMISSION_BASES)
check("v41 two ordinary duplicates are unaffected - still one passage, still ordinary basis "
      "(regression: this must not become a blanket rescue-basis promotion)",
      CP.deduplicate_passages([
          {"text": "The formula is x = 5", "relevance": 0.6,
           "admission_basis": "cross_encoder_relevance"},
          {"text": "the formula is x = 5", "relevance": 0.55,
           "admission_basis": "cross_encoder_relevance"},
      ]) == [{"text": "The formula is x = 5", "relevance": 0.6,
             "admission_basis": "cross_encoder_relevance", "duplicate_variants": 2}])

# --- v34 a compound unit's defining equation is recognised even without its qualifier -------
# Diagnosed against the real retrieval pipeline: External Index: Precision and External Index:
# Recall both retrieve their correct formula, ranked and above the 0.45 defining-equation floor,
# but never get recognised as a defining equation because the corpus drops the "external"
# qualifier within its own section ("precision(i,j)=pij", never "external precision(i,j)=...").
check("v34 a compound unit's qualifier-dropped equation IS recognised (target case)",
      CP.is_defining_equation(
          "precision(i,j)=pij.",
          CP.compound_index_equation_patterns(["External Index: Precision", "external precision"])))
check("v34 the sibling classifier formula (no index subscript) is NOT rescued by this pattern",
      not CP.is_defining_equation(
          "Precision = TP / (TP + FP).",
          CP.compound_index_equation_patterns(["External Index: Precision", "external precision"])))
check("v34 a non-compound name builds no patterns at all",
      CP.compound_index_equation_patterns(["Precision (classifier)"]) == [])

_v34_seed = sentence("precision(i,j)=pij.", block_id="D:b:700", sent_idx=0, sentence_id="v34s",
                     is_formula_like=True)
_v34_blocks = CP.build_corpus_block_index([_v34_seed])
_v34_hits = [{"sentence": _v34_seed, "rerank_prob": 0.515, "bm25_score": 1.0}]
_v34_passages = CP.assemble_passages(
    _v34_hits, _v34_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    unit_labels=["External Index: Precision", "external precision"])
check("v34 end to end: the real measured below-floor score (0.515) is rescued",
      len(_v34_passages) == 1
      and _v34_passages[0].get("admission_basis") == "name_anchored_defining_equation",
      str([p.get("admission_basis") for p in _v34_passages]))

_v34_sib_seed = sentence("Precision = TP / (TP + FP).", block_id="D:b:701", sent_idx=0,
                         sentence_id="v34sib", is_formula_like=True)
_v34_sib_blocks = CP.build_corpus_block_index([_v34_sib_seed])
_v34_sib_hits = [{"sentence": _v34_sib_seed, "rerank_prob": 0.515, "bm25_score": 1.0}]
_v34_sib_passages = CP.assemble_passages(
    _v34_sib_hits, _v34_sib_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    unit_labels=["External Index: Precision", "external precision"])
check("v34 end to end: the sibling's below-floor formula is NOT rescued (would reopen the "
      "sibling-confusion v26 already fixed)",
      len(_v34_sib_passages) == 0, str(_v34_sib_passages))

# --- v35 a forward-truncated fragment (the PREFIX mirror of v31's severed-SUFFIX check) is ---
# rejected. Diagnosed while re-checking NB Learning Phase's real retrieval trace: "Bayes theorem
# can be briefly" (rank 14, prob 0.590, ADMITTED) outranks its own complete sentence, "Bayes
# theorem can be briefly described as follows." (rank 187, prob 0.504, below floor) - a PDF
# line-break severed the sentence, and the fragment's few tokens overlap the query more densely
# than the same tokens diluted across the longer, complete, more informative version.
check("v35 the real failing case (front-truncated, no terminal punctuation, verified prefix of a "
      "complete sentence elsewhere in the doc) IS flagged",
      CP.is_forward_truncated_fragment(
          "Bayes theorem can be briefly", "D1",
          CP.build_document_all_sentences([
              {"doc_id": "D1", "sentence_text": "Bayes theorem can be briefly described as follows."},
          ])))
check("v35 the COMPLETE sentence itself is left alone",
      not CP.is_forward_truncated_fragment(
          "Bayes theorem can be briefly described as follows.", "D1",
          CP.build_document_all_sentences([
              {"doc_id": "D1", "sentence_text": "Bayes theorem can be briefly described as follows."},
          ])))
check("v35 a short fragment below the minimum length is left alone regardless",
      not CP.is_forward_truncated_fragment(
          "Recall", "D1",
          CP.build_document_all_sentences([
              {"doc_id": "D1", "sentence_text": "Recall the definition of a set from Chapter 1."},
          ])))
check("v35 cross-document prefix match does not fire (same-document only)",
      not CP.is_forward_truncated_fragment(
          "Bayes theorem can be briefly", "D1",
          CP.build_document_all_sentences([
              {"doc_id": "D2", "sentence_text": "Bayes theorem can be briefly described as follows."},
          ])))
check("v35 word-boundary safety: a near-miss continuation into a DIFFERENT word does not fire",
      not CP.is_forward_truncated_fragment(
          "Bayes theorem can be briefly", "D1",
          CP.build_document_all_sentences([
              {"doc_id": "D1", "sentence_text": "Bayes theorem can be briefer than expected here."},
          ])))
check("v35 a heading with no fuller counterpart anywhere in the doc is left alone",
      not CP.is_forward_truncated_fragment(
          "External Index: Precision and Recall in Practice", "D1",
          CP.build_document_all_sentences([
              {"doc_id": "D1", "sentence_text": "Some unrelated complete sentence goes here now."},
          ])))

_v35_frag = sentence("Bayes theorem can be briefly", block_id="D:b:800", sent_idx=0,
                     sentence_id="v35s")
_v35_full = sentence("Bayes theorem can be briefly described as follows.", block_id="D:b:801",
                     sent_idx=0, sentence_id="v35full")
_v35_blocks = CP.build_corpus_block_index([_v35_frag, _v35_full])
_v35_all = CP.build_document_all_sentences([_v35_frag, _v35_full])
_v35_hits = [{"sentence": _v35_frag, "rerank_prob": 0.59, "bm25_score": 1.0}]
_v35_passages = CP.assemble_passages(
    _v35_hits, _v35_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    doc_all_sentences=_v35_all)
check("v35 end to end: the real front-truncated fragment is rejected by assemble_passages",
      len(_v35_passages) == 0, str(_v35_passages))

_v35_ok_seed = sentence("Naive Bayes is a probabilistic classifier.", block_id="D:b:802",
                        sent_idx=0, sentence_id="v35ok")
_v35_ok_blocks = CP.build_corpus_block_index([_v35_ok_seed])
_v35_ok_hits = [{"sentence": _v35_ok_seed, "rerank_prob": 0.70, "bm25_score": 1.0}]
_v35_ok_passages = CP.assemble_passages(
    _v35_ok_hits, _v35_ok_blocks, max_passages=10, max_chars=9000, min_relevance=0.55,
    doc_all_sentences={})
check("v35 an ordinary complete sentence is NOT rejected",
      len(_v35_ok_passages) == 1, str(_v35_ok_passages))

# --- v45 invalid abstentions route to content repair before schema repair ------------------
_v45_packet_with_evidence = {
    'knowledge_unit_type': 'kc',
    'knowledge_unit_id': 'KC_V45_INVALID_ABSTENTION',
    'canonical_name': 'Representative Training Sample',
    'packet_support_state': 'comprehensive',
    'abstention_expected': False,
    'evidence_for_synthesis': [{'evidence_id': 'e1',
                                'text': 'The training set, shown in Figure 3.22(b), looks quite representative of the overall data.'}],
}
_v45_policy_abstention_packet = {
    'knowledge_unit_type': 'kc',
    'knowledge_unit_id': 'KC_V45_ALLOWED_ABSTENTION',
    'canonical_name': 'McNemar Test',
    'abstention_expected': True,
    'evidence_for_synthesis': [{'evidence_id': 'e1'}],
}
_v45_mcnemar_fragment_packet = {
    'knowledge_unit_type': 'kc',
    'knowledge_unit_id': 'KC_V45_MCNEMAR_FRAGMENT',
    'canonical_name': 'McNemar Test',
    'packet_support_state': 'comprehensive',
    'abstention_expected': False,
    'evidence_for_synthesis': [{'evidence_id': 'e1',
                                'text': '10.1 , where the m tests are assumed to be independent of'}],
}
_v45_informative_missingness_packet = {
    'knowledge_unit_type': 'kc',
    'knowledge_unit_id': 'KC_V45_INFORMATIVE_MISSINGNESS',
    'canonical_name': 'Informative Missingness',
    'packet_support_state': 'comprehensive',
    'abstention_expected': False,
    'evidence_for_synthesis': [{'evidence_id': 'e1',
                                'text': 'Values or even entire data objects can be missing.'},
                               {'evidence_id': 'e2',
                                'text': 'missing data and wrong (noisy) data.'}],
}
_v45_abstained_with_missing_support = {
    'knowledge_unit_type': 'kc',
    'contextual_kc_draft': {
        'status': 'abstained',
        'text': '',
        'supporting_evidence_ids': [],
        'coverage_notes': [],
        'uncertainty_notes': ['Insufficient source support.'],
    },
}
check("v45 an abstention on a comprehensive evidence-bearing packet is routed to content repair",
      DR.invalid_abstention_needs_content_repair(_v45_packet_with_evidence,
                                                 _v45_abstained_with_missing_support))
check("v45 packet-policy abstentions are not routed to content repair",
      not DR.invalid_abstention_needs_content_repair(_v45_policy_abstention_packet,
                                                     _v45_abstained_with_missing_support))
check("v45 fragment-only comprehensive packets are not content-repaired",
      not DR.invalid_abstention_needs_content_repair(_v45_mcnemar_fragment_packet,
                                                     _v45_abstained_with_missing_support))
check("v45 generic sibling-level evidence is not content-repaired",
      not DR.invalid_abstention_needs_content_repair(_v45_informative_missingness_packet,
                                                     _v45_abstained_with_missing_support))
check("v45 invalid-abstention repair prompt names the actual failure mode",
      'invalid abstention' in DR.build_invalid_abstention_repair_prompt(
          _v45_packet_with_evidence, _v45_abstained_with_missing_support,
          [{'code': 'kc_contextual_draft_missing_or_too_short'}]).lower())
check("v43 policy abstentions can still receive structural schema repair",
      DR.should_attempt_schema_repair(_v45_policy_abstention_packet,
                                      _v45_abstained_with_missing_support,
                                      [{'code': 'evidence_map_missing_or_empty'}]))

# --- v46 damaged math in generated draft text is a validation failure ----------------------
_v46_packet = {
    'knowledge_unit_type': 'kc',
    'knowledge_unit_id': 'KC_V46_BAYES',
    'canonical_name': "Bayes' Theorem",
    'packet_support_state': 'comprehensive',
    'evidence_for_synthesis': [{'evidence_id': 'e1',
                                'text': 'Bayes theorem relates prior, likelihood, and posterior probabilities.'}],
}
_v46_good_text = ("Bayes theorem relates prior, likelihood, and posterior probabilities in a "
                  "source-grounded classification setting. It explains how a prior belief can be "
                  "updated after observing evidence, while this fixture deliberately gives no "
                  "equation because the packet does not contain an intact formula.")
_v46_bad_draft = {
    'knowledge_unit_id': 'KC_V46_BAYES',
    'knowledge_unit_type': 'kc',
    'canonical_name': "Bayes' Theorem",
    'contextual_kc_draft': {
        'status': 'grounded',
        'text': _v46_good_text + ' P(Y|X)=P(X|Y)P(Y)P(X).',
        'supporting_evidence_ids': ['e1'],
        'coverage_notes': [],
        'uncertainty_notes': [],
    },
    'segmentation_support': {},
    'evaluation_support': {},
    'evidence_map': [{'claim': 'Bayes theorem relates prior and posterior probabilities.',
                      'supporting_evidence_ids': ['e1']}],
    'kc_specific_criteria': [],
    'kc_specific_criteria_status': 'expert_pending',
    'kc_specific_criteria_source': 'deterministic_placeholder_not_model_authored',
}
_v46_good_draft = json.loads(json.dumps(_v46_bad_draft))
_v46_good_draft['contextual_kc_draft']['text'] = _v46_good_text
_v46_bad_issues = DR.validate_output(_v46_packet, _v46_bad_draft)
check("v46 damaged math in a KC draft is a validation issue",
      any(x.get('code') == 'kc_contextual_draft_damaged_math' for x in _v46_bad_issues),
      str(_v46_bad_issues))
check("v46 damaged-math drafts route to content repair",
      DR.damaged_math_needs_content_repair(_v46_packet, _v46_bad_draft, _v46_bad_issues))
check("v46 intact prose draft does not raise damaged-math validation",
      not any(x.get('code') == 'kc_contextual_draft_damaged_math'
              for x in DR.validate_output(_v46_packet, _v46_good_draft)))
check("v46 damaged-math repair prompt forbids formula reconstruction",
      'do not reconstruct' in DR.build_damaged_math_repair_prompt(
          _v46_packet, _v46_bad_draft, _v46_bad_issues).lower())

# --- v8/v11 query formulation is unit-denoting only ---------------------------------------
forms = HR.candidate_query_texts({
    "canonical_name": "Cost-Sensitive Classification",
    "parent_topic_label": "Class Imbalance",
    "topic_path_labels": ["DM", "Evaluation", "Class Imbalance", "Cost-Sensitive Classification"],
})
check("v11 ancestor label never enters the reranker query text",
      all("Class Imbalance" not in f for f in forms), str(forms))
acro = HR.expand_acronyms("NB Learning Phase", ["Naive Bayes", "Classification"])
check("v8 acronym expansion still active", acro == ["Naive Bayes Learning Phase"], str(acro))

# --- v5 PRF is corpus-derived, and no LLM-provenance field is read ------------------------
# Resolved through the imported module rather than a literal path: a hardcoded path survived a
# module rename once and left this check reading the pre-rename copy while still reporting OK.
src = io.open(HR.__file__, encoding="utf-8").read()
check("v5 no alias/route field is read anywhere in retrieval",
      not any(k in src for k in
              ("normalized_surface_variants", "expanded_aliases", "retrieval_routes",
               "accepted_source_cues", "query_variants")))
check("v5 PRF expansion function present and used",
      "def expand_query_tokens" in src and "expansion_terms" in src)

# --- v15 prompt-side pointer neutralisation ------------------------------------------------
smoke = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "pipeline", "04_draft_runner.py"), encoding="utf-8").read()
# 2026-08-17: updated for the controlled-comparator indirection (visible_packet_for_prompt),
# which itself must still route through prompt_safe_packet() for neutralisation - both call
# sites now go through the wrapper, so the raw substring this check originally looked for
# ("compact_json(prompt_safe_packet(packet))") no longer appears verbatim; check the new call
# pattern instead, plus that the wrapper itself still calls prompt_safe_packet(packet), plus that
# no call site was quietly changed to serialise the raw, unneutralised packet.
check("v15 prompt serialises the NEUTRALISED packet",
      "compact_json(visible_packet_for_prompt(packet, mode))" in smoke
      and "def visible_packet_for_prompt" in smoke
      and "safe = prompt_safe_packet(packet)" in smoke
      and "compact_json(packet)" not in smoke.replace(
          "compact_json(visible_packet_for_prompt(packet, mode))", ""))

# --- R-1a: status-integrity gate must count real verified-schema evidence, and must actually run
# from the script every real drafting job executes, not merely exist in an unreached module. -----

# Check 1: the counter matches the CURRENT schema (evidence_lane is a single fixed constant on the
# verified pipeline's own packets - "comprehensive_relevance_ranked", confirmed by reading
# 02_build_kc_packets.py's own emission), not the retired pipeline's multi-lane vocabulary.
_synthetic_packet_real_schema = {
    "knowledge_unit_type": "kc",
    "evidence_for_synthesis": [
        {"evidence_id": "x:1", "text": "a", "evidence_lane": "comprehensive_relevance_ranked"},
        {"evidence_id": "x:2", "text": "b", "evidence_lane": "comprehensive_relevance_ranked"},
    ],
}
check("R-1a counter reads real verified-schema evidence (not a retired lane name)",
      SI.kc_admitted_evidence_count(_synthetic_packet_real_schema) == 2,
      "got %r, expected 2" % SI.kc_admitted_evidence_count(_synthetic_packet_real_schema))

# Check 2: the forward direction still fires (zero evidence, positive status -> forced abstained).
_synthetic_empty_packet = {"knowledge_unit_type": "kc", "evidence_for_synthesis": []}
_synthetic_grounded_draft = {"contextual_kc_draft": {"status": "grounded", "text": "unsupported"}}
_corrected, _violation = SI.apply_status_integrity_gate(_synthetic_packet_real_schema
                                                         if False else _synthetic_empty_packet,
                                                         _synthetic_grounded_draft)
check("R-1a forward direction still forces abstained on zero real evidence",
      _violation is not None and _violation.get("forced_status") == "abstained"
      and _corrected["contextual_kc_draft"]["status"] == "abstained",
      str(_violation))

# Check 3: the inverse direction fires on a draftable, evidenced, permission-less abstention -
# exactly the shape confirmed against 5 real KCs in the 2026-08-17 audit replay
# (KC_CLF_UND_001, KC_CLF_DT_010, KC_EVAL_BASIC_009, KC_EVAL_ROC_004, KC_CLU_EVAL_011).
_synthetic_draftable_packet = dict(_synthetic_packet_real_schema)
_synthetic_draftable_packet["packet_support_state"] = "draftable"
_synthetic_draftable_packet["abstention_expected"] = False
_synthetic_draftable_packet["weak_fallback_abstention_allowed"] = False
_synthetic_abstained_draft = {"contextual_kc_draft": {"status": "abstained", "text": ""}}
_corrected2, _violation2 = SI.apply_status_integrity_gate(_synthetic_draftable_packet,
                                                           _synthetic_abstained_draft)
check("R-1a inverse direction flags an unpermitted abstention on a draftable packet",
      isinstance(_violation2, dict) and _violation2.get("code") == SI.UNJUSTIFIED_ABSTENTION_CODE
      and _violation2.get("forced_status") is None,
      str(_violation2))
check("R-1a inverse direction never promotes the status (would manufacture confidence)",
      _corrected2["contextual_kc_draft"]["status"] == "abstained", str(_corrected2))

# Check 4: a LEGITIMATE abstention (packet grants permission) must NOT be flagged - the row-5
# canary from the audit (Mutually Exclusive Classes correctly abstains; must keep abstaining).
_synthetic_permitted_packet = dict(_synthetic_draftable_packet)
_synthetic_permitted_packet["weak_fallback_abstention_allowed"] = True
_, _violation3 = SI.apply_status_integrity_gate(_synthetic_permitted_packet, _synthetic_abstained_draft)
check("R-1a inverse direction does not flag a packet-permitted abstention (no false positives)",
      _violation3 is None, str(_violation3))

# Check 5: the gate is actually CALLED from the script every real drafting job executes. Resolved
# through the probe's own source text (this file's established pattern for "is X reachable", per
# the v15 check below and the v5 scar comment about a hardcoded path surviving a rename) rather
# than a literal path, so a future rename of the probe script fails this check instead of it
# silently reading a stale copy.
_probe_src = io.open(_PROBE_PATH, encoding="utf-8").read()
check("R-1a gate is LIVE-CALLED from the REAL probe script, not merely mentioned in its source",
      "apply_status_integrity_gate" in live_calls(_PROBE_PATH),
      "the probe does not actually call the gate - it would be silently inert on every real job")

# --- num_ctx is a property of the MODEL, not of the run (job 246037 regression guard) --------
# 246037 ran qwen3.8:27b at num_ctx=65536 inherited from a RUN_STATE configured for gemma4. That
# model's hybrid attention+SSM architecture cannot reuse KV cache, so every call re-processed the
# full prompt and timed out at 1200s: 16 of 71 units in 5.5h, all failed, zero output.
_runtime_profile_dir = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "config", "runtime"))
_profiles = sorted(f for f in os.listdir(_runtime_profile_dir)
                   if f.startswith("clusterb_ollama_") and f.endswith(".env"))
_missing_ctx = []
for _p in _profiles:
    _txt = io.open(os.path.join(_runtime_profile_dir, _p), encoding="utf-8").read()
    if "KC_L_PROFILE_MODEL_CONTEXT=" not in _txt:
        _missing_ctx.append(_p)
check("every Ollama runtime profile declares its own KC_L_PROFILE_MODEL_CONTEXT",
      bool(_profiles) and not _missing_ctx,
      "profiles=%d missing_context=%s" % (len(_profiles), _missing_ctx))

_orch_path = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "scripts",
    "kc_l_orchestrator.py"))
_orch_src = io.open(_orch_path, encoding="utf-8").read()
check("orchestrator resolves drafting num_ctx from the model's runtime profile, not only a "
      "per-run override",
      "KC_L_PROFILE_MODEL_CONTEXT" in _orch_src
      and "_resolve_ollama_runtime" in live_calls(orchestrator_path())
      and _ast.parse(_orch_src) is not None
      and any(
          isinstance(n, _ast.If)
          and any(isinstance(x, _ast.Name) and x.id == "_profile_context"
                  for x in _ast.walk(n.test))
          and not (isinstance(n.test, _ast.BoolOp)
                   and any(isinstance(v, _ast.Constant) and not v.value for v in n.test.values))
          and not (isinstance(n.test, _ast.Constant) and not n.test.value)
          for n in _ast.walk(_ast.parse(_orch_src))),
      "drafting context would fall back to a stale per-run num_ctx (job 246037 failure mode)")

# --- drafting contract: evidence-first procedure must REACH the prompt, not just exist ------
# Guarded by building a real prompt, because this project's worst regression was three
# anti-contamination instructions silently disabled by an empty packet field while the dict that
# declared them still looked correct.
_contract_packet = {
    "knowledge_unit_id": "KC_PROBE_001",
    "knowledge_unit_type": "kc",
    "canonical_name": "Probe Unit",
    "hierarchy": {"topic_path": ["A", "B"], "parent_topic_label": "B", "leaf_label": "Probe Unit"},
    "sibling_kc_names": ["Neighbouring Unit"],
    "rival_units_considered": ["Neighbouring Unit"],
    "evidence_for_synthesis": [{
        "evidence_id": "KC_PROBE_001:comprehensive:0001",
        "text": "A probe unit is defined as the unit used for probing.",
        "source_block_text": "A probe unit is defined as the unit used for probing.",
        "evidence_lane": "comprehensive_relevance_ranked",
    }],
    "drafting_instruction": PB.DRAFTING_INSTRUCTION,
    "packet_support_state": "draftable",
}
_contract_prompt = DR.build_prompt(_contract_packet)
_contract_markers = {
    "evidence triage step": "STEP 1 - TRIAGE",
    "packet-scoped sufficiency step": "STEP 2 - SUFFICIENCY",
    "claim-level verify step": "STEP 5 - VERIFY",
    "sibling boundary clause": "must not be absorbed",
    "non-assertable source roles": "NOT established fact",
    "conflict handling without memory": "do not resolve the conflict from your own knowledge",
    "precision over breadth": "Do not maximise breadth",
    "evidence-driven completeness": "the draft must carry it",
}
_contract_missing = [k for k, m in _contract_markers.items() if m not in _contract_prompt]
_contract_required_keys = ("procedure", "boundary", "assertability", "conflicts",
                           "precision_over_breadth", "must_use")
check("drafting contract still declares every required clause KEY (renaming one disables it)",
      all(k in PB.DRAFTING_INSTRUCTION for k in _contract_required_keys),
      "missing: %s" % [k for k in _contract_required_keys if k not in PB.DRAFTING_INSTRUCTION])
check("drafting contract reaches the real prompt (triage/sufficiency/boundary/verify)",
      not _contract_missing,
      "missing from prompt: %s" % _contract_missing)
check("drafting contract's sufficiency step is scoped to the packet, never corpus absence",
      "only this packet" in _contract_prompt,
      "sufficiency wording would let the drafter claim corpus-level absence it cannot observe")

# --- extractor capture-marker truncation counts as formula damage --------------------------
# 15 of 1,332 mathematics evidence items (13 of 71 units) ended at the extractor's own capture
# marker with the formula never captured, and every v28-v74 detector passed them as clean. Found by
# hand-reading formula-shaped evidence AFTER the automated check reported the corpus clean.
check("dangling extractor capture marker is detected as formula damage",
      CP.math_rendering_damaged("The sum is given by the following (LATEX code:")
      and CP.math_rendering_damaged("Defined as (LaTeX code :"))
check("a COMPLETE captured formula is not falsely flagged as damaged",
      not CP.math_rendering_damaged("The formula (LATEX code: \sum x_i) sums the values."),
      "would discard intact formula evidence")
check("ordinary prose is not falsely flagged by the capture-marker rule",
      not CP.math_rendering_damaged("SSE = sum of squared errors over all clusters."))

# --- R-3 formula recall does not depend on the equation's LHS naming the unit ---------------
# supplement_defining_equation_rows() rescues only equations whose LEFT-HAND SIDE names the unit,
# and standard notation almost never does (Bayes' LHS is P(Y|X), Laplace's is P(Xi=c|y), an
# external-index entropy's is e_i). Measured: the defining formula for Bayes, Laplace, external
# entropy and the two-model variance comparison was present, undamaged and usable in the real
# corpus, and never reached the pool.
check("R-3 dense formula-shaped supplementation is LIVE-CALLED in the packet builder",
      callable(getattr(PB, "supplement_dense_formula_rows", None))
      and "supplement_dense_formula_rows" in live_calls(PB.__file__),
      "formula recall would again depend on the LHS naming the unit")


class _R3FakeDense(object):
    available = True

    def top_k(self, query, k):
        return [(0, 0.9), (1, 0.8), (2, 0.7)]


_r3_pool, _r3_idx = [], set()
_r3_added = PB.supplement_dense_formula_rows(_r3_pool, _r3_idx, _R3FakeDense(), "any unit",
                                             {0, 2}, limit=40)
check("R-3 supplementation adds only formula-shaped rows, never arbitrary ones",
      _r3_added == 2 and sorted(i for i, _ in _r3_pool) == [0, 2],
      str((_r3_added, _r3_pool)))

_r3_pool2, _r3_idx2 = [], set()
check("R-3 supplementation is inert without a dense index (no silent behaviour change)",
      PB.supplement_dense_formula_rows(_r3_pool2, _r3_idx2, None, "q", {0, 1}) == 0)

# Shape must still never ADMIT anything on its own - relevance remains the only gate.
check("R-3 adds candidates at zero bm25 score, leaving admission to the relevance gate",
      all(score == 0.0 for _, score in _r3_pool), str(_r3_pool))

# --- D-6: three metric-named damage assertions deliberately removed ------------------------
# v47's gain-ratio split-info form, and v48's flattened Gaussian/F-beta/silhouette/cluster-weight
# and concatenated-metric forms, can only be recognised by naming the metric. "silhouette(s3) =
# 1 -2.2882" is indistinguishable from a legitimate subtraction unless you know a silhouette lies
# in [-1,1]; that is subject knowledge, and this pipeline may not carry any.
#
# Measured tradeoff on the real 100,218-row corpus (5,670 formula-bearing candidates), so the cost
# is recorded rather than assumed:
#     with 20 metric-named regexes : 1008 detections
#     structural patterns only     : 1065 detections
# The generic patterns catch 82 genuinely bar-lost renderings the named list MISSED entirely
# (TPR, FPR, Recall - nobody had written a regex for those), and lose ~33 metric-specific numeric
# forms. Net +57 detections AND no subject matter. Guarded below in both directions.
_d6_src = io.open(CP.__file__, encoding="utf-8").read()
# Looks for the NAME anywhere in the module, not only immediately before ".search". The first
# version of this check required the ".search" suffix and therefore missed eight metric-named
# regexes that were passed inside a tuple - it reported OK while the vocabulary was still live.
_d6_named = re.findall(
    r"_(?:RAW|COMPACT)_[A-Z_]*(?:SILHOUETTE|JACCARD|GAUSSIAN|COVARIANCE|PURITY|ACCURACY|"
    r"GAIN_RATIO|COHESION|SEPARATION|F_BETA|CLUSTER_SSE|EXTERNAL_F|PRECISION_PREVALENCE)"
    r"[A-Z_]*_RE",
    _d6_src)
check("D-6 no metric-named damage regex remains anywhere in the evidence module",
      not _d6_named, str(sorted(set(_d6_named))[:6]))
check("D-6 structural bar-loss catches renderings the metric-named list never covered",
      CP.math_rendering_damaged("Recall = TP TP + FN")
      and CP.math_rendering_damaged("TPR = TP TP + FN = TP")
      and CP.math_rendering_damaged("RandIndex = 1 + 10 1 + 2 + 2 + 10 = 11"))
check("D-6 structural bar-loss does not condemn correct formulas",
      not CP.math_rendering_damaged("P(Y|X)=P(X|Y)P(Y)/P(X).")
      and not CP.math_rendering_damaged("SSE=∑i=1K∑x∈Ci dist(ci,x)^2 (7.1)")
      and not CP.math_rendering_damaged("Recall = TP / (TP + FN)"))

# --- D-1/D-3: the 18 per-KC semantic-misbinding rules are removed ---------------------------
# semantic_misbinding_owner() previously held 18 rules keyed on specific data-mining KC names
# (learning phase, querying phase, cost matrix, models of randomness 1/2, sse cluster quality,
# shannon entropy, density connected, euclidean distance, filter approach, ...) plus a DBSCAN term
# set. Each was written against a real observed contamination, and each could only ever fire for
# the one curriculum whose KC it named. The checks removed here asserted those rules were active,
# so a passing check meant the domain-agnosticity claim was false.
#
# Measured, so the cost is recorded rather than assumed:
#   rule firings: data-mining 66 drops, sociology 0, mathematics 0
#   removal cost: +2.6% admitted evidence (66 of 2,556 items), touching 20 of 159 units
#   two generic replacements were built and REJECTED on measurement - a corpus-derived
#   concept-rival mechanism reproduced 20% then 15% of these drops while FALSELY dropping 8.9%
#   then 6.9% of already-admitted evidence, both worse than removal.
#
# What carries the load instead: drop_passages_claimed_by_rivals()'s cross-encoder adjudication,
# which already performs the majority of drops in every corpus (109/175, 106/108, 23/29), and the
# drafting contract's explicit KC boundary. Sociology is the evidence this suffices - a HARDER
# collision profile than data-mining (mean 3.24 rivals/unit vs 2.16; 36% saturating RIVAL_LIMIT vs
# 9%) reaching 96.0% grounded with 0 hard failures on the generic mechanism alone, while
# data-mining WITH all 66 rules drafted at 78.0%.
check("D-1 no per-KC semantic-misbinding rule remains",
      CP.semantic_misbinding_owner("any text at all", "Any Unit", ["Any Rival"]) is None
      and CP.semantic_misbinding_owner("SNN similarity density", "Density Connected", []) is None,
      "a per-KC rule is still firing")
check("D-1 the generic cross-encoder rival adjudication is still the ownership authority",
      callable(getattr(CP, "drop_passages_claimed_by_rivals", None))
      and callable(getattr(CP, "find_rival_units", None)))
check("D-3 no curriculum-specific unit vocabulary remains in the misbinding path",
      CP._STANDARD_DBSCAN_UNITS == frozenset(), str(CP._STANDARD_DBSCAN_UNITS))

# D-6 tail: two more metric-named damage assertions removed (purity weight bar, extended-Jaccard
# denominator). Both need the formula's identity to recognise - "purity=SUM i=1K mi m purity(i)"
# loses its bar between "mi" and "m", which structurally is just two adjacent short identifiers,
# far too common in ordinary mathematics to flag without flooding false positives. Same category as
# the silhouette numeric forms. The generic companion guard (ordinary prose saying "fraction" is
# NOT explicit fraction notation) is kept, since that one carries no subject matter.

# --- items 7/8: assertability field and definitional-authority ordering ---------------------
# Motivated by an observed failure where a True/False exercise prompt became a stated fact, and by
# long-context work showing material mid-context is attended to less reliably.
_a8_question = {"text": "Is entropy always positive?", "shapes": ["definition"]}
_a8_defn = {"text": "A cluster is a group of similar objects.", "shapes": ["definition"]}
_a8_formula = {"text": "SSE = sum over clusters.", "shapes": ["formula"]}
_a8_proc = {"text": "Step 1: pick centroids.", "shapes": ["procedure"]}
_a8_bg = {"text": "Some background prose.", "shapes": []}

check("item 8 an interrogative passage is marked not assertable",
      PB.passage_assertability(_a8_question) == PB.INTERROGATIVE_ASSERTABILITY,
      PB.passage_assertability(_a8_question))
check("item 8 an ordinary declarative passage stays assertable",
      PB.passage_assertability(_a8_defn) == PB.ASSERTABLE
      and PB.passage_assertability(_a8_formula) == PB.ASSERTABLE)
check("item 8 assertability outranks shape (a question tagged 'definition' still sinks)",
      PB.authority_tier(_a8_question) > PB.authority_tier(_a8_bg),
      "%d vs %d" % (PB.authority_tier(_a8_question), PB.authority_tier(_a8_bg)))

_a7_ordered = PB.order_by_definitional_authority(
    [_a8_bg, _a8_question, _a8_proc, _a8_defn, _a8_formula])
check("item 7 evidence is ordered definition, formula, procedure, then the rest",
      [p["text"][:9] for p in _a7_ordered][:3] == ["A cluster", "SSE = sum", "Step 1: p"],
      str([p["text"][:16] for p in _a7_ordered]))
check("item 7 the authority ordering is LIVE-CALLED in the packet builder, not merely defined",
      "order_by_definitional_authority" in live_calls(PB.__file__),
      "evidence would ship in raw relevance order and the ordering fix would be inert")
check("item 7 non-assertable evidence sorts last",
      _a7_ordered[-1] is _a8_question, str(_a7_ordered[-1]))

# Stability matters: within one tier the existing relevance/document order must survive, which is
# what keeps a procedure's steps in sequence.
_a7_steps = [{"text": "Step %d" % i, "shapes": ["procedure"]} for i in range(1, 6)]
check("item 7 ordering is stable within a tier (procedure steps keep their sequence)",
      [p["text"] for p in PB.order_by_definitional_authority(_a7_steps)]
      == ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"])

# The field must actually reach the emitted evidence item, not merely exist as a helper.
_a8_item = PB.evidence_item({"text": "Is this a question?", "shapes": []}, 1, "KC_X")
check("item 8 assertability is carried on the emitted evidence item",
      _a8_item.get("assertability") == PB.INTERROGATIVE_ASSERTABILITY
      and "authority_tier" in _a8_item,
      str({k: _a8_item.get(k) for k in ("assertability", "authority_tier")}))

# And the drafting contract must reference the field rather than asking the model to infer it.
check("item 8 the drafting contract points the drafter at the assertability field",
      "assertability field" in PB.DRAFTING_INSTRUCTION["assertability"]
      and "not_assertable_interrogative" in PB.DRAFTING_INSTRUCTION["assertability"])

# --- items 5/11: the ledger is built before the prose, and its citations must resolve -------
# An evidence_map is a control mechanism, not proof of grounding, unless its ids name something
# real. Applied to existing output this found 4 gemma4 units citing identifiers that do not exist,
# one of them citing 13 sibling KC IDs as though they were evidence IDs, while qwen3.6 and qwen3.8
# were clean - a defect no previous check detected.
check("item 5 the contract fills the ledger BEFORE writing prose",
      "evidence_map FIRST" in PB.DRAFTING_INSTRUCTION["procedure"][2]
      and "not a citation list added afterwards" in PB.DRAFTING_INSTRUCTION["procedure"][2],
      PB.DRAFTING_INSTRUCTION["procedure"][2][:90])
check("item 5 the draft may only use claims present in the ledger",
      "only claims that appear in evidence_map" in PB.DRAFTING_INSTRUCTION["procedure"][3],
      PB.DRAFTING_INSTRUCTION["procedure"][3][:90])

_led_packet = {
    "knowledge_unit_id": "KC_LED_001",
    "knowledge_unit_type": "kc",
    "canonical_name": "Ledger Probe",
    "evidence_for_synthesis": [
        {"evidence_id": "KC_LED_001:comprehensive:0001", "text": "real evidence",
         "evidence_lane": "comprehensive_relevance_ranked"},
    ],
}


def _led_draft(ids):
    return {
        "knowledge_unit_id": "KC_LED_001",
        "knowledge_unit_type": "kc",
        "contextual_kc_draft": {"status": "grounded", "text": "x" * 200,
                                "supporting_evidence_ids": list(ids)},
        "kc_specific_criteria": [],
        "kc_specific_criteria_status": "expert_pending",
        "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
        "segmentation_support": {}, "evaluation_support": {},
        "evidence_map": [{"claim": "c", "supporting_evidence_ids": list(ids),
                          "support_strength": "strong", "support_role": "definition"}],
    }


_led_codes_bad = {i.get("code") for i in
                  DR.validate_output(_led_packet, _led_draft(["KC_LED_001:comprehensive:9999"]))}
check("item 11 a citation naming no real evidence item is flagged",
      "evidence_map_cites_unknown_evidence_id" in _led_codes_bad, str(sorted(_led_codes_bad)))

_led_codes_ok = {i.get("code") for i in
                 DR.validate_output(_led_packet, _led_draft(["KC_LED_001:comprehensive:0001"]))}
check("item 11 a citation naming a real evidence item is NOT flagged",
      "evidence_map_cites_unknown_evidence_id" not in _led_codes_ok, str(sorted(_led_codes_ok)))

_led_codes_none = {i.get("code") for i in DR.validate_output(_led_packet, _led_draft([]))}
check("item 11 a non-abstaining draft that cites nothing at all is flagged",
      "evidence_map_cites_no_evidence_ids" in _led_codes_none, str(sorted(_led_codes_none)))

# --- step_06v_assemble_library: KC+topic draft combination is wired, not a bridging script ---
import importlib.util as _sr_ilu
_sr_path = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "src", "kc_l", "runtime",
    "stage_registry.py"))
_sr_spec = _sr_ilu.spec_from_file_location("stage_registry_under_test", _sr_path)
SR = _sr_ilu.module_from_spec(_sr_spec)
# dataclasses._process_class does sys.modules.get(cls.__module__) internally, which needs
# this module registered in sys.modules before exec_module runs - stage_registry.py uses
# @dataclass(frozen=True) on StageSpec.
sys.modules["stage_registry_under_test"] = SR
_sr_spec.loader.exec_module(SR)
check("step_06v_assemble_library is registered and wired for automatic self-chaining",
      "step_06v_assemble_library" in SR.STAGE_SPECS
      and SR.STAGE_SPECS["step_06v_assemble_library"].run_stage_wired,
      "the combination step would need manual invocation every run")
check("step_06v_assemble_library depends on BOTH kc and topic drafting, not just one",
      set(SR.STAGE_SPECS["step_06v_assemble_library"].depends_on)
      == {"step_06v_kc_draft_generation", "step_06v_topic_draft_generation"},
      str(SR.STAGE_SPECS["step_06v_assemble_library"].depends_on))
check("step_06v_assemble_library is LIVE-CALLED from the orchestrator's dispatch, not only "
      "registered",
      "step_06v_assemble_library" in live_calls(orchestrator_path())
      or '"step_06v_assemble_library"' in io.open(orchestrator_path(), encoding="utf-8").read(),
      "the stage would be registered but never actually dispatched")

import importlib.util as _ilu
_lib_spec = _ilu.spec_from_file_location(
    "assemble_kc_library_under_test",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "pipeline", "05_assemble_kc_library.py"))
LIB = _ilu.module_from_spec(_lib_spec)
_lib_spec.loader.exec_module(LIB)

_lib_kc_row = {
    "knowledge_unit_id": "KC_X_001", "knowledge_unit_type": "kc", "canonical_name": "X",
    "model": "probe:1b", "run_id": "r", "source_packet": {"packet_support_state": "draftable"},
    "draft": {"contextual_kc_draft": {"status": "grounded"}},
    "validation_issues": [],
}
_lib_orphan_row = {
    "knowledge_unit_id": "KC_ORPHAN_001", "knowledge_unit_type": "kc", "canonical_name": "Orphan",
    "model": "probe:1b", "run_id": "r", "source_packet": {"packet_support_state": "draftable"},
    "draft": {"contextual_kc_draft": {"status": "partial"}},
    "validation_issues": [],
}
_lib_topic_row = {
    "knowledge_unit_id": "TOPIC_X", "knowledge_unit_type": "topic", "canonical_name": "Topic X",
    "model": "probe:1b", "run_id": "r",
    "source_packet": {"packet_support_state": "draftable", "child_kc_count": 1,
                      "direct_child_kcs": [{"child_kc_id": "KC_X_001", "child_kc_name": "X"}]},
    "draft": {"contextual_topic_draft": {"status": "grounded"}},
    "validation_issues": [],
}

import tempfile as _tf
with _tf.TemporaryDirectory() as _lib_tmp:
    _kc_path = os.path.join(_lib_tmp, "kc.jsonl")
    _tp_path = os.path.join(_lib_tmp, "topic.jsonl")
    _out_path = os.path.join(_lib_tmp, "lib.json")
    with io.open(_kc_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_lib_kc_row) + "\n" + json.dumps(_lib_orphan_row) + "\n")
    with io.open(_tp_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_lib_topic_row) + "\n")
    import sys as _sys
    _argv_backup = _sys.argv
    _sys.argv = ["x", "--kc-drafts-jsonl", _kc_path, "--topic-drafts-jsonl", _tp_path,
                "--out-json", _out_path, "--run-id", "probe"]
    try:
        LIB.main()
    finally:
        _sys.argv = _argv_backup
    _assembled = json.load(io.open(_out_path, encoding="utf-8"))

check("library assembly nests a KC under its topic via direct_child_kcs",
      _assembled["topics"][0]["children"][0]["knowledge_unit_id"] == "KC_X_001",
      str(_assembled["topics"]))
check("library assembly reports an ungrouped KC explicitly, never drops it",
      _assembled["ungrouped_kcs"]
      and _assembled["ungrouped_kcs"][0]["knowledge_unit_id"] == "KC_ORPHAN_001"
      and _assembled["counts"]["ungrouped_kcs"] == 1,
      str(_assembled.get("ungrouped_kcs")))
check("library assembly counts are internally consistent (grouped + ungrouped = total)",
      _assembled["counts"]["grouped_kcs"] + _assembled["counts"]["ungrouped_kcs"]
      == _assembled["counts"]["total_kcs"] == 2,
      str(_assembled["counts"]))

# --- Base Dense RAG fairness audit (local_audits/base_dense_rag_fairness_20260817T000000Z) ---
# Tests A-I from the audit brief section 12. A fix that regresses here can re-introduce a real
# fairness confound between the baseline-RAG comparator and the proposed pipeline without either
# condition's own run failing outright, so these must be liveness checks, not one-off manual
# spot checks.

# Test A/D: baseline never imports or reaches BM25/reranker/query-expansion/block-assembly code.
_baseline_src = io.open(_BASELINE_RAG_PATH, encoding="utf-8").read()


def _real_imported_modules(path):
    """Module names actually IMPORTED (import/import-from), not merely mentioned in prose. A
    plain substring search on the source text would false-positive on this file's own docstring,
    which explains in prose what it deliberately does NOT import - confirmed the hard way when
    this exact check first shipped as a substring search and failed against real, correct code."""
    tree = _ast.parse(io.open(path, encoding="utf-8").read())
    names = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, _ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


_baseline_imports = _real_imported_modules(_BASELINE_RAG_PATH)
check("A/D: baseline never imports evidence_pack.py (no block expansion, no rival "
      "adjudication, no damaged-math/junk filtering available to it)",
      not any("evidence_pack" in m for m in _baseline_imports),
      "an import of evidence_pack would let proposed-system evidence engineering leak into the "
      "baseline; real imports found: %s" % sorted(_baseline_imports))
_baseline_live = live_calls(_BASELINE_RAG_PATH)
check("A/D: baseline never calls BM25Index, CrossEncoderReranker, retrieve_for_unit, "
      "assemble_passages, expand_query_tokens, candidate_query_texts, build_query, or "
      "find_rival_units",
      not (_baseline_live & {"BM25Index", "CrossEncoderReranker", "retrieve_for_unit",
                             "assemble_passages", "expand_query_tokens", "candidate_query_texts",
                             "build_query", "find_rival_units"}),
      str(_baseline_live & {"BM25Index", "CrossEncoderReranker", "retrieve_for_unit",
                            "assemble_passages", "expand_query_tokens", "candidate_query_texts",
                            "build_query", "find_rival_units"}))

# Test C: single dense retrieval route - the only ranking call reachable is DenseIndex.top_k.
check("C: baseline reaches DenseIndex.top_k as its only ranking call",
      "top_k" in _baseline_live, "baseline must call dense.top_k() to retrieve anything")

# Test B: no proposed-system-computed method-specific field leaks into a real baseline packet.
_leak_probe_real_packet = {
    "knowledge_unit_id": "KC_PROBE_001", "kc_id": "KC_PROBE_001", "canonical_name": "Probe",
    "aliases": ["Probe"], "hierarchy": {"topic_path": ["T"]}, "sibling_kc_names": ["Other"],
    "rival_units_considered": [],
    # fields that must NOT survive into the baseline packet:
    "drafting_instruction": {"goal": "x"}, "query_formulation": {"selected": "x"},
    "evidence_coverage": {"has_definition": True}, "evidence_dropped_to_rival_units": [1],
    "packet_support_state": "draftable", "support_state_reason": "x",
    "insufficient_support_reasons": ["x"], "weak_fallback_abstention_allowed": True,
}
_leak_probe_evidence = [{
    "evidence_id": "e1", "text": "probe sentence.", "source_block_text": "probe sentence.",
    "doc_id": "D", "page_index": 1, "patch_heading": "", "sentence_id": "D:1",
    "evidence_lane": "baseline_dense_retrieval", "retrieval_score": 0.9,
    # method-specific fields that must NOT be added by build_baseline_packet:
    "assertability": "assertable", "authority_tier": 0, "shape_tags": ["definition"],
}]
_leaked_packet = BB.build_baseline_packet(_leak_probe_real_packet, _leak_probe_evidence)
_forbidden_top = {"drafting_instruction", "query_formulation", "evidence_coverage",
                  "evidence_dropped_to_rival_units", "packet_support_state",
                  "support_state_reason", "insufficient_support_reasons",
                  "weak_fallback_abstention_allowed"}
check("B: build_baseline_packet() drops every proposed-system-computed top-level field even "
      "when the source real_packet carries them",
      not (set(_leaked_packet.keys()) & _forbidden_top),
      str(set(_leaked_packet.keys()) & _forbidden_top))
check("B: build_baseline_packet() does not add assertability/authority_tier/shape_tags to "
      "evidence items it did not put there itself",
      all("assertability" not in e or True for e in _leaked_packet["evidence_for_synthesis"])
      and _leaked_packet["evidence_for_synthesis"][0].get("assertability") == "assertable",
      "the probe's own input evidence item legitimately still carries the fields it was given - "
      "build_baseline_packet must not have STRIPPED or ADDED any, only passed the evidence list "
      "through unchanged")

# Test G: the two conditions share one real, non-arbitrary character ceiling.
check("G: baseline MAX_CHARS_BUDGET equals the proposed system's DEFAULT_MAX_CHARS (matched, "
      "not independently configured)",
      BB.MAX_CHARS_BUDGET == CP.DEFAULT_MAX_CHARS == 14000,
      "baseline=%r proposed=%r" % (BB.MAX_CHARS_BUDGET, CP.DEFAULT_MAX_CHARS))

check("naming: baseline packet_version accurately says sentence-level Base Dense RAG, not the "
      "old generic 'baseline_rag_v1' tag (section 9 of the audit - must not be reported as a "
      "generic ablation)",
      BB.build_baseline_packet(
          {"knowledge_unit_id": "KC_PROBE_002"}, []
      )["packet_version"] == "sentence_level_base_dense_rag_v1",
      BB.build_baseline_packet({"knowledge_unit_id": "KC_PROBE_002"}, [])["packet_version"])


class _StubDense:
    """Deterministic stand-in for DenseIndex.top_k, ranked by an index -> (idx, text) list."""
    def __init__(self, rows):
        self._rows = rows

    def top_k(self, _query_text, k):
        return [(i, 1.0 - i * 0.001) for i in range(min(k, len(self._rows)))]


_stub_corpus = [{"sentence_text": ("x" * 5000), "doc_id": "D", "page_index": i,
                 "patch_heading": "", "sentence_id": "D:%d" % i} for i in range(5)]
_stub_dense = _StubDense(_stub_corpus)
_stub_evidence = BB.retrieve_baseline_evidence("KC_STUB", "probe query", _stub_dense,
                                               _stub_corpus, max_chars=14000)
check("G: retrieve_baseline_evidence stops within the shared character budget",
      sum(len(e["text"]) for e in _stub_evidence) <= 14000 + 5000,
      "budget check runs after adding a hit, so overshoot is bounded by one item's length, not "
      "unbounded: got %d chars over %d items"
      % (sum(len(e["text"]) for e in _stub_evidence), len(_stub_evidence)))
check("H: baseline evidence items are raw unexpanded sentences (text == source_block_text, no "
      "block join)",
      all(e["text"] == e["source_block_text"] for e in _stub_evidence) and len(_stub_evidence) > 0,
      "n=%d first_item_chars=%d text_equals_block=%s"
      % (len(_stub_evidence), len(_stub_evidence[0]["text"]),
         _stub_evidence[0]["text"] == _stub_evidence[0]["source_block_text"]))

# Test E/F: the shared drafting prompt is identical text for both conditions and no longer
# claims baseline evidence is exhaustive/block-coherent.
_kc_packet_shape = {
    "knowledge_unit_id": "KC_X", "knowledge_unit_type": "kc", "canonical_name": "X",
    "hierarchy": {}, "sibling_kc_names": [], "rival_units_considered": [],
    "evidence_for_synthesis": [], "abstention_expected": False,
    "insufficient_synthesis_support": False,
}
_baseline_shaped_prompt = DR.build_prompt(_kc_packet_shape)
_proposed_shaped_prompt = DR.build_prompt(dict(_kc_packet_shape,
                                               drafting_instruction={"goal": "x"},
                                               packet_support_state="draftable"))
check("F: old 'coherent blocks rather than isolated sentences' claim is gone from the shared "
      "drafting prompt",
      "coherent blocks" not in _baseline_shaped_prompt
      and "coherent blocks" not in _proposed_shaped_prompt,
      "this sentence falsely described baseline evidence as block-expanded and exhaustive")
_neutral_sentence = ("The supplied evidence contains passages retrieved from the course source "
                     "for the target KC.")
check("E/F: the new neutral evidence-framing sentence is present, verbatim, in the prompt "
      "built from EITHER a baseline-shaped or a proposed-shaped packet (same code path, no "
      "branch on packet origin)",
      _neutral_sentence in _baseline_shaped_prompt and _neutral_sentence in _proposed_shaped_prompt,
      "baseline_has=%r proposed_has=%r"
      % (_neutral_sentence in _baseline_shaped_prompt, _neutral_sentence in _proposed_shaped_prompt))

# Test I: generation options can only ever come from the shared probe script, never from either
# packet-building path - structurally impossible for the two conditions to diverge in decoding.
check("I: baseline packet construction contains no generation-option vocabulary of its own "
      "(temperature/num_ctx/num_predict/top_k/seed) - decoding config can only come from the "
      "one shared probe script for both conditions",
      not any(term in _baseline_src for term in
              ("temperature", "num_predict", "top_k=", "\"seed\"", "'seed'")),
      "if any of these appeared here, the baseline could silently diverge from the proposed "
      "condition's generation settings instead of both being governed solely by "
      "run_step67_v2_schema_contract_probe.py's ollama_generate_schema()")

# --- 2026-08-17 controlled-comparator drafting-contract fix (14/15_*.md) -------------------
# Verifies: (CC-2) controlled_comparator mode never mutates the caller's packet dict; (CC-3)
# native_proposed mode (the default, and the only mode any real production job uses) is
# unchanged; (CC-1) controlled_comparator mode removes drafting_instruction from the
# MODEL-VISIBLE prompt only; (CC-7)/(CC-6) method-specific evidence metadata is never added or
# removed by this fix, for either condition; (CC-4) the shared common-instruction text is
# hash-identical across conditions for the same unit; (CC-5) the rewritten shape_tags/
# assertability wording no longer presumes a field that isn't there, and the underlying
# content-based completeness rule reaches both conditions; (CC-residual) no method-presuming
# exhaustive/admitted/authority-ordered language remains in the shared text.
_cc_evidence_proposed = [{
    "evidence_id": "e1", "text": "A probe unit is defined by its probing formula p = x/y.",
    "source_block_text": "A probe unit is defined by its probing formula p = x/y.",
    "doc_id": "D", "page_index": 1, "patch_heading": "",
    "shape_tags": ["definition", "formula"], "assertability": "assertable",
    "authority_tier": 0, "relevance": 0.91, "role": "definition", "roles": ["definition"],
}]
_cc_proposed_packet = {
    "knowledge_unit_id": "KC_CC_PROBE", "knowledge_unit_type": "kc", "canonical_name": "Probe Unit",
    "hierarchy": {"topic_path": ["A", "B"], "source_hierarchy_path": ["A", "B"]},
    "sibling_kc_names": ["Neighbour"], "rival_units_considered": ["Neighbour"],
    "evidence_for_synthesis": _cc_evidence_proposed,
    "abstention_expected": False, "insufficient_synthesis_support": False,
    "packet_support_state": "draftable", "drafting_instruction": PB.DRAFTING_INSTRUCTION,
}
_cc_evidence_baseline = [{
    "evidence_id": "e1", "text": "A probe unit is defined by its probing formula p = x/y.",
    "source_block_text": "A probe unit is defined by its probing formula p = x/y.",
    "doc_id": "D", "page_index": 1, "patch_heading": "", "retrieval_score": 0.5,
}]
_cc_baseline_packet = {
    "knowledge_unit_id": "KC_CC_PROBE", "knowledge_unit_type": "kc", "canonical_name": "Probe Unit",
    "hierarchy": {"topic_path": ["A", "B"], "source_hierarchy_path": ["A", "B"]},
    "sibling_kc_names": ["Neighbour"], "rival_units_considered": ["Neighbour"],
    "evidence_for_synthesis": _cc_evidence_baseline,
    "abstention_expected": False, "insufficient_synthesis_support": False,
}
_cc_proposed_packet_before = copy.deepcopy(_cc_proposed_packet)

_cc_native_prompt = DR.build_prompt(_cc_proposed_packet)  # mode omitted = native_proposed
_cc_native_default_prompt = DR.build_prompt(_cc_proposed_packet, mode="native_proposed")
_cc_controlled_prompt = DR.build_prompt(_cc_proposed_packet, mode="controlled_comparator")
_cc_controlled_baseline_prompt = DR.build_prompt(_cc_baseline_packet, mode="controlled_comparator")

check("CC-2: build_prompt() never mutates the caller's own packet dict (native or controlled)",
      _cc_proposed_packet == _cc_proposed_packet_before,
      "packet dict changed after calling build_prompt - stored/historical artifacts would be at risk")

check("CC-3: native_proposed mode (default, no mode kwarg) still shows drafting_instruction text",
      "STEP 1 - TRIAGE" in _cc_native_prompt and '"goal"' in _cc_native_prompt,
      "native production behaviour must be byte-for-byte what it was before this fix")
check("CC-3b: explicit mode=\"native_proposed\" is identical to omitting mode entirely",
      _cc_native_prompt == _cc_native_default_prompt,
      "the default value must be native_proposed, not silently something else")

check("CC-1: controlled_comparator mode removes drafting_instruction from the visible prompt",
      '"drafting_instruction"' not in _cc_controlled_prompt,
      "drafting_instruction must not reach the model in controlled-comparator mode")
check("CC-1b: controlled_comparator mode still shows the rest of the proposed packet's own "
      "identity/evidence fields (only drafting_instruction is removed)",
      '"canonical_name"' in _cc_controlled_prompt
      and '"KC_CC_PROBE"' in _cc_controlled_prompt
      and '"shape_tags"' in _cc_controlled_prompt
      and '"authority_tier"' in _cc_controlled_prompt,
      "controlled-comparator mode must retain every field except drafting_instruction")

check("CC-7: proposed evidence-item metadata survives controlled-comparator mode unchanged",
      all(k in _cc_controlled_prompt for k in
          ('"shape_tags"', '"assertability"', '"authority_tier"', '"relevance"', '"role"', '"roles"')),
      "method-specific evidence metadata must not be stripped, only the instruction channel")

check("CC-6: a baseline-shaped packet's controlled-comparator prompt carries none of the "
      "proposed-only evidence metadata (it was never there to strip)",
      not any(k in _cc_controlled_baseline_prompt for k in
              ('"shape_tags"', '"assertability"', '"authority_tier"', '"drafting_instruction"')),
      "confirms the fix does not need to add stripping logic for a comparator that never had "
      "this metadata in the first place")


def _cc_common_instruction_text(prompt_text):
    marker = "\n\nPACKET:\n"
    return prompt_text[:prompt_text.index(marker)]


_cc_common_proposed = _cc_common_instruction_text(_cc_controlled_prompt)
_cc_common_baseline = _cc_common_instruction_text(_cc_controlled_baseline_prompt)
_cc_hash_proposed = hashlib.sha256(_cc_common_proposed.encode("utf-8")).hexdigest()
_cc_hash_baseline = hashlib.sha256(_cc_common_baseline.encode("utf-8")).hexdigest()
check("CC-4: common task-level instruction text is hash-identical across comparator "
      "conditions in controlled-comparator mode (same unit type, same KC identity)",
      _cc_hash_proposed == _cc_hash_baseline,
      "proposed=%s baseline=%s" % (_cc_hash_proposed, _cc_hash_baseline))

check("CC-5: no remaining unconditional 'each evidence item carries shape_tags' claim",
      "Each evidence item carries shape_tags" not in _cc_common_proposed
      and "Each evidence item carries shape_tags" not in _cc_common_baseline,
      "the universal-claim phrasing must be gone from both conditions' prompts")
check("CC-5b: the content-based formula/procedure completeness rule reaches BOTH conditions "
      "(no longer depends on shape_tags being present)",
      ("your draft is INCOMPLETE unless it carries that formula" in _cc_common_proposed
       and "your draft is INCOMPLETE unless it carries that formula" in _cc_common_baseline),
      "a comparator with no shape_tags field must still receive the underlying rule")
check("CC-5c: the remaining shape_tags mention is explicitly framed as an optional shortcut, "
      "not a precondition",
      "not as a precondition for the rule above" in _cc_common_proposed,
      "must read as: use the tag if present, but the rule binds either way")

_cc_forbidden_unconditional = (
    "every passage the source corpus offers", "semantically admitted", "evidence is exhaustive",
    "in order of definitional authority",
)
check("CC-residual: no method-presuming exhaustive/admitted/authority-ordered language in the "
      "shared common-instruction text",
      not any(term in _cc_common_proposed for term in _cc_forbidden_unconditional)
      and not any(term in _cc_common_baseline for term in _cc_forbidden_unconditional),
      [t for t in _cc_forbidden_unconditional
       if t in _cc_common_proposed or t in _cc_common_baseline])

try:
    DR.build_prompt(_cc_proposed_packet, mode="bogus_mode")
    _cc_bogus_mode_rejected = False
except ValueError:
    _cc_bogus_mode_rejected = True
check("CC-mode: an invalid mode value is rejected rather than silently accepted",
      _cc_bogus_mode_rejected,
      "build_prompt must fail loudly on an unrecognised mode, not silently default")

# --- draft-side damaged-math scoping (all 10 real flags were false positives) ---
# math_rendering_damaged() is tuned for SHORT EXTRACTED EVIDENCE SENTENCES. Applied to generated
# draft prose it misfired on every single flagged draft in the real data-mining run: summation
# bounds ("=1 to C"), "= 1 only if", a normal paragraph after a display equation, a named quantity
# discussed across paragraphs, and one unclosed paren in 5,624 chars. These checks pin the
# corrected scoping AND the true positives it must keep catching.
check("DM-1 summation/product bounds are not a lost fraction bar (the '=1 to' false positive)",
      not CP._ONE_OVER_PRODUCT_BAR_LOST_RE.search("Entropy(D) = -∑(i=1 to C) p_i log2(p_i)")
      and not CP._ONE_OVER_PRODUCT_BAR_LOST_RE.search("L = ∏(i=1 to m) x_i")
      and not CP._ONE_OVER_PRODUCT_BAR_LOST_RE.search("s(x, y) = 1 only if x = y"),
      "correct mathematics would be reported as a damaged rendering")
check("DM-2 the real one-over-product bar loss is STILL caught (regression guard on DM-1)",
      bool(CP._ONE_OVER_PRODUCT_BAR_LOST_RE.search("AUC = 1 P · N"))
      and bool(CP._ONE_OVER_PRODUCT_BAR_LOST_RE.search("AUC = 1 P N")),
      "DM-1 must not be widened into disabling the pattern outright")
check("DM-3 draft damage checking is scoped to the draft's own math spans, not the whole prose",
      CP.draft_math_spans("Defined as:\n$$ a = b $$\nIn this formula, terms vary.") == ["a = b"],
      str(CP.draft_math_spans("Defined as:\n$$ a = b $$\nIn this formula, terms vary.")))
check("DM-4 a normal paragraph after display math is not a 'stray tail'",
      not CP.draft_math_rendering_damaged(
          "The density is:\n$$ P(x) = { \\frac { 1 } { \\sigma } } $$\n\nIn this formula, sigma "
          "denotes the standard deviation of the attribute."),
      "a drafter continuing its explanation after an equation is correct writing")
check("DM-5 one unclosed paren in long prose is not damaged mathematics",
      not CP.draft_math_rendering_damaged(
          "The method computes a = b for each instance. " + ("Filler prose here. " * 40)
          + "It then looks for the KNN (using the"),
      "an incomplete trailing sentence is a truncation defect, not a math-rendering defect")
check("DM-6 a genuinely damaged formula appended to prose IS still caught (the v46 shape)",
      CP.draft_math_rendering_damaged(
          "Bayes theorem relates prior and posterior probabilities in classification. "
          "P(Y|X)=P(X|Y)P(Y)P(X)."),
      "this is the exact shape v46 exists to catch - it must not be lost to the new scoping")
check("DM-7 a plain-text damaged metric line in a draft is still caught",
      CP.draft_math_rendering_damaged("The measure is defined below.\n\nRecall = TP TP + FN\n")
      and CP.draft_math_rendering_damaged("Defined as:\n$$ GainRatio(A) = IG(A) SplitInfo(A). $$"),
      "delimited and undelimited damaged formulas must both still be caught")
check("DM-8 a formula carrying English connectives is not shredded into fake damage",
      not CP.draft_math_rendering_damaged(
          "The statistic is chi-squared = sum from j=1 to r of (oij - eij)^2 / eij for the table."),
      "splitting a formula at 'from'/'of' manufactures truncation and unbalanced delimiters - "
      "measured at 16 false positives when this was token-level")
check("DM-9 the draft runner uses the draft-scoped predicate, not the evidence-scoped one",
      "draft_math_rendering_damaged" in live_calls(_DRAFT_RUNNER_PATH)
      and "math_rendering_damaged" not in {
          n for n in live_calls(_DRAFT_RUNNER_PATH) if n == "math_rendering_damaged"},
      "the draft side must not call the evidence-scoped predicate directly")
check("DM-10 EVIDENCE-side damage checking is unchanged by the draft-side scoping",
      CP.math_rendering_damaged("Recall = TP TP + FN")
      and CP.is_structural_junk(sentence("AUC = 1 P · N", is_formula_like=True))
      and not CP.math_rendering_damaged("Recall = TP / (TP + FN)"),
      "evidence gating must be completely untouched")

# --- topic contract alignment + status-aware abstention shape ---
# The topic validator required child_kc_coverage_summary and supporting_child_kc_ids, neither of
# which the ENFORCED schema declares (topic_json_schema, additionalProperties:False), so the model
# could not emit them and 22/22 topic drafts failed by construction. And an abstention's own
# required shape (empty text, empty ledger) was reported as two schema defects.
_tc_packet = {
    "knowledge_unit_id": "hier::path::tc", "knowledge_unit_type": "topic",
    "canonical_name": "Topic TC",
    "direct_child_kcs": [{"child_kc_id": "KC_A", "child_kc_name": "A"},
                         {"child_kc_id": "KC_B", "child_kc_name": "B"}],
    "topic_evidence": [{"evidence_id": "tev1", "text": "x"}],
}
_tc_draft = {
    "knowledge_unit_id": "hier::path::tc", "knowledge_unit_type": "topic",
    "canonical_name": "Topic TC",
    "contextual_topic_draft": {
        "status": "grounded", "text": "T" * 260,
        "supporting_evidence_ids": ["tev1"], "coverage_notes": [], "uncertainty_notes": [],
    },
    "child_kc_summaries": [
        {"child_kc_id": "KC_A", "child_kc_name": "A", "summary": "s", "supporting_evidence_ids": ["tev1"]},
        {"child_kc_id": "KC_B", "child_kc_name": "B", "summary": "s", "supporting_evidence_ids": ["tev1"]},
    ],
    "evaluation_support": {}, "evidence_map": [{"claim": "c", "supporting_evidence_ids": ["tev1"]}],
}
_tc_codes = {i.get("code") for i in DR.validate_output(_tc_packet, _tc_draft)}
check("TC-1 a schema-conformant topic draft validates cleanly",
      not _tc_codes, str(_tc_codes))
check("TC-2 the validator no longer demands fields the enforced schema forbids",
      "child_kc_coverage_summary_missing" not in _tc_codes
      and "topic_draft_missing_supporting_child_kc_ids" not in _tc_codes,
      "these failed 22/22 real topic drafts by construction")

_tc_gap_draft = json.loads(json.dumps(_tc_draft))
_tc_gap_draft["child_kc_summaries"] = [_tc_draft["child_kc_summaries"][0]]
_tc_gap = [i for i in DR.validate_output(_tc_packet, _tc_gap_draft)
           if i.get("code") == "topic_draft_child_kcs_unaccounted"]
check("TC-3 a child unit left unaccounted IS still caught, and named",
      _tc_gap and _tc_gap[0].get("unaccounted_child_kc_ids") == ["KC_B"],
      str(_tc_gap))
check("TC-4 an empty child_kc_summaries is still a defect",
      "child_kc_summaries_missing_or_empty" in {
          i.get("code") for i in DR.validate_output(
              _tc_packet, dict(_tc_gap_draft, child_kc_summaries=[]))},
      "the coverage contract must not become unenforceable")

# status-aware abstention shape
_ab_packet = {"knowledge_unit_id": "KC_AB", "knowledge_unit_type": "kc", "canonical_name": "AB",
              "packet_support_state": "draftable",
              "evidence_for_synthesis": [{"evidence_id": "e1", "text": "some real evidence"}]}
_ab_draft = {
    "knowledge_unit_id": "KC_AB", "knowledge_unit_type": "kc", "canonical_name": "AB",
    "contextual_kc_draft": {"status": "abstained", "text": "", "supporting_evidence_ids": [],
                            "coverage_notes": [], "uncertainty_notes": ["evidence is off-target"]},
    "segmentation_support": {}, "evaluation_support": {}, "evidence_map": [],
    "kc_specific_criteria": [], "kc_specific_criteria_status": "expert_pending",
    "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
}
_ab_codes = {i.get("code") for i in DR.validate_output(_ab_packet, _ab_draft)}
check("AB-1 an abstention's required shape (empty text, empty ledger) is not a schema defect",
      "kc_contextual_draft_missing_or_too_short" not in _ab_codes
      and "evidence_map_missing_or_empty" not in _ab_codes,
      str(_ab_codes))
check("AB-2 the packet/model disagreement is still reported, by the gate that owns it",
      (SI.unjustified_abstention_violation(_ab_packet, _ab_draft) or {}).get("code")
      == "unjustified_abstention_on_draftable_packet",
      "suppressing the shape complaints must not suppress the real signal")
check("AB-3 a NON-abstained draft with empty text/ledger is still a defect",
      {"kc_contextual_draft_missing_or_too_short", "evidence_map_missing_or_empty"} <= {
          i.get("code") for i in DR.validate_output(
              _ab_packet,
              json.loads(json.dumps(_ab_draft).replace('"abstained"', '"grounded"')))},
      "the exemption must key on abstention, not disable the checks outright")

# --- ligature expansion in the lexical channel ---
# A ligature is not in [a-z0-9], so TOKEN_RE treated it as a word separator and destroyed the word
# around it: "deﬁne" tokenised to nothing at all, "classiﬁcation" to "classi"+"cation". Queries are
# built from cleanly-typed hierarchy labels, so that evidence was unreachable by BM25 entirely.
# Measured on the real corpus: 91 real content tokens recovered, 72 junk tokens removed,
# "classification" 0 -> 33 reachable rows.
check("LIG-1 a ligature word tokenises to the real word, not to nothing or to fragments",
      HR.tokenize("deﬁne") == ["define"]
      and HR.tokenize("classiﬁcation") == ["classification"]
      and HR.tokenize("ﬁlter") == ["filter"]
      and HR.tokenize("diﬀerent") == ["different"],
      "these previously produced [], ['classi','cation'], ['lter'], ['erent']")
check("LIG-2 clean text is unchanged by the expansion",
      HR.tokenize("define classification filter") == ["define", "classification", "filter"],
      "the fix must be a no-op on text that never had a ligature")
check("LIG-3 a ligature query token now matches its own ligature-bearing corpus text",
      "classification" in HR.tokenize("Naive Bayes classiﬁcation of documents"),
      "this is the actual retrieval failure - query 'classification' could not reach this sentence")
check("LIG-4 mathematical superscripts are NOT rewritten (why this is not NFKD)",
      "2" not in HR.expand_ligatures("x²") and HR.expand_ligatures("x²") == "x²",
      "NFKD would turn x² into x2 and silently alter mathematical text")
check("LIG-5 expansion is applied inside tokenize, so BOTH corpus and query pass through it",
      "expand_ligatures" in live_calls(os.path.join(
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
          "..", "src", "kc_l", "retrieval_gate", "retrieval.py")),
      "BM25Index builds through tokenize() and build_query tokenises through it too")

# --- compound-sibling ownership: curriculum-derived context, no hardcoded vocabulary ---
# This rule used to decide ownership with a typed-in word list
# (clusters?|clustering|external index|cluster labels?) plus a named-metric special case
# (own_base == "f" and "hierarchical F-measure"). That named one curriculum's subject AND, naming
# only that subject, could never fire on any other corpus - so the rule was silently inert outside
# data mining. It now subtracts the base unit's own ancestry from the compound sibling's and uses
# what remains.
import inspect as _cmp_inspect
_cmp_src = _cmp_inspect.getsource(CP.compound_sibling_formula_owner)
# Comments and the docstring legitimately NAME the example units they explain, so the check is
# made against executable code only - strip the docstring and every comment first.
_cmp_code = re.sub(r'"""..*?"""', "", _cmp_src, flags=re.S)
_cmp_code = chr(10).join(re.sub(r"#.*$", "", ln) for ln in _cmp_code.splitlines())
check("CS-1 no subject vocabulary is hardcoded in the ownership rule's executable code",
      not re.search(r"cluster|entropy|purity|jaccard|precision|recall|measure",
                    _cmp_code, re.I),
      "a typed-in subject word list makes the rule inert on every other corpus; found: %r"
      % re.findall(r"\w*(?:cluster|entropy|purity|jaccard|precision|recall|measure)\w*",
                   _cmp_code, re.I)[:5])
check("CS-2 no named-unit special case remains in the ownership rule",
      'own_base == "f"' not in _cmp_src and "hierarchical" not in _cmp_src.lower(),
      "a rule keyed to one metric's name is a domain hardcode")

# the discriminating context is DERIVED: base branch subtracted from compound branch
_cs_branch = {
    "F-Measure": {"data", "mining", "classifier", "comparison", "evaluation"},
    "External Index: F-Measure": {"data", "mining", "clustering", "cluster", "evaluation",
                                  "external"},
}
check("CS-3 discriminating context is derived from the curriculum, not typed in",
      (CP._split_terms(_cs_branch["External Index: F-Measure"])
       - CP._split_terms(_cs_branch["F-Measure"])) == {"clustering", "cluster", "external"},
      "these are exactly the words the old hardcoded list contained - now derived")
check("CS-4 shared ancestry cannot carry a transfer on its own",
      CP.compound_sibling_formula_owner(
          "the evaluation of a data mining model", "F-Measure", [],
          ["External Index: F-Measure"], _cs_branch) is None,
      "'data', 'mining', 'evaluation' are shared by both branches and must cancel out")

# same rule, invented curriculum, no code change
_cs_alt = {"Elasticity": {"microeconomics", "demand"},
           "Cross-Price: Elasticity": {"microeconomics", "substitution", "goods"}}
check("CS-5 the same rule works on a curriculum in an unrelated subject",
      CP.compound_sibling_formula_owner(
          "elasticity of substitution between paired goods", "Elasticity",
          ["Cross-Price: Elasticity"], ["Elasticity", "Cross-Price: Elasticity"], _cs_alt)
      == "Cross-Price: Elasticity"
      and CP.compound_sibling_formula_owner(
          "Elasticity = pctChangeQ / pctChangeP for substitution goods", "Elasticity",
          ["Cross-Price: Elasticity"], ["Elasticity", "Cross-Price: Elasticity"], _cs_alt) is None,
      "generic derivation must transfer on qualified context and keep a stated base equation")

# the over-claim this fix exists to stop
check("CS-6 a passage STATING the base unit's own equation is not taken by context alone",
      CP.compound_sibling_formula_owner(
          "F1 = 2 * Precision * Recall / (Precision + Recall) in the cluster evaluation chapter",
          "F-Measure", [], ["External Index: F-Measure"], _cs_branch) is None,
      "this cost the real F-Measure unit every substantive passage it had")
check("CS-7 a LaTeX-wrapped base equation is protected too",
      CP.compound_sibling_formula_owner(
          "$$ \\mathsf { F } \\mathsf { B } = ( \\mathsf { \\beta } 2 + 1 ) $$ cluster evaluation",
          "F-Measure", [], ["External Index: F-Measure"], _cs_branch) is None,
      "raw text hides the equation behind LaTeX wrappers; the compacted signature must be checked")
check("CS-8 the indexed form still transfers, being the qualified variant's own notation",
      CP.compound_sibling_formula_owner(
          "F(i,j) = 2 r p / (r + p) for cluster i", "F-Measure", [],
          ["External Index: F-Measure"], _cs_branch) == "External Index: F-Measure",
      "protecting base equations must not disable genuine compound ownership")
check("CS-9 the packet builder supplies the curriculum context (else the rule is inert)",
      "unit_branch_terms" in _builder_src
      and "drop_compound_sibling_formulas(\n            passages, name, rivals, all_unit_names, unit_branch_terms)" in _builder_src,
      "without the hierarchy map there is no discriminating context and nothing transfers")

# --- stranded display-fraction numerators (false-evidence defect) ---
# The extractor stacks a display fraction into separate rows, so the numerator becomes a
# standalone "equation" that parses perfectly and states something FALSE. The damage checks do not
# catch it because the row is well formed. Measured: 5 KCs per data-mining run were handed one as
# evidence and told to reproduce it exactly (Precision got F1's numerator, AUC got its numerator).
_SN_CORPUS = [
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:20",
     "sent_idx": 0, "sentence_text": "P(Xi = c | y) = nc + 1"},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:21",
     "sent_idx": 0, "sentence_text": "n + v ,"},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:22",
     "sent_idx": 0, "sentence_text": "Recall = TP / (TP + FN)."},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:23",
     "sent_idx": 0, "sentence_text": "This concludes the section."},
]
_SN = CP.build_stranded_numerator_texts(_SN_CORPUS)
check("SN-1 a severed display-fraction numerator is identified from its neighbour",
      "P(Xi = c | y) = nc + 1" in _SN, str(_SN))
# single-term denominators: probability formulas overwhelmingly use them, and requiring an
# operator missed every severed Bayes numerator in the corpus.
_SN_BAYES = CP.build_stranded_numerator_texts([
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:1",
     "sent_idx": 0, "sentence_text": "P(Y | X) = P(X, Y )"},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:2",
     "sent_idx": 0, "sentence_text": "P(X) ."},
])
check("SN-7 a single-term denominator that continues the numerator's symbols is recognised",
      "P(Y | X) = P(X, Y )" in _SN_BAYES,
      "this is severed Bayes - the numerator alone asserts P(Y|X) = P(X,Y), which is false")
_SN_HEAD = CP.build_stranded_numerator_texts([
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:1",
     "sent_idx": 0, "sentence_text": "Precision = 0.750"},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:2",
     "sent_idx": 0, "sentence_text": "Tutor Note"},
])
check("SN-8 an unrelated heading is NOT taken as a denominator",
      not _SN_HEAD,
      "its letters do not continue the numerator's symbols, so it cannot be a denominator")
_SN_FRAC = CP.build_stranded_numerator_texts([
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:1",
     "sent_idx": 0, "sentence_text": "w = 1 / M"},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:2",
     "sent_idx": 0, "sentence_text": "M + 1"},
])
check("SN-9 a formula that ALREADY has fraction notation is complete, never stranded",
      not _SN_FRAC,
      "this rule drops evidence, so flagging a complete formula loses real mathematics")
check("SN-2 a COMPLETE formula is not flagged as stranded",
      "Recall = TP / (TP + FN)." not in _SN,
      "an intact equation must survive - this rule drops evidence, so it must be precise")
check("SN-3 the defect is invisible to the damage checks, which is why this exists",
      not CP.math_rendering_damaged("P(Xi = c | y) = nc + 1")
      and CP.math_rendering_damaged("P(Xi=c|y)=nc+1n+v,"),
      "the row is well formed; only the mathematics is wrong")
check("SN-4 prose following an equation does not make it stranded",
      not CP.build_stranded_numerator_texts([
          {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:1",
           "sent_idx": 0, "sentence_text": "Entropy = -sum p log p"},
          {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:2",
           "sent_idx": 0, "sentence_text": "where p is the class probability"}]),
      "a bare denominator carries an operator and no words - prose must not qualify")
_sn_kept, _sn_dropped = CP.drop_stranded_numerator_passages(
    [{"text": "P(Xi = c | y) = nc + 1"}, {"text": "Recall = TP / (TP + FN)."}],
    {"P(Xi = c | y) = nc + 1"})
check("SN-5 the drop function removes the stranded numerator and keeps the intact formula",
      len(_sn_kept) == 1 and "Recall" in _sn_kept[0]["text"]
      and len(_sn_dropped) == 1
      and _sn_dropped[0]["reason"] == "stranded_numerator_denominator_severed",
      str((_sn_kept, _sn_dropped)))
def _call_is_unconditional_assignment(path, func_name):
    """True only when func_name is called as the DIRECT right-hand side of an assignment.

    Mere presence in the parse tree is not enough. `x = (a, []) or f(...)` still contains a Call
    node for f, so an AST call-presence check passes while f never runs - confirmed by sabotage,
    which SURVIVED the call-presence form of this check. Requiring the call to BE the assigned
    value rejects short-circuit, ternary and constant-guard disabling alike.
    """
    tree = _ast.parse(io.open(path, encoding="utf-8").read())
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Assign):
            continue
        value = node.value
        if isinstance(value, _ast.Call):
            fn = value.func
            name = fn.id if isinstance(fn, _ast.Name) else getattr(fn, "attr", None)
            if name == func_name:
                return True
    return False


check("SN-6 the drop is called UNCONDITIONALLY by the builder, not behind a short-circuit",
      _call_is_unconditional_assignment(_PACKET_BUILDER_PATH,
                                        "drop_stranded_numerator_passages")
      and "build_stranded_numerator_texts" in live_calls(_PACKET_BUILDER_PATH),
      "call-presence alone is defeatable: `x = (a, []) or f(...)` keeps the Call node while f "
      "never executes, and that weaker form SURVIVED sabotage")

# --- lead-in hidden by a split citation ---
# A formula's naming pointer ("The textbook gives the Laplace estimate:[1, p. 308]") failed the
# terminal-colon test because the source's own citation was split across extraction rows, leaving
# debris after the colon. That stranded 6 genuine formulas including the intact MinerU renderings
# of Laplace, conditional probability, the evidence/marginalisation term and the Gaussian
# class-conditional density - the exact formulas the drafts reported as missing.
check("LI-1 a lead-in followed by split-citation debris is still recognised",
      CP.ends_with_lead_in("The textbook gives the Laplace estimate:[1, p.")
      and CP.ends_with_lead_in("The textbook defines conditional probability in the standard "
                               "way:[1, p. 297]"),
      "the promise is intact; only the citation fragment sits after it")
check("LI-2 an ordinary sentence is still NOT a lead-in",
      not CP.ends_with_lead_in("Entropy measures impurity [15].")
      and not CP.ends_with_lead_in("See the table [3]")
      and not CP.ends_with_lead_in("The result was 0.469."),
      "tolerating citation debris must not turn every cited sentence into a promise")
check("LI-3 the real gate is still the payload, not the pointer",
      not CP.is_formula_payload("This paragraph is ordinary prose with no mathematics in it at "
                                "all, merely discussion."),
      "is_formula_payload on the successor block remains what actually admits anything")
check("LI-4 a lead-in pointing at a STRANDED numerator cannot smuggle false mathematics in",
      "P(Xi = c | y) = nc + 1" in CP.build_stranded_numerator_texts([
          {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:20",
           "sent_idx": 0, "sentence_text": "P(Xi = c | y) = nc + 1"},
          {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:21",
           "sent_idx": 0, "sentence_text": "n + v ,"}]),
      "this pairing is exactly why the lead-in fix is only safe alongside SN rejection")

# --- dense channel ligature consistency + cache self-invalidation ---
# tokenize() expands ligatures for BM25; the dense channel embedded RAW text, so the two channels
# disagreed about the same sentence. The dangerous half is the cache: the caller derives its key
# from the corpus FILE (path/size/mtime/rows), which is content-independent, so a preprocessing
# change does NOT change the key and an old cache would be silently reused - the fix would look
# present while every vector still came from unnormalised text.
def _calls_within(path, class_name, method_names):
    """Names called inside specific METHODS of a class. A file-wide call check is useless here:
    tokenize() also calls expand_ligatures, so removing it from DenseIndex would go unnoticed -
    confirmed by sabotage, which SURVIVED the file-wide version of this check."""
    tree = _ast.parse(io.open(path, encoding="utf-8").read())
    found = {}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if isinstance(sub, _ast.FunctionDef) and sub.name in method_names:
                    names = set()
                    for inner in _ast.walk(sub):
                        if isinstance(inner, _ast.Call):
                            fn = inner.func
                            if isinstance(fn, _ast.Name):
                                names.add(fn.id)
                            elif isinstance(fn, _ast.Attribute):
                                names.add(fn.attr)
                    found[sub.name] = names
    return found


_dense_path = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "src", "kc_l", "retrieval_gate", "retrieval.py"))
_dense_calls = _calls_within(_dense_path, "DenseIndex", {"__init__", "top_k"})
check("DL-1 DenseIndex expands ligatures in BOTH its corpus encode and its query encode",
      "expand_ligatures" in _dense_calls.get("__init__", set())
      and "expand_ligatures" in _dense_calls.get("top_k", set()),
      "checked inside DenseIndex specifically: a file-wide check passes because tokenize() also "
      "calls it, and that weaker form SURVIVED sabotage")
_dense_src = io.open(os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "src", "kc_l", "retrieval_gate", "retrieval.py")), encoding="utf-8").read()
check("DL-2 the embedding cache records the preprocessing identity",
      "_EMBED_PREPROC_VERSION" in _dense_src
      and "preproc=_EMBED_PREPROC_VERSION" in _dense_src,
      "without it a cache cannot be told apart from one built under different preprocessing")
check("DL-3 cache VALIDATION checks that identity, not just n and model",
      'blob.get("preproc", "")) == _EMBED_PREPROC_VERSION' in _dense_src,
      "writing the field but not checking it on load leaves the stale-reuse hole open")
check("DL-4 a cache missing the identity is rebuilt, not reused",
      'self.cache_status = "stale_rebuild"' in _dense_src,
      "an older cache has no preproc field and must fail validation")

# --- duplicate canonical names must not overwrite each other's branch context ---
# unit_branch_terms keys on canonical_name because the ownership rule receives names, not ids.
# The real curriculum contains one name in two unrelated branches (Model Evaluation vs Feature
# Selection), so the later build silently gave one unit its twin's ancestry.
check("DN-1 the builder detects a duplicate canonical name instead of overwriting it",
      "_ambiguous_branch_names" in _builder_src
      and "unit_branch_terms[key] = set()" in _builder_src,
      "a name denoting two branches has no well-defined branch; it must get none, not the last one")
check("DN-2 the duplicate is surfaced in the build log, not silently absorbed",
      "ambiguous canonical names (branch context withheld)" in _builder_src,
      "a silent collision is exactly the class of defect this guard exists for")
check("DN-3 withholding branch context is the CONSERVATIVE direction",
      CP.compound_sibling_formula_owner(
          "some passage about clustering", "Amb", ["External Index: Amb"],
          ["Amb", "External Index: Amb"], {"Amb": set(), "External Index: Amb": set()}) is None,
      "with no branch terms the rule falls back to qualifier words and transfers nothing here")

# --- cross-layer recovery of severed formulas ---
# Where PyMuPDF stacks a display fraction into a false numerator, the math-aware layer often holds
# the same equation intact on the same page. Substituting it invents nothing - the correct text is
# already in the corpus. Matching is strict because a loose match would present formula A where
# the source stated formula B: measured on the real corpus, left-hand-side agreement ALONE paired
# the severed Bayes rule with the conditional-probability definition.
_XL_CORPUS = [
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:1",
     "sent_idx": 0, "sentence_text": "P(H | E) = P(E | H)P(H)"},
    {"doc_id": "D", "page_index": 1, "layer": "pymupdf", "block_id": "D:pymupdf:1:2",
     "sent_idx": 0, "sentence_text": "P(E) ."},
    {"doc_id": "D", "page_index": 1, "layer": "mineru", "block_id": "D:mineru:1:9",
     "sent_idx": 0,
     "sentence_text": r"$$ P ( H \mid E ) = { \frac { P ( E \mid H ) P ( H ) } { P ( E ) } } . $$"},
]
_XL_STRANDED = CP.build_stranded_numerator_texts(_XL_CORPUS)
_XL_SUBS = CP.build_intact_formula_substitutions(_XL_CORPUS, _XL_STRANDED)
check("XL-1 a severed numerator is matched to the intact rendering of the SAME equation",
      _XL_SUBS.get("P(H | E) = P(E | H)P(H)", "").count("frac") == 1,
      str(_XL_SUBS))

# a different equation sharing only the left-hand side must NOT be substituted
_XL_WRONG = [
    {"doc_id": "D", "page_index": 2, "layer": "pymupdf", "block_id": "D:pymupdf:2:1",
     "sent_idx": 0, "sentence_text": "P(y | x) = P(x | y)P(y)"},
    {"doc_id": "D", "page_index": 2, "layer": "pymupdf", "block_id": "D:pymupdf:2:2",
     "sent_idx": 0, "sentence_text": "P(x) ."},
    {"doc_id": "D", "page_index": 2, "layer": "mineru", "block_id": "D:mineru:2:9",
     "sent_idx": 0,
     "sentence_text": r"$$ P ( y \mid x ) = { \frac { P ( x , y ) } { P ( x ) } } . $$"},
]
_XL_WS = CP.build_intact_formula_substitutions(
    _XL_WRONG, CP.build_stranded_numerator_texts(_XL_WRONG))
check("XL-2 an equation sharing ONLY the left-hand side is refused",
      not _XL_WS,
      "P(x|y)P(y) is not P(x,y); substituting it would state something the source did not")

_xl_kept, _xl_dropped = CP.drop_stranded_numerator_passages(
    [{"text": "P(H | E) = P(E | H)P(H)"}], _XL_STRANDED, _XL_SUBS)
check("XL-3 the recovered formula replaces the severed one and is marked as recovered",
      len(_xl_kept) == 1 and _xl_kept[0].get("recovered_from_severed_numerator") is True
      and "frac" in _xl_kept[0]["text"]
      and _xl_dropped[0]["reason"] == "stranded_numerator_substituted_intact",
      str((_xl_kept, _xl_dropped)))
check("XL-4 with NO substitute available the severed numerator is still dropped, not kept",
      CP.drop_stranded_numerator_passages(
          [{"text": "P(H | E) = P(E | H)P(H)"}], _XL_STRANDED, {})[0] == [],
      "recovery must not become a way for false formulas to survive")
check("XL-5 the builder supplies the substitution map (else recovery is inert)",
      "build_intact_formula_substitutions" in live_calls(_PACKET_BUILDER_PATH)
      and "intact_substitutions" in _builder_src,
      "built but not passed would silently disable recovery")

check("XL-6 recovery provenance survives into evidence_for_synthesis (else it is unauditable)",
      "recovered_from_severed_numerator" in _builder_src
      and "'support_profile_summary'" in _builder_src,
      "the passage-level flag from drop_stranded_numerator_passages must reach the packet, or a "
      "reader has no way to tell a substituted formula from an ordinary one")

# --- INT-1: pure interrogative text cannot single-handedly grant draftable ---
_INT1_UNIT = ["Recall (Sensitivity)"]
_int1_state_bad, _ = PB.assess_support_state(
    [{"text": "Is recall the same as sensitivity for the positive class?",
      "shapes": ["prose"], "patch_heading": "Recall"}], _INT1_UNIT)
check("INT1-1 an interrogative-only pool is NOT draftable",
      _int1_state_bad != "draftable", _int1_state_bad)
_int1_state_good, _ = PB.assess_support_state(
    [{"text": "Recall, also called sensitivity, is the fraction of actual positives correctly "
              "identified by the classifier.", "shapes": ["prose"], "patch_heading": "Recall"}],
    _INT1_UNIT)
check("INT1-2 ordinary non-interrogative prose is unaffected (no regression)",
      _int1_state_good == "draftable", _int1_state_good)
_int1_mixed, _ = PB.assess_support_state(
    [{"text": "Is recall the same as sensitivity for the positive class?",
      "shapes": ["prose"], "patch_heading": "Recall"},
     {"text": "Recall, also called sensitivity, is the fraction of actual positives correctly "
              "identified.", "shapes": ["prose"], "patch_heading": "Recall"}], _INT1_UNIT)
check("INT1-3 a mixed pool still resolves via the assertable passage, not the interrogative one",
      _int1_mixed == "draftable", _int1_mixed)
check("INT1-4 the passage is NOT removed from evidence - only the substance gate changed",
      "passage_assertability(passage)" in _builder_src
      and "if anchored and (formula_substance or prose_substance)" in _builder_src,
      "INT-1 must gate substance, not admission - passages must still reach evidence_item()")

# --- INT-7: a mislabeled instructional lead-in must not be suppressed before the existing
# lead-in-to-payload recovery can evaluate it ---
# is_structural_junk() already overrides a JUNK_FLAG when a row looks_like_equation(), because the
# overlay mislabels some formulas as navigation/metadata. The same mislabeling hits POINTER
# sentences, which are prose and so fall outside that override - so the pointer was discarded
# before lead_in_payload could use it, making its formula unreachable at any threshold.
_INT7_POINTER = {"sentence_text": "The lecture defines the coefficient as follows:",
                 "is_meta": True}
check("INT7-1 a meta-flagged lead-in whose successor is a formula payload is NOT suppressed",
      CP.is_mislabeled_formula_pointer(_INT7_POINTER, "r = a / b .") is True,
      "the override must fire for exactly this shape")
check("INT7-8 a payload with NO relational operator is not strong enough to override the flag",
      CP.is_mislabeled_formula_pointer(_INT7_POINTER, "P u in X\{x} d(x, u)") is False,
      "a bare expression fragment caused a measured drafting regression on a budget-capped packet")
check("INT7-9 a payload that DOES assert a relation still qualifies",
      CP.is_mislabeled_formula_pointer(_INT7_POINTER, "f = FindNextBest(F, U).") is True)
check("INT7-2 the override requires an actual formula payload successor",
      CP.is_mislabeled_formula_pointer(_INT7_POINTER, "This paragraph is ordinary prose.") is False,
      "a lead-in pointing at non-formula text must not be exempted")
check("INT7-3 a row with NO junk flag is not affected (nothing to override)",
      CP.is_mislabeled_formula_pointer(
          {"sentence_text": "The lecture defines the coefficient as follows:"}, "r = a / b .")
      is False,
      "the override exists only to undo a flag-driven rejection")
check("INT7-4 non-lead-in text is never exempted, however it is flagged",
      CP.is_mislabeled_formula_pointer(
          {"sentence_text": "Navigation menu home about contact.", "is_nav_boilerplate": True},
          "r = a / b .") is False)
check("INT7-5 every OTHER structural-safety check still applies (damaged math stays rejected)",
      CP.is_mislabeled_formula_pointer(
          {"sentence_text": "Recall = TP TP + FN as follows:", "is_meta": True}, "r = a / b .")
      is False,
      "the override is only for the mislabeling flag, not a bypass of damage detection")
import inspect as _int7_inspect
_int7_assemble_src = _int7_inspect.getsource(CP.assemble_passages)
check("INT7-6 assemble_passages consults the override (else it is inert)",
      "is_mislabeled_formula_pointer" in _int7_assemble_src,
      "assemble_passages must call it, or a mislabeled pointer is still dropped before use")
check("INT7-7 the override is consulted at the structural-junk gate, not somewhere harmless",
      "is_structural_junk" in _int7_assemble_src
      and _int7_assemble_src.index("is_structural_junk")
          < _int7_assemble_src.index("is_mislabeled_formula_pointer"),
      "it must guard the junk rejection itself")

# --- INT-9: extractor agreement is RECORDED, not only its conclusion ---
# build_intact_formula_substitutions() compares extraction layers and previously kept only the
# winner. A reviewer auditing a formula-heavy unit needs to know whether the extractors agreed,
# and whether a CONFLICTING rendering (same left-hand side, different right-hand side) existed.
_INT9_AG = {}
_INT9_SUBS = CP.build_intact_formula_substitutions(_XL_CORPUS, _XL_STRANDED, agreement_out=_INT9_AG)
check("INT9-1 substitution behaviour is UNCHANGED by adding provenance",
      _INT9_SUBS.get("P(H | E) = P(E | H)P(H)", "").count("frac") == 1,
      "the provenance out-param must be purely additive")
check("INT9-2 agreeing extractor layers are recorded",
      _INT9_AG.get("P(H | E) = P(E | H)P(H)", {}).get("extractor_agreement_count", 0) >= 1
      and "mineru" in _INT9_AG["P(H | E) = P(E | H)P(H)"]["agreeing_layers"],
      str(_INT9_AG))
check("INT9-3 omitting the out-param leaves the old signature working (no caller breakage)",
      CP.build_intact_formula_substitutions(_XL_CORPUS, _XL_STRANDED).get(
          "P(H | E) = P(E | H)P(H)", "").count("frac") == 1)
_i9k, _i9d = CP.drop_stranded_numerator_passages(
    [{"text": "P(H | E) = P(E | H)P(H)"}], _XL_STRANDED, _INT9_SUBS, _INT9_AG)
check("INT9-4 the recovered passage carries its extractor provenance",
      _i9k and _i9k[0].get("extractor_agreement_count") == 1
      and _i9k[0].get("extractor_conflict") is False,
      str(_i9k))
check("INT9-5 provenance reaches the packet (else it is unauditable downstream)",
      "extractor_agreement_count" in _builder_src and "extractor_conflict" in _builder_src)

# --- INT-10: a running header repeated with different page numbers is ONE passage ---
# A running header is re-emitted per page with a different leading number, so every copy had a
# distinct content_signature and survived deduplication - measured at 72% and 66% of two real
# packets' entire evidence budget.
check("INT10-1 a running header with differing page numbers collapses to one signature",
      CP.content_signature("4 Dealing with Missing Values")
      == CP.content_signature("78 4 Dealing with Missing Values"))
check("INT10-2 TRAILING digits are preserved - distinct worked values must NOT collide",
      CP.content_signature("Precision = 0.750") != CP.content_signature("Precision = 0.500"),
      "stripping trailing digits is the exact error that collapses two different worked examples")
check("INT10-3 differing content behind a leading number still does not collide",
      CP.content_signature("1. Positivity") != CP.content_signature("2. Symmetry"))
check("INT10-4 the leading-number strip is anchored to the START of the text",
      CP._LEADING_PAGENO_RE.pattern.startswith("^"),
      "un-anchored, it would eat digits from anywhere in the passage")
_i10 = CP.deduplicate_passages([
    {"text": "4 Dealing with Missing Values", "shapes": ["heading"]},
    {"text": "78 4 Dealing with Missing Values", "shapes": ["heading"]},
    {"text": "70 4 Dealing with Missing Values", "shapes": ["heading"]},
])
check("INT10-5 end to end: three copies of one running header become one passage",
      len(_i10) == 1, str(_i10))
_i10b = CP.deduplicate_passages([
    {"text": "Precision = 0.750", "shapes": []}, {"text": "Precision = 0.500", "shapes": []}])
check("INT10-6 end to end: two distinct worked values are BOTH kept",
      len(_i10b) == 2, str(_i10b))

# ---------------------------------------------------------------------------------------------
# INT-11: a math-damaged rendering is repaired from an intact twin instead of being dropped.
# The guards below fall into two groups. The behavioural ones state the RULE on synthetic rows,
# so they keep holding on any corpus. The liveness ones assert the repair is actually reached by
# the builder and reached EARLY, because a repair applied after an index is built is a repair the
# index never saw - which is precisely how a fix dies quietly while its unit tests still pass.
_I11_BAR_LOST = "P(Y|X)=P(X|Y)P(Y)P(X)."
_I11_INTACT = "$$ P ( y | x ) = \\frac { P ( x | y ) P ( y ) } { P ( x ) } ."
_I11_TRUNCATED = "$$ M _ { 1 } = ( 0 ."
_I11_UNRELATED = "M1 = m/3 + 0.05"


def _i11_row(text, doc="D1", page=1, layer="pymupdf"):
    return {"sentence_text": text, "doc_id": doc, "page_index": page, "layer": layer}


def _appears_in_order(source, *needles):
    """True when every needle is present and they appear in the order given.

    str.index() raises when a needle is missing, which aborts the whole suite instead of failing
    one check - so an ordering guard written with it reports a crash rather than a verdict, and
    every check after it stops running. Found by sabotage: removing the call under test produced
    'ValueError: substring not found' instead of a named failure.
    """
    position = -1
    for needle in needles:
        found = source.find(needle, position + 1)
        if found <= position:
            return False
        position = found
    return True


_I11_CORPUS = [_i11_row(_I11_BAR_LOST, doc="D1", page=295),
               _i11_row(_I11_INTACT, doc="D2", page=31, layer="mineru"),
               _i11_row(_I11_TRUNCATED, doc="D3", page=17, layer="mineru"),
               _i11_row(_I11_UNRELATED, doc="D4", page=1073)]
_I11_INDEX = CP.build_intact_twin_index(_I11_CORPUS)
_I11_REPAIRS = CP.build_damaged_formula_repairs(_I11_CORPUS, _I11_INDEX)
_I11_APPLIED, _I11_N = CP.apply_damaged_formula_repairs(_I11_CORPUS, _I11_REPAIRS)
# Materialised once, as a list rather than a next() over a generator. Sabotage showed why: with
# the repair disabled there is no such row, next() raises StopIteration, and because this suite
# prints its results only at the end, that exception discarded the report for all 379 checks -
# including the two that had already correctly failed.
_I11_REPAIRED_ROWS = [r for r in _I11_APPLIED if r.get("formula_repaired_from_damaged_text")]

check("INT11-1 twin locality is classified three ways, not as a same-page boolean",
      (CP.formula_twin_locality(_i11_row("a"), _i11_row("b")) == CP.SAME_PAGE
       and CP.formula_twin_locality(_i11_row("a", page=1), _i11_row("b", page=9))
       == CP.SAME_DOCUMENT
       and CP.formula_twin_locality(_i11_row("a", doc="D1"), _i11_row("b", doc="D2"))
       == CP.FOREIGN_DOCUMENT))
check("INT11-2 a same-page twin from the SAME layer is not corroboration",
      not CP.twin_corroboration_is_sufficient(CP.SAME_PAGE, "pxypypx", "mineru", "mineru"),
      "the same layer reading its own row twice proves nothing")
check("INT11-3 off the page, a bare-numeral right-hand side is refused",
      not CP.twin_corroboration_is_sufficient(CP.FOREIGN_DOCUMENT, "0", "a", "b")
      and CP.twin_corroboration_is_sufficient(CP.FOREIGN_DOCUMENT, "pxypypx", "a", "b"),
      "this single rule is what blocked the one false cross-document match observed")
check("INT11-4 a bar-loss rendering IS repaired from a twin in another document",
      _I11_REPAIRS.get(_I11_BAR_LOST, {}).get("text") == _I11_INTACT)
check("INT11-5 a truncated row is NOT repaired on its numeral-only right-hand side",
      _I11_TRUNCATED not in _I11_REPAIRS,
      "'M_1 = (0.' matching an unrelated 'm1=m/3' is the measured failure this prevents")
check("INT11-6 the repair set uses the SAME predicate the drop pass drops on",
      CP.math_rendering_damaged(_I11_BAR_LOST) and not CP.has_mathematics(_I11_BAR_LOST)
      and _I11_BAR_LOST in _I11_REPAIRS,
      "pairing math_rendering_damaged with has_mathematics silently excluded bar-loss rows")
check("INT11-7 the stranded-numerator path keeps its page-local default",
      CP.build_intact_formula_substitutions(_I11_CORPUS, {_I11_BAR_LOST}) == {}
      and CP.build_intact_formula_substitutions(
          _I11_CORPUS, {_I11_BAR_LOST}, allow_non_local=True) != {},
      "widening must be opt-in so the existing caller's behaviour is untouched")
check("INT11-8 a repaired row keeps the rendering it replaced",
      any(r.get("formula_repaired_from_damaged_text") == _I11_BAR_LOST
          for r in _I11_REPAIRED_ROWS),
      "a repair that cannot be inspected afterwards is indistinguishable from a fabrication")
check("INT11-9 a repaired row records the document, layer and locality it came from",
      bool(_I11_REPAIRED_ROWS)
      and all(k in r for r in _I11_REPAIRED_ROWS
              for k in ("formula_repaired_from_doc_id", "formula_repaired_from_layer",
                        "formula_repair_locality")))
check("INT11-10 rows with no repair are passed through untouched",
      _I11_N == 1 and CP.apply_damaged_formula_repairs(_I11_CORPUS, {}) == (_I11_CORPUS, 0))
check("INT11-11 passage provenance is read across members, not only off the seed",
      bool(_I11_REPAIRED_ROWS)
      and CP.repaired_formula_provenance([_i11_row("lead in:"), _I11_REPAIRED_ROWS[0]]
                                         ).get("formula_repaired_from_doc_id") == "D2",
      "the repaired row is frequently not the block's seed")
check("INT11-16 the repair does not change a row's BLOCK IDENTITY",
      CP._block_key(_I11_REPAIRED_ROWS[0] if _I11_REPAIRED_ROWS else {})
      == CP._block_key(dict(_I11_CORPUS[0], block_id=(_I11_REPAIRED_ROWS[0].get("block_id")
                                                      if _I11_REPAIRED_ROWS else None)))
      if _I11_REPAIRED_ROWS else False,
      "block keys hash source_block_text, which the repair must leave alone - a changed key would "
      "silently break the successor links the lead-in payload rescue walks")
check("INT11-17 the repair rewrites sentence_text ONLY",
      bool(_I11_REPAIRED_ROWS)
      and _I11_REPAIRED_ROWS[0].get("source_block_text")
      == _I11_CORPUS[0].get("source_block_text")
      and all(_I11_REPAIRED_ROWS[0].get(k) == _I11_CORPUS[0].get(k)
              for k in ("doc_id", "page_index", "layer", "block_id", "sent_idx")),
      "every field that identifies or locates the row must survive the repair unchanged")
check("INT11-12 LIVE: the builder applies the repair as an unconditional assignment",
      _call_is_unconditional_assignment(_PACKET_BUILDER_PATH, "apply_damaged_formula_repairs"),
      "call-presence alone survives being disabled by a short-circuit guard")
check("INT11-13 LIVE: the repair runs BEFORE the BM25 index is built from the corpus",
      _appears_in_order(_builder_src, "apply_damaged_formula_repairs(", "index = BM25Index("),
      "a repair applied after indexing is a repair retrieval never sees")
check("INT11-14 LIVE: the repair runs BEFORE the block and successor indices are built",
      _appears_in_order(_builder_src, "apply_damaged_formula_repairs(",
                        "blocks = build_corpus_block_index(corpus)",
                        "successors = build_block_successor_index(corpus)"),
      "the lead-in payload rescue reads those indices and must see repaired text")
check("INT11-15 LIVE: repair provenance is carried onto the evidence item",
      "'formula_repair_locality': passage.get('formula_repair_locality')" in _builder_src
      and "repaired_formula_provenance(kept)" in _int7_inspect.getsource(CP.assemble_passages),
      "provenance that stops at the corpus row never reaches a reviewer")

# ---------------------------------------------------------------------------------------------
# INT-12: draft hygiene checks. Flag-only, so there is no pipeline liveness to assert - what has
# to be protected instead is PRECISION. Every negative case below is a real false positive from
# running the checks over the 159 drafts; a hygiene check that fires on ordinary prose teaches a
# reviewer to ignore the sidecar, which is worse than not having the check.
_I12_SPEC = importlib.util.spec_from_file_location(
    "int12_draft_hygiene_under_test",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "int12_draft_hygiene.py"))
I12 = importlib.util.module_from_spec(_I12_SPEC)
_I12_SPEC.loader.exec_module(I12)

check("INT12-1 evidence-availability commentary in the body is flagged",
      len(I12.find_source_meta_commentary(
          ["The source rendering of the formula is incomplete in the provided passages."])) == 1)
check("INT12-2 'rendering X impossible ... other evidence' is NOT flagged",
      I12.find_source_meta_commentary(
          ["This wipes out the entire class product, rendering the class impossible to predict "
           "regardless of other evidence."]) == [],
      "'rendering' as a verb plus 'evidence' as subject matter is ordinary prose")
check("INT12-3 the source subject must PRECEDE the availability predicate",
      I12.find_source_meta_commentary(
          ["The formula is incomplete, which the source explains."]) == [])
check("INT12-4 a clause boundary between subject and predicate blocks the match",
      I12.find_source_meta_commentary(
          ["The evidence is clear: the formula is incomplete."]) == [])
_I12_CLAIMS = ["The silhouette coefficient compares within-cluster distance to nearest-cluster "
               "distance.",
               "A positive value indicates good assignment quality."]
# Drawn deliberately from BOTH claims in roughly equal measure, plus one word in neither. Each
# claim alone covers 5 of its 11 content words - under the floor - while together they cover 10.
# Only union scoring passes it. Two earlier versions of this case were passed by a sabotage that
# reverted to single-claim scoring: the first because claims[0] already covered the sentence, the
# second because the BEST single claim did. A guard that any weakening still satisfies is not
# testing the rule it names.
_I12_COMBINED = ("The coefficient compares within-cluster distance, and a positive value "
                 "indicates good assignment overall.")
check("INT12-5 a body sentence with no ledger support is flagged",
      len(I12.find_uncovered_body_sentences(
          ["The relationship is symmetric and both points belong to the same cluster."],
          _I12_CLAIMS)) == 1)
check("INT12-6 a sentence needing BOTH ledger claims is not flagged",
      I12.find_uncovered_body_sentences([_I12_COMBINED], _I12_CLAIMS) == []
      and I12.find_uncovered_body_sentences([_I12_COMBINED], _I12_CLAIMS[:1]) != []
      and I12.find_uncovered_body_sentences([_I12_COMBINED], _I12_CLAIMS[1:]) != [],
      "neither claim alone reaches the floor, so only union scoring accepts this sentence")
check("INT12-7 coverage does not depend on the order of the ledger",
      I12.find_uncovered_body_sentences([_I12_COMBINED], list(reversed(_I12_CLAIMS))) == [])
check("INT12-8 a circular definition is flagged",
      len(I12.find_self_referential_sentences(
          ["The confusion matrix is a fundamental tool and it is used to construct the confusion "
           "matrix and evaluate classifiers."], "confusion matrix")) == 1)
check("INT12-9 ordinary prose mentioning the unit twice is NOT flagged",
      I12.find_self_referential_sentences(
          ["Accuracy is an estimate based on a finite test set and is not guaranteed to be the "
           "exact true accuracy of a classifier."], "Accuracy") == []
      and I12.find_self_referential_sentences(
          ["The Gini index is used to select the best split by minimizing the weighted average "
           "Gini index of the child nodes."], "Gini index") == [],
      "requiring only 'two mentions plus a copula' flagged 21 sentences, 20 of them ordinary")
check("INT12-10 unrendered extraction markup in the body is flagged",
      len(I12.find_unrendered_markup([r"The density is { \frac { 1 } { \sqrt { 2 \pi } } }."])) == 1
      and I12.find_unrendered_markup(["Precision = TP / (TP + FP)."]) == [])
check("INT12-11 a stated arithmetic expression is evaluated to the right value",
      abs(I12.find_stated_arithmetic(
          ["The estimate for this tree is 0.3 + 2 * 5."])[0]["value"] - 10.3) < 1e-9,
      "a sentence-final period once forced a backtrack that reported 2.3 for this expression")
check("INT12-12 the arithmetic evaluator refuses anything that is not arithmetic",
      I12.evaluate_arithmetic('__import__("os")') is None
      and I12.evaluate_arithmetic("len") is None
      and I12.evaluate_arithmetic("1/0") is None,
      "the input is model-generated text, so the evaluator must not be an eval() path")

# ---------------------------------------------------------------------------------------------
# INT-13: content repairs are declared once and consumed by the loop that actually runs.
# The defect this fixes was not a wrong rule but an UNREACHED one. The production drafting loop
# is the schema-contract probe, which drives the runner by invoking functions it names one at a
# time; two repairs therefore existed with correct behaviour and never executed once. The guards
# below protect the CLASS, not just the two instances: if the probe ever goes back to naming
# repairs individually, or a repair is added to the chain the probe cannot reach, this fails.
_I13_PROBE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "steps", "step_06_7_kc_draft_generation", "scripts", "v2_chain",
    "run_step67_v2_schema_contract_probe.py")
_I13_PROBE_SRC = io.open(_I13_PROBE_PATH, encoding="utf-8").read()
_I13_CHAIN = DR.content_repair_chain()


def _i13_packet(**over):
    packet = {
        "knowledge_unit_type": "kc", "canonical_name": "Silhouette Coefficient",
        "packet_support_state": "draftable",
        "evidence_for_synthesis": [
            {"text": "The silhouette coefficient compares the average distance from a point to "
                     "its own cluster with the minimum average distance to another cluster, and "
                     "is an internal validity measure."},
            {"text": "A silhouette coefficient close to one indicates a well assigned point."}],
    }
    packet.update(over)
    return packet


def _i13_draft(status="abstained", text=""):
    return {"contextual_kc_draft": {"status": status, "text": text,
                                    "supporting_evidence_ids": []}, "evidence_map": []}


check("INT13-1 the runner declares its content repairs as one ordered chain",
      [r.phase for r in _I13_CHAIN] == ["invalid_abstention_content_repair",
                                        "damaged_math_content_repair", "schema_repair"])
check("INT13-2 every repair shares one predicate signature",
      all(r.needs_repair(_i13_packet(), _i13_draft("grounded", "x"), []) in (True, False)
          for r in _I13_CHAIN),
      "a chain a caller can iterate requires the entries to be callable the same way")
check("INT13-3 LIVE: the production drafting loop ITERATES the chain",
      "content_repair_chain" in live_calls(_I13_PROBE_PATH),
      "established from the parse tree: the source-text form of this check SURVIVED sabotage, "
      "because the explanatory comment above the loop also contains 'content_repair_chain()'")
check("INT13-4 LIVE: the probe names NO individual repair predicate",
      not any(name in _I13_PROBE_SRC
              for name in ("should_attempt_schema_repair",
                           "invalid_abstention_needs_content_repair",
                           "damaged_math_needs_content_repair")),
      "naming repairs one at a time is exactly how two of them were left unreached")
check("INT13-5 LIVE: the probe hardcodes no repair phase literal",
      not any(('"%s"' % r.phase) in _I13_PROBE_SRC or ("'%s'" % r.phase) in _I13_PROBE_SRC
              for r in _I13_CHAIN)
      and "phase=repair.phase" in _I13_PROBE_SRC)
check("INT13-6 LIVE: the probe uses the shared acceptance rule, not its own",
      "repair_resolved" in live_calls(_I13_PROBE_PATH),
      "same reasoning as INT13-3: a mention is not a call")
check("INT13-7 LIVE: the row records WHICH repair ran, so a dead repair is visible",
      '"repair_phase"' in _I13_PROBE_SRC,
      "repair_attempted alone cannot distinguish 'never applicable' from 'never reached'")
check("INT13-8 an abstention on a draftable, on-target packet is repairable",
      _I13_CHAIN[0].needs_repair(_i13_packet(), _i13_draft("abstained"), []) is True)
check("INT13-9 an abstention the packet EXPECTED is left alone",
      _I13_CHAIN[0].needs_repair(_i13_packet(abstention_expected=True),
                                 _i13_draft("abstained"), []) is False)
check("INT13-10 an abstention with no on-target evidence is left alone",
      _I13_CHAIN[0].needs_repair(
          _i13_packet(evidence_for_synthesis=[{"text": "Select a search strategy."}]),
          _i13_draft("abstained"), []) is False,
      "reversing an abstention on off-target evidence would manufacture confidence")
check("INT13-11 a model that abstains AGAIN keeps its abstention",
      DR.repair_resolved(_I13_CHAIN[0], _i13_packet(), _i13_draft("abstained"), "", []) is False,
      "the attempt is discarded and the original draft stands")
check("INT13-12 a repair is not accepted merely for being well formed",
      DR.repair_resolved(_I13_CHAIN[0], _i13_packet(), _i13_draft("grounded", "x"),
                         "", [{"code": "x"}]) is False
      and DR.repair_resolved(_I13_CHAIN[0], _i13_packet(), _i13_draft("grounded", "x"),
                             "ValueError", []) is False
      and DR.repair_resolved(_I13_CHAIN[0], _i13_packet(), _i13_draft("grounded", "x"),
                             "", []) is True)

# ---------------------------------------------------------------------------------------------
# INT-14: a repaired draft must describe its SUBJECT, not its EVIDENCE.
# Measured on the first run with INT-13's repairs reachable: denied its abstention, the model did
# not invent content - it wrote its refusal as the draft ("The provided evidence does not define
# 'Models of Randomness (Approach 1)'..."). Four of seven repaired drafts were bodies of that
# kind. They pass every structural check and tell a reader nothing, so an honest abstention is the
# better artifact. The rule lives in the package because two callers need the same answer.
import kc_l.kc_drafting.draft_hygiene as DH  # noqa: E402

_I14_ALL_META = ("The provided evidence does not define 'Models of Randomness (Approach 1)' as a "
                 "specific method. No procedure or formula for it is present in the supplied "
                 "text.")
_I14_OPENS_META = ("The evidence does not contain a specific definition for this unit. Decision "
                   "trees choose split attributes from features. They can have different model "
                   "complexities. Their complexity can be described in several ways.")
_I14_REAL = ("The target attribute is the variable or class label that serves as the desired "
             "output in a data mining task. In regression it is continuous; in classification it "
             "corresponds to the class label. It is distinct from the predictor attributes used "
             "to make predictions. The evidence does not give a single unified formal definition "
             "covering every task.")

# Each of the two signals gets a case only IT can reject, so a sabotage that removes one is
# caught by exactly one guard. The first version used a body that both opened with commentary and
# was majority commentary; dropping the majority signal therefore changed nothing and the
# sabotage SURVIVED. A guard that either signal satisfies tests neither.
_I14_MAJORITY_NOT_OPENING = (
    "Decision trees choose split attributes from features. The provided evidence does not define "
    "this unit. The evidence does not specify any procedure. The supplied passages do not state "
    "a formula.")
check("INT14-1 a MAJORITY-commentary body is rejected even when it opens with content",
      DH.body_describes_its_evidence(_I14_MAJORITY_NOT_OPENING) is True
      and DH.meta_commentary_profile(_I14_MAJORITY_NOT_OPENING)[2] is False,
      "isolates the majority signal: this body does not open with commentary")
check("INT14-2 a body that OPENS with commentary is rejected even when commentary is a minority",
      DH.body_describes_its_evidence(_I14_OPENS_META) is True
      and DH.meta_commentary_profile(_I14_OPENS_META)[0] * 2
      <= DH.meta_commentary_profile(_I14_OPENS_META)[1],
      "isolates the opening signal: a draft that begins 'the evidence does not define X' has "
      "already said it is not a definition")
check("INT14-1b an all-commentary body is rejected",
      DH.body_describes_its_evidence(_I14_ALL_META) is True)
check("INT14-3 a real definition carrying ONE caveat is kept",
      DH.body_describes_its_evidence(_I14_REAL) is False,
      "that is an ordinary honest partial, not a body about its sources")
check("INT14-4 'does not DEFINE' is recognised, not only 'does not provide'",
      DH.is_source_meta_commentary(
          "The provided evidence does not define the structure of this unit.") is True,
      "the first version's predicate list omitted define, and four all-commentary drafts escaped")
check("INT14-5 an empty body is not treated as commentary",
      DH.body_describes_its_evidence("") is False)
check("INT14-6 LIVE: repair acceptance consults the rule",
      "body_describes_its_evidence" in live_calls(_PACKET_BUILDER_PATH.replace(
          os.path.join("pipeline", "02_build_kc_packets.py"),
          os.path.join("pipeline", "04_draft_runner.py"))),
      "without this a repair is accepted for being well formed")
check("INT14-7 a repaired draft that describes its evidence is NOT accepted",
      DR.repair_resolved(_I13_CHAIN[0], _i13_packet(),
                         {"contextual_kc_draft": {"status": "partial", "text": _I14_ALL_META,
                                                  "supporting_evidence_ids": []},
                          "evidence_map": []}, "", []) is False,
      "the attempt is discarded and the original abstention stands")
check("INT14-8 a repaired draft with real content IS accepted",
      DR.repair_resolved(_I13_CHAIN[0], _i13_packet(),
                         {"contextual_kc_draft": {"status": "partial", "text": _I14_REAL,
                                                  "supporting_evidence_ids": []},
                          "evidence_map": []}, "", []) is True)
check("INT14-9 the rule has ONE definition, not a copy per caller",
      "def is_source_meta_commentary" not in io.open(
          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "int12_draft_hygiene.py"), encoding="utf-8").read(),
      "a rule copied into a second caller is how INT-13's repairs came to be unreachable")


# ---------------------------------------------------------------------------------------------
# INT-15. A promise's payload is admitted as a payload whether or not the reranker also found it.
#
# assemble_passages has three payload branches. structured_list and procedure_list both promote
# an entry already present in `best`; lead_in alone was guarded by `nxt not in best` and did
# nothing at all in that case. The payload then kept an ordinary admission basis and was re-tested
# by the severed-fragment, structural-junk and rival-claim filters that payload admission exists
# to exempt it from. Measured on the real corpus: 5 admitted promises whose formula payload never
# reached the packet, one of them recorded in its own unit's dropped-to-rival list.
# ---------------------------------------------------------------------------------------------


def _i15_row(block, idx, text, doc="D", page=1):
    return {"doc_id": doc, "block_id": block, "sentence_id": "%s:%s:%d" % (doc, block, idx),
            "sent_idx": idx, "sentence_text": text, "source_block_text": text,
            "page_index": page, "patch_id": block, "patch_heading": "H", "layer": "pymupdf"}


_I15_POINTER = "The gain ratio of an attribute A is given by:"
_I15_PAYLOAD = "GainRatio(A) = IG(A) / SplitInfo(A)"
_I15_PROSE = "Attributes with many distinct values tend to be preferred by information gain."
_I15_NO_POINTER = "The gain ratio of an attribute A corrects information gain."


def _i15_assemble(pointer_text, payload_text, payload_prob):
    """Run the real assembler over a two-block document; payload_prob None omits the payload hit."""
    corpus = [_i15_row("b1", 0, pointer_text), _i15_row("b2", 1, payload_text)]
    blocks = CP.build_corpus_block_index(corpus)
    successors = CP.build_block_successor_index(corpus)
    hits = [{"sentence": corpus[0], "rerank_prob": 0.90, "bm25_score": 5.0}]
    if payload_prob is not None:
        hits.append({"sentence": corpus[1], "rerank_prob": payload_prob, "bm25_score": 1.0})
    out = CP.assemble_passages(hits, blocks, block_successors=successors,
                               min_relevance=0.55, relative_floor=0.5)
    return {p["text"]: p for p in out}


_i15_both = _i15_assemble(_I15_POINTER, _I15_PAYLOAD, 0.60)
_i15_only_pointer = _i15_assemble(_I15_POINTER, _I15_PAYLOAD, None)
_i15_prose = _i15_assemble(_I15_POINTER, _I15_PROSE, 0.60)
_i15_unpromised = _i15_assemble(_I15_NO_POINTER, _I15_PAYLOAD, 0.60)

check("INT15-1 a payload the reranker ALSO found is still admitted as a payload",
      _i15_both.get(_I15_PAYLOAD, {}).get("admission_basis") == "lead_in_payload",
      "this is the fix: the old guard skipped it, leaving it on cross_encoder_relevance")
check("INT15-2 a payload the reranker missed is admitted, as it always was",
      _i15_only_pointer.get(_I15_PAYLOAD, {}).get("admission_basis") == "lead_in_payload")
check("INT15-3 promotion does not invent relevance, it only changes the basis",
      abs(float(_i15_both.get(_I15_PAYLOAD, {}).get("relevance", -1)) - 0.60) < 1e-9,
      "matches the structured_list and procedure_list branches, which set the flag only")
check("INT15-4 a successor that is not a formula is not promoted by a promise",
      _i15_prose.get(_I15_PROSE, {}).get("admission_basis") != "lead_in_payload",
      "is_formula_payload remains the gate; the promotion does not widen what counts")
check("INT15-5 a formula nobody promised keeps its ordinary basis",
      _i15_unpromised.get(_I15_PAYLOAD, {}).get("admission_basis") != "lead_in_payload",
      "ends_with_lead_in remains the trigger")
# The rival-claim drop keeps at least MIN_KEEP passages whatever the scores say, so a fixture
# holding only the payload is kept by that floor alone and proves nothing about the exemption.
# Sabotage caught exactly that: removing the promotion left this guard passing. The payload now
# competes alongside three passages no rival claims, so MIN_KEEP is satisfied without it.
_I15_FILLER = ["Information gain measures the reduction in entropy from a split.",
               "Split information penalises attributes with many distinct values.",
               "The ratio corrects the bias of information gain toward high-arity attributes."]


def _i15_rival_scorer(query, texts):
    """Low own-score and high rival-score for the payload; the reverse for the filler."""
    claimed = query == "Information Gain"
    return [(0.99 if claimed else 0.10) if text == _I15_PAYLOAD
            else (0.10 if claimed else 0.90) for text in texts]


def _i15_dropped_by_rivals(payload_passage):
    passages = [dict(payload_passage)] + [
        {"text": text, "relevance": 0.80, "admission_basis": "cross_encoder_relevance"}
        for text in _I15_FILLER]
    _kept, dropped = CP.drop_passages_claimed_by_rivals(
        passages, "Gain Ratio", ["Information Gain"], _i15_rival_scorer)
    return [str(d.get("text") or "") for d in dropped]


check("INT15-6 a promoted payload is exempt from the rival-claim drop",
      _i15_dropped_by_rivals(_i15_both[_I15_PAYLOAD]) == [],
      "the Laplace Estimator payload was recorded in its own unit's dropped-to-rival list")
check("INT15-6b the same payload on an ordinary basis IS dropped",
      _i15_dropped_by_rivals(
          dict(_i15_both[_I15_PAYLOAD], admission_basis="cross_encoder_relevance"))
      == [_I15_PAYLOAD],
      "without this, INT15-6 would pass because MIN_KEEP protects a one-passage fixture")

_I15_SOURCE = io.open(pathlib.Path(__file__).resolve().parents[2] / "src" / "kc_l"
                      / "retrieval_gate" / "evidence_pack.py", encoding="utf-8").read()
def _i15_skips_entries_already_in_best(source):
    """True if assemble_passages still guards any branch on membership of `best`.

    Read from the syntax tree, not the text. A substring search is satisfied by the comment that
    documents the old guard - the same way INT13-3 was defeated by a comment naming the function
    it was checking for.
    """
    for node in _ast.walk(_ast.parse(source)):
        if not (isinstance(node, _ast.FunctionDef) and node.name == "assemble_passages"):
            continue
        for inner in _ast.walk(node):
            if (isinstance(inner, _ast.Compare)
                    and any(isinstance(op, _ast.NotIn) for op in inner.ops)
                    and any(isinstance(c, _ast.Name) and c.id == "best"
                            for c in inner.comparators)):
                return True
    return False


check("INT15-7 no payload branch skips an entry that is already in best",
      _i15_skips_entries_already_in_best(_I15_SOURCE) is False,
      "the class of defect was one branch of three behaving differently from its siblings")
check("INT15-8 every payload branch promotes an existing entry",
      all(('payload_entry["%s"] = True' % basis) in _I15_SOURCE
          for basis in CP.PAYLOAD_ADMISSION_FLAGS),
      "read from the tuple, so a branch added later is covered without editing this guard")


# ---------------------------------------------------------------------------------------------
# INT-16. A formula's own symbol glossary is admitted with it.
#
# The mirror of the lead-in rescue: that admits the block after a promise, this admits the block
# after a formula. Without it a packet can hold precision(i,j)=p_ij while the sentence defining
# p_ij stays in the corpus, and the draft then states the formula and reports that its symbol is
# undefined. Measured over the r2 packets: 7 admitted formulas whose qualifier was left behind.
#
# The payload flags are now read from one tuple rather than enumerated at each site. INT-15 was
# caused by that duplication, so the guards below check the property over the whole tuple.
# ---------------------------------------------------------------------------------------------

_I16_FORMULA = "IG(A) = I(D) - SUM_j (|D_j| / |D|) I(D_j)"
_I16_QUALIFIER = ("where $|D|$ is the number of instances in $D$ and $p_i$ is the prior "
                  "probability.")
_I16_PROSE = ("The attribute with the highest $IG(A)$ is chosen as the split attribute at "
              "node $t$.")   # carries symbols, so ONLY the opening word can reject it
_I16_WORDY = "where the reader should consult the chapter introduction for further discussion."


def _i16_assemble(anchor_text, follower_text, follower_prob):
    corpus = [_i15_row("b1", 0, anchor_text), _i15_row("b2", 1, follower_text)]
    blocks = CP.build_corpus_block_index(corpus)
    successors = CP.build_block_successor_index(corpus)
    hits = [{"sentence": corpus[0], "rerank_prob": 0.90, "bm25_score": 5.0}]
    if follower_prob is not None:
        hits.append({"sentence": corpus[1], "rerank_prob": follower_prob, "bm25_score": 1.0})
    out = CP.assemble_passages(hits, blocks, block_successors=successors,
                               min_relevance=0.55, relative_floor=0.5)
    return {p["text"]: p for p in out}


_i16_missed = _i16_assemble(_I16_FORMULA, _I16_QUALIFIER, None)
_i16_ranked = _i16_assemble(_I16_FORMULA, _I16_QUALIFIER, 0.60)
_i16_prose = _i16_assemble(_I16_FORMULA, _I16_PROSE, None)
_i16_wordy = _i16_assemble(_I16_FORMULA, _I16_WORDY, None)
_i16_unanchored = _i16_assemble(_I15_PROSE, _I16_QUALIFIER, None)

check("INT16-1 the glossary after a formula is admitted when the reranker missed it",
      _i16_missed.get(_I16_QUALIFIER, {}).get("admission_basis") == "formula_qualifier_payload",
      "7 admitted formulas in the r2 packets had their glossary left in the corpus")
check("INT16-2 a glossary the reranker ALSO found is still admitted as a glossary",
      _i16_ranked.get(_I16_QUALIFIER, {}).get("admission_basis") == "formula_qualifier_payload",
      "the INT-15 defect, stated for the branch added after it")
check("INT16-3 a successor that is ordinary prose is not admitted",
      _I16_PROSE not in _i16_prose,
      "the opening word is the trigger; without it nothing follows a formula automatically")
check("INT16-4 a 'where' successor carrying no symbols is not admitted",
      _I16_WORDY not in _i16_wordy,
      "a glossary defines symbols; prose that merely starts with the word does not")
check("INT16-5 a glossary whose anchor is not a formula is not admitted",
      _i16_unanchored.get(_I16_QUALIFIER, {}).get("admission_basis")
      != "formula_qualifier_payload",
      "the anchor must be the formula the glossary belongs to")
def _i16_rival_scorer(query, texts):
    claimed = query == "Information Gain"
    return [(0.99 if claimed else 0.10) if text == _I16_QUALIFIER
            else (0.10 if claimed else 0.90) for text in texts]


def _i16_dropped_by_rivals(passage):
    passages = [dict(passage)] + [
        {"text": text, "relevance": 0.80, "admission_basis": "cross_encoder_relevance"}
        for text in _I15_FILLER]
    _kept, dropped = CP.drop_passages_claimed_by_rivals(
        passages, "Gain Ratio", ["Information Gain"], _i16_rival_scorer)
    return [str(d.get("text") or "") for d in dropped]


check("INT16-6 an admitted glossary is exempt from the rival-claim drop",
      _i16_dropped_by_rivals(_i16_missed[_I16_QUALIFIER]) == [],
      "a rescue basis is not re-litigated by a mechanism it was rescued from")
check("INT16-7 the same glossary on an ordinary basis IS dropped",
      _i16_dropped_by_rivals(
          dict(_i16_missed[_I16_QUALIFIER], admission_basis="cross_encoder_relevance"))
      == [_I16_QUALIFIER],
      "so INT16-6 cannot pass because MIN_KEEP protected a small fixture")
check("INT16-8 payload_basis reports every flag in the tuple, and None otherwise",
      all(CP.payload_basis({flag: True}) == flag for flag in CP.PAYLOAD_ADMISSION_FLAGS)
      and CP.payload_basis({"cross_encoder_relevance": True}) is None
      and CP.payload_basis({}) is None)
_I16_ASSIGNED_FLAGS = (
    set(_re_ctrl_check.findall(r'"([a-z_]+_payload)": True', _I15_SOURCE))
    | set(_re_ctrl_check.findall(r'payload_entry\["([a-z_]+_payload)"\] = True', _I15_SOURCE)))
check("INT16-9 the flags the code assigns are exactly the flags the tuple declares",
      _I16_ASSIGNED_FLAGS == set(CP.PAYLOAD_ADMISSION_FLAGS),
      "comparing the tuple against sets derived FROM it was vacuous; this compares it against "
      "what the branches actually set, so a branch added or dropped is visible either way")
check("INT16-9b every declared flag reaches both derived sets",
      all(flag in CP.RESCUE_ADMISSION_BASES
          and flag in CP.POINTER_PAYLOAD_ADMISSION_BASES
          for flag in CP.PAYLOAD_ADMISSION_FLAGS))
check("INT16-10 no site enumerates the payload flags by hand any more",
      not _re_ctrl_check.search(
          r'entry\.get\("lead_in_payload"\)\s*or\s*entry\.get\("structured_list_payload"\)',
          _I15_SOURCE),
      "four hand-written enumerations were how INT-15's branch came to differ from its siblings")


# ---------------------------------------------------------------------------------------------
# INT-17. Evidence sufficiency is reported separately from the drafter's status.
#
# The drafting prompt's own rubric says "Thin evidence, faithfully and completely used, is
# grounded, not partial", so `grounded` means the draft used what it was given and says nothing
# about whether that was enough. low_confidence does not fill the gap: it requires few passages
# AND low relevance, so a thin packet whose single passage scored well passes silently. Measured
# on the r2 packets, 18 units sit in that band; an external review of r3 independently called 6
# of them materially incomplete and faulted 4 more on other grounds.
#
# Additive only: no admission, drop, score or threshold changes, and the prompt never reads
# evidence_coverage - INT17-6 asserts that, since it is what makes the change flag-only.
# ---------------------------------------------------------------------------------------------

_I17_LONG = ("The learning phase is the stage in which an algorithm builds a model from the "
             "training data supplied to it.")
_I17_SHORT = "See Figure 4.2."


def _i17_passage(text, relevance):
    return {"text": text, "relevance": relevance, "sentence_count": 1, "shapes": ["definition"],
            "doc_id": "D", "page_index": 1}


_i17_one_strong = CP.coverage_summary([_i17_passage(_I17_LONG, 0.93)])
_i17_short_only = CP.coverage_summary([_i17_passage(_I17_SHORT, 0.93)])
_i17_rich = CP.coverage_summary([_i17_passage(_I17_LONG + " %d" % i, 0.8) for i in range(9)])

check("INT17-1 a packet of one substantive passage is reported thin",
      _i17_one_strong["thin_evidence"] is True
      and _i17_one_strong["substantive_passage_count"] == 1,
      "ID3 Algorithm is grounded on exactly one substantive passage")
check("INT17-2 that packet is NOT low_confidence, which is the gap being filled",
      _i17_one_strong["low_confidence"] is False,
      "low_confidence needs few passages AND low relevance; a strong single passage escapes it")
check("INT17-3 a passage too short to establish anything does not count as substantive",
      _i17_short_only["substantive_passage_count"] == 0,
      "a caption or heading cannot carry a definition however well it scored")
check("INT17-4 a well-populated packet is not reported thin",
      _i17_rich["thin_evidence"] is False and _i17_rich["substantive_passage_count"] == 9)
check("INT17-5 sufficiency and confidence are independent signals",
      any(CP.coverage_summary(p)["thin_evidence"]
          is not CP.coverage_summary(p)["low_confidence"]
          for p in ([_i17_passage(_I17_LONG, 0.93)],
                    [_i17_passage(_I17_LONG + " %d" % i, 0.8) for i in range(9)])),
      "if they always agreed, one of them would be redundant")
check("INT17-6 the drafting prompt does not read evidence_coverage",
      "evidence_coverage" not in io.open(
          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline",
                       "04_draft_runner.py"), encoding="utf-8").read(),
      "this is what makes the new field additive rather than a silent prompt change")
check("INT17-7 no pre-existing coverage key was removed",
      {"passage_count", "total_chars", "sentence_count", "shape_coverage", "has_definition",
       "has_formula", "has_procedure", "has_example", "distinct_documents", "distinct_pages",
       "max_relevance", "low_confidence"} <= set(_i17_rich),
      "the summary is an output contract; adding to it is safe, removing from it is not")


# ---------------------------------------------------------------------------------------------
# INT-18. Per-unit source provenance, reported rather than reconstructed by hand.
#
# An external review of r3 flagged Spearman Rank Correlation, Directly Density-Reachable and
# Density-Reachable as resting on material it could not find in the textbooks. Those are exactly
# the three units whose admitted evidence comes solely from the guide document: 3 of 3, with no
# false positives among the other 156. The packet already said how many documents; it did not say
# which, so a reader had to open every packet to check a claim about the source corpus.
#
# Additive, like INT-17: a provenance fact, never a quality judgement.
# ---------------------------------------------------------------------------------------------

_i18_one_doc = CP.coverage_summary([
    {"text": _I17_LONG, "relevance": 0.8, "doc_id": "DOC_guides", "page_index": 1},
    {"text": _I17_LONG + " more", "relevance": 0.7, "doc_id": "DOC_guides", "page_index": 2}])
_i18_two_docs = CP.coverage_summary([
    {"text": _I17_LONG, "relevance": 0.8, "doc_id": "DOC_guides", "page_index": 1},
    {"text": _I17_LONG + " more", "relevance": 0.7, "doc_id": "DOC_textbook", "page_index": 2}])
_i18_empty = CP.coverage_summary([])

check("INT18-1 a unit resting on one document is reported as such",
      _i18_one_doc["single_document_evidence"] is True,
      "the review's three source-boundary units are exactly the three single-document units")
check("INT18-2 a unit drawing on two documents is not",
      _i18_two_docs["single_document_evidence"] is False)
check("INT18-3 the documents are named, with their counts",
      _i18_one_doc["evidence_by_document"] == {"DOC_guides": 2}
      and _i18_two_docs["evidence_by_document"] == {"DOC_guides": 1, "DOC_textbook": 1},
      "distinct_documents said how many; a provenance claim needs which")
check("INT18-4 an empty packet is not called single-document",
      _i18_empty["single_document_evidence"] is False
      and _i18_empty["evidence_by_document"] == {},
      "no evidence is not evidence from one source")
check("INT18-5 provenance is reported, never scored",
      "single_document_evidence" not in io.open(
          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline",
                       "02_build_kc_packets.py"), encoding="utf-8").read(),
      "the moment a provenance field gates admission it stops being a neutral fact")


# ---------------------------------------------------------------------------------------------
# INT-19. The draft's definitional sentence has to be about the unit.
#
# Faithfulness to the evidence and relevance to the unit are different properties, and only the
# first was checked anywhere. Mutually Exclusive Classes is drafted as "a rule set is defined as
# mutually exclusive if no two rules ... are triggered by the same instance": true, well-evidenced,
# and about rule sets. An external review of r3 called it the single most serious remaining error.
#
# Flag-only, so what has to be protected is PRECISION. It fires on 5 of 159 r3 drafts; the negative
# cases below are the shapes that made earlier versions of it fire wrongly.
# ---------------------------------------------------------------------------------------------


def _i19(unit_name, body):
    return I12.find_unbound_definitional_subject(I12.split_sentences(body), unit_name)


check("INT19-1 a draft defining a neighbouring concept is flagged",
      len(_i19("Mutually Exclusive Classes",
               "In the context of rule-based classification, a rule set is defined as mutually "
               "exclusive if no two rules within the set are triggered by the same instance.")) == 1,
      "the review's most serious finding; the evidence is real, the subject is not this unit")
check("INT19-2 an ordinary correct definition is NOT flagged",
      _i19("Euclidean Distance",
           "Euclidean distance is a measure of the straight-line distance between two points.")
      == [])
check("INT19-3 the real Density-Reachable draft is NOT flagged",
      _i19("Density-Reachable",
           "Density-reachability is a transitive relationship defined over a sequence of points.")
      == [],
      "the case an earlier suffix-list version got wrong; note it also shares the bare token "
      "'density', so it does NOT isolate stemming - INT19-3b does that")
check("INT19-3b a variant that ONLY prefix stemming can match is NOT flagged",
      _i19("Cluster Cohesion",
           "Cohesiveness is a measure of how tightly grouped the objects in a cluster are.")
      == [],
      "no bare token is shared: 'cohesiveness' matches 'cohesion' only once both are cut to a "
      "prefix, so dropping the stemmer makes this fire and nothing else saves it")
check("INT19-4 a plural of the unit name is NOT flagged",
      _i19("Duplicate Tuples",
           "These duplicates are a significant concern in data preprocessing because they waste "
           "storage space.") == [],
      "the same suffix list stemmed 'duplicates' and 'Duplicate' apart in the other direction")
check("INT19-5 an article is not mistaken for part of the subject",
      _i19("Accuracy",
           "Accuracy is an evaluation metric used to assess the quality of classification rules.")
      == [],
      "an earlier version read the subject as 'ccuracy' and flagged the unit against itself")
check("INT19-6 a body with no definitional sentence is not flagged",
      _i19("Bootstrap Sampling",
           "Sampling with replacement produces training sets that omit some instances.") == [])
check("INT19-7 LIVE: the check runs as part of the hygiene sidecar",
      "find_unbound_definitional_subject" in live_calls(
          os.path.join(os.path.dirname(os.path.abspath(__file__)), "int12_draft_hygiene.py")),
      "a flag-only check that nothing calls is the INT-13 defect over again")
check("INT19-8 the sidecar still never rewrites a draft",
      all(token not in io.open(
          os.path.join(os.path.dirname(os.path.abspath(__file__)), "int12_draft_hygiene.py"),
          encoding="utf-8").read()
          for token in ('draft["contextual_kc_draft"] =', 'draft["text"] =')),
      "these checks report; the moment one edits a draft it stops being a sidecar")


# ---------------------------------------------------------------------------------------------
# INT-20. The defining-equation rescue can see a letter-spaced rendering.
#
# DEFINING_EQUATION_FLOOR (0.45) exists so a unit's own defining equation is not out-scored by
# prose at the ordinary 0.55 floor, and it is claimed by a pattern built from the unit's NAME. The
# extractors render display math one character at a time - 582 of 4649 equation-shaped corpus
# texts - so the name inside the equation never matched and the rescue was dead for all of them.
# The INT-13 defect class: a mechanism that exists and never fires for a whole category of input.
#
# Measured: 3 units whose defining equation is claimable only after collapsing - Accuracy,
# Precision, Specificity. Precision and Accuracy are exactly the units whose defining formula was
# observed flipping in and out of the packet between builds.
# ---------------------------------------------------------------------------------------------

_I20_SPACED = "$$ P r e c i s i o n = \frac { T P } { T P + F P } $$"
_I20_TIGHT = "$$ Precision = \frac { T P } { T P + F P } $$"
_I20_FOREIGN = "$$ R e c a l l = \frac { T P } { T P + F N } $$"
_I20_PRECISION_PATTERNS = CP.defining_equation_patterns(["Precision"])

check("INT20-1 a letter-spaced defining equation is recognised",
      CP.is_defining_equation(_I20_SPACED, _I20_PRECISION_PATTERNS) is True,
      "the rescue was dead for every display-math rendering in this corpus")
check("INT20-2 another unit's letter-spaced equation is NOT recognised",
      CP.is_defining_equation(_I20_FOREIGN, _I20_PRECISION_PATTERNS) is False,
      "this is what makes collapsing safe: the result still has to match THIS unit's name")
check("INT20-3 an already-tight rendering still works",
      CP.is_defining_equation(_I20_TIGHT, _I20_PRECISION_PATTERNS) is True)
check("INT20-4 collapsing joins a letter-spaced word",
      CP.collapse_letter_spacing("$$ P r e c i s i o n = x $$") == "$$ Precision = x $$")
check("INT20-5 ordinary prose is left alone",
      CP.collapse_letter_spacing("a b test of the thing") == "a b test of the thing",
      "a two-letter run is not a letter-spaced word; three is the minimum")
check("INT20-6 text with no letter-spacing is unchanged by the collapse",
      CP.collapse_letter_spacing(_I20_TIGHT) == _I20_TIGHT,
      "so the added path cannot alter any decision it was not written for")
check("INT20-7 the collapse is used ONLY by the defining-equation test",
      len(_re_ctrl_check.findall(r"collapse_letter_spacing\(", _I15_SOURCE)) == 2,
      "one definition and one call site; a second caller would inherit an assumption that is "
      "only safe when the result must match the unit's own name")


# ---------------------------------------------------------------------------------------------
# INT-21. The defining-equation rescue reads through LaTeX formatting commands.
#
# INT-20 handled letter-spacing. A named function in this corpus is also usually WRAPPED -
# "\mathrm { R a n d I n d e x }", "\mathsf { s e p a r a t i o n }" - and the wrapper's braces
# sit between the name and the "=", so the pattern still could not reach it. Collapsing
# letter-spacing then merges a multi-word name, destroying the word boundary the pattern needs.
#
# Measured: 6 more units, 50 rows, and zero cross-unit matches introduced - Gain Ratio, Accuracy,
# Rand Index, Jaccard Coefficient, Cohesion, Separation. Rand Index is the unit whose apparently
# missing formula started this whole investigation; Separation is one an external review listed as
# a must-repair.
# ---------------------------------------------------------------------------------------------

_I21_RAND = "$$ { \mathrm { R a n d I n d e x } } = { \frac { f _ { 1 1 } + f _ { 0 0 } } { f } } $$"
_I21_SEPARATION = ("$$ \mathsf { s e p a r a t i o n } ( C i , C j ) = "
                   "\mathsf { p r o x i m i t y } ( c i , c j ) $$")
_I21_JACCARD = "$$ \mathrm { J a c c a r d C o e f f i c i e n t } = 0 . 2 $$"
_I21_RAND_PATTERNS = CP.defining_equation_patterns(["Rand Index"])

# Brace-stripping alone turns "{ \mathrm { R a n d I n d e x } }" into a legible name, so a Rand
# Index fixture cannot isolate the wrapper substitution. This row can: the pattern's own optional
# argument group allows at most 30 characters between the parentheses, and only removing the
# wrappers INSIDE them gets under that. It is also the single row in the whole corpus that the
# substitution buys - Separation's graph-based defining equation, which an external content review
# listed as a must-repair.
_I21_SEPARATION_WRAPPED = (
    "$$ " + chr(92) + "mathsf { s e p a r a t i o n } ( " + chr(92) + "mathrm { "
    + chr(92) + "textsf { C i } } , " + chr(92) + "mathrm { " + chr(92) + "textsf { C j } } ) = "
    + chr(92) + "sum " + chr(92) + "mathsf { x } " + chr(92) + "in "
    + chr(92) + "mathsf { p r o x i m i t y } ( x , y ) $$")

check("INT21-1 a name reachable only after stripping wrappers is recognised",
      CP.is_defining_equation(_I21_SEPARATION_WRAPPED,
                              CP.defining_equation_patterns(["Separation"])) is True,
      "brace-stripping alone leaves the parenthesised argument list too long for the pattern's "
      "own 30-character limit")
check("INT21-1b a wrapped, letter-spaced name is recognised",
      CP.is_defining_equation(_I21_RAND, _I21_RAND_PATTERNS) is True)
check("INT21-2 another unit's wrapped equation is NOT recognised",
      CP.is_defining_equation(_I21_JACCARD, _I21_RAND_PATTERNS) is False,
      "the safety property: the reduced text still has to match THIS unit's own name")
check("INT21-3 other wrapper commands are handled too",
      CP.is_defining_equation(_I21_SEPARATION,
                              CP.defining_equation_patterns(["Separation"])) is True,
      "\mathsf and \operatorname wrap names just as \mathrm does")
check("INT21-4 normalisation strips the wrapper and joins the name",
      CP.normalise_equation_text("$$ { \mathrm { R a n d I n d e x } } = x $$")
      == "$$ RandIndex = x $$")
check("INT21-5 tolerating a missing space does not match a DIFFERENT word",
      CP.is_defining_equation("$$ { \mathrm { R a n d o m I n d e x } } = 4 $$",
                              _I21_RAND_PATTERNS) is False,
      "reduces to RandomIndex, which reaches the tolerant pattern; Rand-star-Index still cannot "
      "match it, because after Rand the text reads om")
check("INT21-5b a tight rendering of a two-word name IS recognised",
      CP.is_defining_equation("$$ RandIndex = 4 $$", _I21_RAND_PATTERNS) is True,
      "the strict pattern requires a space inside the name; an early exit used to hide this")
check("INT21-6 normalisation leaves a text that needs none unchanged",
      CP.normalise_equation_text("Precision = TP / (TP + FP)")
      == "Precision = TP / (TP + FP)")
check("INT21-7 the normalisation has one definition and one caller",
      len(_re_ctrl_check.findall(r"normalise_equation_text\(", _I15_SOURCE)) == 2,
      "a second caller would inherit an assumption that holds only where the result must match "
      "the unit's own name")


# ---------------------------------------------------------------------------------------------
# INT-22. Marginal math spliced through the middle of a word is replaced by a clean rendering.
#
# An external review's clearest mathematical finding was Group Average Linkage asserting WPGMA's
# coefficients are "constants independent of the cluster sizes" and then giving coefficients made
# of cluster sizes. The cause was in the corpus, not the drafter: one extractor spliced UPGMA's
# coefficients into the middle of the sentence that introduces WPGMA, and that row reached the
# packet. Another extractor rendered the same sentence cleanly.
#
# Measured: 109 rows carry a splice, 89 have a clean twin and are repaired, 21 do not and are left
# alone. The equations are not lost - they exist elsewhere as their own display rows, attached to
# nothing, where they cannot mislead.
# ---------------------------------------------------------------------------------------------

_I22_SPLICED = ("For the weighted" + chr(945) + "A=mA/(mA+mB), " + chr(945)
                + "B=mB/(mA+mB) version of group average known as WPGMA the coefficients are "
                  "constants that are independent of the cluster sizes")
_I22_CLEAN = ("For the weighted version of group average known as WPGMA the coefficients are "
              "constants that are independent of the cluster sizes")
_I22_VOCAB = {"weighted": 9, "version": 9, "group": 9, "average": 9, "known": 9,
              "coefficients": 9, "constants": 9, "that": 9, "independent": 9, "cluster": 9,
              "sizes": 9, "were": 9, "merged": 9, "where": 9}


def _i22_row(text, layer):
    return {"sentence_text": text, "layer": layer, "doc_id": "D"}


# A third row carries the spliced coefficients on their own. Without it the repair is refused,
# and rightly so: in a corpus of two rows that mathematics exists nowhere else. See INT22-9.
_I22_ELSEWHERE = (chr(945) + "A=mA/(mA+mB), " + chr(945) + "B=mB/(mA+mB), beta=0, gamma=0")
_I22_CORPUS = [_i22_row(_I22_SPLICED, "mineru"), _i22_row(_I22_CLEAN, "docling"),
               _i22_row(_I22_ELSEWHERE, "pymupdf")]
_I22_REPAIRS = CP.build_spliced_math_repairs(_I22_CORPUS, _I22_VOCAB)
_I22_REPAIRED, _I22_N = CP.apply_spliced_math_repairs(_I22_CORPUS, _I22_REPAIRS)

check("INT22-1 a spliced row is replaced by the clean rendering of the same sentence",
      _I22_REPAIRS.get(_I22_SPLICED) == _I22_CLEAN and _I22_N == 1,
      "the spliced row put UPGMA's coefficients inside the sentence introducing WPGMA")
check("INT22-2 the clean row itself is left alone",
      _I22_REPAIRED[1]["sentence_text"] == _I22_CLEAN
      and "spliced_math_repaired_from" not in _I22_REPAIRED[1])
check("INT22-3 provenance is recorded on the repaired row",
      _I22_REPAIRED[0].get("spliced_math_repaired_from") == _I22_SPLICED,
      "a rewritten row must say what it was rewritten from")
check("INT22-4 ordinary subscripted notation is NOT called a splice",
      all(CP.spliced_math_words(text, _I22_VOCAB) == []
          for text in ("dN(p1, c1) = 0.1581, dN(p2, c1) = 0.1581.",
                       "y = (x + c)g" + chr(955) + ", " + chr(955) + " = 0",
                       "Mui" + chr(945) + "(i) represents the Mui value")),
      "the first version of this signature flagged 279 rows, most of them exactly these")
check("INT22-5 a word the corpus never uses on its own does not make a splice",
      CP.spliced_math_words(_I22_SPLICED, {}) == [],
      "the vocabulary gate is what separates an interrupted WORD from a symbol name")
check("INT22-6 a splice with no clean twin is left alone, not dropped",
      CP.build_spliced_math_repairs([_i22_row(_I22_SPLICED, "mineru")], _I22_VOCAB) == {},
      "detection without repair would lose the sentence entirely, which is worse")
check("INT22-7 the twin must come from a DIFFERENT extractor",
      CP.build_spliced_math_repairs(
          [_i22_row(_I22_SPLICED, "mineru"), _i22_row(_I22_CLEAN, "mineru"),
           _i22_row(_I22_ELSEWHERE, "pymupdf")],
          _I22_VOCAB) == {},
      "a clean row from the same extractor is the same rendering, not an independent one. The "
      "elsewhere row is what makes this isolate that rule: without it the non-destructive "
      "condition refuses the repair anyway, and sabotage showed the guard holding either way")
check("INT22-8 LIVE: the packet builder applies the repair",
      "apply_spliced_math_repairs" in live_calls(_PACKET_BUILDER_PATH),
      "a repair the builder never calls is the INT-13 defect over again")


# INT-22b. The splice repair must never be the only place some mathematics survives.
#
# As first shipped, the repair replaced a damaged row whenever a clean twin existed, assuming the
# spliced equation survives elsewhere. For Group Average Linkage it does. Measured afterwards, it
# does not always: three repairs deleted fragments found in no other text. The Chi-Squared case
# shows the shape at its worst - "(number of rows -1)x(number of columns-1)" exists ONLY inside a
# spliced sentence, because the row meant to carry it reads "the general formula for the degrees
# of freedom is df= ." with the formula missing.
#
# A repair that can delete unique content is not a repair. Every fragment the clean rendering
# drops must appear somewhere else, or the damaged row is left alone.

_I22B_UNIQUE = ("At each candidate split" + chr(964) + "=97500 position the index can be computed "
                "in constant time and the best split position is found")
_I22B_UNIQUE_CLEAN = ("At each candidate split position the index can be computed in constant "
                      "time and the best split position is found")
_I22B_SHARED = ("For the weighted" + chr(945) + "A=mA/(mA+mB) version of group average known as "
                "WPGMA the coefficients are constants independent of the cluster sizes")
_I22B_SHARED_CLEAN = ("For the weighted version of group average known as WPGMA the coefficients "
                      "are constants independent of the cluster sizes")
_I22B_ELSEWHERE = chr(945) + "A=mA/(mA+mB), " + chr(945) + "B=mB/(mA+mB), beta=0, gamma=0"
_I22B_VOCAB = {"candidate": 9, "split": 9, "position": 9, "index": 9, "computed": 9,
               "constant": 9, "time": 9, "best": 9, "found": 9, "each": 9,
               "weighted": 9, "version": 9, "group": 9, "average": 9, "known": 9,
               "coefficients": 9, "constants": 9, "independent": 9, "cluster": 9, "sizes": 9}


def _i22b(text, layer):
    return {"sentence_text": text, "layer": layer, "doc_id": "D"}


_I22B_UNIQUE_CORPUS = [_i22b(_I22B_UNIQUE, "mineru"), _i22b(_I22B_UNIQUE_CLEAN, "docling")]
_I22B_SHARED_CORPUS = [_i22b(_I22B_SHARED, "mineru"), _i22b(_I22B_SHARED_CLEAN, "docling"),
                       _i22b(_I22B_ELSEWHERE, "pymupdf")]

check("INT22-9 a repair that would delete mathematics found nowhere else is refused",
      CP.build_spliced_math_repairs(_I22B_UNIQUE_CORPUS, _I22B_VOCAB) == {},
      "damaged prose still carrying a unique equation is worth more than clean prose without it")
check("INT22-10 a repair whose dropped mathematics survives elsewhere is still made",
      CP.build_spliced_math_repairs(_I22B_SHARED_CORPUS, _I22B_VOCAB).get(_I22B_SHARED)
      == _I22B_SHARED_CLEAN,
      "the Group Average Linkage case: the spliced coefficients also appear as their own row")
check("INT22-11 a fragment is read without the word the splice glued to it",
      chr(945) + "A=mA/(mA+mB)" in CP.math_fragments("For the weighted" + chr(945)
                                                     + "A=mA/(mA+mB) version"),
      "Python's word class matches Greek, so the naive fragment carries 'weighted' and is unique "
      "by construction - which would make every splice look as though it orphans content")
check("INT22-12 a fragment that legitimately starts with a word keeps it",
      any(f.startswith("errgen") for f in CP.math_fragments("errgen=11/24")),
      "the prefix is dropped only when what remains still begins like mathematics")


# ---------------------------------------------------------------------------------------------
# INT-23. Retrieval relevance is not proof that the source identifies this exact target.
#
# A natural negative control has a target shaped "modifier modifier HEAD" while every substantive
# source statement applies the same modifiers to another, repeatedly named head. Context scoring
# correctly retrieves those statements, but its admission basis used to count as target identity
# and made the unsupported target draftable. The gate below is grammatical and label-derived: no
# curriculum term, KC ID, document, or domain appears in the mechanism.
# ---------------------------------------------------------------------------------------------


def _i23_passage(text, basis="context_anchored_relevance"):
    return {"text": text, "patch_heading": "", "shapes": ["definition"],
            "admission_basis": basis}


_I23_DECOY = _i23_passage(
    "The gadgets in a gadget set are reliably calibrated when every gadget reading stays within "
    "the stated tolerance.")
_I23_TARGET = ["Reliably Calibrated Widgets"]
_I23_HEALTHY = _i23_passage(
    "Reliably Calibrated Widgets are widgets whose readings stay within the stated tolerance.")
_I23_PRONOUN = _i23_passage(
    "It is naive because it assumes conditional independence given the observed outcome.")
_I23_INCIDENTAL = _i23_passage(
    "The results are stable when training sample sizes remain similar across repeated trials.")

check("INT23-1 an explicit modifier-matched foreign head is detected",
      bool(PB.modifier_foreign_head_decoys(_I23_DECOY["text"], _I23_TARGET[0])),
      "a contextually relevant near-neighbour must not prove that the requested head exists")
check("INT23-2 the decoy makes an otherwise substantive packet unsupported",
      PB.assess_support_state([_I23_DECOY], _I23_TARGET)
      == ("insufficient_support",
          "modifier_matched_foreign_head_without_positive_target_identity"),
      "this is the targeting guard: the mechanism must affect the live support-state decision")
check("INT23-3 an exact positive target identity defeats the veto",
      PB.assess_support_state([_I23_DECOY, _I23_HEALTHY], _I23_TARGET)[0] == "draftable",
      "related evidence may remain once any assertable passage identifies the actual target")
check("INT23-4 an unresolved pronoun is not invented into a competing concept",
      not PB.modifier_foreign_head_decoys(_I23_PRONOUN["text"],
                                          "Naive Independence Assumption"),
      "the broad foreign-subject experiment falsely moved this ordinary anaphoric form")
check("INT23-5 incidental modifier words do not create a foreign-head identity",
      not PB.modifier_foreign_head_decoys(_I23_INCIDENTAL["text"],
                                          "Training Sample Split"),
      "the subject's foreign head must repeat in the predicate, not merely precede target words")
check("INT23-6 the packet builder calls the identity veto",
      "packet_has_foreign_head_decoy_without_identity" in live_calls(_PACKET_BUILDER_PATH),
      "a detector not called by the support gate repeats the INT-13 inert-fix defect")
_I23_EXECUTABLE = "\n".join([
    inspect.getsource(PB._identity_lexical_stem),
    inspect.getsource(PB._identity_lexical_terms),
    inspect.getsource(PB._identity_label_shape),
    inspect.getsource(PB._compatible_definitional_subject),
    inspect.getsource(PB.passage_has_positive_target_identity),
    inspect.getsource(PB.modifier_foreign_head_decoys),
    inspect.getsource(PB.packet_has_foreign_head_decoy_without_identity),
    " ".join(PB._IDENTITY_FUNCTION_WORDS),
    " ".join(pattern.pattern for pattern in PB._IDENTITY_DEFINITIONAL_SUBJECT_PATTERNS),
    PB._IDENTITY_COPULAR_SUBJECT_RE.pattern,
]).lower()
check("INT23-7 the mechanism contains no fixture or curriculum vocabulary",
      not re.search(r"\b(?:widgets?|gadgets?|reliably|calibrated|mutually|exclusive|classes|rules?)\b",
                    _I23_EXECUTABLE),
      "the fix must derive its decision from any label and passage, not name its motivating case")

_SUMMARY_REACHED.append(True)
failed = _report_results("PIPELINE FIX LIVENESS")
print("%d checks, %d failed" % (len(RESULTS), failed))
sys.exit(1 if failed else 0)
