from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import time
import urllib.request
from typing import Any, Dict, List, Mapping


def now_utc() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def read_jsonl(path: pathlib.Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: pathlib.Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def unit_id(packet: Mapping[str, Any]) -> str:
    return str(packet.get("knowledge_unit_id") or packet.get("kc_id") or packet.get("topic_id") or "")


def unit_type(packet: Mapping[str, Any]) -> str:
    return str(packet.get("knowledge_unit_type") or "")


def canonical_name(packet: Mapping[str, Any]) -> str:
    return str(packet.get("canonical_name") or packet.get("name") or packet.get("title") or "")


def schema_string_array() -> Dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"}
    }


def schema_evidence_map() -> Dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["claim", "supporting_evidence_ids", "support_strength", "support_role"],
            "properties": {
                "claim": {"type": "string"},
                "supporting_evidence_ids": schema_string_array(),
                "support_strength": {"type": "string", "enum": ["strong", "moderate", "weak"]},
                "support_role": {
                    "type": "string",
                    "enum": ["definition", "scope", "procedure", "formula", "example", "contrast", "context"]
                },
            },
            "additionalProperties": False,
        },
    }


def schema_evaluation_support() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "what_tutor_should_explain",
            "common_confusions_or_errors",
            "acceptable_teaching_moves",
            "red_flags",
        ],
        "properties": {
            "what_tutor_should_explain": schema_string_array(),
            "common_confusions_or_errors": schema_string_array(),
            "acceptable_teaching_moves": schema_string_array(),
            "red_flags": schema_string_array(),
        },
        "additionalProperties": False,
    }


def kc_json_schema(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "knowledge_unit_id",
            "knowledge_unit_type",
            "canonical_name",
            "contextual_kc_draft",
            "segmentation_support",
            "evaluation_support",
            "evidence_map",
            "kc_specific_criteria",
            "kc_specific_criteria_status",
            "kc_specific_criteria_source",
        ],
        "properties": {
            "knowledge_unit_id": {"type": "string"},
            "knowledge_unit_type": {"type": "string", "enum": ["kc"]},
            "canonical_name": {"type": "string"},
            "contextual_kc_draft": {
                "type": "object",
                "required": [
                    "status",
                    "text",
                    "supporting_evidence_ids",
                    "coverage_notes",
                    "uncertainty_notes",
                ],
                "properties": {
                    "status": {"type": "string", "enum": ["grounded", "partial", "abstained"]},
                    "text": {"type": "string"},
                    "supporting_evidence_ids": schema_string_array(),
                    "coverage_notes": schema_string_array(),
                    "uncertainty_notes": schema_string_array(),
                },
                "additionalProperties": False,
            },
            "segmentation_support": {
                "type": "object",
                "required": [
                    "matching_cues",
                    "likely_dialogue_surface_forms",
                    "sibling_contrast_notes",
                    "do_not_confuse_with",
                ],
                "properties": {
                    "matching_cues": schema_string_array(),
                    "likely_dialogue_surface_forms": schema_string_array(),
                    "sibling_contrast_notes": schema_string_array(),
                    "do_not_confuse_with": schema_string_array(),
                },
                "additionalProperties": False,
            },
            "evaluation_support": schema_evaluation_support(),
            "evidence_map": schema_evidence_map(),
            "kc_specific_criteria": {"type": "array", "items": {"type": "object"}},
            "kc_specific_criteria_status": {"type": "string"},
            "kc_specific_criteria_source": {"type": "string"},
        },
        "additionalProperties": False,
    }


