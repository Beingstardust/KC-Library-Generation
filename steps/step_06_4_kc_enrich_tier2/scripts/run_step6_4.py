from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_SRC = Path(__file__).resolve().parents[3] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_output_manifest, env_snapshot, pip_freeze, try_cmd_version
from kc_l.kc.validators import classify_tier, load_schema, schema_version, validate_kc_record


ACTIVE_STEP6_KC_LIBRARY_SET = Path("data/processed/kc_library/_sets/ACTIVE_STEP6_KC_LIBRARY_SET.txt")
DEFAULT_CONFIG_PATH = "steps/step_06_4_kc_enrich_tier2/resources/step6_4.default.yaml"
SUPPORT_ROLES = {"definition", "equation", "procedure"}
FORMULA_RE = re.compile(r"=\s*|\\sum|\\prod|\\frac|\\math|\\left|\\right|\\in\b|\bp\s*\(", re.IGNORECASE)
NUMBERED_STEP_RE = re.compile(r"(?:(?<=^)|(?<=[\n\r]))\s*(\d+[\.\)])\s*(.+?)(?=(?:\n\s*\d+[\.\)])|\Z)", re.DOTALL)
TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")


@dataclass
class QuoteCandidate:
    quote_id: str
    doc_id: str
    block_id: str
    page_index: int
    layer: str
    bbox: Any
    quote: str
    block_text: str
    original_role: str
    heuristic_role: str
    heuristic_scores: Dict[str, float]
    name_overlap: int


