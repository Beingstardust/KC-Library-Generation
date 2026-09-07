from __future__ import annotations

import re

from typing import Any, Dict, List, Mapping, Sequence

from .deterministic import normalize_text
from .structure_aware_profile import apply_structure_aware_profile


def _query_token_count(text: Any) -> int:
    cleaned = str(text or "").replace("-", " ").replace("_", " ")
    return len([tok for tok in cleaned.split() if tok.strip()])


def _query_role_and_flags(query: Mapping[str, Any]) -> tuple[str, List[str], List[str], bool, bool]:
    text = normalize_text(query.get("query"))
    source = str(query.get("source") or "")
    variant_type = str(query.get("variant_type") or "")
    cue_type = str(query.get("cue_type") or "")
    n_words = _query_token_count(text)

    flags: List[str] = []
    requires_hierarchy_guard = False

    if not text:
        return "reject_query", ["empty_query"], [], False, False

    if variant_type == "generic_suffix_stripped":
        flags.append("generic_suffix_stripped_broad_risk")
        requires_hierarchy_guard = True

    if source == "deterministic_label_variant" and variant_type in {"exact_label", "hyphen_space_normalized"}:
        role = "lexical_query"
        channels = ["lexical"]
    elif source == "deterministic_label_variant":
        role = "profile_only_query"
        channels = []
    elif source == "accepted_source_cue":
        if n_words <= 4:
            role = "lexical_query"
            channels = ["lexical", "phrase"]
        elif n_words <= 10:
            role = "phrase_query"
            channels = ["phrase", "semantic"]
        else:
            role = "semantic_query"
            channels = ["semantic"]
    elif source == "source_supported_near_target_cue":
        flags.append("source_supported_near_target_not_verbatim_source_observed")
        requires_hierarchy_guard = True
        if n_words <= 4:
            role = "lexical_query"
            channels = ["lexical", "phrase"]
        elif n_words <= 10:
            role = "phrase_query"
            channels = ["phrase", "semantic"]
        else:
            role = "semantic_query"
            channels = ["semantic"]
    elif source == "model_suggested_unverified":
        role = "profile_only_query"
        channels = []
        flags.append("model_suggested_unverified_requires_source_confirmation")
    else:
        role = "profile_only_query"
        channels = []
        flags.append("unknown_query_source")

    if n_words > 14:
        flags.append("long_query_semantic_only")
        if role not in {"profile_only_query", "reject_query"}:
            role = "semantic_query"
            channels = ["semantic"]

    if cue_type in {"mechanism_description", "process_phrase"} and n_words > 8:
        flags.append("mechanism_or_process_phrase_semantic_preferred")
        if role not in {"profile_only_query", "reject_query"}:
            role = "semantic_query"
            channels = ["semantic"]

    normalized_short_surface = text.lower().replace("-", " ").replace("_", " ")
    normalized_short_tokens = [tok for tok in normalized_short_surface.split() if tok]
    short_surface_is_metric_or_issue_like = (
        n_words <= 2
        and (
            cue_type in {"metric_relation", "formula_relation", "mechanism_description"}
            or any(
                tok in {
                    "frequency",
                    "measure",
                    "metric",
                    "score",
                    "index",
                    "rate",
                    "ratio",
                    "error",
                    "problem",
                    "issue",
                    "zero",
                }
                for tok in normalized_short_tokens
            )
        )
    )
    if short_surface_is_metric_or_issue_like:
        flags.append("short_surface_form_needs_hierarchy_guard")
        requires_hierarchy_guard = True

    if variant_type == "generic_suffix_stripped":
        role = "profile_only_query"
        channels = []

    step5x_eligible = role not in {"profile_only_query", "reject_query"}

    return role, sorted(set(flags)), sorted(set(channels)), step5x_eligible, requires_hierarchy_guard


