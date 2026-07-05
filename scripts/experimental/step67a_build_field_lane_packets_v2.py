#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKETS_PATH = Path("data/processed/step67_sidecar_packets/2026-04-28_130527/evidence_packets.jsonl")
OVERLAY_PATH = Path("data/processed/kc_drafting_input_overlay/2026-04-28_002730/candidate_sentence_overlay.jsonl")
OUT_ROOT = Path("data/processed/step67_sidecar_lane_packets_v2")

GENERIC_TERMS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "data", "dataset",
    "datasets", "the", "this", "that", "to", "of", "for", "from", "in", "into", "is",
    "it", "its", "on", "or", "with", "within", "without", "using", "use", "used",
    "method", "methods", "model", "models", "algorithm", "algorithms", "approach",
    "approaches", "example", "examples", "overview", "quality", "evaluation", "evaluate",
    "measure", "measures", "measured", "index", "indices", "value", "values", "score",
    "scores", "class", "classes", "classification", "training", "test", "testing",
    "validation", "set", "sets", "object", "objects", "point", "points", "cluster",
    "clusters", "clustering", "node", "nodes", "tree", "trees", "case", "cases",
    "problem", "problems", "basic", "core", "external", "internal", "handling",
    "missing", "preparing", "learning",
}

PHRASE_OK_GENERIC = {"internal", "external", "core", "missing"}

DEF_PATTERNS = [
    (r"\bis called\b", 3.0),
    (r"\bare called\b", 3.0),
    (r"\bis also known as\b", 3.0),
    (r"\bis known as\b", 2.7),
    (r"\bis defined as\b", 3.2),
    (r"\bare defined as\b", 3.2),
    (r"\bformally defined as\b", 3.6),
    (r"\brefers to\b", 2.8),
    (r"\bmeasures?\b", 1.8),
    (r"\bmeasured by\b", 2.8),
    (r"\bcalculated as\b", 2.6),
    (r"\bcomputed as\b", 2.6),
    (r"\bwe use the\b", 2.4),
    (r"\bin other words\b", 2.3),
    (r"\bis a\b", 1.3),
    (r"\bis an\b", 1.3),
    (r"\bare data points\b", 2.4),
]

SCOPE_PATTERNS = [
    (r"\bused for\b", 2.5),
    (r"\bused to\b", 2.2),
    (r"\bshould be\b", 2.0),
    (r"\bcan be\b", 1.5),
    (r"\bcauses?\b", 2.4),
    (r"\bcause\b", 2.4),
    (r"\bindicates?\b", 2.2),
    (r"\bprefer\b", 2.0),
    (r"\blower\b", 1.8),
    (r"\bhigher\b", 1.8),
    (r"\bbetter\b", 1.6),
    (r"\bcommon mistake\b", 2.8),
    (r"\bwithin the training fold\b", 3.0),
    (r"\bcharacteri[sz]ed by\b", 2.6),
    (r"\btroublesome\b", 2.2),
    (r"\bwasting\b", 1.9),
    (r"\binconsistency\b", 1.9),
    (r"\bnot part of\b", 2.2),
    (r"\bnot in a cluster\b", 2.2),
]

CONTEXT_PATTERNS = [
    (r"\bfor example\b", 1.5),
    (r"\bsuch as\b", 1.2),
    (r"\bprocedure\b", 1.2),
    (r"\balgorithm\b", 1.0),
    (r"\bfigure\b", 0.8),
    (r"\bsection\b", 0.6),
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def now_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def norm_text(value: Any) -> str:
    s = str(value or "").lower()
    s = s.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-")
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    s = s.replace("crossvalidation", "cross validation")
    s = s.replace("kmeans", "k means")
    s = re.sub(r"[^a-z0-9+_.#-]+", " ", s)
    s = s.replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def tokens(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", norm_text(value))


def word_set(value: Any) -> set[str]:
    return set(tokens(value))


def contains_phrase(text_norm: str, phrase_norm: str) -> bool:
    if not text_norm or not phrase_norm:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase_norm)}(?![a-z0-9])", text_norm) is not None


def strip_parenthetical(name: str) -> str:
    return re.sub(r"\([^)]*\)", " ", str(name or "")).strip()


