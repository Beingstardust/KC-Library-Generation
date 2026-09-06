"""Compatibility wrapper for shared sentence/name-matching semantic utilities.

Generic semantic.py logic is owned by kc_l.retrieval_windowing.semantic (the copy live
step5x candidate generation - evidence_stage_v3_candidate_bank.py/evidence_stage_v3_
scored_candidates.py - imports directly). This module exists only to preserve older
retrieval_gate import paths (drafting_input_overlay.py/step_06_6 and the retrieval_gate
package's own __init__.py) while both live call sites share one implementation instead
of two independently maintained, previously near-identical copies.

Deliberately does NOT re-export build_name_seed_terms: that function only ever existed
in the retrieval_windowing copy (never in this one), its own docstring already documents
it as "archived...for historical retrieval code" and warns the active runtime should not
reach it via this package, and its only apparent caller
(steps/step_06_4_2_semantic_safe_enrich/scripts/run_step6_4_2.py) is confirmed dead -
no SLURM launcher references it, and its own `from kc_l.retrieval_gate import
build_name_seed_terms` was already unresolvable before this change (retrieval_gate's
__init__.py never exposed it). Live-traced before writing this wrapper, per the audit's
own dead-code verification standard - not assumed from the docstring alone.

Phase 3.5's original deferral of this fork ("consumed only by orphaned/unwired Step
6.4-era callers") was accurate for build_name_seed_terms specifically, but wrong for the
rest of this module's surface - see Phase 4 Finding 2 / audit codebase-audit-20260805
item 14 for the live call-site trace that promoted this file back into scope.
"""

from __future__ import annotations

from kc_l.retrieval_windowing.semantic import (
    STOPWORDS,
    CandidateSentence,
    build_name_context_terms,
    build_query_text,
    collect_competitor_tokens,
    competitor_token_hit_count,
    derive_doc_group,
    derive_kc_group,
    ensure_string_list,
    exact_phrase_hits,
    match_normalize,
    normalize_ws,
    preferred_good_name_order,
    split_exact_sentences,
    split_sentences,
    tokenize,
    unique_preserve_order,
)

__all__ = [
    "STOPWORDS",
    "CandidateSentence",
    "build_name_context_terms",
    "build_query_text",
    "collect_competitor_tokens",
    "competitor_token_hit_count",
    "derive_doc_group",
    "derive_kc_group",
    "ensure_string_list",
    "exact_phrase_hits",
    "match_normalize",
    "normalize_ws",
    "preferred_good_name_order",
    "split_exact_sentences",
    "split_sentences",
    "tokenize",
    "unique_preserve_order",
]
