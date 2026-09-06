from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

REPO_SRC = Path(__file__).resolve().parents[3] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from kc_l.audit.manifests import build_output_manifest, env_snapshot, pip_freeze, try_cmd_version
from kc_l.kc.validators import classify_tier, load_schema, schema_version, validate_kc_record


ACTIVE_STEP5_2_EVIDENCE_SHARP_SET = Path("data/processed/kc_evidence_sharp/_sets/ACTIVE_STEP5_2_EVIDENCE_SHARP_SET.txt")
ACTIVE_STEP6_KC_LIBRARY_SET = Path("data/processed/kc_library/_sets/ACTIVE_STEP6_KC_LIBRARY_SET.txt")
SENTENCE_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?<=[\.\?!;:])\s+")


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


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def rel_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def describe_file(path: Path, repo_root: Path) -> Dict[str, Any]:
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
        manifest.append(describe_file(resolved, repo_root))
    manifest.sort(key=lambda item: item["path"])
    return manifest


def resolve_pointer(pointer_path: Path) -> Path:
    raw = read_text(pointer_path).strip()
    if not raw:
        raise RuntimeError(f"Pointer file is empty: {pointer_path}")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (pointer_path.parent / candidate).resolve()
    return candidate


def choose_run_paths(repo_root: Path, processed_root_rel: str, runs_dir_rel: str, sets_dir_rel: str) -> Dict[str, Path]:
    base_stamp = utc_stamp()
    suffix = 0
    while True:
        run_id = base_stamp if suffix == 0 else f"{base_stamp}_{suffix:02d}"
        processed_dir = (repo_root / processed_root_rel / run_id).resolve()
        audit_dir = (repo_root / runs_dir_rel / f"{run_id}_step6_3").resolve()
        set_path = (repo_root / sets_dir_rel / f"{run_id}_step6_3_kc_library_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6_3": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


def import_module(repo_root: Path, rel_script_path: str, module_name: str):
    helper_path = (repo_root / rel_script_path).resolve()
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import helper module from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
class SentenceCandidate:
    quote_id: str
    doc_id: str
    block_id: str
    page_index: int
    layer: str
    bbox: Any
    patch_heading: str
    block_rank: int
    quote: str
    quote_norm: str
    score: float
    exact_name_phrase: bool
    exact_alias_phrase: bool
    canonical_token_hits: int
    alias_token_hits: int
    definitional_cue_hits: int
    heading_name_hits: int
    short_penalty_applied: bool
    alignment_score: float
    retrieval_combined: float


def list_ollama_models() -> List[str]:
    proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"ollama list failed: {proc.stderr.strip() or proc.stdout.strip()}")
    models: List[str] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"\s{2,}", line)
        if parts and parts[0]:
            models.append(parts[0].strip())
    return models