def parenthetical_parts(name: str) -> list[str]:
    return [m.strip() for m in re.findall(r"\(([^)]*)\)", str(name or "")) if m.strip()]


def ngrams(seq: list[str], min_n: int = 2, max_n: int = 5) -> list[str]:
    out: list[str] = []
    for n in range(min_n, max_n + 1):
        for i in range(0, max(0, len(seq) - n + 1)):
            out.append(" ".join(seq[i : i + n]))
    return out


def meaningful_phrase(phrase: str) -> bool:
    ts = tokens(phrase)
    if len(ts) < 2:
        return False
    non_generic = [t for t in ts if t not in GENERIC_TERMS or t in PHRASE_OK_GENERIC]
    return len(non_generic) >= 1


def upper_abbrevs(value: Any) -> list[str]:
    out: list[str] = []
    for m in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", str(value or "")):
        if m not in {"KC", "DM", "PDF", "JSON", "ID"}:
            out.append(m.lower())
    return out


def build_target_profile(packet: dict[str, Any]) -> dict[str, Any]:
    canonical = str(packet.get("canonical_name") or "")
    aliases = [str(x) for x in (packet.get("aliases") or []) if str(x).strip()]
    seed = str(packet.get("seed_definition") or "")
    topic_path = " ; ".join(str(x) for x in (packet.get("topic_path_labels") or []) if str(x).strip())

    phrase_sources: list[tuple[str, str]] = []
    canonical_no_paren = strip_parenthetical(canonical)

    for label, value in [("canonical", canonical), ("canonical_no_paren", canonical_no_paren)]:
        n = norm_text(value)
        if meaningful_phrase(n):
            phrase_sources.append((label, n))

    for part in parenthetical_parts(canonical):
        n = norm_text(part)
        if meaningful_phrase(n):
            phrase_sources.append(("canonical_parenthetical", n))

    for alias in aliases:
        n = norm_text(alias)
        if meaningful_phrase(n) or len(tokens(n)) == 1:
            phrase_sources.append(("alias", n))

    for label, value in [("canonical_ngram", canonical), ("seed_ngram", seed)]:
        ts = tokens(value)
        for ng in ngrams(ts, 2, 5):
            if meaningful_phrase(ng):
                phrase_sources.append((label, ng))

    abbrevs = []
    for value in [canonical, *aliases, seed]:
        abbrevs.extend(upper_abbrevs(value))

    head = str(canonical).split("(", 1)[0].strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,9}", head) and head.upper() == head:
        abbrevs.append(head.lower())

    canonical_terms = tokens(canonical_no_paren)
    non_generic_canonical_terms = [t for t in canonical_terms if t not in GENERIC_TERMS and len(t) > 1]
    single_strong_terms: list[str] = []

    if len(non_generic_canonical_terms) == 1:
        single_strong_terms.append(non_generic_canonical_terms[0])

    for alias in aliases:
        ats = tokens(alias)
        if len(ats) == 1 and ats[0] not in GENERIC_TERMS and len(ats[0]) > 1:
            single_strong_terms.append(ats[0])

    seen_phrases = set()
    phrases = []
    for source, phrase in phrase_sources:
        if phrase and phrase not in seen_phrases:
            seen_phrases.add(phrase)
            phrases.append({"source": source, "phrase": phrase})

    subject_terms = []
    for t in canonical_terms:
        if t not in GENERIC_TERMS and len(t) > 1:
            subject_terms.append(t)
    for ab in abbrevs:
        if ab not in subject_terms:
            subject_terms.append(ab)

    return {
        "canonical_name": canonical,
        "aliases": aliases,
        "seed_definition": seed,
        "topic_path_text": topic_path,
        "phrases": phrases,
        "abbreviations": sorted(set(abbrevs)),
        "subject_terms": sorted(set(subject_terms)),
        "single_strong_terms": sorted(set(single_strong_terms)),
    }


