from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from .schema import field_path_is_allowed

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "their", "this",
    "to", "was", "were", "when", "where", "which", "with",
}

GENERIC_SUFFIX_TOKENS = {
    "definition", "problem", "phase", "method", "methods", "approach", "approaches",
    "algorithm", "algorithms", "concept", "concepts", "overview", "measure",
    "measures", "metric", "metrics", "index", "indices", "score", "scores",
    "test", "tests", "model", "models", "process", "procedure", "procedures",
    "technique", "techniques", "criterion", "criteria",
}

PREPROFILE_DESCRIPTOR_TOKENS = GENERIC_SUFFIX_TOKENS | {
    "boundary", "boundaries", "condition", "conditions", "equation", "equations",
    "function", "functions", "objective", "objectives", "parameter", "parameters",
    "relation", "relations", "relationship", "relationships", "stage", "stages",
    "step", "steps", "term", "terms",
}

UNSAFE_TEXT_MARKERS = {
    "references",
    "bibliography",
    "doi:",
    "isbn",
    "retrieved from",
    "http://",
    "https://",
}

DEFINITION_CUE = re.compile(
    r"\b(is|are|means|refers to|defined as|called|known as|denotes|represents|measures|computed as|calculated as)\b",
    re.I,
)
PROCESS_CUE = re.compile(
    r"\b(step|stage|phase|process|procedure|first|next|then|finally|learn|train|estimate|fit|classify|predict)\b",
    re.I,
)
FORMULA_CUE = re.compile(r"[$\\{}_^=<>≤≥∑Σ]|\b(eq\.|equation|formula|ratio|rate|score)\b", re.I)
PROBLEM_CUE = re.compile(r"\b(problem|issue|case|cases|happen|never observed|zero|undefined|fails|failure)\b", re.I)
SCOPE_CUE = re.compile(r"\b(used to|used for|helps|allows|evaluates|measures|compares|select|classify|predict|estimate|under|when|if)\b", re.I)

WORD_RE = re.compile(r"[A-Za-z0-9]+")
GENERIC_METADATA_EDGE_REASONS = {
    "missing_topic_path_terms",
    "missing_sibling_terms",
    "missing_descriptor_terms",
    "limited_surface_forms",
    "derived_initialism_needs_source_confirmation",
    "few_active_deterministic_routes",
    "surface_form_under_specified",
}


def normalize_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_key(text: Any) -> str:
    return normalize_text(text).lower()


def tokenize(text: Any) -> List[str]:
    return [t.lower() for t in WORD_RE.findall(str(text or "")) if len(t) >= 2]


def phrase_tokens(text: Any) -> List[str]:
    """Tokenize without dropping one-character tokens.

    This preserves single-character leading tokens in compact metric-like labels.
    """
    return [t.lower() for t in WORD_RE.findall(str(text or "")) if t]


def phrase_present(term: Any, text: Any) -> bool:
    """Return True only when term appears as a token-boundary phrase.

    This prevents unsafe substring matches such as QP matching QPP.
    """
    tt = phrase_tokens(term)
    xt = phrase_tokens(text)
    if not tt or not xt or len(tt) > len(xt):
        return False
    n = len(tt)
    for i in range(0, len(xt) - n + 1):
        if xt[i:i+n] == tt:
            return True
    return False


def content_tokens(text: Any, dynamic_broad_tokens: Set[str] | None = None) -> List[str]:
    broad = dynamic_broad_tokens or set()
    out = []
    for tok in tokenize(text):
        if tok in STOPWORDS:
            continue
        if tok in GENERIC_SUFFIX_TOKENS:
            continue
        if tok in broad:
            continue
        if len(tok) < 3:
            continue
        out.append(tok)
    return out


def dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        cleaned = normalize_text(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def acronym_for(text: str) -> str:
    words = [w for w in WORD_RE.findall(text) if w and w[0].isalpha()]
    if len(words) < 2:
        return ""
    ac = "".join(w[0].upper() for w in words)
    return ac if 2 <= len(ac) <= 8 else ""


def strip_parentheses(text: str) -> Tuple[str, List[str]]:
    inside = re.findall(r"\(([^)]{2,80})\)", text)
    stripped = normalize_text(re.sub(r"\([^)]*\)", " ", text))
    return stripped, [normalize_text(x) for x in inside if normalize_text(x)]


def deterministic_label_variants(canonical_name: str, aliases: Sequence[str] | None = None) -> List[Dict[str, Any]]:
    raw_terms = [canonical_name] + list(aliases or [])
    variants: List[Dict[str, Any]] = []

    def add(term: str, variant_type: str, source: str) -> None:
        term = normalize_text(term)
        if not term:
            return
        variants.append({
            "term": term,
            "variant_type": variant_type,
            "source": source,
            "active": True,
        })

    for raw in raw_terms:
        raw = normalize_text(raw)
        if not raw:
            continue

        add(raw, "exact_label", "canonical_or_alias")
        add(raw.replace("-", " "), "hyphen_space_normalized", "canonical_or_alias")
        add(raw.replace("/", " "), "slash_space_normalized", "canonical_or_alias")

        stripped, inside_terms = strip_parentheses(raw)
        if stripped and stripped.lower() != raw.lower():
            add(stripped, "parenthetical_removed", "canonical_or_alias")
        for inside in inside_terms:
            add(inside, "parenthetical_inside", "canonical_or_alias")

        # Do not auto-generate acronyms from labels.
        # Acronyms such as LP, QP, and BT are collision-prone and must be
        # source-observed or explicitly supplied as aliases before use.
        toks = tokenize(raw)
        if len(toks) >= 2 and toks[-1] in GENERIC_SUFFIX_TOKENS:
            head = " ".join(toks[:-1])
            if head and len(content_tokens(head)) >= 2:
                add(head, "generic_suffix_stripped", "canonical_or_alias")

        content = content_tokens(raw)
        if 2 <= len(content) <= 5:
            add(" ".join(content), "content_token_head", "canonical_or_alias")

    seen = set()
    out = []
    for v in variants:
        key = v["term"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def descriptor_terms_for_label(label: str) -> List[str]:
    return dedupe_keep_order(
        tok for tok in tokenize(label)
        if tok in PREPROFILE_DESCRIPTOR_TOKENS
    )


def derived_initialism_variants(canonical_name: str, aliases: Sequence[str] | None = None) -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in [canonical_name, *(aliases or [])]:
        text = normalize_text(raw)
        if not text:
            continue
        initialism = acronym_for(text)
        key = initialism.lower()
        if not initialism or key in seen:
            continue
        seen.add(key)
        variants.append({
            "term": initialism,
            "variant_type": "derived_initialism_profile_only",
            "source": "deterministic_preprofile",
            "active": False,
            "risk_flags": ["collision_prone_initialism_profile_only"],
        })
    return variants


def _concept_head_from_label(canonical_name: str, descriptor_terms: Sequence[str]) -> str:
    tokens = WORD_RE.findall(normalize_text(canonical_name))
    if not tokens:
        return normalize_text(canonical_name)
    lowered = [tok.lower() for tok in tokens]
    if lowered and lowered[-1] in descriptor_terms and len(tokens) >= 2:
        return normalize_text(" ".join(tokens[:-1]))
    return normalize_text(canonical_name)


def _deterministic_query_routes(
    variants: Sequence[Mapping[str, Any]],
    derived_initialisms: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    routes: List[Dict[str, Any]] = []

    def add_route(
        *,
        term: str,
        variant_type: str,
        activation: str,
        retrieval_role: str,
        risk_flags: Sequence[str],
    ) -> None:
        if not term:
            return
        routes.append({
            "route_id": f"deterministic_{len(routes) + 1:03d}",
            "query": term,
            "variant_type": variant_type,
            "source": "deterministic_preprofile",
            "activation": activation,
            "retrieval_role": retrieval_role,
            "risk_flags": list(risk_flags),
            "profile_output_role": "retrieval_control_metadata_not_evidence",
        })

    for item in variants:
        term = normalize_text(item.get("term"))
        variant_type = normalize_text(item.get("variant_type"))
        if not term:
            continue
        if variant_type in {"exact_label", "hyphen_space_normalized"}:
            add_route(
                term=term,
                variant_type=variant_type,
                activation="active",
                retrieval_role="lexical_query",
                risk_flags=[],
            )
        elif variant_type == "content_token_head":
            add_route(
                term=term,
                variant_type=variant_type,
                activation="profile_only",
                retrieval_role="profile_only_query",
                risk_flags=["content_head_requires_source_confirmation"],
            )
        elif variant_type == "generic_suffix_stripped":
            add_route(
                term=term,
                variant_type=variant_type,
                activation="profile_only",
                retrieval_role="profile_only_query",
                risk_flags=["generic_suffix_stripped_broad_risk"],
            )

    for item in derived_initialisms:
        add_route(
            term=normalize_text(item.get("term")),
            variant_type=normalize_text(item.get("variant_type")),
            activation="profile_only",
            retrieval_role="profile_only_query",
            risk_flags=[str(flag) for flag in item.get("risk_flags") or []],
        )

    return routes


def build_deterministic_preprofile(
    *,
    canonical_name: str,
    aliases: Sequence[str] | None = None,
    topic_path_labels: Sequence[str] | None = None,
    sibling_labels: Sequence[str] | None = None,
    deterministic_variants: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    aliases = [normalize_text(item) for item in aliases or [] if normalize_text(item)]
    variants = list(deterministic_variants or deterministic_label_variants(canonical_name, aliases))
    descriptor_terms = descriptor_terms_for_label(canonical_name)
    initialisms = derived_initialism_variants(canonical_name, aliases)
    topic_terms = dedupe_keep_order(item for item in topic_path_labels or [] if normalize_text(item))
    sibling_terms = dedupe_keep_order(item for item in sibling_labels or [] if normalize_text(item))
    surface_forms = dedupe_keep_order(normalize_text(item.get("term")) for item in variants if normalize_text(item.get("term")))
    punctuation_variants = [
        dict(item)
        for item in variants
        if normalize_text(item.get("variant_type")) and normalize_text(item.get("variant_type")) != "exact_label"
    ]
    shape_priors = infer_expected_evidence_shapes(canonical_name, variants)
    return {
        "canonical_name": normalize_text(canonical_name),
        "concept_head": _concept_head_from_label(canonical_name, descriptor_terms),
        "deterministic_surface_forms": surface_forms,
        "morphology_and_punctuation_variants": punctuation_variants,
        "derived_initialism_variants": initialisms,
        "descriptor_terms": descriptor_terms,
        "topic_path_terms": topic_terms,
        "sibling_terms": sibling_terms,
        "evidence_shape_priors": shape_priors,
        "deterministic_query_routes": _deterministic_query_routes(variants, initialisms),
    }


def assess_deterministic_preprofile(
    preprofile: Mapping[str, Any],
    *,
    strict_source_window_count: int,
    exploratory_profile_window_count: int,
) -> Dict[str, Any]:
    surface_forms = list(preprofile.get("deterministic_surface_forms") or [])
    descriptor_terms = list(preprofile.get("descriptor_terms") or [])
    topic_terms = list(preprofile.get("topic_path_terms") or [])
    sibling_terms = list(preprofile.get("sibling_terms") or [])
    shape_priors = list(preprofile.get("evidence_shape_priors") or [])
    query_routes = list(preprofile.get("deterministic_query_routes") or [])
    initialisms = list(preprofile.get("derived_initialism_variants") or [])

    score = 0.18
    edge_trigger_reasons: List[str] = []
    evidence_weakness_signals: List[str] = []
    llm_permission_reasons: List[str] = []
    llm_gate_blockers: List[str] = []

    active_route_count = sum(1 for item in query_routes if str(item.get("activation") or "") == "active")

    if len(surface_forms) >= 3:
        score += 0.16
    else:
        edge_trigger_reasons.append("limited_surface_forms")
        evidence_weakness_signals.append("limited_surface_forms")

    if descriptor_terms:
        score += 0.08
    else:
        edge_trigger_reasons.append("missing_descriptor_terms")
        evidence_weakness_signals.append("missing_descriptor_terms")

    if topic_terms:
        score += 0.08
    else:
        edge_trigger_reasons.append("missing_topic_path_terms")
        evidence_weakness_signals.append("missing_topic_path_terms")

    if sibling_terms:
        score += 0.08
    else:
        edge_trigger_reasons.append("missing_sibling_terms")
        evidence_weakness_signals.append("missing_sibling_terms")

    if len(shape_priors) >= 2:
        score += 0.08

    if active_route_count >= 2:
        score += 0.12
    else:
        edge_trigger_reasons.append("few_active_deterministic_routes")
        evidence_weakness_signals.append("few_active_deterministic_routes")

    if strict_source_window_count >= 2:
        score += 0.22
    elif strict_source_window_count == 1:
        score += 0.16
        evidence_weakness_signals.append("single_strict_source_window")
    elif exploratory_profile_window_count >= 6:
        score += 0.09
        edge_trigger_reasons.append("exploratory_only_windows")
        evidence_weakness_signals.append("exploratory_only_windows")
    elif exploratory_profile_window_count > 0:
        score += 0.04
        edge_trigger_reasons.append("sparse_window_support")
        evidence_weakness_signals.append("sparse_window_support")
    else:
        edge_trigger_reasons.append("no_profile_windows")
        evidence_weakness_signals.append("no_profile_windows")

    if initialisms:
        edge_trigger_reasons.append("derived_initialism_needs_source_confirmation")
        evidence_weakness_signals.append("derived_initialism_needs_source_confirmation")

    if len(surface_forms) <= 1:
        edge_trigger_reasons.append("surface_form_under_specified")
        evidence_weakness_signals.append("surface_form_under_specified")

    score = max(0.0, min(1.0, round(score, 6)))
    if score >= 0.7:
        band = "strong"
    elif score >= 0.45:
        band = "medium"
    else:
        band = "weak"

    has_formula_or_procedure_shape = any(
        shape in {
            "formula_relation",
            "metric_relation",
            "process_phrase",
            "mechanism_description",
        }
        for shape in shape_priors
    )

    has_sibling_disambiguation_pressure = bool(
        sibling_terms and len(surface_forms) <= 3 and active_route_count <= 2
    )

    has_sparse_source_bound_ambiguity = bool(
        strict_source_window_count == 1
        or (band == "weak" and strict_source_window_count > 0 and active_route_count <= 1)
    )

    has_exploratory_edge_need = bool(
        strict_source_window_count <= 0
        and exploratory_profile_window_count > 0
        and band != "strong"
        and (
            exploratory_profile_window_count >= 4
            or has_formula_or_procedure_shape
            or has_sibling_disambiguation_pressure
            or bool(initialisms)
            or len(surface_forms) <= 2
        )
    )

    if strict_source_window_count <= 0 and exploratory_profile_window_count <= 0:
        llm_gate_status = "source_absent_no_llm"
        llm_gate_blockers.extend(["no_profile_windows", "no_source_bound_windows"])

    elif has_exploratory_edge_need:
        llm_gate_status = "exploratory_edge_llm_allowed"
        llm_permission_reasons.append("source_windows_available_but_deterministic_profile_weak")
        if exploratory_profile_window_count >= 4:
            llm_permission_reasons.append("exploratory_source_windows_need_semantic_profile_recovery")
        if has_formula_or_procedure_shape:
            llm_permission_reasons.append("shape_interpretation_needed")
        if has_sibling_disambiguation_pressure:
            llm_permission_reasons.append("sibling_or_branch_disambiguation_needed")
        if initialisms:
            llm_permission_reasons.append("derived_initialism_needs_source_confirmation")

    elif strict_source_window_count <= 0:
        llm_gate_status = "exploratory_sparse_no_llm"
        llm_gate_blockers.extend(["insufficient_exploratory_window_support", "no_strict_source_windows"])

    elif has_sibling_disambiguation_pressure and band != "strong":
        llm_gate_status = "sibling_disambiguation_only"
        llm_permission_reasons.append("source_bound_sibling_disambiguation_pressure")

    elif has_formula_or_procedure_shape and band != "strong":
        llm_gate_status = "formula_or_procedure_interpretation_allowed"
        llm_permission_reasons.append("source_bound_formula_or_procedure_interpretation")

    elif has_sparse_source_bound_ambiguity:
        llm_gate_status = "semantic_ambiguous_llm_allowed"
        llm_permission_reasons.append("source_bound_semantic_ambiguity")
        if strict_source_window_count == 1:
            llm_permission_reasons.append("single_strict_source_window")

    else:
        llm_gate_status = "deterministic_only"

    llm_recommended = bool(llm_permission_reasons and not llm_gate_blockers)

    return {
        "deterministic_profile_strength": score,
        "deterministic_profile_strength_band": band,
        "edge_trigger_reasons": dedupe_keep_order(edge_trigger_reasons),
        "evidence_weakness_signals": dedupe_keep_order(evidence_weakness_signals),
        "llm_permission_reasons": dedupe_keep_order(llm_permission_reasons),
        "llm_gate_blockers": dedupe_keep_order(llm_gate_blockers),
        "llm_gate_status": llm_gate_status,
        "llm_recommended": llm_recommended,
    }


def infer_expected_evidence_shapes(canonical_name: str, variants: Sequence[Mapping[str, Any]]) -> List[str]:
    text = " ".join([canonical_name] + [str(v.get("term") or "") for v in variants]).lower()
    shapes = set()

    if any(x in text for x in ["formula", "ratio", "rate", "measure", "metric", "score", "coefficient", "index"]):
        shapes.add("formula_relation")
        shapes.add("metric_relation")

    if any(x in text for x in ["phase", "stage", "process", "algorithm", "procedure"]):
        shapes.add("process_phrase")

    if any(x in text for x in ["problem", "issue", "error", "zero", "missing"]):
        shapes.add("mechanism_description")

    if any(x in text for x in ["definition", "concept"]):
        shapes.add("definition_phrase")

    if not shapes:
        shapes.add("context_phrase")

    return sorted(shapes)


def allowed_text_from_row(row: Mapping[str, Any]) -> Tuple[str, str, bool]:
    fields = [
        ("text", "text"),
        ("sentence_text", "sentence_text"),
        ("quote_surface", "quote_surface"),
        ("original_quote_surface", "original_quote_surface"),
        ("source_block_text", "source_block_text"),
        ("original_source_block_text", "original_source_block_text"),
        ("patch_heading", "patch_heading"),
        ("page_heading_norm", "page_heading_norm"),
        ("original_patch_heading", "original_patch_heading"),
        ("heading", "heading"),
        ("section_title", "section_title"),
    ]

    parts = []
    used = []
    primary_evidence_used = False
    primary_evidence_fields = {
        "text",
        "sentence_text",
        "quote_surface",
        "original_quote_surface",
        "source_block_text",
        "original_source_block_text",
    }
    for key, field_path in fields:
        value = row.get(key)
        if isinstance(value, str) and value.strip() and field_path_is_allowed(field_path):
            parts.append(value)
            used.append(field_path)
            if key in primary_evidence_fields:
                primary_evidence_used = True

    return normalize_text(" ".join(parts)), ",".join(used), primary_evidence_used


def snippet_id_for_row(row: Mapping[str, Any], fallback_index: int) -> str:
    for key in ["snippet_id", "sentence_id", "overlay_candidate_id", "candidate_id", "patch_id", "block_id"]:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = normalize_text(row)
    return "snippet:" + hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def doc_page_for_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": row.get("doc_id") or row.get("source_doc_id") or row.get("document_id") or "",
        "page_index": row.get("page_index") if row.get("page_index") is not None else row.get("page"),
        "patch_id": row.get("patch_id") or "",
        "block_id": row.get("block_id") or "",
    }


def row_is_unsafe(
    row: Mapping[str, Any],
    text: str,
    field_path: str,
    has_primary_evidence: bool,
) -> Tuple[bool, str]:
    low_text = normalize_key(text)
    low_field = normalize_key(field_path)

    if not text:
        return True, "empty_text"

    if row.get("is_meta") is True:
        return True, "step45_meta_flag"

    if row.get("is_nav_boilerplate") is True:
        return True, "step45_nav_boilerplate_flag"

    if row.get("is_author_affiliation") is True:
        return True, "step45_author_affiliation_flag"

    if not has_primary_evidence:
        return True, "structural_only_text"

    if not field_path_is_allowed(low_field):
        return True, "unsafe_field_path"

    if any(marker in low_text[:300] for marker in UNSAFE_TEXT_MARKERS):
        return True, "reference_or_metadata_like_text"

    if len(text) < 20:
        return True, "too_short"

    return False, ""


def evidence_shape_for_text(text: str) -> List[str]:
    shapes = set()
    if DEFINITION_CUE.search(text):
        shapes.add("definition_phrase")
    if PROCESS_CUE.search(text):
        shapes.add("process_phrase")
    if FORMULA_CUE.search(text):
        shapes.add("formula_relation")
    if PROBLEM_CUE.search(text):
        shapes.add("mechanism_description")
    if SCOPE_CUE.search(text):
        shapes.add("context_phrase")
    return sorted(shapes) or ["context_phrase"]


def branch_tokens(topic_path_labels: Sequence[str] | None, dynamic_broad_tokens: Set[str] | None = None) -> List[str]:
    toks: List[str] = []
    for label in topic_path_labels or []:
        toks.extend(content_tokens(label, dynamic_broad_tokens=dynamic_broad_tokens))
    return dedupe_keep_order(toks)


def sibling_labels_for(kc_row: Mapping[str, Any], all_rows: Sequence[Mapping[str, Any]]) -> List[str]:
    explicit = kc_row.get("sibling_labels") or []
    if isinstance(explicit, list):
        cleaned = [str(x).strip() for x in explicit if str(x).strip()]
        if cleaned:
            return dedupe_keep_order(cleaned)

    parent = (
        kc_row.get("parent_topic_id")
        or kc_row.get("parent_id")
        or kc_row.get("parent_node_id")
        or kc_row.get("parent_topic_label")
    )
    if not parent:
        return []

    labels = []
    this_kc = str(kc_row.get("kc_id") or "")
    for row in all_rows:
        if str(row.get("kc_id") or "") == this_kc:
            continue
        other_parent = (
            row.get("parent_topic_id")
            or row.get("parent_id")
            or row.get("parent_node_id")
            or row.get("parent_topic_label")
        )
        if other_parent == parent:
            name = row.get("canonical_name") or row.get("label") or row.get("name")
            if isinstance(name, str) and name.strip():
                labels.append(name.strip())
    return dedupe_keep_order(labels)


def build_dynamic_broad_tokens(kc_rows: Sequence[Mapping[str, Any]], min_df: int = 12) -> Set[str]:
    from collections import Counter

    df = Counter()
    for row in kc_rows:
        name = row.get("canonical_name") or row.get("label") or row.get("name") or ""
        aliases = row.get("aliases") or []
        text = " ".join([str(name)] + [str(a) for a in aliases if isinstance(a, str)])
        df.update(set(tokenize(text)))

    return {tok for tok, count in df.items() if count >= min_df}


def score_snippet_for_kc(
    text: str,
    variants: Sequence[Mapping[str, Any]],
    topic_path_labels: Sequence[str],
    sibling_labels: Sequence[str],
    dynamic_broad_tokens: Set[str] | None = None,
) -> Dict[str, Any]:
    low = normalize_key(text)
    text_tokens = set(content_tokens(text, dynamic_broad_tokens=dynamic_broad_tokens))

    exact_terms = []
    stripped_terms = []
    for variant in variants:
        term = str(variant.get("term") or "")
        if not term:
            continue
        if phrase_present(term, text):
            exact_terms.append(term)
        elif variant.get("variant_type") in {"generic_suffix_stripped", "content_token_head"}:
            vtoks = content_tokens(term, dynamic_broad_tokens=dynamic_broad_tokens)
            if len(vtoks) >= 2 and set(vtoks).issubset(text_tokens):
                stripped_terms.append(term)

    label_tokens = set()
    for variant in variants:
        label_tokens.update(content_tokens(variant.get("term") or "", dynamic_broad_tokens=dynamic_broad_tokens))

    target_overlap = sorted(label_tokens & text_tokens)
    b_tokens = set(branch_tokens(topic_path_labels, dynamic_broad_tokens=dynamic_broad_tokens))
    branch_overlap = sorted(b_tokens & text_tokens)

    sibling_hits = []
    for sib in sibling_labels:
        sib_low = sib.lower()
        if sib_low and sib_low in low:
            sibling_hits.append(sib)

    shapes = evidence_shape_for_text(text)

    score = 0.0
    reasons = []

    if exact_terms:
        score += 8.0
        reasons.append("exact_or_variant_surface_hit")

    if stripped_terms:
        score += 5.0
        reasons.append("stripped_head_or_content_token_hit")

    if target_overlap:
        score += min(5.0, 1.25 * len(target_overlap))
        reasons.append("target_token_overlap")

    if branch_overlap:
        score += min(3.0, 0.75 * len(branch_overlap))
        reasons.append("branch_token_overlap")

    if "definition_phrase" in shapes:
        score += 1.5
        reasons.append("definition_shape")
    if "mechanism_description" in shapes:
        score += 1.5
        reasons.append("mechanism_shape")
    if "formula_relation" in shapes:
        score += 1.25
        reasons.append("formula_shape")
    if "process_phrase" in shapes:
        score += 1.25
        reasons.append("process_shape")

    if sibling_hits and not exact_terms and not stripped_terms:
        score -= 4.0
        reasons.append("sibling_collision_without_target_surface")

    strong_exact_terms = []
    for term in exact_terms:
        toks = content_tokens(term, dynamic_broad_tokens=dynamic_broad_tokens)
        raw_toks = phrase_tokens(term)
        if len(toks) >= 2 or len(raw_toks) >= 2:
            strong_exact_terms.append(term)

    strong_target_binding = bool(strong_exact_terms or stripped_terms or len(target_overlap) >= 2)

    if not strong_target_binding:
        score = min(score, 0.0)
        reasons.append("insufficient_target_binding")

    return {
        "score": round(score, 4),
        "reasons": reasons,
        "exact_terms": dedupe_keep_order(exact_terms),
        "stripped_terms": dedupe_keep_order(stripped_terms),
        "target_overlap": target_overlap,
        "branch_overlap": branch_overlap,
        "sibling_hits": sibling_hits,
        "evidence_shapes": shapes,
    }