def ollama_show(name: str) -> str:
    proc = subprocess.run(["ollama", "show", name], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def pull_model(name: str, logger: AuditLog) -> Dict[str, Any]:
    logger.info(f"Pulling Ollama model: {name}")
    proc = subprocess.run(["ollama", "pull", name], capture_output=True, text=True, timeout=7200)
    result = {
        "model": name,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
    if proc.returncode == 0:
        logger.info(f"Completed model pull: {name}")
    else:
        logger.info(f"Model pull failed: {name} rc={proc.returncode}")
    return result


def choose_generation_model(installed: Sequence[str], cfg: Mapping[str, Any]) -> str:
    candidates = [str(item) for item in cfg["candidate_models"]]
    installed_set = set(installed)
    latest_marker = str(cfg.get("require_qwen3_5_latest_contains") or "").lower()
    for name in candidates:
        if name not in installed_set:
            continue
        if name == "qwen3.5:latest" and latest_marker:
            if latest_marker not in ollama_show(name).lower():
                continue
        return name
    raise RuntimeError(f"No acceptable generation model installed from {candidates}. Installed={sorted(installed_set)}")


def ollama_http_version(base_url: str, timeout_s: float = 15.0) -> str:
    import urllib.request

    url = base_url.rstrip("/") + "/api/version"
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    return str(obj.get("version", ""))


def ollama_chat_json(
    *,
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    format_schema: Dict[str, Any],
    temperature: float,
    top_p: float,
    num_ctx: int,
    repeat_penalty: float,
    think: Optional[bool],
    timeout_s: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    import urllib.request

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": format_schema,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_ctx": num_ctx,
            "repeat_penalty": repeat_penalty,
        },
    }
    if think is not None:
        payload["think"] = bool(think)
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    outer = json.loads(raw)
    content = (outer.get("message") or {}).get("content", "")
    if isinstance(content, dict):
        return content, outer, raw
    parsed = json.loads(str(content))
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama chat response content was not a JSON object.")
    return parsed, outer, raw


def split_sentences(raw_text: str, step6lib: Any) -> List[str]:
    pieces = [step6lib.normalize_ws(part) for part in SENTENCE_SPLIT_RE.split(raw_text) if step6lib.normalize_ws(part)]
    if not pieces and step6lib.normalize_ws(raw_text):
        return [step6lib.normalize_ws(raw_text)]
    return pieces


def count_hits(target_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> int:
    candidate_set = set(candidate_tokens)
    return sum(1 for token in target_tokens if token in candidate_set)


def quote_terms(kc_row: Mapping[str, Any], step6lib: Any) -> Dict[str, Any]:
    canonical_name = step6lib.normalize_ws(str(kc_row.get("canonical_name") or ""))
    aliases = [step6lib.normalize_ws(str(item)) for item in step6lib.ensure_string_list(kc_row.get("aliases"))]
    canonical_norm = step6lib.match_normalize(canonical_name)
    alias_norms = [step6lib.match_normalize(alias) for alias in aliases]
    return {
        "canonical_norm": canonical_norm,
        "alias_norms": alias_norms,
        "canonical_tokens": step6lib.tokenize(canonical_norm),
        "alias_tokens": [token for alias in alias_norms for token in step6lib.tokenize(alias)],
        "heading_terms": [term for term in [canonical_norm] + alias_norms if term],
    }


def build_block_rows(
    *,
    step5_row: Mapping[str, Any],
    source_lookup: Mapping[str, Mapping[str, Any]],
    top_n: int,
    step6lib: Any,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    blocks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen_blocks: set[str] = set()
    for raw_idx, raw in enumerate(step5_row.get("evidence") or []):
        block_id = str(raw.get("block_id") or "")
        if not block_id or block_id in seen_blocks:
            continue
        seen_blocks.add(block_id)
        source_row = source_lookup.get(block_id)
        if source_row is None:
            warnings.append(f"MissingSourceBlock:{block_id}")
            continue
        raw_text = str(source_row.get("text") or "")
        if not step6lib.normalize_ws(raw_text):
            warnings.append(f"EmptySourceText:{block_id}")
            continue
        blocks.append(
            {
                "doc_id": str(raw.get("doc_id") or source_row.get("doc_id") or ""),
                "block_id": block_id,
                "page_index": int(raw.get("page_index") if raw.get("page_index") is not None else source_row.get("page_index", -1)),
                "bbox": raw.get("bbox"),
                "layer": str(raw.get("layer") or source_row.get("layer") or ""),
                "patch_heading": str(raw.get("patch_heading") or ""),
                "alignment_score": float(raw.get("alignment_score") or 0.0),
                "retrieval_combined": float(((raw.get("retrieval_scores") or {}).get("combined")) or 0.0),
                "source_text_raw": raw_text,
                "source_text": step6lib.normalize_ws(raw_text),
                "block_rank": raw_idx,
            }
        )
        if len(blocks) >= top_n:
            break
    return blocks, warnings


def score_sentence(
    *,
    sentence: str,
    block: Mapping[str, Any],
    terms: Mapping[str, Any],
    cue_terms: Sequence[str],
    weights: Mapping[str, Any],
    cfg: Mapping[str, Any],
    step6lib: Any,
) -> Optional[SentenceCandidate]:
    quote = step6lib.normalize_ws(sentence)
    if not quote or len(quote) > int(cfg["quote_max_chars"]):
        return None

    quote_norm = step6lib.match_normalize(quote)
    quote_tokens = step6lib.tokenize(quote_norm)
    if len(quote) < int(cfg["min_sentence_chars"]) or len(quote_tokens) < int(cfg["min_sentence_tokens"]):
        return None

    exact_name_phrase = bool(terms["canonical_norm"] and terms["canonical_norm"] in quote_norm)
    exact_alias_phrase = any(alias and alias in quote_norm for alias in terms["alias_norms"])
    canonical_token_hits = count_hits(terms["canonical_tokens"], quote_tokens)
    alias_token_hits = count_hits(terms["alias_tokens"], quote_tokens)
    heading_norm = step6lib.match_normalize(str(block.get("patch_heading") or ""))
    heading_name_hits = sum(1 for term in terms["heading_terms"] if term and term in heading_norm)
    definitional_cue_hits = sum(1 for cue in cue_terms if cue and cue in quote_norm)
    short_penalty = len(quote) < int(cfg["soft_min_sentence_chars"]) or len(quote_tokens) < int(cfg["soft_min_sentence_tokens"])

    score = 0.0
    score += float(weights["exact_name_phrase"]) if exact_name_phrase else 0.0
    score += float(weights["exact_alias_phrase"]) if exact_alias_phrase else 0.0
    score += canonical_token_hits * float(weights["canonical_token_hit"])
    score += alias_token_hits * float(weights["alias_token_hit"])
    score += definitional_cue_hits * float(weights["definitional_cue_hit"])
    score += heading_name_hits * float(weights["heading_name_hit"])
    score += float(block.get("alignment_score") or 0.0) * float(weights["block_alignment_score"])
    score += float(block.get("retrieval_combined") or 0.0) * float(weights["block_retrieval_score"])
    score += max(0.0, float(12 - int(block.get("block_rank") or 0))) * float(weights["early_rank_bonus"])
    if short_penalty:
        score -= float(weights["soft_short_penalty"])

    return SentenceCandidate(
        quote_id="",
        doc_id=str(block["doc_id"]),
        block_id=str(block["block_id"]),
        page_index=int(block["page_index"]),
        layer=str(block["layer"]),
        bbox=block.get("bbox"),
        patch_heading=str(block.get("patch_heading") or ""),
        block_rank=int(block.get("block_rank") or 0),
        quote=quote,
        quote_norm=quote_norm,
        score=float(score),
        exact_name_phrase=exact_name_phrase,
        exact_alias_phrase=exact_alias_phrase,
        canonical_token_hits=int(canonical_token_hits),
        alias_token_hits=int(alias_token_hits),
        definitional_cue_hits=int(definitional_cue_hits),
        heading_name_hits=int(heading_name_hits),
        short_penalty_applied=bool(short_penalty),
        alignment_score=float(block.get("alignment_score") or 0.0),
        retrieval_combined=float(block.get("retrieval_combined") or 0.0),
    )


def build_sentence_candidates(
    *,
    kc_row: Mapping[str, Any],
    blocks: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any],
    step6lib: Any,
) -> List[SentenceCandidate]:
    terms = quote_terms(kc_row, step6lib)
    cue_terms = [step6lib.match_normalize(str(item)) for item in cfg["definition_cues"] if str(item).strip()]
    weights = cfg["weights"]
    candidates: List[SentenceCandidate] = []
    seen: set[Tuple[str, str]] = set()

    for block in blocks:
        for sentence in split_sentences(str(block["source_text_raw"]), step6lib):
            candidate = score_sentence(
                sentence=sentence,
                block=block,
                terms=terms,
                cue_terms=cue_terms,
                weights=weights,
                cfg=cfg,
                step6lib=step6lib,
            )
            if candidate is None:
                continue
            dedupe_key = (candidate.block_id, candidate.quote_norm)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item.score,
            item.exact_name_phrase,
            item.exact_alias_phrase,
            item.canonical_token_hits,
            item.alias_token_hits,
            item.definitional_cue_hits,
            -item.block_rank,
            item.block_id,
            item.quote_norm,
        ),
        reverse=True,
    )
    return candidates


