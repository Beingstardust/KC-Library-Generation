"""Structural policy for Step 5p retrieval-route terms.

Motivation, measured on the audited baseline run (963 primary route terms, 159 units):

    canonical variant (safe)   10.6%
    long verbatim span (>=8w)  18.9%
    long span (5-7w)           17.9%
    off-name phrase            17.8%
    bare single token          10.6%
    related phrase             24.3%

and 100 of 159 units had NO canonical-variant primary term at all, so their retrieval rested
entirely on model-invented surface forms. Two structural defects follow from that, and both are
observable without knowing anything about the subject matter:

  * A LONG VERBATIM SPAN copied out of a candidate sentence can only match the sentence it came
    from. It is a bookmark, not a retrieval term: it generalises to nothing, and it guarantees the
    drafting model is shown the one passage the profiler already looked at.
  * A BARE SINGLE TOKEN matches every sentence containing that word, so it imports unrelated
    content wholesale.

Policy, applied deterministically:

  1. ADD the unit's own canonical surface variants as primary terms when no active route already
     carries one. These are morphological variants of the unit's registry label, so they can only
     match text that actually mentions the unit - recall rises, false positives do not.
  2. WITHDRAW POSITIVE-SUPPORT AUTHORITY from routes whose primary terms are all structurally
     defective, by clearing can_create_positive_support. The route still matches and still
     contributes context and support signal; it simply can no longer make a candidate positive on
     its own.

No term is ever deleted, so no signal available before is lost. The policy reads only word
counts, token overlap against the unit's own canonical name, and the existing
deterministic_label_variants field. It contains no subject-matter vocabulary and is inert for a
profile whose routes are already well-formed.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

LONG_SPAN_WORD_THRESHOLD = 8
CANONICAL_ROUTE_ID = "canonical_surface_route"

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Structural/rhetorical words only - these describe how a label is phrased, never what field it
# belongs to. Kept aligned in spirit with profile_guidance._ROUTE_GENERIC_TOKENS.
_STOPWORDS: Set[str] = {
    "the", "of", "a", "an", "and", "or", "for", "in", "on", "to", "is", "are", "be", "been",
    "being", "with", "without", "by", "as", "it", "its", "that", "this", "these", "those",
    "from", "into", "within", "between", "among", "not", "no", "than", "then", "so", "such",
    "can", "may", "might", "must", "should", "would", "could", "also", "when", "where", "how",
    "what", "which", "there", "here", "using", "use", "used", "uses",
}


def content_tokens(text: Any) -> Set[str]:
    """Lowercase content tokens, stopwords and 1-2 char fragments removed."""
    return {
        t for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(str(text or "")))
        if t not in _STOPWORDS and len(t) > 2
    }


def _terms_from_deterministic_variants(profile: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for entry in (profile.get("deterministic_label_variants") or []):
        if isinstance(entry, Mapping):
            if entry.get("active") is False:
                continue
            term = str(entry.get("term") or "").strip()
        else:
            term = str(entry or "").strip()
        if term and term not in out:
            out.append(term)
    return out


def classify_route_term(term: str, canonical_tokens: Set[str], canonical_terms: Set[str]) -> str:
    """Structural class of a single route term. Domain-free by construction."""
    text = str(term or "").strip()
    if not text:
        return "empty"
    if text.lower() in canonical_terms:
        return "canonical_variant"
    tokens = content_tokens(text)
    if len(tokens) <= 1:
        return "bare_single_token"
    if len(text.split()) >= LONG_SPAN_WORD_THRESHOLD:
        return "long_verbatim_span"
    if canonical_tokens and not (tokens & canonical_tokens):
        return "off_name_phrase"
    return "related_phrase"


SAFE_CLASSES = {"canonical_variant", "related_phrase"}
DEFECTIVE_CLASSES = {"bare_single_token", "long_verbatim_span", "off_name_phrase"}


def apply_route_term_policy(profile: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (rewritten_profile, stats). Pure - the input mapping is not modified."""
    row: Dict[str, Any] = dict(profile)
    canonical_name = str(row.get("canonical_name") or "")
    canonical_tokens = content_tokens(canonical_name)

    canonical_terms_list = _terms_from_deterministic_variants(row)
    if canonical_name and canonical_name not in canonical_terms_list:
        canonical_terms_list.insert(0, canonical_name)
    canonical_terms = {t.lower() for t in canonical_terms_list}

    routes: List[Any] = list(row.get("retrieval_routes") or [])
    stats = {
        "unit": row.get("kc_id") or row.get("knowledge_unit_id"),
        "routes_in": len(routes),
        "primary_terms_in": 0,
        "class_counts": {},
        "routes_demoted": 0,
        "canonical_route_added": False,
    }

    has_canonical_primary = False
    new_routes: List[Any] = []
    for route in routes:
        if not isinstance(route, Mapping):
            new_routes.append(route)
            continue
        new_route = dict(route)
        primaries = [t for t in (new_route.get("primary_terms_any") or []) if isinstance(t, str)]
        stats["primary_terms_in"] += len(primaries)

        classes = [classify_route_term(t, canonical_tokens, canonical_terms) for t in primaries]
        for c in classes:
            stats["class_counts"][c] = stats["class_counts"].get(c, 0) + 1

        active = str(new_route.get("activation") or "active") == "active"
        if active and any(c == "canonical_variant" for c in classes):
            has_canonical_primary = True

        # Withdraw positive-support authority when EVERY primary is structurally defective.
        if primaries and all(c in DEFECTIVE_CLASSES for c in classes):
            if new_route.get("can_create_positive_support") is not False:
                new_route["can_create_positive_support"] = False
                new_route["route_term_policy"] = {
                    "action": "positive_support_withdrawn",
                    "reason": "all_primary_terms_structurally_defective",
                    "primary_term_classes": classes,
                }
                stats["routes_demoted"] += 1
        new_routes.append(new_route)

    # Guarantee at least one route whose primaries are the unit's own canonical surface forms.
    if canonical_terms_list and not has_canonical_primary:
        new_routes.insert(0, {
            "route_id": CANONICAL_ROUTE_ID,
            "route_type": "canonical_surface",
            "activation": "active",
            "route_strength": "strong",
            "verification_status": "registry_label_derived",
            "primary_terms_any": list(canonical_terms_list),
            "support_terms_any": [],
            "support_terms_all": [],
            "negative_terms_any": [],
            "local_window_scope": "same_sentence_or_patch",
            "support_requirement": "not_required",
            "can_create_candidates": True,
            "can_create_positive_support": True,
            "broad_context_only": False,
            "route_term_policy": {
                "action": "canonical_surface_route_added",
                "reason": "no_active_route_carried_a_canonical_variant_primary_term",
            },
        })
        stats["canonical_route_added"] = True

    row["retrieval_routes"] = new_routes
    row["route_term_policy_applied"] = True
    return row, stats
