from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
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

from kc_l.audit.manifests import build_input_manifest, build_output_manifest, env_snapshot, pip_freeze, try_cmd_version
from kc_l.kc.validators import classify_tier, load_schema, schema_version, validate_kc_record


ACTIVE_STEP6_KC_LIBRARY_SET = Path("data/processed/kc_library/_sets/ACTIVE_STEP6_KC_LIBRARY_SET.txt")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
LAYER_PRIORITY = {"mineru": 3, "docling": 2, "pymupdf": 1}
MODEL_PREFERENCES = ["qwen3", "qwen2.5", "llama3.2", "llama3.1", "llama3", "mistral", "gemma", "phi4"]
FIELD_PRIORITY = [
    "definition_short",
    "definition_full",
    "scope_includes",
    "scope_excludes",
    "kc_type",
    "inputs_outputs",
    "procedure_steps",
    "formal_definition",
    "interpretation",
    "claim_statement",
    "assumptions",
    "misconception_statement",
    "canonical_correction",
    "worked_examples",
    "references",
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


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def rel_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def describe_file(path: Path, repo_root: Path) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"path": rel_path(path, repo_root), "exists": path.exists()}
    if path.exists() and path.is_file():
        stat = path.stat()
        payload["sha256"] = build_input_manifest([path])[0]["sha256"]
        payload["stat"] = {
            "size_bytes": int(stat.st_size),
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    return payload


def build_repo_input_manifest(paths: Sequence[Path], repo_root: Path) -> List[Dict[str, Any]]:
    return [describe_file(path, repo_root) for path in paths]


def ensure_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError("Expected list of strings.")
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RuntimeError("Expected list of strings.")
        item = item.strip()
        if item:
            out.append(item)
    return out


def unique_preserve_order(items: Sequence[Any]) -> List[Any]:
    seen: set[Any] = set()
    out: List[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalize_ws(text: str) -> str:
    return " ".join(str(text).split())


def match_normalize(text: str) -> str:
    return (
        normalize_ws(text)
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )


def tokenize(text: str) -> List[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(text) if len(tok) >= 3]


def resolve_pointer(repo_root: Path, pointer_path: Path) -> Path:
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
        audit_dir = (repo_root / runs_dir_rel / f"{run_id}_step6").resolve()
        set_path = (repo_root / sets_dir_rel / f"{run_id}_step6_kc_library_set.json").resolve()
        if not processed_dir.exists() and not audit_dir.exists() and not set_path.exists():
            return {
                "run_id_step6": Path(run_id),
                "processed_dir": processed_dir,
                "audit_dir": audit_dir,
                "set_path": set_path,
            }
        suffix += 1


@dataclass
class AuditLog:
    path: Path

    def info(self, message: str) -> None:
        line = f"[{now_utc_iso()}] {message}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line)


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


def is_generation_model_name(name: str) -> bool:
    lower = name.lower()
    return "embedding" not in lower and ":embed" not in lower and not lower.endswith("-embed")


def choose_generation_model(config_model: str, installed: Sequence[str]) -> str:
    generation_models = [name for name in installed if is_generation_model_name(name)]
    if config_model:
        if config_model in generation_models:
            return config_model
        matches = [name for name in generation_models if name.startswith(config_model)]
        if matches:
            return sorted(matches)[0]
        raise RuntimeError(
            f"Configured generation model '{config_model}' is not installed as a non-embedding model. Installed: {generation_models}"
        )

    for prefix in MODEL_PREFERENCES:
        matches = [name for name in generation_models if name.startswith(prefix)]
        if matches:
            return sorted(matches)[0]
    raise RuntimeError(f"No suitable instruct generation model found. Installed non-embedding models: {generation_models}")


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
    timeout_s: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    import urllib.request

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": format_schema,
        "options": {"temperature": temperature},
    }
    raw_payload = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=raw_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    outer = json.loads(raw)
    message = outer.get("message") or {}
    content = message.get("content", "")
    if isinstance(content, dict):
        return content, outer, raw
    parsed = json.loads(str(content))
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama chat response content was not a JSON object.")
    return parsed, outer, raw


def build_extraction_schema(allowed_kc_types: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "kc_type",
            "kc_type_evidence",
            "definition_short",
            "definition_full",
            "scope_includes",
            "scope_excludes",
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
        ],
        "properties": {
            "kc_type": {"type": "string", "enum": list(allowed_kc_types)},
            "kc_type_evidence": {"type": "array", "items": {"$ref": "#/$defs/Citation"}},
            "definition_short": {"$ref": "#/$defs/TextField"},
            "definition_full": {"$ref": "#/$defs/TextField"},
            "scope_includes": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "scope_excludes": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "inputs_outputs": {"$ref": "#/$defs/TextField"},
            "procedure_steps": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "parameters": {"type": "array", "items": {"$ref": "#/$defs/ParameterField"}},
            "termination_condition": {"$ref": "#/$defs/TextField"},
            "formal_definition": {"$ref": "#/$defs/TextField"},
            "interpretation": {"$ref": "#/$defs/TextField"},
            "when_to_use": {"$ref": "#/$defs/TextField"},
            "when_not_to_use": {"$ref": "#/$defs/TextField"},
            "claim_statement": {"$ref": "#/$defs/TextField"},
            "assumptions": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "misconception_statement": {"$ref": "#/$defs/TextField"},
            "canonical_correction": {"$ref": "#/$defs/TextField"},
            "diagnostic_cues": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "remediation_suggestions": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "worked_examples": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
            "references": {"type": "array", "items": {"$ref": "#/$defs/TextField"}},
        },
        "$defs": {
            "Citation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["block_id", "quote", "role"],
                "properties": {
                    "block_id": {"type": "string", "minLength": 1},
                    "quote": {"type": "string", "minLength": 1},
                    "role": {
                        "type": "string",
                        "enum": ["definition", "scope", "procedure", "equation", "example", "warning", "other"],
                    },
                },
            },
            "TextField": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence"],
                "properties": {
                    "text": {"type": "string"},
                    "evidence": {"type": "array", "items": {"$ref": "#/$defs/Citation"}},
                },
            },
            "ParameterField": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "evidence"],
                "properties": {
                    "name": {"type": "string"},
                    "meaning": {"type": "string"},
                    "constraints": {"type": "string"},
                    "evidence": {"type": "array", "items": {"$ref": "#/$defs/Citation"}},
                },
            },
        },
    }


def empty_text_field() -> Dict[str, Any]:
    return {"text": "", "evidence": []}


