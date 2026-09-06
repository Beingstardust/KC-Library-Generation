from __future__ import annotations

import re
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

TOPIC_HINTS: dict[str, list[str]] = {
    "Data Mining": ["DM I"],
    "Classification": ["Block Classification"],
    "Classification Underpinnings": [
        "Underpinnings",
        "Phases of Classification",
        "The two phases of classification",
    ],
    "Decision Trees": ["Unit Decision Trees"],
    "Naive Bayes": ["Unit Naive Bayes"],
    "Model Evaluation and Model Comparison": [
        "Classifier Evaluation",
        "Finding the best model",
        "Good model, best model",
    ],
    "Classifier Evaluation Basics": [
        "Classifier Evaluation",
        "Evaluation workflow",
        "Confusion matrix",
    ],
    "Sampling for Testing": ["Sampling for testing"],
    "Ensemble Methods": [
        "Combining classifiers into an ensemble",
        "Combining classifiers",
    ],
    "Class Imbalance": ["Imbalanced classes"],
    "Finding the Best Model": ["Unit 2: Finding the best model", "Good model, best model"],
    "Clustering": ["Data Mining Block Clustering"],
    "Clustering Concepts": ["Clustering", "Different types of clusters", "Clustering algorithms"],
    "Similarity and Distance Functions": ["Similarity functions"],
    "K-Means Family": ["K-Means family"],
    "Hierarchical Clustering": [
        "Hierarchical clustering",
        "This is a family of methods that processes your data to return a tree of clusters",
    ],
    "Density-Based Clustering (DBSCAN)": [
        "Density-based clustering",
        "This is a family of methods that defines a cluster as a set of overlapping neighbourhoods",
        "DBSCAN",
    ],
    "Cluster Evaluation": ["Evaluation in Clustering", "Learn to recognize bad clusters"],
    "Data Engineering - Feature Selection": [
        "BLOCK Data Engineering - Unit 3 on Feature Selection",
        "Feature Selection",
    ],
    "Feature Selection Fundamentals": [
        "Feature Selection: What and Why",
        "Feature selection is a process that chooses the optimal subset of features",
    ],
    "Feature Set Generation Algorithms": [
        "Sequential forward and backward feature set generation algorithms",
        "Bidirectional feature set generation algorithm",
        "Random feature set generation",
        "feature set construction algorithms",
    ],
    "Goodness Criteria": ["Goodness Criteria"],
    "Filters and Wrappers": ["Filters & Wrappers", "filter the good from the no-good features"],
    "Statistical Testing": ["Statistical Testing", "Examples of Null Hypotheses"],
}

DEFINITION_PATTERNS = (
    " is a ",
    " is the ",
    " refers to ",
    " takes as input ",
    " builds a ",
    " chooses the ",
    " defines a cluster as ",
    " family of methods",
    " family of mining algorithms",
)

TOPIC_DRAFT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Minimal Topic Draft",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "topic_id",
        "topic_title",
        "topic_level",
        "parent_topic_id",
        "draft_definition",
        "draft_scope_role",
        "outline_children",
        "source_refs",
        "source_units",
        "draft_flags",
    ],
    "properties": {
        "topic_id": {"type": "string"},
        "topic_title": {"type": "string"},
        "topic_level": {"type": "integer", "minimum": 1},
        "parent_topic_id": {"type": ["string", "null"]},
        "draft_definition": {"type": "string"},
        "draft_scope_role": {"type": "string"},
        "outline_children": {"type": "array", "items": {"type": "string"}},
        "source_refs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["doc_id", "page_index", "block_id", "support_kind", "excerpt"],
                "properties": {
                    "doc_id": {"type": "string"},
                    "page_index": {"type": "integer", "minimum": 0},
                    "block_id": {"type": "string"},
                    "support_kind": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
            },
        },
        "source_units": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["doc_id", "unit_title"],
                "properties": {
                    "doc_id": {"type": "string"},
                    "unit_title": {"type": "string"},
                },
            },
        },
        "draft_flags": {"type": "array", "items": {"type": "string"}},
    },
}


