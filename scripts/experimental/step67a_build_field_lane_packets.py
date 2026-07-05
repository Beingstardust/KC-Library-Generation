import json
import re
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKETS_PATH = Path("data/processed/step67_sidecar_packets/2026-04-28_130527/evidence_packets.jsonl")
OVERLAY_PATH = Path("data/processed/kc_drafting_input_overlay/2026-04-28_002730/candidate_sentence_overlay.jsonl")
OUT_ROOT = Path("data/processed/step67_sidecar_lane_packets")


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "by", "can", "for", "from",
    "has", "have", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "these", "this", "to", "using", "with", "without", "within", "where",
    "which", "we", "use", "used", "uses", "only", "also", "often", "called",
    "data", "set", "sets", "point", "points", "object", "objects", "example",
    "algorithm", "model", "models", "method", "methods", "measure", "measures",
    "quality", "structure", "different", "given"
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def short(text: Any, max_len: int = 900) -> str:
    s = str(text or "").replace("\n", " ")
    return s[:max_len] + ("..." if len(s) > max_len else "")


def tokens(text: Any) -> list[str]:
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]*", norm(text))
    return [t for t in raw if len(t) >= 3 and t not in STOPWORDS]


def token_set(text: Any) -> set[str]:
    return set(tokens(text))