def topic_json_schema(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "knowledge_unit_id",
            "knowledge_unit_type",
            "canonical_name",
            "contextual_topic_draft",
            "child_kc_summaries",
            "evaluation_support",
            "evidence_map",
        ],
        "properties": {
            "knowledge_unit_id": {"type": "string"},
            "knowledge_unit_type": {"type": "string", "enum": ["topic"]},
            "canonical_name": {"type": "string"},
            "contextual_topic_draft": {
                "type": "object",
                "required": [
                    "status",
                    "text",
                    "supporting_evidence_ids",
                    "coverage_notes",
                    "uncertainty_notes",
                ],
                "properties": {
                    "status": {"type": "string", "enum": ["grounded", "partial", "abstained"]},
                    "text": {"type": "string"},
                    "supporting_evidence_ids": schema_string_array(),
                    "coverage_notes": schema_string_array(),
                    "uncertainty_notes": schema_string_array(),
                },
                "additionalProperties": False,
            },
            "child_kc_summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["child_kc_id", "child_kc_name", "summary", "supporting_evidence_ids"],
                    "properties": {
                        "child_kc_id": {"type": "string"},
                        "child_kc_name": {"type": "string"},
                        "summary": {"type": "string"},
                        "supporting_evidence_ids": schema_string_array(),
                    },
                    "additionalProperties": False,
                },
            },
            "evaluation_support": schema_evaluation_support(),
            "evidence_map": schema_evidence_map(),
        },
        "additionalProperties": False,
    }


def output_schema(packet: Mapping[str, Any]) -> Dict[str, Any]:
    if unit_type(packet) == "topic":
        return topic_json_schema(packet)
    return kc_json_schema(packet)


