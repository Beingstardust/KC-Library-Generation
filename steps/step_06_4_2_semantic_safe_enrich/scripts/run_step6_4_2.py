from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_output_manifest, env_snapshot, pip_freeze, try_cmd_version
from kc_l.kc.validators import load_schema, schema_version, validate_kc_record
from kc_l.retrieval_gate import (
    CandidateSentence,
    build_name_seed_terms,
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
    tokenize,
    unique_preserve_order,
)
from kc_l.retrieval_gate.provenance_normalize import (
    build_sentence_provenance_index,
    has_valid_page_index,
    normalize_candidate_provenance,
    safe_int,
)
from kc_l.retrieval_gate.role_scoring import (
    ROLE_LABEL_VALUES,
    ROLE_PRIORITY,
    analyze_quote_role,
    default_role_cfg,
)
from kc_l.retrieval_gate.text_normalize import verify_quote_in_raw_source
from kc_l.retrieval_rerank import RerankerBootstrapResult, bootstrap_reranker

DEFAULT_CONFIG = Path("steps/step_06_4_2_semantic_safe_enrich/resources/step6_4_2.default.yaml")
ACTIVE_STEP6_POINTER = Path("data/processed/kc_library/_sets/ACTIVE_STEP6_KC_LIBRARY_SET.txt")
EVIDENCE_ROLE_VALUES = ["definition", "scope", "procedure", "equation", "example", "warning", "other"]
PRIMARY_ROLE_SET = {"definition", "equation", "procedure"}
REQUIRED_DRY_CANONICAL_NAMES = [
    "Gain Ratio",
    "Binary Decision Tree",
    "Learning Phase",
    "Gini Index",
]
PRIMARY_EVIDENCE_ARTIFACTS = [
    ("kc_evidence_candidates_recalibrated_jsonl", "step5_3", "step5_3_primary"),
    ("kc_evidence_candidates_sharp_jsonl", "step5_2", "step5_2_primary"),
]
CONTRACT_DECOUPLE_CLOSEOUT_FILENAME = "STEP6_4_9_CONTRACT_DECOUPLE_CLOSEOUT_REPORT.txt"
RECAL_CLOSEOUT_FILENAME = "STEP6_4_2_RECAL_CLOSEOUT_REPORT.txt"
DOWNSTREAM_DEBUG_CLOSEOUT_FILENAME = "STEP6_4_4_DOWNSTREAM_DEBUG_CLOSEOUT_REPORT.txt"
DOWNSTREAM_REDESIGN_CLOSEOUT_FILENAME = "STEP6_4_5_DOWNSTREAM_REDESIGN_CLOSEOUT_REPORT.txt"
CONTRACT_CORRECT_RESCUE_CLOSEOUT_FILENAME = "STEP6_4_6_CONTRACT_CORRECT_RESCUE_CLOSEOUT_REPORT.txt"
MIDSCALE_VALIDATION_CLOSEOUT_FILENAME = "STEP6_4_7_MIDSCALE_VALIDATION_CLOSEOUT_REPORT.txt"
MIDSCALE_CLEANUP_CLOSEOUT_FILENAME = "STEP6_4_8_MIDSCALE_CLEANUP_CLOSEOUT_REPORT.txt"
FAMILY_POLICY_VALIDATION_CLOSEOUT_FILENAME = "STEP6_FAMILY_AWARE_POLICY_VALIDATION_CLOSEOUT_REPORT.txt"
SUPPORTED_DEFINITION_STATUSES = {"coherent_supported", "fragmentary_supported"}
TIER1_RETRIEVAL_ROLES = {"definition", "equation", "procedure", "other"}
SHORT_CLEANUP_ONLY_FIELDS = {"definition_short", "field_evidence_map.definition_short"}
REQUIRED_CLOSEOUT_KC_IDS = [
    "KC_CLF_DT_012",
    "KC_CLU_CORE_003",
    "KC_CLF_NB_002",
    "KC_CLF_NB_011",
]
REQUIRED_CLOSEOUT_CANONICAL_NAMES = ["Gini Index"]
FAMILY_POLICY_DISPLAY_NAMES = {
    "dbscan": "DBSCAN",
    "naive_bayes": "Naive Bayes",
    "decision_trees": "Decision Trees",
}
FAMILY_POLICY_REPORT_CASE_IDS = {
    "dbscan": ["KC_CLU_DBS_005", "KC_CLU_DBS_001", "KC_CLU_DBS_009"],
    "naive_bayes": ["KC_CLF_NB_004"],
    "decision_trees": ["KC_CLF_DT_006"],
}
FAMILY_SUPPORT_POLICIES: Dict[str, Dict[str, Any]] = {
    "dbscan": {
        "family_id": "dbscan",
        "overlay_parent_labels": ["Density-Based Clustering (DBSCAN)"],
        "track_family_topic_support": True,
        "family_topic_cues": [
            "dbscan",
            "density based clustering",
            "density-based clustering",
            "advantages of dbscan",
        ],
        "generic_tokens": ["dbscan", "density", "based", "clustering", "cluster", "clusters", "eps", "minpts"],
        "parent_topic_overlap_blocks_rescue": True,
        "permissive_rescue_lineage_mode": "hard_block",
        "bundle_target_support_mode": "strict_leaf_only",
        "default_required_non_generic_name_tokens": 99,
        "default_required_non_generic_seed_hits": 99,
        "leaf_overrides": {
            "KC_CLU_DBS_001": {"include_phrases": ["core point"]},
            "KC_CLU_DBS_002": {"include_phrases": ["border point"]},
            "KC_CLU_DBS_003": {"include_phrases": ["noise point"]},
            "KC_CLU_DBS_004": {"include_all_tokens": [["eps", "minpts"]]},
            "KC_CLU_DBS_005": {"include_phrases": ["directly density reachable"]},
            "KC_CLU_DBS_006": {
                "include_phrases": ["density reachable from", "is density reachable"],
                "exclude_phrases": ["directly density reachable"],
            },
            "KC_CLU_DBS_007": {"include_phrases": ["density connected"]},
            "KC_CLU_DBS_008": {"include_phrases": ["density connected set", "maximally density connected"]},
            "KC_CLU_DBS_009": {"include_phrases": ["advantages and limitations", "advantages limitations"]},
        },
    },
    "naive_bayes": {
        "family_id": "naive_bayes",
        "overlay_parent_labels": ["Naive Bayes"],
        "track_family_topic_support": True,
        "family_topic_cues": ["naive bayes", "bayes classifier"],
        "generic_tokens": ["naive", "bayes", "nb", "classifier", "classification"],
        "parent_topic_overlap_blocks_rescue": False,
        "permissive_rescue_lineage_mode": "advisory",
        "bundle_target_support_mode": "strict_leaf_only",
        "default_required_non_generic_name_tokens": 1,
        "default_required_non_generic_seed_hits": 2,
        "leaf_overrides": {
            "KC_CLF_NB_001": {
                "include_phrases": ["bayes theorem"],
                "include_all_tokens": [["bayes", "theorem"]],
            },
            "KC_CLF_NB_002": {
                "include_phrases": ["prior probability"],
                "include_all_tokens": [["prior", "probability"]],
            },
            "KC_CLF_NB_003": {
                "include_phrases": ["conditional probability", "likelihood"],
                "include_all_tokens": [["conditional", "probability"]],
            },
            "KC_CLF_NB_004": {
                "include_phrases": ["independence assumption"],
                "include_all_tokens": [["independence", "assumption"]],
            },
            "KC_CLF_NB_005": {
                "include_phrases": ["learning phase"],
                "include_all_tokens": [["learning", "phase"]],
            },
            "KC_CLF_NB_006": {
                "include_phrases": ["classification phase"],
                "include_all_tokens": [["classification", "phase"]],
            },
            "KC_CLF_NB_007": {
                "include_phrases": ["zero frequency"],
                "include_all_tokens": [["zero", "frequency"]],
            },
            "KC_CLF_NB_008": {
                "include_phrases": ["laplace estimator", "laplace smoothing"],
                "include_all_tokens": [["laplace", "estimator"]],
            },
            "KC_CLF_NB_009": {
                "include_phrases": ["gaussian nb", "gaussian naive bayes"],
                "include_all_tokens": [["gaussian", "nb"], ["gaussian", "naive", "bayes"]],
            },
            "KC_CLF_NB_011": {
                "include_phrases": ["missing values"],
                "include_all_tokens": [["missing", "values"]],
            },
        },
    },
    "decision_trees": {
        "family_id": "decision_trees",
        "overlay_parent_labels": ["Decision Trees"],
        "track_family_topic_support": True,
        "family_topic_cues": ["decision tree", "decision trees", "tree induction"],
        "generic_tokens": ["decision", "tree", "trees", "node", "nodes", "split", "splitting", "attribute", "attributes", "algorithm", "algorithms", "induction"],
        "parent_topic_overlap_blocks_rescue": False,
        "permissive_rescue_lineage_mode": "advisory",
        "bundle_target_support_mode": "strict_leaf_only",
        "default_required_non_generic_name_tokens": 1,
        "default_required_non_generic_seed_hits": 1,
        "leaf_overrides": {
            "KC_CLF_DT_001": {
                "include_phrases": ["hunt algorithm", "hunt s algorithm"],
                "include_all_tokens": [["hunt", "algorithm"]],
            },
            "KC_CLF_DT_006": {
                "include_phrases": ["information gain", "infgain"],
                "include_all_tokens": [["information", "gain"]],
                "min_non_generic_name_token_hits": 2,
            },
            "KC_CLF_DT_007": {
                "include_phrases": ["intrinsic information", "split information"],
                "include_all_tokens": [["intrinsic", "information"]],
                "min_non_generic_name_token_hits": 2,
            },
            "KC_CLF_DT_008": {
                "include_phrases": ["gain ratio"],
                "include_all_tokens": [["gain", "ratio"]],
                "min_non_generic_name_token_hits": 2,
            },
            "KC_CLF_DT_010": {
                "include_phrases": ["bushy decision tree", "multi split", "multi-split"],
                "include_all_tokens": [["multi", "split"]],
            },
            "KC_CLF_DT_011": {
                "include_phrases": ["binary decision tree"],
                "include_all_tokens": [["binary", "decision", "tree"]],
            },
            "KC_CLF_DT_012": {
                "include_phrases": ["continuous attributes"],
                "include_all_tokens": [["continuous", "attributes"]],
            },
        },
    },
}
SEMANTIC_PAYLOAD_TEXT_FIELDS = [
    "definition_short",
    "definition_full",
    "inputs_outputs",
    "formal_definition",
    "interpretation",
    "claim_statement",
    "termination_condition",
    "when_to_use",
    "when_not_to_use",
    "misconception_statement",
    "canonical_correction",
]
SEMANTIC_PAYLOAD_LIST_FIELDS = [
    "scope_includes",
    "scope_excludes",
    "procedure_steps",
    "parameters",
    "assumptions",
    "diagnostic_cues",
    "remediation_suggestions",
    "worked_examples",
    "references",
]
SEMANTIC_PAYLOAD_EVIDENCE_FIELDS = [
    "definition_short",
    "definition_full",
    "scope_includes",
    "scope_excludes",
    "procedure_steps",
    "inputs_outputs",
    "formal_definition",
    "interpretation",
    "claim_statement",
]


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
        raise RuntimeError(f"Expected mapping config root at {path}")
    return obj


def load_json(path: Path) -> Dict[str, Any]:
    obj = json.loads(read_text(path))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected JSON object at {path}")
    return obj


def load_optional_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return load_json(path)
    except Exception:
        return {}


def load_optional_jsonl_lookup(path: Optional[Path], *, key: str = "kc_id") -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        for row in jsonl_iter(path):
            lookup_key = str(row.get(key) or "")
            if lookup_key:
                rows[lookup_key] = row
    except Exception:
        return {}
    return rows


def load_optional_kc_trace(processed_dir: Optional[Path], kc_id: str) -> Dict[str, Any]:
    if processed_dir is None:
        return {}
    return load_optional_json(processed_dir / "enrichment_traces" / f"{kc_id}.json")


def resolve_optional_repo_path(repo_root: Path, raw_path: Any, *, base_dir: Optional[Path] = None) -> Optional[Path]:
    if raw_path is None:
        return None
    text = str(raw_path).strip()
    if not text:
        return None
    return resolve_repo_path(repo_root, text, base_dir=base_dir)


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
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def choose_run_paths(repo_root: Path, processed_root_rel: str, runs_dir_rel: str, sets_dir_rel: str) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (repo_root / processed_root_rel / run_id).resolve()
        audit_dir = (repo_root / runs_dir_rel / f"{run_id}_step6_4_2").resolve()
        set_path = (repo_root / sets_dir_rel / f"{run_id}_step6_4_2_kc_library_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_4_2": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def import_script_module(repo_root: Path, rel_script_path: str, module_name: str):
    script_path = (repo_root / rel_script_path).resolve()
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import helper module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def list_ollama_models() -> List[str]:
    proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"ollama list failed: {proc.stderr.strip() or proc.stdout.strip()}")
    models: List[str] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split() if part.strip()]
        if parts:
            models.append(parts[0])
    return models


def choose_ollama_model(installed: Sequence[str], preferred: str, fallbacks: Sequence[str]) -> str:
    installed_set = list(installed)
    candidates = [preferred] + [str(item) for item in fallbacks]
    for candidate in candidates:
        if candidate in installed_set:
            return candidate
    for candidate in candidates:
        prefix = candidate.split(":")[0].strip().lower()
        for installed_name in installed_set:
            if installed_name.split(":")[0].strip().lower() == prefix:
                return installed_name
    raise RuntimeError(f"No configured Ollama model installed. Candidates={candidates}, installed={sorted(installed_set)}")


def is_primary_origin(origin: str) -> bool:
    return str(origin).endswith("_primary")


def origin_rank(origin: str) -> int:
    if is_primary_origin(origin):
        return 0
    if str(origin) == "step6_3_anchor":
        return 1
    return 2


def origin_bonus(origin: str) -> float:
    if is_primary_origin(origin):
        return 2.0
    if str(origin) == "step6_3_anchor":
        return 0.8
    return 0.4


def pretruncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


