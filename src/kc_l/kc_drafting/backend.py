from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Protocol, Sequence, Tuple

from kc_l.kc_drafting.contracts import EXECUTION_MODE_LLM, as_text, looks_unresolved
from kc_l.kc_drafting.model_profile import (
    normalize_step67_model_profile,
    validate_supported_step67_model_profile,
)
from kc_l.kc_drafting.policy_generic import build_kc_draft_bundles
from kc_l.utils.kc_step67_model_drafting import Step67DraftingPolicy, Step67ModelRuntime, build_kc_draft_bundles_llm
from kc_l.utils.ollama_json import ollama_http_list_models, ollama_http_version


class DraftingBackend(Protocol):
    backend_name: str

    def ensure_available(self) -> List[str]:
        ...

    def tool_versions(self) -> Dict[str, Any]:
        ...

    def draft(self, overlay_rows: Sequence[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        ...


def ensure_llm_runtime_available(execution: Mapping[str, Any]) -> List[str]:
    model_profile = normalize_step67_model_profile(execution.get("model_profile"))
    validate_supported_step67_model_profile(
        model_profile,
        field_prefix=as_text(execution.get("model_profile_field")) or "execution.model_profile",
    )
    generation_model_alias = as_text(model_profile.get("generation_model") or execution.get("generation_model_alias"))
    generation_base_url = as_text(execution.get("generation_base_url"))
    if not generation_model_alias:
        raise RuntimeError(
            f"Step 6.7 LLM mode requires a resolved generation model alias at {execution.get('generation_model_field')}."
        )
    if looks_unresolved(generation_model_alias):
        raise RuntimeError(
            f"Step 6.7 LLM mode requires a concrete generation model alias, not {generation_model_alias!r}."
        )
    if not generation_base_url:
        raise RuntimeError(
            f"Step 6.7 LLM mode requires a concrete base URL at {execution.get('generation_base_url_field')}."
        )
    if looks_unresolved(generation_base_url):
        raise RuntimeError(
            f"Step 6.7 LLM mode requires a concrete LLM endpoint, not {generation_base_url!r}."
        )
    provider = as_text(model_profile.get("backend_kind") or execution.get("provider") or "ollama").lower()
    transport_mode = as_text(model_profile.get("transport_mode") or "ollama_chat").lower()
    if provider != "ollama" or transport_mode != "ollama_chat":
        raise RuntimeError(
            "Unsupported Step 6.7 LLM backend/transport combination: "
            f"{provider}/{transport_mode}"
        )
    available_models = ollama_http_list_models(generation_base_url, timeout_s=15.0)
    if generation_model_alias not in set(available_models):
        raise RuntimeError(
            "Required Step 6.7 generation model "
            f"{generation_model_alias!r} was not available at {generation_base_url}. "
            f"Available={sorted(set(available_models))}"
        )
    return available_models


@dataclass
class HeuristicDraftingBackend:
    selection_cfg: Mapping[str, Any]
    backend_name: str = "heuristic"

    def ensure_available(self) -> List[str]:
        return []

    def tool_versions(self) -> Dict[str, Any]:
        return {}

    def draft(self, overlay_rows: Sequence[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        return build_kc_draft_bundles(
            overlay_rows,
            max_bundle_size=int(self.selection_cfg.get("max_bundle_size", 4)),
            max_explanatory_candidates=int(self.selection_cfg.get("max_explanatory_candidates", 3)),
        )


@dataclass
class OllamaDraftingBackend:
    execution: Mapping[str, Any]
    drafting_cfg: Mapping[str, Any]
    selection_cfg: Mapping[str, Any]
    backend_name: str = "ollama_llm"

    def _runtime(self) -> Step67ModelRuntime:
        model_profile = normalize_step67_model_profile(self.execution.get("model_profile"))
        return Step67ModelRuntime(
            base_url=as_text(self.execution.get("generation_base_url")),
            model=as_text(model_profile.get("generation_model") or self.execution.get("generation_model_alias")),
            max_retries=int(self.execution.get("max_retries", 3)),
            num_ctx=int(self.execution.get("num_ctx", 8192)),
            timeout_seconds=float(self.execution.get("timeout_seconds", 180.0)),
            temperature=float(self.execution.get("temperature", 0.0)),
            top_p=float(self.execution.get("top_p", 1.0)),
            repeat_penalty=float(self.execution.get("repeat_penalty", 1.0)),
            think=self.execution.get("think"),
            model_profile=model_profile,
        )

    def _policy(self) -> Step67DraftingPolicy:
        return Step67DraftingPolicy(
            definition_candidate_limit=int(self.drafting_cfg.get("definition_candidate_limit", 5)),
            scope_candidate_limit=int(self.drafting_cfg.get("scope_candidate_limit", 5)),
            family_context_limit=int(self.drafting_cfg.get("family_context_limit", 4)),
            completion_context_limit=int(self.drafting_cfg.get("completion_context_limit", 4)),
            evidence_text_max_chars=int(self.drafting_cfg.get("evidence_text_max_chars", 320)),
            max_bundle_size=int(self.selection_cfg.get("max_bundle_size", 6)),
            max_explanatory_candidates=int(self.selection_cfg.get("max_explanatory_candidates", 5)),
            short_definition_max_chars=int(self.drafting_cfg.get("short_definition_max_chars", 220)),
            short_definition_max_tokens=int(self.drafting_cfg.get("short_definition_max_tokens", 32)),
            max_definition_binding_support_rows=int(
                self.drafting_cfg.get("max_definition_binding_support_rows", 2)
            ),
            max_llm_calls_per_kc=int(self.drafting_cfg.get("max_llm_calls_per_kc", 8)),
            definition_generation_mode=as_text(
                self.drafting_cfg.get("definition_generation_mode")
                or "legacy_joint_draft_v1"
            ),
        )

    def ensure_available(self) -> List[str]:
        return ensure_llm_runtime_available(self.execution)

    def tool_versions(self) -> Dict[str, Any]:
        return {
            "ollama_http_version": ollama_http_version(as_text(self.execution.get("generation_base_url"))),
        }

    def draft(self, overlay_rows: Sequence[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        return build_kc_draft_bundles_llm(
            overlay_rows,
            runtime=self._runtime(),
            policy=self._policy(),
        )


def build_drafting_backend(
    execution: Mapping[str, Any],
    *,
    drafting_cfg: Mapping[str, Any],
    selection_cfg: Mapping[str, Any],
) -> DraftingBackend:
    if as_text(execution.get("execution_mode")).lower() == EXECUTION_MODE_LLM:
        return OllamaDraftingBackend(execution=execution, drafting_cfg=drafting_cfg, selection_cfg=selection_cfg)
    return HeuristicDraftingBackend(selection_cfg=selection_cfg)