def harden_query_variants(query_variants: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    hardened: List[Dict[str, Any]] = []

    for query in query_variants:
        if not isinstance(query, Mapping):
            continue

        role, flags, channels, step5x_eligible, requires_hierarchy_guard = _query_role_and_flags(query)
        if role == "reject_query":
            continue

        row = dict(query)
        row["retrieval_role"] = role
        row["retrieval_channels"] = channels
        row["risk_flags"] = flags
        row["step5x_eligible"] = bool(step5x_eligible)
        row["requires_hierarchy_guard"] = bool(requires_hierarchy_guard)
        row["profile_output_role"] = "retrieval_control_metadata_not_evidence"
        row["lexical_direct_use"] = bool(role in {"lexical_query", "phrase_query"} and "lexical" in channels)
        hardened.append(row)

    return hardened


def _provenance_semantic_key(provenance: Any) -> tuple[str, ...]:
    keys: List[str] = []
    if not isinstance(provenance, list):
        return tuple()
    for item in provenance:
        if not isinstance(item, Mapping):
            continue
        sid = normalize_text(item.get("snippet_id") or item.get("sentence_id") or item.get("source_id") or "")
        field = normalize_text(item.get("field_path") or "")
        quoted = normalize_text(item.get("quoted_text") or "")[:160].lower()
        key = "|".join([sid, field, quoted])
        if key.strip("|") and key not in keys:
            keys.append(key)
    return tuple(keys)


def _guidance_term_semantic_key(item: Mapping[str, Any]) -> tuple[str, str, str, tuple[str, ...]]:
    return (
        normalize_text(item.get("term") or item.get("query") or item.get("text")).lower(),
        normalize_text(item.get("cue_type") or item.get("variant_type") or item.get("retrieval_role")).lower(),
        normalize_text(item.get("validation_bucket") or item.get("equivalence_status") or item.get("source")).lower(),
        _provenance_semantic_key(item.get("provenance")),
    )


def harden_accepted_source_cues(cues: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    hardened: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()

    for cue in cues:
        if not isinstance(cue, Mapping):
            continue

        row = dict(cue)
        term = normalize_text(row.get("term"))
        if not term:
            continue
        row["term"] = term
        cue_type = str(row.get("cue_type") or "")
        n_words = _query_token_count(term)
        flags: List[str] = list(row.get("risk_flags") or [])

        provenance = _safe_provenance_items(row.get("provenance") or [])
        row["provenance"] = provenance
        if not provenance:
            flags.append("missing_provenance")

        if n_words > 18:
            flags.append("very_long_cue")

        if cue_type in {
            "source_observed_equivalent",
            "definition_phrase",
            "mechanism_description",
            "process_phrase",
            "formula_relation",
            "metric_relation",
            "context_phrase",
        }:
            row["cue_role"] = "retrieval_control_cue"
        else:
            row["cue_role"] = "review_needed_cue"
            flags.append("unknown_or_weak_cue_type")

        if n_words <= 4:
            row["recommended_retrieval_role"] = "lexical_query"
            row["recommended_retrieval_channels"] = ["lexical", "phrase"]
        elif n_words <= 10:
            row["recommended_retrieval_role"] = "phrase_query"
            row["recommended_retrieval_channels"] = ["phrase", "semantic"]
        else:
            row["recommended_retrieval_role"] = "semantic_query"
            row["recommended_retrieval_channels"] = ["semantic"]

        row["risk_flags"] = sorted(set(flags))
        row["profile_output_role"] = "retrieval_control_metadata_not_evidence"

        key = _guidance_term_semantic_key(row)
        if key in seen:
            continue
        seen.add(key)
        hardened.append(row)

    return hardened


def _shape_hint_from_raw(shape: str, *, source: str, provenance: Sequence[Mapping[str, Any]] | None = None) -> Dict[str, Any]:
    raw = normalize_text(shape)
    low = raw.lower()

    if "formula" in low or "metric" in low:
        family = "formula_or_metric"
    elif "definition" in low:
        family = "definition"
    elif "process" in low or "procedure" in low:
        family = "process"
    elif "mechanism" in low:
        family = "mechanism"
    elif "example" in low:
        family = "example"
    elif "contrast" in low or "sibling" in low:
        family = "contrast"
    else:
        family = "context"

    return {
        "shape": raw,
        "shape_family": family,
        "source": source,
        "confidence": "medium" if source in {"accepted_source_cue", "window_flags"} else "low",
        "provenance": list(provenance or []),
        "profile_output_role": "retrieval_control_metadata_not_evidence",
    }


def build_expected_evidence_shape_hints(
    raw_shapes: Sequence[str],
    accepted_cues: Sequence[Mapping[str, Any]],
    snippets: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for shape in raw_shapes:
        hint = _shape_hint_from_raw(str(shape), source="profile_shape")
        key = (hint["shape"].lower(), hint["source"])
        if hint["shape"] and key not in seen:
            seen.add(key)
            hints.append(hint)

    for cue in accepted_cues:
        cue_type = str(cue.get("cue_type") or "")
        if not cue_type:
            continue
        hint = _shape_hint_from_raw(cue_type, source="accepted_source_cue", provenance=cue.get("provenance") or [])
        key = (hint["shape"].lower(), hint["source"])
        if key not in seen:
            seen.add(key)
            hints.append(hint)

    for snip in snippets:
        for shape in snip.get("evidence_shapes") or []:
            hint = _shape_hint_from_raw(str(shape), source="window_flags")
            key = (hint["shape"].lower(), hint["source"])
            if hint["shape"] and key not in seen:
                seen.add(key)
                hints.append(hint)

    hints.sort(key=lambda h: (h.get("shape_family") or "", h.get("shape") or "", h.get("source") or ""))
    return hints


def summarize_profile_output_hardening(
    query_variants: Sequence[Mapping[str, Any]],
    accepted_cues: Sequence[Mapping[str, Any]],
    evidence_shape_hints: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    role_counts: Dict[str, int] = {}
    channel_counts: Dict[str, int] = {}
    risk_counts: Dict[str, int] = {}
    eligible_count = 0

    for query in query_variants:
        role = str(query.get("retrieval_role") or "missing")
        role_counts[role] = role_counts.get(role, 0) + 1

        if query.get("step5x_eligible") is True:
            eligible_count += 1

        for channel in query.get("retrieval_channels") or []:
            channel = str(channel)
            channel_counts[channel] = channel_counts.get(channel, 0) + 1

        for flag in query.get("risk_flags") or []:
            flag = str(flag)
            risk_counts[flag] = risk_counts.get(flag, 0) + 1

    cue_risk_counts: Dict[str, int] = {}
    for cue in accepted_cues:
        for flag in cue.get("risk_flags") or []:
            flag = str(flag)
            cue_risk_counts[flag] = cue_risk_counts.get(flag, 0) + 1

    return {
        "query_role_counts": dict(sorted(role_counts.items())),
        "query_channel_counts": dict(sorted(channel_counts.items())),
        "query_risk_counts": dict(sorted(risk_counts.items())),
        "accepted_cue_risk_counts": dict(sorted(cue_risk_counts.items())),
        "step5x_eligible_query_count": eligible_count,
        "expected_evidence_shape_hint_count": len(list(evidence_shape_hints)),
        "safe_to_wire_directly_into_step5x": False,
        "reason": "Step 5x must consume retrieval_role, retrieval_channels, risk_flags, and step5x_eligible rather than raw active=true query variants.",
    }




def _safe_provenance_items(raw_provenance: Sequence[Mapping[str, Any]] | None) -> List[Dict[str, Any]]:
    safe: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in raw_provenance or []:
        if not isinstance(raw, Mapping):
            continue

        snippet_id = normalize_text(raw.get("snippet_id") or raw.get("sentence_id") or raw.get("source_id") or "")
        field_path = normalize_text(raw.get("field_path") or "")
        source_id = normalize_text(raw.get("source_id") or raw.get("doc_id") or "")

        item: Dict[str, Any] = {}
        for key in (
            "snippet_id",
            "sentence_id",
            "source_id",
            "doc_id",
            "page_index",
            "patch_id",
            "field_path",
            "source",
            "validation_bucket",
        ):
            value = raw.get(key)
            if value not in (None, ""):
                item[key] = value

        if snippet_id and "snippet_id" not in item:
            item["snippet_id"] = snippet_id
        if field_path and "field_path" not in item:
            item["field_path"] = field_path

        key = (snippet_id, field_path, source_id)
        if not item or key in seen:
            continue
        seen.add(key)
        safe.append(item)

    return safe


def _registry_provenance_for_profile(profile: Mapping[str, Any]) -> List[Dict[str, Any]]:
    kc_id = normalize_text(profile.get("kc_id"))
    if not kc_id:
        return []
    return [{
        "source": "registry",
        "source_id": kc_id,
        "field_path": "canonical_name_or_alias",
    }]


def _dedupe_by_term_and_source(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in rows:
        if not isinstance(raw, Mapping):
            continue

        term = normalize_text(raw.get("term") or raw.get("query") or "")
        source = normalize_text(raw.get("source") or "")
        cue_type = normalize_text(raw.get("cue_type") or raw.get("variant_type") or "")
        if not term:
            continue

        key = (term.lower(), source.lower(), cue_type.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(raw))

    return out


def build_contract_active_query_terms(profile: Mapping[str, Any], queries: Sequence[Mapping[str, Any]], accepted: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for query in queries:
        if not isinstance(query, Mapping):
            continue

        source = normalize_text(query.get("source"))
        if source == "model_suggested_unverified":
            continue
        if query.get("active") is not True:
            continue
        if query.get("step5x_eligible") is not True:
            continue

        term = normalize_text(query.get("query"))
        if not term:
            continue

        provenance = _safe_provenance_items(query.get("provenance") or [])
        if not provenance and source == "deterministic_label_variant":
            provenance = _registry_provenance_for_profile(profile)

        rows.append({
            "term": term,
            "source": source or "unknown",
            "cue_type": normalize_text(query.get("cue_type") or query.get("variant_type") or ""),
            "retrieval_role": normalize_text(query.get("retrieval_role") or ""),
            "retrieval_channels": list(query.get("retrieval_channels") or []),
            "step5x_eligible": True,
            "requires_hierarchy_guard": bool(query.get("requires_hierarchy_guard")),
            "risk_flags": list(query.get("risk_flags") or []),
            "provenance": provenance,
            "profile_output_role": "retrieval_guidance_not_evidence",
            "step5x_verification_required": True,
        })

    if not rows:
        for cue in accepted:
            if not isinstance(cue, Mapping):
                continue
            term = normalize_text(cue.get("term"))
            if not term:
                continue
            provenance = _safe_provenance_items(cue.get("provenance") or [])
            if not provenance:
                continue
            rows.append({
                "term": term,
                "source": "accepted_source_cue",
                "cue_type": normalize_text(cue.get("cue_type") or ""),
                "retrieval_role": normalize_text(cue.get("recommended_retrieval_role") or ""),
                "retrieval_channels": list(cue.get("recommended_retrieval_channels") or []),
                "step5x_eligible": True,
                "requires_hierarchy_guard": False,
                "risk_flags": list(cue.get("risk_flags") or []),
                "provenance": provenance,
                "profile_output_role": "retrieval_guidance_not_evidence",
                "step5x_verification_required": True,
            })

    return _dedupe_by_term_and_source(rows)


def _source_cue_tokenize(text: Any) -> List[str]:
    cleaned = normalize_text(text).lower()
    return re.findall(r"[a-z0-9]+", cleaned)


def _source_cue_norm(text: Any) -> str:
    return " ".join(_source_cue_tokenize(text))


def _source_cue_label_tokens(profile: Mapping[str, Any]) -> List[str]:
    canonical = normalize_text(profile.get("canonical_name"))
    tokens = _source_cue_tokenize(canonical)
    stop = {
        "a", "an", "the", "of", "for", "to", "in", "on", "and", "or", "with", "by", "from",
        "using", "use", "used", "approach", "method", "methods", "model", "models", "algorithm",
        "algorithms", "concept", "definition", "phase", "process", "problem", "problems", "case",
        "cases", "type", "types", "value", "values", "data", "set", "sets",
    }
    informative = [tok for tok in tokens if tok not in stop and len(tok) > 1]
    return informative or [tok for tok in tokens if len(tok) > 1]


def _source_cue_acronym_variants(profile: Mapping[str, Any]) -> List[str]:
    canonical = normalize_text(profile.get("canonical_name"))
    variants: List[str] = []

    # Parenthetical text is only treated as an acronym/abbreviation when it
    # looks like one. This prevents ordinary disambiguating words such as
    # "(Node)" or "(Approach 1)" from becoming active retrieval cues.
    for inside in re.findall(r"\(([^)]+)\)", canonical):
        inside = normalize_text(inside)
        compact = re.sub(r"[^A-Za-z0-9]", "", inside)
        if (
            2 <= len(compact) <= 10
            and any(ch.isalpha() for ch in compact)
            and compact.upper() == compact
        ):
            variants.append(inside)

    words = [
        tok for tok in re.findall(r"[A-Za-z0-9]+", canonical)
        if tok.lower() not in {"of", "for", "to", "in", "on", "and", "or", "the", "a", "an"}
    ]
    if len(words) >= 3:
        acronym = "".join(word[0] for word in words if word)
        if 2 <= len(acronym) <= 8:
            variants.append(acronym)

    out: List[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.lower()
        if key not in seen:
            seen.add(key)
            out.append(variant)
    return out


def _source_cue_candidate_text(raw: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for key in ("text", "source_block_text", "patch_heading", "page_heading", "section_heading"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    return normalize_text(" ".join(parts))


def _source_cue_provenance(raw: Mapping[str, Any], *, quoted_text: str) -> List[Dict[str, Any]]:
    item: Dict[str, Any] = {}
    for key in ("snippet_id", "sentence_id", "source_id", "doc_id", "page_index", "patch_id", "block_id", "field_path"):
        value = raw.get(key)
        if value not in (None, ""):
            item[key] = value

    if quoted_text:
        item["quoted_text"] = quoted_text[:240]

    return [item] if item else []


def _source_cue_window_surfaces(audit: Mapping[str, Any]) -> List[tuple[str, Mapping[str, Any]]]:
    surfaces: List[tuple[str, Mapping[str, Any]]] = []
    for surface_name in ("strict_source_windows", "exploratory_profile_windows", "candidate_snippets", "profile_candidate_snippets"):
        rows = audit.get(surface_name) or []
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if isinstance(raw, Mapping):
                surfaces.append((surface_name, raw))
    return surfaces


def _source_cue_is_probably_reference_or_metadata(text: str) -> bool:
    low = normalize_text(text).lower()
    if not low or len(low) < 4:
        return True
    if low.count("[") + low.count("]") >= 4:
        return True
    if any(marker in low for marker in ("references", "bibliography", "proceedings", "doi:", "http://", "https://")):
        return True
    if re.search(r"\[[0-9,\s-]{1,20}\]", low) and len(low.split()) < 12:
        return True
    return False


def _source_cue_exact_substring(source_text: str, candidate_norm: str) -> str:
    if not candidate_norm:
        return ""
    source_tokens = _source_cue_tokenize(source_text)
    cand_tokens = candidate_norm.split()
    if not source_tokens or not cand_tokens or len(cand_tokens) > len(source_tokens):
        return ""

    for i in range(0, len(source_tokens) - len(cand_tokens) + 1):
        if source_tokens[i:i + len(cand_tokens)] == cand_tokens:
            return " ".join(source_tokens[i:i + len(cand_tokens)])
    return ""


def _source_cue_span_between_tokens(source_text: str, first_token: str, last_token: str, *, max_width: int) -> str:
    tokens = _source_cue_tokenize(source_text)
    if not tokens or not first_token or not last_token:
        return ""

    first_positions = [i for i, tok in enumerate(tokens) if tok == first_token]
    last_positions = [i for i, tok in enumerate(tokens) if tok == last_token]
    if not first_positions or not last_positions:
        return ""

    best: tuple[int, int] | None = None
    for i in first_positions:
        for j in last_positions:
            lo, hi = sorted((i, j))
            width = hi - lo + 1
            if width < 2 or width > max_width:
                continue
            if best is None or width < (best[1] - best[0] + 1):
                best = (lo, hi)

    if best is None:
        return ""

    lo, hi = best
    return " ".join(tokens[lo:hi + 1])


def _source_cue_sibling_collision(term: str, profile: Mapping[str, Any]) -> bool:
    term_norm = _source_cue_norm(term)
    if not term_norm:
        return True

    for sibling in profile.get("sibling_labels") or []:
        if _source_cue_norm(sibling) == term_norm:
            return True
    return False


def _source_observed_terms_from_windows(profile: Mapping[str, Any], audit: Mapping[str, Any]) -> List[Dict[str, Any]]:
    label_tokens = _source_cue_label_tokens(profile)
    canonical = normalize_text(profile.get("canonical_name"))
    canonical_norm = _source_cue_norm(canonical)
    no_paren_norm = _source_cue_norm(re.sub(r"\([^)]*\)", " ", canonical))
    acronym_variants = _source_cue_acronym_variants(profile)

    first_token = label_tokens[0] if label_tokens else ""
    last_token = label_tokens[-1] if label_tokens else ""
    span_max_width = max(len(label_tokens) + 2, 4)

    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for surface_name, raw in _source_cue_window_surfaces(audit):
        source_text = _source_cue_candidate_text(raw)
        if _source_cue_is_probably_reference_or_metadata(source_text):
            continue

        candidates: List[tuple[str, str, List[str]]] = []

        exact = _source_cue_exact_substring(source_text, canonical_norm)
        if exact:
            candidates.append((exact, "exact_canonical_phrase", []))

        if no_paren_norm and no_paren_norm != canonical_norm:
            no_paren = _source_cue_exact_substring(source_text, no_paren_norm)
            if no_paren:
                candidates.append((no_paren, "exact_parenthesis_stripped_phrase", []))

        source_norm = _source_cue_norm(source_text)
        for acronym in acronym_variants:
            acronym_norm = _source_cue_norm(acronym)
            if acronym_norm and re.search(rf"(^| )({re.escape(acronym_norm)})( |$)", source_norm):
                candidates.append((acronym, "exact_acronym_or_parenthetical_variant", []))

        # Partial first-last spans are deliberately stricter than exact phrase
        # matches. They are only retrieval guidance, never evidence, and they
        # must stay compact enough to avoid turning arbitrary surrounding prose
        # into query terms.
        if len(label_tokens) >= 3 and first_token and last_token:
            span = _source_cue_span_between_tokens(source_text, first_token, last_token, max_width=span_max_width)
            if span and span not in {canonical_norm, no_paren_norm}:
                candidates.append((
                    span,
                    "compact_first_last_label_token_source_span",
                    ["source_observed_partial_label_span_requires_step5x_verification"],
                ))

        for term, cue_type, risk_flags in candidates:
            term = normalize_text(term)
            if not term or len(term.split()) > 12 or _source_cue_sibling_collision(term, profile):
                continue

            # Single-token acronym cues must look like real acronyms. Ordinary
            # title words are already covered by exact phrase/label variants.
            if cue_type == "exact_acronym_or_parenthetical_variant":
                compact = re.sub(r"[^A-Za-z0-9]", "", term)
                if not compact or compact.upper() != compact:
                    continue

            provenance = _source_cue_provenance(raw, quoted_text=term)
            if not provenance:
                continue

            key = (term.lower(), str(provenance[0].get("snippet_id") or provenance[0].get("sentence_id") or ""))
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "term": term,
                "source": "source_observed_window_cue",
                "cue_type": cue_type,
                "equivalence_status": "source_observed_profile_window_step5x_must_verify",
                "provenance": provenance,
                "risk_flags": sorted(set([*risk_flags, "profile_window_guidance_not_evidence"])),
                "source_surface": surface_name,
                "profile_output_role": "retrieval_guidance_not_evidence",
                "step5x_verification_required": True,
                "step5x_eligible": True,
            })

    return _dedupe_by_term_and_source(rows)


def merge_source_equivalent_terms_into_active(active_terms: Sequence[Mapping[str, Any]], source_equiv: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = [dict(item) for item in active_terms if isinstance(item, Mapping)]
    seen: set[tuple[str, str]] = set()

    for item in rows:
        seen.add((normalize_text(item.get("term")).lower(), normalize_text(item.get("source")).lower()))

    for cue in source_equiv:
        if not isinstance(cue, Mapping):
            continue

        term = normalize_text(cue.get("term"))
        if not term:
            continue

        provenance = _safe_provenance_items(cue.get("provenance") or [])
        if not provenance:
            continue

        key = (term.lower(), "source_observed_window_cue")
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "term": term,
            "source": "source_observed_window_cue",
            "cue_type": normalize_text(cue.get("cue_type") or ""),
            "retrieval_role": "source_observed_profile_guided_query",
            "retrieval_channels": ["lexical", "phrase"],
            "step5x_eligible": True,
            "requires_hierarchy_guard": True,
            "risk_flags": sorted(set(list(cue.get("risk_flags") or []) + ["source_observed_profile_guidance_not_evidence"])),
            "provenance": provenance,
            "profile_output_role": "retrieval_guidance_not_evidence",
            "step5x_verification_required": True,
        })

    return _dedupe_by_term_and_source(rows)


def build_contract_source_equivalent_terms(profile: Mapping[str, Any], accepted: Sequence[Mapping[str, Any]], *, audit: Mapping[str, Any] | None = None, queries: Sequence[Mapping[str, Any]] | None = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for cue in accepted:
        if not isinstance(cue, Mapping):
            continue

        term = normalize_text(cue.get("term"))
        if not term:
            continue

        provenance = _safe_provenance_items(cue.get("provenance") or [])
        if not provenance:
            continue

        rows.append({
            "term": term,
            "source": "accepted_source_cue",
            "cue_type": normalize_text(cue.get("cue_type") or ""),
            "equivalence_status": "source_observed_or_source_supported",
            "provenance": provenance,
            "risk_flags": list(cue.get("risk_flags") or []),
            "profile_output_role": "retrieval_guidance_not_evidence",
            "step5x_verification_required": True,
            "step5x_eligible": True,
        })

    for cue in profile.get("source_supported_near_target_cues") or []:
        if not isinstance(cue, Mapping):
            continue

        term = normalize_text(cue.get("term"))
        if not term:
            continue

        provenance = _safe_provenance_items(cue.get("provenance") or [])
        if not provenance:
            continue

        rows.append({
            "term": term,
            "source": "source_supported_near_target_cue",
            "cue_type": normalize_text(cue.get("cue_type") or ""),
            "equivalence_status": "source_supported_near_target_step5x_must_verify",
            "provenance": provenance,
            "risk_flags": sorted(set([*list(cue.get("risk_flags") or []), "source_supported_near_target_requires_verification"])),
            "profile_output_role": "retrieval_guidance_not_evidence",
            "step5x_verification_required": True,
            "step5x_eligible": True,
        })

    if audit:
        rows.extend(_source_observed_terms_from_windows(profile, audit))

    return _dedupe_by_term_and_source(rows)


def build_contract_source_windows(profile: Mapping[str, Any], audit: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    lanes = [
        ("candidate_region", audit.get("strict_source_windows") or []),
        ("needs_expansion", audit.get("exploratory_profile_windows") or []),
    ]

    if not any(lane_rows for _, lane_rows in lanes):
        lanes = [("anchor_only", audit.get("candidate_snippets") or [])]

    for window_role, windows in lanes:
        for raw in windows:
            if not isinstance(raw, Mapping):
                continue

            snippet_id = normalize_text(raw.get("snippet_id") or raw.get("sentence_id") or raw.get("source_id") or "")
            doc_id = normalize_text(raw.get("doc_id") or "")
            patch_id = normalize_text(raw.get("patch_id") or raw.get("block_id") or "")
            sentence_id = normalize_text(raw.get("sentence_id") or "")
            key = (snippet_id, doc_id, patch_id, sentence_id)
            if key in seen:
                continue
            seen.add(key)

            item: Dict[str, Any] = {
                "window_role": window_role,
                "profile_output_role": "source_window_navigation_not_evidence",
                "step5x_verification_required": True,
            }

            for field in (
                "snippet_id",
                "sentence_id",
                "source_id",
                "doc_id",
                "page_index",
                "patch_id",
                "block_id",
                "patch_heading",
                "field_path",
                "match_type",
                "profile_window_role",
            ):
                value = raw.get(field)
                if value not in (None, ""):
                    item[field] = value

            risk_flags = list(raw.get("risk_flags") or raw.get("profile_window_risk_flags") or [])
            if risk_flags:
                item["risk_flags"] = sorted(set(str(x) for x in risk_flags if normalize_text(x)))

            flags: Dict[str, Any] = {}
            for field in (
                "is_formula_like",
                "is_definition_like",
                "is_procedure_like",
                "is_example_like",
                "is_heading_like",
            ):
                if field in raw:
                    flags[field] = bool(raw.get(field))
            if flags:
                item["source_flags"] = flags

            rows.append(item)

    return rows


def build_contract_negative_constraints(profile: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for raw in profile.get("quarantined_terms") or []:
        if not isinstance(raw, Mapping):
            continue
        term = normalize_text(raw.get("term"))
        if not term:
            continue
        rows.append({
            "term_or_pattern": term,
            "constraint_type": "quarantined_term",
            "reason": normalize_text(raw.get("reason") or raw.get("validation_bucket") or "quarantined"),
            "source": normalize_text(raw.get("source") or ""),
            "active": False,
            "profile_output_role": "retrieval_constraint_not_evidence",
        })

    for raw in profile.get("rejected_candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        term = normalize_text(raw.get("term"))
        if not term:
            continue
        rows.append({
            "term_or_pattern": term,
            "constraint_type": "rejected_candidate",
            "reason": normalize_text(raw.get("reason") or raw.get("validation_bucket") or "rejected"),
            "source": normalize_text(raw.get("source") or ""),
            "active": False,
            "profile_output_role": "retrieval_constraint_not_evidence",
        })

    sibling_labels = profile.get("sibling_labels") or []
    for sibling in sibling_labels:
        text = normalize_text(sibling)
        if not text:
            continue
        rows.append({
            "term_or_pattern": text,
            "constraint_type": "sibling_label",
            "reason": "sibling_collision_check",
            "active": False,
            "profile_output_role": "retrieval_constraint_not_evidence",
        })

    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("term_or_pattern") or "").lower(), str(row.get("constraint_type") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_contract_rescue_fields(profile: Mapping[str, Any], audit: Mapping[str, Any]) -> tuple[bool, List[str], str]:
    status = normalize_text(profile.get("profile_status"))
    active_count = len(profile.get("active_query_terms") or [])
    source_window_count = len(profile.get("source_windows") or [])
    accepted_count = len(profile.get("accepted_source_cues") or [])
    source_equiv_count = len(profile.get("source_equivalent_terms") or [])
    llm_recommended = bool(profile.get("llm_recommended"))
    profile_input_status = normalize_text(profile.get("profile_input_status"))

    reasons: List[str] = []

    if status in {"weak", "reject", "anchor_only", "likely_corpus_insufficient", "needs_rescue"}:
        reasons.append("profile_status_requires_review")
    if active_count == 0:
        reasons.append("no_active_query_terms")
    if source_equiv_count == 0 and accepted_count == 0:
        reasons.append("no_source_equivalent_terms")
    if source_window_count == 0:
        reasons.append("no_source_windows")
    if llm_recommended:
        reasons.append("deterministic_gate_recommends_llm_edge")
    if profile_input_status in {"exploratory_only", "topic_local_content_scout"}:
        reasons.append("only_weak_or_exploratory_windows")

    rescue_eligible = bool(reasons and status != "usable")
    if status == "reject" and source_window_count == 0 and active_count == 0:
        rescue_status = "likely_corpus_insufficient"
    elif rescue_eligible:
        rescue_status = "needs_rescue"
    elif status == "weak":
        rescue_status = "anchor_only" if source_window_count > 0 else "weak"
    else:
        rescue_status = status or "weak"

    return rescue_eligible, sorted(set(reasons)), rescue_status


def add_step5p_contract_fields(profile: Mapping[str, Any], *, accepted: Sequence[Mapping[str, Any]], queries: Sequence[Mapping[str, Any]], shape_hints: Sequence[Mapping[str, Any]], audit: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(profile)

    source_equiv = build_contract_source_equivalent_terms(out, accepted, audit=audit, queries=queries)
    active_terms = build_contract_active_query_terms(out, queries, accepted)
    active_terms = merge_source_equivalent_terms_into_active(active_terms, source_equiv)
    source_windows = build_contract_source_windows(out, audit)
    negative_constraints = build_contract_negative_constraints(out)

    out["active_query_terms"] = active_terms
    out["source_equivalent_terms"] = source_equiv
    out["expected_evidence_shape"] = list(shape_hints)
    out["source_windows"] = source_windows
    out["negative_constraints"] = negative_constraints

    rescue_eligible, rescue_reason, rescue_status = build_contract_rescue_fields(out, audit)
    out["rescue_eligible"] = bool(rescue_eligible)
    out["rescue_reason"] = rescue_reason
    out["profile_status_for_retrieval"] = rescue_status

    structure_profile = apply_structure_aware_profile(
        profile=out,
        audit=audit,
        source_windows=out["source_windows"],
        source_equivalent_terms=out["source_equivalent_terms"],
        active_query_terms=out["active_query_terms"],
        negative_constraints=out["negative_constraints"],
        expected_evidence_shape=out["expected_evidence_shape"],
    )

    out["source_windows"] = structure_profile["source_windows"]
    out["negative_constraints"] = structure_profile["negative_constraints"]
    out["expected_evidence_shape"] = structure_profile["expected_evidence_shape"]
    out["profile_status_for_retrieval"] = structure_profile["profile_status_for_retrieval"]
    out["rescue_eligible"] = bool(structure_profile["rescue_eligible"])
    out["rescue_reason"] = list(structure_profile["rescue_reason"])
    out["llm_edge_router"] = structure_profile["llm_edge_router"]

    out["provenance"] = {
        "profile_output_role": "profile_level_traceability_not_evidence",
        "active_query_term_count": len(out["active_query_terms"]),
        "source_equivalent_term_count": len(out["source_equivalent_terms"]),
        "source_window_count": len(out["source_windows"]),
        "accepted_source_cue_count": len(accepted),
        "query_variant_count": len(queries),
        "step5x_verification_required": True,
    }

    contract_audit = {
        "contract_fields_added": [
            "active_query_terms",
            "source_equivalent_terms",
            "expected_evidence_shape",
            "source_windows",
            "negative_constraints",
            "rescue_eligible",
            "rescue_reason",
            "profile_status_for_retrieval",
            "llm_edge_router",
            "provenance",
        ],
        "step5p_output_is_guidance_not_evidence": True,
        "step5x_remains_evidence_authority": True,
        "model_suggested_terms_active_count": sum(
            1 for item in out["active_query_terms"]
            if str(item.get("source") or "") == "model_suggested_unverified"
        ),
        "source_observed_window_cue_count": sum(
            1 for item in out["source_equivalent_terms"]
            if str(item.get("source") or "") == "source_observed_window_cue"
        ),
        "source_windows_text_stripped": True,
    }

    audit_out = dict(out.get("audit") or {})
    audit_out["step5p_contract_fields"] = contract_audit
    audit_out["structure_aware_profile"] = structure_profile["audit"]
    out["audit"] = audit_out

    return out

def harden_profile_output(profile: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(profile)
    audit = dict(out.get("audit") or {})

    accepted = harden_accepted_source_cues(out.get("accepted_source_cues") or [])
    queries = harden_query_variants(out.get("query_variants") or [])

    snippets: List[Mapping[str, Any]] = []
    snippets.extend(audit.get("strict_source_windows") or [])
    snippets.extend(audit.get("exploratory_profile_windows") or [])
    if not snippets:
        snippets.extend(audit.get("candidate_snippets") or [])

    shape_hints = build_expected_evidence_shape_hints(
        out.get("expected_evidence_shapes") or [],
        accepted,
        snippets,
    )

    out["accepted_source_cues"] = accepted
    out["query_variants"] = queries
    out["expected_evidence_shape_hints"] = shape_hints
    if "validated_guidance_buckets" in out and not isinstance(out.get("validated_guidance_buckets"), dict):
        out["validated_guidance_buckets"] = {}

    out = add_step5p_contract_fields(
        out,
        accepted=accepted,
        queries=queries,
        shape_hints=shape_hints,
        audit=audit,
    )
    audit = dict(out.get("audit") or {})

    audit["profile_output_hardening"] = summarize_profile_output_hardening(
        queries,
        accepted,
        shape_hints,
    )
    out["audit"] = audit

    return out
