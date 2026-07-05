from __future__ import annotations

from typing import Any, Dict, List, Mapping

from kc_l.kc_drafting.contracts import as_bool, as_text


DEFAULT_STEP67_BACKEND_KIND = "ollama"
DEFAULT_STEP67_TRANSPORT_MODE = "ollama_chat"
DEFAULT_STEP67_THINKING_ACTIVATION_MODE = "request_flag"
DEFAULT_STEP67_RESPONSE_PARSE_MODE = "message_content_or_response_or_thinking"

SUPPORTED_STEP67_BACKEND_KINDS = {
    DEFAULT_STEP67_BACKEND_KIND,
}
SUPPORTED_STEP67_TRANSPORT_MODES = {
    DEFAULT_STEP67_TRANSPORT_MODE,
}
SUPPORTED_STEP67_THINKING_ACTIVATION_MODES = {
    "off",
    DEFAULT_STEP67_THINKING_ACTIVATION_MODE,
    "system_prefix",
}
SUPPORTED_STEP67_RESPONSE_PARSE_MODES = {
    "message_content_only",
    "message_content_or_response",
    DEFAULT_STEP67_RESPONSE_PARSE_MODE,
}


def step67_model_profile_defaults() -> Dict[str, Any]:
    return {
        "generation_model": "",
        "backend_kind": DEFAULT_STEP67_BACKEND_KIND,
        "transport_mode": DEFAULT_STEP67_TRANSPORT_MODE,
        "thinking_enabled": False,
        "thinking_activation_mode": DEFAULT_STEP67_THINKING_ACTIVATION_MODE,
        "thinking_system_prefix": "",
        "strip_thought_block_before_parse": False,
        "response_parse_mode": DEFAULT_STEP67_RESPONSE_PARSE_MODE,
    }


def normalize_step67_model_profile(raw_profile: Mapping[str, Any] | None) -> Dict[str, Any]:
    profile = step67_model_profile_defaults()
    source = dict(raw_profile or {})
    profile["generation_model"] = as_text(source.get("generation_model") or source.get("resolved_model_alias"))
    profile["backend_kind"] = as_text(source.get("backend_kind") or source.get("provider") or DEFAULT_STEP67_BACKEND_KIND).lower()
    profile["transport_mode"] = as_text(source.get("transport_mode") or DEFAULT_STEP67_TRANSPORT_MODE).lower()
    profile["thinking_enabled"] = as_bool(
        source.get("thinking_enabled"),
        default=as_bool(source.get("think"), default=False),
    )
    profile["thinking_activation_mode"] = as_text(
        source.get("thinking_activation_mode") or DEFAULT_STEP67_THINKING_ACTIVATION_MODE
    ).lower()
    profile["thinking_system_prefix"] = as_text(source.get("thinking_system_prefix"))
    profile["strip_thought_block_before_parse"] = as_bool(
        source.get("strip_thought_block_before_parse"),
        default=False,
    )
    profile["response_parse_mode"] = as_text(
        source.get("response_parse_mode") or DEFAULT_STEP67_RESPONSE_PARSE_MODE
    ).lower()
    return profile


def validate_supported_step67_model_profile(
    profile: Mapping[str, Any],
    *,
    field_prefix: str,
) -> None:
    backend_kind = as_text(profile.get("backend_kind")).lower()
    transport_mode = as_text(profile.get("transport_mode")).lower()
    thinking_activation_mode = as_text(profile.get("thinking_activation_mode")).lower()
    response_parse_mode = as_text(profile.get("response_parse_mode")).lower()

    errors: List[str] = []
    if backend_kind not in SUPPORTED_STEP67_BACKEND_KINDS:
        errors.append(
            f"{field_prefix}.backend_kind must be one of {sorted(SUPPORTED_STEP67_BACKEND_KINDS)}, not {backend_kind!r}."
        )
    if transport_mode not in SUPPORTED_STEP67_TRANSPORT_MODES:
        errors.append(
            f"{field_prefix}.transport_mode must be one of {sorted(SUPPORTED_STEP67_TRANSPORT_MODES)}, not {transport_mode!r}."
        )
    if thinking_activation_mode not in SUPPORTED_STEP67_THINKING_ACTIVATION_MODES:
        errors.append(
            f"{field_prefix}.thinking_activation_mode must be one of {sorted(SUPPORTED_STEP67_THINKING_ACTIVATION_MODES)}, not {thinking_activation_mode!r}."
        )
    if response_parse_mode not in SUPPORTED_STEP67_RESPONSE_PARSE_MODES:
        errors.append(
            f"{field_prefix}.response_parse_mode must be one of {sorted(SUPPORTED_STEP67_RESPONSE_PARSE_MODES)}, not {response_parse_mode!r}."
        )
    if (
        as_bool(profile.get("thinking_enabled"))
        and thinking_activation_mode == "system_prefix"
        and not as_text(profile.get("thinking_system_prefix"))
    ):
        errors.append(
            f"{field_prefix}.thinking_system_prefix must be explicit when thinking is enabled via system_prefix."
        )
    if errors:
        raise RuntimeError(" ".join(errors))


def apply_step67_model_profile_to_messages(
    messages: List[Dict[str, str]],
    profile: Mapping[str, Any],
) -> List[Dict[str, str]]:
    prepared = [dict(message) for message in messages]
    if not as_bool(profile.get("thinking_enabled")):
        return prepared
    if as_text(profile.get("thinking_activation_mode")).lower() != "system_prefix":
        return prepared
    prefix = as_text(profile.get("thinking_system_prefix"))
    if not prefix:
        return prepared
    for message in prepared:
        if as_text(message.get("role")).lower() != "system":
            continue
        content = as_text(message.get("content"))
        message["content"] = prefix if not content else f"{prefix}\n\n{content}"
        return prepared
    return [{"role": "system", "content": prefix}, *prepared]


def step67_model_profile_think_flag(profile: Mapping[str, Any]) -> bool | None:
    if as_text(profile.get("thinking_activation_mode")).lower() != DEFAULT_STEP67_THINKING_ACTIVATION_MODE:
        return None
    return bool(as_bool(profile.get("thinking_enabled"), default=False))