def select_quotes(
    candidates: Sequence[SentenceCandidate],
    *,
    target_count: int,
    max_per_block: int,
) -> List[SentenceCandidate]:
    selected: List[SentenceCandidate] = []
    block_counts: Counter[str] = Counter()
    selected_quotes: set[str] = set()

    for candidate in candidates:
        if candidate.quote_norm in selected_quotes:
            continue
        if block_counts[candidate.block_id] > 0:
            continue
        selected.append(candidate)
        selected_quotes.add(candidate.quote_norm)
        block_counts[candidate.block_id] += 1
        if len(selected) >= target_count:
            break

    if len(selected) < target_count:
        for candidate in candidates:
            if candidate.quote_norm in selected_quotes:
                continue
            if block_counts[candidate.block_id] >= max_per_block:
                continue
            selected.append(candidate)
            selected_quotes.add(candidate.quote_norm)
            block_counts[candidate.block_id] += 1
            if len(selected) >= target_count:
                break

    finalized: List[SentenceCandidate] = []
    for idx, item in enumerate(selected, start=1):
        finalized.append(
            SentenceCandidate(
                quote_id=f"Q{idx}",
                doc_id=item.doc_id,
                block_id=item.block_id,
                page_index=item.page_index,
                layer=item.layer,
                bbox=item.bbox,
                patch_heading=item.patch_heading,
                block_rank=item.block_rank,
                quote=item.quote,
                quote_norm=item.quote_norm,
                score=item.score,
                exact_name_phrase=item.exact_name_phrase,
                exact_alias_phrase=item.exact_alias_phrase,
                canonical_token_hits=item.canonical_token_hits,
                alias_token_hits=item.alias_token_hits,
                definitional_cue_hits=item.definitional_cue_hits,
                heading_name_hits=item.heading_name_hits,
                short_penalty_applied=item.short_penalty_applied,
                alignment_score=item.alignment_score,
                retrieval_combined=item.retrieval_combined,
            )
        )
    return finalized


def build_role_schema(allowed_kc_types: Sequence[str], role_labels: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "kc_type",
            "quote_annotations",
            "definition_short",
            "definition_short_quote_ids",
            "definition_full",
            "definition_full_quote_ids",
            "definition_extractive",
        ],
        "properties": {
            "kc_type": {"type": "string", "enum": list(allowed_kc_types)},
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
            "definition_short": {"type": "string"},
            "definition_short_quote_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "definition_full": {"type": "string"},
            "definition_full_quote_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "definition_extractive": {"type": "boolean"},
        },
    }


def validate_role_payload(
    payload: Mapping[str, Any],
    *,
    quote_ids: Sequence[str],
    allowed_kc_types: Sequence[str],
    role_labels: Sequence[str],
) -> List[str]:
    errors: List[str] = []
    required = {
        "kc_type",
        "quote_annotations",
        "definition_short",
        "definition_short_quote_ids",
        "definition_full",
        "definition_full_quote_ids",
        "definition_extractive",
    }
    for key in required:
        if key not in payload:
            errors.append(f"{key}: missing")
    if payload.get("kc_type") not in allowed_kc_types:
        errors.append("kc_type: invalid")
    if not isinstance(payload.get("definition_short"), str):
        errors.append("definition_short: expected string")
    if not isinstance(payload.get("definition_full"), str):
        errors.append("definition_full: expected string")
    if not isinstance(payload.get("definition_extractive"), bool):
        errors.append("definition_extractive: expected boolean")

    for key in ["definition_short_quote_ids", "definition_full_quote_ids"]:
        value = payload.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{key}: expected string array")
            continue
        if any(item not in quote_ids for item in value):
            errors.append(f"{key}: unknown quote id")

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
    kc_row: Mapping[str, Any],
    selected_quotes: Sequence[SentenceCandidate],
    forced_type: Optional[str],
    cfg: Mapping[str, Any],
) -> Tuple[str, str]:
    system_prompt = (
        "You label grounded quote evidence for a knowledge component and write a grounded definition. "
        "Use only the provided quotes. Do not invent facts. "
        "Return JSON only. "
        "Assign one role to every quote. "
        "If a safe rewrite is not possible, copy the best quote as definition_short and set definition_extractive=true."
    )
    user_payload = {
        "task": "Relabel extractive quotes and write grounded definitions.",
        "kc": {
            "kc_id": kc_row["kc_id"],
            "kc_path": kc_row["kc_path"],
            "canonical_name": kc_row["canonical_name"],
            "aliases": kc_row.get("aliases") or [],
            "seed_definition": kc_row.get("seed_definition") or "",
        },
        "forced_kc_type": forced_type or "",
        "allowed_kc_types": list(cfg["allowed_kc_types"]),
        "allowed_quote_roles": list(cfg["role_labels"]),
        "definition_short_max_chars": int(cfg["definition_short_max_chars"]),
        "definition_full_max_chars": int(cfg["definition_full_max_chars"]),
        "rules": [
            "Use only the provided quotes as evidence.",
            "Every quote annotation must reference one of the given quote_id values.",
            "definition_short must be grounded in the listed support quotes.",
            "definition_full is optional and must stay empty if unsupported.",
            "Do not add unsupported scope, procedure steps, or extra claims.",
        ],
        "quotes": [
            {
                "quote_id": item.quote_id,
                "doc_id": item.doc_id,
                "block_id": item.block_id,
                "page_index": item.page_index,
                "layer": item.layer,
                "quote": item.quote,
            }
            for item in selected_quotes
        ],
    }
    return system_prompt, json.dumps(user_payload, ensure_ascii=False)