def target_anchor(text: str, profile: dict[str, Any]) -> dict[str, Any]:
    nt = norm_text(text)
    hits: list[dict[str, Any]] = []
    score = 0.0

    for ab in profile.get("abbreviations", []):
        if contains_phrase(nt, norm_text(ab)):
            score += 4.0
            hits.append({"kind": "abbreviation", "value": ab, "score": 4.0})

    for term in profile.get("single_strong_terms", []):
        if contains_phrase(nt, norm_text(term)):
            score += 3.5
            hits.append({"kind": "single_strong_term", "value": term, "score": 3.5})

    for item in profile.get("phrases", []):
        phrase = str(item.get("phrase") or "")
        if not phrase:
            continue
        if contains_phrase(nt, phrase):
            ts = tokens(phrase)
            base = 2.5 + min(2.0, 0.4 * len(ts))
            if item.get("source") in {"canonical", "canonical_no_paren", "alias"}:
                base += 1.0
            if item.get("source") == "seed_ngram":
                base += 0.5
            score += base
            hits.append({"kind": str(item.get("source") or "phrase"), "value": phrase, "score": round(base, 3)})

    text_terms = word_set(nt)
    subject_hits = [t for t in profile.get("subject_terms", []) if t in text_terms]
    if len(subject_hits) >= 2:
        add = 2.0 + min(2.0, 0.5 * len(subject_hits))
        score += add
        hits.append({"kind": "subject_term_combo", "value": subject_hits, "score": round(add, 3)})
    elif len(subject_hits) == 1:
        score += 0.75
        hits.append({"kind": "single_subject_term_weak", "value": subject_hits, "score": 0.75})

    strong = (
        any(h["kind"] == "abbreviation" for h in hits)
        or any(h["kind"] == "single_strong_term" for h in hits)
        or any(
            h["kind"] in {"canonical", "canonical_no_paren", "alias", "canonical_ngram", "seed_ngram"}
            and float(h.get("score", 0.0)) >= 3.0
            for h in hits
        )
        or score >= 5.0
    )

    very_strong = (
        score >= 7.0
        or any(h["kind"] == "abbreviation" for h in hits)
        or any(h["kind"] == "single_strong_term" for h in hits)
    )

    return {
        "score": round(score, 3),
        "strong": bool(strong),
        "very_strong": bool(very_strong),
        "hits": hits,
        "subject_hits": subject_hits,
    }


