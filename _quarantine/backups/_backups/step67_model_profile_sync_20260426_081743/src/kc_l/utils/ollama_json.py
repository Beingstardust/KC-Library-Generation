from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


DEFAULT_OLLAMA_RESPONSE_PARSE_MODE = "message_content_or_response_or_thinking"


def _truncate_preview(text: str, limit: int = 400) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def _strip_code_fences(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"^\s*```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```\s*$", "", value, flags=re.IGNORECASE)
    return value.strip()


def _strip_think_blocks(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.IGNORECASE | re.DOTALL)
    return value.strip()


def _extract_first_balanced_json_object(text: str) -> str:
    value = str(text or "")
    start = value.find("{")
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(value)):
        ch = value[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return value[start : idx + 1]

    return ""


def _try_parse_json_dict(candidate: str) -> Dict[str, Any] | None:
    value = str(candidate or "").strip()
    if not value:
        return None

    attempts = [
        value,
        re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", value),
    ]
    for item in attempts:
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _candidate_json_payloads(
    raw_text: str,
    *,
    strip_thought_block_before_parse: bool,
) -> List[str]:
    base = str(raw_text or "")
    candidates: List[str] = []

    def add(value: str) -> None:
        item = str(value or "").strip()
        if item and item not in candidates:
            candidates.append(item)

    add(base)
    stripped = base.strip()
    add(stripped)

    no_fence = _strip_code_fences(stripped)
    add(no_fence)

    if strip_thought_block_before_parse:
        no_think = _strip_think_blocks(stripped)
        add(no_think)

        no_think_no_fence = _strip_code_fences(no_think)
        add(no_think_no_fence)

    for seed in list(candidates):
        extracted = _extract_first_balanced_json_object(seed)
        add(extracted)

    return candidates


def _parse_json_object_with_backslash_salvage(
    raw_text: str,
    *,
    strip_thought_block_before_parse: bool = False,
) -> Dict[str, Any]:
    text = str(raw_text or "")
    if not text.strip():
        raise RuntimeError("Ollama chat response content was empty.")

    for candidate in _candidate_json_payloads(
        text,
        strip_thought_block_before_parse=strip_thought_block_before_parse,
    ):
        parsed = _try_parse_json_dict(candidate)
        if parsed is not None:
            return parsed

    raise RuntimeError(
        "Could not parse Ollama content as a JSON object. "
        f"raw_preview={_truncate_preview(text)!r}"
    )


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


def choose_generation_model(installed: Sequence[str], cfg: Mapping[str, Any]) -> str:
    candidates = [str(item) for item in cfg.get("candidate_models") or []]
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


def ollama_http_list_models(base_url: str, timeout_s: float = 15.0) -> List[str]:
    import urllib.request

    url = base_url.rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    models: List[str] = []
    for item in obj.get("models") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("model") or item.get("name") or "").strip()
        if name:
            models.append(name)
    return models


def _ollama_response_text_candidates(
    outer: Mapping[str, Any],
    *,
    response_parse_mode: str,
) -> List[Any]:
    mode = str(response_parse_mode or DEFAULT_OLLAMA_RESPONSE_PARSE_MODE).strip().lower()
    message = outer.get("message") or {}
    candidates: List[Any] = [message.get("content")]

    if mode in {"message_content_or_response", DEFAULT_OLLAMA_RESPONSE_PARSE_MODE}:
        candidates.extend([outer.get("response"), outer.get("content")])
    if mode == DEFAULT_OLLAMA_RESPONSE_PARSE_MODE:
        candidates.extend([message.get("thinking"), outer.get("thinking")])
    return candidates


def parse_ollama_chat_response_json(
    outer: Mapping[str, Any],
    *,
    raw_response: str = "",
    response_parse_mode: str = DEFAULT_OLLAMA_RESPONSE_PARSE_MODE,
    strip_thought_block_before_parse: bool = False,
) -> Dict[str, Any]:
    text_candidates = _ollama_response_text_candidates(
        outer,
        response_parse_mode=response_parse_mode,
    )
    for candidate in text_candidates:
        if isinstance(candidate, Mapping):
            return dict(candidate)
        if isinstance(candidate, str) and candidate.strip():
            parsed = _parse_json_object_with_backslash_salvage(
                candidate,
                strip_thought_block_before_parse=strip_thought_block_before_parse,
            )
            return parsed
    raise RuntimeError(
        "Ollama chat response content was empty. "
        f"response_parse_mode={response_parse_mode!r} "
        f"outer_keys={sorted(str(k) for k in outer.keys())} "
        f"raw_preview={_truncate_preview(raw_response)!r}"
    )


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
    response_parse_mode: str = DEFAULT_OLLAMA_RESPONSE_PARSE_MODE,
    strip_thought_block_before_parse: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    import urllib.request

    payload: Dict[str, Any] = {
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
    parsed = parse_ollama_chat_response_json(
        outer,
        raw_response=raw,
        response_parse_mode=response_parse_mode,
        strip_thought_block_before_parse=strip_thought_block_before_parse,
    )
    return parsed, outer, raw