def _normalize_text(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-")
    return re.sub(r"\s+", " ", text.strip().lower())


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize_text(text)).strip("-") or "topic"


def _topic_id(path: list[str]) -> str:
    return "topic::" + "/".join(_slugify(part) for part in path)


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_text(text))
        if token not in STOPWORDS and len(token) > 1
    }


def _clean_excerpt(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-")
    text = re.sub(r"[\x00-\x1f]", " ", text)
    return re.sub(r"\s+", " ", text.strip())


def _is_noise_like(text: str) -> bool:
    text_norm = _normalize_text(text)
    if not text_norm:
        return True
    noise_markers = [
        "book:",
        "springer",
        "literature of the unit",
        "faculty of computer science",
    ]
    return any(marker in text_norm for marker in noise_markers)


def _is_footer_like(block: dict[str, Any]) -> bool:
    text = _normalize_text(str(block.get("text_raw", "")))
    return not text or "myra spiliopoulou" in text or "···" in text or bool(re.search(r"\b\d+/\d+\b", text))


def _classify_support_kind(block: dict[str, Any], alias_norms: list[str]) -> str:
    text = _normalize_text(str(block.get("text_raw", "")))
    raw_text = str(block.get("text_raw", ""))
    page_index = int(block.get("page_index", 0))
    if page_index == 0 and ("unit" in text or "block" in text or "dm i" in text):
        return "unit_header"
    if page_index in (0, 1, 2) and raw_text.count("\n") >= 2:
        return "agenda"
    if any(pattern in text for pattern in DEFINITION_PATTERNS):
        return "definition"
    if any(alias in text for alias in alias_norms) and len(raw_text.splitlines()) <= 3 and len(text) <= 160:
        return "section_title"
    return "body_excerpt"


def _score_block(block: dict[str, Any], alias_norms: list[str]) -> tuple[int, bool]:
    raw_text = str(block.get("text_raw", ""))
    text_norm = _normalize_text(raw_text)
    if _is_footer_like(block) or _is_noise_like(raw_text):
        return 0, False
    text_tokens = _meaningful_tokens(text_norm)
    best = 0
    used_hint = False
    for index, alias in enumerate(alias_norms):
        alias_tokens = _meaningful_tokens(alias)
        if not alias_tokens:
            continue
        score = 0
        if alias in text_norm:
            score = 12 + min(len(alias_tokens), 3)
        else:
            overlap = len(alias_tokens & text_tokens)
            if overlap == len(alias_tokens):
                score = 8 + overlap
            elif overlap >= 2:
                score = 4 + overlap
        if score > best:
            best = score
            used_hint = index > 0
    if best == 0:
        return 0, False
    page_index = int(block.get("page_index", 0))
    if page_index == 0:
        best += 3
    elif page_index in (1, 2):
        best += 2
    support_kind = _classify_support_kind(block, alias_norms)
    if support_kind == "definition":
        best += 4
    elif support_kind == "section_title":
        best += 2
    elif support_kind == "unit_header":
        best += 1
    elif support_kind == "body_excerpt" and raw_text.count("\n") >= 4:
        best -= 2
    return best, used_hint


def _extract_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_excerpt(raw_line)
        if not line or re.fullmatch(r"\d+", line) or _is_noise_like(line):
            continue
        out.append(line)
    return out


def _first_sentence(text: str) -> str:
    text = _clean_excerpt(text)
    match = re.search(r"(.+?[.!?])(\s|$)", text)
    return match.group(1).strip() if match else text


def _unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = _normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _select_source_refs(topic: dict[str, Any], blocks_by_doc: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], bool]:
    aliases = [topic["label"], *TOPIC_HINTS.get(topic["label"], [])]
    alias_norms = [_normalize_text(alias) for alias in aliases if alias]
    ranked: list[dict[str, Any]] = []
    used_hint = False
    for doc_id, blocks in blocks_by_doc.items():
        for block in blocks:
            score, block_used_hint = _score_block(block, alias_norms)
            if score < 6:
                continue
            excerpt = _clean_excerpt(str(block.get("text_raw", "")))
            if len(excerpt) < 3 or _is_noise_like(excerpt):
                continue
            ranked.append(
                {
                    "doc_id": doc_id,
                    "page_index": int(block.get("page_index", 0)),
                    "block_id": str(block.get("block_id", "")),
                    "support_kind": _classify_support_kind(block, alias_norms),
                    "excerpt": excerpt,
                    "_score": score,
                }
            )
            used_hint = used_hint or block_used_hint
    ranked.sort(key=lambda row: (-row["_score"], row["page_index"], row["block_id"]))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for row in ranked:
        key = (row["doc_id"], row["page_index"], _normalize_text(row["excerpt"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append({k: v for k, v in row.items() if k != "_score"})
        if len(deduped) >= 8:
            break
    return deduped, used_hint


def _build_source_units(source_refs: list[dict[str, Any]], doc_titles: dict[str, str]) -> list[dict[str, str]]:
    ordered_doc_ids = _unique_preserve([ref["doc_id"] for ref in source_refs])
    return [{"doc_id": doc_id, "unit_title": doc_titles.get(doc_id, doc_id)} for doc_id in ordered_doc_ids]


def _collect_outline_lines(source_refs: list[dict[str, Any]], aliases: list[str]) -> list[str]:
    alias_norms = {_normalize_text(alias) for alias in aliases}
    candidates: list[str] = []
    for ref in source_refs:
        if ref["support_kind"] not in {"agenda", "section_title", "body_excerpt"}:
            continue
        for line in _extract_lines(ref["excerpt"]):
            line_norm = _normalize_text(line)
            if line_norm in alias_norms:
                continue
            if len(line.split()) > 10:
                continue
            candidates.append(line)
    return _unique_preserve(candidates)


def _select_definition(source_refs: list[dict[str, Any]], topic_title: str) -> str:
    title_norm = _normalize_text(topic_title)
    for ref in source_refs:
        if ref["support_kind"] != "definition":
            continue
        sentence = _first_sentence(ref["excerpt"])
        if _normalize_text(sentence) == title_norm or _is_noise_like(sentence):
            continue
        return sentence
    return ""


def _build_scope_role(source_refs: list[dict[str, Any]], source_units: list[dict[str, str]], aliases: list[str]) -> str:
    outline_lines = _collect_outline_lines(source_refs, aliases)
    if outline_lines:
        return "Grounded slide scope: " + "; ".join(outline_lines[:5]) + "."
    if source_units:
        titles = [unit["unit_title"] for unit in source_units if unit["unit_title"]]
        if titles:
            return "Grounded source units: " + "; ".join(titles[:5]) + "."
    return ""


def _branch_label_mismatch(topic: dict[str, Any], source_units: list[dict[str, str]]) -> bool:
    path = list(topic.get("source_hierarchy_path", []))
    if len(path) < 3 or not source_units:
        return False
    branch_tokens = _meaningful_tokens(path[1])
    source_tokens = _meaningful_tokens(" ".join(unit["unit_title"] for unit in source_units))
    return bool(branch_tokens and source_tokens and branch_tokens.isdisjoint(source_tokens))


def build_topic_draft_bundle(
    overlay_rows: list[dict[str, Any]],
    blocks_by_doc: dict[str, list[dict[str, Any]]],
    doc_titles: dict[str, str],
    approved_kc_titles: dict[str, str],
) -> dict[str, Any]:
    topic_rows = [row for row in overlay_rows if row.get("node_type") == "topic"]
    topic_rows.sort(key=lambda row: (int(row.get("depth_overlay", 0)), row.get("source_hierarchy_path", [])))
    topic_by_hier = {row["hier_node_id"]: row for row in topic_rows}
    child_topics: dict[str, list[dict[str, Any]]] = {}
    for row in topic_rows:
        parent_id = row.get("parent_hier_node_id")
        if parent_id and parent_id in topic_by_hier:
            child_topics.setdefault(parent_id, []).append(row)

    topic_drafts: list[dict[str, Any]] = []
    link_candidates: list[dict[str, Any]] = []
    overlap_examples: list[dict[str, str]] = []

    for topic in topic_rows:
        path = list(topic["source_hierarchy_path"])
        aliases = [topic["label"], *TOPIC_HINTS.get(topic["label"], [])]
        source_refs, used_hint = _select_source_refs(topic, blocks_by_doc)
        source_units = _build_source_units(source_refs, doc_titles)
        child_labels = [child["label"] for child in child_topics.get(topic["hier_node_id"], [])]
        outline_children = child_labels or _collect_outline_lines(source_refs, aliases)[:6]
        draft_definition = _select_definition(source_refs, topic["label"])
        draft_scope_role = _build_scope_role(source_refs, source_units, aliases)
        if int(topic["depth_overlay"]) == 1 and source_units:
            draft_scope_role = "Grounded source units: " + "; ".join(unit["unit_title"] for unit in source_units[:6]) + "."
        support_kinds = _unique_preserve([ref["support_kind"] for ref in source_refs])
        flags = [f"support_{kind}" for kind in support_kinds]
        flags.append("definition_grounded" if draft_definition else "definition_missing")
        flags.append("scope_role_grounded" if draft_scope_role else "scope_role_missing")
        if len(source_units) > 1:
            flags.append("cross_unit_aggregate")
        if used_hint:
            flags.append("alias_hint_support")
        if _branch_label_mismatch(topic, source_units):
            flags.append("source_branch_label_mismatch")
        if source_refs and set(support_kinds) <= {"unit_header"}:
            flags.append("title_only_support")

        topic_id = _topic_id(path)
        parent_id = None
        parent_hier_id = topic.get("parent_hier_node_id")
        if parent_hier_id and parent_hier_id in topic_by_hier:
            parent_id = _topic_id(list(topic_by_hier[parent_hier_id]["source_hierarchy_path"]))

        topic_drafts.append(
            {
                "topic_id": topic_id,
                "topic_title": topic["label"],
                "topic_level": int(topic["depth_overlay"]),
                "parent_topic_id": parent_id,
                "draft_definition": draft_definition,
                "draft_scope_role": draft_scope_role,
                "outline_children": outline_children,
                "source_refs": source_refs,
                "source_units": source_units,
                "draft_flags": _unique_preserve(flags),
            }
        )

        approved_descendants = sorted({kc_id for kc_id in topic.get("descendant_kc_ids", []) if kc_id in approved_kc_titles})
        for kc_id in approved_descendants:
            link_candidates.append(
                {
                    "link_type": "topic_contains_approved_kc_candidate",
                    "topic_id": topic_id,
                    "topic_title": topic["label"],
                    "kc_id": kc_id,
                    "kc_title": approved_kc_titles[kc_id],
                    "basis": "hierarchy_overlay_descendant_membership",
                    "approved_kc_only": True,
                }
            )
        for kc_id in approved_descendants:
            kc_title = approved_kc_titles[kc_id]
            if _meaningful_tokens(topic["label"]) & _meaningful_tokens(kc_title):
                overlap_examples.append(
                    {
                        "topic_title": topic["label"],
                        "kc_id": kc_id,
                        "kc_title": kc_title,
                    }
                )
                break

    weak_count = sum(1 for row in topic_drafts if "title_only_support" in row["draft_flags"])
    definition_count = sum(1 for row in topic_drafts if row["draft_definition"])
    scope_only_count = sum(1 for row in topic_drafts if (not row["draft_definition"] and row["draft_scope_role"]))

    return {
        "schema": TOPIC_DRAFT_SCHEMA,
        "drafts": topic_drafts,
        "link_candidates": link_candidates,
        "stats": {
            "topic_draft_count": len(topic_drafts),
            "grounded_definition_count": definition_count,
            "scope_only_count": scope_only_count,
            "weak_title_only_count": weak_count,
            "source_unit_count": len(doc_titles),
        },
        "coverage": {
            "topic_paths": [" > ".join(row["source_hierarchy_path"]) for row in topic_rows],
            "source_doc_ids": sorted(doc_titles.keys()),
            "overlap_examples": overlap_examples[:8],
        },
    }

