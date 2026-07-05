from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_output_manifest, env_snapshot, pip_freeze, try_cmd_version
from kc_l.retrieval_gate import (
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
    tokenize,
    unique_preserve_order,
)
from kc_l.retrieval_gate.role_scoring import analyze_quote_role, analyze_support_readiness
from kc_l.retrieval_rerank import bootstrap_reranker


DEFAULT_CONFIG = Path("steps/step_05_3_evidence_recalibrated/resources/step5_3.default.yaml")
ACTIVE_STEP5_3_POINTER = Path("data/processed/kc_evidence_recalibrated/_sets/ACTIVE_STEP5_3_EVIDENCE_SET.txt")
FLAG_FIELDS = [
    "is_meta",
    "is_nav_boilerplate",
    "is_author_affiliation",
    "is_transition_text",
    "is_heading_like",
    "is_formula_like",
    "is_definition_like",
    "is_procedure_like",
    "is_example_like",
]
LAYER_PRIORITY = {"mineru": 3.0, "docling": 2.0, "pymupdf": 1.0}
SUPPORT_ROLE_PRIORITY = {
    "definitional_anchor": 5,
    "context_completion_anchor": 4,
    "explanatory_anchor": 3,
    "formula_or_parameter_anchor": 2,
    "contamination_or_sibling_exclusion": 1,
    "other": 0,
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def jsonl_iter(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_yaml(path: Path) -> Dict[str, Any]:
    text = read_text(path)
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping at config root: {path}")
    return obj


def load_json(path: Path) -> Dict[str, Any]:
    obj = json.loads(read_text(path))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return obj


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve_repo_path(repo_root: Path, raw_path: Any, *, base_dir: Optional[Path] = None) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    root = base_dir if base_dir is not None else repo_root
    return (root / candidate).resolve()


def resolve_pointer(pointer_path: Path) -> Path:
    raw = read_text(pointer_path).strip()
    if not raw:
        raise RuntimeError(f"Pointer file is empty: {pointer_path}")
    return resolve_repo_path(REPO_ROOT, raw, base_dir=pointer_path.parent)


def rel_path(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    repo_resolved = repo_root.resolve()
    try:
        return resolved.relative_to(repo_resolved).as_posix()
    except ValueError:
        return resolved.as_posix()


def describe_path(path: Path, repo_root: Path) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"path": rel_path(path, repo_root), "exists": path.exists()}
    if path.exists() and path.is_file():
        stat = path.stat()
        payload["sha256"] = sha256_file(path)
        payload["stat"] = {
            "size_bytes": int(stat.st_size),
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    return payload


def build_repo_manifest(paths: Sequence[Path], repo_root: Path) -> List[Dict[str, Any]]:
    seen: set[Path] = set()
    manifest: List[Dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        manifest.append(describe_path(resolved, repo_root))
    manifest.sort(key=lambda item: item["path"])
    return manifest


def choose_run_paths(repo_root: Path, processed_root_rel: str, runs_dir_rel: str, sets_dir_rel: str) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (repo_root / processed_root_rel / run_id).resolve()
        audit_dir = (repo_root / runs_dir_rel / f"{run_id}_step5_3").resolve()
        set_path = (repo_root / sets_dir_rel / f"{run_id}_step5_3_kc_evidence_recalibrated_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step5_3": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def logistic(value: float) -> float:
    clamped = max(min(float(value), 12.0), -12.0)
    return 1.0 / (1.0 + math.exp(-clamped))


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return float(ordered[index])


def copy_config_snapshot(config_path: Path, audit_dir: Path) -> Path:
    target = audit_dir / "config_snapshot.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, target)
    return target


def infer_baseline_flags(text: str) -> Dict[str, bool]:
    lower = match_normalize(text)
    normalized = normalize_ws(text)
    short = len(normalized) <= 42
    return {
        "is_meta": False,
        "is_nav_boilerplate": False,
        "is_author_affiliation": False,
        "is_transition_text": False,
        "is_heading_like": short and ":" not in normalized and "." not in normalized,
        "is_formula_like": any(marker in lower for marker in ["=", "p(", "argmax", "sum", "sigma", "lambda", "->", "⇒", "≤", "≥"]),
        "is_definition_like": any(marker in lower for marker in [" is ", " are ", "defined", "refers to", "criterion", "measure", "probability", "algorithm"]),
        "is_procedure_like": any(marker in lower for marker in ["algorithm", "step", "if ", "then", "repeat", "until", "input", "output"]),
        "is_example_like": any(marker in lower for marker in ["example", "e.g.", "for instance"]),
    }


def same_page_key(page_index: Optional[int]) -> int:
    return int(page_index) if isinstance(page_index, int) and page_index >= 0 else -1


@dataclass
class AuditLog:
    path: Path

    def info(self, message: str) -> None:
        line = f"[{now_utc_iso()}] {message}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line)


@dataclass
class KCProfile:
    kc_id: str
    canonical_name: str
    aliases: List[str]
    kc_path: List[str]
    kc_group: str
    query_text: str
    query_tokens: set[str]
    name_terms: Mapping[str, Any]
    competitor_ids: List[str] = field(default_factory=list)
    competitor_tokens: List[str] = field(default_factory=list)


@dataclass
class SentenceCandidate:
    candidate_id: str
    source_type: str
    sentence_id: str
    doc_id: str
    block_id: str
    sent_idx: int
    char_start: int
    char_end: int
    page_index: Optional[int]
    layer: str
    bbox: Any
    reveal_group_id: Any
    patch_id: Any
    patch_heading: str
    page_heading_norm: str
    sentence_text: str
    source_block_text: str
    doc_group: str
    kc_group: str
    doc_mismatch: bool
    flags: Dict[str, bool]
    exact_name_phrase: bool
    exact_alias_phrase: bool
    canonical_name_token_hits: int
    alias_token_hits: int
    name_alias_hits: int
    context_keyword_hits: int
    heading_name_hits: int
    competitor_token_hits: int
    hard_suppressed: bool
    heuristic_score: float
    rerank_target_raw: float = 0.0
    rerank_target: float = 0.0
    rerank_best_other_raw: float = 0.0
    rerank_best_other: float = 0.0
    rerank_margin: float = 0.0
    rerank_best_other_kc_id: str = ""
    final_score: float = 0.0
    strong_same_topic: bool = False
    strong_structured_candidate: bool = False
    contamination_risk: str = "low"
    contamination_signals: List[str] = field(default_factory=list)
    role_hint: Dict[str, Any] = field(default_factory=dict)
    support_profile: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Mapping[str, Any]:
        return asdict(self)


def layer_priority(layer: str) -> float:
    return float(LAYER_PRIORITY.get(str(layer).lower(), 0.0))


def _default_support_profile_weights(cfg: Mapping[str, Any]) -> Dict[str, float]:
    source = dict((cfg.get("scoring") or {}).get("support_profile_weights") or {})
    return {
        "strong_definition_anchor": float(source.get("strong_definition_anchor", 3.0)),
        "usable_definition_anchor": float(source.get("usable_definition_anchor", 1.5)),
        "explanatory_anchor": float(source.get("explanatory_anchor", 1.0)),
        "context_completion_available": float(source.get("context_completion_available", 1.25)),
        "formula_auxiliary_penalty": float(source.get("formula_auxiliary_penalty", 2.0)),
        "contamination_exclusion_penalty": float(source.get("contamination_exclusion_penalty", 1.5)),
    }


def _support_profile(candidate: SentenceCandidate) -> Dict[str, Any]:
    return dict(candidate.support_profile or {})


def _preferred_support_role(candidate: SentenceCandidate) -> str:
    return str(_support_profile(candidate).get("preferred_support_role") or "other")


def _anchor_quality(candidate: SentenceCandidate) -> str:
    return str(_support_profile(candidate).get("anchor_quality") or "weak")


def _formula_auxiliary_only(candidate: SentenceCandidate) -> bool:
    return bool(_support_profile(candidate).get("formula_auxiliary_only", False))


def _needs_context_completion(candidate: SentenceCandidate) -> bool:
    return bool(_support_profile(candidate).get("needs_context_completion", False))


def _has_context_completion_source(candidate: SentenceCandidate) -> bool:
    return bool(_support_profile(candidate).get("has_context_completion_source", False))


def _clean_definition_anchor(candidate: SentenceCandidate) -> bool:
    return bool(
        _preferred_support_role(candidate) == "definitional_anchor"
        and _anchor_quality(candidate) in {"strong", "usable"}
        and not _formula_auxiliary_only(candidate)
        and candidate.contamination_risk != "high"
    )


def _explanatory_anchor(candidate: SentenceCandidate) -> bool:
    return bool(
        _preferred_support_role(candidate) in {"explanatory_anchor", "context_completion_anchor"}
        and not _formula_auxiliary_only(candidate)
        and candidate.contamination_risk != "high"
    )


def _context_completion_candidate(candidate: SentenceCandidate) -> bool:
    return bool(
        (_preferred_support_role(candidate) == "context_completion_anchor" or _needs_context_completion(candidate))
        and _has_context_completion_source(candidate)
        and candidate.contamination_risk != "high"
    )


def _formula_support_candidate(candidate: SentenceCandidate) -> bool:
    return bool(
        _preferred_support_role(candidate) == "formula_or_parameter_anchor"
        or _formula_auxiliary_only(candidate)
    )


def _support_relation_key(candidate: SentenceCandidate) -> Tuple[str, int, str]:
    return (
        str(candidate.doc_id),
        same_page_key(candidate.page_index),
        str(candidate.patch_id or candidate.block_id or candidate.sentence_id),
    )


def _related_to_selected_anchor(candidate: SentenceCandidate, selected: Sequence[SentenceCandidate]) -> bool:
    anchor_keys = {
        _support_relation_key(item)
        for item in selected
        if _clean_definition_anchor(item) or _explanatory_anchor(item)
    }
    if not anchor_keys:
        return False
    return _support_relation_key(candidate) in anchor_keys


def _support_pack_summary(candidates: Sequence[SentenceCandidate]) -> Dict[str, Any]:
    counts: Counter[str] = Counter()
    weak_reasons: List[str] = []
    context_needed = 0
    for candidate in candidates:
        profile = _support_profile(candidate)
        preferred_role = _preferred_support_role(candidate)
        if _clean_definition_anchor(candidate):
            counts["definition_anchor_candidates"] += 1
            if _anchor_quality(candidate) == "strong":
                counts["strong_definition_anchor_candidates"] += 1
        if _explanatory_anchor(candidate):
            counts["explanatory_anchor_candidates"] += 1
        if _context_completion_candidate(candidate):
            counts["context_completion_candidates"] += 1
        if _formula_support_candidate(candidate):
            counts["formula_auxiliary_candidates"] += 1
        if bool(profile.get("contamination_exclusion_hint", False)):
            counts["contamination_exclusion_candidates"] += 1
        if candidate.contamination_risk == "high":
            counts["high_contamination_candidates"] += 1
        if _needs_context_completion(candidate):
            context_needed += 1
        counts[f"preferred_role::{preferred_role}"] += 1

    if counts["definition_anchor_candidates"] == 0:
        weak_reasons.append("definition_anchor_missing")
    if counts["definition_anchor_candidates"] == 0 and counts["formula_auxiliary_candidates"] > 0:
        weak_reasons.append("formula_only_support_pack")
    if context_needed > 0 and counts["context_completion_candidates"] == 0:
        weak_reasons.append("context_completion_missing")
    if counts["high_contamination_candidates"] > 0 and counts["definition_anchor_candidates"] == 0:
        weak_reasons.append("contamination_prone_support_pack")

    return {
        "definition_pack_ready": bool(counts["definition_anchor_candidates"] > 0),
        "weak_reasons": unique_preserve_order(weak_reasons),
        **dict(sorted(counts.items())),
    }


def build_kc_profiles(registry_rows: Sequence[Mapping[str, Any]], competitor_pool_size: int) -> Dict[str, KCProfile]:
    profiles: Dict[str, KCProfile] = {}
    for row in registry_rows:
        kc_id = str(row["kc_id"])
        aliases = ensure_string_list(row.get("aliases"))
        canonical_name = normalize_ws(str(row.get("canonical_name") or ""))
        kc_path = [normalize_ws(str(part)) for part in (row.get("kc_path") or []) if normalize_ws(str(part))]
        hierarchy_context = kc_path
        if kc_path and match_normalize(kc_path[-1]) == match_normalize(canonical_name):
            hierarchy_context = kc_path[:-1]
        query_text = build_query_text(canonical_name, aliases, hierarchy_context)
        profiles[kc_id] = KCProfile(
            kc_id=kc_id,
            canonical_name=canonical_name,
            aliases=aliases,
            kc_path=kc_path,
            kc_group=derive_kc_group(kc_path),
            query_text=query_text,
            query_tokens=set(tokenize(match_normalize(query_text), min_len=3)),
            name_terms=build_name_context_terms(canonical_name, aliases, hierarchy_context, context_limit=24),
        )

    registry_lookup = {
        str(row["kc_id"]): {
            "canonical_name": str(row.get("canonical_name") or ""),
            "aliases": ensure_string_list(row.get("aliases")),
            "kc_path": [normalize_ws(str(part)) for part in (row.get("kc_path") or []) if normalize_ws(str(part))],
        }
        for row in registry_rows
    }
    for kc_id, profile in profiles.items():
        ranked: List[Tuple[int, int, int, str]] = []
        profile_name_tokens = set(profile.name_terms["canonical_tokens"]) | set(profile.name_terms["alias_tokens"])
        for other_id, other_profile in profiles.items():
            if other_id == kc_id:
                continue
            same_group = 1 if profile.kc_group == other_profile.kc_group else 0
            query_overlap = len(profile.query_tokens & other_profile.query_tokens)
            other_name_tokens = set(other_profile.name_terms["canonical_tokens"]) | set(other_profile.name_terms["alias_tokens"])
            name_overlap = len(profile_name_tokens & other_name_tokens)
            ranked.append((same_group, query_overlap, name_overlap, other_id))
        ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        competitor_ids = [item[3] for item in ranked[:competitor_pool_size]]
        profile.competitor_ids = competitor_ids
        profile.competitor_tokens = collect_competitor_tokens(registry_lookup, competitor_ids, min_token_len=4)
    return profiles


def score_sentence_candidate(
    row: Mapping[str, Any],
    profile: KCProfile,
    cfg: Mapping[str, Any],
    *,
    source_type: str,
) -> Optional[SentenceCandidate]:
    sentence_text = normalize_ws(str(row.get("sentence_text") or row.get("snippet") or ""))
    if not sentence_text:
        return None
    weights = cfg["scoring"]["weights"]
    penalties = cfg["scoring"]["penalties"]
    thresholds = cfg["scoring"]["thresholds"]
    sentence_norm = match_normalize(sentence_text)
    sentence_tokens = set(tokenize(sentence_norm, min_len=3))
    exact_name, exact_alias = exact_phrase_hits(
        sentence_norm,
        str(profile.name_terms["canonical_norm"]),
        list(profile.name_terms["alias_norms"]),
    )
    canonical_hits = len(set(profile.name_terms["canonical_tokens"]) & sentence_tokens)
    alias_hits = len(set(profile.name_terms["alias_tokens"]) & sentence_tokens)
    context_hits = sum(1 for token in profile.name_terms["context_keywords"] if token in sentence_tokens)
    patch_heading = normalize_ws(str(row.get("patch_heading") or row.get("page_heading_norm") or ""))
    heading_tokens = set(tokenize(match_normalize(patch_heading), min_len=3))
    target_name_tokens = set(profile.name_terms["canonical_tokens"]) | set(profile.name_terms["alias_tokens"])
    heading_hits = len(target_name_tokens & heading_tokens)
    doc_id = str(row.get("doc_id") or "")
    doc_group = derive_doc_group(doc_id)
    doc_mismatch = doc_group not in {"other", profile.kc_group} and profile.kc_group != "other"
    flags = {flag: bool(row.get(flag)) for flag in FLAG_FIELDS}
    competitor_hits = competitor_token_hit_count(sentence_text, profile.competitor_tokens)
    hard_suppressed = bool(
        flags["is_meta"]
        or flags["is_nav_boilerplate"]
        or flags["is_author_affiliation"]
        or flags["is_transition_text"]
    )
    role_proxy = SimpleNamespace(
        exact_name_phrase=exact_name,
        exact_alias_phrase=exact_alias,
        sentence_flags=flags,
        context_keyword_hits=context_hits,
        heading_name_hits=heading_hits,
        competitor_token_hits=competitor_hits,
        doc_mismatch=doc_mismatch,
        hard_suppressed=hard_suppressed,
    )
    role_hint = analyze_quote_role(
        quote=sentence_text,
        canonical_name=profile.canonical_name,
        aliases=profile.aliases,
        candidate=role_proxy,
    )
    support_profile = analyze_support_readiness(
        quote=sentence_text,
        source_block_text=str(row.get("source_block_text") or sentence_text),
        canonical_name=profile.canonical_name,
        aliases=profile.aliases,
        candidate=role_proxy,
    )

    score = 0.0
    score += float(weights["exact_name_phrase"]) if exact_name else 0.0
    score += float(weights["exact_alias_phrase"]) if exact_alias else 0.0
    score += canonical_hits * float(weights["canonical_token"])
    score += alias_hits * float(weights["alias_token"])
    score += context_hits * float(weights["context_keyword"])
    score += heading_hits * float(weights["heading_name_token"])
    score += float(weights["doc_group_match"]) if not doc_mismatch else 0.0
    score += float(weights["definition_like"]) if flags["is_definition_like"] else 0.0
    score += float(weights["formula_like"]) if flags["is_formula_like"] else 0.0
    score += float(weights["procedure_like"]) if flags["is_procedure_like"] else 0.0
    score += float(weights["example_like"]) if flags["is_example_like"] else 0.0
    score += float(weights["page_index_present"]) if isinstance(row.get("page_index"), int) else -float(penalties["missing_page_index"])
    score += float(weights["patch_id_present"]) if row.get("patch_id") not in (None, "") else -float(penalties["missing_patch_id"])
    score += float(weights["canonical_reveal_page"]) if bool(row.get("is_reveal_canonical")) else 0.0
    score -= float(penalties["noncanonical_reveal_page"]) if bool(row.get("is_noncanonical_reveal_page")) else 0.0
    score -= float(penalties["is_meta"]) if flags["is_meta"] else 0.0
    score -= float(penalties["is_nav_boilerplate"]) if flags["is_nav_boilerplate"] else 0.0
    score -= float(penalties["is_author_affiliation"]) if flags["is_author_affiliation"] else 0.0
    score -= float(penalties["is_transition_text"]) if flags["is_transition_text"] else 0.0
    score -= float(penalties["is_heading_like"]) if flags["is_heading_like"] else 0.0
    score -= float(penalties["doc_group_mismatch"]) if doc_mismatch else 0.0
    score -= competitor_hits * float(penalties["competitor_token_hit"])
    if len(sentence_text) < int(thresholds["very_short_sentence_chars"]):
        score -= float(penalties["very_short_sentence"])
    elif len(sentence_text) < int(thresholds["short_sentence_chars"]):
        score -= float(penalties["short_sentence"])
    if not (canonical_hits or alias_hits or context_hits or exact_name or exact_alias):
        score -= 2.0
    if str(support_profile.get("preferred_support_role") or "") == "definitional_anchor":
        score += 1.0
    elif str(support_profile.get("preferred_support_role") or "") == "context_completion_anchor":
        score += 0.5
    if bool(support_profile.get("formula_auxiliary_only", False)):
        score -= 1.0
    if bool(support_profile.get("contamination_exclusion_hint", False)):
        score -= 0.75

    return SentenceCandidate(
        candidate_id="",
        source_type=source_type,
        sentence_id=str(row.get("sentence_id") or row.get("baseline_id") or ""),
        doc_id=doc_id,
        block_id=str(row.get("block_id") or ""),
        sent_idx=int(row.get("sent_idx") or 0),
        char_start=int(row.get("char_start") or 0),
        char_end=int(row.get("char_end") or len(sentence_text)),
        page_index=int(row["page_index"]) if isinstance(row.get("page_index"), int) else None,
        layer=str(row.get("layer") or ""),
        bbox=row.get("bbox"),
        reveal_group_id=row.get("reveal_group_id"),
        patch_id=row.get("patch_id"),
        patch_heading=patch_heading,
        page_heading_norm=normalize_ws(str(row.get("page_heading_norm") or "")),
        sentence_text=sentence_text,
        source_block_text=str(row.get("source_block_text") or sentence_text),
        doc_group=doc_group,
        kc_group=profile.kc_group,
        doc_mismatch=doc_mismatch,
        flags=flags,
        exact_name_phrase=exact_name,
        exact_alias_phrase=exact_alias,
        canonical_name_token_hits=canonical_hits,
        alias_token_hits=alias_hits,
        name_alias_hits=canonical_hits + alias_hits,
        context_keyword_hits=context_hits,
        heading_name_hits=heading_hits,
        competitor_token_hits=competitor_hits,
        hard_suppressed=hard_suppressed,
        heuristic_score=float(score),
        role_hint=dict(role_hint),
        support_profile=dict(support_profile),
    )


def shortlist_candidates(sentences: Sequence[Mapping[str, Any]], profile: KCProfile, cfg: Mapping[str, Any]) -> List[SentenceCandidate]:
    candidates: List[SentenceCandidate] = []
    for row in sentences:
        candidate = score_sentence_candidate(row, profile, cfg, source_type="step4_5_sentence_overlay")
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            -item.heuristic_score,
            -int(item.exact_name_phrase),
            -int(item.exact_alias_phrase),
            -item.name_alias_hits,
            -item.context_keyword_hits,
            int(item.hard_suppressed),
            -layer_priority(item.layer),
            item.doc_id,
            same_page_key(item.page_index),
            item.block_id,
            item.sentence_id,
        )
    )
    limit = int(cfg["runtime"]["heuristic_shortlist_per_kc"])
    return candidates[:limit]


def apply_reranker_scores(
    profile: KCProfile,
    candidates: Sequence[SentenceCandidate],
    profiles: Mapping[str, KCProfile],
    scorer: Any,
) -> None:
    if not candidates:
        return
    pairs: List[Tuple[str, str]] = []
    refs: List[Tuple[str, str, str]] = []
    for candidate in candidates:
        pairs.append((profile.query_text, candidate.sentence_text))
        refs.append((candidate.sentence_id, "target", ""))
        for competitor_id in profile.competitor_ids:
            competitor = profiles[competitor_id]
            pairs.append((competitor.query_text, candidate.sentence_text))
            refs.append((candidate.sentence_id, "competitor", competitor_id))
    scores = scorer.score_pairs(pairs)
    by_id = {candidate.sentence_id: candidate for candidate in candidates}
    best_other: Dict[str, Tuple[float, str]] = defaultdict(lambda: (-9999.0, ""))
    for score, ref in zip(scores, refs):
        candidate = by_id[ref[0]]
        if ref[1] == "target":
            candidate.rerank_target_raw = float(score)
            candidate.rerank_target = logistic(float(score))
        else:
            best_score, best_id = best_other[ref[0]]
            if float(score) > best_score:
                best_other[ref[0]] = (float(score), str(ref[2]))
    for candidate in candidates:
        best_score, best_id = best_other.get(candidate.sentence_id, (0.0, ""))
        candidate.rerank_best_other_raw = float(best_score)
        candidate.rerank_best_other = logistic(float(best_score))
        candidate.rerank_margin = float(candidate.rerank_target - candidate.rerank_best_other)
        candidate.rerank_best_other_kc_id = str(best_id)


def finalize_candidate(candidate: SentenceCandidate, cfg: Mapping[str, Any]) -> None:
    weights = cfg["scoring"]["weights"]
    thresholds = cfg["scoring"]["thresholds"]
    support_weights = _default_support_profile_weights(cfg)
    candidate.final_score = (
        float(candidate.heuristic_score)
        + float(weights["rerank_target"]) * float(candidate.rerank_target)
        + float(weights["rerank_margin"]) * float(candidate.rerank_margin)
    )
    lexical_pass = bool(
        candidate.exact_name_phrase
        or candidate.exact_alias_phrase
        or candidate.name_alias_hits > 0
        or candidate.context_keyword_hits >= int(thresholds["strong_context_overlap_min"])
    )
    target_min = float(thresholds["rerank_target_min"])
    margin_min = float(thresholds["rerank_margin_min"])
    exact_phrase_target_min = float(thresholds["exact_phrase_rerank_target_min"])
    exact_phrase_margin_min = float(thresholds["exact_phrase_rerank_margin_min"])
    multi_token_margin_min = float(thresholds["multi_token_rerank_margin_min"])
    mismatch_target_min = float(thresholds["doc_mismatch_rerank_target_min"])
    mismatch_margin_min = float(thresholds["doc_mismatch_rerank_margin_min"])
    strong_exact_phrase = bool(
        candidate.exact_name_phrase
        or candidate.exact_alias_phrase
        or candidate.name_alias_hits >= 2
    )
    if candidate.doc_mismatch:
        candidate.strong_same_topic = bool(
            not candidate.hard_suppressed
            and lexical_pass
            and candidate.rerank_target >= mismatch_target_min
            and candidate.rerank_margin >= mismatch_margin_min
        )
    else:
        candidate.strong_same_topic = bool(
            not candidate.hard_suppressed
            and (
                (
                    strong_exact_phrase
                    and candidate.rerank_target >= exact_phrase_target_min
                    and candidate.rerank_margin >= exact_phrase_margin_min
                )
                or (
                    lexical_pass
                    and candidate.rerank_target >= target_min
                    and candidate.rerank_margin >= (
                        multi_token_margin_min if candidate.name_alias_hits >= 2 else margin_min
                    )
                )
            )
        )
    if candidate.competitor_token_hits >= 2 and candidate.name_alias_hits == 0 and not candidate.exact_name_phrase and not candidate.exact_alias_phrase:
        candidate.strong_same_topic = False

    preferred_role = _preferred_support_role(candidate)
    anchor_quality = _anchor_quality(candidate)
    if preferred_role == "definitional_anchor":
        if anchor_quality == "strong":
            candidate.final_score += float(support_weights["strong_definition_anchor"])
        elif anchor_quality == "usable":
            candidate.final_score += float(support_weights["usable_definition_anchor"])
    elif preferred_role in {"explanatory_anchor", "context_completion_anchor"}:
        candidate.final_score += float(support_weights["explanatory_anchor"])
    if _has_context_completion_source(candidate):
        candidate.final_score += float(support_weights["context_completion_available"])
    if _formula_auxiliary_only(candidate):
        candidate.final_score -= float(support_weights["formula_auxiliary_penalty"])
    if bool(_support_profile(candidate).get("contamination_exclusion_hint", False)):
        candidate.final_score -= float(support_weights["contamination_exclusion_penalty"])

    candidate.strong_structured_candidate = bool(
        candidate.strong_same_topic
        and (
            candidate.flags["is_definition_like"]
            or candidate.flags["is_formula_like"]
            or candidate.flags["is_procedure_like"]
        )
    )

    signals: List[str] = []
    if candidate.hard_suppressed:
        signals.append("suppressed")
    if candidate.doc_mismatch and candidate.rerank_margin < float(thresholds["strong_doc_mismatch_override_margin"]):
        signals.append("doc_mismatch")
    if candidate.rerank_margin < float(thresholds["high_risk_negative_margin"]):
        signals.append("competitor_beats_target")
    if candidate.competitor_token_hits >= 2 and candidate.name_alias_hits == 0 and not candidate.exact_name_phrase:
        signals.append("competitor_tokens_without_target")
    candidate.contamination_signals = signals
    if any(signal in {"suppressed", "competitor_beats_target"} for signal in signals):
        candidate.contamination_risk = "high"
    elif signals:
        candidate.contamination_risk = "medium"
    else:
        candidate.contamination_risk = "low"


def dedupe_key(candidate: SentenceCandidate) -> Tuple[str, str]:
    return (candidate.doc_id, match_normalize(candidate.sentence_text))


def candidate_sort_key(candidate: SentenceCandidate) -> Tuple[Any, ...]:
    return (
        int(candidate.strong_same_topic),
        SUPPORT_ROLE_PRIORITY.get(_preferred_support_role(candidate), 0),
        int(_anchor_quality(candidate) == "strong"),
        int(_anchor_quality(candidate) == "usable"),
        int(_has_context_completion_source(candidate)),
        -int(_formula_auxiliary_only(candidate)),
        int(candidate.strong_structured_candidate),
        float(candidate.final_score),
        float(candidate.rerank_target),
        float(candidate.rerank_margin),
        float(candidate.heuristic_score),
        int(not candidate.doc_mismatch),
        int(not candidate.hard_suppressed),
        layer_priority(candidate.layer),
        int(candidate.page_index is not None),
        candidate.doc_id,
        -same_page_key(candidate.page_index),
        candidate.block_id,
        candidate.sentence_id,
    )


def better_candidate(left: SentenceCandidate, right: SentenceCandidate) -> bool:
    return candidate_sort_key(left) > candidate_sort_key(right)


def dedupe_candidates(candidates: Sequence[SentenceCandidate]) -> List[SentenceCandidate]:
    best: Dict[Tuple[str, str], SentenceCandidate] = {}
    for candidate in candidates:
        key = dedupe_key(candidate)
        current = best.get(key)
        if current is None or better_candidate(candidate, current):
            best[key] = candidate
    out = list(best.values())
    out.sort(key=candidate_sort_key, reverse=True)
    for idx, candidate in enumerate(out):
        candidate.candidate_id = f"{candidate.doc_id}:{candidate.block_id}:{idx:03d}"
    return out


def select_candidates(candidates: Sequence[SentenceCandidate], cfg: Mapping[str, Any]) -> List[SentenceCandidate]:
    if not candidates:
        return []
    selection_cfg = cfg["selection"]
    max_candidates = int(selection_cfg["max_candidates_per_kc"])
    max_per_doc = int(selection_cfg["max_candidates_per_doc"])
    max_per_page = int(selection_cfg["max_candidates_per_page"])
    reserve_structured = int(selection_cfg["reserve_structured_candidates"])
    reserve_definition_anchors = int(selection_cfg.get("reserve_definition_anchor_candidates", 3))
    reserve_explanatory_anchors = int(selection_cfg.get("reserve_explanatory_anchor_candidates", 2))
    reserve_context_completion = int(selection_cfg.get("reserve_context_completion_candidates", 1))
    max_formula_auxiliary = int(selection_cfg.get("max_formula_auxiliary_candidates", 2))
    max_formula_without_definition = int(selection_cfg.get("max_formula_only_candidates_without_definition_anchor", 1))
    ordered = sorted(candidates, key=candidate_sort_key, reverse=True)
    selected: List[SentenceCandidate] = []
    selected_ids: set[str] = set()
    doc_counts: Counter[str] = Counter()
    page_counts: Counter[Tuple[str, int]] = Counter()
    formula_selected = 0

    def try_add(candidate: SentenceCandidate, *, relax_doc: bool = False, relax_page: bool = False) -> bool:
        nonlocal formula_selected
        if candidate.sentence_id in selected_ids:
            return False
        doc_key = candidate.doc_id
        page_key = (candidate.doc_id, same_page_key(candidate.page_index))
        if not relax_doc and doc_counts[doc_key] >= max_per_doc:
            return False
        if not relax_page and page_counts[page_key] >= max_per_page:
            return False
        if _formula_support_candidate(candidate):
            definition_anchor_selected = any(_clean_definition_anchor(item) for item in selected)
            if formula_selected >= max_formula_auxiliary:
                return False
            if not definition_anchor_selected and formula_selected >= max_formula_without_definition:
                return False
        selected.append(candidate)
        selected_ids.add(candidate.sentence_id)
        doc_counts[doc_key] += 1
        page_counts[page_key] += 1
        if _formula_support_candidate(candidate):
            formula_selected += 1
        return True

    for candidate in [item for item in ordered if item.strong_structured_candidate][:reserve_structured]:
        if len(selected) >= max_candidates:
            break
        try_add(candidate)

    definition_anchor_added = 0
    for candidate in ordered:
        if len(selected) >= max_candidates or definition_anchor_added >= reserve_definition_anchors:
            break
        if _clean_definition_anchor(candidate) and try_add(candidate):
            definition_anchor_added += 1

    explanatory_anchor_added = 0
    for candidate in ordered:
        if len(selected) >= max_candidates or explanatory_anchor_added >= reserve_explanatory_anchors:
            break
        if _explanatory_anchor(candidate) and try_add(candidate):
            explanatory_anchor_added += 1

    context_completion_added = 0
    for candidate in ordered:
        if len(selected) >= max_candidates or context_completion_added >= reserve_context_completion:
            break
        if _context_completion_candidate(candidate) and _related_to_selected_anchor(candidate, selected) and try_add(candidate):
            context_completion_added += 1

    for candidate in ordered:
        if len(selected) >= max_candidates:
            break
        try_add(candidate)

    if len(selected) < max_candidates:
        for candidate in ordered:
            if len(selected) >= max_candidates:
                break
            try_add(candidate, relax_page=True)

    if len(selected) < max_candidates:
        for candidate in ordered:
            if len(selected) >= max_candidates:
                break
            try_add(candidate, relax_doc=True, relax_page=True)

    selected.sort(key=candidate_sort_key, reverse=True)
    return selected[:max_candidates]


def public_candidate(candidate: SentenceCandidate, profile: KCProfile) -> Dict[str, Any]:
    return {
        "doc_id": candidate.doc_id,
        "block_id": candidate.block_id,
        "page_index": candidate.page_index,
        "bbox": candidate.bbox,
        "layer": candidate.layer,
        "reveal_group_id": candidate.reveal_group_id,
        "patch_id": candidate.patch_id,
        "patch_heading": candidate.patch_heading,
        "query_used": profile.query_text,
        "retrieval_scores": {
            "combined": float(candidate.rerank_target),
            "heuristic": float(candidate.heuristic_score),
            "rerank_target": float(candidate.rerank_target),
            "rerank_best_other": float(candidate.rerank_best_other),
            "rerank_margin": float(candidate.rerank_margin),
            "rerank_target_raw": float(candidate.rerank_target_raw),
            "rerank_best_other_raw": float(candidate.rerank_best_other_raw),
            "doc_group_match": not bool(candidate.doc_mismatch),
            "competitor_token_hits": int(candidate.competitor_token_hits),
            "source_type": candidate.source_type,
        },
        "alignment_score": float(candidate.final_score),
        "alignment_breakdown": {
            "name_or_alias_hit": bool(candidate.name_alias_hits or candidate.exact_name_phrase or candidate.exact_alias_phrase),
            "exact_name_phrase": bool(candidate.exact_name_phrase),
            "exact_alias_phrase": bool(candidate.exact_alias_phrase),
            "canonical_name_token_hits": int(candidate.canonical_name_token_hits),
            "alias_token_hits": int(candidate.alias_token_hits),
            "name_or_alias_token_hits": int(candidate.name_alias_hits),
            "context_keyword_hits": int(candidate.context_keyword_hits),
            "heading_name_hits": int(candidate.heading_name_hits),
            "competitor_token_hits": int(candidate.competitor_token_hits),
            "doc_group": candidate.doc_group,
            "kc_group": candidate.kc_group,
            "doc_mismatch": bool(candidate.doc_mismatch),
            "hard_suppressed": bool(candidate.hard_suppressed),
            "strong_same_topic": bool(candidate.strong_same_topic),
            "strong_structured_candidate": bool(candidate.strong_structured_candidate),
            "contamination_risk": candidate.contamination_risk,
            "contamination_signals": list(candidate.contamination_signals),
            "role_hint": dict(candidate.role_hint),
            "support_profile": dict(candidate.support_profile),
            "flags": dict(candidate.flags),
        },
        "support_profile": dict(candidate.support_profile),
        "snippet": candidate.sentence_text,
        "sentence_id": candidate.sentence_id,
        "sent_idx": int(candidate.sent_idx),
        "char_start": int(candidate.char_start),
        "char_end": int(candidate.char_end),
        "source_block_text": candidate.source_block_text,
    }


def evaluate_baseline_row(
    row: Mapping[str, Any],
    profile: KCProfile,
    profiles: Mapping[str, KCProfile],
    scorer: Any,
    cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    raw_candidates: List[SentenceCandidate] = []
    for idx, evidence in enumerate(row.get("evidence") or []):
        text = normalize_ws(str(evidence.get("snippet") or ""))
        if not text:
            continue
        pseudo = {
            "baseline_id": f"{profile.kc_id}:baseline:{idx:03d}",
            "doc_id": str(evidence.get("doc_id") or ""),
            "block_id": str(evidence.get("block_id") or ""),
            "sent_idx": idx,
            "char_start": 0,
            "char_end": len(text),
            "page_index": evidence.get("page_index"),
            "layer": evidence.get("layer"),
            "bbox": evidence.get("bbox"),
            "reveal_group_id": evidence.get("reveal_group_id"),
            "patch_id": evidence.get("patch_id"),
            "patch_heading": evidence.get("patch_heading"),
            "page_heading_norm": "",
            "sentence_text": text,
            "source_block_text": text,
            **infer_baseline_flags(text),
        }
        candidate = score_sentence_candidate(pseudo, profile, cfg, source_type="baseline_step5_2")
        if candidate is not None:
            raw_candidates.append(candidate)
    if not raw_candidates:
        return {
            "candidate_count": 0,
            "strong_same_topic_count": 0,
            "same_topic_fraction": 0.0,
            "structured_candidate_count": 0,
        }
    apply_reranker_scores(profile, raw_candidates, profiles, scorer)
    for candidate in raw_candidates:
        finalize_candidate(candidate, cfg)
    strong_count = sum(1 for candidate in raw_candidates if candidate.strong_same_topic)
    structured_count = sum(1 for candidate in raw_candidates if candidate.strong_structured_candidate)
    total = len(raw_candidates)
    return {
        "candidate_count": total,
        "strong_same_topic_count": int(strong_count),
        "same_topic_fraction": float(strong_count / total) if total else 0.0,
        "structured_candidate_count": int(structured_count),
    }


def compute_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    per_kc_metrics: List[Dict[str, Any]] = []
    candidate_counts: List[int] = []
    same_topic_fractions: List[float] = []
    structured_counts: List[int] = []
    support_pack_ready_count = 0
    weak_reason_counter: Counter[str] = Counter()
    top_candidate_suppressed = 0
    for row in rows:
        evidence = list(row.get("evidence") or [])
        support_pack_summary = dict(row.get("support_pack_summary") or {})
        candidate_count = len(evidence)
        same_topic_count = sum(1 for item in evidence if bool((item.get("alignment_breakdown") or {}).get("strong_same_topic")))
        structured_count = sum(1 for item in evidence if bool((item.get("alignment_breakdown") or {}).get("strong_structured_candidate")))
        suppressed_top = bool(evidence and (evidence[0].get("alignment_breakdown") or {}).get("hard_suppressed"))
        top_candidate_suppressed += int(suppressed_top)
        support_pack_ready_count += int(bool(support_pack_summary.get("definition_pack_ready", False)))
        for reason in support_pack_summary.get("weak_reasons") or []:
            weak_reason_counter[str(reason)] += 1
        fraction = float(same_topic_count / candidate_count) if candidate_count else 0.0
        candidate_counts.append(candidate_count)
        same_topic_fractions.append(fraction)
        structured_counts.append(structured_count)
        top = evidence[0] if evidence else None
        per_kc_metrics.append(
            {
                "kc_id": row["kc_id"],
                "canonical_name": row["canonical_name"],
                "candidate_count": int(candidate_count),
                "strong_same_topic_count": int(same_topic_count),
                "same_topic_fraction": float(fraction),
                "structured_candidate_count": int(structured_count),
                "top_doc_id": top["doc_id"] if top else "",
                "top_page_index": top["page_index"] if top else None,
                "top_layer": top["layer"] if top else "",
                "top_alignment_score": top["alignment_score"] if top else 0.0,
                "top_rerank_target": ((top.get("retrieval_scores") or {}).get("rerank_target")) if top else 0.0,
                "top_rerank_margin": ((top.get("retrieval_scores") or {}).get("rerank_margin")) if top else 0.0,
                "top_candidate_suppressed": bool(suppressed_top),
                "support_pack_ready": bool(support_pack_summary.get("definition_pack_ready", False)),
                "support_pack_weak_reasons": [str(item) for item in support_pack_summary.get("weak_reasons") or []],
            }
        )
    return {
        "per_kc_metrics": per_kc_metrics,
        "candidate_counts": candidate_counts,
        "same_topic_fractions": same_topic_fractions,
        "structured_counts": structured_counts,
        "support_pack_ready_count": int(support_pack_ready_count),
        "support_pack_weak_reason_breakdown": dict(sorted(weak_reason_counter.items())),
        "top_candidate_suppressed_count": int(top_candidate_suppressed),
        "kcs_with_at_least_8_same_topic_candidates": int(sum(1 for row in per_kc_metrics if int(row["strong_same_topic_count"]) >= 8)),
        "kcs_with_at_least_2_structured_candidates": int(sum(1 for value in structured_counts if value >= 2)),
        "kcs_with_at_least_2_strong_candidates": int(sum(1 for row in per_kc_metrics if int(row["strong_same_topic_count"]) >= 2)),
        "distribution_candidates_per_kc": {
            "min": min(candidate_counts) if candidate_counts else 0,
            "median": float(percentile(candidate_counts, 0.5)),
            "p10": float(percentile(candidate_counts, 0.1)),
            "p90": float(percentile(candidate_counts, 0.9)),
            "max": max(candidate_counts) if candidate_counts else 0,
        },
        "distribution_same_topic_fraction": {
            "min": min(same_topic_fractions) if same_topic_fractions else 0.0,
            "median": float(percentile(same_topic_fractions, 0.5)),
            "p10": float(percentile(same_topic_fractions, 0.1)),
            "p90": float(percentile(same_topic_fractions, 0.9)),
            "max": max(same_topic_fractions) if same_topic_fractions else 0.0,
        },
    }


def build_contamination_audit(
    *,
    rows_by_kc: Mapping[str, Mapping[str, Any]],
    subset_ids: Sequence[str],
    top_k: int,
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    high_risk_total = 0
    for kc_id in subset_ids:
        row = rows_by_kc.get(kc_id)
        if not row:
            continue
        evidence = list(row.get("evidence") or [])[:top_k]
        candidate_entries: List[Dict[str, Any]] = []
        for item in evidence:
            alignment = item.get("alignment_breakdown") or {}
            risk = str(alignment.get("contamination_risk") or "low")
            if risk == "high":
                high_risk_total += 1
            candidate_entries.append(
                {
                    "doc_id": item.get("doc_id"),
                    "page_index": item.get("page_index"),
                    "layer": item.get("layer"),
                    "snippet": item.get("snippet"),
                    "strong_same_topic": bool(alignment.get("strong_same_topic")),
                    "contamination_risk": risk,
                    "contamination_signals": list(alignment.get("contamination_signals") or []),
                }
            )
        entries.append(
            {
                "kc_id": kc_id,
                "canonical_name": row.get("canonical_name"),
                "top_candidates": candidate_entries,
            }
        )
    return {
        "subset_kc_ids": list(subset_ids),
        "top_k_per_kc": int(top_k),
        "high_risk_candidates": int(high_risk_total),
        "entries": entries,
    }


def build_closeout_report(
    *,
    run_id: str,
    created_utc: str,
    reranker_info: Mapping[str, Any],
    step4_5_set_id: str,
    step5_2_set_id: str,
    processed_dir: str,
    audit_dir: str,
    stats_payload: Mapping[str, Any],
    review_queue_count: int,
    acceptance_failures: Sequence[str],
    acceptance_passed: bool,
) -> str:
    audit = stats_payload["contamination_risk_audit"]
    lines: List[str] = [
        "STEP 5.3 CLOSEOUT REPORT",
        "",
        "1) Executive summary",
        f"- Run id: {run_id}",
        f"- Created UTC: {created_utc}",
        f"- Acceptance: {'PASS' if acceptance_passed else 'FAIL'}",
        f"- Median same-topic fraction: {stats_payload['distribution_same_topic_fraction']['median']:.4f}",
        f"- Baseline Step 5.2 median same-topic fraction: {stats_payload['baseline_step5_2_comparison']['median_same_topic_fraction']:.4f}",
        f"- Lift vs Step 5.2: {stats_payload['baseline_step5_2_comparison']['median_same_topic_fraction_lift']:.4f}",
        f"- Relative lift vs Step 5.2: {stats_payload['baseline_step5_2_comparison']['median_same_topic_fraction_relative_lift']:.4f}",
        "",
        "2) Run metadata",
        f"- Step 4.5 set id: {step4_5_set_id}",
        f"- Baseline Step 5.2 set id: {step5_2_set_id}",
        f"- Reranker model: {reranker_info.get('chosen_model')}",
        f"- Device: {reranker_info.get('device')}",
        f"- Processed dir: {processed_dir}",
        f"- Audit dir: {audit_dir}",
        "",
        "3) Acceptance table",
        f"- n_kcs_total: {stats_payload['n_kcs_total']}",
        f"- median_candidates_per_kc: {stats_payload['distribution_candidates_per_kc']['median']:.2f}",
        f"- median_same_topic_fraction: {stats_payload['distribution_same_topic_fraction']['median']:.4f}",
        f"- baseline_median_same_topic_fraction: {stats_payload['baseline_step5_2_comparison']['median_same_topic_fraction']:.4f}",
        f"- lift_vs_step5_2: {stats_payload['baseline_step5_2_comparison']['median_same_topic_fraction_lift']:.4f}",
        f"- relative_lift_vs_step5_2: {stats_payload['baseline_step5_2_comparison']['median_same_topic_fraction_relative_lift']:.4f}",
        f"- kcs_with_at_least_8_same_topic_candidates: {stats_payload['kcs_with_at_least_8_same_topic_candidates']}",
        f"- kcs_with_at_least_2_structured_candidates: {stats_payload['kcs_with_at_least_2_structured_candidates']}",
        f"- kcs_with_at_least_2_strong_candidates: {stats_payload['kcs_with_at_least_2_strong_candidates']}",
        f"- top_candidate_suppressed_count: {stats_payload['top_candidate_suppressed_count']}",
        f"- high_risk_audit_candidates: {audit['high_risk_candidates']}",
        f"- review_queue_count: {review_queue_count}",
        "",
        "4) Top failure reasons",
    ]
    if acceptance_failures:
        lines.extend(f"- {item}" for item in acceptance_failures[:10])
    else:
        lines.append("- none")
    lines.extend(["", "5) Recommendation"])
    if acceptance_passed:
        lines.append("- NOT_READY_FOR_FULL")
        lines.append("- Reason: Step 5.3 accepted, but the repeated Step 6.4.2 dry run has not been completed yet.")
    else:
        lines.append("- NOT_READY_FOR_FULL")
        lines.append("- Reason: Step 5.3 acceptance failed.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="STEP 5.3: evidence recalibration on top of Step 4.5 sentence overlay.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    repo_root = REPO_ROOT
    config_path = resolve_repo_path(repo_root, args.config)
    cfg = load_yaml(config_path)

    step4_5_pointer_path = resolve_repo_path(repo_root, cfg["inputs"]["step4_5_active_set_pointer"])
    step5_2_pointer_path = resolve_repo_path(repo_root, cfg["inputs"]["baseline_step5_2_active_set_pointer"])
    active_pointer_path = resolve_repo_path(repo_root, cfg["inputs"].get("active_step5_3_set_pointer") or ACTIVE_STEP5_3_POINTER)
    kc_registry_path = resolve_repo_path(repo_root, cfg["inputs"]["kc_registry_path"])

    run_paths = choose_run_paths(
        repo_root,
        str(cfg["outputs"]["processed_root"]),
        str(cfg["audit"]["runs_dir"]),
        str(cfg["outputs"]["sets_dir"]),
    )
    run_id = run_paths["run_id_step5_3"].name
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]

    audit_dir.mkdir(parents=True, exist_ok=True)
    logger = AuditLog(audit_dir / "run.log")
    timings: Dict[str, float] = {}
    started = time.perf_counter()
    logger.info(f"run_id_step5_3={run_id}")

    step4_5_set_path = resolve_pointer(step4_5_pointer_path)
    step5_2_set_path = resolve_pointer(step5_2_pointer_path)
    step4_5_set = load_json(step4_5_set_path)
    step5_2_set = load_json(step5_2_set_path)

    sentence_corpus_raw = (
        step4_5_set["artifacts"]["sentence_corpus_jsonl"]
        if "artifacts" in step4_5_set and "sentence_corpus_jsonl" in step4_5_set["artifacts"]
        else step4_5_set.get("sentence_corpus_path")
    )
    if not sentence_corpus_raw:
        raise KeyError("Missing sentence corpus path in Step 4.5 manifest.")
    sentence_corpus_path = resolve_repo_path(repo_root, sentence_corpus_raw)
    sentence_stats_raw = (
        step4_5_set["artifacts"]["sentence_stats_json"]
        if "artifacts" in step4_5_set and "sentence_stats_json" in step4_5_set["artifacts"]
        else step4_5_set.get("sentence_stats_path")
    )
    if not sentence_stats_raw:
        raise KeyError("Missing sentence stats path in Step 4.5 manifest.")
    sentence_stats_path = resolve_repo_path(repo_root, sentence_stats_raw)
    step5_2_candidates_path = resolve_repo_path(repo_root, step5_2_set["artifacts"]["kc_evidence_candidates_sharp_jsonl"])
    step5_2_stats_path = resolve_repo_path(repo_root, step5_2_set["artifacts"]["kc_evidence_sharp_stats_json"])

    input_paths = [
        config_path,
        kc_registry_path,
        step4_5_pointer_path,
        step4_5_set_path,
        sentence_corpus_path,
        sentence_stats_path,
        step5_2_pointer_path,
        step5_2_set_path,
        step5_2_candidates_path,
        step5_2_stats_path,
    ]

    copy_config_snapshot(config_path, audit_dir)
    write_json(
        audit_dir / "invocation.json",
        {
            "argv": list(sys.argv),
            "cwd": ".",
            "config_path": rel_path(config_path, repo_root),
            "run_id_step5_3": run_id,
        },
    )
    write_json(audit_dir / "environment_snapshot.json", env_snapshot())
    write_json(
        audit_dir / "tool_versions.json",
        {
            "python": try_cmd_version(["python", "--version"]),
            "git": try_cmd_version(["git", "--version"]),
            "ollama": try_cmd_version(["ollama", "--version"]),
            "nvidia_smi": try_cmd_version(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]),
        },
    )
    write_json(audit_dir / "pip_freeze.json", pip_freeze())
    write_json(audit_dir / "input_manifest.json", build_repo_manifest(input_paths, repo_root))

    try:
        reranker_bootstrap, scorer = bootstrap_reranker(
            repo_root=repo_root,
            preferred_model=str(cfg["models"]["reranker"]["preferred"]),
            fallback_models=[str(item) for item in cfg["models"]["reranker"].get("fallback", [])],
            device=str(cfg["models"]["reranker"].get("device", "auto")),
            batch_size=int(cfg["models"]["reranker"].get("batch_size", 8)),
            smoke_query="Bayes theorem conditional probability",
            smoke_sentence="The probability of an event H given evidence E depends on the likelihood and the prior probability.",
        )
        write_json(audit_dir / "reranker_bootstrap.json", reranker_bootstrap.as_dict())
        logger.info(
            "Reranker bootstrap passed: "
            f"model={reranker_bootstrap.chosen_model} device={reranker_bootstrap.device} score={reranker_bootstrap.smoke_score:.6f}"
        )

        load_started = time.perf_counter()
        registry_rows = sorted(list(jsonl_iter(kc_registry_path)), key=lambda item: str(item["kc_id"]))
        if len(registry_rows) != int(cfg["acceptance"]["n_kcs_total"]):
            raise RuntimeError(f"Expected {int(cfg['acceptance']['n_kcs_total'])} registry rows, found {len(registry_rows)}")
        sentence_rows = list(jsonl_iter(sentence_corpus_path))
        baseline_rows = {str(row["kc_id"]): row for row in jsonl_iter(step5_2_candidates_path)}
        profiles = build_kc_profiles(registry_rows, int(cfg["runtime"]["competitor_pool_size"]))
        logger.info(f"Loaded registry rows={len(registry_rows)} sentence_rows={len(sentence_rows)} baseline_rows={len(baseline_rows)}")
        timings["load_inputs_seconds"] = round(time.perf_counter() - load_started, 3)

        retrieval_started = time.perf_counter()
        recalibrated_rows: List[Dict[str, Any]] = []
        review_rows: List[Dict[str, Any]] = []
        baseline_metrics_by_kc: Dict[str, Dict[str, Any]] = {}
        per_doc_contribution_counts: Counter[str] = Counter()
        review_threshold = int(cfg["runtime"]["review_queue_min_strong_candidates"])

        for registry_row in registry_rows:
            kc_id = str(registry_row["kc_id"])
            profile = profiles[kc_id]
            shortlist = shortlist_candidates(sentence_rows, profile, cfg)
            apply_reranker_scores(profile, shortlist, profiles, scorer)
            for candidate in shortlist:
                finalize_candidate(candidate, cfg)
            selected = select_candidates(dedupe_candidates(shortlist), cfg)
            public_rows = [public_candidate(candidate, profile) for candidate in selected]
            support_pack_summary = _support_pack_summary(selected)
            strong_count = sum(1 for candidate in selected if candidate.strong_same_topic)
            structured_count = sum(1 for candidate in selected if candidate.strong_structured_candidate)
            top_suppressed = bool(selected and selected[0].hard_suppressed)
            for item in public_rows:
                per_doc_contribution_counts[str(item["doc_id"])] += 1
            recalibrated_rows.append(
                {
                    "kc_id": kc_id,
                    "canonical_name": profile.canonical_name,
                    "aliases": profile.aliases,
                    "query_text": profile.query_text,
                    "support_pack_summary": support_pack_summary,
                    "evidence": public_rows,
                }
            )
            if strong_count < review_threshold or structured_count < 2 or top_suppressed or list(support_pack_summary.get("weak_reasons") or []):
                review_rows.append(
                    {
                        "kc_id": kc_id,
                        "canonical_name": profile.canonical_name,
                        "reasons": [item for item in unique_preserve_order(
                            [
                                f"strong_same_topic_candidates_lt_{review_threshold}" if strong_count < review_threshold else "",
                                "structured_candidates_lt_2" if structured_count < 2 else "",
                                "top_candidate_suppressed" if top_suppressed else "",
                                *[str(item) for item in support_pack_summary.get("weak_reasons") or []],
                            ]
                        ) if item],
                        "selected_candidate_count": len(public_rows),
                        "strong_same_topic_count": int(strong_count),
                        "structured_candidate_count": int(structured_count),
                        "support_pack_summary": support_pack_summary,
                        "top_examples": [
                            {
                                "doc_id": item["doc_id"],
                                "page_index": item["page_index"],
                                "layer": item["layer"],
                                "alignment_score": item["alignment_score"],
                                "rerank_target": (item.get("retrieval_scores") or {}).get("rerank_target"),
                                "rerank_margin": (item.get("retrieval_scores") or {}).get("rerank_margin"),
                                "snippet": item["snippet"],
                                "contamination_risk": (item.get("alignment_breakdown") or {}).get("contamination_risk"),
                            }
                            for item in public_rows[: int(cfg["runtime"]["review_examples_per_kc"])]
                        ],
                    }
                )

            baseline_metrics_by_kc[kc_id] = evaluate_baseline_row(
                baseline_rows.get(kc_id) or {"kc_id": kc_id, "evidence": []},
                profile,
                profiles,
                scorer,
                cfg,
            )
        timings["recalibration_seconds"] = round(time.perf_counter() - retrieval_started, 3)

        recalibrated_rows.sort(key=lambda item: item["kc_id"])
        review_rows.sort(key=lambda item: item["kc_id"])
        rows_by_kc = {str(row["kc_id"]): row for row in recalibrated_rows}

        candidates_path = (processed_dir / "kc_evidence_candidates_recalibrated.jsonl").resolve()
        stats_path = (processed_dir / "kc_evidence_recalibrated_stats.json").resolve()
        review_path = (processed_dir / "review_queue.jsonl").resolve()
        processed_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(candidates_path, recalibrated_rows)
        write_jsonl(review_path, review_rows)

        stats_core = compute_stats(recalibrated_rows)
        baseline_same_topic_fractions = [
            float(item["same_topic_fraction"])
            for _, item in sorted(baseline_metrics_by_kc.items())
        ]
        baseline_payload = {
            "median_same_topic_fraction": float(percentile(baseline_same_topic_fractions, 0.5)),
            "p10_same_topic_fraction": float(percentile(baseline_same_topic_fractions, 0.1)),
            "p90_same_topic_fraction": float(percentile(baseline_same_topic_fractions, 0.9)),
            "kcs_with_at_least_2_strong_candidates": int(
                sum(1 for item in baseline_metrics_by_kc.values() if int(item["strong_same_topic_count"]) >= 2)
            ),
        }
        baseline_payload["median_same_topic_fraction_lift"] = float(
            stats_core["distribution_same_topic_fraction"]["median"] - baseline_payload["median_same_topic_fraction"]
        )
        baseline_payload["median_same_topic_fraction_relative_lift"] = float(
            baseline_payload["median_same_topic_fraction_lift"] / baseline_payload["median_same_topic_fraction"]
        ) if baseline_payload["median_same_topic_fraction"] > 0 else 0.0

        contamination_audit = build_contamination_audit(
            rows_by_kc=rows_by_kc,
            subset_ids=[str(item) for item in cfg["runtime"].get("contamination_audit_subset", []) if str(item)],
            top_k=int(cfg["runtime"]["contamination_audit_top_k"]),
        )

        sample_rows = []
        for row in recalibrated_rows[: int(cfg["runtime"]["sample_kcs"])]:
            evidence = list(row.get("evidence") or [])
            same_topic_count = sum(1 for item in evidence if bool((item.get("alignment_breakdown") or {}).get("strong_same_topic")))
            sample_rows.append(
                {
                    "kc_id": row["kc_id"],
                    "candidate_count": len(evidence),
                    "strong_same_topic_count": int(same_topic_count),
                    "same_topic_fraction": float(same_topic_count / len(evidence)) if evidence else 0.0,
                    "top_doc_id": evidence[0]["doc_id"] if evidence else "",
                    "top_page_index": evidence[0]["page_index"] if evidence else None,
                    "top_layer": evidence[0]["layer"] if evidence else "",
                    "top_alignment_score": evidence[0]["alignment_score"] if evidence else 0.0,
                }
            )

        acceptance_failures: List[str] = []
        candidate_counts = list(stats_core["candidate_counts"])
        if len(recalibrated_rows) != int(cfg["acceptance"]["n_kcs_total"]):
            acceptance_failures.append(
                f"Expected n_kcs_total={int(cfg['acceptance']['n_kcs_total'])}, observed {len(recalibrated_rows)}"
            )
        if any(count > int(cfg["acceptance"]["max_candidates_per_kc"]) for count in candidate_counts):
            acceptance_failures.append(
                f"Observed candidate_count > {int(cfg['acceptance']['max_candidates_per_kc'])}"
            )
        abs_lift_ok = baseline_payload["median_same_topic_fraction_lift"] >= float(
            cfg["acceptance"]["min_median_same_topic_fraction_lift_vs_step5_2"]
        )
        rel_lift_ok = baseline_payload["median_same_topic_fraction_relative_lift"] >= float(
            cfg["acceptance"].get("min_median_same_topic_fraction_relative_lift_vs_step5_2", 0.0)
        )
        if not (abs_lift_ok or rel_lift_ok):
            acceptance_failures.append(
                "Median same-topic fraction lift did not meet absolute or relative materiality targets: "
                f"abs={baseline_payload['median_same_topic_fraction_lift']:.4f}, "
                f"rel={baseline_payload['median_same_topic_fraction_relative_lift']:.4f}"
            )
        if stats_core["kcs_with_at_least_2_strong_candidates"] < int(cfg["acceptance"]["min_kcs_with_2_strong_candidates"]):
            acceptance_failures.append(
                "KCs with at least 2 strong same-topic candidates "
                f"{stats_core['kcs_with_at_least_2_strong_candidates']} < "
                f"{int(cfg['acceptance']['min_kcs_with_2_strong_candidates'])}"
            )
        if stats_core["top_candidate_suppressed_count"] > int(cfg["acceptance"]["max_top_candidate_suppressed"]):
            acceptance_failures.append(
                "Top candidate suppressed count "
                f"{stats_core['top_candidate_suppressed_count']} > "
                f"{int(cfg['acceptance']['max_top_candidate_suppressed'])}"
            )
        if contamination_audit["high_risk_candidates"] > int(cfg["acceptance"]["max_high_risk_audit_candidates"]):
            acceptance_failures.append(
                "High-risk contamination audit candidates "
                f"{contamination_audit['high_risk_candidates']} > "
                f"{int(cfg['acceptance']['max_high_risk_audit_candidates'])}"
            )

        acceptance_passed = not acceptance_failures
        stats_payload = {
            "run_id_step5_3": run_id,
            "created_utc": now_utc_iso(),
            "n_kcs_total": len(recalibrated_rows),
            "distribution_candidates_per_kc": stats_core["distribution_candidates_per_kc"],
            "distribution_same_topic_fraction": stats_core["distribution_same_topic_fraction"],
            "kcs_with_at_least_8_same_topic_candidates": stats_core["kcs_with_at_least_8_same_topic_candidates"],
            "kcs_with_at_least_2_structured_candidates": stats_core["kcs_with_at_least_2_structured_candidates"],
            "kcs_with_at_least_2_strong_candidates": stats_core["kcs_with_at_least_2_strong_candidates"],
            "support_pack_ready_count": stats_core["support_pack_ready_count"],
            "support_pack_weak_reason_breakdown": stats_core["support_pack_weak_reason_breakdown"],
            "top_candidate_suppressed_count": stats_core["top_candidate_suppressed_count"],
            "review_queue_count": len(review_rows),
            "per_doc_contribution_counts": dict(sorted(per_doc_contribution_counts.items())),
            "per_kc_metrics": stats_core["per_kc_metrics"],
            "baseline_step5_2_comparison": baseline_payload,
            "contamination_risk_audit": contamination_audit,
            "diagnostics": {
                "sample_rows": sample_rows,
                "worst_10_kcs_by_same_topic_fraction": sorted(
                    stats_core["per_kc_metrics"],
                    key=lambda item: (item["same_topic_fraction"], item["strong_same_topic_count"], item["candidate_count"], item["kc_id"]),
                )[:10],
            },
            "acceptance": {
                "targets": dict(cfg["acceptance"]),
                "passed": acceptance_passed,
                "failures": acceptance_failures,
            },
        }
        write_json(stats_path, stats_payload)

        write_text(
            audit_dir / "STEP5_3_CLOSEOUT_REPORT.txt",
            build_closeout_report(
                run_id=run_id,
                created_utc=stats_payload["created_utc"],
                reranker_info=reranker_bootstrap.as_dict(),
                step4_5_set_id=str(step4_5_set.get("set_id") or step4_5_set_path.stem),
                step5_2_set_id=str(step5_2_set.get("set_id") or step5_2_set_path.stem),
                processed_dir=rel_path(processed_dir, repo_root),
                audit_dir=rel_path(audit_dir, repo_root),
                stats_payload=stats_payload,
                review_queue_count=len(review_rows),
                acceptance_failures=acceptance_failures,
                acceptance_passed=acceptance_passed,
            ),
        )

        timings["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_json(audit_dir / "timings.json", timings)

        summary_payload = {
            "run_id_step5_3": run_id,
            "status": "success" if acceptance_passed else "acceptance_failed",
            "created_utc": stats_payload["created_utc"],
            "n_kcs_total": len(recalibrated_rows),
            "median_same_topic_fraction": stats_core["distribution_same_topic_fraction"]["median"],
            "baseline_median_same_topic_fraction": baseline_payload["median_same_topic_fraction"],
            "median_same_topic_fraction_lift": baseline_payload["median_same_topic_fraction_lift"],
            "median_same_topic_fraction_relative_lift": baseline_payload["median_same_topic_fraction_relative_lift"],
            "kcs_with_at_least_2_strong_candidates": stats_core["kcs_with_at_least_2_strong_candidates"],
            "top_candidate_suppressed_count": stats_core["top_candidate_suppressed_count"],
            "high_risk_audit_candidates": contamination_audit["high_risk_candidates"],
            "review_queue_count": len(review_rows),
            "acceptance_passed": acceptance_passed,
            "acceptance_failures": acceptance_failures,
            "set_manifest": rel_path(set_path, repo_root) if acceptance_passed else None,
            "active_pointer": rel_path(active_pointer_path, repo_root) if acceptance_passed else None,
        }
        write_json(audit_dir / "summary.json", summary_payload)

        if acceptance_passed:
            set_payload = {
                "schema_version": "1.0",
                "kind": "step5_3_kc_evidence_recalibrated_set",
                "set_id": set_path.stem,
                "created_utc": stats_payload["created_utc"],
                "run_id_step5_3": run_id,
                "artifacts": {
                    "kc_evidence_candidates_recalibrated_jsonl": rel_path(candidates_path, repo_root),
                    "kc_evidence_recalibrated_stats_json": rel_path(stats_path, repo_root),
                    "review_queue_jsonl": rel_path(review_path, repo_root),
                },
                "upstream": {
                    "kc_registry_path": rel_path(kc_registry_path, repo_root),
                    "step4_5_active_set_pointer": rel_path(step4_5_pointer_path, repo_root),
                    "step4_5_active_set_target": rel_path(step4_5_set_path, repo_root),
                    "step4_5_sentence_corpus_jsonl": rel_path(sentence_corpus_path, repo_root),
                    "step4_5_sentence_stats_json": rel_path(sentence_stats_path, repo_root),
                    "baseline_step5_2_active_set_pointer": rel_path(step5_2_pointer_path, repo_root),
                    "baseline_step5_2_active_set_target": rel_path(step5_2_set_path, repo_root),
                    "baseline_step5_2_candidates_jsonl": rel_path(step5_2_candidates_path, repo_root),
                    "baseline_step5_2_stats_json": rel_path(step5_2_stats_path, repo_root),
                },
                "audit": {
                    "run_dir": rel_path(audit_dir, repo_root),
                    "input_manifest": rel_path((audit_dir / "input_manifest.json").resolve(), repo_root),
                    "output_manifest": rel_path((audit_dir / "output_manifest.json").resolve(), repo_root),
                    "summary": rel_path((audit_dir / "summary.json").resolve(), repo_root),
                },
            }
            write_json(set_path, set_payload)
            write_text(active_pointer_path, set_path.name + "\n")
            logger.info(f"Wrote Step 5.3 recalibrated evidence set: {rel_path(set_path, repo_root)}")
            logger.info(f"Updated ACTIVE pointer: {rel_path(active_pointer_path, repo_root)} -> {set_path.name}")

        output_manifest = {
            "processed_outputs": build_output_manifest(processed_dir),
            "audit_outputs": build_output_manifest(audit_dir),
        }
        if acceptance_passed:
            output_manifest["set_manifest"] = describe_path(set_path, repo_root)
            output_manifest["active_pointer"] = describe_path(active_pointer_path, repo_root)
        write_json(audit_dir / "output_manifest.json", output_manifest)

        print(f"n_kcs_total={len(recalibrated_rows)}")
        print(f"median_candidates_per_kc={stats_core['distribution_candidates_per_kc']['median']:.2f}")
        print(f"median_same_topic_fraction={stats_core['distribution_same_topic_fraction']['median']:.4f}")
        print(f"baseline_median_same_topic_fraction={baseline_payload['median_same_topic_fraction']:.4f}")
        print(f"median_same_topic_fraction_lift={baseline_payload['median_same_topic_fraction_lift']:.4f}")
        print(f"median_same_topic_fraction_relative_lift={baseline_payload['median_same_topic_fraction_relative_lift']:.4f}")
        print(f"kcs_with_at_least_2_strong_candidates={stats_core['kcs_with_at_least_2_strong_candidates']}")
        print(f"kcs_with_at_least_2_structured_candidates={stats_core['kcs_with_at_least_2_structured_candidates']}")
        print(f"top_candidate_suppressed_count={stats_core['top_candidate_suppressed_count']}")
        print(f"high_risk_audit_candidates={contamination_audit['high_risk_candidates']}")
        print(f"review_queue_count={len(review_rows)}")
        print(f"acceptance_passed={str(acceptance_passed).lower()}")
        if acceptance_failures:
            print("acceptance_failures:")
            for failure in acceptance_failures:
                print(f"- {failure}")
            print("worst_kcs_by_same_topic_fraction:")
            for item in stats_payload["diagnostics"]["worst_10_kcs_by_same_topic_fraction"]:
                print(
                    f"- {item['kc_id']} | count={item['candidate_count']} | strong={item['strong_same_topic_count']} | "
                    f"frac={item['same_topic_fraction']:.4f} | {item['canonical_name']}"
                )
        return 0 if acceptance_passed else 2
    except Exception as exc:
        write_json(
            audit_dir / "summary.json",
            {
                "run_id_step5_3": run_id,
                "status": "failed",
                "created_utc": now_utc_iso(),
                "error": repr(exc),
            },
        )
        write_json(
            audit_dir / "timings.json",
            {
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "status": "failed",
            },
        )
        logger.info(f"FAILED: {repr(exc)}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
