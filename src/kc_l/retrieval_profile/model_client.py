from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, List, Mapping, Sequence


SYSTEM_PROMPT = """You are a KC retrieval-profile classifier.

Return only valid JSON.

Task:
Extract source-observed retrieval cues for the TARGET KC only.

Rules:
1. Do not draft definitions, scopes, teaching explanations, examples, or criteria.
2. Do not require the canonical KC label to appear exactly.
3. A source-observed cue may be active if the source text directly describes the target KC mechanism, relation, formula, process, or issue.
4. Sibling labels are negative constraints. Do not activate a sibling label as a target cue merely because it appears in the source.
5. If a sibling/background concept appears only as part of a larger phrase that expresses the target KC mechanism, activate the larger phrase, not the sibling label alone.
6. Reject bibliography, reference-only, metadata-only, query-like, or wrong-sense snippets.
7. Every active cue must have provenance.
8. Model-suggested terms without source support must be quarantined, not active.
9. strict_source_windows and exploratory_profile_windows are Step 5p profiler inputs only, not final evidence.
10. exploratory_profile_windows are weak context windows. Use them only to discover possible source-observed cue wording, and keep uncertainty explicit.
11. If a term is broad parent-topic context, mark it as context-only, not as leaf-KC evidence.
12. If a short or ambiguous term is only safe with local support words, express that as a route-level support requirement. Do not make it a global KC rule.
13. Support terms are soft by default. Mark them required only when the pattern is visible in the supplied source window.
14. source_neighborhood_anchor windows are scout context. They may help identify source wording, but they are not evidence until the returned cue is directly source-observed and target-relevant.
15. If the supplied windows are broad parent-topic context only, return context-only routes or weak profile rather than active leaf-KC routes.

Role-target guidance rules:
16. Classify source-confirmed cues by intended retrieval role: primary_core, explanation, formula_or_procedure, example_or_boundary, or bridge_context.
17. Generic parent-topic context is allowed only as bridge_context unless the source window directly binds it to the target unit.
18. Output domain/source-specific terms only when they are visible in the supplied source windows. Keep inferred or model-suggested probes inactive until source-confirmed.
19. This is still retrieval planning metadata, not evidence and not a draft.
"""