def default_role_payload(*, forced_type: Optional[str], selected_quotes: Sequence[SentenceCandidate]) -> Dict[str, Any]:
    best_quote = selected_quotes[0].quote if selected_quotes else ""
    best_quote_id = selected_quotes[0].quote_id if selected_quotes else ""
    return {
        "kc_type": forced_type or "concept",
        "quote_annotations": [{"quote_id": item.quote_id, "role": "other"} for item in selected_quotes],
        "definition_short": best_quote,
        "definition_short_quote_ids": [best_quote_id] if best_quote_id else [],
        "definition_full": "",
        "definition_full_quote_ids": [],
        "definition_extractive": bool(best_quote),
    }


def evidence_from_quote(candidate: SentenceCandidate, role: str) -> Dict[str, Any]:
    return {
        "doc_id": candidate.doc_id,
        "block_id": candidate.block_id,
        "page_index": candidate.page_index,
        "layer": candidate.layer,
        "bbox": candidate.bbox,
        "role": role,
        "quote": candidate.quote,
        "extraction_method": "extractive_quote_first:step6_3",
        "quote_verified": True,
        "provenance_quality_flags": [],
    }


def verify_evidence_items(
    *,
    kc_id: str,
    evidence_items: Sequence[Mapping[str, Any]],
    source_lookup: Mapping[str, Mapping[str, Any]],
    step6lib: Any,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    verified: List[Dict[str, Any]] = []
    issues: List[str] = []
    for evidence in evidence_items:
        probe = {"kc_id": kc_id, "evidence_minimal": [dict(evidence)], "field_evidence_map": {}}
        mismatches = step6lib.find_verified_quote_mismatches(probe, source_lookup)
        if mismatches:
            issues.extend(mismatches)
            continue
        verified.append(dict(evidence))
    return verified, issues


def support_evidence(
    *,
    quote_ids: Sequence[str],
    quote_lookup: Mapping[str, SentenceCandidate],
    quote_role_map: Mapping[str, str],
    kc_id: str,
    source_lookup: Mapping[str, Mapping[str, Any]],
    step6lib: Any,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    evidence = [evidence_from_quote(quote_lookup[quote_id], quote_role_map.get(quote_id, "other")) for quote_id in quote_ids if quote_id in quote_lookup]
    verified, issues = verify_evidence_items(
        kc_id=kc_id,
        evidence_items=evidence,
        source_lookup=source_lookup,
        step6lib=step6lib,
    )
    return step6lib.dedupe_evidence(verified), issues


def failure_distribution(records: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        for reason in record.get("recovery_reasons") or []:
            counter[str(reason)] += 1
    return dict(counter.most_common(10))


def build_set_manifest(
    *,
    repo_root: Path,
    set_path: Path,
    run_id_step6_3: str,
    processed_dir: Path,
    audit_dir: Path,
    created_utc: str,
    kc_registry_path: Path,
    step5_2_pointer_path: Path,
    step5_2_set_path: Path,
    step4_set_path: Path,
    step5_2_manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    step5_outputs = []
    for name, rel in (step5_2_manifest.get("artifacts") or {}).items():
        path = (repo_root / str(rel)).resolve()
        step5_outputs.append({"name": name, **describe_file(path, repo_root)})

    return {
        "schema_version": "1.0",
        "kind": "step6_3_kc_library_set",
        "set_id": set_path.stem,
        "created_utc": created_utc,
        "run_id_step6_3": run_id_step6_3,
        "artifacts": {
            "kc_library_jsonl": rel_path((processed_dir / "kc_library.jsonl").resolve(), repo_root),
            "kc_library_stats_json": rel_path((processed_dir / "kc_library_stats.json").resolve(), repo_root),
            "recovery_queue_jsonl": rel_path((processed_dir / "recovery_queue.jsonl").resolve(), repo_root),
            "extraction_traces_dir": rel_path((processed_dir / "extraction_traces").resolve(), repo_root),
        },
        "upstream": {
            "kc_registry": describe_file(kc_registry_path, repo_root),
            "step5_2_active_set_pointer": describe_file(step5_2_pointer_path, repo_root),
            "step5_2_active_set_target": describe_file(step5_2_set_path, repo_root),
            "step4_set_target": describe_file(step4_set_path, repo_root),
            "step5_2_processed_outputs": step5_outputs,
        },
        "audit": {
            "run_dir": rel_path(audit_dir.resolve(), repo_root),
            "input_manifest": rel_path((audit_dir / "input_manifest.json").resolve(), repo_root),
            "output_manifest": rel_path((audit_dir / "output_manifest.json").resolve(), repo_root),
            "summary": rel_path((audit_dir / "summary.json").resolve(), repo_root),
        },
    }


def sample_kc_ids(registry_rows: Sequence[Mapping[str, Any]], sample_n: int) -> List[str]:
    return sorted(str(row["kc_id"]) for row in registry_rows)[:sample_n]


def run() -> int:
    parser = argparse.ArgumentParser(description="STEP 6.3: Quote-first KC extraction with extractive fallback.")
    parser.add_argument("--config", required=True, help="Repo-relative YAML config path.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    cfg = load_yaml(config_path)
    step6lib = import_module(repo_root, "steps/step_06_kc_library_extract/scripts/run_step6.py", "step6_3_shared")

    inputs_cfg = cfg["inputs"]
    model_cfg = cfg["model_selection"]
    quote_cfg = cfg["quote_extraction"]
    extraction_cfg = cfg["extraction"]
    outputs_cfg = cfg["outputs"]
    audit_cfg = cfg["audit"]
    runtime_cfg = cfg["runtime"]
    acceptance_cfg = cfg["acceptance"]

    schema_path = (repo_root / str(inputs_cfg["schema_path"])).resolve()
    kc_registry_path = (repo_root / str(inputs_cfg["kc_registry_path"])).resolve()
    step5_2_pointer_path = (repo_root / str(inputs_cfg["step5_2_active_set_pointer"])).resolve()
    active_pointer_path = (repo_root / ACTIVE_STEP6_KC_LIBRARY_SET).resolve()

    step5_2_set_path = resolve_pointer(step5_2_pointer_path)
    step5_2_manifest = load_json(step5_2_set_path)
    if str(step5_2_manifest.get("run_id_step5_2")) != "2026-03-06_173902":
        raise RuntimeError(f"Active Step 5.2 set is not the accepted run: {step5_2_manifest.get('run_id_step5_2')}")
    candidates_path = (repo_root / str(step5_2_manifest["artifacts"]["kc_evidence_candidates_sharp_jsonl"])).resolve()
    step4_set_path = (repo_root / str(step5_2_manifest["upstream"]["step4_active_set_target"])).resolve()
    step4_manifest = load_json(step4_set_path)

    run_paths = choose_run_paths(
        repo_root=repo_root,
        processed_root_rel=str(outputs_cfg["processed_root"]),
        runs_dir_rel=str(audit_cfg["runs_dir"]),
        sets_dir_rel=str(outputs_cfg["sets_dir"]),
    )
    run_id_step6_3 = run_paths["run_id_step6_3"].name
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    created_utc = now_utc_iso()

    audit_dir.mkdir(parents=True, exist_ok=False)
    processed_dir.mkdir(parents=True, exist_ok=False)
    trace_dir = processed_dir / "extraction_traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    logger = AuditLog(audit_dir / "logs" / "run.log")

    started = time.perf_counter()
    timings: Dict[str, Any] = {"started_utc": created_utc}
    write_text(audit_dir / "config.snapshot.yaml", read_text(config_path))
    write_json(
        audit_dir / "invocation.json",
        {"argv": sys.argv, "cwd": ".", "config": rel_path(config_path, repo_root), "run_id_step6_3": run_id_step6_3},
    )
    write_json(audit_dir / "env_snapshot.json", {"snapshot": env_snapshot(), "pip_freeze": pip_freeze()})

    installed_before = list_ollama_models()
    pull_result: Optional[Dict[str, Any]] = None
    preferred_pull_model = str(model_cfg.get("preferred_pull_model") or "")
    if bool(model_cfg.get("auto_pull_preferred_model", False)) and preferred_pull_model and preferred_pull_model not in installed_before:
        pull_result = pull_model(preferred_pull_model, logger)
    installed_after = list_ollama_models()
    chosen_model = choose_generation_model(installed_after, model_cfg)
    logger.info(f"Step 6.3 starting with generation model {chosen_model}")

    write_json(
        audit_dir / "tool_versions.json",
        {
            "python": sys.version,
            "pyyaml_available": yaml is not None,
            "ollama_cli": try_cmd_version(["ollama", "--version"]),
            "ollama_http_version": ollama_http_version(str(extraction_cfg["ollama_base_url"])),
            "generation_model": chosen_model,
            "installed_models_before_prepare": installed_before,
            "installed_models_after_prepare": installed_after,
            "model_pull_result": pull_result,
        },
    )

    load_started = time.perf_counter()
    schema = load_schema(schema_path)
    schema_ver = schema_version(schema)
    registry_rows = list(jsonl_iter(kc_registry_path))
    candidate_rows = list(jsonl_iter(candidates_path))
    candidate_by_kc = {str(row["kc_id"]): row for row in candidate_rows}
    if len(candidate_by_kc) != len(registry_rows):
        raise RuntimeError(
            f"KC registry count and Step 5.2 sharp candidates count differ: registry={len(registry_rows)} step5_2={len(candidate_by_kc)}"
        )

    source_lookup: Dict[str, Dict[str, Any]] = {}
    input_paths = [schema_path, kc_registry_path, step5_2_pointer_path, step5_2_set_path, step4_set_path, candidates_path]
    for doc_payload in (step4_manifest.get("docs") or {}).values():
        corpus_rel = ((doc_payload.get("artifacts") or {}).get("block_text_corpus.jsonl") or {}).get("path")
        if not corpus_rel:
            continue
        corpus_path = (repo_root / str(corpus_rel)).resolve()
        input_paths.append(corpus_path)
        for row in jsonl_iter(corpus_path):
            source_lookup[str(row["block_id"])] = row
    write_json(audit_dir / "input_manifest.json", build_repo_manifest(input_paths, repo_root))
    timings["load_seconds"] = round(time.perf_counter() - load_started, 3)

    allowed_kc_types = [str(item) for item in extraction_cfg["allowed_kc_types"]]
    role_labels = [str(item) for item in extraction_cfg["role_labels"]]
    role_schema = build_role_schema(allowed_kc_types, role_labels)
    sample_ids = set(sample_kc_ids(registry_rows, int(runtime_cfg["sample_kcs"])))

    records: List[Dict[str, Any]] = []
    recovery_rows: List[Dict[str, Any]] = []
    extraction_started = time.perf_counter()

    for index, row in enumerate(registry_rows, start=1):
        kc_id = str(row["kc_id"])
        step5_2_row = candidate_by_kc.get(kc_id)
        if step5_2_row is None:
            raise RuntimeError(f"Missing Step 5.2 row for {kc_id}")

        record = step6lib.default_record_shell(
            kc_row=row,
            step4_set_id=str(step4_manifest.get("set_id") or ""),
            step5_set_id=str(step5_2_manifest.get("set_id") or ""),
            run_id_step6=run_id_step6_3,
            created_utc=created_utc,
            schema_ver=schema_ver,
        )

        blocks, block_warnings = build_block_rows(
            step5_row=step5_2_row,
            source_lookup=source_lookup,
            top_n=int(quote_cfg["top_evidence_blocks_per_kc"]),
            step6lib=step6lib,
        )
        record["quality_flags"].extend(block_warnings)

        sentence_candidates = build_sentence_candidates(
            kc_row=row,
            blocks=blocks,
            cfg=quote_cfg,
            step6lib=step6lib,
        )
        selected_quotes = select_quotes(
            sentence_candidates,
            target_count=int(quote_cfg["selected_quotes_target"]),
            max_per_block=int(quote_cfg["max_quotes_per_block"]),
        )

        forced_type, _ = step6lib.rules_based_kc_type(blocks)
        quote_ids = [item.quote_id for item in selected_quotes]
        payload = default_role_payload(forced_type=forced_type, selected_quotes=selected_quotes)
        raw_response = ""
        raw_outer: Dict[str, Any] = {}
        model_errors: List[str] = []

        if selected_quotes:
            prompt_system, prompt_user = role_label_prompt(
                kc_row=row,
                selected_quotes=selected_quotes,
                forced_type=forced_type,
                cfg={**extraction_cfg, "role_labels": role_labels},
            )
            messages = [{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}]
            for attempt in range(int(extraction_cfg["max_retries"])):
                try:
                    candidate_payload, outer, raw = ollama_chat_json(
                        base_url=str(extraction_cfg["ollama_base_url"]),
                        model=chosen_model,
                        messages=messages,
                        format_schema=role_schema,
                        temperature=float(extraction_cfg["temperature"]),
                        top_p=float(extraction_cfg["top_p"]),
                        num_ctx=int(extraction_cfg["num_ctx"]),
                        repeat_penalty=float(extraction_cfg["repeat_penalty"]),
                        think=bool(extraction_cfg["think"]) if "think" in extraction_cfg else None,
                        timeout_s=float(extraction_cfg["timeout_seconds"]),
                    )
                    validation_errors = validate_role_payload(
                        candidate_payload,
                        quote_ids=quote_ids,
                        allowed_kc_types=allowed_kc_types,
                        role_labels=role_labels,
                    )
                    if validation_errors:
                        model_errors.append(f"Attempt{attempt + 1}:InvalidPayload:{';'.join(validation_errors[:8])}")
                        messages.append(
                            {
                                "role": "user",
                                "content": f"The previous JSON failed validation: {validation_errors[:8]}. Return corrected JSON only.",
                            }
                        )
                        continue
                    payload = dict(candidate_payload)
                    raw_outer = outer
                    raw_response = raw
                    break
                except Exception as exc:
                    model_errors.append(f"Attempt{attempt + 1}:{repr(exc)}")
                    messages.append(
                        {
                            "role": "user",
                            "content": f"The previous response failed because {repr(exc)}. Return corrected JSON only.",
                        }
                    )
            else:
                record["quality_flags"].append("QuoteRoleLabelingFailed")
        else:
            record["quality_flags"].append("NoExtractiveQuotesSelected")

        record["quality_flags"].extend(model_errors)
        if forced_type:
            record["kc_type"] = forced_type
            if str(payload.get("kc_type") or "").strip() and str(payload.get("kc_type")).strip() != forced_type:
                record["quality_flags"].append("ModelTypeOverriddenByRules")
        else:
            model_type = str(payload.get("kc_type") or "").strip()
            record["kc_type"] = model_type if model_type in allowed_kc_types else "concept"

        quote_role_map = {
            str(item["quote_id"]): str(item["role"])
            for item in payload.get("quote_annotations") or []
            if isinstance(item, Mapping)
        }
        quote_lookup = {item.quote_id: item for item in selected_quotes}
        selected_quote_norms = {item.quote_norm for item in selected_quotes}

        base_evidence = [
            evidence_from_quote(quote_lookup[quote_id], quote_role_map.get(quote_id, "other"))
            for quote_id in quote_ids
            if quote_id in quote_lookup
        ]
        verified_quotes, verify_issues = verify_evidence_items(
            kc_id=kc_id,
            evidence_items=base_evidence,
            source_lookup=source_lookup,
            step6lib=step6lib,
        )
        record["quality_flags"].extend(verify_issues)
        record["evidence_minimal"] = step6lib.dedupe_evidence(verified_quotes)[: int(extraction_cfg["evidence_minimal_max"])]
        if len({(item["block_id"], item["quote"]) for item in record["evidence_minimal"]}) < 2:
            record["recovery_reasons"].append("LessThanTwoVerifiedExtractiveQuotes")

        definition_short = step6lib.normalize_ws(str(payload.get("definition_short") or ""))
        definition_full = step6lib.normalize_ws(str(payload.get("definition_full") or ""))
        definition_extractive = bool(payload.get("definition_extractive"))
        short_support_ids = [item for item in payload.get("definition_short_quote_ids") or [] if item in quote_lookup]
        full_support_ids = [item for item in payload.get("definition_full_quote_ids") or [] if item in quote_lookup]
        fallback_quote_id = short_support_ids[0] if short_support_ids else (quote_ids[0] if quote_ids else "")

        short_evidence, short_issues = support_evidence(
            quote_ids=short_support_ids or ([fallback_quote_id] if fallback_quote_id else []),
            quote_lookup=quote_lookup,
            quote_role_map=quote_role_map,
            kc_id=kc_id,
            source_lookup=source_lookup,
            step6lib=step6lib,
        )
        record["quality_flags"].extend(short_issues)
        if not definition_short and fallback_quote_id and fallback_quote_id in quote_lookup:
            definition_short = quote_lookup[fallback_quote_id].quote
            definition_extractive = True
        if definition_short and not short_evidence and fallback_quote_id and fallback_quote_id in quote_lookup:
            definition_short = quote_lookup[fallback_quote_id].quote
            definition_extractive = True
            short_evidence, short_issues = support_evidence(
                quote_ids=[fallback_quote_id],
                quote_lookup=quote_lookup,
                quote_role_map=quote_role_map,
                kc_id=kc_id,
                source_lookup=source_lookup,
                step6lib=step6lib,
            )
            record["quality_flags"].extend(short_issues)
        if definition_short and short_evidence:
            record["definition_short"] = definition_short
            record["field_evidence_map"]["definition_short"] = short_evidence
            if definition_extractive:
                record["quality_flags"].append("DefinitionExtractive")
        elif definition_short:
            record["quality_flags"].append("DefinitionShortUnsupported")

        full_evidence, full_issues = support_evidence(
            quote_ids=full_support_ids,
            quote_lookup=quote_lookup,
            quote_role_map=quote_role_map,
            kc_id=kc_id,
            source_lookup=source_lookup,
            step6lib=step6lib,
        )
        record["quality_flags"].extend(full_issues)
        if definition_full and full_evidence:
            record["definition_full"] = definition_full
            record["field_evidence_map"]["definition_full"] = full_evidence
        elif definition_full:
            record["quality_flags"].append("DefinitionFullUnsupported")

        if not record["definition_short"] and not record["definition_full"]:
            record["recovery_reasons"].append("NoGroundedDefinition")

        record["quality_flags"] = step6lib.unique_preserve_order(record["quality_flags"])
        record["recovery_reasons"] = step6lib.unique_preserve_order(record["recovery_reasons"])

        validation_errors = validate_kc_record(record)
        if validation_errors:
            raise RuntimeError(f"Schema validation failed for {kc_id}: {validation_errors[:10]}")

        tier_info = step6lib.apply_tier_classification(record)
        records.append(record)
        if int(tier_info["tier"]) < 1:
            recovery_rows.append(
                {
                    "kc_id": kc_id,
                    "tier": int(tier_info["tier"]),
                    "tier1_fail_reasons": list(tier_info["reasons"]),
                    "reasons": list(record["recovery_reasons"]),
                    "top_blocks_considered": [str(item["block_id"]) for item in blocks],
                    "selected_quotes": [
                        {
                            "quote_id": item.quote_id,
                            "block_id": item.block_id,
                            "role": quote_role_map.get(item.quote_id, "other"),
                            "quote": item.quote,
                        }
                        for item in selected_quotes
                    ],
                }
            )

        if kc_id in sample_ids:
            write_json(
                trace_dir / f"trace_{kc_id}.json",
                {
                    "kc_id": kc_id,
                    "top_blocks": blocks,
                    "quote_scoring": [
                        {
                            "quote": item.quote,
                            "block_id": item.block_id,
                            "page_index": item.page_index,
                            "score": item.score,
                            "canonical_token_hits": item.canonical_token_hits,
                            "alias_token_hits": item.alias_token_hits,
                            "definitional_cue_hits": item.definitional_cue_hits,
                            "exact_name_phrase": item.exact_name_phrase,
                            "exact_alias_phrase": item.exact_alias_phrase,
                            "heading_name_hits": item.heading_name_hits,
                            "short_penalty_applied": item.short_penalty_applied,
                            "selected": item.quote_norm in selected_quote_norms,
                        }
                        for item in sentence_candidates[:40]
                    ],
                    "selected_quotes": [
                        {
                            "quote_id": item.quote_id,
                            "doc_id": item.doc_id,
                            "block_id": item.block_id,
                            "page_index": item.page_index,
                            "layer": item.layer,
                            "role": quote_role_map.get(item.quote_id, "other"),
                            "quote": item.quote,
                            "score": item.score,
                        }
                        for item in selected_quotes
                    ],
                    "rules_based_type": forced_type or "",
                    "model_payload": payload,
                    "model_response_raw": raw_response,
                    "model_outer_response": raw_outer,
                    "validation": {
                        "tier": int(tier_info["tier"]),
                        "tier_reasons": list(tier_info["reasons"]),
                        "quality_flags": list(record["quality_flags"]),
                        "record_errors": validation_errors,
                    },
                    "final_record_snippet": {
                        "kc_type": record["kc_type"],
                        "definition_short": record["definition_short"],
                        "definition_full": record["definition_full"],
                        "evidence_minimal": record["evidence_minimal"],
                        "field_evidence_map": record["field_evidence_map"],
                    },
                },
            )

        if index % int(runtime_cfg["progress_every"]) == 0:
            logger.info(f"Processed {index}/{len(registry_rows)} KCs")

    timings["extraction_seconds"] = round(time.perf_counter() - extraction_started, 3)

    verified_quote_issues: List[str] = []
    for record in records:
        verified_quote_issues.extend(step6lib.find_verified_quote_mismatches(record, source_lookup))

    tier_results = {str(record["kc_id"]): classify_tier(record) for record in records}
    tier1_records = [record for record in records if int(tier_results[str(record["kc_id"])]["tier"]) >= 1]
    tier2_records = [record for record in records if int(tier_results[str(record["kc_id"])]["tier"]) >= 2]
    evidence_sizes = [len(record["evidence_minimal"]) for record in records]
    median_evidence_size = float(statistics.median(evidence_sizes)) if evidence_sizes else 0.0

    kc_library_path = processed_dir / "kc_library.jsonl"
    stats_path = processed_dir / "kc_library_stats.json"
    recovery_path = processed_dir / "recovery_queue.jsonl"
    write_jsonl(kc_library_path, records)
    write_jsonl(recovery_path, recovery_rows)

    recovery_reason_distribution = failure_distribution(records)
    field_coverage = {
        "definition_short": round(100.0 * sum(1 for r in records if str(r["definition_short"]).strip()) / len(records), 2),
        "definition_full": round(100.0 * sum(1 for r in records if str(r["definition_full"]).strip()) / len(records), 2),
        "evidence_minimal": round(100.0 * sum(1 for r in records if len(r["evidence_minimal"]) > 0) / len(records), 2),
    }

    acceptance_failures: List[str] = []
    if len(records) != int(acceptance_cfg["n_kcs_total"]):
        acceptance_failures.append(f"Expected n_kcs_total={int(acceptance_cfg['n_kcs_total'])}, observed {len(records)}")
    if len(tier1_records) < int(acceptance_cfg["min_tier1_count"]):
        acceptance_failures.append(f"Tier1 count {len(tier1_records)} < {int(acceptance_cfg['min_tier1_count'])}")
    if len(verified_quote_issues) > int(acceptance_cfg["max_verified_quote_mismatches"]):
        acceptance_failures.append(
            f"Verified quote mismatch count {len(verified_quote_issues)} > {int(acceptance_cfg['max_verified_quote_mismatches'])}"
        )
    if median_evidence_size < float(acceptance_cfg["min_median_evidence_minimal_size"]):
        acceptance_failures.append(
            f"Median evidence_minimal size {median_evidence_size:.2f} < {float(acceptance_cfg['min_median_evidence_minimal_size']):.2f}"
        )
    if len(recovery_rows) > int(acceptance_cfg["max_recovery_queue_count"]):
        acceptance_failures.append(f"Recovery queue count {len(recovery_rows)} > {int(acceptance_cfg['max_recovery_queue_count'])}")
    recovery_ids = {str(row["kc_id"]) for row in recovery_rows}
    tier0_ids = {str(record["kc_id"]) for record in records if int(tier_results[str(record["kc_id"])]["tier"]) == 0}
    if recovery_ids != tier0_ids:
        acceptance_failures.append("Recovery queue does not match Tier 0 records")

    stats_payload = {
        "run_id_step6_3": run_id_step6_3,
        "n_kcs_total": len(records),
        "n_kcs_tier1": len(tier1_records),
        "n_kcs_tier2": len(tier2_records),
        "n_kcs_usable": len(tier1_records),
        "n_kcs_in_recovery_queue": len(recovery_rows),
        "verified_quote_mismatch_count": len(verified_quote_issues),
        "median_evidence_minimal_size": median_evidence_size,
        "coverage_percent": field_coverage,
        "evidence_minimal_size_distribution": {str(k): int(v) for k, v in sorted(Counter(evidence_sizes).items())},
        "recovery_reason_distribution_top10": recovery_reason_distribution,
        "stats_meta": {
            "usable_definition": "Tier 1 (retrieval-usable)",
            "tier_contract": "Step 6.3 quote-first",
        },
        "acceptance": {
            "targets": dict(acceptance_cfg),
            "passed": not acceptance_failures,
            "failures": acceptance_failures,
        },
    }
    write_json(stats_path, stats_payload)

    summary_payload = {
        "run_id_step6_3": run_id_step6_3,
        "status": "success" if not acceptance_failures else "acceptance_failed",
        "created_utc": created_utc,
        "n_kcs_total": len(records),
        "n_kcs_tier1": len(tier1_records),
        "n_kcs_tier2": len(tier2_records),
        "n_kcs_usable": len(tier1_records),
        "n_kcs_in_recovery_queue": len(recovery_rows),
        "verified_quote_mismatch_count": len(verified_quote_issues),
        "median_evidence_minimal_size": median_evidence_size,
        "acceptance_passed": not acceptance_failures,
        "acceptance_failures": acceptance_failures,
        "recovery_reason_distribution_top10": recovery_reason_distribution,
        "generation_model": chosen_model,
    }
    write_json(audit_dir / "summary.json", summary_payload)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "set_manifest": {"path": rel_path(set_path, repo_root), "exists": False},
        "active_pointer": describe_file(active_pointer_path, repo_root) if active_pointer_path.exists() else {"path": rel_path(active_pointer_path, repo_root), "exists": False},
    }

    if not acceptance_failures:
        write_json(
            set_path,
            build_set_manifest(
                repo_root=repo_root,
                set_path=set_path,
                run_id_step6_3=run_id_step6_3,
                processed_dir=processed_dir,
                audit_dir=audit_dir,
                created_utc=created_utc,
                kc_registry_path=kc_registry_path,
                step5_2_pointer_path=step5_2_pointer_path,
                step5_2_set_path=step5_2_set_path,
                step4_set_path=step4_set_path,
                step5_2_manifest=step5_2_manifest,
            ),
        )
        write_text(active_pointer_path, set_path.name + "\n")
        output_manifest["set_manifest"] = describe_file(set_path, repo_root)
        output_manifest["active_pointer"] = describe_file(active_pointer_path, repo_root)
        logger.info(f"Wrote Step 6.3 set manifest: {rel_path(set_path, repo_root)}")
        logger.info(f"Updated ACTIVE pointer: {rel_path(active_pointer_path, repo_root)} -> {set_path.name}")

    timings["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    write_json(audit_dir / "timings.json", timings)
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(f"n_kcs_total: {len(records)}")
    print(f"n_kcs_tier1: {len(tier1_records)}")
    print(f"n_kcs_tier2: {len(tier2_records)}")
    print(f"n_kcs_usable: {len(tier1_records)}")
    print(f"n_kcs_in_recovery_queue: {len(recovery_rows)}")
    print(f"verified_quote_mismatch_count: {len(verified_quote_issues)}")
    print(f"median_evidence_minimal_size: {median_evidence_size:.2f}")
    if acceptance_failures:
        print("acceptance_passed: false")
        print("acceptance_failures:")
        for failure in acceptance_failures:
            print(f"- {failure}")
        print("failure_reason_distribution_top10:")
        for reason, count in recovery_reason_distribution.items():
            print(f"- {reason}: {count}")
        return 2

    print("acceptance_passed: true")
    print("kc_id | tier | kc_type | definition_short_nonempty | evidence_minimal_n | verified_quotes_n | in_recovery")
    for kc_id in sorted(sample_ids):
        record = next(item for item in records if str(item["kc_id"]) == kc_id)
        tier_info = tier_results[str(record["kc_id"])]
        verified_quotes = step6lib.verified_quote_count(record["evidence_minimal"])
        print(
            f"{kc_id} | {int(tier_info['tier'])} | {record['kc_type']} | {bool(str(record['definition_short']).strip())} | "
            f"{len(record['evidence_minimal'])} | {verified_quotes} | {record['recovery_state'] != 'none'}"
        )
    print("Reply DONE to continue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