def first_str(obj: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def get_nested(obj: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def is_question_or_exercise(text: str) -> bool:
    s = norm_text(text)
    if not s:
        return False
    if "?" in str(text):
        return True
    starts = (
        "describe ", "explain ", "compute ", "calculate ", "show ", "prove ",
        "find ", "assume ", "exercise ", "problem ", "question ",
    )
    return any(s.startswith(x) for x in starts)


def formula_like(text: str) -> bool:
    raw = str(text or "")
    if "\\begin" in raw or "\\sum" in raw or "$" in raw:
        return True
    symbols = len(re.findall(r"[=<>∑Σλγ{}_^]", raw))
    words_count = len(tokens(raw))
    return symbols >= 4 and symbols >= max(3, words_count // 6)


def fragmentary(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    if len(tokens(s)) <= 5:
        return True
    if s.startswith(",") or s.lower().startswith("where "):
        return True
    return False


def sibling_or_negated_target(text: str, profile: dict[str, Any]) -> dict[str, Any]:
    nt = norm_text(text)
    hits: list[str] = []
    for item in profile.get("phrases", []):
        phrase = str(item.get("phrase") or "")
        if len(tokens(phrase)) < 2:
            continue
        if re.search(rf"\bnot\s+(?:a\s+|an\s+|the\s+|enough\s+)?{re.escape(phrase)}\b", nt):
            hits.append(f"not {phrase}")
        if re.search(rf"\bnot\s+.*\b{re.escape(phrase)}\b", nt) and len(nt) < 220:
            hits.append(f"not ... {phrase}")

    for term in profile.get("single_strong_terms", []):
        if re.search(rf"\bnot\s+(?:a\s+|an\s+|the\s+|enough\s+)?{re.escape(term)}\b", nt):
            hits.append(f"not {term}")

    sibling_terms = {"border point", "noise point", "outlier", "sibling", "contrast"}
    has_sibling_term = any(term in nt for term in sibling_terms)
    return {"is_sibling_contrast": bool(hits and has_sibling_term), "hits": hits, "has_sibling_term": has_sibling_term}


def pattern_score(text: str, patterns: list[tuple[str, float]]) -> tuple[float, list[str]]:
    nt = norm_text(text)
    score = 0.0
    hits: list[str] = []
    for pat, weight in patterns:
        if re.search(pat, nt):
            score += weight
            hits.append(pat)
    return score, hits


def enrich_evidence(ev: dict[str, Any], overlay_by_id: dict[str, dict[str, Any]], fallback_index: int) -> dict[str, Any]:
    overlay_candidate_id = str(ev.get("overlay_candidate_id") or "")
    overlay = overlay_by_id.get(overlay_candidate_id, {})

    quote_text = first_str(ev, ["text", "quote", "quote_surface", "candidate_text"])
    if not quote_text:
        quote_text = first_str(overlay, ["quote_surface", "original_quote_surface", "text", "sentence_text"])

    context_text = first_str(
        overlay,
        ["source_block_text", "source_block_text_raw", "original_source_block_text", "quote_surface", "original_quote_surface"],
    )
    if not context_text:
        context_text = quote_text

    support_profile = overlay.get("support_profile") if isinstance(overlay.get("support_profile"), dict) else {}
    role_hint = overlay.get("role_hint") if isinstance(overlay.get("role_hint"), dict) else {}
    retrieval_scores = overlay.get("retrieval_scores") if isinstance(overlay.get("retrieval_scores"), dict) else {}

    role_hints = ev.get("role_hints") if isinstance(ev.get("role_hints"), list) else []
    risk_hints = ev.get("risk_hints") if isinstance(ev.get("risk_hints"), list) else []

    provenance = ev.get("provenance") if isinstance(ev.get("provenance"), dict) else {}
    enriched_provenance = {
        "packet_provenance": provenance,
        "doc_id": provenance.get("doc_id") or overlay.get("doc_id") or overlay.get("original_doc_id") or "",
        "page_index": provenance.get("page_index") if provenance.get("page_index") is not None else overlay.get("page_index"),
        "block_id": provenance.get("block_id") or overlay.get("block_id") or overlay.get("original_block_id") or "",
        "sentence_id": provenance.get("sentence_id") or overlay.get("sentence_id") or overlay.get("original_sentence_id") or "",
        "patch_id": provenance.get("patch_id") or overlay.get("patch_id") or overlay.get("original_patch_id") or "",
        "patch_heading": provenance.get("patch_heading") or overlay.get("patch_heading") or overlay.get("original_patch_heading") or "",
        "patch_type": overlay.get("patch_type") or overlay.get("original_patch_type") or "",
        "layer": provenance.get("layer") or overlay.get("layer") or overlay.get("original_layer") or "",
        "quote_verified": overlay.get("quote_verified"),
        "quote_verification_status": overlay.get("quote_verification_status") or "",
    }

    return {
        "evidence_id": str(ev.get("evidence_id") or f"E{fallback_index}"),
        "overlay_candidate_id": overlay_candidate_id,
        "source_candidate_index": ev.get("source_candidate_index", overlay.get("source_candidate_index")),
        "quote_text": quote_text,
        "context_text": context_text,
        "text_source": ev.get("text_source") or overlay.get("text_source") or "",
        "definition_score_original": as_float(ev.get("definition_score")),
        "scope_score_original": as_float(ev.get("scope_score")),
        "role_hints": role_hints,
        "risk_hints": risk_hints,
        "support_profile": support_profile,
        "role_hint": role_hint,
        "retrieval_scores": retrieval_scores,
        "contamination_risk": overlay.get("contamination_risk") or "",
        "contamination_signals": overlay.get("contamination_signals") if isinstance(overlay.get("contamination_signals"), list) else [],
        "is_heading_like": bool(overlay.get("is_heading_like")),
        "is_definition_like": bool(overlay.get("is_definition_like")),
        "provenance": enriched_provenance,
    }


def classify_item(item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    combined_text = "\n".join([item.get("quote_text") or "", item.get("context_text") or ""]).strip()
    anchor = target_anchor(combined_text, profile)

    def_score_raw, def_patterns = pattern_score(combined_text, DEF_PATTERNS)
    scope_score_raw, scope_patterns = pattern_score(combined_text, SCOPE_PATTERNS)
    context_score_raw, context_patterns = pattern_score(combined_text, CONTEXT_PATTERNS)

    support_profile = item.get("support_profile") if isinstance(item.get("support_profile"), dict) else {}
    role_hint = item.get("role_hint") if isinstance(item.get("role_hint"), dict) else {}
    retrieval_scores = item.get("retrieval_scores") if isinstance(item.get("retrieval_scores"), dict) else {}

    contamination_risk = str(item.get("contamination_risk") or "").lower()
    contamination_signals = item.get("contamination_signals") if isinstance(item.get("contamination_signals"), list) else []
    role_hints = [str(x).lower() for x in (item.get("role_hints") or [])]
    risk_hints = [str(x).lower() for x in (item.get("risk_hints") or [])]

    rerank_margin = as_float(retrieval_scores.get("rerank_margin"), 0.0)
    competitor_hits = as_float(retrieval_scores.get("competitor_token_hits"), 0.0)

    flags: list[str] = []
    if contamination_risk == "high" or "high_contamination" in role_hints or "high_contamination" in risk_hints:
        flags.append("high_contamination_risk")
    if contamination_signals:
        flags.append("contamination_signals_present")
    if rerank_margin < 0:
        flags.append("negative_rerank_margin")
    if bool(support_profile.get("source_block_completion_used")):
        flags.append("source_block_completion_used")
    if bool(role_hint.get("ambiguous")) or not str(role_hint.get("safe_role_hint") or ""):
        flags.append("ambiguous_role_hint")
    if formula_like(combined_text):
        flags.append("formula_or_equation_like")
    if fragmentary(item.get("quote_text") or "") or bool(support_profile.get("fragmentary_surface")):
        flags.append("fragmentary_surface")
    if bool(support_profile.get("needs_context_completion")):
        flags.append("needs_context_completion")
    if is_question_or_exercise(item.get("quote_text") or ""):
        flags.append("question_or_exercise_prompt")

    sibling = sibling_or_negated_target(combined_text, profile)
    if sibling["is_sibling_contrast"]:
        flags.append("negated_target_or_sibling_contrast")

    hard_reason = ""
    if "question_or_exercise_prompt" in flags:
        hard_reason = "exercise/question prompt is not declarative KC evidence"
    elif sibling["is_sibling_contrast"]:
        hard_reason = "sibling or negated-target contrast"
    elif not anchor["strong"]:
        hard_reason = "no strong target anchor"
    elif "high_contamination_risk" in flags and rerank_margin < 0 and not anchor["very_strong"]:
        hard_reason = "high contamination or competitor risk without enough target relevance"
    elif competitor_hits > 0 and not anchor["very_strong"]:
        hard_reason = "competitor token hits without very strong target anchor"
    elif "formula_or_equation_like" in flags and not anchor["very_strong"]:
        hard_reason = "formula/equation-like row without very strong target anchor"

    weak_def_hint = 0.0
    if str(role_hint.get("safe_role_hint") or "") == "definition":
        weak_def_hint += 0.4
    if str(support_profile.get("preferred_support_role") or "") in {"definitional_anchor", "definition_anchor"}:
        weak_def_hint += 0.4
    weak_def_hint += min(0.8, max(0.0, item.get("definition_score_original", 0.0)) / 20.0)
    weak_def_hint += min(0.6, max(0.0, as_float(support_profile.get("definition_anchor_score"))) / 12.0)

    weak_scope_hint = 0.0
    if "scope" in role_hints:
        weak_scope_hint += 0.4
    if str(support_profile.get("preferred_support_role") or "") == "explanatory_anchor":
        weak_scope_hint += 0.5
    weak_scope_hint += min(0.7, max(0.0, item.get("scope_score_original", 0.0)) / 20.0)
    weak_scope_hint += min(0.6, max(0.0, as_float(support_profile.get("explanatory_anchor_score"))) / 12.0)

    definition_score_v2 = anchor["score"] + def_score_raw + weak_def_hint
    scope_score_v2 = anchor["score"] + scope_score_raw + weak_scope_hint
    context_score_v2 = anchor["score"] + context_score_raw + min(0.5, as_float(support_profile.get("context_completion_score")) / 10.0)

    if "high_contamination_risk" in flags:
        definition_score_v2 -= 1.0
        scope_score_v2 -= 0.7
        context_score_v2 -= 0.5
    if "negative_rerank_margin" in flags:
        definition_score_v2 -= 0.5
        scope_score_v2 -= 0.3
    if "fragmentary_surface" in flags:
        definition_score_v2 -= 0.6
    if "formula_or_equation_like" in flags:
        scope_score_v2 -= 0.5
        context_score_v2 -= 0.3

    reason = ""
    primary_lane = "quarantine_or_irrelevant"

    if hard_reason:
        primary_lane = "sibling_contrast" if sibling["is_sibling_contrast"] else "quarantine_or_irrelevant"
        reason = hard_reason
    else:
        if definition_score_v2 >= max(5.5, scope_score_v2 + 1.0) and def_score_raw >= 1.3:
            primary_lane = "definition_candidate"
            reason = "strong target anchor plus definitional pattern"
        elif scope_score_v2 >= 5.5 and scope_score_v2 >= definition_score_v2 - 0.25 and scope_score_raw >= 1.5:
            primary_lane = "scope_candidate"
            reason = "strong target anchor plus scope or consequence pattern"
        elif context_score_v2 >= 4.5:
            primary_lane = "context_candidate"
            reason = "target-relevant contextual support"
        else:
            primary_lane = "quarantine_or_irrelevant"
            reason = "target anchor exists but field support is too weak"

    selection_score = max(definition_score_v2, scope_score_v2, context_score_v2)
    if primary_lane == "definition_candidate":
        selection_score = definition_score_v2
    elif primary_lane == "scope_candidate":
        selection_score = scope_score_v2
    elif primary_lane == "context_candidate":
        selection_score = context_score_v2

    return {
        "primary_lane": primary_lane,
        "reason": reason,
        "flags": flags,
        "target_anchor": anchor,
        "scores_v2": {
            "definition_score_v2": round(definition_score_v2, 3),
            "scope_score_v2": round(scope_score_v2, 3),
            "context_score_v2": round(context_score_v2, 3),
            "selection_score": round(selection_score, 3),
            "definition_pattern_score": round(def_score_raw, 3),
            "scope_pattern_score": round(scope_score_raw, 3),
            "context_pattern_score": round(context_score_raw, 3),
            "weak_def_hint": round(weak_def_hint, 3),
            "weak_scope_hint": round(weak_scope_hint, 3),
            "rerank_margin": rerank_margin,
            "competitor_token_hits": competitor_hits,
        },
        "pattern_hits": {
            "definition": def_patterns,
            "scope": scope_patterns,
            "context": context_patterns,
        },
        "sibling_contrast": sibling,
    }


def summarize_item_for_model(item: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": item["evidence_id"],
        "overlay_candidate_id": item["overlay_candidate_id"],
        "source_candidate_index": item.get("source_candidate_index"),
        "lane": classification["primary_lane"],
        "reason": classification["reason"],
        "flags": classification["flags"],
        "target_anchor": classification["target_anchor"],
        "scores_v2": classification["scores_v2"],
        "pattern_hits": classification["pattern_hits"],
        "quote_text": item.get("quote_text") or "",
        "context_text": item.get("context_text") or "",
        "provenance": item.get("provenance") or {},
        "role_metadata": {
            "role_hints": item.get("role_hints") or [],
            "risk_hints": item.get("risk_hints") or [],
            "support_profile": item.get("support_profile") or {},
            "role_hint": item.get("role_hint") or {},
            "retrieval_scores": item.get("retrieval_scores") or {},
            "contamination_risk": item.get("contamination_risk") or "",
            "contamination_signals": item.get("contamination_signals") or [],
            "is_heading_like": item.get("is_heading_like"),
            "is_definition_like": item.get("is_definition_like"),
        },
    }


def pick_top(items: list[dict[str, Any]], lane: str, n: int, excluded_ids: set[str]) -> list[dict[str, Any]]:
    candidates = [x for x in items if x["lane"] == lane and x["evidence_id"] not in excluded_ids]
    candidates.sort(
        key=lambda x: (
            as_float(x["scores_v2"].get("selection_score")),
            as_float(x["scores_v2"].get("definition_score_v2")),
        ),
        reverse=True,
    )
    picked = candidates[:n]
    excluded_ids.update(x["evidence_id"] for x in picked)
    return picked


def short(text: Any, max_len: int = 900) -> str:
    s = str(text or "").replace("\n", " ").strip()
    return s[:max_len] + ("..." if len(s) > max_len else "")


def main() -> None:
    packets = load_jsonl(PACKETS_PATH)
    overlay_rows = load_jsonl(OVERLAY_PATH)
    overlay_by_id = {str(r.get("overlay_candidate_id") or ""): r for r in overlay_rows if r.get("overlay_candidate_id")}

    run_id = now_run_id()
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    output_rows: list[dict[str, Any]] = []
    lane_counter_all_items: Counter[str] = Counter()
    selected_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()

    for packet in packets:
        profile = build_target_profile(packet)
        evidence = packet.get("evidence") if isinstance(packet.get("evidence"), list) else []

        all_items: list[dict[str, Any]] = []

        for i, ev in enumerate(evidence, start=1):
            if not isinstance(ev, dict):
                continue

            item = enrich_evidence(ev, overlay_by_id, i)
            classification = classify_item(item, profile)
            summarized = summarize_item_for_model(item, classification)

            all_items.append(summarized)
            lane_counter_all_items[classification["primary_lane"]] += 1
            flag_counter.update(classification["flags"])

        excluded: set[str] = set()
        definition_lane = pick_top(all_items, "definition_candidate", 2, excluded)
        scope_lane = pick_top(all_items, "scope_candidate", 3, excluded)
        context_lane = pick_top(all_items, "context_candidate", 3, excluded)

        selected_counter["definition_lane"] += len(definition_lane)
        selected_counter["scope_lane"] += len(scope_lane)
        selected_counter["context_lane"] += len(context_lane)

        selected_ids = {x["evidence_id"] for x in [*definition_lane, *scope_lane, *context_lane]}
        quarantine_lane = [x for x in all_items if x["lane"] in {"quarantine_or_irrelevant", "sibling_contrast"}]
        overflow_unselected = [
            x for x in all_items
            if x["lane"] not in {"quarantine_or_irrelevant", "sibling_contrast"}
            and x["evidence_id"] not in selected_ids
        ]

        output_rows.append({
            "lane_packet_contract_version": "step67a_field_lane_packets_v2",
            "run_id": run_id,
            "source_packets_path": PACKETS_PATH.as_posix(),
            "source_overlay_path": OVERLAY_PATH.as_posix(),
            "kc_id": packet.get("kc_id"),
            "canonical_name": packet.get("canonical_name"),
            "aliases": packet.get("aliases") or [],
            "seed_definition": packet.get("seed_definition") or "",
            "seed_definition_is_not_evidence": bool(packet.get("seed_definition_is_not_evidence", True)),
            "topic_path_labels": packet.get("topic_path_labels") or [],
            "query_text": packet.get("query_text") or "",
            "target_profile": profile,
            "review_queue_aux": packet.get("review_queue_aux") or {},
            "support_pack_summary": packet.get("support_pack_summary") or {},
            "source_candidate_row_count_for_kc": packet.get("source_candidate_row_count_for_kc"),
            "lane_counts_all_items": dict(Counter(x["lane"] for x in all_items)),
            "definition_candidates_all": [x for x in all_items if x["lane"] == "definition_candidate"],
            "scope_candidates_all": [x for x in all_items if x["lane"] == "scope_candidate"],
            "context_candidates_all": [x for x in all_items if x["lane"] == "context_candidate"],
            "definition_lane": definition_lane,
            "scope_lane": scope_lane,
            "context_lane": context_lane,
            "quarantine_lane": quarantine_lane,
            "overflow_unselected": overflow_unselected,
            "all_items": all_items,
        })

    lane_packets_path = out_dir / "lane_packets.jsonl"
    summary_path = out_dir / "summary.json"
    audit_path = out_dir / "lane_audit.md"

    write_jsonl(lane_packets_path, output_rows)

    summary = {
        "stage": "step67a_build_field_lane_packets_v2",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "packets_path": PACKETS_PATH.as_posix(),
        "overlay_path": OVERLAY_PATH.as_posix(),
        "out_dir": out_dir.as_posix(),
        "lane_packets_path": lane_packets_path.as_posix(),
        "packet_count": len(output_rows),
        "lane_counter_all_items": dict(lane_counter_all_items),
        "selected_counter": dict(selected_counter),
        "flag_counter": dict(flag_counter),
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md: list[str] = []
    md.append("# Step 6.7A v2 field-lane packet audit")
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append("```json")
    md.append(json.dumps(summary, indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")

    for row in output_rows:
        md.append(f"## {row['kc_id']} | {row['canonical_name']}")
        md.append("")
        md.append(f"- lane_counts_all_items: `{row['lane_counts_all_items']}`")
        md.append(f"- definition_lane_count: `{len(row['definition_lane'])}`")
        md.append(f"- scope_lane_count: `{len(row['scope_lane'])}`")
        md.append(f"- context_lane_count: `{len(row['context_lane'])}`")
        md.append(f"- quarantine_lane_count: `{len(row['quarantine_lane'])}`")
        md.append("")

        for lane_name in ["definition_lane", "scope_lane", "context_lane", "quarantine_lane", "overflow_unselected"]:
            md.append(f"### {lane_name}")
            md.append("")
            items = row[lane_name]
            if not items:
                md.append("_empty_")
                md.append("")
                continue

            for item in items:
                md.append(f"#### {item['evidence_id']} | {item['lane']}")
                md.append(f"- overlay_candidate_id: `{item['overlay_candidate_id']}`")
                md.append(f"- reason: `{item['reason']}`")
                md.append(f"- flags: `{item['flags']}`")
                md.append(f"- target_anchor: `{item['target_anchor']}`")
                md.append(f"- scores_v2: `{item['scores_v2']}`")
                md.append(f"- pattern_hits: `{item['pattern_hits']}`")
                md.append(f"- provenance: `{item['provenance']}`")

                role_meta = item.get("role_metadata") or {}
                compact_role_meta = {
                    "role_hints": role_meta.get("role_hints"),
                    "risk_hints": role_meta.get("risk_hints"),
                    "preferred_support_role": get_nested(role_meta, ["support_profile", "preferred_support_role"], ""),
                    "support_roles": get_nested(role_meta, ["support_profile", "support_roles"], []),
                    "safe_role_hint": get_nested(role_meta, ["role_hint", "safe_role_hint"], ""),
                    "top_role": get_nested(role_meta, ["role_hint", "top_role"], ""),
                    "role_ambiguous": get_nested(role_meta, ["role_hint", "ambiguous"], None),
                    "contamination_risk": role_meta.get("contamination_risk"),
                    "contamination_signals": role_meta.get("contamination_signals"),
                    "retrieval_scores": role_meta.get("retrieval_scores"),
                }

                md.append(f"- role_metadata: `{compact_role_meta}`")
                md.append(f"- quote_text: {short(item.get('quote_text'))}")
                md.append(f"- context_text: {short(item.get('context_text'))}")
                md.append("")

    audit_path.write_text("\n".join(md), encoding="utf-8")

    print("STEP67A_V2_LANE_RUN_ID =", run_id)
    print("STEP67A_V2_LANE_DIR =", out_dir.as_posix())
    print("STEP67A_V2_LANE_PACKETS =", lane_packets_path.as_posix())
    print("STEP67A_V2_LANE_SUMMARY =", summary_path.as_posix())
    print("STEP67A_V2_LANE_AUDIT_MD =", audit_path.as_posix())
    print("lane_counter_all_items =", json.dumps(dict(lane_counter_all_items), indent=2, ensure_ascii=False))
    print("selected_counter =", json.dumps(dict(selected_counter), indent=2, ensure_ascii=False))
    print("flag_counter =", json.dumps(dict(flag_counter), indent=2, ensure_ascii=False))
    print("STEP67A_V2_FIELD_LANE_PACKETS_DONE")


if __name__ == "__main__":
    main()