def load_base_runner(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("run_step67_v2_tiny_smoke_base", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def ollama_generate_schema(
    host: str,
    model: str,
    prompt: str,
    schema: Mapping[str, Any],
    num_ctx: int,
    timeout_s: int,
    num_predict: int,
    seed: int | None = None,
) -> Dict[str, Any]:
    # 2026-07-28 fix: this call hand-rolls its own /api/generate request instead of going
    # through kc_l.retrieval_profile.model_client.ollama_chat_json() - it never picked up that
    # module's seed fix (made earlier this week for step_05p). temperature=0 alone does not
    # guarantee reproducibility (missing seed, plus GPU floating-point non-associativity as a
    # separate residual risk - same reasoning as the step_05p fix). Confirmed via direct trace
    # this week: 3 of 4 investigated false-negative KCs had byte-identical candidate pools and
    # scores between two runs, yet different final drafting outcomes - this call site, not
    # retrieval, is the most likely explanation.
    # 2026-07-31 fix: `ollama show` confirms each model carries its own, DIFFERENT Modelfile
    # sampling defaults for every option not explicitly set here (e.g. gemma4:31b: top_k=64,
    # presence_penalty unset/0; qwen3.6:27b: top_k=20, presence_penalty=1.5, repeat_penalty=1,
    # min_p=0) - temperature=0 alone does not neutralize presence_penalty (it still reshapes
    # logits before argmax selection, unlike top_k/top_p/min_p which stop mattering once
    # decoding is genuinely greedy). Leaving these unset meant every model swap silently ran
    # under different generation conditions beyond just the model weights - not a fair,
    # single-variable ablation. Pinning all of them to fixed, neutral (no-op) values makes the
    # model name the only thing that differs between calls, matching this project's own
    # single-variable-ablation discipline.
    options: Dict[str, Any] = {
        "temperature": 0,
        "top_k": 100,
        "top_p": 1.0,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repeat_penalty": 1.0,
        "num_ctx": int(num_ctx),
        "num_predict": int(num_predict),
    }
    if seed is not None:
        options["seed"] = int(seed)
    url = f"http://{host}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": dict(schema),
        # 2026-07-31 fix (confirmed real incident, Ablation 2 job 236969, all 181/181 units
        # failed): this is the ACTUAL, live call site for every real step_06_7 drafting run
        # (not scripts/experimental/run_step67_v2_tiny_smoke.py's own ollama_generate(), which
        # this file's caller never invokes for generation - confirmed by tracing run()'s main
        # loop, which calls this function exclusively). Reasoning-capable models (confirmed via
        # `ollama show` listing "thinking" - qwen3.6:27b, gemma4:12b) return their entire answer
        # in a separate "thinking" field instead of "response" when this isn't explicitly
        # disabled, even under schema-constrained format (confirmed directly: same prompt/schema,
        # think=True put a complete, valid draft in response.thinking with response.response
        # empty; think=False put the identical valid draft in response.response as required).
        # General, not model-specific - any future reasoning-capable model swapped in here would
        # hit the same empty-response failure without this. Ollama accepts "think" as a no-op for
        # models without the capability, so this is safe unconditionally.
        "think": False,
        "options": options,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def make_prompt(base_mod: Any, packet: Mapping[str, Any], schema: Mapping[str, Any],
                 mode: str = "native_proposed") -> str:
    prompt = base_mod.build_prompt(packet, mode=mode)
    return (
        prompt
        + "\n\nSTRICT STRUCTURED OUTPUT REQUIREMENT:\n"
        + "The API call supplies a JSON Schema in the format parameter. Return exactly one JSON object conforming to that schema.\n"
        + "Do not repeat keys. Do not emit markdown. Do not add fields outside the schema.\n"
        + "The heavy contract is required: contextual draft, segmentation support, evaluation support, evidence map, and placeholder criteria fields for KC rows must be present.\n"
        + "If evidence is insufficient and packet policy allows abstention, output status='abstained'. Otherwise produce a grounded or partial draft using only source evidence.\n"
        + "\nJSON_SCHEMA_FOR_REFERENCE:\n"
        + compact_json(schema)
    )


def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-runner", required=True)
    ap.add_argument("--selected-packets-jsonl", required=True)
    ap.add_argument("--plan-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--num-predict", type=int, default=16000)
    ap.add_argument("--timeout-s", type=int, default=1200)
    ap.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--prompt-mode", default="native_proposed",
                     choices=("native_proposed", "controlled_comparator"))
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    drafts_jsonl = out_dir / "step67_v2_tiny_smoke_drafts.jsonl"
    summary_json = out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.json"
    progress_json = out_dir / "STEP67_V2_TINY_SMOKE_PROGRESS.json"

    base_mod = load_base_runner(pathlib.Path(args.base_runner))
    packets = read_jsonl(pathlib.Path(args.selected_packets_jsonl))

    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    start = time.time()

    for i, packet in enumerate(packets, 1):
        schema = output_schema(packet)
        prompt = make_prompt(base_mod, packet, schema, mode=args.prompt_mode)
        call_start = time.time()

        runtime_error = ""
        raw = ""
        api: Dict[str, Any] = {}

        try:
            api = ollama_generate_schema(
                args.ollama_host,
                args.model,
                prompt,
                schema,
                args.num_ctx,
                args.timeout_s,
                args.num_predict,
                seed=args.seed,
            )
            raw = str(api.get("response") or "")
            call_elapsed = time.time() - call_start
        except Exception as exc:
            call_elapsed = time.time() - call_start
            runtime_error = f"{exc.__class__.__name__}: {exc!r}"

        if runtime_error:
            normalized = None
            parse_error = runtime_error
            normalization_actions: List[Dict[str, Any]] = []
            validation_issues = [{"code": "model_call_failed", "error": runtime_error}]
        else:
            parsed, parse_error = base_mod.parse_model_json(raw)

            parse_repair_attempted = False
            parse_repair_parse_error = ""
            parse_repair_raw_response = ""

            if parse_error and hasattr(base_mod, "build_parse_repair_prompt"):
                parse_repair_attempted = True
                repair_prompt = base_mod.build_parse_repair_prompt(packet, raw, parse_error)
                try:
                    repair_api = ollama_generate_schema(
                        args.ollama_host,
                        args.model,
                        repair_prompt,
                        schema,
                        args.num_ctx,
                        args.timeout_s,
                        args.num_predict,
                        seed=args.seed,
                    )
                    parse_repair_raw_response = str(repair_api.get("response") or "")
                    repaired_parsed, parse_repair_parse_error = base_mod.parse_model_json(parse_repair_raw_response)
                    if not parse_repair_parse_error:
                        parsed = repaired_parsed
                        parse_error = ""
                except Exception as exc:
                    parse_repair_parse_error = f"{exc.__class__.__name__}: {exc!r}"
            else:
                parse_repair_attempted = False
                parse_repair_parse_error = ""
                parse_repair_raw_response = ""

            normalized, normalization_actions = base_mod.normalize_draft_from_packet(packet, parsed)
            validation_issues = base_mod.validate_output(packet, normalized)

            # 2026-08-17: status-integrity gate, wired in HERE because this is the row loop every
            # real drafting job actually executes (confirmed by tracing v3/jobs/02_draft_kc_*.sbatch
            # -> this script --base-runner 04_draft_runner.py). 04_draft_runner.py's own call site
            # for this gate is dead code from this script's perspective: this loop only ever invokes
            # named functions off base_mod via hasattr(), the same pattern used below for schema
            # repair, never 04_draft_runner.py's own main()/module-level code. Verified empirically
            # before this fix: 0 of 159 real audited drafts carried a status_integrity_override.
            if hasattr(base_mod, "apply_status_integrity_gate"):
                normalized, status_integrity_override = base_mod.apply_status_integrity_gate(packet, normalized)
                if isinstance(status_integrity_override, dict):
                    code = status_integrity_override.get("code")
                    if code and hasattr(base_mod, "UNJUSTIFIED_ABSTENTION_CODE") \
                            and code == base_mod.UNJUSTIFIED_ABSTENTION_CODE:
                        # Inverse direction: an abstention the packet never permitted. Never
                        # promotes the status - only surfaces it, since manufacturing confidence on
                        # the model's behalf is the exact failure this gate exists to prevent.
                        validation_issues = list(validation_issues or []) + [{
                            "code": code,
                            "admitted_evidence_count": status_integrity_override.get("admitted_evidence_count"),
                            "packet_support_state": status_integrity_override.get("packet_support_state"),
                        }]
                    else:
                        # Forward direction: a positive status with zero real admitted evidence was
                        # just force-corrected to abstained. Re-run validation against the corrected
                        # draft so downstream issue codes reflect the corrected status, not the
                        # model's original (now-overridden) claim.
                        validation_issues = base_mod.validate_output(packet, normalized)

            content_repair_attempted = False
            content_repair_parse_error = ""
            content_repair_raw_response = ""
            content_repair_issues_before = list(validation_issues)
            content_repair_phase = ""

            # Content repairs are driven from base_mod.content_repair_chain() rather than named
            # one at a time here. This loop is the one every real drafting job executes, and
            # naming repairs individually is how two of them - the invalid-abstention repair and
            # the damaged-math repair - came to exist with passing unit tests and never once run:
            # `repair_attempted` was 0 across every audited run. Iterating whatever the runner
            # declares means a repair added there cannot be forgotten here. At most one repair is
            # attempted per row, in the chain's own order.
            for repair in (base_mod.content_repair_chain()
                           if hasattr(base_mod, "content_repair_chain") else ()):
                if parse_error or content_repair_attempted:
                    break
                if not repair.needs_repair(packet, normalized, validation_issues):
                    continue
                content_repair_attempted = True
                content_repair_phase = repair.phase
                content_repair_prompt = repair.build_prompt(packet, normalized, validation_issues)
                try:
                    content_repair_api = ollama_generate_schema(
                        args.ollama_host,
                        args.model,
                        content_repair_prompt,
                        schema,
                        args.num_ctx,
                        args.timeout_s,
                        args.num_predict,
                        seed=args.seed,
                    )
                    content_repair_raw_response = str(content_repair_api.get("response") or "")
                    content_repair_parsed, content_repair_parse_error = base_mod.parse_model_json(content_repair_raw_response)
                    repaired, repair_actions = base_mod.normalize_draft_from_packet(packet, content_repair_parsed)
                    content_repair_validation = base_mod.validate_output(packet, repaired)
                    if base_mod.repair_resolved(repair, packet, repaired,
                                                content_repair_parse_error,
                                                content_repair_validation):
                        normalized = repaired
                        validation_issues = []
                        normalization_actions.extend([
                            dict(action, phase=repair.phase) for action in repair_actions
                        ])
                    else:
                        validation_issues = content_repair_validation or validation_issues
                except Exception as exc:
                    content_repair_parse_error = f"{exc.__class__.__name__}: {exc!r}"

        if runtime_error:
            parse_repair_attempted = False
            parse_repair_parse_error = ""
            parse_repair_raw_response = ""
            content_repair_attempted = False
            content_repair_parse_error = ""
            content_repair_raw_response = ""
            content_repair_issues_before = []
            content_repair_phase = ""

        row = {
            "run_id": args.run_id,
            "created_utc": now_utc(),
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": unit_type(packet),
            "canonical_name": canonical_name(packet),
            "packet_index": i,
            "model": args.model,
            "ollama_host": args.ollama_host,
            "num_ctx": args.num_ctx,
            "num_predict": args.num_predict,
            "format_mode": "json_schema",
            "prompt_chars": len(prompt),
            "raw_response_chars": len(raw),
            "call_elapsed_seconds": round(call_elapsed, 3),
            "ollama_metadata": {k: v for k, v in api.items() if k != "response"} if api else {},
            "draft": normalized,
            "parse_error": parse_error,
            "normalization_actions": normalization_actions,
            "parse_repair_attempted": parse_repair_attempted,
            "parse_repair_parse_error": parse_repair_parse_error,
            "parse_repair_raw_response": parse_repair_raw_response if (parse_repair_parse_error or validation_issues) else "",
            "repair_attempted": content_repair_attempted,
            "repair_phase": content_repair_phase,
            "repair_parse_error": content_repair_parse_error,
            "repair_validation_issues_before": content_repair_issues_before,
            "repair_raw_response": content_repair_raw_response if (content_repair_parse_error or validation_issues) else "",
            "raw_response": raw if (parse_error or validation_issues) else "",
            "validation_issues": validation_issues,
            "runtime_error": runtime_error,
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

    summary = {
        "run_id": args.run_id,
        "created_utc": now_utc(),
        "decision": "PASS_STEP67_V2_SCHEMA_CONTRACT_PROBE" if not failures else "FAIL_STEP67_V2_SCHEMA_CONTRACT_PROBE",
        "ready_for_compact_closeout": not failures,
        "ready_for_larger_run": False,
        "metrics": {
            "selected_packet_count": len(packets),
            "draft_row_count": len(rows),
            "failure_count": len(failures),
            "model_call_failed_count": sum(
                1 for r in rows for issue in (r.get("validation_issues") or [])
                if isinstance(issue, dict) and issue.get("code") == "model_call_failed"
            ),
            "parse_repair_attempt_count": sum(1 for r in rows if r.get("parse_repair_attempted")),
            "parse_repair_success_count": sum(1 for r in rows if r.get("parse_repair_attempted") and not r.get("parse_error")),
            "schema_repair_attempt_count": sum(1 for r in rows if r.get("repair_attempted")),
            "schema_repair_success_count": sum(1 for r in rows if r.get("repair_attempted") and not r.get("validation_issues")),
            "elapsed_seconds": round(elapsed, 3),
        },
        "failures": failures,
        "paths": {
            "drafts_jsonl": str(drafts_jsonl),
            "summary_json": str(summary_json),
            "progress_json": str(progress_json),
        },
    }

    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("STEP67_V2_SCHEMA_CONTRACT_PROBE_COMPLETE")
    print(f"DECISION={summary['decision']}")
    print(f"FAILURE_COUNT={len(failures)}")
    print(f"DRAFT_ROW_COUNT={len(rows)}")
    print(f"SUMMARY_JSON={summary_json}")
    print(f"DRAFTS_JSONL={drafts_jsonl}")
    print(f"PROGRESS_JSON={progress_json}")

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(run())