def _post_json(url: str, payload: Mapping[str, Any], timeout_seconds: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def ollama_chat_json(
    *,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int = 180,
    temperature: float = 0.0,
    think: bool = False,
    seed: int | None = None,
) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/api/chat"
    options: Dict[str, Any] = {
        "temperature": temperature,
        "top_p": 1,
        # Every sampling parameter must be pinned explicitly, not just temperature/top_p/seed.
        # Anything left unset falls through to each model's own Modelfile defaults, which differ
        # per model, so a model swap would change sampling as well as weights - a fairness gap in
        # any controlled comparison.
        #
        # The specific values below are not arbitrary "neutral" ones: they are the effective
        # values that already applied when these keys were left unsent (the reference model's
        # Modelfile declares top_k=64, and min_p/presence_penalty/repeat_penalty fall through to
        # Ollama's own defaults of 0.0/0.0/1.1). Pinning to those means a model swap at this
        # stage differs ONLY in the model weights, while the reference model's behaviour stays
        # identical to its established baseline. Choosing neutral-looking values instead would
        # silently change that baseline.
        "top_k": 64,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repeat_penalty": 1.1,
    }
    # temperature=0 alone does not guarantee reproducible output across
    # separate Ollama inference calls (observed in a real run - repeated fresh
    # regenerations of step_05p's retrieval profile for the same KC, same corpus, same config,
    # produced materially different selected source cues run to run, sometimes dropping to zero
    # evidence on one day and recovering with a completely different, zero-overlap set the next).
    # No seed was ever set, so nothing constrained the RNG state between calls. Passing a fixed
    # seed here is necessary but not proven sufficient on its own - GPU floating-point
    # non-associativity across batches is a separate, real source of variance this doesn't
    # address; verify empirically (see run-twice-and-diff check) rather than assume this closes
    # the gap completely.
    if seed is not None:
        options["seed"] = int(seed)
    payload: Dict[str, Any] = {
        "model": model,
        "stream": False,
        "format": "json",
        "think": bool(think),
        "options": options,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    response = _post_json(url, payload, timeout_seconds=timeout_seconds)
    content = (((response or {}).get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("Ollama response did not contain message.content")
    return json.loads(content)


def _clip_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 24].rstrip() + " ...[truncated]"


def _safe_prompt_snippet(snip: Mapping[str, Any]) -> Dict[str, Any]:
    # Step 5p runs on local and HPC models where prompt budget directly affects
    # timeout risk.  The full, auditable window remains in profile artifacts; the
    # model only needs a compact source view to classify route-control cues.
    previews = snip.get("source_neighborhood_anchor_previews")
    if isinstance(previews, list):
        safe_previews = [_clip_text(x, 160) for x in previews[:2]]
    else:
        safe_previews = []

    return {
        "snippet_id": snip.get("snippet_id"),
        "text": _clip_text(snip.get("text"), 760),
        "field_path": snip.get("field_path"),
        "doc_id": snip.get("doc_id"),
        "page_index": snip.get("page_index"),
        "patch_id": snip.get("patch_id"),
        "score": snip.get("score"),
        "score_reasons": snip.get("score_reasons"),
        "target_overlap": snip.get("target_overlap"),
        "branch_overlap": snip.get("branch_overlap"),
        "sibling_hits": snip.get("sibling_hits"),
        "source_neighborhood_anchor_terms": snip.get("source_neighborhood_anchor_terms"),
        "source_neighborhood_anchor_count": snip.get("source_neighborhood_anchor_count"),
        "source_neighborhood_anchor_previews": safe_previews,
        "target_source_neighborhood_anchor_count": snip.get("target_source_neighborhood_anchor_count"),
        "sibling_context_anchor_count": snip.get("sibling_context_anchor_count"),
        "patch_heading": _clip_text(snip.get("patch_heading"), 180),
        "reveal_group_id": snip.get("reveal_group_id"),
        "evidence_shapes": snip.get("evidence_shapes"),
        "profile_window_lane": snip.get("profile_window_lane"),
        "profile_window_role": snip.get("profile_window_role"),
        "window_supplier": snip.get("window_supplier"),
        "topic_local_anchor_reason": snip.get("topic_local_anchor_reason"),
    }


def build_user_prompt(
    kc_meta: Mapping[str, Any],
    snippets: Sequence[Mapping[str, Any]],
    *,
    strict_source_windows: Sequence[Mapping[str, Any]] | None = None,
    exploratory_profile_windows: Sequence[Mapping[str, Any]] | None = None,
    base_profile: Mapping[str, Any] | None = None,
    feedback_gap_request: Mapping[str, Any] | None = None,
    feedback_round: int | None = None,
) -> str:
    strict_payload = [_safe_prompt_snippet(s) for s in (strict_source_windows or [])]
    exploratory_payload = [_safe_prompt_snippet(s) for s in (exploratory_profile_windows or [])]
    # Avoid sending the same windows three times.  Earlier prompts included a
    # backward-compatible combined `source_snippets` view in addition to strict
    # and exploratory lanes, which doubled prompt size and caused local timeouts
    # without adding information.  Artifact compatibility is preserved in the
    # profile audit; model input uses the lane-specific lists only.
    safe_snippets: List[Dict[str, Any]] = []

    payload = {
        "KC": {
            "kc_id": kc_meta.get("kc_id"),
            "canonical_name": kc_meta.get("canonical_name"),
            "aliases": kc_meta.get("aliases") or [],
            "topic_path": kc_meta.get("topic_path_labels") or [],
            "sibling_labels": kc_meta.get("sibling_labels") or [],
        },
        "profile_input_semantics": {
            "strict_source_windows": "higher-confidence profiler input windows; still not final evidence",
            "exploratory_profile_windows": "weak context windows for cue discovery only; never treat as evidence by themselves",
            "source_snippets": "omitted from model prompt to avoid duplicate strict/exploratory windows",
            "final_evidence_selection": "not performed in Step 5p; profile-guided evidence retrieval happens later in Step 5x",
        },
        "strict_source_windows": strict_payload,
        "exploratory_profile_windows": exploratory_payload,
        "source_snippets": safe_snippets,
        "feedback_mode": {
            "enabled": bool(feedback_gap_request),
            "feedback_round": feedback_round,
            "purpose": "repair route-control metadata after a Step 5x retrieval gap; do not produce final evidence",
            "base_profile_summary": {
                "profile_status": (base_profile or {}).get("profile_status"),
                "accepted_source_cue_count": len((base_profile or {}).get("accepted_source_cues") or []),
                "query_variant_count": len((base_profile or {}).get("query_variants") or []),
                "retrieval_route_count": len((base_profile or {}).get("retrieval_routes") or []),
            },
            "step5x_gap_request": feedback_gap_request or {},
            "repair_rules": [
                "Return source-observed route-control cues only.",
                "Do not invent a route if the supplied snippets and candidate summaries do not justify one.",
                "Use context-only routes for broad parent-topic regions.",
                "Use support terms or negative terms only when the supplied source text supports them.",
                "Never output final evidence, definitions, teaching explanations, or KC-specific criteria.",
            ],
        },
        "return_json_shape": {
            "kc_id": kc_meta.get("kc_id"),
            "profile_decision": "usable|weak|reject",
            "accepted_source_cues": [
                {
                    "term": "...",
                    "cue_type": "source_observed_equivalent|mechanism_description|formula_relation|process_phrase|definition_phrase|metric_relation|context_phrase",
                    "active": True,
                    "why_target_relevant": "...",
                    "provenance": [{"snippet_id": "...", "field_path": "..."}],
                }
            ],
            "role_targets": [
                {
                    "role_target_id": "...",
                    "target_role": "primary_core|explanation|formula_or_procedure|example_or_boundary|bridge_context",
                    "support_scope": "branch_specific_core|core_or_support|support|parent_or_generic_context|boundary_or_example",
                    "active_terms_any": ["source-confirmed terms only"],
                    "activation_status": "source_confirmed|context_only|quarantine",
                    "cannot_be_sole_core": False,
                    "provenance": [{"snippet_id": "...", "field_path": "..."}],
                }
            ],
            "retrieval_routes": [
                {
                    "route_id": "...",
                    "route_type": "anchored_phrase|cooccurrence_constrained|formula_or_metric|context_locator|sibling_discriminator|negative_filter",
                    "activation": "active|context_only|quarantine",
                    "route_strength": "strong|weak",
                    "primary_terms_any": ["..."],
                    "support_terms_any": ["..."],
                    "support_terms_all": [],
                    "negative_terms_any": [],
                    "local_window_scope": "same_sentence_or_patch",
                    "support_requirement": "none|boost_only|required_for_this_route|required_for_positive_support_on_this_route",
                    "can_create_candidates": True,
                    "can_create_positive_support": True,
                    "support_authority": "candidate_hint_step5x_must_verify",
                    "step5x_verification_required": True,
                    "route_trust": "model_route_guidance",
                    "broad_context_only": False,
                    "provenance": [{"snippet_id": "...", "field_path": "..."}],
                }
            ],
            "quarantined_terms": [
                {"term": "...", "reason": "...", "related_snippet_ids": ["..."]}
            ],
            "rejected_terms": [
                {"term": "...", "reason": "...", "related_snippet_ids": ["..."]}
            ],
            "sibling_constraint_checks": [
                {
                    "sibling_label": "...",
                    "status": "not_observed|background_only|collision_risk|wrong_sense",
                    "reason": "...",
                    "related_snippet_ids": ["..."],
                }
            ],
        },
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


# Operator note for Step5p prompt evolution:
# The canonical retrieval-planning contract is implemented downstream in
# role_target_contract.py as MAXIMAL_RETRIEVAL_PLANNING_CONTRACT_VERSION.
# Model output should remain source-grounded retrieval guidance, not evidence.
STEP5P_MAXIMAL_RETRIEVAL_PLANNING_PROMPT_NOTE_V2 = (
    "Step5p uses the model as a source-grounded retrieval planner. "
    "It may produce KC-specific retrieval guidance, but all final support "
    "must be verified by Step5x and later review."
)