def empty_extraction_payload(default_kc_type: str) -> Dict[str, Any]:
    return {
        "kc_type": default_kc_type,
        "kc_type_evidence": [],
        "definition_short": empty_text_field(),
        "definition_full": empty_text_field(),
        "scope_includes": [],
        "scope_excludes": [],
        "inputs_outputs": empty_text_field(),
        "procedure_steps": [],
        "parameters": [],
        "termination_condition": empty_text_field(),
        "formal_definition": empty_text_field(),
        "interpretation": empty_text_field(),
        "when_to_use": empty_text_field(),
        "when_not_to_use": empty_text_field(),
        "claim_statement": empty_text_field(),
        "assumptions": [],
        "misconception_statement": empty_text_field(),
        "canonical_correction": empty_text_field(),
        "diagnostic_cues": [],
        "remediation_suggestions": [],
        "worked_examples": [],
        "references": [],
    }


def validate_extraction_payload(payload: Mapping[str, Any], allowed_kc_types: Sequence[str]) -> List[str]:
    errors: List[str] = []
    required = list(empty_extraction_payload("concept").keys())
    for key in required:
        if key not in payload:
            errors.append(f"{key}: missing")
    kc_type = payload.get("kc_type")
    if kc_type not in allowed_kc_types:
        errors.append("kc_type: invalid")

    def check_text_field(key: str) -> None:
        value = payload.get(key)
        if not isinstance(value, Mapping):
            errors.append(f"{key}: expected object")
            return
        if not isinstance(value.get("text"), str):
            errors.append(f"{key}.text: expected string")
        if not isinstance(value.get("evidence"), list):
            errors.append(f"{key}.evidence: expected list")

    def check_text_field_list(key: str) -> None:
        value = payload.get(key)
        if not isinstance(value, list):
            errors.append(f"{key}: expected list")
            return
        for idx, item in enumerate(value):
            if not isinstance(item, Mapping):
                errors.append(f"{key}[{idx}]: expected object")
                continue
            if not isinstance(item.get("text"), str):
                errors.append(f"{key}[{idx}].text: expected string")
            if not isinstance(item.get("evidence"), list):
                errors.append(f"{key}[{idx}].evidence: expected list")

    check_text_field("definition_short")
    check_text_field("definition_full")
    check_text_field("inputs_outputs")
    check_text_field("termination_condition")
    check_text_field("formal_definition")
    check_text_field("interpretation")
    check_text_field("when_to_use")
    check_text_field("when_not_to_use")
    check_text_field("claim_statement")
    check_text_field("misconception_statement")
    check_text_field("canonical_correction")
    check_text_field_list("scope_includes")
    check_text_field_list("scope_excludes")
    check_text_field_list("procedure_steps")
    check_text_field_list("assumptions")
    check_text_field_list("diagnostic_cues")
    check_text_field_list("remediation_suggestions")
    check_text_field_list("worked_examples")
    check_text_field_list("references")

    if not isinstance(payload.get("kc_type_evidence"), list):
        errors.append("kc_type_evidence: expected list")
    parameters = payload.get("parameters")
    if not isinstance(parameters, list):
        errors.append("parameters: expected list")
    else:
        for idx, item in enumerate(parameters):
            if not isinstance(item, Mapping):
                errors.append(f"parameters[{idx}]: expected object")
                continue
            if not isinstance(item.get("name"), str):
                errors.append(f"parameters[{idx}].name: expected string")
            if not isinstance(item.get("evidence"), list):
                errors.append(f"parameters[{idx}].evidence: expected list")
    return errors


def extract_rule_quote(text: str, cue: str, max_chars: int) -> str:
    match = re.search(re.escape(cue), text, flags=re.IGNORECASE)
    if not match:
        return text[:max_chars]
    return text[match.start() : match.end()][:max_chars]


def rules_based_kc_type(selected_blocks: Sequence[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, str]]]:
    patterns = {
        "procedure": ["algorithm", "procedure", "input:", "output:", "repeat", "return", "invoke", "for each"],
        "metric": ["coefficient", "measure", "metric", "index", "score", "accuracy", "precision", "recall", "purity"],
        "theorem_or_claim": ["theorem", "lemma", "proposition", "claim", "corollary"],
        "misconception_cluster": ["misconception", "mistake", "pitfall", "confuse", "confusion", "wrong"],
    }
    scores: Counter[str] = Counter()
    citations: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    for block in selected_blocks:
        text = str(block.get("source_text") or "")
        lower = text.lower()
        for kc_type, cues in patterns.items():
            for cue in cues:
                if cue in lower:
                    scores[kc_type] += 1
                    role = "procedure" if kc_type == "procedure" else "equation" if kc_type == "metric" else "warning" if kc_type == "misconception_cluster" else "other"
                    citations[kc_type].append(
                        {"block_id": str(block["block_id"]), "quote": extract_rule_quote(text, cue, 80), "role": role}
                    )
                    break

    if not scores:
        return None, []
    ordered = scores.most_common()
    best_type, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0
    if best_score >= 2 and best_score >= second_score + 1:
        return best_type, citations[best_type][:2]
    return None, []


def extraction_prompt(
    *,
    kc_row: Mapping[str, Any],
    selected_blocks: Sequence[Dict[str, Any]],
    forced_type: Optional[str],
    quote_max_chars: int,
    definition_max_chars: int,
    definition_full_max_chars: int,
    allowed_kc_types: Sequence[str],
) -> Tuple[str, str]:
    system_prompt = (
        "You extract grounded knowledge component records from source blocks. "
        "Use only the provided source blocks. Never use prior knowledge. "
        "If a field is not supported by the source blocks, return an empty string or an empty list. "
        "Every evidence quote must be copied exactly from a single source block. "
        "Do not emit markdown. Return JSON only."
    )
    block_payload = []
    for block in selected_blocks:
        block_payload.append(
            {
                "doc_id": block["doc_id"],
                "block_id": block["block_id"],
                "page_index": block["page_index"],
                "layer": block["layer"],
                "patch_heading": block.get("patch_heading") or "",
                "text": block.get("source_text") or "",
            }
        )
    user_payload = {
        "task": "Extract grounded KC content.",
        "instructions": {
            "allowed_kc_types": list(allowed_kc_types),
            "forced_kc_type": forced_type or "",
            "definition_short_max_chars": definition_max_chars,
            "definition_full_max_chars": definition_full_max_chars,
            "quote_max_chars": quote_max_chars,
            "rules": [
                "Only use facts supported by the provided source blocks.",
                "Copy evidence quotes exactly from one source block.",
                "If a type-specific field is unsupported, leave it empty.",
                "Do not use the seed definition unless it is supported by a source block.",
                "Prefer concise, UI-ready plain language.",
            ],
        },
        "kc": {
            "kc_id": kc_row["kc_id"],
            "kc_path": kc_row["kc_path"],
            "canonical_name": kc_row["canonical_name"],
            "aliases": kc_row["aliases"],
            "seed_definition": kc_row["seed_definition"],
        },
        "evidence_blocks": block_payload,
    }
    return system_prompt, json.dumps(user_payload, ensure_ascii=False)


