from __future__ import annotations

import hashlib
import json
import re
import tarfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from kc_l.audit.manifests import build_output_manifest, env_snapshot, try_cmd_version
from kc_l.retrieval_gate.profile_guidance import (
    Step5xProfileGuidance,
    alias_safe_terms_for_candidate_generation,
    guidance_summary_for_candidate_row,
    guidance_to_candidate_bank_controls,
    guidance_from_profile,
)
from kc_l.retrieval_gate.evidence_stage_v3_retrieval_policy import (
    AUTHORITY_CONTRACT,
    build_retrieval_policy_plan,
)
from kc_l.retrieval_windowing.semantic import match_normalize, normalize_ws, tokenize
from kc_l.retrieval_windowing.source_surface_fallback import (
    SOURCE_SURFACE_FALLBACK,
    build_source_surface_fallback_candidates,
    fallback_config_from_mapping,
)
from kc_l.runtime.current_step_artifacts import resolve_seedless_kc_registry_path
from kc_l.utils.json_io import read_jsonl, write_json, write_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_BANK_CONTRACT_VERSION = "step5x_v3_candidate_bank_v1"
SOURCE_SURFACE_STEP53_NESTED = "step5_3_nested_evidence"
SOURCE_DIRECT_OVERLAY_SUPPLEMENT = "direct_overlay_supplement"
SOURCE_OVERLAY_TARGET_SUPPLEMENT = "source_overlay_target_supplement"
SOURCE_STEP = "step5_3"
FORBIDDEN_SEED_FIELDS = {
    "seed_definition",
    "seed_keywords",
    "seed_floor",
    "seed_floor_fallback",
    "seed_definition_text",
    "seed_scope",
}
STRUCTURAL_FLAG_KEYS = (
    "has_text",
    "has_source_block_text",
    "has_sentence_id",
    "has_patch_id",
    "has_page_index",
    "looks_formula_like",
    "looks_caption_like",
    "looks_prompt_like",
    "looks_fragmentary",
)
REQUIRED_ROW_KEYS = (
    "candidate_id",
    "candidate_bank_version",
    "run_id",
    "source_surface",
    "source_manifest",
    "source_row_index",
    "source_evidence_index",
    "kc_id",
    "canonical_name",
    "aliases",
    "topic_path_ids",
    "topic_path_labels",
    "parent_topic_id",
    "parent_topic_label",
    "source_kc_id",
    "source_canonical_name",
    "granularity",
    "text",
    "source_block_text",
    "context_text",
    "doc_id",
    "page_index",
    "block_id",
    "sentence_id",
    "sent_idx",
    "patch_id",
    "patch_heading",
    "reveal_group_id",
    "layer",
    "bbox",
    "char_start",
    "char_end",
    "retrieval_scores",
    "alignment_score",
    "alignment_breakdown",
    "support_profile",
    "structural_flags",
    "raw_text_hash",
    "provenance",
)
FORMULA_RE = re.compile(
    r"(?:\\(?:sum|frac|sqrt|log|begin|end|mathbb|mathbf|operatorname)\b|"
    r"\b(?:argmax|argmin)\b|[∑Σ]|"
    r"\bO\s*\(|"
    r"[A-Za-z][A-Za-z0-9_]*\s*=\s*[^=])"
)
CAPTION_RE = re.compile(r"^(?:figure|fig\.|table|algorithm|listing|chart)\b")
PROMPT_RE = re.compile(r"^(?:describe|explain|compare|discuss|consider|identify|list|state|suppose|show)\b")
FRAGMENT_PREFIX_RE = re.compile(r"^(?:and|or|but|because|while|where|when|if|then|thus|therefore|however|for|to)\b")
TRAILING_FRAGMENT_RE = re.compile(r"(?:[,;:]|(?:\b(?:and|or|but|because|while|where|when|if|then)\s*))$")
REFERENCE_LIKE_RE = re.compile(
    r"\b(?:reference|references|bibliography|works\s+cited|further\s+reading|doi|isbn|et\s+al\.?)\b"
)
DIRECT_OVERLAY_OPEN_ENDED_RE = re.compile(
    r"(?:\b(?:given by|defined by|as follows|consists of|includes|comprises|results in|leads to)\b\s*:?|[=\(\[\{:/])$"
)
INPUT_MEMBER_SEPARATOR = "::"
DEFAULT_REGISTRY_ALIAS = "data/work/cache/current_step_artifacts/step1_seedless_hierarchy_registry.current.jsonl"
DEFAULT_OUTPUT_ROOT = "data/processed/evidence_stage_v3_candidate_bank"
DEFAULT_SET_MANIFEST_ROOT = "data/processed/evidence_stage_v3_candidate_bank/_sets"
INPUT_MODE_LEGACY_STEP5_3 = "legacy_step5_3"
INPUT_MODE_CLEAN_SLATE = "clean_slate_registry_sentence_overlay"
REGISTRY_SOURCE_SEEDLESS = "seedless_registry"
SOURCE_REGISTRY_CLEAN_SLATE = "seedless_registry_clean_slate"
STRUCTURAL_ANCHOR_REASON = "structural_anchor_from_profile_or_label"
STRUCTURAL_NEIGHBOR_REASON = "structural_neighbor_from_profile_or_label_anchor"
PROFILE_PROVENANCE_REHYDRATION = "profile_provenance_rehydration"
DEFAULT_MAX_STRUCTURAL_ANCHORS_PER_KC = 6
DEFAULT_MAX_STRUCTURAL_NEIGHBORS_PER_ANCHOR = 3
DEFAULT_MAX_STRUCTURAL_EXPANDED_CANDIDATES_PER_KC = 8
FORMULA_OR_METRIC_HINT_TOKENS = {
    "coefficient",
    "equation",
    "fmeasure",
    "f1",
    "formula",
    "formulas",
    "measure",
    "measures",
    "metric",
    "metrics",
    "ratio",
    "ratios",
    "score",
    "scores",
}
DEFINITION_HINT_TOKENS = {
    "concept",
    "concepts",
    "definition",
    "definitions",
    "meaning",
    "meanings",
    "term",
    "terms",
}
PROCESS_HINT_TOKENS = {
    "algorithm",
    "algorithms",
    "mechanism",
    "mechanisms",
    "phase",
    "phases",
    "procedure",
    "procedures",
    "process",
    "processes",
    "step",
    "steps",
}
EXAMPLE_HINT_TOKENS = {
    "example",
    "examples",
    "illustration",
    "illustrations",
    "instance",
    "instances",
}
DIRECT_OVERLAY_SIGNAL_PREFIXES = ("required:", "context:", "strong:", "signal:")


@dataclass(frozen=True)
class InputSpec:
    raw: str
    archive_path: Optional[Path]
    member_path: Optional[str]
    file_path: Optional[Path]

    @property
    def is_archive_member(self) -> bool:
        return self.archive_path is not None and self.member_path is not None

    def display(self) -> str:
        if self.is_archive_member:
            return f"{self.archive_path.as_posix()}::{self.member_path}"
        if self.file_path is not None:
            return self.file_path.as_posix()
        return self.raw


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _stringify_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_repo_path(raw_path: Any, *, repo_root: Path = REPO_ROOT) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    return (repo_root / candidate).resolve()


def parse_input_spec(raw_value: Any, *, repo_root: Path = REPO_ROOT) -> InputSpec:
    raw = str(raw_value or "").strip()
    if not raw:
        raise RuntimeError("Input spec is empty.")
    if INPUT_MEMBER_SEPARATOR in raw:
        archive_raw, member_raw = raw.split(INPUT_MEMBER_SEPARATOR, 1)
        archive_path = resolve_repo_path(archive_raw, repo_root=repo_root)
        member_path = str(PurePosixPath(member_raw.replace("\\", "/")))
        return InputSpec(raw=raw, archive_path=archive_path, member_path=member_path, file_path=None)
    return InputSpec(raw=raw, archive_path=None, member_path=None, file_path=resolve_repo_path(raw, repo_root=repo_root))


def _tar_members(archive_path: Path) -> set[str]:
    with tarfile.open(archive_path, "r:*") as handle:
        return set(handle.getnames())


def input_spec_exists(spec: InputSpec) -> bool:
    if spec.is_archive_member:
        if spec.archive_path is None or not spec.archive_path.exists():
            return False
        return spec.member_path in _tar_members(spec.archive_path)
    return bool(spec.file_path and spec.file_path.exists())


def _read_text_from_archive_member(archive_path: Path, member_path: str) -> str:
    with tarfile.open(archive_path, "r:*") as handle:
        member = handle.extractfile(member_path)
        if member is None:
            raise FileNotFoundError(f"Archive member not found: {archive_path}::{member_path}")
        return member.read().decode("utf-8")


def read_text_from_spec(spec: InputSpec) -> str:
    if spec.is_archive_member:
        assert spec.archive_path is not None
        assert spec.member_path is not None
        return _read_text_from_archive_member(spec.archive_path, spec.member_path)
    if spec.file_path is None or not spec.file_path.exists():
        raise FileNotFoundError(f"Input path not found: {spec.raw}")
    return spec.file_path.read_text(encoding="utf-8")


def read_json_from_spec(spec: InputSpec) -> Dict[str, Any]:
    obj = json.loads(read_text_from_spec(spec))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected JSON object for {spec.display()}")
    return obj


def read_jsonl_from_spec(spec: InputSpec) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in read_text_from_spec(spec).splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def resolve_related_input_spec(raw_value: Any, *, repo_root: Path, base_spec: Optional[InputSpec]) -> InputSpec:
    direct = parse_input_spec(raw_value, repo_root=repo_root)
    if input_spec_exists(direct):
        return direct
    if base_spec is not None and base_spec.archive_path is not None and not direct.is_archive_member:
        member_path = str(PurePosixPath(str(raw_value).replace("\\", "/")))
        archive_member = InputSpec(
            raw=f"{base_spec.archive_path.as_posix()}::{member_path}",
            archive_path=base_spec.archive_path,
            member_path=member_path,
            file_path=None,
        )
        if input_spec_exists(archive_member):
            return archive_member
    raise FileNotFoundError(f"Could not resolve input spec: {raw_value}")


def ensure_reference_allowed(spec: InputSpec, *, allow_reference_artifact_inputs: bool) -> None:
    if allow_reference_artifact_inputs:
        return
    target = spec.display().lower()
    if "_reference_artifacts" in target:
        raise RuntimeError(f"Reference-artifact input is disabled by config: {spec.display()}")