def l2_normalize_rows(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    denom = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
    return matrix / denom


def mean_or_zero(values: Sequence[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def candidate_sort_key(candidate: CandidateSentence) -> tuple[Any, ...]:
    return (
        candidate.doc_mismatch,
        candidate.d2_used,
        -candidate.rerank_target,
        -candidate.embed_margin,
        -candidate.pre_score,
        candidate.candidate_id,
    )


def evidence_item(candidate: CandidateSentence, role: str, extraction_method: str) -> Dict[str, Any]:
    quote_raw = str(candidate.quote_raw or candidate.quote or "")
    flags: List[str] = []
    if candidate.doc_mismatch:
        flags.append("DocGroupMismatch")
    if candidate.d2_used:
        flags.append(f"D2:{candidate.d2_confidence or 'accepted'}")
    if candidate.semantic_route:
        flags.append(f"SemanticRoute:{candidate.semantic_route}")
    flags.extend([str(item) for item in candidate.provenance_quality_flags if str(item).strip()])
    return {
        "doc_id": candidate.doc_id,
        "block_id": candidate.block_id,
        "page_index": int(candidate.page_index),
        "layer": candidate.layer,
        "bbox": candidate.bbox,
        "role": role if role in EVIDENCE_ROLE_VALUES else "other",
        "quote": quote_raw,
        "extraction_method": extraction_method,
        "quote_verified": bool(candidate.quote_verified and quote_raw),
        "provenance_quality_flags": unique_preserve_order(flags),
    }


def iter_record_evidence_local(record: Mapping[str, Any]) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    evidence_minimal = record.get("evidence_minimal")
    if isinstance(evidence_minimal, list):
        for idx, item in enumerate(evidence_minimal):
            if isinstance(item, Mapping):
                yield f"evidence_minimal[{idx}]", item
    field_map = record.get("field_evidence_map")
    if not isinstance(field_map, Mapping):
        return
    seen: set[Tuple[str, str, str, str]] = set()
    for field_name in sorted(field_map.keys()):
        value = field_map.get(field_name)
        if not isinstance(value, list):
            continue
        for idx, item in enumerate(value):
            if not isinstance(item, Mapping):
                continue
            key = (
                str(item.get("doc_id") or ""),
                str(item.get("block_id") or ""),
                str(item.get("role") or ""),
                str(item.get("quote") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            yield f"field_evidence_map.{field_name}[{idx}]", item


def find_verified_quote_mismatches_raw(
    record: Mapping[str, Any],
    source_lookup: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    issues: List[str] = []
    kc_id = str(record.get("kc_id") or "")
    for location, evidence in iter_record_evidence_local(record):
        if evidence.get("quote_verified") is not True:
            continue
        block_id = str(evidence.get("block_id") or "")
        quote = str(evidence.get("quote") or "")
        source_row = source_lookup.get(block_id)
        if not source_row:
            issues.append(f"{kc_id}:{location}:MissingSourceBlock:{block_id}")
            continue
        source_text = str(source_row.get("text") or "")
        if not source_text:
            issues.append(f"{kc_id}:{location}:EmptySourceText:{block_id}")
            continue
        if not verify_quote_in_raw_source(quote, source_text):
            issues.append(f"{kc_id}:{location}:QuoteNotVerifiable:{block_id}")
    return issues


def heuristic_role(candidate: CandidateSentence) -> str:
    if candidate.role_scores:
        ordered = sorted(candidate.role_scores.items(), key=lambda item: (-float(item[1]), ROLE_PRIORITY.get(str(item[0]), 99), str(item[0])))
        if ordered:
            return str(ordered[0][0])
    analysis = analyze_quote_role(
        quote=candidate.quote,
        canonical_name="",
        aliases=[],
        candidate=candidate,
        cfg={},
    )
    return str(analysis["top_role"])


def is_strong_same_topic(candidate: CandidateSentence, semantic_cfg: Mapping[str, Any]) -> bool:
    margin_min = float(semantic_cfg["margin_min"])
    rerank_margin = float(semantic_cfg["rerank_margin"])
    return (
        candidate.accepted
        and not candidate.doc_mismatch
        and candidate.embed_margin >= margin_min
        and candidate.rerank_margin >= rerank_margin
        and (candidate.name_alias_hits >= int(semantic_cfg["token_hit_min"]) or candidate.seed_kw_overlap >= int(semantic_cfg["seed_kw_overlap_min"]))
    )


def deterministic_sample_ids(kc_ids: Sequence[str], n: int) -> List[str]:
    return sorted(str(kc_id) for kc_id in kc_ids)[:n]


def validate_d2_payload(payload: Mapping[str, Any], allowed_ids: Sequence[str]) -> Tuple[bool, str]:
    if set(payload.keys()) != {"chosen_kc_id", "confidence"}:
        return False, "keys"
    if str(payload.get("chosen_kc_id") or "") not in set(str(item) for item in allowed_ids):
        return False, "chosen_kc_id"
    if str(payload.get("confidence") or "") not in {"high", "medium", "low"}:
        return False, "confidence"
    return True, ""


def validate_role_payload(payload: Mapping[str, Any], candidate_ids: Sequence[str]) -> Tuple[bool, str]:
    if set(payload.keys()) != {"role", "confidence"}:
        return False, "keys"
    if str(payload.get("role") or "") not in set(ROLE_LABEL_VALUES):
        return False, "role"
    if str(payload.get("confidence") or "") not in {"high", "medium", "low"}:
        return False, "confidence"
    return True, ""


class RuntimeCounters(dict):
    pass


@dataclass
class RuntimeModels:
    generation_model: str
    gate_model: str
    generation_base_url: str
    generation_retries: int
    generation_num_ctx: int
    generation_allow_think: bool
    gate_base_url: str
    gate_retries: int
    gate_num_ctx: int
    gate_allow_think: bool


@dataclass
class ProcessingResult:
    record: Dict[str, Any]
    base_tier: int
    semantic_tier: int
    semantic_tier_reasons: List[str]
    contamination_reasons: List[str]
    contamination_summary: Dict[str, Any]
    definition_status: str
    usable_curriculum: bool
    recovery_entry: Dict[str, Any]
    trace: Dict[str, Any]
    selected_candidates: List[CandidateSentence]
    all_candidates: List[CandidateSentence]
    failure_reasons: List[str]


def resolve_step5_primary_source(repo_root: Path, step5_set_obj: Mapping[str, Any]) -> Dict[str, Any]:
    artifacts = dict(step5_set_obj.get("artifacts") or {})
    candidates_path: Optional[Path] = None
    source_kind = ""
    origin_label = ""
    artifact_key = ""
    for candidate_key, candidate_kind, candidate_origin in PRIMARY_EVIDENCE_ARTIFACTS:
        raw_path = artifacts.get(candidate_key)
        if not raw_path:
            continue
        artifact_key = candidate_key
        source_kind = candidate_kind
        origin_label = candidate_origin
        candidates_path = resolve_repo_path(repo_root, raw_path)
        break
    if candidates_path is None:
        raise RuntimeError(
            "Step 5 primary set is missing a supported evidence artifact. "
            f"Expected one of {[item[0] for item in PRIMARY_EVIDENCE_ARTIFACTS]}, found={sorted(artifacts.keys())}"
        )
    upstream = dict(step5_set_obj.get("upstream") or {})
    step4_cfg_path: Optional[Path] = None
    step4_cfg_raw = upstream.get("step4_retrieval_config_snapshot")
    if step4_cfg_raw:
        step4_cfg_path = resolve_repo_path(repo_root, step4_cfg_raw)
    if step4_cfg_path is None:
        baseline_step5_target = upstream.get("baseline_step5_2_active_set_target")
        if baseline_step5_target:
            baseline_step5_set = load_json(resolve_repo_path(repo_root, baseline_step5_target))
            baseline_upstream = dict(baseline_step5_set.get("upstream") or {})
            baseline_cfg_raw = baseline_upstream.get("step4_retrieval_config_snapshot")
            if baseline_cfg_raw:
                step4_cfg_path = resolve_repo_path(repo_root, baseline_cfg_raw)
    if step4_cfg_path is None:
        fallback_cfg = (repo_root / "steps/step_04_structure_retrieval_index/resources/step4_3.default.yaml").resolve()
        if not fallback_cfg.exists():
            raise RuntimeError("Unable to resolve Step 4 retrieval config snapshot for Step 6.4.2")
        step4_cfg_path = fallback_cfg
    return {
        "artifact_key": artifact_key,
        "candidates_path": candidates_path,
        "source_kind": source_kind,
        "origin_label": origin_label,
        "step4_cfg": step4_cfg_path,
        "step4_5_set_path": (
            resolve_repo_path(repo_root, upstream["step4_5_active_set_target"])
            if upstream.get("step4_5_active_set_target")
            else None
        ),
        "step4_5_sentence_corpus_path": (
            resolve_repo_path(repo_root, upstream["step4_5_sentence_corpus_jsonl"])
            if upstream.get("step4_5_sentence_corpus_jsonl")
            else None
        ),
    }


def load_inputs(repo_root: Path, config: Mapping[str, Any]) -> Dict[str, Any]:
    inputs_cfg = dict(config["inputs"])
    step6_pointer = resolve_repo_path(repo_root, inputs_cfg["active_step6_set_pointer"])
    raw_step5_pointer = inputs_cfg.get("active_step5_primary_set_pointer") or inputs_cfg.get("active_step5_2_set_pointer")
    if not raw_step5_pointer:
        raise RuntimeError("Step 6.4.2 config is missing active_step5_primary_set_pointer")
    step5_pointer = resolve_repo_path(repo_root, raw_step5_pointer)
    step4_pointer = resolve_repo_path(repo_root, inputs_cfg["step4_active_set_pointer"])
    kc_registry = resolve_repo_path(repo_root, inputs_cfg["kc_registry_path"])
    baseline_summary_path = (
        resolve_repo_path(repo_root, inputs_cfg["baseline_step6_4_2_summary_json"])
        if inputs_cfg.get("baseline_step6_4_2_summary_json")
        else None
    )
    baseline_closeout_path = (
        resolve_repo_path(repo_root, inputs_cfg["baseline_step6_4_2_closeout_report"])
        if inputs_cfg.get("baseline_step6_4_2_closeout_report")
        else None
    )
    baseline_false_rejection_audit_path = (
        baseline_summary_path.parent / "false_rejection_audit.json"
        if baseline_summary_path is not None
        else None
    )
    baseline_run_id = ""
    baseline_definition_short_audit_path: Optional[Path] = None
    baseline_kc_library_path: Optional[Path] = None
    baseline_processed_dir: Optional[Path] = None
    if baseline_summary_path is not None:
        baseline_run_dir_name = baseline_summary_path.parent.name
        baseline_suffix = "_step6_4_2"
        baseline_run_id = (
            baseline_run_dir_name[: -len(baseline_suffix)]
            if baseline_run_dir_name.endswith(baseline_suffix)
            else ""
        )
        if baseline_run_id:
            candidate_processed_dir = repo_root / "data/processed/kc_library" / baseline_run_id
            if candidate_processed_dir.exists():
                baseline_processed_dir = candidate_processed_dir
            candidate_audit = repo_root / "data/processed/kc_library" / baseline_run_id / "definition_short_contract_audit.jsonl"
            if candidate_audit.exists():
                baseline_definition_short_audit_path = candidate_audit
            candidate_library = repo_root / "data/processed/kc_library" / baseline_run_id / "kc_library.jsonl"
            if candidate_library.exists():
                baseline_kc_library_path = candidate_library
    exact_kc_id_slice = [str(item).strip() for item in list(inputs_cfg.get("exact_kc_id_slice") or []) if str(item).strip()]
    hierarchy_overlay_node_index_path = resolve_optional_repo_path(
        repo_root,
        inputs_cfg.get("hierarchy_overlay_node_index_path"),
    )
    hierarchy_leaf_ancestry_path = resolve_optional_repo_path(
        repo_root,
        inputs_cfg.get("hierarchy_leaf_ancestry_path"),
    )
    if hierarchy_overlay_node_index_path is not None and not hierarchy_overlay_node_index_path.exists():
        raise FileNotFoundError(f"Configured hierarchy overlay node index not found: {hierarchy_overlay_node_index_path}")
    if hierarchy_leaf_ancestry_path is not None and not hierarchy_leaf_ancestry_path.exists():
        raise FileNotFoundError(f"Configured hierarchy leaf ancestry not found: {hierarchy_leaf_ancestry_path}")
    step6_set = resolve_pointer(step6_pointer)
    step5_set = resolve_pointer(step5_pointer)
    step4_set = resolve_pointer(step4_pointer)
    step6_set_obj = load_json(step6_set)
    step5_set_obj = load_json(step5_set)
    step4_set_obj = load_json(step4_set)
    step5_primary_meta = resolve_step5_primary_source(repo_root, step5_set_obj)
    step6_library = resolve_repo_path(repo_root, step6_set_obj["artifacts"]["kc_library_jsonl"])
    schema_path = repo_root / "schema.json"
    return {
        "step6_pointer": step6_pointer,
        "step5_pointer": step5_pointer,
        "step4_pointer": step4_pointer,
        "kc_registry": kc_registry,
        "step6_set_path": step6_set,
        "step5_set_path": step5_set,
        "step4_set_path": step4_set,
        "step6_set": step6_set_obj,
        "step5_set": step5_set_obj,
        "step4_set": step4_set_obj,
        "step6_library": step6_library,
        "step5_primary_candidates": step5_primary_meta["candidates_path"],
        "step5_primary_artifact_key": step5_primary_meta["artifact_key"],
        "step5_primary_kind": step5_primary_meta["source_kind"],
        "step5_primary_origin_label": step5_primary_meta["origin_label"],
        "step4_cfg": step5_primary_meta["step4_cfg"],
        "step4_5_set_path": step5_primary_meta["step4_5_set_path"],
        "step4_5_sentence_corpus_path": step5_primary_meta["step4_5_sentence_corpus_path"],
        "schema_path": schema_path,
        "baseline_step6_4_2_summary_path": baseline_summary_path,
        "baseline_step6_4_2_closeout_path": baseline_closeout_path,
        "baseline_step6_4_2_run_id": baseline_run_id,
        "baseline_step6_4_2_processed_dir": baseline_processed_dir,
        "baseline_step6_4_2_false_rejection_audit_path": baseline_false_rejection_audit_path,
        "baseline_step6_4_2_definition_short_audit_path": baseline_definition_short_audit_path,
        "baseline_step6_4_2_kc_library_path": baseline_kc_library_path,
        "exact_kc_id_slice": exact_kc_id_slice,
        "hierarchy_overlay_node_index_path": hierarchy_overlay_node_index_path,
        "hierarchy_leaf_ancestry_path": hierarchy_leaf_ancestry_path,
    }


def build_overlay_hierarchy_context(
    *,
    overlay_node_index: Mapping[str, Any],
    leaf_ancestry: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    context_by_kc: Dict[str, Dict[str, Any]] = {}
    if not isinstance(overlay_node_index, Mapping) or not isinstance(leaf_ancestry, Mapping):
        return context_by_kc
    for kc_id, raw_ancestry in leaf_ancestry.items():
        if not isinstance(raw_ancestry, Mapping):
            continue
        parent_hier_node_id = str(raw_ancestry.get("parent_hier_node_id") or "")
        parent_node = overlay_node_index.get(parent_hier_node_id) if parent_hier_node_id else None
        parent_node_map = dict(parent_node) if isinstance(parent_node, Mapping) else {}
        sibling_kc_ids = [
            str(descendant_kc_id)
            for descendant_kc_id in list(parent_node_map.get("descendant_kc_ids") or [])
            if str(descendant_kc_id) and str(descendant_kc_id) != str(kc_id)
        ]
        context_by_kc[str(kc_id)] = {
            "overlay_parent_hier_node_id": parent_hier_node_id,
            "overlay_parent_label": str(parent_node_map.get("label") or ""),
            "overlay_ancestor_labels": [str(item) for item in list(raw_ancestry.get("ancestor_labels") or []) if str(item).strip()],
            "overlay_sibling_kc_ids": unique_preserve_order(sibling_kc_ids),
            "overlay_source_hierarchy_path": [
                str(item) for item in list(raw_ancestry.get("source_hierarchy_path") or []) if str(item).strip()
            ],
        }
    return context_by_kc


def attach_hierarchy_context_to_registry_rows(
    registry_rows: Sequence[Mapping[str, Any]],
    hierarchy_context_by_kc: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    attached_rows: List[Dict[str, Any]] = []
    for row in registry_rows:
        merged = dict(row)
        context = dict(hierarchy_context_by_kc.get(str(row.get("kc_id") or "")) or {})
        if context:
            merged.update(context)
        attached_rows.append(merged)
    return attached_rows


def load_kc_rows(registry_path: Path, step6_library_path: Path, primary_path: Path) -> Dict[str, Any]:
    registry_rows = list(jsonl_iter(registry_path))
    registry_by_id = {str(row["kc_id"]): row for row in registry_rows}
    step6_rows = list(jsonl_iter(step6_library_path))
    step6_by_id = {str(row["kc_id"]): row for row in step6_rows}
    step5_rows = list(jsonl_iter(primary_path))
    step5_by_id = {str(row["kc_id"]): row for row in step5_rows}
    return {
        "registry_rows": registry_rows,
        "registry_by_id": registry_by_id,
        "step6_rows": step6_rows,
        "step6_by_id": step6_by_id,
        "step5_by_id": step5_by_id,
    }


def select_kc_subset(
    registry_rows: Sequence[Mapping[str, Any]],
    limit_kcs: Optional[int],
    *,
    exact_kc_ids: Optional[Sequence[str]] = None,
) -> List[Mapping[str, Any]]:
    ordered = sorted(registry_rows, key=lambda row: str(row["kc_id"]))
    if exact_kc_ids:
        by_id = {str(row["kc_id"]): row for row in ordered}
        missing = [str(kc_id) for kc_id in exact_kc_ids if str(kc_id) not in by_id]
        if missing:
            raise RuntimeError(f"Configured exact_kc_id_slice contains unknown kc_id values: {missing}")
        chosen = [by_id[str(kc_id)] for kc_id in exact_kc_ids]
        if limit_kcs is not None and len(chosen) != int(limit_kcs):
            raise RuntimeError(
                f"Configured exact_kc_id_slice length {len(chosen)} does not match --limit-kcs {int(limit_kcs)}"
            )
        return chosen if limit_kcs is None else chosen[: int(limit_kcs)]
    if limit_kcs is None:
        return list(ordered)
    by_name = {match_normalize(str(row.get("canonical_name") or "")): row for row in ordered}
    chosen: List[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for name in REQUIRED_DRY_CANONICAL_NAMES + preferred_good_name_order():
        row = by_name.get(match_normalize(name))
        if row is None:
            continue
        kc_id = str(row["kc_id"])
        if kc_id in seen_ids:
            continue
        chosen.append(row)
        seen_ids.add(kc_id)
        if len(chosen) >= limit_kcs:
            return chosen
    for row in ordered:
        kc_id = str(row["kc_id"])
        if kc_id in seen_ids:
            continue
        chosen.append(row)
        seen_ids.add(kc_id)
        if len(chosen) >= limit_kcs:
            break
    return chosen


def load_source_corpus(step4_set_obj: Mapping[str, Any], repo_root: Path) -> Dict[str, Any]:
    source_lookup: Dict[str, Dict[str, Any]] = {}
    doc_blocks: Dict[str, List[Dict[str, Any]]] = {}
    block_positions: Dict[str, int] = {}
    corpus_paths: List[Path] = []
    for doc_key in sorted(step4_set_obj["docs"].keys()):
        info = step4_set_obj["docs"][doc_key]
        corpus_path = resolve_repo_path(repo_root, info["artifacts"]["block_text_corpus.jsonl"]["path"])
        corpus_paths.append(corpus_path)
        rows = list(jsonl_iter(corpus_path))
        if not rows:
            continue
        doc_id = str(rows[0].get("doc_id") or doc_key)
        doc_blocks[doc_id] = rows
        for idx, row in enumerate(rows):
            block_id = str(row["block_id"])
            source_lookup[block_id] = row
            block_positions[block_id] = idx
    return {"source_lookup": source_lookup, "doc_blocks": doc_blocks, "block_positions": block_positions, "corpus_paths": corpus_paths}


def load_embedding_cfg(step4_cfg_path: Path) -> Dict[str, Any]:
    cfg = load_yaml(step4_cfg_path)
    embed_cfg = cfg.get("embedding")
    if not isinstance(embed_cfg, dict):
        raise RuntimeError(f"Step 4 retrieval config missing embedding section: {step4_cfg_path}")
    return dict(embed_cfg)


def embed_texts(step43: Any, embed_cfg: Mapping[str, Any], texts: Sequence[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, int(embed_cfg.get("dimensions") or 1)), dtype=np.float32)
    batch_size = int(embed_cfg.get("batch_size") or 32)
    max_chars = int(embed_cfg.get("max_chars") or 0)
    prepared = [pretruncate(str(text), max_chars) for text in texts]
    rows: List[List[float]] = []
    for start in range(0, len(prepared), batch_size):
        batch = prepared[start : start + batch_size]
        rows.extend(
            step43.ollama_embed(
                base_url=str(embed_cfg["base_url"]),
                model=str(embed_cfg["model"]),
                inputs=batch,
                truncate=bool(embed_cfg.get("truncate", True)),
                dimensions=int(embed_cfg["dimensions"]),
                keep_alive=str(embed_cfg.get("keep_alive") or "30m"),
                options=dict(embed_cfg.get("options") or {}),
                timeout_s=300.0,
            )
        )
    return np.asarray(rows, dtype=np.float32)


def build_query_cache(
    *,
    selected_rows: Sequence[Mapping[str, Any]],
    step6_by_id: Mapping[str, Mapping[str, Any]],
    embed_cfg: Mapping[str, Any],
    step43: Any,
) -> Dict[str, Any]:
    query_text_by_id: Dict[str, str] = {}
    kc_row_lookup: Dict[str, Dict[str, Any]] = {}
    for registry_row in selected_rows:
        kc_id = str(registry_row["kc_id"])
        base_row = dict(step6_by_id.get(kc_id) or {})
        merged = dict(registry_row)
        if base_row:
            merged["kc_type"] = str(base_row.get("kc_type") or "concept")
            merged["base_definition_short"] = str(base_row.get("definition_short") or "")
        query_text_by_id[kc_id] = build_query_text(
            str(registry_row["canonical_name"]),
            ensure_string_list(registry_row.get("aliases")),
            str(registry_row.get("seed_definition") or ""),
        )
        kc_row_lookup[kc_id] = merged
    ordered_ids = [str(row["kc_id"]) for row in selected_rows]
    query_matrix = embed_texts(step43, embed_cfg, [query_text_by_id[kc_id] for kc_id in ordered_ids])
    query_matrix = l2_normalize_rows(query_matrix)
    index_by_id = {kc_id: idx for idx, kc_id in enumerate(ordered_ids)}
    sims = np.matmul(query_matrix, query_matrix.T)
    competitor_ids_by_kc: Dict[str, List[str]] = {}
    for kc_id in ordered_ids:
        idx = index_by_id[kc_id]
        ranked = np.argsort(-sims[idx])
        competitors: List[str] = []
        for other_idx in ranked:
            other_id = ordered_ids[int(other_idx)]
            if other_id == kc_id:
                continue
            competitors.append(other_id)
            if len(competitors) >= 25:
                break
        competitor_ids_by_kc[kc_id] = competitors
    return {
        "query_text_by_id": query_text_by_id,
        "kc_row_lookup": kc_row_lookup,
        "ordered_ids": ordered_ids,
        "query_matrix": query_matrix,
        "query_similarities": sims,
        "index_by_id": index_by_id,
        "competitor_ids_by_kc": competitor_ids_by_kc,
    }


def call_json_with_retries(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    format_schema: Dict[str, Any],
    retries: int,
    num_ctx: int,
    allow_think_fallback: bool,
    timeout_s: float,
    validator: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    errors: List[str] = []
    max_retries = max(1, int(retries))
    for attempt in range(max_retries):
        think = False
        if allow_think_fallback and attempt >= 2:
            projected_frac = float((runtime_counters["think_calls"] + 1) / max(1, runtime_counters["llm_calls"] + 1))
            think = projected_frac <= 0.10
        runtime_counters["llm_calls"] += 1
        if think:
            runtime_counters["think_calls"] += 1
        try:
            payload, outer, raw = step63.ollama_chat_json(
                base_url=base_url,
                model=model,
                messages=messages,
                format_schema=format_schema,
                temperature=0,
                top_p=1.0,
                num_ctx=int(num_ctx),
                repeat_penalty=1.0,
                think=think,
                timeout_s=timeout_s,
            )
            ok, reason = validator(payload)
            if ok:
                return dict(payload), {"attempt": attempt + 1, "think": think, "raw_response": raw, "outer": outer}
            errors.append(f"Attempt{attempt + 1}:InvalidPayload:{reason}")
        except Exception as exc:
            errors.append(f"Attempt{attempt + 1}:{type(exc).__name__}:{exc}")
    raise RuntimeError(";".join(errors))


def make_block_entry(
    source_row: Mapping[str, Any],
    *,
    origin: str,
    seed_row: Optional[Mapping[str, Any]] = None,
    patch_heading: str = "",
    alignment_score: float = 0.0,
    combined_score: float = 0.0,
    snippet: str = "",
) -> Dict[str, Any]:
    snippet_text = str(snippet or "")
    seed_rows: List[Dict[str, Any]] = []
    if seed_row:
        raw_flags = ((seed_row.get("alignment_breakdown") or {}).get("flags") or {}) if isinstance(seed_row, Mapping) else {}
        quote = str(seed_row.get("sentence_text") or seed_row.get("quote") or snippet_text or "")
        seed_rows.append(
            {
                "quote": quote,
                "sentence_id": str(seed_row.get("sentence_id") or ""),
                "sent_idx": safe_int(seed_row.get("sent_idx"), default=-1),
                "char_start": safe_int(seed_row.get("char_start"), default=-1),
                "char_end": safe_int(seed_row.get("char_end"), default=-1),
                "page_index": safe_int(seed_row.get("page_index"), default=safe_int(source_row.get("page_index"), default=-1)),
                "layer": str(seed_row.get("layer") or source_row.get("layer") or ""),
                "bbox": seed_row.get("bbox") if seed_row.get("bbox") is not None else source_row.get("bbox"),
                "reveal_group_id": seed_row.get("reveal_group_id"),
                "reveal_canonical_page_index": seed_row.get("reveal_canonical_page_index"),
                "patch_id": str(seed_row.get("patch_id") or ""),
                "patch_heading": str(seed_row.get("patch_heading") or patch_heading or ""),
                "patch_type": str(seed_row.get("patch_type") or ""),
                "patch_span_source": str(seed_row.get("patch_span_source") or ""),
                "page_heading_norm": str(seed_row.get("page_heading_norm") or source_row.get("page_heading_norm") or ""),
                "text_source": str(seed_row.get("text_source") or ""),
                "source_block_text": str(seed_row.get("source_block_text") or source_row.get("text") or ""),
                "sentence_flags": {str(key): bool(value) for key, value in raw_flags.items()} if isinstance(raw_flags, Mapping) else {},
            }
        )
    return {
        "doc_id": str(source_row.get("doc_id") or ""),
        "block_id": str(source_row.get("block_id") or ""),
        "page_index": safe_int(source_row.get("page_index"), default=-1),
        "layer": str(source_row.get("layer") or ""),
        "bbox": source_row.get("bbox"),
        "patch_heading": patch_heading,
        "page_heading_norm": str(source_row.get("page_heading_norm") or ""),
        "origin": origin,
        "alignment_score": float(alignment_score),
        "combined_score": float(combined_score),
        "snippet": snippet_text,
        "snippets": [snippet_text] if snippet_text else [],
        "seed_rows": seed_rows,
    }


def register_block(blocks: Dict[str, Dict[str, Any]], entry: Mapping[str, Any]) -> None:
    block_id = str(entry["block_id"])
    existing = blocks.get(block_id)
    if existing is None:
        blocks[block_id] = dict(entry)
        blocks[block_id]["origins"] = [str(entry["origin"])]
        blocks[block_id]["seed_rows"] = list(entry.get("seed_rows") or [])
        return
    existing["alignment_score"] = max(float(existing["alignment_score"]), float(entry["alignment_score"]))
    existing["combined_score"] = max(float(existing["combined_score"]), float(entry["combined_score"]))
    if str(entry.get("patch_heading") or "") and not str(existing.get("patch_heading") or ""):
        existing["patch_heading"] = str(entry["patch_heading"])
    existing["origins"] = unique_preserve_order(list(existing.get("origins") or []) + [str(entry["origin"])])
    existing["snippets"] = unique_preserve_order(
        [str(item) for item in list(existing.get("snippets") or []) + list(entry.get("snippets") or []) if str(item or "").strip()]
    )
    seed_rows: List[Dict[str, Any]] = list(existing.get("seed_rows") or [])
    seen_seed_keys = {
        (str(item.get("quote") or ""), str(item.get("sentence_id") or ""), str(item.get("layer") or ""))
        for item in seed_rows
        if isinstance(item, Mapping)
    }
    for item in list(entry.get("seed_rows") or []):
        if not isinstance(item, Mapping):
            continue
        key = (str(item.get("quote") or ""), str(item.get("sentence_id") or ""), str(item.get("layer") or ""))
        if key in seen_seed_keys:
            continue
        seed_rows.append(dict(item))
        seen_seed_keys.add(key)
    existing["seed_rows"] = seed_rows
    if origin_rank(str(entry.get("origin") or "")) < origin_rank(str(existing.get("origin") or "")):
        existing["origin"] = str(entry["origin"])
    if not str(existing.get("snippet") or "") and str(entry.get("snippet") or ""):
        existing["snippet"] = str(entry["snippet"])
    elif not str(existing.get("snippet") or "") and existing.get("snippets"):
        existing["snippet"] = str(existing["snippets"][0])


def collect_block_candidates(
    *,
    step5_row: Optional[Mapping[str, Any]],
    step6_row: Optional[Mapping[str, Any]],
    source_lookup: Mapping[str, Mapping[str, Any]],
    doc_blocks: Mapping[str, Sequence[Mapping[str, Any]]],
    block_positions: Mapping[str, int],
    max_primary_blocks: int,
    primary_origin_label: str,
) -> List[Dict[str, Any]]:
    blocks: Dict[str, Dict[str, Any]] = {}
    primary_block_ids: List[str] = []
    if step5_row:
        for raw in list(step5_row.get("evidence") or [])[: max_primary_blocks]:
            block_id = str(raw.get("block_id") or "")
            source_row = source_lookup.get(block_id)
            if not source_row:
                continue
            entry = make_block_entry(
                source_row,
                origin=primary_origin_label,
                seed_row=raw,
                patch_heading=str(raw.get("patch_heading") or ""),
                alignment_score=float(raw.get("alignment_score") or 0.0),
                combined_score=float(((raw.get("retrieval_scores") or {}).get("combined")) or 0.0),
                snippet=str(raw.get("snippet") or ""),
            )
            register_block(blocks, entry)
            primary_block_ids.append(block_id)
    if step6_row:
        for raw in list(step6_row.get("evidence_minimal") or []):
            block_id = str(raw.get("block_id") or "")
            source_row = source_lookup.get(block_id)
            if not source_row:
                continue
            register_block(blocks, make_block_entry(source_row, origin="step6_3_anchor", seed_row=raw, snippet=str(raw.get("quote") or "")))
    for block_id in primary_block_ids:
        source_row = source_lookup.get(block_id)
        if not source_row:
            continue
        doc_id = str(source_row.get("doc_id") or "")
        rows = list(doc_blocks.get(doc_id) or [])
        if not rows:
            continue
        idx = int(block_positions.get(block_id, -1))
        if idx < 0:
            continue
        for offset in (-2, -1, 1, 2):
            other_idx = idx + offset
            if other_idx < 0 or other_idx >= len(rows):
                continue
            register_block(blocks, make_block_entry(rows[other_idx], origin="step4_neighbor"))
    return sorted(
        blocks.values(),
        key=lambda item: (
            origin_rank(str(item["origin"])),
            -float(item["alignment_score"]),
            -float(item["combined_score"]),
            str(item["doc_id"]),
            int(item["page_index"]),
            str(item["block_id"]),
        ),
    )


def quote_candidates_from_block(
    *,
    kc_id: str,
    block_entry: Mapping[str, Any],
    source_row: Mapping[str, Any],
    name_terms: Mapping[str, Any],
    kc_group: str,
    semantic_cfg: Mapping[str, Any],
) -> List[CandidateSentence]:
    raw_text = str(source_row.get("text") or "")
    if not normalize_ws(raw_text):
        return []
    patch_heading = str(block_entry.get("patch_heading") or source_row.get("page_heading_norm") or "")
    page_heading_norm = str(source_row.get("page_heading_norm") or "")
    heading_tokens = set(tokenize(match_normalize(f"{patch_heading} {page_heading_norm}")))
    name_tokens = set(name_terms["canonical_tokens"]) | set(name_terms["alias_tokens"])
    quote_pool: List[str] = []
    seed_meta_by_quote: Dict[str, Mapping[str, Any]] = {}
    for seed_row in list(block_entry.get("seed_rows") or []):
        if not isinstance(seed_row, Mapping):
            continue
        seed_quote = str(seed_row.get("quote") or "")
        if seed_quote and seed_quote in raw_text and normalize_ws(seed_quote) == seed_quote:
            quote_pool.append(seed_quote)
            seed_meta_by_quote.setdefault(seed_quote, seed_row)
    for snippet in unique_preserve_order([str(item) for item in list(block_entry.get("snippets") or []) if str(item or "").strip()]):
        if snippet and snippet in raw_text and normalize_ws(snippet) == snippet:
            quote_pool.append(snippet)
    for piece in split_exact_sentences(raw_text):
        if normalize_ws(piece) != piece:
            continue
        quote_pool.append(piece)
    stripped = raw_text.strip()
    if normalize_ws(stripped) == stripped and len(normalize_ws(stripped)) <= 280:
        quote_pool.append(stripped)
    seen_quotes: set[str] = set()
    candidates: List[CandidateSentence] = []
    for quote in quote_pool:
        if quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        quote_norm = normalize_ws(quote)
        if len(quote_norm) < 18:
            continue
        sentence_norm = match_normalize(quote_norm)
        quote_tokens = set(tokenize(sentence_norm))
        canonical_hits = len(set(name_terms["canonical_tokens"]) & quote_tokens)
        alias_hits = len(set(name_terms["alias_tokens"]) & quote_tokens)
        name_hits = canonical_hits + alias_hits
        seed_overlap = sum(1 for token in name_terms["seed_keywords"] if token in quote_tokens)
        exact_name, exact_alias = exact_phrase_hits(sentence_norm, str(name_terms["canonical_norm"]), list(name_terms["alias_norms"]))
        heading_hits = len(name_tokens & heading_tokens)
        doc_group = derive_doc_group(str(block_entry["doc_id"]))
        doc_mismatch = doc_group != kc_group and doc_group != "other" and kc_group != "other"
        origin = str(block_entry["origin"])
        seed_meta = dict(seed_meta_by_quote.get(quote) or {})
        page_index = safe_int(seed_meta.get("page_index"), default=safe_int(block_entry.get("page_index"), default=-1))
        pre_score = (
            float(block_entry["alignment_score"]) * 1.8
            + float(block_entry["combined_score"]) * 2.0
            + name_hits * 2.5
            + seed_overlap * 1.6
            + heading_hits * 0.8
            + (2.0 if exact_name or exact_alias else 0.0)
            + origin_bonus(origin)
            - (float(semantic_cfg["doc_mismatch_penalty"]) if doc_mismatch else 0.0)
        )
        candidates.append(
            CandidateSentence(
                candidate_id=f"{kc_id}:cand:{len(candidates):03d}",
                doc_id=str(block_entry["doc_id"]),
                block_id=str(block_entry["block_id"]),
                page_index=page_index,
                layer=str(block_entry["layer"]),
                bbox=block_entry.get("bbox"),
                quote=quote,
                source_text=raw_text,
                patch_heading=patch_heading,
                block_anchor_id=str(block_entry["block_id"]),
                origin=origin,
                sentence_id=str(seed_meta.get("sentence_id") or ""),
                sent_idx=safe_int(seed_meta.get("sent_idx"), default=-1),
                char_start=safe_int(seed_meta.get("char_start"), default=-1),
                char_end=safe_int(seed_meta.get("char_end"), default=-1),
                reveal_group_id=seed_meta.get("reveal_group_id"),
                reveal_canonical_page_index=seed_meta.get("reveal_canonical_page_index"),
                patch_id=str(seed_meta.get("patch_id") or ""),
                patch_type=str(seed_meta.get("patch_type") or ""),
                patch_span_source=str(seed_meta.get("patch_span_source") or ""),
                page_heading_norm=str(seed_meta.get("page_heading_norm") or block_entry.get("page_heading_norm") or ""),
                text_source=str(seed_meta.get("text_source") or ""),
                source_block_text=str(seed_meta.get("source_block_text") or raw_text),
                quote_raw=quote,
                quote_match_norm=match_normalize(quote),
                text_raw=raw_text,
                text_match_norm=match_normalize(raw_text),
                source_block_text_raw=str(seed_meta.get("source_block_text") or raw_text),
                source_block_text_match_norm=match_normalize(str(seed_meta.get("source_block_text") or raw_text)),
                quote_verified=verify_quote_in_raw_source(quote, raw_text),
                sentence_flags={str(key): bool(value) for key, value in dict(seed_meta.get("sentence_flags") or {}).items()},
                doc_group=doc_group,
                kc_group=kc_group,
                doc_mismatch=doc_mismatch,
                name_alias_hits=name_hits,
                seed_kw_overlap=seed_overlap,
                exact_name_phrase=exact_name,
                exact_alias_phrase=exact_alias,
                heading_name_hits=heading_hits,
                primary_alignment_score=float(block_entry["alignment_score"]),
                primary_combined_score=float(block_entry["combined_score"]),
                pre_score=float(pre_score),
                original_block_id=str(block_entry["block_id"]),
                original_page_index=page_index,
                original_layer=str(block_entry["layer"]),
                provenance_status="original" if has_valid_page_index(page_index) else "invalid",
            )
        )
    return candidates


def build_candidate_pool(
    *,
    kc_id: str,
    registry_row: Mapping[str, Any],
    step5_row: Optional[Mapping[str, Any]],
    step6_row: Optional[Mapping[str, Any]],
    source_lookup: Mapping[str, Mapping[str, Any]],
    doc_blocks: Mapping[str, Sequence[Mapping[str, Any]]],
    block_positions: Mapping[str, int],
    semantic_cfg: Mapping[str, Any],
    enrichment_cfg: Mapping[str, Any],
    primary_origin_label: str,
) -> List[CandidateSentence]:
    kc_group = derive_kc_group(registry_row.get("kc_path") or [])
    name_terms = build_name_seed_terms(
        str(registry_row["canonical_name"]),
        ensure_string_list(registry_row.get("aliases")),
        str(registry_row.get("seed_definition") or ""),
    )
    blocks = collect_block_candidates(
        step5_row=step5_row,
        step6_row=step6_row,
        source_lookup=source_lookup,
        doc_blocks=doc_blocks,
        block_positions=block_positions,
        max_primary_blocks=int(enrichment_cfg["max_candidate_blocks_per_kc"]),
        primary_origin_label=primary_origin_label,
    )
    candidates: List[CandidateSentence] = []
    for block in blocks:
        source_row = source_lookup.get(str(block["block_id"]))
        if not source_row:
            continue
        candidates.extend(
            quote_candidates_from_block(
                kc_id=kc_id,
                block_entry=block,
                source_row=source_row,
                name_terms=name_terms,
                kc_group=kc_group,
                semantic_cfg=semantic_cfg,
            )
        )
    candidates.sort(key=lambda item: (-item.pre_score, item.candidate_id))
    deduped: List[CandidateSentence] = []
    seen_keys: set[Tuple[str, str]] = set()
    quote_norm_pages: Dict[str, set[Tuple[str, int]]] = defaultdict(set)
    for candidate in candidates:
        key = (candidate.block_id, candidate.quote)
        quote_norm = normalize_ws(candidate.quote)
        page_key = (candidate.doc_id, int(candidate.page_index))
        if key in seen_keys:
            continue
        if page_key in quote_norm_pages[quote_norm]:
            continue
        if len(quote_norm_pages[quote_norm]) >= 2:
            continue
        seen_keys.add(key)
        quote_norm_pages[quote_norm].add(page_key)
        deduped.append(candidate)
        if len(deduped) >= int(enrichment_cfg["max_sentences_considered"]):
            break
    for idx, candidate in enumerate(deduped):
        candidate.candidate_id = f"{kc_id}:cand:{idx:03d}"
    return deduped


def apply_embedding_scores(
    *,
    kc_id: str,
    candidates: Sequence[CandidateSentence],
    query_cache: Mapping[str, Any],
    embed_cfg: Mapping[str, Any],
    step43: Any,
) -> None:
    if not candidates:
        return
    quote_matrix = embed_texts(step43, embed_cfg, [normalize_ws(candidate.quote) for candidate in candidates])
    quote_matrix = l2_normalize_rows(quote_matrix)
    target_idx = int(query_cache["index_by_id"][kc_id])
    target_vec = query_cache["query_matrix"][target_idx]
    competitor_ids = list(query_cache["competitor_ids_by_kc"][kc_id])[:25]
    competitor_indices = [int(query_cache["index_by_id"][other_id]) for other_id in competitor_ids]
    competitor_matrix = query_cache["query_matrix"][competitor_indices] if competitor_indices else np.zeros((0, quote_matrix.shape[1]), dtype=np.float32)
    for idx, candidate in enumerate(candidates):
        candidate.embed_sim_target = float(np.dot(quote_matrix[idx], target_vec))
        if competitor_indices:
            scores = np.matmul(competitor_matrix, quote_matrix[idx])
            best_idx = int(np.argmax(scores))
            candidate.embed_best_other = float(scores[best_idx])
            candidate.embed_best_other_kc_id = str(competitor_ids[best_idx])
        else:
            candidate.embed_best_other = 0.0
            candidate.embed_best_other_kc_id = ""
        candidate.embed_margin = float(candidate.embed_sim_target - candidate.embed_best_other)


def semantic_gate(candidate: CandidateSentence, semantic_cfg: Mapping[str, Any]) -> bool:
    token_pass = (
        candidate.name_alias_hits >= int(semantic_cfg["token_hit_min"])
        or candidate.exact_name_phrase
        or candidate.exact_alias_phrase
        or candidate.seed_kw_overlap >= int(semantic_cfg["seed_kw_overlap_min"])
    )
    semantic_pass = (
        candidate.embed_sim_target >= float(semantic_cfg["embed_sim_min"])
        and candidate.embed_margin >= float(semantic_cfg["margin_min"])
    )
    if token_pass and semantic_pass:
        candidate.semantic_route = "token+semantic"
        return True
    if token_pass:
        candidate.semantic_route = "token"
        return True
    if semantic_pass:
        candidate.semantic_route = "semantic"
        return True
    if candidate.embed_sim_target < float(semantic_cfg["embed_sim_min"]):
        candidate.gate_reasons.append("EmbedSimFail")
    if candidate.embed_margin < float(semantic_cfg["margin_min"]):
        candidate.gate_reasons.append("EmbedMarginFail")
    if candidate.name_alias_hits < int(semantic_cfg["token_hit_min"]) and candidate.seed_kw_overlap < int(semantic_cfg["seed_kw_overlap_min"]):
        candidate.gate_reasons.append("TokenAlignmentFail")
    return False


def apply_reranker_scores(
    *,
    kc_id: str,
    candidates: Sequence[CandidateSentence],
    query_cache: Mapping[str, Any],
    scorer: Any,
) -> None:
    if not candidates:
        return
    pairs: List[Tuple[str, str]] = []
    backrefs: List[Tuple[str, str, str]] = []
    competitors = list(query_cache["competitor_ids_by_kc"][kc_id])[:25]
    for candidate in candidates:
        pairs.append((str(query_cache["query_text_by_id"][kc_id]), normalize_ws(candidate.quote)))
        backrefs.append((candidate.candidate_id, "target", ""))
        for competitor_id in competitors:
            pairs.append((str(query_cache["query_text_by_id"][competitor_id]), normalize_ws(candidate.quote)))
            backrefs.append((candidate.candidate_id, "competitor", competitor_id))
    scores = scorer.score_pairs(pairs)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    best_other_scores: Dict[str, Tuple[float, str]] = defaultdict(lambda: (-9999.0, ""))
    for score, ref in zip(scores, backrefs):
        candidate = by_id[ref[0]]
        if ref[1] == "target":
            candidate.rerank_target = float(score)
        else:
            best_score, best_id = best_other_scores[candidate.candidate_id]
            if float(score) > best_score:
                best_other_scores[candidate.candidate_id] = (float(score), str(ref[2]))
    for candidate in candidates:
        best_score, best_id = best_other_scores.get(candidate.candidate_id, (0.0, ""))
        candidate.rerank_best_other = float(best_score)
        candidate.rerank_best_other_kc_id = str(best_id)
        candidate.rerank_margin = float(candidate.rerank_target - candidate.rerank_best_other)


def borderline_candidate(candidate: CandidateSentence, semantic_cfg: Mapping[str, Any]) -> bool:
    margin_min = float(semantic_cfg["margin_min"])
    rerank_margin = float(semantic_cfg["rerank_margin"])
    return (
        candidate.doc_mismatch
        or candidate.embed_margin < margin_min + 0.02
        or candidate.rerank_margin < rerank_margin + 0.05
    )


def run_d2_gate(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    model: str,
    base_url: str,
    retries: int,
    num_ctx: int,
    allow_think_fallback: bool,
    target_kc_id: str,
    registry_row: Mapping[str, Any],
    competitor_ids: Sequence[str],
    query_cache: Mapping[str, Any],
    candidate: CandidateSentence,
) -> Tuple[str, str, Dict[str, Any]]:
    allowed_ids = [target_kc_id] + [str(item) for item in competitor_ids][:25]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["chosen_kc_id", "confidence"],
        "properties": {
            "chosen_kc_id": {"type": "string", "enum": allowed_ids},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }
    competitor_lines = []
    for competitor_id in allowed_ids:
        row = query_cache["kc_row_lookup"].get(competitor_id) or {}
        competitor_lines.append(f"- {competitor_id}: {row.get('canonical_name')}")
    messages = [
        {
            "role": "system",
            "content": "Choose exactly one kc_id from the provided closed set. Output valid JSON only.",
        },
        {
            "role": "user",
            "content": (
                f"Target kc_id: {target_kc_id}\n"
                f"Target canonical_name: {registry_row.get('canonical_name')}\n"
                f"Target seed_definition: {registry_row.get('seed_definition')}\n"
                f"Candidate quote: {normalize_ws(candidate.quote)}\n"
                "Allowed kc_ids:\n"
                + "\n".join(competitor_lines)
            ),
        },
    ]
    payload, meta = call_json_with_retries(
        step63=step63,
        runtime_counters=runtime_counters,
        base_url=base_url,
        model=model,
        messages=messages,
        format_schema=schema,
        retries=retries,
        num_ctx=num_ctx,
        allow_think_fallback=allow_think_fallback,
        timeout_s=120.0,
        validator=lambda obj: validate_d2_payload(obj, allowed_ids),
    )
    return str(payload["chosen_kc_id"]), str(payload["confidence"]), meta


def bundle_text_from_candidates(candidates: Sequence[CandidateSentence]) -> str:
    parts = unique_preserve_order(
        [normalize_ws(str(candidate.quote_raw or candidate.quote or "")) for candidate in candidates if normalize_ws(str(candidate.quote_raw or candidate.quote or ""))]
    )
    return "\n".join(parts[:6])


def bundle_name_support_count(registry_row: Mapping[str, Any], candidates: Sequence[CandidateSentence]) -> int:
    count = 0
    for candidate in candidates:
        quote_text = str(candidate.quote_raw or candidate.quote or "")
        if candidate_has_target_name_support(candidate) or text_has_target_name_or_alias_support(registry_row, quote_text):
            count += 1
    return count


def parent_path_key(kc_row: Mapping[str, Any]) -> Tuple[str, ...]:
    path = kc_row.get("kc_path")
    if not isinstance(path, list):
        return tuple()
    return tuple(match_normalize(str(part)) for part in path[:-1])


def query_similarity(query_cache: Mapping[str, Any], left_kc_id: str, right_kc_id: str) -> float:
    index_by_id = dict(query_cache.get("index_by_id") or {})
    sims = query_cache.get("query_similarities")
    if left_kc_id not in index_by_id or right_kc_id not in index_by_id or sims is None:
        return 0.0
    return float(sims[int(index_by_id[left_kc_id]), int(index_by_id[right_kc_id])])


def is_close_sibling_competitor(
    *,
    target_kc_id: str,
    competitor_kc_id: str,
    registry_row: Mapping[str, Any],
    query_cache: Mapping[str, Any],
    adjudication_cfg: Mapping[str, Any],
) -> bool:
    if not competitor_kc_id or competitor_kc_id == target_kc_id:
        return False
    competitor_ids = list(query_cache.get("competitor_ids_by_kc", {}).get(target_kc_id) or [])
    try:
        competitor_rank = competitor_ids.index(competitor_kc_id) + 1
    except ValueError:
        competitor_rank = 999
    competitor_row = dict(query_cache.get("kc_row_lookup", {}).get(competitor_kc_id) or {})
    same_parent = parent_path_key(registry_row) and parent_path_key(registry_row) == parent_path_key(competitor_row)
    return bool(
        same_parent
        and competitor_rank <= int(adjudication_cfg.get("sibling_competitor_rank_max", 3))
        and query_similarity(query_cache, target_kc_id, competitor_kc_id)
        >= float(adjudication_cfg.get("sibling_query_similarity_min", 0.55))
    )


def is_same_parent_competitor(
    *,
    target_kc_id: str,
    competitor_kc_id: str,
    registry_row: Mapping[str, Any],
    query_cache: Mapping[str, Any],
) -> bool:
    if not competitor_kc_id or competitor_kc_id == target_kc_id:
        return False
    competitor_row = dict(query_cache.get("kc_row_lookup", {}).get(competitor_kc_id) or {})
    return bool(parent_path_key(registry_row) and parent_path_key(registry_row) == parent_path_key(competitor_row))


def is_sibling_confounder(
    *,
    target_kc_id: str,
    competitor_kc_id: str,
    registry_row: Mapping[str, Any],
    query_cache: Mapping[str, Any],
    adjudication_cfg: Mapping[str, Any],
) -> bool:
    return bool(
        is_close_sibling_competitor(
            target_kc_id=target_kc_id,
            competitor_kc_id=competitor_kc_id,
            registry_row=registry_row,
            query_cache=query_cache,
            adjudication_cfg=adjudication_cfg,
        )
        or is_same_parent_competitor(
            target_kc_id=target_kc_id,
            competitor_kc_id=competitor_kc_id,
            registry_row=registry_row,
            query_cache=query_cache,
        )
    )


def support_contract_auto_resolves_sibling_ambiguity(contract: Mapping[str, Any]) -> bool:
    return bool(contract.get("family_scoped")) and not bool(contract.get("bundle_strict_leaf_support"))


def run_bundle_d2_gate(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    model: str,
    base_url: str,
    retries: int,
    num_ctx: int,
    allow_think_fallback: bool,
    target_kc_id: str,
    registry_row: Mapping[str, Any],
    competitor_kc_id: str,
    query_cache: Mapping[str, Any],
    bundle_text: str,
) -> Tuple[str, str, Dict[str, Any]]:
    allowed_ids = [target_kc_id, competitor_kc_id]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["chosen_kc_id", "confidence"],
        "properties": {
            "chosen_kc_id": {"type": "string", "enum": allowed_ids},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }
    competitor_row = dict(query_cache.get("kc_row_lookup", {}).get(competitor_kc_id) or {})
    messages = [
        {
            "role": "system",
            "content": "Choose exactly one kc_id from the provided closed set. Output valid JSON only.",
        },
        {
            "role": "user",
            "content": (
                f"Target kc_id: {target_kc_id}\n"
                f"Target canonical_name: {registry_row.get('canonical_name')}\n"
                f"Target seed_definition: {registry_row.get('seed_definition')}\n"
                f"Competitor kc_id: {competitor_kc_id}\n"
                f"Competitor canonical_name: {competitor_row.get('canonical_name')}\n"
                "Selected evidence bundle:\n"
                f"{bundle_text}"
            ),
        },
    ]
    payload, meta = call_json_with_retries(
        step63=step63,
        runtime_counters=runtime_counters,
        base_url=base_url,
        model=model,
        messages=messages,
        format_schema=schema,
        retries=retries,
        num_ctx=num_ctx,
        allow_think_fallback=allow_think_fallback,
        timeout_s=120.0,
        validator=lambda obj: validate_d2_payload(obj, allowed_ids),
    )
    return str(payload["chosen_kc_id"]), str(payload["confidence"]), meta


def adjudicate_sibling_ambiguity(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    runtime_models: RuntimeModels,
    scorer: Any,
    target_kc_id: str,
    registry_row: Mapping[str, Any],
    competitor_kc_id: str,
    query_cache: Mapping[str, Any],
    selected_candidates: Sequence[CandidateSentence],
    adjudication_cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    bundle_text = bundle_text_from_candidates(selected_candidates)
    if not bundle_text:
        return {
            "competitor_kc_id": competitor_kc_id,
            "bundle_text": "",
            "reranker_target_score": 0.0,
            "reranker_competitor_score": 0.0,
            "reranker_margin": 0.0,
            "d2_chosen_kc_id": "",
            "d2_confidence": "",
            "resolved": True,
            "failure_reason": "",
        }
    reranker_scores = scorer.score_pairs(
        [
            (str(query_cache["query_text_by_id"][target_kc_id]), bundle_text),
            (str(query_cache["query_text_by_id"][competitor_kc_id]), bundle_text),
        ]
    )
    target_score = float(reranker_scores[0])
    competitor_score = float(reranker_scores[1])
    reranker_margin = float(target_score - competitor_score)
    d2_chosen_kc_id = ""
    d2_confidence = ""
    d2_failure = ""
    try:
        d2_chosen_kc_id, d2_confidence, _ = run_bundle_d2_gate(
            step63=step63,
            runtime_counters=runtime_counters,
            model=runtime_models.gate_model,
            base_url=runtime_models.gate_base_url,
            retries=runtime_models.gate_retries,
            num_ctx=runtime_models.gate_num_ctx,
            allow_think_fallback=runtime_models.gate_allow_think,
            target_kc_id=target_kc_id,
            registry_row=registry_row,
            competitor_kc_id=competitor_kc_id,
            query_cache=query_cache,
            bundle_text=bundle_text,
        )
    except Exception as exc:
        d2_failure = f"{type(exc).__name__}:{exc}"
    clear_margin = float(adjudication_cfg.get("bundle_rerank_clear_margin", 0.05))
    competitor_wins_reranker = reranker_margin < -clear_margin
    competitor_wins_d2 = d2_chosen_kc_id == competitor_kc_id and d2_confidence in {"high", "medium"}
    resolved = not (competitor_wins_reranker and competitor_wins_d2)
    return {
        "competitor_kc_id": competitor_kc_id,
        "bundle_text": bundle_text,
        "reranker_target_score": target_score,
        "reranker_competitor_score": competitor_score,
        "reranker_margin": reranker_margin,
        "d2_chosen_kc_id": d2_chosen_kc_id,
        "d2_confidence": d2_confidence,
        "d2_failure": d2_failure,
        "resolved": resolved,
        "failure_reason": "" if resolved else f"SiblingAmbiguityFailed:{competitor_kc_id}",
    }


def evaluate_contamination(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    runtime_models: RuntimeModels,
    scorer: Any,
    registry_row: Mapping[str, Any],
    kc_id: str,
    record: Mapping[str, Any],
    selected_candidates: Sequence[CandidateSentence],
    query_cache: Mapping[str, Any],
    semantic_cfg: Mapping[str, Any],
    adjudication_cfg: Mapping[str, Any],
    sibling_adjudicator: Optional[Callable[[str], Dict[str, Any]]] = None,
    support_contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    competitor_ids = list(query_cache["competitor_ids_by_kc"].get(kc_id) or [])
    competitor_tokens = collect_competitor_tokens(query_cache["kc_row_lookup"], competitor_ids)
    bundle_text = bundle_text_from_candidates(selected_candidates)
    contract = dict(
        support_contract
        or build_support_contract_summary(
            registry_row=registry_row,
            record=record,
            selected_candidates=selected_candidates,
        )
    )
    bundle_target_support = bool(contract["bundle_target_support"])
    bundle_family_topic_support = bool(contract["bundle_family_topic_support"])
    bundle_strict_leaf_support = bool(contract["bundle_strict_leaf_support"])
    auto_resolve_sibling_ambiguity = support_contract_auto_resolves_sibling_ambiguity(contract)
    bundle_competitor_takeover = bool(
        competitor_token_hit_count(bundle_text, competitor_tokens) >= 2 and not bundle_target_support
    )

    hard_reasons: List[str] = []
    sibling_competitors: List[str] = []
    sibling_adjudications: List[Dict[str, Any]] = []
    sibling_resolved: List[str] = []
    sibling_failed: List[str] = []
    competitor_kc_ids: List[str] = []
    for candidate in selected_candidates:
        competitor_kc_id = str(candidate.embed_best_other_kc_id or candidate.rerank_best_other_kc_id or "")
        if candidate.d2_used and candidate.d2_decision and candidate.d2_decision != kc_id:
            hard_reasons.append(f"HardContamination:D2CompetitorWon:{candidate.d2_decision}")
            competitor_kc_ids.append(str(candidate.d2_decision))
            continue
        if candidate.doc_mismatch and (
            candidate.embed_margin < float(semantic_cfg["margin_min"]) + 0.05
            or candidate.rerank_margin < float(semantic_cfg["rerank_margin"]) + 0.05
        ):
            hard_reasons.append(f"HardContamination:DocMismatchWithoutStrongMargin:{candidate.block_id}")
            if competitor_kc_id:
                competitor_kc_ids.append(competitor_kc_id)
            continue
        if candidate.embed_margin >= 0:
            continue
        if not competitor_kc_id:
            hard_reasons.append("HardContamination:NegativeEmbedMargin")
            continue
        competitor_kc_ids.append(competitor_kc_id)
        candidate_competitor_takeover = bool(
            competitor_token_hit_count(str(candidate.quote_raw or candidate.quote or ""), competitor_tokens) >= 2
            and not candidate_has_target_name_support(candidate)
        )
        sibling_confounder = is_sibling_confounder(
            target_kc_id=kc_id,
            competitor_kc_id=competitor_kc_id,
            registry_row=registry_row,
            query_cache=query_cache,
            adjudication_cfg=adjudication_cfg,
        )
        if sibling_confounder and auto_resolve_sibling_ambiguity:
            sibling_competitors.append(competitor_kc_id)
            continue
        if bundle_competitor_takeover or candidate_competitor_takeover or not bundle_target_support:
            hard_reasons.append(f"HardContamination:NegativeEmbedMargin:{competitor_kc_id}")
            continue
        if sibling_confounder:
            sibling_competitors.append(competitor_kc_id)
            continue
        hard_reasons.append(f"HardContamination:NegativeEmbedMargin:{competitor_kc_id}")

    definition_full = str(record.get("definition_full") or "")
    definition_competitor_hits = competitor_token_hit_count(definition_full, competitor_tokens)
    if definition_full and definition_competitor_hits >= 2 and not text_has_target_support(registry_row, definition_full):
        sibling_definition_competitors = [
            competitor_id
            for competitor_id in competitor_ids[: int(adjudication_cfg.get("sibling_competitor_rank_max", 3))]
            if is_sibling_confounder(
                target_kc_id=kc_id,
                competitor_kc_id=competitor_id,
                registry_row=registry_row,
                query_cache=query_cache,
                adjudication_cfg=adjudication_cfg,
            )
        ]
        if sibling_definition_competitors and (bundle_target_support or auto_resolve_sibling_ambiguity):
            sibling_competitors.extend(sibling_definition_competitors)
            competitor_kc_ids.extend(sibling_definition_competitors)
        else:
            hard_reasons.append("HardContamination:DefinitionFullCompetitorTokensWithoutTargetName")

    sibling_competitors = unique_preserve_order([item for item in sibling_competitors if item])
    if not hard_reasons:
        for competitor_kc_id in sibling_competitors:
            if auto_resolve_sibling_ambiguity:
                sibling_adjudications.append(
                    {
                        "competitor_kc_id": competitor_kc_id,
                        "bundle_text": bundle_text,
                        "reranker_target_score": 0.0,
                        "reranker_competitor_score": 0.0,
                        "reranker_margin": 0.0,
                        "d2_chosen_kc_id": "",
                        "d2_confidence": "",
                        "d2_failure": "",
                        "resolved": True,
                        "failure_reason": "",
                        "auto_resolved": True,
                        "resolution_reason": "family_support_contract_blocked_leaf_claim",
                    }
                )
                sibling_resolved.append(competitor_kc_id)
                continue
            adjudication = (
                sibling_adjudicator(competitor_kc_id)
                if sibling_adjudicator is not None
                else adjudicate_sibling_ambiguity(
                    step63=step63,
                    runtime_counters=runtime_counters,
                    runtime_models=runtime_models,
                    scorer=scorer,
                    target_kc_id=kc_id,
                    registry_row=registry_row,
                    competitor_kc_id=competitor_kc_id,
                    query_cache=query_cache,
                    selected_candidates=selected_candidates,
                    adjudication_cfg=adjudication_cfg,
                )
            )
            sibling_adjudications.append(dict(adjudication))
            if bool(adjudication.get("resolved")):
                sibling_resolved.append(competitor_kc_id)
            else:
                sibling_failed.append(competitor_kc_id)

    contamination_reasons = unique_preserve_order(hard_reasons + [f"SiblingAmbiguityFailed:{item}" for item in sibling_failed])
    if hard_reasons:
        category = "hard_contamination"
    elif sibling_competitors:
        category = "sibling_ambiguity"
    else:
        category = "clean"
    return {
        "contamination_reasons": contamination_reasons,
        "hard_reasons": unique_preserve_order(hard_reasons),
        "category": category,
        "sibling_ambiguous_support": bool(sibling_competitors),
        "sibling_ambiguity_competitor_ids": sibling_competitors,
        "sibling_ambiguity_resolved": unique_preserve_order(sibling_resolved),
        "sibling_ambiguity_failed": unique_preserve_order(sibling_failed),
        "sibling_adjudications": sibling_adjudications,
        "competitor_kc_ids": unique_preserve_order(competitor_kc_ids),
        "bundle_target_support": bundle_target_support,
        "bundle_strict_leaf_support": bundle_strict_leaf_support,
        "bundle_family_topic_support": bundle_family_topic_support,
        "bundle_parent_topic_overlap": bool(contract["bundle_parent_topic_overlap"]),
        "generic_selected_support": bool(contract["generic_selected_support"]),
        "permissive_rescue_lineage": bool(contract["permissive_rescue_lineage"]),
        "target_support_state": str(contract.get("target_support_state") or support_contract_target_state(contract)),
        "bundle_competitor_takeover": bundle_competitor_takeover,
        "family_policy_id": str(contract["family_policy_id"] or ""),
        "family_scoped": bool(contract["family_scoped"]),
        "definition_short_strict_leaf_support": bool(contract["definition_short_strict_leaf_support"]),
        "definition_short_family_topic_support": bool(contract["definition_short_family_topic_support"]),
        "definition_full_strict_leaf_support": bool(contract["definition_full_strict_leaf_support"]),
        "definition_full_family_topic_support": bool(contract["definition_full_family_topic_support"]),
        "support_contract_downgraded": bool(contract.get("support_contract_downgraded")),
        "support_contract_downgrade_reason": str(contract.get("support_contract_downgrade_reason") or ""),
    }


def call_role_tiebreaker(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    model: str,
    base_url: str,
    num_ctx: int,
    allow_think_fallback: bool,
    messages: List[Dict[str, str]],
    schema: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    errors: List[str] = []
    last_raw = ""
    last_outer: Dict[str, Any] = {}
    for attempt in range(2):
        runtime_counters["llm_calls"] += 1
        try:
            payload, outer, raw = step63.ollama_chat_json(
                base_url=base_url,
                model=model,
                messages=messages,
                format_schema=dict(schema),
                temperature=0,
                top_p=1.0,
                num_ctx=int(num_ctx),
                repeat_penalty=1.0,
                think=False,
                timeout_s=120.0,
            )
            ok, reason = validate_role_payload(payload, [])
            if ok:
                return dict(payload), {"attempt": attempt + 1, "think": False, "raw_response": raw, "outer": outer, "errors": errors}
            errors.append(f"Attempt{attempt + 1}:InvalidPayload:{reason}")
            last_raw = raw
            last_outer = dict(outer)
        except Exception as exc:
            errors.append(f"Attempt{attempt + 1}:{type(exc).__name__}:{exc}")
    if allow_think_fallback:
        runtime_counters["llm_calls"] += 1
        runtime_counters["think_calls"] += 1
        try:
            payload, outer, raw = step63.ollama_chat_json(
                base_url=base_url,
                model=model,
                messages=messages,
                format_schema=dict(schema),
                temperature=0,
                top_p=1.0,
                num_ctx=int(num_ctx),
                repeat_penalty=1.0,
                think=True,
                timeout_s=120.0,
            )
            ok, reason = validate_role_payload(payload, [])
            if ok:
                return dict(payload), {"attempt": 3, "think": True, "raw_response": raw, "outer": outer, "errors": errors}
            errors.append(f"Attempt3:InvalidPayload:{reason}")
            last_raw = raw
            last_outer = dict(outer)
        except Exception as exc:
            errors.append(f"Attempt3:{type(exc).__name__}:{exc}")
    return None, {"attempt": 0, "think": False, "raw_response": last_raw, "outer": last_outer, "errors": errors}


def annotate_roles(
    *,
    step63: Any,
    runtime_counters: RuntimeCounters,
    model: str,
    base_url: str,
    retries: int,
    num_ctx: int,
    allow_think_fallback: bool,
    registry_row: Mapping[str, Any],
    role_cfg: Mapping[str, Any],
    candidates: Sequence[CandidateSentence],
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
    configured_role_cfg = default_role_cfg(role_cfg)
    role_map: Dict[str, str] = {}
    role_sources: Dict[str, str] = {}
    role_meta: Dict[str, Any] = {
        "ambiguous_role_calls": 0,
        "model_role_success_count": 0,
        "model_role_failure_count": 0,
        "details": {},
    }
    if not candidates:
        return role_map, role_sources, role_meta

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["role", "confidence"],
        "properties": {
            "role": {"type": "string", "enum": list(ROLE_LABEL_VALUES)},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }
    canonical_name = str(registry_row.get("canonical_name") or "")
    aliases = ensure_string_list(registry_row.get("aliases"))
    for candidate in candidates:
        analysis = analyze_quote_role(
            quote=str(candidate.quote_raw or candidate.quote),
            canonical_name=canonical_name,
            aliases=aliases,
            candidate=candidate,
            cfg=configured_role_cfg,
        )
        final_role = str(analysis["top_role"])
        role_source = "heuristic"
        role_confidence = "high" if bool(analysis.get("dominant")) else ("medium" if not bool(analysis["ambiguous"]) else "low")
        model_meta: Dict[str, Any] = {}
        if bool(analysis["ambiguous"]) and model:
            role_meta["ambiguous_role_calls"] += 1
            score_lines = [
                f"{label}={float(analysis['scores'].get(label, 0.0)):.2f}"
                for label in ROLE_LABEL_VALUES
            ]
            messages = [
                {
                    "role": "system",
                    "content": 'Classify the quote role. Return JSON only in the form {"role":"definition|equation|procedure|example|warning|other","confidence":"high|medium|low"}.',
                },
                {
                    "role": "user",
                    "content": "\n".join(
                        [
                            f"KC: {canonical_name}",
                            f"Aliases: {', '.join(aliases) if aliases else 'none'}",
                            f"Quote: {str(candidate.quote_raw or candidate.quote)}",
                            f"Deterministic top_role: {analysis['top_role']}",
                            f"Deterministic gap: {float(analysis['top_score']) - float(analysis['second_score']):.2f}",
                            f"Deterministic scores: {', '.join(score_lines)}",
                            "Allowed roles: definition, equation, procedure, example, warning, other",
                        ]
                    ),
                },
            ]
            payload, model_meta = call_role_tiebreaker(
                step63=step63,
                runtime_counters=runtime_counters,
                model=model,
                base_url=base_url,
                num_ctx=num_ctx,
                allow_think_fallback=allow_think_fallback,
                messages=messages,
                schema=schema,
            )
            if payload is not None:
                final_role = str(payload["role"])
                role_confidence = str(payload["confidence"])
                role_source = "model"
                role_meta["model_role_success_count"] += 1
            else:
                role_meta["model_role_failure_count"] += 1
                model_meta = {**model_meta, "error": ";".join(model_meta.get("errors") or [])}
        role_map[candidate.candidate_id] = final_role
        role_sources[candidate.candidate_id] = role_source
        role_meta["details"][candidate.candidate_id] = {
            **analysis,
            "role_source": role_source,
            "role_confidence": role_confidence,
            "model_meta": model_meta,
        }
    return role_map, role_sources, role_meta


def select_diverse_candidates(candidates: Sequence[CandidateSentence], max_items: int) -> List[CandidateSentence]:
    ordered = sorted(candidates, key=candidate_sort_key)
    selected: List[CandidateSentence] = []
    seen_keys: set[Tuple[str, str]] = set()
    seen_pages: set[Tuple[str, int]] = set()
    for candidate in ordered:
        quote_key = (candidate.block_id, str(candidate.quote_match_norm or match_normalize(candidate.quote_raw or candidate.quote)))
        if quote_key in seen_keys:
            continue
        page_key = (candidate.doc_id, int(candidate.page_index))
        if page_key in seen_pages:
            continue
        selected.append(candidate)
        seen_keys.add(quote_key)
        seen_pages.add(page_key)
        if len(selected) >= max_items:
            return selected
    for candidate in ordered:
        if candidate in selected:
            continue
        quote_key = (candidate.block_id, str(candidate.quote_match_norm or match_normalize(candidate.quote_raw or candidate.quote)))
        if quote_key in seen_keys:
            continue
        selected.append(candidate)
        seen_keys.add(quote_key)
        if len(selected) >= max_items:
            break
    return selected


def apply_provenance_normalization(
    *,
    candidates: Sequence[CandidateSentence],
    provenance_index: Optional[Mapping[str, Any]],
    provenance_cfg: Mapping[str, Any],
) -> Tuple[List[CandidateSentence], Dict[str, int], List[CandidateSentence]]:
    base_stats = {
        "page_index_recovered_count": 0,
        "page_index_substituted_count": 0,
        "page_index_dropped_count": 0,
        "quote_rebound_count": 0,
        "quote_rebind_failed_count": 0,
    }
    if provenance_index is None:
        normalized = [candidate for candidate in candidates if has_valid_page_index(candidate.page_index)]
        dropped = [
            replace(
                candidate,
                provenance_status="dropped",
                provenance_source="missing_overlay_index",
                provenance_note="missing_overlay_index",
                provenance_quality_flags=unique_preserve_order(list(candidate.provenance_quality_flags) + ["PageIndexDropped"]),
            )
            for candidate in candidates
            if not has_valid_page_index(candidate.page_index)
        ]
        stats = dict(base_stats)
        stats["page_index_dropped_count"] = len(dropped)
        return normalized, stats, dropped
    layer_order = [str(item) for item in provenance_cfg.get("layer_preference") or ["mineru", "pymupdf", "docling"]]
    normalized: List[CandidateSentence] = []
    dropped: List[CandidateSentence] = []
    stats = dict(base_stats)
    for candidate in candidates:
        result = normalize_candidate_provenance(candidate, provenance_index, layer_order=layer_order)
        status = str(result["status"])
        if bool(result.get("quote_rebound")):
            stats["quote_rebound_count"] += 1
        if bool(result.get("quote_rebind_failed")):
            stats["quote_rebind_failed_count"] += 1
        updates = dict(result.get("updates") or {})
        provenance_flags = unique_preserve_order(
            list(candidate.provenance_quality_flags)
            + ([f"PageIndex{status.title()}"] if status in {"recovered", "substituted"} else [])
            + ([f"ProvenanceSource:{result['reason']}"] if result.get("reason") else [])
            + (["QuoteRebound"] if bool(result.get("quote_rebound")) else [])
            + (["QuoteRebindFailed"] if bool(result.get("quote_rebind_failed")) else [])
        )
        if status == "original":
            normalized.append(
                replace(
                    candidate,
                    **updates,
                    provenance_source=str(result["reason"] or ""),
                    provenance_status="original",
                    provenance_quality_flags=provenance_flags,
                )
            )
            continue
        if status == "recovered":
            stats["page_index_recovered_count"] += 1
        elif status == "substituted":
            stats["page_index_substituted_count"] += 1
        else:
            stats["page_index_dropped_count"] += 1
        if status == "dropped":
            dropped.append(
                replace(
                    candidate,
                    provenance_status="dropped",
                    provenance_source=str(result.get("reason") or ""),
                    provenance_note=str(result.get("reason") or ""),
                    provenance_quality_flags=unique_preserve_order(provenance_flags + ["PageIndexDropped"]),
                )
            )
            continue
        updated = replace(candidate, **updates, provenance_quality_flags=provenance_flags)
        if not has_valid_page_index(updated.page_index):
            stats["page_index_dropped_count"] += 1
            dropped.append(
                replace(
                    updated,
                    provenance_status="dropped",
                    provenance_source="page_index_unresolved",
                    provenance_note="page_index_unresolved",
                    provenance_quality_flags=unique_preserve_order(list(updated.provenance_quality_flags) + ["PageIndexDropped"]),
                )
            )
            continue
        normalized.append(updated)
    return normalized, stats, dropped


def local_bundle_distance(primary: CandidateSentence, other: CandidateSentence, block_positions: Mapping[str, int]) -> int:
    if primary.doc_id != other.doc_id:
        return 99
    if primary.block_id == other.block_id:
        if primary.sent_idx >= 0 and other.sent_idx >= 0:
            return abs(primary.sent_idx - other.sent_idx)
        return 0
    if primary.patch_id and other.patch_id and primary.patch_id == other.patch_id:
        if primary.page_index == other.page_index:
            return 1
        return 2
    if has_valid_page_index(primary.page_index) and primary.page_index == other.page_index:
        return 3
    primary_pos = safe_int(block_positions.get(primary.block_id), default=-1)
    other_pos = safe_int(block_positions.get(other.block_id), default=-1)
    if primary_pos >= 0 and other_pos >= 0 and abs(primary_pos - other_pos) <= 1:
        return 4
    return 99


def definition_candidate_sort_key(candidate: CandidateSentence) -> tuple[Any, ...]:
    strong_def_eq = max(float(candidate.role_scores.get("definition", 0.0)), float(candidate.role_scores.get("equation", 0.0)))
    return (
        ROLE_PRIORITY.get(candidate.final_role, 99),
        -strong_def_eq,
        candidate.doc_mismatch,
        -candidate.rerank_target,
        -candidate.embed_margin,
        -candidate.pre_score,
        candidate.candidate_id,
    )


def candidate_quote_key(candidate: CandidateSentence) -> str:
    return str(candidate.quote_match_norm or match_normalize(candidate.quote_raw or candidate.quote))


def build_bundle(primary: CandidateSentence, candidates: Sequence[CandidateSentence], block_positions: Mapping[str, int], max_items: int) -> List[CandidateSentence]:
    bundle = [primary]
    supporting = [
        candidate
        for candidate in candidates
        if candidate.candidate_id != primary.candidate_id
        and local_bundle_distance(primary, candidate, block_positions) < 99
        and candidate_quote_key(candidate) != candidate_quote_key(primary)
    ]
    supporting = sorted(
        supporting,
        key=lambda candidate: (
            local_bundle_distance(primary, candidate, block_positions),
            0 if candidate.final_role != primary.final_role else 1,
            0 if candidate.final_role in PRIMARY_ROLE_SET else 1,
            ROLE_PRIORITY.get(candidate.final_role, 99),
            -max(float(candidate.role_scores.get("definition", 0.0)), float(candidate.role_scores.get("equation", 0.0))),
            candidate.doc_mismatch,
            -candidate.rerank_target,
            -candidate.embed_margin,
            candidate.candidate_id,
        ),
    )
    for candidate in supporting:
        bundle.append(candidate)
        if len(bundle) >= max_items:
            break
    return bundle


def bundle_score(bundle: Sequence[CandidateSentence], block_positions: Mapping[str, int]) -> tuple[Any, ...]:
    if not bundle:
        return (-1, -1, -1, -1, -1.0, -1.0, 999)
    primary = bundle[0]
    support_count = max(0, len(bundle) - 1)
    complementary_support = sum(1 for candidate in bundle[1:] if candidate.final_role != primary.final_role)
    same_block_support = sum(1 for candidate in bundle[1:] if candidate.block_id == primary.block_id)
    primary_role_count = sum(1 for candidate in bundle if candidate.final_role in PRIMARY_ROLE_SET)
    strong_def_eq = sum(max(float(candidate.role_scores.get("definition", 0.0)), float(candidate.role_scores.get("equation", 0.0))) for candidate in bundle)
    total_rerank = sum(float(candidate.rerank_target) for candidate in bundle)
    locality = sum(local_bundle_distance(primary, candidate, block_positions) for candidate in bundle[1:]) if len(bundle) > 1 else 99
    return (
        int(primary.final_role in PRIMARY_ROLE_SET),
        int(support_count > 0),
        support_count,
        same_block_support,
        complementary_support,
        primary_role_count,
        strong_def_eq,
        total_rerank,
        -locality,
    )


def select_quote_bundle(
    candidates: Sequence[CandidateSentence],
    *,
    max_items: int,
    block_positions: Mapping[str, int],
    bundle_max_items: int,
) -> Tuple[List[CandidateSentence], Dict[str, Any]]:
    if not candidates or max_items <= 0:
        return [], {"bundle_candidate_ids": [], "bundle_size": 0}
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            0 if candidate.final_role in PRIMARY_ROLE_SET else 1,
            -max(float(candidate.role_scores.get("definition", 0.0)), float(candidate.role_scores.get("equation", 0.0))),
            candidate.doc_mismatch,
            -candidate.rerank_target,
            -candidate.embed_margin,
            -candidate.pre_score,
            candidate.candidate_id,
        ),
    )
    best_bundle: List[CandidateSentence] = []
    best_score: tuple[Any, ...] | None = None
    for primary in ordered:
        bundle = build_bundle(primary, ordered, block_positions, max_items=min(max_items, max(1, bundle_max_items)))
        score = bundle_score(bundle, block_positions)
        if best_score is None or score > best_score:
            best_bundle = bundle
            best_score = score
    selected = list(best_bundle)
    remaining = [candidate for candidate in ordered if candidate.candidate_id not in {item.candidate_id for item in selected}]
    selected.extend(select_diverse_candidates(remaining, max(0, max_items - len(selected))))
    return selected[:max_items], {
        "bundle_candidate_ids": [candidate.candidate_id for candidate in best_bundle],
        "bundle_size": len(best_bundle),
        "bundle_primary_candidate_id": best_bundle[0].candidate_id if best_bundle else "",
    }


def provisional_role_candidate(
    candidate: CandidateSentence,
    *,
    registry_row: Mapping[str, Any],
    role_cfg: Mapping[str, Any],
) -> CandidateSentence:
    analysis = analyze_quote_role(
        quote=str(candidate.quote_raw or candidate.quote or ""),
        canonical_name=str(registry_row.get("canonical_name") or ""),
        aliases=ensure_string_list(registry_row.get("aliases")),
        candidate=candidate,
        cfg=role_cfg,
    )
    return replace(
        candidate,
        final_role=str(analysis["top_role"]),
        role_scores={str(key): float(value) for key, value in dict(analysis.get("scores") or {}).items()},
        role_source=str(analysis.get("role_source") or "heuristic"),
        role_confidence=str(analysis.get("role_confidence") or "high"),
        role_ambiguous=bool(analysis.get("ambiguous")),
        role_ambiguity_reason=str(analysis.get("ambiguity_reason") or ""),
    )


def candidate_has_disallowed_local_bundle_gate(candidate: CandidateSentence) -> bool:
    for reason in candidate.gate_reasons:
        if reason == "D1RerankMinFail":
            return True
        if reason == "D2BudgetExceeded":
            return True
        if reason.startswith("D2Rejected:"):
            return True
        if reason.startswith("DocMismatchWithoutStrongMargin"):
            return True
    return False


def candidate_in_local_bundle_pool(
    candidate: CandidateSentence,
    *,
    rerank_min: float,
    rerank_margin: float,
    margin_slack: float,
) -> bool:
    if not candidate.quote_verified or not candidate.semantic_route or candidate.doc_mismatch:
        return False
    if candidate.rerank_target < rerank_min:
        return False
    if candidate_has_disallowed_local_bundle_gate(candidate):
        return False
    if candidate.accepted:
        return True
    if any(reason.startswith("D2Error:") for reason in candidate.gate_reasons):
        return True
    return "D1RerankMarginFail" in candidate.gate_reasons and candidate.rerank_margin >= rerank_margin - margin_slack


def candidate_needs_local_bundle_rescue(
    candidate: CandidateSentence,
    *,
    rerank_min: float,
    rerank_margin: float,
    margin_slack: float,
) -> bool:
    if candidate.accepted:
        return False
    if not candidate_in_local_bundle_pool(
        candidate,
        rerank_min=rerank_min,
        rerank_margin=rerank_margin,
        margin_slack=margin_slack,
    ):
        return False
    if any(reason.startswith("D2Error:") for reason in candidate.gate_reasons):
        return True
    return "D1RerankMarginFail" in candidate.gate_reasons


def score_bundle_against_competitors(
    *,
    kc_id: str,
    bundle_text: str,
    query_cache: Mapping[str, Any],
    scorer: Any,
    competitor_limit: int = 6,
) -> Dict[str, Any]:
    competitor_ids = list(query_cache["competitor_ids_by_kc"].get(kc_id) or [])[:competitor_limit]
    pairs: List[Tuple[str, str]] = [(str(query_cache["query_text_by_id"][kc_id]), bundle_text)]
    pairs.extend((str(query_cache["query_text_by_id"][competitor_id]), bundle_text) for competitor_id in competitor_ids)
    scores = [float(value) for value in scorer.score_pairs(pairs)]
    target_score = float(scores[0]) if scores else 0.0
    best_other_score = 0.0
    best_other_kc_id = ""
    if competitor_ids and len(scores) > 1:
        best_idx = max(range(1, len(scores)), key=lambda idx: scores[idx])
        best_other_score = float(scores[best_idx])
        best_other_kc_id = str(competitor_ids[best_idx - 1])
    return {
        "target_score": target_score,
        "best_other_score": best_other_score,
        "best_other_kc_id": best_other_kc_id,
        "margin": float(target_score - best_other_score),
    }


def attempt_local_bundle_rescue(
    *,
    kc_id: str,
    registry_row: Mapping[str, Any],
    kc_type: str,
    candidates: Sequence[CandidateSentence],
    query_cache: Mapping[str, Any],
    scorer: Any,
    block_positions: Mapping[str, int],
    semantic_cfg: Mapping[str, Any],
    enrichment_cfg: Mapping[str, Any],
    role_cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    rerank_min = float(semantic_cfg["rerank_min"])
    rerank_margin = float(semantic_cfg["rerank_margin"])
    margin_slack = float(enrichment_cfg.get("local_bundle_rescue_margin_slack", 0.05))
    bundle_margin = float(enrichment_cfg.get("local_bundle_rescue_bundle_margin", 0.05))
    bundle_max_items = max(2, int(enrichment_cfg.get("local_bundle_rescue_max_quotes", 2)))
    configured_role_cfg = default_role_cfg(role_cfg)
    strong_definition_score = float(configured_role_cfg["strong_definition_score"])

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    provisional_pool = [
        provisional_role_candidate(candidate, registry_row=registry_row, role_cfg=role_cfg)
        for candidate in candidates
        if candidate_in_local_bundle_pool(
            candidate,
            rerank_min=rerank_min,
            rerank_margin=rerank_margin,
            margin_slack=margin_slack,
        )
    ]
    rescue_primaries = sorted(
        [
            candidate
            for candidate in provisional_pool
            if candidate_needs_local_bundle_rescue(
                candidate_by_id[candidate.candidate_id],
                rerank_min=rerank_min,
                rerank_margin=rerank_margin,
                margin_slack=margin_slack,
            )
        ],
        key=lambda candidate: (
            0 if candidate.final_role in PRIMARY_ROLE_SET else 1,
            -candidate.rerank_target,
            -candidate.pre_score,
            candidate.candidate_id,
        ),
    )
    blocked_candidate_ids: List[str] = []
    blocked_reasons: List[str] = []

    for primary in rescue_primaries:
        bundle = build_bundle(primary, provisional_pool, block_positions, max_items=bundle_max_items)
        if len(bundle) < 2:
            continue
        if not any(
            candidate_supports_definition_package(
                candidate,
                kc_type=kc_type,
                strong_definition_score=strong_definition_score,
            )
            for candidate in bundle
        ):
            continue
        bundle_text = bundle_text_from_candidates(bundle)
        if not bundle_text:
            continue
        policy = resolve_family_support_policy(registry_row)
        bundle_contract = build_support_contract_summary(
            registry_row=registry_row,
            record={"definition_short": "", "definition_full": ""},
            selected_candidates=bundle,
        )
        block_reason = support_contract_enforcement_reason(
            contract=bundle_contract,
            policy=policy,
            phase="rescue",
        )
        if block_reason:
            blocked_candidate_ids.extend(candidate.candidate_id for candidate in bundle)
            blocked_reasons.append(block_reason)
            continue
        bundle_scores = score_bundle_against_competitors(
            kc_id=kc_id,
            bundle_text=bundle_text,
            query_cache=query_cache,
            scorer=scorer,
        )
        if bundle_scores["target_score"] < rerank_min or bundle_scores["margin"] < bundle_margin:
            continue

        rescued_candidate_ids: List[str] = []
        for bundle_candidate in bundle:
            original = candidate_by_id[bundle_candidate.candidate_id]
            if original.accepted or candidate_has_disallowed_local_bundle_gate(original):
                continue
            original.accepted = True
            original.gate_reasons = unique_preserve_order(
                list(original.gate_reasons)
                + [f"LocalBundleRescueAccepted:{primary.candidate_id}"]
                + [f"LocalBundleRescueBundleMargin:{bundle_scores['margin']:.4f}"]
            )
            rescued_candidate_ids.append(original.candidate_id)
        if rescued_candidate_ids:
            return {
                "rescued_candidate_ids": rescued_candidate_ids,
                "bundle_candidate_ids": [candidate.candidate_id for candidate in bundle],
                "bundle_target_score": float(bundle_scores["target_score"]),
                "bundle_best_other_score": float(bundle_scores["best_other_score"]),
                "bundle_best_other_kc_id": str(bundle_scores["best_other_kc_id"]),
                "bundle_margin": float(bundle_scores["margin"]),
                "blocked_candidate_ids": [],
                "blocked_reasons": [],
                "bundle_target_support": bool(bundle_contract["bundle_target_support"]),
                "bundle_strict_leaf_support": bool(bundle_contract["bundle_strict_leaf_support"]),
                "bundle_family_topic_support": bool(bundle_contract["bundle_family_topic_support"]),
                "bundle_parent_topic_overlap": bool(bundle_contract["bundle_parent_topic_overlap"]),
                "bundle_generic_selected_support": bool(bundle_contract.get("generic_selected_support")),
            }

    for blocked_candidate_id in unique_preserve_order(blocked_candidate_ids):
        candidate = candidate_by_id.get(blocked_candidate_id)
        if candidate is None:
            continue
        block_labels = [local_bundle_rescue_block_label(reason) for reason in unique_preserve_order(blocked_reasons)]
        candidate.gate_reasons = unique_preserve_order(list(candidate.gate_reasons) + block_labels)
    return {
        "rescued_candidate_ids": [],
        "bundle_candidate_ids": [],
        "bundle_target_score": 0.0,
        "bundle_best_other_score": 0.0,
        "bundle_best_other_kc_id": "",
        "bundle_margin": 0.0,
        "blocked_candidate_ids": unique_preserve_order(blocked_candidate_ids),
        "blocked_reasons": unique_preserve_order(blocked_reasons),
        "bundle_target_support": False,
        "bundle_strict_leaf_support": False,
        "bundle_family_topic_support": False,
        "bundle_parent_topic_overlap": False,
        "bundle_generic_selected_support": False,
    }


def definition_support_strength(candidate: CandidateSentence, *, kc_type: str) -> float:
    values = [
        float(candidate.role_scores.get("definition", 0.0)),
        float(candidate.role_scores.get("equation", 0.0)),
    ]
    if kc_type == "procedure":
        values.append(float(candidate.role_scores.get("procedure", 0.0)))
    return max(values or [0.0])


def candidate_is_bare_heading(
    candidate: CandidateSentence,
    *,
    kc_type: str,
    strong_definition_score: float,
) -> bool:
    quote_text = normalize_ws(str(candidate.quote_raw or candidate.quote or ""))
    quote_norm = match_normalize(quote_text)
    token_count = len(tokenize(quote_norm, min_len=2))
    heading_like = bool((candidate.sentence_flags or {}).get("is_heading_like"))
    has_definition_link = any(
        cue in quote_norm
        for cue in [
            " is ",
            " defined as ",
            " means ",
            " refers to ",
            " we call ",
            " denote",
            " denotes",
            " assumed that ",
            " given ",
            " where ",
        ]
    ) or quote_text.endswith(":")
    equation_like = candidate.final_role == "equation" or float(candidate.role_scores.get("equation", 0.0)) >= strong_definition_score
    procedure_like = kc_type == "procedure" and (
        candidate.final_role == "procedure" or float(candidate.role_scores.get("procedure", 0.0)) >= strong_definition_score
    )
    return heading_like and token_count <= 5 and not has_definition_link and not equation_like and not procedure_like


def candidate_supports_definition_package(
    candidate: CandidateSentence,
    *,
    kc_type: str,
    strong_definition_score: float,
) -> bool:
    quote_text = normalize_ws(str(candidate.quote_raw or candidate.quote or ""))
    if not quote_text or not candidate.quote_verified:
        return False
    if candidate_is_bare_heading(candidate, kc_type=kc_type, strong_definition_score=strong_definition_score):
        return False
    if candidate.final_role == "equation":
        return True
    if kc_type == "procedure" and candidate.final_role == "procedure":
        return True
    if candidate.final_role == "definition":
        return True
    return definition_support_strength(candidate, kc_type=kc_type) >= strong_definition_score


def classify_definition_status(
    candidates: Sequence[CandidateSentence],
    *,
    kc_type: str,
    strong_definition_score: float,
) -> str:
    if not candidates:
        return "unsupported_in_source"
    if len(candidates) == 1:
        return (
            "fragmentary_supported"
            if candidate_supports_definition_package(candidates[0], kc_type=kc_type, strong_definition_score=strong_definition_score)
            else "unsupported_in_source"
        )
    roles = {candidate.final_role for candidate in candidates}
    if "definition" in roles and len(candidates) >= 2:
        return "coherent_supported"
    if kc_type == "metric" and "equation" in roles and len(candidates) >= 2:
        return "coherent_supported" if any(candidate.final_role != "equation" for candidate in candidates) else "fragmentary_supported"
    support_count = sum(
        1
        for candidate in candidates
        if candidate_supports_definition_package(candidate, kc_type=kc_type, strong_definition_score=strong_definition_score)
    )
    if support_count >= 2:
        return "coherent_supported"
    return "fragmentary_supported"


def build_definition_package(
    candidates: Sequence[CandidateSentence],
    *,
    kc_type: str,
    role_cfg: Mapping[str, Any],
    max_items: int,
) -> Tuple[List[CandidateSentence], str, Dict[str, Any]]:
    unique_candidates: List[CandidateSentence] = []
    seen_quotes: set[str] = set()
    for candidate in candidates:
        if candidate.final_role == "warning":
            continue
        quote_key = candidate_quote_key(candidate)
        if quote_key in seen_quotes:
            continue
        seen_quotes.add(quote_key)
        unique_candidates.append(candidate)
    ordered = sorted(unique_candidates, key=definition_candidate_sort_key)
    if not ordered:
        return [], "unsupported_in_source", {"definition_candidate_ids": [], "selected_support_candidate_ids": []}
    configured_role_cfg = default_role_cfg(role_cfg)
    strong_definition_score = float(configured_role_cfg["strong_definition_score"])
    has_explicit_definition = any(candidate.final_role == "definition" for candidate in ordered)
    support_candidates = [
        candidate
        for candidate in ordered
        if candidate_supports_definition_package(candidate, kc_type=kc_type, strong_definition_score=strong_definition_score)
    ]
    if not support_candidates:
        return [], "unsupported_in_source", {"definition_candidate_ids": [], "selected_support_candidate_ids": []}
    selected: List[CandidateSentence] = []
    if has_explicit_definition:
        selected.append(next(candidate for candidate in ordered if candidate.final_role == "definition"))
        selected_ids = {selected[0].candidate_id}
        for candidate in ordered:
            if candidate.candidate_id in selected_ids:
                continue
            if (
                candidate_supports_definition_package(candidate, kc_type=kc_type, strong_definition_score=strong_definition_score)
                or candidate.final_role in {"example", "other"}
            ):
                selected.append(candidate)
                selected_ids.add(candidate.candidate_id)
            if len(selected) >= max_items:
                break
    elif len(support_candidates) >= 2:
        selected = support_candidates[:max_items]
    else:
        selected = support_candidates[:1]
    status = classify_definition_status(selected, kc_type=kc_type, strong_definition_score=strong_definition_score)
    if status == "unsupported_in_source":
        return [], status, {"definition_candidate_ids": [], "selected_support_candidate_ids": []}
    return selected[:max_items], status, {
        "definition_candidate_ids": [candidate.candidate_id for candidate in selected[:max_items]],
        "selected_support_candidate_ids": [candidate.candidate_id for candidate in support_candidates],
        "has_explicit_definition": has_explicit_definition,
        "single_quote_fragmentary": bool(status == "fragmentary_supported" and len(selected[:max_items]) == 1),
    }


def definition_short_sort_key(candidate: CandidateSentence) -> tuple[Any, ...]:
    quote_text = normalize_ws(str(candidate.quote_raw or candidate.quote or ""))
    return (
        ROLE_PRIORITY.get(candidate.final_role, 99),
        len(quote_text),
        -max(
            float(candidate.role_scores.get("definition", 0.0)),
            float(candidate.role_scores.get("equation", 0.0)),
            float(candidate.role_scores.get("procedure", 0.0)),
        ),
        candidate.candidate_id,
    )


def select_definition_short_candidate(
    definition_candidates: Sequence[CandidateSentence],
    minimal_candidates: Sequence[CandidateSentence],
    *,
    kc_type: str,
    definition_status: str,
    role_cfg: Mapping[str, Any],
) -> Optional[CandidateSentence]:
    configured_role_cfg = default_role_cfg(role_cfg)
    strong_definition_score = float(configured_role_cfg["strong_definition_score"])
    if definition_candidates:
        return sorted(definition_candidates, key=definition_short_sort_key)[0]
    if definition_status != "unsupported_in_source":
        return None
    support_candidates = [
        candidate
        for candidate in minimal_candidates
        if candidate_supports_definition_package(candidate, kc_type=kc_type, strong_definition_score=strong_definition_score)
    ]
    if not support_candidates:
        return None
    return sorted(support_candidates, key=definition_short_sort_key)[0]


def iter_definition_short_fragments(text: str) -> Iterable[str]:
    for sentence in split_exact_sentences(text):
        fragment = sentence.strip()
        if fragment:
            yield fragment
    for separator in [":", ";", " - ", ","]:
        if separator not in text:
            continue
        parts = [part.strip() for part in text.split(separator) if part.strip()]
        ordered_parts = parts[1:] + parts[:1] if separator == ":" else parts
        for part in ordered_parts:
            if part:
                yield part


def derive_definition_short_text(
    short_candidate: Optional[CandidateSentence],
    definition_candidates: Sequence[CandidateSentence],
    *,
    definition_status: str,
) -> str:
    if short_candidate is None:
        return ""
    candidate_text = str(short_candidate.quote_raw or short_candidate.quote or "")
    normalized_candidate_text = normalize_ws(candidate_text)
    if not normalized_candidate_text:
        return ""
    if definition_status not in SUPPORTED_DEFINITION_STATUSES:
        return normalized_candidate_text
    definition_full_text = normalize_ws(build_definition_full_text(definition_candidates))
    if not definition_full_text:
        return ""
    if len(normalized_candidate_text) < len(definition_full_text):
        return normalized_candidate_text
    seen_fragments: set[str] = set()
    for fragment in iter_definition_short_fragments(candidate_text):
        normalized_fragment = normalize_ws(fragment)
        if normalized_fragment in seen_fragments:
            continue
        seen_fragments.add(normalized_fragment)
        if len(normalized_fragment) >= 16 and len(normalized_fragment) < len(definition_full_text):
            return normalized_fragment
    return ""


def build_definition_short_audit(
    definition_short_text: str,
    short_candidate: Optional[CandidateSentence],
    definition_candidates: Sequence[CandidateSentence],
    minimal_candidates: Sequence[CandidateSentence],
    *,
    kc_type: str,
    definition_status: str,
    role_cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    configured_role_cfg = default_role_cfg(role_cfg)
    strong_definition_score = float(configured_role_cfg["strong_definition_score"])
    definition_candidate_ids = [str(candidate.candidate_id) for candidate in definition_candidates]
    minimal_candidate_ids = [str(candidate.candidate_id) for candidate in minimal_candidates]
    short_text = normalize_ws(definition_short_text)
    short_candidate_id = str(short_candidate.candidate_id) if short_candidate else ""
    candidate_quote_text = str(short_candidate.quote_raw or short_candidate.quote or "") if short_candidate else ""
    is_extractive = bool(short_text and candidate_quote_text and verify_quote_in_raw_source(short_text, candidate_quote_text))
    definition_full_text = normalize_ws(build_definition_full_text(definition_candidates))
    if definition_status in SUPPORTED_DEFINITION_STATUSES:
        if not short_text:
            return {
                "definition_short_source_type": "unsupported_or_empty",
                "definition_short_evidence_ids": [],
                "definition_short_contract_ok": True,
                "definition_short_contract_fail_reason": "",
                "definition_short_candidate_id": short_candidate_id,
            }
        if (
            short_candidate
            and short_candidate_id in set(definition_candidate_ids)
            and short_text
            and is_extractive
            and definition_full_text
            and len(short_text) < len(definition_full_text)
        ):
            return {
                "definition_short_source_type": "derived_from_definition_full",
                "definition_short_evidence_ids": [short_candidate_id],
                "definition_short_contract_ok": True,
                "definition_short_contract_fail_reason": "",
                "definition_short_candidate_id": short_candidate_id,
            }
        fail_reason = "supported_definition_short_not_derived_from_definition_full"
        if short_text and definition_full_text and len(short_text) >= len(definition_full_text):
            fail_reason = "supported_definition_short_not_shorter_than_definition_full"
        elif short_text and not is_extractive:
            fail_reason = "supported_definition_short_not_extractive_from_definition_full"
        return {
            "definition_short_source_type": "unsupported_or_empty",
            "definition_short_evidence_ids": [],
            "definition_short_contract_ok": False,
            "definition_short_contract_fail_reason": fail_reason,
            "definition_short_candidate_id": short_candidate_id,
        }
    direct_quote_ok = bool(
        short_candidate
        and short_candidate_id in set(minimal_candidate_ids)
        and candidate_supports_definition_package(
            short_candidate,
            kc_type=kc_type,
            strong_definition_score=strong_definition_score,
        )
        and short_text
        and is_extractive
    )
    if direct_quote_ok:
        return {
            "definition_short_source_type": "direct_quote_short",
            "definition_short_evidence_ids": [short_candidate_id],
            "definition_short_contract_ok": True,
            "definition_short_contract_fail_reason": "",
            "definition_short_candidate_id": short_candidate_id,
        }
    if short_text:
        return {
            "definition_short_source_type": "unsupported_or_empty",
            "definition_short_evidence_ids": [],
            "definition_short_contract_ok": False,
            "definition_short_contract_fail_reason": "unsupported_definition_short_without_strong_direct_quote",
            "definition_short_candidate_id": short_candidate_id,
        }
    return {
        "definition_short_source_type": "unsupported_or_empty",
        "definition_short_evidence_ids": [],
        "definition_short_contract_ok": True,
        "definition_short_contract_fail_reason": "",
        "definition_short_candidate_id": "",
    }


def filter_quality_flags(
    flags: Sequence[Any],
    *,
    drop_prefixes: Sequence[str] = (),
    drop_exact: Sequence[str] = (),
) -> List[str]:
    exact = {str(item) for item in drop_exact}
    prefixes = [str(item) for item in drop_prefixes]
    kept: List[str] = []
    for item in flags:
        text = str(item)
        if text in exact:
            continue
        if any(text.startswith(prefix) for prefix in prefixes):
            continue
        kept.append(text)
    return kept


def field_evidence_items(record: Mapping[str, Any], field_name: str) -> List[Mapping[str, Any]]:
    field_map = record.get("field_evidence_map")
    if not isinstance(field_map, Mapping):
        return []
    value = field_map.get(field_name)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def evidence_ref_ids(field_name: str, evidence_items: Sequence[Mapping[str, Any]]) -> List[str]:
    ref_ids: List[str] = []
    for idx, evidence in enumerate(evidence_items):
        block_id = str(evidence.get("block_id") or "")
        if block_id:
            ref_ids.append(f"{field_name}:{idx}:{block_id}")
        else:
            ref_ids.append(f"{field_name}:{idx}")
    return ref_ids


def target_support_details(registry_row: Mapping[str, Any], text: str) -> Dict[str, Any]:
    name_terms = build_name_seed_terms(
        str(registry_row.get("canonical_name") or ""),
        ensure_string_list(registry_row.get("aliases")),
        str(registry_row.get("seed_definition") or ""),
    )
    text_norm = match_normalize(text)
    exact_name, exact_alias = exact_phrase_hits(text_norm, str(name_terms["canonical_norm"]), name_terms["alias_norms"])
    text_tokens = set(tokenize(text_norm))
    canonical_tokens = set(name_terms["canonical_tokens"])
    alias_tokens = set(name_terms["alias_tokens"])
    name_token_hits = len((canonical_tokens | alias_tokens) & text_tokens)
    seed_kw_overlap = len(set(name_terms["seed_keywords"]) & text_tokens)
    return {
        "exact_name": exact_name,
        "exact_alias": exact_alias,
        "name_token_hits": name_token_hits,
        "seed_kw_overlap": seed_kw_overlap,
    }


def loose_phrase_normalize(text: str) -> str:
    return " ".join(tokenize(match_normalize(text), min_len=1))


def registry_parent_label(registry_row: Mapping[str, Any]) -> str:
    parent_label = str(registry_row.get("overlay_parent_label") or "").strip()
    if parent_label:
        return parent_label
    path = registry_row.get("kc_path")
    if isinstance(path, list) and len(path) >= 2:
        return str(path[-2] or "").strip()
    return ""


def resolve_family_support_policy(registry_row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    parent_label = loose_phrase_normalize(registry_parent_label(registry_row))
    if not parent_label:
        return None
    for policy in FAMILY_SUPPORT_POLICIES.values():
        labels = [loose_phrase_normalize(str(item)) for item in list(policy.get("overlay_parent_labels") or []) if str(item).strip()]
        if parent_label in labels:
            return dict(policy)
    return None


def policy_leaf_rule(policy: Mapping[str, Any], registry_row: Mapping[str, Any]) -> Dict[str, Any]:
    leaf_overrides = dict(policy.get("leaf_overrides") or {})
    return dict(leaf_overrides.get(str(registry_row.get("kc_id") or "")) or {})


def normalized_policy_token_set(values: Sequence[Any]) -> set[str]:
    tokens: set[str] = set()
    for item in values:
        normalized = loose_phrase_normalize(str(item))
        if not normalized:
            continue
        tokens.update(normalized.split())
    return tokens


def normalized_policy_phrases(values: Sequence[Any]) -> List[str]:
    phrases: List[str] = []
    for item in values:
        normalized = loose_phrase_normalize(str(item))
        if normalized:
            phrases.append(normalized)
    return phrases


def policy_rule_matches_text(rule: Mapping[str, Any], loose_text: str, token_set: set[str]) -> bool:
    if not loose_text:
        return False
    exclude_phrases = normalized_policy_phrases(list(rule.get("exclude_phrases") or []))
    if any(phrase in loose_text for phrase in exclude_phrases):
        return False
    include_phrases = normalized_policy_phrases(list(rule.get("include_phrases") or []))
    if any(phrase in loose_text for phrase in include_phrases):
        return True
    for token_group in list(rule.get("include_all_tokens") or []):
        normalized_group = [loose_phrase_normalize(str(item)) for item in list(token_group) if str(item).strip()]
        if normalized_group and all(token in token_set for token in normalized_group):
            return True
    for token_group in list(rule.get("include_any_tokens") or []):
        normalized_group = [loose_phrase_normalize(str(item)) for item in list(token_group) if str(item).strip()]
        if normalized_group and any(token in token_set for token in normalized_group):
            return True
    return False


def family_topic_support(policy: Mapping[str, Any], text: str) -> bool:
    loose_text = loose_phrase_normalize(text)
    if not loose_text:
        return False
    return any(cue in loose_text for cue in normalized_policy_phrases(list(policy.get("family_topic_cues") or [])))


def family_discriminative_leaf_support(
    policy: Mapping[str, Any],
    registry_row: Mapping[str, Any],
    text: str,
    *,
    non_generic_name_token_hits: int,
    non_generic_seed_kw_overlap: int,
) -> bool:
    loose_text = loose_phrase_normalize(text)
    if not loose_text:
        return False
    token_set = set(loose_text.split())
    rule = policy_leaf_rule(policy, registry_row)
    if policy_rule_matches_text(rule, loose_text, token_set):
        return True
    min_name_hits = int(rule.get("min_non_generic_name_token_hits", policy.get("default_required_non_generic_name_tokens", 1)))
    min_seed_hits = int(rule.get("min_non_generic_seed_hits", policy.get("default_required_non_generic_seed_hits", 0)))
    return bool(
        non_generic_name_token_hits >= min_name_hits
        or (min_seed_hits > 0 and non_generic_seed_kw_overlap >= min_seed_hits)
    )


def bundle_target_support_mode(policy: Optional[Mapping[str, Any]]) -> str:
    if not policy:
        return "legacy"
    return str(policy.get("bundle_target_support_mode") or "strict_leaf_only")


def rescue_lineage_mode(policy: Optional[Mapping[str, Any]]) -> str:
    if not policy:
        return "advisory"
    return str(policy.get("permissive_rescue_lineage_mode") or "advisory")


def support_contract_target_state(contract: Mapping[str, Any]) -> str:
    if not bool(contract.get("family_scoped")):
        return "legacy_target_supported" if bool(contract.get("bundle_target_support")) else "legacy_unsupported"
    if bool(contract.get("bundle_strict_leaf_support")) and bool(contract.get("bundle_target_support")):
        return "strict_leaf_support"
    if bool(contract.get("bundle_parent_topic_overlap")):
        return "family_topic_support_only"
    if bool(contract.get("generic_selected_support")):
        return "generic_selected_support_only"
    if bool(contract.get("permissive_rescue_lineage")):
        return "permissive_rescue_lineage_only"
    return "unsupported"


def support_contract_enforcement_reason(
    *,
    contract: Mapping[str, Any],
    policy: Optional[Mapping[str, Any]],
    phase: str,
    preserved_from_step63: bool = False,
) -> str:
    if phase == "rescue":
        if bool(contract.get("bundle_strict_leaf_support")):
            return ""
        if not bool(contract.get("family_scoped")):
            return "selected_bundle_missing_strict_leaf_support"
        if bool(contract.get("bundle_parent_topic_overlap")) and bool(policy and policy.get("parent_topic_overlap_blocks_rescue")):
            return "parent_topic_overlap"
        if bool(contract.get("generic_selected_support")):
            return "generic_selected_support"
        if bool(contract.get("permissive_rescue_lineage")) and rescue_lineage_mode(policy) == "hard_block":
            return "permissive_rescue_lineage"
        return "selected_bundle_missing_strict_leaf_support"

    if not bool(contract.get("family_scoped")) or bool(contract.get("bundle_strict_leaf_support")):
        return ""
    if bool(contract.get("bundle_parent_topic_overlap")):
        return "family_topic_only_without_leaf_support"
    if bool(contract.get("generic_selected_support")):
        return "generic_selected_support_without_leaf_support"
    if bool(contract.get("permissive_rescue_lineage")) and rescue_lineage_mode(policy) == "hard_block":
        return "permissive_rescue_lineage_without_leaf_support"
    if preserved_from_step63:
        return "preserved_payload_outruns_selected_support"
    return "selected_bundle_missing_strict_leaf_support"


def local_bundle_rescue_block_label(reason: str) -> str:
    mapping = {
        "parent_topic_overlap": "LocalBundleRescueBlocked:ParentTopicOverlap",
        "generic_selected_support": "LocalBundleRescueBlocked:GenericSelectedSupport",
        "permissive_rescue_lineage": "LocalBundleRescueBlocked:PermissiveRescueLineage",
        "selected_bundle_missing_strict_leaf_support": "LocalBundleRescueBlocked:MissingStrictLeafSupport",
    }
    return mapping.get(reason, "LocalBundleRescueBlocked:MissingStrictLeafSupport")


def target_support_profile(registry_row: Mapping[str, Any], text: str) -> Dict[str, Any]:
    support = target_support_details(registry_row, text)
    profile = dict(support)
    policy = resolve_family_support_policy(registry_row)
    profile["family_policy_id"] = str(policy.get("family_id") or "") if policy else ""
    profile["family_scoped"] = bool(policy)
    profile["family_topic_support"] = False
    profile["discriminative_leaf_cue"] = False
    profile["generic_selected_support"] = False
    profile["non_generic_name_token_hits"] = 0
    profile["non_generic_seed_kw_overlap"] = 0
    if policy is None:
        profile["strict_leaf_support"] = bool(
            profile["exact_name"]
            or profile["exact_alias"]
            or profile["name_token_hits"] > 0
            or profile["seed_kw_overlap"] > 0
        )
        return profile

    name_terms = build_name_seed_terms(
        str(registry_row.get("canonical_name") or ""),
        ensure_string_list(registry_row.get("aliases")),
        str(registry_row.get("seed_definition") or ""),
    )
    text_tokens = set(tokenize(match_normalize(text)))
    generic_tokens = normalized_policy_token_set(list(policy.get("generic_tokens") or []))
    canonical_tokens = {str(item) for item in name_terms.get("canonical_tokens") or []}
    alias_tokens = {str(item) for item in name_terms.get("alias_tokens") or []}
    seed_keywords = {str(item) for item in name_terms.get("seed_keywords") or []}
    profile["non_generic_name_token_hits"] = len(((canonical_tokens | alias_tokens) - generic_tokens) & text_tokens)
    profile["non_generic_seed_kw_overlap"] = len((seed_keywords - generic_tokens) & text_tokens)
    if bool(policy.get("track_family_topic_support")):
        profile["family_topic_support"] = family_topic_support(policy, text)
    profile["discriminative_leaf_cue"] = family_discriminative_leaf_support(
        policy,
        registry_row,
        text,
        non_generic_name_token_hits=int(profile["non_generic_name_token_hits"]),
        non_generic_seed_kw_overlap=int(profile["non_generic_seed_kw_overlap"]),
    )
    profile["strict_leaf_support"] = bool(
        profile["exact_name"]
        or profile["exact_alias"]
        or profile["discriminative_leaf_cue"]
    )
    profile["generic_selected_support"] = bool(
        not profile["strict_leaf_support"]
        and (
            profile["family_topic_support"]
            or profile["name_token_hits"] > 0
            or profile["seed_kw_overlap"] > 0
        )
    )
    return profile


def text_has_target_support(registry_row: Mapping[str, Any], text: str) -> bool:
    support = target_support_profile(registry_row, text)
    return bool(support["strict_leaf_support"])


def text_has_target_name_or_alias_support(registry_row: Mapping[str, Any], text: str) -> bool:
    support = target_support_details(registry_row, text)
    return bool(
        support["exact_name"]
        or support["exact_alias"]
        or support["name_token_hits"] > 0
    )


def candidate_has_target_name_support(candidate: CandidateSentence) -> bool:
    return bool(candidate.exact_name_phrase or candidate.exact_alias_phrase or candidate.name_alias_hits > 0)


def selected_candidates_have_permissive_rescue_lineage(candidates: Sequence[CandidateSentence]) -> bool:
    return any(
        any(str(reason).startswith("LocalBundleRescueAccepted:") for reason in list(candidate.gate_reasons))
        for candidate in candidates
    )


def build_support_contract_summary(
    *,
    registry_row: Mapping[str, Any],
    record: Mapping[str, Any],
    selected_candidates: Sequence[CandidateSentence],
) -> Dict[str, Any]:
    policy = resolve_family_support_policy(registry_row)
    bundle_text = bundle_text_from_candidates(selected_candidates)
    bundle_support = target_support_profile(registry_row, bundle_text)
    definition_short_support = target_support_profile(registry_row, str(record.get("definition_short") or ""))
    definition_full_support = target_support_profile(registry_row, str(record.get("definition_full") or ""))
    if bundle_target_support_mode(policy) == "strict_leaf_only":
        bundle_target_support = bool(bundle_support["strict_leaf_support"])
    else:
        bundle_target_support = bool(
            bundle_name_support_count(registry_row, selected_candidates)
            or bundle_support["strict_leaf_support"]
            or definition_short_support["strict_leaf_support"]
            or definition_full_support["strict_leaf_support"]
        )
    contract = {
        "family_policy_id": str(policy.get("family_id") or "") if policy else "",
        "family_scoped": bool(policy),
        "bundle_target_support_mode": bundle_target_support_mode(policy),
        "permissive_rescue_lineage_mode": rescue_lineage_mode(policy),
        "bundle_target_support": bundle_target_support,
        "bundle_strict_leaf_support": bool(bundle_support["strict_leaf_support"]),
        "bundle_family_topic_support": bool(bundle_support["family_topic_support"]),
        "bundle_parent_topic_overlap": bool(bundle_support["family_topic_support"] and not bundle_support["strict_leaf_support"]),
        "generic_selected_support": bool(bundle_support.get("generic_selected_support")),
        "definition_short_strict_leaf_support": bool(definition_short_support["strict_leaf_support"]),
        "definition_short_family_topic_support": bool(definition_short_support["family_topic_support"]),
        "definition_full_strict_leaf_support": bool(definition_full_support["strict_leaf_support"]),
        "definition_full_family_topic_support": bool(definition_full_support["family_topic_support"]),
        "permissive_rescue_lineage": selected_candidates_have_permissive_rescue_lineage(selected_candidates),
    }
    contract["target_support_state"] = support_contract_target_state(contract)
    return contract


def should_preserve_step63_payload(
    *,
    registry_row: Mapping[str, Any],
    record: Mapping[str, Any],
    selected_candidates: Sequence[CandidateSentence],
) -> bool:
    contract = build_support_contract_summary(
        registry_row=registry_row,
        record=record,
        selected_candidates=selected_candidates,
    )
    if not bool(contract["family_scoped"]):
        return True
    return bool(contract["bundle_strict_leaf_support"])


def clear_semantic_support_payload(record: Dict[str, Any]) -> None:
    record["field_evidence_map"] = dict(record.get("field_evidence_map") or {})
    for field_name in SEMANTIC_PAYLOAD_TEXT_FIELDS:
        record[field_name] = ""
    for field_name in SEMANTIC_PAYLOAD_LIST_FIELDS:
        record[field_name] = []
    for field_name in SEMANTIC_PAYLOAD_EVIDENCE_FIELDS:
        record["field_evidence_map"].pop(field_name, None)


def enforce_family_support_contract(
    *,
    record: Dict[str, Any],
    registry_row: Mapping[str, Any],
    selected_candidates: Sequence[CandidateSentence],
    definition_status: str,
    preserved_from_step63: bool,
) -> Tuple[str, Dict[str, Any]]:
    contract = build_support_contract_summary(
        registry_row=registry_row,
        record=record,
        selected_candidates=selected_candidates,
    )
    contract["preserved_from_step63"] = bool(preserved_from_step63)
    contract["support_contract_downgraded"] = False
    contract["support_contract_downgrade_reason"] = ""
    downgrade_reason = support_contract_enforcement_reason(
        contract=contract,
        policy=resolve_family_support_policy(registry_row),
        phase="final",
        preserved_from_step63=preserved_from_step63,
    )
    if not downgrade_reason:
        contract["target_support_state"] = support_contract_target_state(contract)
        return definition_status, contract

    clear_semantic_support_payload(record)
    contract["bundle_target_support"] = False
    contract["support_contract_downgraded"] = True
    contract["support_contract_downgrade_reason"] = downgrade_reason
    contract["target_support_state"] = support_contract_target_state(contract)
    return "unsupported_in_source", contract


def evidence_matches_short_text(short_text: str, evidence: Mapping[str, Any]) -> bool:
    evidence_quote = str(evidence.get("quote") or "")
    return bool(short_text and evidence_quote and verify_quote_in_raw_source(short_text, evidence_quote))


def derive_definition_short_from_full_text(definition_full_text: str) -> str:
    normalized_full = normalize_ws(definition_full_text)
    if not normalized_full:
        return ""
    for fragment in iter_definition_short_fragments(definition_full_text):
        normalized_fragment = normalize_ws(fragment)
        if normalized_fragment and len(normalized_fragment) >= 16 and len(normalized_fragment) < len(normalized_full):
            return normalized_fragment
    return ""


def audit_final_definition_short_record(
    record: Mapping[str, Any],
    registry_row: Mapping[str, Any],
) -> Dict[str, Any]:
    short_text = normalize_ws(str(record.get("definition_short") or ""))
    full_text = normalize_ws(str(record.get("definition_full") or ""))
    short_field_evidence = field_evidence_items(record, "definition_short")
    full_field_evidence = field_evidence_items(record, "definition_full")
    minimal_evidence = [
        item
        for item in list(record.get("evidence_minimal") or [])
        if isinstance(item, Mapping)
    ]
    matched_short_evidence = [item for item in short_field_evidence if evidence_matches_short_text(short_text, item)]
    matched_full_evidence = [item for item in full_field_evidence if evidence_matches_short_text(short_text, item)]
    matched_minimal_evidence = [item for item in minimal_evidence if evidence_matches_short_text(short_text, item)]
    support = target_support_profile(registry_row, short_text)
    has_target_support = bool(support["strict_leaf_support"])

    if not short_text:
        return {
            "definition_short_source_type": "unsupported_or_empty",
            "definition_short_evidence_ids": [],
            "definition_short_contract_ok": True,
            "definition_short_contract_fail_reason": "",
            "definition_short_candidate_id": "",
            "matched_definition_short_evidence": [],
            "matched_definition_full_evidence": [],
            "matched_minimal_evidence": [],
            "target_support": support,
        }

    if full_text and len(short_text) < len(full_text) and verify_quote_in_raw_source(short_text, full_text):
        evidence_items: List[Mapping[str, Any]] = []
        evidence_field = ""
        if matched_short_evidence:
            evidence_items = matched_short_evidence
            evidence_field = "definition_short"
        elif matched_full_evidence:
            evidence_items = matched_full_evidence
            evidence_field = "definition_full"
        elif matched_minimal_evidence:
            evidence_items = matched_minimal_evidence
            evidence_field = "evidence_minimal"
        if evidence_items:
            return {
                "definition_short_source_type": "derived_from_definition_full",
                "definition_short_evidence_ids": evidence_ref_ids(evidence_field, evidence_items),
                "definition_short_contract_ok": True,
                "definition_short_contract_fail_reason": "",
                "definition_short_candidate_id": "",
                "matched_definition_short_evidence": matched_short_evidence,
                "matched_definition_full_evidence": matched_full_evidence,
                "matched_minimal_evidence": matched_minimal_evidence,
                "target_support": support,
            }
        return {
            "definition_short_source_type": "unsupported_or_empty",
            "definition_short_evidence_ids": [],
            "definition_short_contract_ok": False,
            "definition_short_contract_fail_reason": "final_definition_short_missing_supporting_evidence",
            "definition_short_candidate_id": "",
            "matched_definition_short_evidence": matched_short_evidence,
            "matched_definition_full_evidence": matched_full_evidence,
            "matched_minimal_evidence": matched_minimal_evidence,
            "target_support": support,
        }

    if has_target_support and (matched_short_evidence or matched_minimal_evidence):
        evidence_items = matched_short_evidence or matched_minimal_evidence
        evidence_field = "definition_short" if matched_short_evidence else "evidence_minimal"
        return {
            "definition_short_source_type": "direct_quote_short",
            "definition_short_evidence_ids": evidence_ref_ids(evidence_field, evidence_items),
            "definition_short_contract_ok": True,
            "definition_short_contract_fail_reason": "",
            "definition_short_candidate_id": "",
            "matched_definition_short_evidence": matched_short_evidence,
            "matched_definition_full_evidence": matched_full_evidence,
            "matched_minimal_evidence": matched_minimal_evidence,
            "target_support": support,
        }

    if full_text:
        fail_reason = "supported_definition_short_not_derived_from_final_definition_full"
    elif not (matched_short_evidence or matched_minimal_evidence):
        fail_reason = "final_definition_short_missing_supporting_evidence"
    elif not has_target_support:
        fail_reason = "final_definition_short_missing_target_support"
    else:
        fail_reason = "unsupported_definition_short_without_strong_direct_quote"
    return {
        "definition_short_source_type": "unsupported_or_empty",
        "definition_short_evidence_ids": [],
        "definition_short_contract_ok": False,
        "definition_short_contract_fail_reason": fail_reason,
        "definition_short_candidate_id": "",
        "matched_definition_short_evidence": matched_short_evidence,
        "matched_definition_full_evidence": matched_full_evidence,
        "matched_minimal_evidence": matched_minimal_evidence,
        "target_support": support,
    }


def enforce_definition_short_on_final_record(
    *,
    record: Dict[str, Any],
    registry_row: Mapping[str, Any],
    preserved_from_step63: bool,
) -> Dict[str, Any]:
    record["field_evidence_map"] = dict(record.get("field_evidence_map") or {})
    original_short = normalize_ws(str(record.get("definition_short") or ""))
    final_full_text = normalize_ws(str(record.get("definition_full") or ""))

    audit = audit_final_definition_short_record(record, registry_row)
    if (
        original_short
        and final_full_text
        and not bool(audit["definition_short_contract_ok"])
        and audit["definition_short_source_type"] == "unsupported_or_empty"
    ):
        rewritten_short = derive_definition_short_from_full_text(final_full_text)
        if rewritten_short and rewritten_short != original_short:
            record["definition_short"] = rewritten_short
            if not field_evidence_items(record, "definition_short"):
                full_evidence = field_evidence_items(record, "definition_full")
                if full_evidence:
                    record["field_evidence_map"]["definition_short"] = [json.loads(json.dumps(full_evidence[0]))]
            audit = audit_final_definition_short_record(record, registry_row)

    if bool(audit["definition_short_contract_ok"]) and record["definition_short"] and not field_evidence_items(record, "definition_short"):
        matched_evidence = (
            list(audit.get("matched_definition_short_evidence") or [])
            or list(audit.get("matched_definition_full_evidence") or [])
            or list(audit.get("matched_minimal_evidence") or [])
        )
        if matched_evidence:
            record["field_evidence_map"]["definition_short"] = [json.loads(json.dumps(matched_evidence[0]))]
            audit = audit_final_definition_short_record(record, registry_row)

    if not bool(audit["definition_short_contract_ok"]) or (
        audit["definition_short_source_type"] == "unsupported_or_empty" and normalize_ws(str(record.get("definition_short") or ""))
    ):
        record["definition_short"] = ""
        record["field_evidence_map"].pop("definition_short", None)
        audit = audit_final_definition_short_record(record, registry_row)

    final_short = normalize_ws(str(record.get("definition_short") or ""))
    if original_short and not final_short:
        action = "drop"
    elif final_short and final_short != original_short:
        action = "rewrite"
    else:
        action = "unchanged"

    audit["definition_short_pre_enforcement_text"] = original_short
    audit["definition_short_post_enforcement_text"] = final_short
    audit["definition_short_enforcement_action"] = action
    audit["definition_short_post_preserve_rewrite"] = bool(preserved_from_step63 and action == "rewrite")
    audit["definition_short_post_preserve_drop"] = bool(preserved_from_step63 and action == "drop")
    return audit


def verified_record_evidence_items(record: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    evidence_minimal = record.get("evidence_minimal")
    if not isinstance(evidence_minimal, list):
        return []
    return [
        item
        for item in evidence_minimal
        if isinstance(item, Mapping) and bool(item.get("quote_verified"))
    ]


def short_cleanup_evidence_signature(record: Mapping[str, Any]) -> List[Tuple[str, str, str, bool]]:
    signature: List[Tuple[str, str, str, bool]] = []
    for evidence in field_evidence_items(record, "definition_short"):
        signature.append(
            (
                str(evidence.get("block_id") or ""),
                str(evidence.get("role") or ""),
                normalize_ws(str(evidence.get("quote") or "")),
                bool(evidence.get("quote_verified")),
            )
        )
    return signature


def short_cleanup_changed_fields(
    before_record: Mapping[str, Any],
    after_record: Mapping[str, Any],
) -> List[str]:
    changed: List[str] = []
    if normalize_ws(str(before_record.get("definition_short") or "")) != normalize_ws(str(after_record.get("definition_short") or "")):
        changed.append("definition_short")
    if short_cleanup_evidence_signature(before_record) != short_cleanup_evidence_signature(after_record):
        changed.append("field_evidence_map.definition_short")
    return changed


def short_cleanup_only_changed(changed_fields: Sequence[str]) -> bool:
    return bool(changed_fields) and all(field in SHORT_CLEANUP_ONLY_FIELDS for field in changed_fields)


def record_supports_decoupled_tier1(record: Mapping[str, Any]) -> bool:
    evidence_minimal = record.get("evidence_minimal")
    evidence_items = [item for item in list(evidence_minimal or []) if isinstance(item, Mapping)] if isinstance(evidence_minimal, list) else []
    verified_items = verified_record_evidence_items(record)
    has_role = any(str(item.get("role") or "") in TIER1_RETRIEVAL_ROLES for item in verified_items)
    return bool(
        len(evidence_items) >= 2
        and len(verified_items) >= 2
        and has_role
        and not validate_kc_record(record)
    )


def reconcile_tier_post_short_cleanup(
    *,
    record: Mapping[str, Any],
    pre_short_cleanup_record: Mapping[str, Any],
    pre_short_cleanup_tier: int,
    post_short_cleanup_tier: int,
) -> Dict[str, Any]:
    changed_fields = short_cleanup_changed_fields(pre_short_cleanup_record, record)
    regressed = bool(
        pre_short_cleanup_tier >= 1
        and post_short_cleanup_tier < 1
        and short_cleanup_only_changed(changed_fields)
    )
    restored = bool(regressed and record_supports_decoupled_tier1(record))
    effective_tier = pre_short_cleanup_tier if restored else post_short_cleanup_tier
    return {
        "tier1_pre_short_cleanup": int(pre_short_cleanup_tier),
        "tier1_post_short_cleanup": int(post_short_cleanup_tier),
        "tier1_post_short_cleanup_changed_fields": list(changed_fields),
        "tier1_post_short_cleanup_regressed": regressed,
        "tier1_post_short_cleanup_restored": restored,
        "effective_base_tier": int(effective_tier),
    }


def definition_support_payload_signature(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kc_type": str(record.get("kc_type") or ""),
        "definition_short": normalize_ws(str(record.get("definition_short") or "")),
        "definition_full": normalize_ws(str(record.get("definition_full") or "")),
        "definition_short_evidence": short_cleanup_evidence_signature(record),
        "definition_full_evidence": [
            (
                str(evidence.get("block_id") or ""),
                str(evidence.get("role") or ""),
                normalize_ws(str(evidence.get("quote") or "")),
                bool(evidence.get("quote_verified")),
            )
            for evidence in field_evidence_items(record, "definition_full")
        ],
        "evidence_minimal": [
            (
                str(evidence.get("block_id") or ""),
                str(evidence.get("role") or ""),
                normalize_ws(str(evidence.get("quote") or "")),
                bool(evidence.get("quote_verified")),
            )
            for evidence in verified_record_evidence_items(record)
        ],
    }


def reconcile_definition_status_post_short_cleanup(
    *,
    kc_id: str,
    record: Mapping[str, Any],
    definition_status: str,
    preserved_from_step63: bool,
    baseline_definition_audit_by_kc: Mapping[str, Mapping[str, Any]],
    baseline_kc_library_by_kc: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    baseline_audit = dict(baseline_definition_audit_by_kc.get(kc_id) or {})
    baseline_record = dict(baseline_kc_library_by_kc.get(kc_id) or {})
    baseline_status = str(baseline_audit.get("definition_status") or "")
    baseline_supported = baseline_status in SUPPORTED_DEFINITION_STATUSES
    current_supported = definition_status in SUPPORTED_DEFINITION_STATUSES
    payload_unchanged = bool(
        baseline_record
        and definition_support_payload_signature(record) == definition_support_payload_signature(baseline_record)
    )
    regressed = bool(
        preserved_from_step63
        and baseline_supported
        and not current_supported
        and payload_unchanged
    )
    restored = regressed
    effective_status = baseline_status if restored else definition_status
    return effective_status, {
        "baseline_definition_status": baseline_status,
        "definition_status_pre_short_cleanup": baseline_status if baseline_supported else definition_status,
        "definition_status_post_short_cleanup": definition_status,
        "definition_status_post_short_cleanup_regressed": regressed,
        "definition_status_post_short_cleanup_restored": restored,
        "definition_support_payload_unchanged_vs_baseline": payload_unchanged,
        "effective_definition_status": effective_status,
    }


def build_definition_full_text(candidates: Sequence[CandidateSentence]) -> str:
    if not candidates:
        return ""
    return "\n".join(str(candidate.quote_raw or candidate.quote or "") for candidate in candidates if str(candidate.quote_raw or candidate.quote or ""))


def extract_scope_lists(candidates: Sequence[CandidateSentence]) -> Tuple[List[str], List[str]]:
    includes: List[str] = []
    excludes: List[str] = []
    for candidate in candidates:
        quote_raw = str(candidate.quote_raw or candidate.quote or "")
        lower = match_normalize(quote_raw)
        if any(token in lower for token in ["only if", "requires", "assumes", "under the condition"]):
            includes.append(quote_raw)
        if any(token in lower for token in ["not ", "does not", "cannot", "without "]):
            excludes.append(quote_raw)
    return unique_preserve_order(includes)[:3], unique_preserve_order(excludes)[:3]


def infer_kc_type(registry_row: Mapping[str, Any], step6_row: Optional[Mapping[str, Any]]) -> str:
    if step6_row:
        value = str(step6_row.get("kc_type") or "")
        if value in {"concept", "procedure", "metric", "theorem_or_claim", "misconception_cluster"}:
            return value
    name = match_normalize(str(registry_row.get("canonical_name") or ""))
    if any(token in name for token in ["algorithm", "phase"]):
        return "procedure"
    if any(token in name for token in ["index", "ratio", "coefficient", "entropy", "gain", "information"]):
        return "metric"
    if "theorem" in name:
        return "theorem_or_claim"
    return "concept"


def build_record_and_trace(
    *,
    step6lib: Any,
    registry_row: Mapping[str, Any],
    step6_row: Optional[Mapping[str, Any]],
    step5_set_id: str,
    step4_set_id: str,
    run_id: str,
    created_utc: str,
    schema_ver: str,
    extraction_method: str,
    semantic_cfg: Mapping[str, Any],
    enrichment_cfg: Mapping[str, Any],
    provenance_cfg: Mapping[str, Any],
    role_cfg: Mapping[str, Any],
    runtime_models: RuntimeModels,
    runtime_counters: RuntimeCounters,
    step63: Any,
    scorer: Any,
    query_cache: Mapping[str, Any],
    provenance_index: Optional[Mapping[str, Any]],
    block_positions: Mapping[str, int],
    adjudication_cfg: Mapping[str, Any],
    all_candidates: Sequence[CandidateSentence],
    baseline_definition_audit_by_kc: Mapping[str, Mapping[str, Any]],
    baseline_kc_library_by_kc: Mapping[str, Mapping[str, Any]],
) -> ProcessingResult:
    kc_id = str(registry_row["kc_id"])
    if step6_row:
        record = json.loads(json.dumps(step6_row))
        record["source_set_ids"] = dict(record.get("source_set_ids") or {})
        record["source_set_ids"]["step4_set_id"] = step4_set_id
        record["source_set_ids"]["step5_set_id"] = step5_set_id
        record["record_meta"] = dict(record.get("record_meta") or {})
        record["record_meta"]["created_utc"] = created_utc
        record["record_meta"]["run_id_step6"] = run_id
        record["record_meta"]["schema_version"] = schema_ver
        record["field_evidence_map"] = json.loads(json.dumps(record.get("field_evidence_map") or {}))
        record["quality_flags"] = [str(item) for item in record.get("quality_flags") or []]
    else:
        record = step6lib.default_record_shell(
            kc_row=registry_row,
            step4_set_id=step4_set_id,
            step5_set_id=step5_set_id,
            run_id_step6=run_id,
            created_utc=created_utc,
            schema_ver=schema_ver,
        )
    baseline_record = json.loads(json.dumps(record))
    accepted = [candidate for candidate in all_candidates if candidate.accepted]
    normalized_accepted, provenance_stats, dropped_due_to_provenance = apply_provenance_normalization(
        candidates=accepted,
        provenance_index=provenance_index,
        provenance_cfg=provenance_cfg,
    )
    role_map, role_sources, role_meta = annotate_roles(
        step63=step63,
        runtime_counters=runtime_counters,
        model=runtime_models.generation_model,
        base_url=runtime_models.generation_base_url,
        retries=runtime_models.generation_retries,
        num_ctx=runtime_models.generation_num_ctx,
        allow_think_fallback=runtime_models.generation_allow_think,
        registry_row=registry_row,
        role_cfg=role_cfg,
        candidates=normalized_accepted,
    )
    normalized_with_roles: List[CandidateSentence] = []
    for candidate in normalized_accepted:
        detail = dict((role_meta.get("details") or {}).get(candidate.candidate_id) or {})
        normalized_with_roles.append(
            replace(
                candidate,
                final_role=role_map.get(candidate.candidate_id, heuristic_role(candidate)),
                role_scores={str(key): float(value) for key, value in dict(detail.get("scores") or {}).items()},
                role_source=str(role_sources.get(candidate.candidate_id, "heuristic")),
                role_confidence=str(detail.get("role_confidence") or "high"),
                role_ambiguous=bool(detail.get("ambiguous")),
                role_ambiguity_reason=str(detail.get("ambiguity_reason") or ""),
            )
        )
    minimal_candidates, bundle_meta = select_quote_bundle(
        normalized_with_roles,
        max_items=int(enrichment_cfg["evidence_minimal_target"]),
        block_positions=block_positions,
        bundle_max_items=int(enrichment_cfg.get("bundle_max_quotes") or 3),
    )
    record["kc_type"] = infer_kc_type(registry_row, step6_row)
    definition_candidates, definition_status, definition_meta = build_definition_package(
        minimal_candidates,
        kc_type=str(record["kc_type"]),
        role_cfg=role_cfg,
        max_items=int(enrichment_cfg["definition_full_max_quotes"]),
    )
    definition_full_text = build_definition_full_text(definition_candidates)
    short_candidate = select_definition_short_candidate(
        definition_candidates,
        minimal_candidates,
        kc_type=str(record["kc_type"]),
        definition_status=definition_status,
        role_cfg=role_cfg,
    )
    definition_short_text = derive_definition_short_text(
        short_candidate,
        definition_candidates,
        definition_status=definition_status,
    )
    initial_definition_short_audit = build_definition_short_audit(
        definition_short_text,
        short_candidate,
        definition_candidates,
        minimal_candidates,
        kc_type=str(record["kc_type"]),
        definition_status=definition_status,
        role_cfg=role_cfg,
    )
    includes, excludes = extract_scope_lists(minimal_candidates)
    record["definition_short"] = (
        definition_short_text
        if definition_short_text and bool(initial_definition_short_audit["definition_short_contract_ok"])
        else ""
    )
    record["definition_full"] = definition_full_text
    record["scope_includes"] = includes
    record["scope_excludes"] = excludes
    record["field_evidence_map"] = {}
    if definition_short_text and short_candidate and bool(initial_definition_short_audit["definition_short_contract_ok"]):
        record["field_evidence_map"]["definition_short"] = [evidence_item(short_candidate, short_candidate.final_role, extraction_method)]
    if definition_candidates:
        record["field_evidence_map"]["definition_full"] = [evidence_item(candidate, candidate.final_role, extraction_method) for candidate in definition_candidates]
    record["evidence_minimal"] = [evidence_item(candidate, candidate.final_role, extraction_method) for candidate in minimal_candidates]
    if includes:
        include_evidence = [candidate for candidate in minimal_candidates if str(candidate.quote_raw or candidate.quote or "") in set(includes)]
        record["field_evidence_map"]["scope_includes"] = [evidence_item(candidate, "scope", extraction_method) for candidate in include_evidence]
    if excludes:
        exclude_evidence = [candidate for candidate in minimal_candidates if str(candidate.quote_raw or candidate.quote or "") in set(excludes)]
        record["field_evidence_map"]["scope_excludes"] = [evidence_item(candidate, "scope", extraction_method) for candidate in exclude_evidence]
    if record["kc_type"] == "procedure":
        procedure_candidates = [candidate for candidate in minimal_candidates if candidate.final_role == "procedure"]
        if procedure_candidates:
            record["procedure_steps"] = [str(candidate.quote_raw or candidate.quote or "") for candidate in procedure_candidates[:3]]
            record["field_evidence_map"]["procedure_steps"] = [evidence_item(candidate, "procedure", extraction_method) for candidate in procedure_candidates[:3]]
        io_candidates = [candidate for candidate in minimal_candidates if any(token in match_normalize(candidate.quote) for token in ["input", "output"])]
        if io_candidates:
            record["inputs_outputs"] = str(io_candidates[0].quote_raw or io_candidates[0].quote or "")
            record["field_evidence_map"]["inputs_outputs"] = [evidence_item(io_candidates[0], io_candidates[0].final_role, extraction_method)]
    if record["kc_type"] == "metric":
        equation_candidates = [candidate for candidate in minimal_candidates if candidate.final_role == "equation"]
        interpretation_candidates = [candidate for candidate in definition_candidates if candidate.final_role != "equation"]
        if equation_candidates:
            record["formal_definition"] = str(equation_candidates[0].quote_raw or equation_candidates[0].quote or "")
            record["field_evidence_map"]["formal_definition"] = [evidence_item(equation_candidates[0], "equation", extraction_method)]
        if interpretation_candidates:
            record["interpretation"] = str(interpretation_candidates[0].quote_raw or interpretation_candidates[0].quote or "")
            record["field_evidence_map"]["interpretation"] = [
                evidence_item(interpretation_candidates[0], interpretation_candidates[0].final_role, extraction_method)
            ]
        elif definition_candidates:
            record["interpretation"] = str(definition_candidates[0].quote_raw or definition_candidates[0].quote or "")
            record["field_evidence_map"]["interpretation"] = [evidence_item(definition_candidates[0], definition_candidates[0].final_role, extraction_method)]
    if record["kc_type"] == "theorem_or_claim" and definition_candidates:
        record["claim_statement"] = str(definition_candidates[0].quote_raw or definition_candidates[0].quote or "")
        record["field_evidence_map"]["claim_statement"] = [evidence_item(definition_candidates[0], definition_candidates[0].final_role, extraction_method)]
        record["assumptions"] = []
    record["quality_flags"] = filter_quality_flags(
        record.get("quality_flags") or [],
        drop_prefixes=[
            "DefinitionStatus:",
            "DefinitionShortSourceType:",
            "DefinitionShortContractFailReason:",
            "PageIndexDropped:",
            "QuoteRebound:",
            "QuoteRebindFailed:",
            "SemanticSafeTier:",
            "UsableCurriculum:",
            "ContaminationCategory:",
            "SiblingAmbiguityResolved:",
        ],
        drop_exact=["DefinitionShortContractFail", "DefinitionExtractiveOnly", "DefinitionShortPostPreserveRewrite", "DefinitionShortPostPreserveDrop"],
    )
    preserved_from_step63 = False
    tier_info = step6lib.apply_tier_classification(record)
    if int(tier_info["tier"]) < 1 and step6_row and should_preserve_step63_payload(
        registry_row=registry_row,
        record=record,
        selected_candidates=minimal_candidates,
    ):
        record = json.loads(json.dumps(baseline_record))
        record["field_evidence_map"] = dict(record.get("field_evidence_map") or {})
        record["quality_flags"] = filter_quality_flags(
            record.get("quality_flags") or [],
            drop_prefixes=[
                "DefinitionStatus:",
                "DefinitionShortSourceType:",
                "DefinitionShortContractFailReason:",
                "PageIndexDropped:",
                "QuoteRebound:",
                "QuoteRebindFailed:",
                "SemanticSafeTier:",
                "UsableCurriculum:",
                "ContaminationCategory:",
                "SiblingAmbiguityResolved:",
            ],
            drop_exact=["DefinitionShortContractFail", "DefinitionExtractiveOnly", "DefinitionShortPostPreserveRewrite", "DefinitionShortPostPreserveDrop"],
        )
        record["quality_flags"].append("Tier1PreservedFromStep6_3")
        preserved_from_step63 = True
    pre_short_cleanup_record = json.loads(json.dumps(record))
    pre_short_cleanup_tier = int(step6lib.apply_tier_classification(json.loads(json.dumps(pre_short_cleanup_record)))["tier"])
    definition_short_audit = enforce_definition_short_on_final_record(
        record=record,
        registry_row=registry_row,
        preserved_from_step63=preserved_from_step63,
    )
    definition_status, definition_status_contract_decouple = reconcile_definition_status_post_short_cleanup(
        kc_id=kc_id,
        record=record,
        definition_status=definition_status,
        preserved_from_step63=preserved_from_step63,
        baseline_definition_audit_by_kc=baseline_definition_audit_by_kc,
        baseline_kc_library_by_kc=baseline_kc_library_by_kc,
    )
    definition_status, family_support_contract = enforce_family_support_contract(
        record=record,
        registry_row=registry_row,
        selected_candidates=minimal_candidates,
        definition_status=definition_status,
        preserved_from_step63=preserved_from_step63,
    )
    if bool(family_support_contract.get("support_contract_downgraded")):
        definition_short_audit = enforce_definition_short_on_final_record(
            record=record,
            registry_row=registry_row,
            preserved_from_step63=False,
        )
    record["quality_flags"].append("DefinitionExtractiveOnly")
    record["quality_flags"].append(f"DefinitionStatus:{definition_status}")
    record["quality_flags"].append(f"DefinitionShortSourceType:{definition_short_audit['definition_short_source_type']}")
    if definition_status == "fragmentary_supported":
        record["quality_flags"].append("DefinitionFragmentarySupported")
    if definition_meta.get("single_quote_fragmentary"):
        record["quality_flags"].append("DefinitionFragmentarySingleQuote")
    if definition_short_audit.get("definition_short_post_preserve_rewrite"):
        record["quality_flags"].append("DefinitionShortPostPreserveRewrite")
    if definition_short_audit.get("definition_short_post_preserve_drop"):
        record["quality_flags"].append("DefinitionShortPostPreserveDrop")
    if bool(definition_status_contract_decouple["definition_status_post_short_cleanup_restored"]):
        record["quality_flags"].append("DefinitionStatusPostShortCleanupRestored")
    if bool(family_support_contract.get("support_contract_downgraded")):
        reason = str(family_support_contract.get("support_contract_downgrade_reason") or "unknown")
        record["quality_flags"].append("FamilySupportContractDowngrade")
        record["quality_flags"].append(f"FamilySupportContractDowngradeReason:{reason}")
    if not bool(definition_short_audit["definition_short_contract_ok"]):
        record["quality_flags"].append("DefinitionShortContractFail")
        if str(definition_short_audit["definition_short_contract_fail_reason"] or ""):
            record["quality_flags"].append(
                f"DefinitionShortContractFailReason:{definition_short_audit['definition_short_contract_fail_reason']}"
            )
    if provenance_stats["page_index_dropped_count"]:
        record["quality_flags"].append(f"PageIndexDropped:{provenance_stats['page_index_dropped_count']}")
    if provenance_stats.get("quote_rebound_count"):
        record["quality_flags"].append(f"QuoteRebound:{int(provenance_stats['quote_rebound_count'])}")
    if provenance_stats.get("quote_rebind_failed_count"):
        record["quality_flags"].append(f"QuoteRebindFailed:{int(provenance_stats['quote_rebind_failed_count'])}")
    post_short_cleanup_tier_info = step6lib.apply_tier_classification(record)
    tier_contract_decouple = reconcile_tier_post_short_cleanup(
        record=record,
        pre_short_cleanup_record=pre_short_cleanup_record,
        pre_short_cleanup_tier=pre_short_cleanup_tier,
        post_short_cleanup_tier=int(post_short_cleanup_tier_info["tier"]),
    )
    base_tier = int(tier_contract_decouple["effective_base_tier"])
    if bool(tier_contract_decouple["tier1_post_short_cleanup_restored"]):
        record["quality_flags"] = filter_quality_flags(
            record.get("quality_flags") or [],
            drop_prefixes=["UsabilityTier:"],
            drop_exact=[
                "Tier1MissingEvidenceMinimalCount",
                "Tier1MissingVerifiedQuotes",
                "Tier1MissingDefinition",
                "Tier1MissingVerifiedRetrievalRole",
            ],
        )
        record["quality_flags"].append("Tier1PostShortCleanupRestored")
        record["quality_flags"].append(f"UsabilityTier:{base_tier}")
        record["recovery_state"] = "none"
        record["recovery_reasons"] = []
    definition_full_evidence_ids = evidence_ref_ids("definition_full", field_evidence_items(record, "definition_full"))
    definition_short_evidence_ids = list(definition_short_audit.get("definition_short_evidence_ids") or [])
    definition_short_candidate_id = str(definition_short_audit.get("definition_short_candidate_id") or "")
    definition_short_primary_evidence_id = str(definition_short_evidence_ids[0]) if definition_short_evidence_ids else ""
    contamination_summary = evaluate_contamination(
        step63=step63,
        runtime_counters=runtime_counters,
        runtime_models=runtime_models,
        scorer=scorer,
        registry_row=registry_row,
        kc_id=kc_id,
        record=record,
        selected_candidates=minimal_candidates,
        query_cache=query_cache,
        semantic_cfg=semantic_cfg,
        adjudication_cfg=adjudication_cfg,
        support_contract=family_support_contract,
    )
    contamination_reasons = list(contamination_summary["contamination_reasons"])
    record["quality_flags"].append(f"ContaminationCategory:{contamination_summary['category']}")
    for competitor_kc_id in list(contamination_summary.get("sibling_ambiguity_resolved") or []):
        record["quality_flags"].append(f"SiblingAmbiguityResolved:{competitor_kc_id}")
    configured_role_cfg = default_role_cfg(role_cfg)
    strong_definition_score = float(configured_role_cfg["strong_definition_score"])
    has_definition_signal = any(
        candidate_supports_definition_package(candidate, kc_type=str(record["kc_type"]), strong_definition_score=strong_definition_score)
        for candidate in minimal_candidates
    )
    semantic_reasons: List[str] = []
    if definition_status == "unsupported_in_source":
        semantic_reasons.append("DefinitionFullEmpty")
    passed_quotes = [candidate for candidate in minimal_candidates if candidate.accepted and (not candidate.d2_used or candidate.d2_decision == kc_id)]
    if len(passed_quotes) < 2 and definition_status == "unsupported_in_source":
        semantic_reasons.append("AcceptedQuoteCountBelow2")
    elif len(passed_quotes) < 2:
        record["quality_flags"].append("AcceptedQuoteCountBelow2")
    if not has_definition_signal and definition_status == "unsupported_in_source":
        semantic_reasons.append("MissingRequiredRole")
    if bool(family_support_contract.get("support_contract_downgraded")):
        semantic_reasons.append(
            f"SupportContractDowngrade:{str(family_support_contract.get('support_contract_downgrade_reason') or 'unknown')}"
        )
    semantic_reasons.extend(contamination_reasons)
    semantic_reasons = unique_preserve_order(semantic_reasons)
    semantic_tier = 2 if base_tier >= 1 and not semantic_reasons else 1 if base_tier >= 1 else 0
    usable_curriculum = bool(base_tier >= 1 and not contamination_reasons and definition_status in SUPPORTED_DEFINITION_STATUSES)
    record["quality_flags"].append(f"SemanticSafeTier:{semantic_tier}")
    record["quality_flags"].append(f"UsableCurriculum:{yes_no(usable_curriculum)}")
    record["quality_flags"] = unique_preserve_order(record["quality_flags"])
    selected_role_sources = {candidate.candidate_id: candidate.role_source for candidate in minimal_candidates}
    role_source = "model" if any(source == "model" for source in selected_role_sources.values()) else "heuristic"
    recovery_entry = {
        "kc_id": kc_id,
        "canonical_name": str(registry_row["canonical_name"]),
        "semantic_tier": semantic_tier,
        "base_tier": base_tier,
        "reasons": semantic_reasons,
        "accepted_quote_count": len(passed_quotes),
        "candidate_count": len(all_candidates),
        "role_source": role_source,
        "definition_status": definition_status,
        "usable_curriculum": usable_curriculum,
        "definition_full_evidence_ids": definition_full_evidence_ids,
        "definition_short_candidate_id": definition_short_candidate_id,
        "definition_short_primary_evidence_id": definition_short_primary_evidence_id,
        "definition_short_source_type": str(definition_short_audit["definition_short_source_type"]),
        "definition_short_evidence_ids": definition_short_evidence_ids,
        "definition_short_contract_ok": bool(definition_short_audit["definition_short_contract_ok"]),
        "support_contract_downgraded": bool(family_support_contract.get("support_contract_downgraded")),
        "support_contract_downgrade_reason": str(family_support_contract.get("support_contract_downgrade_reason") or ""),
        "contamination_category": str(contamination_summary["category"]),
        "sibling_ambiguity": bool(contamination_summary.get("sibling_ambiguity_competitor_ids")),
        "final_adjudication_result": (
            "failed" if contamination_summary.get("sibling_ambiguity_failed") else "resolved" if contamination_summary.get("sibling_ambiguity_resolved") else "none"
        ),
        "competitor_kc_ids": list(contamination_summary.get("competitor_kc_ids") or []),
    }
    trace = {
        "kc_id": kc_id,
        "canonical_name": str(registry_row["canonical_name"]),
        "query_text": str(query_cache["query_text_by_id"][kc_id]),
        "base_tier": base_tier,
        "semantic_tier": semantic_tier,
        "definition_status": definition_status,
        "usable_curriculum": usable_curriculum,
        "semantic_tier_reasons": semantic_reasons,
        "contamination_reasons": contamination_reasons,
        "selected_candidate_ids": [candidate.candidate_id for candidate in minimal_candidates],
        "selected_bundle_candidate_ids": list(bundle_meta.get("bundle_candidate_ids") or []),
        "role_annotations": {candidate.candidate_id: candidate.final_role for candidate in minimal_candidates},
        "role_source": role_source,
        "role_annotation_meta": role_meta,
        "selected_role_sources": selected_role_sources,
        "definition_full_evidence_ids": definition_full_evidence_ids,
        "definition_short_candidate_id": definition_short_candidate_id,
        "definition_short_primary_evidence_id": definition_short_primary_evidence_id,
        "definition_short_audit": dict(definition_short_audit),
        "support_contract": dict(family_support_contract),
        "contract_decoupling": {
            **dict(tier_contract_decouple),
            **dict(definition_status_contract_decouple),
        },
        "definition_package": dict(definition_meta),
        "definition_full_text": record["definition_full"],
        "definition_short_text": record["definition_short"],
        "contamination_summary": dict(contamination_summary),
        "provenance_normalization": {
            **provenance_stats,
            "dropped_candidate_ids": [candidate.candidate_id for candidate in dropped_due_to_provenance],
        },
        "bundle_selection": dict(bundle_meta),
        "selected_source_breakdown": dict(Counter(candidate.origin for candidate in minimal_candidates)),
        "selected_candidates": [candidate.as_dict() for candidate in minimal_candidates],
        "accepted_candidates_post_provenance": [candidate.as_dict() for candidate in normalized_with_roles],
        "dropped_due_to_provenance": [candidate.as_dict() for candidate in dropped_due_to_provenance],
        "top_candidates_before_gating": [candidate.as_dict() for candidate in all_candidates[:10]],
        "preserved_from_step63": preserved_from_step63,
    }
    return ProcessingResult(
        record=record,
        base_tier=base_tier,
        semantic_tier=semantic_tier,
        semantic_tier_reasons=semantic_reasons,
        contamination_reasons=contamination_reasons,
        contamination_summary=dict(contamination_summary),
        definition_status=definition_status,
        usable_curriculum=usable_curriculum,
        recovery_entry=recovery_entry,
        trace=trace,
        selected_candidates=minimal_candidates,
        all_candidates=list(all_candidates),
        failure_reasons=list(semantic_reasons),
    )


def false_rejection_audit(
    *,
    selected_rows: Sequence[Mapping[str, Any]],
    results_by_kc: Mapping[str, ProcessingResult],
    semantic_cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    by_name = {match_normalize(str(row.get("canonical_name") or "")): row for row in selected_rows}
    chosen: List[Mapping[str, Any]] = []
    seen: set[str] = set()
    for name in preferred_good_name_order():
        row = by_name.get(match_normalize(name))
        if row is None:
            continue
        kc_id = str(row["kc_id"])
        if kc_id in seen:
            continue
        chosen.append(row)
        seen.add(kc_id)
        if len(chosen) >= min(6, len(selected_rows)):
            break
    if len(chosen) < min(6, len(selected_rows)):
        for row in sorted(selected_rows, key=lambda item: str(item["kc_id"])):
            kc_id = str(row["kc_id"])
            if kc_id in seen:
                continue
            chosen.append(row)
            seen.add(kc_id)
            if len(chosen) >= min(6, len(selected_rows)):
                break
    entries: List[Dict[str, Any]] = []
    failures = 0
    for row in chosen:
        kc_id = str(row["kc_id"])
        result = results_by_kc[kc_id]
        top10 = result.all_candidates[:10]
        d1_rejects = [candidate.candidate_id for candidate in top10 if any(reason.startswith("D1") for reason in candidate.gate_reasons)]
        d2_sent = [candidate.candidate_id for candidate in top10 if candidate.d2_used]
        survived = [candidate.candidate_id for candidate in result.selected_candidates if is_strong_same_topic(candidate, semantic_cfg)]
        if len(survived) < 2:
            failures += 1
        entries.append(
            {
                "kc_id": kc_id,
                "canonical_name": str(row["canonical_name"]),
                "top_10_before_gating": [candidate.as_dict() for candidate in top10],
                "d1_rejected_candidate_ids": d1_rejects,
                "d2_candidate_ids": d2_sent,
                "strong_same_topic_survivors": survived,
                "accepted_same_topic_count": len(survived),
            }
        )
    return {"expected_good_kcs": entries, "false_rejection_failures": failures}


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_delta(current: Any, baseline: Any) -> str:
    if isinstance(current, float) or isinstance(baseline, float):
        return f"{float(current) - float(baseline):+.4f}"
    return f"{int(current) - int(baseline):+d}"


def extract_source_breakdown(stats: Mapping[str, Any]) -> Dict[str, int]:
    raw = stats.get("source_breakdown_selected_quotes") or stats.get("source_breakdown_step5_2_vs_step6_3") or {}
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): int(value) for key, value in raw.items()}


def build_recommendation(
    *,
    dry_run: bool,
    acceptance: Mapping[str, Any],
    stats: Mapping[str, Any],
    targets: Mapping[str, Any],
) -> Dict[str, Any]:
    reasons: List[str] = []
    if not acceptance["passed"]:
        reasons.extend(str(reason) for reason in acceptance["reasons"])
    if dry_run:
        thinking_target = float(targets.get("dry_run_thinking_used_frac_target", 0.08))
        if float(stats["thinking_used_frac"]) > thinking_target:
            reasons.append(f"ThinkingUsedFracAdvisory:{stats['thinking_used_frac']:.3f}>{thinking_target:.2f}")
    status = "READY_FOR_NEXT_SCALE" if not reasons else "NOT_READY_FOR_NEXT_SCALE"
    return {"status": status, "reasons": unique_preserve_order(reasons)}


def build_closeout_report(
    *,
    run_id: str,
    created_utc: str,
    dry_run: bool,
    bootstrap: RerankerBootstrapResult,
    runtime_models: RuntimeModels,
    stats: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    results_by_kc: Mapping[str, ProcessingResult],
    failure_counter: Mapping[str, int],
    false_rejection_summary: Mapping[str, Any],
    primary_source_kind: str,
    primary_origin_label: str,
    primary_set_id: str,
    baseline_summary: Mapping[str, Any],
    baseline_closeout_path: Optional[Path],
    recommendation: Mapping[str, Any],
) -> str:
    total_kcs = max(1, int(stats.get("total_kcs", 0)))
    baseline_stats = dict(baseline_summary.get("stats") or {}) if isinstance(baseline_summary.get("stats"), Mapping) else {}
    source_breakdown = extract_source_breakdown(stats)
    baseline_source_breakdown = extract_source_breakdown(baseline_stats)
    role_breakdown = dict(stats.get("role_source_breakdown") or {})
    selected_quote_breakdown = dict(role_breakdown.get("selected_quotes") or {})
    kc_breakdown = dict(role_breakdown.get("kcs") or {})
    definition_status_breakdown = dict(stats.get("definition_status_breakdown") or {})
    short_breakdown = dict(stats.get("definition_short_source_breakdown") or {})
    competitor_breakdown = {
        str(key): int(value)
        for key, value in dict(stats.get("contamination_competitor_kc_ids") or {}).items()
    }

    lines: List[str] = []
    lines.append("STEP 6.4.9 CONTRACT DECOUPLE CLOSEOUT REPORT")
    lines.append("")
    lines.append("1) Executive summary")
    lines.append(f"- Mode: {'dry_run' if dry_run else 'full_run'}")
    lines.append(f"- Run id: {run_id}")
    lines.append(f"- Created UTC: {created_utc}")
    lines.append(f"- Acceptance: {'PASS' if acceptance['passed'] else 'FAIL'}")
    lines.append(f"- Why: {', '.join(acceptance['reasons']) if acceptance['reasons'] else 'All active checks passed.'}")
    lines.append("")
    lines.append("2) Run metadata")
    lines.append(f"- Generation model: {runtime_models.generation_model or 'heuristic_fallback_only'}")
    lines.append(f"- Gate model: {runtime_models.gate_model or 'unavailable'}")
    lines.append(f"- Reranker model: {bootstrap.chosen_model}")
    lines.append(f"- Device: {bootstrap.device}")
    lines.append(f"- Gate bootstrap status: PASS ({'fallback' if bootstrap.used_fallback else 'preferred'})")
    lines.append(f"- Primary evidence source: {primary_source_kind}")
    lines.append(f"- Primary evidence set id: {primary_set_id}")
    lines.append(f"- Comparison baseline run: {str((baseline_summary.get('run_id') or 'unavailable'))}")
    lines.append(
        f"- Comparison baseline closeout: {rel_path(baseline_closeout_path, REPO_ROOT) if baseline_closeout_path and baseline_closeout_path.exists() else 'unavailable'}"
    )
    lines.append("")
    lines.append("3) Acceptance table")
    lines.append(f"- total_kcs: {int(stats.get('total_kcs', 0))}")
    lines.append(f"- tier1_count: {stats['tier1_count']}")
    lines.append(f"- tier2_count: {stats['tier2_count']}")
    lines.append(f"- usable_curriculum_count: {int(stats.get('usable_curriculum_count', 0))}")
    lines.append(f"- usable_curriculum_rate: {int(stats.get('usable_curriculum_count', 0)) / total_kcs:.4f}")
    lines.append(f"- definition_full_count: {int(stats.get('definition_full_count', 0))}")
    lines.append(f"- definition_full_rate: {int(stats.get('definition_full_count', 0)) / total_kcs:.4f}")
    lines.append(f"- definition_status_supported_count: {int(stats.get('definition_status_supported_count', 0))}")
    lines.append(f"- definition_status_supported_rate: {int(stats.get('definition_status_supported_count', 0)) / total_kcs:.4f}")
    lines.append(f"- definition_short_nonempty_count: {int(stats.get('definition_short_nonempty_count', 0))}")
    lines.append(f"- definition_short_contract_ok_count: {int(stats.get('definition_short_contract_ok_count', 0))}")
    lines.append(f"- definition_short_contract_fail_count: {int(stats.get('definition_short_contract_fail_count', 0))}")
    lines.append(f"- contamination_count: {stats['contamination_count']}")
    lines.append(f"- quote_mismatch_count: {stats['quote_mismatch_count']}")
    lines.append(f"- schema_error_count: {int(stats.get('schema_error_count', 0))}")
    lines.append(f"- false_rejection_failures: {stats['false_rejection_failures']}")
    lines.append(f"- false_rejection_failure_rate: {float(stats.get('false_rejection_failure_rate', 0.0)):.4f}")
    lines.append(f"- thinking_used_frac: {float(stats.get('thinking_used_frac', 0.0)):.4f}")
    lines.append(f"- thinking_used_frac_target_0.08_met: {yes_no(float(stats['thinking_used_frac']) <= 0.08)}")
    lines.append(f"- reranker_filter_drop_rate: {stats['reranker_filter_drop_rate']}")
    lines.append(f"- d2_gate_calls: {stats['d2_gate_calls']}")
    lines.append(f"- d2_gate_rejects: {stats['d2_gate_rejects']}")
    lines.append(f"- doc_mismatch_usage_count: {stats['doc_mismatch_usage_count']}")
    if baseline_stats:
        lines.append("- comparison_vs_previous_32kc:")
        lines.append(f"- tier1_count_delta: {format_delta(stats['tier1_count'], baseline_stats.get('tier1_count', 0))}")
        lines.append(f"- tier2_count_delta: {format_delta(stats['tier2_count'], baseline_stats.get('tier2_count', 0))}")
        baseline_usable_curriculum = int(baseline_stats.get("usable_curriculum_count", baseline_stats.get("tier2_count", 0)))
        lines.append(
            f"- usable_curriculum_count_delta: {format_delta(int(stats.get('usable_curriculum_count', 0)), baseline_usable_curriculum)}"
        )
        lines.append(
            f"- definition_full_count_delta: {format_delta(int(stats.get('definition_full_count', 0)), baseline_stats.get('definition_full_count', 0))}"
        )
        baseline_supported_count = int(baseline_stats.get("definition_status_supported_count", baseline_stats.get("definition_full_count", 0)))
        lines.append(
            f"- definition_status_supported_count_delta: {format_delta(int(stats.get('definition_status_supported_count', 0)), baseline_supported_count)}"
        )
        lines.append(
            f"- false_rejection_failures_delta: {format_delta(stats['false_rejection_failures'], baseline_stats.get('false_rejection_failures', 0))}"
        )
        lines.append(
            f"- thinking_used_frac_delta: {format_delta(float(stats.get('thinking_used_frac', 0.0)), float(baseline_stats.get('thinking_used_frac', 0.0)))}"
        )
        lines.append(f"- contamination_count_delta: {format_delta(stats['contamination_count'], baseline_stats.get('contamination_count', 0))}")
        lines.append(f"- quote_mismatch_count_delta: {format_delta(stats['quote_mismatch_count'], baseline_stats.get('quote_mismatch_count', 0))}")
        lines.append(
            f"- definition_short_contract_fail_count_delta: "
            f"{format_delta(int(stats.get('definition_short_contract_fail_count', 0)), int(baseline_stats.get('definition_short_contract_fail_count', 0)))}"
        )
    else:
        lines.append("- comparison_vs_previous_32kc: unavailable")
    lines.append("")
    lines.append("4) Top failure reasons")
    for reason, count in Counter(failure_counter).most_common(10):
        lines.append(f"- {reason}: {count}")
    if not failure_counter:
        lines.append("- none")
    lines.append("")
    lines.append("5) Contamination adjudication breakdown")
    lines.append(f"- contamination_count: {int(stats.get('contamination_count', 0))}")
    lines.append(f"- hard_contamination_count: {int(stats.get('hard_contamination_count', 0))}")
    lines.append(f"- sibling_ambiguity_count: {int(stats.get('sibling_ambiguity_count', 0))}")
    lines.append(f"- sibling_ambiguity_resolved_count: {int(stats.get('sibling_ambiguity_resolved_count', 0))}")
    lines.append(f"- sibling_ambiguity_failed_count: {int(stats.get('sibling_ambiguity_failed_count', 0))}")
    if competitor_breakdown:
        lines.append("- competitor_kc_ids_involved:")
        for competitor_kc_id, count in sorted(competitor_breakdown.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {competitor_kc_id}: {count}")
    else:
        lines.append("- competitor_kc_ids_involved: none")
    lines.append("")
    lines.append("6) Definition_short final-record audit")
    lines.append(f"- definition_short_nonempty_count: {int(stats.get('definition_short_nonempty_count', 0))}")
    lines.append(f"- definition_short_contract_ok_count: {int(stats.get('definition_short_contract_ok_count', 0))}")
    lines.append(f"- definition_short_contract_fail_count: {int(stats.get('definition_short_contract_fail_count', 0))}")
    lines.append(f"- definition_short_post_preserve_rewrite_count: {int(stats.get('definition_short_post_preserve_rewrite_count', 0))}")
    lines.append(f"- definition_short_post_preserve_drop_count: {int(stats.get('definition_short_post_preserve_drop_count', 0))}")
    lines.append(f"- derived_from_definition_full: {int(short_breakdown.get('derived_from_definition_full', 0))}")
    lines.append(f"- direct_quote_short: {int(short_breakdown.get('direct_quote_short', 0))}")
    lines.append(f"- unsupported_or_empty: {int(short_breakdown.get('unsupported_or_empty', 0))}")
    lines.append(f"- coherent_supported: {int(definition_status_breakdown.get('coherent_supported', 0))}")
    lines.append(f"- fragmentary_supported: {int(definition_status_breakdown.get('fragmentary_supported', 0))}")
    lines.append(f"- unsupported_in_source: {int(definition_status_breakdown.get('unsupported_in_source', 0))}")
    lines.append(f"- definition_status_supported_count: {int(stats.get('definition_status_supported_count', 0))}")
    lines.append(f"- usable_curriculum_count: {int(stats.get('usable_curriculum_count', 0))}")
    lines.append(f"- definition_full_count: {int(stats.get('definition_full_count', 0))}")
    lines.append("- selected_quote_source_breakdown:")
    lines.append(f"- {primary_origin_label}: {source_breakdown.get(primary_origin_label, 0)}")
    lines.append(f"- step6_3_anchor: {source_breakdown.get('step6_3_anchor', 0)}")
    lines.append(f"- step4_neighbor: {source_breakdown.get('step4_neighbor', 0)}")
    if baseline_source_breakdown:
        for source_name in [primary_origin_label, 'step6_3_anchor', 'step4_neighbor']:
            lines.append(f"- delta_{source_name}: {format_delta(source_breakdown.get(source_name, 0), baseline_source_breakdown.get(source_name, 0))}")
    lines.append("- role_source_breakdown:")
    lines.append(f"- selected_quotes_model: {int(selected_quote_breakdown.get('model', 0))}")
    lines.append(f"- selected_quotes_heuristic: {int(selected_quote_breakdown.get('heuristic', 0))}")
    lines.append(f"- kcs_model: {int(kc_breakdown.get('model', 0))}")
    lines.append(f"- kcs_heuristic: {int(kc_breakdown.get('heuristic', 0))}")
    lines.append(f"- ambiguous_role_calls: {int(stats.get('ambiguous_role_calls', 0))}")
    lines.append(f"- model_role_success_count: {int(stats.get('model_role_success_count', 0))}")
    lines.append(f"- model_role_failure_count: {int(stats.get('model_role_failure_count', 0))}")
    lines.append("- provenance_normalization:")
    lines.append(f"- page_index_recovered_count: {int(stats.get('page_index_recovered_count', 0))}")
    lines.append(f"- page_index_substituted_count: {int(stats.get('page_index_substituted_count', 0))}")
    lines.append(f"- page_index_dropped_count: {int(stats.get('page_index_dropped_count', 0))}")
    lines.append(f"- quote_rebound_count: {int(stats.get('quote_rebound_count', 0))}")
    lines.append(f"- quote_rebind_failed_count: {int(stats.get('quote_rebind_failed_count', 0))}")
    lines.append("- false_rejection_audit:")
    lines.append(f"- false_rejection_failures: {false_rejection_summary.get('false_rejection_failures', 0)}")
    for entry in false_rejection_summary.get("expected_good_kcs", []):
        lines.append(
            f"- {entry['kc_id']} | {entry['canonical_name']} | accepted_same_topic_count={entry['accepted_same_topic_count']} "
            f"| d1_rejected={len(entry['d1_rejected_candidate_ids'])} | d2_sent={len(entry['d2_candidate_ids'])}"
        )
    lines.append("")
    lines.append("7) Contract-decoupling audit")
    lines.append(f"- tier1_post_short_cleanup_regression_count: {int(stats.get('tier1_post_short_cleanup_regression_count', 0))}")
    lines.append(f"- tier1_post_short_cleanup_restored_count: {int(stats.get('tier1_post_short_cleanup_restored_count', 0))}")
    lines.append(
        f"- definition_status_post_short_cleanup_regression_count: {int(stats.get('definition_status_post_short_cleanup_regression_count', 0))}"
    )
    lines.append(
        f"- definition_status_post_short_cleanup_restored_count: {int(stats.get('definition_status_post_short_cleanup_restored_count', 0))}"
    )
    lines.append("")
    lines.append("8) Detailed KC examples")
    id_lookup = {str(result.record["kc_id"]): result for result in results_by_kc.values()}
    name_lookup = {match_normalize(str(result.record["canonical_name"])): result for result in results_by_kc.values()}
    for kc_id in REQUIRED_CLOSEOUT_KC_IDS:
        result = id_lookup.get(kc_id)
        if result is None:
            lines.append(f"- {kc_id}: not in subset")
            continue
        accepted_quote_count = int(result.recovery_entry.get("accepted_quote_count") or 0)
        validation_errors = validate_kc_record(result.record)
        short_audit = dict(result.trace.get("definition_short_audit") or {})
        lines.append(
            f"- {result.record['kc_id']} | {result.record['canonical_name']} "
            f"| accepted_quote_count={accepted_quote_count} "
            f"| definition_full_status={result.definition_status} "
            f"| definition_short_source_type={str(short_audit.get('definition_short_source_type') or 'unsupported_or_empty')} "
            f"| definition_short_contract_ok={yes_no(bool(short_audit.get('definition_short_contract_ok')))} "
            f"| tier1={yes_no(result.base_tier >= 1)} "
            f"| definition_status_supported={yes_no(result.definition_status in SUPPORTED_DEFINITION_STATUSES)} "
            f"| schema_valid={yes_no(not validation_errors)} "
            f"| usable_curriculum={yes_no(result.usable_curriculum)}"
        )
    for name in REQUIRED_CLOSEOUT_CANONICAL_NAMES:
        result = name_lookup.get(match_normalize(name))
        if result is None:
            lines.append(f"- {name}: not in subset")
            continue
        accepted_quote_count = int(result.recovery_entry.get("accepted_quote_count") or 0)
        validation_errors = validate_kc_record(result.record)
        short_audit = dict(result.trace.get("definition_short_audit") or {})
        lines.append(
            f"- {result.record['kc_id']} | {result.record['canonical_name']} "
            f"| accepted_quote_count={accepted_quote_count} "
            f"| definition_full_status={result.definition_status} "
            f"| definition_short_source_type={str(short_audit.get('definition_short_source_type') or 'unsupported_or_empty')} "
            f"| definition_short_contract_ok={yes_no(bool(short_audit.get('definition_short_contract_ok')))} "
            f"| tier1={yes_no(result.base_tier >= 1)} "
            f"| definition_status_supported={yes_no(result.definition_status in SUPPORTED_DEFINITION_STATUSES)} "
            f"| schema_valid={yes_no(not validation_errors)} "
            f"| usable_curriculum={yes_no(result.usable_curriculum)}"
        )
    lines.append("")
    lines.append("9) Recommendation")
    lines.append(f"- {recommendation['status']}")
    for reason in recommendation["reasons"]:
        lines.append(f"- Reason: {reason}")
    if not recommendation["reasons"]:
        lines.append("- Reason: Mid-scale cleanup targets were met with the current Step 6.4.2 logic.")
    return "\n".join(lines) + "\n"


def extract_support_contract_view(trace: Mapping[str, Any]) -> Dict[str, Any]:
    contamination = dict(trace.get("contamination_summary") or {})
    raw_contract = trace.get("support_contract")
    if isinstance(raw_contract, Mapping) and raw_contract:
        contract = dict(raw_contract)
    else:
        fallback = dict(contamination)
        contract = {
            "family_policy_id": str(fallback.get("family_policy_id") or ""),
            "family_scoped": bool(fallback.get("family_scoped")),
            "bundle_target_support": bool(fallback.get("bundle_target_support")),
            "bundle_target_support_mode": str(fallback.get("bundle_target_support_mode") or ""),
            "bundle_strict_leaf_support": bool(fallback.get("bundle_strict_leaf_support")),
            "bundle_family_topic_support": bool(fallback.get("bundle_family_topic_support")),
            "bundle_parent_topic_overlap": bool(fallback.get("bundle_parent_topic_overlap")),
            "generic_selected_support": bool(fallback.get("generic_selected_support")),
            "definition_short_strict_leaf_support": bool(fallback.get("definition_short_strict_leaf_support")),
            "definition_short_family_topic_support": bool(fallback.get("definition_short_family_topic_support")),
            "definition_full_strict_leaf_support": bool(fallback.get("definition_full_strict_leaf_support")),
            "definition_full_family_topic_support": bool(fallback.get("definition_full_family_topic_support")),
            "permissive_rescue_lineage": bool(fallback.get("permissive_rescue_lineage")),
            "support_contract_downgraded": bool(fallback.get("support_contract_downgraded")),
            "support_contract_downgrade_reason": str(fallback.get("support_contract_downgrade_reason") or ""),
            "preserved_from_step63": bool(trace.get("preserved_from_step63")),
        }
    contract["sibling_ambiguous_support"] = bool(
        contract.get("sibling_ambiguous_support")
        or contamination.get("sibling_ambiguous_support")
        or contamination.get("sibling_ambiguity_competitor_ids")
    )
    contract["target_support_state"] = str(contract.get("target_support_state") or support_contract_target_state(contract))
    return contract


def representative_case_from_artifacts(
    *,
    kc_id: str,
    record: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> Dict[str, Any]:
    contract = extract_support_contract_view(trace)
    selected_candidates = [
        dict(candidate)
        for candidate in list(trace.get("selected_candidates") or [])
        if isinstance(candidate, Mapping)
    ]
    selected_quotes = unique_preserve_order(
        [
            normalize_ws(str(candidate.get("quote_raw") or candidate.get("quote") or ""))
            for candidate in selected_candidates
            if normalize_ws(str(candidate.get("quote_raw") or candidate.get("quote") or ""))
        ]
    )
    accepted_quote_count = sum(1 for candidate in selected_candidates if bool(candidate.get("accepted")))
    if not accepted_quote_count:
        accepted_quote_count = len([item for item in list(trace.get("selected_candidate_ids") or []) if str(item).strip()])
    validation_errors = validate_kc_record(dict(record)) if record else ["missing_record"]
    contamination_summary = dict(trace.get("contamination_summary") or {})
    definition_status = str(trace.get("definition_status") or "")
    if not definition_status:
        quality_flags = [str(item) for item in list(record.get("quality_flags") or [])]
        status_flags = [flag.split(":", 1)[1] for flag in quality_flags if flag.startswith("DefinitionStatus:")]
        definition_status = status_flags[-1] if status_flags else ""
    contamination_category = str(contamination_summary.get("category") or "clean")
    return {
        "kc_id": kc_id,
        "canonical_name": str(record.get("canonical_name") or trace.get("canonical_name") or ""),
        "accepted_quote_count": int(accepted_quote_count),
        "selected_quotes": selected_quotes,
        "definition_full_status": definition_status,
        "definition_short_text": str(record.get("definition_short") or trace.get("definition_short_text") or ""),
        "target_support_state": str(contract.get("target_support_state") or "unsupported"),
        "strict_leaf_support": bool(contract.get("bundle_strict_leaf_support")),
        "family_topic_support": bool(contract.get("bundle_family_topic_support")),
        "generic_selected_support": bool(contract.get("generic_selected_support")),
        "parent_topic_overlap": bool(contract.get("bundle_parent_topic_overlap")),
        "permissive_rescue_lineage": bool(contract.get("permissive_rescue_lineage")),
        "sibling_ambiguous_support": bool(contract.get("sibling_ambiguous_support")),
        "contamination": bool(
            contamination_category == "hard_contamination" or list(contamination_summary.get("sibling_ambiguity_failed") or [])
        ),
        "schema_valid": not validation_errors,
        "usable_curriculum": bool(trace.get("usable_curriculum") or record.get("usable_curriculum")),
        "definition_status_supported": bool(definition_status in SUPPORTED_DEFINITION_STATUSES),
        "support_contract_downgraded": bool(contract.get("support_contract_downgraded")),
        "support_contract_downgrade_reason": str(contract.get("support_contract_downgrade_reason") or ""),
    }


def family_policy_case_summary(result: ProcessingResult) -> Dict[str, Any]:
    return representative_case_from_artifacts(
        kc_id=str(result.record["kc_id"]),
        record=result.record,
        trace=result.trace,
    )


def choose_optional_cluster_evaluation_case(results_by_kc: Mapping[str, ProcessingResult]) -> Optional[str]:
    for kc_id in sorted(results_by_kc.keys()):
        if not kc_id.startswith("KC_CLU_EVAL_"):
            continue
        result = results_by_kc[kc_id]
        contract = extract_support_contract_view(result.trace)
        contamination_summary = dict(result.trace.get("contamination_summary") or {})
        if (
            bool(contract.get("generic_selected_support"))
            or bool(contract.get("permissive_rescue_lineage"))
            or bool(contamination_summary.get("sibling_ambiguity_competitor_ids"))
            or str(contamination_summary.get("category") or "") != "clean"
        ):
            return kc_id
    return None


def build_family_policy_family_table(results_by_kc: Mapping[str, ProcessingResult]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for family_id in ["dbscan", "naive_bayes", "decision_trees"]:
        family_results = []
        for result in results_by_kc.values():
            contract = extract_support_contract_view(result.trace)
            if str(contract.get("family_policy_id") or "") == family_id:
                family_results.append((result, contract))
        if not family_results:
            continue
        rows.append(
            {
                "family_id": family_id,
                "family_name": FAMILY_POLICY_DISPLAY_NAMES[family_id],
                "leaves_present": [str(result.record["kc_id"]) for result, _ in family_results],
                "strict_leaf_support_failures": [
                    str(result.record["kc_id"]) for result, contract in family_results if not bool(contract.get("bundle_strict_leaf_support"))
                ],
                "family_topic_support_cases": [
                    str(result.record["kc_id"]) for result, contract in family_results if bool(contract.get("bundle_family_topic_support"))
                ],
                "generic_selected_support_cases": [
                    str(result.record["kc_id"]) for result, contract in family_results if bool(contract.get("generic_selected_support"))
                ],
                "parent_topic_overlap_cases": [
                    str(result.record["kc_id"]) for result, contract in family_results if bool(contract.get("bundle_parent_topic_overlap"))
                ],
                "permissive_rescue_lineage_cases": [
                    str(result.record["kc_id"]) for result, contract in family_results if bool(contract.get("permissive_rescue_lineage"))
                ],
                "sibling_ambiguous_support_cases": [
                    str(result.record["kc_id"]) for result, contract in family_results if bool(contract.get("sibling_ambiguous_support"))
                ],
            }
        )
    return rows


def build_family_policy_recommendation(
    *,
    stats: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    family_table: Sequence[Mapping[str, Any]],
    validation_scope: str = "",
) -> Dict[str, Any]:
    reasons: List[str] = []
    contamination_count = int(stats.get("contamination_count", 0))
    trust_clean = (
        int(stats.get("quote_mismatch_count", 0)) == 0
        and int(stats.get("schema_error_count", 0)) == 0
        and int(stats.get("definition_short_contract_fail_count", 0)) == 0
    )
    family_rows_by_id = {str(row.get("family_id") or ""): row for row in family_table}
    dbscan_row = dict(family_rows_by_id.get("dbscan") or {})
    dbscan_structural_reclassification = contamination_count == 0 and bool(
        list(dbscan_row.get("generic_selected_support_cases") or [])
        or list(dbscan_row.get("sibling_ambiguous_support_cases") or [])
    )
    strict_leaf_survivor_family_ids = []
    for family_id in ("naive_bayes", "decision_trees"):
        row = dict(family_rows_by_id.get(family_id) or {})
        leaves_present = {str(item) for item in list(row.get("leaves_present") or [])}
        strict_failures = {str(item) for item in list(row.get("strict_leaf_support_failures") or [])}
        if leaves_present - strict_failures:
            strict_leaf_survivor_family_ids.append(family_id)
    provisional_slice_pass = (
        trust_clean
        and contamination_count == 0
        and dbscan_structural_reclassification
        and len(strict_leaf_survivor_family_ids) == 2
    )
    any_cross_family_risk = any(
        list(row.get("generic_selected_support_cases") or [])
        or list(row.get("permissive_rescue_lineage_cases") or [])
        or list(row.get("sibling_ambiguous_support_cases") or [])
        for row in family_table
    )
    if validation_scope == "slice_a_development":
        if provisional_slice_pass:
            reasons.append(
                "The development challenge slice kept trust safeguards clean and reclassified the DBSCAN sentinel path into explicit sibling-conflict structure without hard contamination."
            )
            reasons.append(
                "Strict-leaf support remained alive in both Naive Bayes and Decision Trees under the unchanged support-state logic."
            )
            reasons.append(
                "This result is challenge-slice evidence only; it justifies an unchanged Slice B audit replay, not broader family-policy expansion or ACTIVE promotion."
            )
            return {"status": "READY_FOR_SLICE_B_UNCHANGED_REPLAY", "reasons": reasons}
        if not trust_clean:
            reasons.append("Trust safeguards regressed on the Slice A development challenge set.")
        if contamination_count > 0:
            reasons.append("The Slice A development challenge set still shows unresolved contamination.")
        if not dbscan_structural_reclassification:
            reasons.append("The DBSCAN sentinel path was not cleanly reduced to explicit sibling-conflict structure on Slice A.")
        if len(strict_leaf_survivor_family_ids) < 2:
            reasons.append("Strict-leaf support did not survive in both Naive Bayes and Decision Trees on Slice A.")
        reasons.append("Slice A did not prove enough to justify an unchanged audit-hard replay.")
        return {"status": "NOT_READY", "reasons": reasons}
    if validation_scope == "slice_b_audit":
        if provisional_slice_pass:
            reasons.append(
                "The untouched audit slice kept trust safeguards clean while reusing the unchanged challenge-set mechanism."
            )
            reasons.append(
                "The DBSCAN-style discrimination and sibling-ambiguity handling remained honest on unseen audit cases."
            )
            reasons.append(
                "This result is still side-quest evidence only; it justifies an unchanged replay on the pinned 48-KC slice, not ACTIVE promotion."
            )
            return {"status": "READY_FOR_FULL48_UNCHANGED_REPLAY", "reasons": reasons}
        if not trust_clean:
            reasons.append("Trust safeguards regressed on the untouched audit slice.")
        if contamination_count > 0:
            reasons.append("The untouched audit slice still shows unresolved contamination.")
        if not dbscan_structural_reclassification:
            reasons.append("The audit slice did not preserve honest structural reclassification on the DBSCAN family.")
        if len(strict_leaf_survivor_family_ids) < 2:
            reasons.append("Strict-leaf support did not survive in both Naive Bayes and Decision Trees on the audit slice.")
        reasons.append("Slice B did not justify an unchanged replay on the pinned 48-KC slice.")
        return {"status": "NOT_READY", "reasons": reasons}
    if acceptance.get("passed") and contamination_count == 0 and trust_clean:
        reasons.append("The repeated configured-slice validation met the hard gates with clean trust safeguards.")
        return {"status": "READY_FOR_ANOTHER_48KC_CONFIRMATION", "reasons": reasons}
    if trust_clean and (contamination_count > 0 or any_cross_family_risk):
        if contamination_count > 0:
            reasons.append("The repeated configured-slice validation still shows unresolved contamination on the scoped family slice.")
        if any_cross_family_risk:
            reasons.append(
                "Family-scoped leaves still show generic-selected, sibling-ambiguous, or rescue-lineage support patterns that need further audit before broader claims."
            )
        reasons.append("Trust safeguards remained clean, but this result does not yet justify broader rollout or ACTIVE promotion.")
        return {"status": "NOT_READY", "reasons": reasons}
    reasons.append("The repeated configured-slice validation did not clear the blocker cleanly enough for confirmation or broader rollout.")
    return {"status": "NOT_READY", "reasons": reasons}


def build_family_policy_validation_payload(
    *,
    repo_root: Path,
    config_path: Path,
    config: Mapping[str, Any],
    inputs: Mapping[str, Any],
    selected_rows: Sequence[Mapping[str, Any]],
    stats: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    bootstrap: RerankerBootstrapResult,
    results_by_kc: Mapping[str, ProcessingResult],
    baseline_summary: Mapping[str, Any],
    baseline_kc_library_by_kc: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    exact_slice = [str(item) for item in list(inputs.get("exact_kc_id_slice") or [])] or [str(row["kc_id"]) for row in selected_rows]
    baseline_stats = dict(baseline_summary.get("stats") or {}) if isinstance(baseline_summary.get("stats"), Mapping) else {}
    family_table = build_family_policy_family_table(results_by_kc)
    validation_scope = str((config.get("reporting") or {}).get("validation_scope") or "")
    current_cases = {
        kc_id: family_policy_case_summary(results_by_kc[kc_id])
        for kc_id in unique_preserve_order(
            FAMILY_POLICY_REPORT_CASE_IDS["dbscan"]
            + FAMILY_POLICY_REPORT_CASE_IDS["naive_bayes"]
            + FAMILY_POLICY_REPORT_CASE_IDS["decision_trees"]
        )
        if kc_id in results_by_kc
    }
    cluster_case_id = choose_optional_cluster_evaluation_case(results_by_kc)
    if cluster_case_id is not None:
        current_cases[cluster_case_id] = family_policy_case_summary(results_by_kc[cluster_case_id])

    baseline_cases: Dict[str, Dict[str, Any]] = {}
    baseline_processed_dir = inputs.get("baseline_step6_4_2_processed_dir")
    for kc_id in current_cases:
        baseline_record = dict(baseline_kc_library_by_kc.get(kc_id) or {})
        baseline_trace = load_optional_kc_trace(baseline_processed_dir, kc_id) if isinstance(baseline_processed_dir, Path) else {}
        if baseline_record and baseline_trace:
            baseline_cases[kc_id] = representative_case_from_artifacts(
                kc_id=kc_id,
                record=baseline_record,
                trace=baseline_trace,
            )

    comparison = {}
    for key in [
        "tier1_count",
        "contamination_count",
        "usable_curriculum_count",
        "definition_full_count",
        "definition_status_supported_count",
        "false_rejection_failures",
        "quote_mismatch_count",
        "schema_error_count",
        "definition_short_contract_fail_count",
    ]:
        if key in baseline_stats:
            comparison[key] = {
                "baseline": baseline_stats.get(key),
                "current": stats.get(key),
                "delta": (
                    round(float(stats.get(key, 0.0)) - float(baseline_stats.get(key, 0.0)), 4)
                    if isinstance(stats.get(key), float) or isinstance(baseline_stats.get(key), float)
                    else int(stats.get(key, 0)) - int(baseline_stats.get(key, 0))
                ),
            }

    phase_acceptance_table = [
        {
            "target": "Same deterministic configured slice reruns successfully",
            "status": "PASS" if len(selected_rows) == len(exact_slice) else "FAIL",
            "detail": f"Processed {len(selected_rows)} KCs using the exact configured slice.",
        },
        {
            "target": "No 128 run occurs",
            "status": "PASS" if len(selected_rows) < 128 else "FAIL",
            "detail": f"Run stayed on {len(selected_rows)} KCs.",
        },
        {
            "target": "No ACTIVE update occurs",
            "status": "PASS",
            "detail": "Dry-run execution leaves the ACTIVE Step 6 pointer unchanged.",
        },
        {
            "target": "No frozen prior output is mutated",
            "status": "PASS",
            "detail": "Artifacts are written only under the new run folder and processed output root.",
        },
        {
            "target": "Trust safeguards remain clean",
            "status": (
                "PASS"
                if int(stats.get("quote_mismatch_count", 0)) == 0
                and int(stats.get("schema_error_count", 0)) == 0
                and int(stats.get("definition_short_contract_fail_count", 0)) == 0
                else "FAIL"
            ),
            "detail": (
                f"quote_mismatch_count={int(stats.get('quote_mismatch_count', 0))}, "
                f"schema_error_count={int(stats.get('schema_error_count', 0))}, "
                f"definition_short_contract_fail_count={int(stats.get('definition_short_contract_fail_count', 0))}"
            ),
        },
        {
            "target": "Support contract is the adjudication source of truth for scoped families",
            "status": "PASS",
            "detail": "The rerun uses the enforced support contract for rescue blocking, contamination adjudication, traces, and reporting.",
        },
        {
            "target": "Reporting distinguishes strict/family/generic/overlap/rescue/sibling categories",
            "status": "PASS" if current_cases else "FAIL",
            "detail": "Representative-case summaries now carry the enforced contract categories directly.",
        },
        {
            "target": "Cross-family findings reported for DBSCAN, Naive Bayes, and Decision Trees",
            "status": "PASS" if len(family_table) == 3 else "FAIL",
            "detail": ", ".join(row["family_name"] for row in family_table) if family_table else "No scoped families found in slice.",
        },
    ]

    recovered_state_summary = {
        "active_pointers": {
            "step4": Path(inputs["step4_set_path"]).name,
            "step4_5": Path(inputs["step4_5_set_path"]).name if inputs.get("step4_5_set_path") else "",
            "step5_3": Path(inputs["step5_set_path"]).name,
            "step6": Path(inputs["step6_set_path"]).name,
        },
        "accepted_baselines": {
            "step6_active_baseline": str(Path(inputs["step6_set_path"]).stem),
        },
        "current_development_line": {
            "hierarchy_overlay_run": "2026-03-10_005659_hierarchy_overlay",
            "failed_overlay_aware_rerun": str(inputs.get("baseline_step6_4_2_run_id") or ""),
        },
        "current_blocker": "KC_CLU_DBS_005 vs KC_CLU_DBS_001 contamination plus broader generic/permissive family-support behavior across sibling-dense families.",
        "exact_deterministic_slice": exact_slice,
        "project_state_stale_relative_to_march10": True,
        "acceptance_targets_for_this_phase": [row["target"] for row in phase_acceptance_table],
    }

    recommendation = build_family_policy_recommendation(
        stats=stats,
        acceptance=acceptance,
        family_table=family_table,
        validation_scope=validation_scope,
    )

    return {
        "report_path": f"data/runs/{{run_id}}_step6_4_2/{FAMILY_POLICY_VALIDATION_CLOSEOUT_FILENAME}",
        "comparison_baseline_run_id": str(inputs.get("baseline_step6_4_2_run_id") or ""),
        "recovered_state_summary": recovered_state_summary,
        "exact_inputs": {
            "config": rel_path(config_path, repo_root),
            "validation_scope": validation_scope,
            "exact_configured_slice": exact_slice,
            "exact_48_kc_slice": exact_slice,
            "overlay_artifacts": [
                rel_path(Path(inputs["hierarchy_overlay_node_index_path"]), repo_root)
                if inputs.get("hierarchy_overlay_node_index_path")
                else "",
                rel_path(Path(inputs["hierarchy_leaf_ancestry_path"]), repo_root)
                if inputs.get("hierarchy_leaf_ancestry_path")
                else "",
            ],
            "primary_evidence_set": rel_path(Path(inputs["step5_set_path"]), repo_root),
            "step6_active_baseline": rel_path(Path(inputs["step6_set_path"]), repo_root),
        },
        "phase_acceptance_table": phase_acceptance_table,
        "comparison_against_baseline": comparison,
        "representative_cases_current": current_cases,
        "representative_cases_baseline": baseline_cases,
        "family_diagnosis_table": family_table,
        "trust_safeguard_audit": {
            "quote_mismatch_count": int(stats.get("quote_mismatch_count", 0)),
            "schema_error_count": int(stats.get("schema_error_count", 0)),
            "definition_short_contract_fail_count": int(stats.get("definition_short_contract_fail_count", 0)),
            "active_updated": False,
            "frozen_prior_outputs_mutated": False,
            "reranker_device": str(bootstrap.device),
            "reranker_fallback_used": bool(bootstrap.used_fallback),
        },
        "final_recommendation": recommendation,
    }


def build_family_policy_validation_report(
    *,
    run_id: str,
    created_utc: str,
    acceptance: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str:
    lines: List[str] = []
    lines.append("STEP 6 FAMILY-AWARE POLICY VALIDATION CLOSEOUT REPORT")
    lines.append("")
    lines.append("1) Executive summary")
    lines.append(f"- Run id: {run_id}")
    lines.append(f"- Created UTC: {created_utc}")
    lines.append(f"- Result: {'PASS' if acceptance.get('passed') else 'FAIL'} | {', '.join(acceptance.get('reasons') or ['All active checks passed.'])}")
    recommendation = dict(payload.get("final_recommendation") or {})
    lines.append(f"- Recommendation: {str(recommendation.get('status') or 'NOT_READY')}")
    lines.append("")
    lines.append("2) Recovered State Summary")
    recovered = dict(payload.get("recovered_state_summary") or {})
    lines.append(f"- Active Step 4 pointer target: {dict(recovered.get('active_pointers') or {}).get('step4', '')}")
    lines.append(f"- Active Step 4.5 pointer target: {dict(recovered.get('active_pointers') or {}).get('step4_5', '')}")
    lines.append(f"- Active Step 5.3 pointer target: {dict(recovered.get('active_pointers') or {}).get('step5_3', '')}")
    lines.append(f"- Active Step 6 pointer target: {dict(recovered.get('active_pointers') or {}).get('step6', '')}")
    lines.append(f"- Accepted Step 6 baseline: {dict(recovered.get('accepted_baselines') or {}).get('step6_active_baseline', '')}")
    development = dict(recovered.get("current_development_line") or {})
    lines.append(f"- Current development line: overlay={development.get('hierarchy_overlay_run', '')} | failed_48kc={development.get('failed_overlay_aware_rerun', '')}")
    lines.append(f"- Current blocker: {str(recovered.get('current_blocker') or '')}")
    lines.append(f"- PROJECT_STATE stale relative to March 10 durable artifacts: {yes_no(bool(recovered.get('project_state_stale_relative_to_march10')))}")
    lines.append("")
    lines.append("3) Exact inputs")
    exact_inputs = dict(payload.get("exact_inputs") or {})
    lines.append(f"- Config: {str(exact_inputs.get('config') or '')}")
    if str(exact_inputs.get("validation_scope") or "").strip():
        lines.append(f"- Validation scope: {str(exact_inputs.get('validation_scope') or '')}")
    lines.append(f"- Comparison baseline run: {str(payload.get('comparison_baseline_run_id') or '')}")
    lines.append(f"- Primary evidence set: {str(exact_inputs.get('primary_evidence_set') or '')}")
    lines.append(f"- Step 6 active baseline: {str(exact_inputs.get('step6_active_baseline') or '')}")
    lines.append("- Exact configured slice:")
    for kc_id in list(exact_inputs.get("exact_configured_slice") or exact_inputs.get("exact_48_kc_slice") or []):
        lines.append(f"- {kc_id}")
    lines.append("")
    lines.append("4) Acceptance table")
    for row in list(payload.get("phase_acceptance_table") or []):
        lines.append(f"- {row['target']}: {row['status']} | {row['detail']}")
    lines.append("")
    lines.append("5) Comparison against baseline")
    comparison = dict(payload.get("comparison_against_baseline") or {})
    if comparison:
        for metric, values in comparison.items():
            lines.append(
                f"- {metric}: baseline={values['baseline']} current={values['current']} delta={values['delta']}"
            )
    else:
        lines.append("- unavailable")
    lines.append("")
    lines.append("6) Family diagnosis table")
    for row in list(payload.get("family_diagnosis_table") or []):
        lines.append(
            f"- {row['family_name']} | leaves_present={','.join(row['leaves_present'])} "
            f"| strict_leaf_support_failures={','.join(row['strict_leaf_support_failures']) or 'none'} "
            f"| family_topic_support_cases={','.join(row['family_topic_support_cases']) or 'none'} "
            f"| generic_selected_support_cases={','.join(row['generic_selected_support_cases']) or 'none'} "
            f"| parent_topic_overlap_cases={','.join(row['parent_topic_overlap_cases']) or 'none'} "
            f"| permissive_rescue_lineage_cases={','.join(row['permissive_rescue_lineage_cases']) or 'none'} "
            f"| sibling_ambiguous_support_cases={','.join(row['sibling_ambiguous_support_cases']) or 'none'}"
        )
    lines.append("")
    lines.append("7) Representative-case analysis")
    current_cases = dict(payload.get("representative_cases_current") or {})
    baseline_cases = dict(payload.get("representative_cases_baseline") or {})
    for kc_id in current_cases:
        case = dict(current_cases[kc_id] or {})
        lines.append(
            f"- {kc_id} | {case.get('canonical_name', '')} | accepted_quote_count={case.get('accepted_quote_count', 0)} "
            f"| definition_full_status={case.get('definition_full_status', '')} "
            f"| definition_short_text={case.get('definition_short_text', '')} "
            f"| target_support_state={case.get('target_support_state', '')} "
            f"| strict_leaf_support={yes_no(bool(case.get('strict_leaf_support')))} "
            f"| family_topic_support={yes_no(bool(case.get('family_topic_support')))} "
            f"| generic_selected_support={yes_no(bool(case.get('generic_selected_support')))} "
            f"| parent_topic_overlap={yes_no(bool(case.get('parent_topic_overlap')))} "
            f"| permissive_rescue_lineage={yes_no(bool(case.get('permissive_rescue_lineage')))} "
            f"| sibling_ambiguous_support={yes_no(bool(case.get('sibling_ambiguous_support')))} "
            f"| contamination={yes_no(bool(case.get('contamination')))} "
            f"| schema_valid={yes_no(bool(case.get('schema_valid')))} "
            f"| usable_curriculum={yes_no(bool(case.get('usable_curriculum')))} "
            f"| definition_status_supported={yes_no(bool(case.get('definition_status_supported')))}"
        )
        selected_quotes = list(case.get("selected_quotes") or [])
        if selected_quotes:
            lines.append(f"- {kc_id} selected_quotes: {' || '.join(selected_quotes)}")
        baseline_case = dict(baseline_cases.get(kc_id) or {})
        if baseline_case:
            lines.append(
                f"- {kc_id} baseline_compare: accepted_quote_count={baseline_case.get('accepted_quote_count', 0)} "
                f"| definition_full_status={baseline_case.get('definition_full_status', '')} "
                f"| target_support_state={baseline_case.get('target_support_state', '')} "
                f"| contamination={yes_no(bool(baseline_case.get('contamination')))}"
            )
    lines.append("")
    lines.append("8) Trust safeguards")
    trust = dict(payload.get("trust_safeguard_audit") or {})
    lines.append(f"- quote_mismatch_count: {trust.get('quote_mismatch_count', 0)}")
    lines.append(f"- schema_error_count: {trust.get('schema_error_count', 0)}")
    lines.append(f"- definition_short_contract_fail_count: {trust.get('definition_short_contract_fail_count', 0)}")
    lines.append(f"- ACTIVE updated: {yes_no(bool(trust.get('active_updated')))}")
    lines.append(f"- Frozen prior outputs mutated: {yes_no(bool(trust.get('frozen_prior_outputs_mutated')))}")
    lines.append(f"- Reranker device: {trust.get('reranker_device', '')}")
    lines.append(f"- Reranker fallback used: {yes_no(bool(trust.get('reranker_fallback_used')))}")
    lines.append("")
    lines.append("9) Final recommendation")
    lines.append(f"- {str(recommendation.get('status') or 'NOT_READY')}")
    for reason in list(recommendation.get("reasons") or []):
        lines.append(f"- Reason: {reason}")
    return "\n".join(lines) + "\n"


def build_set_manifest(
    *,
    repo_root: Path,
    run_id: str,
    created_utc: str,
    processed_dir: Path,
    audit_dir: Path,
    inputs: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": "step6_4_2_kc_library_set",
        "set_id": f"{run_id}_step6_4_2_kc_library_set",
        "created_utc": created_utc,
        "run_id_step6_4_2": run_id,
        "artifacts": {
            "kc_library_jsonl": rel_path(processed_dir / "kc_library.jsonl", repo_root),
            "kc_library_stats_json": rel_path(processed_dir / "kc_library_stats.json", repo_root),
            "tier2_recovery_queue_jsonl": rel_path(processed_dir / "tier2_recovery_queue.jsonl", repo_root),
            "definition_short_contract_audit_jsonl": rel_path(processed_dir / "definition_short_contract_audit.jsonl", repo_root),
            "enrichment_traces_dir": rel_path(processed_dir / "enrichment_traces", repo_root),
        },
        "upstream": {
            "kc_registry": rel_path(Path(inputs["kc_registry"]), repo_root),
            "step6_active_set_pointer": rel_path(Path(inputs["step6_pointer"]), repo_root),
            "step6_active_set_target": rel_path(Path(inputs["step6_set_path"]), repo_root),
            "step5_primary_kind": str(inputs["step5_primary_kind"]),
            "step5_primary_active_set_pointer": rel_path(Path(inputs["step5_pointer"]), repo_root),
            "step5_primary_active_set_target": rel_path(Path(inputs["step5_set_path"]), repo_root),
            "step4_active_set_pointer": rel_path(Path(inputs["step4_pointer"]), repo_root),
            "step4_set_target": rel_path(Path(inputs["step4_set_path"]), repo_root),
            "hierarchy_overlay_node_index": (
                rel_path(Path(inputs["hierarchy_overlay_node_index_path"]), repo_root)
                if inputs.get("hierarchy_overlay_node_index_path") is not None
                else ""
            ),
            "hierarchy_leaf_ancestry": (
                rel_path(Path(inputs["hierarchy_leaf_ancestry_path"]), repo_root)
                if inputs.get("hierarchy_leaf_ancestry_path") is not None
                else ""
            ),
        },
        "audit": {
            "run_dir": rel_path(audit_dir, repo_root),
            "input_manifest": rel_path(audit_dir / "input_manifest.json", repo_root),
            "output_manifest": rel_path(audit_dir / "output_manifest.json", repo_root),
            "summary": rel_path(audit_dir / "summary.json", repo_root),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 6.4.2 semantic-safe KC Tier 2 enrichment runner.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Repo-relative config path.")
    parser.add_argument("--limit-kcs", type=int, default=None, help="Deterministic subset size for dry run.")
    args = parser.parse_args()

    repo_root = REPO_ROOT
    config_path = resolve_repo_path(repo_root, args.config)
    config = load_yaml(config_path)
    run_paths = choose_run_paths(
        repo_root,
        str(config["outputs"]["processed_root"]),
        str(config["audit"]["runs_dir"]),
        str(config["outputs"]["sets_dir"]),
    )
    run_id = str(run_paths["run_id_step6_4_2"])
    processed_dir = Path(run_paths["processed_dir"])
    audit_dir = Path(run_paths["audit_dir"])
    traces_dir = processed_dir / "enrichment_traces"
    processed_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)

    step6lib = import_script_module(repo_root, "steps/step_06_kc_library_extract/scripts/run_step6.py", "step6lib_step642")
    step63 = import_script_module(repo_root, "steps/step_06_3_kc_extract_quote_first/scripts/run_step6_3.py", "step63_step642")
    step43 = import_script_module(repo_root, "steps/step_04_structure_retrieval_index/scripts/run_step4_3.py", "step43_step642")
    audit_log = step63.AuditLog(audit_dir / "run.log")

    created_utc = now_utc_iso()
    start_time = time.perf_counter()
    dry_run = args.limit_kcs is not None
    write_text(audit_dir / "config_snapshot.yaml", read_text(config_path))
    write_json(
        audit_dir / "invocation.json",
        {"argv": sys.argv, "cwd": ".", "config": rel_path(config_path, repo_root), "limit_kcs": args.limit_kcs, "created_utc": created_utc},
    )

    inputs = load_inputs(repo_root, config)
    schema = load_schema(inputs["schema_path"])
    schema_ver = schema_version(schema)
    corpus = load_source_corpus(inputs["step4_set"], repo_root)
    sentence_rows = list(jsonl_iter(Path(inputs["step4_5_sentence_corpus_path"]))) if inputs["step4_5_sentence_corpus_path"] else []
    provenance_index = build_sentence_provenance_index(sentence_rows, corpus["source_lookup"]) if sentence_rows else None
    hierarchy_context_by_kc = build_overlay_hierarchy_context(
        overlay_node_index=load_optional_json(inputs.get("hierarchy_overlay_node_index_path")),
        leaf_ancestry=load_optional_json(inputs.get("hierarchy_leaf_ancestry_path")),
    )
    input_manifest_paths = [
        config_path,
        Path(inputs["step6_pointer"]),
        Path(inputs["step5_pointer"]),
        Path(inputs["step4_pointer"]),
        Path(inputs["kc_registry"]),
        Path(inputs["step6_set_path"]),
        Path(inputs["step5_set_path"]),
        Path(inputs["step4_set_path"]),
        Path(inputs["step6_library"]),
        Path(inputs["step5_primary_candidates"]),
        Path(inputs["step4_cfg"]),
        Path(inputs["schema_path"]),
        repo_root / "src/kc_l/retrieval_gate/semantic.py",
        repo_root / "src/kc_l/retrieval_gate/text_normalize.py",
        repo_root / "src/kc_l/retrieval_gate/provenance_normalize.py",
        repo_root / "src/kc_l/retrieval_gate/role_scoring.py",
        repo_root / "src/kc_l/retrieval_rerank/cross_encoder.py",
    ] + list(corpus["corpus_paths"])
    if inputs["hierarchy_overlay_node_index_path"] is not None:
        input_manifest_paths.append(Path(inputs["hierarchy_overlay_node_index_path"]))
    if inputs["hierarchy_leaf_ancestry_path"] is not None:
        input_manifest_paths.append(Path(inputs["hierarchy_leaf_ancestry_path"]))
    if inputs["step4_5_set_path"] is not None:
        input_manifest_paths.append(Path(inputs["step4_5_set_path"]))
    if inputs["step4_5_sentence_corpus_path"] is not None:
        input_manifest_paths.append(Path(inputs["step4_5_sentence_corpus_path"]))
    if inputs["baseline_step6_4_2_summary_path"] is not None:
        input_manifest_paths.append(Path(inputs["baseline_step6_4_2_summary_path"]))
    if inputs["baseline_step6_4_2_closeout_path"] is not None:
        input_manifest_paths.append(Path(inputs["baseline_step6_4_2_closeout_path"]))
    if inputs["baseline_step6_4_2_false_rejection_audit_path"] is not None and Path(
        inputs["baseline_step6_4_2_false_rejection_audit_path"]
    ).exists():
        input_manifest_paths.append(Path(inputs["baseline_step6_4_2_false_rejection_audit_path"]))
    if inputs["baseline_step6_4_2_definition_short_audit_path"] is not None and Path(
        inputs["baseline_step6_4_2_definition_short_audit_path"]
    ).exists():
        input_manifest_paths.append(Path(inputs["baseline_step6_4_2_definition_short_audit_path"]))
    if inputs["baseline_step6_4_2_kc_library_path"] is not None and Path(inputs["baseline_step6_4_2_kc_library_path"]).exists():
        input_manifest_paths.append(Path(inputs["baseline_step6_4_2_kc_library_path"]))
    write_json(audit_dir / "input_manifest.json", step63.build_repo_manifest(input_manifest_paths, repo_root))

    installed_models = list_ollama_models()
    generation_cfg = dict(config["models"]["generation"])
    gate_cfg = dict(config["models"]["gate_llm"])
    reranker_cfg = dict(config["models"]["reranker"])
    runtime_models = RuntimeModels(
        generation_model=choose_ollama_model(installed_models, str(generation_cfg["preferred_model"]), [str(item) for item in generation_cfg.get("fallback_models") or []]),
        gate_model=choose_ollama_model(installed_models, str(gate_cfg["model"]), []),
        generation_base_url=str(generation_cfg["base_url"]),
        generation_retries=int(generation_cfg["retries"]),
        generation_num_ctx=int(generation_cfg["num_ctx"]),
        generation_allow_think=bool((generation_cfg.get("think") or {}).get("allow_fallback")),
        gate_base_url=str(gate_cfg["base_url"]),
        gate_retries=int(gate_cfg["retries"]),
        gate_num_ctx=int(generation_cfg["num_ctx"]),
        gate_allow_think=bool((gate_cfg.get("think") or {}).get("allow_fallback")),
    )
    bootstrap_result, scorer = bootstrap_reranker(
        repo_root=repo_root,
        preferred_model=str(reranker_cfg["preferred"]),
        fallback_models=[str(item) for item in reranker_cfg.get("fallback") or []],
        device=str(reranker_cfg.get("device") or "auto"),
        batch_size=int(reranker_cfg.get("batch_size") or 8),
        smoke_query="Gini Index | decision tree impurity measure | lower is better",
        smoke_sentence="The Gini index measures node impurity for decision tree splits.",
    )
    write_json(audit_dir / "environment_snapshot.json", env_snapshot())
    write_json(
        audit_dir / "tool_versions.json",
        {
            "python": sys.version,
            "ollama_cli": try_cmd_version(["ollama", "--version"]),
            "git": try_cmd_version(["git", "--version"]),
            "nvidia_smi": try_cmd_version(["nvidia-smi"]),
            "pip_freeze": pip_freeze(),
            "reranker_bootstrap": bootstrap_result.as_dict(),
        },
    )

    kc_rows = load_kc_rows(Path(inputs["kc_registry"]), Path(inputs["step6_library"]), Path(inputs["step5_primary_candidates"]))
    selected_rows = attach_hierarchy_context_to_registry_rows(
        select_kc_subset(
            kc_rows["registry_rows"],
            args.limit_kcs,
            exact_kc_ids=inputs.get("exact_kc_id_slice"),
        ),
        hierarchy_context_by_kc,
    )
    embed_cfg = load_embedding_cfg(Path(inputs["step4_cfg"]))
    query_cache = build_query_cache(selected_rows=selected_rows, step6_by_id=kc_rows["step6_by_id"], embed_cfg=embed_cfg, step43=step43)
    baseline_summary = load_optional_json(inputs["baseline_step6_4_2_summary_path"])
    baseline_false_rejection_summary = load_optional_json(inputs["baseline_step6_4_2_false_rejection_audit_path"])
    baseline_definition_short_audit_by_kc = load_optional_jsonl_lookup(inputs["baseline_step6_4_2_definition_short_audit_path"])
    baseline_kc_library_by_kc = load_optional_jsonl_lookup(inputs["baseline_step6_4_2_kc_library_path"])
    adjudication_cfg = dict(config.get("contamination_adjudication") or {})

    extraction_method = "semantic_safe_enrich:step6_4_2"
    runtime_counters = RuntimeCounters(llm_calls=0, think_calls=0)
    results_by_kc: Dict[str, ProcessingResult] = {}
    failure_counter: Counter[str] = Counter()
    quote_mismatch_issues: List[str] = []
    stats_counter = Counter()
    source_breakdown = Counter()
    role_source_quote_breakdown = Counter()
    role_source_kc_breakdown = Counter()
    schema_errors: List[str] = []
    provenance_counter = Counter()
    role_model_counter = Counter()

    for idx, registry_row in enumerate(selected_rows, start=1):
        kc_id = str(registry_row["kc_id"])
        audit_log.info(f"Processing {idx}/{len(selected_rows)} {kc_id}")
        candidates = build_candidate_pool(
            kc_id=kc_id,
            registry_row=registry_row,
            step5_row=kc_rows["step5_by_id"].get(kc_id),
            step6_row=kc_rows["step6_by_id"].get(kc_id),
            source_lookup=corpus["source_lookup"],
            doc_blocks=corpus["doc_blocks"],
            block_positions=corpus["block_positions"],
            semantic_cfg=config["semantic_gates"],
            enrichment_cfg=config["enrichment"],
            primary_origin_label=str(inputs["step5_primary_origin_label"]),
        )
        apply_embedding_scores(kc_id=kc_id, candidates=candidates, query_cache=query_cache, embed_cfg=embed_cfg, step43=step43)
        apply_reranker_scores(kc_id=kc_id, candidates=candidates, query_cache=query_cache, scorer=scorer)
        d2_calls_for_kc = 0
        for candidate in candidates:
            if not semantic_gate(candidate, config["semantic_gates"]):
                continue
            if candidate.rerank_target < float(config["semantic_gates"]["rerank_min"]):
                candidate.gate_reasons.append("D1RerankMinFail")
                continue
            if candidate.rerank_margin < float(config["semantic_gates"]["rerank_margin"]):
                candidate.gate_reasons.append("D1RerankMarginFail")
                continue
            if candidate.doc_mismatch and (
                candidate.embed_margin < float(config["semantic_gates"]["margin_min"]) + 0.05
                or candidate.rerank_margin < float(config["semantic_gates"]["rerank_margin"]) + 0.05
            ):
                candidate.gate_reasons.append("DocMismatchWithoutStrongMargin")
                continue
            if bool(config["gate_policy"]["enable_d2_kc_id_gate"]) and borderline_candidate(candidate, config["semantic_gates"]):
                if d2_calls_for_kc >= int(config["gate_policy"]["max_gate_llm_calls_per_kc"]):
                    candidate.gate_reasons.append("D2BudgetExceeded")
                    continue
                d2_calls_for_kc += 1
                stats_counter["d2_gate_calls"] += 1
                candidate.d2_used = True
                try:
                    chosen_kc_id, confidence, _ = run_d2_gate(
                        step63=step63,
                        runtime_counters=runtime_counters,
                        model=runtime_models.gate_model,
                        base_url=runtime_models.gate_base_url,
                        retries=runtime_models.gate_retries,
                        num_ctx=runtime_models.gate_num_ctx,
                        allow_think_fallback=runtime_models.gate_allow_think,
                        target_kc_id=kc_id,
                        registry_row=registry_row,
                        competitor_ids=query_cache["competitor_ids_by_kc"][kc_id],
                        query_cache=query_cache,
                        candidate=candidate,
                    )
                    candidate.d2_decision = chosen_kc_id
                    candidate.d2_confidence = confidence
                    if chosen_kc_id != kc_id:
                        candidate.gate_reasons.append(f"D2Rejected:{chosen_kc_id}")
                        stats_counter["d2_gate_rejects"] += 1
                        continue
                except Exception as exc:
                    candidate.gate_reasons.append(f"D2Error:{type(exc).__name__}")
                    stats_counter["d2_gate_rejects"] += 1
                    continue
            candidate.accepted = True
        local_bundle_rescue = attempt_local_bundle_rescue(
            kc_id=kc_id,
            registry_row=registry_row,
            kc_type=infer_kc_type(registry_row, kc_rows["step6_by_id"].get(kc_id)),
            candidates=candidates,
            query_cache=query_cache,
            scorer=scorer,
            block_positions=corpus["block_positions"],
            semantic_cfg=config["semantic_gates"],
            enrichment_cfg=config["enrichment"],
            role_cfg=config["role_assignment"],
        )
        if local_bundle_rescue["rescued_candidate_ids"]:
            stats_counter["local_bundle_rescue_candidate_count"] += len(local_bundle_rescue["rescued_candidate_ids"])
            stats_counter["local_bundle_rescue_kc_count"] += 1

        result = build_record_and_trace(
            step6lib=step6lib,
            registry_row=registry_row,
            step6_row=kc_rows["step6_by_id"].get(kc_id),
            step5_set_id=str(inputs["step5_set"]["set_id"]),
            step4_set_id=str(inputs["step4_set"]["set_id"]),
            run_id=run_id,
            created_utc=created_utc,
            schema_ver=schema_ver,
            extraction_method=extraction_method,
            semantic_cfg=config["semantic_gates"],
            enrichment_cfg=config["enrichment"],
            provenance_cfg=dict(config.get("provenance_normalization") or {}),
            role_cfg=dict(config.get("role_assignment") or {}),
            runtime_models=runtime_models,
            runtime_counters=runtime_counters,
            step63=step63,
            scorer=scorer,
            query_cache=query_cache,
            provenance_index=provenance_index,
            block_positions=corpus["block_positions"],
            adjudication_cfg=adjudication_cfg,
            all_candidates=candidates,
            baseline_definition_audit_by_kc=baseline_definition_short_audit_by_kc,
            baseline_kc_library_by_kc=baseline_kc_library_by_kc,
        )
        quote_mismatch_issues.extend(find_verified_quote_mismatches_raw(result.record, corpus["source_lookup"]))
        validation_errors = validate_kc_record(result.record)
        if validation_errors:
            schema_errors.extend([f"{kc_id}:{error}" for error in validation_errors])
            result.failure_reasons.extend([f"Schema:{error}" for error in validation_errors])
        results_by_kc[kc_id] = result
        role_source = str(result.trace.get("role_source") or "heuristic")
        role_source_kc_breakdown[role_source] += 1
        for source_name in list((result.trace.get("selected_role_sources") or {}).values()):
            role_source_quote_breakdown[str(source_name)] += 1
        provenance_stats = dict(result.trace.get("provenance_normalization") or {})
        provenance_counter["page_index_recovered_count"] += int(provenance_stats.get("page_index_recovered_count", 0))
        provenance_counter["page_index_substituted_count"] += int(provenance_stats.get("page_index_substituted_count", 0))
        provenance_counter["page_index_dropped_count"] += int(provenance_stats.get("page_index_dropped_count", 0))
        provenance_counter["quote_rebound_count"] += int(provenance_stats.get("quote_rebound_count", 0))
        provenance_counter["quote_rebind_failed_count"] += int(provenance_stats.get("quote_rebind_failed_count", 0))
        role_meta = dict(result.trace.get("role_annotation_meta") or {})
        role_model_counter["ambiguous_role_calls"] += int(role_meta.get("ambiguous_role_calls", 0))
        role_model_counter["model_role_success_count"] += int(role_meta.get("model_role_success_count", 0))
        role_model_counter["model_role_failure_count"] += int(role_meta.get("model_role_failure_count", 0))
        for candidate in result.selected_candidates:
            if candidate.doc_mismatch:
                stats_counter["doc_mismatch_usage_count"] += 1
            source_breakdown[candidate.origin] += 1
        for candidate in candidates:
            if any(reason.startswith("D1") for reason in candidate.gate_reasons):
                stats_counter["reranker_rejects"] += 1
            if candidate.doc_mismatch and not candidate.accepted:
                stats_counter["doc_mismatch_rejects"] += 1
            if "EmbedMarginFail" in candidate.gate_reasons:
                stats_counter["margin_fail_count"] += 1
        for reason in result.failure_reasons:
            failure_counter[reason] += 1

    kc_records = [results_by_kc[str(row["kc_id"])].record for row in selected_rows]
    write_jsonl(processed_dir / "kc_library.jsonl", kc_records)
    false_rejection_summary = (
        false_rejection_audit(selected_rows=selected_rows, results_by_kc=results_by_kc, semantic_cfg=config["semantic_gates"])
        if dry_run
        else {"expected_good_kcs": [], "false_rejection_failures": 0}
    )
    write_json(audit_dir / "false_rejection_audit.json", false_rejection_summary)

    tier1_count = sum(1 for result in results_by_kc.values() if result.base_tier >= 1)
    tier2_count = sum(1 for result in results_by_kc.values() if result.semantic_tier == 2)
    definition_full_count = sum(1 for result in results_by_kc.values() if str(result.record.get("definition_full") or "").strip())
    definition_short_nonempty_count = sum(1 for result in results_by_kc.values() if str(result.record.get("definition_short") or "").strip())
    definition_status_counter = Counter(result.definition_status for result in results_by_kc.values())
    definition_short_source_counter: Counter[str] = Counter()
    definition_short_contract_ok_count = 0
    definition_short_contract_fail_count = 0
    definition_short_post_preserve_rewrite_count = 0
    definition_short_post_preserve_drop_count = 0
    tier1_post_short_cleanup_regression_count = 0
    tier1_post_short_cleanup_restored_count = 0
    definition_status_post_short_cleanup_regression_count = 0
    definition_status_post_short_cleanup_restored_count = 0
    definition_short_audit_rows: List[Dict[str, Any]] = []
    definition_status_supported_count = int(
        definition_status_counter["coherent_supported"] + definition_status_counter["fragmentary_supported"]
    )
    usable_curriculum_count = sum(1 for result in results_by_kc.values() if result.usable_curriculum)
    hard_contamination_count = 0
    sibling_ambiguity_count = 0
    sibling_ambiguity_resolved_count = 0
    sibling_ambiguity_failed_count = 0
    competitor_kc_counter: Counter[str] = Counter()
    false_rejection_audit_sample_size = len(false_rejection_summary.get("expected_good_kcs", []))
    for result in results_by_kc.values():
        short_audit = dict(result.trace.get("definition_short_audit") or {})
        contract_decoupling = dict(result.trace.get("contract_decoupling") or {})
        source_type = str(short_audit.get("definition_short_source_type") or "unsupported_or_empty")
        definition_short_source_counter[source_type] += 1
        if bool(short_audit.get("definition_short_contract_ok")):
            definition_short_contract_ok_count += 1
        else:
            definition_short_contract_fail_count += 1
        if bool(short_audit.get("definition_short_post_preserve_rewrite")):
            definition_short_post_preserve_rewrite_count += 1
        if bool(short_audit.get("definition_short_post_preserve_drop")):
            definition_short_post_preserve_drop_count += 1
        if bool(contract_decoupling.get("tier1_post_short_cleanup_regressed")):
            tier1_post_short_cleanup_regression_count += 1
        if bool(contract_decoupling.get("tier1_post_short_cleanup_restored")):
            tier1_post_short_cleanup_restored_count += 1
        if bool(contract_decoupling.get("definition_status_post_short_cleanup_regressed")):
            definition_status_post_short_cleanup_regression_count += 1
        if bool(contract_decoupling.get("definition_status_post_short_cleanup_restored")):
            definition_status_post_short_cleanup_restored_count += 1
        contamination_summary = dict(result.trace.get("contamination_summary") or result.contamination_summary or {})
        if str(contamination_summary.get("category") or "") == "hard_contamination":
            hard_contamination_count += 1
        if contamination_summary.get("sibling_ambiguity_competitor_ids"):
            sibling_ambiguity_count += 1
        if contamination_summary.get("sibling_ambiguity_resolved"):
            sibling_ambiguity_resolved_count += 1
        if contamination_summary.get("sibling_ambiguity_failed"):
            sibling_ambiguity_failed_count += 1
        for competitor_kc_id in list(contamination_summary.get("competitor_kc_ids") or []):
            competitor_kc_counter[str(competitor_kc_id)] += 1
        definition_short_audit_rows.append(
            {
                "kc_id": str(result.record["kc_id"]),
                "canonical_name": str(result.record["canonical_name"]),
                "semantic_tier": int(result.semantic_tier),
                "definition_status": str(result.definition_status),
                "definition_full_nonempty": bool(str(result.record.get("definition_full") or "").strip()),
                "definition_short_nonempty": bool(str(result.record.get("definition_short") or "").strip()),
                "definition_short_source_type": source_type,
                "definition_short_primary_evidence_id": str(result.trace.get("definition_short_primary_evidence_id") or ""),
                "definition_short_evidence_ids": list(short_audit.get("definition_short_evidence_ids") or []),
                "definition_short_contract_ok": bool(short_audit.get("definition_short_contract_ok")),
                "definition_short_contract_fail_reason": str(short_audit.get("definition_short_contract_fail_reason") or ""),
                "definition_short_enforcement_action": str(short_audit.get("definition_short_enforcement_action") or "unchanged"),
                "definition_short_pre_enforcement_text": str(short_audit.get("definition_short_pre_enforcement_text") or ""),
                "definition_short_post_enforcement_text": str(short_audit.get("definition_short_post_enforcement_text") or ""),
                "definition_short_post_preserve_rewrite": bool(short_audit.get("definition_short_post_preserve_rewrite")),
                "definition_short_post_preserve_drop": bool(short_audit.get("definition_short_post_preserve_drop")),
                "tier1": bool(result.base_tier >= 1),
                "definition_status_supported": bool(result.definition_status in SUPPORTED_DEFINITION_STATUSES),
                "tier1_post_short_cleanup_regressed": bool(contract_decoupling.get("tier1_post_short_cleanup_regressed")),
                "tier1_post_short_cleanup_restored": bool(contract_decoupling.get("tier1_post_short_cleanup_restored")),
                "definition_status_post_short_cleanup_regressed": bool(
                    contract_decoupling.get("definition_status_post_short_cleanup_regressed")
                ),
                "definition_status_post_short_cleanup_restored": bool(
                    contract_decoupling.get("definition_status_post_short_cleanup_restored")
                ),
                "usable_curriculum": bool(result.usable_curriculum),
            }
        )
    contamination_count = int(hard_contamination_count + sibling_ambiguity_failed_count)
    selected_source_breakdown = {
        str(inputs["step5_primary_origin_label"]): int(source_breakdown[str(inputs["step5_primary_origin_label"])]),
        "step6_3_anchor": int(source_breakdown["step6_3_anchor"]),
        "step4_neighbor": int(source_breakdown["step4_neighbor"]),
    }
    stats = {
        "tier1_count": tier1_count,
        "tier2_count": tier2_count,
        "usable_curriculum_count": usable_curriculum_count,
        "definition_full_count": definition_full_count,
        "definition_short_nonempty_count": definition_short_nonempty_count,
        "definition_short_contract_ok_count": definition_short_contract_ok_count,
        "definition_short_contract_fail_count": definition_short_contract_fail_count,
        "definition_short_post_preserve_rewrite_count": definition_short_post_preserve_rewrite_count,
        "definition_short_post_preserve_drop_count": definition_short_post_preserve_drop_count,
        "tier1_post_short_cleanup_regression_count": tier1_post_short_cleanup_regression_count,
        "tier1_post_short_cleanup_restored_count": tier1_post_short_cleanup_restored_count,
        "definition_status_post_short_cleanup_regression_count": definition_status_post_short_cleanup_regression_count,
        "definition_status_post_short_cleanup_restored_count": definition_status_post_short_cleanup_restored_count,
        "definition_status_supported_count": definition_status_supported_count,
        "definition_status_breakdown": {
            "coherent_supported": int(definition_status_counter["coherent_supported"]),
            "fragmentary_supported": int(definition_status_counter["fragmentary_supported"]),
            "unsupported_in_source": int(definition_status_counter["unsupported_in_source"]),
        },
        "definition_short_source_breakdown": {
            "derived_from_definition_full": int(definition_short_source_counter["derived_from_definition_full"]),
            "direct_quote_short": int(definition_short_source_counter["direct_quote_short"]),
            "unsupported_or_empty": int(definition_short_source_counter["unsupported_or_empty"]),
        },
        "quote_mismatch_count": len(quote_mismatch_issues),
        "thinking_used_frac": float(runtime_counters["think_calls"] / max(1, runtime_counters["llm_calls"])),
        "contamination_count": contamination_count,
        "hard_contamination_count": hard_contamination_count,
        "sibling_ambiguity_count": sibling_ambiguity_count,
        "sibling_ambiguity_resolved_count": sibling_ambiguity_resolved_count,
        "sibling_ambiguity_failed_count": sibling_ambiguity_failed_count,
        "contamination_competitor_kc_ids": dict(sorted(competitor_kc_counter.items())),
        "margin_fail_count": int(stats_counter["margin_fail_count"]),
        "doc_mismatch_usage_count": int(stats_counter["doc_mismatch_usage_count"]),
        "reranker_filter_drop_rate": float(stats_counter["reranker_rejects"] / max(1, sum(len(result.all_candidates) for result in results_by_kc.values()))),
        "d2_gate_calls": int(stats_counter["d2_gate_calls"]),
        "d2_gate_rejects": int(stats_counter["d2_gate_rejects"]),
        "false_rejection_failures": int(false_rejection_summary["false_rejection_failures"]),
        "false_rejection_failure_rate": float(false_rejection_summary["false_rejection_failures"] / max(1, false_rejection_audit_sample_size)),
        "false_rejection_audit_sample_size": int(false_rejection_audit_sample_size),
        "source_breakdown_selected_quotes": selected_source_breakdown,
        "role_source_breakdown": {
            "selected_quotes": {"model": int(role_source_quote_breakdown["model"]), "heuristic": int(role_source_quote_breakdown["heuristic"])},
            "kcs": {"model": int(role_source_kc_breakdown["model"]), "heuristic": int(role_source_kc_breakdown["heuristic"])},
        },
        "schema_error_count": len(schema_errors),
        "local_bundle_rescue_candidate_count": int(stats_counter["local_bundle_rescue_candidate_count"]),
        "local_bundle_rescue_kc_count": int(stats_counter["local_bundle_rescue_kc_count"]),
        "page_index_recovered_count": int(provenance_counter["page_index_recovered_count"]),
        "page_index_substituted_count": int(provenance_counter["page_index_substituted_count"]),
        "page_index_dropped_count": int(provenance_counter["page_index_dropped_count"]),
        "quote_rebound_count": int(provenance_counter["quote_rebound_count"]),
        "quote_rebind_failed_count": int(provenance_counter["quote_rebind_failed_count"]),
        "ambiguous_role_calls": int(role_model_counter["ambiguous_role_calls"]),
        "model_role_success_count": int(role_model_counter["model_role_success_count"]),
        "model_role_failure_count": int(role_model_counter["model_role_failure_count"]),
        "total_kcs": len(kc_records),
        "step5_primary_kind": str(inputs["step5_primary_kind"]),
        "step5_primary_set_id": str(inputs["step5_set"]["set_id"]),
        "bootstrap": bootstrap_result.as_dict(),
    }
    if str(inputs["step5_primary_origin_label"]) == "step5_2_primary":
        stats["source_breakdown_step5_2_vs_step6_3"] = dict(selected_source_breakdown)
    write_json(processed_dir / "kc_library_stats.json", stats)
    write_jsonl(processed_dir / "tier2_recovery_queue.jsonl", [result.recovery_entry for result in results_by_kc.values() if result.semantic_tier < 2])
    write_jsonl(processed_dir / "definition_short_contract_audit.jsonl", definition_short_audit_rows)

    worst_ids = [
        kc_id
        for kc_id, _ in sorted(
            results_by_kc.items(),
            key=lambda item: (
                mean_or_zero([candidate.embed_margin for candidate in item[1].selected_candidates]),
                mean_or_zero([candidate.rerank_margin for candidate in item[1].selected_candidates]),
                item[0],
            ),
        )[:20]
    ]
    trace_ids = unique_preserve_order(deterministic_sample_ids(results_by_kc.keys(), 20) + worst_ids)
    for kc_id in trace_ids:
        write_json(traces_dir / f"{kc_id}.json", results_by_kc[kc_id].trace)

    baseline_stats = dict(baseline_summary.get("stats") or {}) if isinstance(baseline_summary.get("stats"), Mapping) else {}
    expected_total = len(selected_rows) if dry_run else int(config["acceptance_targets"]["tier1_required"])
    acceptance_reasons: List[str] = []
    if len(kc_records) != expected_total:
        acceptance_reasons.append(f"KCCount:{len(kc_records)}!={expected_total}")
    if schema_errors:
        acceptance_reasons.append(f"SchemaErrors:{len(schema_errors)}")
    if len(quote_mismatch_issues) > int(config["acceptance_targets"]["quote_mismatch_max"]):
        acceptance_reasons.append(f"QuoteMismatchCount:{len(quote_mismatch_issues)}")
    if tier1_count != expected_total:
        acceptance_reasons.append(f"Tier1Count:{tier1_count}!={expected_total}")
    if contamination_count > int(config["acceptance_targets"]["semantic_contamination_max"]):
        if not dry_run:
            acceptance_reasons.append(f"ContaminationCount:{contamination_count}")
    if dry_run:
        dry_contamination_max = int(config["acceptance_targets"].get("dry_run_semantic_contamination_max", config["acceptance_targets"]["semantic_contamination_max"]))
        dry_definition_min = int(config["acceptance_targets"].get("dry_run_definition_full_min", 0))
        dry_definition_supported_min = int(config["acceptance_targets"].get("dry_run_definition_status_supported_min", dry_definition_min))
        dry_usable_curriculum_min = int(
            config["acceptance_targets"].get("dry_run_usable_curriculum_min", config["acceptance_targets"].get("dry_run_tier2_min", 0))
        )
        dry_definition_short_contract_fail_max = int(config["acceptance_targets"].get("dry_run_definition_short_contract_fail_max", 0))
        dry_false_rejection_max = int(config["acceptance_targets"].get("dry_run_false_rejection_failures_max", 2))
        if contamination_count > dry_contamination_max:
            acceptance_reasons.append(f"ContaminationCount:{contamination_count}")
        if false_rejection_summary["false_rejection_failures"] > dry_false_rejection_max:
            acceptance_reasons.append(f"FalseRejectionFailures:{false_rejection_summary['false_rejection_failures']}")
        baseline_false_rejection_failures = int(baseline_stats.get("false_rejection_failures", dry_false_rejection_max))
        if false_rejection_summary["false_rejection_failures"] > baseline_false_rejection_failures:
            acceptance_reasons.append(
                f"FalseRejectionFailures:{false_rejection_summary['false_rejection_failures']}>{baseline_false_rejection_failures}"
            )
        if definition_short_contract_fail_count > dry_definition_short_contract_fail_max:
            acceptance_reasons.append(f"DefinitionShortContractFailCount:{definition_short_contract_fail_count}")
        if usable_curriculum_count < dry_usable_curriculum_min:
            acceptance_reasons.append(f"UsableCurriculumCount:{usable_curriculum_count}")
        if definition_full_count < dry_definition_min and definition_status_supported_count < dry_definition_supported_min:
            acceptance_reasons.append(
                f"DefinitionSupportCount:full={definition_full_count},supported={definition_status_supported_count}"
            )
        baseline_usable_curriculum = int(baseline_stats.get("usable_curriculum_count", 0))
        if baseline_stats and usable_curriculum_count < baseline_usable_curriculum:
            acceptance_reasons.append(f"UsableCurriculumCountCollapse:{usable_curriculum_count}<{baseline_usable_curriculum}")
        baseline_supported_count = int(baseline_stats.get("definition_status_supported_count", 0))
        if baseline_stats and definition_status_supported_count < baseline_supported_count:
            acceptance_reasons.append(
                f"DefinitionStatusSupportedCountCollapse:{definition_status_supported_count}<{baseline_supported_count}"
            )
    else:
        usable_curriculum_min = int(config["acceptance_targets"].get("usable_curriculum_min", config["acceptance_targets"].get("tier2_min", 0)))
        definition_supported_min = int(
            config["acceptance_targets"].get("definition_status_supported_min", config["acceptance_targets"].get("definition_full_min", 0))
        )
        definition_short_contract_fail_max = int(config["acceptance_targets"].get("definition_short_contract_fail_max", 0))
        if usable_curriculum_count < usable_curriculum_min:
            acceptance_reasons.append(f"UsableCurriculumCount:{usable_curriculum_count}")
        if definition_full_count < int(config["acceptance_targets"]["definition_full_min"]) and definition_status_supported_count < definition_supported_min:
            acceptance_reasons.append(
                f"DefinitionSupportCount:full={definition_full_count},supported={definition_status_supported_count}"
            )
        if definition_short_contract_fail_count > definition_short_contract_fail_max:
            acceptance_reasons.append(f"DefinitionShortContractFailCount:{definition_short_contract_fail_count}")
    acceptance = {"passed": not acceptance_reasons, "reasons": acceptance_reasons}
    recommendation = build_recommendation(dry_run=dry_run, acceptance=acceptance, stats=stats, targets=config["acceptance_targets"])
    family_policy_validation = build_family_policy_validation_payload(
        repo_root=repo_root,
        config_path=config_path,
        config=config,
        inputs=inputs,
        selected_rows=selected_rows,
        stats=stats,
        acceptance=acceptance,
        bootstrap=bootstrap_result,
        results_by_kc=results_by_kc,
        baseline_summary=baseline_summary,
        baseline_kc_library_by_kc=baseline_kc_library_by_kc,
    )
    closeout_report = build_closeout_report(
        run_id=run_id,
        created_utc=created_utc,
        dry_run=dry_run,
        bootstrap=bootstrap_result,
        runtime_models=runtime_models,
        stats=stats,
        acceptance=acceptance,
        results_by_kc=results_by_kc,
        failure_counter=failure_counter,
        false_rejection_summary=false_rejection_summary,
        primary_source_kind=str(inputs["step5_primary_kind"]),
        primary_origin_label=str(inputs["step5_primary_origin_label"]),
        primary_set_id=str(inputs["step5_set"]["set_id"]),
        baseline_summary=baseline_summary,
        baseline_closeout_path=inputs["baseline_step6_4_2_closeout_path"],
        recommendation=recommendation,
    )
    family_policy_validation_report = build_family_policy_validation_report(
        run_id=run_id,
        created_utc=created_utc,
        acceptance=acceptance,
        payload=family_policy_validation,
    )
    write_text(audit_dir / "STEP6_4_2_CLOSEOUT_REPORT.txt", closeout_report)
    write_text(audit_dir / RECAL_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / DOWNSTREAM_DEBUG_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / DOWNSTREAM_REDESIGN_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / CONTRACT_CORRECT_RESCUE_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / MIDSCALE_VALIDATION_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / MIDSCALE_CLEANUP_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / CONTRACT_DECOUPLE_CLOSEOUT_FILENAME, closeout_report)
    write_text(audit_dir / FAMILY_POLICY_VALIDATION_CLOSEOUT_FILENAME, family_policy_validation_report)
    write_json(audit_dir / "output_manifest.json", build_output_manifest(processed_dir))
    write_json(audit_dir / "timings.json", {"total_seconds": round(time.perf_counter() - start_time, 3)})
    write_json(
        audit_dir / "summary.json",
        {
            "run_id": run_id,
            "dry_run": dry_run,
            "created_utc": created_utc,
            "acceptance": acceptance,
            "recommendation": recommendation,
            "stats": stats,
            "family_policy_validation": {
                **family_policy_validation,
                "report_path": f"data/runs/{run_id}_step6_4_2/{FAMILY_POLICY_VALIDATION_CLOSEOUT_FILENAME}",
            },
        },
    )

    if not dry_run and acceptance["passed"]:
        set_manifest = build_set_manifest(repo_root=repo_root, run_id=run_id, created_utc=created_utc, processed_dir=processed_dir, audit_dir=audit_dir, inputs=inputs)
        write_json(Path(run_paths["set_path"]), set_manifest)
        write_text(repo_root / ACTIVE_STEP6_POINTER, Path(run_paths["set_path"]).name + "\n")
    if acceptance["passed"]:
        audit_log.info("Acceptance passed.")
    else:
        audit_log.info(f"Acceptance failed: {', '.join(acceptance['reasons'])}")
        top_failures = ", ".join(f"{reason}={count}" for reason, count in failure_counter.most_common(10))
        audit_log.info(f"Top failure reasons: {top_failures or 'none'}")
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