def abbrev_tokens(text: Any) -> set[str]:
    out = set()
    for part in re.findall(r"\b[A-Z]{2,8}\b", str(text or "")):
        out.add(part.lower())
    return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def get_nested(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def evidence_text(ev: dict[str, Any]) -> str:
    for key in ("text", "quote", "quote_surface", "source_block_text", "candidate_text"):
        value = ev.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def overlay_texts(row: dict[str, Any]) -> list[str]:
    values = []
    for key in (
        "quote_surface",
        "original_quote_surface",
        "source_block_text",
        "source_block_text_raw",
        "original_source_block_text",
        "text",
        "candidate_text",
        "sentence_text",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return values


def match_overlay(ev: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    oid = str(ev.get("overlay_candidate_id") or "")
    if oid:
        for row in candidates:
            if str(row.get("overlay_candidate_id") or "") == oid:
                return row

    ev_norm = norm(evidence_text(ev))
    if not ev_norm:
        return {}

    for row in candidates:
        for txt in overlay_texts(row):
            row_norm = norm(txt)
            if ev_norm == row_norm or ev_norm in row_norm or row_norm in ev_norm:
                return row
    return {}


def is_question_or_exercise(text: str) -> bool:
    low = norm(text)
    starts = (
        "describe ",
        "explain ",
        "show ",
        "prove ",
        "compute ",
        "calculate ",
        "find ",
        "what ",
        "why ",
        "how ",
    )
    return low.endswith("?") or any(low.startswith(s) for s in starts)


def phrase_hit(text: str, phrase: str) -> bool:
    p = norm(phrase)
    if not p:
        return False
    return p in norm(text)


def negated_target(text: str, canonical_name: str, aliases: list[str]) -> bool:
    low = norm(text)
    names = [canonical_name] + aliases
    for name in names:
        n = norm(name)
        if not n:
            continue
        n = re.sub(r"\([^)]*\)", "", n).strip()
        if not n:
            continue
        patterns = [
            f"not a {n}",
            f"not an {n}",
            f"not {n}",
            f"without {n}",
            f"rather than {n}",
        ]
        if any(p in low for p in patterns):
            return True
    return False


def compute_relevance(packet: dict[str, Any], text: str) -> dict[str, Any]:
    canonical = str(packet.get("canonical_name") or "")
    aliases = [str(x) for x in (packet.get("aliases") or [])]
    seed = str(packet.get("seed_definition") or "")
    query = str(packet.get("query_text") or "")
    topics = " ".join(str(x) for x in (packet.get("topic_path_labels") or []))

    subject_terms = token_set(canonical + " " + " ".join(aliases))
    seed_terms = token_set(seed)
    query_terms = token_set(query)
    topic_terms = token_set(topics)

    text_terms = token_set(text)
    text_abbrevs = abbrev_tokens(text)
    target_abbrevs = abbrev_tokens(canonical + " " + " ".join(aliases) + " " + seed)

    subject_hits = sorted(subject_terms & text_terms)
    seed_hits = sorted(seed_terms & text_terms)
    query_hits = sorted(query_terms & text_terms)
    topic_hits = sorted(topic_terms & text_terms)
    abbrev_hits = sorted(target_abbrevs & text_abbrevs)

    score = (
        3.0 * len(abbrev_hits)
        + 2.0 * len(subject_hits)
        + 0.75 * len(seed_hits)
        + 0.35 * len(query_hits)
        + 0.15 * len(topic_hits)
    )

    return {
        "subject_terms": sorted(subject_terms),
        "seed_term_count": len(seed_terms),
        "query_term_count": len(query_terms),
        "topic_term_count": len(topic_terms),
        "subject_hits": subject_hits,
        "seed_hits": seed_hits[:20],
        "query_hits": query_hits[:20],
        "topic_hits": topic_hits[:20],
        "abbrev_hits": abbrev_hits,
        "target_relevance_score": round(score, 4),
    }


def classify_lane(packet: dict[str, Any], ev: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    canonical = str(packet.get("canonical_name") or "")
    aliases = [str(x) for x in (packet.get("aliases") or [])]

    quote_text = evidence_text(ev)
    context_text = str(
        overlay.get("source_block_text")
        or overlay.get("source_block_text_raw")
        or overlay.get("original_source_block_text")
        or ""
    )

    combined_for_relevance = quote_text + "\n" + context_text
    relevance = compute_relevance(packet, combined_for_relevance)

    support_profile = overlay.get("support_profile") if isinstance(overlay.get("support_profile"), dict) else {}
    role_hint = overlay.get("role_hint") if isinstance(overlay.get("role_hint"), dict) else {}

    preferred_support_role = str(support_profile.get("preferred_support_role") or "")
    support_roles = [str(x) for x in support_profile.get("support_roles", [])] if isinstance(support_profile.get("support_roles"), list) else []

    safe_role_hint = str(role_hint.get("safe_role_hint") or "")
    top_role = str(role_hint.get("top_role") or "")
    role_ambiguous = bool(role_hint.get("ambiguous"))

    contamination_risk = str(overlay.get("contamination_risk") or "")
    contamination_signals = [str(x) for x in overlay.get("contamination_signals", [])] if isinstance(overlay.get("contamination_signals"), list) else []

    retrieval_scores = overlay.get("retrieval_scores") if isinstance(overlay.get("retrieval_scores"), dict) else {}
    rerank_margin = as_float(retrieval_scores.get("rerank_margin"), 0.0)
    competitor_token_hits = as_float(retrieval_scores.get("competitor_token_hits"), 0.0)

    ev_definition_score = as_float(ev.get("definition_score"), 0.0)
    ev_scope_score = as_float(ev.get("scope_score"), 0.0)

    profile_definition_score = as_float(support_profile.get("definition_anchor_score"), 0.0)
    profile_explanatory_score = as_float(support_profile.get("explanatory_anchor_score"), 0.0)
    profile_context_score = as_float(support_profile.get("context_completion_score"), 0.0)
    profile_formula_score = as_float(support_profile.get("formula_support_score"), 0.0)

    definition_strength = max(ev_definition_score, profile_definition_score)
    scope_strength = max(ev_scope_score, profile_explanatory_score, profile_context_score)

    flags = []

    if negated_target(combined_for_relevance, canonical, aliases):
        flags.append("negated_target_or_sibling_contrast")

    if is_question_or_exercise(quote_text):
        flags.append("question_or_exercise_prompt")

    if contamination_risk == "high":
        flags.append("high_contamination_risk")

    if contamination_signals:
        flags.append("contamination_signals_present")

    if rerank_margin < 0:
        flags.append("negative_rerank_margin")

    if role_ambiguous:
        flags.append("ambiguous_role_hint")

    if bool(support_profile.get("fragmentary_surface")):
        flags.append("fragmentary_surface")

    if bool(support_profile.get("source_block_completion_used")):
        flags.append("source_block_completion_used")

    if bool(support_profile.get("needs_context_completion")):
        flags.append("needs_context_completion")

    if bool(support_profile.get("formula_auxiliary_only")) or safe_role_hint == "equation" or top_role == "equation":
        flags.append("formula_or_equation_like")

    target_score = as_float(relevance["target_relevance_score"], 0.0)
    subject_hit_count = len(relevance["subject_hits"])
    abbrev_hit_count = len(relevance["abbrev_hits"])

    relevance_ok = (
        target_score >= 2.0
        or subject_hit_count >= 1
        or abbrev_hit_count >= 1
    )

    strong_target_relevance = (
        target_score >= 4.0
        or subject_hit_count >= 2
        or abbrev_hit_count >= 1
    )

    high_risk = (
        "negated_target_or_sibling_contrast" in flags
        or "question_or_exercise_prompt" in flags
        or (
            contamination_risk == "high"
            and rerank_margin < 0
            and not strong_target_relevance
        )
        or (
            competitor_token_hits > 0
            and not strong_target_relevance
        )
    )

    if "negated_target_or_sibling_contrast" in flags:
        lane = "sibling_contrast"
        lane_reason = "target appears in negated or contrastive relation"
    elif "question_or_exercise_prompt" in flags:
        lane = "quarantine_or_irrelevant"
        lane_reason = "exercise/question prompt is not declarative KC evidence"
    elif not relevance_ok:
        lane = "quarantine_or_irrelevant"
        lane_reason = "insufficient lexical relevance to target KC"
    elif high_risk:
        lane = "quarantine_or_irrelevant"
        lane_reason = "high contamination or competitor risk without enough target relevance"
    elif definition_strength >= max(4.0, scope_strength - 0.5) and (
        safe_role_hint == "definition"
        or preferred_support_role == "definitional_anchor"
        or "definitional_anchor" in support_roles
    ):
        lane = "definition_candidate"
        lane_reason = "definition-like support with target relevance"
    elif scope_strength >= 3.5 or preferred_support_role in {"explanatory_anchor", "context_completion_anchor"}:
        lane = "scope_candidate"
        lane_reason = "explanatory or contextual support with target relevance"
    elif profile_formula_score >= 5.0:
        lane = "formula_or_parameter_candidate"
        lane_reason = "formula or parameter support with target relevance"
    else:
        lane = "context_candidate"
        lane_reason = "target-relevant context, but not strong enough for definition or scope"

    return {
        "lane": lane,
        "lane_reason": lane_reason,
        "flags": flags,
        "quote_text": quote_text,
        "context_text": short(context_text, 1600),
        "model_text": short(context_text if len(context_text) > len(quote_text) else quote_text, 1600),
        "target_relevance": relevance,
        "scores": {
            "packet_definition_score": ev_definition_score,
            "packet_scope_score": ev_scope_score,
            "profile_definition_anchor_score": profile_definition_score,
            "profile_explanatory_anchor_score": profile_explanatory_score,
            "profile_context_completion_score": profile_context_score,
            "profile_formula_support_score": profile_formula_score,
            "rerank_margin": rerank_margin,
            "competitor_token_hits": competitor_token_hits,
        },
        "role_metadata": {
            "packet_role_hints": ev.get("role_hints"),
            "packet_risk_hints": ev.get("risk_hints"),
            "preferred_support_role": preferred_support_role,
            "support_roles": support_roles,
            "safe_role_hint": safe_role_hint,
            "top_role": top_role,
            "role_ambiguous": role_ambiguous,
            "contamination_risk": contamination_risk,
            "contamination_signals": contamination_signals,
        },
    }


def main() -> None:
    packets = load_jsonl(PACKETS_PATH)
    overlay_rows = load_jsonl(OVERLAY_PATH)

    overlay_by_kc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in overlay_rows:
        overlay_by_kc[str(row.get("kc_id") or "")].append(row)

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    lane_packets = []
    lane_counter = Counter()
    flag_counter = Counter()

    for packet in packets:
        kc_id = str(packet.get("kc_id") or "")
        evidence = packet.get("evidence") if isinstance(packet.get("evidence"), list) else []

        lane_items = []
        for idx, ev in enumerate(evidence, start=1):
            if not isinstance(ev, dict):
                continue

            overlay = match_overlay(ev, overlay_by_kc.get(kc_id, []))
            lane_info = classify_lane(packet, ev, overlay)

            item = {
                "evidence_id": str(ev.get("evidence_id") or f"E{idx}"),
                "overlay_candidate_id": str(ev.get("overlay_candidate_id") or overlay.get("overlay_candidate_id") or ""),
                "source_candidate_index": ev.get("source_candidate_index"),
                "lane": lane_info["lane"],
                "lane_reason": lane_info["lane_reason"],
                "flags": lane_info["flags"],
                "quote_text": lane_info["quote_text"],
                "context_text": lane_info["context_text"],
                "model_text": lane_info["model_text"],
                "target_relevance": lane_info["target_relevance"],
                "scores": lane_info["scores"],
                "role_metadata": lane_info["role_metadata"],
                "provenance": {
                    "packet_provenance": ev.get("provenance"),
                    "doc_id": overlay.get("doc_id"),
                    "page_index": overlay.get("page_index"),
                    "patch_heading": overlay.get("patch_heading"),
                    "quote_verified": overlay.get("quote_verified"),
                    "quote_verification_status": overlay.get("quote_verification_status"),
                },
            }

            lane_counter[item["lane"]] += 1
            flag_counter.update(item["flags"])
            lane_items.append(item)

        definition_lane = [
            x for x in lane_items
            if x["lane"] in {"definition_candidate", "formula_or_parameter_candidate"}
        ]
        scope_lane = [
            x for x in lane_items
            if x["lane"] in {"scope_candidate", "context_candidate"}
        ]
        quarantine_lane = [
            x for x in lane_items
            if x["lane"] in {"quarantine_or_irrelevant", "sibling_contrast"}
        ]

        lane_packet = {
            "lane_packet_contract_version": "step67a_field_lane_packets_v1",
            "source_packets_path": PACKETS_PATH.as_posix(),
            "source_overlay_path": OVERLAY_PATH.as_posix(),
            "kc_id": kc_id,
            "canonical_name": packet.get("canonical_name"),
            "aliases": packet.get("aliases") or [],
            "seed_definition": packet.get("seed_definition"),
            "seed_definition_is_not_evidence": packet.get("seed_definition_is_not_evidence", True),
            "topic_path_labels": packet.get("topic_path_labels") or [],
            "query_text": packet.get("query_text"),
            "support_pack_summary": packet.get("support_pack_summary"),
            "review_queue_aux": packet.get("review_queue_aux"),
            "all_evidence": lane_items,
            "definition_lane": definition_lane,
            "scope_lane": scope_lane,
            "quarantine_lane": quarantine_lane,
            "lane_counts": dict(Counter(x["lane"] for x in lane_items)),
            "packet_sha256": sha256_text(json.dumps(lane_items, sort_keys=True, ensure_ascii=False)),
        }
        lane_packets.append(lane_packet)

    jsonl_path = out_dir / "lane_packets.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in lane_packets:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "stage": "step67a_build_field_lane_packets",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "packets_path": PACKETS_PATH.as_posix(),
        "overlay_path": OVERLAY_PATH.as_posix(),
        "out_dir": out_dir.as_posix(),
        "lane_packets_path": jsonl_path.as_posix(),
        "packet_count": len(lane_packets),
        "lane_counter": dict(lane_counter),
        "flag_counter": dict(flag_counter),
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md = []
    md.append("# Step 6.7A field-lane packet audit")
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append("```json")
    md.append(json.dumps(summary, indent=2, ensure_ascii=False))
    md.append("```")
    md.append("")

    for row in lane_packets:
        md.append(f"## {row['kc_id']} | {row['canonical_name']}")
        md.append("")
        md.append(f"- lane_counts: `{row['lane_counts']}`")
        md.append(f"- definition_lane_count: `{len(row['definition_lane'])}`")
        md.append(f"- scope_lane_count: `{len(row['scope_lane'])}`")
        md.append(f"- quarantine_lane_count: `{len(row['quarantine_lane'])}`")
        md.append("")

        for lane_name in ("definition_lane", "scope_lane", "quarantine_lane"):
            md.append(f"### {lane_name}")
            items = row[lane_name]
            if not items:
                md.append("")
                md.append("_empty_")
                md.append("")
                continue

            for item in items:
                md.append("")
                md.append(f"#### {item['evidence_id']} | {item['lane']}")
                md.append(f"- overlay_candidate_id: `{item['overlay_candidate_id']}`")
                md.append(f"- reason: `{item['lane_reason']}`")
                md.append(f"- flags: `{item['flags']}`")
                md.append(f"- relevance: `{item['target_relevance']}`")
                md.append(f"- scores: `{item['scores']}`")
                md.append(f"- role_metadata: `{item['role_metadata']}`")
                md.append(f"- provenance: `{item['provenance']}`")
                md.append(f"- quote_text: {short(item['quote_text'], 700)}")
                md.append(f"- model_text: {short(item['model_text'], 1000)}")
            md.append("")

    md_path = out_dir / "lane_audit.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print("STEP67A_LANE_RUN_ID =", run_id)
    print("STEP67A_LANE_DIR =", out_dir.as_posix())
    print("STEP67A_LANE_PACKETS =", jsonl_path.as_posix())
    print("STEP67A_LANE_SUMMARY =", summary_path.as_posix())
    print("STEP67A_LANE_AUDIT_MD =", md_path.as_posix())
    print("packet_count =", len(lane_packets))
    print("lane_counter =", json.dumps(dict(lane_counter), indent=2, ensure_ascii=False))
    print("flag_counter =", json.dumps(dict(flag_counter), indent=2, ensure_ascii=False))
    print("STEP67A_FIELD_LANE_PACKETS_DONE")


if __name__ == "__main__":
    main()