def strip_forbidden_seed_fields(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        cleaned: Dict[str, Any] = {}
        for key, value in obj.items():
            if str(key) in FORBIDDEN_SEED_FIELDS:
                continue
            cleaned[str(key)] = strip_forbidden_seed_fields(value)
        return cleaned
    if isinstance(obj, list):
        return [strip_forbidden_seed_fields(item) for item in obj]
    return obj


def count_forbidden_seed_fields(obj: Any) -> int:
    if isinstance(obj, Mapping):
        total = 0
        for key, value in obj.items():
            if str(key) in FORBIDDEN_SEED_FIELDS:
                total += 1
            total += count_forbidden_seed_fields(value)
        return total
    if isinstance(obj, list):
        return sum(count_forbidden_seed_fields(item) for item in obj)
    return 0


def _count_forbidden_seed_field_keys(obj: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_text = str(key)
            if key_text in FORBIDDEN_SEED_FIELDS:
                counts[key_text] += 1
            counts.update(_count_forbidden_seed_field_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            counts.update(_count_forbidden_seed_field_keys(item))
    return counts


def _seed_field_detection_for_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(_count_forbidden_seed_field_keys(row))
    return {
        "total": int(sum(counts.values())),
        "by_key": dict(sorted(counts.items())),
    }


def _enforce_seed_bearing_input_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    input_label: str,
    allow_seed_bearing_input_for_diagnostic: bool,
) -> Dict[str, Any]:
    detection = _seed_field_detection_for_rows(rows)
    if int(detection.get("total") or 0) > 0 and not allow_seed_bearing_input_for_diagnostic:
        raise RuntimeError(
            f"{input_label} contains forbidden seed fields. "
            "Active Step 5x runtime rejects seed-bearing inputs unless "
            "--allow-seed-bearing-input-for-diagnostic is explicitly enabled."
        )
    return detection


def _as_text(value: Any) -> str:
    return normalize_ws(str(value or ""))


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = _as_text(item)
        if text:
            out.append(text)
    return out


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _content_tokens(text: str, *, min_len: int = 2) -> List[str]:
    return [token for token in tokenize(match_normalize(text), min_len=min_len) if token]


def _boundary_phrase_hit(surface_norm: str, phrase_norm: str) -> bool:
    if not surface_norm or not phrase_norm:
        return False
    start = surface_norm.find(phrase_norm)
    while start >= 0:
        end = start + len(phrase_norm)
        before = surface_norm[start - 1] if start > 0 else " "
        after = surface_norm[end] if end < len(surface_norm) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = surface_norm.find(phrase_norm, start + 1)
    return False


def _surface_views(sentence_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _as_text(sentence_row.get("sentence_text") or sentence_row.get("text") or sentence_row.get("snippet"))
    source_block_text = _as_text(sentence_row.get("source_block_text") or text)
    patch_heading = _as_text(sentence_row.get("patch_heading"))
    page_heading = _as_text(sentence_row.get("page_heading_norm"))
    heading_text = patch_heading or page_heading
    context_text = page_heading if page_heading and page_heading != patch_heading else ""
    return {
        "text": text,
        "source_block_text": source_block_text,
        "patch_heading": patch_heading,
        "heading_text": heading_text,
        "context_text": context_text,
        "text_norm": match_normalize(text),
        "source_block_norm": match_normalize(source_block_text),
        "heading_norm": match_normalize(heading_text),
    }


def _is_unsafe_sentence_row(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> bool:
    if bool(sentence_row.get("is_meta")) or bool(sentence_row.get("is_nav_boilerplate")) or bool(sentence_row.get("is_author_affiliation")):
        return True
    text = str(views.get("text") or "")
    heading_text = str(views.get("heading_text") or "")
    if bool(sentence_row.get("is_heading_like")) and len(text) < 80:
        return True
    if CAPTION_RE.search(text.lower()) or CAPTION_RE.search(heading_text.lower()):
        return True
    return False


def _structural_shape_tags(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> List[str]:
    tags: List[str] = []
    if bool(sentence_row.get("is_definition_like")):
        tags.append("definition")
    if bool(sentence_row.get("is_formula_like")) or bool(FORMULA_RE.search(str(views.get("text") or ""))):
        tags.append("formula")
    if bool(sentence_row.get("is_procedure_like")):
        tags.append("procedure")
    if bool(sentence_row.get("is_example_like")):
        tags.append("example")
    return tags


def _anchor_surface_terms(
    context_row: Mapping[str, Any],
    guidance: Optional[Step5xProfileGuidance],
) -> List[str]:
    raw_terms = [_as_text(context_row.get("canonical_name")), *_as_str_list(context_row.get("aliases"))]
    if guidance is not None and guidance.safe_to_use_for_step5x:
        raw_terms.extend(query.query for query in guidance.lexical_queries if _as_text(query.query))
    filtered: List[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        normalized = match_normalize(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        filtered.append(term)
    return filtered


def _negative_constraint_terms(guidance: Optional[Step5xProfileGuidance]) -> List[str]:
    if guidance is None:
        return []
    return _dedupe_preserve_order(
        _as_text(item.term)
        for item in guidance.negative_constraints
        if _as_text(item.term)
    )


def _shape_preference_flags(
    context_row: Mapping[str, Any],
    guidance: Optional[Step5xProfileGuidance],
) -> Dict[str, bool]:
    hint_tokens: set[str] = set()
    if guidance is not None:
        for hint in guidance.evidence_shape_hints:
            hint_tokens.update(_content_tokens(hint.shape, min_len=1))
            hint_tokens.update(_content_tokens(hint.shape_family, min_len=1))
    if not hint_tokens:
        for term in [_as_text(context_row.get("canonical_name")), *_as_str_list(context_row.get("aliases"))]:
            hint_tokens.update(_content_tokens(term, min_len=1))
    return {
        "formula_or_metric": bool(hint_tokens & FORMULA_OR_METRIC_HINT_TOKENS),
        "definition": bool(hint_tokens & DEFINITION_HINT_TOKENS),
        "process": bool(hint_tokens & PROCESS_HINT_TOKENS),
        "example": bool(hint_tokens & EXAMPLE_HINT_TOKENS),
    }


def _direct_exact_match_flags(
    *,
    canonical_name: str,
    aliases: Sequence[str],
    views: Mapping[str, Any],
) -> Tuple[bool, bool]:
    canonical_norm = match_normalize(canonical_name)
    alias_norms = [match_normalize(alias) for alias in aliases if _as_text(alias)]
    exact_name = bool(canonical_norm and _boundary_phrase_hit(str(views.get("text_norm") or ""), canonical_norm))
    exact_alias = any(alias_norm and _boundary_phrase_hit(str(views.get("text_norm") or ""), alias_norm) for alias_norm in alias_norms)
    return exact_name, exact_alias


def _sentence_row_matches_negative_constraint(views: Mapping[str, Any], negative_terms: Sequence[str]) -> bool:
    combined = " ".join(
        value
        for value in (
            str(views.get("text_norm") or ""),
            str(views.get("source_block_norm") or ""),
            str(views.get("heading_norm") or ""),
        )
        if value
    )
    for term in negative_terms:
        normalized = match_normalize(term)
        if normalized and _boundary_phrase_hit(combined, normalized):
            return True
    return False


def _route_terms_hit_in_text(surface_norm: str, terms: Sequence[str]) -> List[str]:
    hits: List[str] = []
    for term in terms:
        normalized = match_normalize(term)
        if normalized and _boundary_phrase_hit(surface_norm, normalized):
            hits.append(term)
    return _dedupe_preserve_order(hits)


def _route_terms_hit(views: Mapping[str, Any], terms: Sequence[str]) -> List[str]:
    combined = " ".join(
        value
        for value in (
            str(views.get("text_norm") or ""),
            str(views.get("source_block_norm") or ""),
            str(views.get("heading_norm") or ""),
        )
        if value
    )
    return _route_terms_hit_in_text(combined, terms)


def _evaluate_profile_routes_for_sentence(
    guidance: Optional[Step5xProfileGuidance],
    sentence_row: Mapping[str, Any],
) -> Dict[str, Any]:
    if guidance is None or not guidance.retrieval_routes:
        return {
            "route_contract_present": False,
            "matched_route_count": 0,
            "positive_route_match_count": 0,
            "context_only_route_match_count": 0,
            "route_positive_blocked_by_missing_support_count": 0,
            "context_only_match_without_positive_route": False,
            "positive_route_required_but_absent": False,
            "matched_routes": [],
            "route_control_role": "step5p_retrieval_control_metadata_not_evidence",
        }

    views = _surface_views(sentence_row)
    matched: List[Dict[str, Any]] = []
    positive_count = 0
    context_count = 0
    blocked_count = 0

    for route in guidance.retrieval_routes:
        primary_hits = _route_terms_hit(views, route.primary_terms_any)
        primary_text_hits = _route_terms_hit_in_text(str(views.get("text_norm") or ""), route.primary_terms_any)
        primary_source_block_hits = _route_terms_hit_in_text(str(views.get("source_block_norm") or ""), route.primary_terms_any)
        primary_heading_hits = _route_terms_hit_in_text(str(views.get("heading_norm") or ""), route.primary_terms_any)
        if not primary_hits:
            continue
        support_any_hits = _route_terms_hit(views, route.support_terms_any)
        support_all_hits = _route_terms_hit(views, route.support_terms_all)
        negative_hits = _route_terms_hit(views, route.negative_terms_any)

        any_required = bool(route.support_terms_any)
        all_required = bool(route.support_terms_all)
        any_ok = (not any_required) or bool(support_any_hits)
        all_ok = (not all_required) or len({x.lower() for x in support_all_hits}) >= len({x.lower() for x in route.support_terms_all})
        missing_required_support = False
        if route.support_requirement in {"required_for_this_route", "required_for_positive_support_on_this_route"}:
            missing_required_support = not (any_ok and all_ok)

        route_context_only = bool(route.broad_context_only or route.activation == "context_only")
        # A route may use source_block/heading context to locate candidate rows,
        # but positive leaf-KC support must be anchored in the candidate row text
        # itself. Otherwise a true route sentence can make neighbouring broad
        # background rows positive merely because they share the same source block.
        primary_text_anchor_required_for_positive = bool(not primary_text_hits)
        route_can_positive = bool(
            route.activation == "active"
            and route.can_create_positive_support
            and not route_context_only
            and not primary_text_anchor_required_for_positive
            and not negative_hits
            and not missing_required_support
        )
        if route_context_only:
            context_count += 1
        if route_can_positive:
            positive_count += 1
        if missing_required_support:
            blocked_count += 1

        matched.append({
            "route_id": route.route_id,
            "route_type": route.route_type,
            "activation": route.activation,
            "route_strength": route.route_strength,
            "verification_status": route.verification_status,
            "support_requirement": route.support_requirement,
            "broad_context_only": route_context_only,
            "can_create_candidates": route.can_create_candidates,
            "can_create_positive_support": route.can_create_positive_support,
            "support_authority": getattr(route, "support_authority", "candidate_hint_step5x_must_verify"),
            "step5x_verification_required": getattr(route, "step5x_verification_required", True),
            "route_trust": getattr(route, "route_trust", "guidance"),
            "primary_hits": primary_hits,
            "primary_text_hits": primary_text_hits,
            "primary_source_block_hits": primary_source_block_hits,
            "primary_heading_hits": primary_heading_hits,
            "support_any_hits": support_any_hits,
            "support_all_hits": support_all_hits,
            "negative_hits": negative_hits,
            "missing_required_support": missing_required_support,
            "primary_text_anchor_required_for_positive": primary_text_anchor_required_for_positive,
            "route_can_create_positive_support_here": route_can_positive,
        })

    return {
        "route_contract_present": True,
        "matched_route_count": len(matched),
        "positive_route_match_count": positive_count,
        "context_only_route_match_count": context_count,
        "route_positive_blocked_by_missing_support_count": blocked_count,
        "context_only_match_without_positive_route": bool(context_count > 0 and positive_count == 0),
        "positive_route_required_but_absent": bool(positive_count == 0),
        "matched_routes": matched,
        "route_control_role": "step5p_retrieval_control_metadata_not_evidence",
    }


def _anchor_hits_for_sentence(
    sentence_row: Mapping[str, Any],
    *,
    anchor_terms: Sequence[str],
) -> Dict[str, Any]:
    views = _surface_views(sentence_row)
    matched_terms: List[str] = []
    hit_surfaces: List[str] = []
    surface_priority = 0.0
    for term in anchor_terms:
        normalized = match_normalize(term)
        if not normalized:
            continue
        if _boundary_phrase_hit(str(views.get("text_norm") or ""), normalized):
            matched_terms.append(term)
            hit_surfaces.append("text")
            surface_priority = max(surface_priority, 3.0)
            continue
        if _boundary_phrase_hit(str(views.get("source_block_norm") or ""), normalized):
            matched_terms.append(term)
            hit_surfaces.append("source_block")
            surface_priority = max(surface_priority, 2.5)
            continue
        if _boundary_phrase_hit(str(views.get("heading_norm") or ""), normalized):
            matched_terms.append(term)
            hit_surfaces.append("heading")
            surface_priority = max(surface_priority, 2.0)
    return {
        "views": views,
        "matched_terms": _dedupe_preserve_order(matched_terms),
        "hit_surfaces": _dedupe_preserve_order(hit_surfaces),
        "surface_priority": surface_priority,
    }


def _sentence_identity_values(sentence_row: Mapping[str, Any]) -> List[str]:
    """Return stable row identifiers usable for Step 5p source-window rehydration.

    Step 5p guidance is never evidence.  These IDs only allow Step 5x to
    locate the actual Step 4.5 sentence-overlay rows that Step 5p recommended
    for another look.
    """
    ids: List[str] = []
    for key in ("sentence_id", "snippet_id", "surface_id", "window_id", "source_window_id"):
        text = _as_text(sentence_row.get(key))
        if text and text not in ids:
            ids.append(text)
    return ids


def _sentence_identity_index(sentence_rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[int]]:
    index: Dict[str, List[int]] = {}
    for idx, row in enumerate(sentence_rows):
        for value in _sentence_identity_values(row):
            index.setdefault(value, []).append(idx)
    return index


def _source_window_anchor_indices(
    guidance: Optional[Step5xProfileGuidance],
    sentence_id_index: Mapping[str, Sequence[int]],
) -> List[int]:
    if guidance is None or not guidance.safe_to_use_for_step5x:
        return []
    out: List[int] = []
    seen: set[int] = set()
    for source_window_id in guidance.source_window_ids:
        for idx in sentence_id_index.get(_as_text(source_window_id), []):
            if idx in seen:
                continue
            seen.add(idx)
            out.append(idx)
    return out


def _source_ids_from_profile_provenance(provenance: Any) -> List[str]:
    ids: List[str] = []
    for item in provenance if isinstance(provenance, (list, tuple)) else [provenance]:
        if not isinstance(item, Mapping):
            continue
        for key in ("snippet_id", "sentence_id", "source_id", "surface_id", "window_id", "source_window_id"):
            text = _as_text(item.get(key))
            if text and text not in ids:
                ids.append(text)
    return ids


def _profile_record_shape_tags(record: Mapping[str, Any], sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> List[str]:
    hint_text = " ".join(
        _as_text(record.get(key))
        for key in ("shape", "shape_family", "cue_type", "route_type", "source_provenance_origin")
    )
    hint_tokens = set(_content_tokens(hint_text, min_len=1))
    tags: List[str] = []
    if hint_tokens & FORMULA_OR_METRIC_HINT_TOKENS:
        tags.append("formula")
    if hint_tokens & DEFINITION_HINT_TOKENS:
        tags.append("definition")
    if hint_tokens & PROCESS_HINT_TOKENS:
        tags.append("procedure")
    if hint_tokens & EXAMPLE_HINT_TOKENS:
        tags.append("example")
    for tag in _structural_shape_tags(sentence_row, views):
        if tag not in tags:
            tags.append(tag)
    return tags


def _profile_record_evidence_shape_match(record: Mapping[str, Any], tags: Sequence[str]) -> str:
    shape = match_normalize(_as_text(record.get("shape") or record.get("shape_family") or record.get("cue_type")))
    if "formula" in tags or "metric" in shape or "formula" in shape:
        return "formula_or_metric"
    if "definition" in tags or "definition" in shape or "gloss" in shape:
        return "definition_or_gloss"
    if "procedure" in tags or "process" in shape or "procedure" in shape:
        return "process_or_procedure"
    if "example" in tags or "example" in shape:
        return "example_or_context"
    return "context"


def _profile_source_provenance_records(guidance: Optional[Step5xProfileGuidance]) -> List[Dict[str, Any]]:
    if guidance is None:
        return []
    records: List[Dict[str, Any]] = []

    def append_record(
        *,
        ids: Sequence[str],
        origin: str,
        route_id: str = "",
        cue_source: str = "",
        context_only: bool = False,
        primary_terms: Sequence[str] = (),
        shape: str = "",
        shape_family: str = "",
        cue_type: str = "",
        route_type: str = "",
    ) -> None:
        clean_ids = _dedupe_preserve_order(_as_text(item) for item in ids if _as_text(item))
        if not clean_ids:
            return
        records.append(
            {
                "source_ids": clean_ids,
                "source_provenance_origin": origin,
                "route_id": route_id,
                "cue_source": cue_source,
                "context_only": bool(context_only),
                "primary_terms": list(primary_terms),
                "shape": shape,
                "shape_family": shape_family,
                "cue_type": cue_type,
                "route_type": route_type,
            }
        )

    for route in guidance.retrieval_routes:
        route_ids = list(route.source_provenance_ids)
        for sid in _source_ids_from_profile_provenance(route.provenance):
            if sid not in route_ids:
                route_ids.append(sid)
        append_record(
            ids=route_ids,
            origin="retrieval_route",
            route_id=route.route_id,
            cue_source=route.route_trust or "step5p_route_guidance",
            context_only=bool(route.activation == "context_only" or route.broad_context_only),
            primary_terms=route.primary_terms_any,
            cue_type=route.route_type,
            route_type=route.route_type,
        )

    for query in [*guidance.lexical_queries, *guidance.semantic_queries]:
        append_record(
            ids=_source_ids_from_profile_provenance(query.provenance),
            origin=query.retrieval_role or "query_provenance",
            cue_source=query.source,
            context_only=False,
            primary_terms=(query.query,),
            cue_type=query.cue_type,
        )

    for hint in guidance.evidence_shape_hints:
        append_record(
            ids=_source_ids_from_profile_provenance(hint.provenance),
            origin="evidence_shape_hint",
            cue_source=hint.source,
            context_only=False,
            shape=hint.shape,
            shape_family=hint.shape_family,
        )

    for payload in guidance.region_locator_payloads:
        append_record(
            ids=_source_ids_from_profile_provenance(payload.get("provenance")),
            origin="region_locator_payload",
            cue_source=_as_text(payload.get("source") or "region_locator_payload"),
            context_only=True,
            primary_terms=(_as_text(payload.get("locator") or payload.get("term") or payload.get("text") or payload.get("query")),),
            cue_type=_as_text(payload.get("cue_type")),
        )

    return records


def _build_profile_provenance_rehydration_candidates(
    *,
    run_id: str,
    source_overlay_jsonl: str,
    sentence_rows: Sequence[Mapping[str, Any]],
    selected_kc_context_rows: Sequence[Mapping[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    existing_rows: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    identity_index = _sentence_identity_index(sentence_rows)
    existing_profile_keys: set[tuple[str, str, str, str]] = set()
    for row in existing_rows:
        if _as_text(row.get("candidate_source")) != PROFILE_PROVENANCE_REHYDRATION:
            continue
        existing_profile_keys.add(
            (
                _as_text(row.get("kc_id")),
                _as_text(row.get("sentence_id")),
                _as_text(row.get("raw_text_hash")),
                PROFILE_PROVENANCE_REHYDRATION,
            )
        )

    rows: List[Dict[str, Any]] = []
    stats = {
        "enabled": True,
        "candidate_source": PROFILE_PROVENANCE_REHYDRATION,
        "profile_provenance_rehydration_rows": 0,
        "profile_provenance_rehydration_count_by_kc": {},
        "profile_provenance_missing_source_ids_by_kc": {},
        "profile_provenance_requested_source_ids_by_kc": {},
        "profile_provenance_matched_source_ids_by_kc": {},
        "profile_provenance_duplicate_rows_skipped": 0,
    }

    for kc_context in selected_kc_context_rows:
        kc_id = _as_text(kc_context.get("kc_id"))
        guidance = guidance_lookup.get(kc_id)
        records = _profile_source_provenance_records(guidance)
        if not records:
            continue
        shape_preferences = _shape_preference_flags(kc_context, guidance)
        requested_ids: List[str] = []
        matched_ids: List[str] = []
        missing_ids: List[str] = []
        added = 0

        for record in records:
            for source_id in _as_str_list(record.get("source_ids")):
                if source_id not in requested_ids:
                    requested_ids.append(source_id)
                indices = list(identity_index.get(source_id) or [])
                if not indices:
                    if source_id not in missing_ids:
                        missing_ids.append(source_id)
                    continue
                if source_id not in matched_ids:
                    matched_ids.append(source_id)
                for source_row_index in indices:
                    sentence_row = sentence_rows[source_row_index]
                    views = _surface_views(sentence_row)
                    text = _as_text(views.get("text"))
                    raw_hash = _raw_text_hash(text)
                    sentence_id = _as_text(sentence_row.get("sentence_id"))
                    key = (kc_id, sentence_id, raw_hash, PROFILE_PROVENANCE_REHYDRATION)
                    if key in existing_profile_keys:
                        stats["profile_provenance_duplicate_rows_skipped"] += 1
                        continue
                    existing_profile_keys.add(key)

                    unsafe_review_only = bool(
                        sentence_row.get("is_meta")
                        or sentence_row.get("is_nav_boilerplate")
                        or sentence_row.get("is_author_affiliation")
                    )
                    context_only = bool(record.get("context_only") or unsafe_review_only)
                    shape_tags = _profile_record_shape_tags(record, sentence_row, views)
                    evidence_shape_match = _profile_record_evidence_shape_match(record, shape_tags)
                    matched_terms = _as_str_list(record.get("primary_terms"))
                    matched_tokens = _matched_target_tokens_from_terms(terms=matched_terms, views=views)
                    if not matched_tokens:
                        matched_tokens = _matched_target_tokens_from_terms(
                            terms=[_as_text(kc_context.get("canonical_name")), *_as_str_list(kc_context.get("aliases"))],
                            views=views,
                        )
                    candidate = _candidate_row_from_overlay_sentence(
                        sentence_row=sentence_row,
                        source_row_index=int(source_row_index),
                        kc_context=kc_context,
                        run_id=run_id,
                        source_manifest=source_overlay_jsonl,
                        candidate_source=PROFILE_PROVENANCE_REHYDRATION,
                        fallback_tier="profile_provenance",
                        fallback_reason="source_observed_step5p_provenance_rehydration",
                        fallback_score=4.2,
                        fallback_score_reasons=[
                            "source_observed_step5p_provenance_id",
                            "actual_step4_5_sentence_overlay_row",
                        ],
                        matched_surface_terms=matched_terms,
                        matched_target_tokens=matched_tokens,
                        surface_match_type="step5p_source_provenance_id",
                        hierarchy_match_type="source_observed_profile_guidance",
                        anchor_candidate_id="",
                        anchor_sentence_id=sentence_id,
                        shape_preferences=shape_preferences,
                        shape_tags=shape_tags,
                        source_surface=PROFILE_PROVENANCE_REHYDRATION,
                        profile_provenance_context={
                            **record,
                            "source_provenance_id": source_id,
                            "evidence_shape_match": evidence_shape_match,
                            "context_only": context_only,
                            "review_only_candidate": context_only,
                        },
                    )
                    if unsafe_review_only:
                        candidate["near_miss_reason"] = "meta_or_navigation_source_row"
                        candidate["retrieval_failure_signals"] = _dedupe_preserve_order([
                            *_as_str_list(candidate.get("retrieval_failure_signals")),
                            "context_only_support",
                        ])
                    rows.append(candidate)
                    added += 1

        if requested_ids:
            stats["profile_provenance_requested_source_ids_by_kc"][kc_id] = len(requested_ids)
        if matched_ids:
            stats["profile_provenance_matched_source_ids_by_kc"][kc_id] = len(matched_ids)
        if missing_ids:
            stats["profile_provenance_missing_source_ids_by_kc"][kc_id] = missing_ids
        if added:
            stats["profile_provenance_rehydration_count_by_kc"][kc_id] = added

    stats["profile_provenance_rehydration_rows"] = len(rows)
    return rows, stats


def _source_surface_breakdown(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        surface = _as_text(row.get("source_surface") or row.get("candidate_source") or "unknown")
        counter[surface] += 1
    return dict(counter)


def _matched_target_tokens_from_terms(
    *,
    terms: Sequence[str],
    views: Mapping[str, Any],
) -> List[str]:
    surface_tokens = set(
        _content_tokens(str(views.get("text") or ""), min_len=1)
        + _content_tokens(str(views.get("source_block_text") or ""), min_len=1)
        + _content_tokens(str(views.get("heading_text") or ""), min_len=1)
    )
    hits: List[str] = []
    for term in terms:
        for token in _content_tokens(term, min_len=1):
            if token in surface_tokens and token not in hits:
                hits.append(token)
    return hits


def _structural_neighbor_rank(
    *,
    sentence_row: Mapping[str, Any],
    shape_tags: Sequence[str],
    same_patch: bool,
    same_reveal_group: bool,
    shape_preferences: Mapping[str, bool],
    views: Mapping[str, Any],
) -> float:
    score = 0.0
    if same_patch:
        score += 1.2
    elif same_reveal_group:
        score += 0.8
    if "formula" in shape_tags:
        score += 1.2 + (0.8 if bool(shape_preferences.get("formula_or_metric")) else 0.0)
    if "definition" in shape_tags:
        score += 1.0 + (0.45 if bool(shape_preferences.get("definition")) else 0.0)
    if "procedure" in shape_tags:
        score += 0.75 + (0.35 if bool(shape_preferences.get("process")) else 0.0)
    if "example" in shape_tags:
        score += 0.55 + (0.25 if bool(shape_preferences.get("example")) else 0.0)
    if not _looks_fragmentary(str(views.get("text") or ""), {"support_profile": {}}):
        score += 0.15
    if not _looks_prompt_like(str(views.get("text") or "")):
        score += 0.1
    if bool(sentence_row.get("is_definition_like")) and not bool(sentence_row.get("is_heading_like")):
        score += 0.15
    return round(score, 6)


def _structural_region_indices(
    *,
    anchor_index: int,
    sentence_row: Mapping[str, Any],
    patch_index: Mapping[str, Sequence[int]],
    reveal_index: Mapping[str, Sequence[int]],
) -> List[int]:
    ordered: List[int] = []
    seen: set[int] = set()
    for idx in [anchor_index]:
        seen.add(idx)
        ordered.append(idx)
    patch_id = _as_text(sentence_row.get("patch_id"))
    reveal_group_id = _as_text(sentence_row.get("reveal_group_id"))
    for idx in patch_index.get(patch_id, []) if patch_id else []:
        if idx in seen:
            continue
        seen.add(idx)
        ordered.append(idx)
    for idx in reveal_index.get(reveal_group_id, []) if reveal_group_id else []:
        if idx in seen:
            continue
        seen.add(idx)
        ordered.append(idx)
    return ordered


def _candidate_row_from_overlay_sentence(
    *,
    sentence_row: Mapping[str, Any],
    source_row_index: int,
    kc_context: Mapping[str, Any],
    run_id: str,
    source_manifest: str,
    candidate_source: str,
    fallback_tier: str,
    fallback_reason: str,
    fallback_score: float,
    fallback_score_reasons: Sequence[str],
    matched_surface_terms: Sequence[str],
    matched_target_tokens: Sequence[str],
    surface_match_type: str,
    hierarchy_match_type: str,
    anchor_candidate_id: str,
    anchor_sentence_id: str,
    shape_preferences: Mapping[str, bool],
    shape_tags: Sequence[str],
    source_surface: str = SOURCE_SURFACE_FALLBACK,
    profile_provenance_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    views = _surface_views(sentence_row)
    text = _as_text(views.get("text"))
    source_block_text = _as_text(views.get("source_block_text"))
    page_index = _as_int(sentence_row.get("page_index"))
    patch_id = _as_text(sentence_row.get("patch_id"))
    sentence_id = _as_text(sentence_row.get("sentence_id"))
    block_id = _as_text(sentence_row.get("block_id"))
    raw_text_hash = _raw_text_hash(text)
    structural_flags = build_structural_flags(text, source_block_text, sentence_row)
    exact_name_phrase, exact_alias_phrase = _direct_exact_match_flags(
        canonical_name=_as_text(kc_context.get("canonical_name")),
        aliases=_as_str_list(kc_context.get("aliases")),
        views=views,
    )
    policy_plan = dict(kc_context.get("step5x_retrieval_policy_plan") or {}) if isinstance(kc_context.get("step5x_retrieval_policy_plan"), Mapping) else {}
    query_plan_id = _as_text(policy_plan.get("query_plan_id") or kc_context.get("query_plan_id"))
    profile_provenance = dict(profile_provenance_context or {})
    if candidate_source == PROFILE_PROVENANCE_REHYDRATION:
        retrieval_intent = PROFILE_PROVENANCE_REHYDRATION
        window_build_mode = "source_sentence"
    elif candidate_source == STRUCTURAL_NEIGHBOR_REASON:
        retrieval_intent = "section_neighbor_expansion"
        window_build_mode = "assembled_local_window"
    elif surface_match_type.endswith("heading"):
        retrieval_intent = "heading_anchor_expansion"
        window_build_mode = "source_sentence"
    elif "formula" in shape_tags:
        retrieval_intent = "head_term_plus_metric_frame"
        window_build_mode = "source_sentence"
    elif "definition" in shape_tags:
        retrieval_intent = "head_term_plus_definition_frame"
        window_build_mode = "source_sentence"
    else:
        retrieval_intent = "label_exact_surface" if exact_name_phrase or exact_alias_phrase else "label_normalized_surface"
        window_build_mode = "source_sentence"
    evidence_shape_match = _as_text(profile_provenance.get("evidence_shape_match")) or (
        "formula_or_metric" if "formula" in shape_tags else ("definition_or_gloss" if "definition" in shape_tags else "context")
    )
    target_binding_basis = (
        "source_observed_profile_provenance"
        if candidate_source == PROFILE_PROVENANCE_REHYDRATION
        else f"{surface_match_type}+{hierarchy_match_type}"
    )
    anchor_scope = (
        "exact_source_provenance"
        if candidate_source == PROFILE_PROVENANCE_REHYDRATION
        else ("same_patch_or_reveal_group" if candidate_source == STRUCTURAL_NEIGHBOR_REASON else "same_sentence")
    )
    support_roles: List[str] = []
    if "definition" in shape_tags:
        support_roles.append("definitional_anchor")
    if "formula" in shape_tags:
        support_roles.append("formula_or_metric")
    if "procedure" in shape_tags:
        support_roles.append("process_or_procedure")
    if "example" in shape_tags:
        support_roles.append("example_or_context")
    profile_context_only = bool(profile_provenance.get("context_only"))
    profile_review_only = bool(profile_context_only or profile_provenance.get("review_only_candidate"))
    support_profile = {
        "anchor_quality": "source_observed" if candidate_source == PROFILE_PROVENANCE_REHYDRATION else ("strong" if candidate_source == STRUCTURAL_ANCHOR_REASON else "usable"),
        "preferred_support_role": "definitional_anchor" if "definition" in shape_tags else "other",
        "support_roles": support_roles,
        "formula_support_score": round(
            (1.0 if "formula" in shape_tags else 0.0)
            + (0.75 if "formula" in shape_tags and bool(shape_preferences.get("formula_or_metric")) else 0.0),
            6,
        ),
        "context_completion_score": 0.0,
        "contamination_penalty": 0.0,
        "needs_context_completion": False,
        "has_context_completion_source": False,
        "formula_auxiliary_only": bool("formula" in shape_tags and "definition" not in shape_tags),
        "contamination_exclusion_hint": False,
        "relation_like": bool("definition" in shape_tags or "procedure" in shape_tags),
        "generic_context_only": profile_context_only,
        "fragmentary_surface": bool(structural_flags.get("looks_fragmentary")),
        "source_block_completion_used": False,
        "candidate_source": candidate_source,
        "fallback_tier": fallback_tier,
        "fallback_reason": fallback_reason,
        "fallback_score": round(float(fallback_score), 6),
        "fallback_score_reasons": list(fallback_score_reasons),
        "matched_surface_terms": list(matched_surface_terms),
        "matched_target_tokens": list(matched_target_tokens),
        "surface_match_type": surface_match_type,
        "hierarchy_match_type": hierarchy_match_type,
        "hierarchy_compatibility_signal": hierarchy_match_type,
        "target_branch_tokens": [],
        "fallback_caution_reason": "",
        "structural_anchor_support": candidate_source == STRUCTURAL_NEIGHBOR_REASON,
        "structural_anchor_support_score": round(1.4 if candidate_source == STRUCTURAL_NEIGHBOR_REASON else 0.6, 6),
        "structural_anchor_candidate_id": anchor_candidate_id,
        "structural_anchor_sentence_id": anchor_sentence_id,
        "shape_hint_formula_or_metric": bool(shape_preferences.get("formula_or_metric")),
        "shape_hint_definition_like": bool(shape_preferences.get("definition")),
        "shape_hint_process_like": bool(shape_preferences.get("process")),
        "shape_hint_example_like": bool(shape_preferences.get("example")),
        "structural_shape_tags": list(shape_tags),
        "query_plan_id": query_plan_id,
        "retrieval_intent": retrieval_intent,
        "candidate_origin": retrieval_intent,
        "target_surface_origin": surface_match_type,
        "target_binding_basis": target_binding_basis,
        "evidence_shape_match": evidence_shape_match,
        "anchor_scope": anchor_scope,
        "window_build_mode": window_build_mode,
        "review_only_candidate": profile_review_only,
        "near_miss_reason": "context_only_support" if profile_context_only else "",
        "retrieval_failure_signals": [],
        "authority_contract": AUTHORITY_CONTRACT,
    }
    if candidate_source == PROFILE_PROVENANCE_REHYDRATION:
        support_profile.update(
            {
                "candidate_source": PROFILE_PROVENANCE_REHYDRATION,
                "fallback_tier": "profile_provenance",
                "fallback_reason": "source_observed_step5p_provenance_rehydration",
                "fallback_score": round(float(fallback_score), 6),
                "fallback_score_reasons": list(fallback_score_reasons),
                "profile_output_role": "retrieval_control_metadata_not_evidence",
                "source_observed_profile_provenance": True,
                "step5p_source_provenance_rehydrated": True,
                "source_provenance_id": _as_text(profile_provenance.get("source_provenance_id")),
                "route_id": _as_text(profile_provenance.get("route_id")),
                "cue_source": _as_text(profile_provenance.get("cue_source")),
            }
        )
    alignment_breakdown = {
        "name_or_alias_hit": bool(matched_surface_terms),
        "exact_name_phrase": exact_name_phrase,
        "exact_alias_phrase": exact_alias_phrase,
        "canonical_name_token_hits": len(set(_content_tokens(_as_text(kc_context.get("canonical_name")))) & set(_content_tokens(text))),
        "alias_token_hits": len(
            set(token for alias in _as_str_list(kc_context.get("aliases")) for token in _content_tokens(alias))
            & set(_content_tokens(text))
        ),
        "name_or_alias_token_hits": len(set(matched_target_tokens) & set(_content_tokens(text))),
        "context_keyword_hits": 0,
        "heading_name_hits": 1 if surface_match_type.endswith("heading") else 0,
        "competitor_token_hits": 0,
        "doc_group": "",
        "kc_group": "",
        "doc_mismatch": False,
        "hard_suppressed": False,
        "strong_same_topic": True,
        "strong_structured_candidate": candidate_source == STRUCTURAL_ANCHOR_REASON,
        "contamination_risk": "low",
        "contamination_signals": [],
        "fallback_candidate": True,
        "fallback_tier": fallback_tier,
        "matched_surface_terms": list(matched_surface_terms),
        "matched_target_tokens": list(matched_target_tokens),
        "surface_match_type": surface_match_type,
        "hierarchy_match_type": hierarchy_match_type,
        "hierarchy_compatibility_signal": hierarchy_match_type,
        "target_branch_tokens": [],
        "fallback_score": round(float(fallback_score), 6),
        "fallback_score_reasons": list(fallback_score_reasons),
        "fallback_caution_reason": "",
        "query_plan_id": query_plan_id,
        "retrieval_intent": retrieval_intent,
        "candidate_origin": retrieval_intent,
        "target_surface_origin": surface_match_type,
        "target_binding_basis": target_binding_basis,
        "evidence_shape_match": evidence_shape_match,
        "anchor_scope": anchor_scope,
        "window_build_mode": window_build_mode,
        "authority_contract": AUTHORITY_CONTRACT,
        "profile_output_role": "retrieval_control_metadata_not_evidence" if candidate_source == PROFILE_PROVENANCE_REHYDRATION else "",
        "source_observed_profile_provenance": bool(candidate_source == PROFILE_PROVENANCE_REHYDRATION),
        "step5p_source_provenance_rehydrated": bool(candidate_source == PROFILE_PROVENANCE_REHYDRATION),
        "flags": {
            "is_meta": bool(sentence_row.get("is_meta")),
            "is_nav_boilerplate": bool(sentence_row.get("is_nav_boilerplate")),
            "is_author_affiliation": bool(sentence_row.get("is_author_affiliation")),
            "is_transition_text": bool(sentence_row.get("is_transition_text")),
            "is_heading_like": bool(sentence_row.get("is_heading_like")),
            "is_formula_like": bool(sentence_row.get("is_formula_like")),
            "is_definition_like": bool(sentence_row.get("is_definition_like")),
            "is_procedure_like": bool(sentence_row.get("is_procedure_like")),
            "is_example_like": bool(sentence_row.get("is_example_like")),
        },
    }
    provenance = {
        "from_step": "step4_5_sentence_overlay",
        "source_manifest": source_manifest,
        "source_jsonl": source_manifest,
        "source_row_index": int(source_row_index),
        "source_evidence_index": 0,
        "candidate_source": candidate_source,
        "fallback_tier": fallback_tier,
        "fallback_reason": fallback_reason,
        "fallback_score": round(float(fallback_score), 6),
        "fallback_score_reasons": list(fallback_score_reasons),
        "matched_surface_terms": list(matched_surface_terms),
        "matched_target_tokens": list(matched_target_tokens),
        "surface_match_type": surface_match_type,
        "hierarchy_match_type": hierarchy_match_type,
        "hierarchy_compatibility_signal": hierarchy_match_type,
        "source_heading_text": _as_text(views.get("heading_text")),
        "fallback_caution_reason": "",
        "anchor_candidate_id": anchor_candidate_id,
        "anchor_sentence_id": anchor_sentence_id,
        "anchor_patch_id": patch_id if candidate_source == STRUCTURAL_ANCHOR_REASON else "",
        "anchor_reveal_group_id": _as_text(sentence_row.get("reveal_group_id")) if candidate_source == STRUCTURAL_ANCHOR_REASON else "",
        "query_plan_id": query_plan_id,
        "retrieval_intent": retrieval_intent,
        "candidate_origin": retrieval_intent,
        "target_surface_origin": surface_match_type,
        "target_binding_basis": target_binding_basis,
        "evidence_shape_match": evidence_shape_match,
        "anchor_scope": anchor_scope,
        "window_build_mode": window_build_mode,
        "review_only_candidate": profile_review_only,
        "near_miss_reason": "context_only_support" if profile_context_only else "",
        "retrieval_failure_signals": [],
        "authority_contract": AUTHORITY_CONTRACT,
    }
    if candidate_source == PROFILE_PROVENANCE_REHYDRATION:
        provenance.update(
            {
                "step5p_profile_guidance_used": True,
                "step5p_profile_guidance_role": "retrieval_control_metadata_not_evidence",
                "profile_output_role": "retrieval_control_metadata_not_evidence",
                "step5p_source_provenance_rehydrated": True,
                "source_provenance_id": _as_text(profile_provenance.get("source_provenance_id")),
                "source_provenance_origin": _as_text(profile_provenance.get("source_provenance_origin")),
                "route_id": _as_text(profile_provenance.get("route_id")),
                "cue_source": _as_text(profile_provenance.get("cue_source")),
            }
        )
    return {
        "candidate_id": build_candidate_id(
            kc_id=_as_text(kc_context.get("kc_id")),
            source_surface=source_surface,
            source_manifest=source_manifest,
            source_row_index=source_row_index,
            source_evidence_index=0,
            doc_id=_as_text(sentence_row.get("doc_id")),
            block_id=block_id,
            sentence_id=sentence_id,
            patch_id=patch_id,
            page_index=page_index,
            raw_text_hash=raw_text_hash,
        ),
        "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
        "run_id": run_id,
        "source_surface": source_surface,
        "source_manifest": source_manifest,
        "source_row_index": int(source_row_index),
        "source_evidence_index": 0,
        "kc_id": _as_text(kc_context.get("kc_id")),
        "canonical_name": _as_text(kc_context.get("canonical_name")),
        "aliases": _as_str_list(kc_context.get("aliases")),
        "topic_path_ids": _as_str_list(kc_context.get("topic_path_ids")),
        "topic_path_labels": _as_str_list(kc_context.get("topic_path_labels")),
        "parent_topic_id": _as_text(kc_context.get("parent_topic_id")),
        "parent_topic_label": _as_text(kc_context.get("parent_topic_label")),
        "knowledge_unit_id": _as_text(policy_plan.get("knowledge_unit_id") or kc_context.get("knowledge_unit_id") or kc_context.get("kc_id")),
        "knowledge_unit_type": _as_text(policy_plan.get("knowledge_unit_type") or kc_context.get("knowledge_unit_type") or "kc"),
        "step5x_retrieval_policy_plan": policy_plan,
        "query_plan_id": query_plan_id,
        "retrieval_intent": retrieval_intent,
        "candidate_origin": retrieval_intent,
        "target_surface_origin": surface_match_type,
        "target_binding_basis": target_binding_basis,
        "evidence_shape_match": evidence_shape_match,
        "anchor_scope": anchor_scope,
        "window_build_mode": window_build_mode,
        "review_only_candidate": profile_review_only,
        "near_miss_reason": "context_only_support" if profile_context_only else "",
        "retrieval_failure_signals": ["context_only_support"] if profile_context_only else [],
        "authority_contract": AUTHORITY_CONTRACT,
        "source_kc_id": _as_text(kc_context.get("kc_id")),
        "source_canonical_name": _as_text(kc_context.get("canonical_name")),
        "granularity": "sentence" if _as_text(sentence_row.get("sentence_id")) or sentence_row.get("sent_idx") is not None or text else "block",
        "text": text,
        "source_block_text": source_block_text,
        "context_text": _as_text(views.get("context_text")),
        "doc_id": _as_text(sentence_row.get("doc_id")),
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": _as_int(sentence_row.get("sent_idx")),
        "patch_id": patch_id,
        "patch_heading": _as_text(sentence_row.get("patch_heading")),
        "reveal_group_id": _as_text(sentence_row.get("reveal_group_id")),
        "layer": _as_text(sentence_row.get("layer")),
        "bbox": list(sentence_row.get("bbox") or []) if isinstance(sentence_row.get("bbox"), list) else [],
        "char_start": _as_int(sentence_row.get("char_start")),
        "char_end": _as_int(sentence_row.get("char_end")),
        "retrieval_scores": {
            "combined": round(float(fallback_score), 6),
            "structural_anchor_support_score": round(
                float(support_profile.get("structural_anchor_support_score") or 0.0),
                6,
            ),
            "shape_hint_formula_or_metric": bool(shape_preferences.get("formula_or_metric")),
            "shape_hint_definition_like": bool(shape_preferences.get("definition")),
        },
        "alignment_score": round(float(fallback_score), 6),
        "alignment_breakdown": alignment_breakdown,
        "support_profile": support_profile,
        "structural_flags": structural_flags,
        "raw_text_hash": raw_text_hash,
        "provenance": provenance,
        "candidate_source": candidate_source,
        "fallback_tier": fallback_tier,
        "fallback_reason": fallback_reason,
        "fallback_score": round(float(fallback_score), 6),
        "fallback_score_reasons": list(fallback_score_reasons),
        "matched_surface_terms": list(matched_surface_terms),
        "matched_target_tokens": list(matched_target_tokens),
        "surface_match_type": surface_match_type,
        "hierarchy_match_type": hierarchy_match_type,
        "hierarchy_compatibility_signal": hierarchy_match_type,
        "target_branch_tokens": [],
        "source_heading_text": _as_text(views.get("heading_text")),
        "fallback_caution_reason": "",
    }


def _append_unique_candidate_row(
    rows: List[Dict[str, Any]],
    row: Dict[str, Any],
    *,
    seen_ids: set[str],
) -> bool:
    candidate_id = _as_text(row.get("candidate_id"))
    if not candidate_id or candidate_id in seen_ids:
        return False
    seen_ids.add(candidate_id)
    rows.append(row)
    return True


def _expand_structural_candidates_from_anchors(
    *,
    run_id: str,
    source_overlay_jsonl: str,
    sentence_rows: Sequence[Mapping[str, Any]],
    selected_kc_context_rows: Sequence[Mapping[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    existing_rows: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    patch_index: Dict[str, List[int]] = {}
    reveal_index: Dict[str, List[int]] = {}
    for idx, sentence_row in enumerate(sentence_rows):
        patch_id = _as_text(sentence_row.get("patch_id"))
        reveal_group_id = _as_text(sentence_row.get("reveal_group_id"))
        if patch_id:
            patch_index.setdefault(patch_id, []).append(idx)
        if reveal_group_id:
            reveal_index.setdefault(reveal_group_id, []).append(idx)

    seen_ids = {_as_text(row.get("candidate_id")) for row in existing_rows if _as_text(row.get("candidate_id"))}
    output_rows: List[Dict[str, Any]] = []
    stats = {
        "enabled": True,
        "candidate_source": STRUCTURAL_NEIGHBOR_REASON,
        "anchors_considered_by_kc": {},
        "anchors_selected_by_kc": {},
        "anchor_rows_added_by_kc": {},
        "neighbor_rows_added_by_kc": {},
        "rejected_unsafe_rows": 0,
        "rejected_negative_constraint_rows": 0,
        "rejected_duplicate_rows": 0,
        "source_window_anchor_ids_requested_by_kc": {},
        "source_window_anchor_ids_matched_by_kc": {},
        "source_window_anchor_rows_added_by_kc": {},
        "total_rows_added": 0,
    }

    sentence_id_index = _sentence_identity_index(sentence_rows)

    for kc_context in selected_kc_context_rows:
        kc_id = _as_text(kc_context.get("kc_id"))
        guidance = guidance_lookup.get(kc_id)
        anchor_terms = _anchor_surface_terms(kc_context, guidance)
        negative_terms = _negative_constraint_terms(guidance)
        shape_preferences = _shape_preference_flags(kc_context, guidance)
        anchors: List[Dict[str, Any]] = []

        for source_row_index, sentence_row in enumerate(sentence_rows):
            anchor_hit = _anchor_hits_for_sentence(sentence_row, anchor_terms=anchor_terms)
            matched_terms = anchor_hit["matched_terms"]
            if not matched_terms:
                continue
            views = anchor_hit["views"]
            if _sentence_row_matches_negative_constraint(views, negative_terms):
                stats["rejected_negative_constraint_rows"] += 1
                continue
            if _is_unsafe_sentence_row(sentence_row, views):
                stats["rejected_unsafe_rows"] += 1
                continue
            shape_tags = _structural_shape_tags(sentence_row, views)
            region_indices = _structural_region_indices(
                anchor_index=source_row_index,
                sentence_row=sentence_row,
                patch_index=patch_index,
                reveal_index=reveal_index,
            )
            region_structural_count = 0
            for region_index in region_indices:
                region_row = sentence_rows[region_index]
                region_views = _surface_views(region_row)
                if _is_unsafe_sentence_row(region_row, region_views):
                    continue
                if _sentence_row_matches_negative_constraint(region_views, negative_terms):
                    continue
                if _structural_shape_tags(region_row, region_views):
                    region_structural_count += 1
            priority = float(anchor_hit["surface_priority"]) + min(3, region_structural_count) * 0.6
            if shape_tags:
                priority += 0.8
            anchors.append(
                {
                    "source_row_index": source_row_index,
                    "sentence_row": sentence_row,
                    "views": views,
                    "matched_terms": matched_terms,
                    "shape_tags": shape_tags,
                    "region_indices": region_indices,
                    "priority": round(priority, 6),
                }
            )

        existing_anchor_indices = {int(item["source_row_index"]) for item in anchors}
        source_window_indices = _source_window_anchor_indices(guidance, sentence_id_index)
        stats["source_window_anchor_ids_requested_by_kc"][kc_id] = len(guidance.source_window_ids) if guidance else 0
        stats["source_window_anchor_ids_matched_by_kc"][kc_id] = len(source_window_indices)

        for source_row_index in source_window_indices:
            if source_row_index in existing_anchor_indices:
                continue
            sentence_row = sentence_rows[source_row_index]
            views = _surface_views(sentence_row)
            if _sentence_row_matches_negative_constraint(views, negative_terms):
                stats["rejected_negative_constraint_rows"] += 1
                continue
            if _is_unsafe_sentence_row(sentence_row, views):
                stats["rejected_unsafe_rows"] += 1
                continue
            shape_tags = _structural_shape_tags(sentence_row, views)
            region_indices = _structural_region_indices(
                anchor_index=source_row_index,
                sentence_row=sentence_row,
                patch_index=patch_index,
                reveal_index=reveal_index,
            )
            region_structural_count = 0
            for region_index in region_indices:
                region_row = sentence_rows[region_index]
                region_views = _surface_views(region_row)
                if _is_unsafe_sentence_row(region_row, region_views):
                    continue
                if _sentence_row_matches_negative_constraint(region_views, negative_terms):
                    continue
                if _structural_shape_tags(region_row, region_views):
                    region_structural_count += 1
            token_hits = _matched_target_tokens_from_terms(terms=anchor_terms, views=views)
            priority = 2.6 + min(3, region_structural_count) * 0.6 + min(4, len(token_hits)) * 0.35
            if shape_tags:
                priority += 0.8
            anchors.append(
                {
                    "source_row_index": source_row_index,
                    "sentence_row": sentence_row,
                    "views": views,
                    "matched_terms": [],
                    "matched_target_tokens": token_hits,
                    "shape_tags": shape_tags,
                    "region_indices": region_indices,
                    "priority": round(priority, 6),
                    "anchor_origin": "step5p_source_window_rehydration",
                }
            )
            existing_anchor_indices.add(source_row_index)

        anchors.sort(
            key=lambda item: (
                0 if _as_text(item.get("anchor_origin")) == "step5p_source_window_rehydration" else 1,
                -float(item["priority"]),
                int(item["source_row_index"]),
                _as_text(item["sentence_row"].get("sentence_id")),
            )
        )
        selected_anchors = anchors[:DEFAULT_MAX_STRUCTURAL_ANCHORS_PER_KC]
        stats["anchors_considered_by_kc"][kc_id] = len(anchors)
        stats["anchors_selected_by_kc"][kc_id] = len(selected_anchors)

        added_for_kc = 0
        anchor_rows_added = 0
        neighbor_rows_added = 0

        for anchor in selected_anchors:
            if added_for_kc >= DEFAULT_MAX_STRUCTURAL_EXPANDED_CANDIDATES_PER_KC:
                break
            anchor_row = anchor["sentence_row"]
            anchor_views = anchor["views"]
            anchor_sentence_id = _as_text(anchor_row.get("sentence_id"))
            matched_terms = list(anchor["matched_terms"])
            matched_target_tokens = list(anchor.get("matched_target_tokens") or [])
            if not matched_target_tokens:
                matched_target_tokens = _dedupe_preserve_order(
                    token for term in matched_terms for token in _content_tokens(term, min_len=1)
                )
            anchor_shape_tags = list(anchor["shape_tags"])
            anchor_origin = _as_text(anchor.get("anchor_origin"))
            surface_match_type = (
                "profile_source_window_anchor"
                if anchor_origin == "step5p_source_window_rehydration" and not matched_terms
                else "exact_anchor_text_or_heading"
            )
            anchor_score = float(anchor["priority"]) + 1.2
            anchor_candidate = _candidate_row_from_overlay_sentence(
                sentence_row=anchor_row,
                source_row_index=int(anchor["source_row_index"]),
                kc_context=kc_context,
                run_id=run_id,
                source_manifest=source_overlay_jsonl,
                candidate_source=STRUCTURAL_ANCHOR_REASON,
                fallback_tier="exact_surface",
                fallback_reason=(
                    "step5p_source_window_rehydration"
                    if anchor_origin == "step5p_source_window_rehydration"
                    else STRUCTURAL_ANCHOR_REASON
                ),
                fallback_score=anchor_score,
                fallback_score_reasons=(
                    ["step5p_source_window_rehydrated", "actual_step4_5_sentence_overlay_row", "structural_region_recovery"]
                    if anchor_origin == "step5p_source_window_rehydration"
                    else ["exact_anchor_surface_match", "structural_region_recovery"]
                ),
                matched_surface_terms=matched_terms,
                matched_target_tokens=matched_target_tokens,
                surface_match_type=surface_match_type,
                hierarchy_match_type="structural_anchor_region",
                anchor_candidate_id="",
                anchor_sentence_id=anchor_sentence_id,
                shape_preferences=shape_preferences,
                shape_tags=anchor_shape_tags,
            )
            anchor_candidate_id = _as_text(anchor_candidate.get("candidate_id"))
            if _append_unique_candidate_row(output_rows, anchor_candidate, seen_ids=seen_ids):
                anchor_rows_added += 1
                added_for_kc += 1
            else:
                stats["rejected_duplicate_rows"] += 1

            neighbor_candidates: List[Tuple[float, int, Mapping[str, Any], Mapping[str, Any], List[str]]] = []
            anchor_patch_id = _as_text(anchor_row.get("patch_id"))
            anchor_reveal_group_id = _as_text(anchor_row.get("reveal_group_id"))
            for region_index in anchor["region_indices"]:
                if region_index == int(anchor["source_row_index"]):
                    continue
                region_row = sentence_rows[region_index]
                region_views = _surface_views(region_row)
                if _is_unsafe_sentence_row(region_row, region_views):
                    stats["rejected_unsafe_rows"] += 1
                    continue
                if _sentence_row_matches_negative_constraint(region_views, negative_terms):
                    stats["rejected_negative_constraint_rows"] += 1
                    continue
                shape_tags = _structural_shape_tags(region_row, region_views)
                if not shape_tags:
                    continue
                same_patch = bool(anchor_patch_id and anchor_patch_id == _as_text(region_row.get("patch_id")))
                same_reveal_group = bool(
                    anchor_reveal_group_id and anchor_reveal_group_id == _as_text(region_row.get("reveal_group_id"))
                )
                rank = _structural_neighbor_rank(
                    sentence_row=region_row,
                    shape_tags=shape_tags,
                    same_patch=same_patch,
                    same_reveal_group=same_reveal_group,
                    shape_preferences=shape_preferences,
                    views=region_views,
                )
                neighbor_candidates.append((rank, region_index, region_row, region_views, shape_tags))

            neighbor_candidates.sort(
                key=lambda item: (-float(item[0]), int(item[1]), _as_text(item[2].get("sentence_id")))
            )
            for rank, region_index, region_row, _, shape_tags in neighbor_candidates[:DEFAULT_MAX_STRUCTURAL_NEIGHBORS_PER_ANCHOR]:
                if added_for_kc >= DEFAULT_MAX_STRUCTURAL_EXPANDED_CANDIDATES_PER_KC:
                    break
                same_patch = bool(anchor_patch_id and anchor_patch_id == _as_text(region_row.get("patch_id")))
                hierarchy_match_type = "same_patch_structural_neighbor" if same_patch else "same_reveal_group_structural_neighbor"
                neighbor_candidate = _candidate_row_from_overlay_sentence(
                    sentence_row=region_row,
                    source_row_index=int(region_index),
                    kc_context=kc_context,
                    run_id=run_id,
                    source_manifest=source_overlay_jsonl,
                    candidate_source=STRUCTURAL_NEIGHBOR_REASON,
                    fallback_tier="structural_neighbor",
                    fallback_reason=STRUCTURAL_NEIGHBOR_REASON,
                    fallback_score=float(rank),
                    fallback_score_reasons=[
                        "same_patch_or_reveal_group_anchor_expansion",
                        "structural_shape_flag_match",
                    ],
                    matched_surface_terms=matched_terms,
                    matched_target_tokens=matched_target_tokens,
                    surface_match_type="anchor_term_neighbor",
                    hierarchy_match_type=hierarchy_match_type,
                    anchor_candidate_id=anchor_candidate_id,
                    anchor_sentence_id=anchor_sentence_id,
                    shape_preferences=shape_preferences,
                    shape_tags=shape_tags,
                )
                if _append_unique_candidate_row(output_rows, neighbor_candidate, seen_ids=seen_ids):
                    neighbor_rows_added += 1
                    added_for_kc += 1
                else:
                    stats["rejected_duplicate_rows"] += 1

        stats["anchor_rows_added_by_kc"][kc_id] = anchor_rows_added
        stats["neighbor_rows_added_by_kc"][kc_id] = neighbor_rows_added
        source_window_anchor_rows = 0
        for row in output_rows:
            if _as_text(row.get("kc_id")) != kc_id:
                continue
            support_profile = row.get("support_profile") if isinstance(row.get("support_profile"), Mapping) else {}
            if _as_text(support_profile.get("fallback_reason")) == "step5p_source_window_rehydration":
                source_window_anchor_rows += 1
        stats["source_window_anchor_rows_added_by_kc"][kc_id] = source_window_anchor_rows

    stats["total_rows_added"] = len(output_rows)
    return output_rows, stats


def _topic_path_labels(row: Mapping[str, Any], canonical_name: str) -> List[str]:
    for key in ("topic_path_labels", "source_hierarchy_path", "kc_path"):
        raw = _as_str_list(row.get(key))
        if not raw:
            continue
        if canonical_name and raw and match_normalize(raw[-1]) == match_normalize(canonical_name):
            return raw[:-1]
        return raw
    return []


def _topic_path_ids(row: Mapping[str, Any], label_count: int) -> List[str]:
    for key in ("topic_path_ids", "ancestor_node_ids", "ancestor_hier_node_ids"):
        raw = _as_str_list(row.get(key))
        if raw:
            return raw[:label_count]
    return []


def _parent_topic_id(row: Mapping[str, Any], topic_path_ids: Sequence[str]) -> str:
    for key in ("parent_topic_id", "parent_node_id", "parent_hier_node_id"):
        text = _as_text(row.get(key))
        if text:
            return text
    return str(topic_path_ids[-1]) if topic_path_ids else ""


def _parent_topic_label(topic_path_labels: Sequence[str]) -> str:
    return str(topic_path_labels[-1]) if topic_path_labels else ""


def _canonical_name_from_registry_row(row: Mapping[str, Any]) -> str:
    """Return the KC display label across legacy and seedless hierarchy schemas.

    The seedless hierarchy overlay uses label/name rather than canonical_name.
    Step 5x needs a stable canonical target surface, but this must not use
    seed_definition or any definition-like fallback.
    """
    for key in ("canonical_name", "label", "name", "title"):
        text = _as_text(row.get(key))
        if text:
            return text
    return ""


def _knowledge_unit_type_from_registry_row(row: Mapping[str, Any]) -> str:
    raw = _as_text(
        row.get("knowledge_unit_type")
        or row.get("unit_type")
        or row.get("node_type")
        or row.get("type")
    ).lower()
    if raw in {"kc", "knowledge_component", "knowledge component", "atomic_kc"}:
        return "kc"
    if raw in {"topic", "section", "module"}:
        return "topic"
    if _as_text(row.get("kc_id")) or raw in {"leaf", "leaves"}:
        return "kc"
    return "kc"


def _aliases_from_registry_row(row: Mapping[str, Any], canonical_name: str) -> List[str]:
    aliases: List[str] = []
    aliases.extend(_as_str_list(row.get("aliases")))
    for key in ("label", "name", "title"):
        text = _as_text(row.get(key))
        if text:
            aliases.append(text)

    canonical_norm = match_normalize(canonical_name)
    output: List[str] = []
    seen: set[str] = set()
    for alias in aliases:
        text = _as_text(alias)
        if not text:
            continue
        norm = match_normalize(text)
        if not norm or norm == canonical_norm or norm in seen:
            continue
        seen.add(norm)
        output.append(text)
    return output


def _merge_aliases(*values: Any, canonical_name: str = "") -> List[str]:
    merged: List[str] = []
    for value in values:
        merged.extend(_as_str_list(value))
    canonical_norm = match_normalize(canonical_name)
    output: List[str] = []
    seen: set[str] = set()
    for alias in merged:
        text = _as_text(alias)
        if not text:
            continue
        norm = match_normalize(text)
        if not norm or norm == canonical_norm or norm in seen:
            continue
        seen.add(norm)
        output.append(text)
    return output


def build_kc_context_lookup(registry_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for row in registry_rows:
        kc_id = _as_text(row.get("kc_id") or row.get("knowledge_unit_id") or row.get("node_id"))
        if not kc_id:
            continue
        unit_type = _knowledge_unit_type_from_registry_row(row)
        if unit_type != "kc":
            continue
        canonical_name = _canonical_name_from_registry_row(row)
        topic_path_labels = _topic_path_labels(row, canonical_name)
        topic_path_ids = _topic_path_ids(row, len(topic_path_labels))
        lookup[kc_id] = {
            "kc_id": kc_id,
            "knowledge_unit_id": _as_text(row.get("knowledge_unit_id") or row.get("node_id") or kc_id),
            "knowledge_unit_type": "kc",
            "node_id": _as_text(row.get("node_id") or kc_id),
            "node_type": _as_text(row.get("node_type") or "kc") or "kc",
            "canonical_name": canonical_name,
            "aliases": _aliases_from_registry_row(row, canonical_name),
            "sibling_labels": _as_str_list(row.get("sibling_labels")),
            "topic_path_ids": topic_path_ids,
            "topic_path_labels": topic_path_labels,
            "parent_topic_id": _parent_topic_id(row, topic_path_ids),
            "parent_topic_label": _parent_topic_label(topic_path_labels),
        }
    return lookup


def _selected_kc_context_rows(
    step5_rows: Sequence[Mapping[str, Any]],
    *,
    exact_kc_ids: Optional[Sequence[str]],
    limit_kcs: Optional[int],
    kc_context_lookup: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    selected = select_source_rows(step5_rows, exact_kc_ids=exact_kc_ids, limit_kcs=limit_kcs)
    output: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for _, step5_row in selected:
        kc_id = _as_text(step5_row.get("kc_id"))
        if not kc_id or kc_id in seen:
            continue
        seen.add(kc_id)
        context_row = dict(kc_context_lookup.get(kc_id) or {})
        canonical_name = _as_text(context_row.get("canonical_name") or step5_row.get("canonical_name"))
        topic_path_labels = _as_str_list(context_row.get("topic_path_labels"))
        topic_path_ids = _as_str_list(context_row.get("topic_path_ids"))
        if not topic_path_labels:
            topic_path_labels = _topic_path_labels(step5_row, canonical_name)
        if not topic_path_ids and topic_path_labels:
            topic_path_ids = _topic_path_ids(step5_row, len(topic_path_labels))
        output.append(
            {
                "kc_id": kc_id,
                "knowledge_unit_id": _as_text(context_row.get("knowledge_unit_id") or step5_row.get("knowledge_unit_id") or step5_row.get("node_id") or kc_id),
                "knowledge_unit_type": _as_text(context_row.get("knowledge_unit_type") or step5_row.get("knowledge_unit_type") or step5_row.get("node_type") or "kc") or "kc",
                "node_id": _as_text(context_row.get("node_id") or step5_row.get("node_id") or kc_id),
                "node_type": _as_text(context_row.get("node_type") or step5_row.get("node_type") or "kc") or "kc",
                "canonical_name": canonical_name,
                "aliases": _merge_aliases(context_row.get("aliases"), step5_row.get("aliases"), canonical_name=canonical_name),
                "sibling_labels": _merge_aliases(context_row.get("sibling_labels"), step5_row.get("sibling_labels")),
                "topic_path_ids": topic_path_ids,
                "topic_path_labels": topic_path_labels,
                "parent_topic_id": _as_text(context_row.get("parent_topic_id") or _parent_topic_id(step5_row, topic_path_ids)),
                "parent_topic_label": _as_text(
                    context_row.get("parent_topic_label") or _parent_topic_label(topic_path_labels)
                ),
            }
        )
    return output



def _load_profile_guidance_from_spec(
    *,
    profile_jsonl_spec: Optional[str],
    manifest_spec: Optional[InputSpec],
    repo_root: Path,
    allow_reference_artifact_inputs: bool,
    exact_kc_ids: Optional[Sequence[str]],
) -> Tuple[Dict[str, Step5xProfileGuidance], str]:
    if not profile_jsonl_spec:
        return {}, ""

    spec = resolve_related_input_spec(profile_jsonl_spec, repo_root=repo_root, base_spec=manifest_spec)
    ensure_reference_allowed(spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
    if not input_spec_exists(spec):
        raise FileNotFoundError(f"Step 5p profile JSONL not found: {spec.display()}")

    allowed = {str(x) for x in exact_kc_ids or []} if exact_kc_ids else None
    lookup: Dict[str, Step5xProfileGuidance] = {}

    for line_no, row in enumerate(read_jsonl_from_spec(spec), start=1):
        guidance = guidance_from_profile(row)
        if allowed is not None and guidance.kc_id not in allowed:
            continue
        if guidance.kc_id in lookup:
            raise ValueError(f"duplicate Step 5p profile row for kc_id={guidance.kc_id} at line {line_no}")
        lookup[guidance.kc_id] = guidance

    return lookup, spec.display()


def _apply_profile_guidance_to_context_rows(
    selected_rows: Sequence[Mapping[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for row in selected_rows:
        copied = dict(row)
        kc_id = _as_text(copied.get("kc_id"))
        guidance = guidance_lookup.get(kc_id)
        if guidance is not None:
            aliases = _merge_aliases(copied.get("aliases"), alias_safe_terms_for_candidate_generation(guidance))
            copied["aliases"] = aliases
            copied["step5p_profile_guidance_summary"] = guidance_summary_for_candidate_row(guidance)
        policy_plan = build_retrieval_policy_plan(copied, guidance)
        copied["step5x_retrieval_policy_plan"] = policy_plan.to_dict()
        copied["query_plan_id"] = policy_plan.query_plan_id
        copied["knowledge_unit_id"] = policy_plan.knowledge_unit_id
        copied["knowledge_unit_type"] = policy_plan.knowledge_unit_type
        policy_alias_atoms = [
            atom for atom in policy_plan.lexical_atoms
            if atom.lower() != _as_text(copied.get("canonical_name")).lower()
        ]
        copied["aliases"] = _merge_aliases(copied.get("aliases"), policy_alias_atoms)
        output.append(copied)
    return output


def _retrieval_policy_controls_by_kc(selected_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for row in selected_rows:
        kc_id = _as_text(row.get("kc_id"))
        policy = row.get("step5x_retrieval_policy_plan")
        if kc_id and isinstance(policy, Mapping):
            out[kc_id] = dict(policy)
    return out


def _profile_guidance_stats(
    *,
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    selected_rows: Sequence[Mapping[str, Any]],
    profile_source_jsonl: str,
) -> Dict[str, Any]:
    selected_ids = [_as_text(row.get("kc_id")) for row in selected_rows if _as_text(row.get("kc_id"))]
    available = [kc_id for kc_id in selected_ids if kc_id in guidance_lookup]
    safe = [kc_id for kc_id in available if guidance_lookup[kc_id].safe_to_use_for_step5x]
    return {
        "enabled": bool(profile_source_jsonl),
        "profile_source_jsonl": profile_source_jsonl,
        "selected_kc_count": len(selected_ids),
        "profile_available_count": len(available),
        "safe_profile_count": len(safe),
        "missing_profile_count": max(0, len(selected_ids) - len(available)),
        "lexical_query_count_by_kc": {kc_id: len(guidance_lookup[kc_id].lexical_queries) for kc_id in available},
        "semantic_query_count_by_kc": {kc_id: len(guidance_lookup[kc_id].semantic_queries) for kc_id in available},
        "profile_only_query_count_by_kc": {kc_id: len(guidance_lookup[kc_id].profile_only_queries) for kc_id in available},
        "negative_constraint_count_by_kc": {kc_id: len(guidance_lookup[kc_id].negative_constraints) for kc_id in available},
        "shape_hint_count_by_kc": {kc_id: len(guidance_lookup[kc_id].evidence_shape_hints) for kc_id in available},
        "retrieval_route_count_by_kc": {kc_id: len(guidance_lookup[kc_id].retrieval_routes) for kc_id in available},
        "active_retrieval_route_count_by_kc": {
            kc_id: sum(1 for route in guidance_lookup[kc_id].retrieval_routes if route.activation == "active")
            for kc_id in available
        },
        "context_only_route_count_by_kc": {
            kc_id: sum(1 for route in guidance_lookup[kc_id].retrieval_routes if route.activation == "context_only" or route.broad_context_only)
            for kc_id in available
        },
        "control_role": "step5x_retrieval_control_metadata_not_evidence",
    }


def _profile_guidance_controls_by_kc(
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    selected_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    selected_ids = [_as_text(row.get("kc_id")) for row in selected_rows if _as_text(row.get("kc_id"))]
    return {
        kc_id: guidance_to_candidate_bank_controls(guidance_lookup[kc_id])
        for kc_id in selected_ids
        if kc_id in guidance_lookup
    }


def _annotate_candidate_rows_with_profile_guidance(
    rows: List[Dict[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
) -> None:
    for row in rows:
        kc_id = _as_text(row.get("kc_id"))
        guidance = guidance_lookup.get(kc_id)
        if guidance is None:
            continue
        row["step5p_profile_guidance"] = guidance_summary_for_candidate_row(guidance)
        controls = guidance_to_candidate_bank_controls(guidance)
        row["step5p_role_target_guidance"] = {
            "knowledge_unit_id": controls.get("knowledge_unit_id") or kc_id,
            "knowledge_unit_type": controls.get("knowledge_unit_type") or "kc",
            "role_targets": controls.get("role_targets") or [],
            "branch_policy": controls.get("branch_policy") or {},
            "coverage_goals": controls.get("coverage_goals") or {},
            "source_section_targets": controls.get("source_section_targets") or [],
            "unconfirmed_probe_terms": controls.get("unconfirmed_probe_terms") or [],
            "rescue_hints": controls.get("rescue_hints") or [],
            "control_role": "step5p_role_target_retrieval_control_metadata_not_evidence",
        }
        route_eval = _evaluate_profile_routes_for_sentence(guidance, row)
        row["step5p_route_evaluation"] = route_eval
        row.setdefault("authority_contract", AUTHORITY_CONTRACT)
        if not _as_text(row.get("query_plan_id")):
            policy_plan = build_retrieval_policy_plan(row, guidance)
            row["step5x_retrieval_policy_plan"] = policy_plan.to_dict()
            row["query_plan_id"] = policy_plan.query_plan_id
            row.setdefault("knowledge_unit_id", policy_plan.knowledge_unit_id)
            row.setdefault("knowledge_unit_type", policy_plan.knowledge_unit_type)

        if route_eval.get("context_only_match_without_positive_route"):
            row["review_only_candidate"] = True
            row["near_miss_reason"] = "context_only_support"
            row["retrieval_failure_signals"] = _dedupe_preserve_order([
                *_as_str_list(row.get("retrieval_failure_signals")),
                "context_only_support",
            ])
            support_profile = dict(row.get("support_profile") or {}) if isinstance(row.get("support_profile"), Mapping) else {}
            support_profile["generic_context_only"] = True
            support_profile["profile_context_only_route_match"] = True
            support_profile["profile_route_control_role"] = "step5p_retrieval_control_metadata_not_evidence"
            support_profile["review_only_candidate"] = True
            support_profile["near_miss_reason"] = "context_only_support"
            row["support_profile"] = support_profile

            alignment = dict(row.get("alignment_breakdown") or {}) if isinstance(row.get("alignment_breakdown"), Mapping) else {}
            alignment["profile_context_only_route_match"] = True
            alignment["profile_positive_route_match_count"] = int(route_eval.get("positive_route_match_count") or 0)
            alignment["profile_context_only_route_match_count"] = int(route_eval.get("context_only_route_match_count") or 0)
            row["alignment_breakdown"] = alignment

        provenance = dict(row.get("provenance") or {}) if isinstance(row.get("provenance"), Mapping) else {}
        provenance["step5p_profile_guidance_used"] = True
        provenance["step5p_profile_guidance_role"] = "retrieval_control_metadata_not_evidence"
        provenance["step5p_route_evaluation_used"] = bool(route_eval.get("matched_route_count"))
        row["provenance"] = provenance


def _annotate_candidate_rows_with_retrieval_policy(
    rows: List[Dict[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
) -> None:
    for row in rows:
        kc_id = _as_text(row.get("kc_id"))
        guidance = guidance_lookup.get(kc_id)
        existing = row.get("step5x_retrieval_policy_plan")
        if isinstance(existing, Mapping) and _as_text(existing.get("query_plan_id")):
            policy = dict(existing)
        else:
            plan = build_retrieval_policy_plan(row, guidance)
            policy = plan.to_dict()
            row["step5x_retrieval_policy_plan"] = policy
        row["query_plan_id"] = _as_text(row.get("query_plan_id") or policy.get("query_plan_id"))
        row["knowledge_unit_id"] = _as_text(row.get("knowledge_unit_id") or policy.get("knowledge_unit_id") or kc_id)
        row["knowledge_unit_type"] = _as_text(row.get("knowledge_unit_type") or policy.get("knowledge_unit_type") or "kc")
        row["authority_contract"] = _as_text(row.get("authority_contract") or AUTHORITY_CONTRACT)
        row["retrieval_intent"] = _as_text(row.get("retrieval_intent") or row.get("candidate_origin") or "label_normalized_surface")
        row["candidate_origin"] = _as_text(row.get("candidate_origin") or row.get("retrieval_intent"))
        row["target_surface_origin"] = _as_text(row.get("target_surface_origin") or row.get("surface_match_type"))
        row["target_binding_basis"] = _as_text(row.get("target_binding_basis") or row.get("hierarchy_match_type") or row.get("surface_match_type"))
        row["evidence_shape_match"] = _as_text(row.get("evidence_shape_match") or "context")
        row["anchor_scope"] = _as_text(row.get("anchor_scope") or "same_sentence")
        row["window_build_mode"] = _as_text(row.get("window_build_mode") or "source_sentence")
        row["review_only_candidate"] = bool(row.get("review_only_candidate", False))
        row["retrieval_failure_signals"] = _as_str_list(row.get("retrieval_failure_signals"))

def _resolve_sentence_corpus_input(
    *,
    manifest_spec: Optional[InputSpec],
    manifest_obj: Mapping[str, Any],
    repo_root: Path,
    allow_reference_artifact_inputs: bool,
) -> Tuple[Optional[InputSpec], str, str]:
    if manifest_spec is None:
        return None, "", "step5_3_manifest_missing"
    upstream = dict(manifest_obj.get("upstream") or {})
    raw_sentence = _as_text(upstream.get("step4_5_sentence_corpus_jsonl") or upstream.get("sentence_corpus_jsonl"))
    if raw_sentence:
        sentence_spec = resolve_related_input_spec(raw_sentence, repo_root=repo_root, base_spec=manifest_spec)
        ensure_reference_allowed(sentence_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
        return sentence_spec, sentence_spec.display(), "step5_3_upstream_sentence_corpus_jsonl"
    raw_step4_5_manifest = _as_text(upstream.get("step4_5_active_set_target"))
    if raw_step4_5_manifest:
        step4_5_spec = resolve_related_input_spec(raw_step4_5_manifest, repo_root=repo_root, base_spec=manifest_spec)
        ensure_reference_allowed(step4_5_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
        step4_5_obj = read_json_from_spec(step4_5_spec)
        artifacts = dict(step4_5_obj.get("artifacts") or {})
        raw_sentence = _as_text(artifacts.get("sentence_corpus_jsonl") or step4_5_obj.get("sentence_corpus_path"))
        if raw_sentence:
            sentence_spec = resolve_related_input_spec(raw_sentence, repo_root=repo_root, base_spec=step4_5_spec)
            ensure_reference_allowed(sentence_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
            return sentence_spec, step4_5_spec.display(), "step4_5_set_manifest"
    return None, "", "sentence_corpus_missing"


def _candidate_bank_row_from_fallback_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    source_manifest: str,
) -> Dict[str, Any]:
    text = _as_text(payload.get("text"))
    source_block_text = _as_text(payload.get("source_block_text"))
    raw_text_hash = _as_text(payload.get("raw_text_hash")) or _raw_text_hash(text)
    doc_id = _as_text(payload.get("doc_id"))
    block_id = _as_text(payload.get("block_id"))
    sentence_id = _as_text(payload.get("sentence_id"))
    patch_id = _as_text(payload.get("patch_id"))
    page_index = _as_int(payload.get("page_index"))
    source_row_index = _as_int(payload.get("source_row_index")) or 0
    source_evidence_index = _as_int(payload.get("source_evidence_index")) or 0
    row = {
        "candidate_id": build_candidate_id(
            kc_id=_as_text(payload.get("kc_id")),
            source_surface=SOURCE_SURFACE_FALLBACK,
            source_manifest=source_manifest,
            source_row_index=source_row_index,
            source_evidence_index=source_evidence_index,
            doc_id=doc_id,
            block_id=block_id,
            sentence_id=sentence_id,
            patch_id=patch_id,
            page_index=page_index,
            raw_text_hash=raw_text_hash,
        ),
        "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
        "run_id": run_id,
        "source_surface": SOURCE_SURFACE_FALLBACK,
        "source_manifest": source_manifest,
        "source_row_index": int(source_row_index),
        "source_evidence_index": int(source_evidence_index),
        "kc_id": _as_text(payload.get("kc_id")),
        "canonical_name": _as_text(payload.get("canonical_name")),
        "aliases": _as_str_list(payload.get("aliases")),
        "topic_path_ids": _as_str_list(payload.get("topic_path_ids")),
        "topic_path_labels": _as_str_list(payload.get("topic_path_labels")),
        "parent_topic_id": _as_text(payload.get("parent_topic_id")),
        "parent_topic_label": _as_text(payload.get("parent_topic_label")),
        "knowledge_unit_id": _as_text(payload.get("knowledge_unit_id") or payload.get("kc_id")),
        "knowledge_unit_type": _as_text(payload.get("knowledge_unit_type") or "kc"),
        "step5x_retrieval_policy_plan": strip_forbidden_seed_fields(payload.get("step5x_retrieval_policy_plan") or {})
        if isinstance(payload.get("step5x_retrieval_policy_plan"), Mapping)
        else {},
        "query_plan_id": _as_text(payload.get("query_plan_id")),
        "retrieval_intent": _as_text(payload.get("retrieval_intent")),
        "candidate_origin": _as_text(payload.get("candidate_origin") or payload.get("retrieval_intent")),
        "target_surface_origin": _as_text(payload.get("target_surface_origin")),
        "target_binding_basis": _as_text(payload.get("target_binding_basis")),
        "evidence_shape_match": _as_text(payload.get("evidence_shape_match")),
        "anchor_scope": _as_text(payload.get("anchor_scope")),
        "window_build_mode": _as_text(payload.get("window_build_mode")),
        "review_only_candidate": bool(payload.get("review_only_candidate", False)),
        "near_miss_reason": _as_text(payload.get("near_miss_reason")),
        "retrieval_failure_signals": _as_str_list(payload.get("retrieval_failure_signals")),
        "authority_contract": _as_text(payload.get("authority_contract") or AUTHORITY_CONTRACT),
        "source_kc_id": _as_text(payload.get("source_kc_id") or payload.get("kc_id")),
        "source_canonical_name": _as_text(payload.get("source_canonical_name") or payload.get("canonical_name")),
        "granularity": _as_text(payload.get("granularity")) or "sentence",
        "text": text,
        "source_block_text": source_block_text,
        "context_text": _as_text(payload.get("context_text")),
        "doc_id": doc_id,
        "page_index": page_index,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "sent_idx": _as_int(payload.get("sent_idx")),
        "patch_id": patch_id,
        "patch_heading": _as_text(payload.get("patch_heading")),
        "reveal_group_id": _as_text(payload.get("reveal_group_id")),
        "layer": _as_text(payload.get("layer")),
        "bbox": list(payload.get("bbox") or []) if isinstance(payload.get("bbox"), list) else [],
        "char_start": _as_int(payload.get("char_start")),
        "char_end": _as_int(payload.get("char_end")),
        "retrieval_scores": strip_forbidden_seed_fields(payload.get("retrieval_scores") or {})
        if isinstance(payload.get("retrieval_scores"), Mapping)
        else {},
        "alignment_score": payload.get("alignment_score"),
        "alignment_breakdown": strip_forbidden_seed_fields(payload.get("alignment_breakdown") or {})
        if isinstance(payload.get("alignment_breakdown"), Mapping)
        else {},
        "support_profile": strip_forbidden_seed_fields(payload.get("support_profile") or {})
        if isinstance(payload.get("support_profile"), Mapping)
        else {},
        "structural_flags": strip_forbidden_seed_fields(payload.get("structural_flags") or {})
        if isinstance(payload.get("structural_flags"), Mapping)
        else {},
        "raw_text_hash": raw_text_hash,
        "provenance": strip_forbidden_seed_fields(payload.get("provenance") or {})
        if isinstance(payload.get("provenance"), Mapping)
        else {},
        "candidate_source": _as_text(payload.get("candidate_source") or SOURCE_SURFACE_FALLBACK),
        "fallback_tier": _as_text(payload.get("fallback_tier")),
        "fallback_reason": _as_text(payload.get("fallback_reason")),
        "fallback_score": payload.get("fallback_score"),
        "fallback_score_reasons": _as_str_list(payload.get("fallback_score_reasons")),
        "matched_surface_terms": _as_str_list(payload.get("matched_surface_terms")),
        "matched_target_tokens": _as_str_list(payload.get("matched_target_tokens")),
        "surface_match_type": _as_text(payload.get("surface_match_type")),
        "hierarchy_match_type": _as_text(payload.get("hierarchy_match_type")),
        "hierarchy_compatibility_signal": _as_text(payload.get("hierarchy_compatibility_signal")),
        "target_branch_tokens": _as_str_list(payload.get("target_branch_tokens")),
        "source_heading_text": _as_text(payload.get("source_heading_text")),
        "fallback_caution_reason": _as_text(payload.get("fallback_caution_reason")),
    }
    provenance = dict(row["provenance"]) if isinstance(row.get("provenance"), Mapping) else {}
    provenance.setdefault("candidate_source", SOURCE_SURFACE_FALLBACK)
    provenance.setdefault("source_manifest", source_manifest)
    provenance.setdefault("source_jsonl", source_manifest)
    provenance["candidate_bank_source_surface"] = SOURCE_SURFACE_FALLBACK
    row["provenance"] = provenance
    return row


def load_registry_rows_if_available(
    spec: Optional[InputSpec],
    *,
    allow_seed_bearing_input_for_diagnostic: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if spec is None or not input_spec_exists(spec):
        return [], {"total": 0, "by_key": {}}
    rows = read_jsonl_from_spec(spec) if spec.is_archive_member else read_jsonl(spec.file_path)  # type: ignore[arg-type]
    detection = _enforce_seed_bearing_input_policy(
        rows,
        input_label=f"Registry input {spec.display()}",
        allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
    )
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        sanitized = strip_forbidden_seed_fields(dict(row))
        if isinstance(sanitized, dict):
            cleaned.append(sanitized)
    return cleaned, detection


def _registry_kc_rows(registry_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for row in registry_rows:
        sanitized = strip_forbidden_seed_fields(dict(row))
        if not isinstance(sanitized, dict):
            continue
        if not _as_text(sanitized.get("kc_id")):
            continue
        cleaned.append(sanitized)
    return cleaned


def _count_seed_fields_in_rows(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(count_forbidden_seed_fields(row) for row in rows)


def _load_clean_slate_kc_context_rows(
    *,
    registry_spec: InputSpec,
    repo_root: Path,
    allow_reference_artifact_inputs: bool,
    allow_seed_bearing_input_for_diagnostic: bool,
    exact_kc_ids: Optional[Sequence[str]],
    limit_kcs: Optional[int],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], str, Dict[str, Any]]:
    ensure_reference_allowed(registry_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
    if not input_spec_exists(registry_spec):
        raise FileNotFoundError(f"Seedless registry JSONL not found: {registry_spec.display()}")

    raw_registry_rows = read_jsonl_from_spec(registry_spec)
    seed_detection = _enforce_seed_bearing_input_policy(
        raw_registry_rows,
        input_label=f"Registry input {registry_spec.display()}",
        allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
    )
    registry_rows = _registry_kc_rows(raw_registry_rows)
    if not registry_rows:
        raise RuntimeError(f"Seedless registry JSONL contains no KC rows: {registry_spec.display()}")

    kc_context_lookup = build_kc_context_lookup(registry_rows)
    selected = select_source_rows(
        registry_rows,
        exact_kc_ids=[str(kc_id) for kc_id in exact_kc_ids or []] or None,
        limit_kcs=limit_kcs,
    )

    output: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for _, registry_row in selected:
        kc_id = _as_text(registry_row.get("kc_id"))
        if not kc_id or kc_id in seen:
            continue
        seen.add(kc_id)
        context_row = dict(kc_context_lookup.get(kc_id) or {})
        if not context_row:
            continue
        context_row["aliases"] = _merge_aliases(context_row.get("aliases"), registry_row.get("aliases"))
        context_row["sibling_labels"] = _as_str_list(registry_row.get("sibling_labels"))
        context_row["source"] = SOURCE_REGISTRY_CLEAN_SLATE
        output.append(context_row)

    if not output:
        raise RuntimeError(f"No selected KC rows could be built from registry JSONL: {registry_spec.display()}")

    return output, kc_context_lookup, registry_spec.display(), seed_detection


def _resolve_clean_slate_sentence_corpus(
    *,
    source_overlay_spec: InputSpec,
    allow_reference_artifact_inputs: bool,
) -> Tuple[List[Dict[str, Any]], str]:
    ensure_reference_allowed(source_overlay_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
    if not input_spec_exists(source_overlay_spec):
        raise FileNotFoundError(f"Sentence overlay JSONL not found: {source_overlay_spec.display()}")
    return read_jsonl_from_spec(source_overlay_spec), source_overlay_spec.display()


def _load_direct_overlay_supplement_rows(
    *,
    cfg: Mapping[str, Any] | None,
    repo_root: Path,
    allow_reference_artifact_inputs: bool,
    allow_seed_bearing_input_for_diagnostic: bool,
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any], Dict[str, Any]]:
    config = _direct_overlay_config_from_mapping(cfg)
    if not bool(config.get("enabled")):
        return [], "", {"total": 0, "by_key": {}}, config

    supplement_jsonl = _as_text(config.get("supplement_jsonl"))
    if not supplement_jsonl:
        if bool(config.get("generate_from_source_overlay")):
            return [], "", {"total": 0, "by_key": {}}, config
        raise RuntimeError(
            "Direct overlay supplement is enabled but no supplement_jsonl was provided."
        )

    supplement_spec = parse_input_spec(supplement_jsonl, repo_root=repo_root)
    ensure_reference_allowed(
        supplement_spec,
        allow_reference_artifact_inputs=allow_reference_artifact_inputs,
    )
    if not input_spec_exists(supplement_spec):
        raise FileNotFoundError(
            f"Direct overlay supplement JSONL not found: {supplement_spec.display()}"
        )

    raw_rows = read_jsonl_from_spec(supplement_spec)
    seed_detection = _enforce_seed_bearing_input_policy(
        raw_rows,
        input_label=f"Direct overlay supplement input {supplement_spec.display()}",
        allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
    )

    cleaned_rows: List[Dict[str, Any]] = []
    for row in raw_rows:
        sanitized = strip_forbidden_seed_fields(dict(row))
        if isinstance(sanitized, dict):
            cleaned_rows.append(sanitized)

    return cleaned_rows, supplement_spec.display(), seed_detection, config


def _apply_clean_slate_provenance(
    rows: Sequence[Dict[str, Any]],
    *,
    registry_jsonl: str,
    source_overlay_jsonl: str,
) -> None:
    for row in rows:
        provenance = dict(row.get("provenance") or {}) if isinstance(row.get("provenance"), Mapping) else {}
        provenance["input_mode"] = INPUT_MODE_CLEAN_SLATE
        provenance["registry_source"] = REGISTRY_SOURCE_SEEDLESS
        provenance["registry_jsonl"] = registry_jsonl
        provenance["source_overlay_jsonl"] = source_overlay_jsonl
        provenance.setdefault("step5p_profile_guidance_used", False)
        row["provenance"] = provenance


def _direct_overlay_config_from_mapping(raw: Mapping[str, Any] | None) -> Dict[str, Any]:
    cfg = dict(raw or {})
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "supplement_jsonl": _as_text(cfg.get("supplement_jsonl")),
        "max_candidates_per_kc": max(0, int(cfg.get("max_candidates_per_kc", 8) or 0)),
        "min_score": float(cfg.get("min_score", 4.8) or 0.0),
        "reject_prompt_like": bool(cfg.get("reject_prompt_like", True)),
        "reject_fragmentary": bool(cfg.get("reject_fragmentary", True)),
        "reject_reference_like": bool(cfg.get("reject_reference_like", True)),
        "reject_formula_only_without_target_signal": bool(
            cfg.get("reject_formula_only_without_target_signal", True)
        ),
        # Optional generic supplement generator. This keeps the existing
        # external-supplement path intact, but can build supplement rows from
        # a Step 4.5 sentence overlay using only registry/profile-derived
        # target phrases. It must never contain course-specific labels or
        # model-specific behavior.
        "generate_from_source_overlay": bool(cfg.get("generate_from_source_overlay", False)),
        "source_overlay_jsonl": _as_text(cfg.get("source_overlay_jsonl")),
        "source_overlay_max_scan_rows": max(0, int(cfg.get("source_overlay_max_scan_rows", 0) or 0)),
        "source_overlay_max_hits_per_kc": max(0, int(cfg.get("source_overlay_max_hits_per_kc", 120) or 0)),
        "source_overlay_min_scan_score": float(cfg.get("source_overlay_min_scan_score", 5.8) or 0.0),
        "source_overlay_dynamic_broad_phrase_kc_fraction": float(
            cfg.get("source_overlay_dynamic_broad_phrase_kc_fraction", 0.25) or 0.0
        ),
        "source_overlay_min_single_token_len": max(1, int(cfg.get("source_overlay_min_single_token_len", 5) or 1)),
        "source_overlay_allow_uppercase_acronym": bool(cfg.get("source_overlay_allow_uppercase_acronym", True)),
    }


def _direct_overlay_text(raw_row: Mapping[str, Any]) -> str:
    for key in ("candidate_text", "sentence_text", "text", "snippet", "quote", "evidence_text", "window_text"):
        text = _as_text(raw_row.get(key))
        if text:
            return text
    return ""


def _direct_overlay_sentence_row(raw_row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _direct_overlay_text(raw_row)
    source_block_text = _as_text(raw_row.get("source_block_text") or raw_row.get("window_text") or text)
    page_index = _as_int(raw_row.get("page_index"))
    layer = _as_text(raw_row.get("layer") or raw_row.get("extractor"))
    sentence_row = {
        "sentence_text": text,
        "source_block_text": source_block_text,
        "doc_id": _as_text(raw_row.get("doc_id")),
        "page_index": page_index,
        "block_id": _as_text(raw_row.get("block_id")),
        "sentence_id": _as_text(raw_row.get("sentence_id")),
        "sent_idx": _as_int(raw_row.get("sent_idx")),
        "patch_id": _as_text(raw_row.get("patch_id")),
        "patch_heading": _as_text(raw_row.get("patch_heading") or raw_row.get("heading")),
        "reveal_group_id": _as_text(raw_row.get("reveal_group_id")),
        "layer": layer,
        "bbox": list(raw_row.get("bbox") or []) if isinstance(raw_row.get("bbox"), list) else [],
        "char_start": _as_int(raw_row.get("char_start")),
        "char_end": _as_int(raw_row.get("char_end")) if _as_int(raw_row.get("char_end")) is not None else len(text),
        "is_meta": bool(raw_row.get("is_meta")),
        "is_nav_boilerplate": bool(raw_row.get("is_nav_boilerplate")),
        "is_author_affiliation": bool(raw_row.get("is_author_affiliation")),
        "is_transition_text": bool(raw_row.get("is_transition_text")),
        "is_heading_like": bool(raw_row.get("is_heading_like")),
        "is_formula_like": bool(raw_row.get("is_formula_like")),
        "is_definition_like": bool(raw_row.get("is_definition_like")),
        "is_procedure_like": bool(raw_row.get("is_procedure_like")),
        "is_example_like": bool(raw_row.get("is_example_like")),
    }
    if not sentence_row["is_formula_like"] and FORMULA_RE.search(text):
        sentence_row["is_formula_like"] = True
    return sentence_row


def _direct_overlay_collect_reasonish_strings(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        text = _as_text(value)
        if text:
            out.append(text)
        return out
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = _as_text(key).lower()
            if key_text in {"reasons", "blockers", "status", "decision", "reason_codes"}:
                out.extend(_direct_overlay_collect_reasonish_strings(item))
        return out
    if isinstance(value, list):
        for item in value:
            out.extend(_direct_overlay_collect_reasonish_strings(item))
    return out


def _direct_overlay_target_signals(raw_row: Mapping[str, Any]) -> List[str]:
    signals: List[str] = []
    for key in ("target_signals", "matched_surface_terms", "matched_target_terms", "signal_terms"):
        signals.extend(_as_str_list(raw_row.get(key)))
    support_profile = raw_row.get("support_profile") if isinstance(raw_row.get("support_profile"), Mapping) else {}
    signals.extend(_as_str_list(support_profile.get("target_signals")))
    for reason_text in _direct_overlay_collect_reasonish_strings(raw_row):
        lowered = reason_text.lower()
        for prefix in DIRECT_OVERLAY_SIGNAL_PREFIXES:
            if not lowered.startswith(prefix):
                continue
            for part in reason_text[len(prefix):].split(","):
                cleaned = normalize_ws(part.replace("_", " ").strip(" .:;\"'`"))
                if cleaned:
                    signals.append(cleaned)
    normalized: List[str] = []
    seen: set[str] = set()
    for signal in signals:
        cleaned = normalize_ws(str(signal or "").strip(" .:;\"'`"))
        tokens = _content_tokens(cleaned, min_len=1)
        if not cleaned or not tokens:
            continue
        if len(tokens) == 1 and not _direct_overlay_single_token_signal_allowed(cleaned, tokens):
            continue
        lowered = match_normalize(cleaned)
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(cleaned)
    return normalized



def _direct_overlay_single_token_signal_allowed(signal: str, tokens: Sequence[str]) -> bool:
    """Allow only target-provided uppercase acronym signals as one-token direct-overlay signals.

    This is a generic precision guard. Multi-token direct-overlay signals remain
    handled by the existing path. Lowercase or mixed-case one-token signals are
    too broad to create target binding by themselves and must not survive here.
    """
    if len(tokens) != 1:
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", str(signal or "").strip()))


def _direct_overlay_signal_hits(
    views: Mapping[str, Any],
    target_signals: Sequence[str],
) -> Tuple[List[str], List[str], str]:
    matched_terms: List[str] = []
    matched_tokens: List[str] = []
    best_surface = ""
    best_priority = -1
    for signal in target_signals:
        normalized = match_normalize(signal)
        tokens = _content_tokens(signal, min_len=1)
        if not normalized or not tokens:
            continue
        for surface_name, norm_key, priority in (
            ("text", "text_norm", 3),
            ("source_block", "source_block_norm", 2),
            ("heading", "heading_norm", 1),
        ):
            if not _boundary_phrase_hit(str(views.get(norm_key) or ""), normalized):
                continue
            if (len(tokens) >= 2 or _direct_overlay_single_token_signal_allowed(signal, tokens)) and signal not in matched_terms:
                matched_terms.append(signal)
            for token in tokens:
                if token not in matched_tokens:
                    matched_tokens.append(token)
            if priority > best_priority:
                best_priority = priority
                best_surface = surface_name
            break
    return matched_terms, matched_tokens, best_surface


def _direct_overlay_branch_hits(
    kc_context: Mapping[str, Any],
    views: Mapping[str, Any],
) -> Tuple[List[str], List[str]]:
    branch_tokens: List[str] = []
    for label in [*_as_str_list(kc_context.get("topic_path_labels")), _as_text(kc_context.get("parent_topic_label"))]:
        for token in _content_tokens(label, min_len=2):
            if token not in branch_tokens:
                branch_tokens.append(token)
    heading_tokens = set(_content_tokens(str(views.get("heading_text") or ""), min_len=2))
    local_tokens = set(
        _content_tokens(str(views.get("text") or ""), min_len=2)
        + _content_tokens(str(views.get("source_block_text") or ""), min_len=2)
        + _content_tokens(str(views.get("context_text") or ""), min_len=2)
    )
    heading_hits = [token for token in branch_tokens if token in heading_tokens]
    local_hits = [token for token in branch_tokens if token in local_tokens and token not in heading_hits]
    return heading_hits, local_hits


def _direct_overlay_relation_like(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> bool:
    lowered = normalize_ws(
        f"{_as_text(views.get('text'))} {_as_text(views.get('source_block_text'))}"
    ).lower()
    if bool(sentence_row.get("is_definition_like")) or bool(sentence_row.get("is_procedure_like")):
        return True
    return bool(
        re.search(
            r"\b(?:is|are|was|were|refers to|defined as|known as|called|means|denotes|describes|"
            r"occurs when|results in|leads to|used for|used to|partitions?|splits?|"
            r"minimizes?|maximizes?|evaluates?|measures?)\b",
            lowered,
        )
    )


def _direct_overlay_reference_like(sentence_row: Mapping[str, Any], views: Mapping[str, Any]) -> bool:
    text = f"{_as_text(views.get('text'))} {_as_text(views.get('heading_text'))}".lower()
    return bool(REFERENCE_LIKE_RE.search(text))


def _direct_overlay_rehydration_needed(
    sentence_row: Mapping[str, Any],
    views: Mapping[str, Any],
    *,
    matched_surface_terms: Sequence[str],
    matched_signal_terms: Sequence[str],
    reason_codes: Sequence[str],
    reject_formula_only_without_target_signal: bool,
) -> bool:
    text = _as_text(views.get("text"))
    structural_flags = build_structural_flags(text, _as_text(views.get("source_block_text")), sentence_row)
    reason_text = " ".join(reason_codes).lower()
    if bool(structural_flags.get("looks_fragmentary")):
        return True
    if DIRECT_OVERLAY_OPEN_ENDED_RE.search(text.lower()):
        return True
    if any(token in reason_text for token in ("rehydration", "short surface", "short_surface", "fragment", "truncated")):
        return True
    if reject_formula_only_without_target_signal and bool(structural_flags.get("looks_formula_like")):
        if not matched_surface_terms and not matched_signal_terms:
            return True
    return False


def _direct_overlay_soft_overlap(text_a: str, text_b: str) -> float:
    norm_a = match_normalize(text_a)
    norm_b = match_normalize(text_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a in norm_b or norm_b in norm_a:
        return 1.0
    tokens_a = set(_content_tokens(text_a, min_len=2))
    tokens_b = set(_content_tokens(text_b, min_len=2))
    if not tokens_a or not tokens_b:
        return 0.0
    return float(len(tokens_a & tokens_b)) / float(min(len(tokens_a), len(tokens_b)))


def _direct_overlay_quality_tuple(info: Mapping[str, Any]) -> Tuple[float, int, int, int, int]:
    text = _as_text(info.get("text"))
    return (
        float(info.get("score") or 0.0),
        1 if text.endswith((".", "!", "?", ")")) else 0,
        len(_as_str_list(info.get("matched_signal_terms"))),
        len(_as_str_list(info.get("matched_target_tokens"))),
        len(text),
    )


def _direct_overlay_identity_key(
    *,
    kc_id: str,
    doc_id: str,
    sentence_id: str,
    block_id: str,
    raw_text_hash: str,
) -> Tuple[str, str, str, str, str]:
    return (kc_id, doc_id, sentence_id, block_id, raw_text_hash)



SOURCE_OVERLAY_GENERIC_STOP_TERMS = {
    "the", "and", "or", "for", "with", "from", "into", "onto", "that", "this", "these", "those",
    "source", "sources", "chapter", "section", "page", "pages", "table", "figure", "example",
    "method", "methods", "model", "models", "approach", "approaches", "phase", "process",
    "definition", "concept", "topic", "basic", "general", "target", "targets", "value", "values",
}


def _source_overlay_phrase_parts(phrase: str) -> List[str]:
    normalized = match_normalize(phrase)
    return [part for part in re.split(r"[-\s]+", normalized) if part]


def _source_overlay_boundary_phrase_hit(surface_norm: str, phrase: str) -> bool:
    parts = _source_overlay_phrase_parts(phrase)
    if not surface_norm or not parts:
        return False
    pattern = r"(?<![a-z0-9])" + r"[-\s]+".join(re.escape(part) for part in parts) + r"(?![a-z0-9])"
    return bool(re.search(pattern, surface_norm, flags=re.I))


def _source_overlay_raw_target_phrases(
    kc_context: Mapping[str, Any],
    guidance: Step5xProfileGuidance | None,
) -> List[str]:
    raw: List[str] = []
    canonical_name = _as_text(kc_context.get("canonical_name"))
    aliases = _as_str_list(kc_context.get("aliases"))
    raw.extend([canonical_name, *aliases])

    policy = kc_context.get("step5x_retrieval_policy_plan")
    if isinstance(policy, Mapping):
        for key in ("lexical_atoms", "concept_head_terms", "label_descriptor_terms"):
            raw.extend(_as_str_list(policy.get(key)))

    if guidance is not None:
        raw.extend(alias_safe_terms_for_candidate_generation(guidance))
        for query in [*guidance.lexical_queries, *guidance.semantic_queries]:
            raw.append(_as_text(query))

    expanded: List[str] = []
    for phrase in raw:
        cleaned = normalize_ws(str(phrase or "").strip(" .:;\"'`"))
        if not cleaned:
            continue
        expanded.append(cleaned)
        expanded.append(cleaned.replace("-", " "))
        no_paren = normalize_ws(re.sub(r"\([^)]*\)", "", cleaned))
        if no_paren:
            expanded.append(no_paren)
        for parenthetical in re.findall(r"\(([^)]+)\)", cleaned):
            inner = normalize_ws(parenthetical)
            if inner.isupper() and len(inner) >= 3:
                expanded.append(inner)
        if ":" in cleaned:
            suffix = normalize_ws(cleaned.split(":", 1)[1])
            if suffix:
                expanded.append(suffix)

    out: List[str] = []
    seen: set[str] = set()
    for phrase in expanded:
        key = match_normalize(phrase)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(phrase)
    return out


def _source_overlay_target_phrase_index_unfiltered(
    selected_kc_context_rows: Sequence[Mapping[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    cfg: Mapping[str, Any],
) -> Dict[str, List[str]]:
    raw_by_kc: Dict[str, List[str]] = {}
    phrase_kc_counts: Counter[str] = Counter()
    for row in selected_kc_context_rows:
        kc_id = _as_text(row.get("kc_id"))
        if not kc_id:
            continue
        raw_phrases = _source_overlay_raw_target_phrases(row, guidance_lookup.get(kc_id))
        normalized_for_kc: set[str] = set()
        for phrase in raw_phrases:
            key = match_normalize(phrase)
            if key:
                normalized_for_kc.add(key)
        for key in normalized_for_kc:
            phrase_kc_counts[key] += 1
        raw_by_kc[kc_id] = raw_phrases

    selected_count = max(1, len(raw_by_kc))
    broad_fraction = float(cfg.get("source_overlay_dynamic_broad_phrase_kc_fraction") or 0.0)
    broad_cutoff = max(2, int(selected_count * broad_fraction)) if broad_fraction > 0 else selected_count + 1
    min_single_len = int(cfg.get("source_overlay_min_single_token_len") or 5)
    allow_acronym = bool(cfg.get("source_overlay_allow_uppercase_acronym", True))

    filtered: Dict[str, List[str]] = {}
    for kc_id, phrases in raw_by_kc.items():
        kept: List[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            key = match_normalize(phrase)
            parts = _source_overlay_phrase_parts(phrase)
            if not key or not parts or key in seen:
                continue
            if phrase_kc_counts.get(key, 0) > broad_cutoff:
                continue
            if len(parts) == 1:
                token = parts[0]
                if token in SOURCE_OVERLAY_GENERIC_STOP_TERMS:
                    continue
                is_acronym = phrase.strip().isupper() and len(token) >= 3
                if not (allow_acronym and is_acronym) and len(token) < min_single_len:
                    continue
            else:
                if all(part in SOURCE_OVERLAY_GENERIC_STOP_TERMS for part in parts):
                    continue
            seen.add(key)
            kept.append(phrase)
        filtered[kc_id] = kept
    return filtered




SOURCE_OVERLAY_GENERIC_VARIANT_EXPANSION_VERSION = "generic_source_variant_boundary_v1f"


def _source_overlay_generic_norm_phrase(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split())


def _source_overlay_generic_phrase_key(value: Any) -> str:
    return _source_overlay_generic_norm_phrase(value).lower()


def _source_overlay_generic_tokens(value: Any) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9]*", str(value or ""))


def _source_overlay_generic_token_count(value: Any) -> int:
    return len(_source_overlay_generic_tokens(value))


def _source_overlay_is_upper_acronym(value: Any) -> bool:
    s = str(value or "").strip()
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", s))


def _source_overlay_add_phrase_variant(
    bucket: list[str],
    seen: set[str],
    phrase: Any,
    *,
    min_single_token_len: int = 5,
    allow_uppercase_acronym: bool = True,
) -> None:
    phrase_s = str(phrase or "").strip()
    if not phrase_s:
        return

    phrase_s = re.sub(r"\s+", " ", phrase_s)
    key = _source_overlay_generic_phrase_key(phrase_s)
    if not key:
        return

    token_count = _source_overlay_generic_token_count(phrase_s)
    if token_count == 1:
        if len(key) < int(min_single_token_len) and not (
            allow_uppercase_acronym and _source_overlay_is_upper_acronym(phrase_s)
        ):
            return

    if key in seen:
        return

    bucket.append(phrase_s)
    seen.add(key)


def _source_overlay_expand_label_phrase_variants(
    phrases: Sequence[Any],
    *,
    min_single_token_len: int = 5,
    allow_uppercase_acronym: bool = True,
    max_phrases: int = 48,
) -> list[str]:
    """Generate generic phrase variants from existing target phrases.

    This is recall expansion only. It does not admit evidence. Variants still
    have to survive source scanning, scoring, and pack gates.
    """
    out: list[str] = []
    seen: set[str] = set()

    for phrase in phrases:
        phrase_s = str(phrase or "").strip()
        if not phrase_s:
            continue

        candidates: list[str] = []
        candidates.append(phrase_s)
        candidates.append(phrase_s.replace("-", " "))
        candidates.append(phrase_s.replace(" ", "-"))

        if ":" in phrase_s:
            tail = phrase_s.split(":", 1)[1].strip()
            if tail:
                candidates.append(tail)
                candidates.append(tail.replace("-", " "))
                candidates.append(tail.replace(" ", "-"))

        for inner in re.findall(r"\(([^)]+)\)", phrase_s):
            inner = inner.strip()
            if inner:
                candidates.append(inner)
                candidates.append(inner.replace("-", " "))
                candidates.append(inner.replace(" ", "-"))
                for part in re.split(r"[,;/]", inner):
                    part = part.strip()
                    if part:
                        candidates.append(part)
                        candidates.append(part.replace("-", " "))
                        candidates.append(part.replace(" ", "-"))

        no_paren = re.sub(r"\([^)]*\)", "", phrase_s).strip()
        if no_paren and no_paren != phrase_s:
            candidates.append(no_paren)
            candidates.append(no_paren.replace("-", " "))
            candidates.append(no_paren.replace(" ", "-"))

        for tok in _source_overlay_generic_tokens(phrase_s):
            if _source_overlay_is_upper_acronym(tok):
                candidates.append(tok)

        toks = _source_overlay_generic_tokens(phrase_s)
        if len(toks) == 2:
            first, second = toks[0], toks[1]
            if re.search(r"(ive|al|ic|ary|ory|ous|ent|ant)$", first.lower()):
                candidates.append(f"{second} is {first}")

        for cand in candidates:
            _source_overlay_add_phrase_variant(
                out,
                seen,
                cand,
                min_single_token_len=min_single_token_len,
                allow_uppercase_acronym=allow_uppercase_acronym,
            )
            if len(out) >= int(max_phrases):
                break

        if len(out) >= int(max_phrases):
            break

    return out


def _source_overlay_expand_phrase_index_generic(
    phrase_index: Any,
    *,
    cfg: Mapping[str, Any],
) -> Any:
    """Expand phrase index using only generic label-surface transforms.

    The output remains a phrase index. It is not evidence and it does not bypass
    source scanning, scoring, lane semantics, or pack admission.
    """
    if not isinstance(phrase_index, Mapping):
        return phrase_index

    if not bool(cfg.get("source_overlay_generic_variant_expansion_enabled", True)):
        return phrase_index

    min_single = int(cfg.get("source_overlay_min_single_token_len") or 5)
    allow_acr = bool(cfg.get("source_overlay_allow_uppercase_acronym", True))
    max_phrases = int(cfg.get("source_overlay_max_generated_phrases_per_kc") or 48)

    expanded: dict[Any, list[str]] = {}

    for unit_id, phrases in phrase_index.items():
        base_phrases = list(phrases or []) if isinstance(phrases, (list, tuple, set)) else []
        expanded[unit_id] = _source_overlay_expand_label_phrase_variants(
            base_phrases,
            min_single_token_len=min_single,
            allow_uppercase_acronym=allow_acr,
            max_phrases=max_phrases,
        )

    return expanded

SOURCE_OVERLAY_TARGET_PHRASE_INDEX_FILTER_VERSION = "wrapper_broad_shared_single_token_v2"


def _source_overlay_phrase_token_count(phrase: Any) -> int:
    """Count simple tokens in a phrase without assuming any course domain."""
    return len([part for part in str(phrase or "").replace("-", " ").split() if part])


def _source_overlay_normalize_phrase_for_sharing(phrase: Any) -> str:
    return " ".join(str(phrase or "").lower().replace("-", " ").split())


def _source_overlay_filter_broad_shared_single_token_phrases(
    phrase_index: Any,
    *,
    max_kc_fraction: float = 0.25,
) -> Any:
    """Remove broad one-token phrases shared across many target units.

    This is a generic precision guard. It contains no course-specific terms,
    KC-specific branches, or model-specific behavior. It only prevents a
    one-token phrase that appears across a broad fraction of targets from being
    treated as target-bound source-overlay evidence.
    """
    if not isinstance(phrase_index, Mapping) or not phrase_index:
        return phrase_index

    kc_count = max(1, len(phrase_index))
    phrase_to_kcs: dict[str, set[str]] = {}
    uppercase_acronym_norms: set[str] = set()

    for kc, phrases in phrase_index.items():
        if not isinstance(phrases, (list, tuple, set)):
            continue

        for phrase in phrases:
            norm = _source_overlay_normalize_phrase_for_sharing(phrase)
            if not norm:
                continue

            phrase_to_kcs.setdefault(norm, set()).add(str(kc))
            if _source_overlay_is_upper_acronym(str(phrase).strip()):
                uppercase_acronym_norms.add(norm)

    remove_norms = {
        norm
        for norm, kcs in phrase_to_kcs.items()
        if _source_overlay_phrase_token_count(norm) == 1
        and norm not in uppercase_acronym_norms
        and (len(kcs) / kc_count) > float(max_kc_fraction)
    }

    if not remove_norms:
        return phrase_index

    filtered: dict[Any, Any] = {}

    for kc, phrases in phrase_index.items():
        if not isinstance(phrases, (list, tuple, set)):
            filtered[kc] = phrases
            continue

        out = []
        seen = set()

        for phrase in phrases:
            norm = _source_overlay_normalize_phrase_for_sharing(phrase)
            if not norm:
                continue
            if norm in remove_norms:
                continue
            if norm in seen:
                continue

            out.append(phrase)
            seen.add(norm)

        filtered[kc] = out

    return filtered


def _source_overlay_target_phrase_index(*args: Any, **kwargs: Any) -> Any:
    """Filtered and generically expanded wrapper around the original phrase-index builder.

    The original function remains unchanged as
    _source_overlay_target_phrase_index_unfiltered. This wrapper performs only
    phrase-index expansion and broad shared one-token filtering. It does not
    change scoring, evidence admission, pack composition, or model behavior.
    """
    phrase_index = _source_overlay_target_phrase_index_unfiltered(*args, **kwargs)

    cfg: Mapping[str, Any] = {}
    if len(args) >= 3 and isinstance(args[2], Mapping):
        cfg = args[2]
    cfg_kw = kwargs.get("cfg")
    if isinstance(cfg_kw, Mapping):
        cfg = cfg_kw

    phrase_index = _source_overlay_expand_phrase_index_generic(
        phrase_index,
        cfg=cfg or {},
    )

    max_fraction = kwargs.get("dynamic_broad_phrase_kc_fraction", None)
    if max_fraction is None:
        max_fraction = kwargs.get("source_overlay_dynamic_broad_phrase_kc_fraction", None)
    if max_fraction is None and isinstance(cfg, Mapping):
        max_fraction = cfg.get("source_overlay_dynamic_broad_phrase_kc_fraction", None)
    if max_fraction is None:
        max_fraction = 0.25

    try:
        max_fraction_f = float(max_fraction)
    except Exception:
        max_fraction_f = 0.25

    return _source_overlay_filter_broad_shared_single_token_phrases(
        phrase_index,
        max_kc_fraction=max_fraction_f,
    )




SOURCE_OVERLAY_SOURCE_WINDOW_REHYDRATION_VERSION = "source_overlay_source_window_rehydration_v1f"


def _source_overlay_source_block_window_allowed_for_supplement_scan(
    *,
    sentence_row: Mapping[str, Any],
    views: Mapping[str, Any],
    matched_terms: Sequence[str],
    max_chars: int,
) -> Tuple[bool, Dict[str, Any]]:
    """Check whether source_block_text may become the source-overlay candidate text.

    This is a generic structural-window handoff. It only fires after the source-overlay
    scan has already matched a target phrase inside source_block_text. It does not
    introduce new target phrases, change scoring thresholds, or bypass pack gates.
    """
    text = _as_text(views.get("text"))
    source_block_text = _as_text(views.get("source_block_text"))
    matched_clean = list(_dedupe_preserve_order([_as_text(term) for term in matched_terms if _as_text(term)]))

    meta: Dict[str, Any] = {
        "version": SOURCE_OVERLAY_SOURCE_WINDOW_REHYDRATION_VERSION,
        "promoted": False,
        "reason": "",
        "original_text_len": len(text),
        "source_block_text_len": len(source_block_text),
        "matched_terms": matched_clean,
        "stage": "source_overlay_supplement_generation",
    }

    if not source_block_text or source_block_text == text:
        meta["reason"] = "missing_or_identical_source_block"
        return False, meta
    if not _looks_fragmentary(text, sentence_row):
        meta["reason"] = "sentence_not_fragmentary"
        return False, meta
    if len(source_block_text) < 35:
        meta["reason"] = "source_block_too_short"
        return False, meta
    if max_chars > 0 and len(source_block_text) > max_chars:
        meta["reason"] = "source_block_too_long"
        return False, meta

    source_block_norm = match_normalize(source_block_text)
    if not matched_clean:
        meta["reason"] = "no_matched_terms"
        return False, meta
    if not any(_source_overlay_boundary_phrase_hit(source_block_norm, term) for term in matched_clean):
        meta["reason"] = "matched_terms_not_in_source_block"
        return False, meta

    candidate_sentence_row = dict(sentence_row)
    candidate_sentence_row["sentence_text"] = source_block_text
    candidate_views = _surface_views(candidate_sentence_row)

    if _direct_overlay_reference_like(candidate_sentence_row, candidate_views):
        meta["reason"] = "source_block_reference_like"
        return False, meta
    if _looks_prompt_like(source_block_text):
        meta["reason"] = "source_block_prompt_like"
        return False, meta
    if CAPTION_RE.search(source_block_text.lower()) or CAPTION_RE.search(_as_text(candidate_views.get("heading_text")).lower()):
        meta["reason"] = "source_block_caption_like"
        return False, meta
    if _looks_fragmentary(source_block_text, candidate_sentence_row):
        meta["reason"] = "source_block_still_fragmentary"
        return False, meta

    meta["promoted"] = True
    meta["reason"] = "fragmentary_sentence_rehydrated_from_target_bound_source_block"
    return True, meta


def _source_overlay_promote_source_block_window_for_supplement_scan(
    *,
    sentence_row: Mapping[str, Any],
    views: Mapping[str, Any],
    matched_terms: Sequence[str],
    matched_surface: str,
    cfg: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Promote source_block_text before source-overlay supplement scoring when safe."""
    meta: Dict[str, Any] = {
        "version": SOURCE_OVERLAY_SOURCE_WINDOW_REHYDRATION_VERSION,
        "promoted": False,
        "reason": "not_applicable",
        "stage": "source_overlay_supplement_generation",
    }

    if not bool(cfg.get("source_overlay_promote_source_block_window", True)):
        meta["reason"] = "disabled_by_config"
        return dict(sentence_row), dict(views), meta, matched_surface

    if matched_surface != "source_block":
        meta["reason"] = "matched_surface_not_source_block"
        return dict(sentence_row), dict(views), meta, matched_surface

    max_chars = int(cfg.get("source_overlay_source_block_window_max_chars") or 900)
    allowed, meta = _source_overlay_source_block_window_allowed_for_supplement_scan(
        sentence_row=sentence_row,
        views=views,
        matched_terms=matched_terms,
        max_chars=max_chars,
    )
    if not allowed:
        return dict(sentence_row), dict(views), meta, matched_surface

    promoted_row = dict(sentence_row)
    promoted_row["source_overlay_original_sentence_text"] = _as_text(views.get("text"))
    promoted_row["source_overlay_window_promoted"] = True
    promoted_row["source_overlay_window_promotion_reason"] = _as_text(meta.get("reason"))
    promoted_row["source_overlay_window_promotion"] = dict(meta)
    promoted_row["sentence_text"] = _as_text(views.get("source_block_text"))
    promoted_views = _surface_views(promoted_row)
    return promoted_row, promoted_views, meta, "text"



def _source_overlay_supplement_score(
    *,
    sentence_row: Mapping[str, Any],
    views: Mapping[str, Any],
    matched_terms: Sequence[str],
    matched_surface: str,
    heading_hits: Sequence[str],
    local_branch_hits: Sequence[str],
) -> Tuple[float, List[str]]:
    text = _as_text(views.get("text"))
    score = 0.0
    reasons: List[str] = []
    if matched_surface == "text":
        score += 4.0
        reasons.append("target_phrase_in_sentence_text")
    elif matched_surface == "source_block":
        score += 2.5
        reasons.append("target_phrase_in_source_block")
    else:
        score += 1.0
        reasons.append("target_phrase_in_heading")
    if any(len(_source_overlay_phrase_parts(term)) >= 2 for term in matched_terms):
        score += 1.4
        reasons.append("multi_token_target_phrase")
    if any(str(term).strip().isupper() and len(_source_overlay_phrase_parts(term)) == 1 for term in matched_terms):
        score += 1.0
        reasons.append("uppercase_acronym_target_phrase")
    if _direct_overlay_relation_like(sentence_row, views):
        score += 1.0
        reasons.append("relation_like_sentence")
    if heading_hits or local_branch_hits:
        score += 0.55
        reasons.append("branch_context_present")
    if bool(sentence_row.get("is_formula_like")) or FORMULA_RE.search(text):
        score += 0.4
        reasons.append("formula_or_metric_surface")
    if len(text) < 35:
        score -= 1.5
        reasons.append("very_short_sentence_penalty")
    return round(score, 6), reasons


def _build_source_overlay_target_supplement_rows(
    *,
    sentence_rows: Sequence[Mapping[str, Any]],
    selected_kc_context_rows: Sequence[Mapping[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    cfg: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "enabled": bool(cfg.get("enabled")) and bool(cfg.get("generate_from_source_overlay")),
        "source_surface": SOURCE_OVERLAY_TARGET_SUPPLEMENT,
        "sentence_rows_seen": 0,
        "hit_count_by_kc": {},
        "accepted_count_by_kc": {},
        "supplement_rows_added": 0,
        "rejected_counts": {},
        "domain_specific_logic": False,
        "model_specific_logic": False,
    }
    if not stats["enabled"]:
        return [], stats

    phrases_by_kc = _source_overlay_target_phrase_index(selected_kc_context_rows, guidance_lookup, cfg)
    context_by_kc = {
        _as_text(row.get("kc_id")): dict(row)
        for row in selected_kc_context_rows
        if _as_text(row.get("kc_id"))
    }
    max_hits_per_kc = int(cfg.get("source_overlay_max_hits_per_kc") or 0)
    max_scan_rows = int(cfg.get("source_overlay_max_scan_rows") or 0)
    min_scan_score = float(cfg.get("source_overlay_min_scan_score") or cfg.get("min_score") or 0.0)

    rejected_counts: Counter[str] = Counter()
    accepted_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    hit_counts: Counter[str] = Counter()
    accepted_counts: Counter[str] = Counter()

    for source_row_index, raw_sentence in enumerate(sentence_rows):
        if max_scan_rows and int(stats["sentence_rows_seen"]) >= max_scan_rows:
            break
        stats["sentence_rows_seen"] = int(stats["sentence_rows_seen"]) + 1
        sentence_row = _direct_overlay_sentence_row(raw_sentence)
        views = _surface_views(sentence_row)
        text = _as_text(views.get("text"))
        if not text or not _as_text(sentence_row.get("doc_id")):
            rejected_counts["invalid_missing_text_or_doc"] += 1
            continue
        if _is_unsafe_sentence_row(sentence_row, views) or _direct_overlay_reference_like(sentence_row, views):
            rejected_counts["unsafe_or_reference_like"] += 1
            continue
        text_norm = str(views.get("text_norm") or "")
        block_norm = str(views.get("source_block_norm") or "")
        heading_norm = str(views.get("heading_norm") or "")

        for kc_id, phrases in phrases_by_kc.items():
            if max_hits_per_kc and hit_counts[kc_id] >= max_hits_per_kc:
                continue
            matched: List[str] = []
            surface = ""
            for phrase in phrases:
                if _source_overlay_boundary_phrase_hit(text_norm, phrase):
                    matched.append(phrase)
                    surface = surface or "text"
                elif _source_overlay_boundary_phrase_hit(block_norm, phrase):
                    matched.append(phrase)
                    surface = surface or "source_block"
                elif _source_overlay_boundary_phrase_hit(heading_norm, phrase):
                    matched.append(phrase)
                    surface = surface or "heading"
            if not matched:
                continue
            hit_counts[kc_id] += 1
            kc_context = context_by_kc.get(kc_id, {})

            source_window_promotion: Dict[str, Any] = {
                "version": SOURCE_OVERLAY_SOURCE_WINDOW_REHYDRATION_VERSION,
                "promoted": False,
                "reason": "not_attempted",
                "stage": "source_overlay_supplement_generation",
            }
            sentence_row, views, source_window_promotion, surface = _source_overlay_promote_source_block_window_for_supplement_scan(
                sentence_row=sentence_row,
                views=views,
                matched_terms=matched,
                matched_surface=surface or "text",
                cfg=cfg,
            )
            if bool(source_window_promotion.get("promoted")):
                text = _as_text(views.get("text"))
                text_norm = str(views.get("text_norm") or "")
                block_norm = str(views.get("source_block_norm") or "")
                heading_norm = str(views.get("heading_norm") or "")
                rematched: List[str] = []
                rematched_surface = ""
                for phrase in phrases:
                    if _source_overlay_boundary_phrase_hit(text_norm, phrase):
                        rematched.append(phrase)
                        rematched_surface = rematched_surface or "text"
                    elif _source_overlay_boundary_phrase_hit(block_norm, phrase):
                        rematched.append(phrase)
                        rematched_surface = rematched_surface or "source_block"
                    elif _source_overlay_boundary_phrase_hit(heading_norm, phrase):
                        rematched.append(phrase)
                        rematched_surface = rematched_surface or "heading"
                if not rematched:
                    rejected_counts["source_block_window_promotion_lost_target_match"] += 1
                    continue
                matched = rematched
                surface = rematched_surface or "text"

            heading_hits, local_branch_hits = _direct_overlay_branch_hits(kc_context, views)
            score, reasons = _source_overlay_supplement_score(
                sentence_row=sentence_row,
                views=views,
                matched_terms=matched,
                matched_surface=surface or "text",
                heading_hits=heading_hits,
                local_branch_hits=local_branch_hits,
            )
            if score < min_scan_score:
                rejected_counts["below_source_overlay_min_scan_score"] += 1
                continue
            accepted_counts[kc_id] += 1
            accepted_by_kc[kc_id].append(
                {
                    "kc_id": kc_id,
                    "knowledge_unit_id": kc_id,
                    "canonical_name": _as_text(kc_context.get("canonical_name")),
                    "target_signals": _dedupe_preserve_order(matched),
                    "matched_surface_terms": _dedupe_preserve_order(matched),
                    "signal_terms": _dedupe_preserve_order(matched),
                    "reason_codes": _dedupe_preserve_order([
                        SOURCE_OVERLAY_TARGET_SUPPLEMENT,
                        *reasons,
                        *(
                            [
                                SOURCE_OVERLAY_SOURCE_WINDOW_REHYDRATION_VERSION,
                                _as_text(source_window_promotion.get("reason")),
                            ]
                            if bool(source_window_promotion.get("promoted"))
                            else []
                        ),
                    ]),
                    "source_window_promotion": dict(source_window_promotion),
                    "candidate_source": SOURCE_OVERLAY_TARGET_SUPPLEMENT,
                    "source_overlay_line_no": source_row_index + 1,
                    "source_row_index": source_row_index,
                    "supplement_scan_score": score,
                    "supplement_scan_reasons": reasons,
                    **sentence_row,
                }
            )

    rows: List[Dict[str, Any]] = []
    max_per_kc = int(cfg.get("max_candidates_per_kc") or 0)
    for kc_id, hits in accepted_by_kc.items():
        hits.sort(key=lambda row: (float(row.get("supplement_scan_score") or 0.0), len(_as_str_list(row.get("matched_surface_terms"))), len(_as_text(row.get("sentence_text")))), reverse=True)
        capped = hits[:max_per_kc] if max_per_kc else hits
        if len(hits) > len(capped):
            rejected_counts["source_overlay_per_kc_cap"] += len(hits) - len(capped)
        for index, row in enumerate(capped):
            copied = dict(row)
            copied["candidate_id"] = f"{SOURCE_OVERLAY_TARGET_SUPPLEMENT}{INPUT_MEMBER_SEPARATOR}{kc_id}{INPUT_MEMBER_SEPARATOR}{index:04d}"
            rows.append(copied)

    stats["hit_count_by_kc"] = dict(sorted(hit_counts.items()))
    stats["accepted_count_by_kc"] = dict(sorted(accepted_counts.items()))
    stats["candidate_count_by_kc"] = dict(Counter(_as_text(row.get("kc_id")) for row in rows))
    stats["supplement_rows_added"] = len(rows)
    stats["rejected_counts"] = dict(sorted(rejected_counts.items()))
    stats["target_phrase_count_by_kc"] = {kc_id: len(phrases) for kc_id, phrases in phrases_by_kc.items()}
    return rows, stats



def _source_overlay_already_rehydrated_by_source_window_for_direct_overlay(
    *,
    raw_row: Mapping[str, Any],
    sentence_row: Mapping[str, Any],
    views: Mapping[str, Any],
    matched_signal_terms: Sequence[str],
    matched_surface_terms: Sequence[str],
) -> bool:
    """Return true only when source-overlay generation already repaired the local window.

    This is a narrow exemption from the direct-overlay rehydration queue. It does
    not disable rehydration generally. It only accepts rows whose promoted text is
    already target-bound, non-fragmentary, and structurally safe.
    """
    promotion = raw_row.get("source_window_promotion")
    if not isinstance(promotion, Mapping):
        return False
    if not bool(promotion.get("promoted")):
        return False

    reason = _as_text(promotion.get("reason"))
    if reason != "fragmentary_sentence_rehydrated_from_target_bound_source_block":
        return False

    text = _as_text(views.get("text"))
    if not text:
        return False
    if _looks_fragmentary(text, sentence_row):
        return False
    if _direct_overlay_reference_like(sentence_row, views):
        return False
    if _looks_prompt_like(text):
        return False
    if CAPTION_RE.search(text.lower()) or CAPTION_RE.search(_as_text(views.get("heading_text")).lower()):
        return False

    terms = _dedupe_preserve_order([
        *_as_str_list(matched_signal_terms),
        *_as_str_list(matched_surface_terms),
        *_as_str_list(raw_row.get("target_signals")),
        *_as_str_list(raw_row.get("matched_surface_terms")),
    ])
    if not terms:
        return False

    text_norm = match_normalize(text)
    if not any(_source_overlay_boundary_phrase_hit(text_norm, term) for term in terms):
        return False

    return True


def _build_direct_overlay_supplement_candidates(
    *,
    run_id: str,
    supplement_rows: Sequence[Mapping[str, Any]],
    supplement_manifest: str,
    selected_kc_context_rows: Sequence[Mapping[str, Any]],
    guidance_lookup: Mapping[str, Step5xProfileGuidance],
    existing_rows: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any] | None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    config = _direct_overlay_config_from_mapping(cfg)
    stats: Dict[str, Any] = {
        "enabled": bool(config.get("enabled")),
        "supplement_jsonl": supplement_manifest,
        "input_row_count": len(supplement_rows),
        "candidate_rows_added": 0,
        "candidate_count_by_kc": {},
        "quarantine_count": 0,
        "rehydration_queue_count": 0,
        "invalid_row_count": 0,
        "dropped_duplicate_count": 0,
        "dropped_same_patch_weaker_variant_count": 0,
        "rejected_counts": {},
    }
    if not bool(config.get("enabled")):
        return [], stats

    selected_by_kc = {
        _as_text(row.get("kc_id")): dict(row)
        for row in selected_kc_context_rows
        if _as_text(row.get("kc_id"))
    }
    existing_keys: set[Tuple[str, str, str, str, str]] = set()
    for row in existing_rows:
        kc_id = _as_text(row.get("kc_id"))
        doc_id = _as_text(row.get("doc_id"))
        sentence_id = _as_text(row.get("sentence_id"))
        block_id = _as_text(row.get("block_id"))
        raw_text_hash = _as_text(row.get("raw_text_hash"))
        if kc_id and raw_text_hash:
            existing_keys.add(
                _direct_overlay_identity_key(
                    kc_id=kc_id,
                    doc_id=doc_id,
                    sentence_id=sentence_id,
                    block_id=block_id,
                    raw_text_hash=raw_text_hash,
                )
            )

    rejected_counts: Counter[str] = Counter()
    viable_by_kc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for raw_row in supplement_rows:
        kc_id = _as_text(raw_row.get("kc_id") or raw_row.get("knowledge_unit_id") or raw_row.get("node_id"))
        kc_context = selected_by_kc.get(kc_id)
        if kc_context is None:
            rejected_counts["kc_not_selected"] += 1
            continue
        negative_terms = _negative_constraint_terms(guidance_lookup.get(kc_id))
        sentence_row = _direct_overlay_sentence_row(raw_row)
        views = _surface_views(sentence_row)
        text = _as_text(views.get("text"))
        if not text or not _as_text(sentence_row.get("doc_id")):
            rejected_counts["invalid_missing_text_or_doc"] += 1
            stats["invalid_row_count"] = int(stats["invalid_row_count"]) + 1
            continue
        if negative_terms and _sentence_row_matches_negative_constraint(views, negative_terms):
            rejected_counts["negative_constraint"] += 1
            stats["quarantine_count"] = int(stats["quarantine_count"]) + 1
            continue
        target_signals = _direct_overlay_target_signals(raw_row)
        matched_signal_terms, matched_signal_tokens, signal_surface = _direct_overlay_signal_hits(views, target_signals)
        matched_surface_terms = _route_terms_hit(
            views,
            [_as_text(kc_context.get("canonical_name")), *_as_str_list(kc_context.get("aliases"))],
        )
        matched_target_tokens = _matched_target_tokens_from_terms(
            terms=[_as_text(kc_context.get("canonical_name")), *_as_str_list(kc_context.get("aliases"))],
            views=views,
        )
        for token in matched_signal_tokens:
            if token not in matched_target_tokens:
                matched_target_tokens.append(token)
        reason_codes = _dedupe_preserve_order(_direct_overlay_collect_reasonish_strings(raw_row))

        if bool(config.get("reject_reference_like")) and _direct_overlay_reference_like(sentence_row, views):
            rejected_counts["reference_like"] += 1
            stats["quarantine_count"] = int(stats["quarantine_count"]) + 1
            continue
        if bool(config.get("reject_prompt_like")) and _looks_prompt_like(text):
            rejected_counts["prompt_like"] += 1
            stats["quarantine_count"] = int(stats["quarantine_count"]) + 1
            continue
        if CAPTION_RE.search(text.lower()) or CAPTION_RE.search(_as_text(views.get("heading_text")).lower()):
            rejected_counts["caption_like"] += 1
            stats["quarantine_count"] = int(stats["quarantine_count"]) + 1
            continue
        if bool(config.get("reject_fragmentary")) and _direct_overlay_rehydration_needed(
            sentence_row,
            views,
            matched_surface_terms=matched_surface_terms,
            matched_signal_terms=matched_signal_terms,
            reason_codes=reason_codes,
            reject_formula_only_without_target_signal=bool(
                config.get("reject_formula_only_without_target_signal")
            ),
        ):
            if _source_overlay_already_rehydrated_by_source_window_for_direct_overlay(
                raw_row=raw_row,
                sentence_row=sentence_row,
                views=views,
                matched_signal_terms=matched_signal_terms,
                matched_surface_terms=matched_surface_terms,
            ):
                pass
            else:
                rejected_counts["rehydration_required"] += 1
                stats["rehydration_queue_count"] = int(stats["rehydration_queue_count"]) + 1
                continue

        exact_name_phrase, exact_alias_phrase = _direct_exact_match_flags(
            canonical_name=_as_text(kc_context.get("canonical_name")),
            aliases=_as_str_list(kc_context.get("aliases")),
            views=views,
        )
        heading_hits, local_hits = _direct_overlay_branch_hits(kc_context, views)
        relation_like = _direct_overlay_relation_like(sentence_row, views)
        has_exact_surface = bool(exact_name_phrase or exact_alias_phrase or matched_signal_terms)
        multi_token_target = len(set(matched_target_tokens)) >= 2
        if not (has_exact_surface or multi_token_target or (relation_like and matched_target_tokens and (heading_hits or local_hits))):
            rejected_counts["insufficient_target_binding"] += 1
            stats["quarantine_count"] = int(stats["quarantine_count"]) + 1
            continue

        hierarchy_match_type = (
            "heading_branch_overlap"
            if heading_hits
            else ("local_context_branch_overlap" if local_hits else "supplement_target_bound_source")
        )
        if exact_name_phrase:
            fallback_tier = "direct_overlay_exact_surface"
            surface_match_type = "exact_canonical_text"
            score = 8.6
        elif exact_alias_phrase:
            fallback_tier = "direct_overlay_exact_surface"
            surface_match_type = "exact_alias_text"
            score = 8.3
        elif matched_signal_terms:
            fallback_tier = "direct_overlay_target_signal"
            surface_match_type = f"supplement_signal_{signal_surface or 'text'}"
            score = 7.9
        elif multi_token_target:
            fallback_tier = "direct_overlay_multi_token"
            surface_match_type = "multi_target_token_text"
            score = 7.1
        else:
            fallback_tier = "direct_overlay_context_bound"
            surface_match_type = "context_bound_target_signal"
            score = 6.3
        if relation_like:
            score += 0.55
        if heading_hits or local_hits:
            score += 0.35
        score += min(0.6, 0.15 * len(matched_signal_terms))
        score += min(0.4, 0.1 * len(set(matched_target_tokens)))
        score = round(score, 6)
        if score < float(config.get("min_score") or 0.0):
            rejected_counts["below_min_score"] += 1
            continue

        viable_by_kc[kc_id].append(
            {
                "kc_context": kc_context,
                "sentence_row": sentence_row,
                "views": views,
                "raw_row": dict(raw_row),
                "text": text,
                "reason_codes": reason_codes[:12],
                "target_signals": target_signals[:12],
                "matched_signal_terms": matched_signal_terms,
                "matched_target_tokens": matched_target_tokens,
                "matched_surface_terms": _dedupe_preserve_order([*matched_surface_terms, *matched_signal_terms]),
                "signal_surface": signal_surface or "text",
                "fallback_tier": fallback_tier,
                "surface_match_type": surface_match_type,
                "hierarchy_match_type": hierarchy_match_type,
                "score": score,
                "relation_like": relation_like,
                "shape_tags": _structural_shape_tags(sentence_row, views),
                "shape_preferences": _shape_preference_flags(kc_context, guidance_lookup.get(kc_id)),
                "source_window_promotion": dict(raw_row.get("source_window_promotion") or {}),
            }
        )

    rows: List[Dict[str, Any]] = []
    for kc_id, infos in viable_by_kc.items():
        kept: List[Dict[str, Any]] = []
        infos.sort(key=_direct_overlay_quality_tuple, reverse=True)
        for info in infos:
            sentence_row = info["sentence_row"]
            raw_text_hash = _raw_text_hash(_as_text(info["text"]))
            identity_key = _direct_overlay_identity_key(
                kc_id=kc_id,
                doc_id=_as_text(sentence_row.get("doc_id")),
                sentence_id=_as_text(sentence_row.get("sentence_id")),
                block_id=_as_text(sentence_row.get("block_id")),
                raw_text_hash=raw_text_hash,
            )
            if identity_key in existing_keys:
                rejected_counts["duplicate_of_existing_candidate"] += 1
                stats["dropped_duplicate_count"] = int(stats["dropped_duplicate_count"]) + 1
                continue
            duplicate_variant = False
            for prior in kept:
                same_patch = bool(
                    _as_text(prior["sentence_row"].get("patch_id"))
                    and _as_text(prior["sentence_row"].get("patch_id")) == _as_text(sentence_row.get("patch_id"))
                    and _as_text(prior["sentence_row"].get("doc_id")) == _as_text(sentence_row.get("doc_id"))
                )
                if not same_patch:
                    continue
                if _direct_overlay_soft_overlap(_as_text(prior["text"]), _as_text(info["text"])) >= 0.85:
                    duplicate_variant = True
                    break
            if duplicate_variant:
                rejected_counts["same_patch_weaker_variant"] += 1
                stats["dropped_same_patch_weaker_variant_count"] = (
                    int(stats["dropped_same_patch_weaker_variant_count"]) + 1
                )
                continue
            kept.append(info)
            existing_keys.add(identity_key)

        capped = kept[: int(config.get("max_candidates_per_kc") or 0)]
        if len(kept) > len(capped):
            rejected_counts["per_kc_cap"] += len(kept) - len(capped)
        for info in capped:
            sentence_row = info["sentence_row"]
            kc_context = info["kc_context"]
            sentence_id = _as_text(sentence_row.get("sentence_id"))
            source_manifest = supplement_manifest
            row = _candidate_row_from_overlay_sentence(
                sentence_row=sentence_row,
                source_row_index=0,
                kc_context=kc_context,
                run_id=run_id,
                source_manifest=source_manifest,
                candidate_source=SOURCE_DIRECT_OVERLAY_SUPPLEMENT,
                fallback_tier=_as_text(info["fallback_tier"]),
                fallback_reason=f"{_as_text(info['fallback_tier'])}:{_as_text(info['surface_match_type'])}",
                fallback_score=float(info["score"]),
                fallback_score_reasons=[
                    "direct_overlay_supplement",
                    f"surface:{_as_text(info['surface_match_type'])}",
                    f"hierarchy:{_as_text(info['hierarchy_match_type'])}",
                    "source_local_sentence_verification",
                ],
                matched_surface_terms=_as_str_list(info["matched_surface_terms"]),
                matched_target_tokens=_as_str_list(info["matched_target_tokens"]),
                surface_match_type=_as_text(info["surface_match_type"]),
                hierarchy_match_type=_as_text(info["hierarchy_match_type"]),
                anchor_candidate_id="",
                anchor_sentence_id=sentence_id,
                shape_preferences=info["shape_preferences"],
                shape_tags=info["shape_tags"],
                source_surface=SOURCE_DIRECT_OVERLAY_SUPPLEMENT,
            )
            support_profile = dict(row.get("support_profile") or {})
            support_profile["candidate_source"] = SOURCE_DIRECT_OVERLAY_SUPPLEMENT
            support_profile["target_signals"] = list(info["target_signals"])
            support_profile["supplement_signal_terms"] = list(info["matched_signal_terms"])
            support_profile["supplement_signal_surface"] = _as_text(info["signal_surface"])
            support_profile["direct_overlay_supplement"] = True
            source_window_promotion = dict(info.get("source_window_promotion") or {})
            if bool(source_window_promotion.get("promoted")):
                support_profile["source_overlay_source_block_window"] = True
                support_profile["source_overlay_window_promotion"] = dict(source_window_promotion)
            support_profile["anchor_quality"] = "strong" if float(info["score"]) >= 7.5 else "usable"
            row["support_profile"] = support_profile

            alignment_breakdown = dict(row.get("alignment_breakdown") or {})
            alignment_breakdown["context_keyword_hits"] = max(
                int(alignment_breakdown.get("context_keyword_hits") or 0),
                len(_as_str_list(info["matched_signal_terms"])),
            )
            alignment_breakdown["supplement_target_signals"] = list(info["target_signals"])
            alignment_breakdown["supplement_signal_surface"] = _as_text(info["signal_surface"])
            if bool(source_window_promotion.get("promoted")):
                alignment_breakdown["source_overlay_source_block_window"] = True
                alignment_breakdown["source_overlay_window_promotion_reason"] = _as_text(source_window_promotion.get("reason"))
            row["alignment_breakdown"] = alignment_breakdown

            provenance = dict(row.get("provenance") or {})
            provenance["from_step"] = "step5x_direct_overlay_supplement"
            provenance["source_manifest"] = supplement_manifest
            provenance["source_jsonl"] = supplement_manifest
            provenance["candidate_source"] = SOURCE_DIRECT_OVERLAY_SUPPLEMENT
            provenance["supplement_candidate_id"] = _as_text(info["raw_row"].get("candidate_id"))
            provenance["supplement_input_candidate_source"] = _as_text(
                info["raw_row"].get("candidate_source")
            )
            provenance["supplement_target_signals"] = list(info["target_signals"])
            provenance["supplement_reason_codes"] = list(info["reason_codes"])
            provenance["supplement_signal_surface"] = _as_text(info["signal_surface"])
            if bool(source_window_promotion.get("promoted")):
                provenance["source_overlay_source_block_window"] = True
                provenance["source_overlay_window_promotion"] = dict(source_window_promotion)
            provenance["candidate_bank_source_surface"] = SOURCE_DIRECT_OVERLAY_SUPPLEMENT
            row["provenance"] = provenance

            retrieval_scores = dict(row.get("retrieval_scores") or {})
            retrieval_scores["source_type"] = "direct_overlay_supplement"
            row["retrieval_scores"] = retrieval_scores
            row["candidate_source"] = SOURCE_DIRECT_OVERLAY_SUPPLEMENT
            row["source_surface"] = SOURCE_DIRECT_OVERLAY_SUPPLEMENT
            rows.append(row)

        stats["candidate_count_by_kc"][kc_id] = len(capped)

    stats["candidate_rows_added"] = len(rows)
    stats["rejected_counts"] = dict(sorted(rejected_counts.items()))
    return rows, stats


def _build_clean_slate_candidate_rows(
    *,
    run_id: str,
    registry_jsonl: str,
    source_overlay_jsonl: str,
    sentence_rows: Sequence[Mapping[str, Any]],
    selected_kc_context_rows: Sequence[Mapping[str, Any]],
    registry_kc_context_lookup: Mapping[str, Mapping[str, Any]],
    profile_guidance_lookup: Mapping[str, Step5xProfileGuidance],
    existing_candidate_rows: Sequence[Mapping[str, Any]],
    source_surface_fallback_cfg: Mapping[str, Any] | None,
    direct_overlay_supplement_cfg: Mapping[str, Any] | None,
    seed_field_detection_in_registry: Mapping[str, Any],
    allow_reference_artifact_inputs: bool,
    allow_seed_bearing_input_for_diagnostic: bool,
    repo_root: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    requested_cfg = fallback_config_from_mapping(source_surface_fallback_cfg)
    supplement_rows, supplement_manifest, supplement_seed_detection, supplement_cfg = _load_direct_overlay_supplement_rows(
        cfg=direct_overlay_supplement_cfg,
        repo_root=repo_root,
        allow_reference_artifact_inputs=allow_reference_artifact_inputs,
        allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
    )
    generated_supplement_rows, generated_supplement_stats = _build_source_overlay_target_supplement_rows(
        sentence_rows=sentence_rows,
        selected_kc_context_rows=selected_kc_context_rows,
        guidance_lookup=profile_guidance_lookup,
        cfg=supplement_cfg,
    )
    if generated_supplement_rows:
        supplement_rows = [*supplement_rows, *generated_supplement_rows]
        if not supplement_manifest:
            supplement_manifest = source_overlay_jsonl
    effective_cfg = dict(vars(requested_cfg))
    forced_for_clean_slate = False
    if not requested_cfg.enabled:
        effective_cfg["enabled"] = True
        forced_for_clean_slate = True

    fallback_result = build_source_surface_fallback_candidates(
        sentence_rows,
        selected_kc_contexts=selected_kc_context_rows,
        registry_kc_contexts=list(registry_kc_context_lookup.values()),
        existing_candidate_rows=existing_candidate_rows,
        config=effective_cfg,
        sentence_source_manifest=source_overlay_jsonl,
        sentence_source_jsonl=source_overlay_jsonl,
    )
    rows = [
        _candidate_bank_row_from_fallback_payload(
            payload,
            run_id=run_id,
            source_manifest=source_overlay_jsonl,
        )
        for payload in fallback_result.get("rows") or []
        if isinstance(payload, Mapping)
    ]
    _apply_clean_slate_provenance(
        rows,
        registry_jsonl=registry_jsonl,
        source_overlay_jsonl=source_overlay_jsonl,
    )
    direct_overlay_rows, direct_overlay_stats = _build_direct_overlay_supplement_candidates(
        run_id=run_id,
        supplement_rows=supplement_rows,
        supplement_manifest=supplement_manifest,
        selected_kc_context_rows=selected_kc_context_rows,
        guidance_lookup=profile_guidance_lookup,
        existing_rows=rows,
        cfg=supplement_cfg,
    )
    if direct_overlay_rows:
        rows.extend(direct_overlay_rows)
        _apply_clean_slate_provenance(
            direct_overlay_rows,
            registry_jsonl=registry_jsonl,
            source_overlay_jsonl=source_overlay_jsonl,
        )
    structural_rows, structural_stats = _expand_structural_candidates_from_anchors(
        run_id=run_id,
        source_overlay_jsonl=source_overlay_jsonl,
        sentence_rows=sentence_rows,
        selected_kc_context_rows=selected_kc_context_rows,
        guidance_lookup=profile_guidance_lookup,
        existing_rows=rows,
    )
    if structural_rows:
        rows.extend(structural_rows)
        _apply_clean_slate_provenance(
            structural_rows,
            registry_jsonl=registry_jsonl,
            source_overlay_jsonl=source_overlay_jsonl,
        )
    profile_provenance_rows, profile_provenance_stats = _build_profile_provenance_rehydration_candidates(
        run_id=run_id,
        source_overlay_jsonl=source_overlay_jsonl,
        sentence_rows=sentence_rows,
        selected_kc_context_rows=selected_kc_context_rows,
        guidance_lookup=profile_guidance_lookup,
        existing_rows=rows,
    )
    if profile_provenance_rows:
        rows.extend(profile_provenance_rows)
        _apply_clean_slate_provenance(
            profile_provenance_rows,
            registry_jsonl=registry_jsonl,
            source_overlay_jsonl=source_overlay_jsonl,
        )

    fallback_stats = dict(fallback_result.get("stats") or {})
    fallback_stats.update(
        {
            "requested_enabled": bool(requested_cfg.enabled),
            "enabled": True,
            "forced_for_clean_slate": forced_for_clean_slate,
            "resolved_from": "direct_source_overlay_jsonl",
            "sentence_source_manifest": source_overlay_jsonl,
            "sentence_source_jsonl": source_overlay_jsonl,
        }
    )
    counts = {str(key): int(value or 0) for key, value in dict(fallback_stats.get("candidate_count_by_kc") or {}).items()}
    for kc_id, supplement_count in dict(direct_overlay_stats.get("candidate_count_by_kc") or {}).items():
        counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(supplement_count or 0)
    for kc_id, anchor_count in dict(structural_stats.get("anchor_rows_added_by_kc") or {}).items():
        counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(anchor_count or 0)
    for kc_id, neighbor_count in dict(structural_stats.get("neighbor_rows_added_by_kc") or {}).items():
        counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(neighbor_count or 0)
    for kc_id, profile_count in dict(profile_provenance_stats.get("profile_provenance_rehydration_count_by_kc") or {}).items():
        counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(profile_count or 0)
    stats = {
        "run_id": run_id,
        "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
        "input_mode": INPUT_MODE_CLEAN_SLATE,
        "source_manifest": source_overlay_jsonl,
        "registry_jsonl": registry_jsonl,
        "source_overlay_jsonl": source_overlay_jsonl,
        "total_kc_rows_seen": len(selected_kc_context_rows),
        "total_candidate_rows_emitted": len(rows),
        "kcs_with_candidates": sum(1 for count in counts.values() if int(count or 0) > 0),
        "kcs_without_candidates": max(
            0,
            len(selected_kc_context_rows) - sum(1 for count in counts.values() if int(count or 0) > 0),
        ),
        "candidate_count_by_kc": counts,
        "source_surface_breakdown": _source_surface_breakdown(rows),
        "granularity_breakdown": {
            "sentence": sum(1 for row in rows if _as_text(row.get("granularity")) == "sentence"),
            "block": sum(1 for row in rows if _as_text(row.get("granularity")) == "block"),
            "unknown": sum(1 for row in rows if _as_text(row.get("granularity")) not in {"sentence", "block"}),
        },
        "missing_provenance_counts": _missing_value_counts(rows),
        "seed_fields_detected_in_input": int(seed_field_detection_in_registry.get("total") or 0)
        + int(supplement_seed_detection.get("total") or 0),
        "seed_fields_propagated_to_output": 0,
        "seed_field_detection": {
            "registry_input": {
                "total": int(seed_field_detection_in_registry.get("total") or 0),
                "by_key": dict(seed_field_detection_in_registry.get("by_key") or {}),
            },
            "direct_overlay_supplement_input": {
                "total": int(supplement_seed_detection.get("total") or 0),
                "by_key": dict(supplement_seed_detection.get("by_key") or {}),
            },
        },
        "source_surface_fallback": fallback_stats,
        "direct_overlay_supplement": direct_overlay_stats,
        "source_overlay_target_supplement": generated_supplement_stats,
        "structural_anchor_expansion": structural_stats,
        "profile_provenance_rehydration": profile_provenance_stats,
        "profile_provenance_rehydration_rows": int(profile_provenance_stats.get("profile_provenance_rehydration_rows") or 0),
        "profile_provenance_rehydration_count_by_kc": dict(
            profile_provenance_stats.get("profile_provenance_rehydration_count_by_kc") or {}
        ),
        "profile_provenance_missing_source_ids_by_kc": dict(
            profile_provenance_stats.get("profile_provenance_missing_source_ids_by_kc") or {}
        ),
    }
    return rows, stats, SOURCE_SURFACE_FALLBACK


def _raw_text_hash(text: str) -> str:
    normalized = match_normalize(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_candidate_id(
    *,
    kc_id: str,
    source_surface: str,
    source_manifest: str,
    source_row_index: int,
    source_evidence_index: int,
    doc_id: str,
    block_id: str,
    sentence_id: str,
    patch_id: str,
    page_index: Optional[int],
    raw_text_hash: str,
) -> str:
    payload = {
        "kc_id": kc_id,
        "source_surface": source_surface,
        "source_manifest": source_manifest,
        "source_row_index": int(source_row_index),
        "source_evidence_index": int(source_evidence_index),
        "doc_id": doc_id,
        "block_id": block_id,
        "sentence_id": sentence_id,
        "patch_id": patch_id,
        "page_index": page_index,
        "raw_text_hash": raw_text_hash,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"cand_{digest[:24]}"


def _looks_formula_like(text: str, evidence: Mapping[str, Any]) -> bool:
    flags = evidence.get("alignment_breakdown") or {}
    nested_flags = {}
    if isinstance(flags, Mapping):
        nested_flags = flags.get("flags") or {}
    return bool(
        (isinstance(nested_flags, Mapping) and nested_flags.get("is_formula_like"))
        or FORMULA_RE.search(text)
        or FORMULA_RE.search(_as_text(evidence.get("source_block_text")))
    )


def _looks_caption_like(text: str, evidence: Mapping[str, Any]) -> bool:
    heading = _as_text(evidence.get("patch_heading"))
    return bool(CAPTION_RE.search(text.lower()) or CAPTION_RE.search(heading.lower()))


def _looks_prompt_like(text: str) -> bool:
    return bool(PROMPT_RE.search(text.lower()))


def _looks_fragmentary(text: str, evidence: Mapping[str, Any]) -> bool:
    support_profile = evidence.get("support_profile") or {}
    if isinstance(support_profile, Mapping) and bool(support_profile.get("fragmentary_surface")):
        return True
    lower = text.lower()
    if not lower:
        return True
    if len(lower) < 28:
        return True
    if FRAGMENT_PREFIX_RE.search(lower):
        return True
    if TRAILING_FRAGMENT_RE.search(lower):
        return True
    return False


def detect_granularity(text: str, source_block_text: str, evidence: Mapping[str, Any]) -> str:
    if _as_text(evidence.get("sentence_id")) or evidence.get("sent_idx") is not None or text:
        return "sentence"
    if source_block_text and _as_text(evidence.get("block_id")):
        return "block"
    return "unknown"


def build_structural_flags(text: str, source_block_text: str, evidence: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "has_text": bool(text),
        "has_source_block_text": bool(source_block_text),
        "has_sentence_id": bool(_as_text(evidence.get("sentence_id"))),
        "has_patch_id": bool(_as_text(evidence.get("patch_id"))),
        "has_page_index": _as_int(evidence.get("page_index")) is not None,
        "looks_formula_like": _looks_formula_like(text, evidence),
        "looks_caption_like": _looks_caption_like(text, evidence),
        "looks_prompt_like": _looks_prompt_like(text),
        "looks_fragmentary": _looks_fragmentary(text, evidence),
    }


def select_source_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    exact_kc_ids: Optional[Sequence[str]] = None,
    limit_kcs: Optional[int] = None,
) -> List[Tuple[int, Mapping[str, Any]]]:
    indexed = list(enumerate(rows))
    if exact_kc_ids:
        by_id = {str(row.get("kc_id") or ""): (idx, row) for idx, row in indexed}
        missing = [str(kc_id) for kc_id in exact_kc_ids if str(kc_id) not in by_id]
        if missing:
            # Zero-candidate KCs are valid in clean-slate evidence retrieval.
            # A requested KC may have no Stage 1 candidates because retrieval failed,
            # not because the KC is unknown or corpus-insufficient.
            # Keep available rows and let downstream pack composition represent
            # missing KCs as insufficient-support / zero-candidate cases.
            pass
        chosen = [by_id[str(kc_id)] for kc_id in exact_kc_ids]
        if limit_kcs is not None and len(chosen) != int(limit_kcs):
            raise RuntimeError(f"Configured exact_kc_ids length {len(chosen)} does not match limit_kcs {int(limit_kcs)}")
        return chosen if limit_kcs is None else chosen[: int(limit_kcs)]
    if limit_kcs is None:
        return indexed
    return indexed[: int(limit_kcs)]


def _missing_value_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    fields = (
        "doc_id",
        "page_index",
        "block_id",
        "sentence_id",
        "patch_id",
        "patch_heading",
        "reveal_group_id",
        "layer",
        "bbox",
        "char_start",
        "char_end",
    )
    counts = {field: 0 for field in fields}
    for row in rows:
        for field in fields:
            value = row.get(field)
            if field == "bbox":
                missing = not isinstance(value, list) or len(value) == 0
            else:
                missing = value in (None, "", [])
            if missing:
                counts[field] += 1
    return counts


def _schema_snapshot(rows: Sequence[Mapping[str, Any]], *, run_id: str, source_manifest: str) -> Dict[str, Any]:
    first = dict(rows[0]) if rows else {}
    return {
        "run_id": run_id,
        "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
        "source_manifest": source_manifest,
        "required_row_keys": list(REQUIRED_ROW_KEYS),
        "observed_row_keys": list(first.keys()),
        "structural_flag_keys": list(STRUCTURAL_FLAG_KEYS),
        "provenance_keys": list((first.get("provenance") or {}).keys()) if isinstance(first.get("provenance"), Mapping) else [],
        "sample_row": first,
    }


def flatten_step5_3_nested_evidence_rows(
    step5_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    source_manifest: str,
    source_jsonl: str,
    exact_kc_ids: Optional[Sequence[str]] = None,
    limit_kcs: Optional[int] = None,
    kc_context_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
    preserve_raw_support_profile: bool = True,
    preserve_raw_alignment_breakdown: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    selected = select_source_rows(step5_rows, exact_kc_ids=exact_kc_ids, limit_kcs=limit_kcs)
    output_rows: List[Dict[str, Any]] = []
    candidate_count_by_kc: Dict[str, int] = {}
    granularity_counter: Dict[str, int] = {}
    seed_fields_detected = 0
    kcs_with_candidates = 0
    kcs_without_candidates = 0

    for source_row_index, step5_row in selected:
        seed_fields_detected += count_forbidden_seed_fields(step5_row)
        kc_id = _as_text(step5_row.get("kc_id"))
        if not kc_id:
            continue
        context_row = dict((kc_context_lookup or {}).get(kc_id) or {})
        canonical_name = _as_text(context_row.get("canonical_name") or step5_row.get("canonical_name"))
        aliases = _dedupe_preserve_order(
            _as_str_list(context_row.get("aliases")) + _as_str_list(step5_row.get("aliases"))
        )
        topic_path_ids = _as_str_list(context_row.get("topic_path_ids"))
        topic_path_labels = _as_str_list(context_row.get("topic_path_labels"))
        parent_topic_id = _as_text(context_row.get("parent_topic_id"))
        parent_topic_label = _as_text(context_row.get("parent_topic_label"))

        evidence_items = step5_row.get("evidence")
        if not isinstance(evidence_items, list) or not evidence_items:
            candidate_count_by_kc[kc_id] = 0
            kcs_without_candidates += 1
            continue

        emitted_for_kc = 0
        for source_evidence_index, evidence in enumerate(evidence_items):
            if not isinstance(evidence, Mapping):
                continue
            sanitized_evidence = strip_forbidden_seed_fields(dict(evidence))
            if not isinstance(sanitized_evidence, Mapping):
                continue
            text = _as_text(
                sanitized_evidence.get("snippet")
                or sanitized_evidence.get("quote_surface")
                or sanitized_evidence.get("text")
                or sanitized_evidence.get("source_block_text")
            )
            source_block_text = _as_text(sanitized_evidence.get("source_block_text"))
            raw_text_hash = _raw_text_hash(text)
            doc_id = _as_text(sanitized_evidence.get("doc_id"))
            block_id = _as_text(sanitized_evidence.get("block_id"))
            sentence_id = _as_text(sanitized_evidence.get("sentence_id"))
            patch_id = _as_text(sanitized_evidence.get("patch_id"))
            page_index = _as_int(sanitized_evidence.get("page_index"))
            granularity = detect_granularity(text, source_block_text, sanitized_evidence)
            structural_flags = build_structural_flags(text, source_block_text, sanitized_evidence)
            alignment_breakdown = {}
            if preserve_raw_alignment_breakdown:
                alignment_breakdown = strip_forbidden_seed_fields(sanitized_evidence.get("alignment_breakdown") or {})
                if not isinstance(alignment_breakdown, Mapping):
                    alignment_breakdown = {}
            support_profile = {}
            if preserve_raw_support_profile:
                support_profile = strip_forbidden_seed_fields(sanitized_evidence.get("support_profile") or {})
                if not isinstance(support_profile, Mapping):
                    support_profile = {}
            row = {
                "candidate_id": build_candidate_id(
                    kc_id=kc_id,
                    source_surface=SOURCE_SURFACE_STEP53_NESTED,
                    source_manifest=source_manifest,
                    source_row_index=source_row_index,
                    source_evidence_index=source_evidence_index,
                    doc_id=doc_id,
                    block_id=block_id,
                    sentence_id=sentence_id,
                    patch_id=patch_id,
                    page_index=page_index,
                    raw_text_hash=raw_text_hash,
                ),
                "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
                "run_id": run_id,
                "source_surface": SOURCE_SURFACE_STEP53_NESTED,
                "source_manifest": source_manifest,
                "source_row_index": int(source_row_index),
                "source_evidence_index": int(source_evidence_index),
                "kc_id": kc_id,
                "canonical_name": canonical_name,
                "aliases": aliases,
                "topic_path_ids": topic_path_ids,
                "topic_path_labels": topic_path_labels,
                "parent_topic_id": parent_topic_id,
                "parent_topic_label": parent_topic_label,
                "source_kc_id": _as_text(sanitized_evidence.get("source_kc_id")) or kc_id,
                "source_canonical_name": _as_text(sanitized_evidence.get("source_canonical_name")) or canonical_name,
                "granularity": granularity,
                "text": text,
                "source_block_text": source_block_text,
                "context_text": "",
                "doc_id": doc_id,
                "page_index": page_index,
                "block_id": block_id,
                "sentence_id": sentence_id,
                "sent_idx": _as_int(sanitized_evidence.get("sent_idx")),
                "patch_id": patch_id,
                "patch_heading": _as_text(sanitized_evidence.get("patch_heading")),
                "reveal_group_id": _as_text(sanitized_evidence.get("reveal_group_id")),
                "layer": _as_text(sanitized_evidence.get("layer")),
                "bbox": list(sanitized_evidence.get("bbox") or []) if isinstance(sanitized_evidence.get("bbox"), list) else [],
                "char_start": _as_int(sanitized_evidence.get("char_start")),
                "char_end": _as_int(sanitized_evidence.get("char_end")),
                "retrieval_scores": strip_forbidden_seed_fields(sanitized_evidence.get("retrieval_scores") or {})
                if isinstance(sanitized_evidence.get("retrieval_scores"), Mapping)
                else {},
                "alignment_score": sanitized_evidence.get("alignment_score"),
                "alignment_breakdown": dict(alignment_breakdown),
                "support_profile": dict(support_profile),
                "structural_flags": structural_flags,
                "raw_text_hash": raw_text_hash,
                "provenance": {
                    "from_step": SOURCE_STEP,
                    "source_manifest": source_manifest,
                    "source_jsonl": source_jsonl,
                    "source_row_index": int(source_row_index),
                    "source_evidence_index": int(source_evidence_index),
                },
            }
            output_rows.append(row)
            granularity_counter[granularity] = granularity_counter.get(granularity, 0) + 1
            emitted_for_kc += 1

        candidate_count_by_kc[kc_id] = emitted_for_kc
        if emitted_for_kc > 0:
            kcs_with_candidates += 1
        else:
            kcs_without_candidates += 1

    stats = {
        "run_id": run_id,
        "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
        "source_manifest": source_manifest,
        "total_kc_rows_seen": len(selected),
        "total_candidate_rows_emitted": len(output_rows),
        "kcs_with_candidates": kcs_with_candidates,
        "kcs_without_candidates": kcs_without_candidates,
        "candidate_count_by_kc": candidate_count_by_kc,
        "source_surface_breakdown": {SOURCE_SURFACE_STEP53_NESTED: len(output_rows)},
        "granularity_breakdown": granularity_counter,
        "missing_provenance_counts": _missing_value_counts(output_rows),
        "seed_fields_detected_in_input": seed_fields_detected,
        "seed_fields_propagated_to_output": 0,
    }
    schema_snapshot = _schema_snapshot(output_rows, run_id=run_id, source_manifest=source_manifest)
    return output_rows, stats, schema_snapshot


def _materialize_run_paths(
    *,
    output_root: Path,
    set_manifest_root: Path,
    run_id: Optional[str],
) -> Dict[str, Path]:
    chosen_run_id = str(run_id or utc_stamp())
    processed_dir = (output_root / chosen_run_id).resolve()
    set_manifest_path = (set_manifest_root / f"{chosen_run_id}_step5x_v3_candidate_bank_set.json").resolve()
    if processed_dir.exists() or set_manifest_path.exists():
        raise RuntimeError(f"Requested run_id already exists: {chosen_run_id}")
    return {
        "run_id": Path(chosen_run_id),
        "processed_dir": processed_dir,
        "set_manifest_path": set_manifest_path,
    }


def run_candidate_bank_stage(
    *,
    run_id: Optional[str],
    step5_3_set_manifest_spec: Optional[str],
    step5_3_candidates_jsonl_spec: Optional[str],
    registry_jsonl_spec: Optional[str] = None,
    source_overlay_jsonl_spec: Optional[str] = None,
    config_path: str,
    exact_kc_ids: Optional[Sequence[str]],
    limit_kcs: Optional[int],
    output_root: Path,
    set_manifest_root: Path,
    allow_reference_artifact_inputs: bool,
    fail_if_no_candidate_source: bool,
    exclude_seed_fields: bool,
    preserve_raw_support_profile: bool,
    preserve_raw_alignment_breakdown: bool,
    allow_seed_bearing_input_for_diagnostic: bool = False,
    profile_jsonl_spec: Optional[str] = None,
    source_surface_fallback_cfg: Mapping[str, Any] | None = None,
    direct_overlay_supplement_cfg: Mapping[str, Any] | None = None,
    repo_root: Path = REPO_ROOT,
) -> Dict[str, Any]:
    if not exclude_seed_fields:
        raise RuntimeError("Stage 1 candidate-bank output forbids seed-field propagation; exclude_seed_fields must stay true.")

    clean_slate_requested = bool(_as_text(registry_jsonl_spec) or _as_text(source_overlay_jsonl_spec))
    if clean_slate_requested and (not _as_text(registry_jsonl_spec) or not _as_text(source_overlay_jsonl_spec)):
        raise RuntimeError(
            "Clean-slate candidate-bank mode requires both --registry-jsonl and --source-overlay-jsonl."
        )

    manifest_spec: Optional[InputSpec] = None
    candidate_spec: Optional[InputSpec] = None
    manifest_obj: Dict[str, Any] = {}
    registry_jsonl = ""
    source_overlay_jsonl = ""
    source_manifest_identity = ""
    input_mode = INPUT_MODE_CLEAN_SLATE if clean_slate_requested else INPUT_MODE_LEGACY_STEP5_3
    step5_rows: List[Dict[str, Any]] = []
    kc_context_lookup: Dict[str, Dict[str, Any]] = {}
    selected_kc_context_rows: List[Dict[str, Any]] = []
    sentence_rows: List[Dict[str, Any]] = []
    clean_slate_seed_field_detection: Dict[str, Any] = {"total": 0, "by_key": {}}
    legacy_registry_seed_field_detection: Dict[str, Any] = {"total": 0, "by_key": {}}
    step5_input_seed_field_detection: Dict[str, Any] = {"total": 0, "by_key": {}}

    if clean_slate_requested:
        registry_spec = parse_input_spec(registry_jsonl_spec, repo_root=repo_root)
        source_overlay_spec = parse_input_spec(source_overlay_jsonl_spec, repo_root=repo_root)
        (
            selected_kc_context_rows,
            kc_context_lookup,
            registry_jsonl,
            clean_slate_seed_field_detection,
        ) = _load_clean_slate_kc_context_rows(
            registry_spec=registry_spec,
            repo_root=repo_root,
            allow_reference_artifact_inputs=allow_reference_artifact_inputs,
            allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
            exact_kc_ids=[str(kc_id) for kc_id in exact_kc_ids or []] or None,
            limit_kcs=limit_kcs,
        )
        sentence_rows, source_overlay_jsonl = _resolve_clean_slate_sentence_corpus(
            source_overlay_spec=source_overlay_spec,
            allow_reference_artifact_inputs=allow_reference_artifact_inputs,
        )
        source_manifest_identity = source_overlay_jsonl
    else:
        if step5_3_set_manifest_spec:
            manifest_spec = parse_input_spec(step5_3_set_manifest_spec, repo_root=repo_root)
            ensure_reference_allowed(manifest_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
            if not input_spec_exists(manifest_spec):
                raise FileNotFoundError(f"Step 5.3 set manifest not found: {manifest_spec.display()}")

        if step5_3_candidates_jsonl_spec:
            candidate_spec = resolve_related_input_spec(
                step5_3_candidates_jsonl_spec,
                repo_root=repo_root,
                base_spec=manifest_spec,
            )
            ensure_reference_allowed(candidate_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)

        if manifest_spec is not None:
            manifest_obj = read_json_from_spec(manifest_spec)
            if candidate_spec is None:
                artifacts = manifest_obj.get("artifacts") or {}
                raw_candidates = artifacts.get("kc_evidence_candidates_recalibrated_jsonl")
                if not raw_candidates:
                    raise RuntimeError(
                        f"Step 5.3 manifest is missing kc_evidence_candidates_recalibrated_jsonl: {manifest_spec.display()}"
                    )
                candidate_spec = resolve_related_input_spec(raw_candidates, repo_root=repo_root, base_spec=manifest_spec)
                ensure_reference_allowed(candidate_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)

        if candidate_spec is None:
            if fail_if_no_candidate_source:
                raise RuntimeError(
                    "No candidate-bank input source could be resolved. Provide either legacy Step 5.3 inputs "
                    "(--step5-3-set-manifest or --step5-3-candidates-jsonl) or clean-slate inputs "
                    "(--registry-jsonl and --source-overlay-jsonl)."
                )
            return {"ok": False, "reason": "no_candidate_source"}

        if not input_spec_exists(candidate_spec):
            raise FileNotFoundError(f"Step 5.3 candidates JSONL not found: {candidate_spec.display()}")

        source_manifest_identity = manifest_spec.display() if manifest_spec is not None else candidate_spec.display()
        step5_rows = read_jsonl_from_spec(candidate_spec)
        step5_input_seed_field_detection = _enforce_seed_bearing_input_policy(
            step5_rows,
            input_label=f"Step 5.3 candidate input {candidate_spec.display()}",
            allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
        )
        resolved_registry_path = resolve_seedless_kc_registry_path(repo_root=repo_root)
        registry_jsonl = _stringify_path(resolved_registry_path)
        registry_rows, legacy_registry_seed_field_detection = load_registry_rows_if_available(
            parse_input_spec(registry_jsonl, repo_root=repo_root),
            allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
        )
        kc_context_lookup = build_kc_context_lookup(registry_rows)
        selected_kc_context_rows = _selected_kc_context_rows(
            step5_rows,
            exact_kc_ids=[str(kc_id) for kc_id in exact_kc_ids or []] or None,
            limit_kcs=limit_kcs,
            kc_context_lookup=kc_context_lookup,
        )

    profile_guidance_lookup, profile_source_jsonl = _load_profile_guidance_from_spec(
        profile_jsonl_spec=profile_jsonl_spec,
        manifest_spec=manifest_spec,
        repo_root=repo_root,
        allow_reference_artifact_inputs=allow_reference_artifact_inputs,
        exact_kc_ids=[str(kc_id) for kc_id in exact_kc_ids or []] or None,
    )
    profile_guided_selected_kc_context_rows = _apply_profile_guidance_to_context_rows(
        selected_kc_context_rows,
        profile_guidance_lookup,
    )
    profile_guidance_stats = _profile_guidance_stats(
        guidance_lookup=profile_guidance_lookup,
        selected_rows=selected_kc_context_rows,
        profile_source_jsonl=profile_source_jsonl,
    )
    profile_guidance_controls_by_kc = _profile_guidance_controls_by_kc(
        profile_guidance_lookup,
        selected_kc_context_rows,
    )

    paths = _materialize_run_paths(output_root=output_root, set_manifest_root=set_manifest_root, run_id=run_id)
    chosen_run_id = str(paths["run_id"])
    processed_dir = paths["processed_dir"]
    set_manifest_path = paths["set_manifest_path"]
    processed_dir.mkdir(parents=True, exist_ok=False)
    set_manifest_path.parent.mkdir(parents=True, exist_ok=True)

    row_source_surface = SOURCE_SURFACE_STEP53_NESTED
    direct_overlay_seed_field_detection: Dict[str, Any] = {"total": 0, "by_key": {}}
    if input_mode == INPUT_MODE_CLEAN_SLATE:
        rows, stats, row_source_surface = _build_clean_slate_candidate_rows(
            run_id=chosen_run_id,
            registry_jsonl=registry_jsonl,
            source_overlay_jsonl=source_overlay_jsonl,
            sentence_rows=sentence_rows,
            selected_kc_context_rows=profile_guided_selected_kc_context_rows,
            registry_kc_context_lookup=kc_context_lookup,
            profile_guidance_lookup=profile_guidance_lookup,
            existing_candidate_rows=[],
            source_surface_fallback_cfg=source_surface_fallback_cfg,
            direct_overlay_supplement_cfg=direct_overlay_supplement_cfg,
            seed_field_detection_in_registry=clean_slate_seed_field_detection,
            allow_reference_artifact_inputs=allow_reference_artifact_inputs,
            allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
            repo_root=repo_root,
        )
    else:
        rows, stats, _ = flatten_step5_3_nested_evidence_rows(
            step5_rows,
            run_id=chosen_run_id,
            source_manifest=source_manifest_identity,
            source_jsonl=candidate_spec.display(),
            exact_kc_ids=[str(kc_id) for kc_id in exact_kc_ids or []] or None,
            limit_kcs=limit_kcs,
            kc_context_lookup=kc_context_lookup,
            preserve_raw_support_profile=preserve_raw_support_profile,
            preserve_raw_alignment_breakdown=preserve_raw_alignment_breakdown,
        )
        fallback_cfg = fallback_config_from_mapping(source_surface_fallback_cfg)
        fallback_stats: Dict[str, Any] = {
            "enabled": bool(fallback_cfg.enabled),
            "source_surface": SOURCE_SURFACE_FALLBACK,
            "candidate_rows_added": 0,
        }
        if fallback_cfg.enabled:
            sentence_spec, sentence_manifest_identity, resolved_from = _resolve_sentence_corpus_input(
                manifest_spec=manifest_spec,
                manifest_obj=manifest_obj,
                repo_root=repo_root,
                allow_reference_artifact_inputs=allow_reference_artifact_inputs,
            )
            fallback_stats.update(
                {
                    "resolved_from": resolved_from,
                    "sentence_source_manifest": sentence_manifest_identity,
                    "sentence_source_jsonl": sentence_spec.display() if sentence_spec is not None else "",
                }
            )
            if sentence_spec is None or not input_spec_exists(sentence_spec):
                fallback_stats["missing_input"] = True
            else:
                sentence_rows = read_jsonl_from_spec(sentence_spec)
                fallback_result = build_source_surface_fallback_candidates(
                    sentence_rows,
                    selected_kc_contexts=profile_guided_selected_kc_context_rows,
                    registry_kc_contexts=list(kc_context_lookup.values()),
                    existing_candidate_rows=rows,
                    config=fallback_cfg,
                    sentence_source_manifest=sentence_manifest_identity or sentence_spec.display(),
                    sentence_source_jsonl=sentence_spec.display(),
                )
                fallback_rows = [
                    _candidate_bank_row_from_fallback_payload(
                        payload,
                        run_id=chosen_run_id,
                        source_manifest=sentence_manifest_identity or sentence_spec.display(),
                    )
                    for payload in fallback_result.get("rows") or []
                    if isinstance(payload, Mapping)
                ]
                rows.extend(fallback_rows)
                fallback_stats.update(dict(fallback_result.get("stats") or {}))
                counts = dict(stats.get("candidate_count_by_kc") or {})
                fallback_counts = dict(fallback_stats.get("candidate_count_by_kc") or {})
                for kc_id, count in fallback_counts.items():
                    counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(count or 0)
                stats["candidate_count_by_kc"] = counts
                source_surface_breakdown = dict(stats.get("source_surface_breakdown") or {})
                if fallback_rows:
                    source_surface_breakdown[SOURCE_SURFACE_FALLBACK] = len(fallback_rows)
                stats["source_surface_breakdown"] = source_surface_breakdown
                stats["total_candidate_rows_emitted"] = len(rows)
                stats["kcs_with_candidates"] = sum(1 for count in counts.values() if int(count or 0) > 0)
                stats["kcs_without_candidates"] = max(
                    0,
                    int(stats["total_kc_rows_seen"]) - int(stats["kcs_with_candidates"]),
                )
                stats["missing_provenance_counts"] = _missing_value_counts(rows)
        stats["source_surface_fallback"] = fallback_stats
        supplement_rows, supplement_manifest, direct_overlay_seed_field_detection, supplement_cfg = _load_direct_overlay_supplement_rows(
            cfg=direct_overlay_supplement_cfg,
            repo_root=repo_root,
            allow_reference_artifact_inputs=allow_reference_artifact_inputs,
            allow_seed_bearing_input_for_diagnostic=allow_seed_bearing_input_for_diagnostic,
        )
        generated_supplement_stats: Dict[str, Any] = {"enabled": False, "source_surface": SOURCE_OVERLAY_TARGET_SUPPLEMENT}
        if bool(supplement_cfg.get("enabled")) and bool(supplement_cfg.get("generate_from_source_overlay")):
            configured_overlay_jsonl = _as_text(supplement_cfg.get("source_overlay_jsonl"))
            generated_sentence_rows: List[Dict[str, Any]] = []
            generated_sentence_manifest = ""
            if configured_overlay_jsonl:
                source_overlay_spec = parse_input_spec(configured_overlay_jsonl, repo_root=repo_root)
                ensure_reference_allowed(source_overlay_spec, allow_reference_artifact_inputs=allow_reference_artifact_inputs)
                if not input_spec_exists(source_overlay_spec):
                    raise FileNotFoundError(f"Source overlay target supplement JSONL not found: {source_overlay_spec.display()}")
                generated_sentence_rows = read_jsonl_from_spec(source_overlay_spec)
                generated_sentence_manifest = source_overlay_spec.display()
            elif sentence_rows:
                generated_sentence_rows = sentence_rows
                generated_sentence_manifest = _as_text(fallback_stats.get("sentence_source_jsonl") or fallback_stats.get("sentence_source_manifest"))
            else:
                sentence_spec, sentence_manifest_identity, _resolved_from = _resolve_sentence_corpus_input(
                    manifest_spec=manifest_spec,
                    manifest_obj=manifest_obj,
                    repo_root=repo_root,
                    allow_reference_artifact_inputs=allow_reference_artifact_inputs,
                )
                if sentence_spec is not None and input_spec_exists(sentence_spec):
                    generated_sentence_rows = read_jsonl_from_spec(sentence_spec)
                    generated_sentence_manifest = sentence_spec.display()
                    if sentence_manifest_identity:
                        generated_sentence_manifest = sentence_manifest_identity
            generated_supplement_rows, generated_supplement_stats = _build_source_overlay_target_supplement_rows(
                sentence_rows=generated_sentence_rows,
                selected_kc_context_rows=profile_guided_selected_kc_context_rows,
                guidance_lookup=profile_guidance_lookup,
                cfg=supplement_cfg,
            )
            if generated_supplement_rows:
                supplement_rows = [*supplement_rows, *generated_supplement_rows]
                if not supplement_manifest:
                    supplement_manifest = generated_sentence_manifest
            generated_supplement_stats["source_overlay_jsonl"] = generated_sentence_manifest
        direct_overlay_rows, direct_overlay_stats = _build_direct_overlay_supplement_candidates(
            run_id=chosen_run_id,
            supplement_rows=supplement_rows,
            supplement_manifest=supplement_manifest,
            selected_kc_context_rows=profile_guided_selected_kc_context_rows,
            guidance_lookup=profile_guidance_lookup,
            existing_rows=rows,
            cfg=supplement_cfg,
        )
        if direct_overlay_rows:
            rows.extend(direct_overlay_rows)
            counts = dict(stats.get("candidate_count_by_kc") or {})
            for kc_id, supplement_count in dict(direct_overlay_stats.get("candidate_count_by_kc") or {}).items():
                counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(supplement_count or 0)
            stats["candidate_count_by_kc"] = counts
            stats["total_candidate_rows_emitted"] = len(rows)
            stats["kcs_with_candidates"] = sum(1 for count in counts.values() if int(count or 0) > 0)
            stats["kcs_without_candidates"] = max(
                0,
                int(stats["total_kc_rows_seen"]) - int(stats["kcs_with_candidates"]),
            )
            stats["missing_provenance_counts"] = _missing_value_counts(rows)
        stats["direct_overlay_supplement"] = direct_overlay_stats
        stats["source_overlay_target_supplement"] = generated_supplement_stats
        profile_provenance_rows, profile_provenance_stats = _build_profile_provenance_rehydration_candidates(
            run_id=chosen_run_id,
            source_overlay_jsonl=fallback_stats.get("sentence_source_jsonl") or fallback_stats.get("sentence_source_manifest") or "",
            sentence_rows=sentence_rows,
            selected_kc_context_rows=profile_guided_selected_kc_context_rows,
            guidance_lookup=profile_guidance_lookup,
            existing_rows=rows,
        )
        if profile_provenance_rows:
            rows.extend(profile_provenance_rows)
            counts = dict(stats.get("candidate_count_by_kc") or {})
            for kc_id, profile_count in dict(profile_provenance_stats.get("profile_provenance_rehydration_count_by_kc") or {}).items():
                counts[str(kc_id)] = int(counts.get(str(kc_id), 0)) + int(profile_count or 0)
            stats["candidate_count_by_kc"] = counts
            stats["total_candidate_rows_emitted"] = len(rows)
            stats["kcs_with_candidates"] = sum(1 for count in counts.values() if int(count or 0) > 0)
            stats["kcs_without_candidates"] = max(
                0,
                int(stats["total_kc_rows_seen"]) - int(stats["kcs_with_candidates"]),
            )
            stats["missing_provenance_counts"] = _missing_value_counts(rows)
        stats["source_surface_breakdown"] = _source_surface_breakdown(rows)
        stats["profile_provenance_rehydration"] = profile_provenance_stats
        stats["profile_provenance_rehydration_rows"] = int(profile_provenance_stats.get("profile_provenance_rehydration_rows") or 0)
        stats["profile_provenance_rehydration_count_by_kc"] = dict(
            profile_provenance_stats.get("profile_provenance_rehydration_count_by_kc") or {}
        )
        stats["profile_provenance_missing_source_ids_by_kc"] = dict(
            profile_provenance_stats.get("profile_provenance_missing_source_ids_by_kc") or {}
        )
    _annotate_candidate_rows_with_profile_guidance(rows, profile_guidance_lookup)
    _annotate_candidate_rows_with_retrieval_policy(rows, profile_guidance_lookup)
    retrieval_policy_controls_by_kc = _retrieval_policy_controls_by_kc(profile_guided_selected_kc_context_rows)
    stats["input_mode"] = input_mode
    if input_mode == INPUT_MODE_CLEAN_SLATE:
        stats["registry_jsonl"] = registry_jsonl
        stats["source_overlay_jsonl"] = source_overlay_jsonl
    else:
        stats["registry_jsonl"] = registry_jsonl
    stats["allow_seed_bearing_input_for_diagnostic"] = bool(allow_seed_bearing_input_for_diagnostic)
    if input_mode != INPUT_MODE_CLEAN_SLATE:
        stats["seed_field_detection"] = {
            "step5_3_candidate_input": {
                "total": int(step5_input_seed_field_detection.get("total") or 0),
                "by_key": dict(step5_input_seed_field_detection.get("by_key") or {}),
            },
            "registry_input": {
                "total": int(legacy_registry_seed_field_detection.get("total") or 0),
                "by_key": dict(legacy_registry_seed_field_detection.get("by_key") or {}),
            },
            "direct_overlay_supplement_input": {
                "total": int(direct_overlay_seed_field_detection.get("total") or 0),
                "by_key": dict(direct_overlay_seed_field_detection.get("by_key") or {}),
            },
        }
        stats["seed_fields_detected_in_input"] = (
            int(step5_input_seed_field_detection.get("total") or 0)
            + int(legacy_registry_seed_field_detection.get("total") or 0)
            + int(direct_overlay_seed_field_detection.get("total") or 0)
        )
    stats["step5p_profile_guidance"] = profile_guidance_stats
    stats["retrieval_policy"] = {
        "policy_plan_count": len(retrieval_policy_controls_by_kc),
        "authority_contract": AUTHORITY_CONTRACT,
        "knowledge_unit_type_breakdown": dict(Counter(
            str((plan or {}).get("knowledge_unit_type") or "")
            for plan in retrieval_policy_controls_by_kc.values()
        )),
    }
    schema_snapshot = _schema_snapshot(rows, run_id=chosen_run_id, source_manifest=source_manifest_identity)

    candidate_bank_jsonl = processed_dir / "candidate_bank.jsonl"
    candidate_bank_stats_json = processed_dir / "candidate_bank_stats.json"
    candidate_bank_schema_snapshot_json = processed_dir / "candidate_bank_schema_snapshot.json"
    profile_guidance_controls_json = processed_dir / "profile_guidance_controls.json"
    retrieval_policy_plans_json = processed_dir / "retrieval_policy_plans.json"
    candidate_bank_manifest_json = processed_dir / "candidate_bank_manifest.json"

    write_jsonl(candidate_bank_jsonl, rows)
    write_json(candidate_bank_stats_json, stats)
    write_json(candidate_bank_schema_snapshot_json, schema_snapshot)
    write_json(profile_guidance_controls_json, profile_guidance_controls_by_kc)
    write_json(retrieval_policy_plans_json, retrieval_policy_controls_by_kc)

    candidate_bank_manifest = {
        "run_id": chosen_run_id,
        "candidate_bank_version": CANDIDATE_BANK_CONTRACT_VERSION,
        "created_at": now_utc_iso(),
        "source_surface": row_source_surface,
        "inputs": {
            "mode": input_mode,
            "step5_3_set_manifest": manifest_spec.display() if manifest_spec is not None else "",
            "step5_3_candidates_jsonl": candidate_spec.display() if candidate_spec is not None else "",
            "registry_jsonl": registry_jsonl,
            "source_overlay_jsonl": source_overlay_jsonl,
            "config_path": config_path,
            "exact_kc_ids": [str(kc_id) for kc_id in exact_kc_ids or []],
            "limit_kcs": limit_kcs,
            "profile_jsonl": profile_source_jsonl,
            "source_surface_fallback": dict(stats.get("source_surface_fallback") or {}),
            "direct_overlay_supplement": dict(stats.get("direct_overlay_supplement") or {}),
            "allow_seed_bearing_input_for_diagnostic": bool(allow_seed_bearing_input_for_diagnostic),
            "seed_field_detection": dict(stats.get("seed_field_detection") or {}),
        },
        "artifacts": {
            "candidate_bank_jsonl": _stringify_path(candidate_bank_jsonl),
            "candidate_bank_stats_json": _stringify_path(candidate_bank_stats_json),
            "candidate_bank_schema_snapshot_json": _stringify_path(candidate_bank_schema_snapshot_json),
            "profile_guidance_controls_json": _stringify_path(profile_guidance_controls_json),
            "retrieval_policy_plans_json": _stringify_path(retrieval_policy_plans_json),
        },
        "stats": {
            "total_kc_rows_seen": stats["total_kc_rows_seen"],
            "total_candidate_rows_emitted": stats["total_candidate_rows_emitted"],
            "kcs_with_candidates": stats["kcs_with_candidates"],
            "kcs_without_candidates": stats["kcs_without_candidates"],
            "source_surface_breakdown": dict(stats.get("source_surface_breakdown") or {}),
            "source_surface_fallback": dict(stats.get("source_surface_fallback") or {}),
            "direct_overlay_supplement": dict(stats.get("direct_overlay_supplement") or {}),
            "step5p_profile_guidance": dict(stats.get("step5p_profile_guidance") or {}),
        },
        "compatibility": {
            "step6_6_ready": False,
            "step6_7_contract_changed": False,
        },
        "environment": {
            "env_snapshot": env_snapshot(),
            "python_version": try_cmd_version(["python", "--version"]),
        },
    }
    write_json(candidate_bank_manifest_json, candidate_bank_manifest)

    set_manifest = {
        "run_id": chosen_run_id,
        "stage": "step5x_v3_candidate_bank",
        "created_at": now_utc_iso(),
        "inputs": {
            "mode": input_mode,
            "source_manifest": source_manifest_identity,
            "step5_3_set_manifest": manifest_spec.display() if manifest_spec is not None else "",
            "step5_3_candidates_jsonl": candidate_spec.display() if candidate_spec is not None else "",
            "registry_jsonl": registry_jsonl,
            "source_overlay_jsonl": source_overlay_jsonl,
            "config_path": config_path,
            "exact_kc_ids": [str(kc_id) for kc_id in exact_kc_ids or []],
            "limit_kcs": limit_kcs,
            "profile_jsonl": profile_source_jsonl,
            "source_surface_fallback": dict(stats.get("source_surface_fallback") or {}),
            "direct_overlay_supplement": dict(stats.get("direct_overlay_supplement") or {}),
            "allow_seed_bearing_input_for_diagnostic": bool(allow_seed_bearing_input_for_diagnostic),
            "seed_field_detection": dict(stats.get("seed_field_detection") or {}),
        },
        "artifacts": {
            "candidate_bank_jsonl": _stringify_path(candidate_bank_jsonl),
            "candidate_bank_stats_json": _stringify_path(candidate_bank_stats_json),
            "candidate_bank_schema_snapshot_json": _stringify_path(candidate_bank_schema_snapshot_json),
            "profile_guidance_controls_json": _stringify_path(profile_guidance_controls_json),
            "retrieval_policy_plans_json": _stringify_path(retrieval_policy_plans_json),
            "candidate_bank_manifest_json": _stringify_path(candidate_bank_manifest_json),
        },
        "compatibility": {
            "step6_6_ready": False,
            "step6_7_contract_changed": False,
        },
    }
    write_json(set_manifest_path, set_manifest)

    output_manifest_path = processed_dir / "output_manifest.json"
    write_json(output_manifest_path, build_output_manifest(processed_dir))

    return {
        "run_id": chosen_run_id,
        "processed_dir": _stringify_path(processed_dir),
        "set_manifest": _stringify_path(set_manifest_path),
        "candidate_bank_jsonl": _stringify_path(candidate_bank_jsonl),
        "candidate_bank_stats_json": _stringify_path(candidate_bank_stats_json),
        "candidate_bank_schema_snapshot_json": _stringify_path(candidate_bank_schema_snapshot_json),
        "retrieval_policy_plans_json": _stringify_path(retrieval_policy_plans_json),
        "candidate_bank_manifest_json": _stringify_path(candidate_bank_manifest_json),
        "total_candidate_rows_emitted": stats["total_candidate_rows_emitted"],
    }


__all__ = [
    "CANDIDATE_BANK_CONTRACT_VERSION",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_SET_MANIFEST_ROOT",
    "FORBIDDEN_SEED_FIELDS",
    "REQUIRED_ROW_KEYS",
    "SOURCE_SURFACE_STEP53_NESTED",
    "SOURCE_SURFACE_FALLBACK",
    "SOURCE_DIRECT_OVERLAY_SUPPLEMENT",
    "SOURCE_OVERLAY_TARGET_SUPPLEMENT",
    "build_candidate_id",
    "build_kc_context_lookup",
    "flatten_step5_3_nested_evidence_rows",
    "input_spec_exists",
    "load_registry_rows_if_available",
    "parse_input_spec",
    "read_json_from_spec",
    "read_jsonl_from_spec",
    "resolve_related_input_spec",
    "run_candidate_bank_stage",
    "select_source_rows",
    "strip_forbidden_seed_fields",
]