def selection_terms(kc_row: Mapping[str, Any]) -> Dict[str, Any]:
    canonical_name = normalize_ws(str(kc_row.get("canonical_name") or ""))
    aliases = [normalize_ws(a) for a in ensure_string_list(kc_row.get("aliases"))]
    seed_definition = normalize_ws(str(kc_row.get("seed_definition") or ""))
    canonical_norm = match_normalize(canonical_name)
    alias_norms = [match_normalize(alias) for alias in aliases]
    canonical_tokens = set(tokenize(canonical_norm))
    alias_tokens = set(token for alias in alias_norms for token in tokenize(alias))
    seed_tokens = set(tokenize(match_normalize(seed_definition))) - canonical_tokens - alias_tokens
    return {
        "canonical_name": canonical_name,
        "canonical_norm": canonical_norm,
        "aliases": aliases,
        "alias_norms": alias_norms,
        "canonical_tokens": canonical_tokens,
        "alias_tokens": alias_tokens,
        "seed_tokens": set(list(seed_tokens)[:24]),
    }


def prepare_candidates(
    kc_row: Mapping[str, Any],
    evidence_list: Sequence[Mapping[str, Any]],
    source_lookup: Mapping[str, Mapping[str, Any]],
    max_considered: int,
    selected_count: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    terms = selection_terms(kc_row)
    top_evidence = list(evidence_list[:max_considered])
    deduped: List[Dict[str, Any]] = []
    seen_keys: set[Tuple[str, str]] = set()
    for index, raw in enumerate(top_evidence):
        key = (str(raw.get("doc_id") or ""), str(raw.get("block_id") or ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        source_row = source_lookup.get(key[1])
        if not source_row:
            warnings.append(f"MissingSourceBlock:{key[1]}")
            continue
        source_text = normalize_ws(str(source_row.get("text") or ""))
        if not source_text:
            warnings.append(f"EmptySourceText:{key[1]}")
            continue
        match_text = match_normalize(source_text)
        token_set = set(tokenize(match_text))
        canonical_token_hits = sum(1 for token in terms["canonical_tokens"] if token in token_set)
        alias_token_hits = sum(1 for token in terms["alias_tokens"] if token in token_set)
        seed_token_hits = sum(1 for token in terms["seed_tokens"] if token in token_set)
        exact_name_hit = bool(terms["canonical_norm"] and terms["canonical_norm"] in match_text)
        alias_phrase_hit = any(alias and alias in match_text for alias in terms["alias_norms"])
        score = float(((raw.get("scores") or {}).get("combined")) or 0.0)
        score_band = int(round(score / 0.02))
        layer = str(raw.get("layer") or source_row.get("layer") or "")
        candidate = {
            "doc_id": str(raw.get("doc_id") or source_row.get("doc_id") or ""),
            "block_id": str(raw.get("block_id") or ""),
            "page_index": int(raw.get("page_index") if raw.get("page_index") is not None else source_row.get("page_index", -1)),
            "bbox": raw.get("bbox"),
            "layer": layer,
            "patch_heading": str(raw.get("patch_heading") or ""),
            "scores": {"combined": score},
            "source_text": source_text,
            "is_noncanonical_reveal_page": bool(source_row.get("is_noncanonical_reveal_page", False)),
            "selection_key": (
                -int(exact_name_hit),
                -int(alias_phrase_hit),
                -int(canonical_token_hits),
                -int(alias_token_hits),
                -int(seed_token_hits),
                -score_band,
                int(bool(source_row.get("is_noncanonical_reveal_page", False))),
                -LAYER_PRIORITY.get(layer.lower(), 0),
                -score,
                int(raw.get("page_index", -1)),
                str(raw.get("block_id") or ""),
                index,
            ),
        }
        deduped.append(candidate)

    deduped.sort(key=lambda item: item["selection_key"])
    pages: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for item in deduped:
        pages[(item["doc_id"], int(item["page_index"]))].append(item)

    page_keys = sorted(pages.keys(), key=lambda key: pages[key][0]["selection_key"])
    selected: List[Dict[str, Any]] = []
    selected_ids: set[str] = set()
    while len(selected) < selected_count:
        added = False
        for page_key in page_keys:
            while pages[page_key] and pages[page_key][0]["block_id"] in selected_ids:
                pages[page_key].pop(0)
            if not pages[page_key]:
                continue
            candidate = pages[page_key].pop(0)
            if candidate["block_id"] in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate["block_id"])
            added = True
            if len(selected) >= selected_count:
                break
        if not added:
            break
    return selected, deduped, warnings


def convert_citations(
    citations: Sequence[Mapping[str, Any]],
    candidate_map: Mapping[str, Mapping[str, Any]],
    quote_max_chars: int,
    extraction_method: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    evidence_items: List[Dict[str, Any]] = []
    issues: List[str] = []
    seen: set[Tuple[str, str, str]] = set()
    for citation in citations:
        block_id = str(citation.get("block_id") or "")
        quote = str(citation.get("quote") or "")
        role = str(citation.get("role") or "")
        if not block_id or not quote or not role:
            issues.append("MalformedCitation")
            continue
        candidate = candidate_map.get(block_id)
        if not candidate:
            issues.append(f"CitationBlockNotSelected:{block_id}")
            continue
        if len(quote) > quote_max_chars:
            issues.append(f"QuoteTooLong:{block_id}")
            continue
        source_text = str(candidate.get("source_text") or "")
        if quote not in source_text:
            issues.append(f"QuoteNotVerifiable:{block_id}")
            continue
        key = (block_id, quote, role)
        if key in seen:
            continue
        seen.add(key)
        evidence_items.append(
            {
                "doc_id": candidate["doc_id"],
                "block_id": block_id,
                "page_index": int(candidate["page_index"]),
                "layer": candidate["layer"],
                "bbox": candidate.get("bbox"),
                "role": role,
                "quote": quote,
                "extraction_method": extraction_method,
                "quote_verified": True,
                "provenance_quality_flags": [],
            }
        )
    return evidence_items, issues


def convert_text_field(
    *,
    field_name: str,
    payload_value: Mapping[str, Any],
    candidate_map: Mapping[str, Mapping[str, Any]],
    quote_max_chars: int,
    extraction_method: str,
    quality_flags: List[str],
    recovery_reasons: List[str],
) -> Tuple[str, List[Dict[str, Any]]]:
    text = normalize_ws(str(payload_value.get("text") or ""))
    citations = payload_value.get("evidence") or []
    evidence_items, issues = convert_citations(citations, candidate_map, quote_max_chars, extraction_method)
    for issue in issues:
        quality_flags.append(f"{field_name}:{issue}")
    if text and not evidence_items:
        recovery_reasons.append(f"{field_name}:NoVerifiedEvidence")
        return "", []
    return text, evidence_items


def convert_text_field_list(
    *,
    field_name: str,
    payload_items: Sequence[Mapping[str, Any]],
    candidate_map: Mapping[str, Mapping[str, Any]],
    quote_max_chars: int,
    extraction_method: str,
    quality_flags: List[str],
    recovery_reasons: List[str],
) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    texts: List[str] = []
    aggregated_evidence: List[Dict[str, Any]] = []
    detailed: List[Dict[str, Any]] = []
    for item in payload_items:
        text, evidence_items = convert_text_field(
            field_name=field_name,
            payload_value=item,
            candidate_map=candidate_map,
            quote_max_chars=quote_max_chars,
            extraction_method=extraction_method,
            quality_flags=quality_flags,
            recovery_reasons=recovery_reasons,
        )
        if not text:
            continue
        texts.append(text)
        aggregated_evidence.extend(evidence_items)
        detailed.append({"text": text, "evidence": evidence_items})
    return texts, aggregated_evidence, detailed


def convert_parameter_list(
    payload_items: Sequence[Mapping[str, Any]],
    candidate_map: Mapping[str, Mapping[str, Any]],
    quote_max_chars: int,
    extraction_method: str,
    quality_flags: List[str],
    recovery_reasons: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    parameters: List[Dict[str, Any]] = []
    aggregated_evidence: List[Dict[str, Any]] = []
    for idx, item in enumerate(payload_items):
        name = normalize_ws(str(item.get("name") or ""))
        if not name:
            quality_flags.append(f"parameters[{idx}]:MissingName")
            continue
        evidence_items, issues = convert_citations(item.get("evidence") or [], candidate_map, quote_max_chars, extraction_method)
        for issue in issues:
            quality_flags.append(f"parameters[{idx}]:{issue}")
        if not evidence_items:
            recovery_reasons.append(f"parameters[{idx}]:NoVerifiedEvidence")
            continue
        parameter = {
            "name": name,
            "meaning": normalize_ws(str(item.get("meaning") or "")),
            "constraints": normalize_ws(str(item.get("constraints") or "")),
            "evidence": evidence_items,
        }
        parameters.append(parameter)
        aggregated_evidence.extend(evidence_items)
    return parameters, aggregated_evidence


def dedupe_evidence(evidence_items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for item in evidence_items:
        key = (str(item.get("block_id")), str(item.get("quote")), str(item.get("role")))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return out


def select_evidence_minimal(field_evidence_map: Mapping[str, Sequence[Mapping[str, Any]]], max_items: int) -> List[Dict[str, Any]]:
    ordered: List[Dict[str, Any]] = []
    for field_name in FIELD_PRIORITY:
        for evidence in field_evidence_map.get(field_name, []):
            ordered.append(dict(evidence))
    ordered = dedupe_evidence(ordered)
    grouped: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for evidence in ordered:
        grouped[(str(evidence["doc_id"]), int(evidence["page_index"]))].append(evidence)
    page_keys = sorted(grouped.keys(), key=lambda key: (key[0], key[1], grouped[key][0]["block_id"]))
    selected: List[Dict[str, Any]] = []
    while len(selected) < max_items:
        added = False
        for page_key in page_keys:
            if not grouped[page_key]:
                continue
            selected.append(grouped[page_key].pop(0))
            added = True
            if len(selected) >= max_items:
                break
        if not added:
            break
    return selected


def verified_quote_count(evidence_items: Any) -> int:
    if not isinstance(evidence_items, list):
        return 0
    return sum(1 for item in evidence_items if isinstance(item, Mapping) and item.get("quote_verified") is True)


def apply_tier_classification(record: Dict[str, Any]) -> Dict[str, Any]:
    support_gaps = list(record.get("recovery_reasons") or [])
    tier_info = classify_tier(record)

    record["quality_flags"].extend(support_gaps)
    record["quality_flags"].extend(tier_info["flags"])
    record["quality_flags"].extend(tier_info["reasons"])
    record["quality_flags"].append(f"UsabilityTier:{tier_info['tier']}")

    if int(tier_info["tier"]) >= 1:
        record["recovery_state"] = "none"
        record["recovery_reasons"] = []
    else:
        record["recovery_reasons"] = support_gaps + [str(reason) for reason in tier_info["reasons"]]
        record["recovery_state"] = "manual_required" if not record.get("evidence_minimal") else "needs_recovery"

    record["quality_flags"] = unique_preserve_order(record["quality_flags"])
    record["recovery_reasons"] = unique_preserve_order(record["recovery_reasons"])
    return {"tier": int(tier_info["tier"]), "reasons": list(tier_info["reasons"]), "flags": list(tier_info["flags"])}


def iter_record_evidence(record: Mapping[str, Any]) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    seen: set[Tuple[str, str, str]] = set()

    evidence_minimal = record.get("evidence_minimal")
    if isinstance(evidence_minimal, list):
        for idx, item in enumerate(evidence_minimal):
            if not isinstance(item, Mapping):
                continue
            key = (str(item.get("block_id") or ""), str(item.get("quote") or ""), str(item.get("role") or ""))
            if key in seen:
                continue
            seen.add(key)
            yield f"evidence_minimal[{idx}]", item

    field_map = record.get("field_evidence_map")
    if isinstance(field_map, Mapping):
        for field_name, values in field_map.items():
            if not isinstance(values, list):
                continue
            for idx, item in enumerate(values):
                if not isinstance(item, Mapping):
                    continue
                key = (str(item.get("block_id") or ""), str(item.get("quote") or ""), str(item.get("role") or ""))
                if key in seen:
                    continue
                seen.add(key)
                yield f"field_evidence_map.{field_name}[{idx}]", item


def find_verified_quote_mismatches(
    record: Mapping[str, Any],
    source_lookup: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    issues: List[str] = []
    kc_id = str(record.get("kc_id") or "")
    for location, evidence in iter_record_evidence(record):
        if evidence.get("quote_verified") is not True:
            continue
        block_id = str(evidence.get("block_id") or "")
        quote = str(evidence.get("quote") or "")
        source_row = source_lookup.get(block_id)
        if not source_row:
            issues.append(f"{kc_id}:{location}:MissingSourceBlock:{block_id}")
            continue
        source_text = normalize_ws(str(source_row.get("text") or ""))
        if not source_text:
            issues.append(f"{kc_id}:{location}:EmptySourceText:{block_id}")
            continue
        if quote not in source_text:
            issues.append(f"{kc_id}:{location}:QuoteNotVerifiable:{block_id}")
    return issues


def default_record_shell(
    *,
    kc_row: Mapping[str, Any],
    step4_set_id: str,
    step5_set_id: str,
    run_id_step6: str,
    created_utc: str,
    schema_ver: str,
) -> Dict[str, Any]:
    kc_path = kc_row.get("kc_path")
    if isinstance(kc_path, list):
        path_value = [str(part) for part in kc_path]
    else:
        path_value = [normalize_ws(str(kc_path or ""))] if str(kc_path or "").strip() else []
    return {
        "kc_id": str(kc_row["kc_id"]),
        "kc_path": path_value,
        "canonical_name": str(kc_row["canonical_name"]),
        "aliases": [str(alias) for alias in ensure_string_list(kc_row.get("aliases"))],
        "seed_definition": str(kc_row.get("seed_definition") or ""),
        "kc_type": "concept",
        "definition_short": "",
        "definition_full": "",
        "scope_includes": [],
        "scope_excludes": [],
        "evidence_minimal": [],
        "field_evidence_map": {},
        "kc_specific_criteria": "",
        "source_set_ids": {"step4_set_id": step4_set_id, "step5_set_id": step5_set_id},
        "record_meta": {"created_utc": created_utc, "run_id_step6": run_id_step6, "schema_version": schema_ver},
        "quality_flags": [],
        "recovery_state": "needs_recovery",
        "recovery_reasons": [],
        "inputs_outputs": "",
        "procedure_steps": [],
        "parameters": [],
        "termination_condition": "",
        "formal_definition": "",
        "interpretation": "",
        "when_to_use": "",
        "when_not_to_use": "",
        "claim_statement": "",
        "assumptions": [],
        "misconception_statement": "",
        "canonical_correction": "",
        "diagnostic_cues": [],
        "remediation_suggestions": [],
        "worked_examples": [],
        "references": [],
    }


def set_type_and_evidence(
    record: Dict[str, Any],
    *,
    payload: Mapping[str, Any],
    forced_type: Optional[str],
    forced_type_citations: Sequence[Mapping[str, Any]],
    candidate_map: Mapping[str, Mapping[str, Any]],
    quote_max_chars: int,
    extraction_method: str,
) -> None:
    if forced_type:
        record["kc_type"] = forced_type
        evidence_items, issues = convert_citations(forced_type_citations, candidate_map, quote_max_chars, "rules:kctype")
        if evidence_items:
            record["field_evidence_map"]["kc_type"] = evidence_items
        for issue in issues:
            record["quality_flags"].append(f"kc_type:{issue}")
        model_type = str(payload.get("kc_type") or "")
        if model_type and model_type != forced_type:
            record["quality_flags"].append("ModelTypeOverriddenByRules")
        return

    model_type = str(payload.get("kc_type") or "").strip()
    if model_type not in {"concept", "procedure", "metric", "theorem_or_claim", "misconception_cluster"}:
        model_type = "concept"
        record["quality_flags"].append("TypeInvalidDefaultedToConcept")
    record["kc_type"] = model_type
    evidence_items, issues = convert_citations(payload.get("kc_type_evidence") or [], candidate_map, quote_max_chars, extraction_method)
    if evidence_items:
        record["field_evidence_map"]["kc_type"] = evidence_items
    else:
        record["quality_flags"].append("TypeUncertain")
    for issue in issues:
        record["quality_flags"].append(f"kc_type:{issue}")


def build_record_from_payload(
    *,
    record: Dict[str, Any],
    payload: Mapping[str, Any],
    selected_blocks: Sequence[Dict[str, Any]],
    forced_type: Optional[str],
    forced_type_citations: Sequence[Mapping[str, Any]],
    quote_max_chars: int,
    evidence_minimal_max: int,
) -> Dict[str, Any]:
    candidate_map = {str(block["block_id"]): block for block in selected_blocks}
    extraction_method = "ollama_chat:step6"

    set_type_and_evidence(
        record,
        payload=payload,
        forced_type=forced_type,
        forced_type_citations=forced_type_citations,
        candidate_map=candidate_map,
        quote_max_chars=quote_max_chars,
        extraction_method=extraction_method,
    )

    text_fields = [
        "definition_short",
        "definition_full",
        "inputs_outputs",
        "termination_condition",
        "formal_definition",
        "interpretation",
        "when_to_use",
        "when_not_to_use",
        "claim_statement",
        "misconception_statement",
        "canonical_correction",
    ]
    for field_name in text_fields:
        text, evidence_items = convert_text_field(
            field_name=field_name,
            payload_value=payload.get(field_name) or empty_text_field(),
            candidate_map=candidate_map,
            quote_max_chars=quote_max_chars,
            extraction_method=extraction_method,
            quality_flags=record["quality_flags"],
            recovery_reasons=record["recovery_reasons"],
        )
        record[field_name] = text
        if evidence_items:
            record["field_evidence_map"][field_name] = evidence_items

    list_fields = [
        "scope_includes",
        "scope_excludes",
        "procedure_steps",
        "diagnostic_cues",
        "remediation_suggestions",
    ]
    for field_name in list_fields:
        texts, evidence_items, _ = convert_text_field_list(
            field_name=field_name,
            payload_items=payload.get(field_name) or [],
            candidate_map=candidate_map,
            quote_max_chars=quote_max_chars,
            extraction_method=extraction_method,
            quality_flags=record["quality_flags"],
            recovery_reasons=record["recovery_reasons"],
        )
        record[field_name] = texts
        if evidence_items:
            record["field_evidence_map"][field_name] = dedupe_evidence(evidence_items)

    parameters, parameter_evidence = convert_parameter_list(
        payload.get("parameters") or [],
        candidate_map=candidate_map,
        quote_max_chars=quote_max_chars,
        extraction_method=extraction_method,
        quality_flags=record["quality_flags"],
        recovery_reasons=record["recovery_reasons"],
    )
    record["parameters"] = parameters
    if parameter_evidence:
        record["field_evidence_map"]["parameters"] = dedupe_evidence(parameter_evidence)

    for field_name in ["assumptions", "worked_examples", "references"]:
        _, evidence_items, detailed = convert_text_field_list(
            field_name=field_name,
            payload_items=payload.get(field_name) or [],
            candidate_map=candidate_map,
            quote_max_chars=quote_max_chars,
            extraction_method=extraction_method,
            quality_flags=record["quality_flags"],
            recovery_reasons=record["recovery_reasons"],
        )
        record[field_name] = detailed
        if evidence_items:
            record["field_evidence_map"][field_name] = dedupe_evidence(evidence_items)

    record["evidence_minimal"] = select_evidence_minimal(record["field_evidence_map"], evidence_minimal_max)
    record["quality_flags"] = unique_preserve_order(record["quality_flags"])
    record["recovery_reasons"] = unique_preserve_order(record["recovery_reasons"])

    apply_tier_classification(record)
    return record


def build_set_manifest(
    *,
    repo_root: Path,
    set_path: Path,
    run_id_step6: str,
    processed_dir: Path,
    audit_dir: Path,
    created_utc: str,
    kc_registry_path: Path,
    step5_pointer_path: Path,
    step5_set_path: Path,
    step4_set_path: Path,
    step5_manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    artifacts = {
        "kc_library_jsonl": rel_path((processed_dir / "kc_library.jsonl").resolve(), repo_root),
        "kc_library_stats_json": rel_path((processed_dir / "kc_library_stats.json").resolve(), repo_root),
        "recovery_queue_jsonl": rel_path((processed_dir / "recovery_queue.jsonl").resolve(), repo_root),
        "extraction_traces_dir": rel_path((processed_dir / "extraction_traces").resolve(), repo_root),
    }
    step5_outputs = []
    for name, rel in (step5_manifest.get("artifacts") or {}).items():
        path = (repo_root / str(rel)).resolve()
        step5_outputs.append({"name": name, **describe_file(path, repo_root)})

    return {
        "schema_version": "1.0",
        "kind": "step6_kc_library_set",
        "set_id": set_path.stem,
        "created_utc": created_utc,
        "run_id_step6": run_id_step6,
        "artifacts": artifacts,
        "upstream": {
            "kc_registry": describe_file(kc_registry_path, repo_root),
            "step5_active_set_pointer": describe_file(step5_pointer_path, repo_root),
            "step5_active_set_target": describe_file(step5_set_path, repo_root),
            "step4_set_target": describe_file(step4_set_path, repo_root),
            "step5_processed_outputs": step5_outputs,
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
    parser = argparse.ArgumentParser(description="STEP 6: Evidence-grounded KC library extraction.")
    parser.add_argument("--config", required=True, help="Repo-relative YAML config path.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    cfg = load_yaml(config_path)

    inputs_cfg = cfg["inputs"]
    extraction_cfg = cfg["extraction"]
    outputs_cfg = cfg["outputs"]
    audit_cfg = cfg["audit"]
    runtime_cfg = cfg.get("runtime", {})

    schema_path = (repo_root / str(inputs_cfg["schema_path"])).resolve()
    kc_registry_path = (repo_root / str(inputs_cfg["kc_registry_path"])).resolve()
    step5_pointer_path = (repo_root / str(inputs_cfg["step5_active_set_pointer"])).resolve()
    active_pointer_path = (repo_root / ACTIVE_STEP6_KC_LIBRARY_SET).resolve()

    step5_set_path = resolve_pointer(repo_root, step5_pointer_path)
    step5_manifest = load_json(step5_set_path)
    if str(step5_manifest.get("run_id_step5")) != "2026-03-06_015121":
        raise RuntimeError(f"Active Step 5 set is not the accepted run: {step5_manifest.get('run_id_step5')}")
    candidates_path = (repo_root / str(step5_manifest["artifacts"]["kc_evidence_candidates_jsonl"])).resolve()
    step4_set_path = (repo_root / str(step5_manifest["upstream"]["step4_active_set_target"])).resolve()
    step4_manifest = load_json(step4_set_path)

    evidence_target = int(extraction_cfg["evidence_minimal_target"])
    evidence_max = int(extraction_cfg["evidence_minimal_max"])
    if evidence_target <= 0 or evidence_max <= 0 or evidence_target > evidence_max:
        raise RuntimeError("Invalid evidence_minimal_target/evidence_minimal_max configuration.")

    installed_models = list_ollama_models()
    chosen_model = choose_generation_model(str(extraction_cfg.get("model") or "").strip(), installed_models)

    run_paths = choose_run_paths(
        repo_root=repo_root,
        processed_root_rel=str(outputs_cfg["processed_root"]),
        runs_dir_rel=str(audit_cfg["runs_dir"]),
        sets_dir_rel=str(outputs_cfg["sets_dir"]),
    )
    run_id_step6 = run_paths["run_id_step6"].name
    processed_dir = run_paths["processed_dir"]
    audit_dir = run_paths["audit_dir"]
    set_path = run_paths["set_path"]
    created_utc = now_utc_iso()

    audit_dir.mkdir(parents=True, exist_ok=False)
    processed_dir.mkdir(parents=True, exist_ok=False)
    logger = AuditLog(audit_dir / "logs" / "run.log")
    logger.info(f"Step 6 starting with generation model {chosen_model}")

    started = time.perf_counter()
    timings: Dict[str, Any] = {"started_utc": created_utc}
    write_text(audit_dir / "config.snapshot.yaml", read_text(config_path))
    write_json(
        audit_dir / "invocation.json",
        {"argv": sys.argv, "cwd": ".", "config": rel_path(config_path, repo_root), "run_id_step6": run_id_step6},
    )
    write_json(audit_dir / "env_snapshot.json", {"snapshot": env_snapshot(), "pip_freeze": pip_freeze()})
    write_json(
        audit_dir / "tool_versions.json",
        {
            "python": sys.version,
            "pyyaml_available": yaml is not None,
            "ollama_cli": try_cmd_version(["ollama", "--version"]),
            "ollama_http_version": ollama_http_version(str(extraction_cfg["ollama_base_url"])),
            "generation_model": chosen_model,
            "installed_models": installed_models,
        },
    )

    load_started = time.perf_counter()
    schema = load_schema(schema_path)
    schema_ver = schema_version(schema)
    registry_rows = list(jsonl_iter(kc_registry_path))
    if not registry_rows:
        raise RuntimeError("KC registry is empty.")
    candidate_rows = list(jsonl_iter(candidates_path))
    candidate_by_kc = {str(row["kc_id"]): row for row in candidate_rows}
    if len(candidate_by_kc) != len(registry_rows):
        raise RuntimeError(
            f"KC registry count and Step 5 candidates count differ: registry={len(registry_rows)} step5={len(candidate_by_kc)}"
        )

    source_lookup: Dict[str, Dict[str, Any]] = {}
    input_paths = [schema_path, kc_registry_path, step5_pointer_path, step5_set_path, step4_set_path, candidates_path]
    for doc_payload in (step4_manifest.get("docs") or {}).values():
        corpus_rel = ((doc_payload.get("artifacts") or {}).get("block_text_corpus.jsonl") or {}).get("path")
        if not corpus_rel:
            continue
        corpus_path = (repo_root / str(corpus_rel)).resolve()
        input_paths.append(corpus_path)
        for row in jsonl_iter(corpus_path):
            source_lookup[str(row["block_id"])] = row
    write_json(audit_dir / "input_manifest.json", build_repo_input_manifest(input_paths, repo_root))
    timings["load_seconds"] = round(time.perf_counter() - load_started, 3)

    sample_ids = sample_kc_ids(registry_rows, int(runtime_cfg.get("sample_kcs", 10)))
    extraction_schema = build_extraction_schema(ensure_string_list(extraction_cfg["allowed_kc_types"]))
    records: List[Dict[str, Any]] = []
    recovery_rows: List[Dict[str, Any]] = []
    trace_dir = processed_dir / "extraction_traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    registry_by_order = [str(row["kc_id"]) for row in registry_rows]

    extraction_started = time.perf_counter()
    for row in registry_rows:
        kc_id = str(row["kc_id"])
        step5_row = candidate_by_kc.get(kc_id)
        if step5_row is None:
            raise RuntimeError(f"Missing Step 5 candidate row for {kc_id}")

        record = default_record_shell(
            kc_row=row,
            step4_set_id=str(step4_manifest.get("set_id") or ""),
            step5_set_id=str(step5_manifest.get("set_id") or ""),
            run_id_step6=run_id_step6,
            created_utc=created_utc,
            schema_ver=schema_ver,
        )

        selected_blocks, considered_blocks, selection_warnings = prepare_candidates(
            row,
            step5_row.get("evidence") or [],
            source_lookup,
            max_considered=int(extraction_cfg["max_evidence_blocks_considered_per_kc"]),
            selected_count=evidence_target,
        )
        for warning in selection_warnings:
            record["quality_flags"].append(warning)

        rule_type, rule_citations = rules_based_kc_type(selected_blocks)
        prompt_system, prompt_user = extraction_prompt(
            kc_row=row,
            selected_blocks=selected_blocks,
            forced_type=rule_type,
            quote_max_chars=int(extraction_cfg["quote_max_chars"]),
            definition_max_chars=int(extraction_cfg["definition_max_chars"]),
            definition_full_max_chars=int(extraction_cfg["definition_full_max_chars"]),
            allowed_kc_types=ensure_string_list(extraction_cfg["allowed_kc_types"]),
        )

        payload = empty_extraction_payload(rule_type or "concept")
        raw_outer: Dict[str, Any] = {}
        raw_response = ""
        model_errors: List[str] = []
        if selected_blocks:
            messages = [{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}]
            for attempt in range(3):
                try:
                    payload_candidate, outer, raw = ollama_chat_json(
                        base_url=str(extraction_cfg["ollama_base_url"]),
                        model=chosen_model,
                        messages=messages,
                        format_schema=extraction_schema,
                        temperature=float(extraction_cfg.get("temperature", 0)),
                        timeout_s=float(extraction_cfg.get("timeout_seconds", 180)),
                    )
                    validation_errors = validate_extraction_payload(
                        payload_candidate, ensure_string_list(extraction_cfg["allowed_kc_types"])
                    )
                    if validation_errors:
                        model_errors.append(f"Attempt{attempt + 1}:InvalidPayload:{';'.join(validation_errors[:6])}")
                        messages.append(
                            {
                                "role": "user",
                                "content": f"The previous JSON failed validation: {validation_errors[:6]}. Return corrected JSON only.",
                            }
                        )
                        continue
                    payload = payload_candidate
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
                record["quality_flags"].append("ModelExtractionFailed")
                record["recovery_reasons"].append("ModelExtractionFailed")
        else:
            record["quality_flags"].append("NoSelectedEvidenceBlocks")
            record["recovery_reasons"].append("NoSelectedEvidenceBlocks")

        for error in model_errors:
            record["quality_flags"].append(error)

        record = build_record_from_payload(
            record=record,
            payload=payload,
            selected_blocks=selected_blocks,
            forced_type=rule_type,
            forced_type_citations=rule_citations,
            quote_max_chars=int(extraction_cfg["quote_max_chars"]),
            evidence_minimal_max=evidence_max,
        )

        validation_errors = validate_kc_record(record)
        if validation_errors:
            raise RuntimeError(f"Schema validation failed for {kc_id}: {validation_errors[:10]}")

        tier_info = classify_tier(record)
        records.append(record)
        if len(records) % 10 == 0:
            logger.info(f"Processed {len(records)}/{len(registry_rows)} KCs")
        if int(tier_info["tier"]) < 1:
            recovery_rows.append(
                {
                    "kc_id": kc_id,
                    "tier": int(tier_info["tier"]),
                    "tier1_fail_reasons": list(tier_info["reasons"]),
                    "missing_fields": list(tier_info["reasons"]),
                    "reasons": record["recovery_reasons"],
                    "evidence_blocks_considered": [str(item["block_id"]) for item in considered_blocks],
                    "debug_snippets": [f"{item['block_id']}: {str(item['source_text'])[:140]}" for item in selected_blocks[:6]],
                }
            )

        if kc_id in sample_ids:
            trace_payload = {
                "kc_id": kc_id,
                "selected_blocks": [
                    {
                        "doc_id": item["doc_id"],
                        "block_id": item["block_id"],
                        "page_index": item["page_index"],
                        "layer": item["layer"],
                        "patch_heading": item.get("patch_heading") or "",
                        "text_truncated": str(item["source_text"])[:600],
                    }
                    for item in selected_blocks
                ],
                "prompt": {"system": prompt_system, "user": prompt_user},
                "rules_based_type": rule_type or "",
                "model_payload": payload,
                "model_response_raw": raw_response,
                "model_outer_response": raw_outer,
                "validation": {
                    "record_errors": validation_errors,
                    "tier": int(tier_info["tier"]),
                    "tier_reasons": list(tier_info["reasons"]),
                    "tier_flags": list(tier_info["flags"]),
                    "is_usable": int(tier_info["tier"]) >= 1,
                },
                "final_record_snippet": {
                    "kc_type": record["kc_type"],
                    "definition_short": record["definition_short"],
                    "definition_full": record["definition_full"][:400],
                    "scope_includes": record["scope_includes"],
                    "scope_excludes": record["scope_excludes"],
                    "evidence_minimal": record["evidence_minimal"],
                },
            }
            write_json(trace_dir / f"trace_{kc_id}.json", trace_payload)

    timings["extraction_seconds"] = round(time.perf_counter() - extraction_started, 3)

    registry_ids = set(registry_by_order)
    record_ids = {str(record["kc_id"]) for record in records}
    if registry_ids != record_ids:
        missing = sorted(registry_ids - record_ids)
        extra = sorted(record_ids - registry_ids)
        raise RuntimeError(f"Registry/record KC mismatch. Missing={missing[:10]} Extra={extra[:10]}")

    tier_results = {str(record["kc_id"]): classify_tier(record) for record in records}
    tier1_records = [record for record in records if int(tier_results[str(record["kc_id"])]["tier"]) >= 1]
    tier2_records = [record for record in records if int(tier_results[str(record["kc_id"])]["tier"]) >= 2]
    for record in tier1_records:
        evidence_minimal = record.get("evidence_minimal") or []
        if not evidence_minimal:
            raise RuntimeError(f"Tier 1 record has empty evidence_minimal: {record['kc_id']}")
        if any(not item.get("quote_verified") for item in evidence_minimal):
            raise RuntimeError(f"Tier 1 record has unverified evidence quote: {record['kc_id']}")

    verified_quote_issues: List[str] = []
    for record in records:
        verified_quote_issues.extend(find_verified_quote_mismatches(record, source_lookup))
    if verified_quote_issues:
        raise RuntimeError(f"Verified quote mismatches detected: {verified_quote_issues[:10]}")

    kc_library_path = processed_dir / "kc_library.jsonl"
    stats_path = processed_dir / "kc_library_stats.json"
    recovery_path = processed_dir / "recovery_queue.jsonl"
    write_jsonl(kc_library_path, records)
    write_jsonl(recovery_path, recovery_rows)

    field_coverage = {
        "definition_short": round(100.0 * sum(1 for r in records if str(r["definition_short"]).strip()) / len(records), 2),
        "definition_full": round(100.0 * sum(1 for r in records if str(r["definition_full"]).strip()) / len(records), 2),
        "scope_includes": round(100.0 * sum(1 for r in records if len(r["scope_includes"]) > 0) / len(records), 2),
        "scope_excludes": round(100.0 * sum(1 for r in records if len(r["scope_excludes"]) > 0) / len(records), 2),
        "evidence_minimal": round(100.0 * sum(1 for r in records if len(r["evidence_minimal"]) > 0) / len(records), 2),
    }
    evidence_dist = Counter(len(record["evidence_minimal"]) for record in records)
    top_gaps = []
    for record in records:
        tier_info = tier_results[str(record["kc_id"])]
        gap_reasons = [str(reason) for reason in tier_info["reasons"]]
        top_gaps.append(
            {
                "kc_id": record["kc_id"],
                "tier": int(tier_info["tier"]),
                "missing_count": len(gap_reasons),
                "missing_fields": gap_reasons,
            }
        )
    top_gaps.sort(key=lambda item: (-item["missing_count"], item["kc_id"]))
    n_kcs_total = len(records)
    n_kcs_tier1 = len(tier1_records)
    n_kcs_tier2 = len(tier2_records)
    n_kcs_in_recovery_queue = len(recovery_rows)
    stats_payload = {
        "n_kcs_total": n_kcs_total,
        "n_kcs_tier1": n_kcs_tier1,
        "n_kcs_tier2": n_kcs_tier2,
        "n_kcs_usable": n_kcs_tier1,
        "n_kcs_in_recovery_queue": n_kcs_in_recovery_queue,
        "stats_meta": {
            "usable_definition": "Tier 1 (retrieval-usable)",
            "tier_contract": "Step 6.2",
        },
        "coverage_percent": field_coverage,
        "evidence_minimal_size_distribution": {str(k): int(v) for k, v in sorted(evidence_dist.items())},
        "top_20_kcs_by_missing_fields_count": top_gaps[:20],
    }
    write_json(stats_path, stats_payload)

    summary_payload = {
        "n_kcs_total": n_kcs_total,
        "n_kcs_records_written": n_kcs_total,
        "n_kcs_tier1": n_kcs_tier1,
        "n_kcs_tier2": n_kcs_tier2,
        "n_kcs_usable": n_kcs_tier1,
        "n_kcs_in_recovery_queue": n_kcs_in_recovery_queue,
        "stats_meta": {
            "usable_definition": "Tier 1 (retrieval-usable)",
            "tier_contract": "Step 6.2",
        },
        "coverage_percent": field_coverage,
        "run_id_step6": run_id_step6,
        "schema_version": schema_ver,
        "generation_model": chosen_model,
    }
    write_json(audit_dir / "summary.json", summary_payload)

    if n_kcs_tier1 == 0:
        raise RuntimeError("Hard failure: n_kcs_tier1 = 0")
    recovery_ids = {str(row["kc_id"]) for row in recovery_rows}
    tier0_ids = {str(record["kc_id"]) for record in records if int(tier_results[str(record["kc_id"])]["tier"]) == 0}
    if recovery_ids != tier0_ids:
        missing = sorted(tier0_ids - recovery_ids)
        extra = sorted(recovery_ids - tier0_ids)
        raise RuntimeError(f"Recovery queue mismatch for Tier 1 failures. Missing={missing[:10]} Extra={extra[:10]}")
    if n_kcs_in_recovery_queue != (n_kcs_total - n_kcs_tier1):
        raise RuntimeError(
            "Recovery queue count does not match Tier 1 failures: "
            f"recovery={n_kcs_in_recovery_queue} tier0={n_kcs_total - n_kcs_tier1}"
        )

    set_manifest = build_set_manifest(
        repo_root=repo_root,
        set_path=set_path,
        run_id_step6=run_id_step6,
        processed_dir=processed_dir,
        audit_dir=audit_dir,
        created_utc=created_utc,
        kc_registry_path=kc_registry_path,
        step5_pointer_path=step5_pointer_path,
        step5_set_path=step5_set_path,
        step4_set_path=step4_set_path,
        step5_manifest=step5_manifest,
    )
    write_json(set_path, set_manifest)

    output_manifest = {
        "processed_outputs": build_output_manifest(processed_dir),
        "set_manifest": describe_file(set_path, repo_root),
        "active_pointer": {"path": rel_path(active_pointer_path, repo_root), "exists": False},
    }
    write_json(audit_dir / "output_manifest.json", output_manifest)

    timings["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    write_json(audit_dir / "timings.json", timings)

    write_text(active_pointer_path, set_path.name + "\n")
    output_manifest["active_pointer"] = describe_file(active_pointer_path, repo_root)
    write_json(audit_dir / "output_manifest.json", output_manifest)

    print(f"n_kcs_total: {n_kcs_total}")
    print(f"n_kcs_records_written: {n_kcs_total}")
    print(f"n_kcs_tier1: {n_kcs_tier1}")
    print(f"n_kcs_tier2: {n_kcs_tier2}")
    print(f"n_kcs_usable: {n_kcs_tier1}")
    print(f"n_kcs_in_recovery_queue: {n_kcs_in_recovery_queue}")
    for field_name, pct in field_coverage.items():
        print(f"coverage_{field_name}: {pct}")
    print("kc_id | tier | kc_type | definition_short_nonempty | evidence_minimal_n | verified_quotes_n | in_recovery")
    for kc_id in sample_ids:
        record = next(item for item in records if str(item["kc_id"]) == kc_id)
        tier_info = tier_results[str(record["kc_id"])]
        quotes_verified = verified_quote_count(record["evidence_minimal"])
        print(
            f"{kc_id} | {int(tier_info['tier'])} | {record['kc_type']} | {bool(str(record['definition_short']).strip())} | "
            f"{len(record['evidence_minimal'])} | {quotes_verified} | {record['recovery_state'] != 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