def import_module(repo_root: Path, rel_script_path: str, module_name: str):
    helper_path = (repo_root / rel_script_path).resolve()
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import helper module from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_yaml(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        obj = yaml.safe_load(text)
    else:
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Expected mapping config root at {path}")
    return obj


def choose_run_paths(
    *,
    repo_root: Path,
    utils: Any,
    processed_root_rel: str,
    runs_dir_rel: str,
    sets_dir_rel: str,
) -> Dict[str, Path]:
    base_stamp = utils.utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (repo_root / processed_root_rel / run_id).resolve()
        audit_dir = (repo_root / runs_dir_rel / f"{run_id}_step6_4").resolve()
        set_path = (repo_root / sets_dir_rel / f"{run_id}_step6_4_kc_library_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_4": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def choose_generation_model(installed: Sequence[str], cfg: Mapping[str, Any]) -> str:
    installed_list = [str(item) for item in installed]
    installed_set = set(installed_list)
    preferred_model = str(cfg.get("preferred_model") or "").strip()
    if preferred_model and preferred_model in installed_set:
        return preferred_model
    qwen2_5 = sorted(
        name for name in installed_list if "qwen2.5" in name.lower() and "instruct" in name.lower() and "embedding" not in name.lower()
    )
    if qwen2_5:
        return qwen2_5[-1]
    for name in [str(item) for item in cfg.get("fallback_models") or []]:
        if name in installed_set:
            return name
    raise RuntimeError(f"No acceptable generation model installed. Installed={sorted(installed_set)}")


def build_role_schema(role_labels: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["quote_annotations", "definition_full_quote_ids"],
        "properties": {
            "quote_annotations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["quote_id", "role"],
                    "properties": {
                        "quote_id": {"type": "string", "minLength": 1},
                        "role": {"type": "string", "enum": list(role_labels)},
                    },
                },
            },
            "definition_full_quote_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    }


def validate_role_payload(payload: Mapping[str, Any], *, quote_ids: Sequence[str], role_labels: Sequence[str]) -> List[str]:
    errors: List[str] = []
    if not isinstance(payload.get("definition_full_quote_ids"), list) or any(
        not isinstance(item, str) for item in payload.get("definition_full_quote_ids") or []
    ):
        errors.append("definition_full_quote_ids: expected string array")
    elif any(item not in quote_ids for item in payload.get("definition_full_quote_ids") or []):
        errors.append("definition_full_quote_ids: unknown quote id")

    annotations = payload.get("quote_annotations")
    if not isinstance(annotations, list):
        errors.append("quote_annotations: expected list")
        return errors
    if len(annotations) != len(quote_ids):
        errors.append("quote_annotations: wrong length")
    seen: set[str] = set()
    for idx, item in enumerate(annotations):
        if not isinstance(item, Mapping):
            errors.append(f"quote_annotations[{idx}]: expected object")
            continue
        quote_id = item.get("quote_id")
        role = item.get("role")
        if quote_id not in quote_ids:
            errors.append(f"quote_annotations[{idx}].quote_id: unknown")
        else:
            seen.add(str(quote_id))
        if role not in role_labels:
            errors.append(f"quote_annotations[{idx}].role: invalid")
    if set(quote_ids) != seen:
        errors.append("quote_annotations: missing or duplicate quote ids")
    return errors


def role_label_prompt(
    *,
    record: Mapping[str, Any],
    quotes: Sequence[QuoteCandidate],
    role_schema: Mapping[str, Any],
    cfg: Mapping[str, Any],
) -> Tuple[str, str]:
    schema_text = json.dumps(role_schema, ensure_ascii=False, indent=2)
    system_prompt = (
        "You label verified KC evidence quotes. Use only the provided quotes. "
        "Do not rewrite, summarize, or invent facts. Return JSON only."
    )
    user_payload = {
        "task": "Assign one role to every verified quote and choose up to three quote_ids that should be concatenated verbatim for definition_full.",
        "kc": {
            "kc_id": record["kc_id"],
            "canonical_name": record["canonical_name"],
            "kc_type": record["kc_type"],
            "aliases": record.get("aliases") or [],
            "seed_definition": record.get("seed_definition") or "",
        },
        "rules": [
            "Assign exactly one role to each quote_id.",
            "Only use roles from the allowed enum.",
            "Choose definition_full_quote_ids only from the provided quote_ids.",
            "Choose the smallest grounded subset that best defines the KC.",
            "Do not include unsupported quotes just to increase coverage.",
        ],
        "allowed_roles": list(cfg["role_labels"]),
        "json_schema": schema_text,
        "quotes": [
            {
                "quote_id": item.quote_id,
                "doc_id": item.doc_id,
                "block_id": item.block_id,
                "page_index": item.page_index,
                "layer": item.layer,
                "quote": item.quote,
                "heuristic_role_hint": item.heuristic_role,
            }
            for item in quotes
        ],
    }
    return system_prompt, json.dumps(user_payload, ensure_ascii=False)


def tokenize(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 3]


def is_equation_like(text: str) -> bool:
    return bool(FORMULA_RE.search(text)) or any(symbol in text for symbol in ["≤", "≥", "∑", "∈", "→"])


def preserve_quality_flags(flags: Sequence[Any]) -> List[str]:
    preserved: List[str] = []
    drop_prefixes = ("Attempt", "TypeIncomplete:", "Tier1", "Tier2", "Step6_4", "UsabilityTier:")
    drop_exact = {
        "QuoteRoleLabelingFailed",
        "DefinitionExtractive",
        "DefinitionShortUnsupported",
        "DefinitionFullUnsupported",
        "ModelTypeOverriddenByRules",
        "NoExtractiveQuotesSelected",
        "LessThanTwoVerifiedExtractiveQuotes",
        "NoGroundedDefinition",
    }
    for item in flags:
        value = str(item)
        if value in drop_exact:
            continue
        if any(value.startswith(prefix) for prefix in drop_prefixes):
            continue
        preserved.append(value)
    return preserved


def heuristic_role_for_quote(
    *,
    quote: str,
    record: Mapping[str, Any],
    cfg: Mapping[str, Any],
    step6lib: Any,
) -> Tuple[str, Dict[str, float], int]:
    quote_norm = step6lib.match_normalize(quote)
    quote_tokens = set(tokenize(quote))
    name_tokens = set(tokenize(str(record.get("canonical_name") or "")))
    alias_tokens = {token for alias in (record.get("aliases") or []) for token in tokenize(str(alias))}
    overlap = len(quote_tokens & (name_tokens | alias_tokens))

    scores = {role: 0.0 for role in ["definition", "equation", "procedure", "example", "warning", "other"]}
    scores["definition"] += overlap * 1.5
    if is_equation_like(quote):
        scores["equation"] += 4.0
    if any(cue in quote_norm for cue in cfg["definition_cues"]):
        scores["definition"] += 3.0
    if any(cue in quote_norm for cue in cfg["procedure_cues"]):
        scores["procedure"] += 3.0
    if any(cue in quote_norm for cue in cfg["example_cues"]):
        scores["example"] += 2.0
    if any(cue in quote_norm for cue in cfg["warning_cues"]):
        scores["warning"] += 3.0
    if re.search(r"(^|\s)(\d+[\.\)])\s+", quote_norm):
        scores["procedure"] += 4.0
    if " is " in quote_norm or " are " in quote_norm:
        scores["definition"] += 1.0
    if str(record.get("kc_type")) == "metric" and is_equation_like(quote):
        scores["equation"] += 2.0
    if str(record.get("kc_type")) == "procedure" and scores["procedure"] > 0:
        scores["procedure"] += 1.0
    if str(record.get("kc_type")) == "misconception_cluster" and scores["warning"] > 0:
        scores["warning"] += 1.5
    scores["other"] = 0.25

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_role, best_score = ordered[0]
    if best_score <= 0.5:
        return "other", scores, overlap
    return best_role, scores, overlap


def build_quote_candidates(
    *,
    record: Mapping[str, Any],
    source_lookup: Mapping[str, Mapping[str, Any]],
    cfg: Mapping[str, Any],
    step6lib: Any,
) -> Tuple[List[QuoteCandidate], List[str]]:
    candidates: List[QuoteCandidate] = []
    issues: List[str] = []
    seen: set[Tuple[str, str]] = set()
    for evidence in record.get("evidence_minimal") or []:
        if not isinstance(evidence, Mapping):
            continue
        block_id = str(evidence.get("block_id") or "")
        quote = str(evidence.get("quote") or "")
        if not block_id or not quote:
            issues.append(f"{record['kc_id']}:Step6_4EvidenceMissingBlockOrQuote")
            continue
        key = (block_id, quote)
        if key in seen:
            continue
        seen.add(key)
        source_row = source_lookup.get(block_id)
        if not source_row:
            issues.append(f"{record['kc_id']}:Step6_4MissingSourceBlock:{block_id}")
            continue
        block_text = step6lib.normalize_ws(str(source_row.get("text") or ""))
        if not block_text:
            issues.append(f"{record['kc_id']}:Step6_4EmptySourceBlock:{block_id}")
            continue
        if quote not in block_text:
            issues.append(f"{record['kc_id']}:Step6_4QuoteMismatch:{block_id}")
            continue
        heuristic_role, heuristic_scores, overlap = heuristic_role_for_quote(
            quote=quote,
            record=record,
            cfg=cfg,
            step6lib=step6lib,
        )
        candidates.append(
            QuoteCandidate(
                quote_id=f"Q{len(candidates) + 1}",
                doc_id=str(evidence.get("doc_id") or ""),
                block_id=block_id,
                page_index=int(evidence.get("page_index") or 0),
                layer=str(evidence.get("layer") or ""),
                bbox=evidence.get("bbox"),
                quote=quote,
                block_text=block_text,
                original_role=str(evidence.get("role") or "other"),
                heuristic_role=heuristic_role,
                heuristic_scores=heuristic_scores,
                name_overlap=overlap,
            )
        )
    return candidates, issues


def label_roles_with_model(
    *,
    record: Mapping[str, Any],
    quotes: Sequence[QuoteCandidate],
    chosen_model: str,
    role_schema: Mapping[str, Any],
    role_cfg: Mapping[str, Any],
    step6_3: Any,
) -> Tuple[Optional[Dict[str, str]], List[str], Dict[str, Any], str, Dict[str, Any], bool]:
    if not quotes:
        return {}, [], {}, "", {}, False

    quote_ids = [item.quote_id for item in quotes]
    prompt_system, prompt_user = role_label_prompt(record=record, quotes=quotes, role_schema=role_schema, cfg=role_cfg)
    messages = [{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}]
    errors: List[str] = []
    final_payload: Dict[str, Any] = {}
    raw_response = ""
    raw_outer: Dict[str, Any] = {}

    for attempt in range(int(role_cfg["max_retries"])):
        try:
            payload, outer, raw = step6_3.ollama_chat_json(
                base_url=str(role_cfg["ollama_base_url"]),
                model=chosen_model,
                messages=messages,
                format_schema=role_schema,
                temperature=float(role_cfg["temperature"]),
                top_p=float(role_cfg["top_p"]),
                num_ctx=int(role_cfg["num_ctx"]),
                repeat_penalty=float(role_cfg["repeat_penalty"]),
                think=False,
                timeout_s=float(role_cfg["timeout_seconds"]),
            )
            validation_errors = validate_role_payload(payload, quote_ids=quote_ids, role_labels=role_cfg["role_labels"])
            if validation_errors:
                errors.append(f"Attempt{attempt + 1}:InvalidPayload:{';'.join(validation_errors[:8])}")
                messages.append(
                    {
                        "role": "user",
                        "content": f"The previous JSON failed validation: {validation_errors[:8]}. Return corrected JSON only.",
                    }
                )
                continue
            final_payload = dict(payload)
            raw_outer = outer
            raw_response = raw
            break
        except Exception as exc:
            errors.append(f"Attempt{attempt + 1}:{repr(exc)}")
            messages.append(
                {
                    "role": "user",
                    "content": f"The previous response failed because {repr(exc)}. Return corrected JSON only.",
                }
            )
    else:
        if bool(role_cfg.get("allow_think_fallback", False)):
            try:
                payload, outer, raw = step6_3.ollama_chat_json(
                    base_url=str(role_cfg["ollama_base_url"]),
                    model=chosen_model,
                    messages=messages,
                    format_schema=role_schema,
                    temperature=float(role_cfg["temperature"]),
                    top_p=float(role_cfg["top_p"]),
                    num_ctx=int(role_cfg["num_ctx"]),
                    repeat_penalty=float(role_cfg["repeat_penalty"]),
                    think=True,
                    timeout_s=float(role_cfg["timeout_seconds"]),
                )
                validation_errors = validate_role_payload(payload, quote_ids=quote_ids, role_labels=role_cfg["role_labels"])
                if validation_errors:
                    errors.append(f"ThinkFallback:InvalidPayload:{';'.join(validation_errors[:8])}")
                else:
                    final_payload = dict(payload)
                    raw_outer = outer
                    raw_response = raw
                    annotations = {
                        str(item["quote_id"]): str(item["role"])
                        for item in final_payload.get("quote_annotations") or []
                        if isinstance(item, Mapping)
                    }
                    return (
                        annotations,
                        [str(item) for item in final_payload.get("definition_full_quote_ids") or []],
                        {**final_payload, "errors": errors},
                        raw_response,
                        raw_outer,
                        True,
                    )
            except Exception as exc:
                errors.append(f"ThinkFallback:{repr(exc)}")
        return None, [], {"errors": errors}, raw_response, raw_outer, False

    annotations = {
        str(item["quote_id"]): str(item["role"])
        for item in final_payload.get("quote_annotations") or []
        if isinstance(item, Mapping)
    }
    return (
        annotations,
        [str(item) for item in final_payload.get("definition_full_quote_ids") or []],
        {**final_payload, "errors": errors},
        raw_response,
        raw_outer,
        False,
    )


def reconcile_role_map(*, quotes: Sequence[QuoteCandidate], model_roles: Optional[Mapping[str, str]]) -> Tuple[Dict[str, str], bool]:
    final_roles: Dict[str, str] = {}
    adjusted = False
    for item in quotes:
        heuristic_role = item.heuristic_role
        model_role = str((model_roles or {}).get(item.quote_id, "") or "").strip()
        if model_role and model_role != "other":
            final_roles[item.quote_id] = model_role
            continue
        if heuristic_role in SUPPORT_ROLES:
            final_roles[item.quote_id] = heuristic_role
            adjusted = adjusted or bool(model_role == "other")
            continue
        final_roles[item.quote_id] = model_role or heuristic_role or "other"
    return final_roles, adjusted


def score_definition_quote(item: QuoteCandidate, final_role: str) -> float:
    score = 0.0
    if final_role == "definition":
        score += 6.0
    elif final_role == "equation":
        score += 5.0
    elif final_role == "procedure":
        score += 4.0
    score += item.heuristic_scores.get(final_role, 0.0)
    score += item.name_overlap * 0.5
    if item.original_role in SUPPORT_ROLES:
        score += 1.0
    if len(item.quote) > 220:
        score -= 0.5
    return score


def choose_definition_full_quote_ids(
    *,
    quotes: Sequence[QuoteCandidate],
    final_roles: Mapping[str, str],
    model_selected_ids: Sequence[str],
    max_quotes: int,
) -> List[str]:
    valid_ids = {item.quote_id for item in quotes}
    valid_model_ids = [quote_id for quote_id in model_selected_ids if quote_id in valid_ids]
    if valid_model_ids:
        ordered_model = sorted(
            valid_model_ids,
            key=lambda quote_id: -score_definition_quote(
                next(item for item in quotes if item.quote_id == quote_id),
                final_roles.get(quote_id, "other"),
            ),
        )
        support_selected = [quote_id for quote_id in ordered_model if final_roles.get(quote_id, "other") in SUPPORT_ROLES]
        if support_selected:
            return support_selected[:max_quotes]

    scored = sorted(
        quotes,
        key=lambda item: (-score_definition_quote(item, final_roles.get(item.quote_id, "other")), item.quote_id),
    )
    selected = [item.quote_id for item in scored if final_roles.get(item.quote_id, "other") in SUPPORT_ROLES][:max_quotes]
    if selected:
        return selected
    return [item.quote_id for item in scored[:max_quotes]]


def evidence_from_candidate(item: QuoteCandidate, role: str) -> Dict[str, Any]:
    return {
        "doc_id": item.doc_id,
        "block_id": item.block_id,
        "page_index": item.page_index,
        "layer": item.layer,
        "bbox": item.bbox,
        "role": role,
        "quote": item.quote,
        "extraction_method": "extractive_enrich_tier2:step6_4",
        "quote_verified": True,
        "provenance_quality_flags": [],
    }


def build_evidence_lookup(
    *,
    quotes: Sequence[QuoteCandidate],
    final_roles: Mapping[str, str],
    step6_3: Any,
    step6lib: Any,
    kc_id: str,
    source_lookup: Mapping[str, Mapping[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    evidence_lookup = {
        item.quote_id: evidence_from_candidate(item, final_roles.get(item.quote_id, item.heuristic_role))
        for item in quotes
    }
    verified, issues = step6_3.verify_evidence_items(
        kc_id=kc_id,
        evidence_items=list(evidence_lookup.values()),
        source_lookup=source_lookup,
        step6lib=step6lib,
    )
    verified_lookup = {
        quote_id: evidence
        for quote_id, evidence in evidence_lookup.items()
        if any(
            evidence["block_id"] == item["block_id"] and evidence["quote"] == item["quote"] and evidence["role"] == item["role"]
            for item in verified
        )
    }
    return verified_lookup, issues


def definition_short_support_ids(record: Mapping[str, Any], quote_index: Mapping[Tuple[str, str], str]) -> List[str]:
    out: List[str] = []
    for evidence in (record.get("field_evidence_map") or {}).get("definition_short") or []:
        if not isinstance(evidence, Mapping):
            continue
        key = (str(evidence.get("block_id") or ""), str(evidence.get("quote") or ""))
        quote_id = quote_index.get(key)
        if quote_id and quote_id not in out:
            out.append(quote_id)
    return out


def extract_numbered_steps_from_text(text: str, step6lib: Any) -> List[str]:
    steps: List[str] = []
    for _, step_text in NUMBERED_STEP_RE.findall(text):
        normalized = step6lib.normalize_ws(step_text)
        if normalized:
            steps.append(normalized)
    return step6lib.unique_preserve_order(steps)


def extract_inputs_outputs(quotes: Sequence[QuoteCandidate], step6lib: Any) -> str:
    for item in quotes:
        for part in re.split(r"(?<=[\.\?!;:])\s+|\n+", item.block_text):
            normalized = step6lib.normalize_ws(part)
            lower = normalized.lower()
            if normalized and ("input" in lower or "output" in lower):
                return normalized
    return ""


def extract_discriminator_quotes(
    *,
    quotes: Sequence[QuoteCandidate],
    cfg: Mapping[str, Any],
    step6lib: Any,
) -> List[Tuple[str, str]]:
    hits: List[Tuple[str, str]] = []
    for item in quotes:
        for part in re.split(r"(?<=[\.\?!;:])\s+|\n+", item.block_text):
            normalized = step6lib.normalize_ws(part)
            lower = normalized.lower()
            if normalized and any(cue in lower for cue in cfg["discriminator_cues"]):
                hits.append((item.quote_id, normalized))
    unique: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for quote_id, text in hits:
        if text in seen:
            continue
        seen.add(text)
        unique.append((quote_id, text))
    return unique


def apply_step6_4_status(record: Dict[str, Any], *, step6lib: Any) -> int:
    tier_info = classify_tier(record)
    if int(tier_info["tier"]) >= 1:
        record["recovery_state"] = "none"
        record["recovery_reasons"] = []
        usability_tier = 1
    else:
        record["recovery_reasons"] = step6lib.unique_preserve_order([str(reason) for reason in tier_info["reasons"]])
        record["recovery_state"] = "manual_required" if not record.get("evidence_minimal") else "needs_recovery"
        usability_tier = 0
        record["quality_flags"].extend(record["recovery_reasons"])
    record["quality_flags"].extend([str(flag) for flag in tier_info["flags"]])
    record["quality_flags"].append(f"UsabilityTier:{usability_tier}")
    record["quality_flags"] = step6lib.unique_preserve_order(record["quality_flags"])
    return usability_tier


def classify_step6_4_tier(record: Mapping[str, Any]) -> Dict[str, Any]:
    base_tier = classify_tier(record)
    if int(base_tier["tier"]) < 1:
        return {"tier": 0, "reasons": [str(reason) for reason in base_tier["reasons"]]}
    reasons: List[str] = []
    if not str(record.get("definition_full") or "").strip():
        reasons.append("Step6_4MissingDefinitionFull")
    verified_items = [
        item
        for item in record.get("evidence_minimal") or []
        if isinstance(item, Mapping) and item.get("quote_verified") is True
    ]
    if not any(str(item.get("role")) in SUPPORT_ROLES for item in verified_items):
        reasons.append("Step6_4MissingSupportRole")
    return {"tier": 1 if reasons else 2, "reasons": reasons}


def build_set_manifest(
    *,
    repo_root: Path,
    utils: Any,
    set_path: Path,
    run_id_step6_4: str,
    processed_dir: Path,
    audit_dir: Path,
    created_utc: str,
    active_step6_pointer_path: Path,
    base_step6_set_path: Path,
    base_step6_manifest: Mapping[str, Any],
    step4_set_path: Path,
) -> Dict[str, Any]:
    previous_outputs = []
    for name, rel in (base_step6_manifest.get("artifacts") or {}).items():
        path = (repo_root / str(rel)).resolve()
        previous_outputs.append({"name": name, **utils.describe_file(path, repo_root)})

    return {
        "schema_version": "1.0",
        "kind": "step6_4_kc_library_set",
        "set_id": set_path.stem,
        "created_utc": created_utc,
        "run_id_step6_4": run_id_step6_4,
        "artifacts": {
            "kc_library_jsonl": utils.rel_path((processed_dir / "kc_library.jsonl").resolve(), repo_root),
            "kc_library_stats_json": utils.rel_path((processed_dir / "kc_library_stats.json").resolve(), repo_root),
            "recovery_queue_jsonl": utils.rel_path((processed_dir / "recovery_queue.jsonl").resolve(), repo_root),
            "enrichment_traces_dir": utils.rel_path((processed_dir / "enrichment_traces").resolve(), repo_root),
        },
        "upstream": {
            "active_step6_pointer": utils.describe_file(active_step6_pointer_path, repo_root),
            "base_step6_set_target": utils.describe_file(base_step6_set_path, repo_root),
            "step4_set_target": utils.describe_file(step4_set_path, repo_root),
            "base_step6_processed_outputs": previous_outputs,
        },
        "audit": {
            "run_dir": utils.rel_path(audit_dir.resolve(), repo_root),
            "input_manifest": utils.rel_path((audit_dir / "input_manifest.json").resolve(), repo_root),
            "output_manifest": utils.rel_path((audit_dir / "output_manifest.json").resolve(), repo_root),
            "summary": utils.rel_path((audit_dir / "summary.json").resolve(), repo_root),
        },
    }


def run() -> int:
    parser = argparse.ArgumentParser(description="STEP 6.4: extractive-first Tier 2 enrichment on top of the accepted Step 6.3 KC set.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Repo-relative YAML config path.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--limit-kcs", type=int, default=0, help="Optional deterministic subset size for dry runs.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    cfg = load_yaml(config_path)
    step6lib = import_module(repo_root, "steps/step_06_kc_library_extract/scripts/run_step6.py", "step6_4_step6_shared")
    step6_3 = import_module(repo_root, "steps/step_06_3_kc_extract_quote_first/scripts/run_step6_3.py", "step6_4_step6_3_shared")

    inputs_cfg = cfg["inputs"]
    model_cfg = cfg["model_selection"]
    role_cfg = cfg["role_labeling"]
    enrich_cfg = cfg["enrichment"]
    outputs_cfg = cfg["outputs"]
    audit_cfg = cfg["audit"]
    acceptance_cfg = cfg["acceptance"]

    schema_path = (repo_root / str(inputs_cfg["schema_path"])).resolve()
    active_step6_pointer_path = (repo_root / str(inputs_cfg["active_step6_set_pointer"])).resolve()
    active_pointer_path = (repo_root / ACTIVE_STEP6_KC_LIBRARY_SET).resolve()
    if active_step6_pointer_path.resolve() != active_pointer_path.resolve():
        raise RuntimeError("Config active_step6_set_pointer must match ACTIVE_STEP6_KC_LIBRARY_SET.txt")

    base_step6_set_path = step6lib.resolve_pointer(repo_root, active_step6_pointer_path)
    base_step6_manifest = step6_3.load_json(base_step6_set_path)
    if str(base_step6_manifest.get("kind") or "") != "step6_3_kc_library_set":
        raise RuntimeError(f"Active Step 6 set is not the accepted Step 6.3 set: {base_step6_manifest.get('kind')}")

    base_kc_library_path = (repo_root / str(base_step6_manifest["artifacts"]["kc_library_jsonl"])).resolve()
    step4_set_path = (repo_root / str(base_step6_manifest["upstream"]["step4_set_target"]["path"])).resolve()
    step4_manifest = step6_3.load_json(step4_set_path)

    run_paths = choose_run_paths(
        repo_root=repo_root,
        utils=step6_3,
        processed_root_rel=str(outputs_cfg["processed_root"]),
        runs_dir_rel=str(audit_cfg["runs_dir"]),
        sets_dir_rel=str(outputs_cfg["sets_dir"]),
    )
    run_id_step6_4 = run_paths["run_id_step6_4"].name
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    created_utc = step6_3.now_utc_iso()
    is_subset_run = int(args.limit_kcs or 0) > 0

    audit_dir.mkdir(parents=True, exist_ok=False)
    processed_dir.mkdir(parents=True, exist_ok=False)
    trace_dir = processed_dir / "enrichment_traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    logger = step6_3.AuditLog(audit_dir / "logs" / "run.log")

    started = time.perf_counter()
    timings: Dict[str, Any] = {"started_utc": created_utc}
    step6_3.write_text(audit_dir / "config.snapshot.yaml", config_path.read_text(encoding="utf-8"))
    step6_3.write_json(
        audit_dir / "invocation.json",
        {
            "argv": sys.argv,
            "cwd": ".",
            "config": step6_3.rel_path(config_path, repo_root),
            "run_id_step6_4": run_id_step6_4,
            "limit_kcs": int(args.limit_kcs or 0),
        },
    )
    step6_3.write_json(audit_dir / "env_snapshot.json", {"snapshot": env_snapshot(), "pip_freeze": pip_freeze()})

    installed_before = step6_3.list_ollama_models()
    pull_result: Optional[Dict[str, Any]] = None
    preferred_model = str(model_cfg.get("preferred_model") or "")
    if bool(model_cfg.get("auto_pull_preferred_model", False)) and preferred_model and preferred_model not in set(installed_before):
        pull_result = step6_3.pull_model(preferred_model, logger)
    installed_after = step6_3.list_ollama_models()
    chosen_model = choose_generation_model(installed_after, model_cfg)
    logger.info(f"Step 6.4 starting with generation model {chosen_model}")

    step6_3.write_json(
        audit_dir / "tool_versions.json",
        {
            "python": sys.version,
            "pyyaml_available": yaml is not None,
            "ollama_cli": try_cmd_version(["ollama", "--version"]),
            "ollama_http_version": step6_3.ollama_http_version(str(role_cfg["ollama_base_url"])),
            "generation_model": chosen_model,
            "installed_models_before_prepare": installed_before,
            "installed_models_after_prepare": installed_after,
            "model_pull_result": pull_result,
        },
    )

    load_started = time.perf_counter()
    schema = load_schema(schema_path)
    schema_ver = schema_version(schema)
    base_records = list(step6_3.jsonl_iter(base_kc_library_path))
    source_lookup: Dict[str, Dict[str, Any]] = {}
    input_paths = [schema_path, active_step6_pointer_path, base_step6_set_path, base_kc_library_path, step4_set_path]
    for doc_payload in (step4_manifest.get("docs") or {}).values():
        corpus_rel = ((doc_payload.get("artifacts") or {}).get("block_text_corpus.jsonl") or {}).get("path")
        if not corpus_rel:
            continue
        corpus_path = (repo_root / str(corpus_rel)).resolve()
        input_paths.append(corpus_path)
        for row in step6_3.jsonl_iter(corpus_path):
            source_lookup[str(row["block_id"])] = row
    step6_3.write_json(audit_dir / "input_manifest.json", step6_3.build_repo_manifest(input_paths, repo_root))
    timings["load_seconds"] = round(time.perf_counter() - load_started, 3)

    sorted_records = sorted(base_records, key=lambda item: str(item["kc_id"]))
    records_to_process = sorted_records[: int(args.limit_kcs)] if is_subset_run else base_records
    sample_ids = {str(item["kc_id"]) for item in sorted_records[: int(enrich_cfg["sample_trace_kcs"])]}
    role_schema = build_role_schema(role_cfg["role_labels"])

    records: List[Dict[str, Any]] = []
    recovery_rows: List[Dict[str, Any]] = []
    step6_4_reason_counter: Counter[str] = Counter()
    extraction_started = time.perf_counter()
    thinking_used_count = 0

    for index, source_record in enumerate(records_to_process, start=1):
        kc_id = str(source_record["kc_id"])
        base_row = {
            "kc_id": source_record["kc_id"],
            "kc_path": list(source_record.get("kc_path") or []),
            "canonical_name": source_record["canonical_name"],
            "aliases": list(source_record.get("aliases") or []),
            "seed_definition": source_record.get("seed_definition") or "",
        }
        record = step6lib.default_record_shell(
            kc_row=base_row,
            step4_set_id=str((source_record.get("source_set_ids") or {}).get("step4_set_id") or ""),
            step5_set_id=str((source_record.get("source_set_ids") or {}).get("step5_set_id") or ""),
            run_id_step6=run_id_step6_4,
            created_utc=created_utc,
            schema_ver=schema_ver,
        )
        record["kc_type"] = str(source_record.get("kc_type") or "concept")
        record["definition_short"] = str(source_record.get("definition_short") or "")
        record["scope_includes"] = list(source_record.get("scope_includes") or [])
        record["scope_excludes"] = list(source_record.get("scope_excludes") or [])
        for key in [
            "inputs_outputs",
            "procedure_steps",
            "parameters",
            "termination_condition",
            "formal_definition",
            "interpretation",
            "when_to_use",
            "when_not_to_use",
            "claim_statement",
            "assumptions",
            "misconception_statement",
            "canonical_correction",
            "diagnostic_cues",
            "remediation_suggestions",
            "worked_examples",
            "references",
        ]:
            if key in source_record:
                value = source_record.get(key)
                record[key] = [json.loads(json.dumps(item)) for item in value] if isinstance(value, list) else value
        record["quality_flags"] = preserve_quality_flags(source_record.get("quality_flags") or [])

        quote_candidates, verification_issues = build_quote_candidates(
            record=source_record,
            source_lookup=source_lookup,
            cfg=enrich_cfg,
            step6lib=step6lib,
        )
        if verification_issues:
            record["quality_flags"].extend(verification_issues)
            record["quality_flags"].append("Step6_4Tier2Ineligible")

        model_roles, model_definition_full_ids, model_payload, raw_response, raw_outer, think_used = label_roles_with_model(
            record=record,
            quotes=quote_candidates,
            chosen_model=chosen_model,
            role_schema=role_schema,
            role_cfg=role_cfg,
            step6_3=step6_3,
        )
        thinking_used_count += int(think_used)
        record["quality_flags"].extend([str(item) for item in model_payload.get("errors") or []] if isinstance(model_payload, Mapping) else [])
        if model_roles is None:
            record["quality_flags"].append("QuoteRoleLabelingFailed")

        final_roles, model_adjusted = reconcile_role_map(quotes=quote_candidates, model_roles=model_roles)
        if model_adjusted:
            record["quality_flags"].append("Step6_4HeuristicRoleOverride")

        verified_lookup, post_verify_issues = build_evidence_lookup(
            quotes=quote_candidates,
            final_roles=final_roles,
            step6_3=step6_3,
            step6lib=step6lib,
            kc_id=kc_id,
            source_lookup=source_lookup,
        )
        record["quality_flags"].extend(post_verify_issues)
        quote_index = {(item.block_id, item.quote): item.quote_id for item in quote_candidates if item.quote_id in verified_lookup}
        record["evidence_minimal"] = step6lib.dedupe_evidence(list(verified_lookup.values()))[: int(enrich_cfg["max_evidence_minimal"])]

        if len({(item["block_id"], item["quote"]) for item in record["evidence_minimal"]}) < 2:
            record["quality_flags"].append("LessThanTwoVerifiedExtractiveQuotes")

        short_ids = definition_short_support_ids(source_record, quote_index)
        if not short_ids and quote_candidates:
            short_ids = [quote_candidates[0].quote_id]
        if record["definition_short"] and short_ids:
            record["field_evidence_map"]["definition_short"] = [verified_lookup[quote_id] for quote_id in short_ids if quote_id in verified_lookup]

        definition_full_ids = []
        if not verification_issues and quote_candidates:
            definition_full_ids = choose_definition_full_quote_ids(
                quotes=quote_candidates,
                final_roles=final_roles,
                model_selected_ids=model_definition_full_ids,
                max_quotes=int(enrich_cfg["definition_full_max_quotes"]),
            )
        if definition_full_ids:
            record["definition_full"] = "\n".join(
                next(item.quote for item in quote_candidates if item.quote_id == quote_id)
                for quote_id in definition_full_ids
                if quote_id in verified_lookup
            )
            record["field_evidence_map"]["definition_full"] = [verified_lookup[quote_id] for quote_id in definition_full_ids if quote_id in verified_lookup]
        else:
            record["quality_flags"].append("Step6_4MissingDefinitionFull")

        if not any(str(item.get("role")) in SUPPORT_ROLES for item in record["evidence_minimal"]):
            record["quality_flags"].append("Step6_4MissingSupportRole")

        if record["kc_type"] == "metric":
            equation_quotes = [
                item for item in quote_candidates if final_roles.get(item.quote_id, "other") == "equation" and item.quote_id in verified_lookup
            ]
            if not equation_quotes:
                equation_quotes = [item for item in quote_candidates if is_equation_like(item.quote) and item.quote_id in verified_lookup]
            if equation_quotes:
                best_equation = sorted(equation_quotes, key=lambda item: (-score_definition_quote(item, final_roles.get(item.quote_id, "other")), item.quote_id))[0]
                record["formal_definition"] = best_equation.quote
                record["field_evidence_map"]["formal_definition"] = [verified_lookup[best_equation.quote_id]]

        if record["kc_type"] == "procedure":
            numbered_steps: List[str] = []
            supporting_ids: List[str] = []
            for item in quote_candidates:
                extracted = extract_numbered_steps_from_text(item.block_text, step6lib)
                if extracted:
                    numbered_steps.extend(extracted)
                    if item.quote_id in verified_lookup:
                        supporting_ids.append(item.quote_id)
            record["procedure_steps"] = step6lib.unique_preserve_order(numbered_steps)
            if supporting_ids:
                record["field_evidence_map"]["procedure_steps"] = [
                    verified_lookup[quote_id] for quote_id in step6lib.unique_preserve_order(supporting_ids) if quote_id in verified_lookup
                ]
            inputs_outputs = extract_inputs_outputs(quote_candidates, step6lib)
            if inputs_outputs:
                record["inputs_outputs"] = inputs_outputs

        if record["kc_type"] == "theorem_or_claim":
            claim_candidates = [
                item for item in quote_candidates if final_roles.get(item.quote_id, "other") == "definition" and item.quote_id in verified_lookup
            ]
            if claim_candidates:
                best_claim = sorted(claim_candidates, key=lambda item: (-score_definition_quote(item, "definition"), item.quote_id))[0]
                record["claim_statement"] = best_claim.quote
                record["field_evidence_map"]["claim_statement"] = [verified_lookup[best_claim.quote_id]]

        if record["kc_type"] == "misconception_cluster":
            warning_candidates = [
                item for item in quote_candidates if final_roles.get(item.quote_id, "other") == "warning" and item.quote_id in verified_lookup
            ]
            if not warning_candidates:
                warning_candidates = [
                    item
                    for item in quote_candidates
                    if any(cue in step6lib.match_normalize(item.quote) for cue in enrich_cfg["warning_cues"]) and item.quote_id in verified_lookup
                ]
            if warning_candidates:
                best_warning = sorted(warning_candidates, key=lambda item: (-item.heuristic_scores.get("warning", 0.0), item.quote_id))[0]
                record["misconception_statement"] = best_warning.quote
                record["field_evidence_map"]["misconception_statement"] = [verified_lookup[best_warning.quote_id]]

        discriminators = extract_discriminator_quotes(quotes=quote_candidates, cfg=enrich_cfg, step6lib=step6lib)
        if discriminators:
            record["quality_flags"].append(f"Step6_4DiscriminatorCount:{len(discriminators)}")

        usability_tier = apply_step6_4_status(record, step6lib=step6lib)
        step6_4_tier = classify_step6_4_tier(record)
        record["quality_flags"].extend(step6_4_tier["reasons"])
        record["quality_flags"].append(f"Step6_4Tier:{step6_4_tier['tier']}")
        record["quality_flags"] = step6lib.unique_preserve_order(record["quality_flags"])

        validation_errors = validate_kc_record(record)
        if validation_errors:
            raise RuntimeError(f"Schema validation failed for {kc_id}: {validation_errors[:10]}")

        records.append(record)
        if usability_tier < 1:
            recovery_rows.append(
                {
                    "kc_id": kc_id,
                    "tier": int(usability_tier),
                    "tier1_fail_reasons": list(record["recovery_reasons"]),
                    "step6_4_tier_reasons": list(step6_4_tier["reasons"]),
                }
            )
        for reason in step6_4_tier["reasons"]:
            step6_4_reason_counter[str(reason)] += 1

        if kc_id in sample_ids:
            step6_3.write_json(
                trace_dir / f"trace_{kc_id}.json",
                {
                    "kc_id": kc_id,
                    "quote_candidates": [
                        {
                            "quote_id": item.quote_id,
                            "doc_id": item.doc_id,
                            "block_id": item.block_id,
                            "page_index": item.page_index,
                            "layer": item.layer,
                            "quote": item.quote,
                            "original_role": item.original_role,
                            "heuristic_role": item.heuristic_role,
                            "heuristic_scores": item.heuristic_scores,
                            "final_role": final_roles.get(item.quote_id, item.heuristic_role),
                            "name_overlap": item.name_overlap,
                        }
                        for item in quote_candidates
                    ],
                    "model_payload": model_payload,
                    "model_response_raw": raw_response,
                    "model_outer_response": raw_outer,
                    "definition_full_quote_ids": definition_full_ids,
                    "verification_issues": verification_issues + post_verify_issues,
                    "validation": {
                        "usability_tier": usability_tier,
                        "step6_4_tier": step6_4_tier["tier"],
                        "step6_4_reasons": step6_4_tier["reasons"],
                        "quality_flags": record["quality_flags"],
                        "record_errors": validation_errors,
                    },
                    "final_record_snippet": {
                        "kc_type": record["kc_type"],
                        "definition_short": record["definition_short"],
                        "definition_full": record["definition_full"],
                        "formal_definition": record["formal_definition"],
                        "procedure_steps": record["procedure_steps"],
                        "misconception_statement": record["misconception_statement"],
                        "field_evidence_map": record["field_evidence_map"],
                    },
                },
            )

        if index % int(enrich_cfg["progress_every"]) == 0:
            logger.info(f"Processed {index}/{len(records_to_process)} KCs")

    timings["extraction_seconds"] = round(time.perf_counter() - extraction_started, 3)
    verified_quote_issues: List[str] = []
    for record in records:
        verified_quote_issues.extend(step6lib.find_verified_quote_mismatches(record, source_lookup))

    tier1_records = [record for record in records if apply_step6_4_status(json.loads(json.dumps(record)), step6lib=step6lib) >= 1]
    step6_4_tiers = {str(record["kc_id"]): classify_step6_4_tier(record) for record in records}
    tier2_records = [record for record in records if int(step6_4_tiers[str(record["kc_id"])]["tier"]) >= 2]
    role_success_count = sum(
        1
        for record in records
        if any(
            isinstance(item, Mapping) and item.get("quote_verified") is True and str(item.get("role")) in SUPPORT_ROLES
            for item in record.get("evidence_minimal") or []
        )
    )
    definition_full_count = sum(1 for record in records if str(record.get("definition_full") or "").strip())
    thinking_used_frac = round(float(thinking_used_count) / float(len(records) or 1), 4)

    kc_library_path = processed_dir / "kc_library.jsonl"
    stats_path = processed_dir / "kc_library_stats.json"
    recovery_path = processed_dir / "recovery_queue.jsonl"
    step6_3.write_jsonl(kc_library_path, records)
    step6_3.write_jsonl(recovery_path, recovery_rows)

    coverage_percent = {
        "definition_short": round(100.0 * sum(1 for item in records if str(item["definition_short"]).strip()) / float(len(records) or 1), 2),
        "definition_full": round(100.0 * definition_full_count / float(len(records) or 1), 2),
        "evidence_minimal": round(100.0 * sum(1 for item in records if len(item["evidence_minimal"]) > 0) / float(len(records) or 1), 2),
    }

    acceptance_failures: List[str] = []
    if not is_subset_run:
        if len(records) != int(acceptance_cfg["n_kcs_total"]):
            acceptance_failures.append(f"Expected n_kcs_total={int(acceptance_cfg['n_kcs_total'])}, observed {len(records)}")
        if len(tier1_records) != int(acceptance_cfg["required_tier1_count"]):
            acceptance_failures.append(f"Tier1 count {len(tier1_records)} != {int(acceptance_cfg['required_tier1_count'])}")
        if len(verified_quote_issues) > int(acceptance_cfg["max_verified_quote_mismatches"]):
            acceptance_failures.append(
                f"Verified quote mismatch count {len(verified_quote_issues)} > {int(acceptance_cfg['max_verified_quote_mismatches'])}"
            )
        if thinking_used_frac > float(acceptance_cfg["max_thinking_used_frac"]):
            acceptance_failures.append(
                f"thinking_used_frac {thinking_used_frac:.4f} > {float(acceptance_cfg['max_thinking_used_frac']):.4f}"
            )
        if len(tier2_records) < int(acceptance_cfg["min_tier2_count"]):
            acceptance_failures.append(f"Step6_4 Tier2 count {len(tier2_records)} < {int(acceptance_cfg['min_tier2_count'])}")
        if definition_full_count < int(acceptance_cfg["min_definition_full_count"]):
            acceptance_failures.append(f"definition_full count {definition_full_count} < {int(acceptance_cfg['min_definition_full_count'])}")
        if role_success_count < int(acceptance_cfg["min_role_success_count"]):
            acceptance_failures.append(f"role_success_count {role_success_count} < {int(acceptance_cfg['min_role_success_count'])}")

    step6_3.write_json(
        stats_path,
        {
            "run_id_step6_4": run_id_step6_4,
            "n_kcs_total": len(records),
            "n_kcs_tier1": len(tier1_records),
            "n_kcs_tier2": len(tier2_records),
            "n_kcs_usable": len(tier1_records),
            "n_kcs_in_recovery_queue": len(recovery_rows),
            "verified_quote_mismatch_count": len(verified_quote_issues),
            "definition_full_count": definition_full_count,
            "role_success_count": role_success_count,
            "thinking_used_count": thinking_used_count,
            "thinking_used_frac": thinking_used_frac,
            "coverage_percent": coverage_percent,
            "failure_reason_distribution_top10": dict(step6_4_reason_counter.most_common(10)),
            "stats_meta": {
                "tier_contract": "Step 6.4 Tier 2 enrichment",
                "tier2_definition": "Tier1 + definition_full non-empty + at least one verified definition/equation/procedure role",
                "subset_run": is_subset_run,
                "limit_kcs": int(args.limit_kcs or 0),
            },
            "acceptance": {
                "targets": dict(acceptance_cfg),
                "passed": False if is_subset_run else not acceptance_failures,
                "failures": [] if is_subset_run else acceptance_failures,
            },
        },
    )
    step6_3.write_json(
        audit_dir / "summary.json",
        {
            "run_id_step6_4": run_id_step6_4,
            "status": "partial_success" if is_subset_run else "success" if not acceptance_failures else "acceptance_failed",
            "created_utc": created_utc,
            "n_kcs_total": len(records),
            "n_kcs_tier1": len(tier1_records),
            "n_kcs_tier2": len(tier2_records),
            "n_kcs_usable": len(tier1_records),
            "n_kcs_in_recovery_queue": len(recovery_rows),
            "verified_quote_mismatch_count": len(verified_quote_issues),
            "definition_full_count": definition_full_count,
            "role_success_count": role_success_count,
            "thinking_used_count": thinking_used_count,
            "thinking_used_frac": thinking_used_frac,
            "acceptance_passed": False if is_subset_run else not acceptance_failures,
            "acceptance_failures": [] if is_subset_run else acceptance_failures,
            "generation_model": chosen_model,
            "subset_run": is_subset_run,
            "limit_kcs": int(args.limit_kcs or 0),
        },
    )

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "set_manifest": {"path": step6_3.rel_path(set_path, repo_root), "exists": False},
        "active_pointer": step6_3.describe_file(active_pointer_path, repo_root)
        if active_pointer_path.exists()
        else {"path": step6_3.rel_path(active_pointer_path, repo_root), "exists": False},
    }

    if not is_subset_run and not acceptance_failures:
        step6_3.write_json(
            set_path,
            build_set_manifest(
                repo_root=repo_root,
                utils=step6_3,
                set_path=set_path,
                run_id_step6_4=run_id_step6_4,
                processed_dir=processed_dir,
                audit_dir=audit_dir,
                created_utc=created_utc,
                active_step6_pointer_path=active_step6_pointer_path,
                base_step6_set_path=base_step6_set_path,
                base_step6_manifest=base_step6_manifest,
                step4_set_path=step4_set_path,
            ),
        )
        step6_3.write_text(active_pointer_path, set_path.name + "\n")
        output_manifest["set_manifest"] = step6_3.describe_file(set_path, repo_root)
        output_manifest["active_pointer"] = step6_3.describe_file(active_pointer_path, repo_root)
        logger.info(f"Wrote Step 6.4 set manifest: {step6_3.rel_path(set_path, repo_root)}")
        logger.info(f"Updated ACTIVE pointer: {step6_3.rel_path(active_pointer_path, repo_root)} -> {set_path.name}")

    timings["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    step6_3.write_json(audit_dir / "timings.json", timings)
    step6_3.write_json(audit_dir / "output_manifest.json", output_manifest)

    print(f"n_kcs_total: {len(records)}")
    print(f"n_kcs_tier1: {len(tier1_records)}")
    print(f"n_kcs_tier2: {len(tier2_records)}")
    print(f"n_kcs_usable: {len(tier1_records)}")
    print(f"n_kcs_in_recovery_queue: {len(recovery_rows)}")
    print(f"verified_quote_mismatch_count: {len(verified_quote_issues)}")
    print(f"definition_full_count: {definition_full_count}")
    print(f"role_success_count: {role_success_count}")
    print(f"thinking_used_frac: {thinking_used_frac:.4f}")
    if is_subset_run:
        print("subset_run: true")
        print("active_pointer_updated: false")
        return 0
    if acceptance_failures:
        print("acceptance_passed: false")
        print("acceptance_failures:")
        for failure in acceptance_failures:
            print(f"- {failure}")
        print("top_failure_reasons:")
        for reason, count in step6_4_reason_counter.most_common(10):
            print(f"- {reason}: {count}")
        return 2

    print("acceptance_passed: true")
    print("Reply DONE to continue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
