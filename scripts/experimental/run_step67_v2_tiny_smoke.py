from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Tuple


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def norm(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: pathlib.Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    invalid = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    invalid += 1
            except Exception:
                invalid += 1
    return rows, invalid


def write_jsonl(path: pathlib.Path, rows: List[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def unit_id(packet: Mapping[str, Any]) -> str:
    return str(packet.get("knowledge_unit_id") or packet.get("kc_id") or packet.get("topic_id") or "")


def unit_type(packet: Mapping[str, Any]) -> str:
    return str(packet.get("knowledge_unit_type") or "")


def canonical_name(packet: Mapping[str, Any]) -> str:
    return norm(packet.get("canonical_name"))


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def build_prompt(packet: Mapping[str, Any]) -> str:
    utype = unit_type(packet)

    common = (
        "You are drafting a grounded Knowledge Library unit for downstream dialogue segmentation, "
        "AI tutor evaluation, and expert review.\n\n"
        "Do not output chain-of-thought. Reason internally, then output only valid JSON.\n"
        "Use only the provided packet. Do not invent facts.\n"
        "Every substantive claim must be linked to evidence IDs or child KC IDs in evidence_map.\n"
        "Prefer concise synthesis over copying. Do not accept fragments as complete drafts.\n"
        "If evidence is partial, mark status as partial and explain the uncertainty.\n"
        "If the packet explicitly declares insufficient_synthesis_support or abstention_expected, abstain instead of inventing unsupported content.\n"
        "For an allowed abstention, keep contextual text empty, keep evidence_map empty, and explain the uncertainty in uncertainty_notes.\n"
        "Return exactly one JSON object. Do not omit top-level fields from the requested schema.\n"
        "Copy knowledge_unit_id, knowledge_unit_type, and canonical_name exactly from the schema.\n"
        "For KC units, always include segmentation_support and evidence_map.\n"
        "For KC units, contextual_kc_draft.text must be at least 180 characters unless status is abstained.\n"
        "For KC units, kc_specific_criteria must be an empty list with expert_pending placeholder metadata.\n\n"
    )

    if utype == "kc":
        schema = {
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": "kc",
            "canonical_name": canonical_name(packet),
            "contextual_kc_draft": {
                "status": "grounded|partial|abstained",
                "text": "integrated, legible, contextually useful KC draft",
                "supporting_evidence_ids": [],
                "coverage_notes": [],
                "uncertainty_notes": [],
            },
            "segmentation_support": {
                "matching_cues": [],
                "likely_dialogue_surface_forms": [],
                "sibling_contrast_notes": [],
                "do_not_confuse_with": [],
            },
            "evaluation_support": {
                "what_tutor_should_explain": [],
                "common_confusions_or_errors": [],
                "acceptable_teaching_moves": [],
                "red_flags": [],
            },
            "evidence_map": [
                {
                    "claim": "claim text",
                    "supporting_evidence_ids": [],
                    "support_strength": "strong|moderate|weak",
                    "support_role": "definition|scope|procedure|formula|example|contrast|context",
                }
            ],
            "kc_specific_criteria": [],
            "kc_specific_criteria_status": "expert_pending",
            "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
        }

        return (
            common
            + "TASK TYPE: KC leaf unit draft.\n"
            + "Strict KC requirements:\n"
            + "- Output all top-level keys shown in the schema.\n"
            + "- Do not return only canonical_name, contextual_kc_draft, and evaluation_support.\n"
            + "- contextual_kc_draft.text should synthesize definition, role, and boundary/procedure context when evidence supports them.\n"
            + "- segmentation_support must contain matching cues and sibling/boundary notes useful for dialogue segmentation.\n"
            + "- evidence_map must contain at least one claim linked to concrete evidence IDs.\n"
            + "- kc_specific_criteria must remain exactly [] because expert criteria are authored later.\n"
            + "Output must follow this JSON shape exactly, with useful filled content:\n"
            + compact_json(schema)
            + "\n\nPACKET:\n"
            + compact_json(packet)
        )

    if utype == "topic":
        schema = {
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": "topic",
            "canonical_name": canonical_name(packet),
            "contextual_topic_draft": {
                "status": "grounded|partial|abstained",
                "text": "integrated topic draft using direct child KCs plus topic evidence",
                "supporting_topic_evidence_ids": [],
                "supporting_child_kc_ids": [],
                "coverage_notes": [],
                "uncertainty_notes": [],
            },
            "child_kc_coverage_summary": {
                "included_child_kcs": [],
                "missing_or_weak_child_kcs": [],
                "topic_boundary_notes": [],
            },
            "segmentation_support": {
                "topic_matching_cues": [],
                "child_kc_boundary_cues": [],
                "do_not_confuse_with_topics": [],
            },
            "evaluation_support": {
                "what_tutor_should_cover_at_topic_level": [],
                "common_topic_level_confusions": [],
                "red_flags": [],
            },
            "evidence_map": [
                {
                    "claim": "claim text",
                    "supporting_topic_evidence_ids": [],
                    "supporting_child_kc_ids": [],
                    "support_strength": "strong|moderate|weak",
                    "support_role": "topic_overview|child_kc_synthesis|scope|contrast|gap",
                }
            ],
            "topic_gap_notes": [],
        }

        return (
            common
            + "TASK TYPE: terminal topic internal node draft.\n"
            + "Use child KC summaries as the backbone. Topic evidence can frame or refine the topic, but do not draft from one topic evidence sentence alone.\n"
            + "Parent topics are not included in this smoke.\n"
            + "Output must follow this JSON shape exactly, with useful filled content:\n"
            + compact_json(schema)
            + "\n\nPACKET:\n"
            + compact_json(packet)
        )

    raise ValueError(f"unsupported knowledge_unit_type: {utype!r}")


def ollama_generate(host: str, model: str, prompt: str, num_ctx: int, timeout_s: int, num_predict: int | None = None) -> Dict[str, Any]:
    url = f"http://{host}/api/generate"
    options: Dict[str, Any] = {
        "temperature": 0,
        "num_ctx": num_ctx,
    }
    if num_predict is not None and int(num_predict) > 0:
        options["num_predict"] = int(num_predict)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": options,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def parse_model_json(raw_response: str) -> Tuple[Dict[str, Any] | None, str]:
    text = raw_response.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None, ""
    except Exception as exc:
        # Conservative fallback: extract outermost JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                return obj if isinstance(obj, dict) else None, ""
            except Exception as exc2:
                return None, f"json_parse_failed: {exc!r}; fallback_failed: {exc2!r}"
        return None, f"json_parse_failed: {exc!r}"


def normalize_draft_from_packet(packet: Mapping[str, Any], draft: Mapping[str, Any] | None) -> Tuple[Mapping[str, Any] | None, List[Dict[str, Any]]]:
    """Normalize deterministic wrapper fields that should not depend on model authorship.

    This intentionally does not fabricate semantic content such as contextual drafts,
    segmentation support, evaluation support, or evidence maps.
    """
    if not isinstance(draft, dict):
        return draft, []

    out: Dict[str, Any] = dict(draft)
    actions: List[Dict[str, Any]] = []

    expected_id = unit_id(packet)
    expected_type = unit_type(packet)
    expected_name = canonical_name(packet)

    for key, expected in [
        ("knowledge_unit_id", expected_id),
        ("knowledge_unit_type", expected_type),
        ("canonical_name", expected_name),
    ]:
        if out.get(key) != expected:
            actions.append({"action": "set_deterministic_wrapper_field", "field": key, "old": out.get(key), "new": expected})
            out[key] = expected

    if expected_type == "kc":
        deterministic_fields = {
            "kc_specific_criteria": [],
            "kc_specific_criteria_status": "expert_pending",
            "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
        }
        for key, expected in deterministic_fields.items():
            if out.get(key) != expected:
                actions.append({"action": "set_deterministic_kc_placeholder", "field": key, "old": out.get(key), "new": expected})
                out[key] = expected
    elif expected_type == "topic":
        for key in ["kc_specific_criteria", "kc_specific_criteria_status", "kc_specific_criteria_source"]:
            if key in out:
                actions.append({"action": "remove_topic_forbidden_kc_specific_field", "field": key, "old": out.get(key)})
                out.pop(key, None)

    return out, actions


def packet_support_state(packet: Mapping[str, Any]) -> str:
    upstream = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), Mapping) else {}
    state = str(packet.get("packet_support_state") or upstream.get("packet_support_state") or "").strip()
    if state:
        return state
    if packet_allows_abstention(packet):
        return "insufficient_support"
    source = str(upstream.get("packet_evidence_source") or "")
    if source == "step66_overlay_target_bound_fallback":
        return "weak_fallback"
    if source:
        return "draftable"
    return ""


def draft_declares_evidence_insufficient(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    utype = unit_type(packet)
    if utype == "kc":
        contextual = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    elif utype == "topic":
        contextual = draft.get("contextual_topic_draft") if isinstance(draft.get("contextual_topic_draft"), Mapping) else {}
    else:
        return False

    if str(contextual.get("status") or "").lower() != "abstained":
        return False

    notes = contextual.get("uncertainty_notes") or []
    if not isinstance(notes, list):
        notes = [notes]

    evidence_ids = []
    for item in packet.get("evidence_for_synthesis") or []:
        if isinstance(item, Mapping) and item.get("evidence_id"):
            evidence_ids.append(str(item.get("evidence_id")))

    blob = " ".join(str(x) for x in notes if str(x)).lower()
    if not blob.strip():
        return False

    evidence_words = ("evidence", "provided", "source", "support", "context", "packet", "passage", "text")
    insufficiency_words = (
        "insufficient", "not enough", "no ", "none", "missing", "unsupported", "does not", "do not",
        "cannot", "unable", "lacks", "lack", "no definition", "no descriptive", "not support"
    )

    mentions_evidence = any(word in blob for word in evidence_words) or any(eid and eid.lower() in blob for eid in evidence_ids)
    mentions_insufficiency = any(word in blob for word in insufficiency_words)
    return mentions_evidence and mentions_insufficiency


def draft_abstention_is_validation_allowed(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    if not isinstance(draft, Mapping):
        return False

    utype = unit_type(packet)
    if utype == "kc":
        contextual = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    elif utype == "topic":
        contextual = draft.get("contextual_topic_draft") if isinstance(draft.get("contextual_topic_draft"), Mapping) else {}
    else:
        return False

    if str(contextual.get("status") or "").lower() != "abstained":
        return False

    if packet_allows_abstention(packet):
        return True

    return packet_support_state(packet) == "weak_fallback" and draft_declares_evidence_insufficient(packet, draft)


def schema_repair_allowed_issue_codes() -> set[str]:
    return {
        "segmentation_support_missing",
        "evaluation_support_missing",
        "evidence_map_missing_or_empty",
    }


def should_attempt_schema_repair(packet: Mapping[str, Any], draft: Mapping[str, Any] | None, validation_issues: List[Dict[str, Any]]) -> bool:
    if unit_type(packet) != "kc":
        return False
    if not isinstance(draft, Mapping) or not validation_issues:
        return False

    issue_codes = {str(x.get("code") or "") for x in validation_issues if isinstance(x, Mapping)}
    if not issue_codes or not issue_codes.issubset(schema_repair_allowed_issue_codes()):
        return False

    ck = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    if str(ck.get("status") or "").lower() == "abstained":
        return False
    if len(norm(ck.get("text"))) < 180:
        return False
    if not isinstance(ck.get("supporting_evidence_ids"), list) or not ck.get("supporting_evidence_ids"):
        return False

    return True


def build_required_output_schema(packet: Mapping[str, Any]) -> Dict[str, Any]:
    if unit_type(packet) == "topic":
        return {
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": "topic",
            "canonical_name": canonical_name(packet),
            "contextual_topic_draft": {
                "status": "grounded|partial|abstained",
                "text": "topic-level context text",
                "supporting_evidence_ids": [],
                "coverage_notes": [],
                "uncertainty_notes": [],
            },
            "child_kc_summaries": [
                {
                    "child_kc_id": "child KC id",
                    "child_kc_name": "child KC name",
                    "summary": "brief child summary",
                    "supporting_evidence_ids": [],
                }
            ],
            "evaluation_support": {
                "what_tutor_should_explain": [],
                "common_confusions_or_errors": [],
                "acceptable_teaching_moves": [],
                "red_flags": [],
            },
            "evidence_map": [
                {
                    "claim": "claim text",
                    "supporting_evidence_ids": [],
                    "support_strength": "strong|moderate|weak",
                    "support_role": "definition|scope|procedure|formula|example|contrast|context",
                }
            ],
        }

    return {
        "knowledge_unit_id": unit_id(packet),
        "knowledge_unit_type": "kc",
        "canonical_name": canonical_name(packet),
        "contextual_kc_draft": {
            "status": "grounded|partial|abstained",
            "text": "KC draft text, or empty only when status is abstained and abstention is allowed",
            "supporting_evidence_ids": [],
            "coverage_notes": [],
            "uncertainty_notes": [],
        },
        "segmentation_support": {
            "matching_cues": [],
            "likely_dialogue_surface_forms": [],
            "sibling_contrast_notes": [],
            "do_not_confuse_with": [],
        },
        "evaluation_support": {
            "what_tutor_should_explain": [],
            "common_confusions_or_errors": [],
            "acceptable_teaching_moves": [],
            "red_flags": [],
        },
        "evidence_map": [
            {
                "claim": "claim text",
                "supporting_evidence_ids": [],
                "support_strength": "strong|moderate|weak",
                "support_role": "definition|scope|procedure|formula|example|contrast|context",
            }
        ],
        "kc_specific_criteria": [],
        "kc_specific_criteria_status": "expert_pending",
        "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
    }


def build_parse_repair_prompt(packet: Mapping[str, Any], raw_response: str, parse_error: str) -> str:
    schema = build_required_output_schema(packet)

    clipped_raw = raw_response
    if len(clipped_raw) > 18000:
        clipped_raw = clipped_raw[:18000] + "\n...[TRUNCATED_RAW_RESPONSE_FOR_REPAIR]..."

    return (
        "You are repairing a malformed JSON response for a Knowledge Library drafting task.\n"
        "The previous response was not valid JSON. Your job is NOT to create a new draft from scratch.\n"
        "Recover the intended content from the malformed response where possible, use the packet only to fill missing required fields, and return exactly one complete valid JSON object.\n"
        "Do not include markdown, comments, explanations, or extra text outside JSON.\n"
        "Do not duplicate keys. Each object key must appear only once.\n"
        "Do not leave strings unfinished. Close every string, array, and object.\n"
        "Keep the heavy contract: include all required fields from the schema.\n"
        "If the source evidence is insufficient and packet policy allows abstention, output status='abstained' with empty text and clear uncertainty notes.\n\n"
        "PARSE_ERROR:\n"
        + str(parse_error)
        + "\n\nREQUIRED_SCHEMA:\n"
        + compact_json(schema)
        + "\n\nMALFORMED_RESPONSE:\n"
        + clipped_raw
        + "\n\nPACKET:\n"
        + compact_json(packet)
    )


def build_schema_repair_prompt(packet: Mapping[str, Any], draft: Mapping[str, Any], validation_issues: List[Dict[str, Any]]) -> str:
    schema = {
        "knowledge_unit_id": unit_id(packet),
        "knowledge_unit_type": "kc",
        "canonical_name": canonical_name(packet),
        "contextual_kc_draft": {
            "status": "grounded|partial|abstained",
            "text": "keep the existing contextual draft text unless it is malformed",
            "supporting_evidence_ids": [],
            "coverage_notes": [],
            "uncertainty_notes": [],
        },
        "segmentation_support": {
            "matching_cues": [],
            "likely_dialogue_surface_forms": [],
            "sibling_contrast_notes": [],
            "do_not_confuse_with": [],
        },
        "evaluation_support": {
            "what_tutor_should_explain": [],
            "common_confusions_or_errors": [],
            "acceptable_teaching_moves": [],
            "red_flags": [],
        },
        "evidence_map": [
            {
                "claim": "claim text",
                "supporting_evidence_ids": [],
                "support_strength": "strong|moderate|weak",
                "support_role": "definition|scope|procedure|formula|example|contrast|context",
            }
        ],
        "kc_specific_criteria": [],
        "kc_specific_criteria_status": "expert_pending",
        "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
    }

    return (
        "You are repairing a structured JSON draft for a Knowledge Library KC unit.\n"
        "The previous answer contains useful grounded contextual text but omitted required structure.\n"
        "Do not add unsupported claims. Use only the packet and previous draft.\n"
        "Keep contextual_kc_draft.text unchanged unless it is malformed.\n"
        "Fill only missing or incomplete structural fields: segmentation_support, evaluation_support, and evidence_map.\n"
        "Every evidence_map item must link a concise claim to evidence IDs from contextual_kc_draft.supporting_evidence_ids or packet evidence_for_synthesis.\n"
        "Return exactly one valid JSON object matching this schema.\n\n"
        "VALIDATION_ISSUES:\n"
        + compact_json(validation_issues)
        + "\n\nREQUIRED_SCHEMA:\n"
        + compact_json(schema)
        + "\n\nPREVIOUS_DRAFT:\n"
        + compact_json(draft)
        + "\n\nPACKET:\n"
        + compact_json(packet)
    )


def packet_allows_abstention(packet: Mapping[str, Any]) -> bool:
    upstream = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), Mapping) else {}
    return bool(
        packet.get("abstention_expected")
        or packet.get("insufficient_synthesis_support")
        or upstream.get("abstention_expected")
        or upstream.get("insufficient_synthesis_support")
    )


def validate_output(packet: Mapping[str, Any], draft: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if not isinstance(draft, dict):
        return [{"code": "missing_or_invalid_draft_json"}]

    if draft.get("knowledge_unit_id") != unit_id(packet):
        issues.append({"code": "knowledge_unit_id_mismatch", "expected": unit_id(packet), "actual": draft.get("knowledge_unit_id")})
    if draft.get("knowledge_unit_type") != unit_type(packet):
        issues.append({"code": "knowledge_unit_type_mismatch", "expected": unit_type(packet), "actual": draft.get("knowledge_unit_type")})

    utype = unit_type(packet)
    abstention_allowed_for_validation = draft_abstention_is_validation_allowed(packet, draft)
    if utype == "kc":
        ck = draft.get("contextual_kc_draft")
        ck_status = str(ck.get("status") or "").lower() if isinstance(ck, dict) else ""
        kc_abstention_is_valid = abstention_allowed_for_validation and ck_status == "abstained"
        if not kc_abstention_is_valid and (not isinstance(ck, dict) or len(norm(ck.get("text"))) < 180):
            issues.append({"code": "kc_contextual_draft_missing_or_too_short"})
        if draft.get("kc_specific_criteria") != []:
            issues.append({"code": "kc_specific_criteria_not_empty"})
        if draft.get("kc_specific_criteria_status") != "expert_pending":
            issues.append({"code": "kc_specific_criteria_status_wrong"})
        if draft.get("kc_specific_criteria_source") != "deterministic_placeholder_not_model_authored":
            issues.append({"code": "kc_specific_criteria_source_wrong"})
        for key in ["segmentation_support", "evaluation_support"]:
            if not isinstance(draft.get(key), dict):
                issues.append({"code": f"{key}_missing"})
    elif utype == "topic":
        ct = draft.get("contextual_topic_draft")
        if not isinstance(ct, dict) or len(norm(ct.get("text"))) < 220:
            issues.append({"code": "topic_contextual_draft_missing_or_too_short"})
        child_summary = draft.get("child_kc_coverage_summary")
        if not isinstance(child_summary, dict):
            issues.append({"code": "child_kc_coverage_summary_missing"})
        if "kc_specific_criteria" in draft:
            issues.append({"code": "topic_must_not_include_kc_specific_criteria"})
        # Terminal topic must cite at least one child KC unless it abstains.
        if isinstance(ct, dict) and ct.get("status") != "abstained":
            if not ct.get("supporting_child_kc_ids"):
                issues.append({"code": "topic_draft_missing_supporting_child_kc_ids"})
    else:
        issues.append({"code": "unsupported_unit_type", "unit_type": utype})

    ev_map = draft.get("evidence_map")
    abstained_status = False
    if utype == "kc":
        ck = draft.get("contextual_kc_draft")
        abstained_status = isinstance(ck, dict) and str(ck.get("status") or "").lower() == "abstained"
    elif utype == "topic":
        ct = draft.get("contextual_topic_draft")
        abstained_status = isinstance(ct, dict) and str(ct.get("status") or "").lower() == "abstained"

    if (not isinstance(ev_map, list) or not ev_map) and not (draft_abstention_is_validation_allowed(packet, draft) and abstained_status):
        issues.append({"code": "evidence_map_missing_or_empty"})
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-json", required=True, type=pathlib.Path)
    ap.add_argument("--selected-packets-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model", default=os.environ.get("KC_L_PROFILE_MODEL", "gemma4:31b"))
    ap.add_argument("--num-ctx", type=int, default=int(os.environ.get("OLLAMA_CONTEXT_LENGTH", "65536")))
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--num-predict", type=int, default=int(os.environ.get("KC_L_STEP67_V2_NUM_PREDICT", "3072")))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    plan = read_json(args.plan_json)
    packets, invalid = read_jsonl(args.selected_packets_jsonl)
    if invalid:
        raise SystemExit(f"selected packet JSONL has invalid rows: {invalid}")
    if not plan.get("ready_to_submit_tiny_smoke"):
        raise SystemExit(f"plan not ready: {plan.get('decision')}")

    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").replace("http://", "").replace("https://", "")
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    drafts_jsonl = args.out_dir / "step67_v2_tiny_smoke_drafts.jsonl"
    progress_json = args.out_dir / "STEP67_V2_TINY_SMOKE_PROGRESS.json"

    start = time.time()
    for i, packet in enumerate(packets, start=1):
        prompt = build_prompt(packet)
        call_start = time.time()
        try:
            api = ollama_generate(host, args.model, prompt, args.num_ctx, args.timeout_s, args.num_predict)
            call_elapsed = time.time() - call_start
        except Exception as exc:
            call_elapsed = time.time() - call_start
            runtime_error = f"{exc.__class__.__name__}: {exc!r}"
            validation_issues = [{"code": "model_call_failed", "error": runtime_error}]
            row = {
                "run_id": args.run_id,
                "created_utc": now_utc(),
                "knowledge_unit_id": unit_id(packet),
                "knowledge_unit_type": unit_type(packet),
                "canonical_name": canonical_name(packet),
                "packet_index": i,
                "model": args.model,
                "ollama_host": host,
                "num_ctx": args.num_ctx,
                "num_predict": args.num_predict,
                "prompt_chars": len(prompt),
                "raw_response_chars": 0,
                "call_elapsed_seconds": round(call_elapsed, 3),
                "ollama_metadata": {},
                "draft": None,
                "parse_error": runtime_error,
                "normalization_actions": [],
                "repair_attempted": False,
                "repair_parse_error": "",
                "repair_validation_issues_before": [],
                "repair_normalization_actions": [],
                "raw_response": "",
                "repair_raw_response": "",
                "validation_issues": validation_issues,
                "runtime_error": runtime_error,
                "source_packet": packet,
            }
            rows.append(row)
            failures.append({
                "knowledge_unit_id": unit_id(packet),
                "knowledge_unit_type": unit_type(packet),
                "canonical_name": canonical_name(packet),
                "parse_error": runtime_error,
                "validation_issues": validation_issues,
            })
            write_jsonl(drafts_jsonl, rows)
            progress_json.write_text(json.dumps({
                "run_id": args.run_id,
                "created_utc": now_utc(),
                "processed_count": len(rows),
                "selected_packet_count": len(packets),
                "failure_count": len(failures),
                "last_packet_index": i,
                "last_packet_id": unit_id(packet),
                "last_runtime_error": runtime_error,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            continue

        raw = str(api.get("response") or "")
        parsed, parse_error = parse_model_json(raw)

        parse_repair_attempted = False
        parse_repair_parse_error = ""
        parse_repair_raw_response = ""
        parse_repair_validation_issues: List[Dict[str, Any]] = []

        if parse_error:
            parse_repair_attempted = True
            parse_repair_prompt = build_parse_repair_prompt(packet, raw, parse_error)
            try:
                parse_repair_api = ollama_generate(host, args.model, parse_repair_prompt, args.num_ctx, args.timeout_s, args.num_predict)
                parse_repair_raw_response = str(parse_repair_api.get("response") or "")
                parse_repaired_parsed, parse_repair_parse_error = parse_model_json(parse_repair_raw_response)
                if not parse_repair_parse_error:
                    parsed = parse_repaired_parsed
                    parse_error = ""
            except Exception as exc:
                parse_repair_parse_error = f"{exc.__class__.__name__}: {exc!r}"

        normalized, normalization_actions = normalize_draft_from_packet(packet, parsed)
        validation_issues = validate_output(packet, normalized)

        repair_attempted = False
        repair_parse_error = ""
        repair_raw_response = ""
        repair_validation_issues_before = list(validation_issues)
        repair_normalization_actions: List[Dict[str, Any]] = []

        if not parse_error and should_attempt_schema_repair(packet, normalized, validation_issues):
            repair_attempted = True
            repair_prompt = build_schema_repair_prompt(packet, normalized, validation_issues)
            repair_api = ollama_generate(host, args.model, repair_prompt, args.num_ctx, args.timeout_s, args.num_predict)
            repair_raw_response = str(repair_api.get("response") or "")
            repair_parsed, repair_parse_error = parse_model_json(repair_raw_response)
            repaired, repair_normalization_actions = normalize_draft_from_packet(packet, repair_parsed)
            repair_validation_issues = validate_output(packet, repaired)

            if not repair_parse_error and not repair_validation_issues:
                normalized = repaired
                validation_issues = []
                for action in repair_normalization_actions:
                    tagged = dict(action)
                    tagged["phase"] = "schema_repair"
                    normalization_actions.append(tagged)
            else:
                validation_issues = repair_validation_issues or validation_issues

        row = {
            "run_id": args.run_id,
            "created_utc": now_utc(),
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": unit_type(packet),
            "canonical_name": canonical_name(packet),
            "packet_index": i,
            "model": args.model,
            "ollama_host": host,
            "num_ctx": args.num_ctx,
            "prompt_chars": len(prompt),
            "raw_response_chars": len(raw),
            "call_elapsed_seconds": round(call_elapsed, 3),
            "ollama_metadata": {k: v for k, v in api.items() if k != "response"},
            "draft": normalized,
            "parse_error": parse_error,
            "normalization_actions": normalization_actions,
            "parse_repair_attempted": parse_repair_attempted,
            "parse_repair_parse_error": parse_repair_parse_error,
            "parse_repair_validation_issues": parse_repair_validation_issues,
            "parse_repair_raw_response": parse_repair_raw_response if (parse_repair_parse_error or validation_issues) else "",
            "repair_attempted": repair_attempted,
            "repair_parse_error": repair_parse_error,
            "repair_validation_issues_before": repair_validation_issues_before,
            "repair_normalization_actions": repair_normalization_actions,
            "raw_response": raw if (parse_error or validation_issues) else "",
            "repair_raw_response": repair_raw_response if (repair_parse_error or validation_issues) else "",
            "validation_issues": validation_issues,
            "source_packet": packet,
        }
        rows.append(row)
        if parse_error or validation_issues:
            failures.append({
                "knowledge_unit_id": unit_id(packet),
                "knowledge_unit_type": unit_type(packet),
                "canonical_name": canonical_name(packet),
                "parse_error": parse_error,
                "validation_issues": validation_issues,
            })

        write_jsonl(drafts_jsonl, rows)
        progress_json.write_text(json.dumps({
            "run_id": args.run_id,
            "created_utc": now_utc(),
            "processed_count": len(rows),
            "selected_packet_count": len(packets),
            "failure_count": len(failures),
            "last_packet_index": i,
            "last_packet_id": unit_id(packet),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    elapsed = time.time() - start

    write_jsonl(drafts_jsonl, rows)

    summary = {
        "schema_version": "step67_v2_tiny_smoke_summary_v1",
        "created_utc": now_utc(),
        "run_id": args.run_id,
        "decision": "PASS_STEP67_V2_TINY_SMOKE_RUNTIME_READY_FOR_COMPACT_CLOSEOUT" if not failures else "FAIL_STEP67_V2_TINY_SMOKE_RUNTIME_OR_SCHEMA",
        "ready_for_compact_closeout": not failures,
        "ready_for_larger_run": False,
        "metrics": {
            "selected_packet_count": len(packets),
            "draft_row_count": len(rows),
            "failure_count": len(failures),
            "model_call_failed_count": sum(1 for r in rows for issue in (r.get("validation_issues") or []) if isinstance(issue, dict) and issue.get("code") == "model_call_failed"),
            "parse_repair_attempt_count": sum(1 for r in rows if r.get("parse_repair_attempted")),
            "parse_repair_success_count": sum(1 for r in rows if r.get("parse_repair_attempted") and not r.get("parse_error")),
            "schema_repair_attempt_count": sum(1 for r in rows if r.get("repair_attempted")),
            "schema_repair_success_count": sum(1 for r in rows if r.get("repair_attempted") and not r.get("validation_issues")),
            "unit_type_counter": {t: sum(1 for r in rows if r["knowledge_unit_type"] == t) for t in sorted(set(r["knowledge_unit_type"] for r in rows))},
            "elapsed_seconds": round(elapsed, 3),
            "model": args.model,
            "num_ctx": args.num_ctx,
            "ollama_host": host,
            "total_prompt_chars": sum(r["prompt_chars"] for r in rows),
            "total_raw_response_chars": sum(r["raw_response_chars"] for r in rows),
        },
        "source_paths": {
            "plan_json": str(args.plan_json),
            "selected_packets_jsonl": str(args.selected_packets_jsonl),
        },
        "artifacts": {
            "drafts_jsonl": str(drafts_jsonl),
        },
        "failures": failures,
        "policy": {
            "parent_topics_excluded": True,
            "kc_specific_criteria_model_authorship_forbidden": True,
            "topics_must_not_include_kc_specific_criteria": True,
            "claim_evidence_map_required": True,
        },
    }

    summary_json = args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.json"
    write_json(summary_json, summary)

    md = [
        "# Step6.7 v2 tiny smoke summary",
        "",
        f"- decision: `{summary['decision']}`",
        f"- ready_for_compact_closeout: `{summary['ready_for_compact_closeout']}`",
        "- ready_for_larger_run: `False`",
        f"- selected_packet_count: `{len(packets)}`",
        f"- draft_row_count: `{len(rows)}`",
        f"- failure_count: `{len(failures)}`",
        f"- model: `{args.model}`",
        f"- num_ctx: `{args.num_ctx}`",
        "",
        "## Failures",
    ]
    md += [f"- `{f['knowledge_unit_id']}`: {json.dumps(f, ensure_ascii=False)}" for f in failures] if failures else ["- none"]
    (args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("===== STEP6.7 V2 TINY SMOKE RUNTIME SUMMARY =====")
    print(json.dumps({
        "decision": summary["decision"],
        "ready_for_compact_closeout": summary["ready_for_compact_closeout"],
        "ready_for_larger_run": False,
        "selected_packet_count": len(packets),
        "draft_row_count": len(rows),
        "failure_count": len(failures),
        "metrics": summary["metrics"],
        "summary_json": str(summary_json),
        "summary_md": str(args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.md"),
        "drafts_jsonl": str(drafts_jsonl),
    }, indent=2, ensure_ascii=False))
    print("STEP67_V2_TINY_SMOKE_RUNTIME_SUMMARY_JSON=" + str(summary_json))
    print("STEP67_V2_TINY_SMOKE_RUNTIME_SUMMARY_MD=" + str(args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.md"))
    print("STEP67_V2_TINY_SMOKE_DRAFTS_JSONL=" + str(drafts_jsonl))
    print("STEP67_V2_TINY_SMOKE_RUNTIME_COMPLETE")

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
