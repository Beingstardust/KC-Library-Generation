"""Step 5x-F source-bound evidence pack finalizer.

This module converts a Step 5x evidence pack into a compact, draft-facing,
source-window-completed evidence pack while preserving review/excluded evidence
for audit. It is intentionally stdlib-only and schema-light.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

FINALIZER_CONTRACT_VERSION = "step5xf_source_bound_pack_finalizer_v2_core_binding_20260516"
DRAFT_ROLES = ["core", "explanation", "formula_or_procedure", "example_or_boundary", "bridge_context"]
HARD_RISK_FLAGS = {
    "reference_like",
    "bibliography_like",
    "meta_guidance",
    "caption_like",
    "suspected_false_positive",
    "fake_formula_prose",
    "source_kc_mismatch",
    "sibling_competitor_dominant",
    "rejected_false_positive",
    "source_branch_mismatch",
    "not_admitted_to_ordered_pack_for_drafting",
}
SOFT_RISK_FLAGS = {
    "needs_stronger_anchor_context",
    "broad_topic_only",
    "fragmentary",
    "example_like",
    "heading_like",
    "procedure_like",
    "definition_subject_mismatch",
    "formula_without_target_binding",
    "no_target_binding",
    "candidate_pool_membership_only",
    "recurring_global_candidate",
}
STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "onto", "that", "this", "these", "those",
    "will", "would", "could", "should", "using", "used", "uses", "use", "data", "model", "models",
    "method", "methods", "approach", "approaches", "phase", "process", "classification", "clustering",
    "evaluation", "feature", "selection", "learning", "algorithm", "algorithms", "value", "values",
    "test", "training", "instance", "instances", "class", "labels", "label", "problem", "problems",
    "different", "given", "called", "known", "also", "such", "therefore", "because", "where",
}
# Branch tokens must be derived from registry/profile/source-confirmed role targets.
# Do not hardcode course-domain vocabulary in generic finalizer code.
BRANCH_TOKENS: set[str] = set()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                obj.setdefault("_source_jsonl_line_index", idx)
                rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, obj: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(obj), indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).split())


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def string_list(value: Any) -> List[str]:
    out: List[str] = []
    for item in as_list(value):
        text = as_text(item)
        if text:
            out.append(text)
    return unique(out)


def unique(values: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z][A-Za-z0-9+-]*", text.lower()) if len(t) >= 3 and t not in STOPWORDS}


def normalized_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def item_text(item: Mapping[str, Any]) -> str:
    for key in ["completed_evidence_text", "source_window_text", "text", "quote", "candidate_text", "sentence_text", "primary_text"]:
        value = as_text(item.get(key))
        if value:
            return value
    return ""


def item_anchor_text(item: Mapping[str, Any]) -> str:
    for key in ["anchor_text", "quote", "text", "candidate_text", "sentence_text", "primary_text"]:
        value = as_text(item.get(key))
        if value:
            return value
    return ""


def nested_values(obj: Any, wanted_keys: set[str]) -> List[Any]:
    out: List[Any] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k in wanted_keys and v not in (None, "", []):
                out.append(v)
            out.extend(nested_values(v, wanted_keys))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(nested_values(v, wanted_keys))
    return out


def first_nested_value(obj: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        if k in obj and obj[k] not in (None, "", []):
            return obj[k]
    vals = nested_values(obj, set(keys))
    return vals[0] if vals else None


def profile_terms(profile: Mapping[str, Any]) -> List[str]:
    terms: List[str] = []
    for key in [
        "aliases", "expanded_aliases", "source_equivalent_terms", "deterministic_label_variants",
        "normalized_surface_variants", "query_variants", "topic_path_labels", "route_specific_required_terms",
        "route_specific_optional_terms", "route_specific_query_variants",
    ]:
        val = profile.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    terms.append(item)
                elif isinstance(item, Mapping):
                    for vv in item.values():
                        if isinstance(vv, str):
                            terms.append(vv)
                        elif isinstance(vv, list):
                            terms.extend(as_text(x) for x in vv if as_text(x))
    for cue in as_list(profile.get("accepted_source_cues")):
        if isinstance(cue, Mapping):
            terms.append(as_text(cue.get("term")))
    for term in as_list(profile.get("active_query_terms")):
        if isinstance(term, Mapping):
            terms.append(as_text(term.get("term")))
    return unique([t for t in terms if t])

def role_target_controls(profile: Mapping[str, Any], item: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    item = item or {}
    row_guidance = item.get("step5p_role_target_guidance") if isinstance(item.get("step5p_role_target_guidance"), Mapping) else {}
    role_targets = as_list(row_guidance.get("role_targets") if row_guidance else profile.get("role_targets"))
    branch_policy = row_guidance.get("branch_policy") if row_guidance else profile.get("branch_policy")
    coverage_goals = row_guidance.get("coverage_goals") if row_guidance else profile.get("coverage_goals")
    return {
        "role_targets": [dict(x) for x in role_targets if isinstance(x, Mapping)],
        "branch_policy": dict(branch_policy or {}) if isinstance(branch_policy, Mapping) else {},
        "coverage_goals": dict(coverage_goals or {}) if isinstance(coverage_goals, Mapping) else {},
    }


def _role_target_terms(
    role_targets: Sequence[Mapping[str, Any]],
    *,
    roles: set[str] | None = None,
    scopes: set[str] | None = None,
) -> List[str]:
    out: List[str] = []
    for target in role_targets:
        role = as_text(target.get("target_role"))
        scope = as_text(target.get("support_scope"))
        if roles is not None and role not in roles:
            continue
        if scopes is not None and scope not in scopes:
            continue
        for key in ["active_terms_any", "required_terms_any", "support_terms_any"]:
            out.extend(string_list(target.get(key)))
    return unique(out)




def registry_by_id(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        kid = as_text(row.get("kc_id") or row.get("knowledge_unit_id") or row.get("node_id"))
        if kid:
            out[kid] = dict(row)
    return out


def profiles_by_id(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        kid = as_text(row.get("kc_id") or row.get("knowledge_unit_id") or row.get("node_id"))
        if kid:
            out[kid] = dict(row)
    return out


def row_kc_id(row: Mapping[str, Any]) -> str:
    return as_text(row.get("kc_id") or row.get("knowledge_unit_id") or row.get("target_kc_id"))


class SourceWindowIndex:
    def __init__(self, overlay_rows: Sequence[Mapping[str, Any]]) -> None:
        self.rows = [dict(r) for r in overlay_rows]
        self.by_sentence_id: Dict[str, int] = {}
        self.by_line_index: Dict[int, int] = {}
        self.by_doc_block_sent: Dict[Tuple[str, str, int], int] = {}
        for idx, row in enumerate(self.rows):
            sid = as_text(row.get("sentence_id"))
            if sid:
                self.by_sentence_id[sid] = idx
            self.by_line_index[idx] = idx
            doc_id = as_text(row.get("doc_id"))
            block_id = as_text(row.get("block_id"))
            try:
                sent_idx = int(row.get("sent_idx"))
            except Exception:
                sent_idx = -1
            if doc_id and block_id and sent_idx >= 0:
                self.by_doc_block_sent[(doc_id, block_id, sent_idx)] = idx

    def locate(self, item: Mapping[str, Any]) -> Tuple[Optional[int], str]:
        # Prefer numeric source_row_index because sentence_id is not globally unique
        # across extraction layers in this corpus. This was the failure mode that
        # produced unrelated context windows for otherwise correct evidence.
        for key in ["source_row_index", "row_index", "sentence_index", "global_sentence_index"]:
            value = first_nested_value(item, [key])
            if value is None:
                continue
            try:
                idx = int(value)
            except Exception:
                continue
            if idx in self.by_line_index:
                return self.by_line_index[idx], key
        sid = as_text(first_nested_value(item, ["sentence_id", "source_sentence_id", "evidence_sentence_id"]))
        if sid and sid in self.by_sentence_id:
            return self.by_sentence_id[sid], "sentence_id"
        doc_id = as_text(first_nested_value(item, ["doc_id"]))
        block_id = as_text(first_nested_value(item, ["block_id"]))
        try:
            sent_idx = int(first_nested_value(item, ["sent_idx"]))
        except Exception:
            sent_idx = -1
        if doc_id and block_id and sent_idx >= 0:
            idx = self.by_doc_block_sent.get((doc_id, block_id, sent_idx))
            if idx is not None:
                return idx, "doc_block_sent_idx"
        return None, "unresolved"

    def window(self, item: Mapping[str, Any], *, before: int = 2, after: int = 2, max_chars: int = 1200) -> Dict[str, Any]:
        idx, how = self.locate(item)
        if idx is None:
            return {
                "resolved": False,
                "resolved_by": how,
                "anchor_overlay_index": None,
                "rows": [],
                "source_window_text": item_text(item),
                "source_window_row_indices": [],
            }
        anchor = self.rows[idx]
        doc_id = as_text(anchor.get("doc_id"))
        patch_id = as_text(anchor.get("patch_id"))
        page_index = anchor.get("page_index")
        lo = max(0, idx - before)
        hi = min(len(self.rows), idx + after + 1)
        chosen: List[Tuple[int, Dict[str, Any]]] = []
        for j in range(lo, hi):
            row = self.rows[j]
            if as_text(row.get("doc_id")) != doc_id:
                continue
            # Prefer same patch when available. If patch is missing, same page is enough.
            same_patch = patch_id and as_text(row.get("patch_id")) == patch_id
            same_page = row.get("page_index") == page_index
            if patch_id and not same_patch and not same_page:
                continue
            text = as_text(row.get("sentence_text") or row.get("text") or row.get("raw_text"))
            if not text:
                continue
            if row.get("is_nav_boilerplate") or row.get("is_author_affiliation"):
                continue
            chosen.append((j, dict(row)))
        if not chosen:
            chosen = [(idx, dict(anchor))]
        heading = as_text(anchor.get("patch_heading") or anchor.get("page_heading_norm"))
        parts = []
        if heading:
            parts.append(f"Section: {heading}.")
        for _, row in chosen:
            text = as_text(row.get("sentence_text") or row.get("text") or row.get("raw_text"))
            if text and (not parts or text != parts[-1]):
                parts.append(text)
        window_text = " ".join(parts)
        if len(window_text) > max_chars:
            window_text = window_text[:max_chars].rsplit(" ", 1)[0] + " ..."
        return {
            "resolved": True,
            "resolved_by": how,
            "anchor_overlay_index": idx,
            "source_window_text": window_text,
            "source_window_row_indices": [j for j, _ in chosen],
            "anchor_source_row": anchor,
            "rows": [row for _, row in chosen],
        }


def shape_label(text: str) -> str:
    low = text.strip().lower()
    if not low:
        return "empty"
    if len(re.findall(r"[A-Za-z0-9]+", low)) < 8:
        return "too_short"
    if re.match(r"^(it|this|these|those|such|they|therefore|hence|thus|also|unlike|as in|as with|as before|as previously|as discussed|as shown|as stated|as described|in the previous|from the previous|it should be noted)\b", low):
        return "anaphoric_start"
    if re.match(r"^(figure|fig\.|table|algorithm|equation|eq\.|section)\s+\d", low):
        return "caption_or_pointer_start"
    return "self_contained_surface"


def is_reference_like(text: str) -> bool:
    low = text.lower()
    return bool(re.search(r"\b(proceedings|conference|journal|vol\.|pp\.|doi|springer|wiley|references|isbn|edited by|acm|ieee)\b", low))


def risk_flags(item: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    for key in ["risk_flags", "review_risk_flags"]:
        flags.extend(string_list(item.get(key)))
    admission = item.get("evidence_admission")
    if isinstance(admission, Mapping):
        flags.extend(string_list(admission.get("warnings")))
        flags.extend(string_list(admission.get("hard_reasons")))
    return unique(flags)


def binding_context(pack: Mapping[str, Any], profile: Mapping[str, Any], registry_row: Mapping[str, Any]) -> Dict[str, Any]:
    """Build token context for final evidence admission.

    v2 policy:
    - Label/profile/branch overlap is KC-specific binding.
    - Topic overlap alone is contextual only and cannot justify core evidence.
    - Short uppercase acronyms such as NB must be retained because many KC labels
      encode important branch constraints in acronyms.
    """
    label_terms = [
        as_text(pack.get("canonical_name") or profile.get("canonical_name") or registry_row.get("canonical_name") or registry_row.get("label")),
        *string_list(pack.get("aliases")),
        *string_list(profile.get("aliases")),
        *string_list(profile.get("expanded_aliases")),
    ]
    topic_terms = [
        *string_list(pack.get("topic_path_labels")),
        *string_list(profile.get("topic_path_labels")),
        as_text(pack.get("parent_topic_label") or profile.get("parent_topic_label")),
    ]
    source_terms = profile_terms(profile)

    def acronym_tokens(values: Iterable[str]) -> set[str]:
        out: set[str] = set()
        for value in values:
            for tok in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", value or ""):
                low = tok.lower()
                if low not in {"kc", "id"}:
                    out.add(low)
        return out

    label_token_set = tokens(" ".join(label_terms)) | acronym_tokens(label_terms)
    topic_token_set = tokens(" ".join(topic_terms)) | acronym_tokens(topic_terms)
    source_token_set = tokens(" ".join(source_terms)) | acronym_tokens(source_terms)

    controls = role_target_controls(profile)
    role_targets = controls.get("role_targets") or []
    branch_policy = controls.get("branch_policy") or {}
    branch_terms = [
        *string_list(branch_policy.get("branch_terms")),
        *_role_target_terms(
            role_targets,
            roles={"primary_core", "formula_or_procedure"},
            scopes={"branch_specific_core", "core_or_support"},
        ),
    ]
    generic_parent_terms = [
        *string_list(branch_policy.get("generic_parent_terms")),
        *_role_target_terms(
            role_targets,
            roles={"bridge_context"},
            scopes={"parent_or_generic_context"},
        ),
    ]

    branch_token_set = tokens(" ".join(branch_terms)) | acronym_tokens(label_terms + source_terms + branch_terms)
    generic_parent_token_set = tokens(" ".join(generic_parent_terms))

    return {
        "label_terms": unique([t for t in label_terms if t]),
        "topic_terms": unique([t for t in topic_terms if t]),
        "source_terms": unique([t for t in source_terms if t]),
        "label_tokens": label_token_set,
        "topic_tokens": topic_token_set,
        "source_tokens": source_token_set,
        "branch_tokens": branch_token_set,
        "generic_parent_tokens": generic_parent_token_set,
        "role_targets": role_targets,
        "branch_policy": branch_policy,
        "coverage_goals": controls.get("coverage_goals") or {},
    }


def infer_final_role(item: Mapping[str, Any], source_window_text: str, ctx: Mapping[str, Any], lane: str) -> Tuple[str, List[str]]:
    anchor = item_anchor_text(item)
    full_text = f"{anchor} {source_window_text}"
    low = full_text.lower()
    flags = risk_flags(item)
    reasons: List[str] = []
    source_toks = tokens(full_text)

    # Preserve two-character acronyms in evidence text too.
    source_acronyms = {tok.lower() for tok in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", full_text)}
    source_toks = source_toks | source_acronyms

    label_overlap = len(ctx["label_tokens"] & source_toks)
    topic_overlap = len(ctx["topic_tokens"] & source_toks)
    profile_overlap = len(ctx["source_tokens"] & source_toks)
    branch_required = set(ctx["branch_tokens"])
    branch_present = branch_required & source_toks
    generic_parent_present = set(ctx.get("generic_parent_tokens") or set()) & source_toks
    coverage_goals = ctx.get("coverage_goals") if isinstance(ctx.get("coverage_goals"), Mapping) else {}
    role_targets = [x for x in as_list(ctx.get("role_targets")) if isinstance(x, Mapping)]
    formula_core_expected = bool(
        coverage_goals.get("formula_or_procedure_expected")
        or any(as_text(x.get("target_role")) == "formula_or_procedure" for x in role_targets)
    )

    original_role = as_text(item.get("role"))
    completed_shape = shape_label(source_window_text)
    anchor_shape = shape_label(anchor)

    # Role signals should be read primarily from the anchor when the anchor is
    # already self-contained. The completed source window is context, not a
    # license to promote a neighboring row's formula/core signal onto this row.
    role_text = anchor if anchor_shape == "self_contained_surface" else full_text
    role_low = role_text.lower()

    anchor_toks = tokens(anchor) | {tok.lower() for tok in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", anchor)}
    anchor_label_overlap = len(ctx["label_tokens"] & anchor_toks)
    anchor_profile_overlap = len(ctx["source_tokens"] & anchor_toks)
    anchor_branch_present = set(ctx["branch_tokens"]) & anchor_toks
    anchor_generic_parent_present = set(ctx.get("generic_parent_tokens") or set()) & anchor_toks
    anchor_kc_specific_binding = bool(anchor_label_overlap or anchor_profile_overlap or anchor_branch_present)

    if is_reference_like(source_window_text) or any(f in HARD_RISK_FLAGS for f in flags):
        return "excluded", ["hard_risk_or_reference_like"]

    if not source_window_text.strip():
        return "excluded", ["empty_source_window"]

    if completed_shape in {"empty", "too_short", "anaphoric_start", "caption_or_pointer_start"}:
        return "excluded", [f"bad_completed_shape::{completed_shape}"]

    if anchor_shape in {"caption_or_pointer_start", "empty"} and completed_shape != "self_contained_surface":
        return "excluded", ["bad_anchor_shape"]

    kc_specific_binding = bool(label_overlap or profile_overlap or branch_present)
    topic_context_only = bool(topic_overlap and not kc_specific_binding)

    if not (kc_specific_binding or topic_overlap):
        return "excluded", ["low_binding_no_label_profile_or_topic_overlap"]

    # Topic/generic-parent-only evidence is allowed as bridge context, never as core.
    if topic_context_only:
        return "bridge_context", ["topic_context_only_not_core"]
    # If the anchor itself is generic parent context, weak label overlap such
    # as "rule", "phase", "model", or "method" is not enough to make it core.
    # It must overlap source-confirmed profile/role-target terms. This keeps
    # runtime Step5p outputs domain/unit-specific while generic code remains
    # domain-agnostic.
    if anchor_generic_parent_present and not anchor_profile_overlap:
        return "bridge_context", ["anchor_generic_parent_context_without_source_confirmed_profile_binding"]
    if anchor_generic_parent_present and not anchor_kc_specific_binding:
        return "bridge_context", ["anchor_generic_parent_context_without_kc_binding"]
    if generic_parent_present and not kc_specific_binding:
        return "bridge_context", ["generic_parent_context_without_kc_binding"]

    # Branch-specific KCs must not treat parent evidence as core when branch tokens are absent.
    if branch_required and not branch_present and topic_overlap and not (label_overlap or profile_overlap):
        return "bridge_context", ["branch_specific_terms_absent_parent_or_bridge_context_only"]

    formula_signal = bool(re.search(r"[=∑Σ∏πλρσμ]|\bp\s*\(|\blog\b|\bprobability\b|\bdistance\b|\bratio\b|\bcoefficient\b|\bequation\b|\bmetric\b|\bscore\b", role_low))
    procedure_signal = bool(re.search(r"\b(algorithm|step|repeat|until|assign|compute|select|remove|add|initialize|return|appl(?:y|ies|ied|ying)|predict)\b", role_low))
    definition_signal = bool(re.search(r"\b(is|are|refers to|defined as|known as|called|denotes|measures|computed as|given by)\b", role_low))
    example_signal = bool(re.search(r"\b(example|for instance|consider|illustrates|figure|table|contrast|unlike|limitation|advantage|disadvantage)\b", role_low))

    if formula_signal:
        if formula_core_expected and kc_specific_binding:
            return "core", reasons or ["formula_signal_satisfies_role_target_core"]
        return "formula_or_procedure", reasons or ["formula_or_metric_signal_with_kc_binding"]

    if original_role in {"formula_notation", "formula_or_algorithm_support"}:
        if formula_core_expected and kc_specific_binding:
            return "core", reasons or ["source_role_formula_satisfies_role_target_core"]
        return "formula_or_procedure", reasons or ["source_role_formula_with_kc_binding"]

    if original_role in {"definition_kernel", "definition_anchor", "core"}:
        if kc_specific_binding:
            return "core", reasons or ["source_role_core_with_kc_specific_binding"]
        return "bridge_context", reasons or ["source_role_core_demoted_topic_only"]

    if definition_signal and kc_specific_binding:
        return "core", reasons or ["definition_cue_with_kc_specific_binding"]

    if procedure_signal:
        if original_role in {"procedure", "process_or_procedure"}:
            return "formula_or_procedure", reasons or ["operational_signal_with_kc_binding"]
        return "explanation", reasons or ["operational_explanation_with_kc_binding"]

    if example_signal:
        return "example_or_boundary", reasons or ["example_or_boundary_signal_with_kc_binding"]

    if lane in {"auxiliary_evidence", "near_miss_review_items", "review_needed_evidence"}:
        return "bridge_context", reasons or ["non_core_lane_bridge_context"]

    return "explanation", reasons or ["default_explanation_with_kc_binding"]


def evidence_identity(item: Mapping[str, Any], text: str) -> List[str]:
    """Return stable evidence identities for deduplication.

    Source-window-completed items can share identical completed text when their
    anchors are adjacent. Therefore text identity must not collapse different
    candidate/source-row anchors when stable IDs exist.
    """
    ids: List[str] = []
    for key in [
        "candidate_id",
        "source_candidate_id",
        "stage2_candidate_id",
        "scored_candidate_id",
        "sentence_id",
        "source_row_id",
        "source_row_index",
        "row_index",
        "global_sentence_index",
    ]:
        val = as_text(first_nested_value(item, [key]))
        if val:
            ids.append(f"{key}::{val}")

    doc = as_text(first_nested_value(item, ["doc_id"]))
    sent = as_text(first_nested_value(item, ["sentence_id"]))
    row_idx = as_text(first_nested_value(item, ["source_row_index", "row_index", "global_sentence_index"]))
    if doc and sent:
        ids.append(f"doc_sentence::{doc}::{sent}")
    if doc and row_idx:
        ids.append(f"doc_row::{doc}::{row_idx}")

    stable = unique(ids)
    if stable:
        return stable

    if text:
        return ["text::" + normalized_text_key(text)[:320]]
    return [json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)[:500]]


def finalize_item(item: Mapping[str, Any], *, pack: Mapping[str, Any], profile: Mapping[str, Any], registry_row: Mapping[str, Any], source_index: SourceWindowIndex, lane: str, window_before: int, window_after: int, max_window_chars: int) -> Dict[str, Any]:
    ctx = binding_context(pack, profile, registry_row)
    window = source_index.window(item, before=window_before, after=window_after, max_chars=max_window_chars)
    anchor = item_anchor_text(item)
    completed = as_text(window.get("source_window_text") or anchor)
    role, reasons = infer_final_role(item, completed, ctx, lane)
    item_copy = dict(item)
    flags = risk_flags(item)
    original_shape = shape_label(anchor)
    completed_shape = shape_label(completed)
    item_copy["anchor_text"] = anchor
    item_copy["source_window_text"] = completed
    item_copy["completed_evidence_text"] = completed
    item_copy["text"] = completed
    item_copy["quote"] = completed
    item_copy["finalizer_contract_version"] = FINALIZER_CONTRACT_VERSION
    item_copy["finalizer_role"] = role
    item_copy["role"] = role if role != "excluded" else as_text(item.get("role") or "excluded")
    item_copy["finalizer_decision"] = "draft_evidence" if role in DRAFT_ROLES else "excluded"
    item_copy["finalizer_reason"] = ";".join(reasons)
    item_copy["finalizer_source_lane"] = lane
    item_copy["source_window_provenance"] = {
        "resolved": bool(window.get("resolved")),
        "resolved_by": window.get("resolved_by"),
        "anchor_overlay_index": window.get("anchor_overlay_index"),
        "source_window_row_indices": window.get("source_window_row_indices") or [],
    }
    item_copy["finalizer_shape"] = {
        "anchor_shape": original_shape,
        "completed_shape": completed_shape,
        "was_context_completed": completed != anchor,
    }
    item_copy["finalizer_binding"] = {
        "label_token_overlap": sorted(ctx["label_tokens"] & tokens(completed)),
        "profile_token_overlap": sorted(ctx["source_tokens"] & tokens(completed))[:40],
        "topic_token_overlap": sorted(ctx["topic_tokens"] & tokens(completed))[:40],
        "branch_tokens_required": sorted(ctx["branch_tokens"]),
        "branch_tokens_present": sorted(ctx["branch_tokens"] & tokens(completed)),
        "generic_parent_tokens_present": sorted(set(ctx.get("generic_parent_tokens") or set()) & tokens(completed)),
        "role_target_count": len(as_list(ctx.get("role_targets"))),
    }
    item_copy["finalizer_risk_flags"] = flags
    return item_copy


def lane_items(pack: Mapping[str, Any], lane: str) -> List[Dict[str, Any]]:
    return [dict(x) for x in as_list(pack.get(lane)) if isinstance(x, Mapping)]


def strict_scored_candidates_for_kc(scored_rows: Sequence[Mapping[str, Any]], kc_id: str) -> List[Dict[str, Any]]:
    rows = [dict(r) for r in scored_rows if row_kc_id(r) == kc_id]
    rows.sort(key=lambda r: float(r.get("alignment_score") or (r.get("retrieval_scores") or {}).get("combined") or 0.0), reverse=True)
    return rows[:40]


def dedupe_finalized(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        text = as_text(item.get("completed_evidence_text") or item.get("text"))
        ids = evidence_identity(item, text)
        if any(i in seen for i in ids):
            continue
        seen.update(ids)
        out.append(dict(item))
    return out


def role_sort_key(item: Mapping[str, Any]) -> Tuple[int, float, int, str]:
    role_rank = {"core": 0, "explanation": 1, "formula_or_procedure": 2, "example_or_boundary": 3, "bridge_context": 4, "excluded": 9}
    score = float(item.get("alignment_score") or (item.get("retrieval_scores") or {}).get("combined") or 0.0)
    text = as_text(item.get("completed_evidence_text") or item.get("text"))
    return (role_rank.get(as_text(item.get("finalizer_role")), 8), -score, len(text), text[:80])


def balance_draft_evidence(items: Sequence[Mapping[str, Any]], *, max_total: int = 8) -> List[Dict[str, Any]]:
    caps = {"core": 3, "explanation": 3, "formula_or_procedure": 2, "example_or_boundary": 2, "bridge_context": 2}
    by_role: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in dedupe_finalized(items):
        role = as_text(item.get("finalizer_role"))
        if role in DRAFT_ROLES:
            by_role[role].append(dict(item))
    selected: List[Dict[str, Any]] = []
    # First guarantee core if available, then role diversity.
    for role in DRAFT_ROLES:
        rows = sorted(by_role.get(role, []), key=role_sort_key)
        for item in rows[: caps[role]]:
            if len(selected) < max_total:
                selected.append(item)
    return sorted(dedupe_finalized(selected), key=role_sort_key)[:max_total]


def finalize_pack(pack: Mapping[str, Any], *, profile: Mapping[str, Any], registry_row: Mapping[str, Any], scored_rows: Sequence[Mapping[str, Any]], source_index: SourceWindowIndex, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    kc_id = as_text(pack.get("kc_id") or pack.get("knowledge_unit_id"))
    window_before = int(cfg.get("window_before", 2))
    window_after = int(cfg.get("window_after", 2))
    max_window_chars = int(cfg.get("max_window_chars", 1200))
    max_draft_items = int(cfg.get("max_draft_items", 8))
    allow_strict_scored_promotion = bool(cfg.get("allow_strict_scored_promotion", False))

    candidates: List[Dict[str, Any]] = []
    # Ordered and drafting core are primary. Auxiliary and near-miss can become bridge/support only if clean.
    source_lanes = [
        "ordered_pack_for_drafting",
        "drafting_core_evidence",
        "auxiliary_evidence",
    ]
    for lane in source_lanes:
        lane_cap = 80
        for item in lane_items(pack, lane)[:lane_cap]:
            finalized = finalize_item(
                item,
                pack=pack,
                profile=profile,
                registry_row=registry_row,
                source_index=source_index,
                lane=lane,
                window_before=window_before,
                window_after=window_after,
                max_window_chars=max_window_chars,
            )
            # Review lane is not allowed to become core automatically unless it is very strongly source-bound.
            if lane in {"review_needed_evidence", "near_miss_review_items"} and finalized.get("finalizer_role") == "core":
                bind = finalized.get("finalizer_binding") or {}
                if not bind.get("label_token_overlap") and not bind.get("branch_tokens_present"):
                    finalized["finalizer_role"] = "bridge_context"
                    finalized["role"] = "bridge_context"
                    finalized["finalizer_reason"] = as_text(finalized.get("finalizer_reason")) + ";review_lane_core_demoted_without_label_or_branch_binding"
            candidates.append(finalized)

    if allow_strict_scored_promotion:
        for row in strict_scored_candidates_for_kc(scored_rows, kc_id):
            # Only promote scored candidates as draft support if the existing pack lacks role diversity.
            cand = finalize_item(
                row,
                pack=pack,
                profile=profile,
                registry_row=registry_row,
                source_index=source_index,
                lane="scored_candidates_strict_pool",
                window_before=window_before,
                window_after=window_after,
                max_window_chars=max_window_chars,
            )
            if cand.get("finalizer_role") in DRAFT_ROLES and cand.get("finalizer_decision") == "draft_evidence":
                # Scored-pool core must have label/profile or branch overlap, not merely parent-topic overlap.
                bind = cand.get("finalizer_binding") or {}
                if cand.get("finalizer_role") == "core" and not (bind.get("label_token_overlap") or bind.get("profile_token_overlap") or bind.get("branch_tokens_present")):
                    cand["finalizer_role"] = "bridge_context"
                    cand["role"] = "bridge_context"
                    cand["finalizer_reason"] = as_text(cand.get("finalizer_reason")) + ";strict_scored_core_demoted_low_binding"
                candidates.append(cand)

    draft_candidates = [c for c in candidates if c.get("finalizer_role") in DRAFT_ROLES and c.get("finalizer_decision") == "draft_evidence"]
    excluded = [c for c in candidates if c.get("finalizer_role") == "excluded" or c.get("finalizer_decision") == "excluded"]
    draft = balance_draft_evidence(draft_candidates, max_total=max_draft_items)
    draft_role_counter = Counter(as_text(x.get("finalizer_role")) for x in draft)
    has_core = draft_role_counter.get("core", 0) >= 1
    has_support = sum(draft_role_counter.get(r, 0) for r in ["explanation", "formula_or_procedure", "example_or_boundary", "bridge_context"]) >= 1
    unresolved = [x for x in draft if not ((x.get("source_window_provenance") or {}).get("resolved"))]
    bad_shape = [x for x in draft if (x.get("finalizer_shape") or {}).get("completed_shape") in {"empty", "too_short", "anaphoric_start", "caption_or_pointer_start"}]
    quality_state = "usable_finalized_pack" if has_core and has_support and not unresolved and not bad_shape else "limited_finalized_pack"
    limitation_reasons: List[str] = []
    if not draft:
        limitation_reasons.append("no_draft_evidence")
    if not has_core:
        limitation_reasons.append("no_core_evidence")
    if not has_support:
        limitation_reasons.append("no_support_evidence")
    if unresolved:
        limitation_reasons.append("unresolved_source_windows")
    if bad_shape:
        limitation_reasons.append("bad_completed_evidence_shape")

    out = dict(pack)
    original_ordered = as_list(pack.get("ordered_pack_for_drafting"))
    out["pack_version"] = as_text(pack.get("pack_version") or "") + "+" + FINALIZER_CONTRACT_VERSION
    out["finalizer_contract_version"] = FINALIZER_CONTRACT_VERSION
    out["pre_finalizer_counts"] = {
        "ordered_pack_for_drafting": len(original_ordered),
        "drafting_core_evidence": len(as_list(pack.get("drafting_core_evidence"))),
        "auxiliary_evidence": len(as_list(pack.get("auxiliary_evidence"))),
        "review_needed_evidence": len(as_list(pack.get("review_needed_evidence"))),
        "near_miss_review_items": len(as_list(pack.get("near_miss_review_items"))),
        "rejected_false_positive_evidence": len(as_list(pack.get("rejected_false_positive_evidence"))),
    }
    out["ordered_pack_for_drafting"] = draft
    out["drafting_core_evidence"] = draft
    out["finalized_evidence_pack"] = {
        "contract_version": FINALIZER_CONTRACT_VERSION,
        "knowledge_unit_id": as_text(pack.get("knowledge_unit_id") or kc_id),
        "knowledge_unit_type": as_text(pack.get("knowledge_unit_type") or "kc"),
        "draft_evidence": draft,
        "bridge_context": [x for x in draft if x.get("finalizer_role") == "bridge_context"],
        "excluded_evidence": excluded[:80],
        "gap_requests": as_list(pack.get("retrieval_gap_requests")),
        "pack_quality": {
            "state": quality_state,
            "limitation_reasons": limitation_reasons,
            "draft_role_counter": dict(draft_role_counter),
            "draft_evidence_count": len(draft),
            "excluded_evidence_count": len(excluded),
            "source_window_resolved_count": sum(1 for x in draft if (x.get("source_window_provenance") or {}).get("resolved")),
        },
        "provenance": {
            "source_pack_version": as_text(pack.get("pack_version")),
            "source_candidate_pack_ordered_count": len(original_ordered),
            "finalized_utc": now_utc_iso(),
        },
    }
    out["pack_quality"] = dict(pack.get("pack_quality") or {})
    out["pack_quality"].update(out["finalized_evidence_pack"]["pack_quality"])
    out["missing_positive_support_reason"] = ";".join(limitation_reasons) if quality_state != "usable_finalized_pack" else ""
    return out


def finalize_packs(*, packs: Sequence[Mapping[str, Any]], profiles: Sequence[Mapping[str, Any]], registry_rows: Sequence[Mapping[str, Any]], scored_rows: Sequence[Mapping[str, Any]], sentence_overlay_rows: Sequence[Mapping[str, Any]], cfg: Optional[Mapping[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    cfg = dict(cfg or {})
    profiles_by_kc = profiles_by_id(profiles)
    registry = registry_by_id(registry_rows)
    source_index = SourceWindowIndex(sentence_overlay_rows)
    finalized: List[Dict[str, Any]] = []
    review_queue: List[Dict[str, Any]] = []
    for pack in packs:
        kc_id = as_text(pack.get("kc_id") or pack.get("knowledge_unit_id"))
        final = finalize_pack(
            pack,
            profile=profiles_by_kc.get(kc_id, {}),
            registry_row=registry.get(kc_id, {}),
            scored_rows=scored_rows,
            source_index=source_index,
            cfg=cfg,
        )
        finalized.append(final)
        quality = (final.get("finalized_evidence_pack") or {}).get("pack_quality") or {}
        if quality.get("state") != "usable_finalized_pack":
            review_queue.append({
                "kc_id": kc_id,
                "knowledge_unit_id": as_text(final.get("knowledge_unit_id") or kc_id),
                "canonical_name": as_text(final.get("canonical_name")),
                "knowledge_unit_type": as_text(final.get("knowledge_unit_type") or "kc"),
                "quality_state": quality.get("state"),
                "limitation_reasons": quality.get("limitation_reasons") or [],
                "draft_role_counter": quality.get("draft_role_counter") or {},
                "draft_evidence_count": quality.get("draft_evidence_count") or 0,
            })
    stats = build_stats(finalized)
    return finalized, stats, review_queue


def build_stats(packs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    role_counter = Counter()
    state_counter = Counter()
    limitation_counter = Counter()
    ordered_total = 0
    empty = 0
    for pack in packs:
        ordered = as_list(pack.get("ordered_pack_for_drafting"))
        ordered_total += len(ordered)
        if not ordered:
            empty += 1
        q = (pack.get("finalized_evidence_pack") or {}).get("pack_quality") or {}
        state_counter[as_text(q.get("state") or "unknown")] += 1
        for r in q.get("limitation_reasons") or []:
            limitation_counter[as_text(r)] += 1
        for item in ordered:
            role_counter[as_text(item.get("finalizer_role") or item.get("role") or "unknown")] += 1
    return {
        "contract_version": FINALIZER_CONTRACT_VERSION,
        "created_utc": now_utc_iso(),
        "pack_count": len(packs),
        "ordered_total": ordered_total,
        "nonempty_pack_count": len(packs) - empty,
        "empty_pack_count": empty,
        "quality_state_counter": dict(state_counter),
        "limitation_reason_counter": dict(limitation_counter),
        "draft_role_counter": dict(role_counter),
    }


def run_finalizer_artifacts(*, pack_jsonl: Path, profile_jsonl: Path, registry_jsonl: Path, scored_jsonl: Path, sentence_overlay_jsonl: Path, output_root: Path, run_id: str, cfg: Optional[Mapping[str, Any]] = None, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    processed_dir = output_root / run_id
    sets_root = output_root / "_sets"
    processed_dir.mkdir(parents=True, exist_ok=False)
    sets_root.mkdir(parents=True, exist_ok=True)
    packs = read_jsonl(pack_jsonl)
    profiles = read_jsonl(profile_jsonl)
    registry_rows = read_jsonl(registry_jsonl)
    scored_rows = read_jsonl(scored_jsonl)
    overlay_rows = read_jsonl(sentence_overlay_jsonl)
    finalized, stats, review_queue = finalize_packs(
        packs=packs,
        profiles=profiles,
        registry_rows=registry_rows,
        scored_rows=scored_rows,
        sentence_overlay_rows=overlay_rows,
        cfg=cfg or {},
    )
    pack_out = processed_dir / "kc_evidence_packs.jsonl"
    stats_out = processed_dir / "evidence_pack_stats.json"
    gap_out = processed_dir / "retrieval_gap_requests.jsonl"
    review_out = processed_dir / "finalization_review_queue.jsonl"
    manifest_out = processed_dir / "evidence_pack_manifest.json"
    set_manifest_out = sets_root / f"{run_id}_step5xf_finalized_evidence_packs_set.json"

    write_jsonl(pack_out, finalized)
    write_json(stats_out, stats)
    # Preserve gap requests already attached to packs, plus finalizer limitation gaps.
    gaps: List[Dict[str, Any]] = []
    for pack in finalized:
        for req in as_list(pack.get("retrieval_gap_requests")):
            if isinstance(req, Mapping):
                gaps.append(dict(req))
        q = (pack.get("finalized_evidence_pack") or {}).get("pack_quality") or {}
        if q.get("state") != "usable_finalized_pack":
            gaps.append({
                "kc_id": as_text(pack.get("kc_id") or pack.get("knowledge_unit_id")),
                "knowledge_unit_id": as_text(pack.get("knowledge_unit_id") or pack.get("kc_id")),
                "knowledge_unit_type": as_text(pack.get("knowledge_unit_type") or "kc"),
                "gap_type": "finalized_pack_limitation",
                "reasons": q.get("limitation_reasons") or [],
                "created_by": FINALIZER_CONTRACT_VERSION,
            })
    write_jsonl(gap_out, gaps)
    write_jsonl(review_out, review_queue)
    manifest = {
        "schema_version": "1.0",
        "kind": "step5xf_finalized_evidence_packs",
        "run_id": run_id,
        "created_utc": now_utc_iso(),
        "contract_version": FINALIZER_CONTRACT_VERSION,
        "artifacts": {
            "kc_evidence_packs_jsonl": str(pack_out.relative_to(repo_root)) if pack_out.is_relative_to(repo_root) else str(pack_out),
            "evidence_pack_stats_json": str(stats_out.relative_to(repo_root)) if stats_out.is_relative_to(repo_root) else str(stats_out),
            "retrieval_gap_requests_jsonl": str(gap_out.relative_to(repo_root)) if gap_out.is_relative_to(repo_root) else str(gap_out),
            "finalization_review_queue_jsonl": str(review_out.relative_to(repo_root)) if review_out.is_relative_to(repo_root) else str(review_out),
        },
        "upstream": {
            "source_step5x_pack_jsonl": str(pack_jsonl),
            "profile_jsonl": str(profile_jsonl),
            "scored_candidates_jsonl": str(scored_jsonl),
            "registry_jsonl": str(registry_jsonl),
            "sentence_overlay_jsonl": str(sentence_overlay_jsonl),
        },
        "stats": stats,
    }
    set_manifest = {
        "schema_version": "1.0",
        "kind": "step5_4_evidence_pack_set",
        "set_id": f"{run_id}_step5xf_finalized_evidence_packs_set",
        "run_id_step5xf": run_id,
        "created_utc": now_utc_iso(),
        "contract_version": FINALIZER_CONTRACT_VERSION,
        "artifacts": dict(manifest["artifacts"]),
        "upstream": dict(manifest["upstream"]),
        "stats": stats,
    }
    write_json(manifest_out, manifest)
    write_json(set_manifest_out, set_manifest)
    return {
        "run_id": run_id,
        "processed_dir": str(processed_dir),
        "kc_evidence_packs_jsonl": str(pack_out),
        "evidence_pack_stats_json": str(stats_out),
        "retrieval_gap_requests_jsonl": str(gap_out),
        "finalization_review_queue_jsonl": str(review_out),
        "evidence_pack_manifest_json": str(manifest_out),
        "set_manifest_json": str(set_manifest_out),
        "stats": stats,
        "review_queue_count": len(review_queue),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize Step 5x evidence packs into draft-facing source-bound packs.")
    parser.add_argument("--pack-jsonl", required=True)
    parser.add_argument("--profile-jsonl", required=True)
    parser.add_argument("--registry-jsonl", required=True)
    parser.add_argument("--scored-jsonl", required=True)
    parser.add_argument("--sentence-overlay-jsonl", required=True)
    parser.add_argument("--output-root", default="data/processed/evidence_stage_v3_evidence_packs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--window-before", type=int, default=2)
    parser.add_argument("--window-after", type=int, default=2)
    parser.add_argument("--max-window-chars", type=int, default=1200)
    parser.add_argument("--max-draft-items", type=int, default=8)
    parser.add_argument("--strict-scored-promotion", action="store_true", help="Allow cautious promotion from scored rows. Disabled by default for precision.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result = run_finalizer_artifacts(
        pack_jsonl=Path(args.pack_jsonl),
        profile_jsonl=Path(args.profile_jsonl),
        registry_jsonl=Path(args.registry_jsonl),
        scored_jsonl=Path(args.scored_jsonl),
        sentence_overlay_jsonl=Path(args.sentence_overlay_jsonl),
        output_root=Path(args.output_root),
        run_id=args.run_id,
        cfg={
            "window_before": args.window_before,
            "window_after": args.window_after,
            "max_window_chars": args.max_window_chars,
            "max_draft_items": args.max_draft_items,
            "allow_strict_scored_promotion": bool(args.strict_scored_promotion),
        },
        repo_root=Path.cwd(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

